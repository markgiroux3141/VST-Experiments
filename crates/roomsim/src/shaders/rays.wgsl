// Ray tracing for a room's energy decay: the GPU half of rays.rs (its docstring). One
// thread per ray; the records are summed in 64-bit fixed point (2^-40) as pairs of u32
// (low, high) with integer atomics, so the sums don't depend on the threads' order.

struct Params {
    src: vec4<f32>,
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
};

struct Tri {
    v0: vec4<f32>, // w: the face
    e1: vec4<f32>,
    e2: vec4<f32>,
};

struct Face {
    n: vec4<f32>, // w: scattering
    a0: vec4<f32>,
    a1: vec4<f32>,
};

@group(0) @binding(0) var<uniform> P: Params;
@group(0) @binding(1) var<storage, read> tris: array<Tri>;
@group(0) @binding(2) var<storage, read> faces: array<Face>;
@group(0) @binding(3) var<storage, read> dirs: array<vec4<f32>>;
@group(0) @binding(4) var<storage, read> rx: array<vec4<f32>>;
@group(0) @binding(5) var<storage, read_write> acc: array<atomic<u32>>;
@group(0) @binding(6) var<storage, read_write> dens: array<atomic<u32>>;

const NB: u32 = 7u;
const EPS_BARY: f32 = 1e-5;
const OFFSET_M: f32 = 1e-5;
const TAU: f32 = 6.283185307179586;

fn pcg(v: u32) -> u32 {
    let state = v * 747796405u + 2891336453u;
    let word = ((state >> ((state >> 28u) + 4u)) ^ state) * 277803737u;
    return (word >> 22u) ^ word;
}

fn rnd(ray: u32, bounce: u32, k: u32) -> f32 {
    let h = pcg(P.seed ^ pcg(ray ^ pcg(bounce * 4u + k)));
    return f32(h >> 8u) * (1.0 / 16777216.0);
}

// v (>= 0, < 2^23) as hi = floor(v 2^8), lo = frac 2^32: the value times 2^40.
fn split(v: f32) -> vec2<u32> {
    let x = v * 256.0;
    let fl = floor(x);
    let lo = u32(min((x - fl) * 4294967296.0, 4294967295.0));
    return vec2<u32>(lo, u32(fl));
}

fn add_acc(i: u32, v: f32) {
    let s = split(v);
    let old = atomicAdd(&acc[2u * i], s.x);
    let carry = select(0u, 1u, old > 0xFFFFFFFFu - s.x);
    if (s.y + carry > 0u) {
        atomicAdd(&acc[2u * i + 1u], s.y + carry);
    }
}

fn add_dens(i: u32, v: f32) {
    let s = split(v);
    let old = atomicAdd(&dens[2u * i], s.x);
    let carry = select(0u, 1u, old > 0xFFFFFFFFu - s.x);
    if (s.y + carry > 0u) {
        atomicAdd(&dens[2u * i + 1u], s.y + carry);
    }
}

fn alpha(f: Face, b: u32) -> f32 {
    if (b < 4u) {
        return f.a0[b];
    }
    return f.a1[b - 4u];
}

@compute @workgroup_size(64)
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
    if (gid.x >= P.n_batch) {
        return;
    }
    let ray = P.ray_offset + gid.x;
    var p = P.src.xyz;
    var d = dirs[ray].xyz;
    var e: array<f32, 7>;
    for (var b = 0u; b < NB; b++) {
        e[b] = 1.0;
    }
    var t = 0.0;
    let nt = P.nt;
    let fs = P.fs_env;
    let c = P.c;
    for (var bounce = 0u; bounce < P.max_bounces; bounce++) {
        // the nearest triangle ahead whose face is approached from inside
        var best = 3.0e38;
        var bf = -1;
        for (var i = 0u; i < P.n_tris; i++) {
            let tr = tris[i];
            let fi = u32(tr.v0.w);
            let n = faces[fi].n.xyz;
            if (dot(d, n) >= -1e-9) {
                continue;
            }
            let pv = cross(d, tr.e2.xyz);
            let det = dot(tr.e1.xyz, pv);
            if (abs(det) < 1e-12) {
                continue;
            }
            let inv = 1.0 / det;
            let tv = p - tr.v0.xyz;
            let u = dot(tv, pv) * inv;
            if (u < -EPS_BARY || u > 1.0 + EPS_BARY) {
                continue;
            }
            let qv = cross(tv, tr.e1.xyz);
            let v = dot(d, qv) * inv;
            if (v < -EPS_BARY || u + v > 1.0 + EPS_BARY) {
                continue;
            }
            let tt = dot(tr.e2.xyz, qv) * inv;
            if (tt > 1e-6 && tt < best) {
                best = tt;
                bf = i32(fi);
            }
        }
        if (bf < 0) {
            break; // a numerical escape: the ray's energy leaves now
        }
        let t1 = t + best / c;
        // still travelling at the instants (k + 1) / fs in [t, t1)
        let k_lo = u32(max(ceil(t * fs - 1.0), 0.0));
        let k_hi = min(u32(max(ceil(t1 * fs - 1.0), 0.0)), nt);
        for (var k = k_lo; k < k_hi; k++) {
            for (var b = 0u; b < NB; b++) {
                add_acc(b * nt + k, e[b]);
            }
        }
        let r2 = P.radius * P.radius;
        for (var ri = 0u; ri < P.n_rx; ri++) {
            let v = rx[ri].xyz - p;
            let proj = dot(v, d);
            let d2 = dot(v, v) - proj * proj;
            if (d2 >= r2) {
                continue;
            }
            let half = sqrt(max(r2 - d2, 0.0));
            let s0 = clamp(proj - half, 0.0, best);
            let s1 = clamp(proj + half, 0.0, best);
            let ln = s1 - s0;
            if (ln <= 0.0) {
                continue;
            }
            let k = u32((t + 0.5 * (s0 + s1) / c) * fs);
            if (k < nt) {
                for (var b = 0u; b < NB; b++) {
                    add_dens((ri * NB + b) * nt + k, e[b] * ln / c);
                }
            }
        }
        p = p + best * d;
        t = t1;
        if (t >= P.t_max) {
            break;
        }
        let f = faces[u32(bf)];
        var emax = 0.0;
        for (var b = 0u; b < NB; b++) {
            e[b] = e[b] * (1.0 - alpha(f, b));
            emax = max(emax, e[b]);
        }
        let n = f.n.xyz;
        if (rnd(ray, bounce, 0u) < f.n.w) {
            let z = 2.0 * rnd(ray, bounce, 1u) - 1.0;
            let phi = TAU * rnd(ray, bounce, 2u);
            let s = sqrt(max(1.0 - z * z, 0.0));
            var v = vec3<f32>(s * cos(phi), s * sin(phi), z);
            if (dot(v, n) < 0.0) {
                v = -v;
            }
            d = normalize(n + v);
        } else {
            d = d - 2.0 * dot(d, n) * n;
        }
        p = p + OFFSET_M * n;
        if (emax < 1e-7) {
            break;
        }
    }
}
