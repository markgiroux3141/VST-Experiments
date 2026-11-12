// The moving head on non-interacting particles (head.rs's `run_cpu_head` is the f64
// reference, varimu/tape_particles/strip.py the Python one). A replica is one cell of the
// coating (an x cell and a layer); every replica holds the same particle sample. Step j of
// replica r: the deep-gap field Hg = sign a sin(2 pi phi_s) + B sin(2 pi phi_b), phi_s =
// phi_s0(r) + j fs_dt, phi_b = phi_b0(r) + j / m, times the layer's head factors tab[j, l],
// plus the replica's static field hs (the coating's demagnetization with the head's image);
// past the pass's S steps, the free demagnetizing field he alone. Each thread runs its
// particle in its replica through the steps [j0, j1); `reduce` sums a replica's moments.
// The SW step is bench.wgsl's (the same code; bench.rs / sw.rs the reference).

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
    coupled: u32,
    ms_local: f32,
    pad2: u32,
}

@group(0) @binding(0) var<uniform> u: U;
@group(0) @binding(1) var<storage, read> axis: array<vec4<f32>>;  // n.xyz, v
@group(0) @binding(2) var<storage, read> prm: array<vec4<f32>>;   // hk, e0_kt
@group(0) @binding(3) var<storage, read_write> state: array<f32>;
@group(0) @binding(4) var<storage, read_write> mom: array<vec4<f32>>;
@group(0) @binding(5) var<storage, read> tab: array<vec4<f32>>;   // fx, fy per (step, layer)
@group(0) @binding(6) var<storage, read> repc: array<vec4<f32>>;  // (phi_b0, phi_s0, hsx, hsy), (hex, hey, sign, 0)
@group(0) @binding(7) var<storage, read_write> outm: array<vec4<f32>>;

const PI: f32 = 3.14159265358979;
const TWO_PI: f32 = 6.28318530717959;
const NBISECT: u32 = 14u;

fn fp(t: f32, a: f32, b: f32) -> vec2<f32> {
    let s = sin(t);
    let c = cos(t);
    return vec2<f32>(s * c + a * s - b * c, (c * c - s * s) + a * c + b * s);
}

fn energy(t: f32, a: f32, b: f32) -> f32 {
    let s = sin(t);
    let c = cos(t);
    return 0.5 * s * s - a * c - b * s;
}

fn refine(lo0: f32, hi0: f32, a: f32, b: f32) -> f32 {
    var lo = lo0;
    var hi = hi0;
    var flo = fp(lo, a, b).x;
    var t = 0.5 * (lo + hi);
    for (var k = 0u; k < u.iters; k = k + 1u) {
        let fd = fp(t, a, b);
        if (sign(fd.x) == sign(flo)) {
            lo = t;
            flo = fd.x;
        } else {
            hi = t;
        }
        let tn = t - fd.x / fd.y;
        if (!(tn > lo && tn < hi)) {
            t = 0.5 * (lo + hi);
        } else {
            t = tn;
        }
    }
    return t;
}

fn hash_uniform(seed: u32, idx: u32, step: u32) -> f32 {
    var x = idx * 0x9E3779B1u;
    x = x ^ (seed * 0x85EBCA77u + step * 0xC2B2AE3Du);
    for (var k = 0; k < 2; k = k + 1) {
        x = x ^ (x >> 16u);
        x = x * 0x7FEB352Du;
        x = x ^ (x >> 15u);
        x = x * 0x846CA68Bu;
        x = x ^ (x >> 16u);
    }
    return f32(x >> 8u) / 16777216.0;
}

fn phi(x: f32) -> f32 {
    if (x < 1e-3) {
        return 1.0 - 0.5 * x + x * x / 6.0;
    }
    return (1.0 - exp(-x)) / x;
}

// One SW step: (the new p, the moment).
fn sw_step(n: vec3<f32>, hk: f32, e0: f32, hraw: vec3<f32>, p0: f32, uu_rand: f32) -> vec4<f32> {
    let h = hraw / hk;
    let a = dot(h, n);
    let perp = h - a * n;
    let b = length(perp);
    var uu: vec3<f32>;
    if (b < 1e-6) {
        var alt = vec3<f32>(0.0, 1.0, 0.0);
        if (abs(n.x) < 0.9) {
            alt = vec3<f32>(1.0, 0.0, 0.0);
        }
        uu = normalize(cross(n, alt));
    } else {
        uu = perp / b;
    }
    let bb = max(b, 1e-6);
    let g = u.grid;
    let stp = PI / f32(g - 1u);
    var first_rise = 0xFFFFFFFFu;
    var last_rise = 0xFFFFFFFFu;
    var first_fall = 0xFFFFFFFFu;
    var nrise = 0u;
    var prev = (-bb) > 0.0;
    for (var k = 1u; k < g; k = k + 1u) {
        let th = stp * f32(k);
        var s = sin(th);
        var c = cos(th);
        if (k == g - 1u) {
            s = 0.0;
            c = -1.0;
        }
        let pos_ = (s * c + a * s - bb * c) > 0.0;
        if (!prev && pos_) {
            nrise = nrise + 1u;
            if (first_rise == 0xFFFFFFFFu) {
                first_rise = k - 1u;
            }
            last_rise = k - 1u;
        }
        if (prev && !pos_ && first_fall == 0xFFFFFFFFu) {
            first_fall = k - 1u;
        }
        prev = pos_;
    }
    var fr = first_rise;
    if (fr == 0xFFFFFFFFu) {
        fr = 0u;
    }
    let two = nrise >= 2u && first_fall != 0xFFFFFFFFu;
    let t1 = refine(stp * f32(fr), stp * f32(fr) + stp, a, bb);
    var t2 = t1;
    var qp = 0.0;
    var qm = 0.0;
    if (two) {
        t2 = refine(stp * f32(last_rise), stp * f32(last_rise) + stp, a, bb);
        let ts = refine(stp * f32(first_fall), stp * f32(first_fall) + stp, a, bb);
        let es = energy(ts, a, bb);
        let dp = max(es - energy(t1, a, bb), 0.0);
        let dm = max(es - energy(t2, a, bb), 0.0);
        let rp = u.f0 * exp(-min(dp * e0, 80.0));
        let rm = u.f0 * exp(-min(dm * e0, 80.0));
        let gg = u.dt * phi((rp + rm) * u.dt);
        qp = clamp(rp * gg, 0.0, 1.0);
        qm = clamp(rm * gg, 0.0, 1.0);
    } else if (a >= 0.0) {
        qm = 1.0;
    } else {
        qp = 1.0;
    }
    var p = p0;
    if (u.stochastic == 1u) {
        var flip = false;
        if (p > 0.5) {
            flip = uu_rand < qp;
        } else {
            flip = uu_rand < qm;
        }
        if (flip) {
            p = 1.0 - p;
        }
    } else {
        p = p * (1.0 - qp) + (1.0 - p) * qm;
    }
    let mp = cos(t1) * n + sin(t1) * uu;
    let mm = cos(t2) * n + sin(t2) * uu;
    let m = p * mp + (1.0 - p) * mm;
    return vec4<f32>(m, p);
}

@compute @workgroup_size(64)
fn step_head(@builtin(global_invocation_id) gid: vec3<u32>, @builtin(workgroup_id) wid: vec3<u32>) {
    let i = gid.x;
    let r = wid.y + wid.z * 65535u;
    if (i >= u.n || r >= u.reps) {
        return;
    }
    let base = r * u.n;
    let l = r % u.layers;
    let c0 = repc[2u * r];
    let c1 = repc[2u * r + 1u];
    let ax = axis[i];
    let pr = prm[i];
    var p = state[base + i];
    var m = mom[base + i];
    for (var k = u.j0; k < u.j1; k = k + 1u) {
        // Coupled: k is absolute, the replica's own step k - k0 (it enters the zone at k0).
        var jj = i32(k);
        if (u.coupled == 1u) {
            jj = i32(k) - i32(c1.w);
        }
        var h = vec3<f32>(c1.x, c1.y, 0.0);
        if (jj >= 0 && u32(jj) < u.s_steps) {
            let j = u32(jj);
            let f = tab[j * u.layers + l];
            let pb = fract(c0.x + f32(j) * u.inv_m);
            let ps = fract(c0.y + f32(j) * u.fs_dt);
            let hg = c1.z * u.a_sig * sin(TWO_PI * ps) + u.bias * sin(TWO_PI * pb);
            h = vec3<f32>(hg * f.x + c0.z, hg * f.y + c0.w, 0.0);
        }
        let rnd = hash_uniform(u.seed, base + i, k);
        let o = sw_step(ax.xyz, pr.x, pr.y, h, p, rnd);
        p = o.w;
        m = vec4<f32>(o.xyz, 0.0);
    }
    state[base + i] = p;
    mom[base + i] = m;
}

@compute @workgroup_size(64)
fn reduce(@builtin(global_invocation_id) gid: vec3<u32>) {
    let r = gid.x;
    if (r >= u.reps) {
        return;
    }
    var s = vec3<f32>(0.0);
    for (var i = 0u; i < u.n; i = i + 1u) {
        s = s + axis[i].w * mom[r * u.n + i].xyz;
    }
    outm[r] = vec4<f32>(s / u.vsum, outm[r].w);
}

// The cell's own perpendicular demagnetization, -Ms_coat M_y (a layer of uniform M_y: the
// field inside is -M_y, the long-wavelength limit), implicit in each step (explicit, a step
// late, it flips the cell every step: the feedback's gain is Ms_coat / H_K ~ 2) on the replica (a workgroup: its particles are the threads, n <= 256). The replica's M_y
// persists in outm[r].w between dispatches. Otherwise step_head's pass.
var<workgroup> red: array<f32, 256>;

@compute @workgroup_size(256)
fn step_local(@builtin(local_invocation_id) lid: vec3<u32>, @builtin(workgroup_id) wid: vec3<u32>) {
    let i = lid.x;
    let r = wid.x + wid.y * 65535u;
    if (r >= u.reps) {
        return;
    }
    let valid = i < u.n;
    let base = r * u.n;
    let l = r % u.layers;
    let c0 = repc[2u * r];
    let c1 = repc[2u * r + 1u];
    var ax = vec4<f32>(1.0, 0.0, 0.0, 0.0);
    var pr = vec4<f32>(1.0, 0.0, 0.0, 0.0);
    var p = 0.5;
    var m = vec4<f32>(0.0);
    if (valid) {
        ax = axis[i];
        pr = prm[i];
        p = state[base + i];
        m = mom[base + i];
    }
    var my = outm[r].w;
    for (var k = u.j0; k < u.j1; k = k + 1u) {
        var h = vec3<f32>(c1.x, c1.y, 0.0);
        if (k < u.s_steps) {
            let f = tab[k * u.layers + l];
            let pb = fract(c0.x + f32(k) * u.inv_m);
            let ps = fract(c0.y + f32(k) * u.fs_dt);
            let hg = c1.z * u.a_sig * sin(TWO_PI * ps) + u.bias * sin(TWO_PI * pb);
            h = vec3<f32>(hg * f.x + c0.z, hg * f.y + c0.w, 0.0);
        }
        // Implicit: the cell's M_y after this step, mu, solves mu = F(h - Ms mu) (F the
        // particles' M_y after a step in that field; F falls as mu rises), by bisection.
        let rnd = hash_uniform(u.seed, base + i, k);
        var lo = -1.0;
        var hi = 1.0;
        for (var it = 0u; it < NBISECT; it = it + 1u) {
            let mu = 0.5 * (lo + hi);
            if (valid) {
                let o = sw_step(ax.xyz, pr.x, pr.y, h - vec3<f32>(0.0, u.ms_local * mu, 0.0), p, rnd);
                red[i] = ax.w * o.y;
            } else {
                red[i] = 0.0;
            }
            workgroupBarrier();
            for (var st = 128u; st > 0u; st = st >> 1u) {
                if (i < st) {
                    red[i] = red[i] + red[i + st];
                }
                workgroupBarrier();
            }
            let fm = red[0] / u.vsum;
            workgroupBarrier();
            if (fm > mu) {
                lo = mu;
            } else {
                hi = mu;
            }
        }
        my = 0.5 * (lo + hi);
        if (valid) {
            let o = sw_step(ax.xyz, pr.x, pr.y, h - vec3<f32>(0.0, u.ms_local * my, 0.0), p, rnd);
            p = o.w;
            m = vec4<f32>(o.xyz, 0.0);
        }
    }
    if (valid) {
        state[base + i] = p;
        mom[base + i] = m;
    }
    if (i == 0u) {
        outm[r].w = my;
    }
}
