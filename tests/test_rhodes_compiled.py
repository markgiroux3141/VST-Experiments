"""The harp compiled for circuitsim (docs/RHODES_PLAN.md, RH3): the component version is what
the code compiles, its data is pinned, and circuitsim's harp medium plays it as the Python
reference (varimu/rhodes/harp.py) does."""

from __future__ import annotations

import json

import numpy as np
import pytest

from varimu.devices import versions
from varimu.rhodes import compile as hc
from varimu.rhodes import harp, midi

circuitsim = pytest.importorskip("circuitsim")

FS = 48000.0


def _db(err: np.ndarray, ref: np.ndarray) -> float:
    return 20 * np.log10(np.sqrt(np.mean(err**2)) / np.sqrt(np.mean(ref**2)))


def test_the_saved_harp_is_what_the_code_compiles():
    have = versions.versions(hc.COMPONENT)
    assert have, "no MK1_HARP: run scripts/compile_rhodes_harp.py"
    saved = hc.load_data(f"{hc.COMPONENT}@{have[-1]}")
    assert hc._dump(saved) == hc._dump(hc.compile_harp()), (
        "the instrument, the key fits or the compiler changed: save the next version "
        "(scripts/compile_rhodes_harp.py) and move the circuits to it"
    )


def test_a_version_refuses_data_that_doesnt_match(tmp_path, monkeypatch):
    src = versions.COMPONENT_DIR
    folder = tmp_path / "mk1_harp"
    folder.mkdir()
    (folder / "1.yaml").write_bytes((src / "mk1_harp" / "1.yaml").read_bytes())
    (folder / "1.harp.json").write_text('{"tampered": true}\n', encoding="utf-8")
    (tmp_path / versions.LOCK_NAME).write_bytes((src / versions.LOCK_NAME).read_bytes())
    monkeypatch.setattr(versions, "COMPONENT_DIR", tmp_path)
    with pytest.raises(versions.VersionError, match="sha256"):
        hc.load_data("MK1_HARP@1")


def test_the_halved_modes_and_the_low_rank_arc_are_the_live_tier():
    """Per key, the compiled data's outputs equal the live tier's (`key._System`) for a
    struck tine (an impulse at the strike point): the tip exactly (the halved modes), the arc
    within its reduction once the tine rings (2 ms on; in the first millisecond the bell's
    modes carry it, up to 16% off at key 8, where the EMF's comparison below covers it)."""
    from varimu.rhodes import key as ky
    from varimu.rhodes import spec

    def c(d):
        return np.asarray(d["re"]) + 1j * np.asarray(d["im"])

    data = hc.compile_harp(keys=[20, 44, 68], workers=1)
    for kd in data["keys"]:
        s = ky._System(spec.key(kd["key"]), "modes")
        idx, _ = hc._halve(s.lam)
        f = kd["free"]
        p = c(f["arc"]).reshape(f["arc_rank"], f["modes"])
        for t in (2e-3, 2e-2, 0.2):
            z_full = s.b * 1e-3 * np.exp(s.lam * t)  # 1 mN s at the strike point
            z = z_full[idx]
            tip = np.real(c(f["tip"]) @ z)
            assert tip == pytest.approx(np.real(s.c_tip @ z_full), rel=1e-9, abs=1e-18)
            arc = 0.5 * np.sum(np.real(p @ z) ** 2)
            q = np.real(s.q_map @ z_full)
            assert arc == pytest.approx(0.5 * s.w @ (q * q), rel=5e-3)


def test_circuitsim_plays_the_harp_as_the_reference():
    """Strikes, a re-strike, the pedal and releases: the medium's internal EMF against
    harp.render's (the voices at 2x, the contact at 4x), within the arc's reduction."""
    keys = [20, 44, 56, 68]
    data = hc.compile_harp(keys=keys, workers=1)
    el = {"name": "VHARP", "out": "h", "rate_hz": 2 * FS, "contact_rate_hz": 4 * FS}
    el["model"] = data
    e = midi.Event
    events = [
        e(100 / FS, "on", 40, 100),
        e(2000 / FS, "on", 64, 70),
        e(2300 / FS, "pedal", value=1),
        e(5000 / FS, "off", 40),
        e(6000 / FS, "on", 76, 127),
        e(6500 / FS, "on", 76, 90),  # struck again, ringing
        e(9000 / FS, "off", 64),
        e(12000 / FS, "pedal", value=0),
        e(14000 / FS, "on", 88, 60),
        e(16000 / FS, "off", 88),
    ]
    n = 24000
    ref = harp.render(events, (n - 1) / FS, fs_hz=FS, oversample=2, step_oversample=4).raw_v
    ordered = sorted(events, key=lambda ev: (ev.t_s, ev.kind != "off"))
    notes = [(round(ev.t_s * FS), ev.kind, ev.note, ev.value) for ev in ordered]
    y, raw, (k, s) = circuitsim.harp_render(json.dumps(el), FS, n, notes)
    assert (k, s) == (2, 2)
    assert raw.size == ref.size
    assert _db(raw - ref, ref) < -110  # measured -128 dB (2026-11-04)
    # The step-rate output is the internal EMF decimated (sounding, the same level).
    assert np.max(np.abs(y)) == pytest.approx(np.max(np.abs(raw)), rel=0.2)


def test_the_stage_plays_notes_into_the_5e3_and_live_hears_the_terminals():
    """The circuit's harp played by notes (fast.run_transient's `notes`): the jack silent
    before the strike, sounding after; the live build (no speaker readout) puts the
    speaker's terminal voltage on `out`."""
    from varimu.circuit import builder, spec
    from varimu.sim import fast
    from varimu.sim.io import TransientSettings

    c = spec.load_circuit(spec.circuit_path("rhodes_stage_5e3"))
    ir = builder.build_ir(c, spec.resolve(c, {}), "linear", speaker_readout=False)
    s = TransientSettings.from_sim_settings(engine="circuitsim", quality="draft")
    notes = [(0.05, "on", 40, 110), (0.06, "on", 64, 90), (0.2, "off", 40, 0)]
    r = fast.run_transient(ir, np.zeros(int(0.3 * s.sample_rate)), settings=s, notes=notes)
    jack, out, spk = (r.vectors[f"v({n})"] for n in ("jack", "out", "spk"))
    before = int(0.049 * s.sample_rate)
    assert np.max(np.abs(jack[:before])) < 1e-6
    assert np.max(np.abs(jack[before:])) > 1e-3
    assert np.max(np.abs(out - spk)) < 1e-9 * np.max(np.abs(spk))
