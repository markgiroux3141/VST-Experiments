"""The harp: every key's tone generator and pickup, played by note and pedal events, summed
by the pickups' wiring into the harp's open-circuit EMF (docs/RHODES_PLAN.md, RH2).

**A voice** is one key over a timeline (the live tier: the damped system's complex modes,
`key._System`). Between events its motion is free and evaluated in closed form (each
complex mode a decaying rotation); a note-on throws the hammer at the tine wherever it is
(a key struck again hits a moving tine: `key.contact`); the damper's felt is on the tine
whenever the key is up and the pedal isn't down (the key's damped system, `Key.damped`:
switching systems carries the physical state across). A voice that has died away (its
tip's amplitude bound under `SLEEP_M`) sleeps until struck again. The arc's quadratic
forms are taken to the modes once (`_Forms`), so a free sample costs m^2, not the tine's
quadrature points times m.

**The wiring** (the manual's Fig. 10-4, the 73-key piano): pickups 1-4 (keys 8-11) in
parallel, then groups of three in parallel, the 24 groups in series. With equal coils a
group's open-circuit voltage is its pickups' mean, so the harp's is the sum over keys of
each EMF over its group's size; the coils' resistance and inductance are the circuit's
(`config/circuits/rhodes_stage_5e3.yaml`, `harp_r_ohm`, `harp_l_h`). Every pickup's EMF
adds in phase (the alternating groups reverse coil and magnet together: hum cancels, the
tines don't; provisional, Shear's p.9 names the hum only).

**Velocity** (`hammer_speed`): MIDI velocity to the hammer's speed, `v_ff 10^(-range_db /
20 (127 - vel) / 126)`, `v_ff` set so the 73's lowest key at 127 swings its tip
`ff_swing_m` (provisional; config `velocity`).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field

import numpy as np
from scipy import optimize, signal

from varimu.rhodes import key as ky
from varimu.rhodes import pickup as pk
from varimu.rhodes import spec
from varimu.rhodes.midi import Event

SLEEP_M = 1e-9  # a voice whose tip's amplitude bound falls under this sleeps
CHUNK = 8192
CONTACT_WINDOW_S = 0.03
MIDI_KEY_OFFSET = 20  # MIDI 21 (A0) is key 1


def group_size(n: int) -> int:
    """The size of key n's pickup group (Fig. 10-4: pickups 1-4 a group of four)."""
    p = n - 7
    if not 1 <= p <= 73:
        raise ValueError(f"key {n} isn't on the 73-key harp")
    return 4 if p <= 4 else 3


@dataclass
class _Forms:
    """A system's outputs over its complex modal state z: the tip's displacement and
    velocity rows, and the arc's quadratic forms (arc = 1/4 Re(z'Az) + 1/4 Re(z^H B z),
    arc rate = 1/2 Re(z'Cz) + 1/2 Re(z^H D z))."""

    tip: np.ndarray
    tip_v: np.ndarray
    a: np.ndarray
    b: np.ndarray
    c: np.ndarray
    d: np.ndarray
    lam: np.ndarray

    @classmethod
    def of(cls, s: ky._System) -> _Forms:
        q, qd, w = s.q_map, s.qd_map, s.w[:, None]
        return cls(
            s.c_tip,
            s.c_tip_v,
            q.T @ (w * q),
            q.conj().T @ (w * q),
            q.T @ (w * qd),
            q.conj().T @ (w * qd),
            s.lam,
        )

    def outputs(self, z: np.ndarray) -> tuple[np.ndarray, ...]:
        """z: (m, N) states -> the tip's displacement, velocity, the arc and its rate."""
        tip = np.real(self.tip @ z)
        tip_v = np.real(self.tip_v @ z)
        zc = z.conj()
        arc = 0.25 * np.real(np.sum(z * (self.a @ z) + zc * (self.b @ z), axis=0))
        arc_v = 0.5 * np.real(np.sum(z * (self.c @ z) + zc * (self.d @ z), axis=0))
        return tip, tip_v, arc, arc_v


@dataclass
class Voice:
    """One key over a timeline, adding its weighted EMF into `out` (at fs x oversample)."""

    k: spec.Key
    flux: pk.FluxMap
    out: np.ndarray
    fs_hz: float
    oversample: int = 4
    step_oversample: int = 4
    weight: float = 1.0
    voicing_m: float | None = None
    n: int = 0  # the sample (of `out`) the state is at
    contacts: list = field(default_factory=list)

    def __post_init__(self):
        self.free = ky._System(self.k, "modes")
        self.damp = ky._System(self.k, "modes", self.k.damped)
        self.forms = {id(self.free): _Forms.of(self.free), id(self.damp): _Forms.of(self.damp)}
        self.h = 1.0 / (self.fs_hz * self.step_oversample)
        self.every = self.step_oversample // self.oversample
        self.stepper = ky.stepper(self.free, self.h, True)
        self.sys = self.damp
        self.z = np.zeros(self.damp.lam.size, complex)
        self.asleep = True
        self.voicing = self.k.pickup.voicing_m if self.voicing_m is None else self.voicing_m

    def _emf(self, tip, tip_v, arc, arc_v) -> np.ndarray:
        lo, hi = self.flux.y_range_m
        y = np.clip(self.voicing + tip, lo, hi)
        arc = np.clip(arc, self.flux.dg_m[0], self.flux.dg_m[-1])
        return -(self.flux(y, arc, dy=1) * tip_v + self.flux(y, arc, ddg=1) * arc_v)

    def _rotations(self, f: _Forms) -> np.ndarray:
        """exp(lambda t) for t = 1..CHUNK samples (once per system: the step is fixed)."""
        if not hasattr(f, "rot"):
            dt = 1.0 / (self.fs_hz * self.oversample)
            f.rot = np.exp(np.outer(f.lam, dt * np.arange(1, CHUNK + 1)))
        return f.rot

    def _switch(self, sysm: ky._System) -> None:
        if sysm is not self.sys:
            if not self.asleep:
                x = self.sys.to_phys @ self.z
                self.z = sysm.from_phys @ x
            else:
                self.z = np.zeros(sysm.lam.size, complex)
            self.sys = sysm

    def advance_to(self, n_end: int) -> None:
        """The free motion from the state's sample to n_end."""
        n_end = min(n_end, self.out.size - 1)
        if n_end <= self.n:
            return
        if self.asleep:
            self.n = n_end
            return
        f = self.forms[id(self.sys)]
        rot = self._rotations(f)
        n = self.n
        while n < n_end:
            m = min(CHUNK, n_end - n)
            z = rot[:, :m] * self.z[:, None]
            self.out[n + 1 : n + 1 + m] += self.weight * self._emf(*f.outputs(z))
            self.z = z[:, -1].copy()
            n += m
            if np.sum(np.abs(f.tip * self.z)) < SLEEP_M:
                self.z[:] = 0
                self.asleep = True
                break
        self.n = n_end

    def strike(self, n: int, speed_m_s: float, n_limit: int) -> None:
        """The key struck at sample n at `speed_m_s` (the damper lifted)."""
        n = max(n, self.n)  # struck again within the last strike's window: at its end
        self.advance_to(n)
        self._switch(self.free)
        self.asleep = False
        n_out = max(
            1, min(int(round(CONTACT_WINDOW_S * self.fs_hz * self.oversample)), n_limit - n)
        )
        n_out = min(n_out, self.out.size - n - 1)
        if n_out <= 0:
            return
        adv, g0, g1 = self.stepper
        self.z, outs, stats = ky.contact(
            self.free, self.k, self.z, speed_m_s, self.h, self.every, n_out, adv, g0, g1
        )
        self.out[n + 1 : n + 1 + n_out] += self.weight * self._emf(*outs)
        self.contacts.append((n, speed_m_s, *stats))
        self.n = n + n_out

    def damper(self, n: int, on: bool) -> None:
        self.advance_to(n)
        self._switch(self.damp if on else self.free)


def _velocity_cache(name: str) -> str:
    cfg_bytes = (spec.RHODES_DIR / f"{name}.yaml").read_bytes()
    return hashlib.sha256(cfg_bytes + str(spec._fits_dir(name)).encode()).hexdigest()[:16]


def ff_speed_m_s(name: str = "mk1", flux: pk.FluxMap | None = None) -> float:
    """The hammer speed at velocity 127: the 73's lowest key's tip swings `ff_swing_m`
    (cached in cache/rhodes/)."""
    path = spec.CACHE_DIR / f"velocity_{_velocity_cache(name)}.json"
    if path.exists():
        return float(json.loads(path.read_text(encoding="utf-8"))["ff_speed_m_s"])
    cfg = spec.load(name)["velocity"]
    k = spec.key(int(cfg["calibration_key"]), name)

    class _NoFlux:
        y_range_m = (-1.0, 1.0)
        dg_m = np.array([0.0, 1.0])

        def __call__(self, y, dg, dy=0, ddg=0):
            return np.zeros_like(y)

    def err(log_v: float) -> float:
        s = ky.strike(k, float(np.exp(log_v)), duration_s=0.12, flux=_NoFlux())
        return float(np.log(np.max(np.abs(s.tip_m)) / cfg["ff_swing_m"]))

    v = float(np.exp(optimize.brentq(err, np.log(0.02), np.log(5.0), xtol=1e-4)))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"ff_speed_m_s": v}), encoding="utf-8")
    return v


def hammer_speed(velocity: int, ff_m_s: float, name: str = "mk1") -> float:
    cfg = spec.load(name)["velocity"]
    return ff_m_s * 10 ** (-cfg["range_db"] / 20 * (127 - velocity) / 126)


@dataclass(frozen=True)
class Render:
    emf_v: np.ndarray  # the harp's open-circuit EMF at fs
    fs_hz: float
    skipped: int  # notes outside the 73 keys
    voices: dict  # key -> Voice
    raw_v: np.ndarray  # the EMF at fs x oversample, before decimation (index 0: rest)


def render(
    events: list[Event],
    duration_s: float,
    fs_hz: float = 96000.0,
    oversample: int = 4,
    name: str = "mk1",
    progress: bool = False,
    step_oversample: int = 4,
) -> Render:
    """The harp's open-circuit EMF for the events (MIDI notes 28-100: the 73 keys). The
    voices run at `oversample` x fs_hz, the hammer's contact at `step_oversample` x fs_hz
    (a multiple of `oversample`)."""
    flux = pk.flux_map(spec.key(49, name).pickup, workers=6)
    ff = ff_speed_m_s(name, flux)
    n_total = int(round(duration_s * fs_hz * oversample)) + 1
    out = np.zeros(n_total)
    voices: dict[int, Voice] = {}
    held: set[int] = set()
    pedal = False
    skipped = 0
    events = sorted(events, key=lambda e: (e.t_s, e.kind != "off"))
    # each note's next event on its key, to cap its contact window
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
        if not 8 <= kn <= 80:
            skipped += e.kind == "on"
            continue
        if kn not in voices:
            voices[kn] = Voice(
                spec.key(kn, name),
                flux,
                out,
                fs_hz,
                oversample,
                step_oversample,
                weight=1.0 / group_size(kn),
            )
            if progress:
                print(f"harp: key {kn} ({len(voices)} voices)", flush=True)
        v = voices[kn]
        if e.kind == "on":
            nxt = next(
                (f.t_s for f in events[i + 1 :] if f.kind != "pedal" and f.note == e.note),
                duration_s,
            )
            held.add(kn)
            v.strike(n, hammer_speed(e.value, ff, name), int(round(nxt * fs_hz * oversample)))
        else:
            held.discard(kn)
            if not pedal:
                v.damper(n, on=True)
    for v in voices.values():
        v.advance_to(n_total)
    emf = signal.resample_poly(out, 1, oversample) if oversample > 1 else out
    return Render(emf, fs_hz, skipped, voices, out)
