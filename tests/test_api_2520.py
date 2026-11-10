"""The API 2520 op-amp from BJTs (docs/CHAINS_PLAN.md WP12): config/circuits/api_2520_test.yaml,
the GroupDIY "2520 R1" drawing in API's 1972 Fig. 1 feedback (gain 1 + 47k / 470). Checked
against API's data sheet; the bias string and C5 are fitted to the sheet's quiescent current and
bandwidth (WP12's Notes)."""

from __future__ import annotations

import numpy as np
import pytest

from varimu.circuit import builder, spec
from varimu.config import CONFIG_DIR

pytest.importorskip("circuitsim")
from varimu.sim import fast  # noqa: E402

FS = 96000.0


@pytest.fixture(scope="module")
def ir():
    s = spec.load_circuit(CONFIG_DIR / "circuits" / "api_2520_test.yaml")
    return builder.build_ir(s, spec.resolve(s, {}), "ja")


def _run(ir, f_hz, amp_v, dur_s=0.1):
    t = np.arange(int(dur_s * FS)) / FS
    x = amp_v * np.sin(2 * np.pi * f_hz * t) * np.minimum(1.0, t / 0.01)
    return {k: np.asarray(v) for k, v in fast.run_transient(ir, x).vectors.items()}


def test_idle_is_stable_and_centred(ir):
    """No input: the output sits within 20 mV of 0 V and doesn't oscillate (the drawing's C5 on
    Q3's base did: the Notes)."""
    v = _run(ir, 1000.0, 0.0, 0.05)
    o = v["v(out)"][-2400:]
    assert abs(o.mean()) < 0.02
    assert o.max() - o.min() < 1e-3


def test_closed_loop_gain(ir):
    """1 + 47k / 470 = 101 (40.09 dB): the open-loop gain is high enough not to show."""
    o = _run(ir, 1000.0, 0.01)["v(outc)"][-4800:]
    assert 20 * np.log10((o.max() - o.min()) / 0.02) == pytest.approx(40.09, abs=0.1)


def test_rated_output_distortion(ir):
    """api: 0.2% THD 20-20,000 Hz at rated output (7.75 V rms into 600 ohm at +-15 V)."""
    o = _run(ir, 1000.0, 7.75 * np.sqrt(2) / 101.0)["v(outc)"][-4800:]
    o = o - o.mean()
    sp = abs(np.fft.rfft(o * np.hanning(len(o))))
    fr = np.fft.rfftfreq(len(o), 1 / FS)

    def pk(h):
        i = int(np.argmin(abs(fr - 1000.0 * h)))
        return sp[i - 3 : i + 4].max()

    thd = np.sqrt(sum(pk(k) ** 2 for k in range(2, 8))) / pk(1)
    assert thd < 0.002
    assert o.max() > 10.5  # 7.75 V rms reached unclipped


def test_quiescent_current(ir):
    """api: 15 mA quiescent at +-15 V (the bias resistor's fit), most of it in Q7 / Q8."""
    v = _run(ir, 1000.0, 0.0, 0.02)
    L = {k: v[f"v({k})"][-1] for k in ("vA", "vT", "vD", "vF", "e6", "vG", "e7", "out")}
    iq7 = (L["e7"] - L["out"]) / 5.6
    total = (
        (15 - L["vA"]) / 82e3
        + (15 - L["vT"]) / 22e3
        + (15 - L["vD"]) / 3e3
        + (15 - L["vF"]) / 4e3
        + (15 - L["e6"]) / 1e3
        + (15 - L["vG"]) / 56
        + iq7
    )
    assert total == pytest.approx(0.015, rel=0.05)
    assert 0.010 < iq7 < 0.014


def test_low_level_distortion(ir):
    """Class AB at 12.7 mA: 1 V rms into 600 ohm well under api's 0.2% (the class-B idle of the
    first transcription gave 0.16%)."""
    o = _run(ir, 1000.0, np.sqrt(2) / 101.0)["v(outc)"][-4800:]
    o = o - o.mean()
    sp = abs(np.fft.rfft(o * np.hanning(len(o))))
    fr = np.fft.rfftfreq(len(o), 1 / FS)

    def pk(h):
        i = int(np.argmin(abs(fr - 1000.0 * h)))
        return sp[i - 3 : i + 4].max()

    thd = np.sqrt(sum(pk(k) ** 2 for k in range(2, 8))) / pk(1)
    assert thd < 0.0005


def test_bandwidth(ir):
    """At 40 dB the model is -0.5 dB at 20 kHz (-0.3 dB of it the feedback's 47 pF, C5's fit);
    API's Fig. 1 is +-0.25 dB to 20 kHz at 58 dB."""
    o = _run(ir, 20000.0, 0.01)["v(outc)"][-4800:]
    g = 20 * np.log10((o.max() - o.min()) / 0.02)
    assert 39.3 < g < 39.9
