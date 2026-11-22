"""The tone bar rail as a coupling between the keys: an offline study
(docs/RHODES_IMPERFECTION_PLAN.md, "Notes depending on each other"; INSTRUMENT_REALISM_FABLE.md
SC5). Nothing here is in the live
instrument or circuitsim.

Every tone bar assembly hangs on two screws through springs / grommets on the tone bar rail, a
plywood plank across the harp (web: https://shadetreekeys.com/category/tines, a restoration: "each
tone bar and tine mounted to the plywood tone bar rail by two long screws ... a spring which
suspends the bar just under a half inch from the rail"). In `beam.py` the grommets go to ground:
the rail is rigid. Here it moves:

- **Each key pushes on the rail** with its grommets' force, `sum_g k_g w_g + c_g w_g'` (w_g the
  block's height at grommet g): a row over its modal state.
- **The rail** is a plank simply supported at the harp's ends, its bending modes driven by every
  key's force at the key's place along it; its motion u at a key is the sum of its modes.
- **Each key feels the rail** through the same grommets: a force `G (k_g u + c_g u')` on its block
  (base excitation), an input over its modal state like the hammer's.

**Weak coupling, three passes** (`render`): (1) the keys as `harp.render` plays them (the rail
rigid), each struck key's force on the rail recorded; (2) the rail's motion at every key from
those forces; (3) every key (struck or not, all 73) played again with its rail motion as a base
excitation. The rail-driven keys' own push back on the rail is left out (second order: their
motion is the rail's, ~1e-6 of a struck tine's), and so is the rail's motion's effect on the
grommets' force in (1) (the struck block moves far more than the rail). The hammer's contact
window (30 ms) of a struck key doesn't feel the rail.

**Values: all provisional** (no source gives the rail's section, its supports or the harp's
mounting): `Rail`'s defaults say what each is. The assemblies' mass rides on the rail at low
frequency (below their own bounce on the grommets, 50-220 Hz by Muenster & Pfeifle's
measurement), so it is added to the plank's (a crude bound: above their bounce they decouple and
the rail is lighter, so moves more).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy import signal

from varimu.rhodes import beam as bm
from varimu.rhodes import harp, spec
from varimu.rhodes import key as ky
from varimu.rhodes import pickup as pk
from varimu.rhodes.midi import Event


@dataclass(frozen=True)
class Rail:
    """A simply supported plank under the keys (all provisional: model knowledge)."""

    length_m: float = 1.0  # the 73 keys' span (~13.7 mm a key)
    youngs_pa: float = 8.0e9  # plywood along its face grain
    density_kg_m3: float = 600.0
    width_m: float = 0.10  # horizontal
    thickness_m: float = 0.019  # 3/4 in, bending vertically
    zeta: float = 0.02  # plywood's loss factor ~0.04
    added_mass_kg: float | None = None  # the assemblies' (None: summed from the keys' FE)
    f_max_hz: float = 4000.0

    @property
    def ei(self) -> float:
        return self.youngs_pa * self.width_m * self.thickness_m**3 / 12

    @property
    def mu_kg_m(self) -> float:
        return self.density_kg_m3 * self.width_m * self.thickness_m


def key_x_m(n: int, rail: Rail) -> float:
    """Key n's place along the rail (keys 8-80 evenly)."""
    return rail.length_m * (n - 8 + 0.5) / 73


def assembly_mass_kg(k: spec.Key) -> float:
    """The tone bar assembly's mass (its rigid vertical translation through the FE's mass)."""
    fe = bm.assemble(k.assembly, k.element_m)
    r = np.zeros(fe.n)
    r[0] = 1.0
    r[fe.tine_dofs[:, 0]] = 1.0
    if fe.bar_dofs.size:
        r[fe.bar_dofs[:, 0]] = 1.0
    return float(r @ fe.m @ r)


def coupling(k: spec.Key, sysm: ky._System, asm: bm.Assembly) -> tuple[np.ndarray, np.ndarray]:
    """(mount, base) for a key's system: the row giving its grommets' force on the rail from
    its modal state, and the modal input of a unit `k_g u + c_g u'` at both grommets."""
    fe = bm.assemble(asm, k.element_m)
    n = fe.n
    g = np.zeros(n)
    for xg in asm.grommet_x_m:
        g[0] += 1.0
        g[1] += xg
    row = np.concatenate([asm.grommet_k_n_m * g, asm.grommet_c_n_s_m * g])
    mount = row @ sysm.to_phys
    base = sysm.from_phys @ np.concatenate([np.zeros(n), np.linalg.solve(fe.m, g)])
    return mount, base


class RailVoice(harp.Voice):
    """A harp voice that records its force on the rail (`force_out`) and feels a base
    excitation (`base`: `k_g u + c_g u'` per sample of `out`), both optional."""

    force_out: np.ndarray | None = None
    base: np.ndarray | None = None

    def setup(self, force_out: np.ndarray | None, base: np.ndarray | None) -> None:
        self.force_out, self.base = force_out, base
        self.rows = {
            id(self.free): coupling(self.k, self.free, self.k.assembly),
            id(self.damp): coupling(self.k, self.damp, self.k.damped),
        }
        if base is not None:
            self.asleep = False  # the rail keeps it moving

    def advance_to(self, n_end: int) -> None:
        n_end = min(n_end, self.out.size - 1)
        if n_end <= self.n:
            return
        if self.asleep:
            self.n = n_end
            return
        f = self.forms[id(self.sys)]
        rot = self._rotations(f)
        mount, base_in = self.rows[id(self.sys)]
        dt = 1.0 / (self.fs_hz * self.oversample)
        a = np.exp(f.lam * dt)
        gz = base_in * (a - 1.0) / f.lam  # a zero-order hold of the base force over a sample
        n = self.n
        while n < n_end:
            m = min(harp.CHUNK, n_end - n)
            z = rot[:, :m] * self.z[:, None]
            if self.base is not None:
                fseg = self.base[n : n + m]
                if np.any(fseg):
                    for j in range(z.shape[0]):
                        z[j] += signal.lfilter([gz[j]], [1.0, -a[j]], fseg.astype(complex))
            self.out[n + 1 : n + 1 + m] += self.weight * self._emf(*f.outputs(z))
            if self.force_out is not None:
                self.force_out[n + 1 : n + 1 + m] += np.real(mount @ z)
            self.z = z[:, -1].copy()
            n += m
            if self.base is None and np.sum(np.abs(f.tip * self.z)) < harp.SLEEP_M:
                self.z[:] = 0
                self.asleep = True
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
        extra: list[np.ndarray] = []
        mount, _ = self.rows[id(self.free)]
        self.z, outs, stats = ky.contact(
            self.free,
            self.k,
            self.z,
            speed_m_s,
            self.h,
            self.every,
            n_out,
            adv,
            g0,
            g1,
            rows=[mount],
            rows_out=extra,
        )
        self.out[n + 1 : n + 1 + n_out] += self.weight * self._emf(*outs)
        if self.force_out is not None:
            self.force_out[n + 1 : n + 1 + n_out] += extra[0]
        self.contacts.append((n, speed_m_s, *stats))
        self.n = n + n_out


@dataclass
class RailRender:
    rigid_v: np.ndarray  # the harp's EMF on a rigid rail (pass 1), at fs
    rail_v: np.ndarray  # on the moving rail (pass 3), at fs
    sympathetic_v: np.ndarray  # the keys never struck, alone (pass 3), at fs
    fs_hz: float
    rail_modes_hz: np.ndarray
    forces_n: dict = field(repr=False)  # key -> its force on the rail (pass 1), internal rate
    u_m: dict = field(repr=False)  # key -> the rail's motion there (pass 2), internal rate


def _play(events, voices, n_total, oversample, fs_hz, duration_s):
    """Drive `voices` (key -> RailVoice) by the events as harp.render does; every voice
    gets the pedal; returns nothing (the voices write their outputs)."""
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
            v.strike(n, harp.hammer_speed(e.value, _FF[0]), int(round(nxt * fs_hz * oversample)))
        else:
            held.discard(kn)
            if not pedal:
                v.damper(n, on=True)
    for v in voices.values():
        v.advance_to(n_total)


_FF = [0.0]


def render(
    events: list[Event],
    duration_s: float,
    rail: Rail | None = None,
    fs_hz: float = 48000.0,
    oversample: int = 2,
    step_oversample: int = 4,
    keys: range = spec.KEYS_73,
    progress: bool = False,
) -> RailRender:
    """The three passes (the module docstring)."""
    rail = rail or Rail()
    flux = pk.flux_map(spec.key(49).pickup, workers=6)
    _FF[0] = harp.ff_speed_m_s("mk1", flux)
    n_total = int(round(duration_s * fs_hz * oversample)) + 1
    struck = {e.note - harp.MIDI_KEY_OFFSET for e in events if e.kind == "on"}
    struck &= set(keys)
    kspec = {n: spec.key(n) for n in keys}

    # pass 1: the struck keys on a rigid rail, their forces recorded
    out1 = np.zeros(n_total)
    forces = {n: np.zeros(n_total) for n in struck}
    v1 = {}
    for n in sorted(struck):
        v = RailVoice(
            kspec[n], flux, out1, fs_hz, oversample, step_oversample, 1.0 / harp.group_size(n)
        )
        v.setup(forces[n], None)
        v1[n] = v
    _play(events, v1, n_total, oversample, fs_hz, duration_s)
    if progress:
        print("rail: pass 1 done", flush=True)

    # pass 2: the rail's modes (mass normalized), driven by the forces, read at every key
    added = rail.added_mass_kg
    if added is None:
        added = sum(assembly_mass_kg(kspec[n]) for n in keys)
    mu = rail.mu_kg_m + added / rail.length_m
    f1 = (np.pi / 2) * np.sqrt(rail.ei / mu) / rail.length_m**2
    nm = int(np.floor(np.sqrt(rail.f_max_hz / f1)))
    f_modes = f1 * np.arange(1, nm + 1) ** 2
    xk = {n: key_x_m(n, rail) for n in keys}
    phi = {
        n: np.sqrt(2 / (mu * rail.length_m))
        * np.sin(np.arange(1, nm + 1) * np.pi * xk[n] / rail.length_m)
        for n in keys
    }
    dt = 1.0 / (fs_hz * oversample)
    q = np.zeros((nm, n_total))
    qd = np.zeros((nm, n_total))
    drive = np.zeros((nm, n_total))
    for n in struck:
        drive += phi[n][:, None] * forces[n][None, :]
    for m in range(nm):
        w = 2 * np.pi * f_modes[m]
        a = np.array([[0.0, 1.0], [-w * w, -2 * rail.zeta * w]])
        b = np.array([[0.0], [1.0]])
        ad, bd, *_ = signal.cont2discrete((a, b, np.eye(2), np.zeros((2, 1))), dt, "zoh")
        x = np.zeros(2)
        # a two-state recursion per mode: lfilter on each output's transfer
        num_q, den = signal.ss2tf(ad, bd, np.array([[1.0, 0.0]]), np.zeros((1, 1)))
        num_v, _ = signal.ss2tf(ad, bd, np.array([[0.0, 1.0]]), np.zeros((1, 1)))
        q[m] = signal.lfilter(num_q[0], den, drive[m])
        qd[m] = signal.lfilter(num_v[0], den, drive[m])
        del x
    u = {n: phi[n] @ q for n in keys}
    ud = {n: phi[n] @ qd for n in keys}
    if progress:
        print(f"rail: pass 2 done ({nm} modes from {f1:.1f} Hz)", flush=True)

    # pass 3: every key on the moving rail (the struck ones into out3, the rest into sym)
    out3 = np.zeros(n_total)
    sym = np.zeros(n_total)
    v3 = {}
    for n in keys:
        asm = kspec[n].assembly
        base = asm.grommet_k_n_m * u[n] + asm.grommet_c_n_s_m * ud[n]
        v = RailVoice(
            kspec[n],
            flux,
            out3 if n in struck else sym,
            fs_hz,
            oversample,
            step_oversample,
            1.0 / harp.group_size(n),
        )
        v.setup(None, base)
        v3[n] = v
    _play(events, v3, n_total, oversample, fs_hz, duration_s)
    if progress:
        print("rail: pass 3 done", flush=True)

    def dec(x):
        return signal.resample_poly(x, 1, oversample) if oversample > 1 else x

    return RailRender(dec(out1), dec(out3 + sym), dec(sym), fs_hz, f_modes, forces, u)
