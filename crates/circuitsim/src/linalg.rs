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
            for i in k + 1..n {
                let f = lu.get(i, k) / pivot;
                if f == 0.0 {
                    continue;
                }
                lu.a[i * n + k] = f;
                for j in k + 1..n {
                    lu.a[i * n + j] -= f * lu.a[k * n + j];
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
