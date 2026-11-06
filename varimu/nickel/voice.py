"""One key of the Nickel Organ as one coupled system: its bar, its coil and the coil's dead
twin in a bridge, the tube loop, the lamp, the hammer and the damper
(docs/NICKEL_ORGAN_PLAN.md). The Python reference, offline (the RH1 / D1 pattern).

**The circuit.**

    bridge: the drive line's node A feeds two arms, R_b + the live coil (on the key's bar)
            and R_b + its twin (wound alike on a blocked bar), both to ground; a shunt
            R_sh across A. The sense is the arms' difference, R_b (i_twin - i_live): the
            twin cancels the coil's own (nonlinear, hysteretic) inductance, so only what
            the bar's motion does to the live strip comes through.
    V1a:    12AX7, the sense through the input transformer (1:n_in) on its grid, 100k plate,
            bypassed cathode; Johnson noise at the grid (the transformer's secondary).
    V1b:    12AX7, the same, through 0.01 uF and 1 MOhm; its plate is also the line out.
    SUSTAIN: V1b's 0.01 uF into the audio-taper pot (times the key's voicing trim), then a
            two-section RC ladder onto V3's grid, voiced per key (its dominant pole at 2.5x the
            note, at most 4 kHz), so the fundamental wins the loop.
    V3:     12AU7 driver, 47k plate, bypassed cathode, 0.022 uF into the 6V6GT's 470k leak.
    V2:     6V6GT, triode-connected (a voltage source, so the lamp in series can regulate),
            single-ended class A into the output transformer (n:1, primary inductance,
            a damping resistor across the primary); the secondary through the #327 lamp to A.
            The lamp is the AGC: the drive line's current heats it, its resistance rises and
            the loop's gain falls, with the filament's thermal lag (the bloom).
    POLARIZE: a DC magnetomotive force on every strip (a winding on the yoke, choke-fed).
    The key's contact (a relay) grounds V2's grid while the key is up.

**The magnet** (varimu.nickel.magnet): each strip's magnetic circuit is the strip (length
l_n) and an equivalent gap l_g at the strip's area, so N i + F_bias = H (l_n + l_g) + M l_g.
Jiles-Atherton's dM = chi_e dHe with He = H + alpha M + H_sigma, H_sigma = sigma lambda'(M) /
mu0, sigma = E_n (eps - lambda(M)). Solving for dM divides by 1 - chi_e (alpha + d H_sigma / dM)
+ chi_e l_g / (l_n + l_g), floored at varimu.devices.core's DEN_FLOOR (JA's pole, the same
numerical guard as the transformer cores': a large tension swings nickel's effective field by
kA/m and crossed it). Per step the coil's equation and the magnetization's are
solved together for (di, dM) (they are linear in both given the state): the incremental
inductance and the EMF the motion and the bias's change induce.

**The step.** Fixed step h at `oversample` times 96 kHz:
- the amplifier is solved at its plates from the bridge's currents at the step's start (no
  plate capacitances: a loop delay of one step, 5.2 us at 2x);
- the two coils by the trapezoidal rule, linearly implicit: the drive line's node A as its
  Thevenin equivalent from the 6V6GT's plate, the incremental inductances frozen over the
  step (the coils' arms are stiff, L / R ~ 5 us);
- the lamp, the coupling capacitors and the OT's magnetizing current by forward Euler (time
  constants of milliseconds and longer);
- the bar's modes exactly for the force held over the step (the magnet's at the step's mean
  magnetization, the hammer's felt);
- the hammer by symplectic Euler while it touches (a Hunt-Crossley felt).

This is a prototype's integrator: scalar Python, ~10 s per second of audio per sounding key
at 2x. circuitsim gets a magnetoelastic device when the instrument earns a live tier.
"""

from __future__ import annotations

import functools
import math
import zlib
from dataclasses import dataclass, field

import numpy as np

from varimu.devices.core import DEN_FLOOR, MU0
from varimu.devices.lamp import cp_j_kg_k
from varimu.devices.library import load_device
from varimu.nickel import bar as nbar
from varimu.nickel import magnet
from varimu.nickel import spec as nspec

FS_HZ = 96000.0
K_BOLTZMANN = 1.380649e-23
T_ROOM_K = 300.0
LAMP_T_MAX_K = 3300.0  # the lamp table's end (tungsten melts at 3695 K): a guard, reported


def taper_audio(x: float) -> float:
    """An audio-taper pot's wiper fraction: 10% at half travel, two straight segments."""
    x = min(max(x, 0.0), 1.0)
    return 0.2 * x if x < 0.5 else 0.1 + 1.8 * (x - 0.5)


def _softplus(x: float) -> float:
    return x + math.log1p(math.exp(-x)) if x > 0 else math.log1p(math.exp(x))


@dataclass(frozen=True)
class Triode:
    mu: float
    ex: float
    kg1: float
    kp: float
    kvb: float
    g_perv: float
    g_contact: float
    g_smooth: float

    def ip(self, vgk: float, vpk: float) -> float:
        if vpk <= 0.0:
            return 0.0
        x = self.kp * (1 / self.mu + vgk / math.sqrt(self.kvb + vpk * vpk))
        e1 = vpk / self.kp * _softplus(x)
        return 2.0 / self.kg1 * e1**self.ex if e1 > 0 else 0.0

    def ig(self, vgk: float) -> float:
        x = self.g_smooth * _softplus((vgk - self.g_contact) / self.g_smooth)
        return self.g_perv * x**1.5


@dataclass(frozen=True)
class Pentode:
    mu: float
    ex: float
    kg1: float
    kg2: float
    kp: float
    kvb: float

    def a(self, vg1k: float, vg2k: float) -> float:
        """Ip = a atan(Vpk / kvb): the grids' part."""
        e1 = vg2k / self.kp * _softplus(self.kp * (1 / self.mu + vg1k / vg2k))
        return 2.0 / self.kg1 * e1**self.ex if e1 > 0 else 0.0

    def ig2(self, vg1k: float, vg2k: float) -> float:
        x = vg1k + vg2k / self.mu
        return x**1.5 / self.kg2 if x > 0 else 0.0


@dataclass(frozen=True)
class LampTable:
    """The #327's filament on a uniform temperature grid: R(T), heat out, heat capacity."""

    t0: float
    dt: float
    r: tuple[float, ...]
    loss: tuple[float, ...]
    mc: tuple[float, ...]

    @staticmethod
    def make(ref: str) -> LampTable:
        lamp = load_device(ref)
        t = np.linspace(290.0, 3300.0, 3011)
        return LampTable(
            float(t[0]),
            float(t[1] - t[0]),
            tuple(float(x) for x in lamp.r_ohm(t)),
            tuple(float(x) for x in lamp.p_loss_w(t)),
            tuple(float(x) for x in lamp.mass_kg * cp_j_kg_k(t)[0]),
        )

    def at(self, tk: float) -> tuple[float, float, float]:
        x = (tk - self.t0) / self.dt
        i = min(max(int(x), 0), len(self.r) - 2)
        f = min(max(x - i, 0.0), 1.0)
        g = 1.0 - f
        return (
            g * self.r[i] + f * self.r[i + 1],
            g * self.loss[i] + f * self.loss[i + 1],
            g * self.mc[i] + f * self.mc[i + 1],
        )


@dataclass(frozen=True)
class Params:
    """Everything a voice's step reads, as plain floats."""

    ni: magnet.Nickel
    turns: float
    area_m2: float  # the strip's section
    l_g: float
    l_sigma: float
    r_arm: float  # R_b + DCR
    r_b: float
    e_strip: float
    fb_max: float
    r_shunt: float
    n_in: float
    noise_ohm: float
    b_plus: float
    ra: float
    rk: float
    cc: float
    rg: float
    rk6: float
    r_lad: float
    lad_ratio: float
    lad_max_hz: float
    n_ot: float
    l_m: float
    r_d: float
    r_out: float
    c_out: float
    pre: Triode
    drv: Triode
    drv_ra: float
    drv_rk: float
    drv_cc: float
    rg6: float
    pwr: Pentode
    lamp: LampTable
    hammer_kg: float
    felt_k: float
    felt_p: float
    felt_loss: float
    v_min: float
    v_max: float
    damper_t60: float
    relay_s: float
    polarity: float  # the input transformer's sense (the one that regenerates)


@functools.cache
def params(path: str = str(nspec.ORGAN_FILE)) -> Params:
    d = nspec.load(nspec.Path(path))
    g = functools.partial(nspec.v, d)
    t12 = load_device(g("amp.tubes.preamp"))
    t3 = load_device(g("amp.tubes.driver"))
    dk, dg = t3.plate, t3.grid
    t6 = load_device(g("amp.tubes.power"))
    pk = t12.plate
    gc = t12.grid
    pm = t6.model
    return Params(
        ni=magnet.from_spec(d["nickel"]),
        turns=g("coil.turns"),
        area_m2=g("bar.width_m") * g("strip.thickness_m"),
        l_g=g("coil.gap_eff_m"),
        l_sigma=g("coil.leakage_h"),
        r_arm=g("bridge.arm_ohm") + g("coil.dcr_ohm"),
        r_b=g("bridge.arm_ohm"),
        e_strip=g("strip.youngs_pa"),
        fb_max=g("polarize.mmf_max_a"),
        r_shunt=g("bridge.shunt_ohm"),
        n_in=g("bridge.input_ratio"),
        noise_ohm=g("bridge.input_noise_ohm"),
        b_plus=g("amp.b_plus_v"),
        ra=g("amp.plate_ohm"),
        rk=g("amp.cathode_ohm"),
        cc=g("amp.coupling_f"),
        rg=g("amp.grid_leak_ohm"),
        rk6=g("amp.power_cathode_ohm"),
        r_lad=g("amp.drive_ladder_ohm"),
        lad_ratio=g("amp.drive_ladder_pole_ratio"),
        lad_max_hz=g("amp.drive_ladder_pole_max_hz"),
        n_ot=g("amp.ot_ratio"),
        l_m=g("amp.ot_primary_h"),
        r_d=g("amp.ot_damping_ohm"),
        r_out=g("amp.out_load_ohm"),
        c_out=g("amp.out_coupling_f"),
        pre=Triode(pk.mu, pk.ex, pk.kg1, pk.kp, pk.kvb, gc.perveance, gc.contact_v, gc.smooth_v),
        drv=Triode(dk.mu, dk.ex, dk.kg1, dk.kp, dk.kvb, dg.perveance, dg.contact_v, dg.smooth_v),
        drv_ra=g("amp.driver_plate_ohm"),
        drv_rk=g("amp.driver_cathode_ohm"),
        drv_cc=g("amp.driver_coupling_f"),
        rg6=g("amp.power_grid_leak_ohm"),
        pwr=Pentode(pm.mu, pm.ex, pm.kg1, pm.kg2, pm.kp, pm.kvb),
        lamp=LampTable.make(g("amp.tubes.lamp")),
        hammer_kg=g("action.hammer_mass_kg"),
        felt_k=g("action.felt_k"),
        felt_p=g("action.felt_p"),
        felt_loss=g("action.felt_loss_s_per_m"),
        v_min=g("action.v_min_m_s"),
        v_max=g("action.v_max_m_s"),
        damper_t60=g("action.damper_t60_s"),
        relay_s=g("action.relay_s"),
        polarity=g("bridge.polarity"),
    )


def _idle_triode(tube: Triode, b_plus: float, ra: float, rk: float) -> tuple[float, float]:
    """(Vk, Vp) of a resistance-coupled triode stage at idle (grid at 0 V)."""
    vk = 1.0
    for _ in range(200):
        # Vp from the plate line for this Vk, then Vk from the cathode current
        lo, hi = vk, b_plus
        for _ in range(80):
            vp = 0.5 * (lo + hi)
            if (b_plus - vp) / ra > tube.ip(-vk, vp - vk):
                lo = vp
            else:
                hi = vp
        vk_new = tube.ip(-vk, vp - vk) * rk
        if abs(vk_new - vk) < 1e-12:
            break
        vk = 0.5 * (vk + vk_new)
    return vk, vp


def _idle_power(p: Params) -> tuple[float, float]:
    """(Vk, I) of the triode-connected 6V6GT at idle: plate and screen at B+ through the
    OT's primary, I their sum (the primary's current)."""
    vk = 15.0
    for _ in range(500):
        vg2k = p.b_plus - vk
        i = p.pwr.a(-vk, vg2k) * math.atan(vg2k / p.pwr.kvb) + p.pwr.ig2(-vk, vg2k)
        vk_new = i * p.rk6
        if abs(vk_new - vk) < 1e-12:
            break
        vk = 0.5 * (vk + vk_new)
    return vk, i


def _mode_step(omega: float, sigma: float, h: float) -> tuple[float, ...]:
    """Exact step of q'' + 2 sigma q' + omega^2 q = f with f held: (a11, a12, a21, a22, b1, b2)."""
    wd = math.sqrt(max(omega * omega - sigma * sigma, 1e-12))
    e = math.exp(-sigma * h)
    c, s = math.cos(wd * h), math.sin(wd * h)
    a11 = e * (c + sigma / wd * s)
    a12 = e * s / wd
    a21 = -e * omega * omega / wd * s
    a22 = e * (c - sigma / wd * s)
    w2 = omega * omega
    b1 = (1 - a11) / w2
    b2 = -a21 / w2
    return a11, a12, a21, a22, b1, b2


@dataclass
class Voice:
    """One key: its bar and loop, with state that persists between notes (the strip's
    magnetization remembers)."""

    note: int
    p: Params
    bar: nbar.Bar
    oversample: int = 2
    trim: float = 1.0  # the key's voicing trim (the wiper's share past SUSTAIN)
    seed: int = 1
    noise: bool = True
    # state
    q: list[float] = field(default_factory=list)
    v: list[float] = field(default_factory=list)
    i1: float = 0.0
    i2: float = 0.0
    m1: float = 0.0
    m2: float = 0.0
    d1: float = 1.0
    d2: float = 1.0
    fb: float = 0.0
    vp1: float = 0.0
    uc1: float = 0.0
    vp2: float = 0.0
    uc2: float = 0.0
    vp6: float = 0.0
    im: float = 0.0
    tl: float = T_ROOM_K
    uco: float = 0.0
    la: float = 0.0
    vp3: float = 0.0
    uc3: float = 0.0
    lb: float = 0.0
    hammer: bool = False
    xh: float = 0.0
    vh: float = 0.0
    loop_closed: bool = False
    damper: bool = True
    relay_count: int = -1  # steps until the key's contact closes the loop (-1: not pending)
    steps_done: int = 0
    peak_stress_pa: float = 0.0

    def __post_init__(self):
        p = self.p
        self.h = 1.0 / (FS_HZ * self.oversample)
        self.l_n = self.bar.design.strip_m
        self.l_tot = self.l_n + p.l_g
        self.vk1, vp_idle = _idle_triode(p.pre, p.b_plus, p.ra, p.rk)
        f_pole = min(p.lad_ratio * float(self.bar.freq_hz[0]), p.lad_max_hz)
        self.c_lad = 0.382 / (2 * math.pi * p.r_lad * f_pole)
        self.vk3, self.vp3 = _idle_triode(p.drv, p.b_plus, p.drv_ra, p.drv_rk)
        self.uc3 = self.vp3
        self.vk6, ip6 = _idle_power(p)
        self.vp1 = self.vp2 = vp_idle
        self.uc1 = self.uc2 = vp_idle
        self.vp6 = p.b_plus
        self.im = ip6
        self.vp_idle = vp_idle
        self.uco = 0.0
        nm = len(self.bar.freq_hz)
        self.q = [0.0] * nm
        self.v = [0.0] * nm
        om = 2 * math.pi * self.bar.freq_hz
        # the damper: a dashpot at its point whose fundamental's t60 is damper_t60
        sig_d1 = math.log(1000.0) / p.damper_t60
        c_d = 2 * sig_d1 / self.bar.phi_damper[0] ** 2
        self.steps_free = [_mode_step(om[k], self.bar.sigma_per_s[k], self.h) for k in range(nm)]
        sig_damped = self.bar.sigma_per_s + 0.5 * c_d * self.bar.phi_damper**2
        self.steps_damped = [_mode_step(om[k], sig_damped[k], self.h) for k in range(nm)]
        name = f"nickel key {self.note}".encode()
        self.rng = np.random.default_rng([self.seed, zlib.crc32(name)])

    # --- events ---

    def strike(self, velocity: int) -> None:
        p = self.p
        x = (min(max(velocity, 1), 127) - 1) / 126.0
        v0 = p.v_min * (p.v_max / p.v_min) ** x  # velocity on a log scale of hammer speed
        ws = sum(f * q for f, q in zip(self.bar.phi_strike, self.q, strict=True))
        self.hammer, self.xh, self.vh = True, ws, v0
        self.damper = False
        self.relay_count = int(round(self.p.relay_s / self.h))

    def release(self) -> None:
        self.loop_closed = False
        self.damper = True
        self.relay_count = -1

    # --- the run ---

    def run(self, n_out: int, sustain: float, polarize: float, ramp_s: float = 0.0) -> np.ndarray:
        """n_out samples at 96 kHz of the line out (V1b's plate, AC, volts). POLARIZE moves
        from its present MMF to the knob's over ramp_s (0: at once)."""
        p, bar = self.p, self.bar
        h = self.h
        os_ = self.oversample
        n = n_out * os_
        out = np.empty(n_out)
        pr_sense = np.empty(n_out)
        pr_drive = np.empty(n_out)
        pr_tip = np.empty(n_out)
        pr_lamp = np.empty(n_out)
        pr_m = np.empty(n_out)
        pht = [float(x) for x in bar.phi_tip]
        nm = len(self.q)
        q, v = self.q, self.v
        s_k = [float(x) for x in bar.s_strip]
        phs = [float(x) for x in bar.phi_strike]
        steps = self.steps_damped if self.damper else self.steps_free
        ni = p.ni
        ms2 = ni.ms * ni.ms
        lam_s, alpha = ni.lambda_s, ni.alpha
        ddlam = 2.0 * lam_s / ms2
        e_s = p.e_strip
        e_v = e_s * self.bar.strip_volume_m3
        nt, ar = p.turns, p.area_m2
        nam = nt * ar * MU0
        l_n, l_g, l_tot = self.l_n, p.l_g, self.l_tot
        lsig = p.l_sigma
        r1 = p.r_arm
        r2 = p.r_arm
        rb = p.r_b
        rsh = p.r_shunt
        n_ot = p.n_ot
        bp = p.b_plus
        ra, cc, rg = p.ra, p.cc, p.rg
        pre, pwr = p.pre, p.pwr
        vk1, vk6 = self.vk1, self.vk6
        g_wiper = taper_audio(sustain) * self.trim
        fb_target = polarize * p.fb_max
        n_ramp = max(1, int(round(ramp_s / h)))
        fb_rate = (fb_target - self.fb) / (n_ramp * h)
        pol_nin = p.polarity * p.n_in
        if self.noise:
            sd = math.sqrt(4 * K_BOLTZMANN * T_ROOM_K * p.noise_ohm * 0.5 / h)
            noise = (self.rng.standard_normal(n) * sd).tolist()
        else:
            noise = [0.0] * n
        lamp = p.lamp
        k_lad = h / (p.r_lad * self.c_lad)
        la, lb = self.la, self.lb
        drv, vk3, vp3, uc3 = p.drv, self.vk3, self.vp3, self.uc3
        a_hammer = (p.felt_k, p.felt_p, p.felt_loss, p.hammer_kg)

        i1, i2, m1, m2, d1, d2 = self.i1, self.i2, self.m1, self.m2, self.d1, self.d2
        fb = self.fb
        vp1, uc1, vp2, uc2, vp6, im, tl, uco = (
            self.vp1, self.uc1, self.vp2, self.uc2, self.vp6, self.im, self.tl, self.uco,
        )  # fmt: skip
        hammer, xh, vh = self.hammer, self.xh, self.vh
        loop_closed = self.loop_closed
        relay = self.relay_count
        peak = self.peak_stress_pa
        idle = self.vp_idle

        for j in range(n):
            # --- POLARIZE's ramp
            if j < n_ramp and fb_rate != 0.0:
                fb += fb_rate * h
                fbd = fb_rate
            else:
                fb = fb_target if fb_rate != 0.0 else fb
                fbd = 0.0
            # --- the bar's strain at the strip
            eps = 0.0
            epsd = 0.0
            for k in range(nm):
                eps += s_k[k] * q[k]
                epsd += s_k[k] * v[k]
            # --- the amplifier, from the bridge at the step's start
            vg1 = pol_nin * rb * (i2 - i1) + noise[j]
            # V1a: (B+ - vp)/Ra = Ip + (vp - uc1)/Rg + Ig(vp - uc1 - vk1)
            for _ in range(2):
                vgn = vp1 - uc1
                f0 = (bp - vp1) / ra - pre.ip(vg1 - vk1, vp1 - vk1) - vgn / rg - pre.ig(vgn - vk1)
                dv = 1e-3
                vgn2 = vgn + dv
                f1 = (bp - vp1 - dv) / ra - pre.ip(vg1 - vk1, vp1 + dv - vk1) - vgn2 / rg
                f1 -= pre.ig(vgn2 - vk1)
                vp1 -= f0 * dv / (f1 - f0)
            vgn = vp1 - uc1
            ic1 = vgn / rg + pre.ig(vgn - vk1)
            uc1 += h * ic1 / cc
            # V1b: its grid vgn; plate into 0.022 uF and the SUSTAIN pot (1 MOhm)
            for _ in range(2):
                f0 = (bp - vp2) / ra - pre.ip(vgn - vk1, vp2 - vk1) - (vp2 - uc2) / rg
                dv = 1e-3
                f1 = (bp - vp2 - dv) / ra - pre.ip(vgn - vk1, vp2 + dv - vk1)
                f1 -= (vp2 + dv - uc2) / rg
                vp2 -= f0 * dv / (f1 - f0)
            vtop = vp2 - uc2
            uc2 += h * (vtop / rg) / cc
            # the line out
            vo = vp2 - idle - uco
            uco += h * (vo / p.r_out) / p.c_out
            # the key's contact
            if relay >= 0:
                relay -= 1
                if relay < 0:
                    loop_closed = True
            vw = g_wiper * vtop if loop_closed else 0.0
            # the drive ladder (two R-C sections) onto the 6V6GT's grid
            ia_ = (vw - la) * k_lad
            ib_ = (la - lb) * k_lad
            la += ia_ - ib_
            lb += ib_
            # V3, the 12AU7 driver: its plate into 0.01 uF and the 6V6GT's grid leak
            for _ in range(2):
                f0 = (bp - vp3) / p.drv_ra - drv.ip(lb - vk3, vp3 - vk3) - (vp3 - uc3) / p.rg6
                f1 = (bp - vp3 - 1e-3) / p.drv_ra - drv.ip(lb - vk3, vp3 + 1e-3 - vk3)
                f1 -= (vp3 + 1e-3 - uc3) / p.rg6
                vp3 -= f0 * 1e-3 / (f1 - f0)
            vg6 = vp3 - uc3
            uc3 += h * (vg6 / p.rg6) / p.drv_cc
            # V2 and the OT: Ip(vp) = Im + i_lamp / n + (B+ - vp) / R_d
            i12 = i1 + i2
            rl, loss, mc = lamp.at(tl)
            rls = rl + rsh
            # triode-connected: the screen on the plate, both currents through the primary
            vg1k6 = vg6 - vk6
            for _ in range(3):
                vpk = vp6 - vk6
                ip0 = pwr.a(vg1k6, vpk) * math.atan(vpk / pwr.kvb) + pwr.ig2(vg1k6, vpk)
                vpk2 = vpk + 1e-3
                ip1 = pwr.a(vg1k6, vpk2) * math.atan(vpk2 / pwr.kvb) + pwr.ig2(vg1k6, vpk2)
                gp = (ip1 - ip0) * 1e3
                il = ((bp - vp6) / n_ot + rsh * i12) / rls
                f0 = ip0 - im - il / n_ot - (bp - vp6) / p.r_d
                gg = gp + 1.0 / (n_ot * n_ot * rls) + 1.0 / p.r_d
                vp6 -= f0 / gg
            vs = (bp - vp6) / n_ot
            il = (vs + rsh * i12) / rls
            va = vs - rl * il
            dvs = -(rsh / (n_ot * rls * gg)) / n_ot
            zz = 0.5 * (dvs - rl * (dvs + rsh) / rls)  # half dvA / di12
            # --- the two coils and their strips (the twin's bar is blocked: eps = 0)
            lam1 = lam_s * m1 * m1 / ms2
            dl1 = ddlam * m1
            sig1 = e_s * (eps - lam1)
            if abs(sig1) > peak:
                peak = abs(sig1)
            he1 = (nt * i1 + fb - m1 * l_g) / l_tot + alpha * m1 + sig1 * dl1 / MU0
            g1 = (sig1 * ddlam - e_s * dl1 * dl1) / MU0
            x1 = fbd / l_tot + e_s * epsd * dl1 / MU0
            lam2 = lam_s * m2 * m2 / ms2
            dl2 = ddlam * m2
            sig2 = -e_s * lam2
            he2 = (nt * i2 + fb - m2 * l_g) / l_tot + alpha * m2 + sig2 * dl2 / MU0
            g2 = (sig2 * ddlam - e_s * dl2 * dl2) / MU0
            x2 = fbd / l_tot
            rr1 = va - r1 * i1
            rr2 = va - r2 * i2
            # JA's direction must be the step's own: try the last one, flip it where the
            # step goes the other way, and where neither holds the strip is at a reversal
            # (delta 0: the reversible susceptibility alone)
            t1, t2 = d1, d2
            for _ in range(4):
                chi1 = ni.dm_dhe(he1, m1, t1)
                den = max(1.0 - chi1 * (alpha + g1) + chi1 * l_g / l_tot, DEN_FLOOR)
                ca1 = chi1 * nt / (l_tot * den)
                c01 = chi1 * x1 / den
                chi2 = ni.dm_dhe(he2, m2, t2)
                den = max(1.0 - chi2 * (alpha + g2) + chi2 * l_g / l_tot, DEN_FLOOR)
                ca2 = chi2 * nt / (l_tot * den)
                c02 = chi2 * x2 / den
                # trapezoid, node A linear in i1 + i2
                a1 = (lsig + nam * (nt / l_tot + ca1 * l_n / l_tot)) / h + 0.5 * r1
                a2 = (lsig + nam * (nt / l_tot + ca2 * l_n / l_tot)) / h + 0.5 * r2
                b1 = rr1 - nam * (fbd / l_tot + c01 * l_n / l_tot)
                b2 = rr2 - nam * (fbd / l_tot + c02 * l_n / l_tot)
                det = a1 * a2 - zz * (a1 + a2)
                di1 = (b1 * (a2 - zz) + zz * b2) / det
                di2 = (b2 * (a1 - zz) + zz * b1) / det
                dm1 = ca1 * di1 + c01 * h
                dm2 = ca2 * di2 + c02 * h
                ok1 = t1 == 0.0 or dm1 * t1 >= 0.0
                ok2 = t2 == 0.0 or dm2 * t2 >= 0.0
                if ok1 and ok2:
                    break
                if not ok1:
                    t1 = -t1 if t1 == d1 else 0.0
                if not ok2:
                    t2 = -t2 if t2 == d2 else 0.0
            if t1 != 0.0:
                d1 = t1
            if t2 != 0.0:
                d2 = t2
            m1_old = m1
            m1 += dm1
            m2 += dm2
            i1 += di1
            i2 += di2
            # --- the lamp, the OT's magnetizing current
            tl = min(tl + h * (rl * il * il - loss) / mc, LAMP_T_MAX_K)
            im += h * n_ot * vs / p.l_m
            # --- the bar
            mm = 0.5 * (m1 + m1_old)
            fmag = e_v * lam_s * mm * mm / ms2
            fc = 0.0
            if hammer:
                ws = 0.0
                wv = 0.0
                for k in range(nm):
                    ws += phs[k] * q[k]
                    wv += phs[k] * v[k]
                dl = xh - ws
                if dl > 0.0:
                    fc = a_hammer[0] * dl ** a_hammer[1] * max(0.0, 1.0 + a_hammer[2] * (vh - wv))
                elif vh < wv:
                    hammer = False  # it has left the bar
                vh -= h * fc / a_hammer[3]
                xh += h * vh
            for k in range(nm):
                a11, a12, a21, a22, b1, b2 = steps[k]
                f = s_k[k] * fmag + phs[k] * fc
                qk, vk = q[k], v[k]
                q[k] = a11 * qk + a12 * vk + b1 * f
                v[k] = a21 * qk + a22 * vk + b2 * f
            if (j + 1) % os_ == 0:
                jo = j // os_
                out[jo] = vo
                pr_sense[jo] = rb * (i2 - i1)
                pr_drive[jo] = il
                pr_lamp[jo] = tl
                pr_m[jo] = m1
                w = 0.0
                for k in range(nm):
                    w += pht[k] * q[k]
                pr_tip[jo] = w

        self.i1, self.i2, self.m1, self.m2, self.d1, self.d2 = i1, i2, m1, m2, d1, d2
        self.fb = fb
        self.vp1, self.uc1, self.vp2, self.uc2, self.vp6, self.im, self.tl, self.uco = (
            vp1, uc1, vp2, uc2, vp6, im, tl, uco,
        )  # fmt: skip
        self.hammer, self.xh, self.vh = hammer, xh, vh
        self.la, self.lb = la, lb
        self.vp3, self.uc3 = vp3, uc3
        self.loop_closed = loop_closed
        self.relay_count = relay
        self.peak_stress_pa = peak
        self.steps_done += n
        self.probe = {
            "sense_v": pr_sense,
            "drive_a": pr_drive,
            "tip_m": pr_tip,
            "lamp_k": pr_lamp,
            "m_a_per_m": pr_m,
        }
        return out

    def tip_m(self) -> float:
        return float(sum(f * x for f, x in zip(self.bar.phi_tip, self.q, strict=True)))


def make_voice(note: int, d: dict | None = None, **kw) -> Voice:
    d = d or nspec.load()
    a4 = nspec.v(d, "tuning.a4_hz")
    f = a4 * 2 ** ((note - 69) / 12)
    return Voice(note, params(), nbar.build(d, f), **kw)
