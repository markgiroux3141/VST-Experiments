//! An insert auditioned as the Session view plays it (docs/SESSION_FX_PLAN.md, F3): a
//! file placed on the timeline at bar 1, a device fed from it where the transport is, a
//! knob turned while it plays. Reports the load, dropouts and knob to ear.
//!
//!     cargo run --release -p varimu-app --example audition -- --file FILE
//!         [--device fairchild_670] [--for 12] [--turn KEY=A,B] [--mix-only]
//!
//! `--turn` sets KEY to A at the start and B halfway. `--mix-only` plays the file as a
//! session track with no device (`Player::start_mix`) instead.

use std::path::PathBuf;
use std::sync::Arc;
use std::time::{Duration, Instant};

use varimu_app::audio;
use varimu_app::live::Circuit;
use varimu_app::player::{Player, Source, State};
use varimu_app::print::find_device;
use varimu_app::resample::resample;
use varimu_app::session::{Mix, MixClip};
use varimu_app::settings::{Quality, Settings};
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

fn main() -> Result<(), String> {
    let mut args = std::env::args().skip(1);
    let (mut file, mut device, mut secs, mut turn, mut mix_only) =
        (None, "fairchild_670".to_string(), 12.0, None, false);
    while let Some(a) = args.next() {
        let mut next = || args.next().ok_or(format!("{a} needs a value"));
        match a.as_str() {
            "--file" => file = Some(PathBuf::from(next()?)),
            "--device" => device = next()?,
            "--for" => secs = next()?.parse().map_err(|e| format!("--for: {e}"))?,
            "--turn" => {
                let v = next()?;
                let (k, ab) = v.split_once('=').ok_or("--turn KEY=A,B")?;
                let (x, y) = ab.split_once(',').ok_or("--turn KEY=A,B")?;
                turn = Some((k.to_string(), value(x), value(y)));
            }
            "--mix-only" => mix_only = true,
            _ => return Err(format!("unknown argument {a}")),
        }
    }
    let config = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../config");
    let d = find_device(&device).ok_or(format!("no device {device}"))?;
    let s = d.play_settings(&Settings::load(&config, d.quality)?);
    let rate = s.host();
    let w = audio::decode(&file.ok_or("--file is required")?)?;
    let x: Arc<Vec<f32>> = Arc::new(
        resample(&w.mono(), w.rate, rate)
            .iter()
            .map(|&v| v as f32)
            .collect(),
    );
    let mut transport = TransportSettings::default();
    transport.count_in_bars = 0;
    transport.pre_roll_bars = 0;
    let values = |v: &Value| {
        turn.as_ref()
            .map_or(Vec::new(), |(k, _, _)| vec![(k.clone(), v.clone())])
    };
    let p = if mix_only {
        let p = Player::start_mix(None, Settings::load(&config, Quality::Draft1x)?, 0.05)?;
        p.set_mix(Arc::new(Mix {
            clips: vec![MixClip {
                start: 0,
                audio: x.clone(),
                gain: (1.0, 1.0),
            }],
            live: (0.0, 0.0),
        }));
        p
    } else {
        let circuit = Circuit::load(&config, d.circuit, s.cores()?)?;
        let v0 = turn.as_ref().map_or(Vec::new(), |(_, a, _)| values(a));
        let p = Player::start(
            Source::Timeline {
                audio: x.clone(),
                start: 0,
            },
            v0,
            circuit,
            s,
            1.0,
            d.ahead_s,
        )?;
        p.set_compensation(false);
        p
    };
    p.set_transport(&transport);
    let t0 = Instant::now();
    while p.status().state == State::Starting {
        if t0.elapsed() > Duration::from_secs(30) {
            return Err("didn't start in 30 s".into());
        }
        std::thread::sleep(Duration::from_millis(20));
    }
    if let State::Failed(e) = p.status().state {
        return Err(e);
    }
    println!(
        "started in {:.2} s at {rate} Hz ({})",
        t0.elapsed().as_secs_f64(),
        if mix_only { "mix only" } else { &device }
    );
    p.transport_run(true);
    let t1 = Instant::now();
    let (mut turned, mut loads, mut worst) = (false, Vec::new(), 0f64);
    while t1.elapsed().as_secs_f64() < secs {
        std::thread::sleep(Duration::from_millis(250));
        let st = p.status();
        loads.push(st.load);
        worst = worst.max(st.load_max);
        if !turned
            && t1.elapsed().as_secs_f64() > secs / 2.0
            && let Some((_, _, b)) = &turn
        {
            p.set(values(b));
            turned = true;
        }
    }
    let st = p.status();
    let mean = loads.iter().sum::<f64>() / loads.len().max(1) as f64;
    println!(
        "played {:.1} s: load {:.0}% mean, {:.0}% worst block, {} dropouts, position heard {:.2} s",
        p.played_s(),
        mean * 100.0,
        worst * 100.0,
        p.dropouts(),
        st.transport.heard as f64 / rate as f64
    );
    if let Some(k) = st.knob_to_ear_s {
        println!("knob to ear {:.0} ms", k * 1000.0);
    }
    if !mix_only {
        println!(
            "meter: gain {:.1} dB, out {:.1} dBFS, CV {:?} V",
            st.meter.gain_db, st.meter.out_dbfs, st.meter.cv_v
        );
    }
    Ok(())
}
