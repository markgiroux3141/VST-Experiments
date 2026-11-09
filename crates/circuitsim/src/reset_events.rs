//! Event kernels for a relaxation oscillator's reset and a comparator's edge: technique K
//! beyond the gas tube, the port of `varimu/devices/reset_events.py`'s run time (its
//! docstrings have the method; the arithmetic here is the same, in the same order). First
//! user: the Minimoog's oscillator (docs/MINIMOOG_PLAN.md MM3).
//!
//! A [`ResetEvents`] element senses a ramp and, at a predicted crossing of its trigger level,
//! injects the reset's band-limited charges from `src` into `dst` ([`ResetRun`]); an
//! [`EdgeEvents`] element senses a comparator's input difference and moves the output
//! current it holds through a band-limited step at each predicted flip ([`EdgeRun`]). The
//! transient injects their currents as DK current columns, as the thyratron's
//! ([`crate::events`], whose band-limiting, crossing prediction and phase interpolation these
//! reuse).

use crate::events::{
    KERNEL_ATTEN_DB, cubic_phase, ix, minphase_lowpass, predict_crossing, step_charges,
};
use crate::ir::{EdgeEvents, ResetEvents};

/// Samples the crossing prediction uses: no event's history spans an earlier event
/// (`reset_events.HISTORY`).
pub const HISTORY: f64 = 3.0;

/// The step a table's reference rate makes of `h`: a whole number of reference samples.
fn steps_of(name: &str, ref_rate_hz: f64, h: f64) -> Result<usize, String> {
    let mf = ref_rate_hz * h;
    let m = mf.round() as usize;
    if m < 1 || (mf - m as f64).abs() > 1e-9 * m as f64 {
        return Err(format!(
            "{name}: the step {h:e} s isn't a whole number of its tables' reference samples \
             ({ref_rate_hz} Hz)"
        ));
    }
    Ok(m)
}

/// Counts of a run's events.
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub struct Counts {
    /// Events fired.
    pub events: u64,
    /// Events the prediction missed (started at the next step).
    pub late: u64,
}

/// A reset's tables for a step of `m` reference samples.
#[derive(Debug, Clone)]
pub struct ResetTables {
    log_slope: Vec<f64>,
    v_t: Vec<f64>,
    dead_s: Vec<f64>,
    g_s: Vec<f64>,
    /// Per point, the pulse's centroid in reference samples.
    centroid: Vec<f64>,
    pub m: usize,
    pub steps: usize,
    /// Per point, `(m + 1) x steps` band-limited and raw charges.
    q: Vec<Vec<f64>>,
    q_raw: Vec<Vec<f64>>,
}

impl ResetTables {
    pub fn new(el: &ResetEvents, h: f64) -> Result<ResetTables, String> {
        let m = steps_of(&el.name, el.ref_rate_hz, h)?;
        let kernel = minphase_lowpass(m, KERNEL_ATTEN_DB);
        let rate = el.ref_rate_hz;
        let pts: Vec<[Vec<Vec<f64>>; 2]> = el
            .pulses_a
            .iter()
            .map(|p| {
                [
                    step_charges(p, &kernel, m, rate),
                    step_charges(p, &[1.0], m, rate),
                ]
            })
            .collect();
        let steps = pts
            .iter()
            .flat_map(|c| c.iter().map(|x| x[0].len()))
            .max()
            .expect("validated: a point");
        let flat = |rows: &[Vec<f64>]| {
            let mut out = vec![0.0; (m + 1) * steps];
            for (j, row) in rows.iter().enumerate() {
                out[j * steps..j * steps + row.len()].copy_from_slice(row);
            }
            out
        };
        Ok(ResetTables {
            log_slope: el.log_slope.clone(),
            v_t: el.v_t_v.clone(),
            dead_s: el.dead_s.clone(),
            g_s: el.g_s.clone(),
            centroid: el
                .pulses_a
                .iter()
                .map(|p| {
                    let (mut num, mut den) = (0.0, 0.0);
                    for (n, x) in p.iter().enumerate() {
                        num += n as f64 * x;
                        den += x;
                    }
                    num / den
                })
                .collect(),
            m,
            steps,
            q: pts.iter().map(|[a, _]| flat(a)).collect(),
            q_raw: pts.iter().map(|[_, r]| flat(r)).collect(),
        })
    }

    /// The trigger level at slope `s` (V/s), linear in log slope, clamped to the grid.
    pub fn v_t_at(&self, s: f64) -> f64 {
        let (i, a) = ix(&self.log_slope, s.max(1e-30).ln());
        (1.0 - a) * self.v_t[i] + a * self.v_t[i + 1]
    }
}

/// K's run time on a reset unit (`reset_events.ResetRun`): the sensed ramp after each sample
/// in, the current held from src into dst over the next step out.
#[derive(Debug, Clone)]
pub struct ResetRun {
    pub element: ResetEvents,
    tables: ResetTables,
    h: f64,
    pending: Vec<f64>,
    pending_raw: Vec<f64>,
    pending_comp: Vec<f64>,
    hist: [f64; 3],
    n: u64,
    i_held: f64,
    i_comp: f64,
    lag: f64,
    busy_until: f64,
    pub counts: Counts,
    /// For an edge that follows it ([`Lead`]), as of the last sense.
    lead: Lead,
    /// Scratch: the interpolated tables and an event's charges.
    q: Vec<f64>,
    q_raw: Vec<f64>,
    qq: Vec<f64>,
}

/// What an edge following a reset reads from it after the reset's sense of a sample
/// (`reset_events.ResetRun`'s lag_v, fired, jump_v): the lag correction it applied (volts at
/// its sense), the phase of an event it fired for the coming step, that event's physical jump.
#[derive(Debug, Clone, Copy, Default)]
pub struct Lead {
    pub lag_v: f64,
    pub fired: Option<f64>,
    pub jump_v: f64,
    /// The reset's hold-off (in samples): a following edge predicts nothing before it.
    pub busy_until: f64,
}

impl ResetRun {
    pub fn new(el: &ResetEvents, h: f64) -> Result<ResetRun, String> {
        let tables = ResetTables::new(el, h)?;
        let n = tables.steps + 2;
        Ok(ResetRun {
            element: el.clone(),
            tables,
            h,
            pending: vec![0.0; n],
            pending_raw: vec![0.0; n],
            pending_comp: vec![0.0; n],
            hist: [0.0; 3],
            n: 0,
            i_held: 0.0,
            i_comp: 0.0,
            lag: 0.0,
            busy_until: 0.0,
            counts: Counts::default(),
            lead: Lead::default(),
            q: Vec::new(),
            q_raw: Vec::new(),
            qq: Vec::new(),
        })
    }

    /// What a following edge reads ([`Lead`]), as of the last sense.
    pub fn lead(&self) -> Lead {
        self.lead
    }

    /// The current held from src into dst over the step in progress.
    pub fn current(&self) -> f64 {
        self.i_held
    }

    /// The deficit held from dst into ground over the step in progress.
    pub fn comp_current(&self) -> f64 {
        self.i_comp
    }

    /// Sample n's sensed ramp; the current held over the step to n + 1.
    pub fn sense(&mut self, v: f64) -> f64 {
        let (h, m, steps) = (self.h, self.tables.m, self.tables.steps);
        self.lead.lag_v = self.lag / self.element.c_f;
        self.lead.fired = None;
        let v_phys = v - self.lead.lag_v;
        self.hist = [self.hist[1], self.hist[2], v_phys];
        let n = self.n;
        if n >= 2 && n as f64 >= self.busy_until {
            let [h0, h1, h2] = self.hist;
            let mut s = (h1 - h2) / h;
            if s > 0.0 {
                let vt = self.tables.v_t_at(s);
                let mut phi = predict_crossing([vt - h0, vt - h1, vt - h2]);
                if let Some(p) = phi.filter(|&p| p > 0.0) {
                    let qa = 0.5 * (h0 - 2.0 * h1 + h2);
                    let qb = 0.5 * (h0 - 4.0 * h1 + 3.0 * h2);
                    let s2 = -(qb + 2.0 * qa * p) / h;
                    if s2 > 0.0 {
                        let vt2 = self.tables.v_t_at(s2);
                        if let Some(p2) = predict_crossing([vt2 - h0, vt2 - h1, vt2 - h2]) {
                            (s, phi) = (s2, Some(p2));
                        }
                    }
                }
                if let Some(phi) = phi {
                    let t = &self.tables;
                    let (i, a) = ix(&t.log_slope, s.ln());
                    self.q.clear();
                    self.q.extend(
                        t.q[i]
                            .iter()
                            .zip(&t.q[i + 1])
                            .map(|(x, y)| (1.0 - a) * x + a * y),
                    );
                    self.q_raw.clear();
                    self.q_raw.extend(
                        t.q_raw[i]
                            .iter()
                            .zip(&t.q_raw[i + 1])
                            .map(|(x, y)| (1.0 - a) * x + a * y),
                    );
                    let dead = (1.0 - a) * t.dead_s[i] + a * t.dead_s[i + 1];
                    let g = (1.0 - a) * t.g_s[i] + a * t.g_s[i + 1];
                    let cen = (1.0 - a) * t.centroid[i] + a * t.centroid[i + 1];
                    self.counts.events += 1;
                    self.counts.late += u64::from(phi == 0.0);
                    let j = phi * m as f64;
                    let j0 = (j as usize).min(m - 1);
                    let b = j - j0 as f64;
                    let (r0, r1) = (j0 * steps, (j0 + 1) * steps);
                    self.qq.clear();
                    for k in 0..steps {
                        self.qq.push(cubic_phase(&self.q, j0, b, k, m, steps));
                    }
                    // the deficit (`reset_events.ResetRun._deficit`)
                    let (mut kq, mut total) = (0.0, 0.0);
                    for (k, q) in self.qq.iter().enumerate() {
                        kq += k as f64 * q;
                        total += q;
                    }
                    let f = if g <= 0.0 || total <= 0.0 {
                        0.0
                    } else {
                        let acc =
                            kq - total * (phi + cen / m as f64 - (m - 1) as f64 / (2 * m) as f64);
                        g * h / self.element.c_f * acc / total
                    };
                    self.lead.fired = Some(phi);
                    let mut raw = 0.0;
                    for k in 0..steps {
                        raw += (1.0 - b) * self.q_raw[r0 + k] + b * self.q_raw[r1 + k];
                    }
                    self.lead.jump_v = raw / self.element.c_f;
                    for k in 0..steps {
                        self.pending[k] += self.qq[k];
                        self.pending_raw[k] +=
                            (1.0 - b) * self.q_raw[r0 + k] + b * self.q_raw[r1 + k];
                        self.pending_comp[k] += self.qq[k] * f;
                    }
                    self.busy_until = (n as f64 + phi + dead / h).ceil() + HISTORY - 1.0;
                }
            }
        }
        self.i_held = self.pending[0] / h;
        self.i_comp = self.pending_comp[0] / h;
        self.lag += self.pending[0] - self.pending_raw[0];
        for p in [
            &mut self.pending,
            &mut self.pending_raw,
            &mut self.pending_comp,
        ] {
            p.copy_within(1.., 0);
            *p.last_mut().expect("steps + 2") = 0.0;
        }
        self.lead.busy_until = self.busy_until;
        self.n = n + 1;
        self.i_held
    }
}

/// A transition's normalized shape (0 ..= 1 at the reference rate from the event, held at its
/// last value after) band-limited by `h` and integrated over each step of `m` reference
/// samples at every offset j / m (j = 0 ..= m): rows of `steps` fractions of a step
/// (`reset_events.edge_step_table`); every step after a row's last is 1.
pub fn edge_step_table(shape: &[f64], h: &[f64], m: usize) -> Vec<Vec<f64>> {
    // the shape held at 1 through the kernel's length (a plain convolution would take it as 0
    // past its end and the step would fall back), then 1 beyond (h sums to 1)
    let len = shape.len() + h.len() - 1;
    let ext: Vec<f64> = shape
        .iter()
        .copied()
        .chain(std::iter::repeat_n(1.0, h.len() - 1))
        .collect();
    let mut g = vec![0.0; len + m];
    for (i, &p) in ext.iter().enumerate() {
        for (j, &k) in h.iter().enumerate() {
            if i + j < len {
                g[i + j] += p * k;
            }
        }
    }
    for x in &mut g[len..] {
        *x = 1.0;
    }
    let steps = (g.len() + m).div_ceil(m);
    (0..=m)
        .map(|j| {
            let mut buf = vec![1.0; steps * m];
            buf[..j].fill(0.0);
            buf[j..j + g.len()].copy_from_slice(&g);
            buf.chunks_exact(m)
                .map(|c| c.iter().sum::<f64>() / m as f64)
                .collect()
        })
        .collect()
}

/// Row j (-1 ..= m + 1) of an edge's `(m + 1) x steps` table at step k: beyond the ends, the
/// end rows a whole step on (`reset_events.edge_phase_row`).
fn edge_phase_at(q: &[f64], j: isize, k: usize, m: usize, steps: usize) -> f64 {
    if j < 0 {
        if k + 1 < steps {
            q[(m - 1) * steps + k + 1]
        } else {
            1.0
        }
    } else if j as usize > m {
        if k == 0 { 0.0 } else { q[steps + k - 1] }
    } else {
        q[j as usize * steps + k]
    }
}

/// An edge's table at phase row `j0 + a` (0 <= a < 1), step k (`reset_events.edge_cubic_phase`).
fn edge_cubic_phase(q: &[f64], j0: usize, a: f64, k: usize, m: usize, steps: usize) -> f64 {
    let w = [
        -a * (a - 1.0) * (a - 2.0) / 6.0,
        (a + 1.0) * (a - 1.0) * (a - 2.0) / 2.0,
        -(a + 1.0) * a * (a - 2.0) / 2.0,
        (a + 1.0) * a * (a - 1.0) / 6.0,
    ];
    let j = j0 as isize;
    w[0] * edge_phase_at(q, j - 1, k, m, steps)
        + w[1] * edge_phase_at(q, j, k, m, steps)
        + w[2] * edge_phase_at(q, j + 1, k, m, steps)
        + w[3] * edge_phase_at(q, j + 2, k, m, steps)
}

/// An edge's tables for a step of `m` reference samples.
#[derive(Debug, Clone)]
pub struct EdgeTables {
    log_slope: Vec<f64>,
    /// Per direction and point, the levels before and after.
    levels: [Vec<(f64, f64)>; 2],
    pub m: usize,
    pub steps: usize,
    /// Per direction and point, `(m + 1) x steps` fractions (padded with 1).
    tabs: [Vec<Vec<f64>>; 2],
}

impl EdgeTables {
    pub fn new(el: &EdgeEvents, h: f64) -> Result<EdgeTables, String> {
        let m = steps_of(&el.name, el.ref_rate_hz, h)?;
        let kernel = minphase_lowpass(m, KERNEL_ATTEN_DB);
        let mut raw: [Vec<Vec<Vec<f64>>>; 2] = [Vec::new(), Vec::new()];
        let mut levels: [Vec<(f64, f64)>; 2] = [Vec::new(), Vec::new()];
        for d in 0..2 {
            for w in &el.waves_a[d] {
                let (a, b) = (w[0], w[w.len() - 1]);
                let shape: Vec<f64> = w.iter().map(|x| (x - a) / (b - a)).collect();
                raw[d].push(edge_step_table(&shape, &kernel, m));
                levels[d].push((a, b));
            }
        }
        let steps = raw
            .iter()
            .flatten()
            .map(|t| t[0].len())
            .max()
            .expect("validated");
        let flat = |rows: &[Vec<f64>]| {
            let mut out = vec![1.0; (m + 1) * steps];
            for (j, row) in rows.iter().enumerate() {
                out[j * steps..j * steps + row.len()].copy_from_slice(row);
            }
            out
        };
        let tabs = [
            raw[0].iter().map(|t| flat(t)).collect(),
            raw[1].iter().map(|t| flat(t)).collect(),
        ];
        Ok(EdgeTables {
            log_slope: el.log_slope.clone(),
            levels,
            m,
            steps,
            tabs,
        })
    }

    /// The levels before and after for direction `d` at slope `s`, linear in log slope.
    fn levels_at(&self, d: usize, s: f64) -> (f64, f64) {
        let (i, a) = ix(&self.log_slope, s.max(1e-30).ln());
        let (l0, l1) = (self.levels[d][i], self.levels[d][i + 1]);
        ((1.0 - a) * l0.0 + a * l1.0, (1.0 - a) * l0.1 + a * l1.1)
    }
}

/// K's run time on a comparator edge (`reset_events.EdgeRun`): the sensed plus - minus after
/// each sample in, the current held from src into dst over the next step out.
#[derive(Debug, Clone)]
pub struct EdgeRun {
    pub element: EdgeEvents,
    tables: EdgeTables,
    h: f64,
    pending: Vec<f64>,
    level: f64,
    /// The comparator's state (on: sinking), set by the first sense.
    on: Option<bool>,
    busy_until: f64,
    hist: [f64; 3],
    n: u64,
    i_held: f64,
    pub counts: Counts,
    q: Vec<f64>,
}

impl EdgeRun {
    pub fn new(el: &EdgeEvents, h: f64) -> Result<EdgeRun, String> {
        let tables = EdgeTables::new(el, h)?;
        let n = tables.steps + 2;
        Ok(EdgeRun {
            element: el.clone(),
            tables,
            h,
            pending: vec![0.0; n],
            level: 0.0,
            on: None,
            busy_until: 0.0,
            hist: [0.0; 3],
            n: 0,
            i_held: 0.0,
            counts: Counts::default(),
            q: Vec::new(),
        })
    }

    /// The current held from src into dst over the step in progress.
    pub fn current(&self) -> f64 {
        self.i_held
    }

    /// Sample n's sensed plus - minus (and, following a reset, that reset's [`Lead`] after its
    /// own sense of sample n); the current held over the step to n + 1.
    pub fn sense(&mut self, v: f64, lead: Option<Lead>) -> f64 {
        let (h, m, steps) = (self.h, self.tables.m, self.tables.steps);
        let gain = self.element.follow_gain.unwrap_or(0.0);
        let v = match lead {
            Some(l) => v - gain * l.lag_v,
            None => v,
        };
        self.hist = [self.hist[1], self.hist[2], v];
        let n = self.n;
        match self.on {
            None => {
                let on = v < 0.0;
                self.on = Some(on);
                self.level = self.tables.levels_at(if on { 0 } else { 1 }, 1.0).1;
            }
            Some(on) if n >= 2 && n as f64 >= self.busy_until => {
                let [h0, h1, h2] = self.hist;
                let sign = if on { 1.0 } else { -1.0 };
                let mut phi = predict_crossing([sign * h0, sign * h1, sign * h2]);
                let mut s = (h2 - h1).abs() / h;
                let mut hold = 0.0;
                if let Some(l) = lead
                    && let Some(fired) = l.fired
                    && on
                    && v + gain * l.jump_v > 0.0
                {
                    // the reset's jump carries the input across: off at its phase, as fast as
                    // the tables go
                    phi = Some(fired);
                    s = self.tables.log_slope[self.tables.log_slope.len() - 1].exp();
                    // no prediction until the reset's own history is past its jump (its raw
                    // pulse may spill into the next step)
                    hold = l.busy_until;
                }
                if let Some(phi) = phi {
                    let d = usize::from(on);
                    let t = &self.tables;
                    let (i, a) = ix(&t.log_slope, s.max(1e-30).ln());
                    self.q.clear();
                    self.q.extend(
                        t.tabs[d][i]
                            .iter()
                            .zip(&t.tabs[d][i + 1])
                            .map(|(x, y)| (1.0 - a) * x + a * y),
                    );
                    let (_, hi) = t.levels_at(d, s);
                    let j = phi * m as f64;
                    let j0 = (j as usize).min(m - 1);
                    let b = j - j0 as f64;
                    let delta = hi - self.level;
                    for k in 0..steps {
                        self.pending[k] +=
                            delta * (edge_cubic_phase(&self.q, j0, b, k, m, steps) - 1.0);
                    }
                    self.level = hi;
                    self.on = Some(!on);
                    self.counts.events += 1;
                    self.counts.late += u64::from(phi == 0.0);
                    self.busy_until = (n as f64 + HISTORY).max(hold);
                }
            }
            Some(_) => {}
        }
        self.i_held = self.level + self.pending[0];
        self.pending.copy_within(1.., 0);
        *self.pending.last_mut().expect("steps + 2") = 0.0;
        self.n = n + 1;
        self.i_held
    }
}

/// An event kernel element of any kind, as the transient keeps it (`Mna::events`).
#[derive(Debug, Clone, PartialEq)]
pub enum EventElement {
    Thyratron(crate::ir::ThyratronEvents),
    Reset(ResetEvents),
    Edge(EdgeEvents),
}

impl EventElement {
    pub fn name(&self) -> &str {
        match self {
            EventElement::Thyratron(e) => &e.name,
            EventElement::Reset(e) => &e.name,
            EventElement::Edge(e) => &e.name,
        }
    }
}

/// An event kernel's run time of any kind: its senses (node voltages in its ports' order) in,
/// three currents held over the next step out, one per current column of its ports.
// A circuit has a handful of kernels: boxing the thyratron's run would buy nothing.
#[allow(clippy::large_enum_variant)]
#[derive(Debug, Clone)]
pub enum EventRun {
    Thyratron(crate::events::Run),
    Reset(ResetRun),
    Edge(EdgeRun),
}

impl EventRun {
    pub fn new(el: &EventElement, h: f64) -> Result<EventRun, String> {
        Ok(match el {
            EventElement::Thyratron(e) => EventRun::Thyratron(crate::events::Run::new(e, h)?),
            EventElement::Reset(e) => EventRun::Reset(ResetRun::new(e, h)?),
            EventElement::Edge(e) => EventRun::Edge(EdgeRun::new(e, h)?),
        })
    }

    /// The element it runs.
    pub fn element(&self) -> EventElement {
        match self {
            EventRun::Thyratron(r) => EventElement::Thyratron(r.element.clone()),
            EventRun::Reset(r) => EventElement::Reset(r.element.clone()),
            EventRun::Edge(r) => EventElement::Edge(r.element.clone()),
        }
    }

    /// The element's name.
    pub fn name(&self) -> &str {
        match self {
            EventRun::Thyratron(r) => &r.element.name,
            EventRun::Reset(r) => &r.element.name,
            EventRun::Edge(r) => &r.element.name,
        }
    }

    /// The currents held over the step in progress, one per current column: a thyratron's
    /// a -> k, g -> k and the deficit into a; a reset's src -> dst and its deficit dst ->
    /// ground, then 0; an edge's src -> dst, then 0, 0.
    pub fn currents(&self) -> [f64; 3] {
        match self {
            EventRun::Thyratron(r) => [r.current(), r.grid_current(), r.comp_current()],
            EventRun::Reset(r) => [r.current(), r.comp_current(), 0.0],
            EventRun::Edge(r) => [r.current(), 0.0, 0.0],
        }
    }

    /// (events, late, latched) so far.
    pub fn counts(&self) -> (u64, u64, u64) {
        match self {
            EventRun::Thyratron(r) => (r.counts.events, r.counts.late, r.counts.latched),
            EventRun::Reset(r) => (r.counts.events, r.counts.late, 0),
            EventRun::Edge(r) => (r.counts.events, r.counts.late, 0),
        }
    }

    /// Sample n's senses (the node voltages in its ports' sense order: a thyratron's a, g,
    /// k; a reset's ramp; an edge's plus, minus) and, for an edge that follows a reset, that
    /// reset's [`Lead`].
    pub fn sense(&mut self, v: &[f64], lead: Option<Lead>) {
        match self {
            EventRun::Thyratron(r) => {
                r.sense(v[0] - v[2], v[1] - v[2]);
            }
            EventRun::Reset(r) => {
                r.sense(v[0]);
            }
            EventRun::Edge(r) => {
                r.sense(v[0] - v[1], lead);
            }
        }
    }

    /// A reset's [`Lead`] for the edges that follow it (None for the other kinds).
    pub fn lead(&self) -> Option<Lead> {
        match self {
            EventRun::Reset(r) => Some(r.lead()),
            _ => None,
        }
    }
}
