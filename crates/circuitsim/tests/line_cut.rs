//! Link-line cuts (`partition::LineCut`, METHODOLOGY_REVIEW.md W1). Their agreement with
//! the Python reference is tests/test_line_cut.py; here what can be cut and that a cut the
//! one-sample couplings can't make runs stable.

use circuitsim::ir::{
    Capacitor, CircuitIr, Element, IR_VERSION, Inductor, Probe, Resistor, Section,
};
use circuitsim::partition::{Coupling, cuts, groups, simulate_partitioned};
use circuitsim::transient::{Method, Options};

fn r(name: &str, a: &str, b: &str, r_ohm: f64) -> Element {
    Element::Resistor(Resistor {
        name: name.into(),
        a: a.into(),
        b: b.into(),
        r_ohm,
    })
}

fn c(name: &str, a: &str, b: &str, c_f: f64) -> Element {
    Element::Capacitor(Capacitor {
        name: name.into(),
        a: a.into(),
        b: b.into(),
        c_f,
        v0_v: None,
    })
}

fn section(title: &str, elements: Vec<Element>) -> Section {
    Section {
        title: title.into(),
        substeps: None,
        decimate: None,
        owns: None,
        lag_samples: None,
        method: None,
        tube_tables: None,
        elements,
    }
}

fn circuit(a: Vec<Element>, b: Vec<Element>, probe: &str) -> CircuitIr {
    CircuitIr {
        version: IR_VERSION,
        title: "line cut".into(),
        input_node: "in".into(),
        controls: vec![],
        noise: None,
        heaters: None,
        probes: vec![Probe::Voltage { node: probe.into() }],
        models: vec![],
        sections: vec![section("A", a), section("B", b)],
    }
}

fn strings(v: &[&str]) -> Vec<String> {
    v.iter().map(|s| s.to_string()).collect()
}

#[test]
fn cut_entries_are_not_titles() {
    let list = strings(&["a", "cut:C1", "|", "b", "cut:L2"]);
    assert_eq!(groups(&list), vec![strings(&["a"]), strings(&["b"])]);
    assert_eq!(cuts(&list), strings(&["C1", "L2"]));
    assert!(groups(&strings(&["cut:C1"])).is_empty());
}

#[test]
fn what_can_be_cut_is_checked() {
    let ir = circuit(
        vec![
            r("R1", "in", "s", 1e3),
            c("C1", "s", "0", 1e-6),
            c("CX", "in", "s", 1e-9),
        ],
        vec![
            r("R2", "s", "t", 1e3),
            Element::Inductor(Inductor {
                name: "L1".into(),
                a: "t".into(),
                b: "u".into(),
                l_h: 1e-3,
            }),
            r("R3", "u", "0", 1e3),
        ],
        "s",
    );
    let x = vec![0.0; 4];
    let opts = Options::with_method(Method::TrBdf2);
    let run = |list: &[&str]| {
        simulate_partitioned(
            &ir,
            &strings(list),
            Coupling::Hold,
            &x,
            1e-5,
            &opts,
            1,
            |_| Ok(()),
        )
        .map(|_| ())
        .unwrap_err()
        .0
    };
    assert!(run(&["B", "cut:R1"]).contains("only a capacitor to ground"));
    assert!(run(&["B", "cut:CX"]).contains("only a capacitor to ground"));
    assert!(run(&["B", "cut:C9"]).contains("no element C9"));
    // L1's nodes are both B's.
    assert!(run(&["B", "cut:L1"]).contains("two different parts"));
    assert!(run(&["B", "cut:C1", "cut:C1"]).contains("cut twice"));
}

/// E3's hard case: a fast node (its time constant a third of a sample) behind a stiff
/// source, cut at its capacitor. The line runs stable and repeatably, close to the one solve
/// (trbdf2, the draft's method).
#[test]
fn a_fast_node_cut_as_a_line_is_stable() {
    let h = 1.0 / 96_000.0;
    let tau = 0.3 * h;
    let (r1, r2) = (100.0, 10e3);
    let cap = tau / (r1 * r2 / (r1 + r2));
    let ir = circuit(
        vec![r("R1", "in", "s", r1), c("C1", "s", "0", cap)],
        vec![r("R2", "s", "0", r2)],
        "s",
    );
    let n = 9600;
    let x: Vec<f64> = (0..n)
        .map(|k| (2.0 * std::f64::consts::PI * 1000.0 * k as f64 * h).sin())
        .collect();
    let opts = Options {
        input_order: 1,
        ..Options::with_method(Method::TrBdf2)
    };
    let one = circuitsim::simulate(&ir, &x, h, &opts).unwrap();
    let list = strings(&["B", "cut:C1"]);
    let run = || {
        simulate_partitioned(&ir, &list, Coupling::Extrapolate, &x, h, &opts, 1, |_| {
            Ok(())
        })
        .unwrap()
    };
    let (a, b) = (run(), run());
    assert!(
        a.values[0]
            .iter()
            .zip(&b.values[0])
            .all(|(p, q)| p.to_bits() == q.to_bits())
    );
    let (y, y1) = (&a.values[0], &one.values[0]);
    let level = (y1.iter().map(|v| v * v).sum::<f64>() / n as f64).sqrt();
    let diff = (y
        .iter()
        .zip(y1)
        .map(|(p, q)| (p - q) * (p - q))
        .sum::<f64>()
        / n as f64)
        .sqrt();
    println!("line vs one solve: {:.1} dB", 20.0 * (diff / level).log10());
    assert!(y.iter().all(|v| v.abs() < 2.0), "bounded");
    assert!(diff < 0.01 * level, "{diff} vs {level}");
}
