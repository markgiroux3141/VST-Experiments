//! A hot-cathode gas thyratron as a lumped plasma: a compiled port of
//! `varimu/devices/thyratron.py` (its docstring has the physics and the parameters'
//! roles; HYBRID_PHYSICS_PLAN.md H1).
//!
//! A tetrode's pins (a, g2, g1, w, k), four ports relative to the cathode k: the anode,
//! the shield grid, the control grid, and the plasma's state, w = ln x (x the ion density;
//! 1 V = one e-fold); a triode's (a, g, w, k), three. The circuit's 1 F capacitor from w to
//! k integrates the state; the w port's current is -dw/dt. The model is stateless: the
//! density is a node voltage.

use super::{Device, sigmoid, softplus};
use crate::ir;

/// The state's range (numerics only): above `W_MAX` the density is held at its value
/// there plus a restoring `G_EXT_PER_S` (w - W_MAX) in the w port, as the lamp holds
/// its temperature range; below `W_MIN` likewise. x spans e^-80 to e^40.
pub const W_MIN: f64 = -80.0;
pub const W_MAX: f64 = 40.0;
pub const G_EXT_PER_S: f64 = 1e6;
/// Newton step limit on the state (e-folds per iteration; numerics only).
pub const LIMIT_STEP_W: f64 = 3.0;

#[derive(Debug, Clone)]
pub struct Thyratron {
    m: ir::Thyratron,
}

/// Port voltages' gradients: (d/dva, d/dvg2, d/dvg1, d/dw).
type Grad = [f64; 4];

fn scale(a: Grad, s: f64) -> Grad {
    [a[0] * s, a[1] * s, a[2] * s, a[3] * s]
}

fn add(a: Grad, b: Grad) -> Grad {
    [a[0] + b[0], a[1] + b[1], a[2] + b[2], a[3] + b[3]]
}

impl Thyratron {
    pub fn new(m: &ir::Thyratron) -> Thyratron {
        Thyratron { m: m.clone() }
    }

    /// The anode current and its gradient, at density x (dx/dw = x).
    fn anode(&self, va: f64, vg2: f64, vg1: f64, x: f64, dx: f64) -> (f64, Grad) {
        let m = &self.m;
        let ev = m.e_v;
        let inv_g2 = m.mu_g2.map_or(0.0, |mu| 1.0 / mu);
        let vc = match m.mu_g2 {
            Some(mu) => vg1 + vg2 / mu + va / m.mu_a,
            None => vg1 + va / m.mu_a,
        };
        let dvc: Grad = [1.0 / m.mu_a, inv_g2, 1.0, 0.0];
        let dva: Grad = [1.0, 0.0, 0.0, 0.0];
        let z1 = (va - vc) / ev;
        let d = ev * softplus(z1);
        let dd = scale(add(dva, scale(dvc, -1.0)), sigmoid(z1));
        let vx = m.v_x_v * x;
        let dvx: Grad = [0.0, 0.0, 0.0, m.v_x_v * dx];
        let f = vx / (vx + d);
        let phi1 = vc + d * f;
        let dphi1 = add(
            add(dvc, scale(dd, f * f)),
            scale(dvx, (1.0 - f) * (1.0 - f)),
        );
        let z2 = (phi1 - va) / ev;
        let phi = phi1 - ev * softplus(z2);
        let s2 = sigmoid(z2);
        let dphi = add(scale(dphi1, 1.0 - s2), scale(dva, s2));
        let z3 = (phi - m.v0_v) / ev;
        let u = ev * softplus(z3);
        let du = scale(dphi, sigmoid(z3));
        let s = 1.0 + x / m.x_n;
        let u15 = u * u.sqrt();
        let ia = m.perveance * s * u15;
        let mut g = scale(du, m.perveance * s * 1.5 * u.sqrt());
        g[3] += m.perveance * (dx / m.x_n) * u15;
        (ia, g)
    }

    fn grid_loss(&self, vg1: f64) -> (f64, f64) {
        let m = &self.m;
        let zs = (m.v_float_v - vg1) / m.t_e_v;
        let h = m.t_e_v * softplus(zs);
        if h <= 0.0 {
            // the grid far above its floating potential: no sheath (h^(p-1) sigmoid -> 0)
            return (0.0, 0.0);
        }
        let gl = m.k_grid * h.powf(m.p_grid);
        let dgl = -m.k_grid * m.p_grid * h.powf(m.p_grid - 1.0) * sigmoid(zs);
        (gl, dgl)
    }
}

impl Device for Thyratron {
    fn ports(&self) -> usize {
        if self.m.mu_g2.is_some() { 4 } else { 3 }
    }

    fn eval(&self, v: &[f64], i: &mut [f64], g: &mut [f64]) {
        if self.m.mu_g2.is_some() {
            self.eval4(v, i, g);
        } else {
            // a triode: the tetrode's equations without the shield grid's row and column
            let (mut i4, mut g4) = ([0.0; 4], [0.0; 16]);
            self.eval4(&[v[0], 0.0, v[1], v[2]], &mut i4, &mut g4);
            const KEEP: [usize; 3] = [0, 2, 3];
            for (r, &kr) in KEEP.iter().enumerate() {
                i[r] = i4[kr];
                for (c, &kc) in KEEP.iter().enumerate() {
                    g[r * 3 + c] = g4[kr * 4 + kc];
                }
            }
        }
    }

    /// The state port is its node's only DC path (the 1 F capacitor is open at DC): its
    /// conductance is the plasma's loss rate, ~1e4-1e6 per second.
    fn shunt(&self, port: usize) -> f64 {
        if port == self.ports() - 1 { 1e4 } else { 0.0 }
    }

    /// The state moves at most [`LIMIT_STEP_W`] e-folds per iteration (far from the
    /// solution an exponential density runs Newton away), and stays in its range.
    fn limit(&self, v: &mut [f64], v_old: &[f64]) -> bool {
        let k = self.ports() - 1;
        let want = v[k];
        let w = want
            .clamp(v_old[k] - LIMIT_STEP_W, v_old[k] + LIMIT_STEP_W)
            .clamp(W_MIN.min(v_old[k]), W_MAX.max(v_old[k]));
        v[k] = w;
        w != want
    }
}

impl Thyratron {
    /// The tetrode's ports (va, vg2, vg1, w): currents and the 4 x 4 Jacobian.
    fn eval4(&self, v: &[f64], i: &mut [f64], g: &mut [f64]) {
        let m = &self.m;
        let (va, vg2, vg1, wraw) = (v[0], v[1], v[2], v[3]);
        let w = wraw.clamp(W_MIN, W_MAX);
        let inside = (W_MIN..=W_MAX).contains(&wraw);
        let x = w.exp();
        let dx = if inside { x } else { 0.0 };
        let (ia, dia) = self.anode(va, vg2, vg1, x, dx);
        // ionization
        let zi = (va - m.v_ion_v) / m.w_ion_v;
        let zm = (va - m.v_meta_v) / m.w_meta_v;
        let step = m.c_meta * (x / m.x_n) * m.w_meta_v;
        let nu = m.w_ion_v * softplus(zi) + step * softplus(zm);
        let dnu_va = sigmoid(zi) + m.c_meta * (x / m.x_n) * sigmoid(zm);
        let dnu_w = m.c_meta * (dx / m.x_n) * m.w_meta_v * softplus(zm);
        let (gl, dgl) = self.grid_loss(vg1);
        let loss = 1.0 / m.tau_diff_s + gl;
        let prod = m.k_ion * nu * ia + m.s0_per_s;
        let iw = -prod / x + loss + G_EXT_PER_S * (wraw - w);
        // d prod: k_ion (dnu ia + nu dia)
        let dprod: Grad = [
            m.k_ion * (dnu_va * ia + nu * dia[0]),
            m.k_ion * nu * dia[1],
            m.k_ion * nu * dia[2],
            m.k_ion * (dnu_w * ia + nu * dia[3]),
        ];
        // grid current
        let zs = (m.v_float_v - vg1) / m.t_e_v;
        let (glf, _) = self.grid_loss(m.v_float_v);
        let el = 2.0 * glf * (-softplus(zs)).exp();
        let del = el * sigmoid(zs) / m.t_e_v;
        let ig1 = m.g_leak_s * (vg1 - va) + m.q_s_c * x * (el - gl);
        i[0] = ia;
        i[1] = 0.0;
        i[2] = ig1;
        i[3] = iw;
        // rows: (ia, ig2, ig1, iw); columns (va, vg2, vg1, w)
        g[..4].copy_from_slice(&dia);
        g[4..8].fill(0.0);
        g[8] = -m.g_leak_s;
        g[9] = 0.0;
        g[10] = m.g_leak_s + m.q_s_c * x * (del - dgl);
        g[11] = m.q_s_c * dx * (el - gl);
        g[12] = -dprod[0] / x;
        g[13] = -dprod[1] / x;
        g[14] = -dprod[2] / x + dgl;
        g[15] = if inside {
            -dprod[3] / x + prod / x
        } else {
            G_EXT_PER_S
        };
    }
}
