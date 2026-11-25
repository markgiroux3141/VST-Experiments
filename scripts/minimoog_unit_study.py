"""Does a drawn Minimoog oscillator, re-trimmed by Folkman's procedure, track differently from the
nominal one? (MINIMOOG_BACKLOG.md "Authenticity first", item 3: what a unit's own part tolerances
are worth once the factory trims have been run on it.)

Oscillator 1's file (config/circuits/minimoog_vco.yaml) is copied with a tolerance block added
(cache/minimoog/units/): every resistor, capacitor and pot gets a class from its value's source
(a printed "1%" -> r1, other resistors r5, capacitors c10 (Table 7-4: the integrator C7
polycarbonate +-10 %, the ceramics +-10 %), tantalum / electrolytic c20, pots and trimmers pot20;
the printed 1 % / 5 % / 10 % from the parts list, the tantalums' and pots' bands provisional),
drawn with the builder's own draw (`parts.Tolerance`: default_rng([seed, crc32(designator)]),
uniform in the band). Folkman's four trims are then solved on it at the 12.288 MHz reference
(scripts/minimoog_vco_trim.py's `trim`), and its pitch measured at keys across the keyboard on 2',
8' and 32' against the nominal unit's, both against equal temperament from the low A.

    uv run --extra fast python scripts/minimoog_unit_study.py [--seeds 1 2] [--spread 1.0]

Writes reports/minimoog/units/study.json (~5-10 min a unit: every measurement is the reference,
~250x slower than real time, 20 at once).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import minimoog_vco_trim as trim  # noqa: E402

from varimu.config import CONFIG_DIR  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SRC = CONFIG_DIR / "circuits" / "minimoog_vco.yaml"
WORK = ROOT / "cache" / "minimoog" / "units"
OUT = ROOT / "reports" / "minimoog" / "units"
# Keys across the keyboard (MIDI note, RANGE position: 5 = 2', 3 = 8', 1 = 32').
CHECKS = [(41, 5), (45, 5), (57, 5), (69, 5), (81, 5), (84, 5), (41, 3), (57, 3), (72, 3),
          (45, 1), (57, 1)]  # fmt: skip
BANDS = {"r1": 1.0, "r5": 5.0, "c10": 10.0, "c20": [20.0, 50.0], "pot20": 20.0}
TOLERANCED = {"R", "C", "pot", "rheostat", "tapped_pot", "t_pad"}


def value_source(d: dict, param) -> str:
    if isinstance(param, dict):
        return str(param.get("source", ""))
    entry = d.get("values", {}).get(param) or d.get("controls", {}).get(param) or {}
    return str(entry.get("source", "")) if isinstance(entry, dict) else ""


def class_of(d: dict, name: str, part: dict) -> str | None:
    kind = next((k for k in part if k in TOLERANCED), None)
    if kind is None or part.get("tolerance") == "none":
        return None
    if kind in ("pot", "rheostat", "tapped_pot", "t_pad"):
        return "pot20"
    if kind == "R":
        return "r1" if "1%" in value_source(d, part.get("r")) else "r5"
    src = value_source(d, part.get("c")).lower()
    if "tantalum" in src or "electrolytic" in src:
        return "c20"
    return "c10"


def parts_of(sections: list) -> list[tuple[str, dict]]:
    out = []
    for s in sections:
        for name, part in s.get("parts", {}).items():
            if "switch" in part:
                out += list(part.get("parts", {}).items())
            else:
                out.append((name, part))
    return out


def drawn_file(seed: int, spread: float) -> Path:
    d = yaml.safe_load(SRC.read_text(encoding="utf-8"))
    classes: dict[str, list[str]] = {}
    for name, part in parts_of(d["sections"]):
        c = class_of(d, name, part)
        if c is not None:
            classes.setdefault(c, []).append(name)
    d["values"]["unit_seed"] = {"value": seed, "source": "minimoog_unit_study.py: the unit"}
    d["values"]["unit_spread"] = {"value": spread, "source": "minimoog_unit_study.py"}
    d["tolerance"] = {
        "source": "minimoog_unit_study.py: printed 1% resistors; the rest provisional",
        "seed": "unit_seed",
        "spread": "unit_spread",
        "bands": BANDS,
        "classes": classes,
    }
    WORK.mkdir(parents=True, exist_ok=True)
    path = WORK / f"minimoog_vco_unit{seed}.yaml"
    path.write_text(yaml.safe_dump(d, sort_keys=False, width=10**9), encoding="utf-8")
    return path


def tracking(trims: dict) -> list[dict]:
    with ThreadPoolExecutor(len(CHECKS)) as pool:
        hz = list(pool.map(lambda c: trim.measure_hz(trims, *c), CHECKS))
    return [
        {"note": n, "range": r, "hz": f, "cents": trim.cents(f, trim.target_hz(n, r))}
        for (n, r), f in zip(CHECKS, hz, strict=True)
    ]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--seeds", type=int, nargs="+", default=[1, 2])
    ap.add_argument("--spread", type=float, default=1.0)
    a = ap.parse_args()
    nominal_trims = {
        k: float(yaml.safe_load(SRC.read_text(encoding="utf-8"))["values"][k]["value"])
        for k in trim.TRIMS
    }
    report: dict = {"checks": CHECKS, "bands": BANDS, "units": {}}
    trim.CIRCUIT = SRC
    t0 = time.time()
    report["nominal"] = {"trims": nominal_trims, "tracking": tracking(nominal_trims)}
    print("nominal:", [round(x["cents"], 2) for x in report["nominal"]["tracking"]], flush=True)
    for seed in a.seeds:
        trim.CIRCUIT = drawn_file(seed, a.spread)
        before = tracking(nominal_trims)
        print(f"unit {seed} untrimmed:", [round(x["cents"], 1) for x in before], flush=True)
        trims = trim.trim(nominal_trims)
        after = tracking(trims)
        print(f"unit {seed} trimmed:", [round(x["cents"], 2) for x in after], flush=True)
        report["units"][seed] = {"trims": trims, "untrimmed": before, "tracking": after}
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / "study.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    report["wall_s"] = time.time() - t0
    (OUT / "study.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(f"wrote {OUT / 'study.json'} ({report['wall_s']:.0f} s)")


if __name__ == "__main__":
    main()
