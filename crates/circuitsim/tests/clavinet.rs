//! The Clavinet's strings as a medium (docs/CLAVINET_PLAN.md, CL3) on the saved component's
//! data: the same on any number of threads, three outputs driving a circuit, a stream fed
//! notes block by block equal to the whole run. Its agreement with the Python twin is
//! tests/test_clavinet_compiled.py's.

use std::path::Path;
use std::sync::Arc;

use circuitsim::clavinet::{Medium, StrikeTable};
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

/// Strikes from rest replayed from a table, against the same notes computed: equal sample
/// for sample. The notes cover strikes from rest (replayed), one not recorded (computed),
/// a key up mid-replay, a re-strike mid-replay (the state computed up to there), pressure,
/// a re-strike while ringing (computed) and one after the string slept (replayed again).
#[test]
fn replayed_strikes_equal_computed_ones() {
    let Some(el) = strings() else { return };
    let fs = 96_000.0;
    let (model, fs_int, s) = Medium::rates(&el, fs).expect("the strings");
    let first = model.keys[0].note;
    let table = Arc::new(StrikeTable::new(model.clone(), fs_int, s));
    for (note, vel) in [(29u8, 100u8), (41, 60), (53, 127)] {
        table.ensure((note - first) as usize, vel);
    }
    // When key 29, struck and let go mid-strike, has gone to sleep (its output exactly 0).
    let asleep_at = {
        let mut m = Medium::with_strikes(&el, fs, 0, None).expect("the strings");
        m.queue(10, on(29, 100));
        m.queue(400, NoteEvent::Off { note: 29 });
        m.known_until(usize::MAX);
        let y: Vec<[f64; 2]> = (0..400_000).map(|_| m.push()).collect();
        y.iter()
            .rposition(|v| v[0] != 0.0 || v[1] != 0.0)
            .expect("it sounded")
            + 1
    };
    assert!(
        asleep_at < 300_000,
        "key 29 sleeps within ~3 s ({asleep_at})"
    );
    let again = asleep_at + 2000;
    let events = [
        (10, on(29, 100)),
        (13, on(41, 60)),
        (16, on(53, 127)),
        (20, on(65, 30)),
        (400, NoteEvent::Off { note: 29 }),
        (600, on(41, 60)),
        (3000, NoteEvent::Pressure { value: 100 }),
        (4000, NoteEvent::Off { note: 53 }),
        (5000, on(53, 127)),
        (8000, NoteEvent::Off { note: 53 }),
        (again, on(29, 100)),
    ];
    let run = |strikes: Option<Arc<StrikeTable>>| {
        let mut m = Medium::with_strikes(&el, fs, 2, strikes).expect("the strings");
        for &(at, ev) in &events {
            m.queue(at, ev);
        }
        m.known_until(usize::MAX);
        (0..again + 5000).map(|_| m.push()).collect::<Vec<_>>()
    };
    let computed = run(None);
    let replayed = run(Some(table.clone()));
    let first_diff = computed.iter().zip(&replayed).position(|(a, b)| a != b);
    assert_eq!(first_diff, None, "the replay differs");
    assert_eq!(table.filled().0, 3, "nothing else recorded");
    // 29 and 41 and 53 from rest, 29 again after it slept (41's re-strike materializes).
    assert_eq!(table.replays(), 4);
    assert!(computed.iter().any(|v| v[0].abs() > 1e-4), "it sounds");
}

/// The whole table recorded and saved (under cache/clavinet/), then loaded into a second
/// table: equal slot for slot. Slow (every key at every velocity): run by hand,
/// `cargo test --release -p circuitsim --test clavinet -- --ignored`.
#[test]
#[ignore]
fn a_saved_table_loads_back_equal() {
    let Some(el) = strings() else { return };
    let (model, fs_int, s) = Medium::rates(&el, 96_000.0).expect("the strings");
    let a = StrikeTable::new(model.clone(), fs_int, s);
    let t0 = std::time::Instant::now();
    a.load_or_fill(
        std::thread::available_parallelism().map_or(4, |n| n.get()),
        || {},
    )
    .expect("saved");
    eprintln!(
        "filled or loaded in {:.1} s, {} MB",
        t0.elapsed().as_secs_f64(),
        a.bytes() / 1_000_000
    );
    assert!(a.complete());
    let b = StrikeTable::new(model, fs_int, s);
    b.load_or_fill(1, || {}).expect("loaded");
    assert!(b.complete());
    assert!(a.same_as(&b));
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
