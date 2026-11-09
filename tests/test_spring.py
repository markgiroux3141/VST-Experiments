"""The spring reverb tank (docs/REVERB_PLAN.md, E1-E3): its component, the Python
reference's modes against Parker & Bilbao's closed forms, its response's echoes, and
circuitsim's springs (the IR's Spring element, coupled one way at its ports) agreeing with
the reference."""

from __future__ import annotations

import dataclasses
import math

import numpy as np
import pytest

from varimu.circuit import parts
from varimu.circuit.ir import (
    IR_VERSION,
    CircuitIR,
    IRError,
    Resistor,
    Section,
    Spring,
    VoltageProbe,
)
from varimu.devices import spring as sp
from varimu.devices.library import load_spring_tank

circuitsim = pytest.importorskip("circuitsim")

E, RHO = 2e11, 7800.0
# Parker & Bilbao, DAFx-09, Table 2: the Leem KA-1210's spring 3.
LEEM3 = sp.Spring(0.35e-3, 4.6e-3, 351, 0.163)


def tank() -> sp.SpringTankComponent:
    return load_spring_tank("ACC4AB3C1B@1")


def test_the_component_reads_and_its_decay_meets_its_class() -> None:
    c = tank()
    assert len(c.springs) == 2
    table = dict(sp.decay_table(c.t60_500hz_s, c.loss_factor))
    # The part code's long decay (2.75-4.0 s), at 500 Hz exactly the class's middle.
    assert sp.SIX_LN10 / table[500.0] == pytest.approx(3.4, rel=1e-12)
    assert 2.75 <= sp.SIX_LN10 / table[100.0] <= 4.5
    # The steel's loss shortens the top: under 2 s at 4 kHz.
    assert sp.SIX_LN10 / table[4000.0] < 2.0
    # The transducers: the output's EMF per velocity the input's force per ampere times
    # sqrt(L_out / L_in); the springs' load on the input coil is milliohms.
    assert c.output_v_per_m_s == pytest.approx(
        c.input_force_per_a * math.sqrt(c.output_le_h / c.input_le_h), rel=1e-12
    )
    r_mot = c.input_force_per_a**2 / sp.characteristic_impedance_ns_per_m(c)
    assert 1e-4 < r_mot < 1e-2


def test_the_branch_follows_the_closed_forms() -> None:
    r, big_r, length = (
        0.5 * LEEM3.wire_diameter_m,
        0.5 * LEEM3.helix_diameter_m,
        LEEM3.wire_length_m(),
    )
    c2, k = E / RHO, 2.0 / LEEM3.helix_diameter_m
    beta = np.linspace(1e-4 * k, k, 200_001)
    om, a2 = sp.branch(c2, r, k, beta)
    # F_C, the dispersion's peak below beta = k, within 1% of the first-order formula.
    assert om.max() / (2 * math.pi) == pytest.approx(sp.transition_hz(r, big_r, E, RHO), rel=0.01)
    # The low end's speed is nu_0 (their appendix B, before its approximation), so the
    # echoes come T_D apart.
    v0 = math.sqrt(c2) * r / (big_r * math.sqrt(4 + r * r / (big_r * big_r)))
    assert om[1] / beta[1] == pytest.approx(v0, rel=1e-6)
    assert 2 * length / v0 == pytest.approx(sp.delay_s(r, big_r, length, E, RHO), rel=1e-3)
    # The audio branch is the lower eigenvalue of the curved rod's 2 x 2 problem.
    for b in (0.1 * k, 0.5 * k, 0.9 * k, 1.3 * k):
        g = r * r / 4
        m = c2 * np.array([[b * b, k * b], [k * b, g * (k * k - b * b) ** 2 + k * k]])
        w, v = np.linalg.eigh(m)
        o, a = sp.branch(c2, r, k, np.array([b]))
        assert o[0] ** 2 == pytest.approx(w[0], rel=1e-9)
        assert a[0] == pytest.approx(v[0, 0] ** 2, rel=1e-9)


def test_the_response_echoes_at_t_d() -> None:
    """The low band's envelope repeats at T_D (the round trip). Its first arrival is the
    branch just above beta = k, whose slope there is sqrt(2) nu_0: at T_D / (2 sqrt 2)."""
    r, big_r, length = (
        0.5 * LEEM3.wire_diameter_m,
        0.5 * LEEM3.helix_diameter_m,
        LEEM3.wire_length_m(),
    )
    spec = sp.SpringSpec(RHO, E, ((r, big_r, length),), 6000.0, sp.decay_table(3.4, 2e-4), 40.0)
    fs = 16000.0
    h = sp.impulse_response(spec, fs)
    from scipy.signal import butter, sosfilt

    env = np.abs(sosfilt(butter(4, [100, 800], btype="band", fs=fs, output="sos"), h[: int(fs)]))
    td = sp.delay_s(r, big_r, length, E, RHO)
    lo = int(0.01 * fs)
    ac = np.correlate(env - env.mean(), env - env.mean(), "full")[len(env) - 1 :]
    assert (lo + np.argmax(ac[lo : int(0.2 * fs)])) / fs == pytest.approx(td, rel=0.03)
    onset = np.argmax(env > 0.2 * env.max()) / fs
    assert onset == pytest.approx(td / (2 * math.sqrt(2)), rel=0.05)


def divider_with_springs(p: Spring) -> CircuitIR:
    """The input across a divider (in -- 100 -- s -- 100 -- 0), the springs sensing s, their
    EMF on e into 1k + 1k (out between them)."""
    els = (
        Resistor("R1", "in", "s", 100.0),
        Resistor("R2", "s", "0", 100.0),
        p,
        Resistor("RO", "e", "o", 1e3),
        Resistor("RL", "o", "0", 1e3),
    )
    ir = CircuitIR(
        version=IR_VERSION,
        title="spring",
        input_node="in",
        probes=(VoltageProbe("o"),),
        models=(),
        sections=(Section("tank", els),),
    )
    ir.validate()
    return ir


def small_springs(force_per_v: float = 2.0, out: float = 0.3) -> Spring:
    r, big_r, length = 0.175e-3, 2.3e-3, LEEM3.wire_length_m()
    return Spring(
        name="VSP", sense_pos="s", sense_neg="0", force_per_v=force_per_v, out="e",
        out_per_m_s=out, density_kg_m3=RHO, youngs_pa=E,
        springs=((r, big_r, length), (r, 2.2e-3, 4.19)), f_max_hz=2500.0,
        decay=((100.0, 8.0), (1000.0, 12.0)), tail_db=40.0, saturation_v=0.0,
    )  # fmt: skip


def test_circuitsim_agrees_with_the_reference() -> None:
    """The output in a circuit equals the reference's response convolved with the force,
    one sample later; the IR round-trips through JSON."""
    fs = 8000.0
    p = small_springs()
    ir = divider_with_springs(p)
    assert CircuitIR.from_json(ir.to_json()) == ir
    assert circuitsim.ir_roundtrip(ir.to_json()) is not None
    n = 3000
    t = np.arange(n) / fs
    x = np.sin(2 * np.pi * 220 * t) * np.exp(-30 * t)
    x[3] += 1.0
    out = circuitsim.simulate(ir.to_json(), x, 1.0 / fs, "esdirk4", input_order=1)
    got = np.asarray(out["v(o)"])
    h = sp.impulse_response(sp.SpringSpec.of(p), fs)
    force = p.force_per_v * 0.5 * x
    want = 0.5 * p.out_per_m_s * np.convolve(force, h)[:n]
    assert np.abs(want).max() > 1e-6
    err = np.abs(got - want).max() / np.abs(want).max()
    assert err < 1e-8, err


def test_the_part_and_its_validation() -> None:
    c = tank()
    els = parts.spring_tank("SP", "ti", "0", "to", c)
    names = [e.name for e in els]
    assert names == ["LSP_in", "RSP_mot", "RSP_in", "VSP", "LSP_out", "RSP_out"]
    s = els[3]
    assert isinstance(s, Spring)
    assert s.force_per_v == pytest.approx(c.input_force_per_a / c.input_re_ohm)
    assert s.springs[0][2] == c.springs[0].wire_length_m()
    with pytest.raises(IRError, match="springs"):
        divider_with_springs(dataclasses.replace(small_springs(), springs=((3e-3, 2e-3, 4.0),)))
    with pytest.raises(IRError, match="ground or the input"):
        divider_with_springs(dataclasses.replace(small_springs(), out="0"))


def test_a_split_tank_puts_every_second_spring_on_out_r() -> None:
    """STEREO (docs/REVERB_PLAN.md, "Stereo"): the springs on two output coils, the input
    coil and its load as the whole tank's; the halves' responses sum to the whole tank's."""
    c = tank()
    whole = parts.spring_tank("SP", "ti", "0", "to", c)
    split = parts.spring_tank("SP", "ti", "0", "to", c, out_r="to_r")
    assert [e.name for e in split] == [e.name for e in whole] + ["VSP_R", "LSP_out2", "RSP_out2"]
    assert split[:3] == whole[:3]  # the input coil and the springs' load
    left, right = split[3], split[6]
    assert isinstance(left, Spring) and isinstance(right, Spring)
    assert left.springs == whole[3].springs[0::2] and right.springs == whole[3].springs[1::2]
    assert (left.sense_pos, left.sense_neg) == (right.sense_pos, right.sense_neg)
    assert split[-1].b == "to_r"
    spec = sp.spec_of(c, 4000.0)
    fs = 12000.0
    h = sp.impulse_response(spec, fs)
    h0 = sp.impulse_response(dataclasses.replace(spec, springs=spec.springs[0::2]), fs)
    h1 = sp.impulse_response(dataclasses.replace(spec, springs=spec.springs[1::2]), fs)
    n = min(len(h), len(h0), len(h1))
    assert np.max(np.abs(h0[:n] + h1[:n] - h[:n])) < 1e-12 * np.max(np.abs(h))
    with pytest.raises(ValueError, match="one spring"):
        parts.spring_tank(
            "SP", "ti", "0", "to", dataclasses.replace(c, springs=c.springs[:1]), "to_r"
        )
