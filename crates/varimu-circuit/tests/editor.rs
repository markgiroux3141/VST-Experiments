//! The editor's compile path against Python's (the reference): every drawn circuit and
//! the broken copies in tests/fixtures/editor (scripts/export_editor_fixtures.py), step
//! by step: the connectivity, the compiled circuit's content and file text, the IR it
//! builds (numbers bit for bit), the pre-flight markers; and the symbol table.

use std::path::{Path, PathBuf};

use serde_json::Value as Json;
use varimu_circuit::compile::{check_drawing, circuit_text, compiled_spec};
use varimu_circuit::connect::connect;
use varimu_circuit::drawing::Drawing;
use varimu_circuit::spec::resolve;
use varimu_circuit::{Cores, Library, build_ir, json, symbols};

fn repo() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("../..")
}

fn fixtures() -> Vec<PathBuf> {
    let dir = Path::new(env!("CARGO_MANIFEST_DIR")).join("tests/fixtures/editor");
    let mut v: Vec<PathBuf> = std::fs::read_dir(dir)
        .unwrap()
        .map(|e| e.unwrap().path())
        .filter(|p| p.file_name().unwrap() != "symbols.json")
        .collect();
    v.sort();
    v
}

/// Values equal, numbers bit for bit; differences listed with their paths.
fn compare(path: &str, want: &Json, got: &Json, errors: &mut Vec<String>) {
    match (want, got) {
        (Json::Number(w), Json::Number(g)) => {
            let (wf, gf) = (w.as_f64().unwrap(), g.as_f64().unwrap());
            if wf.to_bits() != gf.to_bits() || w.is_i64() != g.is_i64() {
                errors.push(format!("{path}: python {w}, rust {g}"));
            }
        }
        (Json::Object(w), Json::Object(g)) => {
            let (wk, gk): (Vec<_>, Vec<_>) = (w.keys().collect(), g.keys().collect());
            let (mut ws, mut gs) = (wk.clone(), gk.clone());
            ws.sort();
            gs.sort();
            if ws != gs {
                errors.push(format!("{path}: keys {wk:?} vs {gk:?}"));
                return;
            }
            for k in wk {
                compare(&format!("{path}.{k}"), &w[k], &g[k], errors);
            }
        }
        (Json::Array(w), Json::Array(g)) => {
            if w.len() != g.len() {
                errors.push(format!("{path}: {} items vs {}", w.len(), g.len()));
                return;
            }
            for (i, (a, b)) in w.iter().zip(g).enumerate() {
                compare(&format!("{path}[{i}]"), a, b, errors);
            }
        }
        _ if want != got => errors.push(format!("{path}: python {want}, rust {got}")),
        _ => {}
    }
}

/// A yaml/json Value as serde_json, keys in order (for comparing with the fixture).
fn to_json(v: &varimu_circuit::yaml::Value) -> Json {
    serde_json::from_str(&json::dumps(v, 0)).unwrap()
}

#[test]
fn compile_path_equals_python() {
    let lib = Library::new(repo().join("config"));
    let mut errors = Vec::new();
    let files = fixtures();
    assert!(files.len() >= 7, "{files:?}");
    for f in files {
        let name = f.file_stem().unwrap().to_string_lossy().into_owned();
        let text = std::fs::read_to_string(&f).unwrap();
        let fx: Json = serde_json::from_str(&text).unwrap();
        // The drawing, read with the order-keeping reader.
        let raw = json::parse(&text, &name).unwrap();
        let drawing = raw.as_map().unwrap().get("drawing").unwrap();
        let d = Drawing::from_json(drawing).unwrap();
        let e = &mut errors;

        let conn = connect(&d);
        let nets: Vec<Json> = conn
            .nets
            .iter()
            .map(|n| {
                serde_json::json!({
                    "name": n.name, "node": n.node,
                    "pins": n.pins.iter().map(|p| serde_json::json!([p.reference, p.unit, p.number])).collect::<Vec<_>>(),
                    "wires": n.wires, "labels": n.labels, "grounds": n.grounds,
                })
            })
            .collect();
        compare(&format!("{name}.nets"), &fx["nets"], &Json::Array(nets), e);
        compare(
            &format!("{name}.errors"),
            &fx["errors"],
            &serde_json::json!(conn.errors),
            e,
        );
        compare(
            &format!("{name}.warnings"),
            &fx["warnings"],
            &serde_json::json!(conn.warnings),
            e,
        );
        let mut junctions = conn.junctions.clone();
        junctions.sort_by(|a, b| a.partial_cmp(b).unwrap());
        let mut loose = conn.loose.clone();
        loose.sort_by(|a, b| a.partial_cmp(b).unwrap());
        let pts = |v: &[(f64, f64)]| {
            serde_json::json!(v.iter().map(|(x, y)| [*x, *y]).collect::<Vec<_>>())
        };
        compare(
            &format!("{name}.junctions"),
            &fx["junctions"],
            &pts(&junctions),
            e,
        );
        compare(&format!("{name}.loose"), &fx["loose"], &pts(&loose), e);

        let (c, markers) = check_drawing(&d, &lib);
        compare(
            &format!("{name}.compile_errors"),
            &fx["compile_errors"],
            &serde_json::json!(c.errors),
            e,
        );
        compare(
            &format!("{name}.problems"),
            &fx["problems"],
            &serde_json::json!(c.problems),
            e,
        );
        let ms: Vec<Json> = markers
            .iter()
            .map(|m| {
                serde_json::json!({"check": m.check, "message": m.message, "config": m.config,
                                   "nets": m.nets, "symbols": m.symbols})
            })
            .collect();
        compare(
            &format!("{name}.markers"),
            &fx["markers"],
            &Json::Array(ms),
            e,
        );

        match (&fx.get("data"), &c.data) {
            (Some(want), Some(data)) => {
                let got = to_json(&varimu_circuit::yaml::Value::Map(data.clone()));
                compare(&format!("{name}.data"), want, &got, e);
                let t = circuit_text(&c, "a fixture").unwrap();
                if t != fx["text"].as_str().unwrap() {
                    let want = fx["text"].as_str().unwrap();
                    let line = want
                        .lines()
                        .zip(t.lines())
                        .position(|(a, b)| a != b)
                        .unwrap_or(0);
                    e.push(format!(
                        "{name}.text: line {}: python {:?}, rust {:?}",
                        line + 1,
                        want.lines().nth(line),
                        t.lines().nth(line)
                    ));
                }
                let spec = compiled_spec(&c).unwrap();
                let p = resolve(&spec, &[]).unwrap();
                let ir = build_ir(&lib, &spec, &p, Cores::Ja).unwrap();
                let ir = serde_json::to_value(&ir).unwrap();
                compare(&format!("{name}.ir"), &fx["ir"], &ir, e);
            }
            (None, None) => {}
            (w, g) => e.push(format!(
                "{name}: python compiled {}, rust {}",
                w.is_some(),
                g.is_some()
            )),
        }
    }
    let shown: Vec<&String> = errors.iter().take(40).collect();
    assert!(
        errors.is_empty(),
        "{} differences:\n{shown:#?}",
        errors.len()
    );
}

#[test]
fn symbol_table_equals_python() {
    let path = Path::new(env!("CARGO_MANIFEST_DIR")).join("tests/fixtures/editor/symbols.json");
    let fx: Json = serde_json::from_str(&std::fs::read_to_string(path).unwrap()).unwrap();
    let fx = fx.as_object().unwrap();
    // The fixture's key order is lost (serde_json sorts keys): compare the names as sets.
    let mut names: Vec<&str> = symbols::all().iter().map(|s| s.name.as_str()).collect();
    let mut want: Vec<&str> = fx.keys().map(String::as_str).collect();
    names.sort_unstable();
    want.sort_unstable();
    assert_eq!(names, want);
    let mut errors = Vec::new();
    for s in symbols::all() {
        let w = &fx[&s.name];
        let units: Vec<Json> = s
            .units
            .iter()
            .map(|pins| {
                Json::Array(
                    pins.iter()
                        .map(|p| {
                            let into = match p.angle {
                                0 => [1, 0],
                                90 => [0, -1],
                                180 => [-1, 0],
                                _ => [0, 1],
                            };
                            serde_json::json!({"number": p.number, "name": p.name, "x": p.x,
                                               "y": -p.y, "length": p.length, "into": into})
                        })
                        .collect(),
                )
            })
            .collect();
        let got = serde_json::json!({
            "name": s.name, "kind": s.kind.name(), "prefix": s.prefix,
            "description": s.description, "macro": s.macro_, "primary": s.primary,
            "fields": s.fields, "value": s.value, "units": units,
            "text": {"ref": [s.text.0, -s.text.1], "value": [s.text.0, -s.text.2],
                     "justify": s.text.3},
        });
        let mut want = w.clone();
        let o = want.as_object_mut().unwrap();
        o.remove("graphics");
        o.remove("box");
        compare(&s.name, &want, &got, &mut errors);
    }
    // The table's coordinates are numbers to Python (0 and 0.0 alike): equal by value.
    errors.retain(|e| {
        let Some((_, rest)) = e.split_once(": python ") else {
            return true;
        };
        let Some((w, g)) = rest.split_once(", rust ") else {
            return true;
        };
        !matches!((w.parse::<f64>(), g.parse::<f64>()), (Ok(a), Ok(b)) if a == b)
    });
    assert!(errors.is_empty(), "{errors:#?}");
}
