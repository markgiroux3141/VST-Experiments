//! Writing YAML as PyYAML's `safe_dump` writes it (the subset circuit files use), and
//! the circuit file's layout (`varimu.kicad.importer.to_yaml`), so a drawing compiled
//! here writes the same circuit file the Python editor writes.
//!
//! PyYAML's rules kept: a collection whose items are all scalars is written in flow
//! style (`{a: 1}`, `[x, y]`) when the default flow style is None, block style
//! otherwise; a string is plain unless it would read back as another type (YAML 1.1:
//! `yes`, `0`, `1.0`, `null`, ...) or its characters forbid it (indicators, leading or
//! trailing space, `: `, ` #`, and in flow context `,[]{}`), then single-quoted, or
//! double-quoted with escapes when it has characters outside printable ASCII
//! (`allow_unicode` is off); floats are `repr` with `.0` before an exponent that has no
//! dot. Line breaks inside strings go double-quoted (PyYAML would fold single quotes);
//! circuit files have none.

use std::sync::OnceLock;

use regex::Regex;

use crate::yaml::{Map, Value, py_float_repr};

/// PyYAML's implicit resolvers (YAML 1.1): a plain scalar matching one is not a string.
fn resolves_non_str(s: &str) -> bool {
    static RE: OnceLock<Vec<Regex>> = OnceLock::new();
    let res = RE.get_or_init(|| {
        [
            r"^(?:yes|Yes|YES|no|No|NO|true|True|TRUE|false|False|FALSE|on|On|ON|off|Off|OFF)$",
            r"^(?:[-+]?(?:[0-9][0-9_]*)\.[0-9_]*(?:[eE][-+][0-9]+)?|\.[0-9][0-9_]*(?:[eE][-+][0-9]+)?|[-+]?[0-9][0-9_]*(?::[0-5]?[0-9])+\.[0-9_]*|[-+]?\.(?:inf|Inf|INF)|\.(?:nan|NaN|NAN))$",
            r"^(?:[-+]?0b[0-1_]+|[-+]?0[0-7_]+|[-+]?(?:0|[1-9][0-9_]*)|[-+]?0x[0-9a-fA-F_]+|[-+]?[1-9][0-9_]*(?::[0-5]?[0-9])+)$",
            r"^(?:<<)$",
            r"^(?:~|null|Null|NULL|)$",
            r"^(?:[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]|[0-9][0-9][0-9][0-9]-[0-9][0-9]?-[0-9][0-9]?(?:[Tt]|[ \t]+)[0-9][0-9]?:[0-9][0-9]:[0-9][0-9](?:\.[0-9]*)?(?:[ \t]*(?:Z|[-+][0-9][0-9]?(?::[0-9][0-9])?))?)$",
            r"^(?:=)$",
        ]
        .iter()
        .map(|p| Regex::new(p).expect("a resolver pattern"))
        .collect()
    });
    res.iter().any(|r| r.is_match(s))
}

/// What `analyze_scalar` finds about a scalar's text.
struct Analysis {
    empty: bool,
    multiline: bool,
    allow_flow_plain: bool,
    allow_block_plain: bool,
    allow_single_quoted: bool,
}

fn is_ws(c: Option<char>) -> bool {
    matches!(
        c,
        None | Some('\0' | ' ' | '\t' | '\r' | '\n' | '\u{85}' | '\u{2028}' | '\u{2029}')
    )
}

fn analyze(s: &str) -> Analysis {
    if s.is_empty() {
        return Analysis {
            empty: true,
            multiline: false,
            allow_flow_plain: false,
            allow_block_plain: true,
            allow_single_quoted: true,
        };
    }
    let chars: Vec<char> = s.chars().collect();
    let n = chars.len();
    let (mut block_ind, mut flow_ind) = (false, false);
    let (mut line_breaks, mut special) = (false, false);
    let (mut leading_space, mut leading_break) = (false, false);
    let (mut trailing_space, mut trailing_break) = (false, false);
    let (mut break_space, mut space_break) = (false, false);
    if s.starts_with("---") || s.starts_with("...") {
        block_ind = true;
        flow_ind = true;
    }
    let mut preceded_ws = true;
    let mut followed_ws = n == 1 || is_ws(chars.get(1).copied());
    let (mut prev_space, mut prev_break) = (false, false);
    for (i, &ch) in chars.iter().enumerate() {
        if i == 0 {
            if "#,[]{}&*!|>'\"%@`".contains(ch) {
                flow_ind = true;
                block_ind = true;
            }
            if "?:".contains(ch) {
                flow_ind = true;
                if followed_ws {
                    block_ind = true;
                }
            }
            if ch == '-' && followed_ws {
                flow_ind = true;
                block_ind = true;
            }
        } else {
            if ",?[]{}".contains(ch) {
                flow_ind = true;
            }
            if ch == ':' {
                flow_ind = true;
                if followed_ws {
                    block_ind = true;
                }
            }
            if ch == '#' && preceded_ws {
                flow_ind = true;
                block_ind = true;
            }
        }
        let brk = matches!(ch, '\n' | '\u{85}' | '\u{2028}' | '\u{2029}');
        if brk {
            line_breaks = true;
        }
        // allow_unicode is off: anything outside printable ASCII is special.
        if !(ch == '\n' || (' '..='~').contains(&ch)) {
            special = true;
        }
        if ch == ' ' {
            if i == 0 {
                leading_space = true;
            }
            if i == n - 1 {
                trailing_space = true;
            }
            if prev_break {
                break_space = true;
            }
            prev_space = true;
            prev_break = false;
        } else if brk {
            if i == 0 {
                leading_break = true;
            }
            if i == n - 1 {
                trailing_break = true;
            }
            if prev_space {
                space_break = true;
            }
            prev_space = false;
            prev_break = true;
        } else {
            prev_space = false;
            prev_break = false;
        }
        preceded_ws = is_ws(Some(ch));
        followed_ws = i + 2 >= n || is_ws(chars.get(i + 2).copied());
    }
    let (mut flow_plain, mut block_plain, mut single) = (true, true, true);
    if leading_space || leading_break || trailing_space || trailing_break {
        flow_plain = false;
        block_plain = false;
    }
    if break_space {
        flow_plain = false;
        block_plain = false;
        single = false;
    }
    if space_break || special {
        flow_plain = false;
        block_plain = false;
        single = false;
    }
    if line_breaks {
        flow_plain = false;
        block_plain = false;
    }
    if flow_ind {
        flow_plain = false;
    }
    if block_ind {
        block_plain = false;
    }
    Analysis {
        empty: false,
        multiline: line_breaks,
        allow_flow_plain: flow_plain,
        allow_block_plain: block_plain,
        allow_single_quoted: single,
    }
}

fn double_quoted(s: &str) -> String {
    let mut out = String::from("\"");
    for ch in s.chars() {
        let rep = match ch {
            '\0' => Some('0'),
            '\u{7}' => Some('a'),
            '\u{8}' => Some('b'),
            '\t' => Some('t'),
            '\n' => Some('n'),
            '\u{b}' => Some('v'),
            '\u{c}' => Some('f'),
            '\r' => Some('r'),
            '\u{1b}' => Some('e'),
            '"' => Some('"'),
            '\\' => Some('\\'),
            '\u{85}' => Some('N'),
            '\u{a0}' => Some('_'),
            '\u{2028}' => Some('L'),
            '\u{2029}' => Some('P'),
            _ => None,
        };
        if let Some(r) = rep {
            out.push('\\');
            out.push(r);
        } else if (' '..='~').contains(&ch) {
            out.push(ch);
        } else if (ch as u32) <= 0xFF {
            out.push_str(&format!("\\x{:02X}", ch as u32));
        } else if (ch as u32) <= 0xFFFF {
            out.push_str(&format!("\\u{:04X}", ch as u32));
        } else {
            out.push_str(&format!("\\U{:08X}", ch as u32));
        }
    }
    out.push('"');
    out
}

/// A scalar's text and whether a plain scalar of it reads back as its own type.
fn represent(v: &Value) -> (String, bool) {
    match v {
        Value::Null => ("null".into(), true),
        Value::Bool(b) => ((if *b { "true" } else { "false" }).into(), true),
        Value::Int(i) => (i.to_string(), true),
        Value::Float(x) => {
            let s = if x.is_nan() {
                ".nan".into()
            } else if x.is_infinite() {
                (if *x > 0.0 { ".inf" } else { "-.inf" }).into()
            } else {
                let r = py_float_repr(*x).to_lowercase();
                if !r.contains('.') && r.contains('e') {
                    r.replacen('e', ".0e", 1)
                } else {
                    r
                }
            };
            (s, true)
        }
        Value::Str(s) => (s.clone(), !resolves_non_str(s)),
        Value::List(_) | Value::Map(_) => unreachable!("not a scalar"),
    }
}

fn scalar(v: &Value, flow: bool, simple_key: bool) -> String {
    let (text, implicit) = represent(v);
    let a = analyze(&text);
    if implicit
        && !(simple_key && (a.empty || a.multiline))
        && ((flow && a.allow_flow_plain) || (!flow && a.allow_block_plain))
    {
        return text;
    }
    // PyYAML: single quotes unless a multiline simple key; line breaks go double-quoted
    // here (see the module docs), which covers that case too.
    if a.allow_single_quoted && !a.multiline {
        return format!("'{}'", text.replace('\'', "''"));
    }
    double_quoted(&text)
}

fn is_scalar(v: &Value) -> bool {
    !matches!(v, Value::List(_) | Value::Map(_))
}

/// Flow style throughout (`default_flow_style=True`).
fn flow_node(v: &Value) -> String {
    match v {
        Value::List(l) => {
            let items: Vec<String> = l.iter().map(flow_node).collect();
            format!("[{}]", items.join(", "))
        }
        Value::Map(m) => {
            let items: Vec<String> = m
                .iter()
                .map(|(k, x)| {
                    format!(
                        "{}: {}",
                        scalar(&Value::Str(k.into()), true, true),
                        flow_node(x)
                    )
                })
                .collect();
            format!("{{{}}}", items.join(", "))
        }
        s => scalar(s, true, false),
    }
}

/// `yaml.safe_dump(x, default_flow_style=True, width=10**9, sort_keys=False).strip()`.
pub fn flow(v: &Value) -> String {
    if is_scalar(v) {
        // A document of one scalar: block context.
        return scalar(v, false, false);
    }
    flow_node(v)
}

/// A scalar as an item of a flow sequence (`_flow([x])[1:-1]`).
pub fn flow_scalar(v: &Value) -> String {
    let s = flow_node(&Value::List(vec![v.clone()]));
    s[1..s.len() - 1].to_string()
}

/// With `default_flow_style=None`: flow when every item is a scalar.
fn flow_style(v: &Value) -> bool {
    match v {
        Value::List(l) => l.iter().all(is_scalar),
        Value::Map(m) => m.iter().all(|(_, x)| is_scalar(x)),
        _ => false,
    }
}

fn block_value(out: &mut Vec<String>, line: String, v: &Value, indent: usize) {
    if is_scalar(v) {
        out.push(format!("{line} {}", scalar(v, false, false)));
    } else if flow_style(v) {
        out.push(format!("{line} {}", flow_node(v)));
    } else {
        out.push(line);
        match v {
            Value::Map(m) => block_map(out, m, indent + 2),
            // Sequences in a mapping are indentless.
            Value::List(l) => block_seq(out, l, indent),
            _ => unreachable!(),
        }
    }
}

fn block_map(out: &mut Vec<String>, m: &Map, indent: usize) {
    let pad = " ".repeat(indent);
    for (k, v) in m.iter() {
        let key = scalar(&Value::Str(k.into()), false, true);
        block_value(out, format!("{pad}{key}:"), v, indent);
    }
}

fn block_seq(out: &mut Vec<String>, l: &[Value], indent: usize) {
    let pad = " ".repeat(indent);
    for v in l {
        if is_scalar(v) {
            out.push(format!("{pad}- {}", scalar(v, false, false)));
        } else if flow_style(v) {
            out.push(format!("{pad}- {}", flow_node(v)));
        } else if let Value::Map(m) = v {
            let mut inner = Vec::new();
            block_map(&mut inner, m, indent + 2);
            if let Some(first) = inner.first_mut() {
                *first = format!("{pad}- {}", &first[indent + 2..]);
            }
            out.extend(inner);
        } else if let Value::List(sub) = v {
            let mut inner = Vec::new();
            block_seq(&mut inner, sub, indent + 2);
            if let Some(first) = inner.first_mut() {
                *first = format!("{pad}- {}", &first[indent + 2..]);
            }
            out.extend(inner);
        }
    }
}

/// `yaml.safe_dump({key: val}, sort_keys=False, width=10**9, default_flow_style=None)
/// .rstrip()` for a collection `val`.
pub fn block_entry(key: &str, val: &Value) -> String {
    let mut out = Vec::new();
    let mut m = Map::default();
    m.0.push((key.to_string(), val.clone()));
    if flow_style(&Value::Map(m.clone())) {
        return flow_node(&Value::Map(m));
    }
    block_map(&mut out, &m, 0);
    out.join("\n")
}

/// `{k: v}` in flow style without its braces (a circuit file's one-line entry).
fn flow_entry(k: &str, v: &Value) -> String {
    let mut m = Map::default();
    m.0.push((k.to_string(), v.clone()));
    let s = flow_node(&Value::Map(m));
    s[1..s.len() - 1].to_string()
}

/// The circuit file, laid out like the hand-written ones: one entry per line
/// (`varimu.kicad.importer.to_yaml`).
pub fn to_yaml(data: &Map, header: &str) -> String {
    let mut out: Vec<String> = header
        .lines()
        .map(|l| format!("# {l}").trim_end().to_string())
        .collect();
    if !out.is_empty() {
        out.push(String::new());
    }
    for (key, val) in data.iter() {
        let is_block_map = matches!(key, "controls" | "values" | "device_params" | "devices");
        match val {
            Value::Map(m) if is_block_map => {
                out.push(format!("{key}:"));
                out.extend(m.iter().map(|(k, v)| format!("  {}", flow_entry(k, v))));
            }
            Value::List(sections) if key == "sections" => {
                out.push("sections:".into());
                for s in sections {
                    let Some(s) = s.as_map() else { continue };
                    let title = s.get("title").cloned().unwrap_or(Value::Null);
                    out.push(format!("  - title: {}", flow_scalar(&title)));
                    if let Some(t) = s.get("tolerance") {
                        out.push(format!("    tolerance: {}", t.py_str()));
                    }
                    out.push("    parts:".into());
                    let empty = Map::default();
                    let parts = s.get("parts").and_then(Value::as_map).unwrap_or(&empty);
                    for (name, e) in parts.iter() {
                        match e.as_map() {
                            Some(em) if em.contains("switch") => {
                                let n = flow_entry(name, &Value::Null);
                                out.push(format!("      {}:", n.split(':').next().unwrap_or("")));
                                let sw = em.get("switch").cloned().unwrap_or(Value::Null);
                                out.push(format!("        switch: {}", flow_scalar(&sw)));
                                out.push("        parts:".into());
                                if let Some(ps) = em.get("parts").and_then(Value::as_map) {
                                    out.extend(
                                        ps.iter().map(|(n, p)| {
                                            format!("          {}", flow_entry(n, p))
                                        }),
                                    );
                                }
                            }
                            _ => out.push(format!("      {}", flow_entry(name, e))),
                        }
                    }
                }
            }
            Value::Map(_) | Value::List(_) => out.push(block_entry(key, val)),
            _ => out.push(format!("{key}: {}", flow_scalar(val))),
        }
        out.push(String::new());
    }
    let text = out.join("\n");
    text.trim_end().to_string() + "\n"
}

#[cfg(test)]
mod tests {
    use super::*;

    fn s(x: &str) -> Value {
        Value::Str(x.into())
    }

    #[test]
    fn scalars_as_pyyaml_writes_them() {
        assert_eq!(flow_scalar(&s("in")), "in");
        assert_eq!(flow_scalar(&s("0")), "'0'");
        assert_eq!(flow_scalar(&s("yes")), "'yes'");
        assert_eq!(flow_scalar(&s("1.0")), "'1.0'");
        assert_eq!(flow_scalar(&s("1e-3")), "1e-3");
        assert_eq!(flow_scalar(&s("a, b")), "'a, b'");
        assert_eq!(flow_scalar(&s("it's")), "it's");
        assert_eq!(flow_scalar(&s("'q'")), "'''q'''");
        assert_eq!(flow_scalar(&s("x: y")), "'x: y'");
        assert_eq!(flow_scalar(&s("6973")), "'6973'");
        assert_eq!(flow_scalar(&s("µF")), "\"\\xB5F\"");
        assert_eq!(flow_scalar(&s("")), "''");
        assert_eq!(flow_scalar(&Value::Float(1e-7)), "1.0e-07");
        assert_eq!(flow_scalar(&Value::Float(1e6)), "1000000.0");
        assert_eq!(flow_scalar(&Value::Int(250)), "250");
        assert_eq!(flow_scalar(&Value::Null), "null");
    }

    #[test]
    fn block_and_flow() {
        let probes = Value::List(vec![s("out"), s("g")]);
        assert_eq!(block_entry("probes", &probes), "probes: [out, g]");
        let mut inner = Map::default();
        inner.0.push(("module".into(), s("m")));
        inner.0.push(("values".into(), Value::List(vec![s("a")])));
        assert_eq!(
            block_entry("derived", &Value::Map(inner)),
            "derived:\n  module: m\n  values: [a]"
        );
    }
}
