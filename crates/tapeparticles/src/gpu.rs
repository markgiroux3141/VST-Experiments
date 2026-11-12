//! The GPU: one wgpu device for the process, opened on first use, and the few helpers the
//! kernels share (storage buffers, a pipeline from WGSL, a dispatch that waits, readback).
//!
//! Backends are tried Vulkan, then DX12, then any; a software adapter is refused (the CPU
//! references are the fallback, chosen by the caller). `VARIMU_GPU=off` disables the GPU.
//! Dispatches are kept short (each a fraction of a second): Windows resets a GPU whose
//! dispatch runs past ~2 s (TDR), so the kernels split their work into batches.

use std::sync::OnceLock;

use wgpu::util::DeviceExt;

pub struct Gpu {
    pub device: wgpu::Device,
    pub queue: wgpu::Queue,
    pub info: wgpu::AdapterInfo,
    pub limits: wgpu::Limits,
}

static GPU: OnceLock<Result<Gpu, String>> = OnceLock::new();

/// The process's GPU, or why there is none.
pub fn gpu() -> Result<&'static Gpu, String> {
    GPU.get_or_init(open).as_ref().map_err(Clone::clone)
}

fn open() -> Result<Gpu, String> {
    if std::env::var("VARIMU_GPU").is_ok_and(|v| v == "off" || v == "0") {
        return Err("the GPU is off (VARIMU_GPU)".to_string());
    }
    let mut why = Vec::new();
    for backends in [
        wgpu::Backends::VULKAN,
        wgpu::Backends::DX12,
        wgpu::Backends::all(),
    ] {
        let mut desc = wgpu::InstanceDescriptor::new_without_display_handle();
        desc.backends = backends;
        let instance = wgpu::Instance::new(desc);
        let adapter =
            match pollster::block_on(instance.request_adapter(&wgpu::RequestAdapterOptions {
                power_preference: wgpu::PowerPreference::HighPerformance,
                force_fallback_adapter: false,
                compatible_surface: None,
            })) {
                Ok(a) => a,
                Err(e) => {
                    why.push(format!("{backends:?}: {e}"));
                    continue;
                }
            };
        let info = adapter.get_info();
        if info.device_type == wgpu::DeviceType::Cpu {
            why.push(format!(
                "{backends:?}: only a software adapter ({})",
                info.name
            ));
            continue;
        }
        let a = adapter.limits();
        let limits = wgpu::Limits {
            max_storage_buffer_binding_size: a.max_storage_buffer_binding_size,
            max_buffer_size: a.max_buffer_size,
            max_storage_buffers_per_shader_stage: a.max_storage_buffers_per_shader_stage,
            max_compute_workgroups_per_dimension: a.max_compute_workgroups_per_dimension,
            max_compute_invocations_per_workgroup: a.max_compute_invocations_per_workgroup,
            max_compute_workgroup_size_x: a.max_compute_workgroup_size_x,
            max_compute_workgroup_size_y: a.max_compute_workgroup_size_y,
            max_compute_workgroup_size_z: a.max_compute_workgroup_size_z,
            max_compute_workgroup_storage_size: a.max_compute_workgroup_storage_size,
            ..wgpu::Limits::default()
        };
        let desc = wgpu::DeviceDescriptor {
            label: Some("tapegpu"),
            required_limits: limits.clone(),
            memory_hints: wgpu::MemoryHints::Performance,
            ..Default::default()
        };
        match pollster::block_on(adapter.request_device(&desc)) {
            Ok((device, queue)) => {
                return Ok(Gpu {
                    device,
                    queue,
                    info,
                    limits,
                });
            }
            Err(e) => why.push(format!("{backends:?}: {e}")),
        }
    }
    Err(format!("no GPU: {}", why.join("; ")))
}

impl Gpu {
    /// "name (backend)".
    pub fn describe(&self) -> String {
        format!("{} ({:?})", self.info.name, self.info.backend)
    }

    /// A storage buffer holding `data` (at least 16 bytes: an empty array is padded).
    pub fn storage(&self, label: &str, data: &[u8]) -> wgpu::Buffer {
        let mut owned;
        let bytes = if data.len() < 16 {
            owned = data.to_vec();
            owned.resize(16, 0);
            &owned[..]
        } else {
            data
        };
        self.device
            .create_buffer_init(&wgpu::util::BufferInitDescriptor {
                label: Some(label),
                contents: bytes,
                usage: wgpu::BufferUsages::STORAGE
                    | wgpu::BufferUsages::COPY_SRC
                    | wgpu::BufferUsages::COPY_DST,
            })
    }

    /// A zeroed storage buffer of `size` bytes (at least 16).
    pub fn zeros(&self, label: &str, size: u64) -> wgpu::Buffer {
        self.device.create_buffer(&wgpu::BufferDescriptor {
            label: Some(label),
            size: size.max(16).next_multiple_of(4),
            usage: wgpu::BufferUsages::STORAGE
                | wgpu::BufferUsages::COPY_SRC
                | wgpu::BufferUsages::COPY_DST,
            mapped_at_creation: false,
        })
    }

    pub fn uniform(&self, label: &str, data: &[u8]) -> wgpu::Buffer {
        self.device
            .create_buffer_init(&wgpu::util::BufferInitDescriptor {
                label: Some(label),
                contents: data,
                usage: wgpu::BufferUsages::UNIFORM | wgpu::BufferUsages::COPY_DST,
            })
    }

    /// A compute pipeline from WGSL (its bind group layout inferred from the shader).
    pub fn pipeline(&self, label: &str, wgsl: &str, entry: &str) -> wgpu::ComputePipeline {
        let module = self
            .device
            .create_shader_module(wgpu::ShaderModuleDescriptor {
                label: Some(label),
                source: wgpu::ShaderSource::Wgsl(wgsl.into()),
            });
        self.device
            .create_compute_pipeline(&wgpu::ComputePipelineDescriptor {
                label: Some(label),
                layout: None,
                module: &module,
                entry_point: Some(entry),
                compilation_options: Default::default(),
                cache: None,
            })
    }

    /// Group 0's bindings 0, 1, ... in order.
    pub fn bind(&self, pipe: &wgpu::ComputePipeline, buffers: &[&wgpu::Buffer]) -> wgpu::BindGroup {
        let layout = pipe.get_bind_group_layout(0);
        let entries: Vec<wgpu::BindGroupEntry> = buffers
            .iter()
            .enumerate()
            .map(|(i, b)| wgpu::BindGroupEntry {
                binding: i as u32,
                resource: b.as_entire_binding(),
            })
            .collect();
        self.device.create_bind_group(&wgpu::BindGroupDescriptor {
            label: None,
            layout: &layout,
            entries: &entries,
        })
    }

    /// Dispatch and wait for it.
    pub fn run(
        &self,
        pipe: &wgpu::ComputePipeline,
        group: &wgpu::BindGroup,
        workgroups: (u32, u32, u32),
    ) -> Result<(), String> {
        let mut enc = self
            .device
            .create_command_encoder(&wgpu::CommandEncoderDescriptor { label: None });
        {
            let mut pass = enc.begin_compute_pass(&wgpu::ComputePassDescriptor {
                label: None,
                timestamp_writes: None,
            });
            pass.set_pipeline(pipe);
            pass.set_bind_group(0, group, &[]);
            pass.dispatch_workgroups(workgroups.0, workgroups.1, workgroups.2);
        }
        self.queue.submit([enc.finish()]);
        self.device
            .poll(wgpu::PollType::wait_indefinitely())
            .map_err(|e| format!("GPU: {e}"))?;
        Ok(())
    }

    /// Several dispatches of one pipeline, each with its bind group, in one submission.
    pub fn run_many(
        &self,
        pipe: &wgpu::ComputePipeline,
        work: &[(&wgpu::BindGroup, (u32, u32, u32))],
    ) -> Result<(), String> {
        let mut enc = self
            .device
            .create_command_encoder(&wgpu::CommandEncoderDescriptor { label: None });
        {
            let mut pass = enc.begin_compute_pass(&wgpu::ComputePassDescriptor {
                label: None,
                timestamp_writes: None,
            });
            pass.set_pipeline(pipe);
            for (group, wg) in work {
                pass.set_bind_group(0, *group, &[]);
                pass.dispatch_workgroups(wg.0, wg.1, wg.2);
            }
        }
        self.queue.submit([enc.finish()]);
        self.device
            .poll(wgpu::PollType::wait_indefinitely())
            .map_err(|e| format!("GPU: {e}"))?;
        Ok(())
    }

    /// A buffer's first `size` bytes, copied back.
    pub fn read(&self, buf: &wgpu::Buffer, size: u64) -> Result<Vec<u8>, String> {
        let size = size.next_multiple_of(4).max(4);
        let staging = self.device.create_buffer(&wgpu::BufferDescriptor {
            label: Some("readback"),
            size,
            usage: wgpu::BufferUsages::MAP_READ | wgpu::BufferUsages::COPY_DST,
            mapped_at_creation: false,
        });
        let mut enc = self
            .device
            .create_command_encoder(&wgpu::CommandEncoderDescriptor { label: None });
        enc.copy_buffer_to_buffer(buf, 0, &staging, 0, size);
        self.queue.submit([enc.finish()]);
        let (tx, rx) = std::sync::mpsc::channel();
        staging.map_async(wgpu::MapMode::Read, .., move |r| {
            let _ = tx.send(r);
        });
        self.device
            .poll(wgpu::PollType::wait_indefinitely())
            .map_err(|e| format!("GPU: {e}"))?;
        rx.recv()
            .map_err(|e| format!("GPU readback: {e}"))?
            .map_err(|e| format!("GPU readback: {e}"))?;
        let out = staging.get_mapped_range(..).to_vec();
        staging.unmap();
        Ok(out)
    }
}
