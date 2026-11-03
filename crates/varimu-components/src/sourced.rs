//! Values with their sources, read from YAML.
//!
//! As in circuit files, a physical value is `{value: X, source: "..."}`, never a bare
//! number (CLAUDE.md's hard rule: every value carries its source).

use varimu_circuit::yaml::{Map, Value};

use crate::{Error, err};

/// A value and where it comes from (a datasheet, `web: <url>`, `derived: ...`, or
/// `provisional: model knowledge (...)`).
#[derive(Debug, Clone, PartialEq)]
pub struct Sourced<T> {
    pub value: T,
    pub source: String,
}

impl<T> Sourced<T> {
    pub fn new(value: T, source: impl Into<String>) -> Self {
        Sourced {
            value,
            source: source.into(),
        }
    }
}

pub fn map<'a>(v: &'a Value, what: &str) -> Result<&'a Map, Error> {
    v.as_map()
        .ok_or_else(|| Error(format!("{what}: expected a mapping")))
}

pub fn get<'a>(m: &'a Map, key: &str, what: &str) -> Result<&'a Value, Error> {
    m.get(key)
        .ok_or_else(|| Error(format!("{what}: needs `{key}`")))
}

/// Refuses keys outside `allowed` (a typo would otherwise be a silent default).
pub fn only(m: &Map, allowed: &[&str], what: &str) -> Result<(), Error> {
    for (k, _) in m.iter() {
        if !allowed.contains(&k) {
            return err(format!(
                "{what}: unknown key `{k}` (allowed: {})",
                allowed.join(", ")
            ));
        }
    }
    Ok(())
}

pub fn text(v: &Value, what: &str) -> Result<String, Error> {
    match v {
        Value::Str(s) => Ok(s.clone()),
        Value::Int(_) | Value::Float(_) => Ok(v.py_str()),
        _ => err(format!("{what}: expected text, got {v}")),
    }
}

pub fn number(v: &Value, what: &str) -> Result<f64, Error> {
    v.as_f64().ok_or_else(|| {
        let hint = match v {
            Value::Str(s) if s.parse::<f64>().is_ok() => {
                " (YAML reads it as text: write a float with a dot and a signed exponent, e.g. 1.0e-3)"
            }
            _ => "",
        };
        Error(format!("{what}: expected a number, got {v}{hint}"))
    })
}

fn value_and_source<'a>(v: &'a Value, what: &str) -> Result<(&'a Value, String), Error> {
    let Some(m) = v.as_map() else {
        return err(format!(
            "{what}: a value is {{value: ..., source: \"...\"}}, never bare (got {v})"
        ));
    };
    only(m, &["value", "source", "notes"], what)?;
    let value = get(m, "value", what)?;
    let source = text(get(m, "source", what)?, &format!("{what}.source"))?;
    if source.trim().is_empty() {
        return err(format!("{what}: its source is empty"));
    }
    Ok((value, source))
}

/// `{value: <number>, source}`.
pub fn num(v: &Value, what: &str) -> Result<Sourced<f64>, Error> {
    let (x, source) = value_and_source(v, what)?;
    let x = number(x, &format!("{what}.value"))?;
    if !x.is_finite() {
        return err(format!("{what}: not a finite number"));
    }
    Ok(Sourced::new(x, source))
}

/// `{value: <number>, source}` with value >= 0.
pub fn non_negative(v: &Value, what: &str) -> Result<Sourced<f64>, Error> {
    let s = num(v, what)?;
    if s.value < 0.0 {
        return err(format!("{what}: must be >= 0 (got {})", s.value));
    }
    Ok(s)
}

/// `{value: <number>, source}` with value > 0.
pub fn positive(v: &Value, what: &str) -> Result<Sourced<f64>, Error> {
    let s = num(v, what)?;
    if s.value <= 0.0 {
        return err(format!("{what}: must be > 0 (got {})", s.value));
    }
    Ok(s)
}

/// `{value: <whole number >= 1>, source}`.
pub fn count(v: &Value, what: &str) -> Result<Sourced<u32>, Error> {
    let s = num(v, what)?;
    if s.value < 1.0 || s.value.fract() != 0.0 || s.value > f64::from(u32::MAX) {
        return err(format!(
            "{what}: must be a whole number >= 1 (got {})",
            s.value
        ));
    }
    Ok(Sourced::new(s.value as u32, s.source))
}

/// `{value: <text>, source}`.
pub fn label(v: &Value, what: &str) -> Result<Sourced<String>, Error> {
    let (x, source) = value_and_source(v, what)?;
    Ok(Sourced::new(text(x, &format!("{what}.value"))?, source))
}
