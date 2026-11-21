"""The 200A's reeds compiled for circuitsim (docs/WURLITZER_PLAN.md, WZ4): the component
version is what the code compiles, its data is pinned, and circuitsim's reeds medium plays it
as the Python reference (varimu/wurlitzer/keyboard.py) does."""

from __future__ import annotations

import json

import numpy as np
import pytest

from varimu.devices import versions
from varimu.rhodes import midi
from varimu.wurlitzer import compile as wc
from varimu.wurlitzer import keyboard as kb

circuitsim = pytest.importorskip("circuitsim")

FS = 48000.0
KEYS = [5, 30, 61]  # a bass reed, a middle one (both damped) and an undamped treble one


def _db(err: np.ndarray, ref: np.ndarray) -> float:
    return 20 * np.log10(np.sqrt(np.mean(err**2)) / np.sqrt(np.mean(ref**2)))


@pytest.fixture(scope="module")
def data():
    return wc.compile_reeds(keys=KEYS)


def _element(data: dict) -> dict:
    return {
        "name": "VREEDS",
        "out": "rd",
        "plate": "pk",
        "rate_hz": 2 * FS,
        "contact_rate_hz": 4 * FS,
        "model": data,
    }


def test_the_saved_reeds_are_what_the_code_compiles():
    have = versions.versions(wc.COMPONENT)
    assert have, "no WURLI_REEDS: run scripts/compile_wurlitzer_reeds.py"
    saved = wc.load_data(f"{wc.COMPONENT}@{have[-1]}")
    assert wc._dump(saved) == wc._dump(wc.compile_reeds()), (
        "the instrument, the field maps or the compiler changed: save the next version "
        "(scripts/compile_wurlitzer_reeds.py) and move the circuits to it"
    )


def test_a_version_refuses_data_that_doesnt_match(tmp_path, monkeypatch):
    src = versions.COMPONENT_DIR
    folder = tmp_path / "wurli_reeds"
    folder.mkdir()
    (folder / "1.yaml").write_bytes((src / "wurli_reeds" / "1.yaml").read_bytes())
    (folder / "1.reeds.json").write_text('{"tampered": true}\n', encoding="utf-8")
    (tmp_path / versions.LOCK_NAME).write_bytes((src / versions.LOCK_NAME).read_bytes())
    monkeypatch.setattr(versions, "COMPONENT_DIR", tmp_path)
    with pytest.raises(versions.VersionError, match="sha256"):
        wc.load_data("WURLI_REEDS@1")


def test_circuitsim_plays_the_reeds_as_the_reference(data):
    """Strikes, a re-strike of a ringing reed, the pedal, releases and an undamped key: the
    medium's internal dC against keyboard.render's (the voices at 2x, the contact at 4x)."""
    e = midi.Event
    notes = [k + kb.MIDI_KEY_OFFSET for k in KEYS]
    events = [
        e(100 / FS, "on", notes[0], 100),
        e(2000 / FS, "on", notes[1], 70),
        e(2300 / FS, "pedal", value=1),
        e(5000 / FS, "off", notes[0]),
        e(6000 / FS, "on", notes[2], 127),
        e(6500 / FS, "on", notes[2], 90),  # struck again, ringing
        e(9000 / FS, "off", notes[1]),
        e(12000 / FS, "pedal", value=0),
        e(14000 / FS, "on", notes[0], 40),  # the bass again, under the damper's ring-down
        e(14100 / FS, "on", notes[0], 127),  # and again, 2 ms later
        e(18000 / FS, "off", notes[0]),
        e(19000 / FS, "off", notes[2]),
    ]
    n = 30000
    ref = kb.render(events, (n - 1) / FS, fs_hz=FS, oversample=2, step_oversample=4).raw_f
    ordered = sorted(events, key=lambda ev: (ev.t_s, ev.kind != "off"))
    ev = [(round(x.t_s * FS), x.kind, x.note, x.value) for x in ordered]
    el = json.dumps(_element(data))
    y, raw, (k, s) = circuitsim.wurli_render(el, FS, n, ev, workers=0)
    assert (k, s) == (2, 2)
    assert raw.size == ref.size
    assert _db(raw - ref, ref) < -130  # measured -149 dB (2026-11-20)
    # The same on worker threads, bit for bit.
    _, raw3, _ = circuitsim.wurli_render(el, FS, n, ev, workers=3)
    np.testing.assert_array_equal(raw3, raw)
    # The step-rate output is the internal dC decimated (sounding, the same level).
    assert np.max(np.abs(y)) == pytest.approx(np.max(np.abs(raw)), rel=0.2)
