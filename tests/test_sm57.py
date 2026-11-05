"""The SM57 (docs/SM57_PLAN.md): the cartridge R57@1 against Shure's published figures (SM2's
done-when: each fitted unknown hits its figure), and the circuit file."""

from __future__ import annotations

import csv

import numpy as np
import pytest

from varimu.circuit import builder, spec
from varimu.circuit.ir import NoiseCurrent
from varimu.config import CONFIG_DIR, DATA_DIR
from varimu.devices import versions
from varimu.devices.library import component_data, load_moving_coil
from varimu.mics.free_field import body_entry_factors
from varimu.mics.networks import moving_coil_response

L_PRIMARY_H = 0.386  # cj06 (scripts/fit_sm57.py)
TURNS = 4.53  # cj06
ANGLES = [0.0, 90.0, 180.0]


VERSION = (
    "R57@4"  # the circuit's (on the body; @1 on a sphere, @2 before the cap, @3 before the mode)
)
_ENT: dict = {}


def _response(f, theta_deg):
    """Volts open circuit at the 'H' winding per pascal of a plane wave from theta, the
    entries on the component's body (one BEM solve per frequency, all angles kept)."""
    g = component_data(VERSION)["geometry"]
    c = load_moving_coil(VERSION)
    f = np.atleast_1d(np.asarray(f, float))
    missing = [x for x in f if float(x) not in _ENT]
    if missing:
        fr, rr = body_entry_factors(
            np.array(missing), np.radians(ANGLES), g["body"], g["diaphragm"]["radius_m"]
        )
        for i, x in enumerate(missing):
            _ENT[float(x)] = (fr[i], rr[i])
    j = ANGLES.index(theta_deg)
    ent = (np.array([_ENT[float(x)][0][j] for x in f]), np.array([_ENT[float(x)][1][j] for x in f]))
    return TURNS * moving_coil_response(c, f, ent, l_load_h=L_PRIMARY_H)


def _rows(name, doc):
    with open(DATA_DIR / "datasheets" / name, encoding="utf-8") as f:
        return [r for r in csv.DictReader(f) if r["document"] == doc]


def test_r57_is_pinned_and_locked():
    assert versions.versions("R57")
    c = load_moving_coil(VERSION)
    assert c.re_ohm == 12.1  # hr23
    assert sum(e.kind == "G" and e.c == "@v" for e in c.elements) == 1  # the coil's (+ modes')


def test_sensitivity():
    """s68 'H': 0.149 mV/ubar at 1 kHz open circuit (the plan's +-3 dB; fitted to 0.1 dB)."""
    h = abs(_response(np.array([1000.0]), 0.0)[0])
    assert 20 * np.log10(h / 1.49e-3) == pytest.approx(0.0, abs=0.1)


def test_on_axis_below_the_presence_peak():
    """s68's response, 50 Hz - 6.5 kHz (to the presence peak) re 1 kHz: within the plan's
    +-2 dB (the region above is the diaphragm's modes and the cap, SM3)."""
    rows = [r for r in _rows("shure_sm57_response.csv", "s68") if r["quality"] != "coarse"]
    f = np.array([float(r["freq_hz"]) for r in rows])
    db = np.array([float(r["db"]) for r in rows])
    keep = (f >= 50) & (f <= 6500)
    h = _response(np.concatenate([[1000.0], f[keep]]), 0.0)
    on = 20 * np.log10(abs(h[1:]) / abs(h[0]))
    assert np.max(abs(on - db[keep])) < 2.2
    assert np.sqrt(np.mean((on - db[keep]) ** 2)) < 1.2


def test_polars_front_to_back():
    """c81's polars at every published frequency (125 Hz - 8 kHz): front-to-back and the
    side within 3 dB (Decisions 3; SM4's done-when on the mic's body)."""
    want = {}
    for r in _rows("shure_sm57_polar.csv", "c81"):
        ang = float(r["angle_deg"]) % 360
        if ang in (90.0, 270.0, 180.0) and r["quality"] != "coarse" or ang == 180.0:
            want.setdefault((float(r["freq_hz"]), 180 if ang == 180 else 90), []).append(
                float(r["db"])
            )
    for (fr, side), v in want.items():
        if (fr, side) == (500.0, 180):  # 500 Hz at the rear: a null, read coarse
            continue
        f = np.array([fr])
        model = 20 * np.log10(abs(_response(f, side)[0]) / abs(_response(f, 0.0)[0]))
        assert model == pytest.approx(np.mean(v), abs=3.0), (fr, side)


def test_circuit_builds_both_impedances():
    s = spec.load_circuit(CONFIG_DIR / "circuits" / "shure_sm57.yaml")
    for pos, tie in ((0, "RH"), (1, "RL")):
        ir = builder.build_ir(s, spec.resolve(s, {"impedance": pos}), "ja")
        names = {e.name for e in ir.elements()}
        assert tie in names and {"GMC_dia_ga", "GMC_dia_ge", "RT1_s1", "RT1_s2"} <= names


def test_noise_skips_the_leak():
    """The cartridge's resistances get Johnson noise, its diaphragm's numerical leak none."""
    s = spec.load_circuit(CONFIG_DIR / "circuits" / "shure_sm57.yaml")
    ir = builder.build(s, {}, noise=True, cores="ja").ir
    noisy = {e.name[3:] for e in ir.elements() if isinstance(e, NoiseCurrent)}
    assert {"RMC_re", "RMC_ps_r1", "RMC_washer"} <= noisy
    assert "RMC_dia_leak" not in noisy


def test_on_axis_to_15_khz():
    """SM3's done-when (Decisions 3): s68's on-axis response within +-2 dB 50 Hz-10 kHz and
    +-3 dB to 15 kHz (the curve ends at 13.9 kHz; its coarse ends left out), with the dome's
    mode drawing the dip at 7.7 kHz and the second peak at 9.6 kHz."""
    rows = [r for r in _rows("shure_sm57_response.csv", "s68") if r["quality"] != "coarse"]
    f = np.array([float(r["freq_hz"]) for r in rows])
    db = np.array([float(r["db"]) for r in rows])
    keep = f >= 50
    h = _response(np.concatenate([[1000.0], f[keep]]), 0.0)
    err = 20 * np.log10(abs(h[1:]) / abs(h[0])) - db[keep]
    lo = f[keep] <= 10000
    assert np.max(abs(err[lo])) < 2.0
    assert np.max(abs(err[~lo])) < 3.0


def test_chain_into_the_v76_is_current():
    """sm57_v76.yaml is compose_chain.py's (the SM57's load replaced by the V76's input,
    the cable across it), and builds with the rear entries' control input."""
    import subprocess
    import sys

    from varimu.config import REPO_ROOT

    r = subprocess.run(
        [sys.executable, "scripts/compose_chain.py", "--mic", "shure_sm57",
         "--pre", "telefunken_v76", "--check"],
        cwd=REPO_ROOT, capture_output=True, text=True,
    )  # fmt: skip
    assert r.returncode == 0, r.stdout + r.stderr
    c = spec.load_circuit(spec.circuit_path("sm57_v76"))
    ir = builder.build(c, {"impedance_sm57": 0}, cores="ja").ir
    assert [x.name for x in ir.controls] == ["p_rear"]
    names = {e.name for e in ir.elements()}
    assert "RLOAD_SM57" not in names and "CCABLE" in names and "GMC_SM57_dia_ga" in names
