"""The Nickel Organ's values (config/nickel/organ.yaml): every value `{value, source}`.

`load()` returns the file as nested dicts; `v(d, "bar.youngs_pa")` reads a value by its
dotted path (and fails loudly when it has no source).
"""

from __future__ import annotations

import functools
from pathlib import Path
from typing import Any

import yaml

from varimu.config import CONFIG_DIR, ConfigError

ORGAN_FILE = CONFIG_DIR / "nickel" / "organ.yaml"


@functools.cache
def _load(path: Path) -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        d = yaml.safe_load(f)
    _check(d, path.name)
    return d


def _check(d: Any, where: str) -> None:
    if isinstance(d, dict):
        if "value" in d:
            if not str(d.get("source", "")).strip():
                raise ConfigError(f"{where}: a value without a source")
            return
        for k, x in d.items():
            _check(x, f"{where}.{k}")


def load(path: Path = ORGAN_FILE) -> dict[str, Any]:
    return _load(Path(path))


def v(d: dict[str, Any], dotted: str) -> Any:
    x: Any = d
    for k in dotted.split("."):
        x = x[k]
    return x["value"]
