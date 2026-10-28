//! The app's own settings, per user and outside the repo (`%APPDATA%\varimu\app.json`
//! on Windows, `$XDG_CONFIG_HOME/varimu` or `~/.config/varimu` elsewhere): folders of
//! audio files to list as sources. Those can hold material that must never be
//! committed (multitracks for educational use), so they stay out of the repo.

use std::path::PathBuf;

use serde_json::{Value, json};

#[derive(Debug, Clone, PartialEq)]
pub struct Prefs {
    /// Folders scanned (with their subfolders) for audio files.
    pub source_folders: Vec<PathBuf>,
    /// Bring each file's loudest 8 s to this level (dBFS, sine-equivalent rms); None:
    /// play files as recorded.
    pub normalize_dbfs: Option<f64>,
}

/// The studio alignment the 670's factory adjustment assumes: -18 dBFS = +4 dBu
/// (`sim_settings.yaml`, audio.full_scale_volts_peak).
pub const ALIGNMENT_DBFS: f64 = -18.0;

impl Default for Prefs {
    fn default() -> Prefs {
        Prefs {
            source_folders: Vec::new(),
            normalize_dbfs: Some(ALIGNMENT_DBFS),
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
        let v: Value = serde_json::from_str(&text).unwrap_or(Value::Null);
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
        Prefs {
            source_folders,
            normalize_dbfs,
        }
    }

    pub fn save(&self) -> Result<(), String> {
        let p = path().ok_or("no user settings directory")?;
        if let Some(dir) = p.parent() {
            std::fs::create_dir_all(dir).map_err(|e| e.to_string())?;
        }
        let folders: Vec<String> = self
            .source_folders
            .iter()
            .map(|f| f.display().to_string())
            .collect();
        let text = serde_json::to_string_pretty(&json!({
            "source_folders": folders,
            "normalize_dbfs": self.normalize_dbfs,
        }))
        .map_err(|e| e.to_string())?;
        std::fs::write(&p, text + "\n").map_err(|e| format!("{}: {e}", p.display()))
    }
}
