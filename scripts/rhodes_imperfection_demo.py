"""The imperfect Rhodes measured and heard (docs/RHODES_IMPERFECTION_PLAN.md).

    uv run --extra fast --extra listen python scripts/rhodes_imperfection_demo.py
        [--measure] [--render] [--amounts 0 1 2] [--unit 1] [--quality draft]

`--measure` (seconds; the harp alone, circuitsim's medium): over the 73 keys at velocity 90,
each key's level, pitch, sustain and release against the compiled harp at each amount; a
repeated note (C4 x 8 at velocity 80, the tine at rest each time) with only the hammer's
share on, its strike-to-strike spread in level and brightness. -> measurements.json.

`--render` (minutes per amount): one phrase built to show it (a repeated C4, a repeated
chord, a chromatic run up two octaves at one velocity, staccato chords for the releases, then
the demo's pedalled progression) through the whole Suitcase (config/circuits/
rhodes_suitcase_100w.yaml: the speakers' pressure, stereo) at each amount, every other knob at
the file's values. Each WAV is matched to -23 LUFS (loudness lies), and the harp's own EMF is
written beside it. -> reports/rhodes/imperfection/audio/.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import circuitsim
import numpy as np

from varimu.rhodes import compile as hc
from varimu.rhodes import imperfection as imp
from varimu.rhodes import midi

ROOT = Path(__file__).parents[1]
OUT = ROOT / "reports" / "rhodes" / "imperfection"
FS = 96000.0
MODEL = "MK1_HARP@2"
CIRCUIT = "rhodes_suitcase_100w"


def _element(model: dict, i: imp.Imperfection | None) -> str:
    el = {"name": "VHARP", "out": "h", "rate_hz": FS, "contact_rate_hz": 4 * FS, "model": model}
    if i is not None:
        el["imperfection"] = {k: float(v) for k, v in dataclasses.asdict(i).items()}
    return json.dumps(el)


def _harp(element: str, n: int, steps) -> np.ndarray:
    emf, _, _ = circuitsim.harp_render(element, FS, n, steps)
    return np.asarray(emf)


def _f0(y: np.ndarray, hz: float) -> float:
    s = y[int(0.3 * FS) : int(1.3 * FS)]
    nfft = 1 << 22
    m = np.abs(np.fft.rfft(s * np.hanning(s.size), nfft))
    fr = np.fft.rfftfreq(nfft, 1 / FS)
    band = np.flatnonzero((fr > 0.97 * hz) & (fr < 1.03 * hz))
    return float(fr[band[np.argmax(m[band])]])


def _env_db(y: np.ndarray, t0: float, t1: float) -> float:
    s = y[int(t0 * FS) : int(t1 * FS)]
    return float(20 * np.log10(np.sqrt(np.mean(s**2)) + 1e-30))


def _release_ms(y: np.ndarray, t_off: float, drop_db: float = 40.0) -> float:
    """Milliseconds from the key's release until its 5 ms rms falls `drop_db` under the
    last 5 ms before it."""
    w = int(0.005 * FS)
    i0 = int(t_off * FS)
    before = np.sqrt(np.mean(y[i0 - w : i0] ** 2))
    seg = y[i0:]
    nb = seg.size // w
    r = np.sqrt(np.mean(seg[: nb * w].reshape(nb, w) ** 2, axis=1))
    below = np.flatnonzero(r < before * 10 ** (-drop_db / 20))
    return float((below[0] + 1) * 5.0) if below.size else float("nan")


def _centroid_hz(y: np.ndarray) -> float:
    s = y[: int(0.1 * FS)]
    m = np.abs(np.fft.rfft(s * np.hanning(s.size))) ** 2
    fr = np.fft.rfftfreq(s.size, 1 / FS)
    return float(np.sum(fr * m) / np.sum(m))


def measure(amounts: list[float], unit: int) -> dict:
    model = hc.load_data(MODEL)
    out: dict = {"model": MODEL, "unit": unit, "per_key": {}, "repeated": {}}
    hold, after = 1.6, 0.6  # key held, then released
    n = int((0.01 + hold + after) * FS)
    ref = {}
    for a in [0.0, *[x for x in amounts if x != 0.0]]:
        i = None if a == 0 else imp.Imperfection(seed=unit, amount=a)
        el = _element(model, i)
        rows = []
        for kd in model["keys"]:
            note, hz = int(kd["note"]), float(kd["note_hz"])
            steps = [(int(0.01 * FS), "on", note, 90), (int((0.01 + hold) * FS), "off", note, 0)]
            y = _harp(el, n, steps)
            level = _env_db(y, 0.01, 0.31)
            sustain = _env_db(y, 1.2, 1.5) - _env_db(y, 0.3, 0.6)
            release = _release_ms(y, 0.01 + hold)
            rows.append(
                {
                    "key": kd["key"],
                    "level_db": level,
                    "f0_hz": _f0(y, hz),
                    "sustain_db": sustain,
                    "release_db": release,  # ms to fall 40 dB
                    "centroid_hz": _centroid_hz(y[int(0.01 * FS) :]),
                }
            )
        if a == 0:
            ref = {r["key"]: r for r in rows}
            continue
        d = {
            "level_db": [r["level_db"] - ref[r["key"]]["level_db"] for r in rows],
            "cents": [1200 * np.log2(r["f0_hz"] / ref[r["key"]]["f0_hz"]) for r in rows],
            "sustain_db": [r["sustain_db"] - ref[r["key"]]["sustain_db"] for r in rows],
            "release_ratio": [r["release_db"] / ref[r["key"]]["release_db"] for r in rows],
            "centroid_ratio": [r["centroid_hz"] / ref[r["key"]]["centroid_hz"] for r in rows],
        }
        summary = {
            k: {
                "rms": float(
                    np.sqrt(np.nanmean(np.square(np.log(v) if k.endswith("ratio") else v)))
                ),
                "min": float(np.nanmin(v)),
                "max": float(np.nanmax(v)),
            }
            for k, v in d.items()
        }
        out["per_key"][str(a)] = {"summary": summary, "keys": [r["key"] for r in rows], **d}
        print(f"amount {a}: " + ", ".join(f"{k} rms {s['rms']:.2f}" for k, s in summary.items()))
    # a repeated note, the tine at rest each time: only the hammer's share
    gap, reps, note = 1.2, 8, 60
    n = int(gap * reps * FS)
    steps = []
    for r in range(reps):
        t = 0.01 + gap * r
        steps += [(int(t * FS), "on", note, 80), (int((t + 0.5) * FS), "off", note, 0)]
    steps.sort(key=lambda s: (s[0], s[1] != "off"))
    for a in amounts:
        if a == 0:
            continue
        i = imp.Imperfection(unit, a, 0, 0, 0, 0, 0, 1.0, 0)
        y = _harp(_element(model, i), n, steps)
        lv, ce = [], []
        for r in range(reps):
            seg = y[int((0.01 + gap * r) * FS) :][: int(0.4 * FS)]
            lv.append(_env_db(seg, 0.0, 0.3))
            ce.append(_centroid_hz(seg))
        lv, ce = np.array(lv), np.array(ce)
        out["repeated"][str(a)] = {
            "level_db": (lv - lv.mean()).round(3).tolist(),
            "level_spread_db": float(np.std(lv)),
            "centroid_hz": ce.round(1).tolist(),
            "centroid_spread_pct": float(100 * np.std(ce) / np.mean(ce)),
        }
        print(
            f"repeated C4, hammer at {a}: level {np.std(lv):.2f} dB rms, brightness"
            f" {100 * np.std(ce) / np.mean(ce):.1f}% rms"
        )
    return out


def phrase() -> list[midi.Event]:
    """A repeated C4, a repeated chord, a chromatic run at one velocity, staccato chords
    (releases), then rhodes_render.py's pedalled progression."""
    import importlib.util

    ev: list[midi.Event] = []

    def note(t, n, vel, dur):
        ev.append(midi.Event(t, "on", n, vel))
        ev.append(midi.Event(t + dur, "off", n, 0))

    t = 0.2
    for _ in range(8):  # the same key, the same velocity
        note(t, 60, 80, 0.3)
        t += 0.4
    t += 0.4
    for _ in range(4):  # the same chord
        for j, n in enumerate([57, 60, 64, 67]):
            note(t + 0.008 * j, n, 75, 0.5)
        t += 0.7
    t += 0.4
    for n in range(48, 73):  # chromatic C3-C5 at one velocity: key to key
        note(t, n, 80, 0.22)
        t += 0.25
    t += 0.6
    for _ in range(6):  # staccato: the releases
        for j, n in enumerate([52, 59, 64, 67]):
            note(t + 0.006 * j, n, 90, 0.12)
        t += 0.45
    t += 0.8
    spec_ = importlib.util.spec_from_file_location("rr", ROOT / "scripts" / "rhodes_render.py")
    rr = importlib.util.module_from_spec(spec_)
    spec_.loader.exec_module(rr)
    for e in rr.demo_events():
        ev.append(dataclasses.replace(e, t_s=e.t_s + t))
    return sorted(ev, key=lambda e: (e.t_s, e.kind != "off"))


def _render_one(job: tuple[float, int, str]) -> str:
    a, unit, quality = job
    from varimu.circuit import builder, spec
    from varimu.rhodes import spec as rspec
    from varimu.separation.metrics import match_loudness
    from varimu.sim import fast
    from varimu.sim.io import TransientSettings, write_audio

    events = phrase()
    duration = max(e.t_s for e in events) + 3.0
    c = spec.load_circuit(spec.circuit_path(CIRCUIT))
    ir = builder.build(c, {"imp_amount": a, "imp_unit": float(unit)}).ir
    s = TransientSettings.from_sim_settings(engine="circuitsim", quality=quality)
    notes = [(e.t_s, e.kind, e.note, e.value) for e in events]
    name = f"amount_{a:g}_unit_{unit}"
    audio = OUT / "audio"
    (el,) = [e for e in ir.elements() if e.name == "VHARP"]
    element = {
        "name": el.name,
        "out": el.out,
        "rate_hz": el.rate_hz,
        "contact_rate_hz": el.contact_rate_hz,
        "model": el.model,
    }
    if el.imperfection is not None:
        element["imperfection"] = {
            k: float(v) for k, v in dataclasses.asdict(el.imperfection).items()
        }
    fs = float(s.sample_rate)
    emf, _, _ = circuitsim.harp_render(
        json.dumps(element),
        fs,
        int(round(duration * fs)) + 1,
        [(round(t * fs), k, n, v) for t, k, n, v in notes],
    )
    emf = np.asarray(emf) / rspec.load()["numerics"]["full_scale_v"]
    write_audio(audio / f"{name}_harp.wav", match_loudness(emf, fs).astype(np.float32), int(fs))
    t0 = time.perf_counter()
    x = np.zeros(int(round(duration * fs)))
    vec = fast.run_transient(ir, x, settings=s, notes=notes).vectors
    y = np.column_stack([vec["v(out)"], vec["v(out_r)"]])
    write_audio(audio / f"{name}.wav", match_loudness(y, fs).astype(np.float32), int(fs))
    return f"{name}: {time.perf_counter() - t0:.0f} s for {duration:.1f} s"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--measure", action="store_true")
    ap.add_argument("--render", action="store_true")
    ap.add_argument("--amounts", type=float, nargs="*", default=[0.0, 1.0, 2.0])
    ap.add_argument("--unit", type=int, default=1)
    ap.add_argument("--quality", default="draft", choices=["draft", "draft-1x"])
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    if args.measure:
        m = measure(args.amounts, args.unit)
        (OUT / "measurements.json").write_text(json.dumps(m, indent=1), encoding="utf-8")
    if args.render:
        (OUT / "audio").mkdir(parents=True, exist_ok=True)
        midi.write(OUT / "audio" / "phrase.mid", phrase())
        jobs = [(a, args.unit, args.quality) for a in args.amounts]
        with ProcessPoolExecutor(len(jobs)) as pool:
            for line in pool.map(_render_one, jobs):
                print(line, flush=True)


if __name__ == "__main__":
    main()
