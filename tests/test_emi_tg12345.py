"""The EMI TG12345 Mk II's mic input (docs/CHAINS_PLAN.md WP20), built by inference:
config/circuits/emi_tg12345.yaml (the handbook's topology and figures, the forum's values;
data/schematics/emi_tg12345/README.md).

It builds, passes the pre-flight checks, idles with its direct-coupled output at 0 V; the
gain is the handbook's: 1:3.16 and Amplifier D's 25 +-5 dB (35 dB nominal, FINE 30-40), COARSE
5 dB a step; at least 1.4 V rms into 3k (hb 12.27.4).
"""

from __future__ import annotations

import numpy as np
import pytest

from varimu import preflight
from varimu.circuit import builder, spec
from varimu.config import CONFIG_DIR

TG = CONFIG_DIR / "circuits" / "emi_tg12345.yaml"
FS = 96000.0


@pytest.fixture(scope="module")
def tg():
    return spec.load_circuit(TG)


def test_builds_and_every_value_is_sourced(tg):
    for cores in ("ja", "linear"):
        c = builder.build(tg, cores=cores)
        assert (c.text is None) == (cores == "ja")
    assert spec.check_genome_links(tg) == []


def test_preflight_passes(tg):
    assert preflight.check_circuit(tg) == []


def _run(c, over, f_hz=1000.0, amp=1e-3, dur_s=0.12):
    from varimu.measure import metrics
    from varimu.sim import fast

    ir = builder.build_ir(c, spec.resolve(c, over), "ja")
    t = np.arange(int(dur_s * FS)) / FS
    x = amp * np.sin(2 * np.pi * f_hz * t) * np.minimum(1.0, t / 0.02)
    v = {k: np.asarray(y) for k, y in fast.run_transient(ir, x).vectors.items()}
    if amp == 0.0:
        return None, v
    h = metrics.harmonics(v["v(out)"][-int(0.05 * FS) :], f_hz, int(FS))
    return h, v


def test_idle_output_at_zero(tg):
    pytest.importorskip("circuitsim")
    _, v = _run(tg, {}, amp=0.0, dur_s=0.03)
    assert abs(v["v(out)"][-1]) < 2e-3


def test_gain_fine_and_coarse(tg):
    pytest.importorskip("circuitsim")
    cases = (({}, 34.8), ({"fine": -5}, 29.8), ({"fine": 5}, 39.8), ({"coarse": 15}, 19.6),
             ({"coarse": 55}, -20.4))  # fmt: skip
    for over, want in cases:
        h, _ = _run(tg, over)
        assert 20 * np.log10(h.amps[0] / 1e-3) == pytest.approx(want, abs=0.3), over


def test_drives_1v4_into_3k(tg):
    """hb 12.27.4: 'at least 1.4V r.m.s. into a load of 3kOhm': 2 V rms out under 0.1% THD."""
    pytest.importorskip("circuitsim")
    h, _ = _run(tg, {}, amp=2.0 * np.sqrt(2) / 10 ** (34.8 / 20))
    assert h.amps[0] / np.sqrt(2) == pytest.approx(2.0, rel=0.03)
    assert h.thd < 1e-3
