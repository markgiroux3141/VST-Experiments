"""A recording scene (ROOM_LOOP_PLAN.md R3): a room, sources placed in it, mics placed and
aimed, each through its chain (a mic + preamp circuit file), and the render: every mic's
two entry pressures from the room (varimu.rooms.shoebox), printed through its chain.

A scene file (YAML or JSON; `config/scenes/*.yaml`, the native app's Room view writes
JSON):

    name: two_sources
    room:
      # preset: treated_studio         # a room from config/rooms/ (varimu.rooms.presets);
                                       # the keys below, if given, replace the preset's
      dims_m: [7.0, 5.5, 3.2]          # a shoebox (varimu.rooms.shoebox), or:
      # floor_m: [[0, 0], [7, 0], [6, 5.5], [0, 5]]   # any floor plan (polyroom), with
      # ceiling: {type: gable, height_m: 2.8, peak_m: 4.5, axis_deg: 0, facets: 8}
      #   (flat | shed | gable | vault; varimu/rooms/polyroom.py)
      materials: {walls: furnished_wall, floor: wood_floor, ceiling: gypsum_on_studs}
        # a shoebox may give one per surface: {x0, x1, y0, y1, floor, ceiling}; a floor
        # plan its faces' own (ROOM_LOOP_PLAN.md R7), over the three:
        #   faces: {"wall 2": heavy_drapes, "ceiling 0": acoustic_tile, floor: carpet_on_pad}
        #   ("wall N" runs from the floor's corner N to N + 1, "ceiling N" is a facet)
      objects:                       # boxes in the room (R11; varimu/rooms/polyroom.py): a gobo
        - {name: gobo, center_m: [3.5, 2.7, 0.9], size_m: [1.2, 0.08, 1.8], yaw_deg: 90,
           tilt_deg: 0, material: heavy_drapes}   # width, depth, height; their edges diffract
      source: "provisional: ..."
    sources:
      - name: A
        clip: data/clips/x.wav       # relative to the repo, or absolute
        start_s: 0                   # optional, and seconds: N
        spl_db: 90                   # its rms while it sounds (gated) in dB SPL at 1 m in
                                     # free field (on its axis)
        position_m: [2.0, 2.5, 1.2]
        directivity: amp_1x12        # optional: omni (the default), voice, amp_1x12, amp_2x12,
                                     # bass_1x15, or {sphere_radius_m, cap_radius_m}
                                     # (varimu/rooms/directivity.py: a cap on a sphere)
        aim: {azimuth_deg: 0, elevation_deg: 0}   # where it faces (a directional source)
    mics:
      - name: spot A
        chain: u47_v76               # a circuit file with a capsule or cartridge: any
                                     # mic x preamp of scripts/compose_chain.py --all
        position_m: [2.0, 2.2, 1.2]
        aim: {azimuth_deg: 90, elevation_deg: 0}   # counterclockwise from +x
        set: {pattern_u47: 0, gain_db_v76: 40}     # the chain's controls and values
        pan: -0.5                    # -1 left .. 1 right (the session's balance law)
    settings: {quality: production, ism_s: 0.08, seed: 0, tail_s: null,
               wave_crossover_hz: 500}   # the wave solver below 500 Hz (varimu.rooms.wave,
                                         # ROOM_LOOP_PLAN.md R10); absent or null: off

The sources' clips are mono (any rate, resampled to the project's), each scaled to its
SPL, so a source is the free-field sound pressure 1 m away (pascals). The SPL is its rms
while it sounds (`sounding_rms`, BS.1770's gates on 50 ms blocks; since 2026-11-05: the
plain rms counted a part's silences, so a sparse part came out louder than its number).
Mic positions are kept 0.1 m from sources (the entry tables' nearest distance,
varimu.rooms.entries).

`render(scene)` writes, in its output folder: each mic's print `<mic>.wav` (mono float32 at
the project's rate, the chain's out at its full scale), `mix.wav` (stereo, the mics
panned), and `render.json` (the files, pans, levels, timing). With `solo=True` it also
prints each source alone through every mic (`<mic>__<source>.wav`): the room is linear, so
those give the **bleed matrix** (each mic's level of each source, in total and per octave
band), and the sum minus the solos says how much the chains' nonlinearity mixed the
sources (`intermod_db`). Prints are cached in cache/rooms/prints/ by the built IR, the
inputs, the settings and circuitsim's source. The room's responses (per unit source: no
audio, no levels) are cached in cache/rooms/responses/ by the room, the places, the tables,
the settings and the code (`_responses_key`), so a render that changes only levels or
takes skips the room's physics.
"""

from __future__ import annotations

import dataclasses
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
from varimu.rooms.polyroom import PolyRoom
from varimu.rooms.shoebox import SURFACES, Mic, Shoebox, aim_vector, responses

P_REF = 20e-6
CACHE = REPO_ROOT / "cache" / "rooms" / "prints"
RESPONSES = REPO_ROOT / "cache" / "rooms" / "responses"
RESPONSES_KEEP = 12  # scenes' room responses kept (~50-150 MB each)
# the modules the room responses come from (_responses_key)
RESPONSE_CODE = ("shoebox", "polyroom", "wave", "diffraction", "directivity", "materials", "gpu")
OCTAVES_HZ = (63, 125, 250, 500, 1000, 2000, 4000, 8000, 16000)


@dataclass
class SourceSpec:
    name: str
    clip: Path
    spl_db: float
    position_m: np.ndarray
    start_s: float = 0.0
    seconds: float | None = None
    directivity: object = None
    azimuth_deg: float = 0.0
    elevation_deg: float = 0.0


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
    room: Shoebox | PolyRoom
    sources: list[SourceSpec]
    mics: list[MicSpec]
    quality: str = "production"
    ism_s: float = 0.08
    seed: int = 0
    tail_s: float | None = None
    room_source: str = ""
    wave_crossover_hz: float | None = None


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
    from varimu.rooms.presets import resolve

    r = resolve(d["room"])
    if "floor_m" in r:
        m = r["materials"]
        ce = r.get("ceiling") or {}
        room = PolyRoom(
            [[float(x), float(y)] for x, y in r["floor_m"]],
            ce.get("type", "flat"),
            float(ce.get("height_m", 3.0)),
            None if ce.get("peak_m") is None else float(ce["peak_m"]),
            float(ce.get("axis_deg", 0.0)),
            int(ce.get("facets", 8)),
            m["walls"],
            m["floor"],
            m["ceiling"],
            float(r.get("temp_c", 20.0)),
            float(r.get("rh_percent", 50.0)),
            {str(k): str(v) for k, v in (m.get("faces") or {}).items()},
            list(r.get("objects") or []),
        )
    else:
        room = Shoebox(
            tuple(float(x) for x in r["dims_m"]),
            _materials(r["materials"]),
            float(r.get("temp_c", 20.0)),
            float(r.get("rh_percent", 50.0)),
        )
        if r.get("objects"):  # objects need the polygon room: the shoebox as its rectangle
            from varimu.rooms.wave import poly_of

            room = poly_of(room, list(r["objects"]))
    sources = [
        SourceSpec(
            s["name"],
            _path(s["clip"]),
            float(s["spl_db"]),
            np.array(s["position_m"], float),
            float(s.get("start_s", 0.0)),
            None if s.get("seconds") is None else float(s["seconds"]),
            s.get("directivity"),
            float((s.get("aim") or {}).get("azimuth_deg", 0.0)),
            float((s.get("aim") or {}).get("elevation_deg", 0.0)),
        )
        for s in d["sources"]
    ]
    from varimu.rooms.directivity import from_spec

    for s in sources:
        from_spec(s.directivity)  # unknown presets fail at load
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
        None if not st.get("wave_crossover_hz") else float(st["wave_crossover_hz"]),
    )


def _capsule_geometry(chain: str, over: dict) -> dict:
    from varimu.circuit import spec
    from varimu.devices.library import component_data

    q = spec.resolve(spec.load_circuit(spec.circuit_path(chain)), over)
    keys = [k for k in q if str(k).startswith(("capsule_model", "cartridge_model"))]
    if not keys:
        raise ValueError(
            f"chain {chain} has no capsule (a `capsule_model*` or `cartridge_model*` value)"
        )
    return component_data(str(q[keys[0]])).get("geometry", {})


def _settings(quality: str):
    from varimu.sim.io import TransientSettings

    return TransientSettings.from_sim_settings(
        engine="circuitsim", quality=None if quality == "production" else quality
    )


GATE_BLOCK_S = 0.05  # gating blocks, overlapping by half
GATE_ABSOLUTE_DB = -70.0  # re the loudest block (a clip has no absolute level)
GATE_RELATIVE_DB = -10.0  # re the mean of the blocks above the absolute gate


def sounding_rms(x: np.ndarray, fs: float) -> float:
    """x's rms while it sounds: BS.1770's two gates (absolute, here re the loudest block, and
    -10 dB relative) without its K-weighting (a sound pressure level is unweighted), on 50 ms
    blocks instead of its 400 ms (blocks straddling a note's ends pass the gate and pull the
    level down: 400 ms read 250 ms notes 3.8 dB low, 50 ms 0.4 dB). Silence before, after and
    between a part's notes doesn't count, so a sparse part at 80 dB is as loud while it plays
    as a continuous one at 80 dB. Clips shorter than a block: their plain rms. The native
    app's room::sounding_rms is the same."""
    x = np.asarray(x, float)
    block = int(round(GATE_BLOCK_S * fs))
    hop = block // 2  # (not round(): Rust's rounds halves the other way)
    if len(x) < block or block < 1:
        return float(np.sqrt(np.mean(x**2))) if len(x) else 0.0
    c = np.r_[0.0, np.cumsum(x**2)]
    starts = np.arange(0, len(x) - block + 1, hop)
    ms = (c[starts + block] - c[starts]) / block
    top = ms.max()
    if top <= 0:
        return 0.0
    ms = ms[ms > top * 10 ** (GATE_ABSOLUTE_DB / 10)]
    ms = ms[ms > ms.mean() * 10 ** (GATE_RELATIVE_DB / 10)]
    return float(np.sqrt(ms.mean()))


def source_signals(scene: Scene, fs: int) -> list[np.ndarray]:
    """Each source's free-field pressure 1 m away (pascals), at fs: its clip scaled so its
    rms while it sounds (`sounding_rms`) is its SPL."""
    from varimu.sim.io import load_audio

    out = []
    for s in scene.sources:
        x = load_audio(s.clip, fs)
        x = x[int(s.start_s * fs) :]
        if s.seconds is not None:
            x = x[: int(s.seconds * fs)]
        x = x - np.mean(x)
        rms = sounding_rms(x, fs)
        if rms == 0:
            raise ValueError(f"source {s.name}: its clip is silent")
        out.append(x * (P_REF * 10 ** (s.spl_db / 20) / rms))
    return out


def _fftconv(x: np.ndarray, h: np.ndarray, n_out: int) -> np.ndarray:
    """x * h, n_out samples long: cut, or zero-padded past the full convolution (a
    source shorter than the scene's longest)."""
    m = 1 << int(np.ceil(np.log2(len(x) + len(h))))
    y = np.fft.irfft(np.fft.rfft(x, m) * np.fft.rfft(h, m), m)[:n_out]
    return np.pad(y, (0, n_out - len(y)))


def mic_pressures(
    scene: Scene, fs: int, signals: list[np.ndarray], log: Callable[[str], None] | None = None
) -> tuple[np.ndarray, list[str], int]:
    """Per source and mic the entries' pressures, (sources, mics, 2, samples): each
    source's signal convolved with its room response; and the tables' kinds, and the
    length (the longest source plus the room's tail)."""
    from varimu.rooms.progress import Step

    h, kinds = scene_responses(scene, fs, log)
    n = max(len(x) for x in signals) + h.shape[-1]
    p = np.zeros((len(scene.sources), len(scene.mics), 2, n))
    nm = len(scene.mics)
    sizes = [1 << int(np.ceil(np.log2(len(x) + h.shape[-1]))) for x in signals]
    works = [2 * m * np.log2(m) for m in sizes for _ in range(nm)]
    conv = Step(log, "convolution", "convolve", works)
    for si, x in enumerate(signals):
        for mi in range(nm):
            conv.start(si * nm + mi, f"source {si + 1} -> mic {mi + 1}, {len(x) / fs:.1f} s "
                                     f"of audio, {sizes[si]:,}-point FFTs")  # fmt: skip
            for e in range(2):
                p[si, mi, e] = _fftconv(x, h[si, mi, e], n)
    conv.end()
    return p, kinds, n


def scene_responses(
    scene: Scene, fs: int, log: Callable[[str], None] | None = None
) -> tuple[np.ndarray, list[str]]:
    """The room's responses from each source to each mic's two entries per unit source,
    (sources, mics, 2, samples) (cached: `_cached_responses`), and the tables' kinds."""
    from varimu.rooms.directivity import from_spec
    from varimu.rooms.progress import fmt_s

    tables, kinds = {}, []
    mics = []
    for mi, m in enumerate(scene.mics):
        for s in scene.sources:
            if np.linalg.norm(m.position_m - s.position_m) < MIN_DISTANCE_M:
                raise ValueError(f"mic {m.name} is closer than {MIN_DISTANCE_M} m to {s.name}")
            dv = from_spec(s.directivity)
            if dv is not None:  # its body: a sphere a radius behind the cap
                centre = s.position_m - dv.centre_offset_m * aim_vector(
                    s.azimuth_deg, s.elevation_deg
                )
                if np.linalg.norm(m.position_m - centre) < dv.centre_offset_m:
                    raise ValueError(f"mic {m.name} is inside {s.name}'s body (its cabinet / head)")
        geom = _capsule_geometry(m.chain, m.set)
        key = json.dumps(geom, sort_keys=True, default=str)
        if key not in tables:
            if log:
                log(f"capsule table {len(tables) + 1}: mic {mi + 1}'s ({m.chain}): from the "
                    "cache, or a BEM solve the first time (minutes)")  # fmt: skip
            t1 = time.perf_counter()
            tables[key] = entry_table(geom, fs)
            dt = time.perf_counter() - t1
            if log:
                how = "from the cache" if dt < 1 else f"solved in {fmt_s(dt)}, cached now"
                log(f"capsule table {len(tables)}: {how}")
        kinds.append(tables[key].kind)
        mics.append(Mic(m.position_m, aim_vector(m.azimuth_deg, m.elevation_deg), tables[key]))
    seeds = [scene.seed * 1000 + i for i in range(len(scene.sources))]
    from varimu.rooms.directivity import from_spec

    dirs = [from_spec(s.directivity) for s in scene.sources]
    directivity = [
        None if dv is None else (dv, aim_vector(s.azimuth_deg, s.elevation_deg))
        for dv, s in zip(dirs, scene.sources, strict=True)
    ]
    kw = {
        "ism_s": scene.ism_s,
        "length_s": scene.tail_s,
        "seeds": seeds,
        "tail": not _anechoic(scene.room),
        "wave": (
            {"crossover_hz": scene.wave_crossover_hz}
            if scene.wave_crossover_hz and not _anechoic(scene.room)
            else None
        ),
        "directivity": directivity if any(directivity) else None,
    }
    return _cached_responses(scene, mics, fs, kw, log), kinds


def _plain(x: Any) -> Any:
    """x as JSON-able data for a cache key (arrays as lists, dataclasses as their fields)."""
    if dataclasses.is_dataclass(x) and not isinstance(x, type):
        return {f.name: _plain(getattr(x, f.name)) for f in dataclasses.fields(x) if f.init}
    if isinstance(x, np.ndarray):
        return x.tolist()
    if isinstance(x, dict):
        return {str(k): _plain(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_plain(v) for v in x]
    if isinstance(x, (str, int, float, bool)) or x is None:
        return x
    return repr(x)


def _responses_key(scene: Scene, mics: list[Mic], fs: int, kw: dict) -> str:
    """The room responses' cache key: everything shoebox.responses reads (the room, the
    sources' places, patterns and seeds, the mics' places, aims and entry tables, the
    settings, the backend) and the code it runs (varimu/rooms, the separation room's bands
    and materials, roomsim's build). Not the sources' audio or levels: the room is linear."""
    from varimu.rooms import gpu

    hsh = hashlib.sha256()
    here = Path(__file__).parent
    for f in RESPONSE_CODE:
        hsh.update((here / f"{f}.py").read_bytes())
    hsh.update((here.parent / "separation" / "room.py").read_bytes())
    mod = gpu.module()
    backend = gpu.backend()
    data = {
        "room": _plain(scene.room),
        "sources": [s.position_m.tolist() for s in scene.sources],
        "directivity": [
            None if d is None else [_plain(d[0]), d[1].tolist()] for d in (kw["directivity"] or [])
        ],
        "mics": [[m.position_m.tolist(), m.aim.tolist()] for m in mics],
        "fs": fs,
        "kw": {k: v for k, v in kw.items() if k != "directivity"},
        "backend": backend,
        "roomsim": getattr(mod, "SOURCE_HASH", None) if backend != "numpy" else None,
    }
    hsh.update(json.dumps(data, sort_keys=True, default=str).encode())
    for t in {id(m.table): m.table for m in mics}.values():
        for a in (t.f_hz, t.theta_rad, t.inv_r, t.front, t.rear):
            hsh.update(np.ascontiguousarray(a).tobytes())
    return hsh.hexdigest()[:32]


def _cached_responses(scene: Scene, mics: list[Mic], fs: int, kw: dict, log) -> np.ndarray:
    """shoebox.responses for the scene, from cache/rooms/responses/ when the room, the
    places and the settings are unchanged (a change of level or audio skips the room's
    physics: the rays, reflections, diffraction and the wave solver). The newest
    `RESPONSES_KEEP` entries are kept."""
    key = _responses_key(scene, mics, fs, kw)
    path = RESPONSES / f"{key}.npy"
    if path.exists():
        try:
            h = np.load(path)
            os.utime(path)  # the newest: kept longest
            if log:
                log("room responses: from the cache (the room and its places unchanged)")
            return h
        except (OSError, ValueError):
            pass  # a torn file: compute it again
    wave = kw["wave"] and {**kw["wave"], "log": log}
    h = responses(
        scene.room,
        [s.position_m for s in scene.sources],
        mics,
        fs,
        **{**kw, "wave": wave},
        log=log,
    )
    try:
        RESPONSES.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(f".{os.getpid()}.tmp.npy")
        np.save(tmp, h)
        os.replace(tmp, path)
        old = sorted(RESPONSES.glob("*.npy"), key=lambda p: p.stat().st_mtime, reverse=True)
        for p in old[RESPONSES_KEEP:]:
            p.unlink(missing_ok=True)
    except OSError:
        pass  # a cache is a convenience: never fail a render over it
    return h


def _anechoic(room) -> bool:
    if isinstance(room, PolyRoom):
        return all(m == "anechoic" for m in room.materials())
    return any(m == "anechoic" for m in room.materials)


def rt60_s(room, source_m=None) -> np.ndarray:
    """The room's reverberation time per band: Eyring for a shoebox, ray-traced for a
    PolyRoom (from `source_m`, else the floor's centroid at 1.3 m)."""
    if isinstance(room, PolyRoom):
        from varimu.rooms.polyroom import ray_decay, rt60_from_decay

        src = source_m if source_m is not None else np.r_[room.floor.mean(0), 1.3]
        return rt60_from_decay(*ray_decay(room, np.asarray(src, float), 4.0, n_rays=8000))
    return room.rt60_s()


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
    from varimu.rooms import gpu
    from varimu.rooms.progress import Countdown, fmt_s
    from varimu.sim.io import write_audio

    t0 = time.perf_counter()
    s = _settings(scene.quality)
    fs = s.sample_rate
    log(f"room: {len(scene.sources)} sources x {len(scene.mics)} mics")
    log("sources: " + ", ".join(f"{i + 1} {x.name}" for i, x in enumerate(scene.sources)))
    log("mics: " + ", ".join(f"{i + 1} {m.name} ({m.chain})" for i, m in enumerate(scene.mics)))
    signals = source_signals(scene, fs)
    longest = max(len(x) for x in signals) / fs
    log(f"clips loaded in {fmt_s(time.perf_counter() - t0)}, the longest {fmt_s(longest)}")
    p, kinds, n = mic_pressures(scene, fs, signals, log)
    log(f"room responses in {fmt_s(time.perf_counter() - t0)}")

    jobs = []  # (mic index, source index or None)
    for mi in range(len(scene.mics)):
        jobs.append((mi, None))
        if solo and len(scene.sources) > 1:
            jobs += [(mi, si) for si in range(len(scene.sources))]
    done = np.zeros(len(jobs))
    workers = workers or max(1, min(len(jobs), (os.cpu_count() or 4) - 2))
    log(f"chains: {len(jobs)} prints of {fmt_s(n / fs)} at {scene.quality} on {workers} threads")
    countdown = Countdown(log, "chains")

    def run(j: int) -> np.ndarray:
        mi, si = jobs[j]
        m = scene.mics[mi]
        sel = slice(None) if si is None else slice(si, si + 1)
        front, rear = p[sel, mi, 0].sum(0), p[sel, mi, 1].sum(0)

        def prog(f: float) -> None:
            done[j] = f
            log(f"progress {done.mean():.4f}")
            countdown.update(float(done.mean()))

        return print_chain(m.chain, m.set, front, rear, scene.quality, prog)

    t1 = time.perf_counter()
    with ThreadPoolExecutor(workers) as ex:
        outs = list(ex.map(run, range(len(jobs))))
    log(f"chains: done in {fmt_s(time.perf_counter() - t1)}")

    out_dir.mkdir(parents=True, exist_ok=True)
    log("writing: RT60s, the mics' files and the mix")
    result: dict[str, Any] = {
        "scene": scene.name,
        "fs": fs,
        "quality": scene.quality,
        "rt60_s": dict(zip(map(str, (125, 250, 500, 1000, 2000, 4000, 8000)),
                           np.round(rt60_s(scene.room, scene.sources[0].position_m),
                                    3).tolist(), strict=True)),
        "room": "polygon" if isinstance(scene.room, PolyRoom) else "shoebox",
        "room_backend": gpu.backend(),
        "gpu": gpu.gpu_info(),
        "wave_crossover_hz": scene.wave_crossover_hz,
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
