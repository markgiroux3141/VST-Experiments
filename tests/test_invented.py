"""The invented-instrument sketches (varimu/invented/): each mechanism does what its module
says, on short renders."""

from __future__ import annotations

import math

import numpy as np

from varimu.invented import aeolian, arc, bubbles, friction, jawari, rijke, siren
from varimu.invented.common import FS, envelope, rng


def peak_hz(x: np.ndarray, lo_hz: float = 40.0) -> float:
    sp = np.abs(np.fft.rfft(x * np.hanning(x.size)))
    fr = np.fft.rfftfreq(x.size, 1 / FS)
    k = np.searchsorted(fr, lo_hz)
    return float(fr[k + np.argmax(sp[k:])])


def cents(a: float, b: float) -> float:
    return 1200 * math.log2(a / b)


def test_a_pressed_bar_sings_its_fundamental():
    n = int(1.5 * FS)
    y = friction.bowed_bar(440.0, friction.press(n, 1.3, 0.6), rng(1, "t"))
    assert abs(cents(peak_hz(y[int(0.8 * FS) :]), 440.0)) < 30


def test_the_wind_picks_the_harmonic():
    f1 = 110.0
    n = int(2.0 * FS)
    y = aeolian.string(f1, aeolian.U_NOMINAL * envelope(n, 0, 1.9, 0.15, 0.1), rng(1, "t"))
    assert round(peak_hz(y[int(1.2 * FS) : int(1.9 * FS)]) / f1) == aeolian.HARMONIC


def test_the_arc_sings_and_its_trim_tunes_it():
    cf = arc.tuned_condenser(440.0, 5.0)
    p, tank = arc.sing(np.full(int(0.8 * FS), cf), 5.0, rng(2, "t"), hiss=0.0)
    assert np.max(np.abs(tank[int(0.4 * FS) :])) > 1.0  # amperes in the tank: it oscillates
    assert abs(cents(arc.measure_f0(p[int(0.4 * FS) :]), 440.0)) < 25


def test_the_arc_needs_its_negative_resistance():
    # above |dV/dI| = (c + d l) / I^2 (1.31 ohm at 5 A, 2 mm) the tank can't start
    p, tank = arc.sing(np.full(int(0.5 * FS), arc.condenser_f(330.0)), 5.0, rng(1, "t"),
                       hiss=0.0, tank_ohm=1.6)  # fmt: skip
    assert np.max(np.abs(tank[int(0.3 * FS) :])) < 0.05


def test_each_open_ring_sags_the_shaft():
    keys = [siren.Key(h, 0.1, 3.0) for h in (16, 20, 24, 28)]
    _, four = siren.play(keys, 3.0, rng(1, "t"))
    _, one = siren.play(keys[:1], 3.0, rng(1, "t"))
    sag = cents(four["rps_min"], one["rps_min"])
    assert -90 < sag < -40


def test_the_jawari_sustains_the_buzz():
    def high(jaw: float) -> float:
        y = jawari.string(130.8, 1.3, 1.5e-3, jawari=jaw)[int(1.0 * FS) :]
        sp = np.abs(np.fft.rfft(y * np.hanning(y.size))) ** 2
        fr = np.fft.rfftfreq(y.size, 1 / FS)
        return float(np.sum(sp[fr > 1500]) / np.sum(sp))

    assert high(0.2) > 3 * high(0.0)


def test_minnaert():
    # f r ~ 3.26 m/s at the surface (Minnaert 1933)
    assert abs(bubbles.minnaert_hz(3e-3, depth_m=0.0) * 3e-3 - 3.26) < 0.05
    y = bubbles.bubble(bubbles.radius_for(262.0), rng(1, "t"))
    assert abs(cents(peak_hz(y[: int(0.1 * FS)]), 262.0)) < 60  # the chirp rides above


def test_a_heated_pipe_sings_its_fundamental_and_a_cold_one_doesnt():
    n = int(3.0 * FS)
    hot = rijke.pipe(220.0, np.ones(n), rng(1, "t"))
    cold = rijke.pipe(220.0, np.full(n, 0.2), rng(1, "t"))
    late = slice(int(2.2 * FS), None)
    assert abs(cents(peak_hz(hot[late]), 220.0)) < 30
    assert np.sqrt(np.mean(hot[late] ** 2)) > 100 * np.sqrt(np.mean(cold[late] ** 2))
