//! Audio control inputs (`Control::audio`, STEREO_PLAN.md ST7): a second channel's audio
//! on a control input, interpolated as the input is, so two channels fed the same samples
//! see the same waveform.

use circuitsim::ir::{
    Capacitor, CircuitIr, Control, Element, IR_VERSION, Probe, Resistor, Section,
};
use circuitsim::partition::Coupling;
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

/// Two identical RCs (1k into 4.7 nF, a corner near 34 kHz): the input into `a`, the
/// control `in_r` into `b`.
fn circuit(audio: bool) -> CircuitIr {
    let ir = CircuitIr {
        version: IR_VERSION,
        title: "two channels".into(),
        input_node: "in".into(),
        controls: vec![Control {
            name: "in_r".into(),
            node: "r".into(),
            audio,
        }],
        noise: None,
        heaters: None,
        probes: ["a", "b"]
            .iter()
            .map(|n| Probe::Voltage { node: (*n).into() })
            .collect(),
        models: vec![],
        sections: vec![Section {
            title: "both".into(),
            substeps: None,
            decimate: None,
            owns: None,
            lag_samples: None,
            method: None,
            tube_tables: None,
            elements: vec![
                resistor("R1", "in", "a", 1e3),
                capacitor("C1", "a", "0", 4.7e-9),
                resistor("R2", "r", "b", 1e3),
                capacitor("C2", "b", "0", 4.7e-9),
            ],
        }],
    };
    ir.validate().unwrap();
    ir
}

fn opts() -> Options {
    Options {
        method: Method::Esdirk4,
        input_order: 5,
        ..Options::default()
    }
}

const H: f64 = 1.0 / 192_000.0;

/// A 17 kHz tone at the simulation's rate (a hard case for linear interpolation).
fn tone(n: usize) -> Vec<f64> {
    (0..n)
        .map(|i| (2.0 * std::f64::consts::PI * 17_000.0 * i as f64 * H).sin())
        .collect()
}

/// The largest difference between the two channels' outputs.
fn spread(ir: &CircuitIr, x: &[f64]) -> f64 {
    let out = simulate_controls(ir, x, &[x], H, &opts(), usize::MAX, |_| Ok(())).unwrap();
    let a = &out.values[0];
    let b = &out.values[1];
    a.iter()
        .zip(b)
        .map(|(p, q)| (p - q).abs())
        .fold(0.0, f64::max)
}

#[test]
fn an_audio_control_sees_the_inputs_waveform() {
    let x = tone(4000);
    let same = spread(&circuit(true), &x);
    let linear = spread(&circuit(false), &x);
    // The same polynomial into the same network: equal up to rounding.
    assert!(same < 1e-12, "{same}");
    // A plain control is a line between samples: at 17 kHz on a 192 kHz grid, visibly not.
    assert!(linear > 1e-3, "{linear}");
}

#[test]
fn an_audio_controls_stream_equals_the_whole_run() {
    let ir = circuit(true);
    let x = tone(3000);
    let whole = simulate_controls(&ir, &x, &[&x], H, &opts(), usize::MAX, |_| Ok(())).unwrap();
    let mut s =
        Stream::with_controls(&ir, &[], Coupling::Extrapolate, H, &opts(), x[0], &[x[0]]).unwrap();
    let mut got: Vec<Vec<f64>> = s.initial().into_iter().map(|v| vec![v]).collect();
    for (a, b) in [(1usize, 700usize), (700, 701), (701, 2400), (2400, 3000)] {
        let ys = s.process_with(&x[a..b], &[&x[a..b]]).unwrap();
        for (g, y) in got.iter_mut().zip(ys) {
            g.extend(y);
        }
    }
    for (g, y) in got.iter_mut().zip(s.finish().unwrap()) {
        g.extend(y);
    }
    assert_eq!(got, whole.values);
}
