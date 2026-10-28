//! The resampler against scipy's `resample_poly` (the reference), bit for bit: the
//! filters it designs and its outputs on seeded inputs, every ratio and padding the
//! project uses (scripts/export_audio_fixtures.py writes the fixture).

use std::path::Path;

use serde_json::Value;
use varimu_app::resample::{Pad, firwin_kaiser, resample_poly};

fn fixture() -> Value {
    let path = Path::new(env!("CARGO_MANIFEST_DIR")).join("tests/fixtures/resample.json");
    serde_json::from_str(&std::fs::read_to_string(path).unwrap()).unwrap()
}

fn floats(v: &Value) -> Vec<f64> {
    v.as_array()
        .unwrap()
        .iter()
        .map(|x| x.as_f64().unwrap())
        .collect()
}

/// Differences between two vectors: (count, worst relative), or a length mismatch.
fn diff(want: &[f64], got: &[f64]) -> Result<(usize, f64), String> {
    if want.len() != got.len() {
        return Err(format!("length {} vs {}", want.len(), got.len()));
    }
    let mut n = 0;
    let mut worst = 0.0f64;
    for (w, g) in want.iter().zip(got) {
        if w.to_bits() != g.to_bits() {
            n += 1;
            worst = worst.max(((g - w) / w).abs());
        }
    }
    Ok((n, worst))
}

#[test]
fn filters_equal_scipy() {
    let f = fixture();
    let mut errors = Vec::new();
    for t in f["taps"].as_array().unwrap() {
        let m = t["max_rate"].as_u64().unwrap() as usize;
        let got = firwin_kaiser(2 * 10 * m + 1, 1.0 / m as f64, 5.0);
        match diff(&floats(&t["h"]), &got) {
            Ok((0, _)) => {}
            Ok((n, w)) => errors.push(format!("max_rate {m}: {n} taps differ (worst rel {w:.1e})")),
            Err(e) => errors.push(format!("max_rate {m}: {e}")),
        }
    }
    assert!(errors.is_empty(), "{}", errors.join("\n"));
}

#[test]
fn outputs_equal_scipy() {
    let f = fixture();
    let mut errors = Vec::new();
    let cases = f["cases"].as_array().unwrap();
    for c in cases {
        let (up, down) = (
            c["up"].as_u64().unwrap() as usize,
            c["down"].as_u64().unwrap() as usize,
        );
        let pad = match c["pad"].as_str().unwrap() {
            "constant" => Pad::Zero,
            "edge" => Pad::Edge,
            p => panic!("padtype {p}"),
        };
        let x = floats(&c["x"]);
        let got = resample_poly(&x, up, down, pad);
        let label = format!("{up}/{down} {pad:?} n={}", x.len());
        match diff(&floats(&c["y"]), &got) {
            Ok((0, _)) => {}
            Ok((n, w)) => errors.push(format!("{label}: {n} samples differ (worst rel {w:.1e})")),
            Err(e) => errors.push(format!("{label}: {e}")),
        }
    }
    assert!(cases.len() >= 16, "the fixture has {} cases", cases.len());
    assert!(errors.is_empty(), "{}", errors.join("\n"));
}
