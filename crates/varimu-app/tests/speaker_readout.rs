//! The 5E3's speaker readout on a thread of its own (`Device::live`'s readout apart,
//! COMPONENT_EDITOR_PLAN.md C3's speed) against the one solve it splits: the split IR in one
//! solve is the same circuit bit for bit; partitioned, its back wave runs a sample late,
//! which is all it may cost.

use std::path::{Path, PathBuf};

use varimu_app::live::{Circuit, Live};
use varimu_app::panel::{DEVICES, knobs, values};
use varimu_app::settings::Settings;

fn config() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("../../config")
}

/// A strummed open chord at the host rate: plucked partials decaying, a strum every 0.4 s,
/// peaking near -10 dBFS (a guitar's ~0.3 V into the 5E3's 1 V full scale).
fn strums(rate: f64, seconds: f64) -> Vec<f64> {
    let notes = [82.41, 110.0, 146.83, 196.0, 246.94, 329.63];
    let n = (seconds * rate) as usize;
    (0..n)
        .map(|i| {
            let t = i as f64 / rate;
            let since = t % 0.4;
            notes
                .iter()
                .enumerate()
                .map(|(j, f)| {
                    let t0 = since - 0.012 * j as f64;
                    if t0 < 0.0 {
                        return 0.0;
                    }
                    (1..=12)
                        .map(|k| {
                            let k = k as f64;
                            (2.0 * std::f64::consts::PI * f * k * t0).sin() / k
                                * (-t0 * (3.0 + 2.0 * k)).exp()
                        })
                        .sum::<f64>()
                })
                .sum::<f64>()
                * 0.06
        })
        .collect()
}

fn run(circuit: Circuit, s: Settings, x: &[f64]) -> Vec<f64> {
    run_at(circuit, s, x, None)
}

/// [`run`] with VOLUME (bright) at `volume` (None: the panel's default).
fn run_at(circuit: Circuit, s: Settings, x: &[f64], volume: Option<f64>) -> Vec<f64> {
    let dev = DEVICES.iter().find(|d| d.id == "fender_5e3").unwrap();
    let mut v = values(&knobs(dev, circuit.spec()));
    if let Some(vol) = volume {
        for (k, x) in v.iter_mut() {
            if k == "volume_bright" {
                *x = varimu_circuit::yaml::Value::Float(vol);
            }
        }
    }
    let mut live = Live::new(&[], v, circuit, s).unwrap();
    let mut y = Vec::new();
    for b in x.chunks(480) {
        y.extend(live.process(b).unwrap().0.iter().map(|&v| v as f64));
    }
    y
}

fn rms(x: &[f64]) -> f64 {
    (x.iter().map(|v| v * v).sum::<f64>() / x.len() as f64).sqrt()
}

#[test]
fn the_readout_apart_costs_only_its_lag() {
    let dev = DEVICES.iter().find(|d| d.id == "fender_5e3").unwrap();
    let base = Settings::load(&config(), dev.quality).unwrap();
    let split_s = dev.play_settings(&base);
    let mut split_s = split_s;
    split_s.partition = vec!["SPK readout".to_string()];
    let mut one_s = split_s.clone();
    one_s.partition.clear();
    let cores = split_s.cores().unwrap();
    let load = || Circuit::load(&config(), dev.circuit, cores).unwrap();
    let x = strums(split_s.host() as f64, 1.6);

    // The split IR in one solve: the same circuit, bit for bit.
    let one = run(load(), one_s.clone(), &x);
    let split_one = run(dev.live(load()), one_s, &x);
    assert_eq!(one, split_one);

    let split = run(dev.live(load()), split_s.clone(), &x);
    // Past the first strum's settling.
    let from = (0.4 * split_s.host() as f64) as usize;
    let sig = rms(&one[from..]);
    let report = |label: &str, reference: &[f64]| {
        let d: Vec<f64> = split[from..]
            .iter()
            .zip(&reference[from..])
            .map(|(a, b)| a - b)
            .collect();
        let db = 20.0 * (rms(&d) / sig).log10();
        println!("{label}: {db:.1} dB re signal");
        db
    };
    let db = report("the readout apart vs one solve", &one);
    // Measured 2026-11-11/12 (extrapolated coupling, the draft's): -55.8 dB at draft-2x,
    // -43.7 at draft-1x (the device's quality since 2026-11-12: a sample's lag is 21 us,
    // ~7 mm of the back wave's path, low-passed at ~700 Hz). Before, with the whole readout
    // apart (the front wave's differentiation of a sample-late velocity): -19.4 dB at
    // draft-2x, -33.7 at its best lag; held coupling +4.5 dB.
    assert!(db < -40.0, "{db:.1} dB");
}

/// Cranked (VOLUME 1, the strums 6 dB hotter), the supply on a thread of its own as well:
/// the rails sit behind the reservoir and filter capacitors, so a sample's lag there should
/// cost little against the sag it carries.
#[test]
fn the_supply_apart_cranked() {
    let dev = DEVICES.iter().find(|d| d.id == "fender_5e3").unwrap();
    let s = dev.play_settings(&Settings::load(&config(), dev.quality).unwrap());
    let cores = s.cores().unwrap();
    let load = || Circuit::load(&config(), dev.circuit, cores).unwrap();
    let x: Vec<f64> = strums(s.host() as f64, 1.6)
        .iter()
        .map(|v| 2.0 * v)
        .collect();
    let with = |partition: &[&str]| {
        let mut t = s.clone();
        t.partition = partition.iter().map(|p| p.to_string()).collect();
        run_at(dev.live(load()), t, &x, Some(1.0))
    };
    let one = with(&[]);
    let from = (0.4 * s.host() as f64) as usize;
    let sig = rms(&one[from..]);
    let db = |y: &[f64]| {
        let d: Vec<f64> = y[from..]
            .iter()
            .zip(&one[from..])
            .map(|(a, b)| a - b)
            .collect();
        20.0 * (rms(&d) / sig).log10()
    };
    let readout = db(&with(&["SPK readout"]));
    let supply = db(&with(&["SPK readout", "|", "power supply"]));
    println!("cranked vs one solve: readout apart {readout:.1} dB, and the supply {supply:.1} dB");
    // Measured 2026-11-12 at draft-1x: -39.1 / -38.9 dB.
    assert!(
        readout < -35.0 && supply < readout + 1.0,
        "{readout:.1} {supply:.1}"
    );
    assert_eq!(
        dev.partition,
        Some(&["SPK readout", "|", "power supply"][..])
    );
}
