"""The BJT (varimu.devices.bjt; CLAVINET_PLAN.md CL0, CHAINS_PLAN.md WP10): the Python
reference against ngspice's native Gummel-Poon `Q` (`.op` on a grid of bias points, NPN and
PNP), its Jacobian against finite differences, the components against their datasheet, the
`bjt` part in the builder, and the test circuit config/circuits/bjt_stage.yaml: its idle
point against a hand calculation and both engines, circuitsim's transient against ngspice's
and its DK solver against full MNA.

The compiled port's agreement with the reference is crates/circuitsim/tests/devices.rs
(fixtures from varimu.devices.fixtures); the Rust builder's is varimu-circuit's
tests/agreement.rs."""

import dataclasses
import itertools

import numpy as np
import pytest
from scipy.optimize import brentq, fsolve

from varimu.circuit import builder
from varimu.circuit.ir import Capacitor, Device, Resistor
from varimu.circuit.spec import load_circuit, resolve
from varimu.config import CONFIG_DIR, ConfigError
from varimu.devices.bjt import SPICE_GMIN, Bjt, depletion_c_f, parse_card
from varimu.devices.library import _published, load_device

STAGE = CONFIG_DIR / "circuits" / "bjt_stage.yaml"
TIGHT = "reltol=1e-12 abstol=1e-16 vntol=1e-13"
# wrdata's 10 significant digits; SPICE's cubic below -3 n Vt differs by < 0.1 IS.
ATOL, RTOL = 1e-13, 2e-8


def _ngspice():
    from varimu.sim import ngspice

    try:
        ngspice.find_ngspice()
    except ngspice.SimulatorNotFound:
        pytest.skip("ngspice not available")
    return ngspice


def _plain(q: Bjt) -> Bjt:
    """SPICE's defaults for the optional parameters: no Early effect, no high injection,
    no leakage terms (the model's other branch)."""
    return dataclasses.replace(
        q, name=q.name + "_plain", vaf_v=None, var_v=None, ikf_a=None, ikr_a=None,
        ise_a=0.0, isc_a=0.0,
    )  # fmt: skip


MODELS = {
    "BC550C": lambda: load_device("BC550C@1"),
    "BC560C": lambda: load_device("BC560C@1"),  # PNP
    "BC550C_plain": lambda: _plain(load_device("BC550C@1")),
}

# NPN-signed junction voltages: cut off, reverse active, active, saturated, both
# junctions at most 0.85 V forward.
_VBE = (-6.0, -1.0, -0.2, 0.0, 0.3, 0.55, 0.62, 0.68, 0.74, 0.8, 0.85)
_VCE = (-8.0, -0.3, 0.0, 0.05, 0.2, 1.0, 5.0, 25.0)


def _grid(q: Bjt) -> np.ndarray:
    pts = [(vce, vbe) for vbe, vce in itertools.product(_VBE, _VCE) if vbe - vce <= 0.85]
    return q.sign * np.array(pts, float)


@pytest.mark.parametrize("name", list(MODELS))
def test_reference_agrees_with_ngspice(name):
    """One `.op` with an instance per bias point (a DC sweep would linearize, CLAUDE.md);
    ngspice's GMIN across both junctions (and its substrate junction's) is added to the
    reference."""
    ngspice = _ngspice()
    q = MODELS[name]()
    pts = _grid(q)
    lines = [q.model_card()]
    for k, (vce, vbe) in enumerate(pts):
        lines += [
            f"vc{k} c{k} 0 dc {vce}",
            f"vb{k} b{k} 0 dc {vbe}",
            f"q{k} c{k} b{k} 0 {q.model_name}",
        ]
    vecs = [f"i(vc{k})" for k in range(len(pts))] + [f"i(vb{k})" for k in range(len(pts))]
    r = ngspice.run("\n".join(lines), "op", vecs, options=TIGHT)
    got_c = -np.array([float(r[f"i(vc{k})"][0]) for k in range(len(pts))])
    got_b = -np.array([float(r[f"i(vb{k})"][0]) for k in range(len(pts))])
    vce, vbe = pts.T
    ic, ib = q.currents(vce, vbe)
    vbc = vbe - vce
    ic = ic - SPICE_GMIN * vbc
    ib = ib + SPICE_GMIN * (vbe + vbc)
    # ngspice's substrate junction (ISS 0) carries only its GMIN, to ground (the substrate
    # node's default; the emitter here): from the collector of a vertical NPN, from the base
    # of a lateral PNP (SUBS's defaults).
    if q.polarity == "npn":
        ic = ic + SPICE_GMIN * vce
    else:
        ib = ib + SPICE_GMIN * vbe
    np.testing.assert_allclose(got_c, ic, rtol=RTOL, atol=ATOL, err_msg=f"{name} Ic")
    np.testing.assert_allclose(got_b, ib, rtol=RTOL, atol=ATOL, err_msg=f"{name} Ib")


@pytest.mark.parametrize("name", list(MODELS))
def test_jacobian_matches_finite_differences(name):
    q = MODELS[name]()
    for vce, vbe in _grid(q):
        jac = q.jacobian(vce, vbe)
        for j, (dce, dbe) in enumerate(((1e-7, 0.0), (0.0, 1e-7))):
            hi = q.currents(vce + dce, vbe + dbe)
            lo = q.currents(vce - dce, vbe - dbe)
            for i in range(2):
                fd = (hi[i] - lo[i]) / 2e-7
                assert float(jac[i][j]) == pytest.approx(float(fd), rel=1e-5, abs=1e-12), (
                    name, vce, vbe, i, j,
                )  # fmt: skip


def test_far_forward_junctions_stay_finite():
    """Past EXP_MAX (a junction ~2 V forward) the exponentials continue linearly."""
    q = load_device("BC550C@1")
    ic, ib = q.currents(5.0, 3.0)
    assert np.isfinite(ic) and np.isfinite(ib) and np.all(np.isfinite(q.jacobian(5.0, 3.0)))


def _at_terminals(q: Bjt, ic_a: float, vce_v: float) -> tuple[float, float]:
    """(hFE, VBE) at a collector current and V(c, e) at the transistor's terminals: the
    device behind its RB / RC / RE (the bjt part's resistances)."""

    def internal(vbe_i: float) -> tuple[float, float, float]:
        # V(c', e') follows from the terminal V(c, e) less the drops; iterate (tiny drops).
        vce_i = vce_v
        for _ in range(20):
            ic, ib = q.currents(vce_i, vbe_i)
            vce_i = vce_v - ic * q.rc_ohm - (ic + ib) * q.re_ohm
        return float(ic), float(ib), vce_i

    vbe_i = brentq(lambda v: internal(v)[0] - ic_a, 0.3, 0.9, xtol=1e-14)
    ic, ib, _ = internal(vbe_i)
    return ic / ib, vbe_i + ib * q.rb_ohm + (ic + ib) * q.re_ohm


@pytest.mark.parametrize("ref", ["BC550C@1", "BC413C@1"])
def test_datasheet_points(ref):
    """Philips' BC549; BC550 sheet (data/datasheets/published_points.yaml BC550C): hFE and
    VBE at 2 mA / 5 V, the collector and emitter capacitances (the card's depletion law at
    the sheet's biases; the part's linear values sit at the stated biases)."""
    d = _published()["BC550C"]
    q = load_device(ref)
    hfe, vbe = _at_terminals(q, 2e-3, 5.0)
    assert d["hfe_2ma_5v"]["min"] <= hfe <= d["hfe_2ma_5v"]["max"], hfe  # model: 487
    assert d["vbe_2ma_5v_v"]["min"] <= vbe <= d["vbe_2ma_5v_v"]["max"], vbe  # model: 0.639 V
    _, card = parse_card(_published()["BJT_CARDS"]["BC547C"])
    cc = depletion_c_f(card["CJC"], card["VJC"], card["MJC"], 10.0)
    ce = depletion_c_f(card["CJE"], card["VJE"], card["MJE"], 0.5)
    assert cc == pytest.approx(d["cc_10v_f"]["typ"], rel=0.05)  # 1.48 pF vs 1.5
    assert ce == pytest.approx(d["ce_0v5_f"]["typ"], rel=0.15)  # 9.9 pF vs 11
    assert q.cje_f == card["CJE"] and q.cjc_f == pytest.approx(
        depletion_c_f(card["CJC"], card["VJC"], card["MJC"], 5.0)
    )


def test_bc413c_is_the_bc550c_card():
    a, b = load_device("BC550C@1"), load_device("BC413C@1")
    assert dataclasses.replace(a, name="x") == dataclasses.replace(b, name="x")


# --- The bjt part ----------------------------------------------------------------------


def test_part_places_the_parasitics():
    c = builder.build(load_circuit(STAGE), cores="linear")
    q = c.ir.models[0]
    assert isinstance(q, Bjt) and q.name == "BC550C_Q1"
    els = {e.name: e for e in c.ir.elements()}
    assert els["Q1"] == Device("Q1", "BC550C_Q1", ("q1_c", "q1_b", "q1_e"))
    assert els["RQ1_b"] == Resistor("RQ1_b", "b", "q1_b", 1.0)
    assert els["RQ1_c"] == Resistor("RQ1_c", "c", "q1_c", 1.0)
    assert els["RQ1_e"] == Resistor("RQ1_e", "e", "q1_e", 0.2598)
    assert els["CQ1_je"] == Capacitor("CQ1_je", "q1_b", "q1_e", q.cje_f)
    assert els["CQ1_jc"] == Capacitor("CQ1_jc", "q1_b", "q1_c", q.cjc_f)
    assert ".model Q_BC550C_Q1 NPN(" in c.text and "\nQ1 q1_c q1_b q1_e Q_BC550C_Q1\n" in c.text


def _variant(tmp_path, old: str, new: str):
    text = STAGE.read_text(encoding="utf-8").replace(old, new)
    assert text != STAGE.read_text(encoding="utf-8")
    path = tmp_path / "v.yaml"
    path.write_text(text, encoding="utf-8")
    return load_circuit(path)


def test_area_scales_the_instance(tmp_path):
    s = _variant(
        tmp_path,
        "Q1: {device: BC550C@1}",
        'Q1: {device: BC550C@1, area: {value: 2.0, source: "test"}, parallel: 2}',
    )
    q = builder.build_ir(s, resolve(s)).models[0]
    base = load_device("BC550C@1")
    assert q.is_a == base.is_a * 4 and q.ikf_a == base.ikf_a * 4 and q.isc_a == base.isc_a * 4
    assert q.rb_ohm == base.rb_ohm / 4 and q.cjc_f == base.cjc_f * 4 and q.bf == base.bf


@pytest.mark.parametrize(
    "old,new,message",
    [
        ("Q1: {bjt: [c, b, e], model: Q1}", "Q1: {device: [c, b, e], model: Q1}", "`bjt` part"),
        ("Q1: {bjt: [c, b, e], model: Q1}", "T1: {bjt: [c, b, e], model: Q1}", "starts with Q"),
        ("Q1: {device: BC550C@1}", "Q1: {device: BC550C}", "names no version"),
    ],
)
def test_part_errors(tmp_path, old, new, message):
    s = _variant(tmp_path, old, new)
    with pytest.raises(ConfigError, match=message):
        builder.build_ir(s, resolve(s))


def test_stage_passes_the_preflight_checks():
    from varimu import preflight

    assert preflight.check_circuit(load_circuit(STAGE)) == []


# --- The stage on both engines ---------------------------------------------------------


def _hand_idle() -> dict[str, float]:
    """The stage's idle point by hand: the divider as its Thevenin source, KVL around the
    base loop and the collector, with the reference model at the internal nodes."""
    p = resolve(load_circuit(STAGE))
    q = load_device("BC550C@1")
    vcc, r1, r2 = p["supply_v"], p["r_bias_top_ohm"], p["r_bias_bottom_ohm"]
    vth, rth = vcc * r2 / (r1 + r2), r1 * r2 / (r1 + r2)
    rc, re = p["r_collector_ohm"], p["r_degen_ohm"] + p["r_emitter_ohm"]

    def kvl(x):
        vbe_i, vce_i = x
        ic, ib = q.currents(vce_i, vbe_i)
        ie = ic + ib
        return [
            vth - ib * (rth + q.rb_ohm) - vbe_i - ie * (q.re_ohm + re),
            vcc - ic * (rc + q.rc_ohm) - vce_i - ie * (q.re_ohm + re),
        ]

    vbe_i, vce_i = fsolve(kvl, [0.62, 4.0], xtol=1e-14)
    ic, ib = (float(x) for x in q.currents(vce_i, vbe_i))
    ie = ic + ib
    # The textbook estimate (VBE 0.65 V, beta from the sheet's typical 520).
    beta = _published()["BC550C"]["hfe_2ma_5v"]["typ"]
    ie_book = (vth - 0.65) / (re + rth / (beta + 1))
    return {
        "v(b)": vth - ib * rth,
        "v(e)": ie * re,
        "v(c)": vcc - ic * rc,
        "ic": ic,
        "ie_book": ie_book,
        "vc_book": vcc - beta / (beta + 1) * ie_book * rc,
    }


def test_stage_idles_at_the_hand_calculation():
    """Ic 1.020 mA: the base at 1.561 V, the emitter at 0.940 V, the collector at 4.207 V;
    ngspice's .op and circuitsim's DC point both within 1e-6 V of the hand calculation, which
    is within 5% of the textbook estimate."""
    pytest.importorskip("circuitsim", reason="needs `uv sync --extra fast`")
    from engine_compare import settings

    from varimu.sim import fast

    ngspice = _ngspice()
    want = _hand_idle()
    c = builder.build(load_circuit(STAGE), cores="linear")
    nodes = ("v(b)", "v(e)", "v(c)")
    r = ngspice.run(c.text + "vin in 0 dc 0\n", "op", list(nodes), options=TIGHT)
    rs = fast.run_transient(c.ir, np.zeros(16), settings=settings(2))
    for n in nodes:
        assert float(r[n][0]) == pytest.approx(want[n], abs=1e-6), n
        assert float(rs.vectors[n][0]) == pytest.approx(want[n], abs=1e-6), n
    assert want["ic"] == pytest.approx(1.0198e-3, rel=1e-3)
    assert want["ic"] == pytest.approx(want["ie_book"], rel=0.05)
    assert want["v(c)"] == pytest.approx(want["vc_book"], rel=0.05)


@pytest.mark.parametrize("amp,bound_db", [(0.02, -80.0), (0.3, -68.0)])
def test_stage_transient_agrees_with_ngspice(amp, bound_db):
    """Three tones (100 Hz, 1 kHz, 10 kHz) into the stage, small (the linear gain, ~31 dB)
    and hot (0.3 V: the collector swings into saturation and cutoff): circuitsim against
    ngspice, both trapezoidal at k = 8 (tests/engine_compare.py). Measured 2026-11-06:
    -85.1 dB small, -73.4 dB hot (the triode stage's bound is -60 dB)."""
    pytest.importorskip("circuitsim", reason="needs `uv sync --extra fast`")
    _ngspice()
    from engine_compare import compare, signal

    ir = builder.build(load_circuit(STAGE), cores="linear").ir
    err_db, dc = compare(ir, signal(amp=amp), 8)
    print(f"amp {amp}: worst {err_db:.1f} dB re swing, DC {dc:.1e}")
    assert err_db < bound_db and dc < 1e-6, (err_db, dc)


def test_stage_dk_matches_full_mna():
    """The DK solver against full MNA on the hot signal, in Newton tolerances."""
    pytest.importorskip("circuitsim", reason="needs `uv sync --extra fast`")
    from engine_compare import compare_solvers, signal

    ir = builder.build(load_circuit(STAGE), cores="linear").ir
    worst = compare_solvers(ir, signal(amp=0.3), 2, "trap")
    print(f"DK vs MNA: {worst:.2f} tolerances")
    assert worst < 1.0, worst


def test_stage_gain_at_production_matches_the_textbook():
    """Production's settings (esdirk4, error control, DK; the cold start through the
    junction limiting): 10 mV at 1 kHz comes out ~29.7 dB up, the textbook's
    Rin / (Rin + Rs) (Rc || RL) / (re + RE1 + RE' + |Z(CE || RE2)|) within 0.3 dB."""
    pytest.importorskip("circuitsim", reason="needs `uv sync --extra fast`")
    from varimu.sim import fast, io

    s = load_circuit(STAGE)
    p = resolve(s)
    ir = builder.build_ir(s, p)
    st = dataclasses.replace(
        io.TransientSettings.from_sim_settings(engine="circuitsim"), full_scale_volts_peak=1.0
    )
    fs = st.sample_rate
    t = np.arange(int(0.1 * fs)) / fs
    amp = 0.01
    x = amp * np.sin(2 * np.pi * 1000.0 * t) * np.clip(t / 0.01, 0, 1)
    o = fast.run_transient(ir, x, settings=st).vectors["v(o)"][int(0.05 * fs) :]
    got_db = 20 * np.log10(np.sqrt(np.mean(o**2)) / (amp / np.sqrt(2)))

    q, ic = load_device("BC550C@1"), _hand_idle()["ic"]
    hfe = _at_terminals(q, ic, 4.207 - 0.94)[0]
    re = q.nf * 0.025865 / ic + q.re_ohm  # kT/q at 27 C
    ze = abs(1 / (1 / p["r_emitter_ohm"] + 2j * np.pi * 1000.0 * p["c_emitter_f"]))
    r_emit = re + p["r_degen_ohm"] + ze
    rin = 1 / (1 / p["r_bias_top_ohm"] + 1 / p["r_bias_bottom_ohm"] + 1 / (hfe * r_emit))
    rl = 1 / (1 / p["r_collector_ohm"] + 1 / p["r_load_ohm"])
    want_db = 20 * np.log10(rin / (rin + p["r_source_ohm"]) * hfe / (hfe + 1) * rl / r_emit)
    print(f"production gain {got_db:.2f} dB, textbook {want_db:.2f} dB")
    assert got_db == pytest.approx(want_db, abs=0.3)
