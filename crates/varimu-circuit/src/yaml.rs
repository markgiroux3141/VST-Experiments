//! YAML read as PyYAML reads it (`yaml.safe_load`), for the files the builder
//! reads: circuit files, device files, config/magnetics.yaml.
//!
//! The parser is yaml-rust2 (YAML 1.2); plain scalars are then resolved with
//! PyYAML's YAML 1.1 rules where the two differ in ways these files can hit:
//! a float needs a dot and a signed exponent (`1.0e-3`; PyYAML reads `1e-3`
//! and `1.0e6` as strings, which the circuit format rejects as a value), and
//! mapping keys become Python's `str()` of the key. Anchors, tags and YAML 1.1
//! booleans (`yes`, `on`) aren't supported: no file uses them.

use std::fmt;

use yaml_rust2::{Yaml, YamlLoader};

use crate::Error;

/// A parsed YAML value, as Python sees it.
#[derive(Debug, Clone, PartialEq)]
pub enum Value {
    Null,
    Bool(bool),
    Int(i64),
    Float(f64),
    Str(String),
    List(Vec<Value>),
    Map(Map),
}

/// A mapping in file order (Python dicts keep insertion order).
#[derive(Debug, Clone, PartialEq, Default)]
pub struct Map(pub Vec<(String, Value)>);

impl Map {
    pub fn get(&self, key: &str) -> Option<&Value> {
        self.0.iter().find(|(k, _)| k == key).map(|(_, v)| v)
    }

    pub fn contains(&self, key: &str) -> bool {
        self.get(key).is_some()
    }

    pub fn keys(&self) -> impl Iterator<Item = &str> {
        self.0.iter().map(|(k, _)| k.as_str())
    }

    pub fn iter(&self) -> impl Iterator<Item = (&str, &Value)> {
        self.0.iter().map(|(k, v)| (k.as_str(), v))
    }

    pub fn len(&self) -> usize {
        self.0.len()
    }

    pub fn is_empty(&self) -> bool {
        self.0.is_empty()
    }
}

impl Value {
    /// A number (`isinstance(x, int | float) and not isinstance(x, bool)`).
    pub fn as_f64(&self) -> Option<f64> {
        match self {
            Value::Int(i) => Some(*i as f64),
            Value::Float(x) => Some(*x),
            _ => None,
        }
    }

    pub fn as_str(&self) -> Option<&str> {
        match self {
            Value::Str(s) => Some(s),
            _ => None,
        }
    }

    pub fn as_map(&self) -> Option<&Map> {
        match self {
            Value::Map(m) => Some(m),
            _ => None,
        }
    }

    pub fn as_list(&self) -> Option<&[Value]> {
        match self {
            Value::List(l) => Some(l),
            _ => None,
        }
    }

    pub fn is_null(&self) -> bool {
        matches!(self, Value::Null)
    }

    /// Python's `==` between two loaded values (1 == 1.0; True == 1).
    pub fn py_eq(&self, other: &Value) -> bool {
        match (self.numeric(), other.numeric()) {
            (Some(a), Some(b)) => a == b,
            _ => self == other,
        }
    }

    fn numeric(&self) -> Option<f64> {
        match self {
            Value::Bool(b) => Some(f64::from(u8::from(*b))),
            _ => self.as_f64(),
        }
    }

    /// Python's `str()` of a scalar (node names, part names, keys).
    pub fn py_str(&self) -> String {
        match self {
            Value::Null => "None".into(),
            Value::Bool(true) => "True".into(),
            Value::Bool(false) => "False".into(),
            Value::Int(i) => i.to_string(),
            Value::Float(x) => py_float_repr(*x),
            Value::Str(s) => s.clone(),
            Value::List(_) | Value::Map(_) => format!("{self}"),
        }
    }
}

impl fmt::Display for Value {
    /// Roughly Python's `repr()`, for error messages.
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Value::Str(s) => write!(f, "'{s}'"),
            Value::List(l) => {
                write!(f, "[")?;
                for (i, v) in l.iter().enumerate() {
                    if i > 0 {
                        write!(f, ", ")?;
                    }
                    write!(f, "{v}")?;
                }
                write!(f, "]")
            }
            Value::Map(m) => {
                write!(f, "{{")?;
                for (i, (k, v)) in m.iter().enumerate() {
                    if i > 0 {
                        write!(f, ", ")?;
                    }
                    write!(f, "'{k}': {v}")?;
                }
                write!(f, "}}")
            }
            other => write!(f, "{}", other.py_str()),
        }
    }
}

/// Python's `repr(float)` for ordinary values (shortest round trip, `.0` on integers).
pub fn py_float_repr(x: f64) -> String {
    if x.is_nan() {
        return "nan".into();
    }
    if x.is_infinite() {
        return if x > 0.0 { "inf".into() } else { "-inf".into() };
    }
    let s = format!("{x:?}");
    // Rust writes 1e-5 where Python writes 1e-05.
    match s.split_once('e') {
        Some((m, e)) => {
            let (sign, digits) = e.strip_prefix('-').map_or(("+", e), |d| ("-", d));
            format!("{m}e{sign}{digits:0>2}")
        }
        None => s,
    }
}

/// Parse YAML text (one document; an empty file is Null).
pub fn parse(text: &str, what: &str) -> Result<Value, Error> {
    let docs = YamlLoader::load_from_str(text).map_err(|e| Error(format!("{what}: {e}")))?;
    match docs.into_iter().next() {
        None => Ok(Value::Null),
        Some(doc) => convert(doc, what),
    }
}

/// Read and parse a YAML file.
pub fn load(path: &std::path::Path) -> Result<Value, Error> {
    let text =
        std::fs::read_to_string(path).map_err(|e| Error(format!("{}: {e}", path.display())))?;
    parse(&text, &path.display().to_string())
}

fn convert(y: Yaml, what: &str) -> Result<Value, Error> {
    Ok(match y {
        Yaml::Null => Value::Null,
        Yaml::Boolean(b) => Value::Bool(b),
        Yaml::Integer(i) => Value::Int(i),
        Yaml::Real(s) => match pyyaml_float(&s) {
            Some(x) => Value::Float(x),
            None => Value::Str(s),
        },
        Yaml::String(s) => Value::Str(s),
        Yaml::Array(a) => Value::List(
            a.into_iter()
                .map(|v| convert(v, what))
                .collect::<Result<_, _>>()?,
        ),
        Yaml::Hash(h) => {
            let mut m = Vec::with_capacity(h.len());
            for (k, v) in h {
                let key = convert(k, what)?.py_str();
                let v = convert(v, what)?;
                // Duplicate keys: the last wins, in the first one's place (PyYAML).
                match m
                    .iter_mut()
                    .find(|(mk, _): &&mut (String, Value)| *mk == key)
                {
                    Some(slot) => slot.1 = v,
                    None => m.push((key, v)),
                }
            }
            Value::Map(Map(m))
        }
        Yaml::Alias(_) => return Err(Error(format!("{what}: YAML aliases aren't supported"))),
        Yaml::BadValue => return Err(Error(format!("{what}: bad YAML value"))),
    })
}

/// A plain scalar yaml-rust2 resolved as a float, as PyYAML's float resolver reads it:
/// `[-+]?[0-9][0-9_]*\.[0-9_]*([eE][-+][0-9]+)?`, `\.[0-9][0-9_]*([eE][-+][0-9]+)?`,
/// `[-+]?\.(inf|Inf|INF)`, `\.(nan|NaN|NAN)` (sexagesimal floats aren't supported).
/// None: PyYAML reads it as a string.
fn pyyaml_float(s: &str) -> Option<f64> {
    match s {
        ".inf" | ".Inf" | ".INF" | "+.inf" | "+.Inf" | "+.INF" => return Some(f64::INFINITY),
        "-.inf" | "-.Inf" | "-.INF" => return Some(f64::NEG_INFINITY),
        ".nan" | ".NaN" | ".NAN" => return Some(f64::NAN),
        _ => {}
    }
    let b = s.as_bytes();
    let mut i = 0;
    let signed = matches!(b.first(), Some(b'+' | b'-'));
    if signed {
        i += 1;
    }
    let int_start = i;
    while i < b.len() && (b[i].is_ascii_digit() || b[i] == b'_') {
        i += 1;
    }
    let int_part = &b[int_start..i];
    if int_part.is_empty() {
        // `.5`: no sign allowed, a digit right after the dot.
        if signed || b.get(i) != Some(&b'.') || !b.get(i + 1).is_some_and(u8::is_ascii_digit) {
            return None;
        }
    } else if !int_part[0].is_ascii_digit() {
        return None;
    }
    if b.get(i) != Some(&b'.') {
        return None;
    }
    i += 1;
    while i < b.len() && (b[i].is_ascii_digit() || b[i] == b'_') {
        i += 1;
    }
    if i < b.len() {
        if !matches!(b[i], b'e' | b'E') || !matches!(b.get(i + 1), Some(b'+' | b'-')) {
            return None;
        }
        i += 2;
        let exp_start = i;
        while i < b.len() && b[i].is_ascii_digit() {
            i += 1;
        }
        if i == exp_start || i < b.len() {
            return None;
        }
    }
    s.replace('_', "").parse().ok()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn floats_as_pyyaml_reads_them() {
        let v = parse(
            "a: 1.0e-3\nb: 1e-3\nc: 1.0e6\nd: 2.5\ne: 4\nf: .5\ng: 1.\nh: '1.0'\ni: -3.0e+2\n",
            "t",
        )
        .unwrap();
        let m = v.as_map().unwrap();
        assert_eq!(m.get("a"), Some(&Value::Float(1.0e-3)));
        assert_eq!(m.get("b"), Some(&Value::Str("1e-3".into())));
        assert_eq!(m.get("c"), Some(&Value::Str("1.0e6".into())));
        assert_eq!(m.get("d"), Some(&Value::Float(2.5)));
        assert_eq!(m.get("e"), Some(&Value::Int(4)));
        assert_eq!(m.get("f"), Some(&Value::Float(0.5)));
        assert_eq!(m.get("g"), Some(&Value::Float(1.0)));
        assert_eq!(m.get("h"), Some(&Value::Str("1.0".into())));
        assert_eq!(m.get("i"), Some(&Value::Float(-300.0)));
    }

    #[test]
    fn keys_and_order() {
        let v = parse("z: 1\n0: a\nb: [x, 0]\n", "t").unwrap();
        let m = v.as_map().unwrap();
        assert_eq!(m.keys().collect::<Vec<_>>(), ["z", "0", "b"]);
        let nodes: Vec<String> = m
            .get("b")
            .unwrap()
            .as_list()
            .unwrap()
            .iter()
            .map(Value::py_str)
            .collect();
        assert_eq!(nodes, ["x", "0"]);
    }

    #[test]
    fn python_reprs() {
        assert_eq!(py_float_repr(1e-5), "1e-05");
        assert_eq!(py_float_repr(2.0), "2.0");
        assert_eq!(py_float_repr(1e22), "1e+22");
        assert!(Value::Int(1).py_eq(&Value::Float(1.0)));
    }
}
