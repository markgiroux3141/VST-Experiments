"""Room presets: rooms ready to record in, one file each in `config/rooms/<name>.yaml`
(`title`, `description`, `room`: a scene's room block, varimu/rooms/scene.py's docstring).

A scene names one as `room: {preset: treated_studio}`; any other key there replaces the
preset's (`room: {preset: brick_drum_room, ceiling: {type: flat, height_m: 3.6}}`). The
native app's Room view lists the same files (varimu-app `room::load_presets`).

Five are scripts/room_demo.py's rooms (shoebox, splayed_gable, angled, vaulted_hall,
treated_studio); the rest show per-face materials (ROOM_LOOP_PLAN.md R7), treatments,
the tabulated hard surfaces (varimu.rooms.materials TABULATED) and objects (R11).
"""

from __future__ import annotations

import copy
from pathlib import Path

import yaml

from varimu.config import CONFIG_DIR

PRESET_DIR = CONFIG_DIR / "rooms"


def path(name: str) -> Path:
    return PRESET_DIR / f"{name}.yaml"


def names() -> list[str]:
    """Every preset's name, sorted."""
    return sorted(p.stem for p in PRESET_DIR.glob("*.yaml"))


def load(name: str) -> dict:
    """A preset's file: {title, description, room}."""
    p = path(name)
    if not p.exists():
        raise ValueError(f"unknown room preset {name!r}: one of {names()}")
    return yaml.safe_load(p.read_text(encoding="utf-8"))


def room(name: str) -> dict:
    """A preset's room block (a copy)."""
    return copy.deepcopy(load(name)["room"])


def resolve(r: dict) -> dict:
    """A scene's room block with its `preset` (if any) filled in, its own keys on top."""
    if "preset" not in r:
        return r
    return {**room(str(r["preset"])), **{k: v for k, v in r.items() if k != "preset"}}
