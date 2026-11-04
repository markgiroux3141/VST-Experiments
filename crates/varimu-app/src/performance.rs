//! Performances (docs/MIDI_TAKES_PLAN.md N1, RECORDING_PLAN.md T2): what a keyboard played
//! into a device, as events at the samples where they took effect, and the [`Performer`]
//! that turns them into the device's inputs, the same way live and offline.
//!
//! **A performance** runs from a defined start: a fresh device (settled warm, as a render
//! starts) whose first sample is the performance's sample 0, at the rate the device played
//! at (`rate`, its host rate). It holds the device and its panel at the start, the
//! player's key settings (test oscillator, range switch, velocity range, multi-trigger),
//! the key events (`events`: keys down and up with velocity, pressure, the sustain pedal)
//! and the knob changes (`knobs`).
//!
//! **Knob changes, two ways.** Played live through the device, a knob is built in the
//! background and lands at a block the player can't choose, so `knobs` is the log of what
//! the device applied (`knobs_applied`): the values (the range switch's position in them)
//! and, for a change of structure, the input and control values its new stream settled at.
//! Replayed at the quality it was played at, that log gives the audio heard bit for bit.
//! Otherwise (monitored through the proxy, or edited) `knobs` holds the panel as it was
//! turned, the range switch's position left to the [`Performer`], and a render applies each
//! at the block it falls in, at once.
//!
//! **The Performer** is the player's keyboard logic: the last key held sounds (key
//! priority), a new key while another is held lifts the gate for [`RETRIGGER_GAP_S`]
//! (multi-trigger), the range switch follows the keys (AUTO) and a key waits until it has
//! moved, velocity sets the gate's key-down volts through the device's table. Each event
//! acts at its own sample in a block (a note shorter than a block is kept).

use std::sync::Arc;

use circuitsim::media::NoteEvent;
use serde_json::{Value as Json, json};
use varimu_circuit::yaml::Value;

use crate::live::Values;
use crate::midi::{TestOsc, Wave};
use crate::panel::{Feed, RangeMode, RangeSwitch};
use crate::print::{json_value, value_json};
use crate::settings::Quality;

/// The note a pitch feed holds until the first key (A3).
pub const START_NOTE: u8 = 57;

/// How long a legato key lifts the gate with multi-trigger on: tube_synth's ADSR resets
/// with 0.5 ms; 1 ms for margin, where at the fastest RELEASE the envelope dips ~20 V
/// before the new attack (scripts/adsr_study.py --bench --legato-gap-ms).
pub const RETRIGGER_GAP_S: f64 = 1.0e-3;

/// A key event.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Ev {
    On {
        note: u8,
        velocity: u8,
    },
    Off {
        note: u8,
    },
    /// Aftertouch (channel pressure, or the sounding key's), 0-127.
    Pressure(u8),
    /// The sustain pedal down or up (a medium played by keys: the Rhodes harp).
    Pedal(bool),
}

impl Ev {
    /// The event as a medium played by keys takes it (pressure: none).
    pub fn note_event(self) -> Option<NoteEvent> {
        match self {
            Ev::On { note, velocity } => Some(NoteEvent::On { note, velocity }),
            Ev::Off { note } => Some(NoteEvent::Off { note }),
            Ev::Pedal(down) => Some(NoteEvent::Pedal { down }),
            Ev::Pressure(_) => None,
        }
    }

    fn to_json(self, at: u64) -> Json {
        match self {
            Ev::On { note, velocity } => json!([at, "on", note, velocity]),
            Ev::Off { note } => json!([at, "off", note]),
            Ev::Pressure(p) => json!([at, "pressure", p]),
            Ev::Pedal(d) => json!([at, "pedal", d]),
        }
    }

    fn from_json(v: &Json) -> Result<(u64, Ev), String> {
        let at = v[0].as_u64().ok_or("an event without its sample")?;
        let byte = |i: usize| {
            v[i].as_u64()
                .filter(|&b| b < 128)
                .map(|b| b as u8)
                .ok_or(format!("event {v}: no value {i}"))
        };
        let ev = match v[1].as_str() {
            Some("on") => Ev::On {
                note: byte(2)?,
                velocity: byte(3)?,
            },
            Some("off") => Ev::Off { note: byte(2)? },
            Some("pressure") => Ev::Pressure(byte(2)?),
            Some("pedal") => Ev::Pedal(v[2].as_bool().ok_or("a pedal event without down")?),
            _ => return Err(format!("an event of no kind: {v}")),
        };
        Ok((at, ev))
    }
}

/// A knob change: every value, from sample `at` on. Logged from a device played live, a
/// change of structure also carries the input sample and control values its new stream
/// settled at (`restart`).
#[derive(Debug, Clone, PartialEq)]
pub struct Knob {
    pub at: u64,
    pub values: Values,
    pub restart: Option<(f64, Vec<f64>)>,
}

/// The player's settings for keys, held for a performance.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct Playing {
    /// The test oscillator's waveform (Off: the device makes its own sound).
    pub wave: Wave,
    pub range_mode: RangeMode,
    /// The velocity range (dB between velocity 127 and 1; 0: every key alike).
    pub velocity_db: f64,
    pub retrigger: bool,
}

impl Default for Playing {
    fn default() -> Playing {
        Playing {
            wave: Wave::Saw,
            range_mode: RangeMode::Auto,
            velocity_db: crate::panel::VELOCITY_RANGE_DB,
            retrigger: true,
        }
    }
}

fn wave_name(w: Wave) -> &'static str {
    match w {
        Wave::Saw => "saw",
        Wave::Square => "square",
        Wave::Off => "off",
    }
}

fn wave_of(s: &str) -> Option<Wave> {
    match s {
        "saw" => Some(Wave::Saw),
        "square" => Some(Wave::Square),
        "off" => Some(Wave::Off),
        _ => None,
    }
}

/// What a keyboard played into a device (see the module docs).
#[derive(Debug, Clone, PartialEq)]
pub struct Performance {
    /// The device (`panel::Device::id`).
    pub device: String,
    /// The quality it was played at (a replay at it is exact: `knobs_applied`).
    pub quality: Quality,
    /// Samples per second of `at` (the device's host rate as played).
    pub rate: u32,
    /// The values the device started with (the range switch's position in them).
    pub values: Values,
    pub playing: Playing,
    /// The input gain (the test oscillator's level into the device).
    pub gain: f64,
    pub noise: bool,
    /// Where a pitch feed starts (the last key before the start), and the range switch.
    pub start_note: u8,
    pub start_low: bool,
    /// Key events in order, at their samples.
    pub events: Vec<(u64, Ev)>,
    pub knobs: Vec<Knob>,
    /// `knobs` is the log of what the device applied (see the module docs).
    pub knobs_applied: bool,
    /// The samples it covers.
    pub end: u64,
}

impl Performance {
    pub fn to_json(&self) -> Json {
        let values =
            |v: &Values| Json::Array(v.iter().map(|(k, x)| json!([k, value_json(x)])).collect());
        json!({
            "version": 1,
            "device": self.device,
            "quality": self.quality.name(),
            "rate": self.rate,
            "values": values(&self.values),
            "wave": wave_name(self.playing.wave),
            "range_mode": crate::panel::RANGE_MODES[self.playing.range_mode.index() as usize],
            "velocity_db": self.playing.velocity_db,
            "retrigger": self.playing.retrigger,
            "gain": self.gain,
            "noise": self.noise,
            "start_note": self.start_note,
            "start_low": self.start_low,
            "end": self.end,
            "knobs_applied": self.knobs_applied,
            "events": self.events.iter().map(|&(at, e)| e.to_json(at)).collect::<Vec<_>>(),
            "knobs": self.knobs.iter().map(|k| json!({
                "at": k.at,
                "values": values(&k.values),
                "restart": k.restart.as_ref().map(|(u0, c0)| json!({"u0": u0, "c0": c0})),
            })).collect::<Vec<_>>(),
        })
    }

    pub fn from_json(v: &Json) -> Result<Performance, String> {
        let values = |v: &Json| -> Result<Values, String> {
            v.as_array()
                .ok_or("values aren't a list")?
                .iter()
                .map(|kv| {
                    let k = kv[0].as_str().ok_or("a value without a name")?;
                    Ok((k.to_string(), json_value(&kv[1])?))
                })
                .collect()
        };
        let quality = v["quality"].as_str().unwrap_or("draft-1x");
        let mode = v["range_mode"].as_str().unwrap_or("AUTO");
        let mut events = Vec::new();
        for e in v["events"].as_array().cloned().unwrap_or_default() {
            events.push(Ev::from_json(&e)?);
        }
        let mut knobs = Vec::new();
        for k in v["knobs"].as_array().cloned().unwrap_or_default() {
            let restart = match &k["restart"] {
                Json::Null => None,
                r => Some((
                    r["u0"].as_f64().ok_or("a restart without u0")?,
                    r["c0"]
                        .as_array()
                        .ok_or("a restart without c0")?
                        .iter()
                        .map(|x| x.as_f64().ok_or("c0 isn't numbers"))
                        .collect::<Result<_, _>>()?,
                )),
            };
            knobs.push(Knob {
                at: k["at"].as_u64().ok_or("a knob change without its sample")?,
                values: values(&k["values"])?,
                restart,
            });
        }
        Ok(Performance {
            device: v["device"].as_str().ok_or("no device")?.to_string(),
            quality: Quality::from_name(quality).ok_or(format!("no quality {quality}"))?,
            rate: v["rate"].as_u64().ok_or("no rate")? as u32,
            values: values(&v["values"])?,
            playing: Playing {
                wave: wave_of(v["wave"].as_str().unwrap_or("saw")).ok_or("no such wave")?,
                range_mode: RangeMode::from_value(&Value::Str(mode.into()))
                    .ok_or(format!("no range mode {mode}"))?,
                velocity_db: v["velocity_db"]
                    .as_f64()
                    .unwrap_or(crate::panel::VELOCITY_RANGE_DB),
                retrigger: v["retrigger"].as_bool().unwrap_or(true),
            },
            gain: v["gain"].as_f64().unwrap_or(1.0),
            noise: v["noise"].as_bool().unwrap_or(false),
            start_note: v["start_note"].as_u64().unwrap_or(START_NOTE as u64) as u8,
            start_low: v["start_low"].as_bool().unwrap_or(false),
            events,
            knobs,
            knobs_applied: v["knobs_applied"].as_bool().unwrap_or(false),
            end: v["end"].as_u64().ok_or("no end")?,
        })
    }

    /// Its notes (see [`notes`]).
    pub fn notes(&self) -> Vec<Note> {
        notes(&self.events, self.end)
    }

    /// A copy with `notes` in place of its key events (pressure and pedal kept), its knob
    /// changes now the panel as turned (an edited performance isn't what the device applied:
    /// the range switch is the Performer's again, `range` its control).
    pub fn edited(&self, notes: &[Note], range: Option<&str>) -> Performance {
        let mut p = self.clone();
        p.events = with_notes(&self.events, notes);
        p.end = p.end.max(notes.iter().map(|n| n.end).max().unwrap_or(0));
        if p.knobs_applied {
            p.knobs_applied = false;
            for k in &mut p.knobs {
                k.restart = None;
                if let Some(r) = range {
                    k.values.retain(|(name, _)| name != r);
                }
            }
        }
        p
    }

    /// The same performance at `rate` (sample positions scaled, rounded): a render at
    /// another host rate (production's 96 kHz).
    pub fn at_rate(&self, rate: u32) -> Performance {
        if rate == self.rate {
            return self.clone();
        }
        let f = |at: u64| (at as f64 * rate as f64 / self.rate as f64).round() as u64;
        let mut p = self.clone();
        p.rate = rate;
        p.end = f(self.end);
        p.events = self.events.iter().map(|&(at, e)| (f(at), e)).collect();
        p.knobs = self
            .knobs
            .iter()
            .map(|k| Knob {
                at: f(k.at),
                ..k.clone()
            })
            .collect();
        p
    }
}

/// A note: a key down from `start` to `end` (samples), at a velocity.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Note {
    pub start: u64,
    pub end: u64,
    pub note: u8,
    pub velocity: u8,
}

/// The notes in key events: each key down until its key up (a key pressed again while down
/// ends there; one still down ends at `end`).
pub fn notes(events: &[(u64, Ev)], end: u64) -> Vec<Note> {
    let mut open: Vec<(u8, u64, u8)> = Vec::new();
    let mut out = Vec::new();
    let close = |open: &mut Vec<(u8, u64, u8)>, note: u8, at: u64, out: &mut Vec<Note>| {
        if let Some(i) = open.iter().position(|o| o.0 == note) {
            let (note, start, velocity) = open.remove(i);
            out.push(Note {
                start,
                end: at.max(start),
                note,
                velocity,
            });
        }
    };
    for &(at, e) in events {
        match e {
            Ev::On { note, velocity } => {
                close(&mut open, note, at, &mut out);
                open.push((note, at, velocity));
            }
            Ev::Off { note } => close(&mut open, note, at, &mut out),
            _ => {}
        }
    }
    for (note, start, velocity) in open {
        out.push(Note {
            start,
            end: end.max(start),
            note,
            velocity,
        });
    }
    out.sort_by_key(|n| (n.start, n.note));
    out
}

/// `events` with their keys replaced by `notes` (pressure and pedal kept where they were):
/// in time order, at one sample the keys up before the keys down.
pub fn with_notes(events: &[(u64, Ev)], notes: &[Note]) -> Vec<(u64, Ev)> {
    let mut out: Vec<(u64, u8, Ev)> = events
        .iter()
        .filter(|(_, e)| matches!(e, Ev::Pressure(_) | Ev::Pedal(_)))
        .map(|&(at, e)| (at, 1, e))
        .collect();
    for n in notes {
        out.push((
            n.start,
            2,
            Ev::On {
                note: n.note,
                velocity: n.velocity.clamp(1, 127),
            },
        ));
        out.push((n.end.max(n.start + 1), 0, Ev::Off { note: n.note }));
    }
    out.sort_by_key(|&(at, order, _)| (at, order));
    out.into_iter().map(|(at, _, e)| (at, e)).collect()
}

/// A feed's volts with `sounding` held (a key and its velocity, or none), `last_note` the
/// last key, the range switch at LOW (`low`) or HIGH, the aftertouch `pressure` (0-127)
/// and the velocity range `vel_db`.
pub fn feed_volts(
    f: &Feed,
    sounding: Option<(u8, u8)>,
    last_note: u8,
    low: bool,
    pressure: u8,
    vel_db: f64,
) -> f64 {
    match (f, sounding) {
        (Feed::Gate(_, down), Some(_)) => *down,
        (Feed::Gate(up, _) | Feed::VelocityGate(up, _), None) => *up,
        (Feed::VelocityGate(_, t), Some((_, vel))) => crate::panel::velocity_volts(t, vel, vel_db),
        (Feed::Pitch(p), _) => p.volts_in(TestOsc::note_hz(last_note), low),
        (Feed::Key(k), _) => k.volts(last_note),
        (Feed::Pressure(full), _) => full * (pressure.min(127) as f64) / 127.0,
    }
}

/// A gate feed's block `c`, its first `gap` samples lifted to the key-up volts `up`.
pub fn lift_gate(c: &mut [f64], up: f64, gap: usize) {
    let n = gap.min(c.len());
    c[..n].fill(up);
}

/// One block of what the keys feed a device.
#[derive(Debug, Clone, Default)]
pub struct Block {
    /// The audio input: the test oscillator (silence for a device with its own sound).
    pub audio: Vec<f64>,
    /// Each control input's volts (the feeds' order).
    pub controls: Vec<Vec<f64>>,
    /// The key events for a medium played by keys, at their offsets.
    pub notes: Vec<(usize, NoteEvent)>,
    /// The range switch asked to move in this block (LOW: true).
    pub range: Option<bool>,
}

/// The keyboard logic (see the module docs), sample-accurate.
#[derive(Debug, Clone)]
pub struct Performer {
    feeds: Vec<Feed>,
    range: Option<RangeSwitch>,
    own_oscillator: bool,
    osc: TestOsc,
    playing: Playing,
    held: Vec<(u8, u8)>,
    pressure: u8,
    last_note: u8,
    asked_low: bool,
    was_sounding: bool,
    gap_left: usize,
    gap: usize,
}

impl Performer {
    /// The keys into `feeds` at `rate`, a pitch at `start_note`, the range switch asked at
    /// LOW (`start_low`) or HIGH.
    pub fn new(
        feeds: Vec<Feed>,
        playing: Playing,
        rate: u32,
        start_note: u8,
        start_low: bool,
    ) -> Performer {
        let range = feeds.iter().find_map(|f| match f {
            Feed::Pitch(p) => p.range,
            _ => None,
        });
        let own_oscillator =
            playing.wave == Wave::Off || feeds.iter().any(|f| matches!(f, Feed::Pitch(..)));
        let mut osc = TestOsc::new(rate as f64);
        osc.wave = playing.wave;
        osc.steady = feeds.iter().any(Feed::is_gate);
        Performer {
            range,
            own_oscillator,
            osc,
            playing,
            held: Vec::new(),
            pressure: 0,
            last_note: start_note,
            asked_low: start_low,
            was_sounding: false,
            gap_left: 0,
            gap: (RETRIGGER_GAP_S * rate as f64).round() as usize,
            feeds,
        }
    }

    /// The device makes its own sound: its audio input stays silent.
    pub fn own_oscillator(&self) -> bool {
        self.own_oscillator
    }

    /// The range switch the feeds' pitch has, if any.
    pub fn range(&self) -> Option<RangeSwitch> {
        self.range
    }

    /// The control inputs with no key held (where a stream starts).
    pub fn resting(&self) -> Vec<f64> {
        self.feeds
            .iter()
            .map(|f| feed_volts(f, None, self.last_note, self.asked_low, 0, 0.0))
            .collect()
    }

    /// The keys held (in the order pressed), the last key, whether the range switch was
    /// last asked to LOW.
    pub fn held(&self) -> &[(u8, u8)] {
        &self.held
    }

    pub fn last_note(&self) -> u8 {
        self.last_note
    }

    pub fn asked_low(&self) -> bool {
        self.asked_low
    }

    /// The settings it plays with now (the player's may change between blocks).
    pub fn set_playing(&mut self, p: Playing) {
        self.playing = p;
    }

    pub fn playing(&self) -> Playing {
        self.playing
    }

    fn apply(&mut self, e: Ev) -> bool {
        match e {
            Ev::On { note, velocity } => {
                self.held.retain(|&(n, _)| n != note);
                self.held.push((note, velocity));
                return true;
            }
            Ev::Off { note } => {
                self.held.retain(|&(n, _)| n != note);
                if self.held.is_empty() {
                    self.pressure = 0;
                }
            }
            Ev::Pressure(p) => self.pressure = p.min(127),
            Ev::Pedal(_) => {}
        }
        false
    }

    /// The next `n` samples with `events` (offsets in the block, rising; past its end: at its
    /// last sample) and the range switch where the device has it now (`low_applied`: LOW
    /// true; None without one).
    pub fn block(&mut self, n: usize, events: &[(usize, Ev)], low_applied: Option<bool>) -> Block {
        let mut out = Block {
            audio: vec![0.0; n],
            controls: vec![vec![0.0; n]; self.feeds.len()],
            notes: Vec::new(),
            range: None,
        };
        let mut i = 0;
        let mut s = 0;
        while s < n {
            let mut pressed = false;
            while i < events.len() && events[i].0.min(n - 1) <= s {
                let e = events[i].1;
                pressed |= self.apply(e);
                if let Some(ne) = e.note_event() {
                    out.notes.push((s, ne));
                }
                i += 1;
            }
            let next = events.get(i).map_or(n, |e| e.0.min(n - 1)).max(s + 1);
            let mut sounding = self.held.last().copied();
            let mut low = false;
            if let (Some(r), Some(applied)) = (self.range, low_applied) {
                let hz = sounding.map(|(k, _)| TestOsc::note_hz(k));
                let want = r.low_for(self.playing.range_mode, hz, self.asked_low);
                if want != self.asked_low {
                    self.asked_low = want;
                    out.range = Some(want);
                }
                low = applied;
                // A key waits (gate up, the last pitch held) until the switch has moved.
                if want != low {
                    sounding = None;
                }
            }
            if let Some((note, _)) = sounding {
                self.last_note = note;
            }
            if pressed && self.was_sounding && sounding.is_some() && self.playing.retrigger {
                self.gap_left = self.gap;
            }
            self.was_sounding = sounding.is_some();
            let seg = s..next;
            if !self.own_oscillator {
                self.osc.fill(sounding, &mut out.audio[seg.clone()]);
            }
            for (c, f) in out.controls.iter_mut().zip(&self.feeds) {
                let v = feed_volts(
                    f,
                    sounding,
                    self.last_note,
                    low,
                    self.pressure,
                    self.playing.velocity_db,
                );
                let c = &mut c[seg.clone()];
                c.fill(v);
                if let Some(up) = f.gate_up() {
                    lift_gate(c, up, self.gap_left);
                }
            }
            self.gap_left = self.gap_left.saturating_sub(seg.len());
            s = next;
        }
        out
    }
}

/// A performance being recorded: shared by the player's worker (which adds to it) and its
/// recorder (which snapshots it when a take ends).
#[derive(Debug, Clone)]
pub struct Log {
    pub perf: Performance,
}

impl Log {
    /// What's been played so far, as a performance ending at the last sample computed.
    pub fn snapshot(&self) -> Arc<Performance> {
        Arc::new(self.perf.clone())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::panel::{Feed, KeyString};

    fn on(note: u8) -> Ev {
        Ev::On {
            note,
            velocity: 100,
        }
    }

    #[test]
    fn a_note_shorter_than_a_block_sounds_at_its_samples() {
        let feeds = vec![Feed::Gate(-110.0, -1.0)];
        let mut p = Performer::new(feeds, Playing::default(), 48_000, START_NOTE, false);
        let b = p.block(480, &[(100, on(60)), (130, Ev::Off { note: 60 })], None);
        let g = &b.controls[0];
        assert!(g[..100].iter().all(|&v| v == -110.0));
        assert!(g[100..130].iter().all(|&v| v == -1.0));
        assert!(g[130..].iter().all(|&v| v == -110.0));
        assert_eq!(b.notes.len(), 2);
        // The test oscillator sounds only while the key is down (it has a gate: it holds
        // the last note, steady).
        assert!(b.audio[..100].iter().all(|&v| v == 0.0));
        assert!(b.audio[101..130].iter().any(|&v| v != 0.0));
    }

    #[test]
    fn a_legato_key_lifts_the_gate_for_the_gap() {
        let feeds = vec![Feed::Gate(-110.0, -1.0)];
        let mut p = Performer::new(feeds.clone(), Playing::default(), 48_000, START_NOTE, false);
        p.block(480, &[(0, on(60))], None);
        let b = p.block(480, &[(200, on(62))], None);
        let g = &b.controls[0];
        assert!(g[..200].iter().all(|&v| v == -1.0));
        assert!(g[200..248].iter().all(|&v| v == -110.0));
        assert!(g[248..].iter().all(|&v| v == -1.0));
        // Single trigger: no gap.
        let playing = Playing {
            retrigger: false,
            ..Playing::default()
        };
        let mut p = Performer::new(feeds, playing, 48_000, START_NOTE, false);
        p.block(480, &[(0, on(60))], None);
        let b = p.block(480, &[(200, on(62))], None);
        assert!(b.controls[0].iter().all(|&v| v == -1.0));
        assert_eq!((RETRIGGER_GAP_S * 48_000.0).round() as usize, 48);
        let mut c = vec![-1.0; 64];
        lift_gate(&mut c, -110.0, 100); // a gap longer than the block fills it
        assert!(c.iter().all(|&v| v == -110.0));
    }

    #[test]
    fn the_last_key_held_plays_and_pressure_resets_when_all_are_up() {
        let k = KeyString {
            v_per_semitone: 0.75,
            ref_note: 60.0,
            min_v: -30.0,
            max_v: 30.0,
        };
        let feeds = vec![Feed::Key(k), Feed::Pressure(15.0)];
        let mut p = Performer::new(feeds, Playing::default(), 48_000, START_NOTE, false);
        let b = p.block(
            100,
            &[
                (0, on(60)),
                (10, on(64)),
                (20, Ev::Pressure(127)),
                (30, Ev::Off { note: 64 }),
            ],
            None,
        );
        assert_eq!(b.controls[0][5], 0.0);
        assert_eq!(b.controls[0][15], 3.0);
        assert_eq!(b.controls[0][35], 0.0); // back to the key still held
        assert_eq!(b.controls[1][25], 15.0);
        let b = p.block(10, &[(0, Ev::Off { note: 60 })], None);
        assert_eq!(b.controls[1][0], 0.0);
    }

    #[test]
    fn notes_pair_their_keys_and_come_back_as_events() {
        let ev = vec![
            (10, on(60)),
            (20, Ev::Pressure(30)),
            (30, on(60)), // pressed again while down: the first ends here
            (40, on(64)),
            (50, Ev::Off { note: 60 }),
        ];
        let n = notes(&ev, 100);
        assert_eq!(
            n,
            vec![
                Note {
                    start: 10,
                    end: 30,
                    note: 60,
                    velocity: 100
                },
                Note {
                    start: 30,
                    end: 50,
                    note: 60,
                    velocity: 100
                },
                Note {
                    start: 40,
                    end: 100,
                    note: 64,
                    velocity: 100
                },
            ]
        );
        let back = with_notes(&ev, &n);
        assert_eq!(notes(&back, 100), n);
        assert!(back.contains(&(20, Ev::Pressure(30))));
        // At one sample, the key up first.
        let i = back
            .iter()
            .position(|e| *e == (30, Ev::Off { note: 60 }))
            .unwrap();
        assert_eq!(back[i + 1], (30, on(60)));
    }

    #[test]
    fn a_performance_survives_json_exactly() {
        let p = Performance {
            device: "tube_synth".into(),
            quality: Quality::Draft2x,
            rate: 48_000,
            values: vec![
                ("cutoff".into(), Value::Float(0.1 + 0.2)),
                ("range".into(), Value::Int(1)),
            ],
            playing: Playing {
                wave: Wave::Off,
                range_mode: RangeMode::Low,
                velocity_db: 12.5,
                retrigger: false,
            },
            gain: 0.7,
            noise: true,
            start_note: 40,
            start_low: true,
            events: vec![(3, on(60)), (9, Ev::Pedal(true)), (12, Ev::Pressure(5))],
            knobs: vec![Knob {
                at: 480,
                values: vec![("cutoff".into(), Value::Float(1.0 / 3.0))],
                restart: Some((1e-17, vec![-110.0, 2.0 / 7.0])),
            }],
            knobs_applied: true,
            end: 96_000,
        };
        let text = serde_json::to_string(&p.to_json()).unwrap();
        let back = Performance::from_json(&serde_json::from_str(&text).unwrap()).unwrap();
        assert_eq!(back, p);
        // Edited: the knobs are the panel's now, the range switch the Performer's.
        let e = p.edited(&p.notes(), Some("range"));
        assert!(!e.knobs_applied && e.knobs[0].restart.is_none());
        let at96 = p.at_rate(96_000);
        assert_eq!(
            (at96.end, at96.events[1].0, at96.knobs[0].at),
            (192_000, 18, 960)
        );
    }
}
