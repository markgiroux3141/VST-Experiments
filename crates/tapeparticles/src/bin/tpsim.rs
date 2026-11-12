//! Runs a scenario directory written by `varimu/tape_particles` and writes its outputs
//! there (`out_*.f64`, `out.json`).
//!
//!     tpsim bench DIR [--gpu] [--threads N] [--trace]
//!     tpsim medium DIR [--threads N]
//!     tpsim uniform DIR [--threads N] [--trace]

use std::path::PathBuf;
use std::time::Instant;

use tapeparticles::io::{Meta, read_f64, write_f64};
use tapeparticles::sw::Particle;
use tapeparticles::{bench, gpu_bench, medium};

fn main() {
    if let Err(e) = run() {
        eprintln!("tpsim: {e}");
        std::process::exit(1);
    }
}

fn run() -> Result<(), String> {
    let args: Vec<String> = std::env::args().collect();
    let what = args.get(1).ok_or("usage: tpsim bench|medium|uniform DIR")?;
    let dir = PathBuf::from(args.get(2).ok_or("no DIR")?);
    let flag = |f: &str| args.iter().any(|a| a == f);
    let threads = args
        .iter()
        .position(|a| a == "--threads")
        .and_then(|i| args.get(i + 1))
        .and_then(|s| s.parse().ok())
        .unwrap_or(6usize);
    let t0 = Instant::now();
    let mut info = serde_json::Map::new();
    match what.as_str() {
        "bench" => {
            let b = bench::Bench::read(&dir)?;
            let trace = flag("--trace");
            let (p, fin, tr) = if flag("--gpu") {
                info.insert("backend".into(), "gpu".into());
                info.insert(
                    "device".into(),
                    tapeparticles::gpu::gpu()?.describe().into(),
                );
                let (p, fin, tr, h) = gpu_bench::run_gpu(&b, trace)?;
                write_f64(&dir, "out_hint", &h)?;
                (p, fin, tr)
            } else {
                info.insert("backend".into(), "cpu".into());
                bench::run_cpu(&b, threads, trace)
            };
            write_f64(&dir, "out_p", &p)?;
            write_f64(&dir, "out_m", &fin)?;
            if trace {
                write_f64(&dir, "out_trace", &tr)?;
            }
        }
        "field" => {
            // The interaction field of the erased state p0 (the kernels' agreement test).
            let b = bench::Bench::read(&dir)?;
            let m: Vec<[f64; 3]> = (0..b.n())
                .map(|i| {
                    let s = 2.0 * b.p0[i] - 1.0;
                    let nn = b.parts[i].n;
                    [s * nn[0], s * nn[1], s * nn[2]]
                })
                .collect();
            let h = bench::interaction_field(&b, &m, threads);
            let flat: Vec<f64> = h.iter().flat_map(|x| x.iter().copied()).collect();
            write_f64(&dir, "out_hint", &flat)?;
        }
        "medium" => {
            let sc = medium::Scenario::read(&dir)?;
            let mut be = medium::Cpu::new(&sc, threads);
            let (p, m, updates) = medium::run(&sc, &mut be);
            write_f64(&dir, "out_p", &p)?;
            let flat: Vec<f64> = m.iter().flat_map(|x| x.iter().copied()).collect();
            write_f64(&dir, "out_m", &flat)?;
            info.insert("updates".into(), (updates as u64).into());
        }
        "uniform" => {
            let m = Meta::read(&dir)?;
            let n = m.usize("n_particles")?;
            let reps = m.usize("reps")?;
            let steps = m.usize("steps")?;
            let nn = read_f64(&dir, "n", 3 * n)?;
            let hk = read_f64(&dir, "hk", n)?;
            let e0 = read_f64(&dir, "e0_kt", n)?;
            let hl = read_f64(&dir, "hloc", 3 * n)?;
            let parts: Vec<Particle> = (0..n)
                .map(|i| Particle {
                    n: [nn[3 * i], nn[3 * i + 1], nn[3 * i + 2]],
                    hk: hk[i],
                    e0_kt: e0[i],
                    hloc: [hl[3 * i], hl[3 * i + 1], hl[3 * i + 2]],
                })
                .collect();
            let trace = flag("--trace");
            let (fin, tr) = medium::uniform(
                &parts,
                &read_f64(&dir, "v", n)?,
                &read_f64(&dir, "p0", n)?,
                &read_f64(&dir, "happ", steps * reps)?,
                reps,
                m.f64("dt")?,
                m.f64("f0")?,
                m.usize("grid")?,
                m.usize("iters")?,
                threads,
                trace,
            );
            write_f64(&dir, "out_m", &fin)?;
            if trace {
                write_f64(&dir, "out_trace", &tr)?;
            }
        }
        o => return Err(format!("unknown command {o}")),
    }
    info.insert("seconds".into(), t0.elapsed().as_secs_f64().into());
    std::fs::write(
        dir.join("out.json"),
        serde_json::Value::Object(info).to_string(),
    )
    .map_err(|e| e.to_string())?;
    Ok(())
}
