"""AM13 step 1 (varimu.magic.solo): an RC low-pass's sensitivity to R against the analytic
derivative; a first-order prediction on triode_stage."""

from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("circuitsim")

from varimu.circuit.ir import (  # noqa: E402
    IR_VERSION,
    Capacitor,
    CircuitIR,
    Resistor,
    Section,
    VoltageProbe,
)
from varimu.magic import render, solo  # noqa: E402

R_OHM, C_F = 1.0e3, 159.0e-9  # ~1 kHz


def _rc() -> CircuitIR:
    ir = CircuitIR(
        version=IR_VERSION,
        title="rc",
        input_node="in",
        probes=(VoltageProbe("o"),),
        models=(),
        sections=(
            Section("all", (Resistor("R1", "in", "o", R_OHM), Capacitor("C1", "o", "0", C_F))),
        ),
    )
    ir.validate()
    return ir


def test_rc_sensitivity_matches_the_analytic_derivative():
    fs = render.sample_rate()
    n = fs // 2
    t = np.arange(n) / fs
    # A periodic multisine (whole cycles in the window), so the FFT's derivative is exact.
    x = sum(0.1 * np.sin(2 * np.pi * k * 20 * t + k) for k in (5, 23, 50, 113, 251, 500))
    r = solo.sensitivity(_rc(), x, "R1", 1.0, 1.0, probe="o")
    w = 2 * np.pi * np.fft.rfftfreq(n, 1 / fs)
    a = 1j * w * R_OHM * C_F
    want = np.fft.irfft(np.fft.rfft(x) * (-a / (1 + a) ** 2), n)
    skip = int(0.02 * fs)  # the start's transient
    err = solo.level_db(r["s"][skip:] - want[skip:], want[skip:])
    assert err < -50.0, err
    assert not r["flag"]


def test_first_order_prediction_on_triode_stage():
    fs = render.sample_rate()
    t = np.arange(fs // 2) / fs
    x = 0.05 * np.sin(2 * np.pi * 440 * t)
    x[: int(0.02 * fs)] *= np.linspace(0, 1, int(0.02 * fs))
    ir, v_in, v_out = solo.build("triode_stage")
    r = solo.sensitivity(ir, x, "RK", v_in, v_out, probe="o")
    y0 = solo.run_ir(ir, x, v_in, v_out, probe="o")
    y5 = solo.run_ir(solo.perturbed(ir, "RK", 1.05), x, v_in, v_out, probe="o")
    pred = y0 + np.log(1.05) * r["s"]
    assert solo.level_db(y5 - pred, r["s"]) < -40.0
