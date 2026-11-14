"""AM1's fingerprints on synthetic signals with known answers (ANALOG_MAGIC_FABLE.md)."""

from __future__ import annotations

import numpy as np
from scipy import signal

from varimu.magic import fingerprints as fp

FS = 48000


def _pink(n: int, rng) -> np.ndarray:
    X = np.fft.rfft(rng.standard_normal(n))
    f = np.fft.rfftfreq(n, 1 / FS)
    f[0] = f[1]
    y = np.fft.irfft(X / np.sqrt(f), n)
    return y / np.std(y)


def test_ltas_tilt_and_edge():
    rng = np.random.default_rng(1)
    assert abs(fp.ltas(_pink(20 * FS, rng), FS)["tilt_db_oct"] + 3.0) < 0.2
    w = rng.standard_normal(20 * FS)
    sos = signal.butter(12, 12000, fs=FS, output="sos")
    edge = fp.ltas(signal.sosfilt(sos, w), FS)["hf_edge_hz"]
    assert 12000 <= edge <= 13000  # the 12.5 kHz band


def test_crest_by_band():
    t = np.arange(12 * FS) / FS
    s = np.sin(2 * np.pi * 1000 * t)
    assert abs(fp._crest_db(s) - 3.01) < 0.05
    rng = np.random.default_rng(2)
    c = fp.crest_by_band(rng.standard_normal(12 * FS), FS)
    # Gaussian noise's largest of 144,000 samples: sqrt(2 ln 288000) = 5.0 sigma, 14 dB (the
    # doc's 11-13 dB was too low).
    assert 13 <= c["broadband"] <= 14.6


def test_asymmetry_falls_through_an_allpass():
    n = 12 * FS
    x = np.zeros(n)
    x[:: FS // 100] = 1.0  # a 100 Hz pulse train
    x = signal.sosfilt(signal.butter(2, 50, "highpass", fs=FS, output="sos"), x)
    a0 = fp.asymmetry(x, FS)["peak_ratio_db"]
    # Four first-order all-pass poles at 200 Hz.
    c = (np.tan(np.pi * 200 / FS) - 1) / (np.tan(np.pi * 200 / FS) + 1)
    y = x
    for _ in range(4):
        y = signal.lfilter([c, 1], [1, c], y)
    a1 = fp.asymmetry(y, FS)["peak_ratio_db"]
    assert a0 > 6 and a1 < a0 - 3


def test_level_distribution_spread():
    t = np.arange(20 * FS) / FS
    g = np.where((t // 2) % 2 == 0, 1.0, 10 ** (-12 / 20))
    x = 0.3 * g * np.sin(2 * np.pi * 1000 * t)
    d = fp.level_distribution(x, FS)
    assert abs(d["spread_db"] - 12) < 0.5


def test_comodulation():
    rng = np.random.default_rng(3)
    n = 12 * FS
    w = rng.standard_normal(n)
    assert abs(fp.comodulation(w, FS)["mean_corr"]) < 0.1
    env = 1 + 0.9 * np.sin(2 * np.pi * 5 * np.arange(n) / FS)
    assert fp.comodulation(w * env, FS)["mean_corr"] > 0.8


def test_floor_follow():
    rng = np.random.default_rng(4)
    t = np.arange(12 * FS) / FS
    trem = 10 ** (20 * np.sin(2 * np.pi * 3 * t) / 20)  # +-20 dB
    tone = 0.3 * trem * np.sin(2 * np.pi * 200 * t)
    noise = 1e-3 * rng.standard_normal(len(t))
    assert fp.floor_follow(tone + noise, FS)["slope"] < 0.1
    s = fp.floor_follow(tone + noise * trem, FS)["slope"]
    assert 0.8 <= s <= 1.05


def test_hum_finds_a_planted_line():
    rng = np.random.default_rng(5)
    n = 64 * FS
    x = 10 ** (-40 / 20) * _pink(n, rng)
    x = x + 10 ** (-70 / 20) * np.sin(2 * np.pi * 60 * np.arange(n) / FS)
    h = fp.hum(x, FS)
    assert abs(h["60"]["level_dbfs"] + 70) < 1.0


def test_stereo():
    rng = np.random.default_rng(6)
    a = rng.standard_normal(10 * FS)
    s = fp.stereo(np.column_stack([a, a]), FS)
    assert s["coherence"]["1000"] > 0.999 and s["side_over_mid_db"] == float("-inf")
    s = fp.stereo(np.column_stack([a, rng.standard_normal(10 * FS)]), FS)
    assert max(s["coherence"].values()) < 0.1


def test_tuning_of_a_sharp_chord():
    t = np.arange(20 * FS) / FS
    x = np.zeros_like(t)
    for midi in (57, 61, 64, 69, 73):  # A major, 15 cents sharp
        f = 440 * 2 ** ((midi - 69 + 0.15) / 12)
        for h in (1, 2, 3):
            x += np.sin(2 * np.pi * f * h * t) / h
    assert abs(fp.tuning(x, FS)["offset_cents"] - 15) < 2


def test_flutter():
    t = np.arange(10 * FS) / FS
    # 0.1 % rms frequency deviation at 5 Hz: peak 0.1 * sqrt(2) % of 1 kHz.
    dev = 1e-3 * np.sqrt(2) * np.sin(2 * np.pi * 5 * t)
    phase = 2 * np.pi * np.cumsum(1000 * (1 + dev)) / FS
    r = fp.flutter(np.sin(phase), FS, (700, 1400))
    assert abs(r["wow"] - 1e-3) < 1e-4


def test_bass_arrival():
    n = 20 * FS
    x = np.zeros(n)
    rng = np.random.default_rng(7)
    for k in range(1, 19):
        s = k * FS
        x[s : s + 48] += rng.standard_normal(48)  # a click
        m = np.arange(int(0.3 * FS))
        d = int(0.020 * FS)
        x[s + d : s + d + len(m)] += (
            0.5 * np.sin(2 * np.pi * 60 * m / FS) * np.exp(-m / (0.08 * FS))
        )
    r = fp.bass_arrival(x, FS)
    assert abs(r["median_s"] - 0.020) < 0.004
