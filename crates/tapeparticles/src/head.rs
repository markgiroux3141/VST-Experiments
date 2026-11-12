//! The record head's field per unit deep-gap field: `varimu.devices.tape.head_field` (a
//! gap and finite pole faces whose potential relaxes linearly over r), in f64.

use std::f64::consts::PI;

#[derive(Debug, Clone, Copy)]
pub struct Head {
    pub gap: f64,
    pub pole: f64,
    pub relax: f64,
}

/// arg(z - a) - arg(z - b) and ln|z - a| - ln|z - b| for z = x + i y.
#[inline]
fn seg(x: f64, y: f64, a: f64, b: f64) -> (f64, f64) {
    let (xa, xb) = (x - a, x - b);
    let im = y.atan2(xa) - y.atan2(xb);
    let re = 0.5 * ((xa * xa + y * y).ln() - (xb * xb + y * y).ln());
    (re, im)
}

/// (Hx, Hy) / Hg at x from the gap's centre, height y > 0 (Hy positive away from the head).
pub fn field(h: &Head, x: f64, y: f64) -> (f64, f64) {
    let (g, p, r) = (h.gap, h.pole, h.relax);
    let e = g / 2.0 + p;
    // acc = seg(-1, -g/2, g/2) + ...; Hx = Im(acc) / pi, Hy = Re(acc) / pi.
    let (re0, im0) = seg(x, y, -g / 2.0, g / 2.0);
    let (mut re, mut im) = (-re0, -im0);
    if r <= 0.0 {
        // (g/2) / (z + e) + (g/2) / (z - e).
        for c in [-e, e] {
            let (dx, d2) = (x - c, (x - c) * (x - c) + y * y);
            re += (g / 2.0) * dx / d2;
            im += -(g / 2.0) * y / d2;
        }
    } else {
        let w = g / 2.0 / r;
        let (r1, i1) = seg(x, y, -e - r, -e);
        let (r2, i2) = seg(x, y, e, e + r);
        re += w * (r1 + r2);
        im += w * (i1 + i2);
    }
    (im / PI, re / PI)
}
