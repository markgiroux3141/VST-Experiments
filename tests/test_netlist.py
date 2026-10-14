"""Netlist generation for the 670 slice (varimu.circuit.netlist): structure and provenance."""

import re

import numpy as np
import pytest

from varimu.circuit import netlist as nl
from varimu.devices.library import load_device


def _elements(text):
    """Element name -> the rest of its line (upper-cased names)."""
    out = {}
    for line in text.splitlines():
        if line and line[0].isalpha() and not line.startswith("."):
            name, _, rest = line.partition(" ")
            out[name.upper()] = rest
    return out


def _value(text, name):
    return float(_elements(text)[name.upper()].split()[-1])


@pytest.fixture(scope="module")
def default():
    return nl.build(triode_formulation="exact")


def test_every_circuit_value_has_a_source_and_genome_links_resolve():
    spec = nl.load_spec()
    for section in (spec.controls, spec.values):
        for k, e in section.items():
            assert str(e.get("source", "")).strip(), k
    assert nl.check_genome_links() == []


def test_one_coupled_netlist(default):
    """Audio path, sidechain and PSU are one circuit sharing nodes (CLAUDE.md hard rule)."""
    el = _elements(default.text)
    # The control voltage is the T101 secondary centre tap, i.e. on the audio grids.
    assert el["LT101_SA"].split()[1] == "cv" and el["RT101_SB"].split()[0] == "cv"
    assert "cv" in el["DCR103"].split() and "cv" in el["DCR104"].split()
    # The sidechain is fed from the output (feedback topology).
    assert el["R145"].split()[0] == "out"
    # One B+ node feeds the 6386 plates, every sidechain stage and the 6973 screens.
    for name in ("R111", "R120", "R126", "R132", "R118", "R116"):
        assert "bp" in el[name].split()[:2], name
    assert default.input_node == "in" and "v(cv)" in default.save


def test_time_constant_positions_switch_the_documented_parts():
    expected = {
        1: {"R141"},
        2: {"R138"},
        3: {"C113"},
        4: {"C113", "C111"},
        5: {"C113", "R139", "C110"},
        6: {"R139", "C110", "R140", "C112"},
    }
    switched = {"R141", "R138", "C113", "C111", "R139", "C110", "R140", "C112"}
    for pos, parts in expected.items():
        el = _elements(nl.build({"time_constant": pos}).text)
        assert {"R137", "C109"} <= set(el)
        assert switched & set(el) == parts, pos


def test_pots_follow_their_controls():
    lo = nl.build({"ac_threshold": 0.0, "dc_threshold": 0.0, "zero": 0.0, "balance": 0.25}).text
    hi = nl.build({"ac_threshold": 1.0, "dc_threshold": 1.0, "zero": 1.0, "balance": 0.25}).text
    # AC threshold fully up: wiper at the transformer end (all of the signal).
    assert _value(hi, "R115Aa") == pytest.approx(1e-3) and _value(lo, "R115Ab") == pytest.approx(
        1e-3
    )
    # ZERO: wiper from ground (0) to the bias rail (1).
    assert _value(lo, "R142a") == pytest.approx(1e-3) and _value(hi, "R142a") == pytest.approx(2500)
    # Balance splits R105 between the two cathode returns.
    assert _value(lo, "R105a") == pytest.approx(25.0) and _value(lo, "R105b") == pytest.approx(75.0)


def test_t_pad_gives_its_attenuation_into_its_own_impedance():
    for db in (1.0, 10.0, 20.0):
        el = {r.name: r for r in nl._t_pad("AT", "a", "b", 600.0, db)}
        r1, r2, r3 = (el[n].r_ohm for n in ("RAT1", "RAT2", "RAT3"))
        load = 600.0
        mid = r3 * (r2 + load) / (r3 + r2 + load)
        v_mid = mid / (r1 + mid)
        gain = v_mid * load / (r2 + load)
        assert 20 * np.log10(gain) == pytest.approx(-db, abs=1e-9)
        # Image impedance stays 600 ohm.
        assert r1 + mid == pytest.approx(600.0)


def test_overrides_are_validated():
    with pytest.raises(KeyError):
        nl.build({"not_a_parameter": 1})
    with pytest.raises(ValueError):
        nl.build({"time_constant": 7})


def test_tube_instance_scales_current_and_mu():
    base = load_device("6386")
    vg, vp = np.array([-20.0, -5.0]), np.array([200.0, 200.0])
    quad = nl.tube_instance(base, "q", n_parallel=4, emission_scale=0.9)
    np.testing.assert_allclose(quad.ip(vg, vp), 3.6 * base.ip(vg, vp), rtol=1e-12)
    assert quad.c_gk == pytest.approx(4 * base.c_gk)
    assert quad.grid.contact_v == base.grid.contact_v
    hot = nl.tube_instance(base, "m", mu_spread=1.05, grid_contact_v=-0.6)
    assert hot.plate.mus[0] == pytest.approx(1.05 * base.plate.mus[0])
    assert hot.grid.contact_v == -0.6
    # Higher mu cuts off sooner: less current at the same negative bias.
    assert hot.ip(-30.0, 240.0) < base.ip(-30.0, 240.0)


def test_mismatch_reaches_the_netlist():
    a = nl.build({"v6386_a.emission_scale": 0.8}, triode_formulation="exact").text
    b = nl.build(triode_formulation="exact").text
    sub_a = re.findall(r"\.subckt (TRIODE_6386_A)[\s\S]*?\.ends", a)
    assert sub_a and a != b


def test_table_formulation_lists_its_files():
    c = nl.build()
    assert set(c.files) == {"v6386_a.tab", "v6386_b.tab", "v12ax7.tab", "v12bh7.tab"}
    for name, path in c.files.items():
        assert path.exists() and f'file="{name}"' in c.text
