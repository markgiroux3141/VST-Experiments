//! The recording: a strip of particles moving past the record head with AC bias, the
//! cell-averaged field of the coating updated every few steps (`varimu/tape_particles/
//! medium.py`'s `record`, the reference, step for step). The backends advance particles
//! (the CPU in f64 here, the GPU in f32 in `gpu_medium`); the driver owns the cell field.

use std::path::Path;

use crate::field::{CellField, Kernels};
use crate::head::{self, Head};
use crate::io::{Meta, read_f64, read_kernels};
use crate::sw::{self, Grid, Particle};

/// Everything a run needs (read from a scenario directory written by medium.py).
pub struct Scenario {
    pub parts: Vec<Particle>,
    pub x: Vec<f64>,
    pub y: Vec<f64>,
    pub v: Vec<f64>,
    pub cell: Vec<u32>,
    pub p0: Vec<f64>,
    pub cell_start: Vec<usize>,
    pub step_x: Vec<f64>,
    pub step_hg: Vec<f64>,
    pub step_c0: Vec<usize>,
    pub step_c1: Vec<usize>,
    pub img: Kernels,
    pub free: Kernels,
    pub layers: usize,
    pub ncx: usize,
    pub n_fft: usize,
    pub update_every: usize,
    pub dt: f64,
    pub f0: f64,
    pub grid: usize,
    pub iters: usize,
    pub stochastic: bool,
    pub seed: u32,
    pub relax_steps: usize,
    pub relax_dt: f64,
    pub head: Head,
    pub ms_p: f64,
    pub cell_vol: f64,
}

impl Scenario {
    pub fn read(dir: &Path) -> Result<Self, String> {
        let m = Meta::read(dir)?;
        let n = m.usize("n_particles")?;
        let nn = read_f64(dir, "n", 3 * n)?;
        let hk = read_f64(dir, "hk", n)?;
        let e0 = read_f64(dir, "e0_kt", n)?;
        let hl = read_f64(dir, "hloc", 3 * n)?;
        let parts = (0..n)
            .map(|i| Particle {
                n: [nn[3 * i], nn[3 * i + 1], nn[3 * i + 2]],
                hk: hk[i],
                e0_kt: e0[i],
                hloc: [hl[3 * i], hl[3 * i + 1], hl[3 * i + 2]],
            })
            .collect();
        let layers = m.usize("layers")?;
        let ncx = m.usize("ncx")?;
        let steps = m.usize("steps")?;
        let g = m.f64s("head")?;
        Ok(Scenario {
            parts,
            x: read_f64(dir, "x", n)?,
            y: read_f64(dir, "y", n)?,
            v: read_f64(dir, "v", n)?,
            cell: read_f64(dir, "cell", n)?
                .iter()
                .map(|&c| c as u32)
                .collect(),
            p0: read_f64(dir, "p0", n)?,
            cell_start: read_f64(dir, "cell_start", ncx * layers + 1)?
                .iter()
                .map(|&c| c as usize)
                .collect(),
            step_x: read_f64(dir, "step_x", steps)?,
            step_hg: read_f64(dir, "step_hg", steps)?,
            step_c0: read_f64(dir, "step_c0", steps)?
                .iter()
                .map(|&c| c as usize)
                .collect(),
            step_c1: read_f64(dir, "step_c1", steps)?
                .iter()
                .map(|&c| c as usize)
                .collect(),
            img: read_kernels(dir, "img", layers)?,
            free: read_kernels(dir, "free", layers)?,
            layers,
            ncx,
            n_fft: m.usize("n_fft")?,
            update_every: m.usize("update_every")?,
            dt: m.f64("dt")?,
            f0: m.f64("f0")?,
            grid: m.usize("grid")?,
            iters: m.usize("iters")?,
            stochastic: m.bool("stochastic")?,
            seed: m.usize("seed")? as u32,
            relax_steps: m.usize("relax_steps")?,
            relax_dt: m.f64("relax_dt")?,
            head: Head {
                gap: g[0],
                pole: g[1],
                relax: g[2],
            },
            ms_p: m.f64("ms_p")?,
            cell_vol: m.f64("cell_vol")?,
        })
    }

    pub fn steps(&self) -> usize {
        self.step_x.len()
    }

    /// Particle index range of step j's zone.
    pub fn zone(&self, j: usize) -> (usize, usize) {
        let l = self.layers;
        (
            self.cell_start[self.step_c0[j] * l],
            self.cell_start[self.step_c1[j] * l],
        )
    }
}

/// What a backend does to the particles.
pub trait Backend {
    /// Steps j0..j1 for the particles in [lo, hi) (each stepped only inside its step's
    /// zone), the cell field held.
    fn advance(&mut self, sc: &Scenario, j0: usize, j1: usize, lo: usize, hi: usize);
    /// One step of dt with no head field, every particle (the tape off the head).
    fn relax(&mut self, sc: &Scenario, r: usize);
    /// sum of v m_x, v m_y per cell id in [c_lo, c_hi).
    fn deposit(&mut self, sc: &Scenario, c_lo: usize, c_hi: usize) -> (Vec<f64>, Vec<f64>);
    /// The cell field (A/m) for cell ids [c_lo, c_hi).
    fn set_field(&mut self, c_lo: usize, fx: &[f64], fy: &[f64]);
    /// (p, m) per particle.
    fn finish(&mut self) -> (Vec<f64>, Vec<[f64; 3]>);
}

/// Run the scenario on a backend; returns (p, m) and the number of field updates.
pub fn run(sc: &Scenario, be: &mut dyn Backend) -> (Vec<f64>, Vec<[f64; 3]>, usize) {
    let nl = sc.layers;
    let ncells = sc.ncx * nl;
    let cf = CellField::new(sc.n_fft, sc.ncx, nl);
    let scale = sc.ms_p / sc.cell_vol;
    let mut mx = vec![0.0; ncells];
    let mut my = vec![0.0; ncells];
    let mut update = |be: &mut dyn Backend, lo: usize, hi: usize, kern: &Kernels| {
        let (dx, dy) = be.deposit(sc, lo, hi);
        for c in lo..hi {
            mx[c] = scale * dx[c - lo];
            my[c] = scale * dy[c - lo];
        }
        let (fx, fy) = cf.apply(kern, &mx, &my);
        be.set_field(0, &fx, &fy);
    };
    update(be, 0, ncells, &sc.img);
    let mut updates = 1;
    let steps = sc.steps();
    let u = sc.update_every.max(1);
    let mut j = 0;
    while j < steps {
        let j1 = (j + u).min(steps);
        let (mut lo, mut hi) = (usize::MAX, 0);
        for k in j..j1 {
            let (a, b) = sc.zone(k);
            lo = lo.min(a);
            hi = hi.max(b);
        }
        be.advance(sc, j, j1, lo, hi);
        // The cells stepped since the last update.
        let c_lo = sc.step_c0[j] * nl;
        let c_hi = (j..j1).map(|k| sc.step_c1[k]).max().unwrap_or(0) * nl;
        update(be, c_lo, c_hi.max(c_lo), &sc.img);
        updates += 1;
        j = j1;
    }
    for r in 0..sc.relax_steps {
        update(be, 0, ncells, &sc.free);
        updates += 1;
        be.relax(sc, r);
    }
    let (p, m) = be.finish();
    (p, m, updates)
}

/// The f64 CPU backend (threads over particles).
pub struct Cpu {
    pub p: Vec<f64>,
    pub m: Vec<[f64; 3]>,
    pub fx: Vec<f64>,
    pub fy: Vec<f64>,
    pub threads: usize,
    grid: Grid,
}

impl Cpu {
    pub fn new(sc: &Scenario, threads: usize) -> Self {
        let n = sc.parts.len();
        let ncells = sc.ncx * sc.layers;
        // The erased state's moment: p m+ + (1 - p) m- at zero field is (2p - 1) n.
        let m = (0..n)
            .map(|i| {
                let s = 2.0 * sc.p0[i] - 1.0;
                let nn = sc.parts[i].n;
                [s * nn[0], s * nn[1], s * nn[2]]
            })
            .collect();
        Cpu {
            p: sc.p0.clone(),
            m,
            fx: vec![0.0; ncells],
            fy: vec![0.0; ncells],
            threads: threads.max(1),
            grid: Grid::new(sc.grid),
        }
    }

    fn par<F>(&mut self, lo: usize, hi: usize, f: F)
    where
        F: Fn(usize, &mut f64, &mut [f64; 3]) + Sync,
    {
        if hi <= lo {
            return;
        }
        let chunk = (hi - lo).div_ceil(self.threads).max(256);
        let ps = &mut self.p[lo..hi];
        let ms = &mut self.m[lo..hi];
        std::thread::scope(|s| {
            for (ci, (pc, mc)) in ps.chunks_mut(chunk).zip(ms.chunks_mut(chunk)).enumerate() {
                let f = &f;
                s.spawn(move || {
                    for (k, (p, m)) in pc.iter_mut().zip(mc.iter_mut()).enumerate() {
                        f(lo + ci * chunk + k, p, m);
                    }
                });
            }
        });
    }
}

impl Backend for Cpu {
    fn advance(&mut self, sc: &Scenario, j0: usize, j1: usize, lo: usize, hi: usize) {
        let zones: Vec<(usize, usize)> = (j0..j1).map(|j| sc.zone(j)).collect();
        let (fx, fy) = (std::mem::take(&mut self.fx), std::mem::take(&mut self.fy));
        let grid = std::mem::replace(&mut self.grid, Grid::new(2));
        self.par(lo, hi, |i, p, m| {
            let c = sc.cell[i] as usize;
            for (k, j) in (j0..j1).enumerate() {
                if i < zones[k].0 || i >= zones[k].1 {
                    continue;
                }
                let (hx, hy) = head::field(&sc.head, sc.x[i] - sc.step_x[j], sc.y[i]);
                let hg = sc.step_hg[j];
                let h = [hg * hx + fx[c], hg * hy + fy[c], 0.0];
                let u = sc
                    .stochastic
                    .then(|| sw::hash_uniform(sc.seed, i as u32, j as u32));
                let o = sw::step(&sc.parts[i], h, *p, sc.dt, sc.f0, &grid, sc.iters, u);
                *p = o.p;
                *m = o.m;
            }
        });
        self.fx = fx;
        self.fy = fy;
        self.grid = grid;
    }

    fn relax(&mut self, sc: &Scenario, r: usize) {
        let (fx, fy) = (std::mem::take(&mut self.fx), std::mem::take(&mut self.fy));
        let grid = std::mem::replace(&mut self.grid, Grid::new(2));
        let j = (sc.steps() + r) as u32;
        let n = sc.parts.len();
        self.par(0, n, |i, p, m| {
            let c = sc.cell[i] as usize;
            let u = sc
                .stochastic
                .then(|| sw::hash_uniform(sc.seed, i as u32, j));
            let o = sw::step(
                &sc.parts[i],
                [fx[c], fy[c], 0.0],
                *p,
                sc.relax_dt,
                sc.f0,
                &grid,
                sc.iters,
                u,
            );
            *p = o.p;
            *m = o.m;
        });
        self.fx = fx;
        self.fy = fy;
        self.grid = grid;
    }

    fn deposit(&mut self, sc: &Scenario, c_lo: usize, c_hi: usize) -> (Vec<f64>, Vec<f64>) {
        let mut dx = vec![0.0; c_hi - c_lo];
        let mut dy = vec![0.0; c_hi - c_lo];
        for c in c_lo..c_hi {
            for i in sc.cell_start[c]..sc.cell_start[c + 1] {
                dx[c - c_lo] += sc.v[i] * self.m[i][0];
                dy[c - c_lo] += sc.v[i] * self.m[i][1];
            }
        }
        (dx, dy)
    }

    fn set_field(&mut self, c_lo: usize, fx: &[f64], fy: &[f64]) {
        self.fx[c_lo..c_lo + fx.len()].copy_from_slice(fx);
        self.fy[c_lo..c_lo + fy.len()].copy_from_slice(fy);
    }

    fn finish(&mut self) -> (Vec<f64>, Vec<[f64; 3]>) {
        (self.p.clone(), self.m.clone())
    }
}

/// Uniform fields along x (the B-H meter): `happ` is steps x reps (row major); every
/// particle runs each history from p0. Returns per history the final sum v m_x / sum v
/// and, if `trace`, the same after every step (steps x reps).
#[allow(clippy::too_many_arguments)]
pub fn uniform(
    parts: &[Particle],
    v: &[f64],
    p0: &[f64],
    happ: &[f64],
    reps: usize,
    dt: f64,
    f0: f64,
    grid: usize,
    iters: usize,
    threads: usize,
    trace: bool,
) -> (Vec<f64>, Vec<f64>) {
    let steps = happ.len() / reps;
    let n = parts.len();
    let vsum: f64 = v.iter().sum();
    let threads = threads.max(1);
    let chunk = n.div_ceil(threads).max(64);
    let results: Vec<(Vec<f64>, Vec<f64>)> = std::thread::scope(|s| {
        let hs: Vec<_> = (0..n)
            .step_by(chunk)
            .map(|lo| {
                let hi = (lo + chunk).min(n);
                s.spawn(move || {
                    let g = Grid::new(grid);
                    let mut fin = vec![0.0; reps];
                    let mut tr = vec![0.0; if trace { steps * reps } else { 0 }];
                    for r in 0..reps {
                        for i in lo..hi {
                            let mut p = p0[i];
                            let mut mx = 0.0;
                            for j in 0..steps {
                                let o = sw::step(
                                    &parts[i],
                                    [happ[j * reps + r], 0.0, 0.0],
                                    p,
                                    dt,
                                    f0,
                                    &g,
                                    iters,
                                    None,
                                );
                                p = o.p;
                                mx = o.m[0];
                                if trace {
                                    tr[j * reps + r] += v[i] * mx;
                                }
                            }
                            fin[r] += v[i] * mx;
                        }
                    }
                    (fin, tr)
                })
            })
            .collect();
        hs.into_iter().map(|h| h.join().unwrap()).collect()
    });
    let mut fin = vec![0.0; reps];
    let mut tr = vec![0.0; if trace { steps * reps } else { 0 }];
    for (f, t) in results {
        for r in 0..reps {
            fin[r] += f[r] / vsum;
        }
        for k in 0..tr.len() {
            tr[k] += t[k] / vsum;
        }
    }
    (fin, tr)
}
