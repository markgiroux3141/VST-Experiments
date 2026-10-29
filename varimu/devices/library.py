"""Device files: building them, and loading them as models.

A device file is a version of a component (`config/components/<name>/<N>.yaml`,
`varimu.devices.versions`): `load_device("12AX7@1")` loads that version, a bare name its
latest. `varimu fit-devices` fits the models from data/datasheets/ and saves a new
version only when a fit changed (versions are never overwritten). Every block
carries a `source`, following the same rule as genome_bounds.yaml. Values
tagged "provisional:" come from model knowledge or loose web references, not
from a datasheet, and are expected to become genome parameters or be replaced.
"""

from __future__ import annotations

import copy
import datetime as _dt
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import numpy as np
import yaml

import varimu
from varimu.config import REPO_ROOT
from varimu.devices import versions
from varimu.devices.diode import JunctionDiode, VacuumDiode
from varimu.devices.fit import (
    DATASHEETS,
    PitchDistribution,
    curve_report,
    effective_sigma,
    evaluate_6386,
    fit_6386,
    fit_junction_diode,
    fit_koren_pentode,
    fit_koren_triode,
    load_6386,
    load_csv,
)
from varimu.devices.pentode import KorenPentode, Pentode, koren_pentode_from_spec
from varimu.devices.triode import GridCurrent, KorenTriode, Triode, koren_from_spec

DEVICE_DIR = versions.COMPONENT_DIR
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


# Parsed device files by (path, modification time, size): a circuit build reads dozens,
# and a knob turned while playing (varimu.sim.live) rebuilds the circuit each step. A file
# is checked against versions.lock when it is parsed (an edit changes its key).
_PARSED: dict[tuple[Path, int, int], dict[str, Any]] = {}


def _read(ref: str, root: Path) -> dict[str, Any]:
    path = versions.path(ref, root)
    st = path.stat()
    key = (path.resolve(), st.st_mtime_ns, st.st_size)
    if key not in _PARSED:
        _, text = versions.read_text(ref, root)
        _PARSED[key] = yaml.safe_load(text)
    return copy.deepcopy(_PARSED[key])


def load_device(name: str, root: Path = DEVICE_DIR) -> Device:
    """Device file `name` (`NAME@N`, or `NAME` for its latest version) as a model."""
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
        g = d.get("grid_current")
        return Pentode(
            d["name"],
            KorenPentode(p["mu"], p["ex"], p["kg1"], p["kg2"], p["kp"], p["kvb"]),
            GridCurrent(g["perveance"], g["contact_v"], g["smooth_v"]) if g else None,
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


def build_12au7() -> dict[str, Any]:
    pub = _published()["12AU7"]
    caps = pub["capacitances_f"]
    return {
        "name": "12AU7",
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
        "grid_current": dict(PROVISIONAL_GRID),
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


def build_6x4() -> dict[str, Any]:
    pub = _published()["6X4"]
    v = np.array([p["va_v"] for p in pub["plate_curve_read_off_render"]])
    i = np.array([p["ia_a"] for p in pub["plate_curve_read_off_render"]])
    perv = float(np.sum(i * v**1.5) / np.sum(v**3))  # least squares through the origin
    return {
        "name": "6X4",
        "kind": "vacuum_diode",
        "perveance": perv,
        "smooth_v": 0.1,
        "source": f"Child-law least-squares fit to 6 points read off the plate curve "
        f"({pub['source']}); per section",
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


def build_el34t() -> dict[str, Any]:
    """The EL34 triode-connected (the 670's series pass tube, V302): a Koren triode fit to
    Mullard's triode-connected plate curves."""
    pub = _published()["EL34"]
    vg, va, ia = load_csv("mullard_el34_triode_plate.csv").T
    m, rep = fit_koren_triode(vg, va, ia, np.hypot(0.03 * ia, 2e-3))
    caps = pub["capacitances_f"]
    return {
        "name": "EL34T",
        "kind": "triode",
        "source": "fit: Koren triode, least squares on Mullard EL34 sheet C4 (triode "
        "connected, g2 to anode), digitized: data/datasheets/mullard_el34.provenance.yaml. "
        "The 670 also ties g3 to the anode; no data for that",
        "plate": {"model": "koren", "mu": m.mu, "ex": m.ex, "kg1": m.kg1, "kp": m.kp, "kvb": m.kvb},
        "grid_current": dict(PROVISIONAL_GRID),
        "capacitances_f": {
            "gk": caps["input"],
            "gp": caps["ag1"],
            "pk": caps["output"],
            "source": f"provisional: the pentode-connection values ({pub['source']}); none "
            "printed for triode connection",
        },
        "fit_report": {"plate": rep.as_dict(), "sigma": "hypot(3% of Ia, 2 mA)"},
    }


def build_6084() -> dict[str, Any]:
    """The 6084 (E80F), the regulator's error amplifier (V303): a Koren pentode fit to the
    Philips E80F transfer, plate and screen curves."""
    pub = _published()["6084"]
    tr = load_csv("philips_e80f_transfer.csv")  # va, vg2, vg1, ia
    pl = load_csv("philips_e80f_plate.csv")  # vg2, vg1, va, ia
    sc = load_csv("philips_e80f_screen.csv")  # va, vg1, vg2, ig2
    plate = np.r_[
        np.c_[tr[:, 2], tr[:, 1], tr[:, 0], tr[:, 3]],
        np.c_[pl[:, 1], pl[:, 0], pl[:, 2], pl[:, 3]],
    ]
    screen = np.c_[sc[:, 1], sc[:, 2], sc[:, 3]]
    m, rp, rs = fit_koren_pentode(
        plate,
        screen,
        np.hypot(0.02 * plate[:, 3], 0.03e-3),
        np.hypot(0.03 * screen[:, 2], 0.02e-3),
    )
    caps = pub["capacitances_f"]
    return {
        "name": "6084",
        "kind": "pentode",
        "source": "fit: Koren pentode, least squares on the Philips E80F (6084) transfer, "
        "plate and screen curves, digitized: data/datasheets/philips_e80f.provenance.yaml. "
        "Koren's screen law fits the screen curves only to ~40% rms",
        "model": {"mu": m.mu, "ex": m.ex, "kg1": m.kg1, "kg2": m.kg2, "kp": m.kp, "kvb": m.kvb},
        "grid_current": dict(PROVISIONAL_GRID),
        "capacitances_f": {
            "g1k": caps["input"],
            "g1p": caps["ag1"],
            "pk": caps["output"],
            "source": pub["source"],
        },
        "fit_report": {
            "plate": rp.as_dict(),
            "screen": rs.as_dict(),
            "sigma": "plate hypot(2%, 30 uA), screen hypot(3%, 20 uA)",
        },
    }


# The 5651's current at which its operating voltage (circuit value v5651_operating_v) is
# taken: the middle of its 1.5-3.5 mA range.
V5651_REF_A = 2.5e-3


def build_5651() -> dict[str, Any]:
    """The 5651 voltage reference (V304) as a junction diode in series with its burning
    voltage (a DC source in the netlist): the diode's series resistance is the slope of
    Tung-Sol's typical drop-vs-current line; its knee only keeps the tube from
    conducting below the burning voltage (lit from the DC point on: no ignition)."""
    i, v = load_csv("tungsol_5651_drop.csv").T
    slope, _ = np.polyfit(i, v, 1)
    return {
        "name": "5651",
        "kind": "junction_diode",
        "is_a": 1.0e-9,
        "n": 1.0,
        "rs_ohm": float(slope),
        "source": "rs: slope of the Tung-Sol 5651 typical tube drop vs current (1.45-3.6 mA, "
        "digitized: data/datasheets/tungsol_5651.provenance.yaml); is, n: provisional (the "
        "knee below 1.5 mA isn't published; it only blocks conduction below the burning "
        "voltage)",
    }


def build_selenium() -> dict[str, Any]:
    """A selenium rectifier cell of 1 sq. in. rectifying area (GR301): a junction diode fit
    to Tarzian's 25 C static forward characteristic. The netlist scales it by area."""
    se = load_csv("tarzian_selenium_static.csv")
    s25 = se[se[:, 0] == 25]
    v, j = s25[:, 1], s25[:, 2]
    m, rep = fit_junction_diode(v, j, np.hypot(0.05 * j, 5e-3), "SELENIUM")
    return {
        "name": "SELENIUM",
        "kind": "junction_diode",
        "is_a": m.is_a,
        "n": m.n,
        "rs_ohm": m.rs_ohm,
        "source": "fit: Shockley diode with series resistance on the Sarkes Tarzian (1950) "
        "Fig. 4 static forward characteristic at 25 C, per sq. in. of rectifying area "
        "(digitized: data/datasheets/tarzian_selenium.provenance.yaml). Reverse leakage "
        "(~1 mA/in^2 at an unstated voltage, Fig. 6) is not modeled",
        "fit_report": {"forward": rep.as_dict(), "sigma": "hypot(5%, 5 mA/in^2)"},
    }


# --- Fender 5E3 Deluxe (device builder B9) ------------------------------------------

# Digitizing errors (data/datasheets/*.provenance.yaml): the effective variance adds each
# point's local slope times the error in its x coordinate (effective_sigma).
AY7_SIGMA = {"rel": 0.02, "abs_": 0.03e-3, "sigma_x": 1.0}  # A, A, V of Vp
V6_PLATE_SIGMA = {"rel": 0.02, "abs_": 0.3e-3, "sigma_x": 1.0}  # V of Va
V6_TRANSFER_SIGMA = {"rel": 0.02, "abs_": 0.3e-3, "sigma_x": 0.15}  # V of Vg1
V6_SCREEN_SIGMA = {"rel": 0.03, "abs_": 0.03e-3, "sigma_x": 0.15}
# The 12AY7's fit lands in a poor minimum (Kvb -> 0) from the default starts.
AY7_STARTS = ([40.0, 1.35, 1000.0, 300.0, 300.0], [40.0, 1.4, 500.0, 100.0, 30.0])


def load_12ay7() -> tuple[np.ndarray, np.ndarray]:
    """RCA's plate curves at grid <= 0 (the fit's data), and Tung-Sol's (a cross-check);
    columns vg, vp, ip. RCA's +1 V curve is left out: at positive grid the cathode current
    splits with the grid, which Koren's plate law doesn't describe."""
    rca, ts = load_csv("rca_12ay7_plate.csv"), load_csv("tungsol_12ay7_plate.csv")
    return rca[rca[:, 0] <= 0], ts[ts[:, 0] <= 0]


def build_12ay7() -> dict[str, Any]:
    """The 5E3's V1: a Koren triode fit to RCA's plate curves."""
    pub = _published()["12AY7"]
    d, ts = load_12ay7()
    vg, vp, ip = d.T
    m, rep = fit_koren_triode(
        vg, vp, ip, effective_sigma(vp, ip, vg, 8.0, **AY7_SIGMA), starts=AY7_STARTS
    )
    ts_err = m.ip(ts[:, 0], ts[:, 1]) - ts[:, 2]
    caps = pub["capacitances_f"]
    return {
        "name": "12AY7",
        "kind": "triode",
        "source": "fit: Koren triode, least squares (effective variance) on the RCA 12AY7 "
        "(1953) plate curves, grid 0..-7 V, digitized: data/datasheets/rca_12ay7.provenance.yaml",
        "plate": {"model": "koren", "mu": m.mu, "ex": m.ex, "kg1": m.kg1, "kp": m.kp, "kvb": m.kvb},
        "grid_current": dict(PROVISIONAL_GRID),
        "capacitances_f": {
            "gk": caps["input"],
            "gp": caps["gp"],
            "pk": caps["output"],
            "source": f"{pub['source']} (input -> gk, output -> pk; no shield); Tung-Sol's "
            "sheet prints the same",
        },
        "fit_report": {
            "plate": rep.as_dict(),
            "sigma": "2% of Ip + 30 uA, with the curve's slope times 1 V of Vp",
            "tungsol_plate_rms_a": float(np.sqrt(np.mean(ts_err**2))),
            "tungsol_plate_max_a": float(np.max(np.abs(ts_err))),
        },
    }


def load_6v6gt() -> dict[str, np.ndarray]:
    """The GE ET-T914 figures as (vg1, vg2, va, ia) plate points and (vg1, vg2, ig2) screen
    points, plus each figure's raw columns for the plot."""
    pl = load_csv("ge_6v6gt_plate.csv")  # vg2, vg1, va, ia
    pv = load_csv("ge_6v6gt_plate_vg2.csv")  # vg2, vg1, va, ia
    tr = load_csv("ge_6v6gt_transfer.csv")  # va, vg2, vg1, ia
    sc = load_csv("ge_6v6gt_screen.csv")  # va, vg1, vg2, ig2
    return {"plate": pl, "plate_vg2": pv, "transfer": tr, "screen": sc}


def build_6v6gt() -> dict[str, Any]:
    """The 5E3's output pair: a Koren pentode fit to GE's plate, transfer and screen curves.
    The knee below ~60 V is sharper than Koren's atan(Va/Kvb) can draw, and the fit's plate
    resistance at the class-A point is about twice the sheet's "approximate" 50 kOhm."""
    pub = _published()["6V6GT"]
    f = load_6v6gt()
    pl, pv, tr, sc = f["plate"], f["plate_vg2"], f["transfer"], f["screen"]
    plate = np.r_[
        np.c_[pl[:, 1], pl[:, 0], pl[:, 2], pl[:, 3]],
        np.c_[pv[:, 1], pv[:, 0], pv[:, 2], pv[:, 3]],
        np.c_[tr[:, 2], tr[:, 1], tr[:, 0], tr[:, 3]],
    ]
    plate_sigma = np.r_[
        effective_sigma(pl[:, 2], pl[:, 3], pl[:, 1], 12.0, **V6_PLATE_SIGMA),
        effective_sigma(pv[:, 2], pv[:, 3], pv[:, 0], 12.0, **V6_PLATE_SIGMA),
        effective_sigma(tr[:, 2], tr[:, 3], tr[:, 1], 1.5, **V6_TRANSFER_SIGMA),
    ]
    screen = np.c_[sc[:, 1], sc[:, 2], sc[:, 3]]
    screen_sigma = effective_sigma(sc[:, 1], sc[:, 3], sc[:, 2], 1.5, **V6_SCREEN_SIGMA)
    m, rp, rs = fit_koren_pentode(plate, screen, plate_sigma, screen_sigma)
    a, dv = pub["class_a1"], 1e-3
    vg1, vg2, va = a["vg1_v"], a["vg2_v"], a["vp_v"]
    knee = plate[:, 2] < 60
    err = m.ip(plate[:, 0], plate[:, 1], plate[:, 2]) - plate[:, 3]
    caps = pub["capacitances_f"]
    return {
        "name": "6V6GT",
        "kind": "pentode",
        "source": "fit: Koren pentode, least squares (effective variance) on the GE 6V6-GT "
        "ET-T914 (1955) plate (Vg2 250 V; Vg1 0 at Vg2 100-250 V), transfer and screen-current "
        "curves, digitized: data/datasheets/ge_6v6gt.provenance.yaml. Koren's screen law "
        "fits the screen curves only roughly (fit_report)",
        "model": {"mu": m.mu, "ex": m.ex, "kg1": m.kg1, "kg2": m.kg2, "kp": m.kp, "kvb": m.kvb},
        "grid_current": dict(PROVISIONAL_GRID),
        "capacitances_f": {
            "g1k": caps["input"],
            "g1p": caps["g1p"],
            "pk": caps["output"],
            "source": f"{pub['source']} (without external shield)",
        },
        "fit_report": {
            "plate": rp.as_dict(),
            "screen": rs.as_dict(),
            "sigma": "plate 2% + 0.3 mA with slope x 1 V of Va (0.15 V of Vg1 on the transfer "
            "curves); screen 3% + 30 uA with slope x 0.15 V",
            "plate_rms_a_va_below_60": float(np.sqrt(np.mean(err[knee] ** 2))),
            "plate_rms_a_va_from_60": float(np.sqrt(np.mean(err[~knee] ** 2))),
            "class_a1_model": {
                "ip_a": float(m.ip(vg1, vg2, va)),
                "gm_s": float((m.ip(vg1 + dv, vg2, va) - m.ip(vg1 - dv, vg2, va)) / (2 * dv)),
                "rp_ohm": float(2 * dv / (m.ip(vg1, vg2, va + dv) - m.ip(vg1, vg2, va - dv))),
                "ig2_a": float(m.ig2(vg1, vg2)),
            },
        },
    }


def build_5y3gt() -> dict[str, Any]:
    """The 5E3's rectifier: a Child-law vacuum diode fit to GE's plate curve (per section)."""
    v, i = load_csv("ge_5y3gt_plate.csv").T
    sigma = np.hypot(0.03 * i, 2e-3)
    w = 1 / sigma**2
    perv = float(np.sum(w * i * v**1.5) / np.sum(w * v**3))  # weighted, through the origin
    d = VacuumDiode("5Y3GT", perv)
    return {
        "name": "5Y3GT",
        "kind": "vacuum_diode",
        "perveance": perv,
        "smooth_v": 0.1,
        "source": "fit: Child-law least squares on the GE 5Y3-GT ET-T965 (1955) plate "
        "characteristic, each section (digitized: data/datasheets/ge_5y3gt.provenance.yaml); "
        "per anode. A filament cathode: the drop along the filament isn't modeled",
        "fit_report": {
            "plate": curve_report(d.i(v), i, sigma).as_dict(),
            "sigma": "hypot(3% of Ia, 2 mA)",
        },
    }


BUILDERS = {
    "6386": build_6386,
    "12AX7": build_12ax7,
    "12BH7": build_12bh7,
    "12AU7": build_12au7,
    "6973": build_6973,
    "GZ34": build_gz34,
    "SI_RECTIFIER": build_si_rectifier,
    "EL34T": build_el34t,
    "6084": build_6084,
    "5651": build_5651,
    "SELENIUM": build_selenium,
    "6X4": build_6x4,
    "12AY7": build_12ay7,
    "6V6GT": build_6v6gt,
    "5Y3GT": build_5y3gt,
}

REPORT_FOR = {
    "6386": "6386_fit.png",
    "12AY7": "12ay7_fit.png",
    "6V6GT": "6v6gt_fit.png",
    "5Y3GT": "5y3gt_fit.png",
}


def plot_fit(name: str, root: Path = DEVICE_DIR) -> Path:
    """The review plot of a fitted device (reports/devices/), from its saved version."""
    from varimu.devices import plots

    path = REPORT_DIR / REPORT_FOR[name]
    dev = load_device(name, root)
    pub = _published()
    if name == "6386":
        plots.plot_6386(dev, load_6386(), path)
    elif name == "12AY7":
        _, ts = load_12ay7()
        rca = load_csv("rca_12ay7_plate.csv")  # with the +1 V curve (not fitted)
        a, t = pub["12AY7"]["class_a1"], pub["12AY7"]["tungsol_class_a1"]
        plots.plot_koren_triode(
            dev,
            rca,
            ts,
            [
                {
                    **a,
                    "label": f"sheets: {a['ip_a'] * 1e3:g} mA at {a['vg_v']} V; "
                    f"mu {a['mu']} (RCA) / {t['mu']} (Tung-Sol)",
                }
            ],
            path,
            "12AY7 Koren fit vs RCA (1953) plate curves (+1 V not fitted); Tung-Sol (1956) as the "
            "second source",
        )
    elif name == "6V6GT":
        f = load_6v6gt()
        a = pub["6V6GT"]["class_a1"]
        plots.plot_koren_pentode(
            dev,
            f["plate"],
            f["plate_vg2"],
            f["transfer"],
            f["screen"],
            [{"va_v": a["vp_v"], "ia_a": a["ip_a"], "label": f"sheet class A: {a['vg1_v']} V"}],
            path,
            "6V6GT Koren pentode fit vs GE ET-T914 (1955)",
        )
    elif name == "5Y3GT":
        d = pub["5Y3GT"]
        plots.plot_vacuum_diode(
            dev,
            load_csv("ge_5y3gt_plate.csv"),
            [
                {
                    "va_v": d["tube_drop_v_at_125ma_dc_per_plate"],
                    "ia_a": 0.125,
                    "label": "sheet: 50 V drop at 125 mA",
                }
            ],
            path,
            "5Y3GT Child-law fit vs GE ET-T965 (1955)",
        )
    return path


def write_devices(
    names: Iterable[str] | None = None, root: Path = DEVICE_DIR
) -> list[tuple[str, Path]]:
    """Fit each device and save it as its component's next version when the fit differs
    from the latest version's data; returns (what happened, path) per device (and plot)."""
    root.mkdir(parents=True, exist_ok=True)
    out = []
    stamp = _dt.date.today().isoformat()
    for name in names or BUILDERS:
        data = _f(BUILDERS[name]())
        latest = None
        if versions.versions(name, root):
            ref, text = versions.read_text(name, root)
            latest = (ref, yaml.safe_load(text))
        if latest is not None and latest[1] == data:
            out.append((f"unchanged {latest[0]}", versions.path(latest[0], root)))
        else:
            header = (
                f"# Generated by `varimu fit-devices` (varimu {varimu.__version__}) on {stamp}.\n"
                f"# Don't edit by hand: change the inputs in data/datasheets/ and refit.\n"
            )
            text = header + yaml.safe_dump(data, sort_keys=False, width=100)
            ref = versions.save(name, text, root)
            out.append((f"saved {ref}", versions.path(ref, root)))
        if name in REPORT_FOR:
            out.append(("plotted", plot_fit(name, root)))
    return out
