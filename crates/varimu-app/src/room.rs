//! The Room view's model (docs/ROOM_LOOP_PLAN.md): a scene of a shoebox room, sources
//! (session tracks) placed in it, mics placed and aimed, each through a chain (a mic +
//! preamp circuit), and its render into new session tracks.
//!
//! The render is Python's reference pipeline for now (`scripts/room_print.py`,
//! `varimu/rooms/`: the entry tables' BEM, the image sources with directions, the shared
//! diffuse field, the chains printed at production), run as a background process: the
//! scene is written as JSON (the format of `varimu/rooms/scene.py`'s docstring), each source
//! track's active take as a WAV beside it, and the process reports `progress F` lines.
//! Porting the room to Rust (the chains already render in `render`) is the plan's later
//! step.

use std::collections::BTreeMap;
use std::io::{BufRead, BufReader};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Arc, Mutex};

use serde_json::{Value, json};

/// A setting of a chain: its key in the chain's circuit file and its positions.
pub struct Setting {
    pub key: &'static str,
    pub label: &'static str,
    pub choices: &'static [(f64, &'static str)],
    pub default: f64,
}

/// A mic + preamp chain (a composed circuit file with a capsule).
pub struct Chain {
    pub id: &'static str,
    pub label: &'static str,
    pub settings: &'static [Setting],
}

const V76_GAINS: &[(f64, &str)] = &[
    (3.0, "3 dB"),
    (9.0, "9 dB"),
    (18.0, "18 dB"),
    (24.0, "24 dB"),
    (34.0, "34 dB"),
    (40.0, "40 dB"),
    (46.0, "46 dB"),
    (52.0, "52 dB"),
    (58.0, "58 dB"),
    (64.0, "64 dB"),
    (70.0, "70 dB"),
    (76.0, "76 dB"),
];
const CLEAN_GAINS: &[(f64, &str)] = &[
    (20.0, "20 dB"),
    (30.0, "30 dB"),
    (40.0, "40 dB"),
    (50.0, "50 dB"),
    (60.0, "60 dB"),
];

/// The chains a mic can be (config/circuits/u47_v76.yaml, omni_clean.yaml).
pub const CHAINS: &[Chain] = &[
    Chain {
        id: "u47_v76",
        label: "U47 → V76",
        settings: &[
            Setting {
                key: "pattern_u47",
                label: "Pattern",
                choices: &[(0.0, "cardioid"), (1.0, "omni")],
                default: 0.0,
            },
            Setting {
                key: "gain_db_v76",
                label: "V76 gain",
                choices: V76_GAINS,
                default: 34.0,
            },
        ],
    },
    Chain {
        id: "omni_clean",
        label: "Omni (4134) → clean",
        settings: &[Setting {
            key: "gain_db_clean",
            label: "Gain",
            choices: CLEAN_GAINS,
            default: 40.0,
        }],
    },
];

pub fn chain(id: &str) -> Option<&'static Chain> {
    CHAINS.iter().find(|c| c.id == id)
}

/// The surface materials (varimu/separation/room.py MATERIALS, and `anechoic`).
pub const MATERIALS: &[&str] = &[
    "furnished_wall",
    "gypsum_on_studs",
    "plaster",
    "wood_floor",
    "carpet_on_pad",
    "heavy_drapes",
    "acoustic_tile",
    "anechoic",
];

/// The qualities a scene renders at.
pub const QUALITIES: &[&str] = &["production", "draft"];

/// A mic's polar pattern, for drawing (the physics is the capsule's).
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum Pattern {
    Cardioid,
    Omni,
}

/// Nearest a mic may be to a source (the entry tables' nearest distance).
pub const MIN_DISTANCE_M: f64 = 0.1;

#[derive(Clone, PartialEq, Debug)]
pub struct RoomSource {
    pub name: String,
    /// The session track whose active take plays here.
    pub track: String,
    /// Its rms in dB SPL 1 m away in free field.
    pub spl_db: f64,
    pub pos: [f64; 3],
}

#[derive(Clone, PartialEq, Debug)]
pub struct RoomMic {
    pub name: String,
    pub chain: String,
    pub set: BTreeMap<String, f64>,
    pub pos: [f64; 3],
    /// Counterclockwise from +x in the floor plan.
    pub azimuth_deg: f64,
    pub elevation_deg: f64,
    pub pan: f64,
}

impl RoomMic {
    pub fn new(name: &str, chain_id: &str, pos: [f64; 3], azimuth_deg: f64) -> RoomMic {
        let set = chain(chain_id)
            .map(|c| {
                c.settings
                    .iter()
                    .map(|s| (s.key.to_string(), s.default))
                    .collect()
            })
            .unwrap_or_default();
        RoomMic {
            name: name.to_string(),
            chain: chain_id.to_string(),
            set,
            pos,
            azimuth_deg,
            elevation_deg: 0.0,
            pan: 0.0,
        }
    }

    pub fn pattern(&self) -> Pattern {
        match self.chain.as_str() {
            "u47_v76" if self.set.get("pattern_u47").copied().unwrap_or(0.0) == 0.0 => {
                Pattern::Cardioid
            }
            _ => Pattern::Omni,
        }
    }

    /// Point the mic at a floor-plan position.
    pub fn aim_at(&mut self, x: f64, y: f64) {
        let (dx, dy) = (x - self.pos[0], y - self.pos[1]);
        if dx.hypot(dy) > 1e-9 {
            self.azimuth_deg = dy.atan2(dx).to_degrees();
        }
    }
}

#[derive(Clone, PartialEq, Debug)]
pub struct Scene {
    pub name: String,
    pub dims: [f64; 3],
    pub walls: String,
    pub floor: String,
    pub ceiling: String,
    pub sources: Vec<RoomSource>,
    pub mics: Vec<RoomMic>,
    pub quality: String,
}

impl Default for Scene {
    fn default() -> Scene {
        Scene {
            name: "Room".to_string(),
            dims: [7.0, 5.5, 3.2],
            walls: "furnished_wall".to_string(),
            floor: "wood_floor".to_string(),
            ceiling: "gypsum_on_studs".to_string(),
            sources: Vec::new(),
            mics: Vec::new(),
            quality: "production".to_string(),
        }
    }
}

fn f(v: &Value, k: &str, d: f64) -> f64 {
    v.get(k).and_then(Value::as_f64).unwrap_or(d)
}

fn s3(v: &Value) -> [f64; 3] {
    let a = v.as_array().cloned().unwrap_or_default();
    let g = |i: usize| a.get(i).and_then(Value::as_f64).unwrap_or(1.0);
    [g(0), g(1), g(2)]
}

fn st(v: &Value, k: &str, d: &str) -> String {
    v.get(k).and_then(Value::as_str).unwrap_or(d).to_string()
}

impl Scene {
    /// The editor's state (what `<session>/rooms/<name>.json` holds: sources by track id).
    pub fn state(&self) -> Value {
        json!({
            "name": self.name,
            "dims_m": self.dims,
            "walls": self.walls, "floor": self.floor, "ceiling": self.ceiling,
            "quality": self.quality,
            "sources": self.sources.iter().map(|s| json!({
                "name": s.name, "track": s.track, "spl_db": s.spl_db, "position_m": s.pos,
            })).collect::<Vec<_>>(),
            "mics": self.mics.iter().map(|m| json!({
                "name": m.name, "chain": m.chain, "set": m.set, "position_m": m.pos,
                "azimuth_deg": m.azimuth_deg, "elevation_deg": m.elevation_deg, "pan": m.pan,
            })).collect::<Vec<_>>(),
        })
    }

    pub fn from_state(v: &Value) -> Scene {
        let d = Scene::default();
        Scene {
            name: st(v, "name", &d.name),
            dims: v.get("dims_m").map_or(d.dims, s3),
            walls: st(v, "walls", &d.walls),
            floor: st(v, "floor", &d.floor),
            ceiling: st(v, "ceiling", &d.ceiling),
            quality: st(v, "quality", &d.quality),
            sources: v["sources"]
                .as_array()
                .map(|a| {
                    a.iter()
                        .map(|s| RoomSource {
                            name: st(s, "name", "source"),
                            track: st(s, "track", ""),
                            spl_db: f(s, "spl_db", 90.0),
                            pos: s3(&s["position_m"]),
                        })
                        .collect()
                })
                .unwrap_or_default(),
            mics: v["mics"]
                .as_array()
                .map(|a| {
                    a.iter()
                        .map(|m| RoomMic {
                            name: st(m, "name", "mic"),
                            chain: st(m, "chain", "u47_v76"),
                            set: m["set"]
                                .as_object()
                                .map(|o| {
                                    o.iter()
                                        .filter_map(|(k, x)| Some((k.clone(), x.as_f64()?)))
                                        .collect()
                                })
                                .unwrap_or_default(),
                            pos: s3(&m["position_m"]),
                            azimuth_deg: f(m, "azimuth_deg", 0.0),
                            elevation_deg: f(m, "elevation_deg", 0.0),
                            pan: f(m, "pan", 0.0),
                        })
                        .collect()
                })
                .unwrap_or_default(),
        }
    }

    /// The scene in varimu/rooms/scene.py's format, each source's clip from `clips`.
    pub fn render_json(&self, clips: &BTreeMap<String, PathBuf>) -> Value {
        json!({
            "name": self.name,
            "room": {
                "dims_m": self.dims,
                "materials": {"walls": self.walls, "floor": self.floor, "ceiling": self.ceiling},
                "source": "the Room view (docs/ROOM_LOOP_PLAN.md)",
            },
            "sources": self.sources.iter().map(|s| json!({
                "name": s.name,
                "clip": clips.get(&s.name).map(|p| p.to_string_lossy().to_string()),
                "spl_db": s.spl_db,
                "position_m": s.pos,
            })).collect::<Vec<_>>(),
            "mics": self.mics.iter().map(|m| json!({
                "name": m.name, "chain": m.chain, "set": m.set, "position_m": m.pos,
                "aim": {"azimuth_deg": m.azimuth_deg, "elevation_deg": m.elevation_deg},
                "pan": m.pan,
            })).collect::<Vec<_>>(),
            "settings": {"quality": self.quality, "seed": 0},
        })
    }

    /// What stops a render: the problems, in words.
    pub fn problems(&self) -> Vec<String> {
        let mut out = Vec::new();
        if self.sources.is_empty() {
            out.push("place a source".to_string());
        }
        if self.mics.is_empty() {
            out.push("place a mic".to_string());
        }
        if self.dims.iter().any(|&d| d < 1.0) {
            out.push("the room needs at least 1 m each way".to_string());
        }
        let inside = |p: &[f64; 3]| p.iter().zip(self.dims).all(|(&x, d)| x > 0.0 && x < d);
        let mut names = std::collections::HashSet::new();
        for s in &self.sources {
            if !inside(&s.pos) {
                out.push(format!("{} is outside the room", s.name));
            }
            if s.track.is_empty() {
                out.push(format!("{} has no track", s.name));
            }
            if !names.insert(s.name.clone()) {
                out.push(format!("two items are called {}", s.name));
            }
        }
        for m in &self.mics {
            if !inside(&m.pos) {
                out.push(format!("{} is outside the room", m.name));
            }
            if !names.insert(m.name.clone()) {
                out.push(format!("two items are called {}", m.name));
            }
            if chain(&m.chain).is_none() {
                out.push(format!("{}: unknown chain {}", m.name, m.chain));
            }
            for s in &self.sources {
                let d: f64 = (0..3)
                    .map(|i| (m.pos[i] - s.pos[i]).powi(2))
                    .sum::<f64>()
                    .sqrt();
                if d < MIN_DISTANCE_M {
                    out.push(format!("{} is closer than 10 cm to {}", m.name, s.name));
                }
            }
        }
        out
    }

    /// The next free name with this prefix ("A", "B", ... or "Mic 1", "Mic 2", ...).
    pub fn free_name(&self, prefix: &str) -> String {
        let taken = |n: &str| {
            self.sources.iter().any(|s| s.name == n) || self.mics.iter().any(|m| m.name == n)
        };
        (1..)
            .map(|i| format!("{prefix} {i}"))
            .find(|n| !taken(n))
            .unwrap()
    }
}

/// A mic's print, as the render left it.
#[derive(Clone, Debug)]
pub struct MicPrint {
    pub name: String,
    pub pan: f64,
    pub file: PathBuf,
    pub rms_dbfs: f64,
}

/// A render's result (its render.json).
#[derive(Clone, Debug)]
pub struct Rendered {
    pub mics: Vec<MicPrint>,
    pub json: Value,
}

pub fn read_render(dir: &Path) -> Result<Rendered, String> {
    let text = std::fs::read_to_string(dir.join("render.json"))
        .map_err(|e| format!("{}: {e}", dir.join("render.json").display()))?;
    let v: Value = serde_json::from_str(&text).map_err(|e| e.to_string())?;
    let mics = v["mics"]
        .as_array()
        .ok_or("render.json has no mics")?
        .iter()
        .map(|m| MicPrint {
            name: st(m, "name", "mic"),
            pan: f(m, "pan", 0.0),
            file: dir.join(st(m, "file", "")),
            rms_dbfs: f(m, "rms_dbfs", f64::NAN),
        })
        .collect();
    Ok(Rendered { mics, json: v })
}

/// The render as a background process (the module docstring).
pub struct RenderJob {
    child: Mutex<Child>,
    progress: Arc<AtomicU64>,
    log: Arc<Mutex<Vec<String>>>,
    pub out_dir: PathBuf,
    readers: Vec<std::thread::JoinHandle<()>>,
}

impl RenderJob {
    /// `uv run --extra fast python scripts/room_print.py SCENE --out OUT` in `repo`.
    pub fn spawn(repo: &Path, scene: &Path, out_dir: &Path) -> Result<RenderJob, String> {
        let mut cmd = Command::new("uv");
        cmd.current_dir(repo)
            .args(["run", "--extra", "fast", "python", "scripts/room_print.py"])
            .arg(scene)
            .arg("--out")
            .arg(out_dir)
            .env("PYTHONUNBUFFERED", "1")
            .stdin(Stdio::null())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped());
        #[cfg(windows)]
        {
            use std::os::windows::process::CommandExt;
            cmd.creation_flags(0x0800_0000); // CREATE_NO_WINDOW
        }
        let mut child = cmd
            .spawn()
            .map_err(|e| format!("couldn't start uv (is it on PATH?): {e}"))?;
        let progress = Arc::new(AtomicU64::new(0f64.to_bits()));
        let log = Arc::new(Mutex::new(Vec::new()));
        let mut readers = Vec::new();
        let out = child.stdout.take().unwrap();
        let err = child.stderr.take().unwrap();
        for (stream, is_out) in [
            (Box::new(out) as Box<dyn std::io::Read + Send>, true),
            (Box::new(err), false),
        ] {
            let (p, l) = (progress.clone(), log.clone());
            readers.push(std::thread::spawn(move || {
                for line in BufReader::new(stream).lines().map_while(Result::ok) {
                    if is_out && let Some(x) = line.strip_prefix("progress ") {
                        if let Ok(v) = x.trim().parse::<f64>() {
                            p.store(v.to_bits(), Ordering::Relaxed);
                        }
                        continue;
                    }
                    let mut l = l.lock().unwrap();
                    l.push(line);
                    let n = l.len();
                    if n > 200 {
                        l.drain(..n - 200);
                    }
                }
            }));
        }
        Ok(RenderJob {
            child: Mutex::new(child),
            progress,
            log,
            out_dir: out_dir.to_path_buf(),
            readers,
        })
    }

    pub fn progress(&self) -> f64 {
        f64::from_bits(self.progress.load(Ordering::Relaxed))
    }

    /// The process's last lines (its log and errors).
    pub fn tail(&self, n: usize) -> Vec<String> {
        let l = self.log.lock().unwrap();
        l[l.len().saturating_sub(n)..].to_vec()
    }

    pub fn cancel(&self) {
        let _ = self.child.lock().unwrap().kill();
    }

    /// None while it runs; then its result.
    pub fn poll(&mut self) -> Option<Result<Rendered, String>> {
        let status = match self.child.lock().unwrap().try_wait() {
            Ok(Some(s)) => s,
            Ok(None) => return None,
            Err(e) => return Some(Err(e.to_string())),
        };
        for r in self.readers.drain(..) {
            let _ = r.join();
        }
        if !status.success() {
            let tail = self.tail(6).join("\n");
            return Some(Err(format!("the render stopped ({status}):\n{tail}")));
        }
        Some(read_render(&self.out_dir))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn scene() -> Scene {
        let mut s = Scene::default();
        s.sources.push(RoomSource {
            name: "A".into(),
            track: "k1".into(),
            spl_db: 90.0,
            pos: [2.0, 2.5, 1.3],
        });
        let mut m = RoomMic::new("Mic 1", "u47_v76", [2.3, 2.5, 1.3], 0.0);
        m.aim_at(2.0, 2.5);
        s.mics.push(m);
        s
    }

    #[test]
    fn state_round_trips() {
        let s = scene();
        assert_eq!(Scene::from_state(&s.state()), s);
    }

    #[test]
    fn aim_and_pattern() {
        let s = scene();
        assert!((s.mics[0].azimuth_deg - 180.0).abs() < 1e-9);
        assert_eq!(s.mics[0].pattern(), Pattern::Cardioid);
        assert_eq!(s.mics[0].set["gain_db_v76"], 34.0);
        let mut m = s.mics[0].clone();
        m.set.insert("pattern_u47".into(), 1.0);
        assert_eq!(m.pattern(), Pattern::Omni);
    }

    #[test]
    fn problems_found() {
        let mut s = scene();
        assert!(s.problems().is_empty(), "{:?}", s.problems());
        s.mics[0].pos = [2.05, 2.5, 1.3];
        assert!(s.problems().iter().any(|p| p.contains("closer than")));
        s.mics[0].pos = [9.0, 2.5, 1.3];
        assert!(s.problems().iter().any(|p| p.contains("outside")));
    }

    #[test]
    fn render_json_is_the_python_format() {
        let s = scene();
        let clips = BTreeMap::from([("A".to_string(), PathBuf::from("a.wav"))]);
        let v = s.render_json(&clips);
        assert_eq!(v["sources"][0]["clip"], "a.wav");
        assert_eq!(v["room"]["materials"]["walls"], "furnished_wall");
        assert_eq!(v["mics"][0]["aim"]["azimuth_deg"], 180.0);
        assert_eq!(v["mics"][0]["set"]["pattern_u47"], 0.0);
    }
}
