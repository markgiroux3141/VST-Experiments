//! Where a device's real-time load goes, block by block, without an audio device: a
//! file through the device at its Play quality (draft-1x; the 5E3 draft-2x, its input
//! upsampled 2x as Live does; `--quality draft`: the project's 96 kHz at 1x), each
//! block's compute
//! time over its audio time next to the solver's counters (Newton iterations,
//! factorizations, device evaluations, halved steps) and the input's level and top
//! octaves. Writes a CSV and prints the heaviest blocks.
//!
//!     cargo run --release -p varimu-app --example load_profile -- --file F
//!         [--device fairchild_670] [--normalize -11.5] [--block 512] [--out load.csv]
//!         [--set KEY=VALUE ...] [--add-c NODE=FARADS ...] [--quality draft-1x|draft-2x|draft]
//!
//! The input is normalized as the Play view does: the file's loudest 8 s to
//! `--normalize` dBFS (sine-equivalent rms).

use std::io::Write;
use std::path::Path;
use std::time::Instant;

use circuitsim::dk::Refactor;
use circuitsim::ir::{Capacitor, Element};
use circuitsim::stream::Stream;
use varimu_app::audio;
use varimu_app::live::Circuit;
use varimu_app::panel::{DEVICES, knobs, values};
use varimu_app::resample::{StreamResampler, resample};
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

/// The gain (linear) that brings `x`'s loudest `len_s` to `target_dbfs`.
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

fn main() -> Result<(), String> {
    let mut args = std::env::args().skip(1);
    let (mut device, mut file, mut out) = ("fairchild_670".to_string(), None, None);
    let (mut target, mut block) = (-11.5, 512usize);
    let mut sets = Vec::new();
    let mut quality = None;
    let mut added: Vec<(String, f64)> = Vec::new();
    while let Some(a) = args.next() {
        let mut next = || args.next().ok_or(format!("{a} needs a value"));
        match a.as_str() {
            "--device" => device = next()?,
            "--file" => file = Some(next()?),
            "--out" => out = Some(next()?),
            "--normalize" => target = next()?.parse().map_err(|e| format!("{e}"))?,
            "--block" => block = next()?.parse().map_err(|e| format!("{e}"))?,
            "--quality" => {
                quality = Some(match next()?.as_str() {
                    "draft" => Quality::Draft,
                    "draft-1x" => Quality::Draft1x,
                    "draft-2x" => Quality::Draft2x,
                    q => return Err(format!("--quality {q}: draft, draft-1x or draft-2x")),
                })
            }
            "--add-c" => {
                let kv = next()?;
                let (k, v) = kv.split_once('=').ok_or("--add-c NODE=FARADS")?;
                added.push((k.to_string(), v.parse().map_err(|e| format!("{e}"))?));
            }
            "--set" => {
                let kv = next()?;
                let (k, v) = kv.split_once('=').ok_or("--set KEY=VALUE")?;
                sets.push((k.to_string(), value(v)));
            }
            _ => return Err(format!("unknown argument {a}")),
        }
    }
    let file = file.ok_or("--file is required")?;
    let config = Path::new(env!("CARGO_MANIFEST_DIR")).join("../../config");
    let dev = DEVICES
        .iter()
        .find(|d| d.id == device)
        .ok_or(format!("unknown device {device}"))?;
    let s = dev.play_settings(&Settings::load(&config, quality.unwrap_or(dev.quality))?);
    let k = s.oversample as usize;
    let circuit = Circuit::load(&config, dev.circuit, s.cores()?)?;
    let mut v = values(&knobs(dev, circuit.spec()));
    for (k, x) in sets {
        match v.iter_mut().find(|(key, _)| *key == k) {
            Some(e) => e.1 = x,
            None => v.push((k, x)),
        }
    }
    let mut ir = circuit.build(&v)?;
    // Experiments: capacitors to ground added to the built circuit (the circuit
    // file is untouched).
    for (node, c_f) in &added {
        let at = ir
            .sections
            .iter()
            .position(|s| {
                s.elements
                    .iter()
                    .any(|e| e.nodes().contains(&node.as_str()))
            })
            .ok_or(format!("no node {node}"))?;
        ir.sections[at].elements.push(Element::Capacitor(Capacitor {
            name: format!("Cadded_{node}"),
            a: node.clone(),
            b: "0".into(),
            c_f: *c_f,
        }));
        println!("added {c_f:e} F from {node} to ground");
    }

    let clip = audio::load(Path::new(&file), s.sample_rate)?;
    let gain = normalize(&clip, s.sample_rate, 8.0, target);
    let rate = s.host();
    let x: Vec<f64> = resample(&clip, s.sample_rate, rate)
        .iter()
        .map(|t| t * gain)
        .collect();
    let vfs = circuit.full_scale(&s).input_v;

    let opts = s.stream_options()?;
    let second = s.partition_sections(&ir);
    let h = 1.0 / s.sim_rate() as f64;
    let u0 = x[0] * vfs;
    let mut stream =
        Stream::new(&ir, &second, s.coupling()?, h, &opts, u0).map_err(|e| e.to_string())?;
    let n0 = (s.settle_s * rate as f64) as usize;
    stream
        .process(&vec![u0; n0 * k])
        .map_err(|e| e.to_string())?;
    // Oversampled, the input goes up to the simulation's rate as Live takes it.
    let mut up = StreamResampler::new(k, 1);
    up.process(&vec![x[0]; n0], &mut Vec::new());
    let cv = stream.names().iter().position(|n| n == "v(cv)");
    println!(
        "{} at {} ({} Hz host, {} Hz engine), gain {:+.1} dB, {:.1} s, blocks of {block}",
        dev.id,
        s.quality.name(),
        rate,
        s.sim_rate(),
        20.0 * gain.log10(),
        x.len() as f64 / rate as f64,
    );

    struct Row {
        t: f64,
        load: f64,
        iters: u64,
        facts: u64,
        evals: u64,
        halved: u64,
        retries: u64,
        in_dbfs: f64,
        hf_dbfs: f64,
        cv: f64,
    }
    let db = |r: f64| 20.0 * (r.max(1e-12)).log10();
    let rms = |a: &[f64]| (a.iter().map(|t| t * t).sum::<f64>() / a.len().max(1) as f64).sqrt();
    let mut rows = Vec::new();
    let mut prev = stream.stats().clone();
    // Per device and per refactor reason, summed over heavy blocks (load > 2) and
    // the rest: [heavy, light].
    let tr = stream.transient();
    let names: Vec<String> = tr.mna().devices.iter().map(|d| d.name.clone()).collect();
    let counts = |s: &Stream| {
        let t = s.transient();
        let ev = t
            .device_evaluations()
            .map(<[u64]>::to_vec)
            .unwrap_or_default();
        let (lim, why) = t
            .newton_counts()
            .map(|(l, w)| (l.to_vec(), w.to_vec()))
            .unwrap_or_default();
        (ev, lim, why)
    };
    let mut before = counts(&stream);
    let mut dev_ev = [vec![0u64; names.len()], vec![0u64; names.len()]];
    let mut dev_lim = dev_ev.clone();
    let mut why = [vec![0u64; Refactor::COUNT], vec![0u64; Refactor::COUNT]];
    let mut samples = [0usize; 2];
    let audio_s = block as f64 / rate as f64;
    let wall = Instant::now();
    for (i, chunk) in x.chunks(block).enumerate() {
        let mut xu = Vec::with_capacity(chunk.len() * k);
        up.process(chunk, &mut xu);
        let xv: Vec<f64> = xu.iter().map(|u| u * vfs).collect();
        let t0 = Instant::now();
        let o = stream.process(&xv).map_err(|e| e.to_string())?;
        let el = t0.elapsed().as_secs_f64();
        let st = stream.stats().clone();
        // The top octaves: the second difference (+12 dB/octave), referred to the
        // level a full-scale sine at the host's quarter rate would read.
        let d2: Vec<f64> = chunk
            .windows(3)
            .map(|w| (w[2] - 2.0 * w[1] + w[0]) / 2.0)
            .collect();
        rows.push(Row {
            t: i as f64 * audio_s,
            load: el / (chunk.len() as f64 / rate as f64),
            iters: st.iterations - prev.iterations,
            facts: st.factorizations - prev.factorizations,
            evals: st.device_evaluations - prev.device_evaluations,
            halved: st.halved_steps - prev.halved_steps,
            retries: st.exact_retries - prev.exact_retries,
            in_dbfs: db(rms(chunk) * 2f64.sqrt()),
            hf_dbfs: db(rms(&d2) * 2f64.sqrt()),
            cv: cv.map_or(f64::NAN, |c| {
                o[c].iter().sum::<f64>() / o[c].len().max(1) as f64
            }),
        });
        prev = st;
        let now = counts(&stream);
        let k = usize::from(rows.last().is_none_or(|r: &Row| r.load <= 2.0));
        samples[k] += chunk.len();
        for (acc, (a, b)) in [
            (&mut dev_ev[k], (&now.0, &before.0)),
            (&mut dev_lim[k], (&now.1, &before.1)),
            (&mut why[k], (&now.2, &before.2)),
        ] {
            for (x, (n, o)) in acc.iter_mut().zip(a.iter().zip(b.iter())) {
                *x += n - o;
            }
        }
        before = now;
    }
    let total = wall.elapsed().as_secs_f64() / (x.len() as f64 / rate as f64);

    if let Some(path) = &out {
        let mut f = std::fs::File::create(path).map_err(|e| e.to_string())?;
        writeln!(
            f,
            "t_s,load,iterations,factorizations,device_evaluations,halved_steps,exact_retries,in_dbfs,hf_dbfs,cv_v"
        )
        .map_err(|e| e.to_string())?;
        for r in &rows {
            writeln!(
                f,
                "{:.4},{:.4},{},{},{},{},{},{:.2},{:.2},{:.3}",
                r.t,
                r.load,
                r.iters,
                r.facts,
                r.evals,
                r.halved,
                r.retries,
                r.in_dbfs,
                r.hf_dbfs,
                r.cv
            )
            .map_err(|e| e.to_string())?;
        }
    }
    let n = rows.len() as f64;
    let mean = |f: &dyn Fn(&Row) -> f64| rows.iter().map(f).sum::<f64>() / n;
    let over = rows.iter().filter(|r| r.load > 1.0).count();
    println!(
        "whole run {total:.2}x real time; per block: load mean {:.2}, blocks over 1.0: {over} of {}",
        mean(&|r| r.load),
        rows.len()
    );
    println!(
        "per sample: iterations {:.2}, factorizations {:.3}, device evaluations {:.1}, halved {:.4}",
        mean(&|r| r.iters as f64) / block as f64,
        mean(&|r| r.facts as f64) / block as f64,
        mean(&|r| r.evals as f64) / block as f64,
        mean(&|r| r.halved as f64) / block as f64,
    );
    for (k, what) in ["heavy blocks (load > 2)", "other blocks"]
        .iter()
        .enumerate()
    {
        let n = samples[k].max(1) as f64;
        println!(
            "{what}, {:.1} s: factorizations per sample by cause:",
            samples[k] as f64 / rate as f64
        );
        for (r, name) in Refactor::NAMES.iter().enumerate() {
            println!("    {name:12} {:.3}", why[k][r] as f64 / n);
        }
        let mut order: Vec<usize> = (0..names.len()).collect();
        order.sort_by_key(|&d| std::cmp::Reverse(dev_ev[k][d]));
        println!("  per device and sample: evaluations, limited iterations");
        for &d in order.iter().take(12) {
            println!(
                "    {:24} {:7.2} {:7.3}",
                names[d],
                dev_ev[k][d] as f64 / n,
                dev_lim[k][d] as f64 / n
            );
        }
    }
    let mut idx: Vec<usize> = (0..rows.len()).collect();
    idx.sort_by(|&a, &b| rows[b].load.total_cmp(&rows[a].load));
    println!("heaviest blocks:");
    println!("     t_s  load  iter/smp fact/smp eval/smp halved retries  in_dBFS  hf_dBFS   cv_V");
    for &i in idx.iter().take(15) {
        let r = &rows[i];
        let b = block as f64;
        println!(
            "{:8.3} {:5.2} {:8.2} {:8.3} {:8.1} {:6} {:7} {:8.1} {:8.1} {:6.2}",
            r.t,
            r.load,
            r.iters as f64 / b,
            r.facts as f64 / b,
            r.evals as f64 / b,
            r.halved,
            r.retries,
            r.in_dbfs,
            r.hf_dbfs,
            r.cv
        );
    }
    Ok(())
}
