//! Noise sources in a run (device builder B5): Johnson noise reaches thermal
//! equilibrium (kT/C on every capacitor), the samples sit on the noise grid whatever
//! the engine's rate, a seed reproduces its run, and blocks and partitions see the same
//! noise.

use circuitsim::ir::{
    Capacitor, CircuitIr, Element, IR_VERSION, NoiseCurrent, NoiseSpec, Probe, Resistor, Section,
    SineSource,
};
use circuitsim::noise::K_B;
use circuitsim::partition::{Coupling, simulate_partitioned};
use circuitsim::stream::Stream;
use circuitsim::transient::{Method, Options};

const T_K: f64 = 300.0;
const C_F: f64 = 100e-9;
const RATE: f64 = 96_000.0;

fn r(name: &str, a: &str, b: &str, ohm: f64) -> Element {
    Element::Resistor(Resistor {
        name: name.into(),
        a: a.into(),
        b: b.into(),
        r_ohm: ohm,
    })
}

fn c(name: &str, a: &str, b: &str, f: f64) -> Element {
    Element::Capacitor(Capacitor {
        name: name.into(),
        a: a.into(),
        b: b.into(),
        c_f: f,
        v0_v: None,
    })
}

fn noise(of: &str, a: &str, b: &str, ohm: f64) -> Element {
    Element::NoiseCurrent(NoiseCurrent {
        name: format!("IN_{of}"),
        a: a.into(),
        b: b.into(),
        psd_a2_hz: 4.0 * K_B * T_K / ohm,
    })
}

/// Two RCs (10k || 100 nF, corners 159 Hz) joined by 1M, every resistor noisy.
fn circuit(seed: u64) -> CircuitIr {
    let ir = CircuitIr {
        version: IR_VERSION,
        title: "noise".into(),
        input_node: "in".into(),
        controls: vec![],
        noise: Some(NoiseSpec {
            seed,
            rate_hz: RATE,
            mains_rms: 0.0,
            mains_sources: vec![],
        }),
        probes: vec![
            Probe::Voltage { node: "out".into() },
            Probe::Voltage { node: "x".into() },
        ],
        models: vec![],
        sections: vec![
            Section {
                title: "first".into(),
                elements: vec![
                    r("RIN", "in", "0", 1e3),
                    r("R1", "out", "0", 1e4),
                    noise("R1", "out", "0", 1e4),
                    c("C1", "out", "0", C_F),
                    r("R3", "out", "x", 1e6),
                    noise("R3", "out", "x", 1e6),
                ],
            },
            Section {
                title: "other".into(),
                elements: vec![
                    r("R2", "x", "0", 1e4),
                    noise("R2", "x", "0", 1e4),
                    c("C2", "x", "0", C_F),
                ],
            },
        ],
    };
    ir.validate().unwrap();
    ir
}

fn opts() -> Options {
    Options::with_method(Method::Esdirk4)
}

fn probe(out: &circuitsim::Output, name: &str) -> Vec<f64> {
    out.values[out.names.iter().position(|s| s == name).unwrap()].clone()
}

fn var(x: &[f64]) -> f64 {
    let m = x.iter().sum::<f64>() / x.len() as f64;
    x.iter().map(|v| (v - m) * (v - m)).sum::<f64>() / x.len() as f64
}

fn rms_diff(a: &[f64], b: &[f64]) -> f64 {
    let d: f64 = a.iter().zip(b).map(|(x, y)| (x - y) * (x - y)).sum();
    let s: f64 = a.iter().map(|x| x * x).sum();
    (d / s).sqrt()
}

#[test]
fn johnson_noise_puts_kt_over_c_on_every_capacitor() {
    let n = 4 * RATE as usize;
    let out = circuitsim::simulate(&circuit(1), &vec![0.0; n], 1.0 / RATE, &opts()).unwrap();
    let want = K_B * T_K / C_F;
    for p in ["v(out)", "v(x)"] {
        let v = probe(&out, p);
        let got = var(&v[RATE as usize / 20..]);
        println!("{p}: variance / (kT/C) = {:.4}", got / want);
        assert!(
            (got / want - 1.0).abs() < 0.1,
            "{p}: variance {got:e} V^2, kT/C {want:e}"
        );
    }
}

#[test]
fn the_noise_is_on_its_grid_whatever_the_engines_rate() {
    let n = RATE as usize / 4;
    let x = vec![0.0; n];
    let at1 = circuitsim::simulate(&circuit(2), &x, 1.0 / RATE, &opts()).unwrap();
    let x2 = vec![0.0; 2 * n];
    let at2 = circuitsim::simulate(&circuit(2), &x2, 0.5 / RATE, &opts()).unwrap();
    let (a, b) = (probe(&at1, "v(out)"), probe(&at2, "v(out)"));
    let b: Vec<f64> = b.iter().step_by(2).copied().collect();
    let d = rms_diff(&a[..n], &b[..n]);
    println!("1x vs 2x: {d:.2e}");
    assert!(d < 1e-3, "1x vs 2x: rms difference {d:e} of the signal");
}

#[test]
fn a_seed_reproduces_its_run() {
    let n = 4000;
    let x = vec![0.0; n];
    let run = |seed| {
        probe(
            &circuitsim::simulate(&circuit(seed), &x, 1.0 / RATE, &opts()).unwrap(),
            "v(out)",
        )
    };
    let (a, b, other) = (run(5), run(5), run(6));
    assert!(a.iter().zip(&b).all(|(p, q)| p.to_bits() == q.to_bits()));
    assert!(rms_diff(&a, &other) > 0.5);
}

#[test]
fn blocks_and_partitions_see_the_same_noise() {
    let n = 6000;
    let x = vec![0.0; n];
    let ir = circuit(9);
    let o = opts();
    let whole = circuitsim::simulate(&ir, &x, 1.0 / RATE, &o).unwrap();
    // In blocks: bit for bit.
    let mut s = Stream::new(&ir, &[], Coupling::Extrapolate, 1.0 / RATE, &o, 0.0).unwrap();
    let mut got: Vec<Vec<f64>> = s.initial().into_iter().map(|v| vec![v]).collect();
    let mut i = 1;
    for b in [1usize, 7, 64, 333].iter().cycle() {
        if i >= n {
            break;
        }
        let b = (*b).min(n - i);
        for (g, v) in got.iter_mut().zip(s.process(&x[i..i + b]).unwrap()) {
            g.extend(v);
        }
        i += b;
    }
    for (g, v) in got.iter_mut().zip(s.finish().unwrap()) {
        g.extend(v);
    }
    for (k, name) in whole.names.iter().enumerate() {
        let j = s.names().iter().position(|m| m == name).unwrap();
        assert!(
            whole.values[k]
                .iter()
                .zip(&got[j])
                .all(|(p, q)| p.to_bits() == q.to_bits()),
            "{name} in blocks"
        );
    }
    // Partitioned ("other" on its own thread, one sample of coupling latency): the same
    // noise, up to the coupling.
    let part = simulate_partitioned(
        &ir,
        &["other".to_string()],
        Coupling::Extrapolate,
        &x,
        1.0 / RATE,
        &o,
        usize::MAX,
        |_| Ok(()),
    )
    .unwrap();
    for p in ["v(out)", "v(x)"] {
        let d = rms_diff(&probe(&whole, p)[100..], &probe(&part, p)[100..]);
        println!("{p} partitioned: {d:.2e}");
        assert!(d < 1e-2, "{p} partitioned: rms difference {d:e}");
    }
}

/// The mains wander multiplies a mains source's amplitude by 1 + m, m from the Python
/// reference (`varimu.devices.noise.mains_wander`, in the noise fixture).
#[test]
fn the_mains_wander_multiplies_the_mains_amplitude() {
    let fx: serde_json::Value = serde_json::from_str(
        &std::fs::read_to_string(
            std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
                .join("tests/fixtures/noise/noise.json"),
        )
        .unwrap(),
    )
    .unwrap();
    let m = &fx["mains"];
    let want: Vec<f64> = m["samples"]
        .as_array()
        .unwrap()
        .iter()
        .map(|x| x.as_f64().unwrap())
        .collect();
    let (amp, hz) = (100.0, 60.0);
    let ir = CircuitIr {
        version: IR_VERSION,
        title: "mains".into(),
        input_node: "in".into(),
        controls: vec![],
        noise: Some(NoiseSpec {
            seed: m["seed"].as_u64().unwrap(),
            rate_hz: RATE,
            mains_rms: m["rms"].as_f64().unwrap(),
            mains_sources: vec!["VM".into()],
        }),
        probes: vec![Probe::Voltage { node: "m".into() }],
        models: vec![],
        sections: vec![Section {
            title: "t".into(),
            elements: vec![
                r("RIN", "in", "0", 1e3),
                Element::SineSource(SineSource {
                    name: "VM".into(),
                    pos: "m".into(),
                    neg: "0".into(),
                    offset_v: 0.0,
                    amplitude_v: amp,
                    freq_hz: hz,
                    phase_deg: 90.0,
                }),
                r("RM", "m", "0", 1e3),
            ],
        }],
    };
    let n = want.len();
    let out = circuitsim::simulate(&ir, &vec![0.0; n], 1.0 / RATE, &opts()).unwrap();
    let v = probe(&out, "v(m)");
    let mut worst = 0.0f64;
    for (k, (&got, &mk)) in v.iter().zip(&want).enumerate().skip(1) {
        let s = amp
            * (2.0 * std::f64::consts::PI * hz * k as f64 / RATE + std::f64::consts::FRAC_PI_2)
                .sin();
        if s.abs() > 0.5 * amp {
            worst = worst.max((got / s - 1.0 - mk).abs());
        }
    }
    let rms = (want.iter().map(|x| x * x).sum::<f64>() / n as f64).sqrt();
    println!("mains wander: worst {worst:.2e} against m's rms {rms:.2e}");
    assert!(worst < 1e-9 * (1.0 + rms), "worst {worst:e}");
}
