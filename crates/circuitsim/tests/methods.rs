//! The integration methods reach their orders of accuracy.
//!
//! A series RLC (f0 = 1.6 kHz, Q = 1) plus an RC, driven by a ramp: the input
//! is linear between samples, as every method assumes, so the error is the
//! method's own. The reference is radau5 at a 64x finer step.

use circuitsim::ir::{
    Capacitor, CircuitIr, Element, IR_VERSION, Inductor, Probe, Resistor, Section,
};
use circuitsim::{Method, Options, simulate};

fn circuit() -> CircuitIr {
    let r = |name: &str, a: &str, b: &str, r_ohm: f64| {
        Element::Resistor(Resistor {
            name: name.into(),
            a: a.into(),
            b: b.into(),
            r_ohm,
        })
    };
    let c = |name: &str, a: &str, b: &str, c_f: f64| {
        Element::Capacitor(Capacitor {
            name: name.into(),
            a: a.into(),
            b: b.into(),
            c_f,
            v0_v: None,
        })
    };
    CircuitIr {
        version: IR_VERSION,
        title: "rlc".into(),
        input_node: "in".into(),
        controls: vec![],
        noise: None,
        heaters: None,
        probes: vec![
            Probe::Voltage { node: "c".into() },
            Probe::Voltage { node: "o".into() },
        ],
        models: vec![],
        sections: vec![Section {
            title: "t".into(),
            elements: vec![
                r("R1", "in", "a", 100.0),
                Element::Inductor(Inductor {
                    name: "L1".into(),
                    a: "a".into(),
                    b: "c".into(),
                    l_h: 10e-3,
                }),
                c("C1", "c", "0", 1e-6),
                r("R2", "c", "o", 1e3),
                c("C2", "o", "0", 47e-9),
            ],
        }],
    }
}

/// Probe values at t = 0, h, ..., t_end for a 1 V/ms ramp.
fn run(method: Method, h: f64, t_end: f64) -> Vec<Vec<f64>> {
    let n = (t_end / h).round() as usize + 1;
    let input: Vec<f64> = (0..n).map(|i| 1e3 * i as f64 * h).collect();
    simulate(&circuit(), &input, h, &Options::with_method(method))
        .unwrap()
        .values
}

/// Max error over both probes against `reference` (sampled `ratio` times finer).
fn max_err(v: &[Vec<f64>], reference: &[Vec<f64>], ratio: usize) -> f64 {
    v.iter()
        .zip(reference)
        .flat_map(|(a, r)| {
            a.iter()
                .enumerate()
                .map(move |(i, x)| (x - r[i * ratio]).abs())
        })
        .fold(0.0, f64::max)
}

#[test]
fn methods_converge_at_their_order() {
    let (h, t_end) = (1.0 / 24_000.0, 3e-3);
    let reference = run(Method::Radau5, h / 64.0, t_end);
    for (name, order) in [
        ("euler", 1.0),
        ("trap", 2.0),
        ("trbdf2", 2.0),
        ("sdirk3", 3.0),
        ("esdirk4", 4.0),
        ("radau3", 3.0),
        ("radau5", 5.0),
    ] {
        let m = Method::parse(name).unwrap();
        let e1 = max_err(&run(m, h, t_end), &reference, 64);
        let e2 = max_err(&run(m, h / 2.0, t_end), &reference, 32);
        let e4 = max_err(&run(m, h / 4.0, t_end), &reference, 16);
        let (p1, p2) = ((e1 / e2).log2(), (e2 / e4).log2());
        eprintln!("{name:8} {e1:.2e} {e2:.2e} {e4:.2e}  order {p1:.2} {p2:.2}");
        assert!(
            (p2 - order).abs() < 0.35,
            "{name}: observed order {p2:.2}, expected {order}"
        );
    }
}
