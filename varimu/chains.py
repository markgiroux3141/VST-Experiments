"""The chain list as data: `config/chains.yaml` (docs/CHAINS_PLAN.md, WP0).

The file's header comment is the format. `load()` reads and checks it (unknown kinds,
stages or needs, duplicate tags, an id that isn't its stages' tags joined by "_", a
built circuit without its port: `ValueError`). A circuit is *built* when its circuit
file exists and its entry has its port (a mic's `output`, a booster's or preamp's
`input`); a chain is *available* when every stage is built. Its composed file
(`config/circuits/<id>.yaml`, scripts/compose_chain.py) is what the room and the app
render.

Nothing here is in the render cache key: the list says which chains exist, not how they
sound.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from varimu.config import CONFIG_DIR

CHAINS_PATH = CONFIG_DIR / "chains.yaml"
KINDS = ("mic", "booster", "pre")
# What the Room view draws (varimu-app room::PATTERN_NAMES, the same names): a first-order
# figure a + (1 - a) cos(theta) per name, by its coefficient a.
PATTERNS = {
    "omni": 1.0,
    "wide omni": 0.875,
    "wide cardioid": 0.75,
    "broad cardioid": 0.625,
    "cardioid": 0.5,
    "supercardioid": 0.375,
    "hypercardioid": 0.25,
    "narrow figure-8": 0.125,
    "figure-8": 0.0,
}
PORT = {"mic": "output", "booster": "input", "pre": "input"}


@dataclass(frozen=True)
class Setting:
    key: str  # the circuit file's key, unsuffixed
    label: str
    choices: tuple[tuple[float, str], ...]
    default: float


@dataclass(frozen=True)
class Circuit:
    name: str  # config/circuits/<name>.yaml
    kind: str
    tag: str
    label: str
    output: str | None = None
    input: str | None = None
    drop: tuple[str, ...] = ()
    settings: tuple[Setting, ...] = ()
    pattern: str | dict | None = None  # a mic's: a PATTERNS name, or {setting: KEY}
    wp: int | None = None

    @property
    def path(self) -> Path:
        return CONFIG_DIR / "circuits" / f"{self.name}.yaml"

    @property
    def built(self) -> bool:
        return self.path.is_file() and getattr(self, PORT[self.kind]) is not None


@dataclass(frozen=True)
class ChainSetting:
    key: str  # the chain's key (the circuit's, suffixed with its tag)
    label: str
    choices: tuple[tuple[float, str], ...]
    default: float


@dataclass(frozen=True)
class Chain:
    id: str
    stages: tuple[Circuit, ...]  # mic, [booster,] pre
    use: str
    needs: tuple[str, ...]
    needs_note: str | None = None
    defaults: dict[str, float] = field(default_factory=dict)

    @property
    def mic(self) -> Circuit:
        return self.stages[0]

    @property
    def pre(self) -> Circuit:
        return self.stages[-1]

    @property
    def booster(self) -> Circuit | None:
        return self.stages[1] if len(self.stages) == 3 else None

    @property
    def label(self) -> str:
        return " → ".join(s.label for s in self.stages)

    @property
    def available(self) -> bool:
        return all(s.built for s in self.stages)

    @property
    def missing(self) -> tuple[Circuit, ...]:
        return tuple(s for s in self.stages if not s.built)

    @property
    def path(self) -> Path:
        return CONFIG_DIR / "circuits" / f"{self.id}.yaml"

    def settings(self) -> list[ChainSetting]:
        """What the Room view offers for this chain, mic's first, in the chain's keys."""
        out = []
        for s in self.stages:
            for st in s.settings:
                key = f"{st.key}_{s.tag}"
                out.append(
                    ChainSetting(key, st.label, st.choices, self.defaults.get(key, st.default))
                )
        return out


@dataclass(frozen=True)
class ChainList:
    needs: dict[str, dict[str, Any]]
    circuits: dict[str, Circuit]
    chains: tuple[Chain, ...]

    def chain(self, chain_id: str) -> Chain:
        for c in self.chains:
            if c.id == chain_id:
                return c
        raise KeyError(chain_id)

    def available(self) -> list[Chain]:
        return [c for c in self.chains if c.available]


def _setting(d: dict) -> Setting:
    choices = tuple((float(v), str(lbl)) for v, lbl in d["choices"])
    default = float(d["default"])
    if default not in {v for v, _ in choices}:
        raise ValueError(f"setting {d['key']}: default {default} isn't a choice")
    return Setting(str(d["key"]), str(d["label"]), choices, default)


def _check_pattern(c: Circuit) -> None:
    if c.kind != "mic" or c.output is None:
        return
    if isinstance(c.pattern, dict):
        st = next((s for s in c.settings if s.key == c.pattern.get("setting")), None)
        if st is None or any(lbl not in PATTERNS for _, lbl in st.choices):
            raise ValueError(f"{c.name}: pattern {c.pattern} isn't a setting of patterns")
    elif c.pattern not in PATTERNS:
        raise ValueError(f"{c.name}: a built mic's pattern is one of {list(PATTERNS)} or a setting")


def load(path: Path = CHAINS_PATH) -> ChainList:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    needs = dict(raw["needs"])
    circuits: dict[str, Circuit] = {}
    tags: dict[str, str] = {}
    for name, d in raw["circuits"].items():
        if d["kind"] not in KINDS:
            raise ValueError(f"{name}: kind {d['kind']!r} isn't one of {KINDS}")
        if d["tag"] in tags:
            raise ValueError(f"{name}: tag {d['tag']!r} is {tags[d['tag']]}'s too")
        tags[d["tag"]] = name
        c = Circuit(
            name=name,
            kind=d["kind"],
            tag=str(d["tag"]),
            label=str(d["label"]),
            output=d.get("output"),
            input=d.get("input"),
            drop=tuple(d.get("drop") or ()),
            settings=tuple(_setting(s) for s in d.get("settings") or ()),
            pattern=d.get("pattern"),
            wp=d.get("wp"),
        )
        if getattr(c, PORT[c.kind]) is None and c.wp is None:
            raise ValueError(f"{name}: neither its {PORT[c.kind]} port nor the WP building it")
        _check_pattern(c)
        circuits[name] = c
    chains = []
    ids = set()
    for d in raw["chains"]:
        stages = []
        for kind in KINDS:
            if kind in d:
                c = circuits[d[kind]]
                if c.kind != kind:
                    raise ValueError(f"{d['id']}: {c.name} is a {c.kind}, not a {kind}")
                stages.append(c)
        if stages[0].kind != "mic" or stages[-1].kind != "pre":
            raise ValueError(f"{d['id']}: a chain is a mic, an optional booster and a preamp")
        expected = "_".join(s.tag for s in stages)
        if d["id"] != expected:
            raise ValueError(f"chain {d['id']!r}: its stages' tags make {expected!r}")
        if d["id"] in ids:
            raise ValueError(f"chain {d['id']!r} is listed twice")
        ids.add(d["id"])
        for n in d["needs"]:
            if n not in needs:
                raise ValueError(f"{d['id']}: need {n!r} isn't in `needs`")
        chain = Chain(
            id=d["id"],
            stages=tuple(stages),
            use=str(d["use"]),
            needs=tuple(d["needs"]),
            needs_note=d.get("needs_note"),
            defaults={k: float(v) for k, v in (d.get("defaults") or {}).items()},
        )
        known = {s.key for s in chain.settings()}
        for k, v in chain.defaults.items():
            if k not in known:
                raise ValueError(f"{d['id']}: default {k!r} isn't one of its settings")
            st = next(s for s in chain.settings() if s.key == k)
            if v not in {x for x, _ in st.choices}:
                raise ValueError(f"{d['id']}: default {k} = {v} isn't a choice")
        chains.append(chain)
    return ChainList(needs, circuits, tuple(chains))
