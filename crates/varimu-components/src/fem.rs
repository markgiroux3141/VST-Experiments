//! A 2D magnetostatic field solution of the winding window: the leakage formulas' check
//! (docs/COMPONENT_EDITOR_PLAN.md C2 step 4, the user's choice of an own solver over FEMM).
//!
//! The window's cross-section (r across it from the wound leg, z along the leg from the
//! lower yoke) with the iron around it taken as infinitely permeable: its tangential H is
//! zero, so the vector potential A_z has a natural (Neumann) boundary on all four sides,
//! one node held at 0 (the field is unchanged; the problem is consistent because the
//! window's ampere-turns balance). Leakage is a linear field problem:
//!
//!   -div (1/mu0 grad A) = J,
//!
//! J the ampere-turns of each copper rectangle spread over it. Linear (P1) triangles on a
//! tensor grid with a line at every copper edge (two triangles per cell), solved by
//! conjugate gradients with a Jacobi preconditioner. The field energy is weighted by the
//! turn length at each radius, as the 1D model weights it ([`Layout::turn`]): planar in the
//! window, the whole turn's length (the usual 2D treatment of a transformer's leakage).
//! L = 2 W / I^2.
//!
//! The copper: a layer winding's layers are rectangles of the equal-area copper thickness
//! (as [`crate::geometry`] lays them out) and the layer's length; a disc winding's sections
//! are rectangles of their full width and build, the turns spread evenly (a wild-wound or
//! multilayer disc).

use circuitsim::devices::core::MU0;

use crate::design::Arrangement;
use crate::geometry::Layout;
use crate::leakage;

/// A copper rectangle: r0..r1 across the window, z0..z1 along it (from the lower yoke),
/// carrying `turns` of a winding.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct Block {
    pub winding: usize,
    pub turns: f64,
    pub r0: f64,
    pub r1: f64,
    pub z0: f64,
    pub z1: f64,
}

/// The window and its copper, from a layout.
#[derive(Debug, Clone)]
pub struct Window {
    pub width: f64,
    pub height: f64,
    pub blocks: Vec<Block>,
}

impl Window {
    /// `z_offset`: the traverse's start above the lower yoke (cheek plus margin).
    pub fn from_layout(layout: &Layout, z_offset: f64) -> Window {
        let mut blocks = Vec::new();
        match layout.arrangement {
            Arrangement::Layer => {
                // A layer's copper: the slab carrying its turns (the equal-area square,
                // centred in the layer), along the layer's length.
                let copper: Vec<_> = layout
                    .slabs
                    .iter()
                    .filter(|s| s.winding.is_some())
                    .collect();
                for (l, s) in layout.layers.iter().zip(copper) {
                    blocks.push(Block {
                        winding: l.winding,
                        turns: l.turns,
                        r0: s.x0_m,
                        r1: s.x1_m,
                        z0: z_offset + l.z0_m,
                        z1: z_offset + l.z1_m,
                    });
                }
            }
            Arrangement::Disc => {
                // A section: its layers' radial span, its width, all its turns.
                let mut by_section: Vec<(usize, Block)> = Vec::new();
                for l in &layout.layers {
                    match by_section.iter_mut().find(|(s, _)| *s == l.section) {
                        Some((_, b)) => {
                            b.turns += l.turns;
                            b.r0 = b.r0.min(l.r0_m);
                            b.r1 = b.r1.max(l.r1_m);
                        }
                        None => by_section.push((
                            l.section,
                            Block {
                                winding: l.winding,
                                turns: l.turns,
                                r0: l.r0_m,
                                r1: l.r1_m,
                                z0: z_offset + l.z0_m,
                                z1: z_offset + l.z1_m,
                            },
                        )),
                    }
                }
                blocks = by_section.into_iter().map(|(_, b)| b).collect();
            }
        }
        Window {
            width: layout.window_width_m,
            height: layout.window_height_m,
            blocks,
        }
    }
}

/// Grid lines through `fixed` (sorted, deduplicated), every interval split into equal
/// cells no longer than `h`, and at least `min_cells` cells across every interval.
fn grid(mut fixed: Vec<f64>, h: f64, min_cells: usize) -> Vec<f64> {
    fixed.sort_by(f64::total_cmp);
    fixed.dedup_by(|a, b| (*a - *b).abs() < 1e-12);
    let mut out = vec![fixed[0]];
    for w in fixed.windows(2) {
        let n = (((w[1] - w[0]) / h).ceil() as usize).max(min_cells);
        for i in 1..=n {
            out.push(w[0] + (w[1] - w[0]) * i as f64 / n as f64);
        }
    }
    out
}

/// The field solution of one excitation.
pub struct Field {
    pub r: Vec<f64>,
    pub z: Vec<f64>,
    /// A_z at the grid nodes, r fastest.
    pub a: Vec<f64>,
    /// The turn-length-weighted field energy (J).
    pub energy_j: f64,
    pub cg_iterations: usize,
}

/// Mesh fineness: the longest cell (a fraction of the window's smaller side) and the
/// fewest cells across any interval between copper edges.
#[derive(Debug, Clone, Copy)]
pub struct Mesh {
    pub cells_per_side: f64,
    pub min_cells: usize,
}

impl Default for Mesh {
    fn default() -> Self {
        Mesh {
            cells_per_side: 160.0,
            min_cells: 2,
        }
    }
}

/// Solves the window for the ampere-turns `amps[k]` x turns of winding k's blocks,
/// weighting the energy by `turn(r)`.
pub fn solve(win: &Window, amps: &[f64], turn: impl Fn(f64) -> f64, mesh: Mesh) -> Field {
    let h = win.width.min(win.height) / mesh.cells_per_side;
    let mut rs = vec![0.0, win.width];
    let mut zs = vec![0.0, win.height];
    for b in &win.blocks {
        rs.extend([b.r0.clamp(0.0, win.width), b.r1.clamp(0.0, win.width)]);
        zs.extend([b.z0.clamp(0.0, win.height), b.z1.clamp(0.0, win.height)]);
    }
    let r = grid(rs, h, mesh.min_cells);
    let z = grid(zs, h, mesh.min_cells);
    let (nr, nz) = (r.len(), z.len());
    let n = nr * nz;
    let id = |i: usize, j: usize| j * nr + i;

    // Current density per cell (cells lie wholly inside or outside each block).
    let mut jc = vec![0.0; (nr - 1) * (nz - 1)];
    for b in &win.blocks {
        let area = (b.r1 - b.r0) * (b.z1 - b.z0);
        let jd = amps[b.winding] * b.turns / area;
        for j in 0..nz - 1 {
            let zc = 0.5 * (z[j] + z[j + 1]);
            if zc < b.z0 || zc > b.z1 {
                continue;
            }
            for i in 0..nr - 1 {
                let rc = 0.5 * (r[i] + r[i + 1]);
                if rc > b.r0 && rc < b.r1 {
                    jc[j * (nr - 1) + i] += jd;
                }
            }
        }
    }

    // Assemble: each cell two triangles (lower-left / upper-right split).
    let nu = 1.0 / MU0;
    let mut rows: Vec<Vec<(usize, f64)>> = vec![Vec::with_capacity(7); n];
    let mut rhs = vec![0.0; n];
    let add = |rows: &mut Vec<Vec<(usize, f64)>>, a: usize, b: usize, v: f64| match rows[a]
        .iter_mut()
        .find(|(c, _)| *c == b)
    {
        Some(e) => e.1 += v,
        None => rows[a].push((b, v)),
    };
    let tris = |i: usize, j: usize| {
        let (n00, n10, n01, n11) = (id(i, j), id(i + 1, j), id(i, j + 1), id(i + 1, j + 1));
        [[n00, n10, n11], [n00, n11, n01]]
    };
    let xy = |k: usize| (r[k % nr], z[k / nr]);
    for j in 0..nz - 1 {
        for i in 0..nr - 1 {
            let jd = jc[j * (nr - 1) + i];
            for t in tris(i, j) {
                let p: Vec<(f64, f64)> = t.iter().map(|&k| xy(k)).collect();
                let area2 =
                    (p[1].0 - p[0].0) * (p[2].1 - p[0].1) - (p[2].0 - p[0].0) * (p[1].1 - p[0].1);
                let area = 0.5 * area2.abs();
                // Gradients of the barycentric functions: (b_k, c_k) / (2 area).
                let bc: Vec<(f64, f64)> = (0..3)
                    .map(|k| {
                        let (p1, p2) = (p[(k + 1) % 3], p[(k + 2) % 3]);
                        ((p1.1 - p2.1) / area2, (p2.0 - p1.0) / area2)
                    })
                    .collect();
                for a in 0..3 {
                    for b in 0..3 {
                        let v = nu * area * (bc[a].0 * bc[b].0 + bc[a].1 * bc[b].1);
                        add(&mut rows, t[a], t[b], v);
                    }
                    rhs[t[a]] += jd * area / 3.0;
                }
            }
        }
    }
    // Hold node 0 at zero: drop its row and column.
    let fixed = 0;
    for (k, row) in rows.iter_mut().enumerate() {
        if k == fixed {
            row.clear();
            row.push((fixed, 1.0));
        } else {
            row.retain(|(c, _)| *c != fixed);
        }
    }
    rhs[fixed] = 0.0;

    let (a, iters) = cg(&rows, &rhs, 1e-12, 50 * n);

    // Energy: 1/2 integral |grad A|^2 / mu0 weighted by the turn length at the centroid.
    let mut w = 0.0;
    for j in 0..nz - 1 {
        for i in 0..nr - 1 {
            for t in tris(i, j) {
                let p: Vec<(f64, f64)> = t.iter().map(|&k| xy(k)).collect();
                let area2 =
                    (p[1].0 - p[0].0) * (p[2].1 - p[0].1) - (p[2].0 - p[0].0) * (p[1].1 - p[0].1);
                let (mut gx, mut gy) = (0.0, 0.0);
                for k in 0..3 {
                    let (p1, p2) = (p[(k + 1) % 3], p[(k + 2) % 3]);
                    gx += a[t[k]] * (p1.1 - p2.1) / area2;
                    gy += a[t[k]] * (p2.0 - p1.0) / area2;
                }
                let rc = (p[0].0 + p[1].0 + p[2].0) / 3.0;
                w += 0.5 * nu * (gx * gx + gy * gy) * 0.5 * area2.abs() * turn(rc);
            }
        }
    }
    Field {
        r,
        z,
        a,
        energy_j: w,
        cg_iterations: iters,
    }
}

/// Conjugate gradients, Jacobi-preconditioned, on a symmetric positive definite matrix in
/// row lists; stops at a relative residual `tol`.
fn cg(rows: &[Vec<(usize, f64)>], b: &[f64], tol: f64, max_iter: usize) -> (Vec<f64>, usize) {
    let n = b.len();
    let mul = |x: &[f64], y: &mut [f64]| {
        for (k, row) in rows.iter().enumerate() {
            y[k] = row.iter().map(|&(c, v)| v * x[c]).sum();
        }
    };
    let diag: Vec<f64> = rows
        .iter()
        .enumerate()
        .map(|(k, row)| row.iter().find(|(c, _)| *c == k).map_or(1.0, |e| e.1))
        .collect();
    let mut x = vec![0.0; n];
    let mut r = b.to_vec();
    let bnorm = b.iter().map(|v| v * v).sum::<f64>().sqrt().max(1e-300);
    let mut z: Vec<f64> = r.iter().zip(&diag).map(|(r, d)| r / d).collect();
    let mut p = z.clone();
    let mut rz: f64 = r.iter().zip(&z).map(|(a, b)| a * b).sum();
    let mut ap = vec![0.0; n];
    for it in 0..max_iter {
        let rn = r.iter().map(|v| v * v).sum::<f64>().sqrt();
        if rn <= tol * bnorm {
            return (x, it);
        }
        mul(&p, &mut ap);
        let alpha = rz / p.iter().zip(&ap).map(|(a, b)| a * b).sum::<f64>();
        for k in 0..n {
            x[k] += alpha * p[k];
            r[k] -= alpha * ap[k];
        }
        for k in 0..n {
            z[k] = r[k] / diag[k];
        }
        let rz_new: f64 = r.iter().zip(&z).map(|(a, b)| a * b).sum();
        let beta = rz_new / rz;
        rz = rz_new;
        for k in 0..n {
            p[k] = z[k] + beta * p[k];
        }
    }
    (x, max_iter)
}

/// The leakage (H) of the windings `drive` in series with `shorted` in series and
/// shorted, by the field solution (as [`leakage::series_short_circuit`] by the 1D model).
pub fn series_short_circuit(
    layout: &Layout,
    z_offset: f64,
    n: usize,
    drive: &[usize],
    shorted: &[usize],
    mesh: Mesh,
) -> f64 {
    let nt = leakage::turns(layout, n);
    let nd: f64 = drive.iter().map(|&k| nt[k]).sum();
    let ns: f64 = shorted.iter().map(|&k| nt[k]).sum();
    let mut amps = vec![0.0; n];
    for &k in drive {
        amps[k] = 1.0;
    }
    for &k in shorted {
        amps[k] = -nd / ns;
    }
    let win = Window::from_layout(layout, z_offset);
    let f = solve(&win, &amps, |r| layout.turn(r), mesh);
    2.0 * f.energy_j
}

#[cfg(test)]
mod tests {
    use super::*;

    /// Two windings filling the window's height: the field is exactly 1D (uniform along
    /// z, iron above and below), so L = mu0 N^2 P / G (c1/3 + g + c2/3) for a constant P
    /// (to the P1 elements' discretization error, ~1e-4 here).
    #[test]
    fn full_height_windings_are_one_dimensional() {
        let (w, g_h) = (0.01, 0.03);
        let (c1, gap, c2) = (2e-3, 1e-3, 3e-3);
        let win = Window {
            width: w,
            height: g_h,
            blocks: vec![
                Block {
                    winding: 0,
                    turns: 100.0,
                    r0: 1e-3,
                    r1: 1e-3 + c1,
                    z0: 0.0,
                    z1: g_h,
                },
                Block {
                    winding: 1,
                    turns: 10.0,
                    r0: 1e-3 + c1 + gap,
                    r1: 1e-3 + c1 + gap + c2,
                    z0: 0.0,
                    z1: g_h,
                },
            ],
        };
        let p = 0.1;
        let f = solve(&win, &[1.0, -10.0], |_| p, Mesh::default());
        let want = MU0 * 100.0 * 100.0 * p / g_h * (c1 / 3.0 + gap + c2 / 3.0);
        let got = 2.0 * f.energy_j;
        assert!(
            (got / want - 1.0).abs() < 5e-4,
            "{got} vs {want} ({} its)",
            f.cg_iterations
        );
    }

    /// Short windings in a tall window: the field spreads into the empty ends, so the
    /// leakage falls below the 1D value at the windings' own height, and converges as the
    /// mesh refines.
    #[test]
    fn short_windings_converge() {
        let win = Window {
            width: 0.01,
            height: 0.03,
            blocks: vec![
                Block {
                    winding: 0,
                    turns: 100.0,
                    r0: 1e-3,
                    r1: 3e-3,
                    z0: 0.01,
                    z1: 0.02,
                },
                Block {
                    winding: 1,
                    turns: 100.0,
                    r0: 4e-3,
                    r1: 6e-3,
                    z0: 0.01,
                    z1: 0.02,
                },
            ],
        };
        let at = |c: f64| {
            let m = Mesh {
                cells_per_side: c,
                min_cells: 2,
            };
            2.0 * solve(&win, &[1.0, -1.0], |_| 0.1, m).energy_j
        };
        let (l1, l2, l3) = (at(40.0), at(80.0), at(160.0));
        let one_d = MU0 * 1e4 * 0.1 / 0.01 * (2e-3 / 3.0 + 1e-3 + 2e-3 / 3.0);
        assert!(l3 < one_d, "{l3} vs {one_d}");
        assert!(
            (l3 - l2).abs() < 0.5 * (l2 - l1).abs() + 1e-12,
            "{l1} {l2} {l3}"
        );
        assert!((l3 / l2 - 1.0).abs() < 2e-3);
    }
}
