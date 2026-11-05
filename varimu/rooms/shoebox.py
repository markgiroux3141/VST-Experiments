"""A shoebox room's responses from point sources to placed, aimed microphones, each as
its capsule's two entries (ROOM_LOOP_PLAN.md R2; MIC_ROOM_PLAN.md A4).

The separation study's room (varimu.separation.room: Allen and Berkley's image sources
for the early part, a diffuse tail at Eyring's RT60 per octave band, ISO 9613-1 air)
grown in two ways:

- **Every arrival keeps its direction.** An image source reaches a mic from a direction;
  its angle to the mic's aim and its distance pick the capsule's entries from its
  `EntryTable` (varimu.rooms.entries). Each image's spectrum is smooth (walls per band,
  air, 1 / r, the entries), so it is formed on the table's coarse log grid, interpolated
  to the FFT's bins and given its delay there exactly (a phase).
- **The diffuse tail is a field, not a per-mic noise:** plane waves from `TAIL_DIRECTIONS`
  directions spread evenly over the sphere (a Fibonacci lattice), each an independent
  noise per band decaying at the band's RT60, shared by every mic in the room (a plane
  wave from u reaches a mic at x at (u . x) / c early). So a mic's tail sees each
  direction through its pattern (a cardioid's diffuse-field level comes out of its
  physics), the front and rear entries are as coherent as the field makes them, and
  spaced mics get the diffuse field's coherence between them (sin(kd) / kd) without a
  model of it. The tail starts at the images' energy (all mics' omni average, per band)
  in the 20 ms before `ism_s`, faded across that window as the images fade out.

Sources are omnidirectional points. Pressures are per unit source: the free-field pressure
1 / r at r metres (so a source's track in pascals at 1 m comes out as pascals at the mic).
The room's materials are the separation room's per-band absorption coefficients, one
material per surface.
"""

from __future__ import annotations

import zlib
from dataclasses import dataclass

import numpy as np
import scipy.fft as sfft

from varimu.rooms.entries import EntryTable
from varimu.separation.room import (
    BANDS_HZ,
    MATERIALS,
    SPEED_OF_SOUND_M_S,
    air_absorption_db_per_m,
)

SURFACES = ("x0", "x1", "y0", "y1", "floor", "ceiling")
# The separation room's materials, and a surface that reflects nothing (a free field: no
# tail; the anechoic check against scripts/mic_print.py).
ROOM_MATERIALS = {
    **MATERIALS,
    "anechoic": (1.0,) * len(BANDS_HZ),
    "rigid": (0.0,) * len(BANDS_HZ),  # the checks' room (image sources exact, no decay)
}
TAIL_DIRECTIONS = 96
FADE_S = 0.02


@dataclass(frozen=True)
class Shoebox:
    """A room: dims (x, y, z) in m, one material (separation.room.MATERIALS) per surface
    (x0, x1, y0, y1, floor, ceiling), air at temp_c / rh_percent."""

    dims_m: tuple[float, float, float]
    materials: tuple[str, str, str, str, str, str]
    temp_c: float = 20.0
    rh_percent: float = 50.0

    def alphas(self) -> np.ndarray:
        return np.stack([np.array(ROOM_MATERIALS[m]) for m in self.materials])

    def areas_m2(self) -> np.ndarray:
        lx, ly, lz = self.dims_m
        return np.array([ly * lz, ly * lz, lx * lz, lx * lz, lx * ly, lx * ly])

    def rt60_s(self) -> np.ndarray:
        """Eyring's reverberation time per band, air included."""
        s = self.areas_m2()
        a_mean = (s[:, None] * self.alphas()).sum(0) / s.sum()
        m = air_absorption_db_per_m(BANDS_HZ, self.temp_c, self.rh_percent) / (10 * np.log10(np.e))
        v = float(np.prod(self.dims_m))
        c = SPEED_OF_SOUND_M_S
        with np.errstate(divide="ignore"):
            loss = -s.sum() * np.log(np.maximum(1 - a_mean, 0.0)) + 4 * m * v
        return 24 * np.log(10) * v / (c * loss)


@dataclass(frozen=True)
class Mic:
    """A capsule at `position_m`, its axis along `aim` (a unit vector), its table."""

    position_m: np.ndarray
    aim: np.ndarray
    table: EntryTable


def aim_vector(azimuth_deg: float, elevation_deg: float = 0.0) -> np.ndarray:
    """A unit vector: azimuth counterclockwise from +x in the floor plane, elevation up."""
    az, el = np.radians(azimuth_deg), np.radians(elevation_deg)
    return np.array([np.cos(el) * np.cos(az), np.cos(el) * np.sin(az), np.sin(el)])


def fibonacci_sphere(n: int) -> np.ndarray:
    """n unit vectors spread evenly over the sphere."""
    i = np.arange(n) + 0.5
    z = 1 - 2 * i / n
    phi = np.pi * (1 + 5**0.5) * i
    r = np.sqrt(1 - z**2)
    return np.stack([r * np.cos(phi), r * np.sin(phi), z], axis=1)


def band_weights_at(f_hz: np.ndarray) -> np.ndarray:
    """separation.room.band_weights on any frequencies: (bands, freqs), summing to 1."""
    lf = np.log2(np.maximum(np.asarray(f_hz, float), 1e-3))
    lc = np.log2(BANDS_HZ)
    w = np.zeros((len(BANDS_HZ), len(lf)))
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


def images(room: Shoebox, source_m: np.ndarray, r_max: float) -> tuple[np.ndarray, np.ndarray]:
    """Image sources within r_max of the room's farthest corner from the source: their
    positions (n, 3) and the walls each path hits (n, 6), by surface."""
    dims = np.array(room.dims_m)
    nmax = (np.ceil(r_max / dims) + 1).astype(int)
    per_axis = []
    for ax in range(3):
        rows = []
        for nn in range(-nmax[ax], nmax[ax] + 1):
            for q in (0, 1):
                pos = (1 - 2 * q) * source_m[ax] + 2 * nn * dims[ax]
                rows.append((pos, abs(nn - q), abs(nn)))  # hits on the 0 wall, the far wall
        per_axis.append(np.array(rows))
    ix, iy, iz = np.meshgrid(*(np.arange(len(a)) for a in per_axis), indexing="ij")
    ix, iy, iz = ix.ravel(), iy.ravel(), iz.ravel()
    pos = np.stack([per_axis[0][ix, 0], per_axis[1][iy, 0], per_axis[2][iz, 0]], axis=1)
    hits = np.stack(
        [per_axis[0][ix, 1], per_axis[0][ix, 2], per_axis[1][iy, 1], per_axis[1][iy, 2],
         per_axis[2][iz, 1], per_axis[2][iz, 2]],
        axis=1,
    )  # fmt: skip
    centre = 0.5 * dims
    keep = np.linalg.norm(pos - centre, axis=1) <= r_max + np.linalg.norm(centre)
    return pos[keep], hits[keep]


def _inside(room: Shoebox, p: np.ndarray, what: str) -> None:
    if np.any(p <= 0) or np.any(p >= np.array(room.dims_m)):
        raise ValueError(f"{what} at {p.tolist()} is not inside the room {room.dims_m}")


WAVE_EARLY_S = 0.04  # the wave solver's hand-over: amplitude crossover before, power after

POLY_MAX_ORDER = 4  # image sources in a PolyRoom: every path of up to 4 reflections
POLY_ISM_S = 0.05  # and the hand-over to the ray-traced tail (orders past 4 are thin by then)


def _poly_early(room, src, mic_pos, beta):
    """A PolyRoom's image sources valid for one mic: positions, log of the walls' product."""
    from varimu.rooms import polyroom

    pos, seqs = room._images_cache.get(tuple(src), (None, None))
    if pos is None:
        pos, seqs = polyroom.image_sources(room, src, POLY_MAX_ORDER)
        room._images_cache[tuple(src)] = (pos, seqs)
    ok = polyroom.valid_paths(room, pos, seqs, mic_pos)
    pos, seqs = pos[ok], seqs[ok]
    lb = np.zeros((len(pos), beta.shape[1]))
    for j in range(seqs.shape[1]):
        f = seqs[:, j]
        has = f >= 0
        lb[has] += np.log(beta[f[has]])
    return pos, lb, seqs


def emission_dirs(d: np.ndarray, room, seqs=None, hits=None) -> np.ndarray:
    """The directions in which image paths leave the real source (unit, (images, 3)): the
    image's direction to the mic `d` mirrored back through its reflections (a PolyRoom's face
    sequences, the last first; a shoebox's walls per axis, an odd count flipping the axis)."""
    v = d / np.linalg.norm(d, axis=1)[:, None]
    if hits is not None:
        flips = 1 - 2 * ((hits[:, 0::2] + hits[:, 1::2]) % 2)  # (x0+x1, y0+y1, floor+ceiling)
        return v * flips
    out = v.copy()
    for j in range(seqs.shape[1] - 1, -1, -1):
        fi = seqs[:, j]
        has = fi >= 0
        if not np.any(has):
            continue
        n = np.array([room.faces[k].normal for k in fi[has]])
        out[has] -= 2 * (out[has] * n).sum(1)[:, None] * n
    return out


def _ray_weights(directivity, si: int, n_rays: int):
    """A directional source's rays' starting energies (rays, bands): |D|^2 at the bands'
    centres in each ray's direction (the rays' directions: polyroom.ray_decay's)."""
    if not directivity or directivity[si] is None:
        return None
    d, aim = directivity[si]
    cos_r = fibonacci_sphere(n_rays) @ aim
    return np.abs(d.at(BANDS_HZ, cos_r)) ** 2


def _receiver_gains(decay, n: int, fs: float, volume: float) -> np.ndarray:
    """Per mic, the tail's gain over time (mics, n): the ray-traced energy density at the mic
    over the room's mean (e(t) / V), in the mid bands (500 Hz-4 kHz), smoothed over 5 ms
    (flutter's 10-40 ms periods stay): the shared diffuse field shaped to what reaches
    each point (polyroom.ray_decay's receivers)."""
    t, e, w = decay
    mid = slice(2, 6)
    mean = e[mid].sum(0) / volume
    win = np.hanning(7)[1:-1]
    win /= win.sum()
    out = np.zeros((w.shape[0], n))
    ts = np.arange(n) / fs
    for i, wi in enumerate(w):
        ratio = np.convolve(wi[mid].sum(0), win, "same") / np.maximum(
            np.convolve(mean, win, "same"), 1e-30
        )
        out[i] = np.sqrt(np.clip(np.interp(ts, t, ratio), 0.02, 16.0))
    return out


def responses(
    room,
    sources_m: list[np.ndarray],
    mics: list[Mic],
    fs: float,
    *,
    ism_s: float = 0.08,
    length_s: float | None = None,
    seeds: list[int] | None = None,
    tail: bool = True,
    backend: str | None = None,
    wave: dict | None = None,
    directivity: list | None = None,
) -> np.ndarray:
    """The rooms' impulse responses, (sources, mics, 2 entries (front, rear), samples):
    the entries' pressure per unit source (1 / r in free field). `seeds` per source
    seed its tail (default its index). `room` is a Shoebox (images of every order up to
    ism_s, the tail started at their energy, Eyring's decay) or a
    varimu.rooms.polyroom.PolyRoom (images up to POLY_MAX_ORDER valid per mic, the hand-over
    at POLY_ISM_S, the tail's level and decay ray-traced from the shape). `backend`
    (varimu.rooms.gpu) runs the images' spectra and the rays on the GPU, roomsim's CPU
    reference or numpy (the default: varimu.rooms.gpu.backend()). `wave` ({crossover_hz,
    log?}) puts the wave solver under the crossover (varimu.rooms.wave, ROOM_LOOP_PLAN.md
    R10): below it the room's modes, above it this model. `directivity` per source: None
    (omni) or (varimu.rooms.directivity.Directivity, its aim as a unit vector): every image
    and diffraction path weighted by D in the direction it leaves the source, the rays started
    with |D|^2, the wave solver's source a monopole and a dipole."""
    from varimu.rooms import diffraction, gpu
    from varimu.rooms.polyroom import RECEIVER_RAYS, PolyRoom, ray_decay, rt60_from_decay

    backend = gpu.resolve(backend)
    c = SPEED_OF_SOUND_M_S
    poly = isinstance(room, PolyRoom)
    decays = {}
    if poly:
        ism_s = min(ism_s, POLY_ISM_S)
        room._images_cache = {}
        for si, src in enumerate(sources_m):
            if not room.inside(np.asarray(src, float)):
                raise ValueError(f"a source at {list(src)} is not inside the room")
            decays[si] = ray_decay(
                room,
                np.asarray(src, float),
                4.0,
                n_rays=RECEIVER_RAYS,
                seed=seeds[si] if seeds else si,
                receivers=[m.position_m for m in mics],
                backend=backend,
                weights=_ray_weights(directivity, si, RECEIVER_RAYS),
            )
        rt = np.nanmax([rt60_from_decay(*d[:2]) for d in decays.values()], axis=0)
        rt = np.where(np.isfinite(rt), rt, 1.0)
    else:
        rt = room.rt60_s()
    length_s = length_s if length_s is not None else float(rt.max()) * 1.1 + ism_s
    n = int(np.ceil(length_s * fs))
    n_fft = 1 << int(np.ceil(np.log2(n + int(0.05 * fs))))
    f_fine = np.fft.rfftfreq(n_fft, 1.0 / fs)
    for m in mics:
        if poly:
            if not room.inside(m.position_m):
                raise ValueError(f"a mic at {m.position_m.tolist()} is not inside the room")
        else:
            _inside(room, m.position_m, "a mic")
    if poly:
        alphas = np.stack([np.array(ROOM_MATERIALS[room.material(f)]) for f in room.faces])
        beta = np.maximum(np.sqrt(1 - alphas), 1e-300)  # (faces, bands)
        centre = np.r_[room.floor.mean(0), 0.5 * room.height_m]
        volume = room.volume_m3()
    else:
        beta = np.maximum(np.sqrt(1 - room.alphas()), 1e-300)  # (6, bands)
        centre = 0.5 * np.array(room.dims_m)
    seeds = seeds if seeds is not None else list(range(len(sources_m)))
    out = np.zeros((len(sources_m), len(mics), 2, n))
    tails = []  # per source: its diffuse field's plane waves (directions, bins), its gains
    n_ism, win = int(ism_s * fs), int(FADE_S * fs)

    # Per mic table: the coarse grid and its map onto the FFT's bins.
    grids = {}
    for m in mics:
        key = id(m.table)
        if key not in grids:
            fg = m.table.f_grid
            idx = np.clip(np.searchsorted(fg, f_fine, side="right") - 1, 0, len(fg) - 2)
            w = np.clip((f_fine - fg[idx]) / (fg[idx + 1] - fg[idx]), 0, 1)
            bw = band_weights_at(fg)
            air = air_absorption_db_per_m(fg, room.temp_c, room.rh_percent)
            grids[key] = (idx, w, bw, air)

    for si, src in enumerate(sources_m):
        src = np.asarray(src, float)
        src_dir = directivity[si] if directivity else None
        if not poly:
            _inside(room, src, "a source")
            pos, hits_all = images(room, src, c * ism_s)
            log_beta = hits_all @ np.log(beta)  # (images, bands): log of the walls' product
        early = np.zeros((len(mics), len(BANDS_HZ)))
        for mi, m in enumerate(mics):
            idx, w, bw, air = grids[id(m.table)]
            if poly:
                pos, log_beta, seqs = _poly_early(room, src, m.position_m, beta)
            d = pos - m.position_m
            r = np.linalg.norm(d, axis=1)
            tau_s = r / c
            sel = tau_s <= ism_s
            d, r, tau_s, lb = d[sel], r[sel], tau_s[sel], log_beta[sel]
            d_src = None  # each image's D (images, grid), a directional source's
            if src_dir is not None:
                emit = (
                    emission_dirs(-d, room, seqs=seqs[sel])
                    if poly
                    else emission_dirs(-d, room, hits=hits_all[sel])
                )
                cos_e = emit @ src_dir[1]
                d_src = src_dir[0].cap(m.table.f_grid, cos_e)
                d_band = np.abs(src_dir[0].at(BANDS_HZ, cos_e))
            # the images' fade out over the window before ism_s (the tail fades in)
            fade = np.clip((tau_s * fs - (n_ism - win)) / win, 0, 1)
            band_amp = np.exp(lb) / r[:, None]  # (images, bands)
            # the tail's start: the omni images' energy per sample in the window, per band
            in_win = (tau_s * fs >= n_ism - win) & (tau_s * fs < n_ism)
            e_amp = band_amp if d_src is None else band_amp * d_band
            early[mi] = (e_amp[in_win] ** 2).sum(0) / win
            band_amp = band_amp * (1 - fade)[:, None]
            cos_t = np.clip((d @ m.aim) / r, -1, 1)
            e_front, e_rear = m.table.at(np.arccos(cos_t), r)
            smooth = (band_amp @ bw) * 10 ** (-air[None, :] * r[:, None] / 20)
            if d_src is not None:
                smooth = smooth * d_src
            # the edges' diffraction (a PolyRoom's objects and reflex corners: R11), each
            # path one smooth spectrum (its walls, the air, the entries seen from its apex)
            dpaths = diffraction.paths(room, src, m.position_m, fs, beta) if poly else []
            d_coarse, d_delay, d_spec, d_scale = [], [], [], []
            for k, dp in enumerate(dpaths):
                dv = dp.apex_m - m.position_m
                rr = float(np.linalg.norm(dv))
                th = np.arccos(np.clip((dv @ m.aim) / rr, -1, 1))
                ef, er = m.table.at(np.array([th]), np.array([rr]))
                fade_d = 1 - np.clip((dp.n0 - (n_ism - win)) / win, 0, 1)
                sm = (np.exp(dp.log_beta) @ bw) * 10 ** (-air * dp.path_m / 20) * fade_d
                if src_dir is not None:
                    ev = dp.apex_m - dp.start_m
                    if dp.start_face >= 0:  # an image's path: back through its face
                        nf = room.faces[dp.start_face].normal
                        ev = ev - 2 * (ev @ nf) * nf
                    ev = ev / np.linalg.norm(ev)
                    sm = sm * src_dir[0].cap(m.table.f_grid, np.array([ev @ src_dir[1]]))[0]
                d_coarse.append(np.stack([sm * ef[0], sm * er[0]]))
                nz = np.flatnonzero(np.abs(dp.h) > 1e-9 * np.abs(dp.h).max())
                d_delay.append(dp.n0 + nz.astype(float))
                d_spec.append(np.full(len(nz), len(r) + k))
                d_scale.append(dp.h[nz])
            if backend != "numpy":
                coarse = np.stack([smooth * e_front, smooth * e_rear], axis=1)
                if dpaths:
                    coarse = np.concatenate([coarse, np.array(d_coarse)])
                    spec = gpu.image_spectra(
                        coarse,
                        np.r_[tau_s * fs, *d_delay],
                        idx,
                        w,
                        n_fft,
                        backend,
                        spec_index=np.r_[np.arange(len(r)), *d_spec],
                        scale=np.r_[np.ones(len(r)), *d_scale],
                    )
                else:
                    spec = gpu.image_spectra(coarse, tau_s * fs, idx, w, n_fft, backend)
                out[si, mi] = np.fft.irfft(spec, n_fft)[:, :n]
                continue
            spec = np.zeros((2, len(f_fine)), complex)
            for k, dp in enumerate(dpaths):
                hf = np.fft.rfft(np.r_[np.zeros(dp.n0), dp.h], n_fft)
                for e in range(2):
                    s_c = d_coarse[k][e]
                    spec[e] += (s_c[idx] * (1 - w) + s_c[idx + 1] * w) * hf
            for lo in range(0, len(r), 64):
                hi = min(lo + 64, len(r))
                ph = np.exp(-2j * np.pi * f_fine[None, :] * tau_s[lo:hi, None])
                for e, ent in enumerate((e_front, e_rear)):
                    s_c = smooth[lo:hi] * ent[lo:hi]
                    s_f = s_c[:, idx] * (1 - w) + s_c[:, idx + 1] * w
                    spec[e] += np.einsum("if,if->f", s_f, ph)
            out[si, mi] = np.fft.irfft(spec, n_fft)[:, :n]
        if not tail:
            continue
        # The diffuse field: shared plane waves, each one white noise (2026-11-05: the same
        # noise in every band, each band's envelope on it, so the band weights, which sum to 1
        # in amplitude, cross over without the -3 dB dips that independent noises per band left
        # between bands; and one draw instead of seven).
        e_rate = early.mean(0)  # (bands,)
        dirs = fibonacci_sphere(TAIL_DIRECTIONS)
        rng = np.random.default_rng([seeds[si], zlib.crc32(b"room tail")])
        t = (np.arange(n_fft) - n_ism) / fs
        fade_in = np.clip((np.arange(n_fft) - (n_ism - win)) / win, 0, 1)
        bw_fine = band_weights_at(f_fine)
        noise_spec = np.zeros((TAIL_DIRECTIONS, len(f_fine)), complex)
        white = rng.standard_normal((TAIL_DIRECTIONS, n_fft))
        for b in range(len(BANDS_HZ)):
            if poly:
                # <h^2(t)> = 4 pi c e(t) / V per second (polyroom's docstring)
                te, eb = decays[si][0], decays[si][1][b]
                e_t = np.interp(np.arange(n_fft) / fs, te, eb, right=0.0)
                env = np.sqrt(4 * np.pi * c * e_t / (volume * fs * TAIL_DIRECTIONS))
            else:
                env = np.sqrt(e_rate[b] / TAIL_DIRECTIONS) * np.exp(-3 * np.log(10) * t / rt[b])
            env *= fade_in
            env[n:] = 0.0
            noise_spec += bw_fine[b][None, :] * sfft.rfft(white * env[None, :], axis=1, workers=-1)
        gains = _receiver_gains(decays[si], n, fs, volume) if poly else None
        tails.append((si, noise_spec, gains))
    # each mic's view of the diffuse field (its entries and arrival phases per direction,
    # the same for every source), then every source's field through it
    if tails:
        dirs = fibonacci_sphere(TAIL_DIRECTIONS)
    for mi, m in enumerate(mics) if tails else ():
        cos_t = np.clip(dirs @ m.aim, -1, 1)
        e_front, e_rear = m.table.at(np.arccos(cos_t), np.full(len(dirs), np.inf))
        idx, w, _, _ = grids[id(m.table)]
        lead_s = (dirs @ (m.position_m - centre)) / c  # u . x / c early
        # e^{2 pi j f lead} on the FFT's evenly spaced bins: powers of one step (a running
        # product; ~1e-11 from exp after 2^18 bins), far cheaper than the exponentials
        ph = np.empty((len(dirs), len(f_fine)), complex)
        ph[:, 0] = 1.0
        ph[:, 1:] = np.exp(2j * np.pi * f_fine[1] * lead_s)[:, None]
        np.cumprod(ph, axis=1, out=ph)
        for e, ent in enumerate((e_front, e_rear)):
            view = (ent[:, idx] * (1 - w) + ent[:, idx + 1] * w) * ph
            for si, noise_spec, gains in tails:
                spec = np.einsum("if,if->f", view, noise_spec)
                tail_t = sfft.irfft(spec, n_fft, workers=-1)[:n]
                out[si, mi, e] += tail_t if gains is None else tail_t * gains[mi]
    if wave:
        from varimu.rooms import wave as wave_solver

        low, xw = wave_solver.responses(
            room,
            sources_m,
            mics,
            fs,
            n_fft,
            crossover_hz=float(wave["crossover_hz"]),
            rt_s=rt,
            length_s=n / fs,
            backend=backend,
            log=wave.get("log"),
            directivity=directivity,
        )
        # the early part (direct sound, first reflections: the same arrivals in both models)
        # crosses over in amplitude, the late part (two unrelated fields) in power, so the
        # crossover neither dips the reverb nor bumps the direct sound
        k = len(xw)
        t = np.arange(n_fft) / fs
        early = np.clip((WAVE_EARLY_S + FADE_S - t) / FADE_S, 0, 1)
        g_late = np.sqrt(np.clip(1 - xw**2 / np.maximum(xw**2 + (1 - xw) ** 2, 1e-12), 0, 1))
        w_late = np.sqrt(np.clip(xw**2 / np.maximum(xw**2 + (1 - xw) ** 2, 1e-12), 0, 1))
        with np.errstate(divide="ignore", invalid="ignore"):
            w_late = np.where(xw > 0, w_late / xw, 0.0)
        for si in range(len(sources_m)):
            for mi in range(len(mics)):
                for e in range(2):
                    geo = np.fft.rfft(out[si, mi, e], n_fft)
                    lw = np.fft.irfft(np.r_[low[si, mi, e], np.zeros(len(geo) - k)], n_fft)
                    ge = np.fft.rfft(np.fft.irfft(geo, n_fft) * early, n_fft)
                    gl = geo - ge
                    le = np.fft.rfft(lw * early, n_fft)
                    ll = np.fft.rfft(lw, n_fft) - le
                    h = geo.copy()
                    h[:k] = ge[:k] * (1 - xw) + le[:k] + gl[:k] * g_late + ll[:k] * w_late
                    out[si, mi, e] = np.fft.irfft(h, n_fft)[:n]
    return out
