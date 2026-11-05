"""A spring reverb tank (docs/REVERB_PLAN.md, E1-E3): the component, the decay its losses
give, and the Python reference of its springs' modes and impulse response (circuitsim's
spring.rs is the port; the two agree within rounding, tests/test_spring.py).

**The spring** (Parker & Bilbao, DAFx-09, eq. 1, after Fletcher et al.'s curved-rod model:
the helix angle neglected, vibration in the plane of curvature). Along the wire's arc
length s, the tangential displacement u and the radial v:

    u_tt = (E / rho) (u_ss - k v_s)
    v_tt = -(E r^2 / (4 rho)) (v_ssss + 2 k^2 v_ss + k^4 v) + (E k / rho) (u_s - k v)

with k = 1 / R the helix's curvature, r the wire's radius, E and rho the steel's. On a
spring of uncurled length L = sqrt((2 pi R N)^2 + H^2) (their eq. 3) with its ends pinned
radially (v = v_ss = 0) and free tangentially (u_s - k v = 0: the beads are light and turn
freely, Parker & Bilbao Fig. 1), the modes separate exactly: u = a cos(beta s),
v = b sin(beta s), beta = n pi / L, each n a 2 x 2 eigenproblem. With c^2 = E / rho and
g = r^2 / 4, the stiffness over the mass is c^2 [[beta^2, k beta], [k beta, g (k^2 -
beta^2)^2 + k^2]]; its determinant is c^4 g beta^2 (k^2 - beta^2)^2, so the audio branch
is omega^2 = det / lambda_hi exactly (no cancellation). The other branch starts near c k
(~350 kHz for a tank's spring) and is dropped. The audio branch rises from 0 to the
transition frequency F_C near beta = k / 2, falls to 0 at beta = k and rises steeply after
it: the low-frequency chirped echoes below F_C repeating at T_D, the faster echoes above it
(their Figs. 2, 4).

**The transducers.** Each spring hangs from a magnetic bead turned by its coil's field
(the input) or turning in its coil's field (the output); the bead's torsion moves the
wire tangentially where it enters the helix (Parker & Bilbao, section 2). So a force F
(N, from the input coil's current) drives every spring's u at s = 0, and the output is
the sum of the springs' tangential velocities at s = L. Mass-normalized, a mode's weight is
(2 / (rho A L)) a^2 (-1)^n, with (a, b) its unit eigenvector. The beads' inertia is
neglected (~3 mg against the spring's ~0.13 g per wavelength at 1 kHz). The input coil's
pole pieces saturate: the force is a soft limit of its current (tanh, `drive_force`), the
springs linear after it.

**Losses.** A mode's amplitude decays as exp(-s t), s = sigma_E(f) / 2, from a table of
the energy decay rate against frequency (as the plate's): the end dampers' loss, the same
at every frequency, plus the steel's internal loss (loss factor eta: sigma_E = omega
eta), set together by the tank's decay at 500 Hz (`decay_table`).

**The response** at rate fs: force (N) to the output's velocity (m/s), h[k] = T v(kT)
for k >= 1 (impulse invariance; h[0] is never used: the output is a spring's length
away), each mode summed until it has decayed by tail_db, the modes below min(f_max,
0.45 fs).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np

SIX_LN10 = 6.0 * math.log(10.0)

# Third octaves from 20 Hz to 20 kHz: the decay table's frequencies.
DECAY_GRID_HZ = (
    20.0, 25.0, 31.5, 40.0, 50.0, 63.0, 80.0, 100.0, 125.0, 160.0, 200.0, 250.0, 315.0,
    400.0, 500.0, 630.0, 800.0, 1000.0, 1250.0, 1600.0, 2000.0, 2500.0, 3150.0, 4000.0,
    5000.0, 6300.0, 8000.0, 10000.0, 12500.0, 16000.0, 20000.0,
)  # fmt: skip


@dataclass(frozen=True)
class Spring:
    """One spring of a tank, as measured: wire and helix diameters, turns, helix length."""

    wire_diameter_m: float
    helix_diameter_m: float
    turns: float
    helix_length_m: float

    def wire_length_m(self) -> float:
        """The uncurled wire's length (Parker & Bilbao eq. 3). Plain products, as the Rust
        builder computes it (bit for bit, tests/agreement.rs)."""
        a = 2.0 * math.pi * (0.5 * self.helix_diameter_m) * self.turns
        h = self.helix_length_m
        return math.sqrt(a * a + h * h)


@dataclass(frozen=True)
class SpringTankComponent:
    """A spring tank component version (config/components/<name>/<N>.yaml, kind
    `spring_tank`)."""

    name: str
    springs: tuple[Spring, ...]
    density_kg_m3: float
    youngs_pa: float
    input_re_ohm: float
    input_le_h: float
    input_force_per_a: float
    input_saturation_a: float
    output_re_ohm: float
    output_le_h: float
    output_v_per_m_s: float
    t60_500hz_s: float
    loss_factor: float
    f_max_hz: float
    tail_db: float


def spring_tank_from_data(d: dict[str, Any], name: str) -> SpringTankComponent:
    m, i, o, loss, mod = d["material"], d["input"], d["output"], d["losses"], d["model"]
    return SpringTankComponent(
        name=name,
        springs=tuple(
            Spring(
                float(s["wire_diameter_m"]),
                float(s["helix_diameter_m"]),
                float(s["turns"]),
                float(s["helix_length_m"]),
            )
            for s in d["springs"]["list"]
        ),
        density_kg_m3=float(m["density_kg_m3"]),
        youngs_pa=float(m["youngs_pa"]),
        input_re_ohm=float(i["re_ohm"]),
        input_le_h=float(i["le_h"]),
        input_force_per_a=float(i["force_per_a"]),
        input_saturation_a=float(i["saturation_a"]),
        output_re_ohm=float(o["re_ohm"]),
        output_le_h=float(o["le_h"]),
        output_v_per_m_s=float(o["v_per_m_s"]),
        t60_500hz_s=float(loss["t60_500hz_s"]),
        loss_factor=float(loss["loss_factor"]),
        f_max_hz=float(mod["f_max_hz"]),
        tail_db=float(mod["tail_db"]),
    )


def decay_table(t60_500hz_s: float, loss_factor: float) -> tuple[tuple[float, float], ...]:
    """The energy decay rate (Hz, 1/s) on DECAY_GRID_HZ: the end dampers' rate, flat, plus
    the steel's omega eta, the two together giving t60_500hz_s at 500 Hz. Plain arithmetic
    in this order, as varimu-circuit's spring.rs does it."""
    ends = SIX_LN10 / t60_500hz_s - 2.0 * math.pi * 500.0 * loss_factor
    ends = max(ends, 0.0)
    return tuple((f, ends + 2.0 * math.pi * f * loss_factor) for f in DECAY_GRID_HZ)


def characteristic_impedance_ns_per_m(c: SpringTankComponent) -> float:
    """The springs' tangential impedance at their ends at low frequencies, summed over the
    springs on the bead's coil: rho A v0 each, v0 = r c / (2 R) the low-frequency wave
    speed (Parker & Bilbao, appendix B). The input coil's motional resistance is
    force_per_a^2 over it (one-way coupling: the springs' load on the coil). Plain loops,
    as the Rust builder sums."""
    c_m_s = math.sqrt(c.youngs_pa / c.density_kg_m3)
    z = 0.0
    for s in c.springs:
        r = 0.5 * s.wire_diameter_m
        area = math.pi * r * r
        v0 = r * c_m_s / s.helix_diameter_m  # r c / (2 R), 2 R the helix's diameter
        z += c.density_kg_m3 * area * v0
    return z


# --- The reference --------------------------------------------------------------------


@dataclass(frozen=True)
class SpringSpec:
    """What the IR's Spring element carries (varimu.circuit.ir.Spring's medium fields):
    per spring (wire radius, helix radius, wire length) in metres."""

    density_kg_m3: float
    youngs_pa: float
    springs: tuple[tuple[float, float, float], ...]
    f_max_hz: float
    decay: tuple[tuple[float, float], ...]
    tail_db: float

    @classmethod
    def of(cls, el: Any) -> SpringSpec:
        """From an IR Spring element (or anything with its fields)."""
        return cls(
            el.density_kg_m3,
            el.youngs_pa,
            tuple(tuple(s) for s in el.springs),
            el.f_max_hz,
            tuple(tuple(d) for d in el.decay),
            el.tail_db,
        )


def energy_decay(table: tuple[tuple[float, float], ...], f_hz: np.ndarray) -> np.ndarray:
    """sigma_E at f_hz: linear in log frequency between the table's points, held at its
    ends."""
    fs = np.array([p[0] for p in table])
    ss = np.array([p[1] for p in table])
    return np.interp(np.log(np.maximum(f_hz, 1e-300)), np.log(fs), ss)


def branch(c2: float, r: float, k: float, beta: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """The audio branch at wavenumbers beta: (omega, a^2), a the tangential share of the
    unit eigenvector."""
    g = 0.25 * r * r
    bb = beta * beta
    p = bb
    q = k * beta
    s = g * (k * k - bb) ** 2 + k * k
    mean = 0.5 * (p + s)
    half = 0.5 * (p - s)
    hi = mean + np.sqrt(half * half + q * q)
    lo = g * bb * (k * k - bb) ** 2 / hi
    ea, eb = s - lo, -q
    a2 = ea * ea / (ea * ea + eb * eb)
    return np.sqrt(c2 * lo), a2


def spring_modes(
    rho: float, e: float, r: float, big_r: float, length: float, f_top_hz: float
) -> tuple[np.ndarray, np.ndarray]:
    """(omega, weight) of one spring's audio-branch modes below f_top_hz, n = 1, 2, ...
    until the branch has risen past f_top beyond beta = k (it falls to 0 at beta = k)."""
    c2 = e / rho
    k = 1.0 / big_r
    w_top = 2.0 * math.pi * f_top_hz
    n_k = k * length / math.pi
    # Past beta = k the branch only rises: stop at its first mode above f_top there.
    n = 1
    while True:
        beta = n * math.pi / length
        om, _ = branch(c2, r, k, np.array([beta]))
        if n > n_k and om[0] > w_top:
            break
        n += 1
    ns = np.arange(1, n)
    beta = ns * math.pi / length
    om, a2 = branch(c2, r, k, beta)
    area = math.pi * r * r
    sign = np.where(ns % 2 == 0, 1.0, -1.0)
    weight = (2.0 / (rho * area * length)) * a2 * sign
    keep = om <= w_top
    return om[keep], weight[keep]


def modes(p: SpringSpec, f_top_hz: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(omega, amplitude decay rate, weight) of every spring's modes below f_top_hz, the
    springs in order, each in n order."""
    om, w = [], []
    for r, big_r, length in p.springs:
        o, ww = spring_modes(p.density_kg_m3, p.youngs_pa, r, big_r, length, f_top_hz)
        om.append(o)
        w.append(ww)
    omega = np.concatenate(om)
    weight = np.concatenate(w)
    decay = 0.5 * energy_decay(p.decay, omega / (2.0 * math.pi))
    return omega, decay, weight


def impulse_response(p: SpringSpec, fs: float) -> np.ndarray:
    """Force (N) at the input beads to velocity (m/s) at the output beads at fs (see the
    module docs)."""
    omega, s, w = modes(p, min(p.f_max_hz, 0.45 * fs))
    ok = (w != 0) & (omega > s)
    omega, s, w = omega[ok], s[ok], w[ok]
    t = 1.0 / fs
    ln_tail = abs(p.tail_db) / 20.0 * math.log(10.0)
    lens = np.ceil(ln_tail / s * fs).astype(np.int64) + 1
    n = int(min(lens.max(), 60 * int(fs)))
    h = np.zeros(n)
    wd = np.sqrt(omega * omega - s * s)
    # v(t) = w exp(-s t) [cos(wd t) - (s / wd) sin(wd t)], times T.
    ca = t * w
    cb = -t * w * s / wd
    chunk, group = 1 << 12, 256
    for k0 in range(0, n, chunk):
        k = np.arange(k0, min(k0 + chunk, n))
        kt = k[None, :] * t
        live = np.flatnonzero(lens > k0)
        for g0 in range(0, len(live), group):
            j = live[g0 : g0 + group]
            env = np.exp(-s[j, None] * kt)
            ph = wd[j, None] * kt
            terms = env * (ca[j, None] * np.cos(ph) + cb[j, None] * np.sin(ph))
            terms[k[None, :] >= lens[j, None]] = 0.0
            h[k0 : k0 + len(k)] += terms.sum(axis=0)
    h[0] = 0.0
    return h


def drive_force(el: Any, v: np.ndarray | float) -> np.ndarray:
    """The force (N) on the input beads for the sense voltage v (an IR Spring element's
    fields): linear, or the input coil's pole pieces saturating as tanh (saturation_v)."""
    v = np.asarray(v, float)
    if el.saturation_v > 0:
        return el.force_per_v * el.saturation_v * np.tanh(v / el.saturation_v)
    return el.force_per_v * v


# --- Closed forms (Parker & Bilbao, appendix B) -------------------------------------------


def delay_s(r: float, big_r: float, length: float, e: float, rho: float) -> float:
    """T_D = 4 L R / (r sqrt(E / rho)): the echoes' spacing below F_C."""
    return 4.0 * length * big_r / (r * math.sqrt(e / rho))


def transition_hz(r: float, big_r: float, e: float, rho: float) -> float:
    """F_C = 3 r sqrt(E / rho) / (16 sqrt(5) pi R^2), to first order."""
    return 3.0 * r * math.sqrt(e / rho) / (16.0 * math.sqrt(5.0) * math.pi * big_r * big_r)


def spec_of(c: SpringTankComponent, f_max_hz: float | None = None) -> SpringSpec:
    """The component's springs as the IR carries them."""
    return SpringSpec(
        c.density_kg_m3,
        c.youngs_pa,
        tuple(
            (0.5 * s.wire_diameter_m, 0.5 * s.helix_diameter_m, s.wire_length_m())
            for s in c.springs
        ),
        c.f_max_hz if f_max_hz is None else f_max_hz,
        decay_table(c.t60_500hz_s, c.loss_factor),
        c.tail_db,
    )
