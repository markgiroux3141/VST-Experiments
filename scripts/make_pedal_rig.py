"""A pedal into an amp as one circuit file: the guitar's signal through the pedal, a cable,
and the amp, one coupled netlist (the project's rule: the pedal's output impedance meets the
amp's input, a Fuzz Face's input meets the guitar).

    uv run python scripts/make_pedal_rig.py --pedal ibanez_ts808 --amp fender_5e3 [--check]
    uv run python scripts/make_pedal_rig.py --all [--check]   # every rig of RIGS

Writes config/circuits/<pedal>_<amp>.yaml from the two circuit files. The pedal's parameter
and device keys get its tag as a prefix (`ts_drive`), its nodes too (`ts_op1`) but ground and
its input `in` (the rig's input: the guitar), its parts the tag as a suffix (`R101_TS`: a part's
first letter is its element type). Its section `amp input load` (the standalone pedal's stand-in
for an amp) goes; its output `out` becomes the amp's input node, renamed `jack` (the amp's
`in`), with the pedal's cable from there to ground. Everything else is the amp's: its title,
mains, tolerance, heaters, probes (plus the jack), full scale out; the full scale in is the
pedal's. Pedals share the amp's ground: a pedal drawn about its bias node (the TS808) floats
its battery there (the circuit file's header says why that is exact).

The generated file says it is generated; edit its sources and rerun (`--check` exits 1 when
a file on disk differs: tests/test_pedal_rigs.py).
"""

from __future__ import annotations

import argparse
import sys
from typing import Any

import yaml

from varimu.config import CONFIG_DIR

CIRCUITS = CONFIG_DIR / "circuits"
GROUND = "0"

# Pedal file -> its tag (a short prefix).
TAGS = {"ibanez_ts808": "ts", "fuzz_face": "ff"}
# The rigs the app plays (pedal, amp).
RIGS = [
    ("ibanez_ts808", "fender_5e3"),
    ("ibanez_ts808", "marshall_1987"),
    ("fuzz_face", "marshall_1987"),
    ("fuzz_face", "fender_5e3"),
]
LOAD_SECTION = "amp input load"
# A part's keys that are node lists (its macro's first key's value is one too).
NODE_KEYS = {"nodes"}


def _load(name: str) -> dict[str, Any]:
    return yaml.safe_load((CIRCUITS / f"{name}.yaml").read_text(encoding="utf-8"))


def _rename_part(entry: dict[str, Any], keys: dict[str, str], node) -> dict[str, Any]:
    """A part's entry with its parameter references and nodes renamed (recursing into a
    switch's parts and a transformer's windings)."""
    out: dict[str, Any] = {}
    for i, (k, v) in enumerate(entry.items()):
        if i == 0 and isinstance(v, list):  # the macro's nodes
            out[k] = [node(n) for n in v]
        elif k == "parts" and isinstance(v, dict):
            out[k] = {f"{pk}": _rename_part(pv, keys, node) for pk, pv in v.items()}
        elif isinstance(v, dict):  # a transformer's windings, a core block
            out[k] = {
                kk: (_rename_part(vv, keys, node) if isinstance(vv, dict) else keys.get(vv, vv))
                for kk, vv in v.items()
            }
        elif k in NODE_KEYS and isinstance(v, list):
            out[k] = [node(n) for n in v]
        elif isinstance(v, str):
            out[k] = keys.get(v, v)
        else:
            out[k] = v
    return out


def _untoleranced(entry: dict[str, Any], amp: dict[str, Any]) -> dict[str, Any]:
    """In an amp with a tolerance block (every part in a class), a pedal's passive part
    without one (the pedals' drawings print none): `tolerance: none`."""
    macro = next(iter(entry))
    if "tolerance" not in amp or macro not in ("R", "C", "L", "pot", "rheostat"):
        return entry
    return {**entry, "tolerance": "none"}


def compose(pedal_name: str, amp_name: str) -> str:
    pedal, amp = _load(pedal_name), _load(amp_name)
    tag = TAGS[pedal_name]
    keys = {k: f"{tag}_{k}" for sec in ("controls", "values") for k in pedal.get(sec, {})}
    keys.update({k: f"{tag.upper()}{k}" for k in pedal.get("devices", {})})

    def pnode(n: str) -> str:
        if n in (GROUND, "in"):
            return n
        if n == "out":
            return "jack"
        return f"{tag}_{n}"

    def anode(n: str) -> str:
        return "jack" if n == "in" else n

    rig: dict[str, Any] = {"title": f"{pedal['title']} into the {amp['title']}"}
    rig["input"] = "in"
    rig["probes"] = [*amp.get("probes", []), "jack"]
    fs = dict(amp.get("full_scale", {}))
    fs["input_volts_peak"] = pedal["full_scale"]["input_volts_peak"]
    rig["full_scale"] = fs
    for block in ("heaters", "noise"):
        if block in amp:
            rig[block] = amp[block]
    rig["controls"] = {**{keys[k]: v for k, v in pedal.get("controls", {}).items()},
                       **amp.get("controls", {})}  # fmt: skip
    rig["values"] = {
        **{keys[k]: v for k, v in pedal.get("values", {}).items()},
        **amp.get("values", {}),
    }
    for block in ("mains", "tolerance"):
        if block in amp:
            rig[block] = amp[block]
    devices: dict[str, Any] = {}
    for k, v in pedal.get("devices", {}).items():
        devices[keys[k]] = {kk: keys.get(vv, vv) if isinstance(vv, str) else vv
                            for kk, vv in v.items()}  # fmt: skip
    devices.update(amp.get("devices", {}))
    rig["devices"] = devices
    sections = []
    for s in pedal["sections"]:
        if s["title"] == LOAD_SECTION:
            continue
        parts = {
            f"{name}_{tag.upper()}": _untoleranced(_rename_part(entry, keys, pnode), amp)
            for name, entry in s["parts"].items()
        }
        sections.append({"title": f"{tag} {s['title']}", "parts": parts})
    cable = {
        f"CRIG_{tag.upper()}": _untoleranced(
            {"C": ["jack", GROUND], "c": keys["cable_c_f"]}, amp
        ),
    }
    sections.append({"title": f"{tag} cable", "parts": cable})
    for s in amp["sections"]:
        s = dict(s)
        s["parts"] = {name: _rename_part(entry, {}, anode) for name, entry in s["parts"].items()}
        sections.append(s)
    rig["sections"] = sections
    for k in rig["values"]:
        if k in rig["controls"]:
            raise SystemExit(f"{k}: both a control and a value")
    header = (
        f"# GENERATED by scripts/make_pedal_rig.py from config/circuits/{pedal_name}.yaml and\n"
        f"# config/circuits/{amp_name}.yaml: don't edit; edit those and rerun. The pedal into the\n"
        "# amp as one netlist (the script's docstring): the pedal's keys and nodes prefixed\n"
        f"# `{tag}_`, its parts suffixed `_{tag.upper()}`, its output the amp's input `jack`.\n"
    )
    body = yaml.safe_dump(rig, sort_keys=False, allow_unicode=True, width=100)
    return header + body


def out_path(pedal: str, amp: str):
    return CIRCUITS / f"{pedal}_{amp}.yaml"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--pedal")
    ap.add_argument("--amp")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--check", action="store_true", help="exit 1 if a file on disk differs")
    a = ap.parse_args()
    rigs = RIGS if a.all else [(a.pedal, a.amp)]
    stale = False
    for pedal, amp in rigs:
        text, path = compose(pedal, amp), out_path(pedal, amp)
        if a.check:
            same = path.exists() and path.read_text(encoding="utf-8") == text
            stale |= not same
            print(f"{path.name}: {'current' if same else 'STALE'}")
        else:
            path.write_text(text, encoding="utf-8", newline="\n")
            print(f"wrote {path}")
    sys.exit(1 if stale else 0)


if __name__ == "__main__":
    main()
