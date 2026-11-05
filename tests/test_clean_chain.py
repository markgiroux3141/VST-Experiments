"""The opposite chain (docs/ROOM_LOOP_PLAN.md R4): the op-amp macro part, the pressure omni
(omni_4134) and the clean preamp (clean_pre), composed as omni_clean."""

from __future__ import annotations

import subprocess
import sys

import numpy as np
import pytest

from varimu.circuit import builder, spec
from varimu.circuit.ir import Device, Vccs
from varimu.config import REPO_ROOT


def test_opamp_part_expands_as_documented():
    ir = builder.build(spec.load_circuit(spec.circuit_path("clean_pre"))).ir
    els = {
        e.name: e for e in ir.elements() if e.name.startswith(("RU1", "GU1", "CU1", "VU1", "DU1"))
    }
    assert set(els) == {"RU1_i", "GU1_1", "RU1_1", "CU1_1", "VU1_p", "DU1_p", "VU1_n", "DU1_n",
                        "GU1_o", "RU1_o"}  # fmt: skip
    assert isinstance(els["GU1_1"], Vccs) and els["GU1_1"].gm_s == 1e-3
    assert els["RU1_1"].r_ohm == pytest.approx(1e5 / 1e-3)  # a0 / gm
    gbw = 1e-3 / (2 * np.pi * els["CU1_1"].c_f)
    assert gbw == pytest.approx(10e6)
    assert isinstance(els["DU1_p"], Device) and els["DU1_p"].nodes == ("u1_1", "u1_p")


def test_the_chain_file_is_current():
    r = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "compose_chain.py"), "--mic", "omni_4134",
         "--pre", "clean_pre", "--check"],
        capture_output=True, text=True,
    )  # fmt: skip
    assert r.returncode == 0, r.stdout + r.stderr


def _tone(name: str, amp: float, over: dict) -> tuple[float, float]:
    from varimu.sim import fast
    from varimu.sim.io import TransientSettings

    s = TransientSettings.from_sim_settings(engine="circuitsim")
    fs = s.sample_rate
    t = np.arange(int(0.4 * fs)) / fs
    x = amp * np.sqrt(2) * np.sin(2 * np.pi * 1000 * t) * np.clip(t / 0.02, 0, 1)
    ir = builder.build(spec.load_circuit(spec.circuit_path(name)), over).ir
    v = fast.run_transient(ir, x, settings=s).vectors["v(out)"][int(0.2 * fs) :]
    return float(np.sqrt(np.mean(v**2))), float(np.max(np.abs(v)))


def test_clean_preamp_gain_and_clip():
    pytest.importorskip("circuitsim")
    for g in (20, 40):
        rms, _ = _tone("clean_pre", 0.01, {"gain_db": g})
        # the 150 Ohm generator into the 10 kOhm input: -0.13 dB
        assert 20 * np.log10(rms / 0.01) == pytest.approx(g - 0.13, abs=0.1)
    _, peak = _tone("clean_pre", 0.2, {"gain_db": 40})
    assert 12.0 < peak < 13.6  # the NE5534's +-13 V swing


def test_omni_sensitivity():
    pytest.importorskip("circuitsim")
    rms, _ = _tone("omni_4134", 1.0, {})
    assert rms * 1e3 == pytest.approx(9.5, rel=0.03)  # the capsule at 200 V (A2: 9.53 mV/Pa)
