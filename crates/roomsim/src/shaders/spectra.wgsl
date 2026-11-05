// The image sources' spectra: the GPU half of spectra.rs (its docstring has the phase's
// exact reduction). One thread per frequency bin, looping over a batch of images and
// adding into `out`.

struct Params {
    n_img: u32,
    n_grid: u32,
    n_bins: u32,
    n_ent: u32,
    log2n: u32,
    img_offset: u32,
    n_img_batch: u32,
    pad: u32,
};

@group(0) @binding(0) var<uniform> P: Params;
@group(0) @binding(1) var<storage, read> coarse: array<vec2<f32>>;
@group(0) @binding(2) var<storage, read> delay: array<vec4<u32>>; // di, A, bits(b), 0
@group(0) @binding(3) var<storage, read> bins: array<vec2<u32>>; // g, bits(w)
@group(0) @binding(4) var<storage, read_write> out: array<vec2<f32>>;

const TAU: f32 = 6.283185307179586;

@compute @workgroup_size(64)
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
    let k = gid.x;
    if (k >= P.n_bins) {
        return;
    }
    let mask = (1u << P.log2n) - 1u;
    let inv_n = 1.0 / f32(1u << P.log2n);
    let bw = bins[k];
    let g = bw.x;
    let w = bitcast<f32>(bw.y);
    let fk = f32(k);
    var acc0 = vec2<f32>(0.0, 0.0);
    var acc1 = vec2<f32>(0.0, 0.0);
    for (var j = 0u; j < P.n_img_batch; j++) {
        let i = P.img_offset + j;
        let dl = delay[i];
        // k d mod N as an exact integer part and a small rest
        let int1 = (k * dl.x) & mask;
        let ka = k * dl.y;
        let int2 = (ka >> 12u) & mask;
        var rest = f32(ka & 4095u) * (1.0 / 4096.0) + fk * bitcast<f32>(dl.z);
        let whole = floor(rest);
        rest = rest - whole;
        let ii = (int1 + int2 + u32(whole)) & mask;
        let ang = -TAU * (f32(ii) * inv_n) - TAU * (rest * inv_n);
        let ph = vec2<f32>(cos(ang), sin(ang));
        let base = (i * P.n_ent) * P.n_grid + g;
        let s0 = coarse[base] * (1.0 - w) + coarse[base + 1u] * w;
        acc0 += vec2<f32>(s0.x * ph.x - s0.y * ph.y, s0.x * ph.y + s0.y * ph.x);
        if (P.n_ent > 1u) {
            let b1 = base + P.n_grid;
            let s1 = coarse[b1] * (1.0 - w) + coarse[b1 + 1u] * w;
            acc1 += vec2<f32>(s1.x * ph.x - s1.y * ph.y, s1.x * ph.y + s1.y * ph.x);
        }
    }
    out[k] += acc0;
    if (P.n_ent > 1u) {
        out[P.n_bins + k] += acc1;
    }
}
