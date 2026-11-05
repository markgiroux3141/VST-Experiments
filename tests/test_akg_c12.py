"""The AKG C12 (the chains build-out's WP3): config/circuits/akg_c12.yaml.

It builds from the generic format, passes the pre-flight checks at every pattern position,
idles where AKG's brochure says (B+ 120 V at 0.7 mA; the drawing prints no voltages:
data/schematics/akg_c12/README.md), each position's capsule is polarized as the DC
solution puts its electrodes, and the whole microphone's sensitivity and directivity meet
the brochure's data.
"""

import numpy as np
import pytest

from varimu import preflight
from varimu.circuit import builder, spec
from varimu.config import CONFIG_DIR

C12 = CONFIG_DIR / "circuits" / "akg_c12.yaml"


@pytest.fixture(scope="module")
def c12():
    return spec.load_circuit(C12)


def test_builds_and_every_value_is_sourced(c12):
    for cores in ("ja", "linear"):  # no SPICE text either way: the rear pressure is a control input
        assert [x.name for x in builder.build(c12, cores=cores).ir.controls] == ["p_rear"]
    assert spec.check_genome_links(c12) == []
    a = builder.build_ir(c12, spec.resolve(c12, {"passive_spread": 1.0, "passive_seed": 3}))
    b = builder.build_ir(c12, spec.resolve(c12))
    moved = sum(e != e0 for e, e0 in zip(a.elements(), b.elements(), strict=True))
    assert moved > 15


def test_preflight_passes(c12):
    assert preflight.check_circuit(c12) == []


def test_each_position_is_its_tap_and_its_capsule(c12):
    for k in range(9):
        ir = builder.build_ir(c12, spec.resolve(c12, {"pattern": k}))
        names = {e.name for e in ir.elements()}
        assert f"RW{k}" in names
        assert {f"RW{j}" for j in range(9) if j != k}.isdisjoint(names)
        assert any(n.startswith(f"CKC{k}_") for n in names)
        assert not any(n.startswith(f"CKC{j}_") for j in range(9) if j != k for n in names)


def _idle(c12, pattern):
    pytest.importorskip("circuitsim", reason="needs `uv sync --extra fast`")
    from varimu.sim import fast
    from varimu.sim.io import TransientSettings

    st = TransientSettings.from_sim_settings(engine="circuitsim")
    n = int(0.1 * st.sample_rate)
    ir = builder.build_ir(c12, spec.resolve(c12, {"pattern": pattern}))
    v = fast.run_transient(ir, np.zeros(n), settings=st, controls={"p_rear": np.zeros(n)})
    return {k[2:-1]: float(np.mean(a[-n // 2 :])) for k, a in v.vectors.items()}


def test_idles_at_the_brochures_point(c12):
    """br: 'plate voltage 120 vdc at 0.7 ma' (the B+ to the plate circuit, R17): B+
    within 1%, the plate current within 10% (0.65 mA measured 2026-11-05); the backplate
    at half of B+ (R12 = R13, no DC in R14); the grid's bias the HV's whole current times
    R7 (1 k), as the drawing wires it."""
    m = _idle(c12, 4)
    q = spec.resolve(c12)
    assert m["bplus"] == pytest.approx(120.0, rel=0.01)
    i_a = (m["bplus"] - m["a"]) / q["r17_ohm"]
    assert i_a == pytest.approx(0.7e-3, rel=0.10)
    assert m["bp"] == pytest.approx(m["bplus"] / 2, rel=0.005)
    i_hv = i_a + m["bplus"] / (q["r12_ohm"] + q["r13_ohm"]) + m["bplus"] / (8 * q["r_ladder_ohm"])
    assert m["nbias"] == pytest.approx(-i_hv * q["r7_ohm"], rel=0.05)
    assert m["g"] == pytest.approx(m["nbias"], abs=0.05)


def test_polarizations_follow_the_dc_solution(c12):
    """Each position's capsule is built with the front's and the rear's polarization the
    DC solution puts on its electrodes (pol_front_v, pol_rear_k*_v: B+ / 2 x (1 - k / 4)),
    within 2% of the front's."""
    q = spec.resolve(c12)
    for k in (0, 2, 4, 6, 8):
        m = _idle(c12, k)
        assert m["bp"] == pytest.approx(q["pol_front_v"], rel=0.02)
        tol = 0.02 * q["pol_front_v"]
        assert m["bp"] - m["rd"] == pytest.approx(q[f"pol_rear_k{k}_v"], abs=tol)


def test_sensitivity_and_directivity_against_akgs(c12):
    """The whole microphone (the capsule on its body, varimu.mics.bor; the 6072 stage, T14/1
    at 200 ohm into 100 k) against br: 1.0 mV/ubar (10 mV/Pa) at no load +-1.5 dB, 'equally
    high sensitivity at all directional patterns'; the cardioid's front / back 'better than
    20 dB' (the later leaflet) or 15 dB (the earlier), its 180 deg curve -20 dB at 100 Hz and
    -26 at 1 kHz (br's chart)."""
    pytest.importorskip("circuitsim", reason="needs `uv sync --extra fast`")
    from varimu.devices.library import component_data
    from varimu.measure import metrics
    from varimu.mics.free_field import capsule_entry_pressures
    from varimu.sim import fast
    from varimu.sim.io import TransientSettings

    s = TransientSettings.from_sim_settings(engine="circuitsim")
    fs = s.sample_rate
    g = component_data(spec.resolve(c12)["capsule_model"])["geometry"]
    t = np.arange(int(0.5 * fs)) / fs

    def level(pattern, f0, angle_deg):
        p = np.sqrt(2) * np.sin(2 * np.pi * f0 * t) * np.minimum(1, t / 0.05)
        front, rear, _ = capsule_entry_pressures(g, p, np.radians(angle_deg), fs)
        ir = builder.build(c12, {"pattern": pattern}).ir
        v = fast.run_transient(ir, front, settings=s, controls={"p_rear": rear}).vectors
        return metrics.harmonics(v["v(out)"][-fs // 5 :], f0, fs).amps[0] / np.sqrt(2)

    for pattern in (0, 4, 8):
        assert 20 * np.log10(level(pattern, 1000.0, 0) / 10e-3) == pytest.approx(0.0, abs=1.5)
    for f0, lo in ((100.0, 15.0), (1000.0, 20.0)):
        assert 20 * np.log10(level(4, f0, 0) / level(4, f0, 180)) > lo
