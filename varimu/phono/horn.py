"""Ducts and horns as acoustic ladders, and the mouth's radiation (network.py's impedance
analogy: pressure as volts, volume velocity as amperes).

A duct of length L with radius a(x) is cut into sections no longer than `dx_max_m`; each
section's air mass rho dx / S sits between two nodes and its compliance S dx / (rho c^2)
goes to ground split half to each end (Webster's equation in a lumped ladder: plane waves
in a slowly flaring duct; its first cut-off is c / (pi dx), far above the band). The
mouth's radiation is an unflanged pipe's: its end correction's air mass 0.6133 a rho / S
(Levine and Schwinger 1948) in parallel with rho c / S (the high-frequency limit). At low
frequencies that resistance is 1.5x the exact (ka)^2 / 4 value, +1.8 dB of radiation
damping below ka ~ 1: a documented approximation (`radiation`).
"""

from __future__ import annotations

import numpy as np

from varimu.phono.network import GROUND, Network

END_CORRECTION = 0.6133  # Levine and Schwinger (1948), the unflanged pipe's l / a at ka -> 0
# Air at 20 C (model knowledge, CRC Handbook values): for the walls' boundary layers.
AIR_VISCOSITY_PA_S = 1.81e-5
AIR_CONDUCTIVITY_W_MK = 0.0257
AIR_CP_J_KGK = 1005.0
AIR_GAMMA = 1.4


def _ladder(
    net: Network,
    nodes: list[str],
    radii: np.ndarray,
    dx: float,
    rho: float,
    c: float,
    prefix: str,
    loss_hz: float | None,
) -> None:
    """Sections between successive nodes. With `loss_hz`, the walls' viscous and thermal
    boundary layers (Kirchhoff 1868; the wide-tube limit, e.g. Keefe 1984, J. Acoust. Soc.
    Am. 75, 58) evaluated at that frequency: a series resistance per length sqrt(2 mu rho
    w) / (pi a^3) in each section (a node between it and the air's mass) and a shunt
    conductance per length (gamma - 1) w pi a^2 / (rho c^2) * delta_t / a at its ends,
    delta_t = sqrt(2 kappa / (rho c_p w)). Their sqrt(f) growth is left out (one value per
    section): set loss_hz where the losses matter (a duct's resonances below a horn's
    cut-off). Without it the ladder is lossless (the cylinder's)."""
    w = 2 * np.pi * loss_hz if loss_hz else 0.0
    for i in range(len(nodes) - 1):
        # Air mass over a cone section: rho * integral dx / S(x) = rho dx / (pi r0 r1).
        mass = rho * dx / (np.pi * radii[i] * radii[i + 1])
        vol = np.pi * dx * (radii[i] ** 2 + radii[i] * radii[i + 1] + radii[i + 1] ** 2) / 3
        comp = vol / (rho * c * c)
        if w:
            r_mean = 0.5 * (radii[i] + radii[i + 1])
            r_series = np.sqrt(2 * AIR_VISCOSITY_PA_S * rho * w) / (np.pi * r_mean**3) * dx
            mid = f"{prefix}R{i}"
            net.resistor(nodes[i], mid, r_series)
            net.inductor(mid, nodes[i + 1], mass, f"{prefix}L{i}")
            delta_t = np.sqrt(2 * AIR_CONDUCTIVITY_W_MK / (rho * AIR_CP_J_KGK * w))
            g = (AIR_GAMMA - 1) * w * comp * delta_t / r_mean
            net.conductance(nodes[i], GROUND, g / 2)
            net.conductance(nodes[i + 1], GROUND, g / 2)
        else:
            net.inductor(nodes[i], nodes[i + 1], mass, f"{prefix}L{i}")
        # Compliance of its volume, half to each end.
        net.capacitor(nodes[i], GROUND, comp / 2)
        net.capacitor(nodes[i + 1], GROUND, comp / 2)


def duct(
    net: Network,
    a: str,
    b: str,
    length_m: float,
    radius_in_m: float,
    radius_out_m: float,
    rho: float,
    c: float,
    dx_max_m: float,
    prefix: str,
    loss_hz: float | None = None,
) -> int:
    """A straight or conical duct from node a to node b, radii linear in x (a cone).
    Returns the number of sections. `loss_hz`: the walls' losses (`_ladder`)."""
    n = max(1, int(np.ceil(length_m / dx_max_m)))
    xs = np.linspace(0.0, length_m, n + 1)
    radii = radius_in_m + (radius_out_m - radius_in_m) * xs / length_m
    nodes = [a] + [f"{prefix}{i}" for i in range(1, n)] + [b]
    _ladder(net, nodes, radii, length_m / n, rho, c, prefix, loss_hz)
    return n


def exponential(
    net: Network,
    a: str,
    b: str,
    length_m: float,
    radius_in_m: float,
    radius_out_m: float,
    rho: float,
    c: float,
    dx_max_m: float,
    prefix: str,
    loss_hz: float | None = None,
) -> int:
    """An exponential horn from a to b: radius r_in (r_out / r_in)^(x / L), its area's
    flare constant m = 2 ln(r_out / r_in) / L and cut-off m c / (4 pi) (Webster, 1919).
    Each section is a cone between its end radii (`duct`'s formulas). Returns the number
    of sections."""
    n = max(1, int(np.ceil(length_m / dx_max_m)))
    xs = np.linspace(0.0, length_m, n + 1)
    radii = radius_in_m * (radius_out_m / radius_in_m) ** (xs / length_m)
    nodes = [a] + [f"{prefix}{i}" for i in range(1, n)] + [b]
    _ladder(net, nodes, radii, length_m / n, rho, c, prefix, loss_hz)
    return n


def exponential_cutoff_hz(length_m: float, radius_in_m: float, radius_out_m: float, c: float):
    return 2 * np.log(radius_out_m / radius_in_m) / length_m * c / (4 * np.pi)


def radiation(
    net: Network, mouth: str, outer: str, radius_m: float, rho: float, c: float, prefix: str
) -> tuple[float, float]:
    """The mouth's radiation load between `mouth` and `outer` (ground when playing; the
    incident sound's source when recording). Returns (air mass, resistance)."""
    area = np.pi * radius_m**2
    mass = rho * END_CORRECTION * radius_m / area
    res = rho * c / area
    net.inductor(mouth, outer, mass, f"{prefix}Lrad")
    net.resistor(mouth, outer, res)
    return mass, res


def radiation_exact(f_hz: np.ndarray, radius_m: float, rho: float, c: float) -> np.ndarray:
    """The ladder's mouth load evaluated in closed form (for tests): jwM || R."""
    area = np.pi * radius_m**2
    jwm = 2j * np.pi * f_hz * rho * END_CORRECTION * radius_m / area
    res = rho * c / area
    return jwm * res / (jwm + res)


def cylinder_input_impedance(
    f_hz: np.ndarray, length_m: float, radius_m: float, z_load, rho: float, c: float
) -> np.ndarray:
    """A cylindrical duct's input impedance on a load (plane waves, lossless): the
    transmission-line formula, the ladder's test."""
    z0 = rho * c / (np.pi * radius_m**2)
    kl = 2 * np.pi * f_hz / c * length_m
    t = np.tan(kl)
    return z0 * (z_load + 1j * z0 * t) / (z0 + 1j * z_load * t)


def stepped_input_impedance(
    f_hz: np.ndarray,
    length_m: float,
    radius_in_m: float,
    radius_out_m: float,
    z_load,
    rho: float,
    c: float,
    steps: int,
) -> np.ndarray:
    """A cone's input impedance as `steps` exact cylindrical segments (transmission lines
    at each segment's mean radius) chained from the mouth's load back to the throat: an
    independent reference that converges to Webster's equation as steps grow (the
    ladder's test)."""
    f_hz = np.asarray(f_hz, dtype=float)
    z = np.broadcast_to(np.asarray(z_load, dtype=complex), f_hz.shape).copy()
    dx = length_m / steps
    for i in reversed(range(steps)):
        r = radius_in_m + (radius_out_m - radius_in_m) * (i + 0.5) / steps
        z = cylinder_input_impedance(f_hz, dx, r, z, rho, c)
    return z
