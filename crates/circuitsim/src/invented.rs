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
//! sung by heated gauzes: `varimu/invented/keys/rijke.py`).

use std::collections::HashMap;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Arc, Mutex, OnceLock};

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
        }
    }

    fn notes(&self) -> Vec<u8> {
        match self {
            Model::Rosin(m) => m.keys.iter().map(|k| k.note).collect(),
            Model::Zither(m) => m.keys.iter().map(|k| k.note).collect(),
            Model::Rijke(m) => m.keys.iter().map(|k| k.note).collect(),
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
        };
        v.set_knobs(knobs);
        v
    }

    fn set_knobs(&mut self, k: [f64; 4]) {
        let (wheel, res, touch) = {
            let m = self.rm();
            (
                knob(m.wheel_range_m_s, k[0]),
                m.resonator_max * k[1],
                knob(m.touch_range, k[2]),
            )
        };
        self.wheel = wheel;
        self.res_gain = res;
        self.touch = touch;
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
        let mut vh = 0.0;
        let mut y_adm = 0.0;
        for (((s, xn), vn), (&x, &v)) in steps
            .iter()
            .zip(self.xn.iter_mut())
            .zip(self.vn.iter_mut())
            .zip(self.x.iter().zip(&self.v))
        {
            *xn = s[0] * x + s[1] * v;
            *vn = s[2] * x + s[3] * v;
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
}

impl Voice {
    fn awake(&self) -> bool {
        match self {
            Voice::Rosin(v) => v.awake,
            Voice::Zither(v) => v.awake,
            Voice::Rijke(v) => v.awake,
        }
    }

    fn set_knobs(&mut self, k: [f64; 4]) {
        match self {
            Voice::Rosin(v) => v.set_knobs(k),
            Voice::Zither(v) => v.set_knobs(k),
            Voice::Rijke(v) => v.set_knobs(k),
        }
    }

    fn event(&mut self, ev: NoteEvent) {
        match self {
            Voice::Rosin(v) => v.event(ev),
            Voice::Zither(v) => v.event(ev),
            Voice::Rijke(v) => v.event(ev),
        }
    }

    /// One sample (the voice is awake).
    fn step(&mut self) -> f64 {
        match self {
            Voice::Rosin(v) => v.step(),
            Voice::Zither(v) => v.step(),
            Voice::Rijke(v) => v.step(),
        }
    }
}

impl crate::keyed::KeyVoice for Voice {
    type Ctx = Knobs;

    fn asleep(&self) -> bool {
        !self.awake()
    }

    fn wakes_on_broadcast(&self) -> bool {
        matches!(self, Voice::Zither(v) if v.drone.is_some())
    }

    fn event(&mut self, ev: NoteEvent, _ctx: &Knobs) {
        Voice::event(self, ev);
    }

    fn render(&mut self, buf: &mut [f64], _n: usize, from: usize, to: usize, ctx: &Knobs) {
        if !self.awake() {
            return;
        }
        self.set_knobs(ctx.get());
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
        let mut keys = crate::keyed::Medium::new(v, Knobs::new(knobs), fs, k, 1, n);
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
        self.keys.ctx().set(knobs_of(el));
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
