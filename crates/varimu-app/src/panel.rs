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

pub const DEVICES: [Device; 8] = [
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
        partition: Some(&[
            "input",
            "filter",
            "resonance",
            "cutoff",
            "|",
            "oscillator",
            "pitch",
            "|",
            "power supply",
            "bias supply",
        ]),
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
    (26.25, -24.5),
    (30.65, -24.25),
    (35.59, -24.0),
    (40.38, -23.75),
    (46.2, -23.5),
    (52.0, -23.25),
    (58.25, -23.0),
    (64.76, -22.75),
    (71.88, -22.5),
    (79.57, -22.25),
    (87.86, -22.0),
    (96.83, -21.75),
    (106.42, -21.5),
    (116.66, -21.25),
    (127.19, -21.0),
    (138.25, -20.75),
    (149.64, -20.5),
    (161.31, -20.25),
    (173.27, -20.0),
    (185.49, -19.75),
    (197.99, -19.5),
    (210.77, -19.25),
    (223.83, -19.0),
    (237.2, -18.75),
    (250.86, -18.5),
    (264.84, -18.25),
    (279.14, -18.0),
    (293.76, -17.75),
    (308.72, -17.5),
    (324.02, -17.25),
    (339.64, -17.0),
    (355.6, -16.75),
    (371.9, -16.5),
    (388.52, -16.25),
    (405.48, -16.0),
    (422.77, -15.75),
    (440.37, -15.5),
    (458.3, -15.25),
    (476.53, -15.0),
    (494.97, -14.75),
    (513.38, -14.5),
    (531.88, -14.25),
    (550.51, -14.0),
    (569.3, -13.75),
    (588.26, -13.5),
    (607.38, -13.25),
    (626.67, -13.0),
    (646.12, -12.75),
    (665.74, -12.5),
    (685.51, -12.25),
    (705.44, -12.0),
    (725.52, -11.75),
    (745.75, -11.5),
    (766.11, -11.25),
    (786.61, -11.0),
    (807.25, -10.75),
    (828.0, -10.5),
    (848.87, -10.25),
    (869.85, -10.0),
    (890.94, -9.75),
    (912.12, -9.5),
    (933.4, -9.25),
    (954.76, -9.0),
    (976.2, -8.75),
    (997.72, -8.5),
    (1019.3, -8.25),
    (1040.94, -8.0),
    (1062.64, -7.75),
    (1084.39, -7.5),
    (1106.19, -7.25),
    (1128.02, -7.0),
    (1149.89, -6.75),
    (1171.78, -6.5),
    (1193.7, -6.25),
    (1215.63, -6.0),
    (1237.58, -5.75),
    (1259.54, -5.5),
    (1281.51, -5.25),
    (1303.46, -5.0),
    (1325.41, -4.75),
    (1347.35, -4.5),
    (1369.27, -4.25),
    (1391.19, -4.0),
    (1413.07, -3.75),
    (1434.93, -3.5),
    (1456.74, -3.25),
    (1478.53, -3.0),
    (1500.26, -2.75),
    (1521.98, -2.5),
    (1543.61, -2.25),
    (1565.22, -2.0),
    (1586.76, -1.75),
    (1608.25, -1.5),
    (1629.68, -1.25),
    (1651.07, -1.0),
    (1672.34, -0.75),
    (1693.56, -0.5),
    (1714.73, -0.25),
    (1735.78, 0.0),
];

/// tube_synth's keyboard tuning at LOW (`range` 0, 224 nF): as the HIGH table with
/// `--set range=0 --floor -24.75 --suffix _low` (synth_tuning_low.json): 18.8 Hz to 789 Hz;
/// a gentler law, so less of the supply's ripple FM in cents (9 cents cycle to cycle at
/// 110 Hz against ~30 at HIGH).
const TUBE_SYNTH_TUNING_LOW: &[(f64, f64)] = &[
    (18.84, -24.75),
    (21.44, -24.5),
    (24.09, -24.25),
    (26.96, -24.0),
    (30.05, -23.75),
    (33.01, -23.5),
    (36.18, -23.25),
    (39.45, -23.0),
    (42.8, -22.75),
    (46.27, -22.5),
    (49.87, -22.25),
    (53.6, -22.0),
    (57.47, -21.75),
    (61.4, -21.5),
    (65.57, -21.25),
    (69.88, -21.0),
    (74.36, -20.75),
    (79.0, -20.5),
    (83.83, -20.25),
    (88.84, -20.0),
    (94.05, -19.75),
    (99.46, -19.5),
    (105.08, -19.25),
    (110.91, -19.0),
    (116.97, -18.75),
    (123.21, -18.5),
    (129.71, -18.25),
    (136.43, -18.0),
    (143.38, -17.75),
    (150.56, -17.5),
    (157.97, -17.25),
    (165.6, -17.0),
    (173.46, -16.75),
    (181.53, -16.5),
    (189.83, -16.25),
    (198.34, -16.0),
    (207.04, -15.75),
    (215.96, -15.5),
    (225.04, -15.25),
    (234.31, -15.0),
    (243.71, -14.75),
    (253.07, -14.5),
    (262.49, -14.25),
    (271.96, -14.0),
    (281.5, -13.75),
    (291.11, -13.5),
    (300.77, -13.25),
    (310.49, -13.0),
    (320.25, -12.75),
    (330.06, -12.5),
    (339.91, -12.25),
    (349.79, -12.0),
    (359.7, -11.75),
    (369.63, -11.5),
    (379.58, -11.25),
    (389.54, -11.0),
    (399.51, -10.75),
    (409.49, -10.5),
    (419.47, -10.25),
    (429.45, -10.0),
    (439.41, -9.75),
    (449.37, -9.5),
    (459.31, -9.25),
    (469.25, -9.0),
    (479.15, -8.75),
    (489.04, -8.5),
    (498.9, -8.25),
    (508.73, -8.0),
    (518.53, -7.75),
    (528.3, -7.5),
    (538.03, -7.25),
    (547.71, -7.0),
    (557.35, -6.75),
    (566.94, -6.5),
    (576.47, -6.25),
    (585.95, -6.0),
    (595.36, -5.75),
    (604.72, -5.5),
    (614.01, -5.25),
    (623.23, -5.0),
    (632.38, -4.75),
    (641.46, -4.5),
    (650.45, -4.25),
    (659.37, -4.0),
    (668.2, -3.75),
    (676.95, -3.5),
    (685.6, -3.25),
    (694.17, -3.0),
    (702.64, -2.75),
    (711.02, -2.5),
    (719.29, -2.25),
    (727.46, -2.0),
    (735.53, -1.75),
    (743.49, -1.5),
    (751.34, -1.25),
    (759.08, -1.0),
    (766.71, -0.75),
    (774.22, -0.5),
    (781.61, -0.25),
    (788.88, 0.0),
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
            ["cutoff", "resonance", "attack", "release", "wave", "range"]
        );
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
