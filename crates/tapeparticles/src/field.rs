//! The cell-averaged field of the coating's magnetization: per layer an FFT along the tape,
//! each wavenumber's layer-to-layer kernel (`varimu.devices.tape._demag_kernels`: the 2D
//! magnetostatics of uniformly magnetized layers, layer-averaged, with or without the
//! head's image), the inverse FFT. `varimu/tape_particles/medium.py`'s `cell_field` in
//! f64, the same transform length and kernels (the caller passes them).

use std::sync::Arc;

use rustfft::num_complex::Complex64;
use rustfft::{Fft, FftPlanner};

/// The kernels at the kept wavenumbers: kept[i] is the FFT bin, k[c][i][a][b] (c: xx, xy,
/// yx, yy) the field in layer a from layer b.
pub struct Kernels {
    pub kept: Vec<usize>,
    pub k: [Vec<Complex64>; 4],
}

pub struct CellField {
    pub n: usize,
    pub ncx: usize,
    pub layers: usize,
    fwd: Arc<dyn Fft<f64>>,
    inv: Arc<dyn Fft<f64>>,
}

impl CellField {
    pub fn new(n: usize, ncx: usize, layers: usize) -> Self {
        let mut p = FftPlanner::new();
        CellField {
            n,
            ncx,
            layers,
            fwd: p.plan_fft_forward(n),
            inv: p.plan_fft_inverse(n),
        }
    }

    /// (Hx, Hy) per cell (id = xcell * layers + layer) from (Mx, My) per cell (A/m).
    pub fn apply(&self, kern: &Kernels, mx: &[f64], my: &[f64]) -> (Vec<f64>, Vec<f64>) {
        let (n, ncx, nl) = (self.n, self.ncx, self.layers);
        let spec = |m: &[f64], l: usize| -> Vec<Complex64> {
            let mut v = vec![Complex64::new(0.0, 0.0); n];
            for c in 0..ncx {
                v[c].re = m[c * nl + l];
            }
            self.fwd.process(&mut v);
            v
        };
        let sx: Vec<Vec<Complex64>> = (0..nl).map(|l| spec(mx, l)).collect();
        let sy: Vec<Vec<Complex64>> = (0..nl).map(|l| spec(my, l)).collect();
        let mut hx = vec![vec![Complex64::new(0.0, 0.0); n]; nl];
        let mut hy = vec![vec![Complex64::new(0.0, 0.0); n]; nl];
        for (i, &bin) in kern.kept.iter().enumerate() {
            let base = i * nl * nl;
            for a in 0..nl {
                let (mut ax, mut ay) = (Complex64::new(0.0, 0.0), Complex64::new(0.0, 0.0));
                for b in 0..nl {
                    let j = base + a * nl + b;
                    ax += kern.k[0][j] * sx[b][bin] + kern.k[1][j] * sy[b][bin];
                    ay += kern.k[2][j] * sx[b][bin] + kern.k[3][j] * sy[b][bin];
                }
                hx[a][bin] = ax;
                hy[a][bin] = ay;
            }
        }
        let mut outx = vec![0.0; ncx * nl];
        let mut outy = vec![0.0; ncx * nl];
        for a in 0..nl {
            for (h, out) in [(&mut hx[a], &mut outx), (&mut hy[a], &mut outy)] {
                // A real signal's spectrum: Nyquist real (irfft drops its imaginary part),
                // the negative bins conjugate.
                h[n / 2].im = 0.0;
                for k in 1..n / 2 {
                    h[n - k] = h[k].conj();
                }
                h[0] = Complex64::new(h[0].re, 0.0);
                self.inv.process(h);
                for c in 0..ncx {
                    out[c * nl + a] = h[c].re / n as f64;
                }
            }
        }
        (outx, outy)
    }
}
