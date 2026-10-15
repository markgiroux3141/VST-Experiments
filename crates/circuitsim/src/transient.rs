//! Fixed-step transient analysis of `G x + C x' + d(x) = b(t)`, where `d` are
//! the device currents.
//!
//! The step h is 1 / (oversample x sample rate), and the input is given at
//! every step, so outputs land exactly on the sample grid. The run starts from
//! the DC operating point with the first input sample (capacitors open,
//! inductors shorted), as ngspice's `.tran` does.
//!
//! Trapezoidal rule in companion form, with `q' = C x'` carried as state:
//!
//! ```text
//! (G + 2C/h) x[n+1] + d(x[n+1]) = b[n+1] + 2C/h x[n] + q'[n]
//! q'[n+1] = 2C/h (x[n+1] - x[n]) - q'[n]
//! ```
//!
//! This is SPICE's capacitor/inductor companion model written for the whole
//! matrix. Rows without a C entry (resistive nodes, sources) are solved exactly
//! each step instead of being averaged, so they can't ring. Backward Euler,
//! `(G + C/h) x[n+1] + d(x[n+1]) = b[n+1] + C/h x[n]`, is there for damping
//! stiff modes. Each step is solved by Newton (see `newton.rs`).
//!
//! Newton robustness:
//! - the initial guess is the previous two points extrapolated linearly;
//! - devices limit their own steps (junction limiting);
//! - a step that doesn't converge is retried as two half steps (input
//!   interpolated linearly), recursively up to `max_halvings` times; the
//!   error then names the time, the node and the devices on it;
//! - the DC operating point tries plain Newton, then gmin stepping (a shunt
//!   from every device node to ground, 1e-2 S down to 0), then source
//!   stepping (all sources scaled up from 0), the SPICE homotopies.

use crate::Error;
use crate::ir::CircuitIr;
use crate::mna::{Mna, SPICE_GMIN};
use crate::newton::{Failure, Newton, NewtonOptions, Reduced};

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Method {
    Trapezoidal,
    BackwardEuler,
}

impl Method {
    pub fn parse(name: &str) -> Result<Method, Error> {
        match name {
            "trap" => Ok(Method::Trapezoidal),
            "euler" => Ok(Method::BackwardEuler),
            _ => Err(Error::new(format!(
                "unknown method {name:?} (trap | euler)"
            ))),
        }
    }
}

/// Solver settings.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct Options {
    pub method: Method,
    /// Newton converges when no device-node voltage moves by more than
    /// `reltol * |v| + vntol`. Newton's error after that is about the square
    /// of the last update, far below these.
    ///
    /// vntol can't go much below 1e-6 V (SPICE's default): a node whose
    /// voltage is set by tiny conductances against large ones carries
    /// roundoff of that size, and Newton's updates there never shrink below
    /// it. In the 670 at DC, T104's secondary is a 1 mOhm winding held only
    /// by the bridge diodes' leakage and a 1 GOhm leak: ~1e-6 to 1e-5 V of
    /// roundoff (measured by reordering the unknowns), and ngspice fails to
    /// converge there at reltol 1e-9.
    pub reltol: f64,
    pub vntol: f64,
    /// Newton iterations per step before the step is halved.
    pub max_iter: usize,
    /// Newton iterations per DC attempt (plain, and each homotopy point).
    pub max_iter_dc: usize,
    /// How often a failing step may be halved (2^n substeps at most).
    pub max_halvings: u32,
    /// Conductance across every junction diode (S); SPICE's GMIN by default.
    pub gmin: f64,
    /// Extrapolate the previous two points for Newton's initial guess.
    pub extrapolate: bool,
}

impl Default for Options {
    fn default() -> Self {
        Options {
            method: Method::Trapezoidal,
            reltol: 1e-6,
            vntol: 1e-6,
            max_iter: 50,
            max_iter_dc: 200,
            max_halvings: 8,
            gmin: SPICE_GMIN,
            extrapolate: true,
        }
    }
}

impl Options {
    pub fn with_method(method: Method) -> Options {
        Options {
            method,
            ..Options::default()
        }
    }

    fn check(&self) -> Result<(), Error> {
        let ok = self.reltol.is_finite()
            && self.reltol >= 0.0
            && self.vntol.is_finite()
            && self.vntol > 0.0
            && self.max_iter > 0
            && self.max_iter_dc > 0
            && self.max_halvings <= 30;
        if ok {
            Ok(())
        } else {
            Err(Error::new(format!("invalid solver options {self:?}")))
        }
    }
}

/// Solver statistics of a run.
#[derive(Debug, Clone, Default, PartialEq)]
pub struct Stats {
    /// Time steps taken at the full step size, and as substeps.
    pub steps: u64,
    pub substeps: u64,
    /// Steps that had to be halved at least once.
    pub halved_steps: u64,
    /// Newton iterations over all steps (DC excluded).
    pub iterations: u64,
    pub max_iterations: usize,
    /// How the DC operating point was found: "newton", "gmin" or "source".
    pub dc_method: &'static str,
    pub dc_iterations: usize,
    /// Size of the Newton system and of the eliminated linear block.
    pub nonlinear_unknowns: usize,
    pub linear_unknowns: usize,
}

/// A transient run in progress; `step` advances it one sample.
#[derive(Debug)]
pub struct Transient {
    mna: Mna,
    opts: Options,
    h: f64,
    device_nodes: Vec<usize>,
    newton: Newton,
    /// Reduced step matrix per halving level (built on first use).
    levels: Vec<Option<Reduced>>,
    x: Vec<f64>,
    x_prev: Vec<f64>,
    /// Step that led to `x` (0 before the first step: nothing to extrapolate).
    h_prev: f64,
    cx: Vec<f64>,
    qdot: Vec<f64>,
    /// Port voltages of every device at `x` (layout of `Newton::v_lin`).
    ports: Vec<f64>,
    u: f64,
    /// Samples stepped so far (the sample index of `x`).
    n: u64,
    stats: Stats,
    // Scratch.
    rhs: Vec<f64>,
    y: Vec<f64>,
    rn: Vec<f64>,
    xn: Vec<f64>,
    x_new: Vec<f64>,
    cx_new: Vec<f64>,
    work: Vec<f64>,
}

impl Transient {
    /// Solve the DC operating point with input `u0`, ready to step by `h`.
    pub fn new(mna: Mna, h: f64, opts: Options, u0: f64) -> Result<Transient, Error> {
        if !(h.is_finite() && h > 0.0) {
            return Err(Error::new(format!("time step {h} must be > 0")));
        }
        opts.check()?;
        let n = mna.len();
        let mut device_nodes = Vec::new();
        for d in &mna.devices {
            for &p in d.pins.iter().flatten() {
                if !device_nodes.contains(&p) {
                    device_nodes.push(p);
                }
            }
        }
        let newton = Newton::new(&mna.devices, &device_nodes);
        let ports = vec![0.0; newton.v_lin.len()];
        let mut tr = Transient {
            opts,
            h,
            newton,
            levels: vec![None; opts.max_halvings as usize + 1],
            x: vec![0.0; n],
            x_prev: vec![0.0; n],
            h_prev: 0.0,
            cx: vec![0.0; n],
            qdot: vec![0.0; n],
            ports,
            u: u0,
            n: 0,
            stats: Stats::default(),
            rhs: vec![0.0; n],
            y: vec![0.0; n],
            rn: vec![0.0; n],
            xn: vec![0.0; n],
            x_new: vec![0.0; n],
            cx_new: vec![0.0; n],
            work: vec![0.0; n],
            device_nodes,
            mna,
        };
        tr.dc(u0)?;
        Ok(tr)
    }

    /// The DC operating point: plain Newton, then gmin stepping, then source
    /// stepping.
    fn dc(&mut self, u0: f64) -> Result<(), Error> {
        let sys = Reduced::new(&self.mna.g, &self.device_nodes);
        let nn = sys.n_len();
        let nl = sys.l_len();
        let mut base = self.mna.b.clone();
        base[self.mna.input_row] += u0;
        let o = self.opts;
        let opts = |gshunt: f64| NewtonOptions {
            reltol: o.reltol,
            vntol: o.vntol,
            max_iter: o.max_iter_dc,
            gshunt,
        };

        // One Newton solve at source scale `lambda`, from `xn` and `v_lin`.
        let mut iterations = 0;
        let mut attempt = |tr: &mut Transient, lambda: f64, gshunt: f64, xn: &mut [f64]| {
            for (r, b) in tr.rhs.iter_mut().zip(&base) {
                *r = lambda * b;
            }
            sys.reduce(
                &tr.rhs,
                &mut tr.y[..nl],
                &mut tr.rn[..nn],
                &mut tr.work[..nl],
            );
            let res = tr
                .newton
                .solve(&sys, &tr.mna.devices, &tr.rn[..nn], xn, &opts(gshunt));
            if let Ok(k) = res {
                iterations += k;
            }
            res
        };

        let mut xn = vec![0.0; nn];
        self.newton.v_lin.fill(0.0);
        let mut method = "newton";
        let mut result = attempt(self, 1.0, 0.0, &mut xn);

        if matches!(result, Err(Failure::NoConvergence { .. })) {
            // gmin stepping: from a heavily shunted circuit down to none.
            method = "gmin";
            xn.fill(0.0);
            self.newton.v_lin.fill(0.0);
            let mut gshunt = 1e-2;
            result = loop {
                let r = attempt(self, 1.0, gshunt, &mut xn);
                if r.is_err() || gshunt == 0.0 {
                    break r;
                }
                gshunt = if gshunt > 1e-12 { gshunt * 0.1 } else { 0.0 };
            };
        }
        if matches!(result, Err(Failure::NoConvergence { .. })) {
            // Source stepping, with an adaptive step in the scale.
            method = "source";
            xn.fill(0.0);
            self.newton.v_lin.fill(0.0);
            let (mut lambda, mut step) = (0.0f64, 0.1f64);
            let (mut good_xn, mut good_v) = (xn.clone(), self.newton.v_lin.clone());
            result = loop {
                let next = (lambda + step).min(1.0);
                match attempt(self, next, 0.0, &mut xn) {
                    Ok(k) => {
                        lambda = next;
                        good_xn.copy_from_slice(&xn);
                        good_v.copy_from_slice(&self.newton.v_lin);
                        if lambda >= 1.0 {
                            break Ok(k);
                        }
                        step = (step * 2.0).min(0.25);
                    }
                    Err(e) => {
                        step *= 0.25;
                        if step < 1e-6 {
                            break Err(e);
                        }
                        xn.copy_from_slice(&good_xn);
                        self.newton.v_lin.copy_from_slice(&good_v);
                    }
                }
            };
        }
        if let Err(f) = result {
            return Err(self.failure_error(&sys, f, "DC operating point"));
        }
        sys.expand(&self.y[..nl], &xn, &mut self.x);
        self.newton.ports(&self.mna.devices, &xn, &mut self.ports);
        self.accept_ports();
        self.mna.c.mul_vec(&self.x, &mut self.cx);
        self.qdot.fill(0.0);
        self.stats.dc_method = method;
        self.stats.dc_iterations = iterations;
        self.stats.nonlinear_unknowns = nn;
        self.stats.linear_unknowns = nl;
        Ok(())
    }

    /// Tell every device its port voltages at the accepted point `x`.
    fn accept_ports(&mut self) {
        let mut off = 0;
        for inst in &mut self.mna.devices {
            let np = inst.device.ports();
            inst.device.accept(&self.ports[off..off + np]);
            off += np;
        }
    }

    /// Advance one step to the time where the input is `u`.
    pub fn step(&mut self, u: f64) -> Result<(), Error> {
        let u0 = self.u;
        let halved_before = self.stats.substeps;
        let res = self.advance(0, u0, u);
        if self.stats.substeps > halved_before {
            self.stats.halved_steps += 1;
        }
        self.n += 1;
        res.map_err(|(level, f)| {
            let sys = self.levels[level].as_ref().expect("built");
            let what = format!(
                "transient step to t = {:.9e} s (sample {}, after {} halvings)",
                self.n as f64 * self.h,
                self.n,
                level
            );
            self.failure_error(sys, f, &what)
        })
    }

    /// Advance by `h / 2^level` to input `u1`, halving on failure.
    fn advance(&mut self, level: usize, u0: f64, u1: f64) -> Result<(), (usize, Failure)> {
        match self.try_step(level, u1) {
            Ok(()) => Ok(()),
            Err(f) if level as u32 >= self.opts.max_halvings => Err((level, f)),
            Err(_) => {
                let um = 0.5 * (u0 + u1);
                self.advance(level + 1, u0, um)?;
                self.advance(level + 1, um, u1)
            }
        }
    }

    fn try_step(&mut self, level: usize, u: f64) -> Result<(), Failure> {
        let hk = self.h / (1u64 << level) as f64;
        let coef = match self.opts.method {
            Method::Trapezoidal => 2.0 / hk,
            Method::BackwardEuler => 1.0 / hk,
        };
        if self.levels[level].is_none() {
            let a = self.mna.g.plus_scaled(coef, &self.mna.c);
            self.levels[level] = Some(Reduced::new(&a, &self.device_nodes));
        }
        let sys = self.levels[level].as_ref().expect("just built");
        let (nn, nl) = (sys.n_len(), sys.l_len());

        for (((r, b), cx), q) in self
            .rhs
            .iter_mut()
            .zip(&self.mna.b)
            .zip(&self.cx)
            .zip(&self.qdot)
        {
            *r = b + coef * cx;
            if self.opts.method == Method::Trapezoidal {
                *r += q;
            }
        }
        self.rhs[self.mna.input_row] += u;
        sys.reduce(
            &self.rhs,
            &mut self.y[..nl],
            &mut self.rn[..nn],
            &mut self.work[..nl],
        );

        let xn = &mut self.xn[..nn];
        let slope = if self.opts.extrapolate && self.h_prev > 0.0 {
            hk / self.h_prev
        } else {
            0.0
        };
        for (v, &i) in xn.iter_mut().zip(&sys.n_idx) {
            *v = self.x[i] + slope * (self.x[i] - self.x_prev[i]);
        }
        self.newton.v_lin.copy_from_slice(&self.ports);
        let opts = NewtonOptions {
            reltol: self.opts.reltol,
            vntol: self.opts.vntol,
            max_iter: self.opts.max_iter,
            gshunt: 0.0,
        };
        let iters = self
            .newton
            .solve(sys, &self.mna.devices, &self.rn[..nn], xn, &opts)?;

        // Accept.
        sys.expand(&self.y[..nl], xn, &mut self.x_new);
        self.mna.c.mul_vec(&self.x_new, &mut self.cx_new);
        for ((q, new), old) in self.qdot.iter_mut().zip(&self.cx_new).zip(&self.cx) {
            *q = match self.opts.method {
                Method::Trapezoidal => coef * (new - old) - *q,
                Method::BackwardEuler => coef * (new - old),
            };
        }
        std::mem::swap(&mut self.x_prev, &mut self.x);
        std::mem::swap(&mut self.x, &mut self.x_new);
        std::mem::swap(&mut self.cx, &mut self.cx_new);
        self.h_prev = hk;
        self.u = u;
        self.newton
            .ports(&self.mna.devices, &self.xn[..nn], &mut self.ports);
        self.accept_ports();
        if level == 0 {
            self.stats.steps += 1;
        } else {
            self.stats.substeps += 1;
        }
        self.stats.iterations += iters as u64;
        self.stats.max_iterations = self.stats.max_iterations.max(iters);
        Ok(())
    }

    /// An error naming the unknown Newton failed on and the devices there.
    fn failure_error(&self, sys: &Reduced, f: Failure, what: &str) -> Error {
        let (position, detail) = match f {
            Failure::Singular { position } => (
                position,
                "matrix singular (no DC path to ground, or a loop of sources and inductors?)"
                    .to_string(),
            ),
            Failure::NoConvergence { position, update } => (
                position,
                format!("Newton did not converge (last update {update:.3e})"),
            ),
        };
        let full = sys.n_idx[position];
        let unknown = &self.mna.unknowns[full];
        let mut on: Vec<String> = Vec::new();
        for d in &self.mna.devices {
            for (p, name) in d.pins.iter().zip(d.pin_names) {
                if *p == Some(full) {
                    on.push(format!("{}.{name}", d.name));
                }
            }
        }
        let at = if on.is_empty() {
            String::new()
        } else {
            format!(" ({})", on.join(", "))
        };
        Error::new(format!(
            "{what}: {detail} at the {}{at}",
            unknown.describe()
        ))
    }

    /// The current solution (node voltages, then branch currents; see `Mna`).
    pub fn x(&self) -> &[f64] {
        &self.x
    }

    pub fn mna(&self) -> &Mna {
        &self.mna
    }

    pub fn stats(&self) -> &Stats {
        &self.stats
    }
}

/// Probe signals, one value per input sample.
#[derive(Debug, Clone, PartialEq)]
pub struct Output {
    /// SPICE-style names, e.g. `v(out)`.
    pub names: Vec<String>,
    pub values: Vec<Vec<f64>>,
    pub stats: Stats,
}

/// Run `ir` with `input` (volts at `input_node`, one sample per step of `h`
/// seconds). Sample 0 is the DC operating point.
pub fn simulate(ir: &CircuitIr, input: &[f64], h: f64, opts: &Options) -> Result<Output, Error> {
    if let Some(i) = input.iter().position(|u| !u.is_finite()) {
        return Err(Error::new(format!("input sample {i} is not finite")));
    }
    let mna = Mna::from_ir(ir, opts.gmin)?;
    let names: Vec<String> = mna.probes.iter().map(|(n, _)| n.clone()).collect();
    let mut values: Vec<Vec<f64>> = vec![Vec::with_capacity(input.len()); names.len()];
    let Some((&u0, rest)) = input.split_first() else {
        return Ok(Output {
            names,
            values,
            stats: Stats::default(),
        });
    };
    let mut tr = Transient::new(mna, h, *opts, u0)?;
    let mut record = |tr: &Transient| {
        for (v, y) in values.iter_mut().zip(tr.mna().probe_values(tr.x())) {
            v.push(y);
        }
    };
    record(&tr);
    for &u in rest {
        tr.step(u)?;
        record(&tr);
    }
    Ok(Output {
        names,
        values,
        stats: tr.stats().clone(),
    })
}
