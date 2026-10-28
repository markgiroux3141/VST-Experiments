//! Engineering numbers as the editor shows and steps them (`varimu/listen/editor/eng.js`
//! and `edits.js`'s `engText`): "200 kΩ", E12 / E24 stepping, units implied by keys.
//! Reading a number is `varimu_circuit::values::parse_eng` (Python's reader).

use varimu_circuit::values::parse_eng;
use varimu_circuit::yaml::Value;

/// The number `text` writes, or None when it isn't one (then it is a key).
pub fn parse_num(text: &str) -> Option<f64> {
    parse_eng(text).and_then(|v| v.as_f64())
}

/// JavaScript's `Math.round`: halves round up.
pub fn js_round(x: f64) -> f64 {
    let r = x.floor();
    if x - r >= 0.5 { r + 1.0 } else { r }
}

/// JavaScript's `String(x)` for a number: the shortest round trip, an exponent outside
/// 1e-6 .. 1e21.
pub fn js_str(x: f64) -> String {
    if !x.is_finite() {
        return if x.is_nan() {
            "NaN".into()
        } else if x > 0.0 {
            "Infinity".into()
        } else {
            "-Infinity".into()
        };
    }
    let a = x.abs();
    if a != 0.0 && !(1e-6..1e21).contains(&a) {
        // Rust's `{:e}` is the shortest round trip too: "1.5e-7"; JS writes "1.5e-7"
        // and "1e+21".
        let s = format!("{x:e}");
        return match s.split_once('e') {
            Some((m, e)) if !e.starts_with('-') => format!("{m}e+{e}"),
            _ => s,
        };
    }
    if x == 0.0 {
        return "0".into();
    }
    format!("{x}")
}

/// `+x.toPrecision(p)`: `x` rounded to `p` significant digits.
pub fn to_precision(x: f64, p: usize) -> f64 {
    if x == 0.0 || !x.is_finite() {
        return x;
    }
    format!("{:.*e}", p - 1, x).parse().unwrap_or(x)
}

const PREFIXES: [(f64, &str); 8] = [
    (1e9, "G"),
    (1e6, "M"),
    (1e3, "k"),
    (1.0, ""),
    (1e-3, "m"),
    (1e-6, "u"),
    (1e-9, "n"),
    (1e-12, "p"),
];

/// The value text a symbol shows for a number: what `varimu.kicad.values` reads exactly
/// (`edits.js`'s `engText`). An integer below 1000 stays an integer.
pub fn eng_text(x: f64) -> String {
    if x.fract() == 0.0 && x.abs() < 1000.0 {
        return js_str(x);
    }
    let a = x.abs();
    let Some(&(scale, p)) = PREFIXES.iter().find(|(s, _)| a >= s * 0.9995) else {
        return js_str(x);
    };
    let mut m = js_str(to_precision(x / scale, 12));
    if p.is_empty() && !m.contains('.') && !m.contains('e') {
        m.push_str(".0");
    }
    m + p
}

/// A parameter value's text (`String(v)` of a JSON value): numbers as JavaScript writes
/// them, strings as they are.
pub fn value_text(v: &Value) -> String {
    match v {
        Value::Int(i) => i.to_string(),
        Value::Float(x) => js_str(*x),
        other => other.py_str(),
    }
}

/// A number as JSON carries it from the page to Python: an int when whole.
pub fn number_value(x: f64) -> Value {
    if x.fract() == 0.0 && x.abs() < 1e21 {
        Value::Int(x as i64)
    } else {
        Value::Float(x)
    }
}

const SI: [(f64, &str); 8] = [
    (1e9, "G"),
    (1e6, "M"),
    (1e3, "k"),
    (1.0, ""),
    (1e-3, "m"),
    (1e-6, "µ"),
    (1e-9, "n"),
    (1e-12, "p"),
];

/// 200000, "Ω" -> "200 kΩ"; 2.5e-7, "F" -> "250 nF". Plain for unitless or odd values.
pub fn with_unit(x: f64, unit: &str) -> String {
    if !x.is_finite() {
        return js_str(x);
    }
    if unit.is_empty() {
        return trim(x);
    }
    if unit == "%" {
        return format!("{} %", trim(x));
    }
    if unit.contains(['²', '³']) {
        return format!("{} {unit}", trim(x));
    }
    if x == 0.0 {
        return format!("0 {unit}");
    }
    let a = x.abs();
    let (scale, p) = SI
        .iter()
        .find(|(s, _)| a >= s * 0.9995)
        .copied()
        .unwrap_or(SI[SI.len() - 1]);
    format!("{} {p}{unit}", trim(x / scale))
}

/// A number's short form: an integer as it is, 4 significant digits, an exponent for
/// the very large and small.
pub fn trim(x: f64) -> String {
    let a = x.abs();
    if x.fract() == 0.0 && a < 1e6 {
        return js_str(x);
    }
    if a != 0.0 && !(1e-3..1e6).contains(&a) {
        // toExponential(3) without trailing zeros: 1.500e-4 -> 1.5e-4, 2.000e6 -> 2e+6.
        let s = format!("{x:.3e}");
        let (m, e) = s.split_once('e').unwrap_or((&s, "0"));
        let m = if m.contains('.') {
            m.trim_end_matches('0').trim_end_matches('.')
        } else {
            m
        };
        let e = if e.starts_with('-') {
            e.to_string()
        } else {
            format!("+{e}")
        };
        return format!("{m}e{e}");
    }
    js_str(to_precision(x, 4))
}

/// The unit a parameter key or a macro param implies (CLAUDE.md: units in names).
pub fn unit_of(key: Option<&str>, primary: Option<&str>) -> &'static str {
    let k = key.unwrap_or("");
    const BY_SUFFIX: [(&str, &str); 11] = [
        ("_ohm", "Ω"),
        ("_f", "F"),
        ("_h", "H"),
        ("_v", "V"),
        ("_hz", "Hz"),
        ("_a", "A"),
        ("_m2", "m²"),
        ("_m", "m"),
        ("_s", "s"),
        ("_pct", "%"),
        ("_db", "dB"),
    ];
    for (s, u) in BY_SUFFIX {
        if k.ends_with(s) {
            return u;
        }
    }
    match primary.unwrap_or("") {
        "r" | "z" => "Ω",
        "c" => "F",
        "l" => "H",
        "v" | "amplitude_v" | "v_rms" | "operating_v" => "V",
        _ => "",
    }
}

const E12: [f64; 12] = [1.0, 1.2, 1.5, 1.8, 2.2, 2.7, 3.3, 3.9, 4.7, 5.6, 6.8, 8.2];
const E24: [f64; 24] = [
    1.0, 1.1, 1.2, 1.3, 1.5, 1.6, 1.8, 2.0, 2.2, 2.4, 2.7, 3.0, 3.3, 3.6, 3.9, 4.3, 4.7, 5.1, 5.6,
    6.2, 6.8, 7.5, 8.2, 9.1,
];

/// The next standard value above (`dir` 1) or below (-1) `x` in the E12 (or E24)
/// series: how a part's value is stepped by ear.
pub fn step_e(x: f64, dir: i32, series: u32) -> f64 {
    if x.is_nan() || x <= 0.0 {
        return x;
    }
    let s: &[f64] = if series == 24 { &E24 } else { &E12 };
    let dec = (x.log10() + 1e-9).floor();
    let m = x / 10f64.powf(dec);
    let all: Vec<f64> = s
        .iter()
        .map(|v| v / 10.0)
        .chain(s.iter().copied())
        .chain(s.iter().map(|v| v * 10.0))
        .collect();
    let cand = if dir > 0 {
        all.iter().copied().find(|&v| v > m * (1.0 + 1e-6))
    } else {
        all.iter().rev().copied().find(|&v| v < m * (1.0 - 1e-6))
    };
    let Some(cand) = cand else { return x };
    format!("{}e{}", js_str(to_precision(cand, 3)), dec as i64)
        .parse()
        .unwrap_or(x)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn engineering_numbers_read_as_python_reads_them() {
        assert_eq!(parse_num("0.47u"), Some(4.7e-7));
        assert_eq!(parse_num("470n"), Some(4.7e-7));
        assert_eq!(parse_num("4k7"), Some(4700.0));
        assert_eq!(parse_num("40uF"), Some(40e-6));
        assert_eq!(parse_num("1.0e+9"), Some(1e9));
        assert_eq!(parse_num("load_ohm"), None);
        for x in [
            4.7e-7, 0.25e-6, 33e-3, 600.0, 2554.0, 1.5e-6, 10e-12, 117.0, 0.0,
        ] {
            assert_eq!(parse_num(&eng_text(x)), Some(x), "{}", eng_text(x));
        }
        assert_eq!(eng_text(250e-9), "250n");
        assert_eq!(eng_text(1e-6), "1u");
        assert_eq!(eng_text(1.5e3), "1.5k");
        assert_eq!(with_unit(200000.0, "Ω"), "200 kΩ");
        assert_eq!(with_unit(2.5e-7, "F"), "250 nF");
        assert_eq!(unit_of(Some("c_couple_f"), None), "F");
        assert_eq!(unit_of(None, Some("r")), "Ω");
    }

    #[test]
    fn stepping_a_value_through_the_e12_and_e24_series() {
        assert_eq!(step_e(250e-9, 1, 12), 270e-9);
        assert_eq!(step_e(250e-9, -1, 12), 220e-9);
        assert_eq!(step_e(100e3, 1, 12), 120e3);
        assert_eq!(step_e(100e3, -1, 12), 82e3);
        assert_eq!(step_e(8.2, 1, 12), 10.0);
        assert_eq!(step_e(1.5e3, 1, 24), 1.6e3);
        assert_eq!(step_e(470e3, -1, 12), 390e3);
    }

    #[test]
    fn numbers_as_javascript_writes_them() {
        assert_eq!(js_str(600.0), "600");
        assert_eq!(js_str(0.82), "0.82");
        assert_eq!(js_str(1.5e-7), "1.5e-7");
        assert_eq!(js_str(1e21), "1e+21");
        assert_eq!(trim(1.5e-4), "1.5e-4");
        assert_eq!(trim(0.123456), "0.1235");
    }
}
