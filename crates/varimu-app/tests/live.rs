//! The real-time engine without an audio device: the EQP-1A (the cheaper device, ~6x
//! faster than real time at draft-1x) looping a tone while knobs turn; the 5E3 at its
//! oversampled quality (draft-2x).

use std::path::{Path, PathBuf};
use std::time::{Duration, Instant};

use varimu_app::live::{Circuit, Live, Values, make_loop, structure};
use varimu_app::panel::{DEVICES, knobs, values};
use varimu_app::settings::{Quality, Settings};
use varimu_circuit::yaml::Value;

fn config() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("../../config")
}

fn tone(s: &Settings, seconds: f64, f_hz: f64, amp: f64) -> Vec<f64> {
    let n = (seconds * s.sample_rate as f64) as usize;
    (0..n)
        .map(|i| amp * (2.0 * std::f64::consts::PI * f_hz * i as f64 / s.sample_rate as f64).sin())
        .collect()
}

fn set(v: &Values, key: &str, to: Value) -> Values {
    v.iter()
        .map(|(k, x)| (k.clone(), if k == key { to.clone() } else { x.clone() }))
        .collect()
}

/// Play blocks until the session plays `want` (or time runs out); returns the blocks.
fn play_until(live: &mut Live, want: &Values) -> Vec<f32> {
    let t0 = Instant::now();
    let mut y = Vec::new();
    while live.values != *want {
        assert!(
            t0.elapsed() < Duration::from_secs(60),
            "values never applied"
        );
        assert_eq!(live.error(), None);
        y.extend(live.next_block(480).unwrap().0);
    }
    for _ in 0..20 {
        y.extend(live.next_block(480).unwrap().0);
    }
    y
}

#[test]
fn eqp1a_plays_and_turns() {
    let s = Settings::load(&config(), Quality::Draft1x).unwrap();
    let dev = &DEVICES[1];
    let circuit = Circuit::load(&config(), dev.circuit, s.cores().unwrap()).unwrap();
    let k = knobs(dev, circuit.spec());
    let v0 = values(&k);
    let mut live = Live::new(&tone(&s, 0.5, 1000.0, 0.1), v0.clone(), circuit, s.clone()).unwrap();
    assert_eq!(live.rate, 48_000);
    assert_eq!(live.loop_len(), 24_000 - 480); // the seam's 10 ms folded in

    let mut y = Vec::new();
    let mut gain = 0.0;
    for _ in 0..60 {
        let (b, m) = live.next_block(480).unwrap();
        assert_eq!(b.len(), 480);
        y.extend(b);
        gain = m.gain_db;
    }
    assert!(y.iter().all(|v| v.is_finite()));
    // Python's Live on the same tone: -5.0264 dB (its samples are equal to these bit for
    // bit; checked 2026-10-27).
    assert!(
        (gain + 5.0264).abs() < 1e-3,
        "gain at the defaults {gain} dB"
    );

    // A knob: the same structure, updated in place.
    let v1 = set(&v0, "hf_boost", Value::Float(1.0));
    live.set(v1.clone());
    play_until(&mut live, &v1);
    assert_eq!(live.restarts, 0);

    // Every selector position plays (in place or by a restarted stream).
    let lf = k.iter().find(|k| k.key == "lf_freq_hz").unwrap();
    let varimu_app::panel::Kind::Choices(choices) = &lf.kind else {
        panic!("lf_freq_hz is a selector")
    };
    let mut v = v1;
    for c in choices {
        v = set(&v, "lf_freq_hz", c.clone());
        live.set(v.clone());
        let y = play_until(&mut live, &v);
        assert!(y.iter().all(|t| t.is_finite() && t.abs() < 2.0));
    }
}

#[test]
fn loop_seam_is_crossfaded() {
    let x: Vec<f64> = (0..10_000).map(|i| i as f64).collect();
    let y = make_loop(&x, 48_000);
    assert_eq!(y.len(), 10_000 - 480);
    assert_eq!(y[0], x[10_000 - 480]); // starts where the end left off
    assert_eq!(y[479], x[479]); // numpy's linspace ends exactly at 1
    assert_eq!(y[1000], 1000.0);
}

#[test]
fn structure_tells_values_from_rewiring() {
    let s = Settings::load(&config(), Quality::Draft1x).unwrap();
    let c = Circuit::load(&config(), "fairchild_670", s.cores().unwrap()).unwrap();
    let v = values(&knobs(&DEVICES[0], c.spec()));
    let base = structure(&c.build(&v).unwrap());
    let thr = structure(
        &c.build(&set(&v, "ac_threshold", Value::Float(0.3)))
            .unwrap(),
    );
    assert_eq!(base, thr);
    // Time Constant 5 adds parts (live.py: a change of structure).
    let tc5 = structure(&c.build(&set(&v, "time_constant", Value::Int(5))).unwrap());
    assert_ne!(base, tc5);
}

/// A restart and then an update for the restarted circuit, both ready before the next
/// block: the update belongs to the new stream (it failed on the old one, whose
/// structure it doesn't have: "update: the circuit's nodes, sources or inductors
/// changed", found moving the 670's pad across its 0 dB end, 2026-10-28).
#[test]
fn update_after_restart_goes_to_the_new_stream() {
    let s = Settings::load(&config(), Quality::Draft1x).unwrap();
    let dev = &DEVICES[1];
    let circuit = Circuit::load(&config(), dev.circuit, s.cores().unwrap()).unwrap();
    let v0 = values(&knobs(dev, circuit.spec()));
    let mut live = Live::new(&tone(&s, 0.5, 1000.0, 0.1), v0.clone(), circuit, s).unwrap();
    for _ in 0..5 {
        live.next_block(480).unwrap();
    }
    // A selector that rewires: a restart (built and settled in the background).
    let v1 = set(&v0, "hf_boost_freq_khz", Value::Int(5));
    live.set(v1.clone());
    std::thread::sleep(Duration::from_secs(3));
    // A value on the new structure: an update, also ready before the next block.
    let v2 = set(&v1, "hf_boost", Value::Float(0.5));
    live.set(v2.clone());
    std::thread::sleep(Duration::from_secs(1));
    let y = play_until(&mut live, &v2);
    assert!(y.iter().all(|t| t.is_finite()));
    assert_eq!(live.restarts, 1);
}

/// The input gain is the source's level: a clip at gain 2 plays exactly as the clip
/// doubled (powers of two scale exactly, through the resampler too).
#[test]
fn gain_equals_a_louder_clip() {
    let s = Settings::load(&config(), Quality::Draft1x).unwrap();
    let dev = &DEVICES[1];
    let run = |clip: &[f64], gain: f64| -> Vec<f32> {
        let circuit = Circuit::load(&config(), dev.circuit, s.cores().unwrap()).unwrap();
        let v = values(&knobs(dev, circuit.spec()));
        let mut live = Live::with_gain(clip, v, circuit, s.clone(), gain).unwrap();
        (0..20)
            .flat_map(|_| live.next_block(480).unwrap().0)
            .collect()
    };
    let x = tone(&s, 0.5, 1000.0, 0.05);
    let x2: Vec<f64> = x.iter().map(|v| 2.0 * v).collect();
    assert_eq!(run(&x, 2.0), run(&x2, 1.0));
}

/// The 5E3 hard clipped (2902 Hz at 0.5 V, full volume) through Live at draft-1x and at
/// draft-2x (its Play quality: the input upsampled into a 96 kHz stream, the output
/// decimated back): what isn't a harmonic of the tone (aliases, the supply's hum and its
/// sidebands) falls by more than 5 dB at 2x. Measured on the heard output, the sound
/// pressure in front of the speaker (component editor C3): -28.1 dB re the harmonics at
/// draft-1x, -34.5 at draft-2x (on the speaker's terminal voltage, before C3: -7.2 and
/// -24.1; the speaker filters most of what folds).
#[test]
fn fender_5e3_oversampled_aliases_less() {
    let dev = DEVICES.iter().find(|d| d.id == "fender_5e3").unwrap();
    assert_eq!(dev.quality, Quality::Draft2x);
    let other_db = |q: Quality| -> f64 {
        let s = Settings::load(&config(), q).unwrap();
        assert_eq!((s.host(), s.sim_rate()), (48_000, 48_000 * s.oversample));
        let circuit = Circuit::load(&config(), dev.circuit, s.cores().unwrap()).unwrap();
        let v = set(
            &values(&knobs(dev, circuit.spec())),
            "volume_bright",
            Value::Float(1.0),
        );
        let f = 2902.0;
        let mut live = Live::new(&tone(&s, 1.0, f, 0.5), v, circuit, s.clone()).unwrap();
        // 0.3 s in, then 0.5 s: 24000 samples, exactly 1451 periods of the tone.
        let y: Vec<f64> = (0..80)
            .flat_map(|_| live.next_block(480).unwrap().0)
            .skip(14_400)
            .take(24_000)
            .map(f64::from)
            .collect();
        let n = y.len() as f64;
        let mean = y.iter().sum::<f64>() / n;
        let total = y.iter().map(|v| (v - mean).powi(2)).sum::<f64>() / n;
        let harmonic: f64 = (1..=8) // 8 x 2902 = 23.2 kHz, below 24 kHz
            .map(|k| {
                let w = 2.0 * std::f64::consts::PI * f * k as f64 / 48_000.0;
                let (c, s) = y.iter().enumerate().fold((0.0, 0.0), |(c, s), (i, v)| {
                    (c + v * (w * i as f64).cos(), s + v * (w * i as f64).sin())
                });
                2.0 * (c * c + s * s) / (n * n)
            })
            .sum();
        10.0 * ((total - harmonic) / harmonic).log10()
    };
    let (x1, x2) = (other_db(Quality::Draft1x), other_db(Quality::Draft2x));
    assert!(x2 < x1 - 5.0, "draft-1x {x1:.1} dB, draft-2x {x2:.1} dB");
}
