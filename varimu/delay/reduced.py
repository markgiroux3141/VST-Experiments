"""The reduced tape medium: the live tier's tape (docs/DELAY_PLAN.md, "The reduced medium").

`TapeStream` (varimu.devices.tape_machine) records each block of tape by running every
0.5 um cell's Preisach ensemble over every bias peak in its zone, then iterates the
recorded pattern's own field to a fixed point. Here only that recording is replaced; the
blocks, the transport, the read a head distance later and the playback by reciprocity are
the stream's own. Per layer l, on coarse cells, with H(t) the deep-gap signal field and
t(s) the time cell s is at the gap's centre:

    g_l(s)   = sum_j ax_l[j] H(t(s) + tau_j)                (ax_l sums to 1)
    M_x,l(s) = T_l(g_l(s))
    M_y,l(s) = sat_l(g_l(s)) sum_j ky_l[j] H(t(s) + tau_j)

- T_l: M_x / Ms against a constant field H, recorded by the real kernel at the stream's
  bias (the ensemble's remanence after the bias has decayed; orientations and the layer's
  depth in it). sat_l(g) = T_l(g) / (T_l'(0) g), the particles' saturation.
- ax_l, ky_l: the layer's apertures in time after the gap's centre, the reference's
  small-signal step response (`apertures`): where the decaying bias last switches the
  layer's particles; they carry the HF self-erasure. ky_l is M_y's (bipolar: Hy is odd
  about the gap), in M / Ms per A/m.

Both are taken without the recorded pattern's own field (demagnetization): its effect is
mostly linear and long-range (a step's field reaches back hundreds of um), so the stream
applies it as one correction filter on the EMF, measured against the reference at low
level (`demag_correction`). Known approximations (measured, not modelled): one aperture
per layer at every level; demagnetization's level dependence.
"""

from __future__ import annotations

import dataclasses
import math
import time
from dataclasses import dataclass

import numpy as np

from varimu.devices import tape_machine as tm
from varimu.devices.tape import TapeFormulation, cubic_at

#: Recording a table point: this much tape at a constant field, its middle third kept.
TABLE_LENGTH_M = 300e-6


def _plain(spec):
    """The spec recording without the pattern's own field."""
    return dataclasses.replace(spec, demag_iterations=0)


@dataclass(frozen=True)
class Reduction:
    """A medium's reduction at one bias (see the module docs): tables of M_x over h_a_m
    (layers x points), apertures (layers x taps, the first at tau0_s, then every dt_s)."""

    h_a_m: np.ndarray
    mx: np.ndarray
    slope: np.ndarray  # T_l'(0) per layer
    tau0_s: float
    dt_s: float
    ax: np.ndarray
    ky: np.ndarray
    hg_bias: float

    @property
    def tau(self) -> np.ndarray:
        return self.tau0_s + self.dt_s * np.arange(self.ax.shape[1])


@dataclass(frozen=True)
class BiasReductions:
    """A medium's reductions on a grid of bias amplitudes (rising; one table grid and one
    aperture grid), for BIAS as a knob: `at` interpolates linearly in ln(bias) between
    the neighbouring points (held past the ends). One point is a single bias's reduction."""

    points: tuple[Reduction, ...]

    @property
    def bias_a_m(self) -> np.ndarray:
        return np.array([r.hg_bias for r in self.points])

    def weights(self, hg_bias: float) -> tuple[int, float]:
        """(j, w): the bias between points j and j + 1, w of the way in ln(bias) (w 0 at
        or below the first point, j the last point and w 0 at or above it)."""
        n = len(self.points)
        if n == 1:
            return 0, 0.0
        lb = np.log(self.bias_a_m)
        x = math.log(hg_bias)
        if x <= lb[0]:
            return 0, 0.0
        if x >= lb[-1]:
            return n - 1, 0.0
        j = int(np.searchsorted(lb, x, side="right")) - 1
        return j, float((x - lb[j]) / (lb[j + 1] - lb[j]))

    def mix(self, rows: np.ndarray, hg_bias: float) -> np.ndarray:
        """rows (one per point) at hg_bias, as `at` mixes the tables."""
        j, w = self.weights(hg_bias)
        if w == 0.0:
            return np.asarray(rows[j])
        return (1.0 - w) * np.asarray(rows[j]) + w * np.asarray(rows[j + 1])

    def at(self, hg_bias: float) -> Reduction:
        pts = self.points
        if len(pts) == 1:
            return pts[0]
        j, w = self.weights(hg_bias)
        if w == 0.0:
            return dataclasses.replace(pts[j], hg_bias=hg_bias)
        a, b = pts[j], pts[j + 1]

        def mix(u, v):
            return (1.0 - w) * u + w * v

        return dataclasses.replace(
            a,
            mx=mix(a.mx, b.mx),
            slope=mix(a.slope, b.slope),
            ax=mix(a.ax, b.ax),
            ky=mix(a.ky, b.ky),
            hg_bias=hg_bias,
        )


def _record_const(spec, tape, hg_bias: float, h: float, length_m: float):
    """(M_x, M_y) / Ms (layers x cells) of `length_m` of tape recorded at a constant
    signal field h with the bias."""
    v, ds = spec.speed_m_s, spec.ds_m
    s = np.arange(int(round(length_m / ds))) * ds
    t0 = -tm.ZONE_PAD_M / v
    t1 = (s[-1] + tm.ZONE_PAD_M) / v
    return tm._record(
        _plain(spec),
        tape,
        lambda t: np.full_like(np.asarray(t, float), h),
        hg_bias,
        t0,
        t1,
        s,
        abs(h),
    )


def tables(spec, tape: TapeFormulation, hg_bias: float, h_a_m: np.ndarray) -> np.ndarray:
    """T_l(H): the middle third's mean M_x / Ms per layer at each field (layers x points)."""
    mx = np.zeros((spec.layers, len(h_a_m)))
    for i, h in enumerate(h_a_m):
        ax, _ = _record_const(spec, tape, hg_bias, float(h), TABLE_LENGTH_M)
        n = ax.shape[1]
        mx[:, i] = ax[:, n // 3 : 2 * n // 3].mean(axis=1)
    return mx


def step_response(spec, tape, hg_bias: float, h0: float, dh: float, length_m: float = 400e-6):
    """The cells' (M_x, M_y) / Ms recorded with the field stepping from h0 to h0 + dh as
    the middle cell passes the gap's centre, and each cell's time at the gap relative to
    the step (s)."""
    v, ds = spec.speed_m_s, spec.ds_m
    s = np.arange(int(round(length_m / ds))) * ds
    t_step = s[len(s) // 2] / v
    t0 = -tm.ZONE_PAD_M / v
    t1 = (s[-1] + tm.ZONE_PAD_M) / v

    def hg(t):
        return np.where(np.asarray(t, float) >= t_step, h0 + dh, h0)

    mx, my = tm._record(_plain(spec), tape, hg, hg_bias, t0, t1, s, abs(h0) + abs(dh))
    return mx, my, s / v - t_step


def apertures(spec, tape, hg_bias: float, dh: float = 300.0):
    """(tau, ax, ky): each layer's apertures from the step response (layers x taps, tau
    rising, the reference's cell time apart). A cell at the gap at t_c records the step at
    t = 0 if its switching point t_c + tau lies after it, so the response r(t_c) =
    sum_{tau > -t_c} a(tau) and a(tau) = r's increment at t_c = -tau. The step is taken
    both ways (+-dh) and halved, so the table's curvature cancels. ax is normalized to sum
    to 1; ky is per A/m."""
    up = step_response(spec, tape, hg_bias, 0.0, dh)
    dn = step_response(spec, tape, hg_bias, 0.0, -dh)
    tc = up[2]
    tau = -0.5 * (tc[1:] + tc[:-1])
    order = np.argsort(tau)
    rx = 0.5 * (up[0] - dn[0])
    ry = 0.5 * (up[1] - dn[1])
    ax = np.diff(rx, axis=1)[:, order]
    ky = np.diff(ry, axis=1)[:, order] / dh
    return tau[order], ax / ax.sum(axis=1, keepdims=True), ky


def _untrimmed(spec, tape, hg_bias: float, h: np.ndarray) -> Reduction:
    """The tables (odd-symmetrized) and the whole apertures at one bias."""
    mx = tables(spec, tape, hg_bias, h)
    mx = 0.5 * (mx - mx[:, ::-1])
    i0 = len(h) // 2
    slope = (mx[:, i0 + 1] - mx[:, i0 - 1]) / (h[i0 + 1] - h[i0 - 1])
    tau, ax, ky = apertures(spec, tape, hg_bias)
    return Reduction(h, mx, slope, float(tau[0]), float(tau[1] - tau[0]), ax, ky, hg_bias)


def _span(r: Reduction, trim: float) -> tuple[int, int]:
    """The taps holding all but `trim` of the apertures' weight (both tails)."""
    ax, ky = r.ax, r.ky
    w = np.abs(ax).sum(axis=0) + np.abs(ky).sum(axis=0) / np.abs(ky).sum() * np.abs(ax).sum()
    c = np.cumsum(w) / w.sum()
    return int(np.searchsorted(c, trim)), int(np.searchsorted(c, 1 - trim)) + 1


def _trimmed(r: Reduction, a: int, b: int) -> Reduction:
    ax = r.ax[:, a:b] / r.ax[:, a:b].sum(axis=1, keepdims=True)
    return dataclasses.replace(r, tau0_s=float(r.tau[a]), ax=ax, ky=r.ky[:, a:b])


def reduce(
    spec, tape, hg_bias: float, h_max: float, points: int = 321, trim: float = 1e-4
) -> Reduction:
    """The reduction: tables over +-h_max (odd-symmetrized), apertures trimmed where their
    tails' weight falls below `trim` of the total."""
    r = _untrimmed(spec, tape, hg_bias, np.linspace(-h_max, h_max, points))
    return _trimmed(r, *_span(r, trim))


def reduce_bias(
    spec, tape, biases_a_m, h_max: float, points: int = 321, trim: float = 1e-4, note=None
) -> BiasReductions:
    """`reduce` at each bias (rising), the apertures trimmed to one span: the union of
    each bias's (the same cells, so the same tap times)."""
    h = np.linspace(-h_max, h_max, points)
    rs = []
    for hb in biases_a_m:
        t0 = time.perf_counter()
        rs.append(_untrimmed(spec, tape, float(hb), h))
        if note:
            note(f"  bias {hb:.0f} A/m in {time.perf_counter() - t0:.0f} s")
    spans = [_span(r, trim) for r in rs]
    a, b = min(x[0] for x in spans), max(x[1] for x in spans)
    return BiasReductions(tuple(_trimmed(r, a, b) for r in rs))


def flux_slope_corrected(mx, my, slab, head, k_max, demag) -> np.ndarray:
    """`varimu.devices.tape.flux_slope` with the demagnetization correction D(k) (demag:
    (k rad/m rising, D), interpolated, 1 at k = 0, its last value held) on the spectrum."""
    from varimu.devices.tape import head_hx_spectrum, head_hy_spectrum

    layers, cells = mx.shape
    ext = int(math.ceil(4.0 * (head.gap_m / 2.0 + head.pole_m + head.relax_m) / slab.ds_m))
    n = 1 << int(math.ceil(math.log2(cells + 2 * ext)))
    k = 2.0 * math.pi * np.fft.rfftfreq(n, slab.ds_m)
    acc = np.zeros(len(k), complex)
    for li, depth in enumerate(slab.depths_m):
        y = slab.spacing_m + depth
        acc += np.fft.rfft(mx[li], n) * head_hx_spectrum(head, k, y)
        acc -= np.fft.rfft(my[li], n) * head_hy_spectrum(head, k, y)
    acc *= 1j * k
    if demag is not None:
        acc *= np.interp(k, demag[0], demag[1])
    u = np.clip((k / k_max - 0.8) / 0.2, 0.0, 1.0)
    acc *= np.where(k >= k_max, 0.0, 0.5 * (1.0 + np.cos(math.pi * u)))
    return np.fft.irfft(acc, n)[:cells]


def aperture_fir(
    tau: np.ndarray, a: np.ndarray, fs: float, k0: int | None = None, taps: int | None = None
) -> tuple[int, np.ndarray]:
    """Apertures (layers x len(tau), weights at times tau after a sample) as FIRs on the
    samples (`cubic_held` between them): sum_j a[j] H(t_n + tau_j) = sum_k c[k] H[n + k0 + k]
    exactly, each tap's cubic weights summed in tap order. k0, taps: the FIR's first offset
    and length (default: the span the taps reach)."""
    u = np.asarray(tau, float) * fs
    i = np.floor(u).astype(np.int64)
    f = u - i
    w = np.stack(
        [
            -f * (f - 1) * (f - 2) / 6.0,
            (f + 1) * (f - 1) * (f - 2) / 2.0,
            -(f + 1) * f * (f - 2) / 2.0,
            (f + 1) * f * (f - 1) / 6.0,
        ]
    )  # 4 x taps: at samples i - 1 .. i + 2
    if k0 is None:
        k0 = int(i.min()) - 1
    if taps is None:
        taps = int(i.max()) + 2 - k0 + 1
    c = np.zeros((a.shape[0], taps))
    for j in range(len(u)):
        for q in range(4):
            c[:, i[j] - 1 + q - k0] += a[:, j] * w[q, j]
    return k0, c


def fir_rows(hm: np.ndarray, c: np.ndarray) -> np.ndarray:
    """Each row of hm (samples n + k0 + k over k) times the FIR c, summed in k order (as
    circuitsim's port)."""
    out = np.zeros(hm.shape[0])
    for k in range(len(c)):
        out = out + c[k] * hm[:, k]
    return out


class ReducedStream(tm.TapeStream):
    """`TapeStream` with each block recorded by the reduction on coarse cells (ds_m long),
    played back with the demagnetization correction (demag: (k, D) or None; D one row, or
    one per point of a bias grid). red: one bias's reduction, or a bias grid's
    (`BiasReductions`): each block is then recorded at the bias set when it is recorded
    (`set_bias`; at first hg_bias, else the grid's first point's), and its flux slope
    taken with that bias's D."""

    def __init__(
        self,
        spec,
        tape,
        red: Reduction | BiasReductions,
        fs: float,
        ds_m: float = 2e-6,
        demag=None,
        hg_bias: float | None = None,
        **kw,
    ):
        reds = red if isinstance(red, BiasReductions) else BiasReductions((red,))
        bias = reds.points[0].hg_bias if hg_bias is None else hg_bias
        super().__init__(dataclasses.replace(spec, ds_m=ds_m), tape, bias, fs, **kw)
        self.reds = reds
        self.bias = bias
        self.red = reds.at(bias)
        self.demag = demag
        self.block_demag: dict[int, tuple[np.ndarray, np.ndarray] | None] = {}

    def set_bias(self, hg_bias: float) -> None:
        """The bias's deep-gap peak (A/m) for the blocks recorded from now on."""
        self.bias = hg_bias
        self.red = self.reds.at(hg_bias)

    def _demag_at(self, hg_bias: float):
        if self.demag is None:
            return None
        k, d = self.demag
        d = np.asarray(d)
        return (k, d) if d.ndim == 1 else (k, self.reds.mix(d, hg_bias))

    def table(self, li: int, g: np.ndarray) -> np.ndarray:
        """T_l(g): 4-point Lagrange on the table's uniform grid (`cubic_at`), g clipped to it."""
        h = self.red.h_a_m
        u = (np.clip(g, h[0], h[-1]) - h[0]) / (h[1] - h[0])
        return cubic_at(self.red.mx[li], u)

    def _slope_block(self, b: int) -> None:
        nb, nr = self.nb, self.nr
        w = nb + 2 * nr
        wx = np.zeros((self.spec.layers, w))
        wy = np.zeros((self.spec.layers, w))
        c0 = b * nb - nr
        for c in (b - 1, b, b + 1):
            if c not in self.rec:
                continue
            a0, a1 = max(c * nb, c0), min((c + 1) * nb, c0 + w)
            if a1 > a0:
                mx, my = self.rec[c]
                wx[:, a0 - c0 : a1 - c0] = mx[:, a0 - c * nb : a1 - c * nb]
                wy[:, a0 - c0 : a1 - c0] = my[:, a0 - c * nb : a1 - c * nb]
        demag = self.block_demag.get(b, self._demag_at(self.bias))
        g = flux_slope_corrected(wx, wy, self.slab, self.spec.rep_head(), self.k_max, demag)
        self.slopes[b] = g[nr - 2 : nr + nb + 2]

    def _record_block(self, b: int) -> None:
        """The block's cells: each layer's apertures as FIRs on the pushed samples
        (`aperture_fir`), read cubic at each cell's time at the gap, then the table."""
        j0, j1, _, _ = self._span(b)
        ds, fs, red = self.slab.ds_m, self.fs, self.red
        s = np.arange(j0, j1) * ds
        if self.moving:
            tc = np.interp(s, self.s, (self.s_first + np.arange(len(self.s))) / fs)
        else:
            tc = s / self.v
        u = tc * fs
        n_lo = math.floor(u.min()) - 1
        n_hi = math.floor(u.max()) + 2
        # The apertures are positions behind the gap: at the block's speed (its middle
        # cell's sample's varispeed factor) their times scale as 1 / ratio.
        ratio = 1.0
        if self.varispeed is not None:
            ratio = float(self._fac(max(math.floor(u[len(u) // 2]), 0)))
        tau = red.tau / ratio
        k0, cx = aperture_fir(tau, red.ax, fs)
        _, cy = aperture_fir(tau, red.ky, fs, k0=k0, taps=cx.shape[1])
        idx = np.arange(n_lo, n_hi + 1)[:, None] + k0 + np.arange(cx.shape[1])[None, :]
        hm = self.h[np.clip(idx - self.first, 0, len(self.h) - 1)]
        hmax = red.h_a_m[-1]
        mx = np.empty((self.spec.layers, len(s)))
        my = np.empty_like(mx)
        for li in range(self.spec.layers):
            g = np.clip(tm.cubic_held(fir_rows(hm, cx[li]), u, n_lo), -hmax, hmax)
            m = self.table(li, g)
            lin = red.slope[li] * g
            sat = np.where(np.abs(lin) > 1e-12, m / np.where(lin == 0, 1, lin), 1.0)
            mx[li] = m
            my[li] = sat * tm.cubic_held(fir_rows(hm, cy[li]), u, n_lo)
        i0 = b * self.nb
        mx = mx[:, i0 - j0 : i0 - j0 + self.nb].copy()
        my = my[:, i0 - j0 : i0 - j0 + self.nb].copy()
        if self.noise_seed is not None:
            self._grain(mx, my, i0)
        self.rec[b] = (mx, my)
        self.block_demag[b] = self._demag_at(self.bias)


def spec_351(values) -> tm.TapeMachineSpec:
    """The 351's heads and transport from its circuit file's resolved values (the tape
    part's physical values; numerics the stream's)."""
    keys = (
        "speed_m_s f_bias_hz rec_gap_m rep_gap_m pole_m relax_m spacing_m track_m "
        "head_distance_m capstan_d_m capstan_rms roller_d_m roller_rms reel_r_m reel_rms "
        "hunting_hz hunting_q hunting_rms scrape_span_m scrape_c_m_s scrape_q scrape_rms"
    ).split()
    d = {k: float(values[k]) for k in keys}
    base = tm.TapeMachineSpec()
    return dataclasses.replace(base, ds_m=base.ds_m * d["speed_m_s"] / base.speed_m_s, **d)


def demag_correction(
    spec,
    tape,
    red: Reduction,
    fs: float,
    ds_m: float,
    h_rms: float,
    seconds: float = 4.0,
    band_hz: float = 20e3,
) -> tuple[np.ndarray, np.ndarray]:
    """D(k): the reference stream's linear response over the reduced stream's without the
    correction, on band-limited white noise (to band_hz, deep-gap rms h_rms: low enough to be
    linear; the band sets the shortest wavelength measured, v / band_hz, D held past it), as
    a function of the wavenumber k = 2 pi f / v: its magnitude smoothed over a
    sixth of an octave, normalized to 1 at the lowest frequency, D(0) = 1. Measured with
    circuitsim's stream (the reference's port) at constant speed."""
    import json

    import circuitsim
    from scipy import signal

    rng = np.random.default_rng([1, 351])
    n = int(seconds * fs)
    b, a = signal.butter(8, band_hz, fs=fs)
    w = signal.lfilter(b, a, rng.standard_normal(n))
    h = w / np.sqrt(np.mean(w**2)) * h_rms
    v = spec.speed_m_s
    delay = int(round(spec.head_distance_m / v * fs))
    feed = np.concatenate([h, np.zeros(delay + 64)])
    params = tm.stream_params(spec, tape, red.hg_bias, head_distance_m=delay * v / fs)
    e_ref = np.asarray(circuitsim.tape_stream_run(json.dumps(params), fs, feed))
    st = ReducedStream(spec, tape, red, fs, ds_m=ds_m, head_distance_m=delay * v / fs)
    chunk = int(fs * 0.05)
    e_red = np.concatenate([st.push_many(feed[c : c + chunk]) for c in range(0, len(feed), chunk)])
    e_ref, e_red = e_ref[delay - 1 : delay - 1 + n], e_red[delay - 1 : delay - 1 + n]
    f, sxy = signal.csd(e_red, e_ref, fs=fs, nperseg=8192)
    _, sxx = signal.welch(e_red, fs=fs, nperseg=8192)
    mag = np.abs(sxy / sxx)
    keep = (f > 20) & (f < min(0.45 * fs, band_hz))
    f, mag = f[keep], mag[keep]
    sm = np.array([mag[(f >= x * 2 ** (-1 / 12)) & (f <= x * 2 ** (1 / 12))].mean() for x in f])
    return np.concatenate([[0.0], 2 * np.pi * f / v]), np.concatenate([[1.0], sm / sm[0]])


#: The medium's values a reduction is made for (a builder refuses it for any other). The
#: track's width isn't one: it scales the flux, not the recording (the 351 and the 351-2's
#: two-track heads share a reduction).
MEDIUM_KEYS = (
    "hc_median_a_m sigma_ln_hc sigma_hi_a_m h_max_a_m n_table ms_a_m coating_m kappa "
    "orientations speed_m_s f_bias_hz rec_gap_m rep_gap_m pole_m relax_m spacing_m "
    "layers ds_m table_step zone_floor_a_m local_zones demag_iterations demag_tol head_image "
    "lam_min_m"
).split()


def spec_from_medium(medium) -> tm.TapeMachineSpec:
    """The stream's spec for a circuit's tape part (its IR `TapeMedium`: the heads, the
    numerics the builder chose), at constant speed (the transport is the stream's own,
    and a reduction doesn't depend on it)."""
    return tm.TapeMachineSpec(
        speed_m_s=medium.speed_m_s,
        f_bias_hz=medium.f_bias_hz,
        rec_gap_m=medium.rec_gap_m,
        rep_gap_m=medium.rep_gap_m,
        pole_m=medium.pole_m,
        relax_m=medium.relax_m,
        track_m=medium.track_m,
        spacing_m=medium.spacing_m,
        layers=medium.layers,
        ds_m=medium.ds_m,
        table_step=medium.table_step,
        zone_floor_oe=medium.zone_floor_a_m / tm.OE_A_M,
        local_zones=medium.local_zones,
        demag_iterations=medium.demag_iterations,
        demag_tol=medium.demag_tol,
        head_image=medium.head_image,
        block_m=medium.block_m,
        margin_m=medium.margin_m,
        head_distance_m=medium.head_distance_m,
        flutter=False,
    )


def bias_hg(bias_ma_rms: float, rec_h_per_a: float) -> float:
    """The deep-gap bias peak (A/m) of a record-head bias current (mA rms)."""
    return bias_ma_rms * 1e-3 * math.sqrt(2.0) * rec_h_per_a
