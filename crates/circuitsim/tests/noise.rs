//! The noise streams against the Python reference (`varimu/devices/noise.py`, exported by
//! `scripts/export_circuit_fixtures.py` into `fixtures/noise/`): Philox's raw words bit for
//! bit, the normals and the flicker filter to the last bits of libm.

use std::collections::BTreeMap;
use std::fs;
use std::path::Path;

use circuitsim::noise::{self, Flicker, FlickerFilter};
use serde::Deserialize;

#[derive(Deserialize)]
struct Fixture {
    rate_hz: f64,
    streams: Vec<Stream>,
    flicker: FlickerFix,
}

#[derive(Deserialize)]
struct Stream {
    seed: u64,
    name: String,
    stream: u32,
    key: [String; 2],
    words: Vec<[String; 4]>,
    starts: BTreeMap<String, Vec<f64>>,
}

#[derive(Deserialize)]
struct FlickerFix {
    poles: Vec<f64>,
    residues: Vec<f64>,
    direct: f64,
    gain: f64,
    start_chol: Vec<f64>,
    seed: u64,
    name: String,
    samples: Vec<f64>,
}

fn fixture() -> Fixture {
    let path = Path::new(env!("CARGO_MANIFEST_DIR")).join("tests/fixtures/noise/noise.json");
    serde_json::from_str(&fs::read_to_string(path).unwrap()).unwrap()
}

fn close(a: f64, b: f64, rel: f64, what: &str) {
    assert!(
        (a - b).abs() <= rel * b.abs().max(1e-300),
        "{what}: {a} vs {b}"
    );
}

#[test]
fn philox_words_equal_numpys() {
    for s in fixture().streams {
        let k = noise::key(s.seed, &s.name, s.stream);
        assert_eq!(k[0].to_string(), s.key[0]);
        assert_eq!(k[1].to_string(), s.key[1]);
        for (b, row) in s.words.iter().enumerate() {
            let w = noise::philox(b as u64 + 1, k);
            for (x, y) in w.iter().zip(row) {
                assert_eq!(x.to_string(), *y, "{} block {b}", s.name);
            }
        }
    }
}

#[test]
fn normals_equal_the_reference() {
    for s in fixture().streams {
        let k = noise::key(s.seed, &s.name, s.stream);
        for (start, want) in &s.starts {
            let mut got = vec![0.0; want.len()];
            noise::normals(k, start.parse().unwrap(), &mut got);
            for (g, w) in got.iter().zip(want) {
                close(*g, *w, 1e-14, &s.name);
            }
        }
    }
}

#[test]
fn flicker_equals_the_reference() {
    let fx = fixture();
    let f = &fx.flicker;
    let d = FlickerFilter::new(fx.rate_hz);
    for (a, b) in d.poles.iter().zip(&f.poles) {
        close(*a, *b, 1e-15, "pole");
    }
    for (a, b) in d.residues.iter().zip(&f.residues) {
        close(*a, *b, 1e-12, "residue");
    }
    close(d.direct, f.direct, 1e-12, "direct");
    close(d.gain, f.gain, 1e-12, "gain");
    let scale = f.start_chol.iter().fold(0.0f64, |m, x| m.max(x.abs()));
    for (a, b) in d.start_chol.iter().zip(&f.start_chol) {
        assert!((a - b).abs() <= 1e-10 * scale, "chol {a} vs {b}");
    }
    let mut s = Flicker::new(
        &d,
        noise::key(f.seed, &f.name, noise::STREAM_FLICKER),
        noise::key(f.seed, &f.name, noise::STREAM_FLICKER_START),
    );
    let rms = (f.samples.iter().map(|x| x * x).sum::<f64>() / f.samples.len() as f64).sqrt();
    for (i, want) in f.samples.iter().enumerate() {
        let got = s.next(&d);
        assert!(
            (got - want).abs() <= 1e-9 * rms,
            "sample {i}: {got} vs {want}"
        );
    }
}
