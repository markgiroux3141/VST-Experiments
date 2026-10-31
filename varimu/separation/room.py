"""A shoebox room's impulse response from an omnidirectional source to a pressure (omni)
microphone: image sources for the early part, a diffuse tail after.

Image sources (Allen and Berkley, "Image method for efficiently simulating small-room
acoustics", JASA 65(4), 1979): every reflection path is a mirror image of the source,
attenuated by the walls it hits (pressure reflection sqrt(1 - alpha) per octave band), by
spreading (1 / 4 pi r) and by air (ISO 9613-1). After `ism_s` the response is a diffuse
tail: Gaussian noise per band decaying at the band's Eyring reverberation time, started
at the image sources' energy just before `ism_s`. Bands are octaves 125 Hz-8 kHz,
recombined by complementary, zero-phase weights on log frequency.

Mono: what a distance changes in one channel (direct-to-reverberant ratio, the early
reflections' comb, air loss of the highs, onsets smeared by reflections) is all here.
"""

from __future__ import annotations

import itertools
import zlib
from dataclasses import dataclass

import numpy as np

SPEED_OF_SOUND_M_S = 343.2  # dry air at 20 C
BANDS_HZ = np.array([125.0, 250.0, 500.0, 1000.0, 2000.0, 4000.0, 8000.0])

ABSORPTION_SOURCE = (
    "provisional: model knowledge (typical random-incidence absorption coefficients, "
    "as tabulated in Everest and Pohlmann, Master Handbook of Acoustics; 8 kHz = 4 kHz's)"
)
# Absorption coefficients alpha per octave band (125 Hz-8 kHz).
MATERIALS: dict[str, tuple[float, ...]] = {
    "gypsum_on_studs": (0.29, 0.10, 0.05, 0.04, 0.07, 0.09, 0.09),
    "wood_floor": (0.15, 0.11, 0.10, 0.07, 0.06, 0.07, 0.07),
    "plaster": (0.013, 0.015, 0.02, 0.03, 0.04, 0.05, 0.05),
    "carpet_on_pad": (0.08, 0.24, 0.57, 0.69, 0.71, 0.73, 0.73),
    "heavy_drapes": (0.14, 0.35, 0.55, 0.72, 0.70, 0.65, 0.65),
    "acoustic_tile": (0.50, 0.70, 0.60, 0.70, 0.70, 0.50, 0.50),
    # A furnished room's walls: gypsum with shelves, a sofa, curtains over part of it.
    "furnished_wall": (0.25, 0.20, 0.20, 0.25, 0.30, 0.30, 0.30),
}
FURNISHED_SOURCE = (
    "provisional: model knowledge (gypsum walls with furniture and some curtains, averaged)"
)


@dataclass(frozen=True)
class Room:
    """A shoebox: dimensions (x, y, z) in m and one material per surface."""

    name: str
    dims_m: tuple[float, float, float]
    walls: str  # the four walls
    floor: str
    ceiling: str
    source: str

    def alphas(self) -> np.ndarray:
        """alpha per surface (x0, x1, y0, y1, z0 floor, z1 ceiling) and band: (6, bands)."""
        w, f, c = (np.array(MATERIALS[m]) for m in (self.walls, self.floor, self.ceiling))
        return np.stack([w, w, w, w, f, c])

    def areas_m2(self) -> np.ndarray:
        lx, ly, lz = self.dims_m
        return np.array([ly * lz, ly * lz, lx * lz, lx * lz, lx * ly, lx * ly])

    def volume_m3(self) -> float:
        return float(np.prod(self.dims_m))

    def rt60_s(self) -> np.ndarray:
        """Eyring's reverberation time per band, air absorption included."""
        s = self.areas_m2()
        a_mean = (s[:, None] * self.alphas()).sum(0) / s.sum()
        m = air_absorption_db_per_m(BANDS_HZ) / (10 * np.log10(np.e))
        v = self.volume_m3()
        return (
            24 * np.log(10) * v / (SPEED_OF_SOUND_M_S * (-s.sum() * np.log(1 - a_mean) + 4 * m * v))
        )


ROOMS: dict[str, Room] = {
    "home": Room(
        "home",
        (5.0, 4.0, 2.6),
        "furnished_wall",
        "wood_floor",
        "gypsum_on_studs",
        "provisional: model knowledge (a furnished home recording room, 5 x 4 x 2.6 m)",
    ),
    "booth": Room(
        "booth",
        (3.0, 2.5, 2.4),
        "heavy_drapes",
        "carpet_on_pad",
        "acoustic_tile",
        "provisional: model knowledge (a small, heavily damped vocal room)",
    ),
    "hall": Room(
        "hall",
        (14.0, 10.0, 6.0),
        "furnished_wall",
        "wood_floor",
        "plaster",
        (
            "provisional: model knowledge (a large, live tracking room: a hard ceiling, walls "
            "partly treated; RT60 ~1.4-1.7 s mid)"
        ),
    ),
}


def air_absorption_db_per_m(
    f_hz: np.ndarray, temp_c: float = 20.0, rh_percent: float = 50.0
) -> np.ndarray:
    """Pure-tone atmospheric attenuation at sea level (ISO 9613-1:1993, equations 1-5)."""
    f = np.asarray(f_hz, float)
    t, t0, t01 = temp_c + 273.15, 293.15, 273.16
    psat_rel = 10 ** (-6.8346 * (t01 / t) ** 1.261 + 4.6151)
    h = rh_percent * psat_rel
    fr_o = 24 + 4.04e4 * h * (0.02 + h) / (0.391 + h)
    fr_n = (t / t0) ** -0.5 * (9 + 280 * h * np.exp(-4.170 * ((t / t0) ** (-1 / 3) - 1)))
    return (
        8.686
        * f**2
        * (
            1.84e-11 * (t / t0) ** 0.5
            + (t / t0) ** -2.5
            * (
                0.01275 * np.exp(-2239.1 / t) / (fr_o + f**2 / fr_o)
                + 0.1068 * np.exp(-3352.0 / t) / (fr_n + f**2 / fr_n)
            )
        )
    )


def band_weights(n_fft: int, fs: float) -> np.ndarray:
    """Zero-phase weights per octave band on rfft bins, (bands, bins), summing to 1: raised
    cosines on log frequency between neighbouring band centres."""
    f = np.fft.rfftfreq(n_fft, 1.0 / fs)
    lf = np.log2(np.maximum(f, 1e-3))
    lc = np.log2(BANDS_HZ)
    w = np.zeros((len(BANDS_HZ), len(f)))
    for b in range(len(BANDS_HZ)):
        if b == 0:
            lo = np.ones_like(lf)
        else:
            u = np.clip((lf - lc[b - 1]) / (lc[b] - lc[b - 1]), 0, 1)
            lo = 0.5 - 0.5 * np.cos(np.pi * u)
        if b == len(BANDS_HZ) - 1:
            hi = np.ones_like(lf)
        else:
            u = np.clip((lf - lc[b]) / (lc[b + 1] - lc[b]), 0, 1)
            hi = 0.5 + 0.5 * np.cos(np.pi * u)
        w[b] = np.where(lf < lc[b], lo, hi)
    return w


def _taps(delay_samples: np.ndarray, half: int = 8) -> tuple[np.ndarray, np.ndarray]:
    """Fractional-delay windowed sinc: indices and weights, (n, 2 half)."""
    i0 = np.floor(delay_samples).astype(np.int64)
    k = np.arange(-half + 1, half + 1)
    u = k[None, :] - (delay_samples - i0)[:, None]
    win = 0.5 + 0.5 * np.cos(np.pi * np.clip(u / half, -1, 1))
    return i0[:, None] + k[None, :], np.sinc(u) * win


def impulse_response(
    room: Room,
    source_m: tuple[float, float, float],
    mic_m: tuple[float, float, float],
    fs: float,
    *,
    ism_s: float = 0.08,
    length_s: float | None = None,
    seed: int = 0,
) -> np.ndarray:
    """Pressure at the mic per unit source (1 / 4 pi r at 1 m is the direct sound's level)."""
    c = SPEED_OF_SOUND_M_S
    rt = room.rt60_s()
    length_s = length_s if length_s is not None else float(rt.max()) * 1.1 + ism_s
    n = int(np.ceil(length_s * fs)) + 32
    dims = np.array(room.dims_m)
    src, mic = np.array(source_m), np.array(mic_m)
    if np.any(src <= 0) or np.any(src >= dims) or np.any(mic <= 0) or np.any(mic >= dims):
        raise ValueError("source and mic must be inside the room")

    beta = np.sqrt(1 - room.alphas())  # (6, bands)
    air = air_absorption_db_per_m(BANDS_HZ)
    r_max = c * ism_s
    nmax = (np.ceil(r_max / dims) + 1).astype(int)
    # Per axis: image coordinate offsets and wall hit counts for (n, q).
    per_axis = []
    for ax in range(3):
        rows = []
        for nn, q in itertools.product(range(-nmax[ax], nmax[ax] + 1), (0, 1)):
            pos = (1 - 2 * q) * src[ax] + 2 * nn * dims[ax]
            rows.append((pos - mic[ax], abs(nn - q), abs(nn)))
        per_axis.append(np.array(rows))
    ax0, ax1, ax2 = per_axis
    dx = ax0[:, 0][:, None, None]
    dy = ax1[:, 0][None, :, None]
    dz = ax2[:, 0][None, None, :]
    r = np.sqrt(dx**2 + dy**2 + dz**2)
    keep = r <= r_max
    ix, iy, iz = np.nonzero(keep)
    r = r[keep]
    hits = np.stack(
        [ax0[ix, 1], ax0[ix, 2], ax1[iy, 1], ax1[iy, 2], ax2[iz, 1], ax2[iz, 2]], axis=1
    )  # (images, 6)
    # Amplitude per image and band.
    amp = (
        np.exp(hits @ np.log(beta))
        / (4 * np.pi * r[:, None])
        * 10 ** (-air[None, :] * r[:, None] / 20)
    )
    idx, w = _taps(r / c * fs)
    bands = np.zeros((len(BANDS_HZ), n))
    for b in range(len(BANDS_HZ)):
        np.add.at(bands[b], np.clip(idx, 0, n - 1).ravel(), (w * amp[:, b : b + 1]).ravel())

    # The diffuse tail: noise per band, its envelope matching the image sources' energy in
    # the 20 ms before ism_s and decaying at the band's RT60.
    n_ism = int(ism_s * fs)
    win = int(0.02 * fs)
    t = (np.arange(n) - n_ism) / fs
    rng = np.random.default_rng([seed, zlib.crc32(room.name.encode())])
    noise = rng.standard_normal((len(BANDS_HZ), n))
    for b in range(len(BANDS_HZ)):
        e_early = np.mean(bands[b, n_ism - win : n_ism] ** 2)
        decay = np.exp(-3 * np.log(10) * t / rt[b])  # amplitude: -60 dB at RT60
        tail = noise[b] * np.sqrt(e_early) * decay
        fade = np.clip((np.arange(n) - (n_ism - win)) / win, 0, 1)
        bands[b] = bands[b] * (1 - fade) + tail * fade
    # Recombine the bands.
    n_fft = 1 << int(np.ceil(np.log2(n)))
    wts = band_weights(n_fft, fs)
    spec = np.einsum("bf,bf->f", wts, np.fft.rfft(bands, n_fft, axis=1))
    return np.fft.irfft(spec, n_fft)[:n]


def direct_distance_m(source_m, mic_m) -> float:
    return float(np.linalg.norm(np.subtract(source_m, mic_m)))
