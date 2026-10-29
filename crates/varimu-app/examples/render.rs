//! A render from the command line, through the app's render (`varimu_app::render`).
//!
//!     cargo run --release -p varimu-app --example render -- --circuit NAME
//!         --input FILE [--set KEY=VALUE ...] [--quality production|draft|draft-1x]
//!         [--out out.wav] [--probes DIR]
//!
//! FILE is an audio file (loaded as `load_audio` does) or raw little-endian float64
//! samples at the project's rate (`.f64`). `--probes` writes every probe in volts as
//! `<node>.f64`: scripts/app_render_agreement.py compares them with Python's render.
//! VALUEs are integers (no dot), numbers, true / false, or strings.

use std::path::{Path, PathBuf};
use std::sync::atomic::AtomicBool;

use varimu_app::audio;
use varimu_app::live::Circuit;
use varimu_app::render::render;
use varimu_app::settings::{Quality, Settings};
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
    let (mut circuit, mut input, mut out, mut probes) = (None, None, None, None);
    let mut quality = Quality::Production;
    let mut values = Vec::new();
    while let Some(a) = args.next() {
        let mut next = || args.next().ok_or(format!("{a} needs a value"));
        match a.as_str() {
            "--circuit" => circuit = Some(next()?),
            "--input" => input = Some(PathBuf::from(next()?)),
            "--out" => out = Some(PathBuf::from(next()?)),
            "--probes" => probes = Some(PathBuf::from(next()?)),
            "--quality" => {
                quality = match next()?.as_str() {
                    "production" => Quality::Production,
                    "draft" => Quality::Draft,
                    "draft-1x" => Quality::Draft1x,
                    "draft-2x" => Quality::Draft2x,
                    q => return Err(format!("unknown quality {q}")),
                }
            }
            "--set" => {
                let kv = next()?;
                let (k, v) = kv.split_once('=').ok_or(format!("--set {kv}: KEY=VALUE"))?;
                values.push((k.to_string(), value(v)));
            }
            _ => return Err(format!("unknown argument {a}")),
        }
    }
    let config = Path::new("config");
    let s = Settings::load(config, quality)?;
    let circuit = Circuit::load(config, &circuit.ok_or("--circuit is required")?, s.cores()?)?;
    let input = input.ok_or("--input is required")?;
    let x = if input.extension().is_some_and(|e| e == "f64") {
        std::fs::read(&input)
            .map_err(|e| e.to_string())?
            .chunks_exact(8)
            .map(|b| f64::from_le_bytes(b.try_into().unwrap()))
            .collect()
    } else {
        audio::load(&input, s.sample_rate)?
    };
    let r = render(&circuit, &values, &x, &s, |_| {}, &AtomicBool::new(false))?;
    println!(
        "{:.2} s of audio in {:.1} s ({:.1}x real time)",
        r.out.len() as f64 / r.sample_rate as f64,
        r.wall_s,
        r.realtime_factor()
    );
    if let Some(dir) = probes {
        std::fs::create_dir_all(&dir).map_err(|e| e.to_string())?;
        for (name, v) in &r.probes {
            let node = name.trim_start_matches("v(").trim_end_matches(')');
            let bytes: Vec<u8> = v.iter().flat_map(|x| x.to_le_bytes()).collect();
            std::fs::write(dir.join(format!("{node}.f64")), bytes).map_err(|e| e.to_string())?;
        }
    }
    if let Some(path) = out {
        audio::write_wav(&path, &r.out, r.sample_rate)?;
    }
    Ok(())
}
