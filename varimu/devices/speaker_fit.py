"""Fitting a speaker component to its datasheet (component editor C3): `varimu
fit-devices --only P12R`.

Inputs: the sheet's Thiele-Small figures (data/datasheets/published_points.yaml) and its
two curves, digitized from the PDF's vector paths (data/datasheets/jensen_p12r.provenance
.yaml): the on-axis response on the IEC baffle at 2.83 V, 1 m, and the free-air impedance,
drawn on the same dB axis without an ohm scale (`trace = z0 + kz 20 log10 |Z|`, kz and z0
fitted: the shape is what it gives).

Fitted: the voice coil's Le, L2, R2 and eight breakup modes (each mode's mass, frequency,
Q and signed radiating area), with the moving system fixed to the sheet's figures (Mms,
Cms, BL, Sd; Rms from Fs, Mms and Qms), so Re, Fs and Qts hold by construction. Also
fitted, and reported but never used in a circuit: the response's level offset (the sheet's
level against the model's physics at 2.83 V) and the impedance trace's kz, z0.

The model is the circuit's own: the elements `varimu.circuit.parts.speaker` makes, solved
by `varimu.circuit.ac` (the driver once per evaluation, current-driven, which gives the
impedance and the velocities at once; the readout's back path once, since it doesn't depend
on any fitted value: exact by superposition, the readout being driven one way).
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from functools import cache
from pathlib import Path
from typing import Any

import numpy as np
from scipy.optimize import least_squares

from varimu.circuit import ac, parts
from varimu.circuit.ir import GROUND, Inductor, Resistor, Vccs
from varimu.devices import speaker as spk

# The response's band printed on the page: the sheet's plot is clipped at the page's
# edge, while its vector paths run on to 20 kHz (jensen_p12r.provenance.yaml).
VISIBLE_MAX_HZ = 8527.0
HIDDEN_WEIGHT = 0.3  # the clipped part: data, but nobody saw it on the sheet
DRIVE_V_RMS = 2.83  # "1W" into the nominal 8 ohm, the sheet's response
MODE_STARTS_HZ = (400.0, 800.0, 1300.0, 2000.0, 3000.0, 4500.0, 7000.0, 12000.0)
MODE_MIN_HZ = 300.0  # paper cones break up above a few hundred Hz; lower "modes" would
#                      fit the IEC baffle's own response, which the cabinet doesn't share
MODE_MIN_KG = 0.05e-3
MODE_Q = (0.7, 10.0)  # the curve's points are ~1/12 octave apart: a narrower mode is
#                      unconstrained by them (and rings as a tone the sheet doesn't show)
MODES_MAX_MASS_SHARE = 0.9  # the rigid part (coil, former, inner cone) keeps a tenth


@dataclass(frozen=True)
class Curves:
    response_hz: np.ndarray
    response_db: np.ndarray
    impedance_hz: np.ndarray
    impedance_trace: np.ndarray


@dataclass(frozen=True)
class Fit:
    speaker: spk.Speaker
    level_db: float
    kz: float
    z0: float
    report: dict[str, Any]


def base_speaker(ts: Mapping[str, float], name: str) -> spk.Speaker:
    """The sheet's moving system and voice coil (Le from the sheet), no modes."""
    rms = 2 * math.pi * ts["fs_hz"] * ts["mms_kg"] / ts["qms"]
    return spk.Speaker(
        name=name,
        re_ohm=ts["re_ohm"],
        le_h=ts["le_h_1khz"],
        l2_h=1e-3,
        r2_ohm=10.0,
        mms_kg=ts["mms_kg"],
        cms_m_per_n=ts["cms_m_per_n"],
        rms_ns_per_m=rms,
        bl_tm=ts["bl_tm"],
        sd_m2=ts["sd_m2"],
        modes=(),
    )


@cache
def _back_transfer(
    sd_m2: float, cabinet: spk.Cabinet, distance_m: float, f_key: tuple
) -> np.ndarray:
    """out / p_front of the readout's back path (its front sources and their inductor
    replaced by a 1 ohm load on p_front, driven with 1 A: p_front = 1 V)."""
    s = spk.Speaker("x", 1.0, 1e-3, 1e-3, 1.0, 1e-3, 1e-3, 1.0, 1.0, sd_m2, ())
    els = parts.speaker_readout("S", GROUND, "out", s, [("s_m", 1.0)], cabinet, distance_m)
    pf = "s_pf"
    els = [e for e in els if not (isinstance(e, Vccs) and e.neg == pf)]
    els = [e for e in els if not (isinstance(e, Inductor) and pf in (e.a, e.b))]
    els.append(Resistor("RPF", pf, GROUND, 1.0))
    return ac.solve(els, np.array(f_key), (pf, GROUND), ["out"])["out"]


def response(
    s: spk.Speaker, cabinet: spk.Cabinet, distance_m: float, freqs_hz: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """(pressure at the listening point in Pa per volt at the terminals, impedance in
    ohm), complex, from the circuit's elements."""
    f = np.asarray(freqs_hz, float)
    drv, radiating = parts.speaker_driver("S", "plus", GROUND, s)
    v = ac.solve(drv, f, ("plus", GROUND), ["plus", *(n for n, _ in radiating)])
    z = v["plus"]
    ro = parts.speaker_readout("S", GROUND, "out", s, radiating, cabinet, distance_m)
    front = [e for e in ro if isinstance(e, Vccs) and e.neg == "s_pf"]
    l_pf = next(e.l_h for e in ro if isinstance(e, Inductor) and e.name == "LS_pf")
    jw = 2j * np.pi * f
    p_front = jw * l_pf * sum(g.gm_s * v[g.ctrl_pos] for g in front) / z
    return p_front * _back_transfer(s.sd_m2, cabinet, distance_m, tuple(f)), z


def impedance(s: spk.Speaker, freqs_hz: np.ndarray) -> np.ndarray:
    """The speaker's electrical impedance (ohm, complex): the driver's elements alone (the
    readout draws nothing)."""
    drv, _ = parts.speaker_driver("S", "plus", GROUND, s)
    return ac.solve(drv, np.asarray(freqs_hz, float), ("plus", GROUND), ["plus"])["plus"]


def spl_db(p_per_v: np.ndarray, v_rms: float = DRIVE_V_RMS) -> np.ndarray:
    return 20 * np.log10(np.abs(p_per_v) * v_rms / spk.P_REF_PA)


def impedance_figures(s: spk.Speaker) -> dict[str, float]:
    """Re, Fs, Zmax, Qms, Qes, Qts read off the model's impedance curve the way they are
    measured (Small: the peak, and f1, f2 where |Z| = sqrt(Re Zmax))."""
    f = np.geomspace(20.0, 400.0, 20001)
    mag = np.abs(impedance(s, f))
    i = int(np.argmax(mag))
    re = float(abs(impedance(s, np.array([1e-3]))[0]))
    zmax = float(mag[i])
    r0 = zmax / re
    z12 = math.sqrt(re * zmax)
    f1 = float(np.interp(z12, mag[: i + 1], f[: i + 1]))
    f2 = float(np.interp(z12, mag[i:][::-1], f[i:][::-1]))
    fs = math.sqrt(f1 * f2)
    qms = fs * math.sqrt(r0) / (f2 - f1)
    qes = qms / (r0 - 1)
    return {
        "re_ohm": re,
        "fs_hz": fs,
        "fs_peak_hz": float(f[i]),
        "zmax_ohm": zmax,
        "qms": qms,
        "qes": qes,
        "qts": qms * qes / (qms + qes),
    }


def _speaker(x: Sequence[float], base: spk.Speaker) -> spk.Speaker:
    modes = tuple(
        spk.Mode(
            float(x[6 + 4 * k]) * base.mms_kg,
            float(x[7 + 4 * k]),
            float(x[8 + 4 * k]),
            float(x[9 + 4 * k]) * base.sd_m2,
        )
        for k in range((len(x) - 6) // 4)
    )
    return replace(base, le_h=float(x[0]), l2_h=float(x[1]), r2_ohm=float(x[2]), modes=modes)


def fit(ts: Mapping[str, float], curves: Curves, name: str) -> Fit:
    base = base_speaker(ts, name)
    fr, dr = curves.response_hz, curves.response_db
    fz, dz = curves.impedance_hz, curves.impedance_trace
    f = np.union1d(fr, fz)
    ir_, iz = np.searchsorted(f, fr), np.searchsorted(f, fz)
    w = np.where(fr <= VISIBLE_MAX_HZ, 1.0, HIDDEN_WEIGHT)

    x0 = [
        base.le_h * 0.6,
        1e-3,
        10.0,
        0.0,
        1.25,
        float(np.min(dz)) - 1.25 * 20 * math.log10(base.re_ohm),
    ]
    lo = [0.0, 1e-5, 0.5, -4.0, 1.0, 0.0]
    hi = [1e-3, 5e-3, 100.0, 4.0, 1.6, 100.0]
    for fk in MODE_STARTS_HZ:
        x0 += [0.05, fk, 3.0, 0.05]
        lo += [MODE_MIN_KG / base.mms_kg, MODE_MIN_HZ, MODE_Q[0], -1.0]
        hi += [0.6, 20000.0, MODE_Q[1], 1.0]

    def model(x):
        p, z = response(_speaker(x, base), spk.IEC_BAFFLE, 1.0, f)
        return spl_db(p)[ir_] + x[3], x[5] + x[4] * 20 * np.log10(np.abs(z))[iz]

    def resid(x):
        r, t = model(x)
        excess = sum(x[6 + 4 * k] for k in range(len(MODE_STARTS_HZ))) - MODES_MAX_MASS_SHARE
        return np.concatenate([(r - dr) * w, t - dz, [100.0 * max(0.0, excess)]])

    sol = least_squares(resid, x0, bounds=(lo, hi), x_scale="jac", max_nfev=800)
    s = _speaker(sol.x, base)
    r, t = model(sol.x)
    e, ez = r - dr, t - dz
    vis = fr <= VISIBLE_MAX_HZ
    bounded = [
        i for i in range(6, len(sol.x))
        if min(sol.x[i] - lo[i], hi[i] - sol.x[i]) <= 1e-6 * max(1.0, abs(hi[i]))
    ]  # fmt: skip
    report = {
        "response_db": {
            "rms_visible": float(np.sqrt(np.mean(e[vis] ** 2))),
            "max_visible": float(np.max(np.abs(e[vis]))),
            "rms_beyond_page": float(np.sqrt(np.mean(e[~vis] ** 2))),
            "visible_band_hz": [float(fr[vis][0]), VISIBLE_MAX_HZ],
        },
        "impedance_trace": {
            "rms": float(np.sqrt(np.mean(ez**2))),
            "max": float(np.max(np.abs(ez))),
        },
        "impedance": impedance_figures(s),
        "level_offset_db": float(sol.x[3]),
        "impedance_axis": {"kz": float(sol.x[4]), "z0": float(sol.x[5])},
        "mode_parameters_at_bounds": len(bounded),
        "rigid_part": {
            "mass_kg": s.mms_kg - sum(m.mass_kg for m in s.modes),
            "area_m2": s.sd_m2 - sum(m.area_m2 for m in s.modes),
        },
        "optimizer": {"nfev": int(sol.nfev), "status": int(sol.status)},
    }
    return Fit(s, float(sol.x[3]), float(sol.x[4]), float(sol.x[5]), report)


def load_curves(datasheets: Path, stem: str) -> Curves:
    r = np.loadtxt(datasheets / f"{stem}_response.csv", delimiter=",", skiprows=1)
    z = np.loadtxt(datasheets / f"{stem}_impedance.csv", delimiter=",", skiprows=1)
    return Curves(r[:, 0], r[:, 1], z[:, 0], z[:, 1])


def plot_fit(
    s: spk.Speaker, curves: Curves, fit_meta: Mapping[str, Any], path: Path, title: str
) -> Path:
    """The review plot: response on the IEC baffle and impedance shape against the sheet,
    the impedance in ohms, and the response in the circuit's cabinet if given."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    f = np.geomspace(20.0, 20000.0, 800)
    p, z = response(s, spk.IEC_BAFFLE, 1.0, f)
    fig, ax = plt.subplots(3, 1, figsize=(11, 12), sharex=True)
    ax[0].semilogx(
        f, spl_db(p) + fit_meta["level_offset_db"], "C3", label="model (IEC baffle, 1 m)"
    )
    ax[0].semilogx(curves.response_hz, curves.response_db, "k.", ms=4, label="sheet")
    ax[0].set_ylabel("dB SPL at 2.83 V, 1 m")
    kz, z0 = fit_meta["impedance_axis"]["kz"], fit_meta["impedance_axis"]["z0"]
    ax[1].semilogx(f, z0 + kz * 20 * np.log10(np.abs(z)), "C0", label="model")
    ax[1].semilogx(curves.impedance_hz, curves.impedance_trace, "k.", ms=4, label="sheet (trace)")
    ax[1].set_ylabel("impedance trace (plot units)")
    ax[2].loglog(f, np.abs(z), "C0")
    ax[2].set_ylabel("|Z| (ohm)")
    ax[2].set_xlabel("Hz")
    for a in ax:
        a.axvline(VISIBLE_MAX_HZ, color="k", lw=0.5, ls=":")
        a.grid(which="both", alpha=0.3)
        a.legend(loc="lower center") if a is not ax[2] else None
    fig.suptitle(title)
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=100)
    plt.close(fig)
    return path
