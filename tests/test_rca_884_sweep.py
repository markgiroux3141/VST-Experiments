"""RCA's 884 sweep oscillator (config/circuits/rca_884_sweep.yaml; HYBRID_PHYSICS_PLAN.md H1):
it passes the pre-flight checks, oscillates in circuitsim, strikes near the sheet's control
characteristic and extinguishes near the drop, and keeps the charge-to-strike formula's pitch
less the reset's time (scripts/thyratron_study.py measures every range -> reports/hybrid/)."""

import dataclasses

import numpy as np
import pytest

from varimu import preflight
from varimu.circuit import builder, spec
from varimu.circuit.ir import VoltageProbe
from varimu.config import CONFIG_DIR

fast = pytest.importorskip("varimu.sim.fast")
from varimu.sim import io  # noqa: E402

CIRCUIT = CONFIG_DIR / "circuits" / "rca_884_sweep.yaml"


def test_preflight_passes_at_every_range():
    assert preflight.check_circuit(spec.load_circuit(CIRCUIT)) == []


def test_it_oscillates_at_the_charge_to_strike_pitch():
    s = spec.load_circuit(CIRCUIT)
    vals = spec.resolve(s, {"range": 5, "fine": 0.0})
    ir = builder.build_ir(s, vals)
    ir = dataclasses.replace(ir, probes=(VoltageProbe("out"), VoltageProbe("k")))
    rate = 8 * 96000
    st = dataclasses.replace(
        io.TransientSettings.from_sim_settings(engine="circuitsim", quality="production"),
        sample_rate=rate,
        oversample=1,
        full_scale_volts_peak=1.0,
        settle_s=0.0,
    )
    res = fast.run_transient(ir, np.zeros(int(0.12 * rate)), settings=st)
    vk = np.asarray(res.vectors["v(k)"])
    y = np.asarray(res.vectors["v(out)"]) - vk
    y, vk = y[len(y) // 2 :], vk[len(vk) // 2 :]  # the cathode's bias settles (R11 C11)
    lo, hi = y.min(), y.max()
    # strikes near the average control characteristic at the ~-5.8 V bias (~50 V; the grid
    # resistors' pre-conduction ion current fires it a few volts early), extinguishes
    # near the drop
    assert 40.0 < hi < 52.0, hi
    assert 10.0 < lo < 25.0, lo
    mid = 0.5 * (lo + hi)
    k = np.where((y[:-1] < mid) & (y[1:] >= mid))[0]
    f = rate / np.mean(np.diff(k))
    r = vals["r5_ohm"]
    b = vals["b_plus_v"] - np.median(vk)
    f_formula = 1.0 / (r * vals["c5_f"] * np.log((b - lo) / (b - hi)))
    # the formula leaves out the reset (discharge through R4 and the arc's tail,
    # deionization): measured 1943 Hz against 2127 Hz (2026-11-02)
    assert 0.85 * f_formula < f < f_formula, (f, f_formula)
