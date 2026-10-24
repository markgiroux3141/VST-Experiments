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
    return nl.build(triode_formulation="exact", cores="linear")


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
    # The supply's rails, as traced on A-96039 (data/schematics/fairchild_670/README.md):
    # regulated 240 V, the unregulated rail, the screen tap and the bias supply's nodes.
    rails = {
        "bp": ("R111", "R120", "R121", "R118", "R116", "R315", "R211"),
        "ur": ("R126", "R127", "LT104_PA", "R309"),
        "sg": ("R132", "R133", "R232"),
        "nb2": ("R105A", "R105B", "R203", "C303"),
        "nb3": ("R142B", "R242B", "R301", "R302"),
        "nb4": ("R130", "R131", "R230", "R303"),
    }
    for node, names in rails.items():
        for name in names:
            assert node in el[name].split()[:2], (node, name)
    # The mains drives the rectifiers: both supplies hang off sine sources.
    assert "sin(" in el["VHVA"] and "sin(" in el["VBS"]
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
        el = _elements(nl.build({"time_constant": pos}, cores="linear").text)
        assert {"R137", "C109"} <= set(el)
        assert switched & set(el) == parts, pos


def test_pots_follow_their_controls():
    lo_ov = {"ac_threshold": 0.0, "dc_threshold": 0.0, "zero": 0.0, "balance": 0.25}
    hi_ov = {"ac_threshold": 1.0, "dc_threshold": 1.0, "zero": 1.0, "balance": 0.25}
    lo = nl.build(lo_ov, cores="linear").text
    hi = nl.build(hi_ov, cores="linear").text
    # AC threshold fully up: wiper at the transformer end (all of the signal); at 0 on
    # the centre line (none). Segments a / b / c from the centre-line end up.
    assert _value(hi, "R115Ac") == pytest.approx(1e-3)
    assert _value(lo, "R115Aa") == pytest.approx(1e-3)
    # ZERO: wiper from ground (0) to the bias rail (1).
    assert _value(lo, "R142a") == pytest.approx(1e-3) and _value(hi, "R142a") == pytest.approx(2500)
    # Balance splits R105 between the two cathode returns.
    assert _value(lo, "R105a") == pytest.approx(25.0) and _value(lo, "R105b") == pytest.approx(75.0)


def _divider(els, top: str, wiper: str) -> float:
    """Voltage at `wiper` per volt at `top` of a resistor network to ground (DC)."""
    nodes = sorted({n for r in els for n in (r.a, r.b) if n not in ("0", top)})
    idx = {n: i for i, n in enumerate(nodes)}
    g, b = np.zeros((len(nodes), len(nodes))), np.zeros(len(nodes))
    for r in els:
        for x, y in ((r.a, r.b), (r.b, r.a)):
            if x in idx:
                g[idx[x], idx[x]] += 1 / r.r_ohm
                if y in idx:
                    g[idx[x], idx[y]] -= 1 / r.r_ohm
                elif y == top:
                    b[idx[x]] += 1 / r.r_ohm
    return float(np.linalg.solve(g, b)[idx[wiper]])


def test_ac_threshold_tapped_pot():
    """R113 off the tap: below the tap the wiper sees the tap's divided voltage, a
    gentler slope; above it, linear up to the whole secondary."""
    p = nl.resolve({})
    tap, r, rt = p["ac_threshold_tap"], p["r115a_ohm"], p["r113_r114_ohm"]
    lo = tap * r * rt / (tap * r + rt)
    v_tap = lo / (lo + (1 - tap) * r)
    for th in (0.0, 0.2, tap, 0.7, 1.0):
        els = nl._tapped_pot("115A", "t5", "w", "x", r, th, tap) + [nl._r("113", "x", "0", rt)]
        want = v_tap * th / tap if th <= tap else v_tap + (1 - v_tap) * (th - tap) / (1 - tap)
        assert _divider(els, "t5", "w") == pytest.approx(want, abs=1e-6), th
    # The load on the secondary doesn't depend on the wiper.
    assert nl.threshold_section_load_ohm(p, r) == pytest.approx((1 - tap) * r + lo)


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
    a = nl.build({"v6386_a.emission_scale": 0.8}, triode_formulation="exact", cores="linear").text
    b = nl.build(triode_formulation="exact", cores="linear").text
    sub_a = re.findall(r"\.subckt (TRIODE_6386_V101A)[\s\S]*?\.ends", a)
    assert sub_a and a != b


def test_table_formulation_lists_its_files():
    c = nl.build(cores="linear")
    triodes = [*nl.BANK_TRIODES["a"], *nl.BANK_TRIODES["b"]]
    assert set(c.files) == {f"v6386_{d.lower()}.tab" for d in triodes} | {
        "v12ax7_v105a.tab", "v12ax7_v105b.tab", "v12bh7_v106a.tab", "v12bh7_v106b.tab",
        "vel34t_v302.tab", "v6386_ch2.tab", "v12bh7_ch2.tab",
    }  # fmt: skip
    for name, path in c.files.items():
        assert path.exists() and f'file="{name}"' in c.text


# --- Per-instance tolerance (Phase 3) -------------------------------------------------


def _values(overrides):
    ir = nl.build(overrides, cores="linear").ir
    vals = {}
    for e in ir.elements():
        if hasattr(e, "r_ohm"):
            vals[e.name] = e.r_ohm
        elif hasattr(e, "c_f"):
            vals[e.name] = e.c_f
    return vals, {m.name: m for m in ir.models}


def test_tolerances_are_seeded_per_part_and_stay_in_their_bands():
    nominal, _ = _values({})
    a, _ = _values({"passive_spread": 1.0, "passive_seed": 7})
    assert a == _values({"passive_spread": 1.0, "passive_seed": 7})[0]  # reproducible
    b, _ = _values({"passive_spread": 1.0, "passive_seed": 8})
    spec = nl.load_spec()
    classes = spec.part_classes()
    p = nl.resolve({"passive_spread": 1.0})
    band = {
        "r1": (1, 1), "r5": (5, 5), "r10": (10, 10), "pot": (20, 20), "attenuator": (2, 2),
        "paper": (20, 20), "mica": (10, 10),
        "electrolytic": (p["tol_electrolytic_minus_pct"], p["tol_electrolytic_plus_pct"]),
    }  # fmt: skip
    moved = 0
    for name, v0 in nominal.items():
        d = nl.part_designator(name)
        if d is None:
            assert a[name] == v0, name  # not a part: never moves
            continue
        lo, hi = band[classes[spec.parts["combined"].get(d, [d])[0]]]
        assert v0 * (1 - lo / 100) <= a[name] <= v0 * (1 + hi / 100), name
        moved += a[name] != v0
        assert a[name] != b[name], name  # another seed, other parts
    assert moved > 80
    # The two halves of a pot share its track's draw; the wiper stays where it was.
    assert a["R105a"] / nominal["R105a"] == pytest.approx(a["R105b"] / nominal["R105b"])


def test_the_banks_are_individual_triodes_that_differ_with_spread():
    _, models = _values({"passive_spread": 1.0})
    triodes = [models[f"6386_{d}"] for side in "ab" for d in nl.BANK_TRIODES[side]]
    assert len({t.plate.kg1 for t in triodes}) == 8
    assert len({t.plate.mus[0] for t in triodes}) == 8
    _, nominal = _values({})
    assert len({nominal[f"6386_{d}"].plate.kg1 for d in nl.BANK_TRIODES["a"]}) == 1
