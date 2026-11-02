"""A groove worn by earlier plays (docs/PHONO_PLAN.md §1 "Wear", G3): play count as an
aging variable, by Archard's wear law (Archard 1953, J. Appl. Phys. 24, 981): the depth
worn per distance slid is k p / H, k the wear coefficient, p the contact pressure, H the
wax's hardness. Each play the reproducer's tip slides the groove's whole length; its Hertz
patch presses hardest where the groove throws the tip upward, so the wear is uneven over a
waveform (the shape the next play reads is distorted) and spread over the patch (detail
finer than the patch rounds off: the treble a play takes away).

Per play, at positions every `stride` along the groove (quasi-statically: dozens of plays
in seconds):

    F  = F0 + m v^2 y''        the static load plus the tip's moving mass m times the
                               acceleration the dilated groove y forces on it at speed v
                               (0 where y'' asks for more than gravity gives: it flies)
    a  = (3 F R / 4 E*)^(1/3)  the Hertz patch's radius (R the tip's mean radius)
    p  = p0 sqrt(1 - u^2/a^2), p0 = 3 F / (2 pi a^2), along the patch around the contact
    dh = (k / H) p * stride    summed over the positions sliding past each groove point

A point on the uncut flat loses (k / H) 3 F0 / (4 a0) per play. k is set from the one
figure found: brown wax lasts "as few as several dozen plays" (web: conservation-wiki
"Cylinders"), taken as ~0.2 um of the ~10 um modulation per play (`wear_coefficient`). The
quasi-static force misses the tip's resonances and its landings after flights (the full
player has them); m is the tip's mass plus the diaphragm's and the link's through the
lever (n^2), the moving mass above the floating weight's resonance.
"""

from __future__ import annotations

import numpy as np

from varimu.phono.groove import Groove, dilate_contact

CHUNK = 50000  # positions accumulated at once


def moving_mass(spec: dict) -> float:
    from varimu.phono.cylinder import _rep_diaphragm

    rep = spec["reproducer"]
    n = rep["lever_ratio"]
    return rep["tip_mass_kg"] + n * n * (_rep_diaphragm(spec).mass_kg + rep["link_mass_kg"])


def _e_star(spec: dict) -> float:
    rep, cyl = spec["reproducer"], spec["cylinder"]
    return 1.0 / (
        (1 - rep["tip_poisson"] ** 2) / rep["tip_youngs_pa"]
        + (1 - cyl["wax_poisson"] ** 2) / cyl["wax_youngs_pa"]
    )


def flat_wear_per_play(spec: dict) -> float:
    """The depth one play takes off an unmodulated groove (m)."""
    rep, cyl = spec["reproducer"], spec["cylinder"]
    r = np.sqrt(rep["tip_radius_along_m"] * rep["tip_radius_across_m"])
    a0 = (3 * rep["downforce_n"] * r / (4 * _e_star(spec))) ** (1 / 3)
    return cyl["wear_coefficient"] / cyl["wax_hardness_pa"] * 3 * rep["downforce_n"] / (4 * a0)


def wear(g: Groove, spec: dict, plays: int, rpm: float | None = None, stride_m=1e-5) -> dict:
    """Wears the groove (in place) by `plays` earlier plays on the configured reproducer.
    Returns per play the deepest wear and its spread (max - min) along the groove."""
    rep, cyl = spec["reproducer"], spec["cylinder"]
    rpm = rep["rpm"] if rpm is None else rpm
    v = np.pi * cyl["diameter_m"] * rpm / 60.0
    r_mean = np.sqrt(rep["tip_radius_along_m"] * rep["tip_radius_across_m"])
    e_star = _e_star(spec)
    k_over_h = cyl["wear_coefficient"] / cyl["wax_hardness_pa"]
    m = moving_mass(spec)
    f0 = rep["downforce_n"]
    ds = g.ds_m
    step = max(1, int(round(stride_m / ds)))
    smooth = max(1, int(round(rep["tip_radius_along_m"] / 8 / ds)))
    kernel = np.ones(smooth) / smooth
    stats = {"plays": int(plays), "deepest_m": [], "spread_m": []}
    for _ in range(int(plays)):
        y, contact = dilate_contact(g.h_m, ds, rep["tip_radius_along_m"])
        ys = np.convolve(np.pad(y, smooth, mode="edge"), kernel, mode="same")[smooth:-smooth]
        ypp = np.gradient(np.gradient(ys, ds), ds)
        pos = np.arange(0, len(g.h_m), step)
        force = np.maximum(f0 + m * v * v * ypp[pos], 0.0)
        a = (3 * force * r_mean / (4 * e_star)) ** (1 / 3)
        reach = int(np.ceil(np.max(a) / ds)) + 1
        offs = np.arange(-reach, reach + 1)
        dh = np.zeros(len(g.h_m))
        for lo in range(0, len(pos), CHUNK):
            c = contact[pos[lo : lo + CHUNK]]
            f = force[lo : lo + CHUNK]
            aa = np.maximum(a[lo : lo + CHUNK], 1e-12)
            p0 = 3 * f / (2 * np.pi * aa * aa)
            u = offs[None, :] * ds / aa[:, None]
            p = p0[:, None] * np.sqrt(np.maximum(1.0 - u * u, 0.0))
            idx = np.clip(c[:, None] + offs[None, :], 0, len(g.h_m) - 1)
            dh += np.bincount(
                idx.ravel(), weights=(k_over_h * p * step * ds).ravel(), minlength=len(dh)
            )
        g.h_m -= dh
        stats["deepest_m"].append(float(dh.max()))
        stats["spread_m"].append(float(dh.max() - np.median(dh)))
    return stats
