//! Heated cathodes (device builder B6, the heater): a compiled port of
//! `varimu/devices/cathode.py` (its docstring has the physics; `tests/cathode.rs` checks
//! this port against fixtures exported from it).
//!
//! A [`Heated`] device wraps a tube model: its control port (a triode's grid, a pentode's
//! control grid, a diode's anode) moved by the space-charge shift for the cathode's
//! temperature and a reference current (the tube's own at its last accepted step), every
//! current then scaled by the emission ceiling relative to its value at the rated
//! temperature. [`HeatRun`] carries the circuit's one cathode temperature through a run.

use crate::devices::Device;
use crate::ir::HeaterSpec;

/// Boltzmann's constant in eV/K (CODATA 2018).
pub const K_EV: f64 = 8.617333262e-5;
/// The shift's current floor (Python's `I_MIN_A`).
pub const I_MIN_A: f64 = 1e-9;

/// One tube's emission constants.
#[derive(Debug, Clone, Copy)]
pub struct Emission {
    pub is0_a: f64,
    pub phi_ev: f64,
    pub n: f64,
    pub t0_k: f64,
}

impl Emission {
    /// Emission capacity at `t_k` (Richardson-Dushman, normalized at T0).
    pub fn is_a(&self, t_k: f64) -> f64 {
        self.is0_a
            * (t_k / self.t0_k).powi(2)
            * (-(self.phi_ev / K_EV) * (1.0 / t_k - 1.0 / self.t0_k)).exp()
    }

    /// The space-charge shift (V) at `t_k` for a tube current `i_a`: zero at T0.
    pub fn shift_v(&self, t_k: f64, i_a: f64) -> f64 {
        let i = i_a.max(I_MIN_A);
        let (vt0, vt) = (K_EV * self.t0_k, K_EV * t_k);
        let r0 = (i / self.is0_a).min(1.0);
        let r = (i / self.is_a(t_k)).min(1.0);
        vt0 * r0.ln() - vt * r.ln()
    }
}

/// `(1 + x^n)^(-1/n)` and its derivative in x.
fn ceil(x: f64, n: f64) -> (f64, f64) {
    let xn = x.powf(n);
    let c = (1.0 + xn).powf(-1.0 / n);
    // d/dx = -c x^(n-1) / (1 + x^n)
    let d = if x > 0.0 {
        -c * xn / x / (1.0 + xn)
    } else {
        0.0
    };
    (c, d)
}

/// A tube model under its cathode's temperature (see the module docs).
#[derive(Debug)]
pub struct Heated {
    inner: Box<dyn Device>,
    port: usize,
    em: Emission,
    t_k: f64,
    shift: f64,
    is_t: f64,
}

impl Heated {
    /// `inner` with its control on `port`, at the rated temperature.
    pub fn new(inner: Box<dyn Device>, port: usize, em: Emission) -> Heated {
        Heated {
            inner,
            port,
            em,
            t_k: em.t0_k,
            shift: 0.0,
            is_t: em.is0_a,
        }
    }
}

const MAX_PORTS: usize = 4;

impl Device for Heated {
    fn ports(&self) -> usize {
        self.inner.ports()
    }

    fn eval(&self, v: &[f64], i: &mut [f64], g: &mut [f64]) {
        let np = self.ports();
        let mut vs = [0.0; MAX_PORTS];
        vs[..np].copy_from_slice(v);
        vs[self.port] += self.shift;
        self.inner.eval(&vs[..np], i, g);
        let ik = i.iter().sum::<f64>().max(0.0);
        let (ct, dct) = ceil(ik / self.is_t, self.em.n);
        let (c0, dc0) = ceil(ik / self.em.is0_a, self.em.n);
        let f = ct / c0;
        // df / dik
        let df = if ik > 0.0 {
            f * (dct / self.is_t / ct - dc0 / self.em.is0_a / c0)
        } else {
            0.0
        };
        let mut col = [0.0; MAX_PORTS]; // d ik / dv_k
        if ik > 0.0 {
            for j in 0..np {
                for (k, c) in col.iter_mut().enumerate().take(np) {
                    *c += g[j * np + k];
                }
            }
        }
        for j in 0..np {
            for k in 0..np {
                g[j * np + k] = f * g[j * np + k] + i[j] * df * col[k];
            }
        }
        for x in i.iter_mut() {
            *x *= f;
        }
    }

    fn limit(&self, v: &mut [f64], v_old: &[f64]) -> bool {
        let np = self.ports();
        let mut old = [0.0; MAX_PORTS];
        old[..np].copy_from_slice(v_old);
        old[self.port] += self.shift;
        v[self.port] += self.shift;
        let limited = self.inner.limit(v, &old[..np]);
        v[self.port] -= self.shift;
        limited
    }

    fn shunt(&self, port: usize) -> f64 {
        self.inner.shunt(port)
    }

    fn tabulate(&self) -> Option<Box<dyn Device>> {
        self.inner.tabulate().map(|t| {
            let mut h = Heated::new(t, self.port, self.em);
            h.set_cathode(self.t_k, f64::NAN);
            h.shift = self.shift;
            Box::new(h) as Box<dyn Device>
        })
    }

    fn set_cathode(&mut self, t_k: f64, i_ref: f64) {
        self.t_k = t_k;
        self.is_t = self.em.is_a(t_k);
        if i_ref.is_finite() {
            self.shift = self.em.shift_v(t_k, i_ref);
        }
    }
}

/// The circuit's cathode temperature through a run, and the tubes it heats.
#[derive(Debug, Clone)]
pub struct HeatRun {
    pub spec: HeaterSpec,
    pub t_k: f64,
    /// The device instances it heats (a bank merged into one: once; it shares its current
    /// among its tubes, [`Device::set_cathode`]).
    pub tubes: Vec<usize>,
    /// The temperature and reference currents last given to the devices.
    pub set_t: f64,
    pub set_i: Vec<f64>,
}

impl HeatRun {
    /// At the start: warm (the ratio's steady temperature) or cold (ambient).
    pub fn new(spec: HeaterSpec, tubes: Vec<usize>) -> HeatRun {
        let t_k = if spec.start == "cold" {
            spec.t_amb_k
        } else {
            steady_k(&spec, spec.heater_ratio)
        };
        let n = tubes.len();
        HeatRun {
            spec,
            t_k,
            tubes,
            set_t: f64::NAN,
            set_i: vec![1e-3; n],
        }
    }

    /// dT/dt at `t_k` with the heater at `ratio` of its rating (Python's `Cathode.dt_dt`
    /// for a heater of 1 V, 1 A: the rating cancels).
    pub fn dt_dt(&self, t_k: f64, ratio: f64) -> f64 {
        dt_dt(&self.spec, t_k, ratio)
    }

    /// One explicit Euler step of `h` seconds with the heater at `ratio`.
    pub fn step(&mut self, h: f64, ratio: f64) {
        self.t_k += h * self.dt_dt(self.t_k, ratio);
    }

    /// Whether the devices need new values: the temperature moved by more than 1e-4 K or a
    /// reference current by more than 1% since they were last given.
    pub fn stale(&self, i_ref: &[f64]) -> bool {
        !((self.t_k - self.set_t).abs() <= 1e-4
            && i_ref
                .iter()
                .zip(&self.set_i)
                .all(|(a, b)| (a.max(I_MIN_A) / b.max(I_MIN_A)).ln().abs() <= 0.01))
    }
}

fn dt_dt(s: &HeaterSpec, t_k: f64, ratio: f64) -> f64 {
    let s4 = s.t0_k.powi(4) - s.t_amb_k.powi(4);
    let radiation = 1.0 / s4; // W/K^4 for a 1 V, 1 A heater
    let capacity = s.tau_s * 4.0 * radiation * s.t0_k.powi(3);
    let r = (t_k / s.t0_k).powf(s.alpha);
    let p = ratio * ratio / r;
    (p - radiation * (t_k.powi(4) - s.t_amb_k.powi(4))) / capacity
}

/// The temperature a heater ratio holds (bisection, Python's `steady_k`).
pub fn steady_k(s: &HeaterSpec, ratio: f64) -> f64 {
    let (mut lo, mut hi) = (s.t_amb_k, 4.0 * s.t0_k);
    let s4 = s.t0_k.powi(4) - s.t_amb_k.powi(4);
    for _ in 0..200 {
        let mid = 0.5 * (lo + hi);
        let gain = ratio * ratio / (mid / s.t0_k).powf(s.alpha);
        let loss = (mid.powi(4) - s.t_amb_k.powi(4)) / s4;
        if gain > loss {
            lo = mid;
        } else {
            hi = mid;
        }
    }
    0.5 * (lo + hi)
}
