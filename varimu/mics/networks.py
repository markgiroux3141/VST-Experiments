"""Capsule-only networks (MIC_ROOM_PLAN.md A2 / A3): a capsule as a small circuit IR
(the same elements the builders make, varimu.circuit.parts), solved in the frequency
domain (varimu.measure.ac) to fit and check capsules without rendering.

    h = dual_response(capsule, f_hz, theta_rad, path_m, polarization_v, pattern)

The electrode `out` into a load (c_load_f || r_load_ohm) to the backplate's AC ground;
the response is volts at `out` per pascal of a plane wave at the capsule's centre
(varimu.mics.free_field), for the cardioid pattern (only the front diaphragm polarized,
the rear electrode held at the backplate) or omni (both polarized, both electrodes on
`out`).
"""

from __future__ import annotations

import numpy as np

from varimu.circuit import parts
from varimu.circuit.ir import (
    GROUND,
    Capacitor,
    CircuitIR,
    Control,
    Resistor,
    Section,
    VoltageProbe,
)
from varimu.devices.capsule import DualCapsule
from varimu.devices.moving_coil import MovingCoil
from varimu.measure import ac
from varimu.mics.free_field import entry_factors, sphere_entry_factors

PATTERNS = ("cardioid", "omni")


def dual_ir(
    c: DualCapsule,
    polarization_v: float,
    pattern: str,
    r_load_ohm: float = 60e6,
    c_load_f: float = 0.0,
) -> CircuitIR:
    """The capsule (front pressure `in`, rear pressure on the control input `p_rear`,
    the backplate grounded) into its load on `out`."""
    if pattern not in PATTERNS:
        raise ValueError(f"pattern {pattern!r} ({PATTERNS})")
    omni = pattern == "omni"
    els = parts.capsule_dual(
        "KK", "in", "p_rear", GROUND, "out", "out" if omni else "re",
        c, polarization_v, polarization_v if omni else 0.0,
    )  # fmt: skip
    els.append(Resistor("RLOAD", "out", GROUND, r_load_ohm))
    if c_load_f > 0:
        els.append(Capacitor("CLOAD", "out", GROUND, c_load_f))
    if not omni:  # the unpolarized rear electrode, held at the backplate (as the U47's)
        els.append(Resistor("RREAR", "re", GROUND, 1e12))
    return CircuitIR(
        title="capsule",
        input_node="in",
        probes=(VoltageProbe("out"),),
        models=(),
        sections=(Section("capsule", tuple(els)),),
        controls=(Control("p_rear", "p_rear"),),
    )


def dual_response(
    c: DualCapsule,
    f_hz: np.ndarray,
    theta_rad: float,
    path_m: float,
    polarization_v: float,
    pattern: str,
    sphere: tuple[float, float] | None = None,
    entries: tuple[np.ndarray, np.ndarray] | None = None,
    **load,
) -> np.ndarray:
    """Complex volts at the electrode per pascal of a plane wave from theta_rad: the
    entries `path_m` apart in free field, or on a rigid sphere (`sphere` = (radius_m,
    cap_radius_m): varimu.mics.free_field.sphere_entry_factors; path_m unused), or given
    (`entries` = (front, rear) at f_hz: e.g. the capsule's body, free_field.
    body_entry_factors)."""
    f_hz = np.asarray(f_hz, float)
    if entries is not None:
        front, rear = (np.asarray(e, complex) for e in entries)
    elif sphere is not None:
        front, rear = sphere_entry_factors(f_hz, theta_rad, *sphere)
    else:
        front, rear = entry_factors(f_hz, theta_rad, path_m)
    ir = dual_ir(c, polarization_v, pattern, **load)
    return front * ac.transfer(ir, f_hz, "out", drives={"p_rear": rear / front})


# --- Moving-coil cartridges (docs/SM57_PLAN.md, SM2) -------------------------------------------


def moving_coil_ir(c: MovingCoil, r_load_ohm: float = 1e9) -> CircuitIR:
    """The cartridge (front pressure `in`, rear pressure on the control input `p_rear`)
    with its coil into a load r_load_ohm on `out` (the coil's minus grounded)."""
    els = parts.moving_coil("MC", "in", "p_rear", "out", GROUND, c)
    els.append(Resistor("RLOAD", "out", GROUND, r_load_ohm))
    if not any(x == "rear" for e in c.elements for x in (e.a, e.b)):
        els.append(Resistor("RREAR", "p_rear", GROUND, 1.0))  # a pressure cartridge: unused
    return CircuitIR(
        title="cartridge",
        input_node="in",
        probes=(VoltageProbe("out"),),
        models=(),
        sections=(Section("cartridge", tuple(els)),),
        controls=(Control("p_rear", "p_rear"),),
    )


def moving_coil_response(
    c: MovingCoil,
    f_hz: np.ndarray,
    entries: tuple[np.ndarray, np.ndarray],
    r_load_ohm: float = 1e9,
) -> np.ndarray:
    """Complex volts at the coil per pascal of the wave whose entry pressures (front, rear)
    at f_hz are `entries` (free_field.entry_factors, a body's, ...)."""
    f_hz = np.asarray(f_hz, float)
    front, rear = (np.asarray(e, complex) for e in entries)
    ir = moving_coil_ir(c, r_load_ohm)
    return front * ac.transfer(ir, f_hz, "out", drives={"p_rear": rear / front})
