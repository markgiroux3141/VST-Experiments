//! Externals (`Mna::externals`) and partitioned runs (`partition.rs`).

use std::fs;
use std::path::Path;

use circuitsim::ir::{
    Capacitor, CircuitIr, Element, IR_VERSION, Probe, Resistor, Section, VoltageSource,
};
use circuitsim::mna::Mna;
use circuitsim::partition::{Coupling, GROUP_BREAK, simulate_partitioned};
use circuitsim::transient::{Method, Options, Output, Transient};

fn fixture(name: &str) -> CircuitIr {
    let path = Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("tests")
        .join("fixtures")
        .join(name);
    CircuitIr::from_json(&fs::read_to_string(path).expect(name)).unwrap()
}

fn resistor(name: &str, a: &str, b: &str, r_ohm: f64) -> Element {
    Element::Resistor(Resistor {
        name: name.into(),
        a: a.into(),
        b: b.into(),
        r_ohm,
    })
}

/// `src` -- 1k -- out -- 1 uF -- 0, driven by the input (`src` = the input
/// node) or by a 0 V source on `src` whose row is an external.
fn rc(external: bool) -> CircuitIr {
    let mut elements = vec![
        resistor("R1", "src", "out", 1e3),
        Element::Capacitor(Capacitor {
            name: "C1".into(),
            a: "out".into(),
            b: "0".into(),
            c_f: 1e-6,
            v0_v: None,
        }),
    ];
    if external {
        elements.push(Element::VoltageSource(VoltageSource {
            name: "VX".into(),
            pos: "src".into(),
            neg: "0".into(),
            dc_v: 0.0,
        }));
        elements.push(resistor("RIN", "in", "0", 1e3));
    }
    CircuitIr {
        version: IR_VERSION,
        title: "rc".into(),
        input_node: if external { "in" } else { "src" }.into(),
        controls: vec![],
        noise: None,
        heaters: None,
        probes: vec![Probe::Voltage { node: "out".into() }],
        models: vec![],
        sections: vec![Section {
            title: "t".into(),
            substeps: None,
            elements,
        }],
    }
}

/// A source driven through its external row is the same equation as the
/// input: the same output to roundoff, for a one-stage and a multistage
/// method (externals are linear over a sample, at each stage's time).
#[test]
fn an_external_source_drives_like_the_input() {
    let h = 1e-5;
    let u = |n: usize| (n as f64 * h * 2e3).sin() + 0.3;
    for method in [Method::Trapezoidal, Method::TrBdf2, Method::Esdirk4] {
        let opts = Options::with_method(method);
        let mut a = Transient::new(Mna::from_ir(&rc(false), 0.0).unwrap(), h, opts, u(0)).unwrap();
        let mut mb = Mna::from_ir(&rc(true), 0.0).unwrap();
        mb.externals = vec![mb.branch("VX").unwrap()];
        let mut b = Transient::with_externals(mb, h, opts, 0.0, &[u(0)]).unwrap();
        let out = |t: &Transient| t.x()[t.mna().probes[0].1.unwrap()];
        assert!((out(&a) - out(&b)).abs() < 1e-14);
        for n in 1..400 {
            a.step(u(n)).unwrap();
            b.set_externals(&[u(n - 1)], &[u(n)]);
            b.step(0.0).unwrap();
            assert!(
                (out(&a) - out(&b)).abs() <= 1e-12,
                "{method:?} step {n}: {} vs {}",
                out(&a),
                out(&b)
            );
        }
    }
}

/// Externals need the DK solver (only its stages read them).
#[test]
fn externals_need_the_dk_solver() {
    let mut m = Mna::from_ir(&rc(true), 0.0).unwrap();
    m.externals = vec![m.branch("VX").unwrap()];
    let opts = Options {
        solver: circuitsim::transient::Solver::Mna,
        ..Options::with_method(Method::Trapezoidal)
    };
    let e = Transient::with_externals(m, 1e-5, opts, 0.0, &[0.0]).unwrap_err();
    assert!(e.0.contains("DK"), "{e}");
}

const SUPPLIES: [&str; 3] = ["power supply", "bias supply", "channel 2 (idle, lumped)"];

fn tone(n: usize, h: f64) -> Vec<f64> {
    // 1 kHz at 0 dBFS (13.8 V), faded in over 1 ms.
    (0..n)
        .map(|i| {
            let t = i as f64 * h;
            13.8 * (t / 1e-3).min(1.0) * (2.0 * std::f64::consts::PI * 1e3 * t).sin()
        })
        .collect()
}

fn series<'a>(o: &'a Output, name: &str) -> &'a [f64] {
    &o.values[o.names.iter().position(|n| n == name).expect(name)]
}

fn rms(x: impl Iterator<Item = f64>) -> f64 {
    let (s, n) = x.fold((0.0, 0), |(s, n), v| (s + v * v, n + 1));
    (s / n as f64).sqrt()
}

/// The 670 with its supplies (and the idle channel 2) on a second thread,
/// against the one solve: 30 ms of 1 kHz at 0 dBFS, TR-BDF2 at 2x 48 kHz (the
/// draft's method): the output within -80 dB of its level, the control
/// voltage within 1 mV (measured on 3 s of program: -103 dB, 0.1 mV). The
/// result doesn't depend on timing: two runs are identical.
#[test]
fn the_670_partitioned_follows_the_one_solve() {
    follows_the_one_solve(&SUPPLIES);
}

/// The same in three partitions (groups separated by `GROUP_BREAK`): the
/// power supply with the idle channel 2 on one thread, the bias supply on
/// another; the nodes all three share are the bias supply's (the last group's).
#[test]
fn the_670_in_three_partitions_follows_the_one_solve() {
    follows_the_one_solve(&[
        "power supply",
        "channel 2 (idle, lumped)",
        GROUP_BREAK,
        "bias supply",
    ]);
}

fn follows_the_one_solve(second: &[&str]) {
    let ir = fixture("default.json");
    let h = 1.0 / 96_000.0;
    let x = tone((0.03 / h) as usize, h);
    let opts = Options {
        input_order: 5,
        reltol: 1e-4,
        vntol: 1e-3,
        tube_tables: true,
        all_unknowns: false,
        ..Options::with_method(Method::TrBdf2)
    };
    let one = circuitsim::simulate(&ir, &x, h, &opts).unwrap();
    let second: Vec<String> = second.iter().map(|s| s.to_string()).collect();
    let run = || {
        simulate_partitioned(
            &ir,
            &second,
            Coupling::Extrapolate,
            &x,
            h,
            &opts,
            usize::MAX,
            |_| Ok(()),
        )
        .unwrap()
    };
    let (p, again) = (run(), run());
    assert_eq!(p.names, one.names, "the IR's probes, in its order");
    for (a, b) in p.values.iter().zip(&again.values) {
        assert!(a.iter().zip(b).all(|(x, y)| x.to_bits() == y.to_bits()));
    }
    let (o1, op) = (series(&one, "v(out)"), series(&p, "v(out)"));
    let level = rms(o1.iter().copied());
    let diff = rms(o1.iter().zip(op).map(|(a, b)| a - b));
    let cv = o1.len().min(series(&p, "v(cv)").len());
    let cv_diff = series(&one, "v(cv)")[..cv]
        .iter()
        .zip(series(&p, "v(cv)"))
        .map(|(a, b)| (a - b).abs())
        .fold(0.0, f64::max);
    println!(
        "partitioned vs one solve: {:.1} dB, CV max {cv_diff:.2e} V",
        20.0 * (diff / level).log10()
    );
    assert!(diff <= 1e-4 * level, "{diff} vs level {level}");
    assert!(cv_diff <= 1e-3, "CV {cv_diff} V");
}

/// What a split can't be: unknown sections, the input in the second part.
#[test]
fn partitions_are_checked() {
    let ir = fixture("default.json");
    let x = vec![0.0; 4];
    let opts = Options::with_method(Method::TrBdf2);
    let run = |second: &[&str]| {
        let second: Vec<String> = second.iter().map(|s| s.to_string()).collect();
        simulate_partitioned(&ir, &second, Coupling::Hold, &x, 1e-5, &opts, 1, |_| Ok(()))
            .unwrap_err()
            .0
    };
    assert!(run(&["no such section"]).contains("no section titled"));
    assert!(run(&["input"]).contains("input node"));
    assert!(run(&["bias supply", GROUP_BREAK, "bias supply"]).contains("in two groups"));
    assert!(Coupling::parse("lagged").is_err());
}

/// A stiff node in the audio part (`s`: 10 uF behind 100 ohm from the input) feeding a
/// multi-rate section (16 steps per sample) with a 100 kHz source in it, above the
/// sample rate's Nyquist frequency: the multi-rate run against the whole circuit solved
/// as one at the fine step, the input interpolated linearly in both.
fn multirate_ir(substeps: Option<usize>) -> CircuitIr {
    let cap = |name: &str, a: &str, c_f: f64| {
        Element::Capacitor(Capacitor {
            name: name.into(),
            a: a.into(),
            b: "0".into(),
            c_f,
            v0_v: None,
        })
    };
    CircuitIr {
        version: IR_VERSION,
        title: "multirate".into(),
        input_node: "in".into(),
        controls: vec![],
        noise: None,
        heaters: None,
        probes: vec![
            Probe::Voltage { node: "s".into() },
            Probe::Voltage { node: "f".into() },
        ],
        models: vec![],
        sections: vec![
            Section {
                title: "audio".into(),
                substeps: None,
                elements: vec![resistor("R1", "in", "s", 100.0), cap("C1", "s", 10e-6)],
            },
            Section {
                title: "fast".into(),
                substeps,
                elements: vec![
                    resistor("R2", "s", "f", 1e3),
                    cap("C2", "f", 1e-9),
                    Element::SineSource(circuitsim::ir::SineSource {
                        name: "VG".into(),
                        pos: "g".into(),
                        neg: "0".into(),
                        offset_v: 0.0,
                        amplitude_v: 50.0,
                        freq_hz: 99.3e3,
                        phase_deg: 0.0,
                    }),
                    resistor("R3", "g", "f", 1e3),
                ],
            },
        ],
    }
}

#[test]
fn a_multirate_part_follows_the_fine_one_solve() {
    let (m, h) = (16usize, 1.0 / 192_000.0);
    let n = 2000;
    let x: Vec<f64> = (0..n)
        .map(|i| 10.0 + 5.0 * (2.0 * std::f64::consts::PI * 1e3 * i as f64 * h).sin())
        .collect();
    let opts = Options {
        input_order: 1,
        ..Options::with_method(Method::Esdirk4)
    };
    let run = || {
        simulate_partitioned(
            &multirate_ir(Some(m)),
            &[],
            Coupling::Extrapolate,
            &x,
            h,
            &opts,
            usize::MAX,
            |_| Ok(()),
        )
        .unwrap()
    };
    let (p, again) = (run(), run());
    for (a, b) in p.values.iter().zip(&again.values) {
        assert!(a.iter().zip(b).all(|(x, y)| x.to_bits() == y.to_bits()));
    }
    // The reference: one solve at h / m, the input linear between samples.
    let fine: Vec<f64> = (0..(n - 1) * m + 1)
        .map(|j| {
            let (i, f) = (j / m, (j % m) as f64 / m as f64);
            if i + 1 < n {
                x[i] + (x[i + 1] - x[i]) * f
            } else {
                x[i]
            }
        })
        .collect();
    let one = circuitsim::simulate(&multirate_ir(None), &fine, h / m as f64, &opts).unwrap();
    // The audio part sees the multi-rate part's current averaged over each sample (the
    // charge it moved). That isn't a sharp filter: the source's 99.3 kHz aliases to 92.7 kHz
    // at 192 kHz, above the audio band, which a render's decimation removes. So s is
    // compared in the audio band (means over 16-sample blocks, 12 kHz) against the fine
    // solve's at the same samples (measured: 0.4 mV, the ripple 9 mV); f, inside the
    // multi-rate part, sample by sample.
    let (s_fine, f_fine) = (series(&one, "v(s)"), series(&one, "v(f)"));
    let (s_p, f_p) = (series(&p, "v(s)"), series(&p, "v(f)"));
    assert_eq!(s_p.len(), n);
    let blocks = (n - 1) / 16;
    let ds = (8..blocks)
        .map(|b| {
            let span = 1 + 16 * b..1 + 16 * (b + 1);
            let mp = s_p[span.clone()].iter().sum::<f64>() / 16.0;
            mp - span.map(|i| s_fine[i * m]).sum::<f64>() / 16.0
        })
        .fold(0.0, |w: f64, d| w.max(d.abs()));
    let df = (100..n)
        .map(|i| f_fine[i * m] - f_p[i])
        .fold(0.0, |w: f64, d| w.max(d.abs()));
    let f_swing = f_p.iter().fold(0.0, |w: f64, v| w.max(v.abs()));
    assert!(ds < 1e-3, "v(s) differs by {ds} V in the audio band");
    assert!(df < 1e-3 * f_swing, "v(f) differs by {df} V of {f_swing}");
    // Without substeps the part can't run the source (one solve at h refuses nothing,
    // but the multi-rate IR does refuse the single solve).
    assert!(circuitsim::simulate(&multirate_ir(Some(m)), &x, h, &opts).is_err());
}
