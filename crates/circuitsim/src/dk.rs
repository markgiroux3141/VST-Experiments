//! Nodal DK: the linear part of the circuit folded into a discrete
//! state-space system, so each implicit stage runs Newton on the device
//! ports only (Yeh 2009; Holters & Zölzer 2015, generalized to the
//! diagonally implicit Runge-Kutta stages of `transient.rs`).
//!
//! A stage of a diagonally implicit method solves (see `transient.rs`)
//!
//! ```text
//! A Y + N^T i(N Y) = b + u e_in + C x[n]/(g h) + w,     A = G + C/(g h)
//! w = (1/g) sum_j a_ij F_j
//! ```
//!
//! where `N` maps the unknowns to the device port voltages (row j: +1 at
//! port j's pin, -1 at its reference pin) and `i` are the port currents.
//! `C x` and every `F = C x'` only involve the rows and columns S where `C`
//! has any entry, r of them, so the state is `x_S`: the voltages of nodes
//! with capacitance, the currents of inductors, and the flux densities of
//! core nodes (a winding's row reads its core node's column: C is not
//! symmetric there). With the responses of `A^-1` to `C x_S/(g h)`, to `w`, to
//! the port currents, to `b` and to the input computed once per step size,
//! a stage is
//!
//! ```text
//! p   = N A^-1 (b + C x_S/(g h)) + u N A^-1 e_in + N A^-1 w   (once per step; M x r per stage)
//! v   = p - K i(v),   K = N A^-1 N^T                           (Newton on M port voltages)
//! Y_S = (same responses on the rows S) - (A^-1 N^T)_S i        (r x r, r x M)
//! F   = C_SS (Y_S - x_S)/(g h) - w
//! ```
//!
//! and the unknowns themselves, `Y = A^-1 (...) - A^-1 N^T i`, are only
//! needed at the end of a step (probes, error control). This is exact
//! algebra on the same equations as the full-MNA solver (`newton.rs`); only
//! the linear algebra moves out of the iteration.
//!
//! Why `x_S` and not `C x` as the state: in the 670 the transformer windings
//! carry DC fluxes (~5 Wb at 50 mA in 100 H) that nearly cancel between the
//! halves of a push-pull winding, so `C x/(g h)` is ~1e4..1e6 while the port
//! voltages it produces are ~1..300 V. Every precomputed response column
//! carries its own roundoff, and summing them with such coefficients lost
//! 3-5 digits (measured: DK 1e-4 V from full MNA on the plates, whose own
//! roundoff spread is 1e-7 V). The response to `C x_S/(g h)` is
//! `(I - A^-1 G)` on S, entries of order 1, so nothing large is formed.
//!
//! Diode ports also move a fixed conductance g0 from the device into `A`
//! (`A + N^T G0 N`; the device becomes `i(v) - g0 v`). In exact arithmetic
//! nothing changes: the linearized system Newton solves is the same. But
//! without it `A` describes the circuit with the devices removed, and in
//! the 670 that leaves T104's secondary and the bridge on a 1 GOhm leak
//! next to 1 mOhm windings: K reaches 1e9 Ohm, and its precomputed entries
//! lost 4 digits on every node (5e-6 V on the plates, 50x full MNA's own
//! roundoff spread; iterative refinement diverged). With g0 the floating
//! island's conditioning is left to the small Newton matrix, which is
//! equilibrated and factored every iteration, as full MNA does on its
//! device-node block. (The island itself stays ill-conditioned in any
//! engine: with the bridge off it hangs on ~1e-7 S of diode leakage, and the
//! 1 mOhm winding's ~5e4 A conductance terms leave ~1e-11 A of roundoff in
//! its KCL, ~1e-4 V. Checked in 40-digit arithmetic: both solvers sit there.)
//!
//! Newton linearizes every device at its (limited) port voltages, as SPICE
//! does: `i ~ i_d + G_d (v - v_d)`, so an iteration solves
//! `(I + K G_d) v = p - K (i_d - G_d v_d)`, an M x M system (M = 22 for the
//! 670, against 27 device nodes plus the eliminated block for full MNA).
//! Without reuse ([`DkNewton`]) the iterates are those of full-MNA Newton;
//! the convergence test looks at the port voltages instead of the
//! device-node voltages. With reuse (the default) the factored matrix is
//! kept while it keeps converging and unmoved devices aren't re-evaluated,
//! so a typical stage is one evaluation of the devices, a few M x M
//! products and a triangular solve.
//!
//! Everything here depends on the component values, so a parameter change
//! (`Transient::update`) only rebuilds the matrices: ~1 ms for the 670 per
//! step size, on first use.

use std::sync::atomic::{AtomicU64, Ordering};

use crate::linalg::{ColLu, Lu, Matrix, Singular, gemv_add, gemv_sub};
use crate::mna::{DeviceInstance, Wave};
use crate::newton::{Failure, NewtonOptions};
use crate::timing::{self, Part};

/// Where the device ports sit: unknown indices of every port's pin and
/// reference pin, device by device, in the layout of `Newton::v_lin`.
#[derive(Debug, Clone)]
pub struct Ports {
    /// (pin, reference) of every port; `None` is ground.
    pub nodes: Vec<(Option<usize>, Option<usize>)>,
    /// First port of each device, and its number of ports.
    pub offsets: Vec<usize>,
    pub widths: Vec<usize>,
    /// Conductance moved from each port's device into the step matrix
    /// (see [`crate::devices::Device::shunt`]).
    pub shunts: Vec<f64>,
    /// First entry of each device's Jacobian (row-major, ports x ports) in a
    /// packed list of all of them.
    g_offsets: Vec<usize>,
    g_len: usize,
}

impl Ports {
    pub fn new(devices: &[DeviceInstance]) -> Ports {
        let (mut nodes, mut offsets, mut widths, mut g_offsets, mut shunts) =
            (Vec::new(), Vec::new(), Vec::new(), Vec::new(), Vec::new());
        let mut g_len = 0;
        for d in devices {
            let np = d.device.ports();
            let reference = *d.pins.last().expect("devices have pins");
            offsets.push(nodes.len());
            widths.push(np);
            g_offsets.push(g_len);
            g_len += np * np;
            for (k, &p) in d.pins[..np].iter().enumerate() {
                nodes.push((p, reference));
                shunts.push(d.device.shunt(k));
            }
        }
        Ports {
            nodes,
            shunts,
            offsets,
            widths,
            g_offsets,
            g_len,
        }
    }

    pub fn len(&self) -> usize {
        self.nodes.len()
    }

    pub fn is_empty(&self) -> bool {
        self.nodes.is_empty()
    }

    /// Port voltages of the unknowns `x`.
    pub fn voltages(&self, x: &[f64], v: &mut [f64]) {
        let at = |p: Option<usize>| p.map_or(0.0, |a| x[a]);
        for (v, &(p, r)) in v.iter_mut().zip(&self.nodes) {
            *v = at(p) - at(r);
        }
    }

    /// The device (index) and its port of port `j`.
    pub fn device_of(&self, j: usize) -> (usize, usize) {
        let d = self.offsets.partition_point(|&o| o <= j) - 1;
        (d, j - self.offsets[d])
    }
}

/// Rows and columns of `C` with any nonzero entry: the state of the DK system.
pub fn support(c: &Matrix) -> Vec<usize> {
    let n = c.n();
    (0..n)
        .filter(|&i| c.row(i).iter().any(|&x| x != 0.0) || (0..n).any(|j| c.get(j, i) != 0.0))
        .collect()
}

/// The DK matrices of one step matrix `A = G + C/(g h)`.
///
/// Everything is a response of `A^-1` to an input column, read out on
/// three blocks of rows: the M port voltages, the r state unknowns `x_S`,
/// and all n unknowns. Input columns: the state (`C e_s / (g h)` for each s
/// in S), the stage inputs (`e_s`: the F history), the M port currents
/// (`N^T e_j`), the sources `b`, the input `e_in` and each sine source's
/// row (its wave, [`crate::mna::Wave`]).
#[derive(Debug, Clone)]
pub struct DkSystem {
    /// Unique per system built, so a factored Newton matrix knows its K.
    id: u64,
    pub m: usize,
    pub r: usize,
    pub n: usize,
    /// Rows of every response: m + r + n.
    rows: usize,
    /// Response to the state, rows x r, column-major.
    xa: Vec<f64>,
    /// Response to the stage inputs, rows x r, column-major.
    qa: Vec<f64>,
    /// Response to the port currents, rows x m, column-major (its port
    /// rows are K).
    ia: Vec<f64>,
    /// Responses to `b` and to the input.
    b0: Vec<f64>,
    be: Vec<f64>,
    /// Response to each wave's row, rows x waves, column-major.
    bw: Vec<f64>,
}

impl DkSystem {
    /// For a circuit with conductance and reactive matrices `g` and `c`,
    /// sources `b`, the input on row `input_row` and sine sources `waves`,
    /// stepped with `inv = 1 / (g h)`. Fails if the step matrix is singular.
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        g: &Matrix,
        c: &Matrix,
        inv: f64,
        b: &[f64],
        input_row: usize,
        waves: &[Wave],
        ports: &Ports,
        support: &[usize],
    ) -> Result<DkSystem, Singular> {
        let n = g.n();
        let (m, r) = (ports.len(), support.len());
        let rows = m + r + n;
        let mut a = g.plus_scaled(inv, c);
        for (&(p, rf), &g0) in ports.nodes.iter().zip(&ports.shunts) {
            if g0 != 0.0 {
                for (i, si) in [(p, 1.0), (rf, -1.0)] {
                    for (j, sj) in [(p, 1.0), (rf, -1.0)] {
                        if let (Some(i), Some(j)) = (i, j) {
                            a.add(i, j, si * sj * g0);
                        }
                    }
                }
            }
        }
        let lu = Lu::factor(&a)?;
        let mut work = vec![0.0; n];
        // A^-1 z read out on the three row blocks.
        let mut respond = |z: &mut [f64], out: &mut [f64]| {
            lu.solve(z, &mut work);
            ports.voltages(z, &mut out[..m]);
            for (o, &s) in out[m..m + r].iter_mut().zip(support) {
                *o = z[s];
            }
            out[m + r..].copy_from_slice(z);
        };
        let mut z = vec![0.0; n];
        let mut xa = vec![0.0; rows * r];
        for (col, &s) in xa.chunks_exact_mut(rows).zip(support) {
            // Column s of C (not symmetric where windings read core nodes).
            for (i, zi) in z.iter_mut().enumerate() {
                *zi = inv * c.get(i, s);
            }
            respond(&mut z, col);
        }
        let mut qa = vec![0.0; rows * r];
        for (col, &s) in qa.chunks_exact_mut(rows).zip(support) {
            z.fill(0.0);
            z[s] = 1.0;
            respond(&mut z, col);
        }
        let mut ia = vec![0.0; rows * m];
        for (col, &(p, rf)) in ia.chunks_exact_mut(rows).zip(&ports.nodes) {
            z.fill(0.0);
            if let Some(p) = p {
                z[p] += 1.0;
            }
            if let Some(rf) = rf {
                z[rf] -= 1.0;
            }
            respond(&mut z, col);
        }
        let mut b0 = vec![0.0; rows];
        z.copy_from_slice(b);
        respond(&mut z, &mut b0);
        let mut be = vec![0.0; rows];
        z.fill(0.0);
        z[input_row] = 1.0;
        respond(&mut z, &mut be);
        let mut bw = vec![0.0; rows * waves.len()];
        for (col, wave) in bw.chunks_exact_mut(rows).zip(waves) {
            z.fill(0.0);
            z[wave.row] = 1.0;
            respond(&mut z, col);
        }
        static NEXT_ID: AtomicU64 = AtomicU64::new(1);
        Ok(DkSystem {
            id: NEXT_ID.fetch_add(1, Ordering::Relaxed),
            m,
            r,
            n,
            rows,
            xa,
            qa,
            ia,
            b0,
            be,
            bw,
        })
    }

    /// The part of every stage that only depends on the step's start: the
    /// response to `b` and to the state `x_S`, on all rows.
    pub fn step_base(&self, xs: &[f64], base: &mut [f64]) {
        base.copy_from_slice(&self.b0);
        gemv_add(base, &self.xa, 0, self.rows, xs);
    }

    /// Port voltages and state without device currents, for the stage
    /// inputs `w`, input `u` and wave values `wv` (one per sine source, at
    /// the stage's time): `out[..m + r]` (the first m are Newton's `p`).
    pub fn stage(&self, base: &[f64], u: f64, wv: &[f64], w: &[f64], out: &mut [f64]) {
        let k = self.m + self.r;
        for ((o, b), e) in out[..k].iter_mut().zip(base).zip(&self.be) {
            *o = b + u * e;
        }
        gemv_add(&mut out[..k], &self.bw, 0, self.rows, wv);
        gemv_add(&mut out[..k], &self.qa, 0, self.rows, w);
    }

    /// Subtract the port currents' share from the state: `ys` is
    /// `out[m..m + r]` of [`DkSystem::stage`] on entry, the stage's `Y_S` on exit.
    pub fn states(&self, ys: &mut [f64], i: &[f64], neg: &mut [f64]) {
        gemv_sub(ys, &self.ia, self.m, self.rows, i, neg);
    }

    /// All unknowns of a stage: `x = A^-1 (b + u e_in + sum wv_k e_k + C x_S
    /// / (g h) + w) - A^-1 N^T i`.
    #[allow(clippy::too_many_arguments)]
    pub fn unknowns(
        &self,
        base: &[f64],
        u: f64,
        wv: &[f64],
        w: &[f64],
        i: &[f64],
        x: &mut [f64],
        neg: &mut [f64],
    ) {
        let k = self.m + self.r;
        for ((o, b), e) in x.iter_mut().zip(&base[k..]).zip(&self.be[k..]) {
            *o = b + u * e;
        }
        gemv_add(x, &self.bw, k, self.rows, wv);
        gemv_add(x, &self.qa, k, self.rows, w);
        gemv_sub(x, &self.ia, k, self.rows, i, neg);
    }

    /// `(A + N^T G_d N)^-1 E_S e` on all unknowns, for a vector `e` on the
    /// state rows, with the device Jacobians and factored Newton matrix of
    /// `newton`'s last iteration (Woodbury: `A^-1 E_S e - A^-1 N^T G_d
    /// (I + K G_d)^-1 N A^-1 E_S e`). `w` has length m.
    pub fn solve_linearized(
        &self,
        newton: &DkNewton,
        ports: &Ports,
        e: &[f64],
        x: &mut [f64],
        w: &mut [f64],
        neg: &mut [f64],
    ) {
        let k = self.m + self.r;
        w.fill(0.0);
        gemv_add(w, &self.qa, 0, self.rows, e);
        newton.factored().lu.solve(w);
        gd_mul(&newton.factored().gd, ports, w, neg);
        w.copy_from_slice(&neg[..self.m]);
        x.fill(0.0);
        gemv_add(x, &self.qa, k, self.rows, e);
        gemv_sub(x, &self.ia, k, self.rows, w, neg);
    }

    /// Rows of every response (the length of [`DkSystem::step_base`]'s output).
    pub fn rows(&self) -> usize {
        self.rows
    }

    /// K, column-major with leading dimension `rows`.
    fn k(&self) -> &[f64] {
        &self.ia
    }

    /// K as a dense m x m column-major matrix.
    pub fn k_matrix(&self) -> Vec<f64> {
        (0..self.m)
            .flat_map(|c| {
                self.ia[c * self.rows..c * self.rows + self.m]
                    .iter()
                    .copied()
            })
            .collect()
    }
}

/// Refactor at the start of a solve when the last observed contraction of
/// the reused matrix was above this.
const THETA_REFACTOR: f64 = 0.1;
/// Refactor within a solve when an iteration contracted the update less
/// than this; with it, accepting an update within the tolerance leaves an
/// error of at most theta / (1 - theta) <= 1 tolerance.
const THETA_MAX: f64 = 0.5;

/// Factored Newton matrices kept at once: one per step size in use (error
/// control moves between the full step and a few halvings).
const SLOTS: usize = 6;

/// A factored Newton matrix `I + K G`.
#[derive(Debug, Clone)]
struct Factored {
    lu: ColLu,
    /// The device Jacobians in it.
    gd: Vec<f64>,
    /// The [`DkSystem`] it belongs to (0: none).
    id: u64,
    /// Contraction of the last iteration of the last solve that used it (0
    /// if that took one iteration).
    theta: f64,
    /// When it was last used (solve count), to replace the oldest.
    used: u64,
}

/// Newton on the device port voltages of a [`DkSystem`].
///
/// Each iteration linearizes the devices, `i(v') ~ i_d + G_d (v' - v_d)`,
/// and solves `(I + K G) v' = p - K (i_d + G_d (v - v_d) - G v)` with the
/// factored matrix of some `G`. With `G = G_d` that is Newton (SPICE's
/// companion models). With `reuse` it is Newton with a lagged Jacobian, as
/// stiff ODE codes do (Hairer & Wanner IV.8): the factorization is kept
/// across iterations, stages and steps (one per step size) and redone
/// when an iteration contracts the update by less than [`THETA_MAX`], when
/// the last solve's contraction was above [`THETA_REFACTOR`], and on and
/// after an iteration with junction limiting. Devices
/// whose ports moved by less than the tolerance since they were last
/// evaluated keep that evaluation (SPICE's bypass), which leaves a
/// linearization error of order tolerance squared.
///
/// Either way a solve ends when no device was limited and the update is
/// within `reltol |v| + vntol` on every port; the currents it returns are
/// the linearized ones, so `v = p - K i` holds exactly.
#[derive(Debug, Clone)]
pub struct DkNewton {
    m: usize,
    /// Jacobian reuse and device bypass (see above).
    pub reuse: bool,
    /// Limiting reference: the port voltages each device was last
    /// linearized at. Callers set them before a solve (the previous accepted
    /// point).
    pub v_lin: Vec<f64>,
    /// Port currents of the linearized devices at the solution (valid after
    /// a successful [`DkNewton::solve`]).
    pub i: Vec<f64>,
    /// Each device's last evaluation: port voltages, currents, Jacobian
    /// (packed, see [`Ports`]), and whether it may be reused.
    v_eval: Vec<f64>,
    i_dev: Vec<f64>,
    gd: Vec<f64>,
    evaluated: Vec<bool>,
    /// Factored matrices, and the one the last solve used.
    slots: Vec<Factored>,
    cur: usize,
    solves: u64,
    /// Device evaluations (in all, and per device) and factorizations so far.
    pub evaluations: u64,
    pub device_evaluations: Vec<u64>,
    pub factorizations: u64,
    // Scratch.
    ieq: Vec<f64>,
    j: Vec<f64>,
    rhs: Vec<f64>,
    neg: Vec<f64>,
    vd: Vec<f64>,
}

impl DkNewton {
    pub fn new(ports: &Ports, reuse: bool) -> DkNewton {
        let m = ports.len();
        let widest = ports.widths.iter().copied().max().unwrap_or(0);
        DkNewton {
            m,
            reuse,
            v_lin: vec![0.0; m],
            i: vec![0.0; m],
            v_eval: vec![0.0; m],
            i_dev: vec![0.0; m],
            gd: vec![0.0; ports.g_len],
            evaluated: vec![false; ports.offsets.len()],
            slots: vec![
                Factored {
                    lu: ColLu::with_size(m),
                    gd: vec![0.0; ports.g_len],
                    id: 0,
                    theta: 0.0,
                    used: 0,
                };
                if reuse { SLOTS } else { 1 }
            ],
            cur: 0,
            solves: 0,
            evaluations: 0,
            device_evaluations: vec![0; ports.offsets.len()],
            factorizations: 0,
            ieq: vec![0.0; m],
            j: vec![0.0; m * m],
            rhs: vec![0.0; m],
            neg: vec![0.0; m],
            vd: vec![0.0; widest],
        }
    }

    /// Forget every device evaluation (devices with memory changed state,
    /// or the circuit changed).
    pub fn invalidate(&mut self) {
        self.evaluated.fill(false);
        for f in &mut self.slots {
            f.id = 0;
        }
    }

    /// Forget device `d`'s evaluation (it accepted a step and changed state).
    /// The factored matrices stay: a lagged Jacobian is refactored anyway
    /// when it stops converging.
    pub fn invalidate_device(&mut self, d: usize) {
        self.evaluated[d] = false;
    }

    /// Solve `v = p - K i(v)` for the port voltages `v` (the guess on
    /// entry). Returns the number of iterations; failures name a port.
    pub fn solve(
        &mut self,
        sys: &DkSystem,
        devices: &[DeviceInstance],
        ports: &Ports,
        p: &[f64],
        v: &mut [f64],
        opts: &NewtonOptions,
    ) -> Result<usize, Failure> {
        let m = self.m;
        if m == 0 {
            // No devices: the stage is linear and already solved.
            return Ok(0);
        }
        let (k, lda) = (sys.k(), sys.rows);
        let tol = |a: f64, b: f64| opts.reltol * a.abs().max(b.abs()) + opts.vntol;
        // This step size's factored matrix, or the oldest to replace.
        self.solves += 1;
        self.cur = match self.slots.iter().position(|f| f.id == sys.id) {
            Some(c) => c,
            None => (0..self.slots.len())
                .min_by_key(|&c| self.slots[c].used)
                .expect("slots"),
        };
        let slot = &mut self.slots[self.cur];
        slot.used = self.solves;
        let mut refactor = !self.reuse || slot.id != sys.id || slot.theta > THETA_REFACTOR;
        let mut r_prev = f64::INFINITY;
        let mut worst = (0, f64::NAN);
        for iter in 1..=opts.max_iter {
            // Evaluate the devices that moved (all of them without reuse).
            let t0 = timing::now();
            let mut limited = false;
            for (d, inst) in devices.iter().enumerate() {
                let (o, np, go) = (ports.offsets[d], ports.widths[d], ports.g_offsets[d]);
                let moved = !self.reuse
                    || !self.evaluated[d]
                    || (o..o + np)
                        .any(|j| (v[j] - self.v_eval[j]).abs() > tol(v[j], self.v_eval[j]));
                if !moved {
                    continue;
                }
                let vd = &mut self.vd[..np];
                vd.copy_from_slice(&v[o..o + np]);
                let lim = inst.device.limit(vd, &self.v_lin[o..o + np]);
                limited |= lim;
                self.v_lin[o..o + np].copy_from_slice(vd);
                self.v_eval[o..o + np].copy_from_slice(vd);
                // A limited device restarts from its limited point.
                v[o..o + np].copy_from_slice(vd);
                let g = &mut self.gd[go..go + np * np];
                inst.device.eval(vd, &mut self.i_dev[o..o + np], g);
                // The shunt is in the step matrix: the device here is
                // i - g0 v, Jacobian G - g0.
                for (jj, g0) in ports.shunts[o..o + np].iter().enumerate() {
                    self.i_dev[o + jj] -= g0 * vd[jj];
                    g[jj * np + jj] -= g0;
                }
                self.evaluated[d] = true;
                self.evaluations += 1;
                self.device_evaluations[d] += 1;
                if lim {
                    // Far from its last linearization: refactor.
                    refactor = true;
                }
            }

            timing::add(Part::Devices, t0);
            if refactor || !self.reuse {
                let t0 = timing::now();
                self.slots[self.cur].gd.copy_from_slice(&self.gd);
                self.factor(sys, ports)?;
                refactor = false;
                timing::add(Part::Factor, t0);
            }
            let t0 = timing::now();
            let slot = &mut self.slots[self.cur];

            // ieq = i_d + G_d (v - v_d) - G v with G the factored Jacobians.
            for (d, (&o, &np)) in ports.offsets.iter().zip(&ports.widths).enumerate() {
                let go = ports.g_offsets[d];
                let (g, glu) = (&self.gd[go..go + np * np], &slot.gd[go..go + np * np]);
                for jj in 0..np {
                    let mut s = self.i_dev[o + jj];
                    for kk in 0..np {
                        let (vk, dv) = (v[o + kk], v[o + kk] - self.v_eval[o + kk]);
                        s += g[jj * np + kk] * dv - glu[jj * np + kk] * vk;
                    }
                    self.ieq[o + jj] = s;
                }
            }
            self.rhs.copy_from_slice(&p[..m]);
            gemv_sub(&mut self.rhs, k, 0, lda, &self.ieq, &mut self.neg);
            slot.lu.solve(&mut self.rhs);

            // Converged when no device was limited and the ports have
            // settled. A NaN update counts as not settled, and as the worst.
            worst = (0, 0.0);
            let mut r = 0.0;
            for (a, (&old, &new)) in v.iter().zip(&self.rhs).enumerate() {
                let ratio = (new - old).abs() / tol(old, new);
                if ratio.is_nan() || ratio > r {
                    r = if ratio.is_nan() { f64::INFINITY } else { ratio };
                    worst = (a, new - old);
                }
            }
            v[..m].copy_from_slice(&self.rhs);
            if iter > 1 {
                slot.theta = if r_prev > 0.0 { r / r_prev } else { 0.0 };
                if slot.theta > THETA_MAX {
                    refactor = true;
                }
            } else {
                slot.theta = 0.0;
            }
            if limited {
                // This matrix holds the limited linearizations; the next
                // iteration's devices sit elsewhere (a chord step from here
                // cycles at a diode turning on).
                refactor = true;
            }
            r_prev = r;
            timing::add(Part::Iteration, t0);
            if !limited && r <= 1.0 {
                // The linearized currents at the solution: v = p - K i.
                gd_mul(&slot.gd, ports, v, &mut self.i);
                for (i, e) in self.i.iter_mut().zip(&self.ieq) {
                    *i += e;
                }
                return Ok(iter);
            }
            if v.iter().any(|x| !x.is_finite()) {
                break;
            }
        }
        Err(Failure::NoConvergence {
            position: worst.0,
            update: worst.1,
        })
    }

    /// The factored matrix the last solve used.
    fn factored(&self) -> &Factored {
        &self.slots[self.cur]
    }

    /// Factor `I + K G` into the current slot, with `G` its Jacobians.
    fn factor(&mut self, sys: &DkSystem, ports: &Ports) -> Result<(), Failure> {
        let m = self.m;
        let (k, lda) = (sys.k(), sys.rows);
        // Column o + kk of device d is e + sum_jj K[:, o + jj] g[jj][kk].
        self.j.fill(0.0);
        for c in 0..m {
            self.j[c * m + c] = 1.0;
        }
        for (d, (&o, &np)) in ports.offsets.iter().zip(&ports.widths).enumerate() {
            let g = &self.slots[self.cur].gd[ports.g_offsets[d]..ports.g_offsets[d] + np * np];
            for kk in 0..np {
                let col = &mut self.j[(o + kk) * m..(o + kk + 1) * m];
                for jj in 0..np {
                    let gjk = g[jj * np + kk];
                    if gjk != 0.0 {
                        let kc = &k[(o + jj) * lda..(o + jj) * lda + m];
                        for (x, kv) in col.iter_mut().zip(kc) {
                            *x += kv * gjk;
                        }
                    }
                }
            }
        }
        self.factorizations += 1;
        let slot = &mut self.slots[self.cur];
        match slot.lu.factor(&self.j) {
            Ok(()) => {
                slot.id = sys.id;
                Ok(())
            }
            Err(Singular { column }) => {
                slot.id = 0;
                Err(Failure::Singular { position: column })
            }
        }
    }
}

/// `out = G_d w`, device by device (`gd` packed as in [`Ports`]).
fn gd_mul(gd: &[f64], ports: &Ports, w: &[f64], out: &mut [f64]) {
    for (d, (&o, &np)) in ports.offsets.iter().zip(&ports.widths).enumerate() {
        let g = &gd[ports.g_offsets[d]..ports.g_offsets[d] + np * np];
        for jj in 0..np {
            let mut s = 0.0;
            for kk in 0..np {
                s += g[jj * np + kk] * w[o + kk];
            }
            out[o + jj] = s;
        }
    }
}
