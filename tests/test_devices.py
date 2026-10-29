"""Device models: Python reference behaviour and fits to the published data."""

import numpy as np
import pytest
import yaml

from varimu.devices import library, versions
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


def test_6x4_matches_its_plate_curve_and_printed_drop():
    """The Child-law fit to the plate curve (GE ET-T865A p.4) also gives the drop the
    sheet prints in its text (p.2): 22 V at 70 mA DC per plate."""
    d = load_device("6X4")
    for pt in PUB["6X4"]["plate_curve_read_off_render"]:
        assert d.i(pt["va_v"]) == pytest.approx(pt["ia_a"], rel=0.10)
    drop = (0.070 / d.perveance) ** (2 / 3)
    assert drop == pytest.approx(PUB["6X4"]["tube_drop_v_at_70ma_dc_per_plate"], rel=0.05)


def test_12ay7_matches_both_sheets():
    """The Koren fit to RCA's curves (B9) at the point both sheets print (250 V, -4 V):
    current and gm as printed; mu and rp between or near RCA's (40, 22.8 k) and Tung-Sol's
    (44, 25 k), which disagree. Tung-Sol's curves, not fitted, agree within 0.2 mA rms."""
    t, a = load_device("12AY7"), PUB["12AY7"]["class_a1"]
    ts = PUB["12AY7"]["tungsol_class_a1"]
    vg, vp = a["vg_v"], a["vp_v"]
    assert t.ip(vg, vp) == pytest.approx(a["ip_a"], rel=0.05)
    assert t.gm(vg, vp) == pytest.approx(a["gm_s"], rel=0.10)
    assert a["mu"] - 2 < t.gm(vg, vp) * t.rp(vg, vp) < ts["mu"] + 2
    assert a["rp_ohm"] * 0.95 < t.rp(vg, vp) < ts["rp_ohm"] * 1.10
    _, tung = library.load_12ay7()
    err = t.ip(tung[:, 0], tung[:, 1]) - tung[:, 2]
    assert np.sqrt(np.mean(err**2)) < 0.2e-3


def test_6v6gt_matches_its_sheet():
    """The Koren pentode fit to GE's ET-T914 curves (B9): the printed class-A and push-pull
    idle points, and the plate curves above the knee within 2 mA rms. Known limits of
    Koren's form, recorded so a refit that changes them shows: the knee (Va < 60 V) is
    off by ~5 mA rms, and rp at the class-A point is about twice the printed 50 k."""
    p, pub = load_device("6V6GT"), PUB["6V6GT"]
    a = pub["class_a1"]
    vg1, vg2, va = a["vg1_v"], a["vg2_v"], a["vp_v"]
    assert p.ip(vg1, vg2, va) == pytest.approx(a["ip_a"], rel=0.05)
    gm = (p.ip(vg1 + 1e-3, vg2, va) - p.ip(vg1 - 1e-3, vg2, va)) / 2e-3
    assert gm == pytest.approx(a["gm_s"], rel=0.10)
    assert p.ig2(vg1, vg2) == pytest.approx(a["ig2_a"], rel=0.20)
    for q in pub["push_pull_ab1"]:  # idle current of each tube of the pair
        idle = p.ip(q["vg1_v"], q["vg2_v"], q["vp_v"])
        assert idle == pytest.approx(q["ip_zero_a"] / 2, rel=0.05)
    pl = library.load_6v6gt()["plate"]  # vg2, vg1, va, ia
    err = p.ip(pl[:, 1], pl[:, 0], pl[:, 2]) - pl[:, 3]
    above = pl[:, 2] >= 60
    assert np.sqrt(np.mean(err[above] ** 2)) < 2e-3
    rp = 2e-3 / (p.ip(vg1, vg2, va + 1e-3) - p.ip(vg1, vg2, va - 1e-3))
    assert 1.5 * a["rp_ohm"] < rp < 3 * a["rp_ohm"]


def test_5y3gt_matches_its_plate_curve_and_printed_drop():
    """The Child-law fit to GE's ET-T965 plate curve (B9) gives the drop printed on p.2:
    50 V at 125 mA DC per plate."""
    d = load_device("5Y3GT")
    v, i = library.load_csv("ge_5y3gt_plate.csv").T
    sel = v >= 10
    np.testing.assert_allclose(d.i(v[sel]), i[sel], rtol=0.06)
    drop = (0.125 / d.perveance) ** (2 / 3)
    assert drop == pytest.approx(PUB["5Y3GT"]["tube_drop_v_at_125ma_dc_per_plate"], rel=0.03)


def test_12au7_is_korens_table():
    t = load_device("12AU7")
    k = PUB["12AU7"]["koren"]
    assert (t.plate.mu, t.plate.ex, t.plate.kg1, t.plate.kp) == (
        k["mu"],
        k["ex"],
        k["kg1"],
        k["kp"],
    )
    assert t.ip(-8.5, 250.0) == pytest.approx(10e-3, rel=0.2)  # ~10 mA at the usual point


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
    for name in (
        "6386", "12AX7", "12BH7", "6973", "GZ34", "SI_RECTIFIER", "EL34T", "6084", "5651",
        "SELENIUM", "12AU7", "6X4", "12AY7", "6V6GT", "5Y3GT",
    ):  # fmt: skip
        dev = load_device(name)
        assert dev is not None
        d = yaml.safe_load(versions.read_text(name)[1])
        assert d["source"]
        for block in ("grid_current", "capacitances_f"):
            if block in d:
                assert d[block]["source"], f"{name}.{block} has no source"


def test_triode_subckt_names_are_spice_safe():
    t = Triode("6386 (GE)", KorenTriode(17, 1.4, 1000, 300, 300))
    assert t.subckt_name == "TRIODE_6386__GE_"
