"""The Play page (`/play`): a clip looped through the circuit in real time while its
front panel turns (varimu.sim.live; CIRCUIT_SIM_PLAN.md M8).

Protocol over the WebSocket `/ws/play` (JSON text one way and the other, audio as
binary frames of float32 samples at the session's rate):

- client: {"cmd": "start", "device", "source", "start_s", "seconds", "values"}, then
  {"cmd": "set", "values"} as knobs turn, {"cmd": "played", "samples"} (samples the
  page has played so far) and {"cmd": "stop"};
- server: {"type": "ready", "rate", "loop_s"}, audio blocks, {"type": "meter", ...}
  every few blocks, {"type": "error", "message"}.

The server keeps about AHEAD_S of audio ahead of what the page reports played, so a
knob reaches the ear within that plus a block (and a circuit build, ~40 ms).
"""

from __future__ import annotations

import asyncio
import functools
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

# Module level: FastAPI resolves the endpoint's (postponed) annotations here.
from fastapi import WebSocket, WebSocketDisconnect  # listen extra

BLOCK = 480  # samples per audio frame (10 ms at 48 kHz)
AHEAD_S = 0.25  # audio kept ahead of playback
METER_EVERY = 5  # blocks per meter message
# The front panel (keys of the tweak page's controls): live on the Play page.
KNOBS = ("input_atten_db", "ac_threshold", "time_constant", "dc_threshold")
QUALITY = "draft-1x"  # the user's choice for playing (2026-10-27)

# The devices the page plays: id -> (label, circuit file or None for the 670 through its
# netlist API). Each brings its own front panel (`knobs`).
DEVICES = {
    "fairchild_670": ("Fairchild 670 (compressor)", None),
    "pultec_eqp1a": ("Pultec EQP-1A (program EQ)", "pultec_eqp1a"),
}
# Labels for circuit-file controls (keys otherwise); controls left off the panel.
LABELS = {
    "lf_freq_hz": "Low frequency (Hz)",
    "lf_boost": "Low boost",
    "lf_atten": "Low atten",
    "hf_boost_freq_khz": "High boost frequency (kHz)",
    "hf_boost": "High boost",
    "bandwidth": "Bandwidth (sharp to broad)",
    "hf_atten_freq_khz": "High atten frequency (kHz)",
    "hf_atten": "High atten",
}
OFF_PANEL = {"mains_v_rms", "mains_hz"}


def circuit_knobs(circuit: str) -> list[dict[str, Any]]:
    """A circuit file's front panel: its controls (operating conditions left out), in
    file order; a selector's positions as `choices`."""
    from varimu.circuit import spec

    out = []
    for key, e in spec.load_circuit(spec.circuit_path(circuit)).controls.items():
        if key in OFF_PANEL:
            continue
        k = {"key": key, "label": LABELS.get(key, key), "default": e["value"]}
        if "choices" in e:
            k["choices"] = list(e["choices"])
        else:
            k.update(min=e["min"], max=e["max"], step=(e["max"] - e["min"]) / 200)
        out.append(k)
    return out


def register(app) -> None:
    from fastapi.responses import FileResponse, HTMLResponse

    from varimu.listen.app import control_schema, excerpt, list_sources, to_overrides
    from varimu.sim.io import TransientSettings
    from varimu.sim.live import Live

    here = Path(__file__).parent

    @app.get("/play", response_class=HTMLResponse)
    def play_page():
        return (here / "play.html").read_text(encoding="utf-8")

    @app.get("/play/worklet.js")
    def play_worklet():
        return FileResponse(here / "play_worklet.js", media_type="text/javascript")

    def knobs(device: str) -> list[dict[str, Any]]:
        circuit = DEVICES[device][1]
        if circuit is None:
            return [c for c in control_schema() if c["key"] in KNOBS]
        return circuit_knobs(circuit)

    def overrides(device: str, values: dict[str, Any]) -> dict[str, Any]:
        return to_overrides(values) if DEVICES[device][1] is None else dict(values)

    @app.get("/api/play/info")
    def play_info():
        s = TransientSettings.from_sim_settings(engine="circuitsim", quality=QUALITY)
        devices = [{"id": d, "label": lab, "knobs": knobs(d)} for d, (lab, _) in DEVICES.items()]
        return {"rate": s.host, "quality": QUALITY, "devices": devices, "sources": list_sources()}

    @app.websocket("/ws/play")
    async def play_ws(ws: WebSocket):
        await ws.accept()
        loop = asyncio.get_running_loop()
        pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="play")
        inbox: asyncio.Queue = asyncio.Queue()
        live: Live | None = None
        device = "fairchild_670"
        sent = played = blocks = 0

        async def read() -> None:
            try:
                while True:
                    inbox.put_nowait(await ws.receive_json())
            except (WebSocketDisconnect, RuntimeError):
                inbox.put_nowait({"cmd": "stop"})

        async def error(msg: str) -> None:
            try:
                await ws.send_json({"type": "error", "message": msg[-1000:]})
            except RuntimeError:
                pass

        reader = asyncio.create_task(read())
        try:
            while True:
                msgs: list[dict[str, Any]] = []
                ahead = live is not None and sent - played < AHEAD_S * live.rate
                if not ahead:  # nothing to send: wait for a message
                    try:
                        msgs.append(await asyncio.wait_for(inbox.get(), 0.005))
                    except TimeoutError:
                        pass
                while not inbox.empty():
                    msgs.append(inbox.get_nowait())
                stop = False
                for m in msgs:
                    cmd = m.get("cmd")
                    if cmd == "stop":
                        stop = True
                    elif cmd == "played":
                        played = int(m.get("samples", played))
                    elif cmd == "set" and live is not None:
                        live.set(overrides(device, dict(m.get("values", {}))))
                    elif cmd == "start":
                        if live is not None:
                            live.close()
                            live = None
                        try:
                            device = str(m.get("device") or "fairchild_670")
                            if device not in DEVICES:
                                raise ValueError(f"unknown device {device!r}")
                            x = excerpt(m["source"], float(m.get("start_s") or 0), m.get("seconds"))
                            ov = overrides(device, dict(m.get("values", {})))
                            start = functools.partial(
                                Live, x, ov, circuit=DEVICES[device][1], quality=QUALITY
                            )
                            live = await loop.run_in_executor(pool, start)
                        except Exception as e:
                            await error(f"can't start: {type(e).__name__}: {e}")
                            continue
                        sent = played = blocks = 0
                        await ws.send_json({"type": "ready", "rate": live.rate,
                                            "loop_s": len(live.loop) / live.rate})  # fmt: skip
                if stop:
                    break
                if live is None or sent - played >= AHEAD_S * live.rate:
                    continue
                try:
                    y, meter = await loop.run_in_executor(pool, live.next_block, BLOCK)
                except Exception as e:
                    await error(f"the circuit stopped: {type(e).__name__}: {e}")
                    live.close()
                    live = None
                    continue
                await ws.send_bytes(y.tobytes())
                sent += BLOCK
                blocks += 1
                if blocks % METER_EVERY == 0:
                    await ws.send_json({
                        "type": "meter", "gain_db": round(meter.gain_db, 2),
                        "out_dbfs": round(meter.out_dbfs, 1),
                        "cv_v": None if meter.cv_v is None else round(meter.cv_v, 2),
                        "load": round(meter.load, 2),
                        "ahead_ms": round(1000 * (sent - played) / live.rate),
                        "restarts": live.restarts, "error": live.error,
                    })  # fmt: skip
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            reader.cancel()
            if live is not None:
                await loop.run_in_executor(pool, live.close)
            pool.shutdown(wait=False)
