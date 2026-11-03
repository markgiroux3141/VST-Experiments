//! The leakage formulas against the 2D field solution (docs/COMPONENT_EDITOR_PLAN.md C2
//! step 4): four geometries on the repo's tables, every winding pair. Layer windings
//! within +-8% (the formula low by up to 8% where thick paper spreads the field), disc
//! windings within +-20%.
//!
//! Run with `--nocapture` to see the table; `cargo test --release` (the solver is slow
//! unoptimized).

use std::path::{Path, PathBuf};

use varimu_circuit::Library;
use varimu_circuit::yaml;
use varimu_components::compile::{Compiled, compile};
use varimu_components::design::Design;
use varimu_components::fem::{self, Mesh};
use varimu_components::leakage::series_short_circuit;
use varimu_components::tables::Tables;

fn config() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("../../config")
}

fn compiled(text: &str) -> Compiled {
    let d = Design::parse(&yaml::parse(text, "design").unwrap()).unwrap();
    let t = Tables::load(&config()).unwrap();
    compile(&d, &t, &Library::new(config())).unwrap()
}

fn v(x: &str) -> String {
    format!("{{value: {x}, source: test}}")
}

/// A layer-wound output transformer on an EI-75 (the 5E3's family): a primary of 1000
/// turns in 10 layers with kraft between them, then the secondary; `split` puts half the
/// secondary under the primary (S P S).
fn layer_ot(split: bool) -> String {
    let sec = |turns: &str, layers: &str| {
        format!(
            "  - winding: s\n    turns: {}\n    layers: {}\n    wire: {{value: AWG 22 heavy, source: test}}\n    enamel: {{value: enamel, source: test}}\n",
            v(turns),
            v(layers)
        )
    };
    let ins = format!(
        "  - insulation: {{thickness_m: {}, dielectric: {{value: kraft_dry, source: test}}}}\n",
        v("0.25e-3")
    );
    let pri = format!(
        "  - winding: p\n    turns: {}\n    layers: {}\n    wire: {{value: AWG 33 heavy, source: test}}\n    enamel: {{value: enamel, source: test}}\n    interlayer: {{thickness_m: {}, dielectric: {{value: kraft_dry, source: test}}}}\n",
        v("1000"),
        v("10"),
        v("0.05e-3")
    );
    let sections = if split {
        format!("{}{ins}{pri}{ins}{}", sec("30", "1"), sec("30", "1"))
    } else {
        format!("{pri}{ins}{}", sec("60", "2"))
    };
    format!(
        "name: T\nkind: transformer\nsource: test\ncore:\n  lamination: {{value: EI-75, source: test}}\n  material: {{value: grain_oriented_si_steel, source: test}}\n  stack_m: {}\n  stacking_factor: {}\n  stacking: {{value: interleaved, source: test}}\n  joint_gap_m: {}\nbobbin:\n  wall_m: {}\n  cheek_m: {}\n  margin_m: {}\n  pitch_factor: {}\narrangement: {{value: layer, source: test}}\nwindings: [p, s]\nsections:\n{sections}",
        v("0.0254"),
        v("0.95"),
        v("5.0e-6"),
        v("1.0e-3"),
        v("1.0e-3"),
        v("1.5e-3"),
        v("1.05")
    )
}

/// 1D / 2D - 1 for every ordered pair, and each listed series group.
fn compare(name: &str, c: &Compiled, groups: &[(&[usize], &[usize])]) -> Vec<f64> {
    let n = c.windings.len();
    let z0 = c.design.bobbin.cheek_m.value + c.design.bobbin.margin_m.value;
    let mut cases: Vec<(Vec<usize>, Vec<usize>)> = Vec::new();
    for j in 0..n {
        for k in 0..n {
            if j != k {
                cases.push((vec![j], vec![k]));
            }
        }
    }
    cases.extend(groups.iter().map(|(d, s)| (d.to_vec(), s.to_vec())));
    let mut errs = Vec::new();
    for (d, s) in cases {
        let one = series_short_circuit(&c.layout, n, &d, &s);
        let two = fem::series_short_circuit(&c.layout, z0, n, &d, &s, Mesh::default());
        let e = one / two - 1.0;
        println!(
            "{name}: {:?} with {:?} shorted: 1D {:.4} mH, 2D {:.4} mH ({:+.1}%)",
            d,
            s,
            one * 1e3,
            two * 1e3,
            100.0 * e
        );
        errs.push(e);
    }
    errs
}

#[test]
fn layer_windings() {
    let plain = compare("P|S", &compiled(&layer_ot(false)), &[]);
    let split = compare("S|P|S", &compiled(&layer_ot(true)), &[]);
    // The fitted 5E3 output transformer (config/designs/ot_5e3.yaml): thick paper between
    // the windings, where the field spreads most (-3 to -8%).
    let text = std::fs::read_to_string(config().join("designs/ot_5e3.yaml")).unwrap();
    let formula = text
        .replace("\r\n", "\n")
        .replace("leakage_method: field\n", "");
    let ot = compare("OT_5E3", &compiled(&formula), &[]);
    for e in plain.iter().chain(&split).chain(&ot) {
        assert!(e.abs() < 0.08, "{e}");
    }
}

#[test]
fn disc_windings_bv191() {
    let text = std::fs::read_to_string(config().join("designs/v72_bv191.yaml")).unwrap();
    let c = compiled(
        &text
            .replace("\r\n", "\n")
            .replace("leakage_method: field\n", ""),
    );
    let errs = compare("BV 191", &c, &[(&[0, 1], &[2])]);
    for e in errs {
        assert!(e.abs() < 0.20, "{e}");
    }
}

/// `leakage_method: field`: the compiled leakages reproduce the field solution's pairs, and
/// (three windings: the pairs fix every balanced excitation) its series groups.
#[test]
fn the_field_method_compiles_the_field_solution() {
    // BV 191's design compiles by the field (as BV191@2 does).
    let text = std::fs::read_to_string(config().join("designs/v72_bv191.yaml"))
        .unwrap()
        .replace("\r\n", "\n");
    assert!(text.contains("\nleakage_method: field\n"));
    let c = compiled(&text);
    let z0 = c.design.bobbin.cheek_m.value + c.design.bobbin.margin_m.value;
    let field = |d: &[usize], s: &[usize]| {
        fem::series_short_circuit(&c.layout, z0, 3, d, s, Mesh::default())
    };
    for (j, k) in [(0, 2), (1, 2), (0, 1)] {
        let want = field(&[j], &[k]);
        assert!((c.short_circuit_h(j, k) / want - 1.0).abs() < 1e-9);
        assert!((c.group_short_circuit_h(&[j], &[k]) / want - 1.0).abs() < 1e-9);
    }
    let want = field(&[0, 1], &[2]);
    let got = c.group_short_circuit_h(&[0, 1], &[2]);
    assert!((got / want - 1.0).abs() < 1e-6, "{got} vs {want}");
}
