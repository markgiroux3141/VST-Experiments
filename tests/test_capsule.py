"""Condenser capsules (MIC_ROOM_PLAN.md A2): varimu/devices/capsule.py, the `capsule` and
`capsule_dual` parts, the AC reference varimu/measure/ac.py, and the B&K 4134 circuit
(config/circuits/capsule_bk4134.yaml) against its references (scripts/capsule_study.py).

Measured 2026-11-03 on the 4134 (Zuckerwar's geometry, H&M's FEM film resistance): the
transient render agrees with the AC solution within 0.018 dB below 20 kHz; the rendered
self-noise with the AC prediction within 0.5 dB, 18.6 dB(A) against B&K's 18 (theory
17.9-19.7); sensitivity 9.53 mV/Pa against the parameter set's own bound 9.6 (B&K's
nominal 12.5 is ~2.3 dB above what the published geometry gives: data/schematics/
bk_4134/README.md); the response peaks +3.3 dB at 15.6 kHz (B&K: ~+1)."""

import numpy as np
import pytest

from varimu.circuit import builder, spec
from varimu.circuit.ir import Capacitor, Resistor, Vccs
from varimu.devices import capsule as cap
from varimu.devices.library import load_capsule
from varimu.measure import ac

BK = "capsule_bk4134"


@pytest.fixture(scope="module")
def bk():
    return spec.load_circuit(spec.circuit_path(BK))


def test_membrane_and_electrode():
    c = load_capsule("BK4134@1")
    # The lumped membrane resonates near the exact first mode (2.405 sqrt(T / sigma) / a,
    # 22.9 kHz): the lumped form has 6 for 2.405^2 = 5.78.
    assert 1 / (2 * np.pi * np.sqrt(c.m_front * c.c_diaphragm)) == pytest.approx(22.0e3, rel=0.05)
    assert c.c0_f + c.c_stray_f == pytest.approx(18e-12, rel=0.01)  # bk: 18 pF
    # The electrostatic softening at 200 V: a few % of the membrane's stiffness.
    soft = 1 - c.c_diaphragm / c.c_diaphragm_at(200.0)
    assert 0.0 < soft < 0.05


def test_closed_form_matches_the_circuit(bk):
    q = spec.resolve(bk)
    c = load_capsule(q["capsule_model"])
    f = np.geomspace(5, 40e3, 40)
    ir = builder.build(bk, noise=False).ir
    h_ac = ac.transfer(ir, f, "out")
    h_cf = cap.sensitivity(c, f, q["polarization_v"], q["c_load_f"], q["r_load_ohm"])
    assert np.max(np.abs(20 * np.log10(np.abs(h_cf / h_ac)))) < 1e-3
    s250 = abs(ac.transfer(ir, [250.0], "out")[0])
    assert s250 == pytest.approx(9.53e-3, rel=0.01)


def test_noise_lands_on_the_acoustic_resistances_only(bk):
    ir = builder.build(bk, noise=True).ir
    noisy = {e.name for e in ir.elements() if type(e).__name__ == "NoiseCurrent"}
    assert noisy == {"IN_RFEED", "IN_RLOAD", "IN_RK1_h", "IN_RK1_v"}  # not the readout RK1_x


def test_renders_agree_with_the_ac_solution(bk):
    pytest.importorskip("circuitsim", reason="needs `uv sync --extra fast`")
    from scipy.signal import welch

    from varimu.sim import fast
    from varimu.sim.io import TransientSettings

    s = TransientSettings.from_sim_settings(engine="circuitsim")
    fs = s.sample_rate
    tones = np.array([100.0, 1000.0, 5000.0, 12000.0, 18000.0])
    t = np.arange(int(1.5 * fs)) / fs
    x = sum(0.01 * np.sin(2 * np.pi * f * t) for f in tones) * np.minimum(1, t / 0.02)
    quiet = builder.build(bk, noise=False).ir
    v = fast.run_transient(quiet, x, settings=s).vectors["v(out)"]
    k, n = int(0.5 * fs), fs
    bins = tones.astype(int)
    h_tr = np.fft.rfft(v[k : k + n])[bins] / np.fft.rfft(x[k : k + n])[bins]
    h_ac = ac.transfer(quiet, tones, "out")
    assert np.max(np.abs(20 * np.log10(np.abs(h_tr / h_ac)))) < 0.05
    noisy = builder.build(bk, noise=True).ir
    vn = fast.run_transient(noisy, np.zeros(3 * fs), settings=s).vectors["v(out)"][fs // 2 :]
    f, p = welch(vn - vn.mean(), fs=fs, nperseg=fs // 4)
    band = (f >= 100) & (f <= 20000)
    p_ac = ac.noise_psd(noisy, f[band], "out")
    assert abs(np.median(10 * np.log10(p[band] / p_ac))) < 1.0


def test_dual_capsule_parts():
    lp = cap.dual_lumped(
        {
            "diaphragm": {"radius_m": 0.013, "thickness_m": 6e-6, "density_kg_m3": 1390,
                          "tension_n_m": 1500},
            "gap_m": 52e-6,
            "backplate": {"radius_m": 0.012, "thickness_m": 3e-3,
                          "through": {"holes": 38, "radius_m": 0.5e-3},
                          "blind": {"holes": 58, "radius_m": 0.5e-3, "depth_m": 1.2e-3}},
            "leak_time_s": 0.5,
            "stray_capacitance_f": 3e-12,
        }
    )  # fmt: skip
    c = cap.DualCapsule("K", *(lp[k] for k in cap.DUAL_FIELDS))
    from varimu.circuit import parts

    els = parts.capsule_dual("KK", "pf", "pr", "bp", "g", "re", c, 63.0, 0.0)
    names = {e.name for e in els}
    # The front polarized (a source), the rear not (C0 straight from the backplate).
    assert "GKK_xf" in names and "GKK_xr" not in names and "RKK_xr" not in names
    c0r = next(e for e in els if e.name == "CKK_0r")
    assert isinstance(c0r, Capacitor) and (c0r.a, c0r.b) == ("bp", "re")
    assert sum(isinstance(e, Vccs) for e in els) == 1
    assert sum(isinstance(e, Resistor) for e in els) == 7  # 2 x (film, blind), xf, t, l

    from varimu.mics.networks import dual_response

    f = np.array([200.0, 1000.0, 4000.0])
    for pattern in ("cardioid", "omni"):
        front = dual_response(c, f, 0.0, 0.012, 63.0, pattern)
        back = dual_response(c, f, np.pi, 0.012, 63.0, pattern)
        assert np.all(np.isfinite(front)) and np.all(np.abs(front) > 0)
        if pattern == "omni":  # both polarized, tied: front and back alike (to the leak's tap)
            np.testing.assert_allclose(np.abs(front), np.abs(back), rtol=1e-3)
