//! IR fixtures exported from Python (`scripts/export_circuit_fixtures.py`) survive
//! JSON -> Rust -> JSON unchanged, and validation rejects broken circuits.

use std::fs;
use std::path::{Path, PathBuf};

use circuitsim::ir::{CircuitIr, DeviceModel, Element, IR_VERSION, PlateModel};
use serde_json::Value;

fn fixture_dir() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("tests")
        .join("fixtures")
}

/// Every exported IR (index.json lists cases, not circuits).
fn fixtures() -> Vec<(String, String)> {
    let mut out: Vec<(String, String)> = fs::read_dir(fixture_dir())
        .expect("fixture dir")
        .map(|e| e.expect("dir entry").path())
        .filter(|p| p.extension().is_some_and(|x| x == "json"))
        .filter(|p| p.file_name().is_some_and(|n| n != "index.json"))
        .map(|p| {
            let name = p.file_stem().unwrap().to_string_lossy().into_owned();
            (name, fs::read_to_string(&p).expect("read fixture"))
        })
        .collect();
    out.sort();
    assert!(
        out.len() >= 5,
        "expected the exported fixtures, found {}",
        out.len()
    );
    out
}

fn default_text() -> String {
    fs::read_to_string(fixture_dir().join("default.json")).expect("default.json")
}

fn edit(text: &str, f: impl FnOnce(&mut Value)) -> String {
    let mut v: Value = serde_json::from_str(text).unwrap();
    f(&mut v);
    v.to_string()
}

#[test]
fn fixtures_round_trip_exactly() {
    for (name, text) in fixtures() {
        let original: Value = serde_json::from_str(&text).unwrap();
        let ir = CircuitIr::from_json(&text).unwrap_or_else(|e| panic!("{name}: {e}"));
        let back: Value = serde_json::from_str(&ir.to_json()).unwrap();
        // Value equality compares floats exactly (and int vs float as different).
        assert_eq!(original, back, "{name}: JSON changed through Rust");
        // And the Rust value is stable through a second trip.
        assert_eq!(CircuitIr::from_json(&ir.to_json()).unwrap(), ir, "{name}");
    }
}

#[test]
fn round_trip_check_catches_ints_in_float_fields() {
    // Python must write every value as a float; an int would come back as a float.
    let text = edit(&default_text(), |v| {
        v["sections"][0]["elements"][1]["r_ohm"] = 50.into()
    });
    let original: Value = serde_json::from_str(&text).unwrap();
    let back: Value =
        serde_json::from_str(&CircuitIr::from_json(&text).unwrap().to_json()).unwrap();
    assert_ne!(original, back);
}

#[test]
fn default_fixture_has_the_670_parts() {
    let ir = CircuitIr::from_json(&default_text()).unwrap();
    assert_eq!(ir.version, IR_VERSION);
    assert_eq!(ir.input_node, "in");
    let names: Vec<&str> = ir.models.iter().map(DeviceModel::name).collect();
    assert_eq!(
        names,
        ["6386_a", "6386_b", "12AX7", "12BH7", "6973", "SI_RECTIFIER"]
    );
    let DeviceModel::Triode(bank) = ir.model("6386_a").unwrap() else {
        panic!("6386_a is not a triode")
    };
    let PlateModel::VariMu(plate) = &bank.plate else {
        panic!("6386 plate is not variable-mu")
    };
    assert_eq!(plate.mus.len(), plate.weights.len());
    assert!((plate.weights.iter().sum::<f64>() - 1.0).abs() < 1e-12);

    let find = |n: &str| ir.elements().find(|e| e.name() == n).cloned();
    let Some(Element::Resistor(r103)) = find("R103") else {
        panic!("R103 missing")
    };
    assert_eq!(
        (r103.a.as_str(), r103.b.as_str(), r103.r_ohm),
        ("ka", "ta", 680.0)
    );
    let Some(Element::Coupling(k)) = find("KT101_p_sa") else {
        panic!("KT101_p_sa missing")
    };
    assert_eq!((k.l_a.as_str(), k.l_b.as_str()), ("LT101_p", "LT101_sa"));
    let Some(Element::Device(xva)) = find("XVA") else {
        panic!("XVA missing")
    };
    assert_eq!(xva.model, "6386_a");
    assert_eq!(xva.nodes, ["pa", "ga", "ka"]);
}

#[test]
fn time_constant_fixtures_differ_only_in_the_switched_parts() {
    let names = |file: &str| -> Vec<String> {
        let text = fs::read_to_string(fixture_dir().join(file)).unwrap();
        let ir = CircuitIr::from_json(&text).unwrap();
        ir.elements().map(|e| e.name().to_string()).collect()
    };
    let tc6 = names("tc6.json");
    for part in ["R139", "C110", "R140", "C112"] {
        assert!(
            tc6.iter().any(|n| n == part),
            "{part} missing at position 6"
        );
    }
    assert!(!names("default.json").iter().any(|n| n == "C112"));
}

fn rejects(text: &str, needle: &str) {
    match CircuitIr::from_json(text) {
        Ok(_) => panic!("accepted a circuit that should fail with {needle:?}"),
        Err(e) => assert!(e.to_string().contains(needle), "error {e} lacks {needle:?}"),
    }
}

#[test]
fn rejects_unknown_fields_and_versions() {
    let text = default_text();
    rejects(&edit(&text, |v| v["extra"] = 1.into()), "unknown field");
    rejects(
        &edit(&text, |v| {
            v["sections"][0]["elements"][1]["tolerance"] = 0.01.into()
        }),
        "unknown field",
    );
    rejects(
        &edit(&text, |v| v["models"][0]["plate"]["n_sections"] = 32.into()),
        "unknown field",
    );
    rejects(
        &edit(&text, |v| v["version"] = (IR_VERSION + 1).into()),
        "version",
    );
    rejects(
        &edit(&text, |v| {
            v["sections"][0]["elements"][0]["kind"] = "fuse".into()
        }),
        "unknown variant",
    );
}

#[test]
fn rejects_inconsistent_circuits() {
    let text = default_text();
    // Element 1 of the power supply section is the resistor Rpsu.
    rejects(
        &edit(&text, |v| {
            v["sections"][0]["elements"][1]["name"] = "VBP".into()
        }),
        "duplicate element",
    );
    rejects(
        &edit(&text, |v| {
            v["sections"][0]["elements"][1]["name"] = "Xpsu".into()
        }),
        "must start with R",
    );
    rejects(
        &edit(&text, |v| {
            v["sections"][0]["elements"][1]["r_ohm"] = 0.0.into()
        }),
        "> 0",
    );
    rejects(
        &edit(&text, |v| {
            v["sections"][0]["elements"][1]["b"] = "bpi".into()
        }),
        "both ends",
    );
    rejects(
        &edit(&text, |v| v["models"][0]["name"] = "6386_x".into()),
        "unknown model 6386_a",
    );
    rejects(
        &edit(&text, |v| v["input_node"] = "nowhere".into()),
        "input node",
    );
    rejects(
        &edit(&text, |v| v["probes"][0]["node"] = "nowhere".into()),
        "probe node",
    );
    let bad_coupling = edit(&text, |v| {
        for s in v["sections"].as_array_mut().unwrap() {
            for e in s["elements"].as_array_mut().unwrap() {
                if e["name"] == "KT101_p_sa" {
                    e["l_b"] = "RT101_sa".into();
                }
            }
        }
    });
    rejects(&bad_coupling, "not an inductor");
}
