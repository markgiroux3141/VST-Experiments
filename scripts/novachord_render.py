"""The Novachord played from MIDI (docs/NOVACHORD_PLAN.md, NV3): config/circuits/novachord.yaml
(scripts/make_novachord.py) rendered whole, every key's springs worked by its notes: springs 3
by the key, spring 1 by the key or the sustaining pedal (MIDI CC64 for the whole keyboard;
`--bass-pedal-cc` names a controller for the bass pedal, the lower 36 keys).

    uv run --extra fast python scripts/novachord_render.py (--midi FILE | --demo)
        [--seconds S] [--tail 2] [--quality draft|production]
        [--set attack=7 full=3 res1=2 mellow=1 ...] [--threads 4] [--out NAME]

Key 1 is F1 (MIDI 29), key 72 E7 (MIDI 100); notes outside are folded into range by octaves.
The Novachord has no touch: velocities are ignored. The keys are switch controls in the circuit
(rheostat contacts, always present), so the render is a stream updated in place at each key
event (the stream's restart is first order, as a knob's), settled like a render first. Writes
reports/novachord/renders/<name>.wav (the preamplifier's output, 0 dBFS = the circuit's full
scale) and <name>.json (the settings, the time taken), and with --demo the MIDI beside them.
The whole instrument is offline (tens to hundreds of times slower than real time); the
partition runs the note groups on threads of their own.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import time
from pathlib import Path

import numpy as np

from varimu.circuit import builder, spec
from varimu.circuit.ir import VoltageProbe
from varimu.config import CONFIG_DIR, REPO_ROOT
from varimu.rhodes import midi
from varimu.sim import fast
from varimu.sim.io import TransientSettings, decimate, write_audio

OUT = REPO_ROOT / "reports" / "novachord" / "renders"
CIRCUIT = CONFIG_DIR / "circuits" / "novachord.yaml"
LOW_MIDI, HIGH_MIDI = 29, 100  # keys 1..72


def _maker():
    sp = importlib.util.spec_from_file_location(
        "make_novachord", REPO_ROOT / "scripts" / "make_novachord.py"
    )
    m = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(m)
    return m


def fold(note: int) -> int:
    while note < LOW_MIDI:
        note += 12
    while note > HIGH_MIDI:
        note -= 12
    return note


def demo_events() -> list[midi.Event]:
    """A string pad (the slow attack suits it): four chords at 60 bpm, a melody on top."""
    ev: list[midi.Event] = []

    def note(t, n, dur):
        ev.append(midi.Event(t, "on", n, 100))
        ev.append(midi.Event(t + dur, "off", n, 0))

    chords = [(45, [57, 60, 64]), (41, [57, 60, 65]), (43, [55, 59, 62]), (40, [55, 59, 64])]
    for bar, (bass, chord) in enumerate(chords):
        t0 = bar * 3.0
        note(t0, bass, 2.95)
        for n in chord:
            note(t0 + 0.05, n, 2.9)
    for i, n in enumerate([76, 74, 72, 71, 72, 74, 76, 79]):
        note(0.5 + 1.5 * i, n, 1.4)
    return sorted(ev, key=lambda e: e.t_s)


def key_states(events: list[midi.Event], bass_cc: list[tuple[float, int]] | None = None):
    """[(seconds, {control: 0 / 1})] at each change: `k<key>` the key (springs 3), `s<key>`
    spring 1 (the key or a pedal)."""
    changes: dict[float, list] = {}
    for e in events:
        changes.setdefault(e.t_s, []).append(e)
    for t, v in bass_cc or []:
        changes.setdefault(t, []).append(midi.Event(t, "bass", value=1 if v >= 64 else 0))
    down: dict[int, int] = {}
    pedal = bass = 0
    state = {f"{c}{k}": 0 for k in range(1, 73) for c in "ks"}
    out = []
    for t in sorted(changes):
        for e in changes[t]:
            if e.kind == "pedal":
                pedal = 1 if e.value else 0
            elif e.kind == "bass":
                bass = e.value
            elif e.kind in ("on", "off"):
                k = fold(e.note) - LOW_MIDI + 1
                down[k] = max(0, down.get(k, 0) + (1 if e.kind == "on" else -1))
        new = {}
        for k in range(1, 73):
            g = 1 if down.get(k, 0) else 0
            new[f"k{k}"] = g
            new[f"s{k}"] = max(g, pedal, bass if k <= 36 else 0)
        if new != state:
            state = new
            out.append((t, dict(new)))
    return out


def render(
    events,
    seconds: float,
    quality: str = "draft",
    sets: dict | None = None,
    threads: int = 3,
    probes=("out",),
    progress=print,
):
    """The instrument's probes over `seconds` (at the sample rate) for the events; returns
    ({probe: array}, wall seconds, spec)."""
    import circuitsim

    fast.check_build()
    mk = _maker()
    s = spec.load_circuit(CIRCUIT)
    st = TransientSettings.from_sim_settings(engine="circuitsim", quality=quality)
    fs, k = st.sample_rate, st.oversample
    base = dict(sets or {})

    def ir_for(state):
        ir = builder.build_ir(s, spec.resolve(s, base | state))
        import dataclasses

        return dataclasses.replace(ir, probes=tuple(VoltageProbe(p) for p in probes))

    states = key_states(events)
    ir0 = ir_for({})
    part = [
        t
        for t in mk.partition(12 // threads)
        if t == "|" or any(x.title == t for x in ir0.sections)
    ]
    t0 = time.perf_counter()
    stream = circuitsim.Stream(
        ir0.to_json(),
        1.0 / st.sim_rate,
        0.0,
        st.method,
        solver=st.solver,
        reltol=st.newton_reltol,
        vntol=st.newton_vntol,
        input_order=st.input_order,
        newton_reuse=st.newton_reuse,
        tube_tables=st.tube_tables,
        partition=part,
        partition_coupling=st.partition_coupling,
        error_abstol=st.error_abstol,
        error_reltol=st.error_reltol,
        step_selection=st.step_selection,
        error_norm=st.error_norm,
    )
    chunks: dict[str, list] = {p: [] for p in probes}

    def run(n_sim: int, keep: bool):
        left = n_sim
        while left > 0:
            m = min(left, st.sim_rate // 4)
            out = stream.process(np.zeros(m))
            if keep:
                for p in probes:
                    chunks[p].append(np.asarray(out[f"v({p})"]))
            left -= m

    run(int(st.settle_s * st.sim_rate), keep=False)
    for p in probes:
        chunks[p].clear()
    t_now = 0.0
    for t, state in states:
        if t >= seconds:
            break
        run(int(round((t - t_now) * st.sim_rate)), keep=True)
        t_now = t
        stream.update(ir_for(state).to_json())
        if progress:
            down = sum(v for c, v in state.items() if c[0] == "k")
            progress(f"  {t:7.2f} s: {down} keys down ({time.perf_counter() - t0:.0f} s)")
    run(int(round((seconds - t_now) * st.sim_rate)), keep=True)
    tail = stream.finish()
    for p in probes:
        chunks[p].append(np.asarray(tail[f"v({p})"]))
    el = time.perf_counter() - t0
    n = int(round(seconds * fs))
    out = {p: decimate(np.concatenate(chunks[p]), k, n) for p in probes}
    return out, el, s


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--midi", type=Path)
    src.add_argument("--demo", action="store_true")
    ap.add_argument("--seconds", type=float, default=None)
    ap.add_argument("--tail", type=float, default=2.0)
    ap.add_argument("--quality", default="draft")
    ap.add_argument("--set", nargs="*", default=[])
    ap.add_argument("--threads", type=int, default=3, choices=(1, 2, 3, 4, 6, 12))
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    events = demo_events() if args.demo else midi.read(args.midi)
    end = max((e.t_s for e in events), default=0.0)
    seconds = (args.seconds if args.seconds is not None else end) + args.tail
    sets = {}
    for kv in args.set:
        key, v = kv.split("=")
        sets[key] = float(v)
    name = args.out or ("demo" if args.demo else args.midi.stem)
    OUT.mkdir(parents=True, exist_ok=True)
    if args.demo:
        midi.write(OUT / f"{name}.mid", events)
    v, el, s = render(events, seconds, args.quality, sets, args.threads)
    fs_out = float(s.full_scale[1])
    y = v["out"]
    write_audio(OUT / f"{name}.wav", (y / fs_out).astype(np.float32), 96000)
    info = {
        "quality": args.quality,
        "set": sets,
        "seconds": seconds,
        "wall_s": round(el, 1),
        "x_real_time": round(el / seconds, 1),
        "peak_v": float(np.abs(y).max()),
        "full_scale_v": fs_out,
    }
    (OUT / f"{name}.json").write_text(json.dumps(info, indent=2), encoding="utf-8")
    print(json.dumps(info))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
