"""The grouping measures (varimu/separation/grouping.py) on signals whose answer is known."""

import numpy as np
import pytest

from varimu.separation import grouping as g

FS = 96000
DUR_S = 4.0
T = np.arange(int(DUR_S * FS)) / FS


def harm(rng, f0, n=10):
    return sum(
        np.sin(2 * np.pi * k * f0 * T + rng.uniform(0, 2 * np.pi)) / k for k in range(1, n + 1)
    )


def smooth_am(rng, rate_hz):
    e = rng.standard_normal(int(DUR_S * rate_hz * 4) + 2)
    return 1 + 0.8 * np.tanh(np.interp(T, np.linspace(0, DUR_S, len(e)), e))


def gated(x, offset_s):
    return x * (((T - offset_s) % 0.5 < 0.3) & (T > offset_s))


def test_common_modulation_raises_coherence():
    rng = np.random.default_rng(0)
    t, m = 0.1 * harm(rng, 200), 0.1 * harm(rng, 250)
    a, b = smooth_am(rng, 4), smooth_am(rng, 4)
    indep = g.temporal_coherence(t * a, m * b, FS)["cross"]
    common = g.temporal_coherence(t * a, m * a, FS)["cross"]
    assert abs(indep) < 0.3
    assert common > 0.8
    # Steady tones have no envelope to share.
    assert abs(g.temporal_coherence(t, m, FS)["cross"]) < 0.2


@pytest.mark.parametrize(("offset_s", "shared"), [(0.0, 1.0), (0.02, 1.0), (0.1, 0.0)])
def test_onset_coincidence(offset_s, shared):
    rng = np.random.default_rng(1)
    t = gated(harm(rng, 200), 0.0)
    m = gated(harm(rng, 250), offset_s)
    assert g.onset_coincidence(t, m, FS) == pytest.approx(shared, abs=0.1)


def test_harmonic_cancellation_sees_intermodulation():
    rng = np.random.default_rng(2)
    t, m = 0.1 * harm(rng, 200), 0.1 * harm(rng, 250)
    clean = g.harmonic_cancellation(t, m, FS)
    assert clean["gain_db"] > 20 and clean["residual_db"] < -15

    def bus(x):
        return np.tanh(4 * x) / 4

    # Saturating each track keeps it harmonic; saturating the sum doesn't.
    per = g.harmonic_cancellation(bus(t), bus(m), FS)
    st, sm = g.shares(bus, t, m)
    together = g.harmonic_cancellation(st, sm, FS, t_clean=bus(t), m_clean=bus(m))
    assert per["gain_db"] > clean["gain_db"] - 2
    assert together["gain_db"] < per["gain_db"] - 8
    assert together["residual_db"] > per["residual_db"] + 10


def test_shares_of_a_linear_bus_are_the_tracks():
    rng = np.random.default_rng(3)
    t, m = rng.standard_normal(1000), rng.standard_normal(1000)
    st, sm = g.shares(lambda x: 0.5 * x, t, m)
    np.testing.assert_allclose(st, 0.5 * t)
    np.testing.assert_allclose(sm, 0.5 * m)


def test_f0_track():
    rng = np.random.default_rng(4)
    times, f0 = g.f0_track(harm(rng, 220.0), FS)
    assert np.nanmedian(np.abs(f0 / 220.0 - 1)) < 0.002


def test_envelope_snr_falls_with_the_masker():
    rng = np.random.default_rng(5)
    t = 0.1 * harm(rng, 200) * smooth_am(rng, 4)
    m = 0.1 * harm(rng, 250) * smooth_am(rng, 4)
    assert g.envelope_snr(t, m, FS)["snr_env_db"] > g.envelope_snr(t, 4 * m, FS)["snr_env_db"]
