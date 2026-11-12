//! `solver: dk_sparse` (dk.rs's `SparseDk`, METHODOLOGY_REVIEW.md W2) against `dk`: the
//! same algebra with the step matrix's sparse LU in place of the dense responses, so the
//! runs agree within the Newton tolerance.

use std::fs;
use std::path::Path;

use circuitsim::ir::CircuitIr;
use circuitsim::transient::{Method, Options, Solver};

/// circuitsim's own fixture, or a circuit's default IR from varimu-circuit's fixtures.
fn circuit(name: &str) -> CircuitIr {
    let here = Path::new(env!("CARGO_MANIFEST_DIR"));
    let own = here
        .join("tests")
        .join("fixtures")
        .join(format!("{name}.json"));
    if own.exists() {
        return CircuitIr::from_json(&fs::read_to_string(own).unwrap()).unwrap();
    }
    let path = here
        .join("../varimu-circuit/tests/fixtures")
        .join(format!("{name}.json"));
    let v: serde_json::Value =
        serde_json::from_str(&fs::read_to_string(&path).expect(name)).unwrap();
    CircuitIr::from_json(&v["default"].to_string()).unwrap()
}

fn agree(name: &str, amp_v: f64) {
    let ir = circuit(name);
    let h = 1.0 / 48_000.0;
    let n = 2400;
    let x: Vec<f64> = (0..n)
        .map(|k| {
            let t = k as f64 * h;
            amp_v * (t / 0.005).min(1.0) * (2.0 * std::f64::consts::PI * 330.0 * t).sin()
        })
        .collect();
    let run = |solver| {
        let opts = Options {
            solver,
            reltol: 1e-8,
            vntol: 1e-7,
            input_order: 1,
            error_abstol: 0.0,
            ..Options::with_method(Method::TrBdf2)
        };
        circuitsim::simulate(&ir, &x, h, &opts).unwrap()
    };
    let (dense, sparse) = (run(Solver::Dk), run(Solver::DkSparse));
    assert_eq!(dense.names, sparse.names);
    let mut worst = (0.0f64, String::new());
    for ((a, b), name) in dense.values.iter().zip(&sparse.values).zip(&dense.names) {
        let scale = a.iter().fold(1.0f64, |m, v| m.max(v.abs()));
        let d = a
            .iter()
            .zip(b)
            .map(|(p, q)| (p - q).abs())
            .fold(0.0, f64::max)
            / scale;
        if d > worst.0 {
            worst = (d, name.clone());
        }
    }
    println!(
        "{name}: dk_sparse vs dk, worst {:.2e} (re the probe's peak) at {}",
        worst.0, worst.1
    );
    assert!(worst.0 < 1e-6, "{name}: {worst:?}");
}

#[test]
fn the_670_agrees() {
    agree("default", 1.0);
}

#[test]
fn the_amps_agree() {
    agree("fender_5e3", 0.5);
    agree("vox_ac30", 0.5);
    agree("marshall_1987", 0.5);
}
