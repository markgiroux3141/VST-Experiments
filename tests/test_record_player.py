"""The 1960s record player (docs/PHONO_PLAN.md, "The 1960s record player"): the stereo
groove's geometry, the lathe, the changer, the cartridge."""

import numpy as np
import pytest

from varimu.phono import microgroove as mg
from varimu.phono import rimdrive as rd

A45 = np.deg2rad(45.0)


def test_equal_channels_cut_laterally_and_opposite_ones_vertically():
    u = np.linspace(-1e-5, 1e-5, 11)
    x, z = mg.channels_to_xz(u, u, A45)
    assert np.allclose(z, 0.0) and np.allclose(x, np.sqrt(2) * u)
    x, z = mg.channels_to_xz(u, -u, A45)
    assert np.allclose(x, 0.0) and np.allclose(z, np.sqrt(2) * u)


def test_one_channel_moves_one_wall_only():
    u = np.sin(np.linspace(0, 20, 200)) * 1e-5
    x, z = mg.channels_to_xz(u, np.zeros_like(u), A45)
    left, right = mg.walls(x, z, A45)
    assert np.allclose(left, u) and np.allclose(right, 0.0, atol=1e-20)
    a, b = mg.xz_to_channels(x, z, A45)
    assert np.allclose(a, u) and np.allclose(b, 0.0, atol=1e-20)


def test_the_incline_reads_a_vertical_sine_with_its_second_harmonic():
    """A cutter inclined beta writes z(s) at s + z tan(beta): read back on the uniform
    grid the sine gains a second harmonic of k A tan(beta) / 2 (the vertical tracking
    error's geometry)."""
    ds, wl, amp = 1e-7, 1e-4, 2e-6
    s = np.arange(200_000) * ds
    z = amp * np.sin(2 * np.pi * s / wl)
    beta = np.deg2rad(20.0)
    grid, (zg,) = mg.resample_on_grid(mg.incline(s, z, beta), [z], ds)
    seg = zg[20_000 : 20_000 + 100_000]
    spec = np.abs(np.fft.rfft(seg * np.hanning(len(seg))))
    k1 = int(round(len(seg) * ds / wl))
    h2 = spec[2 * k1 - 2 : 2 * k1 + 3].max() / spec[k1 - 2 : k1 + 3].max()
    expect = np.pi * amp / wl * np.tan(beta)
    assert h2 == pytest.approx(expect, rel=0.05)


def test_variable_pitch_keeps_the_land_and_follows_the_program():
    fs, rpm = 2000.0, 33.333
    t = np.arange(int(20 * fs)) / fs
    theta = 2 * np.pi * rpm / 60 * t
    exc = np.where(t < 10, 5e-6, 40e-6)  # quiet, then loud
    width = np.full_like(t, 50e-6)
    dr = mg.variable_pitch(theta, exc, width, 25e-6, 60e-6, 250e-6, smooth_turns=0.0)
    turns = np.floor(theta / (2 * np.pi)).astype(int)
    per_turn = np.bincount(turns, dr)
    # Quiet: half widths 50 + excursions 10 + land 25 = 85 um; loud: 50 + 80 + 25 = 155.
    assert per_turn[2] == pytest.approx(85e-6, rel=1e-3)
    assert per_turn[-3] == pytest.approx(155e-6, rel=1e-3)


def test_a_table_spiral_finds_its_turns():
    s = np.linspace(0, 10.0, 100_001)
    r = 0.14 - 1e-4 * s
    theta = np.concatenate([[0.0], np.cumsum(np.diff(s) / (0.5 * (r[1:] + r[:-1])))])
    sp = mg.TableSpiral(s, r, theta)
    hits = sp.turns_s(1.0, 9.0)
    assert np.allclose(np.mod(sp.angle(hits) - 1.0 + np.pi, 2 * np.pi) - np.pi, 0.0, atol=1e-6)
    assert len(hits) == int((sp.angle(9.0) - 1.0) // (2 * np.pi)) + 1


CHANGER = dict(
    fs_hz=2000.0, idler_radius_m=0.02, rim_radius_m=0.11, motor_inertia_kg_m2=2e-5,
    idler_inertia_kg_m2=2e-6, platter_inertia_kg_m2=8e-3, motor_friction_nm_s=1e-5,
    idler_friction_nm_s=1e-6, platter_friction_nm_s=1e-4, contact_stiffness_n_m=2e4,
    contact_damping_ns_m=5.0, mains_hz=50.0, poles=4, mains_v=240.0, rated_v=240.0,
    stall_torque_n_m=0.04, torque_ripple=0.0, pulley_ecc_m=0.0, idler_ecc_m=0.0, rim_ecc_m=0.0,
    idler_flat_m=0.0, idler_flat_rad=0.3, rated_load_n_m=0.01,
)  # fmt: skip


def test_a_perfect_changer_turns_at_its_speed_and_low_mains_slows_it():
    mo = rd.simulate(CHANGER, 33.333, 2.0, 2000.0, 0.01, 1)
    rpm = mo.omega * 60 / (2 * np.pi)
    assert np.allclose(rpm, 33.333, rtol=1e-6)
    low = dict(CHANGER, mains_v=216.0)  # -10%
    rpm_low = rd.simulate(low, 33.333, 2.0, 2000.0, 0.01, 1).omega[-1] * 60 / (2 * np.pi)
    assert 31.0 < rpm_low < 33.3


# LP1: the lathe (config/phono/westrex_3d.yaml).

from varimu.phono import lathe as la  # noqa: E402
from varimu.phono import lp  # noqa: E402


@pytest.fixture(scope="module")
def rec_spec():
    return lp.load()


@pytest.fixture(scope="module")
def card_params(rec_spec):
    return lp.card(rec_spec)


def test_riaa_matches_nabs_table():
    """NAB Disc Standard 1964 Table 1."""
    f = np.array([30.0, 100.0, 1000.0, 10000.0, 15000.0])
    got = la.riaa_reproduce_db(f)
    assert np.allclose(got, [18.61, 13.11, 0.0, -13.75, -17.17], atol=0.03)  # the table rounds


def test_the_cutter_fits_nelson_and_staffords_curves(rec_spec):
    import csv
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    rows = list(csv.DictReader((root / "data" / "datasheets" / "westrex_3d_response.csv").open()))
    ax = la.Axis.from_spec(rec_spec["cutter"])

    def shape_rms(name, model):
        f = np.array([float(r["f_hz"]) for r in rows if r["curve"] == name])
        lv = np.array([float(r["level_db"]) for r in rows if r["curve"] == name])
        e = 20 * np.log10(np.abs(model(f))) - lv
        return np.sqrt(np.mean((e - e.mean()) ** 2))

    assert shape_rms("open_loop", lambda f: la.open_loop(ax, f)[0]) < 1.2
    c = rec_spec["cutter"]
    g = la.gain_for_feedback(ax, c["feedback_db"], c["low_pole_hz"], c["high_pole_hz"])
    closed = shape_rms(
        "closed_loop", lambda f: la.closed_loop(ax, f, g, c["low_pole_hz"], c["high_pole_hz"])[0]
    )
    assert closed < 3.5  # a check: the card trims what remains
    _, loop = la.closed_loop(ax, np.array([la.resonance_hz(ax, np.geomspace(100, 5000, 4000))]), g,
                             c["low_pole_hz"], c["high_pole_hz"])  # fmt: skip
    assert 20 * np.log10(abs(1 + loop[0])) == pytest.approx(28.0, abs=0.01)


def test_the_card_trims_the_cut_to_the_ra1574ds_spec(rec_spec, card_params):
    """NS64: +-1 dB 50 Hz - 12 kHz, +-2 dB 12-15 kHz; NAB: separation at least 26 dB, 100 Hz
    - 7.5 kHz."""
    f = np.geomspace(50, 15000, 80)
    h = la.chain(rec_spec, f, card_params)
    dev = 20 * np.log10(np.abs(h[:, 0, 0]) / np.abs(la.riaa_record(f)))
    assert np.max(np.abs(dev[f <= 12000])) < 1.0
    assert np.max(np.abs(dev[f > 12000])) < 2.0
    sep = 20 * np.log10(np.abs(h[:, 1, 0]) / np.abs(h[:, 0, 0]))
    assert np.max(sep[(f >= 100) & (f <= 7500)]) < -26.0


def test_a_0_vu_tone_cuts_the_reference_on_its_own_wall(rec_spec, card_params):
    fs = 48000
    t = np.arange(int(1.5 * fs)) / fs
    x = np.stack([0.5 * np.sin(2 * np.pi * 1000 * t), np.zeros_like(t)], 1)
    rec = lp.record(rec_spec, x, fs, card_params)
    mid = slice(len(rec.x_m) // 2, len(rec.x_m) // 2 + 20000)
    ref = rec_spec["level"]["reference_cm_s"] / 100 / (2 * np.pi * 1000)
    assert np.max(np.abs(rec.wall_l_m[mid])) == pytest.approx(ref, rel=0.01)
    assert 20 * np.log10(np.std(rec.wall_r_m[mid]) / np.std(rec.wall_l_m[mid])) < -26.0


def test_the_pressing_meets_nabs_surface_noise(rec_spec):
    """LP2: the roughness gives NAB's 50 dB below 5 cm/s at the outer groove."""
    sigma = lp.calibrate_surface(rec_spec)
    v = 2 * np.pi * rec_spec["lathe"]["rpm"] / 60 * rec_spec["lathe"]["outer_radius_m"]
    got = lp.surface_noise_db(sigma, rec_spec, v, rec_spec["numerics"]["fs_hz"], seed=7)
    assert got == pytest.approx(-rec_spec["surface"]["noise_db"], abs=0.5)


# LP3-LP4: the changer and the cartridge (config/phono/ge_rp1560.yaml).

from varimu.phono import portable as po  # noqa: E402


@pytest.fixture(scope="module")
def player(rec_spec):
    return po.calibrate(po.load(), rec_spec)


def test_the_changers_wow_is_a_period_changers(player):
    m = player["changer"]
    mo = rd.simulate(m, 33.3333333, 8.0, 2000.0, 0.008, 1)
    rpm = mo.omega[4000:] * 60 / (2 * np.pi)
    dev = rpm / rpm.mean() - 1
    assert abs(rpm.mean() - 33.333) < 0.2
    assert 0.0005 < np.std(dev) < 0.005  # 0.05-0.5 % rms


def test_the_cartridge_meets_sonotones_figures(player, rec_spec):
    """Sonotone 16T: 0.65 V (taken at 1 kHz, 5 cm/s), 25 dB separation, response 20 Hz - 12 kHz."""
    f = np.array([100.0, 300.0, 1000.0, 3000.0, 6000.0, 10000.0])
    h = po.response(player, rec_spec, f)
    x1k = 0.05 / (2 * np.pi * 1000)
    assert abs(h[2, 0]) * x1k / np.sqrt(2) == pytest.approx(0.65, rel=0.01)
    assert 20 * np.log10(abs(h[2, 1]) / abs(h[2, 0])) == pytest.approx(-25.0, abs=1.5)
    rel = 20 * np.log10(np.abs(h[:, 0]) / abs(h[2, 0]))
    assert np.all(rel < 4.0) and np.all(rel > -2.0)


def test_a_tone_plays_on_its_own_channel(player, rec_spec, card_params):
    pytest.importorskip("circuitsim", reason="needs `uv sync --extra fast`")
    fs = 48000
    t = np.arange(int(1.2 * fs)) / fs
    x = np.stack([0.5 * np.sin(2 * np.pi * 1000 * t), np.zeros_like(t)], 1)
    rec = lp.record(rec_spec, x, fs, card_params)
    pb = po.play(player, rec_spec, rec)
    seg = slice(int(0.7 * pb.fs_hz), int(1.1 * pb.fs_hz))
    a, b = pb.emf_v[0][seg], pb.emf_v[1][seg]
    assert np.std(a) == pytest.approx(0.65, rel=0.05)
    assert 20 * np.log10(np.std(b) / np.std(a)) < -20.0
    assert pb.mistracking_fraction() < 1e-3


def test_the_player_agrees_with_its_python_reference(player, rec_spec, card_params):
    pytest.importorskip("circuitsim", reason="needs `uv sync --extra fast`")
    fs = 48000
    t = np.arange(int(0.35 * fs)) / fs
    x = np.stack([0.4 * np.sin(2 * np.pi * 700 * t), 0.3 * np.sin(2 * np.pi * 1900 * t)], 1)
    rec = lp.record(rec_spec, x, fs, card_params)
    a = po.play(player, rec_spec, rec, engine="rust").emf_v
    b = po.play(player, rec_spec, rec, engine="python").emf_v
    assert 20 * np.log10(np.std(a - b) / np.std(b)) < -120.0


# LP5: the amplifier (config/circuits/ge_rp1560.yaml).


def test_the_amplifier_idles_at_the_sheets_voltages():
    pytest.importorskip("circuitsim", reason="needs `uv sync --extra fast`")
    from varimu.circuit import builder, spec
    from varimu.config import CONFIG_DIR
    from varimu.sim import fast
    from varimu.sim.io import TransientSettings

    c = spec.load_circuit(CONFIG_DIR / "circuits" / "ge_rp1560.yaml")
    st = TransientSettings.from_sim_settings(engine="circuitsim")
    ir = builder.build(c, spec.resolve(c, {})).ir
    v = fast.run_transient(
        ir, np.zeros(48000), settings=st, controls={"in_r": np.zeros(48000)}
    ).vectors
    n = int(0.1 * st.sample_rate)
    sheet = {"b120": 120, "b105": 105, "p_a": 85, "p_b": 85, "k_a": 1.15, "k_b": 1.05,
             "pp_a": 115, "pp_b": 118, "kp": 2.7}  # fmt: skip
    for node, d in sheet.items():
        assert np.mean(v[f"v({node})"][-n:]) == pytest.approx(d, rel=0.20), node


def test_the_tubes_meet_rcas_sheets():
    """35W4@1 reproduces RCA's half-wave regulation; 35EH5@1 its typical class-A1 point."""
    import yaml

    from varimu.config import CONFIG_DIR

    w4 = yaml.safe_load((CONFIG_DIR / "components" / "35w4" / "1.yaml").read_text())
    assert w4["fit_report"]["dc_v_at_50ma"] == pytest.approx(135.0, abs=1.0)
    assert w4["fit_report"]["dc_v_at_100ma"] == pytest.approx(120.0, abs=1.0)
    eh5 = yaml.safe_load((CONFIG_DIR / "components" / "35eh5" / "1.yaml").read_text())
    a = eh5["fit_report"]["class_a1_model"]
    assert a["ip_a"] == pytest.approx(32e-3, rel=0.20)
    assert a["ig2_a"] == pytest.approx(7.2e-3, rel=0.30)
    assert a["gm_s"] == pytest.approx(12e-3, rel=0.30)
