"""A microphone into a preamp as one circuit file (MIC_ROOM_PLAN.md: "mic, cable and
preamp are one netlist").

    uv run python scripts/compose_chain.py --mic neumann_u47 --pre telefunken_v76 [--check]
    uv run python scripts/compose_chain.py --mic rca_44bx --booster cloudlifter --pre clean_pre
    uv run python scripts/compose_chain.py --all [--check]   # every available chain of the list

Writes config/circuits/<mic>_<pre>.yaml from the two circuit files: every parameter key,
device key, part and node of each gets its circuit's suffix (_<tag>: `u47`, `v76`, ...),
so nothing collides; the mic's measuring load (its PORTS `drop`) and the preamp's
test generator go; the mic's output node becomes the preamp's input node (behind where
the generator was), with the cable across it. The chain's input and control inputs are
the mic's (unsuffixed: `in`, `p_rear`), its output the preamp's `out`; full scale in from
the mic, out from the preamp; the preamp's mains, tolerance draws (seed, spread, tube
spreads) and noise block, the mic's tolerance classes in bands of their own.

The generated file says it is generated; edit its sources and rerun (`--check` exits 1
when the file on disk differs: tests/test_chain_matrix.py). The tags and ports are
config/chains.yaml's (varimu/chains.py); `--all` writes every chain of that list whose
stages are built (scripts/chain_status.py; the Room view offers them).
"""

from __future__ import annotations

import argparse
import copy
import sys
from typing import Any

import yaml

from varimu import chains as chain_list
from varimu.chains import PORT
from varimu.circuit import spec
from varimu.config import CONFIG_DIR

# Per built circuit of the list: its tag, and how it joins a chain. A mic: its output node
# and the parts that are only its measuring setup. A preamp: the node a source drives
# (behind its generator's resistance) and the generator's parts.
CHAINS = chain_list.load()
PORTS = {
    c.name: {
        "tag": c.tag,
        PORT[c.kind]: getattr(c, PORT[c.kind]),
        **({"output": c.output} if c.kind == "booster" else {}),
        "drop": list(c.drop),
        **({"cable": c.cable} if c.cable else {}),
    }
    for c in CHAINS.circuits.values()
    if c.built
}
CABLE = {
    "cable_c_f": {
        "value": 1.0e-9,
        "source": "provisional: model knowledge (10 m of microphone cable, ~100 pF/m "
        "between the audio pair; the UC 4's per-metre values weren't found)",
    },
}
GROUND = "0"


def _keys(c: dict) -> set[str]:
    out = set()
    for block in ("controls", "values", "device_params"):
        out |= set(c.get(block) or {})
    return out


class Renamer:
    def __init__(self, c: dict, tag: str, keep_nodes=(), node_map=None):
        self.keys = _keys(c)
        self.devices = set(c.get("devices") or {})
        self.tag = tag
        self.keep = set(keep_nodes) | {GROUND}
        self.node_map = dict(node_map or {})

    def key(self, k: Any) -> Any:
        return f"{k}_{self.tag}" if isinstance(k, str) and k in self.keys else k

    def node(self, n: str) -> str:
        n = str(n)
        if n in self.node_map:
            return self.node_map[n]
        return n if n in self.keep else f"{n}_{self.tag}"

    def part_name(self, p: str) -> str:
        return f"{p}_{self.tag}"

    def param(self, x: Any) -> Any:
        if isinstance(x, str):
            return self.key(x)
        return x

    def part(self, entry: dict) -> dict:
        entry = copy.deepcopy(entry)
        macro = next(iter(entry))
        out: dict[str, Any] = {}
        for k, v in entry.items():
            if k == macro:
                if macro == "switch":
                    out[k] = self.key(v)
                elif macro == "transformer":
                    out[k] = {
                        lbl: {
                            wk: ([self.node(n) for n in wv] if wk == "nodes" else self.param(wv))
                            for wk, wv in w.items()
                        }
                        for lbl, w in v.items()
                    }
                elif macro in ("K",):
                    out[k] = [self.part_name(n) for n in v]
                else:
                    out[k] = [self.node(n) for n in v]
            elif k == "parts":
                out[k] = {self.part_name(n): self.part(p) for n, p in v.items()}
            elif k in ("model", "clamp"):  # a device key (a tube's model, an op-amp's clamp)
                out[k] = f"{v}_{self.tag}" if v in self.devices else v
            elif k == "core":
                out[k] = {ck: self.param(cv) for ck, cv in v.items()}
            elif k in ("in", "tolerance"):
                out[k] = v
            else:
                out[k] = self.param(v)
        return out


def _suffix_block(block: dict | None, tag: str) -> dict:
    return {f"{k}_{tag}": v for k, v in (block or {}).items()}


def compose(mic_name: str, pre_name: str, booster_name: str | None = None) -> dict:
    """The chain's circuit file as a dict: the mic, an optional booster (CHAINS_PLAN.md WP27:
    the mic's output its input, its output the preamp's input, its test generator dropped;
    the cable at the mic's output), the preamp."""
    mic = yaml.safe_load(spec.circuit_path(mic_name).read_text(encoding="utf-8"))
    pre = yaml.safe_load(spec.circuit_path(pre_name).read_text(encoding="utf-8"))
    pm, pp = PORTS[mic_name], PORTS[pre_name]
    tm, tp = pm["tag"], pp["tag"]
    joint = f"{pp['input']}_{tp}"
    mid: list[tuple[Renamer, dict, list[str]]] = []
    if booster_name is not None:
        bst = yaml.safe_load(spec.circuit_path(booster_name).read_text(encoding="utf-8"))
        pb = PORTS[booster_name]
        tb = pb["tag"]
        rb = Renamer(bst, tb, node_map={pb["output"]: joint})
        joint = f"{pb['input']}_{tb}"  # the mic's output: the booster's input
        mid = [(rb, bst, pb["drop"])]
    mic_keep = [mic["input"], *(mic.get("cv_inputs") or {}).values()]
    rm = Renamer(mic, tm, keep_nodes=mic_keep, node_map={pm["output"]: joint})
    rp = Renamer(pre, tp, node_map={"out": "out"})
    stages = [(rm, mic, pm["drop"]), *mid, (rp, pre, pp["drop"])]

    out: dict[str, Any] = {
        "title": " into the ".join(c["title"] for _, c, _ in stages),
        "input": mic["input"],
    }
    if mic.get("cv_inputs"):
        out["cv_inputs"] = dict(mic["cv_inputs"])
    out["probes"] = ["out", joint] + [
        rm.node(n) for n in mic.get("probes", []) if n != pm["output"]
    ]
    for r, c, _ in mid:
        out["probes"] += [r.node(n) for n in c.get("probes", [])]
    out["probes"] += [rp.node(n) for n in pre.get("probes", []) if n != "out"]
    out["probes"] = list(dict.fromkeys(out["probes"]))  # the joint may be the pre's probe too
    # a preamp's output is volts; an amplifier's (the 5E3: CHAINS_PLAN.md WP30) its speaker's
    # pressure
    out_key = "output_volts_peak"
    if "output_pascals_peak" in pre["full_scale"]:
        out_key = "output_pascals_peak"
    out["full_scale"] = {
        "input_volts_peak": mic["full_scale"]["input_volts_peak"],
        out_key: pre["full_scale"][out_key],
    }
    attached = pm.get("cable") == "attached"  # the mic's own cord is in its file
    for block in ("controls", "values", "device_params"):
        merged = {**_suffix_block(mic.get(block), tm)}
        for r, c, _ in mid:
            merged.update(_suffix_block(c.get(block), r.tag))
        merged.update(_suffix_block(pre.get(block), tp))
        if block == "values" and not attached:
            merged.update(CABLE)
        if merged:
            out[block] = merged
    if pre.get("noise") or mic.get("noise"):
        out["noise"] = copy.deepcopy(pre.get("noise") or mic.get("noise"))
    if pre.get("mains"):
        m = copy.deepcopy(pre["mains"])
        out["mains"] = {k: rp.param(v) for k, v in m.items()}
    tol = copy.deepcopy(pre["tolerance"])
    tol = {
        "source": tol["source"],
        "seed": rp.key(tol["seed"]),
        "spread": rp.key(tol["spread"]),
        "bands": {
            f"{b}_{tp}": ([rp.key(x) for x in v] if isinstance(v, list) else rp.key(v))
            for b, v in tol["bands"].items()
        },
        "classes": {f"{b}_{tp}": [rp.part_name(p) for p in v] for b, v in tol["classes"].items()},
    }
    mt = mic.get("tolerance") or {}  # a nominal-only mic (the SM57) has none
    if tol_tube := (pre["tolerance"].get("tube") or mt.get("tube")):
        r = rp if pre["tolerance"].get("tube") else rm
        tol = {**{k: tol[k] for k in ("source", "seed", "spread")},
               "tube": {k: r.key(v) for k, v in tol_tube.items()},
               **{k: tol[k] for k in ("bands", "classes")}}  # fmt: skip
    for b, v in (mt.get("bands") or {}).items():
        tol["bands"][f"{b}_{tm}"] = [rm.key(x) for x in v] if isinstance(v, list) else rm.key(v)
    for b, v in (mt.get("classes") or {}).items():
        names = [rm.part_name(p) for p in v if p not in pm["drop"]]
        tol["classes"][f"{b}_{tm}"] = names
    for r, c, drop in mid:
        bt = c.get("tolerance") or {}
        for b, v in (bt.get("bands") or {}).items():
            tol["bands"][f"{b}_{r.tag}"] = (
                [r.key(x) for x in v] if isinstance(v, list) else r.key(v)
            )
        for b, v in (bt.get("classes") or {}).items():
            tol["classes"][f"{b}_{r.tag}"] = [r.part_name(p) for p in v if p not in drop]
    out["tolerance"] = tol
    devices = {}
    for r, c, _ in stages:
        for k, d in (c.get("devices") or {}).items():
            d = dict(d)
            d["device"] = r.param(d["device"])
            for x in ("area", "emission", "mu", "grid_contact_v"):
                if x in d:
                    d[x] = r.param(d[x])
            devices[f"{k}_{r.tag}"] = d
    out["devices"] = devices
    sections = []
    for r, c, drop in stages:
        for s in c["sections"]:
            parts = {r.part_name(n): r.part(p) for n, p in s["parts"].items() if n not in drop}
            sections.append({"title": f"{c['title']}: {s['title']}", "parts": parts})
    if not attached:
        sections.insert(
            len(mic["sections"]),
            {
                "title": "cable",
                "parts": {"CCABLE": {"C": [joint, GROUND], "c": "cable_c_f", "tolerance": "none"}},
            },
        )
    out["sections"] = sections
    return out


HEADER = """# GENERATED by scripts/compose_chain.py from config/circuits/{mic}.yaml and {pre}.yaml:
# don't edit; edit those and rerun (`uv run python scripts/compose_chain.py --mic {mic}
# --pre {pre}`). The {mic} into the {pre} as one netlist (MIC_ROOM_PLAN.md): every key,
# part and node of each carries its circuit's suffix; the mic's output is the preamp's
# input node, the cable across it.

"""
HEADER3 = """# GENERATED by scripts/compose_chain.py from config/circuits/{mic}.yaml,
# {booster}.yaml and {pre}.yaml: don't edit; edit those and rerun (`uv run python
# scripts/compose_chain.py --mic {mic} --booster {booster} --pre {pre}`). The {mic} into
# the {booster} into the {pre} as one netlist (MIC_ROOM_PLAN.md): every key, part and node
# of each carries its circuit's suffix; the mic's output is the booster's input node, the
# cable across it; the booster's output is the preamp's input node.

"""


def render(mic: str, pre: str, booster: str | None = None) -> str:
    body = yaml.safe_dump(
        compose(mic, pre, booster), sort_keys=False, width=100, allow_unicode=True
    )
    if booster is None:
        head = HEADER.format(mic=mic, pre=pre)
        if PORTS[mic].get("cable") == "attached":
            head = head.replace("the cable across it.", "its own cord across it.")
        return head + body
    return HEADER3.format(mic=mic, booster=booster, pre=pre) + body


def chain_name(mic: str, pre: str, booster: str | None = None) -> str:
    names = [mic, *([booster] if booster else []), pre]
    return "_".join(PORTS[n]["tag"] for n in names)


def listed_pairs() -> list[tuple[str, str, str | None]]:
    """The (mic, pre, booster or None) of every available chain of the list."""
    return [
        (c.mic.name, c.pre.name, c.booster.name if c.booster else None) for c in CHAINS.available()
    ]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--mic")
    ap.add_argument("--pre")
    ap.add_argument("--booster")
    ap.add_argument("--all", action="store_true", help="every available chain of the list")
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    if args.all:
        pairs = listed_pairs()
    elif args.mic and args.pre:
        pairs = [(args.mic, args.pre, args.booster)]
    else:
        ap.error("--mic and --pre, or --all")
    stale = []
    for mic, pre, booster in pairs:
        text = render(mic, pre, booster)
        path = CONFIG_DIR / "circuits" / f"{chain_name(mic, pre, booster)}.yaml"
        if args.check:
            if not (path.exists() and path.read_text(encoding="utf-8") == text):
                stale.append(path)
            continue
        path.write_text(text, encoding="utf-8")
        spec.load_circuit(path)  # it loads
        print(f"wrote {path}")
    if args.check:
        print("\n".join(f"stale: {p}" for p in stale) or "current")
        sys.exit(1 if stale else 0)


if __name__ == "__main__":
    main()
