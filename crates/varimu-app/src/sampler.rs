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
//! a new one cutting the last; it is heard but never recorded (the player keeps the kit's
//! voices apart for the take).
//!
//! The kit (the slots' files) is the user's, kept outside the repo beside the app's
//! settings (`sampler.json` next to `prefs::path()`).

use std::collections::VecDeque;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::{Arc, Mutex};

use serde_json::{Value, json};

use crate::audio;

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
    /// The file to preview (taken by the player's next block), and a stop asked for.
    preview: Mutex<Option<Arc<Sample>>>,
    stop_preview: AtomicBool,
    /// The kit's level (dB, f64 bits) and whether velocity sets each hit's level.
    gain_db: AtomicU64,
    velocity: AtomicBool,
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
            gain_db: AtomicU64::new(DEFAULT_GAIN_DB.to_bits()),
            velocity: AtomicBool::new(true),
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
    }

    /// Play slot `i` now (a pad clicked), as a key at `velocity` would.
    pub fn hit(&self, i: usize, velocity: u8) {
        let mut q = self.pads.lock().expect("pads");
        q.push_back((i, velocity));
        while q.len() > MAX_PENDING {
            q.pop_front();
        }
    }

    /// Play `s` on the preview voice (cutting the one before).
    pub fn preview(&self, s: Arc<Sample>) {
        *self.preview.lock().expect("preview") = Some(s);
    }

    pub fn stop_preview(&self) {
        *self.preview.lock().expect("preview") = None;
        self.stop_preview.store(true, Ordering::Relaxed);
    }

    pub fn gain_db(&self) -> f64 {
        f64::from_bits(self.gain_db.load(Ordering::Relaxed))
    }

    pub fn set_gain_db(&self, db: f64) {
        self.gain_db.store(db.to_bits(), Ordering::Relaxed);
    }

    pub fn velocity(&self) -> bool {
        self.velocity.load(Ordering::Relaxed)
    }

    pub fn set_velocity(&self, on: bool) {
        self.velocity.store(on, Ordering::Relaxed);
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
        json!({"slots": slots, "gain_db": self.gain_db(), "velocity": self.velocity()})
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
        let level = if sampler.velocity() {
            velocity.min(127) as f32 / 127.0
        } else {
            1.0
        };
        let g = 10f32.powf(sampler.gain_db() as f32 / 20.0) * level;
        if self.voices.len() >= MAX_VOICES {
            self.voices.remove(0);
        }
        self.voices.push(Voice::new(s, self.rate, g));
    }

    /// The next block: the kit's voices into `kit`, the preview into `preview` (both
    /// overwritten), after the pads hit and the preview asked for since the last block.
    pub fn render(&mut self, sampler: &Sampler, kit: &mut [f32], preview: &mut [f32]) {
        let pads: Vec<(usize, u8)> = sampler.pads.lock().expect("pads").drain(..).collect();
        for (slot, vel) in pads {
            self.trigger(sampler, slot, vel);
        }
        if sampler.stop_preview.swap(false, Ordering::Relaxed) {
            self.preview = None;
        }
        if let Some(s) = sampler.preview.lock().expect("preview").take() {
            self.preview = Some(Voice::new(s, self.rate, 1.0));
        }
        kit.fill(0.0);
        preview.fill(0.0);
        for v in &mut self.voices {
            v.add(kit);
        }
        self.voices.retain(|v| !v.done());
        if let Some(v) = &mut self.preview {
            v.add(preview);
            if v.done() {
                self.preview = None;
            }
        }
    }
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
