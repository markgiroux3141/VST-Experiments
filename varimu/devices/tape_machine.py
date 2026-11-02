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
    flux_slope,
    head_hx_spectrum,
    head_hy_spectrum,
    record_demagnetized_vector,
)

MINUS_18_DBFS_PEAK = 10 ** (-18 / 20) * math.sqrt(2.0)  # a -18 dBFS rms sine's peak
OE_A_M = 1000.0 / (4.0 * math.pi)  # one oersted in A/m


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
    # Numerical: layers, cell length, field table, demag (TAPE_PLAN.md: each moves No. 21's
    # curves by <= 0.2 dB against finer settings). The zone's floor (Oe; None: the grid's
    # `switching_floor`, 31 Oe) and per-cell zones (`record`'s local_zones): a print moves
    # by -75 dB against 31 Oe and global zones, 2.6x faster (TAPE_PLAN.md, "Speed").
    # The cell length: 7.62 per bias wavelength (0.5 um at 15 ips; `at_speed` keeps the
    # ratio). Cells are point samples of the pattern, and the bias leaves a residue at its
    # wavelength and harmonics: at 1 um its harmonics aliased into the audio band (a 9.5 kHz
    # line at -59 dB re the 3% level at 7.5 ips, 19 kHz at -75 dB at 15 ips); at this ratio
    # none lands in band, and it isn't whole (whole ratios alias them to DC: TAPE_PLAN.md,
    # TM3).
    layers: int = 6
    ds_m: float = 0.5e-6
    table_step: float = 1 / 40
    zone_floor_oe: float | None = 120.0
    local_zones: bool = True
    demag_iterations: int = 12
    demag_tol: float = 2e-3
    head_image: bool = True
    # The stream (`TapeStream`): tape is recorded in blocks this long, each with this
    # margin of neighbours either side (block length moves a print by -63 dB from 0.5 s
    # blocks: TAPE_PLAN.md, TM4); the repro gap sits this far behind the record gap
    # (provisional, secondary sources: ~2" on the 350/351 headblock, ~133 ms at 15 ips).
    block_m: float = 16e-3
    margin_m: float = 0.5e-3
    head_distance_m: float = 50.8e-3
    # The transport (wow and flutter, TAPE_PLAN.md TM3): v(t) = v (1 + eps(t)), eps from
    # mechanisms at their own rates. Scaled so that a 3150 Hz tone recorded and played back
    # deviates 0.11% rms over 0.5-250 Hz, the 351's spec at 15 ips (1962 manual p10, ASA
    # Z57.1-1954: a playback measurement; scripts/tape_flutter.py), the speed itself 0.08%;
    # the split among them is provisional (model knowledge: nothing printed separates them).
    flutter: bool = True
    # The capstan is the hysteresis synchronous motor's shaft (manual p51-52): 15 ips at
    # 1800 rpm (60 Hz, four poles) makes it 4.04 mm; provisional (the diameter isn't
    # printed). Its runout turns once per revolution.
    capstan_d_m: float = 4.04e-3
    capstan_rms: float = 3.7e-4
    # The rubber capstan idler: provisional, model knowledge (~1.25 in).
    roller_d_m: float = 31.8e-3
    roller_rms: float = 2.9e-4
    # The supply reel at mid pack: provisional, model knowledge (a 10.5 in NAB reel, ~80 mm).
    reel_r_m: float = 80e-3
    reel_rms: float = 4.4e-4
    # The motor's rotor hunting around synchronism, a lightly damped resonance driven by
    # load changes: provisional, model knowledge.
    hunting_hz: float = 2.5
    hunting_q: float = 3.0
    hunting_rms: float = 4.8e-4
    # Scrape flutter (Sound Talk No. 34, Fig. 1): the free span's first longitudinal mode,
    # c / 2L, excited by friction over the heads; c = sqrt(E / rho) of acetate (~3.4 GPa,
    # 1290 kg/m^3), a ~0.2 m span: provisional, model knowledge. Above the spec's band.
    scrape_span_m: float = 0.2
    scrape_c_m_s: float = 1623.0
    scrape_q: float = 10.0
    scrape_rms: float = 3e-4

    def transport(self) -> tuple[tuple, tuple]:
        """The speed's components: (periodic (relative peak, Hz, phase), random resonances
        (relative rms, Hz, Q)); none without flutter."""
        if not self.flutter:
            return (), ()
        v = self.speed_m_s
        periodic = (
            (self.capstan_rms * math.sqrt(2.0), v / (math.pi * self.capstan_d_m), 0.0),
            (self.roller_rms * math.sqrt(2.0), v / (math.pi * self.roller_d_m), 1.0),
            (self.reel_rms * math.sqrt(2.0), v / (2.0 * math.pi * self.reel_r_m), 2.0),
        )
        random = (
            (self.hunting_rms, self.hunting_hz, self.hunting_q),
            (self.scrape_rms, self.scrape_c_m_s / (2.0 * self.scrape_span_m), self.scrape_q),
        )
        return periodic, random

    def rec_head(self) -> HeadGeometry:
        return HeadGeometry(self.rec_gap_m, self.pole_m, self.relax_m)

    def rep_head(self) -> HeadGeometry:
        return HeadGeometry(self.rep_gap_m, self.pole_m, self.relax_m)

    def at_speed(self, v: float) -> TapeMachineSpec:
        """The spec at speed v, its cells scaled with it (the same cells per bias
        wavelength)."""
        d = asdict(self)
        d["ds_m"] = self.ds_m * v / self.speed_m_s
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


def _record(
    spec,
    tape,
    hg_signal,
    hg_bias,
    t0,
    t1,
    s_cells,
    hg_signal_max,
    bias_phase=0.0,
    engine="rust",
    s_rec=None,
    peaks=None,
):
    slab = _slab(spec, tape)
    if s_rec is None:

        def s_rec(t):
            return spec.speed_m_s * t

    mx, my, _, _ = record_demagnetized_vector(
        tape.ensemble(),
        tape.ms_a_m,
        spec.rec_head(),
        slab,
        hg_signal,
        hg_bias,
        spec.f_bias_hz,
        s_rec,
        t0,
        t1,
        s_cells,
        hg_signal_max=hg_signal_max,
        orientation=tape.orientation,
        lam_min_m=spec.lam_min_m(),
        iterations=spec.demag_iterations,
        tol=spec.demag_tol,
        head_image=spec.head_image,
        engine=engine,
        table_step=spec.table_step,
        floor_a_m=None if spec.zone_floor_oe is None else spec.zone_floor_oe * OE_A_M,
        local_zones=spec.local_zones,
        bias_phase_rad=bias_phase,
        peaks=peaks,
    )
    return mx, my


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

    def read(head: HeadGeometry | None, spacing: float) -> np.ndarray:
        out = []
        for h in range(1, harmonics + 1):
            k = 2 * math.pi * h / lam
            ks = np.array([k])
            ph = np.exp(-1j * k * s)
            ax = (mx * ph).mean(axis=1) * 2
            ay = (my * ph).mean(axis=1) * 2
            if head is None:
                # The ideal reproducer: the gap's term alone, per unit gap (no gap loss, no
                # pole edges), at no spacing.
                wx = np.exp(-k * (spacing + slab.depths_m))
                wy = 1j * wx
            else:
                wx = np.array([head_hx_spectrum(head, ks, spacing + y)[0] for y in slab.depths_m])
                wy = np.array([head_hy_spectrum(head, ks, spacing + y)[0] for y in slab.depths_m])
                # The field's spectrum carries the gap length: per unit gap, as the ideal
                # head's. EMF ~ i k v flux, before the EQ.
                wx, wy = wx / head.gap_m, wy / head.gap_m
            out.append(1j * k * v * ((ax * wx).sum() - (ay * wy).sum()))
        return np.array(out) * spec.rep_gap_m

    real = read(spec.rep_head(), slab.spacing_m)
    if not ideal:
        return real
    return real, read(None, 0.0)


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


#: Bumped when `align`'s procedure changes (2: the ideal reproducer as the gap's term
#: alone; before, a vanishing gap between finite poles read its pole edges, so the repro
#: trim was set from a reading off by up to +30 dB: TAPE_PLAN.md TM5).
ALIGN_VERSION = 2


def aligned(spec: TapeMachineSpec, tape: TapeFormulation, cache_dir: Path) -> Alignment:
    """`align`, cached by the spec, the tape's data and ALIGN_VERSION."""
    key = hashlib.sha256(
        json.dumps([asdict(spec), repr(tape), ALIGN_VERSION], sort_keys=True, default=str).encode()
    ).hexdigest()[:16]
    path = cache_dir / f"align_{key}.json"
    if path.exists():
        d = json.loads(path.read_text())
        return Alignment(**d)
    al = align(spec, tape)
    cache_dir.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(al), indent=1))
    return al


# --- The stream ------------------------------------------------------------------------

#: Recording runs this much tape past a block's ends: well past the record zone.
ZONE_PAD_M = 2e-3

#: Newton steps of `refine_extremum` (fixed, so both languages take the same ones).
EXTREMUM_NEWTON_STEPS = 3


def parabola_extremum(a: float, b: float, c: float) -> tuple[float, float]:
    """The extremum of the parabola through (-1, a), (0, b), (1, c): (offset, value)."""
    den = a - 2.0 * b + c
    d = 0.0 if den == 0.0 else 0.5 * (a - c) / den
    return d, b - 0.25 * (a - c) * d


def refine_extremum(y0: float, y1: float, y2: float, y3: float, y4: float) -> tuple[float, float]:
    """The extremum of the quartic through five equally spaced samples (at -2 .. 2, the
    middle one a local extremum): (offset, value). Newton on its derivative from the
    parabola's offset, EXTREMUM_NEWTON_STEPS steps, the offset kept within +-1.

    The literal bias's peaks set every recorded cell's bias. The parabola's value error
    grows as (w h)^4 for a sinusoid sampled h apart, and it depends on where the samples
    fall on the peak, so it beats against the oscillator: at 10 substeps (~20.7 samples per
    92.9 kHz period) a line at -78.6 dBFS in the 351's noise, the whole of its S/N miss
    (TAPE_PLAN.md "Gaps" 4, scripts/tape_snr_study.py). The quartic's is its interpolation
    error, ~(w h)^6: 4e-6 of the carrier at 20.7 samples per period against the parabola's
    2e-4 (tests/test_tape_stream.py). Newton converges in one step."""
    c1 = (y0 - 8.0 * y1 + 8.0 * y3 - y4) / 12.0
    c2 = (-y0 + 16.0 * y1 - 30.0 * y2 + 16.0 * y3 - y4) / 24.0
    c3 = (-y0 + 2.0 * y1 - 2.0 * y3 + y4) / 12.0
    c4 = (y0 - 4.0 * y1 + 6.0 * y2 - 4.0 * y3 + y4) / 24.0
    u, _ = parabola_extremum(y1, y2, y3)
    for _ in range(EXTREMUM_NEWTON_STEPS):
        g = c1 + u * (2.0 * c2 + u * (3.0 * c3 + u * 4.0 * c4))
        gp = 2.0 * c2 + u * (6.0 * c3 + u * 12.0 * c4)
        if gp == 0.0:
            break
        u = min(max(u - g / gp, -1.0), 1.0)
    return u, y2 + u * (c1 + u * (c2 + u * (c3 + u * c4)))


def cubic_held(h: np.ndarray, u, first: int = 0) -> np.ndarray:
    """`cubic_at` on samples h (sample i at index first + i) at fractional indices u, the
    taps clamped to the samples there are (the first held before them)."""
    u = np.asarray(u, float)
    i = np.floor(u).astype(np.int64)
    f = u - i
    n = len(h)

    def tap(k):
        return h[np.clip(k - first, 0, n - 1)]

    return (
        -f * (f - 1) * (f - 2) / 6.0 * tap(i - 1)
        + (f + 1) * (f - 1) * (f - 2) / 2.0 * tap(i)
        - (f + 1) * f * (f - 2) / 2.0 * tap(i + 1)
        + (f + 1) * f * (f - 1) / 6.0 * tap(i + 2)
    )


def stream_params(
    spec: TapeMachineSpec,
    tape: TapeFormulation,
    hg_bias: float,
    rep_h_per_a: float = 1.0,
    bias_phase: float = 0.0,
    head_distance_m: float | None = None,
) -> dict:
    """`TapeStream`'s parameters as circuitsim's `TapeParams` takes them (the stream's
    port and the IR element `Tape`). The spec's zone floor must be set."""
    if spec.zone_floor_oe is None:
        raise ValueError("a stream needs an explicit zone floor (spec.zone_floor_oe)")
    p, o, nz = tape.preisach, tape.orientation, tape.noise
    return {
        "hc_median_a_m": p.hc_median_a_m,
        "sigma_ln_hc": p.sigma_ln_hc,
        "sigma_hi_a_m": p.sigma_hi_a_m,
        "h_max_a_m": p.h_max_a_m,
        "n_table": p.n_table,
        "ms_a_m": tape.ms_a_m,
        "coating_m": tape.coating_m,
        "kappa": o.kappa,
        "orientations": o.n,
        "speed_m_s": spec.speed_m_s,
        "f_bias_hz": spec.f_bias_hz,
        "hg_bias_a_m": float(hg_bias),
        "bias_phase_rad": float(bias_phase),
        "rec_gap_m": spec.rec_gap_m,
        "rep_gap_m": spec.rep_gap_m,
        "pole_m": spec.pole_m,
        "relax_m": spec.relax_m,
        "spacing_m": spec.spacing_m,
        "track_m": spec.track_m,
        "head_distance_m": spec.head_distance_m if head_distance_m is None else head_distance_m,
        "rep_h_per_a": float(rep_h_per_a),
        "layers": spec.layers,
        "ds_m": spec.ds_m,
        "table_step": spec.table_step,
        "zone_floor_a_m": spec.zone_floor_oe * OE_A_M,
        "local_zones": spec.local_zones,
        "demag_iterations": spec.demag_iterations,
        "demag_tol": spec.demag_tol,
        "head_image": spec.head_image,
        "lam_min_m": spec.lam_min_m(),
        "block_m": spec.block_m,
        "margin_m": spec.margin_m,
        "flutter": [list(c) for c in spec.transport()[0]],
        "flutter_noise": [list(c) for c in spec.transport()[1]],
        "particle_volume_m3": nz.particle_volume_m3 if nz else 0.0,
        "packing": nz.packing if nz else 0.0,
        "packing_sigma": nz.packing_sigma if nz else 0.0,
        "packing_corr_m": nz.packing_corr_m if nz else 0.0,
    }


class TapeStream:
    """The tape between the heads, sample by sample (TM4; circuitsim's `tape_stream` is
    the port and the IR element `Tape` runs it). `push(h)` takes the record gap's signal
    field at t_n = n / fs (deep-gap A/m; the bias, hg_bias at the spec's f_bias_hz, is
    added inside) and returns the repro coil's EMF at t_{n+1} (V): the tape played back
    was recorded long before, so the medium never waits on the circuit.

    Tape position s = v t is at the record gap at time t; the repro gap reads s minus the
    head distance (the spec's head_distance_m). Cells are recorded in blocks of block_m
    (`record_demagnetized_vector` over the block and margin_m either side, erased beyond)
    once the record head is ZONE_PAD_M past the block's margin, and a block's flux slope
    (`flux_slope` over the block and the repro head's reach either side, erased where
    nothing is recorded) once the next block is recorded. Between samples the signal is
    cubic (`cubic_held`); each block's zone bound is the largest |sample| its recording
    reads. The EMF is read cubic between cells, band limited at 0.45 fs. rep_h_per_a: the
    repro head's deep-gap field per coil ampere (turns and efficiency over the gap).

    literal (M): the bias is the circuit's (TAPE_PLAN.md, TM5's option A): each push is M
    samples of the head's whole deep-gap field, bias included, and hg_bias isn't added
    (pass 0). Push n carries the field over (t_{n-2}, t_{n-1}] (fast sample k at
    t = (k + 1 - 2M) / (M fs)): a multi-rate part's samples reach the medium a sample
    after they're computed (circuitsim's partition.rs; the first two pushes are the DC
    point's). It returns the EMF at t_{n+1} as before. A block records at the field's
    extrema (`literal_peaks`)."""

    def __init__(
        self,
        spec: TapeMachineSpec,
        tape: TapeFormulation,
        hg_bias: float,
        fs: float,
        rep_h_per_a: float = 1.0,
        bias_phase: float = 0.0,
        engine: str = "rust",
        head_distance_m: float | None = None,
        noise_seed: int | None = None,
        noise_name: str = "tape",
        transport_seed: int = 0,
        literal: int | None = None,
    ):
        if literal is not None and (literal < 2 or hg_bias != 0.0):
            raise ValueError("literal bias: M >= 2 samples per push, and hg_bias 0")
        self.literal = literal
        if noise_seed is not None and tape.noise is None:
            raise ValueError(f"{tape.name} has no noise block (its particles aren't fitted)")
        if noise_seed is not None and not 0 <= noise_seed < 2**53:
            raise ValueError(f"noise seed {noise_seed}: 0 .. 2^53")
        self.noise_seed, self.noise_name = noise_seed, noise_name
        if spec.zone_floor_oe is None:
            raise ValueError("a stream needs an explicit zone floor (spec.zone_floor_oe)")
        self.spec, self.tape, self.hg_bias, self.fs = spec, tape, float(hg_bias), float(fs)
        self.bias_phase, self.engine = bias_phase, engine
        self.slab = _slab(spec, tape)
        v, ds = spec.speed_m_s, self.slab.ds_m
        self.v = v
        self.d = spec.head_distance_m if head_distance_m is None else head_distance_m
        self.nb = int(round(spec.block_m / ds))
        self.nm = int(round(spec.margin_m / ds))
        reach = 2.0 * (spec.rep_gap_m / 2.0 + spec.pole_m + spec.relax_m)
        self.nr = int(math.ceil(reach / ds))
        if self.nr > self.nb:
            raise ValueError(f"the repro head's reach ({reach:.3g} m) is longer than a block")
        lag = (2 * self.nb + self.nm) * ds + ZONE_PAD_M + 4.0 * v / self.fs
        if self.d <= lag:
            raise ValueError(
                f"the heads are too close for the blocks ({self.d:.3g} <= {lag:.3g} m)"
            )
        self.k_max = 2.0 * math.pi * 0.45 * self.fs / v
        dy = tape.coating_m / spec.layers
        self.scale = MU0 * spec.track_m * tape.ms_a_m * rep_h_per_a * dy
        self.h = np.zeros(0)  # samples first, first + 1, ... (literal: the fast samples)
        self.first = 0
        self.n = 0  # samples pushed
        self.rec: dict[int, tuple[np.ndarray, np.ndarray]] = {}
        self.slopes: dict[int, np.ndarray] = {}
        self.next_rec = 0
        # The transport: with flutter, the tape's position at the record gap per sample
        # (s[k] at sample s_first + k, one sample ahead of the pushes), integrated
        # (trapezoids) from v (1 + eps); before t = 0 the tape ran at v.
        self.periodic, self.resonances = spec.transport()
        self.moving = bool(self.periodic or self.resonances)
        self.transport_seed = transport_seed
        if self.moving:
            self.zi = [np.zeros(2) for _ in self.resonances]
            self.s = np.zeros(1)
            self.s_first = 0
            self.v_last = self._speeds(0, 1)[0]

    def _span(self, b: int) -> tuple[int, int, float, float | None]:
        """Block b's recorded cells [j0, j1) and its recording's time span (its end None
        while the tape hasn't got there): the times the record gap is ZONE_PAD_M before
        the first cell and after the last."""
        ds, v = self.slab.ds_m, self.v
        j0 = max(b * self.nb - self.nm, 0)
        j1 = (b + 1) * self.nb + self.nm
        if not self.moving:
            return j0, j1, j0 * ds / v - ZONE_PAD_M / v, (j1 - 1) * ds / v + ZONE_PAD_M / v
        return (
            j0,
            j1,
            self._time_at(j0 * ds - ZONE_PAD_M, True),
            self._time_at((j1 - 1) * ds + ZONE_PAD_M, False),
        )

    def _speeds(self, k0: int, k1: int) -> np.ndarray:
        """v (1 + eps) at samples k0 .. k1 (in turn: the resonances' filters run on)."""
        from scipy.signal import lfilter

        from varimu.devices import noise

        t = np.arange(k0, k1) / self.fs
        eps = np.zeros(k1 - k0)
        for a, f, ph in self.periodic:
            eps = eps + a * np.cos(2.0 * math.pi * f * t + ph)
        for i, (rms, f, q) in enumerate(self.resonances):
            # A resonance at f, Q q driven by white noise, scaled to rms.
            r = math.exp(-math.pi * f / (q * self.fs))
            a1, a2 = -2.0 * r * math.cos(2.0 * math.pi * f / self.fs), r * r
            var = (1.0 + a2) / ((1.0 - a2) * ((1.0 + a2) ** 2 - a1 * a1))
            x = noise.normals(noise.key(self.transport_seed, "transport", i), k0, k1 - k0)
            y, self.zi[i] = lfilter(
                [rms / math.sqrt(var), 0.0, 0.0], [1.0, a1, a2], x, zi=self.zi[i]
            )
            eps = eps + y
        return self.v * (1.0 + eps)

    def _advance(self, k: int) -> None:
        """The tape's position through sample k."""
        last = self.s_first + len(self.s) - 1
        if k <= last:
            return
        v = self._speeds(last + 1, k + 1)
        inc = (np.concatenate([[self.v_last], v[:-1]]) + v) * (0.5 / self.fs)
        self.s = np.concatenate([self.s, np.concatenate([[self.s[-1]], inc]).cumsum()[1:]])
        self.v_last = float(v[-1])

    def _s_at(self, t) -> np.ndarray:
        """The tape's position at the record gap at times t (cubic between samples)."""
        if not self.moving:
            return self.v * np.asarray(t)
        u = np.asarray(t, float) * self.fs
        i = np.floor(u).astype(np.int64)
        f = u - i
        last = self.s_first + len(self.s) - 1

        def tap(k):
            known = self.s[np.clip(k - self.s_first, 0, len(self.s) - 1)]
            return np.where(k < 0, self.v * k / self.fs, np.where(k > last, known, known))

        return (
            -f * (f - 1) * (f - 2) / 6.0 * tap(i - 1)
            + (f + 1) * (f - 1) * (f - 2) / 2.0 * tap(i)
            - (f + 1) * f * (f - 2) / 2.0 * tap(i + 1)
            + (f + 1) * f * (f - 1) / 6.0 * tap(i + 2)
        )

    def _time_at(self, sv: float, start: bool) -> float | None:
        """A sample time at or before (start) / at or after the tape's position sv (None:
        not yet there)."""
        if sv < 0:
            return sv / self.v
        k = int(np.searchsorted(self.s, sv, side="left"))
        if k >= len(self.s):
            return None
        k += self.s_first
        return (k - 1) / self.fs if start else k / self.fs

    def literal_peaks(self, t0: float, t1: float) -> tuple[np.ndarray, np.ndarray]:
        """The literal field's extrema with t0 <= t <= t1: each sample above its left
        neighbour and not below its right (a maximum) or the reverse, refined by
        `refine_extremum` over the five samples around it (the parabola through three
        where the buffer's newest edge has no second neighbour); the same arithmetic as
        circuitsim's port."""
        m, fs = self.literal, self.fs
        h, first = self.h, self.first
        mf = m * fs
        kl = max(math.floor(t0 * mf + 2 * m - 1) - 1, first + 1)
        kh = min(math.floor(t1 * mf + 2 * m - 1) + 2, first + len(h) - 2)
        ts, vs = [], []
        for k in range(kl, kh + 1):
            i = k - first
            a, b, c = h[i - 1], h[i], h[i + 1]
            if not ((b > a and b >= c) or (b < a and b <= c)):
                continue
            if i >= 2 and i + 2 < len(h):
                d, v = refine_extremum(h[i - 2], a, b, c, h[i + 2])
            else:
                d, v = parabola_extremum(a, b, c)
            tk = (k + d + 1 - 2 * m) / mf
            if t0 <= tk <= t1:
                ts.append(tk)
                vs.append(v)
        return np.array(ts), np.array(vs)

    def _record_block(self, b: int) -> None:
        j0, j1, t0, t1 = self._span(b)
        fs = self.fs
        s = np.arange(j0, j1) * self.slab.ds_m
        if self.literal is not None:
            tp, hp = self.literal_peaks(t0, t1)
            peak = float(np.abs(hp).max()) if len(hp) else 0.0
            mx, my = _record(
                self.spec,
                self.tape,
                None,
                0.0,
                t0,
                t1,
                s,
                peak,
                0.0,
                self.engine,
                self._s_at,
                peaks=(tp, hp),
            )
        else:
            lo = max(math.floor(t0 * fs) - 1, 0)
            hi = math.floor(t1 * fs) + 3
            h, first = self.h, self.first
            peak = float(np.abs(h[lo - first : hi - first]).max())
            mx, my = _record(
                self.spec,
                self.tape,
                lambda t: cubic_held(h, np.asarray(t) * fs, first),
                self.hg_bias,
                t0,
                t1,
                s,
                peak,
                self.bias_phase,
                self.engine,
                self._s_at,
            )
        i0 = b * self.nb
        mx = mx[:, i0 - j0 : i0 - j0 + self.nb].copy()
        my = my[:, i0 - j0 : i0 - j0 + self.nb].copy()
        if self.noise_seed is not None:
            self._grain(mx, my, i0)
        self.rec[b] = (mx, my)

    def _grain(self, mx: np.ndarray, my: np.ndarray, i0: int) -> None:
        """The coating's grain on the block's cells from i0 (`TapeNoise`), in place: each
        cell's magnetization times 1 + the packing field, plus the Poisson particle noise
        (variance sum_j w_j (cos^2, sin^2) phi_j / N for N particles per cell). The packing
        field is one for the coating's depth, exponentially correlated along the tape (an
        AR(1) from cell to cell, std packing_sigma, its state carried from block to
        block). Philox streams (`noise.key(seed, noise_name, stream)`), indexed by cell:
        stream 0 the packing field's (cell i at i + 1, its start at 0), 1 + layer the
        particles' (two per cell)."""
        from scipy.signal import lfilter

        from varimu.devices import noise

        nz, nb = self.tape.noise, self.nb
        ds, dy = self.slab.ds_m, self.tape.coating_m / self.spec.layers
        n_cell = nz.packing * ds * dy * self.spec.track_m / nz.particle_volume_m3
        cs, sn, wt = self.tape.orientation.axes()
        sx = math.sqrt(float(np.sum(wt * cs * cs)) / n_cell)
        sy = math.sqrt(float(np.sum(wt * sn * sn)) / n_cell)
        d = np.zeros(nb)
        if nz.packing_sigma > 0:
            rho = math.exp(-ds / nz.packing_corr_m)
            k = noise.key(self.noise_seed, self.noise_name, 0)
            if i0 == 0:
                self._packing_prev = float(noise.normals(k, 0, 1)[0])
            xi = noise.normals(k, i0 + 1, nb)
            d, _ = lfilter(
                [math.sqrt(1.0 - rho * rho)], [1.0, -rho], xi, zi=[rho * self._packing_prev]
            )
            self._packing_prev = float(d[-1])
            d = nz.packing_sigma * d
        for li in range(self.spec.layers):
            z = noise.normals(noise.key(self.noise_seed, self.noise_name, 1 + li), 2 * i0, 2 * nb)
            mx[li] = mx[li] * (1.0 + d) + sx * z[0::2]
            my[li] = my[li] * (1.0 + d) + sy * z[1::2]

    def _slope_block(self, b: int) -> None:
        nb, nr = self.nb, self.nr
        w = nb + 2 * nr
        wx = np.zeros((self.spec.layers, w))
        wy = np.zeros((self.spec.layers, w))
        c0 = b * nb - nr  # the window's first cell
        for c in (b - 1, b, b + 1):
            if c not in self.rec:
                continue
            a0, a1 = max(c * nb, c0), min((c + 1) * nb, c0 + w)
            if a1 > a0:
                mx, my = self.rec[c]
                wx[:, a0 - c0 : a1 - c0] = mx[:, a0 - c * nb : a1 - c * nb]
                wy[:, a0 - c0 : a1 - c0] = my[:, a0 - c * nb : a1 - c * nb]
        g = flux_slope(wx, self.slab, self.spec.rep_head(), self.k_max, wy)
        self.slopes[b] = g[nr - 2 : nr + nb + 2]

    def ready(self, b: int) -> bool:
        """Block b's samples are in."""
        t1 = self._span(b)[3]
        return t1 is not None and math.floor(t1 * self.fs) + 3 <= self.n

    def push_many(self, hs: np.ndarray) -> np.ndarray:
        """`push` for each of hs in turn (the same results, any chunking)."""
        hs = np.asarray(hs, float)
        n0 = self.n
        m = self.literal or 1
        if len(hs) % m:
            raise ValueError(f"literal bias: pushes of {m} samples each")
        self.h = np.concatenate([self.h, hs])
        self.n += len(hs) // m
        fs = self.fs
        if self.moving:
            self._advance(self.n)
        # Every block whose samples are in, then its predecessor's slope.
        while self.ready(self.next_rec):
            b = self.next_rec
            self._record_block(b)
            self.next_rec += 1
            if b >= 1:
                self._slope_block(b - 1)
                self.rec.pop(b - 2, None)
        # Samples no block will read again.
        t0n = self._span(self.next_rec)[2]
        keep = self.first // m if t0n is None else max(math.floor(t0n * fs) - 1, 0)
        if keep * m > self.first:
            self.h = self.h[keep * m - self.first :]
            self.first = keep * m
        # Positions: from the earliest a future recording reads and this push's outputs.
        cut = min(keep - 2, n0 + 1)
        if self.moving and cut > self.s_first:
            self.s = self.s[cut - self.s_first :]
            self.s_first = cut
        out = np.zeros(len(hs) // m)
        if self.moving:
            k = np.arange(n0, self.n) + 1 - self.s_first
            u = (self.s[k] - self.d) / self.slab.ds_m
        else:
            u = (self.v * (np.arange(n0, self.n) + 1) / fs - self.d) / self.slab.ds_m
        live = u >= 0
        blocks = np.floor(u).astype(np.int64) // self.nb
        for b in np.unique(blocks[live]):
            sel = live & (blocks == b)
            out[sel] = (
                -self.v * self.scale * cubic_held(self.slopes[int(b)], u[sel] - (b * self.nb - 2))
            )
        if live.any():
            for b in [k for k in self.slopes if k < int(blocks[live].max()) - 1]:
                del self.slopes[b]
        return out

    def push(self, h: float) -> float:
        return float(self.push_many(np.array([h]))[0])


# --- The print --------------------------------------------------------------------------


def print_audio(
    x: np.ndarray,
    fs: float,
    spec: TapeMachineSpec,
    tape: TapeFormulation,
    al: Alignment,
    drive_db: float = 0.0,
    progress=None,
    engine: str = "circuitsim",
    noise_seed: int | None = None,
    transport_seed: int = 0,
) -> np.ndarray:
    """Audio (full scale 1.0, mono) recorded on the tape and played back (see the module
    docs): the record network, then `TapeStream` fed the whole clip and the silence after
    it (the heads' distance rounded to whole samples, the delay taken out), then the repro
    network. engine: "circuitsim" (the stream's port, all of it in Rust), or the reference
    `TapeStream` recording with "rust" (circuitsim's kernel) or "python"."""
    v = spec.speed_m_s
    tp = al.trim_tp_s
    gain = al.hg_0vu / MINUS_18_DBFS_PEAK * 10 ** (drive_db / 20)
    rb_, ra_ = rec_network(spec, al.rec_trim_tz_s, tp)
    y = gain * _filter(rb_, ra_, np.asarray(x, float), fs)
    delay = int(round(spec.head_distance_m / v * fs))
    feed = np.concatenate([y, np.zeros(delay)])
    emf = np.zeros(len(feed) + 1)  # emf[n] at t_n: push n returns t_{n+1}
    if engine == "circuitsim":
        import circuitsim

        params = stream_params(spec, tape, al.hg_bias, head_distance_m=delay * v / fs)
        emf[1:] = circuitsim.tape_stream_run(
            json.dumps(params), fs, feed, noise_seed=noise_seed, transport_seed=transport_seed
        )
        if progress:
            progress(1.0)
    else:
        st = TapeStream(
            spec,
            tape,
            al.hg_bias,
            fs,
            engine=engine,
            head_distance_m=delay * v / fs,
            noise_seed=noise_seed,
            transport_seed=transport_seed,
        )
        chunk = int(fs * 0.05)
        for c0 in range(0, len(feed), chunk):
            part = feed[c0 : c0 + chunk]
            emf[c0 + 1 : c0 + 1 + len(part)] = st.push_many(part)
            if progress:
                progress(min(c0 + chunk, len(feed)) / len(feed))
    return repro_output(emf[delay : delay + len(x)], fs, spec, tape, al)


def repro_output(
    emf: np.ndarray, fs: float, spec: TapeMachineSpec, tape: TapeFormulation, al: Alignment
) -> np.ndarray:
    """The repro head's EMF (a stream's, rep_h_per_a = 1) through the repro network, at
    the print's level (full scale 1.0)."""
    rb, ra = rep_network(spec, al.rep_trim_tz_s, al.trim_tp_s)
    # The stream's volts are tone_harmonics' units times mu0 W Ms dy (rep_h_per_a = 1).
    volts_per_unit = MU0 * spec.track_m * tape.ms_a_m * (tape.coating_m / spec.layers)
    return al.out_gain / volts_per_unit * _filter(rb, ra, np.asarray(emf, float), fs)
