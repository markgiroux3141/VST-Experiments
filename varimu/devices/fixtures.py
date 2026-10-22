"""Device fixtures for the Rust engine: the Python models evaluated on grids.

crates/circuitsim/tests/devices.rs checks its compiled models against these
values (to 1e-12), so the Python models stay the single source of truth.
Written by scripts/export_circuit_fixtures.py; tests/test_circuitsim_devices.py
checks the file is current.

Port conventions are the Rust engine's: port j is pin j relative to the last
pin (the cathode), and the currents flow into pins 0..P-1:
- triode (p, g, k): ports (Vpk, Vgk), currents (Ip, Ig);
- pentode (p, g2, g1, k): ports (Vpk, Vg2k, Vg1k), currents (Ip, Ig2, Ig1);
- diodes (a, k): port Vak, current I;
- magnetic core (b, ref): port B / TESLA_PER_V, current path * H. A core has
  memory, so each of its points also records the state it is evaluated
  from ([b, h, delta]: the last accepted point), taken along a magnetization
  history: demagnetized, up, back down, into saturation.
"""

from __future__ import annotations

import dataclasses
import itertools
import json

import numpy as np

from varimu.circuit import netlist as nl
from varimu.circuit.ir import model_to_dict
from varimu.devices.core import DEMAGNETIZED, TESLA_PER_V, MagneticCore, core_model
from varimu.devices.diode import JunctionDiode, VacuumDiode
from varimu.devices.library import load_device
from varimu.devices.pentode import Pentode
from varimu.devices.triode import Triode

# Tube mismatch, as in the netlist golden cases (export_circuit_fixtures.py).
MISMATCH = {
    "v6386_a.emission_scale": 0.8,
    "v6386_a.mu_spread": 1.05,
    "v6386_a.grid_contact_v": -0.6,
    "v6386_b.emission_scale": 1.1,
    "v6386_b.mu_spread": 0.97,
}

# Cutoff, class A, grid conduction, negative plate (Koren clamps E1 at 0).
_TRIODE_VG = (-80, -40, -20, -10, -5, -2, -1, -0.7, -0.5, -0.2, 0, 0.3, 1, 3)
_TRIODE_VP = (-20, -1, 0, 0.5, 5, 25, 100, 180, 250, 400)
# The screen floor (1 mV) and both sides of it; negative plate (atan < 0).
_PENTODE_VG1 = (-80, -40, -20, -10, -3, 0, 1)
_PENTODE_VG2 = (-5, 0, 5e-4, 1e-3, 2e-3, 10, 100, 250, 300)
_PENTODE_VP = (-10, 0, 1, 10, 50, 250, 400)
# Reverse bias through the knee to series-resistance-dominated conduction.
_JUNCTION_V = (-100, -10, -1, -0.2, *np.round(np.arange(-0.1, 1.5001, 0.02), 10), 2, 3, 5, 10, 20)
_VACUUM_V = (-50, -5, -1, -0.3, -0.1, 0, 0.05, 0.1, 0.5, 1, 5, 20, 50, 100, 300)
# Core: B history (T) whose accepted points are the states, and offsets from each state's B.
_CORE_HISTORY = (0.0, 0.6, 0.3, 1.2, -0.4, 1.9)
# (not multiples of DB_MAX: there the substep count changes, a ~1e-8 relative jump that
# finite differences would see)
_CORE_DB = (
    *(-x for x in (0.9713, 0.3071, 0.0473, 4.73e-3, 7e-4, 1e-6)),
    0.0,
    *(1e-6, 7e-4, 4.73e-3, 0.0473, 0.3071, 0.9713),
)
# A literature set with a wide loop (Jiles & Atherton 1986, via Holters & Zoelzer, DAFx-16,
# Table 1, c converted to the 1992 form), for the fixtures only.
_JA1986 = MagneticCore("CORE_JA1986", 1.6e6, 1100.0, 400.0, 0.17, 1.6e-3, 0.1)


def _models() -> list:
    default = nl.build().ir.models
    mismatch = [
        dataclasses.replace(m, name=m.name + "_mismatch")
        for m in nl.build(MISMATCH).ir.models
        if m.name.startswith("6386")
    ]
    ax7 = next(m for m in default if m.name.startswith("12AX7_"))
    diode = next(m for m in default if isinstance(m, JunctionDiode))
    extra = [
        dataclasses.replace(ax7, name="12AX7_no_grid", grid=None),
        dataclasses.replace(diode, name=diode.name + "_rs0", rs_ohm=0.0),
        load_device("GZ34"),
        core_model("CORE_GO", "grain_oriented_si_steel", 0.1),
        core_model("CORE_NI", "permalloy_fluxgate", 0.08),
        core_model("CORE_MU", "mumetall", 0.07),
        _JA1986,
    ]
    return [*default, *mismatch, *extra]


def _core_points(m: MagneticCore):
    states, state = [], DEMAGNETIZED
    for b in _CORE_HISTORY:
        # walk there in 10 mT steps, accepting each (as a transient would)
        for bj in np.linspace(state.b, b, max(2, int(abs(b - state.b) / 0.01) + 1))[1:]:
            state = m.advance(float(bj), state)
        states.append(state)
    ports, currents, st = [], [], []
    for s in states:
        for db in _CORE_DB:
            v = (s.b + db) / TESLA_PER_V
            ports.append((v,))
            currents.append((m.port_current(v, s)[0],))
            st.append((s.b, s.h, s.delta))
    return ports, currents, st


def _evaluate(m) -> tuple[list[list[float]], list[list[float]]]:
    if isinstance(m, Triode):
        ports = [(vp, vg) for vg, vp in itertools.product(_TRIODE_VG, _TRIODE_VP)]
        vp, vg = np.array(ports, float).T
        currents = np.stack([m.ip(vg, vp), m.ig(vg)], axis=1)
    elif isinstance(m, Pentode):
        grid = itertools.product(_PENTODE_VG1, _PENTODE_VG2, _PENTODE_VP)
        ports = [(vp, vg2, vg1) for vg1, vg2, vp in grid]
        vp, vg2, vg1 = np.array(ports, float).T
        currents = np.stack([m.ip(vg1, vg2, vp), m.ig2(vg1, vg2), m.ig1(vg1)], axis=1)
    elif isinstance(m, MagneticCore):
        ports, currents, _ = _core_points(m)
    elif isinstance(m, JunctionDiode | VacuumDiode):
        volts = _JUNCTION_V if isinstance(m, JunctionDiode) else _VACUUM_V
        if isinstance(m, JunctionDiode) and m.rs_ohm == 0:
            volts = tuple(v for v in volts if v <= 3)  # pure exponential beyond
        ports = [(float(v),) for v in volts]
        currents = m.i(np.array(volts, float))[:, None]
    else:
        raise TypeError(type(m))
    return [[float(v) for v in p] for p in ports], np.asarray(currents, float).tolist()


def device_fixtures() -> dict:
    out = []
    for m in _models():
        ports, currents = _evaluate(m)
        entry = {"model": model_to_dict(m), "ports": ports, "currents": currents}
        if isinstance(m, MagneticCore):
            entry["states"] = [list(s) for s in _core_points(m)[2]]
        out.append(entry)
    return {"devices": out}


def device_fixtures_json() -> str:
    return json.dumps(device_fixtures(), indent=1) + "\n"
