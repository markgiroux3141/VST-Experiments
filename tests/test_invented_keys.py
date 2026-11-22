"""The invented keyboards' live tier (docs/INVENTED_LIVE_PLAN.md): circuitsim's invented.rs
against the Python references in varimu/invented/keys/, on performances."""

from __future__ import annotations

import json

import numpy as np
import pytest

from varimu.invented.keys import common
from varimu.invented.keys import compile as kc

circuitsim = pytest.importorskip("circuitsim")

FS = 48_000.0


def element(ref: str, knobs: list[float], max_keys: int = 16) -> dict:
    instrument, data, sha = kc.ir_data(ref)
    return {
        "name": "VKEYS",
        "out": "out",
        "instrument": instrument,
        "data": data,
        "sha256": sha,
        "rate_hz": FS,
        "max_keys": float(max_keys),
        "k0": knobs[0],
        "k1": knobs[1],
        "k2": knobs[2],
        "k3": knobs[3],
    }


def db(err: np.ndarray, ref: np.ndarray) -> float:
    return 20 * np.log10(max(np.sqrt(np.mean(err**2)), 1e-300) / np.sqrt(np.mean(ref**2)))


PERFORMANCE = [
    (0, "on", 57, 90),
    (int(0.15 * FS), "on", 64, 50),
    (int(0.30 * FS), "pressure", 0, 100),
    (int(0.35 * FS), "off", 57, 0),
    (int(0.40 * FS), "pedal", 0, 1),
    (int(0.45 * FS), "off", 64, 0),
    (int(0.50 * FS), "on", 57, 120),  # a re-strike of a ringing bar
    (int(0.60 * FS), "pedal", 0, 0),
    (int(0.70 * FS), "off", 57, 0),
]


@pytest.mark.parametrize("limit", [0.0, 1.0])
def test_the_rosin_wheel_agrees_with_its_reference(limit: float):
    """LIMIT off, and LIMIT full: a bar pressed hard swells into its felt within the first
    second (the output then differs from LIMIT off), released into its damper."""
    from varimu.invented.keys import rosin

    ref = kc.latest("ROSIN_WHEEL")
    knobs = [0.375, 0.5, 1.0, limit]
    perf = PERFORMANCE + [
        (int(0.9 * FS), "on", 60, 127),
        (int(0.9 * FS), "pressure", 0, 127),
        (int(1.9 * FS), "off", 60, 0),
    ]
    n = int(2.1 * FS)
    kb = rosin.keyboard(kc.load(ref), FS, knobs)
    want = common.play(kb, n, perf, lambda v: v.step())
    got = circuitsim.invented_render(json.dumps(element(ref, knobs)), FS, n, perf, 0)
    assert np.sqrt(np.mean(want**2)) > 1e-3  # it sounds
    assert np.array_equal(got, want)  # bit-exact
    if limit:
        off = knobs[:3] + [0.0]
        free = circuitsim.invented_render(json.dumps(element(ref, off)), FS, n, perf, 0)
        assert db(got - free, free) > -20  # the felt acted


def test_the_rosin_wheel_without_its_felt_is_version_1():
    """The latest ROSIN_WHEEL at LIMIT 0 plays exactly as @1 (no felt: its k3 is unused)."""
    knobs = [0.6, 0.5, 0.6, 0.0]
    n = int(0.9 * FS)
    a = circuitsim.invented_render(
        json.dumps(element("ROSIN_WHEEL@1", knobs)), FS, n, PERFORMANCE, 0
    )
    b = circuitsim.invented_render(
        json.dumps(element(kc.latest("ROSIN_WHEEL"), knobs)), FS, n, PERFORMANCE, 0
    )
    assert np.array_equal(a, b)
    a1 = circuitsim.invented_render(
        json.dumps(element("ROSIN_WHEEL@1", knobs[:3] + [1.0])), FS, n, PERFORMANCE, 0
    )
    assert np.array_equal(a, a1)


def _rosin_note(knobs: list[float], note: int, vel: int, secs: float, off_s: float | None = None):
    fs = 96_000.0
    el = element(kc.latest("ROSIN_WHEEL"), knobs)
    el["rate_hz"] = fs
    perf = [(0, "on", note, vel)]
    if off_s is not None:
        perf.append((int(off_s * fs), "off", note, 0))
    return fs, circuitsim.invented_render(json.dumps(el), fs, int(secs * fs), perf, 0)


def _off_harmonic_db(y: np.ndarray, fs: float, f1: float) -> float:
    """The share of energy away from f1's harmonics (+-3 %): the rosin's scratch and the
    bar's inharmonic modes."""
    sp = np.abs(np.fft.rfft(y * np.hanning(y.size))) ** 2
    fr = np.fft.rfftfreq(y.size, 1 / fs)
    keep = np.zeros(fr.size, bool)
    for h in range(1, int(20_000 / f1)):
        keep |= np.abs(fr - h * f1) < 0.03 * f1
    return float(10 * np.log10(sp[~keep].sum() / sp.sum()))


def _levels_db(y: np.ndarray, k: int, n: int) -> np.ndarray:
    """The rms of the first n windows of k samples, in dB."""
    return 20 * np.log10(np.sqrt(np.mean(y[: n * k].reshape(n, k) ** 2, 1)) + 1e-12)


def test_even_holds_one_level_and_keeps_the_rosin():
    """The user: keep the rosin-on-glass scratch, an even level, a sooner start. At EVEN 0 a loud
    note swells for seconds (30 dB and more) into a clean tone (its limit cycle); at EVEN 0.5 it
    is up within 0.1 s, held within a few dB at one level on every key, and still scratchy
    (energy off the harmonics -5 to -32 dB, where the free tone is under -40)."""
    f1 = {k["note"]: k["f_hz"][0] for k in kc.load(kc.latest("ROSIN_WHEEL"))["keys"]}
    medians = []
    for note in (36, 60, 84):
        fs, free = _rosin_note([0.375, 0.5, 0.333, 0.0], note, 127, 4.0)
        fs, even = _rosin_note([0.375, 0.5, 0.333, 0.5], note, 127, 4.0)
        lf, le = _levels_db(free, int(0.1 * fs), 40), _levels_db(even, int(0.1 * fs), 40)
        assert lf[-1] - lf[1] > 30.0, (note, "a swell")
        med = float(np.median(le[1:]))
        medians.append(med)
        assert np.all(le[1:] > med - 8.0) and np.all(le[1:] < med + 4.0), (note, le - med)
        tex = _off_harmonic_db(even[int(1 * fs) : int(3 * fs)], fs, f1[note])
        assert -32.0 < tex < -5.0, (note, tex)
        if note > 36:  # the free treble's limit cycle is a clean tone
            assert _off_harmonic_db(free[int(3.5 * fs) :], fs, f1[note]) < -40.0, note
    assert np.ptp(medians) < 2.0, medians


def test_even_tames_the_runaway_and_lets_the_release_decay():
    """At the fastest WHEEL, full RESONATOR and a hard press a free bar swells past the 4 V full
    scale; EVEN holds it under 3 V. Let go, the AVC's gain is frozen: the damped bar decays."""
    hard = [(1.0, 1.0, 1.0)]
    fs, free = _rosin_note([*hard[0], 0.0], 60, 127, 5.0)
    fs, even = _rosin_note([*hard[0], 0.5], 60, 127, 5.0)
    assert np.max(np.abs(free)) > 4.5
    assert np.max(np.abs(even)) < 3.0
    fs, y = _rosin_note([0.375, 0.5, 0.333, 0.5], 60, 127, 3.0, off_s=2.0)

    def rms(a, b):
        return np.sqrt(np.mean(y[int(a * fs) : int(b * fs)] ** 2))

    assert 20 * np.log10(rms(2.3, 2.5) / rms(1.5, 2.0)) < -20.0


def test_the_buzz_zither_agrees_with_its_reference():
    """Two keys (one re-plucked while ringing, released, damped), the tanpura's cam on the
    pedal at a raised tonic, the JAWARI's contact, at the stream's 96 kHz."""
    from varimu.invented.keys import zither

    fs = 96_000.0
    ref = kc.latest("BUZZ_ZITHER")
    knobs = [0.6, 0.5, 0.7, 0.2]
    n = int(0.25 * fs)
    perf = [
        (0, "on", 72, 100),
        (int(0.02 * fs), "pedal", 0, 1),
        (int(0.05 * fs), "on", 79, 60),
        (int(0.10 * fs), "on", 72, 127),  # a re-pluck of a ringing string
        (int(0.15 * fs), "off", 79, 0),
        (int(0.20 * fs), "pedal", 0, 0),
        (int(0.22 * fs), "off", 72, 0),
    ]
    kb = zither.keyboard(kc.load(ref), fs, knobs)
    # only the keys played and the tanpura (the rest stay asleep in both)
    kb = {k: v for k, v in kb.items() if k in (0, 1, 2, 3, 72, 79)}
    want = common.play(kb, n, perf, lambda v: v.step())
    el = element(ref, knobs)
    el["rate_hz"] = fs
    got = circuitsim.invented_render(json.dumps(el), fs, n, perf, 0)
    assert np.sqrt(np.mean(want**2)) > 1e-3  # it sounds
    assert db(got - want, want) < -120
    assert np.array_equal(got, want)  # bit-exact, in fact


def test_the_jawari_brightens_the_ring():
    """JAWARI 0 (a sharp bridge) against 0.6 (the sketch's best, 10 um): the bridge's contact
    keeps the energy above 1.5 kHz up a second after the pluck (the sketch: +9 dB)."""
    from scipy import signal

    from varimu.invented.keys import zither

    fs = 96_000.0
    m = kc.load(kc.latest("BUZZ_ZITHER"))
    share = []
    for jaw in (0.0, 0.6):
        kb = {48: zither.keyboard(m, fs, [jaw, 0.5, 0.0, 0.0])[48]}
        y = common.play(kb, int(1.2 * fs), [(0, "on", 48, 100)], lambda v: v.step())
        f, p = signal.welch(y[int(1.0 * fs) :], fs, nperseg=4096)
        share.append(10 * np.log10(p[f > 1500].sum() / p.sum()))
    assert share[1] - share[0] > 6


def test_the_zither_is_the_same_on_any_number_of_threads():
    ref = kc.latest("BUZZ_ZITHER")
    el = element(ref, [0.6, 0.5, 0.7, 0.0])
    el["rate_hz"] = 96_000.0
    el = json.dumps(el)
    chord = [(0, "pedal", 0, 1)] + [(0, "on", k, 80) for k in (48, 52, 55, 60, 64, 67)]
    a = circuitsim.invented_render(el, 96_000.0, 9600, chord, 0)
    b = circuitsim.invented_render(el, 96_000.0, 9600, chord, 3)
    assert np.array_equal(a, b)


def test_the_rijke_organ_agrees_with_its_reference():
    """Two pipes (one released while the pedal holds its heater, then the pedal up),
    aftertouch, the gauze at a stop off the sketch's, the breath, at the stream's 96 kHz:
    long enough for a pipe to start (its bloom) and to fall silent."""
    from varimu.invented.keys import rijke

    fs = 96_000.0
    ref = kc.latest("RIJKE_ORGAN")
    knobs = [0.6, 0.4, 0.5, 0.0]
    n = int(2.5 * fs)
    perf = [
        (0, "on", 81, 110),
        (int(0.2 * fs), "on", 76, 70),
        (int(0.6 * fs), "pressure", 0, 90),
        (int(0.9 * fs), "pedal", 0, 1),
        (int(1.0 * fs), "off", 81, 0),
        (int(1.4 * fs), "off", 76, 0),
        (int(1.6 * fs), "pedal", 0, 0),
    ]
    kb = rijke.keyboard(kc.load(ref), fs, knobs)
    kb = {k: v for k, v in kb.items() if k in (76, 81)}
    want = common.play(kb, n, perf, lambda v: v.step())
    el = element(ref, knobs)
    el["rate_hz"] = fs
    got = circuitsim.invented_render(json.dumps(el), fs, n, perf, 0)
    assert np.sqrt(np.mean(want[int(0.8 * fs) :] ** 2)) > 0.05  # the pipes sing
    assert np.array_equal(got, want)  # bit-exact


def test_a_rijke_pipe_starts_late_and_holds_below_its_start():
    """The subcritical Hopf point (the sketch's): a held pipe blooms ~0.3-1.5 s after its key;
    with the heat then lowered (HEAT 0.5 -> 0.1: K 0.60 -> 0.36, below the start at ~0.40) it
    sings on, while a pipe heated at 0.36 from the first never starts."""
    from varimu.invented.keys import rijke

    fs = 96_000.0
    m = kc.load(kc.latest("RIJKE_ORGAN"))

    def rms(y):
        return np.array([np.sqrt(np.mean(y[i : i + 4800] ** 2)) for i in range(0, y.size, 4800)])

    v = rijke.keyboard(m, fs, [0.5, 0.4667, 0.25, 0.0])[69]
    v.on(1)
    y = np.array([v.step() for _ in range(int(2.0 * fs))])
    env = rms(y)
    onset_s = np.argmax(env > 0.3 * env.max()) * 0.05
    assert 0.3 < onset_s < 1.5
    assert env[:4].max() < 0.01 * env.max()  # silent before it starts
    v.set_knobs([0.1, 0.4667, 0.25, 0.0])
    held = rms(np.array([v.step() for _ in range(int(2.0 * fs))]))
    assert held[-5:].min() > 0.3 * env.max()  # it holds
    cold = rijke.keyboard(m, fs, [0.1, 0.4667, 0.25, 0.0])[69]
    cold.on(1)
    never = rms(np.array([cold.step() for _ in range(int(3.0 * fs))]))
    assert never.max() < 0.01 * env.max()  # it never starts


def test_the_aeolian_keyboard_agrees_with_its_reference():
    """Two strings (one released, its slot shutting and damper falling), aftertouch, the
    pedal, the chest's gust (absolute time: the second string opens later, mid-chunk), at the
    stream's 96 kHz."""
    from varimu.invented.keys import aeolian

    fs = 96_000.0
    ref = kc.latest("AEOLIAN_KEYBOARD")
    knobs = [0.45, 0.6, 0.0, 0.0]
    n = int(0.6 * fs)
    perf = [
        (0, "on", 57, 100),
        (int(0.1 * fs) + 37, "on", 64, 50),
        (int(0.2 * fs), "pressure", 0, 80),
        (int(0.3 * fs), "pedal", 0, 1),
        (int(0.35 * fs), "off", 57, 0),
        (int(0.4 * fs), "pedal", 0, 0),
        (int(0.45 * fs), "off", 64, 0),
    ]
    kb = aeolian.keyboard(kc.load(ref), fs, knobs)
    kb = {k: v for k, v in kb.items() if k in (57, 64)}
    want = common.play(kb, n, perf, lambda v: v.step())
    el = element(ref, knobs)
    el["rate_hz"] = fs
    got = circuitsim.invented_render(json.dumps(el), fs, n, perf, 0)
    assert np.sqrt(np.mean(want**2)) > 1e-3  # it sounds
    assert np.array_equal(got, want)  # bit-exact


def test_the_wind_picks_the_harmonic():
    """At the nominal 2.5 m/s every string speaks its 4th harmonic; at 3.6 m/s its 6th (the
    sketch's finding at 110 Hz)."""
    from varimu.invented.keys import aeolian

    fs = 96_000.0
    m = kc.load(kc.latest("AEOLIAN_KEYBOARD"))
    for wind_k, want in ((0.375, 4), (0.65, 6)):
        kb = {45: aeolian.keyboard(m, fs, [wind_k, 0.24, 0.0, 0.0])[45]}
        y = common.play(kb, int(1.5 * fs), [(0, "on", 45, 100)], lambda v: v.step())
        seg = y[int(0.8 * fs) :]
        sp = np.abs(np.fft.rfft(seg * np.hanning(seg.size)))
        f = np.fft.rfftfreq(seg.size, 1 / fs)
        assert round(f[np.argmax(sp)] / 110.0) == want


def test_the_aeolian_keyboard_is_the_same_on_any_number_of_threads():
    """Its voices read the absolute time (the chest's gust) on whichever thread renders them."""
    ref = kc.latest("AEOLIAN_KEYBOARD")
    el = element(ref, [0.375, 1.0, 0.0, 0.0])
    el["rate_hz"] = 96_000.0
    el = json.dumps(el)
    chord = [(0, "on", 45, 100), (700, "on", 52, 90)] + [
        (1000 + k, "on", k, 80) for k in (57, 60, 64, 69)
    ]
    a = circuitsim.invented_render(el, 96_000.0, 19200, chord, 0)
    b = circuitsim.invented_render(el, 96_000.0, 19200, chord, 3)
    assert np.array_equal(a, b)


def test_the_bubble_organ_agrees_with_its_reference():
    """STRUCK (single bubbles, a chord, their pops) and HELD (streams; aftertouch; the pedal
    holding a released key's valve, then lifting), at the stream's 96 kHz."""
    from varimu.invented.keys import bubbles

    fs = 96_000.0
    ref = kc.latest("BUBBLE_ORGAN")
    n = int(1.0 * fs)
    for knobs, perf in (
        (
            [0.0, 0.4, 0.2857, 0.25],
            [(0, "on", 72, 100), (int(0.2 * fs), "on", 48, 40), (int(0.2 * fs), "on", 55, 90)],
        ),
        (
            [1.0, 0.5, 0.4, 0.4],
            [
                (0, "on", 60, 100),
                (int(0.1 * fs), "on", 67, 64),
                (int(0.3 * fs), "pressure", 0, 100),
                (int(0.4 * fs), "pedal", 0, 1),
                (int(0.45 * fs), "off", 60, 0),
                (int(0.6 * fs), "pedal", 0, 0),
                (int(0.7 * fs), "off", 67, 0),
            ],
        ),
    ):
        kb = bubbles.keyboard(kc.load(ref), fs, knobs)
        kb = {k: v for k, v in kb.items() if k in (48, 55, 60, 67, 72)}
        want = common.play(kb, n, perf, lambda v: v.step())
        el = element(ref, knobs)
        el["rate_hz"] = fs
        got = circuitsim.invented_render(json.dumps(el), fs, n, perf, 0)
        assert np.sqrt(np.mean(want**2)) > 1e-3  # it sounds
        assert np.array_equal(got, want)  # bit-exact


def test_a_bubble_bends_flat_with_the_flow():
    """A struck bubble rings at its key at velocity 64 (the image included), and flat with
    more flow (r ~ q^0.4: FLOW 1.6x is ~3 semitones flat)."""
    from varimu.invented.keys import bubbles

    fs = 96_000.0
    m = kc.load(kc.latest("BUBBLE_ORGAN"))

    def pitch(flow_k: float) -> float:
        kb = {69: bubbles.keyboard(m, fs, [0.0, flow_k, 0.2857, 0.25])[69]}
        y = common.play(kb, int(0.05 * fs), [(0, "on", 69, 64)], lambda v: v.step())
        sp = np.abs(np.fft.rfft(y * np.hanning(y.size), 16 * y.size))
        return float(np.fft.rfftfreq(16 * y.size, 1 / fs)[np.argmax(sp)])

    assert abs(12 * np.log2(pitch(0.4) / 440.0)) < 0.5
    assert -3.8 < 12 * np.log2(pitch(1.0) / pitch(0.4)) < -2.5


def test_the_siren_organ_agrees_with_its_reference():
    """Both stops: keys struck mid-chunk and overlapping (the shaft and the bellows sag under
    them), aftertouch, the pedal holding a released key's valve, then lifting, a re-strike of
    a key still sounding; off-centre SPEED, WIND and MOTOR; at the stream's 96 kHz."""
    from varimu.invented.keys import siren

    fs = 96_000.0
    ref = kc.latest("SIREN_ORGAN")
    n = int(0.9 * fs)
    perf = [
        (0, "on", 57, 100),
        (int(0.1 * fs) + 37, "on", 64, 60),
        (int(0.2 * fs) + 101, "on", 36, 127),
        (int(0.3 * fs), "pressure", 0, 90),
        (int(0.4 * fs), "pedal", 0, 1),
        (int(0.45 * fs), "off", 57, 0),
        (int(0.5 * fs), "on", 64, 110),
        (int(0.6 * fs), "pedal", 0, 0),
        (int(0.65 * fs), "off", 36, 0),
        (int(0.7 * fs), "off", 64, 0),
    ]
    for knobs in ([0.5, 0.0, 0.5, 0.5], [0.62, 1.0, 0.3, 0.2]):
        m = kc.load(ref)
        kb, shaft = siren.keyboard(m, fs, knobs)
        kb = {k: v for k, v in kb.items() if k in (36, 57, 64)}
        want = common.play(kb, n, perf, lambda v: v.step(), shared=shaft)
        el = element(ref, knobs)
        el["rate_hz"] = fs
        got = circuitsim.invented_render(json.dumps(el), fs, n, perf, 0)
        assert np.sqrt(np.mean(want**2)) > 1e-2  # it sounds
        assert np.array_equal(got, want)  # bit-exact


def test_the_siren_organ_is_the_same_on_any_number_of_threads():
    ref = kc.latest("SIREN_ORGAN")
    el = element(ref, [0.5, 0.0, 0.5, 0.5])
    el["rate_hz"] = 96_000.0
    chord = [(0, "on", k, 80) for k in (45, 52, 57, 61, 64, 67, 72)]
    a = circuitsim.invented_render(json.dumps(el), 96_000.0, 19200, chord, 0)
    b = circuitsim.invented_render(json.dumps(el), 96_000.0, 19200, chord, 3)
    assert np.array_equal(a, b)


def test_a_chord_drags_the_shaft_and_the_wind():
    """One key at its full opening runs the shaft at its nominal speed; three more pull every
    pitch down together (~20 cents a ring, the sketch's KEY_DRAG) and the bellows' wind sags;
    a weak MOTOR sags further. The keyboard is the harmonic series on A (the 7th harmonic's
    G a third of a semitone flat)."""
    from varimu.invented.keys import siren

    fs = 96_000.0
    m = kc.load(kc.latest("SIREN_ORGAN"))

    def settle(keys: list[int], motor_k: float = 0.5) -> tuple[float, float]:
        sh = siren.Shaft(m, fs, [0.5, 0.0, 0.5, motor_k])
        for k in keys:
            sh.event("on", k, 127)
        w = p = 0.0
        for _ in range(int(2.5 * fs)):
            sh.step()
            w, p = sh.w, sh.p
        return w, p

    w1, p1 = settle([57])
    w4, p4 = settle([57, 61, 64, 67])
    w4_weak, _ = settle([57, 61, 64, 67], motor_k=0.25)
    assert abs(1200 * np.log2(w1 / siren.SHAFT_HZ)) < 0.5
    assert -70 < 1200 * np.log2(w4 / w1) < -45
    assert 1200 * np.log2(w4_weak / w1) < 1200 * np.log2(w4 / w1) - 30
    assert p4 < 0.9 * p1
    # A 64, C# 80, E 96, G 112 holes: 16:20:24:28 (the G the 7th harmonic, -31 cents)
    assert [siren.holes_of(k) for k in (57, 61, 64, 67)] == [64, 80, 96, 112]
