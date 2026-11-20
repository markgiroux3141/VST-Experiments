"""A stereo microgroove (docs/PHONO_PLAN.md, "The 1960s record player"): the 45/45 groove's
geometry, the cutter's vertical angle, a spiral of variable pitch.

**45/45.** A stereo groove is a 90 degree V whose walls each carry one channel (the
Westrex system, standardized by the RIAA in 1958: the left channel on the inner wall,
equal in-phase signals moving the groove laterally, so a mono record plays on a stereo
player and the reverse). In disc.py's convention a wall's position is its offset along
its own inward normal n = (+-sin a, cos a) (lateral, up): a cutter displaced (x, z) moves
the left wall by sin(a) x + cos(a) z and the right by -sin(a) x + cos(a) z. A channel is
the cutter's motion along one wall's normal, signed so that equal channels are lateral:
A = wall_left, B = -wall_right, so x = (A + B) / (2 sin a), z = (A - B) / (2 cos a); at
a = 45 degrees each channel's unit excursion is 1 / sqrt(2) lateral and 1 / sqrt(2)
vertical. The difference L - R is the groove's depth: a vertical excursion the cutter
can lift out of the lacquer with (`lift_outs`).

**The vertical angle.** A cutter's vertical motion isn't vertical: its stylus moves on a
line inclined by the vertical tracking angle beta toward the groove's direction (Westrex
3D: ~23 degrees; the 1964 IEC / RIAA recommendation 15 degrees), so a tip raised z sits
z tan(beta) along the groove (`incline`, tracking_remap's geometry turned on its side).
A player whose stylus moves at another angle reads the vertical channel with a second
harmonic: vertical tracking distortion.

**Variable pitch.** A lathe's feed per turn is set from the program a turn ahead (the
preview head) so that neighbouring turns keep a land between them: the spacing between
turn k and the next must clear each one's half width plus its largest lateral excursion
on that turn (`variable_pitch`). The spiral is then a table, r and theta per arc length
(`TableSpiral`, disc.Spiral's interface).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


def walls(x_m: np.ndarray, z_m: np.ndarray, wall_angle_rad: float):
    """Each wall's position along its inward normal for a cutter at (x, z): (left, right)."""
    s, c = np.sin(wall_angle_rad), np.cos(wall_angle_rad)
    return s * x_m + c * z_m, -s * x_m + c * z_m


def channels_to_xz(a_m: np.ndarray, b_m: np.ndarray, wall_angle_rad: float):
    """(x, z) from the channels' excursions along their walls' normals (A left, B right)."""
    s, c = np.sin(wall_angle_rad), np.cos(wall_angle_rad)
    return (a_m + b_m) / (2 * s), (a_m - b_m) / (2 * c)


def xz_to_channels(x_m: np.ndarray, z_m: np.ndarray, wall_angle_rad: float):
    left, right = walls(x_m, z_m, wall_angle_rad)
    return left, -right


def incline(s_m: np.ndarray, z_m: np.ndarray, beta_rad: float) -> np.ndarray:
    """Arc positions of a stylus at nominal positions s raised z on a line inclined beta
    toward the groove's direction (positive: the tip trails as it rises)."""
    return np.asarray(s_m) + np.asarray(z_m) * np.tan(beta_rad)


def resample_on_grid(s_m: np.ndarray, values: list[np.ndarray], ds_m: float):
    """Values known at increasing positions s, interpolated onto a uniform grid from 0.
    Refuses positions that turn back (a cutter's incline steeper than the groove)."""
    if np.any(np.diff(s_m) <= 0):
        raise ValueError("the stylus' positions turn back along the groove")
    grid = np.arange(int(np.floor((s_m[-1] - max(s_m[0], 0.0)) / ds_m))) * ds_m + max(s_m[0], 0.0)
    return grid, [np.interp(grid, s_m, v) for v in values]


def lift_outs(z_m: np.ndarray, depth_m: float) -> float:
    """The fraction of samples where the cutter's upward excursion exceeds the groove's
    mean depth (the groove vanishes: an engineer keeps L - R's bass down for this)."""
    return float(np.mean(np.asarray(z_m) > depth_m))


@dataclass
class TableSpiral:
    """A spiral given as radius and angle per arc length (uniform grid ds)."""

    s_m: np.ndarray
    r_m: np.ndarray
    theta: np.ndarray

    @property
    def r0_m(self) -> float:
        return float(self.r_m[0])

    def radius(self, s_m) -> np.ndarray:
        return np.interp(s_m, self.s_m, self.r_m)

    def angle(self, s_m) -> np.ndarray:
        return np.interp(s_m, self.s_m, self.theta)

    def turns_s(self, theta0: float, s_end_m: float) -> np.ndarray:
        """The arc lengths where the groove passes angle theta0 (mod 2 pi) before s_end."""
        t_end = float(self.angle(s_end_m))
        k = np.arange(np.ceil(-theta0 / (2 * np.pi)), np.floor((t_end - theta0) / (2 * np.pi)) + 1)
        th = theta0 + 2 * np.pi * k
        th = th[(th >= self.theta[0]) & (th <= t_end)]
        return np.interp(th, self.theta, self.s_m)


def variable_pitch(
    theta: np.ndarray,
    excursion_m: np.ndarray,
    width_m: np.ndarray,
    land_m: float,
    pitch_min_m: float,
    pitch_max_m: float,
    smooth_turns: float = 0.25,
) -> np.ndarray:
    """The radial feed per sample (m, positive inward) for a cut at angles theta (per
    sample, increasing), whose lateral excursion |x| and groove width are given per
    sample: per turn, the spacing to the next turn is the larger of pitch_min and each
    angle's need (this turn's and the next's half widths plus their excursions plus the
    land), capped at pitch_max (the lead screw's range), and changed smoothly over
    `smooth_turns` (the feed motor's servo). Returns the radial position's decrement per
    sample, summing to the radius travelled."""
    theta = np.asarray(theta, dtype=float)
    turn = np.floor((theta - theta[0]) / (2 * np.pi)).astype(int)
    n_turns = int(turn[-1]) + 1
    # Per turn: the largest outward reach (half width + excursion) in each of 64 sectors.
    sectors = 64
    sec = np.floor(((theta - theta[0]) % (2 * np.pi)) / (2 * np.pi) * sectors).astype(int)
    sec = np.minimum(sec, sectors - 1)
    reach = np.zeros((n_turns + 1, sectors))
    np.maximum.at(reach, (turn, sec), 0.5 * np.asarray(width_m) + np.abs(excursion_m))
    need = reach[:-1] + reach[1:] + land_m  # turn k to k + 1, per sector
    pitch_turn = np.clip(need.max(axis=1), pitch_min_m, pitch_max_m)
    # The feed per turn, as a function of angle: steps between turns smoothed.
    frac = (theta - theta[0]) / (2 * np.pi)
    centres = np.arange(n_turns) + 0.5
    p = np.interp(frac, centres, pitch_turn)
    if smooth_turns > 0:
        span = smooth_turns
        k = int(max(1, round(span / max(np.median(np.diff(frac)), 1e-12))))
        if k > 1:
            pad = np.concatenate([np.full(k, p[0]), p, np.full(k, p[-1])])
            c = np.cumsum(np.concatenate([[0.0], pad]))
            p = (c[2 * k + 1 :] - c[: -2 * k - 1])[: len(p)] / (2 * k + 1)
            p = p[: len(theta)]
    dtheta = np.diff(theta, prepend=theta[0])
    return p * dtheta / (2 * np.pi)
