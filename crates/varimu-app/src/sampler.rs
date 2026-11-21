//! The sampler: a kit of [`SLOTS`] sounds, one per key of an octave, played from a MIDI
//! keyboard (or the pads on screen) through the player (`player::Source::Sampler`), so the
//! Session view records it like any instrument. Not a device: no circuit, plain playback.
//!
//! A key plays its slot by pitch class (every C plays slot 1, every C# slot 2, ...), so the
//! kit sits under any octave of the keyboard. Each hit is a voice of its own (polyphonic, up
//! to [`MAX_VOICES`], the oldest dropped), at the velocity's level, read at the file's own
//! rate with cubic (Catmull-Rom) interpolation to the host rate. Files are mono (channels
//! averaged) as everywhere in the app.
//!
//! **Preview**: a browsed file plays at once on a voice of its own ([`Sampler::preview`]),
//! a new one cutting the last, at the preview level ([`Sampler::preview_db`], its own
//! slider: one-shots are normalized near full scale); it is heard but never recorded (the
//! player keeps the kit's voices apart for the take).
//!
//! **MIDI takes** (docs/MIDI_TAKES_PLAN.md): the sampler is an instrument like the circuit
//! devices, so a take from it can be its notes ([`DEVICE_ID`]). The performance holds the
//! kit as it was ([`Sampler::values`]: each slot's file, the level, velocity) and its
//! changes as knob changes; [`render_performance`] replays it offline with the same
//! [`Engine`] in the player's blocks, so the audio heard and its render agree, and an edit
//! in the piano roll renders in a moment. A pad on screen records as its slot's key in
//! octave 4 ([`PAD_NOTE`]).
//!
//! The kit (the slots' files) is the user's, kept outside the repo beside the app's
//! settings (`sampler.json` next to `prefs::path()`).

use std::collections::{HashMap, VecDeque};
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::{Arc, Mutex};

use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use varimu_circuit::yaml::Value as Knob;

use crate::audio;
use crate::live::Values;
use crate::performance::{Ev, Performance};
use crate::player::SAMPLER_BLOCK;

/// The sampler's id where a device's would be (a take's `device`, a performance's).
pub const DEVICE_ID: &str = "sampler";
/// The key a pad on screen records as: its slot's key from C4.
pub const PAD_NOTE: u8 = 60;
/// How long a pad's key is held in a take (one-shots ignore it; the roll shows it).
pub const PAD_HOLD_S: f64 = 0.1;
/// A new kit's preview level (dB).
pub const DEFAULT_PREVIEW_DB: f64 = -12.0;

/// Slots in a kit: one octave.
pub const SLOTS: usize = 12;
/// Voices sounding at once (the oldest stops when a new hit needs one).
pub const MAX_VOICES: usize = 32;
/// Note-ons kept for the player between its blocks (more are dropped, oldest first).
const MAX_PENDING: usize = 256;
/// A new kit's level (dB): one-shots are normalized near full scale, and a kick with a hat
/// at 0 dB peaked +2.3 dBFS (examples/sampler.rs).
pub const DEFAULT_GAIN_DB: f64 = -6.0;

/// A sound: mono samples at the file's rate.
#[derive(Debug)]
pub struct Sample {
    pub path: PathBuf,
    pub data: Vec<f32>,
    pub rate: u32,
}

impl Sample {
    /// The file decoded (any format the app reads), channels averaged.
    pub fn load(path: &Path) -> Result<Sample, String> {
        let d = audio::decode(path)?;
        Ok(Sample {
            path: path.to_path_buf(),
            data: d.mono().into_iter().map(|v| v as f32).collect(),
            rate: d.rate,
        })
    }

    pub fn seconds(&self) -> f64 {
        self.data.len() as f64 / self.rate.max(1) as f64
    }

    /// The file's name without its extension.
    pub fn name(&self) -> String {
        self.path
            .file_stem()
            .map_or_else(String::new, |s| s.to_string_lossy().into_owned())
    }
}

/// The slot a MIDI note plays: its pitch class.
pub fn slot_of(note: u8) -> usize {
    note as usize % SLOTS
}

/// The kit and what the window asks of the player: shared between them.
#[derive(Debug)]
pub struct Sampler {
    slots: Mutex<Vec<Option<Arc<Sample>>>>,
    /// Hits from the pads on screen (slot, velocity), for the player's next block.
    pads: Mutex<VecDeque<(usize, u8)>>,
    /// The file to preview with its level (taken by the player's next block), and a stop
    /// asked for.
    preview: Mutex<Option<(Arc<Sample>, f32)>>,
    stop_preview: AtomicBool,
    /// The preview's level (dB, f64 bits): it follows the slider while a preview sounds.
    preview_db: AtomicU64,
    /// The kit's level (dB, f64 bits) and whether velocity sets each hit's level.
    gain_db: AtomicU64,
    velocity: AtomicBool,
    /// Moves with every change to what a take records of the kit (slots, level, velocity).
    generation: AtomicU64,
    /// Hits per slot so far (the window lights a slot when its count moves).
    hits: Vec<AtomicU64>,
}

impl Default for Sampler {
    fn default() -> Sampler {
        Sampler {
            slots: Mutex::new(vec![None; SLOTS]),
            pads: Mutex::new(VecDeque::new()),
            preview: Mutex::new(None),
            stop_preview: AtomicBool::new(false),
            preview_db: AtomicU64::new(DEFAULT_PREVIEW_DB.to_bits()),
            gain_db: AtomicU64::new(DEFAULT_GAIN_DB.to_bits()),
            velocity: AtomicBool::new(true),
            generation: AtomicU64::new(0),
            hits: (0..SLOTS).map(|_| AtomicU64::new(0)).collect(),
        }
    }
}

impl Sampler {
    pub fn slot(&self, i: usize) -> Option<Arc<Sample>> {
        self.slots.lock().expect("slots").get(i).cloned().flatten()
    }

    pub fn set_slot(&self, i: usize, s: Option<Arc<Sample>>) {
        if let Some(x) = self.slots.lock().expect("slots").get_mut(i) {
            *x = s;
        }
        self.generation.fetch_add(1, Ordering::Relaxed);
    }

    /// A count that moves whenever what a take records of the kit changes.
    pub fn generation(&self) -> u64 {
        self.generation.load(Ordering::Relaxed)
    }

    /// The pads hit since the last call (slot, velocity), oldest first.
    pub fn take_pads(&self) -> Vec<(usize, u8)> {
        self.pads.lock().expect("pads").drain(..).collect()
    }

    /// The kit as a take records it: `slot_1` .. `slot_12` (each a file's path, or null),
    /// `gain_db` and `velocity`.
    pub fn values(&self) -> Values {
        let mut v: Values = (0..SLOTS)
            .map(|i| {
                let path = self
                    .slot(i)
                    .map_or(Knob::Null, |s| Knob::Str(s.path.display().to_string()));
                (format!("slot_{}", i + 1), path)
            })
            .collect();
        v.push(("gain_db".into(), Knob::Float(self.gain_db())));
        v.push(("velocity".into(), Knob::Bool(self.velocity())));
        v
    }

    /// The kit set from [`Sampler::values`]' form, its files from `cache` (loaded into it as
    /// needed). A file that no longer loads is an error: a render of it would be silent.
    pub fn apply_values(
        &self,
        v: &Values,
        cache: &mut HashMap<String, Arc<Sample>>,
    ) -> Result<(), String> {
        for (k, x) in v {
            if let Some(i) = k
                .strip_prefix("slot_")
                .and_then(|n| n.parse::<usize>().ok())
                .filter(|&n| (1..=SLOTS).contains(&n))
            {
                let s = match x {
                    Knob::Str(p) => Some(match cache.get(p) {
                        Some(s) => s.clone(),
                        None => {
                            let s = Arc::new(Sample::load(Path::new(p))?);
                            cache.insert(p.clone(), s.clone());
                            s
                        }
                    }),
                    _ => None,
                };
                self.set_slot(i - 1, s);
            } else if k == "gain_db" {
                match x {
                    Knob::Float(g) => self.set_gain_db(*g),
                    Knob::Int(g) => self.set_gain_db(*g as f64),
                    _ => {}
                }
            } else if k == "velocity"
                && let Knob::Bool(b) = x
            {
                self.set_velocity(*b);
            }
        }
        Ok(())
    }

    /// Play slot `i` now (a pad clicked), as a key at `velocity` would.
    pub fn hit(&self, i: usize, velocity: u8) {
        let mut q = self.pads.lock().expect("pads");
        q.push_back((i, velocity));
        while q.len() > MAX_PENDING {
            q.pop_front();
        }
    }

    /// Play `s` on the preview voice (cutting the one before), at the preview level.
    pub fn preview(&self, s: Arc<Sample>) {
        self.preview_at(s, 1.0);
    }

    /// [`Sampler::preview`] at `level` (a linear factor on the preview level: a piano
    /// roll's note at its velocity).
    pub fn preview_at(&self, s: Arc<Sample>, level: f32) {
        *self.preview.lock().expect("preview") = Some((s, level));
    }

    pub fn stop_preview(&self) {
        *self.preview.lock().expect("preview") = None;
        self.stop_preview.store(true, Ordering::Relaxed);
    }

    /// The preview's level (dB).
    pub fn preview_db(&self) -> f64 {
        f64::from_bits(self.preview_db.load(Ordering::Relaxed))
    }

    pub fn set_preview_db(&self, db: f64) {
        self.preview_db.store(db.to_bits(), Ordering::Relaxed);
    }

    pub fn gain_db(&self) -> f64 {
        f64::from_bits(self.gain_db.load(Ordering::Relaxed))
    }

    pub fn set_gain_db(&self, db: f64) {
        if db.to_bits() != self.gain_db.swap(db.to_bits(), Ordering::Relaxed) {
            self.generation.fetch_add(1, Ordering::Relaxed);
        }
    }

    pub fn velocity(&self) -> bool {
        self.velocity.load(Ordering::Relaxed)
    }

    pub fn set_velocity(&self, on: bool) {
        if on != self.velocity.swap(on, Ordering::Relaxed) {
            self.generation.fetch_add(1, Ordering::Relaxed);
        }
    }

    /// A hit's level at `velocity`: the kit's level, times velocity's share when it counts.
    fn hit_gain(&self, velocity: u8) -> f32 {
        let level = if self.velocity() {
            velocity.min(127) as f32 / 127.0
        } else {
            1.0
        };
        10f32.powf(self.gain_db() as f32 / 20.0) * level
    }

    /// How many times slot `i` has been played.
    pub fn hits(&self, i: usize) -> u64 {
        self.hits.get(i).map_or(0, |h| h.load(Ordering::Relaxed))
    }

    /// Where the kit is kept (None: no user directory known).
    pub fn kit_path() -> Option<PathBuf> {
        crate::prefs::path().map(|p| p.with_file_name("sampler.json"))
    }

    /// The slots' files, the level and velocity, as JSON.
    pub fn to_json(&self) -> Value {
        let slots: Vec<Value> = (0..SLOTS)
            .map(|i| {
                self.slot(i)
                    .map_or(Value::Null, |s| json!(s.path.display().to_string()))
            })
            .collect();
        json!({
            "slots": slots,
            "gain_db": self.gain_db(),
            "velocity": self.velocity(),
            "preview_db": self.preview_db(),
        })
    }

    /// Fill the kit from [`Sampler::to_json`]'s form; files that no longer load are left
    /// empty and named in the errors.
    pub fn load_json(&self, v: &Value) -> Vec<String> {
        let mut errors = Vec::new();
        if let Some(a) = v["slots"].as_array() {
            for (i, p) in a.iter().enumerate().take(SLOTS) {
                let s = p.as_str().and_then(|p| match Sample::load(Path::new(p)) {
                    Ok(s) => Some(Arc::new(s)),
                    Err(e) => {
                        errors.push(e);
                        None
                    }
                });
                self.set_slot(i, s);
            }
        }
        if let Some(g) = v["gain_db"].as_f64() {
            self.set_gain_db(g);
        }
        if let Some(b) = v["velocity"].as_bool() {
            self.set_velocity(b);
        }
        if let Some(g) = v["preview_db"].as_f64() {
            self.set_preview_db(g);
        }
        errors
    }

    pub fn save(&self) -> Result<(), String> {
        let p = Sampler::kit_path().ok_or("no user settings directory")?;
        if let Some(dir) = p.parent() {
            std::fs::create_dir_all(dir).map_err(|e| e.to_string())?;
        }
        let text = serde_json::to_string_pretty(&self.to_json()).map_err(|e| e.to_string())?;
        std::fs::write(&p, text).map_err(|e| format!("{}: {e}", p.display()))
    }

    /// The saved kit (an empty one if there is none).
    pub fn load_saved(&self) -> Vec<String> {
        let Some(text) = Sampler::kit_path().and_then(|p| std::fs::read_to_string(p).ok()) else {
            return Vec::new();
        };
        match serde_json::from_str::<Value>(&text) {
            Ok(v) => self.load_json(&v),
            Err(e) => vec![format!("sampler.json: {e}")],
        }
    }
}

#[derive(Debug)]
struct Voice {
    sample: Arc<Sample>,
    /// Where it is in the sample (its samples), and how far a host sample moves it.
    pos: f64,
    step: f64,
    gain: f32,
}

impl Voice {
    fn new(sample: Arc<Sample>, host_rate: u32, gain: f32) -> Voice {
        let step = sample.rate as f64 / host_rate as f64;
        Voice {
            sample,
            pos: 0.0,
            step,
            gain,
        }
    }

    fn done(&self) -> bool {
        self.pos >= self.sample.data.len() as f64
    }

    /// Add its next `out.len()` samples into `out`.
    fn add(&mut self, out: &mut [f32]) {
        let x = &self.sample.data;
        let n = x.len() as isize;
        let at = |i: isize| {
            if (0..n).contains(&i) {
                x[i as usize]
            } else {
                0.0
            }
        };
        for o in out.iter_mut() {
            if self.done() {
                return;
            }
            let i = self.pos.floor() as isize;
            let t = (self.pos - i as f64) as f32;
            let (y0, y1, y2, y3) = (at(i - 1), at(i), at(i + 1), at(i + 2));
            // Catmull-Rom: exact on the samples (t = 0), a cubic between them.
            let v = y1
                + 0.5
                    * t
                    * (y2 - y0
                        + t * (2.0 * y0 - 5.0 * y1 + 4.0 * y2 - y3
                            + t * (3.0 * (y1 - y2) + y3 - y0)));
            *o += self.gain * v;
            self.pos += self.step;
        }
    }
}

/// The player's side: the voices sounding.
#[derive(Debug)]
pub struct Engine {
    rate: u32,
    voices: Vec<Voice>,
    /// The preview's voice (its gain the level it was asked at; the slider's on top).
    preview: Option<Voice>,
}

impl Engine {
    pub fn new(host_rate: u32) -> Engine {
        Engine {
            rate: host_rate,
            voices: Vec::new(),
            preview: None,
        }
    }

    /// Voices sounding (the kit's, not the preview).
    pub fn sounding(&self) -> usize {
        self.voices.len()
    }

    /// A key: its slot's sound from the start (nothing in an empty slot).
    pub fn note_on(&mut self, sampler: &Sampler, note: u8, velocity: u8) {
        self.trigger(sampler, slot_of(note), velocity);
    }

    fn trigger(&mut self, sampler: &Sampler, slot: usize, velocity: u8) {
        let Some(s) = sampler.slot(slot) else { return };
        if let Some(h) = sampler.hits.get(slot) {
            h.fetch_add(1, Ordering::Relaxed);
        }
        let g = sampler.hit_gain(velocity);
        if self.voices.len() >= MAX_VOICES {
            self.voices.remove(0);
        }
        self.voices.push(Voice::new(s, self.rate, g));
    }

    /// The next block: the kit's voices into `kit`, the preview into `preview` (both
    /// overwritten), after the pads hit and the preview asked for since the last block.
    pub fn render(&mut self, sampler: &Sampler, kit: &mut [f32], preview: &mut [f32]) {
        for (slot, vel) in sampler.take_pads() {
            self.trigger(sampler, slot, vel);
        }
        self.process(sampler, &[], kit, preview);
    }

    /// The next block with `events` (offset in the block, in order): each key down starts
    /// its slot at its own sample; the rest (keys up, pressure, the pedal) mean nothing to
    /// one-shots. The kit's voices into `kit`, the preview into `preview` (both
    /// overwritten). The pads aren't taken here: the player records them as keys.
    pub fn process(
        &mut self,
        sampler: &Sampler,
        events: &[(usize, Ev)],
        kit: &mut [f32],
        preview: &mut [f32],
    ) {
        if sampler.stop_preview.swap(false, Ordering::Relaxed) {
            self.preview = None;
        }
        if let Some((s, level)) = sampler.preview.lock().expect("preview").take() {
            self.preview = Some(Voice::new(s, self.rate, level));
        }
        kit.fill(0.0);
        preview.fill(0.0);
        let mut from = 0;
        for &(at, ev) in events {
            let at = at.clamp(from, kit.len());
            if at > from {
                self.add_voices(&mut kit[from..at]);
                from = at;
            }
            if let Ev::On { note, velocity } = ev {
                self.note_on(sampler, note, velocity);
            }
        }
        self.add_voices(&mut kit[from..]);
        if let Some(v) = &mut self.preview {
            v.add(preview);
            if v.done() {
                self.preview = None;
            }
            let g = 10f32.powf(sampler.preview_db() as f32 / 20.0);
            for p in preview.iter_mut() {
                *p *= g;
            }
        }
    }

    fn add_voices(&mut self, out: &mut [f32]) {
        if out.is_empty() {
            return;
        }
        for v in &mut self.voices {
            v.add(out);
        }
        self.voices.retain(|v| !v.done());
    }
}

/// A sampler take's events and kit changes, block by block as the player made them: the
/// kit's voices at `perf.rate`, `perf.end` samples from its start (see the module docs).
/// Its files are read from disk (`cache` holds them between calls).
pub fn render_performance(
    perf: &Performance,
    cache: &mut HashMap<String, Arc<Sample>>,
) -> Result<Vec<f32>, String> {
    let sampler = Sampler::default();
    sampler.apply_values(&perf.values, cache)?;
    let mut engine = Engine::new(perf.rate);
    let total = perf.end as usize;
    let mut out = vec![0.0f32; total.div_ceil(SAMPLER_BLOCK) * SAMPLER_BLOCK];
    let mut preview = vec![0.0f32; SAMPLER_BLOCK];
    let (mut e, mut k) = (0, 0);
    let mut events = Vec::new();
    for (b, kit) in out.chunks_mut(SAMPLER_BLOCK).enumerate() {
        let (start, end) = ((b * SAMPLER_BLOCK) as u64, ((b + 1) * SAMPLER_BLOCK) as u64);
        // Kit changes logged in this block, at its start (the player logs them there).
        while k < perf.knobs.len() && perf.knobs[k].at < end {
            sampler.apply_values(&perf.knobs[k].values, cache)?;
            k += 1;
        }
        events.clear();
        while e < perf.events.len() && perf.events[e].0 < end {
            let (at, ev) = perf.events[e];
            events.push((at.saturating_sub(start) as usize, ev));
            e += 1;
        }
        engine.process(&sampler, &events, kit, &mut preview);
    }
    out.truncate(total);
    Ok(out)
}

/// What a sampler take's render is made from: the performance (the kit's paths in it) and
/// each file's size and modification time (a file replaced under the same name renders
/// again). The same at every quality: a sampler plays its files as they are.
pub fn render_key(perf: &Performance) -> Result<String, String> {
    let mut h = Sha256::new();
    h.update(b"varimu sampler take render 1\n");
    h.update(serde_json::to_vec(&perf.to_json()).map_err(|e| e.to_string())?);
    let mut paths: Vec<&str> = perf
        .values
        .iter()
        .chain(perf.knobs.iter().flat_map(|k| k.values.iter()))
        .filter_map(|(_, v)| match v {
            Knob::Str(p) => Some(p.as_str()),
            _ => None,
        })
        .collect();
    paths.sort_unstable();
    paths.dedup();
    for p in paths {
        let m = std::fs::metadata(p).map_err(|e| format!("{p}: {e}"))?;
        let t = m
            .modified()
            .ok()
            .and_then(|t| t.duration_since(std::time::UNIX_EPOCH).ok())
            .map_or(0, |d| d.as_nanos());
        h.update(format!("{p}\n{}\n{t}\n", m.len()).as_bytes());
    }
    Ok(h.finalize()[..16]
        .iter()
        .map(|b| format!("{b:02x}"))
        .collect())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn sample(data: Vec<f32>, rate: u32) -> Arc<Sample> {
        Arc::new(Sample {
            path: PathBuf::from("x.wav"),
            data,
            rate,
        })
    }

    #[test]
    fn every_octave_plays_the_same_slots() {
        assert_eq!(slot_of(60), 0); // C4
        assert_eq!(slot_of(36), 0); // C2
        assert_eq!(slot_of(61), 1);
        assert_eq!(slot_of(71), 11);
    }

    #[test]
    fn a_key_plays_its_slot_at_its_velocity_and_ends() {
        let s = Sampler::default();
        s.set_gain_db(0.0);
        s.set_slot(2, Some(sample(vec![1.0, 0.5, 0.25], 48_000)));
        let mut e = Engine::new(48_000);
        e.note_on(&s, 62, 127); // D: slot 2
        e.note_on(&s, 63, 127); // D#: empty, silent
        let (mut kit, mut pre) = (vec![0.0; 5], vec![0.0; 5]);
        e.render(&s, &mut kit, &mut pre);
        assert_eq!(kit, vec![1.0, 0.5, 0.25, 0.0, 0.0]);
        assert_eq!(e.sounding(), 0);
        assert_eq!(s.hits(2), 1);
        e.note_on(&s, 62, 64);
        e.render(&s, &mut kit, &mut pre);
        assert!((kit[0] - 64.0 / 127.0).abs() < 1e-6);
    }

    #[test]
    fn hits_overlap_and_the_preview_stays_apart() {
        let s = Sampler::default();
        s.set_gain_db(0.0);
        s.set_preview_db(0.0);
        s.set_slot(0, Some(sample(vec![1.0; 4], 48_000)));
        let mut e = Engine::new(48_000);
        e.note_on(&s, 60, 127);
        s.hit(0, 127);
        s.preview(sample(vec![0.5; 2], 48_000));
        let (mut kit, mut pre) = (vec![0.0; 4], vec![0.0; 4]);
        e.render(&s, &mut kit, &mut pre);
        assert_eq!(kit, vec![2.0; 4]);
        assert_eq!(pre, vec![0.5, 0.5, 0.0, 0.0]);
    }

    #[test]
    fn a_file_at_another_rate_plays_at_its_own_speed() {
        // A ramp at 24 kHz on a 48 kHz host: twice as many samples, halfway values between.
        let s = Sampler::default();
        s.set_gain_db(0.0);
        s.set_slot(0, Some(sample(vec![0.0, 1.0, 2.0, 3.0], 24_000)));
        let mut e = Engine::new(48_000);
        e.note_on(&s, 60, 127);
        let (mut kit, mut pre) = (vec![0.0; 8], vec![0.0; 8]);
        e.render(&s, &mut kit, &mut pre);
        for (k, want) in [(0, 0.0), (2, 1.0), (3, 1.5), (4, 2.0)] {
            assert!((kit[k] - want).abs() < 1e-6, "{k}: {}", kit[k]);
        }
    }

    #[test]
    fn the_preview_plays_at_its_own_level_and_follows_it() {
        let s = Sampler::default();
        s.set_preview_db(-20.0);
        s.preview(sample(vec![1.0; 8], 48_000));
        let mut e = Engine::new(48_000);
        let (mut kit, mut pre) = (vec![0.0; 4], vec![0.0; 4]);
        e.render(&s, &mut kit, &mut pre);
        assert!((pre[0] - 0.1).abs() < 1e-6, "{}", pre[0]);
        assert_eq!(kit, vec![0.0; 4]);
        // The slider moves while it sounds: the rest of it follows.
        s.set_preview_db(0.0);
        e.render(&s, &mut kit, &mut pre);
        assert!((pre[0] - 1.0).abs() < 1e-6);
        // The kit's level doesn't touch it, nor a take's record of the kit.
        let g = s.generation();
        s.set_preview_db(-6.0);
        assert_eq!(s.generation(), g);
    }

    #[test]
    fn a_key_starts_at_its_sample_in_the_block() {
        let s = Sampler::default();
        s.set_gain_db(0.0);
        s.set_slot(0, Some(sample(vec![1.0, 0.5], 48_000)));
        let mut e = Engine::new(48_000);
        let (mut kit, mut pre) = (vec![0.0; 6], vec![0.0; 6]);
        let ev = [
            (
                3,
                Ev::On {
                    note: 60,
                    velocity: 127,
                },
            ),
            (4, Ev::Off { note: 60 }),
            (
                5,
                Ev::On {
                    note: 72,
                    velocity: 127,
                },
            ),
        ];
        e.process(&s, &ev, &mut kit, &mut pre);
        assert_eq!(kit, vec![0.0, 0.0, 0.0, 1.0, 0.5, 1.0]);
        e.process(&s, &[], &mut kit, &mut pre);
        assert_eq!(kit[0], 0.5);
    }

    /// A take as the player records one (keys at their samples, a change of the kit
    /// mid-take at the block it was seen) replays offline bit for bit.
    #[test]
    fn a_take_replays_bit_for_bit() {
        use crate::performance::{Knob as KnobChange, Playing, START_NOTE};
        let dir = std::env::temp_dir().join(format!("varimu_sampler_{}", std::process::id()));
        std::fs::create_dir_all(&dir).unwrap();
        let (a, b) = (dir.join("a.wav"), dir.join("b.wav"));
        let tone = |f: f64, n: usize| -> Vec<f64> {
            (0..n)
                .map(|i| (i as f64 * f).sin() * (-(i as f64) / 900.0).exp())
                .collect()
        };
        crate::audio::write_wav(&a, &tone(0.05, 3000), 44_100).unwrap();
        crate::audio::write_wav(&b, &tone(0.31, 1500), 48_000).unwrap();
        let rate = 48_000;
        let live = Sampler::default();
        live.set_slot(0, Some(Arc::new(Sample::load(&a).unwrap())));
        live.set_slot(2, Some(Arc::new(Sample::load(&b).unwrap())));
        let mut perf = Performance {
            device: DEVICE_ID.into(),
            quality: crate::settings::Quality::Production,
            rate,
            values: live.values(),
            playing: Playing::default(),
            gain: 1.0,
            noise: false,
            start_note: START_NOTE,
            start_low: false,
            events: Vec::new(),
            knobs: Vec::new(),
            knobs_applied: false,
            end: 0,
        };
        // Block by block as work_sampler: (block, offset, event); the level and velocity
        // change at block 20.
        let plan: Vec<(usize, usize, Ev)> = vec![
            (
                1,
                10,
                Ev::On {
                    note: 60,
                    velocity: 100,
                },
            ),
            (
                2,
                63,
                Ev::On {
                    note: 62,
                    velocity: 64,
                },
            ),
            (5, 0, Ev::Off { note: 60 }),
            (
                5,
                0,
                Ev::On {
                    note: 48,
                    velocity: 127,
                },
            ),
            (
                21,
                7,
                Ev::On {
                    note: 62,
                    velocity: 30,
                },
            ),
            (
                22,
                7,
                Ev::On {
                    note: 61,
                    velocity: 127,
                },
            ), // an empty slot
        ];
        let mut engine = Engine::new(rate);
        let (mut kit, mut pre) = (vec![0.0; SAMPLER_BLOCK], vec![0.0; SAMPLER_BLOCK]);
        let mut heard = Vec::new();
        for blk in 0..40 {
            let at = (blk * SAMPLER_BLOCK) as u64;
            if blk == 20 {
                live.set_gain_db(-3.0);
                live.set_velocity(false);
                perf.knobs.push(KnobChange {
                    at,
                    values: live.values(),
                    restart: None,
                });
            }
            let ev: Vec<(usize, Ev)> = plan
                .iter()
                .filter(|(b, _, _)| *b == blk)
                .map(|&(_, o, e)| (o, e))
                .collect();
            engine.process(&live, &ev, &mut kit, &mut pre);
            perf.events
                .extend(ev.iter().map(|&(o, e)| (at + o as u64, e)));
            heard.extend_from_slice(&kit);
        }
        perf.end = heard.len() as u64 - 17; // a take ends anywhere
        heard.truncate(perf.end as usize);
        let mut cache = HashMap::new();
        let rendered = render_performance(&perf, &mut cache).unwrap();
        assert_eq!(rendered, heard);
        assert!(heard.iter().any(|&v| v != 0.0));
        // The key follows the kit's files.
        let k0 = render_key(&perf).unwrap();
        assert_eq!(render_key(&perf).unwrap(), k0);
        let mut moved = perf.clone();
        moved.events[0].0 += 1;
        assert_ne!(render_key(&moved).unwrap(), k0);
        // A performance survives its JSON (the kit's paths, a null slot, the level).
        let back = Performance::from_json(&perf.to_json()).unwrap();
        assert_eq!(render_performance(&back, &mut cache).unwrap(), heard);
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn the_oldest_voice_gives_way() {
        let s = Sampler::default();
        s.set_gain_db(0.0);
        s.set_slot(0, Some(sample(vec![1.0; 1000], 48_000)));
        let mut e = Engine::new(48_000);
        for _ in 0..MAX_VOICES + 5 {
            e.note_on(&s, 60, 127);
        }
        assert_eq!(e.sounding(), MAX_VOICES);
    }
}
