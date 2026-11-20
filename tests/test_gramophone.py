"""The shellac 78 and the acoustic gramophone (docs/PHONO_PLAN.md G2; varimu/phono/disc.py,
gramophone.py)."""

from __future__ import annotations

import numpy as np
import pytest

from varimu.phono import disc
from varimu.phono import gramophone as gr
from varimu.phono import groove as gv


def test_spiral_arc_length_turns_and_radius():
    sp = disc.Spiral(0.1175, 2.54e-4)
    s_turns = sp.turns_s(0.0, 30.0)
    # One turn's arc is 2 pi r at the turn's mean radius; each turn moves in one pitch.
    r = sp.radius(s_turns)
    assert np.allclose(np.diff(r), -2.54e-4, rtol=1e-9)
    mean_r = 0.5 * (r[1:] + r[:-1])
    assert np.allclose(np.diff(s_turns), 2 * np.pi * mean_r, rtol=1e-6)
    assert np.allclose(np.angle(np.exp(1j * sp.theta(s_turns))), 0.0, atol=1e-6)


def test_arc_positions_follow_the_shrinking_radius():
    sp = disc.Spiral(0.1175, 2.54e-4)
    fs = 8000.0
    n = int(60 * fs)
    w = 2 * np.pi * 78 / 60
    omega = np.full(n, w)
    s = disc.arc_positions(omega, w * np.arange(n) / fs, fs, sp, 0.0, 0.0)
    v = np.diff(s) * fs
    r = sp.radius(s[1:])
    assert np.max(np.abs(v / (w * r) - 1)) < 1e-4


def test_an_unworn_point_dilates_each_wall_as_a_sphere():
    rng = np.random.default_rng(0)
    w = np.cumsum(rng.standard_normal(4000)) * 2e-7
    ds = 4e-6
    a = disc.dilate_worn(w, ds, 4e-5, 0.0)
    b = gv.dilate(w, ds, 4e-5)
    assert np.max(np.abs(a - b)) < 1e-15


def test_a_flat_longer_than_the_wavelength_rests_on_the_crests():
    ds = 1e-6
    s = np.arange(20000) * ds
    lam = 5e-5
    w = 1e-6 * np.sin(2 * np.pi * s / lam)
    y = disc.dilate_worn(w, ds, 4e-5, 6e-5)
    assert np.allclose(y[2000:-2000], 1e-6, rtol=1e-3)


def test_the_needle_flat_grows_as_the_cube_root():
    a = disc.needle_flat(np.array([0.0, 1.0, 8.0, 100.0]), 4e-5, 100.0)
    assert a[0] == 0.0
    assert np.isclose(a[2] / a[1], 2.0)
    assert np.isclose(a[3], 4e-5)


def test_tracking_error_reads_ahead_by_its_tangent():
    ds = 1e-6
    s = np.arange(200000) * ds
    lam = 2e-4
    k = 2 * np.pi / lam
    amp = 2e-5
    y = amp * np.sin(k * s)
    phi = np.full(len(s), np.deg2rad(10))
    z = disc.tracking_remap(y, ds, phi)
    seg = z[20000:-20000] * np.hanning(len(z) - 40000)
    spec = np.abs(np.fft.rfft(seg))
    f = np.fft.rfftfreq(len(seg), ds)
    h1 = spec[np.argmin(abs(f - 1 / lam))]
    h2 = spec[np.argmin(abs(f - 2 / lam))]
    expect = np.tan(np.deg2rad(10)) * k * amp / 2
    assert h2 / h1 == pytest.approx(expect, rel=0.05)
    assert disc.tracking_angle(0.09, 0.23, np.hypot(0.23, 0.09)) == pytest.approx(0.0, abs=1e-12)


@pytest.fixture(scope="module")
def tone_take():
    spec = gr.load()
    fs = 48000
    t = np.arange(int(0.5 * fs)) / fs
    x = np.sin(2 * np.pi * 800 * t) * np.clip(t / 0.02, 0, 1)
    rec = gr.record(spec, x, fs)
    return spec, rec


def test_the_cut_reaches_the_formats_amplitude(tone_take):
    spec, rec = tone_take
    loud = np.percentile(np.abs(rec.z_m), spec["record"]["cut_level_percentile"])
    assert loud == pytest.approx(spec["record"]["max_amplitude_m"], rel=1e-9)


def test_the_needle_rests_on_its_downforce_and_rides_up_twice_a_cycle(tone_take):
    pytest.importorskip("circuitsim")
    spec, rec = tone_take
    # The arm aligned with the groove's radius here: no tracking error (it adds an f line
    # to the height at second order, through its own second harmonic).
    aligned = dict(spec, arm=dict(spec["arm"]))
    aligned["arm"]["pivot_to_spindle_m"] = float(np.hypot(spec["arm"]["length_m"], 0.1175))
    pb = gr.play(aligned, rec, needle_played_m=None)
    lead = rec.lead_in_samples
    a = gr.wall_angle(spec)
    rest = pb.forces_n[:, lead - 2000 : lead - 1000].mean(axis=1)
    assert rest.sum() * np.cos(a) == pytest.approx(spec["arm"]["downforce_n"], rel=0.02)
    # The pinch effect: a symmetric lateral groove moves the tip's height at twice the
    # tone's frequency, not at it.
    yv = pb.tip_y_m[lead + 30000 : lead + 30000 + 2**16]
    yv = (yv - yv.mean()) * np.hanning(len(yv))
    f = np.fft.rfftfreq(len(yv), 1 / pb.fs_hz)
    spec_v = np.abs(np.fft.rfft(yv))

    def line(hz):
        return spec_v[(f > hz - 20) & (f < hz + 20)].max()

    assert line(1600) > 100 * line(800)
    assert pb.mistracking_fraction() < 1e-3


@pytest.mark.parametrize("machine", ["victor_exhibition", "victor_orthophonic"])
def test_rust_gramophone_equals_the_reference(tone_take, machine):
    """Within -120 dB: the ducts' loss nodes (massless, horn.py) add near-zero modes, and
    the modal transform's condition number is ~6e7 (Victor) / ~9e8 (Orthophonic), so the
    modal player agrees with the dense reference to ~1e-7 (it was 2e6 and -195 dB on the
    lossless cylinder)."""
    pytest.importorskip("circuitsim")
    _, rec = tone_take
    spec = gr.load(machine)
    k = int(0.06 * len(rec.y_m))
    short = gr.DiscRecord(
        rec.y_m[:k].copy(), rec.wall_l_m[:k].copy(), rec.wall_r_m[:k].copy(), rec.ds_m,
        rec.spiral, rec.z_m, rec.pa_per_unit, rec.lead_in_samples, rec.fs_hz, rec.omega,
        rec.s_m,
    )  # fmt: skip
    gr.surface(short, spec, 2)
    a = gr.play(spec, short, needle_played_m=0.0, engine="python")
    b = gr.play(spec, short, needle_played_m=0.0, engine="rust")
    d = np.max(np.abs(a.pressure_pa - b.pressure_pa)) / np.max(np.abs(a.pressure_pa))
    assert 20 * np.log10(d) < -120
    df = np.max(np.abs(a.forces_n - b.forces_n)) / np.max(np.abs(a.forces_n))
    assert 20 * np.log10(df) < -120


def test_the_victor_follows_maxfield_and_harrisons_old_machine():
    """Fig. 20's curve B ('one of the best commercial machines previously on the market',
    data/datasheets/maxfield_harrison_1926_fig20.csv): the model's output per groove
    velocity, its level matched by the mean offset. Fitted by scripts/fit_gramophone.py
    (2026-11-18): 4.9 dB rms over 238-3900 Hz, with guards against resonances below the
    curve's start and between its read points (an unguarded fit reached 3.4 dB with a
    +20 dB duct resonance at 207 Hz)."""
    import csv
    from pathlib import Path

    path = Path(__file__).parents[1] / "data" / "datasheets" / "maxfield_harrison_1926_fig20.csv"
    with path.open(encoding="utf-8") as fh:
        rows = [r for r in csv.DictReader(fh) if r["curve"] == "B"]
    f = np.array([float(r["f_hz"]) for r in rows])
    level = np.array([float(r["level_db"]) for r in rows])
    keep = (f >= 238) & (f <= 3900)
    f, level = f[keep], level[keep]
    spec = gr.load()
    model = 20 * np.log10(np.abs(gr.reproducer_response(spec, f) / (2j * np.pi * f)))
    err = model - level
    err -= err.mean()
    assert np.sqrt(np.mean(err**2)) < 5.5


def _fig20(curve: str, lo: float, hi: float):
    import csv
    from pathlib import Path

    path = Path(__file__).parents[1] / "data" / "datasheets" / "maxfield_harrison_1926_fig20.csv"
    with path.open(encoding="utf-8") as fh:
        rows = [r for r in csv.DictReader(fh) if r["curve"] == curve]
    f = np.array([float(r["f_hz"]) for r in rows])
    level = np.array([float(r["level_db"]) for r in rows])
    keep = (f >= lo) & (f <= hi)
    return f[keep], level[keep]


def test_the_orthophonic_is_maxfield_and_harrisons_design():
    spec = gr.load("victor_orthophonic")
    d = gr.ortho_design(spec)
    assert d["z0"] == pytest.approx(2.92, rel=2e-3)  # 2920 mechanical ohms (cgs)
    assert np.pi * d["throat_radius_m"] ** 2 == pytest.approx(2.37e-4, rel=0.02)  # G A1^2 / z0
    assert d["arm_ratio"] == pytest.approx(
        np.sqrt(4.5 / d["z0"]), rel=1e-9
    )  # to 4500 at the record
    # The needle's bending spring is the design's needle-point compliance (c / 2)(z0 / z_rec).
    c_half = 0.5 / d["k_section"] * d["z0"] / spec["orthophonic"]["record_impedance_ns_m"]
    assert 1.0 / gr.needle(spec).stiffness_n_m == pytest.approx(c_half, rel=0.02)


def test_the_orthophonic_follows_its_measured_curve_unfitted():
    """Fig. 20's curve A, the design's values only (no fit: measured 2026-11-18, 4.2 dB rms
    over 115-3900 Hz, 4.1 with the ducts' wall losses; fitting its four provisional values
    bought 0.3 dB at their bounds)."""
    f, level = _fig20("A", 115.0, 3900.0)
    spec = gr.load("victor_orthophonic")
    model = 20 * np.log10(np.abs(gr.reproducer_response(spec, f) / (2j * np.pi * f)))
    err = model - level
    err -= err.mean()
    assert np.sqrt(np.mean(err**2)) < 5.0


def test_the_electrical_recorder_cuts_uniform_velocity():
    """Maxfield and Harrison p. 5: uniform velocity 200-4000 Hz, uniform amplitude below."""
    spec = gr.load("victor_orthophonic")
    f = np.array([50.0, 100.0, 300.0, 1000.0, 3000.0, 4500.0, 8000.0])
    v = np.abs(gr.recorder_response(spec, f) * 2j * np.pi * f)
    db = 20 * np.log10(v / v[3])
    assert np.all(np.abs(db[2:6]) < 2.0)
    assert db[0] - db[1] == pytest.approx(-6.0, abs=1.5)  # amplitude, not velocity, below
    assert db[6] < -15.0
