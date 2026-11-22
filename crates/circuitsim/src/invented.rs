//! The invented instruments' keyboards (docs/INVENTED_LIVE_PLAN.md): one medium for all of
//! them, the IR element [`InventedKeys`] naming the instrument its data is for. Each
//! instrument is a voice kind here, step for step with its Python reference in
//! `varimu/invented/keys/` (plain scalar arithmetic in the same order, sums in a loop), played
//! by note events through [`crate::keyed`]. It senses nothing and drives `out` with the
//! keys' summed output at the next step.
//!
//! The panel is four knobs `k0`-`k3` (0-1), each instrument saying what they are; they play
//! on ([`Medium::update`]).
//!
//! Instruments: `rosin_wheel` (IL1, steel bars bowed by a rosined wheel:
//! `varimu/invented/keys/rosin.py`), `buzz_zither` (IL2, plucked strings over jawari bridges
//! and a tanpura on the pedal: `varimu/invented/keys/zither.py`), `rijke_organ` (IL3, pipes
//! sung by heated gauzes: `varimu/invented/keys/rijke.py`), `aeolian_keyboard` (IL4, gut
//! strings sung by the wind: `varimu/invented/keys/aeolian.py`), `bubble_organ` (IL5, air
//! bubbles from nozzles in a water tank: `varimu/invented/keys/bubbles.py`), `siren_organ`
//! (IL6, rings of holes on one motor's shaft chopping one bellows' wind:
//! `varimu/invented/keys/siren.py`; its shaft is state every key shares, [`Shaft`]).

use std::collections::HashMap;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Arc, Mutex, OnceLock, RwLock};

use serde::Deserialize;

use crate::ir::InventedKeys;
use crate::media::NoteEvent;

// --- shared pieces ----------------------------------------------------------------------

const GOLDEN: u64 = 0x9E3779B97F4A7C15;

/// splitmix64 into Box-Muller, the spare kept (`common.Gauss`).
#[derive(Debug, Clone)]
pub struct Gauss {
    s: u64,
    spare: Option<f64>,
}

impl Gauss {
    pub fn new(seed: u64) -> Gauss {
        Gauss {
            s: seed,
            spare: None,
        }
    }

    fn next_u64(&mut self) -> u64 {
        self.s = self.s.wrapping_add(GOLDEN);
        let mut z = self.s;
        z = (z ^ (z >> 30)).wrapping_mul(0xBF58476D1CE4E5B9);
        z = (z ^ (z >> 27)).wrapping_mul(0x94D049BB133111EB);
        z ^ (z >> 31)
    }

    fn uniform(&mut self) -> f64 {
        ((self.next_u64() >> 11) as f64 + 0.5) / (1u64 << 53) as f64
    }

    pub fn sample(&mut self) -> f64 {
        if let Some(x) = self.spare.take() {
            return x;
        }
        let (u, v) = (self.uniform(), self.uniform());
        let r = (-2.0 * u.ln()).sqrt();
        let a = 2.0 * std::f64::consts::PI * v;
        self.spare = Some(r * a.sin());
        r * a.cos()
    }
}

/// A voice's noise stream (`common.key_seed`).
pub fn key_seed(seed: u64, note: u8) -> u64 {
    seed ^ (note as u64).wrapping_mul(GOLDEN)
}

/// RBJ's constant-0-dB-peak band-pass, normalized: [b0, b1, b2, a1, a2] (`common.bandpass`).
pub fn bandpass(f_hz: f64, q: f64, fs: f64) -> [f64; 5] {
    let w0 = 2.0 * std::f64::consts::PI * f_hz / fs;
    let alpha = w0.sin() / (2.0 * q);
    let a0 = 1.0 + alpha;
    [
        alpha / a0,
        0.0,
        -alpha / a0,
        -2.0 * w0.cos() / a0,
        (1.0 - alpha) / a0,
    ]
}

/// One trapezoidal step of m x'' + c x' + k x = F (unit mode shape), y+ = P y + r (F + F+):
/// [p00, p01, p10, p11, r0, r1] (`common.modal_step`).
pub fn modal_step(f_hz: f64, q: f64, h: f64, mass: f64) -> [f64; 6] {
    let w = 2.0 * std::f64::consts::PI * f_hz;
    let zeta = 1.0 / (2.0 * q);
    let hw2 = h * w / 2.0;
    let det = 1.0 + h * zeta * w + hw2 * hw2;
    let i00 = (1.0 + h * zeta * w) / det;
    let i01 = (h / 2.0) / det;
    let i10 = (-(h / 2.0) * w * w) / det;
    let i11 = 1.0 / det;
    let (a01, a10, a11) = (h / 2.0, -(h / 2.0) * w * w, 1.0 - h * zeta * w);
    let p00 = i00 + i01 * a10;
    let p01 = i00 * a01 + i01 * a11;
    let p10 = i10 + i11 * a10;
    let p11 = i10 * a01 + i11 * a11;
    let b = (h / 2.0) / mass;
    [p00, p01, p10, p11, i01 * b, i11 * b]
}

fn knob(lo_hi: [f64; 2], k: f64) -> f64 {
    lo_hi[0] + (lo_hi[1] - lo_hi[0]) * k
}

// --- the data ---------------------------------------------------------------------------

/// An instrument's compiled data (a component version of kind `invented_keys`).
#[derive(Debug, Clone)]
pub enum Model {
    Rosin(RosinModel),
    Zither(ZitherModel),
    Rijke(RijkeModel),
    Aeolian(AeolianModel),
    Bubble(BubbleModel),
    Siren(SirenModel),
}

impl Model {
    pub fn from_json(instrument: &str, text: &str) -> Result<Model, String> {
        let head: serde_json::Value =
            serde_json::from_str(text).map_err(|e| format!("invented keys: {e}"))?;
        let named = head
            .get("instrument")
            .and_then(|v| v.as_str())
            .unwrap_or("");
        if named != instrument {
            return Err(format!(
                "the data is for {named:?}, the element says {instrument:?}"
            ));
        }
        match instrument {
            "rosin_wheel" => Ok(Model::Rosin(
                serde_json::from_value(head).map_err(|e| format!("rosin_wheel: {e}"))?,
            )),
            "buzz_zither" => Ok(Model::Zither(
                serde_json::from_value(head).map_err(|e| format!("buzz_zither: {e}"))?,
            )),
            "rijke_organ" => Ok(Model::Rijke(
                serde_json::from_value(head).map_err(|e| format!("rijke_organ: {e}"))?,
            )),
            "aeolian_keyboard" => Ok(Model::Aeolian(
                serde_json::from_value(head).map_err(|e| format!("aeolian_keyboard: {e}"))?,
            )),
            "bubble_organ" => Ok(Model::Bubble(
                serde_json::from_value(head).map_err(|e| format!("bubble_organ: {e}"))?,
            )),
            "siren_organ" => Ok(Model::Siren(
                serde_json::from_value(head).map_err(|e| format!("siren_organ: {e}"))?,
            )),
            other => Err(format!("no invented instrument {other:?}")),
        }
    }

    /// The span (dB from velocity 127 to 1) of what velocity sets: the Rosin Wheel's press
    /// force, the Buzz Zither's pluck force (the Play view's Touch sliders).
    pub fn velocity_span_db(&self) -> f64 {
        let lo = 1.0 / 127.0;
        match self {
            Model::Rosin(m) => {
                let f =
                    |v: f64| m.force_min_n + (m.force_max_n - m.force_min_n) * v.powf(m.force_exp);
                20.0 * (f(1.0) / f(lo)).log10()
            }
            Model::Zither(m) => {
                20.0 * (knob(m.force_range_n, 1.0) / knob(m.force_range_n, lo)).log10()
            }
            // The heater's power (the level follows it weakly; the bloom's speed strongly).
            Model::Rijke(m) => 20.0 * (knob(m.k_range, 1.0) / knob(m.k_range, lo)).log10(),
            // The slot's opening: the jet's width, so the lift.
            Model::Aeolian(m) => 20.0 * (1.0 / knob([m.open_min, 1.0], lo)).log10(),
            // A struck bubble's pinch-off (0.5 + velocity; the flow's size law aside).
            Model::Bubble(_) => 20.0 * (1.5 / (0.5 + lo)).log10(),
            // The valve's opening: the flow through the ring.
            Model::Siren(m) => 20.0 * (1.0 / knob(m.open_range, lo)).log10(),
        }
    }

    fn notes(&self) -> Vec<u8> {
        match self {
            Model::Rosin(m) => m.keys.iter().map(|k| k.note).collect(),
            Model::Zither(m) => m.keys.iter().map(|k| k.note).collect(),
            Model::Rijke(m) => m.keys.iter().map(|k| k.note).collect(),
            Model::Aeolian(m) => m.keys.iter().map(|k| k.note).collect(),
            Model::Bubble(m) => m.keys.iter().map(|k| k.note).collect(),
            Model::Siren(m) => m.keys.iter().map(|k| k.note).collect(),
        }
    }
}

/// The data an element names, loaded once per process (by path and sha256; the builders
/// check the file against the sha256 its component version gives).
pub fn load(el: &InventedKeys) -> Result<Arc<Model>, String> {
    type Loaded = Mutex<HashMap<(String, String), Arc<Model>>>;
    static LOADED: OnceLock<Loaded> = OnceLock::new();
    let cache = LOADED.get_or_init(Default::default);
    let id = (el.data.clone(), el.sha256.clone());
    if let Some(m) = cache.lock().expect("invented").get(&id) {
        return Ok(m.clone());
    }
    let path = {
        let p = std::path::Path::new(&el.data);
        if p.is_absolute() {
            p.to_path_buf()
        } else {
            crate::clavinet::data_root().join(p)
        }
    };
    let raw = std::fs::read_to_string(&path)
        .map_err(|e| format!("{}: {}: {e}", el.name, path.display()))?;
    let m =
        Arc::new(Model::from_json(&el.instrument, &raw).map_err(|e| format!("{}: {e}", el.name))?);
    if m.notes().is_empty() {
        return Err(format!("{}: {}: no keys", el.name, path.display()));
    }
    Ok(cache
        .lock()
        .expect("invented")
        .entry(id)
        .or_insert(m)
        .clone())
}

// --- IL1 the Rosin Wheel Organ ----------------------------------------------------------

#[derive(Debug, Clone, Deserialize)]
pub struct RosinKey {
    pub note: u8,
    pub f_hz: Vec<f64>,
    pub q: Vec<f64>,
    pub mass_kg: f64,
}

#[derive(Debug, Clone, Deserialize)]
pub struct RosinModel {
    pub keys: Vec<RosinKey>,
    pub mu_s: f64,
    pub mu_d: f64,
    pub v0_m_s: f64,
    pub wheel_range_m_s: [f64; 2],
    pub wheel_hz: f64,
    pub wobble: f64,
    pub rosin_noise: f64,
    pub noise_hz: f64,
    pub force_min_n: f64,
    pub force_max_n: f64,
    pub force_exp: f64,
    pub pressure_gain: f64,
    pub touch_range: [f64; 2],
    pub attack_s: f64,
    pub release_s: f64,
    pub q_damped: f64,
    pub sleep_s: f64,
    pub resonator_max: f64,
    pub resonator_q: f64,
    pub pickup_v_per_m_s: f64,
    /// LIMIT's check felt (ROSIN_WHEEL@2 on; absent: no felt, k3 unused): its drag (N s/m),
    /// the end velocity where it engages from LIMIT just on to full, the fraction of its gap
    /// it engages over (`rosin.py`'s docs).
    #[serde(default)]
    pub felt_c_n_s_m: Option<f64>,
    #[serde(default)]
    pub limit_v_m_s: Option<[f64; 2]>,
    #[serde(default)]
    pub felt_width: Option<f64>,
    pub seed: u64,
}

/// One key's bar (`rosin.Voice`, step for step).
#[derive(Debug, Clone)]
pub struct RosinVoice {
    m: Arc<Model>,
    h: f64,
    free: Vec<[f64; 6]>,
    damped_steps: Vec<[f64; 6]>,
    bp: [f64; 5],
    x: Vec<f64>,
    v: Vec<f64>,
    xn: Vec<f64>,
    vn: Vec<f64>,
    f_prev: f64,
    bx1: f64,
    bx2: f64,
    by1: f64,
    by2: f64,
    press: f64,
    down: bool,
    pedal_down: bool,
    velocity: f64,
    aftertouch: f64,
    damped: bool,
    quiet: usize,
    awake: bool,
    cw: f64,
    sw: f64,
    pc: f64,
    ps: f64,
    na: f64,
    norm: f64,
    nz: f64,
    gauss: Gauss,
    sleep_n: usize,
    wheel: f64,
    res_gain: f64,
    touch: f64,
    f1: f64,
    /// LIMIT's felt gap at the free end (m; 0: no felt).
    gap: f64,
}

impl RosinVoice {
    fn rm(&self) -> &RosinModel {
        match &*self.m {
            Model::Rosin(r) => r,
            _ => unreachable!("a rosin voice on another model"),
        }
    }

    fn new(model: &Arc<Model>, key: &RosinKey, fs: f64, knobs: [f64; 4]) -> RosinVoice {
        let Model::Rosin(m) = &**model else {
            unreachable!("a rosin voice on another model")
        };
        let h = 1.0 / fs;
        let free: Vec<[f64; 6]> = key
            .f_hz
            .iter()
            .zip(&key.q)
            .map(|(&f, &q)| modal_step(f, q, h, key.mass_kg))
            .collect();
        let damped_steps: Vec<[f64; 6]> = key
            .f_hz
            .iter()
            .zip(&key.q)
            .map(|(&f, &q)| modal_step(f, q.min(m.q_damped), h, key.mass_kg))
            .collect();
        let n = key.f_hz.len();
        let w = 2.0 * std::f64::consts::PI * m.wheel_hz * h;
        let a = (-2.0 * std::f64::consts::PI * m.noise_hz * h).exp();
        let mut v = RosinVoice {
            m: model.clone(),
            h,
            free,
            damped_steps,
            bp: bandpass(key.f_hz[0], m.resonator_q, fs),
            x: vec![0.0; n],
            v: vec![0.0; n],
            xn: vec![0.0; n],
            vn: vec![0.0; n],
            f_prev: 0.0,
            bx1: 0.0,
            bx2: 0.0,
            by1: 0.0,
            by2: 0.0,
            press: 0.0,
            down: false,
            pedal_down: false,
            velocity: 0.0,
            aftertouch: 0.0,
            damped: true,
            quiet: 0,
            awake: false,
            cw: w.cos(),
            sw: w.sin(),
            pc: 1.0,
            ps: 0.0,
            na: a,
            norm: ((1.0 + a) / (1.0 - a)).sqrt(),
            nz: 0.0,
            gauss: Gauss::new(key_seed(m.seed, key.note)),
            sleep_n: (m.sleep_s * fs) as usize,
            wheel: 0.0,
            res_gain: 0.0,
            touch: 0.0,
            f1: key.f_hz[0],
            gap: 0.0,
        };
        v.set_knobs(knobs);
        v
    }

    fn set_knobs(&mut self, k: [f64; 4]) {
        let f1 = self.f1;
        let (wheel, res, touch, gap) = {
            let m = self.rm();
            let gap = match (m.felt_c_n_s_m, m.limit_v_m_s) {
                (Some(_), Some([lo, hi])) if k[3] > 0.0 => {
                    let v_lim = lo * (hi / lo).powf(k[3].min(1.0));
                    v_lim / (2.0 * std::f64::consts::PI * f1)
                }
                _ => 0.0,
            };
            (
                knob(m.wheel_range_m_s, k[0]),
                m.resonator_max * k[1],
                knob(m.touch_range, k[2]),
                gap,
            )
        };
        self.wheel = wheel;
        self.res_gain = res;
        self.touch = touch;
        self.gap = gap;
    }

    fn event(&mut self, ev: NoteEvent) {
        match ev {
            NoteEvent::On { velocity, .. } => {
                self.down = true;
                self.velocity = velocity as f64 / 127.0;
                self.awake = true;
                self.damped = false;
                self.quiet = 0;
            }
            NoteEvent::Off { .. } => self.down = false,
            NoteEvent::Pedal { down } => self.pedal_down = down,
            NoteEvent::Pressure { value } => self.aftertouch = value as f64 / 127.0,
        }
    }

    fn step(&mut self) -> f64 {
        let model = self.m.clone();
        let Model::Rosin(m) = &*model else {
            unreachable!("a rosin voice on another model")
        };
        let held = self.down || (self.pedal_down && self.press > 0.0);
        if held {
            self.press = (self.press + self.h / m.attack_s).min(1.0);
        } else {
            self.press = (self.press - self.h / m.release_s).max(0.0);
            if self.press == 0.0 && !self.damped {
                self.damped = true;
                self.quiet = 0;
            }
        }
        let p = self.press;
        let shape = p * p * (3.0 - 2.0 * p);
        let f_vel =
            m.force_min_n + (m.force_max_n - m.force_min_n) * self.velocity.powf(m.force_exp);
        let pc = self.pc * self.cw - self.ps * self.sw;
        let ps = self.ps * self.cw + self.pc * self.sw;
        self.pc = pc;
        self.ps = ps;
        let fn_ = self.touch
            * f_vel
            * (1.0 + m.pressure_gain * self.aftertouch)
            * shape
            * (1.0 + m.wobble * ps);
        self.nz = self.na * self.nz + (1.0 - self.na) * self.gauss.sample();
        let rosin = 1.0 + m.rosin_noise * self.nz * self.norm;
        let steps = if self.damped {
            &self.damped_steps
        } else {
            &self.free
        };
        // LIMIT's felt at the free end (mode shapes +-2, the pickup's): its drag from the
        // step's start, held over the step (gf: the trapezoid's two ends).
        let mut gf = 0.0;
        if self.gap > 0.0 {
            let (mut xf, mut vf) = (0.0, 0.0);
            for (i, (&x, &v)) in self.x.iter().zip(&self.v).enumerate() {
                let phi = if i % 2 == 0 { 2.0 } else { -2.0 };
                xf += phi * x;
                vf += phi * v;
            }
            let (c, width) = (m.felt_c_n_s_m.unwrap_or(0.0), m.felt_width.unwrap_or(1.0));
            let e = ((xf.abs() - self.gap) / (width * self.gap)).clamp(0.0, 1.0);
            gf = 2.0 * (-c * (e * e * (3.0 - 2.0 * e)) * vf);
        }
        let mut vh = 0.0;
        let mut y_adm = 0.0;
        for (i, (((s, xn), vn), (&x, &v))) in steps
            .iter()
            .zip(self.xn.iter_mut())
            .zip(self.vn.iter_mut())
            .zip(self.x.iter().zip(&self.v))
            .enumerate()
        {
            *xn = s[0] * x + s[1] * v;
            *vn = s[2] * x + s[3] * v;
            if gf != 0.0 {
                let phi = if i % 2 == 0 { 2.0 } else { -2.0 };
                *xn += s[4] * (phi * gf);
                *vn += s[5] * (phi * gf);
            }
            vh += 2.0 * *vn;
            y_adm += 2.0 * (2.0 * s[5]);
        }
        let f_prev = self.f_prev;
        let a = vh + y_adm * f_prev - self.wheel;
        let f_new = if fn_ <= 0.0 {
            0.0
        } else {
            let (ms, md) = (m.mu_s * rosin, m.mu_d * rosin);
            let f_stick = -a / y_adm;
            if f_stick.abs() <= ms * fn_ {
                f_stick
            } else {
                let v0 = m.v0_m_s;
                let yf = y_adm * fn_;
                let bb = a.abs() - yf * md;
                let c0 = v0 * (yf * (ms - md) - bb);
                let bq = v0 - bb;
                let u = 0.5 * (-bq + (bq * bq - 4.0 * c0).max(0.0).sqrt());
                let mu = md + (ms - md) * v0 / (v0 + u);
                -(fn_ * mu).copysign(a)
            }
        };
        let fsum = 2.0 * (f_prev + f_new);
        let mut pick = 0.0;
        for (i, ((s, x), v)) in steps
            .iter()
            .zip(self.x.iter_mut())
            .zip(self.v.iter_mut())
            .enumerate()
        {
            *x = self.xn[i] + s[4] * fsum;
            *v = self.vn[i] + s[5] * fsum;
            let phi = if i % 2 == 0 { 2.0 } else { -2.0 };
            pick += phi * *v;
        }
        self.f_prev = f_new;
        let [b0, b1, b2, a1, a2] = self.bp;
        let y = b0 * pick + b1 * self.bx1 + b2 * self.bx2 - a1 * self.by1 - a2 * self.by2;
        self.bx2 = self.bx1;
        self.bx1 = pick;
        self.by2 = self.by1;
        self.by1 = y;
        if self.damped {
            self.quiet += 1;
            if self.quiet >= self.sleep_n {
                self.awake = false;
            }
        }
        m.pickup_v_per_m_s * (pick + self.res_gain * y)
    }
}

// --- IL2 the Buzz Zither ----------------------------------------------------------------

#[derive(Debug, Clone, Deserialize)]
pub struct ZitherKey {
    pub note: u8,
    pub f_hz: f64,
    pub length_m: f64,
}

#[derive(Debug, Clone, Deserialize)]
pub struct ZitherModel {
    pub keys: Vec<ZitherKey>,
    pub rho_a_kg_m: f64,
    pub bridge_m: f64,
    pub drop_flat_m: f64,
    pub k_contact: f64,
    pub t60_low_s: f64,
    pub t60_high_s: f64,
    pub f_high_hz: f64,
    pub courant: f64,
    pub damper: f64,
    pub sleep_s: f64,
    pub force_range_n: [f64; 2],
    pub pluck_range: [f64; 2],
    pub drone_hz: Vec<Vec<f64>>,
    pub drone_length_m: Vec<Vec<f64>>,
    pub drone_pluck_at: Vec<f64>,
    pub drone_gap_s: f64,
    pub drone_force_n: f64,
    pub drone_steps: usize,
    pub soundboard: Vec<[f64; 3]>,
    pub v_per_n: f64,
}

const SAVGOL_9_2: [f64; 9] = [-21.0, 14.0, 39.0, 54.0, 59.0, 54.0, 39.0, 14.0, -21.0];

/// One string over the jawari (`zither.String`, step for step).
#[derive(Debug, Clone)]
pub struct JawariString {
    k: f64,
    rho_a: f64,
    bridge_m: f64,
    drop_flat_m: f64,
    k_contact: f64,
    t60_low_s: f64,
    t60_high_s: f64,
    f_high_hz: f64,
    courant: f64,
    damper: f64,
    jawari: f64,
    damped: bool,
    nx: usize,
    h: f64,
    length: f64,
    lam2: f64,
    s0_free: f64,
    bs: f64,
    t_n: f64,
    nb: usize,
    r2: Vec<f64>,
    b: Vec<f64>,
    c1: f64,
    a0: f64,
    kc: f64,
    u: Vec<f64>,
    u1: Vec<f64>,
    un: Vec<f64>,
    lap: Vec<f64>,
    lapp: Vec<f64>,
}

impl JawariString {
    fn new(m: &ZitherModel, fs: f64) -> JawariString {
        JawariString {
            k: 1.0 / fs,
            rho_a: m.rho_a_kg_m,
            bridge_m: m.bridge_m,
            drop_flat_m: m.drop_flat_m,
            k_contact: m.k_contact,
            t60_low_s: m.t60_low_s,
            t60_high_s: m.t60_high_s,
            f_high_hz: m.f_high_hz,
            courant: m.courant,
            damper: m.damper,
            jawari: 0.0,
            damped: true,
            nx: 0,
            h: 0.0,
            length: 0.0,
            lam2: 0.0,
            s0_free: 0.0,
            bs: 0.0,
            t_n: 0.0,
            nb: 0,
            r2: Vec::new(),
            b: Vec::new(),
            c1: 0.0,
            a0: 0.0,
            kc: 0.0,
            u: Vec::new(),
            u1: Vec::new(),
            un: Vec::new(),
            lap: Vec::new(),
            lapp: Vec::new(),
        }
    }

    /// The grid and losses for pitch `f_hz` over `length` (at rest). Within the buffers'
    /// capacity nothing is allocated (a drone string re-tuned upward has fewer points).
    fn tune(&mut self, f_hz: f64, length: f64) {
        let k = self.k;
        let c = 2.0 * length * f_hz;
        let h = c * k / self.courant;
        let nx = (length / h) as usize;
        let h = length / nx as f64;
        self.nx = nx;
        self.h = h;
        self.length = length;
        let lam = c * k / h;
        self.lam2 = lam * lam;
        let w1 = 2.0 * std::f64::consts::PI * f_hz;
        let w2 = 2.0 * std::f64::consts::PI * self.f_high_hz;
        let xi1 = (w1 / c) * (w1 / c);
        let xi2 = (w2 / c) * (w2 / c);
        let g = 6.0 * 10.0f64.ln() / (xi2 - xi1);
        let s1 = g * (1.0 / self.t60_high_s - 1.0 / self.t60_low_s);
        self.s0_free = g * (xi2 / self.t60_low_s - xi1 / self.t60_high_s);
        let s1 = s1.max(0.0);
        self.bs = 2.0 * s1 * k / (h * h);
        self.t_n = c * c * self.rho_a;
        self.nb = (self.bridge_m / h) as usize + 1;
        self.r2.clear();
        for i in 0..self.nb {
            let r = (i as f64 * h) / self.bridge_m;
            self.r2.push(r * r);
        }
        for v in [
            &mut self.u,
            &mut self.u1,
            &mut self.un,
            &mut self.lap,
            &mut self.lapp,
        ] {
            v.clear();
            v.resize(nx + 1, 0.0);
        }
        self.set_damped(self.damped);
        self.set_jawari(self.jawari);
    }

    fn set_damped(&mut self, damped: bool) {
        let k = self.k;
        self.damped = damped;
        let s0 = if damped {
            self.s0_free * self.damper
        } else {
            self.s0_free
        };
        self.c1 = 1.0 - s0 * k;
        self.a0 = 1.0 / (1.0 + s0 * k);
        self.kc = self.a0 * self.k_contact * k * k / self.rho_a;
    }

    fn set_jawari(&mut self, j: f64) {
        self.jawari = j;
        if j > 0.0 {
            let drop = self.drop_flat_m / j;
            self.b.clear();
            for &r2 in &self.r2 {
                self.b.push(-(drop * r2));
            }
        }
    }

    /// Released from the finger's rounded triangle (a 9-point Savitzky-Golay smoothing of
    /// it), held by `force_n` at `at` of the length, at rest.
    fn pluck(&mut self, force_n: f64, at: f64) {
        let (nx, h, length) = (self.nx, self.h, self.length);
        let amp_m = force_n * at * (1.0 - at) * length / self.t_n;
        let p = at * length;
        // the triangle in `lap` (scratch until the next step writes it)
        for i in 0..=nx {
            let x = i as f64 * h;
            self.lap[i] = if x < p {
                x / p
            } else {
                (length - x) / (length - p)
            };
        }
        for i in 0..=nx {
            self.u[i] = if i >= 4 && i + 4 <= nx {
                let mut s = 0.0;
                for (j, c) in SAVGOL_9_2.iter().enumerate() {
                    s += c * self.lap[i + j - 4];
                }
                amp_m * (s / 231.0)
            } else {
                amp_m * self.lap[i]
            };
        }
        self.u[0] = 0.0;
        self.u[nx] = 0.0;
        self.u1.copy_from_slice(&self.u);
        self.lapp[0] = 0.0;
        self.lapp[nx] = 0.0;
        for i in 1..nx {
            self.lapp[i] = (self.u[i + 1] - 2.0 * self.u[i]) + self.u[i - 1];
        }
    }

    /// One step: the force on the bridge (N).
    fn step(&mut self) -> f64 {
        let nx = self.nx;
        let (a0, c1, lam2, bs) = (self.a0, self.c1, self.lam2, self.bs);
        {
            let (u, u1, un, lap, lapp) =
                (&self.u, &self.u1, &mut self.un, &mut self.lap, &self.lapp);
            lap[0] = 0.0;
            lap[nx] = 0.0;
            un[0] = 0.0;
            un[nx] = 0.0;
            for i in 1..nx {
                let l = (u[i + 1] - 2.0 * u[i]) + u[i - 1];
                lap[i] = l;
                un[i] = a0 * (((2.0 * u[i] - c1 * u1[i]) + lam2 * l) + bs * (l - lapp[i]));
            }
        }
        let mut contact = 0.0;
        if self.jawari > 0.0 {
            let mut acc = 0.0;
            let kc = self.kc;
            for i in 1..self.nb {
                let free = self.un[i];
                let b = self.b[i];
                if free < b {
                    let fixed = (free + kc * b) / (1.0 + kc);
                    acc += b - fixed;
                    self.un[i] = fixed;
                }
            }
            contact = self.k_contact * self.h * acc;
        }
        // u1 <- u, u <- un, un <- the old u1 (scratch); lapp <- lap
        std::mem::swap(&mut self.u1, &mut self.u);
        std::mem::swap(&mut self.u, &mut self.un);
        std::mem::swap(&mut self.lapp, &mut self.lap);
        self.t_n * self.u[1] / self.h + contact
    }
}

/// One key's string, or one of the tanpura's (`zither.Voice`, step for step).
#[derive(Debug, Clone)]
pub struct ZitherVoice {
    m: Arc<Model>,
    /// None: a key; else the cam's string 0-3.
    drone: Option<usize>,
    string: JawariString,
    /// A drone string's DRONE TONIC step (None before the first tuning).
    step_tuned: Option<usize>,
    bp: Vec<[f64; 5]>,
    gain: Vec<f64>,
    st: Vec<[f64; 4]>,
    awake: bool,
    quiet: usize,
    sleep_n: usize,
    /// Samples since the pedal went down (None: the cam stopped).
    cam: Option<usize>,
    gap_n: usize,
    knobs: [f64; 4],
}

impl ZitherVoice {
    fn new(
        model: &Arc<Model>,
        fs: f64,
        knobs: [f64; 4],
        key: Option<&ZitherKey>,
        drone: Option<usize>,
    ) -> ZitherVoice {
        let Model::Zither(m) = &**model else {
            unreachable!("a zither voice on another model")
        };
        let mut v = ZitherVoice {
            m: model.clone(),
            drone,
            string: JawariString::new(m, fs),
            step_tuned: None,
            bp: m
                .soundboard
                .iter()
                .map(|b| bandpass(b[0], b[1], fs))
                .collect(),
            gain: m.soundboard.iter().map(|b| b[2]).collect(),
            st: vec![[0.0; 4]; m.soundboard.len()],
            awake: false,
            quiet: 0,
            sleep_n: (m.sleep_s * fs) as usize,
            cam: None,
            gap_n: (m.drone_gap_s * fs) as usize,
            knobs,
        };
        match key {
            Some(k) => v.string.tune(k.f_hz, k.length_m),
            None => v.retune(0),
        }
        v.set_knobs(knobs);
        v
    }

    /// A drone string tuned DRONE TONIC's `step` semitones up (re-strung at rest).
    fn retune(&mut self, step: usize) {
        if self.step_tuned != Some(step) {
            self.step_tuned = Some(step);
            let d = self.drone.expect("a drone string");
            let model = self.m.clone();
            let Model::Zither(m) = &*model else {
                unreachable!("a zither voice on another model")
            };
            self.string
                .tune(m.drone_hz[d][step], m.drone_length_m[d][step]);
        }
    }

    fn set_knobs(&mut self, k: [f64; 4]) {
        self.knobs = k;
        if k[0] != self.string.jawari {
            self.string.set_jawari(k[0]);
        }
    }

    fn wake(&mut self) {
        self.awake = true;
        self.quiet = 0;
        self.string.set_damped(false);
    }

    fn damp(&mut self) {
        if !self.string.damped {
            self.string.set_damped(true);
            self.quiet = 0;
        }
    }

    fn event(&mut self, ev: NoteEvent) {
        match ev {
            NoteEvent::On { velocity, .. } => {
                if self.drone.is_none() {
                    let Model::Zither(m) = &*self.m else {
                        unreachable!("a zither voice on another model")
                    };
                    let force = knob(m.force_range_n, velocity as f64 / 127.0);
                    let at = knob(m.pluck_range, self.knobs[1]);
                    self.string.pluck(force, at);
                    self.wake();
                }
            }
            NoteEvent::Off { .. } => {
                if self.drone.is_none() {
                    self.damp();
                }
            }
            NoteEvent::Pedal { down } => {
                if self.drone.is_some() {
                    if down && self.cam.is_none() {
                        self.cam = Some(0);
                        self.wake();
                    } else if !down && self.cam.is_some() {
                        self.cam = None;
                        self.damp();
                    }
                }
            }
            NoteEvent::Pressure { .. } => {}
        }
    }

    fn step(&mut self) -> f64 {
        let model = self.m.clone();
        let Model::Zither(m) = &*model else {
            unreachable!("a zither voice on another model")
        };
        if let (Some(cam), Some(d)) = (self.cam, self.drone) {
            let at = d * self.gap_n;
            if cam >= at && (cam - at).is_multiple_of(4 * self.gap_n) {
                let s = (self.knobs[3] * m.drone_steps as f64 + 0.5).floor();
                self.retune(s.clamp(0.0, m.drone_steps as f64) as usize);
                self.string
                    .pluck(self.knobs[2] * m.drone_force_n, m.drone_pluck_at[d]);
            }
            self.cam = Some(cam + 1);
        }
        let x = self.string.step();
        let mut y = x;
        for ((bp, s), g) in self.bp.iter().zip(self.st.iter_mut()).zip(&self.gain) {
            let [b0, b1, b2, a1, a2] = *bp;
            let yb = b0 * x + b1 * s[0] + b2 * s[1] - a1 * s[2] - a2 * s[3];
            s[1] = s[0];
            s[0] = x;
            s[3] = s[2];
            s[2] = yb;
            y += g * yb;
        }
        if self.string.damped {
            self.quiet += 1;
            if self.quiet >= self.sleep_n {
                self.awake = false;
            }
        }
        m.v_per_n * y
    }
}

// --- IL3 the Rijke Organ ----------------------------------------------------------------

#[derive(Debug, Clone, Deserialize)]
pub struct RijkeKey {
    pub note: u8,
    pub f_hz: f64,
    pub bore: f64,
}

#[derive(Debug, Clone, Deserialize)]
pub struct RijkeModel {
    pub keys: Vec<RijkeKey>,
    pub c_air_m_s: f64,
    pub modes: usize,
    pub tau: f64,
    pub c1: f64,
    pub c2: f64,
    pub gauze_s: f64,
    pub turbulence: f64,
    pub k_range: [f64; 2],
    pub k_pressure: f64,
    pub k_ref: f64,
    pub heat_range: [f64; 2],
    pub gauze_range: [f64; 2],
    pub breath_max: f64,
    pub breath_hz: f64,
    pub sleep_k: f64,
    pub sleep_energy: f64,
    pub mic_v: f64,
    pub seed: u64,
}

/// One key's pipe (`rijke.Voice`, step for step).
#[derive(Debug, Clone)]
pub struct RijkeVoice {
    m: Arc<Model>,
    fs: f64,
    p: Vec<[f64; 4]>,
    g: Vec<[f64; 2]>,
    buf: Vec<f64>,
    at: usize,
    eta: Vec<f64>,
    deta: Vec<f64>,
    ends: Vec<f64>,
    sf: Vec<f64>,
    cf: Vec<f64>,
    prev: f64,
    bore: f64,
    ag: f64,
    kg: f64,
    na: f64,
    norm: f64,
    nz: f64,
    gauss: Gauss,
    down: bool,
    pedal_down: bool,
    held: bool,
    velocity: f64,
    aftertouch: f64,
    awake: bool,
    x_f: f64,
    heat: f64,
    breath: f64,
}

impl RijkeVoice {
    fn new(model: &Arc<Model>, key: &RijkeKey, fs: f64, knobs: [f64; 4]) -> RijkeVoice {
        let Model::Rijke(m) = &**model else {
            unreachable!("a rijke voice on another model")
        };
        let pi = std::f64::consts::PI;
        let f1 = key.f_hz;
        let length = m.c_air_m_s / (2.0 * f1);
        let dt = (m.c_air_m_s / length) / fs;
        let n = m.modes;
        let w1 = pi;
        let mut p = Vec::with_capacity(n);
        let mut g = Vec::with_capacity(n);
        for j in 1..=n {
            let w = j as f64 * pi;
            let zeta = (m.c1 * w / w1 + m.c2 * (w1 / w).sqrt()) / (2.0 * pi);
            let wd = w * (1.0 - zeta * zeta).sqrt();
            let e = (-zeta * w * dt).exp();
            let (cs, sn) = ((wd * dt).cos(), (wd * dt).sin());
            let p00 = e * (cs + zeta * w / wd * sn);
            let p01 = e * sn / wd;
            let p10 = -e * w * w / wd * sn;
            let p11 = e * (cs - zeta * w / wd * sn);
            p.push([p00, p01, p10, p11]);
            g.push([(1.0 - p00) / (w * w), -p10 / (w * w)]);
        }
        let lag = ((m.tau / dt + 0.5).floor() as usize).max(1);
        let a = (-2.0 * pi * m.breath_hz / fs).exp();
        let mut v = RijkeVoice {
            m: model.clone(),
            fs,
            p,
            g,
            buf: vec![0.0; lag],
            at: 0,
            eta: vec![0.0; n],
            deta: vec![0.0; n],
            ends: (1..=n)
                .map(|j| if j % 2 == 1 { -2.0 } else { 0.0 })
                .collect(),
            sf: vec![0.0; n],
            cf: vec![0.0; n],
            prev: 0.0,
            bore: key.bore,
            ag: (-1.0 / (m.gauze_s * fs)).exp(),
            kg: 0.0,
            na: a,
            norm: ((1.0 + a) / (1.0 - a)).sqrt(),
            nz: 0.0,
            gauss: Gauss::new(key_seed(m.seed, key.note)),
            down: false,
            pedal_down: false,
            held: false,
            velocity: 0.0,
            aftertouch: 0.0,
            awake: false,
            x_f: -1.0,
            heat: 0.0,
            breath: 0.0,
        };
        v.set_knobs(knobs);
        v
    }

    fn set_knobs(&mut self, k: [f64; 4]) {
        let model = self.m.clone();
        let Model::Rijke(m) = &*model else {
            unreachable!("a rijke voice on another model")
        };
        self.heat = knob(m.heat_range, k[0]);
        let x_f = knob(m.gauze_range, k[1]);
        if x_f != self.x_f {
            self.x_f = x_f;
            let pi = std::f64::consts::PI;
            for (i, (s, c)) in self.sf.iter_mut().zip(self.cf.iter_mut()).enumerate() {
                let j = (i + 1) as f64;
                *s = (j * pi * x_f).sin();
                *c = (j * pi * x_f).cos();
            }
        }
        self.breath = m.breath_max * k[2];
    }

    fn event(&mut self, ev: NoteEvent) {
        match ev {
            NoteEvent::On { velocity, .. } => {
                self.down = true;
                self.held = true;
                self.velocity = velocity as f64 / 127.0;
                self.awake = true;
            }
            NoteEvent::Off { .. } => {
                self.down = false;
                self.held = self.pedal_down;
            }
            NoteEvent::Pedal { down } => {
                self.pedal_down = down;
                self.held = self.down || (down && self.held);
            }
            NoteEvent::Pressure { value } => self.aftertouch = value as f64 / 127.0,
        }
    }

    fn step(&mut self) -> f64 {
        let model = self.m.clone();
        let Model::Rijke(m) = &*model else {
            unreachable!("a rijke voice on another model")
        };
        let pi = std::f64::consts::PI;
        let mut k_in = 0.0;
        if self.held {
            k_in = self.heat * (knob(m.k_range, self.velocity) + m.k_pressure * self.aftertouch);
        }
        self.kg = (1.0 - self.ag) * k_in + self.ag * self.kg;
        self.nz = self.na * self.nz + (1.0 - self.na) * self.gauss.sample();
        let turb = m.turbulence * self.breath * self.nz * self.norm * self.kg / m.k_ref;
        let uf_late = self.buf[self.at];
        let q = self.kg * ((1.0 / 3.0 + uf_late).abs().sqrt() - (1.0f64 / 3.0).sqrt());
        let mut uf = 0.0;
        let mut out = 0.0;
        let mut energy = 0.0;
        for i in 0..self.eta.len() {
            let jp = (i + 1) as f64 * pi;
            let force = (-jp * q) * self.sf[i] + turb * self.sf[i];
            let [p00, p01, p10, p11] = self.p[i];
            let [g0, g1] = self.g[i];
            let (e, de) = (self.eta[i], self.deta[i]);
            let e2 = p00 * e + p01 * de + g0 * force;
            self.deta[i] = p10 * e + p11 * de + g1 * force;
            self.eta[i] = e2;
            uf += self.cf[i] * e2;
            out += self.ends[i] * e2;
            energy += e2 * e2;
        }
        self.buf[self.at] = uf;
        self.at = (self.at + 1) % self.buf.len();
        let y = (out - self.prev) * self.fs;
        self.prev = out;
        if !self.held && self.kg < m.sleep_k && energy < m.sleep_energy {
            self.awake = false;
        }
        m.mic_v * self.bore * y
    }
}

// --- IL4 the Aeolian Keyboard -----------------------------------------------------------

#[derive(Debug, Clone, Deserialize)]
pub struct AeolianKey {
    pub note: u8,
    pub f_hz: f64,
    pub d_m: f64,
    pub voicing: f64,
}

#[derive(Debug, Clone, Deserialize)]
pub struct AeolianModel {
    pub keys: Vec<AeolianKey>,
    pub rho_air: f64,
    pub st: f64,
    pub cl0: f64,
    pub a_wake: f64,
    pub eps_wake: f64,
    pub rho_gut: f64,
    pub length_m: f64,
    pub q_string: f64,
    pub inharm_b: f64,
    pub segments: usize,
    pub f_top_hz: f64,
    pub max_harmonic: usize,
    pub attack_s: f64,
    pub release_s: f64,
    pub open_min: f64,
    pub pressure_open: f64,
    pub q_damped: f64,
    pub sleep_s: f64,
    pub wind_range_m_s: [f64; 2],
    pub gust_range: [f64; 2],
    pub gust_hz: f64,
    pub turb: f64,
    pub turb_hz: f64,
    pub turb_every: usize,
    pub q0: f64,
    pub omh_max: f64,
    pub v_per_n: f64,
    pub seed: u64,
}

/// The chest's gust lattice: a Gaussian per index (`aeolian.lattice`).
fn gust_lattice(seed: u64, i: u64) -> f64 {
    let mut g = Gauss::new(seed ^ i.wrapping_mul(0xD1B54A32D192ED03));
    let (u, v) = (g.uniform(), g.uniform());
    (-2.0 * u.ln()).sqrt() * (2.0 * std::f64::consts::PI * v).cos()
}

/// The chest's gust at absolute sample t, shared by every string (`aeolian.Chest`).
#[derive(Debug, Clone)]
struct Chest {
    seed: u64,
    per: f64,
    i: i64,
    a: f64,
    b: f64,
}

impl Chest {
    fn at(&mut self, t: usize) -> f64 {
        let x = t as f64 / self.per;
        let i = x.floor();
        if i as i64 != self.i {
            self.i = i as i64;
            self.a = gust_lattice(self.seed, i as u64);
            self.b = gust_lattice(self.seed, i as u64 + 1);
        }
        let s = x - i;
        let s = s * s * (3.0 - 2.0 * s);
        self.a + (self.b - self.a) * s
    }
}

/// Per mode [p00, p01, p10, p11, g0, g1, zeta]: the exact damped step, the force held
/// (`aeolian.tables`).
fn aeolian_tables(
    m: &AeolianModel,
    f: &[f64],
    f1: f64,
    h: f64,
    mass: f64,
    q_cap: f64,
) -> Vec<[f64; 7]> {
    f.iter()
        .map(|&fk| {
            let w = 2.0 * std::f64::consts::PI * fk;
            let zeta = 1.0 / (2.0 * m.q_string) * (fk / f1).sqrt().sqrt();
            let zeta = zeta.max(1.0 / (2.0 * q_cap));
            let wd = w * (1.0 - zeta * zeta).sqrt();
            let e = (-zeta * w * h).exp();
            let (cs, sn) = ((wd * h).cos(), (wd * h).sin());
            let p00 = e * (cs + zeta * w / wd * sn);
            let p01 = e * sn / wd;
            let p10 = -e * w * w / wd * sn;
            let p11 = e * (cs - zeta * w / wd * sn);
            [
                p00,
                p01,
                p10,
                p11,
                (1.0 - p00) / (w * w) / mass,
                -p10 / (w * w) / mass,
                zeta,
            ]
        })
        .collect()
}

/// One key's string (`aeolian.Voice`, step for step).
#[derive(Debug, Clone)]
pub struct AeolianVoice {
    m: Arc<Model>,
    h: f64,
    d: f64,
    voicing: f64,
    free: Vec<[f64; 7]>,
    damped_t: Vec<[f64; 7]>,
    seg_len: f64,
    /// shape[s][k], segments x modes
    shape: Vec<Vec<f64>>,
    slope: Vec<f64>,
    w: Vec<f64>,
    w2: Vec<f64>,
    mass: f64,
    x: Vec<f64>,
    v: Vec<f64>,
    force: Vec<f64>,
    acc: Vec<f64>,
    gauss: Gauss,
    q: Vec<f64>,
    p: Vec<f64>,
    nz: Vec<f64>,
    lift: Vec<f64>,
    om: Vec<f64>,
    na: f64,
    norm: f64,
    tick: usize,
    chest: Chest,
    slot: f64,
    down: bool,
    pedal_down: bool,
    held: bool,
    velocity: f64,
    aftertouch: f64,
    damped: bool,
    quiet: usize,
    awake: bool,
    sleep_n: usize,
    /// The internal sample the chunk being rendered starts at, and the next step's.
    chunk0: usize,
    now: usize,
    wind: f64,
    gust: f64,
}

impl AeolianVoice {
    fn new(model: &Arc<Model>, key: &AeolianKey, fs: f64, knobs: [f64; 4]) -> AeolianVoice {
        let Model::Aeolian(m) = &**model else {
            unreachable!("an aeolian voice on another model")
        };
        let pi = std::f64::consts::PI;
        let h = 1.0 / fs;
        let (f1, d, length) = (key.f_hz, key.d_m, m.length_m);
        let mu = m.rho_gut * pi * d * d / 4.0;
        let tension = (2.0 * length * f1) * (2.0 * length * f1) * mu;
        let mut f = Vec::new();
        for k in 1..=m.max_harmonic {
            let kf = k as f64;
            let fk = kf * f1 * (1.0 + m.inharm_b * kf * kf).sqrt();
            if fk < m.f_top_hz {
                f.push(fk);
            }
        }
        let nk = f.len();
        let mass = mu * length / 2.0;
        let ns = m.segments;
        let shape: Vec<Vec<f64>> = (0..ns)
            .map(|s| {
                let z = (0.15 + s as f64 * (0.7 / (ns - 1) as f64)) * length;
                (0..nk)
                    .map(|k| (z * (k + 1) as f64 * pi / length).sin())
                    .collect()
            })
            .collect();
        let w: Vec<f64> = f.iter().map(|&fk| 2.0 * pi * fk).collect();
        let mut gauss = Gauss::new(key_seed(m.seed, key.note));
        let q: Vec<f64> = (0..ns).map(|_| m.q0 * gauss.sample()).collect();
        let a = (-2.0 * pi * m.turb_hz * m.turb_every as f64 / fs).exp();
        let mut v = AeolianVoice {
            m: model.clone(),
            h,
            d,
            voicing: key.voicing,
            free: aeolian_tables(m, &f, f1, h, mass, 1e300),
            damped_t: aeolian_tables(m, &f, f1, h, mass, m.q_damped),
            seg_len: 0.7 * length / ns as f64,
            shape,
            slope: (0..nk)
                .map(|k| tension * (k + 1) as f64 * pi / length)
                .collect(),
            w2: w.iter().map(|w| w * w).collect(),
            w,
            mass,
            x: vec![0.0; nk],
            v: vec![0.0; nk],
            force: vec![0.0; nk],
            acc: vec![0.0; nk],
            gauss,
            q,
            p: vec![0.0; ns],
            nz: vec![0.0; ns],
            lift: vec![0.0; ns],
            om: vec![0.0; ns],
            na: a,
            norm: ((1.0 + a) / (1.0 - a)).sqrt(),
            tick: 0,
            chest: Chest {
                seed: m.seed,
                per: fs / (2.0 * m.gust_hz),
                i: -1,
                a: 0.0,
                b: 0.0,
            },
            slot: 0.0,
            down: false,
            pedal_down: false,
            held: false,
            velocity: 0.0,
            aftertouch: 0.0,
            damped: true,
            quiet: 0,
            awake: false,
            sleep_n: (m.sleep_s * fs) as usize,
            chunk0: 0,
            now: 0,
            wind: 0.0,
            gust: 0.0,
        };
        v.set_knobs(knobs);
        v
    }

    fn set_knobs(&mut self, k: [f64; 4]) {
        let Model::Aeolian(m) = &*self.m else {
            unreachable!("an aeolian voice on another model")
        };
        let (wind, gust) = (knob(m.wind_range_m_s, k[0]), knob(m.gust_range, k[1]));
        self.wind = wind;
        self.gust = gust;
    }

    fn event(&mut self, ev: NoteEvent) {
        match ev {
            NoteEvent::On { velocity, .. } => {
                self.down = true;
                self.held = true;
                self.velocity = velocity as f64 / 127.0;
                self.awake = true;
                self.damped = false;
                self.quiet = 0;
            }
            NoteEvent::Off { .. } => {
                self.down = false;
                self.held = self.pedal_down;
            }
            NoteEvent::Pedal { down } => {
                self.pedal_down = down;
                self.held = self.down || (down && self.held);
            }
            NoteEvent::Pressure { value } => self.aftertouch = value as f64 / 127.0,
        }
    }

    // The modes' and segments' arrays are indexed together, in the reference's order.
    #[allow(clippy::needless_range_loop)]
    fn step(&mut self) -> f64 {
        let model = self.m.clone();
        let Model::Aeolian(m) = &*model else {
            unreachable!("an aeolian voice on another model")
        };
        let pi = std::f64::consts::PI;
        if self.held {
            self.slot = (self.slot + self.h / m.attack_s).min(1.0);
        } else {
            self.slot = (self.slot - self.h / m.release_s).max(0.0);
            if self.slot == 0.0 && !self.damped {
                self.damped = true;
                self.quiet = 0;
            }
        }
        let sl = self.slot;
        let shape_s = sl * sl * (3.0 - 2.0 * sl);
        let o_v = knob([m.open_min, 1.0], self.velocity);
        let opening = o_v + (1.0 - o_v) * m.pressure_open * self.aftertouch;
        let chest = 1.0 + self.gust * self.chest.at(self.now);
        self.now += 1;
        let u0 = self.wind * chest * shape_s;
        let draw = self.tick == 0;
        self.tick = (self.tick + 1) % m.turb_every;
        for s in 0..self.q.len() {
            if draw {
                self.nz[s] = self.na * self.nz[s] + (1.0 - self.na) * self.gauss.sample();
            }
            let u = u0 * (1.0 + m.turb * self.nz[s] * self.norm);
            self.om[s] = 2.0 * pi * m.st * u / self.d;
            self.lift[s] =
                0.25 * m.rho_air * u * u * self.d * m.cl0 * self.q[s] * self.seg_len * opening;
        }
        let t = if self.damped {
            &self.damped_t
        } else {
            &self.free
        };
        let nk = self.x.len();
        for k in 0..nk {
            self.force[k] = 0.0;
        }
        for (row, &l) in self.shape.iter().zip(&self.lift) {
            for (f, &sh) in self.force.iter_mut().zip(row) {
                *f += sh * l;
            }
        }
        for k in 0..nk {
            self.acc[k] = (self.force[k] / self.mass - 2.0 * t[k][6] * self.w[k] * self.v[k])
                - self.w2[k] * self.x[k];
        }
        for s in 0..self.q.len() {
            let mut yacc = 0.0;
            for (&sh, &a) in self.shape[s].iter().zip(&self.acc) {
                yacc += sh * a;
            }
            let (mut q, mut p, o) = (self.q[s], self.p[s], self.om[s]);
            let nsub = ((o * self.h / m.omh_max).ceil() as usize).max(1);
            let hs = self.h / nsub as f64;
            let drive = m.a_wake / self.d * yacc;
            for _ in 0..nsub {
                p += hs * ((-m.eps_wake * o * (q * q - 1.0) * p - o * o * q) + drive);
                q += hs * p;
            }
            self.p[s] = p;
            self.q[s] = q;
        }
        let mut out = 0.0;
        for k in 0..nk {
            let (x, v, f) = (self.x[k], self.v[k], self.force[k]);
            let r = &t[k];
            self.x[k] = (r[0] * x + r[1] * v) + r[4] * f;
            self.v[k] = (r[2] * x + r[3] * v) + r[5] * f;
            out += self.slope[k] * self.x[k];
        }
        if self.damped {
            self.quiet += 1;
            if self.quiet >= self.sleep_n {
                self.awake = false;
            }
        }
        m.v_per_n * self.voicing * out
    }
}

// --- IL5 the Bubble Organ ---------------------------------------------------------------

#[derive(Debug, Clone, Deserialize)]
pub struct BubbleKey {
    pub note: u8,
    pub f_hz: f64,
    pub r_m: f64,
    pub depth_m: f64,
    pub voicing: f64,
}

#[derive(Debug, Clone, Deserialize)]
pub struct BubbleModel {
    pub keys: Vec<BubbleKey>,
    pub gamma: f64,
    pub rho_w: f64,
    pub c_w: f64,
    pub p_atm: f64,
    pub rise_m_s: f64,
    pub thermal_delta_3mm: f64,
    pub size_spread: f64,
    pub rate_jitter: f64,
    pub pop_level: f64,
    pub slots: usize,
    pub q_range: [f64; 2],
    pub q_pressure: f64,
    pub flow_range: [f64; 2],
    pub rate_range_hz: [f64; 2],
    pub depth_range: [f64; 2],
    pub attack_s: f64,
    pub life_max_s: f64,
    pub pop_s: f64,
    pub pop_decay_s: f64,
    pub pop_hz: f64,
    pub pop_q: f64,
    pub pop_gain: f64,
    pub interval_min_s: f64,
    pub hydrophone_v: f64,
    pub seed: u64,
}

/// One bubble's state (`bubbles.Bubble`).
#[derive(Debug, Clone)]
struct Bubble {
    r: f64,
    depth: f64,
    f0: f64,
    amp: f64,
    n_ring: usize,
    k_pop: usize,
    n_pop: usize,
    n_life: usize,
    d1: f64,
    d2: f64,
    e1: f64,
    e2: f64,
    ph: f64,
    pe: f64,
    pd: f64,
    bx1: f64,
    bx2: f64,
    by1: f64,
    by2: f64,
    i: usize,
}

impl Bubble {
    fn new(m: &BubbleModel, r: f64, depth: f64, amp: f64, fs: f64) -> Bubble {
        let pi = std::f64::consts::PI;
        let p = m.p_atm + m.rho_w * 9.81 * depth;
        let f0 = (3.0 * m.gamma * p / m.rho_w).sqrt() / (2.0 * pi * r);
        let delta = 2.0 * pi * f0 * r / m.c_w + m.thermal_delta_3mm * (3e-3 / r).sqrt();
        let tau = 1.0 / (pi * delta * f0);
        let n_ring = ((7.0 * tau).min(m.life_max_s) * fs) as usize;
        let k_pop = ((depth - r) / m.rise_m_s * fs) as usize;
        let n_pop = (m.pop_s * fs) as usize;
        Bubble {
            r,
            depth,
            f0,
            amp,
            n_ring,
            k_pop,
            n_pop,
            n_life: n_ring.max(k_pop + n_pop),
            d1: (-1.0 / (tau * fs)).exp(),
            d2: (-1.0 / (tau * fs) - 1.0 / (m.attack_s * fs)).exp(),
            e1: 1.0,
            e2: 1.0,
            ph: 0.0,
            pe: 1.0,
            pd: (-1.0 / (m.pop_decay_s * fs)).exp(),
            bx1: 0.0,
            bx2: 0.0,
            by1: 0.0,
            by2: 0.0,
            i: 0,
        }
    }
}

/// One key's nozzle (`bubbles.Voice`, step for step).
#[derive(Debug, Clone)]
pub struct BubbleVoice {
    m: Arc<Model>,
    fs: f64,
    r_key: f64,
    depth_key: f64,
    voicing: f64,
    slots: Vec<Option<Bubble>>,
    bp: [f64; 5],
    gauss: Gauss,
    down: bool,
    pedal_down: bool,
    held: bool,
    pending: bool,
    velocity: f64,
    aftertouch: f64,
    next_n: i64,
    awake: bool,
    held_mode: bool,
    flow: f64,
    rate: f64,
    depth_scale: f64,
}

impl BubbleVoice {
    fn new(model: &Arc<Model>, key: &BubbleKey, fs: f64, knobs: [f64; 4]) -> BubbleVoice {
        let Model::Bubble(m) = &**model else {
            unreachable!("a bubble voice on another model")
        };
        let mut v = BubbleVoice {
            m: model.clone(),
            fs,
            r_key: key.r_m,
            depth_key: key.depth_m,
            voicing: key.voicing,
            slots: vec![None; m.slots],
            bp: bandpass(m.pop_hz, m.pop_q, fs),
            gauss: Gauss::new(key_seed(m.seed, key.note)),
            down: false,
            pedal_down: false,
            held: false,
            pending: false,
            velocity: 0.0,
            aftertouch: 0.0,
            next_n: 0,
            awake: false,
            held_mode: false,
            flow: 0.0,
            rate: 0.0,
            depth_scale: 0.0,
        };
        v.set_knobs(knobs);
        v
    }

    fn set_knobs(&mut self, k: [f64; 4]) {
        let Model::Bubble(m) = &*self.m else {
            unreachable!("a bubble voice on another model")
        };
        let (flow, rate, depth) = (
            knob(m.flow_range, k[1]),
            knob(m.rate_range_hz, k[2]),
            knob(m.depth_range, k[3]),
        );
        self.held_mode = k[0] >= 0.5;
        self.flow = flow;
        self.rate = rate;
        self.depth_scale = depth;
    }

    fn event(&mut self, ev: NoteEvent) {
        match ev {
            NoteEvent::On { velocity, .. } => {
                self.down = true;
                self.held = true;
                self.velocity = velocity as f64 / 127.0;
                self.awake = true;
                self.pending = true;
                self.next_n = 0;
            }
            NoteEvent::Off { .. } => {
                self.down = false;
                self.held = self.pedal_down;
            }
            NoteEvent::Pedal { down } => {
                self.pedal_down = down;
                self.held = self.down || (down && self.held);
            }
            NoteEvent::Pressure { value } => self.aftertouch = value as f64 / 127.0,
        }
    }

    fn emit(&mut self, m: &BubbleModel, q: f64, amp: f64) {
        let r = self.r_key * q.powf(0.4) * (m.size_spread * self.gauss.sample()).exp();
        let depth = self.depth_key * self.depth_scale;
        let b = Bubble::new(m, r, depth.max(1.2 * r), amp, self.fs);
        let mut free = None;
        let mut oldest = 0;
        for (j, s) in self.slots.iter().enumerate() {
            match s {
                None => {
                    free = Some(j);
                    break;
                }
                Some(s) => {
                    if s.i > self.slots[oldest].as_ref().map_or(0, |o| o.i) {
                        oldest = j;
                    }
                }
            }
        }
        self.slots[free.unwrap_or(oldest)] = Some(b);
    }

    fn step(&mut self) -> f64 {
        let model = self.m.clone();
        let Model::Bubble(m) = &*model else {
            unreachable!("a bubble voice on another model")
        };
        let q = self.flow * (knob(m.q_range, self.velocity) + m.q_pressure * self.aftertouch);
        if self.held_mode {
            if self.held {
                if self.next_n <= 0 {
                    self.emit(m, q, 1.0);
                    let iv = 1.0 / (self.rate * q.powf(0.8))
                        * (1.0 + m.rate_jitter * self.gauss.sample());
                    self.next_n = (iv.max(m.interval_min_s) * self.fs) as i64;
                }
                self.next_n -= 1;
            }
            self.pending = false;
        } else if self.pending {
            self.emit(m, q, 0.5 + self.velocity);
            self.pending = false;
        }
        let mut y = 0.0;
        let mut sounding = false;
        let two_pi_fs = 2.0 * std::f64::consts::PI / self.fs;
        let [b0, b1, b2, a1, a2] = self.bp;
        for slot in self.slots.iter_mut() {
            let Some(b) = slot else { continue };
            let i = b.i;
            if i < b.n_ring {
                let t = i as f64 / self.fs;
                let h = (b.depth - m.rise_m_s * t).max(1.2 * b.r);
                let f = b.f0 / (1.0 - b.r / (2.0 * h)).sqrt();
                b.ph += two_pi_fs * f;
                y += b.amp * b.r * (b.e1 - b.e2) * b.ph.sin();
                b.e1 *= b.d1;
                b.e2 *= b.d2;
            }
            if b.k_pop <= i && i < b.k_pop + b.n_pop {
                let x = self.gauss.sample() * b.pe;
                b.pe *= b.pd;
                let yb = b0 * x + b1 * b.bx1 + b2 * b.bx2 - a1 * b.by1 - a2 * b.by2;
                b.bx2 = b.bx1;
                b.bx1 = x;
                b.by2 = b.by1;
                b.by1 = yb;
                y += m.pop_level * b.r * m.pop_gain * b.amp * yb;
            }
            b.i = i + 1;
            if b.i >= b.n_life {
                *slot = None;
            } else {
                sounding = true;
            }
        }
        if !(sounding || self.pending || (self.held_mode && self.held)) {
            self.awake = false;
        }
        m.hydrophone_v * self.voicing * y
    }
}

// --- IL6 the Siren Organ ----------------------------------------------------------------

#[derive(Debug, Clone, Deserialize)]
pub struct SirenKey {
    pub note: u8,
    pub holes: f64,
    pub f_hz: f64,
    pub area_m2: f64,
    pub phase: f64,
}

#[derive(Debug, Clone, Deserialize)]
pub struct SirenModel {
    pub keys: Vec<SirenKey>,
    pub shaft_hz: f64,
    pub rho: f64,
    pub cd: f64,
    pub p_max_pa: f64,
    pub blower_q_m3_s: f64,
    pub bellows_m3_pa: f64,
    pub motor_slope: f64,
    pub friction: f64,
    pub key_drag: f64,
    pub inertia: f64,
    pub chamber_q: f64,
    pub jet_noise: f64,
    pub jet_noise_hz: f64,
    pub noise_ref_holes: f64,
    pub duty: [f64; 2],
    pub mean_open: [f64; 2],
    pub open_range: [f64; 2],
    pub valve_open_s: f64,
    pub valve_close_s: f64,
    pub speed_octaves: f64,
    pub wind_range: [f64; 2],
    pub motor_octaves: f64,
    pub hunt_hz: f64,
    pub hunt_depth: f64,
    pub wander: f64,
    pub wander_hz: f64,
    pub tail_s: f64,
    pub mic_r_m: f64,
    pub mic_v_per_pa: f64,
    pub seed: u64,
    pub wander_seed: u64,
}

/// A key's valve (`siren.Valve`): the voice and the shaft each keep one, moved by the same
/// events.
#[derive(Debug, Clone)]
struct Valve {
    up: f64,
    dn: f64,
    open_range: [f64; 2],
    v: f64,
    down: bool,
    pedal_down: bool,
    held: bool,
    opening: f64,
    after: f64,
}

impl Valve {
    fn new(m: &SirenModel, fs: f64) -> Valve {
        Valve {
            up: 1.0 / (m.valve_open_s * fs),
            dn: 1.0 / (m.valve_close_s * fs),
            open_range: m.open_range,
            v: 0.0,
            down: false,
            pedal_down: false,
            held: false,
            opening: 0.0,
            after: 0.0,
        }
    }

    fn event(&mut self, ev: NoteEvent) {
        match ev {
            NoteEvent::On { velocity, .. } => {
                self.down = true;
                self.held = true;
                self.opening = knob(self.open_range, velocity as f64 / 127.0);
            }
            NoteEvent::Off { .. } => {
                self.down = false;
                self.held = self.pedal_down;
            }
            NoteEvent::Pedal { down } => {
                self.pedal_down = down;
                self.held = self.down || (down && self.held);
            }
            NoteEvent::Pressure { value } => self.after = value as f64 / 127.0,
        }
    }

    fn target(&self) -> f64 {
        if self.held {
            self.opening + (1.0 - self.opening) * self.after
        } else {
            0.0
        }
    }

    fn step(&mut self) -> f64 {
        let t = self.target();
        if self.v < t {
            self.v = (self.v + self.up).min(t);
        } else if self.v > t {
            self.v = (self.v - self.dn).max(t);
        }
        self.v
    }
}

/// The motor, the bellows and the shaft's angle, shared by every key (`siren.Shaft`, step
/// for step): stepped per chunk on the calling thread before the voices render
/// ([`crate::keyed::KeyVoice::prepare`]), from the chunk's events, into per-sample buffers
/// the voices read. It depends only on the valves, so the coupling is exact.
#[derive(Debug)]
pub struct Shaft {
    m: Arc<Model>,
    fs: f64,
    dt: f64,
    /// Per key in note order: its valve and its ring's area.
    valves: Vec<Valve>,
    area: Vec<f64>,
    by_note: [Option<usize>; 128],
    wander: Chest,
    w: f64,
    p: f64,
    rev: f64,
    /// Per internal sample of the chunk: the shaft's angle (revolutions, 0-1) and the jet's
    /// speed (m/s).
    rev_buf: Vec<f64>,
    jet_buf: Vec<f64>,
}

/// The panel's values the shaft reads.
struct ShaftPanel {
    lever: f64,
    stop: usize,
    p_max: f64,
    motor: f64,
    w_nl: f64,
}

fn shaft_panel(m: &SirenModel, k: [f64; 4]) -> ShaftPanel {
    let lever = 2f64.powf(m.speed_octaves * (2.0 * k[0] - 1.0));
    let stop = usize::from(k[1] >= 0.5);
    let p_max = m.p_max_pa * knob(m.wind_range, k[2]);
    let motor = m.motor_slope * 2f64.powf(m.motor_octaves * (2.0 * k[3] - 1.0));
    let w_nl = m.shaft_hz * (motor + m.friction + m.key_drag) / motor;
    ShaftPanel {
        lever,
        stop,
        p_max,
        motor,
        w_nl,
    }
}

impl Shaft {
    fn new(model: &Arc<Model>, fs: f64, knobs: [f64; 4]) -> Shaft {
        let Model::Siren(m) = &**model else {
            unreachable!("a shaft on another model")
        };
        let mut by_note = [None; 128];
        for (i, k) in m.keys.iter().enumerate() {
            by_note[k.note as usize] = Some(i);
        }
        let pn = shaft_panel(m, knobs);
        let p = pn.p_max;
        Shaft {
            m: model.clone(),
            fs,
            dt: 1.0 / fs,
            valves: m.keys.iter().map(|_| Valve::new(m, fs)).collect(),
            area: m.keys.iter().map(|k| k.area_m2).collect(),
            by_note,
            wander: Chest {
                seed: m.wander_seed,
                per: fs / (2.0 * m.wander_hz),
                i: -1,
                a: 0.0,
                b: 0.0,
            },
            w: pn.w_nl * pn.lever * pn.motor / (pn.motor + m.friction),
            p,
            rev: 0.0,
            rev_buf: Vec::new(),
            jet_buf: Vec::new(),
        }
    }

    fn event(&mut self, ev: NoteEvent) {
        match ev {
            NoteEvent::On { note, .. } | NoteEvent::Off { note } => {
                if let Some(i) = self.by_note[note as usize & 127] {
                    self.valves[i].event(ev);
                }
            }
            NoteEvent::Pedal { .. } | NoteEvent::Pressure { .. } => {
                for v in &mut self.valves {
                    v.event(ev);
                }
            }
        }
    }

    /// Internal samples `start .. start + n` (absolute), `events` at their offsets: each
    /// sample's events, then its step.
    fn prepare(&mut self, knobs: [f64; 4], start: usize, n: usize, events: &[(usize, NoteEvent)]) {
        let model = self.m.clone();
        let Model::Siren(m) = &*model else {
            unreachable!("a shaft on another model")
        };
        let pn = shaft_panel(m, knobs);
        let mo = m.mean_open[pn.stop];
        let two_pi = 2.0 * std::f64::consts::PI;
        self.rev_buf.clear();
        self.jet_buf.clear();
        let mut e = 0;
        for i in 0..n {
            while e < events.len() && events[e].0 <= i {
                self.event(events[e].1);
                e += 1;
            }
            let mut open_sum = 0.0;
            let mut draw = 0.0;
            for (v, a) in self.valves.iter_mut().zip(&self.area) {
                let x = v.step();
                if x > 0.0 {
                    open_sum += x;
                    draw += mo * x * a;
                }
            }
            let drag = m.friction + m.key_drag * open_sum;
            self.w +=
                self.dt / m.inertia * (pn.motor * (pn.w_nl * pn.lever - self.w) - drag * self.w);
            let q_out = m.cd * draw * (2.0 * self.p / m.rho).sqrt();
            let q_in = m.blower_q_m3_s * (1.0 - self.p / pn.p_max);
            self.p = (self.p + self.dt / m.bellows_m3_pa * (q_in - q_out))
                .max(1.0)
                .min(pn.p_max);
            let t = start + i;
            let hunt = 1.0
                + m.hunt_depth * (two_pi * m.hunt_hz * t as f64 / self.fs).sin()
                + m.wander * self.wander.at(t);
            self.rev += self.w * hunt * self.dt;
            self.rev -= self.rev.floor();
            self.rev_buf.push(self.rev);
            self.jet_buf.push((2.0 * self.p / m.rho).sqrt());
        }
    }
}

/// The FLUTE's Helmholtz chamber wn^2 / (s^2 + wn / Q s + wn^2), bilinear (`siren.chamber`).
fn siren_chamber(f_hz: f64, q: f64, fs: f64) -> [f64; 5] {
    let wn = 2.0 * std::f64::consts::PI * f_hz;
    let k = 2.0 * fs;
    let k2 = k * k;
    let w2 = wn * wn;
    let a0 = k2 + wn * k / q + w2;
    [
        w2 / a0,
        2.0 * w2 / a0,
        w2 / a0,
        (2.0 * w2 - 2.0 * k2) / a0,
        (k2 - wn * k / q + w2) / a0,
    ]
}

/// One key's ring (`siren.Voice`, step for step): it reads the shaft's buffers.
#[derive(Debug, Clone)]
pub struct SirenVoice {
    m: Arc<Model>,
    holes: f64,
    phase: f64,
    area: f64,
    valve: Valve,
    ch: [f64; 5],
    gauss: Gauss,
    na: f64,
    norm: f64,
    gain: f64,
    tail_n: usize,
    awake: bool,
    quiet: usize,
    nz: f64,
    nz1: f64,
    x1: f64,
    x2: f64,
    y1: f64,
    y2: f64,
    u1: f64,
    stop: usize,
}

impl SirenVoice {
    fn new(model: &Arc<Model>, key: &SirenKey, fs: f64, knobs: [f64; 4]) -> SirenVoice {
        let Model::Siren(m) = &**model else {
            unreachable!("a siren voice on another model")
        };
        let pi = std::f64::consts::PI;
        let band = m.jet_noise_hz * key.holes / m.noise_ref_holes;
        let a = (-2.0 * pi * band / fs).exp();
        let norm = 1.0 / ((1.0 - a).powf(4.0) * (1.0 + a * a) / (1.0 - a * a).powf(3.0)).sqrt();
        let mut v = SirenVoice {
            m: model.clone(),
            holes: key.holes,
            phase: key.phase,
            area: key.area_m2,
            valve: Valve::new(m, fs),
            ch: siren_chamber(key.f_hz, m.chamber_q, fs),
            gauss: Gauss::new(key_seed(m.seed, key.note)),
            na: a,
            norm,
            gain: m.mic_v_per_pa * m.rho / (4.0 * pi * m.mic_r_m) * fs,
            tail_n: (m.tail_s * fs) as usize,
            awake: false,
            quiet: 0,
            nz: 0.0,
            nz1: 0.0,
            x1: 0.0,
            x2: 0.0,
            y1: 0.0,
            y2: 0.0,
            u1: 0.0,
            stop: 0,
        };
        v.set_knobs(knobs);
        v
    }

    fn reset(&mut self) {
        self.nz = 0.0;
        self.nz1 = 0.0;
        self.x1 = 0.0;
        self.x2 = 0.0;
        self.y1 = 0.0;
        self.y2 = 0.0;
        self.u1 = 0.0;
    }

    fn set_knobs(&mut self, k: [f64; 4]) {
        self.stop = usize::from(k[1] >= 0.5);
    }

    fn event(&mut self, ev: NoteEvent) {
        if matches!(ev, NoteEvent::On { .. }) {
            self.awake = true;
            self.quiet = 0;
        }
        self.valve.event(ev);
    }

    /// One sample at the shaft's angle `rev` and the jet's speed `jet`.
    fn step(&mut self, rev: f64, jet: f64) -> f64 {
        let model = self.m.clone();
        let Model::Siren(m) = &*model else {
            unreachable!("a siren voice on another model")
        };
        let v = self.valve.step();
        let x = self.holes * rev + self.phase;
        let f = x - x.floor();
        let dist = f.min(1.0 - f);
        let xx = (dist / m.duty[self.stop]).min(1.0);
        let open = (2.0 * xx.acos() - 2.0 * xx * (1.0 - xx * xx).sqrt()) / std::f64::consts::PI;
        let mut q = m.cd * self.area * open * jet * v;
        self.nz1 = self.na * self.nz1 + (1.0 - self.na) * self.gauss.sample();
        self.nz = self.na * self.nz + (1.0 - self.na) * self.nz1;
        q += m.jet_noise * q * (self.nz * self.norm);
        let u = if self.stop == 0 {
            let [b0, b1, b2, a1, a2] = self.ch;
            let u = b0 * q + b1 * self.x1 + b2 * self.x2 - a1 * self.y1 - a2 * self.y2;
            self.x2 = self.x1;
            self.x1 = q;
            self.y2 = self.y1;
            self.y1 = u;
            u
        } else {
            q
        };
        let y = self.gain * (u - self.u1);
        self.u1 = u;
        if v == 0.0 && self.valve.target() == 0.0 {
            self.quiet += 1;
            if self.quiet >= self.tail_n {
                self.awake = false;
                self.reset();
            }
        } else {
            self.quiet = 0;
        }
        y
    }
}

// --- the keyboard -----------------------------------------------------------------------

/// The panel every key reads, set between chunks ([`Medium::update`]).
#[derive(Debug)]
pub struct Knobs([AtomicU64; 4]);

impl Knobs {
    fn new(k: [f64; 4]) -> Knobs {
        Knobs(k.map(|x| AtomicU64::new(x.to_bits())))
    }

    fn get(&self) -> [f64; 4] {
        [0, 1, 2, 3].map(|i| f64::from_bits(self.0[i].load(Ordering::Relaxed)))
    }

    fn set(&self, k: [f64; 4]) {
        for (a, x) in self.0.iter().zip(k) {
            a.store(x.to_bits(), Ordering::Relaxed);
        }
    }
}

/// One key of any invented instrument.
#[derive(Debug, Clone)]
pub enum Voice {
    Rosin(RosinVoice),
    Zither(ZitherVoice),
    Rijke(RijkeVoice),
    Aeolian(AeolianVoice),
    Bubble(BubbleVoice),
    Siren(SirenVoice),
}

impl Voice {
    fn awake(&self) -> bool {
        match self {
            Voice::Rosin(v) => v.awake,
            Voice::Zither(v) => v.awake,
            Voice::Rijke(v) => v.awake,
            Voice::Aeolian(v) => v.awake,
            Voice::Bubble(v) => v.awake,
            Voice::Siren(v) => v.awake,
        }
    }

    fn set_knobs(&mut self, k: [f64; 4]) {
        match self {
            Voice::Rosin(v) => v.set_knobs(k),
            Voice::Zither(v) => v.set_knobs(k),
            Voice::Rijke(v) => v.set_knobs(k),
            Voice::Aeolian(v) => v.set_knobs(k),
            Voice::Bubble(v) => v.set_knobs(k),
            Voice::Siren(v) => v.set_knobs(k),
        }
    }

    fn event(&mut self, ev: NoteEvent) {
        match self {
            Voice::Rosin(v) => v.event(ev),
            Voice::Zither(v) => v.event(ev),
            Voice::Rijke(v) => v.event(ev),
            Voice::Aeolian(v) => v.event(ev),
            Voice::Bubble(v) => v.event(ev),
            Voice::Siren(v) => v.event(ev),
        }
    }

    /// One sample (the voice is awake).
    fn step(&mut self) -> f64 {
        match self {
            Voice::Rosin(v) => v.step(),
            Voice::Zither(v) => v.step(),
            Voice::Rijke(v) => v.step(),
            Voice::Aeolian(v) => v.step(),
            Voice::Bubble(v) => v.step(),
            Voice::Siren(_) => unreachable!("a siren key steps with its shaft"),
        }
    }
}

/// What every key reads: the panel, and the Siren Organ's shaft (None for the others).
#[derive(Debug)]
pub struct Ctx {
    knobs: Knobs,
    shaft: Option<RwLock<Shaft>>,
}

impl crate::keyed::KeyVoice for Voice {
    type Ctx = Ctx;

    fn asleep(&self) -> bool {
        !self.awake()
    }

    fn wakes_on_broadcast(&self) -> bool {
        matches!(self, Voice::Zither(v) if v.drone.is_some())
    }

    fn chunk_start(&mut self, start: usize) {
        if let Voice::Aeolian(v) = self {
            v.chunk0 = start;
        }
    }

    fn prepare(ctx: &Ctx, start: usize, n: usize, events: &[(usize, NoteEvent)]) {
        if let Some(s) = &ctx.shaft {
            s.write()
                .expect("shaft")
                .prepare(ctx.knobs.get(), start, n, events);
        }
    }

    fn event(&mut self, ev: NoteEvent, _ctx: &Ctx) {
        Voice::event(self, ev);
    }

    fn render(&mut self, buf: &mut [f64], _n: usize, from: usize, to: usize, ctx: &Ctx) {
        if !self.awake() {
            return;
        }
        self.set_knobs(ctx.knobs.get());
        if let Voice::Siren(v) = self {
            let s = ctx.shaft.as_ref().expect("shaft").read().expect("shaft");
            let shaft = s.rev_buf[from..to].iter().zip(&s.jet_buf[from..to]);
            for (o, (&rev, &jet)) in buf[from..to].iter_mut().zip(shaft) {
                if !v.awake {
                    break;
                }
                *o += v.step(rev, jet);
            }
            return;
        }
        if let Voice::Aeolian(v) = self {
            v.now = v.chunk0 + from;
        }
        for o in buf[from..to].iter_mut() {
            if !self.awake() {
                break;
            }
            *o += self.step();
        }
    }

    fn silence(&mut self) {
        match self {
            Voice::Rosin(v) => {
                v.awake = false;
                v.down = false;
            }
            // A key's string falls silent; the tanpura's run on (the cap counts them, so
            // up to four keys more sound while the cam runs).
            Voice::Zither(v) => {
                if v.drone.is_none() {
                    v.awake = false;
                }
            }
            Voice::Rijke(v) => {
                v.awake = false;
                v.down = false;
                v.held = false;
            }
            Voice::Aeolian(v) => {
                v.awake = false;
                v.down = false;
                v.held = false;
            }
            Voice::Bubble(v) => {
                v.awake = false;
                v.down = false;
                v.held = false;
                v.pending = false;
                v.slots.iter_mut().for_each(|s| *s = None);
            }
            // Its ring falls silent; the shaft still counts the key's valve (held, it draws
            // on the motor and the bellows).
            Voice::Siren(v) => {
                v.awake = false;
                v.valve.down = false;
                v.valve.held = false;
                v.valve.v = 0.0;
                v.reset();
            }
        }
    }
}

/// The keyboard's voices at internal rate `fs` (ascending notes).
pub fn voices(model: &Arc<Model>, fs: f64, knobs: [f64; 4]) -> Vec<(u8, Voice)> {
    match &**model {
        Model::Rosin(m) => m
            .keys
            .iter()
            .map(|k| (k.note, Voice::Rosin(RosinVoice::new(model, k, fs, knobs))))
            .collect(),
        // The tanpura's strings on notes 0-3 (no key plays them), then the keys.
        Model::Zither(m) => (0..m.drone_hz.len())
            .map(|d| {
                let v = ZitherVoice::new(model, fs, knobs, None, Some(d));
                (d as u8, Voice::Zither(v))
            })
            .chain(m.keys.iter().map(|k| {
                let v = ZitherVoice::new(model, fs, knobs, Some(k), None);
                (k.note, Voice::Zither(v))
            }))
            .collect(),
        Model::Rijke(m) => m
            .keys
            .iter()
            .map(|k| (k.note, Voice::Rijke(RijkeVoice::new(model, k, fs, knobs))))
            .collect(),
        Model::Aeolian(m) => m
            .keys
            .iter()
            .map(|k| {
                (
                    k.note,
                    Voice::Aeolian(AeolianVoice::new(model, k, fs, knobs)),
                )
            })
            .collect(),
        Model::Bubble(m) => m
            .keys
            .iter()
            .map(|k| (k.note, Voice::Bubble(BubbleVoice::new(model, k, fs, knobs))))
            .collect(),
        Model::Siren(m) => m
            .keys
            .iter()
            .map(|k| (k.note, Voice::Siren(SirenVoice::new(model, k, fs, knobs))))
            .collect(),
    }
}

/// The element's panel.
pub fn knobs_of(el: &InventedKeys) -> [f64; 4] {
    [el.k0, el.k1, el.k2, el.k3]
}

pub struct Medium {
    pub el: InventedKeys,
    pub model: Arc<Model>,
    /// Internal samples per step.
    pub k: usize,
    keys: crate::keyed::Medium<Voice>,
}

impl std::fmt::Debug for Medium {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("invented::Medium")
            .field("el", &self.el.name)
            .field("instrument", &self.el.instrument)
            .field("k", &self.k)
            .field("keys", &self.keys)
            .finish()
    }
}

impl Medium {
    /// The keys at step rate `fs`.
    pub fn new(el: &InventedKeys, fs: f64) -> Result<Medium, String> {
        Medium::with_workers(el, fs, crate::keyed::workers())
    }

    /// Internal samples per step at step rate `fs`.
    pub fn rate(el: &InventedKeys, fs: f64) -> usize {
        ((el.rate_hz / fs) - 1e-9).ceil().max(1.0) as usize
    }

    /// [`Medium::new`] with `n` worker threads (the result is the same with any number).
    pub fn with_workers(el: &InventedKeys, fs: f64, n: usize) -> Result<Medium, String> {
        let model = load(el)?;
        let k = Medium::rate(el, fs);
        let knobs = knobs_of(el);
        let v = voices(&model, fs * k as f64, knobs);
        let shaft = matches!(*model, Model::Siren(_))
            .then(|| RwLock::new(Shaft::new(&model, fs * k as f64, knobs)));
        let ctx = Ctx {
            knobs: Knobs::new(knobs),
            shaft,
        };
        let mut keys = crate::keyed::Medium::new(v, ctx, fs, k, 1, n);
        keys.set_max_awake(Some(el.max_keys as usize));
        Ok(Medium {
            el: el.clone(),
            model,
            k,
            keys,
        })
    }

    /// Keep every internal sample rendered from now on ([`Medium::raw`]; tests).
    pub fn keep_raw(&mut self) {
        self.keys.keep_raw();
    }

    /// The output's internal samples kept.
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

    /// The summed output at the next step (the push at step p gives step p + 1's).
    pub fn push(&mut self) -> f64 {
        let mut y = [0.0];
        self.keys.push_into(&mut y);
        y[0]
    }

    /// Keys sounding after the last chunk.
    pub fn sounding(&self) -> usize {
        self.keys.sounding()
    }

    /// Whether `el` keeps this keyboard playing (all but the panel the same).
    pub fn same(&self, el: &InventedKeys) -> bool {
        InventedKeys {
            k0: self.el.k0,
            k1: self.el.k1,
            k2: self.el.k2,
            k3: self.el.k3,
            ..el.clone()
        } == self.el
    }

    /// New knobs, from the first step not yet rendered.
    pub fn update(&mut self, el: &InventedKeys) {
        self.el.k0 = el.k0;
        self.el.k1 = el.k1;
        self.el.k2 = el.k2;
        self.el.k3 = el.k3;
        self.keys.ctx().knobs.set(knobs_of(el));
    }

    pub fn fs(&self) -> f64 {
        self.keys.fs()
    }
}

/// The keys alone: `n` internal samples at `fs` (k = 1), `events` (step, event) in order,
/// the raw sum (sample p after the events at p), as the Python reference plays them.
pub fn render_raw(
    el: &InventedKeys,
    fs: f64,
    n: usize,
    events: &[(usize, NoteEvent)],
    workers: usize,
) -> Result<Vec<f64>, String> {
    let mut m = Medium::with_workers(el, fs, workers)?;
    m.keep_raw();
    for &(at, ev) in events {
        m.queue(at, ev);
    }
    m.known_until(usize::MAX);
    for _ in 0..n {
        m.push();
    }
    Ok(m.raw()[..n.min(m.raw().len())].to_vec())
}
