"""The separation experiment's prototypes (docs/SEPARATION_PLAN.md): flutter, room, measures."""

import numpy as np
import pytest

from varimu.separation import flutter, metrics, phrases, room

FS = 96000


def test_flutter_total_and_independence():
    a = flutter.speed_error(FS * 20, FS, 1)
    b = flutter.speed_error(FS * 20, FS, 2)
    assert np.std(a) == pytest.approx(flutter.TOTAL_RMS, rel=0.02)
    np.testing.assert_array_equal(a, flutter.speed_error(FS * 20, FS, 1))
    # Two passes on one machine: the rotations keep their rates at random phases (they can
    # correlate either way), the random parts are independent.
    assert abs(np.corrcoef(a, b)[0, 1]) < 0.8


def test_read_at_fractional_delay():
    n = np.arange(FS // 4)
    f = 3000.0
    x = np.sin(2 * np.pi * f * n / FS)
    np.testing.assert_allclose(
        flutter.read_at(x, n.astype(float))[100:-100], x[100:-100], atol=1e-12
    )
    y = flutter.read_at(x, n - 0.37)
    ref = np.sin(2 * np.pi * f * (n - 0.37) / FS)
    err = y[200:-200] - ref[200:-200]
    assert 20 * np.log10(np.std(err) / np.std(ref)) < -80


def test_flutter_pitch_deviation():
    # A 1 kHz tone's instantaneous frequency follows 1 - s(t) (recorded fast, plays flat).
    n = FS * 4
    x = np.sin(2 * np.pi * 1000 * np.arange(n) / FS)
    y = flutter.apply(x, FS, 3, total_rms=0.01)
    from scipy.signal import hilbert

    ph = np.unwrap(np.angle(hilbert(y)))
    inst = np.diff(ph) * FS / (2 * np.pi)
    s = flutter.speed_error(n, FS, 3, total_rms=0.01)
    mid = slice(FS // 2, -FS // 2)
    # Low-passed (the scrape band is above what a 1 kHz carrier resolves).
    k = np.ones(480) / 480
    dev = np.convolve(inst[mid] / 1000 - 1, k, "same")[1000:-1000]
    ref = np.convolve(s[1:][mid], k, "same")[1000:-1000]
    assert np.corrcoef(dev, -ref)[0, 1] > 0.98


def test_air_absorption_iso_table():
    # ISO 9613-1 Table 1 at 20 C, 50% RH, 101.325 kPa: 1 kHz 4.66 dB/km, 4 kHz 29.7 dB/km.
    a = room.air_absorption_db_per_m(np.array([1000.0, 4000.0]))
    np.testing.assert_allclose(a * 1000, [4.66, 29.7], rtol=0.03)


def test_band_weights_sum_to_one():
    w = room.band_weights(4096, FS)
    np.testing.assert_allclose(w.sum(0), 1.0, atol=1e-12)


def test_room_direct_sound_and_decay():
    r = room.ROOMS["home"]
    src, mic = (2.0, 2.0, 1.2), (4.3, 1.2, 1.5)
    h = room.impulse_response(r, src, mic, FS)
    d = room.direct_distance_m(src, mic)
    i = int(np.argmax(np.abs(h)))
    assert i / FS == pytest.approx(d / room.SPEED_OF_SOUND_M_S, abs=2 / FS)
    # The direct sound's energy (a fractional delay spreads it over a few samples).
    direct = np.sqrt(np.sum(h[i - 8 : i + 9] ** 2))
    assert direct == pytest.approx(1 / (4 * np.pi * d), rel=0.1)
    # Broadband T30 against Eyring's mid-band times.
    e = np.cumsum(h[::-1] ** 2)[::-1]
    edc = 10 * np.log10(e / e[0])
    t30 = (np.argmax(edc < -35) - np.argmax(edc < -5)) / FS * 2
    mids = r.rt60_s()[2:5]
    assert mids.min() * 0.7 < t30 < mids.max() * 1.3


def test_room_distance_lowers_direct_to_reverberant():
    r = room.ROOMS["home"]

    def drr(mic):
        h = room.impulse_response(r, (2.0, 2.0, 1.2), mic, FS)
        k = int(np.argmax(np.abs(h))) + int(0.0025 * FS)
        return 10 * np.log10(np.sum(h[:k] ** 2) / np.sum(h[k:] ** 2))

    assert drr((2.0, 2.3, 1.2)) - drr((4.3, 1.2, 1.5)) > 10


def test_glimpse_proportion_limits_and_level():
    rng = np.random.default_rng(0)
    t = rng.standard_normal(FS)
    m = rng.standard_normal(FS)
    assert metrics.glimpse_proportion(t, np.zeros(FS) + 1e-9, FS) == pytest.approx(1.0)
    assert metrics.glimpse_proportion(t, t, FS) == 0.0
    p_lo = metrics.glimpse_proportion(t * 0.3, m, FS)
    p_hi = metrics.glimpse_proportion(t * 3.0, m, FS)
    assert p_lo < p_hi
    g = metrics.level_for_proportion(t, m, FS, 0.5)
    assert metrics.glimpse_proportion(t * 10 ** (g / 20), m, FS) == pytest.approx(0.5, abs=0.03)


def test_match_loudness():
    pytest.importorskip("pyloudnorm")
    x = 0.1 * np.sin(2 * np.pi * 1000 * np.arange(FS * 3) / FS)
    assert metrics.loudness_lufs(metrics.match_loudness(x, FS), FS) == pytest.approx(
        metrics.TARGET_LUFS, abs=0.01
    )


def test_phrase_controls():
    notes = [(57, 0.0, 0.5), (69, 1.0, 0.5)]
    c = phrases.controls(notes, 120.0, 1000.0, 1.0, -1.0, -110.0)
    g, p = c["gate"], c["pitch"]
    assert (
        g[0] == -1.0 and g[249] == -1.0 and g[250] == -110.0 and g[500] == -1.0 and g[999] == -110.0
    )
    assert p[0] < p[600]  # a higher key, a higher (less negative) pitch control
    assert phrases.pitch_volts(440.0) == pytest.approx(p[600])


def test_glimpses_count_only_the_notes_cells():
    # A "tail" filling the gaps between the target's notes, where the masker is silent,
    # raises the proportion over all cells but not over the notes' cells.
    rng = np.random.default_rng(1)
    n = FS
    gate = (np.arange(n) // (FS // 10)) % 2 == 0
    notes = rng.standard_normal(n) * gate
    masker = rng.standard_normal(n) * gate * 3
    tail = notes + 0.3 * rng.standard_normal(n) * ~gate
    assert metrics.glimpse_proportion(tail, masker, FS) > 0.3
    assert metrics.glimpse_proportion(tail, masker, FS, notes=notes) < 0.05
