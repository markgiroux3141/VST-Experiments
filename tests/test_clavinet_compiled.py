"""The Clavinet's strings compiled for circuitsim (docs/CLAVINET_PLAN.md, CL3): the component
version is what the code compiles, its files are pinned, and circuitsim's clavinet medium
plays them as the Python twin (varimu/clavinet/live.py) does."""

from __future__ import annotations

import json

import numpy as np
import pytest

from varimu.clavinet import compile as cc
from varimu.clavinet import live
from varimu.devices import versions

circuitsim = pytest.importorskip("circuitsim")

FS = 96000.0


def _db(err: np.ndarray, ref: np.ndarray) -> float:
    return float(20 * np.log10(np.sqrt(np.mean(err**2)) / np.sqrt(np.mean(ref**2))))


def _latest() -> str:
    have = versions.versions(cc.COMPONENT)
    assert have, "no D6_STRINGS: run scripts/compile_clavinet_strings.py"
    return f"{cc.COMPONENT}@{have[-1]}"


def test_the_saved_strings_are_what_the_code_compiles():
    assert cc.is_current(_latest(), cc.compile_strings()), (
        "the instrument, the fits or the compiler changed: save the next version "
        "(scripts/compile_clavinet_strings.py) and move the circuits to it"
    )


def test_a_version_refuses_files_that_dont_match(tmp_path, monkeypatch):
    ref = _latest()
    r = versions.parse(ref)
    src = versions.COMPONENT_DIR / r.folder
    folder = tmp_path / r.folder
    folder.mkdir()
    n = r.version
    (folder / f"{n}.yaml").write_bytes((src / f"{n}.yaml").read_bytes())
    (folder / f"{n}{cc.HEADER_SUFFIX}").write_bytes((src / f"{n}{cc.HEADER_SUFFIX}").read_bytes())
    (folder / f"{n}{cc.BINARY_SUFFIX}").write_bytes(b"\0" * 64)
    lock = versions.read_lock()
    versions.write_lock({r.folder: lock[r.folder]}, tmp_path)
    monkeypatch.setattr(versions, "COMPONENT_DIR", tmp_path)
    with pytest.raises(versions.VersionError, match="sidecar"):
        cc.load_data(ref)
    (folder / f"{n}{cc.HEADER_SUFFIX}").write_text('{"tampered": true}\n', encoding="utf-8")
    with pytest.raises(versions.VersionError, match="doesn't match"):
        cc.load_data(ref)


def _element(ref: str, rate_hz: float = 96000.0) -> dict:
    data, sha = cc.ir_data(ref)
    return {
        "name": "VSTRINGS",
        "centre": "ec",
        "bridge": "eb",
        "bridge_neg": "ebn",
        "rate_hz": rate_hz,
        "contact_rate_hz": 96000.0 * 16,
        "data": data,
        "sha256": sha,
    }


# (step, event): chords struck, a pressure, a key released mid-strike, a re-strike while
# its release still rings, a re-strike of a held key, keys released.
EVENTS = [
    (100, ("on", 41, 100)),
    (103, ("on", 48, 64)),
    (106, ("on", 29, 127)),
    (2500, ("pressure", 90)),
    (3000, ("on", 88, 120)),
    (3050, ("off", 88)),
    (5000, ("off", 41)),
    (5300, ("on", 41, 30)),
    (7000, ("on", 48, 110)),
    (9000, ("off", 41)),
    (9000, ("off", 48)),
    (9500, ("off", 29)),
    (9600, ("pressure", 0)),
]
N = 14000


def _notes():
    out = []
    for at, ev in EVENTS:
        if ev[0] == "pressure":
            out.append((at, "pressure", 0, ev[1]))
        else:
            out.append((at, ev[0], ev[1], ev[2] if len(ev) > 2 else 0))
    return out


@pytest.fixture(scope="module")
def saved():
    ref = _latest()
    header, arrays = cc.load_data(ref)
    return ref, header, arrays


def test_rust_plays_the_strings_as_the_twin_does(saved):
    ref, header, arrays = saved
    el = json.dumps(_element(ref))
    yc, yb, rc, rb, (k, s) = circuitsim.clav_render(el, FS, N, _notes(), 0)
    assert (k, s) == (1, 16)
    twin = live.Strings(header, arrays, FS)
    tw = twin.render((N - 1) * k, [(at * k, ev) for at, ev in EVENTS])
    for raw, t in ((rc, tw[0]), (rb, tw[1])):
        assert raw.size == t.size + 1 and raw[0] == 0.0
        assert np.max(np.abs(t)) > 1e-3, "it sounds"
        assert _db(raw[1:] - t, t) < -120
    np.testing.assert_array_equal(yc, rc[: yc.size])


def test_the_threads_dont_change_a_sample(saved):
    ref, _, _ = saved
    el = json.dumps(_element(ref))
    one = circuitsim.clav_render(el, FS, N, _notes(), 0)
    three = circuitsim.clav_render(el, FS, N, _notes(), 3)
    for a, b in zip(one[:4], three[:4], strict=True):
        np.testing.assert_array_equal(a, b)


def test_at_twice_the_rate_it_decimates(saved):
    ref, header, arrays = saved
    el = json.dumps(_element(ref, rate_hz=192000.0))
    yc, yb, rc, rb, (k, s) = circuitsim.clav_render(el, FS, 4000, _notes()[:3], 0)
    assert (k, s) == (2, 8)
    twin = live.Strings(header, arrays, FS, rate_hz=192000.0)
    tw = twin.render(3999 * k, [(at * k, ev) for at, ev in EVENTS[:3]])
    assert _db(rc[1:] - tw[0], tw[0]) < -120
    assert np.max(np.abs(yc)) > 1e-3
