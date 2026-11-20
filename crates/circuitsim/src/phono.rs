//! Groove players and their drives (docs/PHONO_PLAN.md, G1's Rust half): the hot loops of
//! `varimu/phono/` step for step, the Python reference's numbers in and out.
//!
//! **The player** ([`Player`], [`play`]). A machine's linear mechano-acoustic network
//! (`varimu/phono/network.py`: the stylus, the diaphragm, the ducts and horn, the mouth's
//! radiation) stepped by the trapezoidal rule, x1 = P x0 + Q0 u0 + Q1 u1, arrives here in
//! **modal form**: Python diagonalizes P = V diag(lam) V^-1 once (`network.modal`) and
//! sends lam, each input's columns V^-1 Q0 / V^-1 Q1, and each read-out row c V. A real
//! network's complex modes come in conjugate pairs whose states stay conjugate under real
//! inputs, so Python keeps one of each pair and doubles its read-out rows: a read-out is
//! Re(sum_m c_m xi_m). Per step that is O(modes) instead of the dense O(states^2), and
//! exact to rounding (-220 dB against the dense stepper on the cylinder's reproducer).
//!
//! Inputs are known per step (the floating weight's gravity, ...); **contacts** are
//! inputs whose value at the step's end is solved: a tip meeting a precomputed surface
//! (the groove dilated by the tip, along the contact's normal) through a Hertz law with
//! Hunt and Crossley's damping,
//!
//!     f_k = K_k d_k^1.5 (1 + alpha_k (d_k - d_k,prev) / h),  f_k >= 0,
//!     d_k = a_k - sum_j Kff_kj f_j,   a_k = surface_k - Re(row_k . xi_pred),
//!
//! a_k the indentation if no contact pushed, Kff_kj = Re(row_k . B1_j) how far contact
//! j's force moves contact k's tip by the step's end. One contact (the cylinder's floor)
//! is solved as `cylinder._solve_contact` (bisection safeguarding Newton); several (a
//! V-groove's two walls) by projected Newton on R(f) = f - law(a - Kff f), the same
//! algorithm as `varimu/phono/contacts.py`. Mistracking is where a force is 0.
//!
//! **The drive** ([`Drive`], [`drive`]): `varimu/phono/transport.py`'s seven-state spring
//! motor, flyball governor, belt (or gear train) and mandrel (or turntable), RK4 at the
//! transport's rate. The seeded draws (the mainspring's irregularity, the felt's harmonics,
//! the pulleys' phases) are Python's and arrive as numbers.

use serde::Deserialize;

/// A complex vector as its real and imaginary parts.
pub type CVec = [Vec<f64>; 2];

#[derive(Debug, Clone, Deserialize)]
pub struct Input {
    pub b0: CVec,
    pub b1: CVec,
}

#[derive(Debug, Clone, Deserialize)]
pub struct Contact {
    pub b0: CVec,
    pub b1: CVec,
    /// The tip's coordinate along the contact's normal (toward the groove's air).
    pub row: CVec,
    /// Hertz: F = k d^1.5.
    pub k: f64,
    /// Hunt and Crossley's damping (s/m).
    pub alpha: f64,
}

/// The modal network and its ports (`varimu/phono/fast.py` writes it as JSON).
#[derive(Debug, Clone, Deserialize)]
pub struct Player {
    pub lam: CVec,
    /// The modal state at sample 0.
    pub xi0: CVec,
    pub inputs: Vec<Input>,
    pub contacts: Vec<Contact>,
    pub outputs: Vec<CVec>,
}

impl Player {
    pub fn modes(&self) -> usize {
        self.lam[0].len()
    }

    pub fn check(&self) -> Result<(), String> {
        let n = self.modes();
        let ok = |v: &CVec| v[0].len() == n && v[1].len() == n;
        if self.lam[1].len() != n || !ok(&self.xi0) {
            return Err("phono player: lam / xi0 lengths differ".into());
        }
        for i in &self.inputs {
            if !ok(&i.b0) || !ok(&i.b1) {
                return Err("phono player: an input's columns have the wrong length".into());
            }
        }
        for c in &self.contacts {
            if !ok(&c.b0) || !ok(&c.b1) || !ok(&c.row) {
                return Err("phono player: a contact's vectors have the wrong length".into());
            }
            if c.k.is_nan() || c.k <= 0.0 {
                return Err("phono player: a contact's stiffness must be > 0".into());
            }
        }
        if self.contacts.len() > MAX_CONTACTS {
            return Err(format!("phono player: at most {MAX_CONTACTS} contacts"));
        }
        if self.outputs.iter().any(|o| !ok(o)) {
            return Err("phono player: an output row has the wrong length".into());
        }
        Ok(())
    }
}

pub const MAX_CONTACTS: usize = 4;

/// Re(a . b) for complex vectors.
fn re_dot(a: &CVec, br: &[f64], bi: &[f64]) -> f64 {
    let (ar, ai) = (&a[0], &a[1]);
    let mut s = 0.0;
    for m in 0..br.len() {
        s += ar[m] * br[m] - ai[m] * bi[m];
    }
    s
}

/// What a run returns: per step each contact's force and each output's value
/// (row-major: `forces[k * steps + i]`).
pub struct Played {
    pub forces: Vec<f64>,
    pub outputs: Vec<f64>,
}

/// Plays `steps` steps at step `h`: `u[j * steps + i]` input j at step i,
/// `surfaces[k * steps + i]` contact k's surface at step i. Step 0 is the initial state
/// (its forces 0). Each step: the state predicted with the contacts' forces at the step's
/// start, the contacts' forces at its end solved, the state completed.
pub fn play(p: &Player, u: &[f64], surfaces: &[f64], steps: usize, h: f64) -> Played {
    let n = p.modes();
    let nc = p.contacts.len();
    let no = p.outputs.len();
    let (lr, li) = (&p.lam[0], &p.lam[1]);
    let mut xr = p.xi0[0].clone();
    let mut xi = p.xi0[1].clone();
    let mut pr = vec![0.0; n];
    let mut pi = vec![0.0; n];
    let mut forces = vec![0.0; nc * steps];
    let mut outputs = vec![0.0; no * steps];
    if steps == 0 {
        return Played { forces, outputs };
    }
    for (o, row) in p.outputs.iter().enumerate() {
        outputs[o * steps] = re_dot(row, &xr, &xi);
    }
    // Kff[k][j] = Re(row_k . B1_j).
    let mut kff = [[0.0; MAX_CONTACTS]; MAX_CONTACTS];
    for (k, ck) in p.contacts.iter().enumerate() {
        for (j, cj) in p.contacts.iter().enumerate() {
            kff[k][j] = re_dot(&ck.row, &cj.b1[0], &cj.b1[1]);
        }
    }
    let mut f0 = [0.0; MAX_CONTACTS];
    let mut d0 = [0.0; MAX_CONTACTS];
    for i in 1..steps {
        // xi_pred = lam xi + sum_j (B0_j u_j[i-1] + B1_j u_j[i]) + sum_k B0_k f0_k.
        for m in 0..n {
            pr[m] = lr[m] * xr[m] - li[m] * xi[m];
            pi[m] = lr[m] * xi[m] + li[m] * xr[m];
        }
        for (j, inp) in p.inputs.iter().enumerate() {
            let (ua, ub) = (u[j * steps + i - 1], u[j * steps + i]);
            if ua == 0.0 && ub == 0.0 {
                continue;
            }
            let (b0r, b0i, b1r, b1i) = (&inp.b0[0], &inp.b0[1], &inp.b1[0], &inp.b1[1]);
            for m in 0..n {
                pr[m] += b0r[m] * ua + b1r[m] * ub;
                pi[m] += b0i[m] * ua + b1i[m] * ub;
            }
        }
        for (k, c) in p.contacts.iter().enumerate() {
            let f = f0[k];
            if f == 0.0 {
                continue;
            }
            for m in 0..n {
                pr[m] += c.b0[0][m] * f;
                pi[m] += c.b0[1][m] * f;
            }
        }
        // Each contact's indentation if no force acted at the step's end.
        let mut a = [0.0; MAX_CONTACTS];
        for (k, c) in p.contacts.iter().enumerate() {
            a[k] = surfaces[k * steps + i] - re_dot(&c.row, &pr, &pi);
        }
        let f1 = solve_contacts(&p.contacts, &a[..nc], &kff, &d0[..nc], h);
        for k in 0..nc {
            let mut d = a[k];
            for j in 0..nc {
                d -= kff[k][j] * f1[j];
            }
            d0[k] = d.max(0.0);
            forces[k * steps + i] = f1[k];
        }
        xr.copy_from_slice(&pr);
        xi.copy_from_slice(&pi);
        for (k, c) in p.contacts.iter().enumerate() {
            let f = f1[k];
            if f == 0.0 {
                continue;
            }
            for m in 0..n {
                xr[m] += c.b1[0][m] * f;
                xi[m] += c.b1[1][m] * f;
            }
        }
        for (o, row) in p.outputs.iter().enumerate() {
            outputs[o * steps + i] = re_dot(row, &xr, &xi);
        }
        f0 = f1;
    }
    Played { forces, outputs }
}

/// The Hertz law with its rate term, and its derivative in d (0 out of contact).
fn law(c: &Contact, d: f64, d_prev: f64, h: f64) -> (f64, f64) {
    if d <= 0.0 {
        return (0.0, 0.0);
    }
    let rate = 1.0 + c.alpha * (d - d_prev) / h;
    let f = c.k * d.powf(1.5) * rate;
    if f < 0.0 {
        return (0.0, 0.0); // separating faster than the surface recovers: no force
    }
    (f, c.k * (1.5 * d.sqrt() * rate + d.powf(1.5) * c.alpha / h))
}

/// The contacts' forces at the step's end.
pub fn solve_contacts(
    cs: &[Contact],
    a: &[f64],
    kff: &[[f64; MAX_CONTACTS]; MAX_CONTACTS],
    d_prev: &[f64],
    h: f64,
) -> [f64; MAX_CONTACTS] {
    let mut f = [0.0; MAX_CONTACTS];
    match cs.len() {
        0 => {}
        1 => {
            if a[0] > 0.0 {
                f[0] = solve_one(a[0], kff[0][0], cs[0].k, cs[0].alpha, d_prev[0], h);
            }
        }
        _ => solve_many(cs, a, kff, d_prev, h, &mut f),
    }
    f
}

/// One contact (`cylinder._solve_contact`): f >= 0 with f = K d^1.5 (1 + alpha (d -
/// d_prev) / h), d = a - kff f; the residual is increasing in f on [0, a / kff]: bisection
/// safeguarding Newton.
pub fn solve_one(a: f64, kff: f64, big_k: f64, alpha: f64, d_prev: f64, h: f64) -> f64 {
    let (mut lo, mut hi) = (0.0, a / kff);
    let mut f = (big_k * a.powf(1.5)).min(hi);
    for _ in 0..60 {
        let d = a - kff * f;
        let rate = 1.0 + alpha * (d - d_prev) / h;
        let mut lw = big_k * d.powf(1.5) * rate;
        if lw < 0.0 {
            lw = 0.0;
        }
        let r = f - lw;
        if r > 0.0 {
            hi = f;
        } else {
            lo = f;
        }
        if r.abs() <= 1e-12 * f.max(1.0) {
            return f;
        }
        let dlaw = if lw > 0.0 {
            -kff * big_k * (1.5 * d.sqrt() * rate + d.powf(1.5) * alpha / h)
        } else {
            0.0
        };
        let fnew = f - r / (1.0 - dlaw);
        f = if lo < fnew && fnew < hi {
            fnew
        } else {
            0.5 * (lo + hi)
        };
        if hi - lo <= 1e-15 * hi.max(1.0) {
            return f;
        }
    }
    f
}

/// Several coupled contacts (`varimu/phono/contacts.py`'s `solve`): projected Newton on
/// R(f) = f - law(a - Kff f) with backtracking on |R|_inf, from the contacts solved alone.
fn solve_many(
    cs: &[Contact],
    a: &[f64],
    kff: &[[f64; MAX_CONTACTS]; MAX_CONTACTS],
    d_prev: &[f64],
    h: f64,
    f: &mut [f64; MAX_CONTACTS],
) {
    let n = cs.len();
    for k in 0..n {
        f[k] = if a[k] > 0.0 {
            solve_one(a[k], kff[k][k], cs[k].k, cs[k].alpha, d_prev[k], h)
        } else {
            0.0
        };
    }
    let resid =
        |f: &[f64; MAX_CONTACTS], r: &mut [f64; MAX_CONTACTS], g: &mut [f64; MAX_CONTACTS]| {
            let mut worst: f64 = 0.0;
            for k in 0..n {
                let mut d = a[k];
                for j in 0..n {
                    d -= kff[k][j] * f[j];
                }
                let (lw, dl) = law(&cs[k], d, d_prev[k], h);
                r[k] = f[k] - lw;
                g[k] = dl;
                worst = worst.max(r[k].abs());
            }
            worst
        };
    let mut r = [0.0; MAX_CONTACTS];
    let mut g = [0.0; MAX_CONTACTS];
    let mut norm = resid(f, &mut r, &mut g);
    for _ in 0..60 {
        let scale = f[..n].iter().fold(1.0_f64, |m, x| m.max(x.abs()));
        if norm <= 1e-12 * scale {
            return;
        }
        // J = I + diag(law') Kff; solve J step = R.
        let mut jm = [[0.0; MAX_CONTACTS]; MAX_CONTACTS];
        for k in 0..n {
            for j in 0..n {
                jm[k][j] = g[k] * kff[k][j] + if k == j { 1.0 } else { 0.0 };
            }
        }
        let step = gauss(&jm, &r, n);
        let mut t = 1.0;
        let mut accepted = false;
        for _ in 0..40 {
            let mut trial = *f;
            for k in 0..n {
                trial[k] = (f[k] - t * step[k]).max(0.0);
            }
            let mut rt = [0.0; MAX_CONTACTS];
            let mut gt = [0.0; MAX_CONTACTS];
            let nt = resid(&trial, &mut rt, &mut gt);
            if nt < norm {
                *f = trial;
                r = rt;
                g = gt;
                norm = nt;
                accepted = true;
                break;
            }
            t *= 0.5;
        }
        if !accepted {
            return;
        }
    }
}

/// Gaussian elimination with partial pivoting on an n x n system (n <= MAX_CONTACTS).
fn gauss(
    m: &[[f64; MAX_CONTACTS]; MAX_CONTACTS],
    b: &[f64; MAX_CONTACTS],
    n: usize,
) -> [f64; MAX_CONTACTS] {
    let mut a = *m;
    let mut x = *b;
    for col in 0..n {
        let piv = (col..n)
            .max_by(|&i, &j| a[i][col].abs().total_cmp(&a[j][col].abs()))
            .unwrap_or(col);
        a.swap(col, piv);
        x.swap(col, piv);
        let d = a[col][col];
        if d == 0.0 {
            continue;
        }
        let pivot = a[col];
        for row in col + 1..n {
            let fac = a[row][col] / d;
            for (v, p) in a[row][col..n].iter_mut().zip(&pivot[col..n]) {
                *v -= fac * p;
            }
            x[row] -= fac * x[col];
        }
    }
    for col in (0..n).rev() {
        let mut s = x[col];
        for k in col + 1..n {
            s -= a[col][k] * x[k];
        }
        x[col] = if a[col][col] != 0.0 {
            s / a[col][col]
        } else {
            0.0
        };
    }
    x
}

/// `transport.simulate`'s machine, its seeded draws already made.
#[derive(Debug, Clone, Deserialize)]
pub struct Drive {
    pub h: f64,
    pub r1: f64,
    pub r2: f64,
    pub e1: f64,
    pub e2: f64,
    pub pe1: f64,
    pub pe2: f64,
    pub jp: f64,
    pub jd: f64,
    pub bp: f64,
    pub bd: f64,
    pub kb: f64,
    pub cb: f64,
    pub g_ratio: f64,
    pub wg: f64,
    pub zeta: f64,
    pub k_brake: f64,
    pub t_spring0: f64,
    pub droop: f64,
    pub y_set: f64,
    pub w_gov0: f64,
    /// The felt's harmonics: mu / mu0 = 1 + sum a_k cos(k phi + p_k), k = 1, 2, ...
    pub felt_amps: Vec<f64>,
    pub felt_phases: Vec<f64>,
    /// The state at the start: (th_p, w_p, th_d, w_d, u, y, y').
    pub state0: [f64; 7],
}

impl Drive {
    fn felt(&self, phi: f64) -> f64 {
        let mut s = 0.0;
        for (k, (a, p)) in self.felt_amps.iter().zip(&self.felt_phases).enumerate() {
            s += a * ((k + 1) as f64 * phi + p).cos();
        }
        1.0 + s
    }

    fn deriv(&self, i: usize, st: &[f64; 7], frac: f64, spring: &[f64], load: &[f64]) -> [f64; 7] {
        let [thp, wp, thd, wd, u, y, yd] = *st;
        let r1t = self.r1 + self.e1 * (thp + self.pe1).cos();
        let r2t = self.r2 + self.e2 * (thd + self.pe2).cos();
        let ud = r1t * wp - r2t * wd;
        let force = self.kb * u + self.cb * ud;
        let t = (i as f64 + frac) * self.h;
        let ts = self.t_spring0 * (1.0 - self.droop * t) * (1.0 + spring[i]);
        let brake = self.k_brake * (y - self.y_set).max(0.0) * self.felt(self.g_ratio * thp);
        let wpd = (ts - brake - r1t * force - self.bp * wp) / self.jp;
        let wdd = (r2t * force - load[i] - self.bd * wd) / self.jd;
        let r = self.g_ratio * wp / self.w_gov0;
        let ydd = self.wg * self.wg * (r * r - y) - 2.0 * self.zeta * self.wg * yd;
        [wp, wpd, wd, wdd, ud, yd, ydd]
    }
}

/// The drive run for `spring.len()` steps (spring: the mainspring's relative
/// irregularity per step; load: the mandrel's load torque per step). Returns the mandrel's
/// angular velocity and angle at each step's start.
pub fn drive(d: &Drive, spring: &[f64], load: &[f64]) -> (Vec<f64>, Vec<f64>) {
    let n = spring.len().min(load.len());
    let h = d.h;
    let mut st = d.state0;
    let mut w = Vec::with_capacity(n);
    let mut th = Vec::with_capacity(n);
    let add = |a: &[f64; 7], b: &[f64; 7], s: f64| {
        let mut o = [0.0; 7];
        for k in 0..7 {
            o[k] = a[k] + s * b[k];
        }
        o
    };
    for i in 0..n {
        w.push(st[3]);
        th.push(st[2]);
        let k1 = d.deriv(i, &st, 0.0, spring, load);
        let k2 = d.deriv(i, &add(&st, &k1, 0.5 * h), 0.5, spring, load);
        let k3 = d.deriv(i, &add(&st, &k2, 0.5 * h), 0.5, spring, load);
        let k4 = d.deriv(i, &add(&st, &k3, h), 1.0, spring, load);
        for k in 0..7 {
            st[k] += h / 6.0 * (k1[k] + 2.0 * k2[k] + 2.0 * k3[k] + k4[k]);
        }
    }
    (w, th)
}

#[cfg(test)]
mod tests {
    use super::*;

    /// One mode, no contacts: the output follows lam^i.
    #[test]
    fn a_free_mode_decays_by_its_eigenvalue() {
        let lam = [0.9_f64, 0.1];
        let p = Player {
            lam: [vec![lam[0]], vec![lam[1]]],
            xi0: [vec![1.0], vec![0.0]],
            inputs: vec![],
            contacts: vec![],
            outputs: vec![[vec![1.0], vec![0.0]]],
        };
        p.check().unwrap();
        let out = play(&p, &[], &[], 5, 1e-3);
        let mut z = (1.0_f64, 0.0_f64);
        for i in 0..5 {
            assert!((out.outputs[i] - z.0).abs() < 1e-15);
            z = (lam[0] * z.0 - lam[1] * z.1, lam[0] * z.1 + lam[1] * z.0);
        }
    }

    /// The coupled solver agrees with the single one when the contacts don't couple, and
    /// satisfies the law when they do.
    #[test]
    fn coupled_contacts_satisfy_their_laws() {
        let c = |k: f64| Contact {
            b0: [vec![], vec![]],
            b1: [vec![], vec![]],
            row: [vec![], vec![]],
            k,
            alpha: 2.0,
        };
        let cs = [c(3e7), c(5e7)];
        let h = 1.0 / 192000.0;
        let a = [2e-6, 1e-6];
        let d_prev = [1.5e-6, 0.5e-6];
        let mut kff = [[0.0; MAX_CONTACTS]; MAX_CONTACTS];
        kff[0][0] = 1e-6;
        kff[1][1] = 2e-6;
        let f = solve_contacts(&cs, &a, &kff, &d_prev, h);
        for k in 0..2 {
            let one = solve_one(a[k], kff[k][k], cs[k].k, cs[k].alpha, d_prev[k], h);
            assert!((f[k] - one).abs() <= 1e-12 * one.max(1.0));
        }
        kff[0][1] = -0.8e-6;
        kff[1][0] = -0.8e-6;
        let f = solve_contacts(&cs, &a, &kff, &d_prev, h);
        for k in 0..2 {
            let d = a[k] - kff[k][0] * f[0] - kff[k][1] * f[1];
            let (lw, _) = law(&cs[k], d, d_prev[k], h);
            assert!(
                (f[k] - lw).abs() <= 1e-9 * f[k].max(1e-6),
                "{k}: {} vs {lw}",
                f[k]
            );
        }
    }
}
