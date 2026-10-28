//! JSON as Python's `json` module reads and writes it, keys in file order: what the
//! drawing format needs to round-trip a `.drawing.json` byte for byte
//! (`json.dumps(d, indent=1, ensure_ascii=False)`, floats as Python's `repr`, ints as
//! ints). Values are [`crate::yaml::Value`]s, the type circuit data has here.

use crate::Error;
use crate::yaml::{Map, Value, py_float_repr};

/// Parse JSON text (ordered maps; a number with a fraction or exponent is a float).
pub fn parse(text: &str, what: &str) -> Result<Value, Error> {
    let mut p = Parser {
        s: text.as_bytes(),
        i: 0,
        what,
    };
    p.ws();
    let v = p.value()?;
    p.ws();
    if p.i != p.s.len() {
        return Err(p.err("extra data after the value"));
    }
    Ok(v)
}

struct Parser<'a> {
    s: &'a [u8],
    i: usize,
    what: &'a str,
}

impl Parser<'_> {
    fn err(&self, msg: &str) -> Error {
        Error(format!("{}: JSON: {msg} at byte {}", self.what, self.i))
    }

    fn ws(&mut self) {
        while self.i < self.s.len() && matches!(self.s[self.i], b' ' | b'\t' | b'\n' | b'\r') {
            self.i += 1;
        }
    }

    fn eat(&mut self, lit: &str) -> bool {
        if self.s[self.i..].starts_with(lit.as_bytes()) {
            self.i += lit.len();
            true
        } else {
            false
        }
    }

    fn value(&mut self) -> Result<Value, Error> {
        match self.s.get(self.i) {
            None => Err(self.err("unexpected end")),
            Some(b'{') => self.object(),
            Some(b'[') => self.array(),
            Some(b'"') => Ok(Value::Str(self.string()?)),
            Some(b't') if self.eat("true") => Ok(Value::Bool(true)),
            Some(b'f') if self.eat("false") => Ok(Value::Bool(false)),
            Some(b'n') if self.eat("null") => Ok(Value::Null),
            Some(b'N') if self.eat("NaN") => Ok(Value::Float(f64::NAN)),
            Some(b'I') if self.eat("Infinity") => Ok(Value::Float(f64::INFINITY)),
            Some(b'-') if self.eat("-Infinity") => Ok(Value::Float(f64::NEG_INFINITY)),
            Some(_) => self.number(),
        }
    }

    fn object(&mut self) -> Result<Value, Error> {
        self.i += 1;
        let mut m = Vec::new();
        self.ws();
        if self.eat("}") {
            return Ok(Value::Map(Map(m)));
        }
        loop {
            self.ws();
            if self.s.get(self.i) != Some(&b'"') {
                return Err(self.err("expected a key"));
            }
            let k = self.string()?;
            self.ws();
            if !self.eat(":") {
                return Err(self.err("expected ':'"));
            }
            self.ws();
            let v = self.value()?;
            // Python keeps the last of repeated keys, where the first stood.
            match m
                .iter_mut()
                .find(|(key, _): &&mut (String, Value)| *key == k)
            {
                Some(e) => e.1 = v,
                None => m.push((k, v)),
            }
            self.ws();
            if self.eat(",") {
                continue;
            }
            if self.eat("}") {
                return Ok(Value::Map(Map(m)));
            }
            return Err(self.err("expected ',' or '}'"));
        }
    }

    fn array(&mut self) -> Result<Value, Error> {
        self.i += 1;
        let mut v = Vec::new();
        self.ws();
        if self.eat("]") {
            return Ok(Value::List(v));
        }
        loop {
            self.ws();
            v.push(self.value()?);
            self.ws();
            if self.eat(",") {
                continue;
            }
            if self.eat("]") {
                return Ok(Value::List(v));
            }
            return Err(self.err("expected ',' or ']'"));
        }
    }

    fn hex4(&mut self) -> Result<u32, Error> {
        let h = self
            .s
            .get(self.i..self.i + 4)
            .and_then(|b| std::str::from_utf8(b).ok())
            .and_then(|t| u32::from_str_radix(t, 16).ok())
            .ok_or_else(|| self.err("bad \\u escape"))?;
        self.i += 4;
        Ok(h)
    }

    fn string(&mut self) -> Result<String, Error> {
        self.i += 1;
        let mut out = String::new();
        loop {
            let start = self.i;
            while self.i < self.s.len() && !matches!(self.s[self.i], b'"' | b'\\') {
                self.i += 1;
            }
            out.push_str(
                std::str::from_utf8(&self.s[start..self.i]).map_err(|_| self.err("not UTF-8"))?,
            );
            match self.s.get(self.i) {
                None => return Err(self.err("unterminated string")),
                Some(b'"') => {
                    self.i += 1;
                    return Ok(out);
                }
                _ => {}
            }
            self.i += 1;
            let c = *self.s.get(self.i).ok_or_else(|| self.err("bad escape"))?;
            self.i += 1;
            match c {
                b'"' => out.push('"'),
                b'\\' => out.push('\\'),
                b'/' => out.push('/'),
                b'b' => out.push('\u{8}'),
                b'f' => out.push('\u{c}'),
                b'n' => out.push('\n'),
                b'r' => out.push('\r'),
                b't' => out.push('\t'),
                b'u' => {
                    let mut cp = self.hex4()?;
                    if (0xD800..0xDC00).contains(&cp) && self.eat("\\u") {
                        let lo = self.hex4()?;
                        cp = 0x10000 + ((cp - 0xD800) << 10) + (lo - 0xDC00);
                    }
                    out.push(char::from_u32(cp).ok_or_else(|| self.err("bad code point"))?);
                }
                _ => return Err(self.err("bad escape")),
            }
        }
    }

    fn number(&mut self) -> Result<Value, Error> {
        let start = self.i;
        let mut float = false;
        while let Some(&c) = self.s.get(self.i) {
            match c {
                b'0'..=b'9' | b'-' | b'+' => {}
                b'.' | b'e' | b'E' => float = true,
                _ => break,
            }
            self.i += 1;
        }
        let t = std::str::from_utf8(&self.s[start..self.i]).expect("ASCII");
        if t.is_empty() {
            return Err(self.err("unexpected character"));
        }
        if float {
            t.parse()
                .map(Value::Float)
                .map_err(|_| self.err("bad number"))
        } else {
            t.parse()
                .map(Value::Int)
                .map_err(|_| self.err("bad integer"))
        }
    }
}

/// `json.dumps(v, indent=indent, ensure_ascii=False)`.
pub fn dumps(v: &Value, indent: usize) -> String {
    let mut out = String::new();
    write(&mut out, v, indent, 0);
    out
}

fn write(out: &mut String, v: &Value, indent: usize, level: usize) {
    match v {
        Value::Null => out.push_str("null"),
        Value::Bool(b) => out.push_str(if *b { "true" } else { "false" }),
        Value::Int(i) => out.push_str(&i.to_string()),
        Value::Float(x) => out.push_str(&float(*x)),
        Value::Str(s) => string(out, s),
        Value::List(l) if l.is_empty() => out.push_str("[]"),
        Value::Map(m) if m.is_empty() => out.push_str("{}"),
        Value::List(l) => {
            out.push('[');
            for (i, x) in l.iter().enumerate() {
                out.push_str(if i == 0 { "\n" } else { ",\n" });
                pad(out, indent * (level + 1));
                write(out, x, indent, level + 1);
            }
            out.push('\n');
            pad(out, indent * level);
            out.push(']');
        }
        Value::Map(m) => {
            out.push('{');
            for (i, (k, x)) in m.iter().enumerate() {
                out.push_str(if i == 0 { "\n" } else { ",\n" });
                pad(out, indent * (level + 1));
                string(out, k);
                out.push_str(": ");
                write(out, x, indent, level + 1);
            }
            out.push('\n');
            pad(out, indent * level);
            out.push('}');
        }
    }
}

fn pad(out: &mut String, n: usize) {
    out.extend(std::iter::repeat_n(' ', n));
}

/// Python's json float: `repr`, with NaN and Infinity as JavaScript writes them.
fn float(x: f64) -> String {
    if x.is_nan() {
        "NaN".into()
    } else if x.is_infinite() {
        if x > 0.0 { "Infinity" } else { "-Infinity" }.into()
    } else {
        py_float_repr(x)
    }
}

/// A string as `ensure_ascii=False` writes it: only quotes, backslashes and control
/// characters escaped.
fn string(out: &mut String, s: &str) {
    out.push('"');
    for c in s.chars() {
        match c {
            '"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            '\u{8}' => out.push_str("\\b"),
            '\u{c}' => out.push_str("\\f"),
            c if (c as u32) < 0x20 => out.push_str(&format!("\\u{:04x}", c as u32)),
            c => out.push(c),
        }
    }
    out.push('"');
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn round_trip_like_python() {
        let text = "{\n \"a\": [\n  1,\n  2.5,\n  1e-07,\n  \"x\\\"y\\n\u{b5}\"\n ],\n \"b\": {},\n \"c\": [],\n \"d\": null,\n \"e\": true\n}";
        let v = parse(text, "t").unwrap();
        assert_eq!(dumps(&v, 1), text);
        let Value::Map(m) = &v else { panic!() };
        assert_eq!(m.keys().collect::<Vec<_>>(), ["a", "b", "c", "d", "e"]);
        assert_eq!(m.get("a").unwrap().as_list().unwrap()[0], Value::Int(1));
    }

    #[test]
    fn floats_as_python_repr() {
        for (x, s) in [
            (1e-7, "1e-07"),
            (40.64, "40.64"),
            (1e16, "1e+16"),
            (2.0, "2.0"),
        ] {
            assert_eq!(float(x), s);
        }
    }
}
