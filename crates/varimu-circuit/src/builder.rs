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
    CircuitIr, Coupling, Device, DeviceModel, Element, HeatedCathode, HeaterSpec, Inductor,
    MagneticCore, NoiseCurrent, NoiseSpec, Probe, Section, SineSource, TubeNoise, VoltageSource,
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
const DEVICE_KEYS: [&str; 12] = [
    "device",
    "name",
    "instance",
    "tolerance",
    "parallel",
    "emission",
    "mu",
    "grid_contact_v",
    "area",
    "events",
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
    /// Model name -> its device file's model name (the tube type).
    types: HashMap<String, String>,
    /// Heated cathodes (B6): "warm" | "cold" start, None: off.
    heaters: Option<String>,
    /// Thyratrons as their event kernels (HYBRID_PHYSICS_PLAN.md H3), and the models
    /// they replaced (out of the IR).
    events: bool,
    replaced_models: HashSet<String>,
    /// The literal bias's substeps of every tape an events build reduced: the sections at
    /// them run at the sample rate.
    tape_islands: HashSet<usize>,
    /// False: a speaker part's terminal voltage on its `out`, no readout (a live build).
    speaker_readout: bool,
}

/// A build's heated cathodes, as Python's `build_ir(..., heaters=)`.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Heaters {
    /// The file's `heaters` block (none without one).
    File,
    Off,
    /// On, with the block's start (warm without a block).
    On,
    Warm,
    Cold,
}

fn heaters_setting(spec: &CircuitSpec, h: Heaters) -> Option<String> {
    let start = || {
        spec.heaters
            .as_ref()
            .and_then(|b| b.get("start"))
            .and_then(Value::as_str)
            .unwrap_or("warm")
            .to_string()
    };
    match h {
        Heaters::File => spec.heaters.as_ref().map(|_| start()),
        Heaters::Off => None,
        Heaters::On => Some(start()),
        Heaters::Warm => Some("warm".into()),
        Heaters::Cold => Some("cold".into()),
    }
}

/// config/cathodes.yaml: the oxide constants (values) and the tube types' heaters.
fn load_cathodes(lib: &Library) -> Result<(Map, Map), Error> {
    let path = lib.config_dir().join("cathodes.yaml");
    let d = crate::yaml::load(&path)?;
    let m = d
        .as_map()
        .ok_or_else(|| Error(format!("{}: not a mapping", path.display())))?;
    let get = |k: &str| {
        m.get(k)
            .and_then(Value::as_map)
            .cloned()
            .ok_or_else(|| Error(format!("{}: no `{k}`", path.display())))
    };
    Ok((get("oxide")?, get("tubes")?))
}

fn oxide_value(ox: &Map, k: &str) -> Result<f64, Error> {
    ox.get(k)
        .and_then(Value::as_map)
        .and_then(|e| e.get("value"))
        .and_then(Value::as_f64)
        .ok_or_else(|| Error(format!("config/cathodes.yaml: oxide.{k}")))
}

/// A `device` part's heated cathodes (Python's `_heated`).
fn heated_elements(ctx: &Context, els: &[Element]) -> Result<Vec<Element>, Error> {
    let (ox, tubes) = load_cathodes(ctx.lib)?;
    let per_w = oxide_value(&ox, "emission_a_per_w")?;
    let mut out = Vec::new();
    for e in els {
        let Element::Device(d) = e else { continue };
        let Some((_, m)) = ctx.models.iter().find(|(_, m)| m.name() == d.model) else {
            continue;
        };
        if !matches!(
            m,
            DeviceModel::Triode(_) | DeviceModel::Pentode(_) | DeviceModel::VacuumDiode(_)
        ) {
            continue;
        }
        let kind = ctx
            .types
            .get(m.name())
            .cloned()
            .unwrap_or_else(|| m.name().to_string());
        let Some(t) = tubes.get(&kind).and_then(Value::as_map) else {
            return Err(ctx.fail(
                &d.name,
                format!("no heater rating for {kind} in config/cathodes.yaml"),
            ));
        };
        let num = |k: &str| t.get(k).and_then(Value::as_f64).unwrap_or(f64::NAN);
        let w = num("heater_v") * num("heater_a") / num("cathodes");
        let parallel = ctx.parallel.get(m.name()).copied().unwrap_or(1) as f64;
        out.push(Element::HeatedCathode(HeatedCathode {
            name: format!("BH_{}", d.name),
            device: d.name.clone(),
            is0_a: per_w * w * parallel,
        }));
    }
    Ok(out)
}

/// The IR's heaters block (Python's `_heater_spec`).
fn heater_spec(ctx: &Context, start: &str) -> Result<HeaterSpec, Error> {
    let (ox, _) = load_cathodes(ctx.lib)?;
    let mut ratio = 1.0;
    if let Some(m) = &ctx.spec.mains {
        let get = |k: &str| m.get(k).cloned().unwrap_or(Value::Null);
        let mains_v = ctx.reference("mains", &get("v_rms").py_str())?;
        let rated = ctx.physical("mains.rated_v_rms", &get("rated_v_rms"))?;
        ratio = ctx.float("mains", &mains_v)? / ctx.float("mains.rated_v_rms", &rated)?;
    }
    // A heater tap on the panel (the block's `tap` parameter) scales it.
    if let Some(tap) = ctx.spec.heaters.as_ref().and_then(|h| h.get("tap")) {
        let v = ctx.reference("heaters.tap", &tap.py_str())?;
        ratio *= ctx.float("heaters.tap", &v)?;
    }
    Ok(HeaterSpec {
        t0_k: oxide_value(&ox, "t0_k")?,
        t_amb_k: oxide_value(&ox, "t_amb_k")?,
        alpha: oxide_value(&ox, "alpha")?,
        tau_s: oxide_value(&ox, "tau_s")?,
        phi_ev: oxide_value(&ox, "phi_ev")?,
        n: oxide_value(&ox, "n")?,
        reserve: oxide_value(&ox, "reserve")?,
        heater_ratio: ratio,
        start: start.to_string(),
    })
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
const NOISY: [(&str, Option<&str>); 11] = [
    ("R", Some("r")),
    ("pot", Some("r")),
    ("rheostat", Some("r")),
    ("tapped_pot", Some("r")),
    ("t_pad", Some("z")),
    ("transformer", None),
    ("capsule", None),
    ("capsule_dual", None),
    ("harp", None),
    ("moving_coil", None),
    ("ribbon_motor", None),
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
                && !(kind.starts_with("capsule")
                    && r.name
                        .rsplit('_')
                        .next()
                        .is_some_and(|t| t.starts_with('x')))
                && !((kind == "moving_coil" || kind == "ribbon_motor") && r.name.ends_with("_leak"))
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

const MACROS: [&str; 27] = [
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
    "bjt",
    "capsule",
    "capsule_dual",
    "moving_coil",
    "ribbon_motor",
    "speaker",
    "plate",
    "spring_tank",
    "tape",
    "harp",
    "opamp",
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
        "bjt" => (Some(3), vec![p("model", Device)], false),
        "pot" => (
            Some(3),
            vec![
                p("r", Physical),
                p("at", Number),
                opt("taper_mid", Physical),
                num("reverse", 0.0),
            ],
            true,
        ),
        "rheostat" => (
            Some(2),
            vec![
                p("r", Physical),
                p("at", Number),
                opt("taper_mid", Physical),
                num("reverse", 0.0),
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
                opt("core", Raw),
                opt("turns", Physical),
                opt("leakage_h", Physical),
                opt("leak_couplings", Raw),
                opt("interwinding", Raw),
                opt("component", Raw),
                opt("shields", Raw),
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
        "plate" => (
            Some(3),
            vec![p("component", Raw), p("decay_500hz_s", Physical)],
            false,
        ),
        "spring_tank" => (Some(3), vec![p("component", Raw)], false),
        "harp" => (
            Some(1),
            vec![
                p("component", Raw),
                p("rate_hz", Physical),
                p("contact_rate_hz", Physical),
            ],
            false,
        ),
        "tape" => (
            Some(3),
            std::iter::once(p("component", Raw))
                .chain(crate::tape::VALUES.iter().map(|k| {
                    if crate::tape::OWN_BIAS.contains(k) {
                        opt(k, Physical)
                    } else {
                        p(k, Physical)
                    }
                }))
                .chain(std::iter::once(opt("bias_substeps", Count)))
                .chain(crate::tape::TRANSPORT.iter().map(|k| opt(k, Physical)))
                .chain(std::iter::once(opt("reduction", Raw)))
                .chain(std::iter::once(opt("reduction_bias", Raw)))
                .chain(std::iter::once(opt("supply", Raw)))
                .chain(std::iter::once(opt("supply_nominal_hz", Physical)))
                .collect(),
            false,
        ),
        "capsule" => (
            Some(3),
            vec![p("component", Raw), p("polarization_v", Physical)],
            false,
        ),
        "opamp" => (
            Some(3),
            vec![
                p("a0", Physical),
                p("gbw_hz", Physical),
                p("r_out_ohm", Physical),
                p("r_in_ohm", Physical),
                opt("clamp", Device),
                opt("swing_v", Physical),
            ],
            false,
        ),
        "moving_coil" => (Some(4), vec![p("component", Raw)], false),
        "ribbon_motor" => (
            Some(4),
            vec![p("component", Raw), opt("stop", Number)],
            false,
        ),
        "capsule_dual" => (
            Some(5),
            vec![
                p("component", Raw),
                p("polarization_front_v", Physical),
                Param("polarization_rear_v", Physical, Some(Value::Float(0.0))),
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
    if ctx.heaters.is_some() && kind == "device" {
        let extra = heated_elements(ctx, &els)?;
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
            let key = a["model"].as_str().unwrap();
            let model = ctx.model_of(key).clone();
            if matches!(model, DeviceModel::Bjt(_)) {
                return Err(ctx.fail(
                    name,
                    "a BJT is placed with a `bjt` part (its series R and junction C)",
                ));
            }
            let pins = model.pins();
            match conn.as_list() {
                Some(l) if l.len() == pins.len() => {
                    let nodes: Vec<String> = l.iter().map(Value::py_str).collect();
                    match &model {
                        DeviceModel::Thyratron(t) if ctx.events => {
                            vec![events_element(ctx, key, t, name, &nodes)?]
                        }
                        _ => vec![Element::Device(Device {
                            name: s(name),
                            model: model.name().to_string(),
                            nodes,
                        })],
                    }
                }
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
            f("reverse")? != 0.0,
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
                f("reverse")? != 0.0,
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
        "bjt" => {
            let DeviceModel::Bjt(model) = ctx.model_of(a["model"].as_str().unwrap()).clone() else {
                let m = ctx
                    .model_of(a["model"].as_str().unwrap())
                    .name()
                    .to_string();
                return Err(ctx.fail(name, format!("bjt: {m} is not a BJT")));
            };
            if !name.to_uppercase().starts_with('Q') {
                return Err(ctx.fail(name, "a bjt part's name starts with Q (its SPICE element)"));
            }
            parts::bjt(name, &nodes[0], &nodes[1], &nodes[2], &model)
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
        "opamp" => {
            let (p, m, o) = (nodes[0].as_str(), nodes[1].as_str(), nodes[2].as_str());
            let clamp = match a["clamp"].as_str() {
                Some(key) => {
                    let Some(swing) = opt("swing_v")? else {
                        return Err(ctx.fail(name, "a clamp needs swing_v"));
                    };
                    Some((ctx.model_of(key).name().to_string(), swing))
                }
                None => None,
            };
            parts::opamp(
                name,
                p,
                m,
                o,
                f("a0")?,
                f("gbw_hz")?,
                f("r_out_ohm")?,
                f("r_in_ohm")?,
                clamp.as_ref().map(|(k, v)| (k.as_str(), *v)),
            )
        }
        "capsule" => return capsule_part(ctx, name, nodes, a),
        "capsule_dual" => return capsule_dual_part(ctx, name, nodes, a),
        "moving_coil" => return moving_coil_part(ctx, name, nodes, a, false),
        "ribbon_motor" => return moving_coil_part(ctx, name, nodes, a, true),
        "speaker" => return speaker_part(ctx, name, nodes, a),
        "plate" => return plate_part(ctx, name, nodes, a),
        "spring_tank" => return spring_tank_part(ctx, name, nodes, a),
        "tape" => return tape_part(ctx, name, nodes, a),
        "harp" => return harp_part(ctx, name, nodes, a),
        _ => unreachable!("{kind}"),
    })
}

fn capsule_part(
    ctx: &mut Context,
    name: &str,
    nodes: &[String],
    a: &Args,
) -> Result<Vec<Element>, Error> {
    let where_ = format!("{name}.component");
    let reference = ctx.text(&where_, &a["component"])?;
    let model = versions::require_pinned(&ctx.lib.components_dir(), &reference)
        .and_then(|r| ctx.lib.capsule(&r.to_string()))
        .map_err(|e| ctx.fail(&where_, e.0))?;
    let e0 = ctx.float(&format!("{name}.polarization_v"), &a["polarization_v"])?;
    Ok(crate::capsule::capsule(
        name, &nodes[0], &nodes[1], &nodes[2], &model, e0,
    ))
}

fn capsule_dual_part(
    ctx: &mut Context,
    name: &str,
    nodes: &[String],
    a: &Args,
) -> Result<Vec<Element>, Error> {
    let where_ = format!("{name}.component");
    let reference = ctx.text(&where_, &a["component"])?;
    let model = versions::require_pinned(&ctx.lib.components_dir(), &reference)
        .and_then(|r| ctx.lib.dual_capsule(&r.to_string()))
        .map_err(|e| ctx.fail(&where_, e.0))?;
    let ef = ctx.float(
        &format!("{name}.polarization_front_v"),
        &a["polarization_front_v"],
    )?;
    let er = ctx.float(
        &format!("{name}.polarization_rear_v"),
        &a["polarization_rear_v"],
    )?;
    Ok(crate::capsule::capsule_dual(
        name, &nodes[0], &nodes[1], &nodes[2], &nodes[3], &nodes[4], &model, ef, er,
    ))
}

fn moving_coil_part(
    ctx: &mut Context,
    name: &str,
    nodes: &[String],
    a: &Args,
    ribbon: bool,
) -> Result<Vec<Element>, Error> {
    let where_ = format!("{name}.component");
    let reference = ctx.text(&where_, &a["component"])?;
    let model = versions::require_pinned(&ctx.lib.components_dir(), &reference)
        .and_then(|r| {
            if ribbon {
                ctx.lib.ribbon_motor(&r.to_string())
            } else {
                ctx.lib.moving_coil(&r.to_string())
            }
        })
        .map_err(|e| ctx.fail(&where_, e.0))?;
    let model = if ribbon {
        let w = format!("{name}.stop");
        let stop = match &a["stop"] {
            Value::Null => None,
            v => match v.as_f64() {
                Some(f) if f.trunc() == f && f >= 0.0 && !matches!(v, Value::Bool(_)) => {
                    Some(f as i64)
                }
                _ => return Err(ctx.fail(&w, format!("{} is not a stop (0, 1, ...)", v.py_str()))),
            },
        };
        match stop {
            Some(_) => crate::moving_coil::at_stop(&model, stop).map_err(|e| ctx.fail(&w, e.0))?,
            None => model,
        }
    } else {
        model
    };
    crate::moving_coil::moving_coil(name, &nodes[0], &nodes[1], &nodes[2], &nodes[3], &model)
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
    if !ctx.speaker_readout {
        return Ok(speaker::terminal(
            name, &nodes[0], &nodes[1], &nodes[2], &model,
        ));
    }
    Ok(speaker::speaker(
        name, &nodes[0], &nodes[1], &nodes[2], &model, &cab, distance,
    ))
}

fn tape_part(
    ctx: &mut Context,
    name: &str,
    nodes: &[String],
    a: &Args,
) -> Result<Vec<Element>, Error> {
    let where_ = format!("{name}.component");
    let reference = ctx.text(&where_, &a["component"])?;
    let model = versions::require_pinned(&ctx.lib.components_dir(), &reference)
        .and_then(|r| ctx.lib.tape(&r.to_string()))
        .map_err(|e| ctx.fail(&where_, e.0))?;
    let m = match &a["bias_substeps"] {
        Value::Null => None,
        x => Some(ctx.count(&format!("{name}.bias_substeps"), x)? as usize),
    };
    let mut v = [0.0; 16];
    for (x, k) in v.iter_mut().zip(crate::tape::VALUES) {
        let null = a[k].is_null();
        if crate::tape::OWN_BIAS.contains(&k) {
            if m.is_none() && null {
                return Err(ctx.fail(
                    &format!("{name}.{k}"),
                    "required (or bias_substeps: the literal bias)",
                ));
            }
            if m.is_some() {
                if !null {
                    return Err(ctx.fail(
                        &format!("{name}.{k}"),
                        "not read with bias_substeps (the literal bias)",
                    ));
                }
                continue;
            }
        }
        *x = ctx.float(&format!("{name}.{k}"), &a[k])?;
    }
    let given = crate::tape::TRANSPORT
        .iter()
        .filter(|k| !a[**k].is_null())
        .count();
    let mut tr = [0.0; 13];
    if given > 0 {
        for (x, k) in tr.iter_mut().zip(crate::tape::TRANSPORT) {
            if a[k].is_null() {
                return Err(ctx.fail(
                    &format!("{name}.{k}"),
                    "the transport's values go all or none",
                ));
            }
            *x = ctx.float(&format!("{name}.{k}"), &a[k])?;
        }
    }
    let supply = match (&a["supply"], &a["supply_nominal_hz"]) {
        (Value::Null, Value::Null) => None,
        (Value::Null, _) => {
            return Err(ctx.fail(
                &format!("{name}.supply_nominal_hz"),
                "only with a supply node",
            ));
        }
        (_, Value::Null) => {
            return Err(ctx.fail(
                &format!("{name}.supply_nominal_hz"),
                "required with a supply",
            ));
        }
        (node, hz) => {
            if given == 0 {
                return Err(ctx.fail(
                    &format!("{name}.supply"),
                    "varispeed needs the transport's values",
                ));
            }
            Some((
                ctx.text(&format!("{name}.supply"), node)?,
                ctx.float(&format!("{name}.supply_nominal_hz"), hz)?,
            ))
        }
    };
    let mut els = crate::tape::tape(
        name,
        &nodes[0],
        &nodes[1],
        &nodes[2],
        &model,
        &v,
        m,
        (given > 0).then_some(&tr),
        supply.as_ref().map(|(n, hz)| (n.as_str(), *hz)),
    );
    if !a["reduction_bias"].is_null() && a["reduction"].is_null() {
        return Err(ctx.fail(&format!("{name}.reduction_bias"), "only with a reduction"));
    }
    if !ctx.events || a["reduction"].is_null() {
        return Ok(els);
    }
    let where_ = format!("{name}.reduction");
    let table = ctx.text(&where_, &a["reduction"])?;
    let bias_control = if a["reduction_bias"].is_null() {
        None
    } else {
        let w = format!("{name}.reduction_bias");
        // A control's name, not its setting.
        let c = match &a["reduction_bias"] {
            Value::Str(s) => s.clone(),
            v => return Err(ctx.fail(&w, format!("{v} is not a control"))),
        };
        if !ctx.spec.controls.contains(&c) {
            return Err(ctx.fail(&w, format!("'{c}' is not a control")));
        }
        Some(c)
    };
    for e in els.iter_mut() {
        if let Element::Tape(t) = e {
            tape_reduction(
                ctx,
                &where_,
                &table,
                &reference,
                bias_control.as_deref(),
                &mut t.medium,
            )?;
        }
    }
    if let Some(m) = m {
        ctx.tape_islands.insert(m);
    }
    Ok(els)
}

/// numpy's `interp` (xp rising, fp held beyond its ends): Python's `builder._interp`.
fn interp(x: f64, xp: &[f64], fp: &[f64]) -> f64 {
    let n = xp.len();
    if x <= xp[0] {
        return fp[0];
    }
    if x >= xp[n - 1] {
        return fp[n - 1];
    }
    let j = (0..n - 1).find(|&i| xp[i + 1] > x).unwrap_or(n - 2);
    let slope = (fp[j + 1] - fp[j]) / (xp[j + 1] - xp[j]);
    slope * (x - xp[j]) + fp[j]
}

/// The tape part's medium reduced by config/tape_reductions/<name>.json (written by
/// scripts/tape_reduction.py for this medium; refused for any other), at its own bias or,
/// with bias_control, at that control's setting through the file's measured bias map:
/// Python's `builder._tape_reduction`.
fn tape_reduction(
    ctx: &Context,
    where_: &str,
    table: &str,
    component: &str,
    bias_control: Option<&str>,
    medium: &mut circuitsim::tape_stream::TapeParams,
) -> Result<(), Error> {
    let path = ctx
        .lib
        .config_dir()
        .join("tape_reductions")
        .join(format!("{table}.json"));
    let text = std::fs::read_to_string(&path).map_err(|e| {
        ctx.fail(
            where_,
            format!(
                "no {} ({e}; scripts/tape_reduction.py writes it)",
                path.display()
            ),
        )
    })?;
    let bad = |e: String| ctx.fail(where_, format!("{table}: {e}"));
    let d: serde_json::Value = serde_json::from_str(&text).map_err(|e| bad(e.to_string()))?;
    let tape: String = field(&d, "tape").map_err(bad)?;
    if tape != component {
        return Err(ctx.fail(
            where_,
            format!("{table}.json is for {tape}, not {component}"),
        ));
    }
    let full = serde_json::to_value(&*medium).map_err(|e| bad(e.to_string()))?;
    let made: serde_json::Map<String, serde_json::Value> = field(&d, "medium").map_err(bad)?;
    for (k, v) in &made {
        let same = match (full.get(k), v) {
            (Some(serde_json::Value::Bool(a)), serde_json::Value::Bool(b)) => a == b,
            (Some(a), b) => a.as_f64().is_some() && a.as_f64() == b.as_f64(),
            (None, _) => false,
        };
        if !same {
            return Err(ctx.fail(
                where_,
                format!("{table}.json was made for another medium ({k}): rerun its script"),
            ));
        }
    }
    let mut bias: f64 = field(&d, "bias_a_m").map_err(bad)?;
    if let Some(control) = bias_control {
        let map = d
            .get("bias_map")
            .filter(|m| m.get("control").and_then(|c| c.as_str()) == Some(control))
            .ok_or_else(|| {
                ctx.fail(
                    where_,
                    format!("{table}.json has no bias map for {control}"),
                )
            })?;
        let xs: Vec<f64> = field(map, "x").map_err(bad)?;
        let bs: Vec<f64> = field(map, "bias_a_m").map_err(bad)?;
        let at = ctx.reference(where_, control)?;
        bias = interp(ctx.float(where_, &at)?, &xs, &bs);
    }
    let points: Vec<serde_json::Value> = field(&d, "points").map_err(bad)?;
    let points = points
        .iter()
        .map(|q| {
            Ok(circuitsim::tape_stream::ReductionPoint {
                bias_a_m: field(q, "bias_a_m")?,
                mx: field(q, "mx")?,
                slope: field(q, "slope")?,
                ax: field(q, "ax")?,
                ky: field(q, "ky")?,
                demag_d: field(q, "demag_d")?,
            })
        })
        .collect::<Result<Vec<_>, String>>()
        .map_err(bad)?;
    medium.ds_m = field(&d, "ds_m").map_err(bad)?;
    medium.hg_bias_a_m = bias;
    medium.bias_substeps = None;
    medium.reduced = Some(circuitsim::tape_stream::TapeReduction {
        h_a_m: field(&d, "h_a_m").map_err(bad)?,
        tau0_s: field(&d, "tau0_s").map_err(bad)?,
        dt_s: field(&d, "dt_s").map_err(bad)?,
        points,
        demag_k: field(&d, "demag_k").map_err(bad)?,
    });
    Ok(())
}

/// A Rhodes harp (docs/RHODES_PLAN.md, RH3; `varimu.circuit.parts.harp`): its EMF V<NAME>
/// on <name>_e behind its coils' resistance R<NAME>_coils and inductance L<NAME>_coils
/// into `out`.
fn harp_part(
    ctx: &mut Context,
    name: &str,
    nodes: &[String],
    a: &Args,
) -> Result<Vec<Element>, Error> {
    let where_ = format!("{name}.component");
    let reference = ctx.text(&where_, &a["component"])?;
    let model = versions::require_pinned(&ctx.lib.components_dir(), &reference)
        .and_then(|r| ctx.lib.harp(&r.to_string()))
        .map_err(|e| ctx.fail(&where_, e.0))?;
    let rate_hz = ctx.float(&format!("{name}.rate_hz"), &a["rate_hz"])?;
    let contact_rate_hz = ctx.float(&format!("{name}.contact_rate_hz"), &a["contact_rate_hz"])?;
    let (n, upper) = (name.to_lowercase(), name.to_uppercase());
    let (r_ohm, l_h) = (model.coils.r_ohm, model.coils.l_h);
    Ok(vec![
        Element::Harp(circuitsim::ir::Harp {
            name: format!("V{upper}"),
            out: format!("{n}_e"),
            rate_hz,
            contact_rate_hz,
            model: Box::new((*model).clone()),
        }),
        Element::Resistor(circuitsim::ir::Resistor {
            name: format!("R{upper}_coils"),
            a: format!("{n}_e"),
            b: format!("{n}_r"),
            r_ohm,
        }),
        Element::Inductor(circuitsim::ir::Inductor {
            name: format!("L{upper}_coils"),
            a: format!("{n}_r"),
            b: nodes[0].clone(),
            l_h,
        }),
    ])
}

fn plate_part(
    ctx: &mut Context,
    name: &str,
    nodes: &[String],
    a: &Args,
) -> Result<Vec<Element>, Error> {
    let where_ = format!("{name}.component");
    let reference = ctx.text(&where_, &a["component"])?;
    let model = versions::require_pinned(&ctx.lib.components_dir(), &reference)
        .and_then(|r| ctx.lib.plate(&r.to_string()))
        .map_err(|e| ctx.fail(&where_, e.0))?;
    let decay = ctx.float(&format!("{name}.decay_500hz_s"), &a["decay_500hz_s"])?;
    Ok(crate::plate::plate(
        name, &nodes[0], &nodes[1], &nodes[2], &model, decay,
    ))
}

fn spring_tank_part(
    ctx: &mut Context,
    name: &str,
    nodes: &[String],
    a: &Args,
) -> Result<Vec<Element>, Error> {
    let where_ = format!("{name}.component");
    let reference = ctx.text(&where_, &a["component"])?;
    let model = versions::require_pinned(&ctx.lib.components_dir(), &reference)
        .and_then(|r| ctx.lib.spring_tank(&r.to_string()))
        .map_err(|e| ctx.fail(&where_, e.0))?;
    Ok(crate::spring::spring_tank(
        name, &nodes[0], &nodes[1], &nodes[2], &model,
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

/// Python's repr of a sorted list of labels (an error message both builders write alike).
fn py_labels<'a>(labels: impl Iterator<Item = &'a str>) -> String {
    let mut v: Vec<&str> = labels.collect();
    v.sort_unstable();
    let quoted: Vec<String> = v.iter().map(|s| format!("'{s}'")).collect();
    format!("[{}]", quoted.join(", "))
}

/// The compiled block of the part's transformer component, if it names one.
fn transformer_component(ctx: &Context, name: &str, a: &Args) -> Result<Option<Map>, Error> {
    if a["component"].is_null() {
        return Ok(None);
    }
    let where_ = format!("{name}.component");
    let reference = ctx.text(&where_, &a["component"])?;
    let r = versions::require_pinned(&ctx.lib.components_dir(), &reference)
        .map_err(|e| ctx.fail(&where_, e.0))?;
    let data = ctx
        .lib
        .component_data(&r.to_string())
        .map_err(|e| ctx.fail(&where_, e.0))?;
    let m = data.as_map();
    let compiled = m.and_then(|m| m.get("compiled")).and_then(Value::as_map);
    match (m.and_then(|m| m.get("kind")), compiled) {
        (Some(Value::Str(k)), Some(c)) if k == "transformer" => Ok(Some(c.clone())),
        _ => Err(ctx.fail(
            &where_,
            format!("{r} is not a compiled transformer component"),
        )),
    }
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
    let comp = transformer_component(ctx, name, a)?;
    let empty = Map::default();
    let cw = comp
        .as_ref()
        .and_then(|c| c.get("windings"))
        .and_then(Value::as_map)
        .unwrap_or(&empty);
    if comp.is_some() {
        let mut have: Vec<&str> = windings_map.keys().collect();
        let mut want: Vec<&str> = cw.keys().collect();
        have.sort_unstable();
        want.sort_unstable();
        if have != want {
            return Err(ctx.fail(
                name,
                format!(
                    "the component's windings are {}; the part names {}",
                    py_labels(cw.keys()),
                    py_labels(windings_map.keys())
                ),
            ));
        }
        if !a["leakage_h"].is_null() {
            return Err(ctx.fail(name, "leakage_h: a component gives every winding its leak"));
        }
    }
    let mut windings = Vec::new();
    for (label, w) in windings_map.iter() {
        let where_ = format!("{name}.{label}");
        let bad = || {
            ctx.fail(
                &where_,
                "a winding is {nodes: [dot, other], ratio, r, c, leak}",
            )
        };
        let w = w.as_map().ok_or_else(bad)?;
        let nodes = w.get("nodes").and_then(Value::as_list);
        let unknown = w
            .keys()
            .any(|k| !["nodes", "ratio", "r", "c", "leak"].contains(&k));
        let Some(nodes) = nodes.filter(|n| n.len() == 2 && !unknown) else {
            return Err(bad());
        };
        let own = cw.get(label).and_then(Value::as_map).unwrap_or(&empty);
        // The circuit's value, else the component's, else the default.
        let value = |k: &str| -> Result<Option<f64>, Error> {
            let w2 = format!("{where_}.{k}");
            match w.get(k) {
                Some(x) => {
                    let v = if k == "ratio" {
                        ctx.number(&w2, x)?
                    } else {
                        ctx.physical(&w2, x)?
                    };
                    Ok(Some(ctx.float(&w2, &v)?))
                }
                None => match own.get(k) {
                    Some(x) => Ok(Some(ctx.float(&w2, x)?)),
                    None => Ok(None),
                },
            }
        };
        windings.push(WindingSpec {
            label: label.to_string(),
            dot: nodes[0].py_str(),
            other: nodes[1].py_str(),
            ratio: value("ratio")?.unwrap_or(1.0),
            r_ohm: value("r")?.unwrap_or(0.0),
            c_f: value("c")?.unwrap_or(0.0),
            leak_h: value("leak")?,
        });
    }
    let total = match &a["leakage_h"] {
        Value::Null => None,
        v => Some(ctx.float(&format!("{name}.leakage_h"), v)?),
    };
    if total.is_none() && windings.iter().any(|w| w.leak_h.is_none()) {
        return Err(ctx.fail(
            name,
            "leakage: every winding's `leak`, or the total `leakage_h`",
        ));
    }
    let core = match (&a["core"], &comp) {
        (Value::Null, None) => return Err(ctx.fail(name, "needs `core` (or a `component`)")),
        (Value::Null, Some(c)) => {
            let cc = c.get("core").and_then(Value::as_map).unwrap_or(&empty);
            let f = |k: &str| -> Result<f64, Error> {
                ctx.float(
                    &format!("{name}.component.core.{k}"),
                    cc.get(k).unwrap_or(&Value::Null),
                )
            };
            CoreSpec {
                material: cc.get("material").map(Value::py_str).unwrap_or_default(),
                area_m2: f("area_m2")?,
                path_m: f("path_m")?,
                gap_m: f("gap_m")?,
            }
        }
        (c, _) => core_spec(ctx, name, c)?,
    };
    let turns = match (&a["turns"], &comp) {
        (Value::Null, None) => return Err(ctx.fail(name, "needs `turns` (or a `component`)")),
        (Value::Null, Some(c)) => ctx.float(
            &format!("{name}.component.turns"),
            c.get("turns").unwrap_or(&Value::Null),
        )?,
        (v, _) => ctx.float(&format!("{name}.turns"), v)?,
    };
    let labels: Vec<&str> = windings.iter().map(|w| w.label.as_str()).collect();
    let (given, own_k) = match &a["leak_couplings"] {
        Value::Null => (
            comp.as_ref()
                .and_then(|c| c.get("leak_couplings"))
                .cloned()
                .filter(|v| !v.is_null())
                .unwrap_or(Value::List(vec![])),
            false,
        ),
        v => (v.clone(), true),
    };
    let Some(given) = given.as_list() else {
        return Err(ctx.fail(
            &format!("{name}.leak_couplings"),
            "a list of {between: [a, b], k}",
        ));
    };
    let mut couplings: Vec<(String, String, f64)> = Vec::new();
    for (i, d) in given.iter().enumerate() {
        let where_ = format!("{name}.leak_couplings[{i}]");
        let between = d
            .as_map()
            .filter(|m| m.len() == 2 && m.contains("between") && m.contains("k"))
            .and_then(|m| m.get("between"))
            .and_then(Value::as_list)
            .filter(|b| b.len() == 2);
        let Some(between) = between else {
            return Err(ctx.fail(&where_, "{between: [a, b], k}"));
        };
        let (x, y) = (between[0].py_str(), between[1].py_str());
        if !labels.contains(&x.as_str()) || !labels.contains(&y.as_str()) || x == y {
            return Err(ctx.fail(
                &where_,
                format!(
                    "between two of the windings [{}]",
                    labels
                        .iter()
                        .map(|l| format!("'{l}'"))
                        .collect::<Vec<_>>()
                        .join(", ")
                ),
            ));
        }
        if couplings
            .iter()
            .any(|(a, b, _)| (*a == x && *b == y) || (*a == y && *b == x))
        {
            return Err(ctx.fail(&where_, format!("{x}-{y} twice")));
        }
        let kv = d.as_map().unwrap().get("k").unwrap();
        let w2 = format!("{where_}.k");
        let k = if own_k {
            let v = ctx.physical(&w2, kv)?;
            ctx.float(&w2, &v)?
        } else {
            ctx.float(&w2, kv)?
        };
        if !(-1.0 < k && k < 1.0) {
            return Err(ctx.fail(
                &where_,
                format!(
                    "k = {}: a coupling is between -1 and 1",
                    crate::yaml::py_float_repr(k)
                ),
            ));
        }
        couplings.push((x, y, k));
    }
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
        turns,
        total,
        iw,
        c_iw,
        &couplings,
        ctx.cores == Cores::Linear,
    )
    .map_err(|e| ctx.fail(name, e.0))?;
    if ctx.cores != Cores::Linear {
        ctx.core_models.push(model);
    }
    let mut els = els;
    els.extend(component_capacitors(
        ctx,
        name,
        &windings,
        comp.as_ref(),
        &a["shields"],
    )?);
    Ok(els)
}

/// The component's facing capacitances (Python's `_component_capacitors`).
fn component_capacitors(
    ctx: &Context,
    name: &str,
    windings: &[WindingSpec],
    comp: Option<&Map>,
    shields: &Value,
) -> Result<Vec<Element>, Error> {
    let caps: Vec<(String, String, f64)> = comp
        .and_then(|c| c.get("capacitors"))
        .and_then(Value::as_list)
        .unwrap_or_default()
        .iter()
        .map(|d| {
            let b = d
                .as_map()
                .and_then(|m| m.get("between"))
                .and_then(Value::as_list)
                .unwrap_or_default();
            let c = d
                .as_map()
                .and_then(|m| m.get("c"))
                .and_then(Value::as_f64)
                .unwrap_or(0.0);
            (
                b.first().map(Value::py_str).unwrap_or_default(),
                b.get(1).map(Value::py_str).unwrap_or_default(),
                c,
            )
        })
        .collect();
    let mut nodes: Vec<(String, String)> = Vec::new();
    for w in windings {
        nodes.push((format!("{}.dot", w.label), w.dot.clone()));
        nodes.push((format!("{}.other", w.label), w.other.clone()));
    }
    let wanted: Vec<&str> = caps
        .iter()
        .flat_map(|(a, b, _)| [a.as_str(), b.as_str()])
        .filter_map(|t| t.strip_prefix("shield."))
        .collect();
    match shields {
        Value::Null => {}
        Value::Map(m) => {
            for (s, node) in m.iter() {
                if !wanted.contains(&s) {
                    return Err(ctx.fail(
                        &format!("{name}.shields"),
                        format!("the component has no shield {s}"),
                    ));
                }
                nodes.push((format!("shield.{s}"), node.py_str()));
            }
        }
        _ => {
            return Err(ctx.fail(&format!("{name}.shields"), "a mapping {shield: node}"));
        }
    }
    let node = |t: &str| nodes.iter().find(|(k, _)| k == t).map(|(_, n)| n.clone());
    let upper = name.to_uppercase();
    let mut els = Vec::new();
    for (t1, t2, c) in &caps {
        let (Some(a), Some(b)) = (node(t1), node(t2)) else {
            let missing = if node(t1).is_none() { t1 } else { t2 };
            let what = missing.split_once('.').map_or("", |x| x.1);
            return Err(ctx.fail(
                name,
                format!("the component's capacitor to {missing}: shields: {{{what}: node}}"),
            ));
        };
        if a == b || *c <= 0.0 {
            continue;
        }
        els.push(parts::capacitor(
            &format!("C{upper}_{}_{}", t1.replace('.', "_"), t2.replace('.', "_")),
            &a,
            &b,
            *c,
        ));
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

// --- Event kernels (HYBRID_PHYSICS_PLAN.md H3) ----------------------------------------

/// A tables file's field (`thyratron_events.Tables.to_dict`), as `T`.
fn field<T: serde::de::DeserializeOwned>(v: &serde_json::Value, key: &str) -> Result<T, String> {
    let x = v.get(key).ok_or_else(|| format!("no field {key}"))?;
    serde_json::from_value(x.clone()).map_err(|e| format!("{key}: {e}"))
}

/// A thyratron's device part as its event kernels: its `devices` entry's `events` tables,
/// for the same component version (Python's `builder._events_element`).
fn events_element(
    ctx: &mut Context,
    key: &str,
    t: &circuitsim::ir::Thyratron,
    name: &str,
    nodes: &[String],
) -> Result<Element, Error> {
    let where_ = format!("devices.{key}");
    let entry = ctx
        .spec
        .devices
        .get(key)
        .and_then(Value::as_map)
        .expect("checked in load_circuit");
    let Some(events) = entry.get("events") else {
        return Err(ctx.fail(
            &where_,
            "a thyratron in an events build needs its `events` tables",
        ));
    };
    if t.mu_g2.is_some() {
        return Err(ctx.fail(&where_, "event kernels are for triode thyratrons"));
    }
    let table = ctx.text(&where_, events)?;
    let path = ctx
        .lib
        .config_dir()
        .join("events")
        .join(format!("{table}.json"));
    let text = std::fs::read_to_string(&path).map_err(|e| {
        ctx.fail(
            &where_,
            format!(
                "no tables {} ({e}; scripts/thyratron_kernels.py --write)",
                path.display()
            ),
        )
    })?;
    let bad = |e: String| ctx.fail(&where_, format!("tables {table}: {e}"));
    let f: serde_json::Value = serde_json::from_str(&text).map_err(|e| bad(e.to_string()))?;
    let unit = f.get("unit").cloned().unwrap_or_default();
    let unit_device: String = field(&unit, "device").map_err(bad)?;
    let file = ctx.text(&where_, entry.get("device").unwrap())?;
    let device = versions::require_pinned(&ctx.lib.components_dir(), &file)
        .map_err(|err| ctx.fail(&where_, err.0))?
        .to_string();
    if unit_device != device {
        return Err(ctx.fail(
            &where_,
            format!("tables {table} are for {unit_device}, not {device}"),
        ));
    }
    let reference = f
        .get("source")
        .and_then(|s| s.get("key"))
        .and_then(|k| k.as_str())
        .unwrap_or("?")
        .to_string();
    let el = circuitsim::ir::ThyratronEvents {
        name: name.to_string(),
        a: nodes[0].clone(),
        g: nodes[1].clone(),
        w: nodes[2].clone(),
        k: nodes[3].clone(),
        c_gk_f: t.c_gk,
        c_ga_f: t.c_ga,
        c_ak_f: t.c_ak,
        g_leak_s: t.g_leak_s,
        c_f: field(&unit, "c_f").map_err(bad)?,
        r_s_ohm: field(&unit, "r_s_ohm").map_err(bad)?,
        r_g_ohm: field(&unit, "r_g_ohm").map_err(bad)?,
        ref_rate_hz: field(&f, "ref_rate_hz").map_err(bad)?,
        v_g_v: field(&f, "v_g_v").map_err(bad)?,
        log_slope: field(&f, "log_slope").map_err(bad)?,
        v_s_v: field(&f, "v_s_v").map_err(bad)?,
        dead_s: field(&f, "dead_s").map_err(bad)?,
        latched: field(&f, "latched").map_err(bad)?,
        pulses_a: field(&f, "pulses_a").map_err(bad)?,
        grid_pulses_a: field(&f, "grid_pulses_a").map_err(bad)?,
        source: format!("config/events/{table}.json, reference {reference}"),
    };
    ctx.replaced_models.insert(t.name.clone());
    Ok(Element::ThyratronEvents(el))
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
        let base_name = base.name().to_string();
        if e.get("events").is_some() && !matches!(base, DeviceModel::Thyratron(_)) {
            return Err(ctx.fail(&where_, "events: a thyratron's tables"));
        }
        let model = if e.get("instance") == Some(&Value::Bool(false)) {
            if e.keys()
                .any(|k| !["device", "instance", "events", "source", "notes"].contains(&k))
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
        ctx.types.insert(model.name().to_string(), base_name);
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
    build_ir_with(lib, spec, p, cores, noise, Heaters::File)
}

/// [`build_ir`] with the noise and the heaters set: Python's
/// `build_ir(..., noise=, heaters=)`.
pub fn build_ir_with(
    lib: &Library,
    spec: &CircuitSpec,
    p: &Params,
    cores: Cores,
    noise: Noise,
    heaters: Heaters,
) -> Result<CircuitIr, Error> {
    build_ir_events(lib, spec, p, cores, noise, heaters, false)
}

/// [`build_ir_with`], with thyratrons as their event kernels when `events` (technique K,
/// HYBRID_PHYSICS_PLAN.md H3): Python's `build_ir(..., events=)`.
pub fn build_ir_events(
    lib: &Library,
    spec: &CircuitSpec,
    p: &Params,
    cores: Cores,
    noise: Noise,
    heaters: Heaters,
    events: bool,
) -> Result<CircuitIr, Error> {
    build_ir_live(lib, spec, p, cores, noise, heaters, events, true)
}

/// [`build_ir_events`], each speaker part without its readout when `speaker_readout` is
/// false (its terminal voltage on its `out`: a live build): Python's
/// `build_ir(..., speaker_readout=)`.
#[allow(clippy::too_many_arguments)]
pub fn build_ir_live(
    lib: &Library,
    spec: &CircuitSpec,
    p: &Params,
    cores: Cores,
    noise: Noise,
    heaters: Heaters,
    events: bool,
    speaker_readout: bool,
) -> Result<CircuitIr, Error> {
    let mut q = p.clone();
    if events {
        // A control's `events` value is its setting in an events build (the 351's
        // oscillator out of its socket while its tape plays a reduction).
        for (k, e) in spec.controls.iter() {
            if let Some(v) = e.as_map().and_then(|m| m.get("events")) {
                q.insert(k.to_string(), v.clone());
            }
        }
    }
    let base = q.clone();
    if let Some(module) = &spec.derived_module {
        for k in &spec.derived {
            q.insert(k.clone(), derived::derive(module, k, &base)?);
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
        types: HashMap::new(),
        heaters: heaters_setting(spec, heaters),
        events,
        replaced_models: HashSet::new(),
        tape_islands: HashSet::new(),
        speaker_readout,
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
        // K replaces the island it plays in (technique M1 renders it, K plays it live); a
        // section its switches leave empty is no island (it owns nothing it doesn't have).
        let k = elements.is_empty()
            || elements
                .iter()
                .any(|e| matches!(e, Element::ThyratronEvents(_)));
        sections.push(Section {
            title: s.title.clone(),
            substeps: if k { None } else { s.substeps },
            decimate: if k { None } else { s.decimate },
            owns: if k { None } else { s.owns.clone() },
            elements,
        });
    }
    if !ctx.tape_islands.is_empty() {
        // A reduced tape replaces the literal bias's island: those sections at the sample
        // rate.
        for s in &mut sections {
            if s.substeps.is_some_and(|m| ctx.tape_islands.contains(&m)) {
                s.substeps = None;
                s.decimate = None;
                s.owns = None;
            }
        }
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
    let heaters = match &ctx.heaters {
        Some(start) => Some(heater_spec(&ctx, start)?),
        None => None,
    };
    let mut models: Vec<DeviceModel> = ctx
        .models
        .into_iter()
        .map(|(_, m)| m)
        .filter(|m| !ctx.replaced_models.contains(m.name()))
        .collect();
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
        heaters,
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
