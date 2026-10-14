"""Audio <-> ngspice transient I/O (varimu.sim.io)."""

import dataclasses

import numpy as np
import pytest
import soundfile as sf

from varimu.sim import ngspice
from varimu.sim.io import (
    TransientSettings,
    load_audio,
    read_raw,
    run_transient,
    upsample,
    write_audio,
)

FS = 96000


def test_load_audio_folds_to_mono_and_resamples(tmp_path):
    t = np.arange(4800) / 48000
    left, right = np.sin(2 * np.pi * 1000 * t), 0.5 * np.sin(2 * np.pi * 1000 * t)
    sf.write(tmp_path / "st.wav", np.column_stack([left, right]), 48000, subtype="FLOAT")
    x = load_audio(tmp_path / "st.wav", FS)
    assert x.ndim == 1 and len(x) == 9600
    # Mono fold is the channel mean: a 0.75-amplitude 1 kHz sine, band-limited resampled.
    assert np.max(np.abs(x[500:-500])) == pytest.approx(0.75, rel=1e-3)


def test_write_audio_is_mono_float32(tmp_path):
    write_audio(tmp_path / "a" / "x.wav", np.linspace(-1, 1, 100), FS)
    info = sf.info(tmp_path / "a" / "x.wav")
    assert (info.channels, info.samplerate, info.subtype) == (1, FS, "FLOAT")


def test_read_raw_parses_binary_rawfile(tmp_path):
    t = np.linspace(0, 1e-3, 7)
    v = np.sin(t * 1e3)
    header = (
        "Title: test\nDate: x\nPlotname: Transient Analysis\nFlags: real\n"
        "No. Variables: 2\nNo. Points: 7       \nVariables:\n"
        "\t0\ttime\ttime\n\t1\tV(Out)\tvoltage\nBinary:\n"
    )
    data = np.column_stack([t, v]).astype("<f8").tobytes()
    (tmp_path / "x.raw").write_bytes(header.encode() + data)
    r = read_raw(tmp_path / "x.raw")
    np.testing.assert_array_equal(r["time"], t)
    np.testing.assert_array_equal(r["v(out)"], v)  # names are lower-cased


@pytest.mark.parametrize("n,chunk", [(10, 3), (12, 4), (1000, 999), (5, 10)])
def test_input_chunks_sum_to_the_linear_interpolation(n, chunk):
    """A filesource interpolates linearly and holds its end values, like np.interp."""
    from varimu.sim.io import input_chunks

    x = np.random.default_rng(n).standard_normal(n)
    rate = 10.0
    t = np.linspace(-0.5, (n + 2) / rate, 50 * n)
    total = sum(np.interp(t, tc, vc) for tc, vc in input_chunks(x, rate, chunk))
    expected = np.interp(t, np.arange(n) / rate, x)
    np.testing.assert_allclose(total, expected, atol=1e-12)
    for tc, _ in input_chunks(x, rate, chunk):
        assert tc[0] == 0.0 and np.all(np.diff(tc) > 0)


def _have_ngspice():
    try:
        ngspice.find_ngspice()
        return True
    except ngspice.SimulatorNotFound:
        return False


spice = pytest.mark.skipif(not _have_ngspice(), reason="ngspice not available")


@spice
def test_round_trip_through_rc_matches_exact_response():
    """Band-limited noise through an RC low-pass vs the exact frequency-domain answer.

    The residual is the high-frequency droop of linear interpolation between
    solver timepoints (see varimu/sim/io.py); at 2x oversampling it is about
    -31 dB rms for flat 20 Hz-20 kHz noise, so -25 dB leaves margin.
    """
    s = dataclasses.replace(TransientSettings.from_sim_settings(), oversample=2)
    rng = np.random.default_rng(0)
    n = FS // 8
    X = np.fft.rfft(rng.standard_normal(n))
    f = np.fft.rfftfreq(n, 1 / FS)
    X[(f > 20000) | (f < 20)] = 0
    x = np.fft.irfft(X, n) * np.hanning(n)
    x = np.concatenate([0.5 * x / np.abs(x).max(), np.zeros(FS // 50)])

    r_ohm, c_f = 1e3, 1 / (2 * np.pi * 1e3 * 8000)
    m = 4 * len(x)
    fm = np.fft.rfftfreq(m, 1 / FS)
    exact = np.fft.irfft(np.fft.rfft(x, m) / (1 + 2j * np.pi * fm * r_ohm * c_f), m)[: len(x)]

    seen = []
    res = run_transient(
        f"r1 in out {r_ohm}\nc1 out 0 {c_f}",
        x,
        input_node="in",
        save=["v(out)", "v(in)"],
        settings=s,
        progress=seen.append,
    )
    y = res.vectors["v(out)"]
    assert len(y) == len(x) and res.sample_rate == FS
    err_db = 20 * np.log10(np.std(y - exact) / np.std(exact))
    assert err_db < -25, err_db
    assert seen and seen[-1] == 1.0
    # The input arrives unchanged apart from the same interpolation droop.
    assert 20 * np.log10(np.std(res.vectors["v(in)"] - x) / np.std(x)) < -25


@spice
def test_chunked_input_matches_single_file(monkeypatch):
    """Series filesources reproduce the one-file result (ngspice holds/interpolates as modeled)."""
    import varimu.sim.io as io

    s = dataclasses.replace(TransientSettings.from_sim_settings(), oversample=1)
    x = np.sin(2 * np.pi * 997 * np.arange(3000) / FS) * np.hanning(3000)
    net, save = "r1 in out 1k\nc1 out 0 1n", ["v(out)", "v(in)"]
    one = run_transient(net, x, input_node="in", save=save, settings=s)
    monkeypatch.setattr(io, "CHUNK_LINES", 700)
    many = run_transient(net, x, input_node="in", save=save, settings=s)
    for v in save:
        np.testing.assert_allclose(many.vectors[v], one.vectors[v], atol=2e-4)


@spice
def test_input_holds_through_the_last_timepoint(tmp_path):
    """ngspice's last timepoint can land a rounding error past the file's last entry
    (times are written with 15 digits), where a filesource stops holding its value.
    Measured on ngspice 47 with this length and rate: the input read 0 there."""
    s = dataclasses.replace(TransientSettings.from_sim_settings(), oversample=4)
    t = np.arange(2880) / FS
    x = np.sin(2 * np.pi * 1000 * t) * np.clip(t / 3e-3, 0, 1)
    run_transient("r1 in 0 1k\n", x, input_node="in", save=["v(in)"], settings=s, workdir=tmp_path)
    raw = read_raw(tmp_path / "out.raw")
    x_up = upsample(x, s.oversample)
    assert raw["time"][-1] == pytest.approx((len(x_up) - 1) / s.sim_rate, rel=1e-12)
    assert raw["v(in)"][-1] == pytest.approx(x_up[-1], abs=1e-9)


@spice
def test_failed_simulation_raises():
    with pytest.raises(ngspice.SimulationFailed):
        run_transient(
            "r1 in out 1k\nr2 out 0 bogus_value", np.zeros(100), input_node="in", save=["v(out)"]
        )
