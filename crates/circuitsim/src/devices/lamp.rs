//! An incandescent lamp: a compiled port of `varimu/devices/lamp.py` (its docstring has
//! the physics and the sources of the tungsten fits).
//!
//! Pins (a, t, b), two ports relative to b: the filament's voltage, and its temperature
//! above ambient (1 V = 1 K; the circuit's 1 F capacitor from t to b integrates the
//! port's current, dT/dt). The model is stateless: the temperature is a node voltage.

use std::f64::consts::PI;

use super::Device;
use crate::ir;

/// Stefan-Boltzmann constant (CODATA 2018).
pub const SIGMA_W_M2K4: f64 = 5.670374419e-8;
/// Tungsten's density at room temperature (kg/m^3).
pub const DENSITY_KG_M3: f64 = 19250.0;
/// Tungsten's molar mass (kg/mol).
pub const MOLAR_KG: f64 = 0.18384;
pub const T_MIN_K: f64 = 200.0;
pub const T_MAX_K: f64 = 3400.0;
/// Newton step limits (numerics only): see [`Lamp::limit`].
pub const LIMIT_STEP_K: f64 = 50.0;
pub const LIMIT_STEP_V: f64 = 1.0;
/// dT/dt per kelvin past the fits' range (numerics only), as lamp.py's.
pub const G_EXT_PER_S: f64 = 100.0;

// White-Minges resistivity (1e-8 ohm m), White-Minges specific heat (J / (mol K)) and the
// modified Hust-Lankford conductivity (W / (m K)): see lamp.py.
const RHO: [f64; 5] = [-0.9680, 1.9274e-2, 7.8260e-6, -1.8517e-9, 2.0790e-13];
const CP: [f64; 5] = [
    21.868372,
    8.068661e-3,
    -3.756196e-6,
    1.075862e-9,
    1.406637e4,
];
const KTH: [f64; 5] = [149.441, -45.466e-3, 13.193e-6, -1.484e-9, 3.866e6];

/// Resistivity (ohm m) and its derivative.
fn rho_ohm_m(t: f64) -> (f64, f64) {
    let [a0, a1, a2, a3, a4] = RHO;
    let r = (((a4 * t + a3) * t + a2) * t + a1) * t + a0;
    let d = ((4.0 * a4 * t + 3.0 * a3) * t + 2.0 * a2) * t + a1;
    (r * 1e-8, d * 1e-8)
}

/// Specific heat (J / (kg K)) and its derivative.
fn cp_j_kg_k(t: f64) -> (f64, f64) {
    let [b0, b1, b2, b3, b4] = CP;
    let c = ((b3 * t + b2) * t + b1) * t + b0 + b4 / (t * t);
    let d = (3.0 * b3 * t + 2.0 * b2) * t + b1 - 2.0 * b4 / (t * t * t);
    (c / MOLAR_KG, d / MOLAR_KG)
}

fn k_w_m_k(t: f64) -> f64 {
    let [k0, k1, k2, k3, k4] = KTH;
    ((k3 * t + k2) * t + k1) * t + k0 + k4 / (t * t)
}

fn k_integral(t: f64) -> f64 {
    let [k0, k1, k2, k3, k4] = KTH;
    (((k3 / 4.0 * t + k2 / 3.0) * t + k1 / 2.0) * t + k0) * t - k4 / t
}

#[derive(Debug, Clone)]
pub struct Lamp {
    t_amb: f64,
    eps: [f64; 4],
    r_per_rho: f64,
    /// sigma times the radiating area.
    sa: f64,
    g_cond: f64,
    mass: f64,
    /// The integral of k at ambient.
    kint_amb: f64,
}

impl Lamp {
    pub fn new(m: &ir::Lamp) -> Lamp {
        let d = m.wire_d_m;
        let l = m.wire_l_m;
        let area = PI * d * d / 4.0;
        let rad_area = m.rad_fraction * PI * d * l;
        Lamp {
            t_amb: m.t_amb_k,
            eps: m.emissivity,
            r_per_rho: l / area,
            sa: SIGMA_W_M2K4 * rad_area,
            g_cond: 12.0 * area / l,
            mass: DENSITY_KG_M3 * area * l,
            kint_amb: k_integral(m.t_amb_k),
        }
    }

    /// Heat out (radiation and conduction, W) and its derivative, at clamped `t`.
    fn loss(&self, t: f64) -> (f64, f64) {
        let [c0, c1, c2, c3] = self.eps;
        let e = ((c3 * t + c2) * t + c1) * t + c0;
        let de = (3.0 * c3 * t + 2.0 * c2) * t + c1;
        let ta = self.t_amb;
        let t2 = t * t;
        let ta2 = ta * ta;
        let q4 = t2 * t2 - ta2 * ta2;
        let p_rad = self.sa * e * q4;
        let dp_rad = self.sa * (de * q4 + e * 4.0 * t2 * t);
        let p_cond = self.g_cond * (k_integral(t) - self.kint_amb);
        let dp_cond = self.g_cond * k_w_m_k(t);
        (p_rad + p_cond, dp_rad + dp_cond)
    }
}

impl Device for Lamp {
    fn ports(&self) -> usize {
        2
    }

    fn eval(&self, v: &[f64], i: &mut [f64], g: &mut [f64]) {
        let (va, u) = (v[0], v[1]);
        let traw = self.t_amb + u;
        let t = traw.clamp(T_MIN_K, T_MAX_K);
        let inside = (T_MIN_K..=T_MAX_K).contains(&traw);
        let (rho, drho) = rho_ohm_m(t);
        let r = rho * self.r_per_rho;
        let dr = drho * self.r_per_rho;
        let ia = va / r;
        let heat = va * ia;
        let (loss, dloss) = self.loss(t);
        let (c, dc) = cp_j_kg_k(t);
        let mc = self.mass * c;
        let dmc = self.mass * dc;
        let it = (loss - heat) / mc + G_EXT_PER_S * (traw - t);
        i[0] = ia;
        i[1] = it;
        g[0] = 1.0 / r;
        g[2] = -2.0 * ia / mc;
        if inside {
            g[1] = -ia * (dr / r);
            g[3] = (dloss + heat * (dr / r)) / mc - it * (dmc / mc);
        } else {
            g[1] = 0.0;
            g[3] = G_EXT_PER_S;
        }
    }

    /// The thermal port is its node's only DC path (the 1 F capacitor is open at DC): its
    /// conductance spans ~0.1 (cold) to ~100 (at the rating) kelvin per second per kelvin.
    /// The filament: ~1e-3 to ~2e-2 S.
    fn shunt(&self, port: usize) -> f64 {
        if port == 0 { 1e-3 } else { 1.0 }
    }

    /// Newton step limiting (numerics only): a cold filament's thermal resistance is
    /// ~4e5 K/W, so far from the solution a millivolt's misestimate of the heating moves its
    /// temperature by hundreds of kelvin and Newton runs away with the circuit around it.
    /// The temperature moves at most [`LIMIT_STEP_K`] or half its rise per iteration, the
    /// filament's voltage at most [`LIMIT_STEP_V`] or half its value, and the temperature
    /// stays in the fits' range.
    fn limit(&self, v: &mut [f64], v_old: &[f64]) -> bool {
        let (want_v, want_u) = (v[0], v[1]);
        let dv = LIMIT_STEP_V.max(0.5 * v_old[0].abs());
        v[0] = want_v.clamp(v_old[0] - dv, v_old[0] + dv);
        let du = LIMIT_STEP_K.max(0.5 * v_old[1].abs());
        let lo = T_MIN_K - self.t_amb;
        let hi = T_MAX_K - self.t_amb;
        let u = want_u
            .clamp(v_old[1] - du, v_old[1] + du)
            .clamp(lo.min(v_old[1]), hi.max(v_old[1]));
        v[1] = u;
        v[0] != want_v || u != want_u
    }
}
