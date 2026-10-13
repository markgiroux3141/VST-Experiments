"""Relight the knob so its lighting stays fixed while it turns.

Knob.png has its studio lighting painted in, so rotating the image rotates the
highlights too. This script rebuilds the knob as:

  height map  a hand-fitted model of the knob's shape (dome, lip, groove,
              skirt, rim, scallops), measured from the art
  matcap      the image's own lighting as a function of surface direction,
              learned from the pixels (so highlights keep their painted look)
  detail      everything the matcap doesn't explain: scratches, wear, the
              pointer; this layer turns with the knob

For each angle it rotates the shape and detail, looks the lighting up again
with the rotated surface directions, and re-applies the camera's slight
perspective (tall parts appear shifted up), which is fixed to the screen.
At 0 degrees the output reproduces the original image.

Output: img/knob-strip.webp, a grid of frames, plus knob-strip.json/.js metadata.

Run:  python relight_knob.py              (--png also writes a lossless PNG strip)
      python relight_knob.py --preview    (naive vs relit comparison sheet)
"""
import json
import sys
from pathlib import Path

import cv2
import numpy as np

HERE = Path(__file__).parent
SRC = HERE.parent / "assets" / "UI parts" / "Knob.png"
OUT = HERE / "img"

# ---- measured from Knob.png (source px) ----
CENTER = (626.4, 636.3)   # centre of the outer silhouette
HALF = 520                # crop half-size around CENTER
PARALLAX = 0.235          # screen-y shift per unit height: the cap (h~110) appears ~25 px high
POINTER_HALF_WIDTH = 24   # cream pointer inlay, excluded when learning the lighting
# Scallop centres (degrees clockwise from 12 o'clock); they are irregular in the art.
SCALLOPS = [27, 63, 108, 152.5, 207.5, 251, 295, 335]

# ---- working / output resolution ----
WORK = 768                # internal resolution (supersampled)
FRAME = 256               # output frame size
STEP_DEG = 2.5            # 144 frames over a full turn
COLS = 12
MATCAP_BINS = 128


def radial_profile(r):
    """Height (source px) of the rotationally symmetric part at radius r."""
    h = np.zeros_like(r)
    def seg(lo, hi):
        return (r >= lo) & (r < hi)
    # Domed cap.
    m = r < 300
    h[m] = 110 - 18 * (r[m] / 300) ** 2
    # Rounded cap edge.
    m = seg(300, 338)
    t = (r[m] - 300) / 38
    h[m] = 62 + 30 * np.sqrt(np.clip(1 - t ** 2, 0, 1))
    # Groove.
    m = seg(338, 356)
    t = (r[m] - 338) / 18
    h[m] = 62 - 14 * np.sin(t * np.pi / 2)
    # Inner lip of the skirt.
    m = seg(356, 368)
    t = (r[m] - 356) / 12
    h[m] = 48 + 22 * np.sin(t * np.pi / 2)
    # Skirt, falling away convexly.
    m = seg(368, 480)
    t = (r[m] - 368) / 112
    h[m] = 70 - 32 * t ** 1.5
    # Outer round-over.
    m = seg(480, 512)
    t = (r[m] - 480) / 28
    h[m] = 38 * np.sqrt(np.clip(1 - t ** 2, 0, 1))
    return h


def scallop_depth(r, theta_deg):
    """Concave scoops cut into the rim."""
    d = np.zeros_like(r)
    for c in SCALLOPS:
        dt = (theta_deg - c + 180) % 360 - 180          # signed angular distance
        u = np.hypot((r - 482) / 46, dt / 15)
        d += 22 * np.clip(1 - u ** 2, 0, None) ** 1.5
    return d


def height_map(n):
    """Height field on an n x n grid covering the crop, in source px units."""
    s = 2 * HALF / n
    y, x = np.mgrid[0:n, 0:n].astype(np.float32)
    x = (x - (n - 1) / 2) * s
    y = (y - (n - 1) / 2) * s
    r = np.hypot(x, y)
    theta = np.degrees(np.arctan2(x, -y)) % 360
    return (radial_profile(r) - scallop_depth(r, theta)).astype(np.float32), r


def normals(h, n):
    s = 2 * HALF / n
    hy, hx = np.gradient(cv2.GaussianBlur(h, (0, 0), 1.0), s)
    v = np.dstack([-hx, -hy, np.ones_like(h)])
    return v / np.linalg.norm(v, axis=2, keepdims=True)


def remap_y(img, dy):
    """Sample img at (x, y + dy) for every output pixel."""
    n = img.shape[0]
    y, x = np.mgrid[0:n, 0:n].astype(np.float32)
    return cv2.remap(img, x, y + dy.astype(np.float32), cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT)


def load_knob(n):
    src = cv2.imread(str(SRC), cv2.IMREAD_UNCHANGED).astype(np.float32) / 255
    src = src[..., [2, 1, 0, 3]]                                   # BGRA -> RGBA
    src[..., :3] *= src[..., 3:4]                                   # premultiply before resampling
    shift = np.float32([[1, 0, HALF - CENTER[0]], [0, 1, HALF - CENTER[1]]])
    crop = cv2.warpAffine(src, shift, (2 * HALF, 2 * HALF), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT)
    return cv2.resize(crop, (n, n), interpolation=cv2.INTER_AREA)


def to_ortho(img, h, n):
    """Undo the perspective: a point of height h shows up k*h px higher in the art."""
    return remap_y(img, -PARALLAX * h * n / (2 * HALF))


def to_screen(img, h, n):
    """Re-apply the perspective (inverse of to_ortho, solved by fixed-point iteration)."""
    k = PARALLAX * n / (2 * HALF)
    dy = np.zeros_like(h)
    for _ in range(4):
        dy = k * remap_y(h, dy)
    return remap_y(img, dy)


def learn_matcap(rgb, nrm, use):
    """Median colour per surface direction, holes filled, lightly smoothed."""
    b = MATCAP_BINS
    ix = np.clip(((nrm[..., 0] + 1) / 2 * b).astype(int), 0, b - 1)
    iy = np.clip(((nrm[..., 1] + 1) / 2 * b).astype(int), 0, b - 1)
    key = (iy * b + ix)[use]
    vals = rgb[use]
    order = np.argsort(key, kind="stable")
    key, vals = key[order], vals[order]
    cap = np.zeros((b * b, 3), np.float32)
    have = np.zeros(b * b, bool)
    starts = np.r_[0, np.flatnonzero(np.diff(key)) + 1]
    ends = np.r_[starts[1:], len(key)]
    for a, e in zip(starts, ends):
        if e - a >= 3:
            cap[key[a]] = np.median(vals[a:e], axis=0)
            have[key[a]] = True
    cap = cap.reshape(b, b, 3)
    have = have.reshape(b, b)
    # Fill unsampled directions by repeated neighbour averaging, then smooth.
    filled = cap.copy()
    w = have.astype(np.float32)
    for _ in range(200):
        if w.min() > 0:
            break
        num = cv2.blur(filled * w[..., None], (3, 3))
        den = cv2.blur(w, (3, 3))[..., None]
        grow = (w == 0) & (den[..., 0] > 0)
        filled[grow] = (num / np.maximum(den, 1e-6))[grow]
        w = np.maximum(w, grow.astype(np.float32))
    smooth = cv2.GaussianBlur(filled, (0, 0), 1.0)
    print(f"  matcap: {have.mean():.0%} of directions sampled directly")
    return smooth


def sample_matcap(cap, nrm):
    b = cap.shape[0]
    mx = ((nrm[..., 0] + 1) / 2 * b - 0.5).astype(np.float32)
    my = ((nrm[..., 1] + 1) / 2 * b - 0.5).astype(np.float32)
    return cv2.remap(cap, mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)


def rotate(img, deg, n):
    m = cv2.getRotationMatrix2D(((n - 1) / 2, (n - 1) / 2), -deg, 1.0)   # clockwise
    return cv2.warpAffine(img, m, (n, n), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT)


def polar_grid(n, na, nr):
    """Sampling maps for a polar image: rows = radius (working px), cols = angle."""
    th = np.linspace(0, 2 * np.pi, na, endpoint=False, dtype=np.float32)
    r = np.arange(nr, dtype=np.float32)
    t, rr = np.meshgrid(th, r)
    c = (n - 1) / 2
    return (c + rr * np.sin(t)).astype(np.float32), (c - rr * np.cos(t)).astype(np.float32)


def from_polar(p, n):
    """Inverse of sampling with polar_grid: cartesian n x n image from a polar image."""
    nr, na = p.shape[:2]
    wrapped = np.concatenate([p[:, -1:], p, p[:, :1]], axis=1)       # periodic in angle
    y, x = np.mgrid[0:n, 0:n].astype(np.float32)
    c = (n - 1) / 2
    r = np.hypot(x - c, y - c)
    th = np.arctan2(x - c, -(y - c)) % (2 * np.pi)
    return cv2.remap(wrapped, (th / (2 * np.pi) * na + 1).astype(np.float32), r.astype(np.float32),
                     cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)


def fill_angular(p, bad):
    """Replace masked samples by interpolating around each ring (periodic)."""
    out = p.copy()
    na = p.shape[1]
    idx = np.arange(na)
    for i in range(p.shape[0] - 1, -1, -1):
        good = ~bad[i]
        if good.sum() < na * 0.15:          # ring is mostly masked (near the centre)
            out[i] = out[i + 1] if i + 1 < p.shape[0] else out[i]
            continue
        if good.all():
            continue
        gi = idx[good]
        for ch in range(p.shape[2]):
            out[i, ~good, ch] = np.interp(idx[~good], gi, p[i, good, ch], period=na)
    return out


# Radial zones (source px) for the screen-fixed lighting estimate, and the radial
# median half-window used in each. Where the profile curves fast (cap edge,
# groove, lip) the window stays small so the lighting isn't smeared.
RADIAL_WINDOWS = [(0, 285, 7), (285, 375, 2), (375, 1000, 6)]
OUTER_BAND = (425, 440)   # beyond this the scallops break symmetry: use the matcap
CAP_SMOOTH = (262, 285, 14)  # cap lighting is blurred (sigma 14) inside r=262, fading out by 285


class Knob:
    def __init__(self, n=WORK):
        self.n = n
        s = 2 * HALF / n                      # source px per working px
        self.h, r = height_map(n)
        self.nrm = normals(self.h, n)

        screen = load_knob(n)
        ortho = to_ortho(screen, self.h, n)
        self.alpha = ortho[..., 3]
        rgb = ortho[..., :3] / np.maximum(self.alpha[..., None], 1e-4)

        # Things that belong to the knob's surface, not the lighting.
        y, x = np.mgrid[0:n, 0:n].astype(np.float32)
        x = (x - (n - 1) / 2) * s
        y = (y - (n - 1) / 2) * s
        lum = rgb @ np.array([0.3, 0.59, 0.11], np.float32)
        warm = rgb[..., 0] - rgb[..., 2]
        wear = cv2.dilate(((lum > 0.30) & (warm > 0.07)).astype(np.uint8), np.ones((5, 5), np.uint8)) > 0
        pointer = (np.abs(x) < POINTER_HALF_WIDTH + 10) & (y < 12) & (r < 475)
        surface = wear | pointer

        # 1) Inner, rotationally symmetric part: the lighting at a screen position never
        #    changes, so read it from the image. Filter along the radius (reflections run
        #    radially, scratches mostly don't) after patching over wear and the pointer.
        na, nr = 2048, int(OUTER_BAND[1] / s) + 4
        mx, my = polar_grid(n, na, nr)
        pol = cv2.remap(rgb, mx, my, cv2.INTER_LINEAR)
        bad = cv2.remap(surface.astype(np.float32), mx, my, cv2.INTER_LINEAR) > 0.1
        pol = fill_angular(pol, bad)
        from scipy.ndimage import median_filter
        lit = np.empty_like(pol)
        radius_src = np.arange(nr) * s
        for lo, hi, w in RADIAL_WINDOWS:
            rows = (radius_src >= lo) & (radius_src < hi)
            if rows.any():
                k = max(1, round(w / s))
                med = median_filter(pol, size=(2 * k + 1, 3, 1), mode="nearest")
                lit[rows] = med[rows]
        inner = from_polar(lit, n)
        # The domed cap's lighting is a soft gradient; anything finer there is texture.
        # Smooth it with a normalised blur that only looks at the cap itself.
        cap_zone = (r < CAP_SMOOTH[1]).astype(np.float32)
        sigma = CAP_SMOOTH[2] / s
        blurred = (cv2.GaussianBlur(inner * cap_zone[..., None], (0, 0), sigma)
                   / np.maximum(cv2.GaussianBlur(cap_zone, (0, 0), sigma), 1e-4)[..., None])
        w = np.clip((CAP_SMOOTH[1] - r) / (CAP_SMOOTH[1] - CAP_SMOOTH[0]), 0, 1)[..., None]
        self.inner = inner * (1 - w) + blurred * w

        # 2) Scalloped rim: lighting depends on the surface direction there, so learn a
        #    matcap from the rim's clean plastic and re-evaluate it as the rim turns.
        lo, hi = OUTER_BAND
        self.band = np.clip((r - lo) / (hi - lo), 0, 1)[..., None].astype(np.float32)
        use = (self.alpha > 0.98) & ~surface & (r > lo - 10)
        self.cap = learn_matcap(rgb, self.nrm, use)

        # Detail = what the lighting doesn't explain; it turns with the knob.
        self.detail = (rgb - self.lighting(self.nrm)) * (self.alpha[..., None] > 0)

    def lighting(self, nrm):
        return self.inner * (1 - self.band) + sample_matcap(self.cap, nrm) * self.band

    def render(self, deg):
        n = self.n
        h = rotate(self.h, deg, n)
        nrm = rotate(self.nrm, deg, n)
        c, s = np.cos(np.radians(deg)), np.sin(np.radians(deg))
        nx = nrm[..., 0] * c - nrm[..., 1] * s
        ny = nrm[..., 0] * s + nrm[..., 1] * c
        nrm = np.dstack([nx, ny, nrm[..., 2]])
        rgb = np.clip(self.lighting(nrm) + rotate(self.detail, deg, n), 0, 1)
        a = rotate(self.alpha, deg, n)
        out = np.dstack([rgb * a[..., None], a])                    # premultiplied
        return to_screen(out, h, n)


def to_png(premul, size):
    img = cv2.resize(premul, (size, size), interpolation=cv2.INTER_AREA)
    a = img[..., 3:4]
    rgb = img[..., :3] / np.maximum(a, 1e-4)
    out = np.clip(np.dstack([rgb, a]) * 255 + 0.5, 0, 255).astype(np.uint8)
    return out[..., [2, 1, 0, 3]]                                    # RGBA -> BGRA for cv2


def build_strip(knob):
    count = round(360 / STEP_DEG)
    rows = -(-count // COLS)
    sheet = np.zeros((rows * FRAME, COLS * FRAME, 4), np.uint8)
    for i in range(count):
        f = to_png(knob.render(i * STEP_DEG), FRAME)
        r, c = divmod(i, COLS)
        sheet[r * FRAME:(r + 1) * FRAME, c * FRAME:(c + 1) * FRAME] = f
    # WebP keeps alpha at a quarter of the PNG size; --png also writes a lossless
    # PNG (the usual filmstrip format for a JUCE plugin).
    cv2.imwrite(str(OUT / "knob-strip.webp"), sheet, [cv2.IMWRITE_WEBP_QUALITY, 92])
    if "--png" in sys.argv:
        cv2.imwrite(str(OUT / "knob-strip.png"), sheet, [cv2.IMWRITE_PNG_COMPRESSION, 9])
    meta = {"frames": count, "stepDeg": STEP_DEG, "cols": COLS, "frameSize": FRAME,
            # Knob body diameter as a fraction of the frame (crop is 2*HALF source px).
            "bodyFraction": 1017 / (2 * HALF)}
    (OUT / "knob-strip.json").write_text(json.dumps(meta, indent=1))
    # Same data as a script, since pages opened from file:// can't fetch JSON.
    (OUT / "knob-strip.js").write_text("// Generated by relight_knob.py - do not edit.\n"
                                       "window.KNOB_STRIP = " + json.dumps(meta) + ";\n")
    size = (OUT / "knob-strip.webp").stat().st_size / 1e6
    print(f"  knob-strip.webp  {count} frames, {COLS}x{rows} grid of {FRAME}px, {size:.1f} MB")


def preview(knob, path):
    """Naive rotation (top) vs relit (bottom) at a few angles, on a panel-ish grey."""
    angles = [0, -120, -60, 60, 120]
    naive_src = load_knob(knob.n)
    tiles = []
    for row in ("naive", "relit"):
        cells = []
        for a in angles:
            img = rotate(naive_src, a, knob.n) if row == "naive" else knob.render(a)
            img = cv2.resize(img, (300, 300), interpolation=cv2.INTER_AREA)
            bg = np.array([0.62, 0.57, 0.48], np.float32)
            comp = img[..., :3] + bg * (1 - img[..., 3:4])
            cells.append(comp)
        tiles.append(np.hstack(cells))
    sheet = (np.clip(np.vstack(tiles), 0, 1) * 255).astype(np.uint8)[..., ::-1]
    cv2.imwrite(str(path), sheet)
    print(f"  preview -> {path}")


if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    k = Knob()
    if "--preview" in sys.argv:
        i = sys.argv.index("--preview")
        preview(k, Path(sys.argv[i + 1]) if len(sys.argv) > i + 1 else HERE / "knob-preview.png")
    else:
        build_strip(k)
