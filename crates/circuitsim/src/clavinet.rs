//! The Hohner Clavinet D6's strings as a medium (docs/CLAVINET_PLAN.md, CL3): every key's
//! string, struck, held and released by note events, read by the two bar pickups; their
//! EMFs (each pickup's strings' summed: the coils are in series) drive the circuit's
//! pickup nodes. `varimu/clavinet/live.py` is the reference this ports, sample for sample
//! (its docstring has the algorithm); the model is a component version of kind
//! `clav_strings` compiled by `varimu/clavinet/compile.py` (its docstring has the data).
//!
//! **A voice** is one key in one of three phases: free (the released system's modes
//! rotating), contact (the strike or the release: the released modes stepped in substeps
//! with the tangent's rubber and the anvil solved inside each, a first-order hold), or
//! held (the held system's modes about the static press). The switches between them are
//! the compiled transfers `z_new = A z + B conj(z) + ...`. Aftertouch ([`NoteEvent::Pressure`])
//! scales the held modes' frequencies by the key's bend table.
//!
//! **Rates.** The voices run at `k` internal samples per step (the least whole multiple of
//! the step rate at or above the element's `rate_hz`), the contacts at `s` substeps of
//! those (`contact_rate_hz`); [`crate::keyed`] renders them ahead and decimates.
//!
//! **The data** lives in two files the IR names (the header JSON, by its path relative to
//! the repository's root, and its float64 sidecar); they are loaded once per process and
//! shared ([`load`]).

use std::collections::HashMap;
use std::path::{Path, PathBuf};
use std::sync::{Arc, Mutex, OnceLock};

use serde::Deserialize;

use crate::harp::{C64, phi12};
use crate::media::NoteEvent;

/// Internal samples between a free or held voice's sleep checks.
const SLEEP_EVERY: usize = 1024;
/// A mode under this (|re| and |im|) at a sleep check is zeroed (subnormals are slow).
const MODE_FLOOR: f64 = 1e-100;
/// Lanes of the modal loops (the modes are padded to a multiple).
const LANES: usize = 4;
/// The format of the compiled data this code reads.
pub const FORMAT: usize = 1;

// --- The model -------------------------------------------------------------------

#[derive(Debug, Clone, Deserialize)]
struct Velocity {
    lo_m_s: f64,
    hi_m_s: f64,
}

#[derive(Debug, Clone, Deserialize)]
struct Pressure {
    max_force_n: f64,
}

/// The contacts' numerics: the strike's window and settle rule, the release's open rule.
#[derive(Debug, Clone, Deserialize)]
struct Numerics {
    strike_window_s: f64,
    settle_s: f64,
    open_window_s: f64,
    open_s: f64,
    max_s: f64,
}

#[derive(Debug, Clone, Deserialize)]
struct Binary {
    sha256: String,
    bytes: usize,
}

#[derive(Debug, Clone, Deserialize)]
struct Contact {
    tangent_mass_kg: f64,
    travel_m: f64,
    hold_force_n: f64,
    return_force_n: f64,
    rubber_k: f64,
    rubber_p: f64,
    rubber_alpha_s_m: f64,
    anvil_k_n_m: f64,
    anvil_c_ns_m: f64,
    anvil_gap_m: f64,
    tilt_rad: f64,
    grip_k_n_m: f64,
    grip_c_ns_m: f64,
}

#[derive(Debug, Clone, Deserialize)]
struct PickupHeader {
    sgn: f64,
    clearance_m: f64,
    h_lo_m: f64,
    h_hi_m: f64,
    dmax_dh: f64,
}

#[derive(Debug, Clone, Deserialize)]
struct Pickups {
    centre: PickupHeader,
    bridge: PickupHeader,
}

#[derive(Debug, Clone, Deserialize)]
struct Statics {
    centre: f64,
    bridge: f64,
}

#[derive(Debug, Clone, Deserialize)]
struct Bend {
    forces_n: Vec<f64>,
    cents: Vec<f64>,
}

/// An array in the sidecar: its byte offset, shape, whether complex (its real part then
/// its imaginary part) and its type ("f4" or "f8", little-endian).
#[derive(Debug, Clone, Deserialize)]
struct Place {
    at: usize,
    shape: Vec<usize>,
    complex: bool,
    dtype: String,
}

#[derive(Debug, Clone, Deserialize)]
struct KeyHeader {
    key: usize,
    note: usize,
    contact: Contact,
    static_y_m: Statics,
    static_tangent_m: f64,
    bend: Bend,
    pickups: Pickups,
    arrays: HashMap<String, Place>,
}

#[derive(Debug, Clone, Deserialize)]
struct Header {
    format: usize,
    velocity: Velocity,
    pressure: Pressure,
    contact: Numerics,
    sleep_v: f64,
    table_points: usize,
    keys: Vec<KeyHeader>,
    binary: Binary,
}

/// A pickup's EMF table over the string's height (see `compile.py`).
#[derive(Debug, Clone)]
struct Table {
    sgn: f64,
    clearance: f64,
    lo: f64,
    hi: f64,
    step: f64,
    dmax: f64,
    dh: Vec<f64>,
}

impl Table {
    /// -dL/dh(h) sgn vy at the string's height y (static included) and velocity vy.
    #[inline(always)]
    fn emf(&self, y: f64, vy: f64) -> f64 {
        let h = (self.clearance + self.sgn * y).clamp(self.lo, self.hi);
        let u = (h - self.lo) / self.step;
        let i = (u.floor() as usize).min(self.dh.len() - 2);
        let f = u - i as f64;
        let d = self.dh[i] + f * (self.dh[i + 1] - self.dh[i]);
        -(d * self.sgn * vy)
    }
}

/// One key's compiled data.
#[derive(Debug, Clone)]
pub struct ClavKey {
    pub key: usize,
    pub note: u8,
    contact: Contact,
    static_y: [f64; 2],
    static_tangent: f64,
    bend_f: Vec<f64>,
    bend_c: Vec<f64>,
    tables: [Table; 2],
    lam_r: Vec<C64>,
    b_y: Vec<C64>,
    b_x: Vec<C64>,
    /// anvil y, x, vy, vx; centre y, vy; bridge y, vy (8 x m_r).
    r_rows: Vec<Vec<C64>>,
    lam_h: Vec<C64>,
    /// centre y, vy; bridge y, vy (4 x m_h).
    h_rows: Vec<Vec<C64>>,
    /// The tangent's position and velocity (2 x m_h).
    t_rows: Vec<Vec<C64>>,
    th_a: Vec<C64>,
    th_b: Vec<C64>,
    th_z: Vec<C64>,
    th_v: Vec<C64>,
    th_c: Vec<C64>,
    rr_a: Vec<C64>,
    rr_b: Vec<C64>,
    rr_c: Vec<C64>,
}

impl ClavKey {
    /// Released and held modes.
    pub fn modes(&self) -> (usize, usize) {
        (self.lam_r.len(), self.lam_h.len())
    }
}

/// The compiled strings (a component version of kind `clav_strings`).
#[derive(Debug)]
pub struct ClavModel {
    pub keys: Vec<ClavKey>,
    velocity: Velocity,
    max_force: f64,
    num: Numerics,
    sleep_v: f64,
    /// The sidecar's sha256 (as the header names it).
    pub sha256: String,
}

impl ClavModel {
    /// The tangent's speed for MIDI velocity `vel` ([G13] 3.2: linear over 1-127).
    pub fn speed(&self, vel: u8) -> f64 {
        let v = &self.velocity;
        let vel = vel.clamp(1, 127) as f64;
        v.lo_m_s + (v.hi_m_s - v.lo_m_s) * (vel - 1.0) / 126.0
    }

    /// The data from its header file `path` (the sidecar beside it, as the header names
    /// it), its sidecar's sha256 checked against `sha256` as the header records it.
    pub fn read(path: &Path) -> Result<ClavModel, String> {
        let text = std::fs::read_to_string(path)
            .map_err(|e| format!("the Clavinet's strings {}: {e}", path.display()))?;
        let header: Header = serde_json::from_str(&text)
            .map_err(|e| format!("the Clavinet's strings {}: {e}", path.display()))?;
        if header.format != FORMAT {
            return Err(format!(
                "the Clavinet's strings: format {} (this code reads {FORMAT})",
                header.format
            ));
        }
        let raw: serde_json::Value = serde_json::from_str(&text).map_err(|e| e.to_string())?;
        let file = raw["binary"]["file"]
            .as_str()
            .ok_or("the Clavinet's strings: no sidecar named")?;
        let bin_path = path.with_file_name(file);
        let bytes = std::fs::read(&bin_path)
            .map_err(|e| format!("the Clavinet's strings {}: {e}", bin_path.display()))?;
        if bytes.len() != header.binary.bytes {
            return Err(format!(
                "the Clavinet's strings {}: {} bytes, the header says {}",
                bin_path.display(),
                bytes.len(),
                header.binary.bytes
            ));
        }
        let keys = header
            .keys
            .iter()
            .map(|k| key_data(k, &bytes, header.table_points))
            .collect::<Result<Vec<_>, String>>()?;
        let mut seen = [false; 128];
        for k in &keys {
            if std::mem::replace(&mut seen[k.note as usize], true) {
                return Err(format!("the Clavinet's strings: note {} twice", k.note));
            }
        }
        Ok(ClavModel {
            keys,
            velocity: header.velocity,
            max_force: header.pressure.max_force_n,
            num: header.contact,
            sleep_v: header.sleep_v,
            sha256: header.binary.sha256,
        })
    }
}

fn key_data(k: &KeyHeader, bytes: &[u8], points: usize) -> Result<ClavKey, String> {
    let at = |name: &str| -> Result<(Vec<usize>, Vec<C64>), String> {
        let p = k
            .arrays
            .get(name)
            .ok_or(format!("key {}: no array {name}", k.key))?;
        let size: usize = p.shape.iter().product();
        let width = match p.dtype.as_str() {
            "f4" => 4,
            "f8" => 8,
            d => return Err(format!("key {}: {name} of type {d}", k.key)),
        };
        let end = p.at + size * width * if p.complex { 2 } else { 1 };
        if end > bytes.len() {
            return Err(format!("key {}: {name} runs past the sidecar", k.key));
        }
        let get = |i: usize| -> f64 {
            let o = p.at + i * width;
            if width == 4 {
                f32::from_le_bytes(bytes[o..o + 4].try_into().expect("4 bytes")) as f64
            } else {
                f64::from_le_bytes(bytes[o..o + 8].try_into().expect("8 bytes"))
            }
        };
        let v = (0..size)
            .map(|i| {
                let im = if p.complex { get(size + i) } else { 0.0 };
                C64(get(i), im)
            })
            .collect::<Vec<_>>();
        if v.iter().any(|c| !(c.0.is_finite() && c.1.is_finite())) {
            return Err(format!("key {}: {name} isn't finite", k.key));
        }
        Ok((p.shape.clone(), v))
    };
    let vec = |name: &str, n: usize| -> Result<Vec<C64>, String> {
        let (shape, v) = at(name)?;
        if shape != [n] {
            return Err(format!("key {}: {name} is {shape:?}, not [{n}]", k.key));
        }
        Ok(v)
    };
    let mat = |name: &str, r: usize, c: usize| -> Result<Vec<C64>, String> {
        let (shape, v) = at(name)?;
        if shape != [r, c] {
            return Err(format!(
                "key {}: {name} is {shape:?}, not [{r}, {c}]",
                k.key
            ));
        }
        Ok(v)
    };
    let rows =
        |v: Vec<C64>, c: usize| -> Vec<Vec<C64>> { v.chunks(c).map(<[C64]>::to_vec).collect() };
    let (_, lam_r) = at("released.lam")?;
    let (_, lam_h) = at("held.lam")?;
    let (mr, mh) = (lam_r.len(), lam_h.len());
    if lam_r.iter().chain(&lam_h).any(|l| l.0 > 0.0) {
        return Err(format!("key {}: a mode grows", k.key));
    }
    let table = |name: &str, p: &PickupHeader| -> Result<Table, String> {
        let dh: Vec<f64> = vec(name, points)?.iter().map(|c| c.0).collect();
        if points < 2 || p.h_hi_m.partial_cmp(&p.h_lo_m) != Some(std::cmp::Ordering::Greater) {
            return Err(format!("key {}: {name}'s range", k.key));
        }
        Ok(Table {
            sgn: p.sgn,
            clearance: p.clearance_m,
            lo: p.h_lo_m,
            hi: p.h_hi_m,
            step: (p.h_hi_m - p.h_lo_m) / (points - 1) as f64,
            dmax: p.dmax_dh,
            dh,
        })
    };
    let b = &k.bend;
    if b.forces_n.len() < 2
        || b.forces_n.len() != b.cents.len()
        || b.forces_n.windows(2).any(|w| w[1] <= w[0])
    {
        return Err(format!("key {}: the bend table", k.key));
    }
    if k.note >= 128 {
        return Err(format!("key {}: note {}", k.key, k.note));
    }
    Ok(ClavKey {
        key: k.key,
        note: k.note as u8,
        contact: k.contact.clone(),
        static_y: [k.static_y_m.centre, k.static_y_m.bridge],
        static_tangent: k.static_tangent_m,
        bend_f: b.forces_n.clone(),
        bend_c: b.cents.clone(),
        tables: [
            table("tables.centre.dh", &k.pickups.centre)?,
            table("tables.bridge.dh", &k.pickups.bridge)?,
        ],
        b_y: vec("released.b_y", mr)?,
        b_x: vec("released.b_x", mr)?,
        r_rows: rows(mat("released.rows", 8, mr)?, mr),
        h_rows: rows(mat("held.rows", 4, mh)?, mh),
        t_rows: rows(mat("held.tangent", 2, mh)?, mh),
        th_a: mat("to_held.a", mh, mr)?,
        th_b: mat("to_held.b", mh, mr)?,
        th_z: vec("to_held.t_z", mh)?,
        th_v: vec("to_held.t_v", mh)?,
        th_c: vec("to_held.c", mh)?,
        rr_a: mat("release.a", mr, mh)?,
        rr_b: mat("release.b", mr, mh)?,
        rr_c: vec("release.c", mr)?,
        lam_r,
        lam_h,
    })
}

/// The repository's root, against which the IR's relative data paths resolve:
/// `$VARIMU_ROOT`, else this crate's checkout (two levels above its manifest).
pub fn data_root() -> PathBuf {
    std::env::var_os("VARIMU_ROOT")
        .map(PathBuf::from)
        .unwrap_or_else(|| Path::new(env!("CARGO_MANIFEST_DIR")).join("../.."))
}

type Loaded = Mutex<HashMap<(PathBuf, String), Arc<ClavModel>>>;

/// The model the IR element names, loaded once per process (by its path and sidecar
/// sha256); its sidecar must be the one the element pins.
pub fn load(el: &crate::ir::ClavStrings) -> Result<Arc<ClavModel>, String> {
    static LOADED: OnceLock<Loaded> = OnceLock::new();
    let path = {
        let p = Path::new(&el.data);
        if p.is_absolute() {
            p.to_path_buf()
        } else {
            data_root().join(p)
        }
    };
    let key = (path.clone(), el.sha256.clone());
    let cache = LOADED.get_or_init(Default::default);
    if let Some(m) = cache.lock().expect("models").get(&key) {
        return Ok(m.clone());
    }
    let m = ClavModel::read(&path)?;
    if m.sha256 != el.sha256 {
        return Err(format!(
            "{}: the strings' sidecar is {}, the element pins {}",
            el.name, m.sha256, el.sha256
        ));
    }
    let m = Arc::new(m);
    cache.lock().expect("models").insert(key, m.clone());
    Ok(m)
}

// --- A voice ----------------------------------------------------------------------

/// Complex vectors as structure of arrays, padded to a multiple of [`LANES`].
#[derive(Debug, Clone, Default)]
struct Soa {
    re: Vec<f64>,
    im: Vec<f64>,
}

impl Soa {
    fn new(v: &[C64], m: usize) -> Soa {
        let mut s = Soa {
            re: vec![0.0; m],
            im: vec![0.0; m],
        };
        for (i, c) in v.iter().enumerate() {
            s.re[i] = c.0;
            s.im[i] = c.1;
        }
        s
    }
}

/// Re(sum c z) over equal slices (a multiple of [`LANES`] long), in four lanes.
#[inline(always)]
fn dot(c: &Soa, zr: &[f64], zi: &[f64]) -> f64 {
    let m = zr.len();
    let mut acc = [0.0; LANES];
    for (((cr, ci), zr), zi) in c.re[..m]
        .chunks_exact(LANES)
        .zip(c.im[..m].chunks_exact(LANES))
        .zip(zr.chunks_exact(LANES))
        .zip(zi.chunks_exact(LANES))
    {
        for l in 0..LANES {
            acc[l] += cr[l] * zr[l] - ci[l] * zi[l];
        }
    }
    (acc[0] + acc[1]) + (acc[2] + acc[3])
}

/// A system's rotation and pickup rows at the voice's rate.
#[derive(Debug, Clone)]
struct Run {
    /// Padded length.
    m: usize,
    rot: Soa,
    /// centre y, vy; bridge y, vy.
    rows: [Soa; 4],
    /// |vy rows| (the sleep test's).
    vy_abs: [Vec<f64>; 2],
}

impl Run {
    fn new(lam: &[C64], rows: &[Vec<C64>], dt: f64, nyquist_masked: bool) -> Run {
        let modes = lam.len();
        let m = modes.div_ceil(LANES) * LANES;
        let keep = |j: usize| !nyquist_masked || lam[j].1.abs() * dt < std::f64::consts::PI;
        let row = |r: &[C64]| {
            let masked: Vec<C64> = (0..modes)
                .map(|j| if keep(j) { r[j] } else { C64(0.0, 0.0) })
                .collect();
            Soa::new(&masked, m)
        };
        let rot: Vec<C64> = lam.iter().map(|l| l.scale(dt).exp()).collect();
        let rows = [row(&rows[0]), row(&rows[1]), row(&rows[2]), row(&rows[3])];
        let abs = |s: &Soa| -> Vec<f64> { (0..m).map(|j| s.re[j].hypot(s.im[j])).collect() };
        Run {
            m,
            rot: Soa::new(&rot, m),
            vy_abs: [abs(&rows[1]), abs(&rows[3])],
            rows,
        }
    }
}

/// The contacts' substep (the released modes' first-order hold at h).
#[derive(Debug, Clone)]
struct Step {
    h: f64,
    phi: Soa,
    phi_sample: Soa,
    g0y: Soa,
    g1y: Soa,
    g0x: Soa,
    g1x: Soa,
    /// The anvil point's rows: y, x, vy, vx.
    c: [Soa; 4],
    /// The pickups through every mode: centre y, vy; bridge y, vy.
    rows: [Soa; 4],
    /// The anvil point's instantaneous responses to the substep's end force.
    gyy: f64,
    gyx: f64,
    gxy: f64,
    gxx: f64,
    hyy: f64,
    hyx: f64,
    hxy: f64,
    hxx: f64,
}

impl Step {
    fn new(k: &ClavKey, fs_int: f64, s: usize) -> Step {
        let h = 1.0 / (fs_int * s as f64);
        let m = k.lam_r.len().div_ceil(LANES) * LANES;
        let (mut phi, mut g0y, mut g1y, mut g0x, mut g1x) =
            (Vec::new(), Vec::new(), Vec::new(), Vec::new(), Vec::new());
        for (j, l) in k.lam_r.iter().enumerate() {
            let x = l.scale(h);
            let (e1, e2) = phi12(x);
            let e0h = e1.sub(e2).scale(h);
            let e1h = e2.scale(h);
            phi.push(x.exp());
            g0y.push(k.b_y[j].mul(e0h));
            g1y.push(k.b_y[j].mul(e1h));
            g0x.push(k.b_x[j].mul(e0h));
            g1x.push(k.b_x[j].mul(e1h));
        }
        let phi_sample: Vec<C64> = k
            .lam_r
            .iter()
            .map(|l| l.scale(1.0 / fs_int).exp())
            .collect();
        let re = |c: &[C64], g: &[C64]| -> f64 {
            c.iter().zip(g).map(|(a, b)| a.0 * b.0 - a.1 * b.1).sum()
        };
        let r = &k.r_rows;
        Step {
            h,
            gyy: re(&r[0], &g1y),
            gyx: re(&r[0], &g1x),
            gxy: re(&r[1], &g1y),
            gxx: re(&r[1], &g1x),
            hyy: re(&r[2], &g1y),
            hyx: re(&r[2], &g1x),
            hxy: re(&r[3], &g1y),
            hxx: re(&r[3], &g1x),
            phi: Soa::new(&phi, m),
            phi_sample: Soa::new(&phi_sample, m),
            g0y: Soa::new(&g0y, m),
            g1y: Soa::new(&g1y, m),
            g0x: Soa::new(&g0x, m),
            g1x: Soa::new(&g1x, m),
            c: [
                Soa::new(&r[0], m),
                Soa::new(&r[1], m),
                Soa::new(&r[2], m),
                Soa::new(&r[3], m),
            ],
            rows: [
                Soa::new(&r[4], m),
                Soa::new(&r[5], m),
                Soa::new(&r[6], m),
                Soa::new(&r[7], m),
            ],
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq)]
enum Until {
    /// The strike: both contacts closed.
    Closed,
    /// The release: both open.
    Open,
}

/// A contact run (the strike or the release).
#[derive(Debug, Clone)]
struct ContactRun {
    zt: f64,
    vt: f64,
    f_h: f64,
    until: Until,
    fr: f64,
    fa: f64,
    /// The rubber's sideways grip, and where it stuck (None: the rubber off the string).
    fg: f64,
    x_stick: Option<f64>,
    fy: f64,
    fx: f64,
    i: usize,
    flight: bool,
    closed_since: Option<f64>,
    open_since: Option<f64>,
}

#[derive(Debug, Clone, Copy, PartialEq)]
enum Phase {
    Free,
    Contact,
    Held,
}

/// One key's string over the timeline.
#[derive(Debug)]
pub struct Voice {
    k: Arc<ClavModel>,
    i: usize,
    fs: f64,
    s: usize,
    free: Run,
    held: Run,
    step: Step,
    phase: Phase,
    /// The modal state (the current system's; padded to the larger system).
    zr: Vec<f64>,
    zi: Vec<f64>,
    asleep: bool,
    release_pending: bool,
    since_check: usize,
    run: Option<ContactRun>,
    max_steps: usize,
    /// Scratch: a substep's free part.
    xr: Vec<f64>,
    xi: Vec<f64>,
}

impl Voice {
    fn new(model: &Arc<ClavModel>, i: usize, fs_int: f64, s: usize) -> Voice {
        let k = &model.keys[i];
        let dt = 1.0 / fs_int;
        let free = Run::new(&k.lam_r, &k.r_rows[4..], dt, true);
        let held = Run::new(&k.lam_h, &k.h_rows, dt, true);
        let step = Step::new(k, fs_int, s);
        let m = free.m.max(held.m);
        Voice {
            k: model.clone(),
            i,
            fs: fs_int,
            s,
            max_steps: (model.num.max_s / step.h).round() as usize,
            phase: Phase::Free,
            zr: vec![0.0; m],
            zi: vec![0.0; m],
            xr: vec![0.0; free.m],
            xi: vec![0.0; free.m],
            asleep: true,
            release_pending: false,
            since_check: 0,
            run: None,
            free,
            held,
            step,
        }
    }

    fn key(&self) -> &ClavKey {
        &self.k.keys[self.i]
    }

    fn zero(&mut self) {
        self.zr.fill(0.0);
        self.zi.fill(0.0);
    }

    /// The held modes' frequencies scaled for the hold force at pressure `value`.
    fn set_pressure(&mut self, value: u8) {
        let k = &self.k.keys[self.i];
        let f0 = k.contact.hold_force_n;
        let f = f0 + (self.k.max_force - f0) * value as f64 / 127.0;
        let cents = interp(f, &k.bend_f, &k.bend_c) - interp(f0, &k.bend_f, &k.bend_c);
        let ratio = 2f64.powf(cents / 1200.0);
        let dt = 1.0 / self.fs;
        for (j, l) in k.lam_h.iter().enumerate() {
            let pair = l.1.abs() > 1e-12 * l.norm();
            let bent = if pair { C64(l.0, l.1 * ratio) } else { *l };
            let r = bent.scale(dt).exp();
            self.held.rot.re[j] = r.0;
            self.held.rot.im[j] = r.1;
        }
    }

    /// `z_new = A z + B conj(z) + c` (A, B rows x cols, row-major) into the state.
    fn transfer(&mut self, a: &[C64], b: &[C64], c: &[C64], cols: usize) {
        let z: Vec<C64> = (0..cols).map(|j| C64(self.zr[j], self.zi[j])).collect();
        self.zero();
        for (r, cr) in c.iter().enumerate() {
            let (ar, br) = (&a[r * cols..(r + 1) * cols], &b[r * cols..(r + 1) * cols]);
            let mut acc = *cr;
            for j in 0..cols {
                acc = acc
                    .add(ar[j].mul(z[j]))
                    .add(br[j].mul(C64(z[j].0, -z[j].1)));
            }
            self.zr[r] = acc.0;
            self.zi[r] = acc.1;
        }
    }

    fn onto_released(&mut self) {
        let k = self.k.clone();
        let k = &k.keys[self.i];
        self.transfer(&k.rr_a, &k.rr_b, &k.rr_c, k.lam_h.len());
    }

    fn on(&mut self, speed: f64) {
        if self.phase == Phase::Held {
            self.onto_released();
        }
        self.release_pending = false;
        if self.asleep {
            self.zero();
        }
        self.asleep = false;
        let c = &self.key().contact;
        let (travel, hold) = (c.travel_m, c.hold_force_n);
        self.start(-travel, speed, hold, Until::Closed);
    }

    fn off(&mut self) {
        match (self.phase, &self.run) {
            (Phase::Contact, Some(r)) if r.until == Until::Closed => self.release_pending = true,
            (Phase::Held, _) => self.release(),
            _ => {}
        }
    }

    fn release(&mut self) {
        let mh = self.held.m;
        let k = self.k.clone();
        let key = &k.keys[self.i];
        let t0 = Soa::new(&key.t_rows[0], mh);
        let t1 = Soa::new(&key.t_rows[1], mh);
        let zt = dot(&t0, &self.zr[..mh], &self.zi[..mh]);
        let vt = dot(&t1, &self.zr[..mh], &self.zi[..mh]);
        self.onto_released();
        self.asleep = false;
        let f = -key.contact.return_force_n;
        self.start(zt + key.static_tangent, vt, f, Until::Open);
    }

    fn start(&mut self, zt: f64, vt: f64, f_h: f64, until: Until) {
        let (fr, fa) = self.forces(zt, vt);
        let c = &self.key().contact;
        let (cs, sn) = (c.tilt_rad.cos(), c.tilt_rad.sin());
        let m = self.free.m;
        let x_now = dot(&self.step.c[1], &self.zr[..m], &self.zi[..m]);
        let vx_now = dot(&self.step.c[3], &self.zr[..m], &self.zi[..m]);
        // Entering from the hold (the release), the grip carries the state's sideways force
        // about its anchor, x = 0.
        let fg = if fr > 0.0 {
            -c.grip_k_n_m * x_now - c.grip_c_ns_m * vx_now
        } else {
            0.0
        };
        self.phase = Phase::Contact;
        self.run = Some(ContactRun {
            zt,
            vt,
            f_h,
            until,
            fr,
            fa,
            fg,
            x_stick: (fr > 0.0).then_some(0.0),
            fy: fr - fa * cs,
            fx: -fa * sn + fg,
            i: 0,
            flight: until == Until::Closed && fr == 0.0 && fa == 0.0,
            closed_since: None,
            open_since: None,
        });
    }

    /// The contacts' forces at the state (note.py's `_forces`).
    fn forces(&self, zt: f64, vt: f64) -> (f64, f64) {
        let c = &self.key().contact;
        let (cs, sn) = (c.tilt_rad.cos(), c.tilt_rad.sin());
        let m = self.free.m;
        let (zr, zi) = (&self.zr[..m], &self.zi[..m]);
        let st = &self.step;
        let (ya, xa) = (dot(&st.c[0], zr, zi), dot(&st.c[1], zr, zi));
        let (vya, vxa) = (dot(&st.c[2], zr, zi), dot(&st.c[3], zr, zi));
        let (dr, ddr) = (zt - ya, vt - vya);
        let mut fr = 0.0;
        if dr > 0.0 {
            fr = c.rubber_k * dr.powf(c.rubber_p) * (1.0 + c.rubber_alpha_s_m * ddr).max(0.0);
        }
        let (da, dda) = (cs * ya + sn * xa - c.anvil_gap_m, cs * vya + sn * vxa);
        let fa = if da > 0.0 {
            (c.anvil_k_n_m * da + c.anvil_c_ns_m * dda).max(0.0)
        } else {
            0.0
        };
        (fr, fa)
    }

    fn end_strike(&mut self) {
        let run = self.run.take().expect("a strike");
        let k = self.k.clone();
        let key = &k.keys[self.i];
        let cols = key.lam_r.len();
        let c: Vec<C64> = (0..key.lam_h.len())
            .map(|r| {
                key.th_c[r]
                    .add(key.th_z[r].scale(run.zt))
                    .add(key.th_v[r].scale(run.vt))
            })
            .collect();
        self.transfer(&key.th_a, &key.th_b, &c, cols);
        self.phase = Phase::Held;
        self.since_check = 0;
        if self.release_pending {
            self.release_pending = false;
            self.release();
        }
    }

    /// One internal sample of a contact run in `s` substeps (note.py's loop): the unknowns
    /// the rubber's push fr, the anvil's fa and the rubber's sideways grip fg (its shear
    /// about where it first touched), a 3x3 Newton on a forward-difference Jacobian.
    fn substeps(&mut self) {
        let k = self.k.clone();
        let c = &k.keys[self.i].contact;
        let st = &self.step;
        let run = self.run.as_mut().expect("a contact run");
        let h = st.h;
        let (cs, sn) = (c.tilt_rad.cos(), c.tilt_rad.sin());
        let (m_t, f_h) = (c.tangent_mass_kg, run.f_h);
        let (k_r, p_r, a_r) = (c.rubber_k, c.rubber_p, c.rubber_alpha_s_m);
        let (k_a, c_a, gap) = (c.anvil_k_n_m, c.anvil_c_ns_m, c.anvil_gap_m);
        let (k_g, c_g) = (c.grip_k_n_m, c.grip_c_ns_m);
        let (gyy, gyx, gxy, gxx) = (st.gyy, st.gyx, st.gxy, st.gxx);
        let (hyy, hyx, hxy, hxx) = (st.hyy, st.hyx, st.hxy, st.hxx);
        let cz = h * h / (6.0 * m_t);
        let cv = h / (2.0 * m_t);
        let m = self.free.m;
        let (zr, zi) = (&mut self.zr[..m], &mut self.zi[..m]);
        let (xr, xi) = (&mut self.xr[..m], &mut self.xi[..m]);
        let (mut zt, mut vt) = (run.zt, run.vt);
        let (mut fr_prev, mut fa_prev, mut fg_prev) = (run.fr, run.fa, run.fg);
        let (mut fy_prev, mut fx_prev) = (run.fy, run.fx);
        let mut x_stick = run.x_stick;
        for _ in 0..self.s {
            for j in 0..m {
                let (a, b) = (zr[j], zi[j]);
                xr[j] = (st.phi.re[j] * a - st.phi.im[j] * b)
                    + st.g0y.re[j] * fy_prev
                    + st.g0x.re[j] * fx_prev;
                xi[j] = (st.phi.re[j] * b + st.phi.im[j] * a)
                    + st.g0y.im[j] * fy_prev
                    + st.g0x.im[j] * fx_prev;
            }
            let (yf, xf) = (dot(&st.c[0], xr, xi), dot(&st.c[1], xr, xi));
            let (vyf, vxf) = (dot(&st.c[2], xr, xi), dot(&st.c[3], xr, xi));
            let a_prev = (f_h - fr_prev) / m_t;
            let ztf = zt + h * vt + h * h * (2.0 * a_prev) / 6.0 + cz * f_h;
            let vtf = vt + h * a_prev / 2.0 + cv * f_h;
            if x_stick.is_none() && fr_prev > 0.0 {
                x_stick = Some(dot(&st.c[1], zr, zi));
            }
            let resid = |f: [f64; 3]| -> [f64; 3] {
                let [fr_, fa_, fg_] = f;
                let (fy_, fx_) = (fr_ - fa_ * cs, -fa_ * sn + fg_);
                let ya_ = yf + gyy * fy_ + gyx * fx_;
                let xa_ = xf + gxy * fy_ + gxx * fx_;
                let vya_ = vyf + hyy * fy_ + hyx * fx_;
                let vxa_ = vxf + hxy * fy_ + hxx * fx_;
                let (dr_, ddr_) = (ztf - cz * fr_ - ya_, vtf - cv * fr_ - vya_);
                let (da_, dda_) = (cs * ya_ + sn * xa_ - gap, cs * vya_ + sn * vxa_);
                let frh = if dr_ > 0.0 {
                    k_r * dr_.powf(p_r) * (1.0 + a_r * ddr_).max(0.0)
                } else {
                    0.0
                };
                let fah = if da_ > 0.0 {
                    (k_a * da_ + c_a * dda_).max(0.0)
                } else {
                    0.0
                };
                let stick = x_stick.unwrap_or(xa_);
                let fgh = if dr_ > 0.0 {
                    -k_g * (xa_ - stick) - c_g * vxa_
                } else {
                    0.0
                };
                [fr_ - frh, fa_ - fah, fg_ - fgh]
            };
            let mut f = [fr_prev, fa_prev, fg_prev];
            for _ in 0..40 {
                let r = resid(f);
                let mut jac = [[0.0; 3]; 3];
                for kk in 0..3 {
                    let d = 1e-7 * f[kk].abs().max(1.0);
                    let mut fp = f;
                    fp[kk] += d;
                    let rp = resid(fp);
                    for (j, row) in jac.iter_mut().enumerate() {
                        row[kk] = (rp[j] - r[j]) / d;
                    }
                }
                let step = solve3(jac, r);
                let f_new = [
                    (f[0] - step[0]).max(0.0),
                    (f[1] - step[1]).max(0.0),
                    f[2] - step[2],
                ];
                let done =
                    (0..3).all(|kk| (f_new[kk] - f[kk]).abs() < 1e-10 * f[kk].abs().max(1.0));
                f = f_new;
                if done {
                    break;
                }
            }
            let [fr, fa, mut fg] = f;
            if fr == 0.0 {
                fg = 0.0;
            }
            let (fy, fx) = (fr - fa * cs, -fa * sn + fg);
            for j in 0..m {
                zr[j] = xr[j] + st.g1y.re[j] * fy + st.g1x.re[j] * fx;
                zi[j] = xi[j] + st.g1y.im[j] * fy + st.g1x.im[j] * fx;
            }
            zt = ztf - cz * fr;
            vt = vtf - cv * fr;
            (fr_prev, fa_prev, fg_prev, fy_prev, fx_prev) = (fr, fa, fg, fy, fx);
            if fr == 0.0 {
                x_stick = None;
            }
            run.i += 1;
            let t = run.i as f64 * h;
            if fr > 0.0 && fa > 0.0 {
                run.closed_since.get_or_insert(t);
            } else {
                run.closed_since = None;
            }
            if fr == 0.0 && fa == 0.0 {
                run.open_since.get_or_insert(t);
            } else {
                run.open_since = None;
            }
        }
        run.zt = zt;
        run.vt = vt;
        (run.fr, run.fa, run.fg, run.fy, run.fx) = (fr_prev, fa_prev, fg_prev, fy_prev, fx_prev);
        run.x_stick = x_stick;
    }

    /// One internal sample of a contact run (a flight sample at once, see live.py).
    fn contact_sample(&mut self) {
        let k = self.k.clone();
        let c = &k.keys[self.i].contact;
        let run = self.run.as_mut().expect("a contact run");
        if run.flight {
            let hh = 1.0 / self.fs;
            let acc = run.f_h / c.tangent_mass_kg;
            let st = &self.step;
            let m = self.free.m;
            let (xr, xi) = (&mut self.xr[..m], &mut self.xi[..m]);
            for j in 0..m {
                let (a, b) = (self.zr[j], self.zi[j]);
                xr[j] = st.phi_sample.re[j] * a - st.phi_sample.im[j] * b;
                xi[j] = st.phi_sample.re[j] * b + st.phi_sample.im[j] * a;
            }
            let zt1 = run.zt + hh * run.vt + 0.5 * acc * hh * hh;
            let (ya, xa) = (dot(&st.c[0], xr, xi), dot(&st.c[1], xr, xi));
            let (cs, sn) = (c.tilt_rad.cos(), c.tilt_rad.sin());
            if zt1 - ya <= 0.0 && cs * ya + sn * xa - c.anvil_gap_m <= 0.0 {
                run.open_since.get_or_insert((run.i + 1) as f64 * st.h);
                self.zr[..m].copy_from_slice(xr);
                self.zi[..m].copy_from_slice(xi);
                run.zt = zt1;
                run.vt += acc * hh;
                run.i += self.s;
                return;
            }
            run.flight = false;
        }
        self.substeps();
    }

    fn run_done(&self) -> bool {
        let run = self.run.as_ref().expect("a contact run");
        let num = &self.k.num;
        let t = run.i as f64 * self.step.h;
        let done = match run.until {
            Until::Closed => run
                .closed_since
                .is_some_and(|cl| t >= num.strike_window_s && t - cl >= num.settle_s),
            Until::Open => run
                .open_since
                .is_some_and(|op| t >= num.open_window_s && t - op >= num.open_s),
        };
        done || run.i >= self.max_steps
    }

    /// The pickups' EMF through `rows` (centre y, vy; bridge y, vy) on the state.
    #[inline(always)]
    fn emf(&self, rows: &[Soa; 4], m: usize, held: bool) -> (f64, f64) {
        let (zr, zi) = (&self.zr[..m], &self.zi[..m]);
        let key = self.key();
        let mut e = [0.0; 2];
        for (p, ep) in e.iter_mut().enumerate() {
            let mut y = dot(&rows[2 * p], zr, zi);
            let vy = dot(&rows[2 * p + 1], zr, zi);
            if held {
                y += key.static_y[p];
            }
            *ep = key.tables[p].emf(y, vy);
        }
        (e[0], e[1])
    }

    fn sleep_check(&mut self) {
        let held = self.phase == Phase::Held;
        let run = if held { &self.held } else { &self.free };
        let key = &self.k.keys[self.i];
        let mut bound = 0.0;
        for p in 0..2 {
            let s: f64 = (0..run.m)
                .map(|j| self.zr[j].hypot(self.zi[j]) * run.vy_abs[p][j])
                .sum();
            bound += s * key.tables[p].dmax;
        }
        if bound < self.k.sleep_v {
            self.asleep = true;
            self.zero();
        } else {
            for j in 0..self.zr.len() {
                if self.zr[j].abs() < MODE_FLOOR && self.zi[j].abs() < MODE_FLOOR {
                    self.zr[j] = 0.0;
                    self.zi[j] = 0.0;
                }
            }
        }
    }

    /// Add internal samples `from..to` of its two EMFs into `buf` (centre at i, bridge
    /// at n + i).
    fn render_into(&mut self, buf: &mut [f64], n: usize, from: usize, to: usize) {
        let mut i = from;
        while i < to {
            if self.phase == Phase::Contact {
                self.contact_sample();
                let (c, b) = self.emf(&self.step.rows, self.free.m, false);
                buf[i] += c;
                buf[n + i] += b;
                i += 1;
                if self.run_done() {
                    if self.run.as_ref().expect("a run").until == Until::Closed {
                        self.end_strike();
                    } else {
                        self.phase = Phase::Free;
                        self.run = None;
                        self.since_check = 0;
                    }
                }
                continue;
            }
            if self.asleep {
                return;
            }
            let len = (to - i).min(SLEEP_EVERY - self.since_check);
            let held = self.phase == Phase::Held;
            free_run(self, held, buf, n, i, len);
            i += len;
            self.since_check += len;
            if self.since_check >= SLEEP_EVERY {
                self.since_check = 0;
                self.sleep_check();
            }
        }
    }
}

/// a x = b for a 3x3 a: Gaussian elimination with partial pivoting (live.py's `solve3`).
#[allow(clippy::needless_range_loop)]
fn solve3(a: [[f64; 3]; 3], b: [f64; 3]) -> [f64; 3] {
    let mut m = [[0.0; 4]; 3];
    for i in 0..3 {
        m[i][..3].copy_from_slice(&a[i]);
        m[i][3] = b[i];
    }
    for c in 0..3 {
        // the first row of the largest |m[r][c]| (Python's max keeps the first)
        let mut p = c;
        for r in c + 1..3 {
            if m[r][c].abs() > m[p][c].abs() {
                p = r;
            }
        }
        m.swap(c, p);
        for r in c + 1..3 {
            let f = m[r][c] / m[c][c];
            for k in c..4 {
                m[r][k] -= f * m[c][k];
            }
        }
    }
    let mut x = [0.0; 3];
    for r in (0..3).rev() {
        let mut s = 0.0;
        for k in r + 1..3 {
            s += m[r][k] * x[k];
        }
        x[r] = (m[r][3] - s) / m[r][r];
    }
    x
}

fn interp(x: f64, xs: &[f64], ys: &[f64]) -> f64 {
    if x <= xs[0] {
        return ys[0];
    }
    let last = xs.len() - 1;
    if x >= xs[last] {
        return ys[last];
    }
    let i = xs.partition_point(|&v| v <= x) - 1;
    ys[i] + (x - xs[i]) * (ys[i + 1] - ys[i]) / (xs[i + 1] - xs[i])
}

/// A free or held voice over `len` samples: rotated, read, its EMFs added (AVX2 where the
/// CPU has it: the same operations lane for lane, no FMA).
fn free_run(v: &mut Voice, held: bool, buf: &mut [f64], n: usize, at: usize, len: usize) {
    #[cfg(target_arch = "x86_64")]
    if std::is_x86_feature_detected!("avx2") {
        // SAFETY: the CPU has AVX2 (checked above).
        unsafe { free_run_avx2(v, held, buf, n, at, len) };
        return;
    }
    free_run_impl(v, held, buf, n, at, len);
}

#[cfg(target_arch = "x86_64")]
#[target_feature(enable = "avx2")]
unsafe fn free_run_avx2(
    v: &mut Voice,
    held: bool,
    buf: &mut [f64],
    n: usize,
    at: usize,
    len: usize,
) {
    free_run_impl(v, held, buf, n, at, len);
}

#[inline(always)]
fn free_run_impl(v: &mut Voice, held: bool, buf: &mut [f64], n: usize, at: usize, len: usize) {
    let run = if held { &v.held } else { &v.free };
    let m = run.m;
    let key = &v.k.keys[v.i];
    let (rr, ri) = (&run.rot.re[..m], &run.rot.im[..m]);
    for i in at..at + len {
        {
            let (zr, zi) = (&mut v.zr[..m], &mut v.zi[..m]);
            for (((zr, zi), rr), ri) in zr
                .chunks_exact_mut(LANES)
                .zip(zi.chunks_exact_mut(LANES))
                .zip(rr.chunks_exact(LANES))
                .zip(ri.chunks_exact(LANES))
            {
                for l in 0..LANES {
                    let (a, c) = (zr[l], zi[l]);
                    zr[l] = a * rr[l] - c * ri[l];
                    zi[l] = a * ri[l] + c * rr[l];
                }
            }
        }
        let (zr, zi) = (&v.zr[..m], &v.zi[..m]);
        for p in 0..2 {
            let mut y = dot(&run.rows[2 * p], zr, zi);
            let vy = dot(&run.rows[2 * p + 1], zr, zi);
            if held {
                y += key.static_y[p];
            }
            buf[p * n + i] += key.tables[p].emf(y, vy);
        }
    }
}

// --- The medium -------------------------------------------------------------------

/// What every voice reads: nothing beyond its own model (each holds the shared Arc).
#[derive(Debug)]
pub struct ClavCtx {
    model: Arc<ClavModel>,
}

impl crate::keyed::KeyVoice for Voice {
    type Ctx = ClavCtx;

    fn asleep(&self) -> bool {
        self.asleep && self.phase != Phase::Contact
    }

    fn event(&mut self, ev: NoteEvent, ctx: &ClavCtx) {
        match ev {
            NoteEvent::On { velocity, .. } => self.on(ctx.model.speed(velocity)),
            NoteEvent::Off { .. } => self.off(),
            NoteEvent::Pressure { value } => self.set_pressure(value),
            NoteEvent::Pedal { .. } => {}
        }
    }

    fn render(&mut self, buf: &mut [f64], n: usize, from: usize, to: usize, _ctx: &ClavCtx) {
        self.render_into(buf, n, from, to);
    }
}

/// The strings beside the circuit at step rate `fs` (see the module docs): two outputs,
/// the centre pickup's EMF and the bridge pickup's.
pub struct Medium {
    pub el: crate::ir::ClavStrings,
    pub model: Arc<ClavModel>,
    /// Internal samples per step and contact substeps per internal sample.
    pub k: usize,
    pub s: usize,
    keys: crate::keyed::Medium<Voice>,
}

impl std::fmt::Debug for Medium {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("clavinet::Medium")
            .field("el", &self.el.name)
            .field("k", &self.k)
            .field("s", &self.s)
            .field("keys", &self.keys)
            .finish()
    }
}

impl Medium {
    pub fn new(el: &crate::ir::ClavStrings, fs: f64) -> Result<Medium, String> {
        Medium::with_workers(el, fs, crate::keyed::workers())
    }

    /// [`Medium::new`] with `n` worker threads (the result is the same with any number).
    pub fn with_workers(el: &crate::ir::ClavStrings, fs: f64, n: usize) -> Result<Medium, String> {
        let model = load(el)?;
        let k = ((el.rate_hz / fs) - 1e-9).ceil().max(1.0) as usize;
        let s = ((el.contact_rate_hz / (fs * k as f64)) - 1e-9)
            .ceil()
            .max(1.0) as usize;
        let fs_int = fs * k as f64;
        let voices = (0..model.keys.len())
            .map(|i| (model.keys[i].note, Voice::new(&model, i, fs_int, s)))
            .collect();
        let ctx = ClavCtx {
            model: model.clone(),
        };
        Ok(Medium {
            el: el.clone(),
            model,
            k,
            s,
            keys: crate::keyed::Medium::new(voices, ctx, fs, k, 2, n),
        })
    }

    /// Keep every internal sample rendered from now on ([`Medium::raw`]; tests).
    pub fn keep_raw(&mut self) {
        self.keys.keep_raw();
    }

    /// Pickup p's (0 centre, 1 bridge) internal samples kept.
    pub fn raw(&self, p: usize) -> &[f64] {
        self.keys.raw(p)
    }

    pub fn delay_steps(&self) -> f64 {
        self.keys.delay_steps()
    }

    pub fn position(&self) -> usize {
        self.keys.position()
    }

    pub fn queue(&mut self, at: usize, ev: NoteEvent) {
        self.keys.queue(at, ev);
    }

    pub fn known_until(&mut self, at: usize) {
        self.keys.known_until(at);
    }

    /// The (centre, bridge) EMFs at the next step (the push at step p gives step p + 1's).
    pub fn push(&mut self) -> [f64; 2] {
        let mut y = [0.0; 2];
        self.keys.push_into(&mut y);
        y
    }

    /// Strings ringing (not asleep) after the last chunk.
    pub fn sounding(&self) -> usize {
        self.keys.sounding()
    }

    /// Whether `el` keeps this medium playing (the same data and rates).
    pub fn same(&self, el: &crate::ir::ClavStrings) -> bool {
        el.data == self.el.data
            && el.sha256 == self.el.sha256
            && el.rate_hz == self.el.rate_hz
            && el.contact_rate_hz == self.el.contact_rate_hz
    }

    pub fn fs(&self) -> f64 {
        self.keys.fs()
    }
}

/// Each pickup's EMF at every step and every internal sample ([`render`]).
pub type Rendered = ([Vec<f64>; 2], [Vec<f64>; 2]);

/// The strings alone: `n` steps at `fs` from rest, `events` (step, event) in order;
/// returns each pickup's EMF at every step (sample 0 the rest's) and every internal
/// sample (index 0 the rest's).
pub fn render(
    el: &crate::ir::ClavStrings,
    fs: f64,
    n: usize,
    events: &[(usize, NoteEvent)],
    workers: Option<usize>,
) -> Result<Rendered, String> {
    let mut m = match workers {
        Some(w) => Medium::with_workers(el, fs, w)?,
        None => Medium::new(el, fs)?,
    };
    m.keep_raw();
    for &(at, ev) in events {
        m.queue(at, ev);
    }
    m.known_until(usize::MAX);
    let mut y = [vec![0.0], vec![0.0]];
    for _ in 1..n {
        let v = m.push();
        y[0].push(v[0]);
        y[1].push(v[1]);
    }
    let raw = [0, 1].map(|p| {
        let mut r = vec![0.0];
        r.extend_from_slice(m.raw(p));
        r.truncate((n - 1) * m.k + 1);
        r
    });
    Ok((y, raw))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn interp_is_linear_and_clamped() {
        let xs = [1.0, 2.0, 4.0];
        let ys = [0.0, 10.0, 30.0];
        assert_eq!(interp(0.5, &xs, &ys), 0.0);
        assert_eq!(interp(1.5, &xs, &ys), 5.0);
        assert_eq!(interp(3.0, &xs, &ys), 20.0);
        assert_eq!(interp(5.0, &xs, &ys), 30.0);
    }

    #[test]
    fn a_table_reads_its_points_and_clips() {
        let t = Table {
            sgn: -1.0,
            clearance: 2.0,
            lo: 1.0,
            hi: 3.0,
            step: 1.0,
            dmax: 3.0,
            dh: vec![1.0, 2.0, 3.0],
        };
        // h = 2 - y: y = 0 reads the middle point, y = -0.5 halfway up, y = 5 the floor.
        assert_eq!(t.emf(0.0, 1.0), 2.0);
        assert_eq!(t.emf(-0.5, 1.0), 2.5);
        assert_eq!(t.emf(5.0, 2.0), 2.0);
        assert_eq!(t.emf(-5.0, 1.0), 3.0);
    }
}
