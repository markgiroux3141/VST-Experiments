"""A Rhodes Mark I's values (`config/rhodes/mk1.yaml`) and one key built from them
(docs/RHODES_PLAN.md, RH1).

`load()` reads the file (every value `{value, source}`) and the digitized tine lengths
(`data/datasheets/rhodes_tine_lengths.csv`). `key(n)` builds key n of 88 (A0 = 1, A4 = 49):

- the note: equal temperament from A4;
- the tine: the chart's free length, the tapered root, the tip diameter;
- the tone bar (keys from `tonebar.first_key`): its length balances the fork, the tine's
  fundamental storing the least of its energy in the grommets (the manual: the prongs "are
  alike only in pitch"; Shear: matched legs sustain longer); it starts from the length at
  which the bar alone, clamped, rings at the note;
- the grommets' stiffness: the assembly's lowest mode on its mount (`beam.mount_mode`:
  pitching or bouncing on the grommets) at Muenster & Pfeifle's measured tone bar
  resonance (a log-linear fit over their nine keys; read as the struck bar on its mount:
  well below the note, it can't be the bar's own bending if the bar is "alike in pitch";
  fitting only the rigid bounce left the long bars pitching at ~7 Hz, a wobble no Rhodes
  has); without a tone bar, a stiff mount (`tonebar.bare_mount_k_n_m`);
- the spring: its mass solved so the tine's fundamental is the note with the spring's
  centre at `spring.position_fraction` of the tine;
- the grommets' dashpots from the rubber's loss factor at the mount's lowest mode;
- the tine's own loss (its root, the air), fitted so that fundamental decays at Shear's
  measured Q (interpolated in log frequency, held flat outside his range);
- the hammer: its tip's hardness by key (the manual's grading, Gent's relation to Young's
  modulus), a Hertz contact with Hunt-Crossley loss, the striking point from the manual's
  striking line;
- the pickup's values.

The bar, the grommets' stiffness and the spring alternate three times (each depends a little on the
others); `Key.fits` keeps what each reached.
"""

from __future__ import annotations

import csv
import functools
import hashlib
import json
import os
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import numpy as np
import yaml
from scipy import optimize

from varimu.config import CONFIG_DIR, REPO_ROOT
from varimu.rhodes import beam as bm

RHODES_DIR = CONFIG_DIR / "rhodes"
CACHE_DIR = REPO_ROOT / "cache" / "rhodes"
TINE_LENGTHS = REPO_ROOT / "data" / "datasheets" / "rhodes_tine_lengths.csv"


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
    if isinstance(v, str):
        try:
            return float(v)
        except ValueError:
            return v
    return v


@functools.cache
def load(name: str = "mk1") -> dict[str, Any]:
    raw = yaml.safe_load((RHODES_DIR / f"{name}.yaml").read_text(encoding="utf-8"))
    cfg = _values(raw, name)
    with TINE_LENGTHS.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    lengths = {int(r["key"]): float(r["free_length_m"]) for r in rows}
    for n in cfg["tine"].get("chart_outliers", []):
        n = int(n)
        lengths[n] = float(np.sqrt(lengths[n - 1] * lengths[n + 1]))
    cfg["tine_lengths_m"] = lengths
    return cfg


def note_hz(n: int, cfg: dict[str, Any] | None = None) -> float:
    cfg = cfg or load()
    return cfg["tuning"]["a4_hz"] * 2.0 ** ((n - 49) / 12)


def gent_youngs_pa(shore_a: float) -> float:
    """Young's modulus of rubber from its Shore A hardness (Gent 1958)."""
    return 1e6 * 0.0981 * (56 + 7.62336 * shore_a) / (0.137505 * (254 - 2.54 * shore_a))


def q_target(f_hz: float, cfg: dict[str, Any]) -> float:
    pts = np.array(sorted(cfg["anchors"]["q_shear"]))
    return float(np.interp(np.log(f_hz), np.log(pts[:, 0]), pts[:, 1]))


def tonebar_f0_hz(n: int, cfg: dict[str, Any]) -> float:
    """Muenster & Pfeifle's tone bar resonance, a least-squares line in (key, log f) over
    their keys; outside them, their nearest end's ratio to the note (the line, extrapolated
    to the bass, rises above the note, where a balanced bar can't put it)."""
    pts = np.array(cfg["anchors"]["tonebar_muenster"], dtype=float)
    keys = pts[:, 0] + 7  # 73-key bar numbers to 88-key keys
    slope, icpt = np.polyfit(keys, np.log(pts[:, 2]), 1)
    end = float(np.clip(n, keys.min(), keys.max()))
    ratio = np.exp(icpt + slope * end) / note_hz(int(end), cfg)
    return float(ratio * note_hz(n, cfg))


@dataclass(frozen=True)
class Hammer:
    mass_kg: float
    stiffness: float  # K of F = K d^p (1 + alpha d')
    exponent: float
    hysteresis_s_m: float
    strike_x_m: float  # the tip's centre along the tine
    durometer: float | None  # None: wrapped


@dataclass(frozen=True)
class Pickup:
    gap_m: float
    voicing_m: float
    coil_ohm: float
    turns: float
    magnet_width_m: float
    magnet_length_m: float
    wedge_length_m: float
    magnet_br_t: float
    magnet_mu_r: float
    tine_mu_r: float
    tine_diameter_m: float
    coil_inner_m: float
    coil_outer_m: float
    coil_length_m: float


@dataclass(frozen=True)
class Key:
    n: int
    note_hz: float
    q_target: float
    tonebar_f0_hz: float
    assembly: bm.Assembly
    hammer: Hammer
    pickup: Pickup
    fits: dict[str, float]
    f_max_hz: float
    element_m: float

    @property
    def damped(self) -> bm.Assembly:
        """The assembly with the damper's felt on the tine (the key up, no pedal)."""
        return replace(
            self.assembly,
            damper_x_m=self.fits["damper_x_m"],
            damper_c_n_s_m=self.fits["damper_c_n_s_m"],
        )


def _hammer(n: int, cfg: dict[str, Any], tine_len_m: float) -> Hammer:
    h = cfg["hammer"]
    bounds, duros = h["durometer_bounds"], h["durometers"]
    duro = next((d for b, d in zip(bounds, duros, strict=True) if n <= b), None)
    e = gent_youngs_pa(duro) if duro is not None else h["wrapped_youngs_pa"]
    e_star = e / (1 - h["poisson"] ** 2)  # the steel tine is rigid beside rubber
    r_eff = np.sqrt(cfg["tine"]["tip_diameter_m"] / 2 * h["tip_radius_m"])
    stiffness = 4 / 3 * e_star * np.sqrt(r_eff)
    lens = cfg["tine_lengths_m"]
    l_bass, l_treble = lens[1], lens[88]
    frac = (tine_len_m - l_treble) / (l_bass - l_treble)
    line = h["strike_line_treble_m"] + frac * (h["strike_line_bass_m"] - h["strike_line_treble_m"])
    return Hammer(
        h["mass_kg"],
        float(stiffness),
        h["exponent"],
        h["hysteresis_s_m"],
        float(line + h["tip_width_m"] / 2),
        duro,
    )


def _clamped_hz(bar: bm.ToneBar) -> float:
    """The bar alone, clamped at its root."""
    c = np.sqrt(bar.youngs_pa / bar.density_kg_m3) * bar.thickness_m / np.sqrt(12)
    return float(1.8751**2 * c / (2 * np.pi * bar.length_m**2))


def _pickup(cfg: dict[str, Any]) -> Pickup:
    p = cfg["pickup"]
    return Pickup(
        p["gap_m"],
        p["voicing_m"],
        p["coil_ohm"],
        float(p["turns"]),
        p["magnet_width_m"],
        p["magnet_length_m"],
        p["wedge_length_m"],
        p["magnet_br_t"],
        p["magnet_mu_r"],
        p["tine_mu_r"],
        cfg["tine"]["tip_diameter_m"],
        p["coil_inner_m"],
        p["coil_outer_m"],
        p["coil_length_m"],
    )


def _fit_damper(asm: bm.Assembly, f_hz: float, d: dict[str, float]) -> tuple[float, float]:
    """The damper's place and its felt's dashpot: the released fundamental's Q for a T60
    of `t60_s` (Q = pi f T60 / ln 1000)."""
    x = d["position_fraction"] * asm.tine_length_m
    q_target = np.pi * f_hz * d["t60_s"] / np.log(1000.0)

    def err(log_c: float) -> float:
        a = replace(asm, damper_x_m=x, damper_c_n_s_m=float(np.exp(log_c)))
        return float(np.log(bm.damped_q(a, f_hz) / q_target))

    grid = np.log(np.geomspace(1e-4, 1e2, 25))
    prev = grid[0]
    for g in grid[1:]:
        if err(g) < 0:
            return x, float(np.exp(optimize.brentq(err, prev, g, xtol=1e-4)))
        prev = g
    raise ValueError(f"no damper up to 100 N s/m stops {f_hz:.2f} Hz in {d['t60_s']} s")


def mount_share(asm: bm.Assembly, f_hz: float, element_m: float) -> float:
    """The share of the tine's fundamental's strain energy in the grommets: how much the
    fork's root moves (0: a balanced fork)."""
    fe = bm.assemble(asm, element_m)
    md = bm.modes(fe, count=12)
    k = bm.tine_mode(fe, md, f_hz)
    phi = md.phi[:, k]
    return float(max(1.0 - phi @ fe.k_beams @ phi / md.omega[k] ** 2, 1e-16))


def _balance_bar(asm: bm.Assembly, f_hz: float, element_m: float) -> bm.Assembly:
    """The bar's length that balances the fork: least of the tine's fundamental in the
    grommets (the manual: the prongs "alike in pitch"; Shear: matched legs, higher Q)."""
    bar = asm.tonebar

    def share(scale: float) -> float:
        a = replace(asm, tonebar=replace(bar, length_m=bar.length_m * scale))
        try:
            return np.log(mount_share(a, f_hz, element_m))
        except ValueError:
            return 0.0

    grid = np.geomspace(0.6, 1.6, 41)
    vals = [share(x) for x in grid]
    i = int(np.argmin(vals))
    lo, hi = grid[max(i - 1, 0)], grid[min(i + 1, grid.size - 1)]
    best = optimize.minimize_scalar(
        share, bounds=(lo, hi), method="bounded", options={"xatol": 1e-5}
    )
    scale = best.x if best.fun <= vals[i] else grid[i]
    return replace(asm, tonebar=replace(bar, length_m=bar.length_m * float(scale)))


def _spring_mass(asm: bm.Assembly, f_hz: float, element_m: float) -> float:
    def err(log_m: float) -> float:
        a = replace(asm, spring_mass_kg=float(np.exp(log_m)))
        fe = bm.assemble(a, element_m)
        md = bm.modes(fe, count=12)
        return float(np.log(md.f_hz[bm.tine_mode(fe, md, f_hz)] / f_hz))

    grid = np.log(np.geomspace(1e-7, 0.02, 31))
    if err(grid[0]) < 0:
        raise ValueError(f"the bare tine is below {f_hz:.2f} Hz: the spring can't raise it")
    # the first sign change going heavier (far heavier, another mode becomes the tine's)
    prev = grid[0]
    for g in grid[1:]:
        if err(g) < 0:
            lo, hi = prev, g
            break
        prev = g
    else:
        raise ValueError(f"no spring up to 20 g brings the tine down to {f_hz:.2f} Hz")
    return float(np.exp(optimize.brentq(err, lo, hi, xtol=1e-6)))


KEYS_73 = range(8, 81)  # the 73-key piano: E1 (key 8) to E7 (key 80)


def _fits_dir(name: str) -> Path:
    """The fitted keys' cache, keyed by the instrument's file, the tine lengths and this
    code (spec.py, beam.py)."""
    h = hashlib.sha256()
    for path in (
        RHODES_DIR / f"{name}.yaml",
        TINE_LENGTHS,
        Path(__file__),
        Path(bm.__file__),
    ):
        h.update(path.read_bytes())
    return CACHE_DIR / f"keys_{name}_{h.hexdigest()[:16]}"


@functools.cache
def key(n: int, name: str = "mk1") -> Key:
    """Key n built and fitted (cached on disk in cache/rhodes/: the fits are slow in the
    bass, a few seconds to a minute a key)."""
    if not 1 <= n <= 88:
        raise ValueError(f"key {n}: a Rhodes has keys 1-88")
    path = _fits_dir(name) / f"{n}.json"
    if path.exists():
        fits = json.loads(path.read_text(encoding="utf-8"))
        return _build(n, name, fits)
    k = _build(n, name, None)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(k.fits, indent=1), encoding="utf-8")
    os.replace(tmp, path)
    return k


def _build(n: int, name: str, fitted: dict[str, float] | None) -> Key:
    """Key n: fitted, or rebuilt from earlier fits."""
    cfg = load(name)
    f = note_hz(n, cfg)
    t, s, tb, blk, gr = cfg["tine"], cfg["spring"], cfg["tonebar"], cfg["block"], cfg["grommets"]
    element_m = cfg["numerics"]["element_m"]
    length = cfg["tine_lengths_m"][n]
    taper = min(t["taper_length_m"], 0.5 * length)
    sections = (
        bm.Section(taper, t["root_diameter_m"], t["tip_diameter_m"]),
        bm.Section(length - taper, t["tip_diameter_m"], t["tip_diameter_m"]),
    )
    tonebar = None
    if n >= tb["first_key"]:
        # clamped cantilever: f = 1.8751^2 / (2 pi L^2) sqrt(E I / rho A), I / A = t^2 / 12
        c = np.sqrt(tb["youngs_pa"] / tb["density_kg_m3"]) * tb["thickness_m"] / np.sqrt(12)
        bar_len = np.sqrt(1.8751**2 * c / (2 * np.pi * f))
        tonebar = bm.ToneBar(
            float(bar_len),
            tb["thickness_m"],
            tb["width_m"],
            tb["youngs_pa"],
            tb["density_kg_m3"],
            tb["root_dx_m"],
        )
    spring_len = min(s["length_m"], s["max_length_fraction"] * length)
    asm = bm.Assembly(
        tine=sections,
        tine_youngs_pa=t["youngs_pa"],
        tine_density_kg_m3=t["density_kg_m3"],
        spring_mass_kg=0.0,
        spring_length_m=spring_len,
        spring_x_m=s["position_fraction"] * length,
        tonebar=tonebar,
        block_mass_kg=blk["mass_kg"],
        block_inertia_kg_m2=blk["inertia_kg_m2"],
        block_x_m=blk["x_m"],
        grommet_x_m=tuple(gr["x_m"]),
        grommet_k_n_m=1e5,
        grommet_c_n_s_m=0.0,
        steel_loss=gr["steel_loss"],
        loss_ref_hz=f,
    )
    f_bar = tonebar_f0_hz(n, cfg)
    q = q_target(f, cfg)
    if fitted is not None:
        asm = replace(
            asm,
            spring_mass_kg=fitted["spring_mass_kg"],
            grommet_k_n_m=fitted["grommet_k_n_m"],
            grommet_c_n_s_m=fitted["grommet_c_n_s_m"],
            tine_loss=fitted["tine_loss"],
            tonebar=replace(tonebar, length_m=fitted["tonebar_length_m"]) if tonebar else None,
        )
        return Key(
            n,
            f,
            q,
            f_bar,
            asm,
            _hammer(n, cfg, length),
            _pickup(cfg),
            dict(fitted),
            cfg["numerics"]["f_max_hz"],
            element_m,
        )
    n_g = len(asm.grommet_x_m)
    for _ in range(3):
        if tonebar is not None:
            asm = _balance_bar(asm, f, element_m)
        if tonebar is None:
            # a block alone, held firmly (on the bars' soft grommets the tine's torque
            # rocks the light block and it is no cantilever; Muenster & Pfeifle measured
            # bars, so their law says nothing here)
            k_g = tb["bare_mount_k_n_m"]
        else:
            # the assembly's lowest mode on its mount at the measured resonance
            def k_err(log_k: float, asm: bm.Assembly = asm) -> float:
                a = replace(asm, grommet_k_n_m=float(np.exp(log_k)))
                fe = bm.assemble(a, element_m)
                md = bm.modes(fe, count=24)
                try:
                    return float(np.log(md.f_hz[bm.mount_mode(fe, md)] / f_bar))
                except ValueError:  # stiff enough to lift it above the modes solved
                    return 10.0

            m_total = bm.total_mass_kg(bm.assemble(asm, element_m))
            k0 = np.log(m_total * (2 * np.pi * f_bar) ** 2 / n_g)  # its bounce alone
            k_g = float(np.exp(optimize.brentq(k_err, k0 - 3.0, k0 + 9.0, xtol=1e-6)))
        asm = replace(asm, grommet_k_n_m=k_g)
        asm = replace(asm, spring_mass_kg=_spring_mass(asm, f, element_m))
    # the grommets' rubber: its loss factor at the mount's lowest mode
    fe = bm.assemble(asm, element_m)
    md = bm.modes(fe, count=24)
    try:
        f_mount = float(md.f_hz[bm.mount_mode(fe, md)])
    except ValueError:
        f_mount = f_bar
    c_g = gr["rubber_loss"] * asm.grommet_k_n_m / (2 * np.pi * f_mount)
    asm = replace(asm, grommet_c_n_s_m=float(c_g))
    asm = bm.fit_tine_loss(asm, f, q)
    damper_x, damper_c = _fit_damper(asm, f, cfg["damper"])
    fe = bm.assemble(asm, element_m)
    md = bm.modes(fe, count=12)
    k_t = bm.tine_mode(fe, md, f)
    fits = {
        "spring_mass_kg": asm.spring_mass_kg,
        "grommet_k_n_m": asm.grommet_k_n_m,
        "grommet_c_n_s_m": asm.grommet_c_n_s_m,
        "tine_loss": asm.tine_loss,
        "fundamental_hz": float(md.f_hz[k_t]),
        "fundamental_q": bm.damped_q(asm, f),
        "assembly_mass_kg": bm.total_mass_kg(fe),
        "tonebar_length_m": asm.tonebar.length_m if asm.tonebar else 0.0,
        "tonebar_clamped_hz": _clamped_hz(asm.tonebar) if asm.tonebar else 0.0,
        "mount_share": mount_share(asm, f, element_m),
        "damper_x_m": damper_x,
        "damper_c_n_s_m": damper_c,
    }
    return Key(
        n,
        f,
        q,
        f_bar,
        asm,
        _hammer(n, cfg, length),
        _pickup(cfg),
        fits,
        cfg["numerics"]["f_max_hz"],
        element_m,
    )
