//! What a partition costs in accuracy and buys in load (METHODOLOGY_REVIEW.md W1): a file
//! through a device at its Play quality, as one solve and as each partition given, the
//! error of each probe re the one solve's (rms, and in three bands), the run's speed and
//! its 10 ms blocks over real time. No audio device.
//!
//!     cargo run --release -p varimu-app --example cut_error -- --file F --device vox_ac30
//!         [--start S] [--seconds S] [--normalize -11.5] [--set KEY=VALUE ...]
//!         [--probe out --probe spk] [--coupling hold|extrapolate] [--block 480]
//!         --partition "TITLE,cut:ELEMENT|TITLE" [--partition ...]
//!         [--save F] [--against F] [--newton RELTOL,VNTOL]
//!
//! A partition is titles separated by ",", groups by "|" (load_profile's form), with
//! `cut:ELEMENT` entries for link lines; the readouts and mechanics it names
//! (`<PART> readout`, `<PART> mechanics`) are moved apart as the app does. "none" is the
//! one solve (always run first, the reference). The input is normalized as Play does.
//! `--save F` writes the one solve's probes (f64, little-endian, probe after probe);
//! `--against F` compares the one solve with such a file (another build or Newton
//! tolerance: `--newton` overrides the quality's).

use std::path::Path;
use std::time::Instant;

use circuitsim::stream::Stream;
use varimu_app::audio;
use varimu_app::live::Circuit;
use varimu_app::panel::{DEVICES, knobs, values};
use varimu_app::resample::resample;
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

/// The gain (linear) that brings `x`'s loudest `len_s` to `target_dbfs` (load_profile's).
fn normalize(x: &[f64], rate: u32, len_s: f64, target_dbfs: f64) -> f64 {
    let n = ((len_s * rate as f64) as usize).min(x.len()).max(1);
    let mut acc: f64 = x[..n].iter().map(|t| t * t).sum();
    let mut best = acc;
    for i in n..x.len() {
        acc += x[i] * x[i] - x[i - n] * x[i - n];
        best = best.max(acc);
    }
    let dbfs = 20.0 * ((best / n as f64).sqrt() * 2f64.sqrt()).log10();
    10f64.powf(((target_dbfs - dbfs).clamp(-40.0, 40.0)) / 20.0)
}

/// A second-order Butterworth low-pass (`high` false) or high-pass at `f` Hz (RBJ).
fn biquad(x: &[f64], f: f64, fs: f64, high: bool) -> Vec<f64> {
    let w = 2.0 * std::f64::consts::PI * f / fs;
    let (c, s) = (w.cos(), w.sin());
    let alpha = s / (2.0 * std::f64::consts::FRAC_1_SQRT_2);
    let (b0, b1, b2) = if high {
        ((1.0 + c) / 2.0, -(1.0 + c), (1.0 + c) / 2.0)
    } else {
        ((1.0 - c) / 2.0, 1.0 - c, (1.0 - c) / 2.0)
    };
    let (a0, a1, a2) = (1.0 + alpha, -2.0 * c, 1.0 - alpha);
    let mut y = vec![0.0; x.len()];
    let (mut x1, mut x2, mut y1, mut y2) = (0.0, 0.0, 0.0, 0.0);
    for (i, &v) in x.iter().enumerate() {
        let o = (b0 * v + b1 * x1 + b2 * x2 - a1 * y1 - a2 * y2) / a0;
        (x2, x1, y2, y1) = (x1, v, y1, o);
        y[i] = o;
    }
    y
}

/// Below 200 Hz, 200 Hz - 2 kHz, above 2 kHz (fourth-order edges).
fn bands(x: &[f64], fs: f64) -> [Vec<f64>; 3] {
    let lo = biquad(&biquad(x, 200.0, fs, false), 200.0, fs, false);
    let hi = biquad(&biquad(x, 2000.0, fs, true), 2000.0, fs, true);
    let mid: Vec<f64> = x
        .iter()
        .zip(&lo)
        .zip(&hi)
        .map(|((v, l), h)| v - l - h)
        .collect();
    [lo, mid, hi]
}

fn rms(a: &[f64]) -> f64 {
    (a.iter().map(|t| t * t).sum::<f64>() / a.len().max(1) as f64).sqrt()
}

fn db(r: f64) -> f64 {
    20.0 * r.max(1e-30).log10()
}

struct Run {
    probes: Vec<Vec<f64>>,
    speed: f64,
    over: usize,
    blocks: usize,
    worst: f64,
}

fn main() -> Result<(), String> {
    let mut args = std::env::args().skip(1);
    let (mut device, mut file) = ("vox_ac30".to_string(), None);
    let (mut start, mut seconds, mut target, mut block) = (0.0, 6.0, -11.5, 480usize);
    let (mut sets, mut parts, mut probes) = (Vec::new(), Vec::new(), Vec::new());
    let mut coupling: Option<String> = None;
    let mut quality = None;
    let (mut save, mut against, mut newton) = (None, None, None);
    while let Some(a) = args.next() {
        let mut next = || args.next().ok_or(format!("{a} needs a value"));
        match a.as_str() {
            "--device" => device = next()?,
            "--file" => file = Some(next()?),
            "--start" => start = next()?.parse().map_err(|e| format!("{e}"))?,
            "--seconds" => seconds = next()?.parse().map_err(|e| format!("{e}"))?,
            "--normalize" => target = next()?.parse().map_err(|e| format!("{e}"))?,
            "--block" => block = next()?.parse().map_err(|e| format!("{e}"))?,
            "--coupling" => coupling = Some(next()?),
            "--probe" => probes.push(next()?),
            "--save" => save = Some(next()?),
            "--against" => against = Some(next()?),
            "--newton" => {
                let v = next()?;
                let (r, n) = v.split_once(',').ok_or("--newton RELTOL,VNTOL")?;
                newton = Some((
                    r.parse::<f64>().map_err(|e| format!("{e}"))?,
                    n.parse::<f64>().map_err(|e| format!("{e}"))?,
                ));
            }
            "--quality" => {
                quality = Some(match next()?.as_str() {
                    "draft" => Quality::Draft,
                    "draft-1x" => Quality::Draft1x,
                    "draft-2x" => Quality::Draft2x,
                    q => return Err(format!("--quality {q}")),
                })
            }
            "--partition" => {
                let p = next()?;
                parts.push(if p == "none" {
                    Vec::new()
                } else {
                    p.split('|')
                        .enumerate()
                        .flat_map(|(i, g)| {
                            let mut v: Vec<String> = if i > 0 {
                                vec![circuitsim::partition::GROUP_BREAK.to_string()]
                            } else {
                                Vec::new()
                            };
                            v.extend(g.split(',').map(|t| t.trim().to_string()));
                            v
                        })
                        .filter(|t| !t.is_empty())
                        .collect()
                });
            }
            "--set" => {
                let kv = next()?;
                let (k, v) = kv.split_once('=').ok_or("--set KEY=VALUE")?;
                sets.push((k.to_string(), value(v)));
            }
            _ => return Err(format!("unknown argument {a}")),
        }
    }
    if probes.is_empty() {
        probes.push("out".to_string());
    }
    let file = file.ok_or("--file is required")?;
    let config = Path::new(env!("CARGO_MANIFEST_DIR")).join("../../config");
    let dev = DEVICES
        .iter()
        .find(|d| d.id == device)
        .ok_or(format!("unknown device {device}"))?;
    let base = dev.play_settings(&Settings::load(&config, quality.unwrap_or(dev.quality))?);
    if base.oversample != 1 {
        return Err("a quality at 1x (the comparison is at the engine's rate)".into());
    }
    let clip = audio::load(Path::new(&file), base.sample_rate)?;
    let gain = normalize(&clip, base.sample_rate, 8.0, target);
    let rate = base.host();
    let x: Vec<f64> = resample(&clip, base.sample_rate, rate)
        .iter()
        .map(|t| t * gain)
        .collect();
    let a = ((start * rate as f64) as usize).min(x.len());
    let b = (a + (seconds * rate as f64) as usize).min(x.len());
    let x = &x[a..b];
    println!(
        "{} at {}, gain {:+.1} dB, {:.1} s from {start} s, sets {:?}",
        dev.id,
        base.quality.name(),
        20.0 * gain.log10(),
        x.len() as f64 / rate as f64,
        sets.iter()
            .map(|(k, v)| format!("{k}={v:?}"))
            .collect::<Vec<_>>()
    );
    let mut variants = vec![Vec::new()];
    variants.extend(parts);
    let mut runs: Vec<Run> = Vec::new();
    for part in &variants {
        let mut s = base.clone();
        s.partition = part.clone();
        if let Some(c) = &coupling {
            s.partition_coupling = c.clone();
        }
        if let Some((r, n)) = newton {
            s.newton_reltol = r;
            s.newton_vntol = n;
        }
        let titles: Vec<&str> = part.iter().map(String::as_str).collect();
        let circuit = Circuit::load(&config, dev.circuit, s.cores()?)?;
        let circuit = if part.is_empty() {
            circuit.with_live_speaker(dev.live_speaker_v)
        } else {
            dev.live(circuit).with_apart_from(&titles)
        }
        .with_events(s.events);
        let mut v = values(&knobs(dev, circuit.spec()));
        for (k, x) in &sets {
            match v.iter_mut().find(|(key, _)| key == k) {
                Some(e) => e.1 = x.clone(),
                None => v.push((k.clone(), x.clone())),
            }
        }
        let ir = circuit.build(&v)?;
        let vfs = circuit.full_scale(&s).input_v;
        let opts = s.stream_options()?;
        let second = s.partition_sections(&ir);
        let h = 1.0 / s.sim_rate() as f64;
        let u0 = x[0] * vfs;
        let mut stream =
            Stream::new(&ir, &second, s.coupling()?, h, &opts, u0).map_err(|e| e.to_string())?;
        let idx: Vec<usize> = probes
            .iter()
            .map(|p| {
                stream
                    .names()
                    .iter()
                    .position(|n| *n == format!("v({p})"))
                    .ok_or(format!("no probe {p}"))
            })
            .collect::<Result<_, _>>()?;
        let n0 = (s.settle_s * rate as f64) as usize;
        stream.process(&vec![u0; n0]).map_err(|e| e.to_string())?;
        let mut got = vec![Vec::with_capacity(x.len()); probes.len()];
        let (mut over, mut worst, mut blocks) = (0usize, 0.0f64, 0usize);
        let wall = Instant::now();
        for chunk in x.chunks(block) {
            let xv: Vec<f64> = chunk.iter().map(|u| u * vfs).collect();
            let t0 = Instant::now();
            let o = stream.process(&xv).map_err(|e| e.to_string())?;
            let load = t0.elapsed().as_secs_f64() / (chunk.len() as f64 / rate as f64);
            blocks += 1;
            over += usize::from(load > 1.0);
            worst = worst.max(load);
            for (g, &i) in got.iter_mut().zip(&idx) {
                g.extend_from_slice(&o[i]);
            }
        }
        let speed = wall.elapsed().as_secs_f64() / (x.len() as f64 / rate as f64);
        runs.push(Run {
            probes: got,
            speed,
            over,
            blocks,
            worst,
        });
    }
    let fs = rate as f64;
    let reference = &runs[0];
    if let Some(path) = &save {
        let bytes: Vec<u8> = reference
            .probes
            .iter()
            .flatten()
            .flat_map(|v| v.to_le_bytes())
            .collect();
        std::fs::write(path, bytes).map_err(|e| e.to_string())?;
    }
    if let Some(path) = &against {
        let bytes = std::fs::read(path).map_err(|e| e.to_string())?;
        let all: Vec<f64> = bytes
            .chunks_exact(8)
            .map(|c| f64::from_le_bytes(c.try_into().expect("8 bytes")))
            .collect();
        let n = all.len() / probes.len();
        println!("the one solve against {path}:");
        for (k, (p, y)) in probes.iter().zip(&reference.probes).enumerate() {
            let r = &all[k * n..(k + 1) * n];
            let m = n.min(y.len());
            let e: Vec<f64> = y[..m].iter().zip(&r[..m]).map(|(a, b)| a - b).collect();
            let (eb, rb) = (bands(&e, fs), bands(&r[..m], fs));
            println!(
                "    {p}: {:.1} dB re its rms; by band {:.1} / {:.1} / {:.1} dB; max {:.3e}",
                db(rms(&e) / rms(&r[..m])),
                db(rms(&eb[0]) / rms(&rb[0])),
                db(rms(&eb[1]) / rms(&rb[1])),
                db(rms(&eb[2]) / rms(&rb[2])),
                e.iter().fold(0.0f64, |a, v| a.max(v.abs())),
            );
        }
    }
    for (part, run) in variants.iter().zip(&runs) {
        let name = if part.is_empty() {
            "one solve".to_string()
        } else {
            part.join(",").replace(",|,", " | ")
        };
        println!(
            "{name}: {:.2}x real time, {} of {} blocks over 1.0 (worst {:.2})",
            run.speed, run.over, run.blocks, run.worst
        );
        if std::ptr::eq(run, reference) {
            for (p, y) in probes.iter().zip(&reference.probes) {
                let [lo, mid, hi] = bands(y, fs);
                println!(
                    "    {p}: rms {:.3e}, min {:.3e}, max {:.3e}, bands < 200 Hz {:.1} / 200 Hz-2 kHz {:.1} / > 2 kHz {:.1} dB re rms",
                    rms(y),
                    y.iter().copied().fold(f64::INFINITY, f64::min),
                    y.iter().copied().fold(f64::NEG_INFINITY, f64::max),
                    db(rms(&lo) / rms(y)),
                    db(rms(&mid) / rms(y)),
                    db(rms(&hi) / rms(y))
                );
            }
            continue;
        }
        for ((p, y), r) in probes.iter().zip(&run.probes).zip(&reference.probes) {
            let n = y.len().min(r.len());
            let e: Vec<f64> = y[..n].iter().zip(&r[..n]).map(|(a, b)| a - b).collect();
            let (eb, rb) = (bands(&e, fs), bands(&r[..n], fs));
            let finite = e.iter().all(|v| v.is_finite());
            let mean = |a: &[f64]| a.iter().sum::<f64>() / a.len().max(1) as f64;
            println!(
                "    {p}: error {:.1} dB re its rms{}, mean {:+.3e} (the one solve's {:.3e}); by band {:.1} / {:.1} / {:.1} dB re the band",
                db(rms(&e) / rms(&r[..n])),
                if finite { "" } else { " (NOT FINITE)" },
                mean(&e),
                mean(&r[..n]),
                db(rms(&eb[0]) / rms(&rb[0])),
                db(rms(&eb[1]) / rms(&rb[1])),
                db(rms(&eb[2]) / rms(&rb[2])),
            );
        }
    }
    Ok(())
}
