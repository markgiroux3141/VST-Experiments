// One step of the wave solver: the GPU half of fdtd/mod.rs (its docstring has the scheme).
// `nxt` holds p^{n-1} on entry and p^{n+1} on exit; cells outside the room are never written
// (they stay 0).

struct Params {
    nx: u32,
    nxy: u32,
    n: u32,
    row: u32,
    l2: f32,
    pad0: u32,
    pad1: u32,
    pad2: u32,
};

@group(0) @binding(0) var<uniform> P: Params;
@group(0) @binding(1) var<storage, read> codes: array<u32>;
@group(0) @binding(2) var<storage, read> bnd: array<vec2<f32>>; // K, g
@group(0) @binding(3) var<storage, read> cur: array<f32>;
@group(0) @binding(4) var<storage, read_write> nxt: array<f32>;

@compute @workgroup_size(256)
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
    let i = gid.x + gid.y * P.row;
    if (i >= P.n) {
        return;
    }
    let code = codes[i];
    if (code == 0u) {
        return;
    }
    let nsum = cur[i - 1u] + cur[i + 1u] + cur[i - P.nx] + cur[i + P.nx] + cur[i - P.nxy]
        + cur[i + P.nxy];
    let p = cur[i];
    if (code == 1u) {
        nxt[i] = (2.0 - 6.0 * P.l2) * p + P.l2 * nsum - nxt[i];
    } else {
        let b = bnd[code - 2u];
        nxt[i] = ((2.0 - P.l2 * b.x) * p + P.l2 * nsum - (1.0 - b.y) * nxt[i]) / (1.0 + b.y);
    }
}
