"""Fit Jiles-Atherton parameters to a material's datasheet figures (config/magnetics.yaml).

    uv run python scripts/fit_core_material.py MATERIAL    # prints the fit; paste it into the file

For materials whose datasheet gives scalars, not loops: a material's
`datasheet:` block in config/magnetics.yaml holds them, and this fits the
four free JA parameters (a, k, c, alpha; Ms is the saturation) to

- mu_initial at h_initial: the initial magnetization curve's B / (mu0 H);
- mu_max: its maximum;
- coercivity of the major loop (driven to near saturation);
- hysteresis loss per cycle at b_loss: the datasheet's total loss per cycle
  minus classical eddy loss in its strip (pi^2 d^2 B^2 f / (6 rho) per cycle);
- optionally the Rayleigh region (`rayleigh_r_per_a_m`, `h_rayleigh_a_per_m`): below
  mu_initial's field the permeability follows Rayleigh's law, mu(H) = mu_i (1 + r H),
  so the initial curve at h_rayleigh is mu_initial (1 + r h_rayleigh) / (1 + r
  h_initial). Without it, the fit is free to put the initial curve's whole rise
  below h_initial (an almost all irreversible JA set: H ~ sqrt(B) at low fields).

tests/test_core.py checks that the stored parameters still meet the targets.
"""

from __future__ import annotations

import argparse
import math

import numpy as np
from scipy.optimize import least_squares

from varimu.devices.core import MU0, MagneticCore, materials


def figures(core: MagneticCore, b_loss: float, h_rayleigh: float | None = None) -> dict[str, float]:
    """The datasheet figures of a JA material (see the module docstring)."""
    js = MU0 * core.ms_a_per_m
    # Initial curve from the demagnetized state, in fine B steps.
    b = np.concatenate(
        [np.geomspace(1e-7, 0.05 * js, 400), np.linspace(0.05 * js, 0.9 * js, 400)[1:]]
    )
    h = np.array(core.trace(b))
    mu = b / (MU0 * np.maximum(h, 1e-30))
    ok = h > 0
    # Major loop to 0.97 Js and back: coercivity where B crosses 0 going down.
    up = np.linspace(0, 0.97 * js, 600)
    down = np.linspace(0.97 * js, -0.97 * js, 1200)[1:]
    hl = np.array(core.trace(np.concatenate([up, down])))[len(up) :]
    k = np.argmax(down <= 0)
    hc = -np.interp(0.0, down[k - 1 : k + 1][::-1], hl[k - 1 : k + 1][::-1])
    # Loss per cycle at b_loss: the third cycle of a sine in B.
    t = np.linspace(0, 3, 3 * 800 + 1)
    bc = b_loss * np.sin(2 * np.pi * t)
    hcyc = np.array(core.trace(bc))
    last = t >= 2
    loss = float(np.trapezoid(hcyc[last], bc[last]))  # oint H dB, J/m^3
    out = {
        "mu_initial": float(np.interp(math.log(0.4), np.log(h[ok]), mu[ok])),
        "mu_max": float(np.max(mu[ok])),
        "coercivity_a_per_m": float(hc),
        "loss_j_per_m3": abs(loss),
    }
    if h_rayleigh is not None:
        out["mu_rayleigh"] = float(np.interp(math.log(h_rayleigh), np.log(h[ok]), mu[ok]))
    return out


def h_rayleigh(name: str) -> float | None:
    return materials()[name]["datasheet"].get("h_rayleigh_a_per_m")


def targets(name: str) -> tuple[dict[str, float], float, float]:
    m = materials()[name]
    ds = m["datasheet"]
    d, rho, f, b = ds["strip_m"], m["resistivity_ohm_m"], ds["loss_hz"], ds["b_loss_t"]
    eddy = math.pi**2 * d**2 * b**2 * f / (6 * rho)  # J/m^3 per cycle
    total = ds["loss_w_per_kg"] / f * ds["density_kg_per_m3"]
    want = {
        "mu_initial": ds["mu_initial"],
        "mu_max": ds["mu_max"],
        "coercivity_a_per_m": ds["coercivity_a_per_m"],
        "loss_j_per_m3": total - eddy,
    }
    if "rayleigh_r_per_a_m" in ds:
        r, h0, hr = ds["rayleigh_r_per_a_m"], ds["h_initial_a_per_m"], ds["h_rayleigh_a_per_m"]
        want["mu_rayleigh"] = ds["mu_initial"] * (1 + r * hr) / (1 + r * h0)
    return want, b, ds["h_initial_a_per_m"]


def fit(name: str) -> MagneticCore:
    m = materials()[name]
    want, b_loss, _ = targets(name)
    ms = m["ms_a_per_m"]

    def core(x):
        a, k, c, alpha = math.exp(x[0]), math.exp(x[1]), 1 / (1 + math.exp(-x[2])), math.exp(x[3])
        return MagneticCore(name, ms, a, k, c, alpha, 0.1)

    def resid(x):
        c = core(x)
        if c.validate():
            return np.full(len(want), 10.0)
        got = figures(c, b_loss, h_rayleigh(name))
        return np.array([math.log(got[k] / want[k]) for k in want])

    # With a Rayleigh region to meet, start from a mostly reversible set: an almost all
    # irreversible start (c ~ 1e-3) sits in a different basin.
    c0 = max(m["c"], 0.2) if "mu_rayleigh" in want else m["c"]
    x0 = np.log([m["a_a_per_m"], m["k_a_per_m"]]).tolist()
    x0 += [math.log(c0 / (1 - c0)), math.log(m["alpha"])]
    sol = least_squares(resid, x0, diff_step=1e-3, xtol=1e-10, ftol=1e-10)
    best = core(sol.x)
    got = figures(best, b_loss, h_rayleigh(name))
    print(f"{name}: a {best.a_a_per_m:.6g}, k {best.k_a_per_m:.6g}, c {best.c:.6g}, "
          f"alpha {best.alpha:.6g}  (Ms {ms:.6g})")  # fmt: skip
    for key in want:
        print(f"  {key:20s} target {want[key]:.4g}  fit {got[key]:.4g}  "
              f"({100 * (got[key] / want[key] - 1):+.1f}%)")  # fmt: skip
    return best


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("material")
    fit(ap.parse_args().material)


if __name__ == "__main__":
    main()
