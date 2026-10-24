"""The coupled 670 slice on both engines: stable at idle, gain reduction rising with level.

These run real transients (ngspice: about 20-40 s in total at ~50x real time;
circuitsim: a few seconds). Agreement between the engines is in
test_circuitsim_slice.py.
"""

import numpy as np
import pytest

from varimu.circuit import netlist as nl
from varimu.measure import metrics
from varimu.measure.signals import stepped_sine
from varimu.sim import fast, ngspice
from varimu.sim.io import TransientSettings, run_transient

# Most sensitive front panel so a short signal shows strong compression.
HOT = {"input_atten_db": 0.0, "ac_threshold": 1.0, "dc_threshold": 0.0, "time_constant": 1}


def _ngspice_available() -> bool:
    try:
        ngspice.find_ngspice()
    except ngspice.SimulatorNotFound:
        return False
    return True


ENGINES = [
    pytest.param(
        "ngspice", marks=pytest.mark.skipif(not _ngspice_available(), reason="no ngspice")
    ),
    pytest.param(
        "circuitsim",
        marks=pytest.mark.skipif(not fast.available(), reason="needs `uv sync --extra fast`"),
    ),
]


def _run(engine, x_dbfs, overrides):
    """Production settings of `engine`; every probe comes back. circuitsim runs the
    Jiles-Atherton cores, ngspice their linear limit (it has no core model)."""
    s = TransientSettings.from_sim_settings(engine=engine)
    c = nl.build(overrides, cores=s.cores)
    x = x_dbfs * s.full_scale_volts_peak
    if engine == "circuitsim":
        return fast.run_transient(c.ir, x, settings=s), s
    return run_transient(
        c.text, x, input_node=c.input_node, save=list(c.save), settings=s, files=c.files
    ), s


@pytest.mark.parametrize("engine", ENGINES)
def test_idle_circuit_is_quiet_and_sits_at_its_operating_point(engine):
    """No input: no parasitic oscillation, CV stays at ZERO * the bias supply's C108 node.

    A lossless transformer model made the 6386 stage oscillate at ~30 kHz and
    pump the CV through grid current; this guards against that coming back.
    Since the power supply is in the circuit (Phase 3), the CV carries the bias
    supply's ripple (C108's ~14 mV pp at 120 Hz times ZERO, ~4 mV pp) and the end
    of its settling.
    """
    r, s = _run(engine, np.zeros(int(0.03 * 96000)), HOT)
    out = r.vectors["v(out)"] / s.full_scale_volts_peak
    assert np.max(np.abs(out)) < 1e-4  # below -80 dBFS
    cv = r.vectors["v(cv)"]
    assert np.ptp(cv) < 0.02
    zero_v = nl.resolve(HOT)["zero"] * r.vectors["v(nb3)"].mean()
    assert cv.mean() == pytest.approx(zero_v, abs=0.05)
    np.testing.assert_allclose(r.vectors["v(ga)"], cv, atol=1e-3)


@pytest.mark.parametrize("engine", ENGINES)
def test_gain_reduction_increases_with_input_level(engine):
    sig = stepped_sine(
        freq_hz=1000, start_dbfs=-30, stop_dbfs=0, step_db=10, hold_s=0.06, sample_rate=96000
    )
    r, s = _run(engine, sig.samples, HOT)
    y = r.vectors["v(out)"] / s.full_scale_volts_peak
    pts = metrics.segment_gains(sig.samples, y, sig.meta["segments"])
    gains = np.array([g for _, g in pts])
    gr = gains[0] - gains
    assert np.all(np.diff(gr) > 0.5), gr  # strictly more reduction at every step
    assert gr[-1] > 10, gr  # 0 dBFS at the most sensitive setting compresses hard
    # The control voltage is what does it: more negative at every step.
    cv = [np.median(r.vectors["v(cv)"][g["stop"] - 1000 : g["stop"]]) for g in sig.meta["segments"]]
    assert np.all(np.diff(cv) < 0), cv
