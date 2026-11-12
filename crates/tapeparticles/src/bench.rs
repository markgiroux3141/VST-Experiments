//! The interacting-particle bench (`varimu/tape_particles/bench.py`, the reference, and its
//! docstring for the physics): a periodic box of SW needles with dipolar interactions
//! (end charges plus a transverse dipole, minimum image, softened), every replica of the box
//! driven by its own applied field history, kinetic Monte Carlo. This is the f64 CPU
//! version; `gpu_bench` is the same in f32.
//!
//! Step j of a replica: the interaction field from the moments after step j - 1 (the
//! trace records the box's magnetization then), the SW step with the applied field
//! h_app[j] plus it, a uniform hash(seed, i, j) for the chain.

use std::path::Path;

use crate::io::{Meta, read_f64};
use crate::sw::{self, Grid, Particle};

pub const FOUR_PI: f64 = 4.0 * std::f64::consts::PI;

#[derive(Debug, Clone, Copy, PartialEq)]
pub enum Mode {
    Dynamic,
    Frozen,
    None,
}

pub struct Bench {
    pub side: f64,
    pub r: Vec<[f64; 3]>,
    pub parts: Vec<Particle>,
    pub l: Vec<f64>,
    pub v: Vec<f64>,
    pub ms_p: f64,
    pub soften: f64,
    pub sample_demag: [f64; 3],
    pub target_points: usize,
    pub mode: Mode,
    pub scale: f64,
    pub f0: f64,
    pub dt: f64,
    pub grid: usize,
    pub iters: usize,
    pub seed: u32,
    /// steps x reps x 3 (row major).
    pub h_app: Vec<f64>,
    pub reps: usize,
    /// The erased state (p in {0, 1}), the same for every replica.
    pub p0: Vec<f64>,
}

impl Bench {
    pub fn read(dir: &Path) -> Result<Self, String> {
        let m = Meta::read(dir)?;
        let n = m.usize("n_particles")?;
        let steps = m.usize("steps")?;
        let reps = m.usize("reps")?;
        let rr = read_f64(dir, "r", 3 * n)?;
        let nn = read_f64(dir, "n", 3 * n)?;
        let hk = read_f64(dir, "hk", n)?;
        let e0 = read_f64(dir, "e0_kt", n)?;
        let parts = (0..n)
            .map(|i| Particle {
                n: [nn[3 * i], nn[3 * i + 1], nn[3 * i + 2]],
                hk: hk[i],
                e0_kt: e0[i],
                hloc: [0.0; 3],
            })
            .collect();
        let sd = m.f64s("sample_demag")?;
        let mode = match m.str("interactions")?.as_str() {
            "dynamic" => Mode::Dynamic,
            "frozen" => Mode::Frozen,
            "none" => Mode::None,
            o => return Err(format!("interactions {o}")),
        };
        Ok(Bench {
            side: m.f64("side_m")?,
            r: (0..n).map(|i| [rr[3 * i], rr[3 * i + 1], rr[3 * i + 2]]).collect(),
            parts,
            l: read_f64(dir, "l", n)?,
            v: read_f64(dir, "v", n)?,
            ms_p: m.f64("ms_p")?,
            soften: m.f64("soften_m")?,
            sample_demag: [sd[0], sd[1], sd[2]],
            target_points: m.usize("target_points")?,
            mode,
            scale: m.f64("interaction_scale")?,
            f0: m.f64("f0")?,
            dt: m.f64("dt")?,
            grid: m.usize("grid")?,
            iters: m.usize("iters")?,
            seed: m.usize("seed")? as u32,
            h_app: read_f64(dir, "h_app", steps * reps * 3)?,
            reps,
            p0: read_f64(dir, "p0", n)?,
        })
    }

    pub fn n(&self) -> usize {
        self.parts.len()
    }

    pub fn steps(&self) -> usize {
        self.h_app.len() / (3 * self.reps)
    }
}

#[inline]
fn wrap(d: f64, side: f64) -> f64 {
    d - side * (d / side).round()
}

/// The interaction field at every particle (bench.py's `interaction_field`), threads over
/// targets.
pub fn interaction_field(b: &Bench, m: &[[f64; 3]], threads: usize) -> Vec<[f64; 3]> {
    let n = b.n();
    let mu: Vec<[f64; 3]> = (0..n)
        .map(|i| {
            let s = b.ms_p * b.v[i];
            [s * m[i][0], s * m[i][1], s * m[i][2]]
        })
        .collect();
    let mut q = vec![0.0; n];
    let mut perp = vec![[0.0; 3]; n];
    let mut ends = vec![[[0.0; 3]; 2]; n];
    for i in 0..n {
        let nn = b.parts[i].n;
        let ax = mu[i][0] * nn[0] + mu[i][1] * nn[1] + mu[i][2] * nn[2];
        q[i] = ax / b.l[i];
        for k in 0..3 {
            perp[i][k] = mu[i][k] - ax * nn[k];
            ends[i][0][k] = b.r[i][k] + 0.5 * b.l[i] * nn[k];
            ends[i][1][k] = b.r[i][k] - 0.5 * b.l[i] * nn[k];
        }
    }
    let a2 = b.soften * b.soften;
    let side = b.side;
    let mut out = vec![[0.0; 3]; n];
    let chunk = n.div_ceil(threads.max(1)).max(16);
    std::thread::scope(|s| {
        for (ci, oc) in out.chunks_mut(chunk).enumerate() {
            let (q, perp, ends) = (&q, &perp, &ends);
            s.spawn(move || {
                for (k, o) in oc.iter_mut().enumerate() {
                    let i = ci * chunk + k;
                    let nt = b.target_points;
                    let mut acc = [0.0; 3];
                    for o in 0..nt {
                        let off = (o as f64 + 0.5) / nt as f64 - 0.5;
                        let ri = [
                            b.r[i][0] + off * b.l[i] * b.parts[i].n[0],
                            b.r[i][1] + off * b.l[i] * b.parts[i].n[1],
                            b.r[i][2] + off * b.l[i] * b.parts[i].n[2],
                        ];
                        for j in 0..n {
                            if j == i {
                                continue;
                            }
                            for (e, sg) in [(0, 1.0), (1, -1.0)] {
                                let d = [
                                    wrap(ri[0] - ends[j][e][0], side),
                                    wrap(ri[1] - ends[j][e][1], side),
                                    wrap(ri[2] - ends[j][e][2], side),
                                ];
                                let r2 = d[0] * d[0] + d[1] * d[1] + d[2] * d[2] + a2;
                                let w = sg * q[j] / (FOUR_PI * r2 * r2.sqrt());
                                for c in 0..3 {
                                    acc[c] += w * d[c];
                                }
                            }
                            let d = [
                                wrap(ri[0] - b.r[j][0], side),
                                wrap(ri[1] - b.r[j][1], side),
                                wrap(ri[2] - b.r[j][2], side),
                            ];
                            let r2 = d[0] * d[0] + d[1] * d[1] + d[2] * d[2] + a2;
                            let p = perp[j];
                            let md = p[0] * d[0] + p[1] * d[1] + p[2] * d[2];
                            let inv = 1.0 / (FOUR_PI * r2 * r2.sqrt());
                            for c in 0..3 {
                                acc[c] += inv * (3.0 * md / r2 * d[c] - p[c]);
                            }
                        }
                    }
                    for c in acc.iter_mut() {
                        *c /= nt as f64;
                    }
                    *o = acc;
                }
            });
        }
    });
    let mf = mean_field(b, &mu, &perp);
    for o in out.iter_mut() {
        for c in 0..3 {
            o[c] += mf[c];
        }
    }
    out
}

/// bench.py's `mean_field`: the transverse dipoles' M_perp / 3 minus the sample's N . M.
pub fn mean_field(b: &Bench, mu: &[[f64; 3]], perp: &[[f64; 3]]) -> [f64; 3] {
    let vol = b.side * b.side * b.side;
    let mut mbar = [0.0; 3];
    let mut pbar = [0.0; 3];
    for (x, p) in mu.iter().zip(perp) {
        for c in 0..3 {
            mbar[c] += x[c] / vol;
            pbar[c] += p[c] / vol;
        }
    }
    [
        pbar[0] / 3.0 - b.sample_demag[0] * mbar[0],
        pbar[1] / 3.0 - b.sample_demag[1] * mbar[1],
        pbar[2] / 3.0 - b.sample_demag[2] * mbar[2],
    ]
}

fn magnetization(b: &Bench, m: &[[f64; 3]]) -> [f64; 3] {
    let vs: f64 = b.v.iter().sum();
    let mut out = [0.0; 3];
    for (i, x) in m.iter().enumerate() {
        for c in 0..3 {
            out[c] += b.v[i] * x[c] / vs;
        }
    }
    out
}

/// Every replica through its history: (final p per replica (reps x N), final M per replica
/// (reps x 3), trace (steps x reps x 3: M after each step) if asked).
pub fn run_cpu(b: &Bench, threads: usize, trace: bool) -> (Vec<f64>, Vec<f64>, Vec<f64>) {
    let n = b.n();
    let steps = b.steps();
    let grid = Grid::new(b.grid);
    let mut pall = Vec::with_capacity(b.reps * n);
    let mut fin = Vec::with_capacity(b.reps * 3);
    let mut tr = vec![0.0; if trace { steps * b.reps * 3 } else { 0 }];
    for r in 0..b.reps {
        let mut p = b.p0.clone();
        let mut m: Vec<[f64; 3]> = (0..n)
            .map(|i| {
                let s = 2.0 * p[i] - 1.0;
                let nn = b.parts[i].n;
                [s * nn[0], s * nn[1], s * nn[2]]
            })
            .collect();
        let mut frozen: Option<Vec<[f64; 3]>> = None;
        for j in 0..steps {
            let hint = match b.mode {
                Mode::None => vec![[0.0; 3]; n],
                Mode::Frozen => frozen
                    .get_or_insert_with(|| interaction_field(b, &m, threads))
                    .clone(),
                Mode::Dynamic => interaction_field(b, &m, threads),
            };
            let ha = &b.h_app[(j * b.reps + r) * 3..(j * b.reps + r) * 3 + 3];
            let chunk = n.div_ceil(threads.max(1)).max(64);
            let grid = &grid;
            std::thread::scope(|s| {
                for (ci, (pc, mc)) in p.chunks_mut(chunk).zip(m.chunks_mut(chunk)).enumerate() {
                    let hint = &hint;
                    s.spawn(move || {
                        for (k, (pp, mm)) in pc.iter_mut().zip(mc.iter_mut()).enumerate() {
                            let i = ci * chunk + k;
                            let h = [
                                ha[0] + b.scale * hint[i][0],
                                ha[1] + b.scale * hint[i][1],
                                ha[2] + b.scale * hint[i][2],
                            ];
                            let u = sw::hash_uniform(b.seed, i as u32, j as u32);
                            let o = sw::step(&b.parts[i], h, *pp, b.dt, b.f0, grid, b.iters, Some(u));
                            *pp = o.p;
                            *mm = o.m;
                        }
                    });
                }
            });
            if trace {
                let mm = magnetization(b, &m);
                tr[(j * b.reps + r) * 3..(j * b.reps + r) * 3 + 3].copy_from_slice(&mm);
            }
        }
        fin.extend_from_slice(&magnetization(b, &m));
        pall.extend_from_slice(&p);
    }
    (pall, fin, tr)
}
