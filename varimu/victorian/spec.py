"""The Victorian synth's values (config/victorian/*.yaml): every value `{value, source}`.

`load(name)` returns config/victorian/<name>.yaml as nested dicts (checked: every value has
a source); `v(d, "reed.youngs_pa")` reads a value by its dotted path.
"""

from __future__ import annotations

import functools
from pathlib import Path
from typing import Any

import yaml

from varimu.config import CONFIG_DIR, ConfigError

VICTORIAN_DIR = CONFIG_DIR / "victorian"


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


def load(name: str = "reeds", root: Path = VICTORIAN_DIR) -> dict[str, Any]:
    return _load(Path(root) / f"{name}.yaml")


def v(d: dict[str, Any], dotted: str) -> Any:
    x: Any = d
    for k in dotted.split("."):
        x = x[k]
    return x["value"]
