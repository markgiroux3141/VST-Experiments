"""A tape machine's record / play chain around the simulated tape: the first print
(docs/TAPE_PLAN.md, "The first print", before TM5).

The tape is the medium of varimu.devices.tape: its particles (a tape component), the
record head's field with AC bias, demagnetization with the head's image, reciprocity
playback. **The electronics are idealized** until TM5 puts the Ampex 351's circuit around
it. They are the standard's networks (NAB: 3180 / 50 us) plus one HF trim each in record
and repro, aligned as the 351's manual aligns the machine (pp.79-85):

1. **Bias:** 500 Hz at 7.5 ips, a low level; raise the bias through the output's peak, go
   1/2 dB down either side and set the median (the same bias then serves 15 ips).
2. **Repro EQ:** the NAB reproducing network, its HF trim set as a test tape sets it. A
   test tape's levels are the short-circuit flux at the tape's surface (what an ideal
   reproducer reads: no gap, no spacing, poles infinitely long), so the trim makes the
   real head's reading of a recorded tone, over the ideal head's reading of the same
   pattern, as high at 10 kHz as at 1 kHz (it makes up the gap and spacing losses). The
   head bump stays (a pot can't remove it).
3. **Operating level:** 0 VU records the level that gives 1% THD at 400 Hz.
4. **Record EQ:** the NAB recording network (bass boost below 50 Hz, limited to +20 dB),
   its HF trim set so the low-level response at 10 kHz equals 1 kHz's.

**Levels:** a sine at -18 dBFS rms records at 0 VU and plays back at -18 dBFS rms (at
1 kHz, low level); `drive_db` raises the record level (the saturation control).

What the medium doesn't have yet: wow and flutter, particle noise (TM3). The heads'
geometry is provisional (TapeMachineSpec).
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np
from scipy import signal as sps

from varimu.devices.tape import (
    MU0,
    HeadGeometry,
    Slab,
    TapeFormulation,
    cubic_at,
    head_hx_spectrum,
    head_hy_spectrum,
    playback_emf,
    record_demagnetized_vector,
)

MINUS_18_DBFS_PEAK = 10 ** (-18 / 20) * math.sqrt(2.0)  # a -18 dBFS rms sine's peak


@dataclass(frozen=True)
class TapeMachineSpec:
    """The machine's mechanics and heads (sources in the field comments) and the medium's
    numerical resolution."""

    # 15 ips (Ampex 351 manual p10); 7.5 ips: 0.1905.
    speed_m_s: float = 0.381
    # "approximately 100 kc" (351 manual p78).
    f_bias_hz: float = 100e3
    # Record gap: provisional, web: ATR Master Tape sheet's test record gap 0.5 mil (the 351's
    # isn't printed); poles: provisional (a 1950s ring head's face, ~3 mm).
    rec_gap_m: float = 12.7e-6
    # Repro gap 0.00025" (351 manual p70); poles: provisional.
    rep_gap_m: float = 6.35e-6
    pole_m: float = 3e-3
    relax_m: float = 3e-3
    # Full track 0.234" (351 manual p41).
    track_m: float = 5.94e-3
    # Head-to-tape spacing: provisional, model knowledge (contact recording, ~0.1-1 um).
    spacing_m: float = 0.5e-6
    # NAB at 15 and 7.5 ips (351 manual pp.13-14).
    t1_s: float = 3180e-6
    t2_s: float = 50e-6
    # Numerical: layers, cell length, field table, zone floor, demag (TAPE_PLAN.md: each
    # moves No. 21's curves by <= 0.2 dB against finer settings).
    layers: int = 6
    ds_m: float = 1e-6
    table_step: float = 1 / 40
    floor_tol: float = 1e-5
    demag_iterations: int = 12
    demag_tol: float = 2e-3
    head_image: bool = True

    def rec_head(self) -> HeadGeometry:
        return HeadGeometry(self.rec_gap_m, self.pole_m, self.relax_m)

    def rep_head(self) -> HeadGeometry:
        return HeadGeometry(self.rep_gap_m, self.pole_m, self.relax_m)

    def at_speed(self, v: float) -> TapeMachineSpec:
        d = asdict(self)
        d["speed_m_s"] = v
        return TapeMachineSpec(**d)

    def lam_min_m(self) -> float:
        """Demagnetization acts on wavelengths above 3 bias wavelengths (the recorded bias
        pattern's own feedback doesn't converge: TAPE_PLAN.md TM2 step 2)."""
        return 3.0 * self.speed_m_s / self.f_bias_hz


@dataclass(frozen=True)
class Alignment:
    """What the alignment set (A/m are deep-gap fields; time constants in s)."""

    hg_bias: float
    hg_0vu: float  # the 0 VU sine's peak deep-gap field at 400 Hz
    rec_trim_tz_s: float
    rep_trim_tz_s: float
    out_gain: float
    trim_tp_s: float = 1.0 / (2.0 * math.pi * 30e3)
    report: dict = field(default_factory=dict)


# --- The medium as the machine uses it --------------------------------------------------


def _slab(spec: TapeMachineSpec, tape: TapeFormulation) -> Slab:
    return Slab(tape.coating_m, spec.layers, spec.ds_m, spec.spacing_m)


def _record(spec, tape, hg_signal, hg_bias, t0, t1, s_cells, hg_signal_max, bias_phase=0.0):
    slab = _slab(spec, tape)
    mx, my, _, _ = record_demagnetized_vector(
        tape.ensemble(),
        tape.ms_a_m,
        spec.rec_head(),
        slab,
        hg_signal,
        hg_bias,
        spec.f_bias_hz,
        lambda t: spec.speed_m_s * t,
        t0,
        t1,
        s_cells,
        hg_signal_max=hg_signal_max,
        orientation=tape.orientation,
        lam_min_m=spec.lam_min_m(),
        iterations=spec.demag_iterations,
        tol=spec.demag_tol,
        head_image=spec.head_image,
        engine="rust",
        table_step=spec.table_step,
        floor_tol=spec.floor_tol,
        bias_phase_rad=bias_phase,
    )
    return mx, my


# The ideal reproducer: no gap, poles a metre long, read at no spacing.
IDEAL_HEAD = HeadGeometry(1e-9, 1.0, 0.0)


def tone_harmonics(
    spec: TapeMachineSpec,
    tape: TapeFormulation,
    f_hz: float,
    hg_amp: float,
    hg_bias: float,
    harmonics: int = 3,
    waves: int = 3,
    ideal: bool = False,
):
    """A tone recorded at hg_amp (peak deep-gap field) and read by the repro head: its
    harmonics' complex EMF amplitudes (arbitrary units: i k v times the flux through the
    head), from the pattern by projection over `waves` whole wavelengths. Two more are
    recorded either side and left out: a pattern that ends next to erased tape has a
    demagnetizing field that isn't the steady tone's there, reaching about a wavelength in
    (with 3 recorded and 3 read, a level-independent 0.7% of 2nd and 3rd harmonic; with
    2 more either side, 0.05%). ideal: also as the ideal reproducer reads it (returns
    (real, ideal)), on the same scale."""
    v = spec.speed_m_s
    lam = v / f_hz
    slab = _slab(spec, tape)
    lead = 600e-6
    every = lead + np.arange(int(round((waves + 4) * lam / slab.ds_m))) * slab.ds_m
    mx, my = _record(
        spec,
        tape,
        lambda t: hg_amp * np.sin(2 * math.pi * f_hz * t),
        hg_bias,
        0.0,
        (every[-1] + lead) / v,
        every,
        hg_amp,
    )
    mid = (every >= every[0] + 2 * lam) & (every < every[0] + (2 + waves) * lam)
    s, mx, my = every[mid], mx[:, mid], my[:, mid]

    def read(head: HeadGeometry, spacing: float) -> np.ndarray:
        out = []
        for h in range(1, harmonics + 1):
            k = 2 * math.pi * h / lam
            ks = np.array([k])
            ph = np.exp(-1j * k * s)
            ax = (mx * ph).mean(axis=1) * 2
            ay = (my * ph).mean(axis=1) * 2
            wx = np.array([head_hx_spectrum(head, ks, spacing + y)[0] for y in slab.depths_m])
            wy = np.array([head_hy_spectrum(head, ks, spacing + y)[0] for y in slab.depths_m])
            # The field's spectrum carries the gap length: per unit gap, so the ideal
            # head (g -> 0) reads on the same scale. EMF ~ i k v flux, before the EQ.
            out.append(1j * k * v * ((ax * wx).sum() - (ay * wy).sum()) / head.gap_m)
        return np.array(out) * spec.rep_gap_m

    real = read(spec.rep_head(), slab.spacing_m)
    if not ideal:
        return real
    return real, read(IDEAL_HEAD, 0.0)


# --- The networks -----------------------------------------------------------------------


def _resp(b: list[float], a: list[float], f_hz: np.ndarray) -> np.ndarray:
    """An analog transfer function's response at f_hz (b, a: descending powers of s)."""
    s = 2j * math.pi * np.asarray(f_hz, float)
    return np.polyval(b, s) / np.polyval(a, s)


def rep_network(spec: TapeMachineSpec, al_tz: float, tp: float):
    """NAB reproducing T1 (1 + s T2) / (1 + s T1), times the HF trim (1 + s tz) / (1 + s tp)."""
    b = np.polymul([spec.t1_s * spec.t2_s, spec.t1_s], [al_tz, 1.0])
    a = np.polymul([spec.t1_s, 1.0], [tp, 1.0])
    return list(b), list(a)


def rec_network(spec: TapeMachineSpec, al_tz: float, tp: float):
    """NAB recording bass boost (1 + s T1) / (0.1 + s T1) (+20 dB at most), times the HF
    trim (1 + s tz) / (1 + s tp)."""
    b = np.polymul([spec.t1_s, 1.0], [al_tz, 1.0])
    a = np.polymul([spec.t1_s, 0.1], [tp, 1.0])
    return list(b), list(a)


def _filter(b, a, x: np.ndarray, fs: float) -> np.ndarray:
    bz, az = sps.bilinear(b, a, fs)
    return sps.lfilter(bz, az, x)


# --- Alignment --------------------------------------------------------------------------


def _trim_tz(gain: float, f_hz: float, tp: float) -> float:
    """The trim's zero for |(1 + j w tz) / (1 + j w tp)| = gain at f_hz (gain >= 1 boosts)."""
    w = 2 * math.pi * f_hz
    target = gain * abs(1 + 1j * w * tp)
    return math.sqrt(max(target**2 - 1.0, 0.0)) / w


def align(spec: TapeMachineSpec, tape: TapeFormulation) -> Alignment:
    """The machine aligned on its tape (see the module docs). Takes a minute or two."""
    hc = tape.preisach.hc_median_a_m
    low = 0.05 * hc
    tp = Alignment.__dataclass_fields__["trim_tp_s"].default
    # 1. Bias: 500 Hz at 7.5 ips.
    slow = spec.at_speed(0.1905)
    biases = np.geomspace(0.6 * hc, 5.0 * hc, 24)
    out = np.array([abs(tone_harmonics(slow, tape, 500.0, low, b, harmonics=1)[0]) for b in biases])
    db = 20 * np.log10(out / out.max())
    lb = np.log(biases)
    i = int(np.argmax(db))
    if i in (0, len(db) - 1):
        raise RuntimeError("the 500 Hz output doesn't peak within the bias sweep")
    fine = np.linspace(lb[0], lb[-1], 4000)
    dfine = np.interp(fine, lb, db)
    pk = int(np.argmax(dfine))
    lo_i = pk - int(np.argmax(dfine[:pk][::-1] < -0.5))
    hi_i = pk + int(np.argmax(dfine[pk:] < -0.5))
    hg_bias = 0.5 * (math.exp(fine[lo_i]) + math.exp(fine[hi_i]))
    # 2. Repro EQ as a test tape sets it: the real head's reading over the ideal one's, as
    # high at 10 kHz as at 1 kHz.
    loss = []
    for f in (1e3, 10e3):
        real, ideal = tone_harmonics(spec, tape, f, low, hg_bias, harmonics=1, ideal=True)
        loss.append(abs(real[0] / ideal[0]))
    rep_tz = _trim_tz(loss[0] / loss[1], 10e3, tp)
    rb, ra = rep_network(spec, rep_tz, tp)
    # 3. Operating level: 1% THD at 400 Hz. The harmonics as the output shows them: each
    # over the low-level (linear) response at its own frequency.
    f0 = 400.0
    lin = np.array(
        [
            abs(tone_harmonics(spec, tape, n * f0, low, hg_bias, harmonics=1)[0]) / low
            for n in (1, 2, 3)
        ]
    )

    def thd(a: float) -> float:
        h = np.abs(tone_harmonics(spec, tape, f0, a, hg_bias, harmonics=3)) / lin
        return float(np.hypot(h[1], h[2]) / h[0])

    lo_a, hi_a = 0.05 * hc, 6.0 * hc
    if thd(hi_a) < 0.01 or thd(lo_a) > 0.01:
        raise RuntimeError("1% THD at 400 Hz isn't bracketed by the level search")
    for _ in range(14):
        mid = math.sqrt(lo_a * hi_a)
        lo_a, hi_a = (mid, hi_a) if thd(mid) < 0.01 else (lo_a, mid)
    hg_0vu = math.sqrt(lo_a * hi_a)
    # 4. Record EQ: the low-level response at 10 kHz equal to 1 kHz's (record trim off).
    cb, ca = rec_network(spec, 0.0, tp)
    g = []
    for f in (1e3, 10e3):
        h1 = tone_harmonics(spec, tape, f, low, hg_bias, harmonics=1)[0]
        g.append(abs(h1 * _resp(cb, ca, np.array([f]))[0] * _resp(rb, ra, np.array([f]))[0]))
    rec_tz = _trim_tz(g[0] / g[1], 10e3, tp)
    rcb, rca = rec_network(spec, rec_tz, tp)
    # Output gain: a 0 VU sine at 1 kHz (low-level response, scaled) plays at -18 dBFS rms.
    h1k = tone_harmonics(spec, tape, 1e3, low, hg_bias, harmonics=1)[0]
    chain = abs(h1k * _resp(rcb, rca, np.array([1e3]))[0] * _resp(rb, ra, np.array([1e3]))[0])
    out_gain = MINUS_18_DBFS_PEAK / (chain * hg_0vu / low)
    report = {
        "bias_sweep_hg_a_m": [float(b) for b in biases],
        "bias_sweep_db_500hz_7ips": [float(d) for d in db],
        "hg_bias_over_hc": hg_bias / hc,
        "hg_0vu_over_hc": hg_0vu / hc,
        "rep_trim_db_at_10k": 20 * math.log10(loss[0] / loss[1]),
        "thd_at_0vu_400hz": thd(hg_0vu),
        "rec_trim_db_at_10k": 20 * math.log10(g[0] / g[1]),
    }
    return Alignment(hg_bias, hg_0vu, rec_tz, rep_tz, out_gain, report=report)


def aligned(spec: TapeMachineSpec, tape: TapeFormulation, cache_dir: Path) -> Alignment:
    """`align`, cached by the spec and the tape's data."""
    key = hashlib.sha256(
        json.dumps([asdict(spec), repr(tape)], sort_keys=True, default=str).encode()
    ).hexdigest()[:16]
    path = cache_dir / f"align_{key}.json"
    if path.exists():
        d = json.loads(path.read_text())
        return Alignment(**d)
    al = align(spec, tape)
    cache_dir.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(al), indent=1))
    return al


# --- The print --------------------------------------------------------------------------


def print_audio(
    x: np.ndarray,
    fs: float,
    spec: TapeMachineSpec,
    tape: TapeFormulation,
    al: Alignment,
    drive_db: float = 0.0,
    block_s: float = 0.5,
    progress=None,
) -> np.ndarray:
    """Audio (full scale 1.0, mono) recorded on the tape and played back (see the module
    docs). Blockwise along the tape: each block recorded with margins (demagnetization's
    neighbours), played once its neighbours are recorded (the repro head's reach)."""
    v = spec.speed_m_s
    slab = _slab(spec, tape)
    tp = al.trim_tp_s
    gain = al.hg_0vu / MINUS_18_DBFS_PEAK * 10 ** (drive_db / 20)
    rb_, ra_ = rec_network(spec, al.rec_trim_tz_s, tp)
    y = gain * _filter(rb_, ra_, np.asarray(x, float), fs)
    pad = 8
    yp = np.concatenate([np.zeros(pad), y, np.zeros(pad)])

    def hg_signal(t):
        return cubic_at(yp, np.asarray(t) * fs + pad)

    hg_max = float(np.abs(y).max()) + 1e-9
    n_out = len(x)
    t_end = n_out / fs
    s_end = v * t_end
    reach = 2.0 * (spec.rep_gap_m / 2 + spec.pole_m + spec.relax_m)
    margin = 0.5e-3
    block = max(int(block_s * v / slab.ds_m), 1000)
    cells_total = int(math.ceil(s_end / slab.ds_m)) + 1
    s_all = lambda i0, i1: np.arange(i0, i1) * slab.ds_m  # noqa: E731
    k_max = 2 * math.pi * 0.45 * fs / v  # no wavelength shorter than 0.45 fs plays
    out = np.zeros(n_out)
    t_out = np.arange(n_out) / fs
    recorded: dict[int, tuple[np.ndarray, np.ndarray]] = {}
    n_blocks = int(math.ceil(cells_total / block))
    zone_t = 2e-3 / v  # well past the record zone, in time

    def record_block(b: int):
        i0, i1 = b * block, min((b + 1) * block, cells_total)
        m = int(margin / slab.ds_m)
        j0, j1 = max(i0 - m, 0), min(i1 + m, cells_total)
        s = s_all(j0, j1)
        # Every cell passes the whole head, also those at the clip's ends: the tape runs
        # (recording silence) before the clip and after it. Stopping with cells inside
        # the zone leaves them as the bias's last peak left them: a spike on playback.
        t0 = s[0] / v - zone_t
        t1 = s[-1] / v + zone_t
        mx, my = _record(spec, tape, hg_signal, al.hg_bias, t0, t1, s, hg_max)
        recorded[b] = (
            mx[:, i0 - j0 : i1 - j0].astype(np.float32),
            my[:, i0 - j0 : i1 - j0].astype(np.float32),
        )

    def play_block(b: int):
        i0, i1 = b * block, min((b + 1) * block, cells_total)
        r = int(reach / slab.ds_m)
        parts = [recorded[c] for c in (b - 1, b, b + 1) if c in recorded]
        first = (b - 1) * block if (b - 1) in recorded else i0
        mx = np.concatenate([p[0] for p in parts], axis=1).astype(float)
        my = np.concatenate([p[1] for p in parts], axis=1).astype(float)
        # Output samples whose read position falls in this block.
        sel = (t_out * v >= i0 * slab.ds_m) & (t_out * v < i1 * slab.ds_m)
        if not sel.any():
            return
        lo = max(i0 - r, first) - first
        hi = min(i1 + r, first + mx.shape[1]) - first
        s0 = (first + lo) * slab.ds_m
        emf = playback_emf(
            mx[:, lo:hi],
            s0,
            slab,
            spec.rep_head(),
            1.0,
            spec.track_m,
            tape.ms_a_m,
            t_out[sel] * v,
            np.full(int(sel.sum()), v),
            k_max,
            my[:, lo:hi],
        )
        out[sel] = emf

    for b in range(n_blocks):
        record_block(b)
        if b >= 1:
            play_block(b - 1)
            recorded.pop(b - 2, None)
        if progress:
            progress((b + 1) / n_blocks)
    play_block(n_blocks - 1)
    rb, ra = rep_network(spec, al.rep_trim_tz_s, tp)
    # playback_emf's volts are tone_harmonics' units times mu0 W Ms dy (h_per_a = 1).
    volts_per_unit = MU0 * spec.track_m * tape.ms_a_m * (tape.coating_m / spec.layers)
    return al.out_gain / volts_per_unit * _filter(rb, ra, out, fs)
