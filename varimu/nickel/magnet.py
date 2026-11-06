"""Nickel: Jiles-Atherton hysteresis with magnetostriction both ways (the Nickel Organ's new
mechanism; docs/NICKEL_ORGAN_PLAN.md).

**The material** is varimu.devices.core's Jiles-Atherton form (the same equations, so a
nickel `MagneticCore` traces the same loops), fitted here to nickel's handbook figures
(`fit`): the initial permeability, the maximum permeability, the coercivity and the
remanence of the major loop (config/nickel/organ.yaml `nickel.datasheet`).

**Magnetostriction** is even in M: lambda(M) = lambda_s (M / Ms)^2 (nickel's lambda_s < 0:
it shortens when magnetized either way). That is why a drive at f pushes at 2f unless a
bias M0 linearizes it: lambda ~ lambda(M0) + lambda'(M0) dM.

**The coupling, from one energy.** The strip (Young's modulus E, volume V) is bonded to the
bar, so its strain eps is the bar's. Its elastic energy is 1/2 E V (eps - lambda(M))^2: the
cross term -E V eps lambda(M) couples the two sides, and nothing else does.

- On the bar: the generalized force on mode k is E V s_k lambda(M), with s_k = d eps / d q_k.
- On the magnet: the stress sigma = E (eps - lambda(M)) adds the field
  H_sigma = (sigma / mu0) lambda'(M) to Jiles-Atherton's effective field (Sablik & Jiles,
  IEEE Trans. Magn. 29(4), 2113 (1993); their 3/2 is inside our lambda, the measured strain
  along the field). This is the Villari effect: tension lowers nickel's magnetization
  (lambda_s < 0) and the coil sees it as an EMF.

Because both come from one energy, the linearized transducer is reciprocal (force per
ampere equals EMF per metre per second, `tests/test_nickel.py`), and at zero bias both
directions vanish to first order: the coil then only pushes at 2f and only hears the bar
mixed with the coil's own magnetization (the parametric loop the first experiment looks
for).

`dm_dhe` is Jiles-Atherton's dM / dHe (no alpha feedback: the caller solves the effective
field's own terms with the circuit's, `varimu.nickel.voice`).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from scipy.optimize import least_squares

from varimu.devices.core import MU0, MagneticCore, dlangevin, langevin


@dataclass(frozen=True)
class Nickel:
    ms: float  # A/m
    a: float
    k: float
    c: float
    alpha: float
    lambda_s: float  # saturation magnetostriction (negative for nickel)

    @property
    def core(self) -> MagneticCore:
        """The same material as varimu.devices.core's device (path 1 m), for loops and fits."""
        return MagneticCore("nickel", self.ms, self.a, self.k, self.c, self.alpha, 1.0)

    def lam(self, m: float) -> float:
        x = m / self.ms
        return self.lambda_s * x * x

    def dlam(self, m: float) -> float:
        return 2.0 * self.lambda_s * m / (self.ms * self.ms)

    @property
    def ddlam(self) -> float:
        return 2.0 * self.lambda_s / (self.ms * self.ms)

    def man(self, he: float) -> float:
        return self.ms * langevin(he / self.a)

    def dm_dhe(self, he: float, m: float, delta: float) -> float:
        """dM / dHe at effective field he, magnetization m, direction delta (core.py's form;
        delta 0: at a reversal, the reversible part alone)."""
        x = he / self.a
        d = self.ms * langevin(x) - m
        chi = self.c * (self.ms / self.a) * dlangevin(x)
        if delta * d > 0:
            chi += abs(d) / self.k
        return chi


def from_spec(nk: dict) -> Nickel:
    ja = nk["ja"]
    return Nickel(
        nk["ms_a_per_m"]["value"],
        ja["a_a_per_m"]["value"],
        ja["k_a_per_m"]["value"],
        ja["c"]["value"],
        ja["alpha"]["value"],
        nk["lambda_s"]["value"],
    )


# --- The fit to the handbook figures ---------------------------------------------------


def figures(core: MagneticCore, h_initial: float) -> dict[str, float]:
    """Initial and maximum permeability of the initial curve, coercivity and remanence of the
    major loop (to 0.97 Js and back)."""
    js = MU0 * core.ms_a_per_m
    b = np.concatenate(
        [np.geomspace(1e-7, 0.05 * js, 300), np.linspace(0.05 * js, 0.9 * js, 300)[1:]]
    )
    h = np.array(core.trace(b))
    ok = h > 0
    mu = b[ok] / (MU0 * h[ok])
    up = np.linspace(0, 0.97 * js, 500)
    down = np.linspace(0.97 * js, -0.97 * js, 1000)[1:]
    hl = np.array(core.trace(np.concatenate([up, down])))[len(up) :]
    k = int(np.argmax(down <= 0))
    hc = -float(np.interp(0.0, down[k - 1 : k + 1][::-1], hl[k - 1 : k + 1][::-1]))
    j = int(np.argmax(hl <= 0))  # where H crosses 0 going down: the remanence
    br = float(np.interp(0.0, hl[j - 1 : j + 1][::-1], down[j - 1 : j + 1][::-1]))
    return {
        "mu_initial": float(np.interp(math.log(h_initial), np.log(h[ok]), mu)),
        "mu_max": float(np.max(mu)),
        "coercivity_a_per_m": hc,
        "remanence_t": br,
    }


def targets(nk: dict) -> tuple[dict[str, float], float]:
    ds = nk["datasheet"]
    want = {k: ds[k]["value"] for k in ("mu_initial", "mu_max", "coercivity_a_per_m")}
    want["remanence_t"] = ds["remanence_t"]["value"]
    return want, ds["h_initial_a_per_m"]["value"]


def fit(nk: dict) -> tuple[Nickel, dict[str, float]]:
    """JA's a, k, c, alpha for nickel's figures (Ms and lambda_s are given)."""
    want, h0 = targets(nk)
    base = from_spec(nk)
    ms = base.ms

    def make(x):
        return Nickel(
            ms,
            math.exp(x[0]),
            math.exp(x[1]),
            1 / (1 + math.exp(-x[2])),
            math.exp(x[3]),
            base.lambda_s,
        )

    def resid(x):
        n = make(x)
        if n.core.validate():
            return np.full(len(want), 10.0)
        got = figures(n.core, h0)
        return np.array([math.log(max(got[k], 1e-9) / want[k]) for k in want])

    x0 = [math.log(560.0), math.log(117.0), math.log(0.26 / 0.74), math.log(3.2e-3)]
    sol = least_squares(resid, x0, diff_step=1e-3, xtol=1e-10, ftol=1e-10)
    best = make(sol.x)
    return best, figures(best.core, h0)
