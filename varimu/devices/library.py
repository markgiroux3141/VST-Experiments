"""Device parameter files (config/devices/*.yaml): building them, and loading them as models.

`varimu fit-devices` regenerates the files from data/datasheets/. Every block
carries a `source`, following the same rule as genome_bounds.yaml. Values
tagged "provisional:" come from model knowledge or loose web references, not
from a datasheet, and are expected to become genome parameters or be replaced.
"""

from __future__ import annotations

import datetime as _dt
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import numpy as np
import yaml

import varimu
from varimu.config import CONFIG_DIR, REPO_ROOT
from varimu.devices.diode import JunctionDiode, VacuumDiode
from varimu.devices.fit import DATASHEETS, PitchDistribution, evaluate_6386, fit_6386, load_6386
from varimu.devices.pentode import KorenPentode, Pentode, koren_pentode_from_spec
from varimu.devices.triode import GridCurrent, KorenTriode, Triode, koren_from_spec

DEVICE_DIR = CONFIG_DIR / "devices"
REPORT_DIR = REPO_ROOT / "reports" / "devices"
Device = Triode | Pentode | JunctionDiode | VacuumDiode

# Oxide-cathode grid conduction. There's no datasheet figure for any of these
# tubes, so this is the same placeholder everywhere until it becomes a genome parameter.
PROVISIONAL_GRID = {
    "perveance": 1.0e-3,
    "contact_v": -0.7,
    "smooth_v": 0.05,
    "source": "provisional: model knowledge (typical oxide-cathode contact potential "
    "-0.5..-1 V; perveance sized so grid resistance near 0 V is ~kOhm, cf. Koren RGI)",
}


# --- Loading -------------------------------------------------------------------


def _read(name: str, root: Path) -> dict[str, Any]:
    path = root / f"{name.lower()}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"{path} not found; run `uv run varimu fit-devices`")
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_device(name: str, root: Path = DEVICE_DIR) -> Device:
    d = _read(name, root)
    kind = d["kind"]
    if kind == "triode":
        p = d["plate"]
        if p["model"] == "koren":
            plate = KorenTriode(p["mu"], p["ex"], p["kg1"], p["kp"], p["kvb"])
        elif p["model"] == "varimu":
            pd = p["pitch_distribution"]
            plate = PitchDistribution(
                pd["u_min"], pd["u_span"], tuple(pd["coeffs"]), pd["n_sections"]
            ).triode(p["ex"], p["kg1"], p["kp"], p["kvb"])
        else:
            raise ValueError(f"{name}: unknown plate model {p['model']!r}")
        g = d.get("grid_current")
        c = d["capacitances_f"]
        return Triode(
            d["name"],
            plate,
            GridCurrent(g["perveance"], g["contact_v"], g["smooth_v"]) if g else None,
            c_gk=c["gk"],
            c_gp=c["gp"],
            c_pk=c["pk"],
        )
    if kind == "pentode":
        p, c = d["model"], d["capacitances_f"]
        return Pentode(
            d["name"],
            KorenPentode(p["mu"], p["ex"], p["kg1"], p["kg2"], p["kp"], p["kvb"]),
            c_g1k=c["g1k"],
            c_g1p=c["g1p"],
            c_pk=c["pk"],
        )
    if kind == "junction_diode":
        return JunctionDiode(d["name"], d["is_a"], d["n"], d["rs_ohm"])
    if kind == "vacuum_diode":
        return VacuumDiode(d["name"], d["perveance"], d.get("smooth_v", 0.1))
    raise ValueError(f"{name}: unknown device kind {kind!r}")


# --- Building --------------------------------------------------------------------


def _published() -> dict[str, Any]:
    with open(DATASHEETS / "published_points.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _f(x):
    """Plain Python floats so the YAML stays readable."""
    if isinstance(x, dict):
        return {k: _f(v) for k, v in x.items()}
    if isinstance(x, list | tuple):
        return [_f(v) for v in x]
    return float(x) if isinstance(x, float | np.floating | np.integer) else x


def build_6386(**fit_kwargs) -> dict[str, Any]:
    pub = _published()["6386"]
    data = load_6386()
    model, dist = fit_6386(data, **fit_kwargs)
    report = evaluate_6386(model, data)
    caps = pub["capacitances_f"]
    return {
        "name": "6386",
        "kind": "triode",
        "source": "fit: GE ET-T1113 (1954) digitized plate/transfer/cascode-gm curves + "
        "tabulated points; see data/datasheets/ge_6386.provenance.yaml",
        "plate": {
            "model": "varimu",
            "pitch_distribution": {
                "u_min": dist.u_min,
                "u_span": dist.u_span,
                "coeffs": list(dist.coeffs),
                "n_sections": dist.n_sections,
            },
            "ex": model.ex,
            "kg1": model.kg1,
            "kp": model.kp,
            "kvb": model.kvb,
            "derived_sections": {"mu": list(model.mus), "weight": list(model.weights)},
        },
        "grid_current": dict(PROVISIONAL_GRID),
        "capacitances_f": {
            "gk": caps["input"],
            "gp": caps["gp"],
            "pk": caps["output"],
            "source": "GE ET-T1113 p.1 (input -> gk, output -> pk; no shield)",
        },
        "fit_report": report.as_dict(),
    }


def build_12ax7() -> dict[str, Any]:
    pub = _published()["12AX7"]
    caps = pub["capacitances_f"]
    return {
        "name": "12AX7",
        "kind": "triode",
        "source": pub["source"],
        "plate": {"model": "koren", **pub["koren"]},
        "grid_current": dict(PROVISIONAL_GRID),
        "capacitances_f": {**caps, "source": pub["source"]},
    }


def build_12bh7() -> dict[str, Any]:
    pub = _published()["12BH7"]
    a = pub["class_a1"]
    k = koren_from_spec(vp=a["vp_v"], vg=a["vg_v"], ip=a["ip_a"], gm=a["gm_s"], rp=a["rp_ohm"])
    return {
        "name": "12BH7",
        "kind": "triode",
        "source": f"fit to one class-A1 point ({pub['source']}); kp=300, kvb=300 are "
        "provisional: Koren's typical values, since one point can't pin down "
        "5 parameters",
        "plate": {"model": "koren", "mu": k.mu, "ex": k.ex, "kg1": k.kg1, "kp": k.kp, "kvb": k.kvb},
        "grid_current": dict(PROVISIONAL_GRID),
        "capacitances_f": {
            "gk": 3.2e-12,
            "gp": 2.6e-12,
            "pk": 0.5e-12,
            "source": "provisional: model knowledge (typical 12BH7A sheet values)",
        },
    }


def build_6973() -> dict[str, Any]:
    pub = _published()["6973"]
    a, c = pub["class_a1"], pub["cutoff"]
    m = koren_pentode_from_spec(
        vp=a["vp_v"],
        vg2=a["vg2_v"],
        vg1=a["vg1_v"],
        ip=a["ip_a"],
        gm=a["gm_s"],
        rp=a["rp_ohm"],
        ig2=a["ig2_a"],
        cutoff_vg1=c["vg1_v"],
        cutoff_ip=c["ip_a"],
    )
    caps = pub["capacitances_f"]
    return {
        "name": "6973",
        "kind": "pentode",
        "source": f"fit to class-A1 point + cutoff point ({pub['source']}); ex=1.35 is "
        "provisional: Koren's typical pentode value",
        "model": {"mu": m.mu, "ex": m.ex, "kg1": m.kg1, "kg2": m.kg2, "kp": m.kp, "kvb": m.kvb},
        "capacitances_f": {
            "g1k": caps["input"],
            "g1p": caps["g1p"],
            "pk": caps["output"],
            "source": pub["source"],
        },
    }


def build_gz34() -> dict[str, Any]:
    pub = _published()["GZ34"]
    v = np.array([p["va_v"] for p in pub["anode_curve_read_by_eye"]])
    i = np.array([p["ia_a"] for p in pub["anode_curve_read_by_eye"]])
    perv = float(np.sum(i * v**1.5) / np.sum(v**3))  # least squares through the origin
    return {
        "name": "GZ34",
        "kind": "vacuum_diode",
        "perveance": perv,
        "smooth_v": 0.1,
        "source": f"Child-law least-squares fit to 3 points read off the anode curve "
        f"({pub['source']}); per anode",
    }


def build_si_rectifier() -> dict[str, Any]:
    return {
        "name": "SI_RECTIFIER",
        "kind": "junction_diode",
        "is_a": 7.0e-9,
        "n": 1.8,
        "rs_ohm": 0.034,
        "source": "provisional: model knowledge (approximates the widely circulated 1N4007 "
        "SPICE model). The 670 sidechain bridge diode type is unknown: "
        "web: https://historyofrecording.com/Tube_Equipment_Corporation.html "
        "says only 'diode bridge rectifier'",
    }


BUILDERS = {
    "6386": build_6386,
    "12AX7": build_12ax7,
    "12BH7": build_12bh7,
    "6973": build_6973,
    "GZ34": build_gz34,
    "SI_RECTIFIER": build_si_rectifier,
}


def write_devices(names: Iterable[str] | None = None, root: Path = DEVICE_DIR) -> list[Path]:
    root.mkdir(parents=True, exist_ok=True)
    out = []
    stamp = _dt.date.today().isoformat()
    for name in names or BUILDERS:
        data = _f(BUILDERS[name]())
        path = root / f"{name.lower()}.yaml"
        header = (
            f"# Generated by `varimu fit-devices` (varimu {varimu.__version__}) on {stamp}.\n"
            f"# Don't edit by hand: change the inputs in data/datasheets/ and refit.\n"
        )
        path.write_text(header + yaml.safe_dump(data, sort_keys=False, width=100), encoding="utf-8")
        out.append(path)
        if name == "6386":
            from varimu.devices.plots import plot_6386

            plot = REPORT_DIR / "6386_fit.png"
            plot_6386(load_device("6386", root), load_6386(), plot)
            out.append(plot)
    return out
