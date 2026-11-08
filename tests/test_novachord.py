"""The Hammond Novachord (docs/NOVACHORD_PLAN.md): its tubes against their sheets, the generated
circuits current and sound, the note A's chain against the service manual (the idle point, the
dividers' division, the attack switch's envelopes) and the renderer's keys."""

from __future__ import annotations

import dataclasses
import importlib.util
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pytest

from varimu import preflight
from varimu.circuit import builder, spec
from varimu.circuit.ir import VoltageProbe
from varimu.config import CONFIG_DIR, REPO_ROOT
from varimu.devices.library import load_device

FS = 96000
NOTE = CONFIG_DIR / "circuits" / "novachord_note.yaml"


def _script(name):
    sp = importlib.util.spec_from_file_location(name, REPO_ROOT / "scripts" / f"{name}.py")
    m = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(m)
    return m


# --- the tubes ------------------------------------------------------------------------------


def test_6c8g_meets_its_class_a_point():
    """RCA 6C8-G: 250 V, -4.5 V: 3.2 mA, 1.6 mS, 22.5 kOhm (the fit weighs the curves too)."""
    t = load_device("6C8G@1")
    assert t.ip(-4.5, 250) == pytest.approx(3.2e-3, rel=0.03)
    assert t.gm(-4.5, 250) == pytest.approx(1.6e-3, rel=0.06)
    assert t.rp(-4.5, 250) == pytest.approx(22500, rel=0.1)


def test_6w7g_meets_its_sheet():
    """RCA 6W7-G: 250 / 100 / -3 V: 2 mA, 0.5 mA screen, 1.225 mS, 1.5 MOhm; ~10 uA at -7 V."""
    p = load_device("6W7G@1")
    m = p.model
    assert m.ip(-3, 100, 250) == pytest.approx(2.0e-3, rel=0.01)
    assert m.ig2(-3, 100) == pytest.approx(0.5e-3, rel=0.01)
    gm = (m.ip(-3 + 1e-3, 100, 250) - m.ip(-3 - 1e-3, 100, 250)) / 2e-3
    assert gm == pytest.approx(1.225e-3, rel=0.01)
    assert m.ip(-7, 100, 250) + m.ig2(-7, 100) == pytest.approx(10e-6, rel=0.05)


def test_2a3_and_6j5g_meet_their_sheets():
    a = load_device("2A3@1")
    assert a.ip(-45, 250) == pytest.approx(60e-3, rel=0.02)
    assert a.ip(-62, 300) == pytest.approx(40e-3, rel=0.02)  # push-pull, zero signal
    j = load_device("6J5G@1")
    assert j.ip(-8, 250) == pytest.approx(9e-3, rel=0.01)
    assert j.ip(0, 90) == pytest.approx(10e-3, rel=0.01)


# --- the circuits ---------------------------------------------------------------------------


def test_generated_files_are_current():
    assert _script("make_novachord").main.__module__  # importable
    import subprocess
    import sys

    r = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "make_novachord.py"), "--check"],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    assert r.returncode == 0, r.stdout + r.stderr


@pytest.mark.parametrize("name", ["novachord_note", "novachord"])
def test_circuits_pass_the_checks(name):
    s = spec.load_circuit(CONFIG_DIR / "circuits" / f"{name}.yaml")
    for sets in ({}, {"normal_vibrato": 1, "mellow": 1, "attack": 1, "res1": 2, "full": 0}):
        assert preflight.check_ir(builder.build_ir(s, spec.resolve(s, sets))) == []


def _render(sets, keys, dur_s, probes, quality="draft"):
    from varimu.sim import fast, io

    s = spec.load_circuit(NOTE)
    ir = builder.build_ir(s, spec.resolve(s, sets))
    ir = dataclasses.replace(ir, probes=tuple(VoltageProbe(p) for p in probes))
    st = dataclasses.replace(
        io.TransientSettings.from_sim_settings(engine="circuitsim", quality=quality),
        full_scale_volts_peak=1.0,
    )
    n = int(dur_s * FS)
    t = np.arange(n) / FS
    ctl = {k: np.zeros(n) for k, _ in s.cv_inputs}
    for k, (t_on, t_off) in keys.items():
        g = ((t >= t_on) & (t < t_off)).astype(float)
        ctl[f"k{k}"], ctl[f"s{k}"] = g, g
    v = fast.run_transient(ir, np.zeros(n), settings=st, controls=ctl).vectors
    return {p: np.asarray(v[f"v({p})"]) for p in probes}


def _freq(x, skip_s=0.1):
    y = x[int(skip_s * FS) :] - x[int(skip_s * FS) :].mean()
    i = np.flatnonzero((y[:-1] < 0) & (y[1:] >= 0))
    t = i + (-y[i]) / (y[i + 1] - y[i])
    return (len(t) - 1) / ((t[-1] - t[0]) / FS)


@pytest.fixture(scope="module")
def idle_chain():
    pytest.importorskip("circuitsim")
    probes = ["ao_top", "ad5_k", "ad4_k", "ad3_k", "ad2_k", "ad1_k", "ad3_p", "k41_k", "grp10"]
    return _render({}, {}, 0.45, probes)


def test_the_idle_point_follows_the_manual(idle_chain):
    """SM2 p.7: a divider's steady current about 0.2 mA through RN6 (1 MEG to -192 V; the
    cathode's: plate and screen), its plate below +270 V by its share through RN5 (Fig. 16);
    a control tube with its key up cut off (its cathode on the cut-off bus, its group's plate
    lead at B+)."""
    v = idle_chain
    run = slice(int(0.1 * FS), None)
    for ch in (5, 4, 3, 2):
        ik = (np.mean(v[f"ad{ch}_k"][run]) + 192.0) / 1e6
        assert ik == pytest.approx(0.2e-3, rel=0.15), ch
    assert 150.0 < np.mean(v["ad3_p"][run]) < 210.0
    assert np.mean(v["k41_k"]) == pytest.approx(7.65, abs=0.3)  # the notes 13-44 tap
    assert np.ptp(v["grp10"][int(0.1 * FS) :]) < 0.01


def test_the_oscillator_is_tuned_and_the_dividers_divide(idle_chain):
    """A6 at 1760 Hz (the trim's tuning, within a cent at draft quality's warping) and every
    divider at half its input: 880, 440, 220, 110, 55 Hz (SM2 Fig. 12)."""
    v = idle_chain
    f0 = _freq(v["ao_top"])
    assert abs(1200 * np.log2(f0 / 1760.0)) < 3.0
    for ch in (5, 4, 3, 2, 1):
        assert _freq(v[f"ad{ch}_k"], 0.2) == pytest.approx(f0 / 2 ** (6 - ch), rel=0.01), ch


def test_the_attack_switch_shapes_the_envelope():
    """SM2 pp.2, 8: position 1 percussive (starts loud, dies away), 4 organ-like (held), 7
    slow (builds up while the key is held); the key's release dies within ~0.2 s (CN7
    through RN10)."""
    pytest.importorskip("circuitsim")

    def env(att):
        out = _render({"attack": att}, {41: (0.1, 1.1)}, 1.35, ["out"])["out"]
        w = int(0.02 * FS)
        e = np.sqrt(np.convolve(out**2, np.ones(w) / w, "same"))
        return {t: float(e[int(t * FS)]) for t in (0.2, 0.5, 1.0, 1.3)}

    with ThreadPoolExecutor(3) as ex:
        e1, e4, e7 = ex.map(env, (1, 4, 7))
    assert e1[0.2] > 1.5 * e1[1.0]  # percussive
    assert e4[1.0] == pytest.approx(e4[0.2], rel=0.25)  # sustained
    assert e7[1.0] > 2.0 * e7[0.2]  # slow
    for e in (e1, e4, e7):
        assert e[1.3] < 0.1 * max(e[0.2], e[1.0])  # released


# --- the renderer -----------------------------------------------------------------------------


def test_the_renderer_keys_follow_notes_and_pedals():
    """Key 1 is F1 (MIDI 29); spring 1 lifts with the key or a pedal; the bass pedal only on
    the lower 36 keys; notes outside the keyboard fold in by octaves."""
    from varimu.rhodes import midi

    r = _script("novachord_render")
    ev = [
        midi.Event(0.0, "on", 29, 100),
        midi.Event(0.5, "pedal", value=1),
        midi.Event(1.0, "off", 29, 0),
        midi.Event(1.5, "on", 20, 100),  # G#0 -> G#1 (key 4)
        midi.Event(1.8, "pedal", value=0),
    ]
    st = r.key_states(ev, bass_cc=[(2.0, 127)])
    by_t = dict(st)
    assert by_t[0.0]["k1"] == 1 and by_t[0.0]["s1"] == 1
    assert by_t[1.0]["k1"] == 0 and by_t[1.0]["s1"] == 1  # held by the pedal
    assert by_t[0.5]["s72"] == 1 and by_t[0.5]["k72"] == 0
    assert by_t[1.5]["k4"] == 1
    assert by_t[1.8]["s36"] == 0 and by_t[1.8]["s4"] == 1
    assert by_t[2.0]["s36"] == 1 and by_t[2.0]["s37"] == 0
