//! The compiled device models against the Python reference (values exported
//! by `scripts/export_circuit_fixtures.py` into `fixtures/devices/`), and
//! their analytic Jacobians against finite differences.

use std::fs;
use std::path::Path;

use circuitsim::devices::core::{CoreState, MagneticCore};
use circuitsim::devices::{self, Device};
use circuitsim::ir::{DeviceModel, TESLA_PER_V};
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
    /// Devices with memory (the magnetic core): the state each point is
    /// evaluated from, `[b, h, delta]`.
    #[serde(default)]
    states: Vec<[f64; 3]>,
}

/// The device of `e` as point `k` sees it (with that point's state, for a core).
fn device_at(e: &Entry, k: usize) -> Box<dyn Device> {
    match &e.model {
        DeviceModel::MagneticCore(m) => {
            let [b, h, delta] = e.states[k];
            let mut c = MagneticCore::new(m);
            c.state = CoreState { b, h, delta };
            Box::new(c)
        }
        model => devices::from_model(model),
    }
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
        assert_eq!(
            device_at(&e, 0).ports(),
            e.ports[0].len(),
            "{}",
            e.model.name()
        );
        let mut worst = 0.0f64;
        for (k, (v, want)) in e.ports.iter().zip(&e.currents).enumerate() {
            let (got, _) = eval(&*device_at(&e, k), v);
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
/// A core has a kink at its state's B, where the direction of B switches.
fn near_kink(model: &DeviceModel, v: &[f64], d: f64, state: Option<&[f64; 3]>) -> bool {
    if let Some([b, _, _]) = state {
        return (v[0] * TESLA_PER_V - b).abs() <= 2.0 * d * TESLA_PER_V;
    }
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
        let n = device_at(&e, 0).ports();
        // Scale for the absolute tolerance: the largest current on the grid.
        let scale = e
            .currents
            .iter()
            .flatten()
            .fold(0.0f64, |m, x| m.max(x.abs()));
        for (p, v) in e.ports.iter().enumerate() {
            let dev = device_at(&e, p);
            let (_, g) = eval(&*dev, v);
            for k in 0..n {
                let d = 1e-6 * v[k].abs().max(1e-3);
                if near_kink(&e.model, v, d, e.states.get(p)) {
                    continue;
                }
                let (mut lo, mut hi) = (v.clone(), v.clone());
                lo[k] -= d;
                hi[k] += d;
                let (i_lo, _) = eval(&*dev, &lo);
                let (i_hi, _) = eval(&*dev, &hi);
                // A core's Jacobian is dH/dB at the end of its path, exact for
                // the path integral. Over many RK4 substeps the discrete map's
                // own slope differs by the discretization, and finite
                // differences straddle the irreversible gate switching at
                // stage points (0.01-1% in deep saturation), so only single-
                // substep offsets (what a transient step uses) are checked;
                // the long jumps are checked against Python's values above.
                // Within one substep the map's slope also differs from the
                // end point's by the step's discretization (~1% at 0.7 mT
                // past a saturated reversal), so check within 10 uT.
                if let Some([b, _, _]) = e.states.get(p)
                    && (v[0] * TESLA_PER_V - b).abs() > 1e-5
                {
                    continue;
                }
                // Right after a reversal from saturation the gate switches off
                // within a fraction of a millitesla: a kink in H(B) near the
                // state. Skip core points where the finite differences
                // themselves don't converge (d vs d / 4).
                if e.states.get(p).is_some() {
                    let fdq = |dd: f64| {
                        let (mut lo, mut hi) = (v.clone(), v.clone());
                        lo[k] -= dd;
                        hi[k] += dd;
                        (eval(&*dev, &hi).0[0] - eval(&*dev, &lo).0[0]) / (2.0 * dd)
                    };
                    let (f1, f4) = (fdq(d), fdq(d / 4.0));
                    if (f1 - f4).abs() > 1e-7 * f1.abs().max(f4.abs()) {
                        continue;
                    }
                }
                let rel = 1e-5;
                for j in 0..n {
                    let fd = (i_hi[j] - i_lo[j]) / (2.0 * d);
                    let an = g[j * n + k];
                    let tol = rel * an.abs().max(fd.abs()) + 1e-9 * scale;
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
