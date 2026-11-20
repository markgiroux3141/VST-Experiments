"""A shellac 78, recorded acoustically and played on an acoustic gramophone (docs/PHONO_PLAN.md
G2 with G4's lateral recorder; config/phono/victor_exhibition.yaml).

Recording (linear, `record`): sound at the recording horn's mouth -> the horn -> the air in
front of the diaphragm -> the diaphragm -> a stylus bar (a lever) -> the lateral cutter
sweeping sideways through the wax blank against its cutting resistance. The cutter's
lateral excursion is the groove's centre line (disc.py), written along the spiral's arc
length as the recording turntable actually turned (its weight-driven motor: transport.py).
The loud passages cut `max_amplitude_m` (the engineer's placement, as the cylinder's).

Playing (nonlinear, `play`): the groove's two walls, each dilated by the steel needle's
worn point (disc.py), read along the arc the player's turntable passes (its spring motor,
governor and worm; the record's off-centre hole and warp), through the pivoted arm's
tracking error -> two Hertz contacts with Hunt-Crossley damping, one per wall, each along
its normal (player.py's coupled contacts) -> the tip, laterally on the needle's bending
spring to the chuck, the chuck on the stylus bar's tension springs, the bar a lever
pivoted in the sound-box -> the mica diaphragm (its clamped fundamental, cylinder.py's
`diaphragm`) -> the air in front of it -> the neck, the tapered tone arm and the flower
horn (horn.py) -> the mouth's radiation; vertically the tip carries the sound-box and
arm's weight. The output is the power the mouth radiates, as a pressure 1 m away
(`output_row`).

Simplifications (documented, each a candidate for later): the sound-box's body is fixed
laterally (the arm's lateral inertia is ~10^4 times the moving system's: it follows only
the spiral's drift and the eccentricity, both sub-audio, left out); the needle's angle to
the record is not modelled; the contact's stiffness is the new point's (a worn flat is
stiffer); the shellac doesn't wear yet (wear.py is the cylinder's).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.signal import fftconvolve, resample_poly

from varimu.phono import cylinder as cy
from varimu.phono import damage as dm
from varimu.phono import disc, horn
from varimu.phono import groove as gv
from varimu.phono import player as pl
from varimu.phono import transport as tr
from varimu.phono.network import GROUND, Network, Stepper, System

IR_SECONDS = 0.25


def load(name: str = "victor_exhibition") -> dict:
    return cy.load(name)


def wall_angle(spec: dict) -> float:
    return np.deg2rad(spec["record"]["wall_angle_deg"])


def _diaphragm(b: dict) -> cy.Diaphragm:
    return cy.diaphragm(
        b["diaphragm_radius_m"],
        b["diaphragm_thickness_m"],
        b["diaphragm_youngs_pa"],
        b["diaphragm_density_kg_m3"],
        b["diaphragm_poisson"],
        b["diaphragm_q"],
    )


# Recording.


def is_electrical(spec: dict) -> bool:
    return "electrical_recorder" in spec


def electrical_recorder_network(spec: dict) -> System:
    """The Western Electric recorder (Maxfield and Harrison's Fig. 12) as a mid-series
    terminated three-section low-pass filter in the mobility analogy: the armature (half a
    section's mass, the field's negative stiffness to the frame), the coupling shaft (the
    shunt compliance), the stylus and its holder (a full section's mass, the balancing
    springs to the frame), the shaft to the coupling disk, the disk (half a section's mass),
    the rubber line as a resistance (`termination_ratio` times z0 = pi f_c m). The input
    'p_src' is the force on the armature per pascal at the condenser transmitter (flat: the
    gain doesn't matter, the cut is set by its loud passages). In the band the stylus'
    velocity follows the force (uniform velocity); below the balancing springs' turnover
    their stiffness rules (uniform amplitude); above f_c the filter cuts."""
    e = spec["electrical_recorder"]
    fc, m = e["cutoff_hz"], e["stylus_mass_kg"]
    z0 = np.pi * fc * m
    k_shunt = (np.pi * fc) ** 2 * m
    k_turn = 2 * np.pi * e["turnover_hz"] * z0
    r_loss = z0 / e["loss_q"]
    net = Network()
    net.current_source("arm", "p_src")
    net.capacitor("arm", GROUND, m / 2)
    net.inductor("arm", GROUND, -1.0 / e["negative_stiffness_n_m"], "k_field")
    net.conductance("arm", GROUND, r_loss)
    net.inductor("arm", "cut", 1.0 / k_shunt, "k_shaft")
    net.capacitor("cut", GROUND, m)
    net.inductor("cut", GROUND, 1.0 / (k_turn + e["negative_stiffness_n_m"]), "k_balance")
    net.conductance("cut", GROUND, r_loss)
    net.inductor("cut", "disk", 1.0 / k_shunt, "k_disk_shaft")
    net.capacitor("disk", GROUND, m / 2)
    net.conductance("disk", GROUND, e["termination_ratio"] * z0)  # the rubber line
    net.integrator("cut", "x_cut")
    return net.compile()


def recorder_network(spec: dict) -> System:
    """The acoustic recorder or, when the config has an `electrical_recorder` block, the
    electrical one; either way the input 'p_src' (per pascal) and the cutter's lateral
    excursion 'x_cut'."""
    if is_electrical(spec):
        return electrical_recorder_network(spec)
    air, rec = spec["air"], spec["recorder"]
    rho, c, dx = air["density_kg_m3"], air["sound_speed_m_s"], spec["numerics"]["dx_max_m"]
    net = Network()
    net.voltage_source("src", GROUND, "p_src")
    horn.radiation(net, "mouth", "src", rec["horn_mouth_radius_m"], rho, c, "rad")
    horn.duct(
        net, "mouth", "throat", rec["horn_length_m"], rec["horn_mouth_radius_m"],
        rec["horn_throat_radius_m"], rho, c, dx, "horn",
    )  # fmt: skip
    horn.duct(
        net, "throat", "cav", rec["coupling_length_m"], rec["horn_throat_radius_m"],
        rec["horn_throat_radius_m"], rho, c, dx, "coup",
    )  # fmt: skip
    dia = _diaphragm(rec)
    vol = np.pi * rec["diaphragm_radius_m"] ** 2 * rec["cavity_height_m"]
    net.capacitor("cav", GROUND, vol / (rho * c * c))
    net.gyrator("d", "cav", dia.area_m2)
    net.capacitor("d", GROUND, dia.mass_kg)
    net.inductor("d", GROUND, 1.0 / dia.stiffness_n_m, "k_dia")
    net.conductance("d", GROUND, dia.resistance_ns_m)
    # The stylus bar: the cutter's lateral velocity n times the diaphragm's.
    net.transformer("d", GROUND, "cut", GROUND, rec["lever_ratio"], "lever")
    net.capacitor("cut", GROUND, rec["cutter_mass_kg"])
    net.conductance("cut", GROUND, rec["wax_cutting_resistance_ns_m"])
    net.integrator("cut", "x_cut")
    return net.compile()


def recorder_response(spec: dict, f_hz: np.ndarray) -> np.ndarray:
    """The cutter's lateral excursion per pascal of incident sound (m/Pa)."""
    sys = recorder_network(spec)
    x = sys.response(f_hz, "p_src")
    return x[:, sys.index("x_cut")] * _blocked(spec)


def _blocked(spec: dict) -> float:
    return 1.0 if is_electrical(spec) else spec["recorder"]["blocked_pressure_factor"]


@dataclass
class DiscRecord:
    y_m: np.ndarray  # the groove's centre line, lateral, per arc sample
    wall_l_m: np.ndarray  # each wall's position along its inward normal (surface included)
    wall_r_m: np.ndarray
    ds_m: float
    spiral: disc.Spiral
    z_m: np.ndarray  # the cutter's excursion at the simulation rate
    pa_per_unit: float
    lead_in_samples: int
    fs_hz: float
    omega: np.ndarray  # the recording turntable's angular velocity per sample
    s_m: np.ndarray  # arc length under the cutter per sample

    @property
    def length_m(self) -> float:
        return len(self.y_m) * self.ds_m

    def s_grid(self) -> np.ndarray:
        return np.arange(len(self.y_m)) * self.ds_m


def _motion(m: dict, rpm, r0, seconds, fs, load, seed, name, engine):
    """(omega, theta) per sample: ideal, or the machine's drive."""
    if seed is None:
        n = int(round(seconds * fs))
        w = 2 * np.pi * rpm / 60.0
        return np.full(n, w), w * np.arange(n) / fs
    mo = tr.simulate(m, rpm, r0, seconds, fs, load, seed, name, engine=engine)
    return mo.omega, mo.theta


def record(
    spec: dict,
    x: np.ndarray,
    fs_in_hz: float,
    drive: float = 1.0,
    start_radius_m: float | None = None,
    motion_seed: int | None = None,
    engine: str = "rust",
) -> DiscRecord:
    """Cuts the program x (any scale) into a lateral groove starting at `start_radius_m`
    (default the record's outer groove), acoustically or electrically (recorder_network).
    The walls are smooth (`surface`, `age` add the
    shellac's grain, dust and scratches)."""
    fs = spec["numerics"]["fs_hz"]
    up = resample_poly(np.asarray(x, dtype=float), int(fs), int(fs_in_hz))
    lead = int(round(spec["numerics"]["lead_in_s"] * fs))
    sig = np.concatenate([np.zeros(lead), up, np.zeros(int(0.05 * fs))])
    sys = recorder_network(spec)
    st = Stepper(sys, 1.0 / fs)
    # The unit sample at step 1 (the player's step 0 is its initial state; Stepper.run's
    # x_0 = Q1 u_0 is this run's step 1).
    n_ir = int(IR_SECONDS * fs)
    imp = np.zeros(n_ir + 1)
    imp[1] = 1.0
    ir = pl.run(
        st, np.zeros(len(sys.names)), {"p_src": imp}, [], sys.pick("x_cut"), n_ir + 1, engine
    ).outputs[0][1:]
    ir *= _blocked(spec)
    z_unit = fftconvolve(sig, ir)[: len(sig)]
    loud = float(np.percentile(np.abs(z_unit), spec["record"]["cut_level_percentile"]))
    scale = drive * spec["record"]["max_amplitude_m"] / (loud or 1.0)
    z = z_unit * scale
    r0 = spec["record"]["outer_radius_m"] if start_radius_m is None else start_radius_m
    spiral = disc.Spiral(r0, spec["record"]["pitch_m"])
    rpm = spec["record"]["rpm_recorded"]
    m = spec["recorder_motor"]
    omega, theta = _motion(
        m, rpm, r0, len(z) / fs, fs, m["feed_friction_n_m"], motion_seed, "recorder", engine
    )
    s = disc.arc_positions(omega, theta, fs, spiral, 0.0, 0.0)
    ds = r0 * 2 * np.pi * rpm / 60.0 / fs
    grid = np.arange(int(s[-1] / ds)) * ds
    y = np.interp(grid, s, z)
    wl, wr = disc.walls(y, wall_angle(spec))
    return DiscRecord(y, wl, wr, ds, spiral, z, scale, lead, fs, omega, s)


def surface(rec: DiscRecord, spec: dict, seed: int) -> None:
    """The shellac's grain on both walls (in place)."""
    srf = spec["surface"]
    gl, gr = disc.roughness_pair(len(rec.y_m), rec.ds_m, srf["sigma_m"], srf["corr_m"], seed)
    rec.wall_l_m += gl
    rec.wall_r_m += gr


def age(rec: DiscRecord, d: dict, seed: int) -> dict:
    """Dust (each grain on one wall) and scratches (in place). Returns the counts."""
    counts = {}
    for name, w in (("left", rec.wall_l_m), ("right", rec.wall_r_m)):
        g = gv.Groove(h_m=w, ds_m=rec.ds_m)
        counts[f"dust_{name}"] = dm.dust(g, d, seed, kind=f"dust {name}")
    counts["scratches"] = disc.scratches(rec.wall_l_m, rec.wall_r_m, rec.ds_m, rec.spiral, d, seed)
    return counts


# Playing.


@dataclass
class Needle:
    mass_kg: float  # the free part's modal mass at the tip (a cantilever's 33/140)
    stiffness_n_m: float  # 3 E I / L^3
    resistance_ns_m: float


def needle(spec: dict) -> Needle:
    sb = spec["soundbox"]
    length, dia = sb["needle_free_length_m"], sb["needle_diameter_m"]
    inertia = np.pi * dia**4 / 64
    k = 3 * sb["needle_youngs_pa"] * inertia / length**3
    m = 33.0 / 140.0 * sb["needle_density_kg_m3"] * np.pi * dia**2 / 4 * length
    return Needle(m, k, np.sqrt(k * m) / sb["needle_q"])


def contact_k(spec: dict) -> float:
    sb, r = spec["soundbox"], spec["record"]
    return gv.hertz_k(
        sb["tip_radius_m"], sb["tip_radius_m"], sb["needle_youngs_pa"], sb["needle_poisson"],
        r["shellac_youngs_pa"], r["shellac_poisson"],
    )  # fmt: skip


def wall_load(spec: dict) -> float:
    """Each wall's normal force at rest."""
    return spec["arm"]["downforce_n"] / (2 * np.cos(wall_angle(spec)))


def is_orthophonic(spec: dict) -> bool:
    return "orthophonic" in spec


def ortho_design(spec: dict) -> dict:
    """The Orthophonic's elements from Maxfield and Harrison's design equations (12)-(16)
    and (22): equal sections of cut-off f_c on the diaphragm's mass m."""
    o, air = spec["orthophonic"], spec["air"]
    fc, m = o["cutoff_hz"], o["diaphragm_mass_kg"]
    z0 = np.pi * fc * m  # mid-series impedance (eq. 15)
    k_section = (np.pi * fc) ** 2 * m  # 1 / c (eq. 14)
    rho_c = air["density_kg_m3"] * air["sound_speed_m_s"]
    a1 = o["diaphragm_area_m2"]
    a2 = rho_c * a1**2 / z0  # the horn's throat (eq. 22, G = rho c)
    m_flare = 4 * np.pi * o["horn_cutoff_hz"] / air["sound_speed_m_s"]  # the area's flare
    r_throat = np.sqrt(a2 / np.pi)
    return {
        "z0": z0,
        "k_section": k_section,
        "arm_ratio": np.sqrt(o["record_impedance_ns_m"] / z0),
        "k_soft": (2 * np.pi * o["soft_compliance_hz"]) ** 2 * m,
        "r_loss": z0 / o["loss_q"],
        "throat_radius_m": r_throat,
        "mouth_radius_m": r_throat * np.exp(m_flare * o["horn_length_m"] / 2),
        "chamber_m3": a1**2 * air["density_kg_m3"] * air["sound_speed_m_s"] ** 2 / k_section,
    }


def mouth_radius(spec: dict) -> float:
    if is_orthophonic(spec):
        return ortho_design(spec)["mouth_radius_m"]
    return spec["horn"]["mouth_radius_m"]


def _exhibition(net: Network, spec: dict, rho: float, c: float, dx: float) -> None:
    """The Exhibition sound-box from the needle's chuck to the horn's mouth."""
    sb, arm, hn = spec["soundbox"], spec["arm"], spec["horn"]
    loss = spec["numerics"]["duct_loss_hz"]
    net.capacitor("c", GROUND, sb["chuck_mass_kg"])
    net.inductor("c", GROUND, 1.0 / sb["pivot_stiffness_n_m"], "k_pivot")
    net.conductance("c", GROUND, sb["pivot_resistance_ns_m"])
    net.transformer("c", GROUND, "d", GROUND, sb["lever_ratio"], "lever")
    dia = _diaphragm(sb)
    net.capacitor("d", GROUND, dia.mass_kg + sb["link_mass_kg"])
    net.inductor("d", GROUND, 1.0 / dia.stiffness_n_m, "k_dia")
    net.conductance("d", GROUND, dia.resistance_ns_m)
    net.gyrator("d", "cav", dia.area_m2)
    vol = np.pi * sb["diaphragm_radius_m"] ** 2 * sb["cavity_height_m"]
    net.capacitor("cav", GROUND, vol / (rho * c * c))
    r_neck, r_arm = sb["neck_radius_m"], arm["tube_radius_out_m"]
    horn.duct(net, "cav", "elbow", sb["neck_length_m"], r_neck, r_neck, rho, c, dx, "neck", loss)
    horn.duct(net, "elbow", "throat", arm["tube_length_m"], r_neck, r_arm, rho, c, dx, "arm", loss)
    horn.exponential(
        net,
        "throat",
        "mouth",
        hn["length_m"],
        r_arm,
        hn["mouth_radius_m"],
        rho,
        c,
        dx,
        "horn",
        loss,
    )


def _orthophonic(net: Network, spec: dict, rho: float, c: float, dx: float) -> None:
    """The Orthophonic (Maxfield and Harrison's Fig. 16) from the needle's chuck to the
    horn's mouth, in the mobility analogy: their series masses are masses here (m1 the
    needle arm at the spider, m2 the spider, m3 the diaphragm), their shunt compliances the
    springs joining them (c3 the arm's end, c5 the spider's legs), their series
    compliances springs to the frame (c2 the pivot, c4 the arm's attachment, c6 the
    diaphragm's corrugated edge), the needle arm a lever of l2 / l1 = sqrt(4500 / 2920),
    the air chamber (c7) the cavity's compliance; their 'air chamber transformer' is the
    gyrator's area against the throat's here. The needle's bending spring is their
    needle-point compliance c1."""
    o, d = spec["orthophonic"], ortho_design(spec)
    m = o["diaphragm_mass_kg"]
    loss = spec["numerics"]["duct_loss_hz"]
    net.transformer("c", GROUND, "b", GROUND, d["arm_ratio"], "lever")
    for node, frame in (("b", "k_pivot"), ("sp", "k_attach"), ("d", "k_edge")):
        net.capacitor(node, GROUND, m)
        net.inductor(node, GROUND, 1.0 / d["k_soft"], frame)
        net.conductance(node, GROUND, d["r_loss"])
    net.inductor("b", "sp", 1.0 / d["k_section"], "k_arm_end")
    net.inductor("sp", "d", 1.0 / d["k_section"], "k_spider_legs")
    net.gyrator("d", "cav", o["diaphragm_area_m2"])
    net.capacitor("cav", GROUND, d["chamber_m3"] / (rho * c * c))
    r_t = d["throat_radius_m"]
    horn.duct(net, "cav", "throat", o["neck_length_m"], r_t, r_t, rho, c, dx, "neck", loss)
    horn.exponential(
        net,
        "throat",
        "mouth",
        o["horn_length_m"],
        r_t,
        d["mouth_radius_m"],
        rho,
        c,
        dx,
        "horn",
        loss,
    )


def reproducer_network(spec: dict, linear_contact: bool = False) -> System:
    """Lateral (node t: the tip, its displacement z_x) and vertical (node v, z_y). Inputs:
    'gravity' (the weight on v) and each wall's normal force 'f_left' / 'f_right' (into
    t and v by its direction cosines); with linear_contact, a 'groove' lateral velocity
    source drives the tip through both walls' contacts linearized at rest. The tip sits on
    the needle's bending spring to the chuck (node c); the sound-box is the Exhibition's
    or, when the config has an `orthophonic` block, the Orthophonic's."""
    air, arm = spec["air"], spec["arm"]
    rho, c, dx = air["density_kg_m3"], air["sound_speed_m_s"], spec["numerics"]["dx_max_m"]
    nd = needle(spec)
    net = Network()
    net.capacitor("t", GROUND, nd.mass_kg)
    net.inductor("t", "c", 1.0 / nd.stiffness_n_m, "k_needle")
    net.conductance("t", "c", nd.resistance_ns_m)
    (_orthophonic if is_orthophonic(spec) else _exhibition)(net, spec, rho, c, dx)
    horn.radiation(net, "mouth", GROUND, mouth_radius(spec), rho, c, "rad")
    net.integrator("t", "z_x")
    net.capacitor("v", GROUND, arm["vertical_mass_kg"])
    net.conductance("v", GROUND, arm["vertical_resistance_ns_m"])
    net.integrator("v", "z_y")
    a = wall_angle(spec)
    if linear_contact:
        k = contact_k(spec)
        f_w = wall_load(spec)
        delta0 = gv.static_indent(f_w, k)
        kc = 1.5 * k * np.sqrt(delta0)
        lat = 2 * np.sin(a) ** 2
        net.voltage_source("g", GROUND, "groove")
        net.inductor("g", "t", 1.0 / (lat * kc), "k_contact")
        net.conductance("g", "t", lat * spec["record"]["contact_damping_s_m"] * f_w)
    else:
        net.current_source("v", "gravity")
        for wall, sx in (("left", 1.0), ("right", -1.0)):
            net.current_source("t", f"f_{wall}", sx * np.sin(a))
            net.current_source("v", f"f_{wall}", np.cos(a))
    return net.compile()


def mouth_flow_row(spec: dict, sys: System) -> np.ndarray:
    a = mouth_radius(spec)
    air = spec["air"]
    res = air["density_kg_m3"] * air["sound_speed_m_s"] / (np.pi * a * a)
    return sys.pick("radLrad") + sys.element_current("mouth", GROUND, "g", 1.0 / res)


def pressure_gain(spec: dict) -> float:
    return spec["air"]["density_kg_m3"] / (4 * np.pi * spec["listening"]["distance_m"])


def output_row(spec: dict, sys: System) -> np.ndarray:
    """c with c @ x = the pressure at the listening distance r that the mouth's radiated
    power W gives spread over a sphere: p^2 / (rho c) 4 pi r^2 = W, W = p_mouth^2 / R
    (R = rho c / S, the radiation's resistance, carrying the real power), so p = p_mouth
    a / (2 r). Not the cylinder's on-axis monopole (rho / 4 pi r) dU/dt: for a mouth this
    large (0.56-0.82 m across) 1 m is in its near field, and that formula rises 6 dB per
    octave with constant volume velocity where a matched horn's power is flat. Maxfield
    and Harrison designed for flat power and measured it flat (Fig. 20 A): a listener in a
    room hears the power."""
    return mouth_radius(spec) / (2 * spec["listening"]["distance_m"]) * sys.pick("mouth")


def reproducer_response(spec: dict, f_hz: np.ndarray) -> np.ndarray:
    """Pressure at the listening position (`output_row`) per metre of lateral groove
    displacement, small signals (the contacts linearized at rest, a new needle): Pa/m."""
    sys = reproducer_network(spec, linear_contact=True)
    x = sys.response(f_hz, "groove")
    return x @ output_row(spec, sys) * 2j * np.pi * np.asarray(f_hz)


@dataclass
class Playback:
    pressure_pa: np.ndarray
    forces_n: np.ndarray  # (2, steps): each wall's normal force
    tip_x_m: np.ndarray  # lateral
    tip_y_m: np.ndarray  # vertical
    fs_hz: float
    omega: np.ndarray
    s_m: np.ndarray  # arc length under the needle per sample
    flat_m: np.ndarray  # the needle's flat half-length per groove sample

    def mistracking_fraction(self) -> float:
        """The fraction of samples with a wall out of contact."""
        return float(np.mean(np.any(self.forces_n <= 0.0, axis=0)))


def play(
    spec: dict,
    rec: DiscRecord,
    rpm: float | None = None,
    motion_seed: int | None = None,
    needle_played_m: float | None = 0.0,
    engine: str = "rust",
) -> Playback:
    """Plays the record to its end. `needle_played_m`: groove the steel needle has slid
    before this excerpt (0: a new needle, wearing as it plays; None: an unworn point
    throughout). With a motion_seed, the player's drive turns the turntable, the disc is
    off-centre and warped (config `disc`, phases seeded); else exactly `rpm`, true."""
    fs = spec["numerics"]["fs_hz"]
    h = 1.0 / fs
    sb, arm = spec["soundbox"], spec["arm"]
    rpm = spec["player"]["rpm"] if rpm is None else rpm
    spiral = rec.spiral
    a = wall_angle(spec)
    seconds = 1.05 * rec.length_m / (2 * np.pi * rpm / 60.0 * spiral.radius(rec.length_m)) + 0.2
    if motion_seed is None:
        omega, theta = _motion(None, rpm, spiral.r0_m, seconds, fs, 0.0, None, "player", engine)
        ecc = phase = warp = warp_phase = 0.0
    else:
        m = spec["player_motor"]
        friction = arm["stylus_friction"] * arm["downforce_n"] / np.cos(a)
        load = friction * spiral.r0_m + m["feed_friction_n_m"]
        omega, theta = _motion(
            m, rpm, spiral.r0_m, seconds, fs, load, motion_seed, "player", engine
        )
        g = disc.rng(motion_seed, "disc")
        phase, warp_phase = g.uniform(0, 2 * np.pi, 2)
        ecc, warp = spec["disc"]["eccentric_m"], spec["disc"]["warp_m"]
    s_t = disc.arc_positions(omega, theta, fs, spiral, ecc, phase)
    end = rec.length_m - 2 * rec.ds_m
    n = int(np.searchsorted(s_t, end))
    s_t, theta = s_t[:n], theta[:n]

    # The walls as the tip reads them: the tracking error, then the worn point.
    grid = rec.s_grid()
    phi = disc.tracking_angle(
        spiral.radius(grid),
        arm["length_m"],
        arm["pivot_to_spindle_m"],
        np.deg2rad(arm["offset_deg"]),
    )
    if needle_played_m is None:
        flat = np.zeros(len(grid))
    else:
        side_m = (
            sb["side_s"]
            * 2
            * np.pi
            * rpm
            / 60.0
            * 0.5
            * (spec["record"]["outer_radius_m"] + spec["record"]["inner_radius_m"])
        )
        flat = disc.needle_flat(needle_played_m + grid, sb["flat_after_side_m"], side_m)
    surfaces = []
    for w in (rec.wall_l_m, rec.wall_r_m):
        shifted = np.interp(grid + rec.y_m * np.tan(phi), grid, w) / np.cos(phi)
        dil = disc.dilate_worn(shifted, rec.ds_m, sb["tip_radius_m"], flat)
        surfaces.append(np.interp(s_t, grid, dil) + np.cos(a) * warp * np.cos(theta + warp_phase))

    sys = reproducer_network(spec)
    st = Stepper(sys, h)
    i = np.arange(n)
    ramp = int(0.01 * fs)
    f_down = arm["downforce_n"]
    grav = np.where(i >= ramp, -f_down, -f_down * 0.5 * (1 - np.cos(np.pi * i / ramp)))
    zx, zy = sys.pick("z_x"), sys.pick("z_y")
    k = contact_k(spec)
    alpha = spec["record"]["contact_damping_s_m"]
    contacts = [
        pl.Contact("f_left", np.sin(a) * zx + np.cos(a) * zy, k, alpha, surfaces[0]),
        pl.Contact("f_right", -np.sin(a) * zx + np.cos(a) * zy, k, alpha, surfaces[1]),
    ]
    rows = np.array([zx, zy, output_row(spec, sys)])
    r = pl.run(st, np.zeros(len(sys.names)), {"gravity": grav}, contacts, rows, n, engine)
    return Playback(r.outputs[2], r.forces, r.outputs[0], r.outputs[1], fs, omega[:n], s_t, flat)


def pitch_cents(rec: DiscRecord, pb: Playback) -> np.ndarray:
    """The played pitch's deviation (cents) per playback sample: the arc speed under the
    needle over the arc speed under the cutter at the same arc length."""
    h_rec, h_pb = 1.0 / rec.fs_hz, 1.0 / pb.fs_hz
    v_rec = np.gradient(rec.s_m, h_rec)
    v_pb = np.gradient(pb.s_m, h_pb)
    ratio = v_pb / np.interp(pb.s_m, rec.s_m, v_rec)
    return 1200 * np.log2(ratio / np.median(ratio))


def to_output_rate(x: np.ndarray, fs_sim: float, fs_out: float) -> np.ndarray:
    return resample_poly(x, int(fs_out), int(fs_sim))
