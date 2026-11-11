//! The Nickel Organ's Rust voice against the Python reference (varimu/nickel/voice.py), from
//! `scripts/export_nickel_fixture.py` (rerun it after a change to the voice or its config) and
//! the compiled organ `NICKEL_ORGAN` (`scripts/compile_nickel_organ.py`); and the keyboard as
//! a keyed medium (`nickel::Medium`, the IR's `NickelKeys`).

use std::path::PathBuf;
use std::sync::Arc;

use circuitsim::ir::NickelKeys;
use circuitsim::media::NoteEvent;
use circuitsim::nickel::{Medium, Model, Voice};
use serde_json::Value;

fn repo() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../..")
}

/// The latest version of the compiled organ: (its data's path relative to the repository,
/// the sha256 its version names).
fn latest() -> (String, String) {
    let dir = repo().join("config/components/nickel_organ");
    let n = std::fs::read_dir(&dir)
        .expect("config/components/nickel_organ (scripts/compile_nickel_organ.py)")
        .filter_map(|e| {
            let f = e.ok()?.file_name().to_string_lossy().into_owned();
            f.strip_suffix(".yaml")?.parse::<u32>().ok()
        })
        .max()
        .expect("a version");
    let yaml = std::fs::read_to_string(dir.join(format!("{n}.yaml"))).expect("version");
    let sha = yaml
        .lines()
        .skip_while(|l| l.trim_end() != "data:")
        .find_map(|l| l.trim().strip_prefix("sha256: "))
        .expect("data.sha256")
        .to_string();
    (
        format!("config/components/nickel_organ/{n}.organ.json"),
        sha,
    )
}

fn model() -> Arc<Model> {
    let text = std::fs::read_to_string(repo().join(latest().0)).expect("the compiled organ");
    Arc::new(Model::from_json(&text).expect("model"))
}

/// The keys' element at the reference's rates (96 kHz line outs, 192 kHz physics).
fn keys(sustain: f64, polarize: f64, max_keys: f64) -> NickelKeys {
    let (data, sha256) = latest();
    NickelKeys {
        name: "VKEYS".into(),
        out: "out".into(),
        data,
        sha256,
        rate_hz: 96_000.0,
        step_hz: 192_000.0,
        sustain,
        polarize,
        max_keys,
    }
}

fn on(note: u8, velocity: u8) -> NoteEvent {
    NoteEvent::On { note, velocity }
}

fn floats(v: &Value) -> Vec<f64> {
    v.as_array()
        .expect("array")
        .iter()
        .map(|x| x.as_f64().expect("f64"))
        .collect()
}

/// The difference's rms against the reference's rms, dB.
fn err_db(got: &[f64], want: &[f64]) -> f64 {
    assert_eq!(got.len(), want.len());
    let num: f64 = got.iter().zip(want).map(|(a, b)| (a - b).powi(2)).sum();
    let den: f64 = want.iter().map(|b| b * b).sum();
    10.0 * (num / den.max(1e-300)).max(1e-300).log10()
}

#[test]
fn a_struck_key_matches_the_python_reference() {
    let m = model();
    let text =
        std::fs::read_to_string(repo().join("crates/circuitsim/tests/fixtures/nickel/voice.json"))
            .expect("fixture (scripts/export_nickel_fixture.py)");
    let fx: Value = serde_json::from_str(&text).expect("json");
    for c in fx["cases"].as_array().expect("cases") {
        let note = c["note"].as_u64().unwrap() as u8;
        let (sustain, polarize) = (
            c["sustain"].as_f64().unwrap(),
            c["polarize"].as_f64().unwrap(),
        );
        let (hold, rel) = (floats(&c["hold"]), floats(&c["release"]));
        let mut v = Voice::new(&m, note, 2, None).expect("voice");
        v.power_on(polarize);
        v.strike(c["velocity"].as_u64().unwrap() as u8);
        let mut y1 = vec![0.0; hold.len()];
        v.run(&mut y1, sustain, polarize, 0.0);
        v.release();
        let mut y2 = vec![0.0; rel.len()];
        v.run(&mut y2, sustain, polarize, 0.0);
        let (e1, e2) = (err_db(&y1, &hold), err_db(&y2, &rel));
        let rms = (hold.iter().map(|x| x * x).sum::<f64>() / hold.len() as f64).sqrt();
        eprintln!("note {note}: held {e1:.1} dB, released {e2:.1} dB (rms {rms:.3} V)");
        assert!(rms > 1e-3, "the reference is silent");
        assert!(e1 < -80.0 && e2 < -80.0, "note {note}: {e1} / {e2} dB");
        let m1 = c["m1"].as_f64().unwrap();
        assert!((v.m1() - m1).abs() < 1e-6 * m1.abs().max(1.0));
    }
}

#[test]
fn the_medium_at_96_khz_is_the_reference_voice_bit_for_bit() {
    // One key through the keyboard (powered on at load, struck at step 100, released at
    // 30000) against the voice run as the reference runs it: the same samples times its
    // mixing gain, the medium's one step later.
    let m = model();
    let (note, sustain, polarize) = (69u8, 0.75, 0.35);
    let el = keys(sustain, polarize, 8.0);
    let (at, off, n) = (100usize, 30_000usize, 40_000usize);
    let got = circuitsim::nickel::render(
        &el,
        96_000.0,
        n,
        &[(at, on(note, 100)), (off, NoteEvent::Off { note })],
        None,
        2,
    )
    .expect("render");
    let mut v = Voice::new(&m, note, 2, None).expect("voice");
    v.power_on(polarize);
    v.strike(100);
    let mut y = vec![0.0; off - at];
    v.run(&mut y, sustain, polarize, 0.0);
    v.release();
    let mut y2 = vec![0.0; n - off];
    v.run(&mut y2, sustain, polarize, 0.0);
    y.extend(y2);
    let mix = m.key(note).expect("key").mix;
    let mut want = vec![0.0; n];
    for (i, x) in y.iter().enumerate() {
        if at + 1 + i < n {
            want[at + 1 + i] = 0.0 + mix * x;
        }
    }
    let first = got.iter().zip(&want).position(|(a, b)| a != b);
    // A released key stops once quiet (its line out frozen at zero from then).
    let quiet = first.map(|i| i > off && want[i..].iter().all(|x| x.abs() < 0.05));
    assert!(
        first.is_none() || quiet == Some(true),
        "the medium differs from the voice at sample {first:?}"
    );
    assert!(got.iter().any(|x| x.abs() > 0.1), "silent");
}

#[test]
fn the_keys_are_the_same_on_any_number_of_threads() {
    let el = keys(0.75, 0.35, 8.0);
    let evs: Vec<(usize, NoteEvent)> = [48u8, 55, 60, 64, 67, 72]
        .iter()
        .enumerate()
        .map(|(i, &n)| (50 + 300 * i, on(n, 60 + 10 * i as u8)))
        .chain([(9_000, NoteEvent::Off { note: 55 })])
        .collect();
    let a = circuitsim::nickel::render(&el, 96_000.0, 12_000, &evs, Some(1), 0).expect("a");
    let b = circuitsim::nickel::render(&el, 96_000.0, 12_000, &evs, Some(1), 3).expect("b");
    assert_eq!(a, b);
    assert!(a.iter().any(|x| x.abs() > 0.1), "silent");
}

#[test]
fn a_chord_plays_and_goes_quiet() {
    let el = keys(0.75, 0.35, 8.0);
    let mut m = Medium::with_workers(&el, 96_000.0, Some(1), 2).expect("medium");
    for n in [60u8, 64, 67] {
        m.queue(10, on(n, 90));
    }
    for n in [60u8, 64, 67] {
        m.queue(96_000, NoteEvent::Off { note: n });
    }
    m.known_until(usize::MAX);
    let mut peak: f64 = 0.0;
    for _ in 0..96_000 {
        peak = peak.max(m.push().abs());
    }
    assert!(peak > 0.01, "silent: {peak}");
    assert_eq!(m.sounding(), 3);
    for _ in 0..4 * 96_000 {
        m.push();
    }
    assert_eq!(m.sounding(), 0, "released keys stop once quiet");
}

#[test]
fn a_key_past_the_cap_silences_a_released_one_first() {
    // Two keys at most: 60 and 64 held, 64 released, 67 struck: 64 stops (keys up first),
    // 60 sounds on.
    let el = keys(0.75, 0.35, 2.0);
    let mut m = Medium::with_workers(&el, 96_000.0, None, 0).expect("medium");
    m.queue(0, on(60, 90));
    m.queue(1_000, on(64, 90));
    m.queue(2_000, NoteEvent::Off { note: 64 });
    m.queue(2_500, on(67, 90));
    m.known_until(usize::MAX);
    for _ in 0..2_400 {
        m.push();
    }
    assert_eq!(m.sounding(), 2);
    for _ in 0..1_000 {
        m.push();
    }
    assert_eq!(m.sounding(), 2, "the cap holds");
    // 67 and 60 sound: a fourth key (60 the oldest held, 67 newer) silences 60.
    m.queue(4_000, on(72, 90));
    for _ in 0..1_000 {
        m.push();
    }
    assert_eq!(m.sounding(), 2);
}

#[test]
fn the_panel_plays_on_and_a_new_organ_does_not() {
    let el = keys(0.5, 0.35, 8.0);
    let mut m = Medium::with_workers(&el, 96_000.0, None, 0).expect("medium");
    let turned = keys(0.9, 0.2, 8.0);
    assert!(m.same(&turned));
    m.update(&turned);
    assert_eq!((m.el.sustain, m.el.polarize), (0.9, 0.2));
    assert!(!m.same(&keys(0.9, 0.2, 4.0)), "a new cap is another organ");
    // At 48 kHz the line outs run at 96 kHz (k = 2, decimated) stepped at 192 kHz.
    assert_eq!(Medium::rates(&el, 48_000.0), (2, 2));
    assert_eq!(Medium::rates(&el, 96_000.0), (1, 2));
    assert_eq!(Medium::rates(&el, 192_000.0), (1, 1));
}
