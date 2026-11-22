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
/// sidebands) falls by more than 4 dB at 2x. Measured on the heard output, the sound
/// pressure in front of the speaker (component editor C3): -29.8 dB re the harmonics at
/// draft-1x, -34.5 at draft-2x with the designed output transformer OT_5E3@2 (C2 step 6;
/// with version 1's -28.1 and -34.5; on the speaker's terminal voltage, before C3: -7.2
/// and -24.1; the speaker filters most of what folds).
#[test]
fn fender_5e3_oversampled_aliases_less() {
    let dev = DEVICES.iter().find(|d| d.id == "fender_5e3").unwrap();
    // Played at draft-1x since 2026-11-12 (the user's choice, for live play with the
    // speaker's readout); draft-2x stays the option this measures.
    assert_eq!(dev.quality, Quality::Draft1x);
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
    assert!(x2 < x1 - 4.0, "draft-1x {x1:.1} dB, draft-2x {x2:.1} dB");
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
                Feed::Key(k) => k.volts(last),
                Feed::VelocityGate(up, _) if note.is_none() => *up,
                Feed::VelocityGate(_, t) => varimu_app::panel::velocity_volts(t, 127, 0.0),
                Feed::Pressure(_) => 0.0,
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

/// The tube synth's RANGE switch (docs/SYNTH_LOW_END.md): a value change, so the stream
/// updates in place (no restart: AUTO flips it per key) and the held note drops to the
/// LOW capacitor's pitch (224 nF against 56 nF: 477 -> 234 Hz at -15 V, measured at
/// draft by `scripts/vco_study.py`).
#[test]
fn the_synth_range_switch_updates_in_place() {
    use varimu_app::panel::Feed;
    let dev = DEVICES.iter().find(|d| d.id == "tube_synth").unwrap();
    let s = dev.play_settings(&Settings::load(&config(), dev.quality).unwrap());
    let c = Circuit::load(&config(), dev.circuit, s.cores().unwrap()).unwrap();
    let range = dev.pitch.unwrap().range.unwrap();
    let v = values(&knobs(dev, c.spec()));
    assert!(!range.is_low(&v), "AUTO starts at HIGH");
    let feeds = varimu_app::panel::key_feeds(dev, c.spec()).unwrap();
    let held: Vec<f64> = feeds
        .iter()
        .map(|f| match f {
            Feed::Gate(_, down) => *down,
            Feed::Pitch(_) => -15.0,
            Feed::Key(k) => k.volts(70), // -15 V's pitch: ~474 Hz
            Feed::VelocityGate(_, t) => varimu_app::panel::velocity_volts(t, 127, 0.0),
            Feed::Pressure(_) => 0.0,
        })
        .collect();
    let mut live = Live::with_controls(&[], v.clone(), c, s.clone(), 1.0, &held).unwrap();
    let (rate, block) = (live.rate as f64, 480);
    let lanes: Vec<Vec<f64>> = held.iter().map(|&x| vec![x; block]).collect();
    let refs: Vec<&[f64]> = lanes.iter().map(Vec::as_slice).collect();
    let play = |live: &mut Live, secs: f64| -> Vec<f32> {
        let mut y = Vec::new();
        for _ in 0..(secs * rate / block as f64) as usize {
            assert_eq!(live.error(), None);
            y.extend(live.process_with(&vec![0.0; block], &refs).unwrap().0);
        }
        y
    };
    let freq = |y: &[f32]| -> f64 {
        let y = &y[y.len() - rate as usize..];
        let m = y.iter().map(|&x| x as f64).sum::<f64>() / y.len() as f64;
        y.windows(2)
            .filter(|w| (w[0] as f64) < m && (w[1] as f64) >= m)
            .count() as f64
    };
    let high = freq(&play(&mut live, 2.0));
    let low_v = range.with_position(&v, true);
    live.set(low_v.clone());
    let t0 = Instant::now();
    while live.values != low_v {
        assert!(t0.elapsed() < Duration::from_secs(60), "never applied");
        play(&mut live, 0.01);
    }
    let low = freq(&play(&mut live, 2.0));
    println!("-15 V: HIGH {high} Hz, LOW {low} Hz");
    assert_eq!(live.restarts, 0, "the switch restarted the stream");
    assert!(range.is_low(&live.values));
    assert!((low / high - 234.0 / 477.0).abs() < 0.03, "{high} -> {low}");
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
                Feed::Key(k) => k.volts(note),
                Feed::VelocityGate(_, t) => varimu_app::panel::velocity_volts(t, 127, 0.0),
                Feed::Pressure(_) => 0.0,
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

/// The keyboard's touch plays on the harp's own velocity law (docs/RHODES_PLAN.md, "Touch"):
/// the span the Play view reads from the Rhodes' build is its component's (MK1_HARP@2: 21 dB,
/// fitted to jRhodes3d's layers), and none from a circuit without a harp.
#[test]
fn the_harp_s_velocity_span_is_read_from_its_build() {
    let rhodes = DEVICES.iter().find(|d| d.id == "rhodes_stage_5e3").unwrap();
    let c = Circuit::load(&config(), rhodes.circuit, varimu_circuit::Cores::Linear).unwrap();
    let v = values(&knobs(rhodes, c.spec()));
    assert_eq!(c.key_velocity_span_db(&v).unwrap(), Some(21.0));
    let pultec = DEVICES.iter().find(|d| d.id == "pultec_eqp1a").unwrap();
    let eq = Circuit::load(&config(), pultec.circuit, varimu_circuit::Cores::Linear).unwrap();
    let v = values(&knobs(pultec, eq.spec()));
    assert_eq!(eq.key_velocity_span_db(&v).unwrap(), None);
}

/// The Clavinet (docs/CLAVINET_PLAN.md, CL3): its strings are a medium played by keys; its
/// touch spans the tangent's speed law (1-4 m/s: 12 dB); a key struck through `Live`
/// sounds out of its amp, and channel pressure reaches the strings.
#[test]
fn the_clavinet_plays_from_note_events() {
    use circuitsim::media::NoteEvent;
    let dev = DEVICES.iter().find(|d| d.id == "clavinet_d6").unwrap();
    let s = Settings::load(&config(), dev.quality).unwrap();
    let Ok(circuit) = Circuit::load(&config(), dev.circuit, s.cores().unwrap()) else {
        return; // a checkout without the strings' data
    };
    let v = values(&knobs(dev, circuit.spec()));
    let span = circuit.key_velocity_span_db(&v).unwrap().unwrap();
    assert!((span - 20.0 * 4f64.log10()).abs() < 1e-9, "{span}");
    let mut live = Live::new(&vec![0.0; 48_000], v, circuit, s).unwrap();
    assert!(live.has_keys());
    let x = vec![0.0; 480];
    let mut peak = 0.0f32;
    for b in 0..40 {
        let notes: Vec<(usize, NoteEvent)> = match b {
            1 => vec![(
                10,
                NoteEvent::On {
                    note: 60,
                    velocity: 110,
                },
            )],
            10 => vec![(0, NoteEvent::Pressure { value: 100 })],
            30 => vec![(0, NoteEvent::Off { note: 60 })],
            _ => vec![],
        };
        let (y, _) = live.process_notes(&x, &[], &notes).unwrap();
        peak = y.iter().fold(peak, |p, v| p.max(v.abs()));
    }
    assert!(peak > 1e-3, "it sounds: {peak}");
}

/// The Wurlitzer 200A (docs/WURLITZER_PLAN.md, WZ4): its reeds are a medium played by keys;
/// its touch spans the hammer's speed law (WURLI_REEDS@2: 9.2 dB); VOLUME and VIBRATO are
/// values (a turn plays on), OUTPUT builds the power amplifier or not (a restart); a key
/// struck through `Live` sounds at the AUX jack.
#[test]
fn the_wurlitzer_plays_from_note_events() {
    use circuitsim::media::NoteEvent;
    let dev = DEVICES.iter().find(|d| d.id == "wurlitzer_200a").unwrap();
    let s = Settings::load(&config(), dev.quality).unwrap();
    let circuit = Circuit::load(&config(), dev.circuit, s.cores().unwrap()).unwrap();
    let v = values(&knobs(dev, circuit.spec()));
    let keys: Vec<&str> = v.iter().map(|(k, _)| k.as_str()).collect();
    assert_eq!(keys, ["volume", "vibrato", "speakers"]);
    let span = circuit.key_velocity_span_db(&v).unwrap().unwrap();
    assert!((span - 9.2177).abs() < 1e-3, "{span}");
    let base = structure(&circuit.build(&v).unwrap());
    for (k, x) in [
        ("volume", Value::Float(0.4)),
        ("vibrato", Value::Float(1.0)),
    ] {
        let turned = structure(&circuit.build(&set(&v, k, x)).unwrap());
        assert_eq!(base, turned, "{k} plays on");
    }
    let speakers = structure(&circuit.build(&set(&v, "speakers", Value::Int(1))).unwrap());
    assert_ne!(base, speakers, "SPEAKERS builds the power amplifier");
    let mut live = Live::new(&vec![0.0; 48_000], v, circuit, s).unwrap();
    assert!(live.has_keys());
    let x = vec![0.0; 480];
    let mut peak = 0.0f32;
    for b in 0..40 {
        let notes: Vec<(usize, NoteEvent)> = match b {
            1 => vec![(
                10,
                NoteEvent::On {
                    note: 57,
                    velocity: 110,
                },
            )],
            30 => vec![(0, NoteEvent::Off { note: 57 })],
            _ => vec![],
        };
        let (y, _) = live.process_notes(&x, &[], &notes).unwrap();
        peak = y.iter().fold(peak, |p, v| p.max(v.abs()));
    }
    assert!(peak > 1e-3, "it sounds: {peak}");
}

/// The Wurlitzer's VIBRATO through `Live` (docs/WURLITZER_PLAN.md WZ2's ~6 dB p-p at 5.7 Hz):
/// a held A4's level over 20 ms windows, its linear decay in dB removed, peak to peak, at
/// VIBRATO 0, at 1 from the start and turned to 1 while it plays.
#[test]
fn the_wurlitzer_vibrato_modulates_live() {
    use circuitsim::media::NoteEvent;
    use std::time::Duration;
    let dev = DEVICES.iter().find(|d| d.id == "wurlitzer_200a").unwrap();
    let s = Settings::load(&config(), dev.quality).unwrap();
    let fs = s.host() as f64;
    let run = |start: f64, turn_to: Option<f64>| -> f64 {
        let circuit = Circuit::load(&config(), dev.circuit, s.cores().unwrap()).unwrap();
        let v = values(&knobs(dev, circuit.spec()));
        let v0 = set(&v, "vibrato", Value::Float(start));
        let mut live = Live::new(&vec![0.0; 48_000], v0, circuit, s.clone()).unwrap();
        let x = vec![0.0; 480];
        let mut y_all = Vec::new();
        let blocks = (4.0 * fs / 480.0) as usize;
        for b in 0..blocks {
            if b == 10
                && let Some(to) = turn_to
            {
                live.set(set(&v, "vibrato", Value::Float(to)));
                std::thread::sleep(Duration::from_millis(500)); // the build in the background
            }
            let notes: Vec<(usize, NoteEvent)> = if b == 2 {
                vec![(
                    0,
                    NoteEvent::On {
                        note: 69,
                        velocity: 110,
                    },
                )]
            } else {
                vec![]
            };
            let (y, _) = live.process_notes(&x, &[], &notes).unwrap();
            y_all.extend(y.iter().map(|&s| s as f64));
        }
        // windows of 20 ms over 1.5-3.9 s
        let w = (0.02 * fs) as usize;
        let (a, b) = ((1.5 * fs) as usize, (3.9 * fs) as usize);
        let db: Vec<f64> = y_all[a..b]
            .chunks_exact(w)
            .map(|c| 10.0 * (c.iter().map(|v| v * v).sum::<f64>() / w as f64).log10())
            .collect();
        let n = db.len() as f64;
        let tm = (n - 1.0) / 2.0;
        let mean = db.iter().sum::<f64>() / n;
        let slope = db
            .iter()
            .enumerate()
            .map(|(i, d)| (i as f64 - tm) * (d - mean))
            .sum::<f64>()
            / db.iter()
                .enumerate()
                .map(|(i, _)| (i as f64 - tm).powi(2))
                .sum::<f64>();
        let r: Vec<f64> = db
            .iter()
            .enumerate()
            .map(|(i, d)| d - mean - slope * (i as f64 - tm))
            .collect();
        r.iter().cloned().fold(f64::MIN, f64::max) - r.iter().cloned().fold(f64::MAX, f64::min)
    };
    let off = run(0.0, None);
    let half = run(0.5, None);
    let full = run(1.0, None);
    let turned = run(0.0, Some(1.0));
    println!(
        "vibrato p-p: off {off:.2} dB, half {half:.2} dB, full {full:.2} dB, \
         turned up live {turned:.2} dB"
    );
    assert!(off < 1.5, "off: {off}");
    // LG1_200A@1: the knob deepens across its travel (2 dB at half on a steady tone)
    assert!(half > off + 0.8 && half < full - 1.5, "half: {half}");
    assert!(full > 4.0, "full: {full}");
    assert!(turned > 4.0, "turned up: {turned}");
}

/// The Rosin Wheel Organ (docs/INVENTED_LIVE_PLAN.md IL1): its bars are the invented-keys
/// medium played by keys; WHEEL, RESONATOR and TOUCH are values (a turn plays on); a key
/// pressed through `Live` sounds, and aftertouch reaches it.
#[test]
fn the_rosin_wheel_plays_from_note_events() {
    use circuitsim::media::NoteEvent;
    let dev = DEVICES.iter().find(|d| d.id == "rosin_wheel").unwrap();
    let s = Settings::load(&config(), dev.quality).unwrap();
    let circuit = Circuit::load(&config(), dev.circuit, s.cores().unwrap()).unwrap();
    let v = values(&knobs(dev, circuit.spec()));
    let keys: Vec<&str> = v.iter().map(|(k, _)| k.as_str()).collect();
    assert_eq!(keys, ["wheel", "resonator", "touch"]);
    let base = structure(&circuit.build(&v).unwrap());
    for (k, x) in [("wheel", 0.9), ("resonator", 0.1), ("touch", 0.8)] {
        let turned = structure(&circuit.build(&set(&v, k, Value::Float(x))).unwrap());
        assert_eq!(base, turned, "{k} plays on");
    }
    let mut live = Live::new(&vec![0.0; 48_000], v, circuit, s).unwrap();
    assert!(live.has_keys());
    let x = vec![0.0; 480];
    let mut peak = 0.0f32;
    for b in 0..40 {
        let notes: Vec<(usize, NoteEvent)> = match b {
            1 => vec![(
                10,
                NoteEvent::On {
                    note: 57,
                    velocity: 100,
                },
            )],
            10 => vec![(0, NoteEvent::Pressure { value: 90 })],
            30 => vec![(0, NoteEvent::Off { note: 57 })],
            _ => vec![],
        };
        let (y, _) = live.process_notes(&x, &[], &notes).unwrap();
        peak = y.iter().fold(peak, |p, v| p.max(v.abs()));
    }
    assert!(peak > 1e-3, "it sounds: {peak}");
}

/// The Buzz Zither (docs/INVENTED_LIVE_PLAN.md IL2): its strings are the invented-keys medium
/// played by keys; its touch spans the pluck's force (0.1-1 N); the four knobs are values
/// (a turn plays on); a key plucked through `Live` sounds, and the pedal's tanpura too.
#[test]
fn the_buzz_zither_plays_from_note_events() {
    use circuitsim::media::NoteEvent;
    let dev = DEVICES.iter().find(|d| d.id == "buzz_zither").unwrap();
    let s = Settings::load(&config(), dev.quality).unwrap();
    let circuit = Circuit::load(&config(), dev.circuit, s.cores().unwrap()).unwrap();
    let v = values(&knobs(dev, circuit.spec()));
    let keys: Vec<&str> = v.iter().map(|(k, _)| k.as_str()).collect();
    assert_eq!(keys, ["jawari", "pluck", "drone", "drone_tonic"]);
    let span = circuit.key_velocity_span_db(&v).unwrap().unwrap();
    let lo: f64 = 0.1 + 0.9 / 127.0;
    assert!((span - 20.0 * (1.0f64 / lo).log10()).abs() < 1e-9, "{span}");
    let base = structure(&circuit.build(&v).unwrap());
    for (k, x) in [
        ("jawari", 0.9),
        ("pluck", 0.1),
        ("drone", 0.2),
        ("drone_tonic", 0.5),
    ] {
        let turned = structure(&circuit.build(&set(&v, k, Value::Float(x))).unwrap());
        assert_eq!(base, turned, "{k} plays on");
    }
    for (pedal, first) in [(false, 1), (true, 0)] {
        let mut live =
            Live::new(&vec![0.0; 48_000], v.clone(), circuit.clone(), s.clone()).unwrap();
        assert!(live.has_keys());
        let x = vec![0.0; 480];
        let mut peak = 0.0f32;
        for b in 0..30 {
            let notes: Vec<(usize, NoteEvent)> = match (pedal, b) {
                (false, 1) => vec![(
                    10,
                    NoteEvent::On {
                        note: 60,
                        velocity: 100,
                    },
                )],
                (false, 20) => vec![(0, NoteEvent::Off { note: 60 })],
                (true, 1) => vec![(10, NoteEvent::Pedal { down: true })],
                _ => vec![],
            };
            let (y, _) = live.process_notes(&x, &[], &notes).unwrap();
            if b > first {
                peak = y.iter().fold(peak, |p, v| p.max(v.abs()));
            }
        }
        assert!(peak > 1e-3, "it sounds (pedal {pedal}): {peak}");
    }
}

/// The Rijke Organ (docs/INVENTED_LIVE_PLAN.md IL3): its pipes are the invented-keys medium
/// played by keys; its touch spans the heater's power (0.6-1.2); HEAT, GAUZE and BREATH are
/// values (a turn plays on); a key held through `Live` blooms into sound.
#[test]
fn the_rijke_organ_plays_from_note_events() {
    use circuitsim::media::NoteEvent;
    let dev = DEVICES.iter().find(|d| d.id == "rijke_organ").unwrap();
    let s = Settings::load(&config(), dev.quality).unwrap();
    let circuit = Circuit::load(&config(), dev.circuit, s.cores().unwrap()).unwrap();
    let v = values(&knobs(dev, circuit.spec()));
    let keys: Vec<&str> = v.iter().map(|(k, _)| k.as_str()).collect();
    assert_eq!(keys, ["heat", "gauze", "breath"]);
    let span = circuit.key_velocity_span_db(&v).unwrap().unwrap();
    let lo: f64 = 0.6 + 0.6 / 127.0;
    assert!((span - 20.0 * (1.2f64 / lo).log10()).abs() < 1e-9, "{span}");
    let base = structure(&circuit.build(&v).unwrap());
    for (k, x) in [("heat", 0.9), ("gauze", 0.1), ("breath", 0.8)] {
        let turned = structure(&circuit.build(&set(&v, k, Value::Float(x))).unwrap());
        assert_eq!(base, turned, "{k} plays on");
    }
    let mut live = Live::new(&vec![0.0; 48_000], v, circuit, s).unwrap();
    assert!(live.has_keys());
    let x = vec![0.0; 480];
    let mut peak = 0.0f32;
    // 1.5 s held (the bloom: a pipe starts ~0.4-1.3 s after its key)
    for b in 0..150 {
        let notes: Vec<(usize, NoteEvent)> = match b {
            1 => vec![(
                10,
                NoteEvent::On {
                    note: 72,
                    velocity: 120,
                },
            )],
            _ => vec![],
        };
        let (y, _) = live.process_notes(&x, &[], &notes).unwrap();
        peak = y.iter().fold(peak, |p, v| p.max(v.abs()));
    }
    assert!(peak > 1e-2, "it sounds: {peak}");
}

/// The Aeolian Keyboard (docs/INVENTED_LIVE_PLAN.md IL4): its strings are the invented-keys
/// medium played by keys; its touch spans the slot's opening (0.3-1); WIND and GUST are
/// values (a turn plays on); a key held through `Live` sings.
#[test]
fn the_aeolian_keyboard_plays_from_note_events() {
    use circuitsim::media::NoteEvent;
    let dev = DEVICES.iter().find(|d| d.id == "aeolian_keyboard").unwrap();
    let s = Settings::load(&config(), dev.quality).unwrap();
    let circuit = Circuit::load(&config(), dev.circuit, s.cores().unwrap()).unwrap();
    let v = values(&knobs(dev, circuit.spec()));
    let keys: Vec<&str> = v.iter().map(|(k, _)| k.as_str()).collect();
    assert_eq!(keys, ["wind", "gust"]);
    let span = circuit.key_velocity_span_db(&v).unwrap().unwrap();
    let lo: f64 = 0.3 + 0.7 / 127.0;
    assert!((span - 20.0 * (1.0f64 / lo).log10()).abs() < 1e-9, "{span}");
    let base = structure(&circuit.build(&v).unwrap());
    for (k, x) in [("wind", 0.9), ("gust", 0.1)] {
        let turned = structure(&circuit.build(&set(&v, k, Value::Float(x))).unwrap());
        assert_eq!(base, turned, "{k} plays on");
    }
    let mut live = Live::new(&vec![0.0; 48_000], v, circuit, s).unwrap();
    assert!(live.has_keys());
    let x = vec![0.0; 480];
    let mut peak = 0.0f32;
    for b in 0..60 {
        let notes: Vec<(usize, NoteEvent)> = match b {
            1 => vec![(
                10,
                NoteEvent::On {
                    note: 57,
                    velocity: 100,
                },
            )],
            _ => vec![],
        };
        let (y, _) = live.process_notes(&x, &[], &notes).unwrap();
        peak = y.iter().fold(peak, |p, v| p.max(v.abs()));
    }
    assert!(peak > 1e-3, "it sounds: {peak}");
}

/// The Bubble Organ (docs/INVENTED_LIVE_PLAN.md IL5): its nozzles are the invented-keys
/// medium played by keys; its touch spans a struck bubble's pinch-off (0.5-1.5); MODE, FLOW,
/// RATE and DEPTH are values (a turn plays on); a key struck through `Live` sounds, and held
/// in HELD mode it streams.
#[test]
fn the_bubble_organ_plays_from_note_events() {
    use circuitsim::media::NoteEvent;
    let dev = DEVICES.iter().find(|d| d.id == "bubble_organ").unwrap();
    let s = Settings::load(&config(), dev.quality).unwrap();
    let circuit = Circuit::load(&config(), dev.circuit, s.cores().unwrap()).unwrap();
    let v = values(&knobs(dev, circuit.spec()));
    let keys: Vec<&str> = v.iter().map(|(k, _)| k.as_str()).collect();
    assert_eq!(keys, ["held", "flow", "rate", "depth"]);
    let span = circuit.key_velocity_span_db(&v).unwrap().unwrap();
    let lo: f64 = 0.5 + 1.0 / 127.0;
    assert!((span - 20.0 * (1.5f64 / lo).log10()).abs() < 1e-9, "{span}");
    let base = structure(&circuit.build(&v).unwrap());
    for (k, x) in [("flow", 0.9), ("rate", 0.1), ("depth", 0.8)] {
        let turned = structure(&circuit.build(&set(&v, k, Value::Float(x))).unwrap());
        assert_eq!(base, turned, "{k} plays on");
    }
    let held = set(&v, "held", Value::Float(1.0));
    assert_eq!(
        base,
        structure(&circuit.build(&held).unwrap()),
        "MODE plays on"
    );
    for values in [v.clone(), held] {
        let mut live = Live::new(&vec![0.0; 48_000], values, circuit.clone(), s.clone()).unwrap();
        assert!(live.has_keys());
        let x = vec![0.0; 480];
        let mut peak = 0.0f32;
        for b in 0..40 {
            let notes: Vec<(usize, NoteEvent)> = match b {
                1 => vec![(
                    10,
                    NoteEvent::On {
                        note: 64,
                        velocity: 100,
                    },
                )],
                _ => vec![],
            };
            let (y, _) = live.process_notes(&x, &[], &notes).unwrap();
            peak = y.iter().fold(peak, |p, v| p.max(v.abs()));
        }
        assert!(peak > 1e-3, "it sounds: {peak}");
    }
}

/// The Siren Organ (docs/INVENTED_LIVE_PLAN.md IL6): its rings are the invented-keys medium
/// played by keys, their shaft shared; its touch spans the valve's opening (0.2-1); SPEED,
/// STOP, WIND and MOTOR are values (a turn plays on); a key struck through `Live` sounds on
/// either stop.
#[test]
fn the_siren_organ_plays_from_note_events() {
    use circuitsim::media::NoteEvent;
    let dev = DEVICES.iter().find(|d| d.id == "siren_organ").unwrap();
    let s = Settings::load(&config(), dev.quality).unwrap();
    let circuit = Circuit::load(&config(), dev.circuit, s.cores().unwrap()).unwrap();
    let v = values(&knobs(dev, circuit.spec()));
    let keys: Vec<&str> = v.iter().map(|(k, _)| k.as_str()).collect();
    assert_eq!(keys, ["speed", "stop", "wind", "motor"]);
    let span = circuit.key_velocity_span_db(&v).unwrap().unwrap();
    let lo: f64 = 0.2 + 0.8 / 127.0;
    assert!((span - 20.0 * (1.0 / lo).log10()).abs() < 1e-9, "{span}");
    let base = structure(&circuit.build(&v).unwrap());
    for (k, x) in [("speed", 0.9), ("wind", 0.1), ("motor", 0.8)] {
        let turned = structure(&circuit.build(&set(&v, k, Value::Float(x))).unwrap());
        assert_eq!(base, turned, "{k} plays on");
    }
    let reed = set(&v, "stop", Value::Float(1.0));
    assert_eq!(
        base,
        structure(&circuit.build(&reed).unwrap()),
        "STOP plays on"
    );
    for values in [v.clone(), reed] {
        let mut live = Live::new(&vec![0.0; 48_000], values, circuit.clone(), s.clone()).unwrap();
        assert!(live.has_keys());
        let x = vec![0.0; 480];
        let mut peak = 0.0f32;
        for b in 0..40 {
            let notes: Vec<(usize, NoteEvent)> = match b {
                1 => vec![(
                    10,
                    NoteEvent::On {
                        note: 57,
                        velocity: 100,
                    },
                )],
                _ => vec![],
            };
            let (y, _) = live.process_notes(&x, &[], &notes).unwrap();
            peak = y.iter().fold(peak, |p, v| p.max(v.abs()));
        }
        assert!(peak > 1e-3, "it sounds: {peak}");
    }
}

/// The Nickel Organ (docs/NICKEL_ORGAN_DEVICE_PLAN.md): its keys are a medium played by keys;
/// its touch spans the hammer's speed law (0.02-0.25 m/s: 21.9 dB); SUSTAIN and POLARIZE
/// are values (a turn plays on); a key struck through `Live` sounds.
#[test]
fn the_nickel_organ_plays_from_note_events() {
    use circuitsim::media::NoteEvent;
    let dev = DEVICES.iter().find(|d| d.id == "nickel_organ").unwrap();
    let s = Settings::load(&config(), dev.quality).unwrap();
    let circuit = Circuit::load(&config(), dev.circuit, s.cores().unwrap()).unwrap();
    let v = values(&knobs(dev, circuit.spec()));
    let keys: Vec<&str> = v.iter().map(|(k, _)| k.as_str()).collect();
    assert_eq!(keys, ["sustain", "polarize"]);
    let span = circuit.key_velocity_span_db(&v).unwrap().unwrap();
    assert!((span - 20.0 * 12.5f64.log10()).abs() < 1e-9, "{span}");
    let base = structure(&circuit.build(&v).unwrap());
    for (k, x) in [("sustain", 0.9), ("polarize", 0.1)] {
        let turned = structure(&circuit.build(&set(&v, k, Value::Float(x))).unwrap());
        assert_eq!(base, turned, "{k} plays on");
    }
    let mut live = Live::new(&vec![0.0; 48_000], v, circuit, s).unwrap();
    assert!(live.has_keys());
    let x = vec![0.0; 480];
    let mut peak = 0.0f32;
    for b in 0..40 {
        let notes: Vec<(usize, NoteEvent)> = match b {
            1 => vec![(
                10,
                NoteEvent::On {
                    note: 69,
                    velocity: 110,
                },
            )],
            30 => vec![(0, NoteEvent::Off { note: 69 })],
            _ => vec![],
        };
        let (y, _) = live.process_notes(&x, &[], &notes).unwrap();
        peak = y.iter().fold(peak, |p, v| p.max(v.abs()));
    }
    assert!(peak > 1e-3, "it sounds: {peak}");
}
