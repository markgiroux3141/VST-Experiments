"""Write the circuit test fixtures.

    uv run python scripts/export_circuit_fixtures.py           # IR JSON for the Rust tests
    uv run python scripts/export_circuit_fixtures.py --golden  # also re-capture the SPICE goldens

SPICE goldens (tests/fixtures/netlist_golden/): the netlist text and the table
file names for a set of builds that cover every switch position, the pot
extremes, tube mismatch and both triode formulations. They were first captured
before netlist.py was refactored to build an IR (circuit-sim plan, M1), so the
test that compares against them proves the refactor changed nothing; the same
held for the device builder's B1 (the 670 rebuilt from its circuit file). Re-capture
them only when the circuit is meant to change, and review the diff.

IR JSON (crates/circuitsim/tests/fixtures/): the same builds as IR, which the
Rust serde round-trip tests read.

Device fixtures (crates/circuitsim/tests/fixtures/devices/devices.json): every
device model of the 670 (plus mismatch, a triode without grid current, a
series-resistance-free diode and the GZ34) evaluated by the Python reference
on grids, for the Rust device tests (varimu.devices.fixtures).

Noise fixtures (crates/circuitsim/tests/fixtures/noise/noise.json): the noise
streams' raw Philox words, normals and the flicker filter, from the Python
reference (varimu.devices.noise), for crates/circuitsim/tests/noise.rs.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from varimu.circuit import netlist as nl
from varimu.config import REPO_ROOT
from varimu.devices.cathode import cathode_fixtures_json
from varimu.devices.fixtures import MISMATCH, device_fixtures_json
from varimu.devices.noise import noise_fixtures_json

GOLDEN_DIR = REPO_ROOT / "tests" / "fixtures" / "netlist_golden"
RUST_FIXTURE_DIR = REPO_ROOT / "crates" / "circuitsim" / "tests" / "fixtures"
DEVICE_FIXTURE = RUST_FIXTURE_DIR / "devices" / "devices.json"
NOISE_FIXTURE = RUST_FIXTURE_DIR / "noise" / "noise.json"
CATHODE_FIXTURE = RUST_FIXTURE_DIR / "cathode" / "cathode.json"

_MISMATCH = MISMATCH

# name -> (overrides, triode formulation)
CASES: dict[str, tuple[dict, str]] = {
    "default_table": ({}, "table"),
    "default_exact": ({}, "exact"),
    **{f"tc{pos}": ({"time_constant": pos}, "table") for pos in range(1, 7)},
    "pots_min": (
        {
            "input_atten_db": 0.0,
            "ac_threshold": 0.0,
            "dc_threshold": 0.0,
            "zero": 0.0,
            "balance": 0.0,
        },
        "table",
    ),
    "pots_max": (
        {
            "input_atten_db": 30.0,
            "ac_threshold": 1.0,
            "dc_threshold": 1.0,
            "zero": 1.0,
            "balance": 1.0,
        },
        "table",
    ),
    "mismatch_table": (_MISMATCH, "table"),
    "mismatch_exact": ({**_MISMATCH, "time_constant": 6}, "exact"),
}


def build_case(name: str, cores: str = "ja"):
    """The case's circuit: Jiles-Atherton cores for the IR fixtures, linear cores for
    the SPICE goldens (ngspice has no core model)."""
    overrides, form = CASES[name]
    return nl.build(overrides, triode_formulation=form, cores=cores)


def write_golden(out_dir: Path = GOLDEN_DIR) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    index = {}
    for name, (overrides, form) in CASES.items():
        c = build_case(name, cores="linear")
        (out_dir / f"{name}.cir").write_bytes(c.text.encode("utf-8"))
        index[name] = {
            "overrides": overrides,
            "triode_formulation": form,
            "files": {k: Path(v).name for k, v in sorted(c.files.items())},
        }
        print(f"{name}: {len(c.text)} chars, {len(c.files)} files")
    (out_dir / "cases.json").write_bytes((json.dumps(index, indent=2) + "\n").encode("utf-8"))


def write_ir(out_dir: Path = RUST_FIXTURE_DIR) -> None:
    """One file per distinct IR (the triode formulation is a SPICE choice, not in the IR),
    plus index.json: case name -> file."""
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("*.json"):
        old.unlink()
    index: dict[str, str] = {}
    written: dict[str, str] = {}  # IR JSON -> file name
    for name in CASES:
        ir = build_case(name).ir
        text = ir.to_json()
        if text not in written:
            fname = f"{name.removesuffix('_table')}.json"
            (out_dir / fname).write_bytes(text.encode("utf-8"))
            written[text] = fname
            n_el = sum(1 for _ in ir.elements())
            print(f"{fname}: {n_el} elements, {len(ir.models)} models")
        index[name] = written[text]
    (out_dir / "index.json").write_bytes((json.dumps(index, indent=2) + "\n").encode("utf-8"))


def write_devices(path: Path = DEVICE_FIXTURE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(device_fixtures_json().encode("utf-8"))
    print(f"{path.name}: {path.stat().st_size} bytes")


def write_noise(path: Path = NOISE_FIXTURE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(noise_fixtures_json().encode("utf-8"))
    print(f"{path.name}: {path.stat().st_size} bytes")


def write_cathode(path: Path = CATHODE_FIXTURE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(cathode_fixtures_json().encode("utf-8"))
    print(f"{path.name}: {path.stat().st_size} bytes")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--golden", action="store_true", help="re-capture the SPICE goldens too")
    args = ap.parse_args()
    if args.golden:
        write_golden()
    write_ir()
    write_devices()
    write_noise()
    write_cathode()


if __name__ == "__main__":
    main()
