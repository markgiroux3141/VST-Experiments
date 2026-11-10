"""The multitrack deck (docs/PERIOD_GEAR_BACKLOG.md, PG1): MT2, four tracks on one tape and
one transport (the medium as it is: each Tape element's transport keyed by the circuit's
seed, its grain by its name), and MT3's crosstalk model (`varimu.multitrack.crosstalk`)
against Ampex's measured curve."""

from __future__ import annotations

import dataclasses
import math

import numpy as np
import pytest

from varimu.devices import library
from varimu.devices.tape import HeadGeometry, Orientation, TapeNoise
from varimu.devices.tape_machine import TapeMachineSpec, TapeStream
from varimu.multitrack import crosstalk as x

FS = 96_000.0
OE = 1000.0 / (4.0 * math.pi)
HEAD_351 = HeadGeometry(6.35e-6, 1.5e-3, 5.5e-3)


# --- formats ---------------------------------------------------------------------------


def test_the_four_track_format_fits_half_inch_tape():
    f = x.FOUR_TRACK_HALF_INCH
    assert f.guard_m == pytest.approx(60 * x.MIL)
    span = 3 * f.pitch_m + f.width_m
    assert span < f.tape_m
    assert [j for j, _ in f.neighbours(0)] == [1]
    assert [j for j, _ in f.neighbours(3)] == [2]
    assert [j for j, _ in f.neighbours(1)] == [0, 2]
    assert f.neighbours(1, reach=2)[-1] == (3, pytest.approx(2 * f.pitch_m))
    with pytest.raises(ValueError, match="don't fit"):
        x.TrackFormat("x", 4, 85 * x.MIL, 145 * x.MIL, 500 * x.MIL, "")


# --- MT3: the crosstalk model ----------------------------------------------------------


def test_the_lateral_factor_agrees_with_quadrature_and_falls_with_distance():
    w = 1.78e-3
    for k in (40.0, 500.0, 5e3):
        got = x.lateral([k], 3.3e-3, w)[0]
        assert got == pytest.approx(x.lateral_quad(k, 3.3e-3, w), rel=1e-9)
    near, far = x.lateral([500.0], 3.3e-3, w)[0], x.lateral([500.0], 6.6e-3, w)[0]
    assert 0 < far < near < 1
    # Short waves don't cross the guard band: exp(-k (d - w)) and faster.
    k = np.array([2e3, 4e3])
    lat = x.lateral(k, 3.3e-3, w)
    assert lat[1] / lat[0] < math.exp(-(k[1] - k[0]) * (3.3e-3 - w))
    with pytest.raises(ValueError, match="overlap"):
        x.lateral([100.0], 1e-3, 2e-3)


def test_the_bands_average_power():
    f = np.geomspace(20, 20e3, 500)
    db = np.where(f < 1e3, -40.0, -60.0)
    c, b = x.bands(f, db, per_octave=1)
    assert b[0] == pytest.approx(-40.0) and b[-1] == pytest.approx(-60.0)


@pytest.fixture(scope="module")
def fitted():
    return x.fit(HEAD_351)


def test_the_model_meets_ampexs_curve_on_its_octave_envelope(fitted):
    """Fitted on the three-track Model 300's curve (the 354 manual p 12): within 2.5 dB rms
    on octaves; the mid band is the cores' coupling, the top octaves the record heads'."""
    c, rms = fitted
    assert rms < 2.5
    f, db = x.measured()
    mid = (f > 500) & (f < 3000)
    got = c.curve_db(f[mid], 0.381, x.THREE_TRACK_HALF_INCH)
    assert np.abs(got - db[mid]).max() < 3.5
    # Above ~16 kHz Ampex's curve levels off at -43 dB (the heads' resonance or the
    # equalizers' roll-off, not modelled); the couplings keep rising, 3.1 dB over at 19.6 kHz.
    top = (f > 8e3) & (f < 16e3)
    got = c.curve_db(f[top], 0.381, x.THREE_TRACK_HALF_INCH)
    assert np.abs(got - db[top]).max() < 2.0
    # The bass crosses most: the lowest octave tens of dB above the mid band.
    lo = c.curve_db(np.array([31.5]), 0.381, x.THREE_TRACK_HALF_INCH)[0]
    assert lo > -45.0


def test_four_tracks_on_half_inch_cross_about_50_db(fitted):
    """AI-14 p 13: four tracks on 1/2 in, crosstalk rejection around 50 dB (mid band)."""
    c = fitted[0].scaled()
    fmt = x.FOUR_TRACK_HALF_INCH
    mid = c.curve_db(np.array([500.0, 1000.0, 2000.0]), 0.381, fmt)
    assert np.all((mid > -56.0) & (mid < -48.0))
    # Half the speed halves the wavelengths' frequencies: the bass bleed moves down an octave.
    k_fast = c.curve_db(np.array([40.0]), 0.381, fmt)[0]
    k_slow = c.curve_db(np.array([20.0]), 0.1905, fmt)[0]
    assert k_fast == pytest.approx(k_slow, abs=1e-6)


# --- MT2: four tracks, one transport ---------------------------------------------------


def _small():
    spec = TapeMachineSpec(
        pole_m=50e-6,
        relax_m=50e-6,
        layers=2,
        table_step=0.0,
        zone_floor_oe=120.0,
        local_zones=True,
        demag_iterations=3,
        block_m=0.4e-3,
        margin_m=0.1e-3,
        head_distance_m=3e-3,
    )
    tape = library.load_tape("SCOTCH111@2")
    tape = dataclasses.replace(tape, orientation=Orientation(tape.orientation.kappa, 3))
    n = int(0.012 * FS)
    t = np.arange(n) / FS
    h = 300 * OE * np.sin(2 * math.pi * 1000 * t) * np.clip(t / 0.006, 0.05, 1.0)
    return spec, tape, h, 750 * OE


def _grainy(tape):
    return dataclasses.replace(tape, noise=TapeNoise(4.7e-21, 0.35, 0.05, 20e-6))


def test_tracks_of_one_tape_share_the_transport_and_not_the_grain():
    """Four streams of one circuit: one transport (keyed by the circuit's seed, not the
    track: the same speeds bit for bit, the same playback without grain), each its own
    grain (keyed by the element's name)."""
    spec, tape, h, bias = _small()
    assert spec.flutter
    names = ("VT1", "VT2", "VT3", "VT4")
    clean = [
        TapeStream(spec, tape, bias, FS, engine="rust", noise_name=n, transport_seed=11)
        for n in names
    ]
    speeds = [st._speeds(1, 4000) for st in clean]
    for s in speeds[1:]:
        np.testing.assert_array_equal(s, speeds[0])
    assert np.std(speeds[0]) > 0
    outs = [st.push_many(h) for st in clean]
    for o in outs[1:]:
        np.testing.assert_array_equal(o, outs[0])
    grainy = [
        TapeStream(
            spec,
            _grainy(tape),
            bias,
            FS,
            engine="rust",
            noise_seed=11,
            noise_name=n,
            transport_seed=11,
        ).push_many(h)
        for n in names
    ]
    noise = [g - outs[0] for g in grainy]
    late = slice(len(h) // 2, None)
    for i in range(4):
        for j in range(i + 1, 4):
            r = np.corrcoef(noise[i][late], noise[j][late])[0, 1]
            assert abs(r) < 0.5, (i, j, r)


def test_narrow_tracks_hiss_as_the_square_root_of_their_width():
    """The grain's playback noise against the signal: S/N in proportion to sqrt(width)
    (Ampex AI-14 p 11: +3 dB per doubling), so the 300-4's 70 mil tracks are 5.3 dB under the
    351's full track (234 mil). The hiss is unbiased tape's (the particles alone): the small
    machine's biased silence also records a residue that scales with width like a signal."""
    spec, tape, h, bias = _small()
    tape = _grainy(tape)
    sn = {}
    for mil in (70, 234):
        sp = dataclasses.replace(spec, track_m=mil * x.MIL, flutter=False)
        sig = TapeStream(sp, dataclasses.replace(tape, noise=None), bias, FS).push_many(h)
        hiss = TapeStream(sp, tape, 0.0, FS, noise_seed=5).push_many(np.zeros_like(h))
        late = slice(len(h) // 2, None)
        sn[mil] = 20 * math.log10(np.std(sig[late]) / np.std(hiss[late]))
    assert sn[234] - sn[70] == pytest.approx(10 * math.log10(234 / 70), abs=0.3)


# --- MT1: the tape ---------------------------------------------------------------------


def test_scotch_202_is_111_moved_to_eilers_figures():
    """SCOTCH202@1 (scripts/make_scotch202.py, current): Eilers' 315 Oe against 111's 270, the
    same 0.64 lines per 1/4 in (0 dB re 111), half the particle volume (provisional)."""
    import subprocess
    import sys

    from varimu.config import REPO_ROOT

    r = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "make_scotch202.py"), "--check"],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stdout + r.stderr
    t, u = library.load_tape("SCOTCH202@1"), library.load_tape("SCOTCH111@3")
    assert t.preisach.hc_median_a_m / u.preisach.hc_median_a_m == pytest.approx(315 / 270)
    assert t.ms_a_m * t.coating_m == pytest.approx(u.ms_a_m * u.coating_m)
    assert t.noise.particle_volume_m3 == pytest.approx(0.5 * u.noise.particle_volume_m3)
