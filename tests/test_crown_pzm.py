"""The Crown PZM-30D (the chains build-out's WP26): config/circuits/crown_pzm.yaml, the topology of
AKG / Crown's PZM30 D schematic with every value inferred and fitted by scripts/fit_pzm.py to the
manual's figures (data/schematics/crown_pzm/).

It builds and passes the pre-flight checks; draws the manual's 1.1 mA from 48 V phantom; gives 7
mV/Pa open circuit and 240 ohm; its RISING and FLAT responses follow Fig. 1; positive pressure gives
a positive output (pin 2); its overload (3% THD at ~141.5 dB SPL against the manual's 150).
"""

import math
import sys

import numpy as np
import pytest

from varimu import preflight
from varimu.circuit import builder, spec
from varimu.config import CONFIG_DIR, REPO_ROOT

PZM = CONFIG_DIR / "circuits" / "crown_pzm.yaml"


def test_builds_and_preflight():
    c = spec.load_circuit(PZM)
    builder.build(c)
    assert spec.check_genome_links(c) == []
    assert preflight.check_circuit(c) == []


@pytest.fixture(scope="module")
def bench():
    pytest.importorskip("circuitsim", reason="needs `uv sync --extra fast`")
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    import fit_pzm

    return fit_pzm, fit_pzm.Bench()


def test_current_drain(bench):
    _, b = bench
    assert b.drain_a() == pytest.approx(1.1e-3, rel=0.01)  # akg: 1.1 mA


def test_sensitivity_impedance_polarity(bench):
    _, b = bench
    oc = b.tones([1000.0], over={"r_pre_leg_ohm": 1e9, "response": 1})[0]
    ld = b.tones([1000.0], over={"r_pre_leg_ohm": 120.0, "response": 1})[0]
    assert abs(oc) == pytest.approx(0.007, rel=0.04)  # akg: 7 mV/Pa open circuit
    assert 240.0 * (abs(oc) / abs(ld) - 1) == pytest.approx(240.0, rel=0.05)  # akg: 240 ohm
    assert abs(math.degrees(np.angle(oc))) < 45  # akg: positive pressure, positive pin 2


def test_response_follows_fig1(bench):
    fit, b = bench
    tr = fit.load_trace()
    for name, sw, tol in (("rising", 0, 2.0), ("flat", 1, 1.5)):
        f, d = tr[name][:, 0], tr[name][:, 1]
        h = b.tones(f, over={"response": sw})  # (1 kHz is one of the trace's points)
        got = 20 * np.log10(np.abs(h) / abs(h[f == 1000.0][0]))
        err = got - d
        assert np.sqrt(np.mean(err**2)) < tol, (name, np.round(err, 2))


def test_overload(bench):
    """akg: 150 dB SPL produces 3% THD (open circuit). The inferred follower reaches 3% at ~141.5
    dB (a known miss, WP26's Notes: it starves into the transformer's reflected load)."""
    _, b = bench
    assert b.thd_at(140.0) < 0.03
    assert 0.03 < b.thd_at(145.0) < 0.3


def test_on_a_boundary_the_pressure_doubles():
    """A mic on the floor (scene.surface_placement, 1 mm up) hears the floor's reflection with the
    direct sound: +6 dB in the room's first arrivals, flat to 20 kHz (no comb), where a mic 0.5 m
    up has the comb. Image sources only (no tail), an omni entry table."""
    from varimu.rooms import entries
    from varimu.rooms.scene import surface_placement
    from varimu.rooms.shoebox import Mic, Shoebox, aim_vector, responses

    room = Shoebox((7.0, 5.5, 3.2), ("concrete_floor",) * 6)
    f = np.geomspace(entries.F_MIN_HZ, 24000.0, 32)
    th = np.radians(np.arange(0, 180.1, entries.THETA_STEP_DEG))
    ir = np.r_[0.0, 1 / np.array(entries.DISTANCES_M[:-1])[::-1]]
    ones = np.ones((len(f), len(ir), len(th)), complex)
    table = entries.EntryTable(f, th, ir, ones, ones, "omni")
    fs = 96000
    pos, az, el = surface_placement(room, np.array([3.5, 2.75, 1.3]), "floor")
    assert pos[2] == pytest.approx(0.001) and el == 90.0
    mics = [
        Mic(pos, aim_vector(az, el), table),
        Mic(np.array([3.5, 2.75, 0.5]), aim_vector(0), table),
    ]
    src = np.array([1.5, 2.75, 1.0])
    h = responses(room, [src], mics, fs, ism_s=0.0125, length_s=0.05, tail=False)[0, :, 0]
    n = int(0.0135 * fs)  # the direct sound and the floor's (images within ~4 m of path)
    spec = np.abs(np.fft.rfft(h[:, :n], 4 * n))
    fr = np.fft.rfftfreq(4 * n, 1 / fs)
    band = (fr > 200) & (fr < 20000)
    floor = 20 * np.log10(spec[0, band])
    comb = 20 * np.log10(spec[1, band])
    # the floor mic: direct and image coincide, (2 / r)^2; the 0.5 m mic's comb averages to the
    # two arrivals' powers, (1 / r1)^2 + (1 / r2)^2
    r = np.linalg.norm(src - pos)
    m2 = mics[1].position_m
    r1, r2 = np.linalg.norm(src - m2), np.linalg.norm(src - m2 * [1, 1, -1])
    want = 10 * np.log10((2 / r) ** 2 / (1 / r1**2 + 1 / r2**2))
    got = np.median(floor) - 10 * np.log10(np.mean(10 ** (comb / 10)))
    assert got == pytest.approx(want, abs=0.7)
    assert np.ptp(floor) < 3.0  # no comb on the boundary
    assert np.ptp(comb) > 10.0  # the 0.5 m mic's comb (nulls ~20 dB deep, sampled)
