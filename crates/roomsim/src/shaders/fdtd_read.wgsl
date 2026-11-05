// The mics' records after a step of the wave solver (fdtd/mod.rs): one thread, every mic's
// pressure and gradient from the newest field into slot `ctr`, then ctr += 1.

struct Params {
    nx: u32,
    nxy: u32,
    n_mics: u32,
    pad: u32,
};

@group(0) @binding(0) var<uniform> P: Params;
@group(0) @binding(1) var<storage, read> mics: array<vec4<f32>>;
@group(0) @binding(2) var<storage, read> field: array<f32>;
@group(0) @binding(3) var<storage, read_write> out: array<vec4<f32>>;
@group(0) @binding(4) var<storage, read_write> ctr: array<u32>;

fn at(i: u32, j: u32, k: u32) -> f32 {
    return field[i + P.nx * j + P.nxy * k];
}

fn tri(x: f32, y: f32, z: f32) -> f32 {
    let x0 = floor(x);
    let y0 = floor(y);
    let z0 = floor(z);
    let fx = x - x0;
    let fy = y - y0;
    let fz = z - z0;
    let i = u32(x0);
    let j = u32(y0);
    let k = u32(z0);
    let c00 = at(i, j, k) * (1.0 - fx) + at(i + 1u, j, k) * fx;
    let c10 = at(i, j + 1u, k) * (1.0 - fx) + at(i + 1u, j + 1u, k) * fx;
    let c01 = at(i, j, k + 1u) * (1.0 - fx) + at(i + 1u, j, k + 1u) * fx;
    let c11 = at(i, j + 1u, k + 1u) * (1.0 - fx) + at(i + 1u, j + 1u, k + 1u) * fx;
    let c0 = c00 * (1.0 - fy) + c10 * fy;
    let c1 = c01 * (1.0 - fy) + c11 * fy;
    return c0 * (1.0 - fz) + c1 * fz;
}

@compute @workgroup_size(1)
fn main() {
    let slot = ctr[0];
    for (var m = 0u; m < P.n_mics; m++) {
        let q = mics[m];
        let x = q.x;
        let y = q.y;
        let z = q.z;
        out[slot * P.n_mics + m] = vec4<f32>(
            tri(x, y, z),
            0.5 * (tri(x + 1.0, y, z) - tri(x - 1.0, y, z)),
            0.5 * (tri(x, y + 1.0, z) - tri(x, y - 1.0, z)),
            0.5 * (tri(x, y, z + 1.0) - tri(x, y, z - 1.0)),
        );
    }
    ctr[0] = slot + 1u;
}
