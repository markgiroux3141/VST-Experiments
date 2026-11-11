"""The chain list (config/chains.yaml, varimu/chains.py; docs/CHAINS_PLAN.md): every
available chain's generated file is current (scripts/compose_chain.py --all), each builds
as one netlist with the mic's load and the preamp's generator gone, the room finds its
capsule, and every setting the Room view offers (varimu-app room::chains reads the same
list) is a key of its chain."""

from __future__ import annotations

import subprocess
import sys

import pytest

from varimu import chains as chain_list
from varimu.circuit import builder, spec
from varimu.config import REPO_ROOT

sys.path.insert(0, str(REPO_ROOT / "scripts"))
import compose_chain  # noqa: E402

LIST = chain_list.load()
AVAILABLE = LIST.available()


def test_every_available_chain_is_current():
    r = subprocess.run(
        [sys.executable, "scripts/compose_chain.py", "--all", "--check"],
        cwd=REPO_ROOT, capture_output=True, text=True,
    )  # fmt: skip
    assert r.returncode == 0, r.stdout + r.stderr
    assert len(compose_chain.listed_pairs()) == len(AVAILABLE)
    assert {c.id for c in AVAILABLE} >= {"u47_v76", "omni_clean", "sm58_clean"}


def test_the_list():
    assert len(LIST.chains) == 51  # MIC_ROOM_PLAN.md's curation; a change is the user's
    for c in LIST.chains:
        assert c.id == "_".join(s.tag for s in c.stages)
        assert c.use
        if not c.available:  # a blocked chain says what builds it
            assert all(s.wp for s in c.missing), c.id
    assert LIST.chain("sm57_v76").label == "SM57 → V76"
    assert [(s.key, s.default) for s in LIST.chain("sm57_v76").settings()] == [
        ("impedance_sm57", 0.0),
        ("gain_db_v76", 58.0),
    ]


def test_a_wrong_id_is_refused(tmp_path):
    text = chain_list.CHAINS_PATH.read_text(encoding="utf-8")
    bad = tmp_path / "chains.yaml"
    bad.write_text(text.replace("- id: u47_clean", "- id: u47_cln"), encoding="utf-8")
    with pytest.raises(ValueError, match="u47_cln"):
        chain_list.load(bad)


@pytest.mark.parametrize("chain", AVAILABLE, ids=lambda c: c.id)
def test_each_chain_builds_as_one_netlist(chain):
    from varimu.rooms.scene import _capsule_geometry

    c = spec.load_circuit(chain.path)
    ir = builder.build(c, {}).ir
    names = {e.name for e in ir.elements()}
    assert "CCABLE" in names
    for stage in chain.stages:
        for part in stage.drop:
            assert f"{part}_{stage.tag.upper()}" not in names
    has_rear = any(k.name == "p_rear" for k in ir.controls)
    pressure = ("omni_4134", "carbon_transmitter", "crown_pzm")  # a pressure transducer: one entry
    assert has_rear == (chain.mic.name not in pressure)
    assert _capsule_geometry(chain.id, {}).get("body")  # the room's entry tables need a body
    q = spec.resolve(c, {})
    for s in chain.settings():  # every setting the app offers is a key of the chain
        assert s.key in q, (chain.id, s.key)
