//! The kernel's f64 CPU reference, step for step with `record.wgsl` (and with circuitsim's
//! `tape::record`, of which it is a single-threaded copy on [`Block`]'s inputs).

use crate::{Block, sum_axes};

fn catmull_rom(f: f64) -> [f64; 4] {
    let f2 = f * f;
    let f3 = f * f * f;
    [
        -0.5 * f3 + f2 - 0.5 * f,
        1.5 * f3 - 2.5 * f2 + 1.0,
        -1.5 * f3 + 2.0 * f2 + 0.5 * f,
        0.5 * f3 - 0.5 * f2,
    ]
}

struct Tabs<'a> {
    h_max: f64,
    n: usize,
    q: &'a [f64],
    d: &'a [f64],
}

impl Tabs<'_> {
    fn node(&self, x: f64) -> (usize, f64) {
        let h = self.h_max;
        let u = (x.clamp(-h, h) + h) * (self.n as f64 / (2.0 * h));
        let i = (u.floor().max(0.0) as usize).min(self.n - 1);
        (i, u - i as f64)
    }

    fn tap(&self, i: usize, k: usize) -> usize {
        (i + k).saturating_sub(1).min(self.n)
    }

    fn q_at(&self, a: f64, ib: usize, wb: &[f64; 4]) -> f64 {
        let (ia, fa) = self.node(a);
        let wa = catmull_rom(fa);
        let m = self.n + 1;
        let mut out = 0.0;
        for (da, wa) in wa.iter().enumerate() {
            let ra = self.tap(ia, da);
            let mut acc = 0.0;
            for (db, wb) in wb.iter().enumerate() {
                acc += wb * self.q[ra * m + self.tap(ib, db)];
            }
            out += wa * acc;
        }
        out
    }

    fn q(&self, a: f64, b: f64) -> f64 {
        let (ib, fb) = self.node(b);
        self.q_at(a, ib, &catmull_rom(fb))
    }

    fn q_diff(&self, a1: f64, a0: f64, b: f64) -> f64 {
        let (ib, fb) = self.node(b);
        let wb = catmull_rom(fb);
        self.q_at(a1, ib, &wb) - self.q_at(a0, ib, &wb)
    }

    fn d(&self, x: f64) -> f64 {
        let (i, f) = self.node(x);
        let w = catmull_rom(f);
        w.iter()
            .enumerate()
            .map(|(k, w)| w * self.d[self.tap(i, k)])
            .sum()
    }
}

/// ln(z - a) - ln(z - b) for z = x + iy, y > 0: (real, imaginary).
fn log_ratio(x: f64, y: f64, a: f64, b: f64) -> (f64, f64) {
    let (xa, xb) = (x - a, x - b);
    let re = 0.5 * ((xa * xa + y * y) / (xb * xb + y * y)).ln();
    let im = y.atan2(xa) - y.atan2(xb);
    (re, im)
}

/// (Hx, Hy) / Hg at (x, y), y > 0 (circuitsim's `tape::head_field`).
pub fn head_field(head: [f64; 3], x: f64, y: f64) -> (f64, f64) {
    let [g, pole, relax] = head;
    let e = g / 2.0 + pole;
    let (mut re, mut im) = log_ratio(x, y, -g / 2.0, g / 2.0);
    re = -re;
    im = -im;
    if relax <= 0.0 {
        for xe in [-e, e] {
            let (dx, r2) = (x - xe, (x - xe) * (x - xe) + y * y);
            re += (g / 2.0) * dx / r2;
            im += -(g / 2.0) * y / r2;
        }
    } else {
        let c = g / 2.0 / relax;
        for (a, b) in [(-e - relax, -e), (e, e + relax)] {
            let (r, i) = log_ratio(x, y, a, b);
            re += c * r;
            im += c * i;
        }
    }
    let pi = std::f64::consts::PI;
    (im / pi, re / pi)
}

/// The kernel in f64 (the GPU's [`crate::record`] on the CPU).
pub fn record(b: &Block<'_>) -> Result<(Vec<f64>, Vec<f64>), String> {
    b.check()?;
    let t = Tabs {
        h_max: b.tables.h_max,
        n: b.tables.n,
        q: b.tables.q,
        d: b.tables.d,
    };
    let (layers, cells, n_axes) = (b.heights.len(), b.s_cells.len(), b.axes.len());
    let big = 4.0 * t.h_max;
    let mut m = vec![0.0; layers * n_axes * cells];
    for l in 0..layers {
        let y = b.heights[l];
        for ci in 0..cells {
            let lc = l * cells + ci;
            let [sx, sy, ex, ey] = b.steady(lc);
            let [k0, k1] = b.ranges[lc];
            for (ai, a) in b.axes.iter().enumerate() {
                let (mut nmax, mut nmin, mut up) = (f64::NEG_INFINITY, f64::INFINITY, 0.0);
                let mut push = |x: f64| {
                    if x > nmax {
                        up += t.q_diff(x, nmax.max(-big), nmin.min(big));
                    }
                    nmax = nmax.max(x);
                    nmin = nmin.min(x);
                };
                let hs = a[0] * sx + a[1] * sy;
                push(a[0] * ex + a[1] * ey);
                push(hs);
                for j in (k0 as usize..(k1 as usize).max(k0 as usize)).rev() {
                    let x = b.s_cells[ci] - b.s_rec[j];
                    let (fx, fy) = match b.field {
                        Some(f) => {
                            let ft = &f[l];
                            let u = (x - ft.x0) * ft.inv_dx;
                            let i = (u.floor() as usize).clamp(1, ft.fx.len() - 3);
                            let w = catmull_rom(u - i as f64);
                            let (mut p, mut q) = (0.0, 0.0);
                            for (k, w) in w.iter().enumerate() {
                                p += w * ft.fx[i + k - 1];
                                q += w * ft.fy[i + k - 1];
                            }
                            (p, q)
                        }
                        None => head_field(b.head, x, y),
                    };
                    let (fx, fy) = (b.hg[j] * fx, b.hg[j] * fy);
                    push(a[0] * fx + a[1] * fy + hs);
                }
                let x = nmax.max(-nmin);
                up += t.q(x, nmin) - t.q(nmax, nmin) + t.d(x);
                m[(l * n_axes + ai) * cells + ci] = 2.0 * up - 1.0;
            }
        }
    }
    Ok(sum_axes(b.axes, layers, cells, |l, a, c| {
        m[(l * n_axes + a) * cells + c]
    }))
}
