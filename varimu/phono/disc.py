"""A lateral disc groove (docs/PHONO_PLAN.md §1 and §3, G2): a shellac 78's spiral, its
two walls, the tip's dilation against each wall, the pivoted arm's tracking error, a
steel needle grinding itself flat, scratches.

**The spiral.** A groove of pitch p wound inward from radius r0: r = r0 - p theta / 2 pi,
arc length s = integral r dtheta (the radial component is p / 2 pi r ~ 4e-4 of it), so
r(s) = sqrt(r0^2 - p s / pi) and theta(s) = 2 pi (r0 - r(s)) / p. A turntable turning at
w passes arc length w r(s) per second under the needle: the groove slows toward the
label (0.95 m/s at a 10 in record's outer groove, ~0.5 near the label).

**The groove.** A lateral ("needle-cut") groove is the cutter's V swept along the spiral,
its centre line displaced sideways by y(s): one value per arc sample, like the cylinder's
height. Its walls are planes at +-`wall_angle` from the vertical; each wall's position
along its own inward normal n = (+-sin a, cos a) (lateral, up) is +-sin(a) y(s) (the apex's
depth is a constant, absorbed into the tip's rest position). A tip resting in the groove
touches each wall at one point.

**Reading by dilation, per wall.** A wall is a surface whose offset along a fixed normal
varies along s only: the distance from a sphere's centre to it is a 2-D problem in the
(s, normal) plane, so the tip's coordinate along each wall's normal follows that wall's
profile dilated by the tip's section (groove.dilate), exactly for a spherical tip. A
lateral excursion moves the walls apart along their normals in opposite senses: the
tip's lateral position is their difference, its height their sum (the pinch effect:
the tip rides up twice a cycle where the groove's slope narrows it).

**Tracking error.** The needle swings on a line set by the soundbox's angle on a pivoted
arm, phi(r) away from the groove's radius (arm length L, pivot d from the spindle, offset
beta: sin(phi + beta) = (r^2 + L^2 - d^2) / (2 r L)). A tip displaced u along that line
sits u sin(phi) along the groove and u cos(phi) across it, so it reads the groove at
s + y tan(phi) and moves y / cos(phi): `tracking_remap`. Its distortion is the classic
second harmonic ~ (tan phi) k y / 2.

**The steel needle.** A steel needle is ground by the shellac's abrasive filler to the
groove's walls in its first revolutions (Copeland; rfwilmut.net "steel needles ... wear
down to fit the groove"). Archard's law on a cone cut flat by a wall: the worn volume
~ a^3 grows linearly with the distance slid, so a flat's half-length along the groove is
a(s) = a_side (s / s_side)^(1/3): fast at first, slower later. A worn tip is a flat of
half-length a with the point's radius at its ends (`worn_profile`): detail shorter than
the flat is averaged away (the treble a steel needle loses through a side), and the flat
traces a groove's crests differently from its troughs.
"""

from __future__ import annotations

import zlib
from dataclasses import dataclass

import numpy as np

from varimu.phono import groove as gv


@dataclass
class Spiral:
    r0_m: float  # the radius where the excerpt's groove starts
    pitch_m: float  # groove to groove, radially

    def radius(self, s_m) -> np.ndarray:
        return np.sqrt(np.maximum(self.r0_m**2 - self.pitch_m * np.asarray(s_m) / np.pi, 0.0))

    def theta(self, s_m) -> np.ndarray:
        return 2 * np.pi * (self.r0_m - self.radius(s_m)) / self.pitch_m

    def turns_s(self, theta0: float, s_end_m: float) -> np.ndarray:
        """The arc lengths where the groove passes angle theta0 (mod 2 pi) before s_end."""
        t_end = float(self.theta(s_end_m))
        k = np.arange(
            np.ceil((0 - theta0) / (2 * np.pi)), np.floor((t_end - theta0) / (2 * np.pi)) + 1
        )
        th = theta0 + 2 * np.pi * k
        th = th[(th >= 0) & (th <= t_end)]
        r = self.r0_m - self.pitch_m * th / (2 * np.pi)
        return (self.r0_m**2 - r**2) * np.pi / self.pitch_m


@dataclass
class LateralGroove:
    y_m: np.ndarray  # the centre line's lateral displacement per arc sample
    ds_m: float
    spiral: Spiral

    @property
    def length_m(self) -> float:
        return len(self.y_m) * self.ds_m

    def s_m(self) -> np.ndarray:
        return np.arange(len(self.y_m)) * self.ds_m


def arc_positions(
    omega: np.ndarray,
    theta: np.ndarray,
    fs_hz: float,
    spiral: Spiral,
    eccentric_m: float,
    phase: float,
) -> np.ndarray:
    """Arc length passed under the needle per sample: ds/dt = w (r(s) + e sin(theta + phase))
    (an off-centre hole e: the contact's radius swings once a turn, cylinder.py's
    `surface_speed` geometry). r(s) changes ~4e-4 per metre of groove: a fixed point on
    the cumulative sum converges in a few passes."""
    h = 1.0 / fs_hz
    ecc = eccentric_m * np.sin(theta + phase)
    s = np.concatenate([[0.0], np.cumsum(omega[:-1] * h * spiral.r0_m)])
    for _ in range(6):
        v = omega * (spiral.radius(s) + ecc)
        s_new = np.concatenate([[0.0], np.cumsum(0.5 * (v[1:] + v[:-1]) * h)])
        if np.max(np.abs(s_new - s)) < 1e-12:
            s = s_new
            break
        s = s_new
    return s


def tracking_angle(r_m, arm_m: float, pivot_m: float, offset_rad: float = 0.0) -> np.ndarray:
    """phi(r): the needle's line of motion off the groove's radius for an arm of length
    `arm_m` pivoted `pivot_m` from the spindle (offset beta)."""
    r = np.asarray(r_m, dtype=float)
    x = (r * r + arm_m * arm_m - pivot_m * pivot_m) / (2 * r * arm_m)
    return np.arcsin(np.clip(x, -1.0, 1.0)) - offset_rad


def tracking_remap(y_m: np.ndarray, ds_m: float, phi: np.ndarray) -> np.ndarray:
    """The lateral excursion along the needle's line, read where the tip actually sits:
    y(s + y tan phi) / cos phi."""
    s = np.arange(len(y_m)) * ds_m
    return np.interp(s + y_m * np.tan(phi), s, y_m) / np.cos(phi)


def walls(y_m: np.ndarray, wall_angle_rad: float) -> tuple[np.ndarray, np.ndarray]:
    """Each wall's position along its inward normal: (left, right)."""
    k = np.sin(wall_angle_rad)
    return k * y_m, -k * y_m


def worn_profile(u_m: np.ndarray, edge_radius_m: float, flat_half_m) -> np.ndarray:
    """A worn needle's section along the groove: 0 on its flat |u| <= a, the point's
    radius beyond it (out to a + R), -inf further (can't touch)."""
    a = np.asarray(flat_half_m, dtype=float)
    out = np.abs(u_m) - a
    r = edge_radius_m
    prof = np.where(out <= 0.0, 0.0, np.sqrt(np.maximum(r * r - out * out, 0.0)) - r)
    return np.where(out > r, -np.inf, prof)


def dilate_worn(w_m: np.ndarray, ds_m: float, edge_radius_m: float, flat_half_m) -> np.ndarray:
    """The tip's coordinate along a wall's normal (resting on it) for a needle whose flat
    half-length may vary per sample (a scalar or one value per sample of w): the grayscale
    dilation of w by `worn_profile`. A zero flat is groove.dilate's sphere."""
    w = np.asarray(w_m, dtype=float)
    n = len(w)
    a = np.broadcast_to(np.asarray(flat_half_m, dtype=float), (n,))
    relief = float(np.max(w) - np.min(w)) if n else 0.0
    r = edge_radius_m
    reach_edge = np.sqrt(max(2.0 * r * relief - relief**2, 0.0)) if relief < r else r
    reach = float(np.max(a)) + reach_edge + 2 * ds_m
    kmax = int(np.ceil(reach / ds_m))
    pad = kmax
    wp = np.concatenate([np.full(pad, w[0]), w, np.full(pad, w[-1])])
    out = np.full(n, -np.inf)
    for k in range(-kmax, kmax + 1):
        b = worn_profile(np.full(n, k * ds_m), r, a)
        np.maximum(out, wp[pad + k : pad + k + n] + b, out=out)
    return out


def needle_flat(s_m, flat_after_side_m: float, side_m: float) -> np.ndarray:
    """A new steel needle's flat half-length after sliding s along the groove (Archard on
    a cone: a^3 ~ s)."""
    return flat_after_side_m * np.cbrt(np.maximum(np.asarray(s_m, dtype=float), 0.0) / side_m)


def rng(seed: int, name: str) -> np.random.Generator:
    return np.random.default_rng([seed, zlib.crc32(name.encode())])


def scratches(
    wl: np.ndarray, wr: np.ndarray, ds_m: float, spiral: Spiral, d: dict, seed: int
) -> int:
    """Scratches across the record (in place): each meets the groove once a turn at its
    angle, a gouge `scratch_width_m` wide and `scratch_depth_m` deep in both walls with
    raised burrs `scratch_burr_m` high at its edges (the tick of a scratched 78)."""
    count = int(d["scratches"])
    g = rng(seed, "scratches")
    end = len(wl) * ds_m
    half = d["scratch_width_m"] / 2
    burr = d["scratch_burr_m"]
    for _ in range(count):
        theta0 = g.uniform(0, 2 * np.pi)
        depth = d["scratch_depth_m"] * g.uniform(0.5, 1.5)
        for s0 in spiral.turns_s(theta0, end):
            i0 = int((s0 - 2 * half) / ds_m)
            i1 = int((s0 + 2 * half) / ds_m) + 1
            i0, i1 = max(i0, 0), min(i1, len(wl))
            if i1 <= i0:
                continue
            u = (np.arange(i0, i1) * ds_m - s0) / half
            # A rounded gouge with burrs thrown up on either side.
            shape = np.where(
                np.abs(u) <= 1.0,
                -depth * (1 - u * u),
                burr * np.maximum(1.0 - (np.abs(u) - 1.5) ** 2 / 0.25, 0.0),
            )
            wl[i0:i1] += shape
            wr[i0:i1] += shape
    return count


def roughness_pair(n: int, ds_m: float, sigma_m: float, corr_m: float, seed: int):
    """Independent seeded roughness on each wall (groove.roughness)."""
    return (
        gv.roughness(n, ds_m, sigma_m, corr_m, seed, "wall left"),
        gv.roughness(n, ds_m, sigma_m, corr_m, seed, "wall right"),
    )
