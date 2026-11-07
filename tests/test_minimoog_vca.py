"""The Minimoog VCA (circuit No. 7 of config/circuits/minimoog_filter_board.yaml,
docs/MINIMOOG_PLAN.md MM2): idle bias, Folkman's VCA Balance met at the file's trims
(scripts/minimoog_vca_trim.py --write sets them), the gain over the contour."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("circuitsim")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import minimoog_vca_trim as vt  # noqa: E402
import minimoog_vcf_study as st  # noqa: E402


@pytest.fixture(scope="module")
def s():
    return st.load()


def test_idle_bias_leaves_headroom(s):
    """Contour 0: the 1st stage off (its collectors equal), the output pair in its active
    region with room to swing both ways."""
    v = st.idle(s)
    assert v["v(c16)"] == pytest.approx(v["v(c15)"], abs=1e-3)
    assert 2.0 < v["v(vo)"] < 6.0
    assert v["v(c1)"] - v["v(vo)"] > 3.0  # Q17's emitter-collector


def test_vca_balance_nulls_the_loudness_feedthrough(s):
    """Folkman, 'VCA Balance': EXT. LOUDNESS stepped 4 -> 8 V moves the output by < 5 mV with
    the key up and < 1 mV with it held (untrimmed: hundreds of mV)."""
    assert abs(vt.feedthrough(s, {}, 0.0)) < 5e-3
    assert abs(vt.feedthrough(s, {}, 5.0)) < 1e-3


def _gain_db(s, contour_v, amp_v=0.01, f_hz=220.0):
    ir = st.build(s, {"cutoff_v": 4.0, "emphasis": 0.0})
    t = np.arange(int(0.25 * st.FS)) / st.FS
    v = st.run(ir, amp_v * np.sin(2 * np.pi * f_hz * t), contour_v=contour_v)
    n = int(0.15 * st.FS)
    return 20 * np.log10(np.ptp(v["v(out)"][-n:]) / np.ptp(v[st.VCF][-n:]))


def test_contour_opens_the_vca(s):
    """Shut at contour 0 (< -80 dB re the filter's output), rising monotonically, about unity
    by 3 V (the 1st stage's tail saturating the gain)."""
    g = [_gain_db(s, c) for c in (0.0, 1.0, 2.0, 3.0)]
    assert g[0] < -80.0
    assert g[0] < g[1] < g[2] < g[3]
    assert -4.0 < g[3] < 4.0
