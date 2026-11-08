//! The proxy against its device (docs/MIDI_TAKES_PLAN.md N2's done-when): held keys played
//! through both at the same panel, the device rendered offline at its play quality
//! (`take_render`), compared per case: pitch (cents), level (dB, rms over the held stretch).
//!
//!     cargo run --release -p varimu-app --example proxy_compare -- [--device tube_synth]
//!         [--key NOTE:VELOCITY ...] [--set KEY=VALUE ...] [--range-db 18] [--seconds 1.5]
//!
//! Each case is one key held from 0.1 s for `--seconds`, measured over its second half.

use std::path::PathBuf;
use std::sync::Arc;
use std::sync::atomic::AtomicBool;

use varimu_app::live::Circuit;
use varimu_app::midi::Wave;
use varimu_app::panel::{DEVICES, RangeMode, knobs, values};
use varimu_app::performance::{Ev, Performance, Playing, START_NOTE};
use varimu_app::proxy::{Proxy, Tables};
use varimu_app::settings::Settings;
use varimu_app::take_render::{Prepared, render};
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

/// The fundamental's frequency (Hz) from rising zero crossings.
fn freq(y: &[f32], rate: f64) -> f64 {
    let ups: Vec<f64> = y
        .windows(2)
        .enumerate()
        .filter(|(_, w)| w[0] < 0.0 && w[1] >= 0.0)
        .map(|(i, w)| i as f64 + w[0] as f64 / (w[0] - w[1]) as f64)
        .collect();
    if ups.len() < 3 {
        return f64::NAN;
    }
    (ups.len() - 1) as f64 / ((ups[ups.len() - 1] - ups[0]) / rate)
}

fn rms_db(y: &[f32]) -> f64 {
    let r = (y.iter().map(|&v| (v as f64).powi(2)).sum::<f64>() / y.len().max(1) as f64).sqrt();
    20.0 * r.max(1e-12).log10()
}

fn main() {
    if let Err(e) = run() {
        eprintln!("error: {e}");
        std::process::exit(1);
    }
}

fn run() -> Result<(), String> {
    let (mut device, mut keys, mut sets) = ("tube_synth".to_string(), Vec::new(), Vec::new());
    let (mut range_db, mut seconds) = (18.0, 1.5);
    let mut args = std::env::args().skip(1);
    while let Some(a) = args.next() {
        let mut next = || args.next().ok_or(format!("{a} needs a value"));
        match a.as_str() {
            "--device" => device = next()?,
            "--key" => keys.push(next()?),
            "--set" => sets.push(next()?),
            "--range-db" => range_db = next()?.parse().map_err(|e| format!("{e}"))?,
            "--seconds" => seconds = next()?.parse().map_err(|e| format!("{e}"))?,
            _ => return Err(format!("unknown option {a}")),
        }
    }
    if keys.is_empty() {
        keys = ["71:127", "60:100", "48:110", "67:90", "72:127", "36:127"]
            .iter()
            .map(|s| s.to_string())
            .collect();
    }
    let config = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../config");
    let dev = DEVICES
        .iter()
        .find(|d| d.id == device)
        .ok_or(format!("no device {device}"))?;
    let s = dev.play_settings(&Settings::load(&config, dev.quality)?);
    let spec_circuit = Circuit::load(&config, dev.circuit, s.cores()?)?;
    let mut v = values(&knobs(dev, spec_circuit.spec()));
    for kv in &sets {
        let (k, x) = kv.split_once('=').ok_or(format!("--set {kv}"))?;
        match v.iter_mut().find(|(n, _)| n == k) {
            Some(e) => e.1 = value(x),
            None => v.push((k.to_string(), value(x))),
        }
    }
    let tables = Arc::new(Tables::load(&config, dev.id)?.ok_or("no proxy tables")?);
    let rate = s.host();
    let playing = Playing {
        wave: Wave::Off,
        range_mode: RangeMode::Auto,
        velocity_db: range_db,
        retrigger: true,
    };
    let n = ((seconds + 0.1) * rate as f64) as usize;
    let (a, b) = (((0.1 + seconds / 2.0) * rate as f64) as usize, n);
    println!(
        "{:>6} {:>4}  {:>9} {:>9} {:>7}  {:>8} {:>8} {:>6}",
        "note", "vel", "dev Hz", "proxy Hz", "cents", "dev dB", "proxy dB", "diff"
    );
    for k in &keys {
        let (note, vel) = k
            .split_once(':')
            .ok_or(format!("--key {k}: NOTE:VELOCITY"))?;
        let note: u8 = note.parse().map_err(|e| format!("{e}"))?;
        let vel: u8 = vel.parse().map_err(|e| format!("{e}"))?;
        let on = (
            rate as u64 / 10,
            Ev::On {
                note,
                velocity: vel,
            },
        );
        let perf = Performance {
            device: dev.id.into(),
            quality: dev.quality,
            rate,
            values: v.clone(),
            playing,
            gain: 1.0,
            noise: false,
            start_note: START_NOTE,
            start_low: false,
            events: vec![on],
            knobs: Vec::new(),
            knobs_applied: false,
            end: n as u64,
        };
        let prep = Prepared::load(&config, &perf, dev.quality)?;
        let d = render(&prep, &perf, |_| {}, &AtomicBool::new(false))?.0;
        let mut p = Proxy::new(tables.clone(), rate, 1);
        p.set_values(&v);
        p.set_playing(playing);
        let mut y = vec![0.0f32; n];
        p.process(&[(on.0 as usize, on.1)], &mut y[..]);
        let (fd, fp) = (freq(&d[a..b], rate as f64), freq(&y[a..b], rate as f64));
        let (ld, lp) = (rms_db(&d[a..b]), rms_db(&y[a..b]));
        println!(
            "{note:>6} {vel:>4}  {fd:>9.2} {fp:>9.2} {:>7.1}  {ld:>8.2} {lp:>8.2} {:>+6.2}",
            1200.0 * (fp / fd).log2(),
            lp - ld
        );
    }
    Ok(())
}
