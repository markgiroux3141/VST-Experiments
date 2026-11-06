//! The Clavinet's proxy: a stand-in to hear while playing and recording (the take renders
//! on the real strings later, docs/MIDI_TAKES_PLAN.md N2). Fast and simple by design (the
//! user's ask, 2026-11-06: "I don't care what it sounds like"), only vaguely a Clavinet:
//!
//! - each key a Karplus-Strong string (a delay line one period long, read with linear
//!   interpolation, a two-point average and a loop gain for the decay), struck by a short
//!   burst of noise, brighter and louder with velocity;
//! - read through a **pickup comb** (the string's output less itself a fraction of a period
//!   earlier): the hollow, nasal honk of a pickup near the string's end; PICKUP SELECT moves
//!   the fraction (the centre pickup farther in, the bridge nearer the end);
//! - held, the string rings a few seconds (shorter up the keyboard); let go, the yarn's job
//!   is a fast decay and the pitch drops three semitones (the whole string speaking, as on
//!   the real instrument), the Clavinet's release "thwack";
//! - VOLUME scales the output (its log taper roughly); the tone rockers, the wear and the
//!   rest of the panel are heard in the render only.
//!
//! No tables, no measurement: nothing here claims to match the device's level or tone.

use crate::live::Values;
use crate::performance::{Ev, Playing};

/// Voices (a Clavinet is polyphonic; the oldest is stolen past this).
const VOICES: usize = 16;
/// The delay lines' length (a power of two above the lowest note's period at 192 kHz).
const LINE: usize = 8192;
/// A held string's T60 at the bottom and the top of the keyboard (s). Provisional: a
/// design choice for the stand-in.
const HELD_T60_S: (f64, f64) = (4.0, 1.2);
/// A released string's T60 (s): the yarn.
const RELEASED_T60_S: f64 = 0.07;
/// The pitch drop on release (semitones): the whole string speaks ([G13] 2.3.1's three).
const RELEASE_DROP: f64 = 3.0;
/// The output's gain at velocity 127 and full VOLUME.
const GAIN: f32 = 0.25;

#[derive(Debug, Clone)]
struct Voice {
    note: Option<u8>,
    /// Whether it sounds at all (struck and not yet died away).
    live: bool,
    struck: u64,
    line: Vec<f32>,
    w: usize,
    /// The period (samples) and the loop gain per period's pass.
    period: f64,
    g: f32,
    prev: f32,
    /// The noise burst's samples still to add, its level and one-pole brightness.
    burst: usize,
    burst_amp: f32,
    burst_lp: f32,
    burst_state: f32,
    /// Samples since the level was last checked, and the largest |y| since.
    since: usize,
    peak: f32,
}

impl Voice {
    fn new() -> Voice {
        Voice {
            note: None,
            live: false,
            struck: 0,
            line: vec![0.0; LINE],
            w: 0,
            period: 100.0,
            g: 0.0,
            prev: 0.0,
            burst: 0,
            burst_amp: 0.0,
            burst_lp: 0.5,
            burst_state: 0.0,
            since: 0,
            peak: 0.0,
        }
    }

    #[inline]
    fn read(&self, back: f64) -> f32 {
        let back = back.clamp(1.0, (LINE - 2) as f64);
        let i = back.floor() as usize;
        let f = (back - i as f64) as f32;
        let a = self.line[(self.w + LINE - i) % LINE];
        let b = self.line[(self.w + LINE - i - 1) % LINE];
        a + f * (b - a)
    }
}

/// The Clavinet's stand-in (see the module docs).
pub struct ClavProxy {
    rate: f64,
    voices: Vec<Voice>,
    held: Vec<(u8, u8)>,
    strikes: u64,
    volume: f32,
    /// The pickup comb's fraction of a period.
    comb: f64,
    noise: u32,
    /// The output's DC blocker.
    hp_x: f32,
    hp_y: f32,
}

impl ClavProxy {
    pub fn new(rate: u32) -> ClavProxy {
        let mut p = ClavProxy {
            rate: rate as f64,
            voices: vec![Voice::new(); VOICES],
            held: Vec::new(),
            strikes: 0,
            volume: 0.0,
            comb: 0.0,
            noise: 0x1234_5678,
            hp_x: 0.0,
            hp_y: 0.0,
        };
        p.set_values(&Vec::new());
        p
    }

    /// The panel: VOLUME and PICKUP SELECT (the rest is heard in the render only).
    pub fn set_values(&mut self, values: &Values) {
        let mut volume = 0.8;
        let mut pickup = 3.0;
        for (k, v) in values {
            match (k.as_str(), v.as_f64()) {
                ("volume", Some(x)) => volume = x,
                ("pickup_select", Some(x)) => pickup = x,
                _ => {}
            }
        }
        // a log pot, roughly: -40 dB at 0.1, 0 dB at 1
        self.volume = if volume <= 0.0 {
            0.0
        } else {
            (10f64.powf(2.0 * (volume.min(1.0) - 1.0))) as f32
        };
        // 0 centre, 1 bridge, 2 both anti-phase (thinner), 3 both in phase
        self.comb = match pickup.round() as i64 {
            0 => 0.25,
            1 => 0.12,
            2 => 0.06,
            _ => 0.18,
        };
    }

    /// The proxy plays every key alike (no velocity range or retrigger to follow).
    pub fn set_playing(&mut self, _p: Playing) {}

    pub fn held(&self) -> &[(u8, u8)] {
        &self.held
    }

    pub fn sounding(&self) -> usize {
        self.voices.iter().filter(|v| v.live).count()
    }

    fn random(&mut self) -> f32 {
        // xorshift32: a stand-in's noise needs no more
        let mut x = self.noise;
        x ^= x << 13;
        x ^= x >> 17;
        x ^= x << 5;
        self.noise = x;
        (x as f32 / u32::MAX as f32) * 2.0 - 1.0
    }

    fn loop_gain(&self, period: f64, t60: f64) -> f32 {
        // -60 dB over t60 seconds, applied once per period
        10f64.powf(-3.0 * period / (t60 * self.rate)) as f32
    }

    fn strike(&mut self, note: u8, velocity: u8) {
        let n = self.voices.len();
        let i = self
            .voices
            .iter()
            .position(|v| v.note == Some(note))
            .or_else(|| self.voices.iter().position(|v| !v.live))
            .unwrap_or_else(|| {
                (0..n)
                    .min_by_key(|&k| self.voices[k].struck)
                    .expect("a voice")
            });
        self.strikes += 1;
        let hz = 440.0 * 2f64.powf((note as f64 - 69.0) / 12.0);
        let period = (self.rate / hz).clamp(2.0, (LINE - 4) as f64);
        let x = ((note as f64 - 29.0) / 59.0).clamp(0.0, 1.0);
        let t60 = HELD_T60_S.0 + (HELD_T60_S.1 - HELD_T60_S.0) * x;
        let g = self.loop_gain(period, t60);
        let vel = velocity.max(1) as f32 / 127.0;
        let v = &mut self.voices[i];
        v.note = Some(note);
        v.live = true;
        v.struck = self.strikes;
        v.period = period;
        v.g = g;
        v.burst = period.round() as usize;
        v.burst_amp = vel * vel;
        v.burst_lp = 0.25 + 0.7 * vel;
        v.since = 0;
        v.peak = 1.0;
    }

    fn release(&mut self, note: u8) {
        for i in 0..self.voices.len() {
            if self.voices[i].note == Some(note) {
                let period =
                    (self.voices[i].period * 2f64.powf(RELEASE_DROP / 12.0)).min((LINE - 4) as f64);
                let g = self.loop_gain(period, RELEASED_T60_S);
                let v = &mut self.voices[i];
                v.note = None;
                v.period = period;
                v.g = g;
            }
        }
    }

    fn apply(&mut self, e: Ev) {
        match e {
            Ev::On { note, velocity } if velocity > 0 => {
                self.held.retain(|&(n, _)| n != note);
                self.held.push((note, velocity));
                self.strike(note, velocity);
            }
            Ev::On { note, .. } | Ev::Off { note } => {
                self.held.retain(|&(n, _)| n != note);
                self.release(note);
            }
            Ev::Pressure(_) | Ev::Pedal(_) => {}
        }
    }

    /// The next `out.len()` samples with `events` (offsets in the block, rising).
    pub fn process(&mut self, events: &[(usize, Ev)], out: &mut [f32]) {
        out.fill(0.0);
        let mut j = 0;
        for (i, o) in out.iter_mut().enumerate() {
            while j < events.len() && events[j].0 <= i {
                self.apply(events[j].1);
                j += 1;
            }
            let mut sum = 0.0f32;
            for k in 0..self.voices.len() {
                if !self.voices[k].live {
                    continue;
                }
                let noise = if self.voices[k].burst > 0 {
                    self.random()
                } else {
                    0.0
                };
                let comb = self.comb;
                let v = &mut self.voices[k];
                let y = v.read(v.period);
                // the loop: a two-point average (the string's loss rising with frequency)
                let mut next = v.g * 0.5 * (y + v.prev);
                v.prev = y;
                if v.burst > 0 {
                    v.burst_state += v.burst_lp * (noise - v.burst_state);
                    next += v.burst_amp * v.burst_state;
                    v.burst -= 1;
                }
                v.line[v.w] = next;
                v.w = (v.w + 1) % LINE;
                // the pickup comb
                let s = y - v.read(v.period * (1.0 + comb));
                sum += s;
                v.peak = v.peak.max(s.abs());
                v.since += 1;
                if v.since >= 4096 {
                    if v.peak < 1e-5 && v.burst == 0 {
                        v.live = false;
                        v.note = None;
                        v.line.fill(0.0);
                        v.prev = 0.0;
                    }
                    v.since = 0;
                    v.peak = 0.0;
                }
            }
            // DC blocker (~20 Hz), then the gain
            let y = sum - self.hp_x + 0.9974 * self.hp_y;
            self.hp_x = sum;
            self.hp_y = y;
            *o = y * GAIN * self.volume;
        }
        while j < events.len() {
            self.apply(events[j].1);
            j += 1;
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn rms(y: &[f32]) -> f32 {
        (y.iter().map(|v| v * v).sum::<f32>() / y.len() as f32).sqrt()
    }

    #[test]
    fn a_key_rings_held_and_dies_when_let_go() {
        let mut p = ClavProxy::new(48_000);
        let mut y = vec![0.0f32; 24_000];
        p.process(
            &[(
                0,
                Ev::On {
                    note: 60,
                    velocity: 100,
                },
            )],
            &mut y,
        );
        assert!(rms(&y) > 1e-3, "it sounds");
        assert!(y.iter().all(|v| v.is_finite() && v.abs() < 1.0));
        p.process(&[(0, Ev::Off { note: 60 })], &mut y);
        let mut tail = vec![0.0f32; 48_000];
        p.process(&[], &mut tail);
        assert!(rms(&tail[24_000..]) < 1e-4);
        assert_eq!(p.sounding(), 0);
        assert!(p.held().is_empty());
    }

    #[test]
    fn its_pitch_is_the_key() {
        let rate = 48_000;
        let mut p = ClavProxy::new(rate);
        let mut y = vec![0.0f32; 48_000];
        p.process(
            &[(
                0,
                Ev::On {
                    note: 57,
                    velocity: 100,
                },
            )],
            &mut y,
        );
        // the fundamental by autocorrelation over the second half
        let x = &y[24_000..];
        let lag = (40..400)
            .max_by(|&a, &b| {
                let c = |l: usize| {
                    x[..x.len() - l]
                        .iter()
                        .zip(&x[l..])
                        .map(|(a, b)| a * b)
                        .sum::<f32>()
                };
                c(a).total_cmp(&c(b))
            })
            .unwrap();
        let hz = rate as f64 / lag as f64;
        assert!((hz / 220.0 - 1.0).abs() < 0.02, "{hz} Hz");
    }

    #[test]
    fn sixteen_chords_cost_little() {
        let mut p = ClavProxy::new(48_000);
        let ev: Vec<(usize, Ev)> = (0..16)
            .map(|i| {
                (
                    0,
                    Ev::On {
                        note: 36 + 3 * i as u8,
                        velocity: 110,
                    },
                )
            })
            .collect();
        let mut y = vec![0.0f32; 48_000];
        let t = std::time::Instant::now();
        p.process(&ev, &mut y);
        let s = t.elapsed().as_secs_f64();
        assert_eq!(p.sounding(), 16);
        // a second of 16 voices in well under a tenth of a second (debug builds included)
        assert!(s < 0.5, "{s} s");
    }
}
