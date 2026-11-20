"""A Wurlitzer 200A's values (`config/wurlitzer/200a.yaml`) and one key built from them
(docs/WURLITZER_PLAN.md, WZ1).

`load()` reads the file (every value `{value, source}`). `key(n)` builds key n of the 64
(A1 = 1, A4 = 37, C7 = 64; the reed numbers are the keys'):

- the note: equal temperament from A4;
- the reed: its blank's thickness and width (Vintage Vibe's 200A table), the lead's mass a
  ratio of the tongue's (log-linear in the key between the bass's and the treble's), the
  free length solved so the fundamental is the note;
- the reed's own loss: its fundamental's Q from the Pie-finger set's decays (a cubic in log
  f, held at the ends);
- the pickup's section for its blank and the field map (`pickup.field_map`);
- the slot along the reed's outer end, the hammer's strike point;
- the plate's constant capacitance: `plate.fixed_f` plus every reed's standing capacitance
  at its voicing (the 64 reeds share the plate).
"""

from __future__ import annotations

import functools
from dataclasses import dataclass
from typing import Any

import numpy as np
import yaml

from varimu.config import CONFIG_DIR
from varimu.wurlitzer import pickup as pk
from varimu.wurlitzer import reed as rd

WURLITZER_DIR = CONFIG_DIR / "wurlitzer"


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
    if isinstance(v, list):
        return [_number(x) for x in v]
    if isinstance(v, str):
        try:
            return float(v)
        except ValueError:
            return v
    return v


@functools.cache
def load(name: str = "200a") -> dict[str, Any]:
    raw = yaml.safe_load((WURLITZER_DIR / f"{name}.yaml").read_text(encoding="utf-8"))
    return _values(raw, name)


def note_hz(n: int, cfg: dict[str, Any] | None = None) -> float:
    cfg = cfg or load()
    return cfg["tuning"]["a4_hz"] * 2.0 ** ((n - 37) / 12)


def midi_note(n: int) -> int:
    return 32 + n


def blank(n: int, cfg: dict[str, Any]) -> int:
    for i, last in enumerate(cfg["reed"]["blank_last_reed"]):
        if n <= last:
            return i
    raise ValueError(f"key {n}: past the last blank")


def tip_mass_ratio(n: int, cfg: dict[str, Any]) -> float:
    r = cfg["reed"]
    keys = cfg["keyboard"]["keys"]
    t = (n - 1) / (keys - 1)
    return float(
        np.exp((1 - t) * np.log(r["tip_mass_ratio_bass"]) + t * np.log(r["tip_mass_ratio_treble"]))
    )


def q_target(f_hz: float, cfg: dict[str, Any]) -> float:
    pts = np.array(sorted(cfg["anchors"]["q_pie_finger"]), dtype=float)
    lf = float(np.clip(np.log(f_hz), np.log(pts[0, 0]), np.log(pts[-1, 0])))
    c = np.polyfit(np.log(pts[:, 0]), np.log(pts[:, 1]), 3)
    return float(np.exp(np.polyval(c, lf)))


@dataclass(frozen=True)
class Hammer:
    mass_kg: float
    stiffness: float
    exponent: float
    hysteresis_s_m: float
    strike_x_m: float


@dataclass(frozen=True)
class Key:
    n: int
    f_hz: float
    reed: rd.Reed
    hammer: Hammer
    section: pk.Section
    slot_lo_m: float  # the slot's prongs alongside the reed from here ...
    slot_hi_m: float  # ... to here (from the root)
    voicing_m: float
    polarizing_v: float
    feed_ohm: float
    plate_f: float  # the plate's constant capacitance (every reed at rest, the fixed part)
    f_max_hz: float
    full_scale_v: float


def section_for(n: int, cfg: dict[str, Any]) -> pk.Section:
    r, p, num = cfg["reed"], cfg["pickup"], cfg["numerics"]
    b = blank(n, cfg)
    return pk.section(
        r["blank_width_m"][b],
        r["blank_thickness_m"][b],
        p["plate_thickness_m"],
        p["side_gap_m"],
        p["reed_pitch_m"],
        p["shield_distance_m"],
        num["field_cell_m"],
        num["swing_m"],
    )


@functools.cache
def _reed(n: int, name: str) -> rd.Reed:
    cfg = load(name)
    r = cfg["reed"]
    b = blank(n, cfg)
    f = note_hz(n, cfg)
    base = rd.Reed(
        length_m=0.05,
        thickness_m=r["blank_thickness_m"][b],
        width_m=r["blank_width_m"][b],
        youngs_pa=r["youngs_pa"],
        density_kg_m3=r["density_kg_m3"],
        tip_mass_kg=0.0,
        tip_length_m=r["tip_length_m"],
        tip_height_m=r["tip_height_m"],
        loss=1.0 / q_target(f, cfg),
        element_m=cfg["numerics"]["element_m"],
    )
    return rd.tune(base, f, tip_mass_ratio(n, cfg), r["tip_length_m"], r["max_tip_fraction"])


def _slot(reed: rd.Reed, cfg: dict[str, Any]) -> tuple[float, float]:
    p = cfg["pickup"]
    hi = reed.length_m - p["overlap_tip_clearance_m"]
    lo = max(hi - p["overlap_m"], 0.3 * reed.length_m)
    return lo, hi


@functools.cache
def _field(sec: pk.Section) -> pk.FieldMap:
    return pk.field_map(sec)


def standing_f(n: int, name: str = "200a") -> float:
    """Key n's reed at rest: its share of the plate's capacitance (F)."""
    cfg = load(name)
    reed = _reed(n, name)
    lo, hi = _slot(reed, cfg)
    return float(_field(section_for(n, cfg))(np.array([cfg["pickup"]["voicing_m"]]))[0] * (hi - lo))


@functools.cache
def plate_f(name: str = "200a") -> float:
    cfg = load(name)
    return cfg["plate"]["fixed_f"] + sum(
        standing_f(n, name) for n in range(1, cfg["keyboard"]["keys"] + 1)
    )


def key(n: int, name: str = "200a", with_plate: bool = True) -> Key:
    cfg = load(name)
    if not 1 <= n <= cfg["keyboard"]["keys"]:
        raise ValueError(f"key {n}: 1-{cfg['keyboard']['keys']}")
    reed = _reed(n, name)
    lo, hi = _slot(reed, cfg)
    h = cfg["hammer"]
    pl = cfg["plate"]
    strike_x = h["strike_fraction"] * reed.length_m
    return Key(
        n=n,
        f_hz=note_hz(n, cfg),
        reed=reed,
        hammer=Hammer(h["mass_kg"], h["stiffness"], h["exponent"], h["hysteresis_s_m"], strike_x),
        section=section_for(n, cfg),
        slot_lo_m=lo,
        slot_hi_m=hi,
        voicing_m=cfg["pickup"]["voicing_m"],
        polarizing_v=pl["polarizing_v"],
        feed_ohm=pl["feed_ohm"],
        plate_f=plate_f(name) if with_plate else pl["fixed_f"] + standing_f(n, name),
        f_max_hz=cfg["numerics"]["f_max_hz"],
        full_scale_v=cfg["numerics"]["full_scale_v"],
    )


def field(k: Key) -> pk.FieldMap:
    return _field(k.section)
