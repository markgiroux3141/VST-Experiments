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
    /// The circuit's control input a keyboard's keys set the pitch on, for a device with
    /// an oscillator of its own (its audio input then stays silent; None: none).
    pub pitch: Option<Pitch>,
    /// Its circuit makes its own sound without a pitch input (a drum's oscillator): the
    /// keys only gate it, its audio input stays silent (as with a `pitch` input).
    pub own_oscillator: bool,
    /// The sections its draft puts on the second thread, over its quality's
    /// `partition` (None: the quality's).
    pub partition: Option<&'static [&'static str]>,
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

/// What feeds one of a circuit's control inputs while a keyboard plays it.
#[derive(Debug, Clone, Copy, PartialEq)]
pub enum Feed {
    /// The keys' gate: (key up, key down) volts.
    Gate(f64, f64),
    /// The last key's pitch.
    Pitch(Pitch),
}

/// The feeds of `spec`'s control inputs in its order, for `device` played from keys
/// (every control input needs one: the device's gate or pitch).
pub fn key_feeds(device: &Device, spec: &CircuitSpec) -> Result<Vec<Feed>, String> {
    spec.cv_inputs
        .iter()
        .map(|(name, _)| {
            if device.gate == Some(name.as_str()) {
                let (up, down) = gate_levels(spec, name)?;
                Ok(Feed::Gate(up, down))
            } else if let Some(p) = device.pitch.filter(|p| p.control == name) {
                Ok(Feed::Pitch(p))
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
        s
    }
}

pub const DEVICES: [Device; 9] = [
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
        pitch: None,
        own_oscillator: false,
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
        pitch: None,
        own_oscillator: false,
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
        pitch: None,
        own_oscillator: false,
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
        pitch: None,
        own_oscillator: false,
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
        pitch: None,
        own_oscillator: false,
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
        pitch: None,
        own_oscillator: false,
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
        pitch: Some(Pitch {
            control: "pitch",
            tuning: VCO_LC_TUNING,
            range: None,
        }),
        own_oscillator: false,
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
        // and 0.01 dB of the one solve.
        own_oscillator: false,
        partition: Some(&[
            "resonance",
            "|",
            "input",
            "filter",
            "cutoff",
            "envelope",
            "|",
            "oscillator",
            "pitch",
            "|",
            "power supply",
            "bias supply",
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
        pitch: None,
        own_oscillator: true,
        // Three threads: the trigger, the envelopes and the VCA (with the keys) | the
        // oscillator and its pitch driver | the supplies.
        partition: Some(&["oscillator", "pitch", "|", "power supply", "bias supply"]),
    },
];

/// Where AUTO changes range: keys below it play on LOW (`range` 0, the tank's 224 nF),
/// the rest on HIGH. At 330 Hz (E4) the two sound most alike (measured at draft, the same
/// pitch on each: LOW 1.4 dB louder, the harmonics within 2 dB; at 440-660 Hz LOW has 7-9 dB
/// more 2nd harmonic); crossing it adds no pop or glide beyond the supply ripple's FM (the
/// key waits a block or two for the switch). LOW's pitch is steadier up to its top (17
/// against 27 cents cycle to cycle at 330 Hz), so the split trades that for the tone.
const TUBE_SYNTH_SPLIT_HZ: f64 = 330.0;

/// tube_synth's keyboard tuning at HIGH (`range` 1, the tank's 56 nF): `scripts/vco_study.py
/// --only synth --tuning draft --step 0.25 --set range=1 --floor -24.5 --suffix _high`
/// (reports/tube_synth/vco/synth_tuning_high.json, 2026-10-30): 26 Hz to 1.74 kHz. Below
/// -24.5 V a plateau (17-19 Hz down to -26.5 V: the cores saturated, another regime).
const TUBE_SYNTH_TUNING: &[(f64, f64)] = &[
    (26.05, -24.5),
    (30.38, -24.25),
    (35.32, -24.0),
    (40.18, -23.75),
    (45.92, -23.5),
    (51.67, -23.25),
    (57.87, -23.0),
    (64.37, -22.75),
    (71.47, -22.5),
    (79.18, -22.25),
    (87.36, -22.0),
    (96.27, -21.75),
    (105.82, -21.5),
    (115.98, -21.25),
    (126.49, -21.0),
    (137.55, -20.75),
    (148.93, -20.5),
    (160.61, -20.25),
    (172.55, -20.0),
    (184.76, -19.75),
    (197.25, -19.5),
    (210.03, -19.25),
    (223.08, -19.0),
    (236.43, -18.75),
    (250.09, -18.5),
    (264.05, -18.25),
    (278.33, -18.0),
    (292.96, -17.75),
    (307.9, -17.5),
    (323.17, -17.25),
    (338.79, -17.0),
    (354.74, -16.75),
    (371.02, -16.5),
    (387.63, -16.25),
    (404.57, -16.0),
    (421.85, -15.75),
    (439.44, -15.5),
    (457.35, -15.25),
    (475.57, -15.0),
    (494.01, -14.75),
    (512.41, -14.5),
    (530.91, -14.25),
    (549.53, -14.0),
    (568.32, -13.75),
    (587.26, -13.5),
    (606.38, -13.25),
    (625.66, -13.0),
    (645.1, -12.75),
    (664.72, -12.5),
    (684.48, -12.25),
    (704.41, -12.0),
    (724.48, -11.75),
    (744.7, -11.5),
    (765.07, -11.25),
    (785.56, -11.0),
    (806.19, -10.75),
    (826.94, -10.5),
    (847.8, -10.25),
    (868.78, -10.0),
    (889.86, -9.75),
    (911.04, -9.5),
    (932.32, -9.25),
    (953.68, -9.0),
    (975.12, -8.75),
    (996.62, -8.5),
    (1018.2, -8.25),
    (1039.85, -8.0),
    (1061.54, -7.75),
    (1083.29, -7.5),
    (1105.09, -7.25),
    (1126.91, -7.0),
    (1148.78, -6.75),
    (1170.68, -6.5),
    (1192.59, -6.25),
    (1214.53, -6.0),
    (1236.48, -5.75),
    (1258.43, -5.5),
    (1280.4, -5.25),
    (1302.35, -5.0),
    (1324.31, -4.75),
    (1346.25, -4.5),
    (1368.16, -4.25),
    (1390.08, -4.0),
    (1411.96, -3.75),
    (1433.81, -3.5),
    (1455.63, -3.25),
    (1477.42, -3.0),
    (1499.15, -2.75),
    (1520.85, -2.5),
    (1542.52, -2.25),
    (1564.11, -2.0),
    (1585.66, -1.75),
    (1607.14, -1.5),
    (1628.58, -1.25),
    (1649.93, -1.0),
    (1671.23, -0.75),
    (1692.46, -0.5),
    (1713.59, -0.25),
    (1734.68, 0.0),
];

/// tube_synth's keyboard tuning at LOW (`range` 0, 224 nF): as the HIGH table with
/// `--set range=0 --floor -24.75 --suffix _low` (synth_tuning_low.json): 18.8 Hz to 789 Hz;
/// a gentler law, so less of the supply's ripple FM in cents (9 cents cycle to cycle at
/// 110 Hz against ~30 at HIGH).
const TUBE_SYNTH_TUNING_LOW: &[(f64, f64)] = &[
    (18.67, -24.75),
    (21.26, -24.5),
    (24.08, -24.25),
    (26.77, -24.0),
    (29.78, -23.75),
    (32.81, -23.5),
    (35.98, -23.25),
    (39.29, -23.0),
    (42.57, -22.75),
    (46.06, -22.5),
    (49.65, -22.25),
    (53.37, -22.0),
    (57.23, -21.75),
    (61.11, -21.5),
    (65.32, -21.25),
    (69.62, -21.0),
    (74.09, -20.75),
    (78.73, -20.5),
    (83.54, -20.25),
    (88.55, -20.0),
    (93.75, -19.75),
    (99.15, -19.5),
    (104.76, -19.25),
    (110.58, -19.0),
    (116.63, -18.75),
    (122.85, -18.5),
    (129.36, -18.25),
    (136.06, -18.0),
    (143.0, -17.75),
    (150.17, -17.5),
    (157.56, -17.25),
    (165.18, -17.0),
    (173.04, -16.75),
    (181.1, -16.5),
    (189.39, -16.25),
    (197.89, -16.0),
    (206.58, -15.75),
    (215.48, -15.5),
    (224.57, -15.25),
    (233.83, -15.0),
    (243.22, -14.75),
    (252.58, -14.5),
    (261.99, -14.25),
    (271.46, -14.0),
    (281.0, -13.75),
    (290.6, -13.5),
    (300.25, -13.25),
    (309.97, -13.0),
    (319.73, -12.75),
    (329.54, -12.5),
    (339.38, -12.25),
    (349.26, -12.0),
    (359.17, -11.75),
    (369.1, -11.5),
    (379.05, -11.25),
    (389.01, -11.0),
    (398.98, -10.75),
    (408.95, -10.5),
    (418.93, -10.25),
    (428.9, -10.0),
    (438.87, -9.75),
    (448.83, -9.5),
    (458.77, -9.25),
    (468.69, -9.0),
    (478.6, -8.75),
    (488.48, -8.5),
    (498.34, -8.25),
    (508.18, -8.0),
    (517.97, -7.75),
    (527.73, -7.5),
    (537.46, -7.25),
    (547.14, -7.0),
    (556.77, -6.75),
    (566.35, -6.5),
    (575.89, -6.25),
    (585.36, -6.0),
    (594.78, -5.75),
    (604.13, -5.5),
    (613.41, -5.25),
    (622.63, -5.0),
    (631.77, -4.75),
    (640.84, -4.5),
    (649.83, -4.25),
    (658.74, -4.0),
    (667.58, -3.75),
    (676.32, -3.5),
    (684.98, -3.25),
    (693.53, -3.0),
    (702.0, -2.75),
    (710.37, -2.5),
    (718.64, -2.25),
    (726.81, -2.0),
    (734.87, -1.75),
    (742.83, -1.5),
    (750.68, -1.25),
    (758.41, -1.0),
    (766.04, -0.75),
    (773.54, -0.5),
    (780.93, -0.25),
    (788.2, 0.0),
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

/// Controls never on a panel (operating conditions).
const OFF_PANEL: [&str; 2] = ["mains_v_rms", "mains_hz"];

/// Labels for control keys (keys otherwise).
const LABELS: [(&str, &str); 25] = [
    ("range", "Range (AUTO: by key)"),
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
    ("release", "Release"),
    ("wave", "Wave (tank to square)"),
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
}

/// One knob: its control key, label, kind and value.
#[derive(Debug, Clone, PartialEq)]
pub struct Knob {
    pub key: String,
    pub label: String,
    pub kind: Kind,
    pub default: Value,
    pub value: Value,
}

impl Knob {
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
        } else if let Some(c) = e.get("choices").and_then(Value::as_list) {
            Kind::Choices(c.to_vec())
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
                "release",
                "env_amount",
                "wave",
                "range"
            ]
        );
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
        assert!(DEVICES[8].plays_own_oscillator() && DEVICES[7].plays_own_oscillator());
        assert!(!DEVICES[5].plays_own_oscillator());
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
                Feed::Gate(-110.0, -1.0),
                Feed::Pitch(DEVICES[7].pitch.unwrap())
            ])
        );
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
