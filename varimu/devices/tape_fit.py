"""Fitting a tape formulation's Preisach ensemble (docs/TAPE_PLAN.md, TM1).

**Scotch 111** (Type B coating, #111 4RBA): the remanence after symmetric loops against
their peak field (3M Sound Talk No. 20, data/datasheets/scotch_111_remanence.csv) and the
coercivity (Eilers' table, data/datasheets/published_points.yaml SCOTCH111).

- Bulletin 20's curve is the model's state after [+Hp, -Hp, +Hp, -Hp, +Hp, 0] (the
  60 cycle meter's loop, read on its descending branch at H = 0), scaled so the
  saturated remanence is the curve's top.
- Alone it fits within its reading error for any interaction spread sigma_Hi from about
  20 to 150 Oe: sigma_Hi trades off against the median switching field.
- The major loop's coercivity breaks the tie (+-10%, as the bulletins give samples).
- sigma_Hi then sets the anhysteretic susceptibility, which No. 21's bias curves measure
  (TM2's independent check).

The saturation magnetization follows from the fitted saturation remanence, the curve's
top flux per width and the coating's thickness: Ms = Phi_rs / (mu0 delta S).

With an orientation (`varimu.devices.tape.Orientation`, the vector Preisach model), the
bulletin's B-H meter measures the x component of the ensemble driven along x: each
direction sees H cos(phi) and contributes cos(phi) of its state (`along_x`).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from varimu.devices.preisach import OE_A_PER_M, Preisach, PreisachParams

MU0 = 4e-7 * math.pi
H_MAX_A_M = 2000.0 * OE_A_PER_M  # the tables' range: past every field a machine applies
SIGMA_PHI_WB_PER_M = 0.01e-8 / 6.35e-3  # Bulletin 20's reading error, 0.01 lines per 1/4"


def along_x(pre: Preisach, h: np.ndarray, orientation=None) -> np.ndarray:
    """M_x / Ms after field histories along x (rows of h): the scalar model, or each
    easy-axis direction driven by H cos(phi) contributing cos(phi) of its state."""
    h = np.atleast_2d(np.asarray(h, float))
    if orientation is None:
        return pre.state_after(h)
    cs, _, wt = orientation.axes()
    return sum(w * c * pre.state_after(h * c) for c, w in zip(cs, wt, strict=True))


def symmetric_remanence(pre: Preisach, h_peak: np.ndarray, orientation=None) -> np.ndarray:
    """M / Ms at H = 0 on the descending branch of the symmetric loop to +-h_peak."""
    h = np.asarray(h_peak, float)
    hist = np.stack([h, -h, h, -h, h, np.zeros_like(h)], axis=1)
    return along_x(pre, hist, orientation)


def saturation_remanence(pre: Preisach, orientation=None) -> float:
    """M / Ms at H = 0 after saturation."""
    return float(along_x(pre, np.array([[2.0 * pre.p.h_max_a_m, 0.0]]), orientation)[0])


def loop_coercivity(pre: Preisach, orientation=None) -> float:
    """The major loop's coercivity (A/m): where its descending branch crosses M = 0."""
    lo, hi = 0.0, pre.p.h_max_a_m
    sat = 2.0 * pre.p.h_max_a_m
    for _ in range(50):
        mid = 0.5 * (lo + hi)
        m = along_x(pre, np.array([[sat, -mid]]), orientation)[0]
        lo, hi = (mid, hi) if m > 0 else (lo, mid)
    return 0.5 * (lo + hi)


@dataclass(frozen=True)
class TapeFit:
    params: PreisachParams
    ms_a_m: float
    saturation_remanence: float
    coercivity_a_m: float
    rms_sigma: float  # the remanence curve's residuals, in reading errors
    max_abs_wb_per_m: float


def fit_preisach(
    h_peak: np.ndarray,
    phi_r: np.ndarray,
    coercivity_a_m: float,
    coating_m: float,
    n_table: int = 1024,
    orientation=None,
) -> TapeFit:
    """The ensemble that gives the remanence curve (h_peak A/m, phi_r Wb/m per track width)
    and the coercivity (+-10%) on a coating coating_m thick."""
    from scipy.optimize import least_squares

    h_peak, phi_r = np.asarray(h_peak, float), np.asarray(phi_r, float)
    top = float(phi_r.max())

    def pre_of(x, n=512):
        return Preisach(PreisachParams(x[0], x[1], x[2], H_MAX_A_M, n_table=n))

    def resid(x):
        pre = pre_of(x)
        sat = saturation_remanence(pre, orientation)
        r_curve = (
            symmetric_remanence(pre, h_peak, orientation) * top / sat - phi_r
        ) / SIGMA_PHI_WB_PER_M
        r_hc = (loop_coercivity(pre, orientation) - coercivity_a_m) / (0.1 * coercivity_a_m)
        return np.r_[r_curve, r_hc]

    x0 = [1.1 * coercivity_a_m, 0.3, 0.3 * coercivity_a_m]
    lo = [0.3 * coercivity_a_m, 0.03, 0.01 * coercivity_a_m]
    hi = [3.0 * coercivity_a_m, 1.0, 2.0 * coercivity_a_m]
    r = least_squares(resid, x0, bounds=(lo, hi), x_scale=[coercivity_a_m, 0.1, coercivity_a_m])
    params = PreisachParams(*(float(v) for v in r.x), H_MAX_A_M, n_table=n_table)
    pre = Preisach(params)
    sat = saturation_remanence(pre, orientation)
    curve = symmetric_remanence(pre, h_peak, orientation) * top / sat
    return TapeFit(
        params=params,
        ms_a_m=top / (MU0 * coating_m * sat),
        saturation_remanence=sat,
        coercivity_a_m=loop_coercivity(pre, orientation),
        rms_sigma=float(np.sqrt(np.mean(((curve - phi_r) / SIGMA_PHI_WB_PER_M) ** 2))),
        max_abs_wb_per_m=float(np.abs(curve - phi_r).max()),
    )


def plot_fit(
    pre: Preisach,
    ms_a_m: float,
    coating_m: float,
    h_peak: np.ndarray,
    phi_r: np.ndarray,
    coercivity_a_m: float,
    path: Path,
    title: str,
    orientation=None,
) -> Path:
    """The fit against Bulletin 20's curve, the major loop and the anhysteretic remanence."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    scale = MU0 * ms_a_m * coating_m  # Wb/m per unit M / Ms
    fig, ax = plt.subplots(1, 3, figsize=(15, 4.6))
    hp = np.linspace(0.0, 900.0, 181) * OE_A_PER_M
    lines = 1e-8 / 6.35e-3
    ax[0].plot(
        hp / OE_A_PER_M, symmetric_remanence(pre, hp, orientation) * scale / lines, label="model"
    )
    ax[0].plot(h_peak / OE_A_PER_M, phi_r / lines, "o", label="Sound Talk No. 20, Type B")
    ax[0].set(
        xlabel="peak field (Oe)",
        ylabel='remanent flux (lines per 1/4")',
        title="remanence after symmetric loops",
    )
    ax[0].legend()
    h = np.linspace(-1000.0, 1000.0, 401) * OE_A_PER_M
    sat = 2.0 * pre.p.h_max_a_m
    asc = along_x(pre, np.stack([np.full_like(h, -sat), h], axis=1), orientation)
    desc = along_x(pre, np.stack([np.full_like(h, sat), h], axis=1), orientation)
    ax[1].plot(h / OE_A_PER_M, asc, "C0")
    ax[1].plot(h / OE_A_PER_M, desc, "C0")
    for k in (-1, 1):
        ax[1].axvline(k * coercivity_a_m / OE_A_PER_M, color="C1", ls=":", lw=1)
    ax[1].set(
        xlabel="H (Oe)",
        ylabel="M_x / Ms (irreversible part)",
        title="major loop (dotted: Eilers' Hc, 270 Oe)",
    )
    ha = np.linspace(-150.0, 150.0, 61) * OE_A_PER_M
    ax[2].plot(ha / OE_A_PER_M, pre.anhysteretic_remanence(ha, cycles=1024))
    ax[2].set(xlabel="steady field (Oe)", ylabel="M / Ms", title="anhysteretic remanence")
    for a in ax:
        a.grid(alpha=0.3)
    fig.suptitle(title)
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=110)
    plt.close(fig)
    return path
