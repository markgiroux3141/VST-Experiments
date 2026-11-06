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
//!
//! **Strikes from rest** ([`StrikeTable`]): a strike on a string at rest depends only on its
//! key and velocity, so a process that plays live (the app, [`fill_strike_tables`]) records
//! all of them once, 60 keys x 127 velocities, in the background (saved under the
//! repository's `cache/clavinet/`, keyed by the data, the rates and this crate's sources).
//! A voice struck from rest replays its record, the pickups' EMF sample by sample and the
//! state the strike leaves, bit for bit what it would compute; a string still ringing, or a
//! strike not recorded yet, is computed. Renders that don't ask for tables compute every
//! strike, as before.
//!
//! **Wear** ([`ClavModel::worn`], `varimu.clavinet.wear` the reference): an IR element's
//! `wear` gives an instrument of its own, drawn from a seed: per key detune, old strings,
//! hardened tangents, worn yarn and pickup heights, applied to the model once, at load
//! (no cost per sample). The worn modes rotate freely (the hold, the released string between
//! contacts); the contact runs keep the compiled released modes (a changed decay under the
//! compiled residues is active under the contact's feedback). A worn model has its own
//! strike table ([`ClavModel::id`]).

use std::collections::HashMap;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};
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
    /// A worn tangent's rubber ([`ClavModel::worn`]): the nominal rubber's compression under
    /// the hold force less the worn one's (0 as compiled).
    #[serde(default)]
    hold_shift_m: f64,
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
    dh: Arc<[f64]>,
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
    /// The released modes as they rotate freely (worn; `lam_r` as compiled).
    lam_f: Vec<C64>,
    b_y: Vec<C64>,
    b_x: Vec<C64>,
    /// anvil y, x, vy, vx; centre y, vy; bridge y, vy (8 x m_r).
    r_rows: Vec<Vec<C64>>,
    lam_h: Vec<C64>,
    /// centre y, vy; bridge y, vy (4 x m_h).
    h_rows: Vec<Vec<C64>>,
    /// The tangent's position and velocity (2 x m_h).
    t_rows: Vec<Vec<C64>>,
    th_a: Arc<[C64]>,
    th_b: Arc<[C64]>,
    th_z: Vec<C64>,
    th_v: Vec<C64>,
    th_c: Vec<C64>,
    rr_a: Arc<[C64]>,
    rr_b: Arc<[C64]>,
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
    /// A worn model's wear (its hash: [`wear_hash`]); None as compiled.
    pub wear: Option<u64>,
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
            wear: None,
        })
    }

    /// What tells this model's strike table apart: the sidecar's sha256, and a worn
    /// model's wear.
    pub fn id(&self) -> String {
        match self.wear {
            None => self.sha256.clone(),
            Some(h) => format!("{}w{h:016x}", self.sha256),
        }
    }

    /// This (compiled) model worn by `w` (`varimu.clavinet.wear.apply`, the module docs):
    /// the big arrays shared, every key's modes, rubber and pickup clearances its own.
    pub fn worn(&self, w: &crate::ir::ClavWear) -> ClavModel {
        let amounts = [w.tuning, w.strings, w.tangents, w.yarn, w.pickups]
            .map(|share| wear_amount(w.age, share));
        let seed = w.seed as u64;
        ClavModel {
            keys: self
                .keys
                .iter()
                .map(|k| worn_key(k, seed, amounts))
                .collect(),
            velocity: self.velocity.clone(),
            max_force: self.max_force,
            num: self.num.clone(),
            sleep_v: self.sleep_v,
            sha256: self.sha256.clone(),
            wear: Some(wear_hash(w)),
        }
    }
}

// --- Wear (`varimu.clavinet.wear`: the constants' sources are there) -----------------

/// The largest wear amount (2: beyond a realistic old instrument).
pub const WEAR_MAX: f64 = 2.0;
const TUNING_CENTS: f64 = 6.0;
const STRINGS_SIGMA_REF: f64 = 6.91 / 3.8;
const STRINGS_F_REF_HZ: f64 = 3000.0;
const STRINGS_SPREAD: f64 = 0.3;
const STRINGS_JITTER_CENTS: f64 = 0.5;
const NOMINAL_SHORE: f64 = 60.0;
const TANGENTS_SHORE: f64 = 12.0;
const TANGENTS_SPREAD: f64 = 0.4;
const SHORE_MAX: f64 = 90.0;
const YARN_LOSS: f64 = 0.6;
const YARN_SPREAD: f64 = 0.3;
const YARN_BAND: f64 = 0.15;
const PICKUP_BAR_M: f64 = 0.25e-3;
const PICKUP_STRING_M: f64 = 0.15e-3;
const PICKUP_RANGE: (f64, f64) = (0.6, 1.6);
const BAR_STRINGS: usize = 10;
const PAIR: f64 = 1e-12;

/// The IR's checks of a wear (`wear.check`).
pub fn check_wear(w: &crate::ir::ClavWear) -> Result<(), String> {
    if !(w.seed.is_finite() && w.seed >= 0.0 && w.seed < 9_007_199_254_740_992.0)
        || w.seed.fract() != 0.0
    {
        return Err(format!("seed {}: a whole number in [0, 2^53)", w.seed));
    }
    for (name, v) in [
        ("age", w.age),
        ("tuning", w.tuning),
        ("strings", w.strings),
        ("tangents", w.tangents),
        ("yarn", w.yarn),
        ("pickups", w.pickups),
    ] {
        if !(v.is_finite() && (0.0..=WEAR_MAX).contains(&v)) {
            return Err(format!("{name} = {v}: in [0, {WEAR_MAX}]"));
        }
    }
    Ok(())
}

/// A part's amount: age x its share, at most [`WEAR_MAX`].
fn wear_amount(age: f64, share: f64) -> f64 {
    (age * share).min(WEAR_MAX)
}

/// No wear at all: the compiled model exactly (the seed doesn't matter).
pub fn wear_is_new(w: &crate::ir::ClavWear) -> bool {
    [w.tuning, w.strings, w.tangents, w.yarn, w.pickups]
        .iter()
        .all(|&share| wear_amount(w.age, share) == 0.0)
}

/// A wear's hash (its seven numbers' bits).
pub fn wear_hash(w: &crate::ir::ClavWear) -> u64 {
    let bits = [
        w.seed, w.age, w.tuning, w.strings, w.tangents, w.yarn, w.pickups,
    ]
    .map(|x| x.to_bits().to_le_bytes());
    fnv(&bits.iter().map(|b| &b[..]).collect::<Vec<_>>())
}

fn wear_normals(seed: u64, name: &str, stream: usize, n: usize) -> Vec<f64> {
    let mut out = vec![0.0; n];
    crate::noise::normals(crate::noise::key(seed, name, stream as u32), 0, &mut out);
    out
}

fn is_pair(l: &C64) -> bool {
    l.1.abs() > PAIR * l.norm()
}

/// Rubber's Young's modulus from its Shore A hardness (Gent 1958; `spec.gent_youngs_pa`).
fn gent_youngs_pa(shore_a: f64) -> f64 {
    1e6 * 0.0981 * (56.0 + 7.62336 * shore_a) / (0.137505 * (254.0 - 2.54 * shore_a))
}

/// The released modes keeping `keep` of their damping above the string's own (`wear._yarn`).
fn wear_yarn(lam_r: &[C64], lam_h: &[C64], keep: f64) -> Vec<C64> {
    let mut out = lam_r.to_vec();
    let held: Vec<(f64, f64)> = lam_h
        .iter()
        .filter(|l| is_pair(l))
        .map(|l| (l.1.abs(), -l.0))
        .collect();
    if held.is_empty() {
        return out;
    }
    let floor_all = held.iter().map(|h| h.1).fold(f64::INFINITY, f64::min);
    for (j, l) in lam_r.iter().enumerate() {
        if !is_pair(l) {
            continue;
        }
        let f = l.1.abs();
        let floor = held
            .iter()
            .filter(|h| (h.0 - f).abs() <= YARN_BAND * f)
            .map(|h| h.1)
            .fold(f64::INFINITY, f64::min);
        let floor = if floor.is_finite() { floor } else { floor_all };
        let s = -l.0;
        if s > floor {
            out[j] = C64(-(floor + (s - floor) * keep), l.1);
        }
    }
    out
}

/// Old strings' loss: `extra` 1/s at the reference frequency, as its square (`wear._decay`).
fn wear_decay(lam: &mut [C64], extra: f64) {
    for l in lam.iter_mut().filter(|l| is_pair(l)) {
        let f = l.1.abs() / (2.0 * std::f64::consts::PI);
        let r = f / STRINGS_F_REF_HZ;
        l.0 -= extra * (r * r);
    }
}

/// Every oscillating mode's frequency by 2^((cents + jitter_cents z_j) / 1200).
fn wear_tune(lam: &mut [C64], cents: f64, jitter: &[f64], jitter_cents: f64) {
    for (l, z) in lam.iter_mut().zip(jitter) {
        if is_pair(l) {
            let ratio = 2f64.powf((cents + jitter_cents * z) / 1200.0);
            l.1 *= ratio;
        }
    }
}

/// Key `k` worn by the amounts (tuning, strings, tangents, yarn, pickups) under `seed`.
fn worn_key(k: &ClavKey, seed: u64, a: [f64; 5]) -> ClavKey {
    let [tuning, strings, tangents, yarn, pickups] = a;
    let mut k = k.clone();
    let n = k.key;
    let z = wear_normals(seed, "clavinet.wear", n, 6);
    let mut lam_r = k.lam_r.clone();
    let mut lam_h = k.lam_h.clone();
    if yarn > 0.0 {
        let g = yarn * (YARN_SPREAD * z[3]).exp();
        lam_r = wear_yarn(&lam_r, &lam_h, (1.0 - YARN_LOSS).powf(g));
    }
    let (mr, mh) = (lam_r.len(), lam_h.len());
    let mut jitter = vec![0.0; mr + mh];
    if strings > 0.0 {
        let extra = strings * STRINGS_SIGMA_REF * (STRINGS_SPREAD * z[1]).exp();
        wear_decay(&mut lam_r, extra);
        wear_decay(&mut lam_h, extra);
        jitter = wear_normals(seed, "clavinet.wear.modes", n, mr + mh);
    }
    if tuning > 0.0 || strings > 0.0 {
        let cents = tuning * TUNING_CENTS * z[0];
        let jc = strings * STRINGS_JITTER_CENTS;
        wear_tune(&mut lam_r, cents, &jitter[..mr], jc);
        wear_tune(&mut lam_h, cents, &jitter[mr..], jc);
    }
    k.lam_f = lam_r;
    k.lam_h = lam_h;
    if tangents > 0.0 {
        let c = &mut k.contact;
        let shore = (NOMINAL_SHORE + tangents * TANGENTS_SHORE * (TANGENTS_SPREAD * z[2]).exp())
            .min(SHORE_MAX);
        let k0 = c.rubber_k;
        let k1 = k0 * gent_youngs_pa(shore) / gent_youngs_pa(NOMINAL_SHORE);
        let (p, f) = (c.rubber_p, c.hold_force_n);
        c.rubber_k = k1;
        c.hold_shift_m = (f / k0).powf(1.0 / p) - (f / k1).powf(1.0 / p);
    }
    if pickups > 0.0 {
        let bar = wear_normals(seed, "clavinet.wear.bars", (n - 1) / BAR_STRINGS, 2);
        for (j, t) in k.tables.iter_mut().enumerate() {
            let c0 = t.clearance;
            let moved = c0 + pickups * (PICKUP_BAR_M * bar[j] + PICKUP_STRING_M * z[4 + j]);
            t.clearance = moved.max(PICKUP_RANGE.0 * c0).min(PICKUP_RANGE.1 * c0);
        }
    }
    k
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
            dh: dh.into(),
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
        th_a: mat("to_held.a", mh, mr)?.into(),
        th_b: mat("to_held.b", mh, mr)?.into(),
        th_z: vec("to_held.t_z", mh)?,
        th_v: vec("to_held.t_v", mh)?,
        th_c: vec("to_held.c", mh)?,
        rr_a: mat("release.a", mr, mh)?.into(),
        rr_b: mat("release.b", mr, mh)?.into(),
        rr_c: vec("release.c", mr)?,
        lam_f: lam_r.clone(),
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

/// The model the IR element names, worn by its `wear` ([`ClavModel::worn`]; a wear of
/// nothing is the compiled model): loaded once per process (by its path and sidecar
/// sha256), worn copies kept for the last few wears.
pub fn load(el: &crate::ir::ClavStrings) -> Result<Arc<ClavModel>, String> {
    let base = load_compiled(el)?;
    let Some(w) = el.wear.as_ref().filter(|w| !wear_is_new(w)) else {
        return Ok(base);
    };
    check_wear(w).map_err(|e| format!("{}.wear: {e}", el.name))?;
    type Worn = Mutex<Vec<(String, Arc<ClavModel>)>>;
    static WORN: OnceLock<Worn> = OnceLock::new();
    /// Worn models kept (each holds its own modes; the big arrays are the compiled one's).
    const KEEP: usize = 4;
    let id = format!("{}w{:016x}", base.sha256, wear_hash(w));
    let cache = WORN.get_or_init(Default::default);
    if let Some((_, m)) = cache.lock().expect("worn").iter().find(|(i, _)| *i == id) {
        return Ok(m.clone());
    }
    let m = Arc::new(base.worn(w));
    let mut all = cache.lock().expect("worn");
    if let Some((_, m)) = all.iter().find(|(i, _)| *i == id) {
        return Ok(m.clone());
    }
    all.push((id, m.clone()));
    if all.len() > KEEP {
        all.remove(0);
    }
    Ok(m)
}

/// The compiled model the IR element names, loaded once per process (by its path and
/// sidecar sha256); its sidecar must be the one the element pins.
fn load_compiled(el: &crate::ir::ClavStrings) -> Result<Arc<ClavModel>, String> {
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
    // Another thread may have loaded it meanwhile: the first one in is everyone's.
    let m = Arc::new(m);
    Ok(cache
        .lock()
        .expect("models")
        .entry(key)
        .or_insert(m)
        .clone())
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
    /// A strike from rest replayed from the [`StrikeTable`].
    Replay,
}

/// A strike being replayed: its slot in the table, the next sample, its velocity.
#[derive(Debug, Clone, Copy)]
struct Replaying {
    slot: usize,
    pos: usize,
    vel: u8,
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
    /// The strikes from rest recorded for this voice's model and rates, if any.
    strikes: Option<Arc<StrikeTable>>,
    replay: Option<Replaying>,
}

impl Voice {
    fn new(model: &Arc<ClavModel>, i: usize, fs_int: f64, s: usize) -> Voice {
        let k = &model.keys[i];
        let dt = 1.0 / fs_int;
        let free = Run::new(&k.lam_f, &k.r_rows[4..], dt, true);
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
            strikes: None,
            replay: None,
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

    /// A key down at MIDI velocity `vel` (the tangent's speed `speed`).
    fn on(&mut self, vel: u8, speed: f64) {
        if self.phase == Phase::Replay {
            // A re-strike mid-replay: the state the strike has reached, computed.
            self.materialize();
        }
        if self.phase == Phase::Held {
            self.onto_released();
        }
        self.release_pending = false;
        if self.asleep {
            self.zero();
            if let Some(t) = &self.strikes {
                let slot = StrikeTable::slot(self.i, vel);
                if t.slots[slot].get().is_some() {
                    t.replays.fetch_add(1, Ordering::Relaxed);
                    self.asleep = false;
                    self.phase = Phase::Replay;
                    self.run = None;
                    self.replay = Some(Replaying { slot, pos: 0, vel });
                    return;
                }
            }
        }
        self.asleep = false;
        self.strike_from_here(speed);
    }

    fn strike_from_here(&mut self, speed: f64) {
        let c = &self.key().contact;
        let (travel, hold) = (c.travel_m, c.hold_force_n);
        self.start(-travel, speed, hold, Until::Closed);
    }

    /// A replayed strike's state at its next sample, by computing the strike from rest up
    /// to it (the same operations the replayed samples recorded): the voice continues as a
    /// computed strike.
    fn materialize(&mut self) {
        let r = self.replay.take().expect("a replay");
        let pending = self.release_pending;
        self.zero();
        self.strike_from_here(self.k.speed(r.vel));
        for _ in 0..r.pos {
            self.contact_sample();
        }
        self.release_pending = pending;
    }

    fn off(&mut self) {
        match (self.phase, &self.run) {
            (Phase::Contact, Some(r)) if r.until == Until::Closed => self.release_pending = true,
            (Phase::Replay, _) => self.release_pending = true,
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
        let zt0 = zt + key.static_tangent - key.contact.hold_shift_m;
        self.start(zt0, vt, f, Until::Open);
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
        let zt = run.zt + key.contact.hold_shift_m;
        let c: Vec<C64> = (0..key.lam_h.len())
            .map(|r| {
                key.th_c[r]
                    .add(key.th_z[r].scale(zt))
                    .add(key.th_v[r].scale(run.vt))
            })
            .collect();
        self.transfer(&key.th_a, &key.th_b, &c, cols);
        self.onto_held();
    }

    /// The strike's end, its state on the held modes: held, or released at once when the
    /// key went up during it.
    fn onto_held(&mut self) {
        self.phase = Phase::Held;
        self.since_check = 0;
        if self.release_pending {
            self.release_pending = false;
            self.release();
        }
    }

    /// Samples of a replayed strike into `buf` from `i` (up to `to`); returns the next.
    fn replay_into(&mut self, buf: &mut [f64], n: usize, i: usize, to: usize) -> usize {
        let mut r = self.replay.expect("a replay");
        let table = self.strikes.clone().expect("a strike table");
        let rec = table.slots[r.slot].get().expect("a recorded strike");
        let take = (rec.emf.len() - r.pos).min(to - i);
        for (j, e) in rec.emf[r.pos..r.pos + take].iter().enumerate() {
            buf[i + j] += e[0];
            buf[n + i + j] += e[1];
        }
        r.pos += take;
        if r.pos == rec.emf.len() {
            self.zr.copy_from_slice(&rec.zr);
            self.zi.copy_from_slice(&rec.zi);
            self.replay = None;
            self.run = None;
            self.onto_held();
        } else {
            self.replay = Some(r);
        }
        i + take
    }

    /// One internal sample of a contact run in `s` substeps (note.py's loop): the unknowns
    /// the rubber's push fr, the anvil's fa and the rubber's sideways grip fg (its shear
    /// about where it first touched), a 3x3 Newton on a forward-difference Jacobian.
    fn substeps(&mut self) {
        #[cfg(target_arch = "x86_64")]
        if std::is_x86_feature_detected!("avx2") {
            // SAFETY: the CPU has AVX2 (checked above).
            unsafe { self.substeps_avx2() };
            return;
        }
        self.substeps_impl();
    }

    /// [`Voice::substeps_impl`] compiled for AVX2 (the same operations lane for lane: the
    /// same result bit for bit; no FMA).
    #[cfg(target_arch = "x86_64")]
    #[target_feature(enable = "avx2")]
    unsafe fn substeps_avx2(&mut self) {
        self.substeps_impl();
    }

    #[inline(always)]
    fn substeps_impl(&mut self) {
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
            if self.phase == Phase::Replay {
                i = self.replay_into(buf, n, i, to);
                continue;
            }
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

// --- Strikes from rest ------------------------------------------------------------

/// FNV-1a 64 over byte strings in turn.
fn fnv(parts: &[&[u8]]) -> u64 {
    let mut h: u64 = 0xcbf2_9ce4_8422_2325;
    for part in parts {
        for &b in *part {
            h ^= b as u64;
            h = h.wrapping_mul(0x0100_0000_01b3);
        }
    }
    h
}

/// The strike table file's format.
const STRIKES_FORMAT: u32 = 1;
const STRIKES_MAGIC: &[u8; 8] = b"CLAVSTRK";
/// Velocities a key is recorded at (MIDI 1-127).
const VELOCITIES: usize = 127;

/// One strike from rest as a voice computes it: the pickups' EMF (centre, bridge) at each
/// internal sample of the contact run, and the state the strike leaves on the held modes.
#[derive(Debug)]
pub struct StrikeRec {
    emf: Vec<[f64; 2]>,
    zr: Vec<f64>,
    zi: Vec<f64>,
}

impl StrikeRec {
    /// Key `i`'s strike from rest at velocity `vel`, computed by a fresh voice exactly as
    /// [`Voice::render_into`] runs it.
    fn record(model: &Arc<ClavModel>, i: usize, vel: u8, fs_int: f64, s: usize) -> StrikeRec {
        let mut v = Voice::new(model, i, fs_int, s);
        v.asleep = false;
        v.strike_from_here(model.speed(vel));
        let mut emf = Vec::new();
        loop {
            v.contact_sample();
            let (c, b) = v.emf(&v.step.rows, v.free.m, false);
            emf.push([c, b]);
            if v.run_done() {
                v.end_strike();
                break;
            }
        }
        StrikeRec {
            emf,
            zr: v.zr,
            zi: v.zi,
        }
    }

    fn bytes(&self) -> usize {
        16 * self.emf.len() + 8 * (self.zr.len() + self.zi.len())
    }
}

/// Every key's strike from rest at velocities 1-127, for one model at one internal rate and
/// substep count. Slots fill on demand ([`StrikeTable::ensure`]) or all at once
/// ([`StrikeTable::load_or_fill`]); a voice replays a slot only once it is filled.
pub struct StrikeTable {
    model: Arc<ClavModel>,
    fs_int: f64,
    s: usize,
    slots: Vec<OnceLock<StrikeRec>>,
    filled: AtomicUsize,
    replays: AtomicUsize,
    /// No longer shared (another wear of the same strings took its place): its filling
    /// stops and it isn't saved.
    abandoned: AtomicBool,
}

impl std::fmt::Debug for StrikeTable {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("StrikeTable")
            .field("fs_int", &self.fs_int)
            .field("s", &self.s)
            .field("filled", &self.filled())
            .field("slots", &self.slots.len())
            .finish()
    }
}

impl StrikeTable {
    /// An empty table for `model` at internal rate `fs_int` and `s` contact substeps.
    pub fn new(model: Arc<ClavModel>, fs_int: f64, s: usize) -> StrikeTable {
        let slots = (0..model.keys.len() * VELOCITIES)
            .map(|_| OnceLock::new())
            .collect();
        StrikeTable {
            model,
            fs_int,
            s,
            slots,
            filled: AtomicUsize::new(0),
            replays: AtomicUsize::new(0),
            abandoned: AtomicBool::new(false),
        }
    }

    /// Strikes replayed from this table so far (every medium sharing it).
    pub fn replays(&self) -> usize {
        self.replays.load(Ordering::Relaxed)
    }

    fn slot(i: usize, vel: u8) -> usize {
        i * VELOCITIES + (vel.clamp(1, 127) - 1) as usize
    }

    /// Slots recorded so far, and of how many.
    pub fn filled(&self) -> (usize, usize) {
        (self.filled.load(Ordering::Relaxed), self.slots.len())
    }

    pub fn complete(&self) -> bool {
        self.filled.load(Ordering::Relaxed) == self.slots.len()
    }

    /// Key `i`'s strike at `vel`, recorded now if it isn't yet.
    pub fn ensure(&self, i: usize, vel: u8) {
        self.slots[StrikeTable::slot(i, vel)].get_or_init(|| {
            self.filled.fetch_add(1, Ordering::Relaxed);
            StrikeRec::record(&self.model, i, vel, self.fs_int, self.s)
        });
    }

    /// Whether every slot of both tables holds the same record (unfilled slots count as
    /// equal only to unfilled ones).
    pub fn same_as(&self, other: &StrikeTable) -> bool {
        self.slots.len() == other.slots.len()
            && self
                .slots
                .iter()
                .zip(&other.slots)
                .all(|(a, b)| match (a.get(), b.get()) {
                    (Some(x), Some(y)) => x.emf == y.emf && x.zr == y.zr && x.zi == y.zi,
                    (None, None) => true,
                    _ => false,
                })
    }

    /// Bytes the filled slots hold.
    pub fn bytes(&self) -> usize {
        self.slots
            .iter()
            .filter_map(OnceLock::get)
            .map(StrikeRec::bytes)
            .sum()
    }

    /// Where this table is saved: `cache/clavinet/` under the repository's root, named
    /// `strikes_<what>_<code>.bin` (a worn model's `strikes_<what>w<wear>_<code>.bin`):
    /// `what` a hash of the strings' data and the rates, `wear` the wear's ([`wear_hash`]),
    /// `code` of the format and this crate's sources (a change to the code records it again;
    /// saving removes the tables of the same `what` and wear and older code, and a worn one
    /// the other wears' of the same `what`: one worn table is kept beside the compiled one).
    pub fn path(&self) -> PathBuf {
        let what = fnv(&[
            self.model.sha256.as_bytes(),
            &self.fs_int.to_bits().to_le_bytes(),
            &(self.s as u64).to_le_bytes(),
        ]);
        let code = fnv(&[&STRIKES_FORMAT.to_le_bytes(), crate::SOURCE_HASH.as_bytes()]);
        let wear = match self.model.wear {
            None => String::new(),
            Some(h) => format!("w{h:016x}"),
        };
        data_root()
            .join("cache")
            .join("clavinet")
            .join(format!("strikes_{what:016x}{wear}_{code:016x}.bin"))
    }

    /// Stop filling (the slots recorded so far stay) and don't save.
    fn abandon(&self) {
        self.abandoned.store(true, Ordering::Relaxed);
    }

    /// Every slot, from the saved file when there is one, else recorded on `threads`
    /// threads (each calling `on_thread` first: a priority, say) and saved. Blocks.
    pub fn load_or_fill(&self, threads: usize, on_thread: fn()) -> Result<(), String> {
        let path = self.path();
        if path.exists() && self.load(&path).is_ok() {
            return Ok(());
        }
        let next = AtomicUsize::new(0);
        std::thread::scope(|sc| {
            for _ in 0..threads.max(1) {
                sc.spawn(|| {
                    on_thread();
                    loop {
                        let j = next.fetch_add(1, Ordering::Relaxed);
                        if j >= self.slots.len() || self.abandoned.load(Ordering::Relaxed) {
                            return;
                        }
                        self.ensure(j / VELOCITIES, (j % VELOCITIES + 1) as u8);
                    }
                });
            }
        });
        if self.abandoned.load(Ordering::Relaxed) {
            return Ok(());
        }
        self.save(&path)
    }

    fn save(&self, path: &Path) -> Result<(), String> {
        let mut out = Vec::with_capacity(self.bytes() + 16 + 8 * self.slots.len());
        out.extend_from_slice(STRIKES_MAGIC);
        out.extend_from_slice(&STRIKES_FORMAT.to_le_bytes());
        out.extend_from_slice(&(self.slots.len() as u32).to_le_bytes());
        for slot in &self.slots {
            let rec = slot.get().ok_or("an unfilled slot")?;
            out.extend_from_slice(&(rec.emf.len() as u32).to_le_bytes());
            out.extend_from_slice(&(rec.zr.len() as u32).to_le_bytes());
            for e in &rec.emf {
                out.extend_from_slice(&e[0].to_le_bytes());
                out.extend_from_slice(&e[1].to_le_bytes());
            }
            for x in rec.zr.iter().chain(&rec.zi) {
                out.extend_from_slice(&x.to_le_bytes());
            }
        }
        let dir = path.parent().ok_or("no directory")?;
        std::fs::create_dir_all(dir).map_err(|e| e.to_string())?;
        let tmp = path.with_extension(format!("tmp{}", std::process::id()));
        std::fs::write(&tmp, &out).map_err(|e| e.to_string())?;
        std::fs::rename(&tmp, path).map_err(|e| e.to_string())?;
        // The same strings' tables from older code (and the old naming, strikes_<hash>.bin);
        // a worn table's, every other wear's of the same strings.
        let name = path
            .file_name()
            .and_then(|n| n.to_str())
            .unwrap_or_default();
        let what = &name[..name.len().min("strikes_".len() + 16)];
        // the name up to its code: "strikes_<what>" or "strikes_<what>w<wear>"
        let own = &name[..name.len().saturating_sub("_".len() + 16 + ".bin".len())];
        let worn = self.model.wear.is_some();
        for e in std::fs::read_dir(dir).map_err(|e| e.to_string())?.flatten() {
            let n = e.file_name().to_string_lossy().into_owned();
            let stale = n != name
                && n.ends_with(".bin")
                && (n.starts_with(&format!("{own}_"))
                    || (worn && n.starts_with(&format!("{what}w")))
                    || (n.starts_with("strikes_") && n.len() == 28));
            if stale {
                let _ = std::fs::remove_file(e.path());
            }
        }
        Ok(())
    }

    fn load(&self, path: &Path) -> Result<(), String> {
        let b = std::fs::read(path).map_err(|e| e.to_string())?;
        let mut at = 0usize;
        let mut take = |n: usize| -> Result<&[u8], String> {
            let s = b.get(at..at + n).ok_or("the strike table is truncated")?;
            at += n;
            Ok(s)
        };
        let u32_ = |s: &[u8]| u32::from_le_bytes(s.try_into().expect("4 bytes")) as usize;
        let f64_ = |s: &[u8]| f64::from_le_bytes(s.try_into().expect("8 bytes"));
        if take(8)? != STRIKES_MAGIC
            || u32_(take(4)?) != STRIKES_FORMAT as usize
            || u32_(take(4)?) != self.slots.len()
        {
            return Err("not this strike table".into());
        }
        // Each key's state length, as its voice holds it (a record must fit it exactly).
        let want: Vec<usize> = (0..self.model.keys.len())
            .map(|i| Voice::new(&self.model, i, self.fs_int, self.s).zr.len())
            .collect();
        let mut recs = Vec::with_capacity(self.slots.len());
        for j in 0..self.slots.len() {
            let len = u32_(take(4)?);
            let m = u32_(take(4)?);
            if m != want[j / VELOCITIES] {
                return Err("the strike table's states don't fit the voices".into());
            }
            let mut emf = Vec::with_capacity(len);
            for _ in 0..len {
                let e = take(16)?;
                emf.push([f64_(&e[..8]), f64_(&e[8..])]);
            }
            let zr = take(8 * m)?.chunks_exact(8).map(f64_).collect();
            let zi = take(8 * m)?.chunks_exact(8).map(f64_).collect();
            recs.push(StrikeRec { emf, zr, zi });
        }
        // The whole file read and checked: fill the slots.
        for (slot, rec) in self.slots.iter().zip(recs) {
            if slot.set(rec).is_ok() {
                self.filled.fetch_add(1, Ordering::Relaxed);
            }
        }
        Ok(())
    }
}

/// How a process that plays live fills its strike tables: threads and a hook each thread
/// runs first (its priority).
#[derive(Debug, Clone, Copy)]
struct FillPolicy {
    threads: usize,
    max_rate_hz: f64,
    on_thread: fn(),
}

static FILL: OnceLock<FillPolicy> = OnceLock::new();

type Tables = Mutex<HashMap<(String, u64, usize), Arc<StrikeTable>>>;

fn tables() -> &'static Tables {
    static TABLES: OnceLock<Tables> = OnceLock::new();
    TABLES.get_or_init(Default::default)
}

/// From now on, every medium this process builds at an internal rate up to `max_rate_hz`
/// replays strikes from rest, its table loaded or recorded in the background (once per
/// table) on `threads` threads that each run `on_thread` first (faster ones, a production
/// render's, compute every strike). Call once, before playing (the app); the first call
/// wins.
pub fn fill_strike_tables(threads: usize, max_rate_hz: f64, on_thread: fn()) {
    let _ = FILL.set(FillPolicy {
        threads,
        max_rate_hz,
        on_thread,
    });
}

/// Every shared strike table's progress: (slots filled, slots), in no order.
pub fn strike_tables_filled() -> Vec<(usize, usize)> {
    tables()
        .lock()
        .expect("strike tables")
        .values()
        .map(|t| t.filled())
        .collect()
}

/// The shared table for `model` at `fs_int` and `s`, if this process fills tables: created
/// (and its filling started) on first use.
fn shared_table(model: &Arc<ClavModel>, fs_int: f64, s: usize) -> Option<Arc<StrikeTable>> {
    let policy = *FILL.get()?;
    if fs_int > policy.max_rate_hz {
        return None;
    }
    let key = (model.id(), fs_int.to_bits(), s);
    let mut all = tables().lock().expect("strike tables");
    if let Some(t) = all.get(&key) {
        return Some(t.clone());
    }
    if model.wear.is_some() {
        // One worn table per strings and rates: the media that hold the others keep theirs.
        let other = format!("{}w", model.sha256);
        all.retain(|(id, f, n), t| {
            let keep = !(id.starts_with(&other) && *f == key.1 && *n == key.2);
            if !keep {
                t.abandon();
            }
            keep
        });
    }
    let t = Arc::new(StrikeTable::new(model.clone(), fs_int, s));
    all.insert(key, t.clone());
    let filler = t.clone();
    let spawned = std::thread::Builder::new()
        .name("clavinet strikes".into())
        .spawn(move || {
            (policy.on_thread)();
            if let Err(e) = filler.load_or_fill(policy.threads, policy.on_thread) {
                eprintln!("clavinet: the strike table wasn't saved: {e}");
            }
        });
    if spawned.is_err() {
        eprintln!("clavinet: no thread for the strike table: strikes computed");
    }
    Some(t)
}

/// What every voice reads: nothing beyond its own model (each holds the shared Arc).
#[derive(Debug)]
pub struct ClavCtx {
    model: Arc<ClavModel>,
}

impl crate::keyed::KeyVoice for Voice {
    type Ctx = ClavCtx;

    fn asleep(&self) -> bool {
        self.asleep && !matches!(self.phase, Phase::Contact | Phase::Replay)
    }

    fn event(&mut self, ev: NoteEvent, ctx: &ClavCtx) {
        match ev {
            NoteEvent::On { velocity, .. } => self.on(velocity, ctx.model.speed(velocity)),
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
        let (model, fs_int, s) = Medium::rates(el, fs)?;
        let strikes = shared_table(&model, fs_int, s);
        Medium::with_strikes(el, fs, n, strikes)
    }

    /// The model, internal rate and contact substeps a medium for `el` at step rate `fs`
    /// runs at (a [`StrikeTable`] for it is made at these).
    pub fn rates(
        el: &crate::ir::ClavStrings,
        fs: f64,
    ) -> Result<(Arc<ClavModel>, f64, usize), String> {
        let model = load(el)?;
        let k = ((el.rate_hz / fs) - 1e-9).ceil().max(1.0) as usize;
        let s = ((el.contact_rate_hz / (fs * k as f64)) - 1e-9)
            .ceil()
            .max(1.0) as usize;
        Ok((model, fs * k as f64, s))
    }

    /// [`Medium::with_workers`] replaying strikes from rest from `strikes` (None: every
    /// strike computed); the table must be for this medium's [`Medium::rates`].
    pub fn with_strikes(
        el: &crate::ir::ClavStrings,
        fs: f64,
        n: usize,
        strikes: Option<Arc<StrikeTable>>,
    ) -> Result<Medium, String> {
        let (model, fs_int, s) = Medium::rates(el, fs)?;
        let k = (fs_int / fs).round() as usize;
        if let Some(t) = &strikes
            && (t.model.id() != model.id() || t.fs_int != fs_int || t.s != s)
        {
            return Err(format!(
                "{}: a strike table for other rates or data",
                el.name
            ));
        }
        let voices = (0..model.keys.len())
            .map(|i| {
                let mut v = Voice::new(&model, i, fs_int, s);
                v.strikes = strikes.clone();
                (model.keys[i].note, v)
            })
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
            && el.wear == self.el.wear
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
            dh: vec![1.0, 2.0, 3.0].into(),
        };
        // h = 2 - y: y = 0 reads the middle point, y = -0.5 halfway up, y = 5 the floor.
        assert_eq!(t.emf(0.0, 1.0), 2.0);
        assert_eq!(t.emf(-0.5, 1.0), 2.5);
        assert_eq!(t.emf(5.0, 2.0), 2.0);
        assert_eq!(t.emf(-5.0, 1.0), 3.0);
    }
}
