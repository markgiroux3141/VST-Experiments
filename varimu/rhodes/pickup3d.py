"""The pickup's flux map in 3D (docs/RHODES_PLAN.md, "Single notes: jRhodes3d", RH5's 3D
pickup): the same Phi(y, dg) as `pickup.flux_map`, from the real shapes instead of the 2D
section's slab.

**Why 3D.** The 2D section extrudes everything by the magnet's width, so the tine is a slab
4.76 mm deep: its pull on the pole's flux falls off slowly as it moves away (a 2D field
decays like a line source's). The real tine is a 1.5 mm rod whose end faces the chisel: its
coupling falls off faster with height, so the field the tip swings through is narrower and
the pickup more nonlinear at a given swing (the comparison with jRhodes3d's single notes
asked for a field ~3-4x narrower).

**The method: a volume integral for the tine, reciprocity for the coil.**
- The magnet: a round rod (`magnet_width_m` across) along +x, its end ground to a chisel
  (two flat faces meeting in an edge along z at x = 0, y = 0; the 2D section's wedge), its
  body behind; magnetized uniformly along x with M0 = Br / mu0. Its recoil susceptibility
  (mu_r 1.05) is left out (it moves the field a few percent). A uniform magnetization's
  field is that of its surface charges sigma = M . n: only the chisel's faces and the back
  face carry charge (the rod's sides are parallel to M). They are point charges on a fine
  grid of columns over the rod's cross-section (`MAGNET_CELL_M`): at 1.6 mm, 0.05 mm patches
  are exact to ~1e-4.
- The tine: a rod of the tip's diameter, `field_tine_length_m` long behind its end face
  (the far end barely couples), as cuboid cells (a staircase circle across, graded along x:
  fine at the tip). Linear, isotropic steel: M = chi H with chi = mu_r - 1, H the magnet's
  field plus the tine's own. Each cell's field on the others (the exact field of a uniformly
  magnetized cuboid, from its faces' charges, at the other cell's centre) is the same matrix
  at every position (the tine moves rigidly), so it is factored once and each position is
  one right-hand side.
- The coil: a thick solenoid around the magnet's body (N turns spread over its section),
  as coaxial current loops (exact fields from elliptic integrals). By reciprocity the flux
  a magnetization links through the coil is mu0 int M . h dV, h the coil's field per ampere
  of its own current (N turns in it): the tine's share is the map (the magnet's own share is
  a constant and the EMF only sees changes).

**Checks** (tests/test_pickup3d.py): a cube's self field (-M / 3), a sphere-like body against
the analytic M = 3 chi / (chi + 3) H0, a loop's field on its axis against the closed form, and
the linkage by reciprocity against the flux of the tine's own field through the coil's turns
(direct), at a tine position.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
from scipy import interpolate, linalg, special

from varimu.rhodes.pickup import CACHE_DIR, MAP_DG_M, FluxMap
from varimu.rhodes.spec import Pickup

MU0 = 4e-7 * np.pi
FOUR_PI = 4.0 * np.pi
MAGNET_CELL_M = 0.05e-3  # the chisel's charge grid
BACK_CELL_M = 0.25e-3  # the back face's (13 mm away)
TINE_ACROSS = 6  # cells across the tine's diameter (a staircase circle)
TIP_CELL_M = 0.1e-3  # the tine's cells along x at its end
TIP_FINE_M = 0.8e-3  # that fine for this far from the end
TINE_GROWTH = 1.25
TINE_MAX_CELL_M = 2.0e-3
COIL_LOOPS = (12, 20)  # loops across the coil's radial build, along its length
SWING_M = 18e-3  # like the 2D map: the tine's centre within +-this of the pole's axis
FINE_STEP_M = 0.05e-3  # the map's samples within +-FINE_SWING_M
FINE_SWING_M = 6e-3
COARSE_STEP_M = 0.25e-3


# --- fields -------------------------------------------------------------------------------


def _rect(x: np.ndarray, u1: np.ndarray, u2: np.ndarray, v1: np.ndarray, v2: np.ndarray):
    """The field of a unit-charge-density rectangle in the plane X = 0 (X the point's
    height over it, u / v the point's offsets from its edges: u1 = r_b - b1, u2 = r_b - b2):
    (H_normal, H_b, H_d) times 4 pi."""
    hn = np.zeros_like(x)
    hb = np.zeros_like(x)
    hd = np.zeros_like(x)
    for u, su in ((u1, 1.0), (u2, -1.0)):
        for v, sv in ((v1, 1.0), (v2, -1.0)):
            s = su * sv
            r = np.sqrt(x * x + u * u + v * v)
            # the principal arctan (continuous in u, v on either side of the plane; arctan2
            # would add pi branches below it); X = 0 only in the plane, never evaluated
            hn += s * np.arctan(u * v / (x * r))
            hb -= s * _log_sum(v, r, x * x + u * u)
            hd -= s * _log_sum(u, r, x * x + v * v)
    return hn, hb, hd


def _log_sum(a: np.ndarray, r: np.ndarray, rest2: np.ndarray) -> np.ndarray:
    """ln(a + r), r = sqrt(a^2 + rest2), without cancellation for a < 0."""
    out = np.empty_like(a)
    pos = a >= 0
    out[pos] = np.log(a[pos] + r[pos])
    neg = ~pos
    out[neg] = np.log(np.maximum(rest2[neg], 1e-300) / (r[neg] - a[neg]))
    return out


def cuboid_field(p: np.ndarray, lo: np.ndarray, hi: np.ndarray) -> np.ndarray:
    """H at points p (P, 3) from cuboids [lo, hi] (P, 3) each uniformly magnetized with a
    unit M along x, y, z: (P, 3 field components, 3 M axes). Exact (the faces' charges);
    a point inside its cuboid gets that cuboid's own (demagnetizing) field."""
    out = np.zeros((p.shape[0], 3, 3))
    for a in range(3):  # M along axis a: charge +1 on the face at hi[a], -1 at lo[a]
        b, d = (a + 1) % 3, (a + 2) % 3
        u1, u2 = p[:, b] - lo[:, b], p[:, b] - hi[:, b]
        v1, v2 = p[:, d] - lo[:, d], p[:, d] - hi[:, d]
        for face, sigma in ((hi[:, a], 1.0), (lo[:, a], -1.0)):
            hn, hb, hd = _rect(p[:, a] - face, u1, u2, v1, v2)
            out[:, a, a] += sigma * hn / FOUR_PI
            out[:, b, a] += sigma * hb / FOUR_PI
            out[:, d, a] += sigma * hd / FOUR_PI
    return out


def charge_field(p: np.ndarray, q_pos: np.ndarray, q: np.ndarray, chunk: int = 256) -> np.ndarray:
    """H at points p (P, 3) from point magnetic charges q (A m) at q_pos (Q, 3)."""
    out = np.zeros_like(p)
    for i in range(0, p.shape[0], chunk):
        d = p[i : i + chunk, None, :] - q_pos[None, :, :]
        r3 = np.sum(d * d, axis=-1) ** 1.5
        out[i : i + chunk] = np.einsum("pqk,q->pk", d / r3[..., None], q) / FOUR_PI
    return out


def loop_field(p: np.ndarray, radius: np.ndarray, x0: np.ndarray, turns: np.ndarray) -> np.ndarray:
    """H per ampere at points p (P, 3) from coaxial current loops on the x axis (radius,
    position x0, turns each): (P, 3)."""
    x = p[:, 0][:, None] - x0[None, :]
    rho = np.hypot(p[:, 1], p[:, 2])[:, None]
    a = radius[None, :]
    rho_s = np.maximum(rho, 1e-12)
    den = (a + rho_s) ** 2 + x**2
    m = np.clip(4 * a * rho_s / den, 0.0, 1.0 - 1e-15)
    kk, ee = special.ellipk(m), special.ellipe(m)
    near = (a - rho_s) ** 2 + x**2
    pre = turns[None, :] / (2 * np.pi * np.sqrt(den))
    hx = pre * (kk + (a**2 - rho_s**2 - x**2) / near * ee)
    h_rho = pre * (x / rho_s) * (-kk + (a**2 + rho_s**2 + x**2) / near * ee)
    hx, h_rho = hx.sum(axis=1), h_rho.sum(axis=1)
    rr = np.hypot(p[:, 1], p[:, 2])
    cy = np.divide(p[:, 1], rr, out=np.zeros_like(rr), where=rr > 0)
    cz = np.divide(p[:, 2], rr, out=np.zeros_like(rr), where=rr > 0)
    return np.stack([hx, h_rho * cy, h_rho * cz], axis=1)


# --- the geometry -------------------------------------------------------------------------


@dataclass(frozen=True)
class Geometry:
    cell_lo: np.ndarray  # the tine's cells at rest (its end face at x = -gap, centre y = 0)
    cell_hi: np.ndarray
    q_pos: np.ndarray  # the magnet's charges
    q: np.ndarray
    loop_r: np.ndarray  # the coil's loops
    loop_x: np.ndarray
    loop_n: np.ndarray

    @property
    def centres(self) -> np.ndarray:
        return 0.5 * (self.cell_lo + self.cell_hi)

    @property
    def volumes(self) -> np.ndarray:
        return np.prod(self.cell_hi - self.cell_lo, axis=1)


def _tine_x_edges(length_m: float) -> np.ndarray:
    edges = [0.0]
    step = TIP_CELL_M
    while edges[-1] < length_m - 1e-12:
        if edges[-1] >= TIP_FINE_M - 1e-12:
            step = min(step * TINE_GROWTH, TINE_MAX_CELL_M)
        edges.append(min(edges[-1] + step, length_m))
    return -np.array(edges)  # 0 at the end face, going back along -x


def geometry(p: Pickup, tine_length_m: float, across: int = TINE_ACROSS) -> Geometry:
    g, w, lw, lm = p.gap_m, p.magnet_width_m, p.wedge_length_m, p.magnet_length_m
    br = p.magnet_br_t
    # the tine: a staircase circle across, graded along x behind its end at -gap
    d = p.tine_diameter_m
    a = d / across
    c = (np.arange(across) + 0.5) * a - d / 2
    yy, zz = np.meshgrid(c, c, indexing="ij")
    keep = yy**2 + zz**2 <= (d / 2) ** 2
    yc, zc = yy[keep], zz[keep]
    xe = _tine_x_edges(tine_length_m) - g
    lo, hi = [], []
    for x_hi, x_lo in zip(xe[:-1], xe[1:], strict=True):
        for y0, z0 in zip(yc, zc, strict=True):
            lo.append([x_lo, y0 - a / 2, z0 - a / 2])
            hi.append([x_hi, y0 + a / 2, z0 + a / 2])
    # the magnet: charges -M0 dA on the chisel (each column's front at x = 2 lw |y| / w)
    # and +M0 dA on the back face at lw + lm
    m0 = br / MU0
    pos, q = [], []
    for cell, front in ((MAGNET_CELL_M, True), (BACK_CELL_M, False)):
        n = int(np.ceil(w / cell))
        cc = (np.arange(n) + 0.5) * (w / n) - w / 2
        my, mz = np.meshgrid(cc, cc, indexing="ij")
        inside = my**2 + mz**2 <= (w / 2) ** 2
        my, mz = my[inside], mz[inside]
        x = 2 * lw * np.abs(my) / w if front else np.full(my.shape, lw + lm)
        pos.append(np.stack([x, my, mz], axis=1))
        q.append(np.full(my.shape, (-m0 if front else m0) * (w / n) ** 2))
    # the coil: N turns spread uniformly over its section, centred on the magnet's body
    nr, nx = COIL_LOOPS
    xc0 = lw + 0.5 * (lm - p.coil_length_m)
    r = p.coil_inner_m + (np.arange(nr) + 0.5) * (p.coil_outer_m - p.coil_inner_m) / nr
    xs = xc0 + (np.arange(nx) + 0.5) * p.coil_length_m / nx
    rr, xx = np.meshgrid(r, xs, indexing="ij")
    return Geometry(
        np.array(lo),
        np.array(hi),
        np.concatenate(pos),
        np.concatenate(q),
        rr.ravel(),
        xx.ravel(),
        np.full(rr.size, p.turns / rr.size),
    )


# --- the solve ----------------------------------------------------------------------------


class Solver:
    """The tine's magnetization for any position of its end (centre height y, pulled back
    dg): the self-interaction factored once."""

    def __init__(self, p: Pickup, tine_length_m: float, across: int = TINE_ACROSS):
        self.p = p
        self.geo = geometry(p, tine_length_m, across)
        cen, lo, hi = self.geo.centres, self.geo.cell_lo, self.geo.cell_hi
        n = cen.shape[0]
        t = np.zeros((3 * n, 3 * n))
        for j in range(n):  # the field at every centre from cell j's unit magnetizations
            f = cuboid_field(cen, np.repeat(lo[j : j + 1], n, 0), np.repeat(hi[j : j + 1], n, 0))
            t[:, 3 * j : 3 * j + 3] = f.reshape(3 * n, 3)
        chi = p.tine_mu_r - 1.0
        self.lu = linalg.lu_factor(np.eye(3 * n) / chi - t)

    def magnetization(self, y_m: float, dg_m: float) -> tuple[np.ndarray, np.ndarray]:
        """(the cells' centres at that position, their M (n, 3) in A/m)."""
        cen = self.geo.centres + np.array([-dg_m, y_m, 0.0])
        h0 = charge_field(cen, self.geo.q_pos, self.geo.q)
        m = linalg.lu_solve(self.lu, h0.ravel()).reshape(-1, 3)
        return cen, m

    def linkage(self, y_m: float, dg_m: float) -> float:
        """The tine's share of the coil's flux linkage (weber-turns), by reciprocity."""
        cen, m = self.magnetization(y_m, dg_m)
        h = loop_field(cen, self.geo.loop_r, self.geo.loop_x, self.geo.loop_n)
        return float(MU0 * np.sum(self.geo.volumes * np.sum(m * h, axis=1)))


def map_y_m() -> np.ndarray:
    """The heights sampled (y >= 0; the map is even in y)."""
    fine = np.arange(0.0, FINE_SWING_M + FINE_STEP_M / 2, FINE_STEP_M)
    far = np.arange(FINE_SWING_M + COARSE_STEP_M, SWING_M + COARSE_STEP_M / 2, COARSE_STEP_M)
    return np.concatenate([fine, far])


_SOLVERS: dict[str, Solver] = {}


def _one(job: tuple[Pickup, float, float, float]) -> float:
    p, length, y, dg = job
    k = json.dumps([asdict(p), length], sort_keys=True)
    if k not in _SOLVERS:
        _SOLVERS[k] = Solver(p, length)
    return _SOLVERS[k].linkage(y, dg)


def _cache_key(p: Pickup, tine_length_m: float) -> str:
    src = Path(__file__).read_bytes()
    blob = json.dumps(
        {
            "pickup": asdict(p),
            "tine_length_m": tine_length_m,
            "dg": MAP_DG_M.tolist(),
            "y": map_y_m().tolist(),
            "consts": [
                MAGNET_CELL_M,
                BACK_CELL_M,
                TINE_ACROSS,
                TIP_CELL_M,
                TIP_FINE_M,
                TINE_GROWTH,
                TINE_MAX_CELL_M,
                COIL_LOOPS,
            ],
        },
        sort_keys=True,
    ).encode()
    return hashlib.sha256(src + blob).hexdigest()[:16]


def flux_map(p: Pickup, tine_length_m: float, workers: int = 1, progress: bool = False) -> FluxMap:
    """Phi(y, dg) in 3D, as `pickup.flux_map`'s (cached in cache/rhodes/)."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = CACHE_DIR / f"pickup3d_{_cache_key(p, tine_length_m)}.npz"
    half = map_y_m()
    if path.exists():
        phi_half = np.load(path)["phi"]
    else:
        jobs = [(p, tine_length_m, float(y), float(dg)) for y in half for dg in MAP_DG_M]
        if workers > 1:
            from concurrent.futures import ProcessPoolExecutor

            # one solver per worker process: chunks by height keep its factorization reused
            with ProcessPoolExecutor(workers) as pool:
                vals = list(pool.map(_one, jobs, chunksize=max(1, len(jobs) // (4 * workers))))
        else:
            vals = []
            for i, job in enumerate(jobs):
                vals.append(_one(job))
                if progress and (i + 1) % 100 == 0:
                    print(f"pickup 3D map: {i + 1} / {len(jobs)}", flush=True)
        phi_half = np.array(vals).reshape(half.size, MAP_DG_M.size)
        np.savez(path, phi=phi_half)
    y = np.concatenate([-half[:0:-1], half])
    phi = np.concatenate([phi_half[:0:-1], phi_half])
    spline = interpolate.RectBivariateSpline(y, MAP_DG_M, phi, kx=3, ky=3)
    return FluxMap(y, MAP_DG_M, phi, spline)
