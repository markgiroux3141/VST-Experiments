//! The devices the app plays and their front panels (`varimu/listen/play.py`'s
//! `DEVICES` and knobs): the 670's four front-panel controls; for other circuits, the
//! circuit file's controls in file order, selectors as choices, the mains settings left
//! off.

use varimu_circuit::spec::CircuitSpec;
use varimu_circuit::yaml::Value;

use crate::live::Values;
use crate::player::AHEAD_S;
use crate::settings::{Quality, Settings};

/// A device: a circuit file and what its panel shows.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct Device {
    pub id: &'static str,
    pub label: &'static str,
    /// Its circuit file (`config/circuits/<circuit>.yaml`).
    pub circuit: &'static str,
    /// The controls on its panel (None: every control but the mains settings).
    pub panel: Option<&'static [&'static str]>,
    /// Audio kept ahead of playback for a file's loop (s; see [`AHEAD_S`]).
    pub ahead_s: f64,
    /// The quality it plays at (draft-1x; draft-2x for a device whose clipping aliases).
    pub quality: Quality,
    /// The cores it plays with, over its quality's (None: the quality's; "ja" for a
    /// device whose sound is its cores' hysteresis: the draft's linear cores would
    /// leave a saturable reactor a fixed inductor).
    pub cores: Option<&'static str>,
    /// The control a MIDI keyboard's mod wheel turns (None: none).
    pub mod_wheel: Option<&'static str>,
    /// The circuit's control input a keyboard's keys gate (its key-up and key-down volts
    /// are the circuit file's `<name>_off_v` and `<name>_on_v` values; None: none).
    pub gate: Option<&'static str>,
    /// How the gate's key-down volts follow a key's velocity: (dB, volts) points rising
    /// in dB, the device's output level at each key-down voltage against its level at the
    /// circuit file's `<gate>_on_v` (0 dB), measured (`scripts/velocity_study.py`). A key
    /// at velocity v aims at -range x (127 - v) / 126 dB, the range the Play view's (None:
    /// every key at `<gate>_on_v`).
    pub velocity: Option<&'static [(f64, f64)]>,
    /// The circuit's control input a keyboard's keys set the pitch on, for a device with
    /// an oscillator of its own (its audio input then stays silent; None: none).
    pub pitch: Option<Pitch>,
    /// A second oscillator's pitch input, on a keyboard string of its own: its own measured
    /// tuning, no range switch (tube_synth's gas-tube saw, whose law isn't the first's; None:
    /// none).
    pub pitch2: Option<Pitch>,
    /// Its circuit makes its own sound without a pitch input (a drum's oscillator): the
    /// keys only gate it, its audio input stays silent (as with a `pitch` input).
    pub own_oscillator: bool,
    /// The circuit's control input a key (sidechain) signal drives: another track's audio
    /// in the session, in circuit volts on the input's full scale (None: no key input;
    /// SIDECHAIN_PLAN.md).
    pub key: Option<&'static str>,
    /// The sections its draft puts on the second thread, over its quality's
    /// `partition` (None: the quality's).
    pub partition: Option<&'static [&'static str]>,
    /// How its partitions see each other's nodes, over its quality's `partition_coupling`
    /// (None: the quality's): "hold" where a waveform's edge crosses a cut (extrapolated, a
    /// one-sample edge doubled for a sample).
    pub coupling: Option<&'static str>,
}

/// A keyboard's pitch into a circuit's control input: the control and the keyboard's
/// tuning, (Hz, volts) points rising in Hz, measured on the circuit at the quality it
/// plays at (`scripts/vco_study.py --tuning`). A key's frequency goes on the control by
/// interpolating linearly in log2(Hz) between the points, held at the ends: a period
/// keyboard's divider string set to its oscillator's curve. Nothing corrects the
/// oscillator's drift (TUBE_SYNTH_PLAN.md decision 2).
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct Pitch {
    pub control: &'static str,
    /// The tuning (with a range switch: at HIGH, position 1).
    pub tuning: &'static [(f64, f64)],
    /// The oscillator's range switch, if it has one.
    pub range: Option<RangeSwitch>,
}

/// An oscillator's range switch: the circuit's selector `control` (0 LOW, 1 HIGH), the
/// LOW position's tuning, and where AUTO changes range: keys below `split_hz` play on
/// LOW, the rest on HIGH (each note on the gentler stretch of a pitch law; see
/// docs/SYNTH_LOW_END.md). On the panel it is a LOW / HIGH / AUTO selector
/// ([`RANGE_MODES`]); the circuit only ever sees 0 or 1.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct RangeSwitch {
    pub control: &'static str,
    pub low: &'static [(f64, f64)],
    pub split_hz: f64,
}

/// A range switch's positions on the panel.
pub const RANGE_MODES: [&str; 3] = ["LOW", "HIGH", "AUTO"];

/// Where a range switch is set.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum RangeMode {
    Low,
    High,
    /// The keys choose: LOW below the split, HIGH above.
    Auto,
}

impl RangeMode {
    pub fn from_value(v: &Value) -> Option<RangeMode> {
        match v.as_str()? {
            "LOW" => Some(RangeMode::Low),
            "HIGH" => Some(RangeMode::High),
            "AUTO" => Some(RangeMode::Auto),
            _ => None,
        }
    }

    pub fn index(self) -> u8 {
        self as u8
    }

    pub fn from_index(i: u8) -> RangeMode {
        match i {
            0 => RangeMode::Low,
            1 => RangeMode::High,
            _ => RangeMode::Auto,
        }
    }
}

impl RangeSwitch {
    /// Whether a key of `hz` plays on LOW at `mode` (`current` when AUTO has no key).
    pub fn low_for(&self, mode: RangeMode, hz: Option<f64>, current: bool) -> bool {
        match mode {
            RangeMode::Low => true,
            RangeMode::High => false,
            RangeMode::Auto => hz.map_or(current, |hz| hz < self.split_hz),
        }
    }

    /// `values` with the switch at LOW (`low`) or HIGH: the circuit's position.
    pub fn with_position(&self, values: &Values, low: bool) -> Values {
        let pos = Value::Int(if low { 0 } else { 1 });
        let mut v: Values = values
            .iter()
            .filter(|(k, _)| k != self.control)
            .cloned()
            .collect();
        v.push((self.control.to_string(), pos));
        v
    }

    /// Whether `values` put the switch at LOW.
    pub fn is_low(&self, values: &Values) -> bool {
        values
            .iter()
            .find(|(k, _)| k == self.control)
            .and_then(|(_, v)| v.as_f64())
            .is_some_and(|p| p == 0.0)
    }
}

impl Pitch {
    /// The control's volts for `hz` (at HIGH, with a range switch).
    pub fn volts(&self, hz: f64) -> f64 {
        Self::interpolate(self.tuning, hz)
    }

    /// The control's volts for `hz` with the range switch at LOW (`low`) or HIGH.
    pub fn volts_in(&self, hz: f64, low: bool) -> f64 {
        match self.range {
            Some(r) if low => Self::interpolate(r.low, hz),
            _ => self.volts(hz),
        }
    }

    fn interpolate(t: &[(f64, f64)], hz: f64) -> f64 {
        let (first, last) = (t[0], t[t.len() - 1]);
        if hz <= first.0 {
            return first.1;
        }
        if hz >= last.0 {
            return last.1;
        }
        let i = t.partition_point(|&(f, _)| f <= hz);
        let ((f0, v0), (f1, v1)) = (t[i - 1], t[i]);
        v0 + (v1 - v0) * (hz / f0).log2() / (f1 / f0).log2()
    }
}

/// A keyboard's linear contact string (tube_synth's KEY TRACK, SYNTH_IDEAS.md #2): the
/// same volts a key wherever it is, 0 V at `ref_note`, held at the string's ends. Unlike a
/// pitch input's, it isn't tuned to anything: the circuit file's `<name>_v_per_semitone`,
/// `<name>_ref_note`, `<name>_min_v` and `<name>_max_v`.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct KeyString {
    pub v_per_semitone: f64,
    pub ref_note: f64,
    pub min_v: f64,
    pub max_v: f64,
}

impl KeyString {
    /// The string's volts at MIDI `note`.
    pub fn volts(&self, note: u8) -> f64 {
        ((note as f64 - self.ref_note) * self.v_per_semitone).clamp(self.min_v, self.max_v)
    }

    /// The control input `name`'s string, if the circuit file has one.
    pub fn of(spec: &CircuitSpec, name: &str) -> Option<KeyString> {
        let get = |k: &str| {
            spec.values
                .get(&format!("{name}_{k}"))
                .and_then(Value::as_map)
                .and_then(|m| m.get("value"))
                .and_then(Value::as_f64)
        };
        Some(KeyString {
            v_per_semitone: get("v_per_semitone")?,
            ref_note: get("ref_note")?,
            min_v: get("min_v")?,
            max_v: get("max_v")?,
        })
    }
}

/// What feeds one of a circuit's control inputs while a keyboard plays it.
#[derive(Debug, Clone, Copy, PartialEq)]
pub enum Feed {
    /// The keys' gate: (key up, key down) volts.
    Gate(f64, f64),
    /// The keys' gate with the key-down volts by velocity: key up, the device's
    /// velocity table ([`Device::velocity`]).
    VelocityGate(f64, &'static [(f64, f64)]),
    /// The last key's pitch.
    Pitch(Pitch),
    /// The last key on a linear contact string.
    Key(KeyString),
    /// The keyboard's aftertouch (channel or key pressure): 0 V at rest, the circuit
    /// file's `<name>_full_v` pressed fully.
    Pressure(f64),
}

impl Feed {
    /// Whether it is the keys' gate.
    pub fn is_gate(&self) -> bool {
        matches!(self, Feed::Gate(..) | Feed::VelocityGate(..))
    }

    /// A gate's key-up volts (None for other feeds).
    pub fn gate_up(&self) -> Option<f64> {
        match self {
            Feed::Gate(up, _) | Feed::VelocityGate(up, _) => Some(*up),
            _ => None,
        }
    }
}

/// The volts for velocity `vel` (1-127) over `range_db` on a velocity table.
pub fn velocity_volts(table: &[(f64, f64)], vel: u8, range_db: f64) -> f64 {
    let db = -range_db.max(0.0) * (127.0 - vel.clamp(1, 127) as f64) / 126.0;
    let (first, last) = (table[0], table[table.len() - 1]);
    if db <= first.0 {
        return first.1;
    }
    if db >= last.0 {
        return last.1;
    }
    let i = table.partition_point(|&(d, _)| d <= db);
    let ((d0, v0), (d1, v1)) = (table[i - 1], table[i]);
    v0 + (v1 - v0) * (db - d0) / (d1 - d0)
}

/// The Play view's velocity range at first (dB between velocity 127 and 1).
pub const VELOCITY_RANGE_DB: f64 = 18.0;
/// Its largest: the velocity table's measured span.
pub const VELOCITY_RANGE_MAX_DB: f64 = 30.0;

/// tube_synth's velocity table: `scripts/velocity_study.py` (reports/tube_synth/velocity.json,
/// 2026-11-01; a key held at -15 V, the panel's defaults, draft): the output's level
/// against the keyboard bus's key-down volts, re -1 V's (`gate_on_v`). The 6386's remote
/// cutoff makes it gentle down to ~-60 V (-19 dB), then the VCA closes fast (-35.5 dB at
/// -90 V); the harmonics stay ~7% throughout (the waveform's own, not the VCA's).
const TUBE_SYNTH_VELOCITY: &[(f64, f64)] = &[
    (-35.51, -90.0),
    (-27.17, -80.0),
    (-24.43, -75.0),
    (-22.15, -70.0),
    (-20.47, -65.0),
    (-19.06, -60.0),
    (-17.92, -55.0),
    (-16.96, -50.0),
    (-16.05, -45.0),
    (-15.25, -40.0),
    (-14.41, -35.0),
    (-13.54, -30.0),
    (-12.77, -26.0),
    (-12.08, -23.0),
    (-11.28, -20.0),
    (-10.73, -18.0),
    (-10.07, -16.0),
    (-9.21, -14.0),
    (-8.45, -12.0),
    (-7.36, -10.0),
    (-5.98, -8.0),
    (-4.53, -6.0),
    (-3.6, -5.0),
    (-2.76, -4.0),
    (-1.2, -3.0),
    (-0.45, -2.0),
    (0.0, -1.0),
];

/// The feeds of `spec`'s control inputs in its order, for `device` played from keys
/// (every control input needs one: the device's gate or pitch, or a key string the
/// circuit file describes).
pub fn key_feeds(device: &Device, spec: &CircuitSpec) -> Result<Vec<Feed>, String> {
    spec.cv_inputs
        .iter()
        .map(|(name, _)| {
            if device.gate == Some(name.as_str()) {
                let (up, down) = gate_levels(spec, name)?;
                Ok(match device.velocity {
                    Some(t) => Feed::VelocityGate(up, t),
                    None => Feed::Gate(up, down),
                })
            } else if let Some(p) = [device.pitch, device.pitch2]
                .into_iter()
                .flatten()
                .find(|p| p.control == name)
            {
                Ok(Feed::Pitch(p))
            } else if let Some(k) = KeyString::of(spec, name) {
                Ok(Feed::Key(k))
            } else if let Some(full) = spec
                .values
                .get(&format!("{name}_full_v"))
                .and_then(Value::as_map)
                .and_then(|m| m.get("value"))
                .and_then(Value::as_f64)
            {
                Ok(Feed::Pressure(full))
            } else {
                Err(format!(
                    "nothing plays the control input {name} from the keys"
                ))
            }
        })
        .collect()
}

/// A gate control input's (key up, key down) volts: the circuit file's `<name>_off_v`
/// and `<name>_on_v` values.
pub fn gate_levels(spec: &CircuitSpec, name: &str) -> Result<(f64, f64), String> {
    let get = |key: String| {
        spec.values
            .get(&key)
            .and_then(Value::as_map)
            .and_then(|m| m.get("value"))
            .and_then(Value::as_f64)
            .ok_or(format!("the circuit has no value {key} for its gate"))
    };
    Ok((get(format!("{name}_off_v"))?, get(format!("{name}_on_v"))?))
}

impl Device {
    /// Whether its circuit makes its own sound (a pitch input or `own_oscillator`): the
    /// keys don't play the test oscillator into it.
    pub fn plays_own_oscillator(&self) -> bool {
        self.own_oscillator || self.pitch.is_some()
    }

    /// The settings it plays at: `s` (its quality's) with its cores.
    pub fn play_settings(&self, s: &Settings) -> Settings {
        let mut s = s.clone();
        if let Some(c) = self.cores {
            s.cores = c.to_string();
        }
        if let Some(p) = self.partition {
            s.partition = p.iter().map(|t| t.to_string()).collect();
        }
        if let Some(c) = self.coupling {
            s.partition_coupling = c.to_string();
        }
        s
    }
}

pub const DEVICES: [Device; 16] = [
    Device {
        id: "fairchild_670",
        label: "Fairchild 670 (compressor)",
        circuit: "fairchild_670",
        panel: Some(&[
            "input_atten_db",
            "ac_threshold",
            "time_constant",
            "dc_threshold",
        ]),
        // HF-rich input (a drum stem's hi-hat at -11.5 dBFS) runs the draft 670's
        // sidechain bridge at 3-4x real time for up to ~170 ms at a time
        // (`examples/load_profile.rs`, 2026-10-28): 0.1 s ran dry.
        ahead_s: 0.25,
        quality: Quality::Draft1x,
        cores: None,
        mod_wheel: None,
        gate: None,
        velocity: None,
        pitch: None,
        own_oscillator: false,
        key: None,
        pitch2: None,
        coupling: None,
        partition: None,
    },
    Device {
        id: "pultec_eqp1a",
        label: "Pultec EQP-1A (program EQ)",
        circuit: "pultec_eqp1a",
        panel: None,
        ahead_s: AHEAD_S,
        quality: Quality::Draft1x,
        cores: None,
        mod_wheel: None,
        gate: None,
        velocity: None,
        pitch: None,
        own_oscillator: false,
        key: None,
        pitch2: None,
        coupling: None,
        partition: None,
    },
    Device {
        id: "fender_5e3",
        label: "Fender 5E3 Deluxe (guitar amp)",
        circuit: "fender_5e3",
        panel: None,
        // At full volume a guitar take (data/clips' dry guitar) clips hard enough to run
        // blocks at up to 2.3x real time, a backlog of 170 ms at worst (draft-2x,
        // `examples/load_profile.rs`, 2026-10-29); at volume 0.6, 8 ms.
        ahead_s: 0.25,
        // Hard clipped, it aliases -8 dB re its harmonics at draft-1x, -31 at the draft's
        // 96 kHz (amp_suite); 0.46x real time there on a guitar take (the user's choice,
        // 2026-10-29).
        quality: Quality::Draft2x,
        cores: None,
        mod_wheel: None,
        gate: None,
        velocity: None,
        pitch: None,
        own_oscillator: false,
        key: None,
        pitch2: None,
        coupling: None,
        partition: None,
    },
    Device {
        id: "reactor_filter",
        label: "Saturable-reactor low-pass (tube synth)",
        circuit: "reactor_filter",
        panel: None,
        ahead_s: AHEAD_S,
        // Its two hysteretic cores run 0.16-0.21x real time at draft-1x (Python's
        // circuitsim on a 110 Hz saw, 2026-10-29).
        quality: Quality::Draft1x,
        cores: Some("ja"),
        mod_wheel: Some("cutoff_v"),
        gate: None,
        velocity: None,
        pitch: None,
        own_oscillator: false,
        key: None,
        pitch2: None,
        coupling: None,
        partition: None,
    },
    Device {
        id: "tube_filter",
        label: "Tube reactor filter + VCA (tube synth)",
        circuit: "tube_filter",
        panel: None,
        ahead_s: AHEAD_S,
        // 0.30-0.45x real time at draft-1x with its JA cores (Python's circuitsim on a
        // 110 Hz saw, 2026-10-29).
        quality: Quality::Draft1x,
        cores: Some("ja"),
        mod_wheel: Some("cutoff"),
        gate: None,
        velocity: None,
        pitch: None,
        own_oscillator: false,
        key: None,
        pitch2: None,
        coupling: None,
        partition: None,
    },
    Device {
        id: "tube_voice",
        label: "Tube synth voice (envelope, push-pull VCA)",
        circuit: "tube_voice",
        panel: None,
        ahead_s: AHEAD_S,
        // 0.55-0.62x real time at draft-1x with its JA cores (Python's circuitsim on a
        // 110 Hz saw with a gate, 2026-10-29).
        quality: Quality::Draft1x,
        cores: Some("ja"),
        mod_wheel: Some("cutoff"),
        gate: Some("gate"),
        velocity: None,
        pitch: None,
        own_oscillator: false,
        key: None,
        pitch2: None,
        coupling: None,
        partition: None,
    },
    Device {
        id: "vco_lc",
        label: "Tube synth VCO (b): reactor-tuned LC",
        circuit: "vco_lc",
        panel: None,
        ahead_s: AHEAD_S,
        // Draft (96 kHz internal) runs it at 0.56x real time, draft-1x at 3.5x: its 48 kHz
        // step fights the square's edges (Python's circuitsim, 2026-10-30).
        quality: Quality::Draft2x,
        cores: Some("ja"),
        mod_wheel: Some("wave"),
        gate: None,
        velocity: None,
        pitch: Some(Pitch {
            control: "pitch",
            tuning: VCO_LC_TUNING,
            range: None,
        }),
        own_oscillator: false,
        key: None,
        pitch2: None,
        coupling: None,
        partition: None,
    },
    Device {
        id: "tube_synth",
        label: "Tube synth (oscillator, filter, envelope, VCA)",
        circuit: "tube_synth",
        panel: None,
        ahead_s: AHEAD_S,
        quality: Quality::Draft2x,
        cores: Some("ja"),
        mod_wheel: Some("cutoff"),
        gate: Some("gate"),
        velocity: Some(TUBE_SYNTH_VELOCITY),
        pitch: Some(Pitch {
            control: "pitch",
            tuning: TUBE_SYNTH_TUNING,
            range: Some(RangeSwitch {
                control: "range",
                low: TUBE_SYNTH_TUNING_LOW,
                split_hz: TUBE_SYNTH_SPLIT_HZ,
            }),
        }),
        // Four threads: the VCA and envelope (with the keys), the input stage and the
        // filter, the oscillator, the supplies (each partition owns the nodes it
        // drives stiffly: the filter's follower, the oscillator's buffer, the rails).
        // On two (the oscillator and the supplies on the second) it ran ~96% load;
        // bench, 3 s at -15 V: 1.38x real time on two, 0.89x on four, within 0.1 cent
        // and 0.01 dB of the one solve. The LFO (SYNTH_IDEAS.md #7) on a thread of its
        // own: it owns its pots' wipers, where the pitch and the cutoff hear it. The ring
        // modulator (#14) on one of its own, ahead of the oscillator and the LFO (they own
        // its inputs, the buffer and the LFO's output; it owns its output into the mixer):
        // on the filter's thread it cost +46%, alone nothing but a core. Empty (RING OFF,
        // or the LFO off), it gets no thread. The gas-tube saw (SAW ON) on one of its own with
        // its supply and its grid's side of the pitch (it owns the follower's cathode, where
        // the mixer hears it); OSC OFF empties the LC oscillator's.
        own_oscillator: false,
        key: None,
        pitch2: Some(Pitch {
            control: "pitch2",
            tuning: SYNTH_SAW_TUNING,
            range: None,
        }),
        coupling: None,
        partition: Some(&[
            "resonance",
            "|",
            "input",
            "filter",
            "cutoff",
            "|",
            "envelope",
            "|",
            "ring",
            "|",
            "oscillator",
            "pitch",
            "|",
            "saw pitch",
            "saw",
            "|",
            "lfo",
            "|",
            "power supply",
            "bias supply",
            "saw supply",
        ]),
    },
    Device {
        id: "tube_kick",
        label: "Tube kick (oscillator, pitch sweep, decaying VCA)",
        circuit: "tube_kick",
        panel: None,
        ahead_s: AHEAD_S,
        quality: Quality::Draft2x,
        cores: Some("ja"),
        mod_wheel: Some("depth"),
        gate: Some("gate"),
        velocity: None,
        pitch: None,
        own_oscillator: true,
        key: None,
        pitch2: None,
        coupling: None,
        // Three threads: the trigger, the envelopes and the VCA (with the keys) | the
        // oscillator and its pitch driver | the supplies.
        partition: Some(&["oscillator", "pitch", "|", "power supply", "bias supply"]),
    },
    Device {
        id: "saw_884",
        label: "Gas-tube sawtooth (884 thyratron)",
        circuit: "saw_884",
        panel: None,
        ahead_s: AHEAD_S,
        // The 884 as its event kernels (technique K: the draft's `events`), whose tables
        // step at 3.072 MHz: a whole 32 per step at the draft's 96 kHz (HYBRID_PHYSICS_PLAN.md
        // H4).
        quality: Quality::Draft2x,
        cores: None,
        mod_wheel: None,
        gate: Some("gate"),
        velocity: None,
        pitch: Some(Pitch {
            control: "pitch",
            tuning: SAW_884_TUNING,
            range: None,
        }),
        own_oscillator: false,
        key: None,
        pitch2: None,
        coupling: Some("hold"),
        // Two threads: the VCA | the rest (the oscillator, the keys and the envelope: control
        // inputs stay in the first part). The cuts are the VCA's grids (`ga`, `gt`), and the
        // saw's edge crosses at `ga`: extrapolated it was doubled for a sample (peaks 49 V
        // against 34), held it is the one solve's.
        partition: Some(&["vca"]),
    },
    Device {
        id: "plate_reverb",
        label: "Plate reverb (EMT 140 plate)",
        circuit: "plate_reverb",
        panel: Some(&["drive", "decay_500hz_s", "return_level"]),
        ahead_s: AHEAD_S,
        quality: Quality::Draft1x,
        cores: None,
        mod_wheel: None,
        gate: None,
        velocity: None,
        pitch: None,
        own_oscillator: false,
        key: None,
        pitch2: None,
        coupling: None,
        partition: None,
    },
    Device {
        id: "ampex_351_echo",
        label: "Ampex 351 slap echo (tape)",
        circuit: "ampex_351_echo",
        panel: Some(&[
            "drive",
            "send",
            "repeat",
            "capstan_hz",
            "speed",
            "equalization",
            "bias_adjust_f",
        ]),
        ahead_s: AHEAD_S,
        // Live, the tape plays its reduction (an events build: DELAY_PLAN.md, "The reduced
        // medium"); production prints the literal machine.
        quality: Quality::Draft1x,
        cores: None,
        mod_wheel: None,
        gate: None,
        velocity: None,
        pitch: None,
        own_oscillator: false,
        key: None,
        pitch2: None,
        // Cut at the medium (the tape senses its record head a sample late), held across
        // the cut: at full DRIVE the saturating record side's Newton work splits from the
        // repro side's (0.55x real time, p95 1.25; one thread 0.85x, p95 1.95; at the
        // default DRIVE 0.50x, p95 1.35 against 0.55x, 0.80: DELAY_PLAN.md, DRIVE).
        coupling: Some("hold"),
        partition: Some(&[
            "heads and tape",
            "reproduce amplifier",
            "output",
            "|",
            "power supply",
        ]),
    },
    Device {
        id: "ampex_351_2_echo",
        label: "Ampex 351-2 ping-pong echo (tape, stereo)",
        circuit: "ampex_351_2_echo",
        panel: Some(&[
            "drive",
            "send",
            "repeat",
            "capstan_hz",
            "speed",
            "equalization",
            "bias_adjust_f",
        ]),
        ahead_s: AHEAD_S,
        // Live, its tapes play their reduction (an events build), as the 351 echo's.
        quality: Quality::Draft1x,
        cores: None,
        mod_wheel: None,
        gate: None,
        velocity: None,
        pitch: None,
        own_oscillator: false,
        key: None,
        pitch2: None,
        // Held across the cuts: extrapolated, the crossed slap through each part's input
        // bus kept the record side's Newton from contracting (13.6 iterations a sample
        // against 3.4; 1.8x real time against 0.55x; DELAY_PLAN.md, "PING-PONG").
        coupling: Some("hold"),
        // Cut at the media: both record sides with the input, each channel's tape, repro
        // and output on a thread of its own (a tape senses its record head a sample late:
        // partition.rs), the supplies and the capstan's last.
        partition: Some(&[
            "heads and tape",
            "reproduce amplifier",
            "output",
            "|",
            "heads and tape (right)",
            "reproduce amplifier (right)",
            "output (right)",
            "|",
            "power supply",
            "power supply (right)",
            "capstan",
        ]),
    },
    Device {
        id: "telefunken_v76",
        label: "Telefunken V76 (mic preamp)",
        circuit: "telefunken_v76",
        panel: Some(&["gain_db", "bass_cut", "treble_cut"]),
        ahead_s: AHEAD_S,
        // Four pentodes, three JA cores and a selenium supply (B10).
        quality: Quality::Draft1x,
        cores: None,
        mod_wheel: None,
        gate: None,
        velocity: None,
        pitch: None,
        own_oscillator: false,
        key: None,
        // The supply on a thread of its own, coupled through its rails (as the 670's).
        partition: Some(&["power supply"]),
        coupling: None,
        pitch2: None,
    },
    Device {
        id: "fairchild_670_keyed",
        label: "Fairchild 670 + key (compressor, sidechain)",
        circuit: "fairchild_670_keyed",
        panel: Some(&[
            "key_mode",
            "key_depth",
            "input_atten_db",
            "ac_threshold",
            "time_constant",
            "dc_threshold",
        ]),
        // The 670's (above).
        ahead_s: 0.25,
        quality: Quality::Draft1x,
        cores: None,
        mod_wheel: None,
        gate: None,
        velocity: None,
        pitch: None,
        own_oscillator: false,
        key: Some("key"),
        pitch2: None,
        coupling: None,
        partition: None,
    },
    Device {
        id: "sideman_bd",
        label: "Side Man bass drum (Wurlitzer, 1960)",
        circuit: "sideman_bd",
        panel: None,
        ahead_s: AHEAD_S,
        // One 12AX7 section ringing and the 6AV6 preamp: production runs about real time.
        quality: Quality::Draft2x,
        cores: None,
        // The mod wheel turns R106, the ring (DRUM_PLAN.md D2a).
        mod_wheel: Some("ring"),
        gate: Some("gate"),
        velocity: None,
        pitch: None,
        // The keys ground its key line (K1), as the commutator does: it makes its own sound.
        own_oscillator: true,
        key: None,
        pitch2: None,
        coupling: None,
        partition: None,
    },
];

/// The devices that can go at a chain's end (`player::EndDevice`: after the device played,
/// on a thread of its own). The 670 and the EQP-1A would fit too; the reverb first.
pub const CHAIN_ENDS: [&str; 3] = ["plate_reverb", "ampex_351_echo", "ampex_351_2_echo"];

/// Where AUTO changes range: keys below it play on LOW (`range` 0, the tank's 224 nF),
/// the rest on HIGH. At 330 Hz (E4) the two sound most alike (measured at draft, the same
/// pitch on each: LOW 1.4 dB louder, the harmonics within 2 dB; at 440-660 Hz LOW has 7-9 dB
/// more 2nd harmonic); crossing it adds no pop or glide beyond the supply ripple's FM (the
/// key waits a block or two for the switch). LOW's pitch is steadier up to its top (17
/// against 27 cents cycle to cycle at 330 Hz), so the split trades that for the tone.
const TUBE_SYNTH_SPLIT_HZ: f64 = 330.0;

/// tube_synth's keyboard tuning at HIGH (`range` 1, the tank's 56 nF): `scripts/vco_study.py
/// --only synth --tuning draft --step 0.25 --set range=1 --floor -25.0 --suffix _high`
/// (reports/tube_synth/vco/synth_tuning_high.json, 2026-11-01, with the LFO and VIBRATO's
/// summing ahead of GLIDE: the key string scaled by 0.979): 26.1 Hz to 1.73 kHz. Below
/// -25 V a plateau (the cores saturated, another regime).
const TUBE_SYNTH_TUNING: &[(f64, f64)] = &[
    (26.1, -25.0),
    (30.48, -24.75),
    (35.19, -24.5),
    (40.15, -24.25),
    (45.4, -24.0),
    (51.06, -23.75),
    (57.1, -23.5),
    (63.34, -23.25),
    (70.2, -23.0),
    (77.65, -22.75),
    (85.53, -22.5),
    (94.14, -22.25),
    (103.33, -22.0),
    (113.11, -21.75),
    (123.27, -21.5),
    (134.04, -21.25),
    (145.09, -21.0),
    (156.42, -20.75),
    (168.04, -20.5),
    (179.87, -20.25),
    (192.04, -20.0),
    (204.42, -19.75),
    (217.07, -19.5),
    (230.02, -19.25),
    (243.27, -19.0),
    (256.81, -18.75),
    (270.64, -18.5),
    (284.8, -18.25),
    (299.25, -18.0),
    (314.03, -17.75),
    (329.14, -17.5),
    (344.57, -17.25),
    (360.33, -17.0),
    (376.38, -16.75),
    (392.77, -16.5),
    (409.47, -16.25),
    (426.49, -16.0),
    (443.8, -15.75),
    (461.44, -15.5),
    (479.37, -15.25),
    (497.45, -15.0),
    (515.47, -14.75),
    (533.62, -14.5),
    (551.9, -14.25),
    (570.34, -14.0),
    (588.92, -13.75),
    (607.67, -13.5),
    (626.58, -13.25),
    (645.64, -13.0),
    (664.87, -12.75),
    (684.23, -12.5),
    (703.76, -12.25),
    (723.44, -12.0),
    (743.24, -11.75),
    (763.18, -11.5),
    (783.26, -11.25),
    (803.46, -11.0),
    (823.79, -10.75),
    (844.21, -10.5),
    (864.75, -10.25),
    (885.39, -10.0),
    (906.14, -9.75),
    (926.96, -9.5),
    (947.87, -9.25),
    (968.87, -9.0),
    (989.92, -8.75),
    (1011.05, -8.5),
    (1032.24, -8.25),
    (1053.49, -8.0),
    (1074.79, -7.75),
    (1096.13, -7.5),
    (1117.51, -7.25),
    (1138.93, -7.0),
    (1160.38, -6.75),
    (1181.84, -6.5),
    (1203.33, -6.25),
    (1224.83, -6.0),
    (1246.35, -5.75),
    (1267.87, -5.5),
    (1289.39, -5.25),
    (1310.91, -5.0),
    (1332.42, -4.75),
    (1353.93, -4.5),
    (1375.4, -4.25),
    (1396.86, -4.0),
    (1418.3, -3.75),
    (1439.71, -3.5),
    (1461.09, -3.25),
    (1482.43, -3.0),
    (1503.73, -2.75),
    (1524.99, -2.5),
    (1546.2, -2.25),
    (1567.37, -2.0),
    (1588.47, -1.75),
    (1609.52, -1.5),
    (1630.52, -1.25),
    (1651.46, -1.0),
    (1672.32, -0.75),
    (1693.12, -0.5),
    (1713.85, -0.25),
    (1734.5, 0.0),
];

/// tube_synth's keyboard tuning at LOW (`range` 0, 224 nF): as the HIGH table with
/// `--set range=0 --floor -25.25 --suffix _low` (synth_tuning_low.json): 18.7 Hz to 788 Hz;
/// a gentler law, so less of the supply's ripple FM in cents (9 cents cycle to cycle at
/// 110 Hz against ~30 at HIGH).
const TUBE_SYNTH_TUNING_LOW: &[(f64, f64)] = &[
    (18.73, -25.25),
    (21.29, -25.0),
    (24.08, -24.75),
    (26.68, -24.5),
    (29.73, -24.25),
    (32.57, -24.0),
    (35.67, -23.75),
    (38.86, -23.5),
    (42.09, -23.25),
    (45.49, -23.0),
    (48.99, -22.75),
    (52.61, -22.5),
    (56.38, -22.25),
    (60.06, -22.0),
    (64.18, -21.75),
    (68.39, -21.5),
    (72.72, -21.25),
    (77.21, -21.0),
    (81.88, -20.75),
    (86.71, -20.5),
    (91.74, -20.25),
    (96.96, -20.0),
    (102.36, -19.75),
    (107.98, -19.5),
    (113.8, -19.25),
    (120.09, -19.0),
    (126.07, -18.75),
    (132.52, -18.5),
    (139.19, -18.25),
    (146.1, -18.0),
    (153.21, -17.75),
    (160.55, -17.5),
    (168.1, -17.25),
    (175.88, -17.0),
    (183.86, -16.75),
    (192.03, -16.5),
    (200.43, -16.25),
    (208.99, -16.0),
    (217.78, -15.75),
    (226.72, -15.5),
    (235.82, -15.25),
    (245.01, -15.0),
    (254.2, -14.75),
    (263.42, -14.5),
    (272.71, -14.25),
    (282.06, -14.0),
    (291.47, -13.75),
    (300.94, -13.5),
    (310.45, -13.25),
    (320.03, -13.0),
    (329.62, -12.75),
    (339.27, -12.5),
    (348.96, -12.25),
    (358.66, -12.0),
    (368.39, -11.75),
    (378.13, -11.5),
    (387.88, -11.25),
    (397.65, -11.0),
    (407.43, -10.75),
    (417.21, -10.5),
    (426.98, -10.25),
    (436.74, -10.0),
    (446.5, -9.75),
    (456.24, -9.5),
    (465.98, -9.25),
    (475.69, -9.0),
    (485.38, -8.75),
    (495.05, -8.5),
    (504.7, -8.25),
    (514.31, -8.0),
    (523.9, -7.75),
    (533.45, -7.5),
    (542.94, -7.25),
    (552.42, -7.0),
    (561.83, -6.75),
    (571.2, -6.5),
    (580.51, -6.25),
    (589.77, -6.0),
    (598.96, -5.75),
    (608.1, -5.5),
    (617.18, -5.25),
    (626.18, -5.0),
    (635.12, -4.75),
    (643.99, -4.5),
    (652.78, -4.25),
    (661.48, -4.0),
    (670.12, -3.75),
    (678.66, -3.5),
    (687.12, -3.25),
    (695.49, -3.0),
    (703.77, -2.75),
    (711.96, -2.5),
    (720.04, -2.25),
    (728.03, -2.0),
    (735.92, -1.75),
    (743.71, -1.5),
    (751.39, -1.25),
    (758.96, -1.0),
    (766.43, -0.75),
    (773.78, -0.5),
    (781.02, -0.25),
    (788.14, 0.0),
];

/// vco_lc's keyboard tuning: `scripts/vco_study.py --only lc --tuning draft`
/// (reports/tube_synth/vco/lc_tuning.json, 2026-10-30): 68 Hz to 1.8 kHz, smooth and
/// monotonic (below -42 V the tank's swing saturates the cores and the pitch turns
/// chaotic, so the table stops there and lower keys hold at its bottom).
const VCO_LC_TUNING: &[(f64, f64)] = &[
    (68.09, -42.0),
    (93.64, -41.0),
    (120.47, -40.0),
    (147.61, -39.0),
    (174.89, -38.0),
    (202.62, -37.0),
    (231.04, -36.0),
    (260.34, -35.0),
    (290.7, -34.0),
    (322.23, -33.0),
    (355.05, -32.0),
    (389.2, -31.0),
    (424.76, -30.0),
    (461.82, -29.0),
    (500.28, -28.0),
    (540.17, -27.0),
    (581.6, -26.0),
    (624.47, -25.0),
    (668.72, -24.0),
    (714.32, -23.0),
    (761.17, -22.0),
    (809.18, -21.0),
    (858.24, -20.0),
    (908.09, -19.0),
    (956.96, -18.0),
    (1005.44, -17.0),
    (1053.79, -16.0),
    (1102.07, -15.0),
    (1150.24, -14.0),
    (1198.33, -13.0),
    (1246.23, -12.0),
    (1293.99, -11.0),
    (1341.48, -10.0),
    (1388.77, -9.0),
    (1435.77, -8.0),
    (1482.48, -7.0),
    (1528.88, -6.0),
    (1574.68, -5.0),
    (1620.72, -4.0),
    (1666.05, -3.0),
    (1711.06, -2.0),
    (1755.6, -1.0),
    (1799.85, 0.0),
];

/// saw_884's keyboard tuning: `scripts/saw_884_tuning.py` (reports/hybrid/saw_884_tuning.json,
/// 2026-11-03): the 884 as its event kernels at the draft, the pitch read on CT's lower plate
/// `n`, 5 V apart and bisected wherever the interpolation missed the law by more than 1 cent:
/// 13.2 Hz to 4.52 kHz. Below ~17 Hz (the two lowest points) the ramp is slower than K's
/// tables reach (0.002 V/us), so K holds their end there. A render (M1) can sit flat of it
/// in the bass (HYBRID_PHYSICS_PLAN.md H4: up to ~7 cents at 180 Hz, ~23 at 47 Hz, open).
const SAW_884_TUNING: &[(f64, f64)] = &[
    (13.15, -250.0),
    (15.58, -248.75),
    (18.42, -247.5),
    (21.71, -246.25),
    (25.5, -245.0),
    (29.84, -243.75),
    (34.77, -242.5),
    (40.34, -241.25),
    (46.6, -240.0),
    (49.99, -239.375),
    (53.56, -238.75),
    (57.32, -238.125),
    (61.27, -237.5),
    (65.4, -236.875),
    (69.73, -236.25),
    (74.25, -235.625),
    (78.97, -235.0),
    (83.88, -234.375),
    (88.97, -233.75),
    (94.26, -233.125),
    (99.73, -232.5),
    (105.4, -231.875),
    (111.25, -231.25),
    (117.29, -230.625),
    (123.51, -230.0),
    (136.49, -228.75),
    (150.13, -227.5),
    (164.43, -226.25),
    (179.36, -225.0),
    (194.9, -223.75),
    (211.01, -222.5),
    (227.65, -221.25),
    (244.75, -220.0),
    (262.34, -218.75),
    (280.38, -217.5),
    (298.84, -216.25),
    (317.7, -215.0),
    (336.94, -213.75),
    (356.54, -212.5),
    (376.43, -211.25),
    (396.58, -210.0),
    (417.02, -208.75),
    (437.73, -207.5),
    (458.7, -206.25),
    (479.91, -205.0),
    (501.36, -203.75),
    (523.02, -202.5),
    (544.89, -201.25),
    (566.96, -200.0),
    (589.22, -198.75),
    (611.61, -197.5),
    (656.76, -195.0),
    (702.49, -192.5),
    (748.76, -190.0),
    (795.52, -187.5),
    (842.72, -185.0),
    (890.33, -182.5),
    (938.31, -180.0),
    (986.63, -177.5),
    (1034.79, -175.0),
    (1083.22, -172.5),
    (1131.9, -170.0),
    (1180.81, -167.5),
    (1229.93, -165.0),
    (1279.25, -162.5),
    (1328.76, -160.0),
    (1378.45, -157.5),
    (1428.29, -155.0),
    (1528.43, -150.0),
    (1578.71, -147.5),
    (1628.75, -145.0),
    (1728.47, -140.0),
    (1828.54, -135.0),
    (1928.92, -130.0),
    (2029.58, -125.0),
    (2130.48, -120.0),
    (2231.61, -115.0),
    (2332.94, -110.0),
    (2434.46, -105.0),
    (2536.14, -100.0),
    (2636.9, -95.0),
    (2736.62, -90.0),
    (2836.4, -85.0),
    (2936.22, -80.0),
    (3036.08, -75.0),
    (3135.98, -70.0),
    (3235.91, -65.0),
    (3335.87, -60.0),
    (3435.86, -55.0),
    (3535.86, -50.0),
    (3635.87, -45.0),
    (3735.9, -40.0),
    (3835.95, -35.0),
    (3936.0, -30.0),
    (4036.06, -25.0),
    (4136.13, -20.0),
    (4232.87, -15.0),
    (4329.43, -10.0),
    (4425.93, -5.0),
    (4522.37, 0.0),
];

/// tube_synth's gas-tube saw's keyboard tuning (`pitch2`): `scripts/saw_884_tuning.py
/// --target synth` (reports/hybrid/synth_saw_tuning.json, 2026-11-03): K at the draft, the
/// saw alone on (its own supply, the LFO off: the vibrato follower's grid at 0 V either
/// way), the pitch read on its CT plate `s_ct`, 5 V apart and bisected wherever the
/// interpolation missed the law by more than 1 cent: 10.8 Hz to 3.99 kHz. Below ~15 Hz (the
/// lowest 3 points) the ramp is slower than K's tables reach (0.002 V/us), so K holds their
/// end there. A render (M1) sits flat of it in the bass (+33 cents K over M1 at 39 Hz, under
/// 1 cent from 1.9 kHz up: HYBRID_PHYSICS_PLAN.md H4, open).
const SYNTH_SAW_TUNING: &[(f64, f64)] = &[
    (10.81, -310.0),
    (12.89, -308.75),
    (15.31, -307.5),
    (18.1, -306.25),
    (21.32, -305.0),
    (23.09, -304.375),
    (24.98, -303.75),
    (26.99, -303.125),
    (29.13, -302.5),
    (31.39, -301.875),
    (33.78, -301.25),
    (36.3, -300.625),
    (38.95, -300.0),
    (41.74, -299.375),
    (44.67, -298.75),
    (47.73, -298.125),
    (50.94, -297.5),
    (54.27, -296.875),
    (57.75, -296.25),
    (61.36, -295.625),
    (65.1, -295.0),
    (68.98, -294.375),
    (72.99, -293.75),
    (77.14, -293.125),
    (81.41, -292.5),
    (85.8, -291.875),
    (90.32, -291.25),
    (94.95, -290.625),
    (99.7, -290.0),
    (109.55, -288.75),
    (119.85, -287.5),
    (130.55, -286.25),
    (141.65, -285.0),
    (153.09, -283.75),
    (164.89, -282.5),
    (177.01, -281.25),
    (189.44, -280.0),
    (202.16, -278.75),
    (215.15, -277.5),
    (228.38, -276.25),
    (241.82, -275.0),
    (255.48, -273.75),
    (269.35, -272.5),
    (283.42, -271.25),
    (297.68, -270.0),
    (312.1, -268.75),
    (326.69, -267.5),
    (341.44, -266.25),
    (356.33, -265.0),
    (371.35, -263.75),
    (386.44, -262.5),
    (401.65, -261.25),
    (416.97, -260.0),
    (447.94, -257.5),
    (479.29, -255.0),
    (511.01, -252.5),
    (543.05, -250.0),
    (575.38, -247.5),
    (607.97, -245.0),
    (640.67, -242.5),
    (673.59, -240.0),
    (706.71, -237.5),
    (740.02, -235.0),
    (773.5, -232.5),
    (807.15, -230.0),
    (840.95, -227.5),
    (874.88, -225.0),
    (908.95, -222.5),
    (943.14, -220.0),
    (977.45, -217.5),
    (1011.61, -215.0),
    (1080.06, -210.0),
    (1148.78, -205.0),
    (1217.82, -200.0),
    (1287.12, -195.0),
    (1356.65, -190.0),
    (1426.39, -185.0),
    (1496.32, -180.0),
    (1566.42, -175.0),
    (1636.21, -170.0),
    (1705.63, -165.0),
    (1775.14, -160.0),
    (1844.75, -155.0),
    (1914.44, -150.0),
    (1984.2, -145.0),
    (2054.04, -140.0),
    (2123.94, -135.0),
    (2193.91, -130.0),
    (2263.93, -125.0),
    (2334.0, -120.0),
    (2404.13, -115.0),
    (2474.3, -110.0),
    (2544.52, -105.0),
    (2614.19, -100.0),
    (2682.96, -95.0),
    (2751.73, -90.0),
    (2820.51, -85.0),
    (2889.29, -80.0),
    (2958.07, -75.0),
    (3026.85, -70.0),
    (3095.64, -65.0),
    (3164.42, -60.0),
    (3233.21, -55.0),
    (3302.01, -50.0),
    (3370.8, -45.0),
    (3439.59, -40.0),
    (3508.4, -35.0),
    (3577.2, -30.0),
    (3646.01, -25.0),
    (3714.81, -20.0),
    (3783.63, -15.0),
    (3852.45, -10.0),
    (3921.28, -5.0),
    (3990.1, 0.0),
];

/// Controls never on a panel (operating conditions).
const OFF_PANEL: [&str; 2] = ["mains_v_rms", "mains_hz"];

/// Labels for control keys (keys otherwise).
const LABELS: [(&str, &str); 53] = [
    ("range", "Range (AUTO: by key)"),
    ("drive", "Drive (console line amp)"),
    ("send", "Send"),
    ("repeat", "Repeat"),
    ("capstan_hz", "Varispeed (capstan supply, Hz)"),
    ("speed", "Tape speed 15 ips (off: 7-1/2)"),
    ("equalization", "Record EQ HI, 15 ips (off: LOW, 7-1/2)"),
    ("bias_adjust_f", "Bias (BIAS ADJUST; aligned 31 pF)"),
    ("input_atten_db", "Input attenuator (dB)"),
    ("ac_threshold", "Threshold (AC)"),
    ("time_constant", "Time constant"),
    ("dc_threshold", "DC threshold trim"),
    ("lf_freq_hz", "Low frequency (Hz)"),
    ("lf_boost", "Low boost"),
    ("lf_atten", "Low atten"),
    ("hf_boost_freq_khz", "High boost frequency (kHz)"),
    ("hf_boost", "High boost"),
    ("bandwidth", "Bandwidth (sharp to broad)"),
    ("hf_atten_freq_khz", "High atten frequency (kHz)"),
    ("hf_atten", "High atten"),
    ("input_jack", "Input (1-2 bright, 3-4 normal)"),
    ("volume_bright", "Volume, bright"),
    ("volume_normal", "Volume, normal"),
    ("tone", "Tone"),
    ("cutoff_v", "Cutoff (control V)"),
    ("r_load_ohm", "Load (damping to resonance, ohm)"),
    ("cutoff", "Cutoff"),
    ("resonance", "Resonance"),
    ("level", "Level (VCA)"),
    ("attack", "Attack"),
    ("decay", "Decay"),
    ("sustain", "Sustain"),
    ("release", "Release"),
    ("wave", "Wave (tank to square)"),
    ("glide", "Glide"),
    ("key_track", "Key track"),
    ("pressure", "Pressure (aftertouch)"),
    ("heater", "Heater (x rated; under 0.9 out of rating)"),
    ("reservoir", "Reservoir (hum; under 6 \u{b5}F detunes)"),
    ("lfo_on", "LFO on (off saves a core)"),
    ("lfo_audio", "LFO audio range (8 Hz-1.9 kHz)"),
    ("lfo_rate", "LFO rate"),
    ("vibrato", "Vibrato (LFO to pitch)"),
    ("wobble", "Wobble (LFO to cutoff)"),
    ("ring_on", "Ring mod on (needs the LFO; off saves a core)"),
    ("ring", "Ring level (oscillator x LFO)"),
    ("osc_level", "Oscillator level"),
    ("osc_on", "Oscillator on (LC; off saves a core)"),
    ("saw_on", "Saw on (gas-tube 884; off saves a core)"),
    ("saw_level", "Saw level"),
    ("drive", "Drive (send level)"),
    ("decay_500hz_s", "Decay at 500 Hz (s)"),
    ("return_level", "Return"),
];

/// How a knob moves.
#[derive(Debug, Clone, PartialEq)]
pub enum Kind {
    /// A continuous range.
    Range { min: f64, max: f64 },
    /// Whole steps from `min` to `max` (a switch or a stepped attenuator); `int` says
    /// whether the circuit takes an integer (a switch position).
    Steps { min: f64, max: f64, int: bool },
    /// A selector's positions.
    Choices(Vec<Value>),
    /// An on / off switch (`unit: switch`, choices [0, 1]): a checkbox, the circuit
    /// getting 0 or 1.
    Toggle,
}

/// One knob: its control key, label, kind and value.
#[derive(Debug, Clone, PartialEq)]
pub struct Knob {
    pub key: String,
    pub label: String,
    pub kind: Kind,
    pub default: Value,
    pub value: Value,
    /// The control's unit in the circuit file (`unit`), if it has one.
    pub unit: Option<String>,
}

impl Knob {
    /// How a choice reads on the panel: a capacitance (unit F) in uF, else as written.
    pub fn choice_text(&self, v: &Value) -> String {
        match (self.unit.as_deref(), v.as_f64()) {
            (Some("F"), Some(f)) => format!("{} \u{b5}F", (f * 1e7).round() / 10.0),
            _ => v.py_str(),
        }
    }

    /// A range's display scale: an SI prefix on its unit when its values are tiny (a
    /// capacitance in farads shows in pF: a slider's decimals would round 31 pF to 0), as
    /// (factor, suffix); (1, "") otherwise.
    pub fn display_scale(&self) -> (f64, String) {
        let Kind::Range { min, max } = self.kind else {
            return (1.0, String::new());
        };
        let top = min.abs().max(max.abs());
        let Some(unit) = self.unit.as_deref().filter(|_| top > 0.0 && top < 1e-2) else {
            return (1.0, String::new());
        };
        for (f, p) in [(1e3, "m"), (1e6, "u"), (1e9, "n"), (1e12, "p"), (1e15, "f")] {
            if top * f >= 1.0 {
                return (f, format!(" {p}{unit}"));
            }
        }
        (1e15, format!(" f{unit}"))
    }

    /// The value as a number (a choice's index for selectors).
    pub fn number(&self) -> f64 {
        match &self.kind {
            Kind::Choices(c) => c.iter().position(|v| v.py_eq(&self.value)).unwrap_or(0) as f64,
            _ => self.value.as_f64().unwrap_or(0.0),
        }
    }
}

/// The knobs of `device`'s panel, at the circuit's defaults.
pub fn knobs(device: &Device, spec: &CircuitSpec) -> Vec<Knob> {
    let mut out = Vec::new();
    for (key, e) in spec.controls.iter() {
        if OFF_PANEL.contains(&key) || device.panel.is_some_and(|p| !p.contains(&key)) {
            continue;
        }
        let Some(e) = e.as_map() else { continue };
        let mut default = e.get("value").cloned().unwrap_or(Value::Null);
        let num = |k: &str| e.get(k).and_then(Value::as_f64);
        let range = device
            .pitch
            .and_then(|p| p.range)
            .filter(|r| r.control == key);
        let kind = if range.is_some() {
            // LOW / HIGH / AUTO; the circuit gets 0 or 1 (`values`, the player).
            default = Value::Str("AUTO".into());
            Kind::Choices(
                RANGE_MODES
                    .iter()
                    .map(|m| Value::Str(m.to_string()))
                    .collect(),
            )
        } else if e.get("unit").and_then(Value::as_str) == Some("switch") {
            Kind::Toggle
        } else if let Some(c) = e.get("choices").and_then(Value::as_list) {
            // A two-position switch (0 / 1) is a checkbox, as `unit: switch`.
            if matches!(c, [Value::Int(0), Value::Int(1)]) {
                Kind::Toggle
            } else {
                Kind::Choices(c.to_vec())
            }
        } else {
            let (min, max) = (num("min").unwrap_or(0.0), num("max").unwrap_or(1.0));
            let position = e.get("unit").and_then(Value::as_str) == Some("position");
            // The attenuator is 1 dB per step ([MAN] p.5; the web page's slider step).
            if position || key == "input_atten_db" {
                Kind::Steps {
                    min,
                    max,
                    int: position,
                }
            } else {
                Kind::Range { min, max }
            }
        };
        let label = LABELS
            .iter()
            .find(|(k, _)| *k == key)
            .map_or(key.to_string(), |(_, l)| l.to_string());
        out.push(Knob {
            key: key.to_string(),
            label,
            kind,
            value: default.clone(),
            default,
            unit: e.get("unit").and_then(Value::as_str).map(str::to_string),
        });
    }
    // The 670's panel in the order the device lists it.
    if let Some(order) = device.panel {
        out.sort_by_key(|k| order.iter().position(|o| *o == k.key));
    }
    out
}

/// The knobs' values as overrides. A range switch goes to the circuit as its position:
/// LOW 0, HIGH 1, and AUTO 1 until the keys choose (the player, [`range_mode`]).
pub fn values(knobs: &[Knob]) -> Values {
    knobs
        .iter()
        .map(|k| {
            let v = match RangeMode::from_value(&k.value) {
                Some(RangeMode::Low) => Value::Int(0),
                Some(_) => Value::Int(1),
                None => k.value.clone(),
            };
            (k.key.clone(), v)
        })
        .collect()
}

/// Where the panel's range switch is set, if it has one.
pub fn range_mode(knobs: &[Knob]) -> Option<RangeMode> {
    knobs.iter().find_map(|k| RangeMode::from_value(&k.value))
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::path::Path;
    use varimu_circuit::spec;

    fn spec_of(name: &str) -> CircuitSpec {
        let config = Path::new(env!("CARGO_MANIFEST_DIR")).join("../../config");
        spec::load_circuit(&spec::circuit_path(&config, name).unwrap()).unwrap()
    }

    #[test]
    fn v76_panel_is_its_switches() {
        let d = DEVICES.iter().find(|d| d.id == "telefunken_v76").unwrap();
        let k = knobs(d, &spec_of("telefunken_v76"));
        let keys: Vec<&str> = k.iter().map(|k| k.key.as_str()).collect();
        assert_eq!(keys, d.panel.unwrap());
        // A two-position switch (choices [0, 1]) is a checkbox.
        let treble = k.iter().find(|k| k.key == "treble_cut").unwrap();
        assert_eq!(treble.kind, Kind::Toggle);
    }

    #[test]
    fn echo_panel_switches_and_bias() {
        let d = DEVICES.iter().find(|d| d.id == "ampex_351_echo").unwrap();
        let k = knobs(d, &spec_of("ampex_351_echo"));
        for key in ["speed", "equalization"] {
            let s = k.iter().find(|k| k.key == key).unwrap();
            assert_eq!(s.kind, Kind::Toggle);
            assert_eq!(s.number(), 1.0); // 15 ips, HI
        }
        // BIAS ADJUST in farads shows in pF (a slider's 3 decimals would round it to 0).
        let bias = k.iter().find(|k| k.key == "bias_adjust_f").unwrap();
        let (f, suffix) = bias.display_scale();
        assert_eq!((f, suffix.as_str()), (1e12, " pF"));
        assert!((bias.number() * f - 31.08).abs() < 0.01);
        let drive = k.iter().find(|k| k.key == "drive").unwrap();
        assert_eq!(drive.display_scale().0, 1.0);
    }

    #[test]
    fn panels() {
        let k = knobs(&DEVICES[0], &spec_of("fairchild_670"));
        let keys: Vec<&str> = k.iter().map(|k| k.key.as_str()).collect();
        assert_eq!(keys, DEVICES[0].panel.unwrap());
        assert_eq!(
            k[2].kind,
            Kind::Steps {
                min: 1.0,
                max: 6.0,
                int: true
            }
        );
        let k = knobs(&DEVICES[1], &spec_of("pultec_eqp1a"));
        assert!(k.iter().all(|k| !OFF_PANEL.contains(&k.key.as_str())));
        let lf = k.iter().find(|k| k.key == "lf_freq_hz").unwrap();
        assert!(matches!(&lf.kind, Kind::Choices(c) if c.len() == 4));
        assert_eq!(lf.number(), 2.0); // 60 Hz
        let k = knobs(&DEVICES[2], &spec_of("fender_5e3"));
        let keys: Vec<&str> = k.iter().map(|k| k.key.as_str()).collect();
        assert_eq!(
            keys,
            ["input_jack", "volume_bright", "volume_normal", "tone"]
        );
        assert!(matches!(&k[0].kind, Kind::Choices(c) if c.len() == 4));
        let k = knobs(&DEVICES[3], &spec_of("reactor_filter"));
        let keys: Vec<&str> = k.iter().map(|k| k.key.as_str()).collect();
        assert_eq!(keys, ["cutoff_v", "r_load_ohm"]);
        assert!(keys.contains(&DEVICES[3].mod_wheel.unwrap()));
        let k = knobs(&DEVICES[4], &spec_of("tube_filter"));
        let keys: Vec<&str> = k.iter().map(|k| k.key.as_str()).collect();
        assert_eq!(keys, ["cutoff", "resonance", "level"]);
        assert!(keys.contains(&DEVICES[4].mod_wheel.unwrap()));
        let voice = spec_of("tube_voice");
        let k = knobs(&DEVICES[5], &voice);
        let keys: Vec<&str> = k.iter().map(|k| k.key.as_str()).collect();
        assert_eq!(keys, ["cutoff", "resonance", "attack", "release"]);
        assert_eq!(
            gate_levels(&voice, DEVICES[5].gate.unwrap()),
            Ok((-110.0, -1.0))
        );
        assert_eq!(
            key_feeds(&DEVICES[5], &voice),
            Ok(vec![Feed::Gate(-110.0, -1.0)])
        );
        let vco = spec_of("vco_lc");
        let k = knobs(&DEVICES[6], &vco);
        let keys: Vec<&str> = k.iter().map(|k| k.key.as_str()).collect();
        assert_eq!(keys, ["wave"]);
        let pitch = DEVICES[6].pitch.unwrap();
        assert_eq!(key_feeds(&DEVICES[6], &vco), Ok(vec![Feed::Pitch(pitch)]));
        let synth = spec_of("tube_synth");
        let k = knobs(&DEVICES[7], &synth);
        let keys: Vec<&str> = k.iter().map(|k| k.key.as_str()).collect();
        assert_eq!(
            keys,
            [
                "cutoff",
                "resonance",
                "attack",
                "decay",
                "sustain",
                "release",
                "env_amount",
                "key_track",
                "pressure",
                "glide",
                "wave",
                "range",
                "reservoir",
                "lfo_on",
                "lfo_audio",
                "lfo_rate",
                "vibrato",
                "wobble",
                "ring_on",
                "ring",
                "osc_on",
                "osc_level",
                "saw_on",
                "saw_level",
                "heater"
            ]
        );
        // The LFO's ON / OFF switch (`unit: switch`) is a checkbox, as are its AUDIO range
        // and the ring's ON / OFF (off at first: the panel's sound as before).
        let lfo = k.iter().find(|k| k.key == "lfo_on").unwrap();
        assert_eq!(lfo.kind, Kind::Toggle);
        assert_eq!(lfo.number(), 1.0);
        for key in ["lfo_audio", "ring_on"] {
            let s = k.iter().find(|k| k.key == key).unwrap();
            assert_eq!(s.kind, Kind::Toggle);
            assert_eq!(s.number(), 0.0);
        }
        // The kick: the keys only gate it, its own oscillator sounds.
        let kick = spec_of("tube_kick");
        let kick_keys: Vec<String> = knobs(&DEVICES[8], &kick)
            .into_iter()
            .map(|k| k.key)
            .collect();
        assert_eq!(
            kick_keys,
            ["tune", "depth", "sweep_time", "tone", "decay", "wave"]
        );
        assert!(kick_keys.iter().any(|k| k == DEVICES[8].mod_wheel.unwrap()));
        assert_eq!(
            key_feeds(&DEVICES[8], &kick),
            Ok(vec![Feed::Gate(-110.0, -1.0)])
        );
        // The gas-tube sawtooth: the keys set its pitch and gate its VCA.
        let saw = spec_of("saw_884");
        let saw_keys: Vec<String> = knobs(&DEVICES[9], &saw)
            .into_iter()
            .map(|k| k.key)
            .collect();
        assert_eq!(saw_keys, ["attack", "release"]);
        let pitch = DEVICES[9].pitch.unwrap();
        assert_eq!(
            key_feeds(&DEVICES[9], &saw),
            Ok(vec![Feed::Pitch(pitch), Feed::Gate(-110.0, -1.0)])
        );
        assert!(DEVICES[9].plays_own_oscillator());
        assert!(DEVICES[8].plays_own_oscillator() && DEVICES[7].plays_own_oscillator());
        assert!(!DEVICES[5].plays_own_oscillator());
        // The Side Man's bass drum: the keys ground its key line, the wheel turns its ring.
        let bd = spec_of("sideman_bd");
        let bd_keys: Vec<String> = knobs(&DEVICES[15], &bd)
            .into_iter()
            .map(|k| k.key)
            .collect();
        assert_eq!(bd_keys, ["ring", "volume"]);
        assert_eq!(DEVICES[15].mod_wheel, Some("ring"));
        assert_eq!(
            key_feeds(&DEVICES[15], &bd),
            Ok(vec![Feed::Gate(-40.0, 0.0)])
        );
        assert!(DEVICES[15].plays_own_oscillator());
        // The range switch: LOW / HIGH / AUTO on the panel, 0 or 1 to the circuit.
        let mut k = k;
        let r = k.iter().position(|k| k.key == "range").unwrap();
        assert!(matches!(&k[r].kind, Kind::Choices(c) if c.len() == 3));
        assert_eq!(range_mode(&k), Some(RangeMode::Auto));
        let at = |k: &[Knob]| {
            values(k)
                .into_iter()
                .find(|(key, _)| key == "range")
                .unwrap()
                .1
        };
        assert_eq!(at(&k), Value::Int(1));
        k[r].value = Value::Str("LOW".into());
        assert_eq!(
            (at(&k), range_mode(&k)),
            (Value::Int(0), Some(RangeMode::Low))
        );
        assert_eq!(
            key_feeds(&DEVICES[7], &synth),
            Ok(vec![
                Feed::VelocityGate(-110.0, TUBE_SYNTH_VELOCITY),
                Feed::Pitch(DEVICES[7].pitch.unwrap()),
                Feed::Key(KeyString {
                    v_per_semitone: 0.75,
                    ref_note: 60.0,
                    min_v: -27.0,
                    max_v: 27.0
                }),
                Feed::Pressure(15.0),
                Feed::Pitch(DEVICES[7].pitch2.unwrap())
            ])
        );
        // Velocity: 127 at the circuit's gate_on_v, softer keys down the table.
        let t = TUBE_SYNTH_VELOCITY;
        assert_eq!(t[t.len() - 1], (0.0, -1.0));
        assert_eq!(velocity_volts(t, 127, 18.0), -1.0);
        assert_eq!(velocity_volts(t, 1, 0.0), -1.0);
        assert!((velocity_volts(t, 1, 18.0) - -55.0).abs() < 2.0);
        assert!(t.windows(2).all(|w| w[0].0 < w[1].0 && w[0].1 < w[1].1));
        let Ok(feeds) = key_feeds(&DEVICES[7], &synth) else {
            unreachable!()
        };
        let Feed::Key(k) = feeds[2] else {
            unreachable!()
        };
        assert_eq!((k.volts(60), k.volts(72), k.volts(59)), (0.0, 9.0, -0.75));
        assert_eq!((k.volts(0), k.volts(127)), (-27.0, 27.0));
        // A device without a feed for a control input can't be played from keys.
        assert!(key_feeds(&DEVICES[4], &voice).is_err());
    }

    #[test]
    fn a_tuning_interpolates_in_octaves_and_holds_at_its_ends() {
        let p = Pitch {
            control: "pitch",
            tuning: &[(100.0, -10.0), (400.0, 0.0)],
            range: None,
        };
        assert_eq!(p.volts(50.0), -10.0);
        assert_eq!(p.volts(1000.0), 0.0);
        assert!((p.volts(200.0) + 5.0).abs() < 1e-12);
        let t = DEVICES[6].pitch.unwrap().tuning;
        assert!(t.windows(2).all(|w| w[1].0 > w[0].0));
        let t = DEVICES[7].pitch.unwrap().tuning;
        assert!(t.windows(2).all(|w| w[1].0 > w[0].0));
        let t = DEVICES[7].pitch.unwrap().range.unwrap().low;
        assert!(t.windows(2).all(|w| w[1].0 > w[0].0));
        let t = DEVICES[7].pitch2.unwrap().tuning;
        assert!(t.windows(2).all(|w| w[1].0 > w[0].0 && w[1].1 > w[0].1));
        let t = DEVICES[9].pitch.unwrap().tuning;
        assert!(t.windows(2).all(|w| w[1].0 > w[0].0 && w[1].1 > w[0].1));
    }

    /// The range switch: AUTO plays keys below the split on LOW and the rest on HIGH
    /// (holding where it was with no key); a key's volts come from its range's table.
    #[test]
    fn the_range_switch_follows_the_keys_in_auto() {
        let p = DEVICES[7].pitch.unwrap();
        let r = p.range.unwrap();
        let below = r.split_hz * 0.9;
        let above = r.split_hz * 1.1;
        assert!(r.low_for(RangeMode::Auto, Some(below), false));
        assert!(!r.low_for(RangeMode::Auto, Some(above), true));
        assert!(r.low_for(RangeMode::Auto, None, true));
        assert!(!r.low_for(RangeMode::Auto, None, false));
        assert!(r.low_for(RangeMode::Low, Some(above), false));
        assert!(!r.low_for(RangeMode::High, Some(below), true));
        // The same key needs a higher control on LOW (the bigger capacitor).
        assert!(p.volts_in(220.0, true) > p.volts_in(220.0, false));
        assert_eq!(p.volts_in(220.0, false), p.volts(220.0));
        let v: Values = vec![
            ("range".into(), Value::Int(1)),
            ("wave".into(), Value::Float(0.5)),
        ];
        let low = r.with_position(&v, true);
        assert!(r.is_low(&low) && !r.is_low(&v));
        assert_eq!(low.len(), 2);
    }
}
