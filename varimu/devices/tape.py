"""Magnetic tape as a medium (docs/TAPE_PLAN.md, TM2): the heads' fields, recording into
a 2D slab of Preisach cells (varimu.devices.preisach) moving past the record gap with AC
bias, and playback by reciprocity. This module is the Python reference.

**Coordinates.** s is position along the tape (m), fixed to the tape. The point of tape
at the record gap at time t is s_rec(t) = integral of the speed v(t); the repro head
reads s_rep(t) = s_rec(t) - spacing (the heads sit `spacing` apart on the headblock).
A cell at s_c is at x = s_c - s_rec(t) from the record gap's centre. Depth y is measured
into the coating from its surface; the head surface is a distance d (head-to-tape
spacing) above it, so a cell at depth y is y + d from the head.

**Head field** (`head_hx`): the head surface is a plane carrying the magnetic scalar
potential +phi0/2 on one pole face, falling linearly across the gap g, -phi0/2 on the
other, each pole face p long, and outside the poles a potential that relaxes to 0 over
a length r (the head's contour receding from the tape). The field above it is the
Poisson integral of that potential (Karlqvist's derivation, which takes p infinite:
Bertram, "Theory of Magnetic Recording", 1994, ch. 3.1-3.2). The deep-gap field is
Hg = phi0 / g. Its x component's spatial spectrum, per unit deep-gap field, is

    Hx(k, y) = g e^{-|k| y} [sinc(k g / 2) - cos(k (g/2 + p)) R(k)]

with R(k) the relaxation's spectrum (1 for an abrupt edge): the gap loss (sinc), the
spacing and thickness losses (e^{-ky}) and the head bump (the cosine: the poles' finite
length) are all in it, not added.

**Playback by reciprocity** (Bertram ch. 4): the flux linking the repro coil is
lambda = mu0 W integral M(s, y) H_rep(s - s_rep, y + d) / I ds dy, H_rep / I the head's
field per unit coil current (it carries the turns and the head's efficiency), and the
EMF is -d lambda / dt = -v d lambda / ds_rep. Only the x component is used (particles
oriented along the tape, a scalar Preisach model).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from varimu.devices.preisach import Preisach, PreisachParams

MU0 = 4e-7 * math.pi


@dataclass(frozen=True)
class TapeFormulation:
    """A tape component version (config/components/<name>/<N>.yaml, kind `tape`): the
    coating's thickness and particles (a Preisach ensemble and its saturation
    magnetization), the base's thickness."""

    name: str
    coating_m: float
    base_m: float
    ms_a_m: float
    preisach: PreisachParams
    orientation: Orientation | None = None
    noise: TapeNoise | None = None

    def ensemble(self) -> Preisach:
        return Preisach(self.preisach)


@dataclass(frozen=True)
class TapeNoise:
    """The coating's graininess (docs/TAPE_PLAN.md, TM3): particles of particle_volume_m3
    at a volume fraction `packing`, placed at random (a Poisson count per cell, each
    particle up or down: hiss whatever the level), and the packing's own fluctuation along
    the tape, a field of relative std packing_sigma, exponentially correlated over
    packing_corr_m and the same through the coating's depth (the coating's nonuniformity:
    modulation noise, growing with the recorded level)."""

    particle_volume_m3: float
    packing: float
    packing_sigma: float
    packing_corr_m: float


def tape_from_data(d: dict, name: str) -> TapeFormulation:
    c, m = d["coating"], d["particles"]
    o = d.get("orientation")
    return TapeFormulation(
        name=name,
        coating_m=float(c["thickness_m"]),
        base_m=float(d["base"]["thickness_m"]),
        ms_a_m=float(m["ms_a_m"]),
        preisach=PreisachParams(
            hc_median_a_m=float(m["hc_median_a_m"]),
            sigma_ln_hc=float(m["sigma_ln_hc"]),
            sigma_hi_a_m=float(m["sigma_hi_a_m"]),
            h_max_a_m=float(m["h_max_a_m"]),
            n_table=int(m["n_table"]),
        ),
        orientation=Orientation(float(o["kappa"]), int(o["n"])) if o else None,
        noise=TapeNoise(
            float(nz["particle_volume_m3"]),
            float(nz["packing"]),
            float(nz["packing_sigma"]),
            float(nz["packing_corr_m"]),
        )
        if (nz := d.get("noise"))
        else None,
    )


@dataclass(frozen=True)
class HeadGeometry:
    """A ring head's face: gap g, pole faces p long each, the potential outside them
    relaxing to 0 over r (r = 0: an abrupt edge)."""

    gap_m: float
    pole_m: float
    relax_m: float


def _atan_pair(x: np.ndarray, y: np.ndarray, a: float) -> np.ndarray:
    """atan((x + a) / y) - atan((x - a) / y), for y > 0."""
    return np.arctan2(x + a, y) - np.arctan2(x - a, y)


def head_hx(head: HeadGeometry, x: np.ndarray, y: np.ndarray) -> np.ndarray:
    """Hx / Hg at (x, y): x along the tape from the gap's centre, y > 0 from the head
    surface (see the module docs)."""
    x, y = np.broadcast_arrays(np.asarray(x, float), np.asarray(y, float))
    g, p, r = head.gap_m, head.pole_m, head.relax_m
    # The gap: phi' = -phi0 / g over |x| < g / 2 -> Hx = (Hg / pi) [atan pair].
    hx = _atan_pair(x, y, g / 2.0) / math.pi
    # The outer pole edges: phi rises from 0 to phi0 / 2 at x = -(g/2 + p) and falls
    # from -phi0 / 2 to 0 at +(g/2 + p): phi' = +phi0 / 2 at both, spread over r.
    e = g / 2.0 + p
    scale = (g / 2.0) / math.pi  # phi0 / (2 pi) per unit Hg
    if r <= 0.0:
        hx = hx - scale * (y / ((x + e) ** 2 + y**2) + y / ((x - e) ** 2 + y**2))
    else:
        # A linear relaxation over r: phi' = (phi0 / 2) / r over [e, e + r] (and the
        # mirror), whose field is the atan pair over that interval, over r.
        hx = hx - scale / r * (
            _atan_pair(x + e + r / 2.0, y, r / 2.0) + _atan_pair(x - e - r / 2.0, y, r / 2.0)
        )
    return hx


def head_field(head: HeadGeometry, x: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """(Hx, Hy) / Hg at (x, y), y > 0. The field above the head is analytic in z = x + iy:
    Hx - i Hy = -(i / pi) integral phi'(x') / (z - x') dx' over the surface potential's
    derivative (the Poisson integral, differentiated and integrated by parts): a uniform
    phi' = c over [a, b] gives c ln((z - a) / (z - b)), a point step A gives A / (z - x_e).
    Hy is positive pointing away from the head."""
    x, y = np.broadcast_arrays(np.asarray(x, float), np.asarray(y, float))
    z = x + 1j * y
    g, p, r = head.gap_m, head.pole_m, head.relax_m
    e = g / 2.0 + p

    def seg(c: float, a: float, b: float) -> np.ndarray:
        return c * (np.log(z - a) - np.log(z - b))

    acc = seg(-1.0, -g / 2.0, g / 2.0)  # the gap: phi' = -phi0 / g = -Hg
    if r <= 0.0:
        acc = acc + (g / 2.0) / (z + e) + (g / 2.0) / (z - e)
    else:
        acc = acc + seg(g / 2.0 / r, -e - r, -e) + seg(g / 2.0 / r, e, e + r)
    w = -(1j / math.pi) * acc  # Hx - i Hy
    return w.real, -w.imag


def head_hx_spectrum(head: HeadGeometry, k: np.ndarray, y: float) -> np.ndarray:
    """The spatial Fourier transform of head_hx at height y (integral of Hx / Hg
    e^{-i k x} dx), in closed form: g e^{-|k| y} [sinc(k g / 2) - cos(k e_c) R(k)], e_c the
    edge's centre and R the relaxation's sinc."""
    k = np.asarray(k, float)
    g, p, r = head.gap_m, head.pole_m, head.relax_m
    ka = np.abs(k)
    gap = np.sinc(k * g / (2.0 * math.pi))  # numpy's sinc is sin(pi u) / (pi u)
    ec = g / 2.0 + p + r / 2.0
    relax = np.sinc(k * r / (2.0 * math.pi)) if r > 0 else 1.0
    return g * np.exp(-ka * y) * (gap - np.cos(k * ec) * relax)


def head_hy_spectrum(head: HeadGeometry, k: np.ndarray, y: float) -> np.ndarray:
    """The spatial Fourier transform of Hy / Hg at height y: i sgn(k) times Hx's (Hx - i Hy
    is analytic above the head and decays, so it has only k > 0 in e^{ikx})."""
    k = np.asarray(k, float)
    return 1j * np.sign(k) * head_hx_spectrum(head, k, y)


# --- Crosstalk: a head reading its neighbour's track (PERIOD_GEAR_BACKLOG.md PG1, MT3) ----


@dataclass(frozen=True)
class CrossPickup:
    """What a head of a stack reads of the track beside its own, centre to centre pitch_m
    (varimu.multitrack.crosstalk is the model and its fit to Ampex's measured curve): the
    outer contour's field, which the interchannel shields don't screen, a fraction
    `unshielded` of it, spread across the width as a strip contour_width_m wide
    (`lateral_factor`); plus the cores' flat coupling ("stacked heads form a small
    transformer", Ampex AI-14 p 10), a fraction `core` of what the neighbour's own head
    reads. Both linear in the neighbour's magnetization, so the neighbour's stream computes
    it (`cross_hx_spectrum`) and the heads beside it add it to their own EMF."""

    pitch_m: float
    unshielded: float
    contour_width_m: float
    core: float

    def check(self) -> None:
        if not (
            self.pitch_m > self.contour_width_m > 0.0
            and self.unshielded >= 0.0
            and math.isfinite(self.core)
        ):
            raise ValueError("crosstalk: pitch > contour width > 0, unshielded >= 0")


#: `lateral_factor`'s quadrature: the step in t and where it stops (the integrand below
#: e^-LATERAL_DECAY of its scale). The integrand is analytic in |Im t| < pi / 2, so the
#: trapezoidal rule's error is ~exp(-pi^2 / step), far below rounding.
LATERAL_STEP = 0.1
LATERAL_DECAY = 60.0


def lateral_factor(k: np.ndarray, d_m: float, w_m: float) -> np.ndarray:
    """L(k): the field of a strip contour w wide, read by a head at centre distance d > w
    across the tape, relative to a track of infinite width (varimu.multitrack.crosstalk's
    `lateral`: k / (pi w) integral of the triangle (w - |u - d|) times K0(k u)). With
    K0(x) = integral_0^inf exp(-x cosh t) dt the triangle integrates in closed form, so

        L(k) = k / (pi w) integral_0^inf e^{-a (d - w)} (1 - e^{-a w})^2 / a^2 dt,
        a = k cosh t,

    a double-exponentially decaying integrand: the trapezoidal rule from t = 0 (half its
    weight there) at LATERAL_STEP, to the last t with a (d - w) <= LATERAL_DECAY. In the
    same order of operations as circuitsim's port; L(0) = 0 (and k < 0 reads |k|)."""
    if not d_m > w_m > 0.0:
        raise ValueError("the strips overlap: crosstalk is for separate tracks")
    k = np.abs(np.asarray(k, float))
    out = np.zeros_like(k)
    gap = d_m - w_m
    for i, kk in np.ndenumerate(k):
        if kk == 0.0:
            continue
        n = int(math.ceil(math.acosh(max(LATERAL_DECAY / (kk * gap), 1.0)) / LATERAL_STEP))
        a = kk * np.cosh(LATERAL_STEP * np.arange(n + 1))
        f = np.exp(-a * gap) * np.expm1(-a * w_m) ** 2 / (a * a)
        acc = 0.5 * f[0]
        for x in f[1:].tolist():
            acc += x
        out[i] = kk / (math.pi * w_m) * LATERAL_STEP * acc
    return out


def cross_hx_spectrum(
    head: HeadGeometry, k: np.ndarray, y: float, x: CrossPickup, lat: np.ndarray | None = None
) -> np.ndarray:
    """`head_hx_spectrum` for a neighbouring head (`CrossPickup`): the contour's term times
    unshielded L(k) (`lateral_factor`, or `lat` precomputed on k), and the cores' coupling
    times the head's own bracket: g e^{-|k| y} [core sinc(k g / 2) - (unshielded L + core)
    cos(k e_c) R(k)]."""
    k = np.asarray(k, float)
    g, p, r = head.gap_m, head.pole_m, head.relax_m
    gap = np.sinc(k * g / (2.0 * math.pi))
    ec = g / 2.0 + p + r / 2.0
    relax = np.sinc(k * r / (2.0 * math.pi)) if r > 0 else 1.0
    if lat is None:
        lat = lateral_factor(k, x.pitch_m, x.contour_width_m)
    bracket = x.core * gap - (x.unshielded * lat + x.core) * np.cos(k * ec) * relax
    return g * np.exp(-np.abs(k) * y) * bracket


_LATERAL_CACHE: dict[tuple, np.ndarray] = {}


def _lateral_on(k: np.ndarray, x: CrossPickup) -> np.ndarray:
    """`lateral_factor` on an FFT's bins, kept per (bins, spacing, pickup): a stream asks
    for the same grid every block."""
    key = (len(k), float(k[1]) if len(k) > 1 else 0.0, x.pitch_m, x.contour_width_m)
    if key not in _LATERAL_CACHE:
        _LATERAL_CACHE[key] = lateral_factor(k, x.pitch_m, x.contour_width_m)
    return _LATERAL_CACHE[key]


@dataclass(frozen=True)
class Orientation:
    """The particles' easy axes in the x-y plane (along the tape and into the coating):
    n directions phi_j = -pi/2 + (j + 1/2) pi / n, weighted exp(kappa cos 2 phi) (an axial
    von Mises distribution; kappa = 0 unoriented, large: aligned along the tape). Each
    direction is a scalar Preisach ensemble driven by the field along its axis (the vector
    Preisach model of Mayergoyz, "Mathematical Models of Hysteresis", ch. 3)."""

    kappa: float
    n: int = 8

    def axes(self) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """(cos phi, sin phi, weight) per direction, weights summing to 1."""
        phi = -math.pi / 2.0 + (np.arange(self.n) + 0.5) * math.pi / self.n
        w = np.exp(self.kappa * (np.cos(2.0 * phi) - 1.0))
        return np.cos(phi), np.sin(phi), w / w.sum()


# --- Recording ------------------------------------------------------------------------


@dataclass(frozen=True)
class Slab:
    """The coating as cells: `layers` depths over thickness_m, cells ds_m long along the
    tape, at head-to-tape spacing spacing_m."""

    thickness_m: float
    layers: int
    ds_m: float
    spacing_m: float

    @property
    def depths_m(self) -> np.ndarray:
        """Each layer's centre, from the coating's surface."""
        dy = self.thickness_m / self.layers
        return (np.arange(self.layers) + 0.5) * dy


def bias_peak_times(t0_s: float, t1_s: float, f_bias_hz: float, sub: int = 1) -> np.ndarray:
    """Sample times for the bias: `sub` per half cycle of sin(2 pi f t), centred on the
    half cycle's peak (sub = 1: the peaks, where the carrier is +-1)."""
    half = 0.5 / f_bias_hz
    k0 = math.floor(t0_s / half)
    k1 = math.ceil(t1_s / half)
    k = np.arange(k0, k1)
    off = (np.arange(sub) - sub // 2) / sub  # within the half cycle, the peak included
    t = ((k[:, None] + 0.5) + off[None, :]) * half
    return t.ravel()


def zone_halfwidth_m(
    head: HeadGeometry, y_m: float, hg_peak: float, h_min: float, vector: bool = False
) -> float:
    """How far from the gap a cell at height y still sees |Hx| >= h_min (vector: |H|) when
    the deep-gap field peaks at hg_peak (the gap region only: the far pole edges' fields
    are checked to stay below h_min by the caller)."""
    if hg_peak <= h_min:
        return 0.0

    def mag(x: float) -> float:
        hx, hy = head_field(head, np.array([x]), np.array([y_m]))
        return float(np.hypot(hx[0], hy[0]) if vector else abs(hx[0]))

    # The field falls monotonically outside the gap (its Karlqvist part): bisect.
    lo, hi = 0.0, head.gap_m
    while mag(hi) * hg_peak >= h_min:
        hi *= 2.0
        if hi > 0.5 * head.pole_m:
            return hi
    for _ in range(60):
        mid = 0.5 * (lo + hi)
        if mag(mid) * hg_peak >= h_min:
            lo = mid
        else:
            hi = mid
    return hi


def switching_floor(pre, tol: float = 1e-7) -> float:
    """The field below which hysterons of total weight < tol can switch from any state
    (|alpha| or |beta| below it), on the ensemble's discrete grid (`pre.grid`). The
    continuous density has no such gap (hysterons near alpha = 0 or beta = 0 have weight
    ~ linear in the field: 1e-3 below ~4.5 Oe for Scotch 111), so on a coarse grid this is
    half a grid step for any small tol (31 Oe on the 64-point grid). A machine sets its
    zone floor explicitly instead (`record`'s floor_a_m, measured: TAPE_PLAN.md)."""
    a = pre.grid
    w = pre.weights
    reach = np.minimum(np.abs(a)[:, None], np.abs(a)[None, :])
    order = np.argsort(reach, axis=None)
    cum = np.cumsum(w.ravel()[order])
    k = int(np.searchsorted(cum, tol))
    return float(reach.ravel()[order][min(k, len(order) - 1)])


def record(
    pre,
    head: HeadGeometry,
    slab: Slab,
    hg_signal,
    hg_bias: float,
    f_bias_hz: float,
    s_rec,
    t0_s: float,
    t1_s: float,
    s_cells_m: np.ndarray,
    sub: int = 1,
    hg_signal_max: float | None = None,
    chunk: int = 4096,
    h_static: np.ndarray | None = None,
    bias_phase_rad: float = 0.0,
    orientation: Orientation | None = None,
    engine: str = "python",
    h_end: np.ndarray | tuple | None = None,
    table_step: float = 0.0,
    floor_tol: float = 1e-7,
    floor_a_m: float | None = None,
    local_zones: bool = False,
    peaks: tuple[np.ndarray, np.ndarray] | None = None,
):
    """The remanent M / Ms of cells at tape positions s_cells_m (one row per layer of
    `slab`), recorded from t0_s to t1_s, the tape erased before.

    hg_signal(t): the signal's deep-gap field (A/m) at times t; the bias adds
    hg_bias sin(2 pi f_bias t). s_rec(t): the tape position at the record gap (rising).
    Each cell sees the head's field at the bias's sample times (`bias_peak_times`, `sub`
    per half cycle) while it is in the zone where the field can switch hysterons, then
    the field removed (it leaves the head). hg_signal_max bounds |hg_signal| (for the
    zone; default: its maximum over the samples). h_static (layers x cells, A/m): a steady
    field on each cell through its whole pass and after it (demagnetization,
    `record_demagnetized`): the cell is left in it instead of in zero field. bias_phase_rad:
    the oscillator's phase at t = 0 (it runs free of the signal).

    orientation: None, the particles all along the tape (a scalar model of Hx; returns
    M_x / Ms, layers x cells); else the particles' axes (`Orientation`), each direction
    driven by the head's field along it (returns (M_x, M_y) / Ms). h_static: along x, or
    a pair (H_x, H_y). h_end: the field the cell is left in after its pass, if not h_static
    (under the head the tape's own field differs from free tape's: the head's image).

    engine: "python" (this reference) or "rust" (circuitsim's `tape_record`, the port: the
    same inputs, cells in parallel; agreement in tests/test_tape.py). table_step (rust
    only): the head field tabulated per layer at this fraction of the layer's height, cubic
    between points (0: exact at every sample). floor_tol: the zone ends where the field can
    switch only hysterons of less total weight (`switching_floor`, on the ensemble's
    discrete grid); floor_a_m, if given, is the zone's floor instead (A/m: the field
    magnitude below which a cell's samples are left out). local_zones: each cell's zone
    from the largest |deep-gap field| over its own pass (rounded up, `_cell_zones`)
    instead of hg_signal_max for all: the same floor, fewer samples where the signal is
    quieter than its peak.

    peaks (t, hg): the deep-gap field's extrema, given (the literal bias: the head's whole
    current from the circuit, `TapeStream`'s literal mode) instead of the signal plus a
    regenerated carrier: hg_signal, hg_bias, f_bias_hz, sub and bias_phase_rad aren't read.
    """
    if peaks is not None:
        t, hg = (np.asarray(a, float) for a in peaks)
    else:
        shift = bias_phase_rad / (2.0 * math.pi * f_bias_hz)
        t = bias_peak_times(t0_s + shift, t1_s + shift, f_bias_hz, sub) - shift
        t = t[(t >= t0_s) & (t <= t1_s)]
        hg = np.asarray(hg_signal(t), float) + hg_bias * np.sin(
            2.0 * math.pi * f_bias_hz * t + bias_phase_rad
        )
    srec = np.asarray(s_rec(t), float)
    peak = (hg_signal_max if hg_signal_max is not None else float(np.abs(hg).max())) + hg_bias
    if floor_a_m is None:
        floor = switching_floor(pre, floor_tol)
        # The far pole edges' weak fields may touch hysterons of weight < 1e-4 (-80 dB):
        # the zone leaves them out.
        edge_floor = switching_floor(pre, 1e-4)
    else:
        floor = edge_floor = float(floor_a_m)
    s_cells_m = np.asarray(s_cells_m, float)
    vector = orientation is not None
    cs, sn, wt = orientation.axes() if vector else (np.ones(1), np.zeros(1), np.ones(1))
    heights = slab.spacing_m + slab.depths_m
    zones = np.array(
        [_zone_checked(head, y, peak, floor, edge_floor, vector) for y in heights], float
    )
    if local_zones:
        zones = _cell_zones(head, heights, zones, hg, srec, s_cells_m, peak, floor, vector)
    if engine == "rust":
        return _record_rust(
            pre,
            head,
            slab,
            srec,
            hg,
            s_cells_m,
            zones,
            h_static,
            vector,
            np.stack([cs, sn, wt], axis=1),
            h_end,
            table_step,
        )
    if engine != "python":
        raise ValueError(f"unknown engine {engine!r}")
    out = np.zeros((slab.layers, len(s_cells_m)))
    out_y = np.zeros((slab.layers, len(s_cells_m)))
    for li, depth in enumerate(slab.depths_m):
        y = slab.spacing_m + depth
        xz = zones[li]
        k0 = np.searchsorted(srec, s_cells_m - xz, side="left")
        k1 = np.searchsorted(srec, s_cells_m + xz, side="right")
        n_max = int((k1 - k0).max()) if len(s_cells_m) else 0
        for c0 in range(0, len(s_cells_m), chunk):
            c1 = min(c0 + chunk, len(s_cells_m))
            j = np.arange(n_max)[None, :]
            idx = k0[c0:c1, None] + j
            live = idx < k1[c0:c1, None]
            idx = np.minimum(idx, len(t) - 1)
            x = s_cells_m[c0:c1, None] - srec[idx]
            if vector:
                fx, fy = head_field(head, x, np.full_like(x, y))
                fy = np.where(live, hg[idx] * fy, 0.0)
            else:
                fx, fy = head_hx(head, x, np.full_like(x, y)), None
            fx = np.where(live, hg[idx] * fx, 0.0)
            if h_static is None:
                hsx = hsy = None
            elif isinstance(h_static, tuple):
                hsx, hsy = h_static[0][li, c0:c1, None], h_static[1][li, c0:c1, None]
            else:
                hsx, hsy = h_static[li, c0:c1, None], None
            if h_end is None:
                hex_ = hey = None
            elif isinstance(h_end, tuple):
                hex_, hey = h_end[0][li, c0:c1, None], h_end[1][li, c0:c1, None]
            else:
                hex_, hey = h_end[li, c0:c1, None], None
            if h_end is None:
                hex_, hey = hsx, hsy
            for c, sv, w in zip(cs, sn, wt, strict=True):
                h = c * fx if fy is None else c * fx + sv * fy
                end = np.zeros((c1 - c0, 1))
                stat = np.zeros((c1 - c0, 1))
                if hsx is not None:
                    stat = stat + (c * hsx if hsy is None else c * hsx + sv * hsy)
                    h = h + stat
                if hex_ is not None:
                    end = end + (c * hex_ if hey is None else c * hex_ + sv * hey)
                # The history: the pass, the steady field alone as the cell leaves the
                # head (also where the zone ends early: the padding past k1 holds it
                # too), then the field it is left in.
                m = pre.state_after(np.concatenate([h, stat, end], axis=1))
                out[li, c0:c1] += w * c * m
                out_y[li, c0:c1] += w * sv * m
    return (out, out_y) if vector else out


def _zone_checked(head, y, peak, floor, edge_floor, vector) -> float:
    xz = zone_halfwidth_m(head, y, peak, floor, vector)
    # The far pole edges must stay below the floor (else the zone is wrong).
    e = head.gap_m / 2.0 + head.pole_m + head.relax_m
    ex, ey = head_field(head, np.array([e]), np.array([y]))
    edge = float(np.hypot(ex[0], ey[0]) if vector else abs(ex[0])) * peak
    if edge >= edge_floor:
        raise ValueError(f"the pole edges switch hysterons ({edge:.3g} >= {edge_floor:.3g} A/m)")
    return xz


def _range_max(v: np.ndarray, k0: np.ndarray, k1: np.ndarray) -> np.ndarray:
    """max(v[k0:k1]) per pair (0 where empty), by a sparse table."""
    n = len(v)
    out = np.zeros(len(k0))
    if n == 0:
        return out
    levels = [np.asarray(v, float)]
    while (1 << len(levels)) <= n:
        prev, w = levels[-1], 1 << (len(levels) - 1)
        levels.append(np.maximum(prev[:-w], prev[w:]))
    k0 = np.clip(k0, 0, n)
    k1 = np.clip(k1, 0, n)
    length = k1 - k0
    live = length > 0
    lv = np.zeros(len(k0), np.int64)
    lv[live] = np.floor(np.log2(length[live])).astype(np.int64)
    for j in np.unique(lv[live]):
        sel = live & (lv == j)
        t = levels[j]
        out[sel] = np.maximum(t[k0[sel]], t[k1[sel] - (1 << j)])
    return out


#: Peaks per octave of `_cell_zones`' grid, and its octaves above the floor.
_ZONE_STEPS, _ZONE_OCTAVES = 8, 16
_ZONE_TABLES: dict[tuple, np.ndarray] = {}


def _zone_table(head, y, floor, vector) -> np.ndarray:
    """zone_halfwidth_m at the peaks floor 2^(i / _ZONE_STEPS), kept (they don't depend
    on the recording)."""
    key = (head, float(y), float(floor), vector)
    if key not in _ZONE_TABLES:
        grid = floor * 2.0 ** (np.arange(_ZONE_STEPS * _ZONE_OCTAVES + 1) / _ZONE_STEPS)
        if len(_ZONE_TABLES) > 64:
            _ZONE_TABLES.pop(next(iter(_ZONE_TABLES)))
        _ZONE_TABLES[key] = np.array([zone_halfwidth_m(head, y, p, floor, vector) for p in grid])
    return _ZONE_TABLES[key]


def _cell_zones(head, heights, outer, hg, srec, s_cells, peak, floor, vector):
    """Each cell's zone half-width per layer (layers x cells): the zone of the largest
    |hg| among the samples within the widest outer zone (`outer`: per layer, for the
    whole recording's peak), rounded up to a geometric grid of peaks above the floor
    (`_zone_table`), at most the outer zone. A bound like the outer zone's, so the floor
    means the same."""
    w = float(np.max(outer))
    k0 = np.searchsorted(srec, s_cells - w, side="left")
    k1 = np.searchsorted(srec, s_cells + w, side="right")
    local = _range_max(np.abs(hg), k0, k1)
    # The smallest grid peak at or above each cell's (past the grid: the outer zone).
    u = np.log2(np.maximum(local, floor) / floor) * _ZONE_STEPS
    gi = np.ceil(u).astype(np.int64)
    n = _ZONE_STEPS * _ZONE_OCTAVES
    zones = np.empty((len(heights), len(s_cells)))
    for li, y in enumerate(heights):
        table = _zone_table(head, y, floor, vector)
        z = np.where(gi > n, np.inf, table[np.minimum(gi, n)])
        zones[li] = np.minimum(z, outer[li])
    return zones


def _record_rust(
    pre,
    head,
    slab,
    srec,
    hg,
    s_cells,
    zones,
    h_static,
    vector,
    axes,
    h_end=None,
    table_step=0.0,
):
    """`record`'s kernel in circuitsim (`tape_record`): zones per layer, or per layer and
    cell (`_cell_zones`)."""
    import circuitsim

    heights = slab.spacing_m + slab.depths_m
    p = pre.p

    def flat(h):
        if h is None:
            return None, None
        if isinstance(h, tuple):
            return tuple(np.ascontiguousarray(a, float).ravel() for a in h)
        return np.ascontiguousarray(h, float).ravel(), None

    hx, hy = flat(h_static)
    ex, ey = flat(h_end)
    mx, my = circuitsim.tape_record(
        (p.hc_median_a_m, p.sigma_ln_hc, p.sigma_hi_a_m, p.h_max_a_m, p.n_table),
        (head.gap_m, head.pole_m, head.relax_m),
        np.ascontiguousarray(heights, float),
        np.ascontiguousarray(zones, float).ravel(),
        np.ascontiguousarray(srec, float),
        np.ascontiguousarray(hg, float),
        np.ascontiguousarray(s_cells, float),
        np.ascontiguousarray(axes, float).ravel(),
        hx,
        hy,
        ex,
        ey,
        table_step,
    )
    shape = (slab.layers, len(s_cells))
    mx, my = np.asarray(mx).reshape(shape), np.asarray(my).reshape(shape)
    return (mx, my) if vector else mx


# --- Playback -------------------------------------------------------------------------


def flux_slope(
    m: np.ndarray,
    slab: Slab,
    head: HeadGeometry,
    k_max: float | None = None,
    m_y: np.ndarray | None = None,
    cross: CrossPickup | None = None,
) -> np.ndarray:
    """G(s) = d/ds of sum_l integral m_l(s') Hx_l(s' - s) ds' / Hg on the cells' grid
    (s the repro gap's position; Hx_l the head's field at layer l's height), from the
    cells' samples m (layers x cells) read as band limited, by the field's closed-form
    spectrum. k_max (rad/m) cuts the spectrum off smoothly above 0.8 k_max (to sample
    the EMF without aliasing); None keeps all of it. m_y: the cells' M_y / Ms, read through
    Hy (reciprocity: M . H), if any. F(s) = integral m(s') K(s' - s) ds' has the spectrum
    m^(k) K^(-k): K^(k) for the even Hx, -K^(k) for the odd Hy.

    cross: the slope a neighbouring head reads (`cross_hx_spectrum`, Hy's i sgn(k) times
    it as for the head's own)."""
    layers, cells = m.shape
    ext = int(math.ceil(4.0 * (head.gap_m / 2.0 + head.pole_m + head.relax_m) / slab.ds_m))
    n = 1 << int(math.ceil(math.log2(cells + 2 * ext)))
    k = 2.0 * math.pi * np.fft.rfftfreq(n, slab.ds_m)
    acc = np.zeros(len(k), complex)
    lat = None if cross is None else _lateral_on(k, cross)
    for li, depth in enumerate(slab.depths_m):
        if cross is None:
            spec = head_hx_spectrum(head, k, slab.spacing_m + depth)
        else:
            spec = cross_hx_spectrum(head, k, slab.spacing_m + depth, cross, lat)
        acc += np.fft.rfft(m[li], n) * spec
        if m_y is not None:
            acc -= np.fft.rfft(m_y[li], n) * (1j * np.sign(k) * spec)
    # d/ds -> i k.
    acc *= 1j * k
    if k_max is not None:
        u = np.clip((k / k_max - 0.8) / 0.2, 0.0, 1.0)
        acc *= np.where(k >= k_max, 0.0, 0.5 * (1.0 + np.cos(math.pi * u)))
    return np.fft.irfft(acc, n)[:cells]


def cubic_at(y: np.ndarray, u: np.ndarray) -> np.ndarray:
    """y (uniform samples) at fractional indices u: 4-point Lagrange (cubic), held at the
    ends."""
    n = len(y)
    i = np.clip(np.floor(u).astype(np.int64), 1, n - 3)
    f = u - i
    ym1, y0, y1, y2 = y[i - 1], y[i], y[i + 1], y[i + 2]
    return (
        -f * (f - 1) * (f - 2) / 6.0 * ym1
        + (f + 1) * (f - 1) * (f - 2) / 2.0 * y0
        - (f + 1) * f * (f - 2) / 2.0 * y1
        + (f + 1) * f * (f - 1) / 6.0 * y2
    )


def playback_emf(
    m: np.ndarray,
    s0_m: float,
    slab: Slab,
    head: HeadGeometry,
    h_per_a: float,
    width_m: float,
    ms_a_m: float,
    s_rep: np.ndarray,
    v_m_s: np.ndarray,
    k_max: float | None = None,
    m_y: np.ndarray | None = None,
) -> np.ndarray:
    """The repro coil's EMF (V) when its gap reads tape positions s_rep moving at v_m_s
    (arrays over the output's samples). m: the cells' M / Ms (layers x cells), cell c at
    s0_m + c ds; h_per_a: the head's deep-gap field per coil ampere (A/m / A: turns and
    efficiency over the gap length); ms_a_m: the coating's saturation magnetization.

    lambda(s) = mu0 W Ms h_per_a dy sum_l integral m_l(s') Hx_l(s' - s) / Hg ds', the EMF
    -d lambda / dt = -v d lambda / ds."""
    dy = slab.thickness_m / slab.layers
    g = flux_slope(m, slab, head, k_max, m_y)
    u = (np.asarray(s_rep, float) - s0_m) / slab.ds_m
    scale = MU0 * width_m * ms_a_m * h_per_a * dy
    return -np.asarray(v_m_s, float) * scale * cubic_at(g, u)


def short_circuit_fluxivity(
    m: np.ndarray, slab: Slab, ms_a_m: float, k_max: float | None = None
) -> np.ndarray:
    """The tape's short-circuit flux per track width (Wb/m) along the cells: what an
    ideal reproducer (no gap, no spacing, poles infinitely long) reads, mu0 Ms dy
    sum_l m_l: the quantity reference levels are given in (e.g. 250 nWb/m at 1 kHz,
    IEC 60094 / NAB)."""
    dy = slab.thickness_m / slab.layers
    phi = MU0 * ms_a_m * dy * m.sum(axis=0)
    if k_max is None:
        return phi
    n = 1 << int(math.ceil(math.log2(len(phi) * 2)))
    k = 2.0 * math.pi * np.fft.rfftfreq(n, slab.ds_m)
    u = np.clip((k / k_max - 0.8) / 0.2, 0.0, 1.0)
    w = np.where(k >= k_max, 0.0, 0.5 * (1.0 + np.cos(math.pi * u)))
    return np.fft.irfft(np.fft.rfft(phi, n) * w, n)[: len(phi)]


# --- Demagnetization -------------------------------------------------------------------


def demag_kernel(k: np.ndarray, slab: Slab) -> np.ndarray:
    """D[k, l, l'] with Hx_l(k) = -D M_l'(k): the x field averaged over layer l from a
    longitudinal magnetization M_l'(k) e^{ikx} uniform through layer l' (2D magnetostatics:
    a charge sheet -ik M dy' gives Hx = -(|k| / 2) M dy' e^{-|k| |y - y'|}). Uniform M through
    the whole coating gives the slab's demagnetizing factor 1 - (1 - e^{-k delta}) / (k delta)
    (layers summed)."""
    k = np.abs(np.asarray(k, float))
    n = slab.layers
    dy = slab.thickness_m / n
    ks = np.where(k > 0, k, 1.0)
    e = np.exp(-ks * dy)
    gap = np.abs(np.subtract.outer(np.arange(n), np.arange(n)))
    # Layers apart: (1 - e^{-k dy})^2 / k^2 e^{-k (|l - l'| - 1) dy}; the layer itself:
    # (2 / k) (dy - (1 - e^{-k dy}) / k). Both times (k / 2) / dy.
    cross = ((1.0 - e) ** 2 / ks**2)[:, None, None] * np.exp(
        -ks[:, None, None] * (gap[None] - 1) * dy
    )
    own = (2.0 / ks) * (dy - (1.0 - e) / ks)
    d = np.where(gap[None] == 0, own[:, None, None], cross)
    d = d * (ks / 2.0 / dy)[:, None, None]
    return np.where((k > 0)[:, None, None], d, 0.0)


def demag_field(
    m: np.ndarray, slab: Slab, ms_a_m: float, lam_min_m: float | None = None
) -> np.ndarray:
    """The x field (A/m, layers x cells) of the cells' magnetization Ms m on their own (no
    head nearby), the pattern zero outside the cells; lam_min_m: only from the pattern's
    wavelengths longer than it."""
    layers, cells = m.shape
    n = 1 << int(math.ceil(math.log2(2 * cells)))
    k = 2.0 * math.pi * np.fft.rfftfreq(n, slab.ds_m)
    mk = np.fft.rfft(m, n, axis=1)  # layers x k
    d = demag_kernel(k, slab)  # k x l x l'
    if lam_min_m is not None:
        d = d * (k < 2.0 * math.pi / lam_min_m)[:, None, None]
    hk = -np.einsum("kab,bk->ak", d, mk)
    return ms_a_m * np.fft.irfft(hk, n, axis=1)[:, :cells]


def record_demagnetized(
    pre,
    ms_a_m: float,
    head: HeadGeometry,
    slab: Slab,
    *args,
    iterations: int = 40,
    tol: float = 1e-6,
    history: int = 6,
    lam_min_m: float | None = None,
    **kwargs,
):
    """`record` with the recorded pattern's own field on every cell, self-consistently: M =
    record(h_static = demag(M)), solved by Anderson-accelerated fixed-point iteration.
    Returns (M / Ms, iterations used, the last step's largest change).

    Approximation: each cell sees the final pattern's field throughout its pass (also from
    neighbours upstream that are recorded only after it); after its pass that is exact."""
    m = record(pre, head, slab, *args, **kwargs)
    xs, gs = [], []
    change = float("inf")
    for it in range(1, iterations + 1):
        hd = demag_field(m, slab, ms_a_m, lam_min_m)
        g = record(pre, head, slab, *args, h_static=hd, **kwargs) - m
        change = float(np.abs(g).max())
        if change < tol:
            return m + g, it, change
        xs.append(m.ravel().copy())
        gs.append(g.ravel().copy())
        xs, gs = xs[-history:], gs[-history:]
        if len(gs) > 1:
            dg = np.diff(np.array(gs), axis=0)  # (h - 1) x N
            dx = np.diff(np.array(xs), axis=0)
            coef, *_ = np.linalg.lstsq(dg.T, g.ravel(), rcond=None)
            step = m.ravel() + g.ravel() - (dx + dg).T @ coef
        else:
            step = m.ravel() + 0.1 * g.ravel()
        m = np.clip(step, -1.0, 1.0).reshape(m.shape)
    return m, iterations, change


def _layer_profiles(k: np.ndarray, slab: Slab, q: int) -> tuple[np.ndarray, ...]:
    """For source layer l' = [a, b] and q midpoints y of each target layer:
    I = integral_a^b e^{-|k||y - y'|} dy', its y derivative, and the two face terms
    e^{-|k||y - b|}, e^{-|k||y - a|}; arrays k x (layers * q) x layers."""
    n = slab.layers
    dy = slab.thickness_m / n
    ks = np.maximum(np.abs(k), 1e-300)[:, None, None]
    y = ((np.arange(n * q) + 0.5) * dy / q)[None, :, None]
    a = (np.arange(n) * dy)[None, None, :]
    b = a + dy
    ea, eb = np.exp(-ks * np.abs(y - a)), np.exp(-ks * np.abs(y - b))
    above, below = y < a, y > b
    inside = ~(above | below)
    integ = np.where(inside, (2.0 - ea - eb) / ks, np.where(above, ea - eb, eb - ea) / ks)
    deriv = np.where(above, ea - eb, np.where(below, ea - eb, eb - ea))
    return integ, deriv, eb, ea


def demag_field_vector(
    mx: np.ndarray,
    my: np.ndarray,
    slab: Slab,
    ms_a_m: float,
    lam_min_m: float | None = None,
    q: int = 16,
    image_spacing_m: float | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """(H_x, H_y) (A/m, layers x cells, averaged over each layer) of the cells'
    magnetization Ms (mx, my), uniform through each layer (2D magnetostatics, the pattern
    zero outside the cells, no head nearby). M_x's volume charge -ik M_x and M_y's face
    charges +-M_y (y into the coating) each give phi = sigma e^{-|k||y - y0|} / (2 |k|);
    H = -grad phi. Uniform M_y through the coating is demagnetized by
    (1 - e^{-k delta}) / (k delta): the slab's x and y factors add to 1. lam_min_m: only
    from the pattern's wavelengths longer than it.

    image_spacing_m: the tape against a head (a highly permeable plane that far from the
    coating's surface): each charge has an image of opposite sign mirrored in the head's
    surface (tangential H vanishes there), which adds e^{-|k|(y + y' + 2d)} terms. At long
    wavelengths it cancels most of the demagnetization; at short ones it is too far away."""
    return demag_fields_vector(mx, my, slab, ms_a_m, lam_min_m, q, (image_spacing_m,))[0]


def demag_fields_vector(
    mx: np.ndarray,
    my: np.ndarray,
    slab: Slab,
    ms_a_m: float,
    lam_min_m: float | None = None,
    q: int = 16,
    image_spacings_m: tuple = (None,),
) -> list[tuple[np.ndarray, np.ndarray]]:
    """`demag_field_vector` for each of image_spacings_m (None: free tape), the pattern
    transformed once."""
    from scipy import fft as sfft

    layers, cells = mx.shape
    n = sfft.next_fast_len(2 * cells, real=True)
    mxk = myk = None
    out = []
    for image in image_spacings_m:
        keep, kern = _demag_kernels(n, slab, lam_min_m, q, image)
        if mxk is None:
            mxk = sfft.rfft(mx, n, axis=1, workers=-1)[:, keep].T  # k x l'
            myk = sfft.rfft(my, n, axis=1, workers=-1)[:, keep].T
        kxx, kxy, kyx, kyy = kern
        hxk = np.zeros((layers, n // 2 + 1), complex)
        hyk = np.zeros((layers, n // 2 + 1), complex)
        hxk[:, keep] = (np.einsum("kab,kb->ka", kxx, mxk) + np.einsum("kab,kb->ka", kxy, myk)).T
        hyk[:, keep] = (np.einsum("kab,kb->ka", kyx, mxk) + np.einsum("kab,kb->ka", kyy, myk)).T
        hx = sfft.irfft(hxk, n, axis=1, workers=-1)[:, :cells]
        hy = sfft.irfft(hyk, n, axis=1, workers=-1)[:, :cells]
        out.append((ms_a_m * hx, ms_a_m * hy))
    return out


_DEMAG_KERNELS: dict[tuple, tuple] = {}


def _demag_kernels(n: int, slab: Slab, lam_min_m, q: int, image_spacing_m):
    """The layer-averaged kernels of `demag_field_vector` at the kept wavenumbers of an
    n-point transform (they don't depend on the magnetization: built once, kept)."""
    key = (n, slab.ds_m, slab.thickness_m, slab.layers, lam_min_m, q, image_spacing_m)
    if key in _DEMAG_KERNELS:
        return _DEMAG_KERNELS[key]
    layers = slab.layers
    k = 2.0 * math.pi * np.fft.rfftfreq(n, slab.ds_m)
    keep = (k > 0) if lam_min_m is None else (k > 0) & (k < 2.0 * math.pi / lam_min_m)
    kk = k[keep]
    out = [np.zeros((len(kk), layers, layers), complex) for _ in range(4)]
    y = ((np.arange(layers * q) + 0.5) * slab.thickness_m / (layers * q))[None, :, None]
    dyl = slab.thickness_m / layers
    a = (np.arange(layers) * dyl)[None, None, :]
    b = a + dyl

    def avg(t):
        return t.reshape(t.shape[0], layers, q, layers).mean(axis=2)  # k x l x l'

    for j0 in range(0, len(kk), 512):
        kc = kk[j0 : j0 + 512]
        integ, deriv, eb, ea = _layer_profiles(kc, slab, q)
        kab = np.abs(kc)[:, None, None]
        sg = np.sign(kc)[:, None, None]
        # M_x: Hx = -(|k|/2) M_x I, Hy = (i sgn k / 2) M_x dI/dy.
        # M_y: Hx = -(i sgn k / 2) M_y (e_b - e_a); Hy: the faces' sgn(y - y0) terms, +M_y
        # at b gives sgn(y - b) e_b / 2, -M_y at a gives -sgn(y - a) e_a / 2.
        kx_x = -(kab / 2.0) * integ
        ky_x = 0.5j * sg * deriv
        kx_y = -0.5j * sg * (eb - ea)
        hy_from_my = 0.5 * (np.sign(y - b) * eb - np.sign(y - a) * ea)
        if image_spacing_m is not None:
            # Images below the head's surface: M_x's volume charge +ik M_x over the mirrored
            # layer, M_y's faces -M_y at -2d - b and +M_y at -2d - a; the target is always
            # above them.
            d2 = 2.0 * image_spacing_m
            ia = np.exp(-kab * (y + d2 + a))
            ib = np.exp(-kab * (y + d2 + b))
            jint = (ia - ib) / kab
            kx_x = kx_x + (kab / 2.0) * jint
            ky_x = ky_x + 0.5j * sg * kab * jint
            kx_y = kx_y - 0.5j * sg * (ia - ib)
            hy_from_my = hy_from_my + 0.5 * (ia - ib)
        sl = slice(j0, j0 + len(kc))
        out[0][sl], out[1][sl] = avg(kx_x), avg(kx_y)
        out[2][sl], out[3][sl] = avg(ky_x), avg(hy_from_my)
    if len(_DEMAG_KERNELS) > 8:
        _DEMAG_KERNELS.pop(next(iter(_DEMAG_KERNELS)))
    _DEMAG_KERNELS[key] = (keep, tuple(out))
    return _DEMAG_KERNELS[key]


def lstsq_mgs(cols: list[np.ndarray], b: np.ndarray) -> list[float]:
    """The least-squares coefficients c minimizing |sum_j c_j cols[j] - b| by modified
    Gram-Schmidt in column order (circuitsim's `tape_stream` does the same, step for
    step). A column whose remainder falls below 1e-10 of its norm is dropped (c_j = 0)."""
    p = len(cols)
    qs: list[tuple[int, np.ndarray]] = []
    r = np.zeros((p, p))
    for j in range(p):
        v = cols[j].copy()
        n0 = math.sqrt(float(np.dot(v, v)))
        for i, q in qs:
            r[i, j] = float(np.dot(q, v))
            v -= r[i, j] * q
        n = math.sqrt(float(np.dot(v, v)))
        if n0 == 0.0 or n <= 1e-10 * n0:
            continue
        r[j, j] = n
        qs.append((j, v / n))
    qb = {i: float(np.dot(q, b)) for i, q in qs}
    c = [0.0] * p
    kept = [i for i, _ in qs]
    for a, i in reversed(list(enumerate(kept))):
        s = qb[i]
        for k in kept[a + 1 :]:
            s -= r[i, k] * c[k]
        c[i] = s / r[i, i]
    return c


def record_demagnetized_vector(
    pre,
    ms_a_m: float,
    head: HeadGeometry,
    slab: Slab,
    *args,
    iterations: int = 40,
    tol: float = 1e-4,
    history: int = 6,
    lam_min_m: float | None = None,
    head_image: bool = False,
    **kwargs,
):
    """`record` with orientations and the recorded pattern's own field (both components)
    on every cell, self-consistently, as `record_demagnetized` does for M_x. head_image:
    during its pass a cell sees the field with the head's image (`demag_field_vector`'s
    image_spacing_m, the slab's spacing), after it free tape's. Returns (M_x, M_y,
    iterations used, the last step's largest change)."""

    def fields(mx, my) -> dict:
        if head_image:
            hd, hz = demag_fields_vector(
                mx, my, slab, ms_a_m, lam_min_m, image_spacings_m=(None, slab.spacing_m)
            )
            return {"h_static": hz, "h_end": hd}
        return {"h_static": demag_field_vector(mx, my, slab, ms_a_m, lam_min_m)}

    mx, my = record(pre, head, slab, *args, **kwargs)
    shape = mx.shape
    x = np.concatenate([mx.ravel(), my.ravel()])
    xs, gs = [], []
    change = float("inf")
    for it in range(1, iterations + 1):
        nx, ny = record(pre, head, slab, *args, **kwargs, **fields(mx, my))
        g = np.concatenate([nx.ravel(), ny.ravel()]) - x
        change = float(np.abs(g).max())
        if change < tol:
            return nx, ny, it, change
        xs.append(x.copy())
        gs.append(g.copy())
        xs, gs = xs[-history:], gs[-history:]
        if len(gs) > 1:
            dg = [gs[i + 1] - gs[i] for i in range(len(gs) - 1)]
            dx = [xs[i + 1] - xs[i] for i in range(len(xs) - 1)]
            coef = lstsq_mgs(dg, g)
            for c, a, b in zip(coef, dx, dg, strict=True):
                if c != 0.0:
                    x = x - c * (a + b)
            x = x + g
        else:
            x = x + 0.1 * g
        x = np.clip(x, -1.0, 1.0)
        mx, my = x[: mx.size].reshape(shape), x[mx.size :].reshape(shape)
    return mx, my, iterations, change
