"""The Wurlitzer 200A played live (docs/WURLITZER_PLAN.md, WZ4): config/circuits/
wurlitzer_200a_live.yaml (scripts/make_wurlitzer_200a_live.py) with the reeds as circuitsim's
medium plays the notes as WZ3's path does (varimu/wurlitzer/keyboard.py into the stock
circuit's input), AUX doesn't hear the power amplifier, SPEAKERS reads the terminals."""

from __future__ import annotations

import dataclasses
import importlib.util

import numpy as np
import pytest

from varimu.circuit import builder, spec
from varimu.circuit.ir import VoltageProbe, WurliReeds
from varimu.config import REPO_ROOT
from varimu.preflight import check_circuit
from varimu.rhodes import midi
from varimu.wurlitzer import circuit as wcirc
from varimu.wurlitzer import compile as wc
from varimu.wurlitzer import keyboard as kb

LIVE = "wurlitzer_200a_live"
DUR_S = 0.35
NOTES = [(0.05, "on", n, v) for n, v in ((45, 110), (57, 100), (64, 90), (69, 120))] + [
    (0.2, "on", 81, 127),
    (0.25, "off", 45, 0),
]


def _db(err: np.ndarray, ref: np.ndarray) -> float:
    return float(20 * np.log10(np.sqrt(np.mean(err**2)) / np.sqrt(np.mean(ref**2))))


def _script():
    path = REPO_ROOT / "scripts" / "make_wurlitzer_200a_live.py"
    sp_ = importlib.util.spec_from_file_location("make_wurlitzer_200a_live", path)
    mod = importlib.util.module_from_spec(sp_)
    sp_.loader.exec_module(mod)
    return mod


def test_the_live_file_is_generated():
    m = _script()
    assert m.OUT.read_text(encoding="utf-8").replace("\r\n", "\n") == m.derive(), (
        "stale: run scripts/make_wurlitzer_200a_live.py"
    )


@pytest.mark.parametrize("speakers", [0, 1])
def test_the_live_circuit_passes_the_checks(speakers):
    c = spec.load_circuit(spec.circuit_path(LIVE))
    assert check_circuit(c, {"speakers": speakers}) == []


def test_the_part_carries_the_reeds_standing_capacitance():
    c = spec.load_circuit(spec.circuit_path(LIVE))
    ir = builder.build_ir(c, spec.resolve(c, {}))
    (el,) = [e for e in ir.elements() if isinstance(e, WurliReeds)]
    (cap,) = [e for e in ir.elements() if e.name == "CREEDS" and e.a == el.out]
    assert cap.b == el.plate == "pk"
    assert cap.c_f == el.model["standing_f"]
    # the stock file's stand-in has the same capacitance (the field maps' sum)
    assert cap.c_f == pytest.approx(wcirc.c_reeds_f(), rel=1e-3)
    assert el.model == wc.load_data("WURLI_REEDS@2")


circuitsim = pytest.importorskip("circuitsim")


@pytest.fixture(scope="module")
def runs():
    from varimu.sim import fast

    st = wcirc.settings("production")
    fs = st.sample_rate
    events = [midi.Event(t, k, n, v) for t, k, n, v in NOTES]
    kr = kb.render(events, DUR_S, fs_hz=fs)
    # WZ3's stand-in (the plate at its idle V0 in the product), then the exact current with
    # the stand-in run's own plate voltage, -V(t) dC / C_r (one fixed-point pass)
    first = wcirc.render(wcirc.plate_input_v(kr.dc_f), quality="production", probes=("out", "pk"))
    x = -first["pk"][: kr.dc_f.size] * kr.dc_f / wcirc.c_reeds_f()
    ref = {"stand-in": first["out"], "exact": wcirc.render(x, quality="production")["out"]}
    c = spec.load_circuit(spec.circuit_path(LIVE))
    out = {}
    for speakers, probes in ((0, ("out", "aux")), (1, ("out", "aux", "spk"))):
        ir = builder.build_ir(c, spec.resolve(c, {"speakers": speakers}))
        ir = dataclasses.replace(ir, probes=tuple(VoltageProbe(p) for p in probes))
        r = fast.run_transient(ir, np.zeros(kr.dc_f.size), settings=st, notes=NOTES)
        out[speakers] = {p: np.asarray(r.vectors[f"v({p})"]) for p in probes}
    return fs, ref, out


def test_the_live_circuit_plays_the_reeds_as_the_reference(runs):
    """The medium senses the plate (a step late) and pushes -d((C_r + dC) V)/dt into it; the
    reference, the keyboard's dC into the stock circuit's input driven with the plate's own
    voltage, -V(t) dC / C_r: -73 dB (2026-11-20; at production the medium steps at the 192 kHz
    step itself, no decimation). WZ3's stand-in (V held at its idle 150 V) is -60 dB from it:
    the plate swings ~0.2% on a chord."""
    fs, ref, out = runs
    # the reference's input ends in resample_poly's edge transient: its last 2 ms left out
    seg = slice(int(0.06 * fs), ref["exact"].size - int(0.002 * fs))
    exact, live = ref["exact"][seg], out[0]["aux"][seg]
    assert np.max(np.abs(exact)) > 0.1  # it sounds (volts at the AUX jack)
    assert _db(live - exact, exact) < -65
    assert -66 < _db(live - ref["stand-in"][seg], exact) < -50


def test_aux_doesnt_hear_the_power_amplifier(runs):
    """With SPEAKERS the power amplifier is built; with AUX it isn't (its input network
    stays as the volume wiper's load): the AUX jack moves by -55 dB rms, +0.009 dB in level
    (measured 2026-11-20 on a louder chord at volume 1; -81 dB on this one)."""
    fs, _, out = runs
    a, b = out[0]["aux"], out[1]["aux"]
    seg = slice(int(0.06 * fs), a.size)
    assert _db(a[seg] - b[seg], b[seg]) < -45
    np.testing.assert_array_equal(out[0]["out"], out[0]["aux"] * 1.0)  # AUX reads the jack


def test_speakers_reads_the_terminals(runs):
    _, _, out = runs
    o = out[1]
    assert np.max(np.abs(o["spk"])) > 1.0  # the power amplifier sounds (volts)
    assert np.max(np.abs(o["out"] - o["spk"] * 0.3)) < 1e-6 * np.max(np.abs(o["spk"]))
