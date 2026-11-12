//! The moving head on non-interacting particles, by cell (`head.wgsl`'s docstring; Python
//! `varimu/tape_particles/strip.py`): the f64 CPU reference and the f32 GPU run.

use std::path::Path;

use bytemuck::{Pod, Zeroable};

use crate::gpu::gpu;
use crate::io::{Meta, read_f64};
use crate::sw::{self, Grid, Particle};

pub struct Strip {
    pub parts: Vec<Particle>,
    pub v: Vec<f64>,
    pub p0: Vec<f64>,
    pub reps: usize,
    pub layers: usize,
    /// The pass's steps (then `e_steps` with the free field).
    pub s_steps: usize,
    pub e_steps: usize,
    /// s_steps x layers x (fx, fy).
    pub tab: Vec<f64>,
    /// reps x (phi_b0, phi_s0, hsx, hsy, hex, hey, sign).
    pub repc: Vec<f64>,
    pub a_sig: f64,
    pub bias: f64,
    pub fs_dt: f64,
    pub inv_m: f64,
    pub dt: f64,
    pub f0: f64,
    pub grid: usize,
    pub iters: usize,
    pub stochastic: bool,
    pub seed: u32,
}

impl Strip {
    pub fn read(dir: &Path) -> Result<Self, String> {
        let m = Meta::read(dir)?;
        let n = m.usize("n_particles")?;
        let reps = m.usize("reps")?;
        let layers = m.usize("layers")?;
        let s_steps = m.usize("s_steps")?;
        let nn = read_f64(dir, "n", 3 * n)?;
        let hk = read_f64(dir, "hk", n)?;
        let e0 = read_f64(dir, "e0_kt", n)?;
        Ok(Strip {
            parts: (0..n)
                .map(|i| Particle {
                    n: [nn[3 * i], nn[3 * i + 1], nn[3 * i + 2]],
                    hk: hk[i],
                    e0_kt: e0[i],
                    hloc: [0.0; 3],
                })
                .collect(),
            v: read_f64(dir, "v", n)?,
            p0: read_f64(dir, "p0", n)?,
            reps,
            layers,
            s_steps,
            e_steps: m.usize("e_steps")?,
            tab: read_f64(dir, "tab", s_steps * layers * 2)?,
            repc: read_f64(dir, "repc", reps * 7)?,
            a_sig: m.f64("a_sig")?,
            bias: m.f64("bias")?,
            fs_dt: m.f64("fs_dt")?,
            inv_m: m.f64("inv_m")?,
            dt: m.f64("dt")?,
            f0: m.f64("f0")?,
            grid: m.usize("grid")?,
            iters: m.usize("iters")?,
            stochastic: m.bool("stochastic")?,
            seed: m.usize("seed")? as u32,
        })
    }

    pub fn n(&self) -> usize {
        self.parts.len()
    }

    /// The applied field of replica r at step j.
    pub fn field(&self, r: usize, j: usize) -> [f64; 3] {
        let c = &self.repc[7 * r..7 * r + 7];
        if j >= self.s_steps {
            return [c[4], c[5], 0.0];
        }
        let l = r % self.layers;
        let fx = self.tab[2 * (j * self.layers + l)];
        let fy = self.tab[2 * (j * self.layers + l) + 1];
        let tau = std::f64::consts::TAU;
        let pb = (c[0] + j as f64 * self.inv_m).fract();
        let ps = (c[1] + j as f64 * self.fs_dt).fract();
        let hg = c[6] * self.a_sig * (tau * ps).sin() + self.bias * (tau * pb).sin();
        [hg * fx + c[2], hg * fy + c[3], 0.0]
    }
}

/// Final M per replica (reps x 3: sum v m / sum v), f64 on `threads`.
pub fn run_cpu(s: &Strip, threads: usize) -> Vec<f64> {
    let n = s.n();
    let steps = s.s_steps + s.e_steps;
    let vsum: f64 = s.v.iter().sum();
    let mut out = vec![0.0; 3 * s.reps];
    let chunk = s.reps.div_ceil(threads.max(1)).max(1);
    std::thread::scope(|sc| {
        for (ci, oc) in out.chunks_mut(3 * chunk).enumerate() {
            sc.spawn(move || {
                let g = Grid::new(s.grid);
                for (k, o) in oc.chunks_mut(3).enumerate() {
                    let r = ci * chunk + k;
                    let mut acc = [0.0; 3];
                    for i in 0..n {
                        let mut p = s.p0[i];
                        let mut m = [0.0; 3];
                        for j in 0..steps {
                            let u = s.stochastic.then(|| {
                                sw::hash_uniform(s.seed, (r * n + i) as u32, j as u32)
                            });
                            let st = sw::step(&s.parts[i], s.field(r, j), p, s.dt, s.f0, &g, s.iters, u);
                            p = st.p;
                            m = st.m;
                        }
                        for c in 0..3 {
                            acc[c] += s.v[i] * m[c] / vsum;
                        }
                    }
                    o.copy_from_slice(&acc);
                }
            });
        }
    });
    out
}

#[repr(C)]
#[derive(Clone, Copy, Pod, Zeroable)]
struct U {
    n: u32,
    reps: u32,
    layers: u32,
    s_steps: u32,
    j0: u32,
    j1: u32,
    seed: u32,
    grid: u32,
    iters: u32,
    stochastic: u32,
    f0: f32,
    dt: f32,
    a_sig: f32,
    bias: f32,
    fs_dt: f32,
    inv_m: f32,
    vsum: f32,
    pad0: u32,
    pad1: u32,
    pad2: u32,
}

fn v4(x: impl Iterator<Item = [f32; 4]>) -> Vec<u8> {
    let v: Vec<[f32; 4]> = x.collect();
    bytemuck::cast_slice(&v).to_vec()
}

/// `run_cpu` on the GPU (f32).
pub fn run_gpu(s: &Strip) -> Result<Vec<f64>, String> {
    let g = gpu()?;
    let n = s.n();
    let reps = s.reps;
    let steps = s.s_steps + s.e_steps;
    let vsum: f64 = s.v.iter().map(|v| v * 1e18).sum();
    let axis = g.storage(
        "axis",
        &v4((0..n).map(|i| {
            let nn = s.parts[i].n;
            [nn[0] as f32, nn[1] as f32, nn[2] as f32, (s.v[i] * 1e18) as f32]
        })),
    );
    let prm = g.storage(
        "prm",
        &v4((0..n).map(|i| [s.parts[i].hk as f32, s.parts[i].e0_kt as f32, 0.0, 0.0])),
    );
    let st: Vec<f32> = (0..reps).flat_map(|_| s.p0.iter().map(|&p| p as f32)).collect();
    let state = g.storage("state", bytemuck::cast_slice(&st));
    let mom = g.zeros("mom", (reps * n * 16) as u64);
    let tab = g.storage(
        "tab",
        &v4((0..s.s_steps * s.layers).map(|k| [s.tab[2 * k] as f32, s.tab[2 * k + 1] as f32, 0.0, 0.0])),
    );
    let repc = g.storage(
        "repc",
        &v4((0..reps).flat_map(|r| {
            let c = &s.repc[7 * r..7 * r + 7];
            // The phases' fractions in f64 (f32 holds them to ~1e-7 of a cycle).
            [
                [c[0].fract() as f32, c[1].fract() as f32, c[2] as f32, c[3] as f32],
                [c[4] as f32, c[5] as f32, c[6] as f32, 0.0],
            ]
        })),
    );
    let outm = g.zeros("outm", (reps * 16) as u64);
    let src = include_str!("head.wgsl");
    let entries: Vec<wgpu::BindGroupLayoutEntry> = (0..8)
        .map(|i| wgpu::BindGroupLayoutEntry {
            binding: i as u32,
            visibility: wgpu::ShaderStages::COMPUTE,
            ty: wgpu::BindingType::Buffer {
                ty: if i == 0 {
                    wgpu::BufferBindingType::Uniform
                } else {
                    wgpu::BufferBindingType::Storage {
                        read_only: matches!(i, 1 | 2 | 5 | 6),
                    }
                },
                has_dynamic_offset: false,
                min_binding_size: None,
            },
            count: None,
        })
        .collect();
    let bgl = g
        .device
        .create_bind_group_layout(&wgpu::BindGroupLayoutDescriptor {
            label: Some("head"),
            entries: &entries,
        });
    let pl = g
        .device
        .create_pipeline_layout(&wgpu::PipelineLayoutDescriptor {
            label: Some("head"),
            bind_group_layouts: &[Some(&bgl)],
            immediate_size: 0,
        });
    let module = g
        .device
        .create_shader_module(wgpu::ShaderModuleDescriptor {
            label: Some("head"),
            source: wgpu::ShaderSource::Wgsl(src.into()),
        });
    let pipe = |e: &str| {
        g.device
            .create_compute_pipeline(&wgpu::ComputePipelineDescriptor {
                label: Some(e),
                layout: Some(&pl),
                module: &module,
                entry_point: Some(e),
                compilation_options: Default::default(),
                cache: None,
            })
    };
    let (p_step, p_reduce) = (pipe("step_head"), pipe("reduce"));
    let mut un = U {
        n: n as u32,
        reps: reps as u32,
        layers: s.layers as u32,
        s_steps: s.s_steps as u32,
        j0: 0,
        j1: 0,
        seed: s.seed,
        grid: s.grid as u32,
        iters: s.iters as u32,
        stochastic: s.stochastic as u32,
        f0: s.f0 as f32,
        dt: s.dt as f32,
        a_sig: s.a_sig as f32,
        bias: s.bias as f32,
        fs_dt: s.fs_dt as f32,
        inv_m: s.inv_m as f32,
        vsum: vsum as f32,
        pad0: 0,
        pad1: 0,
        pad2: 0,
    };
    let ubuf = g.uniform("u", bytemuck::bytes_of(&un));
    let bufs = [&ubuf, &axis, &prm, &state, &mom, &tab, &repc, &outm];
    let ents: Vec<wgpu::BindGroupEntry> = bufs
        .iter()
        .enumerate()
        .map(|(i, b)| wgpu::BindGroupEntry {
            binding: i as u32,
            resource: b.as_entire_binding(),
        })
        .collect();
    let group = g.device.create_bind_group(&wgpu::BindGroupDescriptor {
        label: None,
        layout: &bgl,
        entries: &ents,
    });
    let wx = (n as u32).div_ceil(64);
    let (wy, wz) = if reps <= 65535 {
        (reps as u32, 1)
    } else {
        (65535, (reps as u32).div_ceil(65535))
    };
    // Steps per dispatch: ~2e8 particle-steps (well under Windows' GPU timeout).
    let per = ((2e8 / (n * reps) as f64) as usize).clamp(1, steps.max(1));
    let mut j = 0;
    while j < steps {
        let j1 = (j + per).min(steps);
        un.j0 = j as u32;
        un.j1 = j1 as u32;
        g.queue.write_buffer(&ubuf, 0, bytemuck::bytes_of(&un));
        g.run(&p_step, &group, (wx, wy, wz))?;
        j = j1;
    }
    g.run(&p_reduce, &group, ((reps as u32).div_ceil(64), 1, 1))?;
    let o: Vec<[f32; 4]> = bytemuck::cast_slice(&g.read(&outm, (reps * 16) as u64)?).to_vec();
    Ok(o.iter().flat_map(|x| [x[0] as f64, x[1] as f64, x[2] as f64]).collect())
}
