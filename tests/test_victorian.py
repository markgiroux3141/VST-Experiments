"""The Victorian synth (docs/VICTORIAN_SYNTH_PLAN.md): the reed key's reference
(varimu/victorian/reed.py) and circuitsim's reeds medium against it."""

from __future__ import annotations

import dataclasses
import math

import numpy as np
import pytest

from varimu.victorian import compile as vcompile
from varimu.victorian import reed


@pytest.fixture(scope="module")
def cfg():
    return reed.load_cfg()


def test_compiled_keyboard_is_current(cfg):
    """GRAY_REEDS's latest version is what the design and the code give now (rerun
    scripts/compile_victorian_reeds.py)."""
    import json

    have = vcompile.latest()
    assert have is not None
    assert vcompile.load(have) == json.loads(vcompile.dump(vcompile.keyboard(cfg)))


@pytest.mark.parametrize("note", [36, 60, 84])
def test_tuned_reed_speaks_its_note(cfg, note):
    """Filed in place, a reed maintained on the nominal local battery speaks its note."""
    tune = vcompile.tuning(cfg)
    p = vcompile.key_params(cfg, note, tune[note])
    o = reed.run(p, max(0.6, 25.0 / p.f_hz + 0.35), 2.8, 6.0, [(0.0, "on", 100)], probes=True)
    f = reed.pitch_hz(o["x"])
    assert abs(1200 * math.log2(f / vcompile.note_hz(cfg, note))) < 2.0


def test_velocity_shapes_the_line_not_the_reed(cfg):
    """The carbon is in the line only: velocity scales the line's current, the reed's swing
    and pitch stay."""
    p = vcompile.key_params(cfg, 57)
    out = {}
    for vel in (30, 120):
        o = reed.run(p, 0.5, 2.8, 6.0, [(0.0, "on", vel)], probes=True)
        x = np.array(o["x"][-20000:])
        out[vel] = (np.ptp(x), reed.pitch_hz(o["x"]), np.std(o["i_line"][-20000:]))
    assert out[30][0] == pytest.approx(out[120][0], rel=1e-3)
    assert out[30][1] == pytest.approx(out[120][1], rel=1e-4)
    assert 3.0 < out[120][2] / out[30][2] < 5.0


def test_medium_matches_the_reference():
    """circuitsim's reeds medium on ideal batteries gives the reference's currents a sample
    late (its output a sample after its push), equal up to rounding: both circuits' outputs, a
    key struck, pressed harder and released (times exact in binary; a note at t = 0 would land
    a sample late, at the first push)."""
    from varimu.circuit import builder
    from varimu.circuit.spec import circuit_path, load_circuit
    from varimu.sim import fast
    from varimu.sim.io import TransientSettings

    pytest.importorskip("circuitsim")
    spec = load_circuit(circuit_path("reeds_test"))
    ir = builder.build(spec).ir
    s = TransientSettings.from_sim_settings(engine="circuitsim")
    s = dataclasses.replace(s, oversample=1, settle_s=0.0)
    n = int(0.25 * 96000)
    notes = [(0.03125, "on", 60, 90), (0.0625, "pressure", 0, 127), (0.15625, "off", 60, 0)]
    res = fast.run_transient(ir, np.zeros(n), settings=s, notes=notes)
    data = vcompile.load(str(spec.values["reeds_model"]["value"]))
    p = vcompile.from_data(data["keys"][60 - data["keys"][0]["note"]])
    events = [(0.03125, "on", 90), (0.0625, "pressure", 127), (0.15625, "off", 0)]
    ref = reed.run(p, n / 96000, 2.8, 6.0, events)
    # The other keys sleep; their unloaded carbon leaks through the closed line contacts.
    leak = (len(data["keys"]) - 1) * 6.0 * p.g_open_s
    for probe, key, add in (("v(ol)", "i_loc", 0.0), ("v(ok)", "i_line", leak)):
        got = np.asarray(res.vectors[probe])[1:]
        want = np.asarray(ref[key])[: len(got)] + add
        err = np.max(np.abs(got - want)) / np.max(np.abs(want))
        assert err < 1e-9, (probe, err)
