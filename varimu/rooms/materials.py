"""Wall treatments from their physics (MIC_ROOM_PLAN.md A5's "materials from physics"): a
surface's absorption computed from its construction, not looked up.

Every treatment here is a locally reacting surface impedance Z_s(f) (the project's e^{jwt},
outgoing e^{-jkx}); a plane wave at angle t from the normal reflects with R = (Z_s cos t - rho c)
/ (Z_s cos t + rho c), and the random-incidence absorption is Paris' average of 1 - |R|^2 over
the half space (the wave solver's mapping, varimu.rooms.wave, the other way round). Averaged
over each octave band (log-spaced points) it is the material's row in ROOM_MATERIALS.

- **Porous layers** (mineral wool, fibreglass, foam) from their flow resistivity sigma: Miki's
  regression of Delany and Bazley's measurements ("Acoustical properties of porous materials:
  modifications of Delany-Bazley models", J. Acoust. Soc. Jpn (E) 11(1), 1990), valid for
  0.01 < f / sigma < 1: characteristic impedance Z_c = rho c (1 + 0.070 X^-0.632 - j 0.107
  X^-0.632) and wavenumber k_c = (w / c)(1 + 0.109 X^-0.618 - j 0.160 X^-0.618), X = f / sigma.
  A layer d thick on a rigid wall: Z_s = -j Z_c cot(k_c d); over an air gap D: the gap's -j rho
  c cot(k D) carried through the layer (Z_in = Z_c (Z_L + j Z_c tan k_c d) / (Z_c + j Z_L tan
  k_c d)), the gap partitioned (locally reacting).
- **Panel absorbers** (a membrane, a plywood or gypsum panel over a cavity): Z_s = j w m + r +
  Z_cavity, m the panel's mass per area, r its loss, the cavity empty or filled with a porous
  layer: a resonance near 60 / sqrt(m D) Hz (m in kg/m^2, D in m), the classic bass trap.

Flow resistivities, masses and losses are provisional (model knowledge: typical published
values for 30-50 kg/m^3 mineral wool, plywood and gypsum board).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from varimu.separation.room import BANDS_HZ, SPEED_OF_SOUND_M_S

RHO_AIR = 1.204  # kg/m^3 at 20 C
SOURCE = (
    "provisional: model knowledge (flow resistivity of 30-50 kg/m^3 mineral wool ~8-20 kPa s/m^2; "
    "12.5 mm gypsum board ~10 kg/m^2, 12 mm plywood ~7 kg/m^2; panel losses ~0.1-0.3 rho c), "
    "the models: Miki 1990 (porous), the mass-spring panel"
)


def miki(f_hz, sigma: float) -> tuple[np.ndarray, np.ndarray]:
    """A porous material's characteristic impedance and wavenumber (Miki 1990)."""
    f = np.asarray(f_hz, float)
    x = np.maximum(f, 1e-3) / sigma
    zc = RHO_AIR * SPEED_OF_SOUND_M_S * (1 + 0.070 * x**-0.632 - 1j * 0.107 * x**-0.632)
    kc = 2 * np.pi * f / SPEED_OF_SOUND_M_S * (1 + 0.109 * x**-0.618 - 1j * 0.160 * x**-0.618)
    return zc, kc


def _through(zc, kc, d, z_load):
    """An impedance seen through a layer (characteristic impedance zc, wavenumber kc, d thick)
    in front of z_load (None: rigid)."""
    t = np.tan(kc * d)
    if z_load is None:
        return -1j * zc / t
    return zc * (z_load + 1j * zc * t) / (zc + 1j * z_load * t)


@dataclass(frozen=True)
class Porous:
    """A porous layer `thickness_m` thick, flow resistivity `sigma` (Pa s / m^2), on a rigid
    wall or over an air gap `gap_m`."""

    sigma: float
    thickness_m: float
    gap_m: float = 0.0

    def impedance(self, f_hz) -> np.ndarray:
        f = np.asarray(f_hz, float)
        zc, kc = miki(f, self.sigma)
        load = None
        if self.gap_m > 0:
            k0 = 2 * np.pi * np.maximum(f, 1e-3) / SPEED_OF_SOUND_M_S
            load = -1j * RHO_AIR * SPEED_OF_SOUND_M_S / np.tan(k0 * self.gap_m)
        return _through(zc, kc, self.thickness_m, load)


@dataclass(frozen=True)
class Panel:
    """A panel of `mass_kg_m2` per area with loss `loss` (in rho c) over a cavity `cavity_m`
    deep, empty or filled with a porous layer of flow resistivity `fill_sigma`."""

    mass_kg_m2: float
    cavity_m: float
    loss: float = 0.2
    fill_sigma: float | None = None

    def impedance(self, f_hz) -> np.ndarray:
        f = np.maximum(np.asarray(f_hz, float), 1e-3)
        w = 2 * np.pi * f
        rc = RHO_AIR * SPEED_OF_SOUND_M_S
        if self.fill_sigma:
            zc, kc = miki(f, self.fill_sigma)
            cav = _through(zc, kc, self.cavity_m, None)
        else:
            cav = -1j * rc / np.tan(w / SPEED_OF_SOUND_M_S * self.cavity_m)
        return 1j * w * self.mass_kg_m2 + self.loss * rc + cav

    def resonance_hz(self) -> float:
        """The mass on the cavity's air spring (empty cavity, low-frequency limit)."""
        rc2 = RHO_AIR * SPEED_OF_SOUND_M_S**2
        return float(np.sqrt(rc2 / (self.mass_kg_m2 * self.cavity_m)) / (2 * np.pi))


def absorption(z_s: np.ndarray, angles: int = 181) -> np.ndarray:
    """Random-incidence absorption of a locally reacting surface impedance (Paris)."""
    th = np.linspace(0, np.pi / 2, angles)
    c = np.cos(th)[None, :]
    rc = RHO_AIR * SPEED_OF_SOUND_M_S
    z = np.atleast_1d(z_s)[:, None]
    r = (z * c - rc) / (z * c + rc)
    a = 1 - np.abs(r) ** 2
    return np.trapezoid(a * np.sin(2 * th)[None, :], th, axis=1)


def normal_absorption(z_s: np.ndarray) -> np.ndarray:
    rc = RHO_AIR * SPEED_OF_SOUND_M_S
    r = (np.asarray(z_s) - rc) / (np.asarray(z_s) + rc)
    return 1 - np.abs(r) ** 2


def band_absorption(model) -> tuple[float, ...]:
    """A treatment's random-incidence absorption per octave band (BANDS_HZ), each the mean over
    15 log-spaced points across its octave; the lowest band over the octave below it too (it
    stands for every frequency under 125 Hz in the rooms' band weights: a bass trap tuned to
    ~60 Hz shows there)."""
    out = []
    for b, fc in enumerate(BANDS_HZ):
        lo = fc / (2 * np.sqrt(2)) if b == 0 else fc / np.sqrt(2)
        f = np.geomspace(lo, fc * np.sqrt(2), 15 if b else 25)
        out.append(round(float(np.mean(absorption(model.impedance(f)))), 4))
    return tuple(out)


# The treatments offered as materials (ROOM_MATERIALS gets their bands; SCATTERING theirs).
TREATMENTS = {
    "mineral_wool_50mm": Porous(sigma=12_000.0, thickness_m=0.05),
    "mineral_wool_100mm": Porous(sigma=10_000.0, thickness_m=0.10),
    "wool_100mm_gap_100mm": Porous(sigma=10_000.0, thickness_m=0.10, gap_m=0.10),
    "foam_25mm": Porous(sigma=20_000.0, thickness_m=0.025),
    "panel_trap_plywood": Panel(mass_kg_m2=7.0, cavity_m=0.15, loss=0.15, fill_sigma=8_000.0),
}
# (An ordinary stud wall stays the measured `gypsum_on_studs`: as a lightly damped panel on an
# empty cavity it absorbs far less than real walls, whose studs and fixings lose energy.)
TREATMENT_SCATTERING = {
    "mineral_wool_50mm": 0.1,
    "mineral_wool_100mm": 0.1,
    "wool_100mm_gap_100mm": 0.1,
    "foam_25mm": 0.15,
    "panel_trap_plywood": 0.1,
}


def treatment_materials() -> dict[str, tuple[float, ...]]:
    return {name: band_absorption(m) for name, m in TREATMENTS.items()}
