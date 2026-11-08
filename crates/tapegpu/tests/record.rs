//! The GPU kernel against its f64 CPU reference (skipped without a GPU), on a block shaped
//! like the Ampex 351's: 15 ips, a ~99 kHz bias, cells 0.5 um apart tens of metres down
//! the tape (where f32 can't hold a position to a bias wavelength).

use tapegpu::{Block, FieldTable, Tables, reference};

/// circuitsim's `tape::Preisach::new` tables: (Q, D).
fn preisach(
    hc_median: f64,
    sigma_ln_hc: f64,
    sigma_hi: f64,
    h_max: f64,
    n: usize,
) -> (Vec<f64>, Vec<f64>) {
    let d = 2.0 * h_max / n as f64;
    let c: Vec<f64> = (0..n).map(|i| -h_max + (i as f64 + 0.5) * d).collect();
    let s2pi = (2.0 * std::f64::consts::PI).sqrt();
    let mut w = vec![0.0; n * n];
    let mut total = 0.0;
    for i in 0..n {
        for k in 0..n {
            let hc = 0.5 * (c[i] - c[k]);
            if hc <= 0.0 {
                continue;
            }
            let hi = -0.5 * (c[i] + c[k]);
            let u = (hc / hc_median).ln() / sigma_ln_hc;
            let f = (-0.5 * u * u).exp() / (hc * sigma_ln_hc * s2pi);
            let v = hi / sigma_hi;
            let g = (-0.5 * v * v).exp() / (sigma_hi * s2pi);
            w[i * n + k] = f * g * d * d / 2.0;
            total += w[i * n + k];
        }
    }
    w.iter_mut().for_each(|x| *x /= total);
    let m = n + 1;
    let mut col = vec![0.0; n * n];
    for k in 0..n {
        let mut acc = 0.0;
        for i in 0..n {
            acc += w[i * n + k];
            col[i * n + k] = acc;
        }
    }
    let mut q = vec![0.0; m * m];
    for i in 0..n {
        let mut acc = 0.0;
        for k in 0..n {
            acc += col[i * n + k];
            q[(i + 1) * m + k + 1] = acc;
        }
    }
    let mut dt = vec![0.0; m];
    let mut acc = 0.0;
    for i in (0..n).rev() {
        let mut row = 0.0;
        for k in 0..n {
            let s = i + k;
            let init = if s + 1 < n {
                1.0
            } else if s + 1 == n {
                0.5
            } else {
                0.0
            };
            row += w[i * n + k] * init;
        }
        acc += row;
        dt[i] = acc;
    }
    (q, dt)
}

struct Case {
    q: Vec<f64>,
    d: Vec<f64>,
    heights: Vec<f64>,
    s_cells: Vec<f64>,
    s_rec: Vec<f64>,
    hg: Vec<f64>,
    ranges: Vec<[u32; 2]>,
    axes: Vec<[f64; 3]>,
    tables: Vec<(f64, f64, Vec<f64>, Vec<f64>)>,
    hsx: Vec<f64>,
    hsy: Vec<f64>,
    hex: Vec<f64>,
    hey: Vec<f64>,
}

const HEAD: [f64; 3] = [51e-6, 1.5e-3, 5.5e-3];
const OE: f64 = 1000.0 / (4.0 * std::f64::consts::PI);
const H_MAX: f64 = 2000.0 * OE;

fn case() -> Case {
    let (q, d) = preisach(293.0 * OE, 0.33, 46.0 * OE, H_MAX, 256);
    let speed = 0.381;
    let f_bias = 99e3;
    let ds = speed / (f_bias * 7.62);
    let layers = 6;
    let heights: Vec<f64> = (0..layers)
        .map(|l| 1e-6 + (l as f64 + 0.5) * 12e-6 / layers as f64)
        .collect();
    // 40 m down the tape.
    let s0 = 40.0;
    let cells = 3000;
    let s_cells: Vec<f64> = (0..cells).map(|i| s0 + i as f64 * ds).collect();
    // The bias's extrema with a 1 kHz and a 7 kHz signal on them, passing the gap.
    let dt = 1.0 / (2.0 * f_bias);
    let t0 = (s0 - 2e-3) / speed;
    let n_peaks = ((cells as f64 * ds + 4e-3) / speed / dt) as usize;
    let mut s_rec = Vec::new();
    let mut hg = Vec::new();
    for j in 0..n_peaks {
        let t = t0 + j as f64 * dt;
        s_rec.push(t * speed);
        let sig = 9e3 * (2.0 * std::f64::consts::PI * 1e3 * t).sin()
            + 3e3 * (2.0 * std::f64::consts::PI * 7e3 * t).sin();
        let sign = if j % 2 == 0 { 1.0 } else { -1.0 };
        hg.push(sign * 2.4e5 + sig);
    }
    let mut ranges = Vec::new();
    for &y in &heights {
        let zone = 4.0 * HEAD[0] + 3.0 * y;
        for &s in &s_cells {
            let k0 = s_rec.partition_point(|&v| v < s - zone);
            let k1 = s_rec.partition_point(|&v| v <= s + zone);
            ranges.push([k0 as u32, k1 as u32]);
        }
    }
    let n_ax = 8;
    let axes: Vec<[f64; 3]> = (0..n_ax)
        .map(|j| {
            let phi = -std::f64::consts::FRAC_PI_2
                + (j as f64 + 0.5) * std::f64::consts::PI / n_ax as f64;
            [phi.cos(), phi.sin(), 1.0 / n_ax as f64]
        })
        .collect();
    let tables = heights
        .iter()
        .map(|&y| {
            let half = 4.0 * HEAD[0] + 3.0 * y;
            let dx = y / 40.0;
            let n = (2.0 * half / dx).ceil() as usize + 5;
            let x0 = -half - 2.0 * dx;
            let (fx, fy): (Vec<f64>, Vec<f64>) = (0..n)
                .map(|i| reference::head_field(HEAD, x0 + i as f64 * dx, y))
                .unzip();
            (x0, 1.0 / dx, fx, fy)
        })
        .collect();
    let lc = layers * cells;
    let wave = |k: usize, a: f64, f: f64| a * (k as f64 * f).sin();
    Case {
        q,
        d,
        heights,
        s_cells,
        s_rec,
        hg,
        ranges,
        axes,
        tables,
        hsx: (0..lc).map(|k| wave(k, 4e3, 0.013)).collect(),
        hsy: (0..lc).map(|k| wave(k, 2e3, 0.021)).collect(),
        hex: (0..lc).map(|k| wave(k, 5e3, 0.017)).collect(),
        hey: (0..lc).map(|k| wave(k, 1e3, 0.007)).collect(),
    }
}

fn worst(a: &(Vec<f64>, Vec<f64>), b: &(Vec<f64>, Vec<f64>)) -> f64 {
    a.0.iter()
        .chain(&a.1)
        .zip(b.0.iter().chain(&b.1))
        .fold(0.0, |w: f64, (x, y)| w.max((x - y).abs()))
}

#[test]
fn the_gpu_records_as_its_f64_reference() {
    if let Err(e) = tapegpu::available() {
        eprintln!("skipped: {e}");
        return;
    }
    let c = case();
    let ft: Vec<FieldTable> = c
        .tables
        .iter()
        .map(|(x0, inv, fx, fy)| FieldTable {
            x0: *x0,
            inv_dx: *inv,
            fx,
            fy,
        })
        .collect();
    for (name, field, steady) in [
        ("tables, no steady field", Some(&ft[..]), false),
        ("tables, steady fields", Some(&ft[..]), true),
        ("exact field, steady fields", None, true),
    ] {
        let b = Block {
            tables: Tables {
                key: [1, 2, 3, 4, 5],
                h_max: H_MAX,
                n: 256,
                q: &c.q,
                d: &c.d,
            },
            head: HEAD,
            heights: &c.heights,
            field,
            s_cells: &c.s_cells,
            ranges: &c.ranges,
            s_rec: &c.s_rec,
            hg: &c.hg,
            axes: &c.axes,
            h_static: steady.then_some((&c.hsx[..], &c.hsy[..])),
            h_end: steady.then_some((&c.hex[..], &c.hey[..])),
        };
        let r = reference::record(&b).unwrap();
        let t = std::time::Instant::now();
        let g = tapegpu::record(&b).unwrap();
        let el = t.elapsed();
        let w = worst(&r, &g);
        let rms = (r.0.iter().map(|v| v * v).sum::<f64>() / r.0.len() as f64).sqrt();
        eprintln!("{name}: worst |GPU - f64| {w:.2e} (M_x rms {rms:.3}), GPU {el:?}");
        // f32 tables and sums: ~1e-6 of Ms; a position lost to f32 would be ~1e-2.
        assert!(w < 2e-5, "{name}: {w}");
        assert!(rms > 0.01, "{name}: nothing recorded ({rms})");
    }
}
