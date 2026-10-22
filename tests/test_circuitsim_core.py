"""The hysteretic core in circuitsim against its Python reference, in circuits.

The device itself is checked value for value against Python
(crates/circuitsim/tests/devices.rs, fixtures from varimu.devices.fixtures).
Here it runs in circuits, against an exact solution of the same equations in
Python:

  source Vs -- R1 -- winding N1 -- ground,  (optionally) winding N2 -- R2 load,
  air gap on the core node.

The winding voltages are N A dB/dt and Ampere's law is
N1 i1 + N2 i2 = l_e H(B) + G_gap B, so with i1 = (Vs - N1 A B') / R1 and
i2 = -N2 A B' / R2 the circuit is one ODE in B,

  B' = (N1 Vs / R1 - l_e H - G_gap B) / (A (N1^2 / R1 + N2^2 / R2)),

with H(B) the JA path from the core's state: integrated alongside as
H' = dH/dB(B, H, delta) B', delta = sign(B'), each monotonic segment solved
by DOP853 at rtol 1e-11 and the reversals located as events. Drive: a 50 Hz
sine ramped into saturation plus 1 kHz, so the loop has saturation,
reversals and minor loops.

Also: the DK and full-MNA solvers agree on these circuits, and in the core's
linear limit (a resistor on the core node) Windings agree with ngspice (the
SPICE emission of a Winding) and with the equivalent coupled inductors.
"""

import dataclasses

import numpy as np
import pytest
from scipy.integrate import solve_ivp

from varimu.circuit.ir import (
    Capacitor,
    Coupling,
    Device,
    Inductor,
    Resistor,
    Winding,
)
from varimu.devices.core import MU0, TESLA_PER_V, core_model
from varimu.sim import fast, io

pytest.importorskip("circuitsim", reason="needs `uv sync --extra fast`")

from engine_compare import FS, circuit, compare_solvers  # noqa: E402

# Test fixtures, not modelled hardware: round numbers.
N1, N2, AREA, PATH = 500.0, 100.0, 1e-4, 0.1
R1, R2 = 100.0, 50.0
GAP_M = 20e-6
DUR_S = 0.1


def drive(t, amp):
    """50 Hz ramped from 0 to `amp` over the first 60 ms, plus 1 kHz at amp / 20."""
    ramp = np.minimum(1.0, t / 0.06)
    return amp * (ramp * np.sin(2 * np.pi * 50 * t) + 0.05 * np.sin(2 * np.pi * 1000 * t))


def build(material, *, secondary, gap, linear=False, eddy_f=0.0):
    """The test circuit; `linear`: the core in its linear limit (a resistor); `eddy_f`:
    a capacitance on the core node (eddy-current loss)."""
    core = core_model("JA", material, PATH)
    els = [
        Resistor("R1", "in", "w1", R1),
        Winding("LW1", "w1", "0", "u", N1, AREA),
    ]
    if secondary:
        els += [Winding("LW2", "w2", "0", "u", N2, AREA), Resistor("R2", "w2", "0", R2)]
    if gap:
        els.append(Resistor("RGAP", "u", "0", MU0 / (GAP_M * TESLA_PER_V)))
    if eddy_f:
        els.append(Capacitor("CEDDY", "u", "0", eddy_f))
    if linear:
        els.append(Resistor("RCORE", "u", "0", 1 / core.linear_conductance()))
        models = ()
    else:
        els.append(Device("XCORE", "JA", ("u", "0")))
        models = (core,)
    # (a linear build goes to ngspice, whose text has no core node)
    probes = ["w1"] + ([] if linear else ["u"]) + (["w2"] if secondary else [])
    return circuit(els, probes, models), core


def reference(core, amp, *, secondary, gap, t_out):
    """Exact solution (see the module docstring): winding voltages and B on t_out."""
    g_eff = N1**2 / R1 + (N2**2 / R2 if secondary else 0.0)
    g_gap = GAP_M / MU0 if gap else 0.0

    def num(t, b, h):
        return N1 * drive(t, amp) / R1 - PATH * h - g_gap * b

    out = np.zeros((2, len(t_out)))
    t0, y0, delta = 0.0, np.zeros(2), 1.0
    while t0 < t_out[-1]:

        def rhs(t, y, delta=delta):
            bd = num(t, y[0], y[1]) / (AREA * g_eff)
            return [bd, core.dh_db(y[0], y[1], delta) * bd]

        def reverse(t, y, delta=delta):
            return num(t, y[0], y[1]) + delta * 1e-12

        reverse.terminal, reverse.direction = True, -delta
        sol = solve_ivp(rhs, (t0, t_out[-1]), y0, method="DOP853", events=reverse,
                        dense_output=True, rtol=1e-11, atol=[1e-13, 1e-9])  # fmt: skip
        k = (t_out >= t0) & (t_out <= sol.t[-1])
        if k.any():
            out[:, k] = sol.sol(t_out[k])
        if sol.status != 1:
            break
        t0, y0, delta = sol.t[-1] + 1e-13, sol.y[:, -1], -delta
    b, h = out
    bd = (np.array([num(t, bb, hh) for t, bb, hh in zip(t_out, b, h, strict=True)])
          / (AREA * g_eff))  # fmt: skip
    return {"w1": N1 * AREA * bd, "w2": N2 * AREA * bd, "b": b}


def err_db(a, b):
    return 20 * np.log10(np.std(a - b) / np.std(b))


# (material, drive amplitude V, secondary, gap): saturating each material
CASES = {
    "steel_winding": ("grain_oriented_si_steel", 40.0, False, False),
    "steel_transformer_gap": ("grain_oriented_si_steel", 60.0, True, True),
    "nickel_transformer": ("permalloy_fluxgate", 40.0, True, False),
    "mumetall_transformer": ("mumetall", 6.0, True, True),
    "mumetall_saturated": ("mumetall", 15.0, True, True),
}


@pytest.fixture(scope="module")
def runs():
    """circuitsim at production settings, and converged, for every case."""
    prod = io.TransientSettings.from_sim_settings(engine="circuitsim")
    prod = dataclasses.replace(prod, full_scale_volts_peak=1.0)
    conv = dataclasses.replace(
        prod, oversample=8, error_abstol=prod.error_abstol / 10, error_reltol=prod.error_reltol / 10
    )
    t = np.arange(int(DUR_S * FS)) / FS
    out = {}
    for name, (mat, amp, sec, gap) in CASES.items():
        ir, core = build(mat, secondary=sec, gap=gap)
        x = drive(t, amp)
        out[name] = (
            fast.run_transient(ir, x, settings=prod).vectors,
            fast.run_transient(ir, x, settings=conv).vectors,
            reference(core, amp, secondary=sec, gap=gap, t_out=t),
        )
    return out


@pytest.mark.parametrize("name", list(CASES))
def test_core_circuit_saturates(runs, name):
    """The drive really reaches saturation (B within 15% of mu0 Ms) and reverses; the
    mumetall_transformer case stays below it (B < 70% of mu0 Ms)."""
    mat = CASES[name][0]
    _, _, ref = runs[name]
    ms = core_model("x", mat, PATH).ms_a_per_m
    b = np.max(np.abs(ref["b"]))
    if name == "mumetall_transformer":
        assert b < 0.7 * MU0 * ms, b
    else:
        assert b > 0.85 * MU0 * ms, b


@pytest.mark.parametrize("name", list(CASES))
def test_circuitsim_agrees_with_the_python_reference(runs, name):
    prod, conv, ref = runs[name]
    rows = []
    for p in ("w1", "w2") if CASES[name][2] else ("w1",):
        rows.append((p, err_db(prod[f"v({p})"], ref[p]), err_db(conv[f"v({p})"], ref[p])))
    b_err = np.max(np.abs(conv["v(u)"] * TESLA_PER_V - ref["b"]))
    print(name, rows, f"B (converged) within {b_err:.2e} T")
    # Measured 2026-10-21 (rms dB re signal, production / converged): steel winding
    # -87.8 / -89.6, steel transformer with gap -79.3 / -85.4, permalloy transformer
    # -92.5 / -91.0, mumetall below saturation -94.9 / -93.7, mumetall driven past
    # its saturation -88.0 / -91.2; B within 5e-5 T. What is left is mostly the
    # input (the engine's band-limited upsampling vs the reference's analytic drive).
    # (Mumetall past saturation was -46 dB until the core's RK4 substeps followed
    # the slope's curvature: its knee is ~1 mT wide.)
    for p, e_prod, e_conv in rows:
        assert e_conv < -80, (p, e_conv)
        assert e_prod < -75, (p, e_prod)
    assert b_err < 1e-4


@pytest.mark.parametrize("name", list(CASES))
def test_dk_agrees_with_full_mna(name):
    mat, amp, sec, gap = CASES[name]
    ir, _ = build(mat, secondary=sec, gap=gap)
    t = np.arange(int(0.03 * FS)) / FS
    worst = compare_solvers(ir, drive(t, amp), 2, "esdirk4")
    print(name, f"{worst:.2f} tolerances")
    assert worst < 1.0


def test_linear_core_windings_match_coupled_inductors():
    """Windings on a linear core are coupled inductors with k = 1,
    L = N^2 A mu0 (1 + chi0) / l_e."""
    ir_w, core = build("permalloy_fluxgate", secondary=True, gap=False, linear=True)
    lam = AREA * MU0 * (1 + core.initial_susceptibility()) / PATH  # permeance
    ir_l = circuit(
        [
            Resistor("R1", "in", "w1", R1),
            Inductor("L1", "w1", "0", N1**2 * lam),
            Inductor("L2", "w2", "0", N2**2 * lam),
            Coupling("K12", "L1", "L2", 1.0),
            Resistor("R2", "w2", "0", R2),
        ],
        ["w1", "w2"],
    )
    s = dataclasses.replace(
        io.TransientSettings.from_sim_settings(engine="circuitsim"), full_scale_volts_peak=1.0
    )
    t = np.arange(int(0.03 * FS)) / FS
    x = drive(t, 1.0)
    a = fast.run_transient(ir_w, x, settings=s).vectors
    b = fast.run_transient(ir_l, x, settings=s).vectors
    for p in ("v(w1)", "v(w2)"):
        e = err_db(a[p], b[p])
        print(p, f"{e:.1f} dB")
        assert e < -200  # measured 2026-10-21: -250 to -262 dB (roundoff)


def test_linear_core_windings_match_ngspice():
    from engine_compare import compare

    from varimu.sim import ngspice

    try:
        ngspice.find_ngspice()
    except ngspice.SimulatorNotFound:
        pytest.skip("ngspice not available")
    # SPICE has the linear core as k = 1 coupled inductors, the eddy capacitance as a
    # resistor across a winding (varimu.circuit.spice): an exact equivalent.
    ir, _ = build("grain_oriented_si_steel", secondary=True, gap=True, linear=True, eddy_f=2e-6)
    t = np.arange(int(0.03 * FS)) / FS
    # Measured 2026-10-21: -131.5 dB at 2x, -138.2 dB at 4x; DC within 7e-10.
    for k in (2, 4):
        worst_db, worst_dc = compare(ir, drive(t, 1.0), k)
        print(f"k = {k}: {worst_db:.1f} dB, DC {worst_dc:.1e}")
        assert worst_db < -120 and worst_dc < 1e-8
