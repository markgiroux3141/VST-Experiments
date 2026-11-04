//! The proxy (docs/MIDI_TAKES_PLAN.md N2): a cheap digital stand-in for tube_synth, heard
//! while a take is played and recorded; the take's real audio is a render of its events
//! through the circuit, later.
//!
//! **It follows the panel** through tables measured on the real circuit
//! (`config/proxy/tube_synth.json`, made by `scripts/proxy_tables.py`, each with its
//! source; the ones not measured yet say provisional). It is built like the circuit, so
//! the tables plug in where the circuit's quantities are:
//!
//! - **the envelope runs in volts** as the ADSR does: from the keyboard bus's rest (-110 V)
//!   toward the key's key-down volts (its velocity through the device's velocity table,
//!   `panel::velocity_volts`), then toward SUSTAIN's volts, released back to rest, each a
//!   one-pole at its pot's time constant (audio taper);
//! - **the VCA** turns those volts into a level through the measured law (the envelope's
//!   volts against the output's level, a key held at each key-down voltage), the absolute
//!   level (rms re full scale) matched at the measurement's key and panel;
//! - **the filter** is a 2-pole low-pass whose f0 and Q follow V4's grid volts through the
//!   measured law, and V4's grid is the sum the circuit makes: CUTOFF's volts, KEY TRACK's
//!   share of the key string, PRESSURE's share of the aftertouch strip, ENV AMOUNT's share
//!   of the envelope, WOBBLE's share of the LFO; RESONANCE raises Q (provisional);
//! - **the oscillator** is a wavetable per octave from the measured harmonics per WAVE (the
//!   tank at 0, the out at 0.5; a square at 1), pitched where the device's tuning puts the
//!   key (measured per key; equal temperament without it), gliding as a one-pole at GLIDE's measured time
//!   constant, VIBRATO's measured depth on the LFO; the saw (SAW ON) a band-limited
//!   sawtooth at its measured level; the ring (RING ON) the oscillator times the LFO, with
//!   its measured level and bleeds;
//! - **one LFO** (a sine at the measured rate per RATE, both ranges) shared by every voice.
//!
//! Knobs it ignores are heard in the render only ([`RENDER_ONLY`]: the heaters, the
//! reservoir, the mains). It runs at the host rate with naive wavetables (aliasing
//! accepted), up to [`MAX_VOICES`] voices: one (mono, the last key held sounding, as the
//! real synth) or several, allocated as docs/MIDI_TAKES_PLAN.md decision 4 says (the voice
//! already on the note, else round-robin, else the oldest stolen), each gliding from the
//! last note it played.

use std::path::Path;

use serde_json::Value as Json;

use crate::live::Values;
use crate::midi::TestOsc;
use crate::performance::{Ev, Playing};

/// The most voices a proxy plays.
pub const MAX_VOICES: usize = 16;

/// The panel's controls the proxy doesn't follow: heard in the render only.
pub const RENDER_ONLY: [&str; 4] = ["heater", "reservoir", "mains_v_rms", "mains_hz"];

/// The keyboard bus at rest (V).
const REST_V: f64 = -110.0;
/// Samples between filter coefficient updates.
const CONTROL_EVERY: usize = 16;
const TABLE_N: usize = 2048;
/// The octaves the wavetables cover (from 16 Hz).
const OCTAVES: usize = 11;
const TABLE_BASE_HZ: f64 = 16.0;

/// A table of (x, y) points, interpolated linearly, held at its ends.
#[derive(Debug, Clone)]
struct Curve(Vec<(f64, f64)>);

impl Curve {
    fn from(xs: &Json, ys: &Json) -> Result<Curve, String> {
        let f = |v: &Json| -> Result<Vec<f64>, String> {
            v.as_array()
                .ok_or("a proxy table isn't a list")?
                .iter()
                .map(|x| {
                    x.as_f64()
                        .ok_or_else(|| "a proxy table value isn't a number".to_string())
                })
                .collect()
        };
        let (x, y) = (f(xs)?, f(ys)?);
        if x.len() != y.len() || x.is_empty() {
            return Err("a proxy table's columns differ in length".into());
        }
        let mut p: Vec<(f64, f64)> = x.into_iter().zip(y).collect();
        p.sort_by(|a, b| a.0.total_cmp(&b.0));
        Ok(Curve(p))
    }

    fn at(&self, x: f64) -> f64 {
        let p = &self.0;
        if x <= p[0].0 {
            return p[0].1;
        }
        if x >= p[p.len() - 1].0 {
            return p[p.len() - 1].1;
        }
        let i = p.partition_point(|q| q.0 <= x);
        let ((x0, y0), (x1, y1)) = (p[i - 1], p[i]);
        y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    }
}

/// An audio (logarithmic) taper through 0, (0.5, `mid`) and 1, as the circuit's pots
/// (`varimu.circuit.parts.taper`).
fn taper(pos: f64, mid: f64) -> f64 {
    let a = ((1.0 - mid) / mid).powi(2);
    (a.powf(pos.clamp(0.0, 1.0)) - 1.0) / (a - 1.0)
}

/// The measured tables (see the module docs).
#[derive(Debug, Clone)]
pub struct Tables {
    pub device: String,
    /// The circuit file's sha256 when they were made.
    pub circuit_sha256: String,
    f0: Curve,
    q: Curve,
    cutoff_g4: Curve,
    key_track_per_semitone: f64,
    pressure_per_v: f64,
    pressure_full_v: f64,
    vca_db: Curve,
    level_dbfs: f64,
    glide: Curve,
    lfo_low: Curve,
    lfo_audio: Curve,
    vibrato_cents: f64,
    wobble_g4_pp: f64,
    ring_db: f64,
    ring_osc_bleed_db: f64,
    ring_carrier_bleed_db: f64,
    harmonics: [Vec<f64>; 3],
    saw_db: f64,
    mix_mid: f64,
    env_mid: f64,
    attack_s: (f64, f64),
    decay_s: (f64, f64),
    release_s: (f64, f64),
    sustain_v: (f64, f64),
    resonance_q: f64,
    resonance_fade: Curve,
    env_g4: f64,
    /// A held key's level across the keyboard at the defaults (note, rms dB re full scale),
    /// if measured: the proxy matches it key by key.
    key_level: Option<Vec<(f64, f64)>>,
    /// Where the device's tuning puts each key (note, cents re equal temperament), if
    /// measured: the proxy plays there.
    key_cents: Option<Curve>,
    /// The circuit's velocity table (`panel::Device::velocity`).
    velocity: Option<&'static [(f64, f64)]>,
}

impl Tables {
    /// The tables for `device` in `<config>/proxy/<device>.json`; None when it has none.
    pub fn load(config_dir: &Path, device: &str) -> Result<Option<Tables>, String> {
        let p = config_dir.join("proxy").join(format!("{device}.json"));
        if !p.is_file() {
            return Ok(None);
        }
        let text = std::fs::read_to_string(&p).map_err(|e| format!("{}: {e}", p.display()))?;
        let v: Json = serde_json::from_str(&text).map_err(|e| format!("{}: {e}", p.display()))?;
        Tables::from_json(&v, device)
            .map(Some)
            .map_err(|e| format!("{}: {e}", p.display()))
    }

    fn from_json(v: &Json, device: &str) -> Result<Tables, String> {
        let num = |x: &Json, what: &str| x.as_f64().ok_or(format!("no {what}"));
        let pair = |x: &Json, what: &str| -> Result<(f64, f64), String> {
            Ok((num(&x[0], what)?, num(&x[1], what)?))
        };
        let f = &v["filter"];
        let law = &f["law"];
        let h = &v["oscillator"]["harmonics_db"];
        let harm = |i: usize| -> Result<Vec<f64>, String> {
            h[i].as_array()
                .ok_or("no harmonics")?
                .iter()
                .map(|x| {
                    x.as_f64()
                        .ok_or_else(|| "a harmonic isn't a number".to_string())
                })
                .collect()
        };
        let e = &v["envelope"];
        let r = &v["resonance"];
        Ok(Tables {
            device: device.to_string(),
            circuit_sha256: v["circuit_sha256"].as_str().unwrap_or("").to_string(),
            f0: Curve::from(&law["g4_v"], &law["f0_hz"])?,
            q: Curve::from(&law["g4_v"], &law["q"])?,
            cutoff_g4: Curve::from(&f["cutoff_g4"]["pot"], &f["cutoff_g4"]["g4_v"])?,
            key_track_per_semitone: num(&f["key_track_g4_per_semitone"]["at_1"], "key track")?,
            pressure_per_v: num(&f["pressure_g4_per_v"]["value"], "pressure")?,
            pressure_full_v: num(&f["pressure_g4_per_v"]["full_v"], "pressure's full volts")?,
            vca_db: Curve::from(&v["vca"]["env_v"], &v["vca"]["db"])?,
            level_dbfs: num(&v["vca"]["level_dbfs_at_minus_1v"], "the level")?,
            glide: Curve::from(&v["glide"]["pot"], &v["glide"]["tau_s"])?,
            lfo_low: Curve::from(&v["lfo"]["low"]["pot"], &v["lfo"]["low"]["hz"])?,
            lfo_audio: Curve::from(&v["lfo"]["audio"]["pot"], &v["lfo"]["audio"]["hz"])?,
            vibrato_cents: num(&v["lfo"]["vibrato_cents_at_1"], "vibrato")?,
            wobble_g4_pp: num(&v["lfo"]["wobble_g4_pp_v_at_1"], "wobble")?,
            ring_db: num(&v["ring"]["level_db_re_osc"], "the ring's level")?,
            ring_osc_bleed_db: num(&v["ring"]["osc_bleed_db"], "the ring's bleed")?,
            ring_carrier_bleed_db: num(&v["ring"]["carrier_bleed_db"], "the carrier's bleed")?,
            harmonics: [harm(0)?, harm(1)?, harm(2)?],
            saw_db: num(&v["saw"]["db_re_osc"], "the saw's level")?,
            mix_mid: num(&v["tapers"]["mix_mid"], "mix taper")?,
            env_mid: num(&v["tapers"]["env_mid"], "envelope taper")?,
            attack_s: pair(&e["attack_s"], "attack")?,
            decay_s: pair(&e["decay_s"], "decay")?,
            release_s: pair(&e["release_s"], "release")?,
            sustain_v: pair(&e["sustain_v"], "sustain")?,
            resonance_q: num(&r["q_at_1"], "resonance")?,
            resonance_fade: Curve::from(&r["fade_cutoff"], &r["fade"])?,
            env_g4: num(&v["env_amount"]["g4_v_at_1"], "env amount")?,
            key_level: match &v["key_level"] {
                Json::Null => None,
                k => Some(Curve::from(&k["note"], &k["dbfs"])?.0),
            },
            key_cents: match &v["key_level"]["cents"] {
                Json::Null => None,
                c => Some(Curve::from(&v["key_level"]["note"], c)?),
            },
            velocity: crate::print::find_device(device).and_then(|d| d.velocity),
        })
    }

    /// Whether the circuit file has changed since the tables were measured.
    pub fn stale(&self, config_dir: &Path) -> bool {
        use sha2::{Digest, Sha256};
        let Some(d) = crate::print::find_device(&self.device) else {
            return true;
        };
        let p = config_dir
            .join("circuits")
            .join(format!("{}.yaml", d.circuit));
        let Ok(bytes) = std::fs::read(p) else {
            return true;
        };
        let h: String = Sha256::digest(&bytes)
            .iter()
            .map(|b| format!("{b:02x}"))
            .collect();
        h != self.circuit_sha256
    }
}

/// The panel as the proxy reads it.
#[derive(Debug, Clone, Copy, PartialEq)]
struct Panel {
    cutoff: f64,
    resonance: f64,
    attack: f64,
    decay: f64,
    sustain: f64,
    release: f64,
    env_amount: f64,
    key_track: f64,
    pressure: f64,
    glide: f64,
    wave: f64,
    lfo_on: bool,
    lfo_audio: bool,
    lfo_rate: f64,
    vibrato: f64,
    wobble: f64,
    ring_on: bool,
    ring: f64,
    osc_on: bool,
    osc_level: f64,
    saw_on: bool,
    saw_level: f64,
}

impl Default for Panel {
    /// tube_synth.yaml's defaults.
    fn default() -> Panel {
        Panel {
            cutoff: 0.3,
            resonance: 0.3,
            attack: 0.2,
            decay: 0.3,
            sustain: 1.0,
            release: 0.4,
            env_amount: 0.0,
            key_track: 0.0,
            pressure: 0.0,
            glide: 0.0,
            wave: 0.5,
            lfo_on: true,
            lfo_audio: false,
            lfo_rate: 0.7,
            vibrato: 0.0,
            wobble: 0.0,
            ring_on: false,
            ring: 1.0,
            osc_on: true,
            osc_level: 1.0,
            saw_on: false,
            saw_level: 1.0,
        }
    }
}

impl Panel {
    fn set(&mut self, values: &Values) {
        for (k, v) in values {
            let Some(x) = v.as_f64() else { continue };
            let on = x != 0.0;
            match k.as_str() {
                "cutoff" => self.cutoff = x,
                "resonance" => self.resonance = x,
                "attack" => self.attack = x,
                "decay" => self.decay = x,
                "sustain" => self.sustain = x,
                "release" => self.release = x,
                "env_amount" => self.env_amount = x,
                "key_track" => self.key_track = x,
                "pressure" => self.pressure = x,
                "glide" => self.glide = x,
                "wave" => self.wave = x,
                "lfo_on" => self.lfo_on = on,
                "lfo_audio" => self.lfo_audio = on,
                "lfo_rate" => self.lfo_rate = x,
                "vibrato" => self.vibrato = x,
                "wobble" => self.wobble = x,
                "ring_on" => self.ring_on = on,
                "ring" => self.ring = x,
                "osc_on" => self.osc_on = on,
                "osc_level" => self.osc_level = x,
                "saw_on" => self.saw_on = on,
                "saw_level" => self.saw_level = x,
                _ => {}
            }
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq)]
enum Stage {
    Attack,
    Decay,
    Release,
}

/// One voice.
#[derive(Debug, Clone)]
struct Voice {
    /// The key it plays, while held (None: released).
    note: Option<u8>,
    /// The key it last played (glides start there), and when it was struck (for stealing).
    last_note: u8,
    struck: u64,
    key_v: f64,
    /// Its pitch (log2 Hz) and its target.
    pitch: f64,
    target: f64,
    phase: f64,
    saw: f64,
    env_v: f64,
    stage: Stage,
    /// The filter's state (a TPT state-variable filter) and coefficients.
    ic1: f64,
    ic2: f64,
    g: f64,
    k: f64,
    a1: f64,
    /// Its gate lifted for the multi-trigger gap (samples left).
    gap: usize,
    /// Its key's gain (the per-key calibration).
    key_gain: f64,
    /// The phase increment and the VCA's gain now and their steps per sample (computed
    /// every CONTROL_EVERY samples, ramped between), and the wavetable's octave.
    inc: f64,
    d_inc: f64,
    level: f64,
    d_level: f64,
    octave: usize,
}

impl Voice {
    fn new() -> Voice {
        let p = TestOsc::note_hz(crate::performance::START_NOTE).log2();
        Voice {
            note: None,
            last_note: crate::performance::START_NOTE,
            struck: 0,
            key_v: -1.0,
            pitch: p,
            target: p,
            phase: 0.0,
            saw: 0.0,
            env_v: REST_V,
            stage: Stage::Release,
            ic1: 0.0,
            ic2: 0.0,
            g: 0.1,
            k: 1.4,
            a1: 1.0 / (1.0 + 0.1 * 1.5),
            gap: 0,
            key_gain: 1.0,
            inc: 0.0,
            d_inc: 0.0,
            level: 0.0,
            d_level: 0.0,
            octave: 0,
        }
    }

    fn silent(&self) -> bool {
        self.note.is_none() && self.env_v < REST_V + 0.5
    }
}

/// The proxy synth (see the module docs).
pub struct Proxy {
    tables: std::sync::Arc<Tables>,
    rate: f64,
    panel: Panel,
    playing: Playing,
    voices: Vec<Voice>,
    /// The keys held, in the order pressed (mono: the last sounds).
    held: Vec<(u8, u8)>,
    next_voice: usize,
    strikes: u64,
    pressure: f64,
    /// The LFO: its phase (cycles), its sine and cosine now, one sample's rotation.
    lfo_phase: f64,
    lfo_s: f64,
    lfo_c: f64,
    rot_s: f64,
    rot_c: f64,
    /// Per octave, the wavetables at the WAVE points (0, 0.5, 1).
    tables_by_octave: Vec<[Vec<f32>; 3]>,
    /// The output's gain per key (dB, by note): a held key's level at the panel's defaults
    /// matched to the circuit's, key by key where it was measured.
    key_db: Curve,
    counter: usize,
}

impl Proxy {
    /// A proxy on `tables` at `rate` with `voices` voices (1: mono).
    pub fn new(tables: std::sync::Arc<Tables>, rate: u32, voices: usize) -> Proxy {
        let rate = rate as f64;
        let mut tables_by_octave = Vec::with_capacity(OCTAVES);
        for o in 0..OCTAVES {
            // Band-limited to the octave's top note.
            let top = TABLE_BASE_HZ * 2f64.powi(o as i32 + 1);
            let max_h = ((rate * 0.5 / top).floor() as usize).max(1);
            let make = |h: &[f64], extend_square: bool| -> Vec<f32> {
                let mut amps: Vec<f64> = h.iter().map(|db| 10f64.powf(db / 20.0)).collect();
                if extend_square {
                    for n in amps.len() + 1..=max_h {
                        amps.push(if n % 2 == 1 { 1.0 / n as f64 } else { 0.0 });
                    }
                }
                let mut t = vec![0.0f64; TABLE_N];
                for (i, &a) in amps.iter().enumerate().take(max_h) {
                    let n = (i + 1) as f64;
                    for (j, x) in t.iter_mut().enumerate() {
                        *x += a * (std::f64::consts::TAU * n * j as f64 / TABLE_N as f64).sin();
                    }
                }
                let peak = t.iter().fold(1e-9f64, |m, &x| m.max(x.abs()));
                t.iter().map(|&x| (x / peak) as f32).collect()
            };
            let h = &tables.harmonics;
            tables_by_octave.push([make(&h[0], false), make(&h[1], false), make(&h[2], true)]);
        }
        let mut p = Proxy {
            tables,
            rate,
            panel: Panel::default(),
            playing: Playing::default(),
            voices: vec![Voice::new(); voices.clamp(1, MAX_VOICES)],
            held: Vec::new(),
            next_voice: 0,
            strikes: 0,
            pressure: 0.0,
            lfo_phase: 0.0,
            lfo_s: 0.0,
            lfo_c: 1.0,
            rot_s: 0.0,
            rot_c: 1.0,
            tables_by_octave,
            key_db: Curve(vec![(0.0, 0.0)]),
            counter: 0,
        };
        p.key_db = p.calibrate();
        p
    }

    /// The gain per key that puts a key held at -1 V on the bus at the panel's defaults at
    /// the circuit's measured level: key by key where the level across the keyboard was
    /// measured, else at the VCA measurement's key (B4) for every key.
    fn calibrate(&self) -> Curve {
        let t = self.tables.clone();
        match &t.key_level {
            Some(k) => Curve(
                k.iter()
                    .map(|&(note, db)| (note, db - self.probe_db(note as u8)))
                    .collect(),
            ),
            None => {
                // Held at the default SUSTAIN (1: ~-2 V) the VCA is this far below -1 V's.
                let held = t.vca_db.at(t.sustain_v.1);
                Curve(vec![(71.0, t.level_dbfs + held - self.probe_db(71))])
            }
        }
    }

    /// The proxy's own level (rms dB re full scale, no gain) of key `note` held at velocity
    /// 127 (no velocity range) at the panel's defaults.
    fn probe_db(&self, note: u8) -> f64 {
        let t = self.tables.clone();
        let mut probe = Proxy {
            tables: t.clone(),
            rate: self.rate,
            panel: Panel::default(),
            playing: Playing {
                velocity_db: 0.0,
                ..Playing::default()
            },
            voices: vec![Voice::new()],
            held: Vec::new(),
            next_voice: 0,
            strikes: 0,
            pressure: 0.0,
            lfo_phase: 0.0,
            lfo_s: 0.0,
            lfo_c: 1.0,
            rot_s: 0.0,
            rot_c: 1.0,
            tables_by_octave: self.tables_by_octave.clone(),
            key_db: Curve(vec![(0.0, 0.0)]),
            counter: 0,
        };
        let n = (0.6 * self.rate) as usize;
        let mut y = vec![0.0f32; n];
        probe.process(
            &[(
                0,
                Ev::On {
                    note,
                    velocity: 127,
                },
            )],
            &mut y,
        );
        let tail = &y[n / 2..];
        let rms =
            (tail.iter().map(|&v| (v as f64).powi(2)).sum::<f64>() / tail.len() as f64).sqrt();
        // The level as the measurements state it: rms re full scale.
        20.0 * rms.max(1e-12).log10()
    }

    /// The panel (every value, as for a render; ones it doesn't know are ignored).
    pub fn set_values(&mut self, values: &Values) {
        self.panel.set(values);
    }

    /// The key settings (velocity range, multi-trigger).
    pub fn set_playing(&mut self, p: Playing) {
        self.playing = p;
    }

    /// The keys held, in the order pressed.
    pub fn held(&self) -> &[(u8, u8)] {
        &self.held
    }

    /// Voices sounding (an envelope not at rest).
    pub fn sounding(&self) -> usize {
        self.voices.iter().filter(|v| !v.silent()).count()
    }

    fn key_volts(&self, vel: u8) -> f64 {
        match self.tables.velocity {
            Some(t) => crate::panel::velocity_volts(t, vel, self.playing.velocity_db),
            None => -1.0,
        }
    }

    fn strike(&mut self, i: usize, note: u8, vel: u8, legato: bool) {
        let key_v = self.key_volts(vel);
        let key_gain = 10f64.powf(self.key_db.at(note as f64) / 20.0);
        let cents = self
            .tables
            .key_cents
            .as_ref()
            .map_or(0.0, |c| c.at(note as f64));
        self.strikes += 1;
        let gap = (crate::performance::RETRIGGER_GAP_S * self.rate).round() as usize;
        let v = &mut self.voices[i];
        v.note = Some(note);
        v.last_note = note;
        v.struck = self.strikes;
        v.key_v = key_v;
        v.key_gain = key_gain;
        v.target = TestOsc::note_hz(note).log2() + cents / 1200.0;
        if !legato || self.playing.retrigger {
            v.stage = Stage::Attack;
            if legato {
                v.gap = gap;
            }
        }
    }

    fn apply(&mut self, e: Ev) {
        let mono = self.voices.len() == 1;
        match e {
            Ev::On { note, velocity } => {
                self.held.retain(|&(n, _)| n != note);
                self.held.push((note, velocity));
                if mono {
                    let legato = self.voices[0].note.is_some();
                    self.strike(0, note, velocity, legato);
                    return;
                }
                // The voice on this note, else the next free one round-robin, else the
                // oldest struck.
                let n = self.voices.len();
                let i = self
                    .voices
                    .iter()
                    .position(|v| v.note == Some(note))
                    .or_else(|| {
                        (0..n)
                            .map(|k| (self.next_voice + k) % n)
                            .find(|&k| self.voices[k].note.is_none())
                    })
                    .unwrap_or_else(|| {
                        (0..n)
                            .min_by_key(|&k| self.voices[k].struck)
                            .expect("a voice")
                    });
                self.next_voice = (i + 1) % n;
                self.strike(i, note, velocity, false);
            }
            Ev::Off { note } => {
                self.held.retain(|&(n, _)| n != note);
                if self.held.is_empty() {
                    self.pressure = 0.0;
                }
                if mono {
                    match self.held.last().copied() {
                        // Back to the key still held (legato).
                        Some((k, vel)) if self.voices[0].note == Some(note) => {
                            self.strike(0, k, vel, true)
                        }
                        Some(_) => {}
                        None => {
                            self.voices[0].note = None;
                            self.voices[0].stage = Stage::Release;
                        }
                    }
                    return;
                }
                for v in &mut self.voices {
                    if v.note == Some(note) {
                        v.note = None;
                        v.stage = Stage::Release;
                    }
                }
            }
            Ev::Pressure(p) => self.pressure = p as f64 / 127.0,
            Ev::Pedal(_) => {}
        }
    }

    /// The next `out.len()` samples with `events` (offsets in the block, rising).
    pub fn process(&mut self, events: &[(usize, Ev)], out: &mut [f32]) {
        let t = self.tables.clone();
        let p = self.panel;
        let rate = self.rate;
        let dt = 1.0 / rate;
        // What the panel sets, once per block.
        let tc = |pos: f64, (lo, hi): (f64, f64)| lo + (hi - lo) * taper(pos, t.env_mid);
        let (ta, td, tr) = (
            tc(p.attack, t.attack_s),
            tc(p.decay, t.decay_s),
            tc(p.release, t.release_s),
        );
        let (ka, kd, kr) = (
            1.0 - (-dt / ta).exp(),
            1.0 - (-dt / td).exp(),
            1.0 - (-dt / tr).exp(),
        );
        let sustain_v = t.sustain_v.0 + (t.sustain_v.1 - t.sustain_v.0) * p.sustain;
        let glide_tau = t.glide.at(p.glide).max(1e-4);
        let kg = 1.0 - (-dt / glide_tau).exp();
        let lfo_hz = if p.lfo_audio {
            t.lfo_audio.at(p.lfo_rate)
        } else {
            t.lfo_low.at(p.lfo_rate)
        };
        let lfo_on = p.lfo_on;
        let osc = if p.osc_on {
            taper(p.osc_level, t.mix_mid)
        } else {
            0.0
        };
        let saw = if p.saw_on {
            taper(p.saw_level, t.mix_mid) * 10f64.powf(t.saw_db / 20.0)
        } else {
            0.0
        };
        let ring = if p.ring_on && lfo_on {
            taper(p.ring, t.mix_mid) * 10f64.powf(t.ring_db / 20.0)
        } else {
            0.0
        };
        let osc_bleed = ring * 10f64.powf(t.ring_osc_bleed_db / 20.0);
        let carrier_bleed = ring * 10f64.powf(t.ring_carrier_bleed_db / 20.0);
        let g4_base = t.cutoff_g4.at(p.cutoff);
        let fade = t.resonance_fade.at(p.cutoff);
        // The wave's tables and their mix.
        let (w0, w1, wf) = if p.wave <= 0.5 {
            (0, 1, p.wave / 0.5)
        } else {
            (1, 2, (p.wave - 0.5) / 0.5)
        };
        let mut e = 0;
        let last = out.len().saturating_sub(1);
        for (s, y) in out.iter_mut().enumerate() {
            while e < events.len() && events[e].0.min(last) <= s {
                self.apply(events[e].1);
                e += 1;
            }
            let control = self.counter.is_multiple_of(CONTROL_EVERY);
            if control {
                // Its phase kept exactly; the sine between, a rotation.
                self.lfo_phase = (self.lfo_phase + lfo_hz * dt * CONTROL_EVERY as f64).fract();
                let a = std::f64::consts::TAU * self.lfo_phase;
                let w = std::f64::consts::TAU * lfo_hz * dt;
                (self.lfo_s, self.lfo_c, self.rot_s, self.rot_c) =
                    (a.sin(), a.cos(), w.sin(), w.cos());
            }
            let lfo = if lfo_on { self.lfo_s } else { 0.0 };
            (self.lfo_s, self.lfo_c) = (
                self.lfo_s * self.rot_c + self.lfo_c * self.rot_s,
                self.lfo_c * self.rot_c - self.lfo_s * self.rot_s,
            );
            self.counter = self.counter.wrapping_add(1);
            let mut sum = 0.0;
            for v in &mut self.voices {
                if v.silent() {
                    continue;
                }
                // The envelope, in the bus's volts.
                let gate = v.note.is_some() && v.gap == 0;
                v.gap = v.gap.saturating_sub(1);
                match (v.stage, gate) {
                    (_, false) if v.note.is_none() => v.env_v += (REST_V - v.env_v) * kr,
                    (Stage::Attack, true) => {
                        v.env_v += (v.key_v - v.env_v) * ka;
                        if v.env_v >= v.key_v - 1.0 {
                            v.stage = Stage::Decay;
                        }
                    }
                    (Stage::Decay, true) => {
                        let to = sustain_v.max(REST_V).min(v.key_v);
                        v.env_v += (to - v.env_v) * kd;
                    }
                    (_, false) => v.env_v += (REST_V - v.env_v) * kr,
                    (Stage::Release, true) => v.stage = Stage::Attack,
                }
                // The pitch glides per sample; what costs (the pitch's and the level's
                // exponentials, the filter's coefficients) every CONTROL_EVERY samples,
                // ramped between.
                v.pitch += (v.target - v.pitch) * kg;
                if control {
                    let n = CONTROL_EVERY as f64;
                    let hz = 2f64.powf(v.pitch + p.vibrato * t.vibrato_cents / 1200.0 * lfo);
                    let inc = hz * dt;
                    v.d_inc = (inc - v.inc) / n;
                    if v.inc == 0.0 {
                        (v.inc, v.d_inc) = (inc, 0.0);
                    }
                    v.octave =
                        ((hz / TABLE_BASE_HZ).log2().floor().max(0.0) as usize).min(OCTAVES - 1);
                    let level = if v.env_v <= REST_V + 0.5 {
                        0.0
                    } else {
                        10f64.powf(t.vca_db.at(v.env_v) / 20.0)
                    };
                    v.d_level = (level - v.level) / n;
                    // V4's grid: the panel's sum (see the module docs).
                    let key = v.last_note as f64 - 60.0;
                    let env = ((v.env_v - REST_V) / (-1.0 - REST_V)).clamp(0.0, 1.0);
                    let g4 = g4_base
                        + p.key_track * t.key_track_per_semitone * key
                        + p.pressure * t.pressure_per_v * t.pressure_full_v * self.pressure
                        + p.env_amount * t.env_g4 * env
                        + p.wobble * t.wobble_g4_pp * 0.5 * lfo;
                    let f0 = t.f0.at(g4).min(0.45 * rate);
                    let q0 = t.q.at(g4);
                    let q = q0 + (t.resonance_q - q0).max(0.0) * p.resonance * fade;
                    v.g = (std::f64::consts::PI * f0 / rate).tan();
                    v.k = 1.0 / q.max(0.1);
                    v.a1 = 1.0 / (1.0 + v.g * (v.g + v.k));
                }
                let inc = v.inc;
                v.inc += v.d_inc;
                let level = v.level;
                v.level = (v.level + v.d_level).max(0.0);
                // The oscillators.
                let tb = &self.tables_by_octave[v.octave];
                let x = v.phase * TABLE_N as f64;
                let i0 = (x as usize).min(TABLE_N - 1);
                let fr = (x - i0 as f64) as f32;
                let i1 = if i0 + 1 == TABLE_N { 0 } else { i0 + 1 };
                let look = |t: &[f32]| t[i0] + (t[i1] - t[i0]) * fr;
                let lc = (look(&tb[w0]) as f64) * (1.0 - wf) + (look(&tb[w1]) as f64) * wf;
                v.phase += inc;
                if v.phase >= 1.0 {
                    v.phase -= 1.0;
                }
                let sw = if saw != 0.0 {
                    let d = inc.min(0.5);
                    let tt = v.saw;
                    let blep = if tt < d {
                        let u = tt / d;
                        2.0 * u - u * u - 1.0
                    } else if tt > 1.0 - d {
                        let u = (tt - 1.0) / d;
                        u * u + 2.0 * u + 1.0
                    } else {
                        0.0
                    };
                    v.saw += inc;
                    if v.saw >= 1.0 {
                        v.saw -= 1.0;
                    }
                    2.0 * tt - 1.0 - blep
                } else {
                    0.0
                };
                let mix =
                    osc * lc + saw * sw + ring * lc * lfo + osc_bleed * lc + carrier_bleed * lfo;
                // The filter (TPT SVF, low-pass).
                let (g, a1) = (v.g, v.a1);
                let v3 = mix - v.ic2;
                let v1 = a1 * v.ic1 + g * a1 * v3;
                let v2 = v.ic2 + g * v1;
                v.ic1 = 2.0 * v1 - v.ic1;
                v.ic2 = 2.0 * v2 - v.ic2;
                sum += v2 * level * v.key_gain;
            }
            *y = sum as f32;
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::Arc;

    fn tables() -> Arc<Tables> {
        let config = Path::new(env!("CARGO_MANIFEST_DIR")).join("../../config");
        Arc::new(
            Tables::load(&config, "tube_synth")
                .unwrap()
                .expect("the tables"),
        )
    }

    fn rms_db(y: &[f32]) -> f64 {
        let r = (y.iter().map(|&v| (v as f64).powi(2)).sum::<f64>() / y.len() as f64).sqrt();
        20.0 * r.max(1e-12).log10()
    }

    /// The fundamental's frequency from zero crossings (rising) over `y`.
    fn freq(y: &[f32], rate: f64) -> f64 {
        let ups: Vec<f64> = y
            .windows(2)
            .enumerate()
            .filter(|(_, w)| w[0] < 0.0 && w[1] >= 0.0)
            .map(|(i, w)| i as f64 + w[0] as f64 / (w[0] - w[1]) as f64)
            .collect();
        (ups.len() - 1) as f64 / ((ups[ups.len() - 1] - ups[0]) / rate)
    }

    #[test]
    fn a_held_key_plays_its_pitch_at_the_circuits_level() {
        let t = tables();
        let mut p = Proxy::new(t.clone(), 48_000, 1);
        let mut y = vec![0.0f32; 48_000];
        p.process(
            &[(
                0,
                Ev::On {
                    note: 69,
                    velocity: 127,
                },
            )],
            &mut y,
        );
        let f = freq(&y[24_000..], 48_000.0);
        // Where the device's tuning puts A4 (equal temperament without the measurement).
        let want = 440.0 * 2f64.powf(t.key_cents.as_ref().map_or(0.0, |c| c.at(69.0)) / 1200.0);
        let cents = 1200.0 * (f / want).log2();
        assert!(cents.abs() < 2.0, "A4 at {f} Hz, the device's at {want}");
        // At the defaults, held (SUSTAIN 1), its level is the circuit's (calibrated at B4).
        let mut p = Proxy::new(t.clone(), 48_000, 1);
        let mut y = vec![0.0f32; 48_000];
        p.process(
            &[(
                0,
                Ev::On {
                    note: 71,
                    velocity: 127,
                },
            )],
            &mut y,
        );
        let want = t
            .key_level
            .as_ref()
            .map_or(t.level_dbfs + t.vca_db.at(t.sustain_v.1), |k| {
                Curve(k.clone()).at(71.0)
            });
        assert!((rms_db(&y[24_000..]) - want).abs() < 0.2);
        // Released, it falls silent (RELEASE 0.4).
        let mut tail = vec![0.0f32; 96_000];
        p.process(&[(0, Ev::Off { note: 71 })], &mut tail);
        assert!(rms_db(&tail[90_000..]) < want - 60.0);
        assert_eq!(p.sounding(), 0);
    }

    #[test]
    fn the_cutoff_follows_the_panel_and_glide_takes_its_time() {
        let t = tables();
        let level = |cutoff: f64| {
            let mut p = Proxy::new(t.clone(), 48_000, 1);
            p.set_values(&vec![
                ("cutoff".into(), varimu_circuit::yaml::Value::Float(cutoff)),
                ("wave".into(), varimu_circuit::yaml::Value::Float(1.0)),
                ("resonance".into(), varimu_circuit::yaml::Value::Float(0.0)),
            ]);
            let mut y = vec![0.0f32; 24_000];
            p.process(
                &[(
                    0,
                    Ev::On {
                        note: 36,
                        velocity: 127,
                    },
                )],
                &mut y,
            );
            // The upper harmonics' share: the first difference's level re the signal's.
            let d: Vec<f32> = y[12_000..].windows(2).map(|w| w[1] - w[0]).collect();
            rms_db(&d) - rms_db(&y[12_000..])
        };
        let (dark, bright) = (level(0.0), level(1.0));
        eprintln!("a C2 square's highs: {dark:.1} dB at CUTOFF 0, {bright:.1} at 1");
        assert!(
            bright > dark + 6.0,
            "a brighter filter passes more of a square's harmonics"
        );
        // GLIDE 1: a fifth up takes a measured ~0.3 s time constant.
        let mut p = Proxy::new(t.clone(), 48_000, 1);
        p.set_values(&vec![(
            "glide".into(),
            varimu_circuit::yaml::Value::Float(1.0),
        )]);
        let mut y = vec![0.0f32; 48_000];
        p.process(
            &[(
                0,
                Ev::On {
                    note: 60,
                    velocity: 127,
                },
            )],
            &mut y,
        );
        let mut y = vec![0.0f32; 4_800];
        p.process(
            &[(
                0,
                Ev::On {
                    note: 67,
                    velocity: 127,
                },
            )],
            &mut y,
        );
        let f = freq(&y, 48_000.0);
        assert!(f < 0.9 * TestOsc::note_hz(67), "still gliding at {f} Hz");
    }

    #[test]
    fn voices_are_allocated_and_sixteen_cost_little() {
        let t = tables();
        let mut p = Proxy::new(t, 48_000, 4);
        let on = |n| Ev::On {
            note: n,
            velocity: 100,
        };
        let mut y = vec![0.0f32; 480];
        p.process(&[(0, on(60)), (1, on(64)), (2, on(67))], &mut y);
        assert_eq!(p.sounding(), 3);
        // The same note again takes the voice already on it.
        p.process(&[(0, on(64))], &mut y);
        assert_eq!(p.voices.iter().filter(|v| v.note == Some(64)).count(), 1);
        // A fifth key steals the oldest.
        p.process(&[(0, on(72)), (1, on(76))], &mut y);
        assert!(p.voices.iter().all(|v| v.note != Some(60)));
        // Sixteen voices, ten seconds: the time it takes.
        let mut p = Proxy::new(tables(), 48_000, MAX_VOICES);
        let ev: Vec<(usize, Ev)> = (0..16).map(|i| (i, on(40 + 3 * i as u8))).collect();
        let mut y = vec![0.0f32; 64];
        p.process(&ev, &mut y);
        let t0 = std::time::Instant::now();
        for _ in 0..(480_000 / 64) {
            p.process(&[], &mut y);
        }
        let share = t0.elapsed().as_secs_f64() / 10.0;
        eprintln!("16 voices: {:.2}% of a core", share * 100.0);
        assert_eq!(p.sounding(), 16);
        assert!(share < 0.05, "{share}");
    }
}
