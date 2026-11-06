"""The D6's electronics (config/circuits/clavinet_d6.yaml, drawn from Hohner's E7 schematic;
docs/CLAVINET_PLAN.md, CL2): the idle point, the tone rockers' shapes on the drawn circuit,
all rockers off silent, [G13]'s amp figures (the -3 dB at 130 Hz with the tone stack
removed; 1% THD at the pickups' largest normal level, which sets d6.yaml's `level_v`, and
3.6% about 6 dB above it)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np
import pytest

from varimu.clavinet import spec

pytest.importorskip("circuitsim")

_spec = importlib.util.spec_from_file_location(
    "clavinet_amp_study", Path(__file__).parents[1] / "scripts" / "clavinet_amp_study.py"
)
study = importlib.util.module_from_spec(_spec)
sys.modules["clavinet_amp_study"] = study
_spec.loader.exec_module(study)

FS = study.FS
FREQS = np.unique(np.round(np.geomspace(40, 12000, 40)))


def _response(sw: dict) -> np.ndarray:
    """The chain node over the centre pickup's EMF (dB) at FREQS."""
    x_in = study.multisine(FREQS, 0.002, FS // 2)
    v = study.render({"pickup_select": 0, **sw}, x_in)
    h = study.tone_bins(v["x"], FREQS) / study.tone_bins(x_in, FREQS)
    return 20 * np.log10(np.abs(h) + 1e-30)


def _at(r: np.ndarray, f_hz: float) -> float:
    return float(np.interp(np.log(f_hz), np.log(FREQS), r))


def test_idle_point() -> None:
    v = study.render({}, np.zeros(int(0.03 * FS)))
    vcc = v["vcc"][-1]
    assert 7.2 < vcc < 7.8  # the BC238 on the 8.2 V zener, a Vbe below it
    assert 1.2 < v["c1"][-1] < 2.2  # Q1 self-biased through its 1 MOhm
    assert v["e2"][-1] + 0.5 < v["c2"][-1] < vcc - 0.5  # Q2 in its active region


def test_tone_shapes() -> None:
    all_ = _response(study.TONES["ALL"])
    band = (FREQS > 2000) & (FREQS < 6000)
    notch = FREQS[band][np.argmin(all_[band])]
    assert 3000 < notch < 4200  # TREBLE + BRILLIANT's series resonance
    assert _at(all_, 1000) - np.min(all_[band]) > 5
    tre = _response(study.TONES["TREBLE"])
    assert 180 < FREQS[np.argmax(tre)] < 450  # the 0.22 uF coupling against TREBLE's 2 H
    assert _at(tre, 1000) - _at(tre, 40) > 25  # a high-pass
    bri = _response(study.TONES["BRILLIANT"])
    assert _at(bri, 1000) - _at(bri, 40) > 35  # a steeper high-pass (0.6 H)
    soft = _response(study.TONES["SOFT"])
    assert _at(soft, 100) - _at(soft, 10000) > 15  # a low-pass
    none = _response(study.TONES["NONE"])
    assert np.max(all_) - np.max(none) > 60  # every rocker off: the chain shorts the signal


def test_amp_figures() -> None:
    shelf = study.amp_shelf({"pickup_select": 0})
    assert shelf["130"] == pytest.approx(-3.0, abs=1.0)  # [G13] 2.3.6
    assert shelf["4000"] == pytest.approx(-0.13, abs=0.5)  # the drawn circuit (G13: +3)
    level = spec.load()["pickups"]["level_v"]
    d, _ = study.thd_at({"pickup_select": 0}, 2 * level)
    assert d == pytest.approx(0.01, abs=0.0015)  # [G13] 3.4: 1% at normal playing's peak
    d, _ = study.thd_at({"pickup_select": 0}, 2 * level * 10 ** (6.6 / 20))
    assert d == pytest.approx(0.036, abs=0.006)  # 3.6% on fortissimo peaks, 6.6 dB up
