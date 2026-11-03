"""Technique K in the circuit (HYBRID_PHYSICS_PLAN.md H3c): config/circuits/thyratron_unit.yaml
built with events (the 884 as its event kernels from config/events/884_unit_c6.json), the
builder's refusals, the pre-flight checks, and circuitsim's K against the Python reference
(thyratron_events.Emulator) on the unit. The unit against its 3 MHz reference is
scripts/thyratron_kernels.py (reports/hybrid/k_unit_fine.json)."""

import dataclasses

import numpy as np
import pytest

from varimu.circuit import builder, spec
from varimu.circuit.ir import Device, ThyratronEvents
from varimu.config import CONFIG_DIR, ConfigError
from varimu.devices import thyratron_events as te
from varimu.preflight import check_ir

UNIT = CONFIG_DIR / "circuits" / "thyratron_unit.yaml"
TABLES = CONFIG_DIR / "events" / "884_unit_c6.json"
pytestmark = pytest.mark.skipif(
    not TABLES.exists(),
    reason="no tables: scripts/thyratron_kernels.py --write 884_unit_c6",
)


def _ir(events=True, **overrides):
    c = spec.load_circuit(UNIT)
    return builder.build_ir(c, spec.resolve(c, overrides), events=events)


def test_an_events_build_puts_the_kernels_in_the_tubes_place():
    ir = _ir()
    (el,) = [e for e in ir.elements() if e.name == "XV1"]
    assert isinstance(el, ThyratronEvents)
    assert (el.a, el.g, el.w, el.k) == ("a", "g", "w", "0")
    assert not ir.models  # the thyratron's model left with its device
    t = te.Tables.load(TABLES)
    want = te.element(t, "XV1", "a", "g", "w", "0", source=te.source_label("884_unit_c6", t))
    assert el == want
    # without events the tube itself
    plain = _ir(events=False)
    assert isinstance(next(e for e in plain.elements() if e.name == "XV1"), Device)
    assert check_ir(ir) == []
    # SPICE has only the off tube: its capacitances, the grid's leakage, w held to k
    text = builder.build(spec.load_circuit(UNIT), cores="linear", events=True).text
    assert "RXV1_w w 0 1" in text and "CXV1_ga g a" in text and "RXV1_leak g a" in text


def test_an_events_build_refuses_what_it_cant_play(tmp_path):
    c = spec.load_circuit(UNIT)
    p = spec.resolve(c)
    no_tables = dataclasses.replace(c, devices={"V1": {"device": "884@1"}})
    with pytest.raises(ConfigError, match="needs its `events` tables"):
        builder.build_ir(no_tables, p, events=True)
    missing = dataclasses.replace(c, devices={"V1": {"device": "884@1", "events": "nope"}})
    with pytest.raises(ConfigError, match="no tables"):
        builder.build_ir(missing, p, events=True)
    builder.build_ir(missing, p)  # a build without events doesn't read them


def test_tables_for_another_version_are_refused(monkeypatch):
    t = te.Tables.load(TABLES)
    other = dataclasses.replace(t, unit=dataclasses.replace(t.unit, device="884@9"))
    monkeypatch.setattr(te.Tables, "load", classmethod(lambda cls, path: other))
    with pytest.raises(ConfigError, match="are for 884@9"):
        _ir()


@pytest.mark.parametrize("bias, r_ch", [(-6.0, 66.67e6), (-5.0, 13.0e6)])
def test_circuitsim_plays_the_unit_as_the_python_reference(bias, r_ch):
    """At the draft (96 kHz): circuitsim's K and the Emulator (the ramp exact) within
    0.5 cents, no strike missed."""
    import circuitsim  # noqa: F401  (the fast extra)

    from varimu.sim import fast, io

    st = dataclasses.replace(
        io.TransientSettings.from_sim_settings(engine="circuitsim", quality="draft"),
        full_scale_volts_peak=1.0,
        settle_s=0.0,
    )
    ir = _ir(bias_v=bias, r_charge_ohm=r_ch)
    stats: dict = {}
    n = int(0.2 * te.FS)
    out = fast.run_transient(ir, np.zeros(n), settings=st, stats=stats).vectors["v(out)"]
    t = te.Tables.load(TABLES)
    slope = (t.unit.v_charge_v - te.V_SLOPE_REF) / (r_ch * t.unit.c_f)
    em = te.Emulator(t, bias, slope)
    ref = em.run(n)

    def pitch(y):
        y = y[int(0.05 * te.FS) :]
        mid = 0.5 * (y.max() + y.min())
        k = np.where((y[:-1] < mid) & (y[1:] >= mid))[0]
        tt = k + (mid - y[k]) / (y[k + 1] - y[k])
        return te.FS / np.mean(np.diff(tt))

    assert 1200 * np.log2(pitch(out) / pitch(ref)) == pytest.approx(0.0, abs=0.5)
    assert stats["events"] == pytest.approx(em.events, abs=1)
    assert stats["late_events"] <= 1 and stats["latched_events"] == 0


def test_an_events_build_plays_the_island_at_the_sample_rate():
    """saw_884 renders its oscillator as an island (M1); with events, K is in it and the
    section is an ordinary one (H4)."""
    c = spec.load_circuit(CONFIG_DIR / "circuits" / "saw_884.yaml")
    p = spec.resolve(c)
    m1 = {s.title: s for s in builder.build_ir(c, p).sections}["oscillator"]
    assert (m1.substeps, m1.decimate, m1.owns) == (16, "fir", ("kf",))
    k = {s.title: s for s in builder.build_ir(c, p, events=True).sections}["oscillator"]
    assert (k.substeps, k.decimate, k.owns) == (None, None, None)
    assert any(isinstance(e, ThyratronEvents) for e in k.elements)
