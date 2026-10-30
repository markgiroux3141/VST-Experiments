//! Circuit files (config/circuits/*.yaml): loading, checks, parameter resolution.
//!
//! The port of `varimu/circuit/spec.py`; its docstring is the format's reference.
//! `load_circuit` makes the same checks (the messages follow Python's), `resolve`
//! merges defaults with overrides and checks the controls' ranges.

use std::collections::HashMap;
use std::path::{Path, PathBuf};

use crate::Error;
use crate::yaml::{self, Map, Value};

const TOP_KEYS: [&str; 14] = [
    "title",
    "input",
    "cv_inputs",
    "probes",
    "full_scale",
    "controls",
    "values",
    "device_params",
    "derived",
    "mains",
    "tolerance",
    "devices",
    "sections",
    "noise",
];

/// Resolved parameters: every control, value and non-null device parameter (plus, in a
/// build, the derived values).
pub type Params = HashMap<String, Value>;

#[derive(Debug, Clone)]
pub struct SectionSpec {
    pub title: String,
    pub tolerance: Option<Value>,
    pub parts: Map,
}

#[derive(Debug, Clone)]
pub struct CircuitSpec {
    pub path: PathBuf,
    pub title: String,
    pub input_node: String,
    /// Control inputs (`cv_inputs: {name: node}`, file order): nodes driven by
    /// their own samples beside the audio input (a gate, a pitch voltage).
    pub cv_inputs: Vec<(String, String)>,
    pub probes: Vec<String>,
    pub controls: Map,
    pub values: Map,
    pub device_params: Map,
    /// The `derived` block's module and value names (empty: none).
    pub derived_module: Option<String>,
    pub derived: Vec<String>,
    pub mains: Option<Map>,
    /// The `tolerance` block (empty: none).
    pub tolerance: Map,
    pub devices: Map,
    pub sections: Vec<SectionSpec>,
    /// The file's audio convention (`full_scale`; None: sim_settings' for both).
    pub full_scale: Option<FullScale>,
    /// The `noise` block as written (device builder B5; None: no noise).
    pub noise: Option<Map>,
}

/// Circuit volts peak at full scale: what a sample of 1.0 puts on the input node, and
/// the `v(out)` that reads as 1.0 (spec.py's docstring, `full_scale`). When `out` is a
/// sound pressure (a `speaker` part's readout, pascals as volts), `output_v` is pascals
/// and `output_pascals` says so (for display; every path scales by the number alike).
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct FullScale {
    pub input_v: f64,
    pub output_v: f64,
    pub output_pascals: bool,
}

const FULL_SCALE_OUTPUTS: [&str; 2] = ["output_volts_peak", "output_pascals_peak"];

/// The `full_scale` block (None: absent, or an error pushed).
fn full_scale(fs: Option<&Value>, errors: &mut Vec<String>) -> Option<FullScale> {
    let fs = fs.filter(|v| !v.is_null())?;
    let outs: Vec<&str> = fs.as_map().map_or_else(Vec::new, |m| {
        FULL_SCALE_OUTPUTS
            .into_iter()
            .filter(|k| m.contains(k))
            .collect()
    });
    let Some(m) = fs
        .as_map()
        .filter(|m| m.len() == 2 && m.contains("input_volts_peak") && outs.len() == 1)
    else {
        errors.push(format!(
            "full_scale: needs exactly input_volts_peak and one of {FULL_SCALE_OUTPUTS:?}"
        ));
        return None;
    };
    let keys = ["input_volts_peak", outs[0]];
    let mut out = [0.0; 2];
    for (k, o) in keys.iter().zip(&mut out) {
        let n = errors.len();
        let e = m.get(k).unwrap();
        sourced(&format!("full_scale.{k}"), e, errors, false);
        if errors.len() > n {
            return None;
        }
        let v = e.as_map().and_then(|m| m.get("value")).unwrap();
        match v.as_f64().filter(|x| *x > 0.0) {
            Some(x) => *o = x,
            None => {
                errors.push(format!(
                    "full_scale.{k}: value {v} is not a positive number"
                ));
                return None;
            }
        }
    }
    Some(FullScale {
        input_v: out[0],
        output_v: out[1],
        output_pascals: outs[0] == "output_pascals_peak",
    })
}

fn has_source(e: &Map) -> bool {
    e.get("source")
        .is_some_and(|s| !s.py_str().trim().is_empty())
}

/// A string that is a number to the eye but not to PyYAML (`1.0e6`):
/// `[-+]?(\d+\.?\d*|\.\d+)([eE][-+]?\d+)?`.
fn number_like(s: &str) -> bool {
    let b = s.as_bytes();
    let mut i = usize::from(matches!(b.first(), Some(b'+' | b'-')));
    let digits = |i: &mut usize| {
        let start = *i;
        while *i < b.len() && b[*i].is_ascii_digit() {
            *i += 1;
        }
        *i - start
    };
    if digits(&mut i) > 0 {
        if b.get(i) == Some(&b'.') {
            i += 1;
            digits(&mut i);
        }
    } else if b.get(i) == Some(&b'.') {
        i += 1;
        if digits(&mut i) == 0 {
            return false;
        }
    } else {
        return false;
    }
    if matches!(b.get(i), Some(b'e' | b'E')) {
        i += 1;
        if matches!(b.get(i), Some(b'+' | b'-')) {
            i += 1;
        }
        if digits(&mut i) == 0 {
            return false;
        }
    }
    i == b.len()
}

fn sourced(where_: &str, e: &Value, errors: &mut Vec<String>, allow_null: bool) {
    let Some(m) = e.as_map().filter(|m| m.contains("value")) else {
        errors.push(format!("{where_}: needs a `value`"));
        return;
    };
    let v = m.get("value").unwrap();
    if !has_source(m) {
        errors.push(format!("{where_}: needs a `source`"));
    } else if v.is_null() && !allow_null {
        errors.push(format!("{where_}: value is null"));
    } else if let Value::Str(s) = v
        && number_like(s.trim())
    {
        errors.push(format!(
            "{where_}: value '{s}' is not a number (write 1.0e+6, not 1.0e6)"
        ));
    }
}

fn map_or_empty(v: Option<&Value>) -> Map {
    v.and_then(Value::as_map).cloned().unwrap_or_default()
}

/// Read and check a circuit file (parameters and their sources, the tolerance block, the
/// shape of devices and sections; the builder checks the parts).
pub fn load_circuit(path: &Path) -> Result<CircuitSpec, Error> {
    circuit_from_value(&yaml::load(path)?, path)
}

/// A circuit file's content (as `load_circuit` reads it) checked into a spec; `path`
/// names it in messages (a compiled drawing has no file).
pub fn circuit_from_value(data: &Value, path: &Path) -> Result<CircuitSpec, Error> {
    let empty = Map::default();
    let data = match data {
        Value::Map(m) => m,
        Value::Null => &empty,
        _ => return Err(Error(format!("{}: not a mapping", path.display()))),
    };
    let mut errors = Vec::new();
    let mut unknown: Vec<&str> = data.keys().filter(|k| !TOP_KEYS.contains(k)).collect();
    unknown.sort_unstable();
    if !unknown.is_empty() {
        errors.push(format!("unknown top-level keys {unknown:?}"));
    }
    let controls = map_or_empty(data.get("controls"));
    let values = map_or_empty(data.get("values"));
    let device_params = map_or_empty(data.get("device_params"));
    for (k, e) in controls.iter() {
        sourced(&format!("controls.{k}"), e, &mut errors, false);
        if let Some(m) = e.as_map() {
            let range = m.contains("min") && m.contains("max");
            if !range && !m.contains("choices") {
                errors.push(format!("controls.{k}: needs `min` and `max`, or `choices`"));
            } else if let Some(choices) = m.get("choices") {
                let v = m.get("value").unwrap_or(&Value::Null);
                let ok = choices
                    .as_list()
                    .is_some_and(|c| c.iter().any(|x| x.py_eq(v)));
                if !ok {
                    errors.push(format!("controls.{k}: value {v} not in its choices"));
                }
            }
        }
    }
    for (k, e) in values.iter() {
        sourced(&format!("values.{k}"), e, &mut errors, false);
    }
    for (k, e) in device_params.iter() {
        sourced(&format!("device_params.{k}"), e, &mut errors, true);
    }
    let derived_block = map_or_empty(data.get("derived"));
    let mut derived_module = None;
    let mut derived = Vec::new();
    if !derived_block.is_empty() {
        match derived_block.get("module").and_then(Value::as_str) {
            Some(m) if !m.is_empty() => derived_module = Some(m.to_string()),
            _ => errors.push("derived: needs a `module`".into()),
        }
        for (k, e) in map_or_empty(derived_block.get("values")).iter() {
            if !e.as_map().is_some_and(has_source) {
                errors.push(format!("derived.values.{k}: needs a `source`"));
            }
            derived.push(k.to_string());
        }
    }
    let keys: Vec<&str> = controls
        .keys()
        .chain(values.keys())
        .chain(device_params.keys())
        .chain(derived.iter().map(String::as_str))
        .collect();
    let mut dupes: Vec<&str> = keys
        .iter()
        .copied()
        .filter(|k| keys.iter().filter(|x| *x == k).count() > 1)
        .collect();
    dupes.sort_unstable();
    dupes.dedup();
    if !dupes.is_empty() {
        errors.push(format!("parameters defined twice: {dupes:?}"));
    }

    let tol = map_or_empty(data.get("tolerance"));
    if !tol.is_empty() {
        if !has_source(&tol) {
            errors.push("tolerance: needs a `source`".into());
        }
        for k in ["seed", "spread"] {
            if !tol.contains(k) {
                errors.push(format!("tolerance: needs `{k}` (a parameter key)"));
            }
        }
        let bands = map_or_empty(tol.get("bands"));
        let mut seen: HashMap<String, String> = HashMap::new();
        for (c, ds) in map_or_empty(tol.get("classes")).iter() {
            if !bands.contains(c) {
                errors.push(format!("tolerance: class {c} has no band"));
            }
            for d in ds.as_list().unwrap_or_default() {
                let d = d.py_str();
                if let Some(other) = seen.get(&d) {
                    errors.push(format!("tolerance: {d} in both {other} and {c}"));
                }
                seen.insert(d, c.to_string());
            }
        }
    }

    let mut sections = Vec::new();
    for (i, s) in data
        .get("sections")
        .and_then(Value::as_list)
        .unwrap_or_default()
        .iter()
        .enumerate()
    {
        let Some(m) = s
            .as_map()
            .filter(|m| m.contains("title") && m.contains("parts"))
        else {
            errors.push(format!("sections[{i}]: needs `title` and `parts`"));
            continue;
        };
        let mut extra: Vec<&str> = m
            .keys()
            .filter(|k| !["title", "parts", "tolerance"].contains(k))
            .collect();
        extra.sort_unstable();
        if !extra.is_empty() {
            errors.push(format!("sections[{i}]: unknown keys {extra:?}"));
            continue;
        }
        sections.push(SectionSpec {
            title: m.get("title").unwrap().py_str(),
            tolerance: m.get("tolerance").cloned(),
            parts: map_or_empty(m.get("parts")),
        });
    }
    let devices = map_or_empty(data.get("devices"));
    for (k, e) in devices.iter() {
        if !e.as_map().is_some_and(|m| m.contains("device")) {
            errors.push(format!("devices.{k}: needs a `device`"));
        }
    }
    let full_scale = full_scale(data.get("full_scale"), &mut errors);
    let noise = data.get("noise").filter(|v| !v.is_null());
    if let Some(n) = noise {
        match n.as_map().filter(|m| m.contains("seed")) {
            None => errors.push("noise: a mapping {seed, temperature_k?, flicker_v2?}".into()),
            Some(m) => {
                let mut extra: Vec<&str> = m
                    .keys()
                    .filter(|k| !["seed", "temperature_k", "flicker_v2"].contains(k))
                    .collect();
                extra.sort_unstable();
                if !extra.is_empty() {
                    errors.push(format!("noise: unknown keys {extra:?}"));
                }
                if !matches!(m.get("seed"), Some(Value::Int(i)) if *i >= 0) {
                    errors.push(format!(
                        "noise.seed: {} is not an integer in [0, 2^64)",
                        m.get("seed").unwrap()
                    ));
                }
            }
        }
    }
    let noise = noise.and_then(Value::as_map).cloned();
    if !errors.is_empty() {
        return Err(Error(format!(
            "{}:\n  {}",
            path.display(),
            errors.join("\n  ")
        )));
    }
    let probes = data
        .get("probes")
        .and_then(Value::as_list)
        .unwrap_or_default()
        .iter()
        .map(Value::py_str)
        .collect();
    Ok(CircuitSpec {
        path: path.to_path_buf(),
        title: data.get("title").map_or_else(String::new, Value::py_str),
        input_node: data.get("input").map_or_else(|| "in".into(), Value::py_str),
        cv_inputs: data
            .get("cv_inputs")
            .and_then(Value::as_map)
            .map(|m| m.iter().map(|(k, v)| (k.to_string(), v.py_str())).collect())
            .unwrap_or_default(),
        probes,
        controls,
        values,
        device_params,
        derived_module,
        derived,
        mains: data.get("mains").and_then(Value::as_map).cloned(),
        tolerance: tol,
        devices,
        sections,
        full_scale,
        noise,
    })
}

/// config/circuits/<name>.yaml under the config directory.
pub fn circuit_path(config_dir: &Path, name: &str) -> Result<PathBuf, Error> {
    let path = config_dir.join("circuits").join(format!("{name}.yaml"));
    if !path.exists() {
        return Err(Error(format!("no circuit file {}", path.display())));
    }
    Ok(path)
}

impl CircuitSpec {
    /// Designator -> tolerance class.
    pub fn part_classes(&self) -> HashMap<String, String> {
        let mut out = HashMap::new();
        if let Some(classes) = self.tolerance.get("classes").and_then(Value::as_map) {
            for (c, ds) in classes.iter() {
                for d in ds.as_list().unwrap_or_default() {
                    out.insert(d.py_str(), c.to_string());
                }
            }
        }
        out
    }

    fn entry_value(e: &Value) -> Value {
        e.as_map()
            .and_then(|m| m.get("value"))
            .cloned()
            .unwrap_or(Value::Null)
    }

    pub fn defaults(&self) -> Params {
        let mut d = Params::new();
        for (k, e) in self.controls.iter().chain(self.values.iter()) {
            d.insert(k.to_string(), Self::entry_value(e));
        }
        for (k, e) in self.device_params.iter() {
            let v = Self::entry_value(e);
            if !v.is_null() {
                d.insert(k.to_string(), v);
            }
        }
        d
    }

    /// Every key an override may set.
    pub fn is_parameter(&self, key: &str) -> bool {
        self.controls.contains(key) || self.values.contains(key) || self.device_params.contains(key)
    }
}

/// Defaults merged with overrides. Unknown keys and out-of-range controls are errors.
pub fn resolve(spec: &CircuitSpec, overrides: &[(String, Value)]) -> Result<Params, Error> {
    let mut p = spec.defaults();
    for (k, v) in overrides {
        if !spec.is_parameter(k) {
            return Err(Error(format!("unknown circuit parameter '{k}'")));
        }
        p.insert(k.clone(), v.clone());
    }
    for (k, e) in spec.controls.iter() {
        let e = e.as_map().expect("checked in load_circuit");
        let v = &p[k];
        if let Some(choices) = e.get("choices") {
            let choices = choices.as_list().unwrap_or_default();
            if !choices.iter().any(|c| c.py_eq(v)) {
                return Err(Error(format!(
                    "control {k}={} not one of {}",
                    v.py_str(),
                    Value::List(choices.to_vec())
                )));
            }
        } else {
            let (lo, hi) = (e.get("min").unwrap(), e.get("max").unwrap());
            let inside = match (v.as_f64(), lo.as_f64(), hi.as_f64()) {
                (Some(x), Some(lo), Some(hi)) => lo <= x && x <= hi,
                _ => false,
            };
            if !inside {
                return Err(Error(format!(
                    "control {k}={} outside [{}, {}]",
                    v.py_str(),
                    lo.py_str(),
                    hi.py_str()
                )));
            }
        }
    }
    for (k, e) in spec.controls.iter() {
        if e.as_map()
            .and_then(|m| m.get("unit"))
            .and_then(Value::as_str)
            == Some("position")
        {
            let x = p[k]
                .as_f64()
                .ok_or_else(|| Error(format!("control {k}: not a position")))?;
            p.insert(k.to_string(), Value::Int(x.trunc() as i64));
        }
    }
    Ok(p)
}

#[cfg(test)]
mod tests {
    use super::number_like;

    #[test]
    fn number_like_strings() {
        for s in ["1.0e6", "1e-3", "12", ".5", "-3.", "+2e+4"] {
            assert!(number_like(s), "{s}");
        }
        for s in ["mumetall", "1.0e", "e5", ".", "1.2.3", "0x10"] {
            assert!(!number_like(s), "{s}");
        }
    }
}
