//! A run's origin (`Options::origin_samples`, TAPE_SPEED_PLAN.md P3): a run started at
//! sample K of a longer run continues it in what depends on time alone (the sine sources,
//! the noise streams, the mains wander), so pieces of a long render can run apart.

use circuitsim::ir::{
    CircuitIr, Element, IR_VERSION, NoiseCurrent, NoiseSpec, Probe, Resistor, Section, SineSource,
};
use circuitsim::transient::{Method, Options};

fn r(name: &str, a: &str, b: &str, ohm: f64) -> Element {
    Element::Resistor(Resistor {
        name: name.into(),
        a: a.into(),
        b: b.into(),
        r_ohm: ohm,
    })
}

/// A memoryless circuit: the mains (60 Hz, with its wander) into a noisy divider, so its
/// output at a sample depends on that sample's time alone.
fn circuit() -> CircuitIr {
    let ir = CircuitIr {
        version: IR_VERSION,
        title: "origin".into(),
        input_node: "in".into(),
        controls: vec![],
        heaters: None,
        noise: Some(NoiseSpec {
            seed: 7,
            rate_hz: 96_000.0,
            mains_rms: 0.005,
            mains_sources: vec!["VM".into()],
        }),
        probes: vec![Probe::Voltage { node: "out".into() }],
        models: vec![],
        sections: vec![Section {
            title: "all".into(),
            substeps: None,
            decimate: None,
            owns: None,
            lag_samples: None,
            elements: vec![
                r("RIN", "in", "0", 1e3),
                Element::SineSource(SineSource {
                    name: "VM".into(),
                    pos: "m".into(),
                    neg: "0".into(),
                    offset_v: 0.0,
                    amplitude_v: 10.0,
                    freq_hz: 60.0,
                    phase_deg: 90.0,
                }),
                r("R1", "m", "out", 1e3),
                r("R2", "out", "0", 1e3),
                Element::NoiseCurrent(NoiseCurrent {
                    name: "IN_R2".into(),
                    a: "out".into(),
                    b: "0".into(),
                    psd_a2_hz: 4.0 * circuitsim::noise::K_B * 300.0 / 1e3,
                }),
            ],
        }],
    };
    ir.validate().unwrap();
    ir
}

#[test]
fn a_run_from_an_origin_continues_the_longer_run() {
    let h = 1.0 / 192_000.0;
    let (n, k) = (6000usize, 2500u64);
    let run = |origin: u64, len: usize| {
        let opts = Options {
            origin_samples: origin,
            ..Options::with_method(Method::Esdirk4)
        };
        circuitsim::simulate(&circuit(), &vec![0.0; len], h, &opts)
            .unwrap()
            .values[0]
            .clone()
    };
    let whole = run(0, n);
    let piece = run(k, n - k as usize);
    // Sample 0 is the DC point (no noise there): compare from the first step on.
    let worst = (1..piece.len())
        .map(|i| (piece[i] - whole[k as usize + i]).abs())
        .fold(0.0, f64::max);
    let noise_rms = (1..piece.len())
        .map(|i| {
            let d = piece[i] - piece[i - 1];
            d * d
        })
        .sum::<f64>()
        .sqrt();
    assert!(noise_rms > 0.0);
    assert!(worst < 1e-9, "the piece is {worst} V from the whole run");
    // And without an origin it doesn't continue it (the test would see that).
    let fresh = run(0, n - k as usize);
    let off = (1..fresh.len())
        .map(|i| (fresh[i] - whole[k as usize + i]).abs())
        .fold(0.0, f64::max);
    assert!(off > 1e-3, "{off}");
}
