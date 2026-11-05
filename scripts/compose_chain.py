"""A microphone into a preamp as one circuit file (MIC_ROOM_PLAN.md: "mic, cable and
preamp are one netlist").

    uv run python scripts/compose_chain.py --mic neumann_u47 --pre telefunken_v76 [--check]

Writes config/circuits/<mic>_<pre>.yaml from the two circuit files: every parameter key,
device key, part and node of each gets its circuit's suffix (_<tag>: `u47`, `v76`, ...),
so nothing collides; the mic's measuring load (its PORTS `drop`) and the preamp's
test generator go; the mic's output node becomes the preamp's input node (behind where
the generator was), with the cable across it. The chain's input and control inputs are
the mic's (unsuffixed: `in`, `p_rear`), its output the preamp's `out`; full scale in from
the mic, out from the preamp; the preamp's mains, tolerance draws (seed, spread, tube
spreads) and noise block, the mic's tolerance classes in bands of their own.

The generated file says it is generated; edit its sources and rerun (`--check` exits 1
when the file on disk differs: tests/test_chain.py).
"""

from __future__ import annotations

import argparse
import copy
import sys
from typing import Any

import yaml

from varimu.circuit import spec
from varimu.config import CONFIG_DIR

# Per circuit: its tag, and how it joins a chain. A mic: its output node and the parts
# that are only its measuring setup. A preamp: the node a source drives (behind its
# generator's resistance) and the generator's parts.
PORTS = {
    "neumann_u47": {"tag": "u47", "output": "out", "drop": ["RLOAD"]},
    "telefunken_v76": {"tag": "v76", "input": "ia", "drop": ["RSRC"]},
    "omni_4134": {"tag": "omni", "output": "out", "drop": ["RMEAS"]},
    "clean_pre": {"tag": "clean", "input": "ia", "drop": ["RSRC"]},
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


def compose(mic_name: str, pre_name: str) -> dict:
    mic = yaml.safe_load(spec.circuit_path(mic_name).read_text(encoding="utf-8"))
    pre = yaml.safe_load(spec.circuit_path(pre_name).read_text(encoding="utf-8"))
    pm, pp = PORTS[mic_name], PORTS[pre_name]
    tm, tp = pm["tag"], pp["tag"]
    joint = f"{pp['input']}_{tp}"
    mic_keep = [mic["input"], *(mic.get("cv_inputs") or {}).values()]
    rm = Renamer(mic, tm, keep_nodes=mic_keep, node_map={pm["output"]: joint})
    rp = Renamer(pre, tp, node_map={"out": "out"})

    out: dict[str, Any] = {
        "title": f"{mic['title']} into the {pre['title']}",
        "input": mic["input"],
    }
    if mic.get("cv_inputs"):
        out["cv_inputs"] = dict(mic["cv_inputs"])
    out["probes"] = ["out", joint] + [
        rm.node(n) for n in mic.get("probes", []) if n != pm["output"]
    ]
    out["probes"] += [rp.node(n) for n in pre.get("probes", []) if n != "out"]
    out["probes"] = list(dict.fromkeys(out["probes"]))  # the joint may be the pre's probe too
    out["full_scale"] = {
        "input_volts_peak": mic["full_scale"]["input_volts_peak"],
        "output_volts_peak": pre["full_scale"]["output_volts_peak"],
    }
    for block in ("controls", "values", "device_params"):
        merged = {**_suffix_block(mic.get(block), tm), **_suffix_block(pre.get(block), tp)}
        if block == "values":
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
    if tol_tube := (pre["tolerance"].get("tube") or mic["tolerance"].get("tube")):
        r = rp if pre["tolerance"].get("tube") else rm
        tol = {**{k: tol[k] for k in ("source", "seed", "spread")},
               "tube": {k: r.key(v) for k, v in tol_tube.items()},
               **{k: tol[k] for k in ("bands", "classes")}}  # fmt: skip
    mt = mic["tolerance"]
    for b, v in mt["bands"].items():
        tol["bands"][f"{b}_{tm}"] = [rm.key(x) for x in v] if isinstance(v, list) else rm.key(v)
    for b, v in mt["classes"].items():
        names = [rm.part_name(p) for p in v if p not in pm["drop"]]
        tol["classes"][f"{b}_{tm}"] = names
    out["tolerance"] = tol
    devices = {}
    for r, c in ((rm, mic), (rp, pre)):
        for k, d in (c.get("devices") or {}).items():
            d = dict(d)
            d["device"] = r.param(d["device"])
            for x in ("area", "emission", "mu", "grid_contact_v"):
                if x in d:
                    d[x] = r.param(d[x])
            devices[f"{k}_{r.tag}"] = d
    out["devices"] = devices
    sections = []
    for r, c, drop in ((rm, mic, pm["drop"]), (rp, pre, pp["drop"])):
        for s in c["sections"]:
            parts = {r.part_name(n): r.part(p) for n, p in s["parts"].items() if n not in drop}
            sections.append({"title": f"{c['title']}: {s['title']}", "parts": parts})
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


def render(mic: str, pre: str) -> str:
    body = yaml.safe_dump(compose(mic, pre), sort_keys=False, width=100, allow_unicode=True)
    return HEADER.format(mic=mic, pre=pre) + body


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--mic", required=True)
    ap.add_argument("--pre", required=True)
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    text = render(args.mic, args.pre)
    path = CONFIG_DIR / "circuits" / f"{PORTS[args.mic]['tag']}_{PORTS[args.pre]['tag']}.yaml"
    if args.check:
        same = path.exists() and path.read_text(encoding="utf-8") == text
        print("current" if same else f"stale: {path}")
        sys.exit(0 if same else 1)
    path.write_text(text, encoding="utf-8")
    spec.load_circuit(path)  # it loads
    print(f"wrote {path}")


if __name__ == "__main__":
    main()
