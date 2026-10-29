"""The physical speaker (component editor C3): the voltage-controlled current source the
readout needs, the P12R against its sheet, and the pressure the engines compute.

- The Vccs element: JSON round trip, its checks, its SPICE line.
- P12R@1 against the Jensen sheet (data/datasheets/jensen_p12r.provenance.yaml): the
  impedance's Re, Fs and Qts read off the model's curve the way they are measured, its
  shape against the sheet's trace, and the on-axis response on the IEC baffle within the
  stated tolerance over the band the sheet prints.
- The readout loads nothing (the impedance is the driver's alone), and circuitsim's
  transient and ngspice's AC analysis compute the same pressure as the AC model the fit
  used (varimu.circuit.ac).
"""

import math

import numpy as np
import pytest

from varimu.circuit import ac, builder, parts, spec
from varimu.circuit.ir import (
    GROUND,
    CircuitIR,
    IRError,
    Resistor,
    Section,
    Vccs,
    VoltageProbe,
)
from varimu.config import ConfigError
from varimu.devices import speaker as spk
from varimu.devices import speaker_fit
from varimu.devices.fit import DATASHEETS
from varimu.devices.library import load_device, load_speaker

# The stated tolerances (COMPONENT_EDITOR_PLAN.md C3's done-when).
FS_HZ_TOL = 1.0
QTS_REL_TOL = 0.02
IMPEDANCE_SHAPE_DB_RMS = 1.5  # of |Z|
RESPONSE_DB_RMS, RESPONSE_DB_MAX = 2.0, 4.0  # on the band the sheet prints
DELUXE = spk.Cabinet(0.504825, 0.41275, 0.2413)


@pytest.fixture(scope="module")
def p12r():
    return load_speaker("P12R@1")


def _tiny(gm=1e-3, extra=()):
    els = (
        Resistor("R1", "in", GROUND, 1e3),
        Vccs("G1", GROUND, "out", "in", GROUND, gm),
        Resistor("R2", "out", GROUND, 1e3),
        *extra,
    )
    return CircuitIR("vccs", "in", (VoltageProbe("out"),), (), (Section("s", els),))


def test_vccs_round_trips_and_is_checked():
    ir = _tiny()
    assert CircuitIR.from_json(ir.to_json()) == ir
    assert '"kind": "vccs"' in ir.to_json()
    with pytest.raises(IRError, match="finite and nonzero"):
        _tiny(gm=0.0)
    with pytest.raises(IRError, match="both ends on node in"):
        _tiny(extra=(Vccs("G2", GROUND, "out", "in", "in", 1.0),))
    with pytest.raises(IRError, match="node lone has no other element"):
        _tiny(extra=(Vccs("G2", GROUND, "out", "lone", GROUND, 1.0),))
    els = (Resistor("R1", "in", GROUND, 1.0), Vccs("X1", GROUND, "in", "in", GROUND, 1.0))
    with pytest.raises(IRError, match="must start with G"):
        CircuitIR("x", "in", (), (), (Section("s", els),))


def test_vccs_spice_line():
    from varimu.circuit.spice import element_line

    assert element_line(Vccs("GA", "0", "p", "c", "0", 2.5e-3), {}) == "GA 0 p c 0 0.0025"


def test_vccs_sign():
    """gm v(ctrl) flows from pos through the source to neg (SPICE G): from ground into
    `out`, out = gm R v(in)."""
    v = ac.solve(_tiny().elements(), [100.0], ("in", GROUND), ["in", "out"])
    assert (v["out"] / v["in"])[0] == pytest.approx(1.0)


def test_p12r_impedance_matches_the_sheet(p12r):
    fig = speaker_fit.impedance_figures(p12r)
    assert fig["re_ohm"] == pytest.approx(6.05, abs=1e-6)
    assert abs(fig["fs_hz"] - 80.0) <= FS_HZ_TOL
    assert fig["qts"] == pytest.approx(2.1, rel=QTS_REL_TOL)
    assert fig["zmax_ohm"] == pytest.approx(6.05 * (1 + 13.07 / 2.50), rel=0.02)


def _fit_meta():
    import yaml

    from varimu.devices import versions

    return yaml.safe_load(versions.read_text("P12R@1")[1])["fit_report"]


def test_p12r_impedance_shape(p12r):
    """The sheet's trace is kz 20 log10 |Z| + z0 (no ohm axis): the model's |Z| within
    IMPEDANCE_SHAPE_DB_RMS dB rms of it, with the fit's kz and z0."""
    c = speaker_fit.load_curves(DATASHEETS, "jensen_p12r")
    ax = _fit_meta()["impedance_axis"]
    model = 20 * np.log10(np.abs(speaker_fit.impedance(p12r, c.impedance_hz)))
    sheet = (c.impedance_trace - ax["z0"]) / ax["kz"]
    assert np.sqrt(np.mean((model - sheet) ** 2)) < IMPEDANCE_SHAPE_DB_RMS
    assert 1.0 < ax["kz"] < 1.6


def test_p12r_response_on_the_iec_baffle(p12r):
    """On-axis, 1 m, 2.83 V, on the IEC baffle (the sheet's setup), against the printed
    curve (to the page's edge, 8.5 kHz); the fit's level offset is the sheet's level
    against the model's physics (reported, small)."""
    c = speaker_fit.load_curves(DATASHEETS, "jensen_p12r")
    meta = _fit_meta()
    p, _ = speaker_fit.response(p12r, spk.IEC_BAFFLE, 1.0, c.response_hz)
    err = speaker_fit.spl_db(p) + meta["level_offset_db"] - c.response_db
    vis = c.response_hz <= speaker_fit.VISIBLE_MAX_HZ
    assert np.sqrt(np.mean(err[vis] ** 2)) < RESPONSE_DB_RMS
    assert np.max(np.abs(err[vis])) < RESPONSE_DB_MAX
    assert abs(meta["level_offset_db"]) < 3.0


def test_edge_taps():
    taps = spk.edge_taps(DELUXE, 1.0)
    # A centred driver: opposite edges alike; the angular shares add up to one.
    assert taps[0] == taps[2] and taps[1][0] == taps[3][0]
    assert taps[1][1] == pytest.approx(taps[3][1], rel=1e-12)
    shares = []
    for (tap, w), d in zip(taps, (DELUXE.height_m / 2, DELUXE.width_m / 2) * 2, strict=True):
        depth = DELUXE.depth_m
        path = math.sqrt(depth**2 + d**2) + depth + math.sqrt(1 + d**2) - 1
        assert tap == round(path / (spk.C_AIR_M_S * spk.LADDER_SECTION_S))
        shares.append(w * (1 + path))
    assert sum(shares) == pytest.approx(1.0)
    # The IEC baffle's offset driver: the nearer edges come sooner.
    iec = spk.edge_taps(spk.IEC_BAFFLE, 1.0)
    assert iec[3][0] < iec[1][0] and iec[0][0] < iec[2][0]


def test_the_readout_loads_nothing(p12r):
    f = np.geomspace(20, 20000, 50)
    drv, rad = parts.speaker_driver("S", "plus", GROUND, p12r)
    full = drv + parts.speaker_readout("S", GROUND, "out", p12r, rad, DELUXE, 1.0)
    z_drv = ac.solve(drv, f, ("plus", GROUND), ["plus"])["plus"]
    z_full = ac.solve(full, f, ("plus", GROUND), ["plus"])["plus"]
    np.testing.assert_allclose(z_full, z_drv, rtol=1e-12)


def _speaker_ir(s):
    els = parts.speaker("SPK", "in", GROUND, "out", s, DELUXE, 1.0)
    return CircuitIR("speaker", "in", (VoltageProbe("out"),), (), (Section("speaker", tuple(els)),))


def test_circuitsim_computes_the_ac_models_pressure(p12r):
    pytest.importorskip("circuitsim", reason="needs `uv sync --extra fast`")
    import dataclasses

    from varimu.sim import fast
    from varimu.sim.io import TransientSettings

    st = dataclasses.replace(TransientSettings.from_sim_settings(engine="circuitsim"), settle_s=0.0)
    fs = st.sample_rate
    ir = _speaker_ir(p12r)
    for f in (60.0, 1000.0, 2500.0, 8000.0):
        t = np.arange(int(0.3 * fs)) / fs
        x = np.sin(2 * np.pi * f * t) * np.minimum(1.0, t / 0.02)
        y = fast.run_transient(ir, x, settings=st).vectors["v(out)"]
        m = slice(len(t) // 2, len(t))
        ref = np.exp(-2j * np.pi * f * t[m])
        got = np.mean(y[m] * ref) / np.mean(x[m] * ref)
        want = speaker_fit.response(p12r, DELUXE, 1.0, np.array([f]))[0][0]
        assert abs(got / want - 1) < 5e-3, f  # production's error control, -46 dB


def test_ngspice_computes_the_ac_models_pressure(p12r):
    from varimu.circuit import spice
    from varimu.sim import ngspice

    try:
        ngspice.find_ngspice()
    except ngspice.SimulatorNotFound:
        pytest.skip("ngspice not available")
    text, _ = spice.emit(_speaker_ir(p12r), triode_formulation="exact", rshunt_ohm=None)
    f = np.geomspace(30.0, 15000.0, 7)
    ng = ngspice.run(text + "Vin in 0 dc 0 ac 1\n", "ac dec 1 30 15000", ["v(out)"], digits=16)
    got = np.interp(f, ng["scale"].real, ng["v(out)"].real) + 1j * np.interp(
        f, ng["scale"].real, ng["v(out)"].imag
    )
    fr = ng["scale"].real
    want = speaker_fit.response(p12r, DELUXE, 1.0, fr)[0]
    np.testing.assert_allclose(ng["v(out)"], want, rtol=1e-6)
    assert len(got) == 7


def test_speaker_part_needs_a_pinned_speaker(tmp_path):
    d = spec.circuit_path("fender_5e3").read_text(encoding="utf-8")
    for ref, msg in (("P12R", "names no version"), ("12AX7@1", "not a speaker")):
        p = tmp_path / "x.yaml"
        p.write_text(d.replace("value: P12R@1", f"value: {ref}"), encoding="utf-8")
        with pytest.raises(ConfigError, match=msg):
            builder.build_ir(spec.load_circuit(p), spec.resolve(spec.load_circuit(p)))
    with pytest.raises(ValueError, match="is a speaker, not a device model"):
        load_device("P12R@1")


def test_full_scale_in_pascals(tmp_path):
    base = (
        "title: t\ninput: in\nprobes: [out]\nfull_scale:\n"
        "  input_volts_peak: {value: 1.0, source: x}\n"
    )
    ok = tmp_path / "ok.yaml"
    ok.write_text(base + "  output_pascals_peak: {value: 30.0, source: x}\nsections: []\n")
    s = spec.load_circuit(ok)
    assert s.full_scale == (1.0, 30.0) and s.full_scale_unit == "Pa"
    both = tmp_path / "both.yaml"
    both.write_text(
        base
        + "  output_pascals_peak: {value: 30.0, source: x}\n"
        + "  output_volts_peak: {value: 30.0, source: x}\nsections: []\n"
    )
    with pytest.raises(ConfigError, match="one of"):
        spec.load_circuit(both)
