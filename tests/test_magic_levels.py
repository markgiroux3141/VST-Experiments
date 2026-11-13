"""AM6: A-weighting's anchors and the optimum on a synthetic stage."""

from __future__ import annotations

import numpy as np

from varimu.listen import difference
from varimu.magic import levels

FS = 96000


def test_a_weighting_reads_iec_values():
    db = 20 * np.log10(levels.a_gain(np.array([100.0, 1000.0, 10000.0])))
    assert abs(db[1]) < 0.01
    assert abs(db[0] + 19.1) < 0.1
    assert abs(db[2] + 2.5) < 0.2  # IEC 61672: -2.5 dB at 10 kHz


def test_optimum_of_tanh_plus_noise():
    t = np.arange(2 * FS) / FS
    x = np.sin(2 * np.pi * 440 * t) * (0.6 + 0.4 * np.sin(2 * np.pi * 1.1 * t))
    x /= np.std(x)
    noise_rms = 1e-3
    lv = np.arange(-40.0, 7.0, 3.0)
    imp = []
    for L in lv:
        u = x * 10 ** (L / 20)
        y = np.tanh(u)
        char = difference.decompose(u, y).character
        e = FS // 4
        c = np.std(char[e:-e])
        imp.append((noise_rms**2 + c**2) / np.mean(y**2))
    found = levels.optimum(lv, np.array(imp))
    # The analytic optimum: tanh's character ~ k L^3 (third order) against a fixed noise;
    # impairment = n^2 / s^2 + k^2 s^4 is least where its derivative vanishes. Check that
    # the grid's minimum is within one step of the found level.
    i = int(np.argmin(imp))
    assert abs(found - lv[i]) <= 3.0
    assert -30 < found < 0
