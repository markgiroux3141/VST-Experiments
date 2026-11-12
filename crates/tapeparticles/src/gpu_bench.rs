//! The bench on the GPU (`bench.wgsl`, f32): every replica at once, the steps encoded in
//! batches (field, step, tick per step) with no readback between them.

use bytemuck::{Pod, Zeroable};

use crate::bench::{Bench, Mode};
use crate::gpu::{Gpu, gpu};

#[repr(C)]
#[derive(Clone, Copy, Pod, Zeroable)]
struct Uniforms {
    n: u32,
    reps: u32,
    steps: u32,
    seed: u32,
    side: f32,
    a2: f32,
    ms_p: f32,
    scale: f32,
    f0: f32,
    dt: f32,
    mode: u32,
    grid: u32,
    iters: u32,
    vsum: f32,
    vol: f32,
    tp: u32,
    sd: [f32; 4],
}

const UM: f64 = 1e6;

fn v4(x: impl Iterator<Item = [f32; 4]>) -> Vec<u8> {
    let v: Vec<[f32; 4]> = x.collect();
    bytemuck::cast_slice(&v).to_vec()
}

/// (final p (reps x N), final M (reps x 3), trace (steps x reps x 3) if asked, the last
/// interaction field (reps x N x 3: from the final moments)): bench.rs's `run_cpu` in f32.
#[allow(clippy::type_complexity)]
pub fn run_gpu(
    b: &Bench,
    trace: bool,
) -> Result<(Vec<f64>, Vec<f64>, Vec<f64>, Vec<f64>), String> {
    let g: &Gpu = gpu()?;
    let n = b.n();
    let reps = b.reps;
    let steps = b.steps();
    let vsum: f64 = b.v.iter().map(|v| v * UM * UM * UM).sum();
    let un = Uniforms {
        n: n as u32,
        reps: reps as u32,
        steps: steps as u32,
        seed: b.seed,
        side: (b.side * UM) as f32,
        a2: (b.soften * UM * b.soften * UM) as f32,
        ms_p: b.ms_p as f32,
        scale: b.scale as f32,
        f0: b.f0 as f32,
        dt: b.dt as f32,
        mode: match b.mode {
            Mode::Dynamic => 0,
            Mode::Frozen => 1,
            Mode::None => 2,
            Mode::Mean => 3,
        },
        grid: b.grid as u32,
        iters: b.iters as u32,
        vsum: vsum as f32,
        vol: ((b.side * UM).powi(3)) as f32,
        tp: b.target_points as u32,
        sd: [
            b.sample_demag[0] as f32,
            b.sample_demag[1] as f32,
            b.sample_demag[2] as f32,
            0.0,
        ],
    };
    let ubuf = g.uniform("u", bytemuck::bytes_of(&un));
    let pos = g.storage(
        "pos",
        &v4((0..n).map(|i| {
            [
                (b.r[i][0] * UM) as f32,
                (b.r[i][1] * UM) as f32,
                (b.r[i][2] * UM) as f32,
                (b.l[i] * UM) as f32,
            ]
        })),
    );
    let axis = g.storage(
        "axis",
        &v4((0..n).map(|i| {
            let nn = b.parts[i].n;
            [nn[0] as f32, nn[1] as f32, nn[2] as f32, (b.v[i] * UM * UM * UM) as f32]
        })),
    );
    let prm = g.storage(
        "prm",
        &v4((0..n).map(|i| [b.parts[i].hk as f32, b.parts[i].e0_kt as f32, 0.0, 0.0])),
    );
    let st: Vec<f32> = (0..reps).flat_map(|_| b.p0.iter().map(|&p| p as f32)).collect();
    let state = g.storage("state", bytemuck::cast_slice(&st));
    let mom = g.storage(
        "mom",
        &v4((0..reps * n).map(|k| {
            let i = k % n;
            let s = (2.0 * b.p0[i] - 1.0) as f32;
            let nn = b.parts[i].n;
            [s * nn[0] as f32, s * nn[1] as f32, s * nn[2] as f32, 0.0]
        })),
    );
    let hint = g.zeros("hint", (reps * n * 16) as u64);
    let hfrozen = g.zeros("hfrozen", (reps * n * 16) as u64);
    let happ = g.storage(
        "happ",
        &v4((0..steps * reps).map(|k| {
            [
                b.h_app[3 * k] as f32,
                b.h_app[3 * k + 1] as f32,
                b.h_app[3 * k + 2] as f32,
                0.0,
            ]
        })),
    );
    let tr = g.zeros("trace", ((steps + 1) * reps * 16) as u64);
    let counter = g.zeros("counter", 16);
    let src = include_str!("bench.wgsl");
    let ro = [false, true, true, true, false, false, false, false, true, false, false];
    let entries: Vec<wgpu::BindGroupLayoutEntry> = (0..11)
        .map(|i| wgpu::BindGroupLayoutEntry {
            binding: i as u32,
            visibility: wgpu::ShaderStages::COMPUTE,
            ty: wgpu::BindingType::Buffer {
                ty: if i == 0 {
                    wgpu::BufferBindingType::Uniform
                } else {
                    wgpu::BufferBindingType::Storage { read_only: ro[i] }
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
            label: Some("bench"),
            entries: &entries,
        });
    let pl = g
        .device
        .create_pipeline_layout(&wgpu::PipelineLayoutDescriptor {
            label: Some("bench"),
            bind_group_layouts: &[Some(&bgl)],
            immediate_size: 0,
        });
    let module = g
        .device
        .create_shader_module(wgpu::ShaderModuleDescriptor {
            label: Some("bench"),
            source: wgpu::ShaderSource::Wgsl(src.into()),
        });
    let pipe = |entry: &str| {
        g.device
            .create_compute_pipeline(&wgpu::ComputePipelineDescriptor {
                label: Some(entry),
                layout: Some(&pl),
                module: &module,
                entry_point: Some(entry),
                compilation_options: Default::default(),
                cache: None,
            })
    };
    let (p_field, p_step, p_tick) = (pipe("field"), pipe("step"), pipe("tick"));
    let bufs = [
        &ubuf, &pos, &axis, &prm, &state, &mom, &hint, &hfrozen, &happ, &tr, &counter,
    ];
    let used: Vec<wgpu::BindGroupEntry> = bufs
        .iter()
        .enumerate()
        .map(|(i, buf)| wgpu::BindGroupEntry {
            binding: i as u32,
            resource: buf.as_entire_binding(),
        })
        .collect();
    let group = g.device.create_bind_group(&wgpu::BindGroupDescriptor {
        label: None,
        layout: &bgl,
        entries: &used,
    });
    let (g_field, g_step, g_tick) = (&group, &group, &group);
    let wg = ((n as u32).div_ceil(64), reps as u32, 1);
    // Batches short enough to stay well under Windows' ~2 s GPU timeout.
    let pairs = (n * n * reps) as f64;
    let batch = ((2e9 / pairs) as usize).clamp(1, 512);
    let mut j = 0;
    while j <= steps {
        let j1 = (j + batch).min(steps);
        let mut enc = g
            .device
            .create_command_encoder(&wgpu::CommandEncoderDescriptor { label: None });
        {
            let mut pass = enc.begin_compute_pass(&wgpu::ComputePassDescriptor {
                label: None,
                timestamp_writes: None,
            });
            for k in j..j1 {
                let _ = k;
                pass.set_pipeline(&p_field);
                pass.set_bind_group(0, g_field, &[]);
                pass.dispatch_workgroups(wg.0, wg.1, wg.2);
                pass.set_pipeline(&p_step);
                pass.set_bind_group(0, g_step, &[]);
                pass.dispatch_workgroups(wg.0, wg.1, wg.2);
                pass.set_pipeline(&p_tick);
                pass.set_bind_group(0, g_tick, &[]);
                pass.dispatch_workgroups(1, 1, 1);
            }
            if j1 == steps {
                // The final magnetization into the trace.
                pass.set_pipeline(&p_field);
                pass.set_bind_group(0, g_field, &[]);
                pass.dispatch_workgroups(wg.0, wg.1, wg.2);
            }
        }
        g.queue.submit([enc.finish()]);
        g.device
            .poll(wgpu::PollType::wait_indefinitely())
            .map_err(|e| format!("GPU: {e}"))?;
        if j1 == steps {
            break;
        }
        j = j1;
    }
    let pv: Vec<f32> = bytemuck::cast_slice(&g.read(&state, (reps * n * 4) as u64)?).to_vec();
    let tv: Vec<[f32; 4]> =
        bytemuck::cast_slice(&g.read(&tr, ((steps + 1) * reps * 16) as u64)?).to_vec();
    let mut fin = Vec::with_capacity(reps * 3);
    for r in 0..reps {
        let t = tv[steps * reps + r];
        fin.extend_from_slice(&[t[0] as f64, t[1] as f64, t[2] as f64]);
    }
    let mut trace_out = Vec::new();
    if trace {
        for k in 1..=steps {
            for r in 0..reps {
                let t = tv[k * reps + r];
                trace_out.extend_from_slice(&[t[0] as f64, t[1] as f64, t[2] as f64]);
            }
        }
    }
    let hv: Vec<[f32; 4]> = bytemuck::cast_slice(&g.read(&hint, (reps * n * 16) as u64)?).to_vec();
    let hint_out: Vec<f64> = hv
        .iter()
        .flat_map(|h| [h[0] as f64, h[1] as f64, h[2] as f64])
        .collect();
    Ok((pv.iter().map(|&x| x as f64).collect(), fin, trace_out, hint_out))
}
