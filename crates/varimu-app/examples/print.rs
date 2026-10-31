//! A print from the command line (docs/SESSION_FX_PLAN.md, F1): a file through a chain of
//! inserts, as the Session view prints a track, with each insert's real-time factor.
//!
//!     cargo run --release -p varimu-app --example print -- --file FILE
//!         [--rate 48000] [--seconds S] [--quality Q]
//!         --device D [--set KEY=VALUE ...] [--trim DB] [--device D2 ...]
//!         [--cache DIR] [--out out.wav]
//!
//! Each `--device` starts an insert; `--set`, `--trim` and `--quality` after it apply to
//! it (`--quality` before the first applies to all). The file is read as mono, resampled
//! to `--rate` (the session's, 48 kHz by default) and cut to `--seconds`.

use std::path::PathBuf;
use std::sync::Arc;
use std::sync::atomic::AtomicBool;

use varimu_app::audio;
use varimu_app::print::{Prepared, Slot, print};
use varimu_app::resample::resample;
use varimu_app::settings::Quality;
use varimu_circuit::yaml::Value;

fn value(s: &str) -> Value {
    if let Ok(i) = s.parse::<i64>() {
        Value::Int(i)
    } else if let Ok(x) = s.parse::<f64>() {
        Value::Float(x)
    } else if s == "true" || s == "false" {
        Value::Bool(s == "true")
    } else {
        Value::Str(s.to_string())
    }
}

fn main() -> Result<(), String> {
    let mut args = std::env::args().skip(1);
    let (mut file, mut out, mut cache, mut seconds) = (None, None, None, None);
    let mut rate = 48_000u32;
    let mut quality: Option<Quality> = None;
    let mut slots: Vec<Slot> = Vec::new();
    while let Some(a) = args.next() {
        let mut next = || args.next().ok_or(format!("{a} needs a value"));
        match a.as_str() {
            "--file" => file = Some(PathBuf::from(next()?)),
            "--out" => out = Some(PathBuf::from(next()?)),
            "--cache" => cache = Some(PathBuf::from(next()?)),
            "--rate" => rate = next()?.parse().map_err(|e| format!("--rate: {e}"))?,
            "--seconds" => seconds = Some(next()?.parse::<f64>().map_err(|e| format!("{e}"))?),
            "--quality" => {
                let q = next()?;
                let q = Quality::from_name(&q).ok_or(format!("unknown quality {q}"))?;
                match slots.last_mut() {
                    Some(s) => s.quality = q,
                    None => quality = Some(q),
                }
            }
            "--device" => {
                let mut s = Slot::new(&next()?);
                if let Some(q) = quality {
                    s.quality = q;
                }
                slots.push(s);
            }
            "--set" | "--trim" => {
                let s = slots.last_mut().ok_or(format!("{a} before any --device"))?;
                let v = next()?;
                if a == "--trim" {
                    s.trim_db = v.parse().map_err(|e| format!("--trim: {e}"))?;
                } else {
                    let (k, x) = v.split_once('=').ok_or(format!("--set {v}: KEY=VALUE"))?;
                    s.values.push((k.to_string(), value(x)));
                }
            }
            _ => return Err(format!("unknown argument {a}")),
        }
    }
    let file = file.ok_or("--file is required")?;
    if slots.is_empty() {
        return Err("at least one --device".into());
    }
    let config = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../config");
    let d = audio::decode(&file)?;
    let mut x = resample(&d.mono(), d.rate, rate);
    if let Some(s) = seconds {
        x.truncate((s * rate as f64) as usize);
    }
    let mut cur: Arc<Vec<f32>> = Arc::new(x.iter().map(|&v| v as f32).collect());
    println!(
        "{}: {:.1} s at {rate} Hz",
        file.display(),
        cur.len() as f64 / rate as f64
    );
    let no = AtomicBool::new(false);
    for s in &slots {
        let p = Prepared::load(&config, &s.device, s.quality, s.noise)?;
        let t0 = std::time::Instant::now();
        let mut last = -1i32;
        let r = print(
            &p,
            s,
            &cur,
            rate,
            cache.as_deref(),
            |f| {
                let pct = (f * 10.0) as i32;
                if pct != last {
                    last = pct;
                    eprint!("\r  {} {}%   ", s.device, pct * 10);
                }
            },
            &no,
        )?;
        eprintln!();
        let peak = r.audio.iter().fold(0f32, |m, &v| m.max(v.abs()));
        println!(
            "  {} at {}: {:.2}x real time{} ({:.1} s wall), peak {:.1} dBFS, key {}",
            s.device,
            s.quality.name(),
            r.realtime_factor,
            if r.cached { " (cached)" } else { "" },
            t0.elapsed().as_secs_f64(),
            20.0 * (peak.max(1e-12) as f64).log10(),
            r.key
        );
        cur = r.audio;
    }
    if let Some(o) = out {
        let y: Vec<f64> = cur.iter().map(|&v| v as f64).collect();
        audio::write_wav(&o, &y, rate)?;
        println!("wrote {}", o.display());
    }
    Ok(())
}
