"""Candidates for blind listening (Phase 5): units as physical genomes, and the parts sandbox.

A candidate is a name and a genome: overrides of the circuit's values and tube
parameters (varimu.circuit.netlist), physical only (the plan's guiding
principles). Front-panel controls are not part of it: a listening condition sets
the Time Constant, and the matching solves AC THRESHOLD (varimu.listen.stimuli).

The pool lives in config/listening.yaml. The parts sandbox makes candidates by
swapping one part's physical property on a base unit (`swap`): any genome
parameter, a choice (a transformer's core material) or a value within its
bounds (`catalog` lists them, with their sources). Both sides of a sandbox pair
are set up and matched the same way as any other pair.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from varimu.circuit import netlist as nl
from varimu.config import CONFIG_DIR, DATA_DIR, load_genome_bounds

POOL_FILE = CONFIG_DIR / "listening.yaml"


@dataclass(frozen=True)
class Candidate:
    name: str
    genome: Mapping[str, Any] = field(default_factory=dict)
    note: str = ""

    @property
    def id(self) -> str:
        """Content address of the genome: two names for one unit are one candidate."""
        text = json.dumps(dict(self.genome), sort_keys=True, default=str)
        return hashlib.sha256(text.encode()).hexdigest()[:12]

    def validate(self) -> None:
        controls = set(nl.load_spec().controls)
        panel = sorted(set(self.genome) & controls)
        if panel:
            raise ValueError(f"candidate {self.name}: front-panel controls {panel} aren't genome")
        nl.resolve(dict(self.genome))  # unknown keys raise


@dataclass(frozen=True)
class Pool:
    candidates: dict[str, Candidate]
    gr_targets_db: tuple[float, ...]
    time_constant: int
    excerpt_s: float
    clips: dict[str, dict[str, Any]]  # file name -> {category, start_s, seconds}


def load_pool(path: Path = POOL_FILE) -> Pool:
    """The pool file; clip settings also from data/clips/clips.yaml (the user's, local)."""
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    clips = dict(data.get("clips") or {})
    local = DATA_DIR / "clips" / "clips.yaml"
    if local.exists():
        clips |= yaml.safe_load(local.read_text(encoding="utf-8")) or {}
    cands = {
        name: Candidate(name, dict(c.get("genome") or {}), str(c.get("note", "")))
        for name, c in data["candidates"].items()
    }
    for c in cands.values():
        c.validate()
    return Pool(
        cands,
        tuple(float(x) for x in data["gr_targets_db"]),
        int(data["time_constant"]),
        float(data["excerpt_s"]),
        clips,
    )


def catalog() -> list[dict[str, Any]]:
    """The parts the sandbox can swap: every genome-linked circuit value, with its
    nominal, its bounds or choices, and its source."""
    spec = nl.load_spec()
    bounds = load_genome_bounds()
    out = []
    for key, path in nl.genome_links(spec).items():
        b = bounds[path]
        out.append(
            {
                "key": key,
                "genome_path": path,
                "nominal": spec.values[key]["value"],
                "choices": list(b.choices) if b.is_choice else None,
                "min": None if b.is_choice else b.min,
                "max": None if b.is_choice else b.max,
                "unit": b.unit,
                "source": b.source,
            }
        )
    return out


def swap(base: Candidate, key: str, value: Any, name: str | None = None) -> Candidate:
    """`base` with one part's property changed: a choice from the catalog, or a value
    within its bounds (out of bounds raises: the genome is physical)."""
    part = {p["key"]: p for p in catalog()}.get(key)
    if part is None:
        raise KeyError(f"{key} is not a swappable part (see candidates.catalog())")
    if part["choices"] is not None:
        if value not in part["choices"]:
            raise ValueError(f"{key}: {value!r} not among {part['choices']}")
    elif not (float(part["min"]) <= float(value) <= float(part["max"])):
        raise ValueError(f"{key}: {value} outside [{part['min']}, {part['max']}]")
    c = Candidate(
        name or f"{base.name}+{key}={value}",
        {**base.genome, key: value},
        f"{base.name} with {key} = {value} (sandbox swap; nominal {part['nominal']})",
    )
    c.validate()
    return c
