//! Parameter changes mid-run (`Transient::update`): the state carries over
//! and the integration restarts from it, on both solvers.

use std::fs;
use std::path::Path;
use std::time::Instant;

use circuitsim::ir::{Capacitor, CircuitIr, Element, IR_VERSION, Probe, Resistor, Section};
use circuitsim::mna::Mna;
use circuitsim::transient::{Method, Options, Solver, Transient};

fn fixture(name: &str) -> CircuitIr {
    let path = Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("tests")
        .join("fixtures")
        .join(name);
    CircuitIr::from_json(&fs::read_to_string(path).expect(name)).unwrap()
}

/// in -- R -- out -- C -- 0
fn rc(r_ohm: f64) -> CircuitIr {
    CircuitIr {
        version: IR_VERSION,
        title: "rc".into(),
        input_node: "in".into(),
        controls: vec![],
        noise: None,
        heaters: None,
        probes: vec![Probe::Voltage { node: "out".into() }],
        models: vec![],
        sections: vec![Section {
            title: "t".into(),
            elements: vec![
                Element::Resistor(Resistor {
                    name: "R1".into(),
                    a: "in".into(),
                    b: "out".into(),
                    r_ohm,
                }),
                Element::Capacitor(Capacitor {
                    name: "C1".into(),
                    a: "out".into(),
                    b: "0".into(),
                    c_f: 1e-6,
                    v0_v: None,
                }),
            ],
        }],
    }
}

/// The output node's voltage (the probe's unknown).
fn out(tr: &Transient) -> f64 {
    let i = tr.mna().probes[0].1.unwrap();
    tr.x()[i]
}

/// 1 V into an RC whose R switches from 1k to 3k at t1: the capacitor
/// voltage is continuous and relaxes with the new time constant. (The input
/// rises linearly over the first step, as every input does between samples.)
#[test]
fn switching_a_resistor_follows_the_closed_form() {
    let h = 1e-6;
    let (t1, t_end) = (0.5e-3, 3e-3);
    for solver in [Solver::Dk, Solver::Mna] {
        let opts = Options {
            solver,
            ..Options::with_method(Method::Esdirk4)
        };
        let mna = Mna::from_ir(&rc(1e3), opts.gmin).unwrap();
        let mut tr = Transient::new(mna, h, opts, 0.0).unwrap();
        let mut worst = 0.0f64;
        let n1 = (t1 / h).round() as usize;
        for i in 1..=(t_end / h).round() as usize {
            if i == n1 + 1 {
                tr.update(&rc(3e3)).unwrap();
            }
            tr.step(1.0).unwrap();
            let t = i as f64 * h;
            // A ramp to 1 V over [0, h], then 1 V: for t >= h,
            // v = 1 - (tau / h) (exp(h / tau) - 1) exp(-t / tau).
            let tau = 1e-3;
            let ramp = tau / h * ((h / tau).exp() - 1.0);
            let want = if i <= n1 {
                1.0 - ramp * (-t / tau).exp()
            } else {
                let v1 = 1.0 - ramp * (-t1 / tau).exp();
                1.0 - (1.0 - v1) * (-(t - t1) / 3e-3).exp()
            };
            worst = worst.max((out(&tr) - want).abs());
        }
        println!("{solver:?}: {worst:.1e} V from the closed form");
        assert!(worst < 1e-9, "{solver:?}: {worst:e} V");
    }
}

/// in -- 10k -- p -- 0.22 uF -- t -- R_end -- w -- 22k -- 0: a pot's end segment
/// (R_end) between a series capacitor and the rest of the circuit, as the tube
/// filter's RESONANCE pot sits.
fn pot_end(r_end_ohm: f64) -> CircuitIr {
    let r = |name: &str, a: &str, b: &str, r_ohm: f64| {
        Element::Resistor(Resistor {
            name: name.into(),
            a: a.into(),
            b: b.into(),
            r_ohm,
        })
    };
    CircuitIr {
        version: IR_VERSION,
        title: "pot end".into(),
        input_node: "in".into(),
        controls: vec![],
        noise: None,
        heaters: None,
        probes: vec![Probe::Voltage { node: "w".into() }],
        models: vec![],
        sections: vec![Section {
            title: "t".into(),
            elements: vec![
                r("R1", "in", "p", 10e3),
                Element::Capacitor(Capacitor {
                    name: "C1".into(),
                    a: "p".into(),
                    b: "t".into(),
                    c_f: 0.22e-6,
                    v0_v: None,
                }),
                r("RQ", "t", "w", r_end_ohm),
                r("RFB", "w", "0", 22e3),
            ],
        }],
    }
}

/// A pot's section dropped from 1 kOhm to its 1 mOhm end in one update, against
/// the same change a decade per sample: the same run within millivolts. (Before
/// the first-order restart, the derivative at the carried point, ~100 A through
/// 1 mOhm, came out as a thump of volts: DEVICE_BUILDER_PLAN.md B6, "Pot end stop".)
#[test]
fn a_pot_thrown_to_its_end_next_to_a_capacitor_stays_quiet() {
    let h = 1.0 / 96_000.0;
    let input: Vec<f64> = (0..960)
        .map(|i| (2.0 * std::f64::consts::PI * 220.0 * i as f64 * h).sin())
        .collect();
    let at = 400;
    let ends = [1e3, 1e2, 1e1, 1.0, 0.1, 0.01, 1e-3];
    let decades: Vec<(usize, CircuitIr)> = ends[1..]
        .iter()
        .enumerate()
        .map(|(k, &r)| (at + k, pot_end(r)))
        .collect();
    for solver in [Solver::Dk, Solver::Mna] {
        for method in [Method::TrBdf2, Method::Esdirk4, Method::Trapezoidal] {
            let opts = Options {
                solver,
                ..Options::with_method(method)
            };
            let probe = Mna::from_ir(&pot_end(1e3), opts.gmin).unwrap().probes[0]
                .1
                .unwrap();
            let once = run(&pot_end(1e3), &[(at, pot_end(1e-3))], &input, h, opts);
            let gradual = run(&pot_end(1e3), &decades, &input, h, opts);
            let peak = |xs: &[Vec<f64>]| xs.iter().map(|x| x[probe].abs()).fold(0.0, f64::max);
            let worst = once
                .iter()
                .zip(&gradual)
                .skip(at + ends.len())
                .map(|(a, b)| (a[probe] - b[probe]).abs())
                .fold(0.0, f64::max);
            println!(
                "{solver:?} {method:?}: peak {:.4} V (gradual {:.4} V), then within {worst:.1e} V",
                peak(&once),
                peak(&gradual)
            );
            assert!(peak(&once) < 1.05 * peak(&gradual), "{solver:?} {method:?}");
            assert!(worst < 2e-3, "{solver:?} {method:?}: {worst:e} V");
        }
    }
}

/// A 1 kHz tone at 0 dBFS (13.8 V at the 670's input), faded in over 1 ms.
fn tone(n: usize, h: f64) -> Vec<f64> {
    (0..n)
        .map(|i| {
            let t = i as f64 * h;
            13.8 * (t / 1e-3).min(1.0) * (2.0 * std::f64::consts::PI * 1000.0 * t).sin()
        })
        .collect()
}

/// Run `ir` through `input`, switching to each `(sample, circuit)` of
/// `updates` on the way; every unknown at every sample.
fn run(
    ir: &CircuitIr,
    updates: &[(usize, CircuitIr)],
    input: &[f64],
    h: f64,
    opts: Options,
) -> Vec<Vec<f64>> {
    let mna = Mna::from_ir(ir, opts.gmin).unwrap();
    let mut tr = Transient::new(mna, h, opts, input[0]).unwrap();
    let mut xs = vec![tr.x().to_vec()];
    for (i, &u) in input.iter().enumerate().skip(1) {
        for (_, then) in updates.iter().filter(|(at, _)| *at == i) {
            tr.update(then).unwrap();
        }
        tr.step(u).unwrap();
        xs.push(tr.x().to_vec());
    }
    xs
}

/// A knob turned from `a` a fraction `reach` of the way to `b` over `steps`
/// samples from sample `at`: every resistor whose value differs moves
/// linearly (a pot's two halves keep their sum as its wiper travels).
fn sweep(
    a: &CircuitIr,
    b: &CircuitIr,
    reach: f64,
    at: usize,
    steps: usize,
) -> Vec<(usize, CircuitIr)> {
    (1..=steps)
        .map(|k| {
            let f = reach * k as f64 / steps as f64;
            let mut ir = a.clone();
            for (sa, sb) in ir.sections.iter_mut().zip(&b.sections) {
                for (ea, eb) in sa.elements.iter_mut().zip(&sb.elements) {
                    if let (Element::Resistor(ra), Element::Resistor(rb)) = (ea, eb) {
                        ra.r_ohm = ra.r_ohm * (1.0 - f) + rb.r_ohm * f;
                    }
                }
            }
            (at + k - 1, ir)
        })
        .collect()
}

/// Worst difference over every unknown and sample, relative to the Newton
/// tolerance on it, skipping T104's floating secondary (see tests/dk.rs).
fn worst(a: &[Vec<f64>], b: &[Vec<f64>], ir: &CircuitIr, opts: &Options) -> f64 {
    let unknowns = Mna::from_ir(ir, opts.gmin).unwrap().unknowns;
    let floating = ["node ay", "node bk", "node T104_s_l"];
    let skip: Vec<bool> = unknowns
        .iter()
        .map(|u| floating.contains(&u.describe().as_str()))
        .collect();
    let (mut w, mut at) = (0.0f64, 0);
    for (x, y) in a.iter().zip(b) {
        for (j, ((p, q), &s)) in x.iter().zip(y).zip(&skip).enumerate() {
            if !s {
                let tol = opts.reltol * p.abs().max(q.abs()) + opts.vntol;
                let e = (p - q).abs() / tol;
                if e > w {
                    (w, at) = (e, j);
                }
            }
        }
    }
    println!("  worst at the {}", unknowns[at].describe());
    w
}

#[test]
fn updating_to_the_same_circuit_barely_changes_the_run() {
    let ir = fixture("default.json");
    let h = 1.0 / 192_000.0;
    let input = tone(1152, h);
    let opts = Options::with_method(Method::Esdirk4);
    let plain = run(&ir, &[], &input, h, opts);
    let updated = run(&ir, &[(400, ir.clone())], &input, h, opts);
    // The restart starts the sample with backward Euler over h / 256 and doesn't
    // extrapolate the first guess. Measured: within 0.2 tolerance before the
    // power supply went in; 5.2 since (main plan Phase 3, 2026-10-21), at the
    // 6973 feedback node nfb (47k into 20 pF, behind a pentode idling near
    // cutoff), which is the most sensitive node since; 24.3 with the
    // first-order restart (2026-10-30; 86 with it over h / 64). At the output
    // that is -122 dB peak re the signal at 10 kHz (production).
    let w = worst(&plain, &updated, &ir, &opts);
    println!("same circuit: {w:.2} x tolerance");
    assert!(w < 40.0, "{w}");
}

/// Time Constant 2 (default) to 1 mid-run, and the pots (input attenuator,
/// thresholds) swept 90% of the way from their defaults to the other end
/// over 32 samples, and thrown to their ends at once. Measured: within 0.13
/// tolerance (thrown: 0.21 with trapezoidal, 0.03 with ESDIRK4).
///
/// Thrown to the end at once (pot sections from kOhms to their 1 mOhm ends in
/// one update), Newton didn't converge in either solver before the first-order
/// restart (2026-10-30): the derivative carried in across the change was ~100 A
/// through 1 mOhm (DEVICE_BUILDER_PLAN.md B6, "Pot end stop").
#[test]
fn dk_and_full_mna_agree_through_a_switch() {
    let h = 1.0 / 192_000.0;
    let input = tone(1152, h);
    let a = fixture("default.json");
    let cases = [
        ("TC 2 -> 1", vec![(500, fixture("tc1.json"))]),
        (
            "pots swept",
            sweep(&a, &fixture("pots_max.json"), 0.9, 500, 32),
        ),
        ("pots thrown", vec![(500, fixture("pots_max.json"))]),
    ];
    for (name, updates) in &cases {
        for method in [Method::Trapezoidal, Method::Esdirk4] {
            let opts = Options {
                newton_reuse: false,
                ..Options::with_method(method)
            };
            let solver = |solver| Options { solver, ..opts };
            let mna = run(&a, updates, &input, h, solver(Solver::Mna));
            let dk = run(&a, updates, &input, h, solver(Solver::Dk));
            let w = worst(&mna, &dk, &a, &opts);
            println!("{name} {method:?}: {w:.3} x tolerance");
            assert!(w < 1.0, "{name} {method:?}: {w}");
        }
    }
}

/// A switch position that adds nodes (Time Constant 6's extra RC network,
/// the input pad's 0 dB end) is a different circuit: refused. Switching
/// between such positions while running is M8's (crossfading runs).
#[test]
fn a_switch_position_with_other_nodes_is_refused() {
    let opts = Options::default();
    let mna = Mna::from_ir(&fixture("default.json"), opts.gmin).unwrap();
    let mut tr = Transient::new(mna, 1e-6, opts, 0.0).unwrap();
    for other in ["tc6.json", "pots_min.json"] {
        let e = tr.update(&fixture(other)).unwrap_err().to_string();
        assert!(e.contains("nodes"), "{other}: {e}");
    }
    // A device moved to other nodes.
    let mut moved = fixture("default.json");
    for s in &mut moved.sections {
        for e in &mut s.elements {
            if let Element::Device(d) = e
                && d.name == "XV105A"
            {
                d.nodes.swap(0, 1);
            }
        }
    }
    let e = tr.update(&moved).unwrap_err().to_string();
    assert!(e.contains("devices"), "{e}");
}

/// What a knob change costs on the 670: rebuilding the matrices, and the
/// first step after it (which builds the DK system for the step size).
/// Printed, and bounded loosely.
#[test]
fn recomputation_cost_on_the_670() {
    let a = fixture("default.json");
    let b = sweep(&a, &fixture("pots_max.json"), 0.9, 0, 32)
        .swap_remove(0)
        .1;
    let h = 1.0 / 192_000.0;
    let opts = Options::with_method(Method::Esdirk4);
    let mut tr = Transient::new(Mna::from_ir(&a, opts.gmin).unwrap(), h, opts, 0.0).unwrap();
    for _ in 0..10 {
        tr.step(0.0).unwrap();
    }
    let t = Instant::now();
    tr.update(&b).unwrap();
    let update_ms = t.elapsed().as_secs_f64() * 1e3;
    let t = Instant::now();
    tr.step(0.0).unwrap();
    let step_ms = t.elapsed().as_secs_f64() * 1e3;
    println!("update {update_ms:.2} ms, first step after it {step_ms:.2} ms");
    assert!(update_ms + step_ms < 50.0);
}
