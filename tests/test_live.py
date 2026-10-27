"""Real-time playback (varimu.sim.live) and the Play page's WebSocket (varimu.listen.play)."""

import time

import numpy as np
import pytest

pytest.importorskip("circuitsim", reason="needs `uv sync --extra fast`")

from varimu.config import load_sim_settings  # noqa: E402
from varimu.sim import live  # noqa: E402

FS = load_sim_settings().sample_rate


def _clip(s=1.5, amp=0.5):
    t = np.arange(int(s * FS)) / FS
    return amp * np.sin(2 * np.pi * 220 * t) * np.minimum(1, t / 0.02)


def test_the_loop_seam_is_crossfaded():
    x = np.arange(10000.0)  # the fade: 10 ms at 48 kHz (at most a quarter of the clip)
    y = live.make_loop(x, 48000)
    assert len(y) == 10000 - 480 and y[0] == x[-480] and y[-1] == x[-481]
    assert len(live.make_loop(x[:1000], 48000)) == 750


def test_structure_tells_updates_from_restarts():
    """Values (a pot's position, even across its tap) keep the structure; the pad's 0 dB
    end (one through resistor instead of a T) changes it."""
    from varimu.circuit import netlist as nl

    def s(ov):
        return live.structure(nl.build(ov, cores="linear").ir)

    base = s({"ac_threshold": 0.8, "input_atten_db": 6})
    assert s({"ac_threshold": 0.3, "input_atten_db": 6}) == base
    assert s({"ac_threshold": 0.8, "input_atten_db": 20}) == base
    assert s({"ac_threshold": 0.8, "input_atten_db": 0}) != base


def test_live_plays_and_takes_knob_changes():
    """Blocks of the asked size at the host rate; a lower threshold compresses less (the
    gain rises), applied in place; the pad to 0 dB restarts the stream underneath."""
    p = live.Live(_clip(), {"ac_threshold": 0.9, "input_atten_db": 0.0 + 4})
    try:
        assert p.rate == 48000
        gains = []
        for i in range(120):
            if i == 40:
                p.set({"ac_threshold": 0.1, "input_atten_db": 4})
            if i == 80:
                p.set({"ac_threshold": 0.1, "input_atten_db": 0})
            if i in (40, 80):
                time.sleep(0.5)  # let the background build land (it is real time's job)
            y, m = p.next_block(480)
            assert y.dtype == np.float32 and len(y) == 480 and np.all(np.isfinite(y))
            gains.append(m.gain_db)
        assert p.error is None, p.error
        assert np.mean(gains[60:80]) > np.mean(gains[20:40]) + 1.0, gains
        assert p.restarts == 1
    finally:
        p.close()


def test_the_play_websocket():
    """start -> ready, audio frames (float32 blocks) and meters; set; stop."""
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from varimu.listen import app, play

    sources = app.list_sources()
    src = next((s for s in sources if s.startswith("signal:")), sources[0])
    client = TestClient(app.create_app(workers=1))
    info = client.get("/api/play/info").json()
    knobs = next(d["knobs"] for d in info["devices"] if d["id"] == "fairchild_670")
    assert info["rate"] == 48000 and {k["key"] for k in knobs} == set(play.KNOBS)
    assert client.get("/play").status_code == 200
    assert "registerProcessor" in client.get("/play/worklet.js").text
    with client.websocket_connect("/ws/play") as ws:
        ws.send_json({"cmd": "start", "source": src, "start_s": 0, "seconds": 1.0,
                      "values": {"ac_threshold": 0.7}})  # fmt: skip
        assert ws.receive_json()["type"] == "ready"
        audio = meters = 0
        while audio < 10 or meters < 1:
            m = ws.receive()
            if m.get("bytes") is not None:
                assert len(m["bytes"]) == 4 * play.BLOCK
                audio += 1
            elif '"meter"' in m.get("text", ""):
                meters += 1
            ws.send_json({"cmd": "played", "samples": audio * play.BLOCK})
        ws.send_json({"cmd": "set", "values": {"ac_threshold": 0.2}})
        ws.send_json({"cmd": "stop"})


def test_live_plays_the_eqp1a():
    """The EQP-1A from its circuit file: the low boost turned up raises the level of a
    low tone, in place; a frequency selector that rewires the network restarts."""
    p = live.Live(_clip() * 0.5, {"lf_boost": 0.0, "lf_freq_hz": 60}, circuit="pultec_eqp1a")
    try:
        gains = []
        for i in range(90):
            if i == 30:
                p.set({"lf_boost": 1.0, "lf_freq_hz": 60})
                time.sleep(0.5)
            if i == 60:
                p.set({"lf_boost": 1.0, "lf_freq_hz": 100})
                time.sleep(1.0)
            y, m = p.next_block(480)
            assert len(y) == 480 and np.all(np.isfinite(y)) and m.cv_v is None
            gains.append(m.gain_db)
        assert p.error is None, p.error
        assert np.mean(gains[45:60]) > np.mean(gains[15:30]) + 3.0, gains
    finally:
        p.close()


def test_the_play_page_lists_devices_and_plays_the_eq():
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from varimu.listen import app, play

    client = TestClient(app.create_app(workers=1))
    info = client.get("/api/play/info").json()
    devices = {d["id"]: d for d in info["devices"]}
    assert set(devices) == set(play.DEVICES)
    eq = {k["key"]: k for k in devices["pultec_eqp1a"]["knobs"]}
    assert eq["lf_freq_hz"]["choices"] == [20, 30, 60, 100] and "mains_hz" not in eq
    src = next(s for s in info["sources"] if s.startswith("signal:"))
    with client.websocket_connect("/ws/play") as ws:
        ws.send_json({"cmd": "start", "device": "pultec_eqp1a", "source": src, "start_s": 0,
                      "seconds": 1.0, "values": {"lf_boost": 0.5, "lf_freq_hz": 60}})  # fmt: skip
        assert ws.receive_json()["type"] == "ready"
        assert ws.receive().get("bytes") is not None
        ws.send_json({"cmd": "start", "device": "nope", "source": src})
        while (m := ws.receive()).get("bytes") is not None:
            pass
        assert "unknown device" in m["text"]
        ws.send_json({"cmd": "stop"})
