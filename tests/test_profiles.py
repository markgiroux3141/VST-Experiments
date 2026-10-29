"""Per-circuit profiles (device builder B2, step 5; B9 step 4): varimu.measure.profiles,
generic, eq_suite, amp_suite."""

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
    assert profiles.profile("fender_5e3").kind == "guitar_amp"
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


def test_speaker_power_is_mean_v_times_i():
    """amp_suite's speaker power from v(out) and the load's admittance equals mean(v i) of
    a periodic signal, the current from the admittance bin by bin."""
    from varimu.circuit.spec import circuit_path, load_circuit, resolve
    from varimu.measure import amp_suite

    p = resolve(load_circuit(circuit_path("fender_5e3")))
    fs, n = 96000, 9600  # 0.1 s: whole periods of 1 kHz and its harmonics
    t = np.arange(n) / fs
    v = 10 * np.sin(2 * np.pi * 1000 * t) + 3 * np.cos(2 * np.pi * 3000 * t + 0.4)
    y = amp_suite.speaker_admittance(p, np.fft.rfftfreq(n, 1 / fs))
    i = np.fft.irfft(np.fft.rfft(v) * y, n)

    class R:
        sample_rate = fs
        vectors = {"v(out)": v}
        meta = {"params": p}

    assert amp_suite.speaker_power_w(R, n) == pytest.approx(float(np.mean(v * i)), rel=1e-9)
    z80 = abs(1 / amp_suite.speaker_admittance(p, np.array([80.0]))[0])
    assert 35 < z80 < 40  # the P12R's resonance: Re + Res, 37.6 ohm


def test_amp_profile_measures_the_nominal_5e3(tmp_path, monkeypatch):
    """The 5E3's report (measured 2026-10-29): it passes its screen (B+1..3 within 0.5% of
    the kit, idle -90 dBFS re 60 V); 1 kHz gain at half volume 45.5 dB bright, 40.0 normal
    (the bright channel's .0005 around its volume), 60.8 / 60.6 dB at full; 1% THD at
    28 mV peak in at half volume (1.8 W); at most ~13 W into the speaker; a full-drive
    burst sags B+2 by ~10%, B+3 by ~8% (recovering in ~0.45 s, 22K x 16 uF), and lifts the
    6V6 cathodes ~20%; aliasing of a hard-clipped 2902 Hz -40 dB at production, -31 at
    draft, -8 at draft-1x."""
    pytest.importorskip("circuitsim", reason="needs `uv sync --extra fast`")
    from varimu.measure import amp_suite

    monkeypatch.setattr(amp_suite, "REPORT_DIR", tmp_path)
    r = amp_suite.run("nominal", {}, log=lambda _: None)
    assert r["plausible"], r["checks"]
    g = r["gain"]
    assert g["bright"]["gain_db"][4] == pytest.approx(45.5, abs=1.0)
    assert g["normal"]["gain_db"][4] == pytest.approx(40.0, abs=1.0)
    assert g["bright"]["gain_db"] == sorted(g["bright"]["gain_db"])
    half = r["distortion"]["0.5"]
    assert 0.02 < half["onset"]["in_v_peak"] < 0.04
    assert 11.0 < half["max_power_w"] < 16.0
    thd = [row["thd_pct"] for row in half["rows"]]
    assert thd[:10] == sorted(thd[:10])  # rising with level up to clipping
    sag = r["sag"]["1000_hz"]
    assert -12.0 < sag["b2"]["change_pct"] < -7.0 and sag["k6"]["change_pct"] > 10.0
    assert 0.3 < sag["b3"]["recover_63_s"] < 0.6
    alias = [r["aliasing"][q]["alias_db"] for q in ("production", "draft", "draft-1x")]
    assert alias == sorted(alias) and alias[0] < -35.0
    assert (tmp_path / "nominal" / "aliasing.png").exists()
