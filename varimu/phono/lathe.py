"""The 1960s stereo disc lathe (docs/PHONO_PLAN.md, "The 1960s record player"; sources
data/schematics/westrex_3d/README.md): the RIAA pre-emphasis, the RA-1574-D's constant-velocity
card and power stage, and each 45 degree axis of a Westrex 3D cutter with its feedback coil.

**One axis of the cutter** (mobility analogy; network.py). The amplifier's output (a voltage)
drives the drive coil's resistance R and inductance L; the coil's force factor Bl is a
transformer onto the coil form (node `c`): its mass m_c on the coil-support springs k with a
little mechanical loss r_m (the damping is the feedback's: DF58, "the damper ... has little or
no effect below 10 kc"). The form drives the stylus through its link and the torque tube (k_t,
r_t) to the stylus' tip (node `t`, mass m_t), which cuts the lacquer (its resistance r_lac). The
feedback coil sits on the drive coil's form: its EMF is Bl_fb times the form's velocity. Each
axis carries only its own mass (DF58: the links are "relatively stiff ... in a forward direction
but with relatively high compliance in a lateral direction"); the two axes are coupled by a
spring `k_cross` (the links' sideways stiffness) giving the head its separation.

**The loop.** The RA-1574-D takes the program after the card and sums the feedback coil's
voltage at its phase inverter's grid (DF58 Fig. 1): v_out = A (e - beta v_fb), with the
amplifier's own bandwidth as two real poles (an output transformer's low end and its leakage's
high end). Its gain is set for the paper's 28 dB of feedback at the resonance (NS64).

**The card** (NS64: "plug-in card for precise constant velocity correction for individual
cutters", +-1 dB 50 Hz - 12 kHz, +-2 dB to 15 kHz): passive shelves ahead of the amplifier,
fitted per cutter (`fit_card`) to make the closed loop flat over its band, as the factory
fitted each card to its cutter.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from varimu.phono.network import GROUND, Network, System

# RIAA / NAB 1964 §3.05 time constants.
T1_S, T2_S, T3_S = 75e-6, 318e-6, 3180e-6


def riaa_record(f_hz) -> np.ndarray:
    """The recording characteristic, velocity per unit input, 0 dB at 1 kHz: the inverse of
    NAB's reproducing curve N(f) = (1 + 1/(w t2)^2)^(1/2) / ((1 + (w t1)^2) (1 + 1/(w t3)^2))^(1/2)
    as a minimum-phase transfer, (1 + s t1)(1 + s t3) / ((1 + s t2) s t3) * s t3 ... normalized."""
    s = 2j * np.pi * np.asarray(f_hz, dtype=float)
    h = (1 + s * T1_S) * (1 + s * T3_S) / (1 + s * T2_S)
    s1 = 2j * np.pi * 1000.0
    return h / abs((1 + s1 * T1_S) * (1 + s1 * T3_S) / (1 + s1 * T2_S))


def riaa_reproduce_db(f_hz) -> np.ndarray:
    """NAB 1964 §3.05's N(f) in dB re 1 kHz (Table 1: +18.61 at 30 Hz, -13.75 at 10 kHz)."""
    return -20 * np.log10(np.abs(riaa_record(f_hz)))


@dataclass
class Axis:
    """One axis's elements (SI)."""

    r_coil_ohm: float
    l_coil_h: float
    bl_t_m: float
    m_coil_kg: float
    k_susp_n_m: float
    r_mech_ns_m: float
    k_tube_n_m: float
    r_tube_ns_m: float
    m_tip_kg: float
    r_lacquer_ns_m: float

    @staticmethod
    def from_spec(c: dict) -> Axis:
        return Axis(
            c["drive_coil_ohm"], c["drive_coil_h"], c["bl_t_m"], c["coil_mass_kg"],
            c["suspension_n_m"], c["mech_resistance_ns_m"], c["torque_tube_n_m"],
            c["torque_tube_ns_m"], c["tip_mass_kg"], c["lacquer_resistance_ns_m"],
        )  # fmt: skip


def axis_network(ax: Axis, p: str = "") -> Network:
    """One axis open loop: a voltage source `drive{p}` across the coil; nodes `c{p}` (the
    form: the feedback coil's velocity) and `t{p}` (the tip: the cut)."""
    net = Network()
    _axis(net, ax, p)
    return net


def _axis(net: Network, ax: Axis, p: str) -> None:
    net.voltage_source(f"o{p}", GROUND, f"drive{p}")
    net.resistor(f"o{p}", f"i{p}", ax.r_coil_ohm)
    net.inductor(f"i{p}", f"e{p}", ax.l_coil_h, f"Lcoil{p}")
    # The coil: its EMF Bl v on the electrical side, its force Bl i on the form.
    net.transformer(f"c{p}", GROUND, f"e{p}", GROUND, ax.bl_t_m, f"bl{p}")
    net.capacitor(f"c{p}", GROUND, ax.m_coil_kg)
    net.inductor(f"c{p}", GROUND, 1.0 / ax.k_susp_n_m, f"ksusp{p}")
    net.conductance(f"c{p}", GROUND, ax.r_mech_ns_m)
    net.inductor(f"c{p}", f"t{p}", 1.0 / ax.k_tube_n_m, f"ktube{p}")
    net.conductance(f"c{p}", f"t{p}", ax.r_tube_ns_m)
    net.capacitor(f"t{p}", GROUND, ax.m_tip_kg)
    net.conductance(f"t{p}", GROUND, ax.r_lacquer_ns_m)


def open_loop(ax: Axis, f_hz: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """(tip velocity, form velocity) per volt of drive."""
    sys = axis_network(ax).compile()
    x = sys.response(f_hz, "drive")
    return x[:, sys.index("t")], x[:, sys.index("c")]


def amplifier(f_hz: np.ndarray, f_low_hz: float, f_high_hz: float) -> np.ndarray:
    """The amplifier's frequency shape inside the loop: a real pole at each end, unit gain
    in the band."""
    s = 2j * np.pi * np.asarray(f_hz, dtype=float)
    wl, wh = 2 * np.pi * f_low_hz, 2 * np.pi * f_high_hz
    return (s / (s + wl)) * (wh / (s + wh))


def closed_loop(ax: Axis, f_hz, gain: float, f_low_hz: float, f_high_hz: float):
    """Tip velocity per volt at the summing point with the feedback loop closed (the
    feedback coil's ratio absorbed into `gain`, the loop's gain per (m/s) of the form's
    velocity per volt). Returns (closed, loop gain)."""
    vt, vc = open_loop(ax, f_hz)
    a = gain * amplifier(f_hz, f_low_hz, f_high_hz)
    loop = a * vc
    return a * vt / (1 + loop), loop


def resonance_hz(ax: Axis, f_hz: np.ndarray) -> float:
    vt, _ = open_loop(ax, f_hz)
    return float(f_hz[int(np.argmax(np.abs(vt)))])


def gain_for_feedback(ax: Axis, feedback_db: float, f_low_hz: float, f_high_hz: float) -> float:
    """The loop gain that gives `feedback_db` (20 log |1 + T|) at the open loop's resonance."""
    f = np.geomspace(100, 5000, 2000)
    f0 = resonance_hz(ax, f)
    _, vc = open_loop(ax, np.array([f0]))
    am = amplifier(np.array([f0]), f_low_hz, f_high_hz)
    target = 10 ** (feedback_db / 20)
    # |1 + g a vc| = target, g real and positive: solve the quadratic in g.
    z = am[0] * vc[0]
    a2, a1, a0 = abs(z) ** 2, 2 * z.real, 1 - target**2
    return float((-a1 + np.sqrt(a1 * a1 - 4 * a2 * a0)) / (2 * a2))


def stereo_network(ax: Axis, k_cross_n_m: float, spec: dict) -> System:
    """Both axes with the loops closed, as one network for the time-domain cut: inputs
    `e_a`, `e_b` (the card's outputs, volts), outputs the tips' excursions `x_a`, `x_b`
    (integrators of nodes t_a, t_b). The amplifier is two stages per channel: a summing
    stage with the low pole (a series capacitor's high-pass, as an RC node) and the high
    pole, then a stiff output (the coil's source)."""
    amp = spec["amplifier"]
    g = spec["loop_gain"]
    fl, fh = amp["low_pole_hz"], amp["high_pole_hz"]
    net = Network()
    for p in ("_a", "_b"):
        # Summing node: (e - fb) / g_stage into node s with its high pole.
        net.voltage_source(f"in{p}", GROUND, f"e{p}")
        ch = 1.0 / (2 * np.pi * fh)  # 1 ohm || ch: pole at fh
        net.vccs(f"s{p}", f"in{p}", 1.0)
        net.vccs(f"s{p}", f"fb{p}", -1.0)
        net.conductance(f"s{p}", GROUND, 1.0)
        net.capacitor(f"s{p}", GROUND, ch)
        # The low pole: a series C into 1 ohm (high-pass), node h.
        net.capacitor(f"s{p}", f"h{p}", 1.0 / (2 * np.pi * fl))
        net.conductance(f"h{p}", GROUND, 1.0)
        # The output stage: v(o) = g v(h), stiff (1 mOhm source).
        net.vccs(f"o{p}", f"h{p}", g * 1e3)
        net.conductance(f"o{p}", GROUND, 1e3)
        net.resistor(f"o{p}", f"i{p}", ax.r_coil_ohm)
        net.inductor(f"i{p}", f"el{p}", ax.l_coil_h, f"Lcoil{p}")
        net.transformer(f"c{p}", GROUND, f"el{p}", GROUND, ax.bl_t_m, f"bl{p}")
        net.capacitor(f"c{p}", GROUND, ax.m_coil_kg)
        net.inductor(f"c{p}", GROUND, 1.0 / ax.k_susp_n_m, f"ksusp{p}")
        net.conductance(f"c{p}", GROUND, ax.r_mech_ns_m)
        net.inductor(f"c{p}", f"t{p}", 1.0 / ax.k_tube_n_m, f"ktube{p}")
        net.conductance(f"c{p}", f"t{p}", ax.r_tube_ns_m)
        net.capacitor(f"t{p}", GROUND, ax.m_tip_kg)
        net.conductance(f"t{p}", GROUND, ax.r_lacquer_ns_m)
        # The feedback coil: unit ratio (its sensitivity is in the loop gain), unloaded.
        net.transformer(f"c{p}", GROUND, f"fb{p}", GROUND, 1.0, f"fbcoil{p}")
        net.integrator(f"t{p}", f"x{p}")
    net.inductor("t_a", "t_b", 1.0 / k_cross_n_m, "kcross")
    return net.compile()


# The card and the whole chain.

CARD_ORDER = 4  # real zero / pole pairs
CARD_RESONANCES = 2  # second-order sections


def card_response(f_hz, params: np.ndarray) -> np.ndarray:
    """The card as a minimum-phase cascade: CARD_ORDER first-order sections (zero z_i, pole
    p_i, from log-frequencies) and one second-order section (a resonance f_r, Q_n over Q_d,
    for the closed loop's dip above the resonance). Unit gain at DC of each section's zero
    over pole (the level is set at the cut)."""
    s = 2j * np.pi * np.asarray(f_hz, dtype=float)
    h = np.ones_like(s)
    for i in range(CARD_ORDER):
        z, p = np.exp(params[2 * i]), np.exp(params[2 * i + 1])
        h *= (1 + s / (2 * np.pi * z)) / (1 + s / (2 * np.pi * p))
    for j in range(CARD_RESONANCES):
        k = 2 * CARD_ORDER + 3 * j
        fr, qn, qd = np.exp(params[k : k + 3])
        w = 2 * np.pi * fr
        h *= (s * s + s * w / qn + w * w) / (s * s + s * w / qd + w * w)
    return h


CARD_STARTS = ((6000.0, 14000.0), (9000.0, 14500.0), (11000.0, 15000.0), (4000.0, 12000.0))


def card_initial(resonances=CARD_STARTS[0]) -> np.ndarray:
    pairs = [(50.0, 50.0), (500.0, 500.0), (2000.0, 2000.0), (10000.0, 10000.0)]
    x = []
    for z, p in pairs:
        x += [np.log(z), np.log(p)]
    for fr in resonances[:CARD_RESONANCES]:
        x += [np.log(fr), 0.0, 0.0]
    return np.array(x)


def loops(spec: dict, f_hz) -> np.ndarray:
    """The closed loops' tip velocity per volt at the card's output, with the axes'
    coupling: (len(f), 2, 2), [out axis, in axis]."""
    f = np.atleast_1d(np.asarray(f_hz, dtype=float))
    c = spec["cutter"]
    sys = stereo_network(Axis.from_spec(c), c["cross_stiffness_n_m"], _loop_spec(spec))
    h = np.zeros((len(f), 2, 2), dtype=complex)
    for j, e in enumerate(("e_a", "e_b")):
        x = sys.response(f, e)
        h[:, 0, j] = x[:, sys.index("t_a")]
        h[:, 1, j] = x[:, sys.index("t_b")]
    return h


def chain(spec: dict, f_hz, card: np.ndarray | None, loop: np.ndarray | None = None,
          ref: complex | None = None) -> np.ndarray:  # fmt: skip
    """The cut's velocity per unit program per channel (len(f), 2, 2: [out, in]) through
    the RIAA pre-emphasis, the card and the closed loops (`loops`, passed in when known),
    normalized to 1 at 1 kHz on the diagonal (`ref`: the un-normalized value there)."""
    f = np.atleast_1d(np.asarray(f_hz, dtype=float))
    h = loops(spec, f) if loop is None else loop
    pre = riaa_record(f)
    if card is not None:
        pre = pre * card_response(f, card)
    if ref is None:
        ref = chain_ref(spec, card)
    return (
        h * pre[:, None, None] / abs(ref)
    )  # a complex divisor would rotate every phase: not causal


def _loop_spec(spec: dict) -> dict:
    c = spec["cutter"]
    ax = Axis.from_spec(c)
    g = gain_for_feedback(ax, c["feedback_db"], c["low_pole_hz"], c["high_pole_hz"])
    return {
        "loop_gain": g,
        "amplifier": {"low_pole_hz": c["low_pole_hz"], "high_pole_hz": c["high_pole_hz"]},
    }


def chain_ref(spec: dict, card: np.ndarray | None, loop_1k: complex | None = None) -> complex:
    """The un-normalized chain's diagonal at 1 kHz."""
    f = np.array([1000.0])
    h = loops(spec, f)[0, 0, 0] if loop_1k is None else loop_1k
    pre = riaa_record(f) * (card_response(f, card) if card is not None else 1.0)
    return complex(h * pre[0])


def fit_card(spec: dict) -> tuple[np.ndarray, float]:
    """The card for this cutter: the chain's diagonal within the band equal to the RIAA
    recording curve (velocity), as the factory trimmed each card. Returns (params, the
    worst deviation in the band, dB)."""
    from scipy.optimize import least_squares

    cd = spec["card"]
    lo, hi = cd["band_low_hz"], cd["band_high_hz"]
    f = np.geomspace(lo, 15000.0, 120)
    w = np.where(f <= hi, 1.0, 0.5)
    target = 20 * np.log10(np.abs(riaa_record(f)))

    loop = loops(spec, f)
    l1k = loops(spec, np.array([1000.0]))[0, 0, 0]

    def dev(x):
        h = chain(spec, f, x, loop, chain_ref(spec, x, l1k))[:, 0, 0]
        return 20 * np.log10(np.abs(h)) - target

    res_lb = [np.log(2000), np.log(0.2), np.log(0.2)] * CARD_RESONANCES
    res_ub = [np.log(20000), np.log(30), np.log(30)] * CARD_RESONANCES
    lb = np.concatenate([np.full(2 * CARD_ORDER, np.log(5.0)), res_lb])
    ub = np.concatenate([np.full(2 * CARD_ORDER, np.log(60000.0)), res_ub])
    best = None
    for start in CARD_STARTS:  # the factory trimmed to a tolerance: keep the best start
        r = least_squares(lambda x: dev(x) * w, card_initial(start), bounds=(lb, ub))
        worst = float(np.max(np.abs(dev(r.x)[f <= hi])))
        if best is None or worst < best[1]:
            best = (r.x, worst)
    return best
