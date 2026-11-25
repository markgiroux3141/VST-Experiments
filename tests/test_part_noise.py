"""PB0's generators against their theory (docs/PART_NOISE_PLAN.md)."""

from __future__ import annotations

import math

import numpy as np
import pytest

from varimu.devices import noise
from varimu.part_noise import barkhausen, bench, contact, popcorn, resistor, rng_for

FS = 96000.0


def band_power(x: np.ndarray, rate_hz: float, lo: float, hi: float) -> float:
    """The mean-square of x between lo and hi (Hz), from its periodogram."""
    spec = np.fft.rfft(x)
    f = np.fft.rfftfreq(x.size, 1.0 / rate_hz)
    keep = (f >= lo) & (f < hi)
    return float(2.0 * np.sum(np.abs(spec[keep]) ** 2) / x.size**2)


def test_johnson_density_is_4ktr():
    n = int(4 * FS)
    v = resistor.johnson_v(100e3, 300.0, n, FS, seed=1, name="r")
    measured = band_power(v, FS, 1000.0, 10000.0) / 9000.0
    theory = (
        4 * noise.K_B * 300.0 * 100e3 * np.mean(noise.interp_gain(np.linspace(1e3, 1e4, 99), FS))
    )
    assert measured == pytest.approx(theory, rel=0.05)


@pytest.mark.parametrize("ni_db", [-25.0, 0.0, 10.0])
def test_excess_noise_per_decade_is_the_noise_index(ni_db):
    """IEC 60195's definition: rms uV per volt of DC in one decade (here 100 Hz - 1 kHz)."""
    n = int(8 * FS)
    dc_v, r = 100.0, 100e3
    v = resistor.excess_v(np.full(n, dc_v / r), r, ni_db, FS, seed=3, name=f"ni{ni_db}")
    per_decade_uv_per_v = math.sqrt(band_power(v, FS, 100.0, 1000.0)) / dc_v * 1e6
    assert 20 * math.log10(per_decade_uv_per_v) == pytest.approx(ni_db, abs=0.6)


def test_excess_noise_needs_current():
    n = int(FS)
    assert not np.any(resistor.excess_v(np.zeros(n), 100e3, 10.0, FS, 1, "r"))
    with pytest.raises(ValueError):
        resistor.excess_v(1e-3, 100e3, 0.0, FS, 1, "r")


def test_telegraph_statistics():
    trap = popcorn.Trap(1.0, tau_high_s=0.02, tau_low_s=0.06)
    rng = rng_for(5, "trap")
    s = popcorn.telegraph(trap, int(200 * FS), FS, rng)
    assert s.min() >= -1e-6 and s.max() <= 1.0 + 1e-6  # rounding of the integral
    assert s.mean() == pytest.approx(0.25, abs=0.02)  # tau_high / (tau_high + tau_low)
    high = s > 0.5
    rises = np.count_nonzero(high[1:] & ~high[:-1])
    mean_high_s = high.sum() / FS / rises
    assert mean_high_s == pytest.approx(0.02, rel=0.08)


@pytest.mark.parametrize("c", [0.5, 4.0])
def test_abbm_mean_and_relative_fluctuation(c):
    """The square-root diffusion's stationary mean is theta, its std / mean 1 / sqrt(c)."""
    theta = 10.0
    n = int(10 * FS)
    v = barkhausen.cir_path(
        np.full(n, theta), 2 * math.pi * 1000, c / theta, FS, rng_for(7, f"c{c}")
    )
    v = v[int(0.1 * FS) :]
    assert v.mean() == pytest.approx(theta, rel=0.05)
    assert v.std() / v.mean() == pytest.approx(1 / math.sqrt(c), rel=0.08)


def test_abbm_crackle_has_no_periodic_part():
    """Under a 50 Hz drive the crackle (process minus its mean path) folds to ~0 per phase."""
    n = int(4 * FS)
    t = np.arange(n) / FS
    h = 1.5 * np.sin(2 * math.pi * 50.0 * t)
    mean, v = barkhausen.crackle(h, FS, 2 * math.pi * 1000, 0.25, rng_for(9, "mains"))
    x = v - mean
    period = int(FS / 50)
    folded = x[: (n // period) * period].reshape(-1, period).mean(axis=0)
    assert np.sqrt(np.mean(folded**2)) < 0.1 * np.sqrt(np.mean(x**2))


def test_new_pot_follows_and_worn_pot_jumps():
    n = int(2 * FS)
    pos = np.linspace(0.1, 0.9, n)
    top = np.full(n, 2.5)
    new, ideal = contact.turned(top, pos, bench.TRACK_NEW, 150e-12, FS, rng_for(1, "new"))
    assert np.max(np.abs(new - ideal)) < 1e-6
    worn_track = contact.Track(1e6, crv=0.10, bad_spots=40.0)
    worn, ideal = contact.turned(top, pos, worn_track, 150e-12, FS, rng_for(1, "worn"))
    assert np.max(np.abs(worn - ideal)) > 1e-3


@pytest.mark.parametrize("name", ["johnson_100k", "carbon_comp_follows_tone", "popcorn_defective"])
def test_bench_is_reproducible(name):
    a = bench.render(name, 11, 48000.0)
    b = bench.render(name, 11, 48000.0)
    assert np.all(np.isfinite(a)) and np.array_equal(a, b)
