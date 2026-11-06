"""Digitize the RCA 77-DX's response and pattern figures into CSV (CHAINS_PLAN.md WP7 step 3).

Reproduces data/datasheets/rca_77dx_response.csv and rca_77dx_polar.csv from RCA's
IB-24884-2 (provenance: rca_77dx.provenance.yaml; the PDF is git-ignored, its copy in
cache/sources/rca_77dx/, URL and sha256 in data/schematics/rca_77dx/README.md). Needs PyMuPDF:

    uv run --with pymupdf python scripts/digitize_rca_77dx.py [--overlays DIR]

Both figures are read on the PDF's own 1-bit foreground masks (~262 dpi, not resampled):
page 9 (Fig. 5, the response) is one image, page 8 (Fig. 4, the patterns) five full-width
strips stacked.

Fig. 5: three charts (U, B, N), each with M, V1, V2. Per chart the ruled lines are found on
row / column darkness profiles: frequency log-linear through the 26 vertical rules (50 Hz to
20 kHz), level through the 8 horizontal rules (+10 to -25 dB, 5 dB apart), each horizontal
rule fitted as a tilted line (the scan's turn, up to 4.6 px per 1000). The rules are erased
where no curve touches them (an ink run lying within a rule's +-2.5 px band), the curve labels
dropped as small connected components, and the curves followed column by column from the
chart's left frame (seeded there, M above, V1, V2 below) by continuity; a curve riding exactly
on a rule takes the rule's level ("rule"). Values at the grid frequencies from the followed
columns within +-3 px.

Fig. 4: six polar charts (U, B, N, L-1, L-2, L-3). Per chart the centre is the one that
makes the dB rings sharpest; the chart is unwrapped to (radius, angle), the rings (one per 5 dB,
0 dB at r ~ 213.5 px) and the drawn rays (every 10 degrees inside the -5 dB ring, every 5
outside) erased the same way. The curves (3-4 per chart, told apart only by line style:
thick solid, long dash, medium dash, dash-dot) cross and break too often to follow
automatically, so each value is a run read on rays 2.5 degrees either side of the angle (and
mirrored, the charts are drawn symmetric), the run nearest an identified guide level
(`POLAR`, its curve told by the chart's labelled arrows), averaged over the rays that have it.
Levels inside the -15 dB ring can't be read (the rays converge): those rows are bounds.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import math
from pathlib import Path

import fitz  # PyMuPDF
import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage

REPO = Path(__file__).resolve().parents[1]
PDF = REPO / "cache/sources/rca_77dx/RCA-BCA-77-Mic.pdf"
PDF_SHA256 = "4bc60769ed32dd610928af12c60e637d93a7f414efa355844d021b7ab235821b"
OUT = REPO / "data/datasheets"

# ---------------------------------------------------------------------------- the masks


def page_mask(doc: fitz.Document, pno: int) -> np.ndarray:
    """A page's full-size 1-bit foreground (one image or full-width strips), ink = True."""
    page = doc[pno - 1]
    strips = []
    for img in sorted(page.get_images(full=True), key=lambda i: int(i[7][1:])):
        if img[2] > 2000 and img[4] == 1:
            data = doc.extract_image(img[0])["image"]
            strips.append(np.array(Image.open(io.BytesIO(data)).convert("L")) < 128)
    ink = np.vstack(strips)
    return ~ink if ink.mean() > 0.5 else ink


def groups(idx, gap: int = 2) -> list[list[int]]:
    out: list[list[int]] = []
    for i in idx:
        if out and i - out[-1][-1] <= gap:
            out[-1].append(int(i))
        else:
            out.append([int(i)])
    return out


def erase_band(line: np.ndarray, c: float, half: float = 2.5) -> None:
    """Across a rule centred at c: erase the ink run through it when the run lies within
    c +- half (the rule alone); a longer run is a curve crossing or riding it."""
    lo, hi = int(np.floor(c - half - 1)), int(np.ceil(c + half + 1))
    lo = max(lo, 0)
    seg = line[lo : hi + 1]
    i = 0
    while i < len(seg):
        if seg[i]:
            j = i
            while j + 1 < len(seg) and seg[j + 1]:
                j += 1
            if lo + i >= c - half and lo + j <= c + half:
                line[lo + i : lo + j + 1] = False
            i = j + 1
        else:
            i += 1


# ------------------------------------------------------------------------ Fig. 5 response

CHARTS = {"U": (380, 990), "B": (1070, 1680), "N": (1760, 2360)}  # rows holding the rules
SEEDS = {  # each curve's row at the chart's left frame (50 Hz), M above, V1, V2 below
    "U": {"M": 599.5, "V1": 789.5, "V2": 866.5},
    "B": {"M": 1350.5, "V1": 1538.5, "V2": 1638.0},
    "N": {"M": 1958.0, "V1": 2116.0, "V2": 2216.5},
}
RULE_FREQS = [
    50,
    60,
    70,
    80,
    90,
    100,
    200,
    300,
    400,
    500,
    600,
    700,
    800,
    900,
    1000,
    2000,
    3000,
    4000,
    5000,
    6000,
    7000,
    8000,
    9000,
    10000,
    15000,
    20000,
]
LEVELS = 10.0 - 5.0 * np.arange(8)
FREQS = [
    50,
    55,
    60,
    65,
    70,
    75,
    80,
    85,
    90,
    95,
    100,
    105,
    110,
    115,
    120,
    125,
    130,
    135,
    140,
    145,
    150,
    155,
    160,
    165,
    170,
    175,
    180,
    190,
    200,
    210,
    225,
    240,
    250,
    275,
    300,
    325,
    350,
    375,
    400,
    450,
    500,
    550,
    600,
    650,
    700,
    750,
    800,
    900,
    1000,
    1100,
    1250,
    1400,
    1600,
    1800,
    2000,
    2250,
    2500,
    2750,
    3000,
    3250,
    3500,
    3750,
    4000,
    4250,
    4500,
    4750,
    5000,
    5250,
    5500,
    5750,
    6000,
    6500,
    7000,
    7500,
    8000,
    8500,
    9000,
    9500,
    10000,
    10500,
    11000,
    11500,
    12000,
    12500,
    13000,
    13500,
    14000,
    14500,
    15000,
]


class Chart:
    """One response chart's axes on the page mask (modified in place: rules and labels go)."""

    def __init__(self, ink: np.ndarray, y0: int, y1: int):
        self.ink = ink
        rows = ink[y0:y1].sum(1)
        hr = [
            float(np.average(np.array(g) + y0, weights=rows[g]))
            for g in groups(np.where(rows > 800)[0])
        ]
        cols = ink[y0:y1].sum(0)
        vr = [
            float(np.average(g, weights=cols[g]))
            for g in groups(np.where(cols > 0.6 * (y1 - y0))[0])
        ][1:-1]  # the figure's border
        if len(vr) != len(RULE_FREQS) or len(hr) != 8:
            raise SystemExit(f"rules: {len(vr)} vertical, {len(hr)} horizontal")
        self.vr = np.array(vr)
        lf = np.log10(RULE_FREQS)
        self.bx, self.ax = np.polyfit(vr, lf, 1)
        self.res_x_px = float(np.max(np.abs(self.ax + self.bx * self.vr - lf)) / self.bx)
        self.lines = [self._fit_rule(y) for y in hr]
        mid = (vr[0] + vr[-1]) / 2
        ym = np.array([np.polyval(p, mid) for p in self.lines])
        by, ay = np.polyfit(ym, LEVELS, 1)
        self.px_per_db = 1 / abs(by)
        self.res_y_px = float(np.max(np.abs(ay + by * ym - LEVELS)) / abs(by))
        self.vlines = [self._fit_vrule(x, min(hr), max(hr)) for x in vr]

    def _fit_rule(self, y: float) -> np.ndarray:
        xs, cs = [], []
        for x0 in range(int(self.vr[0]) + 6, int(self.vr[-1]) - 40, 40):
            yy = np.arange(int(y) - 6, int(y) + 7)
            band = yy[self.ink[yy, x0 : x0 + 40].mean(1) > 0.85]
            if 2 <= len(band) <= 4 and band.max() - band.min() == len(band) - 1:
                xs.append(x0 + 20)
                cs.append(band.mean())
        xs, cs = np.array(xs), np.array(cs)
        for _ in range(3):
            p = np.polyfit(xs, cs, 1)
            r = np.abs(np.polyval(p, xs) - cs)
            keep = r < max(0.75, 2.5 * np.median(r))
            xs, cs = xs[keep], cs[keep]
        return np.polyfit(xs, cs, 1)

    def _fit_vrule(self, x: float, ya: float, yb: float) -> tuple[np.ndarray, float]:
        ys, cs = [], []
        for y0 in range(int(ya) + 6, int(yb) - 40, 40):
            xx = np.arange(int(x) - 6, int(x) + 7)
            band = xx[self.ink[y0 : y0 + 40, xx].mean(0) > 0.85]
            if 2 <= len(band) <= 6 and band.max() - band.min() == len(band) - 1:
                ys.append(y0 + 20)
                cs.append((band.min(), band.max()))
        c = np.array(cs, float)
        return np.polyfit(ys, c.mean(1), 1), float(np.median(c[:, 1] - c[:, 0])) + 1

    def rule_ys(self, x: float) -> np.ndarray:
        return np.array([np.polyval(p, x) for p in self.lines])

    def x_of(self, f: float) -> float:
        return (math.log10(f) - self.ax) / self.bx

    def db_at(self, x: float, y: float) -> float:
        b, a = np.polyfit(self.rule_ys(x), LEVELS, 1)
        return float(a + b * y)

    def clean(self) -> None:
        ink = self.ink
        for x in range(int(self.vr[0]) - 3, int(self.vr[-1]) + 4):
            for p in self.lines:
                erase_band(ink[:, x], np.polyval(p, x))
        ry = self.rule_ys(self.vr[0])
        ref = ink.copy()  # a steep curve crossing a vertical rule touches its edges in nearby rows
        for y in range(int(min(ry)) - 3, int(max(ry)) + 4):
            for p, th in self.vlines:
                c, half = np.polyval(p, y), max(2.5, th / 2 + 1)
                lo, hi = int(np.floor(c - half)) - 1, int(np.ceil(c + half)) + 1
                if not (ref[y - 3 : y + 4, lo].any() or ref[y - 3 : y + 4, hi].any()):
                    erase_band(ink[y, :], c, half=half)
        # the curve labels: small components once the rules are gone
        y0, y1 = int(min(ry)) + 3, int(max(ry)) - 2
        x0, x1 = int(self.vr[0]) + 4, int(self.vr[-1]) - 3
        sub = ink[y0:y1, x0:x1]
        lab, _ = ndimage.label(sub, structure=np.ones((3, 3)))
        for i, sl in enumerate(ndimage.find_objects(lab), 1):
            if sl[0].stop - sl[0].start <= 35 and sl[1].stop - sl[1].start <= 45:
                sub[lab == i] = False

    def track(self, seeds: dict[str, float], f_hi: float = 15000.0):
        """Follow each curve column by column; per curve [(x, y | None, quality)]."""
        ry = self.rule_ys(0)
        top, bot = int(min(ry)) + 3, int(max(ry)) - 2
        state = {k: [v, v, 0] for k, v in seeds.items()}
        out: dict[str, list] = {k: [] for k in seeds}
        for x in range(int(self.vr[0]) + 3, int(round(self.x_of(f_hi))) + 1):
            col = self.ink[top:bot, x]
            runs = [
                (top + g[0], top + g[-1], top + (g[0] + g[-1]) / 2)
                for g in groups(np.where(col)[0], gap=1)
            ]
            pick: dict[str, tuple | None] = {}
            # tracked curves first; a missing one takes no run of theirs
            for missing in (False, True):
                taken = {r for r in pick.values() if r is not None}
                for k, (yp, ypp, miss) in state.items():
                    if (miss > 0) != missing:
                        continue
                    pred = yp + (0.5 * (yp - ypp) if miss == 0 else 0.0)
                    cand = [r for r in runs if r[0] - 4 <= pred <= r[1] + 4]
                    if not cand:
                        tol = min(10 + 2 * miss, 60) if miss else 10
                        pool = [r for r in runs if r not in taken] if miss else runs
                        near = sorted(pool, key=lambda r: min(abs(r[0] - pred), abs(r[1] - pred)))  # noqa: B023
                        if near and min(abs(near[0][0] - pred), abs(near[0][1] - pred)) <= tol:
                            cand = near[:1]
                    pick[k] = min(cand, key=lambda r: abs(r[2] - pred)) if cand else None  # noqa: B023
            users: dict[tuple, list[str]] = {}
            for k, r in pick.items():
                if r is not None:
                    users.setdefault(r, []).append(k)
            for k, r in pick.items():
                yp, ypp, miss = state[k]
                if r is None:
                    ry_ = self.rule_ys(x)
                    j = int(np.argmin(np.abs(ry_ - yp)))
                    if abs(ry_[j] - yp) <= 5:
                        state[k] = [ry_[j], ry_[j], miss + 1]
                        out[k].append((x, ry_[j], "rule"))
                    else:
                        state[k] = [yp, ypp, miss + 1]
                        out[k].append((x, None, "lost"))
                    continue
                q = "merged" if len(users[r]) > 1 else ("steep" if r[1] - r[0] >= 12 else "read")
                state[k] = [r[2], yp if miss == 0 else r[2], 0]
                out[k].append((x, r[2], q))
        return out

    def sample(self, trace, f: float) -> tuple[float | None, str]:
        x = self.x_of(f)
        near = [t for t in trace if t[1] is not None and abs(t[0] - x) <= 3]
        coarse = not near  # the curve lost along a vertical rule: the columns either side
        if coarse:
            near = [t for t in trace if t[1] is not None and abs(t[0] - x) <= 10]
        if not near:
            return None, "missing"
        order = {"read": 0, "merged": 1, "steep": 2, "rule": 3}
        best = min(order[t[2]] for t in near)
        use = [t for t in near if order[t[2]] == best] if not coarse else near
        xs = np.array([t[0] for t in use], float)
        ys = np.array([t[1] for t in use], float)
        y = float(np.polyval(np.polyfit(xs, ys, 1), x)) if len(use) > 2 else float(ys.mean())
        return self.db_at(x, y), "coarse" if coarse else use[0][2]


def read_response(ink: np.ndarray, overlay: Image.Image | None):
    rows = []
    for name, (y0, y1) in CHARTS.items():
        chart = Chart(ink, y0, y1)
        print(
            f"Fig. 5 {name}: {1 / chart.bx:.2f} px/decade (rules within {chart.res_x_px:.2f} px),"
            f" {chart.px_per_db:.3f} px/dB (within {chart.res_y_px:.2f} px)"
        )
        chart.clean()
        traces = chart.track(SEEDS[name])
        draw = ImageDraw.Draw(overlay) if overlay is not None else None
        colour = {"M": (255, 0, 0), "V1": (0, 160, 0), "V2": (0, 0, 255)}
        for k, tr in traces.items():
            lost = sum(1 for t in tr if t[1] is None)
            if lost > 60:
                raise SystemExit(f"Fig. 5 {name} {k}: lost for {lost} columns")
            for f in FREQS:
                db, q = chart.sample(tr, f)
                if db is None:
                    raise SystemExit(f"Fig. 5 {name} {k}: nothing at {f} Hz")
                rows.append((name, k, f, db, q))
                if draw is not None:
                    x = chart.x_of(f)
                    b, a = np.polyfit(LEVELS, chart.rule_ys(x), 1)
                    y = a + b * db
                    draw.ellipse([x - 3, y - 3, x + 3, y + 3], outline=colour[k])
    return rows


# ------------------------------------------------------------------------ Fig. 4 patterns

PATTERN_SEEDS = {
    "U": (650, 563),
    "L1": (1428, 563),
    "B": (652, 1324),
    "L2": (1436, 1340),
    "N": (656, 2111),
    "L3": (1404, 2106),
}
RING_R = [85.5, 129.5, 172.5, 213.5, 258.5]  # px, -15 ... +5 dB (U's chart)
RING_DB = [-15, -10, -5, 0, 5]
DR, DT = 0.5, 0.25  # px, degrees
R0, R1 = 10.0, 320.0
NT = int(360 / DT)

# (pattern, frequency label as printed, a representative frequency, angle, guide dB, how the
# curve is told). Guides are the identified curve's level within ~1 dB; the run read is the
# nearest one. "bound": inside the -15 dB ring, unreadable; db is an upper bound.
POLAR = [
    ("B", "50-1000", 500, 180, -1.5, "thick solid (arrow '50-1,000~'); the 4000 long dash merges"),
    ("B", "4000", 4000, 180, -1.5, "long dash (arrow '4,000~'); merged with 50-1000"),
    ("B", "10000", 10000, 135, -10.1, "medium dash, the rear lobe's inner curve (arrow '10,000~')"),
    ("B", "10000", 10000, 150, -12.9, "medium dash"),
    ("B", "10000", 10000, 170, -14.8, "medium dash (a dash gap at 180)"),
    ("B", "all", 500, 90, "bound", "the side nulls, inside -15 dB"),
    ("N", "50-1000", 500, 90, -1.7, "long dash, the outer circle (arrow '50-1,000~')"),
    ("N", "50-1000", 500, 180, -2.6, "long dash"),
    ("N", "4000", 4000, 90, -3.8, "thick solid (label '4,000~' on it)"),
    ("N", "4000", 4000, 180, -5.1, "thick solid"),
    ("N", "10000", 10000, 90, -10.7, "medium dash, the inner curve (arrow '10,000~')"),
    ("N", "10000", 10000, 180, -18.0, "medium dash (inside -15 dB: coarse)"),
    (
        "U",
        "400-1000",
        630,
        90,
        -5.9,
        "thick solid; the '400~' / '1,000~' arrows point at the "
        "curves near -4 to -6 dB at 80 / 270 deg",
    ),
    ("U", "400-1000", 630, 180, "bound", "the rear null, inside -15 dB"),
    ("U", "4000", 4000, 180, -9.3, "long dash, flat across the rear (arrow '4,000~')"),
    ("U", "10000", 10000, 90, -12.8, "dash-dot, the inner lobe (arrow '10,000~')"),
    ("L1", "400-1000", 630, 90, -10.4, "thick solid (arrow '400-1,000~')"),
    ("L1", "400-1000", 630, 180, -1.8, "thick solid, the rear lobe's outer curve"),
    (
        "L2",
        "400 and 1000",
        630,
        90,
        -7.4,
        "thick solid (arrow '400 AND 1,000~'); among three curves within 3 dB at the sides",
    ),
    ("L2", "400 and 1000", 630, 180, -6.1, "thick solid, the rear lobe's outer curve"),
    ("L2", "4000", 4000, 180, -7.7, "long dash (arrow '4,000~')"),
    ("L3", "400", 400, 90, -5.2, "thick solid (arrow '400~')"),
    ("L3", "400", 400, 180, -7.2, "thick solid, the rear lobe's outer curve"),
    ("L3", "1000", 1000, 180, -11.9, "medium dash (arrow '1,000~')"),
]
TOL_DB = 1.2


def rays_for(angle: float) -> list[float]:
    """Rays 2.5 degrees either side of the angle, and mirrored (the drawn rays avoided)."""
    out = {(angle - 2.5) % 360, (angle + 2.5) % 360, (-angle - 2.5) % 360, (-angle + 2.5) % 360}
    return sorted(out)


class Polar:
    def __init__(self, ink: np.ndarray, name: str):
        self.ink = ink
        self.cx, self.cy = self._centre(*PATTERN_SEEDS[name])
        self.P = self._unwrap()
        self.rings = self._rings()
        self._clean()

    def _hist_score(self, cx: float, cy: float) -> float:
        rmax = 330
        y0, x0 = int(cy - rmax), int(cx - rmax)
        yy, xx = np.nonzero(self.ink[y0 : y0 + 2 * rmax, x0 : x0 + 2 * rmax])
        r = np.hypot(xx + x0 - cx, yy + y0 - cy)
        h, _ = np.histogram(r, bins=np.arange(30, rmax + 0.5, 0.5))
        return float(np.sort(h)[-12:].sum())

    def _centre(self, cx0: float, cy0: float) -> tuple[float, float]:
        best = max(
            (self._hist_score(cx0 + dx, cy0 + dy), cx0 + dx, cy0 + dy)
            for dx in range(-12, 13)
            for dy in range(-12, 13)
        )
        for step in (0.5, 0.25):
            _, cx, cy = best
            best = max(
                (self._hist_score(cx + dx, cy + dy), cx + dx, cy + dy)
                for dx in (-step, 0, step)
                for dy in (-step, 0, step)
            )
        return best[1], best[2]

    def _unwrap(self) -> np.ndarray:
        r = np.arange(R0, R1, DR)
        t = np.radians(np.arange(0, 360, DT))
        X = np.rint(self.cx + r[:, None] * np.sin(t[None, :])).astype(int)
        Y = np.rint(self.cy - r[:, None] * np.cos(t[None, :])).astype(int)
        return self.ink[Y, X]

    def _rings(self) -> np.ndarray:
        """Each ring's row per angle column (the scan's slight ellipticity)."""
        out = []
        for r in RING_R:
            c0 = (r - R0) / DR
            cs, ts = [], []
            for j0 in range(0, NT, 20):
                rows = np.arange(int(c0) - 8, int(c0) + 9)
                band = rows[self.P[rows, j0 + 2 : j0 + 18].mean(1) > 0.8]
                if 2 <= len(band) <= 10 and band.max() - band.min() == len(band) - 1:
                    cs.append(band.mean())
                    ts.append(j0 + 10)
            cs, ts = np.array(cs), np.array(ts)
            full = np.interp(np.arange(NT), np.concatenate([ts - NT, ts, ts + NT]), np.tile(cs, 3))
            k = 41
            pad = np.concatenate([full[-k:], full, full[:k]])
            out.append(np.array([np.median(pad[i : i + 2 * k + 1]) for i in range(NT)]))
        return np.array(out)

    def _rays(self) -> list[tuple[int, np.ndarray]]:
        rays = []
        for a in range(0, 360, 5):
            r_lo = 60 if a % 10 == 0 else 178
            rs, cs = [], []
            for r in np.arange(r_lo, 296, 6):
                i0 = int((r - R0) / DR)
                cols = np.arange(int(a / DT) - 16, int(a / DT) + 17)
                band = cols[self.P[i0 : i0 + 12, cols % NT].mean(0) > 0.85]
                wide = 2 + 4 * math.degrees(4 / r) / DT
                if len(band) and band.max() - band.min() == len(band) - 1 and len(band) <= wide:
                    rs.append(r + 3)
                    cs.append(band.mean())
            coef = np.array([a / DT, 0.0])
            if len(rs) >= 3:
                rs, cs = np.array(rs), np.array(cs)
                for _ in range(3):
                    A = np.vstack([np.ones_like(rs), 1 / rs]).T
                    coef = np.linalg.lstsq(A, cs, rcond=None)[0]
                    res = np.abs(A @ coef - cs)
                    keep = res < max(1.0, 2.5 * np.median(res))
                    rs, cs = rs[keep], cs[keep]
            rays.append((r_lo, coef))
        return rays

    def _clean(self) -> None:
        P = self.P
        for j in range(NT):
            for c in self.rings[:, j]:
                erase_band(P[:, j], c, half=5.0)  # rows: 2.5 px
        rays = self._rays()
        for i in range(P.shape[0]):
            r = R0 + i * DR
            row = np.concatenate([P[i, -40:], P[i], P[i, :40]])
            half = max(math.degrees(3.0 / r) / DT, 2.5)
            for r_lo, coef in rays:
                if r >= r_lo - 8:
                    c = coef[0] + coef[1] / r
                    erase_band(row, c + 40, half=half)
                    if c < 40:
                        erase_band(row, c + NT + 40, half=half)
            P[i] = row[40:-40]

    def db_of(self, j: int, row: float) -> float:
        b, a = np.polyfit(self.rings[:, j % NT], RING_DB, 1)
        return float(a + b * row)

    def runs_db(self, angle: float) -> list[float]:
        j = int(round(angle / DT)) % NT
        col = self.P[100:600, j]
        return [self.db_of(j, 100 + (g[0] + g[-1]) / 2) for g in groups(np.where(col)[0], gap=1)]


def read_polar(ink: np.ndarray):
    charts = {name: Polar(ink, name) for name in PATTERN_SEEDS}
    for name, ch in charts.items():
        print(
            f"Fig. 4 {name}: centre ({ch.cx}, {ch.cy}), rings vary "
            f"{max(np.ptp(r) for r in ch.rings) * DR:.1f} px around"
        )
    rows = []
    for pattern, label, f_hz, angle, guide, note in POLAR:
        if guide == "bound":
            rows.append((pattern, label, f_hz, angle, -15.0, "bound", 0, 0.0, note))
            continue
        vals = []
        for a in rays_for(angle):
            near = [v for v in charts[pattern].runs_db(a) if abs(v - guide) <= TOL_DB]
            if near:
                vals.append(min(near, key=lambda v: abs(v - guide)))  # noqa: B023
        if not vals:
            got = {a: [round(v, 1) for v in charts[pattern].runs_db(a)] for a in rays_for(angle)}
            raise SystemExit(f"Fig. 4 {pattern} {label} {angle} deg: no run near {guide}: {got}")
        q = "read" if len(vals) >= 2 else "single"
        rows.append(
            (
                pattern,
                label,
                f_hz,
                angle,
                float(np.mean(vals)),
                q,
                len(vals),
                float(np.ptp(vals)),
                note,
            )
        )
    return rows


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--overlays", type=Path, help="write the response overlay PNG here")
    args = ap.parse_args()
    if hashlib.sha256(PDF.read_bytes()).hexdigest() != PDF_SHA256:
        raise SystemExit(f"{PDF}: not the expected file (data/schematics/rca_77dx/README.md)")
    doc = fitz.open(PDF)
    ink9 = page_mask(doc, 9)
    overlay = None
    if args.overlays:
        overlay = Image.fromarray(np.where(ink9, 0, 255).astype(np.uint8)).convert("RGB")
    resp = read_response(ink9.copy(), overlay)
    if overlay is not None:
        args.overlays.mkdir(parents=True, exist_ok=True)
        overlay.crop((560, 380, 1850, 2360)).save(args.overlays / "rca_77dx_response.png")
    ref = "ib2 Fig. 5 (472178-0) 0 dB rule; open circuit"
    with open(OUT / "rca_77dx_response.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(["pattern", "curve", "freq_hz", "db", "document", "reference", "quality"])
        for pattern, curve, f, db, q in resp:
            w.writerow([pattern, curve, f, f"{db:.2f}", "ib2", ref, q])
    pol = read_polar(page_mask(doc, 8))
    ref = "ib2 Fig. 4 (T-163143) the 0 dB ring"
    with open(OUT / "rca_77dx_polar.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(
            [
                "pattern",
                "freq_label",
                "freq_hz",
                "angle_deg",
                "db",
                "document",
                "reference",
                "quality",
                "n_rays",
                "spread_db",
                "curve",
            ]
        )
        for pattern, label, f, a, db, q, n, sp, note in pol:
            w.writerow([pattern, label, f, a, f"{db:.2f}", "ib2", ref, q, n, f"{sp:.2f}", note])
    for pattern, label, _f, a, db, q, n, sp, _note in pol:
        print(f"  {pattern:3s} {label:13s} {a:4d} deg {db:6.2f} dB  {q} ({n} rays, {sp:.2f} apart)")


if __name__ == "__main__":
    main()
