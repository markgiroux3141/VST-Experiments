"""Every microphone into every preamp (scripts/compose_chain.py --all): the generated chain
files are current, each builds as one netlist with the mic's load and the preamp's
generator gone, the room finds its capsule, and the Room view offers each
(varimu-app room::CHAINS)."""

from __future__ import annotations

import re
import subprocess
import sys

import pytest

from varimu.circuit import builder, spec
from varimu.config import REPO_ROOT

sys.path.insert(0, str(REPO_ROOT / "scripts"))
import compose_chain  # noqa: E402

PAIRS = [(m, p) for m in compose_chain.MICS for p in compose_chain.PREAMPS]


def test_every_pair_is_current():
    r = subprocess.run(
        [sys.executable, "scripts/compose_chain.py", "--all", "--check"],
        cwd=REPO_ROOT, capture_output=True, text=True,
    )  # fmt: skip
    assert r.returncode == 0, r.stdout + r.stderr
    assert len(PAIRS) == 8


@pytest.mark.parametrize("mic,pre", PAIRS)
def test_each_pair_builds_as_one_netlist(mic, pre):
    from varimu.rooms.scene import _capsule_geometry

    name = compose_chain.chain_name(mic, pre)
    c = spec.load_circuit(spec.circuit_path(name))
    ir = builder.build(c, {}).ir
    names = {e.name for e in ir.elements()}
    pm, pp = compose_chain.PORTS[mic], compose_chain.PORTS[pre]
    assert "CCABLE" in names
    for part in pm["drop"]:
        assert f"{part}_{pm['tag'].upper()}" not in names
    for part in pp["drop"]:
        assert f"{part}_{pp['tag'].upper()}" not in names
    has_rear = any(k.name == "p_rear" for k in ir.controls)
    assert has_rear == (mic != "omni_4134")  # a pressure capsule has one entry
    assert _capsule_geometry(name, {}).get("body")  # the room's entry tables need a body


def test_the_room_view_offers_every_pair():
    src = (REPO_ROOT / "crates" / "varimu-app" / "src" / "room.rs").read_text(encoding="utf-8")
    start = src.index("pub const CHAINS")
    block = src[start : src.index("\n];", start)]
    ids = re.findall(r'id: "([a-z0-9_]+)"', block)
    assert sorted(ids) == sorted(compose_chain.chain_name(m, p) for m, p in PAIRS)
    for cid in ids:  # every setting the app offers is a key of the chain
        c = spec.load_circuit(spec.circuit_path(cid))
        q = spec.resolve(c, {})
        chain_block = block[block.index(f'id: "{cid}"') :].split("Chain {")[0]
        for key in re.findall(r'key: "([a-z0-9_]+)"', chain_block):
            assert key in q, (cid, key)
