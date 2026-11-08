//! Diagnostic: the Rhodes Suitcase's live device run offline, deterministically,
//! exactly as Play runs it (its quality's settings with the device's partition, coupling and
//! Newton tolerances, the live speaker voltage), on loud material, to catch a channel that
//! goes silent and hums. Prints both channels' levels and the power amps' inner nodes per
//! 0.25 s, and dumps chosen nodes at the simulation's rate (f32) for analysis.
//!
//!     cargo run --release -p varimu-app --example suitcase_latch -- [--scenario chords|all|bass]
//!         [--seconds S] [--set KEY=VALUE ...] [--dump DIR] [--coupling hold|extrapolate]
//!         [--newton REL,VN] [--one-solve]

use std::io::Write as _;
use std::path::{Path, PathBuf};

use circuitsim::ir::Probe;
use circuitsim::media::NoteEvent;
use circuitsim::stream::Stream;
use varimu_app::live::Circuit;
use varimu_app::panel::{DEVICES, knobs, values};
use varimu_app::settings::Settings;
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

/// Events at host samples.
fn scenario(name: &str, rate: f64, seconds: f64, vel: u8) -> Vec<(usize, NoteEvent)> {
    let at = |t: f64| (t * rate) as usize;
    let mut ev = Vec::new();
    match name {
        // Loud chords with the pedal down, walking up and down the keyboard, the pedal
        // lifted and put down again every 4 s (so many notes sustain, then clear).
        "chords" => {
            let shapes: [&[i32]; 4] = [
                &[0, 4, 7, 12],
                &[0, 3, 7, 10],
                &[0, 5, 9, 12],
                &[0, 4, 7, 11],
            ];
            let roots = [
                36, 41, 43, 48, 53, 55, 60, 65, 67, 72, 48, 43, 40, 36, 31, 28,
            ];
            let mut t = 0.5;
            let mut i = 0usize;
            let mut pedal_t = 0.5;
            ev.push((at(0.4), NoteEvent::Pedal { down: true }));
            while t < seconds - 1.0 {
                let root = roots[i % roots.len()];
                let shape = shapes[i % shapes.len()];
                // Left hand an octave below too.
                for &o in shape {
                    for base in [root - 12, root] {
                        let note = (base + o).clamp(21, 108) as u8;
                        ev.push((
                            at(t),
                            NoteEvent::On {
                                note,
                                velocity: vel,
                            },
                        ));
                    }
                }
                for &o in shape {
                    for base in [root - 12, root] {
                        let note = (base + o).clamp(21, 108) as u8;
                        ev.push((at(t + 0.4), NoteEvent::Off { note }));
                    }
                }
                t += 0.5;
                i += 1;
                if t - pedal_t >= 4.0 {
                    ev.push((at(t - 0.05), NoteEvent::Pedal { down: false }));
                    ev.push((at(t - 0.01), NoteEvent::Pedal { down: true }));
                    pedal_t = t;
                }
            }
        }
        // Every key at 127, pedal down, again every 3 s (play.rs --strike-all 127 --restrike 3).
        "all" => {
            ev.push((at(0.4), NoteEvent::Pedal { down: true }));
            let mut t = 0.5;
            while t < seconds - 1.0 {
                for (j, note) in (21u8..=108).enumerate() {
                    ev.push((
                        at(t + j as f64 * 0.001),
                        NoteEvent::On {
                            note,
                            velocity: vel,
                        },
                    ));
                }
                t += 3.0;
            }
        }
        // Low octaves pounded at 127 (the biggest swings), pedal down.
        "bass" => {
            ev.push((at(0.4), NoteEvent::Pedal { down: true }));
            let mut t = 0.5;
            let mut i = 0;
            while t < seconds - 1.0 {
                let root = [28, 31, 33, 36, 38, 40][i % 6];
                for note in [root, root + 7, root + 12, root + 19] {
                    ev.push((
                        at(t),
                        NoteEvent::On {
                            note,
                            velocity: vel,
                        },
                    ));
                }
                t += 0.25;
                i += 1;
            }
        }
        _ => panic!("unknown scenario {name}"),
    }
    ev.sort_by_key(|e| e.0);
    ev
}

fn rms(x: &[f64]) -> f64 {
    (x.iter().map(|v| v * v).sum::<f64>() / x.len().max(1) as f64).sqrt()
}
fn mean(x: &[f64]) -> f64 {
    x.iter().sum::<f64>() / x.len().max(1) as f64
}
/// The part of `x` at the simulation's Nyquist (rms of the second difference / 4).
fn nyq(x: &[f64]) -> f64 {
    if x.len() < 3 {
        return 0.0;
    }
    let d: Vec<f64> = x
        .windows(3)
        .map(|w| (w[0] - 2.0 * w[1] + w[2]) / 4.0)
        .collect();
    rms(&d)
}
fn db(x: f64) -> f64 {
    20.0 * x.max(1e-12).log10()
}

fn main() -> Result<(), String> {
    let mut args = std::env::args().skip(1);
    let (mut scen, mut seconds) = ("chords".to_string(), 20.0);
    let mut sets: Vec<(String, Value)> = Vec::new();
    let mut dump: Option<PathBuf> = None;
    let mut coupling: Option<String> = None;
    let mut newton: Option<(f64, f64)> = None;
    let mut one_solve = false;
    let mut vel: u8 = 127;
    let mut tols: Vec<(String, f64)> = Vec::new();
    while let Some(a) = args.next() {
        match a.as_str() {
            "--scenario" => scen = args.next().ok_or("--scenario NAME")?,
            "--velocity" => {
                vel = args
                    .next()
                    .ok_or("--velocity V")?
                    .parse()
                    .map_err(|e| format!("{e}"))?
            }
            "--seconds" => {
                seconds = args
                    .next()
                    .ok_or("--seconds S")?
                    .parse()
                    .map_err(|e| format!("{e}"))?
            }
            "--set" => {
                let kv = args.next().ok_or("--set KEY=VALUE")?;
                let (k, v) = kv.split_once('=').ok_or("--set KEY=VALUE")?;
                sets.push((k.to_string(), value(v)));
            }
            "--dump" => dump = Some(PathBuf::from(args.next().ok_or("--dump DIR")?)),
            "--coupling" => coupling = Some(args.next().ok_or("--coupling C")?),
            "--newton" => {
                let s = args.next().ok_or("--newton REL,VN")?;
                let (r, v) = s.split_once(',').ok_or("--newton REL,VN")?;
                newton = Some((
                    r.parse().map_err(|e| format!("{e}"))?,
                    v.parse().map_err(|e| format!("{e}"))?,
                ));
            }
            "--one-solve" => one_solve = true,
            "--tol" => {
                let kv = args.next().ok_or("--tol MODEL=K")?;
                let (m, x) = kv.split_once('=').ok_or("--tol MODEL=K")?;
                tols.push((m.to_string(), x.parse().map_err(|e| format!("{e}"))?));
            }
            _ => return Err(format!("unknown argument {a}")),
        }
    }
    let config = Path::new("config");
    let dev = DEVICES
        .iter()
        .find(|d| d.id == "rhodes_suitcase")
        .ok_or("no device")?;
    let mut s = dev.play_settings(&Settings::load(config, dev.quality)?);
    if let Some(c) = coupling {
        s.partition_coupling = c;
    }
    if let Some((r, v)) = newton {
        s.newton_reltol = r;
        s.newton_vntol = v;
    }
    if one_solve {
        s.partition.clear();
    }
    let circuit = dev
        .live(Circuit::load(config, dev.circuit, s.cores()?)?)
        .with_events(s.events);
    let panel = knobs(dev, circuit.spec());
    let mut v = values(&panel);
    for (k, x) in sets {
        match v.iter_mut().find(|(key, _)| *key == k) {
            Some(e) => e.1 = x,
            None => v.push((k, x)),
        }
    }
    eprintln!("panel: {v:?}");
    let mut ir = circuit.build(&v)?;
    for (m, x) in &tols {
        let mut hit = false;
        for model in ir.models.iter_mut() {
            match model {
                circuitsim::ir::DeviceModel::Bjt(q) if &q.name == m => {
                    q.tol_scale = Some(*x);
                    hit = true;
                }
                circuitsim::ir::DeviceModel::JunctionDiode(d) if &d.name == m => {
                    d.tol_scale = Some(*x);
                    hit = true;
                }
                _ => {}
            }
        }
        if !hit {
            let names: Vec<String> = ir
                .models
                .iter()
                .filter_map(|m| match m {
                    circuitsim::ir::DeviceModel::Bjt(q) => Some(q.name.clone()),
                    circuitsim::ir::DeviceModel::JunctionDiode(d) => Some(d.name.clone()),
                    _ => None,
                })
                .collect();
            return Err(format!("no BJT / diode model {m}; have {names:?}"));
        }
    }
    for node in [
        "b_q1b", "b_c1", "b_c3", "a3ao", "a3bo", "a3am", "a3bm", "a_c1", "a_q1b",
    ] {
        if !ir
            .probes
            .iter()
            .any(|p| matches!(p, Probe::Voltage { node: n } if n == node))
        {
            ir.probes.push(Probe::Voltage {
                node: node.to_string(),
            });
        }
    }
    let k = s.oversample as usize;
    let host = s.host() as f64;
    let opts = s.live_options()?;
    let second = s.partition_sections(&ir);
    eprintln!(
        "quality {:?}, sim rate {}, partition {:?}, coupling {}, newton ({}, {})",
        s.quality,
        s.sim_rate(),
        second,
        s.partition_coupling,
        s.newton_reltol,
        s.newton_vntol
    );
    let h = 1.0 / s.sim_rate() as f64;
    let mut stream = Stream::with_controls(&ir, &second, s.coupling()?, h, &opts, 0.0, &[])
        .map_err(|e| e.to_string())?;
    let names = stream.names().to_vec();
    let idx = |n: &str| names.iter().position(|x| x == &format!("v({n})"));
    let n0 = (s.settle_s * host) as usize;
    if n0 > 0 {
        stream
            .process(&vec![0.0; n0 * k])
            .map_err(|e| e.to_string())?;
    }
    let events = scenario(&scen, host, seconds, vel);
    let block = (0.01 * host) as usize; // the player's 10 ms blocks
    let total = (seconds * host) as usize;
    let watch = [
        "out", "out_r", "a_amp", "b_amp", "a3ao", "a3bo", "a_t", "b_t", "a_q1b", "b_q1b", "vp",
        "vn", "pre_a", "pre_b",
    ];
    let wi: Vec<(String, usize)> = watch
        .iter()
        .filter_map(|n| idx(n).map(|i| (n.to_string(), i)))
        .collect();
    let mut keep: Vec<Vec<f32>> = vec![Vec::new(); wi.len()];
    // Per window of 0.25 s at the simulation's rate.
    let win = (0.25 * host) as usize * k;
    let mut acc: Vec<Vec<f64>> = vec![Vec::new(); wi.len()];
    let col = |n: &str| wi.iter().position(|(m, _)| m == n).unwrap();
    let mut e = 0;
    let mut pos = 0;
    let t0 = std::time::Instant::now();
    println!(
        "{:>6} | {:>7} {:>7} | {:>7} {:>7} {:>7} | {:>7} {:>7} {:>7} | {:>7} {:>7} | {:>6} {:>6}",
        "t s",
        "L dB",
        "R dB",
        "a_amp",
        "aNyq",
        "a3aoNy",
        "b_amp",
        "bNyq",
        "a3boNy",
        "a3ao",
        "a3bo",
        "vp",
        "vn"
    );
    let mut first_bad: Option<f64> = None;
    while pos < total {
        let n = block.min(total - pos);
        let end = pos + n;
        let mut notes = Vec::new();
        while e < events.len() && events[e].0 < end {
            notes.push(((events[e].0.saturating_sub(pos)) * k, events[e].1));
            e += 1;
        }
        if !notes.is_empty() {
            stream.queue_notes(&notes).map_err(|e| e.to_string())?;
        }
        let out = stream
            .process(&vec![0.0; n * k])
            .map_err(|e| e.to_string())?;
        for (j, (_, i)) in wi.iter().enumerate() {
            acc[j].extend_from_slice(&out[*i]);
            if dump.is_some() {
                keep[j].extend(out[*i].iter().map(|&x| x as f32));
            }
        }
        pos = end;
        while acc[0].len() >= win {
            let w: Vec<Vec<f64>> = acc.iter_mut().map(|a| a.drain(..win).collect()).collect();
            let t = pos as f64 / host;
            let (l, r) = (rms(&w[col("out")]), rms(&w[col("out_r")]));
            let row = format!(
                "{:6.2} | {:7.1} {:7.1} | {:7.2} {:7.3} {:7.3} | {:7.2} {:7.3} {:7.3} | {:7.2} {:7.2} | {:6.1} {:6.1}",
                t,
                db(l),
                db(r),
                mean(&w[col("a_amp")]),
                nyq(&w[col("a_amp")]),
                nyq(&w[col("a3ao")]),
                mean(&w[col("b_amp")]),
                nyq(&w[col("b_amp")]),
                nyq(&w[col("a3bo")]),
                mean(&w[col("a3ao")]),
                mean(&w[col("a3bo")]),
                mean(&w[col("vp")]),
                mean(&w[col("vn")]),
            );
            let bad = (db(l) - db(r)).abs() > 15.0
                || mean(&w[col("a_amp")]).abs() > 2.0
                || mean(&w[col("b_amp")]).abs() > 2.0
                || nyq(&w[col("a_amp")]) > 0.2
                || nyq(&w[col("b_amp")]) > 0.2;
            if bad && first_bad.is_none() {
                first_bad = Some(t);
            }
            println!("{row}{}", if bad { "  <<" } else { "" });
        }
        std::io::stdout().flush().ok();
    }
    eprintln!(
        "{:.1} s of audio in {:.1} s; first anomaly: {:?}",
        seconds,
        t0.elapsed().as_secs_f64(),
        first_bad
    );
    if let Some(dir) = dump {
        std::fs::create_dir_all(&dir).map_err(|e| e.to_string())?;
        for (j, (name, _)) in wi.iter().enumerate() {
            let bytes: Vec<u8> = keep[j].iter().flat_map(|x| x.to_le_bytes()).collect();
            std::fs::write(dir.join(format!("{name}.f32")), bytes).map_err(|e| e.to_string())?;
        }
        std::fs::write(dir.join("rate.txt"), format!("{}", s.sim_rate()))
            .map_err(|e| e.to_string())?;
        eprintln!("dumped {} nodes to {}", wi.len(), dir.display());
    }
    Ok(())
}
