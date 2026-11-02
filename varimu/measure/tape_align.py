"""The Ampex 351's alignment as a procedure (docs/TAPE_PLAN.md, TM5): the trimmers and level
controls of config/circuits/ampex_351.yaml set as the 1962 manual sets them (pp.79-85;
data/schematics/ampex_351/README.md, "Alignment"), each by measuring the whole machine.

    al = align()                     # ~40 min: full-machine runs, several at a time
    al.overrides                     # the settings, for a render or a print

The steps, in this order:

1. **Playback EQ** (2R31, `rep_eq_hi`), from a virtual test tape. A test tape's levels
   are the short-circuit flux at the tape's surface, recorded to the NAB curve (3180 /
   50 us, man p39) so that an ideal reproducer plays it flat. The trim makes the real
   head's reading through the reproduce amplifier flattest from 1 to 15 kHz re 700 Hz
   (the test tape's reference tone). Two measurements make that: the head's loss (its
   reading over an ideal reproducer's of the same recorded pattern, from the medium:
   `tape_machine.tone_harmonics`) and the reproduce amplifier's response from the head's
   EMF to the line out (`repro_ir`: the reproduce side alone, cheap). The manual: "not
   moved more than 2 db from the standard curve"; the report has how far it moved.
2. **Bias** (BIAS ADJUST 5C13, `bias_adjust_f`): 1 kHz at 15 ips ("bias is set at a
   specific wavelength", man p82: 500 Hz at 7.5 ips) at a level well under operating
   level; the output's peak over BIAS ADJUST, the points 1/2 dB down either side, the
   BIAS meter read at each (the head's bias current across 5R24, rms) and the bias set
   at the median of the two readings. The meter reads in VU, so the median of the
   readings is the currents' geometric mean.
3. **Record EQ** (1C7, `rec_eq_hi_f`): the flattest low-level response 1-15 kHz re
   500 Hz, -10 dB under operating level (man p84: 15 ips at least 10 dB under). At that
   level the machine is linear, so the response at any 1C7 is the full machine's at one
   1C7 times the record amplifier's change (`record_ir`: the record side alone, cheap).
4. **Record level** (RECORD LEVEL 4R9, `record_level`): operating level is "a steady
   400 cycle tone the level of which produces 1% total rms distortion" (man p84). The
   program's 0 VU in (-10 dBm bridging, -18 dBFS rms) records at operating level: the
   rotation at which 400 Hz at 0 VU in plays back with 1% THD at the line out.
5. **Playback level** (PLAYBACK LEVEL 4R36, `playback_level`): the test tape's 700 Hz
   reference at operating level plays at 0 VU, +8 dBm (man p80): 700 Hz recorded at 0 VU
   in plays back at -18 dBFS rms.

The manual calibrates the playback level before the record level from the real test
tape; with a virtual one, operating level on this tape is only known after step 4, so
step 5 comes last (the same settings). The record EQ comes before the record level so the
1% is measured with it (the manual's caution, p83: "Changing bias may change the RECORD
LEVEL CALIBRATION").

The full-machine runs are production's simulation (esdirk4, 192 kHz, JA cores) at 192 kHz
without decimation (`oversample` 1: the same steps, so the BIAS meter sees the ~99 kHz).
Not set here: ERASE ADJUST and NOISE BALANCE (centred, man p82, p84), the meter
calibrations (not modelled). varimu/measure is outside the render cache key.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import math
import time
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
from scipy import signal as sps

from varimu.circuit import builder, spec
from varimu.circuit import ir as irm
from varimu.config import REPO_ROOT
from varimu.devices import library
from varimu.devices.tape_machine import TapeMachineSpec, tone_harmonics
from varimu.sim import fast
from varimu.sim.io import TransientSettings

CIRCUIT = "ampex_351"
#: 0 VU in and out: -18 dBFS rms (the circuit file's full_scale: -10 dBm in, +8 dBm out).
VU0_DBFS_RMS = -18.0
#: NAB at 15 ips (man p39).
T1_S, T2_S = 3180e-6, 50e-6
#: The test tape's reference tone and the frequencies the trims flatten (man p80, p83).
TT_REF_HZ = 700.0
HF_HZ = (1000.0, 2500.0, 5000.0, 7500.0, 10000.0, 12500.0, 15000.0)
REC_REF_HZ = 500.0
#: Tones are recorded this long after the settle (the output arrives a head distance
#: later, 133 ms at 15 ips); measured from MEASURE_FROM_S on.
TONE_S = 0.38
MEASURE_FROM_S = 0.19
FADE_S = 5e-3
#: Step 2's level re 0 VU in (at the record level it is given: "on-scale", well under
#: saturation) and step 3's (man p84: at least 10 dB under operating level).
BIAS_LEVEL_DB = -10.0
LOW_LEVEL_DB = -10.0
#: Full-machine runs at once (each keeps two threads spinning: TAPE_PLAN.md TM5).
WORKERS = 6


@dataclass(frozen=True)
class Bench:
    """The machine on the bench: its circuit file, the runs' settings, levels."""

    circuit: spec.CircuitSpec
    settings: TransientSettings
    v_in_peak: float  # volts at 0 dBFS in
    v_out_peak: float
    workers: int = WORKERS

    @property
    def fs(self) -> int:
        return self.settings.sample_rate

    @classmethod
    def load(cls, workers: int = WORKERS) -> Bench:
        c = spec.load_circuit(spec.circuit_path(CIRCUIT))
        s = TransientSettings.from_sim_settings(engine="circuitsim")
        s = dataclasses.replace(s, sample_rate=s.sample_rate * s.oversample, oversample=1)
        vin, vout = c.full_scale
        return cls(c, s, vin, vout, workers)

    def vu_peak_v(self, level_db: float) -> float:
        """The input's peak volts for a sine at level_db re 0 VU in."""
        return self.v_in_peak * 10 ** ((VU0_DBFS_RMS + level_db) / 20) * math.sqrt(2)

    def out_dbfs_rms(self, amp_peak_v: float) -> float:
        """A sine of amp_peak_v volts at the line out, in dBFS rms."""
        return 20 * math.log10(amp_peak_v / math.sqrt(2) / self.v_out_peak)


# --- Measuring --------------------------------------------------------------------------


def tone(b: Bench, freqs_hz: Sequence[float], level_db: float, seconds: float = TONE_S):
    """Sines at freqs_hz, each at level_db re 0 VU in, faded in (input volts)."""
    t = np.arange(int(seconds * b.fs)) / b.fs
    a = b.vu_peak_v(level_db)
    x = sum(np.sin(2 * math.pi * f * t) for f in freqs_hz)
    return a * x * np.minimum(1.0, t / FADE_S)


def fit(y: np.ndarray, fs: float, freqs_hz: Sequence[float]) -> np.ndarray:
    """Complex amplitudes (peak, cos - i sin) of freqs_hz in y, by least squares with an
    offset and a slope (a coupling capacitor's slow tail)."""
    t = np.arange(len(y)) / fs
    cols = [np.ones_like(t), t - t.mean()]
    for f in freqs_hz:
        cols += [np.cos(2 * math.pi * f * t), np.sin(2 * math.pi * f * t)]
    c, *_ = np.linalg.lstsq(np.array(cols).T, y, rcond=None)
    return c[2::2] - 1j * c[3::2]


def band_width_hz(f_hz: float) -> float:
    """The half-width of a tone's band: the Hann window's main lobe (+-10.5 Hz over a
    0.19 s window) and the transport's frequency modulation (0.11% rms wow and flutter: its
    sidebands reach ~0.4% of the tone at 15 kHz); narrow enough to keep a 30 Hz tone off
    DC."""
    return 12.0 + 0.006 * f_hz


def level(y: np.ndarray, fs: float, f_hz: float) -> float:
    """The peak amplitude of the tone at f_hz in y, from the power in its band (a VTVM
    behind a band-pass: robust to the tape's wow and flutter, where a coherent fit loses a
    tone whose phase wanders)."""
    y = np.asarray(y, float) - np.mean(y)
    w = np.hanning(len(y))
    n = 4 * len(y)
    p = np.abs(np.fft.rfft(y * w, n)) ** 2
    f = np.fft.rfftfreq(n, 1.0 / fs)
    s = p[np.abs(f - f_hz) <= band_width_hz(f_hz)].sum()
    return float(np.sqrt(4.0 * s / (n * (w**2).sum())))


def thd(y: np.ndarray, fs: float, f_hz: float, harmonics: int = 7) -> tuple[float, np.ndarray]:
    """THD (a fraction: the harmonics' rms over the fundamental's) and |h_n| / |h_1|, each
    from its band's power (`level`)."""
    a = np.array([level(y, fs, n * f_hz) for n in range(1, harmonics + 1)])
    return float(np.sqrt((a[1:] ** 2).sum()) / a[0]), a / a[0]


def bias_rms(rbc_v: np.ndarray, fs: float, r_ohm: float) -> float:
    """The BIAS meter: the bias current's rms through 5R24 (above 40 kHz)."""
    sos = sps.butter(8, 40e3, "highpass", fs=fs, output="sos")
    i = sps.sosfiltfilt(sos, rbc_v) / r_ohm
    return float(np.sqrt(np.mean(i**2)))


def run(b: Bench, overrides: Mapping[str, Any], x: np.ndarray) -> dict[str, np.ndarray]:
    """The whole machine (JA cores) on input x: its probes, the settle left out."""
    c = builder.build(b.circuit, dict(overrides), cores="ja")
    return fast.run_transient(c.ir, x, settings=b.settings).vectors


def run_many(b: Bench, jobs: Sequence[tuple[Mapping[str, Any], np.ndarray]], note=print):
    """`run` on each (overrides, x), b.workers at a time (circuitsim releases the GIL)."""
    t0 = time.perf_counter()
    with ThreadPoolExecutor(b.workers) as ex:
        out = list(ex.map(lambda j: run(b, *j), jobs))
    note(f"  {len(jobs)} runs in {time.perf_counter() - t0:.0f} s")
    return out


def window(b: Bench, v: np.ndarray) -> np.ndarray:
    return v[int(MEASURE_FROM_S * b.fs) :]


# --- Partial circuits -------------------------------------------------------------------


def _sub_ir(full: irm.CircuitIR, titles: set[str], input_node: str, drop=()) -> irm.CircuitIR:
    secs = []
    for s in full.sections:
        if s.title in titles:
            els = tuple(e for e in s.elements if not isinstance(e, tuple(drop)))
            secs.append(dataclasses.replace(s, elements=els, substeps=None))
    nodes = {n for s in secs for e in s.elements for n in irm.element_nodes(e)}
    probes = tuple(p for p in full.probes if p.node in nodes)
    return dataclasses.replace(full, sections=tuple(secs), input_node=input_node, probes=probes)


def repro_ir(b: Bench, overrides: Mapping[str, Any]) -> irm.CircuitIR:
    """The reproduce side alone, driven at the repro head's EMF (node tp_e, behind the
    head's coil): the supply, the idle microphone stage, the head's coil, the reproduce
    amplifier and the output. The record side's load on the supply is gone (its B+ is a
    few % higher): for ratios only."""
    full = builder.build(b.circuit, dict(overrides), cores="ja").ir
    keep = {"power supply", "microphone stage (idle)", "heads and tape"}
    keep |= {"reproduce amplifier", "output"}
    return _sub_ir(full, keep, "tp_e", drop=(irm.Tape,))


def record_ir(b: Bench, overrides: Mapping[str, Any]) -> irm.CircuitIR:
    """The record side alone at the audio rate, the oscillator out: the supply, the record
    amplifier and the head driver into the record head and 5R24. For ratios only."""
    full = builder.build(b.circuit, {**overrides, "oscillator": 0}, cores="ja").ir
    keep = {"power supply", "microphone stage (idle)", "record amplifier"}
    keep |= {"bias and head driver"}
    return _sub_ir(full, keep, full.input_node)


def response(
    b: Bench, ir: irm.CircuitIR, probe: str, freqs_hz: Sequence[float], amp_v: float
) -> np.ndarray:
    """ir's complex response from its input to `probe` at freqs_hz (a multitone, each
    amp_v peak, random phases; linear circuits)."""
    t = np.arange(int(0.3 * b.fs)) / b.fs
    ph = np.random.default_rng(1).uniform(0, 2 * math.pi, len(freqs_hz))
    x = amp_v * sum(np.sin(2 * math.pi * f * t + p) for f, p in zip(freqs_hz, ph, strict=True))
    v = fast.run_transient(ir, x, settings=b.settings).vectors[f"v({probe})"]
    w = slice(int(0.1 * b.fs), None)
    return fit(v[w], b.fs, freqs_hz) / fit(x[w], b.fs, freqs_hz)


def _db(z) -> np.ndarray:
    return 20 * np.log10(np.abs(z))


# --- The steps --------------------------------------------------------------------------


def head_loss(b: Bench, freqs_hz: Sequence[float]) -> np.ndarray:
    """The repro head's reading of a low-level recorded pattern over the ideal
    reproducer's (complex), on the circuit's tape and heads. The ratio doesn't depend on
    the bias (measured: 2.5 and 3 Hc agree to 1e-3 dB); 3 Hc."""
    p = spec.resolve(b.circuit)
    m = TapeMachineSpec(
        speed_m_s=p["speed_m_s"],
        f_bias_hz=p["f_bias_hz"],
        rec_gap_m=p["rec_gap_m"],
        rep_gap_m=p["rep_gap_m"],
        pole_m=p["pole_m"],
        relax_m=p["relax_m"],
        track_m=p["track_m"],
        spacing_m=p["spacing_m"],
        head_distance_m=p["head_distance_m"],
        flutter=False,
    )
    tape = library.load_tape(p["tape_model"])
    hc = tape.preisach.hc_median_a_m
    out = []
    for f in freqs_hz:
        real, ideal = tone_harmonics(m, tape, f, 0.05 * hc, 3.0 * hc, harmonics=1, ideal=True)
        out.append(real[0] / ideal[0])
    return np.array(out)


def _nab(freqs_hz) -> np.ndarray:
    """The standard tape's flux (man p39) times i w: what an ideal head reads from it."""
    s = 2j * math.pi * np.asarray(freqs_hz, float)
    return (1 + s * T1_S) / (T1_S * (1 + s * T2_S))


def _grid_min(f: Callable[[float], float], lo: float, hi: float, n: int, rounds: int, workers):
    """The minimum of f over [lo, hi]: n points, then n around the best, `rounds` times
    (points of a round evaluated in parallel)."""
    best = None
    for _ in range(rounds):
        xs = np.linspace(lo, hi, n)
        with ThreadPoolExecutor(workers) as ex:
            ys = list(ex.map(f, xs))
        i = int(np.argmin(ys))
        best = (float(xs[i]), float(ys[i]))
        step = (hi - lo) / (n - 1)
        lo, hi = max(lo, xs[i] - step), min(hi, xs[i] + step)
    return best


def playback_eq(b: Bench, overrides: Mapping[str, Any], note=print) -> dict[str, Any]:
    """Step 1: rep_eq_hi for the flattest test-tape playback, 1-15 kHz re 700 Hz."""
    freqs = (TT_REF_HZ, *HF_HZ)
    loss = head_loss(b, freqs)
    tape_in = loss * _nab(freqs)  # the real head's EMF from the test tape (one scale)

    def dev(pos: float) -> np.ndarray:
        g = response(b, repro_ir(b, {**overrides, "rep_eq_hi": pos}), "out", freqs, 1e-4)
        d = _db(g * tape_in)
        return d[1:] - d[0]

    def cost(pos: float) -> float:
        return float(np.sqrt(np.mean(dev(pos) ** 2)))

    pos, rms = _grid_min(cost, 0.0, 1.0, 11, 3, 8)
    d = dev(pos)
    nominal = dev(_spec_default(b, "rep_eq_hi"))
    note(f"playback EQ: 2R31 at {pos:.3f}, rms {rms:.2f} dB 1-15 kHz re 700 Hz")
    return {
        "rep_eq_hi": pos,
        "freqs_hz": list(freqs[1:]),
        "head_loss_db": [float(x) for x in _db(loss)],
        "flatness_db": [float(x) for x in d],
        "flatness_rms_db": rms,
        # How far from the standard curve (2R31 at 50 us with 2C15) the trim moved it.
        "moved_db": [float(x) for x in d - nominal],
    }


def _spec_default(b: Bench, key: str) -> float:
    return float(spec.resolve(b.circuit)[key])


def bias(b: Bench, overrides: Mapping[str, Any], note=print, points: int = 12) -> dict[str, Any]:
    """Step 2: BIAS ADJUST at the median of the 1/2 dB points of 1 kHz's peak."""
    lo, hi = (b.circuit.controls["bias_adjust_f"][k] for k in ("min", "max"))
    cs = np.geomspace(lo, hi * 0.6, points)
    x = tone(b, [1000.0], BIAS_LEVEL_DB)
    runs = run_many(b, [({**overrides, "bias_adjust_f": float(c)}, x) for c in cs], note)
    r_cal = spec.resolve(b.circuit)["r_bias_cal_ohm"]
    out_db = np.array([_db(level(window(b, v["v(out)"]), b.fs, 1000.0)) for v in runs])
    i_rms = np.array([bias_rms(window(b, v["v(rbc)"]), b.fs, r_cal) for v in runs])
    lc = np.log(cs)
    i = int(np.argmax(out_db))
    if i in (0, len(cs) - 1):
        raise RuntimeError(f"1 kHz doesn't peak within BIAS ADJUST's sweep: {out_db}")
    fine = np.linspace(lc[0], lc[-1], 4000)
    spl = sps_interp(lc, out_db)(fine)
    pk = int(np.argmax(spl))
    lo_i = pk - int(np.argmax(spl[:pk][::-1] < spl[pk] - 0.5))
    hi_i = pk + int(np.argmax(spl[pk:] < spl[pk] - 0.5))
    if lo_i == pk or hi_i == pk:
        raise RuntimeError("the 1/2 dB points aren't both within the sweep")
    li = np.log(i_rms)
    i_lo, i_hi = (math.exp(float(np.interp(fine[k], lc, li))) for k in (lo_i, hi_i))
    i_set = math.sqrt(i_lo * i_hi)  # the median of two VU (dB) readings
    c_set = math.exp(float(np.interp(math.log(i_set), li, lc)))
    note(
        f"bias: peak at {math.exp(fine[pk]) * 1e12:.1f} pF; 1/2 dB points "
        f"{i_lo * 1e3:.2f} / {i_hi * 1e3:.2f} mA rms; set {i_set * 1e3:.2f} mA, "
        f"{c_set * 1e12:.1f} pF"
    )
    return {
        "bias_adjust_f": c_set,
        "sweep_f": [float(c) for c in cs],
        "sweep_out_db": [float(d) for d in out_db - out_db.max()],
        "sweep_bias_ma_rms": [float(a * 1e3) for a in i_rms],
        "peak_f": math.exp(fine[pk]),
        "half_db_ma_rms": [i_lo * 1e3, i_hi * 1e3],
        "bias_ma_rms": i_set * 1e3,
    }


def sps_interp(x: np.ndarray, y: np.ndarray):
    """A smooth interpolant through measured points (a monotone cubic: no overshoot)."""
    from scipy.interpolate import PchipInterpolator

    return PchipInterpolator(x, y)


def record_eq(b: Bench, overrides: Mapping[str, Any], note=print) -> dict[str, Any]:
    """Step 3: rec_eq_hi_f for the flattest low-level response 1-15 kHz re 500 Hz."""
    freqs = (REC_REF_HZ, *HF_HZ)
    c0 = float(spec.resolve(b.circuit, overrides)["rec_eq_hi_f"])
    runs = run_many(b, [(overrides, tone(b, [f], LOW_LEVEL_DB)) for f in freqs], note)
    full0 = np.array(
        [level(window(b, v["v(out)"]), b.fs, f) for v, f in zip(runs, freqs, strict=True)]
    )
    amp = b.vu_peak_v(LOW_LEVEL_DB)

    def rec(c: float) -> np.ndarray:
        return response(b, record_ir(b, {**overrides, "rec_eq_hi_f": c}), "rbc", freqs, amp / 4)

    r0 = rec(c0)

    def dev(c: float) -> np.ndarray:
        d = _db(full0 * rec(c) / r0)
        return d[1:] - d[0]

    def cost(c: float) -> float:
        return float(np.sqrt(np.mean(dev(c) ** 2)))

    lo, hi = (b.circuit.controls["rec_eq_hi_f"][k] for k in ("min", "max"))
    c_set, rms = _grid_min(cost, lo, hi, 10, 3, 8)
    note(f"record EQ: 1C7 at {c_set * 1e12:.0f} pF, rms {rms:.2f} dB 1-15 kHz re 500 Hz")
    return {
        "rec_eq_hi_f": c_set,
        "freqs_hz": list(freqs[1:]),
        "before_db": [float(x) for x in dev(c0)],
        "flatness_db": [float(x) for x in dev(c_set)],
        "flatness_rms_db": rms,
    }


def record_level(
    b: Bench, overrides: Mapping[str, Any], note=print, levels=(0.7, 0.8, 0.9, 1.0)
) -> dict[str, Any]:
    """Step 4: RECORD LEVEL for 1% THD at 400 Hz, 0 VU in, at the line out."""
    x = tone(b, [400.0], 0.0)
    runs = run_many(b, [({**overrides, "record_level": lv}, x) for lv in levels], note)
    th = np.array([thd(window(b, v["v(out)"]), b.fs, 400.0)[0] for v in runs])
    if not th[0] < 0.01 < th[-1]:
        raise RuntimeError(f"1% THD isn't bracketed by RECORD LEVEL {levels}: {th}")
    lv = math.exp(float(np.interp(math.log(0.01), np.log(th), np.log(levels))))
    note(f"record level: {lv:.3f} for 1% THD (sweep {np.round(th * 100, 3).tolist()} %)")
    return {
        "record_level": lv,
        "sweep_levels": list(levels),
        "sweep_thd_pct": [float(t * 100) for t in th],
    }


def playback_level(
    b: Bench, overrides: Mapping[str, Any], note=print, guesses=(0.3, 0.6)
) -> dict[str, Any]:
    """Step 5: PLAYBACK LEVEL so 700 Hz at 0 VU in plays back at 0 VU (-18 dBFS rms);
    the output against the rotation is interpolated in log-log between two runs."""
    x = tone(b, [TT_REF_HZ], 0.0)
    runs = run_many(b, [({**overrides, "playback_level": g}, x) for g in guesses], note)
    lv = np.array([b.out_dbfs_rms(level(window(b, v["v(out)"]), b.fs, TT_REF_HZ)) for v in runs])
    lg = np.log(guesses)
    slope = (lv[1] - lv[0]) / (lg[1] - lg[0])
    pos = math.exp(lg[0] + (VU0_DBFS_RMS - lv[0]) / slope)
    if not 0.0 < pos <= 1.0:
        raise RuntimeError(f"PLAYBACK LEVEL out of range for 0 VU: {pos} ({lv})")
    note(f"playback level: {pos:.4f} ({lv.round(2).tolist()} dBFS at {list(guesses)})")
    return {"playback_level": pos, "guesses": list(guesses), "guess_dbfs": lv.tolist()}


def check(b: Bench, overrides: Mapping[str, Any], note=print) -> dict[str, Any]:
    """The aligned machine: 400 Hz THD and 700 Hz level at 0 VU in, the repro head's level
    at 500 Hz (the drawing: -68 dB re 0.78 V, 8.2 dB under operating level)."""
    jobs = [(overrides, tone(b, [f], 0.0)) for f in (400.0, TT_REF_HZ, 500.0)]
    v400, v700, v500 = run_many(b, jobs, note)
    t, h = thd(window(b, v400["v(out)"]), b.fs, 400.0)
    out700 = b.out_dbfs_rms(level(window(b, v700["v(out)"]), b.fs, TT_REF_HZ))
    rh500 = level(window(b, v500["v(rh)"]), b.fs, 500.0) / math.sqrt(2)
    head400 = level(window(b, v400["v(rbc)"]), b.fs, 400.0) / math.sqrt(2)
    r_cal = spec.resolve(b.circuit)["r_bias_cal_ohm"]
    res = {
        "thd_400hz_pct": t * 100,
        "harmonics_400hz_pct": [float(x * 100) for x in h[1:]],
        "out_700hz_dbfs_rms": out700,
        "repro_head_500hz_db_re_078v": 20 * math.log10(rh500 / 0.775),
        "record_head_audio_ma_rms": head400 / r_cal * 1e3,
        "bias_ma_rms": bias_rms(window(b, v400["v(rbc)"]), b.fs, r_cal) * 1e3,
    }
    note(f"check: {json.dumps(res, default=float)}")
    return res


# --- The procedure ----------------------------------------------------------------------


@dataclass(frozen=True)
class Alignment:
    """The settings the alignment found (`overrides`) and what each step measured."""

    overrides: dict[str, Any]  # the genome's values plus the alignment's settings
    steps: dict[str, Any] = field(default_factory=dict)
    key: str = ""


def _key(b: Bench, genome: Mapping[str, Any] | None = None) -> str:
    """The alignment's cache key: the circuit file (its device and tape versions are
    immutable), the genome, the code (this module, varimu/sim, circuit, devices: as a
    render's), the settings."""
    from varimu.sim import runner

    h = hashlib.sha256()
    h.update(json.dumps(dict(genome or {}), sort_keys=True, default=str).encode())
    h.update(spec.circuit_path(CIRCUIT).read_bytes())
    h.update(Path(__file__).read_bytes())
    h.update(json.dumps(dataclasses.asdict(b.settings), sort_keys=True, default=str).encode())
    h.update(runner.code_version().encode())
    return h.hexdigest()[:16]


def align(b: Bench | None = None, note=print, start: Mapping[str, Any] | None = None):
    """Steps 1-5 on the circuit file's defaults (plus `start`), then `check`."""
    b = b or Bench.load()
    o: dict[str, Any] = dict(start or {})
    steps: dict[str, Any] = {}
    t0 = time.perf_counter()
    steps["playback_eq"] = playback_eq(b, o, note)
    o["rep_eq_hi"] = steps["playback_eq"]["rep_eq_hi"]
    # Steps 2-3 record well under operating level; PLAYBACK LEVEL low enough that the
    # output stage stays clean whatever the record level gives.
    o.setdefault("record_level", 0.85)
    o.setdefault("playback_level", 0.3)
    steps["bias"] = bias(b, o, note)
    o["bias_adjust_f"] = steps["bias"]["bias_adjust_f"]
    steps["record_eq"] = record_eq(b, o, note)
    o["rec_eq_hi_f"] = steps["record_eq"]["rec_eq_hi_f"]
    steps["record_level"] = record_level(b, o, note)
    o["record_level"] = steps["record_level"]["record_level"]
    steps["playback_level"] = playback_level(b, o, note)
    o["playback_level"] = steps["playback_level"]["playback_level"]
    steps["check"] = check(b, o, note)
    steps["wall_s"] = time.perf_counter() - t0
    return Alignment(dict(o), steps, _key(b, start))


ALIGN_DIR = REPO_ROOT / "cache" / "tape"


def aligned(
    genome: Mapping[str, Any] | None = None, note=print, refresh: bool = False
) -> Alignment:
    """`align` on the circuit file with `genome`'s values, cached by `_key`
    (cache/tape/align_351_<key>.json)."""
    b = Bench.load()
    key = _key(b, genome)
    path = ALIGN_DIR / f"align_351_{key}.json"
    if path.exists() and not refresh:
        return Alignment(**json.loads(path.read_text()))
    al = align(b, note, start=genome)
    ALIGN_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dataclasses.asdict(al), indent=1, default=float))
    return al
