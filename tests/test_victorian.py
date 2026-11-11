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


def test_carbon_button_law():
    """The carbon's conductance follows the force's power law above its softened corner, is
    its loose grains' at no force, and is smooth (its derivative matches a difference)."""
    from varimu.devices.library import load_device

    c = load_device("CARBON_BUTTON@1")
    g, _ = c.g(np.array([0.25, 0.5, 1.0]))
    assert g[2] / g[1] == pytest.approx(2.0, rel=1e-3)  # exponent 1
    assert g[1] == pytest.approx(c.g_open_s + c.g0_s, rel=1e-6)
    g0, _ = c.g(-1.0)
    assert float(g0) == pytest.approx(c.g_open_s, rel=1e-6)
    for f in (-0.02, 0.0, 0.01, 0.3):
        (gp, _), (gm, _), (_, dg) = c.g(f + 1e-7), c.g(f - 1e-7), c.g(f)
        assert float(dg) == pytest.approx(float(gp - gm) / 2e-7, rel=1e-4, abs=1e-9)


def test_voice_is_generated():
    """config/circuits/victorian_voice.yaml is what scripts/make_victorian_voice.py writes."""
    import subprocess
    import sys

    r = subprocess.run(
        [sys.executable, "scripts/make_victorian_voice.py", "--check"],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stdout + r.stderr


@pytest.fixture(scope="module")
def voice_runs():
    """The voice at draft quality (JA cores): idle, and one key at CUTOFF 0 and 1."""
    pytest.importorskip("circuitsim")
    from varimu.circuit import builder
    from varimu.circuit.spec import circuit_path, load_circuit
    from varimu.sim import fast
    from varimu.sim.io import TransientSettings

    spec = load_circuit(circuit_path("victorian_voice"))
    s = TransientSettings.from_sim_settings(engine="circuitsim", quality="draft")
    s = dataclasses.replace(s, cores="ja")
    out = {}
    for name, cutoff, notes in (
        ("idle", None, []),
        ("cut0", 0.0, [(0.05, "on", 57, 100)]),
        ("cut1", 1.0, [(0.05, "on", 57, 100)]),
    ):
        ov = None if cutoff is None else {"cutoff": cutoff}
        ir = builder.build(spec, ov, cores="ja").ir
        r = fast.run_transient(ir, np.zeros(int(0.6 * 96000)), settings=s, notes=notes)
        out[name] = {k: np.asarray(v) for k, v in r.vectors.items()}
    return out


def test_voice_idles_on_its_cells(voice_runs):
    """With no key down nothing draws: the line sits at four cells' EMF, the local battery at
    two's (Carhart's cell, 1.58 V), the output silent."""
    r = voice_runs["idle"]
    assert np.mean(r["v(line)"]) == pytest.approx(4 * 1.5772, abs=0.01)
    assert np.mean(r["v(loc)"]) == pytest.approx(2 * 1.5772, abs=0.01)
    assert np.max(np.abs(r["v(out)"])) < 1e-7


def _harmonics_db(x, f0, n=6):
    sp = np.abs(np.fft.rfft(x * np.hanning(len(x))))
    fr = np.fft.rfftfreq(len(x), 1 / 96000)
    lv = [
        20 * np.log10(sp[np.argmin(np.abs(fr - k * f0)) - 3 :][:7].max()) for k in range(1, n + 1)
    ]
    return np.array(lv) - lv[0]


def test_voice_sounds_and_cutoff_acts(voice_runs):
    """A key sounds through the relay (the button's force swings, the cone speaks), the line
    sags under it, the fundamental is the strongest partial (the closed coil and the cone:
    the bass the receivers lost), and CUTOFF opens the filter: A3's 4th-6th harmonics rise
    (scripts/victorian_voice_study.py: 4-10 dB from 0 to 1)."""
    seg = slice(int(0.3 * 96000), None)
    a, b = voice_runs["cut0"], voice_runs["cut1"]
    assert np.std(a["v(fx)"][seg]) > 1e-4  # the button's force moves
    assert np.mean(a["v(line)"][seg]) < 4 * 1.5772 - 0.1  # the line sags
    assert np.std(a["v(out)"][seg]) > 1e-4
    ha, hb = _harmonics_db(a["v(out)"][seg], 220.0), _harmonics_db(b["v(out)"][seg], 220.0)
    assert np.all(ha[1:] < 0) and np.all(hb[1:] < 0)
    assert np.all(hb[3:6] - ha[3:6] > 3.0)


def test_field_starts_fresh(voice_runs):
    """The cone's field winding starts on its rested battery: ~0.41 A, the force factor's
    nominal (PARCHMENT_CONE's 0.4 A); 16 cells behind 16 ohm into 44.4 ohm."""
    r = voice_runs["idle"]
    i_f = np.mean(r["v(out_fs)"]) / 44.39293225373085
    assert i_f == pytest.approx(16 * 1.5772 / (16 * 1.0 + 44.39293225373085), rel=0.02)
