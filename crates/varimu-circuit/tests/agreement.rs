//! The Rust builder against Python's (the reference): every case of every circuit in
//! tests/fixtures (scripts/export_app_fixtures.py), the IR compared value by value.
//! Strings and structure must be equal, and numbers bit for bit: stricter than R1's
//! 1e-15 (NATIVE_APP_PLAN.md), because R2's renders are to equal Python's bit for bit,
//! which needs the same IR. Differences are reported with their relative size.

use std::path::{Path, PathBuf};

use serde_json::Value as Json;
use varimu_circuit::yaml::Value;
use varimu_circuit::{Cores, Heaters, Library, Noise, build_ir_with, spec};

fn repo() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("../..")
}

fn to_value(j: &Json) -> Value {
    match j {
        Json::Null => Value::Null,
        Json::Bool(b) => Value::Bool(*b),
        Json::Number(n) => match n.as_i64() {
            Some(i) => Value::Int(i),
            None => Value::Float(n.as_f64().unwrap()),
        },
        Json::String(s) => Value::Str(s.clone()),
        _ => panic!("override {j} isn't a scalar"),
    }
}

#[derive(Default)]
struct Tally {
    numbers: usize,
    inexact: usize,
    worst: f64,
}

fn compare(path: &str, want: &Json, got: &Json, t: &mut Tally, errors: &mut Vec<String>) {
    match (want, got) {
        (Json::Number(w), Json::Number(g)) => {
            let (w, g) = (w.as_f64().unwrap(), g.as_f64().unwrap());
            t.numbers += 1;
            if w.to_bits() != g.to_bits() {
                t.inexact += 1;
                let rel = if w == 0.0 {
                    g.abs()
                } else {
                    ((g - w) / w).abs()
                };
                t.worst = t.worst.max(rel);
                errors.push(format!("{path}: python {w:e}, rust {g:e} (rel {rel:.1e})"));
            }
        }
        (Json::Object(w), Json::Object(g)) => {
            let (mut wk, mut gk): (Vec<_>, Vec<_>) = (w.keys().collect(), g.keys().collect());
            wk.sort();
            gk.sort();
            if wk != gk {
                errors.push(format!("{path}: fields {wk:?} vs {gk:?}"));
                return;
            }
            for k in wk {
                let label = match w[k].get("name").and_then(Json::as_str) {
                    Some(n) => format!("{path}.{k}[{n}]"),
                    None => format!("{path}.{k}"),
                };
                compare(&label, &w[k], &g[k], t, errors);
            }
        }
        (Json::Array(w), Json::Array(g)) => {
            if w.len() != g.len() {
                let names = |a: &[Json]| -> Vec<String> {
                    a.iter()
                        .map(|x| {
                            x.get("name")
                                .and_then(Json::as_str)
                                .unwrap_or("?")
                                .to_string()
                        })
                        .collect()
                };
                errors.push(format!(
                    "{path}: {} items vs {} (python {:?}, rust {:?})",
                    w.len(),
                    g.len(),
                    names(w),
                    names(g)
                ));
                return;
            }
            for (i, (a, b)) in w.iter().zip(g).enumerate() {
                let label = match a.get("name").and_then(Json::as_str) {
                    Some(n) => format!("{path}[{n}]"),
                    None => format!("{path}[{i}]"),
                };
                compare(&label, a, b, t, errors);
            }
        }
        _ if want == got => {}
        _ => errors.push(format!("{path}: python {want}, rust {got}")),
    }
}

#[test]
fn rust_builds_the_ir_python_builds() {
    let lib = Library::new(repo().join("config"));
    let dir = Path::new(env!("CARGO_MANIFEST_DIR")).join("tests/fixtures");
    let mut files: Vec<_> = std::fs::read_dir(&dir)
        .unwrap()
        .map(|e| e.unwrap().path())
        .filter(|p| p.extension().is_some_and(|e| e == "json"))
        .collect();
    files.sort();
    assert!(
        files.len() >= 6,
        "fixtures missing: scripts/export_app_fixtures.py"
    );
    let mut errors = Vec::new();
    let mut total = Tally::default();
    let mut cases = 0;
    for file in &files {
        let fx: Json = serde_json::from_str(&std::fs::read_to_string(file).unwrap()).unwrap();
        let name = fx["circuit"].as_str().unwrap();
        let c = spec::load_circuit(&spec::circuit_path(lib.config_dir(), name).unwrap())
            .unwrap_or_else(|e| panic!("{e}"));
        let mut all = vec![
            serde_json::json!({"name": "default", "overrides": {}, "cores": "ja", "sections": {}}),
        ];
        all.extend(fx["cases"].as_array().unwrap().iter().cloned());
        let mut t = Tally::default();
        for case in &all {
            let label = format!("{name}/{}", case["name"].as_str().unwrap());
            let overrides: Vec<(String, Value)> = case["overrides"]
                .as_object()
                .unwrap()
                .iter()
                .map(|(k, v)| (k.clone(), to_value(v)))
                .collect();
            let cores = Cores::parse(case["cores"].as_str().unwrap()).unwrap();
            let noise = match case.get("noise") {
                None => Noise::File,
                Some(Json::Bool(false)) => Noise::Off,
                Some(Json::Bool(true)) => Noise::On,
                Some(n) => Noise::Seed(n.as_u64().expect("a seed")),
            };
            let heaters = match case.get("heaters").and_then(Json::as_str) {
                None => Heaters::File,
                Some("cold") => Heaters::Cold,
                Some(_) => Heaters::Warm,
            };
            let built = spec::resolve(&c, &overrides)
                .and_then(|p| build_ir_with(&lib, &c, &p, cores, noise, heaters));
            let ir = match built {
                Ok(ir) => ir,
                Err(e) => {
                    errors.push(format!("{label}: {e}"));
                    continue;
                }
            };
            let mut want = fx["default"].clone();
            for (i, s) in case["sections"].as_object().unwrap() {
                want["sections"][i.parse::<usize>().unwrap()] = s.clone();
            }
            if let Some(m) = case.get("models") {
                want["models"] = m.clone();
            }
            match case.get("heaters_block") {
                Some(Json::Null) => {
                    want.as_object_mut().unwrap().remove("heaters");
                }
                Some(b) => want["heaters"] = b.clone(),
                None => {}
            }
            match case.get("noise_block") {
                Some(Json::Null) => {
                    want.as_object_mut().unwrap().remove("noise");
                }
                Some(b) => want["noise"] = b.clone(),
                None => {}
            }
            let got = serde_json::to_value(&ir).unwrap();
            compare(&label, &want, &got, &mut t, &mut errors);
            cases += 1;
        }
        println!(
            "{name}: {} cases, {} numbers, {} not bit for bit (worst rel {:.1e})",
            all.len(),
            t.numbers,
            t.inexact,
            t.worst
        );
        total.numbers += t.numbers;
        total.inexact += t.inexact;
        total.worst = total.worst.max(t.worst);
    }
    println!(
        "all: {cases} cases, {} numbers, {} not bit for bit (worst rel {:.1e})",
        total.numbers, total.inexact, total.worst
    );
    let shown: Vec<_> = errors.iter().take(40).collect();
    assert!(
        errors.is_empty(),
        "{} disagreements:\n{}",
        errors.len(),
        shown
            .iter()
            .map(|s| s.as_str())
            .collect::<Vec<_>>()
            .join("\n")
    );
}
