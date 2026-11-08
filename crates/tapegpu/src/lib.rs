//! The tape medium's recording kernel on the GPU (docs/TAPE_SPEED_PLAN.md P5): circuitsim's
//! `tape::record` (the reference; its docstring has the physics) in f32 on wgpu, one
//! invocation per (layer, cell, easy axis), each the corner formula's backward pass over
//! the bias peaks in the cell's zone. circuitsim calls it behind its `gpu` feature when a
//! recording asks for it (`Recording::gpu`); the f64 CPU kernel stays the default.
//!
//! [`reference::record`] is this kernel's f64 CPU reference, step for step (the tests hold
//! the GPU to it); circuitsim's tests hold both to `tape::record`.
//!
//! **Precision.** The tape's position runs to tens of metres, past f32's resolution of a
//! bias wavelength, so positions go up as (hi, lo) pairs from the block's middle (the f64
//! offset is hi + lo); a cell's distance past the gap is (hi - hi) + (lo - lo), exact to
//! f32's rounding of a distance of tens of microns. The zones' peak ranges are found in
//! f64 by the caller, so every cell sees the same peaks as on the CPU. What is left is the
//! Preisach tables' and the sums' f32 rounding (~1e-7 per term).

pub mod gpu;
pub mod reference;

use std::sync::{Arc, Mutex, OnceLock};

use bytemuck::{Pod, Zeroable};

use crate::gpu::Gpu;

/// The particles' tables (circuitsim's `tape::Preisach`): Q at the nodes ((n + 1)^2, row
/// alpha major) and D (n + 1), over +-h_max. `key` names them (the GPU keeps a few
/// uploaded, by key).
#[derive(Debug, Clone, Copy)]
pub struct Tables<'a> {
    pub key: [u64; 5],
    pub h_max: f64,
    pub n: usize,
    pub q: &'a [f64],
    pub d: &'a [f64],
}

/// One layer's head field (Hx, Hy) / Hg at x0 + i dx (circuitsim's `tape::FieldTable`).
#[derive(Debug, Clone, Copy)]
pub struct FieldTable<'a> {
    pub x0: f64,
    pub inv_dx: f64,
    pub fx: &'a [f64],
    pub fy: &'a [f64],
}

/// One recording (circuitsim's `tape::Recording`, its zones resolved to peak ranges).
#[derive(Debug, Clone, Copy)]
pub struct Block<'a> {
    pub tables: Tables<'a>,
    /// The record head's (gap, pole, relax), m.
    pub head: [f64; 3],
    /// Each layer's height above the head.
    pub heights: &'a [f64],
    /// Per layer the head field's table, or None: the exact field.
    pub field: Option<&'a [FieldTable<'a>]>,
    pub s_cells: &'a [f64],
    /// The peaks [k0, k1) each cell sees, per layer and cell (layer major).
    pub ranges: &'a [[u32; 2]],
    /// The tape position at the record gap and the deep-gap field at each peak.
    pub s_rec: &'a [f64],
    pub hg: &'a [f64],
    /// (cos, sin, weight) per easy axis.
    pub axes: &'a [[f64; 3]],
    /// The steady field (x, y) through the pass, per layer and cell.
    pub h_static: Option<(&'a [f64], &'a [f64])>,
    /// The steady field after the pass, if not `h_static`.
    pub h_end: Option<(&'a [f64], &'a [f64])>,
}

impl Block<'_> {
    pub fn check(&self) -> Result<(), String> {
        let (layers, cells) = (self.heights.len(), self.s_cells.len());
        let t = &self.tables;
        if t.n < 2 || t.q.len() != (t.n + 1) * (t.n + 1) || t.d.len() != t.n + 1 {
            return Err("tapegpu: Q is (n + 1)^2, D n + 1".into());
        }
        if self.ranges.len() != layers * cells {
            return Err("tapegpu: ranges are layers x cells".into());
        }
        if self.s_rec.len() != self.hg.len() {
            return Err("tapegpu: s_rec and hg differ in length".into());
        }
        if self
            .ranges
            .iter()
            .any(|r| r[1] as usize > self.s_rec.len() || r[0] as usize > self.s_rec.len())
        {
            return Err("tapegpu: a range past the peaks".into());
        }
        for h in [self.h_static, self.h_end].into_iter().flatten() {
            if h.0.len() != layers * cells || h.1.len() != layers * cells {
                return Err("tapegpu: steady fields are layers x cells".into());
            }
        }
        if let Some(f) = self.field
            && (f.len() != layers || f.iter().any(|t| t.fx.len() < 4 || t.fy.len() != t.fx.len()))
        {
            return Err("tapegpu: one field table per layer, 4 points or more".into());
        }
        Ok(())
    }

    /// The steady fields (x, y) through and after the pass at (layer, cell).
    pub(crate) fn steady(&self, lc: usize) -> [f64; 4] {
        let at = |h: Option<(&[f64], &[f64])>| h.map_or((0.0, 0.0), |(x, y)| (x[lc], y[lc]));
        let (sx, sy) = at(self.h_static);
        let (ex, ey) = if self.h_end.is_some() {
            at(self.h_end)
        } else {
            (sx, sy)
        };
        [sx, sy, ex, ey]
    }
}

#[repr(C)]
#[derive(Clone, Copy, Pod, Zeroable)]
struct Params {
    cells: u32,
    n_axes: u32,
    n: u32,
    field_exact: u32,
    h_max: f32,
    inv_step: f32,
    big: f32,
    has_steady: u32,
    gap: f32,
    pole: f32,
    relax: f32,
    _pad: u32,
}

const WORKGROUP: u32 = 64;

struct Kernel {
    pipe: wgpu::ComputePipeline,
    /// Uploaded tables, by key (a few: a demag iteration records many times with one).
    tables: Mutex<Vec<([u64; 5], Arc<wgpu::Buffer>)>>,
}

static KERNEL: OnceLock<Result<Kernel, String>> = OnceLock::new();

fn kernel() -> Result<(&'static Gpu, &'static Kernel), String> {
    let g = gpu::gpu()?;
    let k = KERNEL
        .get_or_init(|| {
            Ok(Kernel {
                pipe: g.pipeline("tape record", include_str!("record.wgsl"), "record"),
                tables: Mutex::new(Vec::new()),
            })
        })
        .as_ref()
        .map_err(Clone::clone)?;
    Ok((g, k))
}

/// The GPU's name and backend, or why there is none (`VARIMU_GPU=off` turns it off).
pub fn available() -> Result<String, String> {
    kernel().map(|(g, _)| g.describe())
}

fn f32s(v: impl IntoIterator<Item = f64>) -> Vec<f32> {
    v.into_iter().map(|x| x as f32).collect()
}

/// An f64 as (hi, lo) f32s: hi the nearest f32, lo the rest's.
fn split(x: f64) -> [f32; 2] {
    let hi = x as f32;
    [hi, (x - hi as f64) as f32]
}

/// The remanent (M_x, M_y) / Ms per layer and cell (layer major), recorded on the GPU in
/// f32 (the orientations' sum in f64, in the reference's order).
pub fn record(b: &Block<'_>) -> Result<(Vec<f64>, Vec<f64>), String> {
    b.check()?;
    let (g, k) = kernel()?;
    let (layers, cells, n_axes) = (b.heights.len(), b.s_cells.len(), b.axes.len());
    if layers == 0 || cells == 0 {
        return Ok((vec![0.0; layers * cells], vec![0.0; layers * cells]));
    }
    let t = &b.tables;
    let tabs = {
        let mut list = k.tables.lock().map_err(|_| "tapegpu: tables")?;
        match list.iter().find(|(key, _)| *key == t.key) {
            Some((_, buf)) => buf.clone(),
            None => {
                let data = f32s(t.q.iter().chain(t.d).copied());
                let buf = Arc::new(g.storage("tape tables", bytemuck::cast_slice(&data)));
                list.push((t.key, buf.clone()));
                if list.len() > 4 {
                    list.remove(0);
                }
                buf
            }
        }
    };
    let origin = b.s_cells[cells / 2];
    let axes: Vec<[f32; 4]> = b
        .axes
        .iter()
        .map(|a| [a[0] as f32, a[1] as f32, 0.0, 0.0])
        .collect();
    let cell_s: Vec<[f32; 2]> = b.s_cells.iter().map(|&s| split(s - origin)).collect();
    let peaks: Vec<[f32; 4]> = b
        .s_rec
        .iter()
        .zip(b.hg)
        .map(|(&s, &h)| {
            let [hi, lo] = split(s - origin);
            [hi, lo, h as f32, 0.0]
        })
        .collect();
    let has_steady = b.h_static.is_some() || b.h_end.is_some();
    let steady: Vec<[f32; 4]> = if has_steady {
        (0..layers * cells)
            .map(|lc| b.steady(lc).map(|v| v as f32))
            .collect()
    } else {
        Vec::new()
    };
    let (mut info, mut ltab, mut field) = (Vec::new(), Vec::new(), Vec::<[f32; 2]>::new());
    for (l, &y) in b.heights.iter().enumerate() {
        match b.field {
            Some(f) => {
                let ft = &f[l];
                // x0 relative to the cell's distance past the gap: no origin to remove.
                info.push([ft.x0 as f32, ft.inv_dx as f32, y as f32, 0.0]);
                ltab.push([field.len() as u32, ft.fx.len() as u32]);
                field.extend(ft.fx.iter().zip(ft.fy).map(|(&a, &c)| [a as f32, c as f32]));
            }
            None => {
                info.push([0.0, 0.0, y as f32, 0.0]);
                ltab.push([0, 0]);
            }
        }
    }
    let ranges: &[u32] = bytemuck::cast_slice(b.ranges);
    let p = Params {
        cells: cells as u32,
        n_axes: n_axes as u32,
        n: t.n as u32,
        field_exact: b.field.is_none() as u32,
        h_max: t.h_max as f32,
        inv_step: (t.n as f64 / (2.0 * t.h_max)) as f32,
        big: (4.0 * t.h_max) as f32,
        has_steady: has_steady as u32,
        gap: b.head[0] as f32,
        pole: b.head[1] as f32,
        relax: b.head[2] as f32,
        _pad: 0,
    };
    let out_len = (layers * n_axes * cells) as u64 * 4;
    let bufs = [
        g.uniform("params", bytemuck::bytes_of(&p)),
        g.storage("axes", bytemuck::cast_slice(&axes)),
        g.storage("cells", bytemuck::cast_slice(&cell_s)),
        g.storage("ranges", bytemuck::cast_slice(ranges)),
        g.storage("peaks", bytemuck::cast_slice(&peaks)),
        g.storage("steady", bytemuck::cast_slice(&steady)),
        g.storage("layer info", bytemuck::cast_slice(&info)),
        g.storage("layer tables", bytemuck::cast_slice(&ltab)),
        g.storage("field", bytemuck::cast_slice(&field)),
        g.zeros("m", out_len),
    ];
    let group = g.bind(
        &k.pipe,
        &[
            &bufs[0], &tabs, &bufs[1], &bufs[2], &bufs[3], &bufs[4], &bufs[5], &bufs[6], &bufs[7],
            &bufs[8], &bufs[9],
        ],
    );
    g.run(
        &k.pipe,
        &group,
        (
            (cells as u32).div_ceil(WORKGROUP),
            n_axes as u32,
            layers as u32,
        ),
    )?;
    let raw = g.read(&bufs[9], out_len)?;
    let m: &[f32] = bytemuck::cast_slice(&raw[..out_len as usize]);
    Ok(sum_axes(b.axes, layers, cells, |l, a, c| {
        m[(l * n_axes + a) * cells + c] as f64
    }))
}

/// (M_x, M_y) from each axis's M (as circuitsim's `tape::cell` sums them).
pub(crate) fn sum_axes(
    axes: &[[f64; 3]],
    layers: usize,
    cells: usize,
    m: impl Fn(usize, usize, usize) -> f64,
) -> (Vec<f64>, Vec<f64>) {
    let mut mx = vec![0.0; layers * cells];
    let mut my = vec![0.0; layers * cells];
    for l in 0..layers {
        for c in 0..cells {
            let (mut x, mut y) = (0.0, 0.0);
            for (ai, a) in axes.iter().enumerate() {
                let v = m(l, ai, c);
                x += a[2] * a[0] * v;
                y += a[2] * a[1] * v;
            }
            mx[l * cells + c] = x;
            my[l * cells + c] = y;
        }
    }
    (mx, my)
}
