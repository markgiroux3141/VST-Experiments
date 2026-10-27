//! What the builder refuses, with messages that say why.

use std::path::Path;

use varimu_circuit::yaml::Value;
use varimu_circuit::{Cores, Library, build_ir, spec};

fn lib() -> Library {
    Library::new(Path::new(env!("CARGO_MANIFEST_DIR")).join("../../config"))
}

fn build(name: &str, overrides: &[(&str, Value)]) -> Result<varimu_circuit::ir::CircuitIr, String> {
    let lib = lib();
    let c = spec::load_circuit(&spec::circuit_path(lib.config_dir(), name).unwrap()).unwrap();
    let o: Vec<(String, Value)> = overrides
        .iter()
        .map(|(k, v)| (k.to_string(), v.clone()))
        .collect();
    spec::resolve(&c, &o)
        .and_then(|p| build_ir(&lib, &c, &p, Cores::Ja))
        .map_err(|e| e.0)
}

#[test]
fn a_nonzero_tolerance_spread_is_refused() {
    let err = build("fairchild_670", &[("passive_spread", Value::Float(1.0))]).unwrap_err();
    assert!(err.contains("nominal units only (spread 0)"), "{err}");
}

#[test]
fn unknown_and_out_of_range_parameters_are_refused() {
    let err = build("fairchild_670", &[("no_such_knob", Value::Float(1.0))]).unwrap_err();
    assert!(
        err.contains("unknown circuit parameter 'no_such_knob'"),
        "{err}"
    );
    let err = build("fairchild_670", &[("ac_threshold", Value::Float(1.5))]).unwrap_err();
    assert!(
        err.contains("control ac_threshold=1.5 outside [0.0, 1.0]"),
        "{err}"
    );
    let err = build("fairchild_670", &[("time_constant", Value::Int(7))]).unwrap_err();
    assert!(err.contains("time_constant=7 outside"), "{err}");
}

#[test]
fn an_unknown_material_names_the_part() {
    let err = build(
        "fairchild_670",
        &[("t101_core_material", Value::Str("cheese".into()))],
    )
    .unwrap_err();
    assert!(
        err.contains("T101") && err.contains("unknown core material 'cheese'"),
        "{err}"
    );
}

#[test]
fn bad_circuit_files_are_refused_at_load() {
    let dir = std::env::temp_dir().join(format!("varimu-circuit-errors-{}", std::process::id()));
    std::fs::create_dir_all(&dir).unwrap();
    let path = dir.join("bad.yaml");
    std::fs::write(
        &path,
        "title: bad\nvalues:\n  r1: {value: 1.0e6, source: x}\n  r2: {value: 5}\nextra: 1\n",
    )
    .unwrap();
    let err = spec::load_circuit(&path).unwrap_err().0;
    std::fs::remove_dir_all(&dir).ok();
    assert!(err.contains("unknown top-level keys [\"extra\"]"), "{err}");
    assert!(
        err.contains("values.r1: value '1.0e6' is not a number"),
        "{err}"
    );
    assert!(err.contains("values.r2: needs a `source`"), "{err}");
}
