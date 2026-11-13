//! A monophonic line of notes rendered offline through a keyed device, as the Play view
//! plays it from a keyboard (the take renderer, `take_render::render`: the same Performer,
//! knobs and range switch), for parts split out of a MIDI file
//! (`scripts/mono_parts_render.py`).
//!
//!     cargo run --release -p varimu-app --example midi_render -- --device tube_synth
//!         --notes part.json --out part.wav [--quality draft-2x|production]
//!         [--set KEY=VALUE ...] [--range AUTO|LOW|HIGH] [--velocity-db 18] [--list]
//!
//! `part.json`: `{"notes": [[on_s, off_s, note, velocity], ...], "end_s": S}`, the notes in
//! order (overlaps are the keyboard's: the last key sounds). The output is the device's at
//! the quality's host rate (float WAV, 0 dBFS its full scale), `end_s` long from a fresh,
//! warm start. `--list` prints the panel's knobs (key, label, default) and exits.

use std::path::PathBuf;
use std::sync::atomic::AtomicBool;
use std::time::Instant;

use varimu_app::live::Circuit;
use varimu_app::midi::Wave;
use varimu_app::panel::{DEVICES, RangeMode, VELOCITY_RANGE_DB, knobs, values};
use varimu_app::performance::{Ev, Performance, Playing};
use varimu_app::settings::{Quality, Settings};
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

fn main() {
    if let Err(e) = run() {
        eprintln!("error: {e}");
        std::process::exit(1);
    }
}

fn run() -> Result<(), String> {
    let mut device = "tube_synth".to_string();
    let (mut notes_path, mut out) = (None::<PathBuf>, None::<PathBuf>);
    let mut quality = None::<Quality>;
    let mut sets: Vec<String> = Vec::new();
    let mut range = None::<String>;
    let mut velocity_db = VELOCITY_RANGE_DB;
    let mut list = false;
    let mut args = std::env::args().skip(1);
    while let Some(a) = args.next() {
        let mut next = || args.next().ok_or(format!("{a} needs a value"));
        match a.as_str() {
            "--device" => device = next()?,
            "--notes" => notes_path = Some(PathBuf::from(next()?)),
            "--out" => out = Some(PathBuf::from(next()?)),
            "--quality" => {
                let q = next()?;
                quality = Some(Quality::from_name(&q).ok_or(format!("no quality {q}"))?);
            }
            "--set" => sets.push(next()?),
            "--range" => range = Some(next()?),
            "--velocity-db" => velocity_db = next()?.parse().map_err(|e| format!("{e}"))?,
            "--list" => list = true,
            _ => return Err(format!("unknown option {a}")),
        }
    }
    let config = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../config");
    let dev = DEVICES
        .iter()
        .find(|d| d.id == device)
        .ok_or(format!("no device {device}"))?;
    let quality = quality.unwrap_or(dev.quality);
    let spec_settings = dev.play_settings(&Settings::load(&config, dev.quality)?);
    let spec_circuit = Circuit::load(&config, dev.circuit, spec_settings.cores()?)?;
    let mut panel = knobs(dev, spec_circuit.spec());
    if list {
        for k in &panel {
            println!("{:<16} {:<40} {}", k.key, k.label, k.default.py_str());
        }
        return Ok(());
    }
    for kv in &sets {
        let (k, x) = kv.split_once('=').ok_or(format!("--set {kv}: KEY=VALUE"))?;
        let knob = panel
            .iter_mut()
            .find(|n| n.key == k)
            .ok_or(format!("{} has no knob {k}", dev.id))?;
        knob.value = value(x);
    }
    if let Some(r) = &range {
        let knob = panel
            .iter_mut()
            .find(|k| RangeMode::from_value(&k.value).is_some())
            .ok_or(format!("{} has no range switch", dev.id))?;
        knob.value = Value::Str(r.to_uppercase());
    }
    let mode = varimu_app::panel::range_mode(&panel).unwrap_or(RangeMode::Auto);
    let mut v = values(&panel);

    let text = std::fs::read_to_string(notes_path.as_ref().ok_or("--notes is needed")?)
        .map_err(|e| e.to_string())?;
    let json: serde_json::Value = serde_json::from_str(&text).map_err(|e| e.to_string())?;
    let end_s = json["end_s"].as_f64().ok_or("no end_s")?;
    let notes = json["notes"].as_array().ok_or("no notes")?;

    // The performance at the quality's host rate, as the player would have logged it there.
    let base = Settings::load(&config, quality)?;
    let rate = match quality {
        Quality::Production => base.host(),
        _ => dev.play_settings(&base).host(),
    };
    let at = |t: f64| (t * rate as f64).round().max(0.0) as u64;
    let mut events: Vec<(u64, Ev)> = Vec::new();
    for n in notes {
        let on = n[0].as_f64().ok_or("a note without its start")?;
        let off = n[1].as_f64().ok_or("a note without its end")?;
        let note = n[2].as_u64().ok_or("a note without its key")? as u8;
        let velocity = n[3].as_u64().unwrap_or(100).clamp(1, 127) as u8;
        events.push((at(on), Ev::On { note, velocity }));
        events.push((at(off), Ev::Off { note }));
    }
    // In time; at one sample a key up before a key down (a repeated or legato note).
    events.sort_by_key(|&(t, e)| (t, matches!(e, Ev::On { .. })));
    let start_note = events
        .iter()
        .find_map(|&(_, e)| match e {
            Ev::On { note, .. } => Some(note),
            _ => None,
        })
        .unwrap_or(varimu_app::performance::START_NOTE);
    // The range switch where the first key wants it (AUTO), so the line doesn't start late.
    let switch = dev.pitch.and_then(|p| p.range);
    let start_low = switch.is_some_and(|r| {
        r.low_for(
            mode,
            Some(varimu_app::midi::TestOsc::note_hz(start_note)),
            false,
        )
    });
    if let Some(r) = switch {
        v = r.with_position(&v, start_low);
    }
    let perf = Performance {
        device: dev.id.to_string(),
        quality,
        rate,
        values: v,
        playing: Playing {
            wave: if dev.plays_own_oscillator() {
                Wave::Off
            } else {
                Wave::Saw
            },
            range_mode: mode,
            velocity_db,
            retrigger: true,
        },
        gain: 1.0,
        noise: false,
        start_note,
        start_low,
        events,
        knobs: Vec::new(),
        knobs_applied: false,
        end: at(end_s),
    };
    let prep = Prepared::load(&config, &perf, quality)?;
    let t0 = Instant::now();
    let mut last = 0.0;
    let (y, right) = render(
        &prep,
        &perf,
        |f| {
            if f - last >= 0.1 {
                last = f;
                eprintln!("  {:3.0}%  {:.0} s", f * 100.0, t0.elapsed().as_secs_f64());
            }
        },
        &AtomicBool::new(false),
    )?;
    let wall = t0.elapsed().as_secs_f64();
    let out = out.ok_or("--out is needed")?;
    if let Some(dir) = out.parent() {
        std::fs::create_dir_all(dir).map_err(|e| e.to_string())?;
    }
    let mono: Vec<f64> = match &right {
        Some(r) => y
            .iter()
            .zip(r)
            .map(|(&l, &r)| 0.5 * (l as f64 + r as f64))
            .collect(),
        None => y.iter().map(|&x| x as f64).collect(),
    };
    varimu_app::audio::write_wav(&out, &mono, rate)?;
    let peak = mono.iter().fold(0.0f64, |m, &x| m.max(x.abs()));
    println!(
        "{}: {} notes, {:.1} s at {} ({} Hz), peak {:.3} FS, {:.0} s ({:.2}x real time) -> {}",
        dev.id,
        notes.len(),
        end_s,
        quality.name(),
        rate,
        peak,
        wall,
        wall / end_s,
        out.display()
    );
    Ok(())
}
