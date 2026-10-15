//! The compiled device models against the Python reference (values exported
//! by `scripts/export_circuit_fixtures.py` into `fixtures/devices/`), and
//! their analytic Jacobians against finite differences.

use std::fs;
use std::path::Path;

use circuitsim::devices::{self, Device};
use circuitsim::ir::DeviceModel;
use serde::Deserialize;

#[derive(Deserialize)]
struct Fixture {
    devices: Vec<Entry>,
}

#[derive(Deserialize)]
struct Entry {
    model: DeviceModel,
    ports: Vec<Vec<f64>>,
    currents: Vec<Vec<f64>>,
}

fn fixtures() -> Vec<Entry> {
    let path = Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("tests")
        .join("fixtures")
        .join("devices")
        .join("devices.json");
    let f: Fixture = serde_json::from_str(&fs::read_to_string(path).expect("devices.json"))
        .expect("parse devices.json");
    assert!(f.devices.len() >= 10, "{} device fixtures", f.devices.len());
    f.devices
}

fn eval(dev: &dyn Device, v: &[f64]) -> (Vec<f64>, Vec<f64>) {
    let n = dev.ports();
    let (mut i, mut g) = (vec![0.0; n], vec![0.0; n * n]);
    dev.eval(v, &mut i, &mut g);
    (i, g)
}

/// Relative tolerance of the plan (Rust vs Python on the fixture grids).
const RTOL: f64 = 1e-12;
/// Absolute floor: a few ulps of the junction diode's Is (7e-9 A), where
/// `nVt/Rs W - Is` cancels to roundoff around 0 V (measured: 8e-25 A with
/// opposite signs in Rust and scipy at exactly 0 V).
const ATOL: f64 = 1e-23;

#[test]
fn currents_match_the_python_reference() {
    let mut checked = 0;
    for e in fixtures() {
        let dev = devices::from_model(&e.model);
        assert_eq!(dev.ports(), e.ports[0].len(), "{}", e.model.name());
        let mut worst = 0.0f64;
        for (v, want) in e.ports.iter().zip(&e.currents) {
            let (got, _) = eval(&*dev, v);
            for (g, w) in got.iter().zip(want) {
                let err = (g - w).abs() / (w.abs() + ATOL / RTOL);
                assert!(
                    err <= RTOL,
                    "{} at {v:?}: Rust {g:e}, Python {w:e} (rel {err:.1e})",
                    e.model.name()
                );
                worst = worst.max(err);
                checked += 1;
            }
        }
        println!(
            "{:>20}: worst relative difference {worst:.1e}",
            e.model.name()
        );
    }
    assert!(checked > 2000, "{checked} values");
}

/// Port voltages that finite differences can't straddle: the pentode's 1 mV
/// screen floor (a kink), and the onsets of power laws, where the first
/// derivative is zero but the second unbounded: a triode at Vp = 0
/// (Ip ~ Vp^Ex) and the screen current at Vg1 + Vg2/mu = 0 (Ig2 ~ x^1.5).
fn near_kink(model: &DeviceModel, v: &[f64], d: f64) -> bool {
    match model {
        DeviceModel::Pentode(p) => {
            (v[1] - 1e-3).abs() <= 2.0 * d || (v[2] + v[1] / p.model.mu).abs() <= 4.0 * d
        }
        DeviceModel::Triode(_) => v[0].abs() <= 2.0 * d,
        _ => false,
    }
}

#[test]
fn jacobians_match_finite_differences() {
    let mut checked = 0;
    for e in fixtures() {
        let dev = devices::from_model(&e.model);
        let n = dev.ports();
        // Scale for the absolute tolerance: the largest current on the grid.
        let scale = e
            .currents
            .iter()
            .flatten()
            .fold(0.0f64, |m, x| m.max(x.abs()));
        for v in &e.ports {
            let (_, g) = eval(&*dev, v);
            for k in 0..n {
                let d = 1e-6 * v[k].abs().max(1e-3);
                if near_kink(&e.model, v, d) {
                    continue;
                }
                let (mut lo, mut hi) = (v.clone(), v.clone());
                lo[k] -= d;
                hi[k] += d;
                let (i_lo, _) = eval(&*dev, &lo);
                let (i_hi, _) = eval(&*dev, &hi);
                for j in 0..n {
                    let fd = (i_hi[j] - i_lo[j]) / (2.0 * d);
                    let an = g[j * n + k];
                    let tol = 1e-5 * an.abs().max(fd.abs()) + 1e-9 * scale;
                    assert!(
                        (an - fd).abs() <= tol,
                        "{} at {v:?}: d i{j} / d v{k} analytic {an:e}, finite difference {fd:e}",
                        e.model.name()
                    );
                    checked += 1;
                }
            }
        }
    }
    assert!(checked > 4000, "{checked} derivatives");
}

#[test]
fn junction_diode_limits_and_tubes_do_not() {
    for e in fixtures() {
        let dev = devices::from_model(&e.model);
        let n = dev.ports();
        let mut v = vec![5.0; n];
        let limited = dev.limit(&mut v, &vec![0.0; n]);
        match e.model {
            // A 5 V jump onto a junction is pulled back to ~vt ln(5 / vt).
            DeviceModel::JunctionDiode(_) => assert!(limited && v[0] < 0.5, "{v:?}"),
            _ => assert!(!limited && v.iter().all(|&x| x == 5.0)),
        }
    }
}
