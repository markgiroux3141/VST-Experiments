//! The tape's recording kernel on the GPU (TAPE_SPEED_PLAN.md P5; `crates/tapegpu`) against
//! the f64 CPU kernel: `tape::record` with per-cell zones, tabulated and exact head fields,
//! steady fields. Needs the `gpu` feature (`cargo test -p circuitsim --features gpu`) and a
//! GPU (skipped without one); without the feature a GPU recording is refused.

use circuitsim::tape::{Head, Recording, preisach, record};

const OE: f64 = 1000.0 / (4.0 * std::f64::consts::PI);

struct Case {
    heights: Vec<f64>,
    zones: Vec<f64>,
    s_rec: Vec<f64>,
    hg: Vec<f64>,
    s_cells: Vec<f64>,
    axes: Vec<[f64; 3]>,
    hx: Vec<f64>,
    hy: Vec<f64>,
}

fn case() -> Case {
    let (speed, f_bias) = (0.381, 99e3);
    let heights: Vec<f64> = (0..6).map(|l| 1e-6 + (l as f64 + 0.5) * 2e-6).collect();
    // 25 m down the tape; 0.5 um cells.
    let s_cells: Vec<f64> = (0..4000)
        .map(|i| 25.0 + i as f64 * speed / (f_bias * 7.62))
        .collect();
    let dt = 1.0 / (2.0 * f_bias);
    let t0 = (s_cells[0] - 1e-3) / speed;
    let n = ((s_cells[s_cells.len() - 1] - s_cells[0] + 2e-3) / speed / dt) as usize;
    let t: Vec<f64> = (0..n).map(|j| t0 + j as f64 * dt).collect();
    let s_rec = t.iter().map(|t| t * speed).collect();
    let hg = t
        .iter()
        .enumerate()
        .map(|(j, t)| {
            let sign = if j % 2 == 0 { 1.0 } else { -1.0 };
            sign * 3000.0 * OE + 300.0 * OE * (2.0 * std::f64::consts::PI * 1100.0 * t).sin()
        })
        .collect();
    // Per-cell zones, wider where the cell index says so (as local zones vary).
    let mut zones = Vec::new();
    for l in 0..heights.len() {
        for c in 0..s_cells.len() {
            zones.push(1.5e-4 + 2e-6 * l as f64 + 4e-5 * ((c as f64 * 0.003).sin()).abs());
        }
    }
    let axes = (0..8)
        .map(|j| {
            let f = -std::f64::consts::FRAC_PI_2 + (j as f64 + 0.5) * std::f64::consts::PI / 8.0;
            [f.cos(), f.sin(), 0.125]
        })
        .collect();
    let lc = heights.len() * s_cells.len();
    Case {
        hx: (0..lc)
            .map(|k| 40.0 * OE * (k as f64 * 0.011).sin())
            .collect(),
        hy: (0..lc)
            .map(|k| 20.0 * OE * (k as f64 * 0.019).cos())
            .collect(),
        heights,
        zones,
        s_rec,
        hg,
        s_cells,
        axes,
    }
}

#[test]
fn the_gpu_kernel_is_the_cpu_kernel_within_f32() {
    let c = case();
    let p = preisach(293.0 * OE, 0.33, 46.0 * OE, 2000.0 * OE, 256);
    let rec = |table_step: f64, steady: bool, gpu: bool| {
        record(&Recording {
            preisach: &p,
            head: Head {
                gap: 51e-6,
                pole: 1.5e-3,
                relax: 5.5e-3,
            },
            heights: &c.heights,
            zones: &c.zones,
            s_rec: &c.s_rec,
            hg: &c.hg,
            s_cells: &c.s_cells,
            axes: &c.axes,
            h_static: steady.then_some((&c.hx[..], &c.hy[..])),
            h_end: None,
            table_step,
            threads: 0,
            gpu,
        })
    };
    let probe = rec(1.0 / 40.0, false, true);
    if cfg!(not(feature = "gpu")) {
        assert!(probe.unwrap_err().contains("gpu"));
        return;
    }
    if let Err(e) = probe {
        eprintln!("skipped: {e}");
        return;
    }
    for (table_step, steady) in [(1.0 / 40.0, false), (1.0 / 40.0, true), (0.0, true)] {
        let cpu = rec(table_step, steady, false).unwrap();
        let gpu = rec(table_step, steady, true).unwrap();
        let worst = cpu
            .0
            .iter()
            .chain(&cpu.1)
            .zip(gpu.0.iter().chain(&gpu.1))
            .fold(0.0, |w: f64, (a, b)| w.max((a - b).abs()));
        let rms = (cpu.0.iter().map(|v| v * v).sum::<f64>() / cpu.0.len() as f64).sqrt();
        eprintln!("table_step {table_step}, steady {steady}: worst {worst:.2e}, rms {rms:.3}");
        assert!(rms > 0.01);
        assert!(worst < 2e-5, "{worst}");
    }
}
