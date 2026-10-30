//! Circuit file -> circuit IR: the generic builder (the port of
//! `varimu/circuit/builder.py`; its docstring lists the macro parts and their params).
//!
//! `build_ir(lib, spec, params, cores)` resolves the derived values, makes the device
//! model instances, expands every part of every section and applies the tolerance draws.
//! The SPICE text Python can also emit isn't needed here: the app runs circuitsim.
//!
//! Tolerance: nominal units only. A nonzero `spread` is refused, because the draws are
//! numpy's (PCG64) and porting them is a separate decision (docs/NATIVE_APP_PLAN.md); at
//! spread 0 every factor is exactly 1, as in Python.
//!
//! Noise (device builder B5): the file's `noise` block, or [`build_ir_noise`]'s setting;
//! each part's noise elements follow its own, as Python's builder places them (its
//! docstring says which parts get which).

use std::collections::{BTreeSet, HashMap, HashSet};

use circuitsim::ir::{
    CircuitIr, Coupling, Device, DeviceModel, Element, Inductor, MagneticCore, NoiseCurrent,
    NoiseSpec, Probe, Section, SineSource, TubeNoise, VoltageSource,
};
use circuitsim::noise as nz;

use crate::devices::Library;
use crate::parts::{self, CoreSpec, Instance, WindingSpec};
use crate::speaker::{self, Cabinet};
use crate::spec::{CircuitSpec, Params};
use crate::yaml::{Map, Value};
use crate::{Error, derived, versions};

/// IR version Python writes (`IR_VERSION` in varimu/circuit/ir.py).
pub const IR_VERSION: u32 = 3;

/// Transformer cores: Jiles-Atherton devices, or each core's linear limit.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Cores {
    Ja,
    Linear,
}

impl Cores {
    pub fn parse(s: &str) -> Result<Cores, Error> {
        match s {
            "ja" => Ok(Cores::Ja),
            "linear" => Ok(Cores::Linear),
            _ => Err(Error(format!("unknown core model '{s}' (ja | linear)"))),
        }
    }
}

const PART_KEYS: [&str; 3] = ["tolerance", "source", "notes"];
const DEVICE_KEYS: [&str; 11] = [
    "device",
    "name",
    "instance",
    "tolerance",
    "parallel",
    "emission",
    "mu",
    "grid_contact_v",
    "area",
    "source",
    "notes",
];

// --- Tolerance -------------------------------------------------------------------------

struct Tolerance {
    classes: HashMap<String, String>,
    combined: Vec<(String, Vec<String>)>,
}

impl Tolerance {
    fn parts_of(&self, designator: &str) -> Vec<String> {
        self.combined
            .iter()
            .find(|(d, _)| d == designator)
            .map_or_else(|| vec![designator.to_string()], |(_, ps)| ps.clone())
    }

    /// The factor of an element standing for part `designator`: 1 at spread 0. Err: the
    /// parts without a class.
    fn factor(&self, designator: &str) -> Result<f64, Vec<String>> {
        let missing: Vec<String> = self
            .parts_of(designator)
            .into_iter()
            .filter(|x| !self.classes.contains_key(x))
            .collect();
        if missing.is_empty() {
            Ok(1.0)
        } else {
            Err(missing)
        }
    }

    fn apply(&self, els: Vec<Element>, designator: &str) -> Result<Vec<Element>, Vec<String>> {
        let f = self.factor(designator)?;
        Ok(els
            .into_iter()
            .map(|el| match el {
                Element::Resistor(mut r) => {
                    r.r_ohm *= f;
                    Element::Resistor(r)
                }
                Element::Capacitor(mut c) => {
                    c.c_f *= f;
                    Element::Capacitor(c)
                }
                other => other,
            })
            .collect())
    }
}

// --- Context ---------------------------------------------------------------------------

struct Context<'a> {
    lib: &'a Library,
    spec: &'a CircuitSpec,
    q: Params,
    cores: Cores,
    tolerance: Option<Tolerance>,
    models: Vec<(String, DeviceModel)>,
    core_models: Vec<MagneticCore>,
    used_devices: HashSet<String>,
    designators: HashSet<String>,
    missing_class: BTreeSet<String>,
    section_tolerance: Option<Value>,
    /// Noise sources on (B5): the seed, the resistors' temperature, K_f, the mains
    /// wander's rms.
    noise: Option<(u64, f64, f64, f64)>,
    /// The `mains` parts' sources, in order of expansion.
    mains_sines: Vec<String>,
    /// Model name -> its `devices` entry's `parallel` (1 for `instance: false`).
    parallel: HashMap<String, i64>,
}

/// A build's noise ([`build_ir_noise`]), as Python's `build_ir(..., noise=)`.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Noise {
    /// The file's `noise` block (none without one).
    File,
    Off,
    /// On, with the block's seed (0 without a block).
    On,
    /// On, with this seed.
    Seed(u64),
}

/// Parts whose resistors are resistors (their noise), and the param holding their value.
const NOISY: [(&str, Option<&str>); 6] = [
    ("R", Some("r")),
    ("pot", Some("r")),
    ("rheostat", Some("r")),
    ("tapped_pot", Some("r")),
    ("t_pad", Some("z")),
    ("transformer", None),
];

/// Whether a part's value (a key or {value, source}) is sourced `numerical:`.
fn numerical(ctx: &Context, x: Option<&Value>) -> bool {
    let starts =
        |src: Option<&Value>| src.is_some_and(|s| s.py_str().trim().starts_with("numerical"));
    match x {
        Some(Value::Str(k)) => {
            for table in [
                &ctx.spec.values,
                &ctx.spec.controls,
                &ctx.spec.device_params,
            ] {
                if let Some(e) = table.get(k) {
                    return starts(e.as_map().and_then(|m| m.get("source")));
                }
            }
            false
        }
        Some(Value::Map(m)) => starts(m.get("source")),
        _ => false,
    }
}

/// A part's noise elements (Python's `_noise_elements`).
fn noise_elements(ctx: &Context, kind: &str, entry: &Map, els: &[Element]) -> Vec<Element> {
    let Some((_, temperature, kf, _)) = ctx.noise else {
        return Vec::new();
    };
    let mut out = Vec::new();
    if let Some((_, key)) = NOISY.iter().find(|(k, _)| *k == kind) {
        if key.is_some_and(|k| numerical(ctx, entry.get(k))) {
            return out;
        }
        let cores: HashSet<&str> = els
            .iter()
            .filter_map(|e| match e {
                Element::Winding(w) => Some(w.core.as_str()),
                _ => None,
            })
            .collect();
        for e in els {
            if let Element::Resistor(r) = e
                && !cores.contains(r.a.as_str())
                && !cores.contains(r.b.as_str())
            {
                out.push(Element::NoiseCurrent(NoiseCurrent {
                    name: format!("IN_{}", r.name),
                    a: r.a.clone(),
                    b: r.b.clone(),
                    psd_a2_hz: 4.0 * nz::K_B * temperature / r.r_ohm,
                }));
            }
        }
    } else if kind == "device" {
        for e in els {
            let Element::Device(d) = e else { continue };
            let Some((_, m)) = ctx.models.iter().find(|(_, m)| m.name() == d.model) else {
                continue;
            };
            let pentode = match m {
                DeviceModel::Triode(_) => false,
                DeviceModel::Pentode(_) => true,
                _ => continue,
            };
            let n = ctx.parallel.get(m.name()).copied().unwrap_or(1);
            out.push(Element::TubeNoise(TubeNoise {
                name: format!("BN_{}", d.name),
                device: d.name.clone(),
                shot_k: nz::shot_k(),
                partition: if pentode { nz::PARTITION } else { 0.0 },
                flicker_v2: kf / n as f64,
            }));
        }
    }
    out
}

/// The build's noise (Python's `_noise`).
fn noise_setting(ctx: &Context, noise: Noise) -> Result<Option<(u64, f64, f64, f64)>, Error> {
    let block = ctx.spec.noise.as_ref();
    let seed = match noise {
        Noise::Off => return Ok(None),
        Noise::File if block.is_none() => return Ok(None),
        Noise::File | Noise::On => match block.and_then(|b| b.get("seed")) {
            Some(Value::Int(i)) => *i as u64,
            _ => 0,
        },
        Noise::Seed(s) => s,
    };
    let get = |k: &str, default: f64| -> Result<f64, Error> {
        match block.and_then(|b| b.get(k)) {
            None => Ok(default),
            Some(x) => {
                let w = format!("noise.{k}");
                let v = ctx.physical(&w, x)?;
                ctx.float(&w, &v)
            }
        }
    };
    Ok(Some((
        seed,
        get("temperature_k", nz::RESISTOR_T_K)?,
        get("flicker_v2", nz::FLICKER_V2)?,
        get("mains_rms", nz::MAINS_RMS)?,
    )))
}

impl Context<'_> {
    fn fail(&self, where_: &str, msg: impl std::fmt::Display) -> Error {
        Error(format!("{}: {where_}: {msg}", self.spec.path.display()))
    }

    fn reference(&self, where_: &str, key: &str) -> Result<Value, Error> {
        if let Some(v) = self.q.get(key) {
            return Ok(v.clone());
        }
        if self.spec.device_params.contains(key) {
            return Ok(Value::Null); // null: the device file's value
        }
        Err(self.fail(where_, format!("unknown parameter '{key}'")))
    }

    /// A physical value: a parameter key or {value, source}; never a bare number.
    fn physical(&self, where_: &str, x: &Value) -> Result<Value, Error> {
        match x {
            Value::Str(k) => self.reference(where_, k),
            Value::Map(m) if m.contains("value") => {
                let ok = m
                    .get("source")
                    .is_some_and(|s| !s.py_str().trim().is_empty());
                if !ok {
                    return Err(self.fail(where_, "an inline value needs a `source`"));
                }
                Ok(m.get("value").unwrap().clone())
            }
            _ => Err(self.fail(
                where_,
                format!("{x}: give a parameter key or {{value, source}}"),
            )),
        }
    }

    /// A structural number (a ratio, phase, position, count) or a physical value.
    fn number(&self, where_: &str, x: &Value) -> Result<Value, Error> {
        match x {
            Value::Int(_) | Value::Float(_) => Ok(x.clone()),
            _ => self.physical(where_, x),
        }
    }

    fn count(&self, where_: &str, x: &Value) -> Result<i64, Error> {
        let v = self.number(where_, x)?;
        match v.as_f64() {
            Some(f) if f.trunc() == f && f >= 1.0 => Ok(f as i64),
            _ => Err(self.fail(where_, format!("{} is not a count", v.py_str()))),
        }
    }

    /// A name (a device file, a material): a parameter holding it, or the name.
    fn text(&self, where_: &str, x: &Value) -> Result<String, Error> {
        let Value::Str(s) = x else {
            return Err(self.fail(where_, format!("{x} is not a name")));
        };
        Ok(match self.q.get(s) {
            Some(v) => v.py_str(),
            None => s.clone(),
        })
    }

    fn model(&mut self, where_: &str, key: &Value) -> Result<String, Error> {
        let k = key.py_str();
        if !matches!(key, Value::Str(_)) || !self.models.iter().any(|(m, _)| *m == k) {
            return Err(self.fail(where_, format!("unknown device {key} (not in `devices`)")));
        }
        self.used_devices.insert(k.clone());
        Ok(k)
    }

    fn model_of(&self, key: &str) -> &DeviceModel {
        &self.models.iter().find(|(k, _)| k == key).unwrap().1
    }

    fn float(&self, where_: &str, v: &Value) -> Result<f64, Error> {
        v.as_f64()
            .ok_or_else(|| self.fail(where_, format!("{v} is not a number")))
    }
}

// --- Macro parts -------------------------------------------------------------------------

#[derive(Clone, Copy, PartialEq)]
enum Kind {
    Physical,
    Number,
    Count,
    Device,
    Raw,
}

/// A param: its kind and default (None: required; Some(Null): defaults to None).
struct Param(&'static str, Kind, Option<Value>);

struct Macro {
    n_nodes: Option<usize>,
    params: Vec<Param>,
    toleranced: bool,
}

const MACROS: [&str; 17] = [
    "R",
    "C",
    "L",
    "K",
    "V",
    "sine",
    "mains",
    "device",
    "pot",
    "rheostat",
    "tapped_pot",
    "t_pad",
    "switch",
    "transformer",
    "bridge",
    "vr_tube",
    "speaker",
];

fn macro_of(kind: &str) -> Macro {
    use Kind::*;
    let p = |n, k| Param(n, k, None);
    let opt = |n, k| Param(n, k, Some(Value::Null));
    let num = |n, v: f64| Param(n, Number, Some(Value::Float(v)));
    let (n_nodes, params, toleranced) = match kind {
        "R" => (
            Some(2),
            vec![
                p("r", Physical),
                Param("parallel", Count, Some(Value::Int(1))),
            ],
            true,
        ),
        "C" => (Some(2), vec![p("c", Physical), opt("v0", Physical)], true),
        "L" => (Some(2), vec![p("l", Physical)], false),
        "K" => (Some(2), vec![p("k", Physical)], false),
        "V" => (Some(2), vec![p("v", Physical)], false),
        "sine" => (
            Some(2),
            vec![
                p("amplitude_v", Physical),
                p("freq_hz", Physical),
                num("offset_v", 0.0),
                num("phase_deg", 0.0),
            ],
            false,
        ),
        "mains" => (
            Some(2),
            vec![p("v_rms", Physical), num("phase_deg", 0.0)],
            false,
        ),
        "device" => (None, vec![p("model", Device)], false),
        "pot" | "rheostat" => (
            Some(if kind == "pot" { 3 } else { 2 }),
            vec![
                p("r", Physical),
                p("at", Number),
                opt("taper_mid", Physical),
            ],
            true,
        ),
        "tapped_pot" => (
            Some(4),
            vec![p("r", Physical), p("at", Number), p("tap", Number)],
            true,
        ),
        "t_pad" => (Some(3), vec![p("z", Physical), p("atten_db", Number)], true),
        "switch" => (None, vec![p("parts", Raw)], false),
        "transformer" => (
            None,
            vec![
                p("core", Raw),
                p("turns", Physical),
                p("leakage_h", Physical),
                opt("interwinding", Raw),
            ],
            false,
        ),
        "bridge" => (
            Some(4),
            vec![
                p("model", Device),
                opt("arm_c_f_per_area", Physical),
                opt("area", Physical),
            ],
            false,
        ),
        "vr_tube" => (
            Some(3),
            vec![
                p("model", Device),
                p("operating_v", Physical),
                p("ref_current_a", Physical),
            ],
            false,
        ),
        "speaker" => (
            Some(3),
            vec![
                p("component", Raw),
                p("distance_m", Physical),
                p("width_m", Physical),
                p("height_m", Physical),
                p("depth_m", Physical),
                Param("offset_x_m", Physical, Some(Value::Float(0.0))),
                Param("offset_y_m", Physical, Some(Value::Float(0.0))),
            ],
            false,
        ),
        _ => unreachable!("{kind}"),
    };
    Macro {
        n_nodes,
        params,
        toleranced,
    }
}

type Args = HashMap<&'static str, Value>;

fn resolve_params(ctx: &mut Context, name: &str, m: &Macro, entry: &Map) -> Result<Args, Error> {
    let mut out = Args::new();
    for Param(k, kind, default) in &m.params {
        let Some(x) = entry.get(k) else {
            match default {
                None => return Err(ctx.fail(name, format!("needs `{k}`"))),
                Some(d) => {
                    out.insert(k, d.clone());
                    continue;
                }
            }
        };
        let w = format!("{name}.{k}");
        let v = match kind {
            Kind::Physical => ctx.physical(&w, x)?,
            Kind::Number => ctx.number(&w, x)?,
            Kind::Count => Value::Int(ctx.count(&w, x)?),
            Kind::Device => Value::Str(ctx.model(&w, x)?),
            Kind::Raw => x.clone(),
        };
        out.insert(k, v);
    }
    Ok(out)
}

fn expand_part(
    ctx: &mut Context,
    name: &str,
    entry: &Value,
    extra: &[&str],
) -> Result<Vec<Element>, Error> {
    let Some(entry) = entry.as_map() else {
        return Err(ctx.fail(name, "a part is a mapping {<macro>: <connection>, ...}"));
    };
    let kinds: Vec<&str> = entry.keys().filter(|k| MACROS.contains(k)).collect();
    if kinds.len() != 1 {
        let mut all = MACROS.to_vec();
        all.sort_unstable();
        return Err(ctx.fail(
            name,
            format!("needs exactly one macro of {all:?}, has {kinds:?}"),
        ));
    }
    let kind = kinds[0];
    let m = macro_of(kind);
    let mut unknown: Vec<&str> = entry
        .keys()
        .filter(|k| {
            *k != kind
                && !m.params.iter().any(|p| p.0 == *k)
                && !PART_KEYS.contains(k)
                && !extra.contains(k)
        })
        .collect();
    unknown.sort_unstable();
    if !unknown.is_empty() {
        return Err(ctx.fail(name, format!("{kind}: unknown keys {unknown:?}")));
    }
    let conn = entry.get(kind).unwrap();
    let nodes: Vec<String> = match m.n_nodes {
        Some(n) => match conn.as_list() {
            Some(l) if l.len() == n => l.iter().map(Value::py_str).collect(),
            _ => return Err(ctx.fail(name, format!("{kind} takes {n} nodes, got {conn}"))),
        },
        None => Vec::new(),
    };
    let a = resolve_params(ctx, name, &m, entry)?;
    let els = expand(ctx, kind, name, conn, &nodes, &a)?;
    if kind == "mains" {
        ctx.mains_sines.push(name.to_string());
    }
    let tol = entry
        .get("tolerance")
        .cloned()
        .or_else(|| ctx.section_tolerance.clone())
        .unwrap_or(Value::Null);
    let none = Value::Str("none".into());
    if !tol.is_null() && tol != none {
        return Err(ctx.fail(
            name,
            format!("tolerance: {tol} (a part's class is in the tolerance block)"),
        ));
    }
    let mut els = els;
    if m.toleranced
        && tol != none
        && let Some(t) = &ctx.tolerance
    {
        ctx.designators.insert(name.to_string());
        match t.apply(els.clone(), name) {
            Ok(applied) => els = applied,
            Err(missing) => ctx.missing_class.extend(missing),
        }
    }
    if ctx.noise.is_some() {
        let extra = noise_elements(ctx, kind, entry, &els);
        els.extend(extra);
    }
    Ok(els)
}

fn n2(nodes: &[String]) -> (&str, &str) {
    (&nodes[0], &nodes[1])
}

fn expand(
    ctx: &mut Context,
    kind: &str,
    name: &str,
    conn: &Value,
    nodes: &[String],
    a: &Args,
) -> Result<Vec<Element>, Error> {
    let f = |k: &str| -> Result<f64, Error> { ctx.float(&format!("{name}.{k}"), &a[k]) };
    let opt = |k: &str| -> Result<Option<f64>, Error> {
        match &a[k] {
            Value::Null => Ok(None),
            v => Ok(Some(ctx.float(&format!("{name}.{k}"), v)?)),
        }
    };
    let s = String::from;
    Ok(match kind {
        "R" => {
            let r = f("r")?;
            let parallel = a["parallel"].as_f64().unwrap();
            let r = if parallel == 1.0 { r } else { r / parallel };
            let (x, y) = n2(nodes);
            vec![parts::resistor(name, x, y, r)]
        }
        "C" => {
            let (x, y) = n2(nodes);
            let mut el = parts::capacitor(name, x, y, f("c")?);
            if let (Some(v0), Element::Capacitor(c)) = (opt("v0")?, &mut el) {
                c.v0_v = Some(v0);
            }
            vec![el]
        }
        "L" => vec![Element::Inductor(Inductor {
            name: s(name),
            a: nodes[0].clone(),
            b: nodes[1].clone(),
            l_h: f("l")?,
        })],
        "K" => vec![Element::Coupling(Coupling {
            name: s(name),
            l_a: nodes[0].clone(),
            l_b: nodes[1].clone(),
            k: f("k")?,
        })],
        "V" => vec![Element::VoltageSource(VoltageSource {
            name: s(name),
            pos: nodes[0].clone(),
            neg: nodes[1].clone(),
            dc_v: f("v")?,
        })],
        "sine" => vec![Element::SineSource(SineSource {
            name: s(name),
            pos: nodes[0].clone(),
            neg: nodes[1].clone(),
            offset_v: f("offset_v")?,
            amplitude_v: f("amplitude_v")?,
            freq_hz: f("freq_hz")?,
            phase_deg: f("phase_deg")?,
        })],
        "mains" => {
            let Some(m) = ctx.spec.mains.clone() else {
                return Err(ctx.fail(name, "a mains part needs the file's `mains` block"));
            };
            let get = |k: &str| m.get(k).cloned().unwrap_or(Value::Null);
            let mains_v = ctx.reference("mains", &get("v_rms").py_str())?;
            let rated = ctx.physical("mains.rated_v_rms", &get("rated_v_rms"))?;
            let hz = ctx.reference("mains", &get("hz").py_str())?;
            vec![parts::mains_sine(
                name,
                &nodes[0],
                &nodes[1],
                f("v_rms")?,
                ctx.float("mains", &mains_v)?,
                ctx.float("mains.rated_v_rms", &rated)?,
                ctx.float("mains", &hz)?,
                f("phase_deg")?,
            )]
        }
        "device" => {
            let model = ctx.model_of(a["model"].as_str().unwrap());
            let pins = model.pins();
            match conn.as_list() {
                Some(l) if l.len() == pins.len() => vec![Element::Device(Device {
                    name: s(name),
                    model: model.name().to_string(),
                    nodes: l.iter().map(Value::py_str).collect(),
                })],
                _ => {
                    return Err(ctx.fail(
                        name,
                        format!("device {} has pins {pins:?}, got {conn}", model.name()),
                    ));
                }
            }
        }
        "pot" => parts::pot(
            name,
            &nodes[0],
            &nodes[1],
            &nodes[2],
            f("r")?,
            f("at")?,
            opt("taper_mid")?,
        )
        .map_err(|e| ctx.fail(name, e.0))?,
        "rheostat" => vec![
            parts::rheostat(
                name,
                &nodes[0],
                &nodes[1],
                f("r")?,
                f("at")?,
                opt("taper_mid")?,
            )
            .map_err(|e| ctx.fail(name, e.0))?,
        ],
        "tapped_pot" => parts::tapped_pot(
            name,
            &nodes[0],
            &nodes[1],
            &nodes[2],
            &nodes[3],
            f("r")?,
            f("at")?,
            f("tap")?,
        ),
        "t_pad" => parts::t_pad(
            name,
            &nodes[0],
            &nodes[1],
            &nodes[2],
            f("z")?,
            f("atten_db")?,
        ),
        "switch" => return switch(ctx, name, conn, &a["parts"]),
        "transformer" => return transformer(ctx, name, conn, a),
        "bridge" => {
            let mut c = 0.0;
            if let Some(per_area) = opt("arm_c_f_per_area")? {
                let Some(area) = opt("area")? else {
                    return Err(ctx.fail(name, "arm_c_f_per_area needs `area`"));
                };
                c = per_area * area;
            }
            let model = ctx.model_of(a["model"].as_str().unwrap());
            parts::bridge(name, [&nodes[0], &nodes[1], &nodes[2], &nodes[3]], model, c)
        }
        "vr_tube" => {
            let DeviceModel::JunctionDiode(model) = ctx.model_of(a["model"].as_str().unwrap())
            else {
                return Err(ctx.fail(
                    name,
                    "vr_tube: the model is a junction diode (the tube's slope)",
                ));
            };
            parts::vr_tube(
                name,
                [&nodes[0], &nodes[1], &nodes[2]],
                model,
                f("operating_v")?,
                f("ref_current_a")?,
            )
        }
        "speaker" => return speaker_part(ctx, name, nodes, a),
        _ => unreachable!("{kind}"),
    })
}

fn speaker_part(
    ctx: &mut Context,
    name: &str,
    nodes: &[String],
    a: &Args,
) -> Result<Vec<Element>, Error> {
    let where_ = format!("{name}.component");
    let reference = ctx.text(&where_, &a["component"])?;
    let model = versions::require_pinned(&ctx.lib.components_dir(), &reference)
        .and_then(|r| ctx.lib.speaker(&r.to_string()))
        .map_err(|e| ctx.fail(&where_, e.0))?;
    let f = |k: &str| ctx.float(&format!("{name}.{k}"), &a[k]);
    let cab = Cabinet {
        width_m: f("width_m")?,
        height_m: f("height_m")?,
        depth_m: f("depth_m")?,
        offset_x_m: f("offset_x_m")?,
        offset_y_m: f("offset_y_m")?,
    };
    let distance = f("distance_m")?;
    Ok(speaker::speaker(
        name, &nodes[0], &nodes[1], &nodes[2], &model, &cab, distance,
    ))
}

fn switch(
    ctx: &mut Context,
    name: &str,
    conn: &Value,
    sub_parts: &Value,
) -> Result<Vec<Element>, Error> {
    let control = match conn {
        Value::Str(c) if ctx.spec.controls.contains(c) => c.clone(),
        _ => return Err(ctx.fail(name, format!("switch: {conn} is not a control"))),
    };
    let pos = ctx.reference(name, &control)?;
    let position = ctx.float(name, &pos)?.trunc();
    let mut els = Vec::new();
    let empty = Map::default();
    let sub_parts = match sub_parts {
        Value::Null => &empty,
        Value::Map(m) => m,
        _ => return Err(ctx.fail(name, "switch: `parts` is a mapping")),
    };
    for (sub, entry) in sub_parts.iter() {
        let where_ = format!("{name}.{sub}");
        let positions = entry.as_map().and_then(|m| m.get("in"));
        let positions = match positions {
            None => None,
            Some(Value::List(l)) => Some(l.clone()),
            Some(_) => return Err(ctx.fail(&where_, "`in` is a list of positions")),
        };
        let part = expand_part(ctx, sub, entry, &["in"])?;
        let on = positions.is_none_or(|ps| ps.iter().any(|p| p.as_f64() == Some(position)));
        if on {
            els.extend(part);
        }
    }
    Ok(els)
}

fn transformer(
    ctx: &mut Context,
    name: &str,
    conn: &Value,
    a: &Args,
) -> Result<Vec<Element>, Error> {
    let Some(windings_map) = conn.as_map().filter(|m| !m.is_empty()) else {
        return Err(ctx.fail(
            name,
            "transformer: a mapping of windings {label: {nodes, ...}}",
        ));
    };
    let mut windings = Vec::new();
    for (label, w) in windings_map.iter() {
        let where_ = format!("{name}.{label}");
        let bad = || ctx.fail(&where_, "a winding is {nodes: [dot, other], ratio, r, c}");
        let w = w.as_map().ok_or_else(bad)?;
        let nodes = w.get("nodes").and_then(Value::as_list);
        let unknown = w.keys().any(|k| !["nodes", "ratio", "r", "c"].contains(&k));
        let Some(nodes) = nodes.filter(|n| n.len() == 2 && !unknown) else {
            return Err(bad());
        };
        let ratio = match w.get("ratio") {
            Some(r) => ctx.number(&format!("{where_}.ratio"), r)?,
            None => Value::Float(1.0),
        };
        let phys = |k: &str| -> Result<f64, Error> {
            match w.get(k) {
                Some(x) => {
                    let w2 = format!("{where_}.{k}");
                    let v = ctx.physical(&w2, x)?;
                    ctx.float(&w2, &v)
                }
                None => Ok(0.0),
            }
        };
        windings.push(WindingSpec {
            label: label.to_string(),
            dot: nodes[0].py_str(),
            other: nodes[1].py_str(),
            ratio: ctx.float(&where_, &ratio)?,
            r_ohm: phys("r")?,
            c_f: phys("c")?,
        });
    }
    let core = core_spec(ctx, name, &a["core"])?;
    let (mut iw, mut c_iw) = (None, 0.0);
    if let Value::Map(d) = &a["interwinding"] {
        let ends = d.get("ends").and_then(Value::as_list).unwrap_or_default();
        let (Some(e0), Some(e1), Some(to)) = (ends.first(), ends.get(1), d.get("to")) else {
            return Err(ctx.fail(name, "interwinding: {ends: [a, b], to, c}"));
        };
        iw = Some(((e0.py_str(), e1.py_str()), to.py_str()));
        let w2 = format!("{name}.interwinding.c");
        let c = ctx.physical(&w2, d.get("c").unwrap_or(&Value::Null))?;
        c_iw = ctx.float(&w2, &c)?;
    }
    let mat = ctx
        .lib
        .material(&core.material)
        .map_err(|e| ctx.fail(name, e.0))?;
    let (els, model) = parts::transformer(
        name,
        &windings,
        &core,
        &mat,
        ctx.float(&format!("{name}.turns"), &a["turns"])?,
        ctx.float(&format!("{name}.leakage_h"), &a["leakage_h"])?,
        iw,
        c_iw,
        ctx.cores == Cores::Linear,
    )?;
    if ctx.cores != Cores::Linear {
        ctx.core_models.push(model);
    }
    Ok(els)
}

fn core_spec(ctx: &Context, name: &str, c: &Value) -> Result<CoreSpec, Error> {
    let keys = ["material", "area_m2", "path_m", "gap_m"];
    let ok = c
        .as_map()
        .filter(|m| m.len() == 4 && keys.iter().all(|k| m.contains(k)));
    let Some(c) = ok else {
        return Err(ctx.fail(name, "core: {material, area_m2, path_m, gap_m}"));
    };
    let phys = |k: &str| -> Result<f64, Error> {
        let w = format!("{name}.core.{k}");
        let v = ctx.physical(&w, c.get(k).unwrap())?;
        ctx.float(&w, &v)
    };
    Ok(CoreSpec {
        material: ctx.text(&format!("{name}.core.material"), c.get("material").unwrap())?,
        area_m2: phys("area_m2")?,
        path_m: phys("path_m")?,
        gap_m: phys("gap_m")?,
    })
}

// --- Devices ---------------------------------------------------------------------------

fn make_models(ctx: &mut Context) -> Result<(), Error> {
    let devices = ctx.spec.devices.clone();
    for (key, e) in devices.iter() {
        let where_ = format!("devices.{key}");
        let e = e.as_map().expect("checked in load_circuit");
        let mut unknown: Vec<&str> = e.keys().filter(|k| !DEVICE_KEYS.contains(k)).collect();
        unknown.sort_unstable();
        if !unknown.is_empty() {
            return Err(ctx.fail(&where_, format!("unknown keys {unknown:?}")));
        }
        let file = ctx.text(&where_, e.get("device").unwrap())?;
        // A circuit names the component version it uses (versions::require_pinned).
        let base = versions::require_pinned(&ctx.lib.components_dir(), &file)
            .and_then(|r| ctx.lib.device(&r.to_string()))
            .map_err(|err| ctx.fail(&where_, err.0))?;
        let model = if e.get("instance") == Some(&Value::Bool(false)) {
            if e.keys()
                .any(|k| !["device", "instance", "source", "notes"].contains(&k))
            {
                return Err(ctx.fail(
                    &where_,
                    "instance: false takes the device file's model as is",
                ));
            }
            base
        } else {
            let one = Value::Float(1.0);
            let emission = ctx.number(
                &format!("{where_}.emission"),
                e.get("emission").unwrap_or(&one),
            )?;
            let mut emission = ctx.float(&format!("{where_}.emission"), &emission)?;
            let mu = ctx.number(&format!("{where_}.mu"), e.get("mu").unwrap_or(&one))?;
            let mut mu = ctx.float(&format!("{where_}.mu"), &mu)?;
            if let Some(tol) = e.get("tolerance").filter(|t| !t.is_null()) {
                if tol.as_str() != Some("tube") || ctx.tolerance.is_none() {
                    return Err(ctx.fail(
                        &where_,
                        format!("tolerance: {tol} (tube, with a tolerance block)"),
                    ));
                }
                // The tube's draws at spread 0: both factors exactly 1.
                let (ef, mf) = (1.0, 1.0);
                emission *= ef;
                if matches!(base, DeviceModel::Triode(_) | DeviceModel::Pentode(_)) {
                    mu *= mf;
                }
            }
            let contact = match e.get("grid_contact_v") {
                None | Some(Value::Null) => None,
                Some(c) => match ctx.physical(&where_, c)? {
                    Value::Null => None,
                    v => Some(ctx.float(&where_, &v)?),
                },
            };
            let area = match e.get("area") {
                Some(x) => {
                    let w = format!("{where_}.area");
                    let v = ctx.physical(&w, x)?;
                    ctx.float(&w, &v)?
                }
                None => 1.0,
            };
            let n_parallel = ctx.count(
                &format!("{where_}.parallel"),
                e.get("parallel").unwrap_or(&Value::Int(1)),
            )?;
            ctx.parallel.insert(
                match e.get("name").map(Value::py_str).filter(|n| !n.is_empty()) {
                    Some(n) => n,
                    None => format!("{}_{key}", base.name()),
                },
                n_parallel,
            );
            let name = match e.get("name").map(Value::py_str).filter(|n| !n.is_empty()) {
                Some(n) => n,
                None => format!("{}_{key}", base.name()),
            };
            parts::device_instance(
                &base,
                &name,
                Instance {
                    n_parallel,
                    emission_scale: emission,
                    mu_spread: mu,
                    grid_contact_v: contact,
                    area,
                },
            )
            .map_err(|err| ctx.fail(&where_, err.0))?
        };
        ctx.models.push((key.to_string(), model));
    }
    Ok(())
}

// --- The circuit -------------------------------------------------------------------------

/// The project's sample rate (sim_settings.yaml `sample_rate`): the noise grid.
fn sample_rate(lib: &Library) -> Result<f64, Error> {
    let path = lib.config_dir().join("sim_settings.yaml");
    crate::yaml::load(&path)?
        .as_map()
        .and_then(|m| m.get("sample_rate"))
        .and_then(Value::as_f64)
        .ok_or_else(|| Error(format!("{}: no sample_rate", path.display())))
}

fn tolerance(ctx: &Context) -> Result<Option<Tolerance>, Error> {
    let t = &ctx.spec.tolerance;
    if t.is_empty() {
        return Ok(None);
    }
    // Every band and tube percentage must resolve, as in Python.
    if let Some(bands) = t.get("bands").and_then(Value::as_map) {
        for (cls, b) in bands.iter() {
            let w = format!("tolerance.bands.{cls}");
            match b {
                Value::List(l) => {
                    for x in l.iter().take(2) {
                        ctx.number(&w, x)?;
                    }
                }
                _ => {
                    ctx.number(&w, b)?;
                }
            }
        }
    }
    let key = |k: &str| t.get(k).map(Value::py_str).unwrap_or_default();
    let seed = ctx.reference("tolerance.seed", &key("seed"))?;
    let spread = ctx.reference("tolerance.spread", &key("spread"))?;
    ctx.float("tolerance.seed", &seed)?;
    let spread = ctx.float("tolerance.spread", &spread)?;
    if spread != 0.0 {
        return Err(ctx.fail(
            "tolerance.spread",
            format!(
                "{spread}: the Rust builder builds nominal units only (spread 0); \
                 matching numpy's draws is open (docs/NATIVE_APP_PLAN.md)"
            ),
        ));
    }
    if let Some(tube) = t.get("tube").and_then(Value::as_map) {
        for k in ["emission_pct", "mu_pct"] {
            let v = tube.get(k).map(Value::py_str).unwrap_or_default();
            ctx.reference("tolerance.tube", &v)?;
        }
    }
    let mut combined = Vec::new();
    if let Some(c) = t.get("combined").and_then(Value::as_map) {
        for (d, ps) in c.iter() {
            let ps = ps
                .as_list()
                .unwrap_or_default()
                .iter()
                .map(Value::py_str)
                .collect();
            combined.push((d.to_string(), ps));
        }
    }
    Ok(Some(Tolerance {
        classes: ctx.spec.part_classes(),
        combined,
    }))
}

/// The circuit IR for resolved parameters `p` (see `spec::resolve`), with the file's
/// noise.
pub fn build_ir(
    lib: &Library,
    spec: &CircuitSpec,
    p: &Params,
    cores: Cores,
) -> Result<CircuitIr, Error> {
    build_ir_noise(lib, spec, p, cores, Noise::File)
}

/// [`build_ir`] with the noise set: Python's `build_ir(..., noise=)`.
pub fn build_ir_noise(
    lib: &Library,
    spec: &CircuitSpec,
    p: &Params,
    cores: Cores,
    noise: Noise,
) -> Result<CircuitIr, Error> {
    let mut q = p.clone();
    if let Some(module) = &spec.derived_module {
        for k in &spec.derived {
            q.insert(k.clone(), derived::derive(module, k, p)?);
        }
    }
    let mut ctx = Context {
        lib,
        spec,
        q,
        cores,
        tolerance: None,
        models: Vec::new(),
        core_models: Vec::new(),
        used_devices: HashSet::new(),
        designators: HashSet::new(),
        missing_class: BTreeSet::new(),
        section_tolerance: None,
        noise: None,
        mains_sines: Vec::new(),
        parallel: HashMap::new(),
    };
    ctx.noise = noise_setting(&ctx, noise)?;
    ctx.tolerance = tolerance(&ctx)?;
    make_models(&mut ctx)?;
    let mut sections = Vec::new();
    for s in &spec.sections {
        ctx.section_tolerance = s.tolerance.clone();
        let mut elements = Vec::new();
        for (name, entry) in s.parts.iter() {
            elements.extend(expand_part(&mut ctx, name, entry, &[])?);
        }
        sections.push(Section {
            title: s.title.clone(),
            elements,
        });
    }
    if !ctx.missing_class.is_empty() {
        return Err(Error(format!(
            "parts without a tolerance class: {:?}",
            ctx.missing_class
        )));
    }
    if let Some(t) = &ctx.tolerance {
        let mut named: BTreeSet<String> = t.classes.keys().cloned().collect();
        named.extend(t.combined.iter().flat_map(|(_, ps)| ps.iter().cloned()));
        let mut listed: HashSet<String> = ctx.designators.clone();
        for d in &ctx.designators {
            listed.extend(t.parts_of(d));
        }
        let stray: Vec<&String> = named.iter().filter(|d| !listed.contains(*d)).collect();
        if !stray.is_empty() {
            return Err(Error(format!(
                "{}: tolerance classes name no part: {stray:?}",
                spec.path.display()
            )));
        }
    }
    let mut unused: Vec<&str> = ctx
        .models
        .iter()
        .map(|(k, _)| k.as_str())
        .filter(|k| !ctx.used_devices.contains(*k))
        .collect();
    unused.sort_unstable();
    if !unused.is_empty() {
        return Err(Error(format!(
            "{}: devices no part uses: {unused:?}",
            spec.path.display()
        )));
    }
    // The mains wander on the mains parts the build kept (a switch may leave one out).
    let noise = match ctx.noise {
        None => None,
        Some((seed, _, _, mains_rms)) => {
            let kept: HashSet<&str> = sections
                .iter()
                .flat_map(|s| s.elements.iter())
                .filter_map(|e| match e {
                    Element::SineSource(s) => Some(s.name.as_str()),
                    _ => None,
                })
                .collect();
            let mains: Vec<String> = if mains_rms > 0.0 {
                ctx.mains_sines
                    .iter()
                    .filter(|n| kept.contains(n.as_str()))
                    .cloned()
                    .collect()
            } else {
                Vec::new()
            };
            Some(NoiseSpec {
                seed,
                rate_hz: sample_rate(lib)?,
                mains_rms: if mains.is_empty() { 0.0 } else { mains_rms },
                mains_sources: mains,
            })
        }
    };
    let mut models: Vec<DeviceModel> = ctx.models.into_iter().map(|(_, m)| m).collect();
    models.extend(ctx.core_models.into_iter().map(DeviceModel::MagneticCore));
    let ir = CircuitIr {
        version: IR_VERSION,
        title: spec.title.clone(),
        input_node: spec.input_node.clone(),
        controls: spec
            .cv_inputs
            .iter()
            .map(|(name, node)| circuitsim::ir::Control {
                name: name.clone(),
                node: node.clone(),
            })
            .collect(),
        noise,
        probes: spec
            .probes
            .iter()
            .map(|n| Probe::Voltage { node: n.clone() })
            .collect(),
        models,
        sections,
    };
    ir.validate()
        .map_err(|e| Error(format!("{}: {}", spec.path.display(), e.0)))?;
    Ok(ir)
}
