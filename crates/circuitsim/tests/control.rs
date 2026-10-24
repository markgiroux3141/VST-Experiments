//! Local error control: the step-selecting controller against recursive
//! halving, the ports-and-states error norm, and runs that only keep the
//! probes (`Options::all_unknowns`).

use std::f64::consts::PI;
use std::fs;
use std::path::{Path, PathBuf};

use circuitsim::ir::CircuitIr;
use circuitsim::mna::Mna;
use circuitsim::simulate;
use circuitsim::transient::{ErrorNorm, LEVEL_STATS, Method, Options, Transient};

fn fixture(name: &str) -> CircuitIr {
    let dir: PathBuf = Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("tests")
        .join("fixtures");
    CircuitIr::from_json(&fs::read_to_string(dir.join(name)).expect(name)).unwrap()
}

fn production() -> Options {
    Options {
        error_abstol: 0.01,
        error_reltol: 1e-3,
        input_order: 5,
        reltol: 1e-4,
        vntol: 1e-3,
        ..Options::with_method(Method::Esdirk4)
    }
}

/// A 1 kHz tone at `amp` volts, faded in over 1 ms, `n` samples of `h`.
fn tone(amp: f64, n: usize, h: f64) -> Vec<f64> {
    (0..n)
        .map(|i| {
            let t = i as f64 * h;
            amp * (t / 1e-3).min(1.0) * (2.0 * PI * 1000.0 * t).sin()
        })
        .collect()
}

/// The worst output difference over `probe` between `a` and `b` sampled at
/// `ka` / `kb` steps per sample, re `b`'s rms.
fn rel_error(
    a: &circuitsim::Output,
    ka: usize,
    b: &circuitsim::Output,
    kb: usize,
    probe: &str,
) -> f64 {
    let i = a.names.iter().position(|n| n == probe).unwrap();
    let (x, y) = (&a.values[i], &b.values[i]);
    let n = (x.len() - 1) / ka;
    let d: f64 = (0..n).map(|j| (x[ka * j] - y[kb * j]).powi(2)).sum::<f64>() / n as f64;
    let r: f64 = (0..n).map(|j| y[kb * j].powi(2)).sum::<f64>() / n as f64;
    (d / r).sqrt()
}

/// Both controllers on the 670 (0 dBFS at TC1: the 6973 grids clamp and the
/// bridge switches every half cycle) against its converged solution (4x the
/// rate, error tolerances / 10): as accurate as each other, every sample on
/// the grid, steps counted once at their level, and step selection
/// rejecting fewer steps than recursive halving.
#[test]
fn step_selection_and_halving_resolve_the_670_alike() {
    let ir = fixture("tc1.json");
    let h = 1.0 / 192_000.0;
    let n = 1920; // 10 ms
    let conv = Options {
        error_abstol: 1e-3,
        error_reltol: 1e-4,
        ..production()
    };
    let reference = simulate(&ir, &tone(13.8, 2 * n, h / 2.0), h / 2.0, &conv).unwrap();
    let mut rows = Vec::new();
    for step_selection in [true, false] {
        let o = Options {
            step_selection,
            ..production()
        };
        let out = simulate(&ir, &tone(13.8, n, h), h, &o).unwrap();
        assert!(out.values.iter().all(|v| v.len() == n));
        let err = 20.0 * rel_error(&out, 1, &reference, 2, "v(out)").log10();
        let s = &out.stats;
        println!(
            "selection {step_selection}: {err:.1} dB re signal, substeps {}, rejections {}, accepted {:?}, rejected {:?}",
            s.substeps, s.error_rejections, s.accepted_by_level, s.rejected_by_level
        );
        assert!(s.substeps > 0, "the clamps are subdivided");
        let accepted: u64 = s.accepted_by_level.iter().sum();
        assert_eq!(accepted, s.accepted_by_level[0] + s.substeps);
        assert_eq!(s.rejected_by_level.iter().sum::<u64>(), s.error_rejections);
        rows.push((err, s.error_rejections));
    }
    let ((sel, rej_sel), (halv, rej_halv)) = (rows[0], rows[1]);
    assert!(sel < -60.0 && halv < -60.0, "{sel} / {halv} dB");
    assert!((sel - halv).abs() < 3.0, "{sel} / {halv} dB");
    assert!(rej_sel < rej_halv, "{rej_sel} / {rej_halv}");
    assert_eq!(LEVEL_STATS, 8);
}

/// A run that keeps only the probes computes them with the same arithmetic:
/// identical outputs, on the 670 with production settings and the
/// ports-and-states norm (which the full unknowns aren't needed for).
#[test]
fn probes_only_runs_match_full_runs_on_the_670() {
    let ir = fixture("default.json");
    let h = 1.0 / 192_000.0;
    let input = tone(13.8, 960, h);
    let opts = Options {
        error_norm: ErrorNorm::PortsStates,
        ..production()
    };
    let full = simulate(&ir, &input, h, &opts).unwrap();
    let probes = simulate(
        &ir,
        &input,
        h,
        &Options {
            all_unknowns: false,
            ..opts
        },
    )
    .unwrap();
    assert_eq!(full.values, probes.values);
    assert_eq!(full.stats.substeps, probes.stats.substeps);
}

/// A parameter change rebuilds from every unknown: refused when the run
/// only keeps the probes.
#[test]
fn update_needs_every_unknown() {
    let ir = fixture("default.json");
    let opts = Options {
        all_unknowns: false,
        error_norm: ErrorNorm::PortsStates,
        ..production()
    };
    let mna = Mna::from_ir(&ir, opts.gmin).unwrap();
    let mut tr = Transient::new(mna, 1.0 / 192_000.0, opts, 0.0).unwrap();
    tr.step(0.0).unwrap();
    let e = tr.update(&ir).unwrap_err().to_string();
    assert!(e.contains("every unknown"), "{e}");
}
