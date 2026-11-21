"""WZ2: the Wurlitzer 200A's electronics (config/circuits/wurlitzer_200a.yaml, drawn from the
200A schematic; docs/WURLITZER_PLAN.md): the idle point against the drawing's printed
voltages, the polarizing supply, the vibrato against the Pie-finger set (its rate unfitted,
its depth and level fitted by LG-1's cell and R17), VIBRATO off unmodulated, the power
amplifier's clipping."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("circuitsim")

from varimu.wurlitzer import circuit  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "wurlitzer_amp_study", Path(__file__).parents[1] / "scripts" / "wurlitzer_amp_study.py"
)
study = importlib.util.module_from_spec(_spec)
sys.modules["wurlitzer_amp_study"] = study
_spec.loader.exec_module(study)

FS = study.FS


@pytest.fixture(scope="module")
def idle() -> dict[str, float]:
    v = study.render({}, np.zeros(int(0.05 * FS)))
    return {p: float(np.mean(v[p][-int(0.01 * FS) :])) for p in study.PROBES}


def test_rails_and_polarizing_supply(idle):
    assert idle["vpos"] == pytest.approx(22.5, rel=0.02)
    assert idle["vneg"] == pytest.approx(-22.5, rel=0.02)
    assert idle["hv150"] == pytest.approx(150.0, rel=0.02)  # the drawing's +150 V
    assert idle["pk"] == pytest.approx(idle["hv150"], abs=0.1)  # the plate draws no DC


def test_idle_point_against_the_drawing(idle):
    # within 30%: TR-2, the AUX stage, the power amplifier's centre and bias string
    for node in ("c1", "c2", "e2", "c15", "e15", "c16", "e16", "et", "c7"):
        assert idle[node] == pytest.approx(study.PRINTED[node], rel=0.3), node
    assert abs(idle["o"]) < 0.1  # 'select R28 for 0 volts DC at point 16'
    assert 1.0 < idle["b10"] - idle["c14"] < 1.4  # TR-9's bias across the two drivers


def _level_db(sets: dict) -> tuple[float, float]:
    """The AUX envelope's mean (dB) and depth (dB p-p) on a steady tone."""
    f0 = 330.0
    n = int(2.5 * FS)
    v = study.render(sets, 0.2 * np.sin(2 * np.pi * f0 * np.arange(n) / FS))
    e = study.envelope_db(v["out"], f0, FS)[FS : -int(0.2 * FS)]
    return float(np.mean(e)), study.envelope_stats(v["out"], f0, FS, 1.0)["depth_db_pp"]


def test_vibrato_rate_and_depth():
    """The rate is the drawing's twin-T, unfitted; the depth, the level and the envelope's
    shape are LG-1's and R17's fit (scripts/fit_wurlitzer_lg1.py: 5.28 dB p-p, -0.60 dB, H2
    -13.7 dB, against the Pie-finger set's 6.22 dB, -1.50 dB, -13.8 dB)."""
    m = study.vibrato_model(seconds=2.5)
    assert m["rate_hz"] == pytest.approx(5.74, rel=0.08)  # Pie-finger 5.73, the 200's manual 5.75
    assert m["depth_db_pp"] == pytest.approx(5.28, abs=0.4)
    assert m["h2_db"] == pytest.approx(-13.8, abs=2.0)
    assert 6.0 < m["osc_vpp"] < 13.0  # the drawing: 11.5 V p-p at the collector


def test_vibrato_knob_is_progressive_and_level():
    """VIBRATO deepens across its travel (the VTL5C2 stand-in at 0.4-1 kOhm did nothing below
    full, then the level jumped +23 dB); full changes the level slightly down, as the recording
    (-0.6 dB at the fit, the recording -1.5)."""
    off, _ = _level_db({"vibrato": 0.0})
    half, d_half = _level_db({"vibrato": 0.5})
    full, d_full = _level_db({"vibrato": 1.0})
    assert 1.2 < d_half < 2.6  # 1.8 dB p-p at the fit
    assert d_full > d_half + 2.0
    assert -2.5 < full - off < 0.0
    assert -5.0 < half - off < -1.5


def test_vibrato_does_not_throb():
    """No DC through LG-1's cell (R5 to ground, the printed voltages' reading): with no note,
    VIBRATO full leaves the AUX output as quiet as off (the Pie-finger set's 5.7 Hz content is
    ~-54 dB re a note either way). With R5 on x it throbbed at 0.35 V p-p."""
    n = int(2.0 * FS)
    quiet = {
        vib: float(np.ptp(study.render({"vibrato": vib}, np.zeros(n))["out"][FS:]))
        for vib in (0.0, 1.0)
    }
    assert quiet[1.0] < 2e-3
    assert quiet[1.0] < 3 * quiet[0.0] + 1e-4


def test_vibrato_off_is_unmodulated():
    f0 = 330.0
    n = int(2.5 * FS)
    v = study.render({"vibrato": 0.0}, 0.2 * np.sin(2 * np.pi * f0 * np.arange(n) / FS))
    assert study.envelope_stats(v["out"], f0, FS, 1.0)["depth_db_pp"] < 0.5


def test_power_amplifier_clips_near_20_watts():
    # the drive as WZ2 set it, at 31 pF of reeds: the same current into the plate whatever
    # CREEDS is (`in` pushes C_reeds d(in)/dt)
    scale = 31.0e-12 / circuit.c_reeds_f()

    def at(a: float) -> tuple[float, float]:
        n = int(0.3 * FS)
        x = scale * a * np.sin(2 * np.pi * 1000 * np.arange(n) / FS)
        v = study.render({"volume": 1.0}, x)
        seg = v["spk"][n // 2 :]
        return float(np.mean(seg**2) / 8.0), study.thd(seg, 1000.0)

    w, d = at(1.6)
    assert w > 10.0 and d < 0.01
    w, d = at(2.8)
    assert d > 0.03 and w < 35.0
