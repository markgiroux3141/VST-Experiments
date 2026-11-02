"""A wax cylinder, recorded acoustically and played acoustically (docs/PHONO_PLAN.md: G1's
groove, G3's reproducer, G4's recorder in a first cut; config/phono/<machine>.yaml).

Recording (linear, `record`): sound at the recording horn's mouth (a Thevenin source behind
the mouth's radiation load) -> the conical horn -> the rubber coupling -> the air in front of
the diaphragm -> the diaphragm (its clamped fundamental as one mode) carrying the cutter
-> the wax's cutting resistance. The cutter's excursion is cut into the groove along arc
length (groove.write: where it lifts out of the wax the surface stays uncut). The
performer's level is the recording engineer's placement: the program's loudest point cuts
the format's maximum amplitude (`drive` 1); drive > 1 is a performer too close.

Playing (nonlinear, `play`): the groove dilated by the reproducer's tip -> a Hertz contact
with Hunt-Crossley damping (mistracking is where its force is 0) -> the tip on the stylus
bar, a lever pivoted on the floating weight, which rides on the groove by gravity and
hinges on the reproducer -> the diaphragm -> the air in front of it -> the neck and the
horn -> the mouth's radiation; the output is the pressure 1 m out on the axis, the mouth
taken as a monopole: p = rho / (4 pi r) dU/dt (U the mouth's volume velocity).

A clamped circular plate's fundamental (Leissa, Vibration of Plates, NASA SP-160, 1969:
lambda^2 = 10.2158) gives the diaphragm's mode: its static shape w = w0 (1 - r^2/a^2)^2
puts a fifth of the plate's mass and a third of its area at the centre's velocity.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import yaml
from scipy.signal import fftconvolve, resample_poly

from varimu.phono import groove as gv
from varimu.phono import horn
from varimu.phono import transport as tr
from varimu.phono.network import GROUND, Network, Stepper, System

PHONO_DIR = Path(__file__).parents[2] / "config" / "phono"
IR_SECONDS = 0.25  # the recorder's impulse response (its slowest mode is down > 200 dB)
CLAMPED_LAMBDA2 = 10.2158  # Leissa (1969), a clamped circular plate's fundamental
MODE_MASS_FRACTION = 0.2  # integral of (1 - r^2/a^2)^4 over the disc / its area
MODE_AREA_FRACTION = 1.0 / 3.0  # integral of (1 - r^2/a^2)^2 over the disc / its area


def load(name: str = "edison_standard", path: Path | None = None) -> dict:
    """The machine's values (sources stripped): {block: {key: value}}."""
    path = path or PHONO_DIR / f"{name}.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    out: dict = {}
    for block, items in data.items():
        out[block] = {}
        for key, item in items.items():
            if not isinstance(item, dict) or "source" not in item:
                raise ValueError(f"{path.name}: {block}.{key} has no source")
            out[block][key] = float(item["value"])
    return out


@dataclass
class Diaphragm:
    mass_kg: float  # modal mass at the centre
    stiffness_n_m: float
    resistance_ns_m: float
    area_m2: float  # volume velocity per centre velocity
    f0_hz: float


def diaphragm(
    radius_m: float, thickness_m: float, youngs_pa: float, density: float, poisson: float, q: float
) -> Diaphragm:
    d_flex = youngs_pa * thickness_m**3 / (12 * (1 - poisson**2))
    mu = density * thickness_m
    f0 = CLAMPED_LAMBDA2 / (2 * np.pi * radius_m**2) * np.sqrt(d_flex / mu)
    m = MODE_MASS_FRACTION * mu * np.pi * radius_m**2
    w0 = 2 * np.pi * f0
    return Diaphragm(m, m * w0**2, m * w0 / q, MODE_AREA_FRACTION * np.pi * radius_m**2, f0)


def groove_speed(spec: dict, rpm: float) -> float:
    return np.pi * spec["cylinder"]["diameter_m"] * rpm / 60.0


# Recording.


def recorder_network(spec: dict) -> System:
    air, rec = spec["air"], spec["recorder"]
    rho, c, dx = air["density_kg_m3"], air["sound_speed_m_s"], spec["numerics"]["dx_max_m"]
    net = Network()
    net.voltage_source("src", GROUND, "p_src")
    horn.radiation(net, "mouth", "src", rec["horn_mouth_radius_m"], rho, c, "rad")
    horn.duct(
        net,
        "mouth",
        "throat",
        rec["horn_length_m"],
        rec["horn_mouth_radius_m"],
        rec["horn_throat_radius_m"],
        rho,
        c,
        dx,
        "horn",
    )
    horn.duct(
        net,
        "throat",
        "cav",
        rec["coupling_length_m"],
        rec["horn_throat_radius_m"],
        rec["horn_throat_radius_m"],
        rho,
        c,
        dx,
        "coup",
    )
    dia = _rec_diaphragm(spec)
    vol = np.pi * rec["diaphragm_radius_m"] ** 2 * rec["cavity_height_m"]
    net.capacitor("cav", GROUND, vol / (rho * c * c))
    # The diaphragm, up (into the cavity) positive; the cutter below it in the wax.
    net.gyrator("d", "cav", dia.area_m2)
    net.capacitor("d", GROUND, dia.mass_kg + rec["cutter_mass_kg"])
    net.inductor("d", GROUND, 1.0 / dia.stiffness_n_m, "k_dia")
    net.conductance("d", GROUND, dia.resistance_ns_m + rec["wax_cutting_resistance_ns_m"])
    net.integrator("d", "x_up")
    return net.compile()


def _rec_diaphragm(spec: dict) -> Diaphragm:
    r = spec["recorder"]
    return diaphragm(
        r["diaphragm_radius_m"],
        r["diaphragm_thickness_m"],
        r["diaphragm_youngs_pa"],
        r["diaphragm_density_kg_m3"],
        r["diaphragm_poisson"],
        r["diaphragm_q"],
    )


def recorder_response(spec: dict, f_hz: np.ndarray) -> np.ndarray:
    """The cutter's downward excursion per pascal of incident sound (m/Pa)."""
    sys = recorder_network(spec)
    x = sys.response(f_hz, "p_src")
    return -x[:, sys.index("x_up")] * spec["recorder"]["blocked_pressure_factor"]


@dataclass
class Recording:
    groove: gv.Groove
    z_m: np.ndarray  # the cutter's downward excursion (at the simulation rate)
    pa_per_unit: float  # incident pascals per unit of the input signal (the placement)
    lead_in_samples: int
    fs_hz: float
    motion: tr.Motion  # the recording machine's mandrel and the groove's speed


def record(
    spec: dict,
    x: np.ndarray,
    fs_in_hz: float,
    drive: float = 1.0,
    surface_seed: int | None = None,
    motion_seed: int | None = None,
) -> Recording:
    """Cuts the program x (any scale) into a groove. The loud passages (the
    `cut_level_percentile` of the cutter's excursion) cut `drive` times the format's
    maximum amplitude; rarer peaks go past it, as on hot acoustic records. With a surface_seed, the cut surface gets the wax's
    roughness (config `surface`; groove.roughness), else it is ideally smooth. With a
    motion_seed, the recording machine's drive (config `recorder_motor`; transport.py)
    turns the mandrel, loaded by the cut's drag, which deepens with the program: the
    groove is written along the arc length that actually passed. Else the mandrel turns at
    exactly `rpm_recorded`."""
    fs = spec["numerics"]["fs_hz"]
    up = resample_poly(np.asarray(x, dtype=float), int(fs), int(fs_in_hz))
    lead = int(round(spec["numerics"]["lead_in_s"] * fs))
    tail = int(round(0.05 * fs))
    sig = np.concatenate([np.zeros(lead), up, np.zeros(tail)])
    # The recorder is linear: its impulse response (the trapezoidal rule at fs, as the
    # player) convolved with the program.
    st = Stepper(recorder_network(spec), 1.0 / fs)
    ir = -st.impulse_response("p_src", st.sys.pick("x_up"), int(IR_SECONDS * fs))
    ir *= spec["recorder"]["blocked_pressure_factor"]
    z_unit = fftconvolve(sig, ir)[: len(sig)]
    loud = float(np.percentile(np.abs(z_unit), spec["cylinder"]["cut_level_percentile"]))
    scale = drive * spec["cylinder"]["max_amplitude_m"] / (loud or 1.0)
    z = z_unit * scale
    cyl = spec["cylinder"]
    radius = cyl["diameter_m"] / 2
    v = groove_speed(spec, cyl["rpm_recorded"])
    seconds = len(z) / fs
    if motion_seed is None:
        motion = tr.ideal(seconds, fs, cyl["rpm_recorded"], radius)
        g = gv.write(z, v, fs, cyl["cut_depth_m"])
    else:
        m = spec["recorder_motor"]
        depth = np.maximum(cyl["cut_depth_m"] + z, 0.0)
        drag = spec["recorder"]["cutting_drag_n"] * (depth / cyl["cut_depth_m"]) ** 1.5
        load = _block_mean(drag * radius, int(round(fs / m["fs_hz"]))) + m["feed_friction_n_m"]
        motion = tr.simulate(
            m, cyl["rpm_recorded"], radius, seconds, fs, load, motion_seed, "recorder"
        )
        h_t = np.minimum(0.0, -(cyl["cut_depth_m"] + z))
        ds = v / fs
        grid = np.arange(int(motion.s_m[-1] / ds)) * ds
        g = gv.Groove(h_m=np.interp(grid, motion.s_m, h_t), ds_m=ds)
    if surface_seed is not None:
        srf = spec["surface"]
        g.h_m = g.h_m + gv.roughness(
            len(g.h_m), g.ds_m, srf["sigma_m"], srf["corr_m"], surface_seed, "wax"
        )
    return Recording(g, z, scale, lead, fs, motion)


def _block_mean(x: np.ndarray, k: int) -> np.ndarray:
    n = len(x) // k * k
    head = x[:n].reshape(-1, k).mean(axis=1)
    return head if n == len(x) else np.append(head, x[n:].mean())


# Playing.


def _rep_diaphragm(spec: dict) -> Diaphragm:
    r = spec["reproducer"]
    return diaphragm(
        r["diaphragm_radius_m"],
        r["diaphragm_thickness_m"],
        r["diaphragm_youngs_pa"],
        r["diaphragm_density_kg_m3"],
        r["diaphragm_poisson"],
        r["diaphragm_q"],
    )


def contact_k(spec: dict) -> float:
    r, cyl = spec["reproducer"], spec["cylinder"]
    return gv.hertz_k(
        r["tip_radius_along_m"],
        r["tip_radius_across_m"],
        r["tip_youngs_pa"],
        r["tip_poisson"],
        cyl["wax_youngs_pa"],
        cyl["wax_poisson"],
    )


def reproducer_network(spec: dict, linear_contact: bool = False) -> System:
    """Up positive everywhere. Inputs: 'gravity' (the weight's load, at node w) and
    'contact' (the groove's force on the tip); with linear_contact, a 'groove' velocity
    source drives the tip through the contact's stiffness at the static load instead."""
    air, rep = spec["air"], spec["reproducer"]
    rho, c, dx = air["density_kg_m3"], air["sound_speed_m_s"], spec["numerics"]["dx_max_m"]
    net = Network()
    net.capacitor("t", GROUND, rep["tip_mass_kg"])
    net.capacitor("w", GROUND, rep["weight_mass_kg"])
    net.conductance("w", GROUND, rep["hinge_resistance_ns_m"])
    # The stylus bar pivots on the weight: v(d) - v(w) = n (v(t) - v(w)).
    net.transformer("t", "w", "d", "w", rep["lever_ratio"], "lever")
    dia = _rep_diaphragm(spec)
    net.capacitor("d", GROUND, dia.mass_kg + rep["link_mass_kg"])
    net.inductor("d", GROUND, 1.0 / dia.stiffness_n_m, "k_dia")
    net.conductance("d", GROUND, dia.resistance_ns_m)
    net.gyrator("d", "cav", dia.area_m2)
    vol = np.pi * rep["diaphragm_radius_m"] ** 2 * rep["cavity_height_m"]
    net.capacitor("cav", GROUND, vol / (rho * c * c))
    horn.duct(
        net,
        "cav",
        "throat",
        rep["neck_length_m"],
        rep["neck_radius_m"],
        rep["neck_radius_m"],
        rho,
        c,
        dx,
        "neck",
    )
    horn.duct(
        net,
        "throat",
        "mouth",
        rep["horn_length_m"],
        rep["neck_radius_m"],
        rep["horn_mouth_radius_m"],
        rho,
        c,
        dx,
        "horn",
    )
    horn.radiation(net, "mouth", GROUND, rep["horn_mouth_radius_m"], rho, c, "rad")
    net.integrator("t", "z_tip")
    if linear_contact:
        k = contact_k(spec)
        delta0 = gv.static_indent(rep["downforce_n"], k)
        kc = 1.5 * k * np.sqrt(delta0)
        net.voltage_source("g", GROUND, "groove")
        net.inductor("g", "t", 1.0 / kc, "k_contact")
        net.conductance("g", "t", kc * rep["contact_damping_s_m"] * delta0)
    else:
        net.current_source("w", "gravity")
        net.current_source("t", "contact")
    return net.compile()


def mouth_flow_row(spec: dict, sys: System) -> np.ndarray:
    """c with c @ x = the mouth's volume velocity into the air."""
    a = spec["reproducer"]["horn_mouth_radius_m"]
    area = np.pi * a * a
    air = spec["air"]
    res = air["density_kg_m3"] * air["sound_speed_m_s"] / area
    return sys.pick("radLrad") + sys.element_current("mouth", GROUND, "g", 1.0 / res)


def pressure_gain(spec: dict) -> float:
    """p at the listening distance per dU/dt at the mouth (a monopole in free air)."""
    return spec["air"]["density_kg_m3"] / (4 * np.pi * spec["listening"]["distance_m"])


def reproducer_response(spec: dict, f_hz: np.ndarray) -> np.ndarray:
    """Pressure at the listening position per metre of groove displacement, small signals
    (the contact linearized at the static load): Pa/m."""
    sys = reproducer_network(spec, linear_contact=True)
    x = sys.response(f_hz, "groove")  # per (m/s) of groove velocity
    u = x @ mouth_flow_row(spec, sys)
    jw = 2j * np.pi * np.asarray(f_hz)
    return pressure_gain(spec) * jw * u * jw  # dU/dt, and velocity per displacement


@dataclass
class Playback:
    pressure_pa: np.ndarray  # at the listening position, at the simulation rate
    force_n: np.ndarray  # the contact force
    tip_m: np.ndarray  # the tip's height
    surface_m: np.ndarray  # the dilated groove under it (with the cylinder's runout)
    fs_hz: float
    motion: tr.Motion  # the playing machine's mandrel

    def mistracking_fraction(self) -> float:
        return float(np.mean(self.force_n <= 0.0))


def play(
    spec: dict,
    groove: gv.Groove,
    rpm: float | None = None,
    progress: bool = False,
    motion_seed: int | None = None,
) -> Playback:
    """Plays the groove to its end. With a motion_seed, the playing machine's drive
    (config `player_motor`) turns the mandrel, loaded by the stylus' friction, and the
    cylinder's runout lifts the surface under the stylus (the floating weight's job) and
    modulates the groove's speed; else the mandrel turns at exactly `rpm`."""
    rep, num = spec["reproducer"], spec["numerics"]
    fs = num["fs_hz"]
    h = 1.0 / fs
    rpm = rep["rpm"] if rpm is None else rpm
    radius = spec["cylinder"]["diameter_m"] / 2
    v = groove_speed(spec, rpm)
    surface_grid = gv.dilate(groove.h_m, groove.ds_m, rep["tip_radius_along_m"])
    end = groove.length_m - 2 * groove.ds_m
    if motion_seed is None:
        motion = tr.ideal(groove.length_m / v, fs, rpm, radius)
    else:
        m = spec["player_motor"]
        load = rep["stylus_friction"] * rep["downforce_n"] * radius + m["feed_friction_n_m"]
        motion = tr.simulate(
            m, rpm, radius, 1.05 * groove.length_m / v + 0.2, fs, load, motion_seed, "player"
        )
    n = int(np.searchsorted(motion.s_m, end))
    s = motion.s_m[:n]
    surf = np.interp(s, groove.s_m(), surface_grid) + motion.runout_m[:n]

    sys = reproducer_network(spec)
    st = Stepper(sys, h)
    p = st.p
    qg0, qg1 = st.input_cols("gravity")
    qc0, qc1 = st.input_cols("contact")
    cz = sys.pick("z_tip")
    cu = mouth_flow_row(spec, sys)
    kff = float(cz @ qc1)  # tip rise per newton at the step's end (> 0)
    big_k = contact_k(spec)
    alpha = rep["contact_damping_s_m"]
    # The bar's pivot on the weight passes (1 - 1/n) of the contact's force to the weight
    # and 1/n to the diaphragm (the body): the contact carries `downforce` at rest.
    load = rep["downforce_n"] * (1.0 - 1.0 / rep["lever_ratio"])
    ramp = int(0.01 * fs)

    def gravity(i: int) -> float:
        if i >= ramp:
            return -load
        return -load * 0.5 * (1 - np.cos(np.pi * i / ramp))

    x = np.zeros(len(sys.names))
    iz = sys.index("z_tip")
    x[iz] = surf[0]
    force = np.zeros(n)
    tip = np.zeros(n)
    flow = np.zeros(n)
    tip[0] = surf[0]
    f0 = 0.0
    d0 = 0.0
    held = (qg0 + qg1) * -load  # gravity once the ramp is over
    for i in range(1, n):
        if i <= ramp:
            xp = p @ x + qg0 * gravity(i - 1) + qg1 * gravity(i) + qc0 * f0
        else:
            xp = p @ x + held + qc0 * f0
        a = surf[i] - xp[iz]  # indentation if the force were 0
        f1 = 0.0
        if a > 0.0:
            f1 = _solve_contact(a, kff, big_k, alpha, d0, h)
            x = xp + qc1 * f1
        else:
            x = xp
        d0 = max(a - kff * f1, 0.0)
        force[i] = f1
        tip[i] = x[iz]
        flow[i] = cu @ x
        f0 = f1
        if progress and i % int(fs) == 0:
            print(f"  played {i / fs:.0f} s", flush=True)
    dudt = np.empty(n)
    dudt[0] = 0.0
    dudt[1:] = np.diff(flow) / h
    return Playback(pressure_gain(spec) * dudt, force, tip, surf, fs, motion)


def _solve_contact(
    a: float, kff: float, big_k: float, alpha: float, d_prev: float, h: float
) -> float:
    """The force f >= 0 at the step's end with f = K d^1.5 (1 + alpha (d - d_prev) / h),
    d = a - kff f (Hunt-Crossley, its rate by the step's difference). The residual is
    increasing in f on [0, a / kff]: bisection safeguarding Newton."""
    lo, hi = 0.0, a / kff
    f = min(big_k * a**1.5, hi)
    for _ in range(60):
        d = a - kff * f
        rate = 1.0 + alpha * (d - d_prev) / h
        law = big_k * d**1.5 * rate
        if law < 0.0:  # separating faster than the wax recovers: no force
            law = 0.0
        r = f - law
        if r > 0:
            hi = f
        else:
            lo = f
        if abs(r) <= 1e-12 * max(1.0, f):
            return f
        dlaw = -kff * big_k * (1.5 * d**0.5 * rate + d**1.5 * alpha / h) if law > 0 else 0.0
        step = r / (1.0 - dlaw)
        fn = f - step
        f = fn if lo < fn < hi else 0.5 * (lo + hi)
        if hi - lo <= 1e-15 * max(1.0, hi):
            return f
    return f


def to_output_rate(x: np.ndarray, fs_sim: float, fs_out: float) -> np.ndarray:
    return resample_poly(x, int(fs_out), int(fs_sim))
