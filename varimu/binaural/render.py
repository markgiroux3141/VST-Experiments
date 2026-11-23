"""Binaural renders for headphones (docs/BINAURAL_PLAN.md): a mono source placed or moved
round a simulated head, anechoic, both ears to a stereo pair (left = left ear).

**Headphone equalization.** An HRTF at the blocked ear canal carries the ear's own
resonances as heard from every direction; headphones (tuned near a diffuse-field target)
already present them once. So by default each ear is divided by its diffuse-field response
(the power average over directions spread evenly on the sphere, smoothed in third octaves):
what is left is what changes with direction, the localization cues (`diffuse_field_eq`).
`eq=False` renders the raw ear-canal pressure.

**Level.** Each ear's transfer function is relative to the free field at the head's centre,
so a source's level at the centre is its own; renders keep a fixed distance unless asked.
"""

from __future__ import annotations

import numpy as np

from varimu.binaural.hrtf import LEAD_S, HeadHrtf
from varimu.rooms.shoebox import fibonacci_sphere

FS = 96_000


def _third_octave_smooth(f: np.ndarray, p: np.ndarray) -> np.ndarray:
    out = np.empty_like(p)
    for i, fi in enumerate(f):
        if fi <= 0:
            out[..., i] = p[..., i]
            continue
        s = (f >= fi * 2 ** (-1 / 6)) & (f <= fi * 2 ** (1 / 6))
        out[..., i] = p[..., s].mean(axis=-1)
    return out


def diffuse_field_eq(h: HeadHrtf, n_dirs: int = 1200) -> np.ndarray:
    """(2, F) real gains: 1 / each ear's diffuse-field magnitude (third-octave smoothed)."""
    u = fibonacci_sphere(n_dirs)
    az = np.degrees(np.arctan2(u[:, 1], u[:, 0]))
    el = np.degrees(np.arcsin(np.clip(u[:, 2], -1, 1)))
    H = h.tf(az, el)
    power = (np.abs(H) ** 2).mean(axis=1)
    return 1.0 / np.sqrt(_third_octave_smooth(h.f_hz, power))


class SphereHead:
    """A rigid sphere with point ears at +-y (no pinnae): the control, front and back
    alike for every source (the analytic series, varimu.binaural.analytic; far field)."""

    def __init__(self, radius_m: float = 0.0875, f_hz: np.ndarray | None = None):
        from varimu.binaural.hrtf import F_STOP_HZ, N_OUT

        self.name = f"sphere_{radius_m * 100:.2f}cm"
        self.radius_m = radius_m
        f = np.arange(N_OUT // 2 + 1) * 96_000.0 / N_OUT
        self.f_hz = f[f <= F_STOP_HZ] if f_hz is None else f_hz

    def tf(self, az_deg, el_deg, distance_m=None) -> np.ndarray:
        from varimu.binaural.analytic import sphere_hrtf
        from varimu.binaural.sphere import sph_from_azel, unit_vectors

        th, ph = sph_from_azel(np.atleast_1d(az_deg), np.atleast_1d(el_deg))
        u = unit_vectors(th, ph)
        out = [
            sphere_hrtf(self.f_hz, u @ np.array([0, s, 0.0]), self.radius_m, self.radius_m, 343.0)
            for s in (1.0, -1.0)
        ]
        return np.stack(out)

    hrirs = HeadHrtf.hrirs


class SofaHead:
    """A measured HRIR set (varimu.binaural.sofa), the nearest measured direction per
    request, resampled to 96 kHz (no interpolation between directions)."""

    def __init__(self, path, name: str | None = None):
        from varimu.binaural import sofa

        self.s = sofa.read(path)
        self.name = name or str(path)
        el, az = np.radians(self.s.el_deg), np.radians(self.s.az_deg)
        self.u = np.stack([np.cos(el) * np.cos(az), np.cos(el) * np.sin(az), np.sin(el)], 1)
        n = 2048
        self.f_hz = np.fft.rfftfreq(n, 1 / self.s.fs)
        self.H = np.fft.rfft(self.s.ir, n, axis=-1)  # (M, 2, F)

    def nearest(self, az_deg, el_deg) -> np.ndarray:
        el, az = np.radians(np.atleast_1d(el_deg)), np.radians(np.atleast_1d(az_deg))
        u = np.stack([np.cos(el) * np.cos(az), np.cos(el) * np.sin(az), np.sin(el)], 1)
        return np.argmax(u @ self.u.T, axis=1)

    def tf(self, az_deg, el_deg, distance_m=None) -> np.ndarray:
        return np.moveaxis(self.H[self.nearest(az_deg, el_deg)], 1, 0)

    def diffuse_field_eq(self) -> np.ndarray:
        """Over the measured directions weighted by cos(elevation) (rings of equal steps)."""
        w = np.cos(np.radians(self.s.el_deg))
        power = np.einsum("m,mef->ef", w / w.sum(), np.abs(self.H) ** 2)
        return 1.0 / np.sqrt(_third_octave_smooth(self.f_hz, power))

    def hrirs(self, az_deg, el_deg, fs=96_000.0, n=768, distance_m=None, gain=None):
        from scipy.signal import resample_poly

        H = self.tf(az_deg, el_deg)
        if gain is not None:
            H = H * gain[:, None, :]
        # a smooth gain is zero-phase: shift by LEAD_S first so nothing wraps
        H = H * np.exp(-2j * np.pi * self.f_hz * 0.5e-3)
        h = np.fft.irfft(H, 2 * (len(self.f_hz) - 1), axis=-1)
        h = resample_poly(h, 320, 147, axis=-1)  # 44.1 -> 96 kHz
        return h[..., :n]


class Binaural:
    """A head ready to render (HeadHrtf, SphereHead or SofaHead): its HRIRs on demand,
    equalized (or not)."""

    def __init__(self, head, eq: bool = True, n_taps: int = 768):
        self.head = head
        if not eq:
            self.eq = None
        elif hasattr(head, "diffuse_field_eq"):
            self.eq = head.diffuse_field_eq()
        else:
            self.eq = diffuse_field_eq(head)
        self.n_taps = n_taps

    def hrirs(self, az_deg, el_deg, distance_m: float | None = None) -> np.ndarray:
        """(2, points, n_taps) at 96 kHz, delayed by LEAD_S."""
        return self.head.hrirs(
            az_deg, el_deg, fs=FS, n=self.n_taps, distance_m=distance_m, gain=self.eq
        )

    def place(self, x: np.ndarray, az_deg: float, el_deg: float = 0.0, distance_m=None):
        """A static source: (2, len(x) + n_taps - 1)."""
        from scipy.signal import fftconvolve

        h = self.hrirs([az_deg], [el_deg], distance_m)[:, 0]
        return np.stack([fftconvolve(x, h[e]) for e in range(2)])

    def path(self, x: np.ndarray, az_deg: np.ndarray, el_deg: np.ndarray, frame: int = 960):
        """A moving source: az / el per sample (deg); a new HRIR each `frame` samples (10
        ms), each frame convolved with its own and the previous one's and cross-faded."""
        from scipy.signal import fftconvolve

        n = len(x)
        nf = int(np.ceil(n / frame))
        idx = np.minimum(np.arange(nf) * frame + frame // 2, n - 1)
        H = self.hrirs(np.asarray(az_deg)[idx], np.asarray(el_deg)[idx])  # (2, nf, taps)
        out = np.zeros((2, n + self.n_taps))
        fade = 0.5 - 0.5 * np.cos(np.pi * (np.arange(frame) + 0.5) / frame)
        for k in range(nf):
            seg = x[k * frame : (k + 1) * frame]
            w = fade[: len(seg)]
            for e in range(2):
                cur = fftconvolve(seg * w, H[e, k])
                prev = fftconvolve(seg * (1 - w), H[e, max(k - 1, 0)])
                y = cur + prev
                out[e, k * frame : k * frame + len(y)] += y
        return out[:, : n + self.n_taps - 1]


__all__ = ["FS", "LEAD_S", "Binaural", "SofaHead", "SphereHead", "diffuse_field_eq"]
