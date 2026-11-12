//! The Stoner-Wohlfarth particle in f64: the reference for the WGSL kernel and the port of
//! `varimu/tape_particles/sw.py` (its docstring has the physics), step for step.

use std::f64::consts::PI;

pub const B_FLOOR: f64 = 1e-6;

/// One particle's fixed data.
#[derive(Debug, Clone, Copy)]
pub struct Particle {
    pub n: [f64; 3],
    pub hk: f64,
    /// mu0 Ms_p H_K V_act / kT.
    pub e0_kt: f64,
    pub hloc: [f64; 3],
}

#[inline]
fn fp(t: f64, a: f64, b: f64) -> (f64, f64) {
    let (s, c) = t.sin_cos();
    (s * c + a * s - b * c, (c * c - s * s) + a * c + b * s)
}

#[inline]
fn energy(t: f64, a: f64, b: f64) -> f64 {
    let (s, c) = t.sin_cos();
    0.5 * s * s - a * c - b * s
}

#[inline]
fn sign(x: f64) -> f64 {
    if x > 0.0 {
        1.0
    } else if x < 0.0 {
        -1.0
    } else {
        0.0
    }
}

/// A root of e' in [lo, hi] (sw.py's `_refine`).
fn refine(mut lo: f64, mut hi: f64, a: f64, b: f64, iters: usize) -> f64 {
    let (mut flo, _) = fp(lo, a, b);
    let mut t = 0.5 * (lo + hi);
    for _ in 0..iters {
        let (f, d) = fp(t, a, b);
        if sign(f) == sign(flo) {
            lo = t;
            flo = f;
        } else {
            hi = t;
        }
        let tn = t - f / d;
        t = if !tn.is_finite() || tn <= lo || tn >= hi {
            0.5 * (lo + hi)
        } else {
            tn
        };
    }
    t
}

/// The grid's sin / cos over [0, pi].
pub struct Grid {
    pub th: Vec<f64>,
    pub s: Vec<f64>,
    pub c: Vec<f64>,
}

impl Grid {
    pub fn new(g: usize) -> Self {
        let th: Vec<f64> = (0..g).map(|j| PI * j as f64 / (g - 1) as f64).collect();
        let s = th.iter().map(|t| t.sin()).collect();
        let c = th.iter().map(|t| t.cos()).collect();
        Grid { th, s, c }
    }
}

/// (theta+, theta-, theta_s, two) (sw.py's `extrema`).
pub fn extrema(a: f64, b: f64, grid: &Grid, iters: usize) -> (f64, f64, f64, bool) {
    let b = b.max(B_FLOOR);
    let g = grid.th.len();
    let mut first_rise = usize::MAX;
    let mut last_rise = usize::MAX;
    let mut first_fall = usize::MAX;
    let mut nrise = 0;
    let mut prev = grid.s[0] * grid.c[0] + a * grid.s[0] - b * grid.c[0] > 0.0;
    for j in 1..g {
        let pos = grid.s[j] * grid.c[j] + a * grid.s[j] - b * grid.c[j] > 0.0;
        if !prev && pos {
            nrise += 1;
            if first_rise == usize::MAX {
                first_rise = j - 1;
            }
            last_rise = j - 1;
        }
        if prev && !pos && first_fall == usize::MAX {
            first_fall = j - 1;
        }
        prev = pos;
    }
    // numpy's argmax of an all-false row is 0.
    let fr = if first_rise == usize::MAX {
        0
    } else {
        first_rise
    };
    let lr = if last_rise == usize::MAX {
        g - 2
    } else {
        last_rise
    };
    let ff = if first_fall == usize::MAX {
        0
    } else {
        first_fall
    };
    let two = nrise >= 2 && first_fall != usize::MAX;
    let step = grid.th[1] - grid.th[0];
    let t1 = refine(grid.th[fr], grid.th[fr] + step, a, b, iters);
    if !two {
        return (t1, t1, f64::NAN, false);
    }
    let t2 = refine(grid.th[lr], grid.th[lr] + step, a, b, iters);
    let ts = refine(grid.th[ff], grid.th[ff] + step, a, b, iters);
    (t1, t2, ts, true)
}

/// One step's outcome for a particle.
#[derive(Debug, Clone, Copy)]
pub struct Outcome {
    pub p: f64,
    pub m: [f64; 3],
}

#[inline]
fn phi(x: f64) -> f64 {
    if x < 1e-12 { 1.0 } else { -(-x).exp_m1() / x }
}

/// One step of dt for a particle in field h (A/m, hloc not yet added): sw.py's frame,
/// barriers, transition and moments, then the master equation (or, stochastic, the
/// two-state chain sampled with u).
#[allow(clippy::too_many_arguments)]
pub fn step(
    pt: &Particle,
    h: [f64; 3],
    p: f64,
    dt: f64,
    f0: f64,
    grid: &Grid,
    iters: usize,
    stochastic: Option<f64>,
) -> Outcome {
    let hr = [
        (h[0] + pt.hloc[0]) / pt.hk,
        (h[1] + pt.hloc[1]) / pt.hk,
        (h[2] + pt.hloc[2]) / pt.hk,
    ];
    let n = pt.n;
    let a = hr[0] * n[0] + hr[1] * n[1] + hr[2] * n[2];
    let perp = [hr[0] - a * n[0], hr[1] - a * n[1], hr[2] - a * n[2]];
    let b = (perp[0] * perp[0] + perp[1] * perp[1] + perp[2] * perp[2]).sqrt();
    let u = if b < 1e-12 {
        let alt = if n[0].abs() < 0.9 {
            [1.0, 0.0, 0.0]
        } else {
            [0.0, 1.0, 0.0]
        };
        let c = [
            n[1] * alt[2] - n[2] * alt[1],
            n[2] * alt[0] - n[0] * alt[2],
            n[0] * alt[1] - n[1] * alt[0],
        ];
        let l = (c[0] * c[0] + c[1] * c[1] + c[2] * c[2]).sqrt();
        [c[0] / l, c[1] / l, c[2] / l]
    } else {
        [perp[0] / b, perp[1] / b, perp[2] / b]
    };
    let (t1, t2, ts, two) = extrema(a, b, grid, iters);
    let bb = b.max(B_FLOOR);
    let (qp, qm) = if two {
        let es = energy(ts, a, bb);
        let dp = (es - energy(t1, a, bb)).max(0.0);
        let dm = (es - energy(t2, a, bb)).max(0.0);
        let rp = f0 * (-(dp * pt.e0_kt).min(745.0)).exp();
        let rm = f0 * (-(dm * pt.e0_kt).min(745.0)).exp();
        let g = dt * phi((rp + rm) * dt);
        ((rp * g).clamp(0.0, 1.0), (rm * g).clamp(0.0, 1.0))
    } else if a >= 0.0 {
        (0.0, 1.0)
    } else {
        (1.0, 0.0)
    };
    let p = match stochastic {
        Some(uu) => {
            let up = p > 0.5;
            let flip = if up { uu < qp } else { uu < qm };
            if flip { 1.0 - p } else { p }
        }
        None => p * (1.0 - qp) + (1.0 - p) * qm,
    };
    let (s1, c1) = t1.sin_cos();
    let (s2, c2) = t2.sin_cos();
    let mut m = [0.0; 3];
    for k in 0..3 {
        let mp = c1 * n[k] + s1 * u[k];
        let mm = c2 * n[k] + s2 * u[k];
        m[k] = p * mp + (1.0 - p) * mm;
    }
    Outcome { p, m }
}

/// ensemble.py's `hash_uniform`: a uniform in [0, 1) per (seed, particle, step).
pub fn hash_uniform(seed: u32, idx: u32, step: u32) -> f64 {
    let mut x = idx.wrapping_mul(0x9E37_79B1);
    x ^= seed
        .wrapping_mul(0x85EB_CA77)
        .wrapping_add(step.wrapping_mul(0xC2B2_AE3D));
    for _ in 0..2 {
        x ^= x >> 16;
        x = x.wrapping_mul(0x7FEB_352D);
        x ^= x >> 15;
        x = x.wrapping_mul(0x846C_A68B);
        x ^= x >> 16;
    }
    (x >> 8) as f64 / (1u32 << 24) as f64
}
