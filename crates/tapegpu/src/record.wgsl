// The tape medium's recording kernel in f32 (lib.rs; circuitsim's tape.rs `record` and
// reference.rs are the f64 references): one invocation per (cell, easy axis, layer), the
// corner formula's backward pass over the bias peaks in the cell's zone.

struct Params {
    cells: u32,
    n_axes: u32,
    n: u32,
    field_exact: u32,
    h_max: f32,
    inv_step: f32,
    big: f32,
    has_steady: u32,
    gap: f32,
    pole: f32,
    relax: f32,
    _pad: u32,
}

@group(0) @binding(0) var<uniform> P: Params;
// Q at the nodes ((n + 1)^2, row alpha major), then D (n + 1).
@group(0) @binding(1) var<storage, read> tabs: array<f32>;
// (cos, sin, 0, 0) per easy axis.
@group(0) @binding(2) var<storage, read> axes: array<vec4<f32>>;
// The cells' positions from the block's origin as (hi, lo): hi + lo is the f64 offset.
@group(0) @binding(3) var<storage, read> cell_s: array<vec2<f32>>;
// The zone's peaks [k0, k1) per layer and cell (layer major).
@group(0) @binding(4) var<storage, read> ranges: array<vec2<u32>>;
// Per bias peak: the gap's tape position (hi, lo) and the deep-gap field.
@group(0) @binding(5) var<storage, read> peaks: array<vec4<f32>>;
// Per layer and cell: the steady field through the pass (x, y) and after it (x, y).
@group(0) @binding(6) var<storage, read> steady: array<vec4<f32>>;
// Per layer: the field table's x0, 1 / dx, the layer's height y.
@group(0) @binding(7) var<storage, read> layer_info: array<vec4<f32>>;
// Per layer: the field table's first entry and length.
@group(0) @binding(8) var<storage, read> layer_tab: array<vec2<u32>>;
// The field tables' (Hx, Hy) / Hg, layer after layer.
@group(0) @binding(9) var<storage, read> field: array<vec2<f32>>;
// M / Ms per (layer, axis, cell): ((l * n_axes + a) * cells + c).
@group(0) @binding(10) var<storage, read_write> out: array<f32>;

const PI: f32 = 3.14159265358979;

fn catmull_rom(f: f32) -> vec4<f32> {
    let f2 = f * f;
    let f3 = f * f * f;
    return vec4<f32>(
        -0.5 * f3 + f2 - 0.5 * f,
        1.5 * f3 - 2.5 * f2 + 1.0,
        -1.5 * f3 + 2.0 * f2 + 0.5 * f,
        0.5 * f3 - 0.5 * f2,
    );
}

struct Node {
    i: u32,
    f: f32,
}

fn node(x: f32) -> Node {
    let h = P.h_max;
    let u = (clamp(x, -h, h) + h) * P.inv_step;
    let i = min(u32(max(floor(u), 0.0)), P.n - 1u);
    return Node(i, u - f32(i));
}

// The table's row (or column) for tap k of node i: (i + k) - 1, saturating at 0, at most n.
fn tap(i: u32, k: u32) -> u32 {
    return min(max(i + k, 1u) - 1u, P.n);
}

// Q(a, b) with b's columns and weights given.
fn q_at(a: f32, rb: vec4<u32>, wb: vec4<f32>) -> f32 {
    let na = node(a);
    let wa = catmull_rom(na.f);
    let m = P.n + 1u;
    var out = 0.0;
    for (var da = 0u; da < 4u; da++) {
        let r = tap(na.i, da) * m;
        let acc = wb.x * tabs[r + rb.x] + wb.y * tabs[r + rb.y] + wb.z * tabs[r + rb.z]
            + wb.w * tabs[r + rb.w];
        out += wa[da] * acc;
    }
    return out;
}

fn columns(ib: u32) -> vec4<u32> {
    return vec4<u32>(tap(ib, 0u), tap(ib, 1u), tap(ib, 2u), tap(ib, 3u));
}

// Q(a1, b) - Q(a0, b).
fn q_diff(a1: f32, a0: f32, b: f32) -> f32 {
    let nb = node(b);
    let wb = catmull_rom(nb.f);
    let rb = columns(nb.i);
    return q_at(a1, rb, wb) - q_at(a0, rb, wb);
}

fn q(a: f32, b: f32) -> f32 {
    let nb = node(b);
    return q_at(a, columns(nb.i), catmull_rom(nb.f));
}

fn d(x: f32) -> f32 {
    let nx = node(x);
    let w = catmull_rom(nx.f);
    let base = (P.n + 1u) * (P.n + 1u);
    var out = 0.0;
    for (var k = 0u; k < 4u; k++) {
        out += w[k] * tabs[base + tap(nx.i, k)];
    }
    return out;
}

// ln(z - a) - ln(z - b) for z = x + iy, y > 0.
fn log_ratio(x: f32, y: f32, a: f32, b: f32) -> vec2<f32> {
    let xa = x - a;
    let xb = x - b;
    let re = 0.5 * log((xa * xa + y * y) / (xb * xb + y * y));
    let im = atan2(y, xa) - atan2(y, xb);
    return vec2<f32>(re, im);
}

// (Hx, Hy) / Hg at (x, y): circuitsim's tape::head_field.
fn head_field(x: f32, y: f32) -> vec2<f32> {
    let g = P.gap;
    let e = g / 2.0 + P.pole;
    var acc = -log_ratio(x, y, -g / 2.0, g / 2.0);
    if (P.relax <= 0.0) {
        for (var s = 0u; s < 2u; s++) {
            let xe = select(e, -e, s == 0u);
            let dx = x - xe;
            let r2 = dx * dx + y * y;
            acc += vec2<f32>((g / 2.0) * dx / r2, -(g / 2.0) * y / r2);
        }
    } else {
        let c = g / 2.0 / P.relax;
        acc += c * log_ratio(x, y, -e - P.relax, -e);
        acc += c * log_ratio(x, y, e, e + P.relax);
    }
    return vec2<f32>(acc.y / PI, acc.x / PI);
}

fn table_field(l: u32, x: f32) -> vec2<f32> {
    let info = layer_info[l];
    let t = layer_tab[l];
    let u = (x - info.x) * info.y;
    let i = u32(clamp(floor(u), 1.0, f32(t.y - 3u)));
    let w = catmull_rom(u - f32(i));
    let o = t.x + i - 1u;
    return w.x * field[o] + w.y * field[o + 1u] + w.z * field[o + 2u] + w.w * field[o + 3u];
}

struct Corner {
    nmax: f32,
    nmin: f32,
    up: f32,
}

fn push(c: ptr<function, Corner>, x: f32) {
    if (x > (*c).nmax) {
        let b = min((*c).nmin, P.big);
        let a_next = max((*c).nmax, -P.big);
        (*c).up += q_diff(x, a_next, b);
    }
    (*c).nmax = max((*c).nmax, x);
    (*c).nmin = min((*c).nmin, x);
}

@compute @workgroup_size(64, 1, 1)
fn record(@builtin(global_invocation_id) gid: vec3<u32>) {
    let ci = gid.x;
    let a = gid.y;
    let l = gid.z;
    if (ci >= P.cells || a >= P.n_axes) {
        return;
    }
    let lc = l * P.cells + ci;
    let ax = axes[a];
    var st = vec4<f32>(0.0);
    if (P.has_steady != 0u) {
        st = steady[lc];
    }
    let hs = ax.x * st.x + ax.y * st.y;
    let he = ax.x * st.z + ax.y * st.w;
    // Below every field: the corner formula's "never reached" (f64's -inf / +inf).
    var c = Corner(-3.0e38, 3.0e38, 0.0);
    push(&c, he);
    push(&c, hs);
    let r = ranges[lc];
    let s = cell_s[ci];
    let y = layer_info[l].z;
    for (var j = r.y; j > r.x; j--) {
        let pk = peaks[j - 1u];
        // The cell's distance past the gap, exact to f32 (both hi and lo parts small).
        let x = (s.x - pk.x) + (s.y - pk.y);
        var f: vec2<f32>;
        if (P.field_exact != 0u) {
            f = head_field(x, y);
        } else {
            f = table_field(l, x);
        }
        let fx = pk.z * f.x;
        let fy = pk.z * f.y;
        push(&c, ax.x * fx + ax.y * fy + hs);
    }
    let top = c.nmax;
    let bot = c.nmin;
    let xm = max(top, -bot);
    c.up += q(xm, bot) - q(top, bot) + d(xm);
    out[(l * P.n_axes + a) * P.cells + ci] = 2.0 * c.up - 1.0;
}
