//! The Nickel Organ as an instrument of the app (docs/NICKEL_ORGAN_PLAN.md, "The Rust voice"):
//! `circuitsim::nickel`'s keyboard played from a MIDI keyboard through the player
//! (`player::Source::Nickel`), so the Session view records it like the sampler.
//!
//! Not a circuit: each key is its own coupled system (a brass bar with a nickel strip, the coil
//! and its dead twin in a bridge, the tube loop, the #327 lamp), solved at 192 kHz as the Python
//! reference does (`varimu/nickel/voice.py`, bit for bit within rounding), on worker threads, one
//! key each while it sounds. The organ's 96 kHz line out is resampled to the host's rate.
//!
//! The panel is the instrument's own: SUSTAIN (the loop's gain: below ~0.6 a struck bell, above it
//! the note sustains and blooms as the lamp catches the level) and POLARIZE (the strips' bias:
//! growly and loud low, clean mid, quiet and pure high), and a LEVEL for the monitor.

use std::collections::VecDeque;
use std::path::Path;
use std::sync::Arc;
use std::sync::atomic::{AtomicU64, AtomicUsize, Ordering};

use circuitsim::nickel::{Model, Organ};

use crate::resample::StreamResampler;

/// Volts of the line out at 0 dBFS (a single key peaks at 5-12 V).
pub const FULL_SCALE_V: f64 = 20.0;
/// The organ's chunk (samples at 96 kHz: 1.33 ms) and its rate.
const CHUNK: usize = 128;
const ORGAN_RATE: usize = 96_000;

/// What the window sets and the player reads: shared between them.
#[derive(Debug)]
pub struct NickelPanel {
    pub model: Result<Arc<Model>, String>,
    sustain: AtomicU64,
    polarize: AtomicU64,
    level_db: AtomicU64,
    /// Keys sounding and the compute load of the last blocks (f64 bits), for the window.
    running: AtomicUsize,
    load: AtomicU64,
}

impl NickelPanel {
    /// The panel at `config_dir`'s compiled organ (`nickel/organ.live.json`,
    /// `scripts/compile_nickel_organ.py`).
    pub fn new(config_dir: &Path) -> NickelPanel {
        let path = config_dir.join("nickel").join("organ.live.json");
        let model = std::fs::read_to_string(&path)
            .map_err(|e| {
                format!(
                    "{}: {e} (uv run python scripts/compile_nickel_organ.py)",
                    path.display()
                )
            })
            .and_then(|t| Model::from_json(&t))
            .map(Arc::new);
        let (s, p) = model
            .as_ref()
            .map_or((0.5, 0.35), |m| (m.panel.sustain, m.panel.polarize));
        NickelPanel {
            model,
            sustain: AtomicU64::new(s.to_bits()),
            polarize: AtomicU64::new(p.to_bits()),
            level_db: AtomicU64::new(0f64.to_bits()),
            running: AtomicUsize::new(0),
            load: AtomicU64::new(0f64.to_bits()),
        }
    }

    pub fn sustain(&self) -> f64 {
        f64::from_bits(self.sustain.load(Ordering::Relaxed))
    }

    pub fn set_sustain(&self, v: f64) {
        self.sustain
            .store(v.clamp(0.0, 1.0).to_bits(), Ordering::Relaxed);
    }

    pub fn polarize(&self) -> f64 {
        f64::from_bits(self.polarize.load(Ordering::Relaxed))
    }

    pub fn set_polarize(&self, v: f64) {
        self.polarize
            .store(v.clamp(0.0, 1.0).to_bits(), Ordering::Relaxed);
    }

    pub fn level_db(&self) -> f64 {
        f64::from_bits(self.level_db.load(Ordering::Relaxed))
    }

    pub fn set_level_db(&self, v: f64) {
        self.level_db.store(v.to_bits(), Ordering::Relaxed);
    }

    pub fn running(&self) -> usize {
        self.running.load(Ordering::Relaxed)
    }

    /// The compute time of a block over its duration (1.0: just keeping up).
    pub fn load(&self) -> f64 {
        f64::from_bits(self.load.load(Ordering::Relaxed))
    }

    pub fn set_stats(&self, running: usize, load: f64) {
        self.running.store(running, Ordering::Relaxed);
        self.load.store(load.to_bits(), Ordering::Relaxed);
    }
}

/// The worker's side: the organ and its resampling to the host's rate.
pub struct Engine {
    organ: Organ,
    panel: Arc<NickelPanel>,
    rs: StreamResampler,
    queue: VecDeque<f64>,
    chunk: Vec<f64>,
    resampled: Vec<f64>,
}

impl Engine {
    /// None when the panel's model didn't load.
    pub fn new(panel: &Arc<NickelPanel>, host_rate: u32) -> Option<Engine> {
        let model = panel.model.as_ref().ok()?.clone();
        let threads = std::thread::available_parallelism()
            .map_or(2, |n| n.get().saturating_sub(2).clamp(2, 6));
        let g = gcd(host_rate as usize, ORGAN_RATE);
        Some(Engine {
            organ: Organ::new(model, 2, Some(1), threads),
            panel: panel.clone(),
            rs: StreamResampler::new(host_rate as usize / g, ORGAN_RATE / g),
            queue: VecDeque::new(),
            chunk: vec![0.0; CHUNK],
            resampled: Vec::new(),
        })
    }

    pub fn note_on(&mut self, note: u8, velocity: u8) {
        self.organ.note_on(note, velocity);
    }

    pub fn note_off(&mut self, note: u8) {
        self.organ.note_off(note);
    }

    pub fn running(&self) -> usize {
        self.organ.running()
    }

    /// The next `out.len()` host samples, the panel's knobs read now.
    pub fn render(&mut self, out: &mut [f32]) {
        self.organ.sustain = self.panel.sustain();
        self.organ.polarize = self.panel.polarize();
        let gain = 10f64.powf(self.panel.level_db() / 20.0) / FULL_SCALE_V;
        while self.queue.len() < out.len() {
            self.organ.render(&mut self.chunk);
            self.resampled.clear();
            self.rs.process(&self.chunk, &mut self.resampled);
            self.queue.extend(self.resampled.iter());
        }
        for o in out.iter_mut() {
            *o = (self.queue.pop_front().unwrap_or(0.0) * gain) as f32;
        }
    }
}

fn gcd(a: usize, b: usize) -> usize {
    if b == 0 { a } else { gcd(b, a % b) }
}
