"""The Clavinet's live tier in Python (docs/CLAVINET_PLAN.md, CL3): `varimu.clavinet.live` on
the compiled strings plays a key as `note.play` does (the reference, at the same band), and
key pressure bends a held note's pitch by the key's bend table."""

from __future__ import annotations

import numpy as np
import pytest

from varimu.clavinet import compile as cc
from varimu.clavinet import live, note

KEYS = (1, 36, 60)
FS = 96000.0
#: The production tier's extras the live tier leaves out (CL4): the keybed's knock, the
#: tension modulation.
OFF = {"knock": False, "tension_mod": False}


def _db(err: np.ndarray, ref: np.ndarray) -> float:
    return float(20 * np.log10(np.sqrt(np.mean(err**2)) / np.sqrt(np.mean(ref**2))))


@pytest.fixture(scope="module")
def compiled():
    return cc.from_compiled(cc.compile_strings(keys=list(KEYS), workers=1))


@pytest.mark.parametrize("n", KEYS)
def test_the_twin_plays_a_key_as_note_play_does(compiled, n):
    """The strike, the hold, the release's contacts and the tail, against note.play with
    the live band's basis, the production tier's knock and tension modulation off (CL4)."""
    header, arrays = compiled
    for vel in (1.0, 4.0):
        out = live.play_note(header, arrays, n, vel, 0.2, 0.2)
        ref = note.play(
            n, vel, 0.2, tail_s=0.2, oversample=1, f_cut_hz=cc.LIVE_BAND_HZ, **OFF
        )
        for j, w in enumerate(note.PICKUPS):
            r = ref.emf_v[w]
            m = min(out.shape[1], r.size)
            assert abs(out.shape[1] - r.size) <= 1
            assert _db(out[j, :m] - r[:m], r[:m]) < -110, (n, vel, w)


def _pitch_hz(x: np.ndarray, f0: float) -> float:
    """The strongest component near f0 (a zero-padded, windowed FFT, the peak's parabola)."""
    nfft = 1 << 22
    spec = np.abs(np.fft.rfft(x * np.hanning(x.size), nfft))
    f = np.fft.rfftfreq(nfft, 1 / FS)
    band = (f > 0.9 * f0) & (f < 1.1 * f0)
    i = np.flatnonzero(band)[np.argmax(spec[band])]
    a, b, c = np.log(spec[i - 1 : i + 2])
    return float(f[i] + 0.5 * (a - c) / (a - 2 * b + c) * (f[1] - f[0]))


def test_pressure_bends_a_held_note(compiled):
    header, arrays = compiled
    n = 36
    kd = next(k for k in header["keys"] if k["key"] == n)
    f0 = kd["note_hz"]
    hz = {}
    for p in (0, 127):
        s = live.Strings(header, arrays, FS)
        events = [(0, ("on", kd["note"], 100))]
        if p:
            events.append((int(0.05 * FS), ("pressure", p)))
        y = s.render(int(0.6 * FS), events)
        hz[p] = _pitch_hz(y[0, int(0.1 * FS) :], f0)
    cents = 1200 * np.log2(hz[127] / hz[0])
    table = kd["bend"]["cents"][-1] - kd["bend"]["cents"][0]
    # in tune unpressed (the polarizations' two modes, ~0.4 Hz apart at E4, beat: the
    # peak of a 0.5 s window sits within a few cents of them)
    assert abs(1200 * np.log2(hz[0] / f0)) < 8
    assert table > 5, "the bend table gives an audible bend"
    assert abs(cents - table) < 0.05 * table + 0.5, (cents, table)
