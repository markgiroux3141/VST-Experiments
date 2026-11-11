"""The Western Electric F1 carbon transmitter (the chains build-out's WP31):
config/circuits/carbon_transmitter.yaml, Jones's Fig. 6 network driving the carbon F1@1 in Fig.
5's loop, fitted by scripts/fit_f1.py (BSTJ 17, 1938; data/schematics/carbon_transmitter/).

It builds and passes the pre-flight checks; it idles at Fig. 5's resistance in Fig. 5's loop; its
response through the circuit matches the fit's network (and so Fig. 6 within the fit's misses);
Fig. 7's sum and difference components come out of the circuit as the fit's memoryless
calculation says; and the chain carbon_clean builds.
"""

import math
import sys

import numpy as np
import pytest

from varimu import preflight
from varimu.circuit import builder, spec
from varimu.config import CONFIG_DIR, REPO_ROOT

F1 = CONFIG_DIR / "circuits" / "carbon_transmitter.yaml"


@pytest.fixture(scope="module")
def c():
    return spec.load_circuit(F1)


@pytest.fixture(scope="module")
def fit():
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    import fit_f1

    return fit_f1


def test_builds_and_preflight(c):
    builder.build(c)
    assert spec.check_genome_links(c) == []
    assert preflight.check_circuit(c) == []


def test_fit_matches_the_figures(fit):
    resp = fit.load("we_f1_response.csv")["measured"]
    v, offset, r = fit.fit_response(resp)
    assert np.sqrt(np.mean(r**2)) < 2.0  # Fig. 6: 1.74 dB rms (Jones's own circuit: ~1.6)
    q = spec.resolve(spec.load_circuit(F1))
    for k in fit.FREE:  # the circuit holds the fit
        assert float(q[k]) == pytest.approx(v[k], rel=1e-4), k


@pytest.fixture(scope="module")
def run(c):
    pytest.importorskip("circuitsim", reason="needs `uv sync --extra fast`")
    from varimu.sim import fast
    from varimu.sim.io import TransientSettings

    s = TransientSettings.from_sim_settings(engine="circuitsim")
    fs = s.sample_rate
    ir = builder.build(c).ir

    def f(x):
        return fast.run_transient(ir, x, settings=s).vectors, fs

    return f


def _tone(fs, f_hz, amp, seconds=0.3):
    t = np.arange(int(seconds * fs)) / fs
    return t, amp * np.sin(2 * np.pi * f_hz * t) * np.minimum(1, t / 0.05)


def test_idle_resistance(run):
    fs = 96000
    v, _ = run(np.zeros(fs // 10))
    vt = v["v(t)"][-1]
    r = 513.0 * vt / (20.5 - vt)
    assert r == pytest.approx(63.0, rel=0.01)  # jones: Fig. 5, two years' aging


@pytest.mark.parametrize("f_hz", [300.0, 1000.0, 2000.0, 4000.0])
def test_response_matches_the_fit(run, fit, f_hz):
    from varimu.measure import metrics

    q = spec.resolve(spec.load_circuit(F1))
    p_pa = 0.05  # small signal
    x = _tone(96000, f_hz, p_pa * math.sqrt(2))[1]
    v, fs = run(x)
    out = metrics.harmonics(v["v(out)"][-fs // 10 :], f_hz, fs).amps[0]
    from varimu.devices.library import component_data

    d = component_data("F1@1")["carbon"]
    g_open, n, s, fp = d["g_open_s"], d["exponent"], d["soft_n"], float(q["preload_n"])
    vals = {k: float(q[k]) for k in fit.fixed()} | {k: float(q[k]) for k in fit.FREE}
    emf = abs(fit.emf_per_pa(vals, np.array([f_hz]), fp, n, s / fp, g_open)[0])
    emf *= p_pa * math.sqrt(2)
    want = emf * 513.0 / (513.0 + 63.0)  # across the transmitter in its loop (the 1 MOhm load)
    assert 20 * np.log10(out / want) == pytest.approx(0.0, abs=0.3), f_hz


def test_intermodulation(run, fit):
    """Fig. 7's components at 3 and 25 bars through the circuit, as the fit's calculation."""
    q = spec.resolve(spec.load_circuit(F1))
    from varimu.devices.library import component_data

    d = component_data("F1@1")["carbon"]
    fp = float(q["preload_n"])
    vals = {k: float(q[k]) for k in fit.fixed()} | {k: float(q[k]) for k in fit.FREE}
    fs = 96000
    t = np.arange(int(0.4 * fs)) / fs
    for p_bar, jones in ((3.0, (20.5, 16.0)), (25.0, (16.2, 11.2))):
        a = p_bar * fit.BAR_PA * math.sqrt(2)
        x = a * (np.sin(2 * np.pi * 1500 * t) + np.sin(2 * np.pi * 1700 * t))
        x *= np.minimum(1, t / 0.05)
        v, _ = run(x)
        y = v["v(out)"][-fs // 10 :]  # 0.1 s: 10 periods of 100 cycles
        spec_ = np.abs(np.fft.rfft(y)) / len(y)
        b = 10  # 100-cycle bins
        fund = 0.5 * (spec_[15 * b] + spec_[17 * b])
        prod = 0.5 * (spec_[2 * b] + spec_[32 * b])
        got = 20 * np.log10(fund / prod)
        want = fit.products_db(vals, fp, d["exponent"], d["soft_n"] / fp, d["g_open_s"], p_bar)
        assert got == pytest.approx(want, abs=1.0), p_bar
        assert min(jones) - 5 < got < max(jones) + 5, p_bar  # Fig. 7: between sum and difference


def test_chain_runs():
    """carbon_clean builds and finds its operating point (the bleed is the joint's DC path)."""
    pytest.importorskip("circuitsim", reason="needs `uv sync --extra fast`")
    from varimu.measure import metrics
    from varimu.sim import fast
    from varimu.sim.io import TransientSettings

    ir = builder.build(
        spec.load_circuit(CONFIG_DIR / "circuits" / "carbon_clean.yaml"), {"gain_db_clean": 20}
    ).ir  # the list's default
    assert any(e.name.startswith("XCB") for e in ir.elements())
    s = TransientSettings.from_sim_settings(engine="circuitsim", quality="draft")
    fs = s.sample_rate
    x = _tone(fs, 1000.0, math.sqrt(2), 0.3)[1]  # 94 dB SPL
    y = fast.run_transient(ir, x, settings=s).vectors["v(out)"][-fs // 10 :]
    a = metrics.harmonics(y, 1000.0, fs).amps[0]
    # ~0.12 V/Pa across the transmitter, x 10 (the clean preamp at 20 dB): ~1.7 V peak
    assert 1.0 < a < 2.5
