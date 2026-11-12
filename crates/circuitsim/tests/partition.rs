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
            decimate: None,
            owns: None,
            lag_samples: None,
            method: None,
            tube_tables: None,
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
                decimate: None,
                owns: None,
                lag_samples: None,
                method: None,
                tube_tables: None,
                elements: vec![resistor("R1", "in", "s", 100.0), cap("C1", "s", 10e-6)],
            },
            Section {
                title: "fast".into(),
                substeps,
                decimate: None,
                owns: None,
                lag_samples: None,
                method: None,
                tube_tables: None,
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

/// The amplitude of `f_hz` in `x` (sampled at `rate`), by projection.
fn amplitude(x: &[f64], f_hz: f64, rate: f64) -> f64 {
    let (mut c, mut s) = (0.0, 0.0);
    for (i, &v) in x.iter().enumerate() {
        let w = 2.0 * std::f64::consts::PI * f_hz * i as f64 / rate;
        c += v * w.cos();
        s += v * w.sin();
    }
    2.0 * (c * c + s * s).sqrt() / x.len() as f64
}

fn with_decimate(mut ir: CircuitIr, owns: Option<Vec<String>>) -> CircuitIr {
    for s in &mut ir.sections {
        if s.substeps.is_some_and(|m| m > 1) {
            s.decimate = Some(circuitsim::ir::Decimate::Fir);
            s.owns = owns.clone();
        }
    }
    ir
}

/// A multi-rate part's 99.3 kHz source seen by the 96 kHz part: averaged per sample it
/// folds to 3.3 kHz (the box filter's sidelobe), through the decimator it is gone
/// (measured: 4.0 mV -> 0.2 uV at `s`); the multi-rate part's own probe likewise. The
/// price is the decimator's delay (~6.4 samples) in a two-way coupling: the multi-rate
/// part loads `s` by ~5% through 1k, and the 1 kHz there is 0.34% (0.03 dB) off the fine
/// one solve, where the average is within 0.02%. Across stiff rails or into a light
/// load (an island's output it owns) the delay costs far less.
#[test]
fn a_decimating_part_hands_on_no_alias() {
    let (m, h) = (16usize, 1.0 / 96_000.0);
    let n = 9600;
    let x: Vec<f64> = (0..n)
        .map(|i| 10.0 + 5.0 * (2.0 * std::f64::consts::PI * 1e3 * i as f64 * h).sin())
        .collect();
    let opts = Options {
        input_order: 1,
        ..Options::with_method(Method::TrBdf2)
    };
    let run = |ir: &CircuitIr| {
        simulate_partitioned(
            ir,
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
    let avg = run(&multirate_ir(Some(m)));
    let fir = run(&with_decimate(multirate_ir(Some(m)), None));
    // The fine one solve at h / m, the input linear between samples.
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
    let tail = |o: &Output, p: &str| series(o, p)[n / 2..].to_vec();
    let alias = 99.3e3 - 96e3;
    for p in ["v(s)", "v(f)"] {
        let (a, f) = (tail(&avg, p), tail(&fir, p));
        let r: Vec<f64> = series(&one, p)[(n / 2) * m..]
            .iter()
            .step_by(m)
            .copied()
            .collect();
        let (aa, fa) = (amplitude(&a, alias, 96e3), amplitude(&f, alias, 96e3));
        let (a1, f1, r1) = (
            amplitude(&a, 1e3, 96e3),
            amplitude(&f, 1e3, 96e3),
            amplitude(&r, 1e3, 96e3),
        );
        assert!(fa < 1e-4 * aa, "{p}: the alias {fa} V (averaged {aa} V)");
        // Inside the multi-rate part (`f`) both runs carry the coupling's lag on `s`
        // (0.4-0.5% at 1 kHz); at `s` the averaged run is within 0.02%, the decimated
        // 0.34% (the decimator's delay, above).
        let (tol_avg, tol_fir) = if p == "v(s)" {
            (1e-3, 5e-3)
        } else {
            (1e-2, 1e-2)
        };
        assert!(
            (a1 / r1 - 1.0).abs() < tol_avg,
            "{p}: 1 kHz averaged {a1} V, fine {r1} V"
        );
        assert!(
            (f1 / r1 - 1.0).abs() < tol_fir,
            "{p}: 1 kHz decimated {f1} V, fine {r1} V"
        );
    }
}

/// An island owning its output into a high-impedance load, with a loop of ownership:
/// the island (8 steps per sample, decimating) drives `o` through an RC from the input
/// and draws from the supply `b` and the source's node `vb`; the slow part owns both (a
/// source, through 10k onto 10 uF) and loads `o` with 10 nF into 1 Mohm (a grid). The DC start equals the one
/// solve's; the grid follows the fine one solve delayed by the decimator's delay.
#[test]
fn an_island_owns_its_output() {
    let (m, h) = (8usize, 1.0 / 96_000.0);
    let cap = |name: &str, a: &str, b: &str, c_f: f64| {
        Element::Capacitor(Capacitor {
            name: name.into(),
            a: a.into(),
            b: b.into(),
            c_f,
            v0_v: None,
        })
    };
    let ir = |substeps: Option<usize>| CircuitIr {
        version: IR_VERSION,
        title: "island".into(),
        input_node: "in".into(),
        controls: vec![],
        noise: None,
        heaters: None,
        probes: vec![
            Probe::Voltage { node: "o".into() },
            Probe::Voltage { node: "g".into() },
            Probe::Voltage { node: "b".into() },
        ],
        models: vec![],
        sections: vec![
            Section {
                title: "supply and load".into(),
                substeps: None,
                decimate: None,
                owns: None,
                lag_samples: None,
                method: None,
                tube_tables: None,
                elements: vec![
                    Element::VoltageSource(VoltageSource {
                        name: "VB".into(),
                        pos: "vb".into(),
                        neg: "0".into(),
                        dc_v: 100.0,
                    }),
                    resistor("RB", "vb", "b", 10e3),
                    cap("CB", "b", "0", 10e-6),
                    cap("CG", "o", "g", 10e-9),
                    resistor("RG", "g", "0", 1e6),
                ],
            },
            Section {
                title: "island".into(),
                substeps,
                decimate: substeps.map(|_| circuitsim::ir::Decimate::Fir),
                owns: substeps.map(|_| vec!["o".to_string()]),
                lag_samples: None,
                method: None,
                tube_tables: None,
                elements: vec![
                    resistor("R1", "in", "o", 1e3),
                    cap("C1", "o", "0", 100e-9),
                    resistor("R2", "b", "o", 100e3),
                    // and from the source's own node (held at DC by VB itself)
                    resistor("R3", "vb", "o", 1e6),
                ],
            },
        ],
    };
    let n = 4800;
    let x: Vec<f64> = (0..n)
        .map(|i| 2.0 * (2.0 * std::f64::consts::PI * 500.0 * i as f64 * h).sin())
        .collect();
    let opts = Options {
        input_order: 1,
        ..Options::with_method(Method::TrBdf2)
    };
    let p = simulate_partitioned(
        &ir(Some(m)),
        &[],
        Coupling::Extrapolate,
        &x,
        h,
        &opts,
        usize::MAX,
        |_| Ok(()),
    )
    .unwrap();
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
    let one = circuitsim::simulate(&ir(None), &fine, h / m as f64, &opts).unwrap();
    // The DC start, the same in both.
    for name in ["v(o)", "v(g)", "v(b)"] {
        let (a, b) = (series(&p, name)[0], series(&one, name)[0]);
        assert!(
            (a - b).abs() < 1e-9 * b.abs().max(1.0),
            "{name} at DC: {a} against {b}"
        );
    }
    // The grid follows, the decimator's delay later: within 1% of its swing (the load's
    // current reaches the island a sample and the delay late).
    let d = circuitsim::partition::Decimator::delay_steps(m);
    let (g_p, g_one) = (series(&p, "v(g)"), series(&one, "v(g)"));
    let swing = g_one.iter().fold(0.0, |w: f64, v| w.max(v.abs()));
    let err = (n / 4..n)
        .map(|i| g_p[i] - g_one[i * m - d])
        .fold(0.0, |w: f64, e| w.max(e.abs()));
    assert!(err < 1e-2 * swing, "v(g) differs by {err} V of {swing}");
}

#[test]
fn ownership_is_checked() {
    let mut ir = with_decimate(multirate_ir(Some(8)), Some(vec!["nowhere".into()]));
    let x = vec![0.0; 10];
    let opts = Options::with_method(Method::TrBdf2);
    let e = simulate_partitioned(
        &ir,
        &[],
        Coupling::Hold,
        &x,
        1e-5,
        &opts,
        usize::MAX,
        |_| Ok(()),
    )
    .unwrap_err();
    assert!(e.0.contains("doesn't have"), "{e}");
    // `f` is the island's alone: owned but not shared, it stays the island's (a switch can leave
    // an island's output unused)
    ir = with_decimate(multirate_ir(Some(8)), Some(vec!["f".into()]));
    simulate_partitioned(
        &ir,
        &[],
        Coupling::Hold,
        &x,
        1e-5,
        &opts,
        usize::MAX,
        |_| Ok(()),
    )
    .unwrap();
    // in a single-rate section: a claim too (a speaker's driver keeping what its back wave
    // senses, `varimu_circuit::speaker::readout_apart`); an empty one is refused
    let mut ir = multirate_ir(None);
    ir.sections[0].owns = Some(vec!["s".into()]);
    assert!(ir.validate().is_ok());
    ir.sections[0].owns = Some(Vec::new());
    assert!(ir.validate().is_err());
}

/// `multirate_ir` with the multi-rate section reading the rest `lag` samples late.
fn lagged(lag: Option<usize>) -> CircuitIr {
    let mut ir = multirate_ir(Some(16));
    ir.sections[1].lag_samples = lag;
    ir
}

#[test]
fn a_lagged_multirate_part_sees_the_rest_late() {
    // TAPE_SPEED_PLAN.md P2: the multi-rate part reads the stiff node s `lag` samples
    // late (interpolated between published samples), so it runs ahead of the audio part.
    let h = 1.0 / 192_000.0;
    let n = 3000;
    let x: Vec<f64> = (0..n)
        .map(|i| 10.0 + 5.0 * (2.0 * std::f64::consts::PI * 1e3 * i as f64 * h).sin())
        .collect();
    let opts = Options {
        input_order: 1,
        ..Options::with_method(Method::Esdirk4)
    };
    let run = |ir: &CircuitIr| {
        simulate_partitioned(
            ir,
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
    let lock = run(&lagged(None));
    let lag = 33;
    let (a, b) = (run(&lagged(Some(lag))), run(&lagged(Some(lag))));
    // Whatever the threads' timing, the same result.
    for (u, v) in a.values.iter().zip(&b.values) {
        assert!(u.iter().zip(v).all(|(x, y)| x.to_bits() == y.to_bits()));
    }
    // The audio part's node: the fast part's current reaches it on time; only that
    // current's own response to a late s differs (block means, the audio band).
    let block = |s: &[f64], i: usize| s[i..i + 16].iter().sum::<f64>() / 16.0;
    let (s_l, s_a) = (series(&lock, "v(s)"), series(&a, "v(s)"));
    let ds = (200..n - 16)
        .step_by(16)
        .map(|i| (block(s_a, i) - block(s_l, i)).abs())
        .fold(0.0, f64::max);
    // The fast part's node is half s and half the source (R2 = R3): it differs from the
    // lockstep run by half of s's change over the lag - 1 samples it sees s late (at the
    // same samples, so the source cancels).
    let (f_l, f_a) = (series(&lock, "v(f)"), series(&a, "v(f)"));
    let d = lag - 1;
    let (mut worst, mut predicted) = (0.0f64, 0.0f64);
    for i in (200..n - 16).step_by(16) {
        let want = 0.5 * (block(s_l, i - d) - block(s_l, i));
        let got = block(f_a, i) - block(f_l, i);
        worst = worst.max((got - want).abs());
        predicted = predicted.max(want.abs());
    }
    eprintln!("lag {lag}: s {ds:.2e} V, f {worst:.2e} V from the prediction ({predicted:.2e} V)");
    // Measured: s 7.1 mV (its load, f, answers its late view of s), f 3.9% of the change.
    assert!(ds < 2e-2, "v(s) moved {ds} V");
    assert!(
        worst < 0.1 * predicted,
        "v(f) {worst} V from the prediction ({predicted})"
    );
}

#[test]
fn lag_is_checked() {
    let mut ir = lagged(Some(0));
    assert!(ir.validate().is_err());
    ir.sections[1].lag_samples = Some(8);
    ir.sections[1].decimate = Some(circuitsim::ir::Decimate::Fir);
    assert!(ir.validate().is_err());
    let mut ir = multirate_ir(None);
    ir.sections[1].lag_samples = Some(8);
    assert!(ir.validate().is_err());
    assert!(lagged(Some(8)).validate().is_ok());
}

#[test]
fn a_multirate_section_steps_with_its_own_method() {
    // TAPE_SPEED_PLAN.md P4: the multi-rate part's sections name its method (and tube
    // tables); the rest keeps the run's.
    let h = 1.0 / 96_000.0;
    let n = 2000;
    let x: Vec<f64> = (0..n)
        .map(|i| 10.0 + 5.0 * (2.0 * std::f64::consts::PI * 2e3 * i as f64 * h).sin())
        .collect();
    let opts = Options {
        input_order: 1,
        ..Options::with_method(Method::Esdirk4)
    };
    let run = |method: Option<&str>| {
        // 64 steps per sample: the fast part's 0.5 us RC resolved (at 8 a step is longer
        // than it, and the two methods' damping of the 99 kHz drive differs by ~1%).
        let mut ir = multirate_ir(Some(64));
        ir.sections[1].method = method.map(str::to_string);
        ir.validate().unwrap();
        simulate_partitioned(
            &ir,
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
    let (base, same, other) = (run(None), run(Some("esdirk4")), run(Some("trbdf2")));
    // The run's own method named: the same numbers.
    for (u, v) in base.values.iter().zip(&same.values) {
        assert!(u.iter().zip(v).all(|(a, b)| a.to_bits() == b.to_bits()));
    }
    // Another: the fast part steps differently, within its truncation error (of its ~25 V
    // carrier).
    let (f0, f1) = (series(&base, "v(f)"), series(&other, "v(f)"));
    let d = f0
        .iter()
        .zip(f1)
        .fold(0.0f64, |w, (a, b)| w.max((a - b).abs()));
    eprintln!("trbdf2 vs esdirk4 in the fast part: {d:.2e} V");
    assert!(d > 0.0 && d < 0.05, "{d}");
}

#[test]
fn a_sections_method_and_tables_are_checked() {
    let mut ir = multirate_ir(Some(8));
    ir.sections[1].method = Some("rk4".into());
    assert!(ir.validate().is_err());
    let mut ir = multirate_ir(Some(8));
    ir.sections[1].method = Some("trbdf2".into());
    ir.sections[1].tube_tables = Some(true);
    assert!(ir.validate().is_ok());
    // In a single-rate section: refused.
    let mut ir = multirate_ir(None);
    ir.sections[1].method = Some("trbdf2".into());
    assert!(ir.validate().is_err());
    let mut ir = multirate_ir(None);
    ir.sections[1].tube_tables = Some(true);
    assert!(ir.validate().is_err());
}
