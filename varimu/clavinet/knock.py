"""The knock (docs/CLAVINET_PLAN.md, CL4): the tangent slamming the string onto the anvil
kicks the board the anvils stand on, and the board's ringing moves the anvil under the
pinched string, which the pickups hear ([G13] 3.5: 'a knock sound, due to the tangent
hitting the stud and hence the soundboard ... most of its energy below 1,200 Hz').

**The board** is a simply supported orthotropic-free plate (plywood, provisional
dimensions) with its modes analytic: f_mn = pi/2 sqrt(D / (rho h)) ((m/a)^2 + (n/b)^2),
mass-normalized shapes 2 / sqrt(rho h a b) sin(m pi x / a) sin(n pi y / b), a loss factor
on every mode. Each key's anvil stands at its own place on it (a line along the board).

**One way:** the anvil's contact force during the strike (the strike's stepper records it)
drives the board's modes at that anvil; the board's motion there, less its static
deflection, pushes the pinched string through the anvil's contact stiffness along the
anvil's normal for the rest of the note (`note.play`, `knock=True`). The string's reaction
on the board is left out (the board is ~1000x the string's mass at the anvil), and so is
the knock heard through the air (the pickups only hear the string).
"""

from __future__ import annotations

import functools
from dataclasses import dataclass

import numpy as np

from varimu.clavinet import spec


@dataclass(frozen=True)
class Board:
    omega: np.ndarray  # rad/s per mode
    zeta: np.ndarray
    shape_at: np.ndarray  # (keys, modes): the mass-normalized shape at each key's anvil


@functools.cache
def board(name: str = "d6", f_max_hz: float = 4000.0) -> Board:
    cfg = spec.load(name)
    kb = cfg["keybed"]
    a, b, h = kb["length_m"], kb["width_m"], kb["thickness_m"]
    e, rho, nu = kb["youngs_pa"], kb["density_kg_m3"], kb["poisson"]
    d = e * h**3 / (12 * (1 - nu * nu))
    rh = rho * h
    keys = int(cfg["tuning"]["keys"])
    x0, x1 = kb["anvil_line_m"]
    xa = x0 + (x1 - x0) * np.arange(keys) / (keys - 1)
    ya = kb["anvil_y_m"]
    om, sh = [], []
    for m in range(1, 80):
        for n in range(1, 40):
            w = (np.pi**2) * ((m / a) ** 2 + (n / b) ** 2) * np.sqrt(d / rh)
            if w > 2 * np.pi * f_max_hz:
                continue
            om.append(w)
            sh.append(
                2 / np.sqrt(rh * a * b) * np.sin(m * np.pi * xa / a) * np.sin(n * np.pi * ya / b)
            )
    om = np.array(om)
    return Board(om, np.full(om.size, kb["loss_factor"] / 2), np.array(sh).T)


def anvil_motion(
    n: int, force_n: np.ndarray, h_s: float, n_out: int, h_out: float, name: str = "d6"
) -> np.ndarray:
    """The board's dynamic displacement at key n's anvil (its static deflection under the
    press removed) at n_out samples of h_out after the strike: driven by the anvil's force
    history `force_n` (one per strike step of h_s; constant over each step), then by the
    press's static force (its last value), in closed form."""
    bd = board(name)
    phi = bd.shape_at[n - 1]
    om, ze = bd.omega, bd.zeta
    lam = -ze * om + 1j * om * np.sqrt(1 - ze * ze)
    # q'' + 2 zeta w q' + w^2 q = phi F; q = Im(Z) / w_d with Z' = lam Z + phi F
    e_step = np.exp(lam * h_s)
    g = (e_step - 1) / lam
    z = np.zeros(om.size, dtype=complex)
    for f in force_n:
        z = e_step * z + g * phi * f
    f_end = float(force_n[-1]) if force_n.size else 0.0
    t = h_out * np.arange(1, n_out + 1)
    et = np.exp(np.outer(t, lam))  # (n_out, modes)
    zt = et * z + (et - 1) / lam * phi * f_end
    wd = om * np.sqrt(1 - ze * ze)
    q = zt.imag / wd
    static = phi * phi / om**2 * f_end
    return (q * phi).sum(axis=1) - static.sum()
