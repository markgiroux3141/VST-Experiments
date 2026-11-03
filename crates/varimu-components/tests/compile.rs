//! The compiler end to end on a scratch config (its own small tables, the repo's
//! magnetics.yaml), against hand computations, and saving versions into a scratch store.

use std::f64::consts::PI;
use std::path::{Path, PathBuf};

use circuitsim::devices::core::MU0;
use varimu_circuit::versions::{self, Ref};
use varimu_circuit::yaml;
use varimu_components::compile::{LeakageModel, compile_file};
use varimu_components::design::Design;
use varimu_components::store;

fn repo_config() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("../../config")
}

const LAMINATIONS: &str = "\
groups:
  - source: 'test: a scrapless EI, 20 mm tongue'
    unit: mm
    shape: EI
    sizes:
      EI-TEST: {leg: 20.0, window_width: 10.0, window_height: 30.0, width: 60.0, height: 50.0}
";

const WIRE: &str = "\
copper:
  resistivity_ohm_m: 1.7241e-8
  temperature_c: 20.0
  source: 'test: IACS'
awg:
  bare_source: 'test: ASTM B258'
  source: 'test: overall diameters'
  unit: inch
  overall:
    30: {heavy: [0.0110, 0.0114]}
metric:
  source: 'test: grades'
  unit: mm
  overall:
    0.2: {grade1: [0.220, 0.230]}
";

const DIELECTRICS: &str = "\
dielectrics:
  paper: {eps_r: 2.0, source: 'test'}
  enamel: {eps_r: 3.0, source: 'test'}
";

/// A scratch config: the tables above, the repo's magnetics.yaml, an empty store.
fn scratch(tag: &str) -> PathBuf {
    let dir = std::env::temp_dir().join(format!("varimu_components_{tag}_{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&dir);
    std::fs::create_dir_all(dir.join("transformer")).unwrap();
    std::fs::create_dir_all(dir.join("components")).unwrap();
    std::fs::write(dir.join("transformer/laminations.yaml"), LAMINATIONS).unwrap();
    std::fs::write(dir.join("transformer/wire.yaml"), WIRE).unwrap();
    std::fs::write(dir.join("transformer/dielectrics.yaml"), DIELECTRICS).unwrap();
    std::fs::copy(
        repo_config().join("magnetics.yaml"),
        dir.join("magnetics.yaml"),
    )
    .unwrap();
    dir
}

fn v(x: &str) -> String {
    format!("{{value: {x}, source: 'test'}}")
}

/// Primary (200 turns, 2 layers of 0.2 mm), 0.1 mm paper, secondary (100 turns, 1 layer).
fn design(extra_sections: &str) -> String {
    format!(
        "\
name: TEST_T
kind: transformer
source: 'test design'
core:
  lamination: {{value: EI-TEST, source: 'test'}}
  material: {{value: mumetall, source: 'test'}}
  stack_m: {}
  stacking_factor: {}
  stacking: {{value: interleaved, source: 'test'}}
  joint_gap_m: {}
bobbin:
  wall_m: {}
  cheek_m: {}
  margin_m: {}
  pitch_factor: {}
arrangement: {{value: layer, source: 'test'}}
windings: [p, s]
sections:
  - winding: p
    turns: {}
    layers: {}
    wire: {{value: 0.2 mm grade 1, source: 'test'}}
    enamel: {{value: enamel, source: 'test'}}
  - insulation: {{thickness_m: {}, dielectric: {{value: paper, source: 'test'}}}}
  - winding: s
    turns: {}
    layers: {}
    wire: {{value: 0.2 mm grade 1, source: 'test'}}
    enamel: {{value: enamel, source: 'test'}}
{extra_sections}rating:
  windings: [p]
  v_rms: {}
  f_hz: {}
",
        v("0.02"),
        v("0.9"),
        v("1.0e-5"),
        v("1.0e-3"),
        v("1.0e-3"),
        v("0.5e-3"),
        v("1.0"),
        v("200"),
        v("2"),
        v("1.0e-4"),
        v("100"),
        v("1"),
        v("10.0"),
        v("50.0"),
    )
}

fn write(dir: &Path, name: &str, text: &str) -> PathBuf {
    let p = dir.join(name);
    std::fs::write(&p, text).unwrap();
    p
}

#[test]
fn a_two_winding_design_matches_hand_computation() {
    let dir = scratch("hand");
    let path = write(&dir, "t.yaml", &design(""));
    let (_, _, c) = compile_file(&path, &dir).unwrap();

    let (a, s) = (0.02, 0.02);
    // Core: leg x stack x stacking factor; a scrapless EI's path 6a; two joints.
    assert!((c.area_m2 - a * s * 0.9).abs() < 1e-15);
    assert!((c.path_m - 6.0 * a).abs() < 1e-12);
    assert!((c.gap_m - 2.0e-5).abs() < 1e-18);

    // The wire: 0.2 mm bare, 0.225 mm overall (the grade's middle).
    let (d_c, d_o) = (0.2e-3, 0.225e-3);
    let a_cu = PI * d_c * d_c / 4.0;
    // McLyman [4-23]: around the 1 mm tube, rounded above it.
    let w = 1e-3;
    let turn = |r: f64| 2.0 * (a + 2.0 * w) + 2.0 * (s + 2.0 * w) + 2.0 * PI * (r - w);
    // Primary: two layers of 100 turns from the 1 mm wall.
    let (p0, p1) = (1e-3 + 0.5 * d_o, 1e-3 + 1.5 * d_o);
    let r_p = 1.7241e-8 * 100.0 * (turn(p0) + turn(p1)) / a_cu;
    assert!(
        (c.windings[0].r_ohm / r_p - 1.0).abs() < 1e-12,
        "{} vs {r_p}",
        c.windings[0].r_ohm
    );
    let s0 = 1e-3 + 2.0 * d_o + 1e-4 + 0.5 * d_o;
    let r_s = 1.7241e-8 * 100.0 * turn(s0) / a_cu;
    assert!((c.windings[1].r_ohm / r_s - 1.0).abs() < 1e-12);
    assert!((c.windings[1].ratio - 0.5).abs() < 1e-15);

    // Leakage: the 1D integral by hand, piece by piece. Each layer's copper is the
    // equal-area square (sqrt(pi)/2 d_c) in the middle of its 0.225 mm; the primary's
    // share ramps 0 -> 1/2 over the first copper, 1/2 -> 1 over the second; the
    // secondary's 0 -> 1 over its copper. (f_p - f_s)^2 P integrated:
    let cu = 0.5 * PI.sqrt() * d_c;
    let e = 0.5 * (d_o - cu);
    let x0 = 1e-3 + e; // the first copper's start: the field starts there
    let pieces = [
        (x0, x0 + cu, (0.0, 0.5)),
        (x0 + cu, x0 + cu + 2.0 * e, (0.5, 0.5)),
        (x0 + cu + 2.0 * e, x0 + 2.0 * cu + 2.0 * e, (0.5, 1.0)),
        (
            x0 + 2.0 * cu + 2.0 * e,
            x0 + 2.0 * cu + 4.0 * e + 1e-4,
            (1.0, 1.0),
        ),
        (
            x0 + 2.0 * cu + 4.0 * e + 1e-4,
            x0 + 3.0 * cu + 4.0 * e + 1e-4,
            (1.0, 0.0),
        ),
    ];
    let mut int = 0.0;
    for (u0, u1, (g0, g1)) in pieces {
        let n = 2000;
        for i in 0..n {
            let t = (i as f64 + 0.5) / n as f64;
            let x = u0 + t * (u1 - u0);
            let g = g0 + (g1 - g0) * t;
            int += g * g * turn(x) * (u1 - u0) / n as f64;
        }
    }
    let b = 100.0 * d_o; // the layer length: 100 turns at pitch factor 1
    let lambda = 3.0 * cu + 4.0 * e + 1e-4;
    let k_r = 1.0 - (1.0 - (-PI * b / lambda).exp()) * lambda / (PI * b);
    let h = b / k_r;
    let want = MU0 / h * int * 200.0 * 200.0;
    let got = c.short_circuit_h(0, 1);
    assert!((got / want - 1.0).abs() < 1e-6, "{got} vs {want}");
    assert_eq!(c.leakage_model, LeakageModel::Star);
    let sum = c.windings[0].leak_h + c.windings[1].leak_h / (0.5 * 0.5);
    assert!((sum / got - 1.0).abs() < 1e-12);

    // Flux: sqrt 2 V / (2 pi f N A).
    let bpk = 2f64.sqrt() * 10.0 / (2.0 * PI * 50.0 * 200.0 * c.area_m2);
    assert!((c.b_peak_t.unwrap() - bpk).abs() < 1e-12);
    // The one warning: the single-layer secondary has no capacitance of its own, so its
    // facing layer's negative share across it (not realizable by positive capacitors) is
    // clamped.
    assert_eq!(c.warnings.len(), 1, "{:?}", c.warnings);
    assert!(
        c.warnings[0].starts_with("capacitance: s's own"),
        "{:?}",
        c.warnings
    );
}

#[test]
fn values_need_sources_and_known_keys() {
    let dir = scratch("refuse");
    let bare = design("").replace("stack_m: {value: 0.02, source: 'test'}", "stack_m: 0.02");
    let e = Design::parse(&yaml::parse(&bare, "t").unwrap())
        .unwrap_err()
        .0;
    assert!(e.contains("never bare"), "{e}");
    let typo = design("").replace("stack_m:", "stak_m:");
    let e = Design::parse(&yaml::parse(&typo, "t").unwrap())
        .unwrap_err()
        .0;
    assert!(e.contains("unknown key `stak_m`"), "{e}");
    let _ = dir;
}

#[test]
fn overflowing_windows_warn() {
    let dir = scratch("overflow");
    // 2000 turns in one layer can't fit a 28 mm traverse.
    let text = design("").replace("turns: {value: 200,", "turns: {value: 2000,");
    let path = write(&dir, "t.yaml", &text);
    let (_, _, c) = compile_file(&path, &dir).unwrap();
    assert!(
        c.warnings.iter().any(|w| w.contains("turns per layer")),
        "{:?}",
        c.warnings
    );
}

#[test]
fn a_shield_screens_the_windings() {
    let dir = scratch("shield");
    let text = design("").replace(
        "  - insulation: {thickness_m: {value: 1.0e-4, source: 'test'}, dielectric: {value: paper, source: 'test'}}\n",
        "  - insulation: {thickness_m: {value: 0.5e-4, source: 'test'}, dielectric: {value: paper, source: 'test'}}\n  - shield: {name: S, thickness_m: {value: 0.3e-4, source: 'test'}}\n  - insulation: {thickness_m: {value: 0.5e-4, source: 'test'}, dielectric: {value: paper, source: 'test'}}\n",
    );
    let path = write(&dir, "t.yaml", &text);
    let (_, _, c) = compile_file(&path, &dir).unwrap();
    assert!(c.capacitance.between.iter().all(|b| b.a == b.b));
    assert_eq!(c.capacitance.to_shields.len(), 2);
    assert!(c.capacitance.to_shields.iter().all(|s| s.c_f > 0.0));
}

#[test]
fn saving_writes_a_version_and_its_lock_line() {
    let dir = scratch("save");
    let path = write(&dir, "t.yaml", &design(""));
    let (data, tables, c) = compile_file(&path, &dir).unwrap();
    let text = c.version_text(&data, &tables, &dir, "2026-11-04").unwrap();
    let root = dir.join("components");
    assert!(store::unchanged(&root, "TEST_T", &text).unwrap().is_none());
    let r = store::save(&root, "TEST_T", &text).unwrap();
    assert_eq!(
        r,
        Ref {
            name: "TEST_T".into(),
            version: Some(1)
        }
    );
    // It reads back through varimu-circuit's checked reader, and parses as YAML.
    let (_, back) = versions::read_text(&root, &r).unwrap();
    assert_eq!(back, text);
    let parsed = yaml::parse(&back, "v").unwrap();
    let compiled = parsed
        .as_map()
        .unwrap()
        .get("compiled")
        .unwrap()
        .as_map()
        .unwrap();
    assert_eq!(compiled.get("turns").unwrap().as_f64(), Some(200.0));
    // The same design on another day is unchanged; nothing new is saved.
    let later = c.version_text(&data, &tables, &dir, "2026-12-01").unwrap();
    assert_eq!(
        store::unchanged(&root, "TEST_T", &later).unwrap(),
        Some(r.clone())
    );
    // A changed design saves version 2.
    let path2 = write(
        &dir,
        "t2.yaml",
        &design("").replace(
            "value: 100, source: 'test'}\n    layers",
            "value: 110, source: 'test'}\n    layers",
        ),
    );
    let (d2, t2, c2) = compile_file(&path2, &dir).unwrap();
    let text2 = c2.version_text(&d2, &t2, &dir, "2026-11-04").unwrap();
    assert!(store::unchanged(&root, "TEST_T", &text2).unwrap().is_none());
    assert_eq!(
        store::save(&root, "TEST_T", &text2).unwrap().version,
        Some(2)
    );
    assert_eq!(versions::versions(&root, "TEST_T"), vec![1, 2]);
}
