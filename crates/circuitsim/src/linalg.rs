//! Dense linear algebra: a row-major square matrix and LU with partial pivoting.
//!
//! Enough for the full-MNA engine on circuits of up to a few hundred unknowns:
//! the nonlinear solver only refactors the small block of unknowns that
//! devices touch (see `newton.rs`), so no sparse LU is needed.

/// Row-major n x n matrix.
#[derive(Debug, Clone, PartialEq)]
pub struct Matrix {
    n: usize,
    a: Vec<f64>,
}

impl Matrix {
    pub fn zeros(n: usize) -> Self {
        Matrix {
            n,
            a: vec![0.0; n * n],
        }
    }

    pub fn n(&self) -> usize {
        self.n
    }

    pub fn get(&self, i: usize, j: usize) -> f64 {
        self.a[i * self.n + j]
    }

    pub fn add(&mut self, i: usize, j: usize, x: f64) {
        self.a[i * self.n + j] += x;
    }

    pub fn row(&self, i: usize) -> &[f64] {
        &self.a[i * self.n..(i + 1) * self.n]
    }

    /// `self + s * other`.
    pub fn plus_scaled(&self, s: f64, other: &Matrix) -> Matrix {
        assert_eq!(self.n, other.n);
        Matrix {
            n: self.n,
            a: self
                .a
                .iter()
                .zip(&other.a)
                .map(|(x, y)| x + s * y)
                .collect(),
        }
    }

    pub fn scaled(&self, s: f64) -> Matrix {
        Matrix {
            n: self.n,
            a: self.a.iter().map(|x| s * x).collect(),
        }
    }

    pub fn set(&mut self, i: usize, j: usize, x: f64) {
        self.a[i * self.n + j] = x;
    }

    /// Copy `other` (same size) into this matrix.
    pub fn copy_from(&mut self, other: &Matrix) {
        self.a.copy_from_slice(&other.a);
    }

    /// `y = self * x`.
    pub fn mul_vec(&self, x: &[f64], y: &mut [f64]) {
        for (i, yi) in y.iter_mut().enumerate() {
            *yi = self.row(i).iter().zip(x).map(|(a, b)| a * b).sum();
        }
    }
}

/// A matrix's nonzero entries by row, for products with mostly-zero
/// matrices (the reactive matrix C). Same sums, in the same order, as
/// [`Matrix::mul_vec`] without the zero terms.
#[derive(Debug, Clone, PartialEq)]
pub struct SparseRows {
    start: Vec<usize>,
    col: Vec<usize>,
    val: Vec<f64>,
}

impl SparseRows {
    pub fn new(m: &Matrix) -> SparseRows {
        let mut s = SparseRows {
            start: vec![0],
            col: Vec::new(),
            val: Vec::new(),
        };
        for i in 0..m.n {
            for (j, &x) in m.row(i).iter().enumerate() {
                if x != 0.0 {
                    s.col.push(j);
                    s.val.push(x);
                }
            }
            s.start.push(s.col.len());
        }
        s
    }

    /// `y = M x`.
    pub fn mul_vec(&self, x: &[f64], y: &mut [f64]) {
        for (i, yi) in y.iter_mut().enumerate() {
            let r = self.start[i]..self.start[i + 1];
            *yi = self.col[r.clone()]
                .iter()
                .zip(&self.val[r])
                .map(|(&j, a)| a * x[j])
                .sum();
        }
    }
}

/// `y += A x` for rows `row0..row0 + y.len()` of the column-major matrix `a`
/// with leading dimension `lda`. Columns are added one after another, so
/// every `y_i` sums its terms in column order, exactly like a row-wise dot
/// product, but the inner loop runs down a column with no reduction and
/// vectorizes.
///
/// With AVX2 (detected at run time) the same loop runs 4 lanes wide: every
/// `y_i` is the same sequence of IEEE operations either way (no fused
/// multiply-add), so the results are identical.
pub fn gemv_add(y: &mut [f64], a: &[f64], row0: usize, lda: usize, x: &[f64]) {
    #[cfg(target_arch = "x86_64")]
    if y.len() >= 8 && std::is_x86_feature_detected!("avx2") {
        // SAFETY: the CPU has AVX2 (checked just above).
        return unsafe { gemv_add_avx2(y, a, row0, lda, x) };
    }
    gemv_add_impl(y, a, row0, lda, x)
}

#[cfg(target_arch = "x86_64")]
#[target_feature(enable = "avx2")]
fn gemv_add_avx2(y: &mut [f64], a: &[f64], row0: usize, lda: usize, x: &[f64]) {
    gemv_add_impl(y, a, row0, lda, x)
}

#[inline(always)]
fn gemv_add_impl(y: &mut [f64], a: &[f64], row0: usize, lda: usize, x: &[f64]) {
    let m = y.len();
    let col = |j: usize| &a[row0 + j * lda..row0 + j * lda + m];
    let mut j = 0;
    // Four columns per pass: y is loaded and stored a quarter as often, and
    // the sums keep their order (left to right).
    while j + 4 <= x.len() {
        let (x0, x1, x2, x3) = (x[j], x[j + 1], x[j + 2], x[j + 3]);
        let (c0, c1, c2, c3) = (col(j), col(j + 1), col(j + 2), col(j + 3));
        for i in 0..m {
            y[i] = y[i] + c0[i] * x0 + c1[i] * x1 + c2[i] * x2 + c3[i] * x3;
        }
        j += 4;
    }
    for (k, &xk) in x.iter().enumerate().skip(j) {
        for (yi, ci) in y.iter_mut().zip(col(k)) {
            *yi += ci * xk;
        }
    }
}

/// `y -= A x`, see [`gemv_add`] (`y - a x` rounds exactly like `y + a (-x)`).
pub fn gemv_sub(y: &mut [f64], a: &[f64], row0: usize, lda: usize, x: &[f64], neg: &mut [f64]) {
    for (n, v) in neg.iter_mut().zip(x) {
        *n = -v;
    }
    gemv_add(y, a, row0, lda, &neg[..x.len()]);
}

/// LU with partial pivoting of a small column-major matrix, for Newton on
/// the device ports (see `dk.rs`), where the matrix changes every iteration.
/// Equilibrated like [`Lu`]: the DK matrix `I + K G_d` has columns of ~1
/// next to ~1e10 (a conducting diode on a node held only by a 1 GOhm leak).
#[derive(Debug, Clone)]
pub struct ColLu {
    n: usize,
    lu: Vec<f64>,
    perm: Vec<usize>,
    row_scale: Vec<f64>,
    col_scale: Vec<f64>,
}

impl ColLu {
    pub fn with_size(n: usize) -> ColLu {
        ColLu {
            n,
            lu: vec![0.0; n * n],
            perm: (0..n).collect(),
            row_scale: vec![0.0; n],
            col_scale: vec![0.0; n],
        }
    }

    pub fn n(&self) -> usize {
        self.n
    }

    /// Factor the column-major `a` (n x n). On error the storage holds
    /// garbage until the next successful factorization. With AVX2 the same
    /// loops run 4 lanes wide (identical results, see [`gemv_add`]).
    pub fn factor(&mut self, a: &[f64]) -> Result<(), Singular> {
        #[cfg(target_arch = "x86_64")]
        if self.n >= 8 && std::is_x86_feature_detected!("avx2") {
            // SAFETY: the CPU has AVX2 (checked just above).
            return unsafe { self.factor_avx2(a) };
        }
        self.factor_impl(a)
    }

    #[cfg(target_arch = "x86_64")]
    #[target_feature(enable = "avx2")]
    fn factor_avx2(&mut self, a: &[f64]) -> Result<(), Singular> {
        self.factor_impl(a)
    }

    #[inline(always)]
    fn factor_impl(&mut self, a: &[f64]) -> Result<(), Singular> {
        let n = self.n;
        if n == 0 {
            return Ok(());
        }
        let a = &a[..n * n];
        // Rows, then columns, scaled to a largest entry of 1. (Maxima by
        // compare-and-select, which vectorizes; `f64::max` handles NaN and
        // doesn't. A NaN entry is caught by the pivot test.)
        self.row_scale.fill(0.0);
        for col in a.chunks_exact(n) {
            for (r, x) in self.row_scale.iter_mut().zip(col) {
                let x = x.abs();
                *r = if x > *r { x } else { *r };
            }
        }
        for (i, r) in self.row_scale.iter_mut().enumerate() {
            if *r == 0.0 {
                return Err(Singular { column: i });
            }
            *r = 1.0 / *r;
        }
        for (j, ((dst, src), c)) in self
            .lu
            .chunks_exact_mut(n)
            .zip(a.chunks_exact(n))
            .zip(self.col_scale.iter_mut())
            .enumerate()
        {
            let mut m = [0.0f64; 4];
            for (k, ((d, s), r)) in dst.iter_mut().zip(src).zip(&self.row_scale).enumerate() {
                *d = s * r;
                let x = d.abs();
                m[k % 4] = if x > m[k % 4] { x } else { m[k % 4] };
            }
            let m = m.iter().fold(0.0f64, |a, &b| if b > a { b } else { a });
            if m == 0.0 {
                return Err(Singular { column: j });
            }
            *c = 1.0 / m;
            for d in dst.iter_mut() {
                *d *= *c;
            }
        }
        let lu = &mut self.lu;
        for k in 0..n {
            let col = &lu[k * n..(k + 1) * n];
            let (mut p, mut big) = (k, -1.0);
            for (i, x) in col.iter().enumerate().skip(k) {
                if x.abs() > big {
                    (p, big) = (i, x.abs());
                }
            }
            if big <= PIVOT_TOL {
                return Err(Singular { column: k });
            }
            self.perm[k] = p;
            if p != k {
                for j in 0..n {
                    lu.swap(j * n + k, j * n + p);
                }
            }
            let (left, right) = lu.split_at_mut((k + 1) * n);
            let ck = &mut left[k * n..];
            let inv = 1.0 / ck[k];
            for x in &mut ck[k + 1..] {
                *x *= inv;
            }
            let lcol = &ck[k + 1..];
            for cj in right.chunks_exact_mut(n) {
                let f = cj[k];
                if f != 0.0 {
                    for (x, l) in cj[k + 1..].iter_mut().zip(lcol) {
                        *x -= l * f;
                    }
                }
            }
        }
        Ok(())
    }

    /// Solve `A x = b` in place.
    pub fn solve(&self, b: &mut [f64]) {
        let n = self.n;
        for (x, r) in b.iter_mut().zip(&self.row_scale) {
            *x *= r;
        }
        for k in 0..n {
            let p = self.perm[k];
            if p != k {
                b.swap(k, p);
            }
        }
        for k in 0..n {
            let bk = b[k];
            if bk != 0.0 {
                let col = &self.lu[k * n + k + 1..(k + 1) * n];
                for (x, l) in b[k + 1..n].iter_mut().zip(col) {
                    *x -= l * bk;
                }
            }
        }
        for k in (0..n).rev() {
            b[k] /= self.lu[k * n + k];
            let bk = b[k];
            if bk != 0.0 {
                let col = &self.lu[k * n..k * n + k];
                for (x, u) in b[..k].iter_mut().zip(col) {
                    *x -= u * bk;
                }
            }
        }
        for (x, c) in b.iter_mut().zip(&self.col_scale) {
            *x *= c;
        }
    }
}

/// The matrix is singular (to working precision) at this column.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Singular {
    pub column: usize,
}

/// `P (R A C) = L U`, stored in place (unit lower L below the diagonal), with
/// row and column scalings R and C.
#[derive(Debug, Clone)]
pub struct Lu {
    lu: Matrix,
    perm: Vec<usize>,
    row_scale: Vec<f64>,
    col_scale: Vec<f64>,
}

/// Pivot threshold on the equilibrated matrix (every row and column has
/// largest entry 1): a smaller pivot counts as zero.
const PIVOT_TOL: f64 = 1e-13;

impl Lu {
    /// Equilibrate, then factor with partial pivoting.
    ///
    /// MNA entries span many decades (1 mOhm pot ends and winding resistances
    /// next to a 1 GOhm leak, 2L/h ~ 1e7 on inductor rows), and unscaled
    /// pivoting then loses digits on high-impedance nodes: measured ~4 mV of
    /// noise on a node that should sit at 0 V in the device-stripped 670.
    /// Scaling rows, then columns, to a largest entry of 1 brings that to the
    /// double-precision floor, eps x G_max x V / G_node (~5e-5 V there).
    /// Iterative refinement was tried on top and didn't lower it.
    pub fn factor(a: &Matrix) -> Result<Lu, Singular> {
        let mut lu = Lu::with_size(a.n);
        lu.refactor(a)?;
        Ok(lu)
    }

    /// Storage for factoring n x n matrices with [`Lu::refactor`].
    pub fn with_size(n: usize) -> Lu {
        Lu {
            lu: Matrix::zeros(n),
            perm: (0..n).collect(),
            row_scale: vec![0.0; n],
            col_scale: vec![0.0; n],
        }
    }

    /// Factor `a` (same size) into this storage, without allocating. On
    /// error the storage holds garbage until the next successful refactor.
    pub fn refactor(&mut self, a: &Matrix) -> Result<(), Singular> {
        let n = a.n;
        assert_eq!(n, self.lu.n, "matrix size");
        if n == 0 {
            return Ok(());
        }
        let Lu {
            lu,
            perm,
            row_scale,
            col_scale,
        } = self;
        for (i, r) in row_scale.iter_mut().enumerate() {
            let m = a.row(i).iter().fold(0.0f64, |m, x| m.max(x.abs()));
            if m == 0.0 {
                return Err(Singular { column: i });
            }
            *r = 1.0 / m;
        }
        col_scale.fill(0.0);
        for (i, &r) in row_scale.iter().enumerate() {
            for (c, x) in col_scale.iter_mut().zip(a.row(i)) {
                *c = c.max((r * x).abs());
            }
        }
        for (j, c) in col_scale.iter_mut().enumerate() {
            if *c == 0.0 {
                return Err(Singular { column: j });
            }
            *c = 1.0 / *c;
        }
        lu.a.copy_from_slice(&a.a);
        for (row, r) in lu.a.chunks_mut(n).zip(row_scale.iter()) {
            for (x, c) in row.iter_mut().zip(col_scale.iter()) {
                *x *= r * c;
            }
        }
        for (k, p) in perm.iter_mut().enumerate() {
            *p = k;
        }
        for k in 0..n {
            let (p, big) = (k..n)
                .map(|i| (i, lu.get(i, k).abs()))
                .fold((k, -1.0), |best, c| if c.1 > best.1 { c } else { best });
            if big <= PIVOT_TOL {
                return Err(Singular { column: k });
            }
            if p != k {
                for j in 0..n {
                    lu.a.swap(k * n + j, p * n + j);
                }
                perm.swap(k, p);
            }
            let pivot = lu.get(k, k);
            // Row slices, so the update loop has no bounds checks and vectorizes.
            let (top, below) = lu.a.split_at_mut((k + 1) * n);
            let pivot_row = &top[k * n + k + 1..(k + 1) * n];
            for row in below.chunks_exact_mut(n) {
                let f = row[k] / pivot;
                if f == 0.0 {
                    continue;
                }
                row[k] = f;
                for (x, p) in row[k + 1..].iter_mut().zip(pivot_row) {
                    *x -= f * p;
                }
            }
        }
        Ok(())
    }

    pub fn n(&self) -> usize {
        self.lu.n
    }

    /// Solve `A x = b`; `b` is overwritten with `x`. `work` must have length n.
    pub fn solve(&self, b: &mut [f64], work: &mut [f64]) {
        let n = self.lu.n;
        for (w, &p) in work.iter_mut().zip(&self.perm) {
            *w = b[p] * self.row_scale[p];
        }
        for i in 0..n {
            let row = self.lu.row(i);
            let s: f64 = row[..i].iter().zip(&work[..i]).map(|(l, y)| l * y).sum();
            work[i] -= s;
        }
        for i in (0..n).rev() {
            let row = self.lu.row(i);
            let s: f64 = row[i + 1..]
                .iter()
                .zip(&work[i + 1..])
                .map(|(u, x)| u * x)
                .sum();
            work[i] = (work[i] - s) / row[i];
        }
        for ((x, w), c) in b.iter_mut().zip(work.iter()).zip(&self.col_scale) {
            *x = w * c;
        }
    }
}

/// A fill-reducing order for a sparse matrix's factorization: greedy minimum degree on the
/// pattern of `a + a^T` (the node with the fewest uneliminated neighbours next, ties by
/// index; its neighbours become a clique). `order[k]` is the original index eliminated k-th.
/// Quadratic in n, for the step matrices' sizes (hundreds).
pub fn min_degree_order(a: &Matrix) -> Vec<usize> {
    let n = a.n;
    let words = n.div_ceil(64);
    let mut adj = vec![vec![0u64; words]; n];
    let set = |row: &mut [u64], j: usize| row[j / 64] |= 1 << (j % 64);
    for (i, row) in adj.iter_mut().enumerate() {
        for j in 0..n {
            if i != j && (a.get(i, j) != 0.0 || a.get(j, i) != 0.0) {
                set(row, j);
            }
        }
    }
    let mut alive = vec![0u64; words];
    for j in 0..n {
        set(&mut alive, j);
    }
    let degree = |row: &[u64], alive: &[u64]| -> u32 {
        row.iter()
            .zip(alive)
            .map(|(r, a)| (r & a).count_ones())
            .sum()
    };
    let mut order = Vec::with_capacity(n);
    for _ in 0..n {
        let v = (0..n)
            .filter(|&j| alive[j / 64] >> (j % 64) & 1 == 1)
            .min_by_key(|&j| (degree(&adj[j], &alive), j))
            .expect("a node left");
        order.push(v);
        alive[v / 64] &= !(1 << (v % 64));
        let nv = adj[v].clone();
        for u in 0..n {
            if nv[u / 64] >> (u % 64) & 1 == 1 && alive[u / 64] >> (u % 64) & 1 == 1 {
                for (x, y) in adj[u].iter_mut().zip(&nv) {
                    *x |= y;
                }
                adj[u][u / 64] &= !(1 << (u % 64));
            }
        }
    }
    order
}

/// A sparse LU for repeated solves with one matrix (DK's step matrix, `dk.rs`'s
/// `dk_sparse`): the rows and columns ordered by [`min_degree_order`], factored as [`Lu`]
/// does (equilibrated, partial pivoting: the same numerics, once per matrix), and the
/// factors' nonzero entries kept row by row. A solve then costs the factors' entries, not
/// n^2, and their few kilobytes stay in L1.
#[derive(Debug, Clone)]
pub struct SparseLu {
    n: usize,
    /// The k-th equation of the factored system: right-hand side entry `in_map[k]` times
    /// `in_scale[k]`.
    in_map: Vec<usize>,
    in_scale: Vec<f64>,
    /// The i-th unknown of the factored system is unknown `out_map[i]`, times `out_scale[i]`.
    out_map: Vec<usize>,
    out_scale: Vec<f64>,
    /// Unit lower L (strictly below the diagonal) and upper U (right of it) by rows:
    /// `ptr` n + 1 offsets into (column, value); U's diagonal apart.
    l_ptr: Vec<u32>,
    l_ent: Vec<(u32, f64)>,
    u_ptr: Vec<u32>,
    u_ent: Vec<(u32, f64)>,
    u_diag: Vec<f64>,
}

impl SparseLu {
    pub fn factor(a: &Matrix) -> Result<SparseLu, Singular> {
        let n = a.n;
        let q = min_degree_order(a);
        let mut ap = Matrix::zeros(n);
        for (i, &qi) in q.iter().enumerate() {
            for (j, &qj) in q.iter().enumerate() {
                ap.set(i, j, a.get(qi, qj));
            }
        }
        let lu = Lu::factor(&ap).map_err(|Singular { column }| Singular { column: q[column] })?;
        let (mut l_ptr, mut l_ent) = (vec![0u32], Vec::new());
        let (mut u_ptr, mut u_ent, mut u_diag) = (vec![0u32], Vec::new(), Vec::with_capacity(n));
        for i in 0..n {
            let row = lu.lu.row(i);
            l_ent.extend(
                row[..i]
                    .iter()
                    .enumerate()
                    .filter(|(_, x)| **x != 0.0)
                    .map(|(j, &x)| (j as u32, x)),
            );
            l_ptr.push(l_ent.len() as u32);
            u_diag.push(row[i]);
            u_ent.extend(
                row[i + 1..]
                    .iter()
                    .enumerate()
                    .filter(|(_, x)| **x != 0.0)
                    .map(|(j, &x)| ((i + 1 + j) as u32, x)),
            );
            u_ptr.push(u_ent.len() as u32);
        }
        Ok(SparseLu {
            n,
            in_map: lu.perm.iter().map(|&p| q[p]).collect(),
            in_scale: lu.perm.iter().map(|&p| lu.row_scale[p]).collect(),
            out_map: q,
            out_scale: lu.col_scale.clone(),
            l_ptr,
            l_ent,
            u_ptr,
            u_ent,
            u_diag,
        })
    }

    pub fn n(&self) -> usize {
        self.n
    }

    /// The factors' stored entries (L, U and the diagonal).
    pub fn nnz(&self) -> usize {
        self.l_ent.len() + self.u_ent.len() + self.n
    }

    /// Solve `A x = b`; `b` is overwritten with `x`. `work` must have length n.
    pub fn solve(&self, b: &mut [f64], work: &mut [f64]) {
        let n = self.n;
        for ((w, &k), &s) in work.iter_mut().zip(&self.in_map).zip(&self.in_scale) {
            *w = b[k] * s;
        }
        for i in 0..n {
            let (a, z) = (self.l_ptr[i] as usize, self.l_ptr[i + 1] as usize);
            let mut s = 0.0;
            for &(j, l) in &self.l_ent[a..z] {
                s += l * work[j as usize];
            }
            work[i] -= s;
        }
        for i in (0..n).rev() {
            let (a, z) = (self.u_ptr[i] as usize, self.u_ptr[i + 1] as usize);
            let mut s = 0.0;
            for &(j, u) in &self.u_ent[a..z] {
                s += u * work[j as usize];
            }
            work[i] = (work[i] - s) / self.u_diag[i];
        }
        for ((w, &k), &c) in work.iter().zip(&self.out_map).zip(&self.out_scale) {
            b[k] = w * c;
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    /// The sparse LU solves as the dense one does, on a sparse matrix with a zero diagonal
    /// (a voltage source's branch) that needs pivoting.
    #[test]
    fn the_sparse_lu_solves_as_the_dense() {
        let n = 40;
        let mut a = Matrix::zeros(n);
        for i in 0..n - 1 {
            // A chain of conductances, a capacitor to ground on every third node.
            let g = 1.0 / (100.0 + 37.0 * i as f64);
            a.add(i, i, g);
            a.add(i + 1, i + 1, g);
            a.add(i, i + 1, -g);
            a.add(i + 1, i, -g);
            if i % 3 == 0 {
                a.add(i, i, 1e-6 * 96_000.0);
            }
        }
        // A source on node 5 through a branch row/column (zero on its diagonal).
        a.add(n - 1, 5, 1.0);
        a.add(5, n - 1, 1.0);
        a.set(n - 1, n - 1, 0.0);
        let dense = Lu::factor(&a).unwrap();
        let sparse = SparseLu::factor(&a).unwrap();
        assert!(sparse.nnz() < n * n / 4, "{} entries", sparse.nnz());
        let mut work = vec![0.0; n];
        for k in [0, 5, 17, n - 1] {
            let mut x = vec![0.0; n];
            x[k] = 1.0;
            let mut y = x.clone();
            dense.solve(&mut x, &mut work);
            sparse.solve(&mut y, &mut work);
            for (p, q) in x.iter().zip(&y) {
                assert!((p - q).abs() <= 1e-12 * p.abs().max(1e-6), "{p} {q}");
            }
        }
    }

    /// Deterministic values spread over many magnitudes (a fixed LCG).
    fn values(n: usize, seed: u64) -> Vec<f64> {
        let mut s = seed;
        (0..n)
            .map(|_| {
                s = s
                    .wrapping_mul(6364136223846793005)
                    .wrapping_add(1442695040888963407);
                let u = (s >> 11) as f64 / (1u64 << 53) as f64 - 0.5;
                u * 10f64.powi(((s >> 3) % 7) as i32 - 3)
            })
            .collect()
    }

    /// The AVX2 paths (taken when the CPU has it) give exactly the portable
    /// loops' results: the same IEEE operations per element.
    #[test]
    fn avx2_paths_are_bitwise_the_portable_ones() {
        let (rows, cols) = (131, 86);
        let a = values(rows * cols, 1);
        let x = values(cols, 2);
        let y0 = values(rows, 3);
        let (mut y1, mut y2) = (y0.clone(), y0.clone());
        gemv_add(&mut y1, &a, 0, rows, &x);
        gemv_add_impl(&mut y2, &a, 0, rows, &x);
        assert_eq!(y1, y2);
        let n = 45;
        let mut m = values(n * n, 4);
        for i in 0..n {
            m[i * n + i] += 3.0;
        }
        let (mut l1, mut l2) = (ColLu::with_size(n), ColLu::with_size(n));
        l1.factor(&m).unwrap();
        l2.factor_impl(&m).unwrap();
        assert_eq!(l1.lu, l2.lu);
        assert_eq!(l1.perm, l2.perm);
    }

    fn matrix(rows: &[&[f64]]) -> Matrix {
        let mut m = Matrix::zeros(rows.len());
        for (i, r) in rows.iter().enumerate() {
            for (j, &x) in r.iter().enumerate() {
                m.add(i, j, x);
            }
        }
        m
    }

    #[test]
    fn solves_with_pivoting() {
        // Zero in the (0, 0) position forces a row swap.
        let a = matrix(&[&[0.0, 2.0, 1.0], &[1.0, 1.0, 0.0], &[3.0, 0.0, 1.0]]);
        let x_true = [1.0, -2.0, 3.0];
        let mut b = vec![0.0; 3];
        a.mul_vec(&x_true, &mut b);
        let lu = Lu::factor(&a).unwrap();
        let mut work = vec![0.0; 3];
        lu.solve(&mut b, &mut work);
        for (x, t) in b.iter().zip(x_true) {
            assert!((x - t).abs() < 1e-14, "{x} vs {t}");
        }
    }

    #[test]
    fn wide_dynamic_range() {
        // 1 mOhm next to 10 MOhm: conductances 1e3 and 1e-7 in one matrix.
        let a = matrix(&[&[1e3 + 1e-7, -1e3], &[-1e3, 1e3 + 2e-7]]);
        let x_true = [0.3, 0.7];
        let mut b = vec![0.0; 2];
        a.mul_vec(&x_true, &mut b);
        let lu = Lu::factor(&a).unwrap();
        lu.solve(&mut b, &mut [0.0; 2]);
        // The problem's condition number is ~1e10; this is the error that implies.
        assert!(
            (b[0] - 0.3).abs() < 1e-5 && (b[1] - 0.7).abs() < 1e-5,
            "{b:?}"
        );
    }

    #[test]
    fn reports_the_singular_column() {
        let a = matrix(&[&[1.0, 0.0, 0.0], &[0.0, 0.0, 0.0], &[0.0, 0.0, 1.0]]);
        assert_eq!(Lu::factor(&a).unwrap_err(), Singular { column: 1 });
        let dependent = matrix(&[&[1.0, 2.0], &[2.0, 4.0]]);
        assert!(Lu::factor(&dependent).is_err());
    }
}
