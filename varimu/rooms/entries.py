"""A capsule's entries as a table over incidence (ROOM_LOOP_PLAN.md R1): the front and
rear entries' pressure per pascal of the free-field pressure at the capsule's centre, on a
grid of frequency x distance x angle to the capsule's axis, so a room's thousands of
arrivals each find theirs by interpolation.

A capsule's body is a body of revolution about its axis (varimu.mics.bor), so an arrival
needs only its angle to the axis and its distance (a point source: proximity); a plane
wave is distance infinity, 1 / r = 0. The grid is linear in angle (2.5 deg) and in 1 / r
(the near field's terms are powers of 1 / (k r)): distances from 0.1 m out. Closer than
that is clamped to 0.1 m (`MIN_DISTANCE_M`).

By the capsule component's geometry, as `free_field.capsule_entry_pressures` picks:
- a `body`: the BEM (`bor.entry_table`: one system per frequency for every incidence),
  cached in cache/diffraction/ by the geometry, the grid and bor.py's source; a ball
  grille's (form `ball`, the SM58) with the grille a permeable sheet
  (`bor_permeable.entry_table`);
- else a `path_m`: two entries `path_m` apart on the axis in free field (a point source's
  spherical wave to each, the plane wave's path delay in the limit);
- else a pressure capsule: one entry, the free field (rear = front).
A capsule with a fitted sphere (K47@2) is refused: K47@3 supersedes it.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from varimu.config import REPO_ROOT
from varimu.devices.capsule import C_AIR

THETA_STEP_DEG = 2.5
DISTANCES_M = (0.1, 0.14, 0.2, 0.3, 0.45, 0.7, 1.0, 1.6, 2.5, 4.0, np.inf)
MIN_DISTANCE_M = DISTANCES_M[0]
N_FREQ = 240
F_MIN_HZ = 5.0
CACHE = REPO_ROOT / "cache" / "diffraction"


@dataclass(frozen=True)
class EntryTable:
    """front / rear: (freqs, inverse distances, angles), complex, per pascal at the centre.
    `f_hz` is a log grid (DC is 1 exactly, `at` adds it); `inv_r` ascending from 0."""

    f_hz: np.ndarray
    theta_rad: np.ndarray
    inv_r: np.ndarray
    front: np.ndarray
    rear: np.ndarray
    kind: str

    def at(self, theta_rad: np.ndarray, distance_m: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """The entries for arrivals (theta, distance), (arrivals, freqs) each on
        `f_grid` (f_hz with 0 Hz first: 1 there): bilinear in angle and 1 / r."""
        th = np.clip(np.atleast_1d(theta_rad), 0.0, np.pi)
        d = np.maximum(np.atleast_1d(distance_m), MIN_DISTANCE_M)
        ir = np.where(np.isinf(d), 0.0, 1.0 / d)
        ia = np.clip(th / self.theta_rad[1], 0, len(self.theta_rad) - 1 - 1e-9)
        a0 = ia.astype(int)
        wa = ia - a0
        b0 = np.clip(np.searchsorted(self.inv_r, ir, side="right") - 1, 0, len(self.inv_r) - 2)
        wb = np.clip((ir - self.inv_r[b0]) / (self.inv_r[b0 + 1] - self.inv_r[b0]), 0, 1)
        out = []
        for t in (self.front, self.rear):
            v = (
                t[:, b0, a0] * ((1 - wa) * (1 - wb))
                + t[:, b0, a0 + 1] * (wa * (1 - wb))
                + t[:, b0 + 1, a0] * ((1 - wa) * wb)
                + t[:, b0 + 1, a0 + 1] * (wa * wb)
            ).T  # (arrivals, freqs)
            out.append(np.hstack([np.ones((len(th), 1), complex), v]))
        return out[0], out[1]

    @property
    def f_grid(self) -> np.ndarray:
        return np.r_[0.0, self.f_hz]


def _grid(fs: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    f = np.unique(np.r_[np.geomspace(F_MIN_HZ, fs / 2, N_FREQ), fs / 2])
    th = np.radians(np.arange(0.0, 180.0 + 1e-9, THETA_STEP_DEG))
    d = np.array(sorted(DISTANCES_M, reverse=True))  # inf first: 1 / r ascending
    return f, th, d


def _path_table(path_m: float, f, th, d) -> tuple[np.ndarray, np.ndarray]:
    """Two entries +-path / 2 on the axis in free field, per pascal at the centre."""
    k = 2 * np.pi * f[:, None, None] / C_AIR
    h = 0.5 * path_m
    out = []
    for z in (h, -h):
        if path_m == 0:
            out.append(np.ones((len(f), len(d), len(th)), complex))
            continue
        rows = []
        for dist in d:
            if np.isinf(dist):
                rows.append(np.exp(1j * k[:, 0, :] * z * np.cos(th)[None, :]))
            else:
                re = np.sqrt(dist**2 + z**2 - 2 * dist * z * np.cos(th))
                rows.append(dist / re[None, :] * np.exp(-1j * k[:, 0, :] * (re - dist)[None, :]))
        out.append(np.stack(rows, axis=1))
    return out[0], out[1]


def entry_table(geometry: dict, fs: float) -> EntryTable:
    """The table for a capsule component's geometry (the module docstring) up to fs / 2."""
    f, th, d = _grid(fs)
    inv_r = np.where(np.isinf(d), 0.0, 1.0 / d)
    a = geometry.get("diaphragm", {}).get("radius_m")
    if "body" in geometry:
        from varimu.mics import bor, bor_permeable

        ball = geometry["body"].get("form") == "ball"
        src = (Path(bor.__file__)).read_bytes() + Path(__file__).read_bytes()
        if ball:
            src += Path(bor_permeable.__file__).read_bytes()
        key = json.dumps([geometry["body"], a, f.tolist(), th.tolist(), inv_r.tolist()])
        h = hashlib.sha256(src + key.encode()).hexdigest()[:24]
        path = CACHE / f"table_{h}.npz"
        if path.exists():
            z = np.load(path)
            front, rear = z["front"], z["rear"]
        else:
            if ball:
                body = geometry["body"]
                op = bor_permeable.operator(bor_permeable.ball_mesh(body, a))
                front, rear = bor_permeable.entry_table(op, f, body["z_s_pa_s_m"], th, d)
            else:
                op = bor.operator(bor.body_mesh(geometry["body"], a))
                front, rear = bor.entry_table(op, f, th, d)
            path.parent.mkdir(parents=True, exist_ok=True)
            np.savez(path, front=front, rear=rear)
        kind = f"body {geometry['body']}"
    elif "sphere_radius_m" in geometry:
        raise ValueError("a capsule with a fitted sphere (K47@2) has no room table: use its body")
    else:
        path_m = float(geometry.get("path_m", 0.0) or 0.0)
        front, rear = _path_table(path_m, f, th, d)
        kind = f"path {path_m}" if path_m else "pressure"
    return EntryTable(f, th, inv_r, front, rear, kind)
