"""Radioactivity in audio: a neon glow-lamp oscillator primed by a radioisotope (2026-11-14).

An experiment, not a device: offline Python, outside the render cache key, nothing in the
engine changed. `uv run --extra listen python scripts/neon_primer.py` -> reports/neon_primer/.

**The physics.** A neon lamp across a capacitor charged through a resistor is a sawtooth
oscillator (Pearson-Anson; the Trautonium's first tone source, GE's Glow Lamp Manual ch. 2).
The lamp fires when the capacitor passes its breakdown voltage, but only once a free electron
appears in the gas to start the avalanche: the *statistical time lag*. Light frees electrons
from the cathode; in the dark they come from cosmic rays, from the afterglow of the last
discharge (the lamp's "memory") or from a radioactive additive GE put in most lamps "for the
reduction of dark effect" (Kr-85 in the fill gas, per patent literature). So radioactivity sets
how regularly a neon oscillator fires in the dark: its pitch jitter and its stalls.

**The model** (per cycle, exact charging between firings; GE Glow Lamp Manual, 2nd ed. 1966,
archive.org `ge-glow-lamp-manual-1966`, for the 5AB = NE-23, which has the "mild radioactive
additive"):
- breakdown hazard  lambda = S(tau) P(dV),  dV = v - (VB0 - dV_mem(tau)), tau since extinction;
- P(dV) = 1 - exp(-(dV / V0)^m), the chance a seed electron starts an avalanche, and S_DARK
  (seeds/s of the NE-23 in the dark): fitted to Fig. 5.9's 0 ft-c curve (3-sigma = 99.8th
  percentile of an exponential lag, ln 500 means);
- the avalanche (formative) time t_a(dV) = TA0 (dV / 3.7 V)^-NA, fitted to Fig. 5.9's 500 ft-c
  curve (statistical lag negligible there); it runs as a rate integral, so the rising ramp
  speeds it up;
- light: seeds per ft-c from Fig. 5.9's 0.1 ft-c curve;
- memory: the breakdown voltage just after a discharge is lowered by dV_mem(tau) (fitted by
  eye to Fig. 5.12's upper envelope), and afterglow seeds S_mem(tau) = SM0 exp(-tau / TAU_M)
  (provisional: sized so that refiring within Fig. 5.12's window is light-independent, as GE
  reports);
- the extinguishing voltage Ve(R, f) from Fig. 2.16 (digitized by eye; quasi-static in the
  previous cycle's frequency); the discharge itself is instantaneous;
- checked against Figs. 2.15 / 2.17 (the dynamic firing voltage and amplitude vs frequency).

Conditions: the bench lamp (50 ft-c, GE's office light), the NE-23 in the dark as made in 1966,
the same lamp in 2026 (Kr-85's half-life 10.76 y: 2.1 % left), a plain unprimed lamp (cosmic
and terrestrial background only, provisional 0.1 seeds/s), and a hot primer (x30: GE's
"prohibitively high radiation intensities" direction).
"""

# ruff: noqa: E501
from __future__ import annotations

import json
import math
import zlib
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import soundfile as sf
from scipy.signal import butter, resample_poly, sosfilt

from varimu.config import load_sim_settings

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reports" / "neon_primer"
STEMS = ROOT / "stems" / "Did she mention my name" / "sample"
FS = load_sim_settings().sample_rate
OVER = 8  # synthesis at 8x, decimated by resample_poly's anti-alias FIR

# --- the lamp: GE NE-23 (5AB) ------------------------------------------------------------------
VB0 = 74.0  # V, static DC breakdown (NE-23 spec page: min 60, avg 74, max 90; "in 5-50 ft-c")
SUPPLY_V = 100.0  # V, Figs. 2.5 / 2.15-2.17's supply
# Fig. 5.9 (5AB, 3-sigma ionization time vs per cent of DC breakdown), digitized by eye.
FIG59 = {
    "0": [(105, 0.40), (115, 0.070), (125, 0.050), (150, 0.035), (180, 0.028)],
    "0.1": [(104, 1.1e-3), (120, 0.5e-3), (140, 0.25e-3), (160, 0.17e-3), (180, 0.13e-3)],
    "0.5": [(105, 0.45e-3), (125, 0.15e-3), (140, 0.10e-3), (160, 0.065e-3), (180, 0.05e-3)],
    "500": [(105, 0.22e-3), (120, 0.10e-3), (140, 0.06e-3), (160, 0.035e-3), (180, 0.025e-3)],
}
Q3 = math.log(500.0)  # 99.8th percentile of an exponential, in means
# Fig. 5.12 (refiring): dV_mem = A1 e^(-tau/T1) + A2 e^(-tau/T2), fitted by eye to the upper
# envelope's (1 V, 5 ms), (2, 2.5), (3, 1.3), (4, 0.85).
MEM = (10.0, 0.6e-3, 2.7, 5e-3)
SM0, TAU_M = 1e8, 1e-3  # afterglow seeds/s and their decay: provisional (see docstring)
# The long-memory scenario: Pejovic et al. (neon, 6.6-7 mbar lab tubes; osti.gov/biblio/22253136):
# the formative delay dominates up to ~0.1 s after a discharge, the memory rises from 30 ms to 3 s,
# cosmic rays and natural radioactivity take over beyond ~3 s. Provisional shape: 1e5 seeds/s at
# 0.1 s falling to the background by 3 s (exponential, 0.21 s). Not measured on a glow lamp.
TAIL = (1e5, 0.1, 0.21)
EMA_CYCLES = (
    8.0  # Ve follows the frequency over ~8 cycles (a quasi-static table, not a per-cycle law)
)
DV_FLOOR = 0.5  # V: t_a's argument floor (Fig. 1.2: ~300 us "slightly in excess")
S_BG = 0.1  # seeds/s from cosmic rays and terrestrial background, unprimed lamp: provisional
KR85_HALF_Y = 10.76  # y, provisional: model knowledge (NNDC: 10.739 y)
OFFICE_FC = 50.0  # GE: offices 30-60 ft-c

# Fig. 2.16 (5AB, 100 V): extinguishing voltage vs frequency per R, digitized by eye.
VE_TABLE = {
    0.51e6: [(0.1, 58.7), (10, 58.3), (100, 57.5), (300, 56.5), (1000, 55.0)],
    1e6: [(0.1, 58.7), (1, 58.5), (10, 57.8), (100, 55.5), (300, 53.5), (1000, 52.0)],
    4.7e6: [
        (0.1, 58.7),
        (1, 58.2),
        (10, 56.0),
        (100, 50.0),
        (300, 46.5),
        (1000, 45.0),
        (2000, 44.8),
    ],
    10e6: [
        (0.1, 58.7),
        (1, 58.0),
        (10, 55.0),
        (100, 48.0),
        (300, 45.0),
        (1000, 44.0),
        (2000, 44.5),
    ],
}
# Figs. 2.15 / 2.17 for the check (2.15: a 5AG, Vf; 2.17: a 5AB at R = 15 MOhm, Vf - Ve).
FIG215 = [
    (1, 77.0),
    (10, 77.2),
    (100, 78.3),
    (200, 78.8),
    (1000, 76.5),
    (4000, 74.0),
    (10000, 75.0),
]
FIG217 = [(1, 18.0), (10, 21.0), (100, 30.0), (300, 32.0), (1000, 31.5), (10000, 28.0)]


def _fit():
    """t_a(dV), P(dV), S_DARK and seeds per ft-c from Fig. 5.9."""
    pts = np.array(FIG59["500"])
    dv = VB0 * (pts[:, 0] / 100 - 1)
    sl, ic = np.polyfit(np.log(dv / 3.7), np.log(pts[:, 1]), 1)
    ta0, na = math.exp(ic), -sl

    def t_a(dv):
        return ta0 * (np.maximum(dv, DV_FLOOR) / 3.7) ** (-na)

    pts = np.array(FIG59["0"])
    dv = VB0 * (pts[:, 0] / 100 - 1)
    rate = Q3 / (pts[:, 1] - t_a(dv))  # S P(dV)
    best = None
    for m in np.linspace(0.8, 2.5, 69):
        for v0 in np.geomspace(5, 60, 111):
            p = 1 - np.exp(-((dv / v0) ** m))
            s = math.exp(np.mean(np.log(rate / p)))
            err = float(np.sum(np.log(rate / (s * p)) ** 2))
            if best is None or err < best[0]:
                best = (err, m, v0, s)
    _, m, v0, s_dark = best

    def p_av(dv):
        return np.where(dv > 0, 1 - np.exp(-((np.maximum(dv, 0) / v0) ** m)), 0.0)

    pts = np.array(FIG59["0.1"])
    dv = VB0 * (pts[:, 0] / 100 - 1)
    s01 = np.exp(np.mean(np.log(Q3 / (pts[:, 1] - t_a(dv)) / p_av(dv)))) - s_dark
    per_fc = s01 / 0.1
    return (
        dict(
            ta0=ta0, na=na, m=m, v0=v0, s_dark=s_dark, per_fc=per_fc, fit_rms=math.sqrt(best[0] / 5)
        ),
        t_a,
        p_av,
    )


FIT, T_A, P_AV = _fit()


def predicted_fig59(fc: float, pct: np.ndarray) -> np.ndarray:
    dv = VB0 * (pct / 100 - 1)
    s = FIT["s_dark"] + FIT["per_fc"] * fc
    return T_A(dv) + Q3 / (s * P_AV(dv))


def dv_mem(tau):
    a1, t1, a2, t2 = MEM
    return a1 * np.exp(-tau / t1) + a2 * np.exp(-tau / t2)


# Fig. 1.3 (reionization time vs extinguished interval, 10 V excess, 170 uA prior current),
# digitized by eye, over its long-interval value (100 us, which t_a(10 V) matches: 93 us): the
# avalanche runs faster for a while after a discharge.
FIG13 = [
    (0.5e-3, 22.0),
    (1e-3, 25.0),
    (2e-3, 32.0),
    (5e-3, 50.0),
    (10e-3, 70.0),
    (20e-3, 92.0),
    (50e-3, 100.0),
]


def reion(tau):
    x, y = np.log([p[0] for p in FIG13]), np.array([p[1] for p in FIG13]) / 100.0
    return np.interp(np.log(np.maximum(tau, 1e-6)), x, y)


def s_mem(tau, tail: bool = False):
    s = SM0 * np.exp(-tau / TAU_M)
    if tail:
        a, t0, tt = TAIL
        s = s + a * np.exp(-(tau - t0) / tt)
    return s


def ve_of(r: float, f: float) -> float:
    rs = sorted(VE_TABLE)
    lf = math.log10(min(max(f, 0.1), 2000.0))
    vals = [
        np.interp(lf, np.log10([p[0] for p in VE_TABLE[k]]), [p[1] for p in VE_TABLE[k]])
        for k in rs
    ]
    return float(np.interp(math.log10(min(max(r, rs[0]), rs[-1])), np.log10(rs), vals))


CONDITIONS = {
    # name: (seeds/s from outside the gas's own afterglow, label)
    "lit": (OFFICE_FC * FIT["per_fc"] + FIT["s_dark"], "NE-23 under office light (50 ft-c)"),
    "dark_1966": (FIT["s_dark"] + S_BG, "NE-23 in the dark, its primer as made (1966)"),
    "dark_2026": (
        FIT["s_dark"] * 0.5 ** (60 / KR85_HALF_Y) + S_BG,
        "the same lamp in 2026: Kr-85 decayed to 2 %",
    ),
    "dark_unprimed": (S_BG, "a plain neon lamp in the dark: cosmic rays only"),
    "dark_hot": (30 * FIT["s_dark"] + S_BG, "the primer x30 (GE: 'prohibitively high')"),
}


class Osc:
    """A neon sawtooth: SUPPLY_V through R(t) into C, the lamp across C. R(t) is piecewise
    constant (sched_t ascending, sched_t[0] = 0)."""

    def __init__(
        self,
        c_f: float,
        sched_t,
        sched_r,
        s_ext: float,
        rng: np.random.Generator,
        tail: bool = False,
    ):
        self.tail = tail
        self.c = c_f
        self.st = np.asarray(sched_t, float)
        self.sr = np.asarray(sched_r, float)
        self.s_ext = s_ext
        self.rng = rng

    def r_at(self, t: float) -> float:
        return float(self.sr[np.searchsorted(self.st, t, side="right") - 1])

    def charge(self, t: np.ndarray, t0: float, v0: float) -> np.ndarray:
        v = np.empty_like(t)
        i = int(np.searchsorted(self.st, t0, side="right") - 1)
        tb, vb = t0, v0
        while True:
            rc = self.sr[i] * self.c
            tend = self.st[i + 1] if i + 1 < len(self.st) else np.inf
            msk = (t >= tb) & (t < tend)
            v[msk] = SUPPLY_V - (SUPPLY_V - vb) * np.exp(-(t[msk] - tb) / rc)
            if tend > t[-1]:
                return v
            vb = SUPPLY_V - (SUPPLY_V - vb) * math.exp(-(tend - tb) / rc)
            tb, i = tend, i + 1

    def fire(self, t0: float, v0: float, t_ext: float) -> tuple[float, float, float]:
        """(t_fire, v_fire, overvoltage at fire) for a cycle starting at t0 with v0, the last
        extinction at t_ext."""
        e = self.rng.exponential()
        rc = self.r_at(t0) * self.c
        w = max(3 * rc * math.log((SUPPLY_V - v0) / (SUPPLY_V - VB0)), 2e-3)
        while True:
            u = np.linspace(0.0, w, 1500)
            dv = self.charge(t0 + u, t0, v0) - (VB0 - dv_mem(u + (t0 - t_ext)))
            k = int(np.argmax(dv > 0))
            if dv[k] <= 0:
                w *= 4
                continue
            tc = (
                u[k]
                if k == 0
                else u[k - 1] + (u[k] - u[k - 1]) * (-dv[k - 1]) / (dv[k] - dv[k - 1])
            )
            g = np.unique(
                np.concatenate([u[u > tc], tc + np.geomspace(1e-9, max(w - tc, 2e-9), 2500), [tc]])
            )
            dv = self.charge(t0 + g, t0, v0) - (VB0 - dv_mem(g + (t0 - t_ext)))
            lam = (self.s_ext + s_mem(g + (t0 - t_ext), self.tail)) * P_AV(dv)
            cum = np.concatenate([[0.0], np.cumsum(0.5 * (lam[1:] + lam[:-1]) * np.diff(g))])
            if cum[-1] < e:
                if w > 3600:
                    return t0 + w, float(self.charge(np.array([t0 + w]), t0, v0)[0]), float(dv[-1])
                w *= 4
                continue
            ts = float(np.interp(e, cum, g))
            ga = np.concatenate([[ts], g[g > ts]])
            dva = self.charge(t0 + ga, t0, v0) - (VB0 - dv_mem(ga + (t0 - t_ext)))
            rate = 1 / (T_A(dva) * reion(ga + (t0 - t_ext)))
            acc = np.concatenate([[0.0], np.cumsum(0.5 * (rate[1:] + rate[:-1]) * np.diff(ga))])
            if acc[-1] < 1.0:
                w *= 2
                continue
            tf = float(np.interp(1.0, acc, ga))
            vf = float(self.charge(np.array([t0 + tf]), t0, v0)[0])
            return t0 + tf, vf, vf - (VB0 - float(dv_mem(tf + (t0 - t_ext))))

    def run(self, t_end: float, fine_fs: float | None = None, max_cycles: int | None = None):
        """Firings [(t, v_fire, ve)] up to t_end (or max_cycles), and the waveform at fine_fs."""
        t0, ve, t_ext, last, f_avg = 0.0, ve_of(self.r_at(0.0), 0.1), -1e3, None, None
        fires = []
        wave = np.zeros(int(t_end * fine_fs) + 1) if fine_fs else None
        while t0 < t_end and (max_cycles is None or len(fires) < max_cycles):
            tf, vf, _ = self.fire(t0, ve, t_ext)
            if wave is not None:
                i0, i1 = (
                    math.ceil(t0 * fine_fs),
                    min(math.ceil(min(tf, t_end) * fine_fs), len(wave)),
                )
                if i1 > i0:
                    wave[i0:i1] = self.charge(np.arange(i0, i1) / fine_fs, t0, ve)
            if last is not None:
                f_now = 1.0 / (tf - last)
                f_avg = f_now if f_avg is None else f_avg + (f_now - f_avg) / EMA_CYCLES
            ve = ve_of(self.r_at(tf), f_avg if f_avg is not None else 0.1)
            fires.append((tf, vf, ve))
            t0, t_ext, last = tf, tf, tf
        return fires, wave


def rng_for(*names) -> np.random.Generator:
    return np.random.default_rng([20261114, *[zlib.crc32(str(n).encode()) for n in names]])


def c_for(f: float, r: float) -> float:
    ve = ve_of(r, f)
    return 1.0 / (f * r * math.log((SUPPLY_V - ve) / (SUPPLY_V - VB0)))


def period_stats(fires, skip=5) -> dict:
    """Cycle-to-cycle jitter: the rms difference of successive periods (cents) over sqrt 2, so
    slow drift (Ve settling over ~30 cycles, note changes) doesn't count; `jitter_robust_cents`
    the same from the median absolute deviation (for a tune, whose note changes are outliers)."""
    t = np.array([x[0] for x in fires])
    per = np.diff(t)[skip:]
    if len(per) < 3:
        return dict(n=len(per))
    cents = 1200 * np.log2(per / np.median(per))
    d = np.diff(cents)
    return dict(
        n=int(len(per)),
        f_mean_hz=float(1 / per.mean()),
        jitter_cents=float(np.sqrt(np.mean(d**2) / 2)),
        jitter_robust_cents=float(1.4826 * np.median(np.abs(d - np.median(d))) / math.sqrt(2)),
        worst_cents=float(np.max(np.abs(cents))),
        longest_over_median=float(per.max() / np.median(per)),
        vf_mean=float(np.mean([x[1] for x in fires[skip:]])),
        vs_pp=float(np.mean([x[1] - x[2] for x in fires[skip:]])),
    )


# --- 1. the check against GE's oscillator figures ---------------------------------------------
def check_figures() -> dict:
    out = {"fig215_vf": [], "fig217_vs": []}
    for f, _ in FIG215:
        r = 4.7e6
        osc = Osc(c_for(f, r), [0.0], [r], CONDITIONS["lit"][0], rng_for("fig215", f))
        st = period_stats(osc.run(1e9, max_cycles=90)[0], skip=40)
        out["fig215_vf"].append((f, st["vf_mean"], st["f_mean_hz"]))
    for f, _ in FIG217:
        r = 15e6
        osc = Osc(c_for(f, r), [0.0], [r], CONDITIONS["lit"][0], rng_for("fig217", f))
        st = period_stats(osc.run(1e9, max_cycles=90)[0], skip=40)
        out["fig217_vs"].append((f, st["vs_pp"], st["f_mean_hz"]))
    return out


# --- 2. jitter against the seed rate -----------------------------------------------------------
SWEEP_NOTES = (27.5, 55.0, 110.0, 220.0, 440.0, 880.0)
SWEEP_S = np.geomspace(0.03, 1e8, 15)


def sweep(tail: bool) -> dict:
    res = {}
    for f in SWEEP_NOTES:
        r = 4.7e6
        c = c_for(f, r)
        row = []
        for s in SWEEP_S:
            osc = Osc(c, [0.0], [r], float(s), rng_for("sweep", f, s), tail)
            st = period_stats(osc.run(1e9, max_cycles=150)[0], skip=30)
            row.append(st)
        res[f] = row
        print(
            f"  sweep{' long' if tail else ''} {f:6.1f} Hz: "
            + " ".join(f"{x['jitter_cents']:7.2f}" for x in row),
            flush=True,
        )
    return res


# --- 3. music: a bass line and a melody on two lamps ------------------------------------------
BPM = 96.0
BASS = [
    (28, 2),
    (28, 2),
    (31, 2),
    (33, 2),
    (28, 2),
    (28, 2),
    (35, 2),
    (33, 2),
    (28, 2),
    (28, 2),
    (31, 2),
    (33, 2),
    (36, 2),
    (35, 2),
    (33, 2),
    (31, 2),
]  # (MIDI, beats)
MELODY = [
    (64, 1),
    (67, 1),
    (69, 1),
    (71, 1),
    (74, 1),
    (71, 1),
    (69, 1),
    (67, 1),
    (64, 1),
    (67, 1),
    (69, 1),
    (71, 1),
    (76, 1),
    (74, 1),
    (71, 1),
    (69, 1),
    (71, 1),
    (69, 1),
    (67, 1),
    (64, 1),
    (62, 1),
    (64, 1),
    (67, 1),
    (69, 1),
    (71, 1),
    (74, 1),
    (76, 1),
    (79, 1),
    (76, 4),
]


def hz(n: int) -> float:
    return 440.0 * 2 ** ((n - 69) / 12)


def tuned_r(f: float, c: float, cache: dict) -> float:
    """R for `f`, trimmed under the bench lamp (as a maker would tune each key), 3 steps."""
    key = (round(f, 4), c)
    if key in cache:
        return cache[key]
    r = 1 / (f * c * math.log((SUPPLY_V - ve_of(5e6, f)) / (SUPPLY_V - VB0)))
    for _ in range(3):
        osc = Osc(c, [0.0], [r], CONDITIONS["lit"][0], rng_for("tune", f))
        fm = period_stats(osc.run(1e9, max_cycles=40)[0])["f_mean_hz"]
        r *= fm / f
    cache[key] = r
    return r


def voice(notes, c: float, cond: str, name: str, cache: dict, gap_s: float, tail: bool):
    beat = 60.0 / BPM
    t, st, sr, env = 0.0, [], [], []
    for n, b in notes:
        st.append(t)
        sr.append(tuned_r(hz(n), c, cache))
        env.append((t, t + b * beat - gap_s))
        t += b * beat
    t_end = t + 0.5
    osc = Osc(c, st, sr, CONDITIONS[cond][0], rng_for("voice", name, cond), tail)
    fires, wave = osc.run(t_end, fine_fs=FS * OVER)
    y = resample_poly(wave, 1, OVER)
    y = sosfilt(butter(1, 20.0, "highpass", fs=FS, output="sos"), y - y[0])  # coupling capacitor
    tt = np.arange(len(y)) / FS
    g = np.zeros_like(y)
    for a, b in env:  # a keyer: 5 ms attack, 40 ms release
        g = np.maximum(
            g, np.clip((tt - a) / 5e-3, 0, 1) * np.clip(1 - (tt - b) / 40e-3, 0, 1) * (tt >= a)
        )
    return y * g, fires


def lufs_norm(x: np.ndarray, target: float = -23.0) -> np.ndarray:
    import pyloudnorm

    m = pyloudnorm.Meter(FS)
    lv = m.integrated_loudness(x)
    return x * 10 ** ((target - lv) / 20) if np.isfinite(lv) else x


def music(cache: dict, tail: bool) -> dict:
    """Each condition's tune; the voices' gains are the lit version's (a stalled voice stays
    quiet), each mix then loudness matched, its peak held at -1 dBFS (the stalled ones only)."""
    stats = {}
    mem = "long" if tail else "short"
    gains = None
    for cond in CONDITIONS:  # "lit" first
        b, fb = voice(BASS, 10e-9, cond, "bass", cache, 0.0, tail)
        m, fm = voice(MELODY, 1e-9, cond, "melody", cache, 0.03, tail)
        n = min(len(b), len(m))
        tone_b = sosfilt(
            butter(1, 700.0, fs=FS, output="sos"), b[:n]
        )  # a tone filter, not modelled
        tone_m = sosfilt(butter(1, 2500.0, fs=FS, output="sos"), m[:n])
        if gains is None:
            gains = (1 / np.std(tone_b), 0.7 / np.std(tone_m))
        mix = lufs_norm(gains[0] * tone_b + gains[1] * tone_m)
        mix *= min(1.0, 10 ** (-1 / 20) / np.max(np.abs(mix)))
        sf.write(OUT / f"tune_{mem}_{cond}.wav", mix.astype(np.float32), FS, subtype="FLOAT")
        stats[cond] = {"bass": period_stats(fb), "melody": period_stats(fm)}
        print(
            f"  tune {mem} {cond:14s} bass {stats[cond]['bass'].get('jitter_robust_cents', float('nan')):7.2f} c, "
            f"melody {stats[cond]['melody'].get('jitter_robust_cents', float('nan')):7.2f} c",
            flush=True,
        )
    return stats


# --- 4. processing: a neon LFO as a tremolo on the guitar stem ----------------------------------
def tremolo(tail: bool) -> dict:
    mem = "long" if tail else "short"
    x, sr = sf.read(STEMS / "guitar.wav", always_2d=True)
    assert sr == FS
    x = np.tile(x.mean(axis=1), 2)
    t_end = len(x) / FS
    r, c = 1e6, 0.47e-6
    out = {}
    for cond in CONDITIONS:
        osc = Osc(c, [0.0], [r], CONDITIONS[cond][0], rng_for("lfo", cond), tail)
        fires, wave = osc.run(t_end, fine_fs=FS * OVER)
        v = resample_poly(wave, 1, OVER)[: len(x)]
        ph = np.clip((v - 56.0) / (VB0 - 56.0), 0, 1.3)
        ph = sosfilt(butter(1, 25.0, fs=FS, output="sos"), ph)  # the gain stage's coupling
        y = x * (1 - 0.6 * ph)
        sf.write(
            OUT / f"tremolo_{mem}_{cond}.wav", lufs_norm(y).astype(np.float32), FS, subtype="FLOAT"
        )
        out[cond] = period_stats(fires, skip=1)
        print(
            f"  tremolo {mem} {cond:14s} {out[cond].get('f_mean_hz', 0):5.2f} Hz, jitter {out[cond].get('jitter_cents', float('nan')):7.1f} c, "
            f"longest {out[cond].get('longest_over_median', float('nan')):5.1f}x",
            flush=True,
        )
    return out


def startup() -> dict:
    """The first firing after rest (GE's test: 8 s off), 100 V switched onto R = 4.7 MOhm and the
    220 Hz capacitor from 0 V: the delay a keyed neon voice speaks with. 400 draws per condition."""
    r = 4.7e6
    c = c_for(220.0, r)
    t_det = r * c * math.log(SUPPLY_V / (SUPPLY_V - VB0))  # the ramp's crossing alone
    out = {}
    for cond, (s, _) in CONDITIONS.items():
        rng = rng_for("startup", cond)
        d = []
        for _ in range(400):
            osc = Osc(c, [0.0], [r], s, rng)
            tf, _, _ = osc.fire(0.0, 0.0, -8.0)
            d.append(tf - t_det)
        d = np.array(d)
        out[cond] = {
            q: float(np.percentile(d, p))
            for q, p in (("median_s", 50), ("p90_s", 90), ("p99_s", 99))
        }
        print(
            f"  startup {cond:14s} median {out[cond]['median_s'] * 1e3:9.2f} ms, 90 % {out[cond]['p90_s'] * 1e3:9.2f} ms",
            flush=True,
        )
    return out


def plots(chk, sw):
    fig, ax = plt.subplots(1, 3, figsize=(16, 4.6))
    pct = np.linspace(102, 180, 100)
    for fc, col in (("0", "k"), ("0.1", "C0"), ("0.5", "C1"), ("500", "C2")):
        p = np.array(FIG59[fc])
        ax[0].semilogy(p[:, 0], p[:, 1] * 1e3, "o", color=col, label=f"GE Fig. 5.9, {fc} ft-c")
        ax[0].semilogy(pct, predicted_fig59(float(fc), pct) * 1e3, "-", color=col)
    ax[0].set(
        xlabel="per cent of DC breakdown",
        ylabel="3-sigma ionization time (ms)",
        title="The fit (lines) to GE's 5AB data",
    )
    ax[0].legend(fontsize=7)
    f = [x[0] for x in FIG215]
    ax[1].semilogx(
        f, np.array([x[1] for x in FIG215]) - FIG215[0][1], "ko", label="GE Fig. 2.15 (5AG) Vf"
    )
    ax[1].semilogx(
        f,
        np.array([x[1] for x in chk["fig215_vf"]]) - chk["fig215_vf"][0][1],
        "k-",
        label="model Vf",
    )
    ax[1].semilogx(
        [x[0] for x in FIG217],
        np.array([x[1] for x in FIG217]) - 30,
        "C3o",
        label="GE Fig. 2.17 Vs - 30 V",
    )
    ax[1].semilogx(
        [x[0] for x in chk["fig217_vs"]],
        np.array([x[1] for x in chk["fig217_vs"]]) - 30,
        "C3-",
        label="model Vs - 30 V",
    )
    ax[1].set(xlabel="Hz", ylabel="V re low frequency", title="Lit oscillator vs GE's curves")
    ax[1].legend(fontsize=7)
    for i, f in enumerate(SWEEP_NOTES):
        ax[2].loglog(
            SWEEP_S,
            [max(x.get("jitter_cents", np.nan), 1e-3) for x in sw[False][f]],
            "-o",
            ms=3,
            color=f"C{i}",
            label=f"{f:g} Hz",
        )
        ax[2].loglog(
            SWEEP_S,
            [max(x.get("jitter_cents", np.nan), 1e-3) for x in sw[True][f]],
            "--",
            lw=0.8,
            color=f"C{i}",
        )
    for k, (s, _) in CONDITIONS.items():
        ax[2].axvline(s, color="0.6", lw=0.8)
        ax[2].text(s, 1.5e3, k, rotation=90, fontsize=7, va="top")
    ax[2].set(
        xlabel="external seed electrons per second",
        ylabel="period jitter, rms cents",
        title="Jitter vs the primer (dashed: long memory)",
    )
    ax[2].legend(fontsize=7)
    fig.tight_layout()
    fig.savefig(OUT / "neon_primer.png", dpi=120)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    print("fit:", {k: round(v, 4) if isinstance(v, float) else v for k, v in FIT.items()})
    print("conditions:", {k: f"{v[0]:.3g}/s" for k, v in CONDITIONS.items()})
    chk = check_figures()
    print("check:", chk)
    st = startup()
    sw = {False: sweep(False), True: sweep(True)}
    cache: dict = {}
    mus = {m: music(cache, m == "long") for m in ("short", "long")}
    trem = {m: tremolo(m == "long") for m in ("short", "long")}
    plots(chk, sw)
    (OUT / "summary.json").write_text(
        json.dumps(
            {
                "fit": FIT,
                "conditions": {
                    k: {"seeds_per_s": v[0], "label": v[1]} for k, v in CONDITIONS.items()
                },
                "check": chk,
                "startup": st,
                "sweep": {
                    mem: {
                        str(f): [
                            dict(s=float(s), **x) for s, x in zip(SWEEP_S, sw[t][f], strict=True)
                        ]
                        for f in SWEEP_NOTES
                    }
                    for mem, t in (("short", False), ("long", True))
                },
                "music": mus,
                "tremolo": trem,
            },
            indent=1,
        )
    )


if __name__ == "__main__":
    main()
