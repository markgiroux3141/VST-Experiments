"""The D6's electronics (config/circuits/clavinet_d6.yaml) against [G13] (docs/CLAVINET_PLAN.md,
CL2): the tone rockers' shapes (Fig. 11), all rockers off silent, the amp's shelves and its
THD at 400 mV (the fitted figures, kept), the idle point sane."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("circuitsim")

_spec = importlib.util.spec_from_file_location(
    "clavinet_amp_study", Path(__file__).parents[1] / "scripts" / "clavinet_amp_study.py"
)
study = importlib.util.module_from_spec(_spec)
sys.modules["clavinet_amp_study"] = study
_spec.loader.exec_module(study)

FS = study.FS


def _response(sw: dict) -> tuple[np.ndarray, np.ndarray]:
    freqs = np.unique(np.round(np.geomspace(200, 12000, 40)))
    x_in = study.multisine(freqs, 0.01, FS // 2)
    v = study.render({"pickup_select": 0, **sw}, x_in)
    h = study.tone_bins(v["x"], freqs) / study.tone_bins(x_in, freqs)
    return freqs, 20 * np.log10(np.abs(h) + 1e-30)


def test_idle_point() -> None:
    v = study.render({}, np.zeros(int(0.03 * FS)))
    vcc = v["vcc"][-1]
    assert 8.0 < vcc < 9.0
    for c, e in (("c1", "e1"), ("c2", "e2")):
        assert v[e][-1] + 0.5 < v[c][-1] < vcc - 0.5  # both stages in their active region


def test_tone_shapes() -> None:
    f, tre = _response(study.TONES["TREBLE"])
    assert 1450 < f[np.argmax(tre)] < 1850  # TREBLE's 2 H || 4.7 nF
    f, all_ = _response(study.TONES["ALL"])
    band = (f > 2000) & (f < 6000)
    assert 3000 < f[band][np.argmin(all_[band])] < 4200  # TREBLE + BRILLIANT's series notch
    f, bri = _response(study.TONES["BRILLIANT"])
    assert bri[-1] > bri[0] + 20  # high-pass
    f, soft = _response(study.TONES["SOFT"])
    assert soft[0] > soft[-1] + 10  # low-pass
    f, none = _response(study.TONES["NONE"])
    assert np.max(none) < -100  # every rocker off: silent


def test_amp_figures() -> None:
    shelf = study.amp_shelf({"pickup_select": 0})
    assert shelf["130"] == pytest.approx(-3.0, abs=0.5)
    assert shelf["4000"] == pytest.approx(3.0, abs=0.5)
    d, _ = study.thd_at({"pickup_select": 0}, 0.4)
    assert d == pytest.approx(0.01, abs=0.003)
