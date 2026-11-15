"""The Pultec HLF-3C (docs/EQ_PLAN.md EQ1): config/circuits/pultec_hlf3c.yaml.

The file is current with its generator, every value is sourced, the switches select the
drawing's parts (OFF shorts or opens what the HLF-3C table says), the key at OUT and both
selectors OFF pass the line unchanged, each section is a 3rd-order constant-K filter whose
stop band lands on the brochure's curves, and circuitsim renders what the AC analysis says.
"""

import importlib.util

import numpy as np
import pytest

from varimu.circuit import builder, spec
from varimu.circuit.ir import Capacitor, Inductor
from varimu.config import CONFIG_DIR, REPO_ROOT
from varimu.measure import ac, filter_suite

HLF = CONFIG_DIR / "circuits" / "pultec_hlf3c.yaml"


@pytest.fixture(scope="module")
def hlf():
    return spec.load_circuit(HLF)


def _gen():
    path = REPO_ROOT / "scripts" / "make_pultec_hlf3c.py"
    m = importlib.util.spec_from_file_location("make_pultec_hlf3c", path)
    mod = importlib.util.module_from_spec(m)
    m.loader.exec_module(mod)
    return mod


def _els(s, ov):
    return builder.build_ir(s, spec.resolve(s, ov)).elements()


def test_the_file_is_current_and_sourced(hlf):
    assert HLF.read_text(encoding="utf-8") == _gen().make()
    assert spec.check_genome_links(hlf) == []
    builder.build(hlf)  # every switch default builds (the preflight runs every combination)


def test_off_positions_follow_the_table(hlf):
    names = {e.name for e in _els(hlf, {"low_cut_hz": 0, "high_cut_hz": 0})}
    # LF OFF: C-1 and C-2 shorted, L-1 not connected; HF OFF: C-3 not connected, L-2 / L-3 shorted.
    assert {"RC1_OFF", "RC2_OFF", "RL2_OFF", "RL3_OFF", "RKEY_I", "RKEY_O"} <= names
    assert not any(n.startswith(("C1_", "C2_", "L1_", "C3_", "L2_", "L3_")) for n in names)
    on = {e.name for e in _els(hlf, {"low_cut_hz": 80, "high_cut_hz": 5000})}
    assert {"C1_80", "L1_80", "C2_80", "L2_5000", "C3_5000", "L3_5000"} <= on
    assert not {"RC1_OFF", "RL2_OFF"} & on
    out = {e.name for e in _els(hlf, {"filter_in": 0, "low_cut_hz": 80})}
    assert "RKEY_BY" in out and not {"RKEY_I", "RKEY_O"} & out


def test_each_position_is_a_constant_k_section_near_500_ohm(hlf):
    """sqrt(L / C) of each position's parts is the drawing's 500 ohm within 25% (the HLF-3C
    table's C-1 / C-2 at 50 cps and 1-2 kc are the low ones)."""
    for f in filter_suite.LOW_HZ:
        els = [e for e in _els(hlf, {"low_cut_hz": f}) if e.name.endswith(f"_{f}")]
        c_arm = next(e.c_f for e in els if isinstance(e, Capacitor))
        l_h = next(e.l_h for e in els if isinstance(e, Inductor))
        z = np.sqrt(l_h / (c_arm / 2))
        assert 450 < z < 625, (f, z)
    for f in filter_suite.HIGH_HZ:
        els = [e for e in _els(hlf, {"high_cut_hz": f}) if e.name.endswith(f"_{f}")]
        c = next(e.c_f for e in els if isinstance(e, Capacitor))
        l_half = next(e.l_h for e in els if isinstance(e, Inductor))
        z = np.sqrt(2 * l_half / c)
        assert 450 < z < 560, (f, z)


def test_the_line_passes_unchanged_when_off(hlf):
    r = filter_suite.response_db(hlf, {}, {"low_cut_hz": 0, "high_cut_hz": 0})
    assert np.max(np.abs(r)) < 0.01
    # The key at OUT is the 600 ohm source into the 600 ohm load: -6.02 dB in volts, which the
    # output's full scale (half the input's) reads as 0 dB.
    ir = builder.build_ir(hlf, spec.resolve(hlf, {"filter_in": 0}))
    h = ac.transfer(ir, [1000.0], "out")[0]
    assert abs(20 * np.log10(abs(h)) + 6.0206) < 1e-3
    assert hlf.full_scale == (13.8, 6.9)


def test_cutoffs_slopes_and_the_brochure(hlf):
    """Third order: 16-18.5 dB / octave two to three octaves out (the 50-150 cps positions
    softer, 13-15, from their coils' resistance), no peak at the knee, the -3 dB point within
    0.85-1.4x the knob, and the -40 dB point within 20% of the brochure's (read by eye)."""
    for band, knobs in (("low", filter_suite.LOW_HZ), ("high", filter_suite.HIGH_HZ)):
        for f in knobs:
            p = filter_suite.position(hlf, {}, band, f)
            assert 0.85 < p["f_3db_ratio"] < 1.4, p
            assert p["peak_db"] < 0.01, p
            assert p["slope_db_per_oct"] > (13.0 if f <= 150 else 15.5), p
            assert p["slope_db_per_oct"] < 18.5, p
            if p["vs_brochure_40db"] is not None:
                assert 0.8 < p["vs_brochure_40db"] < 1.2, p


@pytest.mark.skipif(importlib.util.find_spec("circuitsim") is None, reason="needs the fast extra")
def test_circuitsim_renders_the_ac_response_at_full_level(hlf):
    from varimu.sim.io import TransientSettings

    s = TransientSettings.from_sim_settings(engine="circuitsim")
    tr = filter_suite.transient_check(hlf, {}, s)
    for row in tr["rows"]:
        assert abs(row["error_db"]) < 0.05, row
        assert row["residual_db"] < -70, row
