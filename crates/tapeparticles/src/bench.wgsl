// The interacting-particle bench in f32 (bench.rs is the f64 reference, bench.py the
// Python one). Lengths in um, moments in Ms_p um^3, fields in A/m after the final scale.
// Three entry points per step: `field` (the interaction field from the moments after the
// last step, and the trace of the box's magnetization), `step` (the SW kinetic Monte
// Carlo step), `tick` (the step counter).

struct U {
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
    sd: vec4<f32>,
}

@group(0) @binding(0) var<uniform> u: U;
@group(0) @binding(1) var<storage, read> pos: array<vec4<f32>>;   // r.xyz, l
@group(0) @binding(2) var<storage, read> axis: array<vec4<f32>>;  // n.xyz, v
@group(0) @binding(3) var<storage, read> prm: array<vec4<f32>>;   // hk, e0_kt
@group(0) @binding(4) var<storage, read_write> state: array<f32>;
@group(0) @binding(5) var<storage, read_write> mom: array<vec4<f32>>;
@group(0) @binding(6) var<storage, read_write> hint: array<vec4<f32>>;
@group(0) @binding(7) var<storage, read_write> hfrozen: array<vec4<f32>>;
@group(0) @binding(8) var<storage, read> happ: array<vec4<f32>>;
@group(0) @binding(9) var<storage, read_write> trace: array<vec4<f32>>;
@group(0) @binding(10) var<storage, read_write> counter: array<u32>;

const PI: f32 = 3.14159265358979;
const FOUR_PI: f32 = 12.5663706143592;
const WG: u32 = 64u;

var<workgroup> t_ep: array<vec4<f32>, 64>;  // + end, q
var<workgroup> t_em: array<vec4<f32>, 64>;  // - end
var<workgroup> t_c: array<vec4<f32>, 64>;   // centre
var<workgroup> t_p: array<vec4<f32>, 64>;   // transverse dipole
var<workgroup> t_mu: array<vec4<f32>, 64>;  // the moment

fn wrap(d: vec3<f32>) -> vec3<f32> {
    return d - u.side * round(d / u.side);
}

@compute @workgroup_size(64)
fn field(@builtin(global_invocation_id) gid: vec3<u32>, @builtin(local_invocation_id) lid: vec3<u32>, @builtin(workgroup_id) wid: vec3<u32>) {
    let i = gid.x;
    let r = wid.y;
    let base = r * u.n;
    var rc = vec3<f32>(0.0);
    var na = vec3<f32>(0.0);
    var li = 0.0;
    if (i < u.n) {
        rc = pos[i].xyz;
        li = pos[i].w;
        na = axis[i].xyz;
    }
    var acc = vec3<f32>(0.0);
    var musum = vec3<f32>(0.0);
    let tiles = (u.n + WG - 1u) / WG;
    for (var t = 0u; t < tiles; t = t + 1u) {
        let j = t * WG + lid.x;
        if (j < u.n) {
            let ps = pos[j];
            let ax = axis[j];
            let mu = ax.w * mom[base + j].xyz;
            let a = dot(mu, ax.xyz);
            let q = a / ps.w;
            t_ep[lid.x] = vec4<f32>(ps.xyz + 0.5 * ps.w * ax.xyz, q);
            t_em[lid.x] = vec4<f32>(ps.xyz - 0.5 * ps.w * ax.xyz, -q);
            t_c[lid.x] = vec4<f32>(ps.xyz, 1.0);
            t_p[lid.x] = vec4<f32>(mu - a * ax.xyz, 0.0);
            t_mu[lid.x] = vec4<f32>(mu, 0.0);
        } else {
            t_ep[lid.x] = vec4<f32>(0.0);
            t_em[lid.x] = vec4<f32>(0.0);
            t_c[lid.x] = vec4<f32>(0.0);
            t_p[lid.x] = vec4<f32>(0.0);
            t_mu[lid.x] = vec4<f32>(0.0);
        }
        workgroupBarrier();
        let cnt = min(WG, u.n - t * WG);
        for (var k = 0u; k < cnt; k = k + 1u) {
            musum = musum + t_mu[k].xyz;
            if (t * WG + k == i) {
                continue;
            }
            let ep = t_ep[k];
            let em = t_em[k];
            let pc = t_c[k].xyz;
            let p = t_p[k].xyz;
            for (var o = 0u; o < u.tp; o = o + 1u) {
                let off = (f32(o) + 0.5) / f32(u.tp) - 0.5;
                let ri = rc + off * li * na;
                var d = wrap(ri - ep.xyz);
                var r2 = dot(d, d) + u.a2;
                acc = acc + ep.w / (FOUR_PI * r2 * sqrt(r2)) * d;
                d = wrap(ri - em.xyz);
                r2 = dot(d, d) + u.a2;
                acc = acc + em.w / (FOUR_PI * r2 * sqrt(r2)) * d;
                d = wrap(ri - pc);
                r2 = dot(d, d) + u.a2;
                let inv = 1.0 / (FOUR_PI * r2 * sqrt(r2));
                acc = acc + inv * (3.0 * dot(p, d) / r2 * d - p);
            }
        }
        workgroupBarrier();
    }
    let mbar = musum / u.vol;
    let mf = mbar / 3.0 - u.sd.xyz * mbar;
    let c = counter[0];
    if (i == 0u) {
        trace[c * u.reps + r] = vec4<f32>(musum / u.vsum, 0.0);
    }
    if (i < u.n) {
        let h = u.ms_p * (acc / f32(u.tp) + mf);
        hint[base + i] = vec4<f32>(h, 0.0);
        if (c == 0u) {
            hfrozen[base + i] = vec4<f32>(h, 0.0);
        }
    }
}

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

@compute @workgroup_size(64)
fn step(@builtin(global_invocation_id) gid: vec3<u32>, @builtin(workgroup_id) wid: vec3<u32>) {
    let i = gid.x;
    let r = wid.y;
    if (i >= u.n) {
        return;
    }
    let j = counter[0];
    let base = r * u.n;
    var hi = vec3<f32>(0.0);
    if (u.mode == 0u) {
        hi = hint[base + i].xyz;
    } else if (u.mode == 1u) {
        hi = hfrozen[base + i].xyz;
    }
    let pr = prm[i];
    let n = axis[i].xyz;
    let h = (happ[j * u.reps + r].xyz + u.scale * hi) / pr.x;
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
    // The grid's sign changes of e'.
    let g = u.grid;
    let stp = PI / f32(g - 1u);
    var first_rise = 0xFFFFFFFFu;
    var last_rise = 0xFFFFFFFFu;
    var first_fall = 0xFFFFFFFFu;
    var nrise = 0u;
    var prev = (0.0 + a * 0.0 - bb * 1.0) > 0.0;
    for (var k = 1u; k < g; k = k + 1u) {
        let th = stp * f32(k);
        var s = sin(th);
        var c = cos(th);
        if (k == g - 1u) {
            // The end exactly (f32's pi isn't: sin would be ~1e-7 either side).
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
        let rp = u.f0 * exp(-min(dp * pr.y, 80.0));
        let rm = u.f0 * exp(-min(dm * pr.y, 80.0));
        let gg = u.dt * phi((rp + rm) * u.dt);
        qp = clamp(rp * gg, 0.0, 1.0);
        qm = clamp(rm * gg, 0.0, 1.0);
    } else if (a >= 0.0) {
        qm = 1.0;
    } else {
        qp = 1.0;
    }
    var p = state[base + i];
    let x = hash_uniform(u.seed, i, j);
    var flip = false;
    if (p > 0.5) {
        flip = x < qp;
    } else {
        flip = x < qm;
    }
    if (flip) {
        p = 1.0 - p;
    }
    state[base + i] = p;
    let mp = cos(t1) * n + sin(t1) * uu;
    let mm = cos(t2) * n + sin(t2) * uu;
    mom[base + i] = vec4<f32>(p * mp + (1.0 - p) * mm, 0.0);
}

@compute @workgroup_size(1)
fn tick() {
    counter[0] = counter[0] + 1u;
}
