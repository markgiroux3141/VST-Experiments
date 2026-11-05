"""The Telefunken V72 (the chains build-out's WP1): config/circuits/telefunken_v72.yaml.

It builds from the generic format with BV 191 as a component, passes the pre-flight
checks, and idles near the little that is published about a V72's operating point
(data/schematics/telefunken_v72/README.md: the drawing prints no voltages); its trims
(scripts/v72_trim.py) hold.
"""

import numpy as np
import pytest

from varimu import preflight
from varimu.circuit import builder, spec
from varimu.config import CONFIG_DIR

V72 = CONFIG_DIR / "circuits" / "telefunken_v72.yaml"


@pytest.fixture(scope="module")
def v72():
    return spec.load_circuit(V72)


def test_builds_and_every_value_is_sourced(v72):
    for cores in ("ja", "linear"):
        c = builder.build(v72, cores=cores)
        assert (c.text is None) == (cores == "ja")
    assert spec.check_genome_links(v72) == []
    a = builder.build_ir(v72, spec.resolve(v72, {"passive_spread": 1.0, "passive_seed": 3}))
    b = builder.build_ir(v72, spec.resolve(v72))
    moved = sum(e != e0 for e, e0 in zip(a.elements(), b.elements(), strict=True))
    assert moved > 20


def test_preflight_passes(v72):
    assert preflight.check_circuit(v72) == []


def test_input_transformer_is_bv191(v72):
    """CT V72/1 is NWDR BV 191 by its construction: the compiled version's windings, the
    primaries in series through C30 (sch), the shield's capacitors to 0 V."""
    ir = builder.build_ir(v72, spec.resolve(v72))
    names = {e.name for e in ir.elements()}
    assert {"C30", "R11"} <= names
    assert any(n.startswith("KT1_") for n in names)  # the coupled leakages
    assert sum(n.startswith("CT1_") for n in names) >= 4  # windings to the shield


@pytest.fixture(scope="module")
def idle(v72):
    pytest.importorskip("circuitsim", reason="needs `uv sync --extra fast`")
    from varimu.sim import fast
    from varimu.sim.io import TransientSettings

    st = TransientSettings.from_sim_settings(engine="circuitsim")
    v = fast.run_transient(builder.build(v72).ir, np.zeros(int(0.5 * st.sample_rate)), settings=st)
    n = int(0.1 * st.sample_rate)
    return {k[2:-1]: float(np.mean(a[-n:])) for k, a in v.vectors.items()}


def test_idles_near_the_published_figures(v72, idle):
    """B+ about 245 V (CJ) within 5%; V41's bias about 2.7 V (CJ) within 10%: the feedback
    path's DC from V42's anode sets it (bb sheet 2)."""
    assert idle["bp"] == pytest.approx(245.0, rel=0.05)
    assert idle["k1"] == pytest.approx(2.7, rel=0.10)


def test_idle_currents(v72, idle):
    """The choke carries V42's anode and the feedback path's current within Sowter's
    rating for its CK V72/1 equivalent (up to 7 mA); V42 is in class A with its anode
    well above its cathode; the supply draws ~8 mA (bb sheet 3: ~35 mA from the mains
    with the heaters)."""
    q = spec.resolve(v72)
    i_choke = (idle["bp"] - idle["pl2"]) / q["l3_r_ohm"]
    i_fb = (idle["pl2"] - idle["k1"]) / (q["r18_ohm"] + q["r20_ohm"])
    assert 3e-3 < i_choke < 7e-3
    assert 2e-3 < i_choke - i_fb < 6e-3
    assert idle["pl2"] - idle["k2"] > 100.0
    assert 0.2e-3 < (idle["bq"] - idle["pl1"]) / q["r16_ohm"] < 0.6e-3
    assert 5e-3 < (idle["b1"] - idle["b2"]) / q["r26_ohm"] < 10e-3


def test_trims_hold():
    """R20 (the gain), the HV winding (the maximum output) and C40 (15 kHz) as
    scripts/v72_trim.py sets them."""
    pytest.importorskip("circuitsim", reason="needs `uv sync --extra fast`")
    import importlib.util

    from varimu.config import REPO_ROOT
    from varimu.sim.io import TransientSettings

    path = REPO_ROOT / "scripts" / "v72_trim.py"
    s = importlib.util.spec_from_file_location("v72_trim", path)
    trim = importlib.util.module_from_spec(s)
    s.loader.exec_module(trim)
    c = spec.load_circuit(V72)
    st = TransientSettings.from_sim_settings(engine="circuitsim")
    assert trim.gain_db(c, {}, st) == pytest.approx(34.0, abs=0.05)
    assert trim.thd_pct(c, {}, st) == pytest.approx(0.3, abs=0.03)
    assert trim.hf_db(c, {}, st) == pytest.approx(-0.3, abs=0.1)
