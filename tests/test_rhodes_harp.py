"""The Rhodes, RH2 (varimu/rhodes/harp.py, midi.py; scripts/derive_rhodes_5e3.py): the
harp's wiring, a voice over events, MIDI files, the Stage into the 5E3."""

from __future__ import annotations

import subprocess
import sys

import numpy as np
import pytest

from varimu.rhodes import harp, midi
from varimu.rhodes import spec as rspec


def test_wiring_groups():
    # the manual's Fig. 10-4: pickups 1-4 (keys 8-11) a group of four, then threes
    sizes = [harp.group_size(n) for n in rspec.KEYS_73]
    assert sizes[:4] == [4] * 4 and set(sizes[4:]) == {3}
    assert 1 + (len(sizes) - 4) // 3 == 24  # 24 groups in series
    with pytest.raises(ValueError):
        harp.group_size(7)


def test_midi_round_trip(tmp_path):
    ev = [
        midi.Event(0.0, "on", 60, 90),
        midi.Event(0.5, "pedal", value=1),
        midi.Event(1.0, "off", 60),
        midi.Event(1.25, "pedal", value=0),
    ]
    path = tmp_path / "t.mid"
    midi.write(path, ev)
    back = midi.read(path)
    assert [(e.kind, e.note, e.value) for e in back] == [(e.kind, e.note, e.value) for e in ev]
    assert [e.t_s for e in back] == pytest.approx([e.t_s for e in ev], abs=2e-3)


class _LinearFlux:
    y_range_m = (-1.0, 1.0)
    dg_m = np.array([0.0, 1.0])

    def __call__(self, y, dg, dy=0, ddg=0):
        return np.ones_like(y) if dy == 1 else np.zeros_like(y)


def _voice(n=49, seconds=1.0):
    k = rspec.key(n)
    out = np.zeros(int(seconds * 96000 * 4) + 1)
    return harp.Voice(k, _LinearFlux(), out, 96000.0), out


def test_voice_matches_a_strike():
    # struck from rest and left alone, a voice is key.strike's live tier
    from varimu.rhodes import key as ky

    v, out = _voice(seconds=0.5)
    v.strike(0, 1.0, out.size)
    v.advance_to(out.size)
    s = ky.strike(v.k, 1.0, duration_s=0.5, flux=_LinearFlux(), oversample=4)
    from scipy import signal

    emf = signal.resample_poly(out, 1, 4)[: s.emf_v.size]
    err = np.sqrt(np.mean((emf - s.emf_v) ** 2) / np.mean(s.emf_v**2))
    assert err < 1e-6


def test_damper_stops_the_note():
    v, out = _voice(seconds=1.0)
    v.strike(0, 1.0, out.size)
    n_off = int(0.2 * 96000 * 4)
    v.damper(n_off, on=True)
    v.advance_to(out.size)
    held = np.max(np.abs(out[n_off - 20000 : n_off]))
    late = np.max(np.abs(out[n_off + int(0.3 * 96000 * 4) :]))
    # 0.3 s after the release: well past the felt's 0.15 s T60
    assert late < 1e-3 * held


def test_strike_again_while_ringing():
    v, out = _voice(seconds=0.6)
    v.strike(0, 1.0, out.size)
    v.strike(int(0.3 * 96000 * 4), 1.0, out.size)
    v.advance_to(out.size)
    assert len(v.contacts) == 2
    assert np.all(np.isfinite(out))


def test_derived_circuit_is_current():
    r = subprocess.run(
        [sys.executable, "scripts/derive_rhodes_5e3.py", "--check"], capture_output=True, text=True
    )
    assert r.returncode == 0, r.stdout + r.stderr


def test_stage_into_5e3_builds():
    from varimu.circuit import builder, spec

    c = spec.load_circuit(spec.circuit_path("rhodes_stage_5e3"))
    ir = builder.build(c, {}).ir
    names = {e.name for e in ir.elements()}
    assert {"VHARP", "RHARP_coils", "LHARP_coils", "CBASS", "RBASS", "CCABLE"} <= names
    assert any(n.startswith("RSVOL") for n in names)  # the volume pot's two halves
