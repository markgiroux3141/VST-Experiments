//! Event kernels for gas-tube strikes: technique K (HYBRID_PHYSICS_PLAN.md H3, "K's
//! design"), the port of `varimu/devices/thyratron_events.py`'s run time (its docstrings
//! have the method; the arithmetic here is the same, in the same order).
//!
//! A [`ThyratronEvents`] element carries its unit's tables over (the grid, the ramp's
//! log slope): the strike voltage, the dead time, the latched points and the anode
//! current's pulse from each strike at the reference rate. For a run's step `h`
//! (`m = ref_rate h` reference samples, a whole number) [`Tables::new`] band-limits each
//! pulse by a minimum-phase low-pass ([`minphase_lowpass`]) and integrates it over each
//! step at `m + 1` offsets ([`step_charges`]). [`Run::sense`] takes the senses after each
//! sample and gives the current held a -> k over the next step: the transient injects it
//! as a DK current column (`Mna::events`), so the charge per step is exact.

use std::f64::consts::PI;

use rustfft::FftPlanner;
use rustfft::num_complex::Complex64;

use crate::ir::ThyratronEvents;

/// The kernel's stopband (dB), from 0.75 of the step rate (what folds into its passband).
pub const KERNEL_ATTEN_DB: f64 = 100.0;

/// `scipy.signal.kaiserord`: taps and beta for a ripple (dB) and a transition width (a
/// fraction of the Nyquist frequency).
pub fn kaiserord(ripple_db: f64, width: f64) -> (usize, f64) {
    let a = ripple_db.abs();
    let beta = if a > 50.0 {
        0.1102 * (a - 8.7)
    } else if a > 21.0 {
        0.5842 * (a - 21.0).powf(0.4) + 0.07886 * (a - 21.0)
    } else {
        0.0
    };
    let taps = (a - 7.95) / 2.285 / (PI * width) + 1.0;
    (taps.ceil() as usize, beta)
}

/// The modified Bessel function I0 (its power series).
fn i0(x: f64) -> f64 {
    let q = 0.25 * x * x;
    let (mut term, mut sum) = (1.0, 1.0);
    for k in 1..500 {
        term *= q / ((k * k) as f64);
        sum += term;
        if term < 1e-17 * sum {
            break;
        }
    }
    sum
}

/// numpy's sinc: sin(pi x) / (pi x).
fn sinc(x: f64) -> f64 {
    let y = PI * if x == 0.0 { 1e-20 } else { x };
    y.sin() / y
}

/// A minimum-phase low-pass at `m` steps per sample: the passband to a quarter of the
/// sample rate, the stopband from three quarters, `atten_db` down; taps sum to 1.
/// Designed linear-phase (`scipy.signal.firwin` with a Kaiser window, 3 dB of margin) and
/// made minimum-phase by the real cepstrum (the same magnitude, causal, its energy first).
pub fn minphase_lowpass(m: usize, atten_db: f64) -> Vec<f64> {
    let rate = m as f64;
    let (n, beta) = kaiserord(atten_db + 3.0, 0.5 / (rate / 2.0));
    let n = n | 1;
    // firwin(n, 0.5, window=("kaiser", beta), fs=rate): the cutoff over Nyquist
    let cutoff = 0.5 / (rate / 2.0);
    let alpha = 0.5 * (n - 1) as f64;
    let i0b = i0(beta);
    let mut h: Vec<f64> = (0..n)
        .map(|i| {
            let t = i as f64 - alpha;
            let win = i0(beta * (1.0 - (t / alpha).powi(2)).sqrt()) / i0b;
            cutoff * sinc(cutoff * t) * win
        })
        .collect();
    let s: f64 = h.iter().sum();
    h.iter_mut().for_each(|x| *x /= s);
    // the real cepstrum, folded onto positive quefrencies
    let nfft = (n * 32).next_power_of_two();
    let mut planner = FftPlanner::<f64>::new();
    let fwd = planner.plan_fft_forward(nfft);
    let inv = planner.plan_fft_inverse(nfft);
    let mut buf: Vec<Complex64> = (0..nfft)
        .map(|i| Complex64::new(if i < n { h[i] } else { 0.0 }, 0.0))
        .collect();
    fwd.process(&mut buf);
    for z in &mut buf {
        *z = Complex64::new(z.norm().max(1e-12).ln(), 0.0);
    }
    inv.process(&mut buf);
    let scale = 1.0 / nfft as f64;
    let c: Vec<f64> = buf.iter().map(|z| z.re * scale).collect();
    let half = nfft / 2;
    for (i, z) in buf.iter_mut().enumerate() {
        let f = if i == 0 || i == half {
            c[i]
        } else if i < half {
            2.0 * c[i]
        } else {
            0.0
        };
        *z = Complex64::new(f, 0.0);
    }
    fwd.process(&mut buf);
    for z in &mut buf {
        *z = z.exp();
    }
    inv.process(&mut buf);
    let hm: Vec<f64> = buf[..n].iter().map(|z| z.re * scale).collect();
    let s: f64 = hm.iter().sum();
    hm.iter().map(|x| x / s).collect()
}

/// A pulse (amperes at the reference rate, from the strike) band-limited by `h` (at the
/// same rate) and integrated over each step of `m` reference samples, at every offset
/// `j / m` of a step (j = 0 ..= m): rows of `steps` charges (coulombs).
pub fn step_charges(pulse: &[f64], h: &[f64], m: usize, ref_rate_hz: f64) -> Vec<Vec<f64>> {
    let len = pulse.len() + h.len() - 1;
    let mut g = vec![0.0; len];
    for (i, &p) in pulse.iter().enumerate() {
        for (j, &k) in h.iter().enumerate() {
            g[i + j] += p * k;
        }
    }
    g.iter_mut().for_each(|x| *x /= ref_rate_hz);
    let steps = (len + m).div_ceil(m);
    (0..=m)
        .map(|j| {
            let mut row = vec![0.0; steps];
            for (i, &x) in g.iter().enumerate() {
                row[(i + j) / m] += x;
            }
            row
        })
        .collect()
}

/// The margin at the last three samples (`m[2]` now): the first zero of the quadratic
/// through them in the next step, as a fraction of it (0, 1]; `None` if there is none. A
/// margin already >= 0 (a crossing the extrapolation missed) starts at once: 0.
pub fn predict_crossing(m: [f64; 3]) -> Option<f64> {
    let [m0, m1, m2] = m;
    if m2 >= 0.0 {
        return Some(0.0);
    }
    // m(x) = m2 + b x + a x^2 through (-2, m0), (-1, m1), (0, m2)
    let a = 0.5 * (m0 - 2.0 * m1 + m2);
    let b = 0.5 * (m0 - 4.0 * m1 + 3.0 * m2);
    let mut roots = [f64::NAN; 2];
    if a.abs() <= 1e-12 * (b.abs() + m2.abs()) {
        if b != 0.0 {
            roots[0] = -m2 / b;
        }
    } else {
        let disc = b * b - 4.0 * a * m2;
        if disc < 0.0 {
            return None;
        }
        let r = disc.sqrt();
        // the numerically stable pair
        let qq = -0.5 * (b + r.copysign(b));
        if qq != 0.0 {
            roots = [qq / a, m2 / qq];
        }
    }
    roots
        .into_iter()
        .filter(|x| *x > 0.0 && *x <= 1.0)
        .reduce(f64::min)
}

/// The cell of an ascending grid holding x (clamped to it) and x's fraction in it.
fn ix(grid: &[f64], x: f64) -> (usize, f64) {
    let x = x.max(grid[0]).min(grid[grid.len() - 1]);
    let i = (grid.partition_point(|&g| g <= x) - 1).min(grid.len() - 2);
    (i, (x - grid[i]) / (grid[i + 1] - grid[i]))
}

/// The tables at one condition ([`Tables::lookup`]): V_s, the dead time, the charges
/// (`(m + 1) x steps`, row-major): the anode's band-limited and raw, the grid's
/// band-limited; or latched (no event).
#[derive(Debug, Clone, Default)]
pub struct Lookup {
    pub v_s: f64,
    pub dead_s: f64,
    pub latched: bool,
    pub q: Vec<f64>,
    pub q_raw: Vec<f64>,
    pub q_grid: Vec<f64>,
    /// The pulse's centroid, reference samples from the strike.
    pub centroid: f64,
}

/// Row j (-1 ..= m + 1) of an `(m + 1) x steps` charge table at step k: beyond the ends, the
/// end rows a whole step on, the charge kept (`thyratron_events.phase_row`).
fn phase_at(q: &[f64], j: isize, k: usize, m: usize, steps: usize) -> f64 {
    if j < 0 {
        let r = (m - 1) * steps;
        if k == 0 {
            q[r] + q[r + 1]
        } else if k + 1 < steps {
            q[r + k + 1]
        } else {
            0.0
        }
    } else if j as usize > m {
        let r = steps;
        if k == 0 {
            0.0
        } else if k + 1 == steps {
            q[r + k - 1] + q[r + k]
        } else {
            q[r + k - 1]
        }
    } else {
        q[j as usize * steps + k]
    }
}

/// The charges at phase row `j0 + a` (0 <= a < 1), step k: Lagrange through rows j0 - 1 ..=
/// j0 + 2 (`thyratron_events.cubic_phase`).
fn cubic_phase(q: &[f64], j0: usize, a: f64, k: usize, m: usize, steps: usize) -> f64 {
    let w = [
        -a * (a - 1.0) * (a - 2.0) / 6.0,
        (a + 1.0) * (a - 1.0) * (a - 2.0) / 2.0,
        -(a + 1.0) * a * (a - 2.0) / 2.0,
        (a + 1.0) * a * (a - 1.0) / 6.0,
    ];
    let j = j0 as isize;
    w[0] * phase_at(q, j - 1, k, m, steps)
        + w[1] * phase_at(q, j, k, m, steps)
        + w[2] * phase_at(q, j + 1, k, m, steps)
        + w[3] * phase_at(q, j + 2, k, m, steps)
}

/// A condition's four corners on the grid (point, weight), V_s over them, and the weights
/// of the latched corners and of the others.
#[derive(Debug, Clone, Copy)]
pub struct Corners {
    pub points: [(usize, f64); 4],
    pub v_s: f64,
    pub w_latched: f64,
    pub w_live: f64,
}

impl Corners {
    pub fn latched(&self) -> bool {
        self.w_latched >= 0.5
    }
}

/// A point's step charges: `m + 1` rows (offsets) of `steps`.
type Charges = Vec<Vec<f64>>;

/// A unit's tables for a step of `m` reference samples.
#[derive(Debug, Clone)]
pub struct Tables {
    v_g: Vec<f64>,
    log_slope: Vec<f64>,
    /// Per point (v_g major): V_s, dead time, latched.
    v_s: Vec<f64>,
    dead_s: Vec<f64>,
    latched: Vec<bool>,
    /// Per point, the pulse's centroid in reference samples (0 where latched).
    centroid: Vec<f64>,
    pub m: usize,
    pub steps: usize,
    /// Per point, `(m + 1) x steps` charges (zeros where latched).
    q: Vec<Vec<f64>>,
    q_raw: Vec<Vec<f64>>,
    q_grid: Vec<Vec<f64>>,
}

impl Tables {
    /// The element's tables for a step `h`: `ref_rate_hz h` must be a whole number.
    pub fn new(el: &ThyratronEvents, h: f64) -> Result<Tables, String> {
        let mf = el.ref_rate_hz * h;
        let m = mf.round() as usize;
        if m < 1 || (mf - m as f64).abs() > 1e-9 * m as f64 {
            return Err(format!(
                "{}: the step {h:e} s isn't a whole number of its tables' reference samples \
                 ({} Hz)",
                el.name, el.ref_rate_hz
            ));
        }
        let kernel = minphase_lowpass(m, KERNEL_ATTEN_DB);
        let rate = el.ref_rate_hz;
        let pts: Vec<Option<[Charges; 3]>> = el
            .pulses_a
            .iter()
            .flatten()
            .zip(el.grid_pulses_a.iter().flatten())
            .map(|(p, g)| {
                (!p.is_empty()).then(|| {
                    [
                        step_charges(p, &kernel, m, rate),
                        step_charges(p, &[1.0], m, rate),
                        step_charges(g, &kernel, m, rate),
                    ]
                })
            })
            .collect();
        let steps = pts
            .iter()
            .flatten()
            .flat_map(|c| c.iter().map(|x| x[0].len()))
            .max()
            .expect("validated: a point not latched");
        let flat = |rows: &[Vec<f64>]| {
            let mut out = vec![0.0; (m + 1) * steps];
            for (j, row) in rows.iter().enumerate() {
                out[j * steps..j * steps + row.len()].copy_from_slice(row);
            }
            out
        };
        let zeros = || vec![0.0; (m + 1) * steps];
        let (mut q, mut q_raw, mut q_grid) = (Vec::new(), Vec::new(), Vec::new());
        for p in &pts {
            match p {
                Some([a, r, g]) => {
                    q.push(flat(a));
                    q_raw.push(flat(r));
                    q_grid.push(flat(g));
                }
                None => {
                    q.push(zeros());
                    q_raw.push(zeros());
                    q_grid.push(zeros());
                }
            }
        }
        Ok(Tables {
            v_g: el.v_g_v.clone(),
            log_slope: el.log_slope.clone(),
            v_s: el.v_s_v.iter().flatten().copied().collect(),
            dead_s: el.dead_s.iter().flatten().copied().collect(),
            centroid: el
                .pulses_a
                .iter()
                .flatten()
                .map(|p| {
                    if p.is_empty() {
                        return 0.0;
                    }
                    let (mut num, mut den) = (0.0, 0.0);
                    for (n, x) in p.iter().enumerate() {
                        num += n as f64 * x;
                        den += x;
                    }
                    num / den
                })
                .collect(),
            latched: el.latched.iter().flatten().copied().collect(),
            m,
            steps,
            q,
            q_raw,
            q_grid,
        })
    }

    /// The condition on the grid: bilinear in (v_g, log slope), clamped to it, and V_s
    /// there ([`Tables::lookup`]'s first half: what the margin needs every sample).
    pub fn corners(&self, v_g: f64, slope_v_s: f64) -> Corners {
        let ns = self.log_slope.len();
        let (i, a) = ix(&self.v_g, v_g);
        let (j, b) = ix(&self.log_slope, slope_v_s.max(1e-30).ln());
        let points = [
            (i * ns + j, (1.0 - a) * (1.0 - b)),
            ((i + 1) * ns + j, a * (1.0 - b)),
            (i * ns + j + 1, (1.0 - a) * b),
            ((i + 1) * ns + j + 1, a * b),
        ];
        let (mut v_s, mut w_latched, mut w_live) = (0.0, 0.0, 0.0);
        for &(p, w) in &points {
            v_s += w * self.v_s[p];
            if self.latched[p] {
                w_latched += w;
            } else {
                w_live += w;
            }
        }
        Corners {
            points,
            v_s,
            w_latched,
            w_live,
        }
    }

    /// Bilinear in (v_g, log slope), clamped to the grid. V_s over the four corners; the
    /// charges and the dead time over the corners not latched, their weights renormalized;
    /// latched when the latched corners weigh half or more.
    pub fn lookup(&self, v_g: f64, slope_v_s: f64, out: &mut Lookup) {
        self.lookup_at(&self.corners(v_g, slope_v_s), out);
    }

    /// [`Tables::lookup`] at known corners.
    pub fn lookup_at(&self, c: &Corners, out: &mut Lookup) {
        out.v_s = c.v_s;
        out.latched = c.latched();
        if out.latched {
            out.dead_s = 0.0;
            return;
        }
        let (corners, w_latched, w_live) = (&c.points, c.w_latched, c.w_live);
        let len = (self.m + 1) * self.steps;
        out.q.clear();
        out.q.resize(len, 0.0);
        out.q_raw.clear();
        out.q_raw.resize(len, 0.0);
        out.q_grid.clear();
        out.q_grid.resize(len, 0.0);
        let (mut dead, mut centroid) = (0.0, 0.0);
        for &(p, w) in corners {
            if self.latched[p] {
                continue;
            }
            let w = if w_latched > 0.0 { w / w_live } else { w };
            dead += w * self.dead_s[p];
            centroid += w * self.centroid[p];
            for (o, x) in out.q.iter_mut().zip(&self.q[p]) {
                *o += w * x;
            }
            for (o, x) in out.q_raw.iter_mut().zip(&self.q_raw[p]) {
                *o += w * x;
            }
            for (o, x) in out.q_grid.iter_mut().zip(&self.q_grid[p]) {
                *o += w * x;
            }
        }
        out.dead_s = dead;
        out.centroid = centroid;
    }
}

/// Counts of a run's strikes.
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub struct Counts {
    /// Strikes fired.
    pub events: u64,
    /// Strikes the prediction missed (started at the next step).
    pub late: u64,
    /// Latched conditions met (no event played: K doesn't play the held arc).
    pub latched: u64,
}

/// K's run time on one unit (`thyratron_events.Events`): the senses after each sample in,
/// the currents held over the next step out: a -> k, into the grid (g -> k), and the
/// charging network's deficit from ground into the anode ([`Run::deficit`]).
#[derive(Debug, Clone)]
pub struct Run {
    pub element: ThyratronEvents,
    tables: Tables,
    h: f64,
    pending: Vec<f64>,
    pending_raw: Vec<f64>,
    pending_grid: Vec<f64>,
    pending_comp: Vec<f64>,
    hist: [f64; 3],
    n: u64,
    i_held: f64,
    i_grid: f64,
    i_comp: f64,
    lag: f64,
    /// In samples.
    busy_until: f64,
    in_latch: bool,
    pub counts: Counts,
    lk: Lookup,
    /// Scratch: an event's anode charges, band-limited and raw, and the deficit's.
    qq: Vec<f64>,
    rr: Vec<f64>,
    cc: Vec<f64>,
}

impl Run {
    pub fn new(el: &ThyratronEvents, h: f64) -> Result<Run, String> {
        let tables = Tables::new(el, h)?;
        let n = tables.steps + 2;
        Ok(Run {
            element: el.clone(),
            tables,
            h,
            pending: vec![0.0; n],
            pending_raw: vec![0.0; n],
            pending_grid: vec![0.0; n],
            pending_comp: vec![0.0; n],
            hist: [0.0; 3],
            n: 0,
            i_held: 0.0,
            i_grid: 0.0,
            i_comp: 0.0,
            lag: 0.0,
            busy_until: 0.0,
            in_latch: false,
            counts: Counts::default(),
            lk: Lookup::default(),
            qq: Vec::new(),
            rr: Vec::new(),
            cc: Vec::new(),
        })
    }

    /// What the charging network doesn't deliver because of the kernel's delay, as charges
    /// per step (`cc`) to deliver instead, from ground into the anode
    /// (`thyratron_events.Events._deficit`): the band-limited capacitor sits above the
    /// physical one for ~2 samples after each strike, so a charging network whose current
    /// falls with the capacitor's voltage (conductance G) delivers less meanwhile, G (v -
    /// v_phys) summed over the event. G is measured from the ramp's curvature (G = -C dS/dv
    /// over the last three samples, none below 0); the charge goes in the event's
    /// band-limited shape, from the network's side (the tube's current reaches the cathode
    /// whole: a self-biased cathode sits on it).
    /// The lag is the band-limited charges' centroid less the pulse's own (the strike's
    /// phase `phi` plus `centroid / m`, less a held current's half step on average).
    fn deficit(&mut self, phi: f64, centroid: f64) {
        let [h0, h1, h2] = self.hist;
        let (c, h, m) = (self.element.c_f, self.h, self.tables.m);
        let mut g = 0.0;
        if h2 > h0 {
            g = (-c * 2.0 * (h2 - 2.0 * h1 + h0) / (h * (h2 - h0))).max(0.0);
        }
        let (mut kq, mut total) = (0.0, 0.0);
        for (k, q) in self.qq.iter().enumerate() {
            kq += k as f64 * q;
            total += q;
        }
        self.cc.clear();
        if g == 0.0 || total <= 0.0 {
            self.cc.resize(self.qq.len(), 0.0);
            return;
        }
        let acc = kq - total * (phi + centroid / m as f64 - (m - 1) as f64 / (2 * m) as f64);
        let f = g * h / c * acc / total;
        self.cc.extend(self.qq.iter().map(|q| q * f));
    }

    /// The current held a -> k over the step in progress.
    pub fn current(&self) -> f64 {
        self.i_held
    }

    /// The current held into the grid (g -> k) over the step in progress.
    pub fn grid_current(&self) -> f64 {
        self.i_grid
    }

    /// The charging network's deficit held from ground into the anode over the step in
    /// progress.
    pub fn comp_current(&self) -> f64 {
        self.i_comp
    }

    /// Sample n's senses (v_ak, v_gk); the current held over the step to n + 1.
    pub fn sense(&mut self, v_ak: f64, v_gk: f64) -> f64 {
        let e = &self.element;
        let (h, m) = (self.h, self.tables.m);
        let v_phys = v_ak + e.r_s_ohm * (self.i_held - self.i_comp) + self.lag / e.c_f;
        self.hist = [self.hist[1], self.hist[2], v_phys];
        let n = self.n;
        let mut fired = false;
        if n >= 2 && n as f64 >= self.busy_until {
            let s = (self.hist[2] - self.hist[1]) / h;
            if s > 0.0 {
                let vg = v_gk - e.r_g_ohm * e.c_ga_f * s;
                let mut c = self.tables.corners(vg, s);
                let [h0, h1, h2] = self.hist;
                let mut phi = predict_crossing([h0 - c.v_s, h1 - c.v_s, h2 - c.v_s]);
                if let Some(p) = phi.filter(|&p| p > 0.0) {
                    // the slope at the crossing, from the same quadratic (the last
                    // interval's sits up to a step before it, by the phase: jitter)
                    let qa = 0.5 * (h0 - 2.0 * h1 + h2);
                    let qb = 0.5 * (h0 - 4.0 * h1 + 3.0 * h2);
                    let s2 = (qb + 2.0 * qa * p) / h;
                    if s2 > 0.0 {
                        let vg2 = v_gk - e.r_g_ohm * e.c_ga_f * s2;
                        let c2 = self.tables.corners(vg2, s2);
                        if let Some(p2) = predict_crossing([h0 - c2.v_s, h1 - c2.v_s, h2 - c2.v_s])
                        {
                            (c, phi) = (c2, Some(p2));
                        }
                    }
                }
                if let Some(phi) = phi {
                    fired = true;
                    if c.latched() {
                        if !self.in_latch {
                            self.counts.latched += 1;
                        }
                        self.in_latch = true;
                    } else {
                        self.tables.lookup_at(&c, &mut self.lk);
                        let lk = &self.lk;
                        self.in_latch = false;
                        self.counts.events += 1;
                        self.counts.late += u64::from(phi == 0.0);
                        let j = phi * m as f64;
                        let j0 = (j as usize).min(m - 1);
                        let a = j - j0 as f64;
                        let steps = self.tables.steps;
                        let (r0, r1) = (j0 * steps, (j0 + 1) * steps);
                        self.qq.clear();
                        self.rr.clear();
                        for k in 0..steps {
                            self.qq.push(cubic_phase(&lk.q, j0, a, k, m, steps));
                            self.rr
                                .push((1.0 - a) * lk.q_raw[r0 + k] + a * lk.q_raw[r1 + k]);
                            self.pending_grid[k] += cubic_phase(&lk.q_grid, j0, a, k, m, steps);
                        }
                        let (dead_s, centroid) = (lk.dead_s, lk.centroid);
                        self.deficit(phi, centroid);
                        for k in 0..steps {
                            self.pending[k] += self.qq[k];
                            self.pending_raw[k] += self.rr[k];
                            self.pending_comp[k] += self.cc[k];
                        }
                        self.busy_until = n as f64 + phi + dead_s / h;
                    }
                }
            }
        }
        if !fired {
            self.in_latch = false;
        }
        self.i_held = self.pending[0] / h;
        self.i_grid = self.pending_grid[0] / h;
        self.i_comp = self.pending_comp[0] / h;
        self.lag += self.pending[0] - self.pending_raw[0];
        for v in [
            &mut self.pending,
            &mut self.pending_raw,
            &mut self.pending_grid,
            &mut self.pending_comp,
        ] {
            v.copy_within(1.., 0);
            *v.last_mut().expect("steps + 2") = 0.0;
        }
        self.n = n + 1;
        self.i_held
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn kaiserord_is_scipys() {
        // scipy.signal.kaiserord(103, 1 / 16): (425, 10.39186)
        let (n, beta) = kaiserord(103.0, 0.5 / 16.0);
        assert_eq!(n, 425);
        assert!((beta - 0.1102 * (103.0 - 8.7)).abs() < 1e-15);
    }

    #[test]
    fn i0_matches_known_values() {
        // I0(1) = 1.2660658777520082, I0(10) = 2815.716628466254
        assert!((i0(1.0) / 1.266_065_877_752_008_2 - 1.0).abs() < 1e-15);
        assert!((i0(10.0) / 2_815.716_628_466_254 - 1.0).abs() < 1e-14);
    }

    #[test]
    fn crossings() {
        let q = |x0: f64| move |x: f64| (x - x0) * (x + 4.0) / 4.0;
        for x0 in [0.05, 0.3, 0.77, 1.0] {
            let m = q(x0);
            let phi = predict_crossing([m(-2.0), m(-1.0), m(0.0)]).expect("a crossing");
            assert!((phi - x0).abs() < 1e-12);
        }
        assert_eq!(predict_crossing([-3.0, -2.5, -2.0]), None);
        assert_eq!(predict_crossing([-2.0, -1.0, 0.5]), Some(0.0));
    }
}
