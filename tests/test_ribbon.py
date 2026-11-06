"""The ribbon motor kind (varimu.devices.ribbon; docs/CHAINS_PLAN.md WP5): its formulas,
Olson's mass-controlled ribbon (SBE handbook Eqs. 4.1.6-4.1.7), the length modes, the
slits' leak, the motional impedance, the test circuit through both engines' paths."""

from __future__ import annotations

import copy
import math

import numpy as np
import pytest

from varimu.circuit import builder, parts, spec
from varimu.circuit.ir import GROUND, CircuitIR, NoiseCurrent, Resistor, Section, VoltageProbe
from varimu.config import CONFIG_DIR
from varimu.devices import moving_coil as mc
from varimu.devices import ribbon
from varimu.devices.capsule import C_AIR, RHO_AIR
from varimu.devices.library import _plain, _published, load_ribbon_motor
from varimu.measure import ac
from varimu.mics import networks


def _geometry() -> dict:
    return copy.deepcopy(_plain(_published()["RIBBON_44BX"]["geometry"]))


def _motor(g: dict) -> mc.MovingCoil:
    return mc.moving_coil_from_data(
        {"name": "T", "kind": "ribbon_motor", "lumped": ribbon.compile_network(g)},
        kind="ribbon_motor",
    )


def _gradient(c: mc.MovingCoil, f: np.ndarray, dp: float = 1.0) -> np.ndarray:
    """Open-circuit volts at the ribbon per `dp` Pa of pressure difference (front +dp / 2,
    rear -dp / 2)."""
    half = np.full(len(f), dp / 2)
    return networks.moving_coil_response(c, f, (half, -half))


def test_rectangle_self_integral():
    from scipy import integrate

    for a, b in ((1.0, 1.0), (1.0, 2.0), (4.95e-3, 59.7e-3)):
        num = (
            4
            * integrate.dblquad(
                lambda v, u, a=a, b=b: (a - u) * (b - v) / math.hypot(u, v),
                0,
                a,
                0,
                b,
                epsrel=1e-11,
            )[0]
        )
        assert mc.rectangle_self_integral(a, b) == pytest.approx(num, rel=1e-9)
    # A disk's radiation mass is the baffled piston's 8 rho / (3 pi^2 r).
    disk = {"name": "x", "kind": "radiation", "a": "p", "b": "q", "radius_m": 0.01}
    els = mc.compile_element(disk)
    assert els[0]["value"] == pytest.approx(8 * RHO_AIR / (3 * math.pi**2 * 0.01), rel=1e-12)
    assert els[1]["value"] == pytest.approx(RHO_AIR * C_AIR / (math.pi * 1e-4), rel=1e-12)


def test_wide_slit_is_the_tube_formula_on_plates():
    e = {"name": "ch", "kind": "slit", "a": "p", "b": "q", "width_m": 5e-3,
         "breadth_m": 0.06, "length_m": 4e-3, "wide_at_hz": 1000.0}  # fmt: skip
    r, m = mc.compile_element(e)
    om = 2 * math.pi * 1000.0
    wall, section = 2 * 0.06 * 4e-3, 0.06 * 5e-3
    crandall = wall * math.sqrt(om * RHO_AIR * 1.81e-5 / 2) / section**2
    assert r["value"] == pytest.approx(crandall, rel=2e-2)
    assert m["value"] == pytest.approx(RHO_AIR * 4e-3 / section, rel=1e-12)


def test_foil_figures():
    """The 44-BX's foil (AEA's dimensions): 1.5 mg, about the handbook's '0.2-ohm ribbon',
    B l over the clamped length; the mode fractions sum to the whole mass."""
    fo = ribbon.foil(_geometry())
    assert fo["mass_kg"] == pytest.approx(2700 * 1.8e-6 * 4.7e-3 * 59.7e-3 * 1.1)
    assert 0.18 < fo["foil_ohm"] < 0.22
    assert fo["bl_tm"] == pytest.approx(0.65 * 59.7e-3)
    for n in (1, 3, 5):
        fr = ribbon.mode_fractions(n)
        assert [k for k, _ in fr] == list(range(1, 2 * n + 2, 2))
        assert sum(x for _, x in fr) == pytest.approx(1.0, abs=1e-15)
    assert ribbon.mode_fractions(1)[0][1] == pytest.approx(8 / math.pi**2)


def test_bare_ribbon_is_olsons_mass_controlled_ribbon():
    """A ribbon with no air load and no slits, far above its modes: v = dp A / (j w M) and
    E = B l v (Eqs. 4.1.6-4.1.7), whatever the number of modes; with the air load's masses
    the same with M_R + M_L."""
    g = _geometry()
    g["network"] = [
        {"name": "rib", "kind": "ribbon", "a": "front", "b": "r"},
        {"name": "tie", "kind": "acoustic", "a": "r", "b": "rear", "r_pa_s_m3": 1e-6},
    ]
    fo = ribbon.foil(g)
    f = np.array([2000.0, 5000.0, 20000.0])
    olson = fo["bl_tm"] * fo["area_m2"] / (1j * 2 * np.pi * f * fo["mass_kg"])
    for n in (1, 5):
        g["ribbon"]["modes"] = n
        h = _gradient(_motor(g), f)
        assert np.allclose(h, olson, rtol=3e-3), n
    g["network"] = [
        {"name": "ml_f", "kind": "acoustic", "a": "front", "b": "f", "m_kg_m4": 40.0},
        {"name": "rib", "kind": "ribbon", "a": "f", "b": "r"},
        {"name": "ml_r", "kind": "acoustic", "a": "r", "b": "rear", "m_kg_m4": 40.0},
    ]
    m_l = 80.0 * fo["area_m2"] ** 2
    h = _gradient(_motor(g), f)
    assert np.allclose(h, olson * fo["mass_kg"] / (fo["mass_kg"] + m_l), rtol=3e-3)


def test_modes_ripple_only_near_them():
    """The odd length modes (to 9 x 18 Hz) move the response near them and nowhere else: one
    mode and five agree within 0.05 dB from 1 kHz up, and differ below 200 Hz."""
    g = _geometry()
    f = np.geomspace(20, 10000, 60)
    h5 = _gradient(_motor(g), f)
    g["ribbon"]["modes"] = 1
    h1 = _gradient(_motor(g), f)
    d = 20 * np.log10(np.abs(h5 / h1))
    assert np.max(np.abs(d[f > 1000])) < 0.05
    assert np.max(np.abs(d[f < 200])) > 0.1


def test_the_44bx_motor_follows_olson_in_its_band():
    """RIBBON_44BX@1 in a pure gradient: within 2 dB of Eq. 4.1.6 with its whole air load
    (M_R + the radiation and channel masses of both faces) from 100 Hz to 20 kHz (the slits,
    screens and radiation resistance the rest), stiffness controlled below its resonance."""
    c = load_ribbon_motor("RIBBON_44BX@1")
    els = {e.name: e.value for e in c.elements}
    m_air = 2 * (els["rad_f_m"] + els["chan_f_m"])
    m_rib = c.bl_tm and ribbon.foil(_geometry())["mass_kg"] / c.sd_m2**2
    f = np.geomspace(100, 20000, 40)
    olson = c.gyrator_ohm / (1j * 2 * np.pi * f * (m_air + m_rib))
    d = 20 * np.log10(np.abs(_gradient(c, f) / olson))
    assert np.max(np.abs(d)) < 2.0
    lo = _gradient(c, np.array([0.25, 0.5]))
    assert abs(lo[1] / lo[0]) == pytest.approx(2.0, rel=0.1)  # below resonance: ~ f


def test_a_wider_slit_leaks_sensitivity():
    """The ribbon-to-pole clearance 'forms a leak which, if excessive, will reduce
    sensitivity' (SBE handbook 4.1.3)."""
    g = _geometry()
    f = np.array([300.0, 1000.0, 3000.0])
    h = np.abs(_gradient(_motor(g), f))
    edge = next(e for e in g["network"] if e["name"] == "edge")
    edge["width_m"] *= 3
    assert np.all(np.abs(_gradient(_motor(g), f)) < 0.8 * h)


def test_motional_impedance_peaks_at_the_resonance_in_air():
    """The ribbon's electrical impedance peaks at its resonance in place (the air load
    lowers the foil's 18 Hz to ~8 Hz), a few times its DC resistance (Leckschat & David:
    'up to five times its DC resistance at resonance depending on the ribbon motor
    design'), and falls to the DC resistance at the top."""
    c = load_ribbon_motor("RIBBON_44BX@1")
    els = parts.moving_coil("RB", GROUND, GROUND, "rp", GROUND, c)
    els.append(Resistor("RSRC", "in", "rp", 1.0))
    ir = CircuitIR(
        title="z", input_node="in", probes=(VoltageProbe("rp"),), models=(),
        sections=(Section("z", tuple(els)),),
    )  # fmt: skip
    f = np.geomspace(3, 20000, 300)
    v = ac.transfer(ir, f, "rp")
    z = np.abs(v / (1 - v))
    k = int(np.argmax(z))
    assert 5.0 < f[k] < 12.0
    assert 2.0 < z[k] / c.re_ohm < 8.0
    assert z[-1] == pytest.approx(c.re_ohm, rel=0.05)


def _circuit_ir():
    s = spec.load_circuit(CONFIG_DIR / "circuits" / "ribbon_test.yaml")
    return builder.build_ir(s, spec.resolve(s, {}), "linear")


def test_circuit_phasing_and_level():
    """ribbon_test (the ribbon into its transformer, 250 ohm, open): a plane wave from the
    front puts the red lead (out) in phase with the pressure (IB-24267-5, 'Phasing'), and the
    voltage step-up is the turns ratio (31) through the transformer in its band."""
    ir = _circuit_ir()
    d_m = 0.02  # a front-to-back path for the test (WP6's body gives the 44-BX's)
    f = np.array([300.0, 1000.0])
    rear = np.exp(-1j * 2 * np.pi * f * d_m / C_AIR)
    h = ac.transfer(ir, f, "out", drives={"p_rear": rear})
    assert np.all(np.abs(np.angle(h, deg=True)) < 30)
    emf = ac.transfer(ir, f, "rp", drives={"p_rear": rear}) - ac.transfer(
        ir, f, "rm", drives={"p_rear": rear}
    )
    assert np.allclose(np.abs(h / emf), 31.0, rtol=0.05)


def test_circuit_builds_and_noise_skips_the_leaks():
    s = spec.load_circuit(CONFIG_DIR / "circuits" / "ribbon_test.yaml")
    ir = builder.build(s, {}, noise=True, cores="ja").ir
    names = {e.name for e in ir.elements()}
    assert {"GRB_rib_ga", "GRB_rib_ge", "LRB_rib_n1_m", "RRB_edge", "RRB_re"} <= names
    noisy = {e.name[3:] for e in ir.elements() if isinstance(e, NoiseCurrent)}
    assert {"RRB_re", "RRB_edge", "RRB_screen_f"} <= noisy
    assert not any(n.endswith("_leak") for n in noisy)


def test_kind_is_checked():
    c = load_ribbon_motor("RIBBON_44BX@1")
    assert c.re_ohm == pytest.approx(ribbon.foil(_geometry())["foil_ohm"] + 0.01)
    with pytest.raises(ValueError, match="not a ribbon motor"):
        load_ribbon_motor("R57@4")
    from varimu.devices.library import load_moving_coil

    with pytest.raises(ValueError, match="not a moving-coil cartridge"):
        load_moving_coil("RIBBON_44BX@1")
    g = _geometry()
    g["network"].append({"name": "rib2", "kind": "ribbon", "a": "f", "b": "r"})
    with pytest.raises(ValueError, match="one ribbon"):
        ribbon.compile_network(g)


def test_renders_agree_with_the_ac_solution():
    """circuitsim's transient of ribbon_test (front driven, the rear held at 0 Pa) agrees with
    the AC solution at four tones."""
    pytest.importorskip("circuitsim", reason="needs `uv sync --extra fast`")
    from varimu.sim import fast
    from varimu.sim.io import TransientSettings

    ir = _circuit_ir()
    s = TransientSettings.from_sim_settings(engine="circuitsim")
    fs = s.sample_rate
    tones = np.array([100.0, 1000.0, 5000.0, 12000.0])
    t = np.arange(int(1.5 * fs)) / fs
    x = sum(np.sin(2 * np.pi * f * t) for f in tones) * np.minimum(1, t / 0.02)
    v = fast.run_transient(ir, x, settings=s, controls={"p_rear": np.zeros_like(x)})
    y = v.vectors["v(out)"]
    k, n = int(0.5 * fs), fs
    bins = tones.astype(int)
    h_tr = np.fft.rfft(y[k : k + n])[bins] / np.fft.rfft(x[k : k + n])[bins]
    h_ac = ac.transfer(ir, tones, "out")
    assert np.max(np.abs(20 * np.log10(np.abs(h_tr / h_ac)))) < 0.05


def test_spice_agrees_with_the_ac_solution():
    """The ribbon (front driven, the rear at the ambient, into 1 kOhm) in ngspice's AC
    analysis against varimu.measure.ac: the same network in SPICE (the mic circuits' control
    inputs keep them out of ngspice; this is the part alone)."""
    from varimu.circuit import spice
    from varimu.sim.ngspice import SimulatorNotFound, find_ngspice, run

    try:
        find_ngspice()
    except SimulatorNotFound:
        pytest.skip("ngspice not installed")
    c = load_ribbon_motor("RIBBON_44BX@1")
    els = parts.moving_coil("RB", "in", GROUND, "rp", GROUND, c)
    els.append(Resistor("RLOAD", "rp", GROUND, 1000.0))
    ir = CircuitIR(
        title="ribbon", input_node="in", probes=(VoltageProbe("rp"),), models=(),
        sections=(Section("ribbon", tuple(els)),),
    )  # fmt: skip
    text, _ = spice.emit(ir, rshunt_ohm=None)
    out = run(text + "\nVIN in 0 dc 0 ac 1", "ac dec 10 5 20000", ["v(rp)"], digits=16)
    f = np.real(out["scale"])
    h = ac.transfer(ir, f, "rp")
    assert np.max(np.abs(out["v(rp)"] / h - 1)) < 1e-6
