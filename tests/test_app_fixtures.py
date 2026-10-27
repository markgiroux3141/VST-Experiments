"""The native app's circuit-builder fixtures are current (docs/NATIVE_APP_PLAN.md, R1).

crates/varimu-circuit's agreement test compares the Rust builder with these IRs, built by
the Python builder (the reference) from config/circuits/. A change to a circuit file, a
device file, a material or the builder makes them stale: rerun
`uv run python scripts/export_app_fixtures.py` and review the diff."""

from __future__ import annotations

import importlib.util

import pytest

from varimu.config import REPO_ROOT

_path = REPO_ROOT / "scripts" / "export_app_fixtures.py"
_spec = importlib.util.spec_from_file_location(_path.stem, _path)
export = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(export)


def test_every_circuit_has_a_fixture():
    have = sorted(p.stem for p in export.FIXTURE_DIR.glob("*.json"))
    assert have == export.circuit_names(), "stale: run scripts/export_app_fixtures.py"


@pytest.mark.parametrize("name", export.circuit_names())
def test_fixture_is_current(name):
    path = export.FIXTURE_DIR / f"{name}.json"
    assert path.read_bytes().decode("utf-8") == export.fixture_json(name), (
        f"{path.name} is stale: run scripts/export_app_fixtures.py"
    )
