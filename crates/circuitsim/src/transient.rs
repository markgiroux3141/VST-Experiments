//! Fixed-step transient analysis of `G x + C x' + d(x) = b(t)`, where `d` are
//! the device currents.
//!
//! The step h is 1 / (oversample x sample rate), and the input is given at
//! every step, so outputs land exactly on the sample grid. Between samples the
//! input is linear, like ngspice's PWL file source. Sine sources (the mains)
//! are exact at every stage's time. The run starts from the DC operating
//! point with the first input sample and the sine sources at t = 0
//! (capacitors open, inductors shorted), as ngspice's `.tran` does.
//!
//! Every method is a stiffly accurate implicit Runge-Kutta method (the last
//! stage is the step's end point), so the algebraic rows of the MNA system
//! (resistive nodes, sources) hold exactly at every sample. Write the system
//! as `C x' = F(x, t)` with `F = b - G x - d(x)`.
//!
//! **Diagonally implicit** methods (`trap`, `euler`, `trbdf2`, `sdirk3`,
//! `esdirk4`) solve their stages one after another. Stage i solves
//!
//! ```text
//! (G + C/(gh)) Y_i + d(Y_i) = b(t_i) + C x[n]/(gh) + (1/g) sum_{j<i} a_ij F_j
//! F_i = C (Y_i - x[n]) / (gh) - (1/g) sum_{j<i} a_ij F_j
//! ```
//!
//! with the method's diagonal g the same for every stage, so every stage uses
//! the same step matrix. `F_j = C x'` at stage j is carried as state, as in
//! SPICE's companion models. A first stage with a = 0 is explicit (it is the
//! previous step's end point, so it reuses its F). The trapezoidal rule is the
//! two-stage case g = 1/2, a = [[0], [1/2, 1/2]]:
//!
//! ```text
//! (G + 2C/h) x[n+1] + d(x[n+1]) = b[n+1] + 2C/h x[n] + F[n]
//! F[n+1] = 2C/h (x[n+1] - x[n]) - F[n]
//! ```
//!
//! **Radau IIA** (`radau3`, `radau5`) couples its s stages: with W = A^-1,
//!
//! ```text
//! G Y_i + sum_j (w_ij / h) C Y_j + d(Y_i) = b(t_i) + (sum_j w_ij / h) C x[n]
//! ```
//!
//! one system of s copies of the circuit (block matrix `I (x) G + W/h (x) C`),
//! solved by the same block elimination and Newton as a single step, with
//! every device placed once per stage.
//!
//! | method  | order | stages solved      | stability |
//! |---------|-------|--------------------|-----------|
//! | euler   | 1     | 1                  | L-stable  |
//! | trap    | 2     | 1                  | A-stable (fast modes ring at Nyquist) |
//! | trbdf2  | 2     | 2                  | L-stable  |
//! | sdirk3  | 3     | 3                  | L-stable  |
//! | esdirk4 | 4     | 5                  | L-stable  |
//! | radau3  | 3     | 1 (2 coupled)      | L-stable  |
//! | radau5  | 5     | 1 (3 coupled)      | L-stable  |
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
use crate::dk::{self, DkNewton, DkSystem, Ports};
use crate::ir::CircuitIr;
use crate::linalg::{Matrix, Singular, SparseRows};
use crate::mna::{Mna, SPICE_GMIN};
use crate::newton::{Failure, Newton, NewtonOptions, Reduced};
use crate::timing::{self, Part};

/// The conductance that holds a capacitor at its start voltage during the DC
/// operating point (1 mOhm: ~uV across it at mA).
const DC_START_S: f64 = 1.0e3;

/// What local error control measures the error estimate on, against
/// `error_abstol + error_reltol |v|` each.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ErrorNorm {
    /// Every node voltage.
    Nodes,
    /// The device port voltages and the state node voltages (nodes with
    /// capacitance). The other nodes are algebraic in those, the input and
    /// the sources; leaving them out means a DK step only needs the
    /// unknowns it outputs (`Options::all_unknowns`).
    PortsStates,
}

impl ErrorNorm {
    pub const NAMES: [&'static str; 2] = ["nodes", "ports_states"];

    pub fn parse(name: &str) -> Result<ErrorNorm, Error> {
        match name {
            "nodes" => Ok(ErrorNorm::Nodes),
            "ports_states" => Ok(ErrorNorm::PortsStates),
            _ => Err(Error::new(format!(
                "unknown error norm {name:?} ({})",
                ErrorNorm::NAMES.join(" | ")
            ))),
        }
    }
}

/// Accepted / rejected steps are counted per level up to this (`Stats`).
pub const LEVEL_STATS: usize = 8;

/// Step selection (`Options::step_selection`): the error ratio a refined
/// step aims at, the ratio a coarsened one may be predicted to reach, and
/// the most levels a step may coarsen by at once. The predictions assume the
/// error scales as h^4 (the embedded solution is 3rd order): one level is a
/// factor 16.
const REFINE_TARGET: f64 = 0.5;
const COARSEN_TARGET: f64 = 0.8;
const MAX_COARSEN: usize = 2;

/// Levels to refine a step rejected with error ratio `q` (> 1) by: at least
/// one, enough for the redone step to reach [`REFINE_TARGET`].
/// The sample after an update starts with backward Euler over h / 2^RESTART_LEVEL
/// ([`Transient::restart_sample`]), the deepest halving by default: its first-order
/// error on an update to the identical circuit is then as small as before the
/// restart existed (the 670 and the EQP-1A at 10 kHz, draft: -80 dB peak re the
/// signal, against -68 at h / 64; production -122 dB), and the modes a change
/// makes fast (a pot's end, 1 mOhm, on a capacitor: nanoseconds) settle within it.
const RESTART_LEVEL: usize = 8;

fn refine_levels(q: f64) -> usize {
    ((q / REFINE_TARGET).log2() / 4.0).ceil().max(1.0) as usize
}

/// Levels the step after one accepted with error ratio `q` may coarsen by
/// (0 ..= [`MAX_COARSEN`]) and stay below [`COARSEN_TARGET`].
fn coarsen_levels(q: f64) -> usize {
    if q <= 0.0 {
        return MAX_COARSEN;
    }
    ((COARSEN_TARGET / q).log2() / 4.0)
        .floor()
        .clamp(0.0, MAX_COARSEN as f64) as usize
}

/// The largest error / tolerance over the entries of a step's error
/// estimate `err` that `keep` selects, at the new values `x` (tolerance
/// `error_abstol + error_reltol |x|`).
fn error_ratio(err: &[f64], x: &[f64], keep: &[bool], opts: &Options) -> f64 {
    let (at, rt) = (opts.error_abstol, opts.error_reltol);
    err.iter()
        .zip(x)
        .zip(keep)
        .filter(|(_, k)| **k)
        .map(|((e, x), _)| e.abs() / (at + rt * x.abs()))
        .fold(0.0, f64::max)
}

/// How a step's nonlinear system is solved.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Solver {
    /// Nodal DK (`dk.rs`): the linear part folded into a state-space system
    /// once per step size, Newton on the device ports. Diagonally implicit
    /// methods only; fully implicit ones (Radau) fall back to `Mna`.
    Dk,
    /// Newton on the full MNA system with the linear unknowns eliminated
    /// per step size (`newton.rs`). The reference the DK solver is checked
    /// against.
    Mna,
}

impl Solver {
    pub const NAMES: [&'static str; 2] = ["dk", "mna"];

    pub fn parse(name: &str) -> Result<Solver, Error> {
        match name {
            "dk" => Ok(Solver::Dk),
            "mna" => Ok(Solver::Mna),
            _ => Err(Error::new(format!(
                "unknown solver {name:?} ({})",
                Solver::NAMES.join(" | ")
            ))),
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Method {
    Trapezoidal,
    BackwardEuler,
    TrBdf2,
    Sdirk3,
    Esdirk4,
    Radau3,
    Radau5,
}

impl Method {
    pub const NAMES: [&'static str; 7] = [
        "trap", "euler", "trbdf2", "sdirk3", "esdirk4", "radau3", "radau5",
    ];

    pub fn parse(name: &str) -> Result<Method, Error> {
        Ok(match name {
            "trap" => Method::Trapezoidal,
            "euler" => Method::BackwardEuler,
            "trbdf2" => Method::TrBdf2,
            "sdirk3" => Method::Sdirk3,
            "esdirk4" => Method::Esdirk4,
            "radau3" => Method::Radau3,
            "radau5" => Method::Radau5,
            _ => {
                return Err(Error::new(format!(
                    "unknown method {name:?} ({})",
                    Method::NAMES.join(" | ")
                )));
            }
        })
    }

    fn tableau(self) -> Tableau {
        match self {
            Method::Trapezoidal => Tableau::dirk(0.5, &[&[], &[0.5]]),
            Method::BackwardEuler => Tableau::dirk(1.0, &[&[]]).with_implicit_first(),
            Method::TrBdf2 => {
                // Hosea & Shampine (1996): g = 1 - sqrt(2)/2, the trapezoidal
                // rule to 2g h, then BDF2 to h, as an ESDIRK.
                let g = 1.0 - std::f64::consts::FRAC_1_SQRT_2;
                let w = std::f64::consts::SQRT_2 / 4.0;
                Tableau::dirk(g, &[&[], &[g], &[w, w]])
            }
            Method::Sdirk3 => {
                // Alexander (1977), 3 stages, order 3, L-stable.
                let g = 0.435_866_521_508_459;
                let b1 = -1.5 * g * g + 4.0 * g - 0.25;
                let b2 = 1.5 * g * g - 5.0 * g + 1.25;
                Tableau::dirk(g, &[&[0.0; 0], &[(1.0 - g) / 2.0], &[b1, b2]]).with_implicit_first()
            }
            Method::Esdirk4 => {
                // Kennedy & Carpenter (2003), ESDIRK4(3)6L[2]SA: 6 stages (the
                // first explicit), order 4, stage order 2, L-stable.
                Tableau::dirk(
                    0.25,
                    &[
                        &[],
                        &[0.25],
                        &[8611.0 / 62500.0, -1743.0 / 31250.0],
                        &[
                            5012029.0 / 34652500.0,
                            -654441.0 / 2922500.0,
                            174375.0 / 388108.0,
                        ],
                        &[
                            15267082809.0 / 155376265600.0,
                            -71443401.0 / 120774400.0,
                            730878875.0 / 902184768.0,
                            2285395.0 / 8070912.0,
                        ],
                        &[
                            82889.0 / 524892.0,
                            0.0,
                            15625.0 / 83664.0,
                            69875.0 / 102672.0,
                            -2260.0 / 8211.0,
                        ],
                    ],
                )
                // The pair's embedded 3rd-order solution.
                .with_embedded(&[
                    4586570599.0 / 29645900160.0,
                    0.0,
                    178811875.0 / 945068544.0,
                    814220225.0 / 1159782912.0,
                    -3700637.0 / 11593932.0,
                    61727.0 / 225920.0,
                ])
            }
            Method::Radau3 => Tableau::full(&[&[5.0 / 12.0, -1.0 / 12.0], &[3.0 / 4.0, 1.0 / 4.0]]),
            Method::Radau5 => {
                let s6 = 6f64.sqrt();
                Tableau::full(&[
                    &[
                        (88.0 - 7.0 * s6) / 360.0,
                        (296.0 - 169.0 * s6) / 1800.0,
                        (-2.0 + 3.0 * s6) / 225.0,
                    ],
                    &[
                        (296.0 + 169.0 * s6) / 1800.0,
                        (88.0 + 7.0 * s6) / 360.0,
                        (-2.0 - 3.0 * s6) / 225.0,
                    ],
                    &[(16.0 - s6) / 36.0, (16.0 + s6) / 36.0, 1.0 / 9.0],
                ])
            }
        }
    }
}

/// Butcher tableau of a stiffly accurate implicit Runge-Kutta method.
#[derive(Debug, Clone, PartialEq)]
struct Tableau {
    /// Full A matrix, row-major s x s.
    a: Vec<f64>,
    c: Vec<f64>,
    s: usize,
    /// Diagonally implicit: every diagonal entry is `gamma` (the first may be
    /// 0, an explicit stage), and A is lower triangular.
    diagonal: bool,
    gamma: f64,
    /// `b - b_hat` for an embedded lower-order solution (error estimate).
    d: Option<Vec<f64>>,
}

impl Tableau {
    /// A diagonally implicit method from the strictly lower rows of A (row i
    /// has i entries) and the diagonal `gamma`. The first stage is explicit
    /// (a_00 = 0) unless [`Tableau::with_implicit_first`].
    fn dirk(gamma: f64, lower: &[&[f64]]) -> Tableau {
        let s = lower.len();
        let mut a = vec![0.0; s * s];
        for (i, row) in lower.iter().enumerate() {
            assert_eq!(row.len(), i);
            a[i * s..i * s + i].copy_from_slice(row);
            if i > 0 {
                a[i * s + i] = gamma;
            }
        }
        Tableau::finish(a, s, true, gamma)
    }

    fn with_implicit_first(mut self) -> Tableau {
        self.a[0] = self.gamma;
        self.c[0] = self.gamma;
        self
    }

    fn full(rows: &[&[f64]]) -> Tableau {
        let s = rows.len();
        let a: Vec<f64> = rows.iter().flat_map(|r| r.iter().copied()).collect();
        assert_eq!(a.len(), s * s);
        Tableau::finish(a, s, false, 0.0)
    }

    fn finish(a: Vec<f64>, s: usize, diagonal: bool, gamma: f64) -> Tableau {
        let c = (0..s).map(|i| a[i * s..(i + 1) * s].iter().sum()).collect();
        Tableau {
            a,
            c,
            s,
            diagonal,
            gamma,
            d: None,
        }
    }

    /// With an embedded solution of weights `b_hat`.
    fn with_embedded(mut self, b_hat: &[f64]) -> Tableau {
        let s = self.s;
        assert_eq!(b_hat.len(), s);
        let b = &self.a[(s - 1) * s..];
        self.d = Some(b.iter().zip(b_hat).map(|(x, y)| x - y).collect());
        self
    }

    fn explicit_first(&self) -> bool {
        self.a[0] == 0.0
    }

    /// A^-1 (fully implicit methods), row-major.
    fn inverse(&self) -> Vec<f64> {
        let s = self.s;
        let mut m = Matrix::zeros(s);
        for i in 0..s {
            for j in 0..s {
                m.set(i, j, self.a[i * s + j]);
            }
        }
        let lu = crate::linalg::Lu::factor(&m).expect("Radau A is invertible");
        let mut w = vec![0.0; s * s];
        let mut work = vec![0.0; s];
        for j in 0..s {
            let mut col = vec![0.0; s];
            col[j] = 1.0;
            lu.solve(&mut col, &mut work);
            for i in 0..s {
                w[i * s + j] = col[i];
            }
        }
        w
    }
}

/// The input over one step, as a polynomial in the step fraction theta (0 at
/// the step's start, 1 at its end): Lagrange interpolation through up to six
/// samples at integer theta offsets.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct StepInput {
    vals: [f64; 6],
    /// Offset (in samples, relative to the step's start) of `vals[0]`.
    first: i32,
    len: usize,
}

impl StepInput {
    /// Straight line from `u0` to `u1`.
    pub fn linear(u0: f64, u1: f64) -> StepInput {
        StepInput {
            vals: [u0, u1, 0.0, 0.0, 0.0, 0.0],
            first: 0,
            len: 2,
        }
    }

    /// Through `vals`, the samples at offsets `first`, `first + 1`, ... (the
    /// step runs from offset 0 to 1, which must be among them).
    pub fn lagrange(vals: &[f64], first: i32) -> StepInput {
        assert!((2..=6).contains(&vals.len()) && first <= 0 && first + vals.len() as i32 >= 2);
        let mut v = [0.0; 6];
        v[..vals.len()].copy_from_slice(vals);
        StepInput {
            vals: v,
            first,
            len: vals.len(),
        }
    }

    /// The input at step fraction `theta`. Exact at the sample offsets.
    pub fn at(&self, theta: f64) -> f64 {
        let mut sum = 0.0;
        for j in 0..self.len {
            let oj = (self.first + j as i32) as f64;
            let mut l = 1.0;
            for m in 0..self.len {
                if m != j {
                    let om = (self.first + m as i32) as f64;
                    l *= (theta - om) / (oj - om);
                }
            }
            sum += l * self.vals[j];
        }
        sum
    }
}

/// Solver settings.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct Options {
    pub method: Method,
    pub solver: Solver,
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
    /// How [`simulate`] interpolates the input between samples at stage
    /// times inside a step: 1 = linear (ngspice's PWL source; the default),
    /// 3 or 5 = Lagrange through the 4 or 6 nearest samples. Only methods
    /// with stages inside the step (all but trap and euler) see a difference.
    pub input_order: usize,
    /// Initial guess for a diagonally implicit method's later stages:
    /// 1 = the previous two samples extrapolated linearly (as for the first
    /// stage), 2 = the quadratic through those two and the latest stage
    /// solved in this step. 2 (the default) takes 11-23% fewer Newton
    /// iterations with esdirk4 on the 670.
    pub predictor: usize,
    /// Local error control (methods with an embedded solution: esdirk4).
    /// After each step the error estimate on every node voltage is compared
    /// with `error_abstol + error_reltol * |v|`; a step that fails is redone
    /// as two half steps, recursively, at most `max_error_halvings` times
    /// (and at most `max_halvings`; the deepest level is accepted as it
    /// is). The output stays on the
    /// sample grid. `error_abstol = 0` turns it off (the default).
    pub error_abstol: f64,
    pub error_reltol: f64,
    pub max_error_halvings: u32,
    /// With error control: choose each substep's size from the error
    /// estimate (see [`Transient::advance_selected`]) instead of halving a
    /// rejected step recursively from the sample's starting level.
    pub step_selection: bool,
    /// What the error estimate is measured on (see [`ErrorNorm`]).
    pub error_norm: ErrorNorm,
    /// Keep every unknown current at every step ([`Transient::x`]); without
    /// it the DK solver only computes the probes' unknowns at a step's end
    /// (the rest of `x` is stale), which is all a run's output needs.
    /// [`Transient::update`] needs every unknown. The full-MNA solver
    /// always has them.
    pub all_unknowns: bool,
    /// DK solver: reuse the factored Newton matrix across iterations,
    /// stages and steps until convergence slows, and skip re-evaluating
    /// devices whose ports moved less than the tolerance (see
    /// `dk::DkNewton`). Off: Newton refactors every iteration and evaluates
    /// every device, like the full-MNA solver.
    pub newton_reuse: bool,
    /// Evaluate variable-mu triodes and banks of triodes from tables of the
    /// same model ([`crate::devices::TriodeTable`]: within ~1e-7 of the exact
    /// current, ~40x cheaper for a bank of four 6386s). Off by default: a
    /// setting for fast draft runs.
    pub tube_tables: bool,
}

impl Default for Options {
    fn default() -> Self {
        Options {
            method: Method::Trapezoidal,
            solver: Solver::Dk,
            reltol: 1e-6,
            vntol: 1e-6,
            max_iter: 50,
            max_iter_dc: 200,
            max_halvings: 8,
            gmin: SPICE_GMIN,
            extrapolate: true,
            input_order: 1,
            predictor: 2,
            error_abstol: 0.0,
            error_reltol: 0.0,
            max_error_halvings: 4,
            step_selection: true,
            error_norm: ErrorNorm::Nodes,
            all_unknowns: true,
            newton_reuse: true,
            tube_tables: false,
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
            && self.max_halvings <= 30
            && matches!(self.input_order, 1 | 3 | 5)
            && matches!(self.predictor, 1 | 2)
            && self.error_abstol.is_finite()
            && self.error_abstol >= 0.0
            && self.error_reltol.is_finite()
            && self.error_reltol >= 0.0;
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
    /// Samples stepped, and steps accepted at less than the full step.
    pub steps: u64,
    pub substeps: u64,
    /// Samples that took more than one step (Newton or error halvings).
    pub halved_steps: u64,
    /// Steps (or substeps) redone because of the error estimate.
    pub error_rejections: u64,
    /// Accepted steps and error rejections by halving level (0 = the full
    /// step; the last entry counts that level and deeper ones).
    pub accepted_by_level: [u64; LEVEL_STATS],
    pub rejected_by_level: [u64; LEVEL_STATS],
    /// Newton solves (one per implicit stage of a diagonally implicit
    /// method, one per step otherwise) and iterations over all steps (DC
    /// excluded). `max_iterations` is per solve.
    pub solves: u64,
    pub iterations: u64,
    pub max_iterations: usize,
    /// How the DC operating point was found: "newton", "gmin" or "source".
    pub dc_method: &'static str,
    pub dc_iterations: usize,
    /// The solver that ran ("dk" or "mna"; see [`Solver`]).
    pub solver: &'static str,
    /// Size of the Newton system (device ports for DK, device nodes for
    /// MNA) and of the eliminated linear part (all unknowns for DK, the
    /// rest for MNA).
    pub nonlinear_unknowns: usize,
    pub linear_unknowns: usize,
    /// DK only: size of the state (rows of C with any entry), device
    /// evaluations and Newton matrix factorizations.
    pub states: usize,
    pub device_evaluations: u64,
    pub factorizations: u64,
    /// DK with Jacobian reuse: stage solves that failed with the lagged
    /// Jacobian and were redone with exact Newton (before any halving).
    pub exact_retries: u64,
}

/// The step machinery of a fully implicit method: s coupled copies.
#[derive(Debug)]
struct Coupled {
    /// A^-1 of the tableau, and its row sums.
    w: Vec<f64>,
    w_sum: Vec<f64>,
    newton: Newton,
    nodes: Vec<usize>,
    // Scratch, s x n.
    rhs: Vec<f64>,
    y: Vec<f64>,
    x: Vec<f64>,
}

/// Why a step attempt was rejected.
#[derive(Debug, Clone, Copy, PartialEq)]
enum StepFail {
    Newton(Failure),
    /// The error estimate exceeded the tolerance, by this factor (the
    /// largest error / tolerance over the node voltages).
    Inaccurate(f64),
    /// The DK solver's step matrix is singular at this unknown.
    Matrix(usize),
}

impl From<Failure> for StepFail {
    fn from(f: Failure) -> Self {
        StepFail::Newton(f)
    }
}

/// The DK solver's systems and state (see `dk.rs`).
#[derive(Debug)]
struct Dk {
    ports: Ports,
    /// Rows of C with any entry: the state.
    support: Vec<usize>,
    /// C on those rows and columns.
    css: SparseRows,
    /// DK system per halving level (built on first use), and one more for the
    /// remainder of a sample after a restart ([`Transient::rest_slot`]).
    levels: Vec<Option<DkSystem>>,
    /// Backward Euler's, per level (the first step after an update).
    levels_be: Vec<Option<DkSystem>>,
    newton: DkNewton,
    /// `x_S` and `F_S` at `x`.
    xs: Vec<f64>,
    f: Vec<f64>,
    /// Stage F values (s x r).
    stage_f: Vec<f64>,
    /// Port voltages at `x_prev` (those at `x` are `Transient::ports`).
    v_prev: Vec<f64>,
    // Scratch.
    /// The step's start on every row of the DK responses.
    base: Vec<f64>,
    /// Stage inputs `(1/g) sum_j a_ij F_j`.
    w: Vec<f64>,
    /// Port voltages and state of a stage (m + r).
    out: Vec<f64>,
    v: Vec<f64>,
    d: Vec<f64>,
    neg: Vec<f64>,
    wm: Vec<f64>,
    /// Values of the time-varying sources (sine sources, then externals, then
    /// noise columns) at the latest stage's time.
    wv: Vec<f64>,
    /// A stage's initial guess and limiting reference, for an exact retry.
    v_guess: Vec<f64>,
    v_lin_guess: Vec<f64>,
    /// The probes' unknowns (first in the DK systems' third block), the end
    /// point's unknowns in that block's order, and for the ports-and-states
    /// error norm: the estimate and the new values on ports then states, and
    /// which of those it measures (ports, and states that are nodes).
    probes: Vec<usize>,
    xu: Vec<f64>,
    e_ps: Vec<f64>,
    v_ps: Vec<f64>,
    keep_ps: Vec<bool>,
}

impl Dk {
    /// The DK solver's state for `mna`, stepped by a method of `stages` stages.
    fn new(mna: &Mna, opts: &Options, stages: usize) -> Dk {
        let ports = Ports::new(&mna.devices);
        let support = dk::support(&mna.c);
        let (m, r) = (ports.len(), support.len());
        let mut css = Matrix::zeros(r);
        for (i, &si) in support.iter().enumerate() {
            for (j, &sj) in support.iter().enumerate() {
                css.set(i, j, mna.c.get(si, sj));
            }
        }
        Dk {
            newton: DkNewton::new(&ports, opts.newton_reuse),
            ports,
            css: SparseRows::new(&css),
            levels: vec![None; opts.max_halvings as usize + 2],
            levels_be: vec![None; opts.max_halvings as usize + 1],
            xs: vec![0.0; r],
            f: vec![0.0; r],
            stage_f: vec![0.0; stages * r],
            v_prev: vec![0.0; m],
            base: Vec::new(),
            w: vec![0.0; r],
            out: vec![0.0; m + r],
            v: vec![0.0; m],
            d: vec![0.0; r],
            neg: vec![0.0; m.max(r)],
            wm: vec![0.0; m],
            wv: vec![
                0.0;
                mna.waves.len()
                    + mna.externals.len()
                    + mna.noise.as_ref().map_or(0, |n| n.columns.len())
            ],
            v_guess: vec![0.0; m],
            v_lin_guess: vec![0.0; m],
            probes: mna
                .probes
                .iter()
                .filter_map(|(_, i)| *i)
                .chain(mna.outputs.iter().copied())
                .collect(),
            xu: vec![0.0; mna.len()],
            e_ps: vec![0.0; m + r],
            v_ps: vec![0.0; m + r],
            keep_ps: (0..m)
                .map(|_| true)
                .chain(
                    support
                        .iter()
                        .map(|&k| matches!(mna.unknowns[k], crate::mna::Unknown::Node(_))),
                )
                .collect(),
            support,
        }
    }
}

/// A transient run in progress; `step` advances it one sample.
#[derive(Debug)]
pub struct Transient {
    mna: Mna,
    opts: Options,
    tab: Tableau,
    h: f64,
    device_nodes: Vec<usize>,
    newton: Newton,
    coupled: Option<Coupled>,
    dk: Option<Dk>,
    /// Reduced step matrix per halving level (built on first use).
    levels: Vec<Option<Reduced>>,
    /// Backward Euler's tableau and step systems, for the sample after an update.
    tab_be: Tableau,
    levels_be: Vec<Option<Reduced>>,
    /// The next sample restarts at first order (set by `update`).
    restart: bool,
    x: Vec<f64>,
    x_prev: Vec<f64>,
    /// Step that led to `x` (0 before the first step: nothing to extrapolate).
    h_prev: f64,
    /// `C x` and `F = C x'` at `x`.
    cx: Vec<f64>,
    f: Vec<f64>,
    /// Port voltages of every device at `x` (layout of `Newton::v_lin`).
    ports: Vec<f64>,
    u: f64,
    /// Samples stepped so far (the sample index of `x`).
    n: u64,
    /// The externals' values ([`Mna::externals`]) at the start and the end of
    /// the next sample, linear in between.
    ext0: Vec<f64>,
    ext1: Vec<f64>,
    /// Whether `x` holds every unknown (else only the probes' and outputs' are
    /// current: a DK step without `Options::all_unknowns`).
    x_full: bool,
    /// Deepest halving level accepted in the current sample, and in the
    /// previous one (where error control starts the next).
    deepest: usize,
    level_hint: usize,
    /// The step-selecting controller's level for the next sample, and the
    /// error ratio of the last accepted step (NaN: not checked).
    next_level: usize,
    err_ratio: f64,
    stats: Stats,
    // Scratch.
    rhs: Vec<f64>,
    y: Vec<f64>,
    rn: Vec<f64>,
    xn: Vec<f64>,
    x_new: Vec<f64>,
    cx_new: Vec<f64>,
    work: Vec<f64>,
    /// Stage F values (s x n) of a diagonally implicit step.
    stage_f: Vec<f64>,
    /// Which unknowns are node voltages (the error control looks at those).
    is_node: Vec<bool>,
    err: Vec<f64>,
    /// The ports-and-states error norm's layout for the full-MNA solver.
    norm_ps: NormPs,
}

/// Ports and state nodes, as the DK solver's ports-and-states error norm
/// sees them, for the full-MNA solver: the same decisions from the same
/// estimate.
#[derive(Debug)]
struct NormPs {
    ports: Ports,
    states: Vec<usize>,
    keep: Vec<bool>,
    e: Vec<f64>,
    v: Vec<f64>,
}

impl NormPs {
    fn new(mna: &Mna) -> NormPs {
        let ports = Ports::new(&mna.devices);
        let states = dk::support(&mna.c);
        let m = ports.len();
        let keep = (0..m)
            .map(|_| true)
            .chain(
                states
                    .iter()
                    .map(|&k| matches!(mna.unknowns[k], crate::mna::Unknown::Node(_))),
            )
            .collect();
        let len = m + states.len();
        NormPs {
            ports,
            states,
            keep,
            e: vec![0.0; len],
            v: vec![0.0; len],
        }
    }
}

impl Transient {
    /// Solve the DC operating point with input `u0`, ready to step by `h`.
    pub fn new(mna: Mna, h: f64, opts: Options, u0: f64) -> Result<Transient, Error> {
        let ext = vec![0.0; mna.externals.len()];
        Transient::with_externals(mna, h, opts, u0, &ext)
    }

    /// As [`Transient::new`], with the externals ([`Mna::externals`]) at
    /// `ext` for the DC operating point (and until [`Transient::set_externals`]).
    pub fn with_externals(
        mut mna: Mna,
        h: f64,
        opts: Options,
        u0: f64,
        ext: &[f64],
    ) -> Result<Transient, Error> {
        if !(h.is_finite() && h > 0.0) {
            return Err(Error::new(format!("time step {h} must be > 0")));
        }
        opts.check()?;
        if ext.len() != mna.externals.len() {
            return Err(Error::new(format!(
                "{} external values for {} externals",
                ext.len(),
                mna.externals.len()
            )));
        }
        if (!mna.externals.is_empty() || mna.noise.is_some() || mna.heat.is_some())
            && (opts.solver != Solver::Dk || !opts.method.tableau().diagonal)
        {
            return Err(Error::new(
                "externals (control inputs, a partition's couplings), noise and heated \
                 cathodes need the DK solver and a diagonally implicit method",
            ));
        }
        if let Some(noise) = &mut mna.noise {
            noise.set_step(h).map_err(Error::new)?;
        }
        if opts.tube_tables {
            mna.tabulate_tubes();
        }
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
        let tab = opts.method.tableau();
        let coupled = (!tab.diagonal).then(|| {
            let s = tab.s;
            let w = tab.inverse();
            let w_sum = (0..s).map(|i| w[i * s..(i + 1) * s].iter().sum()).collect();
            Coupled {
                w,
                w_sum,
                newton: Newton::with_copies(&mna.devices, &device_nodes, s),
                nodes: Newton::copy_nodes(&device_nodes, s, n),
                rhs: vec![0.0; s * n],
                y: vec![0.0; s * n],
                x: vec![0.0; s * n],
            }
        });
        let ports = vec![0.0; newton.v_lin.len()];
        let s = tab.s;
        let dk = (opts.solver == Solver::Dk && tab.diagonal).then(|| Dk::new(&mna, &opts, s));
        let mut tr = Transient {
            opts,
            h,
            newton,
            coupled,
            dk,
            levels: vec![None; opts.max_halvings as usize + 2],
            tab_be: Method::BackwardEuler.tableau(),
            levels_be: vec![None; opts.max_halvings as usize + 1],
            restart: false,
            x: vec![0.0; n],
            x_prev: vec![0.0; n],
            h_prev: 0.0,
            cx: vec![0.0; n],
            f: vec![0.0; n],
            ports,
            u: u0,
            n: 0,
            ext0: ext.to_vec(),
            ext1: ext.to_vec(),
            x_full: true,
            deepest: 0,
            level_hint: 0,
            next_level: 0,
            err_ratio: f64::NAN,
            stats: Stats::default(),
            rhs: vec![0.0; n],
            y: vec![0.0; n],
            rn: vec![0.0; n],
            xn: vec![0.0; n],
            x_new: vec![0.0; n],
            cx_new: vec![0.0; n],
            work: vec![0.0; n],
            stage_f: if tab.diagonal {
                vec![0.0; s * n]
            } else {
                Vec::new()
            },
            is_node: mna
                .unknowns
                .iter()
                .map(|u| matches!(u, crate::mna::Unknown::Node(_)))
                .collect(),
            err: vec![0.0; n],
            norm_ps: NormPs::new(&mna),
            tab,
            device_nodes,
            mna,
        };
        // Heated cathodes: the start's temperature for the DC point.
        tr.apply_heat();
        tr.dc(u0)?;
        // The noise sources' first amplitudes, at the operating point (itself noise-free).
        tr.observe_noise();
        Ok(tr)
    }

    /// Give the heated tubes the temperature, and have DK evaluate them afresh.
    fn apply_heat(&mut self) {
        let Some(heat) = &mut self.mna.heat else {
            return;
        };
        heat.set_t = heat.t_k;
        for &d in &heat.tubes {
            self.mna.devices[d].device.set_cathode(heat.t_k);
            if let Some(dk) = &mut self.dk {
                dk.newton.invalidate_device(d);
            }
        }
    }

    /// Before sample `n`: the cathodes' temperature one step on (the heater at its ratio
    /// times the mains wander), the tubes refreshed when it moved.
    fn advance_heat(&mut self) {
        let Some(heat) = &self.mna.heat else {
            return;
        };
        let m = self.mna.noise.as_ref().map_or(0.0, |n| n.mains_m(0.0));
        let ratio = heat.spec.heater_ratio * (1.0 + m);
        let h = self.h;
        let heat = self.mna.heat.as_mut().expect("checked");
        heat.step(h, ratio);
        if heat.stale() {
            self.apply_heat();
        }
    }

    /// The noise sources take the tubes' gm and currents at the operating point.
    fn observe_noise(&mut self) {
        if let (Some(noise), Some(dk)) = (&mut self.mna.noise, &self.dk) {
            noise.observe(&self.mna.devices, &dk.ports.offsets, &self.ports);
        }
    }

    /// ... and after a step, from the DK solve's own last evaluation (the port currents
    /// at the solution, the Jacobians within its tolerance): no device is evaluated again.
    fn observe_noise_step(&mut self) {
        if let (Some(noise), Some(dk)) = (&mut self.mna.noise, &self.dk) {
            let (ports, newton) = (&dk.ports, &dk.newton);
            let jac = newton.jacobians();
            noise.observe_with(|d| {
                let (o, np, go) = (ports.offsets[d], ports.widths[d], ports.g_offset(d));
                let (mut i, mut g) = ([0.0; 4], [0.0; 16]);
                i[..np].copy_from_slice(&newton.i[o..o + np]);
                g[..np * np].copy_from_slice(&jac[go..go + np * np]);
                (i, g)
            });
        }
    }

    /// The DC operating point: plain Newton, then gmin stepping, then source
    /// stepping.
    fn dc(&mut self, u0: f64) -> Result<(), Error> {
        // Capacitors with a start voltage are held at it here (Mna::dc_starts): a
        // Norton source of DC_START_S across each, in this solve's matrix only.
        let mut g_start;
        let g = if self.mna.dc_starts.is_empty() {
            &self.mna.g
        } else {
            g_start = self.mna.g.clone();
            for &(a, b, _) in &self.mna.dc_starts {
                if let Some(i) = a {
                    g_start.add(i, i, DC_START_S);
                }
                if let Some(j) = b {
                    g_start.add(j, j, DC_START_S);
                }
                if let (Some(i), Some(j)) = (a, b) {
                    g_start.add(i, j, -DC_START_S);
                    g_start.add(j, i, -DC_START_S);
                }
            }
            &g_start
        };
        let sys = Reduced::new(g, &self.device_nodes);
        let nn = sys.n_len();
        let nl = sys.l_len();
        let mut base = self.mna.b.clone();
        for &(a, b, v0) in &self.mna.dc_starts {
            if let Some(i) = a {
                base[i] += DC_START_S * v0;
            }
            if let Some(j) = b {
                base[j] -= DC_START_S * v0;
            }
        }
        base[self.mna.input_row] += u0;
        self.mna.add_waves(0.0, &mut base);
        for (&row, &e) in self.mna.externals.iter().zip(&self.ext0) {
            base[row] += e;
        }
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
        self.mna.c_sparse.mul_vec(&self.x, &mut self.cx);
        self.f.fill(0.0);
        self.stats.dc_method = method;
        self.stats.dc_iterations = iterations;
        self.stats.solver = "mna";
        self.stats.nonlinear_unknowns = nn;
        self.stats.linear_unknowns = nl;
        if let Some(dk) = &mut self.dk {
            for (v, &s) in dk.xs.iter_mut().zip(&dk.support) {
                *v = self.x[s];
            }
            dk.f.fill(0.0);
            dk.v_prev.copy_from_slice(&self.ports);
            self.stats.solver = "dk";
            self.stats.nonlinear_unknowns = dk.ports.len();
            self.stats.linear_unknowns = self.x.len();
            self.stats.states = dk.support.len();
        }
        Ok(())
    }

    /// Tell every device its port voltages at the accepted point `x`.
    fn accept_ports(&mut self) {
        let mut off = 0;
        for (d, inst) in self.mna.devices.iter_mut().enumerate() {
            let np = inst.device.ports();
            inst.device.accept(&self.ports[off..off + np]);
            if inst.device.has_state()
                && let Some(dk) = &mut self.dk
            {
                dk.newton.invalidate_device(d);
            }
            off += np;
        }
        self.observe_noise_step();
    }

    /// Advance one step to the time where the input is `u`, the input
    /// linear in between.
    pub fn step(&mut self, u: f64) -> Result<(), Error> {
        self.step_input(&StepInput::linear(self.u, u))
    }

    /// Advance one step with the input `inp` over it (`inp.at(0)` should be
    /// the previous step's end input).
    pub fn step_input(&mut self, inp: &StepInput) -> Result<(), Error> {
        let substeps_before = self.stats.substeps;
        if let Some(noise) = &mut self.mna.noise {
            noise.begin_sample(self.n);
        }
        self.advance_heat();
        self.deepest = 0;
        let res = if self.restart {
            self.restart_sample(inp)
        } else if self.opts.error_abstol > 0.0 && self.opts.step_selection {
            self.advance_selected(inp)
        } else {
            // With error control, start one level above the deepest the
            // previous sample needed (fewer rejected attempts through a hard
            // passage, and back to full steps one level per sample after it).
            let start = if self.opts.error_abstol > 0.0 {
                self.level_hint.saturating_sub(1)
            } else {
                0
            };
            let m = 1usize << start;
            let mut res = Ok(());
            for j in 0..m {
                let (a, b) = (j as f64 / m as f64, (j + 1) as f64 / m as f64);
                res = self.advance(start, a, b, inp);
                if res.is_err() {
                    break;
                }
            }
            self.level_hint = self.deepest;
            res
        };
        self.stats.steps += 1;
        if self.stats.substeps > substeps_before {
            self.stats.halved_steps += 1;
        }
        self.n += 1;
        res.map_err(|(level, f)| {
            let what = format!(
                "transient step to t = {:.9e} s (sample {}, after {} halvings)",
                self.n as f64 * self.h,
                self.n,
                level
            );
            match (f, &self.dk) {
                (StepFail::Matrix(unknown), _) => Error::new(format!(
                    "{what}: step matrix singular at the {} (a loop of sources and inductors?)",
                    self.mna.unknowns[unknown].describe()
                )),
                (StepFail::Newton(f), Some(dk)) => self.port_failure_error(&dk.ports, f, &what),
                (StepFail::Newton(f), None) => {
                    let sys = self.levels[level].as_ref().expect("built");
                    self.failure_error(sys, f, &what)
                }
                (StepFail::Inaccurate(_), _) => unreachable!("inaccurate steps are redone"),
            }
        })
    }

    /// Advance through one sample in substeps of `h / 2^level` whose level
    /// the error estimate selects (`Options::step_selection`):
    ///
    /// - a step rejected with error ratio q (error / tolerance > 1) is redone
    ///   at the level predicted to bring q to [`REFINE_TARGET`], at least
    ///   one level deeper ([`refine_levels`]);
    /// - after an accepted substep with ratio q, the next one may be coarser
    ///   by up to [`MAX_COARSEN`] levels ([`coarsen_levels`]), where the
    ///   substep grid allows it (a substep of level l starts at a multiple of
    ///   h / 2^l);
    /// - the next sample starts at the level the last substep chose.
    ///
    /// So a local event (a grid starting to conduct) costs the substeps it
    /// needs, and the steps after it go back to full size as soon as the
    /// estimate allows, not one level per sample. Newton failures halve, as
    /// in [`Transient::advance`]. Substeps at the deepest error level are
    /// accepted without the error check, as there.
    fn advance_selected(&mut self, inp: &StepInput) -> Result<(), (usize, StepFail)> {
        let top = self.opts.max_halvings as usize;
        let err_top = self.opts.max_error_halvings.min(self.opts.max_halvings) as usize;
        let end = 1u64 << top;
        let mut pos = 0u64; // in units of h / 2^top
        let mut level = self.next_level.min(err_top);
        while pos < end {
            // The coarsest level at or below `level` that this position allows.
            while !pos.is_multiple_of(1u64 << (top - level)) {
                level += 1;
            }
            let len = 1u64 << (top - level);
            let (th0, th1) = (pos as f64 / end as f64, (pos + len) as f64 / end as f64);
            let res = if self.dk.is_some() {
                self.try_step_dk(level, th0, th1, inp)
            } else if self.tab.diagonal {
                self.try_step_dirk(level, th0, th1, inp)
            } else {
                self.try_step_coupled(level, th0, th1, inp)
            };
            match res {
                Ok(()) => {
                    pos += len;
                    let q = self.err_ratio;
                    // Not checked (the deepest error level): one up.
                    let up = if q.is_nan() { 1 } else { coarsen_levels(q) };
                    level -= up.min(level);
                }
                Err(StepFail::Inaccurate(q)) => {
                    self.reject(level);
                    level = (level + refine_levels(q)).min(err_top);
                }
                Err(f @ StepFail::Matrix(_)) => return Err((level, f)),
                Err(f @ StepFail::Newton(_)) if level >= top => return Err((level, f)),
                Err(StepFail::Newton(_)) => level += 1,
            }
        }
        self.next_level = level;
        Ok(())
    }

    /// The sample after an update: backward Euler over its first h / 2^RESTART_LEVEL
    /// (halving on failure, as any step), then the method over the rest in one step
    /// (its own step system, [`Transient::rest_slot`]; in doubling substeps if that
    /// fails or misses the error tolerance).
    ///
    /// Why: `update` carries every node voltage over, but a change can make a mode
    /// fast (a pot's section from kOhms to its 1 mOhm end, next to a series
    /// capacitor), and the derivative at the carried point is then far outside what
    /// the capacitors can hold (~100 A through 1 mOhm). An explicit first stage
    /// injects it as charge: a thump of tens of volts (DEVICE_BUILDER_PLAN.md B6,
    /// "Pot end stop"). Backward Euler's stage takes no derivative in and settles
    /// the change as a switch does (fast modes within the step, charges held), and
    /// the method resumes from that stage's derivative. SPICE restarts at first
    /// order after a breakpoint the same way.
    fn restart_sample(&mut self, inp: &StepInput) -> Result<(), (usize, StepFail)> {
        let lb = RESTART_LEVEL.min(self.opts.max_halvings as usize);
        let end = 1.0 / (1u64 << lb) as f64;
        self.swap_backward_euler();
        let res = self.advance(lb, 0.0, end, inp);
        self.swap_backward_euler();
        res?;
        self.restart = false;
        // Don't extrapolate the switching step's jump into the next guess.
        self.h_prev = 0.0;
        if lb == 0 {
            return Ok(());
        }
        let rest = self.rest_slot();
        let res = if self.dk.is_some() {
            self.try_step_dk(rest, end, 1.0, inp)
        } else {
            self.try_step_dirk(rest, end, 1.0, inp)
        };
        match res {
            Ok(()) => Ok(()),
            Err(f @ StepFail::Matrix(_)) => Err((0, f)),
            Err(f) => {
                if let StepFail::Inaccurate(_) = f {
                    self.reject(0);
                }
                for k in (1..=lb).rev() {
                    let a = 1.0 / (1u64 << k) as f64;
                    self.advance(k, a, 2.0 * a, inp)?;
                }
                Ok(())
            }
        }
    }

    /// The step-system slot of a restart's remainder (a step of its own length).
    fn rest_slot(&self) -> usize {
        self.opts.max_halvings as usize + 1
    }

    /// The step length of `level` over step fractions `th0..th1`: h / 2^level, or
    /// the span itself for the restart's remainder.
    fn step_len(&self, level: usize, th0: f64, th1: f64) -> f64 {
        if level == self.rest_slot() {
            self.h * (th1 - th0)
        } else {
            self.h / (1u64 << level) as f64
        }
    }

    /// Swap the method for backward Euler (tableau and step systems), and back.
    fn swap_backward_euler(&mut self) {
        std::mem::swap(&mut self.tab, &mut self.tab_be);
        std::mem::swap(&mut self.levels, &mut self.levels_be);
        if let Some(dk) = &mut self.dk {
            std::mem::swap(&mut dk.levels, &mut dk.levels_be);
        }
    }

    /// Advance by `h / 2^level`, over step fractions `th0` to `th1` of
    /// `inp`, halving on failure.
    fn advance(
        &mut self,
        level: usize,
        th0: f64,
        th1: f64,
        inp: &StepInput,
    ) -> Result<(), (usize, StepFail)> {
        let res = if self.dk.is_some() {
            self.try_step_dk(level, th0, th1, inp)
        } else if self.tab.diagonal {
            self.try_step_dirk(level, th0, th1, inp)
        } else {
            self.try_step_coupled(level, th0, th1, inp)
        };
        match res {
            Ok(()) => return Ok(()),
            Err(StepFail::Inaccurate(_)) => self.reject(level),
            Err(f @ StepFail::Matrix(_)) => return Err((level, f)),
            Err(f @ StepFail::Newton(_)) if level as u32 >= self.opts.max_halvings => {
                return Err((level, f));
            }
            Err(StepFail::Newton(_)) => {}
        }
        let tm = 0.5 * (th0 + th1);
        self.advance(level + 1, th0, tm, inp)?;
        self.advance(level + 1, tm, th1, inp)
    }

    /// Time at step fraction `theta` of the current sample (the sine sources'
    /// argument).
    fn time(&self, theta: f64) -> f64 {
        (self.n as f64 + theta) * self.h
    }

    fn newton_options(&self) -> NewtonOptions {
        NewtonOptions {
            reltol: self.opts.reltol,
            vntol: self.opts.vntol,
            max_iter: self.opts.max_iter,
            gshunt: 0.0,
        }
    }

    /// Slope for the initial guess `x + slope * c * (x - x_prev)` at stage
    /// time fraction c of a step of `hk`.
    fn extrapolation(&self, hk: f64) -> f64 {
        if self.opts.extrapolate && self.h_prev > 0.0 {
            hk / self.h_prev
        } else {
            0.0
        }
    }

    fn count(&mut self, iterations: usize) {
        if let Some(dk) = &self.dk {
            self.stats.device_evaluations = dk.newton.evaluations;
            self.stats.factorizations = dk.newton.factorizations;
        }
        self.stats.solves += 1;
        self.stats.iterations += iterations as u64;
        self.stats.max_iterations = self.stats.max_iterations.max(iterations);
    }

    /// Accept `x_new` / `cx_new` as the step's end point, reached by `hk`.
    fn accept(&mut self, level: usize, hk: f64, u: f64) {
        std::mem::swap(&mut self.x_prev, &mut self.x);
        std::mem::swap(&mut self.x, &mut self.x_new);
        if self.dk.is_none() {
            std::mem::swap(&mut self.cx, &mut self.cx_new);
        }
        self.h_prev = hk;
        self.u = u;
        self.accept_ports();
        self.deepest = self.deepest.max(level);
        if level > 0 {
            self.stats.substeps += 1;
        }
        self.stats.accepted_by_level[level.min(LEVEL_STATS - 1)] += 1;
    }

    /// A step at `level` rejected by the error estimate.
    fn reject(&mut self, level: usize) {
        self.stats.error_rejections += 1;
        self.stats.rejected_by_level[level.min(LEVEL_STATS - 1)] += 1;
    }

    fn try_step_dirk(
        &mut self,
        level: usize,
        th0: f64,
        th1: f64,
        inp: &StepInput,
    ) -> Result<(), StepFail> {
        let hk = self.step_len(level, th0, th1);
        let n = self.x.len();
        let s = self.tab.s;
        let g = self.tab.gamma;
        let inv = 1.0 / (g * hk);
        if self.levels[level].is_none() {
            let a = self.mna.g.plus_scaled(inv, &self.mna.c);
            self.levels[level] = Some(Reduced::new(&a, &self.device_nodes));
        }
        let sys = self.levels[level].as_ref().expect("just built");
        // A restart's remainder counts as a full step (error control, stats).
        let level = if level == self.rest_slot() { 0 } else { level };
        let (nn, nl) = (sys.n_len(), sys.l_len());
        let slope = self.extrapolation(hk);
        let opts = self.newton_options();
        self.newton.v_lin.copy_from_slice(&self.ports);

        // Newton iterations per implicit stage, counted once the step succeeds.
        let mut iterations = [0usize; 8];
        let mut solves = 0;
        // Step fraction of the latest solved stage (its N values stay in xn).
        let mut c_last: Option<f64> = None;
        for i in 0..s {
            let fi = i * n;
            if i == 0 && self.tab.explicit_first() {
                // The previous end point, and its F.
                self.stage_f[..n].copy_from_slice(&self.f);
                continue;
            }
            let ci = self.tab.c[i];
            for ((r, b), cx) in self.rhs.iter_mut().zip(&self.mna.b).zip(&self.cx) {
                *r = b + inv * cx;
            }
            let th = th0 + ci * (th1 - th0);
            self.rhs[self.mna.input_row] += inp.at(th);
            self.mna.add_waves(self.time(th), &mut self.rhs);
            for j in 0..i {
                let coef = self.tab.a[i * s + j] / g;
                if coef != 0.0 {
                    let fj = &self.stage_f[j * n..(j + 1) * n];
                    for (r, f) in self.rhs.iter_mut().zip(fj) {
                        *r += coef * f;
                    }
                }
            }
            sys.reduce(
                &self.rhs,
                &mut self.y[..nl],
                &mut self.rn[..nn],
                &mut self.work[..nl],
            );
            let xn = &mut self.xn[..nn];
            match c_last {
                Some(cm) if self.opts.predictor == 2 && slope > 0.0 => {
                    // Quadratic through x_prev (at -1/slope), x (at 0) and
                    // the latest stage (at cm), evaluated at ci.
                    let tp = -1.0 / slope;
                    let lp = ci * (ci - cm) / (tp * (tp - cm));
                    let l0 = (ci - tp) * (ci - cm) / (tp * cm);
                    let lm = (ci - tp) * ci / ((cm - tp) * cm);
                    for (v, &k) in xn.iter_mut().zip(&sys.n_idx) {
                        *v = lp * self.x_prev[k] + l0 * self.x[k] + lm * *v;
                    }
                }
                Some(cm) if self.opts.predictor == 2 => {
                    for (v, &k) in xn.iter_mut().zip(&sys.n_idx) {
                        *v = self.x[k] + ci / cm * (*v - self.x[k]);
                    }
                }
                _ => {
                    for (v, &k) in xn.iter_mut().zip(&sys.n_idx) {
                        *v = self.x[k] + ci * slope * (self.x[k] - self.x_prev[k]);
                    }
                }
            }
            let it = self
                .newton
                .solve(sys, &self.mna.devices, &self.rn[..nn], xn, &opts)?;
            iterations[solves] = it;
            solves += 1;
            c_last = Some(ci);
            sys.expand(&self.y[..nl], xn, &mut self.x_new);
            self.mna.c_sparse.mul_vec(&self.x_new, &mut self.cx_new);
            // F_i = (C Y_i - C x[n]) / (g h) - (1/g) sum_j a_ij F_j.
            let (done, rest) = self.stage_f.split_at_mut(fi);
            let f_i = &mut rest[..n];
            for ((f, new), old) in f_i.iter_mut().zip(&self.cx_new).zip(&self.cx) {
                *f = inv * (new - old);
            }
            for j in 0..i {
                let coef = self.tab.a[i * s + j] / g;
                if coef != 0.0 {
                    for (f, fj) in f_i.iter_mut().zip(&done[j * n..(j + 1) * n]) {
                        *f -= coef * fj;
                    }
                }
            }
        }

        if self.opts.error_abstol > 0.0
            && (level as u32) < self.opts.max_error_halvings.min(self.opts.max_halvings)
            && let Some(d) = &self.tab.d
        {
            // Hairer & Wanner's filtered estimate for stiff problems:
            // err = (G + G_dev + C/(g h))^-1 (1/g) sum_i d_i F_i, with the
            // last stage's Newton Jacobian.
            self.rhs.fill(0.0);
            for (i, &di) in d.iter().enumerate() {
                if di != 0.0 {
                    let fi = &self.stage_f[i * n..(i + 1) * n];
                    for (r, f) in self.rhs.iter_mut().zip(fi) {
                        *r += di / g * f;
                    }
                }
            }
            sys.reduce(
                &self.rhs,
                &mut self.y[..nl],
                &mut self.rn[..nn],
                &mut self.work[..nl],
            );
            self.newton
                .solve_jacobian(&mut self.rn[..nn], &mut self.work[..nn]);
            sys.expand(&self.y[..nl], &self.rn[..nn], &mut self.err);
            let ratio = match self.opts.error_norm {
                ErrorNorm::Nodes => error_ratio(&self.err, &self.x_new, &self.is_node, &self.opts),
                ErrorNorm::PortsStates => {
                    let ps = &mut self.norm_ps;
                    let m = ps.ports.len();
                    ps.ports.voltages(&self.err, &mut ps.e[..m]);
                    ps.ports.voltages(&self.x_new, &mut ps.v[..m]);
                    for (j, &k) in ps.states.iter().enumerate() {
                        ps.e[m + j] = self.err[k];
                        ps.v[m + j] = self.x_new[k];
                    }
                    error_ratio(&ps.e, &ps.v, &ps.keep, &self.opts)
                }
            };
            if ratio > 1.0 {
                return Err(StepFail::Inaccurate(ratio));
            }
            self.err_ratio = ratio;
        } else {
            self.err_ratio = f64::NAN;
        }

        // Stiffly accurate: the last stage is the end point.
        self.f.copy_from_slice(&self.stage_f[(s - 1) * n..s * n]);
        self.newton
            .ports(&self.mna.devices, &self.xn[..nn], &mut self.ports);
        self.accept(level, hk, inp.at(th1));
        for &it in &iterations[..solves] {
            self.count(it);
        }
        Ok(())
    }

    /// A diagonally implicit step with the DK solver: the same stages as
    /// [`Transient::try_step_dirk`], on the state rows and device ports.
    fn try_step_dk(
        &mut self,
        level: usize,
        th0: f64,
        th1: f64,
        inp: &StepInput,
    ) -> Result<(), StepFail> {
        let hk = self.step_len(level, th0, th1);
        let rest = self.rest_slot();
        let s = self.tab.s;
        let g = self.tab.gamma;
        let inv = 1.0 / (g * hk);
        let slope = self.extrapolation(hk);
        let opts = self.newton_options();
        let dk = self.dk.as_mut().expect("DK solver");
        if dk.levels[level].is_none() {
            let sys = DkSystem::new(
                &self.mna.g,
                &self.mna.c,
                inv,
                &self.mna.b,
                self.mna.input_row,
                &self.mna.source_rows(),
                self.mna.noise.as_ref().map_or(&[], |n| &n.columns),
                &dk.ports,
                &dk.support,
                &dk.probes,
            )
            .map_err(|Singular { column }| StepFail::Matrix(column))?;
            dk.levels[level] = Some(sys);
        }
        let sys = dk.levels[level].as_ref().expect("just built");
        // A restart's remainder counts as a full step (error control, stats).
        let level = if level == rest { 0 } else { level };
        let (m, r) = (sys.m, sys.r);
        // Every unknown, or (enough for the outputs and this error norm) the probes'.
        let all = self.opts.all_unknowns || self.opts.error_norm == ErrorNorm::Nodes;
        self.x_full = all;
        let rows = sys.rows_for(all);
        dk.newton.v_lin.copy_from_slice(&self.ports);
        let t0 = timing::now();
        dk.base.resize(rows, 0.0);
        sys.step_base(&dk.xs, &mut dk.base);
        timing::add(Part::Step, t0);

        let mut iterations = [0usize; 8];
        let mut solves = 0;
        let mut c_last: Option<f64> = None;
        let mut u = inp.at(th0);
        for i in 0..s {
            if i == 0 && self.tab.explicit_first() {
                dk.stage_f[..r].copy_from_slice(&dk.f);
                continue;
            }
            let ci = self.tab.c[i];
            let t0 = timing::now();
            // w = (1/g) sum_j a_ij F_j.
            dk.w.fill(0.0);
            for j in 0..i {
                let coef = self.tab.a[i * s + j] / g;
                if coef != 0.0 {
                    for (w, f) in dk.w.iter_mut().zip(&dk.stage_f[j * r..(j + 1) * r]) {
                        *w += coef * f;
                    }
                }
            }
            let th = th0 + ci * (th1 - th0);
            u = inp.at(th);
            let t = (self.n as f64 + th) * self.h;
            let nw = self.mna.waves.len();
            for (v, wave) in dk.wv.iter_mut().zip(&self.mna.waves) {
                *v = wave.at(t);
            }
            if let Some(noise) = &self.mna.noise {
                noise.modulate_waves(th, &mut dk.wv[..nw]);
            }
            for ((v, &e0), &e1) in dk.wv[nw..].iter_mut().zip(&self.ext0).zip(&self.ext1) {
                *v = e0 + th * (e1 - e0);
            }
            if let Some(noise) = &self.mna.noise {
                noise.fill(th, &mut dk.wv[nw + self.ext0.len()..]);
            }
            sys.stage(&dk.base, u, &dk.wv, &dk.w, &mut dk.out);
            // The initial guess, as try_step_dirk's on the device nodes (the
            // ports are linear in them, so the guesses correspond).
            let v = &mut dk.v;
            match c_last {
                Some(cm) if self.opts.predictor == 2 && slope > 0.0 => {
                    let tp = -1.0 / slope;
                    let lp = ci * (ci - cm) / (tp * (tp - cm));
                    let l0 = (ci - tp) * (ci - cm) / (tp * cm);
                    let lm = (ci - tp) * ci / ((cm - tp) * cm);
                    for ((v, &p), &x) in v.iter_mut().zip(&dk.v_prev).zip(&self.ports) {
                        *v = lp * p + l0 * x + lm * *v;
                    }
                }
                Some(cm) if self.opts.predictor == 2 => {
                    for (v, &x) in v.iter_mut().zip(&self.ports) {
                        *v = x + ci / cm * (*v - x);
                    }
                }
                _ => {
                    for ((v, &p), &x) in v.iter_mut().zip(&dk.v_prev).zip(&self.ports) {
                        *v = x + ci * slope * (x - p);
                    }
                }
            }
            timing::add(Part::Stage, t0);
            dk.v_guess.copy_from_slice(&dk.v);
            dk.v_lin_guess.copy_from_slice(&dk.newton.v_lin);
            let mut res = dk.newton.solve(
                sys,
                &self.mna.devices,
                &dk.ports,
                &dk.out[..m],
                &mut dk.v,
                &opts,
            );
            if res.is_err() && dk.newton.reuse {
                // A lagged Jacobian can stall where Newton converges (a sharp
                // knee: grid conduction, a diode turning on). Redo the stage
                // with exact Newton from the same guess before halving.
                self.stats.exact_retries += 1;
                dk.v.copy_from_slice(&dk.v_guess);
                dk.newton.v_lin.copy_from_slice(&dk.v_lin_guess);
                dk.newton.reuse = false;
                res = dk.newton.solve(
                    sys,
                    &self.mna.devices,
                    &dk.ports,
                    &dk.out[..m],
                    &mut dk.v,
                    &opts,
                );
                dk.newton.reuse = true;
            }
            let it = res?;
            let t0 = timing::now();
            iterations[solves] = it;
            solves += 1;
            c_last = Some(ci);
            let ys = &mut dk.out[m..m + r];
            sys.states(ys, &dk.newton.i, &mut dk.neg);
            // F_i = C (Y_i - x[n]) / (g h) - w.
            for ((d, y), x) in dk.d.iter_mut().zip(&*ys).zip(&dk.xs) {
                *d = y - x;
            }
            let f_i = &mut dk.stage_f[i * r..(i + 1) * r];
            dk.css.mul_vec(&dk.d, f_i);
            for (f, w) in f_i.iter_mut().zip(&dk.w) {
                *f = inv * *f - w;
            }
            timing::add(Part::Stage, t0);
        }
        let t0 = timing::now();
        // Stiffly accurate: the last stage is the end point.
        let xu = &mut dk.xu[..rows - m - r];
        sys.unknowns(&dk.base, u, &dk.wv, &dk.w, &dk.newton.i, xu, &mut dk.neg);
        for (&v, &k) in xu.iter().zip(sys.order()) {
            self.x_new[k] = v;
        }

        if self.opts.error_abstol > 0.0
            && (level as u32) < self.opts.max_error_halvings.min(self.opts.max_halvings)
            && let Some(d) = &self.tab.d
        {
            // As try_step_dirk: (G + G_dev + C/(g h))^-1 (1/g) sum_i d_i F_i.
            dk.w.fill(0.0);
            for (i, &di) in d.iter().enumerate() {
                if di != 0.0 {
                    let fi = &dk.stage_f[i * r..(i + 1) * r];
                    for (e, f) in dk.w.iter_mut().zip(fi) {
                        *e += di / g * f;
                    }
                }
            }
            let ratio = match self.opts.error_norm {
                ErrorNorm::Nodes => {
                    sys.solve_linearized(
                        &dk.newton,
                        &dk.ports,
                        &dk.w,
                        &mut dk.xu,
                        &mut dk.wm,
                        &mut dk.neg,
                    );
                    for (&e, &k) in dk.xu.iter().zip(sys.order()) {
                        self.err[k] = e;
                    }
                    error_ratio(&self.err, &self.x_new, &self.is_node, &self.opts)
                }
                ErrorNorm::PortsStates => {
                    sys.solve_linearized_ports_states(
                        &dk.newton,
                        &dk.ports,
                        &dk.w,
                        &mut dk.e_ps,
                        &mut dk.wm,
                        &mut dk.neg,
                    );
                    dk.v_ps[..m].copy_from_slice(&dk.v);
                    dk.v_ps[m..].copy_from_slice(&dk.out[m..m + r]);
                    error_ratio(&dk.e_ps, &dk.v_ps, &dk.keep_ps, &self.opts)
                }
            };
            if ratio > 1.0 {
                timing::add(Part::Step, t0);
                return Err(StepFail::Inaccurate(ratio));
            }
            self.err_ratio = ratio;
        } else {
            self.err_ratio = f64::NAN;
        }
        timing::add(Part::Step, t0);

        dk.xs.copy_from_slice(&dk.out[m..m + r]);
        dk.f.copy_from_slice(&dk.stage_f[(s - 1) * r..s * r]);
        dk.v_prev.copy_from_slice(&self.ports);
        self.ports.copy_from_slice(&dk.v);
        self.accept(level, hk, inp.at(th1));
        for &it in &iterations[..solves] {
            self.count(it);
        }
        Ok(())
    }

    fn try_step_coupled(
        &mut self,
        level: usize,
        th0: f64,
        th1: f64,
        inp: &StepInput,
    ) -> Result<(), StepFail> {
        let hk = self.h / (1u64 << level) as f64;
        let n = self.x.len();
        let s = self.tab.s;
        let cp = self.coupled.as_mut().expect("fully implicit method");
        if self.levels[level].is_none() {
            // I (x) G + W/h (x) C.
            let mut a = Matrix::zeros(s * n);
            for bi in 0..s {
                for bj in 0..s {
                    let wij = cp.w[bi * s + bj] / hk;
                    for r in 0..n {
                        for c in 0..n {
                            let mut v = wij * self.mna.c.get(r, c);
                            if bi == bj {
                                v += self.mna.g.get(r, c);
                            }
                            if v != 0.0 {
                                a.set(bi * n + r, bj * n + c, v);
                            }
                        }
                    }
                }
            }
            self.levels[level] = Some(Reduced::new(&a, &cp.nodes));
        }
        let sys = self.levels[level].as_ref().expect("just built");
        let (nn, nl) = (sys.n_len(), sys.l_len());
        for i in 0..s {
            let ws = cp.w_sum[i] / hk;
            let rhs = &mut cp.rhs[i * n..(i + 1) * n];
            for ((r, b), cx) in rhs.iter_mut().zip(&self.mna.b).zip(&self.cx) {
                *r = b + ws * cx;
            }
            let th = th0 + self.tab.c[i] * (th1 - th0);
            rhs[self.mna.input_row] += inp.at(th);
            self.mna.add_waves((self.n as f64 + th) * self.h, rhs);
        }
        let mut work = vec![0.0; nl];
        let mut rn = vec![0.0; nn];
        sys.reduce(&cp.rhs, &mut cp.y[..nl], &mut rn, &mut work);
        let slope = if self.opts.extrapolate && self.h_prev > 0.0 {
            hk / self.h_prev
        } else {
            0.0
        };
        let mut xn = vec![0.0; nn];
        for (v, &k) in xn.iter_mut().zip(&sys.n_idx) {
            let (stage, j) = (k / n, k % n);
            *v = self.x[j] + self.tab.c[stage] * slope * (self.x[j] - self.x_prev[j]);
        }
        let np = self.ports.len();
        for c in 0..s {
            cp.newton.v_lin[c * np..(c + 1) * np].copy_from_slice(&self.ports);
        }
        let opts = NewtonOptions {
            reltol: self.opts.reltol,
            vntol: self.opts.vntol,
            max_iter: self.opts.max_iter,
            gshunt: 0.0,
        };
        let it = cp
            .newton
            .solve(sys, &self.mna.devices, &rn, &mut xn, &opts)?;
        sys.expand(&cp.y[..nl], &xn, &mut cp.x);
        self.x_new.copy_from_slice(&cp.x[(s - 1) * n..]);
        cp.newton
            .copy_ports(&self.mna.devices, &xn, s - 1, &mut self.ports);
        self.mna.c_sparse.mul_vec(&self.x_new, &mut self.cx_new);
        self.accept(level, hk, inp.at(th1));
        self.count(it);
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
        // Fully implicit methods solve s copies; name the circuit unknown.
        let full = sys.n_idx[position] % self.mna.len();
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

    /// Change component values mid-run (a pot, a switch, a refitted model):
    /// `ir` must be the same circuit apart from values, with the same
    /// unknowns (nodes, sources, inductors) and the same devices on the same
    /// pins. Elements may appear or disappear between existing nodes (a
    /// switched capacitor).
    ///
    /// The state (every node voltage and inductor current) carries over, and
    /// the integration restarts from it at first order: the next sample starts
    /// with a short backward-Euler step ([`Transient::restart_sample`]), which
    /// settles what the change made fast as a real switch does (charges held),
    /// and doesn't extrapolate across the change. (The derivative `C x'` from the
    /// new circuit at the current point, `b + u - G x - d(x)` on the rows of `C`,
    /// is still set, but no step reads it before the restart replaces it.) The step matrices are rebuilt on
    /// first use, one per step size (for the 670: ~1 ms each; see
    /// `tests/update.rs`). Devices with memory start over from their model.
    ///
    /// The externals ([`Mna::externals`], [`Mna::outputs`]) stay on the same rows,
    /// at their values at the current point.
    pub fn update(&mut self, ir: &CircuitIr) -> Result<(), Error> {
        if !self.x_full {
            return Err(Error::new(
                "update: needs every unknown at the current point, and the last step kept \
                 only the probes (Transient::set_all_unknowns for one step first)",
            ));
        }
        let mut mna = Mna::from_ir(ir, self.opts.gmin)?;
        if self.opts.tube_tables {
            mna.tabulate_tubes();
        }
        // The same unknowns, possibly in another order (MNA numbers nodes by first
        // appearance: a tapped pot's wiper crossing its tap rewires its segments
        // among the same nodes): old index -> new index.
        let changed = || {
            Error::new(
                "update: the circuit's nodes, sources or inductors changed (only values may)",
            )
        };
        if mna.unknowns.len() != self.mna.unknowns.len() {
            return Err(changed());
        }
        let perm: Vec<usize> = if mna.unknowns == self.mna.unknowns {
            (0..mna.unknowns.len()).collect()
        } else {
            let index: std::collections::HashMap<String, usize> = mna
                .unknowns
                .iter()
                .enumerate()
                .map(|(i, u)| (u.describe(), i))
                .collect();
            let perm: Option<Vec<usize>> = self
                .mna
                .unknowns
                .iter()
                .map(|u| index.get(&u.describe()).copied())
                .collect();
            let perm = perm.ok_or_else(changed)?;
            if self.coupled.is_some() {
                return Err(Error::new(
                    "update: the circuit's unknowns moved, which needs a diagonally implicit method",
                ));
            }
            perm
        };
        let moved = perm.iter().enumerate().any(|(i, &j)| i != j);
        mna.externals = self.mna.externals.iter().map(|&r| perm[r]).collect();
        mna.outputs = self.mna.outputs.iter().map(|&r| perm[r]).collect();
        let same_devices = mna.devices.len() == self.mna.devices.len()
            && mna.devices.iter().zip(&self.mna.devices).all(|(a, b)| {
                a.name == b.name
                    && a.pin_names == b.pin_names
                    && a.pins.len() == b.pins.len()
                    && a.pins
                        .iter()
                        .zip(&b.pins)
                        .all(|(&pa, &pb)| pa == pb.map(|i| perm[i]))
            });
        if !same_devices {
            return Err(Error::new(
                "update: the circuit's devices or their connections changed (only values may)",
            ));
        }
        // Devices with memory (cores) keep it: the new instances start where the
        // old ones were, whatever values changed.
        let mut mna = mna;
        for (new, old) in mna.devices.iter_mut().zip(&self.mna.devices) {
            new.device.set_state(&old.device.state());
        }
        // The cathodes' temperature carries on (the new devices get it below).
        if let (Some(new), Some(old)) = (&mut mna.heat, &self.mna.heat) {
            new.t_k = old.t_k;
        }
        // Noise streams carry on where they were (by source name).
        if let Some(new) = &mut mna.noise {
            new.set_step(self.h).map_err(Error::new)?;
            if let Some(old) = &self.mna.noise {
                new.carry(old);
            }
        }
        self.mna = mna;
        // The new devices start at T0: give them the carried temperature.
        self.apply_heat();
        self.levels.iter_mut().for_each(|l| *l = None);
        self.levels_be.iter_mut().for_each(|l| *l = None);
        let n = self.x.len();
        if moved {
            // The state follows its unknowns; what is indexed by them is rebuilt.
            for v in [&mut self.x, &mut self.x_prev] {
                let old = v.clone();
                for (i, &j) in perm.iter().enumerate() {
                    v[j] = old[i];
                }
            }
            let mut device_nodes = Vec::new();
            for d in &self.mna.devices {
                for &p in d.pins.iter().flatten() {
                    if !device_nodes.contains(&p) {
                        device_nodes.push(p);
                    }
                }
            }
            self.newton = Newton::new(&self.mna.devices, &device_nodes);
            self.device_nodes = device_nodes;
            self.is_node = self
                .mna
                .unknowns
                .iter()
                .map(|u| matches!(u, crate::mna::Unknown::Node(_)))
                .collect();
            self.norm_ps = NormPs::new(&self.mna);
        }

        // F = C x' from the new circuit at x: b + u e_in - G x - d(x) on the
        // rows of C, with d the device currents at the current ports.
        let mut f = self.mna.b.clone();
        f[self.mna.input_row] += self.u;
        for (&row, &e) in self.mna.externals.iter().zip(&self.ext1) {
            f[row] += e;
        }
        let t0 = self.time(0.0);
        let mut waves: Vec<f64> = self.mna.waves.iter().map(|w| w.at(t0)).collect();
        if let Some(noise) = &mut self.mna.noise {
            // At the current point: the next sample's start.
            noise.begin_sample(self.n);
            noise.modulate_waves(0.0, &mut waves);
            let mut vals = vec![0.0; noise.columns.len()];
            noise.fill(0.0, &mut vals);
            noise.add_to(&vals, &mut f);
        }
        for (w, v) in self.mna.waves.iter().zip(&waves) {
            f[w.row] += v;
        }
        let mut gx = vec![0.0; n];
        self.mna.g.mul_vec(&self.x, &mut gx);
        for (f, g) in f.iter_mut().zip(&gx) {
            *f -= g;
        }
        let mut off = 0;
        for inst in &self.mna.devices {
            let np = inst.device.ports();
            let mut i = vec![0.0; np];
            let mut g = vec![0.0; np * np];
            inst.device.eval(&self.ports[off..off + np], &mut i, &mut g);
            let reference = *inst.pins.last().expect("devices have pins");
            for (&pin, &ij) in inst.pins[..np].iter().zip(&i) {
                if let Some(p) = pin {
                    f[p] -= ij;
                }
                if let Some(r) = reference {
                    f[r] += ij;
                }
            }
            off += np;
        }
        let support = dk::support(&self.mna.c);
        let mut on_c = vec![false; n];
        for &k in &support {
            on_c[k] = true;
        }
        for (f, &c) in f.iter_mut().zip(&on_c) {
            if !c {
                *f = 0.0;
            }
        }
        self.f.copy_from_slice(&f);
        self.mna.c_sparse.mul_vec(&self.x, &mut self.cx);
        if let Some(dk) = &mut self.dk {
            *dk = Dk::new(&self.mna, &self.opts, self.tab.s);
            for ((xs, fs), &k) in dk.xs.iter_mut().zip(dk.f.iter_mut()).zip(&dk.support) {
                *xs = self.x[k];
                *fs = f[k];
            }
            dk.v_prev.copy_from_slice(&self.ports);
        }
        // No extrapolation across the change.
        self.x_prev.copy_from_slice(&self.x);
        self.h_prev = 0.0;
        // Methods that carry the derivative in restart at first order (the
        // fully implicit ones take none).
        self.restart = self.tab.explicit_first() && self.coupled.is_none();
        Ok(())
    }

    /// An error naming the device port the DK Newton failed on, and its nodes.
    fn port_failure_error(&self, ports: &Ports, f: Failure, what: &str) -> Error {
        let (position, detail) = match f {
            Failure::Singular { position } => (
                position,
                "Newton matrix singular (a device port with no path through the circuit?)"
                    .to_string(),
            ),
            Failure::NoConvergence { position, update } => (
                position,
                format!("Newton did not converge (last update {update:.3e})"),
            ),
        };
        let (d, k) = ports.device_of(position);
        let dev = &self.mna.devices[d];
        let node =
            |p: Option<usize>| p.map_or("ground".to_string(), |i| self.mna.unknowns[i].describe());
        let (pin, reference) = ports.nodes[position];
        let names = dev.pin_names;
        Error::new(format!(
            "{what}: {detail} at {0}.{1} ({2}) relative to {0}.{3} ({4})",
            dev.name,
            names[k],
            node(pin),
            names[names.len() - 1],
            node(reference),
        ))
    }

    /// The current solution (node voltages, then branch currents; see `Mna`).
    /// Compute every unknown at each step from now on (`Options::all_unknowns`),
    /// or only the probes' and outputs'. [`Transient::update`] needs a step with
    /// every unknown first.
    pub fn set_all_unknowns(&mut self, on: bool) {
        self.opts.all_unknowns = on;
    }

    /// The externals' values ([`Mna::externals`]) over the next sample: `start`
    /// at its start, `end` at its end, linear in between (stage times).
    /// (The externals past the control inputs: a partition's couplings.)
    pub fn set_externals(&mut self, start: &[f64], end: &[f64]) {
        let k = self.mna.n_controls;
        self.ext0[k..].copy_from_slice(start);
        self.ext1[k..].copy_from_slice(end);
    }

    /// The control inputs' values over the next sample ([`Mna::n_controls`],
    /// IR order): `start` at its start, `end` at its end, linear in between.
    pub fn set_controls(&mut self, start: &[f64], end: &[f64]) {
        let k = self.mna.n_controls;
        self.ext0[..k].copy_from_slice(start);
        self.ext1[..k].copy_from_slice(end);
    }

    pub fn x(&self) -> &[f64] {
        &self.x
    }

    /// DK only: evaluations of each device so far (`Mna::devices` order).
    pub fn device_evaluations(&self) -> Option<&[u64]> {
        self.dk
            .as_ref()
            .map(|dk| dk.newton.device_evaluations.as_slice())
    }

    /// DK only: iterations with junction limiting per device, and
    /// factorizations by what asked for them (`dk::Refactor`'s order).
    pub fn newton_counts(&self) -> Option<(&[u64], &[u64])> {
        self.dk
            .as_ref()
            .map(|dk| (dk.newton.device_limits.as_slice(), &dk.newton.refactors[..]))
    }

    /// Port voltages of every device at the current solution (device by
    /// device, as `dk::Ports` lays them out).
    pub fn port_voltages(&self) -> &[f64] {
        &self.ports
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
    simulate_with_progress(ir, input, h, opts, usize::MAX, |_| Ok(()))
}

/// The control inputs' samples at `n` (IR order).
fn controls_at(controls: &[&[f64]], n: usize) -> Vec<f64> {
    controls.iter().map(|c| c[n]).collect()
}

/// Check `controls` against `ir`'s control inputs: one sample stream each, as
/// long as the input, finite.
pub(crate) fn check_controls(ir: &CircuitIr, controls: &[&[f64]], len: usize) -> Result<(), Error> {
    if controls.len() != ir.controls.len() {
        return Err(Error::new(format!(
            "{} control streams for {} control inputs",
            controls.len(),
            ir.controls.len()
        )));
    }
    for (c, x) in ir.controls.iter().zip(controls) {
        if x.len() != len {
            return Err(Error::new(format!(
                "control {}: {} samples for {len} of input",
                c.name,
                x.len()
            )));
        }
        if let Some(i) = x.iter().position(|v| !v.is_finite()) {
            return Err(Error::new(format!(
                "control {} sample {i} is not finite",
                c.name
            )));
        }
    }
    Ok(())
}

/// [`simulate`], calling `progress(samples done)` every `every` samples. An
/// error from `progress` stops the run and is returned (e.g. an interrupt).
pub fn simulate_with_progress(
    ir: &CircuitIr,
    input: &[f64],
    h: f64,
    opts: &Options,
    every: usize,
    progress: impl FnMut(usize) -> Result<(), Error>,
) -> Result<Output, Error> {
    simulate_controls(ir, input, &[], h, opts, every, progress)
}

/// [`simulate_with_progress`] with the control inputs' samples (`controls`, IR
/// order, each as long as `input`; linear between samples).
pub fn simulate_controls(
    ir: &CircuitIr,
    input: &[f64],
    controls: &[&[f64]],
    h: f64,
    opts: &Options,
    every: usize,
    mut progress: impl FnMut(usize) -> Result<(), Error>,
) -> Result<Output, Error> {
    let every = every.max(1);
    check_controls(ir, controls, input.len())?;
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
    let mut tr = if controls.is_empty() {
        Transient::new(mna, h, *opts, u0)?
    } else {
        Transient::with_externals(mna, h, *opts, u0, &controls_at(controls, 0))?
    };
    let mut record = |tr: &Transient| {
        for (v, y) in values.iter_mut().zip(tr.mna().probe_values(tr.x())) {
            v.push(y);
        }
    };
    record(&tr);
    // Step n -> n + 1 interpolates through the `order + 1` samples centred
    // on it (fewer at the ends of the input).
    let order = opts.input_order as i64;
    let len = input.len() as i64;
    for (i, &u) in rest.iter().enumerate() {
        if !controls.is_empty() {
            tr.set_controls(&controls_at(controls, i), &controls_at(controls, i + 1));
        }
        if order == 1 {
            tr.step(u)?;
        } else {
            let n = i as i64; // the step's start sample
            let lo = (n - (order - 1) / 2).max(0);
            let hi = (n + 1 + (order - 1) / 2).min(len - 1);
            let w = &input[lo as usize..=hi as usize];
            tr.step_input(&StepInput::lagrange(w, (lo - n) as i32))?;
        }
        record(&tr);
        if (i + 2) % every == 0 {
            progress(i + 2)?;
        }
    }
    Ok(Output {
        names,
        values,
        stats: tr.stats().clone(),
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    /// Row sums are c, b (the last row) sums to 1, and b . c = 1/2: every
    /// method is at least second-order consistent (except Euler).
    #[test]
    fn tableaus_are_consistent() {
        for name in Method::NAMES {
            let t = Method::parse(name).unwrap().tableau();
            let s = t.s;
            let b = &t.a[(s - 1) * s..];
            assert!((b.iter().sum::<f64>() - 1.0).abs() < 1e-14, "{name}");
            assert!(
                (t.c[s - 1] - 1.0).abs() < 1e-14,
                "{name} is stiffly accurate"
            );
            let bc: f64 = b.iter().zip(&t.c).map(|(p, q)| p * q).sum();
            if name != "euler" {
                assert!((bc - 0.5).abs() < 1e-14, "{name}: b.c = {bc}");
            }
            if t.diagonal {
                for i in 0..s {
                    let d = t.a[i * s + i];
                    assert!(d == t.gamma || (i == 0 && d == 0.0), "{name}");
                }
            }
        }
    }
}
