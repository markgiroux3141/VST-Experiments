"""The native app's editor fixtures are current (docs/NATIVE_APP_PLAN.md, R3).

crates/varimu-circuit's tests/editor.rs compares the Rust compile path with what Python's
editor makes of every drawn circuit (and of broken copies of one), from these fixtures. A
change to a drawing, a circuit file, a device file, the importer, the editor or the
pre-flight checks makes them stale: rerun `uv run python scripts/export_editor_fixtures.py`
and review the diff."""

from __future__ import annotations

import importlib.util

import pytest

from varimu.config import REPO_ROOT

_path = REPO_ROOT / "scripts" / "export_editor_fixtures.py"
_spec = importlib.util.spec_from_file_location(_path.stem, _path)
export = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(export)


@pytest.fixture(scope="module")
def texts():
    return export.fixtures()


def test_the_fixture_set_is_current(texts):
    have = sorted(p.name for p in export.FIXTURE_DIR.glob("*.json"))
    assert have == sorted(texts), "stale: run scripts/export_editor_fixtures.py"


def test_each_fixture_is_current(texts):
    stale = [n for n, t in texts.items()
             if (export.FIXTURE_DIR / n).read_bytes().decode("utf-8") != t]  # fmt: skip
    assert not stale, f"{stale} are stale: run scripts/export_editor_fixtures.py"
