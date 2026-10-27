// Pan and zoom: screen = world * k + (x, y), world in mm. Wheel zooms at the cursor (a
// trackpad pinch too), dragging the empty canvas or the middle button pans, space + drag
// pans from anywhere. Moves to a target are animated.

const K_MIN = 0.4, K_MAX = 80;

export class Camera {
  constructor(el, onChange) {
    this.el = el;
    this.onChange = onChange;
    this.x = 0; this.y = 0; this.k = 4;
    this.anim = null;
    el.addEventListener('wheel', e => this.wheel(e), { passive: false });
  }

  toWorld(sx, sy) { return [(sx - this.x) / this.k, (sy - this.y) / this.k]; }
  toScreen(wx, wy) { return [wx * this.k + this.x, wy * this.k + this.y]; }

  set(x, y, k) {
    this.x = x; this.y = y; this.k = Math.min(K_MAX, Math.max(K_MIN, k));
    this.onChange(this);
  }

  wheel(e) {
    e.preventDefault();
    this.stop();
    const r = this.el.getBoundingClientRect();
    const sx = e.clientX - r.left, sy = e.clientY - r.top;
    // A pinch arrives as ctrl + wheel with small deltas; a mouse wheel as ~100 per notch.
    const dy = e.deltaMode === 1 ? e.deltaY * 33 : e.deltaY;
    if (!e.ctrlKey && Math.abs(e.deltaX) > Math.abs(dy) * 0.5 && e.deltaMode === 0 && Math.abs(dy) < 50) {
      this.set(this.x - e.deltaX, this.y - e.deltaY, this.k); // two-finger scroll pans
      return;
    }
    const f = Math.exp(-dy * (e.ctrlKey ? 0.01 : 0.0018));
    this.zoomAt(sx, sy, this.k * f);
  }

  zoomAt(sx, sy, k) {
    k = Math.min(K_MAX, Math.max(K_MIN, k));
    const [wx, wy] = this.toWorld(sx, sy);
    this.set(sx - wx * k, sy - wy * k, k);
  }

  pan(dx, dy) { this.set(this.x + dx, this.y + dy, this.k); }

  /** The camera that shows world box [x0, y0, x1, y1] with `pad` px around it. */
  framing(box, pad = 48, kMax = 14) {
    const r = this.el.getBoundingClientRect();
    const w = Math.max(1e-6, box[2] - box[0]), h = Math.max(1e-6, box[3] - box[1]);
    const k = Math.min(kMax, Math.max(K_MIN, Math.min((r.width - 2 * pad) / w, (r.height - 2 * pad) / h)));
    return { x: r.width / 2 - (box[0] + w / 2) * k, y: r.height / 2 - (box[1] + h / 2) * k, k };
  }

  show(box, { pad = 48, kMax = 14, animate = true } = {}) {
    const t = this.framing(box, pad, kMax);
    if (!animate) { this.set(t.x, t.y, t.k); return; }
    this.animateTo(t);
  }

  animateTo(t, ms = 260) {
    this.stop();
    const from = { x: this.x, y: this.y, k: this.k }, t0 = performance.now();
    // Interpolate in log zoom so the move feels even, keeping the screen centre's path smooth.
    const r = this.el.getBoundingClientRect(), cx = r.width / 2, cy = r.height / 2;
    const c0 = [(cx - from.x) / from.k, (cy - from.y) / from.k], c1 = [(cx - t.x) / t.k, (cy - t.y) / t.k];
    const step = now => {
      const u = Math.min(1, (now - t0) / ms), e = 1 - (1 - u) ** 3;
      const k = Math.exp(Math.log(from.k) + (Math.log(t.k) - Math.log(from.k)) * e);
      const wx = c0[0] + (c1[0] - c0[0]) * e, wy = c0[1] + (c1[1] - c0[1]) * e;
      this.set(cx - wx * k, cy - wy * k, k);
      this.anim = u < 1 ? requestAnimationFrame(step) : null;
    };
    this.anim = requestAnimationFrame(step);
  }

  stop() { if (this.anim) cancelAnimationFrame(this.anim); this.anim = null; }
}
