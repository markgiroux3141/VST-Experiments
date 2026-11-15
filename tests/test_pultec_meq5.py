"""The Pultec MEQ-5 (docs/EQ_PLAN.md EQ2): config/circuits/pultec_meq5.yaml.

The file is current with its generator, every value is sourced, the switches select the
reconstruction's parts, the amplifier is the EQP-1A's unchanged, and the network (its linear
remainder, tubes out, cores linear: varimu.measure.ac) peaks and dips where the
reconstruction's parts put them, by the published 0-10 dB.
"""

import importlib.util

import numpy as np
import pytest

from varimu.circuit import builder, spec
from varimu.config import CONFIG_DIR, REPO_ROOT
from varimu.measure import ac

MEQ = CONFIG_DIR / "circuits" / "pultec_meq5.yaml"
EQP = CONFIG_DIR / "circuits" / "pultec_eqp1a.yaml"


@pytest.fixture(scope="module")
def meq():
    return spec.load_circuit(MEQ)


def _gen():
    path = REPO_ROOT / "scripts" / "make_pultec_meq5.py"
    m = importlib.util.spec_from_file_location("make_pultec_meq5", path)
    mod = importlib.util.module_from_spec(m)
    m.loader.exec_module(mod)
    return mod


def _names(s, ov):
    return {e.name for e in builder.build_ir(s, spec.resolve(s, ov)).elements()}


def _db(s, ov, f_hz):
    ir = builder.build_ir(s, spec.resolve(s, ov), cores="linear").without_devices()
    return 20 * np.log10(np.abs(ac.transfer(ir, f_hz, "eq_out")))


def test_the_file_is_current_and_sourced(meq):
    assert MEQ.read_text(encoding="utf-8") == _gen().make()
    assert spec.check_genome_links(meq) == []
    builder.build(meq)


def test_the_amplifier_is_the_eqp1as(meq):
    eqp = spec.load_circuit(EQP)
    ours = {e for e in builder.build_ir(meq, spec.resolve(meq)).elements()}
    theirs = builder.build_ir(eqp, spec.resolve(eqp)).elements()
    amp = [e for e in theirs if e.name.startswith(("T2", "T3", "XV", "RPL", "CC2", "RK", "RPSU"))]
    assert amp and all(e in ours for e in amp)


def test_switches_select_the_reconstructions_parts(meq):
    assert {"LLB520", "CLB1000"} <= _names(meq, {"low_peak_hz": 200})
    assert {"LLB120", "CLB200"} <= _names(meq, {"low_peak_hz": 1000})
    assert {"LMC420", "CMC1500", "CMC15"} <= _names(meq, {"dip_hz": 200})
    assert {"LMC34", "CMC170"} <= _names(meq, {"dip_hz": 2000})
    assert {"LMC61", "CMC170"} <= _names(meq, {"dip_hz": 1500})
    assert {"LHB625", "CHB16"} <= _names(meq, {"high_peak_hz": 1500})
    assert {"LHB477", "CHB1"} <= _names(meq, {"high_peak_hz": 5000})


def test_the_knobs_reach_the_published_ten_db(meq):
    """At full knob each band reaches 8.5-11.5 dB at its extreme (published 0-10 dB); at
    zero the network is flat to the knob's 0.01 dB."""
    f = np.geomspace(100, 12000, 120)
    flat = _db(meq, {}, f)
    for ov, sign in (
        ({"low_peak_hz": 300, "low_boost": 1.0}, 1),
        ({"dip_hz": 1000, "dip": 1.0}, -1),
        ({"high_peak_hz": 3000, "high_boost": 1.0}, 1),
    ):
        ext = float(np.max(sign * (_db(meq, ov, f) - flat)))
        assert 8.5 < ext < 11.5, (ov, ext)
    zero = {"low_boost": 0.0, "dip": 0.0, "high_boost": 0.0, "low_peak_hz": 500, "dip_hz": 3000}
    assert np.max(np.abs(_db(meq, zero, f) - flat)) < 0.01


def test_the_mid_cut_dips_on_its_knobs_to_2_khz(meq):
    """The reading that pairs the switches' decks: MID CUT's dips on the knob within 6% from
    200 Hz to 2 kHz (above, the reconstruction's 34 mH tap puts them 10-37% high)."""
    f = np.geomspace(150, 3000, 300)
    flat = _db(meq, {}, f)
    for k in (200, 500, 1000, 2000):
        r = _db(meq, {"dip_hz": k, "dip": 1.0}, f) - flat
        assert abs(f[np.argmin(r)] / k - 1) < 0.06, (k, f[np.argmin(r)])
