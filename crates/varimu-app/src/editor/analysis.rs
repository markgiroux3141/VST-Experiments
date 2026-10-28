//! A drawing compiled, as the editor shows it (`varimu/listen/editor_api.py`'s
//! `analyze`): its connectivity, compile errors, whether it has an output to hear, and
//! the circuit's parameters with their genome bounds and tolerance bands for the
//! inspector.

use std::path::Path;
use std::sync::Arc;

use varimu_circuit::Library;
use varimu_circuit::compile::{Compiled, OUTPUT_NODE, compile_drawing};
use varimu_circuit::connect::DrawnNet;
use varimu_circuit::drawing::Drawing;
use varimu_circuit::yaml::{self, Map, Value};

use super::geom::Pt;

/// A genome parameter's range (`config/genome_bounds.yaml`).
#[derive(Debug, Clone, PartialEq)]
pub struct Bounds {
    pub min: Option<f64>,
    pub max: Option<f64>,
    pub choices: Option<Vec<Value>>,
    pub source: String,
}

/// `config/genome_bounds.yaml`: a parameter is a mapping with a `source`, its id the
/// dotted path.
#[derive(Debug, Clone, Default)]
pub struct GenomeBounds(Map);

impl GenomeBounds {
    pub fn load(config_dir: &Path) -> GenomeBounds {
        match yaml::load(&config_dir.join("genome_bounds.yaml")) {
            Ok(Value::Map(m)) => GenomeBounds(m),
            _ => GenomeBounds::default(),
        }
    }

    pub fn get(&self, id: &str) -> Option<Bounds> {
        let mut m = &self.0;
        let mut parts = id.split('.').peekable();
        while let Some(p) = parts.next() {
            let v = m.get(p)?.as_map()?;
            if parts.peek().is_none() {
                v.get("source")?;
                return Some(Bounds {
                    min: v.get("min").and_then(Value::as_f64),
                    max: v.get("max").and_then(Value::as_f64),
                    choices: v
                        .get("choices")
                        .and_then(Value::as_list)
                        .map(<[Value]>::to_vec),
                    source: v.get("source").map(Value::py_str).unwrap_or_default(),
                });
            }
            m = v;
        }
        None
    }
}

/// One of the circuit's parameters: where it is from (controls, values, device_params,
/// derived), its entry, its genome bounds.
#[derive(Debug, Clone, PartialEq)]
pub struct Param {
    pub kind: String,
    pub entry: Map,
    pub bounds: Option<Bounds>,
}

impl Param {
    pub fn value(&self) -> Option<&Value> {
        self.entry.get("value")
    }

    pub fn text(&self, key: &str) -> Option<String> {
        self.entry
            .get(key)
            .filter(|v| !v.is_null())
            .map(Value::py_str)
    }
}

/// A tolerance class: its parameter keys and their values (percent).
#[derive(Debug, Clone, PartialEq)]
pub struct Band {
    pub keys: Vec<String>,
    pub pct: Vec<Option<Value>>,
}

#[derive(Debug, Clone)]
pub struct Analysis {
    pub compiled: Compiled,
    pub nets: Vec<DrawnNet>,
    pub junctions: Vec<Pt>,
    pub loose: Vec<Pt>,
    /// Renders and the player read node `out`: without it the drawing can't be heard.
    pub has_output: bool,
    pub params: Vec<(String, Param)>,
    pub bands: Vec<(String, Band)>,
}

impl Analysis {
    pub fn ok(&self) -> bool {
        self.compiled.ok()
    }

    pub fn errors(&self) -> &[String] {
        &self.compiled.errors
    }

    pub fn param(&self, key: &str) -> Option<&Param> {
        self.params.iter().find(|(k, _)| k == key).map(|(_, p)| p)
    }

    pub fn band(&self, class: &str) -> Option<&Band> {
        self.bands.iter().find(|(k, _)| k == class).map(|(_, b)| b)
    }
}

/// Compile `d` and gather what the editor shows.
pub fn analyze(d: &Drawing, lib: &Library, bounds: &GenomeBounds) -> Analysis {
    let c = compile_drawing(d, lib);
    let (params, bands) = params(c.data.as_ref().unwrap_or(&d.circuit), bounds);
    Analysis {
        nets: c.conn.nets.clone(),
        junctions: c.conn.junctions.clone(),
        loose: c.conn.loose.clone(),
        has_output: c.conn.nets.iter().any(|n| n.node == OUTPUT_NODE),
        params,
        bands,
        compiled: c,
    }
}

type Params = (Vec<(String, Param)>, Vec<(String, Band)>);

/// The circuit's parameters by key (controls, values, device parameters, derived) with
/// their genome bounds, and each tolerance class's band.
fn params(src: &Map, bounds: &GenomeBounds) -> Params {
    let mut params: Vec<(String, Param)> = Vec::new();
    let mut put = |k: &str, p: Param| match params.iter_mut().find(|(x, _)| x == k) {
        Some((_, q)) => *q = p,
        None => params.push((k.to_string(), p)),
    };
    for kind in ["controls", "values", "device_params"] {
        let Some(m) = src.get(kind).and_then(Value::as_map) else {
            continue;
        };
        for (k, e) in m.iter() {
            let entry = e.as_map().cloned().unwrap_or_default();
            let b = entry
                .get("genome")
                .and_then(Value::as_str)
                .and_then(|g| bounds.get(g));
            put(
                k,
                Param {
                    kind: kind.into(),
                    entry,
                    bounds: b,
                },
            );
        }
    }
    if let Some(m) = src
        .get("derived")
        .and_then(Value::as_map)
        .and_then(|d| d.get("values"))
        .and_then(Value::as_map)
    {
        for (k, e) in m.iter() {
            put(
                k,
                Param {
                    kind: "derived".into(),
                    entry: e.as_map().cloned().unwrap_or_default(),
                    bounds: None,
                },
            );
        }
    }
    let mut bands = Vec::new();
    if let Some(b) = src
        .get("tolerance")
        .and_then(Value::as_map)
        .and_then(|t| t.get("bands"))
        .and_then(Value::as_map)
    {
        for (cls, band) in b.iter() {
            let keys: Vec<String> = match band {
                Value::List(l) => l.iter().map(Value::py_str).collect(),
                other => vec![other.py_str()],
            };
            let pct = keys
                .iter()
                .map(|k| {
                    params
                        .iter()
                        .find(|(x, _)| x == k)
                        .and_then(|(_, p)| p.value().cloned())
                })
                .collect();
            bands.push((cls.to_string(), Band { keys, pct }));
        }
    }
    (params, bands)
}

/// Shared, so the checks' thread can compile too.
pub type SharedLibrary = Arc<Library>;
