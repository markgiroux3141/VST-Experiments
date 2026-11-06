"""The D6's values (config/clavinet/d6.yaml) and each key's string, from the closed-form
fits: the plain strings' lengths from [G13]'s measured inharmonicity, the wound strings'
cores likewise (docs/CLAVINET_PLAN.md, CL1).

**Strings.** A stiff string's partials are f_n = n f0 sqrt(1 + B n^2) with
B = pi^2 E I / (T L^2) (I = pi d^4 / 64 of the steel that carries the tension: the whole
plain wire, a wound string's core) and T = mu (2 L f0)^2. With one gauge for keys 24-60,
B = pi^3 E d^4 / (256 mu f0^2 L^4), so [G13] Fig. 6's flat B over the plain strings means
L ~ f0^-1/2; the top key's length is solved from [G13]'s B at E6. The wound strings run
linearly in length from that law at key 23 to the configured bottom length; each wound
type's core diameter is the one whose B best matches [G13]'s measured values on its keys
(least squares in log B).

Tensions, the non-speaking length and the losses are fitted on the string model
(`fit.py`): they need the anvil, the yarn and the tailpiece.
"""

from __future__ import annotations

import functools
from dataclasses import dataclass
from typing import Any

import numpy as np
import yaml
from scipy import optimize

from varimu.config import CONFIG_DIR, REPO_ROOT

CLAVINET_DIR = CONFIG_DIR / "clavinet"
CACHE_DIR = REPO_ROOT / "cache" / "clavinet"


def _values(node: Any, where: str) -> Any:
    """The file's tree with every {value, source} leaf replaced by its value."""
    if isinstance(node, dict) and "value" in node:
        if not node.get("source"):
            raise ValueError(f"{where}: needs a source")
        return _number(node["value"])
    if isinstance(node, dict):
        return {k: _values(v, f"{where}.{k}") for k, v in node.items()}
    raise ValueError(f"{where}: needs {{value, source}}, got {node!r}")


def _number(v: Any) -> Any:
    """YAML 1.1 reads 2.0e11 (no exponent sign) as a string: numbers back to floats."""
    if isinstance(v, list):
        return [_number(x) for x in v]
    if isinstance(v, dict):
        return {k: _number(x) for k, x in v.items()}
    if isinstance(v, str):
        try:
            return float(v)
        except ValueError:
            return v
    return v


@functools.cache
def load(name: str = "d6") -> dict[str, Any]:
    raw = yaml.safe_load((CLAVINET_DIR / f"{name}.yaml").read_text(encoding="utf-8"))
    return _values(raw, name)


def config_text(name: str = "d6") -> str:
    return (CLAVINET_DIR / f"{name}.yaml").read_text(encoding="utf-8")


def midi_note(n: int, cfg: dict[str, Any] | None = None) -> int:
    cfg = cfg or load()
    return int(cfg["tuning"]["first_midi"]) + n - 1


def note_hz(n: int, cfg: dict[str, Any] | None = None) -> float:
    cfg = cfg or load()
    return float(cfg["tuning"]["a4_hz"] * 2.0 ** ((midi_note(n, cfg) - 69) / 12))


def key_of_midi(midi: int, cfg: dict[str, Any] | None = None) -> int | None:
    cfg = cfg or load()
    n = midi - int(cfg["tuning"]["first_midi"]) + 1
    return n if 1 <= n <= int(cfg["tuning"]["keys"]) else None


def stiffness_b(e_pa: float, d_core_m: float, mu_kg_m: float, f_hz: float, l_m: float) -> float:
    """B of a pinned stiff string tuned to f_hz: pi^2 E I / (T L^2), T = mu (2 L f)^2."""
    tension = mu_kg_m * (2 * l_m * f_hz) ** 2
    inertia = np.pi * d_core_m**4 / 64
    return float(np.pi**2 * e_pa * inertia / (tension * l_m**2))


@dataclass(frozen=True)
class StringGeom:
    """A key's string: its note, its speaking length and its cross-section."""

    n: int
    f_hz: float
    wound: bool
    length_m: float  # speaking: anvil to tailpiece
    d_core_m: float  # the steel that carries the tension
    d_outer_m: float  # what the air sees
    mu_kg_m: float
    ei_n_m2: float
    ea_n: float
    d_magnetic_m: float  # the steel the pickup sees (the core, or core and wrap if magnetic)

    @property
    def b_nominal(self) -> float:
        """B at the nominal tension (T = mu (2 L f)^2)."""
        return float(
            self.ei_n_m2
            * np.pi**2
            / (self.mu_kg_m * (2 * self.length_m * self.f_hz) ** 2 * self.length_m**2)
        )


def _plain_mu(cfg: dict[str, Any]) -> float:
    d = cfg["plain"]["diameter_m"]
    return float(cfg["steel"]["density_kg_m3"] * np.pi * d**2 / 4)


def _wound_mu(cfg: dict[str, Any], d_core: float, d_outer: float) -> float:
    w = cfg["wound"]
    core = cfg["steel"]["density_kg_m3"] * np.pi * d_core**2 / 4
    wrap = w["wrap_density_kg_m3"] * w["wrap_fill"] * np.pi * (d_outer**2 - d_core**2) / 4
    return float(core + wrap)


@functools.cache
def _plain_top_length(name: str) -> float:
    """Key 60's speaking length: B(E6) = [G13]'s with the plain gauge."""
    cfg = load(name)
    n_top = int(cfg["tuning"]["keys"])
    d = cfg["plain"]["diameter_m"]
    mu = _plain_mu(cfg)
    f = note_hz(n_top, cfg)
    b = cfg["plain"]["b_top"]
    e = cfg["steel"]["youngs_pa"]
    return float((np.pi**3 * e * d**4 / (256 * mu * f**2 * b)) ** 0.25)


def plain_length(n: int, name: str = "d6") -> float:
    """The plain strings' law, L ~ f^-1/2 through the top key (also continued below)."""
    cfg = load(name)
    n_top = int(cfg["tuning"]["keys"])
    alpha = cfg["plain"]["length_exponent"]
    return _plain_top_length(name) * (note_hz(n, cfg) / note_hz(n_top, cfg)) ** alpha


def speaking_length(n: int, name: str = "d6") -> float:
    cfg = load(name)
    first_plain = int(cfg["plain"]["first_key"])
    if n >= first_plain:
        return plain_length(n, name)
    l_top = plain_length(first_plain - 1, name)
    l_bot = cfg["wound"]["bottom_length_m"]
    frac = (n - 1) / (first_plain - 2)
    return float(l_bot + frac * (l_top - l_bot))


def _wound_type(n: int, cfg: dict[str, Any]) -> int:
    for i, (a, b) in enumerate(cfg["wound"]["types"]):
        if a <= n <= b:
            return i
    raise ValueError(f"key {n} isn't wound")


@functools.cache
def wound_cores(name: str = "d6") -> tuple[float, ...]:
    """Each wound type's core diameter: least squares in log B over [G13]'s anchors."""
    cfg = load(name)
    e = cfg["steel"]["youngs_pa"]
    cores = []
    for i, (a, b) in enumerate(cfg["wound"]["types"]):
        d_out = cfg["wound"]["outer_diameter_m"][i]
        anchors = [(int(k), float(bv)) for k, bv in cfg["wound"]["b_anchors"] if a <= k <= b]
        if not anchors:
            raise ValueError(f"wound type {i}: no B anchor on keys {a}-{b}")

        def err(log_dc: float, anchors=anchors, d_out=d_out) -> float:
            dc = float(np.exp(log_dc))
            s = 0.0
            for k, bv in anchors:
                mu = _wound_mu(cfg, dc, d_out)
                bm = stiffness_b(e, dc, mu, note_hz(k, cfg), speaking_length(k, name))
                s += (np.log(bm) - np.log(bv)) ** 2
            return s

        res = optimize.minimize_scalar(
            err, bounds=(np.log(0.1 * d_out), np.log(0.95 * d_out)), method="bounded"
        )
        cores.append(float(np.exp(res.x)))
    return tuple(cores)


def string(n: int, name: str = "d6") -> StringGeom:
    cfg = load(name)
    e = cfg["steel"]["youngs_pa"]
    f = note_hz(n, cfg)
    length = speaking_length(n, name)
    if n >= int(cfg["plain"]["first_key"]):
        d = cfg["plain"]["diameter_m"]
        mu = _plain_mu(cfg)
        return StringGeom(
            n, f, False, length, d, d, mu, e * np.pi * d**4 / 64, e * np.pi * d**2 / 4, d
        )
    i = _wound_type(n, cfg)
    dc = wound_cores(name)[i]
    d_out = cfg["wound"]["outer_diameter_m"][i]
    mu = _wound_mu(cfg, dc, d_out)
    if cfg["wound"]["wrap_magnetic"]:
        d_mag = float(np.sqrt(dc**2 + cfg["wound"]["wrap_fill"] * (d_out**2 - dc**2)))
    else:
        d_mag = dc
    return StringGeom(
        n, f, True, length, dc, d_out, mu, e * np.pi * dc**4 / 64, e * np.pi * dc**2 / 4, d_mag
    )


def gent_youngs_pa(shore_a: float) -> float:
    """Young's modulus of rubber from its Shore A hardness (Gent 1958)."""
    return 1e6 * 0.0981 * (56 + 7.62336 * shore_a) / (0.137505 * (254 - 2.54 * shore_a))


def tangent_hc(cfg: dict[str, Any]) -> tuple[float, float]:
    """The tangent's rubber tip as a Hertzian contact on the wire: F = K d^1.5 (a sphere
    of the tip's radius on a flat; rubber nearly incompressible, nu = 0.5)."""
    t = cfg["tangent"]
    e_star = gent_youngs_pa(t["rubber_shore_a"]) / (1 - 0.25)
    return float(4.0 / 3.0 * e_star * np.sqrt(t["tip_radius_m"])), 1.5


def velocity_m_s(midi_velocity: int, cfg: dict[str, Any] | None = None) -> float:
    """[G13] 3.2: key velocity linear over its range, MIDI 1-127."""
    cfg = cfg or load()
    lo, hi = cfg["tangent"]["velocity_range_m_s"]
    v = int(np.clip(midi_velocity, 1, 127))
    return float(lo + (hi - lo) * (v - 1) / 126)
