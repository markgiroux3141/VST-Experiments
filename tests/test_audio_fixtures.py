"""The native app's resampling fixtures are current (docs/NATIVE_APP_PLAN.md, R2).

crates/varimu-app's resampler is compared bit for bit with scipy's `resample_poly` on
them (tests/resample.rs). Another scipy or numpy can change its output: rerun
`uv run python scripts/export_audio_fixtures.py`, then `cargo test -p varimu-app`."""

from __future__ import annotations

import importlib.util

from varimu.config import REPO_ROOT

_path = REPO_ROOT / "scripts" / "export_audio_fixtures.py"
_spec = importlib.util.spec_from_file_location(_path.stem, _path)
export = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(export)


def test_resample_fixture_is_current():
    assert export.FIXTURE.read_bytes().decode("utf-8") == export.fixture_json(), (
        "stale: run scripts/export_audio_fixtures.py"
    )
