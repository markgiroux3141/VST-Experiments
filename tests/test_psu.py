"""The 670's power supply in the one coupled circuit (main plan Phase 3, circuitsim).

The supply is traced on drawing A-96039 (data/schematics/fairchild_670/README.md,
"Supply rails"); its unprinted values are calibrated by scripts/calibrate_psu.py to what
the drawing prints and a measured unit shows. These check that, and that its ripple and
sag reach both the audio path and the sidechain (plan: Coupling Checklist). Measured
2026-10-21 (see the comments for the values).
"""

import dataclasses

import numpy as np
import pytest

from varimu.circuit import netlist as nl
from varimu.circuit.ir import VoltageProbe
from varimu.measure import signals
from varimu.sim import fast, io

pytestmark = pytest.mark.skipif(not fast.available(), reason="needs `uv sync --extra fast`")

FS = 96000
HOT = {"input_atten_db": 0.0, "ac_threshold": 1.0, "time_constant": 1}
NODES = ("out", "cv", "bp", "ur", "sg", "nb1", "nb2", "nb3", "nb4", "ka", "ta", "kb", "tb", "k1")


def _run(overrides: dict, x_dbfs: np.ndarray) -> dict:
    s = io.TransientSettings.from_sim_settings(engine="circuitsim")
    ir = nl.build(overrides).ir
    ir = dataclasses.replace(ir, probes=tuple(VoltageProbe(n) for n in NODES))
    r = fast.run_transient(ir, x_dbfs * s.full_scale_volts_peak, settings=s)
    return {k[2:-1]: v for k, v in r.vectors.items()} | {"fs_v": s.full_scale_volts_peak}


def _tone(v: np.ndarray, f: float) -> float:
    """Peak amplitude of the f component (Hann window)."""
    t = np.arange(len(v)) / FS
    w = np.hanning(len(v))
    return float(2 * np.abs(np.sum(w * (v - v.mean()) * np.exp(-2j * np.pi * f * t))) / np.sum(w))


def _bank_ma(r: dict, side: str, sl=slice(None)) -> float:
    v_k = np.mean(r[f"k{side}"][sl] - r[f"t{side}"][sl])
    return float(v_k / nl.resolve()["r103_r104_ohm"] * 1e3)


@pytest.fixture(scope="module")
def idle():
    """0.4 s of silence after the supply settles (start.settle_s), matched and mismatched."""
    x = np.zeros(int(0.4 * FS))
    return {
        "matched": _run(HOT, x),
        "mismatched": _run({**HOT, "v6386_a.emission_scale": 0.9}, x),
    }


def test_idle_rails_are_what_the_drawing_prints_and_a_unit_measures(idle):
    """Measured: unregulated 434.9 V, B+ 240.06 V, C303 -6.22 V, R303 end -13.77 V,
    banks 24.9 mA, 12AX7 cathodes 3.73 V."""
    r = idle["matched"]
    m = {k: float(np.mean(v)) for k, v in r.items() if k != "fs_v"}
    assert 420 <= m["ur"] <= 450  # sch: "(420V TO 450V)"
    assert m["bp"] == pytest.approx(240.0, abs=0.5)  # sch: "(ADJ. TO 240 V.)"
    assert -14.5 <= m["nb4"] <= -13.0  # sch: "-13V. TO -14.5V."
    assert m["nb2"] == pytest.approx(-6.2, abs=0.3)  # measured (GroupDIY, Dave P)
    assert m["nb1"] == pytest.approx(-34.0, abs=2.0)  # Dave P's ~34 V across the bias reservoir
    for side in "ab":
        assert _bank_ma(r, side) == pytest.approx(26.0, rel=0.15)  # measured ~26 mA per bank
    # web: "3.6V (cut-off)", the DC threshold's low end (the circuit file's r119_ohm)
    assert m["k1"] == pytest.approx(3.6, abs=0.3)


def test_ripple_reaches_the_grids_and_the_output_through_mismatch(idle):
    """The bias supply's 120 Hz ripple sits on both grids through ZERO (common mode, so a
    matched push-pull stage cancels it); a 10% emission mismatch lets it through as hum.
    Measured: CV 1.8 mV, B+ 4.1 mV, output -277 dBFS matched, -121 dBFS mismatched."""
    m, mm = idle["matched"], idle["mismatched"]
    zero = nl.resolve(HOT)["zero"]
    assert _tone(m["cv"], 120) == pytest.approx(zero * _tone(m["nb3"], 120), rel=0.2)
    assert 0.5e-3 < _tone(m["cv"], 120) < 10e-3
    assert 1e-3 < _tone(m["bp"], 120) < 20e-3  # the regulator's residual ripple
    hum_m = 20 * np.log10(_tone(m["out"] / m["fs_v"], 120) + 1e-30)
    hum_mm = 20 * np.log10(_tone(mm["out"] / mm["fs_v"], 120))
    assert -150 < hum_mm < -90, hum_mm
    assert hum_mm > hum_m + 60, (hum_m, hum_mm)


def test_sag_reaches_the_audio_path_and_the_sidechain():
    """A 0 dBFS burst at the hottest front panel. Audio path: the 6386 current halves, so
    the drop across the bias choke L302 shrinks and the stage's cathode return (C303)
    moves several volts (measured -8.2 -> -14.5 V), and the unregulated rail rises as
    the stage stops loading it (439 -> 452 V). Sidechain: the 6973 screens' tap sags
    while they drive the CV (153 -> 147 V), and their grid current, charging the
    coupling capacitors, pulls the bias supply's R303 end down (-13.8 -> -15.0 V). The
    240 V regulator holds (within 0.6 V)."""
    spec = next(s for s in signals.default_library() if s.name == "burst_1000hz_0dbfs")
    sig = signals.render(spec, sample_rate=FS, seed=0)
    a = sig.meta["burst_start"]
    r = _run(HOT, sig.samples[: a + int(1.3 * FS)])
    pre, late = slice(a - FS // 5, a), slice(a + int(0.8 * FS), a + int(1.3 * FS))

    def shift(node: str) -> float:
        return float(np.mean(r[node][late]) - np.mean(r[node][pre]))

    assert _bank_ma(r, "a", late) < 0.6 * _bank_ma(r, "a", pre)
    assert shift("nb2") < -3.0
    assert shift("ur") > 5.0
    assert shift("sg") < -3.0
    assert shift("nb4") < -0.5
    assert np.max(np.abs(r["bp"][a:] - 240.0)) < 1.5
