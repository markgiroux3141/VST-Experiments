"""Per-circuit profiles (device builder B2, step 5): varimu.measure.profiles, generic, eq_suite."""

import numpy as np
import pytest

from varimu.circuit import netlist as nl
from varimu.measure import generic, metrics, profiles
from varimu.sim import runner
from varimu.sim.io import TransientSettings


def test_670_jobs_build_the_670_as_before():
    """A job without a circuit renders the 670 through its API: the same circuit, so the
    same cache keys and reports as before profiles existed."""
    s = TransientSettings.from_sim_settings(engine="circuitsim")
    x = np.zeros(64)
    ov = {"time_constant": 4}
    job = runner.RenderJob(x, ov)
    via_runner = runner.build_circuit(job, s)
    direct = nl.build(ov, triode_formulation=s.triode_formulation, cores=s.cores)
    assert via_runner.ir == direct.ir and via_runner.text == direct.text
    assert runner._key(via_runner, x, s) == runner._key(direct, x, s)
    eq = runner.build_circuit(runner.RenderJob(x, circuit="pultec_eqp1a"), s)
    assert runner._key(eq, x, s)[0] != runner._key(direct, x, s)[0]


def test_profiles():
    assert profiles.profile("fairchild_670").kind == "compressor"
    assert profiles.profile("pultec_eqp1a").kind == "equalizer"
    with pytest.raises(KeyError, match="no measurement profile"):
        profiles.profile("nope")


def test_generic_checks():
    fs = 96000
    t = np.arange(fs // 10) / fs
    assert generic.quiet(1e-6 * np.sin(2 * np.pi * 50 * t))["passes"]
    assert not generic.quiet(1e-2 * np.sin(2 * np.pi * 25e3 * t))["passes"]
    rails = generic.rails({"v(b)": np.full(10, 108.0)}, {"b": 100.0}, 5)
    assert rails["b"]["passes"] and rails["b"]["value"]["pct"] == 8.0
    assert not generic.rails({"v(b)": np.full(10, 85.0)}, {"b": 100.0}, 5)["b"]["passes"]
    tone = np.sin(2 * np.pi * 1000 * t)
    assert generic.no_spurs(metrics.harmonics(tone, 1000.0, fs))["passes"]
    osc = tone + 0.01 * np.sin(2 * np.pi * 31.5e3 * t)  # off the harmonics
    assert not generic.no_spurs(metrics.harmonics(osc, 1000.0, fs))["passes"]
    assert generic.gain(-0.5, 0.0)["passes"] and not generic.gain(-9.0, 0.0)["passes"]


def test_eq_profile_measures_the_nominal_pultec(tmp_path, monkeypatch):
    """The EQP-1A's report (measured 2026-10-26): it passes its screen; at the selected
    frequencies LF boost 13.4 / atten 17.6 / HF atten 16.7 dB against the brochure's
    13.5 / 17.5 / 16, HF boost sharp 20.6 against 18; 65 of 68 points of the published
    curves within 2 dB; THD at +10 dBm 0.0055% (matched tubes; units with drawn part and
    tube tolerances 0.07%) against the brochure's 0.15%."""
    pytest.importorskip("circuitsim", reason="needs `uv sync --extra fast`")
    from varimu.measure import eq_suite

    monkeypatch.setattr(eq_suite, "REPORT_DIR", tmp_path)
    r = eq_suite.run("nominal", {}, log=lambda _: None)
    assert r["plausible"], r["checks"]
    ranges = r["vs_published"]["ranges"]
    for ctl in ("lf_boost", "lf_atten", "hf_atten"):
        assert ranges[ctl]["sim_db"] == pytest.approx(ranges[ctl]["published_db"], abs=1.0)
    assert 18.0 < ranges["hf_boost"]["sim_db"] < 22.0
    agree, total = map(int, r["vs_published"]["curves"]["agree"].split("/"))
    assert agree >= total - 4
    assert r["distortion"]["thd_pct_at_10dbm"] < 0.15
    thd = [row["thd_pct"] for row in r["distortion"]["rows"]]
    assert thd == sorted(thd)  # rising with level
    assert (tmp_path / "nominal" / "response.png").exists()
