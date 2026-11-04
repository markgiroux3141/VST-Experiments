//! An event take recorded through the real player, then replayed offline: RECORDING_PLAN.md
//! T2's and MIDI_TAKES_PLAN.md N1's done-when (a take played live re-renders offline at its
//! quality bit for bit equal to the audio heard, and renders at production).
//!
//!     cargo run --release -p varimu-app --example take_replay -- [--device tube_synth]
//!         [--seconds 7] [--buffer 0.05] [--production] [--out DIR] [--set KEY=VALUE ...]
//!
//! The player plays the device from scripted keys (no keyboard needed) out of the default
//! output: Record as the Session view does it (`Player::begin_event_take`: the device
//! restarted fresh, then the transport and the take). Once the take rolls, a thread plays
//! notes as a keyboard's messages arrive (legato keys, one shorter than a block, a key each
//! side of the range switch's split, velocities, aftertouch), and the knobs turn as the
//! window turns them (built in the background, landing where they land): CUTOFF at 1.5 s,
//! and on tube_synth the LFO switched off at 3 s (a change of structure: a restarted
//! stream). Then the take is replayed from its performance at its quality and compared
//! sample by sample; `--production` renders it at production too (its speed reported);
//! `--out` writes the heard, replayed and production audio as WAVs.
//!
//! `--proxy` monitors through the device's proxy instead (docs/MIDI_TAKES_PLAN.md N2): the
//! take's audio is then the proxy's stand-in, rendered on the device afterwards, and the two
//! are compared (level, and the level's course in 50 ms windows) rather than bit for bit.

use std::path::PathBuf;
use std::sync::Arc;
use std::sync::atomic::AtomicBool;
use std::time::{Duration, Instant};

use varimu_app::live::Circuit;
use varimu_app::midi::{Keys, Wave};
use varimu_app::panel::{DEVICES, RangeMode, knobs, range_mode, values};
use varimu_app::player::{Player, Source, State};
use varimu_app::settings::{Quality, Settings};
use varimu_app::take_render::{Prepared, render};
use varimu_app::transport::TransportSettings;
use varimu_circuit::yaml::Value;

fn value(s: &str) -> Value {
    if let Ok(i) = s.parse::<i64>() {
        Value::Int(i)
    } else if let Ok(x) = s.parse::<f64>() {
        Value::Float(x)
    } else {
        Value::Str(s.to_string())
    }
}

fn set(v: &mut Vec<(String, Value)>, key: &str, to: Value) {
    match v.iter_mut().find(|(k, _)| k == key) {
        Some(e) => e.1 = to,
        None => v.push((key.to_string(), to)),
    }
}

fn main() {
    if let Err(e) = run() {
        eprintln!("error: {e}");
        std::process::exit(1);
    }
}

fn run() -> Result<(), String> {
    let mut device = "tube_synth".to_string();
    let (mut seconds, mut buffer) = (7.0, 0.05);
    let (mut production, mut out, mut sets) = (false, None::<PathBuf>, Vec::new());
    let mut proxy = false;
    let mut args = std::env::args().skip(1);
    while let Some(a) = args.next() {
        let mut next = || args.next().ok_or(format!("{a} needs a value"));
        match a.as_str() {
            "--device" => device = next()?,
            "--seconds" => seconds = next()?.parse().map_err(|e| format!("{e}"))?,
            "--buffer" => buffer = next()?.parse().map_err(|e| format!("{e}"))?,
            "--production" => production = true,
            "--proxy" => proxy = true,
            "--out" => out = Some(PathBuf::from(next()?)),
            "--set" => sets.push(next()?),
            _ => return Err(format!("unknown option {a}")),
        }
    }
    let config = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../config");
    let dev = DEVICES
        .iter()
        .find(|d| d.id == device)
        .ok_or(format!("no device {device}"))?;
    let s = dev.play_settings(&Settings::load(&config, dev.quality)?);
    let circuit = dev
        .live(Circuit::load(&config, dev.circuit, s.cores()?)?)
        .with_events(s.events)
        .with_noise(false);
    let panel = knobs(dev, circuit.spec());
    let mut v = values(&panel);
    for kv in &sets {
        let (k, x) = kv.split_once('=').ok_or(format!("--set {kv}: KEY=VALUE"))?;
        set(&mut v, k, value(x));
    }
    let feeds = varimu_app::panel::key_feeds(dev, circuit.spec())?;
    let wave = if dev.plays_own_oscillator() {
        Wave::Off
    } else {
        Wave::Saw
    };
    let keys = Arc::new(Keys::default());
    varimu_app::player::raise_priority();
    let p = if proxy {
        let tables = varimu_app::proxy::Tables::load(&config, dev.id)?
            .ok_or(format!("{} has no proxy", dev.id))?;
        let start = varimu_app::player::ProxyStart {
            tables: Arc::new(tables),
            device: dev.id.to_string(),
            quality: dev.quality,
            voices: 1,
            noise: false,
        };
        Player::start_proxy(keys.clone(), start, v.clone(), s.clone(), buffer)?
    } else {
        Player::start(
            Source::Keys(keys.clone(), wave, feeds),
            v.clone(),
            circuit,
            s.clone(),
            1.0,
            buffer,
        )?
    };
    p.set_range_mode(range_mode(&panel).unwrap_or(RangeMode::Auto));
    p.set_transport(&TransportSettings {
        bpm: 120.0,
        count_in_bars: 1,
        ..Default::default()
    });
    let wait = |what: &str, cond: &dyn Fn() -> bool, limit_s: f64| -> Result<(), String> {
        let t0 = Instant::now();
        while !cond() {
            if let State::Failed(e) = p.status().state {
                return Err(e);
            }
            if t0.elapsed().as_secs_f64() > limit_s {
                return Err(format!("{what}: still waiting after {limit_s} s"));
            }
            std::thread::sleep(Duration::from_millis(5));
        }
        Ok(())
    };
    wait(
        "the device's start",
        &|| p.status().state == State::Playing,
        120.0,
    )?;
    eprintln!("{} plays; Record (a fresh start)…", dev.label);
    let t_rec = Instant::now();
    p.begin_event_take(dev.id);
    wait("the take's start", &|| p.status().transport.running, 120.0)?;
    eprintln!(
        "the take rolls after {:.2} s of settling (the count-in: 2 s)",
        t_rec.elapsed().as_secs_f64()
    );
    // The keys, as a keyboard's messages arrive (from the count-in's end).
    let k = keys.clone();
    let player_thread = std::thread::spawn(move || {
        let at = |s: f64| std::thread::sleep(Duration::from_secs_f64(s));
        at(2.0);
        let msg = |m: [u8; 3]| k.message(&m);
        msg([0x90, 48, 110]); // C3: below the split (LOW)
        at(0.4);
        msg([0x90, 55, 70]); // legato
        at(0.3);
        msg([0x80, 48, 0]);
        at(0.2);
        msg([0x80, 55, 0]);
        at(0.1);
        msg([0x90, 72, 127]); // C5: above the split (HIGH)
        at(0.003);
        msg([0x80, 72, 0]); // shorter than a block
        at(0.25);
        msg([0x90, 67, 90]);
        for p in 0..20u8 {
            msg([0xd0, p * 6, 0]); // aftertouch rising
            at(0.02);
        }
        msg([0x80, 67, 0]);
        at(0.2);
        msg([0x90, 60, 100]);
        at(0.6);
        msg([0x80, 60, 0]);
        at(0.15);
        msg([0x90, 64, 50]);
        at(0.5);
        msg([0x80, 64, 0]);
    });
    // The knobs, as the window turns them.
    let t_roll = Instant::now();
    let mut turned = (false, false);
    let mut v2 = v.clone();
    while t_roll.elapsed().as_secs_f64() < seconds {
        let el = t_roll.elapsed().as_secs_f64();
        if el > 3.5 && !turned.0 {
            set(&mut v2, "cutoff", Value::Float(0.6));
            p.set(v2.clone());
            turned.0 = true;
        }
        if el > 5.0 && !turned.1 && v2.iter().any(|(k, _)| k == "lfo_on") {
            set(&mut v2, "lfo_on", Value::Int(0));
            p.set(v2.clone());
            turned.1 = true;
        }
        std::thread::sleep(Duration::from_millis(10));
    }
    let _ = player_thread.join();
    p.arm_take(false);
    p.transport_run(false);
    let mut rec = None;
    let t0 = Instant::now();
    while rec.is_none() && t0.elapsed() < Duration::from_secs(5) {
        rec = p.finished_take();
        std::thread::sleep(Duration::from_millis(5));
    }
    let st = p.status();
    let (dropouts, load, restarts) = (p.dropouts(), st.load, st.restarts);
    drop(p);
    let rec = rec.ok_or("no take came back")?;
    let (perf, from) = rec
        .performance
        .clone()
        .ok_or("the take has no performance")?;
    eprintln!(
        "take: {:.2} s from the performance's sample {from}; {} events, {} knob changes \
         ({} restarts); {dropouts} dropouts, load {:.0}%, {restarts} live restarts",
        rec.samples.len() as f64 / perf.rate as f64,
        perf.events.len(),
        perf.knobs.len(),
        perf.knobs.iter().filter(|k| k.restart.is_some()).count(),
        load * 100.0
    );
    let mut perf = (*perf).clone();
    perf.end = from + rec.samples.len() as u64;
    // The performance through its file, then replayed.
    let text = serde_json::to_string(&perf.to_json()).map_err(|e| e.to_string())?;
    let perf = varimu_app::performance::Performance::from_json(
        &serde_json::from_str(&text).map_err(|e| e.to_string())?,
    )?;
    let prep = Prepared::load(&config, &perf, perf.quality)?;
    let t0 = Instant::now();
    let replay = render(&prep, &perf, |_| {}, &AtomicBool::new(false))?;
    let wall = t0.elapsed().as_secs_f64();
    let replay = &replay[from as usize..];
    let n = replay.len().min(rec.samples.len());
    let differ = (0..n)
        .filter(|&i| replay[i].to_bits() != rec.samples[i].to_bits())
        .count();
    let max = (0..n)
        .map(|i| (replay[i] - rec.samples[i]).abs())
        .fold(0.0f32, f32::max);
    let rms =
        (rec.samples.iter().map(|&x| (x as f64).powi(2)).sum::<f64>() / n.max(1) as f64).sqrt();
    println!(
        "replay at {}: {} of {n} samples differ (max {max:.3e}; the take's rms {rms:.4}), {:.2}x real time",
        perf.quality.name(),
        differ,
        wall / (perf.end as f64 / perf.rate as f64)
    );
    if let Some(dir) = &out {
        std::fs::create_dir_all(dir).map_err(|e| e.to_string())?;
        let w = |name: &str, x: &[f32]| {
            let x: Vec<f64> = x.iter().map(|&v| v as f64).collect();
            varimu_app::audio::write_wav(&dir.join(name), &x, perf.rate)
        };
        w("heard.wav", &rec.samples)?;
        w("replay.wav", replay)?;
    }
    if production {
        let prep = Prepared::load(&config, &perf, Quality::Production)?;
        let t0 = Instant::now();
        let y = render(&prep, &perf, |_| {}, &AtomicBool::new(false))?;
        let wall = t0.elapsed().as_secs_f64();
        let y = &y[from as usize..];
        let prms =
            (y.iter().map(|&x| (x as f64).powi(2)).sum::<f64>() / y.len().max(1) as f64).sqrt();
        println!(
            "production: {:.2} s, rms {prms:.4} (draft {rms:.4}), {:.2}x real time (the settle included)",
            y.len() as f64 / perf.rate as f64,
            wall / (perf.end as f64 / perf.rate as f64)
        );
        if let Some(dir) = &out {
            let x: Vec<f64> = y.iter().map(|&v| v as f64).collect();
            varimu_app::audio::write_wav(&dir.join("production.wav"), &x, perf.rate)?;
        }
    }
    if proxy {
        // The stand-in against the device's render of the same take.
        let db = |x: &[f32]| {
            let r =
                (x.iter().map(|&v| (v as f64).powi(2)).sum::<f64>() / x.len().max(1) as f64).sqrt();
            20.0 * (r * 2f64.sqrt()).max(1e-9).log10()
        };
        let w = (0.05 * perf.rate as f64) as usize;
        let course = |x: &[f32]| -> Vec<f64> { x[..n].chunks(w).map(db).collect() };
        let (a, b) = (course(&rec.samples), course(replay));
        let (ma, mb) = (
            a.iter().sum::<f64>() / a.len() as f64,
            b.iter().sum::<f64>() / b.len() as f64,
        );
        let cov: f64 = a.iter().zip(&b).map(|(x, y)| (x - ma) * (y - mb)).sum();
        let r = cov
            / (a.iter().map(|x| (x - ma).powi(2)).sum::<f64>().sqrt()
                * b.iter().map(|y| (y - mb).powi(2)).sum::<f64>().sqrt());
        println!(
            "proxy {:.1} dBFS, the device's render {:.1} dBFS ({:+.1} dB); the level's course              in 50 ms windows correlates r = {r:.3}",
            db(&rec.samples[..n]),
            db(&replay[..n]),
            db(&rec.samples[..n]) - db(&replay[..n])
        );
        return Ok(());
    }
    if differ > 0 {
        return Err("the replay isn't the take heard".into());
    }
    Ok(())
}
