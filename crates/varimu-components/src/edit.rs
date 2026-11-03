//! Editing a design as data: what the Components view does to a transformer's source.
//!
//! The design stays the YAML tree it was read as (`Value`), so a value that isn't edited
//! keeps its source and its form, and a design opened from a version and saved unchanged
//! compiles to that version's text. A path names a place in the tree (`["core",
//! "stack_m"]`, `["sections", 2, "turns"]`); an edited physical value gets a new
//! `{value, source}`: the source says it is a design choice made in the view (it is
//! neither data nor a fit), unless the view gives another.

use varimu_circuit::yaml::{Map, Value};

use crate::{Error, err};

/// A step of a path: a mapping's key or a list's index.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Step {
    Key(String),
    Index(usize),
}

impl From<&str> for Step {
    fn from(k: &str) -> Step {
        Step::Key(k.to_string())
    }
}

impl From<usize> for Step {
    fn from(i: usize) -> Step {
        Step::Index(i)
    }
}

/// `path!["sections", 2, "turns"]`: an array of steps (borrowed as a slice, or
/// `.into()` a `Vec` where a path is kept).
#[macro_export]
macro_rules! path {
    ($($s:expr),* $(,)?) => { [$($crate::edit::Step::from($s)),*] };
}

/// The source of a value chosen in the Components view on `date`.
pub fn chosen(date: &str) -> String {
    format!("design choice: set in the Components view ({date})")
}

/// The design a version file holds: its name, kind and source and its `construction`.
pub fn design_of_version(version: &Value) -> Result<Value, Error> {
    let m = version
        .as_map()
        .ok_or_else(|| Error("a version: a mapping".into()))?;
    if m.get("kind").and_then(Value::as_str) != Some("transformer") {
        return err("not a transformer version");
    }
    let Some(Value::Map(c)) = m.get("construction") else {
        return err("the version has no construction");
    };
    let mut out = Map::default();
    for k in ["name", "kind", "source"] {
        if let Some(v) = m.get(k) {
            out.insert(k, v.clone());
        }
    }
    for (k, v) in c.iter() {
        out.insert(k, v.clone());
    }
    Ok(Value::Map(out))
}

pub fn get<'a>(v: &'a Value, path: &[Step]) -> Option<&'a Value> {
    let mut at = v;
    for s in path {
        at = match (s, at) {
            (Step::Key(k), Value::Map(m)) => m.get(k)?,
            (Step::Index(i), Value::List(l)) => l.get(*i)?,
            _ => return None,
        };
    }
    Some(at)
}

/// The place at `path`, mappings created along the way where a key is missing.
pub fn get_mut<'a>(v: &'a mut Value, path: &[Step]) -> Result<&'a mut Value, Error> {
    let mut at = v;
    for s in path {
        at = match (s, at) {
            (Step::Key(k), Value::Map(m)) => {
                if !m.contains(k) {
                    m.insert(k, Value::Map(Map::default()));
                }
                m.get_mut(k).unwrap()
            }
            (Step::Index(i), Value::List(l)) => match l.get_mut(*i) {
                Some(x) => x,
                None => return err(format!("no item {i}")),
            },
            (s, _) => return err(format!("{s:?}: not there")),
        };
    }
    Ok(at)
}

/// The `value` of the `{value, source}` at `path`.
pub fn value<'a>(v: &'a Value, path: &[Step]) -> Option<&'a Value> {
    get(v, path)?.as_map()?.get("value")
}

pub fn number(v: &Value, path: &[Step]) -> Option<f64> {
    value(v, path)?.as_f64()
}

pub fn text(v: &Value, path: &[Step]) -> Option<String> {
    match value(v, path)? {
        Value::Str(s) => Some(s.clone()),
        x => Some(x.py_str()),
    }
}

pub fn source(v: &Value, path: &[Step]) -> Option<String> {
    get(v, path)?
        .as_map()?
        .get("source")?
        .as_str()
        .map(str::to_string)
}

/// Sets the `{value, source}` at `path` (created if missing).
pub fn set(v: &mut Value, path: &[Step], x: Value, source: &str) -> Result<(), Error> {
    let place = get_mut(v, path)?;
    *place = sourced(x, source);
    Ok(())
}

/// `{value: x, source}`.
pub fn sourced(x: Value, source: &str) -> Value {
    Value::Map(Map(vec![
        ("value".into(), x),
        ("source".into(), Value::Str(source.into())),
    ]))
}

/// Removes the key at the end of `path` (an optional value). True when it was there.
pub fn remove(v: &mut Value, path: &[Step]) -> Result<bool, Error> {
    let Some((Step::Key(k), parent)) = path.split_last() else {
        return err("remove: a path ending in a key");
    };
    let Value::Map(m) = get_mut(v, parent)? else {
        return err("remove: not a mapping");
    };
    Ok(m.remove(k).is_some())
}

/// Sets a plain (unsourced) entry, e.g. `leakage_method`.
pub fn set_plain(v: &mut Value, key: &str, x: Value) -> Result<(), Error> {
    let Value::Map(m) = v else {
        return err("a design: a mapping");
    };
    if !m.contains(key) {
        // Keep the file's order: before `rating` when there is one.
        let at =
            m.0.iter()
                .position(|(k, _)| k == "rating")
                .unwrap_or(m.0.len());
        m.0.insert(at, (key.to_string(), x));
    } else {
        m.insert(key, x);
    }
    Ok(())
}

fn sections_mut(v: &mut Value) -> Result<&mut Vec<Value>, Error> {
    match get_mut(v, &path!["sections"])? {
        Value::List(l) => Ok(l),
        _ => err("sections: a list"),
    }
}

pub fn sections(v: &Value) -> &[Value] {
    get(v, &path!["sections"])
        .and_then(Value::as_list)
        .unwrap_or(&[])
}

/// The design's winding labels.
pub fn windings(v: &Value) -> Vec<String> {
    get(v, &path!["windings"])
        .and_then(Value::as_list)
        .unwrap_or(&[])
        .iter()
        .filter_map(|x| x.as_str().map(str::to_string))
        .collect()
}

/// What a section is.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum SectionKind {
    Winding,
    Insulation,
    Shield,
}

pub fn section_kind(s: &Value) -> Option<SectionKind> {
    let m = s.as_map()?;
    if m.contains("winding") {
        Some(SectionKind::Winding)
    } else if m.contains("insulation") {
        Some(SectionKind::Insulation)
    } else if m.contains("shield") {
        Some(SectionKind::Shield)
    } else {
        None
    }
}

/// Inserts `section` at `at` (clamped to the end).
pub fn insert_section(v: &mut Value, at: usize, section: Value) -> Result<(), Error> {
    let l = sections_mut(v)?;
    let at = at.min(l.len());
    l.insert(at, section);
    Ok(())
}

pub fn remove_section(v: &mut Value, at: usize) -> Result<Value, Error> {
    let l = sections_mut(v)?;
    if at >= l.len() {
        return err(format!("no section {at}"));
    }
    Ok(l.remove(at))
}

/// Moves section `from` to `to` (an index in the list after it is taken out).
pub fn move_section(v: &mut Value, from: usize, to: usize) -> Result<(), Error> {
    let s = remove_section(v, from)?;
    insert_section(v, to, s)
}

/// A copy of section `at` inserted after it (a winding split in two, an insulation
/// repeated: edit the copy).
pub fn duplicate_section(v: &mut Value, at: usize) -> Result<(), Error> {
    let s = sections(v)
        .get(at)
        .cloned()
        .ok_or_else(|| Error(format!("no section {at}")))?;
    insert_section(v, at + 1, s)
}

/// An insulation wrap: `{insulation: {thickness_m, dielectric}}`.
pub fn insulation_section(thickness_m: f64, dielectric: &str, source: &str) -> Value {
    Value::Map(Map(vec![(
        "insulation".into(),
        Value::Map(Map(vec![
            (
                "thickness_m".into(),
                sourced(Value::Float(thickness_m), source),
            ),
            (
                "dielectric".into(),
                sourced(Value::Str(dielectric.into()), source),
            ),
        ])),
    )]))
}

/// A winding section of `turns` in `layers` of `wire`.
pub fn winding_section(
    winding: &str,
    turns: u32,
    layers: u32,
    wire: &str,
    enamel: &str,
    source: &str,
) -> Value {
    Value::Map(Map(vec![
        ("winding".into(), Value::Str(winding.into())),
        ("turns".into(), sourced(Value::Int(turns.into()), source)),
        ("layers".into(), sourced(Value::Int(layers.into()), source)),
        ("wire".into(), sourced(Value::Str(wire.into()), source)),
        ("enamel".into(), sourced(Value::Str(enamel.into()), source)),
    ]))
}

/// A section's winding label.
pub fn section_winding(s: &Value) -> Option<&str> {
    s.as_map()?.get("winding")?.as_str()
}

/// Sets a winding section's label (it must be one of the design's windings).
pub fn set_section_winding(v: &mut Value, at: usize, winding: &str) -> Result<(), Error> {
    if !windings(v).iter().any(|w| w == winding) {
        return err(format!("{winding} isn't one of the design's windings"));
    }
    let s = get_mut(v, &path!["sections", at])?;
    match s {
        Value::Map(m) if m.contains("winding") => {
            m.insert("winding", Value::Str(winding.into()));
            Ok(())
        }
        _ => err(format!("section {at} isn't a winding")),
    }
}

/// Splits winding section `at` in two along its turns and layers (`first` turns and
/// `first_layers` layers stay; the rest goes in a copy after it), both keeping the
/// section's other values: the start of interleaving a winding with another.
pub fn split_section(
    v: &mut Value,
    at: usize,
    first: u32,
    first_layers: u32,
    source: &str,
) -> Result<(), Error> {
    let s = sections(v)
        .get(at)
        .cloned()
        .ok_or_else(|| Error(format!("no section {at}")))?;
    if section_kind(&s) != Some(SectionKind::Winding) {
        return err(format!("section {at} isn't a winding"));
    }
    let turns = number(&s, &path!["turns"]).unwrap_or(0.0) as u32;
    let layers = number(&s, &path!["layers"]).unwrap_or(0.0) as u32;
    if first == 0 || first >= turns || first_layers == 0 || first_layers >= layers {
        return err(format!(
            "split: 1..{} turns and 1..{} layers stay in the first part",
            turns.saturating_sub(1),
            layers.saturating_sub(1)
        ));
    }
    let mut a = s.clone();
    let mut b = s;
    for (x, t, l) in [
        (&mut a, first, first_layers),
        (&mut b, turns - first, layers - first_layers),
    ] {
        set(x, &path!["turns"], Value::Int(t.into()), source)?;
        set(x, &path!["layers"], Value::Int(l.into()), source)?;
        // A drawn width or build belonged to the whole section.
        if let Value::Map(m) = x {
            m.remove("build_m");
        }
    }
    let l = sections_mut(v)?;
    l[at] = a;
    l.insert(at + 1, b);
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use varimu_circuit::yaml;

    const SRC: &str = "\
name: T
kind: transformer
source: a test
core:
  stack_m: {value: 0.0254, source: s}
windings: [p, s]
sections:
  - winding: p
    turns: {value: 100, source: s}
    layers: {value: 4, source: s}
  - insulation: {thickness_m: {value: 1.0e-4, source: s}, dielectric: {value: kraft_dry, source: s}}
  - winding: s
    turns: {value: 10, source: s}
    layers: {value: 1, source: s}
rating: {windings: [p], v_rms: {value: 1.0, source: s}, f_hz: {value: 50.0, source: s}}
";

    #[test]
    fn edits_keep_the_rest() {
        let mut d = yaml::parse(SRC, "t").unwrap();
        let before = d.clone();
        assert_eq!(number(&d, &path!["core", "stack_m"]), Some(0.0254));
        set(&mut d, &path!["core", "stack_m"], Value::Float(0.03), "x").unwrap();
        assert_eq!(number(&d, &path!["core", "stack_m"]), Some(0.03));
        assert_eq!(source(&d, &path!["core", "stack_m"]).as_deref(), Some("x"));
        assert_eq!(
            get(&d, &path!["sections"]),
            get(&before, &path!["sections"])
        );
        set_plain(&mut d, "leakage_method", Value::Str("field".into())).unwrap();
        let keys: Vec<&str> = d.as_map().unwrap().keys().collect();
        assert_eq!(keys[keys.len() - 2..], ["leakage_method", "rating"]);
    }

    #[test]
    fn sections_split_move_and_remove() {
        let mut d = yaml::parse(SRC, "t").unwrap();
        split_section(&mut d, 0, 60, 2, "x").unwrap();
        assert_eq!(sections(&d).len(), 4);
        assert_eq!(number(&sections(&d)[0], &path!["turns"]), Some(60.0));
        assert_eq!(number(&sections(&d)[1], &path!["turns"]), Some(40.0));
        assert_eq!(number(&sections(&d)[1], &path!["layers"]), Some(2.0));
        // p | s | p: the secondary between the halves.
        move_section(&mut d, 3, 1).unwrap();
        let kinds: Vec<_> = sections(&d).iter().map(|s| section_winding(s)).collect();
        assert_eq!(kinds, [Some("p"), Some("s"), Some("p"), None]);
        assert!(split_section(&mut d, 1, 5, 1, "x").is_err()); // one layer can't split
        remove_section(&mut d, 3).unwrap();
        insert_section(&mut d, 1, insulation_section(2e-4, "kraft_dry", "x")).unwrap();
        assert_eq!(
            section_kind(&sections(&d)[1]),
            Some(SectionKind::Insulation)
        );
        assert!(set_section_winding(&mut d, 0, "q").is_err());
    }
}
