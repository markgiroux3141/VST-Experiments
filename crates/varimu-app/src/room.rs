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
    /// Its rms in dB SPL 1 m away in free field (on its axis).
    pub spl_db: f64,
    pub pos: [f64; 3],
    /// How it radiates (`DIRECTIVITIES`: varimu/rooms/directivity.py's presets).
    pub directivity: String,
    /// Where it faces: counterclockwise from +x, and up.
    pub azimuth_deg: f64,
    pub elevation_deg: f64,
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
        }
    }

    pub fn directional(&self) -> bool {
        self.directivity != "omni"
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

/// The objects offered: (label, name prefix, size, centre height, surface).
pub const OBJECT_KINDS: &[(&str, &str, [f64; 3], f64, &str)] = &[
    ("Gobo", "Gobo", [1.2, 0.08, 1.8], 0.9, "heavy_drapes"),
    ("Riser", "Riser", [1.8, 1.2, 0.3], 0.15, "wood_floor"),
    (
        "Cabinet",
        "Cabinet",
        [0.6, 0.45, 1.0],
        0.5,
        "gypsum_on_studs",
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
                "elevation_deg": s.elevation_deg,
            })).collect::<Vec<_>>(),
            "mics": self.mics.iter().map(|m| json!({
                "name": m.name, "chain": m.chain, "set": m.set, "position_m": m.pos,
                "azimuth_deg": m.azimuth_deg, "elevation_deg": m.elevation_deg, "pan": m.pan,
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
            "sources": self.sources.iter().map(|s| json!({
                "name": s.name,
                "clip": clips.get(&s.name).map(|p| p.to_string_lossy().to_string()),
                "spl_db": s.spl_db,
                "position_m": s.pos,
                "directivity": s.directivity,
                "aim": {"azimuth_deg": s.azimuth_deg, "elevation_deg": s.elevation_deg},
            })).collect::<Vec<_>>(),
            "mics": self.mics.iter().map(|m| json!({
                "name": m.name, "chain": m.chain, "set": m.set, "position_m": m.pos,
                "aim": {"azimuth_deg": m.azimuth_deg, "elevation_deg": m.elevation_deg},
                "pan": m.pan,
            })).collect::<Vec<_>>(),
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
        s.sources
            .push(RoomSource::new("A", "k1", 90.0, [2.0, 2.5, 1.3]));
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
        let (_, prefix, size, z, mat) = OBJECT_KINDS[0];
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
}
