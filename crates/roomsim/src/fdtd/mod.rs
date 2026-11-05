//! The wave solver (ROOM_LOOP_PLAN.md R10): the room's sound field below a crossover by
//! finite differences in time and space, on the GPU (`fdtd_update.wgsl`, `fdtd_read.wgsl`,
//! f32) with an f64 CPU reference here.
//!
//! **The scheme.** The standard rectilinear scheme (7 points) for the wave equation on a
//! cubic grid of spacing X, step T, Courant number lambda = c T / X <= 1 / sqrt(3), read as
//! a finite-volume scheme so that walls of any shape (cells staircased by the voxelization,
//! `varimu.rooms.wave`) are energy-stable (Bilbao, "Modeling of complex geometries and
//! boundary conditions in finite difference / finite volume time domain room acoustics
//! simulation", IEEE TASLP 21(7), 2013). Cell i with K_i neighbours in the room and its
//! other 6 - K_i links on walls of locally reacting, real normalized admittance beta:
//!
//!   (1 + g_i) p_i^{n+1} = (2 - lambda^2 K_i) p_i^n + lambda^2 sum_j p_j^n - (1 - g_i) p_i^{n-1}
//!
//! with g_i = (lambda / 2) sum over its wall links of beta (the caller corrects beta for the
//! staircase's extra area). Cells outside the room hold 0, so the sum runs over all six
//! neighbours. Interior cells (K = 6, g = 0) are `codes` 1, wall cells 2 + their index in
//! `bnd`, outside cells 0.
//!
//! **Source and mics.** A unit impulse (a Dirac of unit area: free-field pressure 1 / r at
//! r) is the initial field p^1 at the cells `inject` names (p^0 = 0); the caller spreads it
//! over the 8 cells round the source with weights 4 pi lambda^2 / (X T) w. Each step every
//! mic records the pressure (trilinear) and its gradient (central differences of trilinear
//! values one cell apart, per cell), at fractional grid coordinates: (p, dp/dx, dp/dy,
//! dp/dz). Record n is p^n (record 0 = 0).

use bytemuck::{Pod, Zeroable};

use crate::gpu::Gpu;

/// The voxelized room for one run (one band's admittances).
#[derive(Clone, Debug)]
pub struct Grid {
    pub nx: usize,
    pub ny: usize,
    pub nz: usize,
    /// Per cell (x fastest): 0 outside, 1 interior, 2 + i a wall cell with bnd_k[i], bnd_g[i].
    pub codes: Vec<u32>,
    pub bnd_k: Vec<f64>,
    pub bnd_g: Vec<f64>,
    pub lambda: f64,
}

/// What to inject and record.
#[derive(Clone, Debug)]
pub struct Run {
    /// (cell, value): p^1.
    pub inject: Vec<(u32, f64)>,
    /// Mic positions in grid coordinates (cells, fractional).
    pub mics: Vec<[f64; 3]>,
    pub n_steps: usize,
}

impl Grid {
    pub fn n(&self) -> usize {
        self.nx * self.ny * self.nz
    }

    pub fn check(&self, run: &Run) -> Result<(), String> {
        if self.codes.len() != self.n() {
            return Err(format!(
                "codes: {} cells, the grid has {}",
                self.codes.len(),
                self.n()
            ));
        }
        if self.bnd_k.len() != self.bnd_g.len() {
            return Err("bnd_k and bnd_g per wall cell".into());
        }
        let nb = self.bnd_k.len() as u32;
        if self.codes.iter().any(|&c| c >= 2 && c - 2 >= nb) {
            return Err("a wall cell's index out of range".into());
        }
        if !(self.lambda > 0.0 && self.lambda <= 1.0 / 3f64.sqrt() + 1e-12) {
            return Err(format!("lambda {}: in (0, 1 / sqrt 3]", self.lambda));
        }
        if self.bnd_g.iter().any(|g| *g < 0.0) {
            return Err("admittances >= 0 (passive walls)".into());
        }
        if run.inject.iter().any(|(i, _)| *i as usize >= self.n()) {
            return Err("an injected cell outside the grid".into());
        }
        for m in &run.mics {
            let dims = [self.nx, self.ny, self.nz];
            for a in 0..3 {
                if !(m[a] >= 2.0 && m[a] <= dims[a] as f64 - 3.0) {
                    return Err(format!("a mic at {m:?}: 2 cells inside the grid"));
                }
            }
        }
        Ok(())
    }
}

/// Trilinear interpolation of a field at fractional grid coordinates.
fn trilinear(p: &[f64], g: &Grid, x: f64, y: f64, z: f64) -> f64 {
    let (x0, y0, z0) = (x.floor(), y.floor(), z.floor());
    let (fx, fy, fz) = (x - x0, y - y0, z - z0);
    let (i, j, k) = (x0 as usize, y0 as usize, z0 as usize);
    let at = |a: usize, b: usize, c: usize| p[a + g.nx * (b + g.ny * c)];
    let mut v = 0.0;
    for (dk, wz) in [(0, 1.0 - fz), (1, fz)] {
        for (dj, wy) in [(0, 1.0 - fy), (1, fy)] {
            for (di, wx) in [(0, 1.0 - fx), (1, fx)] {
                v += wx * wy * wz * at(i + di, j + dj, k + dk);
            }
        }
    }
    v
}

fn record(p: &[f64], g: &Grid, m: [f64; 3]) -> [f64; 4] {
    let t = |x: f64, y: f64, z: f64| trilinear(p, g, x, y, z);
    let [x, y, z] = m;
    [
        t(x, y, z),
        0.5 * (t(x + 1.0, y, z) - t(x - 1.0, y, z)),
        0.5 * (t(x, y + 1.0, z) - t(x, y - 1.0, z)),
        0.5 * (t(x, y, z + 1.0) - t(x, y, z - 1.0)),
    ]
}

/// The f64 reference: records (n_steps x mics x 4), flat.
pub fn run_cpu(grid: &Grid, run: &Run) -> Result<Vec<f64>, String> {
    grid.check(run)?;
    let n = grid.n();
    let (nx, nxy) = (grid.nx, grid.nx * grid.ny);
    let l2 = grid.lambda * grid.lambda;
    let mut prev = vec![0.0f64; n]; // p^{n-1}, overwritten with p^{n+1}
    let mut cur = vec![0.0f64; n];
    for &(i, v) in &run.inject {
        cur[i as usize] += v;
    }
    let nm = run.mics.len();
    let mut out = vec![0.0; run.n_steps * nm * 4];
    for (mi, m) in run.mics.iter().enumerate() {
        if run.n_steps > 1 {
            out[(nm + mi) * 4..(nm + mi) * 4 + 4].copy_from_slice(&record(&cur, grid, *m));
        }
    }
    let threads = std::thread::available_parallelism().map_or(4, |n| n.get());
    let slab = n.div_ceil(threads).max(1);
    for step in 2..run.n_steps {
        {
            let cur = &cur;
            std::thread::scope(|s| {
                for (ci, chunk) in prev.chunks_mut(slab).enumerate() {
                    s.spawn(move || {
                        let base = ci * slab;
                        for (o, pv) in chunk.iter_mut().enumerate() {
                            let i = base + o;
                            let code = grid.codes[i];
                            if code == 0 {
                                continue;
                            }
                            let nsum = cur[i - 1]
                                + cur[i + 1]
                                + cur[i - nx]
                                + cur[i + nx]
                                + cur[i - nxy]
                                + cur[i + nxy];
                            *pv = if code == 1 {
                                (2.0 - 6.0 * l2) * cur[i] + l2 * nsum - *pv
                            } else {
                                let b = (code - 2) as usize;
                                let (k, g) = (grid.bnd_k[b], grid.bnd_g[b]);
                                ((2.0 - l2 * k) * cur[i] + l2 * nsum - (1.0 - g) * *pv) / (1.0 + g)
                            };
                        }
                    });
                }
            });
        }
        std::mem::swap(&mut prev, &mut cur);
        for (mi, m) in run.mics.iter().enumerate() {
            let o = (step * nm + mi) * 4;
            out[o..o + 4].copy_from_slice(&record(&cur, grid, *m));
        }
    }
    Ok(out)
}

#[repr(C)]
#[derive(Clone, Copy, Pod, Zeroable)]
struct UpdateParams {
    nx: u32,
    nxy: u32,
    n: u32,
    row: u32, // threads per row of workgroups (the dispatch's x size times 256)
    l2: f32,
    _pad: [u32; 3],
}

#[repr(C)]
#[derive(Clone, Copy, Pod, Zeroable)]
struct ReadParams {
    nx: u32,
    nxy: u32,
    n_mics: u32,
    _pad: u32,
}

const UPDATE_WGSL: &str = include_str!("../shaders/fdtd_update.wgsl");
const READ_WGSL: &str = include_str!("../shaders/fdtd_read.wgsl");
const WG: usize = 256;
/// Cell updates per submission: ~0.1 s on a 3080 (the gpu module's TDR note).
const UPDATES_PER_SUBMIT: usize = 2_000_000_000;

/// The same on the GPU (f32 fields).
pub fn run_gpu(gpu: &Gpu, grid: &Grid, run: &Run) -> Result<Vec<f64>, String> {
    grid.check(run)?;
    let n = grid.n();
    let nm = run.mics.len();
    let mut p1 = vec![0.0f32; n];
    for &(i, v) in &run.inject {
        p1[i as usize] += v as f32;
    }
    let bytes = (n * 4) as u64;
    if bytes > gpu.limits.max_storage_buffer_binding_size {
        return Err(format!(
            "{n} cells: more than the GPU binds in one buffer ({} B)",
            gpu.limits.max_storage_buffer_binding_size
        ));
    }
    let buf_a = gpu.zeros("p_a", bytes); // p^0
    let buf_b = gpu.storage("p_b", bytemuck::cast_slice(&p1)); // p^1
    let codes = gpu.storage("codes", bytemuck::cast_slice(&grid.codes));
    let bnd: Vec<[f32; 2]> = grid
        .bnd_k
        .iter()
        .zip(&grid.bnd_g)
        .map(|(k, g)| [*k as f32, *g as f32])
        .collect();
    let b_bnd = gpu.storage("bnd", bytemuck::cast_slice(&bnd));
    let groups = n.div_ceil(WG);
    let gx = groups.min(65_535);
    let gy = groups.div_ceil(gx);
    let up = UpdateParams {
        nx: grid.nx as u32,
        nxy: (grid.nx * grid.ny) as u32,
        n: n as u32,
        row: (gx * WG) as u32,
        l2: (grid.lambda * grid.lambda) as f32,
        _pad: [0; 3],
    };
    let b_up = gpu.uniform("update", bytemuck::bytes_of(&up));
    let mics: Vec<[f32; 4]> = run
        .mics
        .iter()
        .map(|m| [m[0] as f32, m[1] as f32, m[2] as f32, 0.0])
        .collect();
    let b_mics = gpu.storage("mics", bytemuck::cast_slice(&mics));
    let rp = ReadParams {
        nx: grid.nx as u32,
        nxy: (grid.nx * grid.ny) as u32,
        n_mics: nm as u32,
        _pad: 0,
    };
    let b_rp = gpu.uniform("read", bytemuck::bytes_of(&rp));
    let out_bytes = (run.n_steps.max(1) * nm.max(1) * 16) as u64;
    let b_out = gpu.zeros("records", out_bytes);
    let b_ctr = gpu.storage("counter", bytemuck::cast_slice(&[1u32, 0, 0, 0]));
    let upd = gpu.pipeline("fdtd_update", UPDATE_WGSL, "main");
    let rd = gpu.pipeline("fdtd_read", READ_WGSL, "main");
    // even steps: cur B, next A; odd: cur A, next B
    let g_up = [
        gpu.bind(&upd, &[&b_up, &codes, &b_bnd, &buf_b, &buf_a]),
        gpu.bind(&upd, &[&b_up, &codes, &b_bnd, &buf_a, &buf_b]),
    ];
    let g_rd = [
        gpu.bind(&rd, &[&b_rp, &b_mics, &buf_a, &b_out, &b_ctr]),
        gpu.bind(&rd, &[&b_rp, &b_mics, &buf_b, &b_out, &b_ctr]),
    ];
    let per_submit = (UPDATES_PER_SUBMIT / n.max(1)).clamp(1, 2000);
    let mut enc = gpu
        .device
        .create_command_encoder(&wgpu::CommandEncoderDescriptor { label: None });
    if run.n_steps > 1 && nm > 0 {
        let mut pass = enc.begin_compute_pass(&Default::default());
        pass.set_pipeline(&rd);
        pass.set_bind_group(0, &g_rd[1], &[]); // p^1 in B
        pass.dispatch_workgroups(1, 1, 1);
    }
    gpu.queue.submit([enc.finish()]);
    let mut step = 0;
    let total = run.n_steps.saturating_sub(2);
    while step < total {
        let k = per_submit.min(total - step);
        let mut enc = gpu
            .device
            .create_command_encoder(&wgpu::CommandEncoderDescriptor { label: None });
        {
            let mut pass = enc.begin_compute_pass(&Default::default());
            for j in step..step + k {
                pass.set_pipeline(&upd);
                pass.set_bind_group(0, &g_up[j % 2], &[]);
                pass.dispatch_workgroups(gx as u32, gy as u32, 1);
                if nm > 0 {
                    pass.set_pipeline(&rd);
                    pass.set_bind_group(0, &g_rd[j % 2], &[]);
                    pass.dispatch_workgroups(1, 1, 1);
                }
            }
        }
        gpu.queue.submit([enc.finish()]);
        gpu.device
            .poll(wgpu::PollType::wait_indefinitely())
            .map_err(|e| format!("GPU: {e}"))?;
        step += k;
    }
    if nm == 0 {
        return Ok(Vec::new());
    }
    let raw = gpu.read(&b_out, out_bytes)?;
    let v: &[f32] = bytemuck::cast_slice(&raw);
    Ok(v[..run.n_steps * nm * 4]
        .iter()
        .map(|x| f64::from(*x))
        .collect())
}

#[cfg(feature = "python")]
pub mod python {
    use numpy::{IntoPyArray, PyReadonlyArray1};
    use pyo3::exceptions::{PyRuntimeError, PyValueError};
    use pyo3::prelude::*;

    use super::{Grid, Run};

    /// One run (the module docstring). dims: (nx, ny, nz); codes: cells (uint32); bnd_k,
    /// bnd_g: per wall cell; inject_idx (uint32), inject_val; mics: M x 3 grid coordinates.
    /// Returns the records, n_steps x M x 4, flat.
    #[pyfunction]
    #[pyo3(signature = (dims, codes, bnd_k, bnd_g, lam, inject_idx, inject_val, mics,
                        n_steps, backend="gpu"))]
    #[allow(clippy::too_many_arguments)]
    fn fdtd_run<'py>(
        py: Python<'py>,
        dims: (usize, usize, usize),
        codes: PyReadonlyArray1<u32>,
        bnd_k: PyReadonlyArray1<f64>,
        bnd_g: PyReadonlyArray1<f64>,
        lam: f64,
        inject_idx: PyReadonlyArray1<u32>,
        inject_val: PyReadonlyArray1<f64>,
        mics: PyReadonlyArray1<f64>,
        n_steps: usize,
        backend: &str,
    ) -> PyResult<Bound<'py, PyAny>> {
        let grid = Grid {
            nx: dims.0,
            ny: dims.1,
            nz: dims.2,
            codes: codes.as_slice()?.to_vec(),
            bnd_k: bnd_k.as_slice()?.to_vec(),
            bnd_g: bnd_g.as_slice()?.to_vec(),
            lambda: lam,
        };
        let run = Run {
            inject: inject_idx
                .as_slice()?
                .iter()
                .copied()
                .zip(inject_val.as_slice()?.iter().copied())
                .collect(),
            mics: mics
                .as_slice()?
                .chunks_exact(3)
                .map(|c| [c[0], c[1], c[2]])
                .collect(),
            n_steps,
        };
        let gpu_wanted = match backend {
            "gpu" => true,
            "cpu" => false,
            b => return Err(PyValueError::new_err(format!("backend {b:?}: gpu or cpu"))),
        };
        let out = py
            .detach(|| {
                if gpu_wanted {
                    super::run_gpu(crate::gpu::gpu()?, &grid, &run)
                } else {
                    super::run_cpu(&grid, &run)
                }
            })
            .map_err(PyRuntimeError::new_err)?;
        Ok(out.into_pyarray(py).into_any())
    }

    pub fn register(m: &Bound<'_, PyModule>) -> PyResult<()> {
        m.add_function(wrap_pyfunction!(fdtd_run, m)?)?;
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    /// A rigid or lossy box of nx x ny x nz interior cells inside one layer of outside.
    pub fn boxed(nx: usize, ny: usize, nz: usize, beta: f64) -> Grid {
        let (gx, gy, gz) = (nx + 2, ny + 2, nz + 2);
        let lambda = 1.0 / 3f64.sqrt();
        let mut codes = vec![0u32; gx * gy * gz];
        let (mut bk, mut bg) = (Vec::new(), Vec::new());
        for k in 1..=nz {
            for j in 1..=ny {
                for i in 1..=nx {
                    let walls = [i == 1, i == nx, j == 1, j == ny, k == 1, k == nz]
                        .iter()
                        .filter(|w| **w)
                        .count();
                    let c = i + gx * (j + gy * k);
                    if walls == 0 {
                        codes[c] = 1;
                    } else {
                        codes[c] = 2 + bk.len() as u32;
                        bk.push((6 - walls) as f64);
                        bg.push(0.5 * lambda * beta * walls as f64);
                    }
                }
            }
        }
        Grid {
            nx: gx,
            ny: gy,
            nz: gz,
            codes,
            bnd_k: bk,
            bnd_g: bg,
            lambda,
        }
    }

    fn energy(g: &Grid, p: &[f64]) -> f64 {
        p.iter()
            .zip(&g.codes)
            .filter(|(_, c)| **c > 0)
            .map(|(x, _)| x * x)
            .sum()
    }

    #[test]
    fn a_lossy_box_loses_energy_and_a_rigid_one_rings() {
        let run = |beta: f64| {
            let g = boxed(12, 10, 8, beta);
            let src = 4 + g.nx * (5 + g.ny * 4);
            let r = Run {
                inject: vec![(src as u32, 1.0)],
                mics: vec![[8.3, 6.6, 5.1]],
                n_steps: 4000,
            };
            run_cpu(&g, &r).unwrap()
        };
        // the sound, not the zero-frequency mode: first differences (the module docstring)
        let ac = |x: &[f64]| -> Vec<f64> {
            let p: Vec<f64> = x.chunks(4).map(|c| c[0]).collect();
            p.windows(2).map(|w| w[1] - w[0]).collect()
        };
        let rigid = ac(&run(0.0));
        let lossy = ac(&run(0.5));
        let late = |x: &[f64]| x[3000..].iter().map(|v| v * v).sum::<f64>();
        let early = |x: &[f64]| x[..1000].iter().map(|v| v * v).sum::<f64>();
        assert!(
            late(&rigid) > 0.3 * early(&rigid),
            "a rigid box keeps ringing"
        );
        assert!(late(&lossy) < 1e-6 * early(&lossy), "absorbing walls decay");
        let _ = energy;
    }

    #[test]
    fn gpu_matches_the_cpu() {
        let Ok(gpu) = crate::gpu::gpu() else {
            eprintln!("no GPU: skipped");
            return;
        };
        let g = boxed(30, 24, 18, 0.2);
        let src = 9 + g.nx * (8 + g.ny * 7);
        let r = Run {
            inject: vec![(src as u32, 0.6), (src as u32 + 1, 0.4)],
            mics: vec![[20.3, 15.6, 10.1], [5.5, 18.2, 12.9]],
            n_steps: 1500,
        };
        let c = run_cpu(&g, &r).unwrap();
        let gg = run_gpu(gpu, &g, &r).unwrap();
        // compared on first differences: the zero-frequency mode random-walks in f32 (the
        // module docstring; renders high-pass it away)
        let diff = |x: &[f64], ch: usize| -> Vec<f64> {
            let p: Vec<f64> = x.chunks(4).map(|c| c[ch]).collect();
            p.windows(2).map(|w| w[1] - w[0]).collect()
        };
        for ch in 0..4 {
            let (a, b) = (diff(&c, ch), diff(&gg, ch));
            let (mut num, mut den) = (0.0, 0.0);
            for (x, y) in a.iter().zip(&b) {
                num += (x - y) * (x - y);
                den += x * x;
            }
            let db = 10.0 * (num / den).log10();
            eprintln!("channel {ch}: GPU vs CPU {db:.1} dB");
            assert!(db < -80.0, "channel {ch}: GPU vs CPU {db:.1} dB");
        }
    }
}
