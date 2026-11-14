"""AM2's checks on a small circuit (ANALOG_MAGIC_FABLE.md AM2 "Tests"): two noise-free passes
are bit-identical; two passes with different noise seeds differ by the stage's own output
noise (independent additive noise: sqrt(2) x the noise on silence), within 1 dB.

The tone is small (0.01, the stage linear). Measured 2026-11-13 at 0.1 (2.7 V rms out): the
residual is +8.2 dB over the floor at production tolerances (a numerical part ~103 dB under
the output: the noise moves the error-controlled steps) and +0.1 dB at tolerances 100x
tighter (the stage's own noise ~3 dB lower under a big swing: its incremental gain falls)."""

from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("circuitsim")

from varimu.magic import null, render  # noqa: E402

PROBE = ("o",)  # triode_stage's output node


def _x(fs: int, seconds: float = 1.0, amp: float = 0.01) -> np.ndarray:
    t = np.arange(int(seconds * fs)) / fs
    x = amp * np.sin(2 * np.pi * 440 * t)
    f = int(0.02 * fs)
    x[:f] *= np.linspace(0, 1, f)
    return x


def _run(x, **kw) -> np.ndarray:
    return render.through("triode_stage", x, probes=PROBE, cache=False, **kw)["o"]


def test_p0_noise_off_is_bit_identical():
    fs = render.sample_rate()
    x = _x(fs)
    a, b = _run(x, noise=False), _run(x, noise=False)
    assert null.null_report(a, b, fs)["identical"]


def test_p2_residual_is_the_stages_own_noise():
    fs = render.sample_rate()
    x = _x(fs)
    a, b = _run(x, noise=1), _run(x, noise=2)
    floor = _run(np.zeros_like(x), noise=1)
    skip = int(0.1 * fs)
    res = null.audio_band(a - b, fs)[skip:-skip]
    fl = null.audio_band(floor, fs)[skip:-skip]
    assert np.std(res) > 0
    got = 20 * np.log10(np.std(res) / np.std(fl))
    assert abs(got - 10 * np.log10(2)) < 1.0, got
