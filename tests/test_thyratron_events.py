"""Technique K's Python reference (varimu.devices.thyratron_events; HYBRID_PHYSICS_PLAN.md
H3b): the band-limiting kernel, the step charges, the crossing prediction, the tables'
interpolation and the emulator on a synthetic table. The method against the unit's
reference is scripts/thyratron_kernels.py (reports/hybrid/k_unit_fine.json)."""

import numpy as np
import pytest

from varimu.config import REPO_ROOT
from varimu.devices import thyratron_events as te


def test_the_kernel_is_minimum_phase_and_meets_its_band():
    h = te.minphase_lowpass()
    assert h.sum() == pytest.approx(1.0, abs=1e-12)
    f = np.fft.rfftfreq(1 << 16, 1 / te.REF_OVERSAMPLE)  # in units of fs
    db = 20 * np.log10(np.abs(np.fft.rfft(h, 1 << 16)) + 1e-300)
    assert np.max(np.abs(db[f <= 0.25])) < 1e-3
    assert np.max(db[f >= 0.75]) < -100.0
    # causal with its energy first: at every length at least the linear-phase filter's
    n = len(h)
    lin = np.sinc(np.arange(n) - (n - 1) / 2)  # same length, centred (any symmetric one)
    e_min = np.cumsum(h**2) / np.sum(h**2)
    e_lin = np.cumsum(lin**2) / np.sum(lin**2)
    assert np.all(e_min[: n // 2] >= e_lin[: n // 2] - 1e-12)


def test_step_charges_keep_the_charge_and_shift_with_the_phase():
    rng = np.random.default_rng([3, 1])
    pulse = np.abs(rng.normal(size=200)) * 1e-2
    h = te.minphase_lowpass()
    q = te.step_charges(pulse, h)
    total = pulse.sum() / te.REF_RATE
    assert q.shape[0] == te.PHASES + 1
    assert np.allclose(q.sum(axis=1), total, rtol=1e-12)
    # a whole step later is phase 0 one step on
    assert np.allclose(q[te.PHASES, 1:], q[0, :-1], atol=1e-18)
    # raw (no filter): the pulse's own charge per step
    raw = te.step_charges(pulse, np.ones(1))
    assert np.allclose(raw[0, : len(pulse) // te.REF_OVERSAMPLE],
                       pulse[: len(pulse) // te.REF_OVERSAMPLE * te.REF_OVERSAMPLE]
                       .reshape(-1, te.REF_OVERSAMPLE).sum(axis=1) / te.REF_RATE)  # fmt: skip


@pytest.mark.parametrize("x0", [0.05, 0.3, 0.77, 1.0])
def test_a_crossing_is_found_where_the_quadratic_crosses(x0):
    # m(x) = (x - x0) (x + 4) / 4: negative at -2, -1, 0, zero at x0 in the next step
    m = lambda x: (x - x0) * (x + 4.0) / 4.0  # noqa: E731
    assert te.predict_crossing((m(-2), m(-1), m(0))) == pytest.approx(x0, abs=1e-12)


def test_no_crossing_or_one_already_past():
    assert te.predict_crossing((-3.0, -2.5, -2.0)) is None  # reaches 0 in 4 steps
    assert te.predict_crossing((-1.0, -2.0, -3.0)) is None  # falling
    assert te.predict_crossing((-2.0, -1.0, 0.5)) == 0.0  # missed: at once


def _tables(dv=40.0, c=5e-9, v_s=50.0):
    """A synthetic unit: every strike at v_s takes C dv (a pulse of one reference sample)."""
    unit = te.Unit(c_f=c)
    pulse = np.array([c * dv * te.REF_RATE])
    return te.Tables(unit, np.array([-7.0, -5.0]), np.log([1e3, 1e6]), np.full((2, 2), v_s),
                     np.full((2, 2), 30e-6), np.zeros((2, 2), bool),
                     [[pulse, pulse], [pulse, pulse]], [[0 * pulse] * 2] * 2, {})  # fmt: skip


def test_the_tables_interpolate_and_clamp():
    t = _tables()
    lk = te.lookup(t, te.REF_OVERSAMPLE, -6.0, 3e4)
    assert lk.v_s == pytest.approx(50.0, rel=1e-14) and lk.dead_s == pytest.approx(30e-6, rel=1e-14)
    assert lk.q.sum(axis=1) == pytest.approx(np.full(te.PHASES + 1, 5e-9 * 40.0), rel=1e-12)
    assert te.lookup(t, te.REF_OVERSAMPLE, -20.0, 1e9).v_s == pytest.approx(50.0, rel=1e-14)


def test_latched_corners_drop_out_or_latch():
    """Corners that latch carry no event: below half the weight the others' are renormalized
    (the charge stays whole), from half on the condition latches."""
    t = _tables()
    t.latched[1, 1] = True
    t.pulses[1][1] = np.zeros(0)
    t.grid_pulses = [list(r) for r in t.grid_pulses]
    t.grid_pulses[1][1] = np.zeros(0)
    t.dead_s[1, 1] = 0.0
    lk = te.lookup(t, te.REF_OVERSAMPLE, -6.0, 3e4)  # a quarter on the latched corner
    assert not lk.latched and lk.dead_s == pytest.approx(30e-6, rel=1e-14)
    assert lk.q.sum(axis=1) == pytest.approx(np.full(te.PHASES + 1, 5e-9 * 40.0), rel=1e-12)
    assert te.lookup(t, te.REF_OVERSAMPLE, -5.2, 5e5).latched


def test_the_emulator_runs_the_sawtooth_at_its_period():
    """Charged at S from ~0 the synthetic unit strikes at 50 V and drops 40 V: f = S / 40 V
    (the ramp's curvature from the 10 kV source is ~0.5%: within a few cents)."""
    s = 0.05e6
    em = te.Emulator(_tables(), -6.0, s)
    v = em.run(int(0.2 * te.FS))
    y = v[int(0.05 * te.FS) :]
    mid = 30.0
    k = np.where((y[:-1] < mid) & (y[1:] >= mid))[0]
    t = k + (mid - y[k]) / (y[k + 1] - y[k])
    f = te.FS / np.mean(np.diff(t))
    v = te.V_CHARGE
    exact = s / ((v - te.V_SLOPE_REF) * np.log((v - 10.0) / (v - 50.0)))
    assert 1200 * np.log2(f / exact) == pytest.approx(0.0, abs=0.5)
    assert em.late == 0 and em.events > 100


def test_the_rust_fixtures_are_current():
    """crates/circuitsim/tests/events.rs reads them (scripts/export_circuit_fixtures.py)."""
    path = REPO_ROOT / "crates/circuitsim/tests/fixtures/events/events.json"
    assert path.read_text("utf-8") == te.events_fixtures_json(), (
        "stale: run scripts/export_circuit_fixtures.py"
    )


def test_the_element_round_trips_and_validates():
    import dataclasses

    from varimu.circuit.ir import CircuitIR, IRError, Resistor, Section

    el = te.element_fixture(te._fixture_tables())
    ir = CircuitIR(
        "k",
        "in",
        (),
        (),
        (Section("s", (el, Resistor("R1", "in", "a", 1e3), Resistor("R2", "k", "0", 1.0))),),
    )
    assert CircuitIR.from_json(ir.to_json()) == ir
    bad = dataclasses.replace(el, v_g_v=tuple(reversed(el.v_g_v)))
    with pytest.raises(IRError, match="ascending"):
        CircuitIR("k", "in", (), (), (Section("s", (bad, Resistor("R2", "k", "0", 1.0))),))
    rows = [list(r) for r in el.pulses_a]
    rows[0][0] = ()
    with pytest.raises(IRError, match="pulse"):
        CircuitIR("k", "in", (), (), (Section("s", (dataclasses.replace(
            el, pulses_a=tuple(tuple(r) for r in rows)),)),))  # fmt: skip
