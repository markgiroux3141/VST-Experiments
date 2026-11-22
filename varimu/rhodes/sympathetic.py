"""Sympathetic resonance: the keys coupled through the tone bar rail, played live
(docs/RHODES_IMPERFECTION_PLAN.md, "Sympathetic resonance"). This module is the reference;
circuitsim's `harp.rs` (a coupled medium: `keyed.rs`'s two phases) is the port, and
`varimu/rhodes/compile.py` puts the rail's data in the compiled harp (`rail_data`,
`key_rail`).

**The mechanism** is `varimu/rhodes/rail.py`'s (its docstring: every tone bar assembly hangs on
two grommets on a plywood rail; a struck key's grommet force moves the rail, the rail's motion
moves every key's block through its grommets), with the live tier's split of each key's motion:

- **its own** (`z`): struck by its hammer, free or under its felt, exactly as `harp.Voice`
  plays it; its grommets push on the rail (`mount . z`);
- **the rail's** (`zs`): the same key's modes driven by the rail, **relative to the rail**:
  the assembly's motion less the rail's height u under it, driven by the rail's acceleration
  (`base`: a force `-M r amount u''` on every node, r the rigid translation; exact where only
  the grommets resist a rigid translation, as in the free assembly: `K r = k_g g`,
  `C r = c_g g` to 1e-13), only while the key's felt is off (held, or the pedal down: a
  damped tine moves with the rail, its own motion only); carried through the damper's
  switches as `z` is, never under the hammer's contact.

The pickup reads the two summed (its map isn't linear), **riding with the rail** (the harp's
pickup rail and tone bar rail one frame): a key that only moves with the rail adds nothing.
With the pickups still (absolute motion: the first version, 2026-11-22), the rail's low modes
moved every block alike and every pickup read the same 36 Hz bounce, in phase across the 73
keys: 15 dB under the whole of a pedalled chord, most of the "sympathy" (the keys' own rings
summed only to -31 dB). Weak coupling: the rail is driven by
the keys' own motion only (the rail-driven motion's push back is second order), so the rail
is computed from every key's force, then every key's response to it: one chunk in two phases
live, three passes here (`render`). **A key doesn't feel its own push** (the rail's motion
under it less its own force's part): in a two-way coupling that self-term is a small detuning
and damping of its modes by the rail's driving-point mobility, but one way it drives the key
at its own resonance and grows for as long as the key rings (found 2026-11-22: the sympathetic
part came out 13 dB under the whole of a pedalled chord; likely also the offline study's
thump in the wrong register, not checked). That detuning isn't modelled.

The rail's modes are a simply supported plank's (`RAIL`), stepped exactly (`osc_zoh`, a zero-
order hold of the force per sample) with one sample of latency each way (the force at a sample
moves the rail from the next, the rail at a sample drives the keys from the next).

**The amount** (the panel's SYMPATHY) scales the rail's push on the keys: 1 the compiled rail,
up to `SYMPATHETIC_MAX` for effect (one-way coupling: always stable, but past a few it is no
longer a physical rail). The rail is all provisional (rail.py; its offline study's thump didn't
match the real piano's register pattern: the plan's table), so 1 is a stand-in, not data.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace

import numpy as np
from scipy import signal

from varimu.rhodes import beam as bm
from varimu.rhodes import harp, spec
from varimu.rhodes import imperfection as imp_
from varimu.rhodes import key as ky
from varimu.rhodes import pickup as pk
from varimu.rhodes import rail as rl
from varimu.rhodes.midi import Event

#: The largest amount (design choice: 30x the compiled rail's coupling, for effect).
SYMPATHETIC_MAX = 30.0
#: The compiled rail: rail.py's plank at its offline study's middle stiffness (EI x4 of a 19 mm
#: plywood plank: its first mode at 36 Hz; x1 swung the rail 0.5 mm under the demo's chords).
#: Provisional: model knowledge (no source gives the rail's section or its mounting).
RAIL = rl.Rail(youngs_pa=4 * rl.Rail().youngs_pa)
#: A rail mode whose displacement and velocity fall under this (m, m/s) is zeroed (numerical:
#: it keeps the decaying rail out of the subnormal floats; far under anything a key hears).
RAIL_FLOOR = 1e-20


def check(amount: float, model: dict) -> None:
    """An IR's sympathetic amount against its compiled harp."""
    if not (isinstance(amount, (int, float)) and math.isfinite(amount)):
        raise ValueError(f"amount {amount!r}: a number")
    if not 0.0 <= amount <= SYMPATHETIC_MAX:
        raise ValueError(f"amount {amount}: in [0, {SYMPATHETIC_MAX}]")
    if "rail" not in model or any("rail" not in k for k in model["keys"]):
        raise ValueError("the compiled harp has no rail (MK1_HARP@3 or later)")


def osc_zoh(w: float, zeta: float, dt: float) -> tuple[tuple[float, ...], tuple[float, ...]]:
    """A mode q'' + 2 zeta w q' + w^2 q = d (d the modal force per modal mass) stepped exactly
    over dt with d held: (q, q') <- Ad (q, q') + Bd d; Ad row-major. The same arithmetic as
    circuitsim's `harp::osc_zoh`."""
    s = zeta * w
    wd = w * math.sqrt(1.0 - zeta * zeta)
    e = math.exp(-s * dt)
    c = math.cos(wd * dt)
    sn = math.sin(wd * dt)
    half = math.sin(0.5 * wd * dt)
    ad = (e * (c + s / wd * sn), e * sn / wd, -w * w * e * sn / wd, e * (c - s / wd * sn))
    # 1 - e (c + s / wd sn), without the cancellation at small w dt
    one_minus = -math.expm1(-s * dt) + e * 2.0 * half * half - e * s / wd * sn
    bd = (one_minus / (w * w), e * sn / wd)
    return ad, bd


@dataclass(frozen=True)
class RailModes:
    modes_hz: np.ndarray
    zeta: float
    phi: dict  # key -> its mass-normalized mode shapes at its place on the rail


def rail_modes(rail: rl.Rail = RAIL, name: str = "mk1") -> RailModes:
    """The plank's modes (rail.py's pass 2: the assemblies' mass of all 73 keys added)."""
    keys = spec.KEYS_73
    added = rail.added_mass_kg
    if added is None:
        added = sum(rl.assembly_mass_kg(spec.key(n, name)) for n in keys)
    mu = rail.mu_kg_m + added / rail.length_m
    f1 = (np.pi / 2) * np.sqrt(rail.ei / mu) / rail.length_m**2
    nm = int(np.floor(np.sqrt(rail.f_max_hz / f1)))
    modes = np.arange(1, nm + 1)
    phi = {
        n: np.sqrt(2 / (mu * rail.length_m))
        * np.sin(modes * np.pi * rl.key_x_m(n, rail) / rail.length_m)
        for n in keys
    }
    return RailModes(f1 * modes**2, rail.zeta, phi)


def key_rows(k: spec.Key, sysm: ky._System, asm: bm.Assembly) -> tuple[np.ndarray, ...]:
    """(mount_d, mount_v, base) over a system's full modal state: the grommets' force on the
    rail is Re((mount_d + mount_v) . z) (the springs' part, the dashpots' part), and `base` the
    modes' input of a unit acceleration of the rail under the key (relative coordinates: the
    force -M r on the nodes, so M^-1 of it is -r; r the rigid vertical translation)."""
    fe = bm.assemble(asm, k.element_m)
    n = fe.n
    g = np.zeros(n)
    for xg in asm.grommet_x_m:
        g[0] += 1.0
        g[1] += xg
    r = np.zeros(n)
    r[0] = 1.0
    r[fe.tine_dofs[:, 0]] = 1.0
    if fe.bar_dofs.size:
        r[fe.bar_dofs[:, 0]] = 1.0
    zeros = np.zeros(n)
    mount_d = asm.grommet_k_n_m * np.concatenate([g, zeros]) @ sysm.to_phys
    mount_v = asm.grommet_c_n_s_m * np.concatenate([zeros, g]) @ sysm.to_phys
    base = sysm.from_phys @ np.concatenate([zeros, -r])
    return mount_d, mount_v, base


def key_rail(k: spec.Key, free: ky._System, damp: ky._System, halved: dict) -> dict:
    """A key's rail data for the compiled harp (compile.py): the grommets, and per system the
    rows over its kept modes (`halved[id(system)]`: compile._halve's indices and factors; the
    force rows doubled for pairs as every output, the input not); `phi` is added by the
    compiler (`rail_data`)."""
    out = {
        "grommet_k_n_m": float(k.assembly.grommet_k_n_m),
        "grommet_c_n_s_m": float(k.assembly.grommet_c_n_s_m),
    }
    for what, sysm, asm in (("free", free, k.assembly), ("damped", damp, k.damped)):
        idx, factor = halved[id(sysm)]
        md, mv, b = key_rows(k, sysm, asm)
        out[what] = {
            "mount": _c(md[idx] * factor),
            "mount_v": _c(mv[idx] * factor),
            "base": _c(b[idx]),
        }
    return out


def rail_data(name: str = "mk1", rail: rl.Rail = RAIL) -> tuple[dict, dict]:
    """The compiled harp's `rail` block and each key's `phi` (key -> list)."""
    rm = rail_modes(rail, name)
    block = {
        "modes_hz": [float(f) for f in rm.modes_hz],
        "zeta": float(rm.zeta),
    }
    return block, {n: [float(v) for v in p] for n, p in rm.phi.items()}


def _c(v: np.ndarray) -> dict:
    v = np.asarray(v, complex)
    return {"re": v.real.ravel().tolist(), "im": v.imag.ravel().tolist()}


# --- The reference ------------------------------------------------------------------


class Voice(harp.Voice):
    """A harp voice whose motion is its own (`z`) plus the rail's (`zs`, relative to the
    rail): it records its grommets' force on the rail (`force_out`, from `z` only) and feels the
    rail (`base`, per sample of `out`: amount u'', applied while its felt is off). Both
    optional."""

    force_out: np.ndarray | None = None
    base: np.ndarray | None = None

    def setup(self, force_out: np.ndarray | None, base: np.ndarray | None) -> None:
        self.force_out, self.base = force_out, base
        r = self.draws.ratio
        md, mv, b = key_rows(self.k, self.free, self.k.assembly)
        mdd, mvd, _ = key_rows(self.k, self.damp, self.k.damped)
        self.mount = {id(self.free): md + r * mv, id(self.damp): mdd + r * mvd}
        f = self.forms[id(self.free)]
        a = self._rotations(f)[:, 0]
        self.a_free = a
        self.gz = (b * (1.0 / r)) * (a - 1.0) / f.lam
        self.zs = np.zeros(self.sys.lam.size, complex)

    def _switch(self, sysm: ky._System) -> None:
        if sysm is not self.sys and self.base is not None:
            self.zs = sysm.from_phys @ (self.sys.to_phys @ self.zs)
        super()._switch(sysm)

    def _driven(self, zs0: np.ndarray, rot: np.ndarray, n: int, m: int) -> np.ndarray:
        """The rail's motion over samples n+1 .. n+m from zs0 (on the free system: driven)."""
        zs = rot[:, :m] * zs0[:, None]
        if self.sys is self.free:
            seg = self.base[n : n + m]
            if np.any(seg):
                seg = seg.astype(complex)
                for j in range(zs.shape[0]):
                    zs[j] += signal.lfilter([self.gz[j]], [1.0, -self.a_free[j]], seg)
        return zs

    def advance_to(self, n_end: int) -> None:
        n_end = min(n_end, self.out.size - 1)
        if n_end <= self.n:
            return
        if self.asleep and self.base is None:
            self.n = n_end
            return
        f = self.forms[id(self.sys)]
        rot = self._rotations(f)
        mount = self.mount[id(self.sys)]
        n = self.n
        while n < n_end:
            m = min(harp.CHUNK, n_end - n)
            zo = None if self.asleep else rot[:, :m] * self.z[:, None]
            zs = None if self.base is None else self._driven(self.zs, rot, n, m)
            total = zo if zs is None else (zs if zo is None else zo + zs)
            self.out[n + 1 : n + 1 + m] += self.weight * self._emf(*f.outputs(total))
            if zo is not None:
                if self.force_out is not None:
                    self.force_out[n + 1 : n + 1 + m] += np.real(mount @ zo)
                self.z = zo[:, -1].copy()
            if zs is not None:
                self.zs = zs[:, -1].copy()
            n += m
            if zo is not None and np.sum(np.abs(f.tip * self.z)) < harp.SLEEP_M:
                self.z[:] = 0
                self.asleep = True
                if self.base is None:
                    break
        self.n = n_end

    def strike(self, n: int, speed_m_s: float, n_limit: int) -> None:
        n = max(n, self.n)
        self.advance_to(n)
        self._switch(self.free)
        self.asleep = False
        n_out = max(
            1, min(int(round(harp.CONTACT_WINDOW_S * self.fs_hz * self.oversample)), n_limit - n)
        )
        n_out = min(n_out, self.out.size - n - 1)
        if n_out <= 0:
            return
        adv, g0, g1 = self.stepper
        ks, vs = imp_.strike_draws(self.imperfection, self.k.n, self.strikes)
        self.strikes += 1
        k = self.k
        if ks != 1.0:
            k = replace(k, hammer=replace(k.hammer, stiffness=k.hammer.stiffness * ks))
        speed_m_s = speed_m_s * vs
        states: list[np.ndarray] = []
        self.z, _, stats = ky.contact(
            self.free,
            k,
            self.z,
            speed_m_s,
            self.h,
            self.every,
            n_out,
            adv,
            g0,
            g1,
            states_out=states,
        )
        x = np.array(states).T
        f = self.forms[id(self.free)]
        total = x
        if self.base is not None:
            zs = self._driven(self.zs, self._rotations(f), n, n_out)
            self.zs = zs[:, -1].copy()
            total = x + zs
        self.out[n + 1 : n + 1 + n_out] += self.weight * self._emf(*f.outputs(total))
        if self.force_out is not None:
            self.force_out[n + 1 : n + 1 + n_out] += np.real(self.mount[id(self.free)] @ x)
        self.contacts.append((n, speed_m_s, *stats))
        self.n = n + n_out


@dataclass(frozen=True)
class Render:
    emf_v: np.ndarray  # at fs
    raw_v: np.ndarray  # at fs x oversample (index 0: rest)
    rigid_raw_v: np.ndarray  # pass 1: the struck keys on a rigid rail
    fs_hz: float
    forces_n: dict  # key -> its force on the rail (internal rate)
    udd_m_s2: dict  # key -> the rail's acceleration there that it feels (its own push's out)


def _rail_motion(
    drive_all: np.ndarray, ad: np.ndarray, bd: np.ndarray, w2: np.ndarray, c2: np.ndarray
) -> np.ndarray:
    """The rail's modal accelerations ((samples, modes)) from their modal forces per sample
    (each held over the next sample), as circuitsim's rail steps them (`RAIL_FLOOR` included):
    q'' = -w^2 q - 2 zeta w q' + the force held."""
    n_total, nm = drive_all.shape
    qdds = np.zeros((n_total, nm))
    q = np.zeros(nm)
    qd = np.zeros(nm)
    drive = np.zeros(nm)
    for j in range(1, n_total):
        q, qd = (
            ad[0] * q + ad[1] * qd + bd[0] * drive,
            ad[2] * q + ad[3] * qd + bd[1] * drive,
        )
        small = (np.abs(q) < RAIL_FLOOR) & (np.abs(qd) < RAIL_FLOOR)
        q[small] = 0.0
        qd[small] = 0.0
        qdds[j] = -w2 * q - c2 * qd + drive
        drive = drive_all[j]
    return qdds


def _play(events, voices, n_total, oversample, fs_hz, duration_s, ff, name):
    held: set[int] = set()
    pedal = False
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
        kn = e.note - harp.MIDI_KEY_OFFSET
        if kn not in voices:
            continue
        v = voices[kn]
        if e.kind == "on":
            nxt = next(
                (f.t_s for f in events[i + 1 :] if f.kind != "pedal" and f.note == e.note),
                duration_s,
            )
            held.add(kn)
            v.strike(n, harp.hammer_speed(e.value, ff, name), int(round(nxt * fs_hz * oversample)))
        else:
            held.discard(kn)
            if not pedal:
                v.damper(n, on=True)
    for v in voices.values():
        v.advance_to(n_total)


def render(
    events: list[Event],
    duration_s: float,
    amount: float = 1.0,
    fs_hz: float = 96000.0,
    oversample: int = 1,
    step_oversample: int = 4,
    keys=spec.KEYS_73,
    imperfection: imp_.Imperfection | None = None,
    name: str = "mk1",
) -> Render:
    """The harp's EMF with the keys ringing in sympathy (the module docstring): pass 1 the
    struck keys' own motion and their forces on the rail, pass 2 the rail, pass 3 every key in
    `keys` with its own motion and the rail's. `amount` scales the rail's push on the keys."""
    flux = pk.flux_map(spec.key(49, name).pickup, workers=6)
    ff = harp.ff_speed_m_s(name, flux)
    n_total = int(round(duration_s * fs_hz * oversample)) + 1
    keys = sorted(keys)
    struck = sorted({e.note - harp.MIDI_KEY_OFFSET for e in events if e.kind == "on"} & set(keys))
    kspec = {n: spec.key(n, name) for n in keys}

    def voice(n, out):
        return Voice(
            kspec[n],
            flux,
            out,
            fs_hz,
            oversample,
            step_oversample,
            1.0 / harp.group_size(n),
            imperfection=imperfection,
        )

    out1 = np.zeros(n_total)
    forces = {n: np.zeros(n_total) for n in struck}
    v1 = {}
    for n in struck:
        v1[n] = voice(n, out1)
        v1[n].setup(forces[n], None)
    _play(events, v1, n_total, oversample, fs_hz, duration_s, ff, name)

    rm = rail_modes(RAIL, name)
    nm = rm.modes_hz.size
    dt = 1.0 / (fs_hz * oversample)
    zoh = [osc_zoh(2 * np.pi * f, rm.zeta, dt) for f in rm.modes_hz]
    ad = np.array([z[0] for z in zoh]).T  # (4, nm)
    bd = np.array([z[1] for z in zoh]).T  # (2, nm)
    w = 2 * np.pi * rm.modes_hz
    w2, c2 = w * w, 2 * rm.zeta * w
    drive_all = np.zeros((n_total, nm))
    for n in struck:
        drive_all += forces[n][:, None] * rm.phi[n][None, :]
    qdds = _rail_motion(drive_all, ad, bd, w2, c2)
    udd = {n: qdds @ rm.phi[n] for n in keys}
    for n in struck:  # a key doesn't feel its own push (the module docstring)
        qn = _rail_motion(forces[n][:, None] * rm.phi[n][None, :], ad, bd, w2, c2)
        udd[n] = (qdds - qn) @ rm.phi[n]

    out3 = np.zeros(n_total)
    v3 = {}
    for n in keys:
        base = amount * udd[n]
        v3[n] = voice(n, out3)
        v3[n].setup(None, base)
    _play(events, v3, n_total, oversample, fs_hz, duration_s, ff, name)

    def dec(x):
        return signal.resample_poly(x, 1, oversample) if oversample > 1 else x

    return Render(dec(out3), out3, out1, fs_hz, forces, udd)
