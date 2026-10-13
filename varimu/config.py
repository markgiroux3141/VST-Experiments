"""Loading and validation for the files in config/.

Genome bounds are validated strictly. Every parameter needs a `source`, and a
range or a set of choices. "TBD" is accepted for any of these, so the skeleton
can exist before the values are known. An unsourced number never is.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = REPO_ROOT / "config"
DATA_DIR = REPO_ROOT / "data"

TBD = "TBD"


class ConfigError(ValueError):
    """A config file is malformed or violates the provenance rules."""


def _load_yaml(path: Path) -> Any:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


# --- sim_settings.yaml -------------------------------------------------------


@dataclass(frozen=True)
class SimSettings:
    sample_rate: int
    seed: int
    data: Mapping[str, Any]  # the full file, for sections later phases consume


def load_sim_settings(path: Path | None = None) -> SimSettings:
    path = path or CONFIG_DIR / "sim_settings.yaml"
    data = _load_yaml(path) or {}
    try:
        sample_rate, seed = data["sample_rate"], data["seed"]
    except KeyError as e:
        raise ConfigError(f"{path}: missing required key {e}") from None
    if not isinstance(sample_rate, int) or sample_rate <= 0:
        raise ConfigError(f"{path}: sample_rate must be a positive integer")
    if not isinstance(seed, int):
        raise ConfigError(f"{path}: seed must be an integer")
    return SimSettings(sample_rate=sample_rate, seed=seed, data=data)


# --- genome_bounds.yaml ------------------------------------------------------


@dataclass(frozen=True)
class ParamBound:
    path: str  # dotted ID, e.g. "tubes.v6386_a.emission_scale"
    source: str
    min: float | str | None = None
    max: float | str | None = None
    choices: tuple[Any, ...] | str | None = None
    unit: str | None = None
    notes: str | None = None

    @property
    def is_choice(self) -> bool:
        return self.choices is not None

    @property
    def resolved(self) -> bool:
        """True once the bounds and their source are all known."""
        if self.source == TBD:
            return False
        if self.is_choice:
            return self.choices != TBD
        return TBD not in (self.min, self.max)


_PARAM_KEYS = {"min", "max", "choices", "source", "unit", "notes"}


def _is_number(x: Any) -> bool:
    return isinstance(x, int | float) and not isinstance(x, bool)


def _parse_param(path: str, node: Mapping[str, Any], errors: list[str]) -> ParamBound | None:
    unknown = set(node) - _PARAM_KEYS
    if unknown:
        errors.append(f"{path}: unknown keys {sorted(unknown)}")

    source = node.get("source")
    if not isinstance(source, str) or not source.strip():
        errors.append(f"{path}: `source` must be a non-empty string (use TBD if unknown)")
        return None

    has_range = "min" in node or "max" in node
    has_choices = "choices" in node
    if has_range == has_choices:
        errors.append(f"{path}: needs either min/max or choices, not both or neither")
        return None

    if has_choices:
        choices = node["choices"]
        if choices != TBD and not (isinstance(choices, list) and choices):
            errors.append(f"{path}: `choices` must be a non-empty list or TBD")
            return None
        return ParamBound(
            path,
            source,
            choices=tuple(choices) if isinstance(choices, list) else choices,
            notes=node.get("notes"),
        )

    lo, hi = node.get("min"), node.get("max")
    for name, v in (("min", lo), ("max", hi)):
        if not (_is_number(v) or v == TBD):
            errors.append(f"{path}: `{name}` must be a number or TBD, got {v!r}")
            return None
    if _is_number(lo) and _is_number(hi) and lo > hi:
        errors.append(f"{path}: min ({lo}) > max ({hi})")
        return None
    return ParamBound(path, source, min=lo, max=hi, unit=node.get("unit"), notes=node.get("notes"))


def _walk(prefix: str, node: Any, out: dict[str, ParamBound], errors: list[str]) -> None:
    if not isinstance(node, Mapping):
        errors.append(f"{prefix or '<root>'}: expected a mapping, got {type(node).__name__}")
        return
    if "source" in node:
        param = _parse_param(prefix, node, errors)
        if param is not None:
            out[prefix] = param
        return
    for key, child in node.items():
        _walk(f"{prefix}.{key}" if prefix else str(key), child, out, errors)


def parse_genome_bounds(data: Any) -> dict[str, ParamBound]:
    """Flatten and validate a genome-bounds tree. Raises ConfigError listing every problem."""
    params: dict[str, ParamBound] = {}
    errors: list[str] = []
    _walk("", data or {}, params, errors)
    if errors:
        raise ConfigError("invalid genome bounds:\n  " + "\n  ".join(errors))
    return params


def load_genome_bounds(path: Path | None = None) -> dict[str, ParamBound]:
    return parse_genome_bounds(_load_yaml(path or CONFIG_DIR / "genome_bounds.yaml"))
