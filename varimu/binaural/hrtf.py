"""A head's HRTF set (docs/BINAURAL_PLAN.md): simulated from its mesh (varimu.binaural.solve),
kept as each ear's SH coefficients on the receivers' sphere, so it gives any direction at any
distance >= the sphere (near-field HRTFs for sources close to the head) or the far field.

**Normalization** (as a measured HRTF is): each ear's field over the field of the same grid
with no head and the source at the head's centre (one "reference" run per grid, cached),
both extrapolated the same way, so the grid's own dispersion and the source's normalization
divide out. At 0 Hz the HRTF is 1 (set; the gated records can't resolve it).

**Time.** A transfer function is relative to the sound's arrival at the head's centre; an
HRIR (`hrirs`) is delayed by `LEAD_S` so the ear nearer a source (up to ~0.7 ms early) stays
causal. A renderer delays the sound to the centre by (distance / c) - LEAD_S.

**The band.** Above `F_TOP_HZ` the grid's staircase and dispersion stop being trusted (the
rigid sphere's check: within 0.3 dB to 20 kHz on the ear's side, 2-4 dB high in the far ear's
shadow above 10 kHz); the response rolls off with a raised cosine from F_TOP_HZ to F_STOP_HZ.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np

from varimu.binaural.mesh import Mesh
from varimu.binaural.solve import C_M_S, RunSpec, ear_point, run, spectra
from varimu.binaural.sphere import ShField, gauss_grid, sph_from_azel, transform

CACHE = Path(__file__).resolve().parents[2] / "cache" / "binaural"
LEAD_S = 1.0e-3
F_TOP_HZ = 18_000.0
F_STOP_HZ = 22_000.0
RECEIVER_RADIUS_M = 0.185
N_OUT = 2048  # the spectra's FFT at fs_out (96 kHz: 47 Hz bins); kept to F_STOP_HZ
CODE_VERSION = "2"  # bump when the solver, the gating or the normalization changes


def default_spec(mesh: Mesh, dx_m: float = 0.001, half_m: float | None = None) -> RunSpec:
    """The receivers 1 cm outside the mesh's farthest point; the grid as big as the GPU binds
    one buffer (2 GiB: ~536 M cells), the records gated before the faces answer."""
    # one radius for every head that fits (so they share a reference run)
    r = max(RECEIVER_RADIUS_M, float(np.linalg.norm(mesh.vertices, axis=1).max()) + 0.01)
    k = 2 * np.pi * F_STOP_HZ / C_M_S
    order = int(np.ceil(k * r)) + 8
    if half_m is None:
        cells = int((536e6) ** (1 / 3)) // 2 - 1
        half_m = cells * dx_m
    t_max = (4 * half_m - 2 * r) / C_M_S  # beyond any receiver's first reflection
    return RunSpec(
        dx_m=dx_m,
        radius_m=r,
        order=order,
        half_m=half_m,
        sponge_m=0.03,
        g_max=0.05,
        duration_s=min(t_max, (2 * half_m + 0.1) / C_M_S),
    )


def _key(*parts) -> str:
    h = hashlib.sha256()
    for p in parts:
        h.update(p if isinstance(p, bytes) else json.dumps(p, sort_keys=True, default=str).encode())
    return h.hexdigest()[:20]


def _field(rec, spec: RunSpec) -> ShField:
    f, P = spectra(rec, N_OUT)
    keep = f <= F_STOP_HZ
    return transform(gauss_grid(spec.order), P[keep], f[keep], spec.radius_m, C_M_S)


def _save_field(path: Path, sh: ShField, **extra):
    path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        path,
        f=sh.f_hz,
        radius=sh.radius_m,
        order=sh.order,
        c=sh.c_m_s,
        coeffs=sh.coeffs.astype(np.complex64),
        **extra,
    )


def _load_field(path: Path) -> ShField:
    z = np.load(path)
    return ShField(
        z["f"], float(z["radius"]), int(z["order"]), z["coeffs"].astype(complex), float(z["c"])
    )


def reference(spec: RunSpec, log=print) -> ShField:
    """The no-head field of a source at the centre for this grid (cached)."""
    path = CACHE / "reference" / f"{_key(CODE_VERSION, asdict(spec))}.npz"
    if path.exists():
        return _load_field(path)
    if log:
        log("reference run (no head)")
    rec = run(None, spec, np.zeros(3), log=log)
    sh = _field(rec, spec)
    _save_field(path, sh)
    return sh


@dataclass
class HeadHrtf:
    name: str
    left: ShField
    right: ShField
    ref: ShField
    ears_m: dict

    @property
    def f_hz(self) -> np.ndarray:
        return self.left.f_hz

    def tf(self, az_deg, el_deg, distance_m: float | None = None) -> np.ndarray:
        """(2, points, F): left and right ears' transfer functions for sources at SOFA
        azimuths / elevations (deg), far field or `distance_m` from the centre."""
        th, ph = sph_from_azel(np.atleast_1d(az_deg), np.atleast_1d(el_deg))
        if distance_m is not None and distance_m < self.left.radius_m:
            raise ValueError(
                f"{distance_m} m: inside the receivers' sphere ({self.left.radius_m:.3f} m)"
            )
        ref = self.ref.at(th, ph, distance_m)
        out = np.stack(
            [self.left.at(th, ph, distance_m) / ref, self.right.at(th, ph, distance_m) / ref]
        )
        out[..., self.f_hz == 0] = 1.0
        return out

    def hrirs(
        self,
        az_deg,
        el_deg,
        fs: float = 96_000.0,
        n: int = 512,
        distance_m=None,
        gain: np.ndarray | None = None,
    ) -> np.ndarray:
        """(2, points, n) impulse responses at fs (fs must divide the stored grid's: the
        stored spectra are at 96 kHz / N_OUT), each delayed by LEAD_S. `gain` (2, F) real:
        a per-ear equalization (varimu.binaural.render.diffuse_field_eq)."""
        H = self.tf(az_deg, el_deg, distance_m)
        if gain is not None:
            H = H * gain[:, None, :]
        f = self.f_hz
        w = np.ones_like(f)
        roll = (f > F_TOP_HZ) & (f < F_STOP_HZ)
        w[roll] = 0.5 + 0.5 * np.cos(np.pi * (f[roll] - F_TOP_HZ) / (F_STOP_HZ - F_TOP_HZ))
        w[f >= F_STOP_HZ] = 0.0
        H = H * w * np.exp(-2j * np.pi * f * LEAD_S)
        fs_grid = 96_000.0  # the stored bins are an N_OUT-point grid at 96 kHz, cut at F_STOP_HZ
        full = np.zeros((*H.shape[:-1], N_OUT // 2 + 1), complex)
        full[..., : H.shape[-1]] = H
        h = np.fft.irfft(full, N_OUT, axis=-1)  # H is dimensionless: the DTFT of h at fs_grid
        if fs != fs_grid:
            from fractions import Fraction

            from scipy.signal import resample_poly

            q = Fraction(fs / fs_grid).limit_denominator(1000)
            h = resample_poly(h, q.numerator, q.denominator, axis=-1)
        return h[..., :n]

    def save(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(
            path,
            name=self.name,
            ears=json.dumps({k: list(map(float, v)) for k, v in self.ears_m.items()}),
            **{
                f"{s}_{k}": v
                for s, sh in (("L", self.left), ("R", self.right), ("ref", self.ref))
                for k, v in (
                    ("f", sh.f_hz),
                    ("radius", sh.radius_m),
                    ("order", sh.order),
                    ("c", sh.c_m_s),
                    ("coeffs", sh.coeffs.astype(np.complex64)),
                )
            },
        )

    @classmethod
    def load(cls, path: Path) -> HeadHrtf:
        z = np.load(path)

        def sh(s):
            return ShField(
                z[f"{s}_f"],
                float(z[f"{s}_radius"]),
                int(z[f"{s}_order"]),
                z[f"{s}_coeffs"].astype(complex),
                float(z[f"{s}_c"]),
            )

        ears = {k: np.array(v) for k, v in json.loads(str(z["ears"])).items()}
        return cls(str(z["name"]), sh("L"), sh("R"), sh("ref"), ears)


def cached_head(name: str) -> HeadHrtf | None:
    """The newest cached set saved under exactly `name` (not `name-variant`), or None."""
    import re

    pat = re.compile(re.escape(name) + r"_[0-9a-f]{20}\.npz")
    hits = sorted(
        (p for p in (CACHE / "heads").glob(f"{name}_*.npz") if pat.fullmatch(p.name)),
        key=lambda p: p.stat().st_mtime,
    )
    return HeadHrtf.load(hits[-1]) if hits else None


def simulate(mesh: Mesh, name: str, spec: RunSpec | None = None, log=print, ears=None) -> HeadHrtf:
    """Both ears' HRTFs (cached in cache/binaural/heads/ by mesh, spec and code version).
    `ears` overrides the ear points {"left": xyz, "right": xyz} (metres)."""
    spec = spec or default_spec(mesh)
    if ears is None:
        ears = {s: ear_point(mesh, s, spec.dx_m) for s in ("left", "right")}
    key = _key(
        CODE_VERSION,
        asdict(spec),
        mesh.vertices.tobytes(),
        mesh.faces.tobytes(),
        {k: list(map(float, v)) for k, v in ears.items()},
    )
    path = CACHE / "heads" / f"{name}_{key}.npz"
    if path.exists():
        return HeadHrtf.load(path)
    t0 = time.perf_counter()
    ref = reference(spec, log=log)
    fields = {}
    for side in ("left", "right"):
        if log:
            log(f"{name}: {side} ear at {np.round(ears[side], 4).tolist()}")
        rec = run(mesh, spec, ears[side], log=log)
        fields[side] = _field(rec, spec)
        del rec
    h = HeadHrtf(name, fields["left"], fields["right"], ref, ears)
    h.save(path)
    if log:
        log(f"{name}: done in {time.perf_counter() - t0:.0f} s -> {path}")
    return h
