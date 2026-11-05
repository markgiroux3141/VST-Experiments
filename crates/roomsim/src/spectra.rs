//! The image sources' spectra (ROOM_LOOP_PLAN.md R9; `varimu.rooms.shoebox.responses`'s
//! early part): per entry e, spec[e][k] = sum over images i of S_i,e(f_k) exp(-2 pi j k d_i
//! / N), where S_i,e is the image's smooth spectrum given on a coarse grid (interpolated
//! linearly to bin k by `idx[k]`, `w[k]`), d_i its delay in samples and N the FFT's length
//! (a power of two). The GPU (`spectra.wgsl`, f32) and an f64 CPU reference.
//!
//! **The phase in f32.** k d / N cycles reaches ~10^4 (d to a few thousand samples, k to
//! N / 2), far past f32's resolution. So d = di + A / 4096 + b (integer, 12 fractional
//! bits, the rest b < 1 / 4096), and k d mod N = (k di mod N) + (k A mod 4096 N) / 4096 + k
//! b, the first two in u32 arithmetic, exact (N divides 2^32, so wrapping products keep
//! their residues; N <= 2^20), the last small (k b < 2^8 at N = 2^20). The angle is then
//! the sum of an exact multiple of 2 pi / N and a small rest: error ~1e-6 rad, -120 dB.
//!
//! **Shared spectra.** An image may name another's spectrum (`spec_index`) and scale it
//! (`scale`): an edge's diffraction impulse response (`varimu.rooms.diffraction`) is one
//! smooth spectrum (the walls, the air, the capsule's entries at the apex) times its samples,
//! each a micro-image at its own delay. Empty: image i has spectrum i, scale 1.

use bytemuck::{Pod, Zeroable};

use crate::gpu::Gpu;

pub const MAX_LOG2_N: u32 = 20;

#[derive(Clone, Debug)]
pub struct ImageSpectra {
    /// S[(i * n_ent + e) * n_grid + g] as (re, im).
    pub coarse: Vec<[f64; 2]>,
    pub n_ent: usize,
    pub n_grid: usize,
    /// d_i in samples (>= 0).
    pub delay: Vec<f64>,
    /// Per image: the spectrum it uses (empty: its own) and its scale (empty: 1).
    pub spec_index: Vec<u32>,
    pub scale: Vec<f64>,
    /// Per bin k: the coarse grid's interval (g, g + 1) and the weight of g + 1.
    pub idx: Vec<u32>,
    pub w: Vec<f64>,
    pub n_fft: usize,
}

impl ImageSpectra {
    pub fn n_img(&self) -> usize {
        self.delay.len()
    }

    /// The number of spectra in `coarse`.
    pub fn n_spec(&self) -> usize {
        self.coarse.len() / (self.n_ent * self.n_grid).max(1)
    }

    fn spec_of(&self, i: usize) -> usize {
        self.spec_index.get(i).map_or(i, |&k| k as usize)
    }

    fn scale_of(&self, i: usize) -> f64 {
        self.scale.get(i).copied().unwrap_or(1.0)
    }

    pub fn check(&self) -> Result<u32, String> {
        let n = self.n_fft;
        if !n.is_power_of_two() || n < 2 {
            return Err(format!("n_fft {n}: a power of two"));
        }
        let log2 = n.trailing_zeros();
        if log2 > MAX_LOG2_N {
            return Err(format!("n_fft 2^{log2}: at most 2^{MAX_LOG2_N}"));
        }
        if self.coarse.len() % (self.n_ent * self.n_grid).max(1) != 0 {
            return Err("coarse: spectra x entries x grid".into());
        }
        if self.spec_index.is_empty() {
            if self.n_spec() != self.n_img() {
                return Err("coarse: one spectrum per image (or spec_index)".into());
            }
        } else if self.spec_index.len() != self.n_img()
            || self.spec_index.iter().any(|&k| k as usize >= self.n_spec())
        {
            return Err("spec_index: per image, inside the spectra".into());
        }
        if !self.scale.is_empty() && self.scale.len() != self.n_img() {
            return Err("scale: per image".into());
        }
        if self.idx.len() != self.w.len() {
            return Err("idx and w per bin".into());
        }
        if self.idx.iter().any(|&g| g as usize + 1 >= self.n_grid) {
            return Err("idx: g + 1 inside the grid".into());
        }
        if self.delay.iter().any(|d| !(*d >= 0.0 && *d < 1e9)) {
            return Err("delays: >= 0 samples".into());
        }
        Ok(log2)
    }
}

/// The f64 reference: spec[e * K + k] as (re, im).
pub fn spectra_cpu(s: &ImageSpectra) -> Result<Vec<[f64; 2]>, String> {
    s.check()?;
    let nk = s.idx.len();
    let n = s.n_fft as f64;
    let mut out = vec![[0.0; 2]; s.n_ent * nk];
    let threads = std::thread::available_parallelism().map_or(4, |n| n.get());
    let chunk = nk.div_ceil(threads).max(1);
    let parts: Vec<(usize, Vec<[f64; 2]>)> = std::thread::scope(|sc| {
        let hs: Vec<_> = (0..nk)
            .step_by(chunk)
            .map(|k0| {
                sc.spawn(move || {
                    let k1 = (k0 + chunk).min(nk);
                    let mut o = vec![[0.0; 2]; s.n_ent * (k1 - k0)];
                    for k in k0..k1 {
                        let (g, w) = (s.idx[k] as usize, s.w[k]);
                        for (i, &d) in s.delay.iter().enumerate() {
                            // the cycles mod 1, with k d split as the GPU's
                            let cyc = ((k as f64) * d / n).fract();
                            let (sn, cs) = (-std::f64::consts::TAU * cyc).sin_cos();
                            let (si, sc) = (s.spec_of(i), s.scale_of(i));
                            for e in 0..s.n_ent {
                                let base = (si * s.n_ent + e) * s.n_grid + g;
                                let (a, b) = (s.coarse[base], s.coarse[base + 1]);
                                let re = sc * (a[0] * (1.0 - w) + b[0] * w);
                                let im = sc * (a[1] * (1.0 - w) + b[1] * w);
                                let r = &mut o[e * (k1 - k0) + k - k0];
                                r[0] += re * cs - im * sn;
                                r[1] += re * sn + im * cs;
                            }
                        }
                    }
                    (k0, o)
                })
            })
            .collect();
        hs.into_iter().map(|h| h.join().unwrap()).collect()
    });
    for (k0, o) in parts {
        let len = o.len() / s.n_ent;
        for e in 0..s.n_ent {
            out[e * nk + k0..e * nk + k0 + len].copy_from_slice(&o[e * len..(e + 1) * len]);
        }
    }
    Ok(out)
}

#[repr(C)]
#[derive(Clone, Copy, Pod, Zeroable)]
struct Params {
    n_img: u32,
    n_grid: u32,
    n_bins: u32,
    n_ent: u32,
    log2n: u32,
    img_offset: u32,
    n_img_batch: u32,
    _pad: u32,
}

const SPECTRA_WGSL: &str = include_str!("shaders/spectra.wgsl");
/// Images per dispatch (the gpu module's TDR note).
const BATCH: usize = 2048;

/// d as (di, A, b-bits, spectrum): integer samples, 12 fractional bits, the rest as f32.
fn split_delay(d: f64, spec: u32) -> [u32; 4] {
    let di = d.floor();
    let fr = d - di;
    let a = (fr * 4096.0).floor();
    let b = fr - a / 4096.0;
    [di as u32, a as u32, (b as f32).to_bits(), spec]
}

/// The same on the GPU, summed per bin in f32 over the images.
pub fn spectra_gpu(gpu: &Gpu, s: &ImageSpectra) -> Result<Vec<[f64; 2]>, String> {
    let log2 = s.check()?;
    let nk = s.idx.len();
    let coarse: Vec<[f32; 2]> = s
        .coarse
        .iter()
        .map(|c| [c[0] as f32, c[1] as f32])
        .collect();
    let delays: Vec<[u32; 4]> = s
        .delay
        .iter()
        .enumerate()
        .map(|(i, &d)| split_delay(d, s.spec_of(i) as u32))
        .collect();
    let scales: Vec<f32> = (0..s.n_img()).map(|i| s.scale_of(i) as f32).collect();
    let bins: Vec<[u32; 2]> = s
        .idx
        .iter()
        .zip(&s.w)
        .map(|(&g, &w)| [g, (w as f32).to_bits()])
        .collect();
    let b_coarse = gpu.storage("coarse", bytemuck::cast_slice(&coarse));
    let b_delay = gpu.storage("delay", bytemuck::cast_slice(&delays));
    let b_scale = gpu.storage("scale", bytemuck::cast_slice(&scales));
    let b_bins = gpu.storage("bins", bytemuck::cast_slice(&bins));
    let out_bytes = (s.n_ent * nk * 8) as u64;
    let b_out = gpu.zeros("spectra", out_bytes);
    let pipe = gpu.pipeline("spectra", SPECTRA_WGSL, "main");
    let groups = (nk as u32).div_ceil(64);
    let mut start = 0;
    let mut params = Vec::new();
    while start < s.n_img() || (start == 0 && s.n_img() == 0) {
        let n = BATCH.min(s.n_img() - start);
        params.push(gpu.uniform(
            "params",
            bytemuck::bytes_of(&Params {
                n_img: s.n_img() as u32,
                n_grid: s.n_grid as u32,
                n_bins: nk as u32,
                n_ent: s.n_ent as u32,
                log2n: log2,
                img_offset: start as u32,
                n_img_batch: n as u32,
                _pad: 0,
            }),
        ));
        start += n.max(1);
    }
    for p in &params {
        let group = gpu.bind(&pipe, &[p, &b_coarse, &b_delay, &b_bins, &b_out, &b_scale]);
        gpu.run(&pipe, &group, (groups, 1, 1))?;
    }
    let raw = gpu.read(&b_out, out_bytes)?;
    let v: &[[f32; 2]] = bytemuck::cast_slice(&raw);
    Ok(v[..s.n_ent * nk]
        .iter()
        .map(|c| [f64::from(c[0]), f64::from(c[1])])
        .collect())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn case(n_img: usize, log2: u32) -> ImageSpectra {
        let n_fft = 1usize << log2;
        let nk = n_fft / 2 + 1;
        let n_grid = 64;
        let mut coarse = Vec::new();
        let mut delay = Vec::new();
        for i in 0..n_img {
            let x = crate::rays::rnd(7, i as u32, 0, 0);
            delay.push(10.0 + 7000.0 * x + 0.123_456_789 * x);
            for e in 0..2 {
                for g in 0..n_grid {
                    let a = (1.0 + g as f64 * 0.01) / (1.0 + i as f64 * 0.02);
                    coarse.push([a * (1.0 - 0.3 * e as f64), 0.1 * a * (g as f64).sin()]);
                }
            }
        }
        let idx: Vec<u32> = (0..nk)
            .map(|k| ((k * (n_grid - 1)) / nk).min(n_grid - 2) as u32)
            .collect();
        let w = (0..nk)
            .map(|k| ((k * (n_grid - 1)) as f64 / nk as f64).fract())
            .collect();
        ImageSpectra {
            coarse,
            n_ent: 2,
            n_grid,
            delay,
            spec_index: Vec::new(),
            scale: Vec::new(),
            idx,
            w,
            n_fft,
        }
    }

    #[test]
    fn a_single_image_is_a_delay() {
        let mut s = case(1, 10);
        s.delay = vec![3.25];
        for c in s.coarse.iter_mut() {
            *c = [1.0, 0.0];
        }
        let out = spectra_cpu(&s).unwrap();
        let k = 100;
        let want = -std::f64::consts::TAU * k as f64 * 3.25 / 1024.0;
        assert!((out[k][0] - want.cos()).abs() < 1e-12);
        assert!((out[k][1] - want.sin()).abs() < 1e-12);
    }

    #[test]
    fn gpu_matches_the_cpu_below_minus_100_db() {
        let Ok(gpu) = crate::gpu::gpu() else {
            eprintln!("no GPU: skipped");
            return;
        };
        for (n_img, log2) in [(300, 19), (3000, 14)] {
            let s = case(n_img, log2);
            let c = spectra_cpu(&s).unwrap();
            let g = spectra_gpu(gpu, &s).unwrap();
            let (mut num, mut den) = (0.0, 0.0);
            for (a, b) in c.iter().zip(&g) {
                num += (a[0] - b[0]).powi(2) + (a[1] - b[1]).powi(2);
                den += a[0] * a[0] + a[1] * a[1];
            }
            let db = 10.0 * (num / den).log10();
            assert!(db < -100.0, "{n_img} images, 2^{log2}: {db:.1} dB");
        }
    }

    #[test]
    fn shared_spectra_are_the_images_they_stand_for() {
        // two images through one spectrum, scaled, equal two images with their own
        let mut own = case(2, 12);
        let sz = own.n_ent * own.n_grid;
        let first: Vec<[f64; 2]> = own.coarse[..sz].to_vec();
        own.coarse = first.iter().chain(first.iter()).map(|c| *c).collect();
        for c in own.coarse[sz..].iter_mut() {
            c[0] *= -0.5;
            c[1] *= -0.5;
        }
        let mut shared = own.clone();
        shared.coarse = first;
        shared.spec_index = vec![0, 0];
        shared.scale = vec![1.0, -0.5];
        let a = spectra_cpu(&own).unwrap();
        let b = spectra_cpu(&shared).unwrap();
        for (x, y) in a.iter().zip(&b) {
            assert!((x[0] - y[0]).abs() < 1e-12 && (x[1] - y[1]).abs() < 1e-12);
        }
        if let Ok(gpu) = crate::gpu::gpu() {
            let g = spectra_gpu(gpu, &shared).unwrap();
            for (x, y) in a.iter().zip(&g) {
                assert!((x[0] - y[0]).abs() < 1e-5 && (x[1] - y[1]).abs() < 1e-5);
            }
        }
    }
}
