"""AM0's toolkit (ANALOG_MAGIC_FABLE.md): the cached render, the null report's stages."""

from __future__ import annotations

import numpy as np
import pytest
from scipy.signal import lfilter

from varimu.magic import null

FS = 96000


def _program(seconds: float = 3.0, seed: int = 1) -> np.ndarray:
    """Band-limited noise with a slow envelope, a music-like stand-in."""
    rng = np.random.default_rng(seed)
    n = int(seconds * FS)
    x = rng.standard_normal(n)
    b, a = [0.05], [1, -0.95]
    x = lfilter(b, a, x)  # pinkish
    env = 0.5 + 0.5 * np.sin(2 * np.pi * 1.3 * np.arange(n) / FS) ** 2
    x = x * env
    return x / np.std(x) * 0.1


def test_align_recovers_a_fractional_delay():
    x = _program(1.0)
    y = null.frac_delay(x, 3.3)
    _, _, d = null.align(x, y, FS, 0.01)
    assert abs(d - 3.3) < 0.02


def test_null_of_a_half_gain_copy():
    a = _program()
    r = null.null_report(a, 0.5 * a, FS, dewarp_stage=False)
    assert abs(r["raw"] - (-6.02)) < 0.1
    assert r["gain"] < -200


def test_null_of_a_filtered_copy():
    a = _program()
    b = lfilter([0.3], [1, -0.7], a)  # a one-pole low-pass
    r = null.null_report(a, b, FS, dewarp_stage=False)
    assert r["gain"] > -20
    assert r["filter"] < -60


def test_dewarp_removes_a_wobbling_delay():
    t = np.arange(int(4.0 * FS)) / FS
    rng = np.random.default_rng(3)
    # A 4 kHz-centred program: noise band-passed, so the time base matters.
    from scipy.signal import butter, sosfilt

    a = sosfilt(butter(4, [2000, 6000], "bandpass", fs=FS, output="sos"),
                rng.standard_normal(len(t)))
    a /= np.std(a)
    d = 30e-6 * np.sin(2 * np.pi * 5 * t)  # 30 us peak, 5 Hz
    up = 8
    from scipy.signal import resample_poly

    au = resample_poly(a, up, 1)
    b = np.interp((t - d) * FS * up, np.arange(len(au)), au)
    r = null.null_report(a, b, FS)
    assert r["filter"] > -30
    assert r["dewarped"] < r["filter"] - 25


def test_through_matches_the_hand_written_pattern_and_caches():
    pytest.importorskip("circuitsim")
    from varimu.circuit import builder, spec
    from varimu.magic import render
    from varimu.sim import fast
    from varimu.sim.io import TransientSettings, full_scale

    st = TransientSettings.from_sim_settings(engine="circuitsim", quality="draft")
    x = 0.1 * np.sin(2 * np.pi * 440 * np.arange(int(0.05 * st.sample_rate)) / st.sample_rate)
    c = spec.load_circuit(spec.circuit_path("triode_stage"))
    v_in, v_out = full_scale(st, c)
    ir = builder.build(c, {}, triode_formulation=st.triode_formulation, cores=st.cores).ir
    ref = np.asarray(fast.run_transient(ir, x * v_in, settings=st).vectors["v(o)"]) / v_out
    y = render.through("triode_stage", x, quality="draft", probes=("o",))["o"]
    assert np.array_equal(y, ref)
    files = sorted(render.CACHE.glob("*.npz"), key=lambda p: p.stat().st_mtime)
    mtime = files[-1].stat().st_mtime
    y2 = render.through("triode_stage", x, quality="draft", probes=("o",))["o"]
    assert np.array_equal(y2, y)
    assert files[-1].stat().st_mtime == mtime
