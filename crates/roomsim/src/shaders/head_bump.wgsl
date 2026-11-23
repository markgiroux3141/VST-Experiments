// Advances the body solver's record slot after its receivers are read (fdtd/head.rs).

@group(0) @binding(0) var<storage, read_write> ctr: array<u32>;

@compute @workgroup_size(1)
fn main() {
    ctr[0] = ctr[0] + 1u;
}
