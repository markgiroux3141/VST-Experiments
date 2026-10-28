//! Audio files in and out. Loading equals `varimu.sim.io.load_audio` bit for bit (the
//! clips in data/clips, 16-bit and float, mono and stereo, 44.1 kHz: checked
//! 2026-10-27; they aren't committed, so this test writes its own files).

use std::path::PathBuf;

use varimu_app::audio::{decode, load, write_wav};
use varimu_app::resample::{Pad, resample_poly};

fn tmp(name: &str) -> PathBuf {
    let dir = std::env::temp_dir().join(format!("varimu-app-test-{}", std::process::id()));
    std::fs::create_dir_all(&dir).unwrap();
    dir.join(name)
}

#[test]
fn stereo_pcm16_loads_as_numpys_mean() {
    let path = tmp("stereo16.wav");
    let spec = hound::WavSpec {
        channels: 2,
        sample_rate: 48_000,
        bits_per_sample: 16,
        sample_format: hound::SampleFormat::Int,
    };
    let mut w = hound::WavWriter::create(&path, spec).unwrap();
    let frames: Vec<(i16, i16)> = (0..1000)
        .map(|i| ((i * 37 % 6000) as i16 - 3000, -(i as i16)))
        .collect();
    for &(l, r) in &frames {
        w.write_sample(l).unwrap();
        w.write_sample(r).unwrap();
    }
    w.finalize().unwrap();

    let d = decode(&path).unwrap();
    assert_eq!((d.channels.len(), d.rate, d.frames()), (2, 48_000, 1000));
    let mono = d.mono();
    for (m, &(l, r)) in mono.iter().zip(&frames) {
        // libsndfile's scaling, then (l + r) / 2.
        assert_eq!(*m, (l as f64 / 32768.0 + r as f64 / 32768.0) / 2.0);
    }
    // At 96 kHz: scipy's resample_poly with zero padding (load_audio).
    let x = load(&path, 96_000).unwrap();
    assert_eq!(x, resample_poly(&mono, 2, 1, Pad::Zero));
}

#[test]
fn float_wav_round_trips() {
    let path = tmp("float.wav");
    let x: Vec<f64> = (0..500).map(|i| ((i as f64) * 0.01).sin() * 0.9).collect();
    write_wav(&path, &x, 96_000).unwrap();
    let y = load(&path, 96_000).unwrap();
    assert_eq!(y.len(), x.len());
    for (a, b) in x.iter().zip(&y) {
        assert_eq!(*b, *a as f32 as f64);
    }
}

#[test]
fn not_audio_is_an_error() {
    let path = tmp("not_audio.wav");
    std::fs::write(&path, b"hello").unwrap();
    let e = load(&path, 96_000).unwrap_err();
    assert!(e.contains("not_audio.wav"), "{e}");
}
