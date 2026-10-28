//! Pan and zoom (`varimu/listen/editor/camera.js`): screen = world * k + (x, y), world in
//! mm, screen in points from the canvas's top-left. Moves to a target are animated in
//! log zoom, so they feel even.

use std::time::Instant;

pub const K_MIN: f64 = 0.4;
pub const K_MAX: f64 = 80.0;
const ANIM_S: f64 = 0.26;

#[derive(Debug, Clone, Copy, PartialEq)]
pub struct View {
    pub x: f64,
    pub y: f64,
    pub k: f64,
}

#[derive(Debug, Clone)]
pub struct Camera {
    pub x: f64,
    pub y: f64,
    pub k: f64,
    /// The canvas's size.
    pub w: f64,
    pub h: f64,
    anim: Option<(View, View, Instant)>,
}

impl Default for Camera {
    fn default() -> Camera {
        Camera {
            x: 0.0,
            y: 0.0,
            k: 4.0,
            w: 800.0,
            h: 600.0,
            anim: None,
        }
    }
}

impl Camera {
    pub fn to_world(&self, sx: f64, sy: f64) -> (f64, f64) {
        ((sx - self.x) / self.k, (sy - self.y) / self.k)
    }

    pub fn to_screen(&self, wx: f64, wy: f64) -> (f64, f64) {
        (wx * self.k + self.x, wy * self.k + self.y)
    }

    pub fn set(&mut self, x: f64, y: f64, k: f64) {
        self.x = x;
        self.y = y;
        self.k = k.clamp(K_MIN, K_MAX);
    }

    pub fn zoom_at(&mut self, sx: f64, sy: f64, k: f64) {
        self.stop();
        let k = k.clamp(K_MIN, K_MAX);
        let (wx, wy) = self.to_world(sx, sy);
        self.set(sx - wx * k, sy - wy * k, k);
    }

    pub fn pan(&mut self, dx: f64, dy: f64) {
        self.stop();
        self.set(self.x + dx, self.y + dy, self.k);
    }

    /// The camera that shows world box [x0, y0, x1, y1] with `pad` points around it.
    pub fn framing(&self, b: [f64; 4], pad: f64, k_max: f64) -> View {
        let w = (b[2] - b[0]).max(1e-6);
        let h = (b[3] - b[1]).max(1e-6);
        let k = ((self.w - 2.0 * pad) / w)
            .min((self.h - 2.0 * pad) / h)
            .clamp(K_MIN, k_max.max(K_MIN));
        View {
            x: self.w / 2.0 - (b[0] + w / 2.0) * k,
            y: self.h / 2.0 - (b[1] + h / 2.0) * k,
            k,
        }
    }

    pub fn show(&mut self, b: [f64; 4], pad: f64, k_max: f64, animate: bool) {
        let t = self.framing(b, pad, k_max);
        if animate {
            let from = View {
                x: self.x,
                y: self.y,
                k: self.k,
            };
            self.anim = Some((from, t, Instant::now()));
        } else {
            self.stop();
            self.set(t.x, t.y, t.k);
        }
    }

    pub fn stop(&mut self) {
        self.anim = None;
    }

    pub fn animating(&self) -> bool {
        self.anim.is_some()
    }

    /// Advance an animation; true while one runs.
    pub fn tick(&mut self) -> bool {
        let Some((from, to, t0)) = self.anim else {
            return false;
        };
        let u = (t0.elapsed().as_secs_f64() / ANIM_S).min(1.0);
        let e = 1.0 - (1.0 - u).powi(3);
        let (cx, cy) = (self.w / 2.0, self.h / 2.0);
        let c0 = ((cx - from.x) / from.k, (cy - from.y) / from.k);
        let c1 = ((cx - to.x) / to.k, (cy - to.y) / to.k);
        let k = (from.k.ln() + (to.k.ln() - from.k.ln()) * e).exp();
        let (wx, wy) = (c0.0 + (c1.0 - c0.0) * e, c0.1 + (c1.1 - c0.1) * e);
        self.set(cx - wx * k, cy - wy * k, k);
        if u >= 1.0 {
            self.anim = None;
        }
        true
    }
}
