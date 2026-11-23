// One step of the body-in-free-field solver: the GPU half of fdtd/head.rs (its docstring has
// the scheme). `nxt` holds p^{n-1} on entry and p^{n+1} on exit; solid cells are never written.

struct Params {
    nx: u32,
    ny: u32,
    nz: u32,
    nxy: u32,
    n: u32,
    row: u32,
    sponge: u32,
    pad0: u32,
    l2: f32,
    g_max: f32,
    pad1: u32,
    pad2: u32,
};

@group(0) @binding(0) var<uniform> P: Params;
@group(0) @binding(1) var<storage, read> codes: array<u32>; // one byte a cell, four a word
@group(0) @binding(2) var<storage, read> cur: array<f32>;
@group(0) @binding(3) var<storage, read_write> nxt: array<f32>;

fn sponge_g(idx: u32) -> f32 {
    if (P.sponge == 0u) {
        return 0.0;
    }
    let i = idx % P.nx;
    let j = (idx / P.nx) % P.ny;
    let k = idx / P.nxy;
    let near = min(min(min(i, j), min(k, P.nx - 1u - i)), min(P.ny - 1u - j, P.nz - 1u - k));
    if (near >= P.sponge) {
        return 0.0;
    }
    let x = f32(P.sponge - near) / f32(P.sponge);
    return P.g_max * x * x;
}

@compute @workgroup_size(256)
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
    let i = gid.x + gid.y * P.row;
    if (i >= P.n) {
        return;
    }
    let k = (codes[i >> 2u] >> ((i & 3u) * 8u)) & 0xffu;
    if (k == 0u) {
        return;
    }
    let nsum = cur[i - 1u] + cur[i + 1u] + cur[i - P.nx] + cur[i + P.nx] + cur[i - P.nxy]
        + cur[i + P.nxy];
    let g = sponge_g(i);
    nxt[i] = ((2.0 - P.l2 * f32(k)) * cur[i] + P.l2 * nsum - (1.0 - g) * nxt[i]) / (1.0 + g);
}
