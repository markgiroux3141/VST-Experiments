//! Newton on circuits with devices: operating points against KCL with the
//! device equations, convergence of the transient, and the robustness
//! machinery (limiting, step halving, DC homotopies, failure reports).
//! ngspice agreement is tested from Python (tests/test_circuitsim_nonlinear.py).

use std::f64::consts::PI;

use circuitsim::devices::{JunctionDiode as Jd, Triode as Tr};
use circuitsim::ir::{
    CircuitIr, Device, DeviceModel, Element, IR_VERSION, JunctionDiode, KorenTriode, PlateModel,
    Probe, Resistor, Section, Triode, VoltageSource,
};
use circuitsim::{Options, mna::SPICE_GMIN, simulate};

fn r(name: &str, a: &str, b: &str, r_ohm: f64) -> Element {
    Element::Resistor(Resistor {
        name: name.into(),
        a: a.into(),
        b: b.into(),
        r_ohm,
    })
}

fn c(name: &str, a: &str, b: &str, c_f: f64) -> Element {
    Element::Capacitor(circuitsim::ir::Capacitor {
        name: name.into(),
        a: a.into(),
        b: b.into(),
        c_f,
        v0_v: None,
    })
}

fn v(name: &str, pos: &str, dc_v: f64) -> Element {
    Element::VoltageSource(VoltageSource {
        name: name.into(),
        pos: pos.into(),
        neg: "0".into(),
        dc_v,
    })
}

fn dev(name: &str, model: &str, nodes: &[&str]) -> Element {
    Element::Device(Device {
        name: name.into(),
        model: model.into(),
        nodes: nodes.iter().map(|n| n.to_string()).collect(),
    })
}

fn circuit(models: Vec<DeviceModel>, elements: Vec<Element>, probes: &[&str]) -> CircuitIr {
    let ir = CircuitIr {
        version: IR_VERSION,
        title: "test".into(),
        input_node: "in".into(),
        controls: vec![],
        noise: None,
        heaters: None,
        probes: probes
            .iter()
            .map(|n| Probe::Voltage {
                node: n.to_string(),
            })
            .collect(),
        models,
        sections: vec![Section {
            title: "test".into(),
            elements,
        }],
    };
    ir.validate().expect("valid test circuit");
    ir
}

/// A steep diode (no series resistance, Is = 1e-14) and the provisional
/// 1N4007-like one of the 670 bridge.
fn steep_diode() -> JunctionDiode {
    JunctionDiode {
        name: "DSTEEP".into(),
        is_a: 1e-14,
        n: 1.0,
        rs_ohm: 0.0,
    }
}

fn rectifier_diode() -> JunctionDiode {
    JunctionDiode {
        name: "DRECT".into(),
        is_a: 7e-9,
        n: 1.8,
        rs_ohm: 0.034,
    }
}

/// Koren's published 12AX7 parameters (test values only).
fn koren_12ax7() -> Triode {
    Triode {
        name: "T".into(),
        plate: PlateModel::Koren(KorenTriode {
            mu: 100.0,
            ex: 1.4,
            kg1: 1060.0,
            kp: 600.0,
            kvb: 300.0,
        }),
        grid: Some(circuitsim::ir::GridCurrent {
            perveance: 1e-3,
            contact_v: -0.7,
            smooth_v: 0.05,
        }),
        c_gk: 1.6e-12,
        c_gp: 1.7e-12,
        c_pk: 0.46e-12,
    }
}

/// in -- R -- a -- D -- 0
fn diode_r(d: JunctionDiode) -> (CircuitIr, f64) {
    let name = d.name.clone();
    let ir = circuit(
        vec![DeviceModel::JunctionDiode(d)],
        vec![r("R1", "in", "a", 1e3), dev("D1", &name, &["a", "0"])],
        &["a"],
    );
    (ir, 1e3)
}

/// KCL residual allowed, relative to the drive current. Newton stops once the
/// last update is within reltol (1e-6) of the voltage, which leaves about
/// (1e-6 V)^2 / Vt of error on a conducting junction: up to ~1e-10 of the
/// current through it (measured on the steep diode at 1 A).
const KCL_RTOL: f64 = 1e-9;

#[test]
fn diode_operating_point_satisfies_kcl() {
    for d in [steep_diode(), rectifier_diode()] {
        let model = Jd::new(&d);
        let (ir, rr) = diode_r(d);
        for u in [-20.0, 0.0, 0.3, 5.0, 100.0] {
            let out = simulate(&ir, &[u], 1e-6, &Options::default()).unwrap();
            let va = out.values[0][0];
            let (id, _) = model.current(va);
            let residual = (u - va) / rr - id - SPICE_GMIN * va;
            assert!(
                residual.abs() <= KCL_RTOL * (u.abs() / rr).max(1e-12),
                "u={u}: va={va}, residual {residual:e}"
            );
            // Limiting keeps even the steep diode at 100 V to a few iterations.
            assert_eq!(out.stats.dc_method, "newton");
            assert!(out.stats.dc_iterations < 40, "{:?}", out.stats);
        }
    }
}

/// Common-cathode triode stage: B+ 250 V, 100k plate load, 1.5k cathode
/// resistor, grid to the input through 1 MOhm.
fn triode_stage() -> CircuitIr {
    circuit(
        vec![DeviceModel::Triode(koren_12ax7())],
        vec![
            v("VB", "bp", 250.0),
            r("RP", "bp", "p", 100e3),
            r("RG", "in", "g", 1e6),
            r("RK", "k", "0", 1.5e3),
            c("CK", "k", "0", 22e-6),
            dev("XV1", "T", &["p", "g", "k"]),
        ],
        &["p", "g", "k"],
    )
}

#[test]
fn triode_operating_point_satisfies_kcl() {
    let ir = triode_stage();
    let DeviceModel::Triode(t) = &ir.models[0] else {
        unreachable!()
    };
    let tube = Tr::new(t);
    for u in [-5.0, 0.0, 2.0] {
        let out = simulate(&ir, &[u], 1e-6, &Options::default()).unwrap();
        let (p, g, k) = (out.values[0][0], out.values[1][0], out.values[2][0]);
        let (ip, _, _) = tube.plate(g - k, p - k);
        let (ig, _) = tube.grid(g - k);
        let plate = (250.0 - p) / 100e3 - ip;
        let grid = (u - g) / 1e6 - ig;
        let cathode = ip + ig - k / 1.5e3;
        for (what, res) in [("plate", plate), ("grid", grid), ("cathode", cathode)] {
            assert!(
                res.abs() < KCL_RTOL * ip.max(1e-6),
                "u={u}: {what} KCL residual {res:e} (p={p}, g={g}, k={k}, ip={ip:e})"
            );
        }
        // A sane bias point: the tube conducts and the plate sits mid-supply.
        if u == 0.0 {
            assert!(p > 100.0 && p < 220.0 && k > 0.5 && k < 3.0, "p={p}, k={k}");
        }
    }
}

/// Half-wave rectifier into an RC load, against itself at a 16x finer step:
/// second-order convergence survives the diode switching.
#[test]
fn rectifier_transient_converges_at_second_order() {
    let d = rectifier_diode();
    let name = d.name.clone();
    let ir = circuit(
        vec![DeviceModel::JunctionDiode(d)],
        vec![
            r("RS", "in", "a", 10.0),
            dev("D1", &name, &["a", "out"]),
            c("C1", "out", "0", 10e-6),
            r("RL", "out", "0", 1e3),
        ],
        &["out"],
    );
    let (f, t_end) = (1e3, 3e-3);
    let run = |h: f64| {
        let n = (t_end / h).round() as usize + 1;
        let x: Vec<f64> = (0..n)
            .map(|i| 10.0 * (2.0 * PI * f * i as f64 * h).sin())
            .collect();
        simulate(&ir, &x, h, &Options::default()).unwrap()
    };
    let h = 1.0 / 192e3;
    let reference = run(h / 16.0);
    let err = |k: usize| {
        let out = run(h / k as f64);
        let stride = 16 / k;
        out.values[0]
            .iter()
            .zip(reference.values[0].iter().step_by(stride))
            .map(|(a, b)| (a - b).abs())
            .fold(0.0, f64::max)
    };
    let (e1, e2) = (err(1), err(2));
    let peak = reference.values[0]
        .iter()
        .fold(0.0f64, |m, x| m.max(x.abs()));
    assert!(peak > 8.0, "the rectifier charges the capacitor ({peak} V)");
    assert!(e1 < 1e-2 * peak, "error {e1:e} at h");
    let ratio = e2 / e1;
    assert!(
        (0.15..0.35).contains(&ratio),
        "h/2 error ratio {ratio} (expect ~1/4)"
    );
}

/// A 0 -> 100 V input step onto the steep diode. Newton needs 8 iterations
/// for it at full size and at most 7 for each half (measured), so with 7
/// allowed the step must be halved; the result still satisfies KCL.
///
/// Halving helps a junction only so far: each substep that turns the diode
/// further on still needs ~7 iterations, because the linearized step
/// overshoots the exponential by more than Vt for any input step much larger
/// than Vt. With 6 allowed, even 256 substeps don't converge.
#[test]
fn hard_steps_are_halved_and_failures_name_time_and_device() {
    let d = steep_diode();
    let model = Jd::new(&d);
    let (ir, rr) = diode_r(d);
    let opts = Options {
        max_iter: 7,
        ..Options::default()
    };
    let out = simulate(&ir, &[0.0, 100.0, 100.0], 1e-6, &opts).unwrap();
    assert!(out.stats.halved_steps >= 1, "{:?}", out.stats);
    assert!(out.stats.substeps >= 2, "{:?}", out.stats);
    let va = out.values[0][2];
    let residual = (100.0 - va) / rr - model.current(va).0 - SPICE_GMIN * va;
    assert!(residual.abs() < KCL_RTOL * 0.1, "{residual:e}");

    // Without halvings the same step fails, and says where.
    let opts = Options {
        max_iter: 3,
        max_halvings: 0,
        ..Options::default()
    };
    let e = simulate(&ir, &[0.0, 100.0], 1e-6, &opts)
        .unwrap_err()
        .to_string();
    for want in ["t = 1.0", "sample 1", "node a", "D1.a", "did not converge"] {
        assert!(e.contains(want), "{want:?} missing from: {e}");
    }
}

#[test]
fn dc_falls_back_to_homotopies() {
    let (ir, rr) = diode_r(steep_diode());
    let model = Jd::new(&steep_diode());
    // Too few iterations for plain Newton from 0 V to a 1000 V drive.
    let opts = Options {
        max_iter_dc: 6,
        ..Options::default()
    };
    let out = simulate(&ir, &[1000.0], 1e-6, &opts).unwrap();
    assert_ne!(out.stats.dc_method, "newton", "{:?}", out.stats);
    let va = out.values[0][0];
    let residual = (1000.0 - va) / rr - model.current(va).0 - SPICE_GMIN * va;
    assert!(residual.abs() < KCL_RTOL * 1.0, "{residual:e}");

    // Hopeless: a single iteration can't even do the homotopy steps.
    let opts = Options {
        max_iter_dc: 1,
        ..Options::default()
    };
    let e = simulate(&ir, &[1000.0], 1e-6, &opts)
        .unwrap_err()
        .to_string();
    assert!(
        e.contains("DC operating point") && e.contains("D1.a"),
        "{e}"
    );
}

/// The triode stage as an amplifier: about -mu Rp / (Rp + rp) of gain with
/// the cathode bypassed (Koren 12AX7: |A| ~ 60 here), inverted.
#[test]
fn triode_stage_amplifies_and_inverts() {
    let ir = triode_stage();
    let h = 1.0 / 192e3;
    let n = 960; // 5 ms
    let x: Vec<f64> = (0..n)
        .map(|i| 0.01 * (2.0 * PI * 1e3 * i as f64 * h).sin())
        .collect();
    let out = simulate(&ir, &x, h, &Options::default()).unwrap();
    let p = &out.values[0];
    let tail = n / 2;
    let (x_t, p_t) = (&x[tail..], &p[tail..]);
    let mean = p_t.iter().sum::<f64>() / p_t.len() as f64;
    let corr: f64 = x_t.iter().zip(p_t).map(|(a, b)| a * (b - mean)).sum();
    let gain = corr / x_t.iter().map(|a| a * a).sum::<f64>();
    assert!((-80.0..-40.0).contains(&gain), "gain {gain}");
    assert!(out.stats.max_iterations <= 4, "{:?}", out.stats);
}
