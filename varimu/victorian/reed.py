"""One key of the Victorian synth: a self-interrupting reed (Gray's Musical Telegraph, 1874-75)
whose second contact chops the line through the carbon under the key
(docs/VICTORIAN_SYNTH_PLAN.md, V1-V2). The Python reference of circuitsim's `reeds` medium
(`crates/circuitsim/src/reeds.rs`), step for step.

**Two circuits per key**, as Gray's local-circuit magnets (US 165,728) and the period's tuning
fork interrupters had them: a local circuit keeps the reed going, the line carries the tone.

    local: loc -- key (down: the battery; up: its back contact, the coil shorted)
               -- coil (R_d: winding and voicing resistance, flux linkage lam)
               -- [drive contact || condenser C_d] -- return
    line:  line -- carbon (R_k(F)) -- [line contact || condenser C_l] -- return

`loc` and `line` are nodes of the circuit, sensed a sample late; the key returns each
circuit's current (the medium's outputs, drawn from those nodes by the circuit's `G` parts).
The local current is a coil's (inductive: the sample's latency costs nothing); the line's is
resistive, so the circuit holds the line node with a condenser.

**The reed.** A steel cantilever, its first two bending modes (`modes`: coordinates q_m
normalized to the tip, each a tip mass m / 4 for a uniform cantilever), driven at one point,
where the magnet's poles and the contacts are: x = sum b_m q_m there (b_m the mode's shape at
the drive point, averaged over the pole face), toward the magnet; a force F there acts on mode
m as b_m F. Each mode is advanced exactly over the step for the force held over it.

**The magnet.** A horseshoe electromagnet, two pole faces of area A at a gap g0 - x each, the
iron's reluctance as an equivalent gap g_c: L(x) = mu0 N^2 A / (2 (g0 - x) + g_c). The state is
the flux linkage lam = L(x) i; the pull is the co-energy's derivative,
F = lam^2 / (mu0 N^2 A) (both faces). Moving the reed at constant lam changes i: the motional
EMF is in the formulation. A brass stop keeps the reed g_min off the poles.

**The contacts.** A light follow spring riveted to the reed carries two insulated platinum
points against two screws on the side away from the magnet (one in each circuit); the spring
rests on a stop on the reed with a preload F_pre. While x < x_c the screws hold the points
(closed) and the spring presses the reed toward the magnet, F_pre + k_s (x_c - x) - c_s v
(never pulling); at x_c the spring reaches its stop and both points lift at once (the Neef /
Wagner hammer's snap). Each point's resistance is Holm's constriction R_c0 (F0 / F)^1/2 plus a
film, at half the spring's force. The drive contact's condenser (Fizeau's, 1853) takes the
coil's current at the break; open, its gap d = x - x_c breaks down when the condenser's voltage
passes V_bd(d) = max(V_arc, min(E_fe d, V_p + E_air max(d - d_p, 0))) (the modified Paschen
curve: field emission below d_p, Paschen's plateau and beyond); the spark then holds the arc's
minimum voltage through R_arc until its current falls below the metal's minimum arc current.
The line contact breaks a resistive circuit at the line's few volts, below any arc: no spark.

**The damper.** With its key up a felt damper rests on the reed (a piano's damper, fitted
by the instrument's builder), adding its loss to every mode: a released reed stops in a few of
its periods instead of ringing on for seconds.

**The carbon under the key.** Granular carbon between the key and the frame:
G_k(F) = G_open + G0 (F / F0)^n. The key presses it through an oil dashpot: the force relaxes
toward its target (velocity's law times aftertouch) with tau_on while held, toward zero with
tau_off when released. The reed is keyed on and off; the carbon shapes the line's level.

**The step** (fixed h at `oversample` x 96 kHz): the local pair (lam, q_d) and the line's q_l by
backward Euler with x held (a closed contact's R_c C is nanoseconds: L-stable); then the pull
from the new lam with the contact's and stop's forces at the step's start move the modes
exactly; then the spark's state; then the dashpot, exactly. The outputs are the two currents,
averaged over the step's internal samples (charge per step).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from varimu.victorian import spec

MU0 = 4e-7 * math.pi
FS_HZ = 96000.0


@dataclass(frozen=True)
class Mode:
    omega: float  # rad/s
    zeta: float
    mass_kg: float  # at the tip
    b: float  # its shape at the drive point (the magnet's and the contacts'), the tip's 1


@dataclass(frozen=True)
class KeyParams:
    """One key's compiled values (`compile.key_params`), everything the step reads."""

    note: int
    f_hz: float  # the reed's first mode
    modes: tuple[Mode, ...]
    # magnet
    turns: float
    area_m2: float  # one pole face
    gap_m: float  # g0, at x = 0
    core_gap_m: float  # g_c
    r_drive_ohm: float  # the coil's winding plus its voicing resistance
    stop_m: float  # x where the stop is hit (g0 - g_min)
    k_stop_n_m: float
    c_stop_ns_m: float
    # contacts
    x_c_m: float
    f_pre_n: float  # the follow spring's preload on its stop on the reed
    k_s_n_m: float
    c_s_ns_m: float
    r_c0_ohm: float
    f_c0_n: float
    r_film_ohm: float
    cond_drive_f: float  # condenser + stray, across the drive contact
    cond_line_f: float  # across the line contact
    v_arc: float
    i_arc_min_a: float
    r_arc_ohm: float
    e_fe_v_m: float
    v_paschen: float
    d_paschen_m: float
    e_air_v_m: float
    # carbon key
    g_open_s: float
    g0_s: float
    f0_n: float
    n_carbon: float
    f_max_n: float
    vel_exp: float
    touch_gain: float
    tau_on_s: float
    tau_off_s: float
    q_damper: float  # each mode's Q with the key up (the felt damper on the reed)


def inductance(p: KeyParams, x: float) -> float:
    return MU0 * p.turns * p.turns * p.area_m2 / (2.0 * (p.gap_m - x) + p.core_gap_m)


def breakdown_v(p: KeyParams, d: float) -> float:
    """The drive gap's breakdown voltage (d >= 0)."""
    paschen = p.v_paschen + p.e_air_v_m * max(d - p.d_paschen_m, 0.0)
    return max(p.v_arc, min(p.e_fe_v_m * d, paschen))


@dataclass
class ModeStep:
    """A damped mode's exact step: [x, v]' = M [x - xs, v] + [xs, 0], xs = F / (m w^2)."""

    a11: float
    a12: float
    a21: float
    a22: float
    inv_k: float  # 1 / (m w^2)


def mode_step(m: Mode, h: float) -> ModeStep:
    w, z = m.omega, m.zeta
    wd = w * math.sqrt(1.0 - z * z)
    e = math.exp(-z * w * h)
    c = math.cos(wd * h)
    s = math.sin(wd * h)
    zw = z * w / wd
    return ModeStep(
        a11=e * (c + zw * s),
        a12=e * s / wd,
        a21=-e * w * w / wd * s,
        a22=e * (c - zw * s),
        inv_k=1.0 / (m.mass_kg * w * w),
    )


def k_drive(p: KeyParams) -> float:
    """The reed's static stiffness at the drive point (its two modes')."""
    s = 0.0
    for m in p.modes:
        s += m.b * m.b / (m.mass_kg * m.omega * m.omega)
    return 1.0 / s


@dataclass
class Key:
    """One key's state, stepped at the internal rate fs_int."""

    p: KeyParams
    fs_int: float
    steps: list[ModeStep] = field(init=False)
    steps_up: list[ModeStep] = field(init=False)
    h: float = field(init=False)
    xs: list[float] = field(init=False)
    vs: list[float] = field(init=False)
    x_rest: list[float] = field(init=False)
    lam: float = 0.0
    qd: float = 0.0
    ql: float = 0.0
    arc: int = 0  # 0, or the spark's sign
    force: float = 0.0  # on the carbon
    target: float = 0.0
    held: bool = False
    velocity: float = 0.0
    pressure: float = 0.0
    sparks: int = 0  # counted ignitions (a readout)
    i_line: float = 0.0  # the last step's line current

    def __post_init__(self) -> None:
        p = self.p
        self.h = 1.0 / self.fs_int
        self.steps = [mode_step(m, self.h) for m in p.modes]
        # The key up: the felt damper on the reed adds its loss to every mode's.
        self.steps_up = [
            mode_step(Mode(m.omega, m.zeta + 0.5 / p.q_damper, m.mass_kg, m.b), self.h)
            for m in p.modes
        ]
        self.xs = [0.0] * len(p.modes)
        self.vs = [0.0] * len(p.modes)
        # At rest on the screws: the follow spring's push against the reed's stiffness.
        k_reed = k_drive(p)
        x0 = (p.f_pre_n + p.k_s_n_m * p.x_c_m) / (k_reed + p.k_s_n_m)
        f0 = k_reed * x0
        for j, st in enumerate(self.steps):
            self.xs[j] = p.modes[j].b * f0 * st.inv_k
        self.x_rest = list(self.xs)
        self.on_k = math.exp(-self.h / p.tau_on_s)
        self.off_k = math.exp(-self.h / p.tau_off_s)

    # --- events -----------------------------------------------------------------------------
    def _retarget(self) -> None:
        p = self.p
        if self.held:
            self.target = (
                p.f_max_n
                * (self.velocity / 127.0) ** p.vel_exp
                * (1.0 + p.touch_gain * self.pressure / 127.0)
            )
        else:
            self.target = 0.0

    def press(self, velocity: int) -> None:
        self.held = True
        self.velocity = float(max(1, min(127, velocity)))
        self._retarget()

    def release(self) -> None:
        self.held = False
        self._retarget()

    def set_pressure(self, value: int) -> None:
        self.pressure = float(max(0, min(127, value)))
        self._retarget()

    # --- state ------------------------------------------------------------------------------
    def x(self) -> float:
        s = 0.0
        for m, q in zip(self.p.modes, self.xs, strict=True):
            s += m.b * q
        return s

    def v(self) -> float:
        s = 0.0
        for m, u in zip(self.p.modes, self.vs, strict=True):
            s += m.b * u
        return s

    def carbon_g(self) -> float:
        p = self.p
        f = self.force
        return p.g_open_s + (p.g0_s * (f / p.f0_n) ** p.n_carbon if f > 0.0 else 0.0)

    def contact_force(self, x: float, v: float) -> float:
        """The follow spring's push on the reed (>= 0, toward the magnet), 0 open."""
        p = self.p
        if x >= p.x_c_m:
            return 0.0
        return max(p.f_pre_n + p.k_s_n_m * (p.x_c_m - x) - p.c_s_ns_m * v, 0.0)

    def energy(self) -> float:
        """The reed's swing's energy (J): its modes' about their rest on the screws."""
        e = 0.0
        for m, st, q, q0, u in zip(
            self.p.modes, self.steps, self.xs, self.x_rest, self.vs, strict=True
        ):
            d = q - q0
            e += 0.5 * m.mass_kg * u * u + 0.5 * d * d / st.inv_k
        return e

    # --- the step ---------------------------------------------------------------------------
    def step(self, v_loc: float, v_line: float) -> tuple[float, float]:
        """One internal step with the local battery at v_loc and the line at v_line; the local
        and line currents at its end."""
        p, h = self.p, self.h
        x = self.x()
        v = self.v()
        ell = inductance(p, x)
        fc = self.contact_force(x, v)
        closed = x < p.x_c_m
        if closed:
            # Each point carries half the spring's force.
            rc = p.r_film_ohm + p.r_c0_ohm * math.sqrt(p.f_c0_n / max(0.5 * fc, 1e-9 * p.f_c0_n))
            g = 1.0 / rc
            j = 0.0
        elif self.arc != 0:
            rc = 0.0
            g = 1.0 / p.r_arc_ohm
            j = self.arc * p.v_arc / p.r_arc_ohm
        else:
            rc = 0.0
            g = 0.0
            j = 0.0
        # The local circuit, backward Euler on
        #   lam' = V - R_d lam / L - q_d / C_d      (V = v_loc with the key down, else 0)
        #   q_d' = lam / L - g q_d / C_d + j
        vd = v_loc if self.held else 0.0
        cd = p.cond_drive_f
        a11 = 1.0 + h * p.r_drive_ohm / ell
        a12 = h / cd
        a21 = -h / ell
        a22 = 1.0 + h * g / cd
        b1 = self.lam + h * vd
        b2 = self.qd + h * j
        det = a11 * a22 - a12 * a21
        lam = (b1 * a22 - a12 * b2) / det
        qd = (a11 * b2 - a21 * b1) / det
        self.lam, self.qd = lam, qd
        i_loc = lam / ell
        # The line: q_l' = (V_line - q_l / C_l) G_k - g_l q_l / C_l.
        cl = p.cond_line_f
        gk = self.carbon_g()
        gl = 1.0 / rc if closed else 0.0
        ql = (self.ql + h * v_line * gk) / (1.0 + h * (gk + gl) / cl)
        self.ql = ql
        i_line = (v_line - ql / cl) * gk
        self.i_line = i_line
        # The pull, the contacts' and the stop's forces; the modes exactly over the step.
        f = lam * lam / (MU0 * p.turns * p.turns * p.area_m2) + fc
        if x > p.stop_m:
            f -= p.k_stop_n_m * (x - p.stop_m) + p.c_stop_ns_m * v
        for jm, st in enumerate(self.steps if self.held else self.steps_up):
            xs = p.modes[jm].b * f * st.inv_k
            dx = self.xs[jm] - xs
            vm = self.vs[jm]
            self.xs[jm] = xs + st.a11 * dx + st.a12 * vm
            self.vs[jm] = st.a21 * dx + st.a22 * vm
        # The spark: lit across the open drive gap past its breakdown, out when the contact
        # makes or its current falls below the arc's minimum.
        xn = self.x()
        vc = qd / cd
        if xn < p.x_c_m:
            self.arc = 0
        elif self.arc != 0:
            ic = self.arc * (vc - self.arc * p.v_arc) / p.r_arc_ohm
            if ic < p.i_arc_min_a:
                self.arc = 0
        elif abs(vc) > breakdown_v(p, xn - p.x_c_m):
            self.arc = 1 if vc > 0.0 else -1
            self.sparks += 1
        # The dashpot.
        k = self.on_k if self.held else self.off_k
        self.force = self.target + (self.force - self.target) * k
        return i_loc, i_line

    def asleep(self) -> bool:
        """Silent from here on: key up, carbon unloaded, the coil's current and the reed's
        swing gone (the reed back near its rest, its energy under a nanojoule)."""
        return (
            not self.held
            and self.force < 1e-6 * self.p.f0_n
            and abs(self.lam) < 1e-9
            and self.energy() < 1e-9
        )


def run(
    p: KeyParams,
    seconds: float,
    v_loc: float,
    v_line: float,
    events: list[tuple[float, str, int]] | None = None,
    oversample: int = 8,
    fs: float = FS_HZ,
    probes: bool = False,
) -> dict[str, list[float]]:
    """A key on held lines (volts): its local and line currents per step-rate sample (each the
    mean of the step's internal samples). Events (time s, "on" | "off" | "pressure", value)
    land at the first step at or after their time. `probes`: the drive point's displacement
    and the drive condenser's voltage at each step's end too."""
    key = Key(p, fs * oversample)
    n = int(round(seconds * fs))
    evs = sorted(events or [], key=lambda e: e[0])
    out: dict[str, list[float]] = {"i_loc": [], "i_line": []}
    if probes:
        out["x"] = []
        out["vc"] = []
    e = 0
    for k in range(n):
        while e < len(evs) and evs[e][0] * fs <= k + 1e-9:
            _, kind, val = evs[e]
            if kind == "on":
                key.press(val)
            elif kind == "off":
                key.release()
            else:
                key.set_pressure(val)
            e += 1
        sl, sn = 0.0, 0.0
        for _ in range(oversample):
            a, b = key.step(v_loc, v_line)
            sl += a
            sn += b
        out["i_loc"].append(sl / oversample)
        out["i_line"].append(sn / oversample)
        if probes:
            out["x"].append(key.x())
            out["vc"].append(key.qd / p.cond_drive_f)
    out["sparks"] = [float(key.sparks)]
    return out


def load_cfg() -> dict:
    return spec.load("reeds")


def pitch_hz(x: list[float] | object, fs: float = FS_HZ, tail_s: float = 0.2) -> float:
    """The running reed's frequency from its last `tail_s`: upward crossings of its mean,
    each placed by linear interpolation."""
    import numpy as np

    y = np.asarray(x, dtype=float)[-int(round(tail_s * fs)) :]
    y = y - y.mean()
    k = np.nonzero((y[:-1] < 0.0) & (y[1:] >= 0.0))[0]
    if len(k) < 3:
        return 0.0
    t = k + (-y[k]) / (y[k + 1] - y[k])
    return (len(t) - 1) * fs / (t[-1] - t[0])
