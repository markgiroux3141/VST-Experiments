"""The Pultec EQP-1A (device builder B2): config/circuits/pultec_eqp1a.yaml.

It builds from the generic format, idles at the voltages DWG E-72,658-2 prints,
its controls reach the brochure's ranges ([MAN] p.1), and both engines agree on
it (its cores in their linear limit, as the 670's agreement tests run).
"""

import dataclasses

import numpy as np
import pytest

from varimu.circuit import builder, spec
from varimu.circuit.ir import Capacitor, Inductor, Resistor
from varimu.config import CONFIG_DIR

PULTEC = CONFIG_DIR / "circuits" / "pultec_eqp1a.yaml"


@pytest.fixture(scope="module")
def eqp():
    return spec.load_circuit(PULTEC)


def _names(s, ov):
    return {e.name for e in builder.build_ir(s, spec.resolve(s, ov)).elements()}


def test_builds_and_every_value_is_sourced(eqp):
    for cores in ("ja", "linear"):
        c = builder.build(eqp, cores=cores)
        assert (c.text is None) == (cores == "ja")
    assert spec.check_genome_links(eqp) == []
    # Tolerance draws reach every part with a class (no part left without one).
    a = builder.build_ir(eqp, spec.resolve(eqp, {"passive_spread": 1.0, "passive_seed": 3}))
    b = builder.build_ir(eqp, spec.resolve(eqp))
    moved = sum(e != e0 for e, e0 in zip(a.elements(), b.elements(), strict=True))
    assert moved > 40


def test_switches_select_the_redraws_parts(eqp):
    assert {"CHB18", "LHB150"} <= _names(eqp, {"hf_boost_freq_khz": 3})
    assert {"CHB18", "LHB82"} <= _names(eqp, {"hf_boost_freq_khz": 4})
    assert {"CHB82", "LHB33"} <= _names(eqp, {"hf_boost_freq_khz": 10})
    assert {"CHB56", "LHB33"} <= _names(eqp, {"hf_boost_freq_khz": 12})
    # The LF banks: one capacitor always in, the 100 cps position adds none.
    assert {"CLA12", "CLB330"} <= _names(eqp, {"lf_freq_hz": 100})
    assert not {"CLA20", "CLA30", "CLA60", "CLB20"} & _names(eqp, {"lf_freq_hz": 100})
    with pytest.raises(ValueError, match="not one of"):
        spec.resolve(eqp, {"hf_boost_freq_khz": 6})


def test_hf_boost_pairs_resonate_at_the_panel_frequencies(eqp):
    """Each position's L and C (the redraw's values) resonate within 7% of the knob."""
    for khz in (3, 4, 5, 8, 10, 12, 16):
        els = builder.build_ir(eqp, spec.resolve(eqp, {"hf_boost_freq_khz": khz})).elements()
        sel = [e for e in els if e.name.startswith(("CHB", "LHB"))]
        c = next(e.c_f for e in sel if isinstance(e, Capacitor))
        l_h = next(e.l_h for e in sel if isinstance(e, Inductor))
        f = 1 / (2 * np.pi * np.sqrt(l_h * c))
        assert f == pytest.approx(khz * 1e3, rel=0.07), khz


def test_flat_network_loss(eqp):
    """At every control's zero the network loses ~22 dB, which the amplifier restores
    ("no loss, no gain", [MAN] p.4): 10k series, 1k || 11k shunt, 1k / 10k after it."""
    ir = builder.build_ir(eqp, spec.resolve(eqp))
    r = {e.name: e.r_ohm for e in ir.elements() if isinstance(e, Resistor)}
    series = r["RHBa"] + r["RHBb"]
    shunt = 1 / (1 / (r["RHAa"] + r["RHAb"]) + 1 / (r["RLA_SER"] + r["RSHUNT"]))
    loss_db = 20 * np.log10(shunt / (series + shunt) * r["RSHUNT"] / (r["RLA_SER"] + r["RSHUNT"]))
    assert loss_db == pytest.approx(-22.3, abs=0.2)


# --- Simulated (circuitsim) -------------------------------------------------------------

DRAWING_V = {"b0": 355.0, "b1": 345.0, "b2": 325.0, "b3": 290.0, "b4": 250.0, "htr": 60.0}


def _settings(settle_s=0.0):
    from varimu.sim import io

    s = io.TransientSettings.from_sim_settings(engine="circuitsim")
    return dataclasses.replace(s, full_scale_volts_peak=1.0, settle_s=settle_s)


def test_idles_at_the_drawings_voltages(eqp):
    pytest.importorskip("circuitsim", reason="needs `uv sync --extra fast`")
    from varimu.sim import fast

    st = _settings()
    x = np.zeros(int(6.0 * st.sample_rate))
    v = fast.run_transient(builder.build(eqp).ir, x, settings=st).vectors
    n = int(0.5 * st.sample_rate)
    for node, d in DRAWING_V.items():
        assert np.mean(v[f"v({node})"][-n:]) == pytest.approx(d, rel=0.03), node
    # 12AU7 cathodes (+40 V printed) and 12AX7 cathodes (+1.3 V): the tube models
    # within 15%.
    assert np.mean(v["v(k2a)"][-n:]) == pytest.approx(40.0, rel=0.15)
    assert np.mean(v["v(k1a)"][-n:]) == pytest.approx(1.3, rel=0.15)


TONES = np.array([20.0, 100.0, 1000.0, 3000.0, 10000.0, 16000.0, 20000.0])


def _gain_db(eqp, ov):
    """Small-signal gain (out / input terminals) at TONES, from a multitone transient."""
    from varimu.sim import fast

    st = _settings(settle_s=0.5)
    fs, pre, win = st.sample_rate, 0.5, 0.5
    t = np.arange(int((pre + win) * fs)) / fs
    rng = np.random.default_rng(1)
    x = sum(0.01 * np.sin(2 * np.pi * f * t + rng.uniform(0, 2 * np.pi)) for f in TONES)
    x *= np.minimum(1, t / 0.02)
    v = fast.run_transient(builder.build(eqp, ov).ir, x, settings=st).vectors
    k, bins = int(pre * fs), np.round(TONES * win).astype(int)

    def at(w):
        return np.fft.rfft(w[k : k + int(win * fs)])[bins]

    gain = 20 * np.log10(np.abs(at(v["v(out)"]) / at(v["v(in_s)"])))
    return dict(zip(TONES, gain, strict=True))


def test_controls_reach_the_brochures_ranges(eqp):
    """[MAN] p.1: LF boost 13.5 dB, LF atten 17.5 dB, HF boost 18 dB, HF atten 16 dB
    (at their extremes, against the flat response); overall gain 0 dB."""
    pytest.importorskip("circuitsim", reason="needs `uv sync --extra fast`")
    flat = _gain_db(eqp, {})
    assert flat[1000.0] == pytest.approx(0.0, abs=1.0)

    def rel(ov, f):
        return _gain_db(eqp, ov)[f] - flat[f]

    assert rel({"lf_freq_hz": 20, "lf_boost": 1.0}, 20.0) == pytest.approx(13.5, abs=1.5)
    assert rel({"lf_freq_hz": 20, "lf_atten": 1.0}, 20.0) == pytest.approx(-17.5, abs=1.5)
    assert rel({"hf_atten_freq_khz": 20, "hf_atten": 1.0}, 20000.0) == pytest.approx(-16, abs=1.5)
    # Sharp: 20.5 dB here, 2.5 dB above the brochure (measured 2026-10-26; only the
    # coils' resistance limits the Q at the sharp end).
    boost = rel({"hf_boost_freq_khz": 10, "hf_boost": 1.0, "bandwidth": 0.0}, 10000.0)
    assert 17.0 < boost < 22.0


# --- Both engines (the circuit-sim plan's M7) ---------------------------------------------

AGREE_SET = {
    "hf_boost": 0.7,
    "hf_boost_freq_khz": 5,
    "lf_boost": 0.6,
    "lf_freq_hz": 60,
    "hf_atten": 0.3,
}


def test_engines_agree_and_converge(eqp):
    """circuitsim against ngspice on 30 ms from the DC operating point (the supply's
    start included), cores in their linear limit, ngspice as a reference (engine_compare:
    tight tolerance, a timepoint per sample, 8 steps per sample) with tabulated triodes:
    the exact formulation stalled ngspice here (over 700 s of CPU for 10 ms, 2026-10-26,
    not pursued). Measured 2026-10-26, worst probe re its swing: out -62.6 / -67.3 dB at
    k = 4 / 8; the network and transformer nodes -69 / -80 dB, falling 12 dB per doubling
    (the second-order step error); the tube nodes level off near -66 dB, the tables'
    interpolation error (as on the 670)."""
    pytest.importorskip("circuitsim", reason="needs `uv sync --extra fast`")
    from varimu.sim import fast, io, ngspice

    try:
        ngspice.find_ngspice()
    except ngspice.SimulatorNotFound:
        pytest.skip("ngspice not available")
    from engine_compare import REFERENCE, settings, signal

    c = builder.build(eqp, AGREE_SET, cores="linear", triode_formulation="table")
    x = signal(dur_s=0.03, amp=0.5)
    err = {}
    for k in (4, 8):
        st = settings(k)
        ng = io.run_transient(
            c.text, x, input_node=c.input_node, save=list(c.save), settings=st,
            timeout_s=600, files=c.files, **REFERENCE,
        )  # fmt: skip
        rs = fast.run_transient(c.ir, x, settings=st, method="trap")
        for n in ("out", "p2a", "g1a", "eq_out"):
            a, b = ng.vectors[f"v({n})"], rs.vectors[f"v({n})"]
            err[n, k] = 20 * np.log10(np.max(np.abs(a - b)) / np.max(np.abs(a - a[0])))
    assert max(err[n, 8] for n in ("out", "p2a", "g1a", "eq_out")) < -63, err
    for n in ("g1a", "eq_out"):  # second order where there are no tables
        assert err[n, 8] < err[n, 4] - 8, (n, err)
