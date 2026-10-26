"""Circuit files: parameters with sources, devices, parts (device builder, B1).

A circuit file (config/circuits/*.yaml) describes one circuit for
varimu.circuit.builder, which expands its parts with the parts library
(varimu.circuit.parts) into the circuit IR. Top-level keys:

    title: ...                      # the IR's title
    input: in                       # the node the audio input drives
    probes: [out, cv, ...]          # node voltages every render saves
    controls: {key: {value, min, max | choices, source, unit?, notes?}}
    values: {key: {value, source, genome?, unit?, notes?}}
    device_params: {key: {value, source, genome?}}   # act on device instances
    derived: {module: python.module, values: {key: {source}}}
    mains: {v_rms: <control>, hz: <control>, rated_v_rms: <param or {value, source}>}
    tolerance: {source, seed, spread, tube: {emission_pct, mu_pct}, bands, classes, combined}
    devices: {key: {device, ...}}   # device model instances, in IR model order
    sections: [{title, tolerance?, parts: {NAME: {<macro>: <nodes>, ...}}}]

Parameters (controls, values, device_params, derived) are what parts refer to by
key; every one has a `source` (CLAUDE.md, hard rules), and `--set` overrides
any control, value or device parameter. A control has `min` and `max`, or
`choices` (a switch's positions, e.g. its frequencies); one with `unit: position`
is an integer switch position. Values linked to the genome (`genome:`) have their
bounds in config/genome_bounds.yaml. A device parameter may be null: the
device file's value. Derived values are functions of the resolved parameters,
named in the file with their source and computed by the module's function of
the same name (for arithmetic the parts can't express, e.g. lumping parallel
parts); they can't be overridden.

Parts and devices are read by varimu.circuit.builder (its docstring has the
macro parts and their parameters).
"""

from __future__ import annotations

import copy
import dataclasses
import functools
import importlib
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from varimu.config import ConfigError, load_genome_bounds

# PyYAML reads 1.0e6 (no sign in the exponent) as a string: such a value is an error.
_NUMBER_LIKE = re.compile(r"[-+]?(\d+\.?\d*|\.\d+)([eE][-+]?\d+)?")
_TOP_KEYS = {
    "title",
    "input",
    "probes",
    "controls",
    "values",
    "device_params",
    "derived",
    "mains",
    "tolerance",
    "devices",
    "sections",
}


@dataclass(frozen=True)
class CircuitSpec:
    controls: dict[str, dict[str, Any]]
    values: dict[str, dict[str, Any]]
    parts: dict[str, Any] = dataclasses.field(default_factory=dict)  # the tolerance block
    device_params: dict[str, dict[str, Any]] = dataclasses.field(default_factory=dict)
    title: str = ""
    input_node: str = "in"
    probes: tuple[str, ...] = ()
    mains: dict[str, Any] | None = None
    derived: dict[str, Any] = dataclasses.field(default_factory=dict)
    devices: dict[str, dict[str, Any]] = dataclasses.field(default_factory=dict)
    sections: tuple[dict[str, Any], ...] = ()
    path: Path | None = None

    def part_classes(self) -> dict[str, str]:
        """Designator -> tolerance class."""
        return {d: c for c, ds in self.parts.get("classes", {}).items() for d in ds}

    def defaults(self) -> dict[str, Any]:
        d = {k: e["value"] for k, e in self.controls.items()}
        d.update({k: e["value"] for k, e in self.values.items()})
        d.update({k: e["value"] for k, e in self.device_params.items() if e["value"] is not None})
        return d

    def parameter_keys(self) -> set[str]:
        """Every key `--set` takes."""
        return set(self.controls) | set(self.values) | set(self.device_params)

    def derived_keys(self) -> set[str]:
        return set(self.derived.get("values", {}))

    def derive(self, p: Mapping[str, Any]) -> dict[str, Any]:
        """The derived values for resolved parameters `p`."""
        names = self.derived_keys()
        if not names:
            return {}
        module = importlib.import_module(self.derived["module"])
        return {k: getattr(module, k)(p) for k in names}


def _sourced(where: str, e: Any, errors: list[str], *, allow_null: bool = False) -> None:
    if not isinstance(e, Mapping) or "value" not in e:
        errors.append(f"{where}: needs a `value`")
    elif not str(e.get("source", "")).strip():
        errors.append(f"{where}: needs a `source`")
    elif e["value"] is None and not allow_null:
        errors.append(f"{where}: value is null")
    elif isinstance(e["value"], str) and _NUMBER_LIKE.fullmatch(e["value"].strip()):
        errors.append(f"{where}: value {e['value']!r} is not a number (write 1.0e+6, not 1.0e6)")


@functools.lru_cache(maxsize=16)
def _parse(path: Path, mtime_ns: int, size: int) -> Any:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_circuit(path: Path) -> CircuitSpec:
    """Read and check a circuit file (parameters and their sources, the tolerance block,
    the shape of devices and sections; the builder checks the parts). Raises ConfigError.
    The parse is cached per (path, modification time, size); each call gets its own copy."""
    path = Path(path).resolve()
    st = path.stat()
    data = copy.deepcopy(_parse(path, st.st_mtime_ns, st.st_size))
    errors: list[str] = []
    unknown = set(data) - _TOP_KEYS
    if unknown:
        errors.append(f"unknown top-level keys {sorted(unknown)}")
    controls = data.get("controls") or {}
    values = data.get("values") or {}
    device_params = data.get("device_params") or {}
    for k, e in controls.items():
        _sourced(f"controls.{k}", e, errors)
        if isinstance(e, Mapping) and not ({"min", "max"} <= set(e) or "choices" in e):
            errors.append(f"controls.{k}: needs `min` and `max`, or `choices`")
        elif isinstance(e, Mapping) and "choices" in e and e.get("value") not in e["choices"]:
            errors.append(f"controls.{k}: value {e.get('value')!r} not in its choices")
    for k, e in values.items():
        _sourced(f"values.{k}", e, errors)
    for k, e in device_params.items():
        _sourced(f"device_params.{k}", e, errors, allow_null=True)
    derived = data.get("derived") or {}
    if derived:
        if not derived.get("module"):
            errors.append("derived: needs a `module`")
        for k, e in (derived.get("values") or {}).items():
            if not isinstance(e, Mapping) or not str(e.get("source", "")).strip():
                errors.append(f"derived.values.{k}: needs a `source`")
    keys = [*controls, *values, *device_params, *(derived.get("values") or {})]
    dupes = sorted({k for k in keys if keys.count(k) > 1})
    if dupes:
        errors.append(f"parameters defined twice: {dupes}")

    tol = data.get("tolerance") or {}
    if tol:
        if not str(tol.get("source", "")).strip():
            errors.append("tolerance: needs a `source`")
        for k in ("seed", "spread"):
            if k not in tol:
                errors.append(f"tolerance: needs `{k}` (a parameter key)")
        seen: dict[str, str] = {}
        for c, ds in (tol.get("classes") or {}).items():
            if c not in (tol.get("bands") or {}):
                errors.append(f"tolerance: class {c} has no band")
            for d in ds:
                if d in seen:
                    errors.append(f"tolerance: {d} in both {seen[d]} and {c}")
                seen[d] = c

    sections = data.get("sections") or []
    for i, s in enumerate(sections):
        if not isinstance(s, Mapping) or "title" not in s or "parts" not in s:
            errors.append(f"sections[{i}]: needs `title` and `parts`")
        elif extra := set(s) - {"title", "parts", "tolerance"}:
            errors.append(f"sections[{i}]: unknown keys {sorted(extra)}")
    for k, e in (data.get("devices") or {}).items():
        if not isinstance(e, Mapping) or "device" not in e:
            errors.append(f"devices.{k}: needs a `device`")
    if errors:
        raise ConfigError(f"{path}:\n  " + "\n  ".join(errors))
    return CircuitSpec(
        controls=controls,
        values=values,
        parts=tol,
        device_params=device_params,
        title=data.get("title", ""),
        input_node=data.get("input", "in"),
        probes=tuple(data.get("probes") or ()),
        mains=data.get("mains"),
        derived=derived,
        devices=data.get("devices") or {},
        sections=tuple(sections),
        path=Path(path),
    )


def circuit_path(name: str) -> Path:
    """config/circuits/<name>.yaml (KeyError: no such circuit)."""
    from varimu.config import CONFIG_DIR

    path = CONFIG_DIR / "circuits" / f"{name}.yaml"
    if not path.exists():
        raise KeyError(f"no circuit file {path}")
    return path


def resolve(spec: CircuitSpec, overrides: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Defaults merged with overrides. Unknown keys and out-of-range controls are errors."""
    p = spec.defaults()
    known = spec.parameter_keys()
    for k, v in (overrides or {}).items():
        if k not in known:
            raise KeyError(f"unknown circuit parameter {k!r}")
        p[k] = v
    for k, e in spec.controls.items():
        if "choices" in e:
            if p[k] not in e["choices"]:
                raise ValueError(f"control {k}={p[k]} not one of {e['choices']}")
        elif not e["min"] <= p[k] <= e["max"]:
            raise ValueError(f"control {k}={p[k]} outside [{e['min']}, {e['max']}]")
    for k, e in spec.controls.items():
        if e.get("unit") == "position":
            p[k] = int(p[k])
    return p


def genome_links(spec: CircuitSpec) -> dict[str, str]:
    """Circuit value key -> genome_bounds.yaml path, for the uncertain values."""
    return {k: e["genome"] for k, e in spec.values.items() if "genome" in e}


def check_genome_links(spec: CircuitSpec) -> list[str]:
    """Problems with the circuit <-> genome_bounds links (empty list = fine): values and
    device parameters (a null device parameter's nominal is the device file's)."""
    bounds = load_genome_bounds()
    links = [(k, e["genome"], e["value"]) for k, e in spec.values.items() if "genome" in e]
    links += [(k, e["genome"], e["value"]) for k, e in spec.device_params.items() if "genome" in e]
    problems = []
    for key, path, v in links:
        b = bounds.get(path)
        if b is None:
            problems.append(f"{key}: genome path {path} not in genome_bounds.yaml")
        elif not b.resolved:
            problems.append(f"{key}: genome bounds {path} still TBD")
        elif v is None:
            continue
        elif b.choices is not None:
            if v not in b.choices:
                problems.append(f"{key}: nominal {v!r} not in {list(b.choices)} ({path})")
        elif not b.min <= v <= b.max:
            problems.append(f"{key}: nominal {v} outside [{b.min}, {b.max}] ({path})")
    return problems
