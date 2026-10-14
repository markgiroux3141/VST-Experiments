"""Listening support: loudness matching, the app's control schema and override plumbing."""

import numpy as np
import pytest

pytest.importorskip("pyloudnorm")

from varimu.listen import matching  # noqa: E402

FS = 48000


def _tone(amp, f=440.0, s=2.0):
    t = np.arange(int(s * FS)) / FS
    return amp * np.sin(2 * np.pi * f * t)


def test_clips_are_matched_to_one_loudness():
    clips = [_tone(0.05), _tone(0.3, 1000), _tone(0.01, 3000)]
    out, info = matching.match_loudness(clips, FS, target=-23.0)
    after = [matching.integrated_lufs(c, FS) for c in out]
    np.testing.assert_allclose(after, -23.0, atol=0.05)
    assert info.target_lufs == -23.0


def test_shared_target_drops_instead_of_clipping():
    # A peaky clip (short click train) needs far more gain than its peak allows.
    click = np.zeros(2 * FS)
    click[:: FS // 10] = 0.5
    out, info = matching.match_loudness([_tone(0.5), click], FS, target=-10.0)
    assert info.target_lufs < -10.0
    assert max(np.max(np.abs(c)) for c in out) <= matching.PEAK_CEILING + 1e-9
    after = [matching.integrated_lufs(c, FS) for c in out]
    assert after[0] == pytest.approx(after[1], abs=0.05)


def test_gain_trace_measures_level_ratio_and_ignores_silence():
    dry = np.concatenate([_tone(0.5, s=1.0), np.zeros(FS)])
    wet = 0.25 * dry
    t, g = matching.gain_trace(dry, wet, FS)
    assert np.nanmedian(g) == pytest.approx(20 * np.log10(0.25), abs=1e-6)
    assert np.all(np.isnan(g[t > 1.05]))


def test_app_schema_and_overrides():
    pytest.importorskip("fastapi")
    from varimu.circuit import netlist as nl
    from varimu.listen import app

    schema = app.control_schema()
    keys = [c["key"] for c in schema]
    for k in ("input_atten_db", "ac_threshold", "time_constant", "balance", "zero",
              "dc_threshold", "v6386_a.emission_scale", "grid_contact_v",
              "psu_source_impedance_ohm"):  # fmt: skip
        assert k in keys
    for c in schema:
        assert c["min"] <= c["default"] <= c["max"], c["key"]
        assert c["source"]
    ov = app.to_overrides({"grid_contact_v": -0.6, "time_constant": 3.0})
    assert ov == {
        "v6386_a.grid_contact_v": -0.6,
        "v6386_b.grid_contact_v": -0.6,
        "time_constant": 3,
    }
    nl.resolve(ov)  # accepted by the netlist
