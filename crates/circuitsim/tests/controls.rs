//! Control inputs (`CircuitIr::controls`, the tube synth's S3): nodes driven by their
//! own samples beside the audio input, linear between samples.

use circuitsim::ir::{
    Capacitor, CircuitIr, Control, Element, IR_VERSION, Probe, Resistor, Section,
};
use circuitsim::partition::{Coupling, simulate_partitioned_controls};
use circuitsim::stream::Stream;
use circuitsim::transient::{Method, Options, simulate_controls};

fn resistor(name: &str, a: &str, b: &str, r_ohm: f64) -> Element {
    Element::Resistor(Resistor {
        name: name.into(),
        a: a.into(),
        b: b.into(),
        r_ohm,
    })
}

fn capacitor(name: &str, a: &str, b: &str, c_f: f64) -> Element {
    Element::Capacitor(Capacitor {
        name: name.into(),
        a: a.into(),
        b: b.into(),
        c_f,
        v0_v: None,
    })
}

/// The audio input into one RC (in -- 1k -- a -- 1 uF), a control `gate` into another
/// (gate -- 1k -- out -- 1 uF), the two joined by 10 MOhm; a second section on its own
/// (supply -- 10k -- out2 -- 10 uF, tied to `out` by 1 MOhm) to partition across.
fn circuit() -> CircuitIr {
    let ir = CircuitIr {
        version: IR_VERSION,
        title: "controls".into(),
        input_node: "in".into(),
        controls: vec![Control {
            name: "gate".into(),
            node: "g".into(),
        }],
        noise: None,
        probes: ["out", "a", "out2"]
            .iter()
            .map(|n| Probe::Voltage { node: (*n).into() })
            .collect(),
        models: vec![],
        sections: vec![
            Section {
                title: "audio".into(),
                elements: vec![
                    resistor("R1", "in", "a", 1e3),
                    capacitor("C1", "a", "0", 1e-6),
                    resistor("R2", "g", "out", 1e3),
                    capacitor("C2", "out", "0", 1e-6),
                    resistor("RJ", "a", "out", 1e7),
                    resistor("RT", "out", "out2", 1e6),
                ],
            },
            Section {
                title: "other".into(),
                elements: vec![
                    capacitor("C3", "out2", "0", 10e-6),
                    resistor("R3", "out2", "0", 1e5),
                ],
            },
        ],
    };
    ir.validate().unwrap();
    ir
}

fn opts() -> Options {
    Options {
        method: Method::Esdirk4,
        ..Options::default()
    }
}

const H: f64 = 1.0 / 96_000.0;

/// A gate low for 100 samples, then high (1 V), with silence on the audio input.
fn gate(n: usize) -> (Vec<f64>, Vec<f64>) {
    let g = (0..n).map(|i| if i < 100 { 0.0 } else { 1.0 }).collect();
    (vec![0.0; n], g)
}

#[test]
fn a_control_drives_its_node() {
    let n = 2000;
    let (x, g) = gate(n);
    let out = simulate_controls(&circuit(), &x, &[&g], H, &opts(), usize::MAX, |_| Ok(())).unwrap();
    let v = &out.values[out.names.iter().position(|s| s == "v(out)").unwrap()];
    // The gate ramps from 0 to 1 V over sample 99 -> 100: the RC's response to a ramp
    // of one sample, then 1 - exp(-t / tau) (tau 1 ms; 1 MOhm to out2 and 10 MOhm to
    // `a` lower the final value by ~0.1%).
    let tau = 1e-3;
    let ramp = |t: f64| {
        // response to a unit ramp over [0, H] (t from the ramp's start)
        let r = |t: f64| {
            if t <= 0.0 {
                0.0
            } else {
                t - tau * (1.0 - (-t / tau).exp())
            }
        };
        (r(t) - r(t - H)) / H
    };
    let mut worst = 0.0f64;
    for (i, &y) in v.iter().enumerate().skip(99) {
        let t = (i - 99) as f64 * H;
        worst = worst.max((y - ramp(t)).abs());
    }
    assert!(v[..99].iter().all(|y| y.abs() < 1e-12), "{:?}", &v[..5]);
    assert!(worst < 3e-3, "{worst}");
    let a = &out.values[out.names.iter().position(|s| s == "v(a)").unwrap()];
    assert!(
        a.iter().all(|y| y.abs() < 1e-3),
        "the audio side stays quiet"
    );
}

#[test]
fn a_stream_equals_the_whole_run() {
    let n = 3000;
    let (x, g) = gate(n);
    let whole =
        simulate_controls(&circuit(), &x, &[&g], H, &opts(), usize::MAX, |_| Ok(())).unwrap();
    let mut s =
        Stream::with_controls(&circuit(), &[], Coupling::Hold, H, &opts(), x[0], &[g[0]]).unwrap();
    let mut got: Vec<Vec<f64>> = s.initial().into_iter().map(|v| vec![v]).collect();
    for (a, b) in [(1, 480), (480, 1001), (1001, n)] {
        for (v, y) in got
            .iter_mut()
            .zip(s.process_with(&x[a..b], &[&g[a..b]]).unwrap())
        {
            v.extend(y);
        }
    }
    for (v, y) in got.iter_mut().zip(s.finish().unwrap()) {
        v.extend(y);
    }
    assert_eq!(got, whole.values);
}

#[test]
fn a_held_control_keeps_its_last_value() {
    let n = 1000;
    let (x, g) = gate(n);
    let whole =
        simulate_controls(&circuit(), &x, &[&g], H, &opts(), usize::MAX, |_| Ok(())).unwrap();
    let mut s =
        Stream::with_controls(&circuit(), &[], Coupling::Hold, H, &opts(), x[0], &[g[0]]).unwrap();
    let mut got: Vec<Vec<f64>> = s.initial().into_iter().map(|v| vec![v]).collect();
    // Up to the step with the gate, then without: it holds 1 V.
    for (v, y) in got
        .iter_mut()
        .zip(s.process_with(&x[1..200], &[&g[1..200]]).unwrap())
    {
        v.extend(y);
    }
    for (v, y) in got.iter_mut().zip(s.process(&x[200..]).unwrap()) {
        v.extend(y);
    }
    for (v, y) in got.iter_mut().zip(s.finish().unwrap()) {
        v.extend(y);
    }
    assert_eq!(got, whole.values);
}

#[test]
fn a_partitioned_run_takes_controls() {
    let n = 2000;
    let (x, g) = gate(n);
    let whole =
        simulate_controls(&circuit(), &x, &[&g], H, &opts(), usize::MAX, |_| Ok(())).unwrap();
    let part = simulate_partitioned_controls(
        &circuit(),
        &["other".into()],
        Coupling::Extrapolate,
        &x,
        &[&g],
        H,
        &opts(),
        500,
        |_| Ok(()),
    )
    .unwrap();
    let i = whole.names.iter().position(|s| s == "v(out)").unwrap();
    let j = part.names.iter().position(|s| s == "v(out)").unwrap();
    let err = whole.values[i]
        .iter()
        .zip(&part.values[j])
        .map(|(a, b)| (a - b).abs())
        .fold(0.0, f64::max);
    assert!(err < 1e-4, "{err}");
    // A control's node must stay in the first partition.
    assert!(
        simulate_partitioned_controls(
            &circuit(),
            &["audio".into()],
            Coupling::Hold,
            &x,
            &[&g],
            H,
            &opts(),
            500,
            |_| Ok(())
        )
        .is_err()
    );
}

#[test]
fn controls_round_trip_and_are_checked() {
    let ir = circuit();
    let back = CircuitIr::from_json(&ir.to_json()).unwrap();
    assert_eq!(back, ir);
    assert!(ir.to_json().contains("\"controls\""));
    let (x, g) = gate(10);
    // One stream per control, as long as the input.
    assert!(simulate_controls(&ir, &x, &[], H, &opts(), usize::MAX, |_| Ok(())).is_err());
    assert!(simulate_controls(&ir, &x, &[&g[..5]], H, &opts(), usize::MAX, |_| Ok(())).is_err());
    let mut bad = ir.clone();
    bad.controls[0].node = "nowhere".into();
    assert!(bad.validate().is_err());
    let mut twice = ir.clone();
    twice.controls.push(twice.controls[0].clone());
    assert!(twice.validate().is_err());
}
