//! A body in free field (docs/BINAURAL_PLAN.md): the wave solver's scheme (the parent
//! module's docstring) on a grid that is all air but a rigid body (a head and torso), with an
//! absorbing sponge layer at the grid's faces instead of walls, and pressure-only receivers.
//! Used by `varimu.binaural` reciprocally: the source at an ear's blocked canal, the
//! receivers on a sphere round the body, from which the far field (the HRTF in every
//! direction) is extrapolated.
//!
//! **Cells.** `codes[i]` = 0 a solid cell (never written: it holds 0), else K in 1..=6, the
//! number of its six neighbours that are air: one byte per cell (the GPU reads them four to
//! a word, little-endian), so a grid costs 9 bytes a cell with its two time levels. With the solid neighbours holding 0, the
//! finite-volume update of the parent module with beta = 0 on the solid links is a rigid
//! (Neumann) boundary:
//!
//!   (1 + g) p^{n+1} = (2 - lambda^2 K) p^n + lambda^2 sum_j p_j^n - (1 - g) p^{n-1}
//!
//! where g is the sponge's damping, computed from the cell's position (no storage): with d
//! the cell's depth into the layer of `sponge` cells along the grid's faces (d = sponge - the
//! distance to the nearest face, in cells, when positive), g = g_max (d / sponge)^2. g = (sigma
//! T) / 2 of a damped wave equation p_tt + sigma p_t = c^2 lap p; the graded profile keeps the
//! layer's reflection small. The grid's outermost cells must be solid (the caller's job,
//! `check`): the update reads all six neighbours unguarded.
//!
//! **Source and receivers.** As the parent's: `inject` is p^1 (p^0 = 0). Each step every
//! receiver records the pressure, trilinear at fractional grid coordinates. Record n is p^n
//! (record 0 = 0).

use bytemuck::{Pod, Zeroable};

use crate::gpu::Gpu;

#[derive(Clone, Debug)]
pub struct BodyGrid {
    pub nx: usize,
    pub ny: usize,
    pub nz: usize,
    /// Per cell (x fastest): 0 solid, else the number of air neighbours (1..=6).
    pub codes: Vec<u8>,
    pub lambda: f64,
    /// The sponge layer's thickness in cells.
    pub sponge: u32,
    pub g_max: f64,
}

#[derive(Clone, Debug)]
pub struct BodyRun {
    /// (cell, value): p^1.
    pub inject: Vec<(u32, f64)>,
    /// Receiver positions in grid coordinates (cells, fractional).
    pub mics: Vec<[f64; 3]>,
    pub n_steps: usize,
}

impl BodyGrid {
    pub fn n(&self) -> usize {
        self.nx * self.ny * self.nz
    }

    pub fn check(&self, run: &BodyRun) -> Result<(), String> {
        let n = self.n();
        if self.codes.len() != n {
            return Err(format!("codes: {} cells, the grid has {n}", self.codes.len()));
        }
        if !(self.lambda > 0.0 && self.lambda <= 1.0 / 3f64.sqrt() + 1e-12) {
            return Err(format!("lambda {}: in (0, 1 / sqrt 3]", self.lambda));
        }
        if !(self.g_max >= 0.0) {
            return Err("g_max >= 0".into());
        }
        if self.codes.iter().any(|&c| c > 6) {
            return Err("a code above 6".into());
        }
        // the outermost layer solid
        let (nx, ny, nz) = (self.nx, self.ny, self.nz);
        for k in 0..nz {
            for j in 0..ny {
                for i in 0..nx {
                    let edge = i == 0 || j == 0 || k == 0 || i == nx - 1 || j == ny - 1 || k == nz - 1;
                    if edge && self.codes[i + nx * (j + ny * k)] != 0 {
                        return Err("the grid's outermost cells must be solid".into());
                    }
                }
            }
        }
        if run.inject.iter().any(|(i, _)| *i as usize >= n) {
            return Err("an injected cell outside the grid".into());
        }
        let dims = [nx, ny, nz];
        for m in &run.mics {
            for a in 0..3 {
                if !(m[a] >= 1.0 && m[a] <= dims[a] as f64 - 2.0) {
                    return Err(format!("a receiver at {m:?}: 1 cell inside the grid"));
                }
            }
        }
        Ok(())
    }

    /// The sponge's g at cell (i, j, k).
    pub fn sponge_g(&self, i: usize, j: usize, k: usize) -> f64 {
        let w = self.sponge as i64;
        if w == 0 {
            return 0.0;
        }
        let near = [
            i as i64,
            j as i64,
            k as i64,
            self.nx as i64 - 1 - i as i64,
            self.ny as i64 - 1 - j as i64,
            self.nz as i64 - 1 - k as i64,
        ]
        .into_iter()
        .min()
        .unwrap();
        let d = w - near;
        if d <= 0 {
            0.0
        } else {
            let x = d as f64 / w as f64;
            self.g_max * x * x
        }
    }
}

fn trilinear(p: &[f64], g: &BodyGrid, m: [f64; 3]) -> f64 {
    let [x, y, z] = m;
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

/// The f64 reference (single-threaded per step over slabs, as the parent's): records
/// (n_steps x mics), flat.
pub fn run_cpu(grid: &BodyGrid, run: &BodyRun) -> Result<Vec<f64>, String> {
    grid.check(run)?;
    let n = grid.n();
    let (nx, nxy) = (grid.nx, grid.nx * grid.ny);
    let l2 = grid.lambda * grid.lambda;
    let gvals: Vec<f64> = (0..n)
        .map(|i| grid.sponge_g(i % nx, (i / nx) % grid.ny, i / nxy))
        .collect();
    let mut a = vec![0.0f64; n];
    let mut b = vec![0.0f64; n];
    for &(i, v) in &run.inject {
        b[i as usize] += v;
    }
    let nm = run.mics.len();
    let mut out = vec![0.0; run.n_steps * nm];
    if run.n_steps > 1 {
        for (mi, m) in run.mics.iter().enumerate() {
            out[nm + mi] = trilinear(&b, grid, *m);
        }
    }
    for step in 2..run.n_steps {
        // p^step from cur = p^{step-1} into dst, which holds p^{step-2}
        let (cur, dst) = if step % 2 == 0 { (&b, &mut a) } else { (&a, &mut b) };
        for i in 0..n {
            let k = grid.codes[i];
            if k == 0 {
                continue;
            }
            let nsum = cur[i - 1] + cur[i + 1] + cur[i - nx] + cur[i + nx] + cur[i - nxy] + cur[i + nxy];
            let g = gvals[i];
            dst[i] = ((2.0 - l2 * k as f64) * cur[i] + l2 * nsum - (1.0 - g) * dst[i]) / (1.0 + g);
        }
        let level: &[f64] = if step % 2 == 0 { &a } else { &b };
        for (mi, m) in run.mics.iter().enumerate() {
            out[step * nm + mi] = trilinear(level, grid, *m);
        }
    }
    Ok(out)
}

#[repr(C)]
#[derive(Clone, Copy, Pod, Zeroable)]
struct UpdateParams {
    nx: u32,
    ny: u32,
    nz: u32,
    nxy: u32,
    n: u32,
    row: u32,
    sponge: u32,
    _pad0: u32,
    l2: f32,
    g_max: f32,
    _pad1: [u32; 2],
}

#[repr(C)]
#[derive(Clone, Copy, Pod, Zeroable)]
struct ReadParams {
    nx: u32,
    nxy: u32,
    n_mics: u32,
    _pad: u32,
}

const UPDATE_WGSL: &str = include_str!("../shaders/head_update.wgsl");
const READ_WGSL: &str = include_str!("../shaders/head_read.wgsl");
const BUMP_WGSL: &str = include_str!("../shaders/head_bump.wgsl");
const WG: usize = 256;
/// Cell updates per submission (the gpu module's TDR note).
const UPDATES_PER_SUBMIT: usize = 3_000_000_000;

/// The same on the GPU (f32 fields). `progress(step, n_steps)` after each submission.
pub fn run_gpu(
    gpu: &Gpu,
    grid: &BodyGrid,
    run: &BodyRun,
    progress: &mut dyn FnMut(usize, usize),
) -> Result<Vec<f32>, String> {
    grid.check(run)?;
    let n = grid.n();
    let nm = run.mics.len();
    let bytes = (n * 4) as u64;
    if bytes > gpu.limits.max_storage_buffer_binding_size {
        return Err(format!(
            "{n} cells: more than the GPU binds in one buffer ({} B)",
            gpu.limits.max_storage_buffer_binding_size
        ));
    }
    let mut p1 = vec![0.0f32; n];
    for &(i, v) in &run.inject {
        p1[i as usize] += v as f32;
    }
    let buf_a = gpu.zeros("p_a", bytes);
    let buf_b = gpu.storage("p_b", bytemuck::cast_slice(&p1));
    drop(p1);
    let mut packed = grid.codes.clone();
    packed.resize(n.next_multiple_of(4), 0);
    let codes = gpu.storage("codes", &packed);
    drop(packed);
    let groups = n.div_ceil(WG);
    let gx = groups.min(65_535);
    let gy = groups.div_ceil(gx);
    let up = UpdateParams {
        nx: grid.nx as u32,
        ny: grid.ny as u32,
        nz: grid.nz as u32,
        nxy: (grid.nx * grid.ny) as u32,
        n: n as u32,
        row: (gx * WG) as u32,
        sponge: grid.sponge,
        _pad0: 0,
        l2: (grid.lambda * grid.lambda) as f32,
        g_max: grid.g_max as f32,
        _pad1: [0; 2],
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
    let out_bytes = (run.n_steps.max(1) * nm.max(1) * 4) as u64;
    if out_bytes > gpu.limits.max_storage_buffer_binding_size {
        return Err(format!("records: {out_bytes} B, more than the GPU binds"));
    }
    let b_out = gpu.zeros("records", out_bytes);
    let b_ctr = gpu.storage("counter", bytemuck::cast_slice(&[1u32, 0, 0, 0]));
    let upd = gpu.pipeline("head_update", UPDATE_WGSL, "main");
    let rd = gpu.pipeline("head_read", READ_WGSL, "main");
    let bump = gpu.pipeline("head_bump", BUMP_WGSL, "main");
    let g_up = [
        gpu.bind(&upd, &[&b_up, &codes, &buf_b, &buf_a]),
        gpu.bind(&upd, &[&b_up, &codes, &buf_a, &buf_b]),
    ];
    let g_rd = [
        gpu.bind(&rd, &[&b_rp, &b_mics, &buf_a, &b_out, &b_ctr]),
        gpu.bind(&rd, &[&b_rp, &b_mics, &buf_b, &b_out, &b_ctr]),
    ];
    let g_bump = gpu.bind(&bump, &[&b_ctr]);
    let rd_groups = nm.div_ceil(64).max(1) as u32;
    let per_submit = (UPDATES_PER_SUBMIT / n.max(1)).clamp(1, 2000);
    let mut enc = gpu
        .device
        .create_command_encoder(&wgpu::CommandEncoderDescriptor { label: None });
    if run.n_steps > 1 && nm > 0 {
        let mut pass = enc.begin_compute_pass(&Default::default());
        pass.set_pipeline(&rd);
        pass.set_bind_group(0, &g_rd[1], &[]); // p^1 in B
        pass.dispatch_workgroups(rd_groups, 1, 1);
        pass.set_pipeline(&bump);
        pass.set_bind_group(0, &g_bump, &[]);
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
                    pass.dispatch_workgroups(rd_groups, 1, 1);
                    pass.set_pipeline(&bump);
                    pass.set_bind_group(0, &g_bump, &[]);
                    pass.dispatch_workgroups(1, 1, 1);
                }
            }
        }
        gpu.queue.submit([enc.finish()]);
        gpu.device
            .poll(wgpu::PollType::wait_indefinitely())
            .map_err(|e| format!("GPU: {e}"))?;
        step += k;
        progress(step + 2, run.n_steps);
    }
    if nm == 0 {
        return Ok(Vec::new());
    }
    let raw = gpu.read(&b_out, out_bytes)?;
    let v: &[f32] = bytemuck::cast_slice(&raw);
    Ok(v[..run.n_steps * nm].to_vec())
}

#[cfg(feature = "python")]
pub mod python {
    use numpy::{IntoPyArray, PyReadonlyArray1};
    use pyo3::exceptions::{PyRuntimeError, PyValueError};
    use pyo3::prelude::*;

    use super::{BodyGrid, BodyRun};

    /// One run (the module docstring). dims: (nx, ny, nz); codes: cells (uint8, 0 solid,
    /// else the air neighbours); inject_idx (uint32), inject_val; mics: M x 3 grid
    /// coordinates, flat. Returns the records, n_steps x M, flat (float32 from the GPU,
    /// float64 from the CPU reference). `progress(step, n_steps)` is called now and then.
    #[pyfunction]
    #[pyo3(signature = (dims, codes, lam, sponge, g_max, inject_idx, inject_val, mics,
                        n_steps, backend="gpu", progress=None))]
    #[allow(clippy::too_many_arguments)]
    fn body_run<'py>(
        py: Python<'py>,
        dims: (usize, usize, usize),
        codes: PyReadonlyArray1<u8>,
        lam: f64,
        sponge: u32,
        g_max: f64,
        inject_idx: PyReadonlyArray1<u32>,
        inject_val: PyReadonlyArray1<f64>,
        mics: PyReadonlyArray1<f64>,
        n_steps: usize,
        backend: &str,
        progress: Option<Py<PyAny>>,
    ) -> PyResult<Bound<'py, PyAny>> {
        let grid = BodyGrid {
            nx: dims.0,
            ny: dims.1,
            nz: dims.2,
            codes: codes.as_slice()?.to_vec(),
            lambda: lam,
            sponge,
            g_max,
        };
        let run = BodyRun {
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
        match backend {
            "gpu" => {
                let out = py
                    .detach(|| {
                        let gpu = crate::gpu::gpu()?;
                        let mut last = std::time::Instant::now();
                        let mut cb = |s: usize, t: usize| {
                            if let Some(p) = &progress {
                                if last.elapsed().as_secs_f64() > 2.0 {
                                    last = std::time::Instant::now();
                                    Python::attach(|py| {
                                        let _ = p.call1(py, (s, t));
                                    });
                                }
                            }
                        };
                        super::run_gpu(gpu, &grid, &run, &mut cb)
                    })
                    .map_err(PyRuntimeError::new_err)?;
                Ok(out.into_pyarray(py).into_any())
            }
            "cpu" => {
                let out = py
                    .detach(|| super::run_cpu(&grid, &run))
                    .map_err(PyRuntimeError::new_err)?;
                Ok(out.into_pyarray(py).into_any())
            }
            b => Err(PyValueError::new_err(format!("backend {b:?}: gpu or cpu"))),
        }
    }

    pub fn register(m: &Bound<'_, PyModule>) -> PyResult<()> {
        m.add_function(wrap_pyfunction!(body_run, m)?)?;
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    /// An all-air cube of side m + 2 (the solid shell), optionally with a solid sphere.
    fn cube(m: usize, sphere_r: f64, sponge: u32, g_max: f64) -> BodyGrid {
        let s = m + 2;
        let c = (s as f64 - 1.0) / 2.0;
        let solid = |i: usize, j: usize, k: usize| {
            let edge = i == 0 || j == 0 || k == 0 || i == s - 1 || j == s - 1 || k == s - 1;
            let (x, y, z) = (i as f64 - c, j as f64 - c, k as f64 - c);
            edge || (x * x + y * y + z * z).sqrt() < sphere_r
        };
        let mut codes = vec![0u8; s * s * s];
        for k in 0..s {
            for j in 0..s {
                for i in 0..s {
                    if solid(i, j, k) {
                        continue;
                    }
                    let nb = [
                        (i - 1, j, k),
                        (i + 1, j, k),
                        (i, j - 1, k),
                        (i, j + 1, k),
                        (i, j, k - 1),
                        (i, j, k + 1),
                    ];
                    codes[i + s * (j + s * k)] =
                        nb.iter().filter(|(a, b, c)| !solid(*a, *b, *c)).count() as u8;
                }
            }
        }
        BodyGrid {
            nx: s,
            ny: s,
            nz: s,
            codes,
            lambda: 1.0 / 3f64.sqrt(),
            sponge,
            g_max,
        }
    }

    #[test]
    fn the_sponge_absorbs() {
        // a pulse in a 40-cell box: rigid walls keep it, a sponge removes it
        let late = |sponge: u32, g: f64| {
            let grid = cube(40, 0.0, sponge, g);
            let c = 21;
            let run = BodyRun {
                inject: vec![((c + 42 * (c + 42 * c)) as u32, 1.0)],
                mics: vec![[25.3, 18.7, 21.1]],
                n_steps: 1500,
            };
            let r = run_cpu(&grid, &run).unwrap();
            r[800..].iter().map(|v| v * v).sum::<f64>() / r[..200].iter().map(|v| v * v).sum::<f64>()
        };
        let rigid = late(0, 0.0);
        let damped = late(12, 0.3);
        eprintln!("late / early energy: rigid {rigid:.3e}, sponge {damped:.3e}");
        assert!(damped < 1e-3 * rigid);
    }

    #[test]
    fn gpu_matches_the_cpu() {
        let Ok(gpu) = crate::gpu::gpu() else {
            eprintln!("no GPU: skipped");
            return;
        };
        let grid = cube(46, 7.0, 10, 0.25);
        let c = 24usize;
        let src = c + 12 + 48 * (c + 48 * c); // beside the sphere
        let run = BodyRun {
            inject: vec![(src as u32, 0.7), (src as u32 + 1, 0.3)],
            mics: vec![[12.3, 20.6, 24.1], [36.5, 30.2, 14.9], [24.0, 24.0, 38.2]],
            n_steps: 600,
        };
        let c64 = run_cpu(&grid, &run).unwrap();
        let g32 = run_gpu(gpu, &grid, &run, &mut |_, _| {}).unwrap();
        let (mut num, mut den) = (0.0, 0.0);
        for (x, y) in c64.iter().zip(&g32) {
            num += (x - f64::from(*y)).powi(2);
            den += x * x;
        }
        let db = 10.0 * (num / den).log10();
        eprintln!("GPU vs CPU {db:.1} dB");
        assert!(db < -90.0, "GPU vs CPU {db:.1} dB");
    }
}
