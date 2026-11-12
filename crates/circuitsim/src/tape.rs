//! Magnetic tape (docs/TAPE_PLAN.md, TM4): the port of the tape medium's recording kernel.
//! `varimu/devices/preisach.py` and `varimu/devices/tape.py` are the reference; the two
//! agree within rounding (`tests/test_tape.py`).
//!
//! **Particles** ([`Preisach`]): a continuous Preisach ensemble, a lognormal switching-field
//! density f(Hc) times a Gaussian interaction density g(Hi), tabulated as Q(a, b) (the
//! weight of hysterons with alpha <= a, beta < b) and D(x) (the erased state's up weight
//! beyond alpha = x) and read by bicubic (Catmull-Rom) interpolation. A cell's state after
//! a field history, starting erased, is the corner formula: the sum over the history's
//! backward records h_t > max(h after t) of Q(h_t, min after t) - Q(max after t, min
//! after t), plus the never-reached hysterons' erased state. One backward pass per
//! cell, two table lookups per record.
//!
//! **Recording** ([`record`]): each cell at tape position s and layer height y sees the
//! record head's field (Karlqvist with finite poles, both components: [`head_field`])
//! at the bias's sample times while it is within the zone, then a steady field (zero, or
//! its demagnetization) as it leaves. Each easy-axis direction of the particles is an
//! ensemble driven by the field along it (the vector Preisach model). Cells run in
//! parallel.
//!
//! **On the GPU** (TAPE_SPEED_PLAN.md P5): with the `gpu` feature a recording that asks for
//! it ([`Recording::gpu`]) runs on `crates/tapegpu` in f32, its zones resolved to peak
//! ranges here in f64. The f64 CPU kernel stays the reference and the default.

use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::{Arc, Mutex, OnceLock};

/// The particles' tables.
#[derive(Debug, Clone)]
pub struct Preisach {
    /// The parameters' bits (`preisach`'s cache key; the GPU's too).
    key: [u64; 5],
    h_max: f64,
    n: usize,
    /// Q at the nodes, (n + 1) x (n + 1), row a (alpha) major.
    q: Vec<f64>,
    /// D at the nodes, n + 1.
    d: Vec<f64>,
}

/// Catmull-Rom weights for a fraction f (taps at -1, 0, 1, 2).
#[inline]
fn catmull_rom(f: f64) -> [f64; 4] {
    let f2 = f * f;
    let f3 = f * f * f;
    [
        -0.5 * f3 + f2 - 0.5 * f,
        1.5 * f3 - 2.5 * f2 + 1.0,
        -1.5 * f3 + 2.0 * f2 + 0.5 * f,
        0.5 * f3 - 0.5 * f2,
    ]
}

impl Preisach {
    /// The tables of the density f(Hc) g(Hi) / 2 on an n x n grid over +-h_max (as
    /// `varimu.devices.preisach._weights` and `_tables` build them).
    pub fn new(hc_median: f64, sigma_ln_hc: f64, sigma_hi: f64, h_max: f64, n: usize) -> Self {
        let d = 2.0 * h_max / n as f64;
        let c: Vec<f64> = (0..n).map(|i| -h_max + (i as f64 + 0.5) * d).collect();
        let s2pi = (2.0 * std::f64::consts::PI).sqrt();
        let mut w = vec![0.0; n * n];
        let mut total = 0.0;
        for i in 0..n {
            for k in 0..n {
                let hc = 0.5 * (c[i] - c[k]);
                if hc <= 0.0 {
                    continue;
                }
                let hi = -0.5 * (c[i] + c[k]);
                let u = (hc / hc_median).ln() / sigma_ln_hc;
                let f = (-0.5 * u * u).exp() / (hc * sigma_ln_hc * s2pi);
                let v = hi / sigma_hi;
                let g = (-0.5 * v * v).exp() / (sigma_hi * s2pi);
                let x = f * g * d * d / 2.0;
                w[i * n + k] = x;
                total += x;
            }
        }
        for x in &mut w {
            *x /= total;
        }
        // Q: cumulative down alpha, then along beta (numpy's cumsum order).
        let m = n + 1;
        let mut col = vec![0.0; n * n];
        for k in 0..n {
            let mut acc = 0.0;
            for i in 0..n {
                acc += w[i * n + k];
                col[i * n + k] = acc;
            }
        }
        let mut q = vec![0.0; m * m];
        for i in 0..n {
            let mut acc = 0.0;
            for k in 0..n {
                acc += col[i * n + k];
                q[(i + 1) * m + k + 1] = acc;
            }
        }
        // D: the erased state's up weight per row (Hi > 0: i + k < n - 1; half on Hi = 0),
        // summed from the top row down.
        let mut d_tab = vec![0.0; m];
        let mut acc = 0.0;
        for i in (0..n).rev() {
            let mut row = 0.0;
            for k in 0..n {
                let s = i + k;
                let init = if s + 1 < n {
                    1.0
                } else if s + 1 == n {
                    0.5
                } else {
                    0.0
                };
                row += w[i * n + k] * init;
            }
            acc += row;
            d_tab[i] = acc;
        }
        Preisach {
            key: [
                hc_median.to_bits(),
                sigma_ln_hc.to_bits(),
                sigma_hi.to_bits(),
                h_max.to_bits(),
                n as u64,
            ],
            h_max,
            n,
            q,
            d: d_tab,
        }
    }

    #[inline]
    fn node(&self, x: f64) -> (usize, f64) {
        let h = self.h_max;
        let u = (x.clamp(-h, h) + h) * (self.n as f64 / (2.0 * h));
        let i = (u.floor().max(0.0) as usize).min(self.n - 1);
        (i, u - i as f64)
    }

    /// Q(a, b): the weight of hysterons with alpha <= a, beta < b (bicubic).
    pub fn q(&self, a: f64, b: f64) -> f64 {
        let (ib, fb) = self.node(b);
        self.q_at(a, ib, &catmull_rom(fb))
    }

    /// Q(a1, b) - Q(a0, b), b's node and weights found once.
    #[inline]
    fn q_diff(&self, a1: f64, a0: f64, b: f64) -> f64 {
        let (ib, fb) = self.node(b);
        let wb = catmull_rom(fb);
        self.q_at(a1, ib, &wb) - self.q_at(a0, ib, &wb)
    }

    /// Q(a, b) with b's node and weights given.
    #[inline]
    fn q_at(&self, a: f64, ib: usize, wb: &[f64; 4]) -> f64 {
        let (ia, fa) = self.node(a);
        let wa = catmull_rom(fa);
        let m = self.n + 1;
        let mut out = 0.0;
        for (da, wa) in wa.iter().enumerate() {
            let ra = (ia + da).saturating_sub(1).min(self.n);
            let mut acc = 0.0;
            for (db, wb) in wb.iter().enumerate() {
                let rb = (ib + db).saturating_sub(1).min(self.n);
                acc += wb * self.q[ra * m + rb];
            }
            out += wa * acc;
        }
        out
    }

    /// D(x): the erased state's up weight of hysterons with alpha > x (bicubic).
    pub fn d(&self, x: f64) -> f64 {
        let (i, f) = self.node(x);
        let w = catmull_rom(f);
        let mut out = 0.0;
        for (k, w) in w.iter().enumerate() {
            out += w * self.d[(i + k).saturating_sub(1).min(self.n)];
        }
        out
    }

    /// M / Ms after the history `h` (oldest first), starting erased.
    pub fn state_after(&self, h: &[f64]) -> f64 {
        let mut acc = Corner::new(self.h_max);
        for &x in h.iter().rev() {
            acc.push(self, x);
        }
        acc.finish(self)
    }
}

/// The corner formula's backward pass over one history.
#[derive(Debug, Clone, Copy)]
struct Corner {
    nmax: f64,
    nmin: f64,
    up: f64,
    big: f64,
}

impl Corner {
    fn new(h_max: f64) -> Self {
        Corner {
            nmax: f64::NEG_INFINITY,
            nmin: f64::INFINITY,
            up: 0.0,
            big: 4.0 * h_max,
        }
    }

    /// The next older sample.
    #[inline]
    fn push(&mut self, p: &Preisach, x: f64) {
        if x > self.nmax {
            let b = self.nmin.min(self.big);
            let a_next = self.nmax.max(-self.big);
            self.up += p.q_diff(x, a_next, b);
        }
        self.nmax = self.nmax.max(x);
        self.nmin = self.nmin.min(x);
    }

    fn finish(self, p: &Preisach) -> f64 {
        2.0 * self.finish_up(p) - 1.0
    }

    /// The up weight (M / Ms = 2 up - 1).
    fn finish_up(mut self, p: &Preisach) -> f64 {
        let (top, bot) = (self.nmax, self.nmin);
        let x = top.max(-bot);
        self.up += p.q(x, bot) - p.q(top, bot) + p.d(x);
        self.up
    }
}

// --- The moving model (an opt-in variant: TAPE_PLAN.md "Over-bias options") ------------
//
// Della Torre's moving Preisach model: each hysteron sees H + alpha M, M the cell's own
// (irreversible) magnetization, so the state must be followed forward: the wiping-out
// memory as a stack of the history's alternating dominant extrema, each with the up weight
// after it. The erased start is the limit of a decaying alternating history, so below the
// stack's first entry e lies a virtual extremum of the other kind at -e. A new extremum x
// pops what it wipes out; then the up weight is the entry's below it plus (rising from a
// minimum m) T(x, m) or less (falling from a maximum m) T(m, x), T(a, b) = Q(a, a) - Q(a,
// b) the triangle b <= beta < alpha <= a; past the stack's first entry it is the corner
// formula on what is left (at most one entry) and x. The reference is
// `varimu.tape_variants.Stack`.

/// The wiping-out memory of one easy axis's ensemble.
#[derive(Debug, Clone, Default)]
struct Stack {
    v: Vec<f64>,
    up: Vec<f64>,
    max: Vec<bool>,
}

/// The state if `x` came next: its up weight, the entries kept below it, its kind.
#[derive(Debug, Clone, Copy)]
struct Trial {
    x: f64,
    up: f64,
    keep: usize,
    max: bool,
}

impl Stack {
    fn clear(&mut self) {
        self.v.clear();
        self.up.clear();
        self.max.clear();
    }

    fn trial(&self, p: &Preisach, x: f64) -> Trial {
        let n = self.v.len();
        if n > 0 && x == self.v[n - 1] {
            return Trial {
                x,
                up: self.up[n - 1],
                keep: n - 1,
                max: self.max[n - 1],
            };
        }
        let rising = if n == 0 { x > 0.0 } else { x > self.v[n - 1] };
        let mut i = n;
        loop {
            if i == 0 {
                let mut c = Corner::new(p.h_max);
                c.push(p, x);
                return Trial {
                    x,
                    up: c.finish_up(p),
                    keep: 0,
                    max: rising,
                };
            }
            let t = i - 1;
            if self.max[t] == rising {
                // Of the move's own kind, passed by x.
                i -= 1;
                continue;
            }
            let e = self.v[t];
            let below = if t >= 1 { self.v[t - 1] } else { -e };
            if (rising && x >= below) || (!rising && x <= below) {
                // Wiped out with the entry below it (past the first entry: the corner
                // formula on x alone).
                i = t.saturating_sub(1);
                continue;
            }
            let up = if rising {
                self.up[t] + (p.q(x, x) - p.q(x, e))
            } else {
                self.up[t] - (p.q(e, e) - p.q(e, x))
            };
            return Trial {
                x,
                up,
                keep: t + 1,
                max: rising,
            };
        }
    }

    fn commit(&mut self, t: Trial) {
        self.v.truncate(t.keep);
        self.up.truncate(t.keep);
        self.max.truncate(t.keep);
        self.v.push(t.x);
        self.up.push(t.up);
        self.max.push(t.max);
    }
}

/// The moving model's solver counters since the last [`moving_stats`]: (samples solved,
/// samples not converged, the largest residual left in M / Ms).
static MOVING_SOLVES: AtomicUsize = AtomicUsize::new(0);
static MOVING_FAILS: AtomicUsize = AtomicUsize::new(0);
static MOVING_WORST: Mutex<f64> = Mutex::new(0.0);

/// (samples solved, not converged, largest residual) since the last call; resets them.
pub fn moving_stats() -> (usize, usize, f64) {
    let worst = std::mem::take(&mut *MOVING_WORST.lock().expect("worst"));
    (
        MOVING_SOLVES.swap(0, Ordering::Relaxed),
        MOVING_FAILS.swap(0, Ordering::Relaxed),
        worst,
    )
}

/// The solver's tolerance on M / Ms and its iteration limit.
const MOVING_TOL: f64 = 1e-12;
const MOVING_ITER: usize = 400;

/// One sample of the moving model: the cell's M (in Ms) that the axes' states give when each
/// axis sees its share of (hx, hy) + a M, a = alpha Ms; commits the axes' states. `m0` is
/// the start (the previous sample's M). Newton for a < 0 (the map is monotone, its Jacobian
/// I + |a| sum w chi u u^T definite); fixed-point iteration from the previous state for a > 0
/// (it follows the branch the field moves along, an avalanche where a chi > 1).
fn moving_step(
    p: &Preisach,
    axes: &[[f64; 3]],
    stacks: &mut [Stack],
    trials: &mut [Trial],
    (hx, hy): (f64, f64),
    a: f64,
    m0: (f64, f64),
) -> (f64, f64) {
    let eval = |m: (f64, f64), trials: &mut [Trial]| -> (f64, f64) {
        let (fx, fy) = (hx + a * m.0, hy + a * m.1);
        let (mut ox, mut oy) = (0.0, 0.0);
        for ((st, ax), tr) in stacks.iter().zip(axes).zip(trials.iter_mut()) {
            *tr = st.trial(p, ax[0] * fx + ax[1] * fy);
            let mj = 2.0 * tr.up - 1.0;
            ox += ax[2] * ax[0] * mj;
            oy += ax[2] * ax[1] * mj;
        }
        (ox, oy)
    };
    let mut m = m0;
    let mut f = eval(m, trials);
    let mut res = (f.0 - m.0).abs().max((f.1 - m.1).abs());
    let mut done = res <= MOVING_TOL;
    let mut it = 0;
    while !done && it < MOVING_ITER {
        it += 1;
        let next = if a < 0.0 {
            // Newton on G = M - F(M), F's Jacobian from each axis's slope (a difference).
            let (fx, fy) = (hx + a * m.0, hy + a * m.1);
            let (mut j11, mut j12, mut j22) = (1.0, 0.0, 1.0);
            for (st, ax) in stacks.iter().zip(axes) {
                let x = ax[0] * fx + ax[1] * fy;
                let dx = 1e-6 * (x.abs() + p.h_max * 1e-3);
                let chi = 2.0 * (st.trial(p, x + dx).up - st.trial(p, x).up) / dx;
                let k = -a * ax[2] * chi;
                j11 += k * ax[0] * ax[0];
                j12 += k * ax[0] * ax[1];
                j22 += k * ax[1] * ax[1];
            }
            let (gx, gy) = (m.0 - f.0, m.1 - f.1);
            let det = j11 * j22 - j12 * j12;
            let mut step = ((j22 * gx - j12 * gy) / det, (j11 * gy - j12 * gx) / det);
            // Damped: halve while the residual grows.
            let mut cand = (m.0 - step.0, m.1 - step.1);
            let mut fc = eval(cand, trials);
            let mut rc = (fc.0 - cand.0).abs().max((fc.1 - cand.1).abs());
            let mut halvings = 0;
            while rc > res && halvings < 30 {
                step = (0.5 * step.0, 0.5 * step.1);
                cand = (m.0 - step.0, m.1 - step.1);
                fc = eval(cand, trials);
                rc = (fc.0 - cand.0).abs().max((fc.1 - cand.1).abs());
                halvings += 1;
            }
            f = fc;
            res = rc;
            cand
        } else {
            let cand = f;
            f = eval(cand, trials);
            res = (f.0 - cand.0).abs().max((f.1 - cand.1).abs());
            cand
        };
        m = next;
        done = res <= MOVING_TOL;
    }
    // The trials hold the states at m (the last evaluation).
    for (st, tr) in stacks.iter_mut().zip(trials.iter()) {
        st.commit(*tr);
    }
    MOVING_SOLVES.fetch_add(1, Ordering::Relaxed);
    if !done {
        MOVING_FAILS.fetch_add(1, Ordering::Relaxed);
        let mut w = MOVING_WORST.lock().expect("worst");
        if res > *w {
            *w = res;
        }
    }
    f
}

/// Tables built recently, by their parameters (a demag iteration records many times).
type Cache = Mutex<Vec<Arc<Preisach>>>;

fn cache() -> &'static Cache {
    static C: OnceLock<Cache> = OnceLock::new();
    C.get_or_init(|| Mutex::new(Vec::new()))
}

/// [`Preisach::new`], kept a while.
pub fn preisach(
    hc_median: f64,
    sigma_ln_hc: f64,
    sigma_hi: f64,
    h_max: f64,
    n: usize,
) -> Arc<Preisach> {
    let key = [
        hc_median.to_bits(),
        sigma_ln_hc.to_bits(),
        sigma_hi.to_bits(),
        h_max.to_bits(),
        n as u64,
    ];
    if let Some(p) = cache().lock().expect("cache").iter().find(|p| p.key == key) {
        return p.clone();
    }
    let p = Arc::new(Preisach::new(hc_median, sigma_ln_hc, sigma_hi, h_max, n));
    let mut c = cache().lock().expect("cache");
    c.push(p.clone());
    if c.len() > 4 {
        c.remove(0);
    }
    p
}

/// A ring head's face: gap, pole faces, and the potential's relaxation outside them (m).
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct Head {
    pub gap: f64,
    pub pole: f64,
    pub relax: f64,
}

/// ln(z - a) - ln(z - b) for z = x + iy, y > 0: (real, imaginary).
#[inline]
fn log_ratio(x: f64, y: f64, a: f64, b: f64) -> (f64, f64) {
    let (xa, xb) = (x - a, x - b);
    let re = 0.5 * ((xa * xa + y * y) / (xb * xb + y * y)).ln();
    let im = y.atan2(xa) - y.atan2(xb);
    (re, im)
}

/// (Hx, Hy) / Hg at (x, y), y > 0 (`varimu.devices.tape.head_field`): Hx - i Hy =
/// -(i / pi) times the sum of the surface potential's derivative's terms.
pub fn head_field(head: &Head, x: f64, y: f64) -> (f64, f64) {
    let g = head.gap;
    let e = g / 2.0 + head.pole;
    let (mut re, mut im) = log_ratio(x, y, -g / 2.0, g / 2.0);
    re = -re;
    im = -im;
    if head.relax <= 0.0 {
        for xe in [-e, e] {
            let (dx, r2) = (x - xe, (x - xe) * (x - xe) + y * y);
            re += (g / 2.0) * dx / r2;
            im += -(g / 2.0) * y / r2;
        }
    } else {
        let c = g / 2.0 / head.relax;
        for (a, b) in [(-e - head.relax, -e), (e, e + head.relax)] {
            let (r, i) = log_ratio(x, y, a, b);
            re += c * r;
            im += c * i;
        }
    }
    // w = -(i / pi) acc: Hx = Im(acc) / pi, Hy = -Im(w) = Re(acc) / pi.
    let pi = std::f64::consts::PI;
    (im / pi, re / pi)
}

/// One recording's inputs (layers x cells arrays row-major, layer major).
#[derive(Debug, Clone, Copy)]
pub struct Recording<'a> {
    pub preisach: &'a Preisach,
    pub head: Head,
    /// Each layer's height above the head (spacing + depth).
    pub heights: &'a [f64],
    /// The zone half-width per layer, or per layer and cell (layer major): the cell sees
    /// the head while within it.
    pub zones: &'a [f64],
    /// The tape position at the record gap at each sample (rising).
    pub s_rec: &'a [f64],
    /// The deep-gap field (A/m) at each sample.
    pub hg: &'a [f64],
    pub s_cells: &'a [f64],
    /// (cos, sin, weight) per easy-axis direction.
    pub axes: &'a [[f64; 3]],
    /// A steady field (H_x, H_y) on each cell through its pass (and after it, without
    /// `h_end`).
    pub h_static: Option<(&'a [f64], &'a [f64])>,
    /// The steady field each cell is left in after its pass, if not `h_static`.
    pub h_end: Option<(&'a [f64], &'a [f64])>,
    /// The head field's table step per layer as a fraction of the layer's height (0: the
    /// exact field at every sample; else [`FieldTable`], cubic between its points).
    pub table_step: f64,
    /// Threads to record on (0: every logical core). The cells are split into fixed
    /// chunks, so the result doesn't depend on it.
    pub threads: usize,
    /// Record on the GPU in f32 (`crates/tapegpu`; the `gpu` feature, else refused): within
    /// f32's rounding of this kernel, ~1e-6 of Ms (TAPE_SPEED_PLAN.md P5).
    pub gpu: bool,
}

/// One layer's head field (Hx, Hy) / Hg tabulated over its zone, read by Catmull-Rom
/// interpolation: the exact field costs three complex logarithms per cell and sample.
#[derive(Debug, Clone)]
pub struct FieldTable {
    x0: f64,
    inv_dx: f64,
    fx: Vec<f64>,
    fy: Vec<f64>,
}

impl FieldTable {
    pub fn new(head: &Head, y: f64, half_width: f64, dx: f64) -> Self {
        // Two points past each end, for the interpolation's taps.
        let n = (2.0 * half_width / dx).ceil() as usize + 5;
        let x0 = -half_width - 2.0 * dx;
        let (mut fx, mut fy) = (Vec::with_capacity(n), Vec::with_capacity(n));
        for i in 0..n {
            let (a, b) = head_field(head, x0 + i as f64 * dx, y);
            fx.push(a);
            fy.push(b);
        }
        FieldTable {
            x0,
            inv_dx: 1.0 / dx,
            fx,
            fy,
        }
    }

    #[inline]
    pub fn at(&self, x: f64) -> (f64, f64) {
        let u = (x - self.x0) * self.inv_dx;
        let i = (u.floor() as usize).clamp(1, self.fx.len() - 3);
        let w = catmull_rom(u - i as f64);
        let (mut a, mut b) = (0.0, 0.0);
        for (k, w) in w.iter().enumerate() {
            a += w * self.fx[i + k - 1];
            b += w * self.fy[i + k - 1];
        }
        (a, b)
    }
}

/// A task's result: its layer, first cell and (M_x, M_y) of its cells.
type Chunk = (usize, usize, Vec<f64>, Vec<f64>);

/// Cells per task of the parallel recording.
const CHUNK: usize = 256;

/// The remanent (M_x, M_y) / Ms per layer and cell (layer major), as
/// `varimu.devices.tape.record` computes it; on the GPU if `r.gpu` (an error there: no GPU,
/// or a build without the `gpu` feature).
pub fn record(r: &Recording<'_>) -> Result<(Vec<f64>, Vec<f64>), String> {
    if r.gpu {
        return record_gpu(r);
    }
    Ok(record_cpu(r, 0.0))
}

/// [`record`] with the moving model's mean field (an opt-in variant, TAPE_PLAN.md "Over-bias
/// options"): every hysteron of a cell sees the field plus `alpha` Ms M, M the cell's own
/// magnetization (`ms` A/m its saturation), followed forward sample by sample. On the CPU
/// only; `alpha` 0 is [`record`] itself.
pub fn record_mean_field(
    r: &Recording<'_>,
    alpha: f64,
    ms: f64,
) -> Result<(Vec<f64>, Vec<f64>), String> {
    if alpha == 0.0 {
        return record(r);
    }
    if r.gpu {
        return Err("tape: the moving model runs on the CPU only".into());
    }
    Ok(record_cpu(r, alpha * ms))
}

/// Each layer's head field table, if the recording tabulates it.
fn field_tables(r: &Recording<'_>) -> Vec<Option<FieldTable>> {
    let (layers, cells) = (r.heights.len(), r.s_cells.len());
    (0..layers)
        .map(|l| {
            (r.table_step > 0.0).then(|| {
                let y = r.heights[l];
                let widest = if r.zones.len() == layers {
                    r.zones[l]
                } else {
                    r.zones[l * cells..(l + 1) * cells]
                        .iter()
                        .fold(0.0, |a: f64, &z| a.max(z))
                };
                FieldTable::new(&r.head, y, widest, r.table_step * y)
            })
        })
        .collect()
}

/// The bias peaks [k0, k1) a cell sees: those within its zone (as [`cell`] finds them).
fn peak_range(r: &Recording<'_>, l: usize, ci: usize) -> (usize, usize) {
    let s = r.s_cells[ci];
    let xz = if r.zones.len() == r.heights.len() {
        r.zones[l]
    } else {
        r.zones[l * r.s_cells.len() + ci]
    };
    let k0 = r.s_rec.partition_point(|&v| v < s - xz);
    let k1 = r.s_rec.partition_point(|&v| v <= s + xz);
    (k0, k1)
}

#[cfg(not(feature = "gpu"))]
fn record_gpu(_: &Recording<'_>) -> Result<(Vec<f64>, Vec<f64>), String> {
    Err("tape: circuitsim was built without the GPU kernel (the `gpu` feature)".into())
}

#[cfg(feature = "gpu")]
fn record_gpu(r: &Recording<'_>) -> Result<(Vec<f64>, Vec<f64>), String> {
    let (layers, cells) = (r.heights.len(), r.s_cells.len());
    let tables = field_tables(r);
    let ft: Vec<tapegpu::FieldTable> = tables
        .iter()
        .flatten()
        .map(|t| tapegpu::FieldTable {
            x0: t.x0,
            inv_dx: t.inv_dx,
            fx: &t.fx,
            fy: &t.fy,
        })
        .collect();
    let mut ranges = Vec::with_capacity(layers * cells);
    for l in 0..layers {
        for ci in 0..cells {
            let (k0, k1) = peak_range(r, l, ci);
            ranges.push([k0 as u32, k1 as u32]);
        }
    }
    let p = r.preisach;
    tapegpu::record(&tapegpu::Block {
        tables: tapegpu::Tables {
            key: p.key,
            h_max: p.h_max,
            n: p.n,
            q: &p.q,
            d: &p.d,
        },
        head: [r.head.gap, r.head.pole, r.head.relax],
        heights: r.heights,
        field: (r.table_step > 0.0).then_some(&ft[..]),
        s_cells: r.s_cells,
        ranges: &ranges,
        s_rec: r.s_rec,
        hg: r.hg,
        axes: r.axes,
        h_static: r.h_static,
        h_end: r.h_end,
    })
}

/// [`record`] on the CPU, in f64.
fn record_cpu(r: &Recording<'_>, a: f64) -> (Vec<f64>, Vec<f64>) {
    let layers = r.heights.len();
    let cells = r.s_cells.len();
    let chunks = cells.div_ceil(CHUNK);
    let tasks = layers * chunks;
    let next = AtomicUsize::new(0);
    let out: Mutex<Vec<Chunk>> = Mutex::new(Vec::new());
    let threads = match r.threads {
        0 => std::thread::available_parallelism().map_or(1, |n| n.get()),
        n => n,
    }
    .clamp(1, 16);
    let tables = field_tables(r);
    let tables = &tables;
    std::thread::scope(|scope| {
        for _ in 0..threads {
            scope.spawn(|| {
                let mut corners = vec![Corner::new(0.0); r.axes.len()];
                let mut stacks = vec![Stack::default(); r.axes.len()];
                loop {
                    let t = next.fetch_add(1, Ordering::Relaxed);
                    if t >= tasks {
                        break;
                    }
                    let (l, c) = (t / chunks, t % chunks);
                    let c0 = c * CHUNK;
                    let c1 = (c0 + CHUNK).min(cells);
                    let mut mx = vec![0.0; c1 - c0];
                    let mut my = vec![0.0; c1 - c0];
                    for ci in c0..c1 {
                        let (x, y) = if a == 0.0 {
                            cell(r, l, ci, &mut corners, tables[l].as_ref())
                        } else {
                            cell_moving(r, l, ci, &mut stacks, tables[l].as_ref(), a)
                        };
                        mx[ci - c0] = x;
                        my[ci - c0] = y;
                    }
                    out.lock().expect("out").push((l, c0, mx, my));
                }
            });
        }
    });
    let mut mx = vec![0.0; layers * cells];
    let mut my = vec![0.0; layers * cells];
    for (l, c0, x, y) in out.into_inner().expect("out") {
        mx[l * cells + c0..l * cells + c0 + x.len()].copy_from_slice(&x);
        my[l * cells + c0..l * cells + c0 + y.len()].copy_from_slice(&y);
    }
    (mx, my)
}

/// One cell's (M_x, M_y) / Ms.
fn cell(
    r: &Recording<'_>,
    l: usize,
    ci: usize,
    corners: &mut [Corner],
    table: Option<&FieldTable>,
) -> (f64, f64) {
    let cells = r.s_cells.len();
    let s = r.s_cells[ci];
    let y = r.heights[l];
    let (k0, k1) = peak_range(r, l, ci);
    let at = |h: Option<(&[f64], &[f64])>| match h {
        Some((hx, hy)) => (hx[l * cells + ci], hy[l * cells + ci]),
        None => (0.0, 0.0),
    };
    let (hsx, hsy) = at(r.h_static);
    let (hex, hey) = if r.h_end.is_some() {
        at(r.h_end)
    } else {
        (hsx, hsy)
    };
    let p = r.preisach;
    for (cr, a) in corners.iter_mut().zip(r.axes) {
        *cr = Corner::new(p.h_max);
        // The field it is left in, after its pass (the history's last sample), and before
        // it the steady field alone as the cell leaves the head.
        cr.push(p, a[0] * hex + a[1] * hey);
        cr.push(p, a[0] * hsx + a[1] * hsy);
    }
    for j in (k0..k1.max(k0)).rev() {
        let x = s - r.s_rec[j];
        let (fx, fy) = match table {
            Some(t) => t.at(x),
            None => head_field(&r.head, x, y),
        };
        let (fx, fy) = (r.hg[j] * fx, r.hg[j] * fy);
        for (cr, a) in corners.iter_mut().zip(r.axes) {
            cr.push(p, a[0] * fx + a[1] * fy + (a[0] * hsx + a[1] * hsy));
        }
    }
    let (mut mx, mut my) = (0.0, 0.0);
    for (cr, a) in corners.iter().zip(r.axes) {
        let m = cr.finish(p);
        mx += a[2] * a[0] * m;
        my += a[2] * a[1] * m;
    }
    (mx, my)
}

/// (M_x, M_y) / Ms after a history of applied fields (h_x, h_y) under the moving model
/// (a = alpha Ms), from the erased state: the static loops' (Sound Talk Nos. 20 / 22) with
/// the mean field on. The reference is `varimu.tape_variants.along_x`.
pub fn moving_history(p: &Preisach, axes: &[[f64; 3]], h: &[(f64, f64)], a: f64) -> (f64, f64) {
    let mut stacks = vec![Stack::default(); axes.len()];
    let mut trials = vec![
        Trial {
            x: 0.0,
            up: 0.0,
            keep: 0,
            max: false,
        };
        axes.len()
    ];
    let mut m = (0.0, 0.0);
    for &x in h {
        m = moving_step(p, axes, &mut stacks, &mut trials, x, a, m);
    }
    m
}

/// One cell's (M_x, M_y) / Ms under the moving model (a = alpha Ms): the history forward,
/// the pass's samples, the steady field alone, then the field it is left in (as [`cell`]
/// reads them backward).
fn cell_moving(
    r: &Recording<'_>,
    l: usize,
    ci: usize,
    stacks: &mut [Stack],
    table: Option<&FieldTable>,
    a: f64,
) -> (f64, f64) {
    let cells = r.s_cells.len();
    let s = r.s_cells[ci];
    let y = r.heights[l];
    let (k0, k1) = peak_range(r, l, ci);
    let at = |h: Option<(&[f64], &[f64])>| match h {
        Some((hx, hy)) => (hx[l * cells + ci], hy[l * cells + ci]),
        None => (0.0, 0.0),
    };
    let (hsx, hsy) = at(r.h_static);
    let (hex, hey) = if r.h_end.is_some() {
        at(r.h_end)
    } else {
        (hsx, hsy)
    };
    let p = r.preisach;
    for st in stacks.iter_mut() {
        st.clear();
    }
    let mut trials = vec![
        Trial {
            x: 0.0,
            up: 0.0,
            keep: 0,
            max: false,
        };
        r.axes.len()
    ];
    let mut m = (0.0, 0.0);
    for j in k0..k1.max(k0) {
        let x = s - r.s_rec[j];
        let (fx, fy) = match table {
            Some(t) => t.at(x),
            None => head_field(&r.head, x, y),
        };
        let h = (r.hg[j] * fx + hsx, r.hg[j] * fy + hsy);
        m = moving_step(p, r.axes, stacks, &mut trials, h, a, m);
    }
    m = moving_step(p, r.axes, stacks, &mut trials, (hsx, hsy), a, m);
    moving_step(p, r.axes, stacks, &mut trials, (hex, hey), a, m)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn ensemble() -> Preisach {
        let oe = 1000.0 / (4.0 * std::f64::consts::PI);
        Preisach::new(293.0 * oe, 0.33, 46.0 * oe, 2000.0 * oe, 256)
    }

    #[test]
    fn erased_is_zero_and_saturation_is_one() {
        let p = ensemble();
        assert!(p.state_after(&[0.0]).abs() < 1e-12);
        assert!((p.state_after(&[1e9]) - 1.0).abs() < 1e-9);
        assert!((p.state_after(&[-1e9]) + 1.0).abs() < 1e-9);
    }

    #[test]
    fn only_extrema_matter_and_the_model_is_odd() {
        let p = ensemble();
        let h: Vec<f64> = (0..200)
            .map(|k| 4e4 * (k as f64 * 0.37).sin() * (1.0 - k as f64 / 250.0))
            .collect();
        let dense = p.state_after(&h);
        let mut turns = vec![h[0]];
        for k in 1..h.len() - 1 {
            if (h[k] - h[k - 1]) * (h[k + 1] - h[k]) < 0.0 {
                turns.push(h[k]);
            }
        }
        turns.push(h[h.len() - 1]);
        // A dense run's records telescope: equal within rounding.
        assert!((dense - p.state_after(&turns)).abs() < 1e-12);
        let neg: Vec<f64> = h.iter().map(|x| -x).collect();
        assert!((p.state_after(&neg) + dense).abs() < 1e-6);
    }

    #[test]
    fn the_head_field_over_the_gap_is_karlqvists() {
        let head = Head {
            gap: 6.35e-6,
            pole: 2e-3,
            relax: 0.5e-3,
        };
        let (hx, hy) = head_field(&head, 0.0, 1e-6);
        let want = 2.0 / std::f64::consts::PI * (3.175f64).atan();
        // The finite poles' share at the centre is ~1e-3 of the gap's.
        assert!((hx - want).abs() < 2e-3, "{hx} vs {want}");
        assert!(hy.abs() < 1e-12);
        let (_, a) = head_field(&head, 10e-6, 1e-6);
        let (_, b) = head_field(&head, -10e-6, 1e-6);
        assert!(a * b < 0.0);
    }
}
