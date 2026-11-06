//! The Clavinet's strings as a medium (docs/CLAVINET_PLAN.md, CL3) on the saved component's
//! data: the same on any number of threads, three outputs driving a circuit, a stream fed
//! notes block by block equal to the whole run. Its agreement with the Python twin is
//! tests/test_clavinet_compiled.py's.

use std::path::Path;

use circuitsim::clavinet::Medium;
use circuitsim::ir::ClavStrings;
use circuitsim::media::NoteEvent;

/// The saved strings' element (None when the component isn't there: a checkout without it).
fn strings() -> Option<ClavStrings> {
    let dir = Path::new(env!("CARGO_MANIFEST_DIR")).join("../../config/components/d6_strings");
    let header = std::fs::read_to_string(dir.join("1.strings.json")).ok()?;
    let h: serde_json::Value = serde_json::from_str(&header).expect("a header");
    Some(ClavStrings {
        name: "VSTRINGS".into(),
        centre: "ec".into(),
        bridge: "eb".into(),
        bridge_neg: "ebn".into(),
        rate_hz: 96_000.0,
        contact_rate_hz: 1_536_000.0,
        data: "config/components/d6_strings/1.strings.json".into(),
        sha256: h["binary"]["sha256"].as_str().expect("a sha").into(),
    })
}

fn on(note: u8, velocity: u8) -> NoteEvent {
    NoteEvent::On { note, velocity }
}

/// Ten bass keys and a chord over them, pressure, releases.
fn notes() -> Vec<(usize, NoteEvent)> {
    let mut v: Vec<(usize, NoteEvent)> = (0..10)
        .map(|i| (10 + 7 * i, on(29 + i as u8, 100)))
        .collect();
    v.extend([
        (2000, on(60, 90)),
        (2003, on(64, 90)),
        (2006, on(67, 90)),
        (3000, NoteEvent::Pressure { value: 100 }),
        (4000, NoteEvent::Off { note: 60 }),
        (4500, NoteEvent::Off { note: 29 }),
    ]);
    v
}

fn play(el: &ClavStrings, workers: usize, n: usize) -> Vec<[f64; 2]> {
    let mut m = Medium::with_workers(el, 96_000.0, workers).expect("the strings");
    for (at, ev) in notes() {
        m.queue(at, ev);
    }
    m.known_until(usize::MAX);
    (0..n).map(|_| m.push()).collect()
}

#[test]
fn the_threads_dont_change_a_sample() {
    let Some(el) = strings() else { return };
    let one = play(&el, 0, 6000);
    let three = play(&el, 3, 6000);
    assert_eq!(one, three);
    assert!(one.iter().any(|v| v[0].abs() > 1e-3), "it sounds");
}

#[test]
fn a_wrong_sidecar_is_refused() {
    let Some(mut el) = strings() else { return };
    el.sha256 = "0".repeat(64);
    let err = Medium::with_workers(&el, 96_000.0, 0).unwrap_err();
    assert!(err.contains("pins"), "{err}");
}

/// The strings into loads: each output across 10 kOhm, the probes on all three.
fn circuit(el: ClavStrings) -> circuitsim::ir::CircuitIr {
    use circuitsim::ir::{CircuitIr, Element, Probe, Resistor, Section};
    let r = |name: &str, a: &str, b: &str, ohm: f64| {
        Element::Resistor(Resistor {
            name: name.into(),
            a: a.into(),
            b: b.into(),
            r_ohm: ohm,
        })
    };
    let ir = CircuitIr {
        version: circuitsim::ir::IR_VERSION,
        title: "strings into loads".into(),
        input_node: "in".into(),
        probes: ["ec", "eb", "ebn"]
            .iter()
            .map(|n| Probe::Voltage { node: (*n).into() })
            .collect(),
        models: vec![],
        sections: vec![Section {
            title: "strings".into(),
            elements: vec![
                Element::ClavStrings(el),
                r("RC", "ec", "0", 10e3),
                r("RB", "eb", "0", 10e3),
                r("RN", "ebn", "0", 10e3),
                r("RIN", "in", "0", 1e6),
            ],
            substeps: None,
            decimate: None,
            owns: None,
        }],
        controls: vec![],
        noise: None,
        heaters: None,
    };
    ir.validate().expect("valid");
    ir
}

#[test]
fn a_stream_fed_notes_block_by_block_plays_the_whole_run() {
    use circuitsim::stream::Stream;
    use circuitsim::transient::{Method, Options, simulate_notes};
    let Some(el) = strings() else { return };
    let direct = play(&el, 0, 5999);
    let ir = circuit(el);
    let fs = 96_000.0;
    let opts = Options {
        method: Method::Esdirk4,
        ..Options::default()
    };
    let n = 6000;
    let x = vec![0.0; n];
    let notes = notes();
    let whole = simulate_notes(
        &ir,
        &x,
        &[],
        &notes,
        1.0 / fs,
        &opts,
        usize::MAX,
        |_| Ok(()),
    )
    .unwrap()
    .values;
    let coupling = circuitsim::partition::Coupling::parse("hold").unwrap();
    let mut stream = Stream::new(&ir, &[], coupling, 1.0 / fs, &opts, 0.0).unwrap();
    let mut y: Vec<Vec<f64>> = stream.initial().into_iter().map(|v| vec![v]).collect();
    for (b, block) in x[1..].chunks(480).enumerate() {
        let a = 1 + 480 * b;
        let here: Vec<_> = notes
            .iter()
            .filter(|(at, _)| (a..a + block.len()).contains(at))
            .map(|&(at, e)| (at - a, e))
            .collect();
        stream.queue_notes(&here).unwrap();
        for (v, o) in y.iter_mut().zip(stream.process(block).unwrap()) {
            v.extend(o);
        }
    }
    for (v, o) in y.iter_mut().zip(stream.finish().unwrap()) {
        v.extend(o);
    }
    assert_eq!(y, whole, "a stream equals the whole run");
    // The outputs are the medium's, a sample on (to the solve's rounding): the centre, the
    // bridge and its negation.
    let near = |a: f64, b: f64| (a - b).abs() <= 1e-12 * b.abs().max(1e-9);
    for (i, d) in direct.iter().enumerate() {
        assert!(near(whole[0][i + 1], d[0]), "{i}");
        assert!(near(whole[1][i + 1], d[1]), "{i}");
        assert!(near(whole[2][i + 1], -d[1]), "{i}");
    }
}
