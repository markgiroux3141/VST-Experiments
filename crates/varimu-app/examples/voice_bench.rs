//! A keyed device's stream as fast as it runs, with no audio device: its real-time factor
//! (wall time over audio time; under 1 keeps up) with a key held, for load work on the
//! Minimoog voice (docs/MINIMOOG_PLAN.md, "Real time").
//!
//!     cargo run --release -p varimu-app --example voice_bench -- [--device minimoog_voice]
//!         [--for S] [--note 57] [--block 512] [--restrike S] [--up S] [--set KEY=VALUE ...]
//!         [--partition "TITLE,TITLE|TITLE"] [--newton REL,VN] [--out out.f32]
//!         [--quality draft-1x|draft-2x|draft|production] (the device's by default)
//!
//! The key goes down 0.2 s in and stays (the gate on its key-down volts, every key string
//! on `--note`); the first 0.5 s isn't timed. Prints the factor over the whole run and its
//! worst 64-block window, and the output's peak. `CIRCUITSIM_PART_TIMING=1` adds each
//! part's busy and waiting time. `--out` saves the output (f32 little-endian, host rate).
//! `--probe NODE` (repeatable) runs circuitsim's `Stream` directly, as `Live` does, with those
//! nodes as its probes, and with `--out F` saves each as `F.NODE.f32`.

use std::io::Write;
use std::path::Path;
use std::time::Instant;

use circuitsim::ir::Probe;
use circuitsim::stream::Stream;
use varimu_app::live::{Circuit, Live, Values};
use varimu_app::panel::{DEVICES, Feed, key_feeds, knobs, values};
use varimu_app::settings::{Quality, Settings};
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
    let mut device = "minimoog_voice".to_string();
    let (mut seconds, mut note, mut block) = (10.0f64, 57u8, 512usize);
    let mut restrike: Option<f64> = None;
    let mut up_at: Option<f64> = None;
    let mut sets: Vec<(String, Value)> = Vec::new();
    let mut partition: Option<String> = None;
    let mut newton: Option<(f64, f64)> = None;
    let mut out: Option<String> = None;
    let mut quality: Option<Quality> = None;
    let mut probes: Vec<String> = Vec::new();
    while let Some(a) = args.next() {
        let mut next = || args.next().ok_or(format!("{a} needs a value"));
        match a.as_str() {
            "--device" => device = next()?,
            "--for" => seconds = next()?.parse().map_err(|e| format!("{e}"))?,
            "--note" => note = next()?.parse().map_err(|e| format!("{e}"))?,
            "--up" => up_at = Some(next()?.parse().map_err(|e| format!("{e}"))?),
            "--restrike" => restrike = Some(next()?.parse().map_err(|e| format!("{e}"))?),
            "--block" => block = next()?.parse().map_err(|e| format!("{e}"))?,
            "--set" => {
                let kv = next()?;
                let (k, v) = kv.split_once('=').ok_or("--set KEY=VALUE")?;
                sets.push((k.to_string(), value(v)));
            }
            "--partition" => partition = Some(next()?),
            "--newton" => {
                let v = next()?;
                let (r, n) = v.split_once(',').ok_or("--newton REL,VN")?;
                newton = Some((
                    r.parse().map_err(|e| format!("{e}"))?,
                    n.parse().map_err(|e| format!("{e}"))?,
                ));
            }
            "--out" => out = Some(next()?),
            "--quality" => {
                let q = next()?;
                quality = Some(Quality::from_name(&q).ok_or(format!("unknown quality {q}"))?);
            }
            "--probe" => probes.push(next()?),
            _ => return Err(format!("unknown argument {a}")),
        }
    }
    let config = Path::new("config");
    let dev = DEVICES
        .iter()
        .find(|d| d.id == device)
        .ok_or(format!("unknown device {device}"))?;
    let mut s = dev.play_settings(&Settings::load(config, quality.unwrap_or(dev.quality))?);
    if let Some(p) = &partition {
        s.partition = p
            .split('|')
            .enumerate()
            .flat_map(|(i, g)| {
                let mut v: Vec<String> = if i > 0 { vec!["|".to_string()] } else { vec![] };
                v.extend(g.split(',').filter(|t| !t.is_empty()).map(str::to_string));
                v
            })
            .collect();
    }
    if let Some((r, n)) = newton {
        s.newton_reltol = r;
        s.newton_vntol = n;
    }
    let circuit = dev
        .live(Circuit::load(config, dev.circuit, s.cores()?)?)
        .with_events(s.events);
    let panel = knobs(dev, circuit.spec());
    let mut v = values(&panel);
    for (k, x) in sets {
        match v.iter_mut().find(|(key, _)| *key == k) {
            Some(slot) => slot.1 = x,
            None => v.push((k, x)),
        }
    }
    let feeds = key_feeds(dev, circuit.spec())?;
    let level = |f: &Feed, down: bool| -> f64 {
        match f {
            Feed::Gate(up, dn) => {
                if down {
                    *dn
                } else {
                    *up
                }
            }
            Feed::Key(k) => k.volts(note),
            _ => 0.0,
        }
    };
    let c0: Vec<f64> = feeds.iter().map(|f| level(f, false)).collect();
    let rate = s.host() as usize;
    if !probes.is_empty() {
        return probe_run(
            &circuit, &v, &s, &feeds, &level, &c0, seconds, block, &probes, out, up_at,
        );
    }
    let t_build = Instant::now();
    let mut live = Live::with_controls(&[], v, circuit, s, 1.0, &c0)?;
    eprintln!(
        "built and settled in {:.2} s",
        t_build.elapsed().as_secs_f64()
    );
    let n_blocks = (seconds * rate as f64 / block as f64).ceil() as usize;
    let skip = (0.1 * rate as f64 / block as f64) as usize;
    let x = vec![0.0; block];
    let mut times = Vec::with_capacity(n_blocks);
    let mut peak = 0.0f32;
    let mut audio: Vec<f32> = Vec::new();
    for b in 0..n_blocks {
        let down = key_down(b * block, rate, restrike)
            && !up_at.is_some_and(|u| (b * block) as f64 >= u * rate as f64);
        let ctl: Vec<Vec<f64>> = feeds.iter().map(|f| vec![level(f, down); block]).collect();
        let refs: Vec<&[f64]> = ctl.iter().map(Vec::as_slice).collect();
        let t0 = Instant::now();
        let (y, _) = live.process_with(&x, &refs)?;
        times.push(t0.elapsed().as_secs_f64());
        peak = y.iter().fold(peak, |p, s| p.max(s.abs()));
        if out.is_some() {
            audio.extend_from_slice(&y);
        }
    }
    let audio_s = block as f64 / rate as f64;
    let t = &times[skip.min(times.len())..];
    let total: f64 = t.iter().sum();
    let worst = t
        .windows(64.min(t.len()))
        .map(|w| w.iter().sum::<f64>() / (w.len() as f64 * audio_s))
        .fold(0.0f64, f64::max);
    let worst_block = t.iter().fold(0.0f64, |m, &x| m.max(x)) / audio_s;
    println!(
        "{device}: {:.3}x real time (worst 64 blocks {:.3}x, worst block {:.2}x), peak {:.1} dBFS",
        total / (t.len() as f64 * audio_s),
        worst,
        worst_block,
        20.0 * (peak.max(1e-12) as f64).log10()
    );
    // The heaviest blocks: where, and the time over the mean block's.
    let mean = total / t.len().max(1) as f64;
    let mut idx: Vec<usize> = (0..t.len()).collect();
    idx.sort_by(|&a, &b| t[b].total_cmp(&t[a]));
    let heavy: Vec<String> = idx
        .iter()
        .take(6)
        .map(|&i| {
            format!(
                "{:.3} s +{:.2} ms",
                (i + skip) as f64 * audio_s,
                (t[i] - mean) * 1e3
            )
        })
        .collect();
    println!(
        "heaviest blocks (start, extra over the mean): {}",
        heavy.join(", ")
    );
    if let Some(path) = out {
        let mut f = std::fs::File::create(&path).map_err(|e| e.to_string())?;
        for s in audio {
            f.write_all(&s.to_le_bytes()).map_err(|e| e.to_string())?;
        }
    }
    Ok(())
}

/// `--probe`: the stream as `Live` runs it (settled with the controls at `c0`, then the blocks),
/// its probes the nodes named.
#[allow(clippy::too_many_arguments)]
fn probe_run(
    circuit: &Circuit,
    v: &Values,
    s: &Settings,
    feeds: &[Feed],
    level: &dyn Fn(&Feed, bool) -> f64,
    c0: &[f64],
    seconds: f64,
    block: usize,
    probes: &[String],
    out: Option<String>,
    up_at: Option<f64>,
) -> Result<(), String> {
    let mut ir = circuit.build(v)?;
    ir.probes = probes
        .iter()
        .map(|n| Probe::Voltage { node: n.clone() })
        .collect();
    let second = s.partition_sections(&ir);
    let h = 1.0 / s.sim_rate() as f64;
    let mut stream =
        Stream::with_controls(&ir, &second, s.coupling()?, h, &s.live_options()?, 0.0, c0)
            .map_err(|e| e.to_string())?;
    let rate = s.sim_rate() as usize;
    let n0 = (s.settle_s * rate as f64) as usize;
    stream.process(&vec![0.0; n0]).map_err(|e| e.to_string())?;
    let mut got: Vec<Vec<f64>> = vec![Vec::new(); probes.len()];
    let n_blocks = (seconds * rate as f64 / block as f64).ceil() as usize;
    for b in 0..n_blocks {
        let down = key_down(b * block, rate, None)
            && !up_at.is_some_and(|u| (b * block) as f64 >= u * rate as f64);
        let ctl: Vec<Vec<f64>> = feeds.iter().map(|f| vec![level(f, down); block]).collect();
        let refs: Vec<&[f64]> = ctl.iter().map(Vec::as_slice).collect();
        let o = stream
            .process_with(&vec![0.0; block], &refs)
            .map_err(|e| e.to_string())?;
        for (g, y) in got.iter_mut().zip(o) {
            g.extend(y);
        }
    }
    for (name, y) in probes.iter().zip(&got) {
        let peak = y.iter().fold(0.0f64, |m, x| m.max(x.abs()));
        println!("{name}: {} samples, peak {peak:.4} V", y.len());
        if let Some(path) = &out {
            let mut f =
                std::fs::File::create(format!("{path}.{name}.f32")).map_err(|e| e.to_string())?;
            for x in y {
                f.write_all(&(*x as f32).to_le_bytes())
                    .map_err(|e| e.to_string())?;
            }
        }
    }
    Ok(())
}

/// Whether the key is down at sample `n`: from 0.2 s on; with `restrike` S, released for the
/// last 0.1 s of every S seconds after that (struck again at 0.2 + k S).
fn key_down(n: usize, rate: usize, restrike: Option<f64>) -> bool {
    let t = n as f64 / rate as f64 - 0.2;
    match restrike {
        _ if t < 0.0 => false,
        Some(s) => t % s < s - 0.1,
        None => true,
    }
}
