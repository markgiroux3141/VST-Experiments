"""The Minimoog's oscillator 1 (config/circuits/minimoog_vco.yaml; docs/MINIMOOG_PLAN.md MM3) and
the op-amp macro's options it brought: a slew limit and an open-collector output (the LM393,
config/circuits/lm393_test.yaml)."""

from __future__ import annotations

import math
import sys

import numpy as np
import pytest

from varimu.circuit import builder, parts, spec
from varimu.circuit.ir import Device, Resistor, Vccs
from varimu.config import REPO_ROOT, ConfigError

sys.path.insert(0, str(REPO_ROOT / "scripts"))


def _els(name: str, prefix: str, overrides: dict | None = None) -> dict:
    s = spec.load_circuit(spec.circuit_path(name))
    ir = builder.build_ir(s, spec.resolve(s, overrides or {}), "linear")
    return {e.name: e for e in ir.elements() if e.name.upper().startswith(prefix)}


def test_slew_limit_expands_as_documented():
    els = _els("minimoog_vco", ("RIC7", "GIC7", "DIC7", "CIC7", "VIC7"))
    assert {"GIC7_s", "RIC7_s", "DIC7_sp", "DIC7_sn", "GIC7_1"} <= set(els)
    k = parts.OPAMP_SLEW_KNEE_V * 2 * math.pi * 3e6 / 20e6
    assert els["GIC7_s"].gm_s == pytest.approx(1e-3 * k)
    assert els["GIC7_1"].gm_s == pytest.approx(1e-3 / k)
    assert els["GIC7_1"].ctrl_pos == "ic7_s"
    # Small signal: the gain and the pole are the plain macro's.
    assert els["GIC7_s"].gm_s * els["RIC7_s"].r_ohm * els["GIC7_1"].gm_s == pytest.approx(1e-3)
    # Large signal: the integrator's current tops out at slew x C at the diodes' knee.
    i_max = els["GIC7_1"].gm_s * parts.OPAMP_SLEW_KNEE_V
    assert i_max / els["CIC7_1"].c_f == pytest.approx(20e6)


def test_open_collector_expands_as_documented():
    els = _els("lm393_test", ("GUC", "RUC", "QUC", "RQUC"))
    assert "RUC_o" not in els  # no output buffer
    g, rb, q = els["GUC_o"], els["RUC_b"], els["QUC_o"]
    assert isinstance(g, Vccs) and (g.ctrl_pos, g.ctrl_neg) == ("0", "uc_1")
    assert g.gm_s == pytest.approx(parts.OPAMP_OC_BASE_A / 1.0)
    assert isinstance(rb, Resistor) and {rb.a, rb.b} == {"uc_b", "0"}
    assert isinstance(q, Device) and q.model.startswith("2N3904")
    # The card's parasitics: the collector reaches `out` (through RC), the emitter V- (0 V here).
    outer = {n: n for n in ("out", "uc_b", "0")}
    for e in els.values():
        if isinstance(e, Resistor) and e.name.startswith("RQUC_O_"):
            outer[e.b] = e.a
    assert [outer.get(n, n) for n in q.nodes] == ["out", "uc_b", "0"]


@pytest.mark.parametrize(
    "change, message",
    [
        ({"open_collector": "QOC", "clamp": None}, "need a clamp"),
        ({"nodes": ["in", "0", "out", "0"], "open_collector": None}, "only for an open collector"),
        ({"nodes": ["in", "0", "out"]}, "needs the v_minus node"),
    ],
)
def test_open_collector_refusals(change, message, tmp_path):
    path = spec.circuit_path("lm393_test")
    text = path.read_text(encoding="utf-8")
    line = next(t for t in text.splitlines() if t.strip().startswith("UC:"))
    entry = line
    if "nodes" in change:
        entry = entry.replace('[in, "0", out, "0"]', "[" + ", ".join(
            f'"{n}"' for n in change["nodes"]) + "]")  # fmt: skip
    if change.get("open_collector", "x") is None:
        entry = entry.replace(", open_collector: QOC", "")
    if change.get("clamp", "x") is None:
        entry = entry.replace(
            " clamp: DCL, swing_v: cmp_swing_v, slew_v_per_s: cmp_slew_v_per_s,", ""
        )
    bad = tmp_path / "bad.yaml"
    bad.write_text(text.replace(line, entry), encoding="utf-8")
    s = spec.load_circuit(bad)
    with pytest.raises(ConfigError, match=message):
        builder.build_ir(s, spec.resolve(s, {}), "linear")


def test_the_comparator_meets_the_sheets_response_times():
    pytest.importorskip("circuitsim")
    import fit_lm393

    s = spec.load_circuit(fit_lm393.CIRCUIT)
    gbw, slew = (float(s.values[k]["value"]) for k in ("cmp_gbw_hz", "cmp_slew_v_per_s"))
    r = fit_lm393.responses(s, gbw, slew)
    for k, sheet in fit_lm393.SHEET.items():
        assert np.mean(r[k]) == pytest.approx(sheet, rel=0.01), k


def test_the_oscillator_is_trimmed_to_folkmans_points():
    pytest.importorskip("circuitsim")
    import minimoog_vco_trim as trim

    for note, rng in ((trim.LOW_A, trim.RANGE_2), (trim.HIGH_A, trim.RANGE_2)):
        f = trim.measure_hz({}, note, rng)
        assert abs(trim.cents(f, trim.target_hz(note, rng))) < 0.2, (note, rng, f)


# --- technique K: the reset and the rectangle's edge (varimu/devices/reset_events.py) ---------


def test_the_reset_events_fixture_is_current():
    from varimu.devices import reset_events as re_

    path = REPO_ROOT / "crates/circuitsim/tests/fixtures/events/reset_events.json"
    assert path.read_text("utf-8") == re_.fixtures_json(), (
        "stale: uv run python scripts/export_circuit_fixtures.py"
    )


def test_exceptions_stand_in_unless_literal():
    s = spec.load_circuit(spec.circuit_path("minimoog_vco"))
    p = spec.resolve(s, {})
    for kw in ({}, {"events": True}):
        names = {e.name for e in builder.build_ir(s, p, "linear", **kw).elements()}
        assert {"XRESET", "XRECT", "CQ4OFF"} <= names
        assert not names & {"JQ4", "DCR1", "C9", "R33", "GIC8A_1", "GIC8B_1"}
    ir = builder.build_ir(s, p, "linear", literal=True)
    names = {e.name for e in ir.elements()}
    assert {"JQ4", "DCR1", "GIC8A_1", "GIC8B_1"} <= names and "XRESET" not in names
    # the replaced parts' models leave the IR with them
    k = builder.build_ir(s, p, "linear")
    assert {m.name for m in k.models} == {"UA726_QX", "2N3904_QN", "1N4148_DCL", "2N3906_QREF"}


@pytest.mark.parametrize(
    "edit, message",
    [
        (("follows: XRESET", "follows: XNONE"), "follows XNONE"),
        (("    follow_gain: rect_follow_gain\n", ""), "follows and follow_gain together"),
        (("replaces: [IC8A]", "replaces: [IC9]"), "replaces: a list of the circuit's part names"),
    ],
)
def test_exception_refusals(edit, message, tmp_path):
    text = spec.circuit_path("minimoog_vco").read_text(encoding="utf-8")
    assert edit[0] in text
    bad = tmp_path / "bad.yaml"
    bad.write_text(text.replace(edit[0], edit[1], 1), encoding="utf-8")
    with pytest.raises((ConfigError, Exception), match=message):
        s = spec.load_circuit(bad)
        builder.build_ir(s, spec.resolve(s, {}), "linear")


def test_k_tracks_the_reference_live():
    """The events build at the draft's 96 kHz (the device's Newton) against the 12.288 MHz
    reference at the low A on 2': pitch within a cent, the rectangle's duty within one percent
    (reports/minimoog/vco/README.md)."""
    pytest.importorskip("circuitsim")
    import minimoog_vco_study as study
    import minimoog_vco_trim as trim

    from varimu.sim import fast

    note, rng = study.POINTS["A 2'"]
    st = study.settings("k-draft")
    ir = study.build(note, rng, ("ramp", "rect"), events=True)
    n = int(0.2 * st.sample_rate)
    r = fast.run_transient(
        ir, np.zeros(n), settings=st, controls={"key": np.full(n, trim.keyboard_volts(note))}
    )
    ramp = np.asarray(r.vectors["v(ramp)"])[int(0.02 * st.sample_rate) :]
    t = trim.falling_crossings(ramp, 2.5)
    f_k = (len(t) - 2) / (t[-1] - t[1]) * st.sample_rate
    f_ref = trim.measure_hz({}, note, rng)
    assert abs(trim.cents(f_k, f_ref)) < 1.0, (f_k, f_ref)
    rect = np.asarray(r.vectors["v(rect)"])[int(0.02 * st.sample_rate) :]
    assert abs(100 * (rect < -1.72).mean() - 52.0) < 1.0
