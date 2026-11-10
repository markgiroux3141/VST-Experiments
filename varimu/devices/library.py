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
import math
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import numpy as np
import yaml

import varimu
from varimu.config import REPO_ROOT
from varimu.devices import versions
from varimu.devices.bjt import Bjt, bjt_from_data, depletion_c_f, parse_card
from varimu.devices.capsule import (
    Capsule,
    DualCapsule,
    capsule_from_data,
    dual_capsule_from_data,
)
from varimu.devices.contact import Contact, contact_from_data
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
from varimu.devices.jfet import Jfet, jfet_from_data
from varimu.devices.lamp import Lamp, lamp_from_data
from varimu.devices.moving_coil import MovingCoil, moving_coil_from_data
from varimu.devices.opto import Optocoupler, fit_vtl5c1, fit_vtl5c2, opto_from_data
from varimu.devices.pentode import KorenPentode, Pentode, koren_pentode_from_spec
from varimu.devices.photocell import Photocell, fit_pdvp9203, photocell_from_data
from varimu.devices.plate import SIX_LN10 as SIX_LN10_PLATE
from varimu.devices.plate import PlateComponent, plate_from_data
from varimu.devices.speaker import Speaker, speaker_from_data
from varimu.devices.spring import SpringTankComponent, spring_tank_from_data
from varimu.devices.tape import TapeFormulation, tape_from_data
from varimu.devices.thyratron import Thyratron, thyratron_from_data
from varimu.devices.triode import GridCurrent, KorenTriode, Triode, koren_from_spec

DEVICE_DIR = versions.COMPONENT_DIR
REPORT_DIR = REPO_ROOT / "reports" / "devices"
Device = (
    Triode
    | Pentode
    | JunctionDiode
    | VacuumDiode
    | Lamp
    | Thyratron
    | Bjt
    | Jfet
    | Optocoupler
    | Photocell
    | Contact
)

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
            KorenPentode(p["mu"], p["ex"], p["kg1"], p["kg2"], p["kp"], p["kvb"], p.get("screen")),
            GridCurrent(g["perveance"], g["contact_v"], g["smooth_v"]) if g else None,
            c_g1k=c["g1k"],
            c_g1p=c["g1p"],
            c_pk=c["pk"],
        )
    if kind == "junction_diode":
        return JunctionDiode(d["name"], d["is_a"], d["n"], d["rs_ohm"])
    if kind == "vacuum_diode":
        return VacuumDiode(d["name"], d["perveance"], d.get("smooth_v", 0.1))
    if kind == "lamp":
        return lamp_from_data(d, name)
    if kind == "optocoupler":
        return opto_from_data(d, name)
    if kind == "photocell":
        return photocell_from_data(d, name)
    if kind == "contact":
        return contact_from_data(d, name)
    if kind == "bjt":
        return bjt_from_data(d, name)
    if kind == "jfet":
        return jfet_from_data(d, name)
    if kind == "thyratron":
        return thyratron_from_data(d, name)
    if kind == "speaker":
        raise ValueError(f"{name} is a speaker, not a device model: place it with a `speaker` part")
    if kind == "moving_coil":
        raise ValueError(f"{name} is a cartridge, not a device model: place it with `moving_coil`")
    if kind == "ribbon_motor":
        raise ValueError(f"{name} is a ribbon, not a device model: place it with `ribbon_motor`")
    if kind == "capsule":
        raise ValueError(f"{name} is a capsule, not a device model: place it with a `capsule` part")
    if kind == "plate":
        raise ValueError(f"{name} is a plate, not a device model: place it with a `plate` part")
    if kind == "spring_tank":
        raise ValueError(
            f"{name} is a spring tank, not a device model: place it with a `spring_tank` part"
        )
    if kind == "tape":
        raise ValueError(f"{name} is a tape, not a device model: load it with load_tape")
    raise ValueError(f"{name}: unknown device kind {kind!r}")


def load_speaker(name: str, root: Path = DEVICE_DIR) -> Speaker:
    """Speaker component `name` (`NAME@N`, or `NAME` for its latest version)."""
    return speaker_from_data(_read(name, root), name)


def component_data(name: str, root: Path = DEVICE_DIR) -> dict[str, Any]:
    """Component `name`'s file as data (`NAME@N`, or `NAME` for its latest version)."""
    return _read(name, root)


def load_capsule(name: str, root: Path = DEVICE_DIR) -> Capsule:
    """Capsule component `name` (`NAME@N`, or `NAME` for its latest version)."""
    return capsule_from_data(_read(name, root), name)


def load_dual_capsule(name: str, root: Path = DEVICE_DIR) -> DualCapsule:
    """Dual-diaphragm capsule component `name` (`NAME@N`, or `NAME` for its latest)."""
    return dual_capsule_from_data(_read(name, root), name)


def load_moving_coil(name: str, root: Path = DEVICE_DIR) -> MovingCoil:
    """Moving-coil cartridge component `name` (`NAME@N`, or `NAME` for its latest)."""
    return moving_coil_from_data(_read(name, root), name)


def load_ribbon_motor(name: str, root: Path = DEVICE_DIR) -> MovingCoil:
    """Ribbon motor component `name` (`NAME@N`, or `NAME` for its latest): its compiled
    network in moving_coil's format (varimu.devices.ribbon)."""
    return moving_coil_from_data(_read(name, root), name, "ribbon_motor")


def load_plate(name: str, root: Path = DEVICE_DIR) -> PlateComponent:
    """Plate component `name` (`NAME@N`, or `NAME` for its latest version)."""
    d = _read(name, root)
    if d.get("kind") != "plate":
        raise ValueError(f"{name} is not a plate (kind {d.get('kind')!r})")
    return plate_from_data(d, name)


def load_spring_tank(name: str, root: Path = DEVICE_DIR) -> SpringTankComponent:
    """Spring tank component `name` (`NAME@N`, or `NAME` for its latest version)."""
    d = _read(name, root)
    if d.get("kind") != "spring_tank":
        raise ValueError(f"{name} is not a spring tank (kind {d.get('kind')!r})")
    return spring_tank_from_data(d, name)


def load_tape(name: str, root: Path = DEVICE_DIR) -> TapeFormulation:
    """Tape component `name` (`NAME@N`, or `NAME` for its latest version)."""
    d = _read(name, root)
    if d.get("kind") != "tape":
        raise ValueError(f"{name} is not a tape (kind {d.get('kind')!r})")
    return tape_from_data(d, name)


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


def build_6201() -> dict[str, Any]:
    """The Ampex 351's record driver: a Koren triode fit to RCA's two class-A1 points (Ip,
    gm, rp at each) and the cutoff point, all five parameters free (log least squares)."""
    from scipy.optimize import least_squares

    pub = _published()["6201"]
    pts, cut = pub["class_a1"], pub["cutoff"]

    def resid(x):
        t = Triode("fit", KorenTriode(*np.exp(x)))
        r = []
        for p in pts:
            vk = p["rk_ohm"] * p["ip_a"]
            vg, vp = -vk, p["supply_v"] - vk
            r += [
                np.log(t.ip(vg, vp) / p["ip_a"]),
                np.log(t.gm(vg, vp) / p["gm_s"]),
                np.log(t.rp(vg, vp) / p["rp_ohm"]),
            ]
        # "Approx.": the cutoff point weighs a tenth of the others.
        r.append(0.1 * np.log(t.ip(cut["vg_v"], cut["supply_v"]) / cut["ip_a"]))
        return r

    sol = least_squares(resid, np.log([60.0, 1.35, 460.0, 300.0, 300.0]), xtol=1e-14, ftol=1e-14)
    mu, ex, kg1, kp, kvb = (float(v) for v in np.exp(sol.x))
    res = np.asarray(sol.fun)
    caps = pub["capacitances_f"]
    return {
        "name": "6201",
        "kind": "triode",
        "source": f"fit: Koren triode to the class-A1 points at 250 and 100 V (Ip, gm, rp) and "
        f"the cutoff point, log least squares ({pub['source']})",
        "plate": {"model": "koren", "mu": mu, "ex": ex, "kg1": kg1, "kp": kp, "kvb": kvb},
        "grid_current": dict(PROVISIONAL_GRID),
        "capacitances_f": {
            "gk": caps["input"],
            "gp": caps["gp"],
            "pk": caps["output"],
            "source": f"{pub['source']} (input -> gk, output -> pk; no shield)",
        },
        "fit_report": {
            "class_a1_max_pct": float(100 * np.max(np.abs(np.expm1(res[:-1])))),
            "cutoff_ratio": float(np.exp(res[-1] / 0.1)),
        },
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


def build_6al5() -> dict[str, Any]:
    """A signal diode whose retarding-field region is the tube synth's exponential converter
    (TUBE_SYNTH_PLAN.md, S4). VacuumDiode's form is P (s softplus(V / s))^1.5: below zero
    its tail is P s^1.5 exp(1.5 V / s), the initial-velocity law I0 exp(V / V_T) when
    s = 1.5 V_T, so the slope is set from a measured one and the perveance from the
    forward curve (no new form). On the Phywe EC92 the same construction predicts the
    measured prefactor within ~10% (P ~2.6 mA/V^1.5 from its forward curve: 199 uA against
    182 uA), with no contact-potential offset needed."""
    pub = _published()
    d, ec = pub["6AL5"], pub["EC92_initial_current"]
    vt = 1.0 / ec["slope_per_v"]["heater_0_150_a"]
    s = 1.5 * vt
    v = np.array([p["va_v"] for p in d["plate_curve_tabulated"]])
    i = np.array([p["ia_a"] for p in d["plate_curve_tabulated"]])
    x = (s * np.logaddexp(0.0, v / s)) ** 1.5
    perv = float(np.sum(i * x) / np.sum(x * x))  # least squares through the origin
    return {
        "name": "6AL5",
        "kind": "vacuum_diode",
        "perveance": perv,
        "smooth_v": s,
        "source": f"Child-law least-squares fit to 10 tabulated points ({d['source']}); per "
        f"section. smooth_v = 1.5 V_T, V_T = {vt:.4f} V the retarding-field slope measured on an "
        f"EC92 at its rated heater current ({ec['source']}): the form's tail below 0 V is "
        "then the initial-velocity law I0 exp(V / V_T)",
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


def build_zpd8v2() -> dict[str, Any]:
    """The Clavinet E7's rail reference, a ZPD 8.2 zener (Hohner's E7 schematic): its
    breakdown slope as a junction diode, used with the `vr_tube` part (the diode in series
    with a fixed breakdown voltage, `operating_v` at `ref_current_a`)."""
    return {
        "name": "ZPD8V2",
        "kind": "junction_diode",
        "is_a": 1.0e-14,
        "n": 1.0,
        "rs_ohm": 5.0,
        "source": "provisional: model knowledge (a 500 mW 8.2 V zener of the ZPD / BZX55 "
        "class: Vz 7.7-8.7 V at 5 mA, dynamic resistance up to ~15 Ohm there; the slope "
        "nVt / I + rs ~10 Ohm at 5 mA; the knee's softness below ~1 mA isn't modelled). "
        "Hohner's E7 schematic names the 'ZPD 8,2' "
        "(data/schematics/hohner_clavinet_d6/clavinete7.jpg)",
    }


def build_zpd12() -> dict[str, Any]:
    """A 12 V zener of the ZPD / BZX55 class (the SSL 82E27's make-up reference, D3 '12V'),
    on ZPD8V2@1's breakdown slope, used with the `vr_tube` part."""
    return {
        "name": "ZPD12",
        "kind": "junction_diode",
        "is_a": 1.0e-14,
        "n": 1.0,
        "rs_ohm": 10.0,
        "source": "provisional: model knowledge (a 500 mW 12 V zener of the ZPD / BZX55 "
        "class: Vz 11.4-12.7 V at 5 mA, dynamic resistance up to ~20 Ohm there; the slope "
        "nVt / I + rs ~15 Ohm at 5 mA; the knee isn't modelled). The SSL 82E27 prints only "
        "'12v' (data/schematics/ssl_bus_comp/README.md)",
    }


def build_1n4148() -> dict[str, Any]:
    """The 1N4148 small-signal diode (the SSL side chain's unmarked signal diodes)."""
    return {
        "name": "1N4148",
        "kind": "junction_diode",
        "is_a": 2.52e-9,
        "n": 1.752,
        "rs_ohm": 0.568,
        "source": "the 1N4148 SPICE model's DC parameters (IS 2.52n, N 1.752, RS 0.568; "
        "mfg=OnSemi, as LTspice 24's lib/cmp/standard.dio distributes it)",
    }


def _jfet_component(name: str, polarity: str, dc: dict, par: dict, source: str,
                    dc_source: str) -> dict[str, Any]:  # fmt: skip
    """A JFET component (kind `jfet`, varimu.devices.jfet): the DC parameters and the
    parasitics (RD, RS; CGS, CGD at zero bias) of a published card, as numbers with their
    source (the card's own text isn't kept: its licence forbids redistribution)."""
    return {
        "name": name,
        "kind": "jfet",
        "source": source,
        "polarity": polarity,
        "dc": {**dc, "source": dc_source},
        "parasitics": {
            **par,
            "source": "the card's RD, RS and its CGS, CGD at zero bias (linear elements of "
            "the jfet part, varimu.devices.jfet)",
        },
    }


def build_j175() -> dict[str, Any]:
    """The J175 P-channel JFET (the SSL 82E26's COMP IN / OUT switch, TR4)."""
    return _jfet_component(
        "J175",
        "pjf",
        {
            "vto_v": -3.0,
            "beta_a_per_v2": 5.0e-3,
            "lambda_per_v": 1.2e-3,
            "is_a": 6.58e-15,
            "pb_v": 1.0,
        },  # fmt: skip
        {"rd_ohm": 21.0, "rs_ohm": 18.9, "cgs_f": 12.5e-12, "cgd_f": 17.1e-12},
        "Central Semiconductor's CMPFJ175 SPICE model (the SMD J175; 30 V 25 mA 150 Ohm "
        "class): data/datasheets/transistors/README.md",
        "web: https://central.aeminc.com/docs/ENGINEERING/CSM/CSM1481.LIB (CMPFJ175, "
        "7/15/24 rev A: VTO -3.00, BETA 5.00m, LAMBDA 1.20m, IS 6.58f, PB 1.00)",
    )


def build_2n3819() -> dict[str, Any]:
    """The 2N3819 N-channel JFET (the 1176's voltage-variable resistor class)."""
    return _jfet_component(
        "2N3819",
        "njf",
        {
            "vto_v": -2.5,
            "beta_a_per_v2": 1.7524e-3,
            "lambda_per_v": 0.02,
            "is_a": 1.0e-20,
            "pb_v": 0.39253,
        },  # fmt: skip
        {"rd_ohm": 0.0, "rs_ohm": 0.0, "cgs_f": 3.5966e-12, "cgd_f": 7.0632e-12},
        "Central Semiconductor's 2N3819 SPICE model (data/datasheets/transistors/README.md); "
        "its datasheet's IDSS 2-20 mA, VGS(off) up to -8 V "
        "(data/datasheets/transistors/central_2N3819.pdf). The card's gate-diode NR 9.99 / "
        "ALPHA / VK (breakdown fit artefacts) aren't in the level-1 model",
        "web: https://central.aeminc.com/docs/ENGINEERING/CSM/CSM1455.LIB (2N3819, 6/25/24 "
        "rev A: VTO -2.5, BETA 1.7524m, LAMBDA 0.02, IS 10.000E-21, PB .39253)",
    )


def build_pn4092() -> dict[str, Any]:
    """The PN4092 N-channel switching JFET (the 50 ohm chopper class; the Minimoog
    oscillator's reset switch, an E112, stands on it: docs/MINIMOOG_PLAN.md MM3)."""
    return _jfet_component(
        "PN4092",
        "njf",
        {
            "vto_v": -3.25,
            "beta_a_per_v2": 27.5e-3,
            "lambda_per_v": 851e-6,
            "is_a": 14.8e-15,
            "pb_v": 1.0,
        },  # fmt: skip
        {"rd_ohm": 4.87, "rs_ohm": 4.38, "cgs_f": 50.4e-12, "cgd_f": 7.50e-12},
        "Central Semiconductor's PN4092 SPICE model (the TO-92 2N4092: 40 V 75 mA, the card's "
        "header 34.8 Ohm on)",
        "web: https://central.aeminc.com/docs/ENGINEERING/CSM/CSM1471.LIB (PN4092, 7/2/24 rev "
        "A: VTO -3.25, BETA 27.5m, LAMBDA 851u, IS 14.8f, PB 1.00, FC .5)",
    )


# The 2N5457's channel-length modulation, read off onsemi 2N5457/D Figure 2 (the same unit as
# Figure 3): ~1.1e-3 / V at VGS = 0 and ~1.7e-3 at -0.2 V (data/datasheets/
# onsemi_2n5457.provenance.yaml, notes).
ONSEMI_2N5457_LAMBDA = 1.4e-3
# PB (the gate junction's potential) only shapes the doping tail; Central's card's value.
CENTRAL_2N5457_PB = 0.3905


def fit_2n5457() -> tuple[dict[str, float], dict[str, float]]:
    """VTO, BETA and the doping tail B fitted by least squares to onsemi 2N5457/D Figure 3
    (one unit, VDS 15 V: the saturated level-1 law, varimu.devices.jfet), in mA; returns the
    parameters and the fit's residuals."""
    from scipy.optimize import least_squares

    vgs, vds, i_d = load_csv("onsemi_2n5457_transfer.csv").T

    def model(p):
        vto, beta, b = p
        vgst = np.maximum(vgs - vto, 0.0)
        bfac = (1 - b) / (CENTRAL_2N5457_PB - vto)
        return beta * (1 + ONSEMI_2N5457_LAMBDA * vds) * vgst**2 * (b + bfac * vgst)

    r = least_squares(lambda p: (model(p) - i_d) * 1e3, [-1.2, 0.7e-3, 1.0])
    res = model(r.x) - i_d
    p = {"vto_v": float(r.x[0]), "beta_a_per_v2": float(r.x[1]), "b": float(r.x[2])}
    return p, {"rms_a": float(np.sqrt(np.mean(res**2))), "max_a": float(np.max(np.abs(res)))}


def build_2n5457() -> dict[str, Any]:
    """The 2N5457 N-channel JFET: the 1176's VVR FET as repairers replace it (Rev F's "UREI
    13-0027" is a selected house part; data/schematics/urei_1176/README.md, open questions).

    Version 2 (2026-11-06): onsemi's sheet's Figure 3 unit (VGS(off) ~-1.2 V, IDSS ~1.05 mA),
    fitted (fit_2n5457). Version 1 was Central's card (VTO -1.47 V, BETA 1.63 mA/V^2): twice
    as steep as onsemi's measured unit, and its CGD a slipped exponent."""
    p, fit = fit_2n5457()
    data = {
        **_jfet_component(
            "2N5457",
            "njf",
            {
                **p,
                "lambda_per_v": ONSEMI_2N5457_LAMBDA,
                "is_a": 783.14e-18,
                "pb_v": CENTRAL_2N5457_PB,
            },  # fmt: skip
            {"rd_ohm": 60.461, "rs_ohm": 60.461, "cgs_f": 3.0e-12, "cgd_f": 1.5e-12},
            "onsemi 2N5457/D Rev. 6 (data/schematics/urei_1176/2N5457-D.PDF): the Figure 3 "
            "unit, a 2N5457 whose VGS(off) (~-1.2 V) the 1176's Q-bias network reaches (the "
            "table's typical part, VGS(off) ~-3 V, it can't). cgs_f, cgd_f: the table's "
            "typical Ciss 4.5 pF and Crss 1.5 pF (CGS = Ciss - Crss). rd_ohm, rs_ohm, is_a, "
            "pb_v: Central's card (web: https://central.aeminc.com/docs/ENGINEERING/CSM/"
            "2N5457_CSM.LIB, RD = RS 60.461, IS 783.14E-18, PB .3905): the sheet gives none",
            "fit: vto_v, beta_a_per_v2 and b by least squares to onsemi 2N5457/D Figure 3 "
            "(data/datasheets/onsemi_2n5457_transfer.csv, its provenance sidecar; "
            "library.fit_2n5457), VDS 15 V, lambda_per_v from Figure 2 "
            "(ONSEMI_2N5457_LAMBDA)",
        ),
        "fit_report": {"rms_error_a": fit["rms_a"], "max_error_a": fit["max_a"]},
    }
    data["parasitics"]["source"] = (
        "rd_ohm, rs_ohm: Central's card's RD, RS; cgs_f, cgd_f: onsemi's typical Ciss - "
        "Crss and Crss (linear elements of the jfet part, varimu.devices.jfet)"
    )
    return data


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


VF14_FIT_IA_MAX, VF14_FIT_VA_MAX = 10e-3, 200.0


def build_vf14t() -> dict[str, Any]:
    """The VF14M triode-connected (g2 and g3 on the anode), the Neumann U47's tube: a Koren
    triode fit to Telefunken's triode-connected plate and transfer curves (Funkschau
    1/1948, Kennlinienfeld 8 and 7). The curves plot the anode lead's current (Ia + Ig2 +
    Ig3), which is the triode connection's plate current."""
    pub = _published()["VF14"]
    pl = load_csv("telefunken_vf14_triode_plate.csv")  # vg1, va, ia
    tr = load_csv("telefunken_vf14_triode_transfer.csv")  # va, vg1, ia
    vg = np.r_[pl[:, 0], tr[:, 1]]
    va = np.r_[pl[:, 1], tr[:, 0]]
    ia = np.r_[pl[:, 2], tr[:, 2]]
    # The U47's region: a Koren triode can't follow this triode-connected pentode from
    # 0.3 to 37 mA (43% rms, mu 35); up to 10 mA and 200 V it does (mu 27).
    k = (ia <= VF14_FIT_IA_MAX) & (va <= VF14_FIT_VA_MAX)
    vg, va, ia = vg[k], va[k], ia[k]
    m, rep = fit_koren_triode(vg, va, ia, np.hypot(0.03 * ia, 0.03e-3), ex_min=1.0)
    caps = pub["ef14_capacitances_f"]["g3_at_anode"]
    return {
        "name": "VF14T",
        "kind": "triode",
        "source": "fit: Koren triode, least squares on the Telefunken VF 14 triode-connected "
        "plate and transfer curves (Funkschau 1/1948 Kennlinienfeld 8, 7), digitized: "
        "data/datasheets/telefunken_vf14.provenance.yaml, the points up to 10 mA and 200 V (the "
        "U47's region; from 0.3 mA: the low end runs into the axis). At the rated heater: the "
        "U47 underheats it (B6's heater block)",
        "plate": {"model": "koren", "mu": m.mu, "ex": m.ex, "kg1": m.kg1, "kp": m.kp, "kvb": m.kvb},
        "grid_current": dict(PROVISIONAL_GRID),
        "capacitances_f": {
            "gk": 6.5e-12,
            "gp": caps["input"] - 6.5e-12,
            "pk": caps["output"],
            "source": "provisional: none printed for the triode connection; the EF 14's "
            "with g3 on the anode (input 9.5 pF, output 10 pF: published_points.yaml VF14 "
            "ef14_capacitances_f) with ~3 pF of the input taken as g1 to g2, which the "
            "triode connection puts on the anode (model knowledge)",
        },
        "fit_report": {"plate": rep.as_dict(), "sigma": "hypot(3% of Ia, 30 uA)"},
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


def _pentode_plate_points(stem: str) -> np.ndarray:
    """A sheet's transfer and plate curves (data/datasheets/<stem>_{transfer,plate}.csv)
    as fit_koren_pentode's plate points (vg1, vg2, vp, ip)."""
    tr = load_csv(f"{stem}_transfer.csv")  # va, vg2, vg1, ia
    pl = load_csv(f"{stem}_plate.csv")  # vg2, vg1, va, ia
    return np.r_[
        np.c_[tr[:, 2], tr[:, 1], tr[:, 0], tr[:, 3]],
        np.c_[pl[:, 1], pl[:, 0], pl[:, 2], pl[:, 3]],
    ]


def build_ef804s() -> dict[str, Any]:
    """The EF804S, the V76's V1-V3: a Koren pentode fit to Telefunken's transfer and
    plate curves. The sheet has no screen-current curves: the screen law is fitted to its
    tabulated screen currents (the measuring point and the RC amplifier's columns), each
    at the grid voltage the plate curves give for its printed plate current (the table's
    own cathode voltages disagree with the curves by ~0.6 V of grid)."""
    from scipy.optimize import brentq

    pub = _published()["EF804S"]
    plate = _pentode_plate_points("telefunken_ef804s")
    plate_sigma = np.hypot(0.02 * plate[:, 3], 0.03e-3)
    a = pub["class_a1"]
    vk = (a["ip_a"] + a["ig2_a"]) * a["rk_ohm"]
    meas = (-vk, a["vg2_v"] - vk, a["vp_v"] - vk, a["ip_a"], a["ig2_a"])
    rows = [r for r in pub["rc_amplifier"] if "derived_vgk_v" in r]

    def fit(screen):
        s = np.asarray(screen, float)
        return fit_koren_pentode(
            plate, s, plate_sigma, np.hypot(0.10 * s[:, 2], 5e-6), screen_law="e1"
        )

    m, _, _ = fit([meas[0:2] + meas[4:5]])
    screen, shifts = [(meas[0], meas[1], meas[4])], []
    for r in rows:
        vak, vg2k, ip = r["derived_vak_v"], r["derived_vg2k_v"], r["ip_a"]
        vg1 = brentq(lambda g, vak=vak, vg2k=vg2k, ip=ip: m.ip(g, vg2k, vak) - ip, -8.0, 0.0)
        screen.append((vg1, vg2k, r["ig2_a"]))
        shifts.append(vg1 - r["derived_vgk_v"])
    m, rp, rs = fit(screen)
    caps = pub["capacitances_f"]
    return {
        "name": "EF804S",
        "kind": "pentode",
        "source": "fit: Koren pentode, least squares on the Telefunken EF 804 S transfer and "
        "plate curves, digitized: data/datasheets/telefunken_ef804s.provenance.yaml. Screen "
        f"law: the sheet's {len(screen)} tabulated screen currents (p.331 measuring point, "
        "p.332 RC amplifier), each at the grid voltage the plate curves give for its plate "
        f"current (the table's own grid voltages are {min(shifts):+.2f}..{max(shifts):+.2f} V "
        "from those); no screen curves are published. Screen law 'e1' (the plate's E1: "
        "Koren's hard cutoff gave no screen current at the V76's V1, varimu/devices/pentode.py)",
        "model": {
            "mu": m.mu,
            "ex": m.ex,
            "kg1": m.kg1,
            "kg2": m.kg2,
            "kp": m.kp,
            "kvb": m.kvb,
            "screen": "e1",
        },
        "grid_current": dict(PROVISIONAL_GRID),
        "capacitances_f": {
            "g1k": caps["input"],
            "g1p": caps["ag1_max"],
            "pk": caps["output"],
            "source": f"{pub['source']}; g1p the printed maximum",
        },
        "fit_report": {
            "plate": rp.as_dict(),
            "screen": rs.as_dict(),
            "sigma": "plate hypot(2%, 30 uA), screen hypot(10%, 5 uA)",
        },
    }


def build_e83f() -> dict[str, Any]:
    """The E83F, the V76's output tube V4: a Koren pentode fit to Philips' transfer, plate
    and screen curves."""
    pub = _published()["E83F"]
    plate = _pentode_plate_points("philips_e83f")
    sc = load_csv("philips_e83f_screen.csv")  # va, vg1, vg2, ig2
    screen = np.c_[sc[:, 1], sc[:, 2], sc[:, 3]]
    m, rp, rs = fit_koren_pentode(
        plate,
        screen,
        np.hypot(0.02 * plate[:, 3], 0.1e-3),
        np.hypot(0.03 * screen[:, 2], 0.05e-3),
        screen_law="e1",
    )
    caps = pub["capacitances_f"]
    return {
        "name": "E83F",
        "kind": "pentode",
        "source": "fit: Koren pentode, least squares on the Philips E83F transfer, plate and "
        "screen curves, digitized: data/datasheets/philips_e83f.provenance.yaml. Screen law "
        "'e1' (the plate's E1; Koren's law fitted the screen curves to 36% rms, e1 to ~7%)",
        "model": {
            "mu": m.mu,
            "ex": m.ex,
            "kg1": m.kg1,
            "kg2": m.kg2,
            "kp": m.kp,
            "kvb": m.kvb,
            "screen": "e1",
        },
        "grid_current": dict(PROVISIONAL_GRID),
        "capacitances_f": {
            "g1k": caps["input"],
            "g1p": caps["ag1_max"],
            "pk": caps["output"],
            "source": f"{pub['source']}; g1p the printed maximum",
        },
        "fit_report": {
            "plate": rp.as_dict(),
            "screen": rs.as_dict(),
            "sigma": "plate hypot(2%, 0.1 mA), screen hypot(3%, 50 uA)",
        },
    }


def build_bk4134() -> dict[str, Any]:
    """The B&K Type 4134 1/2-inch pressure microphone's capsule (MIC_ROOM_PLAN.md A2: the
    capsule machinery's verification case): its geometry and materials as published
    (data/datasheets/published_points.yaml "BK4134"; data/schematics/bk_4134/README.md),
    the lumped elements derived from them (varimu.devices.capsule.lumped)."""
    from varimu.devices import capsule

    pub = _published()["BK4134"]
    geom = pub["geometry"]
    return {
        "name": "BK4134",
        "kind": "capsule",
        "source": f"derived: varimu.devices.capsule.lumped on the geometry ({pub['source']})",
        "geometry": geom,
        "lumped": capsule.lumped(geom),
        "lumped_source": "derived: varimu/devices/capsule.py's formulas (its docstring) on "
        "the geometry; air at 20 C",
    }


def _plain(x: Any) -> Any:
    """A geometry block with {value: ...} leaves as plain numbers."""
    if isinstance(x, dict):
        if set(x) == {"value"}:
            return x["value"]
        return {k: _plain(v) for k, v in x.items()}
    if isinstance(x, list):
        return [_plain(v) for v in x]
    return x


def build_k47() -> dict[str, Any]:
    """Neumann's K47 dual-diaphragm capsule (the U47's KK47; MIC_ROOM_PLAN.md A3): its
    geometry (published_points.yaml "K47": what is known sourced, the rest bounded and
    fitted to Neumann's curves by scripts/fit_k47.py), the lumped network derived from it
    (varimu.devices.capsule.dual_lumped)."""
    from varimu.devices import capsule

    pub = _published()["K47"]
    geom = _plain(pub["geometry"])
    return {
        "name": "K47",
        "kind": "capsule",
        "form": "dual",
        "source": f"derived: varimu.devices.capsule.dual_lumped on the geometry ({pub['source']})",
        "geometry": geom,
        "lumped": capsule.dual_lumped(geom),
        "lumped_source": "derived: varimu/devices/capsule.py's formulas (dual_lumped's "
        "docstring) on the geometry; air at 20 C",
    }


def build_ck12() -> dict[str, Any]:
    """AKG's CK12 dual-diaphragm capsule (the C12's; docs/CHAINS_PLAN.md WP3): its geometry
    (published_points.yaml "CK12": bounded by what is published, fitted to AKG's curves by
    scripts/fit_ck12.py), the lumped network derived from it
    (varimu.devices.capsule.dual_lumped: the slit between the resistance disks as the
    through resistance)."""
    from varimu.devices import capsule

    pub = _published()["CK12"]
    geom = _plain(pub["geometry"])
    return {
        "name": "CK12",
        "kind": "capsule",
        "form": "dual",
        "source": f"derived: varimu.devices.capsule.dual_lumped on the geometry ({pub['source']})",
        "geometry": geom,
        "lumped": capsule.dual_lumped(geom),
        "lumped_source": "derived: varimu/devices/capsule.py's formulas (dual_lumped's "
        "docstring) on the geometry; air at 20 C",
    }


def build_k87() -> dict[str, Any]:
    """Neumann's K87 dual-diaphragm capsule (the U 87's; docs/CHAINS_PLAN.md WP22): its geometry
    (published_points.yaml "K87": the spacer and sizes published, the network fitted to Neumann's
    curves by scripts/fit_k87.py), the lumped network derived from it as the CK12's."""
    from varimu.devices import capsule

    pub = _published()["K87"]
    geom = _plain(pub["geometry"])
    return {
        "name": "K87",
        "kind": "capsule",
        "form": "dual",
        "source": f"derived: varimu.devices.capsule.dual_lumped on the geometry ({pub['source']})",
        "geometry": geom,
        "lumped": capsule.dual_lumped(geom),
        "lumped_source": "derived: varimu/devices/capsule.py's formulas (dual_lumped's "
        "docstring) on the geometry; air at 20 C",
    }


def build_kk84() -> dict[str, Any]:
    """Neumann's KK 84 cardioid capsule (the KM 84's; docs/CHAINS_PLAN.md WP24), in the
    dual-diaphragm form at the cardioid setting (published_points.yaml "KK84": the network fitted
    to the KM 84 i's curves by scripts/fit_kk84.py)."""
    from varimu.devices import capsule

    pub = _published()["KK84"]
    geom = _plain(pub["geometry"])
    return {
        "name": "KK84",
        "kind": "capsule",
        "form": "dual",
        "source": f"derived: varimu.devices.capsule.dual_lumped on the geometry ({pub['source']})",
        "geometry": geom,
        "lumped": capsule.dual_lumped(geom),
        "lumped_source": "derived: varimu/devices/capsule.py's formulas (dual_lumped's "
        "docstring) on the geometry; air at 20 C",
    }


def build_r57() -> dict[str, Any]:
    """The SM57's Unidyne III cartridge, Shure's replacement part R57 (docs/SM57_PLAN.md
    SM2): its geometry (published_points.yaml "R57": sourced where a source exists, the
    rest provisional, bounded and fitted by scripts/fit_sm57.py), the lumped network
    compiled from it (varimu.devices.moving_coil.compile_network)."""
    from varimu.devices import moving_coil

    pub = _published()["R57"]
    geom = _plain(pub["geometry"])
    return {
        "name": "R57",
        "kind": "moving_coil",
        "source": "derived: varimu.devices.moving_coil.compile_network on the geometry "
        f"({pub['source']})",
        "geometry": geom,
        "lumped": moving_coil.compile_network(geom),
        "lumped_source": "derived: varimu/devices/moving_coil.py's formulas (its docstring) on "
        "the geometry; air at 20 C",
    }


def build_r59() -> dict[str, Any]:
    """The SM58's Unidyne III cartridge, Shure's replacement R59 (s70: 99B352; docs/SM57_PLAN.md
    SM8): its geometry (published_points.yaml "R59": the R57's network without its resonator
    cap, on the ball grille's body; fitted by scripts/fit_sm57.py --mic sm58), compiled as
    R57's (varimu.devices.moving_coil.compile_network)."""
    from varimu.devices import moving_coil

    pub = _published()["R59"]
    geom = _plain(pub["geometry"])
    return {
        "name": "R59",
        "kind": "moving_coil",
        "source": "derived: varimu.devices.moving_coil.compile_network on the geometry "
        f"({pub['source']})",
        "geometry": geom,
        "lumped": moving_coil.compile_network(geom),
        "lumped_source": "derived: varimu/devices/moving_coil.py's formulas (its docstring) on "
        "the geometry; air at 20 C",
    }


def build_r_d112() -> dict[str, Any]:
    """The AKG D112's moving-coil cartridge with its bass chamber (docs/CHAINS_PLAN.md WP9
    step 2): its geometry (published_points.yaml "R_D112": no construction is published, so
    every dimension is bounded and fitted by scripts/fit_d112.py), the lumped network compiled
    from it as R57's (varimu.devices.moving_coil.compile_network)."""
    from varimu.devices import moving_coil

    pub = _published()["R_D112"]
    geom = _plain(pub["geometry"])
    return {
        "name": "R_D112",
        "kind": "moving_coil",
        "source": "derived: varimu.devices.moving_coil.compile_network on the geometry "
        f"({pub['source']})",
        "geometry": geom,
        "lumped": moving_coil.compile_network(geom),
        "lumped_source": "derived: varimu/devices/moving_coil.py's formulas (its docstring) on "
        "the geometry; air at 20 C",
    }


def build_r_md421() -> dict[str, Any]:
    """The Sennheiser MD 421-II's moving-coil cartridge (docs/CHAINS_PLAN.md WP14
    step 2): its geometry (published_points.yaml "R_MD421": no construction is published, so
    every dimension is bounded and fitted by scripts/fit_md421.py), the lumped network compiled
    from it as R57's (varimu.devices.moving_coil.compile_network)."""
    from varimu.devices import moving_coil

    pub = _published()["R_MD421"]
    geom = _plain(pub["geometry"])
    return {
        "name": "R_MD421",
        "kind": "moving_coil",
        "source": "derived: varimu.devices.moving_coil.compile_network on the geometry "
        f"({pub['source']})",
        "geometry": geom,
        "lumped": moving_coil.compile_network(geom),
        "lumped_source": "derived: varimu/devices/moving_coil.py's formulas (its docstring) on "
        "the geometry; air at 20 C",
    }


def build_r_sm7() -> dict[str, Any]:
    """The Shure SM7's moving-coil cartridge (docs/CHAINS_PLAN.md WP15): its geometry
    (published_points.yaml "R_SM7": no construction is published, so every dimension is bounded
    and fitted by scripts/fit_sm7.py), the lumped network compiled from it as R57's
    (varimu.devices.moving_coil.compile_network)."""
    from varimu.devices import moving_coil

    pub = _published()["R_SM7"]
    geom = _plain(pub["geometry"])
    return {
        "name": "R_SM7",
        "kind": "moving_coil",
        "source": "derived: varimu.devices.moving_coil.compile_network on the geometry "
        f"({pub['source']})",
        "geometry": geom,
        "lumped": moving_coil.compile_network(geom),
        "lumped_source": "derived: varimu/devices/moving_coil.py's formulas (its docstring) on "
        "the geometry; air at 20 C",
    }


def build_ribbon_44bx() -> dict[str, Any]:
    """The RCA 44-BX's ribbon motor (docs/CHAINS_PLAN.md WP5): its geometry
    (published_points.yaml "RIBBON_44BX": the ribbon from AEA's R44 sheet, the motor after
    Olson's circuit, the rest provisional until WP6 fits it to the 44-BX's curves), the
    lumped network compiled from it (varimu.devices.ribbon.compile_network)."""
    from varimu.devices import ribbon

    pub = _published()["RIBBON_44BX"]
    geom = _plain(pub["geometry"])
    return {
        "name": "RIBBON_44BX",
        "kind": "ribbon_motor",
        "source": "derived: varimu.devices.ribbon.compile_network on the geometry "
        f"({pub['source']})",
        "geometry": geom,
        "lumped": ribbon.compile_network(geom),
        "lumped_source": "derived: varimu/devices/ribbon.py's and moving_coil.py's formulas "
        "(their docstrings) on the geometry; air at 20 C",
    }


def build_ribbon_4038() -> dict[str, Any]:
    """The STC 4038's (BBC PGS) ribbon motor (docs/CHAINS_PLAN.md WP8): its geometry
    (published_points.yaml "RIBBON_4038": the ribbon, gap and screens from BBC Engineering
    Monograph No. 4, the body, tuning and gap flux fitted by scripts/fit_4038.py), the
    lumped network compiled from it (varimu.devices.ribbon.compile_network)."""
    from varimu.devices import ribbon

    pub = _published()["RIBBON_4038"]
    geom = _plain(pub["geometry"])
    return {
        "name": "RIBBON_4038",
        "kind": "ribbon_motor",
        "source": "derived: varimu.devices.ribbon.compile_network on the geometry "
        f"({pub['source']})",
        "geometry": geom,
        "lumped": ribbon.compile_network(geom),
        "lumped_source": "derived: varimu/devices/ribbon.py's and moving_coil.py's formulas "
        "(their docstrings) on the geometry; air at 20 C",
    }


def build_ribbon_77dx() -> dict[str, Any]:
    """The RCA 77-DX's ribbon motor (docs/CHAINS_PLAN.md WP7): its geometry
    (published_points.yaml "RIBBON_77DX": the ribbon from IB-24884-2's parts list on Olson's
    polydirectional circuit, the shutter as the slot's stops, the unprinted dimensions fitted
    by scripts/fit_77dx.py), the lumped network compiled from it, one element set per stop
    (varimu.devices.ribbon.compile_network)."""
    from varimu.devices import ribbon

    pub = _published()["RIBBON_77DX"]
    geom = _plain(pub["geometry"])
    return {
        "name": "RIBBON_77DX",
        "kind": "ribbon_motor",
        "source": "derived: varimu.devices.ribbon.compile_network on the geometry "
        f"({pub['source']})",
        "geometry": geom,
        "stops": ["N", "L-3", "U", "L-2", "L-1", "B"],
        "lumped": ribbon.compile_network(geom),
        "lumped_source": "derived: varimu/devices/ribbon.py's and moving_coil.py's formulas "
        "(their docstrings) on the geometry; air at 20 C",
    }


def build_ribbon_m160() -> dict[str, Any]:
    """The beyerdynamic M 160's ribbon motor (docs/CHAINS_PLAN.md WP17): its geometry
    (published_points.yaml "RIBBON_M160": the double ribbon as one equivalent ribbon on
    RIBBON_77DX's circuit with one fixed slot, fitted by scripts/fit_m160.py), the lumped
    network compiled from it (varimu.devices.ribbon.compile_network)."""
    from varimu.devices import ribbon

    pub = _published()["RIBBON_M160"]
    geom = _plain(pub["geometry"])
    return {
        "name": "RIBBON_M160",
        "kind": "ribbon_motor",
        "source": "derived: varimu.devices.ribbon.compile_network on the geometry "
        f"({pub['source']})",
        "geometry": geom,
        "lumped": ribbon.compile_network(geom),
        "lumped_source": "derived: varimu/devices/ribbon.py's and moving_coil.py's formulas "
        "(their docstrings) on the geometry; air at 20 C",
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


def build_b450c80() -> dict[str, Any]:
    """One arm of a B 450 C 80 selenium bridge (the V76's rectifier, GR94 on IRT drawing
    S 1176): a stack of SELENIUM cells in series. n cells of area A in series are one
    junction diode with n times the emission coefficient and series resistance, is and
    rs scaled by the area."""
    cell = build_selenium()
    pub = _published()["SELENIUM"]
    rms_v, rms_per_cell = 450.0, pub["rms_v_per_cell_max"]
    n_cells = math.ceil(rms_v / rms_per_cell)
    load_a, a_per_in2 = 0.080, 0.8 * pub["bridge_dc_a"]["2"]
    area = load_a / a_per_in2
    return {
        "name": "B450C80",
        "kind": "junction_diode",
        "is_a": cell["is_a"] * area,
        "n": cell["n"] * n_cells,
        "rs_ohm": cell["rs_ohm"] * n_cells / area,
        "source": f"derived: {n_cells} SELENIUM cells of {area:.3f} sq. in. in series per arm. "
        "The DIN code B 450 C 80 reads 'bridge, 450 V rms AC connection, 80 mA into a "
        "capacitor' (provisional: model knowledge); cells per arm: 450 V over Tarzian's "
        f"{rms_per_cell} V rms per cell, rounded up; area: 80 mA over Tarzian's capacitor-"
        "input rating of a 1 sq. in. cell, 80% of 0.225 A (Sarkes Tarzian handbook 1950, "
        "data/datasheets/published_points.yaml). The German maker's cells (not documented) "
        f"stand in for Tarzian's. The cell: {cell['source']}",
        "stack": {
            "cells_per_arm": n_cells,
            "area_in2": area,
            "source": "the derivation above; the arm's capacitance is the circuit's",
        },
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


def build_p12r() -> dict[str, Any]:
    """The 5E3's speaker: the Jensen P12R reissue (8 ohm), its sheet's Thiele-Small figures
    with the voice coil's eddy-current pair and eight breakup modes fitted to its response
    and impedance curves (varimu.devices.speaker_fit)."""
    from varimu.devices import speaker_fit

    pub = _published()["P12R"]
    ts = pub["thiele_small"]
    fit = speaker_fit.fit(ts, speaker_fit.load_curves(DATASHEETS, "jensen_p12r"), "P12R")
    s = fit.speaker
    sheet = "web: " + pub["source"].split("(web: ")[1].rstrip(")")
    return {
        "name": "P12R",
        "kind": "speaker",
        "source": "fit: varimu.devices.speaker_fit on the Jensen P12R reissue sheet (2022), "
        "8 ohm: its Thiele-Small table (data/datasheets/published_points.yaml P12R) and its "
        "response (IEC baffle, 2.83 V, 1 m) and free-air impedance curves (digitized: "
        "data/datasheets/jensen_p12r.provenance.yaml)",
        "voice_coil": {
            "re_ohm": s.re_ohm,
            "le_h": s.le_h,
            "l2_h": s.l2_h,
            "r2_ohm": s.r2_ohm,
            "source": f"Re: {sheet} (Re); Le, L2 || R2 (eddy-current 'LR-2' model): fit to the "
            "impedance curve's shape and the response",
        },
        "moving_system": {
            "mms_kg": s.mms_kg,
            "cms_m_per_n": s.cms_m_per_n,
            "rms_ns_per_m": s.rms_ns_per_m,
            "bl_tm": s.bl_tm,
            "sd_m2": s.sd_m2,
            "source": f"{sheet} (Mms, Cms, BxL, Sd; Rms = 2 pi Fs Mms / Qms with Fs 80 Hz, "
            "Qms 13.07): free-air figures, the air load included",
        },
        "modes": {
            "list": [
                {"mass_kg": m.mass_kg, "f_hz": m.f_hz, "q": m.q, "area_m2": m.area_m2}
                for m in sorted(s.modes, key=lambda m: m.f_hz)
            ],
            "source": "fit: a modal expansion of the cone's breakup (signed radiating "
            "shares, not ring geometry) to the response on the IEC baffle and the impedance "
            "shape; modes from 300 Hz up, each at most the cone's area",
        },
        "fit_report": fit.report,
    }


# The decay curves' frequency grid: third octaves from 50 Hz to the plot's end (~14 kHz).
EMT140_GRID_HZ = [
    50.0,
    63.0,
    80.0,
    100.0,
    125.0,
    160.0,
    200.0,
    250.0,
    315.0,
    400.0,
    500.0,
    630.0,
    800.0,
    1000.0,
    1250.0,
    1600.0,
    2000.0,
    2500.0,
    3150.0,
    4000.0,
    5000.0,
    6300.0,
    8000.0,
    10000.0,
    12500.0,
    14000.0,
]


# The stereo plates' second pickups (fractions of the sides; the builds' sources): placed by
# scripts/plate_pickups.py, each about as loud as the first pickup per octave (125 Hz-2 kHz)
# and uncorrelated with it, on the exciter's other side at an unequal distance.
EMT140_PICKUP2_XY = [0.75, 0.55]
EMT240_PICKUP2_XY = [0.8, 0.3]


def build_emt140() -> dict[str, Any]:
    """An EMT 140 plate (docs/REVERB_PLAN.md, E6): the plate and its suspension from the
    literature's model of it, its decay against frequency for three damper settings from
    the 1971 brochure's plot (data/datasheets/emt_140ts_decay.csv, put on third octaves),
    and provisional transducers (the exciter's and pickups' data aren't published)."""
    rows = load_csv("emt_140ts_decay.csv")  # curve_t500_s, f_hz, t60_s
    curves = []
    for label in sorted(set(rows[:, 0].tolist()), reverse=True):
        sel = rows[:, 0] == label
        f, t60 = rows[sel, 1], rows[sel, 2]
        # Linear in log frequency, held past the curve's ends (the 4,5 s curve below
        # 100 Hz, every curve above the plot's ~14 kHz).
        on_grid = np.interp(np.log(EMT140_GRID_HZ), np.log(f), t60)
        curves.append({"label_s": label, "t60_s": [round(float(v), 3) for v in on_grid]})
    brochure = "data/datasheets/emt_140ts.provenance.yaml"
    russo = "web: https://projekter.aau.dk/projekter/files/517547034/Master_Thesis_Russo.pdf"
    ducceschi = "web: https://mdphys.org/PDF/icaPLA_2016.pdf"
    return {
        "name": "EMT140",
        "kind": "plate",
        "source": "the EMT 140's plate as the literature models it (Russo 2021, Ducceschi & "
        "Webb 2016), its measured decay curves (EMT 140 TS brochure, 1971) and provisional "
        "transducers; varimu.devices.plate",
        "plate": {
            "lx_m": 2.0,
            "ly_m": 1.0,
            "thickness_m": 0.5e-3,
            "density_kg_m3": 7872.0,
            "youngs_pa": 2.0e11,
            "poisson": 0.3,
            "tension_n_m": 600.0,
            "source": f"{russo} (pp.3, 48: 2 m x 1 m, 0.5 mm, SAE 1010 steel: E 2e11 Pa, "
            f"nu 0.3, rho 7872 kg/m^3); tension: provisional, {ducceschi} (§6: '600N' for "
            "a 2 m x 1 m x 0.5 mm steel plate, read as N/m; the EMT's tension isn't published)",
        },
        "positions": {
            "drive_xy": [0.52, 0.53],
            "pickup_xy": [0.47, 0.62],
            "pickup2_xy": EMT140_PICKUP2_XY,
            "source": f"provisional: {ducceschi} (Fig. 3) and {russo} (p.48): the models' "
            "exciter and pickup, fractions of the sides; the brochure (pp.3-4) puts the "
            "exciter on the middle of three bridges across the frame and two pickups at "
            "unequal distances either side, without dimensions; pickup2_xy (the 140 TS's "
            "second pickup): provisional, on the exciter's other side from the first and "
            "farther from it (0.46 m against 0.13 m), as the brochure (p.6) has the two "
            "'mounted at unequal distances from the driving coil' so their outputs are "
            "'entirely uncorrelated'; placed where it is as loud as the first per octave "
            "(125 Hz-2 kHz, within 1.6 dB) and uncorrelated with it (|r| <= 0.11): "
            "scripts/plate_pickups.py",
        },
        "exciter": {
            "re_ohm": 6.0,
            "le_h": 0.3e-3,
            "bl_tm": 2.5,
            "source": "provisional: model knowledge (a small moving-coil exciter, ~8 ohm "
            "nominal; the EMT's isn't published: brochure pp.3-4 'moving coil system')",
        },
        "pickup": {
            "v_per_m_s2": 5.0e-3,
            "c_f": 1.0e-9,
            "source": f"provisional: model knowledge (a ceramic contact accelerometer, "
            f"~50 mV/g, ~1 nF); accelerometers per {russo} (p.3), ceramic contact pickups "
            "per the brochure (pp.3-4)",
        },
        "model": {
            "f_max_hz": 20000.0,
            "tail_db": 90.0,
            "source": "numerical: the modes up to 20 kHz (below 0.45 of the rate), each "
            "summed until 90 dB down",
        },
        "decay": {
            "f_hz": EMT140_GRID_HZ,
            "curves": curves,
            "source": f"digitized: {brochure} (p.2's reverberation time against frequency "
            "for three damper distances, emt_140ts_decay.csv), linear in log frequency onto "
            "third octaves, held past each curve's ends",
        },
    }


# Scotch 111's easy-axis concentration (TAPE_PLAN.md TM2, step 7: No. 21 with the head image).
SCOTCH111_KAPPA = 1.5

# Scotch 111's grain (TAPE_PLAN.md TM3; scripts/fit_tape_noise.py -> reports/tape/
# noise_fit.json, on 0.01-decade grids): particle volume to Sound Talk No. 34's erased noise,
# the packing field to its DC noise.
SCOTCH111_NOISE = {
    "particle_volume_m3": 1.62e-21,
    "packing": 0.35,
    "packing_sigma": 0.0162,
    "packing_corr_m": 0.03,
}


def build_scotch111() -> dict[str, Any]:
    """Scotch 111, the tape of the Ampex 350 / 351's era (docs/TAPE_PLAN.md, TM1): its
    particles as a Preisach ensemble fitted to 3M's remanence curve (Sound Talk No. 20)
    and Eilers' coercivity; coating and base from Eilers' table (varimu.devices.tape_fit);
    its grain fitted to Sound Talk No. 34 (TM3: SCOTCH111_NOISE)."""
    from varimu.devices import tape_fit
    from varimu.devices.tape import Orientation

    pub = _published()["SCOTCH111"]
    rows = load_csv("scotch_111_remanence.csv")  # h_peak_a_m, phi_r_wb_per_m
    orientation = Orientation(SCOTCH111_KAPPA, 8)
    fit = tape_fit.fit_preisach(
        rows[:, 0], rows[:, 1], pub["coercivity_a_m"], pub["oxide_m"], orientation=orientation
    )
    p = fit.params
    eilers = "data/datasheets/published_points.yaml SCOTCH111 (Eilers' table, AES, row 111)"
    b20 = "data/datasheets/3m_sound_talk.provenance.yaml (Sound Talk No. 20, Type B, 4RBA)"
    return {
        "name": "SCOTCH111",
        "kind": "tape",
        "source": "Scotch 111 (gamma-Fe2O3 on acetate, 1948): a Preisach ensemble fitted to "
        "3M's remanence curve and Eilers' coercivity; varimu.devices.tape_fit, "
        "varimu.devices.preisach",
        "coating": {
            "thickness_m": pub["oxide_m"],
            "source": f"{eilers}: 0.5 mil oxide",
        },
        "base": {
            "thickness_m": pub["base_m"],
            "source": f"{eilers}: 1.42 mil acetate",
        },
        "particles": {
            "hc_median_a_m": p.hc_median_a_m,
            "sigma_ln_hc": p.sigma_ln_hc,
            "sigma_hi_a_m": p.sigma_hi_a_m,
            "ms_a_m": fit.ms_a_m,
            "h_max_a_m": p.h_max_a_m,
            "n_table": p.n_table,
            "source": f"fit: the remanence after symmetric loops ({b20}, digitized: "
            "scotch_111_remanence.csv) and the loop's coercivity, 270 Oe +-10% "
            f"({eilers}); Ms from the curve's saturated flux per width (0.636 lines per "
            "1/4\") over the coating's thickness and the fit's saturation remanence "
            "(the x component of the oriented ensemble). h_max, n_table: numerical (the "
            "tables' range and points)",
        },
        "orientation": {
            "kappa": SCOTCH111_KAPPA,
            "n": orientation.n,
            "source": "fit: the easy axes' axial von Mises concentration that reproduces "
            "3M Sound Talk No. 21's bias curves (Type B on an Ampex 300, 15 ips) with the "
            "vector Preisach model, its demagnetization and the head's image, among kappa "
            "0.5-20 (docs/TAPE_PLAN.md, TM2's status, step 7); bulletin 20 alone fits "
            "kappa >= 1. n: numerical (directions; 16 moves No. 21's curves < 0.2 dB)",
        },
        "noise": {
            **SCOTCH111_NOISE,
            "source": "fit: data/datasheets/3m_sound_talk_34.provenance.yaml (Sound Talk No. "
            "34, #111 at 7.5 ips, NARTB playback; digitized: scotch_111_noise.csv) by "
            "scripts/fit_tape_noise.py (reports/tape/noise_fit.json) on the first print's "
            "machine: particle_volume_m3 to the bulk-erased octave spectrum, 300-2400 Hz "
            "(rms 1.6 dB; ~0.4 x 0.07 um acicular); packing_sigma to the DC (3% level) "
            "spectrum, 20-2400 Hz (rms 1.5 dB), which fixes only packing_sigma^2 / "
            "packing_corr_m (8.7e-3 per m: the field's k^-2 regime, longer than ~2 mm); "
            "packing_corr_m 30 mm keeps every audio band in that regime. packing: provisional: "
            "model knowledge (1950s acicular gamma-Fe2O3 coatings, 30-40% by volume; only "
            "volume / packing is seen)",
        },
        "fit_report": {
            "remanence_rms_reading_errors": fit.rms_sigma,
            "remanence_max_error_wb_per_m": fit.max_abs_wb_per_m,
            "coercivity_a_m": fit.coercivity_a_m,
            "saturation_remanence": fit.saturation_remanence,
        },
    }


# The reverse bias CJC is taken at for the bjt part's linear collector capacitance: the
# datasheets' hFE condition (VCE = 5 V), a typical audio stage's collector-base voltage.
BJT_CJC_AT_V = 5.0


def _bjt_component(name: str, card_key: str, source: str) -> dict[str, Any]:
    """A BJT component (kind `bjt`, varimu.devices.bjt) from a published SPICE card: the
    DC parameters as given, RB / RC / RE as given, CJE at zero bias and CJC at
    BJT_CJC_AT_V reverse (the part's linear capacitors)."""
    cards = _published()["BJT_CARDS"]
    card = cards[card_key]
    polarity, p = parse_card(card)
    dc = {
        "is_a": p["IS"],
        "bf": p["BF"],
        "br": p.get("BR", 1.0),
        "nf": p.get("NF", 1.0),
        "nr": p.get("NR", 1.0),
        "vaf_v": p.get("VAF") or None,  # SPICE: 0 / absent = infinite
        "var_v": p.get("VAR") or None,
        "ikf_a": p.get("IKF") or None,
        "ikr_a": p.get("IKR") or None,
        "ise_a": p.get("ISE", 0.0),
        "ne": p.get("NE", 1.5),
        "isc_a": p.get("ISC", 0.0),
        "nc": p.get("NC", 2.0),
        "source": f"the {card_key} card's DC parameters ({cards['source']})",
    }
    cjc = depletion_c_f(p.get("CJC", 0.0), p.get("VJC", 0.75), p.get("MJC", 0.33), BJT_CJC_AT_V)
    return {
        "name": name,
        "kind": "bjt",
        "source": source,
        "polarity": polarity,
        "dc": dc,
        "parasitics": {
            "rb_ohm": p.get("RB", 0.0),
            "rc_ohm": p.get("RC", 0.0),
            "re_ohm": p.get("RE", 0.0),
            "cje_f": p.get("CJE", 0.0),
            "cjc_f": cjc,
            "source": f"the {card_key} card (RB constant: IRB, RBM unused); cje_f its CJE at "
            f"zero bias, cjc_f its CJC (1 + V / VJC)^-MJC at V = {BJT_CJC_AT_V:g} V reverse "
            "(linear capacitors of the bjt part, varimu.devices.bjt)",
        },
        "card": card,
    }


def _bjt_from_numbers(
    name: str, polarity: str, p: dict[str, float], source: str, card_source: str
) -> dict[str, Any]:
    """A BJT component from a card whose licence forbids redistributing it (Central's):
    its numbers, cited, without the card's text (as _jfet_component)."""
    dc = {
        "is_a": p["IS"],
        "bf": p["BF"],
        "br": p.get("BR", 1.0),
        "nf": p.get("NF", 1.0),
        "nr": p.get("NR", 1.0),
        "vaf_v": p.get("VAF") or None,
        "var_v": p.get("VAR") or None,
        "ikf_a": p.get("IKF") or None,
        "ikr_a": p.get("IKR") or None,
        "ise_a": p.get("ISE", 0.0),
        "ne": p.get("NE", 1.5),
        "isc_a": p.get("ISC", 0.0),
        "nc": p.get("NC", 2.0),
        "source": card_source,
    }
    cjc = depletion_c_f(p.get("CJC", 0.0), p.get("VJC", 0.75), p.get("MJC", 0.33), BJT_CJC_AT_V)
    return {
        "name": name,
        "kind": "bjt",
        "source": source,
        "polarity": polarity,
        "dc": dc,
        "parasitics": {
            "rb_ohm": p.get("RB", 0.0),
            "rc_ohm": p.get("RC", 0.0),
            "re_ohm": p.get("RE", 0.0),
            "cje_f": p.get("CJE", 0.0),
            "cjc_f": cjc,
            "source": "the card's RB, RC, RE; cje_f its CJE at zero bias, cjc_f its CJC (1 + V "
            f"/ VJC)^-MJC at V = {BJT_CJC_AT_V:g} V reverse (linear capacitors of the bjt part, "
            "varimu.devices.bjt)",
        },
    }


def build_2n3707() -> dict[str, Any]:
    """The 2N3707 (the 1176's control amp Q7-Q10 and Rev A's Q5)."""
    return _bjt_from_numbers(
        "2N3707",
        "npn",
        {
            "IS": 38.116e-15,
            "BF": 285.0,
            "VAF": 100.0,
            "IKF": 0.76234,
            "ISE": 38.128e-15,
            "NE": 1.9979,
            "BR": 10.364,
            "VAR": 100.0,
            "IKR": 1.5810,
            "ISC": 803.76e-15,
            "NC": 1.5928,
            "RB": 9.7439,
            "RC": 30.0,
            "CJE": 11.658e-12,
            "CJC": 5.3208e-12,
            "VJC": 0.42236,
            "MJC": 0.29245,
        },  # fmt: skip
        "Central Semiconductor's 2N3707 SPICE model (data/datasheets/transistors/README.md: "
        "a family template shared with its 2N5088 card but BF and RC, so the junction "
        "constants are provisional). Its NK 1.2265 (PSpice's high-injection exponent) isn't "
        "in the model: IKF 0.76 A is far above the 1176's currents",
        "web: https://central.aeminc.com/docs/ENGINEERING/CSM/2N3707.LIB (2N3707, 11/16/21 "
        "rev A: IS 38.116f, BF 285, VAF 100, IKF .76234, ISE 38.128f, NE 1.9979, BR 10.364, "
        "VAR 100, IKR 1.5810, ISC 803.76f, NC 1.5928, RB 9.7439, RC 30, CJE 11.658p, CJC "
        "5.3208p, VJC .42236, MJC .29245)",
    )


def build_2n3053() -> dict[str, Any]:
    """The 2N3053 (the 1176 Rev A's class-A output transistor, Q6)."""
    return _bjt_from_numbers(
        "2N3053",
        "npn",
        {
            "IS": 5.42e-17,
            "BF": 205.0,
            "VAF": 114.0,
            "IKF": 0.425,
            "ISE": 1.64e-12,
            "NE": 2.0,
            "BR": 4.0,
            "NR": 1.0,
            "VAR": 20.0,
            "IKR": 1.05,
            "RE": 0.102,
            "RB": 0.409,
            "RC": 40.9e-3,
            "CJE": 111e-12,
            "CJC": 43.3e-12,
            "VJC": 0.3,
            "MJC": 0.3,
        },  # fmt: skip
        "Central Semiconductor's 2N3053 SPICE model (data/datasheets/transistors/README.md: "
        "named sm_NPN, a generic 40 V 0.7 A 100 MHz fit rather than a part-specific "
        "extraction); its datasheet data/datasheets/transistors/central_2N3053.pdf",
        "web: https://central.aeminc.com/docs/ENGINEERING/CSM/2N3053.LIB (2N3053, 10/22/19 "
        "rev A: IS 5.42e-17, BF 205, VAF 114, IKF 0.425, ISE 1.64p, NE 2.00, BR 4.00, NR "
        "1.00, VAR 20.0, IKR 1.05, RE 0.102, RB 0.409, RC 40.9m, CJE 111p, CJC 43.3p, VJC "
        "0.300, MJC 0.300)",
    )


def build_2n5087() -> dict[str, Any]:
    """The 2N5087 (the API 2520's Q6 and Q9, PNP: docs/CHAINS_PLAN.md WP12)."""
    return _bjt_from_numbers(
        "2N5087",
        "pnp",
        {
            "IS": 2.45e-15,
            "BF": 1135.0,
            "VAF": 139.0,
            "IKF": 21.2e-3,
            "ISE": 380e-15,
            "NE": 2.0,
            "BR": 4.0,
            "NR": 1.0,
            "VAR": 20.0,
            "IKR": 45.0e-3,
            "RE": 106.0,
            "RB": 426.0,
            "RC": 42.6,
            "CJE": 9.65e-12,
            "CJC": 11.8e-12,
            "VJC": 0.3,
            "MJC": 0.3,
        },  # fmt: skip
        "Central Semiconductor's 2N5087 SPICE model (8/18/10 rev A; Central's licence forbids "
        "redistributing the card, so its numbers are cited here)",
        "web: https://central.aeminc.com/docs/ENGINEERING/CSM/2N5087.LIB (2N5087, 8/18/10 rev "
        "A: IS 2.45f, BF 1.135k, VAF 139, IKF 21.2m, ISE 380f, NE 2.00, BR 4.00, VAR 20.0, "
        "IKR 45.0m, RE 106, RB 426, RC 42.6, CJE 9.65p, CJC 11.8p, VJC 0.300, MJC 0.300)",
    )


def build_2n4033() -> dict[str, Any]:
    """The 2N4033 (PNP, 80 V 1 A): the stand-in for the API 2520's Q8, a 2N4036 (Central has
    no 2N4036 card; the two are siblings of the 2N3053's complement family)."""
    return _bjt_from_numbers(
        "2N4033",
        "pnp",
        {
            "IS": 57.5e-15,
            "BF": 449.0,
            "VAF": 161.0,
            "IKF": 0.313,
            "ISE": 33.6e-12,
            "NE": 2.0,
            "BR": 4.0,
            "NR": 1.0,
            "VAR": 20.0,
            "IKR": 0.870,
            "RE": 0.112,
            "RB": 0.449,
            "RC": 44.9e-3,
            "CJE": 134e-12,
            "CJC": 42.4e-12,
            "VJC": 0.3,
            "MJC": 0.3,
        },  # fmt: skip
        "Central Semiconductor's 2N4033 SPICE model (11/12/08 rev A; numbers cited, the card "
        "not redistributed); a stand-in for the 2N4036 of the 2520's drawing",
        "web: https://central.aeminc.com/docs/ENGINEERING/CSM/2N4033.LIB (2N4033, 11/12/08 "
        "rev A: IS 57.5f, BF 449, VAF 161, IKF 0.313, ISE 33.6p, NE 2.00, BR 4.00, VAR 20.0, "
        "IKR 0.870, RE 0.112, RB 0.449, RC 44.9m, CJE 134p, CJC 42.4p, VJC 0.300, MJC 0.300)",
    )


def build_2n5784() -> dict[str, Any]:
    """The 2N5784 (NPN, TO-39 epitaxial-base, 65 V 3.5 A: the Rhodes 100 W power amp's Q1,
    Q2, Q3, Q5, docs/RHODES_PLAN.md "The Suitcase"). No card is published; the numbers are
    fitted to RCA's sheet (data/datasheets/transistors/rca_1981_2N5781-2N5786.pdf, p. 160-162,
    Central's R1 sheet agrees): Fig. 9's typical dc beta at 25 C and VCE 2 V (about 61 at
    10 mA, 85 at 0.1 A, 68 at 0.2 A, 21 at 1 A, 7 at 3 A: BF 90, IKF 0.33 A), the limits hFE
    20-100 at 1 A and 4 min at 3.2 A. IS puts VBE near 0.85 V at 1 A (limit 1.5 V). VAF,
    the junction capacitances and the series resistances are provisional (model knowledge
    of the TO-39 class; Central's 2N3053 for the capacitances' size). fT 1-4 MHz (the sheet)
    is not in the model: it has no transit time."""
    return _bjt_from_numbers(
        "2N5784",
        "npn",
        {
            "IS": 2.1e-14,
            "BF": 90.0,
            "VAF": 100.0,
            "IKF": 0.33,
            "ISE": 1.5e-11,
            "NE": 1.8,
            "BR": 4.0,
            "NR": 1.0,
            "VAR": 20.0,
            "IKR": 1.0,
            "RE": 0.1,
            "RB": 2.0,
            "RC": 0.15,
            "CJE": 200e-12,
            "CJC": 100e-12,
            "VJC": 0.75,
            "MJC": 0.33,
        },  # fmt: skip
        "RCA 2N5784 (RCA Power Devices 1981 p. 160-162; Central 2N5784 R1 sheet): dc beta "
        "curve and limits fitted, junction and capacitance numbers provisional",
        "web: https://ftp.mirrorservice.org/sites/www.bitsavers.org/components/rca/_dataBooks/"
        "1981_RCA_Power_Devices.pdf (p. 160-162: hFE 20-100 at 1 A, 4 at 3.2 A, VBE 1.5 V max "
        "at 1 A; Fig. 9 typical dc beta); provisional: model knowledge (VAF, capacitances, RB)",
    )


def build_2n5781() -> dict[str, Any]:
    """The 2N5781 (PNP complement of the 2N5784: the Rhodes 100 W power amp's Q4). Same limits
    as the 2N5784 on the same RCA sheet (hFE 20-100 at 1 A, 4 min at 3.2 A; Fig. 8's typical
    dc beta peaks near 100 and falls to ~10 by 3 A: BF 90, IKF 0.35 A); the junction numbers
    mirror the NPN's, provisional. fT 8-60 MHz isn't in the model (no transit time)."""
    return _bjt_from_numbers(
        "2N5781",
        "pnp",
        {
            "IS": 2.1e-14,
            "BF": 90.0,
            "VAF": 80.0,
            "IKF": 0.35,
            "ISE": 1.5e-11,
            "NE": 1.8,
            "BR": 4.0,
            "NR": 1.0,
            "VAR": 20.0,
            "IKR": 1.0,
            "RE": 0.1,
            "RB": 2.0,
            "RC": 0.15,
            "CJE": 200e-12,
            "CJC": 100e-12,
            "VJC": 0.75,
            "MJC": 0.33,
        },  # fmt: skip
        "RCA 2N5781 (RCA Power Devices 1981 p. 160-162; Central 2N5781 R1 sheet): limits and "
        "Fig. 8 read, junction numbers mirror the 2N5784's and are provisional",
        "web: https://ftp.mirrorservice.org/sites/www.bitsavers.org/components/rca/_dataBooks/"
        "1981_RCA_Power_Devices.pdf (p. 160-162: hFE 20-100 at 1 A, 4 at 3.2 A, VBE -1.5 V max "
        "at 1 A; Fig. 8); provisional: model knowledge (VAF, capacitances, RB)",
    )


def build_2n6254() -> dict[str, Any]:
    """The 2N6254 (NPN, TO-3 hometaxial, 80 V 15 A 150 W: the Rhodes 100 W power amp's Q8 and
    Q9). No card is published. RCA's sheet (rca_1981_2N6254_pages.pdf, p. 80-84; Comset's
    agrees) limits hFE 20-70 at 5 A (VCE 2 V), 5 min at 15 A (VCE 4 V), VBE 1.5 V max at 5 A,
    VCE(sat) 0.5 V at 5 A / 0.5 A; with IKF 4 A and BF 75 the model gives hFE 33 at 5 A and 16
    at 15 A (inside the limits; typical, not worst case). IS 1e-12 puts VBE near 0.65 V at
    100 mA, as power transistors of this die size read (provisional, no curve read); RB, RE,
    RC, VAF and the capacitances are provisional. fT 0.8 MHz min (Comset) isn't in the model."""
    return _bjt_from_numbers(
        "2N6254",
        "npn",
        {
            "IS": 1.0e-12,
            "BF": 75.0,
            "VAF": 100.0,
            "IKF": 4.0,
            "ISE": 2.0e-11,
            "NE": 1.8,
            "BR": 2.0,
            "NR": 1.0,
            "VAR": 20.0,
            "IKR": 8.0,
            "RE": 0.01,
            "RB": 0.3,
            "RC": 0.02,
            "CJE": 1.0e-9,
            "CJC": 1.2e-9,
            "VJC": 0.75,
            "MJC": 0.33,
        },  # fmt: skip
        "RCA 2N6254 (RCA Power Devices 1981 p. 80-84; Comset 2N6253 / 2N6254 / 2N6371 sheet): "
        "hFE limits and VCE(sat) bracketed, the rest provisional",
        "web: https://ftp.mirrorservice.org/sites/www.bitsavers.org/components/rca/_dataBooks/"
        "1981_RCA_Power_Devices.pdf (p. 81: hFE 20-70 at 5 A, 5 min at 15 A, VBE 1.5 V max at "
        "5 A); provisional: model knowledge (IS, RB, RE, RC, VAF, capacitances)",
    )


def build_rca29b() -> dict[str, Any]:
    """The RCA29B (NPN, VERSAWATT TO-220, 80 V 3 A: the Rhodes 100 W power amp's driver Q6).
    The RCA sheet wasn't found (the 1981 databook has no RCA29 pages; reseller listings:
    80 V, 3 A, hFE 15-150 at 1 A and VCE 4 V, fT 3 MHz min): BF 100 with IKF 0.7 A gives
    hFE 41 at 1 A (inside the limits); every junction number is provisional (model
    knowledge of TIP29-class parts, the RCA29's modern equivalent)."""
    return _bjt_from_numbers(
        "RCA29B",
        "npn",
        {
            "IS": 6.0e-13,
            "BF": 100.0,
            "VAF": 100.0,
            "IKF": 0.7,
            "ISE": 2.0e-12,
            "NE": 1.8,
            "BR": 4.0,
            "NR": 1.0,
            "VAR": 20.0,
            "IKR": 2.0,
            "RE": 0.2,
            "RB": 1.0,
            "RC": 0.1,
            "CJE": 150e-12,
            "CJC": 120e-12,
            "VJC": 0.75,
            "MJC": 0.33,
        },  # fmt: skip
        "RCA29B: only the reseller limits were found (littlediode.com RCA29B: 80 V, 3 A, hFE "
        "15-150 at 1 A / 4 V, fT 3 MHz min); the rest is provisional model knowledge",
        "web: https://www.littlediode.com/components/RCA29B.html (80 V, 3 A, hFE 15-150 at "
        "1 A / VCE 4 V); provisional: model knowledge (IS, BF, IKF, RB, capacitances)",
    )


def build_rca30b() -> dict[str, Any]:
    """The RCA30B (PNP complement of the RCA29B, the 100 W power amp's driver Q7); the
    RCA30 series is RCA's stated complement of RCA29 (datasheetspdf.com index of its sheet).
    Numbers mirror the RCA29B's, provisional."""
    return _bjt_from_numbers(
        "RCA30B",
        "pnp",
        {
            "IS": 6.0e-13,
            "BF": 100.0,
            "VAF": 80.0,
            "IKF": 0.7,
            "ISE": 2.0e-12,
            "NE": 1.8,
            "BR": 4.0,
            "NR": 1.0,
            "VAR": 20.0,
            "IKR": 2.0,
            "RE": 0.2,
            "RB": 1.0,
            "RC": 0.1,
            "CJE": 150e-12,
            "CJC": 120e-12,
            "VJC": 0.75,
            "MJC": 0.33,
        },  # fmt: skip
        "RCA30B: the RCA29B's complement (the sheet wasn't found); numbers mirror it and are "
        "provisional",
        "web: https://datasheetspdf.com/pdf/1293560/RCA/RCA30/1 (RCA30 series: p-n-p, "
        "complements of RCA29); provisional: model knowledge (all junction numbers)",
    )


def build_2n3904() -> dict[str, Any]:
    """The 2N3904 (NPN): the Minimoog filter board's printed alternate for the TIS92, and
    the stand-in for its TIS97 ladder transistors (data/schematics/minimoog/README.md)."""
    return _bjt_from_numbers(
        "2N3904",
        "npn",
        {
            "IS": 4.9148e-15,
            "BF": 191.70,
            "VAF": 100.0,
            "IKF": 0.28579,
            "ISE": 11.882e-15,
            "NE": 1.4422,
            "BR": 5.6808,
            "VAR": 100.0,
            "IKR": 61.753e-3,
            "ISC": 71.145e-12,
            "NC": 1.6595,
            "RB": 5.8072,
            "RC": 0.70808,
            "CJE": 6.9435e-12,
            "CJC": 3.7572e-12,
            "VJC": 1.2237,
            "MJC": 0.28886,
        },  # fmt: skip
        "Central Semiconductor's 2N3904 SPICE model (8/18/10 rev A; numbers cited, the card "
        "not redistributed). Its NK .8296 (PSpice's high-injection exponent) isn't in the "
        "model: IKF 0.29 A is far above the Minimoog's currents",
        "web: https://central.aeminc.com/docs/ENGINEERING/CSM/2N3904.LIB (2N3904, 8/18/10 rev "
        "A: IS 4.9148f, BF 191.70, VAF 100, IKF .28579, ISE 11.882f, NE 1.4422, BR 5.6808, VAR "
        "100, IKR 61.753m, ISC 71.145p, NC 1.6595, RB 5.8072, RC .70808, CJE 6.9435p, CJC "
        "3.7572p, VJC 1.2237, MJC .28886)",
    )


def build_2n3906() -> dict[str, Any]:
    """The 2N3906 (PNP): the Minimoog filter board's printed alternate for the TIS93."""
    return _bjt_from_numbers(
        "2N3906",
        "pnp",
        {
            "IS": 7.9190e-15,
            "BF": 196.89,
            "VAF": 100.0,
            "IKF": 0.7271,
            "ISE": 13.654e-15,
            "NE": 1.4535,
            "BR": 124.61,
            "VAR": 100.0,
            "IKR": 10.010e-3,
            "ISC": 18.518e-12,
            "NC": 1.6031,
            "RB": 8.6624,
            "RC": 0.55428,
            "CJE": 11.640e-12,
            "CJC": 7.8722e-12,
            "VJC": 0.98301,
            "MJC": 0.53872,
        },  # fmt: skip
        "Central Semiconductor's 2N3906 SPICE model (8/25/10 rev A; numbers cited, the card "
        "not redistributed). Its NK 1.1475 isn't in the model (IKF 0.73 A)",
        "web: https://central.aeminc.com/docs/ENGINEERING/CSM/2N3906.LIB (2N3906, 8/25/10 rev "
        "A: IS 7.9190f, BF 196.89, VAF 100, IKF .7271, ISE 13.654f, NE 1.4535, BR 124.61, VAR "
        "100, IKR 10.010m, ISC 18.518p, NC 1.6031, RB 8.6624, RC .55428, CJE 11.640p, CJC "
        "7.8722p, VJC .98301, MJC .53872)",
    )


# The uA726's die temperature in the Minimoog (Fig 9-2's mark "T = 78.4 C"): its transistors' gain
# is fitted where they run. A circuit sets the same `temp_c` on its devices entry.
UA726_TEMP_C = 78.4
# Neither the sheet nor the Minimoog's manual gives a saturation current or an Early voltage: a
# small IC NPN's (the pair's Vbe cancels in an expo converter; its exponent is kT / q).
UA726_IS_A = 1.0e-15
UA726_VAF_V = 100.0
UA726_FIT_MAX_A = 2.0e-3


def fit_ua726() -> tuple[dict[str, float], dict[str, float]]:
    """BF, ISE, NE and IKF fitted by least squares (in log hfe) to the uA726 sheet's current gain
    against collector current up to 2 mA (VCE 5 V, the die at its regulated temperature), the
    Gummel-Poon DC subset (varimu.devices.bjt) evaluated at UA726_TEMP_C with IS and VAF fixed."""
    from scipy.optimize import brentq, least_squares

    ic, vce, hfe = load_csv("fairchild_ua726_hfe.csv").T
    # Above ~2 mA the sheet's gain falls about as 1 / Ic (595 at 1.2 mA, 160 at 5 mA), steeper
    # than the model's high-injection 1 / sqrt(Ic): fitted to UA726_FIT_MAX_A, where the
    # Minimoog's 0.05-20 uA are far inside.
    keep = ic <= UA726_FIT_MAX_A
    ic, vce, hfe = ic[keep], vce[keep], hfe[keep]

    def card(p):
        bf, ise, ne, ikf = np.exp(p)
        return Bjt(
            "UA726", "npn", is_a=UA726_IS_A, bf=float(bf), vaf_v=UA726_VAF_V, ikf_a=float(ikf),
            ise_a=float(ise), ne=float(ne), temp_k=UA726_TEMP_C + 273.15,
        )  # fmt: skip

    def gain(m: Bjt, i_c: float, v_ce: float) -> float:
        vbe = brentq(lambda v: float(m.junction(v, v - v_ce)[0]) - i_c, 0.1, 1.2, xtol=1e-12)
        out = m.junction(vbe, vbe - v_ce)
        return float(out[0] / out[1])

    def resid(p):
        m = card(p)
        return [np.log(gain(m, i, v) / h) for i, v, h in zip(ic, vce, hfe, strict=True)]

    r = least_squares(resid, np.log([600.0, 1e-13, 2.0, 5e-3]))
    bf, ise, ne, ikf = (float(x) for x in np.exp(r.x))
    m = card(r.x)
    err = [gain(m, i, v) - h for i, v, h in zip(ic, vce, hfe, strict=True)]
    p = {"bf": bf, "ise_a": ise, "ne": ne, "ikf_a": ikf}
    rms, worst = float(np.sqrt(np.mean(np.square(err)))), float(np.max(np.abs(err)))
    return p, {"rms_hfe": rms, "max_hfe": worst}


def build_ua726() -> dict[str, Any]:
    """One transistor of the uA726 temperature-controlled pair (the Minimoog's expo converters,
    docs/MINIMOOG_PLAN.md MM3): matched as one model instance on one die, run at UA726_TEMP_C
    through a circuit's `temp_c`. Its heater regulator (Q3-Q8, the TEMP ADJ resistor) isn't in the
    component: the die's temperature is a fixed setting until the thermal node."""
    p, fit = fit_ua726()
    return {
        "name": "UA726",
        "kind": "bjt",
        "source": (
            "Fairchild uA726 Temperature-Controlled Differential Pair (1979 Linear Op Amp Data "
            "Book pp. 7-33 to 7-35, data/datasheets/transistors/fairchild_ua726_1979.pdf): bf, "
            "ise_a, ne, ikf_a fitted to its current gain curve at the die's 78.4 C (the "
            "Minimoog's Fig 9-2); is_a and vaf_v provisional: model knowledge (a small IC NPN; the "
            "sheet gives neither); cje_f, cjc_f the sheet's typical 1.0 pF emitter transition (IE "
            "100 uA) and "
            "output (VCB 5 V) capacitances"
        ),
        "polarity": "npn",
        "dc": {
            "is_a": UA726_IS_A,
            "bf": p["bf"],
            "br": 1.0,
            "nf": 1.0,
            "nr": 1.0,
            "vaf_v": UA726_VAF_V,
            "var_v": None,
            "ikf_a": p["ikf_a"],
            "ikr_a": None,
            "ise_a": p["ise_a"],
            "ne": p["ne"],
            "isc_a": 0.0,
            "nc": 2.0,
            "source": (
                "fit: bf, ise_a, ne, ikf_a by least squares in log hfe to the sheet's p. 7-35 "
                "curve up to 2 mA (data/datasheets/fairchild_ua726_hfe.csv, its provenance "
                "sidecar; library.fit_ua726) at 78.4 C (above 2 mA the sheet's gain falls as "
                "~1 / Ic, steeper than the model's roll-off: not fitted, the Minimoog runs "
                "0.05-20 uA); "
                "is_a 1e-15 A and vaf_v 100 V provisional: model knowledge"
            ),
        },
        "parasitics": {
            "rb_ohm": 0.0,
            "rc_ohm": 0.0,
            "re_ohm": 0.0,
            "cje_f": 1.0e-12,
            "cjc_f": 1.0e-12,
            "source": (
                "the sheet's p. 7-34: emitter transition capacitance 1.0 pF (IE 100 uA), output "
                "capacitance 1.0 pF (IE 0, VCB 5 V), typical; no terminal resistances given"
            ),
        },
        "fit_report": {"rms_error_hfe": fit["rms_hfe"], "max_error_hfe": fit["max_hfe"]},
    }


def build_bc550c() -> dict[str, Any]:
    """The BC550C (Philips / NXP), the project's first BJT (CLAVINET_PLAN.md CL0)."""
    return _bjt_component(
        "BC550C",
        "BC547C",
        "NXP's BC547C SPICE model: the BC550 is the BC547's low-noise selection of the same "
        "die, hFE group C 420-800 for both (Philips BC549; BC550 product specification "
        "2004 Oct 11, web: https://www.audiodesignguide.com/DACend2/BC549_550.pdf); "
        "checked against that sheet's hFE and VBE at 2 mA (tests/test_bjt.py)",
    )


def build_bc413c() -> dict[str, Any]:
    """The Clavinet D6's front-end transistor (web: https://clavinet.com/d6upgrade.php
    names the 'BC 413C'), on the BC550C's card."""
    return _bjt_component(
        "BC413C",
        "BC547C",
        "provisional: model knowledge (BC413C is a low-noise NPN of the same class, hFE "
        "group C 380-800; no published model card found): NXP's BC547C card, as BC550C@1's "
        "(web: https://clavinet.com/d6upgrade.php names the D6's 'BC 413C')",
    )


def build_bc238() -> dict[str, Any]:
    """The Clavinet E7's rail regulator (Hohner's E7 schematic, St.-Nr. 801 111: a BC238
    follower on an 8.2 V zener), on the BC547B's card."""
    return _bjt_component(
        "BC238",
        "BC547B",
        "provisional: model knowledge (the BC238 is the BC548's predecessor of the same "
        "family, the BC237 / 238 / 239 = BC547 / 548 / 549; the drawing gives no hFE group, "
        "B taken; no published BC238 card found): NXP's BC547B card (Hohner's E7 schematic "
        "names the BC238, data/schematics/hohner_clavinet_d6/clavinete7.jpg)",
    )


def build_bc560c() -> dict[str, Any]:
    """The BC550C's PNP complement (the BC557's low-noise selection), the tests' PNP."""
    return _bjt_component(
        "BC560C",
        "BC557C",
        "NXP's BC557C SPICE model: the BC560 is the BC557's low-noise selection of the same "
        "die (the BC550's PNP complement: Philips BC549; BC550 product specification "
        "2004 Oct 11, web: https://www.audiodesignguide.com/DACend2/BC549_550.pdf)",
    )


def build_lamp327() -> dict[str, Any]:
    """The #327 pilot lamp (28 V, 40 mA), the tube synth's LFO stabilizer (SYNTH_IDEAS.md #7):
    its filament's wire from the rating at an assumed rated temperature, its emissivity a
    cubic in T least-squares through Holladay's table (varimu.devices.lamp)."""
    pub = _published()
    d, e = pub["LAMP327"], pub["TUNGSTEN_EMISSIVITY"]
    t, eps = np.array(e["t_k"]), np.array(e["total"])
    coeffs = np.polyfit(t, eps, 3)[::-1]  # c0..c3
    resid = np.polyval(coeffs[::-1], t) - eps
    t_rated_k, rad_fraction, t_amb_k = 2300.0, 0.65, 300.0
    lamp = Lamp.from_rating(
        "LAMP327", d["v_rated"], d["i_rated_a"], t_rated_k, rad_fraction, tuple(coeffs), t_amb_k
    )
    return {
        "name": "LAMP327",
        "kind": "lamp",
        "source": "derived: varimu.devices.lamp.Lamp.from_rating on the #327's rating "
        f"({d['source']})",
        "rating": {"v": d["v_rated"], "a": d["i_rated_a"]},
        "t_rated_k": t_rated_k,
        "t_rated_source": "provisional: model knowledge (the filament at its rated 28 V: MSCP 0.34 "
        "at 1.12 W is ~3.8 lm/W, the efficacy of tungsten near 2300 K, as a 4,000 h miniature "
        "lamp runs)",
        "t_amb_k": t_amb_k,
        "t_amb_source": "provisional: model knowledge (room temperature inside a chassis; "
        "config/cathodes.yaml's t_amb_k)",
        "filament": {
            "wire_d_m": lamp.wire_d_m,
            "wire_l_m": lamp.wire_l_m,
            "rad_fraction": rad_fraction,
            "source": "derived from the rating at t_rated_k (wire_d_m, wire_l_m: the uncoiled "
            "wire). rad_fraction provisional: model knowledge (a C-2F coiled filament shades "
            "part of its wire's surface; 0.5-0.8)",
        },
        "emissivity": {
            "coeffs": [float(c) for c in coeffs],
            "max_error": float(np.max(np.abs(resid))),
            "source": f"least-squares cubic in T through {e['source']}",
        },
        "derived": {
            "r_cold_ohm": float(lamp.r_ohm(t_amb_k)),
            "r_hot_ohm": float(lamp.r_ohm(t_rated_k)),
            "mass_kg": lamp.mass_kg,
            "source": "the model's values (not inputs): resistance at t_amb_k and t_rated_k, "
            "the filament's mass",
        },
    }


def _thyratron_data(t: Thyratron, source: str, model_sources: dict, report: dict) -> dict:
    fields = [f for f in t.__dataclass_fields__ if f not in ("name", "c_gk", "c_ga", "c_ak")]
    return {
        "name": t.name,
        "kind": "thyratron",
        "source": source,
        "model": {f: getattr(t, f) for f in fields},
        "model_sources": model_sources,
        "capacitances_f": {"gk": t.c_gk, "ga": t.c_ga, "ak": t.c_ak},
        "fit_report": report,
    }


def _clean(x):
    """Plain floats and strings for YAML (the fit reports carry numpy scalars)."""
    if isinstance(x, dict):
        return {str(k): _clean(v) for k, v in x.items()}
    if isinstance(x, list | tuple):
        return [_clean(v) for v in x]
    if isinstance(x, np.floating | np.integer):
        return float(x)
    return x


def build_2d21() -> dict[str, Any]:
    """The 2D21 thyratron (HYBRID_PHYSICS_PLAN.md H1): the lumped plasma fitted in full to
    RCA's and Sylvania's sheets (varimu.devices.thyratron_fit)."""
    from varimu.devices import thyratron_fit as tf

    t, report = tf.fit_2d21(max_nfev=3)
    return _thyratron_data(
        t,
        "fit: varimu.devices.thyratron_fit.fit_2d21 on data/datasheets/"
        "sylvania_2d21.provenance.yaml (control family, grid current before and during "
        "conduction) and published_points.yaml '2D21' (RCA 6-15-48: drop, ionization and "
        "deionization times)",
        {
            "fitted": "mu_a, mu_g2, v0_v, e_v, perveance, x_n, v_x_v, k_ion, c_meta, tau_diff_s, "
            "k_grid, p_grid, q_s_c (least squares, all targets at once); g_leak_s alone, to the "
            "before-conduction curves' flat parts",
            "v_ion_v, v_meta_v": "web: https://physics.nist.gov/PhysRefData/ASD/ (xenon's first "
            "ionization potential, its 6s[3/2]_2 metastable level)",
            "w_ion_v, w_meta_v, t_e_v, v_float_v": "provisional: model knowledge (the thresholds' "
            "softness and the arc's electron temperature ~0.3 eV; the grid floats near -0.6 V, "
            "where Sylvania's during-conduction curves cross)",
            "s0_per_s": "numerics (background ionization: a floor far below the strike's density)",
            "capacitances_f": "published_points.yaml '2D21' (grid No. 1 to anode; input; output)",
        },
        _clean(report),
    )


def build_884() -> dict[str, Any]:
    """The 884 thyratron (HYBRID_PHYSICS_PLAN.md H1, the sawtooth's tube): the 2D21's fitted
    structure with argon, its own control characteristic and drop, the plasma's transport
    scaled by ion mobility (varimu.devices.thyratron_fit.fit_884)."""
    from varimu.devices import thyratron_fit as tf

    ref, _ = versions.read_text("2D21")
    base = load_device(str(ref))
    t, report = tf.fit_884(base)
    return _thyratron_data(
        t,
        f"fit: varimu.devices.thyratron_fit.fit_884 from {ref} on data/datasheets/"
        "rca_884.provenance.yaml (the average control characteristic) and published_points.yaml "
        "'884' (RCA 12-15-44: drop, capacitances)",
        {
            "fitted": "mu_a, v0_v (to the control characteristic, 40-290 V), c_meta (to the 16 V "
            "drop at 0.1 A)",
            "v_ion_v, v_meta_v": "web: https://physics.nist.gov/PhysRefData/ASD/ (argon's first "
            "ionization potential, its 4s[3/2]_2 metastable level)",
            "tau_diff_s, k_grid": f"provisional: model knowledge ({ref}'s scaled by argon's ion "
            f"mobility over xenon's, {tf.MOBILITY_AR_XE:.3f}: Ar+ in Ar ~1.53, Xe+ in Xe ~0.58 "
            "cm^2/(V s) at low field; equal pressure and geometry assumed. The sheet gives no "
            "times; RCA's sweep circuit and its frequency table are the check)",
            "e_v, perveance, x_n, v_x_v, k_ion, w_ion_v, w_meta_v, p_grid, v_float_v, t_e_v, "
            "q_s_c, g_leak_s, s0_per_s": f"provisional: model knowledge ({ref}'s: an oxide "
            "cathode, a grid and a plasma of the same kind; the 884's sheet doesn't constrain "
            "them)",
            "capacitances_f": "published_points.yaml '884' (grid to cathode, grid to anode, anode "
            "to cathode)",
        },
        _clean(report),
    )


EMT240_BROCHURE = (
    "EMT 240 Reverb Foil brochure (EMT, PE-111-4-U, c. 1972); local copy "
    "sources/emt_240_brochure_1972.pdf (web: https://www.preservationsound.com/wp-content/"
    "uploads/2013/09/EMT_240_reverb.pdf)"
)
RUDOLPH_240 = "web: https://www.barryrudolph.com/reviews/heritage_audio_ha240.html"
# Gold's internal loss factor (provisional): the foil's decay falls above a few kHz.
EMT240_LOSS_FACTOR = 5.0e-5
EMT240_SETTINGS_S = (4.0, 2.0, 1.0)


def build_emt240() -> dict[str, Any]:
    """An EMT 240 "Reverb Foil" (docs/REVERB_PLAN.md, the candidates' first): a thin gold
    foil as a plate (varimu.devices.plate's model: bending plus tension). The brochure
    keeps the 140's principle ("a constant resonant density over the audible range",
    "> 3/Hz", "minimum dispersion"), so bending dominates: 18 um of gold over 270 x 290 mm
    is 3.4 modes per Hz. Its decay: the brochure's 1-4 s at 500 Hz by a damping plate
    giving "proportional damping of all frequencies", so each setting's curve is flat but
    for gold's internal loss at the top (provisional). The transducers are provisional,
    sized for the foil (its driving-point impedance is ~750x the 140's lower) so the
    exciter's motional resistance is 1.5 ohm and the diffuse field's pickup level per
    ampere equals EMT140@1's (Cremer & Heckl's reverberant plate: <v^2> = F^2 / (Z M
    sigma)), so our own electronics serve both."""
    from varimu.devices import plate as plt_

    lx, ly, h = 0.27, 0.29, 18e-6
    rho, e, nu = 19300.0, 79.0e9, 0.42
    tension = 1.0
    d = e * (h * h * h) / (12.0 * (1.0 - nu * nu))
    z_240 = 8.0 * math.sqrt(d * rho * h)
    bl = math.sqrt(1.5 * z_240)
    # EMT140@1's figures, for the same level per ampere: acceleration ~ F sqrt(1 / (Z M)).
    ref = plate_from_data(yaml.safe_load(versions.read_text("EMT140@1", DEVICE_DIR)[1]), "EMT140@1")
    z_140 = plt_.plate_impedance_ns_per_m(ref)
    m_140 = ref.density_kg_m3 * ref.thickness_m * ref.lx_m * ref.ly_m
    m_240 = rho * h * lx * ly
    a_ratio = (bl / ref.exciter_bl_tm) * math.sqrt((z_140 * m_140) / (z_240 * m_240))
    pickup = ref.pickup_v_per_m_s2 / a_ratio
    kappa = math.sqrt(d / (rho * h))
    per_hz = lx * ly / (2.0 * kappa)
    curves = []
    for t500 in EMT240_SETTINGS_S:
        ends = SIX_LN10_PLATE / t500 - 2.0 * math.pi * 500.0 * EMT240_LOSS_FACTOR
        t60 = [
            SIX_LN10_PLATE / (ends + 2.0 * math.pi * f * EMT240_LOSS_FACTOR) for f in EMT140_GRID_HZ
        ]
        curves.append({"label_s": t500, "t60_s": [round(v, 4) for v in t60]})
    return {
        "name": "EMT240",
        "kind": "plate",
        "source": "the EMT 240's gold foil as a plate: its brochure's figures, gold's moduli, a "
        "derived decay and provisional transducers; varimu.devices.plate",
        "plate": {
            "lx_m": lx,
            "ly_m": ly,
            "thickness_m": h,
            "density_kg_m3": rho,
            "youngs_pa": e,
            "poisson": nu,
            "tension_n_m": tension,
            "source": f"{RUDOLPH_240} (the foil 270 x 290 mm, 18 microns; the brochure: 'a foil "
            f"of special gold 12 inches square', {EMT240_BROCHURE}); gold: provisional: model "
            "knowledge (handbook values for gold, E 79 GPa, nu 0.42, rho 19,300 kg/m^3; the "
            "foil is electroplated 'coin gold'); tension: provisional: model knowledge (small "
            "enough that bending dominates above ~40 Hz, as the brochure's 'constant resonant "
            "density' needs; the EMT140@1 model's tension does so above ~30 Hz)",
        },
        "positions": {
            "drive_xy": [0.52, 0.53],
            "pickup_xy": [0.47, 0.62],
            "pickup2_xy": EMT240_PICKUP2_XY,
            "source": "provisional: EMT140@1's model positions (fractions of the sides); the "
            "240's aren't published; pickup2_xy, the stereo unit's second pickup (the brochure, "
            f"p.3: 'for both stereo and mono channels', {EMT240_BROCHURE}): provisional, on the "
            "exciter's other side at an unequal distance (0.10 m against 0.03 m), placed "
            "where it is as loud as the first per octave (125 Hz-2 kHz, within 0.8 dB) and "
            "uncorrelated with it (|r| <= 0.21 at 125 Hz, 0.05 above): "
            "scripts/plate_pickups.py",
        },
        "exciter": {
            "re_ohm": 6.0,
            "le_h": 0.3e-3,
            "bl_tm": bl,
            "source": "provisional: EMT140@1's coil, BL sized so its motional resistance on "
            f"the foil's driving-point impedance (8 sqrt(D rho H) = {z_240:.4f} N s/m) is 1.5 "
            "ohm (a small moving coil; the 240's isn't published)",
        },
        "pickup": {
            "v_per_m_s2": pickup,
            "c_f": 1.0e-9,
            "source": "provisional: derived so the diffuse field's pickup voltage per ampere "
            "of exciter current equals EMT140@1's (<a^2> ~ F^2 / (Z M sigma): the force, the "
            "driving-point impedance, the mass), the same pickup amplifiers serving both; "
            "EMT140@1's capacitance",
        },
        "model": {
            "f_max_hz": 20000.0,
            "tail_db": 90.0,
            "source": "numerical: the modes up to 20 kHz (below 0.45 of the rate), each summed "
            "until 90 dB down",
        },
        "decay": {
            "f_hz": EMT140_GRID_HZ,
            "curves": curves,
            "source": f"derived: {EMT240_BROCHURE} ('reverberation time at 500 Hz 1...4 "
            "seconds'; the damping plate 'produces proportional damping of all frequencies "
            "and avoids formation of decay peaks'): per setting flat at its 500 Hz value, "
            f"plus gold's internal loss omega eta, eta {EMT240_LOSS_FACTOR:g} (provisional: "
            "model knowledge), the two meeting the setting at 500 Hz",
        },
        "fit_report": {"modes_per_hz": per_hz, "driving_point_ns_per_m": z_240},
    }


def load_line(m: KorenPentode, p: dict, phases: int = 128) -> dict[str, float]:
    """A pentode's class-A1 single-ended stage into a transformer (an AC load rl_ohm, the
    plate's mean at its supply), driven to a peak of |vg1|: (power, THD, mean plate and
    screen currents) from one cycle, the plate voltage solved per phase (bisection: the
    plate current rises with it) and the mean current iterated (rectification)."""
    vg1, vg2, vb, rl = p["vg1_v"], p["vg2_v"], p["vp_v"], p["rl_ohm"]
    th = 2 * np.pi * np.arange(phases) / phases
    g = vg1 + abs(vg1) * np.sin(th)
    mean = float(m.ip(vg1, vg2, vb))
    for _ in range(6):
        lo, hi = np.zeros(phases), np.full(phases, 3.0 * vb)
        for _ in range(60):
            mid = 0.5 * (lo + hi)
            f = mid - vb + rl * (m.ip(g, vg2, mid) - mean)
            lo, hi = np.where(f > 0, lo, mid), np.where(f > 0, mid, hi)
        ip = m.ip(g, vg2, 0.5 * (lo + hi))
        mean = float(np.mean(ip))
    c = np.fft.rfft(ip) / phases * 2
    h = np.abs(c[1:8])
    return {
        "power_w": float(h[0] ** 2 / 2 * rl),
        "thd_pct": float(100 * np.sqrt(np.sum(h[1:] ** 2)) / h[0]),
        "ip_a": mean,
        "ig2_a": float(np.mean(m.ig2(g, vg2))),
    }


def build_6k6gt() -> dict[str, Any]:
    """The Fender 6G15's reverb driver: a Koren pentode fit to RCA's three class-A1 columns,
    all six parameters free, log least squares: the zero-signal Ip, Ig2, gm and rp (rp,
    "approx.", weighs a third) and the large-signal figures at each column's rated load and
    full drive (power output, THD weighing a half, the max-signal plate and screen currents:
    `load_line`), so the curvature is the sheet's too. RCA publishes no curves for it."""
    from scipy.optimize import least_squares

    pub = _published()["6K6GT"]
    pts, dv = pub["class_a1"], 1e-3

    def figures(m: KorenPentode, p: dict) -> tuple[float, float, float, float]:
        vg1, vg2, vp = p["vg1_v"], p["vg2_v"], p["vp_v"]
        gm = (m.ip(vg1 + dv, vg2, vp) - m.ip(vg1 - dv, vg2, vp)) / (2 * dv)
        rp = 2 * dv / (m.ip(vg1, vg2, vp + dv) - m.ip(vg1, vg2, vp - dv))
        return float(m.ip(vg1, vg2, vp)), float(m.ig2(vg1, vg2)), float(gm), float(rp)

    def resid(x):
        m = KorenPentode(*np.exp(x))
        r = []
        for p in pts:
            ip, ig2, gm, rp = figures(m, p)
            big = load_line(m, p)
            r += [
                np.log(ip / p["ip_a"]),
                np.log(ig2 / p["ig2_a"]),
                np.log(gm / p["gm_s"]),
                np.log(rp / p["rp_ohm"]) / 3.0,
                np.log(big["power_w"] / p["power_w"]),
                np.log(big["thd_pct"] / p["thd_pct"]) / 2.0,
                np.log(big["ip_a"] / p["ip_max_signal_a"]),
                np.log(big["ig2_a"] / p["ig2_max_signal_a"]) / 2.0,
            ]
        return r

    x0 = np.log([8.0, 1.35, 1500.0, 6000.0, 50.0, 15.0])
    sol = least_squares(resid, x0, xtol=1e-12, ftol=1e-12, max_nfev=4000)
    m = KorenPentode(*(float(v) for v in np.exp(sol.x)))
    caps = pub["capacitances_f"]
    report = {}
    for p in pts:
        ip, ig2, gm, rp = figures(m, p)
        big = load_line(m, p)
        report[f"vp_{p['vp_v']}"] = {
            "ip_pct": 100 * (ip / p["ip_a"] - 1),
            "ig2_pct": 100 * (ig2 / p["ig2_a"] - 1),
            "gm_pct": 100 * (gm / p["gm_s"] - 1),
            "rp_pct": 100 * (rp / p["rp_ohm"] - 1),
            "power_w": big["power_w"],
            "thd_pct": big["thd_pct"],
            "ip_max_signal_a": big["ip_a"],
            "ig2_max_signal_a": big["ig2_a"],
        }
    return {
        "name": "6K6GT",
        "kind": "pentode",
        "source": "fit: Koren pentode to the three class-A1 columns: zero-signal Ip, Ig2, gm, "
        "rp (a third) and, at each column's rated load and full drive, the power output, THD "
        "(a half) and max-signal plate and screen (a half) currents; log least squares "
        f"({pub['source']})",
        "model": {"mu": m.mu, "ex": m.ex, "kg1": m.kg1, "kg2": m.kg2, "kp": m.kp, "kvb": m.kvb},
        "grid_current": dict(PROVISIONAL_GRID),
        "capacitances_f": {
            "g1k": caps["input"],
            "g1p": caps["g1p"],
            "pk": caps["output"],
            "source": f"{pub['source']} (without external shield)",
        },
        "fit_report": _clean(report),
    }


# --- The Hammond Novachord (docs/NOVACHORD_PLAN.md, NV1) --------------------------------

C8G_SIGMA = {"rel": 0.02, "abs_": 0.05e-3, "sigma_x": 2.0}  # A, A, V of Vp


def _triode_figures(t: Triode, vg: float, vp: float) -> tuple[float, float, float]:
    return float(t.ip(vg, vp)), float(t.gm(vg, vp)), float(t.rp(vg, vp))


def build_6c8g() -> dict[str, Any]:
    """The Novachord's top-octave oscillator: a Koren triode fit to RCA's plate curves
    (digitized, 1.0-6.2 mA) with the printed class-A1 point (Ip, gm, rp) weighed in."""
    from scipy.optimize import least_squares

    from varimu.devices.triode import KorenTriode

    pub = _published()["6C8G"]
    a = pub["class_a1"]
    vg, vp, ip = load_csv("rca_6c8g_plate.csv").T
    sigma = effective_sigma(vp, ip, vg, 20.0, **C8G_SIGMA)

    def resid(x):
        t = Triode("fit", KorenTriode(*np.exp(x)))
        r = (t.ip(vg, vp) - ip) / sigma
        f = _triode_figures(t, a["vg_v"], a["vp_v"])
        pts = [
            np.log(f[0] / a["ip_a"]) / 0.03,
            np.log(f[1] / a["gm_s"]) / 0.05,
            np.log(f[2] / a["rp_ohm"]) / 0.10,
        ]
        return np.r_[r, pts]

    best = None
    for x0 in ([36.0, 1.35, 1500.0, 300.0, 300.0], [36.0, 1.4, 800.0, 100.0, 30.0]):
        sol = least_squares(resid, np.log(x0), x_scale="jac", max_nfev=20000)
        if best is None or sol.cost < best.cost:
            best = sol
    mu, ex, kg1, kp, kvb = (float(v) for v in np.exp(best.x))
    t = Triode("fit", KorenTriode(mu, ex, kg1, kp, kvb))
    rep = curve_report(t.ip(vg, vp), ip, sigma)
    f = _triode_figures(t, a["vg_v"], a["vp_v"])
    caps = pub["capacitances_f"]["t1"]
    return {
        "name": "6C8G",
        "kind": "triode",
        "source": "fit: Koren triode, least squares (effective variance) on the RCA 6C8-G "
        "(1941) plate curves, grid 0..-11 V, digitized: data/datasheets/rca_6c8g.provenance.yaml, "
        f"with the printed class-A1 point (Ip 3%, gm 5%, rp 10%) ({pub['source']})",
        "plate": {"model": "koren", "mu": mu, "ex": ex, "kg1": kg1, "kp": kp, "kvb": kvb},
        "grid_current": dict(PROVISIONAL_GRID),
        "capacitances_f": {
            "gk": caps["gk"],
            "gp": caps["gp"],
            "pk": caps["pk"],
            "source": f"{pub['source']} (triode unit T1, the larger)",
        },
        "fit_report": {
            "plate": rep.as_dict(),
            "sigma": "2% of Ip + 50 uA, with the curve's slope times 2 V of Vp",
            "class_a1_pct": {
                "ip": 100 * (f[0] / a["ip_a"] - 1),
                "gm": 100 * (f[1] / a["gm_s"] - 1),
                "rp": 100 * (f[2] / a["rp_ohm"] - 1),
            },
        },
    }


def build_6w7g() -> dict[str, Any]:
    """The Novachord's divider and control tube: a Koren pentode fit to RCA's class-A1
    figures (Ip, Ig2, gm, rp a third), the cathode-current cutoff (a tenth) and the 6J7's
    triode connection (a third each: the same electrode structure), all six parameters
    free. No curves are printed for it (the sheet points to the 6J7's): the knee is the
    plate resistance's, not a curve's."""
    from scipy.optimize import least_squares

    pub = _published()["6W7G"]
    a, cut, tr = pub["class_a1"], pub["cutoff"], pub["triode_6j7"]
    dv = 1e-3

    def figures(m: KorenPentode):
        vg1, vg2, vp = a["vg1_v"], a["vg2_v"], a["vp_v"]
        gm = (m.ip(vg1 + dv, vg2, vp) - m.ip(vg1 - dv, vg2, vp)) / (2 * dv)
        rp = 2 * dv / (m.ip(vg1, vg2, vp + dv) - m.ip(vg1, vg2, vp - dv))
        return float(m.ip(vg1, vg2, vp)), float(m.ig2(vg1, vg2)), float(gm), float(rp)

    def triode(m: KorenPentode, vg, v):
        return float(m.ip(vg, v, v) + m.ig2(vg, v))

    def resid(x):
        m = KorenPentode(*np.exp(x))
        ip, ig2, gm, rp = figures(m)
        vg, v = tr["vg_v"], tr["vp_v"]
        it = triode(m, vg, v)
        gmt = (triode(m, vg + dv, v) - triode(m, vg - dv, v)) / (2 * dv)
        rpt = 2 * dv / (triode(m, vg, v + dv) - triode(m, vg, v - dv))
        ik = float(
            m.ip(cut["vg1_v"], cut["vg2_v"], cut["vp_v"]) + m.ig2(cut["vg1_v"], cut["vg2_v"])
        )
        ik = max(ik, 1e-30)
        return [
            np.log(ip / a["ip_a"]),
            np.log(ig2 / a["ig2_a"]),
            np.log(gm / a["gm_s"]),
            np.log(rp / a["rp_ohm"]) / 3.0,
            0.1 * np.log(ik / cut["ik_a"]),
            np.log(it / tr["ip_a"]) / 3.0,
            np.log(gmt / tr["gm_s"]) / 3.0,
            np.log(rpt / tr["rp_ohm"]) / 3.0,
        ]

    x0 = np.log([20.0, 1.4, 2000.0, 8000.0, 20.0, 20.0])
    sol = least_squares(resid, x0, xtol=1e-12, ftol=1e-12, max_nfev=4000)
    mu, ex, kg1, kg2, kp, kvb = (float(v) for v in np.exp(sol.x))
    m = KorenPentode(mu, ex, kg1, kg2, kp, kvb)
    ip, ig2, gm, rp = figures(m)
    vg, v = tr["vg_v"], tr["vp_v"]
    caps = pub["capacitances_f"]
    return {
        "name": "6W7G",
        "kind": "pentode",
        "source": "fit: Koren pentode to the class-A1 figures (Ip, Ig2, gm, rp a third), the "
        "cathode-current cutoff (a tenth) and the 6J7's triode connection (a third), log least "
        f"squares ({pub['source']}); no curves printed (the knee from rp alone)",
        "model": {"mu": mu, "ex": ex, "kg1": kg1, "kg2": kg2, "kp": kp, "kvb": kvb},
        "grid_current": dict(PROVISIONAL_GRID),
        "capacitances_f": {
            "g1k": caps["input"],
            "g1p": caps["g1p"],
            "pk": caps["output"],
            "source": f"{pub['source']} (with close-fitting shield)",
        },
        "fit_report": {
            "class_a1_pct": {
                "ip": 100 * (ip / a["ip_a"] - 1),
                "ig2": 100 * (ig2 / a["ig2_a"] - 1),
                "gm": 100 * (gm / a["gm_s"] - 1),
                "rp": 100 * (rp / a["rp_ohm"] - 1),
            },
            "cutoff_ik_a": float(
                m.ip(cut["vg1_v"], cut["vg2_v"], cut["vp_v"]) + m.ig2(cut["vg1_v"], cut["vg2_v"])
            ),
            "triode_6j7_ip_a": triode(m, vg, v),
        },
    }


def build_2a3() -> dict[str, Any]:
    """The Novachord's output tubes: a Koren triode fit to RCA's class-A1 point (Ip, gm,
    rp), the push-pull zero-signal point (40 mA a tube at 300 V, -62 V) and the transfer
    curve's foot (a tenth: read by eye). Directly heated: the filament's midpoint is the
    cathode."""
    from scipy.optimize import least_squares

    from varimu.devices.triode import KorenTriode

    pub = _published()["2A3"]
    a, pp, foot = pub["class_a1"], pub["push_pull_ab1"]["fixed_bias"], pub["transfer_foot"]

    def resid(x):
        t = Triode("fit", KorenTriode(*np.exp(x)))
        f = _triode_figures(t, a["vg_v"], a["vp_v"])
        return [
            np.log(f[0] / a["ip_a"]),
            np.log(f[1] / a["gm_s"]),
            np.log(f[2] / a["rp_ohm"]),
            np.log(float(t.ip(pp["vg_v"], pp["vp_v"])) / (pp["ip0_a"] / 2)),
            0.1 * np.log(float(t.ip(foot["vg_v"], foot["vp_v"])) / foot["ip_a"]),
        ]

    sol = least_squares(resid, np.log([4.2, 1.4, 1500.0, 50.0, 300.0]), xtol=1e-14, ftol=1e-14)
    mu, ex, kg1, kp, kvb = (float(v) for v in np.exp(sol.x))
    t = Triode("fit", KorenTriode(mu, ex, kg1, kp, kvb))
    f = _triode_figures(t, a["vg_v"], a["vp_v"])
    caps = pub["capacitances_f"]
    return {
        "name": "2A3",
        "kind": "triode",
        "source": "fit: Koren triode to the class-A1 point (Ip, gm, rp), the push-pull "
        "zero-signal point and the transfer curve's foot (a tenth), log least squares "
        f"({pub['source']})",
        "plate": {"model": "koren", "mu": mu, "ex": ex, "kg1": kg1, "kp": kp, "kvb": kvb},
        "grid_current": dict(PROVISIONAL_GRID),
        "capacitances_f": {
            "gk": caps["gk"],
            "gp": caps["gp"],
            "pk": caps["pk"],
            "source": f"{pub['source']} (no external shield)",
        },
        "fit_report": {
            "class_a1_pct": {
                "ip": 100 * (f[0] / a["ip_a"] - 1),
                "gm": 100 * (f[1] / a["gm_s"] - 1),
                "rp": 100 * (f[2] / a["rp_ohm"] - 1),
            },
            "push_pull_ip0_a": float(t.ip(pp["vg_v"], pp["vp_v"])),
            "foot_ip_a": float(t.ip(foot["vg_v"], foot["vp_v"])),
        },
    }


def build_key_contact() -> dict[str, Any]:
    """An organ key's contact spring on its bus bar (the Novachord's playing keys, manual
    Fig. 19): closed a fraction of an ohm, open the insulation between springs. Worked by
    a key's gate: a make contact, open at 0.25 V and below, closed at 0.75 V and above (a
    0 / 1 V gate)."""
    return {
        "name": "KEY_CONTACT",
        "kind": "contact",
        "source": "provisional: model knowledge (a precious-metal key contact's resistance "
        "and a bakelite channel's insulation); the gate's thresholds a convention: numerics",
        "contact": {
            "r_on_ohm": 1.0,
            "r_off_ohm": 1.0e12,
            "v_open_v": 0.25,
            "v_closed_v": 0.75,
            "source": "provisional: model knowledge (organ key contacts: palladium or silver "
            "wire on a bus bar, tens of milliohms; 1 ohm keeps the solver's matrix modest and "
            "is negligible against the key circuit's tens of kilohms. Insulation: a dry "
            "bakelite channel, >= 1e12 ohm)",
        },
    }


def build_key_break() -> dict[str, Any]:
    """A key's break contact: KEY_CONTACT's spring on its bus bar, closed with the key up
    (gate 0.25 V and below), opened as the key goes down (0.75 V and above): the
    Novachord's spring 3 on bus A and spring 1 on the cut-off bus (manual Fig. 19)."""
    d = build_key_contact()
    d["name"] = "KEY_BREAK"
    d["contact"] = dict(d["contact"], v_open_v=0.75, v_closed_v=0.25)
    d["source"] += "; a break contact: the gate's thresholds swapped"
    return d


def _triode_from_columns(name: str, key: str, use: str) -> dict[str, Any]:
    """A Koren triode fit to a sheet's class-A1 columns (Ip, gm, rp at each), log least
    squares, all five parameters free."""
    from scipy.optimize import least_squares

    from varimu.devices.triode import KorenTriode

    pub = _published()[key]
    pts = pub["class_a1"]

    def resid(x):
        t = Triode("fit", KorenTriode(*np.exp(x)))
        r = []
        for p in pts:
            f = _triode_figures(t, p["vg_v"], p["vp_v"])
            r += [np.log(f[0] / p["ip_a"]), np.log(f[1] / p["gm_s"]), np.log(f[2] / p["rp_ohm"])]
        return r

    best = None
    for x0 in ([20.0, 1.4, 1000.0, 300.0, 300.0], [14.0, 1.35, 1500.0, 100.0, 30.0]):
        sol = least_squares(resid, np.log(x0), xtol=1e-14, ftol=1e-14, max_nfev=20000)
        if best is None or sol.cost < best.cost:
            best = sol
    mu, ex, kg1, kp, kvb = (float(v) for v in np.exp(best.x))
    t = Triode("fit", KorenTriode(mu, ex, kg1, kp, kvb))
    caps = pub["capacitances_f"]
    report = {}
    for p in pts:
        f = _triode_figures(t, p["vg_v"], p["vp_v"])
        report[f"vp_{p['vp_v']}_pct"] = {
            "ip": 100 * (f[0] / p["ip_a"] - 1),
            "gm": 100 * (f[1] / p["gm_s"] - 1),
            "rp": 100 * (f[2] / p["rp_ohm"] - 1),
        }
    return {
        "name": name,
        "kind": "triode",
        "source": f"fit: Koren triode to the class-A1 columns (Ip, gm, rp at each), log least "
        f"squares ({pub['source']}); {use}",
        "plate": {"model": "koren", "mu": mu, "ex": ex, "kg1": kg1, "kp": kp, "kvb": kvb},
        "grid_current": dict(PROVISIONAL_GRID),
        "capacitances_f": {
            "gk": caps["gk"],
            "gp": caps["gp"],
            "pk": caps["pk"],
            "source": pub["source"],
        },
        "fit_report": _clean(report),
    }


def build_6j5g() -> dict[str, Any]:
    """The Novachord preamplifier's 6J5-G (manual Fig. 21)."""
    return _triode_from_columns("6J5G", "6J5", "the 6J5-G (glass) shares the 6J5's ratings")


def build_56() -> dict[str, Any]:
    """The Novachord power amplifier's input pair (manual Fig. 22)."""
    return _triode_from_columns("56", "56", "the Hammond organ amplifier's input pair")


def build_reed_contact() -> dict[str, Any]:
    """A vibrato reed's contact (the Novachord's six reeds, manual p.22: 'three contacts on
    each reed ... The contacts should make in the middle of the reed's motion'): worked by the
    reed's displacement as a voltage (1 V per mm, the circuit's mechanical analogue), a make
    contact closing as the reed passes its middle going positive, within +-0.05 mm."""
    return {
        "name": "REED_CONTACT",
        "kind": "contact",
        "source": "provisional: model knowledge (a tungsten or silver reed contact's resistance "
        "and its insulation); the switching band a contact's travel, numerics",
        "contact": {
            "r_on_ohm": 1.0,
            "r_off_ohm": 1.0e12,
            "v_open_v": -0.05,
            "v_closed_v": 0.05,
            "source": "provisional: model knowledge (contacts 'make in the middle of the "
            "reed's motion', SM2 p.22: the band +-0.05 mm of a ~1 mm swing)",
        },
    }


def build_reed_drive() -> dict[str, Any]:
    """The reed's drive contact: REED_CONTACT closing on the other half of the swing (a
    break contact on the displacement), so the drive coil pulls while the reed is away."""
    d = build_reed_contact()
    d["name"] = "REED_DRIVE"
    d["contact"] = dict(d["contact"], v_open_v=0.05, v_closed_v=-0.05)
    d["source"] += "; the drive contact: closed on the reed's negative half"
    return d


# The Type 4 tank's coils (codes A in, B out), Rod Elliott's measurements.
ESP_REVERB = "web: https://sound-au.com/articles/reverb.htm"
PARKER_BILBAO = (
    "web: https://www.pure.ed.ac.uk/ws/portalfiles/portal/12456049/"
    "Spring_Reverbation_A_Physical_Perspective.pdf"
)
ACCUTRONICS_SPECS = (
    "web: https://www.amplifiedparts.com/tech-corner/accutronics-products-and-specifications"
)
# Rated drive and typical output of a Type 4 with coils A and B (ESP_REVERB, Tables 1, 3).
TANK_RATED_A_RMS = 28e-3
TANK_TYPICAL_OUT_V_RMS = 6.5e-3
# The band the typical output is read over: the tank's useful bandwidth (ESP_REVERB).
TANK_BAND_HZ = (200.0, 6000.0)


def build_acc4ab3c1b() -> dict[str, Any]:
    """An Accutronics 4AB3C1B (the Fender 6G15's tank; docs/REVERB_PLAN.md, E3): two
    springs, an 8 ohm input coil, a 2250 ohm output coil, long decay. The coils are Rod
    Elliott's measurements; the springs a measured tank's (Parker & Bilbao's Leem KA-1210,
    springs 1 and 3: the Type 4's own aren't published); the decay the part code's class.
    The transducers' force per ampere and EMF per velocity (one geometry, so they scale as
    the square root of the coils' inductances) are calibrated so the rated input current
    gives the typical output, rms over the tank's useful band, through the springs' own
    response (varimu.devices.spring)."""
    from varimu.devices import spring as sp

    # (wire diameter, helix diameter, turns, helix length) in m: Table 2's springs 1 and 3.
    keys = ("wire_diameter_m", "helix_diameter_m", "turns", "helix_length_m")
    springs = [
        dict(zip(keys, s, strict=True))
        for s in ((0.35e-3, 4.4e-3, 303, 0.163), (0.35e-3, 4.6e-3, 351, 0.163))
    ]
    data: dict[str, Any] = {
        "name": "ACC4AB3C1B",
        "kind": "spring_tank",
        "source": "an Accutronics 4AB3C1B: Elliott's coil measurements, a measured tank's "
        "springs (Parker & Bilbao, DAFx-09), the part code's decay class; transducers "
        "calibrated to the typical output; varimu.devices.spring",
        "springs": {
            "list": springs,
            "source": f"provisional: {PARKER_BILBAO} (Table 2: the Leem Pro KA-1210's springs "
            "1 and 3, micrometer and caliper; the Type 4's springs aren't published, a 4AB3C1B "
            f"has two: {ACCUTRONICS_SPECS})",
        },
        "material": {
            "density_kg_m3": 7800.0,
            "youngs_pa": 2.0e11,
            "source": f"{PARKER_BILBAO} (appendix A: steel wire, E 2e11 N/m^2, rho 7800 kg/m^3)",
        },
        "input": {
            "re_ohm": 0.81,
            "le_h": 1.27e-3,
            "force_per_a": 0.0,
            "saturation_a": 0.25,
            "source": "",
        },
        "output": {
            "re_ohm": 200.0,
            "le_h": 0.270,
            "v_per_m_s": 0.0,
            "source": f"{ESP_REVERB} (Table 3, code B: 2250 ohm, 200 ohm DC, ~270 mH, "
            "6.5 mV rms typical output); v_per_m_s: fit (see input)",
        },
        "losses": {
            "t60_500hz_s": 3.4,
            "loss_factor": 2.0e-4,
            "source": f"t60_500hz_s: {ACCUTRONICS_SPECS} (decay code 3, long: 2.75-4.0 s; the "
            "class's middle, read at 500 Hz); loss_factor: provisional: model knowledge "
            "(spring steel's internal loss factor, ~1e-4..5e-4: the decay's fall above a "
            "kHz); the rest (the rubber end dampers) flat in frequency",
        },
        "model": {
            "f_max_hz": 16000.0,
            "tail_db": 90.0,
            "source": "numerical: the audio branch's modes up to 16 kHz (below 0.45 of the "
            "rate), each summed until 90 dB down",
        },
    }
    c = sp.spring_tank_from_data(data, "fit")
    # The band rms of force -> velocity, from the springs' response.
    fs = 48000.0
    h = sp.impulse_response(sp.spec_of(c, 0.45 * fs), fs)
    f = np.fft.rfftfreq(len(h), 1.0 / fs)
    band = (f >= TANK_BAND_HZ[0]) & (f <= TANK_BAND_HZ[1])
    h_rms = float(np.sqrt(np.mean(np.abs(np.fft.rfft(h)[band]) ** 2)))
    ratio = math.sqrt(c.output_le_h / c.input_le_h)
    k_in = math.sqrt(TANK_TYPICAL_OUT_V_RMS / (ratio * h_rms * TANK_RATED_A_RMS))
    data["input"]["force_per_a"] = k_in
    data["output"]["v_per_m_s"] = k_in * ratio
    data["input"]["source"] = (
        f"{ESP_REVERB} (Table 1, code A: 8 ohm, 0.81 ohm DC, 1.27 mH, 28 mA rms rated; "
        "saturation_a: 'driven to about 250 mA at 1 kHz before saturation', roughly constant "
        "above 300 Hz, its shape provisional: tanh); "
        f"force_per_a: fit: {TANK_RATED_A_RMS * 1e3:g} mA rms gives "
        f"{TANK_TYPICAL_OUT_V_RMS * 1e3:g} mV rms of EMF over {TANK_BAND_HZ[0]:g}-"
        f"{TANK_BAND_HZ[1]:g} Hz (the useful band, {ESP_REVERB}) through the springs' "
        "response; the output's EMF per velocity is this times sqrt(L_out / L_in) (one "
        "transducer geometry, turns ~ sqrt(L))"
    )
    spec = sp.spec_of(c)
    data["fit_report"] = {
        "band_rms_m_s_per_n": h_rms,
        "delay_s": [
            sp.delay_s(r, rr, length, c.youngs_pa, c.density_kg_m3)
            for r, rr, length in spec.springs
        ],
        "transition_hz": [
            sp.transition_hz(r, rr, c.youngs_pa, c.density_kg_m3) for r, rr, _ in spec.springs
        ],
    }
    return _clean(data)


BUILDERS = {
    "6386": build_6386,
    "12AX7": build_12ax7,
    "12BH7": build_12bh7,
    "12AU7": build_12au7,
    "6201": build_6201,
    "6973": build_6973,
    "GZ34": build_gz34,
    "SI_RECTIFIER": build_si_rectifier,
    "ZPD8V2": build_zpd8v2,
    "ZPD12": build_zpd12,
    "1N4148": build_1n4148,
    "J175": build_j175,
    "2N3819": build_2n3819,
    "PN4092": build_pn4092,
    "2N5457": build_2n5457,
    "2N3707": build_2n3707,
    "2N3053": build_2n3053,
    "2N5087": build_2n5087,
    "2N4033": build_2n4033,
    "2N5784": build_2n5784,
    "2N5781": build_2n5781,
    "2N6254": build_2n6254,
    "RCA29B": build_rca29b,
    "RCA30B": build_rca30b,
    "2N3904": build_2n3904,
    "2N3906": build_2n3906,
    "UA726": build_ua726,
    "EL34T": build_el34t,
    "6084": build_6084,
    "5651": build_5651,
    "SELENIUM": build_selenium,
    "B450C80": build_b450c80,
    "EF804S": build_ef804s,
    "E83F": build_e83f,
    "BK4134": build_bk4134,
    "K47": build_k47,
    "CK12": build_ck12,
    "K87": build_k87,
    "KK84": build_kk84,
    "R57": build_r57,
    "R59": build_r59,
    "R_D112": build_r_d112,
    "R_MD421": build_r_md421,
    "R_SM7": build_r_sm7,
    "RIBBON_44BX": build_ribbon_44bx,
    "RIBBON_4038": build_ribbon_4038,
    "RIBBON_77DX": build_ribbon_77dx,
    "RIBBON_M160": build_ribbon_m160,
    "VF14T": build_vf14t,
    "6X4": build_6x4,
    "6AL5": build_6al5,
    "12AY7": build_12ay7,
    "6V6GT": build_6v6gt,
    "5Y3GT": build_5y3gt,
    "P12R": build_p12r,
    "EMT140": build_emt140,
    "EMT240": build_emt240,
    "6K6GT": build_6k6gt,
    "ACC4AB3C1B": build_acc4ab3c1b,
    "SCOTCH111": build_scotch111,
    "LAMP327": build_lamp327,
    "VTL5C1": fit_vtl5c1,
    "VTL5C2": fit_vtl5c2,
    "PDVP9203": fit_pdvp9203,
    "BC550C": build_bc550c,
    "BC413C": build_bc413c,
    "BC560C": build_bc560c,
    "BC238": build_bc238,
    "2D21": build_2d21,
    "884": build_884,
    "6C8G": build_6c8g,
    "6W7G": build_6w7g,
    "2A3": build_2a3,
    "KEY_CONTACT": build_key_contact,
    "KEY_BREAK": build_key_break,
    "REED_CONTACT": build_reed_contact,
    "REED_DRIVE": build_reed_drive,
    "6J5G": build_6j5g,
    "56": build_56,
}

REPORT_FOR = {
    "6386": "6386_fit.png",
    "12AY7": "12ay7_fit.png",
    "6V6GT": "6v6gt_fit.png",
    "5Y3GT": "5y3gt_fit.png",
    "P12R": "p12r_fit.png",
    "SCOTCH111": "scotch111_fit.png",
}


def plot_fit(name: str, root: Path = DEVICE_DIR) -> Path:
    """The review plot of a fitted device (reports/devices/), from its saved version."""
    from varimu.devices import plots

    path = REPORT_DIR / REPORT_FOR[name]
    if name == "P12R":
        from varimu.devices import speaker_fit

        ref, text = versions.read_text(name, root)
        meta = yaml.safe_load(text)["fit_report"]
        return speaker_fit.plot_fit(
            load_speaker(str(ref), root),
            speaker_fit.load_curves(DATASHEETS, "jensen_p12r"),
            meta,
            path,
            f"{ref}: the model against the Jensen sheet (IEC baffle, 2.83 V, 1 m)",
        )
    if name == "SCOTCH111":
        from varimu.devices import tape_fit

        ref, _ = versions.read_text(name, root)
        tape = load_tape(str(ref), root)
        rows = load_csv("scotch_111_remanence.csv")
        return tape_fit.plot_fit(
            tape.ensemble(),
            tape.ms_a_m,
            tape.coating_m,
            rows[:, 0],
            rows[:, 1],
            _published()["SCOTCH111"]["coercivity_a_m"],
            path,
            f"{ref}: the Preisach ensemble against 3M Sound Talk No. 20 (Type B) and Eilers' Hc",
            orientation=tape.orientation,
        )
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
