//! Leakage inductance from the winding window's MMF profile (the energy method).
//!
//! The 1D model: across the windings (along r for layer windings, along z for disc
//! windings) the leakage field H runs along the other axis, uniform over the field's
//! length h ([`Layout::field_length_m`]), and its line integral is the ampere-turns
//! enclosed: H(x) = MMF(x) / h. With MMF(x) = sum_k N_k I_k f_k(x), f_k the share of
//! winding k's turns at positions below x, the field energy is
//!
//!   W = (mu0 / 2) int (MMF / h)^2 h P(x) dx = 1/2 sum_jk (N_j I_j)(N_k I_k) M_jk,
//!   M_jk = (mu0 / h) int f_j f_k P dx,
//!
//! P(x) the turn length weighting the field's volume ([`Layout::turn_at`]). The textbook
//! two-winding case (builds c1, c2, a gap g between them, one turn length) gives
//! L = mu0 N^2 P / h (c1 / 3 + g + c2 / 3) referred to N turns.
//!
//! Under balanced ampere-turns (sum N_k I_k = 0, the magnetizing current neglected) only
//! the differences f_j - f_k matter. Two representations reproduce every balanced energy:
//! - **star** (a series leakage per winding, what the macro's `leak` is): pairs of windings
//!   shorted give lambda_jk = (mu0 / h) int (f_j - f_k)^2 P dx per turn^2, and a star of
//!   lambda_k with lambda_j + lambda_k = lambda_jk exists exactly for three windings (for
//!   two, the split between them is a convention: each winding takes the field in the
//!   space nearer to it; for four or more, least squares). A star may need a negative
//!   branch (the middle one of three windings wound over each other), which the IR refuses;
//! - **coupled** (series leakages with mutual couplings): L_jk = N_j N_k (mu0 / h) int
//!   (f_j - 1/2)(f_k - 1/2) P dx, a Gram matrix, so always positive semidefinite, exact for
//!   any number of windings.

use circuitsim::devices::core::MU0;

use crate::geometry::{Layout, Slab};

/// Each winding's total turns in the layout.
pub fn turns(layout: &Layout, n: usize) -> Vec<f64> {
    let mut out = vec![0.0; n];
    for s in &layout.slabs {
        if let Some(k) = s.winding {
            out[k] += s.turns;
        }
    }
    out
}

/// f_k at each slab boundary: share of winding k's turns below it (len slabs + 1).
fn shares(layout: &Layout, n: usize) -> Vec<Vec<f64>> {
    let total = turns(layout, n);
    let mut f = vec![0.0; n];
    let mut out = vec![f.clone()];
    for s in &layout.slabs {
        if let Some(k) = s.winding {
            f[k] += s.turns / total[k];
        }
        out.push(f.clone());
    }
    out
}

/// int over one slab (or a part [u0, u1] of it, fractions of its width) of
/// g(x) h(x) P(x) dx, g and h linear from their values at the slab's ends. Simpson's rule
/// is exact: the integrand is at most cubic.
fn slab_integral(
    layout: &Layout,
    s: &Slab,
    (g0, g1): (f64, f64),
    (h0, h1): (f64, f64),
    (u0, u1): (f64, f64),
) -> f64 {
    let w = s.x1_m - s.x0_m;
    let at = |u: f64| {
        let x = s.x0_m + u * w;
        let g = g0 + (g1 - g0) * u;
        let h = h0 + (h1 - h0) * u;
        g * h * layout.turn_at(x)
    };
    let um = 0.5 * (u0 + u1);
    (u1 - u0) * w / 6.0 * (at(u0) + 4.0 * at(um) + at(u1))
}

/// lambda_jk (H per turn^2) for every pair: the leakage of j with k shorted is
/// N_j^2 lambda_jk. Symmetric, zero diagonal.
pub fn pairs(layout: &Layout, n: usize) -> Vec<Vec<f64>> {
    let f = shares(layout, n);
    let c = MU0 / layout.field_length_m;
    let mut out = vec![vec![0.0; n]; n];
    for j in 0..n {
        for k in (j + 1)..n {
            let mut sum = 0.0;
            for (i, s) in layout.slabs.iter().enumerate() {
                let d = (f[i][j] - f[i][k], f[i + 1][j] - f[i + 1][k]);
                sum += slab_integral(layout, s, d, d, (0.0, 1.0));
            }
            out[j][k] = c * sum;
            out[k][j] = c * sum;
        }
    }
    out
}

/// The leakage (H) of the windings `drive` in series (aiding) with the windings `shorted`
/// in series and shorted: one current through the driven group, the shorted group's
/// current balancing its ampere-turns.
pub fn series_short_circuit(layout: &Layout, n: usize, drive: &[usize], shorted: &[usize]) -> f64 {
    let nt = turns(layout, n);
    let nd: f64 = drive.iter().map(|&k| nt[k]).sum();
    let ns: f64 = shorted.iter().map(|&k| nt[k]).sum();
    let mut a = vec![0.0; n];
    for &k in drive {
        a[k] += nt[k];
    }
    for &k in shorted {
        a[k] -= nt[k] * nd / ns;
    }
    let f = shares(layout, n);
    let mmf = |i: usize| (0..n).map(|k| a[k] * f[i][k]).sum::<f64>();
    let mut sum = 0.0;
    for (i, s) in layout.slabs.iter().enumerate() {
        let d = (mmf(i), mmf(i + 1));
        sum += slab_integral(layout, s, d, d, (0.0, 1.0));
    }
    MU0 / layout.field_length_m * sum
}

/// The coupled representation's matrix L_jk (H, for the windings' actual turns).
pub fn coupled(layout: &Layout, n: usize) -> Vec<Vec<f64>> {
    let f = shares(layout, n);
    let nt = turns(layout, n);
    let c = MU0 / layout.field_length_m;
    let mut out = vec![vec![0.0; n]; n];
    for j in 0..n {
        for k in j..n {
            let mut sum = 0.0;
            for (i, s) in layout.slabs.iter().enumerate() {
                let g = (f[i][j] - 0.5, f[i + 1][j] - 0.5);
                let h = (f[i][k] - 0.5, f[i + 1][k] - 0.5);
                sum += slab_integral(layout, s, g, h, (0.0, 1.0));
            }
            out[j][k] = c * sum * nt[j] * nt[k];
            out[k][j] = out[j][k];
        }
    }
    out
}

/// Which winding each slab's part is nearer to: copper slabs are their winding's; an
/// empty slab between two windings' copper is split at its middle.
fn nearest(layout: &Layout) -> Vec<(Option<usize>, Option<usize>)> {
    let slabs = &layout.slabs;
    (0..slabs.len())
        .map(|i| match slabs[i].winding {
            Some(k) => (Some(k), Some(k)),
            None => (
                slabs[..i].iter().rev().find_map(|s| s.winding),
                slabs[i + 1..].iter().find_map(|s| s.winding),
            ),
        })
        .collect()
}

/// The star's lambda_k (H per turn^2) and the largest relative misfit of a pair
/// (0 for up to three windings).
pub fn star(layout: &Layout, n: usize) -> (Vec<f64>, f64) {
    if n != 2 {
        return star_from_pairs(&pairs(layout, n), None);
    }
    // Two windings: each takes the shorted pair's field in the space nearer to it.
    let f = shares(layout, 2);
    let c = MU0 / layout.field_length_m;
    let mut lam = [0.0; 2];
    for (i, (s, (lo, hi))) in layout.slabs.iter().zip(nearest(layout)).enumerate() {
        let d = (f[i][0] - f[i][1], f[i + 1][0] - f[i + 1][1]);
        if lo == hi {
            lam[lo.unwrap()] += c * slab_integral(layout, s, d, d, (0.0, 1.0));
        } else {
            lam[lo.unwrap()] += c * slab_integral(layout, s, d, d, (0.0, 0.5));
            lam[hi.unwrap()] += c * slab_integral(layout, s, d, d, (0.5, 1.0));
        }
    }
    (lam.to_vec(), 0.0)
}

/// The star from pair leakages `p` (H per turn^2, symmetric): exact for three windings,
/// least squares for four or more; two windings split their pair in the proportions
/// `split` (the 1D model's nearer-space convention, [`star`]).
pub fn star_from_pairs(p: &[Vec<f64>], split: Option<[f64; 2]>) -> (Vec<f64>, f64) {
    let n = p.len();
    match n {
        0 | 1 => (vec![0.0; n], 0.0),
        2 => {
            let [a, b] = split.unwrap_or([0.5, 0.5]);
            let s = p[0][1] / (a + b);
            (vec![a * s, b * s], 0.0)
        }
        3 => {
            let l0 = 0.5 * (p[0][1] + p[0][2] - p[1][2]);
            let l1 = 0.5 * (p[0][1] + p[1][2] - p[0][2]);
            let l2 = 0.5 * (p[0][2] + p[1][2] - p[0][1]);
            (vec![l0, l1, l2], 0.0)
        }
        _ => {
            // Least squares: minimize sum over pairs (l_j + l_k - p_jk)^2. Normal
            // equations: (n - 2) l_j + sum_k l_k = sum_k p_jk.
            let mut a = vec![vec![1.0; n]; n];
            let mut b = vec![0.0; n];
            for j in 0..n {
                a[j][j] = (n - 2) as f64 + 1.0;
                b[j] = (0..n).filter(|&k| k != j).map(|k| p[j][k]).sum();
            }
            let lam = solve(a, b);
            let mut worst: f64 = 0.0;
            for j in 0..n {
                for k in (j + 1)..n {
                    worst = worst.max(((lam[j] + lam[k]) - p[j][k]).abs() / p[j][k]);
                }
            }
            (lam, worst)
        }
    }
}

/// The coupled matrix (H, for the windings' turns `nt`) from pair leakages `p` (H per
/// turn^2): any matrix G_jk = -p_jk / 2 + c_j + c_k gives every balanced excitation's
/// energy (for sum a = 0, -1/2 sum a_j a_k (f_j - f_k)^2 = (sum a_j f_j)^2), and a Gram
/// matrix is positive semidefinite. `gauge` c_j: the 1D model's (half its Gram diagonal,
/// [`coupled`]) when that stays positive definite, else winding 0's: G_jk =
/// (p_j0 + p_k0 - p_jk) / 2, the Gram matrix of f_j - f_0 (winding 0 then has none).
pub fn coupled_from_pairs(p: &[Vec<f64>], nt: &[f64], gauge: &[f64]) -> Vec<Vec<f64>> {
    let n = p.len();
    let build = |c: &dyn Fn(usize) -> f64| -> Vec<Vec<f64>> {
        (0..n)
            .map(|j| {
                (0..n)
                    .map(|k| (-0.5 * p[j][k] + c(j) + c(k)) * nt[j] * nt[k])
                    .collect()
            })
            .collect()
    };
    let g = build(&|j| gauge[j]);
    if positive_definite(&g) {
        return g;
    }
    build(&|j| 0.5 * p[j][0])
}

/// Cholesky succeeds.
fn positive_definite(m: &[Vec<f64>]) -> bool {
    let n = m.len();
    let mut l = vec![vec![0.0; n]; n];
    for j in 0..n {
        let d = m[j][j] - l[j][..j].iter().map(|x| x * x).sum::<f64>();
        if d <= 0.0 {
            return false;
        }
        l[j][j] = d.sqrt();
        for i in (j + 1)..n {
            let s: f64 = l[i][..j].iter().zip(&l[j][..j]).map(|(a, b)| a * b).sum();
            l[i][j] = (m[i][j] - s) / l[j][j];
        }
    }
    true
}

/// Gaussian elimination with partial pivoting (small dense systems).
fn solve(mut a: Vec<Vec<f64>>, mut b: Vec<f64>) -> Vec<f64> {
    let n = b.len();
    for c in 0..n {
        let p = (c..n)
            .max_by(|&i, &j| a[i][c].abs().total_cmp(&a[j][c].abs()))
            .unwrap();
        a.swap(c, p);
        b.swap(c, p);
        let pivot = a[c].clone();
        for r in (c + 1)..n {
            let m = a[r][c] / pivot[c];
            for (x, &y) in a[r][c..].iter_mut().zip(&pivot[c..]) {
                *x -= m * y;
            }
            b[r] -= m * b[c];
        }
    }
    let mut x = vec![0.0; n];
    for r in (0..n).rev() {
        let s: f64 = ((r + 1)..n).map(|k| a[r][k] * x[k]).sum();
        x[r] = (b[r] - s) / a[r][r];
    }
    x
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::design::Arrangement;
    use crate::geometry::FieldTurn;

    fn slab(x0: f64, x1: f64, w: Option<usize>, t: f64) -> Slab {
        Slab {
            x0_m: x0,
            x1_m: x1,
            winding: w,
            turns: t,
        }
    }

    fn layout(slabs: Vec<Slab>, turn: FieldTurn) -> Layout {
        Layout {
            arrangement: Arrangement::Layer,
            leg_m: 0.02,
            stack_m: 0.02,
            wall_m: 0.0,
            window_width_m: 0.01,
            window_height_m: 0.03,
            traverse_m: 0.03,
            layers: vec![],
            placed: vec![],
            slabs,
            field_length_m: 0.03,
            field_turn: turn,
            warnings: vec![],
        }
    }

    /// Two windings, builds c1 and c2, a gap g, one turn length: mu0 P / h (c1/3 + g + c2/3).
    #[test]
    fn two_windings_give_the_textbook_formula() {
        let (c1, g, c2, p, h) = (1e-3, 0.5e-3, 2e-3, 0.1, 0.03);
        let l = layout(
            vec![
                slab(0.0, c1, Some(0), 100.0),
                slab(c1, c1 + g, None, 0.0),
                slab(c1 + g, c1 + g + c2, Some(1), 10.0),
            ],
            FieldTurn::Fixed(p),
        );
        let want = MU0 * p / h * (c1 / 3.0 + g + c2 / 3.0);
        let lam = pairs(&l, 2)[0][1];
        assert!((lam / want - 1.0).abs() < 1e-14, "{lam} vs {want}");
        let (s, _) = star(&l, 2);
        assert!(((s[0] + s[1]) / want - 1.0).abs() < 1e-14);
        // The convention: each side its own build's third and half the gap.
        let s0 = MU0 * p / h * (c1 / 3.0 + g / 2.0);
        assert!((s[0] / s0 - 1.0).abs() < 1e-14);
        // The coupled matrix gives the same shorted pair.
        let m = coupled(&l, 2);
        let (n0, n1) = (100.0, 10.0);
        let w = m[0][0] / (n0 * n0) + m[1][1] / (n1 * n1) - 2.0 * m[0][1] / (n0 * n1);
        assert!((w / want - 1.0).abs() < 1e-13);
    }

    /// Splitting a winding into p interleaved interfaces divides its leakage by p^2
    /// (P-S-P with the primary halves in series: the field is two half-sized triangles).
    #[test]
    fn interleaving_divides_by_the_interfaces_squared() {
        let c = 1e-3;
        let simple = layout(
            vec![
                slab(0.0, 2.0 * c, Some(0), 100.0),
                slab(2.0 * c, 4.0 * c, Some(1), 100.0),
            ],
            FieldTurn::Fixed(0.1),
        );
        let split = layout(
            vec![
                slab(0.0, c, Some(0), 50.0),
                slab(c, 3.0 * c, Some(1), 100.0),
                slab(3.0 * c, 4.0 * c, Some(0), 50.0),
            ],
            FieldTurn::Fixed(0.1),
        );
        let r = pairs(&simple, 2)[0][1] / pairs(&split, 2)[0][1];
        assert!((r - 4.0).abs() < 1e-12, "{r}");
    }

    /// Three windings over each other: the star is exact and its middle branch negative;
    /// the coupled matrix is positive definite and reproduces every shorted pair.
    #[test]
    fn three_windings_star_and_coupled() {
        let c = 1e-3;
        let l = layout(
            vec![
                slab(0.0, c, Some(0), 100.0),
                slab(c, 2.0 * c, Some(1), 100.0),
                slab(2.0 * c, 3.0 * c, Some(2), 10.0),
            ],
            FieldTurn::AtRadius,
        );
        let p = pairs(&l, 3);
        let (s, misfit) = star(&l, 3);
        assert_eq!(misfit, 0.0);
        assert!(s[1] < 0.0);
        for (j, k) in [(0, 1), (0, 2), (1, 2)] {
            assert!(((s[j] + s[k]) / p[j][k] - 1.0).abs() < 1e-12);
        }
        let m = coupled(&l, 3);
        let n = turns(&l, 3);
        for (j, k) in [(0, 1), (0, 2), (1, 2)] {
            let w =
                m[j][j] / (n[j] * n[j]) + m[k][k] / (n[k] * n[k]) - 2.0 * m[j][k] / (n[j] * n[k]);
            assert!((w / p[j][k] - 1.0).abs() < 1e-12);
        }
        assert!(m[0][0] > 0.0 && m[0][0] * m[1][1] > m[0][1] * m[0][1]);
        // A group of one is the pair; two windings in series against the third: the
        // coupled matrix's energy with those currents.
        let l = layout_three();
        let p = pairs(&l, 3);
        let one = series_short_circuit(&l, 3, &[0], &[2]);
        assert!((one / (100.0 * 100.0 * p[0][2]) - 1.0).abs() < 1e-12);
        let m = coupled(&l, 3);
        let i = [1.0, 1.0, -20.0];
        let w: f64 = (0..3)
            .flat_map(|j| (0..3).map(move |k| (j, k)))
            .map(|(j, k)| m[j][k] * i[j] * i[k])
            .sum();
        let both = series_short_circuit(&l, 3, &[0, 1], &[2]);
        assert!((both / w - 1.0).abs() < 1e-12, "{both} vs {w}");
    }

    fn layout_three() -> Layout {
        let c = 1e-3;
        layout(
            vec![
                slab(0.0, c, Some(0), 100.0),
                slab(c, 2.0 * c, Some(1), 100.0),
                slab(2.0 * c, 3.0 * c, Some(2), 10.0),
            ],
            FieldTurn::AtRadius,
        )
    }

    /// From the 1D model's own pairs and gauge, the coupled matrix is the 1D one.
    #[test]
    fn coupled_from_pairs_reproduces_the_gram_matrix() {
        let l = layout_three();
        let nt = turns(&l, 3);
        let g = coupled(&l, 3);
        let gauge: Vec<f64> = (0..3).map(|j| 0.5 * g[j][j] / (nt[j] * nt[j])).collect();
        let back = coupled_from_pairs(&pairs(&l, 3), &nt, &gauge);
        for j in 0..3 {
            for k in 0..3 {
                assert!((back[j][k] - g[j][k]).abs() <= 1e-9 * g[j][j].abs().max(g[k][k].abs()));
            }
        }
    }

    #[test]
    fn least_squares_star_is_exact_when_a_star_fits() {
        // A layout whose pairs happen to be a star isn't easy to build; check the solver.
        let x = solve(
            vec![
                vec![2.0, 1.0, 1.0],
                vec![1.0, 3.0, 2.0],
                vec![1.0, 0.0, 0.0],
            ],
            vec![4.0, 5.0, 6.0],
        );
        let back = [
            2.0 * x[0] + x[1] + x[2],
            x[0] + 3.0 * x[1] + 2.0 * x[2],
            x[0],
        ];
        for (a, b) in back.iter().zip([4.0, 5.0, 6.0]) {
            assert!((a - b).abs() < 1e-12);
        }
    }
}
