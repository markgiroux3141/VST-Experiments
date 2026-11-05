//! Ray tracing for a room's energy decay (ROOM_LOOP_PLAN.md R6 / R9): the port of
//! `varimu.rooms.polyroom.ray_decay` (its docstring has the physics), on the GPU
//! (`rays.wgsl`, f32) with an f64 CPU reference here.
//!
//! The room is triangles, each on a face (a plane with its inward normal, absorption per
//! band and a scattering coefficient). A ray starts at the source in a given direction with
//! energy 1 per band; at each wall it loses alpha per band and leaves specularly or, with the
//! scattering coefficient's probability, in a Lambert (cosine) direction. Two things are
//! recorded on a grid of 1 / fs_env:
//!
//! - **travelling**: per band, the energy of all rays still travelling at the instants
//!   (k + 1) / fs_env (numpy's `1 - cumsum(lost)` at bin k, summed over rays rather than
//!   as a fraction; no cancellation, so the decay is good far down);
//! - **density**: per receiver (a sphere of `radius`), per band, the energy times the time
//!   each ray segment spends inside it, binned at the time of the segment's middle there.
//!
//! A ray may start with less energy in some bands than others (`RayRoom::weights`, per ray
//! and band: a directional source, `varimu.rooms.directivity`'s |D|^2 in the ray's direction).
//!
//! Random numbers are a hash of (seed, ray, bounce, draw) (`rnd`), the same on the GPU and
//! the CPU, so the two differ only by their arithmetic (f32 trajectories part from f64 ones
//! after a few dozen bounces: they agree in their statistics). The GPU sums in 64-bit fixed
//! point (2^-40) with integer atomics: the result doesn't depend on the order threads
//! finish, so it is the same on every run.

use bytemuck::{Pod, Zeroable};

use crate::gpu::Gpu;

pub const BANDS: usize = 7;
const EPS_BARY: f64 = 1e-5;
const OFFSET_M: f64 = 1e-5;
pub const DEFAULT_MAX_BOUNCES: u32 = 10_000;

/// The room's surfaces and receivers, and the run's settings.
#[derive(Clone, Debug)]
pub struct RayRoom {
    /// Triangles: v0, v1, v2 (m), and each one's face.
    pub tris: Vec<[[f64; 3]; 3]>,
    pub tri_face: Vec<u32>,
    /// Per face: the unit normal into the room, alpha per band, scattering.
    pub normals: Vec<[f64; 3]>,
    pub alpha: Vec<[f64; BANDS]>,
    pub scattering: Vec<f64>,
    pub receivers: Vec<[f64; 3]>,
    /// Per ray, its starting energy per band (empty: 1).
    pub weights: Vec<[f64; BANDS]>,
    pub radius_m: f64,
    pub c: f64,
    pub t_max_s: f64,
    pub fs_env: f64,
    pub seed: u32,
    pub max_bounces: u32,
}

/// What a run records (the module docstring), flattened: travelling[b * nt + k],
/// density[(r * BANDS + b) * nt + k].
#[derive(Clone, Debug)]
pub struct RayResult {
    pub nt: usize,
    pub travelling: Vec<f64>,
    pub density: Vec<f64>,
}

impl RayRoom {
    pub fn nt(&self) -> usize {
        (self.t_max_s * self.fs_env) as usize + 1
    }

    pub fn check(&self) -> Result<(), String> {
        let nf = self.normals.len();
        if self.tris.len() != self.tri_face.len() {
            return Err("a face index per triangle".into());
        }
        if self.alpha.len() != nf || self.scattering.len() != nf {
            return Err("alpha and scattering per face".into());
        }
        if self.tri_face.iter().any(|&f| f as usize >= nf) {
            return Err("a triangle's face out of range".into());
        }
        if self.tris.is_empty() {
            return Err("no triangles".into());
        }
        if self
            .weights
            .iter()
            .flatten()
            .any(|w| w.is_nan() || *w < 0.0)
        {
            return Err("ray weights: >= 0".into());
        }
        Ok(())
    }

    fn weight(&self, ray: usize) -> [f64; BANDS] {
        self.weights.get(ray).copied().unwrap_or([1.0; BANDS])
    }
}

/// PCG's output hash (O'Neill), as `rays.wgsl`'s `pcg`.
pub fn pcg(v: u32) -> u32 {
    let state = v.wrapping_mul(747_796_405).wrapping_add(2_891_336_453);
    let word = ((state >> ((state >> 28) + 4)) ^ state).wrapping_mul(277_803_737);
    (word >> 22) ^ word
}

/// A uniform draw in [0, 1) on a 2^-24 grid: the same number in f32 and f64.
pub fn rnd(seed: u32, ray: u32, bounce: u32, k: u32) -> f64 {
    let h = pcg(seed ^ pcg(ray ^ pcg(bounce.wrapping_mul(4).wrapping_add(k))));
    f64::from(h >> 8) / 16_777_216.0
}

fn sub(a: [f64; 3], b: [f64; 3]) -> [f64; 3] {
    [a[0] - b[0], a[1] - b[1], a[2] - b[2]]
}
fn dot(a: [f64; 3], b: [f64; 3]) -> f64 {
    a[0] * b[0] + a[1] * b[1] + a[2] * b[2]
}
fn cross(a: [f64; 3], b: [f64; 3]) -> [f64; 3] {
    [
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    ]
}
fn axpy(a: f64, x: [f64; 3], y: [f64; 3]) -> [f64; 3] {
    [a * x[0] + y[0], a * x[1] + y[1], a * x[2] + y[2]]
}
fn normalize(v: [f64; 3]) -> [f64; 3] {
    let n = dot(v, v).sqrt();
    [v[0] / n, v[1] / n, v[2] / n]
}

/// The nearest triangle ahead of p along d whose face is approached from inside.
fn nearest(
    room: &RayRoom,
    edges: &[([f64; 3], [f64; 3])],
    p: [f64; 3],
    d: [f64; 3],
) -> Option<(f64, usize)> {
    let mut best = f64::INFINITY;
    let mut bf = None;
    for (i, tri) in room.tris.iter().enumerate() {
        let f = room.tri_face[i] as usize;
        if dot(d, room.normals[f]) >= -1e-9 {
            continue;
        }
        let (e1, e2) = edges[i];
        let pv = cross(d, e2);
        let det = dot(e1, pv);
        if det.abs() < 1e-12 {
            continue;
        }
        let inv = 1.0 / det;
        let tv = sub(p, tri[0]);
        let u = dot(tv, pv) * inv;
        if !(-EPS_BARY..=1.0 + EPS_BARY).contains(&u) {
            continue;
        }
        let qv = cross(tv, e1);
        let v = dot(d, qv) * inv;
        if v < -EPS_BARY || u + v > 1.0 + EPS_BARY {
            continue;
        }
        let t = dot(e2, qv) * inv;
        if t > 1e-6 && t < best {
            best = t;
            bf = Some(f);
        }
    }
    bf.map(|f| (best, f))
}

/// One ray, its records added to `trav` and `dens` (the module docstring).
fn trace_one(
    room: &RayRoom,
    edges: &[([f64; 3], [f64; 3])],
    src: [f64; 3],
    dir: [f64; 3],
    ray: u32,
    trav: &mut [f64],
    dens: &mut [f64],
) {
    let nt = room.nt();
    let (fs, c) = (room.fs_env, room.c);
    let mut p = src;
    let mut d = dir;
    let mut e = room.weight(ray as usize);
    let mut t = 0.0f64;
    for bounce in 0..room.max_bounces {
        let Some((best, f)) = nearest(room, edges, p, d) else {
            break; // a numerical escape: the ray's energy leaves now
        };
        let t1 = t + best / c;
        // still travelling at the instants (k + 1) / fs in [t, t1)
        let k_lo = (t * fs - 1.0).ceil().max(0.0) as usize;
        let k_hi = ((t1 * fs - 1.0).ceil() as usize).min(nt);
        for k in k_lo..k_hi {
            for b in 0..BANDS {
                trav[b * nt + k] += e[b];
            }
        }
        for (ri, rc) in room.receivers.iter().enumerate() {
            let v = sub(*rc, p);
            let proj = dot(v, d);
            let d2 = dot(v, v) - proj * proj;
            let r2 = room.radius_m * room.radius_m;
            if d2 >= r2 {
                continue;
            }
            let half = (r2 - d2).max(0.0).sqrt();
            let s0 = (proj - half).clamp(0.0, best);
            let s1 = (proj + half).clamp(0.0, best);
            let ln = s1 - s0;
            if ln <= 0.0 {
                continue;
            }
            let k = ((t + 0.5 * (s0 + s1) / c) * fs) as usize;
            if k < nt {
                for b in 0..BANDS {
                    dens[(ri * BANDS + b) * nt + k] += e[b] * ln / c;
                }
            }
        }
        p = axpy(best, d, p);
        t = t1;
        if t >= room.t_max_s {
            break;
        }
        let a = &room.alpha[f];
        let mut emax = 0.0f64;
        for b in 0..BANDS {
            e[b] *= 1.0 - a[b];
            emax = emax.max(e[b]);
        }
        let n = room.normals[f];
        if rnd(room.seed, ray, bounce, 0) < room.scattering[f] {
            let z = 2.0 * rnd(room.seed, ray, bounce, 1) - 1.0;
            let phi = std::f64::consts::TAU * rnd(room.seed, ray, bounce, 2);
            let s = (1.0 - z * z).max(0.0).sqrt();
            let mut v = [s * phi.cos(), s * phi.sin(), z];
            if dot(v, n) < 0.0 {
                v = [-v[0], -v[1], -v[2]];
            }
            d = normalize([n[0] + v[0], n[1] + v[1], n[2] + v[2]]);
        } else {
            d = axpy(-2.0 * dot(d, n), n, d);
        }
        p = axpy(OFFSET_M, n, p);
        if emax < 1e-7 {
            break;
        }
    }
}

fn edges(room: &RayRoom) -> Vec<([f64; 3], [f64; 3])> {
    room.tris
        .iter()
        .map(|t| (sub(t[1], t[0]), sub(t[2], t[0])))
        .collect()
}

/// The CPU reference (f64), the rays split over the cores.
pub fn trace_cpu(room: &RayRoom, src: [f64; 3], dirs: &[[f64; 3]]) -> Result<RayResult, String> {
    room.check()?;
    if !room.weights.is_empty() && room.weights.len() != dirs.len() {
        return Err("weights: one per ray".into());
    }
    let nt = room.nt();
    let nr = room.receivers.len();
    let ed = edges(room);
    let threads = std::thread::available_parallelism().map_or(4, |n| n.get());
    let chunk = dirs.len().div_ceil(threads).max(1);
    let parts: Vec<(Vec<f64>, Vec<f64>)> = std::thread::scope(|s| {
        let handles: Vec<_> = dirs
            .chunks(chunk)
            .enumerate()
            .map(|(ci, ds)| {
                let ed = &ed;
                s.spawn(move || {
                    let mut trav = vec![0.0; BANDS * nt];
                    let mut dens = vec![0.0; nr * BANDS * nt];
                    for (j, d) in ds.iter().enumerate() {
                        let ray = (ci * chunk + j) as u32;
                        trace_one(room, ed, src, *d, ray, &mut trav, &mut dens);
                    }
                    (trav, dens)
                })
            })
            .collect();
        handles.into_iter().map(|h| h.join().unwrap()).collect()
    });
    let mut out = RayResult {
        nt,
        travelling: vec![0.0; BANDS * nt],
        density: vec![0.0; nr * BANDS * nt],
    };
    for (t, d) in parts {
        out.travelling.iter_mut().zip(t).for_each(|(a, b)| *a += b);
        out.density.iter_mut().zip(d).for_each(|(a, b)| *a += b);
    }
    Ok(out)
}

#[repr(C)]
#[derive(Clone, Copy, Pod, Zeroable)]
struct Params {
    src: [f32; 4],
    n_rays: u32,
    n_tris: u32,
    n_rx: u32,
    nt: u32,
    t_max: f32,
    fs_env: f32,
    c: f32,
    radius: f32,
    seed: u32,
    ray_offset: u32,
    max_bounces: u32,
    n_batch: u32,
}

const RAYS_WGSL: &str = include_str!("shaders/rays.wgsl");
/// Rays per dispatch: each a short one (the module gpu's TDR note).
const BATCH: usize = 4096;

fn fixed_to_f64(words: &[u8]) -> Vec<f64> {
    let w: &[u32] = bytemuck::cast_slice(words);
    w.chunks_exact(2)
        .map(|p| (f64::from(p[1]) * 4_294_967_296.0 + f64::from(p[0])) / 1_099_511_627_776.0)
        .collect()
}

/// The same on the GPU (f32 trajectories, sums exact in 64-bit fixed point).
pub fn trace_gpu(
    gpu: &Gpu,
    room: &RayRoom,
    src: [f64; 3],
    dirs: &[[f64; 3]],
) -> Result<RayResult, String> {
    room.check()?;
    if !room.weights.is_empty() && room.weights.len() != dirs.len() {
        return Err("weights: one per ray".into());
    }
    let nt = room.nt();
    let nr = room.receivers.len();
    let f = |x: f64| x as f32;
    let tris: Vec<[f32; 12]> = room
        .tris
        .iter()
        .zip(&room.tri_face)
        .map(|(t, &fi)| {
            let (e1, e2) = (sub(t[1], t[0]), sub(t[2], t[0]));
            [
                f(t[0][0]),
                f(t[0][1]),
                f(t[0][2]),
                fi as f32,
                f(e1[0]),
                f(e1[1]),
                f(e1[2]),
                0.0,
                f(e2[0]),
                f(e2[1]),
                f(e2[2]),
                0.0,
            ]
        })
        .collect(); // fmt: skip
    let faces: Vec<[f32; 12]> = (0..room.normals.len())
        .map(|i| {
            let (n, a) = (room.normals[i], room.alpha[i]);
            [
                f(n[0]),
                f(n[1]),
                f(n[2]),
                f(room.scattering[i]),
                f(a[0]),
                f(a[1]),
                f(a[2]),
                f(a[3]),
                f(a[4]),
                f(a[5]),
                f(a[6]),
                0.0,
            ]
        })
        .collect(); // fmt: skip
    let dv: Vec<[f32; 4]> = dirs
        .iter()
        .map(|d| [f(d[0]), f(d[1]), f(d[2]), 0.0])
        .collect();
    let rv: Vec<[f32; 4]> = room
        .receivers
        .iter()
        .map(|r| [f(r[0]), f(r[1]), f(r[2]), 0.0])
        .collect();
    let b_tris = gpu.storage("tris", bytemuck::cast_slice(&tris));
    let b_faces = gpu.storage("faces", bytemuck::cast_slice(&faces));
    let b_dirs = gpu.storage("dirs", bytemuck::cast_slice(&dv));
    let b_rx = gpu.storage("rx", bytemuck::cast_slice(&rv));
    let wv: Vec<[f32; 8]> = (0..dirs.len())
        .map(|i| {
            let w = room.weight(i);
            [
                f(w[0]),
                f(w[1]),
                f(w[2]),
                f(w[3]),
                f(w[4]),
                f(w[5]),
                f(w[6]),
                0.0,
            ]
        })
        .collect();
    let b_w = gpu.storage("weights", bytemuck::cast_slice(&wv));
    let acc_bytes = (BANDS * nt * 8) as u64;
    let dens_bytes = (nr * BANDS * nt * 8) as u64;
    let b_acc = gpu.zeros("travelling", acc_bytes);
    let b_dens = gpu.zeros("density", dens_bytes);
    let pipe = gpu.pipeline("rays", RAYS_WGSL, "main");
    let mut start = 0;
    while start < dirs.len() {
        let n = BATCH.min(dirs.len() - start);
        let params = Params {
            src: [f(src[0]), f(src[1]), f(src[2]), 0.0],
            n_rays: dirs.len() as u32,
            n_tris: tris.len() as u32,
            n_rx: nr as u32,
            nt: nt as u32,
            t_max: f(room.t_max_s),
            fs_env: f(room.fs_env),
            c: f(room.c),
            radius: f(room.radius_m),
            seed: room.seed,
            ray_offset: start as u32,
            max_bounces: room.max_bounces,
            n_batch: n as u32,
        };
        let b_p = gpu.uniform("params", bytemuck::bytes_of(&params));
        let group = gpu.bind(
            &pipe,
            &[
                &b_p, &b_tris, &b_faces, &b_dirs, &b_rx, &b_acc, &b_dens, &b_w,
            ],
        );
        gpu.run(&pipe, &group, ((n as u32).div_ceil(64), 1, 1))?;
        start += n;
    }
    let travelling = fixed_to_f64(&gpu.read(&b_acc, acc_bytes)?);
    let density = if nr > 0 {
        fixed_to_f64(&gpu.read(&b_dens, dens_bytes)?)
    } else {
        Vec::new()
    };
    Ok(RayResult {
        nt,
        travelling,
        density,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    /// A 7 x 5.5 x 3.2 m shoebox as 12 triangles, furnished.
    pub fn shoebox() -> RayRoom {
        let (lx, ly, lz) = (7.0, 5.5, 3.2);
        let c = |x: f64, y: f64, z: f64| [x, y, z];
        // faces: floor, ceiling, x0, x1, y0, y1
        let quads = [
            [c(0., 0., 0.), c(lx, 0., 0.), c(lx, ly, 0.), c(0., ly, 0.)],
            [c(0., 0., lz), c(lx, 0., lz), c(lx, ly, lz), c(0., ly, lz)],
            [c(0., 0., 0.), c(0., ly, 0.), c(0., ly, lz), c(0., 0., lz)],
            [c(lx, 0., 0.), c(lx, ly, 0.), c(lx, ly, lz), c(lx, 0., lz)],
            [c(0., 0., 0.), c(lx, 0., 0.), c(lx, 0., lz), c(0., 0., lz)],
            [c(0., ly, 0.), c(lx, ly, 0.), c(lx, ly, lz), c(0., ly, lz)],
        ];
        let normals = vec![
            [0., 0., 1.],
            [0., 0., -1.],
            [1., 0., 0.],
            [-1., 0., 0.],
            [0., 1., 0.],
            [0., -1., 0.],
        ];
        let mut tris = Vec::new();
        let mut tri_face = Vec::new();
        for (fi, q) in quads.iter().enumerate() {
            tris.push([q[0], q[1], q[2]]);
            tris.push([q[0], q[2], q[3]]);
            tri_face.extend([fi as u32, fi as u32]);
        }
        let wall = [0.25, 0.20, 0.20, 0.25, 0.30, 0.30, 0.30];
        RayRoom {
            tris,
            tri_face,
            normals,
            alpha: vec![wall; 6],
            scattering: vec![0.3; 6],
            receivers: vec![[4.5, 2.25, 1.6]],
            weights: Vec::new(),
            radius_m: 0.35,
            c: 343.2,
            t_max_s: 1.5,
            fs_env: 1000.0,
            seed: 0,
            max_bounces: DEFAULT_MAX_BOUNCES,
        }
    }

    pub fn sphere_dirs(n: usize) -> Vec<[f64; 3]> {
        (0..n)
            .map(|i| {
                let z = 1.0 - 2.0 * (i as f64 + 0.5) / n as f64;
                let phi = std::f64::consts::PI * (1.0 + 5f64.sqrt()) * (i as f64 + 0.5);
                let r = (1.0 - z * z).sqrt();
                [r * phi.cos(), r * phi.sin(), z]
            })
            .collect()
    }

    fn db(x: f64) -> f64 {
        10.0 * x.max(1e-300).log10()
    }

    #[test]
    fn rng_is_the_shaders() {
        // pinned values: the WGSL `rnd` hashes the same integers
        assert_eq!(pcg(0), 129_708_002);
        let x = rnd(1, 2, 3, 0);
        assert!((0.0..1.0).contains(&x));
        assert_eq!(x, rnd(1, 2, 3, 0));
        assert_ne!(x, rnd(1, 2, 3, 1));
    }

    #[test]
    fn energy_is_conserved_without_absorption() {
        let mut room = shoebox();
        room.alpha = vec![[0.0; BANDS]; 6];
        room.t_max_s = 0.3;
        let r = trace_cpu(&room, [2.0, 2.55, 1.3], &sphere_dirs(500)).unwrap();
        // every ray still travels at every instant (no escapes)
        for k in 0..r.nt - 1 {
            assert!(
                (r.travelling[k] - 500.0).abs() < 1e-9,
                "{k}: {}",
                r.travelling[k]
            );
        }
    }

    #[test]
    fn weights_scale_each_rays_energy() {
        let mut room = shoebox();
        room.t_max_s = 0.3;
        let dirs = sphere_dirs(400);
        let src = [2.0, 2.55, 1.3];
        let a = trace_cpu(&room, src, &dirs).unwrap();
        room.weights = vec![[0.5; BANDS]; dirs.len()];
        let b = trace_cpu(&room, src, &dirs).unwrap();
        for (x, y) in a.travelling.iter().zip(&b.travelling) {
            assert!((0.5 * x - y).abs() < 1e-9 * x.abs().max(1.0));
        }
        if let Ok(gpu) = crate::gpu::gpu() {
            let g = trace_gpu(gpu, &room, src, &dirs).unwrap();
            assert!(
                (g.travelling[0] - 200.0).abs() < 1e-6,
                "{}",
                g.travelling[0]
            );
        }
    }

    #[test]
    fn gpu_matches_the_cpu() {
        let Ok(gpu) = crate::gpu::gpu() else {
            eprintln!("no GPU: skipped");
            return;
        };
        let room = shoebox();
        let dirs = sphere_dirs(20_000);
        let src = [2.0, 2.55, 1.3];
        let c = trace_cpu(&room, src, &dirs).unwrap();
        let g = trace_gpu(gpu, &room, src, &dirs).unwrap();
        let g2 = trace_gpu(gpu, &room, src, &dirs).unwrap();
        assert_eq!(
            g.travelling, g2.travelling,
            "the GPU's sums are deterministic"
        );
        let nt = c.nt;
        // the decay curves within 0.1 dB to -40 dB, as long as rays agree in statistics
        for b in 0..BANDS {
            for k in (0..nt).step_by(10) {
                let (x, y) = (c.travelling[b * nt + k], g.travelling[b * nt + k]);
                if db(x / 20_000.0) < -40.0 {
                    break;
                }
                assert!(
                    (db(x) - db(y)).abs() < 0.1,
                    "band {b} at {k} ms: {x} vs {y}"
                );
            }
        }
        // the receiver's energy over 0.1-0.5 s within 0.2 dB
        let sum =
            |r: &RayResult, b: usize| -> f64 { r.density[b * nt + 100..b * nt + 500].iter().sum() };
        for b in 0..BANDS {
            assert!((db(sum(&c, b)) - db(sum(&g, b))).abs() < 0.2);
        }
    }
}
