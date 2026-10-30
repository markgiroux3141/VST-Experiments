//! MIDI keyboards (the tube synth, docs/TUBE_SYNTH_PLAN.md): a keyboard's keys and
//! controllers, and the test oscillator they play into a device's input.
//!
//! The oscillator is a stand-in until the synth has its own (S4's tube oscillator): it is
//! an input played into the circuit, like a file or live input, not part of any device. A
//! band-limited sawtooth or square (polyBLEP), one voice, the last key held sounding,
//! with a short linear attack and release so notes don't click; velocity sets its level.

use std::sync::{Arc, Mutex};

use midir::{Ignore, MidiInput, MidiInputConnection};

/// The mod wheel's controller number.
pub const MOD_WHEEL: u8 = 1;

/// The MIDI input ports by name.
pub fn ports() -> Result<Vec<String>, String> {
    let input = MidiInput::new("varimu ports").map_err(|e| e.to_string())?;
    Ok(input
        .ports()
        .iter()
        .map(|p| input.port_name(p).unwrap_or_else(|_| "?".into()))
        .collect())
}

/// What the keyboard is doing: the keys held (in the order pressed) and each
/// controller's last value with a count of how often it was sent.
#[derive(Debug, Default)]
pub struct Keys {
    inner: Mutex<KeysInner>,
}

#[derive(Debug)]
struct KeysInner {
    held: Vec<(u8, u8)>,
    cc: [(u8, u64); 128],
}

impl Default for KeysInner {
    fn default() -> Self {
        KeysInner {
            held: Vec::new(),
            cc: [(0, 0); 128],
        }
    }
}

impl Keys {
    /// Apply one MIDI message (any channel).
    pub fn message(&self, m: &[u8]) {
        let Some(&status) = m.first() else { return };
        let mut k = self.inner.lock().expect("keys");
        match (status & 0xf0, m.get(1).copied(), m.get(2).copied()) {
            (0x90, Some(note), Some(vel)) if vel > 0 => {
                k.held.retain(|&(n, _)| n != note);
                k.held.push((note, vel));
            }
            (0x80 | 0x90, Some(note), _) => k.held.retain(|&(n, _)| n != note),
            // All sound off / all notes off.
            (0xb0, Some(120 | 123), _) => k.held.clear(),
            (0xb0, Some(cc), Some(v)) if cc < 128 => {
                let (_, n) = k.cc[cc as usize];
                k.cc[cc as usize] = (v, n + 1);
            }
            _ => {}
        }
    }

    /// The key sounding (the last one held) and its velocity.
    pub fn sounding(&self) -> Option<(u8, u8)> {
        self.inner.lock().expect("keys").held.last().copied()
    }

    /// A controller's last value and how many times it was sent (0: never).
    pub fn cc(&self, number: u8) -> (u8, u64) {
        self.inner.lock().expect("keys").cc[number as usize & 127]
    }
}

/// An open keyboard: its port's name and its keys, updated from MIDI's thread.
pub struct Keyboard {
    pub name: String,
    pub keys: Arc<Keys>,
    _connection: MidiInputConnection<()>,
}

impl Keyboard {
    /// Open the first port whose name contains `name` (any case; None: the first port).
    pub fn open(name: Option<&str>) -> Result<Keyboard, String> {
        let mut input = MidiInput::new("varimu").map_err(|e| e.to_string())?;
        input.ignore(Ignore::All);
        let ports = input.ports();
        let want = name.map(str::to_lowercase);
        let port = ports
            .iter()
            .find(|p| {
                let n = input.port_name(p).unwrap_or_default().to_lowercase();
                want.as_ref().is_none_or(|w| n.contains(w.as_str()))
            })
            .ok_or_else(|| match name {
                Some(n) => format!("no MIDI input named like {n:?}"),
                None => "no MIDI input".to_string(),
            })?;
        let port_name = input.port_name(port).map_err(|e| e.to_string())?;
        let keys = Arc::new(Keys::default());
        let k = keys.clone();
        let connection = input
            .connect(port, "varimu-in", move |_, m, _| k.message(m), ())
            .map_err(|e| format!("can't open {port_name}: {e}"))?;
        Ok(Keyboard {
            name: port_name,
            keys,
            _connection: connection,
        })
    }
}

/// The test oscillator's waveform.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Wave {
    Saw,
    Square,
}

/// The test oscillator (the module docstring).
#[derive(Debug, Clone)]
pub struct TestOsc {
    rate: f64,
    phase: f64,
    freq: f64,
    env: f64,
    target: f64,
    pub wave: Wave,
    /// The level at velocity 127 (1.0 is the device's full scale).
    pub level: f64,
}

/// Attack and release (s).
const ATTACK_S: f64 = 0.005;
const RELEASE_S: f64 = 0.06;

/// The polyBLEP correction of a unit step at phase 0 (t, dt in cycles).
fn poly_blep(t: f64, dt: f64) -> f64 {
    if t < dt {
        let x = t / dt;
        2.0 * x - x * x - 1.0
    } else if t > 1.0 - dt {
        let x = (t - 1.0) / dt;
        x * x + 2.0 * x + 1.0
    } else {
        0.0
    }
}

impl TestOsc {
    pub fn new(rate: f64) -> TestOsc {
        TestOsc {
            rate,
            phase: 0.0,
            freq: 110.0,
            env: 0.0,
            target: 0.0,
            wave: Wave::Saw,
            level: 0.8,
        }
    }

    /// The frequency of MIDI note `note` (A4 = 69 = 440 Hz, equal temperament).
    pub fn note_hz(note: u8) -> f64 {
        440.0 * 2f64.powf((note as f64 - 69.0) / 12.0)
    }

    /// Fill `out` with what `sounding` (a key and its velocity, or none) plays.
    pub fn fill(&mut self, sounding: Option<(u8, u8)>, out: &mut [f64]) {
        if let Some((note, vel)) = sounding {
            self.freq = Self::note_hz(note);
            self.target = vel as f64 / 127.0;
        } else {
            self.target = 0.0;
        }
        let up = 1.0 / (ATTACK_S * self.rate);
        let down = 1.0 / (RELEASE_S * self.rate);
        let dt = (self.freq / self.rate).min(0.5);
        for y in out.iter_mut() {
            self.env = if self.env < self.target {
                (self.env + up).min(self.target)
            } else {
                (self.env - down).max(self.target)
            };
            let t = self.phase;
            let saw = |t: f64| 2.0 * t - 1.0 - poly_blep(t, dt);
            let v = match self.wave {
                Wave::Saw => saw(t),
                Wave::Square => {
                    let t2 = (t + 0.5) % 1.0;
                    0.5 * (saw(t) - saw(t2))
                }
            };
            *y = self.level * self.env * v;
            self.phase += dt;
            if self.phase >= 1.0 {
                self.phase -= 1.0;
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn keys_follow_the_last_held() {
        let k = Keys::default();
        assert_eq!(k.sounding(), None);
        k.message(&[0x90, 60, 100]);
        k.message(&[0x91, 64, 50]); // another channel counts too
        assert_eq!(k.sounding(), Some((64, 50)));
        k.message(&[0x80, 64, 0]);
        assert_eq!(k.sounding(), Some((60, 100)));
        k.message(&[0x90, 60, 0]); // note on at velocity 0 is a note off
        assert_eq!(k.sounding(), None);
        k.message(&[0xb0, MOD_WHEEL, 42]);
        k.message(&[0xb0, MOD_WHEEL, 43]);
        assert_eq!(k.cc(MOD_WHEEL), (43, 2));
        k.message(&[0x90, 60, 1]);
        k.message(&[0xb0, 123, 0]);
        assert_eq!(k.sounding(), None);
    }

    #[test]
    fn oscillator_plays_the_note_and_releases() {
        let rate = 48_000.0;
        let mut o = TestOsc::new(rate);
        let mut y = vec![0.0; 48_000];
        o.fill(Some((69, 127)), &mut y);
        // A 440 Hz saw rises through zero once a cycle (its falling edge, spread over
        // two samples by the band limiting, crosses downward).
        let rising = y.windows(2).filter(|w| w[0] < 0.0 && w[1] >= 0.0).count();
        assert!((439..=441).contains(&rising), "{rising}");
        assert!(y.iter().all(|v| v.abs() <= 1.0));
        let mut tail = vec![1.0; 4800];
        o.fill(None, &mut tail);
        assert!(tail[tail.len() - 1].abs() < 1e-12); // released within 60 ms
        assert_eq!(TestOsc::note_hz(57), 220.0);
    }
}
