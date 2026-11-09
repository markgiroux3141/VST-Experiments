"""CdS photocells lit by a lamp's filament: the Uni-Vibe's four cells around one bulb
(docs/MODULATION_PLAN.md, MD1; data/schematics/univibe/).

A photocell is a device with pins (t, tb, s, ra, rb) and four ports, all relative to rb:
V(t, rb), V(tb, rb), V(s, rb) and V(ra, rb).

- **The light** comes from a lamp (varimu.devices.lamp): pins t and tb sense the lamp's
  thermal node and its reference pin (the lamp's b), V(t, tb) = T - T_amb in kelvin, and draw
  no current. The illuminance on the cell follows Wien's law at the cell's spectral peak
  lambda_e (Wien's approximation to Planck's law is exact to e^-8 there: lambda T ~ 1.6e-3
  m K against c2 = 1.44e-2 m K):

      E(T) = lux * exp(c2 / lambda_e * (1 / T_ref - 1 / T)),

  `lux` the illuminance this cell gets when the filament is at T_ref = 2856 K, the tungsten
  source photocell sheets specify their resistances at (CIE illuminant A). `lux` is per
  instance (the cell's place in the lamp's box), the rest the component's. A filament's
  spectral emissivity at ~570 nm moves < 5% over 2000-2900 K and is left out; so is the
  spread of the cell's response around its peak (it moves lambda_e, a fitted number anyway).
  Below T_FLOOR_K the light is held at its (vanishing) value there: a Newton iterate with
  the thermal node far below ambient is dark.
- **The cell** is the optocoupler's (varimu.devices.opto): its photoconductance g generated
  by the light and lost by recombination through single traps (lifetime tau0) and pairwise
  (kappa),

      dg/dt = a E - g / tau0 - g |g| / kappa,

  so a bright cell answers fast and a darkened one creeps back (the 1 / t tail of pairwise
  recombination, then tau0). The cell conducts G = g_dark + max(g, 0). One state: the trap
  filling that makes a dim cell's turn-on slower than its turn-off (the PDV-P9203's sheet:
  rise 60 ms, fall 25 ms at 10 lux) is not in it.
- **The state node** s carries g as a voltage, `s_unit_s` siemens per volt, on a 1 F capacitor
  from s to rb (the optocoupler's convention): the port's current is -dg/dt / s_unit.

The cell's parameters are fitted per component version (`varimu fit-devices --only PDVP9203`)
to the sheet's figures.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from varimu.devices.triode import num

C2_M_K = 1.438776877e-2  # the second radiation constant h c / k (CODATA 2018, m K)
T_REF_K = 2856.0  # CIE illuminant A: the tungsten source photocell sheets specify lux at
T_FLOOR_K = 100.0  # below this the filament is dark (numerics: no 1 / T blow-up)


@dataclass(frozen=True)
class Photocell:
    name: str
    gen_s_per_s_lux: float  # a: photoconductance generated per second per lux
    tau0_s: float  # single-trap recombination
    kappa_s_s: float  # pairwise recombination: g^2 / kappa
    g_dark_s: float
    lambda_m: float  # the cell's effective wavelength (its spectral peak)
    t_amb_k: float  # the lamp's thermal node's zero (its t_amb_k)
    lux: float = 0.0  # illuminance on this cell with the filament at T_REF_K (per instance)
    s_unit_s: float = 1e-6  # the state node: siemens per volt

    # --- the parts ----------------------------------------------------------------------

    def illuminance(self, dt_k):
        """E (lux) and dE/d(dt_k) at the lamp's thermal node voltage dt_k = T - T_amb."""
        t = np.asarray(dt_k, float) + self.t_amb_k
        c = C2_M_K / self.lambda_m
        tc = np.maximum(t, T_FLOOR_K)
        e = self.lux * np.exp(c * (1.0 / T_REF_K - 1.0 / tc))
        de = np.where(t > T_FLOOR_K, e * c / (tc * tc), 0.0)
        return e, de

    def steady_g(self, lux):
        """The photoconductance a constant illuminance holds."""
        k, t0 = self.kappa_s_s, self.tau0_s
        # a E = g / tau0 + g^2 / kappa
        return 0.5 * k / t0 * (np.sqrt(1.0 + 4.0 * self.gen_s_per_s_lux * lux * t0 * t0 / k) - 1.0)

    def steady_r_ohm(self, lux):
        return 1.0 / (self.g_dark_s + self.steady_g(lux))

    def rate(self, g, lux):
        """dg/dt."""
        return self.gen_s_per_s_lux * lux - g / self.tau0_s - g * np.abs(g) / self.kappa_s_s

    def conductance_response(self, lux: float, g0: float, t_s: np.ndarray) -> np.ndarray:
        """The photoconductance over t_s at a constant illuminance from g0: the Riccati
        equation's closed form."""
        a, t0, k = self.gen_s_per_s_lux * lux, self.tau0_s, self.kappa_s_s
        disc = math.sqrt(1.0 / (t0 * t0) + 4.0 * a / k)
        g1 = 0.5 * k * (-1.0 / t0 + disc)
        g2 = 0.5 * k * (-1.0 / t0 - disc)
        c = (g0 - g1) / (g0 - g2)
        e = c * np.exp(-disc * np.asarray(t_s, float))
        return (g1 - g2 * e) / (1.0 - e)

    def rise_s(self, lux: float, frac: float = 1.0 - math.exp(-1.0)) -> float:
        """From dark, the time the photoconductance takes to reach `frac` of its steady
        value at `lux` (the sheets' rise time: 1 - 1/e)."""
        from scipy.optimize import brentq

        g1 = float(self.steady_g(lux))
        return brentq(lambda t: float(self.conductance_response(lux, 0.0, t)) - frac * g1, 0, 100)

    def fall_s(self, lux: float, frac: float = math.exp(-1.0)) -> float:
        """From steady at `lux`, the time the photoconductance takes to fall to `frac` of it
        in the dark (the sheets' fall time: 1/e)."""
        from scipy.optimize import brentq

        g1 = float(self.steady_g(lux))
        return brentq(lambda t: float(self.conductance_response(0.0, g1, t)) - frac * g1, 0, 100)

    # --- the device ---------------------------------------------------------------------

    def eval(self, v):
        """Port currents i (4,) and Jacobian (4, 4) at the port voltages v = (V(t, rb),
        V(tb, rb), V(s, rb), V(ra, rb))."""
        vt, vtb, u, vr = (float(x) for x in v)
        e, de = (float(x) for x in self.illuminance(vt - vtb))
        su = self.s_unit_s
        g = u * su
        dgdt = self.rate(g, e)
        cond = self.g_dark_s + max(g, 0.0)
        i = np.array([0.0, 0.0, -dgdt / su, cond * vr])
        j = np.zeros((4, 4))
        dgen = self.gen_s_per_s_lux * de / su
        j[2, 0], j[2, 1] = -dgen, dgen
        j[2, 2] = 1.0 / self.tau0_s + 2.0 * abs(g) / self.kappa_s_s
        j[3, 2] = su * vr if g > 0.0 else 0.0
        j[3, 3] = cond
        return i, j

    def currents(self, v):
        return self.eval(v)[0]

    @property
    def subckt_name(self) -> str:
        return "PCELL_" + "".join(c if c.isalnum() else "_" for c in self.name).upper()

    def subckt(self) -> str:
        """SPICE subcircuit with pins (t, tb, s, ra, rb): the illuminance, the state current
        and the cell as B-sources; t and tb only sensed."""
        c = num(C2_M_K / self.lambda_m)
        tk = f"max(V(t,tb)+{num(self.t_amb_k)},{num(T_FLOOR_K)})"
        e = f"({num(self.lux)}*exp({c}*({num(1.0 / T_REF_K)}-1/{tk})))"
        su = num(self.s_unit_s)
        g = f"(V(s,rb)*{su})"
        rate = (
            f"({num(self.gen_s_per_s_lux)}*{e}-{g}/{num(self.tau0_s)}"
            f"-{g}*abs({g})/{num(self.kappa_s_s)})"
        )
        return (
            f"* {self.name}: generated by varimu.devices.photocell\n"
            f".subckt {self.subckt_name} t tb s ra rb\n"
            f"Bs s rb I={{-{rate}/{su}}}\n"
            f"Bcell ra rb I={{({num(self.g_dark_s)}+max({g},0))*V(ra,rb)}}\n"
            f".ends {self.subckt_name}\n"
        )


def photocell_from_data(d: dict, ref: str) -> Photocell:
    """A photocell component version's model (its `lux` 0: an instance sets its own)."""
    cell, light = d["cell"], d["light"]
    return Photocell(
        d["name"],
        cell["gen_s_per_s_lux"],
        cell["tau0_s"],
        cell["kappa_s_s"],
        cell["g_dark_s"],
        light["lambda_m"],
        light["t_amb_k"],
        s_unit_s=float(d["state"]["s_unit_s"]),
    )


# --- the fit (varimu fit-devices --only PDVP9203) -----------------------------------------------

# Advanced Photonix's PDV-P9203 sheet (DS PDV-P9203 Rev. A, via Laser Components, 03/25;
# data/datasheets/photocell/advanced_photonix_pdv_p9203.pdf), "Typical Electro-Optical
# Specifications at TA = 23 C".
P9203 = {
    "r10_min_ohm": 10e3,  # Illuminated Resistance, 10 Lux @ 2856 K: 10 (min) - 30 (max) kOhm
    "r10_max_ohm": 30e3,
    "sensitivity": 0.90,  # (log R100 - log R10) / (log E100 - log E10), typ., magnitude
    "peak_m": 570e-9,  # Spectral Peak, typ.
    "rise_s": 60e-3,  # Rise Time, 10 Lux @ 2856 K, typ.
    "fall_s": 25e-3,  # Fall Time, after 10 Lux @ 2856 K, typ.
    "dark_ohm": 5e6,  # Dark Resistance, after 10 s @ 10 Lux @ 2856 K, min.
}
SHEET = (
    "data/datasheets/photocell/advanced_photonix_pdv_p9203.pdf (Advanced Photonix PDV-P9203, "
    "DS PDV-P9203 Rev. A, Typical Electro-Optical Specifications at 23 C)"
)


def fit_pdvp9203() -> dict:
    """The PDV-P9203's cell fitted to its sheet: a, tau0 and kappa by least squares in log
    over the resistance at 10 lux (the geometric middle of its 10-30 kOhm range), the
    sensitivity's resistance at 100 lux, and the rise and fall times (the sheets' 1 - 1/e and
    1/e of the photoconductance: PerkinElmer's photocell definitions, which Advanced
    Photonix's line inherits); g_dark the sheet's dark resistance (5 MOhm min. at 10 s)."""
    from scipy import optimize

    s = P9203
    r10 = math.sqrt(s["r10_min_ohm"] * s["r10_max_ohm"])
    r100 = r10 * 10.0 ** (-s["sensitivity"])
    g_dark = 1.0 / s["dark_ohm"]

    def model(p):
        a, t0, k = np.exp(p)
        return Photocell("PDVP9203", a, t0, k, g_dark, s["peak_m"], 300.0)

    def resid(p):
        m = model(p)
        return np.array(
            [
                math.log(float(m.steady_r_ohm(10.0)) / r10),
                math.log(float(m.steady_r_ohm(100.0)) / r100),
                math.log(m.rise_s(10.0) / s["rise_s"]),
                math.log(m.fall_s(10.0) / s["fall_s"]),
            ]
        )

    best = None
    with np.errstate(all="ignore"):
        for t0 in (1e-2, 4e-2, 1e-1):
            for k in (1e-6, 1e-5, 1e-4, 1e-3):
                g0 = 1.0 / r10
                try:
                    sol = optimize.least_squares(
                        resid, np.log([g0 / t0 / 10.0, t0, k]), method="lm", max_nfev=4000
                    )
                except (ValueError, FloatingPointError):
                    continue
                if np.all(np.isfinite(sol.fun)) and (best is None or sol.cost < best.cost):
                    best = sol
    m = model(best.x)
    a, t0, k = (float(x) for x in np.exp(best.x))
    return {
        "name": "PDVP9203",
        "kind": "photocell",
        "source": f"fitted (varimu.devices.photocell.fit_pdvp9203) to {SHEET}. Standing in for "
        "the Uni-Vibe's photocells (a custom Japanese CdS part with no cross-reference: "
        "data/schematics/univibe/README.md), as Aion FX's Straylight specifies: provisional",
        "cell": {
            "gen_s_per_s_lux": a,
            "tau0_s": t0,
            "kappa_s_s": k,
            "g_dark_s": g_dark,
            "source": "least squares in log over the sheet's resistance at 10 lux (the geometric "
            "middle of 10-30 kOhm, 17.3 kOhm), at 100 lux by its sensitivity (0.90), and its rise "
            "(60 ms) and fall (25 ms) times read as the photoconductance's 1 - 1/e and 1/e "
            "(provisional: model knowledge, PerkinElmer's photocell application notes' "
            "definitions); g_dark_s the sheet's dark resistance (5 MOhm min. after 10 s)",
        },
        "light": {
            "lambda_m": s["peak_m"],
            "t_amb_k": 300.0,
            "source": "lambda_m the sheet's spectral peak (570 nm), the wavelength the lamp's "
            "light is weighed at (Wien's law, varimu.devices.photocell); t_amb_k the lamp's "
            "thermal node's zero (config/components/lamp327/1.yaml's t_amb_k, 300 K)",
        },
        "state": {
            "s_unit_s": 1e-6,
            "source": "numerics: the state node's siemens per volt (VTL5C2@2's: the cell's "
            "conductance well above a live draft's Newton tolerance); the dynamics don't "
            "depend on it",
        },
        "fit": {
            "r10_ohm": round(float(m.steady_r_ohm(10.0)), 1),
            "r100_ohm": round(float(m.steady_r_ohm(100.0)), 1),
            "rise_s": round(m.rise_s(10.0), 5),
            "fall_s": round(m.fall_s(10.0), 5),
            "source": "the fitted model's figures against the sheet's 17.3 kOhm, "
            f"{r100:.0f} ohm, 60 ms, 25 ms (one state: a turn-on slower than the turn-off "
            "isn't in it, so the two times are a compromise)",
        },
    }
