//! Edits to the drawing's values, and their history (`varimu/listen/editor/edits.js`).
//!
//! Every edit keeps the importer's rules: a number has a source (an edit's source says it
//! is the user's and what it was), parts sharing a Param agree on value and source, a
//! genome link belongs to a parameter, never to an inline value.

use varimu_circuit::drawing::{Drawing, Symbol};
use varimu_circuit::yaml::{Map, Value};

use super::eng::{eng_text, parse_num};

/// Today's local date, YYYY-MM-DD.
pub fn today() -> String {
    #[cfg(windows)]
    {
        let t = unsafe {
            let mut t = std::mem::zeroed::<windows_sys::Win32::Foundation::SYSTEMTIME>();
            windows_sys::Win32::System::SystemInformation::GetLocalTime(&mut t);
            t
        };
        format!("{:04}-{:02}-{:02}", t.wYear, t.wMonth, t.wDay)
    }
    #[cfg(not(windows))]
    {
        // UTC (civil from days, Howard Hinnant's algorithm).
        let days = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map_or(0, |d| d.as_secs() / 86400) as i64;
        let z = days + 719_468;
        let era = z.div_euclid(146_097);
        let doe = z - era * 146_097;
        let yoe = (doe - doe / 1460 + doe / 36524 - doe / 146_096) / 365;
        let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
        let mp = (5 * doy + 2) / 153;
        let d = doy - (153 * mp + 2) / 5 + 1;
        let m = if mp < 10 { mp + 3 } else { mp - 9 };
        let y = yoe + era * 400 + i64::from(m <= 2);
        format!("{y:04}-{m:02}-{d:02}")
    }
}

/// The default source of an edited value: whose it is, and what it replaced. Editing an
/// edit keeps what the first edit replaced (the value's real provenance).
pub fn edit_source(old_value: &str, old_source: &str) -> String {
    if let Some(rest) = old_source.strip_prefix("edit ")
        && let Some((date, tail)) = rest.split_once(": by ear; ")
        && !date.is_empty()
        && date.chars().all(|c| c.is_ascii_digit() || c == '-')
        && tail.starts_with("was ")
    {
        return format!("edit {}: by ear; {tail}", today());
    }
    let was = if old_source.is_empty() {
        String::new()
    } else {
        format!(" ({old_source})")
    };
    format!("edit {}: by ear; was {old_value}{was}", today())
}

/// Where a parameter lives.
#[derive(Debug, Clone, PartialEq)]
pub enum Home {
    /// The symbols that carry it as their Param.
    Symbols(Vec<String>),
    /// The sidecar's `controls`, `values` or `device_params` entry.
    Entry(&'static str),
}

pub const SIDECAR_KINDS: [&str; 3] = ["controls", "values", "device_params"];

/// Where parameter `key` lives: the symbols that carry it as their Param, or the
/// sidecar's values / controls / device_params entry.
pub fn param_home(d: &Drawing, key: &str) -> Option<Home> {
    let refs: Vec<String> = d
        .symbols
        .iter()
        .filter(|(_, s)| s.field("Param") == Some(key))
        .map(|(r, _)| r.clone())
        .collect();
    if !refs.is_empty() {
        return Some(Home::Symbols(refs));
    }
    SIDECAR_KINDS.into_iter().find_map(|kind| {
        d.circuit
            .get(kind)
            .and_then(Value::as_map)
            .is_some_and(|m| m.contains(key))
            .then_some(Home::Entry(kind))
    })
}

/// The sidecar entry of `key` under `kind`, to change.
pub fn entry_mut<'a>(d: &'a mut Drawing, kind: &str, key: &str) -> Option<&'a mut Map> {
    match d.circuit.get_mut(kind)? {
        Value::Map(m) => match m.get_mut(key)? {
            Value::Map(e) => Some(e),
            _ => None,
        },
        _ => None,
    }
}

/// Set parameter `key` to `value` (a number or a string) with `source` (None: keep it).
/// False when the key lives nowhere the drawing can change.
pub fn set_param(d: &mut Drawing, key: &str, value: &Value, source: Option<&str>) -> bool {
    let Some(home) = param_home(d, key) else {
        return false;
    };
    match home {
        Home::Symbols(refs) => {
            let text = match value {
                Value::Int(_) | Value::Float(_) => eng_text(value.as_f64().unwrap_or(0.0)),
                other => other.py_str(),
            };
            for r in refs {
                let s = d.symbol_mut(&r).expect("a symbol on the parameter");
                s.value = text.clone();
                if let Some(src) = source {
                    s.set_field("Source", src);
                }
            }
        }
        Home::Entry(kind) => {
            let e = entry_mut(d, kind, key).expect("the parameter's entry");
            e.insert("value", value.clone());
            if let Some(src) = source
                && kind != "controls"
            {
                e.insert("source", Value::Str(src.into()));
            }
        }
    }
    true
}

/// A symbol's own value (no Param): its Value and Source.
pub fn set_inline(d: &mut Drawing, r: &str, text: &str, source: &str) {
    if let Some(s) = d.symbol_mut(r) {
        s.value = text.into();
        s.set_field("Source", source);
    }
}

/// Take a symbol off its shared Param: its value becomes inline, with the parameter's
/// source (a genome link stays with the parameter).
pub fn unlink(d: &mut Drawing, r: &str) {
    let Some(s) = d.symbol(r) else { return };
    let Some(key) = s.field("Param").map(str::to_string) else {
        return;
    };
    let mine = s.clone();
    let others: Vec<String> = d
        .symbols
        .iter()
        .filter(|(o, x)| o != r && x.field("Param") == Some(key.as_str()))
        .map(|(o, _)| o.clone())
        .collect();
    let field_of = |d: &Drawing, o: &str, k: &str| -> Option<String> {
        d.symbol(o)?
            .field(k)
            .filter(|v| !v.is_empty())
            .map(str::to_string)
    };
    let source = mine
        .field("Source")
        .filter(|v| !v.is_empty())
        .map(str::to_string)
        .or_else(|| others.iter().find_map(|o| field_of(d, o, "Source")))
        .unwrap_or_default();
    let any_source = others.iter().any(|o| field_of(d, o, "Source").is_some());
    if !any_source
        && let Some(src) = mine.field("Source").filter(|v| !v.is_empty())
        && let Some(first) = others.first()
    {
        d.symbol_mut(first).expect("other").set_field("Source", src);
    }
    if others.is_empty() {
        return; // the only part on it: nothing to unlink from
    }
    // The parameter's other metadata stays on the parts that still carry it.
    for k in ["Genome", "Unit", "Notes"] {
        if let Some(v) = mine.field(k).filter(|v| !v.is_empty())
            && !others.iter().any(|o| field_of(d, o, k).is_some())
        {
            d.symbol_mut(&others[0]).expect("other").set_field(k, v);
        }
    }
    let s = d.symbol_mut(r).expect("the symbol");
    for k in ["Param", "Genome", "Unit", "Notes"] {
        s.remove_field(k);
    }
    s.set_field("Source", &source);
}

/// The parameter a symbol's main value is (its Param, or a key it names), or None.
pub fn value_key(s: &Symbol) -> Option<String> {
    if let Some(p) = s.field("Param") {
        return Some(p.into());
    }
    (!s.value.is_empty() && parse_num(&s.value).is_none()).then(|| s.value.clone())
}

/// Undo and redo: the drawing before each edit, with the edit's label.
#[derive(Debug, Clone, Default)]
pub struct History {
    pub past: Vec<(Drawing, String)>,
    pub future: Vec<(Drawing, String)>,
    /// The drawing as opened (or last saved).
    pub base: Option<Drawing>,
}

impl History {
    pub fn reset(&mut self, d: Option<&Drawing>) {
        self.past.clear();
        self.future.clear();
        self.base = d.cloned();
    }

    /// Record the drawing before an edit labelled `label`.
    pub fn push(&mut self, d: Drawing, label: &str) {
        self.past.push((d, label.into()));
        self.future.clear();
    }

    /// The drawing before the last edit, and its label.
    pub fn undo(&mut self, current: &Drawing) -> Option<(Drawing, String)> {
        let (d, label) = self.past.pop()?;
        self.future.push((current.clone(), label.clone()));
        Some((d, label))
    }

    pub fn redo(&mut self, current: &Drawing) -> Option<(Drawing, String)> {
        let (d, label) = self.future.pop()?;
        self.past.push((current.clone(), label.clone()));
        Some((d, label))
    }

    pub fn is_edited(&self, current: &Drawing) -> bool {
        self.base.as_ref().is_some_and(|b| b != current)
    }
}

#[cfg(test)]
mod tests {
    //! tests/editor_js/edits.test.mjs, ported.
    use super::*;
    use varimu_circuit::drawing::Symbol;

    fn sym(symbol: &str, value: &str, fields: &[(&str, &str)]) -> Symbol {
        Symbol {
            symbol: symbol.into(),
            value: value.into(),
            fields: fields
                .iter()
                .map(|(k, v)| (k.to_string(), v.to_string()))
                .collect(),
            units: Vec::new(),
        }
    }

    fn entry(pairs: &[(&str, Value)]) -> Value {
        Value::Map(Map(pairs
            .iter()
            .map(|(k, v)| (k.to_string(), v.clone()))
            .collect()))
    }

    fn drawing() -> Drawing {
        let s = |x: &str| Value::Str(x.into());
        let mut d = Drawing {
            circuit: Map(vec![
                (
                    "values".into(),
                    entry(&[(
                        "load_ohm",
                        entry(&[("value", Value::Int(600)), ("source", s("man"))]),
                    )]),
                ),
                (
                    "controls".into(),
                    entry(&[(
                        "knob",
                        entry(&[
                            ("value", Value::Float(0.5)),
                            ("min", Value::Int(0)),
                            ("max", Value::Int(1)),
                            ("source", s("panel")),
                        ]),
                    )]),
                ),
            ]),
            ..Drawing::default()
        };
        d.symbols = vec![
            (
                "CC2A".into(),
                sym(
                    "C",
                    "250n",
                    &[
                        ("Param", "c_couple_f"),
                        ("Source", "dwg: .25"),
                        ("Tol", "paper"),
                    ],
                ),
            ),
            (
                "CC2B".into(),
                sym(
                    "C",
                    "250n",
                    &[
                        ("Param", "c_couple_f"),
                        ("Source", "dwg: .25"),
                        ("Genome", "g.c"),
                    ],
                ),
            ),
            ("R1".into(), sym("R", "1k", &[("Source", "mine")])),
            ("RL".into(), sym("R", "load_ohm", &[])),
        ];
        d
    }

    #[test]
    fn a_shared_parameter_changes_on_every_part_with_one_source() {
        let mut d = drawing();
        assert_eq!(
            param_home(&d, "c_couple_f"),
            Some(Home::Symbols(vec!["CC2A".into(), "CC2B".into()]))
        );
        set_param(
            &mut d,
            "c_couple_f",
            &Value::Float(4.7e-7),
            Some("edit: by ear"),
        );
        for r in ["CC2A", "CC2B"] {
            let s = d.symbol(r).unwrap();
            assert_eq!(s.value, "470n");
            assert_eq!(s.field("Source"), Some("edit: by ear"));
        }
    }

    #[test]
    fn sidecar_values_and_controls() {
        let mut d = drawing();
        assert_eq!(param_home(&d, "load_ohm"), Some(Home::Entry("values")));
        set_param(&mut d, "load_ohm", &Value::Int(10000), Some("edit"));
        assert_eq!(
            d.circuit
                .get("values")
                .unwrap()
                .as_map()
                .unwrap()
                .get("load_ohm"),
            Some(&entry(&[
                ("value", Value::Int(10000)),
                ("source", Value::Str("edit".into()))
            ]))
        );
        set_param(
            &mut d,
            "knob",
            &Value::Float(0.8),
            Some("ignored for a control"),
        );
        let knob = d
            .circuit
            .get("controls")
            .unwrap()
            .as_map()
            .unwrap()
            .get("knob")
            .unwrap();
        assert_eq!(
            knob.as_map().unwrap().get("value"),
            Some(&Value::Float(0.8))
        );
        assert_eq!(
            knob.as_map().unwrap().get("source"),
            Some(&Value::Str("panel".into()))
        );
        assert!(!set_param(&mut d, "nowhere", &Value::Int(1), Some("s")));
        assert_eq!(value_key(d.symbol("RL").unwrap()), Some("load_ohm".into()));
        assert_eq!(value_key(d.symbol("R1").unwrap()), None);
        assert_eq!(
            value_key(d.symbol("CC2A").unwrap()),
            Some("c_couple_f".into())
        );
    }

    #[test]
    fn unlinking_a_part_keeps_the_parameter_whole_on_the_others() {
        let mut d = drawing();
        unlink(&mut d, "CC2B"); // CC2B carried the genome link: it moves to CC2A
        assert_eq!(
            d.symbol("CC2B").unwrap().fields,
            [("Source".to_string(), "dwg: .25".to_string())]
        );
        assert_eq!(d.symbol("CC2A").unwrap().field("Genome"), Some("g.c"));
        assert_eq!(d.symbol("CC2A").unwrap().field("Param"), Some("c_couple_f"));
        let mut e = drawing();
        e.symbol_mut("CC2A").unwrap().remove_field("Source"); // the source lives on the other
        unlink(&mut e, "CC2B");
        assert_eq!(e.symbol("CC2A").unwrap().field("Source"), Some("dwg: .25"));
        set_inline(&mut e, "CC2B", "330n", "edit");
        assert_eq!(e.symbol("CC2B").unwrap().value, "330n");
    }

    #[test]
    fn an_edit_source_says_whose_it_is_and_what_it_replaced() {
        let t = today();
        assert_eq!(
            edit_source("250n", "dwg: .25 coupling"),
            format!("edit {t}: by ear; was 250n (dwg: .25 coupling)")
        );
        // Editing an edit keeps what the first one replaced.
        let twice = edit_source("330n", &edit_source("250n", "dwg"));
        assert_eq!(twice, format!("edit {t}: by ear; was 250n (dwg)"));
    }

    #[test]
    fn history_undo_and_redo_restore_drawings() {
        let mut h = History::default();
        let mut d = drawing();
        h.reset(Some(&d));
        h.push(d.clone(), "first");
        set_param(&mut d, "c_couple_f", &Value::Float(1e-6), Some("s"));
        assert!(h.is_edited(&d));
        let (u, label) = h.undo(&d).unwrap();
        assert_eq!(label, "first");
        assert_eq!(u.symbol("CC2A").unwrap().value, "250n");
        assert!(!h.is_edited(&u));
        let (r, _) = h.redo(&u).unwrap();
        assert_eq!(r.symbol("CC2A").unwrap().value, "1u");
        assert_eq!(h.undo(&r).unwrap().0.symbol("CC2A").unwrap().value, "250n");
        assert!(h.undo(&drawing()).is_none());
    }
}
