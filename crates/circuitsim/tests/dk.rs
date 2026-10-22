//! The DK solver against the full-MNA solver: same method, same input, every
//! node compared at every sample, on the 670 fixtures.
//!
//! "Agree" means within one Newton tolerance (`reltol |v| + vntol`) on every
//! node with exact Newton (`newton_reuse: false`, the same iterates as full
//! MNA). Measured 2026-10-17 (0 dBFS 1 kHz tone, 6 ms): worst 0.2 tolerance;
//! on the plates 3e-8..2e-7 V, full MNA's own roundoff spread (the same
//! circuit with its unknowns numbered in reverse: 3e-8..9e-8 V). With
//! Jacobian reuse (the default) each solve ends within a tolerance, and the
//! differences add up over steps (bounds below).
//!
//! Except the common mode of T104's floating secondary (nodes ay, bk,
//! T104_s_l, compared relative to bk; bk itself gets an absolute bound).
//! With the bridge off the island hangs on diode leakage (~1e-7 S) or, with
//! the bridge reversed for good, on its 1 GOhm leak alone, and the 1 mOhm
//! winding's ~5e4 A conductance terms leave ~1e-11 A of roundoff in its KCL:
//! ~1e-4 V or ~1e-2 V of common mode in either solver. Evaluated in 40-digit
//! arithmetic at one sample, full MNA's solution there violated the
//! island's KCL by 4e-12 A (4.6e-5 V), DK's by 1e-12 A.

use std::fs;
use std::path::{Path, PathBuf};

use circuitsim::ir::CircuitIr;
use circuitsim::mna::{Mna, Unknown};
use circuitsim::transient::{Method, Options, Solver, Transient};

fn fixture(name: &str) -> CircuitIr {
    let dir: PathBuf = Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("tests")
        .join("fixtures");
    CircuitIr::from_json(&fs::read_to_string(dir.join(name)).expect(name)).unwrap()
}

/// 0 dBFS in volts at the 670's input (sim_settings.yaml, full_scale_volts_peak).
const FULL_SCALE_V: f64 = 13.8;
const FS: f64 = 96_000.0;

/// T104's secondary, floating on the bridge diodes and a 1 GOhm leak: its
/// nodes, compared relative to the first, and the bound on the first (V):
/// 1e-11 A of KCL roundoff on the 1 GOhm leak. Measured up to 2.1e-3 V.
const FLOATING: [&str; 3] = ["node bk", "node ay", "node T104_s_l"];
const FLOATING_BOUND_V: f64 = 1e-2;

/// A 1 kHz tone at `dbfs`, faded in over 1 ms, for `dur_s`, at k x 96 kHz.
fn tone(dbfs: f64, dur_s: f64, k: usize) -> Vec<f64> {
    let h = 1.0 / (FS * k as f64);
    let n = (dur_s / h) as usize;
    let a = FULL_SCALE_V * 10f64.powf(dbfs / 20.0);
    (0..n)
        .map(|i| {
            let t = i as f64 * h;
            a * (t / 1e-3).min(1.0) * (2.0 * std::f64::consts::PI * 1000.0 * t).sin()
        })
        .collect()
}

/// Every unknown at every sample, and the solver statistics.
fn run(ir: &CircuitIr, opts: Options, input: &[f64], h: f64) -> (Vec<Vec<f64>>, circuitsim::Stats) {
    let mna = Mna::from_ir(ir, opts.gmin).unwrap();
    let mut tr = Transient::new(mna, h, opts, input[0]).unwrap();
    let mut xs = vec![tr.x().to_vec()];
    for &u in &input[1..] {
        tr.step(u).unwrap();
        xs.push(tr.x().to_vec());
    }
    (xs, tr.stats().clone())
}

/// Worst difference between two runs over the nodes, relative to each
/// node's Newton tolerance (and that node), and of the `floating` island's
/// common mode in volts (its first node; the others are compared relative
/// to it).
fn compare(
    unknowns: &[Unknown],
    a: &[Vec<f64>],
    b: &[Vec<f64>],
    opts: &Options,
    floating: &[&str],
) -> (f64, String, f64) {
    let common = unknowns
        .iter()
        .position(|u| floating.first() == Some(&u.describe().as_str()));
    let (mut worst, mut worst_floating) = (0.0f64, 0.0f64);
    let mut worst_at = 0;
    for (a, b) in a.iter().zip(b) {
        let (ca, cb) = common.map_or((0.0, 0.0), |c| (a[c], b[c]));
        worst_floating = worst_floating.max((ca - cb).abs());
        for (j, ((p, q), u)) in a.iter().zip(b).zip(unknowns).enumerate() {
            if !matches!(u, Unknown::Node(_)) || Some(j) == common {
                continue;
            }
            let (p, q) = if floating.contains(&u.describe().as_str()) {
                (p - ca, q - cb)
            } else {
                (*p, *q)
            };
            let tol = opts.reltol * p.abs().max(q.abs()) + opts.vntol;
            let e = (p - q).abs() / tol;
            if e > worst {
                (worst, worst_at) = (e, j);
            }
        }
    }
    (worst, unknowns[worst_at].describe(), worst_floating)
}

#[test]
fn dk_agrees_with_full_mna_on_the_670() {
    let k = 2;
    let input = tone(0.0, 0.006, k);
    let h = 1.0 / (FS * k as f64);
    // Default settings, the fastest attack, the bridge reversed (pots at
    // minimum), mismatched 6386s.
    for name in ["default.json", "tc1.json", "pots_min.json", "mismatch.json"] {
        let ir = fixture(name);
        let unknowns = Mna::from_ir(&ir, 1e-12).unwrap().unknowns;
        let esdirk4 = Options::with_method(Method::Esdirk4);
        let production = Options {
            error_abstol: 0.01,
            error_reltol: 1e-3,
            ..esdirk4
        };
        for opts in [
            Options::with_method(Method::Trapezoidal),
            esdirk4,
            production,
        ] {
            let (mna, st_mna) = run(
                &ir,
                Options {
                    solver: Solver::Mna,
                    ..opts
                },
                &input,
                h,
            );
            assert_eq!(st_mna.solver, "mna");
            for newton_reuse in [false, true] {
                let o = Options {
                    solver: Solver::Dk,
                    newton_reuse,
                    ..opts
                };
                let (dk, st_dk) = run(&ir, o, &input, h);
                assert_eq!(st_dk.solver, "dk");
                let (worst, at, floating) = compare(&unknowns, &mna, &dk, &opts, &FLOATING);
                println!(
                    "{name:14} {:?} control {} reuse {newton_reuse}: worst {worst:.2e} tol ({at}), \
                     floating {floating:.1e} V; iterations mna {} dk {}, substeps {} / {}",
                    opts.method,
                    opts.error_abstol > 0.0,
                    st_mna.iterations,
                    st_dk.iterations,
                    st_mna.substeps,
                    st_dk.substeps,
                );
                if newton_reuse && st_mna.substeps != st_dk.substeps {
                    // With reuse a solve ends anywhere within a tolerance of
                    // its solution, which can tip a borderline error-control
                    // decision (measured once, TC1 with the Jiles-Atherton
                    // cores: 13 substeps vs 12). The runs then differ by what
                    // that decision is about: compare them in units of the
                    // error tolerance (measured: 5.0; the floating island
                    // 0.19 V).
                    assert!(opts.error_abstol > 0.0, "{name}: decisions differ");
                    let err_opts = Options {
                        reltol: opts.error_reltol,
                        vntol: opts.error_abstol,
                        ..opts
                    };
                    let (w, _, floating) = compare(&unknowns, &mna, &dk, &err_opts, &FLOATING);
                    println!("  decisions differ: {w:.2} x error tolerance");
                    assert!(w < 30.0 && floating < 0.5, "{name}: {w}, {floating} V");
                    continue;
                }
                assert!(floating < FLOATING_BOUND_V, "{name}: {floating} V");
                // Exact Newton: the iterates are full MNA's, so every node
                // agrees within a tolerance (measured <= 0.2). With reuse each
                // solve stops within a tolerance of its own solution, and those
                // add up over steps: <= 3 measured with esdirk4 (L-stable), <= 18
                // with trapezoidal, which doesn't damp them.
                let bound = if newton_reuse { 30.0 } else { 1.0 };
                assert!(
                    worst < bound,
                    "{name} {:?} reuse {newton_reuse}: {worst} x tol",
                    opts.method
                );
                // The same error-control decisions (exact Newton: always).
                assert_eq!(
                    st_mna.substeps, st_dk.substeps,
                    "{name} reuse {newton_reuse}"
                );
            }
        }
    }
}
