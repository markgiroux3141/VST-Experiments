"""Write the native app's circuit-builder fixtures (docs/NATIVE_APP_PLAN.md, R1).

    uv run python scripts/export_app_fixtures.py

For every circuit file in config/circuits/, the IR Python builds (varimu.circuit.builder,
the reference) at its defaults and over a sweep of its controls, one control at a time:
every selector position or choice, every other control at 0 / 0.3 / 0.5 / 0.7 / 1 of
its range; plus the defaults with linear cores, with noise forced on (device builder B5:
a seed past 2^63; off too where the file has a `noise` block), heated (B6: cold, and warm at
the lowest mains, where every tube has a heater rating) and, for the 670, a few values and
device parameters away from nominal. crates/varimu-circuit's tests build the same cases in
Rust and compare value by value (tests/agreement.rs).

One file per circuit, crates/varimu-circuit/tests/fixtures/<circuit>.json: the default
IR in full, and per case only the sections (and the models) that differ from it, which
keeps ~300 IRs to a few hundred kB. tests/test_app_fixtures.py fails when they're stale.
"""

from __future__ import annotations

import json
from typing import Any

from varimu.circuit import builder, spec
from varimu.config import CONFIG_DIR, REPO_ROOT

FIXTURE_DIR = REPO_ROOT / "crates" / "varimu-circuit" / "tests" / "fixtures"
FRACTIONS = (0.0, 0.3, 0.5, 0.7, 1.0)
NOISE_SEED = 2**63 + 12345  # past i64: the seed is a u64 everywhere
#: Circuits whose reduced tape is checked at its defaults only (an events case embeds the
#: whole reduction, ~4-7 MB): the 351-2's tapes are the mono echo's, which sweeps them.
REDUCTION_DEFAULT_ONLY = {"ampex_351_2_echo"}

# Away from nominal (values and device parameters; nonzero tolerance spread is refused
# in Rust for now, so passive_spread stays 0).
EXTRA = {
    "fairchild_670": {
        "tubes": {
            "v6386_a.emission_scale": 1.1,
            "v6386_b.mu_spread": 0.97,
            "v6386_a.grid_contact_v": -0.5,
        },
        "materials": {"t101_core_material": "grain_oriented_si_steel", "t101_gap_m": 25.0e-6},
    },
}


def circuit_names() -> list[str]:
    return sorted(p.stem for p in (CONFIG_DIR / "circuits").glob("*.yaml"))


def control_cases(c: spec.CircuitSpec) -> list[tuple[str, dict[str, Any]]]:
    cases = []
    for k, e in c.controls.items():
        if "choices" in e:
            values = list(e["choices"])
        elif e.get("unit") == "position":
            values = list(range(int(e["min"]), int(e["max"]) + 1))
        else:
            values = [e["min"] + f * (e["max"] - e["min"]) for f in FRACTIONS]
        cases += [(f"{k}={v}", {k: v}) for v in values]
    return cases


def ir_dict(
    c: spec.CircuitSpec,
    overrides: dict[str, Any],
    cores: str,
    noise: bool | int | None = None,
    heaters: bool | str | None = None,
    events: bool = False,
) -> dict[str, Any]:
    p = spec.resolve(c, overrides)
    return builder.build_ir(c, p, cores, noise, heaters, events).to_dict()


def heated(c: spec.CircuitSpec) -> bool:
    """Whether every tube of the circuit has a heater rating (config/cathodes.yaml): its
    heated build is a case."""
    from varimu.config import ConfigError

    try:
        builder.build_ir(c, spec.resolve(c), heaters="warm")
    except ConfigError as e:
        if "no heater rating" in str(e):
            return False
        raise
    return True


def fixture(name: str) -> dict[str, Any]:
    c = spec.load_circuit(CONFIG_DIR / "circuits" / f"{name}.yaml")
    default = ir_dict(c, {}, "ja")
    cases: list[tuple[str, dict, str, bool | int | None, Any, bool]] = [
        ("linear", {}, "linear", None, None, False)
    ]
    cases += [(n, o, "ja", None, None, False) for n, o in control_cases(c)]
    cases += [(n, o, "ja", None, None, False) for n, o in EXTRA.get(name, {}).items()]
    cases.append(("noise", {}, "ja", NOISE_SEED, None, False))
    if c.noise is not None:
        cases.append(("noise=off", {}, "ja", False, None, False))
    if heated(c):
        cases.append(("heaters=cold", {}, "ja", None, "cold", False))
        mains = c.mains["v_rms"] if c.mains else None
        if mains:  # the heater's ratio follows the mains setting
            lo = c.controls[mains]["min"]
            cases.append((f"heaters, {mains}={lo}", {mains: lo}, "ja", None, "warm", False))

    def reduced(e) -> bool:  # a tape part naming its reduction, or a switch holding one
        if not isinstance(e, dict):
            return False
        if "tape" in e and "reduction" in e:
            return True
        return "switch" in e and any(reduced(x) for x in (e.get("parts") or {}).values())

    reduced_tape = any(reduced(e) for s in c.sections for e in s["parts"].values())
    if any("events" in e for e in c.devices.values()) or reduced_tape:
        # Thyratrons as event kernels (H3); a tape playing its reduction (DELAY_PLAN.md).
        cases.append(("events", {}, "ja", None, None, True))
    # The other speed's tape and BIAS through the map: the mono echo's only (each case embeds
    # the whole reduction; the 351-2's tape parts are the echo's, generated by one script).
    sweep_reduction = reduced_tape and name not in REDUCTION_DEFAULT_ONLY
    if sweep_reduction and "speed" in c.controls:  # the 351's other tape and its reduction
        cases.append(("events, speed=0", {"speed": 0}, "ja", None, None, True))
    if sweep_reduction and "bias_adjust_f" in c.controls:  # BIAS through the map
        for f in (18e-12, 100e-12):
            cases.append(
                (f"events, bias_adjust_f={f:g}", {"bias_adjust_f": f}, "ja", None, None, True)
            )
    out = []
    for case, overrides, cores, noise, heat, events in cases:
        ir = ir_dict(c, overrides, cores, noise, heat, events)
        for k in ("version", "title", "input_node", "probes"):
            assert ir[k] == default[k], (name, case, k)
        assert len(ir["sections"]) == len(default["sections"]), (name, case)
        entry: dict[str, Any] = {"name": case, "overrides": overrides, "cores": cores}
        if noise is not None:
            entry["noise"] = noise  # the build's setting: a seed, or false
        if heat is not None:
            entry["heaters"] = heat  # the build's setting: warm or cold
        if events:
            entry["events"] = True
        if ir.get("heaters") != default.get("heaters"):
            entry["heaters_block"] = ir.get("heaters")
        if ir.get("noise") != default.get("noise"):
            entry["noise_block"] = ir.get("noise")  # null: none
        entry["sections"] = {
            str(i): s for i, s in enumerate(ir["sections"]) if s != default["sections"][i]
        }
        if ir["models"] != default["models"]:
            entry["models"] = ir["models"]
        out.append(entry)
    return {"circuit": name, "default": default, "cases": out}


def fixture_json(name: str) -> str:
    return json.dumps(fixture(name), indent=None, separators=(",", ":"), allow_nan=False) + "\n"


def main() -> None:
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    names = circuit_names()
    for old in FIXTURE_DIR.glob("*.json"):
        if old.stem not in names:
            old.unlink()
    for name in names:
        path = FIXTURE_DIR / f"{name}.json"
        path.write_bytes(fixture_json(name).encode("utf-8"))
        n = len(json.loads(path.read_text(encoding="utf-8"))["cases"])
        print(f"{path.name}: {n} cases, {path.stat().st_size // 1024} kB")


if __name__ == "__main__":
    main()
