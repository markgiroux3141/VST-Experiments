"""AM5's measurements on systems with known answers."""

from __future__ import annotations

import numpy as np
from scipy import signal

from varimu.listen import difference
from varimu.magic import dispersion as dp

FS = 96000


def test_small_signal_phase_of_a_high_pass():
    b, a = signal.butter(1, 30.0, "highpass", fs=FS)
    r = dp.small_signal(lambda x: signal.lfilter(b, a, x), FS, seconds=4.0)
    _, h = signal.freqz(b, a, worN=r["f"], fs=FS)
    sel = (r["f"] > 15) & (r["f"] < 20000)
    err = np.degrees(np.angle(r["H"][sel] / h[sel]))
    assert np.max(np.abs(err)) < 1.0
    assert abs(r["delay_s"]) < 1e-6


def test_allpass_fir_matches_a_first_order_allpass():
    b, a = dp.first_order_allpass(200.0, FS)
    f = np.geomspace(12, 30000, 400)
    _, h = signal.freqz(b, a, worN=f, fs=FS)
    fir = dp.allpass_fir(f, h, FS)
    rng = np.random.default_rng(1)
    x = signal.lfilter([1], [1, -0.98], rng.standard_normal(4 * FS)) * 0.01
    y1 = dp.apply_fir(fir, x)
    y2 = signal.lfilter(b, a, x)
    m = FS // 2
    e = y1[m:-m] - y2[m:-m]
    assert 20 * np.log10(np.std(e) / np.std(y2[m:-m])) < -60
    _, hf = signal.freqz(fir, worN=np.geomspace(20, 20000, 200), fs=FS)
    assert np.max(np.abs(20 * np.log10(np.abs(hf)))) < 0.05


def test_tanh_commutes_with_a_delay_but_not_an_allpass():
    n = 2 * FS
    x = np.zeros(n)
    x[:: FS // 100] = 1.0
    x = signal.lfilter([1, -1], [1, -0.995], x) * 0.8

    def sat(v):
        return np.tanh(4 * v)

    d = 37
    y1 = sat(np.roll(x, d))
    y2 = np.roll(sat(x), d)
    assert 20 * np.log10(np.std(y1 - y2) / np.std(y1) + 1e-300) < -100
    b, a = dp.first_order_allpass(200.0, FS)

    def ap(v):
        for _ in range(4):
            v = signal.lfilter(b, a, v)
        return v

    lv = difference.levels(ap(sat(x)), sat(ap(x)))
    assert lv["character"] > -40
