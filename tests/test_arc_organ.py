"""The Arc Organ (config/circuits/arc_organ.yaml; docs/INVENTED_LIVE_PLAN.md IL7): the factory
trim is current and holds across the compass, the key contact gates the tank (silent at rest
but for the arc's hiss, a short release), TUNE (the variometer) moves the pitch both ways.

The app's half (the keys setting the condenser in place, a key waiting for it) is
crates/varimu-app/tests/live.rs's the_arc_organ_switches_its_condensers_in_place."""

from __future__ import annotations

import dataclasses
import importlib.util
import math
import re
from pathlib import Path

import numpy as np
import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]


def _trim_module():
    path = ROOT / "scripts" / "arc_organ_trim.py"
    spec = importlib.util.spec_from_file_location("arc_organ_trim", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _trims() -> dict:
    return yaml.safe_load((ROOT / "config" / "arc_organ_trims.yaml").read_text(encoding="utf-8"))


def test_the_trim_is_current_and_the_app_has_it():
    """The trim's key matches the circuit file, the app's table is the trim's condensers, and
    the circuit rests on A4's (the app then knows which key the circuit holds)."""
    t = _trim_module()
    saved = _trims()
    assert saved["circuit_sha256_16"] == t.circuit_key(), "run scripts/arc_organ_trim.py --write"
    rust = (ROOT / "crates" / "varimu-app" / "src" / "arc_organ_trims.rs").read_text()
    table = [float(x) for x in re.findall(r"^\s+([0-9.]+e[-+][0-9]+),$", rust, re.M)]
    assert table == [k["key_f"] for k in saved["keys"]]
    assert f"ARC_ORGAN_FIRST_NOTE: u8 = {saved['keys'][0]['note']};" in rust
    a4 = next(k for k in saved["keys"] if k["note"] == 69)
    circuit = yaml.safe_load((ROOT / "config" / "circuits" / "arc_organ.yaml").read_text())
    assert float(circuit["values"]["key_f"]["value"]) == a4["key_f"]
    assert all(abs(k["cents"]) < 2.0 for k in saved["keys"])


def _run(values: dict, gate_s: tuple[float, float], seconds: float):
    pytest.importorskip("circuitsim", reason="needs `uv sync --extra fast`")
    from varimu.circuit import builder, spec
    from varimu.sim import fast, io

    sp = spec.load_circuit(spec.circuit_path("arc_organ"))
    ir = builder.build_ir(sp, spec.resolve(sp, values))
    st = io.TransientSettings.from_sim_settings(engine="circuitsim", quality="draft")
    st = dataclasses.replace(st, full_scale_volts_peak=1.0, settle_s=0.0)
    fs = st.sample_rate
    n = int(seconds * fs)
    gate = np.zeros(n)
    gate[int(gate_s[0] * fs) : int(gate_s[1] * fs)] = 10.0
    v = fast.run_transient(ir, np.zeros(n), settings=st, controls={"gate": gate}).vectors
    return fs, np.asarray(v["v(out)"])


def _rms_db(x: np.ndarray) -> float:
    return 20 * math.log10(math.sqrt(float(np.mean(x**2))) + 1e-12)


@pytest.mark.parametrize("note", [40, 69, 84])
def test_a_key_sings_its_note_on_its_trimmed_condenser(note: int):
    """E2, A4 and C6 at the panel's defaults, each on its condenser from the trim: in tune
    within 3 cents (the bass's pitch wanders with the hiss: measured over a second)."""
    t = _trim_module()
    key = next(k for k in _trims()["keys"] if k["note"] == note)
    fs, out = _run({"key_f": key["key_f"]}, (0.05, 1.55), 1.55)
    f = t.f0(out[-int(1.2 * fs) :], fs, (0.5 * key["hz"], 1.4 * key["hz"]))
    assert abs(1200 * math.log2(f / key["hz"])) < 3.0


def test_the_key_contact_gates_the_tank():
    """At rest the tank lies on the quench resistance: only the arc's hiss, ~20 dB under a note
    (the sketch's -22 dB); a key builds the note in ~50-70 ms (to -6 dB: the hiss seeds it, so
    it varies with where the key lands); let go, the dashpot opens the contact and within 60 ms
    only the hiss is left."""
    fs, out = _run({}, (0.3, 1.0), 1.3)
    idle = out[int(0.05 * fs) : int(0.28 * fs)]
    note = out[int(0.6 * fs) : int(1.0 * fs)]
    assert -26.0 < _rms_db(idle) - _rms_db(note) < -16.0
    built = out[int(0.4 * fs) : int(0.42 * fs)]
    assert _rms_db(built) - _rms_db(note) > -6.0
    after = out[int(1.06 * fs) : int(1.1 * fs)]
    assert _rms_db(after) < _rms_db(idle) + 3.0


def test_tune_moves_the_pitch_both_ways():
    """TUNE, the variometer's coupling: at 0.02 the tank is 3.26 mH (sharper), at 0.5 4.8 mH
    (flatter), more than a semitone each way from rest at A4."""
    t = _trim_module()
    a4 = next(k for k in _trims()["keys"] if k["note"] == 69)
    cents = []
    for k in (0.02, 0.5):
        fs, out = _run({"key_f": a4["key_f"], "tune": k}, (0.05, 1.05), 1.05)
        f = t.f0(out[-int(0.7 * fs) :], fs, (300.0, 600.0))
        cents.append(1200 * math.log2(f / 440.0))
    assert cents[0] > 120.0 and cents[1] < -120.0, cents
