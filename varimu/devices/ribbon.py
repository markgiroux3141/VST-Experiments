"""Ribbon motors as lumped acoustic networks (docs/CHAINS_PLAN.md, WP5).

A ribbon is Olson's velocity microphone: a corrugated aluminium foil, loosely suspended in
the gap between two pole pieces, moved by the pressure difference between its faces. It is
the conductor itself: its EMF is B l v and its current pushes back on it. Olson's complete
mechanical circuit (SBE handbook sec. 4.1.3, Fig. 4.1.11, the RCA BK-11A; data/schematics/
rca_44bx/README.md): F1 -> R_L/2 -> M_L/2 -> [the ribbon, M_R + C_R, in parallel with the
slits between its edges and the pole pieces, M_S + R_S] -> M_L/2 -> R_L/2 -> F2, R_L and M_L
the air load and the damping screens on its two faces. Above its resonance the ribbon is
mass controlled: v = (P1 - P2) A_R / (j w (M_R + M_L)) (Eq. 4.1.6), E = B l v (Eq. 4.1.7).

A ribbon motor is a component (kind `ribbon_motor`, config/components/<name>/<N>.yaml): its
geometry and materials (sourced) and the lumped elements compiled from them here at fit time
(`varimu fit-devices`), in moving_coil's lumped format, so both circuit builders expand a
ribbon with the moving-coil code they already agree on (the part `ribbon_motor`:
varimu.circuit.parts.moving_coil, varimu-circuit's moving_coil.rs). The analogy is
moving_coil's: pressures as volts, volume velocities as currents, the network between
`front`, `rear`, `0` and the motor's own nodes, its elements of moving_coil's kinds (screen,
tube, slit, radiation, cavity, film, acoustic: varimu.devices.moving_coil's docstring) and
one of kind

    ribbon     the moving system, from the pressure on its front face (a) to its back face
               (b): the foil of `ribbon` (below) with its length modes in parallel, then
               the transducer

`ribbon` {length_m (clamped), width_m, thickness_m, density_kg_m3, resistivity_ohm_m,
corrugation (the foil's length per length of ribbon: the corrugations' share of its mass and
resistance), resonance_hz (the fundamental, its tuning: the foil's own, with its mass
alone; the air load in the network lowers the ribbon's resonance in place, the 44-BX's
from 18 to ~8 Hz), q (the foil's own loss per mode),
modes (how many length modes)}, `magnet` {b_gap_t, gap_length_m: the flux's extent along
the ribbon, B l = B min(length, gap_length)}, `leads` {r_ohm, l_h: the clamps, the ribbon's
loop and its leads to the transformer}.

The length modes: a limp ribbon clamped at both ends is a string under its small tension
(Olson's "limp" ribbon; its stiffness from the tension, so f_n = n f_1). A uniform pressure
and a uniform field couple only to the odd modes, n = 1, 3, 5, ..., each through its shape's
integral (2 / n pi of the length): mode n is an oscillator of mass M n^2 pi^2 / 8 on the
ribbon's area and B l, so every mode shares the gyrator's ratio B l / S, and the modes'
velocities add into the EMF and the volume velocity. In the impedance analogy that is a bank
of series branches (mass, compliance with its numerical leak, loss) in parallel from `a` to
the gyrator's node, one gyrator from there to `b`: the coil's current pushes on every mode
through the same port. Their mass fractions 8 / (n^2 pi^2) sum to 1, so the modes above the
`modes`-th are one more branch at the next odd mode's frequency with the rest of the mass:
above every mode the bank is the whole mass (Eq. 4.1.6), at DC every branch is stiff.
Elements <name>_n<k>_m (L), _c (C), _leak (R), _r (R) per mode k (n = 2k - 1; the last the
lumped rest), <name>_g the gyrator on node <name>_x.

Stops (the RCA 77-DX's shutter, CHAINS_PLAN.md WP7): a network element with `stops`, a list
of overrides of its fields (null: the element absent, e.g. the shutter closed), is compiled
once per stop k (0, 1, ...), its elements named <name>_s<k>... and tagged `stop: k`; every
other element is in every stop. A circuit picks one (the part's `stop`; `at_stop` here), and
the builders refuse a motor with stops when none is picked (varimu.circuit.parts.moving_coil).

The electrical side as moving_coil's: re_ohm = the foil's resistance (resistivity x length x
corrugation / (width x thickness)) + the leads', le_h the loop's inductance, no eddy branch
(l2_h 0). A fraction of an ohm: the step-up transformer is a separate part.
"""

from __future__ import annotations

import dataclasses
import math
from collections.abc import Mapping
from typing import Any

from varimu.devices import moving_coil as mc

KINDS = tuple(k for k in mc.KINDS if k != "diaphragm") + ("ribbon",)


def foil(g: Mapping[str, Any]) -> dict[str, float]:
    """The foil's figures from `ribbon` and `magnet` (SI): area, mass, resistance, B l."""
    r, m = g["ribbon"], g["magnet"]
    length, width, t = float(r["length_m"]), float(r["width_m"]), float(r["thickness_m"])
    corr = float(r.get("corrugation", 1.0))
    if not corr >= 1.0:
        raise ValueError(f"ribbon: corrugation {corr} (the foil's length per length, >= 1)")
    return {
        "area_m2": width * length,
        "mass_kg": float(r["density_kg_m3"]) * t * width * length * corr,
        "foil_ohm": float(r["resistivity_ohm_m"]) * length * corr / (width * t),
        "bl_tm": float(m["b_gap_t"]) * min(length, float(m.get("gap_length_m", length))),
    }


def stops(c: mc.MovingCoil) -> list[int]:
    """The stops a compiled motor's elements are tagged with (empty: none)."""
    return sorted({e.stop for e in c.elements if e.stop is not None})


def at_stop(c: mc.MovingCoil, stop: int | None) -> mc.MovingCoil:
    """The motor at one of its stops: the untagged elements and that stop's (a motor without
    stops: unchanged, and `stop` must be None)."""
    have = stops(c)
    if not have:
        if stop is not None:
            raise ValueError(f"{c.name} has no stops (stop {stop})")
        return c
    if stop is None or not 0 <= stop:
        raise ValueError(f"{c.name}: pick a stop (open ones: {have}; any other is closed)")
    els = tuple(dataclasses.replace(e, stop=None) for e in c.elements if e.stop in (None, stop))
    return dataclasses.replace(c, elements=els)


def mode_fractions(n_modes: int) -> list[tuple[int, float]]:
    """(n, mass fraction) of the odd length modes 1, 3, ..., 2 n_modes - 1 (8 / (n^2 pi^2)
    each), then the rest of the mass on the next odd mode."""
    if n_modes < 1:
        raise ValueError(f"ribbon: modes {n_modes} (at least the fundamental)")
    out = [(2 * k - 1, 8.0 / ((2 * k - 1) ** 2 * math.pi**2)) for k in range(1, n_modes + 1)]
    rest = 1.0
    for _, f in out:
        rest -= f
    return out + [(2 * n_modes + 1, rest)]


def compile_network(g: Mapping[str, Any]) -> dict[str, Any]:
    """The lumped elements of a ribbon motor from its geometry `g` (the module docstring),
    in moving_coil's lumped format."""
    r = g["ribbon"]
    fo = foil(g)
    s, m_total = fo["area_m2"], fo["mass_kg"]
    f1, q = float(r["resonance_hz"]), float(r["q"])
    leads = g.get("leads") or {}
    els: list[dict[str, Any]] = []
    names: set[str] = set()
    n_ribbon = 0
    for e in g["network"]:
        name, kind, a = str(e["name"]), str(e["kind"]), str(e["a"])
        b = str(e.get("b", "0"))
        if kind not in KINDS:
            raise ValueError(f"network element {name}: kind {kind!r} ({KINDS})")
        if name in names:
            raise ValueError(f"network element {name}: the name is taken")
        names.add(name)
        if kind == "ribbon" and "stops" in e:
            raise ValueError(f"network element {name}: the ribbon has no stops")
        if "stops" in e:
            base = {k: v for k, v in e.items() if k != "stops"}
            for k, over in enumerate(e["stops"]):
                if over is None:
                    continue
                for x in mc.compile_element({**base, **over, "name": f"{name}_s{k}"}):
                    els.append({**x, "stop": k})
            continue
        if kind != "ribbon":
            els += mc.compile_element(e)
            continue
        n_ribbon += 1
        x = f"{name}_x"
        m_a = m_total / (s * s)
        for k, (n, frac) in enumerate(mode_fractions(int(r["modes"])), 1):
            mk = m_a / frac
            wk = 2.0 * math.pi * n * f1
            ck = 1.0 / (wk * wk * mk)
            n1, n2 = f"{name}_n{k}_1", f"{name}_n{k}_2"
            els += [
                mc._el(f"{name}_n{k}_m", "L", a, n1, mk),
                mc._el(f"{name}_n{k}_c", "C", n1, n2, ck),
                mc._el(f"{name}_n{k}_leak", "R", n1, n2, mc._leak(ck)),
                mc._el(f"{name}_n{k}_r", "R", n2, x, wk * mk / q),
            ]
        els.append(mc._el(f"{name}_g", "G", x, b, fo["bl_tm"] / s))
    if n_ribbon != 1:
        raise ValueError(f"a ribbon motor has one ribbon ({n_ribbon} in its network)")
    re = fo["foil_ohm"] + float(leads.get("r_ohm", 0.0))
    return {
        "bl_tm": fo["bl_tm"],
        "sd_m2": s,
        "re_ohm": re,
        "le_h": float(leads["l_h"]),
        "l2_h": 0.0,
        "r2_ohm": 0.0,
        "elements": els,
        # Reported, not used by the network:
        "resonance_hz": f1,
        "gyrator_ohm": fo["bl_tm"] / s,
        "moving_mass_kg": m_total,
        "foil_ohm": fo["foil_ohm"],
    }
