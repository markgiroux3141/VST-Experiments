"""The SSL 4000 E mic amplifier (the chains build-out's WP4): config/circuits/ssl_4000e.yaml.

It builds from the generic format and passes the pre-flight checks at every switch
position; its JT-115K-E matches Jensen's sheet in Jensen's test circuit
(config/circuits/jt115k_test.yaml, the fit's targets and the checks it doesn't target);
the gain follows the 82E01's arithmetic (data/schematics/ssl_4000e/README.md), the pad
takes about 20 dB off, PHASE flips the output.
"""

import numpy as np
import pytest

from varimu import preflight
from varimu.circuit import builder, spec
from varimu.config import CONFIG_DIR

SSL = CONFIG_DIR / "circuits" / "ssl_4000e.yaml"
JT = CONFIG_DIR / "circuits" / "jt115k_test.yaml"


@pytest.fixture(scope="module")
def ssl():
    return spec.load_circuit(SSL)


def test_builds_and_every_value_is_sourced(ssl):
    for cores in ("ja", "linear"):
        c = builder.build(ssl, cores=cores)
        assert (c.text is None) == (cores == "ja")
    assert spec.check_genome_links(ssl) == []
    a = builder.build_ir(ssl, spec.resolve(ssl, {"passive_spread": 1.0, "passive_seed": 3}))
    b = builder.build_ir(ssl, spec.resolve(ssl))
    moved = sum(e != e0 for e, e0 in zip(a.elements(), b.elements(), strict=True))
    assert moved > 20


def test_preflight_passes(ssl):
    assert preflight.check_circuit(ssl) == []


def test_the_transformer_is_the_test_circuits():
    """ssl_4000e.yaml and jt115k_test.yaml carry the same JT-115K-E."""
    a, b = spec.resolve(spec.load_circuit(SSL)), spec.resolve(spec.load_circuit(JT))
    keys = [k for k in b if k.startswith("jt_")]
    assert len(keys) == 10
    assert {k: a[k] for k in keys} == {k: b[k] for k in keys}


def test_switches_rewire(ssl):
    def names(**ov):
        return {e.name for e in builder.build_ir(ssl, spec.resolve(ssl, ov)).elements()}

    assert {"RSW1A5", "RSW1B6"} <= names(pad=0) and not {"R3", "R6"} & names(pad=0)
    assert {"R3", "R6"} <= names(pad=1) and not {"RSW1A5", "RSW1B6"} & names(pad=1)
    assert {"RPH0S", "RPH0G"} <= names(phase=0) and {"RPH1S", "RPH1G"} <= names(phase=1)


def _gain_law_db(x: float) -> float:
    """The 82E01's T1 / T9 gain with the wiper a fraction x of the way from 19 to 33 (T4
    is unity): (1 + 10k x / (R9 || R10)) R71 / (10k (1 - x) + R69)."""
    r9_10 = 619.0 * 10e3 / (619.0 + 10e3)
    return 20 * np.log10((1 + 10e3 * x / r9_10) * 10.7e3 / (10e3 * (1 - x) + 619.0))


def _tone(c, ov, f=1000.0, amp=1e-3, n_periods=40):
    pytest.importorskip("circuitsim", reason="needs `uv sync --extra fast`")
    from varimu.sim import fast
    from varimu.sim.io import TransientSettings

    st = TransientSettings.from_sim_settings(engine="circuitsim")
    fs = st.sample_rate
    n0 = int(0.3 * fs)
    t = np.arange(n0 + int(n_periods * fs / f)) / fs
    x = amp * np.sin(2 * np.pi * f * t) * np.clip(t / 0.15, 0, 1)
    r = fast.run_transient(builder.build_ir(c, spec.resolve(c, ov)), x, settings=st)
    sl = slice(n0, None)
    basis = np.array([np.sin(2 * np.pi * f * t[sl]), np.cos(2 * np.pi * f * t[sl])]).T

    def ph(y):
        a = np.linalg.lstsq(basis, y[sl], rcond=None)[0]
        return a[0] + 1j * a[1]

    return {k[2:-1]: ph(v) for k, v in r.vectors.items()}, ph(x)


@pytest.mark.parametrize("x", [0.0, 0.5, 1.0])
def test_gain_follows_the_drawing(ssl, x):
    """T1 -> T9 -> T4 (sy to t4o) within 0.15 dB of the arithmetic at 1 kHz; the whole
    (the source's EMF to out, 150 ohm source) is that plus the transformer's ~19 dB."""
    amp = 1e-3 * 10 ** (-_gain_law_db(x) / 20)
    v, xin = _tone(ssl, {"mic_gain": x}, amp=amp)
    amps_db = 20 * np.log10(abs(v["t4o"]) / abs(v["sy"]))
    assert amps_db == pytest.approx(_gain_law_db(x), abs=0.15)
    whole_db = 20 * np.log10(abs(v["out"]) / abs(xin))
    assert whole_db - _gain_law_db(x) == pytest.approx(19.0, abs=0.6)


def test_pad_and_phase(ssl):
    """The pad takes 17-20 dB off (rev: 'a 20 dB pad'); PHASE 0 keeps the polarity of the
    whole (T9 and T4 both invert), 1 reverses it."""
    v0, x0 = _tone(ssl, {"mic_gain": 0.3})
    v1, _ = _tone(ssl, {"mic_gain": 0.3, "pad": 1})
    vp, _ = _tone(ssl, {"mic_gain": 0.3, "phase": 1})
    pad_db = 20 * np.log10(abs(v1["out"]) / abs(v0["out"]))
    assert -20.0 < pad_db < -17.0
    assert abs(np.angle(v0["out"] / x0)) < 0.2
    assert abs(abs(np.angle(vp["out"] / x0)) - np.pi) < 0.2


def test_the_transformer_against_jensen():
    """In Jensen's test circuit 1, at -20 dBu on the primary: the fitted figures (scripts/
    fit_jt115k.py: 1% THD at 20 Hz at -2.5 dBu; -3 dB at 2.5 Hz; -0.13 dB at 20 kHz and
    -3 dB at 90 kHz, the last on the linear-core build's AC analysis) and the ones it
    doesn't target: the gain (jensen 19.75 dB), the
    20 Hz response (-0.26 dB), the input impedance (1.40 kOhm: the model reads ~1.54, the
    turns ratio's reflected 150k; a known miss), the 20 Hz THD at -20 dBu (jensen 0.065%:
    the model's mumetall reads ~0.3-0.4%, a known miss: docs/CHAINS_PLAN.md WP4's Notes)."""
    pytest.importorskip("circuitsim", reason="needs `uv sync --extra fast`")
    from varimu.measure import ac
    from varimu.measure.transformer_sheet import measure, response_db

    c = spec.load_circuit(JT)
    m1 = measure(c, {}, 1000.0)
    assert m1["gain_db"] == pytest.approx(19.75, abs=0.1)
    assert m1["zin_ohm"] == pytest.approx(1400, rel=0.12)
    assert response_db(c, {}, 2.5) == pytest.approx(-3.0, abs=0.3)
    assert response_db(c, {}, 20.0) == pytest.approx(-0.26, abs=0.15)
    r20k = response_db(c, {}, 20e3)
    assert r20k == pytest.approx(-0.13, abs=0.1)
    h = ac.transfer(builder.build_ir(c, spec.resolve(c), cores="linear"), [1e3, 20e3, 90e3], "out")
    assert 20 * np.log10(abs(h[1] / h[0])) == pytest.approx(r20k, abs=0.05)  # AC = transient
    assert 20 * np.log10(abs(h[2] / h[0])) == pytest.approx(-3.0, abs=0.3)  # past Nyquist: AC
    assert 0.7e-2 < measure(c, {}, 20.0, -2.5)["thd"] < 1.4e-2
    assert measure(c, {}, 20.0, -20.0)["thd"] < 0.6e-2
