"""The plate reverb's plate (docs/REVERB_PLAN.md, E6 / E2): its component, the decay its
damper sets, the Python reference's modes and response, and circuitsim's plate (the IR's
Plate element, coupled one way at its ports) agreeing with the reference."""

from __future__ import annotations

import dataclasses
import math

import numpy as np
import pytest

from varimu.circuit.ir import (
    IR_VERSION,
    CircuitIR,
    Plate,
    Resistor,
    Section,
    VoltageProbe,
)
from varimu.devices import plate as plt
from varimu.devices.library import load_plate

circuitsim = pytest.importorskip("circuitsim")


def emt140() -> plt.PlateComponent:
    return load_plate("EMT140@1")


def test_the_component_reads_and_its_damper_spans_the_brochure() -> None:
    c = emt140()
    lo, hi = c.t500_range()
    # The 1 s, 2 s and 4,5 s curves read about 0.9, 1.9 and 4.8 s at 500 Hz.
    assert 0.85 < lo < 1.0 and 4.6 < hi < 5.0
    # At a curve's own decay, the table is that curve.
    i = c.decay_f_hz.index(500.0)
    for curve in c.decay_curves_s:
        table = plt.decay_table(c, curve[i])
        for (f, s), t in zip(table, curve, strict=True):
            assert s == pytest.approx(plt.SIX_LN10 / t, rel=1e-12), f
    # Between curves: 500 Hz lands on the setting; outside the range, clamped.
    for t500 in (1.5, 2.5, 3.5):
        table = dict(plt.decay_table(c, t500))
        assert plt.SIX_LN10 / table[500.0] == pytest.approx(t500, rel=1e-12)
    assert plt.decay_table(c, 0.1) == plt.decay_table(c, lo)
    assert plt.decay_table(c, 99.0) == plt.decay_table(c, hi)


def test_modes_follow_the_closed_form_and_the_modal_density() -> None:
    c = emt140()
    spec = plt.PlateSpec(
        c.lx_m, c.ly_m, c.thickness_m, c.density_kg_m3, c.youngs_pa, c.poisson,
        c.tension_n_m, c.drive_xy, c.pickup_xy, c.f_max_hz,
        plt.decay_table(c, 2.5), c.tail_db,
    )  # fmt: skip
    omega, s, w = plt.modes(spec, 20_000.0)
    kappa2, tension = plt.stiffness(spec)
    b = (math.pi / c.lx_m) ** 2 + (math.pi / c.ly_m) ** 2
    assert omega.min() == pytest.approx(math.sqrt(tension * b + kappa2 * b * b), rel=1e-12)
    # S / (2 kappa) modes per Hz (Russo 2021, Fig 5.3: about 1.3 for the EMT 140).
    per_hz = c.lx_m * c.ly_m / (2.0 * math.sqrt(kappa2))
    assert per_hz == pytest.approx(1.31, abs=0.02)
    assert len(omega) == pytest.approx(20_000.0 * per_hz, rel=0.05)
    # Each mode decays at half the energy rate at its frequency.
    i = int(np.argmin(np.abs(omega / (2 * math.pi) - 500.0)))
    f_i = omega[i : i + 1] / (2 * math.pi)
    assert s[i] == pytest.approx(0.5 * plt.energy_decay(spec.decay, f_i)[0])


def divider_with_plate(p: Plate) -> CircuitIR:
    """The input across a divider (in -- 100 -- s -- 100 -- 0), the plate sensing s, its
    pickup p into 1k + 1k (out between them)."""
    els = (
        Resistor("R1", "in", "s", 100.0),
        Resistor("R2", "s", "0", 100.0),
        p,
        Resistor("RO", "p", "o", 1e3),
        Resistor("RL", "o", "0", 1e3),
    )
    ir = CircuitIR(
        version=IR_VERSION,
        title="plate",
        input_node="in",
        probes=(VoltageProbe("o"),),
        models=(),
        sections=(Section("plate", els),),
    )
    ir.validate()
    return ir


def small_plate(force_per_v: float = 2.0, out: float = 1e-3) -> Plate:
    return Plate(
        name="VPL", sense_pos="s", sense_neg="0", force_per_v=force_per_v, out="p",
        out_per_m_s2=out, lx_m=2.0, ly_m=1.0, thickness_m=0.5e-3, density_kg_m3=7872.0,
        youngs_pa=2e11, poisson=0.3, tension_n_m=600.0, drive_xy=(0.52, 0.53),
        pickup_xy=(0.47, 0.62), f_max_hz=1500.0,
        decay=((100.0, 8.0), (1000.0, 12.0)), tail_db=40.0,
    )  # fmt: skip


def test_circuitsim_agrees_with_the_reference() -> None:
    """The pickup in a circuit equals the reference's response convolved with the force,
    one sample later; the IR round-trips through JSON."""
    fs = 8000.0
    p = small_plate()
    ir = divider_with_plate(p)
    assert CircuitIR.from_json(ir.to_json()) == ir
    assert circuitsim.ir_roundtrip(ir.to_json()) is not None
    n = 3000
    t = np.arange(n) / fs
    x = np.sin(2 * np.pi * 220 * t) * np.exp(-30 * t)
    x[3] += 1.0
    out = circuitsim.simulate(ir.to_json(), x, 1.0 / fs, "esdirk4", input_order=1)
    got = np.asarray(out["v(o)"])
    h = plt.impulse_response(plt.PlateSpec.of(p), fs)
    force = p.force_per_v * 0.5 * x
    want = 0.5 * p.out_per_m_s2 * np.convolve(force, h)[:n]
    assert np.abs(want).max() > 1e-6
    assert np.max(np.abs(got - want)) < 1e-8 * np.abs(want).max()


def test_the_reference_response_decays_at_its_table() -> None:
    """An octave band of the response decays at the table's rate there: the T60 of the
    band's envelope (a causal band-pass, its -5 to -35 dB) matches 6 ln 10 / sigma_E
    within 10%."""
    from scipy.signal import butter, sosfilt

    p = dataclasses.replace(small_plate(), tail_db=90.0)
    fs = 8000.0
    h = plt.impulse_response(plt.PlateSpec.of(p), fs)
    y = sosfilt(butter(4, [354.0, 707.0], btype="band", fs=fs, output="sos"), h)
    w = int(0.02 * fs)
    env = np.array([np.sqrt(np.mean(y[i : i + w] ** 2)) for i in range(0, len(y) - w, w)])
    level = 20 * np.log10(env + 1e-30)
    tt = np.arange(len(level)) * 0.02
    top = int(np.argmax(level))
    sel = (np.arange(len(level)) > top) & (level < level[top] - 5) & (level > level[top] - 35)
    slope = np.polyfit(tt[sel], level[sel], 1)[0]
    sigma_e = plt.energy_decay(p.decay, np.array([500.0]))[0]
    assert -60 / slope == pytest.approx(plt.SIX_LN10 / sigma_e, rel=0.1)
