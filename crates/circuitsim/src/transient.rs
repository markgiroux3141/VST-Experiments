//! Fixed-step transient analysis of the linear MNA system `G x + C x' = b(t)`.
//!
//! The step h is 1 / (oversample x sample rate), and the input is given at
//! every step, so outputs land exactly on the sample grid. The run starts from
//! the DC operating point with the first input sample (capacitors open,
//! inductors shorted), as ngspice's `.tran` does.
//!
//! Trapezoidal rule in companion form: with `q' = C x'` carried as state,
//!
//! ```text
//! (G + 2C/h) x[n+1] = b[n+1] + s[n],     s[n] = 2C/h x[n] + q'[n]
//! s[n+1] = 4C/h x[n+1] - s[n]
//! ```
//!
//! This is SPICE's capacitor/inductor companion model written for the whole
//! matrix. Rows without a C entry (resistive nodes, sources) are solved exactly
//! each step instead of being averaged, so they can't ring. Backward Euler,
//! `(G + C/h) x[n+1] = b[n+1] + C/h x[n]`, is there for damping stiff modes.

use crate::Error;
use crate::ir::CircuitIr;
use crate::linalg::{Lu, Matrix};
use crate::mna::Mna;

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

/// A transient run in progress; `step` advances it one sample.
#[derive(Debug, Clone)]
pub struct Transient {
    mna: Mna,
    method: Method,
    /// Factors of the step matrix G + 2C/h (or G + C/h).
    lu: Lu,
    /// 4C/h (trapezoidal) or C/h (backward Euler): maps x to the history term.
    c_hist: Matrix,
    x: Vec<f64>,
    s: Vec<f64>,
    rhs: Vec<f64>,
    work: Vec<f64>,
}

impl Transient {
    /// Factor the step matrix and solve the DC operating point with input `u0`.
    pub fn new(mna: Mna, h: f64, method: Method, u0: f64) -> Result<Transient, Error> {
        if !(h.is_finite() && h > 0.0) {
            return Err(Error::new(format!("time step {h} must be > 0")));
        }
        let n = mna.len();
        let mut work = vec![0.0; n];

        let dc = Lu::factor(&mna.g).map_err(|e| {
            Error::new(format!(
                "DC operating point: matrix singular at the {} \
                 (no DC path to ground, or a loop of sources and inductors?)",
                mna.unknowns[e.column].describe()
            ))
        })?;
        let mut x = mna.b.clone();
        x[mna.input_row] += u0;
        dc.solve(&mut x, &mut work);

        let (step_c, hist_c) = match method {
            Method::Trapezoidal => (2.0 / h, 4.0 / h),
            Method::BackwardEuler => (1.0 / h, 1.0 / h),
        };
        let lu = Lu::factor(&mna.g.plus_scaled(step_c, &mna.c)).map_err(|e| {
            Error::new(format!(
                "transient matrix singular at the {}",
                mna.unknowns[e.column].describe()
            ))
        })?;
        let c_hist = mna.c.scaled(hist_c);
        // At a DC operating point q' = 0, so s = 2C/h x (trap) or C/h x (Euler).
        let mut s = vec![0.0; n];
        mna.c.scaled(step_c).mul_vec(&x, &mut s);
        Ok(Transient {
            mna,
            method,
            lu,
            c_hist,
            x,
            s,
            rhs: vec![0.0; n],
            work,
        })
    }

    /// Advance one step to the time where the input is `u`.
    pub fn step(&mut self, u: f64) {
        for ((r, b), s) in self.rhs.iter_mut().zip(&self.mna.b).zip(&self.s) {
            *r = b + s;
        }
        self.rhs[self.mna.input_row] += u;
        self.lu.solve(&mut self.rhs, &mut self.work);
        std::mem::swap(&mut self.x, &mut self.rhs);
        match self.method {
            Method::Trapezoidal => {
                // s = 4C/h x - s, using rhs as scratch.
                self.c_hist.mul_vec(&self.x, &mut self.rhs);
                for (s, w) in self.s.iter_mut().zip(&self.rhs) {
                    *s = w - *s;
                }
            }
            Method::BackwardEuler => self.c_hist.mul_vec(&self.x, &mut self.s),
        }
    }

    /// The current solution (node voltages, then branch currents; see `Mna`).
    pub fn x(&self) -> &[f64] {
        &self.x
    }

    pub fn mna(&self) -> &Mna {
        &self.mna
    }
}

/// Probe signals, one value per input sample.
#[derive(Debug, Clone, PartialEq)]
pub struct Output {
    /// SPICE-style names, e.g. `v(out)`.
    pub names: Vec<String>,
    pub values: Vec<Vec<f64>>,
}

/// Run `ir` with `input` (volts at `input_node`, one sample per step of `h`
/// seconds). Sample 0 is the DC operating point.
pub fn simulate(ir: &CircuitIr, input: &[f64], h: f64, method: Method) -> Result<Output, Error> {
    if let Some(i) = input.iter().position(|u| !u.is_finite()) {
        return Err(Error::new(format!("input sample {i} is not finite")));
    }
    let mna = Mna::from_ir(ir)?;
    let names: Vec<String> = mna.probes.iter().map(|(n, _)| n.clone()).collect();
    let mut values: Vec<Vec<f64>> = vec![Vec::with_capacity(input.len()); names.len()];
    let Some((&u0, rest)) = input.split_first() else {
        return Ok(Output { names, values });
    };
    let mut tr = Transient::new(mna, h, method, u0)?;
    let mut record = |tr: &Transient| {
        for (v, y) in values.iter_mut().zip(tr.mna().probe_values(tr.x())) {
            v.push(y);
        }
    };
    record(&tr);
    for &u in rest {
        tr.step(u);
        record(&tr);
    }
    Ok(Output { names, values })
}
