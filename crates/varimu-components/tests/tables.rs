//! The repo's tables (config/transformer/) load, and agree with themselves.

use std::path::Path;

use varimu_circuit::yaml::{self, Value};
use varimu_components::tables::{Lamination, Tables};

fn config() -> std::path::PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("../../config")
}

#[test]
fn the_tables_load() {
    let t = Tables::load(&config()).unwrap();
    let ei48 = t.lamination("EI 48").unwrap();
    assert_eq!(
        (ei48.leg_m, ei48.window_width_m, ei48.window_height_m),
        (0.016, 0.008, 0.024)
    );
    assert!((ei48.path_m - 0.096).abs() < 1e-12);
    let w = t.wire("AWG 32 heavy").unwrap();
    assert!((w.overall_m - 0.0094 * 0.0254).abs() < 1e-12);
    let w = t.wire("0.06 mm grade 1").unwrap();
    assert!((w.overall_m - 0.069e-3).abs() < 1e-12);
    assert!(
        t.wire("0.28 mm grade 1").is_err(),
        "left out: the sheet's typo"
    );
    assert!(t.dielectric("polystyrene").is_ok());
    assert_eq!(t.copper().unwrap().resistivity_ohm_m, 1.7241e-8);
}

/// Where a size gives both its path and its overall dimensions, the mean path through
/// the legs' and yokes' middles reproduces the source's path (a typo shows up here).
#[test]
fn sourced_paths_match_the_dimensions() {
    let data = yaml::load(&config().join("transformer/laminations.yaml")).unwrap();
    let groups = data
        .as_map()
        .unwrap()
        .get("groups")
        .unwrap()
        .as_list()
        .unwrap();
    let t = Tables::load(&config()).unwrap();
    let mut checked = 0;
    for g in groups {
        let sizes = g.as_map().unwrap().get("sizes").unwrap().as_map().unwrap();
        for (name, row) in sizes.iter() {
            let r = row.as_map().unwrap();
            if !(r.contains("path") && r.contains("width") && r.contains("height")) {
                continue;
            }
            let l = t.lamination(name).unwrap();
            let scale = l.leg_m / r.get("leg").and_then(Value::as_f64).unwrap();
            let derived = Lamination::derived_path_m(
                l.shape,
                l.leg_m,
                l.window_width_m,
                l.window_height_m,
                r.get("width").and_then(Value::as_f64).unwrap() * scale,
                r.get("height").and_then(Value::as_f64).unwrap() * scale,
            );
            assert!(
                (derived / l.path_m - 1.0).abs() < 0.005,
                "{name}: derived {derived} vs the source's {}",
                l.path_m
            );
            checked += 1;
        }
    }
    assert!(checked >= 15, "{checked}");
}
