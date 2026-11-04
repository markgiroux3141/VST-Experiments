//! The harp medium (docs/RHODES_PLAN.md, RH3) on the saved component's data: the same on any
//! number of threads, events landing where they're queued, a circuit driven by it. Its
//! agreement with the Python reference is tests/test_rhodes_compiled.py's.

use std::path::Path;

use circuitsim::harp::{HarpModel, Medium};
use circuitsim::ir::Harp;
use circuitsim::media::NoteEvent;

/// The saved harp (None when the component isn't there: a checkout without it).
fn harp(rate_hz: f64) -> Option<Harp> {
    let path =
        Path::new(env!("CARGO_MANIFEST_DIR")).join("../../config/components/mk1_harp/1.harp.json");
    let text = std::fs::read_to_string(path).ok()?;
    let model: HarpModel = serde_json::from_str(&text).expect("a harp model");
    model.check().expect("valid");
    Some(Harp {
        name: "VHARP".into(),
        out: "h".into(),
        rate_hz,
        contact_rate_hz: 384_000.0,
        model: Box::new(model),
    })
}

fn chord(m: &mut Medium, at: usize, notes: &[u8], vel: u8) {
    for (i, &n) in notes.iter().enumerate() {
        m.queue(
            at + 3 * i,
            NoteEvent::On {
                note: n,
                velocity: vel,
            },
        );
    }
}

fn play(el: &Harp, workers: usize, n: usize) -> Vec<f64> {
    let mut m = Medium::with_workers(el, 48_000.0, workers);
    m.queue(10, NoteEvent::Pedal { down: true });
    // Every key: the threads take over past a few voices.
    let all: Vec<u8> = el.model.keys.iter().map(|k| k.note as u8).collect();
    chord(&mut m, 20, &all, 90);
    m.queue(3000, NoteEvent::Pedal { down: false });
    chord(&mut m, 4000, &[40, 52, 64], 110);
    m.known_until(usize::MAX);
    (0..n).map(|_| m.push()).collect()
}

#[test]
fn the_threads_dont_change_a_sample() {
    let Some(el) = harp(96_000.0) else { return };
    let one = play(&el, 0, 6000);
    let three = play(&el, 3, 6000);
    assert_eq!(one, three);
    assert!(one.iter().any(|v| v.abs() > 1e-3), "it sounds");
}

#[test]
fn an_event_lands_at_its_step_and_a_late_one_at_the_next() {
    let Some(el) = harp(96_000.0) else { return };
    let fs = 48_000.0;
    // On time: nothing before the strike's step (k = 2: one internal sample of contact
    // reaches the step after).
    let mut m = Medium::with_workers(&el, fs, 0);
    m.keep_raw();
    m.queue(
        100,
        NoteEvent::On {
            note: 60,
            velocity: 100,
        },
    );
    m.known_until(usize::MAX);
    let y: Vec<f64> = (0..400).map(|_| m.push()).collect();
    let raw = m.raw();
    assert!(raw[..200].iter().all(|v| *v == 0.0));
    assert!(raw[200..210].iter().any(|v| *v != 0.0));
    assert!(y.iter().any(|v| v.abs() > 1e-6));
    // Late: queued after its step was rendered, it lands at the first step not rendered.
    let mut late = Medium::with_workers(&el, fs, 0);
    late.keep_raw();
    for _ in 0..150 {
        late.push();
    }
    late.queue(
        100,
        NoteEvent::On {
            note: 60,
            velocity: 100,
        },
    );
    late.known_until(usize::MAX);
    for _ in 150..400 {
        late.push();
    }
    let lr = late.raw();
    let first = lr.iter().position(|v| *v != 0.0).expect("it sounds");
    assert!((300..306).contains(&first), "first sample {first}");
}

#[test]
fn a_released_key_stops_and_the_pedal_holds_it() {
    let Some(el) = harp(96_000.0) else { return };
    let fs = 48_000.0;
    let rms = |v: &[f64]| (v.iter().map(|x| x * x).sum::<f64>() / v.len() as f64).sqrt();
    let run = |pedal: bool| {
        let mut m = Medium::with_workers(&el, fs, 0);
        if pedal {
            m.queue(1, NoteEvent::Pedal { down: true });
        }
        m.queue(
            10,
            NoteEvent::On {
                note: 57,
                velocity: 100,
            },
        );
        m.queue(4800, NoteEvent::Off { note: 57 });
        m.known_until(usize::MAX);
        let y: Vec<f64> = (0..24_000).map(|_| m.push()).collect();
        (rms(&y[3800..4800]), rms(&y[19_200..24_000]))
    };
    let (held, damped) = run(false);
    let (held_p, ringing) = run(true);
    assert_eq!(held, held_p);
    // The felt: down by far more than 40 dB 0.3 s after the key came up (its T60 0.15 s).
    assert!(damped < held * 1e-3, "{damped} vs {held}");
    // The pedal: the key rings on (A3's Q ~1000: a few dB in 0.4 s).
    assert!(ringing > held * 0.3, "{ringing} vs {held}");
}

/// A harp into a load: its EMF behind 1.4 kOhm across 100 kOhm, the probe on the load.
fn circuit(el: Harp) -> circuitsim::ir::CircuitIr {
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
        title: "harp into a load".into(),
        input_node: "in".into(),
        probes: vec![Probe::Voltage { node: "o".into() }],
        models: vec![],
        sections: vec![Section {
            title: "harp".into(),
            elements: vec![
                Element::Harp(el),
                r("RCOILS", "h", "o", 1400.0),
                r("RLOAD", "o", "0", 100e3),
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
    let Some(el) = harp(96_000.0) else { return };
    let ir = circuit(el);
    let fs = 96_000.0;
    let opts = Options {
        method: Method::Esdirk4,
        ..Options::default()
    };
    let n = 9600;
    let x = vec![0.0; n];
    let notes = [
        (
            500,
            NoteEvent::On {
                note: 45,
                velocity: 110,
            },
        ),
        (2400, NoteEvent::Pedal { down: true }),
        (
            3000,
            NoteEvent::On {
                note: 69,
                velocity: 80,
            },
        ),
        (5000, NoteEvent::Off { note: 45 }),
        (8000, NoteEvent::Pedal { down: false }),
    ];
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
    .values
    .remove(0);
    let coupling = circuitsim::partition::Coupling::parse("hold").unwrap();
    let mut stream = Stream::new(&ir, &[], coupling, 1.0 / fs, &opts, 0.0).unwrap();
    let mut y = vec![stream.initial()[0]];
    for (b, block) in x[1..].chunks(480).enumerate() {
        let a = 1 + 480 * b;
        let here: Vec<_> = notes
            .iter()
            .filter(|(at, _)| (a..a + block.len()).contains(at))
            .map(|&(at, e)| (at - a, e))
            .collect();
        stream.queue_notes(&here).unwrap();
        y.extend(stream.process(block).unwrap().remove(0));
    }
    y.extend(stream.finish().unwrap().remove(0));
    assert_eq!(y.len(), whole.len());
    assert_eq!(y, whole, "a stream equals the whole run");
    // Silent before the first strike: the medium pushed at sample 500 drives 501 on.
    assert!(whole[..501].iter().all(|v| *v == 0.0));
    assert!(whole[501] != 0.0);
    assert!(whole[600..2400].iter().any(|v| v.abs() > 1e-4));
}
