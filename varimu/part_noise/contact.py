"""A pot's wiper on its track: the contact resistance along the track and what the next stage
hears while it turns.

**The track.** The contact resistance R_c(x) at wiper position x is a small base value plus a
rough profile (a Gaussian process, correlation length `corr`), whose 99.9th percentile is CRV x
the track's resistance (CRV, contact resistance variation: the industry's figure for wiper
noise), plus, on a worn track, bad spots (Poisson along the track) where the wiper rides on oxide
or dirt and R_c is near open.

**Into a grid.** A volume pot whose wiper feeds a grid directly (the Fender 5F1's) carries no DC
current, so CRV alone does nothing: the wiper's resistance is in series with the grid's input
capacitance (C_in, Miller included). Only where R_c becomes large does the grid stop following:
it holds its charge and jumps when contact returns. The jump's size is whatever moved on the
track meanwhile: the signal and, with a leaky coupling capacitor above the pot, its DC. Exact
per sample for the track voltage held over the sample: v_g += (v_w - v_g)(1 - exp(-dt / (R_c
C_in))).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy import ndimage

CRV_SOURCE = (
    "web: https://image-ppubs.uspto.gov/dirsearch-public/print/downloadPdf/4095210 (US "
    "4,095,210, a helical-spring wiper potentiometer: CRV "
    "measured with a constant current source, prior-art peaks over 10%, the improved wiper ~1% "
    "maximum); wear roughens the track and raises the noise, web: "
    "https://siliconchip.com.au/Issue/PE/2023/June/AUDIO+OUT"
)
TRACK_SOURCE = (
    "provisional: model knowledge (a carbon track ~50 mm over 300 degrees; roughness "
    "correlation ~50 um; contact base ~100 ohm; bad spots 0.2 mm wide, ~6 per track when worn, "
    "~1e8 ohm on oxide; C_in ~150 pF for a 12AX7 stage with its Miller capacitance)"
)


@dataclass(frozen=True)
class Track:
    r_track_ohm: float  # the pot's resistance
    crv: float  # contact resistance variation, a share of r_track_ohm
    bad_spots: float  # expected bad spots over the whole track
    corr: float = 1e-3  # roughness correlation length, a share of the travel
    spot_width: float = 4e-3  # a bad spot's width, a share of the travel
    r_base_ohm: float = 100.0
    r_open_ohm: float = 1e8
    points: int = 200_000


def contact_profile(track: Track, rng: np.random.Generator):
    """(x grid, R_c(x)) over the travel 0..1."""
    x = np.linspace(0.0, 1.0, track.points)
    sigma_pts = track.corr * track.points
    g = ndimage.gaussian_filter1d(rng.standard_normal(track.points), sigma_pts, mode="wrap")
    g = np.abs(g)
    g *= track.crv * track.r_track_ohm / max(np.quantile(g, 0.999), 1e-30)
    r = track.r_base_ohm + g
    for centre in rng.uniform(0.0, 1.0, rng.poisson(track.bad_spots)):
        width = track.spot_width * rng.uniform(0.3, 1.5)
        r[np.abs(x - centre) < width / 2] = track.r_open_ohm * rng.uniform(0.2, 1.0)
    return x, r


def audio_taper(x):
    """A log (audio, 10% at mid travel) taper: the wiper's share of the track's voltage."""
    x = np.clip(np.asarray(x, float), 0.0, 1.0)
    return (10.0 ** (2.0 * x) - 1.0) / 99.0


def turned(track_v, position, track: Track, c_in_f: float, rate_hz: float, rng):
    """The grid's voltage while the wiper follows `position` (0..1 per sample) on a track
    driven by `track_v` (the voltage at its top, per sample). Returns (grid, ideal wiper)."""
    xs, rs = contact_profile(track, rng)
    position = np.clip(np.asarray(position, float), 0.0, 1.0)
    r_c = np.interp(position, xs, rs)
    v_w = audio_taper(position) * np.asarray(track_v, float)
    a = np.exp(-1.0 / (rate_hz * r_c * c_in_f))
    v_g = np.empty_like(v_w)
    g = v_w[0]
    for k in range(v_w.size):
        g = v_w[k] + (g - v_w[k]) * a[k]
        v_g[k] = g
    return v_g, v_w
