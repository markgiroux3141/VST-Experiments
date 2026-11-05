"""The room's GPU kernels (docs/ROOM_LOOP_PLAN.md R9-R10): crates/roomsim (wgpu) through its
Python module `roomsim`, with a backend per call:

- `"gpu"`: the GPU (f32; ray sums in exact fixed point, so a run repeats bit for bit);
- `"cpu"`: roomsim's f64 CPU reference (the same algorithm and random numbers);
- `"numpy"`: the original Python reference (varimu.rooms.polyroom / shoebox), with its own
  random numbers (rays agree with the others in their statistics only).

`backend()` picks the default: `$VARIMU_ROOM_BACKEND` if set, else "gpu" when roomsim is
installed and a GPU opens, else "numpy" (said once on stderr). roomsim is part of the `fast`
extra (`uv sync --extra fast`); like circuitsim, a build older than the working tree's
sources is refused (`StaleBuild`).
"""

from __future__ import annotations

import os
import sys
from functools import cache

import numpy as np

from varimu.config import REPO_ROOT

CRATE_DIR = REPO_ROOT / "crates" / "roomsim"
BACKENDS = ("gpu", "cpu", "numpy")


class StaleBuild(RuntimeError):
    """The installed roomsim was built from other sources than the working tree's."""


def source_hash() -> str:
    """crates/roomsim/build.rs's hash: FNV-1a 64 over Cargo.toml, src/**/*.rs and
    src/**/*.wgsl (sorted by relative path) as path, 0, bytes, 0."""
    files = [
        CRATE_DIR / "Cargo.toml",
        *(CRATE_DIR / "src").rglob("*.rs"),
        *(CRATE_DIR / "src").rglob("*.wgsl"),
    ]
    named = sorted((p.relative_to(CRATE_DIR).as_posix(), p) for p in files)
    h = 0xCBF29CE484222325
    for name, path in named:
        for b in name.encode() + b"\0" + path.read_bytes() + b"\0":
            h = ((h ^ b) * 0x100000001B3) & 0xFFFFFFFFFFFFFFFF
    return f"{h:016x}"


@cache
def module():
    """roomsim, checked against the working tree; None when it isn't installed."""
    try:
        import roomsim
    except ImportError:
        return None
    if CRATE_DIR.exists() and roomsim.SOURCE_HASH != (now := source_hash()):
        raise StaleBuild(
            f"roomsim was built from sources {roomsim.SOURCE_HASH}, the working tree has "
            f"{now}: rebuild with `uv sync --extra fast` (name every extra you use) or run "
            "through `uv run --extra fast ...`"
        )
    return roomsim


@cache
def gpu_info() -> str | None:
    """The GPU's name and backend, or None (no roomsim, no GPU)."""
    m = module()
    if m is None:
        return None
    try:
        return m.gpu_info()
    except RuntimeError:
        return None


@cache
def backend() -> str:
    env = os.environ.get("VARIMU_ROOM_BACKEND")
    if env:
        if env not in BACKENDS:
            raise ValueError(f"VARIMU_ROOM_BACKEND={env!r}: one of {BACKENDS}")
        return env
    if gpu_info() is not None:
        return "gpu"
    why = "roomsim isn't installed (uv sync --extra fast)" if module() is None else "no GPU"
    print(f"varimu.rooms: {why}; the room runs on numpy", file=sys.stderr)
    return "numpy"


def resolve(b: str | None) -> str:
    b = b or backend()
    if b not in BACKENDS:
        raise ValueError(f"room backend {b!r}: one of {BACKENDS}")
    if b != "numpy" and module() is None:
        raise RuntimeError(f"room backend {b!r} needs roomsim: uv sync --extra fast")
    return b


def ray_trace(room, source, dirs, receivers, t_max_s, fs_env, radius_m, c, seed, b, weights=None):
    """roomsim.ray_trace on a PolyRoom: (travelling (bands, nt), density (rx, bands, nt));
    `weights` (rays, bands) each ray's starting energy (a directional source)."""
    from varimu.rooms.shoebox import ROOM_MATERIALS

    tris, tri_face = room.triangles()
    mats = room.materials()
    from varimu.rooms.polyroom import SCATTERING

    normals = np.array([f.normal for f in room.faces], float)
    alpha = np.array([ROOM_MATERIALS[m] for m in mats], float)
    scat = np.array([SCATTERING.get(m, 0.1) for m in mats], float)
    rx = np.asarray(receivers, float).reshape(-1, 3)
    trav, dens, nt = module().ray_trace(
        np.ascontiguousarray(tris, float).ravel(),
        np.ascontiguousarray(tri_face, np.uint32),
        normals.ravel(),
        alpha.ravel(),
        scat,
        rx.ravel(),
        np.asarray(source, float),
        np.ascontiguousarray(dirs, float).ravel(),
        float(t_max_s),
        float(fs_env),
        float(radius_m),
        float(c),
        int(seed) & 0xFFFFFFFF,
        backend=b,
        weights=None if weights is None else np.ascontiguousarray(weights, float).ravel(),
    )
    nb = alpha.shape[1]
    return np.asarray(trav).reshape(nb, nt), np.asarray(dens).reshape(len(rx), nb, nt)


def image_spectra(
    coarse: np.ndarray,
    delay_samples: np.ndarray,
    idx,
    w,
    n_fft: int,
    b: str,
    spec_index: np.ndarray | None = None,
    scale: np.ndarray | None = None,
):
    """roomsim.image_spectra: coarse (spectra, entries, grid) complex -> (entries, bins);
    with `spec_index` and `scale` (per image) images share spectra (crates/roomsim
    spectra.rs)."""
    n_img, n_ent, n_grid = coarse.shape
    c = np.empty((n_img, n_ent, n_grid, 2))
    c[..., 0], c[..., 1] = coarse.real, coarse.imag
    out = module().image_spectra(
        c.ravel(),
        n_ent,
        n_grid,
        np.ascontiguousarray(delay_samples, float),
        np.ascontiguousarray(idx, np.uint32),
        np.ascontiguousarray(w, float),
        int(n_fft),
        backend=b,
        spec_index=None if spec_index is None else np.ascontiguousarray(spec_index, np.uint32),
        scale=None if scale is None else np.ascontiguousarray(scale, float),
    )
    out = np.asarray(out).reshape(n_ent, len(idx), 2)
    return out[..., 0] + 1j * out[..., 1]
