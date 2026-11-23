// The receivers' pressures after a step of the body solver (fdtd/head.rs): one thread per
// receiver, trilinear, into slot ctr[0] (head_bump.wgsl advances it afterwards).

struct Params {
    nx: u32,
    nxy: u32,
    n_mics: u32,
    pad: u32,
};

@group(0) @binding(0) var<uniform> P: Params;
@group(0) @binding(1) var<storage, read> mics: array<vec4<f32>>;
@group(0) @binding(2) var<storage, read> field: array<f32>;
@group(0) @binding(3) var<storage, read_write> out: array<f32>;
@group(0) @binding(4) var<storage, read_write> ctr: array<u32>;

fn at(i: u32, j: u32, k: u32) -> f32 {
    return field[i + P.nx * j + P.nxy * k];
}

@compute @workgroup_size(64)
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
    let m = gid.x;
    if (m >= P.n_mics) {
        return;
    }
    let q = mics[m];
    let x0 = floor(q.x);
    let y0 = floor(q.y);
    let z0 = floor(q.z);
    let fx = q.x - x0;
    let fy = q.y - y0;
    let fz = q.z - z0;
    let i = u32(x0);
    let j = u32(y0);
    let k = u32(z0);
    let c00 = at(i, j, k) * (1.0 - fx) + at(i + 1u, j, k) * fx;
    let c10 = at(i, j + 1u, k) * (1.0 - fx) + at(i + 1u, j + 1u, k) * fx;
    let c01 = at(i, j, k + 1u) * (1.0 - fx) + at(i + 1u, j, k + 1u) * fx;
    let c11 = at(i, j + 1u, k + 1u) * (1.0 - fx) + at(i + 1u, j + 1u, k + 1u) * fx;
    let c0 = c00 * (1.0 - fy) + c10 * fy;
    let c1 = c01 * (1.0 - fy) + c11 * fy;
    out[ctr[0] * P.n_mics + m] = c0 * (1.0 - fz) + c1 * fz;
}
