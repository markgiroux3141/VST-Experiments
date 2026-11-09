//! The Nickel Organ's Rust voice against the Python reference (varimu/nickel/voice.py), from
//! `scripts/export_nickel_fixture.py` (rerun it after a change to the voice or its config) and
//! `scripts/compile_nickel_organ.py`'s `config/nickel/organ.live.json`.

use std::path::PathBuf;
use std::sync::Arc;

use circuitsim::nickel::{Model, Organ, Voice};
use serde_json::Value;

fn repo() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../..")
}

fn model() -> Arc<Model> {
    let text = std::fs::read_to_string(repo().join("config/nickel/organ.live.json"))
        .expect("config/nickel/organ.live.json (scripts/compile_nickel_organ.py)");
    Arc::new(Model::from_json(&text).expect("model"))
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
fn the_organ_plays_a_chord_and_goes_quiet() {
    let m = model();
    let mut o = Organ::new(m, 2, Some(1), 2);
    let mut buf = vec![0.0; 960];
    for n in [60u8, 64, 67] {
        o.note_on(n, 90);
    }
    let mut peak: f64 = 0.0;
    for _ in 0..100 {
        o.render(&mut buf);
        peak = buf.iter().fold(peak, |p, x| p.max(x.abs()));
    }
    assert!(peak > 0.01, "silent: {peak}");
    assert_eq!(o.running(), 3);
    for n in [60u8, 64, 67] {
        o.note_off(n);
    }
    for _ in 0..400 {
        o.render(&mut buf);
    }
    assert_eq!(o.running(), 0, "released keys stop once quiet");
}
