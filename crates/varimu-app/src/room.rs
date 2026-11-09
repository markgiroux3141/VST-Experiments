//! The Room view's model (docs/ROOM_LOOP_PLAN.md): a scene of a shoebox room, sources
//! (session tracks) placed in it, mics placed and aimed, each through a chain (a mic +
//! preamp circuit), and its render into new session tracks.
//!
//! The render is Python's reference pipeline for now (`scripts/room_print.py`,
//! `varimu/rooms/`: the entry tables' BEM, the image sources with directions, the shared
//! diffuse field, the chains printed at production), run as a background process: the
//! scene is written as JSON (the format of `varimu/rooms/scene.py`'s docstring), each source
//! track as the mix plays it (its inserts' print, else its take) as a WAV beside it, and
//! the process reports `progress F` lines.
//! Porting the room to Rust (the chains already render in `render`) is the plan's later
//! step.

use std::collections::BTreeMap;
use std::io::{BufRead, BufReader};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Arc, Mutex, OnceLock};

use serde_json::{Value, json};

/// A setting of a chain: its key in the chain's circuit file and its positions.
#[derive(Clone, Debug, PartialEq)]
pub struct Setting {
    pub key: String,
    pub label: String,
    pub choices: Vec<(f64, String)>,
    pub default: f64,
}

/// How a chain's mic is drawn: always one pattern, or the label of a setting's choice.
#[derive(Clone, Debug, PartialEq)]
enum MicPattern {
    Fixed(Pattern),
    Setting(String),
}

/// A chain of the list (`config/chains.yaml`, varimu/chains.py the reference): a mic, an
/// optional booster and a preamp, composed into one circuit file with a capsule
/// (`config/circuits/<id>.yaml`, scripts/compose_chain.py --all).
#[derive(Clone, Debug, PartialEq)]
pub struct Chain {
    pub id: String,
    /// Its stages' labels joined by arrows.
    pub label: String,
    /// What it is most likely used to record (the list's `use`).
    pub use_note: String,
    /// The mic's settings, then the preamp's, in the chain's (suffixed) keys.
    pub settings: Vec<Setting>,
    pattern: MicPattern,
}

impl Chain {
    /// The mic's pattern at these settings (a setting not in `set` at its default).
    pub fn pattern(&self, set: &BTreeMap<String, f64>) -> Pattern {
        match &self.pattern {
            MicPattern::Fixed(p) => *p,
            MicPattern::Setting(key) => {
                let Some(st) = self.settings.iter().find(|s| &s.key == key) else {
                    return Pattern::OMNI;
                };
                let v = set.get(key).copied().unwrap_or(st.default);
                let label = st
                    .choices
                    .iter()
                    .find(|(x, _)| *x == v)
                    .map(|(_, l)| l.as_str());
                pattern_named(label.unwrap_or(""))
            }
        }
    }
}

/// The patterns a mic's `pattern` (or its setting's choice labels) may name, by first-order
/// coefficient in eighths (varimu/chains.py PATTERNS, the same names).
pub const PATTERN_NAMES: &[(&str, u8)] = &[
    ("omni", 8),
    ("wide omni", 7),
    ("wide cardioid", 6),
    ("broad cardioid", 5),
    ("cardioid", 4),
    ("supercardioid", 3),
    ("hypercardioid", 2),
    ("narrow figure-8", 1),
    ("figure-8", 0),
];

fn pattern_named(name: &str) -> Pattern {
    PATTERN_NAMES
        .iter()
        .find(|(n, _)| *n == name)
        .map_or(Pattern::OMNI, |(_, e)| Pattern(*e))
}

/// The chains of `<config>/chains.yaml` that are available (their composed circuit file
/// exists), in the list's order.
pub fn load_chains(config: &Path) -> Result<Vec<Chain>, String> {
    let path = config.join("chains.yaml");
    let v = yaml_json(&varimu_circuit::yaml::load(&path).map_err(|e| e.to_string())?);
    let bad = |what: String| format!("{}: {what}", path.display());
    let circuits = &v["circuits"];
    let mut out = Vec::new();
    for c in v["chains"]
        .as_array()
        .ok_or_else(|| bad("no chains".into()))?
    {
        let id = c["id"]
            .as_str()
            .ok_or_else(|| bad("a chain without an id".into()))?;
        if !config.join("circuits").join(format!("{id}.yaml")).is_file() {
            continue;
        }
        let mut stages = Vec::new();
        for kind in ["mic", "booster", "pre"] {
            if let Some(name) = c[kind].as_str() {
                let s = &circuits[name];
                if !s.is_object() {
                    return Err(bad(format!("{id}: {name} isn't in circuits")));
                }
                stages.push(s);
            }
        }
        if stages.len() < 2 {
            return Err(bad(format!("{id}: a chain is a mic and a preamp")));
        }
        let label = stages
            .iter()
            .map(|s| s["label"].as_str().unwrap_or("?"))
            .collect::<Vec<_>>()
            .join(" → ");
        let mut settings = Vec::new();
        for s in &stages {
            let tag = s["tag"].as_str().unwrap_or("");
            for st in s["settings"].as_array().into_iter().flatten() {
                let key = format!("{}_{tag}", st["key"].as_str().unwrap_or(""));
                let choices = st["choices"]
                    .as_array()
                    .into_iter()
                    .flatten()
                    .map(|x| {
                        let label = x[1].as_str().map_or_else(|| x[1].to_string(), String::from);
                        (x[0].as_f64().unwrap_or(f64::NAN), label)
                    })
                    .collect();
                let default = c["defaults"][&key].as_f64().or(st["default"].as_f64());
                settings.push(Setting {
                    label: st["label"].as_str().unwrap_or(&key).to_string(),
                    default: default.ok_or_else(|| bad(format!("{id}: {key} has no default")))?,
                    key,
                    choices,
                });
            }
        }
        let mic = stages[0];
        let pattern = match &mic["pattern"] {
            Value::String(p) => MicPattern::Fixed(pattern_named(p)),
            Value::Object(o) => match o.get("setting").and_then(Value::as_str) {
                Some(k) => {
                    MicPattern::Setting(format!("{k}_{}", mic["tag"].as_str().unwrap_or("")))
                }
                None => return Err(bad(format!("{id}: its mic's pattern names no setting"))),
            },
            _ => MicPattern::Fixed(Pattern::OMNI),
        };
        out.push(Chain {
            id: id.to_string(),
            label,
            use_note: c["use"].as_str().unwrap_or("").to_string(),
            settings,
            pattern,
        });
    }
    Ok(out)
}

static CHAINS: OnceLock<(Vec<Chain>, Option<String>)> = OnceLock::new();

fn chain_list(config: Option<&Path>) -> &'static (Vec<Chain>, Option<String>) {
    CHAINS.get_or_init(|| {
        let default = std::env::var_os("VARIMU_CONFIG").map_or_else(
            || Path::new(env!("CARGO_MANIFEST_DIR")).join("../../config"),
            PathBuf::from,
        );
        match load_chains(config.unwrap_or(&default)) {
            Ok(list) => (list, None),
            Err(e) => (Vec::new(), Some(e)),
        }
    })
}

/// Reads the chain list from `config` (the Room view does, at its start; the first read
/// wins, a read before it takes `$VARIMU_CONFIG` or the repo's config/). Its error, if
/// the list didn't read.
pub fn init_chains(config: &Path) -> Option<&'static str> {
    chain_list(Some(config)).1.as_deref()
}

/// The available chains of the list (config/chains.yaml), in its order.
pub fn chains() -> &'static [Chain] {
    &chain_list(None).0
}

pub fn chain(id: &str) -> Option<&'static Chain> {
    chains().iter().find(|c| c.id == id)
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
    // treatments from their physics (varimu/rooms/materials.py)
    "mineral_wool_50mm",
    "mineral_wool_100mm",
    "wool_100mm_gap_100mm",
    "foam_25mm",
    "panel_trap_plywood",
    // hard surfaces from the tables (varimu/rooms/materials.py TABULATED)
    "brick",
    "concrete_block_painted",
    "concrete_floor",
    "glass_window",
    "glazed_tile",
    "wood_panel",
    "anechoic",
];

fn dist3(a: &[f64; 3], b: &[f64; 3]) -> f64 {
    (0..3).map(|i| (a[i] - b[i]).powi(2)).sum::<f64>().sqrt()
}

/// The ceiling's forms (varimu/rooms/polyroom.py `CEILINGS`).
pub const CEILINGS: &[&str] = &["flat", "shed", "gable", "vault"];

/// Floor-plan presets (a polygon of the given width and depth; `Scene::set_preset`).
pub const PRESETS: &[&str] = &[
    "shoebox",
    "splayed",
    "trapezoid",
    "L-shape",
    "hexagon",
    "octagon",
];

/// The ceiling over the floor plan: its form, the height at the eaves (or everywhere, flat),
/// the peak, the direction it varies along (counterclockwise from +x), a vault's facets.
#[derive(Clone, PartialEq, Debug)]
pub struct Ceiling {
    pub kind: String,
    pub height: f64,
    pub peak: f64,
    pub axis_deg: f64,
    pub facets: u32,
}

impl Default for Ceiling {
    fn default() -> Ceiling {
        Ceiling {
            kind: "flat".into(),
            height: 3.2,
            peak: 4.5,
            axis_deg: 0.0,
            facets: 8,
        }
    }
}

/// A preset's floor polygon, counterclockwise, `w` x `d` metres from the origin.
pub fn preset_plan(name: &str, w: f64, d: f64) -> Vec<[f64; 2]> {
    let p = |pts: &[(f64, f64)]| pts.iter().map(|&(x, y)| [x * w, y * d]).collect();
    match name {
        "splayed" => p(&[
            (0.0, 0.0),
            (0.93, 0.08),
            (1.0, 0.9),
            (0.47, 1.0),
            (-0.06, 0.8),
        ]),
        "trapezoid" => p(&[(0.0, 0.0), (1.0, 0.0), (0.8, 1.0), (0.2, 1.0)]),
        "L-shape" => p(&[
            (0.0, 0.0),
            (1.0, 0.0),
            (1.0, 0.45),
            (0.45, 0.45),
            (0.45, 1.0),
            (0.0, 1.0),
        ]),
        "hexagon" => p(&[
            (0.25, 0.0),
            (0.75, 0.0),
            (1.0, 0.5),
            (0.75, 1.0),
            (0.25, 1.0),
            (0.0, 0.5),
        ]),
        "octagon" => p(&[
            (0.2, 0.0),
            (0.8, 0.0),
            (1.0, 0.2),
            (1.0, 0.8),
            (0.8, 1.0),
            (0.2, 1.0),
            (0.0, 0.8),
            (0.0, 0.2),
        ]),
        _ => p(&[(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]),
    }
}

/// A room preset (`config/rooms/<name>.yaml`, varimu/rooms/presets.py): a room ready to
/// record in, its plan, ceiling, materials, faces and objects.
#[derive(Clone, Debug, PartialEq)]
pub struct RoomPreset {
    pub name: String,
    pub title: String,
    pub description: String,
    /// The room block (varimu/rooms/scene.py's format).
    pub room: Value,
}

/// A YAML value as JSON (the presets are YAML; the scene is JSON).
fn yaml_json(v: &varimu_circuit::yaml::Value) -> Value {
    use varimu_circuit::yaml::Value as Y;
    match v {
        Y::Null => Value::Null,
        Y::Bool(b) => json!(b),
        Y::Int(i) => json!(i),
        Y::Float(x) => json!(x),
        Y::Str(t) => json!(t),
        Y::List(a) => Value::Array(a.iter().map(yaml_json).collect()),
        Y::Map(m) => Value::Object(m.0.iter().map(|(k, x)| (k.clone(), yaml_json(x))).collect()),
    }
}

/// The presets in `<config>/rooms/`, sorted by title; a file that doesn't read is left
/// out with its error.
pub fn load_presets(config: &Path) -> (Vec<RoomPreset>, Vec<String>) {
    let (mut out, mut errors) = (Vec::new(), Vec::new());
    let mut paths: Vec<PathBuf> = std::fs::read_dir(config.join("rooms"))
        .map(|d| d.filter_map(|e| Some(e.ok()?.path())).collect())
        .unwrap_or_default();
    paths.retain(|p| p.extension().is_some_and(|x| x == "yaml"));
    for p in paths {
        let v = match varimu_circuit::yaml::load(&p) {
            Ok(v) => yaml_json(&v),
            Err(e) => {
                errors.push(e.to_string());
                continue;
            }
        };
        if !v["room"]["floor_m"].is_array() {
            errors.push(format!("{}: no room.floor_m", p.display()));
            continue;
        }
        let name = p.file_stem().unwrap().to_string_lossy().to_string();
        out.push(RoomPreset {
            title: st(&v, "title", &name),
            description: st(&v, "description", ""),
            room: v["room"].clone(),
            name,
        });
    }
    out.sort_by(|a, b| a.title.cmp(&b.title));
    (out, errors)
}

/// Whether (x, y) is inside the polygon (even-odd; the boundary counts as inside).
pub fn in_polygon(poly: &[[f64; 2]], x: f64, y: f64) -> bool {
    let n = poly.len();
    let mut inside = false;
    for i in 0..n {
        let ([x0, y0], [x1, y1]) = (poly[i], poly[(i + 1) % n]);
        if (y0 > y) != (y1 > y) && x < x0 + (y - y0) * (x1 - x0) / (y1 - y0) {
            inside = !inside;
        }
        let (ex, ey) = (x1 - x0, y1 - y0);
        let t = (((x - x0) * ex + (y - y0) * ey) / (ex * ex + ey * ey)).clamp(0.0, 1.0);
        if (x - (x0 + t * ex)).hypot(y - (y0 + t * ey)) < 1e-9 {
            return true;
        }
    }
    inside
}

fn polygon_area(poly: &[[f64; 2]]) -> f64 {
    let n = poly.len();
    0.5 * (0..n)
        .map(|i| poly[i][0] * poly[(i + 1) % n][1] - poly[(i + 1) % n][0] * poly[i][1])
        .sum::<f64>()
}

fn segments_cross(a: [f64; 2], b: [f64; 2], c: [f64; 2], d: [f64; 2]) -> bool {
    let o = |p: [f64; 2], q: [f64; 2], r: [f64; 2]| {
        (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])
    };
    let (d1, d2, d3, d4) = (o(c, d, a), o(c, d, b), o(a, b, c), o(a, b, d));
    (d1 > 0.0) != (d2 > 0.0) && (d3 > 0.0) != (d4 > 0.0)
}

/// The qualities a scene renders at.
pub const QUALITIES: &[&str] = &["production", "draft"];

/// The wave solver's crossovers offered (Hz; 0 = off): varimu/rooms/wave.py, ROOM_LOOP_PLAN.md
/// R10. The cost grows with the crossover's fourth power (~6 s per source at 500 Hz in a
/// 123 m^3 room on the GPU, ~1.5 min at 1 kHz).
pub const WAVE_CROSSOVERS: &[f64] = &[0.0, 250.0, 500.0, 1000.0];

/// A mic's polar pattern, for drawing (the physics is the capsule's): the first-order
/// figure a + (1 - a) cos(theta), its coefficient a in eighths (8 omni, 4 cardioid, 0
/// figure-8).
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub struct Pattern(pub u8);

impl Pattern {
    pub const OMNI: Pattern = Pattern(8);
    pub const CARDIOID: Pattern = Pattern(4);
    pub const FIGURE8: Pattern = Pattern(0);

    /// The figure's signed sensitivity at theta (radians from the axis): 1 on axis.
    pub fn gain(self, theta: f32) -> f32 {
        let a = f32::from(self.0) / 8.0;
        a + (1.0 - a) * theta.cos()
    }
}

/// Nearest a mic may be to a source (the entry tables' nearest distance).
pub const MIN_DISTANCE_M: f64 = 0.1;

#[derive(Clone, PartialEq, Debug)]
pub struct RoomSource {
    pub name: String,
    /// The session track whose active take plays here.
    pub track: String,
    /// Its rms in dB SPL 1 m away in free field (on its axis).
    pub spl_db: f64,
    pub pos: [f64; 3],
    /// How it radiates (`DIRECTIVITIES`: varimu/rooms/directivity.py's presets).
    pub directivity: String,
    /// Where it faces: counterclockwise from +x, and up.
    pub azimuth_deg: f64,
    pub elevation_deg: f64,
    /// A stereo track's two speakers apart (m; docs/STEREO_PLAN.md ST4-ST5): its left at the
    /// facing direction's left as its player sees it, its right at the other side.
    pub spacing_m: f64,
    /// A stereo track placed as one point anyway (its mid), to compare.
    pub as_mono: bool,
}

/// The spacing a stereo device's speakers have (device id, metres, source): the default for
/// a source placed from its track (others: [`DEFAULT_SPACING_M`]).
pub const STEREO_SPACINGS: &[(&str, f64, &str)] = &[(
    "rhodes_suitcase",
    0.6,
    "provisional: model knowledge (two 12 in drivers across the 48 in speaker section, \
     RHODES_PLAN.md 'The Suitcase'; to be measured from a dimensioned photo or the manual)",
)];

/// A stereo source's spacing when its device has none in [`STEREO_SPACINGS`]: two monitors
/// on a desk (provisional).
pub const DEFAULT_SPACING_M: f64 = 1.5;

/// A device's speakers' spacing ([`STEREO_SPACINGS`], else [`DEFAULT_SPACING_M`]).
pub fn default_spacing_m(device: &str) -> f64 {
    STEREO_SPACINGS
        .iter()
        .find(|(d, _, _)| *d == device)
        .map_or(DEFAULT_SPACING_M, |e| e.1)
}

/// A source's patterns (id, label): a cap on a sphere (varimu/rooms/directivity.py PRESETS).
pub const DIRECTIVITIES: &[(&str, &str)] = &[
    ("omni", "omni"),
    ("voice", "voice (a head)"),
    ("amp_1x12", "amp 1x12"),
    ("amp_2x12", "amp 2x12"),
    ("bass_1x15", "bass cab 1x15"),
];

/// A pattern's body: the sphere's radius (varimu/rooms/directivity.py PRESETS), 0 for omni.
pub fn body_radius_m(directivity: &str) -> f64 {
    match directivity {
        "voice" => 0.09,
        "amp_1x12" => 0.25,
        "amp_2x12" => 0.35,
        "bass_1x15" => 0.40,
        _ => 0.0,
    }
}

/// `sounding_rms`'s gating (varimu/rooms/scene.py's GATE_*).
const GATE_BLOCK_S: f64 = 0.05;
const GATE_ABSOLUTE_DB: f64 = -70.0;
const GATE_RELATIVE_DB: f64 = -10.0;

/// A clip's rms while it sounds, the level a source's SPL means: varimu/rooms/scene.py's
/// `sounding_rms` (BS.1770's two gates on 50 ms blocks overlapping by half, unweighted).
pub fn sounding_rms(x: &[f32], rate: u32) -> f64 {
    let block = (GATE_BLOCK_S * rate as f64).round() as usize;
    let hop = block / 2;
    if x.len() < block || block < 2 {
        if x.is_empty() {
            return 0.0;
        }
        let e: f64 = x.iter().map(|&v| (v as f64) * (v as f64)).sum();
        return (e / x.len() as f64).sqrt();
    }
    let mut c = Vec::with_capacity(x.len() + 1);
    let mut acc = 0.0f64;
    c.push(0.0);
    for &v in x {
        acc += (v as f64) * (v as f64);
        c.push(acc);
    }
    let ms: Vec<f64> = (0..=x.len() - block)
        .step_by(hop)
        .map(|s| (c[s + block] - c[s]) / block as f64)
        .collect();
    let top = ms.iter().copied().fold(0.0, f64::max);
    if top <= 0.0 {
        return 0.0;
    }
    let gate = |v: &[f64], g: f64| -> Vec<f64> { v.iter().copied().filter(|&m| m > g).collect() };
    let mean = |v: &[f64]| v.iter().sum::<f64>() / v.len() as f64;
    let a = gate(&ms, top * 10f64.powf(GATE_ABSOLUTE_DB / 10.0));
    let r = gate(&a, mean(&a) * 10f64.powf(GATE_RELATIVE_DB / 10.0));
    mean(&r).sqrt()
}

/// The sources' SPLs that carry the session's balance into the room: `mix_db` per source
/// is its track's level in the mix (its `sounding_rms` in dB plus its fader), None to leave
/// it alone (muted, silent, no take). The source loudest in the mix gets the highest SPL of
/// those sources now (the room's overall loudness, which drives the chains, stays), the
/// others sit below it by as much as they sit below it in the mix; rounded to 0.1 dB and
/// kept in the Room view's 40-130 dB.
pub fn levels_from_mix(mix_db: &[Option<f64>], spl_db: &[f64]) -> Vec<f64> {
    let on = || {
        mix_db
            .iter()
            .zip(spl_db)
            .filter_map(|(m, s)| m.map(|m| (m, *s)))
    };
    let (Some(loud), Some(top)) = (
        on().map(|(m, _)| m).reduce(f64::max),
        on().map(|(_, s)| s).reduce(f64::max),
    ) else {
        return spl_db.to_vec();
    };
    mix_db
        .iter()
        .zip(spl_db)
        .map(|(m, &s)| match m {
            Some(m) => (((top + m - loud) * 10.0).round() / 10.0).clamp(40.0, 130.0),
            None => s,
        })
        .collect()
}

impl RoomSource {
    /// Its body's centre (a radius behind the cap, against its aim) and radius.
    pub fn body(&self) -> ([f64; 3], f64) {
        let r = body_radius_m(&self.directivity);
        let (az, el) = (
            self.azimuth_deg.to_radians(),
            self.elevation_deg.to_radians(),
        );
        let aim = [el.cos() * az.cos(), el.cos() * az.sin(), el.sin()];
        (std::array::from_fn(|i| self.pos[i] - r * aim[i]), r)
    }

    pub fn new(name: &str, track: &str, spl_db: f64, pos: [f64; 3]) -> RoomSource {
        RoomSource {
            name: name.to_string(),
            track: track.to_string(),
            spl_db,
            pos,
            directivity: "omni".to_string(),
            azimuth_deg: 0.0,
            elevation_deg: 0.0,
            spacing_m: DEFAULT_SPACING_M,
            as_mono: false,
        }
    }

    pub fn directional(&self) -> bool {
        self.directivity != "omni"
    }

    /// A stereo source's two speakers on the plan, (left, right): across its facing
    /// direction, `spacing_m` apart about its position (varimu/rooms/scene.py's expansion).
    pub fn sides(&self) -> [[f64; 3]; 2] {
        let a = self.azimuth_deg.to_radians();
        let left = [-a.sin(), a.cos()];
        let h = 0.5 * self.spacing_m;
        let at = |s: f64| {
            [
                self.pos[0] + s * h * left[0],
                self.pos[1] + s * h * left[1],
                self.pos[2],
            ]
        };
        [at(1.0), at(-1.0)]
    }

    /// Face a floor-plan position.
    pub fn aim_at(&mut self, x: f64, y: f64) {
        let (dx, dy) = (x - self.pos[0], y - self.pos[1]);
        if dx.hypot(dy) > 1e-9 {
            self.azimuth_deg = dy.atan2(dx).to_degrees();
        }
    }
}

/// An object in the room (ROOM_LOOP_PLAN.md R11; varimu/rooms/polyroom.py's boxes): a box
/// `size` (width, depth, height) about `center`, turned `yaw_deg` about the vertical and
/// tilted `tilt_deg` about its width axis, of one surface. A gobo is a thin one.
#[derive(Clone, PartialEq, Debug)]
pub struct RoomObject {
    pub name: String,
    pub center: [f64; 3],
    pub size: [f64; 3],
    pub yaw_deg: f64,
    pub tilt_deg: f64,
    pub material: String,
}

/// The objects offered: (label, name prefix, size, centre height, surface, tilt). A piano's
/// lid is a thin panel tilted up (a grand piano: an omni source under it; the lid reflects it
/// out of the open side and its edges diffract).
/// (label, name prefix, size, centre height, surface, tilt).
pub type ObjectKind = (&'static str, &'static str, [f64; 3], f64, &'static str, f64);

pub const OBJECT_KINDS: &[ObjectKind] = &[
    ("Gobo", "Gobo", [1.2, 0.08, 1.8], 0.9, "heavy_drapes", 0.0),
    ("Riser", "Riser", [1.8, 1.2, 0.3], 0.15, "wood_floor", 0.0),
    (
        "Cabinet",
        "Cabinet",
        [0.6, 0.45, 1.0],
        0.5,
        "gypsum_on_studs",
        0.0,
    ),
    (
        "Piano lid",
        "Lid",
        [1.5, 1.6, 0.03],
        1.45,
        "wood_floor",
        35.0,
    ),
    // a 6 ft grand's body, its rim ~1 m high (the lid above it)
    ("Piano", "Piano", [1.5, 1.9, 0.36], 0.83, "wood_floor", 0.0),
    // a ceiling cloud over a mix or tracking position
    (
        "Cloud",
        "Cloud",
        [2.0, 1.6, 0.1],
        2.5,
        "mineral_wool_100mm",
        0.0,
    ),
    // a floor-to-ceiling panel trap, for a corner
    (
        "Bass trap",
        "Trap",
        [0.6, 0.6, 2.4],
        1.2,
        "panel_trap_plywood",
        0.0,
    ),
];

impl RoomObject {
    /// The box's axes (width, depth, height) after yaw and tilt.
    pub fn axes(&self) -> [[f64; 3]; 3] {
        let (y, t) = (self.yaw_deg.to_radians(), self.tilt_deg.to_radians());
        let (cy, sy, ct, st) = (y.cos(), y.sin(), t.cos(), t.sin());
        // Rz(yaw) Rx(tilt), columns
        [
            [cy, sy, 0.0],
            [-sy * ct, cy * ct, st],
            [sy * st, -cy * st, ct],
        ]
    }

    /// The 8 corners.
    pub fn corners(&self) -> Vec<[f64; 3]> {
        let ax = self.axes();
        let mut out = Vec::new();
        for a in [-0.5, 0.5] {
            for b in [-0.5, 0.5] {
                for c in [-0.5, 0.5] {
                    let k = [a * self.size[0], b * self.size[1], c * self.size[2]];
                    out.push(std::array::from_fn(|i| {
                        self.center[i] + k[0] * ax[0][i] + k[1] * ax[1][i] + k[2] * ax[2][i]
                    }));
                }
            }
        }
        out
    }

    /// Its outline seen from above (the convex hull of its corners).
    pub fn footprint(&self) -> Vec<[f64; 2]> {
        let mut pts: Vec<[f64; 2]> = self.corners().iter().map(|c| [c[0], c[1]]).collect();
        pts.sort_by(|a, b| a[0].total_cmp(&b[0]).then(a[1].total_cmp(&b[1])));
        pts.dedup_by(|a, b| (a[0] - b[0]).abs() < 1e-12 && (a[1] - b[1]).abs() < 1e-12);
        if pts.len() < 3 {
            return pts;
        }
        let cross = |o: [f64; 2], a: [f64; 2], b: [f64; 2]| {
            (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
        };
        let mut hull: Vec<[f64; 2]> = Vec::new();
        for pass in 0..2 {
            let start = hull.len();
            let it: Box<dyn Iterator<Item = &[f64; 2]>> = if pass == 0 {
                Box::new(pts.iter())
            } else {
                Box::new(pts.iter().rev())
            };
            for &p in it {
                while hull.len() >= start + 2
                    && cross(hull[hull.len() - 2], hull[hull.len() - 1], p) <= 0.0
                {
                    hull.pop();
                }
                hull.push(p);
            }
            hull.pop();
        }
        hull
    }

    /// Whether a point is inside the box.
    pub fn contains(&self, p: &[f64; 3]) -> bool {
        let ax = self.axes();
        let q: [f64; 3] = std::array::from_fn(|i| p[i] - self.center[i]);
        (0..3).all(|k| {
            let d = q[0] * ax[k][0] + q[1] * ax[k][1] + q[2] * ax[k][2];
            d.abs() < 0.5 * self.size[k]
        })
    }

    fn json(&self) -> Value {
        json!({"name": self.name, "center_m": self.center, "size_m": self.size,
               "yaw_deg": self.yaw_deg, "tilt_deg": self.tilt_deg, "material": self.material})
    }

    fn from_json(v: &Value) -> RoomObject {
        RoomObject {
            name: st(v, "name", "object"),
            center: s3(&v["center_m"]),
            size: s3(&v["size_m"]),
            yaw_deg: f(v, "yaw_deg", 0.0),
            tilt_deg: f(v, "tilt_deg", 0.0),
            material: st(v, "material", "furnished_wall"),
        }
    }
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
    /// The sources it records, by name; None = all (varimu/rooms/scene.py's `hears`: the
    /// others' bleed gated out, as if each source were recorded in a pass of its own).
    pub hears: Option<Vec<String>>,
    /// What it hears goes through its chain a pass per source, the prints summed (scene.py's
    /// `passes: separate`), instead of together in one take.
    pub separate_passes: bool,
    /// No room for this mic: the direct sound only (scene.py's `free_field`).
    pub free_field: bool,
}

impl RoomMic {
    pub fn new(name: &str, chain_id: &str, pos: [f64; 3], azimuth_deg: f64) -> RoomMic {
        let set = chain(chain_id)
            .map(|c| {
                c.settings
                    .iter()
                    .map(|s| (s.key.clone(), s.default))
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
            hears: None,
            separate_passes: false,
            free_field: false,
        }
    }

    /// Whether it records the source called `name`.
    pub fn hears_source(&self, name: &str) -> bool {
        self.hears
            .as_ref()
            .is_none_or(|h| h.iter().any(|n| n == name))
    }

    pub fn pattern(&self) -> Pattern {
        chain(&self.chain).map_or(Pattern::OMNI, |c| c.pattern(&self.set))
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
    /// The floor plan's preset (`PRESETS`), or "custom" once a corner is moved.
    pub shape: String,
    /// The floor polygon (m, counterclockwise).
    pub plan: Vec<[f64; 2]>,
    pub roof: Ceiling,
    /// Materials: the walls', the floor's, the ceiling's.
    pub walls: String,
    pub floor: String,
    pub ceiling: String,
    /// Faces with a material of their own (ROOM_LOOP_PLAN.md R7), as polyroom.py's
    /// `face_materials`: "wall N" (from corner N to N + 1), "ceiling N" (a facet).
    pub faces: BTreeMap<String, String>,
    pub sources: Vec<RoomSource>,
    pub mics: Vec<RoomMic>,
    /// Objects in the room (R11): gobos, risers, cabinets.
    pub objects: Vec<RoomObject>,
    pub quality: String,
    /// The wave solver below this (Hz), 0 = off. New scenes 500; scenes saved before it
    /// existed load as off (they render as they did).
    pub wave_hz: f64,
}

impl Default for Scene {
    fn default() -> Scene {
        Scene {
            name: "Room".to_string(),
            shape: "shoebox".to_string(),
            plan: preset_plan("shoebox", 7.0, 5.5),
            roof: Ceiling::default(),
            walls: "furnished_wall".to_string(),
            floor: "wood_floor".to_string(),
            ceiling: "gypsum_on_studs".to_string(),
            faces: BTreeMap::new(),
            sources: Vec::new(),
            mics: Vec::new(),
            objects: Vec::new(),
            quality: "production".to_string(),
            wave_hz: 500.0,
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
    /// Replace the floor plan by a preset `w` x `d` m.
    pub fn set_preset(&mut self, name: &str, w: f64, d: f64) {
        self.shape = name.to_string();
        self.plan = preset_plan(name, w, d);
        self.faces.retain(|k, _| !k.starts_with("wall "));
    }

    /// Replace the room by a preset's: plan, ceiling, materials, faces and objects. The
    /// sources and mics move together, keeping their distances, so their middle sits over
    /// the new floor's; `problems` names any that end up outside.
    pub fn apply_room_preset(&mut self, p: &RoomPreset) {
        let r = &p.room;
        let old_mid = self.items_middle();
        self.plan = r["floor_m"]
            .as_array()
            .map(|a| {
                a.iter()
                    .filter_map(|q| Some([q[0].as_f64()?, q[1].as_f64()?]))
                    .collect()
            })
            .unwrap_or_default();
        self.shape = "custom".to_string();
        let c = &r["ceiling"];
        self.roof = Ceiling {
            kind: st(c, "type", "flat"),
            height: f(c, "height_m", 3.0),
            peak: c["peak_m"]
                .as_f64()
                .unwrap_or_else(|| f(c, "height_m", 3.0)),
            axis_deg: f(c, "axis_deg", 0.0),
            facets: c["facets"].as_u64().unwrap_or(8) as u32,
        };
        let m = &r["materials"];
        self.walls = st(m, "walls", "furnished_wall");
        self.floor = st(m, "floor", "wood_floor");
        self.ceiling = st(m, "ceiling", "gypsum_on_studs");
        self.faces = m["faces"]
            .as_object()
            .map(|o| {
                o.iter()
                    .filter_map(|(k, x)| Some((k.clone(), x.as_str()?.to_string())))
                    .collect()
            })
            .unwrap_or_default();
        self.objects = r["objects"]
            .as_array()
            .map(|a| a.iter().map(RoomObject::from_json).collect())
            .unwrap_or_default();
        if let Some(old) = old_mid {
            let n = self.plan.len().max(1) as f64;
            let mid = [
                self.plan.iter().map(|q| q[0]).sum::<f64>() / n,
                self.plan.iter().map(|q| q[1]).sum::<f64>() / n,
            ];
            let d = [mid[0] - old[0], mid[1] - old[1]];
            for p in self.sources.iter_mut().map(|s| &mut s.pos) {
                p[0] += d[0];
                p[1] += d[1];
            }
            for p in self.mics.iter_mut().map(|m| &mut m.pos) {
                p[0] += d[0];
                p[1] += d[1];
            }
        }
    }

    /// The middle of the sources' and mics' floor positions (their bounding box's).
    fn items_middle(&self) -> Option<[f64; 2]> {
        let pts: Vec<[f64; 3]> = (self.sources.iter().map(|s| s.pos))
            .chain(self.mics.iter().map(|m| m.pos))
            .collect();
        if pts.is_empty() {
            return None;
        }
        let ext = |i: usize| {
            let lo = pts.iter().map(|p| p[i]).fold(f64::MAX, f64::min);
            let hi = pts.iter().map(|p| p[i]).fold(f64::MIN, f64::max);
            0.5 * (lo + hi)
        };
        Some([ext(0), ext(1)])
    }

    /// The ceiling's facets (planes): one for flat and shed, two for a gable, a vault's.
    pub fn n_facets(&self) -> usize {
        self.profile().len() - 1
    }

    /// A face's material: its own, else the room's for its kind ("wall N", "ceiling N",
    /// "floor").
    pub fn face_material(&self, key: &str) -> &str {
        if let Some(m) = self.faces.get(key) {
            return m;
        }
        if key.starts_with("wall") {
            &self.walls
        } else if key.starts_with("ceiling") {
            &self.ceiling
        } else {
            &self.floor
        }
    }

    /// Give a face its own material, or `None` for the room's again.
    pub fn set_face_material(&mut self, key: &str, m: Option<String>) {
        match m {
            Some(m) => self.faces.insert(key.to_string(), m),
            None => self.faces.remove(key),
        };
    }

    fn wall_faces(&self) -> BTreeMap<usize, String> {
        self.faces
            .iter()
            .filter_map(|(k, v)| Some((k.strip_prefix("wall ")?.parse().ok()?, v.clone())))
            .collect()
    }

    fn set_wall_faces(&mut self, walls: BTreeMap<usize, String>) {
        self.faces.retain(|k, _| !k.starts_with("wall "));
        for (i, m) in walls {
            self.faces.insert(format!("wall {i}"), m);
        }
    }

    /// A corner added after corner `i` (on wall i): both halves keep the wall's material.
    pub fn insert_corner(&mut self, i: usize, p: [f64; 2]) {
        let mut out = BTreeMap::new();
        for (w, m) in self.wall_faces() {
            match w.cmp(&i) {
                std::cmp::Ordering::Less => {
                    out.insert(w, m);
                }
                std::cmp::Ordering::Equal => {
                    out.insert(w, m.clone());
                    out.insert(w + 1, m);
                }
                std::cmp::Ordering::Greater => {
                    out.insert(w + 1, m);
                }
            }
        }
        self.plan.insert(i + 1, p);
        self.set_wall_faces(out);
    }

    /// Corner `c` removed: the two walls meeting there become one, the earlier one's.
    pub fn remove_corner(&mut self, c: usize) {
        let walls = self.wall_faces();
        // a list of walls parallel to the corners, removed as the corner: wall c goes, the
        // merged wall is the one before it (the last when c = 0)
        let mut list: Vec<Option<String>> = (0..self.plan.len())
            .map(|w| walls.get(&w).cloned())
            .collect();
        list.remove(c);
        self.plan.remove(c);
        self.set_wall_faces(
            list.into_iter()
                .enumerate()
                .filter_map(|(i, m)| Some((i, m?)))
                .collect(),
        );
    }

    /// The faces' own materials that exist on this plan and ceiling.
    fn faces_in_room(&self) -> BTreeMap<String, String> {
        let (n, nf) = (self.plan.len(), self.n_facets());
        self.faces
            .iter()
            .filter(|(k, _)| match k.split_once(' ') {
                Some(("wall", i)) => i.parse::<usize>().is_ok_and(|i| i < n),
                Some(("ceiling", i)) => i.parse::<usize>().is_ok_and(|i| i < nf),
                _ => false,
            })
            .map(|(k, v)| (k.clone(), v.clone()))
            .collect()
    }

    /// The floor plan's bounding box: (min, max).
    pub fn bbox(&self) -> ([f64; 2], [f64; 2]) {
        let mut lo = [f64::INFINITY; 2];
        let mut hi = [f64::NEG_INFINITY; 2];
        for p in &self.plan {
            for i in 0..2 {
                lo[i] = lo[i].min(p[i]);
                hi[i] = hi[i].max(p[i]);
            }
        }
        (lo, hi)
    }

    fn u_dir(&self) -> [f64; 2] {
        let a = self.roof.axis_deg.to_radians();
        [a.cos(), a.sin()]
    }

    /// The ceiling's profile along its axis: knots (u, height), as polyroom.py's.
    pub fn profile(&self) -> Vec<(f64, f64)> {
        let u = self.u_dir();
        let us: Vec<f64> = self
            .plan
            .iter()
            .map(|p| p[0] * u[0] + p[1] * u[1])
            .collect();
        let lo = us.iter().cloned().fold(f64::INFINITY, f64::min);
        let hi = us.iter().cloned().fold(f64::NEG_INFINITY, f64::max);
        let (h, pk) = (self.roof.height, self.roof.peak);
        match self.roof.kind.as_str() {
            "shed" => vec![(lo, h), (hi, pk)],
            "gable" => vec![(lo, h), (0.5 * (lo + hi), pk), (hi, h)],
            "vault" => {
                let n = self.roof.facets.max(2);
                (0..=n)
                    .map(|i| {
                        let t = -1.0 + 2.0 * i as f64 / n as f64;
                        (
                            lo + 0.5 * (t + 1.0) * (hi - lo),
                            h + (pk - h) * (1.0 - t * t).max(0.0).sqrt(),
                        )
                    })
                    .collect()
            }
            _ => vec![(lo, h), (hi, h)],
        }
    }

    /// The ceiling's height over (x, y).
    pub fn height_at(&self, x: f64, y: f64) -> f64 {
        let u = self.u_dir();
        let v = x * u[0] + y * u[1];
        let k = self.profile();
        if v <= k[0].0 {
            return k[0].1;
        }
        for w in k.windows(2) {
            if v <= w[1].0 {
                let t = (v - w[0].0) / (w[1].0 - w[0].0).max(1e-12);
                return w[0].1 + t * (w[1].1 - w[0].1);
            }
        }
        k[k.len() - 1].1
    }

    /// The highest point of the ceiling.
    pub fn top(&self) -> f64 {
        self.profile().iter().map(|k| k.1).fold(0.0, f64::max)
    }

    /// Whether a point is inside the room (and in none of its objects).
    pub fn inside(&self, p: &[f64; 3]) -> bool {
        in_polygon(&self.plan, p[0], p[1])
            && p[2] > 0.0
            && p[2] < self.height_at(p[0], p[1])
            && !self.objects.iter().any(|o| o.contains(p))
    }

    /// The editor's state (what `<session>/rooms/<name>.json` holds: sources by track id).
    pub fn state(&self) -> Value {
        json!({
            "name": self.name,
            "shape": self.shape,
            "floor_m": self.plan,
            "ceiling_form": {"type": self.roof.kind, "height_m": self.roof.height,
                             "peak_m": self.roof.peak, "axis_deg": self.roof.axis_deg,
                             "facets": self.roof.facets},
            "walls": self.walls, "floor": self.floor, "ceiling": self.ceiling,
            "faces": self.faces,
            "quality": self.quality,
            "wave_hz": self.wave_hz,
            "objects": self.objects.iter().map(RoomObject::json).collect::<Vec<_>>(),
            "sources": self.sources.iter().map(|s| json!({
                "name": s.name, "track": s.track, "spl_db": s.spl_db, "position_m": s.pos,
                "directivity": s.directivity, "azimuth_deg": s.azimuth_deg,
                "elevation_deg": s.elevation_deg, "spacing_m": s.spacing_m,
                "as_mono": s.as_mono,
            })).collect::<Vec<_>>(),
            "mics": self.mics.iter().map(|m| json!({
                "name": m.name, "chain": m.chain, "set": m.set, "position_m": m.pos,
                "azimuth_deg": m.azimuth_deg, "elevation_deg": m.elevation_deg, "pan": m.pan,
                "hears": m.hears, "separate_passes": m.separate_passes,
                "free_field": m.free_field,
            })).collect::<Vec<_>>(),
        })
    }

    pub fn from_state(v: &Value) -> Scene {
        let d = Scene::default();
        // older scenes: a shoebox's dims
        let (plan, roof, shape) = match (v["floor_m"].as_array(), v["dims_m"].as_array()) {
            (Some(a), _) => (
                a.iter()
                    .filter_map(|p| Some([p[0].as_f64()?, p[1].as_f64()?]))
                    .collect(),
                {
                    let c = &v["ceiling_form"];
                    Ceiling {
                        kind: st(c, "type", "flat"),
                        height: f(c, "height_m", 3.2),
                        peak: f(c, "peak_m", 4.5),
                        axis_deg: f(c, "axis_deg", 0.0),
                        facets: c["facets"].as_u64().unwrap_or(8) as u32,
                    }
                },
                st(v, "shape", "custom"),
            ),
            (None, Some(_)) => {
                let dm = s3(&v["dims_m"]);
                (
                    preset_plan("shoebox", dm[0], dm[1]),
                    Ceiling {
                        height: dm[2],
                        ..Ceiling::default()
                    },
                    "shoebox".to_string(),
                )
            }
            _ => (d.plan.clone(), d.roof.clone(), d.shape.clone()),
        };
        Scene {
            name: st(v, "name", &d.name),
            shape,
            plan,
            roof,
            walls: st(v, "walls", &d.walls),
            floor: st(v, "floor", &d.floor),
            ceiling: st(v, "ceiling", &d.ceiling),
            faces: v["faces"]
                .as_object()
                .map(|o| {
                    o.iter()
                        .filter_map(|(k, x)| Some((k.clone(), x.as_str()?.to_string())))
                        .collect()
                })
                .unwrap_or_default(),
            quality: st(v, "quality", &d.quality),
            wave_hz: f(v, "wave_hz", 0.0),
            objects: v["objects"]
                .as_array()
                .map(|a| a.iter().map(RoomObject::from_json).collect())
                .unwrap_or_default(),
            sources: v["sources"]
                .as_array()
                .map(|a| {
                    a.iter()
                        .map(|s| RoomSource {
                            name: st(s, "name", "source"),
                            track: st(s, "track", ""),
                            spl_db: f(s, "spl_db", 90.0),
                            pos: s3(&s["position_m"]),
                            directivity: st(s, "directivity", "omni"),
                            azimuth_deg: f(s, "azimuth_deg", 0.0),
                            elevation_deg: f(s, "elevation_deg", 0.0),
                            spacing_m: f(s, "spacing_m", DEFAULT_SPACING_M),
                            as_mono: s["as_mono"].as_bool().unwrap_or(false),
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
                            hears: m["hears"].as_array().map(|a| {
                                a.iter()
                                    .filter_map(|x| Some(x.as_str()?.to_string()))
                                    .collect()
                            }),
                            separate_passes: m["separate_passes"].as_bool().unwrap_or(false),
                            free_field: m["free_field"].as_bool().unwrap_or(false),
                        })
                        .collect()
                })
                .unwrap_or_default(),
        }
    }

    /// The scene in varimu/rooms/scene.py's format, each source's clip from `clips`.
    pub fn render_json(&self, clips: &BTreeMap<String, PathBuf>) -> Value {
        self.render_json_lr(clips, &BTreeMap::new())
    }

    /// [`Scene::render_json`] with stereo sources' right channels (`rights`, by source name):
    /// each such source a stereo pair (docs/STEREO_PLAN.md ST4: varimu/rooms/scene.py).
    pub fn render_json_lr(
        &self,
        clips: &BTreeMap<String, PathBuf>,
        rights: &BTreeMap<String, PathBuf>,
    ) -> Value {
        let mut materials =
            json!({"walls": self.walls, "floor": self.floor, "ceiling": self.ceiling});
        let faces = self.faces_in_room();
        if !faces.is_empty() {
            materials["faces"] = json!(faces);
        }
        let mut room = json!({
            "floor_m": self.plan,
            "ceiling": {"type": self.roof.kind, "height_m": self.roof.height,
                        "peak_m": self.roof.peak, "axis_deg": self.roof.axis_deg,
                        "facets": self.roof.facets},
            "materials": materials,
            "source": "the Room view (docs/ROOM_LOOP_PLAN.md)",
        });
        if !self.objects.is_empty() {
            room["objects"] = json!(
                self.objects
                    .iter()
                    .map(RoomObject::json)
                    .collect::<Vec<_>>()
            );
        }
        json!({
            "name": self.name,
            "room": room,
            "sources": self.sources.iter().map(|s| {
                let mut v = json!({
                    "name": s.name,
                    "clip": clips.get(&s.name).map(|p| p.to_string_lossy().to_string()),
                    "spl_db": s.spl_db,
                    "position_m": s.pos,
                    "directivity": s.directivity,
                    "aim": {"azimuth_deg": s.azimuth_deg, "elevation_deg": s.elevation_deg},
                });
                if let Some(r) = rights.get(&s.name) {
                    v["clip_r"] = json!(r.to_string_lossy().to_string());
                    v["stereo"] = json!({"spacing_m": s.spacing_m});
                }
                v
            }).collect::<Vec<_>>(),
            "mics": self.mics.iter().map(|m| {
                let mut v = json!({
                    "name": m.name, "chain": m.chain, "set": m.set, "position_m": m.pos,
                    "aim": {"azimuth_deg": m.azimuth_deg, "elevation_deg": m.elevation_deg},
                    "pan": m.pan,
                });
                // (absent when off: scenes render as before)
                if let Some(h) = &m.hears {
                    let known: Vec<&String> =
                        h.iter().filter(|n| self.sources.iter().any(|s| &s.name == *n)).collect();
                    v["hears"] = json!(known);
                }
                if m.separate_passes {
                    v["passes"] = json!("separate");
                }
                if m.free_field {
                    v["free_field"] = json!(true);
                }
                v
            }).collect::<Vec<_>>(),
            "settings": {"quality": self.quality, "seed": 0,
                         "wave_crossover_hz": if self.wave_hz > 0.0 { json!(self.wave_hz) }
                                              else { Value::Null }},
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
        let n = self.plan.len();
        if n < 3 || polygon_area(&self.plan).abs() < 1.0 {
            out.push("the floor needs at least 3 corners and 1 m²".to_string());
        }
        let crossing = (0..n).any(|i| {
            (i + 2..n).any(|j| {
                (i + 1) % n != j
                    && (j + 1) % n != i
                    && segments_cross(
                        self.plan[i],
                        self.plan[(i + 1) % n],
                        self.plan[j],
                        self.plan[(j + 1) % n],
                    )
            })
        });
        if crossing {
            out.push("the floor plan's walls cross".to_string());
        }
        if self.roof.height < 1.5 || (self.roof.kind != "flat" && self.roof.peak < self.roof.height)
        {
            out.push("the ceiling needs 1.5 m, its peak at least its height".to_string());
        }
        let inside = |p: &[f64; 3]| self.inside(p);
        let mut names = std::collections::HashSet::new();
        for o in &self.objects {
            if o.size.iter().any(|x| *x <= 0.0) {
                out.push(format!("{} needs a size", o.name));
            }
            let in_room = o.corners().iter().all(|c| {
                in_polygon(&self.plan, c[0], c[1])
                    && c[2] >= -1e-9
                    && c[2] <= self.height_at(c[0], c[1]) + 1e-9
            });
            if !in_room {
                out.push(format!("{} sticks out of the room", o.name));
            }
            if !names.insert(o.name.clone()) {
                out.push(format!("two items are called {}", o.name));
            }
        }
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
            if !self.sources.is_empty() && !self.sources.iter().any(|s| m.hears_source(&s.name)) {
                out.push(format!("{} hears no source", m.name));
            }
            for s in &self.sources {
                let d: f64 = (0..3)
                    .map(|i| (m.pos[i] - s.pos[i]).powi(2))
                    .sum::<f64>()
                    .sqrt();
                if d < MIN_DISTANCE_M {
                    out.push(format!("{} is closer than 10 cm to {}", m.name, s.name));
                }
                let (c, r) = s.body();
                if r > 0.0 && dist3(&m.pos, &c) < r {
                    out.push(format!(
                        "{} is inside {}'s body (its cabinet / head)",
                        m.name, s.name
                    ));
                }
            }
        }
        out
    }

    /// A source's name changed from `old` to `new`: the mics that hear it by name follow.
    pub fn rename_source(&mut self, old: &str, new: &str) {
        if old == new {
            return;
        }
        for m in &mut self.mics {
            if let Some(h) = &mut m.hears {
                for n in h.iter_mut().filter(|n| *n == old) {
                    *n = new.to_string();
                }
            }
        }
    }

    /// Source i removed, and from every mic's `hears`.
    pub fn remove_source(&mut self, i: usize) {
        let s = self.sources.remove(i);
        for m in &mut self.mics {
            if let Some(h) = &mut m.hears {
                h.retain(|n| *n != s.name);
            }
        }
    }

    /// No room at all: every face anechoic and nothing standing in it (scene.py's
    /// `free_field_room`: every mic hears the direct sound alone).
    pub fn is_free_field(&self) -> bool {
        self.objects.is_empty()
            && [&self.walls, &self.floor, &self.ceiling]
                .into_iter()
                .chain(self.faces_in_room().values())
                .all(|m| m == "anechoic")
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

/// A source's stem in a scene's live balance (varimu/rooms/balance.py).
#[derive(Clone, Debug)]
pub struct BalanceSource {
    pub name: String,
    /// Its SPL when the stems were made: a fader at `spl_db` plays the stem as it is.
    pub spl_db: f64,
    pub left: PathBuf,
    pub right: PathBuf,
}

/// A scene's live balance (its balance.json): each source's stereo stem through the mics'
/// chains' linear proxies, panned as the mics are, and each mic's print's predicted peaks.
#[derive(Clone, Debug)]
pub struct Balance {
    pub sources: Vec<BalanceSource>,
    pub mics: Vec<String>,
    /// (sources, mics, blocks): a mic's print's peak per block from that source alone at its
    /// prepared SPL, linear re full scale.
    pub peaks: Vec<Vec<Vec<f32>>>,
}

pub fn read_balance(dir: &Path) -> Result<Balance, String> {
    let path = dir.join("balance.json");
    let text = std::fs::read_to_string(&path).map_err(|e| format!("{}: {e}", path.display()))?;
    let v: Value = serde_json::from_str(&text).map_err(|e| e.to_string())?;
    let sources = v["sources"]
        .as_array()
        .ok_or("balance.json has no sources")?
        .iter()
        .map(|s| BalanceSource {
            name: st(s, "name", ""),
            spl_db: f(s, "spl_db", 90.0),
            left: dir.join(st(s, "left", "")),
            right: dir.join(st(s, "right", "")),
        })
        .collect();
    let mics = v["mics"]
        .as_array()
        .ok_or("balance.json has no mics")?
        .iter()
        .map(|m| st(m, "name", "mic"))
        .collect();
    let num = |x: &Value| x.as_f64().unwrap_or(0.0) as f32;
    let peaks = v["peaks"]
        .as_array()
        .ok_or("balance.json has no peaks")?
        .iter()
        .map(|ps| {
            ps.as_array()
                .map(|pm| {
                    pm.iter()
                        .map(|b| {
                            b.as_array()
                                .map_or(Vec::new(), |b| b.iter().map(num).collect())
                        })
                        .collect()
                })
                .unwrap_or_default()
        })
        .collect();
    Ok(Balance {
        sources,
        mics,
        peaks,
    })
}

/// Each mic's print's predicted peak (dBFS) at the sources' gains (linear, re their prepared
/// SPLs): per block the sum of the sources' peaks there, a bound (their waveforms may not
/// line up), the loudest block. It is the proxies' prediction: a chain saturates as it
/// nears its full scale, which the proxies don't.
pub fn balance_peak_dbfs(peaks: &[Vec<Vec<f32>>], gains: &[f64]) -> Vec<f64> {
    let mics = peaks.first().map_or(0, Vec::len);
    (0..mics)
        .map(|m| {
            let blocks = peaks.iter().map(|p| p[m].len()).max().unwrap_or(0);
            let top = (0..blocks)
                .map(|b| {
                    peaks
                        .iter()
                        .zip(gains)
                        .map(|(p, g)| g * p[m].get(b).copied().unwrap_or(0.0) as f64)
                        .sum::<f64>()
                })
                .fold(0.0, f64::max);
            20.0 * top.max(1e-12).log10()
        })
        .collect()
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
        RenderJob::spawn_with(repo, scene, out_dir, &[])
    }

    /// The same with more arguments (`--balance`: the scene's live balance, `read_balance`).
    pub fn spawn_with(
        repo: &Path,
        scene: &Path,
        out_dir: &Path,
        args: &[&str],
    ) -> Result<RenderJob, String> {
        let mut cmd = Command::new("uv");
        cmd.current_dir(repo)
            .args(["run", "--extra", "fast", "python", "scripts/room_print.py"])
            .arg(scene)
            .arg("--out")
            .arg(out_dir)
            .args(args)
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
        Some(self.finished()?.and_then(|()| read_render(&self.out_dir)))
    }

    /// None while it runs; then whether it succeeded (its output in `out_dir`).
    pub fn finished(&mut self) -> Option<Result<(), String>> {
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
        Some(Ok(()))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn scene() -> Scene {
        let mut s = Scene::default();
        s.sources
            .push(RoomSource::new("A", "k1", 90.0, [2.0, 2.5, 1.3]));
        let mut m = RoomMic::new("Mic 1", "u47_v76", [2.3, 2.5, 1.3], 0.0);
        m.aim_at(2.0, 2.5);
        s.mics.push(m);
        s
    }

    #[test]
    fn sounding_rms_matches_python() {
        // tests/test_room_balance.py's test_sounding_rms_matches_the_apps
        let fs = 48000u32;
        let mut x: Vec<f32> = (0..3 * fs as usize)
            .map(|i| {
                let t = i as f64 / fs as f64;
                if t < 1.0 {
                    0.0
                } else {
                    (0.5 * (2.0 * std::f64::consts::PI * 220.0 * t).sin()) as f32
                }
            })
            .collect();
        for v in &mut x[(2.5 * fs as f64) as usize..] {
            *v *= 0.01;
        }
        // Python's is on float64 samples, these are f32: ~1e-8 apart
        assert!((sounding_rms(&x, fs) - 0.350_643_583).abs() < 1e-6);
        assert_eq!(sounding_rms(&[], fs), 0.0);
        assert_eq!(sounding_rms(&vec![0.0; 9600], fs), 0.0);
        assert!((sounding_rms(&[0.5, -0.5], fs) - 0.5).abs() < 1e-12);
    }

    #[test]
    fn balance_reads_and_meters() {
        let dir = std::env::temp_dir().join(format!("varimu_balance_{}", std::process::id()));
        std::fs::create_dir_all(&dir).unwrap();
        // two sources, one mic, three blocks (varimu/rooms/balance.py's balance.json)
        let v = json!({
            "fs": 96000, "seconds": 0.15, "peaks_block_s": 0.05,
            "sources": [
                {"name": "a", "spl_db": 90.0, "left": "a.L.wav", "right": "a.R.wav"},
                {"name": "b", "spl_db": 85.0, "left": "b.L.wav", "right": "b.R.wav"},
            ],
            "mics": [{"name": "m", "chain": "omni_clean", "pan": 0.0}],
            "peaks": [[[0.1, 0.5, 0.0]], [[0.4, 0.1, 0.0]]],
        });
        std::fs::write(dir.join("balance.json"), v.to_string()).unwrap();
        let b = read_balance(&dir).unwrap();
        assert_eq!(b.sources[1].name, "b");
        assert_eq!(b.sources[1].spl_db, 85.0);
        assert_eq!(b.sources[0].left, dir.join("a.L.wav"));
        assert_eq!(b.mics, vec!["m".to_string()]);
        // as prepared: the louder block is 0.1 + 0.4 or 0.5 + 0.1 -> 0.6
        let at = |g: &[f64]| balance_peak_dbfs(&b.peaks, g)[0];
        assert!((at(&[1.0, 1.0]) - 20.0 * 0.6f64.log10()).abs() < 1e-6);
        // b up 2x: 0.1 + 0.8
        assert!((at(&[1.0, 2.0]) - 20.0 * 0.9f64.log10()).abs() < 1e-6);
        std::fs::remove_dir_all(&dir).unwrap();
    }

    #[test]
    fn levels_from_the_mix() {
        // vocal loudest in the mix (-12 + 0), guitar 4 dB under it, bass muted
        let mix = [Some(-12.0), Some(-20.0 + 4.0), None];
        let spl = [80.0, 90.0, 95.0];
        // the loudest in the mix gets the highest SPL among the balanced: 90
        assert_eq!(levels_from_mix(&mix, &spl), vec![90.0, 86.0, 95.0]);
        assert_eq!(
            levels_from_mix(&[None, None], &[80.0, 70.0]),
            vec![80.0, 70.0]
        );
        assert_eq!(
            levels_from_mix(&[Some(0.0), Some(-80.0)], &[120.0, 90.0]),
            vec![120.0, 40.0]
        );
    }

    #[test]
    fn state_round_trips() {
        let s = scene();
        assert_eq!(Scene::from_state(&s.state()), s);
        let mut g = scene();
        g.mics[0].hears = Some(vec!["A".to_string()]);
        g.mics[0].separate_passes = true;
        g.mics[0].free_field = true;
        assert_eq!(Scene::from_state(&g.state()), g);
    }

    /// A mic's hears / passes / free field (2026-11-09): in the render's scene only when on,
    /// following renames and deletes, a mic hearing nothing a problem.
    #[test]
    fn hears_follows_the_sources() {
        let mut s = scene();
        s.sources
            .push(RoomSource::new("B", "k2", 90.0, [4.0, 2.5, 1.3]));
        let json = s.render_json(&BTreeMap::new());
        let m = &json["mics"][0];
        assert!(m.get("hears").is_none() && m.get("passes").is_none());
        assert!(m.get("free_field").is_none());
        s.mics[0].hears = Some(vec!["A".to_string(), "gone".to_string()]);
        s.mics[0].separate_passes = true;
        s.mics[0].free_field = true;
        let m = &s.render_json(&BTreeMap::new())["mics"][0];
        assert_eq!(m["hears"], json!(["A"]));
        assert_eq!(
            (m["passes"].as_str(), m["free_field"].as_bool()),
            (Some("separate"), Some(true))
        );
        assert!(s.mics[0].hears_source("A") && !s.mics[0].hears_source("B"));
        s.sources[0].name = "Kick".to_string(); // (the Room view's name field)
        s.rename_source("A", "Kick");
        assert!(s.mics[0].hears_source("Kick") && !s.mics[0].hears_source("A"));
        assert!(!s.problems().iter().any(|p| p.contains("hears no source")));
        s.remove_source(0);
        assert_eq!(s.sources.len(), 1);
        assert!(s.problems().iter().any(|p| p == "Mic 1 hears no source"));
        s.mics[0].hears = None;
        assert!(!s.problems().iter().any(|p| p.contains("hears no source")));
    }

    #[test]
    fn the_anechoic_preset_is_a_free_field() {
        let config = Path::new(env!("CARGO_MANIFEST_DIR")).join("../../config");
        let (presets, errors) = load_presets(&config);
        assert!(errors.is_empty(), "{errors:?}");
        let p = presets.iter().find(|p| p.name == "anechoic").unwrap();
        let mut s = scene();
        assert!(!s.is_free_field());
        s.apply_room_preset(p);
        assert!(s.is_free_field());
        s.faces.insert("wall 0".to_string(), "brick".to_string());
        assert!(!s.is_free_field());
    }

    /// The list as varimu/chains.py reads it (tests/test_chain_matrix.py checks the same
    /// chains there): the composed chains offered, labels, defaults, patterns.
    #[test]
    fn chain_list_reads() {
        let config = Path::new(env!("CARGO_MANIFEST_DIR")).join("../../config");
        let list = load_chains(&config).unwrap();
        for c in &list {
            assert!(
                config
                    .join("circuits")
                    .join(format!("{}.yaml", c.id))
                    .is_file()
            );
            assert!(!c.use_note.is_empty(), "{}", c.id);
        }
        let ids: Vec<&str> = list.iter().map(|c| c.id.as_str()).collect();
        for id in [
            "u47_v76",
            "u47_clean",
            "sm57_v76",
            "sm58_clean",
            "omni_v76",
            "omni_clean",
        ] {
            assert!(ids.contains(&id), "{id}");
        }
        assert!(!ids.contains(&"r121_api312")); // not built: not offered
        assert!(ids.contains(&"c4038_v72")); // the 4038 (WP8)
        let r = list.iter().find(|c| c.id == "r44_v76").unwrap(); // a ribbon (WP6)
        assert_eq!(r.pattern(&BTreeMap::new()), Pattern::FIGURE8);
        // The 77-DX's shutter (WP7): U by default, B a figure-8, N an omni.
        let r77 = list.iter().find(|c| c.id == "r77_a351").unwrap();
        assert_eq!(r77.pattern(&BTreeMap::new()), Pattern::CARDIOID);
        let at = |k: f64| BTreeMap::from([("pattern_r77".to_string(), k)]);
        assert_eq!(r77.pattern(&at(5.0)), Pattern::FIGURE8);
        assert_eq!(r77.pattern(&at(0.0)), Pattern::OMNI);
        let c = list.iter().find(|c| c.id == "sm57_v76").unwrap();
        assert_eq!(c.label, "SM57 → V76");
        let keys: Vec<(&str, f64)> = c
            .settings
            .iter()
            .map(|s| (s.key.as_str(), s.default))
            .collect();
        assert_eq!(keys, [("impedance_sm57", 0.0), ("gain_db_v76", 58.0)]);
        assert_eq!(c.pattern(&BTreeMap::new()), Pattern::CARDIOID);
        let o = list.iter().find(|c| c.id == "omni_clean").unwrap();
        assert_eq!(o.pattern(&BTreeMap::new()), Pattern::OMNI);
        assert_eq!(o.settings[0].choices[2], (40.0, "40 dB".to_string()));
        // The C12's nine positions draw as first-order figures, omni to figure-8.
        let c12 = list.iter().find(|c| c.id == "c12_ua610").unwrap();
        assert_eq!(c12.pattern(&BTreeMap::new()), Pattern::CARDIOID);
        for (k, eighths) in [(0.0, 8), (6.0, 2), (8.0, 0)] {
            let set = BTreeMap::from([("pattern_c12".to_string(), k)]);
            assert_eq!(c12.pattern(&set), Pattern(eighths));
        }
        assert!((Pattern::FIGURE8.gain(std::f32::consts::PI) + 1.0).abs() < 1e-6);
        assert!(Pattern::CARDIOID.gain(std::f32::consts::PI).abs() < 1e-6);
    }

    #[test]
    fn aim_and_pattern() {
        let s = scene();
        assert!((s.mics[0].azimuth_deg - 180.0).abs() < 1e-9);
        assert_eq!(s.mics[0].pattern(), Pattern::CARDIOID);
        assert_eq!(s.mics[0].set["gain_db_v76"], 34.0);
        let mut m = s.mics[0].clone();
        m.set.insert("pattern_u47".into(), 1.0);
        assert_eq!(m.pattern(), Pattern::OMNI);
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
    fn shapes_and_ceilings() {
        let mut s = scene();
        assert!((s.height_at(3.0, 2.0) - 3.2).abs() < 1e-12);
        s.roof = Ceiling {
            kind: "gable".into(),
            height: 2.8,
            peak: 4.6,
            ..Ceiling::default()
        };
        assert!((s.height_at(0.0, 1.0) - 2.8).abs() < 1e-9);
        assert!((s.height_at(3.5, 1.0) - 4.6).abs() < 1e-9);
        assert!(s.inside(&[3.5, 1.0, 4.0]) && !s.inside(&[0.5, 1.0, 4.0]));
        s.set_preset("L-shape", 8.0, 8.0);
        assert!(s.inside(&[1.0, 7.0, 1.0]) && !s.inside(&[7.0, 7.0, 1.0]));
        let old = json!({"name": "x", "dims_m": [5.0, 4.0, 2.6]});
        let o = Scene::from_state(&old);
        assert_eq!(o.plan.len(), 4);
        assert_eq!(o.roof.height, 2.6);
        let mut bad = scene();
        bad.plan = vec![[0.0, 0.0], [4.0, 4.0], [4.0, 0.0], [0.0, 4.0]];
        assert!(bad.problems().iter().any(|p| p.contains("cross")));
    }

    #[test]
    fn a_stereo_source_is_a_pair_in_the_scene() {
        // docs/STEREO_PLAN.md ST4-ST5: a right channel makes it a pair, its speakers across
        // its facing direction, its left on the left as its player sees it.
        let mut s = scene();
        s.sources[0].azimuth_deg = 90.0; // facing +y: its left is -x
        s.sources[0].spacing_m = 0.6;
        let [l, r] = s.sources[0].sides();
        let p = s.sources[0].pos;
        assert!((l[0] - (p[0] - 0.3)).abs() < 1e-12 && (r[0] - (p[0] + 0.3)).abs() < 1e-12);
        assert!((l[1] - p[1]).abs() < 1e-12 && l[2] == p[2]);
        let clips = BTreeMap::from([("A".to_string(), PathBuf::from("a.L.wav"))]);
        let rights = BTreeMap::from([("A".to_string(), PathBuf::from("a.R.wav"))]);
        let v = s.render_json_lr(&clips, &rights);
        let src = &v["sources"][0];
        assert_eq!(
            (src["clip"].as_str(), src["clip_r"].as_str()),
            (Some("a.L.wav"), Some("a.R.wav"))
        );
        assert_eq!(src["stereo"]["spacing_m"], 0.6);
        // mono: as before
        let m = s.render_json(&clips);
        assert!(m["sources"][0].get("clip_r").is_none() && m["sources"][0].get("stereo").is_none());
        // kept in the session's scene
        s.sources[0].as_mono = true;
        let back = Scene::from_state(&s.state());
        assert_eq!(
            (back.sources[0].spacing_m, back.sources[0].as_mono),
            (0.6, true)
        );
        assert_eq!(default_spacing_m("rhodes_suitcase"), 0.6);
        assert_eq!(default_spacing_m("anything"), DEFAULT_SPACING_M);
    }

    #[test]
    fn render_json_is_the_python_format() {
        let s = scene();
        let clips = BTreeMap::from([("A".to_string(), PathBuf::from("a.wav"))]);
        let v = s.render_json(&clips);
        assert_eq!(v["sources"][0]["clip"], "a.wav");
        assert_eq!(v["room"]["materials"]["walls"], "furnished_wall");
        assert_eq!(v["room"]["floor_m"][2][0], 7.0);
        assert_eq!(v["room"]["ceiling"]["type"], "flat");
        assert_eq!(v["mics"][0]["aim"]["azimuth_deg"], 180.0);
        assert_eq!(v["mics"][0]["set"]["pattern_u47"], 0.0);
        assert_eq!(v["sources"][0]["directivity"], "omni");
        let mut d = s.clone();
        d.sources[0].directivity = "amp_1x12".into();
        d.sources[0].aim_at(2.0, 4.5);
        assert!((d.sources[0].azimuth_deg - 90.0).abs() < 1e-9);
        assert_eq!(Scene::from_state(&d.state()), d);
        assert_eq!(
            d.render_json(&clips)["sources"][0]["aim"]["azimuth_deg"],
            90.0
        );
        // a mic beside the cabinet, inside its body
        d.mics[0].pos = [2.0, 2.35, 1.3];
        assert!(d.problems().iter().any(|p| p.contains("inside A's body")));
        assert!(v["room"]["materials"].get("faces").is_none());
        assert_eq!(v["settings"]["wave_crossover_hz"], 500.0);
        let old = Scene::from_state(&json!({"name": "x", "dims_m": [5.0, 4.0, 2.6]}));
        assert_eq!(old.wave_hz, 0.0);
        assert!(old.render_json(&clips)["settings"]["wave_crossover_hz"].is_null());
    }

    #[test]
    fn objects_round_trip_and_keep_things_out() {
        let mut s = scene();
        let (_, prefix, size, z, mat, _) = OBJECT_KINDS[0];
        s.objects.push(RoomObject {
            name: format!("{prefix} 1"),
            center: [3.5, 2.5, z],
            size,
            yaw_deg: 90.0,
            tilt_deg: 0.0,
            material: mat.to_string(),
        });
        assert_eq!(Scene::from_state(&s.state()), s);
        assert!(!s.inside(&[3.5, 2.5, 1.0]) && s.inside(&[3.5, 3.5, 1.0]));
        let fp = s.objects[0].footprint();
        assert_eq!(fp.len(), 4);
        let xs: Vec<f64> = fp.iter().map(|p| p[0]).collect();
        let w = xs.iter().cloned().fold(f64::MIN, f64::max)
            - xs.iter().cloned().fold(f64::MAX, f64::min);
        assert!(
            (w - 0.08).abs() < 1e-9,
            "turned 90 degrees, its thickness lies along x"
        );
        let v = s.render_json(&BTreeMap::new());
        assert_eq!(v["room"]["objects"][0]["size_m"][1], 0.08);
        assert!(s.problems().is_empty(), "{:?}", s.problems());
        s.objects[0].center[2] = 3.0;
        assert!(s.problems().iter().any(|p| p.contains("sticks out")));
    }

    #[test]
    fn faces_follow_corner_edits() {
        let mut s = scene();
        s.set_face_material("wall 1", Some("heavy_drapes".into()));
        s.set_face_material("wall 3", Some("plaster".into()));
        s.set_face_material("ceiling 0", Some("acoustic_tile".into()));
        assert_eq!(s.face_material("wall 1"), "heavy_drapes");
        assert_eq!(s.face_material("wall 2"), "furnished_wall");
        assert_eq!(Scene::from_state(&s.state()), s);
        s.insert_corner(1, [7.0, 2.0]); // wall 1 split in two
        assert_eq!(s.face_material("wall 1"), "heavy_drapes");
        assert_eq!(s.face_material("wall 2"), "heavy_drapes");
        assert_eq!(s.face_material("wall 4"), "plaster");
        s.remove_corner(2); // the two halves merge again
        assert_eq!(s.plan.len(), 4);
        assert_eq!(s.face_material("wall 1"), "heavy_drapes");
        assert_eq!(s.face_material("wall 3"), "plaster");
        s.remove_corner(0); // walls 3 and 0 meet at corner 0: wall 3 (now 2) stays
        assert_eq!(s.face_material("wall 2"), "plaster");
        assert_eq!(s.face_material("wall 0"), "heavy_drapes");
        let v = s.render_json(&BTreeMap::new());
        assert_eq!(
            v["room"]["materials"]["faces"]["ceiling 0"],
            "acoustic_tile"
        );
        s.set_preset("shoebox", 7.0, 5.5);
        assert_eq!(s.faces.len(), 1);
    }

    #[test]
    fn room_presets_load_and_render_as_written() {
        let config = Path::new(env!("CARGO_MANIFEST_DIR")).join("../../config");
        let (presets, errors) = load_presets(&config);
        assert!(errors.is_empty(), "{errors:?}");
        assert!(presets.len() >= 10);
        assert!(presets.iter().any(|p| p.name == "treated_studio"));
        for p in &presets {
            let mut s = scene(); // its source and mic move with the room
            s.apply_room_preset(p);
            assert_eq!(s.shape, "custom");
            let problems: Vec<_> = s
                .problems()
                .into_iter()
                .filter(|e| !e.contains("has no track") && !e.contains("outside the room"))
                .collect();
            assert!(problems.is_empty(), "{}: {problems:?}", p.name);
            for m in [&s.walls, &s.floor, &s.ceiling]
                .into_iter()
                .chain(s.faces.values())
                .chain(s.objects.iter().map(|o| &o.material))
            {
                assert!(MATERIALS.contains(&m.as_str()), "{}: {m}", p.name);
            }
            let v = s.render_json(&BTreeMap::new());
            assert_eq!(v["room"]["floor_m"], p.room["floor_m"], "{}", p.name);
            let faces = &p.room["materials"]["faces"];
            if faces.is_object() {
                assert_eq!(&v["room"]["materials"]["faces"], faces, "{}", p.name);
            }
            assert_eq!(
                v["room"]["objects"].as_array().map_or(0, Vec::len),
                p.room["objects"].as_array().map_or(0, Vec::len)
            );
            assert_eq!(Scene::from_state(&s.state()), s);
        }
    }
}
