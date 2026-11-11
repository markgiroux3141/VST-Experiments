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
- lamp (a, t, b): ports (Vab, T - T_amb), currents (I, dT/dt);
- BJT (c, b, e): ports (Vce, Vbe), currents (Ic, Ib);
- optocoupler (la, lk, s, ra, rb): ports (V(la), V(lk), V(s), V(ra)) re rb, currents
  (I_led, -I_led, -dg/dt / s_unit, I_cell);
- photocell (t, tb, s, ra, rb): ports (V(t), V(tb), V(s), V(ra)) re rb, currents
  (0, 0, -dg/dt / s_unit, I_cell);
- thyratron, tetrode (a, g2, g1, w, k): ports (Va, Vg2, Vg1, w), currents (Ia, Ig2, Ig1, -dw/dt);
  triode (a, g, w, k): ports (Va, Vg, w), currents (Ia, Ig, -dw/dt);
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
from varimu.devices.bjt import Bjt
from varimu.devices.carbon import Carbon
from varimu.devices.contact import Contact
from varimu.devices.core import DEMAGNETIZED, TESLA_PER_V, MagneticCore, core_model
from varimu.devices.diode import JunctionDiode, VacuumDiode
from varimu.devices.gyrator import Gyrator
from varimu.devices.jfet import Jfet
from varimu.devices.lamp import Lamp
from varimu.devices.library import load_device
from varimu.devices.opto import Optocoupler
from varimu.devices.pentode import Pentode
from varimu.devices.photocell import Photocell
from varimu.devices.thyratron import W_MAX, W_MIN, Thyratron
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
# A lamp from cold to past its rating, both polarities; temperatures below and above the
# fits' range (clamped), never on its edges.
_LAMP_V = (-40, -5, -0.3, 0, 0.02, 0.5, 2, 10, 28, 60)
_LAMP_DT = (-150, -40, 0, 1, 50, 300, 700, 1500, 2000, 2600, 3300)
# An optocoupler's LED off, at its knee, bright and past its tangent's start; its cell's
# state dark, dim, bright and (Newton's excursions) negative; the cell's voltage both ways.
_OPTO_VLED = (-2.0, 0.0, 1.3, 1.45, 1.55, 1.7, 2.6)
_OPTO_LK = (-3.0, 0.0, 5.0)
_OPTO_U = (-0.5, 0.0, 1e-4, 0.05, 1.0, 4.0)
_OPTO_VR = (-7.0, 0.0, 0.3, 12.0)
# A photocell's lamp below the floor (dark), cold, glowing, at its rating and past 2856 K,
# its reference pin both ways; its state and cell as the optocoupler's.
_PCELL_DT = (-250.0, 0.0, 700.0, 1500.0, 2000.0, 2556.0, 3000.0)
_PCELL_TB = (-21.0, 0.0, 17.0)
# A contact's springs both ways (a few volts: closed, the currents stay finite-difference
# sized); its control open, at both ends of the smoothstep, inside it and closed.
_CONTACT_V = (-3.0, -0.5, 0.0, 0.4, 2.0)
_CONTACT_C = (-1.0, 0.0, 0.1, 0.25, 0.5, 0.75, 0.9, 1.0, 2.0)
# A carbon button pulled off (negative force), through its softened zero to pressed hard.
_CARBON_F = (-0.5, -0.02, 0.0, 0.005, 0.02, 0.1, 0.5, 2.0)
# A gyrator's two ports both ways, its field from reversed through zero to past nominal.
_GYR_V = (-30.0, -1.0, 0.0, 0.3, 12.0)
_GYR_F = (-2.0, 0.0, 0.5, 18.6, 40.0)
# A thyratron from reverse anode volts through the arc's drop to its strike, the grid from
# deep cutoff past its floating potential, the state from below its range (held) through
# the pre-breakdown densities and the arc to above its range (never on the range's edges).
_THY_VA = (-20, 0, 5, 9, 12, 16, 30, 100, 300)
_THY_VG = (-100, -20, -5, -2, -0.6, 0, 3)
_THY_VG2 = (-1, 0, 4)
_THY_W = (W_MIN - 10, -30, -8, -1, 2, 6, 10, W_MAX + 5)
# A BJT (NPN signs; a PNP's grid is negated) from reverse junctions through the active
# region to saturation, both junctions at most ~0.95 V forward (past that the currents
# would swamp the Jacobian test's absolute floor).
_BJT_VBE = (-5, -1, -0.2, 0, 0.3, 0.5, 0.6, 0.65, 0.7, 0.75, 0.8, 0.9)
_BJT_VCE = (-5, -0.5, 0, 0.05, 0.2, 1, 5, 20, 45)
# A JFET (N-channel signs; a P-channel grid is negated): cut off through the channel's
# square law to a forward gate, both modes, avoiding the models' VTO (a kink).
_JFET_VGS = (-8, -3.5, -2.7, -1.7, -1.2, -0.6, -0.2, 0, 0.3, 0.6, 0.8)
_JFET_VDS = (-12, -3, -1, -0.2, -0.01, 0, 0.01, 0.2, 1, 1.3, 3, 12)
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
        load_device("LAMP327@1"),
        load_device("VTL5C1@1"),
        dataclasses.replace(load_device("PDVP9203@1"), name="PDVP9203_40lux", lux=40.0),
        load_device("KEY_CONTACT@1"),
        load_device("KEY_BREAK@1"),
        load_device("CARBON_BUTTON@1"),
        load_device("2D21@1"),
        load_device("884@1"),
        load_device("EF804S@1"),  # the e1 screen law (pentode.py)
        load_device("E83F@1"),
        load_device("EF86@1"),  # CHAINS_PLAN.md WP28
        load_device("E88CC@1"),
        load_device("BC550C@1"),
        load_device("BC560C@1"),  # PNP
        # At temperature (bjt.py's "Temperature"): XTB set on the hot one.
        dataclasses.replace(load_device("BC550C@1"), name="BC550C_60C", temp_k=333.15, xtb=1.5),
        dataclasses.replace(load_device("BC560C@1"), name="BC560C_0C", temp_k=273.15),
        # JFETs (jfet.py): the square law, the doping tail B with a gate emission N, and a
        # P-channel one.
        Jfet("JFET_SQ", "njf", -3.0, 1.304e-3, lambda_per_v=2.25e-3, is_a=33.57e-15),
        Jfet("JFET_B", "njf", -2.0, 1e-3, lambda_per_v=0.01, is_a=1e-14, n=1.2, b=0.9, pb_v=0.8),
        Jfet("JFET_P", "pjf", -1.55, 2e-3, lambda_per_v=0.02, b=0.7, pb_v=1.0),
        core_model("CORE_GO", "grain_oriented_si_steel", 0.1),
        core_model("CORE_NI", "permalloy_fluxgate", 0.08),
        core_model("CORE_MU", "mumetall", 0.07),
        _JA1986,
        Gyrator("GYRATOR_FIELD", 0.0537),
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
    elif isinstance(m, Lamp):
        ports = [(float(v), float(u)) for v, u in itertools.product(_LAMP_V, _LAMP_DT)]
        v, u = np.array(ports, float).T
        currents = np.stack(m.currents(v, u), axis=1)
    elif isinstance(m, Optocoupler):
        grid = itertools.product(_OPTO_VLED, _OPTO_LK, _OPTO_U, _OPTO_VR)
        ports = [(vl + lk, lk, u, vr) for vl, lk, u, vr in grid]
        currents = np.array([m.currents(p) for p in ports])
    elif isinstance(m, Photocell):
        grid = itertools.product(_PCELL_DT, _PCELL_TB, _OPTO_U, _OPTO_VR)
        ports = [(dt + tb, tb, u, vr) for dt, tb, u, vr in grid]
        currents = np.array([m.currents(p) for p in ports])
    elif isinstance(m, Gyrator):
        grid = itertools.product(_GYR_V, _GYR_V, _GYR_F)
        ports = [(float(a), float(b), float(c)) for a, b, c in grid]
        currents = np.array([m.currents(p) for p in ports])
    elif isinstance(m, Carbon):
        grid = itertools.product(_CONTACT_V, _CONTACT_V, _CARBON_F)
        ports = [(float(a), float(b), float(c)) for a, b, c in grid]
        currents = np.array([m.currents(p) for p in ports])
    elif isinstance(m, Contact):
        grid = itertools.product(_CONTACT_V, _CONTACT_V, _CONTACT_C)
        ports = [(float(a), float(b), float(c)) for a, b, c in grid]
        currents = np.array([m.currents(p) for p in ports])
    elif isinstance(m, Thyratron):
        if m.mu_g2 is None:
            grid = itertools.product(_THY_VA, _THY_VG, _THY_W)
        else:
            grid = itertools.product(_THY_VA, _THY_VG2, _THY_VG, _THY_W)
        ports = [tuple(float(x) for x in p) for p in grid]
        currents = np.stack(m.currents(*np.array(ports, float).T), axis=1)
    elif isinstance(m, Bjt):
        ports = [
            (m.sign * vce, m.sign * vbe)
            for vbe, vce in itertools.product(_BJT_VBE, _BJT_VCE)
            if max(vbe, vbe - vce) <= 0.95
        ]
        currents = np.stack(m.currents(*np.array(ports, float).T), axis=1)
        ports = [(float(a), float(b)) for a, b in ports]
    elif isinstance(m, Jfet):
        ports = [
            (m.sign * vds, m.sign * vgs)
            for vgs, vds in itertools.product(_JFET_VGS, _JFET_VDS)
            if vgs - vds <= 0.9
        ]
        currents = np.stack(m.currents(*np.array(ports, float).T), axis=1)
        ports = [(float(a), float(b)) for a, b in ports]
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
