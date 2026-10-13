"""Device models: Python reference behaviour and fits to the published data."""

import numpy as np
import pytest
import yaml

from varimu.devices.diode import VT_TNOM, JunctionDiode, VacuumDiode
from varimu.devices.fit import DATASHEETS, cascode_gm, evaluate_6386, load_6386
from varimu.devices.library import load_device
from varimu.devices.pentode import Pentode
from varimu.devices.triode import KorenTriode, Triode, VariMuTriode

PUB = yaml.safe_load((DATASHEETS / "published_points.yaml").read_text(encoding="utf-8"))


# --- Model mechanics -------------------------------------------------------------


def test_koren_12ax7_typical_point():
    # Koren's 12AX7 parameters: roughly 1.2 mA at Vp = 250 V, Vg = -2 V (the usual datasheet point).
    t = KorenTriode(100, 1.4, 1060, 600, 300)
    assert t.ip(-2.0, 250.0) == pytest.approx(1.2e-3, rel=0.3)
    assert t.ip(-2.0, 0.0) == 0.0
    assert t.ip(-10.0, 250.0) < 1e-6  # cut off


def test_varimu_is_weighted_sum_of_sections():
    m = VariMuTriode((30.0, 10.0, 3.0), (0.7, 0.2, 0.1), 1.5, 1000.0, 300.0, 300.0)
    vg, vp = np.linspace(-40, 0, 9), 200.0
    expected = sum(
        w * KorenTriode(mu, 1.5, 1000.0, 300.0, 300.0).ip(vg, vp)
        for mu, w in zip(m.mus, m.weights, strict=True)
    )
    np.testing.assert_allclose(m.ip(vg, vp), expected, rtol=1e-12)
    with pytest.raises(ValueError):
        VariMuTriode((30.0, 3.0), (0.5, 0.6), 1.5, 1000.0, 300.0, 300.0)


def test_junction_diode_lambert_w_solves_series_resistance():
    d = JunctionDiode("d", 7e-9, 1.8, 0.5)
    v = np.linspace(-1, 1.2, 50)
    i = d.i(v)
    # V = I*Rs + n*Vt*ln(1 + I/Is)
    np.testing.assert_allclose(i * d.rs_ohm + d.n * VT_TNOM * np.log1p(i / d.is_a), v, atol=1e-9)


def test_vacuum_diode_child_law():
    d = VacuumDiode("d", 4e-3)
    assert d.i(25.0) == pytest.approx(4e-3 * 25.0**1.5, rel=1e-6)
    assert d.i(-5.0) < 1e-9


# --- Fitted / spec-derived devices reproduce their sources ----------------------


def test_12bh7_reproduces_published_point():
    t, a = load_device("12BH7"), PUB["12BH7"]["class_a1"]
    assert t.ip(a["vg_v"], a["vp_v"]) == pytest.approx(a["ip_a"], rel=1e-4)
    assert t.gm(a["vg_v"], a["vp_v"]) == pytest.approx(a["gm_s"], rel=1e-4)
    assert t.rp(a["vg_v"], a["vp_v"]) == pytest.approx(a["rp_ohm"], rel=1e-4)


def test_6973_reproduces_published_points():
    p, pub = load_device("6973"), PUB["6973"]
    assert isinstance(p, Pentode)
    a, c = pub["class_a1"], pub["cutoff"]
    assert p.ip(a["vg1_v"], a["vg2_v"], a["vp_v"]) == pytest.approx(a["ip_a"], rel=1e-4)
    assert p.ig2(a["vg1_v"], a["vg2_v"]) == pytest.approx(a["ig2_a"], rel=1e-4)
    assert p.ip(c["vg1_v"], c["vg2_v"], c["vp_v"]) == pytest.approx(c["ip_a"], rel=1e-4)


def test_gz34_matches_anode_curve_points():
    d = load_device("GZ34")
    for pt in PUB["GZ34"]["anode_curve_read_by_eye"]:
        assert d.i(pt["va_v"]) == pytest.approx(pt["ia_a"], rel=0.08)


# --- 6386: the done-when criterion for Phase 1 --------------------------------------
#
# Acceptance thresholds (documented error). The data are "average" curves,
# digitized to about 0.05 mA / 0.4 V (see ge_6386.provenance.yaml). The thresholds
# allow for that plus the limits of a compact model.

PLATE_RMS_MA = 0.6
TRANSFER_RMS_MA = 0.6
GM_RMS_LOG_PCT = 15.0


@pytest.fixture(scope="module")
def t6386():
    return load_device("6386")


@pytest.fixture(scope="module")
def report(t6386):
    return evaluate_6386(t6386.plate, load_6386())


def test_6386_plate_and_transfer_curves(report):
    assert report.plate_rms_ma < PLATE_RMS_MA
    assert report.transfer_rms_ma < TRANSFER_RMS_MA


def test_6386_gm_vs_bias_matches_cascode_figure(report):
    assert report.gm_rms_log_pct < GM_RMS_LOG_PCT


def test_6386_published_operating_points(t6386, report):
    a = PUB["6386"]["class_a1"]
    assert report.class_a["ip_a"] == pytest.approx(a["ip_a"], rel=0.05)
    assert report.class_a["gm_s"] == pytest.approx(a["gm_s"], rel=0.10)
    assert report.class_a["rp_ohm"] == pytest.approx(a["rp_ohm"], rel=0.10)
    assert report.class_a["mu"] == pytest.approx(a["mu"], rel=0.10)
    # "Grid voltage, approximate, for gm = 100 umho" at Vp = 100 V: -16 V
    assert report.gm_100umho_vg == pytest.approx(-16.0, abs=2.5)


def test_6386_is_remote_cutoff(t6386):
    """The compression law: gm falls smoothly over tens of volts instead of cutting off."""
    vg = np.linspace(-40, -2, 39)
    gm = t6386.gm(vg, 200.0)
    assert np.all(np.diff(gm) > 0)  # monotonic
    assert gm[0] > 1e-6  # still conducting at -40 V
    assert gm[-1] / gm[0] > 30  # but a gm range of more than 30x (~30 dB)
    # No staircase from discrete sections: in the tail below the knee, where the
    # sheet's log-gm curves are nearly straight, d(ln gm)/dVg must vary smoothly.
    # The knee moves out with plate voltage (about -Vp/mu of the fine-pitch
    # sections), so the window ends at -Vp/20 - 3 V. With 16 sections this
    # measured ~0.1; with 32 sections it's <= 0.06.
    for vp in (150, 200, 250):
        vg = np.arange(-40, -vp / 20 - 3 + 1e-9, 1.0)
        gm = t6386.gm(vg, vp)
        lg = np.log(gm[gm > 2e-6])
        assert np.max(np.abs(np.diff(lg, 2))) < 0.08, f"gm ripple at Vp={vp}"


def test_cascode_solver_matches_bruteforce(t6386):
    from scipy.optimize import brentq

    ip = t6386.plate.ip
    vg1, ecc2 = -12.0, 250.0
    x = brentq(lambda x: ip(vg1, x) - ip(ecc2 / 2 - x, 250 - x), 0, 250, xtol=1e-12)
    d = 0.01
    xp = brentq(lambda x: ip(vg1 + d, x) - ip(ecc2 / 2 - x, 250 - x), 0, 250, xtol=1e-12)
    xm = brentq(lambda x: ip(vg1 - d, x) - ip(ecc2 / 2 - x, 250 - x), 0, 250, xtol=1e-12)
    brute = (ip(vg1 + d, xp) - ip(vg1 - d, xm)) / (2 * d)
    assert cascode_gm(ip, vg1, ecc2) == pytest.approx(brute, rel=1e-6)
    assert 0 < x < 250


def test_all_device_files_have_sources():
    for name in ("6386", "12AX7", "12BH7", "6973", "GZ34", "SI_RECTIFIER"):
        dev = load_device(name)
        assert dev is not None
        d = yaml.safe_load(
            (DATASHEETS.parents[1] / "config" / "devices" / f"{name.lower()}.yaml").read_text(
                encoding="utf-8"
            )
        )
        assert d["source"]
        for block in ("grid_current", "capacitances_f"):
            if block in d:
                assert d[block]["source"], f"{name}.{block} has no source"


def test_triode_subckt_names_are_spice_safe():
    t = Triode("6386 (GE)", KorenTriode(17, 1.4, 1000, 300, 300))
    assert t.subckt_name == "TRIODE_6386__GE_"
