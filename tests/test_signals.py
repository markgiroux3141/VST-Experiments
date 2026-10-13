import numpy as np
import pytest
from scipy.signal import fftconvolve

from varimu.measure import signals as S

SR = 96000


def _rms(x):
    return np.sqrt(np.mean(x**2))


def test_tone_burst_levels_and_zero_crossing_steps():
    sig = S.tone_burst(
        freq_hz=1000,
        base_dbfs=-40,
        burst_dbfs=-10,
        pre_s=0.1,
        burst_s=0.1,
        release_s=0.1,
        sample_rate=SR,
    )
    for seg in sig.meta["segments"]:
        a, b = seg["start"], seg["stop"]
        assert _rms(sig.samples[a:b]) == pytest.approx(
            S.db_to_amp(seg["level_dbfs"]) / np.sqrt(2), rel=1e-6
        )
    # Steps land on zero crossings, so there's no discontinuity in the waveform.
    for idx in (sig.meta["burst_start"], sig.meta["burst_stop"]):
        assert abs(sig.samples[idx]) < 1e-9


def test_stepped_sine_levels():
    sig = S.stepped_sine(
        freq_hz=1000, start_dbfs=-30, stop_dbfs=0, step_db=3, hold_s=0.05, sample_rate=SR
    )
    segs = sig.meta["segments"]
    assert [s["level_dbfs"] for s in segs] == list(range(-30, 1, 3))
    for seg in segs:
        a, b = seg["start"], seg["stop"]
        mid = sig.samples[a + (b - a) // 4 : b - (b - a) // 4]  # clear of the ramps
        assert 20 * np.log10(_rms(mid) * np.sqrt(2)) == pytest.approx(seg["level_dbfs"], abs=0.01)


def test_thump_lead_silence_is_exact_zero():
    sig = S.thump_bursts(
        freq_hz=6000,
        burst_dbfs=[-20, 0],
        lead_silence_s=0.2,
        burst_s=0.05,
        gap_s=0.1,
        sample_rate=SR,
    )
    first = sig.meta["bursts"][0]["start"]
    assert first == round(0.2 * SR)
    assert not np.any(sig.samples[:first])
    assert len(sig.meta["bursts"]) == 2


def _deconvolve(sig, y):
    return fftconvolve(y, sig.companions["inverse"])


def test_ess_deconvolves_to_unit_impulse():
    sig = S.exp_sweep(
        f_start_hz=20,
        f_stop_hz=20000,
        duration_s=2.0,
        level_dbfs=-6,
        pre_s=0.1,
        post_s=0.1,
        sample_rate=SR,
    )
    ir = _deconvolve(sig, sig.samples)
    assert int(np.argmax(np.abs(ir))) == sig.meta["ir_index"]
    assert np.max(np.abs(ir)) == pytest.approx(1.0)
    # f_start * L is an integer (synchronized sweep), so the sweep starts at phase zero.
    assert sig.meta["f_start_hz"] * sig.meta["L_s"] == pytest.approx(
        round(sig.meta["f_start_hz"] * sig.meta["L_s"])
    )


def test_ess_separates_second_harmonic_at_expected_offset():
    sig = S.exp_sweep(
        f_start_hz=20,
        f_stop_hz=20000,
        duration_s=2.0,
        level_dbfs=-6,
        pre_s=0.1,
        post_s=0.5,
        sample_rate=SR,
    )
    x = sig.samples
    ir = _deconvolve(sig, x + 0.3 * x**2)
    expected = sig.meta["ir_index"] - round(sig.meta["L_s"] * np.log(2) * SR)
    window = np.abs(ir[expected - 200 : expected + 200])
    assert abs(int(np.argmax(window)) - 200) <= 2


@pytest.mark.parametrize("f1,f2,ratio", [(60, 7000, 4.0), (19000, 20000, 1.0)])
def test_twin_tone_spectrum(f1, f2, ratio):
    sig = S.twin_tone(
        f1_hz=f1, f2_hz=f2, ratio=ratio, level_dbfs=-10, duration_s=1.0, sample_rate=SR
    )
    assert np.max(np.abs(sig.samples)) <= S.db_to_amp(-10) + 1e-12
    seg = sig.samples[SR // 4 : SR // 4 + SR // 2]  # 0.5 s, 2 Hz bins, all tones on-bin
    mag = np.abs(np.fft.rfft(seg))
    bin_hz = 2.0
    a1, a2 = mag[round(f1 / bin_hz)], mag[round(f2 / bin_hz)]
    assert a1 / a2 == pytest.approx(ratio, rel=1e-6)
    others = np.delete(mag, [round(f1 / bin_hz), round(f2 / bin_hz)])
    assert others.max() < 1e-6 * a1


def test_multitone_is_seeded_and_leakage_free():
    kw = dict(
        f_lo_hz=20,
        f_hi_hz=20000,
        n_tones=31,
        level_dbfs=-10,
        period_s=1.0,
        repeats=2,
        sample_rate=SR,
    )
    a = S.multitone(rng=np.random.default_rng(1), **kw)
    b = S.multitone(rng=np.random.default_rng(1), **kw)
    c = S.multitone(rng=np.random.default_rng(2), **kw)
    assert np.array_equal(a.samples, b.samples)
    assert not np.array_equal(a.samples, c.samples)
    assert np.max(np.abs(a.samples)) == pytest.approx(S.db_to_amp(-10))

    period = a.samples[: a.meta["period_samples"]]
    mag = np.abs(np.fft.rfft(period))
    tone_bins = np.round(np.array(a.meta["freqs_hz"])).astype(int)  # 1 Hz bins
    assert np.delete(mag, tone_bins).max() < 1e-9 * mag[tone_bins].min()


def test_library_names_unique_and_kinds_known():
    specs = S.default_library()
    assert len({s.name for s in specs}) == len(specs)
    assert {s.kind for s in specs} <= set(S.GENERATORS)


def test_library_reproducible_from_seed():
    def hashes(seed):
        return {
            s.name: S.sha256(S.render(s, sample_rate=SR, seed=seed).samples)
            for s in S.default_library()
        }

    h0, h0_again, h1 = hashes(0), hashes(0), hashes(1)
    assert h0 == h0_again
    # Only seeded signals depend on the seed.
    changed = {n for n in h0 if h0[n] != h1[n]}
    assert changed == {s.name for s in S.default_library() if s.kind == "multitone"}


def test_render_rejects_over_full_scale():
    spec = S.SignalSpec(
        "hot", "twin_tone", dict(f1_hz=60, f2_hz=7000, ratio=4.0, level_dbfs=1.0, duration_s=0.1)
    )
    with pytest.raises(ValueError, match="full scale"):
        S.render(spec, sample_rate=SR, seed=0)
