"""What the invented keyboards share with circuitsim's invented.rs: seeded Gaussian noise
(splitmix64 into Box-Muller), the RBJ band-pass, the exact modal step, and the event loop
(a keyboard of voices, asleep voices frozen and skipped, as keyed.rs runs them)."""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence

import numpy as np

M64 = (1 << 64) - 1
GOLDEN = 0x9E3779B97F4A7C15


class Gauss:
    """splitmix64 into Box-Muller, the spare kept (circuitsim's invented::Gauss)."""

    def __init__(self, seed: int) -> None:
        self.s = seed & M64
        self.spare: float | None = None

    def next_u64(self) -> int:
        self.s = (self.s + GOLDEN) & M64
        z = self.s
        z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & M64
        z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & M64
        return z ^ (z >> 31)

    def uniform(self) -> float:
        return ((self.next_u64() >> 11) + 0.5) / float(1 << 53)

    def next(self) -> float:
        if self.spare is not None:
            x, self.spare = self.spare, None
            return x
        u, v = self.uniform(), self.uniform()
        r = math.sqrt(-2.0 * math.log(u))
        a = 2.0 * math.pi * v
        self.spare = r * math.sin(a)
        return r * math.cos(a)


def key_seed(seed: int, note: int) -> int:
    """A voice's noise stream (as nickel.rs seeds its keys)."""
    return (seed ^ ((note * GOLDEN) & M64)) & M64


def bandpass(f_hz: float, q: float, fs: float) -> tuple[float, float, float, float, float]:
    """RBJ's constant-0-dB-peak band-pass, normalized: (b0, b1, b2, a1, a2)."""
    w0 = 2.0 * math.pi * f_hz / fs
    alpha = math.sin(w0) / (2.0 * q)
    a0 = 1.0 + alpha
    return (alpha / a0, 0.0, -alpha / a0, -2.0 * math.cos(w0) / a0, (1.0 - alpha) / a0)


def modal_step(f_hz: float, q: float, h: float, mass: float) -> list[float]:
    """One trapezoidal step of m x'' + c x' + k x = F (unit mode shape), y+ = P y + r (F + F+):
    [p00, p01, p10, p11, r0, r1] (the bowed bar's step, varimu.invented.friction)."""
    w = 2.0 * math.pi * f_hz
    zeta = 1.0 / (2.0 * q)
    hw2 = h * w / 2.0
    det = 1.0 + h * zeta * w + hw2 * hw2
    i00 = (1.0 + h * zeta * w) / det
    i01 = (h / 2.0) / det
    i10 = (-(h / 2.0) * w * w) / det
    i11 = 1.0 / det
    a01, a10, a11 = h / 2.0, -(h / 2.0) * w * w, 1.0 - h * zeta * w
    p00 = i00 + i01 * a10
    p01 = i00 * a01 + i01 * a11
    p10 = i10 + i11 * a10
    p11 = i10 * a01 + i11 * a11
    b = (h / 2.0) / mass
    return [p00, p01, p10, p11, i01 * b, i11 * b]


def play(
    voices: dict[int, object],
    n: int,
    events: Sequence[tuple[int, str, int, float]],
    sample: Callable[[object], float],
    shared: object | None = None,
) -> np.ndarray:
    """keyed.rs's loop in the plain: for each step, the events landing there (on / off to
    the key's voice, pedal / pressure to every voice), then every awake voice's sample
    (voice.asleep(), voice.on(vel), voice.off(), voice.pedal(down), voice.pressure(v)),
    summed in note order. A voice with a `now` attribute is told the sample before each step
    (keyed.rs's `KeyVoice::chunk_start`: the Aeolian Keyboard's shared chest). `shared`, if
    given, gets every event too (shared.event(kind, note, value)) and steps once a sample
    after them, before the voices (keyed.rs's `KeyVoice::prepare`: the Siren Organ's shaft)."""
    evs = sorted(events, key=lambda e: e[0])
    out = np.zeros(n)
    order = sorted(voices)
    j = 0
    for p in range(n):
        while j < len(evs) and evs[j][0] <= p:
            _, kind, note, value = evs[j]
            j += 1
            if shared is not None:
                shared.event(kind, note, value)
            if kind == "on" and value > 0 and note in voices:
                voices[note].on(int(value))
            elif kind in ("on", "off") and note in voices:
                voices[note].off()
            elif kind == "pedal":
                for v in voices.values():
                    v.pedal(value > 0)
            elif kind == "pressure":
                for v in voices.values():
                    v.pressure(int(value))
        if shared is not None:
            shared.step()
        acc = 0.0
        for note in order:
            v = voices[note]
            if not v.asleep():
                if hasattr(v, "now"):
                    v.now = p
                acc += sample(v)
        out[p] = acc
    return out
