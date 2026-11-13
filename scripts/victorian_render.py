"""The Victorian synth's voice played from MIDI (docs/VICTORIAN_SYNTH_PLAN.md, V3):
config/circuits/victorian_voice.yaml, its reeds a medium in the netlist played by the file's
notes, its output the sound pressure 1 m in front of the parchment cone's cabinet.

    uv run --extra fast --extra listen python scripts/victorian_render.py --midi FILE
        [--seconds S] [--tail 4] [--quality draft|draft-1x|production]
        [--set cutoff=0.3 ...] [--velocity-scale 1.0] [--out NAME]

Every channel of the file plays the one voice (one reed per key, C1-C6): a key is pressed
when its first part strikes it and lifted when its last part lets go (a count per key), so
two parts sharing a note don't cut each other off; notes outside C1-C6 are dropped (and
counted). `--velocity-scale` multiplies the file's velocities (clamped to 1-127).

Writes reports/victorian/renders/<name>.wav (float, peak-normalized to -1 dBFS for
listening) and <name>.json (the absolute level at 1 m, the batteries' sag through the
piece, the times). The run is one continuous simulation: the cells tire through the piece.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
import time
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from varimu.circuit import builder  # noqa: E402
from varimu.circuit.spec import circuit_path, load_circuit  # noqa: E402
from varimu.rhodes import midi  # noqa: E402
from varimu.sim import fast  # noqa: E402
from varimu.sim.io import TransientSettings, full_scale, write_audio  # noqa: E402

OUT = REPO / "reports" / "victorian" / "renders"
CIRCUIT = "victorian_voice"
LOW, HIGH = 24, 84  # C1-C6, GRAY_REEDS@3's keys
KEEP = ("out", "line", "loc", "out_fs")  # probes kept (all 13 over minutes: gigabytes)


def keyed(events: list[midi.Event], vel_scale: float) -> tuple[list[tuple], dict]:
    """The file's notes as one keyboard's: (t, "on"/"off", note, velocity), a count per key."""
    held: dict[int, int] = {}
    out, dropped, merged = [], 0, 0
    # Offs before ons at the same instant: a repeated note re-strikes.
    for e in sorted(events, key=lambda e: (e.t_s, e.kind != "off")):
        if e.kind not in ("on", "off"):
            continue
        if not LOW <= e.note <= HIGH:
            dropped += e.kind == "on"
            continue
        n = held.get(e.note, 0)
        if e.kind == "on":
            if n == 0:
                vel = int(min(127, max(1, round(e.value * vel_scale))))
                out.append((e.t_s, "on", e.note, vel))
            else:
                merged += 1
            held[e.note] = n + 1
        elif n > 0:
            held[e.note] = n - 1
            if n == 1:
                out.append((e.t_s, "off", e.note, 0))
    return out, {"dropped_out_of_range": dropped, "merged_into_held_keys": merged}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--midi", type=Path, required=True)
    ap.add_argument("--seconds", type=float, help="cut the MIDI there")
    ap.add_argument("--tail", type=float, default=4.0, help="seconds after the last event")
    ap.add_argument("--quality", default="draft", choices=["draft", "draft-1x", "production"])
    ap.add_argument("--set", nargs="*", default=[], metavar="KEY=VALUE")
    ap.add_argument("--velocity-scale", type=float, default=1.0)
    ap.add_argument("--out", help="the WAV's name")
    args = ap.parse_args()

    events = midi.read(args.midi)
    if args.seconds:
        events = [e for e in events if e.t_s < args.seconds]
        events.append(midi.Event(args.seconds, "pedal", 0, 0))  # marks the cut
    notes, counts = keyed(events, args.velocity_scale)
    if args.seconds:  # lift what is still held at the cut
        down: set[int] = set()
        for _, k, n, _ in notes:
            (down.add if k == "on" else down.discard)(n)
        notes += [(args.seconds, "off", n, 0) for n in sorted(down)]
    duration = max(e.t_s for e in events) + args.tail
    name = args.out or args.midi.stem.replace(" ", "_")

    spec = load_circuit(circuit_path(CIRCUIT))
    over = {k: float(v) for k, v in (kv.split("=", 1) for kv in args.set)}
    ir = builder.build(spec, over or None, cores="ja").ir
    ir = dataclasses.replace(ir, probes=tuple(p for p in ir.probes if p.node in KEEP))
    s = TransientSettings.from_sim_settings(
        engine="circuitsim", quality=None if args.quality == "production" else args.quality
    )
    s = dataclasses.replace(s, cores="ja")
    fs = int(s.sample_rate)

    print(
        f"{len(notes) // 2} key presses ({counts}), {duration:.1f} s at {args.quality}",
        flush=True,
    )
    t0 = time.perf_counter()
    last = [0.0]

    def progress(f: float) -> None:
        if f - last[0] >= 0.05 or f >= 1.0:
            last[0] = f
            el = time.perf_counter() - t0
            eta = el / max(f, 1e-9) * (1 - f)
            print(f"  {f * 100:5.1f}%  {el:6.0f} s elapsed, ~{eta:5.0f} s left", flush=True)

    x = np.zeros(int(round(duration * fs)))
    vec = fast.run_transient(ir, x, settings=s, notes=notes, progress=progress).vectors
    t_run = time.perf_counter() - t0
    y = np.asarray(vec["v(out)"])
    peak = float(np.max(np.abs(y)))

    OUT.mkdir(parents=True, exist_ok=True)
    write_audio(OUT / f"{name}.wav", (y / peak * 10 ** (-1 / 20)).astype(np.float32), fs)

    def at(probe: str, t: float) -> float:
        i = min(len(y) - 1, int(t * fs))
        return float(np.mean(vec[probe][max(0, i - fs // 4) : i + fs // 4]))

    marks = [t for t in (1, 30, 60, 120, 180, 240, 300) if t < duration] + [duration - 0.5]
    rms = [float(np.std(y[int(t * fs) : int((t + 10) * fs)])) for t in range(0, int(duration), 10)]
    summary = {
        "midi": str(args.midi),
        "quality": args.quality,
        "set": over,
        "velocity_scale": args.velocity_scale,
        "key_presses": len(notes) // 2,
        **counts,
        "duration_s": duration,
        "render_s": t_run,
        "x_real_time": t_run / duration,
        "peak_pa_at_1m": peak,
        "peak_re_full_scale": peak / full_scale(s, spec)[1],
        "rms_pa_per_10s": rms,
        "field_winding_v": {f"{t:.0f}s": at("v(out_fs)", t) for t in marks},
        "line_v": {f"{t:.0f}s": at("v(line)", t) for t in marks},
        "local_v": {f"{t:.0f}s": at("v(loc)", t) for t in marks},
    }
    (OUT / f"{name}.json").write_text(json.dumps(summary, indent=2))
    print(
        f"peak {peak * 1e3:.2f} mPa at 1 m ({summary['peak_re_full_scale']:.2f} of full scale), "
        f"{t_run:.0f} s ({t_run / duration:.2f}x real time) -> {OUT / name}.wav"
    )


if __name__ == "__main__":
    main()
