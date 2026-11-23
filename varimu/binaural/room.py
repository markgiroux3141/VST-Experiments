"""A virtual head in a room (docs/BINAURAL_PLAN.md): its two ears as two "mics" of the room
engine (varimu.rooms.shoebox.responses), each with a direction-dependent table instead of a
capsule's, so every image source, diffracted path and plane wave of the diffuse tail reaches
each ear through that ear's HRTF from the direction it arrives from.

`HeadEar` is the table: `directional = True` tells the room engine to pass each arrival's
unit vector (toward where it comes from) and distance (`at_dirs`) instead of its angle to
the mic's aim. Both mics sit at the head's centre (the HRTF is relative to the free field
there). An arrival nearer than `NEAR_M` gets the near-field HRTF at its own distance (the SH
extrapolation, varimu.binaural.sphere; at least the receivers' radius), farther ones the far
field. The ears are diffuse-field equalized (as a dummy head for recording is: a Neumann
KU 100 is), so a pair of headphones tuned near the diffuse field plays them neutrally
(varimu.binaural.render's docstring).

For the wave solver below a crossover (varimu.rooms.wave), which fits a capsule to first
order in the angle to its aim, `at(theta, r)` is the ear's response averaged round its own
axis (the mic's aim is the ear's outward axis): a head is nearly a sphere at those
wavelengths.
"""

from __future__ import annotations

import numpy as np

from varimu.binaural.hrtf import F_STOP_HZ, F_TOP_HZ
from varimu.binaural.render import diffuse_field_eq

NEAR_M = 2.0


class HeadEar:
    directional = True
    kind = "head_ear"

    def __init__(
        self,
        head,
        ear: str,
        forward,
        up=(0.0, 0.0, 1.0),
        fs: float = 96_000.0,
        eq: np.ndarray | None = None,
    ):
        self.head = head
        self.ear = 0 if ear == "left" else 1
        f = np.asarray(head.f_hz, float)
        self.f_hz = f
        self._f_grid = np.r_[f, fs / 2]
        fw = np.asarray(forward, float)
        upv = np.asarray(up, float)
        fw = fw - (fw @ upv) * upv
        self.x = fw / np.linalg.norm(fw)
        self.z = upv / np.linalg.norm(upv)
        self.y = np.cross(self.z, self.x)  # left
        w = np.ones_like(f)
        roll = (f > F_TOP_HZ) & (f < F_STOP_HZ)
        w[roll] = 0.5 + 0.5 * np.cos(np.pi * (f[roll] - F_TOP_HZ) / (F_STOP_HZ - F_TOP_HZ))
        w[f >= F_STOP_HZ] = 0.0
        g = eq[self.ear] if eq is not None else 1.0
        self.gain = w * g

    def key_bytes(self) -> bytes:
        """What the room responses' cache key hashes for this table (varimu/rooms/scene.py):
        the head's data, the ear, its orientation and its equalization."""
        from varimu.binaural.heads import digest

        parts = [digest(self.head).encode(), bytes([self.ear])]
        parts += [np.ascontiguousarray(a, np.float64).tobytes() for a in (self.x, self.z)]
        parts.append(np.ascontiguousarray(self.gain, np.float64).tobytes())
        parts.append(np.ascontiguousarray(self._f_grid, np.float64).tobytes())
        return b"|".join(parts)

    @property
    def f_grid(self) -> np.ndarray:
        return self._f_grid

    @property
    def axis(self) -> np.ndarray:
        """The ear's outward axis (world)."""
        return self.y if self.ear == 0 else -self.y

    def _azel(self, u: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        az = np.degrees(np.arctan2(u @ self.y, u @ self.x))
        el = np.degrees(np.arcsin(np.clip(u @ self.z, -1, 1)))
        return az, el

    def at_dirs(self, u: np.ndarray, distance_m: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """(front, rear) entries (arrivals, f_grid) for unit vectors u (toward the arrivals'
        origins) at distances: the ear's pressure per pascal at the head's centre (a
        pressure "capsule": rear = front)."""
        u = np.atleast_2d(np.asarray(u, float))
        r = np.broadcast_to(np.asarray(distance_m, float), (len(u),))
        az, el = self._azel(u)
        out = np.zeros((len(u), len(self._f_grid)), complex)
        far = ~(r < NEAR_M)
        if far.any():
            out[far, :-1] = self.head.tf(az[far], el[far])[self.ear]
        rmin = getattr(getattr(self.head, "left", None), "radius_m", None)
        for i in np.flatnonzero(~far):
            d = float(max(r[i], rmin)) if rmin is not None else None
            out[i, :-1] = self.head.tf(az[i : i + 1], el[i : i + 1], d)[self.ear, 0]
        out[:, :-1] *= self.gain
        return out, out

    def at(self, theta_rad, distance_m):
        """The ear's response at angle theta to its axis, averaged round the axis (the wave
        solver's first-order fit; varimu.rooms.wave.first_order_entries)."""
        th = np.atleast_1d(np.asarray(theta_rad, float))
        a = self.axis
        b = self.x
        c = np.cross(a, b)
        psi = np.linspace(0, 2 * np.pi, 12, endpoint=False)
        u = np.cos(th)[:, None, None] * a + np.sin(th)[:, None, None] * (
            np.cos(psi)[None, :, None] * b + np.sin(psi)[None, :, None] * c
        )
        f, _ = self.at_dirs(u.reshape(-1, 3), np.full(u.shape[0] * u.shape[1], np.inf))
        e = f.reshape(len(th), len(psi), -1).mean(axis=1)
        return e, e


def head_mics(head, position_m, facing_deg: float = 0.0, eq: bool = True):
    """The head's two ears as varimu.rooms.shoebox.Mic's at `position_m`, its nose toward
    azimuth `facing_deg` in the floor plane (counter-clockwise from +x)."""
    from varimu.rooms.shoebox import Mic, aim_vector

    fwd = aim_vector(facing_deg, 0.0)
    g = (
        (head.diffuse_field_eq() if hasattr(head, "diffuse_field_eq") else diffuse_field_eq(head))
        if eq
        else None
    )
    out = []
    for ear in ("left", "right"):
        t = HeadEar(head, ear, fwd, eq=g)
        out.append(Mic(np.asarray(position_m, float), t.axis, t))
    return out
