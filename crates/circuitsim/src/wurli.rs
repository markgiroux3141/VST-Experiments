//! The Wurlitzer 200A's reeds as a medium (docs/WURLITZER_PLAN.md, WZ4): every key's reed
//! struck by note events, the reeds' capacitance to the comb plate summed, and the current it
//! pushes into the plate's node. `varimu/wurlitzer/keyboard.py` is the reference (its
//! `Voice`s); the model is a component version compiled by `varimu/wurlitzer/compile.py`
//! (its docstring has the data's layout).
//!
//! **A voice** is one key: the reed's complex modes (only the upper of each conjugate pair
//! kept, the outputs doubled in the data), free or under the damper's felt (keys without a
//! damper are free always). Between events each mode is a decaying rotation; a note-on
//! throws the hammer at the reed wherever it is, from the lowest its strike point can swing
//! (the data's `reach`), the felt's Hunt-Crossley contact solved inside each contact step
//! with the modes' instantaneous response folded in (`key.contact`); the felt is on whenever
//! the key is up and the pedal isn't down, switched at a key's events and the pedal's
//! (deferred to the end of a contact, as the reference's are). A voice sleeps when its tip's
//! amplitude bound falls under the model's `sleep_m`.
//!
//! **The pickup**: the reed's height at the slot's Gauss points, each through its blank's
//! field map c(z) (the reference's cubic spline as piecewise polynomials, z held at the
//! ends), weighted: the key's capacitance less its rest value, `dC = sum_s w_s c(h0 + y_s) -
//! c0`. The voices' dC are summed, one channel, on [`crate::keyed`]'s machinery (rendered
//! ahead, voice by voice, on worker threads; the same bit for bit on any number).
//!
//! **Into the circuit.** The medium senses the plate's voltage V after every step and drives
//! its node `out` at the next with `-V dC / C_r`; the element's part puts the reeds' standing
//! capacitance C_r (the model's `standing_f`) from `out` to the plate. Its current is then
//! `C_r d(v_out - V)/dt = -d((C_r + dC) V)/dt`: the reeds' current exactly, V a step late in
//! the product (a slow node: megohms and hundreds of picofarads). The reed's motion doesn't
//! depend on V (the plate's pull moves the pitch < 0.003 cents: WZ1), so the keys stay one
//! way and render ahead.
//!
//! **Rates.** The voices run at `k` internal samples per step (the least whole multiple of
//! the step rate at or above the element's `rate_hz`), the contact at `s` substeps of those
//! (`contact_rate_hz`); dC is decimated to the step rate by
//! [`crate::partition::Decimator`]'s taps (none at k = 1).

use serde::{Deserialize, Serialize};

use crate::harp::{C64, Complexes, HarpHammer, HarpTransfer, HarpVelocity, as_f64, count, phi12};
use crate::media::NoteEvent;

/// Internal samples between a free voice's sleep checks.
const SLEEP_EVERY: usize = 1024;
/// A mode under this (|z|) at a sleep check is zeroed (subnormals are slow).
const MODE_FLOOR: f64 = 1e-100;
/// Lanes of the modal loops (the modes are padded to a multiple).
const LANES: usize = 4;
const GRAVITY_M_S2: f64 = 9.81;

// --- The model (the component version's data) --------------------------------------

/// One of a key's systems (free, or under the damper's felt).
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct WurliSystem {
    #[serde(deserialize_with = "count", serialize_with = "as_f64")]
    pub modes: usize,
    /// The modes' eigenvalues (1/s).
    pub lam: Complexes,
    /// The hammer's force into the modes (per N).
    pub b: Complexes,
    /// The strike point's displacement and velocity rows (doubled for pairs).
    pub strike: Complexes,
    pub strike_v: Complexes,
    /// The tip's displacement row (the sleep test).
    pub tip: Complexes,
    /// The reed's height at the slot's Gauss points (n_slices x modes, row-major).
    pub slices: Complexes,
    /// The free system's reach rows (`compile.py`): sum sqrt(Re(rq z)^2 + Re(rv z)^2) is the
    /// lowest the strike point can swing. The damped system has none.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub reach_q: Option<Complexes>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub reach_v: Option<Complexes>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct WurliKey {
    /// The key (1-64: A1 = 1).
    #[serde(deserialize_with = "count", serialize_with = "as_f64")]
    pub key: usize,
    #[serde(deserialize_with = "count", serialize_with = "as_f64")]
    pub note: usize,
    pub note_hz: f64,
    /// Its reed's blank: which field map.
    #[serde(deserialize_with = "count", serialize_with = "as_f64")]
    pub blank: usize,
    pub voicing_m: f64,
    /// The slot's Gauss weights (m).
    pub slice_w: Vec<f64>,
    /// Its capacitance to the plate at rest (F).
    pub c0_f: f64,
    pub hammer: HarpHammer,
    pub free: WurliSystem,
    /// Under the damper (None: a key without a damper).
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub damped: Option<WurliSystem>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub to_damped: Option<HarpTransfer>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub to_free: Option<HarpTransfer>,
}

/// A blank's field map c(z) (F / m against the reed's height): piecewise cubics on the
/// breakpoints `x`, coefficients `c` (4 x (len(x) - 1), row-major, the highest power first:
/// scipy's PPoly), z held at the ends.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct WurliField {
    pub x: Vec<f64>,
    pub c: Vec<f64>,
    pub z_range_m: [f64; 2],
}

/// Compiled reeds (a component version of kind `ep_reeds`).
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct WurliModel {
    #[serde(deserialize_with = "count", serialize_with = "as_f64")]
    pub format: usize,
    pub instrument: String,
    pub keys: Vec<WurliKey>,
    pub fields: Vec<WurliField>,
    pub velocity: HarpVelocity,
    pub contact_window_s: f64,
    pub sleep_m: f64,
    /// Every reed's standing capacitance to the plate (F): the part's capacitor.
    pub standing_f: f64,
}

impl WurliModel {
    pub const FORMAT: usize = 1;

    /// Its arrays' shapes and values (the IR's check).
    pub fn check(&self) -> Result<(), String> {
        if self.format != Self::FORMAT {
            return Err(format!(
                "reeds format {} (this code reads {})",
                self.format,
                Self::FORMAT
            ));
        }
        for (b, f) in self.fields.iter().enumerate() {
            let n = f.x.len();
            if n < 2
                || f.c.len() != 4 * (n - 1)
                || f.x.windows(2).any(|w| w[1] <= w[0])
                || f.x.iter().chain(&f.c).any(|v| !v.is_finite())
                || f.z_range_m != [f.x[0], f.x[n - 1]]
            {
                return Err(format!("field {b}: not a piecewise cubic over its range"));
            }
        }
        let mut notes = [false; 128];
        for k in &self.keys {
            let at = format!("key {}", k.key);
            if k.note >= 128 || std::mem::replace(&mut notes[k.note], true) {
                return Err(format!("{at}: note {} is out of range or repeated", k.note));
            }
            if k.blank >= self.fields.len() {
                return Err(format!("{at}: blank {} has no field map", k.blank));
            }
            let h = &k.hammer;
            let positive = [h.mass_kg, h.stiffness, h.exponent]
                .iter()
                .all(|v| v.is_finite() && *v > 0.0);
            if !(positive && h.hysteresis_s_m.is_finite() && h.hysteresis_s_m >= 0.0) {
                return Err(format!("{at}: the hammer must be positive"));
            }
            if k.slice_w.is_empty()
                || k.slice_w.iter().any(|w| !w.is_finite())
                || !(k.c0_f.is_finite() && k.voicing_m.is_finite())
            {
                return Err(format!("{at}: the slot's weights, c0 or the voicing"));
            }
            let has = [
                k.damped.is_some(),
                k.to_damped.is_some(),
                k.to_free.is_some(),
            ];
            if has.iter().any(|&h| h != has[0]) {
                return Err(format!(
                    "{at}: a damped system and its transfers go together"
                ));
            }
            let slices = k.slice_w.len();
            let mut systems = vec![("free", &k.free)];
            systems.extend(k.damped.as_ref().map(|d| ("damped", d)));
            for (what, s) in systems {
                let m = s.modes;
                let vecs = [&s.lam, &s.b, &s.strike, &s.strike_v, &s.tip];
                if m == 0
                    || vecs.iter().any(|v| v.len() != m || v.im.len() != m)
                    || s.slices.len() != slices * m
                    || s.slices.im.len() != slices * m
                {
                    return Err(format!("{at}, {what}: arrays don't match its {m} modes"));
                }
                let reach = [&s.reach_q, &s.reach_v];
                if what == "free" {
                    if reach
                        .iter()
                        .any(|r| r.as_ref().is_none_or(|r| r.len() != m || r.im.len() != m))
                    {
                        return Err(format!("{at}: the free system needs its reach rows"));
                    }
                } else if reach.iter().any(|r| r.is_some()) {
                    return Err(format!("{at}, damped: has no reach rows"));
                }
                if vecs
                    .iter()
                    .chain([&&s.slices])
                    .chain(
                        reach
                            .iter()
                            .filter_map(|r| r.as_ref())
                            .collect::<Vec<_>>()
                            .iter(),
                    )
                    .any(|v| v.re.iter().chain(&v.im).any(|x| !x.is_finite()))
                    || s.lam.re.iter().any(|&r| r > 0.0)
                {
                    return Err(format!("{at}, {what}: values not finite, or a mode grows"));
                }
            }
            if let (Some(d), Some(td), Some(tf)) = (&k.damped, &k.to_damped, &k.to_free) {
                for (what, t, from, to) in
                    [("to_damped", td, &k.free, d), ("to_free", tf, d, &k.free)]
                {
                    let n = from.modes * to.modes;
                    if [&t.a, &t.b].iter().any(|v| v.len() != n || v.im.len() != n) {
                        return Err(format!("{at}, {what}: not {} x {}", to.modes, from.modes));
                    }
                }
            }
        }
        let v = &self.velocity;
        if !(v.ff_speed_m_s > 0.0
            && v.range_db >= 0.0
            && self.contact_window_s > 0.0
            && self.sleep_m > 0.0
            && self.standing_f > 0.0
            && self.standing_f.is_finite())
        {
            return Err(
                "velocity, contact window, sleep or standing capacitance out of range".into(),
            );
        }
        Ok(())
    }
}

// --- The field map ------------------------------------------------------------------

/// A field map for evaluation: per interval its four coefficients together.
#[derive(Debug, Clone)]
pub struct Field {
    x: Vec<f64>,
    /// Interval i's (c3, c2, c1, c0) at 4 i: c3 the cubic's.
    c: Vec<f64>,
}

impl Field {
    pub fn new(f: &WurliField) -> Field {
        let n = f.x.len() - 1;
        let mut c = Vec::with_capacity(4 * n);
        for i in 0..n {
            for p in 0..4 {
                c.push(f.c[p * n + i]);
            }
        }
        Field { x: f.x.clone(), c }
    }

    /// c(z), z held at the ends; `hint` the interval last used (walked from there).
    #[inline(always)]
    pub fn eval(&self, z: f64, hint: &mut usize) -> f64 {
        let x = &self.x;
        let last = x.len() - 2;
        let z = z.clamp(x[0], x[last + 1]);
        let mut i = (*hint).min(last);
        while i > 0 && z < x[i] {
            i -= 1;
        }
        while i < last && z >= x[i + 1] {
            i += 1;
        }
        *hint = i;
        let d = z - x[i];
        let c = &self.c[4 * i..4 * i + 4];
        ((c[0] * d + c[1]) * d + c[2]) * d + c[3]
    }
}

// --- A voice ----------------------------------------------------------------------

/// A system at the voice's rates, its modes padded to a multiple of [`LANES`].
#[derive(Debug, Clone)]
struct Sys {
    m: usize,
    modes: usize,
    rot: (Vec<f64>, Vec<f64>),
    /// The slices' rows, n_slices x m.
    slices: (Vec<f64>, Vec<f64>),
    tip_abs: Vec<f64>,
}

impl Sys {
    fn new(s: &WurliSystem, n_slices: usize, dt: f64) -> Sys {
        let modes = s.modes;
        let m = modes.div_ceil(LANES) * LANES;
        let mut rot = (vec![0.0; m], vec![0.0; m]);
        let mut tip_abs = vec![0.0; m];
        for (j, t) in tip_abs.iter_mut().enumerate().take(modes) {
            let r = s.lam.get(j).scale(dt).exp();
            rot.0[j] = r.0;
            rot.1[j] = r.1;
            *t = s.tip.get(j).norm();
        }
        let mut slices = (vec![0.0; n_slices * m], vec![0.0; n_slices * m]);
        for r in 0..n_slices {
            for j in 0..modes {
                let c = s.slices.get(r * modes + j);
                slices.0[r * m + j] = c.0;
                slices.1[r * m + j] = c.1;
            }
        }
        Sys {
            m,
            modes,
            rot,
            slices,
            tip_abs,
        }
    }
}

/// The free system's contact step at h (the first-order hold's exact step of each mode).
#[derive(Debug, Clone)]
struct ContactStep {
    phi: Vec<C64>,
    g0: Vec<C64>,
    g1: Vec<C64>,
    strike: Vec<C64>,
    strike_v: Vec<C64>,
    reach_q: Vec<C64>,
    reach_v: Vec<C64>,
    gd: f64,
    gv: f64,
    h: f64,
}

impl ContactStep {
    fn new(s: &WurliSystem, h: f64) -> ContactStep {
        let n = s.modes;
        let (mut phi, mut g0, mut g1) = (Vec::new(), Vec::new(), Vec::new());
        for j in 0..n {
            let x = s.lam.get(j).scale(h);
            let (e1, e2) = phi12(x);
            let bh = s.b.get(j).scale(h);
            phi.push(x.exp());
            g1.push(bh.mul(e2));
            g0.push(bh.mul(e1.sub(e2)));
        }
        let row = |c: &Complexes| -> Vec<C64> { (0..n).map(|j| c.get(j)).collect() };
        let strike = row(&s.strike);
        let strike_v = row(&s.strike_v);
        let re_dot = |c: &[C64], z: &[C64]| c.iter().zip(z).map(|(a, b)| a.mul(*b).0).sum::<f64>();
        ContactStep {
            gd: re_dot(&strike, &g1),
            gv: re_dot(&strike_v, &g1),
            reach_q: row(s
                .reach_q
                .as_ref()
                .expect("checked: the free system's reach")),
            reach_v: row(s
                .reach_v
                .as_ref()
                .expect("checked: the free system's reach")),
            phi,
            g0,
            g1,
            strike,
            strike_v,
            h,
        }
    }
}

/// A hammer in contact (or in flight towards the reed) over its window.
#[derive(Debug, Clone)]
struct Contact {
    z: f64,
    v: f64,
    f_prev: f64,
    left: usize,
}

/// One key over the timeline.
#[derive(Debug, Clone)]
pub struct Voice {
    hammer: HarpHammer,
    blank: usize,
    voicing: f64,
    w: Vec<f64>,
    c0: f64,
    free: Sys,
    damped: Option<Sys>,
    contact_step: ContactStep,
    to_damped: Option<HarpTransfer>,
    to_free: Option<HarpTransfer>,
    z: (Vec<f64>, Vec<f64>),
    on_damped: bool,
    asleep: bool,
    contact: Option<Contact>,
    held: bool,
    pedal: bool,
    since_check: usize,
    /// The field map's interval last used, per slice.
    hints: Vec<usize>,
    xf: Vec<C64>,
}

impl Voice {
    fn new(k: &WurliKey, dt: f64, s: usize) -> Voice {
        let ns = k.slice_w.len();
        let free = Sys::new(&k.free, ns, dt);
        let damped = k.damped.as_ref().map(|d| Sys::new(d, ns, dt));
        let m = damped.as_ref().map_or(free.m, |d| d.m.max(free.m));
        Voice {
            hammer: k.hammer.clone(),
            blank: k.blank,
            voicing: k.voicing_m,
            w: k.slice_w.clone(),
            c0: k.c0_f,
            free,
            on_damped: damped.is_some(),
            damped,
            contact_step: ContactStep::new(&k.free, dt / s as f64),
            to_damped: k.to_damped.clone(),
            to_free: k.to_free.clone(),
            z: (vec![0.0; m], vec![0.0; m]),
            asleep: true,
            contact: None,
            held: false,
            pedal: false,
            since_check: 0,
            hints: vec![0; ns],
            xf: vec![C64(0.0, 0.0); k.free.modes],
        }
    }

    fn sys(&self) -> &Sys {
        match &self.damped {
            Some(d) if self.on_damped => d,
            _ => &self.free,
        }
    }

    /// Onto the damped system (or off it), the state carried through the physical
    /// coordinates. A key without a damper stays free.
    fn switch(&mut self, damped: bool) {
        if self.damped.is_none() || damped == self.on_damped {
            return;
        }
        if !self.asleep {
            let d = self.damped.as_ref().expect("a damper");
            let (t, from, to) = if damped {
                (self.to_damped.as_ref(), self.free.modes, d.modes)
            } else {
                (self.to_free.as_ref(), d.modes, self.free.modes)
            };
            let t = t.expect("checked: the transfers with the damper");
            let z: Vec<C64> = (0..from).map(|j| C64(self.z.0[j], self.z.1[j])).collect();
            let mut new = vec![C64(0.0, 0.0); to];
            for (i, n) in new.iter_mut().enumerate() {
                for (j, zj) in z.iter().enumerate() {
                    let a = t.a.get(i * from + j);
                    let b = t.b.get(i * from + j);
                    *n = n.add(a.mul(*zj)).add(b.mul(C64(zj.0, -zj.1)));
                }
            }
            self.z.0.fill(0.0);
            self.z.1.fill(0.0);
            for (j, c) in new.iter().enumerate() {
                self.z.0[j] = c.0;
                self.z.1[j] = c.1;
            }
        }
        self.on_damped = damped;
    }

    fn settle_damper(&mut self) {
        if self.contact.is_none() {
            self.switch(!(self.held || self.pedal));
        }
    }

    fn end_contact(&mut self) {
        if self.contact.take().is_some() {
            self.settle_damper();
        }
    }

    fn event(&mut self, ev: NoteEvent, speed: f64, window: usize) {
        match ev {
            NoteEvent::On { .. } => {
                self.end_contact();
                self.held = true;
                if self.asleep {
                    self.z.0.fill(0.0);
                    self.z.1.fill(0.0);
                }
                self.switch(false);
                self.asleep = false;
                let cs = &self.contact_step;
                let n = self.free.modes;
                let (mut y0, mut reach) = (0.0, 0.0);
                for j in 0..n {
                    let z = C64(self.z.0[j], self.z.1[j]);
                    y0 += cs.strike[j].mul(z).0;
                    reach += cs.reach_q[j].mul(z).0.hypot(cs.reach_v[j].mul(z).0);
                }
                self.contact = Some(Contact {
                    z: y0.min(-reach),
                    v: speed,
                    f_prev: 0.0,
                    left: window.max(1),
                });
            }
            NoteEvent::Off { .. } => {
                self.held = false;
                self.end_contact();
                self.settle_damper();
            }
            NoteEvent::Pedal { down } => {
                self.pedal = down;
                self.settle_damper();
            }
            NoteEvent::Pressure { .. } => {}
        }
    }

    /// One internal sample of contact: `s` steps with the force solved in each.
    fn contact_sample(&mut self, s: usize) {
        let c = self.contact.as_mut().expect("in contact");
        let cs = &self.contact_step;
        let hm = &self.hammer;
        let (h, m) = (cs.h, hm.mass_kg);
        let n = self.free.modes;
        let xf = &mut self.xf;
        for _ in 0..s {
            let (mut y_free, mut yv_free) = (0.0, 0.0);
            for (j, xj) in xf.iter_mut().enumerate().take(n) {
                let x = cs.phi[j]
                    .mul(C64(self.z.0[j], self.z.1[j]))
                    .add(cs.g0[j].scale(c.f_prev));
                y_free += cs.strike[j].mul(x).0;
                yv_free += cs.strike_v[j].mul(x).0;
                *xj = x;
            }
            let z_free =
                c.z + h * c.v - h * h * (2.0 * c.f_prev / m) / 6.0 - 0.5 * GRAVITY_M_S2 * h * h;
            let v_free = c.v - h * c.f_prev / (2.0 * m) - GRAVITY_M_S2 * h;
            let d_free = z_free - y_free;
            let dd_free = v_free - yv_free;
            let cd = cs.gd + h * h / (6.0 * m);
            let cv = cs.gv + h / (2.0 * m);
            let mut f = 0.0;
            if d_free > 0.0 {
                f = c.f_prev.max(0.0);
                for _ in 0..60 {
                    let d = d_free - cd * f;
                    let dd = dd_free - cv * f;
                    let (r, dr) = if d <= 0.0 {
                        (f, 1.0)
                    } else {
                        let hc = 1.0 + hm.hysteresis_s_m * dd;
                        let r = f - hm.stiffness * d.powf(hm.exponent) * hc.max(0.0);
                        let mut dr = 1.0;
                        if hc > 0.0 {
                            dr += hm.stiffness
                                * (hm.exponent * d.powf(hm.exponent - 1.0) * cd * hc
                                    + d.powf(hm.exponent) * hm.hysteresis_s_m * cv);
                        }
                        (r, dr)
                    };
                    let step = r / dr;
                    f = (f - step).max(0.0);
                    if step.abs() < 1e-13 * f.abs().max(1.0) {
                        break;
                    }
                }
            }
            for (j, xj) in xf.iter().enumerate().take(n) {
                let x = xj.add(cs.g1[j].scale(f));
                self.z.0[j] = x.0;
                self.z.1[j] = x.1;
            }
            c.z = z_free - h * h * f / (6.0 * m);
            c.v = v_free - h * f / (2.0 * m);
            c.f_prev = f;
        }
        c.left -= 1;
        // The hammer gone for good (falling, below the lowest the strike point can reach):
        // the window's rest would step the free motion only.
        if c.f_prev == 0.0 && c.v <= 0.0 && c.left > 0 {
            let reach: f64 = (0..n)
                .map(|j| cs.strike[j].norm() * self.z.0[j].hypot(self.z.1[j]))
                .sum();
            if c.z < -reach {
                c.left = 0;
            }
        }
    }

    /// dC now (the slices through the field map, less the rest).
    #[inline(always)]
    fn dc(
        sys: &Sys,
        (zr, zi): (&[f64], &[f64]),
        f: &Field,
        (voicing, w, c0): (f64, &[f64], f64),
        hints: &mut [usize],
    ) -> f64 {
        let m = sys.m;
        let (zr, zi) = (&zr[..m], &zi[..m]);
        let mut c = 0.0;
        for (r, (wr, hint)) in w.iter().zip(hints.iter_mut()).enumerate() {
            let y = dot(
                &sys.slices.0[r * m..(r + 1) * m],
                &sys.slices.1[r * m..(r + 1) * m],
                zr,
                zi,
            );
            c += wr * f.eval(voicing + y, hint);
        }
        c - c0
    }

    /// Add `out.len()` internal samples of this voice's dC into `out`.
    fn render(&mut self, out: &mut [f64], fields: &[Field], s: usize, sleep: f64) {
        let f = &fields[self.blank];
        let mut i = 0;
        while i < out.len() && !self.asleep {
            if self.contact.is_some() {
                self.contact_sample(s);
                out[i] += Self::dc(
                    &self.free,
                    (&self.z.0, &self.z.1),
                    f,
                    (self.voicing, &self.w, self.c0),
                    &mut self.hints,
                );
                i += 1;
                if self.contact.as_ref().is_some_and(|c| c.left == 0) {
                    self.end_contact();
                }
                continue;
            }
            let n = (out.len() - i).min(SLEEP_EVERY - self.since_check);
            let sys = match &self.damped {
                Some(d) if self.on_damped => d,
                _ => &self.free,
            };
            free_run(
                sys,
                (&mut self.z.0, &mut self.z.1),
                &mut out[i..i + n],
                f,
                (self.voicing, &self.w, self.c0),
                &mut self.hints,
            );
            i += n;
            self.since_check += n;
            if self.since_check >= SLEEP_EVERY {
                self.since_check = 0;
                let sys = self.sys();
                let bound: f64 = (0..sys.modes)
                    .map(|j| sys.tip_abs[j] * self.z.0[j].hypot(self.z.1[j]))
                    .sum();
                if bound < sleep {
                    self.asleep = true;
                    self.z.0.fill(0.0);
                    self.z.1.fill(0.0);
                } else {
                    for j in 0..self.z.0.len() {
                        if self.z.0[j].abs() < MODE_FLOOR && self.z.1[j].abs() < MODE_FLOOR {
                            self.z.0[j] = 0.0;
                            self.z.1[j] = 0.0;
                        }
                    }
                }
            }
        }
    }
}

/// Re(sum c z) over equal slices (a multiple of [`LANES`] long), in four lanes.
#[inline(always)]
fn dot(cr: &[f64], ci: &[f64], zr: &[f64], zi: &[f64]) -> f64 {
    let mut acc = [0.0; LANES];
    for (((cr, ci), zr), zi) in cr
        .chunks_exact(LANES)
        .zip(ci.chunks_exact(LANES))
        .zip(zr.chunks_exact(LANES))
        .zip(zi.chunks_exact(LANES))
    {
        for l in 0..LANES {
            acc[l] += cr[l] * zr[l] - ci[l] * zi[l];
        }
    }
    (acc[0] + acc[1]) + (acc[2] + acc[3])
}

/// A free voice over `out`: each sample its modes rotated, its dC added. Vectorized with
/// AVX2 where the CPU has it (the same operations lane for lane; no FMA).
fn free_run(
    sys: &Sys,
    z: (&mut [f64], &mut [f64]),
    out: &mut [f64],
    f: &Field,
    key: (f64, &[f64], f64),
    hints: &mut [usize],
) {
    #[cfg(target_arch = "x86_64")]
    if std::is_x86_feature_detected!("avx2") {
        // SAFETY: the CPU has AVX2 (checked above).
        unsafe { free_run_avx2(sys, z, out, f, key, hints) };
        return;
    }
    free_run_impl(sys, z, out, f, key, hints);
}

#[cfg(target_arch = "x86_64")]
#[target_feature(enable = "avx2")]
unsafe fn free_run_avx2(
    sys: &Sys,
    z: (&mut [f64], &mut [f64]),
    out: &mut [f64],
    f: &Field,
    key: (f64, &[f64], f64),
    hints: &mut [usize],
) {
    free_run_impl(sys, z, out, f, key, hints);
}

#[inline(always)]
fn free_run_impl(
    sys: &Sys,
    (zr, zi): (&mut [f64], &mut [f64]),
    out: &mut [f64],
    f: &Field,
    (voicing, w, c0): (f64, &[f64], f64),
    hints: &mut [usize],
) {
    let m = sys.m;
    let (zr, zi) = (&mut zr[..m], &mut zi[..m]);
    let (rr, ri) = (&sys.rot.0[..m], &sys.rot.1[..m]);
    for o in out.iter_mut() {
        for (((zr, zi), rr), ri) in zr
            .chunks_exact_mut(LANES)
            .zip(zi.chunks_exact_mut(LANES))
            .zip(rr.chunks_exact(LANES))
            .zip(ri.chunks_exact(LANES))
        {
            for l in 0..LANES {
                let (a, c) = (zr[l], zi[l]);
                zr[l] = a * rr[l] - c * ri[l];
                zi[l] = a * ri[l] + c * rr[l];
            }
        }
        *o += Voice::dc(sys, (zr, zi), f, (voicing, w, c0), hints);
    }
}

// --- The medium -------------------------------------------------------------------

/// What every voice reads.
#[derive(Debug)]
pub struct WurliCtx {
    fields: Vec<Field>,
    sleep: f64,
    s: usize,
    window: usize,
    velocity: HarpVelocity,
}

impl crate::keyed::KeyVoice for Voice {
    type Ctx = WurliCtx;

    fn asleep(&self) -> bool {
        self.asleep
    }

    fn event(&mut self, ev: NoteEvent, ctx: &WurliCtx) {
        let speed = match ev {
            NoteEvent::On { velocity, .. } => ctx.velocity.hammer_speed(velocity),
            NoteEvent::Pressure { .. } => return,
            _ => 0.0,
        };
        Voice::event(self, ev, speed, ctx.window);
    }

    fn render(&mut self, buf: &mut [f64], _n: usize, from: usize, to: usize, ctx: &WurliCtx) {
        Voice::render(self, &mut buf[from..to], &ctx.fields, ctx.s, ctx.sleep);
    }

    fn silence(&mut self) {
        self.asleep = true;
        self.contact = None;
        self.z.0.fill(0.0);
        self.z.1.fill(0.0);
    }
}

/// The reeds beside the circuit at step rate `fs` (see the module docs).
pub struct Medium {
    pub el: crate::ir::WurliReeds,
    /// Internal samples per step and contact steps per internal sample.
    pub k: usize,
    pub s: usize,
    keys: crate::keyed::Medium<Voice>,
    /// The last push's dC (F).
    dc: f64,
}

impl std::fmt::Debug for Medium {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("wurli::Medium")
            .field("reeds", &self.el.name)
            .field("k", &self.k)
            .field("s", &self.s)
            .field("keys", &self.keys)
            .finish()
    }
}

impl Medium {
    pub fn new(el: &crate::ir::WurliReeds, fs: f64) -> Medium {
        Medium::with_workers(el, fs, crate::keyed::workers())
    }

    /// [`Medium::new`] with `n` worker threads (the result is the same with any number).
    pub fn with_workers(el: &crate::ir::WurliReeds, fs: f64, n: usize) -> Medium {
        let k = ((el.rate_hz / fs) - 1e-9).ceil().max(1.0) as usize;
        let s = ((el.contact_rate_hz / (fs * k as f64)) - 1e-9)
            .ceil()
            .max(1.0) as usize;
        let dt = 1.0 / (fs * k as f64);
        let model = &el.model;
        let voices = model
            .keys
            .iter()
            .map(|key| (key.note as u8, Voice::new(key, dt, s)))
            .collect();
        let ctx = WurliCtx {
            fields: model.fields.iter().map(Field::new).collect(),
            sleep: model.sleep_m,
            s,
            window: (model.contact_window_s * fs * k as f64).round() as usize,
            velocity: model.velocity.clone(),
        };
        let mut keys = crate::keyed::Medium::new(voices, ctx, fs, k, 1, n);
        // A voice is cheap (3-13 modes, 8 slices): a few on the calling thread.
        keys.set_inline_voices(6);
        Medium {
            el: el.clone(),
            k,
            s,
            keys,
            dc: 0.0,
        }
    }

    /// Keep every internal sample rendered from now on ([`Medium::raw`]; tests).
    pub fn keep_raw(&mut self) {
        self.keys.keep_raw();
    }

    /// The internal dC kept (F).
    pub fn raw(&self) -> &[f64] {
        self.keys.raw(0)
    }

    pub fn delay_steps(&self) -> f64 {
        self.keys.delay_steps()
    }

    pub fn position(&self) -> usize {
        self.keys.position()
    }

    pub fn queue(&mut self, at: usize, ev: NoteEvent) {
        self.keys.queue(at, ev);
    }

    pub fn known_until(&mut self, at: usize) {
        self.keys.known_until(at);
    }

    /// The reeds' dC at the next step (F).
    pub fn push_dc(&mut self) -> f64 {
        let mut y = [0.0];
        self.keys.push_into(&mut y);
        self.dc = y[0];
        y[0]
    }

    /// The plate's voltage at this step; the drive at the next, `-V dC / C_r`.
    pub fn push(&mut self, plate_v: f64) -> f64 {
        -plate_v * self.push_dc() / self.el.model.standing_f
    }

    /// The last push's dC (F).
    pub fn last_dc(&self) -> f64 {
        self.dc
    }

    pub fn sounding(&self) -> usize {
        self.keys.sounding()
    }

    pub fn pedal(&self) -> bool {
        self.keys.pedal()
    }

    /// Whether `el` keeps this medium playing (the same model and rates).
    pub fn same(&self, el: &crate::ir::WurliReeds) -> bool {
        el.model == self.el.model
            && el.rate_hz == self.el.rate_hz
            && el.contact_rate_hz == self.el.contact_rate_hz
    }

    pub fn fs(&self) -> f64 {
        self.keys.fs()
    }

    pub fn voice_of(&self, note: u8) -> Option<usize> {
        self.keys.voice_of(note)
    }
}

/// The reeds alone: `n` steps at `fs` from rest, `events` (step, event) in order, on
/// `workers` worker threads (None: the default); returns dC at every step (sample 0 the
/// rest's), every internal sample (index 0 the rest's) and (k, s).
pub fn render(
    el: &crate::ir::WurliReeds,
    fs: f64,
    n: usize,
    events: &[(usize, NoteEvent)],
    workers: Option<usize>,
) -> (Vec<f64>, Vec<f64>, (usize, usize)) {
    let mut m = Medium::with_workers(el, fs, workers.unwrap_or_else(crate::keyed::workers));
    m.keep_raw();
    for &(at, ev) in events {
        m.queue(at, ev);
    }
    m.known_until(usize::MAX);
    let mut y = vec![0.0];
    for _ in 1..n {
        y.push(m.push_dc());
    }
    let mut raw = vec![0.0];
    raw.extend_from_slice(m.raw());
    raw.truncate((n - 1) * m.k + 1);
    (y, raw, (m.k, m.s))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_field_is_its_piecewise_cubics_held_at_the_ends() {
        // c(z) = z^3 on [0, 1], (z - 1)^2 + 1 on [1, 3]: the rows c3 = [1, 0], c2 = [0, 1],
        // c1 = [0, 0], c0 = [0, 1]
        let f = Field::new(&WurliField {
            x: vec![0.0, 1.0, 3.0],
            c: vec![1.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0],
            z_range_m: [0.0, 3.0],
        });
        let mut h = 0;
        for (z, want) in [
            (-1.0, 0.0),
            (0.5, 0.125),
            (1.5, 1.25),
            (2.9, 4.61),
            (9.0, 5.0),
        ] {
            let v = f.eval(z, &mut h);
            assert!((v - want).abs() < 1e-12, "{z}: {v} vs {want}");
        }
        // Walking back from the hint.
        assert!((f.eval(0.25, &mut h) - 0.015625).abs() < 1e-15);
    }
}
