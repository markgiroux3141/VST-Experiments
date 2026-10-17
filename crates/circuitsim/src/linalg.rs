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
pub fn gemv_add(y: &mut [f64], a: &[f64], row0: usize, lda: usize, x: &[f64]) {
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
    /// garbage until the next successful factorization.
    pub fn factor(&mut self, a: &[f64]) -> Result<(), Singular> {
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

#[cfg(test)]
mod tests {
    use super::*;

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
