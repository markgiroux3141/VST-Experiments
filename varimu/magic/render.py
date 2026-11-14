"""A clip through a circuit with the mechanisms switchable (noise, heaters, cores), cached
(ANALOG_MAGIC_FABLE.md AM0).

`varimu.sim.runner` can't pass `noise=` or `heaters=` to the builder, so this builds and runs
directly (the pattern of scripts/reverb_listen.py) and keeps its own cache in
cache/magic/renders/ keyed by everything that decides the output: the circuit file's bytes,
the overrides, the quality, the mechanism switches, the origin, explicit settings, the input,
the controls, circuitsim's SOURCE_HASH and VERSION here.

Also the tape machine without a circuit (`tape_print`: varimu.devices.tape_machine.print_audio,
its grain and transport seeded apart) and the aligned Ampex 351 as a circuit (`ampex_351`), each
cached the same way.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import threading
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import numpy as np

from varimu.config import REPO_ROOT
from varimu.sim.io import TransientSettings

VERSION = 1  # bump when what a cached file holds changes
CACHE = REPO_ROOT / "cache" / "magic" / "renders"
_lock = threading.RLock()  # re-entered: ampex_351_setup -> sample_rate -> settings
_build_lock = threading.Lock()
_settings_cache: dict[str, TransientSettings] = {}


def settings(quality: str = "production") -> TransientSettings:
    with _lock:
        if quality not in _settings_cache:
            _settings_cache[quality] = TransientSettings.from_sim_settings(
                engine="circuitsim", quality=quality
            )
        return _settings_cache[quality]


def sample_rate() -> int:
    return settings().sample_rate


def _source_hash() -> str:
    import circuitsim

    return str(getattr(circuitsim, "SOURCE_HASH", ""))


def _key(parts: Sequence[Any], arrays: Sequence[np.ndarray]) -> str:
    h = hashlib.sha256()
    h.update(json.dumps([repr(p) for p in parts]).encode())
    for a in arrays:
        h.update(np.ascontiguousarray(a, dtype="<f8").tobytes())
        h.update(b"|")
    return h.hexdigest()[:32]


def _cached(key: str, cache: bool, make: Callable[[], dict[str, np.ndarray]]):
    path = CACHE / f"{key}.npz"
    if cache and path.exists():
        with np.load(path) as z:
            return {k: z[k] for k in z.files}
    out = make()
    if cache:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(f".{os.getpid()}.{threading.get_ident()}.tmp.npz")
        np.savez(tmp, **out)
        os.replace(tmp, path)
    return out


def through(
    circuit: str,
    x: np.ndarray,
    *,
    overrides: Mapping[str, Any] | None = None,
    quality: str = "production",
    noise: bool | int | None = None,
    heaters: bool | str | None = None,
    cores: str | None = None,
    origin_s: float = 0.0,
    controls: Mapping[str, np.ndarray] | None = None,
    settings: TransientSettings | None = None,
    probes: Sequence[str] = ("out",),
    cache: bool = True,
    progress: Callable[[float], None] | None = None,
) -> dict[str, np.ndarray]:
    """x (dBFS scale, at the settings' sample rate) through config/circuits/<circuit>.yaml;
    each probe's output on the dBFS scale (the circuit's own full scale, varimu.sim.io)."""
    from varimu.circuit import builder, spec
    from varimu.sim import fast
    from varimu.sim.io import full_scale

    st = settings if settings is not None else globals()["settings"](quality)
    path = spec.circuit_path(circuit)
    ov = dict(overrides or {})
    ctl = {k: np.asarray(v, float) for k, v in sorted((controls or {}).items())}
    x = np.asarray(x, float)
    key = _key(
        [
            "through",
            VERSION,
            hashlib.sha256(Path(path).read_bytes()).hexdigest(),
            json.dumps(ov, sort_keys=True, default=str),
            quality,
            noise,
            heaters,
            cores,
            origin_s,
            repr(settings) if settings is not None else None,
            list(ctl),
            list(probes),
            _source_hash(),
        ],
        [x, *ctl.values()],
    )

    def make() -> dict[str, np.ndarray]:
        c = spec.load_circuit(path)
        v_in, v_out = full_scale(st, c)
        # One build at a time: varimu.devices.table.cached_table's file replace races
        # between threads building the same tube tables (WinError 32).
        with _build_lock:
            built = builder.build(
                c,
                ov,
                triode_formulation=st.triode_formulation,
                cores=cores if cores is not None else st.cores,
                noise=noise,
                heaters=heaters,
            )
        r = fast.run_transient(
            built.ir,
            x * v_in,
            settings=st,
            controls=ctl or None,
            origin_s=origin_s,
            progress=progress,
        )
        return {p: np.asarray(r.vectors[f"v({p})"], float) / v_out for p in probes}

    return _cached(key, cache, make)


def through_many(jobs: Sequence[dict], workers: int | None = None) -> list[dict]:
    """`through(**job)` for each job on a thread pool (runner.default_jobs() workers);
    a job with "fn" calls that function instead (tape_print, ampex_351) with the rest."""
    from varimu.sim.runner import default_jobs

    def one(job: dict) -> dict:
        job = dict(job)
        fn = job.pop("fn", through)
        return fn(**job)

    with ThreadPoolExecutor(workers or default_jobs()) as ex:
        return list(ex.map(one, jobs))


# --- The tape machine without a circuit -----------------------------------------------


_tape_setup: dict[tuple, Any] = {}


def tape_setup(speed_ips: float = 15.0, tape_name: str = "SCOTCH111@3"):
    """(spec, tape, alignment) as scripts/tape_print.py makes them (demag_iterations 8)."""
    from varimu.devices import library
    from varimu.devices.tape_machine import TapeMachineSpec, aligned

    k = (speed_ips, tape_name)
    with _lock:
        if k not in _tape_setup:
            tape = library.load_tape(tape_name)
            sp = TapeMachineSpec().at_speed(speed_ips * 0.0254)
            al = aligned(sp, tape, REPO_ROOT / "cache" / "tape")
            _tape_setup[k] = (dataclasses.replace(sp, demag_iterations=8), tape, al)
        return _tape_setup[k]


def tape_print(
    x: np.ndarray,
    *,
    drive_db: float = 0.0,
    noise_seed: int | None = None,
    transport_seed: int = 0,
    flutter: bool = True,
    speed_ips: float = 15.0,
    tape_name: str = "SCOTCH111@3",
    cache: bool = True,
) -> dict[str, np.ndarray]:
    """x (dBFS scale, at the project's rate) recorded and played back by the idealized tape
    machine (print_audio): {"out": y}, the heads' delay already taken out."""
    from varimu.devices.tape_machine import print_audio

    fs = sample_rate()
    x = np.asarray(x, float)
    key = _key(
        [
            "tape_print",
            VERSION,
            drive_db,
            noise_seed,
            transport_seed,
            flutter,
            speed_ips,
            tape_name,
            fs,
            _source_hash(),
            _code_hash("varimu/devices/tape_machine.py"),
        ],
        [x],
    )

    def make() -> dict[str, np.ndarray]:
        sp, tape, al = tape_setup(speed_ips, tape_name)
        sp = dataclasses.replace(sp, flutter=flutter)
        y = print_audio(
            x,
            fs,
            sp,
            tape,
            al,
            drive_db=drive_db,
            noise_seed=noise_seed,
            transport_seed=transport_seed,
        )
        return {"out": np.asarray(y, float)}

    return _cached(key, cache, make)


def _code_hash(rel: str) -> str:
    return hashlib.sha256((REPO_ROOT / rel).read_bytes()).hexdigest()[:16]


# --- The aligned Ampex 351 as a circuit -----------------------------------------------


_a351: dict[str, Any] = {}


def ampex_351_setup() -> dict[str, Any]:
    """The 351's alignment (varimu.measure.tape_align.aligned: cached in cache/tape/, ~32 min
    when it isn't), its circuit and the heads' delay in samples (scripts/print_351.py)."""
    from varimu.circuit import spec
    from varimu.measure import tape_align as ta

    with _lock:
        if not _a351:
            al = ta.aligned()
            c = spec.load_circuit(spec.circuit_path(ta.CIRCUIT))
            p = spec.resolve(c, al.overrides)
            fs = sample_rate()
            _a351.update(
                circuit=ta.CIRCUIT,
                overrides=dict(al.overrides),
                delay=int(round(p["head_distance_m"] / p["speed_m_s"] * fs)),
            )
        return dict(_a351)


def ampex_351(
    x: np.ndarray,
    *,
    drive_db: float = 0.0,
    noise: bool | int | None = None,
    origin_s: float = 0.0,
    tail_s: float = 0.5,
    gpu: bool = True,
    cache: bool = True,
    progress: Callable[[float], None] | None = None,
) -> dict[str, np.ndarray]:
    """x (dBFS scale) printed through the aligned 351 (cores "ja", as print_351.py), the
    heads' delay taken out: {"out": y} of len(x) + tail_s. `noise` as the builder's (None:
    the file's block, seed 1: grain, transport, hiss and hum together; False: none). `gpu`:
    the tape's recording kernel on the GPU (TAPE_SPEED_PLAN.md P5: -117 dB from the f64
    kernel, ~2x faster)."""
    setup = ampex_351_setup()
    st = settings("production")
    if gpu:
        st = dataclasses.replace(st, tape_gpu=True)
    fs = st.sample_rate
    d = setup["delay"]
    n_tail = int(tail_s * fs)
    xp = np.concatenate([np.asarray(x, float), np.zeros(d + n_tail)]) * 10 ** (drive_db / 20)
    r = through(
        setup["circuit"],
        xp,
        overrides=setup["overrides"],
        noise=noise,
        cores="ja",
        origin_s=origin_s,
        settings=st,
        cache=cache,
        progress=progress,
    )
    return {"out": r["out"][d : d + len(x) + n_tail]}
