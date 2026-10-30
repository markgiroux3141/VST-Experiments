"""The noise streams and densities (device builder B5): varimu.devices.noise."""

from __future__ import annotations

import math

import numpy as np
import pytest
from scipy.signal import welch

from varimu.config import REPO_ROOT
from varimu.devices import noise as nz

NOISE_FIXTURE = REPO_ROOT / "crates/circuitsim/tests/fixtures/noise/noise.json"

M0, M1 = 0xD2E7470EE14C6C93, 0xCA5A826395121157
W0, W1 = 0x9E3779B97F4A7C15, 0xBB67AE8584CAA73B
MASK = (1 << 64) - 1


def _philox(counter: int, k: tuple[int, int]) -> list[int]:
    """Philox4x64-10 from its definition (Salmon et al. 2011), in Python integers."""
    c = [counter, 0, 0, 0]
    k0, k1 = k
    for _ in range(10):
        p0, p1 = M0 * c[0], M1 * c[2]
        c = [(p1 >> 64) ^ c[1] ^ k0, p1 & MASK, (p0 >> 64) ^ c[3] ^ k1, p0 & MASK]
        k0, k1 = (k0 + W0) & MASK, (k1 + W1) & MASK
    return c


def test_fixture_is_current():
    assert NOISE_FIXTURE.read_text("utf-8") == nz.noise_fixtures_json(), (
        "rerun scripts/export_circuit_fixtures.py"
    )


def test_philox_is_numpys_and_the_definitions():
    assert _philox(0, (0, 0)) == [
        0x16554D9ECA36314C,
        0xDB20FE9D672D0FDC,
        0xD7E772CEE186176B,
        0x7E68B68AEC7BA23B,
    ]  # Random123's known answer
    k = nz.key(99, "IN_R7", nz.STREAM_MAIN)
    words = nz._words(k, 0, 5)
    for b in range(5):
        assert [int(w) for w in words[b]] == _philox(b + 1, k)


def test_streams_are_the_same_from_any_start_and_independent():
    k = nz.key(5, "IN_R1", nz.STREAM_MAIN)
    whole = nz.normals(k, 0, 64)
    for start in (1, 3, 4, 5, 33):
        assert np.array_equal(nz.normals(k, start, 20), whole[start : start + 20])
    others = [
        nz.normals(nz.key(5, "IN_R2", nz.STREAM_MAIN), 0, 64),
        nz.normals(nz.key(6, "IN_R1", nz.STREAM_MAIN), 0, 64),
        nz.normals(nz.key(5, "IN_R1", nz.STREAM_GRID), 0, 64),
    ]
    for o in others:
        assert not np.allclose(o, whole)


def test_normals_are_unit_and_white():
    z = nz.normals(nz.key(1, "IN_R1", 0), 0, 2**20)
    assert abs(z.mean()) < 5 / 2**10
    assert abs(z.var() - 1) < 0.01
    assert abs(np.mean(z**4) - 3) < 0.05  # Gaussian kurtosis
    assert abs(np.mean(z[1:] * z[:-1])) < 5 / 2**10


def test_flicker_is_one_over_f_and_stationary_from_the_start():
    fs = 96000.0
    f = nz.FlickerFilter.design(fs)
    assert (f.residues > 0).all()
    # The design's response in the band: within 0.05 dB of 1/f.
    ff = np.logspace(-2, 4, 300)
    x = np.exp(-2j * np.pi * ff / fs)
    h = f.direct + sum(r / (1 - p * x) for p, r in zip(f.poles, f.residues, strict=True))
    level_db = 10 * np.log10(ff * (f.gain * np.abs(h)) ** 2 * 2 / fs)
    assert np.abs(level_db).max() < 0.05
    # A run: the slope and level from Welch, and the variance right from sample 0 the same
    # as later (no warm-up).
    n = 2**20
    y = f.run(nz.key(3, "BN_X", nz.STREAM_FLICKER), nz.key(3, "BN_X", nz.STREAM_FLICKER_START), n)
    fw, s = welch(y, fs=fs, nperseg=2**17)
    sel = (fw > 2) & (fw < 5e3)
    slope = np.polyfit(np.log10(fw[sel]), np.log10(s[sel]), 1)[0]
    assert abs(slope + 1) < 0.03
    assert abs(10 * np.log10(np.exp(np.mean(np.log(s[sel] * fw[sel]))))) < 0.5
    # Stationary start: many starts' first samples have the stationary variance.
    keys = [
        (nz.key(s, "BN_X", nz.STREAM_FLICKER), nz.key(s, "BN_X", nz.STREAM_FLICKER_START))
        for s in range(400)
    ]
    first = [f.run(k, ks, 1)[0] for k, ks in keys]
    # y0 = gain (d x0 + sum s_i[0]), s[0] stationary (covariance P) with cov(s_i[0], x0) = r_i.
    p_sum = float(np.sum(f.start_chol @ f.start_chol.T))
    var = f.gain**2 * (f.direct**2 + 2 * f.direct * f.residues.sum() + p_sum)
    assert np.var(first) == pytest.approx(var, rel=0.2)


def test_densities():
    t = 300.0
    # 1 MOhm at 300 K: 128.7 nV/sqrt(Hz)
    assert math.sqrt(nz.johnson_a2(1e6, t) * 1e6**2) == pytest.approx(128.7e-9, rel=1e-3)
    gm = 1.6e-3
    # R_eq = 2.5 / gm at 290 K, as a plate current: gm^2 4 k T0 R_eq
    assert nz.shot_a2(gm) == pytest.approx(gm**2 * 4 * nz.K_B * 290 * 2.5 / gm)
    assert nz.shot_a2(-1e-3) == 0.0
    # Pentode: (Ib / Ik)(2.5 / gm)(1 + 8 Ic2 / gm) as R_eq
    ib, ic2 = 3e-3, 0.6e-3
    r_eq = ib / (ib + ic2) * 2.5 / gm * (1 + 8 * ic2 / gm)
    assert nz.shot_a2(gm, ib, ic2, nz.PARTITION) == pytest.approx(gm**2 * 4 * nz.K_B * 290 * r_eq)
    assert nz.grid_shot_a2(-1e-6) == pytest.approx(2 * nz.Q_E * 1e-6)
    assert nz.white_sigma(2.0, 96000.0) == pytest.approx(math.sqrt(96000.0))
    assert 10 * np.log10(nz.interp_gain(20e3, 96000.0)) == pytest.approx(-0.62, abs=0.01)
