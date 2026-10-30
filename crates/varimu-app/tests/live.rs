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

#[test]
fn tube_voice_opens_while_its_gate_is_down() {
    // The keyboard's path: a saw through `Live::process_with` with the gate control input
    // (the device's levels from its circuit file) up, down, up again.
    let dev = DEVICES.iter().find(|d| d.id == "tube_voice").unwrap();
    let s = dev.play_settings(&Settings::load(&config(), dev.quality).unwrap());
    let circuit = Circuit::load(&config(), dev.circuit, s.cores().unwrap()).unwrap();
    let (up, down) = varimu_app::panel::gate_levels(circuit.spec(), dev.gate.unwrap()).unwrap();
    let v0 = values(&knobs(dev, circuit.spec()));
    let mut live = Live::with_controls(&[], v0, circuit, s.clone(), 1.0, &[up]).unwrap();
    let rate = live.rate as usize;
    let mut phase = 0.0;
    let mut level = |live: &mut Live, gate_v: f64, seconds: f64| {
        let mut y = Vec::new();
        for _ in 0..(seconds * rate as f64 / 480.0) as usize {
            let x: Vec<f64> = (0..480)
                .map(|_| {
                    phase = (phase + 110.0 / rate as f64) % 1.0;
                    0.5 * (2.0 * phase - 1.0)
                })
                .collect();
            y.extend(live.process_with(&x, &[&vec![gate_v; 480]]).unwrap().0);
        }
        let tail = &y[y.len() / 2..];
        (tail.iter().map(|v| (*v as f64).powi(2)).sum::<f64>() / tail.len() as f64).sqrt()
    };
    let before = level(&mut live, up, 0.3);
    let held = level(&mut live, down, 0.5);
    let after = level(&mut live, up, 1.5);
    println!("before {before:.2e} held {held:.2e} after {after:.2e}");
    assert!(held > 0.05, "{held}");
    // Measured 2026-10-29: 1.9e-4 / 0.126 / 3.4e-4 (-56 dB either side).
    assert!(
        before < held * 1e-2 && after < held * 1e-2,
        "{before} {after}"
    );
}

/// The noise switch (device builder B5): the tube synth builds with its noise sources,
/// and without them when switched off (another structure: the stream restarts); a device
/// without a `noise` block has none to switch.
#[test]
fn the_noise_switch_drops_the_noise_sources() {
    let s = Settings::load(&config(), Quality::Draft2x).unwrap();
    let c = Circuit::load(&config(), "tube_synth", s.cores().unwrap()).unwrap();
    assert!(c.has_noise());
    let v = values(&knobs(
        DEVICES.iter().find(|d| d.id == "tube_synth").unwrap(),
        c.spec(),
    ));
    let on = c.build(&v).unwrap();
    let off = Circuit::load(&config(), "tube_synth", s.cores().unwrap())
        .unwrap()
        .with_noise(false)
        .build(&v)
        .unwrap();
    assert!(on.noise.is_some() && off.noise.is_none());
    assert_ne!(structure(&on), structure(&off));
    let other = Circuit::load(&config(), "fairchild_670", s.cores().unwrap()).unwrap();
    assert!(!other.has_noise());
}

/// The tube synth played from keys (its own oscillator: gate and pitch control inputs):
/// the oscillator follows the key, and still does after a restart (a structure change:
/// the noise switched off). Regression: after a restart every key sounded the same low
/// warble until the stream was started afresh.
#[test]
fn the_synth_follows_its_keys_after_a_restart() {
    use varimu_app::panel::{Feed, key_feeds};
    let dev = DEVICES.iter().find(|d| d.id == "tube_synth").unwrap();
    let s = dev.play_settings(&Settings::load(&config(), dev.quality).unwrap());
    let load = || Circuit::load(&config(), dev.circuit, s.cores().unwrap()).unwrap();
    let c = load();
    let v = values(&knobs(dev, c.spec()));
    let feeds = key_feeds(dev, c.spec()).unwrap();
    let volts = |note: Option<u8>, last: u8| -> Vec<f64> {
        feeds
            .iter()
            .map(|f| match f {
                Feed::Gate(up, down) => {
                    if note.is_some() {
                        *down
                    } else {
                        *up
                    }
                }
                Feed::Pitch(p) => p.volts(440.0 * 2f64.powf((last as f64 - 69.0) / 12.0)),
            })
            .collect()
    };
    let mut live =
        Live::with_controls(&[], v.clone(), c, s.clone(), 1.0, &volts(None, 57)).unwrap();
    let rate = live.rate as f64;
    let block = 480;
    let play = |live: &mut Live, note: Option<u8>, last: u8, secs: f64| -> Vec<f32> {
        let ctl = volts(note, last);
        let lanes: Vec<Vec<f64>> = ctl.iter().map(|&x| vec![x; block]).collect();
        let refs: Vec<&[f64]> = lanes.iter().map(Vec::as_slice).collect();
        let mut y = Vec::new();
        for _ in 0..(secs * rate / block as f64) as usize {
            assert_eq!(live.error(), None);
            y.extend(live.process_with(&vec![0.0; block], &refs).unwrap().0);
        }
        y
    };
    // The frequency of the last second (mean-removed upward zero crossings).
    let freq = |y: &[f32]| -> f64 {
        let y = &y[y.len() - rate as usize..];
        let m = y.iter().map(|&x| x as f64).sum::<f64>() / y.len() as f64;
        let ups = y
            .windows(2)
            .filter(|w| (w[0] as f64) < m && (w[1] as f64) >= m)
            .count();
        ups as f64
    };
    play(&mut live, None, 57, 0.5);
    let a = freq(&play(&mut live, Some(57), 57, 2.0));
    let b = freq(&play(&mut live, Some(69), 69, 2.0));
    println!("before: A3 {a} Hz, A4 {b} Hz");
    live.set_circuit(load().with_noise(false), v.clone());
    let mut waited = 0.0;
    while live.restarts == 0 {
        play(&mut live, None, 69, 0.1);
        waited += 0.1;
        assert!(waited < 60.0, "never restarted");
    }
    play(&mut live, None, 69, 0.5);
    let a2 = freq(&play(&mut live, Some(57), 57, 2.0));
    let b2 = freq(&play(&mut live, Some(69), 69, 2.0));
    println!("after the restart: A3 {a2} Hz, A4 {b2} Hz");
    assert!((b / a - 2.0).abs() < 0.2, "before: {a} / {b}");
    assert!((b2 / a2 - 2.0).abs() < 0.2, "after: {a2} / {b2}");
}

/// A power-on (device builder B6): the tube synth started with its cathodes cold, the warm
/// circuit handed over at once (as the app does: an in-place update, the temperature
/// carried), keys held: silent for its first seconds, then sounding and following the keys.
#[test]
fn the_synth_powers_on_from_cold() {
    use varimu_app::panel::{Feed, key_feeds};
    let dev = DEVICES.iter().find(|d| d.id == "tube_synth").unwrap();
    let s = dev.play_settings(&Settings::load(&config(), dev.quality).unwrap());
    let load = || Circuit::load(&config(), dev.circuit, s.cores().unwrap()).unwrap();
    let c = load().with_heaters(varimu_circuit::Heaters::Cold);
    let v = values(&knobs(dev, c.spec()));
    let feeds = key_feeds(dev, c.spec()).unwrap();
    let volts = |note: u8| -> Vec<f64> {
        feeds
            .iter()
            .map(|f| match f {
                Feed::Gate(_, down) => *down,
                Feed::Pitch(p) => p.volts(440.0 * 2f64.powf((note as f64 - 69.0) / 12.0)),
            })
            .collect()
    };
    let mut live = Live::with_controls(&[], v.clone(), c, s.clone(), 1.0, &volts(57)).unwrap();
    live.set_circuit(load(), v);
    let (rate, block) = (live.rate as f64, 480);
    let second = |live: &mut Live, note: u8| -> (f64, f64) {
        let lanes: Vec<Vec<f64>> = volts(note).iter().map(|&x| vec![x; block]).collect();
        let refs: Vec<&[f64]> = lanes.iter().map(Vec::as_slice).collect();
        let mut y: Vec<f64> = Vec::new();
        for _ in 0..(rate / block as f64) as usize {
            y.extend(
                live.process_with(&vec![0.0; block], &refs)
                    .unwrap()
                    .0
                    .iter()
                    .map(|&x| x as f64),
            );
        }
        let tail = &y[y.len() / 2..];
        let m = tail.iter().sum::<f64>() / tail.len() as f64;
        let ups = tail.windows(2).filter(|w| w[0] < m && w[1] >= m).count();
        let rms = (tail.iter().map(|x| (x - m).powi(2)).sum::<f64>() / tail.len() as f64).sqrt();
        (2.0 * ups as f64, rms)
    };
    let mut seen = Vec::new();
    for t in 0..14 {
        let note = if t % 2 == 0 { 57 } else { 69 };
        seen.push(second(&mut live, note));
    }
    println!("{seen:?}");
    assert!(seen[2].1 < 1e-3, "sounding at 3 s already: {:?}", seen[2]);
    let (a, b) = (seen[12].0, seen[13].0);
    assert!(
        seen[13].1 > 0.05 && (b / a - 2.0).abs() < 0.2,
        "at 13-14 s: {a} / {b}"
    );
}
