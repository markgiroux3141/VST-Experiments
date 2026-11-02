"""The groove and the acoustic machines (docs/PHONO_PLAN.md G1, varimu/phono/)."""

from __future__ import annotations

import numpy as np
import pytest

from varimu.phono import cylinder as cy
from varimu.phono import damage as dm
from varimu.phono import groove as gv
from varimu.phono import horn
from varimu.phono import transport as tr
from varimu.phono import wear as wr
from varimu.phono.network import GROUND, Network, Stepper

RHO, C = 1.204, 343.0


# The network.


def test_mass_spring_damper_mobility():
    """A force into a mass on a spring and damper: v / F = 1 / (r + j w m + k / j w)."""
    m, k, r = 2e-4, 5e3, 0.3
    net = Network()
    net.capacitor("a", GROUND, m)
    net.inductor("a", GROUND, 1 / k, "spring")
    net.conductance("a", GROUND, r)
    net.current_source("a", "force")
    sys = net.compile()
    f = np.array([50.0, 400.0, 795.0, 3000.0])
    v = sys.response(f, "force")[:, sys.index("a")]
    w = 2 * np.pi * f
    np.testing.assert_allclose(v, 1 / (r + 1j * w * m + k / (1j * w)), rtol=1e-12)


def test_lever_and_gyrator_carry_power():
    """A lever (velocity ratio n) and a diaphragm (area S) are lossless: the power a
    force puts in equals what the load dissipates."""
    n, area, r_ac = 3.0, 2e-4, 5e6
    net = Network()
    net.capacitor("t", GROUND, 1e-5)
    net.transformer("t", GROUND, "d", GROUND, n, "lever")
    net.gyrator("d", "cav", area)
    net.resistor("cav", GROUND, r_ac)
    net.current_source("t", "force")
    sys = net.compile()
    f = np.array([100.0, 1000.0])
    x = sys.response(f, "force")
    vt, vd, p = (x[:, sys.index(k)] for k in ("t", "d", "cav"))
    np.testing.assert_allclose(vd, n * vt, rtol=1e-12)
    p_in = 0.5 * np.real(vt)  # unit force
    p_out = 0.5 * np.abs(p) ** 2 / r_ac
    np.testing.assert_allclose(p_in, p_out, rtol=1e-9)


def test_trapezoid_matches_continuous_response():
    """The stepper's steady sine through the recorder equals the exact response (to the
    trapezoid's frequency warping, ~(pi f / fs)^2 / 3)."""
    spec = cy.load()
    fs = 192000.0
    sys = cy.recorder_network(spec)
    st = Stepper(sys, 1 / fs)
    for f in (300.0, 1700.0):
        t = np.arange(int(0.12 * fs)) / fs
        u = np.sin(2 * np.pi * f * t)
        y = st.run("p_src", u, sys.pick("x_up"))[:, 0]
        tail = slice(int(0.08 * fs), None)
        ref = sys.response(np.array([f]), "p_src")[0, sys.index("x_up")]
        amp = np.sqrt(2 * np.mean(y[tail] ** 2))
        assert amp == pytest.approx(abs(ref), rel=2e-3)


# Ducts and horns.


def test_cylindrical_duct_matches_transmission_line():
    """A 0.3 m pipe's impedance peaks (its resonances, nearly lossless) at the transmission
    line's frequencies within 0.3% below 3 kHz (the ladder's dispersion, (k dx)^2 / 24)."""
    net = Network()
    net.current_source("in", "u")
    length, radius = 0.3, 0.01
    horn.duct(net, "in", "out", length, radius, radius, RHO, C, 0.004, "d")
    horn.radiation(net, "out", GROUND, radius, RHO, C, "r")
    sys = net.compile()
    f = np.linspace(100, 3000, 8000)
    z = np.abs(sys.response(f, "u")[:, sys.index("in")])
    ref = np.abs(
        horn.cylinder_input_impedance(
            f, length, radius, horn.radiation_exact(f, radius, RHO, C), RHO, C
        )
    )

    def peaks(m):
        i = np.flatnonzero((m[1:-1] > m[:-2]) & (m[1:-1] > m[2:])) + 1
        return f[i]

    pz, pr = peaks(z), peaks(ref)
    assert len(pz) == len(pr) == 5
    np.testing.assert_allclose(pz, pr, rtol=3e-3)


def test_cone_ladder_converges_to_stepped_reference():
    """The reproducer's horn as the ladder vs 4000 exact cylindrical steps (both tend to
    Webster's equation): the input impedance's magnitude within 1 dB below 3 kHz."""
    length, r_in, r_out = 0.762, 0.0095, 0.2
    net = Network()
    net.current_source("in", "u")
    horn.duct(net, "in", "out", length, r_in, r_out, RHO, C, 0.004, "h")
    horn.radiation(net, "out", GROUND, r_out, RHO, C, "r")
    sys = net.compile()
    f = np.geomspace(80, 3000, 60)
    z = sys.response(f, "u")[:, sys.index("in")]
    ref = horn.stepped_input_impedance(
        f, length, r_in, r_out, horn.radiation_exact(f, r_out, RHO, C), RHO, C, 4000
    )
    db = 20 * np.log10(np.abs(z) / np.abs(ref))
    assert np.max(np.abs(db)) < 1.0


# The groove.


def _sine_groove(amp, wavelength, ds, periods=12):
    s = np.arange(int(periods * wavelength / ds)) * ds
    return s, amp * np.sin(2 * np.pi * s / wavelength)


def _harmonics(y, s, wavelength, count=3):
    k = 2 * np.pi / wavelength
    n_per = wavelength / (s[1] - s[0])
    keep = slice(int(2 * n_per), int(len(s) - 2 * n_per))  # away from the ends
    ys, ss = y[keep], s[keep]
    return [abs(2 * np.mean(ys * np.exp(-1j * m * k * ss))) for m in range(1, count + 1)]


def test_dilation_matches_lewis_hunt():
    """A sine read by a sphere: the second harmonic is pi^2 R A / lambda^2 (Lewis and Hunt
    1941) while R A k^2 is small."""
    r, wl = 190.5e-6, 400e-6
    for amp in (0.5e-6, 1e-6, 2e-6):
        s, h = _sine_groove(amp, wl, 0.25e-6)
        y = gv.dilate(h, 0.25e-6, r)
        h1, h2, _ = _harmonics(y, s, wl)
        assert h2 / h1 == pytest.approx(gv.tracing_h2(r, amp, wl), rel=0.03)


def test_dilation_is_the_exact_offset_curve():
    """Where the tip fits the troughs (R below the smallest radius of curvature), the
    tip's lowest point follows the groove's offset curve (an independent construction)."""
    r, amp, wl, ds = 190.5e-6, 2e-6, 200e-6, 0.1e-6
    s, h = _sine_groove(amp, wl, ds, periods=4)
    assert r < 1 / (amp * (2 * np.pi / wl) ** 2)
    y = gv.dilate(h, ds, r)
    k = 2 * np.pi / wl
    slope = amp * k * np.cos(k * s)
    norm = np.sqrt(1 + slope**2)
    xc = s - r * slope / norm  # the tip's centre over its contact point
    yc = h + r / norm - r
    keep = (xc > wl) & (xc < 3 * wl)
    ref = np.interp(xc[keep], s, y)
    assert np.max(np.abs(ref - yc[keep])) < 2e-10


def test_dilation_converges_in_sample_spacing():
    """The tracing harmonic at the player's spacing (~2.4 um, 160 rpm at 192 kHz) vs a
    10x finer grid: within 1% (measured: PHONO_PLAN.md, G1's status)."""
    r, amp, wl = 190.5e-6, 8e-6, 300e-6
    out = []
    for ds in (2.42e-6, 0.242e-6):
        s, h = _sine_groove(amp, wl, ds)
        y = gv.dilate(h, ds, r)
        h1, h2, _ = _harmonics(y, s, wl)
        out.append(h2 / h1)
    assert out[0] == pytest.approx(out[1], rel=0.01)


def test_tip_wider_than_trough_skips_it():
    """A tip far wider than a short wave rides its crests: the read amplitude collapses."""
    r, amp, wl, ds = 190.5e-6, 5e-6, 60e-6, 0.25e-6
    s, h = _sine_groove(amp, wl, ds)
    y = gv.dilate(h, ds, r)
    h1 = _harmonics(y, s, wl)[0]
    assert h1 < 0.2 * amp
    assert np.min(y[200:-200]) > 0.0  # never below the crests' line minus their bumps


def test_write_leaves_the_surface_where_the_cutter_lifts_out():
    z = np.array([0.0, -10e-6, -30e-6, 5e-6])
    g = gv.write(z, 0.4655, 192000.0, 20e-6)
    np.testing.assert_allclose(g.h_m, [-20e-6, -10e-6, 0.0, -25e-6])


def test_roughness_is_seeded_with_its_rms_and_correlation():
    a = gv.roughness(400000, 1e-6, 3e-7, 2e-5, 1, "wax")
    b = gv.roughness(400000, 1e-6, 3e-7, 2e-5, 1, "wax")
    np.testing.assert_array_equal(a, b)
    assert np.std(a) == pytest.approx(3e-7, rel=0.05)
    lag = 20
    rho = np.corrcoef(a[:-lag], a[lag:])[0, 1]
    assert rho == pytest.approx(np.exp(-lag * 1e-6 / 2e-5), abs=0.03)


# The machine.


def _tone_groove(spec, f_hz, amp_m, seconds=0.12):
    fs = spec["numerics"]["fs_hz"]
    v = cy.groove_speed(spec, spec["cylinder"]["rpm_recorded"])
    lead = int(0.1 * fs)
    t = np.arange(int(seconds * fs)) / fs
    env = np.minimum(1.0, t / 0.01)
    z = np.concatenate([np.zeros(lead), amp_m * env * np.sin(2 * np.pi * f_hz * t)])
    return gv.write(z, v, fs, spec["cylinder"]["cut_depth_m"]), lead


def test_reproducer_rests_on_its_downforce():
    spec = cy.load()
    g, _ = _tone_groove(spec, 500.0, 0.0, seconds=0.3)  # 0.4 s of plain groove
    pb = cy.play(spec, g)
    assert pb.force_n[-2000:].mean() == pytest.approx(spec["reproducer"]["downforce_n"], rel=1e-4)


def test_mistracking_starts_where_the_force_balance_says():
    """A small tone's contact-force swing predicts the amplitude where it reaches the
    static load (the tip leaves the groove on the downswing); below it no flights, above
    it flights."""
    spec = cy.load()
    f, small = 1500.0, 0.3e-6
    g, lead = _tone_groove(spec, f, small)
    pb = cy.play(spec, g)
    steady = pb.force_n[lead + int(0.04 * pb.fs_hz) :]
    swing = 0.5 * (steady.max() - steady.min())
    onset = small * spec["reproducer"]["downforce_n"] / swing
    for factor, flies in ((0.8, False), (1.25, True)):
        g, lead = _tone_groove(spec, f, factor * onset)
        pb = cy.play(spec, g)
        flights = np.mean(pb.force_n[lead + int(0.04 * pb.fs_hz) :] <= 0.0)
        assert (flights > 0.0) == flies, (factor, flights)


def test_record_cuts_the_formats_maximum():
    spec = cy.load()
    fs = 48000.0
    t = np.arange(int(0.2 * fs)) / fs
    x = np.sin(2 * np.pi * 800 * t) * np.minimum(1, t / 0.02)
    rec = cy.record(spec, x, fs)
    loud = np.percentile(np.abs(rec.z_m), spec["cylinder"]["cut_level_percentile"])
    assert loud == pytest.approx(spec["cylinder"]["max_amplitude_m"])
    assert np.max(rec.groove.h_m) <= 0.0


# The drive (transport.py).


def _quiet_motor(spec, block):
    """A machine with every imperfection removed."""
    m = dict(spec[block])
    for key in (
        "spring_droop_per_s",
        "spring_irregularity",
        "motor_pulley_eccentricity_m",
        "mandrel_pulley_eccentricity_m",
        "felt_irregularity",
        "runout_eccentric_m",
        "runout_oval_m",
    ):
        m[key] = 0.0
    return m


def test_a_perfect_drive_holds_its_set_speed():
    spec = cy.load()
    m = _quiet_motor(spec, "player_motor")
    radius = spec["cylinder"]["diameter_m"] / 2
    mo = tr.simulate(m, 160.0, radius, 2.0, 8000.0, 3e-3, 1, "player")
    rpm = mo.omega * 60 / (2 * np.pi)
    np.testing.assert_allclose(rpm, 160.0, rtol=1e-9)


def test_runout_modulates_the_groove_speed_once_per_turn():
    """An eccentric seat e: the arc rate under the stylus swings +-e / R at 2.67 Hz."""
    spec = cy.load()
    m = _quiet_motor(spec, "player_motor")
    m["runout_eccentric_m"] = 1e-4
    radius = spec["cylinder"]["diameter_m"] / 2
    mo = tr.simulate(m, 160.0, radius, 3.0, 8000.0, 3e-3, 1, "player")
    rel = mo.speed_m_s / np.mean(mo.speed_m_s) - 1
    assert 0.5 * (rel.max() - rel.min()) == pytest.approx(1e-4 / radius, rel=0.02)
    spectrum = np.abs(np.fft.rfft(rel))
    f = np.fft.rfftfreq(len(rel), 1 / 8000.0)
    assert f[np.argmax(spectrum)] == pytest.approx(160 / 60, abs=0.34)


def test_the_governor_regulates_a_load_step():
    """Half again the load at 2 s: the speed rings, settles within ~3 s, and stays within
    the governor's regulation (measured 0.075% low) instead of falling with the load. A
    well-damped governor (zeta 0.2): the configured worn one (0.15) rings longer."""
    spec = cy.load()
    m = _quiet_motor(spec, "player_motor")
    m["governor_zeta"] = 0.2
    radius = spec["cylinder"]["diameter_m"] / 2
    load = np.full(int(6 * 8000), 3e-3)
    load[2 * 8000 :] *= 1.5
    mo = tr.simulate(m, 160.0, radius, 6.0, 8000.0, load, 1, "player")
    rpm = mo.omega * 60 / (2 * np.pi)
    before, after = rpm[int(1.9 * 8000)], rpm[-1]
    assert after < before
    assert (before - after) / before < 0.01
    assert np.std(rpm[-4000:]) < 1e-3  # settled


def test_loud_passages_slow_the_recording_lathe():
    """The cutter's drag deepens with the cut: a loud burst slows the recorder's mandrel
    (so it plays back sharp)."""
    spec = cy.load()
    spec["recorder_motor"] = _quiet_motor(spec, "recorder_motor")
    fs = 48000.0
    t = np.arange(int(1.6 * fs)) / fs
    x = np.where((t > 0.6) & (t < 1.2), 1.0, 0.02) * np.sin(2 * np.pi * 400 * t)
    rec = cy.record(spec, x, fs, motion_seed=1)
    mo, lead = rec.motion, spec["numerics"]["lead_in_s"]
    quiet = mo.omega[int((lead + 0.4) * mo.fs_hz) : int((lead + 0.55) * mo.fs_hz)].mean()
    loud = mo.omega[int((lead + 1.0) * mo.fs_hz) : int((lead + 1.15) * mo.fs_hz)].mean()
    assert loud < quiet


def test_played_pitch_follows_the_runout():
    """A steady tone cut on a perfect lathe and played on an eccentric cylinder warbles
    +-e / R in frequency at 2.67 Hz (through the whole reproducer)."""
    from scipy.signal import hilbert

    spec = cy.load()
    spec["player_motor"] = _quiet_motor(spec, "player_motor")
    spec["player_motor"]["runout_eccentric_m"] = 1e-4
    fs = 48000.0
    t = np.arange(int(1.2 * fs)) / fs
    x = np.sin(2 * np.pi * 1000 * t) * np.minimum(1, t / 0.02)
    rec = cy.record(spec, x, fs, drive=0.3)
    pb = cy.play(spec, rec.groove, motion_seed=1)
    lead = rec.lead_in_samples
    p = pb.pressure_pa[lead + int(0.1 * pb.fs_hz) : -int(0.1 * pb.fs_hz)]
    phase = np.unwrap(np.angle(hilbert(p)))
    freq = np.diff(phase) * pb.fs_hz / (2 * np.pi)
    k = int(pb.fs_hz / 200)  # smooth the analytic signal's ripple
    freq = np.convolve(freq, np.ones(k) / k, mode="valid")
    rel = freq / np.median(freq) - 1
    radius = spec["cylinder"]["diameter_m"] / 2
    assert 0.5 * (np.percentile(rel, 99) - np.percentile(rel, 1)) == pytest.approx(
        1e-4 / radius, rel=0.15
    )


# The surface after the cut (damage.py).


def _flat_groove(length_m=0.5, ds=2.4e-6):
    return gv.Groove(h_m=np.full(int(length_m / ds), -20e-6), ds_m=ds)


def test_dust_only_raises_the_groove_and_is_seeded():
    spec = cy.load()
    d = dict(spec["damage"], dust_per_m=200.0)
    a, b = _flat_groove(), _flat_groove()
    n = dm.dust(a, d, 3)
    assert n == dm.dust(b, d, 3) > 0
    np.testing.assert_array_equal(a.h_m, b.h_m)
    assert np.all(a.h_m >= -20e-6)
    assert np.max(a.h_m) <= -20e-6 + (1 - d["dust_embed"]) * d["dust_max_m"] + 1e-12


def test_mould_only_pits():
    spec = cy.load()
    d = dict(spec["damage"], mould_colonies_per_m=10.0)
    g = _flat_groove()
    assert dm.mould(g, d, 1) > 0
    assert np.all(g.h_m <= -20e-6) and np.min(g.h_m) < -20e-6


def test_a_crack_comes_round_once_a_turn():
    spec = cy.load()
    d = dict(spec["damage"], cracks=1.0)
    circ = np.pi * spec["cylinder"]["diameter_m"]
    g = _flat_groove(length_m=3.2 * circ)
    dm.cracks(g, d, 1, circ)
    gaps = np.flatnonzero(np.diff((g.h_m < -40e-6).astype(int)) == 1) * g.ds_m
    assert len(gaps) >= 3
    np.testing.assert_allclose(np.diff(gaps), circ, rtol=1e-4)


def test_a_grain_clicks():
    """A large grain on a silent groove: a click at 1 m, the tip briefly thrown."""
    spec = cy.load()
    g = _flat_groove(length_m=0.12)
    s0 = 0.1
    i = int(s0 / g.ds_m)
    r = 15e-6
    u = (np.arange(i - 10, i + 11) - i) * g.ds_m
    g.h_m[i - 10 : i + 11] = np.maximum(
        g.h_m[i - 10 : i + 11], -20e-6 + np.sqrt(r * r - np.minimum(u * u, r * r))
    )
    pb = cy.play(spec, g)
    t_hit = s0 / cy.groove_speed(spec, 160.0)
    k = int(t_hit * pb.fs_hz)
    before = np.abs(pb.pressure_pa[k - 4000 : k - 400]).max()
    click = np.abs(pb.pressure_pa[k - 400 : k + 4000]).max()
    assert click > 100 * max(before, 1e-9)


# Wear (wear.py).


def test_wear_takes_its_flat_rate_off_a_plain_groove():
    spec = cy.load()
    g = _flat_groove(length_m=0.05)
    h0 = g.h_m.copy()
    wr.wear(g, spec, 3)
    mid = slice(len(g.h_m) // 4, 3 * len(g.h_m) // 4)
    np.testing.assert_allclose(h0[mid] - g.h_m[mid], 3 * wr.flat_wear_per_play(spec), rtol=0.03)


def test_wear_stays_bounded_over_many_plays():
    """Archard's wear is linear per pass: 60 plays of a loud tone take at most a few times
    the flat rate anywhere (no runaway like a plastic-dent rule's)."""
    spec = cy.load()
    v = cy.groove_speed(spec, 160.0)
    ds = v / spec["numerics"]["fs_hz"]
    s = np.arange(int(0.05 / ds)) * ds
    g = gv.Groove(h_m=-20e-6 + 8e-6 * np.sin(2 * np.pi * 1000 * s / v), ds_m=ds)
    h0 = g.h_m.copy()
    wr.wear(g, spec, 60)
    lost = (h0 - g.h_m)[2000:-2000]
    assert np.max(lost) < 5 * 60 * wr.flat_wear_per_play(spec)
    assert np.min(lost) >= 0.0
