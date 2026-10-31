//! A plate in a circuit (docs/REVERB_PLAN.md, E2): its force sensed after each sample,
//! its pickup driven one sample later, equal to its impulse response convolved with the
//! force; the same in a whole run, a stream and a partitioned run.

use circuitsim::ir::{CircuitIr, Control, Element, IR_VERSION, Plate, Probe, Resistor, Section};
use circuitsim::partition::{Coupling, simulate_partitioned_controls};
use circuitsim::plate::response;
use circuitsim::stream::Stream;
use circuitsim::transient::{Method, Options, simulate, simulate_controls};

fn resistor(name: &str, a: &str, b: &str, r_ohm: f64) -> Element {
    Element::Resistor(Resistor {
        name: name.into(),
        a: a.into(),
        b: b.into(),
        r_ohm,
    })
}

fn plate() -> Plate {
    Plate {
        name: "VPL".into(),
        sense_pos: "s".into(),
        sense_neg: "0".into(),
        force_per_v: 2.0,
        out: "p".into(),
        out_per_m_s2: 1e-3,
        lx_m: 2.0,
        ly_m: 1.0,
        thickness_m: 0.5e-3,
        density_kg_m3: 7872.0,
        youngs_pa: 2e11,
        poisson: 0.3,
        tension_n_m: 600.0,
        drive_xy: [0.52, 0.53],
        pickup_xy: [0.47, 0.62],
        f_max_hz: 1_500.0,
        decay: vec![[100.0, 8.0], [1000.0, 12.0]],
        tail_db: 40.0,
    }
}

/// The input across a divider (in -- 100 -- s -- 100 -- 0): the plate senses s; its
/// pickup p into 1k; a control `g` into its own resistor; a second section to partition.
fn circuit(controls: bool) -> CircuitIr {
    let mut audio = vec![
        resistor("R1", "in", "s", 100.0),
        resistor("R2", "s", "0", 100.0),
        Element::Plate(plate()),
        resistor("RO", "p", "o", 1e3),
        resistor("RL", "o", "0", 1e3),
        resistor("RT", "o", "x", 1e9),
    ];
    if controls {
        audio.push(resistor("RG", "g", "0", 1e3));
    }
    let ir = CircuitIr {
        version: IR_VERSION,
        title: "plate".into(),
        input_node: "in".into(),
        controls: if controls {
            vec![Control {
                name: "gate".into(),
                node: "g".into(),
            }]
        } else {
            vec![]
        },
        noise: None,
        heaters: None,
        probes: ["o", "s", "g", "x"]
            .iter()
            .filter(|n| controls || **n != "g")
            .map(|n| Probe::Voltage { node: (*n).into() })
            .collect(),
        models: vec![],
        sections: vec![
            Section {
                title: "audio".into(),
                elements: audio,
            },
            Section {
                title: "other".into(),
                elements: vec![resistor("R3", "x", "0", 1e5)],
            },
        ],
    };
    ir.validate().unwrap();
    ir
}

fn opts() -> Options {
    Options {
        method: Method::Esdirk4,
        input_order: 1,
        ..Options::default()
    }
}

fn input(n: usize) -> Vec<f64> {
    (0..n)
        .map(|i| {
            let t = i as f64 / 8000.0;
            (2.0 * std::f64::consts::PI * 220.0 * t).sin() * (-30.0 * t).exp()
                + if i == 3 { 1.0 } else { 0.0 }
        })
        .collect()
}

/// What the pickup should read: half the input (the divider) times the force per volt,
/// through the response, times the sensitivity, then divided by RO and RL.
fn expected(x: &[f64], fs: f64) -> Vec<f64> {
    let p = plate();
    let h = response(&p, fs);
    (0..x.len())
        .map(|n| {
            let a: f64 = (1..=n.min(h.len() - 1))
                .map(|k| h[k] * p.force_per_v * 0.5 * x[n - k])
                .sum();
            // RO into RL, which RT and R3 (to the second section) load a little.
            let rl = 1.0 / (1.0 / 1e3 + 1.0 / (1e9 + 1e5));
            rl / (1e3 + rl) * p.out_per_m_s2 * a
        })
        .collect()
}

fn max_err(a: &[f64], b: &[f64]) -> (f64, f64) {
    let err = a
        .iter()
        .zip(b)
        .map(|(p, q)| (p - q).abs())
        .fold(0.0, f64::max);
    let peak = b.iter().fold(0.0f64, |m, v| m.max(v.abs()));
    (err, peak)
}

#[test]
fn the_pickup_is_the_response_convolved_with_the_force() {
    let fs = 8000.0;
    let x = input(3000);
    let out = simulate(&circuit(false), &x, 1.0 / fs, &opts()).unwrap();
    let o = &out.values[out.names.iter().position(|n| n == "v(o)").unwrap()];
    let (err, peak) = max_err(o, &expected(&x, fs));
    assert!(peak > 1e-9, "the plate rings: {peak}");
    assert!(err < 1e-9 * peak, "{err} vs {peak}");
}

#[test]
fn controls_streams_and_partitions_see_the_same_plate() {
    let fs = 8000.0;
    let x = input(2000);
    let gate: Vec<f64> = (0..x.len()).map(|i| (i % 400) as f64 / 400.0).collect();
    let ir = circuit(true);
    let whole =
        simulate_controls(&ir, &x, &[&gate], 1.0 / fs, &opts(), usize::MAX, |_| Ok(())).unwrap();
    let col = |o: &circuitsim::Output, n: &str| {
        o.values[o.names.iter().position(|m| m == n).unwrap()].clone()
    };
    let (err, peak) = max_err(&col(&whole, "v(o)"), &expected(&x, fs));
    assert!(err < 1e-9 * peak, "with a control: {err} vs {peak}");
    // The control input still drives its own node.
    let g = col(&whole, "v(g)");
    assert!((g[1234] - gate[1234]).abs() < 1e-9);

    // A stream, block by block, equals the whole run.
    let mut s = Stream::with_controls(
        &ir,
        &[],
        Coupling::Hold,
        1.0 / fs,
        &opts(),
        x[0],
        &[gate[0]],
    )
    .unwrap();
    let mut got: Vec<Vec<f64>> = s.initial().into_iter().map(|v| vec![v]).collect();
    for (a, b) in [(1, 97), (97, 1001), (1001, x.len())] {
        for (v, y) in got
            .iter_mut()
            .zip(s.process_with(&x[a..b], &[&gate[a..b]]).unwrap())
        {
            v.extend(y);
        }
    }
    for (v, y) in got.iter_mut().zip(s.finish().unwrap()) {
        v.extend(y);
    }
    assert_eq!(got, whole.values, "stream vs whole");

    // Partitioned (the second section on its own thread): the plate stays in the first.
    let part = simulate_partitioned_controls(
        &ir,
        &["other".to_string()],
        Coupling::Hold,
        &x,
        &[&gate],
        1.0 / fs,
        &opts(),
        usize::MAX,
        |_| Ok(()),
    )
    .unwrap();
    let (err, peak) = max_err(&col(&part, "v(o)"), &expected(&x, fs));
    assert!(err < 1e-9 * peak, "partitioned: {err} vs {peak}");
}
