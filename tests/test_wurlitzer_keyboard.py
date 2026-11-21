"""WZ3: the 200A's keyboard over events (varimu/wurlitzer/keyboard.py), its damper, pedal and
velocity law, and the reeds into the circuit (varimu/wurlitzer/circuit.py;
docs/WURLITZER_PLAN.md)."""

from __future__ import annotations

import numpy as np
import pytest
from scipy import signal

from varimu.rhodes.midi import Event
from varimu.wurlitzer import circuit, keyboard
from varimu.wurlitzer import key as ky
from varimu.wurlitzer import spec as sp

FS = 48000.0
OFFSET = keyboard.MIDI_KEY_OFFSET


def _fund_slope_db_s(y: np.ndarray, fs: float, f0: float, a_s: float, b_s: float) -> float:
    sos = signal.butter(4, [0.8 * f0, 1.2 * f0], "bandpass", fs=fs, output="sos")
    z = signal.sosfiltfilt(sos, y)
    blk = int(0.005 * fs)
    m = z.size // blk
    env = 20 * np.log10(np.sqrt(np.mean(z[: m * blk].reshape(m, blk) ** 2, axis=1)) + 1e-30)
    t = (np.arange(m) + 0.5) * 0.005
    sel = (t > a_s) & (t < b_s)
    return float(np.polyfit(t[sel], env[sel], 1)[0])


def test_a_lone_note_is_the_single_strike():
    n, vel = 28, 80
    speed = sp.hammer_speed(vel)
    r = keyboard.render(
        [Event(0.0, "on", n + OFFSET, vel)], 0.3, fs_hz=FS, oversample=4, step_oversample=8
    )
    s = ky.strike(sp.key(n), speed, duration_s=0.3, fs_hz=FS, oversample=4, step_oversample=8)
    c0 = s.c_f[0]
    model = r.raw_f[::4][: s.c_f.size]
    assert np.max(np.abs(model - (s.c_f - c0))) < 1e-6 * np.max(np.abs(s.c_f - c0))


@pytest.mark.parametrize("n", [10, 34])
def test_the_damper_decays_at_the_configured_rate(n):
    k = sp.key(n)
    r = keyboard.render(
        [Event(0.0, "on", n + OFFSET, 80), Event(0.1, "off", n + OFFSET, 0)], 0.4, fs_hz=FS
    )
    got = _fund_slope_db_s(r.dc_f, FS, k.f_hz, 0.13, 0.13 + 30 / abs(k.damper_decay_db_s))
    assert got == pytest.approx(k.damper_decay_db_s, rel=0.15)


def test_the_pedal_holds_the_dampers_off():
    n = 34
    k = sp.key(n)
    ev = [
        Event(0.0, "pedal", value=1),
        Event(0.01, "on", n + OFFSET, 80),
        Event(0.1, "off", n + OFFSET, 0),
    ]
    r = keyboard.render(ev, 0.6, fs_hz=FS)
    got = _fund_slope_db_s(r.dc_f, FS, k.f_hz, 0.15, 0.55)
    free = -np.pi * k.f_hz / (1 / k.reed.loss) * 20 / np.log(10)  # the reed's own Q
    assert got > 0.5 * k.damper_decay_db_s
    assert got == pytest.approx(free, abs=15.0)


def test_the_top_keys_have_no_damper():
    k = sp.key(62)
    assert k.damper_decay_db_s is None
    r = keyboard.render(
        [Event(0.0, "on", 62 + OFFSET, 80), Event(0.1, "off", 62 + OFFSET, 0)], 0.6, fs_hz=FS
    )
    assert _fund_slope_db_s(r.dc_f, FS, k.f_hz, 0.15, 0.55) > -100


def test_a_ringing_reed_struck_again():
    n = 10
    ev = [Event(0.0, "on", n + OFFSET, 60), Event(0.2, "on", n + OFFSET, 110)]
    r = keyboard.render(ev, 0.5, fs_hz=FS)
    v = r.voices[n]
    assert len(v.strikes) == 2
    after = np.max(np.abs(r.dc_f[int(0.25 * FS) :]))
    before = np.max(np.abs(r.dc_f[int(0.05 * FS) : int(0.2 * FS)]))
    assert after > before  # the harder strike swings it further


def test_the_velocity_law_passes_the_layers():
    cfg = sp.load()
    v = cfg["velocity"]
    for vel, speed in zip(v["layer_velocities"], v["layer_speeds_m_s"], strict=True):
        assert sp.hammer_speed(vel) == pytest.approx(speed, rel=0.15)
    speeds = [sp.hammer_speed(x) for x in range(1, 128)]
    assert np.all(np.diff(speeds) > 0)


def test_the_circuits_reeds_are_the_keyboards():
    assert circuit.c_reeds_f() == pytest.approx(sp.reeds_f(), rel=0.02)


def test_the_plate_input_is_the_reeds_current():
    """CREEDS driven by in = -V0 dC / C_reeds carries -V0 dC/dt into the plate."""
    dc = np.array([0.0, 1e-13, 3e-13])
    x = circuit.plate_input_v(dc)
    assert np.allclose(circuit.c_reeds_f() * np.diff(x), -circuit.plate_v0() * np.diff(dc))
