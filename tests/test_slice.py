"""The coupled 670 slice in ngspice: stable at idle, gain reduction rising with level.

These run real transients (about 20-40 s in total at ~50x real time).
"""

import numpy as np
import pytest

from varimu.circuit import netlist as nl
from varimu.measure import metrics
from varimu.measure.signals import stepped_sine
from varimu.sim import ngspice
from varimu.sim.io import TransientSettings, run_transient

try:
    ngspice.find_ngspice()
except ngspice.SimulatorNotFound:
    pytest.skip("ngspice not available", allow_module_level=True)

# Most sensitive front panel so a short signal shows strong compression.
HOT = {"input_atten_db": 0.0, "ac_threshold": 1.0, "time_constant": 1}


def _run(x_dbfs, overrides, save=("v(out)", "v(cv)", "v(ga)", "v(gb)")):
    s = TransientSettings.from_sim_settings()
    c = nl.build(overrides)
    return run_transient(
        c.text,
        x_dbfs * s.full_scale_volts_peak,
        input_node=c.input_node,
        save=list(save),
        settings=s,
        files=c.files,
    ), s


def test_idle_circuit_is_quiet_and_sits_at_its_operating_point():
    """No input: no parasitic oscillation, CV stays at ZERO * bias rail.

    A lossless transformer model made the 6386 stage oscillate at ~30 kHz and
    pump the CV through grid current; this guards against that coming back.
    """
    r, s = _run(np.zeros(int(0.03 * 96000)), HOT)
    out = r.vectors["v(out)"] / s.full_scale_volts_peak
    assert np.max(np.abs(out)) < 1e-4  # below -80 dBFS
    cv = r.vectors["v(cv)"]
    assert np.ptp(cv) < 1e-3
    zero_v = nl.resolve(HOT)["zero"] * nl.resolve(HOT)["bias_v"]
    assert cv.mean() == pytest.approx(zero_v, abs=0.6)  # bias rail sags a little under load
    np.testing.assert_allclose(r.vectors["v(ga)"], cv, atol=1e-3)


def test_gain_reduction_increases_with_input_level():
    sig = stepped_sine(
        freq_hz=1000, start_dbfs=-30, stop_dbfs=0, step_db=10, hold_s=0.06, sample_rate=96000
    )
    r, s = _run(sig.samples, HOT)
    y = r.vectors["v(out)"] / s.full_scale_volts_peak
    pts = metrics.segment_gains(sig.samples, y, sig.meta["segments"])
    gains = np.array([g for _, g in pts])
    gr = gains[0] - gains
    assert np.all(np.diff(gr) > 0.5), gr  # strictly more reduction at every step
    assert gr[-1] > 10, gr  # 0 dBFS at the most sensitive setting compresses hard
    # The control voltage is what does it: more negative at every step.
    cv = [np.median(r.vectors["v(cv)"][g["stop"] - 1000 : g["stop"]]) for g in sig.meta["segments"]]
    assert np.all(np.diff(cv) < 0), cv
