"""The 200A's keyboard: every key's reed played by note and pedal events, the reeds'
capacitance to the plate summed (docs/WURLITZER_PLAN.md, WZ3).

**A voice** is one key over a timeline. Between events its reed moves freely, evaluated in
closed form (the system's eigenvectors, each a decaying rotation per sample); a note-on
throws the hammer at the reed wherever it is (`key.contact`: a reed still ringing is met
where it swings); the damper's felt is on the reed whenever the key is up and the pedal
isn't down (`key.System(damped=True)`: the same modal coordinates, so switching carries the
state). Keys from `damper.undamped_from_key` up have no damper. A voice whose tip's
amplitude bound falls under `SLEEP_M` sleeps until struck again.

**The plate.** Every reed sits in its own slot of the one comb plate, so the plate's
capacitance to the reeds is the sum of each reed's (`pickup.py`'s map integrated over the
slot); `Render.dc_f` is that sum less its value at rest. The 200A's circuit takes it as the
reeds' current, `circuit.plate_input_v` (WZ2's input `in`).

Rates: the reeds' capacitance at `oversample` x fs (the map's nonlinearity makes
harmonics), decimated to fs; the hammer's contact stepped at `step_oversample` x fs.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy import linalg, signal

from varimu.rhodes.midi import Event
from varimu.wurlitzer import key as ky
from varimu.wurlitzer import spec as sp

SLEEP_M = 1e-9
CHUNK = 8192
CONTACT_WINDOW_S = 0.03
MIDI_KEY_OFFSET = 32  # MIDI 33 (A1) is key 1


class _Motion:
    """A system's free motion: x(t) = V exp(lambda t) V^-1 x0, read at the slices and the
    tip, with exp(lambda t) for t = 1..CHUNK samples."""

    def __init__(self, sysm: ky.System, dt: float):
        lam, v = linalg.eig(sysm.a)
        self.sysm = sysm
        self.v, self.vinv = v, linalg.inv(v)
        self.cs = sysm.c_slices @ v
        self.ct = sysm.c_tip @ v
        self.rot = np.exp(np.outer(lam, dt * np.arange(1, CHUNK + 1)))


@dataclass
class Voice:
    """One key over a timeline, adding its reed's capacitance change into `out` (at fs x
    oversample)."""

    k: sp.Key
    out: np.ndarray
    fs_hz: float
    oversample: int = 2
    step_oversample: int = 4
    n: int = 0  # the sample (of `out`) the state is at
    strikes: list = field(default_factory=list)
    off_map_samples: int = 0

    def __post_init__(self):
        if self.step_oversample % self.oversample:
            raise ValueError("step_oversample must be a multiple of oversample")
        dt = 1.0 / (self.fs_hz * self.oversample)
        self.h = 1.0 / (self.fs_hz * self.step_oversample)
        self.every = self.step_oversample // self.oversample
        free = ky.System(self.k)
        self.free = _Motion(free, dt)
        self.damp = (
            _Motion(ky.System(self.k, damped=True), dt)
            if self.k.damper_decay_db_s is not None
            else self.free
        )
        self.fmap = sp.field(self.k)
        self.w = free.slice_w
        self.c0 = float(self.w @ self.fmap(np.full(self.w.size, self.k.voicing_m)))
        self.motion = self.damp
        self.x = np.zeros(2 * free.n)
        self.asleep = True

    def _dc(self, sl: np.ndarray) -> np.ndarray:
        zz = self.k.voicing_m + sl
        lo, hi = self.fmap.z_range_m
        self.off_map_samples += int(np.sum(np.any((zz < lo) | (zz > hi), axis=0)))
        return self.w @ self.fmap(zz) - self.c0

    def advance_to(self, n_end: int) -> None:
        """The free (or damped) motion from the state's sample to n_end."""
        n_end = min(n_end, self.out.size - 1)
        if n_end <= self.n:
            return
        if self.asleep:
            self.n = n_end
            return
        mo = self.motion
        z = mo.vinv @ self.x.astype(complex)
        n = self.n
        while n < n_end:
            m = min(CHUNK, n_end - n)
            zt = mo.rot[:, :m] * z[:, None]
            self.out[n + 1 : n + 1 + m] += self._dc(np.real(mo.cs @ zt))
            z = zt[:, -1]
            n += m
            if np.sum(np.abs(mo.ct * z)) < SLEEP_M:
                z = np.zeros_like(z)
                self.asleep = True
                break
        self.x = np.real(mo.v @ z)
        self.n = n_end

    def strike(self, n: int, speed_m_s: float, n_limit: int) -> None:
        """The key struck at sample n at `speed_m_s` (the damper lifted); the contact solved
        until the next event on this key (n_limit) or for CONTACT_WINDOW_S."""
        n = max(n, self.n)  # struck again within the last strike's window: at its end
        self.advance_to(n)
        self.motion = self.free
        self.asleep = False
        n_out = int(round(CONTACT_WINDOW_S * self.fs_hz * self.oversample))
        n_out = min(n_out, n_limit - n, self.out.size - n - 1)
        if n_out <= 0:
            return
        self.x, _, sl, stats = ky.contact(
            self.free.sysm, self.k.hammer, self.x, speed_m_s, self.h, self.every, n_out
        )
        self.out[n + 1 : n + 1 + n_out] += self._dc(sl)
        self.strikes.append((n, speed_m_s, *stats))
        self.n = n + n_out

    def damper(self, n: int, on: bool) -> None:
        self.advance_to(n)
        self.motion = self.damp if on else self.free


@dataclass(frozen=True)
class Render:
    dc_f: np.ndarray  # the reeds' capacitance to the plate less its rest value, at fs
    fs_hz: float
    skipped: int  # notes outside the 64 keys
    voices: dict  # key -> Voice
    raw_f: np.ndarray  # dc_f at fs x oversample, before decimation (index 0: rest)


def render(
    events: list[Event],
    duration_s: float,
    fs_hz: float = 96000.0,
    oversample: int = 2,
    step_oversample: int = 4,
    name: str = "200a",
    progress: bool = False,
) -> Render:
    """The reeds' capacitance change for the events (MIDI notes 33-96: the 64 keys; the
    velocity through `spec.hammer_speed`; the pedal down holds every damper off)."""
    n_total = int(round(duration_s * fs_hz * oversample)) + 1
    out = np.zeros(n_total)
    voices: dict[int, Voice] = {}
    held: set[int] = set()
    pedal = False
    skipped = 0
    n_keys = int(sp.load(name)["keyboard"]["keys"])
    events = sorted(events, key=lambda e: (e.t_s, e.kind != "off"))
    for i, e in enumerate(events):
        n = int(round(e.t_s * fs_hz * oversample))
        if n >= n_total - 1:
            break
        if e.kind == "pedal":
            pedal = bool(e.value)
            for kn, v in voices.items():
                v.damper(n, on=not pedal and kn not in held)
            continue
        kn = e.note - MIDI_KEY_OFFSET
        if not 1 <= kn <= n_keys:
            skipped += e.kind == "on"
            continue
        if kn not in voices:
            voices[kn] = Voice(sp.key(kn, name), out, fs_hz, oversample, step_oversample)
            if progress:
                print(f"keyboard: key {kn} ({len(voices)} voices)", flush=True)
        v = voices[kn]
        if e.kind == "on":
            nxt = next(
                (f.t_s for f in events[i + 1 :] if f.kind != "pedal" and f.note == e.note),
                duration_s,
            )
            held.add(kn)
            v.strike(n, sp.hammer_speed(e.value, name), int(round(nxt * fs_hz * oversample)))
        else:
            held.discard(kn)
            if not pedal:
                v.damper(n, on=True)
    for v in voices.values():
        v.advance_to(n_total)
    dc = signal.resample_poly(out, 1, oversample) if oversample > 1 else out
    return Render(dc, fs_hz, skipped, voices, out)
