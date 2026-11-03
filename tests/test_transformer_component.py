"""A transformer part from a component version (COMPONENT_EDITOR_PLAN.md C2 step 3), and
leakage couplings in the transformer macro (both builders: crates/varimu-circuit's agreement
test covers config/circuits/transformer_component_test.yaml)."""

from __future__ import annotations

import re

import numpy as np
import pytest

from varimu.circuit import builder, spec, spice
from varimu.circuit.ir import Capacitor, Coupling, Inductor, Resistor, Winding
from varimu.config import ConfigError
from varimu.devices.library import component_data

NAME = "transformer_component_test"
COMP = "component: t_model"
K_BAD = "{value: 1.0, source: test}"
K_OK = "{value: 0.5, source: test}"


def _with(extra: str) -> str:
    """The part's `component:` line followed by `extra` (one more key of the part)."""
    return f"{COMP}\n        {extra}"


def _text() -> str:
    return spec.circuit_path(NAME).read_text(encoding="utf-8")


def _build(text: str, tmp_path, cores: str = "ja"):
    p = tmp_path / "t.yaml"
    p.write_text(text, encoding="utf-8")
    c = spec.load_circuit(p)
    return builder.build(c, spec.resolve(c), cores=cores)


def _els(ir) -> dict:
    return {e.name: e for e in ir.elements()}


def test_the_component_fills_the_part(tmp_path):
    comp = component_data("BV191@1")["compiled"]
    els = _els(_build(_text(), tmp_path).ir)
    for w, v in comp["windings"].items():
        assert els[f"RT1_{w}"].r_ohm == v["r"]
        assert els[f"LT1_{w}_lk"].l_h == v["leak"]
        assert els[f"CT1_{w}"].c_f == v["c"]
        assert els[f"LT1_{w}"].turns == v["ratio"] * comp["turns"]
        assert els[f"LT1_{w}"].area_m2 == comp["core"]["area_m2"]
    ks = {e.name: e for e in els.values() if isinstance(e, Coupling)}
    assert len(ks) == len(comp["leak_couplings"]) == 3
    for d in comp["leak_couplings"]:
        a, b = d["between"]
        k = ks[f"KT1_{a}_{b}"]
        assert (k.l_a, k.l_b, k.k) == (f"LT1_{a}_lk", f"LT1_{b}_lk", d["k"])


def test_the_circuit_overrides_the_component(tmp_path):
    text = (
        _text()
        .replace(
            's: {nodes: [out, "0"]}',
            's: {nodes: [out, "0"], r: {value: 1000.0, source: test}}',
        )
        .replace(
            "component: t_model",
            "component: t_model\n        turns: {value: 500.0, source: test}",
        )
    )
    els = _els(_build(text, tmp_path).ir)
    assert els["RT1_s"].r_ohm == 1000.0
    assert els["LT1_p1"].turns == 500.0 and els["LT1_s"].turns == 20.0 * 500.0
    comp = component_data("BV191@1")["compiled"]
    assert els["RT1_p1"].r_ohm == comp["windings"]["p1"]["r"]


@pytest.mark.parametrize(
    ("old", "new", "msg"),
    [
        ("value: BV191@1", "value: BV191", "names no version"),
        ("value: BV191@1", "value: 12AX7@1", "not a compiled transformer"),
        ('          s: {nodes: [out, "0"]}\n', "", "the component's windings are"),
        (
            COMP,
            _with("leakage_h: {value: 1.0e-3, source: test}"),
            "a component gives every winding its leak",
        ),
        (COMP, _with(f"leak_couplings: [{{between: [p1, s], k: {K_BAD}}}]"), "between -1 and 1"),
        (
            COMP,
            _with(f"leak_couplings: [{{between: [p1, q], k: {K_OK}}}]"),
            "between two of the windings",
        ),
    ],
)
def test_refusals(tmp_path, old, new, msg):
    with pytest.raises(ConfigError, match=msg):
        _build(_text().replace(old, new), tmp_path)


def test_couplings_without_a_component(tmp_path):
    def v(x: str) -> str:
        return f"{{value: {x}, source: t}}"

    core = (
        f"{{material: mumetall, area_m2: {v('2.0e-4')}, path_m: {v('0.1')}, gap_m: {v('1.0e-6')}}}"
    )
    text = _text().replace(
        f"        {COMP}\n",
        f"        core: {core}\n"
        f"        turns: {v('400.0')}\n"
        f"        leak_couplings: [{{between: [p1, s], k: {v('0.5')}}}]\n",
    )
    for w, lk, ratio in (("p1", "1.0e-3", "1.0"), ("p2", "1.0e-3", "1.0"), ("s", "0.4", "20.0")):
        text = text.replace(f"{w}: {{nodes: [", f"{w}: {{leak: {v(lk)}, ratio: {ratio}, nodes: [")
    els = _els(_build(text, tmp_path).ir)
    assert els["KT1_p1_s"].k == 0.5
    # A winding without a leakage inductor can't be coupled.
    bad = text.replace(f"p1: {{leak: {v('1.0e-3')}", f"p1: {{leak: {v('0.0')}")
    with pytest.raises(ConfigError, match="has no leakage inductor"):
        _build(bad, tmp_path)


def _spice_matrix(text: str) -> tuple[list[str], np.ndarray]:
    """The windings' inductance matrix from the emitted SPICE (the eddy turn left out)."""
    ls = dict(re.findall(r"^(LT1_\w+) \S+ \S+ (\S+)$", text, re.M))
    names = sorted(ls)
    m = np.diag([float(ls[n]) for n in names])
    for a, b, k in re.findall(r"^K\S+ (LT1_\w+) (LT1_\w+) (\S+)$", text, re.M):
        i, j = names.index(a), names.index(b)
        m[i, j] = m[j, i] = float(k) * np.sqrt(m[i, i] * m[j, j])
    return names, m


def test_spice_folds_the_couplings_into_the_windings(tmp_path):
    """The folded matrix's short circuits are the compiler's leakage (its report), up to
    the magnetizing inductance's finite share."""
    c = _build(_text(), tmp_path, cores="linear")
    names, m = _spice_matrix(c.text)
    report = component_data("BV191@1")["report"]["short_circuit_h"]
    i = {n: names.index(f"LT1_{n}") for n in ("p1", "p2", "s")}

    def shorted(j: str, k: str) -> float:  # j driven, k shorted, the rest open
        a, b = i[j], i[k]
        return m[a, a] - m[a, b] ** 2 / m[b, b]

    for j, k in (("p1", "s"), ("p2", "s"), ("p1", "p2"), ("s", "p1")):
        want = report[f"{j} ({k} shorted)"]
        assert shorted(j, k) == pytest.approx(want, rel=2e-3), (j, k)
    # Without the couplings the shorted pairs move by far more: they matter.
    plain = spice.emit(
        type(c.ir)(
            **{
                **c.ir.__dict__,
                "sections": tuple(
                    type(s)(s.title, tuple(e for e in s.elements if not isinstance(e, Coupling)))
                    for s in c.ir.sections
                ),
            }
        ),
        rshunt_ohm=None,
    )[0]
    names2, m2 = _spice_matrix(plain)
    a, b = names2.index("LT1_p1"), names2.index("LT1_s")
    off = m2[a, a] - m2[a, b] ** 2 / m2[b, b]
    assert abs(off / report["p1 (s shorted)"] - 1) > 0.2


def test_engines_agree_on_coupled_leakage(tmp_path):
    """circuitsim (the IR's couplings) against ngspice's AC analysis (folded), the
    secondary loaded hard so the leakage sets the response."""
    from varimu.sim import fast, ngspice
    from varimu.sim.io import TransientSettings

    try:
        ngspice.find_ngspice()
        fast.check_build()
    except (ngspice.SimulatorNotFound, fast.EngineUnavailable) as err:
        pytest.skip(str(err))
    text = _text().replace("value: 1.0e+6, source", "value: 20.0e+3, source")
    c = _build(text, tmp_path, cores="linear")
    f = np.array([1000.0, 15000.0])
    ng = ngspice.run(
        spice.emit(c.ir, rshunt_ohm=None)[0] + "Vin in 0 dc 0 ac 1\n",
        "ac dec 20 100 20000",
        ["v(out)"],
        digits=16,
    )
    fr = ng["scale"].real
    want = np.interp(f, fr, ng["v(out)"].real) + 1j * np.interp(f, fr, ng["v(out)"].imag)
    st = TransientSettings.from_sim_settings(engine="circuitsim")
    sr = st.sample_rate
    for fi, wi in zip(f, want, strict=True):
        t = np.arange(int(0.1 * sr)) / sr
        x = 0.01 * np.sin(2 * np.pi * fi * t) * np.minimum(1.0, t / 0.02)
        y = fast.run_transient(c.ir, x, settings=st).vectors["v(out)"]
        m = slice(len(t) // 2, len(t))
        ref = np.exp(-2j * np.pi * fi * t[m])
        got = np.mean(y[m] * ref) / np.mean(x[m] * ref)
        assert abs(got / wi - 1) < 5e-3, (fi, got, wi)


def test_element_kinds():
    c = spec.load_circuit(spec.circuit_path(NAME))
    ir = builder.build_ir(c, spec.resolve(c))
    kinds = {type(e) for e in ir.elements()}
    assert {Resistor, Inductor, Winding, Capacitor, Coupling} <= kinds


def test_component_capacitors_and_shields(tmp_path):
    """A version with facing capacitances (compiler 0.2) places them between the windings'
    ends; a shield needs its node."""
    text = _text().replace("value: BV191@1", "value: BV191@3")
    with pytest.raises(ConfigError, match=r"shields: \{S: node\}"):
        _build(text, tmp_path)
    els = _els(_build(text.replace(COMP, _with('shields: {S: "0"}')), tmp_path).ir)
    caps = component_data("BV191@3")["compiled"]["capacitors"]
    on_ground = {"p2.other", "s.other", "shield.S"}  # all on node 0 in this circuit
    for d in caps:
        a, b = (t.replace(".", "_") for t in d["between"])
        if set(d["between"]) <= on_ground:
            assert f"CT1_{a}_{b}" not in els  # both ends on one node: left out
            continue
        assert els[f"CT1_{a}_{b}"].c_f == d["c"]
    assert els["CT1_p1_dot_shield_S"].b == "0"
    with pytest.raises(ConfigError, match="has no shield X"):
        _build(text.replace(COMP, _with('shields: {S: "0", X: "0"}')), tmp_path)


def test_the_5e3_pins_its_output_transformer():
    c = spec.load_circuit(spec.circuit_path("fender_5e3"))
    els = _els(builder.build_ir(c, spec.resolve(c)))
    comp = component_data("OT_5E3@2")["compiled"]
    assert els["RT1_pb"].r_ohm == comp["windings"]["pb"]["r"]
    assert {"KT1_pa_pb", "KT1_pa_s", "KT1_pb_s"} <= set(els)
    # The centre tap joins pa's end and pb's start: that facing pair is left out.
    assert "CT1_pa_other_pb_dot" not in els
    assert els["CT1_pb_other_s_dot"].a == "p6b" and els["CT1_pb_other_s_dot"].b == "spk"
