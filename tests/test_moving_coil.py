"""Moving-coil cartridges (docs/SM57_PLAN.md, SM2): the network compiler, Seeler's phase-shift
network, the gyrator against a closed form, and the part's elements."""

from __future__ import annotations

import math

import numpy as np
import pytest

from varimu.circuit import parts
from varimu.circuit.ir import Resistor, Vccs
from varimu.devices import moving_coil as mc
from varimu.devices.capsule import C_AIR
from varimu.mics import networks
from varimu.mics.free_field import entry_factors

K_S = 35e-6  # a ~12 mm front-to-back path
R1 = 2.0e6  # Pa s/m^3


def _seeler_geometry(q: float = 2.0, bl_tm: float = 2.0) -> dict:
    """A Unidyne-style cartridge from Seeler's design equations (no sourced values: a test
    case)."""
    net = mc.seeler_rear_network(K_S, R1, q * K_S * R1)
    return {
        "diaphragm": {
            "radius_m": 0.009,
            "moving_mass_kg": 0.3e-3,
            "compliance_m_per_n": 4.0e-3,
            "resistance_ns_per_m": 0.01,
        },
        "coil": {"bl_tm": bl_tm, "re_ohm": 30.0, "le_h": 0.3e-3, "l2_h": 0.5e-3, "r2_ohm": 60.0},
        "network": [
            {"name": "dia", "kind": "diaphragm", "a": "front", "b": "u"},
            {"name": "ca", "kind": "cavity", "a": "u", "compliance_m5_n": net["ca"]},
            {
                "name": "gap",
                "kind": "acoustic",
                "a": "u",
                "b": "m",
                "r_pa_s_m3": net["rb"],
                "m_kg_m4": net["lb"],
            },  # fmt: skip
            {"name": "cb", "kind": "cavity", "a": "m", "compliance_m5_n": net["cb"]},
            {
                "name": "back",
                "kind": "acoustic",
                "a": "u",
                "b": "rear",
                "r_pa_s_m3": R1,
                "m_kg_m4": q * K_S * R1,
            },  # fmt: skip
        ],
    }


def _cartridge(geom: dict) -> mc.MovingCoil:
    return mc.moving_coil_from_data(
        {"name": "T", "kind": "moving_coil", "lumped": mc.compile_network(geom)}
    )


@pytest.mark.parametrize("q", [0.75, 1.0, 2.0, 5.0])
def test_seeler_network_matches_the_delay(q):
    """1 + Z1 / Z2 = exp(pK) to fourth order (Seeler's Eq. 3 by Eqs. 5-10): the residual
    falls as (wK)^5, and every element is positive."""
    l1 = q * K_S * R1
    n = mc.seeler_rear_network(K_S, R1, l1)
    assert min(n["ca"], n["cb"], n["rb"], n["lb"]) > 0
    for f in (50.0, 200.0, 1000.0):
        p = 2j * np.pi * f
        y2 = p * n["ca"] + 1.0 / (p * n["lb"] + n["rb"] + 1.0 / (p * n["cb"]))
        err = abs(1 + (p * l1 + R1) * y2 - np.exp(p * K_S))
        assert err < 10 * (2 * np.pi * f * K_S) ** 5


def test_seeler_needs_q_above_half():
    with pytest.raises(ValueError, match="q = L1"):
        mc.seeler_rear_network(K_S, R1, 0.4 * K_S * R1)


def test_seeler_cartridge_is_a_cardioid():
    """The cartridge in free field, its entries K apart: from the rear it cancels to the
    network's fourth-order residual (the diaphragm doesn't enter: Eq. 3)."""
    c = _cartridge(_seeler_geometry())
    f = np.geomspace(50, 1000, 12)
    d_m = K_S * C_AIR
    front = networks.moving_coil_response(c, f, entry_factors(f, 0.0, d_m))
    back = networks.moving_coil_response(c, f, entry_factors(f, math.pi, d_m))
    side = networks.moving_coil_response(c, f, entry_factors(f, math.pi / 2, d_m))
    assert np.all(20 * np.log10(abs(back) / abs(front)) < -40)
    # A cardioid is 6 dB down at the side.
    assert np.allclose(20 * np.log10(abs(side) / abs(front)), -6.02, atol=0.1)


def test_gyrator_against_closed_form():
    """A pressure cartridge (the diaphragm into a closed cavity) driving a load: the volts
    equal the closed form of the coupled system, the coil's impedance reflected onto the
    diaphragm through B l / S (the gyrator's sign: a positive pressure at the front gives a
    positive voltage at plus)."""
    g = _seeler_geometry()
    v_cav = 1e-6
    g["network"] = [
        {"name": "dia", "kind": "diaphragm", "a": "front", "b": "u"},
        {"name": "cav", "kind": "cavity", "a": "u", "volume_m3": v_cav},
    ]
    c = _cartridge(g)
    r_load = 150.0
    f = np.geomspace(20, 20000, 30)
    h = networks.moving_coil_response(c, f, (np.ones_like(f), np.ones_like(f)), r_load)
    d, coil = g["diaphragm"], g["coil"]
    s = math.pi * d["radius_m"] ** 2
    r = coil["bl_tm"] / s
    p = 2j * np.pi * f
    c_m = d["compliance_m_per_n"] * s * s
    z_m = p * d["moving_mass_kg"] / s**2 + 1 / (p * c_m + 1 / mc._leak(c_m))
    z_m += d["resistance_ns_per_m"] / s**2 + 1 / (p * v_cav / (1.4 * 101325.0))
    z_coil = 1 / (1 / (p * coil["l2_h"]) + 1 / coil["r2_ohm"])
    z_e = coil["re_ohm"] + p * coil["le_h"] + z_coil + r_load
    u = 1.0 / (z_m + r * r / z_e)
    expected = r * u / z_e * r_load
    assert np.allclose(h, expected, rtol=1e-9)


def test_part_elements_and_leak():
    c = _cartridge(_seeler_geometry())
    els = parts.moving_coil("SM", "f", "r", "p", "m", c)
    names = [e.name for e in els]
    assert names[:4] == ["RSM_re", "LSM_le", "LSM_l2", "RSM_r2"]
    gyr = [e for e in els if isinstance(e, Vccs)]
    assert [e.name for e in gyr] == ["GSM_dia_ga", "GSM_dia_ge"]
    assert gyr[0].gm_s == -gyr[1].gm_s == pytest.approx(1 / c.gyrator_ohm)
    leak = next(e for e in els if e.name == "RSM_dia_leak")
    c_dia = next(e.value for e in c.elements if e.name == "dia_c")
    assert isinstance(leak, Resistor) and leak.r_ohm == pytest.approx(mc._leak(c_dia))
    nodes = {n for e in els for n in (getattr(e, "a", None), getattr(e, "b", None)) if n}
    assert {"f", "r", "sm_u", "sm_m"} <= nodes


def test_compile_rejects_bad_networks():
    g = _seeler_geometry()
    g["network"] = g["network"] + [{"name": "dia2", "kind": "diaphragm", "a": "u", "b": "m"}]
    with pytest.raises(ValueError, match="one diaphragm"):
        mc.compile_network(g)
    g = _seeler_geometry()
    g["network"][1] = {"name": "ca", "kind": "cavity", "a": "u", "b": "m", "volume_m3": 1e-7}
    with pytest.raises(ValueError, match="ambient"):
        mc.compile_network(g)
    g = _seeler_geometry()
    g["network"][1]["kind"] = "horn"
    with pytest.raises(ValueError, match="kind"):
        mc.compile_network(g)


def test_element_formulas():
    """Each kind's formula on round numbers (the module docstring's)."""
    g = _seeler_geometry()
    g["network"] = [
        {"name": "dia", "kind": "diaphragm", "a": "front", "b": "u"},
        {
            "name": "sl",
            "kind": "slit",
            "a": "u",
            "b": "v",
            "width_m": 1e-4,
            "breadth_m": 0.03,
            "length_m": 2e-3,
        },  # fmt: skip
        {
            "name": "tb",
            "kind": "tube",
            "a": "v",
            "b": "w",
            "radius_m": 5e-4,
            "length_m": 1e-3,
            "count": 4,
            "open_ends": 0,
        },  # fmt: skip
        {"name": "sc", "kind": "screen", "a": "w", "b": "rear", "rayl": 100.0, "area_m2": 1e-4},
        {"name": "cv", "kind": "cavity", "a": "u", "volume_m3": 1e-6},
    ]
    lp = mc.compile_network(g)
    v = {e["name"]: e["value"] for e in lp["elements"]}
    mu, rho = 1.813e-5, 1.204
    assert v["sl"] == pytest.approx(12 * mu * 2e-3 / (0.03 * 1e-12))
    assert v["sl_m"] == pytest.approx(6 * rho * 2e-3 / (5 * 0.03 * 1e-4))
    assert v["tb"] == pytest.approx(8 * mu * 1e-3 / (4 * math.pi * 5e-4**4))
    assert v["tb_m"] == pytest.approx(4 * rho * 1e-3 / (3 * 4 * math.pi * 25e-8))
    assert v["sc"] == pytest.approx(1e6)
    assert v["cv"] == pytest.approx(1e-6 / (1.4 * 101325.0))


def test_sphere_ring_entries():
    """The rear ring at the rear pole is sphere_entry_factors' rear cap in the limit of a
    small cap; at low frequency a ring at beta sees 1 + (3/2) j ka cos(theta) cos(beta)."""
    from varimu.mics.free_field import sphere_entry_factors, sphere_ring_factors

    f = np.array([200.0, 2000.0, 8000.0])
    a, cap = 0.016, 1e-4
    for th in (0.0, 1.0, 2.5):
        f0, r0 = sphere_entry_factors(f, th, a, cap)
        f1, r1 = sphere_ring_factors(f, th, a, cap, math.pi)
        assert np.allclose(f0, f1, rtol=1e-9)
        assert np.allclose(r0, r1, rtol=1e-4)  # the cap's finite size
    ka = 2 * np.pi * 20.0 * a / C_AIR
    _, r = sphere_ring_factors(np.array([20.0]), 0.7, a, cap, 1.9)
    assert abs(r[0] - (1 + 1.5j * ka * math.cos(0.7) * math.cos(1.9))) < 2 * ka**2


def test_seeler_element_equals_the_hand_network():
    """The `seeler` kind expands to the hand-built network of _seeler_geometry."""
    hand = _seeler_geometry()
    g = _seeler_geometry()
    g["network"] = [
        g["network"][0],
        {
            "name": "ps",
            "kind": "seeler",
            "a": "u",
            "b": "rear",
            "mid": "m",
            "d_m": K_S * C_AIR,
            "r1_pa_s_m3": R1,
            "q": 2.0,
        },  # fmt: skip
    ]
    f = np.geomspace(30, 3000, 9)
    for th in (0.0, 2.0):
        e = entry_factors(f, th, K_S * C_AIR)
        h0 = networks.moving_coil_response(_cartridge(hand), f, e)
        h1 = networks.moving_coil_response(_cartridge(g), f, e)
        assert np.allclose(h0, h1, rtol=1e-9)


def test_wide_tube_loss():
    """A tube with wide_at_hz: Crandall's resistance and the plain mass."""
    g = _seeler_geometry()
    g["network"] = [
        {"name": "dia", "kind": "diaphragm", "a": "front", "b": "u"},
        {
            "name": "tb",
            "kind": "tube",
            "a": "u",
            "b": "rear",
            "radius_m": 1e-3,
            "length_m": 1e-3,
            "count": 2,
            "open_ends": 0,
            "wide_at_hz": 10000.0,
        },  # fmt: skip
    ]
    v = {e["name"]: e["value"] for e in mc.compile_network(g)["elements"]}
    mu, rho, w = 1.813e-5, 1.204, 2 * math.pi * 1e4
    assert v["tb"] == pytest.approx(1e-3 * math.sqrt(2 * w * rho * mu) / (2 * math.pi * 1e-9))
    assert v["tb_m"] == pytest.approx(rho * 1e-3 / (2 * math.pi * 1e-6))


def test_dynamic_body_entries():
    """The handheld body (bor.dynamic_mesh): its rear band averaged over its area; at low
    frequency both entries see the free field, the rear a path behind; at high frequency
    the face builds up toward pressure doubling."""
    from varimu.mics import bor

    body = {
        "form": "dynamic", "face_radius_m": 13e-3, "ports_m": [7e-3, 13e-3],
        "cartridge_length_m": 22e-3, "head_radius_m": 15.875e-3, "head_length_m": 63.5e-3,
        "taper_length_m": 75.39e-3, "end_radius_m": 11.9e-3, "end_length_m": 20.24e-3,
    }  # fmt: skip
    m = bor.dynamic_mesh(body, 8e-3)
    w = m.face_weights(bor.REAR)
    assert w.sum() == pytest.approx(1.0) and np.all(w[m.tag != bor.REAR] == 0)
    assert np.all(w[m.tag == bor.REAR] > 0)  # outside the diaphragm's radius: still weighted
    op = bor.operator(m)
    fr, rr = bor.entry_factors(op, np.array([50.0, 8000.0]), np.radians([0.0]))
    assert abs(fr[0, 0]) == pytest.approx(1.0, abs=0.01) and abs(rr[0, 0]) == pytest.approx(
        1, abs=0.01
    )
    path_m = np.angle(fr[0, 0] / rr[0, 0]) / (2 * np.pi * 50.0) * C_AIR
    assert 0.010 < path_m < 0.030
    assert 20 * np.log10(abs(fr[1, 0])) > 5.0
    with pytest.raises(ValueError, match="dynamic body"):
        bor.dynamic_mesh({**body, "ports_m": [7e-3, 30e-3]}, 8e-3)


def test_renders_agree_with_the_ac_solution():
    """circuitsim's transient of the R57 cartridge (front driven, the rear entry held at 0
    Pa) agrees with the AC solution, and its Johnson noise with the AC noise PSD (the coil's
    DCR and every acoustic resistance; the diaphragm's numerical leak none)."""
    pytest.importorskip("circuitsim", reason="needs `uv sync --extra fast`")
    import dataclasses

    from scipy.signal import welch

    from varimu.circuit.ir import NoiseCurrent, NoiseSpec
    from varimu.devices.library import load_moving_coil
    from varimu.measure import ac
    from varimu.sim import fast
    from varimu.sim.io import TransientSettings

    c = load_moving_coil("R57@3")
    quiet = networks.moving_coil_ir(c, r_load_ohm=1000.0, l_load_h=0.386)
    s = TransientSettings.from_sim_settings(engine="circuitsim")
    fs = s.sample_rate
    tones = np.array([100.0, 1000.0, 5000.0, 12000.0])
    t = np.arange(int(1.5 * fs)) / fs
    x = sum(1.0 * np.sin(2 * np.pi * f * t) for f in tones) * np.minimum(1, t / 0.02)
    rear = np.zeros_like(x)
    v = fast.run_transient(quiet, x, settings=s, controls={"p_rear": rear}).vectors["v(out)"]
    k, n = int(0.5 * fs), fs
    bins = tones.astype(int)
    h_tr = np.fft.rfft(v[k : k + n])[bins] / np.fft.rfft(x[k : k + n])[bins]
    h_ac = ac.transfer(quiet, tones, "out")
    assert np.max(np.abs(20 * np.log10(np.abs(h_tr / h_ac)))) < 0.05
    # Noise: every resistor but the leak, 4kT/R (the builders' rule, by hand here).
    els = [e for sec in quiet.sections for e in sec.elements]
    noise = [
        NoiseCurrent(f"IN_{e.name}", e.a, e.b, 4 * 1.380649e-23 * 293.15 / e.r_ohm)
        for e in els
        if type(e).__name__ == "Resistor" and not e.name.endswith("_leak") and e.name != "RLOAD"
    ]
    secs = (type(quiet.sections[0])("cartridge", tuple(els + noise)),)
    noisy = dataclasses.replace(quiet, sections=secs, noise=NoiseSpec(seed=7, rate_hz=fs))
    silence = np.zeros(3 * fs)
    run = fast.run_transient(noisy, silence, settings=s, controls={"p_rear": silence})
    vn = run.vectors["v(out)"][fs // 2 :]
    f, p = welch(vn - vn.mean(), fs=fs, nperseg=fs // 4)
    band = (f >= 100) & (f <= 20000)
    p_ac = ac.noise_psd(noisy, f[band], "out")
    assert abs(np.median(10 * np.log10(p[band] / p_ac))) < 1.0
