//! MIDI keyboards (the tube synth, docs/TUBE_SYNTH_PLAN.md): a keyboard's keys and
//! controllers, and the test oscillator they play into a device's input.
//!
//! The oscillator is a stand-in until the synth has its own (S4's tube oscillator): it is
//! an input played into the circuit, like a file or live input, not part of any device. A
//! band-limited sawtooth or square (polyBLEP), one voice, the last key held sounding,
//! with a short linear attack and release so notes don't click; velocity sets its level.

use std::sync::{Arc, Mutex};

use circuitsim::media::NoteEvent;
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
    /// The last aftertouch (channel pressure, or a held key's pressure).
    pressure: u8,
    /// Key presses so far (note-ons): a new one while another key is held is a legato key.
    presses: u64,
    /// The note-ons not yet taken (note, velocity), for the sampler: each key its own hit.
    ons: std::collections::VecDeque<(u8, u8)>,
    /// Every key down and up and the sustain pedal not yet taken, as they arrived: a medium
    /// played by keys (the Rhodes harp, docs/RHODES_PLAN.md RH3).
    events: std::collections::VecDeque<(std::time::Instant, NoteEvent)>,
    /// The sustain pedal down (CC 64 at 64 and over).
    pedal: bool,
}

/// Note-ons kept until taken (older ones dropped: a player that doesn't take them).
const MAX_ONS: usize = 256;
/// Note events kept until taken (older ones dropped, as note-ons are).
const MAX_EVENTS: usize = 1024;

impl Default for KeysInner {
    fn default() -> Self {
        KeysInner {
            held: Vec::new(),
            cc: [(0, 0); 128],
            pressure: 0,
            presses: 0,
            ons: std::collections::VecDeque::new(),
            events: std::collections::VecDeque::new(),
            pedal: false,
        }
    }
}

impl KeysInner {
    /// A message's note event, if it is one: a key down or up, the sustain pedal moving, or
    /// all notes off (every key held up).
    fn note_event(&mut self, m: &[u8]) {
        let now = std::time::Instant::now();
        let mut push = |e: NoteEvent| {
            self.events.push_back((now, e));
            while self.events.len() > MAX_EVENTS {
                self.events.pop_front();
            }
        };
        match (m[0] & 0xf0, m.get(1).copied(), m.get(2).copied()) {
            (0x90, Some(note), Some(vel)) if vel > 0 => push(NoteEvent::On {
                note: note & 127,
                velocity: vel & 127,
            }),
            (0x80 | 0x90, Some(note), _) => push(NoteEvent::Off { note: note & 127 }),
            (0xb0, Some(64), Some(v)) => {
                let down = v >= 64;
                if down != self.pedal {
                    self.pedal = down;
                    push(NoteEvent::Pedal { down });
                }
            }
            (0xb0, Some(120 | 123), _) => {
                for &(note, _) in &self.held.clone() {
                    push(NoteEvent::Off { note });
                }
            }
            _ => {}
        }
    }
}

impl Keys {
    /// The key and pedal events since the last call, oldest first, with when each arrived.
    pub fn take_events(&self) -> Vec<(std::time::Instant, NoteEvent)> {
        self.inner.lock().expect("keys").events.drain(..).collect()
    }

    /// Apply one MIDI message (any channel).
    pub fn message(&self, m: &[u8]) {
        let Some(&status) = m.first() else { return };
        let mut k = self.inner.lock().expect("keys");
        k.note_event(m);
        match (status & 0xf0, m.get(1).copied(), m.get(2).copied()) {
            (0x90, Some(note), Some(vel)) if vel > 0 => {
                k.held.retain(|&(n, _)| n != note);
                k.held.push((note, vel));
                k.presses += 1;
                k.ons.push_back((note, vel));
                while k.ons.len() > MAX_ONS {
                    k.ons.pop_front();
                }
            }
            (0x80 | 0x90, Some(note), _) => {
                k.held.retain(|&(n, _)| n != note);
                if k.held.is_empty() {
                    k.pressure = 0;
                }
            }
            (0xd0, Some(p), _) => k.pressure = p & 127,
            // Key pressure: the sounding key's.
            (0xa0, Some(note), Some(p)) if k.held.last().is_some_and(|&(n, _)| n == note) => {
                k.pressure = p & 127
            }
            // All sound off / all notes off.
            (0xb0, Some(120 | 123), _) => {
                k.held.clear();
                k.pressure = 0;
            }
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

    /// The note-ons since the last call (note, velocity), oldest first.
    pub fn take_note_ons(&self) -> Vec<(u8, u8)> {
        self.inner.lock().expect("keys").ons.drain(..).collect()
    }

    /// How many keys have been pressed (note-ons), to tell a new key from a held one.
    pub fn presses(&self) -> u64 {
        self.inner.lock().expect("keys").presses
    }

    /// The last aftertouch, 0-127 (0 with no key held).
    pub fn pressure(&self) -> u8 {
        self.inner.lock().expect("keys").pressure
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
    /// Silent: the device plays an oscillator of its own.
    Off,
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
    /// Keep sounding the last key after it is released (a device whose circuit has an
    /// envelope keyed by the gate shapes the notes itself).
    pub steady: bool,
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
            steady: false,
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
        } else if !self.steady {
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
                Wave::Off => 0.0,
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
    fn keys_record_their_events_for_a_harp() {
        let k = Keys::default();
        k.message(&[0x90, 60, 100]);
        k.message(&[0x91, 64, 0]); // a note-on at velocity 0 is a key up
        k.message(&[0xb0, 64, 127]);
        k.message(&[0xb0, 64, 100]); // still down: no event
        k.message(&[0xb0, 64, 10]);
        k.message(&[0x80, 60, 40]);
        k.message(&[0x90, 62, 90]);
        k.message(&[0xb0, 123, 0]); // all notes off: the held key up
        let ev: Vec<NoteEvent> = k.take_events().into_iter().map(|(_, e)| e).collect();
        assert_eq!(
            ev,
            vec![
                NoteEvent::On {
                    note: 60,
                    velocity: 100
                },
                NoteEvent::Off { note: 64 },
                NoteEvent::Pedal { down: true },
                NoteEvent::Pedal { down: false },
                NoteEvent::Off { note: 60 },
                NoteEvent::On {
                    note: 62,
                    velocity: 90
                },
                NoteEvent::Off { note: 62 },
            ]
        );
        assert!(k.take_events().is_empty());
    }

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
        k.message(&[0xd0, 90]);
        assert_eq!(k.pressure(), 90);
        k.message(&[0xa0, 61, 20]); // another key's pressure
        assert_eq!(k.pressure(), 90);
        k.message(&[0xa0, 60, 30]);
        assert_eq!(k.pressure(), 30);
        k.message(&[0xb0, 123, 0]);
        assert_eq!(k.sounding(), None);
    }

    #[test]
    fn presses_count_note_ons_only() {
        let k = Keys::default();
        k.message(&[0x90, 60, 100]);
        k.message(&[0x90, 62, 100]); // legato: a second key while the first is held
        k.message(&[0x80, 62, 0]);
        k.message(&[0x90, 60, 0]); // a note off
        k.message(&[0xd0, 50]);
        assert_eq!(k.presses(), 2);
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
