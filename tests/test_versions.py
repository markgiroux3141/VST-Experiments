"""Component versions (docs/COMPONENT_EDITOR_PLAN.md, C1): immutable, pinned by circuits."""

import shutil
from pathlib import Path

import pytest
import yaml

from varimu.circuit import builder
from varimu.circuit.spec import load_circuit
from varimu.config import CONFIG_DIR, ConfigError
from varimu.devices import library, versions
from varimu.devices.versions import Ref, VersionError


def test_references_parse():
    assert versions.parse("12AX7@1") == Ref("12AX7", 1)
    assert versions.parse("6386") == Ref("6386", None)
    assert str(versions.parse("GZ34@12")) == "GZ34@12"
    for bad in ("", "@1", "12AX7@", "12AX7@0", "12AX7@01", "12AX7@x", "a b", "a@1@2"):
        with pytest.raises(VersionError):
            versions.parse(bad)


def test_hash_ignores_line_ends():
    assert versions.text_hash("a\r\nb\n") == versions.text_hash("a\nb\n")


def test_every_saved_version_matches_the_lock():
    lock = versions.read_lock()
    assert lock, "config/components/versions.lock is empty"
    for folder in versions.names():
        for n in versions.versions(folder):
            assert lock[folder][n], f"{folder}@{n} isn't in versions.lock"
            versions.read_text(f"{folder}@{n}")  # raises when the text was edited
    assert set(lock) == set(versions.names())


def test_a_bare_name_is_the_latest_version():
    for folder in versions.names():
        assert versions.resolve(folder).version == versions.versions(folder)[-1]


@pytest.fixture
def store(tmp_path: Path) -> Path:
    """A copy of the component store to change."""
    root = tmp_path / "components"
    shutil.copytree(versions.COMPONENT_DIR, root)
    return root


def test_a_version_edited_after_saving_is_refused(store: Path):
    p = store / "12ax7" / "1.yaml"
    p.write_text(p.read_text(encoding="utf-8").replace("kp:", "kp:  "), encoding="utf-8")
    with pytest.raises(VersionError, match=r"12AX7@1 .* was edited after it was saved"):
        library.load_device("12AX7@1", store)


def test_an_unrecorded_version_is_refused(store: Path):
    shutil.copy(store / "12ax7" / "1.yaml", store / "12ax7" / "2.yaml")
    with pytest.raises(VersionError, match="isn't in versions.lock"):
        library.load_device("12AX7@2", store)


def test_save_makes_the_next_version_and_records_it(store: Path):
    text = (store / "12ax7" / "1.yaml").read_text(encoding="utf-8") + "# a refit\n"
    assert versions.save("12AX7", text, store) == Ref("12AX7", 2)
    assert versions.versions("12ax7", store) == [1, 2]
    assert versions.resolve("12AX7", store) == Ref("12AX7", 2)
    assert versions.read_text("12AX7@2", store)[1] == text
    versions.read_text("12AX7@1", store)  # the old one is untouched
    with pytest.raises(VersionError):
        versions.save("12AX7@3", text, store)


def test_fit_devices_saves_a_version_only_when_a_fit_changes(store: Path, monkeypatch):
    saved = yaml.safe_load((store / "12ax7" / "1.yaml").read_text(encoding="utf-8"))
    monkeypatch.setitem(library.BUILDERS, "12AX7", lambda: dict(saved))
    (what, _), *_ = library.write_devices(["12AX7"], store)
    assert what == "unchanged 12AX7@1"
    assert versions.versions("12ax7", store) == [1]

    refit = dict(saved, source=saved["source"] + " (refit)")
    monkeypatch.setitem(library.BUILDERS, "12AX7", lambda: dict(refit))
    (what, path), *_ = library.write_devices(["12AX7"], store)
    assert what == "saved 12AX7@2"
    assert path == store / "12ax7" / "2.yaml"
    assert versions.read_text("12AX7@1", store)[1] == (store / "12ax7" / "1.yaml").read_text(
        encoding="utf-8"
    )


def test_every_circuit_pins_its_devices():
    """Every device a circuit file names, directly or through a parameter, is NAME@N."""
    for path in sorted((CONFIG_DIR / "circuits").glob("*.yaml")):
        spec = load_circuit(path)
        defaults = spec.defaults()
        for key, e in spec.devices.items():
            ref = str(e["device"])
            ref = str(defaults.get(ref, ref))
            assert versions.parse(ref).version is not None, f"{path.name}: devices.{key} {ref}"


def test_a_circuit_naming_no_version_is_refused(tmp_path: Path):
    text = (CONFIG_DIR / "circuits" / "triode_stage.yaml").read_text(encoding="utf-8")
    assert "{device: 12AX7@1," in text
    p = tmp_path / "unpinned.yaml"
    p.write_text(text.replace("{device: 12AX7@1,", "{device: 12AX7,"), encoding="utf-8")
    with pytest.raises(ConfigError, match=r"devices\.V1: '12AX7' names no version.*12AX7@1"):
        builder.build(load_circuit(p), cores="linear")
