"""The GE RP1560's mechanics playing a stereo LP (docs/PHONO_PLAN.md, "The 1960s record
player"; config/phono/ge_rp1560.yaml): the V-M changer's rim drive (rimdrive.py), the arm, and
the Sonotone 16T ceramic cartridge, out to each element's open-circuit EMF. The amplifier is a
circuit (config/circuits/ge_rp1560.yaml), fed those EMFs through the elements' capacitance.

**The walls as the tip reads them.** The record's walls (lp.py), read along the arc the
changer passes (its drive's speed, the record's off-centre hole), are remapped for the arm's
tracking error (lateral: disc.tracking_angle) and the cartridge's vertical angle (vertical:
microgroove.incline); each wall is then dilated by the 0.7 mil sphere (groove.dilate, exact
for a sphere on a wall that varies along the groove only). The warp and the changer's rumble
lift both walls together (vertical motion of the record's surface).

**The cartridge** (mobility analogy, network.py). The tip (nodes tx, tz: lateral outward,
vertical up) carries its mass and the two walls' Hertz contacts (player.py), each along its
normal. The cartridge's body is the arm's end (bx, bz: the arm's effective masses, its
bearings, the downforce on bz, the skating force on bx). The tip's motion relative to the body
along each element's axis (a resolver at 45 degrees plus `resolver_error_deg`: Sonotone's 25 dB
separation) is formed by two ideal transformers in series per axis; along it, the butyl link
(a spring with its loss) drives the resolver's mass, which bends the PZT bar: its stiffness,
loss and its piezoelectric coupling, a gyrator of N (C/m) to the element's electrical node
with its capacitance C0 and the amplifier's nominal load. The relative coordinates treat the
resolver's mass as moving with the body's frame: the body moves only below ~100 Hz, where that
mass's inertia is negligible.

The bar's open-circuit stiffness is its share of Sonotone's compliance; N is set so the element
gives Sonotone's 0.65 V at 1 kHz and 5 cm/s, and the open-circuit EMF is N / C0 times the bar's
deflection (`emf_row`).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from varimu.phono import cylinder as cy
from varimu.phono import disc, lp
from varimu.phono import groove as gv
from varimu.phono import microgroove as mg
from varimu.phono import player as pl
from varimu.phono import rimdrive as rd
from varimu.phono.network import GROUND, Network, Stepper, System


def load(name: str = "ge_rp1560") -> dict:
    return cy.load(name)


@dataclass
class Cartridge:
    k_link: float
    k_relax: float  # the link's relaxing spring (a standard linear solid's Maxwell arm)
    r_relax: float  # its damper
    m_yoke: float
    k_bar_short: float  # the bar's stiffness with its electrodes shorted
    r_bar: float
    n_c_m: float  # piezoelectric coupling, C/m
    c0_f: float


def cartridge(spec: dict, vinyl_e_pa: float, vinyl_nu: float) -> Cartridge:
    """The element values from the config's compliance, shares, Qs and output."""
    c, arm = spec["cartridge"], spec["arm"]
    comp = c["compliance_m_n"]
    k_link = 1.0 / (c["link_share"] * comp)
    k_bar_open = 1.0 / ((1 - c["link_share"]) * comp)
    m_arm = arm["lateral_mass_kg"]
    # The butyl link as a standard linear solid: k_link in parallel with k_relax in series
    # with a damper, relaxing at the arm resonance (rubber's loss peaks there and its
    # stiffness rises above it, unlike a dashpot's). k_relax = k_link / link_q sets the
    # loss peak (tan d ~ k_relax / (2 sqrt(k_link (k_link + k_relax)))).
    k_eff = k_link * k_bar_open / (k_link + k_bar_open)
    w_arm = np.sqrt(k_eff / m_arm)
    k_relax = k_link / c["link_q"]
    r_relax = k_relax / w_arm
    r_bar = np.sqrt((k_link + k_bar_open) * c["yoke_mass_kg"]) / c["bar_q"]
    # N for the output: at 1 kHz and 5 cm/s peak along the axis the bar deflects its share of
    # the tip's 7.96 um; the open-circuit EMF is N x / C0 (the 2 M load is nearly open there).
    # (static estimate; `network` rescales it to the network's own response at 1 kHz).
    x_tip = 0.05 / (2 * np.pi * 1000.0)
    x_bar = x_tip * k_link / (k_link + k_bar_open)
    n = (
        c["output_v"]
        * np.sqrt(2)
        * c["element_c_f"]
        / x_bar
        * spec["cartridge"].get("_n_scale", 1.0)
    )
    k_short = k_bar_open - n * n / c["element_c_f"]
    if k_short <= 0:
        raise ValueError("the cartridge's coupling exceeds its bar's stiffness")
    return Cartridge(
        k_link, k_relax, r_relax, c["yoke_mass_kg"], k_short, r_bar, n, c["element_c_f"]
    )


def calibrate(spec: dict, rec_spec: dict) -> dict:
    """The spec with N scaled so channel A gives `output_v` rms at 1 kHz and 5 cm/s peak in
    its plane (the bar's open-circuit stiffness held: k_short follows N)."""
    out = {k: dict(v) for k, v in spec.items()}
    out["cartridge"]["_n_scale"] = 1.0
    x1k = 0.05 / (2 * np.pi * 1000.0)
    for _ in range(6):
        v = abs(response(out, rec_spec, np.array([1000.0]))[0, 0]) * x1k / np.sqrt(2)
        out["cartridge"]["_n_scale"] *= spec["cartridge"]["output_v"] / v
    return out


def contact_k(spec: dict, rec_spec: dict) -> float:
    c, v = spec["cartridge"], rec_spec["vinyl"]
    return gv.hertz_k(
        c["tip_radius_m"], c["tip_radius_m"], c["tip_youngs_pa"], c["tip_poisson"],
        v["youngs_pa"] * v["dynamic_factor"], v["poisson"],
    )  # fmt: skip


def wall_load(spec: dict, rec_spec: dict) -> float:
    return spec["arm"]["downforce_n"] / (2 * np.cos(lp.wall_angle(rec_spec)))


def network(spec: dict, rec_spec: dict, linear_contact: bool = False) -> System:
    """Inputs: 'gravity' (on bz), 'skate' (on bx), each wall's normal force 'f_left' /
    'f_right' (into tx, tz by its direction cosines); with linear_contact, voltage sources
    'groove_l' / 'groove_r' drive each wall's linearized contact along its normal. States
    `z_x`, `z_z` (the tip's displacements), `bar_a`, `bar_b` (the bars' deflections)."""
    c, arm = spec["cartridge"], spec["arm"]
    a = lp.wall_angle(rec_spec)
    cart = cartridge(spec, rec_spec["vinyl"]["youngs_pa"], rec_spec["vinyl"]["poisson"])
    net = Network()
    net.capacitor("tx", GROUND, c["tip_mass_kg"])
    net.capacitor("tz", GROUND, c["tip_mass_kg"])
    net.capacitor("bx", GROUND, arm["lateral_mass_kg"])
    net.capacitor("bz", GROUND, arm["vertical_mass_kg"])
    net.conductance("bx", GROUND, arm["bearing_ns_m"])
    net.conductance("bz", GROUND, arm["bearing_ns_m"])
    err = np.deg2rad(c["resolver_error_deg"])
    for p, sx, ang in (("a", 1.0, a + err), ("b", -1.0, a + err)):
        # v(y) = sx sin(ang) v(tx - bx) + cos(ang) v(tz - bz): two transformers in series.
        net.transformer("tx", "bx", f"y{p}", f"m{p}", sx * np.sin(ang), f"Tx{p}")
        net.transformer("tz", "bz", f"m{p}", GROUND, np.cos(ang), f"Tz{p}")
        net.inductor(f"y{p}", f"r{p}", 1.0 / cart.k_link, f"klink{p}")
        net.inductor(f"y{p}", f"j{p}", 1.0 / cart.k_relax, f"krelax{p}")
        net.conductance(f"j{p}", f"r{p}", cart.r_relax)
        net.capacitor(f"r{p}", GROUND, cart.m_yoke)
        net.inductor(f"r{p}", GROUND, 1.0 / cart.k_bar_short, f"kbar{p}")
        net.conductance(f"r{p}", GROUND, cart.r_bar)
        net.gyrator(f"r{p}", f"e{p}", cart.n_c_m)
        net.capacitor(f"e{p}", GROUND, cart.c0_f)
        net.conductance(f"e{p}", GROUND, 1.0 / c["load_ohm"])
        net.integrator(f"r{p}", f"bar_{p}")
    net.integrator("tx", "z_x")
    net.integrator("tz", "z_z")
    if linear_contact:
        k = contact_k(spec, rec_spec)
        f_w = wall_load(spec, rec_spec)
        kc = 1.5 * k * np.sqrt(gv.static_indent(f_w, k))
        for wall, sx in (("l", 1.0), ("r", -1.0)):
            # The wall's normal displacement drives the tip through the contact's spring:
            # a node n moving at the wall's normal velocity, a spring from it along the
            # normal via a transformer to the tip's coordinates.
            net.voltage_source(f"g{wall}", GROUND, f"groove_{wall}")
            net.inductor(f"g{wall}", f"n{wall}", 1.0 / kc, f"kc{wall}")
            net.transformer("tx", GROUND, f"n{wall}", f"q{wall}", sx * np.sin(a), f"Nx{wall}")
            net.transformer("tz", GROUND, f"q{wall}", GROUND, np.cos(a), f"Nz{wall}")
    else:
        net.current_source("bz", "gravity")
        net.current_source("bx", "skate")
        for wall, sx in (("left", 1.0), ("right", -1.0)):
            net.current_source("tx", f"f_{wall}", sx * np.sin(a))
            net.current_source("tz", f"f_{wall}", np.cos(a))
    return net.compile()


def emf_rows(spec: dict, rec_spec: dict, sys: System) -> np.ndarray:
    """c with c @ x = each element's open-circuit EMF (N / C0 times its bar's deflection)."""
    cart = cartridge(spec, rec_spec["vinyl"]["youngs_pa"], rec_spec["vinyl"]["poisson"])
    g = cart.n_c_m / cart.c0_f
    return np.array([g * sys.pick("bar_a"), g * sys.pick("bar_b")])


def response(spec: dict, rec_spec: dict, f_hz: np.ndarray, wall: str = "l") -> np.ndarray:
    """Small-signal open-circuit EMFs (A, B) per metre of one wall's normal displacement
    (`wall` 'l' = channel A's): (len(f), 2), V/m."""
    sys = network(spec, rec_spec, linear_contact=True)
    x = sys.response(f_hz, f"groove_{wall}")  # per m/s of the wall's normal velocity
    return x @ emf_rows(spec, rec_spec, sys).T * (2j * np.pi * np.asarray(f_hz))[:, None]


@dataclass
class Playback:
    emf_v: np.ndarray  # (2, steps): elements A (left) and B (right), open circuit
    forces_n: np.ndarray  # (2, steps): each wall's normal force
    fs_hz: float
    omega: np.ndarray
    s_m: np.ndarray

    def mistracking_fraction(self) -> float:
        return float(np.mean(np.any(self.forces_n <= 0.0, axis=0)))


def play(
    spec: dict, rec_spec: dict, rec: lp.LPRecord, motion_seed: int | None = None,
    engine: str = "rust",
) -> Playback:  # fmt: skip
    """Plays the record to its end. With a motion_seed the changer's drive turns it (rimdrive),
    the disc is off-centre and warped (phases seeded) and the motor's rumble lifts it; else
    exactly 33-1/3, true and still."""
    fs = spec["numerics"]["fs_hz"]
    if abs(fs - rec.fs_hz) > 1e-9:
        raise ValueError("the player's rate must equal the record's")
    arm, c = spec["arm"], spec["cartridge"]
    a = lp.wall_angle(rec_spec)
    rpm = rec_spec["lathe"]["rpm"]
    sp = rec.spiral
    seconds = 1.05 * rec.length_m / (2 * np.pi * rpm / 60.0 * float(sp.r_m[-1])) + 0.2
    n_all = int(round(seconds * fs))
    f_down = arm["downforce_n"]
    if motion_seed is None:
        w0 = 2 * np.pi * rpm / 60.0
        omega, theta = np.full(n_all, w0), w0 * np.arange(n_all) / fs
        ecc = phase = warp = wphase = rumble = 0.0
    else:
        drag = arm["friction"] * f_down / np.cos(a) * sp.r0_m
        mo = rd.simulate(spec["changer"], rpm, seconds, fs, drag, motion_seed)
        omega, theta = mo.omega, mo.theta
        g = disc.rng(motion_seed, "disc")
        phase, wphase, rphase = g.uniform(0, 2 * np.pi, 3)
        ecc, warp = spec["disc"]["eccentric_m"], spec["disc"]["warp_m"]
        rumble = spec["changer"]["rumble_m"]
    s_t = _arc(omega, theta, fs, sp, ecc, phase)
    end = rec.length_m - 2 * rec.ds_m
    n = int(np.searchsorted(s_t, end))
    s_t, theta, omega = s_t[:n], theta[:n], omega[:n]

    grid = rec.s_grid()
    phi = disc.tracking_angle(sp.radius(grid), arm["length_m"], arm["pivot_to_spindle_m"],
                              np.deg2rad(arm["offset_deg"]))  # fmt: skip
    beta = np.deg2rad(arm["vertical_angle_deg"])
    x, z = mg.channels_to_xz(rec.wall_l_m, -rec.wall_r_m, a)
    shift = grid + x * np.tan(phi) + z * np.tan(beta)
    xr = np.interp(shift, grid, x) / np.cos(phi)
    zr = np.interp(shift, grid, z)
    walls = mg.walls(xr, zr, a)
    t = np.arange(n) / fs
    lift = warp * np.cos(theta + wphase)
    if rumble:
        lift = lift + rumble * np.sin(2 * np.pi * 2 * spec["changer"]["mains_hz"] * t + rphase)
    surfaces = []
    for w in walls:
        dil = gv.dilate(w, rec.ds_m, c["tip_radius_m"])
        surfaces.append(np.interp(s_t, grid, dil) + np.cos(a) * lift)

    sys = network(spec, rec_spec)
    st = Stepper(sys, 1.0 / fs)
    i = np.arange(n)
    ramp = int(0.01 * fs)
    grav = np.where(i >= ramp, -f_down, -f_down * 0.5 * (1 - np.cos(np.pi * i / ramp)))
    # Skating: the drag along the groove, offset from the arm's line, pulls the arm inward.
    skate = -arm["friction"] * f_down * np.tan(np.deg2rad(arm["offset_deg"])) * grav / -f_down
    zx, zz = sys.pick("z_x"), sys.pick("z_z")
    k = contact_k(spec, rec_spec)
    alpha = c["contact_damping_s_m"]
    contacts = [
        pl.Contact("f_left", np.sin(a) * zx + np.cos(a) * zz, k, alpha, surfaces[0]),
        pl.Contact("f_right", -np.sin(a) * zx + np.cos(a) * zz, k, alpha, surfaces[1]),
    ]
    rows = emf_rows(spec, rec_spec, sys)
    r = pl.run(st, np.zeros(len(sys.names)), {"gravity": grav, "skate": skate}, contacts, rows, n,
               engine)  # fmt: skip
    return Playback(r.outputs, r.forces, fs, omega, s_t)


def _arc(omega, theta, fs, sp: mg.TableSpiral, ecc: float, phase: float) -> np.ndarray:
    """Arc length under the stylus per sample (disc.arc_positions on a table spiral)."""
    return disc.arc_positions(omega, theta, fs, sp, ecc, phase)
