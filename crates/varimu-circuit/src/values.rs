//! Engineering numbers and natural order, as `varimu/kicad/values.py` and the importer's
//! `natural` have them.
//!
//! A number is a decimal with an optional exponent and an optional SI prefix (p n u µ m
//! k M G), or the "4k7" form (R for no prefix: "4R7"), then an optional unit (ohm, Ω,
//! F, H, V, A, Hz), which is ignored. The decimal is scaled exactly and rounded to a
//! float once (Python scales a `Decimal`; Rust's float parsing rounds correctly), so
//! "40u", "40e-6" and "0.04m" are all the float "40.0e-6" is. A plain integer ("470")
//! is an int, as YAML would read it.

use std::cmp::Ordering;

use crate::yaml::Value;

fn prefix_exp(c: char) -> Option<i32> {
    Some(match c {
        'p' => -12,
        'n' => -9,
        'u' | 'µ' => -6,
        'm' => -3,
        'k' => 3,
        'M' => 6,
        'G' => 9,
        _ => return None,
    })
}

/// The optional unit after a number (`(?:ohms?|Ω|F|H|V|A|Hz)?`).
fn unit_only(s: &str) -> bool {
    matches!(s, "" | "ohm" | "ohms" | "Ω" | "F" | "H" | "V" | "A" | "Hz")
}

fn skip_ws(s: &str) -> &str {
    s.trim_start_matches(char::is_whitespace)
}

/// The number `text` writes, or None when it isn't one (then it is a key).
pub fn parse_eng(text: &str) -> Option<Value> {
    let s = text.trim();
    plain(s).or_else(|| embedded(s))
}

/// `[-+]?(\d+\.?\d*|\.\d+)([eE][-+]?\d+)?\s*[prefix]?\s*unit?`
fn plain(s: &str) -> Option<Value> {
    let b = s.as_bytes();
    let mut i = 0;
    if i < b.len() && (b[i] == b'-' || b[i] == b'+') {
        i += 1;
    }
    let digits = |i: &mut usize| {
        let st = *i;
        while *i < b.len() && b[*i].is_ascii_digit() {
            *i += 1;
        }
        *i - st
    };
    let int_digits = digits(&mut i);
    let mut has_dot = false;
    if int_digits > 0 {
        if i < b.len() && b[i] == b'.' {
            has_dot = true;
            i += 1;
            digits(&mut i);
        }
    } else {
        if !(i < b.len() && b[i] == b'.') {
            return None;
        }
        has_dot = true;
        i += 1;
        if digits(&mut i) == 0 {
            return None;
        }
    }
    let mant = &s[..i];
    let mut exp: i32 = 0;
    let mut has_exp = false;
    if i < b.len() && (b[i] == b'e' || b[i] == b'E') {
        let mut j = i + 1;
        if j < b.len() && (b[j] == b'-' || b[j] == b'+') {
            j += 1;
        }
        let st = j;
        while j < b.len() && b[j].is_ascii_digit() {
            j += 1;
        }
        if j > st {
            exp = s[i + 1..j].parse().ok()?;
            has_exp = true;
            i = j;
        }
    }
    let rest = skip_ws(&s[i..]);
    let (prefix, rest) = match rest.chars().next().and_then(prefix_exp) {
        Some(p) => {
            let c = rest.chars().next().expect("a prefix");
            (Some(p), &rest[c.len_utf8()..])
        }
        None => (None, rest),
    };
    if !unit_only(skip_ws(rest)) {
        return None;
    }
    if !has_dot && !has_exp && prefix.is_none() {
        return mant.parse().ok().map(Value::Int);
    }
    let total = exp + prefix.unwrap_or(0);
    format!("{mant}e{total}").parse().ok().map(Value::Float)
}

/// `(\d+)([pnuµmkMGR])(\d+)\s*unit?`: "4k7" is 4.7e3, "4R7" 4.7.
fn embedded(s: &str) -> Option<Value> {
    let whole_end = s.find(|c: char| !c.is_ascii_digit())?;
    if whole_end == 0 {
        return None;
    }
    let c = s[whole_end..].chars().next()?;
    let p = if c == 'R' { 0 } else { prefix_exp(c)? };
    let after = &s[whole_end + c.len_utf8()..];
    let frac_end = after
        .find(|c: char| !c.is_ascii_digit())
        .unwrap_or(after.len());
    if frac_end == 0 || !unit_only(skip_ws(&after[frac_end..])) {
        return None;
    }
    format!("{}.{}e{p}", &s[..whole_end], &after[..frac_end])
        .parse()
        .ok()
        .map(Value::Float)
}

/// Python's `natural` key (`re.split(r"(\d+)", s)`, digit runs as ints), compared.
pub fn natural_cmp(a: &str, b: &str) -> Ordering {
    let (pa, pb) = (natural_parts(a), natural_parts(b));
    for (x, y) in pa.iter().zip(&pb) {
        let o = match (x, y) {
            (Part::Text(x), Part::Text(y)) => x.cmp(y),
            (Part::Num(x), Part::Num(y)) => {
                let (x, y) = (x.trim_start_matches('0'), y.trim_start_matches('0'));
                x.len().cmp(&y.len()).then_with(|| x.cmp(y))
            }
            // Positions alternate text, number, text: never mixed.
            (Part::Text(_), Part::Num(_)) => Ordering::Less,
            (Part::Num(_), Part::Text(_)) => Ordering::Greater,
        };
        if o != Ordering::Equal {
            return o;
        }
    }
    pa.len().cmp(&pb.len())
}

enum Part<'a> {
    Text(&'a str),
    Num(&'a str),
}

fn natural_parts(s: &str) -> Vec<Part<'_>> {
    let mut out = Vec::new();
    let mut start = 0;
    let mut in_digits = false;
    for (i, c) in s.char_indices() {
        let d = c.is_ascii_digit();
        if d != in_digits {
            let piece = &s[start..i];
            out.push(if in_digits {
                Part::Num(piece)
            } else {
                Part::Text(piece)
            });
            start = i;
            in_digits = d;
        }
    }
    let piece = &s[start..];
    out.push(if in_digits {
        Part::Num(piece)
    } else {
        Part::Text(piece)
    });
    // re.split puts an empty string after a trailing number.
    if in_digits {
        out.push(Part::Text(""));
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn engineering_numbers() {
        assert_eq!(parse_eng("470"), Some(Value::Int(470)));
        assert_eq!(parse_eng("40u"), Some(Value::Float(40e-6)));
        assert_eq!(parse_eng("0.04m"), Some(Value::Float(40e-6)));
        assert_eq!(parse_eng("4k7"), Some(Value::Float(4700.0)));
        assert_eq!(parse_eng("4R7"), Some(Value::Float(4.7)));
        assert_eq!(parse_eng("100n"), Some(Value::Float(1e-7)));
        assert_eq!(parse_eng("1M"), Some(Value::Float(1e6)));
        assert_eq!(parse_eng("2.2µF"), Some(Value::Float(2.2e-6)));
        assert_eq!(parse_eng("10 kohm"), Some(Value::Float(1e4)));
        assert_eq!(parse_eng("250"), Some(Value::Int(250)));
        assert_eq!(parse_eng("12AX7"), None);
        assert_eq!(parse_eng("r111_ohm"), None);
        assert_eq!(parse_eng("1e3"), Some(Value::Float(1000.0)));
    }

    #[test]
    fn natural_order() {
        let mut v = vec!["R10", "R9", "R101", "C2", "R9A", "R9"];
        v.sort_by(|a, b| natural_cmp(a, b));
        assert_eq!(v, ["C2", "R9", "R9", "R9A", "R10", "R101"]);
    }
}
