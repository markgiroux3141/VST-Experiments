//! The Victorian synth's keyboard of self-interrupting reeds as a medium beside the circuit
//! (docs/VICTORIAN_SYNTH_PLAN.md, V1-V3): a port of `varimu/victorian/reed.py`, step for step
//! (its docstring has the physics).
//!
//! Per key a steel reed (two modes) kept going by its electromagnet in a local circuit
//! through a platinum drive contact with Fizeau's condenser (and its spark), and a second
//! platinum point on the same follow spring chopping the line through the carbon under the
//! key (pressed through an oil dashpot by the key's velocity and aftertouch).
//!
//! **Coupling.** The medium senses the local battery's node `loc` and the line's node `line`
//! a sample late (each key's local circuit sees `loc`, its line branch `line`; both return to
//! ground) and drives two outputs at the next sample: the keys' local currents and their
//! line currents, summed, volts = amperes x `v_per_a`, which the circuit's `G` parts draw from
//! `loc` and `line`. The local current is a coil's (inductive, so the sample's latency costs
//! nothing); the line's is resistive, so the circuit holds `line` with a condenser.
//!
//! **Sleeping keys.** A key up whose carbon is unloaded, whose coil's current and reed's swing
//! have died away sleeps and costs nothing; a key struck wakes at its rest.

use std::collections::{HashMap, VecDeque};
use std::sync::{Arc, Mutex, OnceLock};

use serde::Deserialize;

use crate::ir::ReedKeys;
use crate::media::NoteEvent;

const MU0: f64 = 4e-7 * std::f64::consts::PI;

/// A reed's mode (`reed.Mode`).
#[derive(Debug, Clone, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ModeData {
    pub omega: f64,
    pub zeta: f64,
    pub mass_kg: f64,
    pub b: f64,
}

/// One key's values (`reed.KeyParams`, `varimu/victorian/compile.py`).
#[derive(Debug, Clone, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct KeyParams {
    pub note: u8,
    pub f_hz: f64,
    pub modes: Vec<ModeData>,
    pub turns: f64,
    pub area_m2: f64,
    pub gap_m: f64,
    pub core_gap_m: f64,
    pub r_drive_ohm: f64,
    pub stop_m: f64,
    pub k_stop_n_m: f64,
    pub c_stop_ns_m: f64,
    pub x_c_m: f64,
    pub f_pre_n: f64,
    pub k_s_n_m: f64,
    pub c_s_ns_m: f64,
    pub r_c0_ohm: f64,
    pub f_c0_n: f64,
    pub r_film_ohm: f64,
    pub cond_drive_f: f64,
    pub cond_line_f: f64,
    pub v_arc: f64,
    pub i_arc_min_a: f64,
    pub r_arc_ohm: f64,
    pub e_fe_v_m: f64,
    pub v_paschen: f64,
    pub d_paschen_m: f64,
    pub e_air_v_m: f64,
    pub g_open_s: f64,
    pub g0_s: f64,
    pub f0_n: f64,
    pub n_carbon: f64,
    pub f_max_n: f64,
    pub vel_exp: f64,
    pub touch_gain: f64,
    pub tau_on_s: f64,
    pub tau_off_s: f64,
    pub q_damper: f64,
}

/// The compiled keyboard (a component version of kind `reed_keys`).
#[derive(Debug, Clone, Deserialize)]
pub struct Model {
    pub keys: Vec<KeyParams>,
}

impl Model {
    pub fn from_json(text: &str) -> Result<Model, String> {
        let m: Model = serde_json::from_str(text).map_err(|e| e.to_string())?;
        if m.keys.is_empty() {
            return Err("no keys".into());
        }
        for (i, k) in m.keys.iter().enumerate() {
            if i > 0 && k.note != m.keys[i - 1].note + 1 {
                return Err("the keys must be consecutive notes".into());
            }
            if k.modes.is_empty() {
                return Err(format!("key {}: no modes", k.note));
            }
        }
        Ok(m)
    }
}

/// The compiled keyboard the IR element names, loaded once per process.
pub fn load(el: &ReedKeys) -> Result<Arc<Model>, String> {
    type Loaded = Mutex<HashMap<(String, String), Arc<Model>>>;
    static LOADED: OnceLock<Loaded> = OnceLock::new();
    let cache = LOADED.get_or_init(Default::default);
    let id = (el.data.clone(), el.sha256.clone());
    if let Some(m) = cache.lock().expect("reeds").get(&id) {
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
    let m = Arc::new(Model::from_json(&raw).map_err(|e| format!("{}: {e}", el.name))?);
    Ok(cache.lock().expect("reeds").entry(id).or_insert(m).clone())
}

/// A damped mode's exact step (`reed.mode_step`).
#[derive(Debug, Clone, Copy)]
struct ModeStep {
    a11: f64,
    a12: f64,
    a21: f64,
    a22: f64,
    inv_k: f64,
}

fn mode_step(m: &ModeData, h: f64) -> ModeStep {
    let (w, z) = (m.omega, m.zeta);
    let wd = w * (1.0 - z * z).sqrt();
    let e = (-z * w * h).exp();
    let c = (wd * h).cos();
    let s = (wd * h).sin();
    let zw = z * w / wd;
    ModeStep {
        a11: e * (c + zw * s),
        a12: e * s / wd,
        a21: -e * w * w / wd * s,
        a22: e * (c - zw * s),
        inv_k: 1.0 / (m.mass_kg * w * w),
    }
}

/// The reed's static stiffness at the drive point (`reed.k_drive`).
pub fn k_drive(p: &KeyParams) -> f64 {
    let mut s = 0.0;
    for m in &p.modes {
        s += m.b * m.b / (m.mass_kg * m.omega * m.omega);
    }
    1.0 / s
}

fn inductance(p: &KeyParams, x: f64) -> f64 {
    MU0 * p.turns * p.turns * p.area_m2 / (2.0 * (p.gap_m - x) + p.core_gap_m)
}

fn breakdown_v(p: &KeyParams, d: f64) -> f64 {
    let paschen = p.v_paschen + p.e_air_v_m * (d - p.d_paschen_m).max(0.0);
    p.v_arc.max((p.e_fe_v_m * d).min(paschen))
}

/// One key (`reed.Key`).
#[derive(Debug, Clone)]
pub struct Key {
    p: KeyParams,
    h: f64,
    steps: Vec<ModeStep>,
    steps_up: Vec<ModeStep>,
    xs: Vec<f64>,
    vs: Vec<f64>,
    /// The modes at rest on the screws.
    x_rest: Vec<f64>,
    lam: f64,
    qd: f64,
    ql: f64,
    arc: i32,
    force: f64,
    target: f64,
    held: bool,
    velocity: f64,
    pressure: f64,
    on_k: f64,
    off_k: f64,
    /// The closed contact's resistance at rest.
    rest_rc: f64,
    pub sparks: u64,
}

impl Key {
    pub fn new(p: &KeyParams, fs_int: f64) -> Key {
        let h = 1.0 / fs_int;
        let steps: Vec<ModeStep> = p.modes.iter().map(|m| mode_step(m, h)).collect();
        // The key up: the felt damper's loss on every mode (`reed.Key`).
        let steps_up: Vec<ModeStep> = p
            .modes
            .iter()
            .map(|m| {
                let damped = ModeData {
                    zeta: m.zeta + 0.5 / p.q_damper,
                    ..m.clone()
                };
                mode_step(&damped, h)
            })
            .collect();
        let mut k = Key {
            p: p.clone(),
            h,
            steps_up,
            xs: vec![0.0; steps.len()],
            vs: vec![0.0; steps.len()],
            x_rest: vec![0.0; steps.len()],
            steps,
            lam: 0.0,
            qd: 0.0,
            ql: 0.0,
            arc: 0,
            force: 0.0,
            target: 0.0,
            held: false,
            velocity: 0.0,
            pressure: 0.0,
            on_k: (-h / p.tau_on_s).exp(),
            off_k: (-h / p.tau_off_s).exp(),
            rest_rc: 0.0,
            sparks: 0,
        };
        k.rest();
        let x = k.x();
        let fc = k.contact_force(x, 0.0);
        k.rest_rc = p.r_film_ohm + p.r_c0_ohm * (p.f_c0_n / (0.5 * fc).max(1e-9 * p.f_c0_n)).sqrt();
        k
    }

    /// At rest on the screws.
    fn rest(&mut self) {
        let p = &self.p;
        let k_reed = k_drive(p);
        let x0 = (p.f_pre_n + p.k_s_n_m * p.x_c_m) / (k_reed + p.k_s_n_m);
        let f0 = k_reed * x0;
        for (j, st) in self.steps.iter().enumerate() {
            self.xs[j] = p.modes[j].b * f0 * st.inv_k;
            self.vs[j] = 0.0;
        }
        self.x_rest.clone_from(&self.xs);
        self.lam = 0.0;
        self.qd = 0.0;
        self.ql = 0.0;
        self.arc = 0;
    }

    fn retarget(&mut self) {
        let p = &self.p;
        self.target = if self.held {
            p.f_max_n
                * (self.velocity / 127.0).powf(p.vel_exp)
                * (1.0 + p.touch_gain * self.pressure / 127.0)
        } else {
            0.0
        };
    }

    pub fn press(&mut self, velocity: u8) {
        self.held = true;
        self.velocity = f64::from(velocity.clamp(1, 127));
        self.retarget();
    }

    pub fn release(&mut self) {
        self.held = false;
        self.retarget();
    }

    pub fn set_pressure(&mut self, value: u8) {
        self.pressure = f64::from(value.min(127));
        self.retarget();
    }

    pub fn x(&self) -> f64 {
        let mut s = 0.0;
        for (m, q) in self.p.modes.iter().zip(&self.xs) {
            s += m.b * q;
        }
        s
    }

    fn v(&self) -> f64 {
        let mut s = 0.0;
        for (m, u) in self.p.modes.iter().zip(&self.vs) {
            s += m.b * u;
        }
        s
    }

    fn carbon_g(&self) -> f64 {
        let p = &self.p;
        let f = self.force;
        p.g_open_s
            + if f > 0.0 {
                p.g0_s * (f / p.f0_n).powf(p.n_carbon)
            } else {
                0.0
            }
    }

    fn contact_force(&self, x: f64, v: f64) -> f64 {
        let p = &self.p;
        if x >= p.x_c_m {
            return 0.0;
        }
        (p.f_pre_n + p.k_s_n_m * (p.x_c_m - x) - p.c_s_ns_m * v).max(0.0)
    }

    /// The reed's swing's energy (J): its modes' about their rest on the screws.
    pub fn energy(&self) -> f64 {
        let mut e = 0.0;
        for (j, (m, st)) in self.p.modes.iter().zip(&self.steps).enumerate() {
            let (u, d) = (self.vs[j], self.xs[j] - self.x_rest[j]);
            e += 0.5 * m.mass_kg * u * u + 0.5 * d * d / st.inv_k;
        }
        e
    }

    pub fn asleep(&self) -> bool {
        !self.held
            && self.force < 1e-6 * self.p.f0_n
            && self.lam.abs() < 1e-9
            && self.energy() < 1e-9
    }

    /// One internal step (`reed.Key.step`): the local and line currents at its end.
    pub fn step(&mut self, v_loc: f64, v_line: f64) -> (f64, f64) {
        let h = self.h;
        let x = self.x();
        let v = self.v();
        let p = &self.p;
        let ell = inductance(p, x);
        let fc = self.contact_force(x, v);
        let closed = x < p.x_c_m;
        let (rc, g, j) = if closed {
            let rc =
                p.r_film_ohm + p.r_c0_ohm * (p.f_c0_n / (0.5 * fc).max(1e-9 * p.f_c0_n)).sqrt();
            (rc, 1.0 / rc, 0.0)
        } else if self.arc != 0 {
            (
                0.0,
                1.0 / p.r_arc_ohm,
                f64::from(self.arc) * p.v_arc / p.r_arc_ohm,
            )
        } else {
            (0.0, 0.0, 0.0)
        };
        let vd = if self.held { v_loc } else { 0.0 };
        let cd = p.cond_drive_f;
        let a11 = 1.0 + h * p.r_drive_ohm / ell;
        let a12 = h / cd;
        let a21 = -h / ell;
        let a22 = 1.0 + h * g / cd;
        let b1 = self.lam + h * vd;
        let b2 = self.qd + h * j;
        let det = a11 * a22 - a12 * a21;
        let lam = (b1 * a22 - a12 * b2) / det;
        let qd = (a11 * b2 - a21 * b1) / det;
        self.lam = lam;
        self.qd = qd;
        let i_loc = lam / ell;
        let cl = p.cond_line_f;
        let gk = self.carbon_g();
        let p = &self.p;
        let gl = if closed { 1.0 / rc } else { 0.0 };
        let ql = (self.ql + h * v_line * gk) / (1.0 + h * (gk + gl) / cl);
        self.ql = ql;
        let i_line = (v_line - ql / cl) * gk;
        let mut f = lam * lam / (MU0 * p.turns * p.turns * p.area_m2) + fc;
        if x > p.stop_m {
            f -= p.k_stop_n_m * (x - p.stop_m) + p.c_stop_ns_m * v;
        }
        let steps = if self.held {
            &self.steps
        } else {
            &self.steps_up
        };
        for (jm, st) in steps.iter().enumerate() {
            let xs = p.modes[jm].b * f * st.inv_k;
            let dx = self.xs[jm] - xs;
            let vm = self.vs[jm];
            self.xs[jm] = xs + st.a11 * dx + st.a12 * vm;
            self.vs[jm] = st.a21 * dx + st.a22 * vm;
        }
        let xn = self.x();
        let p = &self.p;
        let vc = qd / cd;
        if xn < p.x_c_m {
            self.arc = 0;
        } else if self.arc != 0 {
            let a = f64::from(self.arc);
            let ic = a * (vc - a * p.v_arc) / p.r_arc_ohm;
            if ic < p.i_arc_min_a {
                self.arc = 0;
            }
        } else if vc.abs() > breakdown_v(p, xn - p.x_c_m) {
            self.arc = if vc > 0.0 { 1 } else { -1 };
            self.sparks += 1;
        }
        let k = if self.held { self.on_k } else { self.off_k };
        self.force = self.target + (self.force - self.target) * k;
        (i_loc, i_line)
    }
}

/// The keyboard beside the circuit.
#[derive(Debug)]
pub struct Medium {
    el: ReedKeys,
    model: Arc<Model>,
    keys: Vec<Key>,
    awake: Vec<bool>,
    /// Key downs per key (several MIDI notes fold onto one key), and a key up deferred by
    /// the pedal.
    held: Vec<u32>,
    sustained: Vec<bool>,
    pedal: bool,
    oversample: usize,
    events: VecDeque<(usize, NoteEvent)>,
    pos: usize,
    outs: [f64; 2],
    sounding: usize,
}

impl Medium {
    pub fn new(el: &ReedKeys, fs: f64) -> Result<Medium, String> {
        let model = load(el)?;
        let oversample = Self::oversample(el, fs);
        let fs_int = fs * oversample as f64;
        let keys: Vec<Key> = model.keys.iter().map(|p| Key::new(p, fs_int)).collect();
        let n = keys.len();
        Ok(Medium {
            el: el.clone(),
            model,
            keys,
            awake: vec![false; n],
            held: vec![0; n],
            sustained: vec![false; n],
            pedal: false,
            oversample,
            events: VecDeque::new(),
            pos: 0,
            outs: [0.0; 2],
            sounding: 0,
        })
    }

    /// Internal steps per step: the least whole multiple of `fs` at or above `step_hz`.
    pub fn oversample(el: &ReedKeys, fs: f64) -> usize {
        ((el.step_hz / fs) * (1.0 - 1e-12)).ceil().max(1.0) as usize
    }

    /// Whether `el` is this keyboard (it has no knobs: anything else is another one).
    pub fn same(&self, el: &ReedKeys) -> bool {
        *el == self.el
    }

    /// The key a MIDI note plays (folded into the compass by octaves).
    pub fn key_of(&self, note: u8) -> usize {
        let lo = self.model.keys[0].note;
        let hi = self.model.keys[self.model.keys.len() - 1].note;
        let mut n = note;
        while n < lo {
            n += 12;
        }
        while n > hi {
            n -= 12;
        }
        (n - lo) as usize
    }

    /// An event at step `at` (lands at the push for that step, or the next one if late).
    pub fn queue(&mut self, at: usize, ev: NoteEvent) {
        let ev = match ev {
            NoteEvent::On { note, velocity: 0 } => NoteEvent::Off { note },
            e => e,
        };
        self.events.push_back((at, ev));
    }

    fn apply(&mut self, ev: NoteEvent) {
        match ev {
            NoteEvent::On { note, velocity } => {
                let i = self.key_of(note);
                self.held[i] += 1;
                self.sustained[i] = false;
                self.keys[i].press(velocity);
                self.awake[i] = true;
            }
            NoteEvent::Off { note } => {
                let i = self.key_of(note);
                self.held[i] = self.held[i].saturating_sub(1);
                if self.held[i] == 0 {
                    if self.pedal {
                        self.sustained[i] = true;
                    } else {
                        self.keys[i].release();
                    }
                }
            }
            NoteEvent::Pedal { down } => {
                self.pedal = down;
                if !down {
                    for i in 0..self.keys.len() {
                        if self.sustained[i] {
                            self.sustained[i] = false;
                            self.keys[i].release();
                        }
                    }
                }
            }
            NoteEvent::Pressure { value } => {
                for k in &mut self.keys {
                    k.set_pressure(value);
                }
            }
        }
    }

    /// The local battery's and the line's voltages at this sample; the keys' local and line
    /// currents (x `v_per_a`) at the next, into [`Medium::output`]. Returns the first.
    pub fn push(&mut self, s: &[f64]) -> f64 {
        while let Some(&(at, ev)) = self.events.front() {
            if at > self.pos {
                break;
            }
            self.events.pop_front();
            self.apply(ev);
        }
        let (v_loc, v_line) = (s[0], s[1]);
        let mut sum_loc = 0.0;
        let mut sum_line = 0.0;
        let mut sounding = 0;
        let ov = self.oversample;
        for (key, awake) in self.keys.iter_mut().zip(self.awake.iter_mut()) {
            if !*awake {
                // Asleep: the unloaded carbon's leak through the closed line contact (its
                // condenser charged to the contact's few microvolts: the DC state).
                let g = key.p.g_open_s;
                sum_line += v_line * g / (1.0 + g * key.rest_rc);
                continue;
            }
            let (mut a, mut b) = (0.0, 0.0);
            for _ in 0..ov {
                let (il, ik) = key.step(v_loc, v_line);
                a += il;
                b += ik;
            }
            sum_loc += a / ov as f64;
            sum_line += b / ov as f64;
            if key.asleep() {
                key.rest();
                *awake = false;
            } else {
                sounding += 1;
            }
        }
        self.sounding = sounding;
        let k = self.el.v_per_a;
        self.outs = [sum_loc * k, sum_line * k];
        self.pos += 1;
        self.outs[0]
    }

    pub fn output(&self, j: usize) -> f64 {
        self.outs[j]
    }

    /// Keys sounding after the last push.
    pub fn sounding(&self) -> usize {
        self.sounding
    }

    /// The keys (tests, studies).
    pub fn keys(&self) -> &[Key] {
        &self.keys
    }

    /// Sparks so far, every key's.
    pub fn sparks(&self) -> u64 {
        self.keys.iter().map(|k| k.sparks).sum()
    }
}
