"""Balancing a room's sources: their SPL measured while they sound, and the room's responses
cached by geometry so a change of level skips the room's physics (varimu.rooms.scene)."""

from __future__ import annotations

import numpy as np
import pytest

FS = 96000


def test_sounding_rms_ignores_silence():
    from varimu.rooms.scene import sounding_rms

    rng = np.random.default_rng(0)
    tone = np.sin(2 * np.pi * 440 * np.arange(2 * FS) / FS)  # rms 1 / sqrt 2
    padded = np.r_[np.zeros(3 * FS), tone, np.zeros(FS)]
    db = 20 * np.log10(sounding_rms(padded, FS) / np.sqrt(0.5))
    assert db == pytest.approx(0, abs=0.1)
    # a part playing a quarter of the time: its level while it plays (the blocks straddling
    # each note's ends pull it down a little)
    sparse = np.concatenate([np.r_[tone[: FS // 2], np.zeros(3 * FS // 2)]] * 4)
    assert 20 * np.log10(sounding_rms(sparse, FS) / np.sqrt(0.5)) == pytest.approx(0, abs=0.3)
    assert 20 * np.log10(np.sqrt(np.mean(sparse**2)) / np.sqrt(0.5)) < -5  # the plain rms
    noise = rng.standard_normal(4 * FS)
    assert sounding_rms(noise, FS) == pytest.approx(1.0, rel=0.01)
    short = rng.standard_normal(1000)
    assert sounding_rms(short, FS) == pytest.approx(np.sqrt(np.mean(short**2)))
    assert sounding_rms(np.zeros(FS), FS) == 0.0


def test_sounding_rms_matches_the_apps():
    """The numbers crates/varimu-app's room::tests::sounding_rms_matches_python checks."""
    from varimu.rooms.scene import sounding_rms

    fs = 48000
    t = np.arange(3 * fs) / fs
    x = np.where(t < 1.0, 0.0, 0.5 * np.sin(2 * np.pi * 220 * t))
    x[int(2.5 * fs) :] *= 0.01  # a quiet end, under the relative gate
    # the blocks straddling the onset and the quiet end lower it a little from 0.5 / sqrt 2
    assert sounding_rms(x, fs) == pytest.approx(0.350_643_583, abs=1e-9)


def _scene(tmp_path, mic_y=4.0, spl=94):
    import soundfile as sf

    from varimu.rooms.scene import load_scene

    clip = tmp_path / "x.wav"
    sf.write(clip, np.random.default_rng(0).standard_normal(4800).astype("<f4"), FS)
    return load_scene(
        {
            "name": "t",
            "room": {"dims_m": [5, 4, 3], "materials": {"walls": "furnished_wall",
                                                        "floor": "wood_floor",
                                                        "ceiling": "gypsum_on_studs"}},
            "sources": [{"name": "s", "clip": str(clip), "spl_db": spl, "position_m": [2, 2, 1.5]}],
            "mics": [{"name": "m", "chain": "capsule_bk4134", "position_m": [2, mic_y - 1, 1.5],
                      "aim": {"azimuth_deg": -90}}],
            "settings": {"tail_s": 0.2},
        }
    )  # fmt: skip


def test_room_responses_are_cached_by_geometry_not_level(tmp_path, monkeypatch):
    from varimu.rooms import scene as sc

    monkeypatch.setattr(sc, "RESPONSES", tmp_path / "responses")
    lines: list[str] = []
    x = [np.ones(2000)]
    p1, _, _ = sc.mic_pressures(_scene(tmp_path), FS, x, lines.append)
    assert not any("room responses: from the cache" in s for s in lines)
    lines.clear()
    p2, _, _ = sc.mic_pressures(_scene(tmp_path, spl=80), FS, [0.1 * x[0]], lines.append)
    assert any("room responses: from the cache" in s for s in lines)
    np.testing.assert_allclose(p2, 0.1 * p1, atol=1e-12 * np.abs(p1).max())  # audio scaled
    lines.clear()
    sc.mic_pressures(_scene(tmp_path, mic_y=3.5), FS, x, lines.append)  # a mic moved
    assert not any("room responses: from the cache" in s for s in lines)
    assert len(list((tmp_path / "responses").glob("*.npy"))) == 2


def test_the_balance_stems_sum_to_the_render(tmp_path, monkeypatch):
    """Two sources, two mics on the clean omni chain (linear: its proxy is the chain), panned
    apart: the stems scaled by a balance sum to the render at those levels."""
    import json

    import soundfile as sf

    from varimu.rooms import balance
    from varimu.rooms import scene as sc

    monkeypatch.setattr(sc, "RESPONSES", tmp_path / "responses")
    monkeypatch.setattr(sc, "CACHE", tmp_path / "prints")
    rng = np.random.default_rng(1)
    for name in ("a", "b"):
        x = rng.standard_normal(FS // 2) * np.hanning(FS // 2)
        sf.write(tmp_path / f"{name}.wav", x.astype("<f4"), FS)

    def scene(spl_a, spl_b):
        return sc.load_scene(
            {
                "name": "t",
                "room": {"dims_m": [5, 4, 3], "materials": {"walls": "furnished_wall",
                                                            "floor": "wood_floor",
                                                            "ceiling": "gypsum_on_studs"}},
                "sources": [
                    {"name": "a", "clip": str(tmp_path / "a.wav"), "spl_db": spl_a,
                     "position_m": [1.5, 2, 1.5]},
                    {"name": "b", "clip": str(tmp_path / "b.wav"), "spl_db": spl_b,
                     "position_m": [3.5, 2, 1.5]},
                ],
                "mics": [
                    {"name": "ma", "chain": "omni_clean", "position_m": [1.5, 2.6, 1.5],
                     "pan": -0.7},
                    {"name": "mb", "chain": "omni_clean", "position_m": [3.5, 2.6, 1.5],
                     "pan": 0.7},
                ],
                "settings": {"tail_s": 0.3, "quality": "draft"},
            }
        )  # fmt: skip

    data = balance.prepare(scene(90, 90), tmp_path / "bal", log=lambda s: None)
    assert [s["spl_db"] for s in data["sources"]] == [90, 90]
    assert json.loads((tmp_path / "bal" / "balance.json").read_text())["fs"] == FS
    # the balance: b down 9 dB
    gains = [1.0, 10 ** (-9 / 20)]
    mix = sum(
        g * np.stack([sf.read(tmp_path / "bal" / s[k])[0] for k in ("left", "right")])
        for g, s in zip(gains, data["sources"], strict=True)
    )
    sc.render(scene(90, 81), tmp_path / "r", log=lambda s: None)
    ref = sf.read(tmp_path / "r" / "mix.wav")[0].T
    n = min(ref.shape[1], mix.shape[1])
    err = 20 * np.log10(np.std(ref[:, :n] - mix[:, :n]) / np.std(ref[:, :n]))
    assert err < -50, err
    # the peaks: per source and mic, the mic's print's level
    peaks = np.array(data["peaks"])
    assert peaks.shape[:2] == (2, 2)
    assert peaks[0, 0].max() > 1.3 * peaks[0, 1].max()  # a is near ma (omnis, a room)
