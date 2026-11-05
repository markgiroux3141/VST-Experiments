"""A recording scene (ROOM_LOOP_PLAN.md R3): a room, sources placed in it, mics placed and
aimed, each through its chain (a mic + preamp circuit file), and the render: every mic's
two entry pressures from the room (varimu.rooms.shoebox), printed through its chain.

A scene file (YAML or JSON; `config/scenes/*.yaml`, the native app's Room view writes
JSON):

    name: two_sources
    room:
      dims_m: [7.0, 5.5, 3.2]
      materials: {walls: furnished_wall, floor: wood_floor, ceiling: gypsum_on_studs}
        # or one per surface: {x0: ..., x1: ..., y0: ..., y1: ..., floor: ..., ceiling: ...}
      source: "provisional: ..."
    sources:
      - name: A
        clip: data/clips/x.wav       # relative to the repo, or absolute
        start_s: 0                   # optional, and seconds: N
        spl_db: 90                   # its rms in dB SPL at 1 m in free field
        position_m: [2.0, 2.5, 1.2]
    mics:
      - name: spot A
        chain: u47_v76               # a circuit file with a capsule (`capsule_model*`)
        position_m: [2.0, 2.2, 1.2]
        aim: {azimuth_deg: 90, elevation_deg: 0}   # counterclockwise from +x
        set: {pattern_u47: 0, gain_db_v76: 40}     # the chain's controls and values
        pan: -0.5                    # -1 left .. 1 right (the session's balance law)
    settings: {quality: production, ism_s: 0.08, seed: 0, tail_s: null}

The sources' clips are mono (any rate, resampled to the project's), each scaled to its
SPL (its rms, as scripts/mic_print.py), so a source is the free-field sound pressure 1 m
away (pascals). Mic positions are kept 0.1 m from sources (the entry tables' nearest
distance, varimu.rooms.entries).

`render(scene)` writes, in its output folder: each mic's print `<mic>.wav` (mono float32 at
the project's rate, the chain's out at its full scale), `mix.wav` (stereo, the mics
panned), and `render.json` (the files, pans, levels, timing). With `solo=True` it also
prints each source alone through every mic (`<mic>__<source>.wav`): the room is linear, so
those give the **bleed matrix** (each mic's level of each source, in total and per octave
band), and the sum minus the solos says how much the chains' nonlinearity mixed the
sources (`intermod_db`). Prints are cached in cache/rooms/prints/ by the built IR, the
inputs, the settings and circuitsim's source.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from varimu.config import REPO_ROOT
from varimu.rooms.entries import MIN_DISTANCE_M, entry_table
from varimu.rooms.shoebox import SURFACES, Mic, Shoebox, aim_vector, responses

P_REF = 20e-6
CACHE = REPO_ROOT / "cache" / "rooms" / "prints"
OCTAVES_HZ = (63, 125, 250, 500, 1000, 2000, 4000, 8000, 16000)


@dataclass
class SourceSpec:
    name: str
    clip: Path
    spl_db: float
    position_m: np.ndarray
    start_s: float = 0.0
    seconds: float | None = None


@dataclass
class MicSpec:
    name: str
    chain: str
    position_m: np.ndarray
    azimuth_deg: float
    elevation_deg: float = 0.0
    set: dict[str, float] = field(default_factory=dict)
    pan: float = 0.0


@dataclass
class Scene:
    name: str
    room: Shoebox
    sources: list[SourceSpec]
    mics: list[MicSpec]
    quality: str = "production"
    ism_s: float = 0.08
    seed: int = 0
    tail_s: float | None = None
    room_source: str = ""


def _materials(m: dict) -> tuple[str, ...]:
    if "walls" in m:
        return (m["walls"],) * 4 + (m["floor"], m["ceiling"])
    return tuple(m[s] for s in SURFACES)


def _path(p: str | Path) -> Path:
    p = Path(p)
    return p if p.is_absolute() else REPO_ROOT / p


def load_scene(path_or_data: str | Path | dict) -> Scene:
    """A scene from its file (YAML or JSON) or its parsed data (the module docstring)."""
    if isinstance(path_or_data, dict):
        d = path_or_data
    else:
        d = yaml.safe_load(Path(path_or_data).read_text(encoding="utf-8"))
    r = d["room"]
    room = Shoebox(
        tuple(float(x) for x in r["dims_m"]),
        _materials(r["materials"]),
        float(r.get("temp_c", 20.0)),
        float(r.get("rh_percent", 50.0)),
    )
    sources = [
        SourceSpec(
            s["name"],
            _path(s["clip"]),
            float(s["spl_db"]),
            np.array(s["position_m"], float),
            float(s.get("start_s", 0.0)),
            None if s.get("seconds") is None else float(s["seconds"]),
        )
        for s in d["sources"]
    ]
    mics = []
    for m in d["mics"]:
        aim = m.get("aim", {})
        mics.append(
            MicSpec(
                m["name"],
                m["chain"],
                np.array(m["position_m"], float),
                float(aim.get("azimuth_deg", 0.0)),
                float(aim.get("elevation_deg", 0.0)),
                {k: float(v) for k, v in (m.get("set") or {}).items()},
                float(m.get("pan", 0.0)),
            )
        )
    st = d.get("settings") or {}
    names = [s.name for s in sources] + [m.name for m in mics]
    if len(set(names)) != len(names):
        raise ValueError(f"scene {d['name']}: sources and mics need distinct names")
    return Scene(
        d["name"],
        room,
        sources,
        mics,
        st.get("quality", "production"),
        float(st.get("ism_s", 0.08)),
        int(st.get("seed", 0)),
        st.get("tail_s"),
        str(r.get("source", "")),
    )


def _capsule_geometry(chain: str, over: dict) -> dict:
    from varimu.circuit import spec
    from varimu.devices.library import component_data

    q = spec.resolve(spec.load_circuit(spec.circuit_path(chain)), over)
    keys = [k for k in q if str(k).startswith("capsule_model")]
    if not keys:
        raise ValueError(f"chain {chain} has no capsule (a `capsule_model*` value)")
    return component_data(str(q[keys[0]])).get("geometry", {})


def _settings(quality: str):
    from varimu.sim.io import TransientSettings

    return TransientSettings.from_sim_settings(
        engine="circuitsim", quality=None if quality == "production" else quality
    )


def source_signals(scene: Scene, fs: int) -> list[np.ndarray]:
    """Each source's free-field pressure 1 m away (pascals), at fs."""
    from varimu.sim.io import load_audio

    out = []
    for s in scene.sources:
        x = load_audio(s.clip, fs)
        x = x[int(s.start_s * fs) :]
        if s.seconds is not None:
            x = x[: int(s.seconds * fs)]
        x = x - np.mean(x)
        rms = np.sqrt(np.mean(x**2))
        if rms == 0:
            raise ValueError(f"source {s.name}: its clip is silent")
        out.append(x * (P_REF * 10 ** (s.spl_db / 20) / rms))
    return out


def _fftconv(x: np.ndarray, h: np.ndarray, n_out: int) -> np.ndarray:
    m = 1 << int(np.ceil(np.log2(len(x) + len(h))))
    return np.fft.irfft(np.fft.rfft(x, m) * np.fft.rfft(h, m), m)[:n_out]


def mic_pressures(
    scene: Scene, fs: int, signals: list[np.ndarray]
) -> tuple[np.ndarray, list[str], int]:
    """Per source and mic the entries' pressures, (sources, mics, 2, samples): each
    source's signal convolved with its room response; and the tables' kinds, and the
    length (the longest source plus the room's tail)."""
    tables, kinds = {}, []
    mics = []
    for m in scene.mics:
        for s in scene.sources:
            if np.linalg.norm(m.position_m - s.position_m) < MIN_DISTANCE_M:
                raise ValueError(f"mic {m.name} is closer than {MIN_DISTANCE_M} m to {s.name}")
        geom = _capsule_geometry(m.chain, m.set)
        key = json.dumps(geom, sort_keys=True, default=str)
        if key not in tables:
            tables[key] = entry_table(geom, fs)
        kinds.append(tables[key].kind)
        mics.append(Mic(m.position_m, aim_vector(m.azimuth_deg, m.elevation_deg), tables[key]))
    seeds = [scene.seed * 1000 + i for i in range(len(scene.sources))]
    h = responses(
        scene.room,
        [s.position_m for s in scene.sources],
        mics,
        fs,
        ism_s=scene.ism_s,
        length_s=scene.tail_s,
        seeds=seeds,
        tail=not any(m == "anechoic" for m in scene.room.materials),
    )
    n = max(len(x) for x in signals) + h.shape[-1]
    p = np.zeros((len(scene.sources), len(scene.mics), 2, n))
    for si, x in enumerate(signals):
        for mi in range(len(scene.mics)):
            for e in range(2):
                p[si, mi, e] = _fftconv(x, h[si, mi, e], n)
    return p, kinds, n


def _print_key(ir_json: str, front: np.ndarray, rear: np.ndarray, settings: Any) -> str:
    import circuitsim

    hsh = hashlib.sha256()
    for part in (ir_json, repr(settings), circuitsim.SOURCE_HASH):
        hsh.update(part.encode())
    hsh.update(np.ascontiguousarray(front, np.float64).tobytes())
    hsh.update(np.ascontiguousarray(rear, np.float64).tobytes())
    return hsh.hexdigest()[:32]


def print_chain(
    chain: str,
    over: dict,
    front: np.ndarray,
    rear: np.ndarray,
    quality: str,
    progress: Callable[[float], None] | None = None,
) -> np.ndarray:
    """A mic's chain driven by its entries' pressures: the chain's `out` at its full scale
    (cached)."""
    from varimu.circuit import builder, spec
    from varimu.sim import fast
    from varimu.sim.io import full_scale

    c = spec.load_circuit(spec.circuit_path(chain))
    ir = builder.build(c, over).ir
    s = _settings(quality)
    key = _print_key(ir.to_json(), front, rear, s)
    path = CACHE / f"{key}.npy"
    if path.exists():
        if progress:
            progress(1.0)
        return np.load(path)
    controls = {"p_rear": rear} if any(k.name == "p_rear" for k in ir.controls) else None
    v = fast.run_transient(ir, front, settings=s, controls=controls, progress=progress)
    y = v.vectors["v(out)"] / full_scale(s, c)[1]
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f".{os.getpid()}.tmp.npy")
    np.save(tmp, y)
    os.replace(tmp, path)
    return y


def _db(x: np.ndarray) -> float:
    return float(20 * np.log10(np.sqrt(np.mean(np.square(x))) + 1e-15))


def octave_levels_db(x: np.ndarray, fs: int) -> list[float]:
    """rms level per octave band (OCTAVES_HZ), dB re full scale."""
    spec = np.abs(np.fft.rfft(x)) ** 2
    f = np.fft.rfftfreq(len(x), 1.0 / fs)
    out = []
    for fc in OCTAVES_HZ:
        sel = (f >= fc / np.sqrt(2)) & (f < fc * np.sqrt(2))
        e = spec[sel].sum() * 2 / len(x) ** 2
        out.append(round(float(10 * np.log10(e + 1e-30)), 2))
    return out


def balance(pan: float) -> tuple[float, float]:
    """The session's balance law (varimu-app session::balance) at 0 dB."""
    p = min(max(pan, -1.0), 1.0)
    return min(1.0, 1.0 - p), min(1.0, 1.0 + p)


def render(
    scene: Scene,
    out_dir: Path,
    *,
    solo: bool = False,
    workers: int | None = None,
    log: Callable[[str], None] = print,
) -> dict:
    """The scene's prints into out_dir (the module docstring); returns render.json's data."""
    from varimu.sim.io import write_audio

    t0 = time.perf_counter()
    s = _settings(scene.quality)
    fs = s.sample_rate
    signals = source_signals(scene, fs)
    log(f"room: {len(scene.sources)} sources x {len(scene.mics)} mics")
    p, kinds, n = mic_pressures(scene, fs, signals)
    log(f"room responses in {time.perf_counter() - t0:.1f} s")

    jobs = []  # (mic index, source index or None)
    for mi in range(len(scene.mics)):
        jobs.append((mi, None))
        if solo and len(scene.sources) > 1:
            jobs += [(mi, si) for si in range(len(scene.sources))]
    done = np.zeros(len(jobs))

    def run(j: int) -> np.ndarray:
        mi, si = jobs[j]
        m = scene.mics[mi]
        sel = slice(None) if si is None else slice(si, si + 1)
        front, rear = p[sel, mi, 0].sum(0), p[sel, mi, 1].sum(0)

        def prog(f: float) -> None:
            done[j] = f
            log(f"progress {done.mean():.4f}")

        return print_chain(m.chain, m.set, front, rear, scene.quality, prog)

    workers = workers or max(1, min(len(jobs), (os.cpu_count() or 4) - 2))
    with ThreadPoolExecutor(workers) as ex:
        outs = list(ex.map(run, range(len(jobs))))

    out_dir.mkdir(parents=True, exist_ok=True)
    result: dict[str, Any] = {
        "scene": scene.name,
        "fs": fs,
        "quality": scene.quality,
        "rt60_s": dict(zip(map(str, (125, 250, 500, 1000, 2000, 4000, 8000)),
                           np.round(scene.room.rt60_s(), 3).tolist(), strict=True)),
        "mics": [],
    }  # fmt: skip
    mix = np.zeros((2, n))
    for j, (mi, si) in enumerate(jobs):
        m = scene.mics[mi]
        y = outs[j]
        if si is None:
            f = out_dir / f"{_safe(m.name)}.wav"
            write_audio(f, y.astype(np.float32), fs)
            gl, gr = balance(m.pan)
            mix[0, : len(y)] += gl * y
            mix[1, : len(y)] += gr * y
            result["mics"].append(
                {
                    "name": m.name,
                    "file": f.name,
                    "chain": m.chain,
                    "set": m.set,
                    "pan": m.pan,
                    "entries": kinds[mi],
                    "rms_dbfs": round(_db(y), 2),
                    "peak_dbfs": round(float(20 * np.log10(np.max(np.abs(y)) + 1e-15)), 2),
                }
            )
        else:
            src = scene.sources[si]
            f = out_dir / f"{_safe(m.name)}__{_safe(src.name)}.wav"
            write_audio(f, y.astype(np.float32), fs)
    if solo and len(scene.sources) > 1:
        for mi in range(len(scene.mics)):
            full = outs[jobs.index((mi, None))]
            solos = [outs[jobs.index((mi, si))] for si in range(len(scene.sources))]
            entry = result["mics"][mi]
            entry["bleed"] = {
                src.name: {"rms_dbfs": round(_db(y), 2), "octaves_db": octave_levels_db(y, fs)}
                for src, y in zip(scene.sources, solos, strict=True)
            }
            entry["intermod_db"] = round(_db(full - sum(solos)) - _db(full), 2)
    write_audio(out_dir / "mix.wav", mix.T.astype(np.float32), fs)
    result["mix"] = "mix.wav"
    result["octaves_hz"] = list(OCTAVES_HZ)
    result["wall_s"] = round(time.perf_counter() - t0, 1)
    result["seconds"] = round(n / fs, 3)
    (out_dir / "render.json").write_text(json.dumps(result, indent=1), encoding="utf-8")
    log("done")
    return result


def _safe(name: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in name).strip("_") or "mic"
