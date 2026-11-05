"""The Tascam Portastudio 424's mic input (the chains build-out's WP4):
config/circuits/tascam_portastudio.yaml.

It builds and passes the pre-flight checks; TRIM's law follows the drawing's arithmetic
(data/schematics/tascam_424/README.md) over a 40 dB range (the jack's "-50 ~ -10 dBV"); a
reverse-taper pot reads its taper from the far end; U101A clips near +9 dBu on the 424's
half rail.
"""

import numpy as np
import pytest

from varimu import preflight
from varimu.circuit import builder, parts, spec
from varimu.config import CONFIG_DIR

PORTA = CONFIG_DIR / "circuits" / "tascam_portastudio.yaml"


@pytest.fixture(scope="module")
def porta():
    return spec.load_circuit(PORTA)


def test_builds_and_every_value_is_sourced(porta):
    for cores in ("ja", "linear"):
        builder.build(porta, cores=cores)
    assert spec.check_genome_links(porta) == []
    a = builder.build_ir(porta, spec.resolve(porta, {"passive_spread": 1.0, "passive_seed": 3}))
    b = builder.build_ir(porta, spec.resolve(porta))
    assert sum(e != e0 for e, e0 in zip(a.elements(), b.elements(), strict=True)) > 8


def test_preflight_passes(porta):
    assert preflight.check_circuit(porta) == []


def test_reverse_pot():
    """`reverse` reads the taper from end_b: the share from end_a is 1 - taper(1 - pos);
    linear, it is the plain pot."""
    a, b = parts.pot("R", "x", "w", "y", 10e3, 0.5, 0.1, reverse=True)
    assert b.r_ohm == pytest.approx(1000.0) and a.r_ohm == pytest.approx(9000.0)
    lin = parts.pot("R", "x", "w", "y", 10e3, 0.3, None, reverse=True)
    assert [r.r_ohm for r in lin] == pytest.approx([3000.0, 7000.0])


def _law_db(c, trim: float) -> float:
    """U101A's gain from its + input to C104's far end: (R102 + Rw) / (Rw + R102 k), k the
    wiper's share of the track above R104 (to AC ground), Rw its source resistance."""
    q = spec.resolve(c, {"trim": trim})
    els = {e.name: e.r_ohm for e in builder.build_ir(c, q).elements() if hasattr(e, "r_ohm")}
    up, low = els["R103a"], els["R103b"] + q["r104_ohm"]
    k = low / (up + low)
    rw = up * low / (up + low)
    return float(20 * np.log10((q["r102_ohm"] + rw) / (rw + q["r102_ohm"] * k)))


def _tone(c, ov, amp, f=1000.0, n_periods=40):
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
    cols = []
    for k in range(1, 8):
        cols += [np.sin(2 * np.pi * k * f * t[sl]), np.cos(2 * np.pi * k * f * t[sl])]
    basis = np.array(cols).T

    def ph(y):
        a = np.linalg.lstsq(basis, y[sl], rcond=None)[0]
        return a[0::2] + 1j * a[1::2]

    return {k[2:-1]: ph(v) for k, v in r.vectors.items()}, ph(x)


def test_trim_law(porta):
    """From the jack's tip (ia) to out within 0.3 dB of the arithmetic (the input's RC and
    the load take ~0.1 dB); the range 0 to +39.9 dB (the jack's -50 to -10 dBV)."""
    assert _law_db(porta, 0.0) == pytest.approx(0.0, abs=0.01)
    assert _law_db(porta, 1.0) == pytest.approx(39.9, abs=0.1)
    for trim in (0.0, 0.5, 1.0):
        amp = 0.05 * 10 ** (-_law_db(porta, trim) / 20)
        v, _ = _tone(porta, {"trim": trim}, amp)
        g = 20 * np.log10(abs(v["out"][0]) / abs(v["ia"][0]))
        assert g == pytest.approx(_law_db(porta, trim), abs=0.3), trim


def test_clips_near_plus_9_dbu(porta):
    """At 0 dB of trim: clean at +3 dBu out (THD < 0.1%), clipped at +12 dBu EMF (THD > 3%)."""
    v_lo, _ = _tone(porta, {"trim": 0.0}, 0.775 * np.sqrt(2) * 10 ** (3 / 20))
    v_hi, _ = _tone(porta, {"trim": 0.0}, 0.775 * np.sqrt(2) * 10 ** (12 / 20))

    def thd(h):
        return np.sqrt(np.sum(np.abs(h[1:]) ** 2)) / abs(h[0])

    assert thd(v_lo["out"]) < 1e-3
    assert thd(v_hi["out"]) > 3e-2
