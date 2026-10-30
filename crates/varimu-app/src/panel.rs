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
        s
    }
}

pub const DEVICES: [Device; 6] = [
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
    },
];

/// Controls never on a panel (operating conditions).
const OFF_PANEL: [&str; 2] = ["mains_v_rms", "mains_hz"];

/// Labels for control keys (keys otherwise).
const LABELS: [(&str, &str); 23] = [
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
        let default = e.get("value").cloned().unwrap_or(Value::Null);
        let num = |k: &str| e.get(k).and_then(Value::as_f64);
        let kind = if let Some(c) = e.get("choices").and_then(Value::as_list) {
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

/// The knobs' values as overrides.
pub fn values(knobs: &[Knob]) -> Values {
    knobs
        .iter()
        .map(|k| (k.key.clone(), k.value.clone()))
        .collect()
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
            Ok((-110.0, -2.0))
        );
    }
}
