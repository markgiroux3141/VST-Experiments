"""The tube microphones' real supplies (CHAINS_PLAN.md NH3): a SUPPLY switch per microphone, ideal
by default (the circuit as before: no supply part, no rectifier model in the IR), 1 the supply from
the mains, which passes the pre-flight checks and runs where its trim put it from the start of a
render (scripts/mic_supply_trim.py's start voltages)."""

from __future__ import annotations

import numpy as np
import pytest

from varimu import preflight
from varimu.circuit import builder, spec
from varimu.config import CONFIG_DIR, ConfigError

# name -> (the rail's node, its target in V, the rectifier's component)
MICS = {
    "akg_c12": ("bplus", 120.0, "E125C5"),
    "neumann_u47": ("b105", 105.0, "B250C75"),
    "neumann_u67": ("bplus", 210.0, "E125C20"),
    "neumann_m49": ("bplus", 116.0, "E125C20"),
    "telefunken_ela_m251": ("bplus", 120.0, "E125C5"),
}


def _load(name):
    return spec.load_circuit(CONFIG_DIR / "circuits" / f"{name}.yaml")


@pytest.mark.parametrize("name", MICS)
def test_the_default_supply_is_the_ideal_one(name):
    ir = builder.build(_load(name)).ir
    names = {e.name for e in ir.elements()}
    assert "VT" not in names and not any(n.startswith("D") and "G" in n for n in names)
    assert MICS[name][2] not in {m.name for m in ir.models}  # its devices entry: emit: used


@pytest.mark.parametrize("name", MICS)
def test_the_real_supply_builds_and_passes_the_checks(name):
    c = _load(name)
    ir = builder.build(c, {"supply": 1}).ir
    assert "VT" in {e.name for e in ir.elements()}
    assert MICS[name][2] in {m.name for m in ir.models}
    assert [p for p in preflight.check_circuit(c) if "supply=1" in str(p)] == []


@pytest.mark.parametrize("name", MICS)
def test_the_real_supply_starts_where_it_runs(name):
    """After a render's settle, the rail is its target within 0.2% and doesn't drift: the start
    voltages put the RC sections where they run (without them it sags for seconds)."""
    pytest.importorskip("circuitsim", reason="needs `uv sync --extra fast`")
    from varimu.sim import fast
    from varimu.sim.io import TransientSettings

    node, target, _ = MICS[name]
    st = TransientSettings.from_sim_settings(engine="circuitsim")
    n = int(0.4 * st.sample_rate)
    import dataclasses

    from varimu.circuit import ir as I

    ir = builder.build_ir(_load(name), spec.resolve(_load(name), {"supply": 1}))
    if node not in {p.node for p in ir.probes}:
        ir = dataclasses.replace(ir, probes=(*ir.probes, I.VoltageProbe(node)))
    ctl = {k.name: np.zeros(n) for k in ir.controls} or None
    v = fast.run_transient(ir, np.zeros(n), settings=st, controls=ctl).vectors[f"v({node})"]
    first, last = float(np.mean(v[: n // 4])), float(np.mean(v[-n // 4 :]))
    assert first == pytest.approx(target, rel=2e-3)
    assert last == pytest.approx(first, abs=0.05)


def test_the_u67s_supply_lands_on_its_drawings_voltages():
    """NU67u-930-06 prints +243 V on C1 and +225 V on C3 (and +210 V out at 0.88 mA): with R7 read
    as 160 kOhm and the winding resistance trimmed to the +210 V, C1 and C3 land within 2%."""
    c = _load("neumann_u67")
    q = spec.resolve(c)
    assert q["nu_c1_v0_v"] == pytest.approx(243.0, rel=0.02)
    assert q["nu_c3_v0_v"] == pytest.approx(225.0, rel=0.02)


def test_a_devices_entrys_emit_takes_only_used(tmp_path):
    text = (CONFIG_DIR / "circuits" / "akg_c12.yaml").read_text(encoding="utf-8")
    bad = text.replace("instance: false, emit: used,", "instance: false, emit: always,")
    assert bad != text
    p = CONFIG_DIR / "circuits" / "_nh3_emit_test.yaml"
    p.write_text(bad, encoding="utf-8")
    try:
        with pytest.raises(ConfigError, match="emit"):
            builder.build(spec.load_circuit(p))
    finally:
        p.unlink()


CHAINS = [("c12_clean", "supply_c12"), ("u47_v76", "supply_u47"), ("m49_v76", "supply_m49")]


@pytest.mark.parametrize("chain, key", CHAINS)
def test_a_chain_carries_its_mics_supply_on_one_mains(chain, key):
    """compose_chain: one mains for the chain (the preamp's, else the mic's: the clean pre has
    none); the mic's SUPPLY switch, ideal by default."""
    c = _load(chain)
    assert c.mains
    assert "VT_" + key.split("_", 1)[1] not in {e.name for e in builder.build(c).ir.elements()}
    names = {e.name for e in builder.build(c, {key: 1}).ir.elements()}
    assert f"VT_{key.split('_', 1)[1]}" in names
