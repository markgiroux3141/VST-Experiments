//! The app's own settings, per user and outside the repo (`%APPDATA%\varimu\app.json`
//! on Windows, `$XDG_CONFIG_HOME/varimu` or `~/.config/varimu` elsewhere): folders of
//! audio files to list as sources. Those can hold material that must never be
//! committed (multitracks for educational use), so they stay out of the repo. Also each
//! MIDI keyboard's touch (`midi::Touch`: the controller's, kept by its port's name).

use std::collections::{BTreeMap, BTreeSet};
use std::path::PathBuf;

use serde_json::{Value, json};

#[derive(Debug, Clone, PartialEq)]
pub struct Prefs {
    /// Folders scanned (with their subfolders) for audio files.
    pub source_folders: Vec<PathBuf>,
    /// Bring each file's loudest 8 s to this level (dBFS, sine-equivalent rms); None:
    /// play files as recorded.
    pub normalize_dbfs: Option<f64>,
    /// Each MIDI keyboard's touch by its port's name: the curve (0-1) and the range (dB;
    /// None: the device's own).
    pub touch: BTreeMap<String, KeyTouch>,
    /// The devices played with their precise Newton tolerance instead of their fast one
    /// (`panel::LIVE_NUMERICS`, Play's "Precise solver").
    pub precise_solver: BTreeSet<String>,
}

/// A keyboard's saved touch (the device's own law is the device's: `midi::Touch::native_db`).
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct KeyTouch {
    pub curve: f64,
    pub range_db: Option<f64>,
}

impl Default for KeyTouch {
    fn default() -> KeyTouch {
        KeyTouch {
            curve: 0.0,
            range_db: None,
        }
    }
}

/// The studio alignment the 670's factory adjustment assumes: -18 dBFS = +4 dBu
/// (`sim_settings.yaml`, audio.full_scale_volts_peak); a circuit with its own `full_scale`
/// (the 5E3: a pickup's volts) needs its own target.
pub const ALIGNMENT_DBFS: f64 = -18.0;

impl Default for Prefs {
    fn default() -> Prefs {
        Prefs {
            source_folders: Vec::new(),
            normalize_dbfs: Some(ALIGNMENT_DBFS),
            touch: BTreeMap::new(),
            precise_solver: BTreeSet::new(),
        }
    }
}

/// Where the settings file lives (None: no user directory known).
pub fn path() -> Option<PathBuf> {
    let base = std::env::var_os("APPDATA")
        .map(PathBuf::from)
        .or_else(|| std::env::var_os("XDG_CONFIG_HOME").map(PathBuf::from))
        .or_else(|| std::env::var_os("HOME").map(|h| PathBuf::from(h).join(".config")))?;
    Some(base.join("varimu").join("app.json"))
}

impl Prefs {
    /// The saved settings (defaults if there are none or the file can't be read).
    pub fn load() -> Prefs {
        let Some(text) = path().and_then(|p| std::fs::read_to_string(p).ok()) else {
            return Prefs::default();
        };
        Prefs::from_json(&serde_json::from_str(&text).unwrap_or(Value::Null))
    }

    /// The settings in `v` (an `app.json`'s), defaults where it has none.
    pub fn from_json(v: &Value) -> Prefs {
        let source_folders = v["source_folders"]
            .as_array()
            .map(|a| {
                a.iter()
                    .filter_map(Value::as_str)
                    .map(PathBuf::from)
                    .collect()
            })
            .unwrap_or_default();
        let normalize_dbfs = match v.get("normalize_dbfs") {
            None => Some(ALIGNMENT_DBFS),
            Some(x) => x.as_f64(),
        };
        let touch = v["touch"]
            .as_object()
            .map(|m| {
                m.iter()
                    .map(|(port, t)| {
                        // (A first version's `full_at` isn't read: back to the line.)
                        let curve = t["curve"].as_f64().unwrap_or(0.0).clamp(0.0, 1.0);
                        let range_db = t["range_db"].as_f64();
                        (port.clone(), KeyTouch { curve, range_db })
                    })
                    .collect()
            })
            .unwrap_or_default();
        let precise_solver = v["precise_solver"]
            .as_array()
            .map(|a| {
                a.iter()
                    .filter_map(Value::as_str)
                    .map(String::from)
                    .collect()
            })
            .unwrap_or_default();
        Prefs {
            source_folders,
            normalize_dbfs,
            touch,
            precise_solver,
        }
    }

    /// These settings, with their devices' precise solvers set for every view
    /// (`panel::set_precise`: `Device::play_settings` reads them).
    pub fn with_solvers_set(self) -> Prefs {
        for id in &self.precise_solver {
            crate::panel::set_precise(id, true);
        }
        self
    }

    pub fn save(&self) -> Result<(), String> {
        let p = path().ok_or("no user settings directory")?;
        if let Some(dir) = p.parent() {
            std::fs::create_dir_all(dir).map_err(|e| e.to_string())?;
        }
        let text = serde_json::to_string_pretty(&self.to_json()).map_err(|e| e.to_string())?;
        std::fs::write(&p, text + "\n").map_err(|e| format!("{}: {e}", p.display()))
    }

    pub fn to_json(&self) -> Value {
        let folders: Vec<String> = self
            .source_folders
            .iter()
            .map(|f| f.display().to_string())
            .collect();
        let touch: serde_json::Map<String, Value> = self
            .touch
            .iter()
            .map(|(port, t)| {
                let v = json!({"curve": t.curve, "range_db": t.range_db});
                (port.clone(), v)
            })
            .collect();
        json!({
            "source_folders": folders,
            "normalize_dbfs": self.normalize_dbfs,
            "touch": touch,
            "precise_solver": self.precise_solver,
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_keyboard_s_touch_survives_the_settings_file() {
        let mut p = Prefs::default();
        p.touch.insert(
            "MasterKey 49".into(),
            KeyTouch {
                curve: 0.35,
                range_db: Some(18.0),
            },
        );
        p.touch.insert("Other".into(), KeyTouch::default());
        p.precise_solver.insert("minimoog_voice".into());
        let text = serde_json::to_string(&p.to_json()).unwrap();
        assert_eq!(Prefs::from_json(&serde_json::from_str(&text).unwrap()), p);
        // A settings file from before the touch: none saved, the rest as it was.
        let old = json!({"source_folders": ["D:/music"], "normalize_dbfs": null});
        let back = Prefs::from_json(&old);
        assert!(back.touch.is_empty() && back.precise_solver.is_empty());
        assert_eq!(back.source_folders, vec![PathBuf::from("D:/music")]);
        assert_eq!(back.normalize_dbfs, None);
    }
}
