import json

import numpy as np
import pytest
import soundfile as sf

from varimu.cli import main
from varimu.measure import signals as S

NAMES = ["smpte_-10dbfs", "multitone_-10dbfs", "ess_-30dbfs"]


def test_signals_command_writes_manifest_and_wavs(tmp_path):
    assert main(["signals", "--out", str(tmp_path), "--seed", "3", "--only", *NAMES]) == 0
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    assert manifest["seed"] == 3
    assert [e["name"] for e in manifest["signals"]] == [
        s.name for s in S.default_library() if s.name in NAMES
    ]

    for entry in manifest["signals"]:
        for key, fname in entry["files"].items():
            data, sr = sf.read(tmp_path / fname, dtype="float32")
            assert sr == manifest["sample_rate"]
            assert S.sha256(data) == entry["sha256"][key]
    assert "inverse" in next(e for e in manifest["signals"] if e["name"] == "ess_-30dbfs")["files"]


def test_signals_command_is_reproducible(tmp_path):
    main(["signals", "--out", str(tmp_path / "a"), "--only", "multitone_-10dbfs"])
    main(["signals", "--out", str(tmp_path / "b"), "--only", "multitone_-10dbfs"])
    a, _ = sf.read(tmp_path / "a" / "multitone_-10dbfs.wav")
    b, _ = sf.read(tmp_path / "b" / "multitone_-10dbfs.wav")
    assert np.array_equal(a, b)


def test_unknown_signal_name_is_an_error(tmp_path):
    with pytest.raises(SystemExit, match="unknown signal"):
        main(["signals", "--out", str(tmp_path), "--only", "nope"])


def test_genome_status_runs(capsys):
    assert main(["genome-status"]) == 0
    assert "genome parameters resolved" in capsys.readouterr().out
