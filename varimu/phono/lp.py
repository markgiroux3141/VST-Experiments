"""A 1960s stereo LP cut, pressed and played (docs/PHONO_PLAN.md, "The 1960s record player";
config/phono/westrex_3d.yaml for the record).

**Cutting** (`record`). The program's two channels are set by a VU meter: their loud passages
(a percentile of the 300 ms rms) at the reference level, 5 cm/s peak per channel at 1 kHz (NAB
1964 §3.15). They go through the lathe's chain (lathe.py: RIAA pre-emphasis, the card, the
closed loops of the two axes with their coupling) as its impulse responses, to each axis' tip
excursion: A on the left (inner) wall's normal, B on the right (outer) wall's (NAB: "outer wall
= right channel"; microgroove.py's convention, x positive outward). The lathe turns at 33-1/3
with its wow (a seeded process at the AM 32b's 0.035% rms), its feed set from the program a turn
ahead (microgroove.variable_pitch: each turn's half width at the surface plus its lateral
excursion plus the land), the tip's vertical motion inclined by the effective cutting angle
(Bauer's springback: tan C = tan 23 deg - 0.42), and the groove is written on a uniform arc
grid.

**Pressing** (`press`). The lacquer is plated, the stamper pressed into vinyl: the walls as cut
(the copies' errors are far below the surface's), plus the vinyl's surface roughness on each
wall, its level set so the played noise meets NAB's figure (`calibrate_surface`), and dust and
non-fill as damage.py's particles.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.signal import oaconvolve, resample_poly

from varimu.phono import cylinder as cy
from varimu.phono import damage as dm
from varimu.phono import disc
from varimu.phono import groove as gv
from varimu.phono import lathe as la
from varimu.phono import microgroove as mg

IR_SECONDS = 0.5


def load(name: str = "westrex_3d") -> dict:
    return cy.load(name)


def wall_angle(spec: dict) -> float:
    return np.deg2rad(spec["lathe"]["wall_angle_deg"])


def cutting_angle(spec: dict) -> float:
    """The effective vertical angle the lacquer keeps (Bauer 1963)."""
    lt = spec["lathe"]
    return float(np.arctan(np.tan(np.deg2rad(lt["cutter_angle_deg"])) - lt["springback"]))


def card(spec: dict) -> np.ndarray:
    """The card trimmed to this cutter (lathe.fit_card)."""
    return la.fit_card(spec)[0]


def cut_irs(spec: dict, card_params: np.ndarray, fs_hz: float) -> np.ndarray:
    """The chain's displacement impulse responses (2, 2, n): [axis out, channel in], metres
    per unit program sample (the chain normalized to 1 m/s per unit at 1 kHz)."""
    n = int(round(IR_SECONDS * fs_hz))
    nfft = 2 * n
    f = np.fft.rfftfreq(nfft, 1.0 / fs_hz)
    h = np.zeros((len(f), 2, 2), dtype=complex)
    h[1:] = la.chain(spec, f[1:], card_params)
    # Displacement = velocity / (j w); the loop's coupling blocks DC (its low pole).
    h[1:] /= (2j * np.pi * f[1:])[:, None, None]
    ir = np.fft.irfft(h, nfft, axis=0)[:n]
    return np.transpose(ir, (1, 2, 0))


def vu_gain(x_lr: np.ndarray, fs_hz: float, spec: dict) -> float:
    """The gain from program units to m/s that puts the louder channel's loud passages
    (`vu_percentile` of its 300 ms rms) at the reference (a 1 kHz sine of `reference_cm_s`
    peak: its rms)."""
    lv = spec["level"]
    k = max(1, int(lv["vu_window_s"] * fs_hz))
    ms = []
    for ch in x_lr.T:
        c = np.cumsum(np.concatenate([[0.0], ch * ch]))
        ms.append((c[k:] - c[:-k]) / k)
    vu = np.sqrt(np.maximum(ms[0], ms[1]))
    loud = float(np.percentile(vu, lv["vu_percentile"]))
    ref_rms = lv["reference_cm_s"] / 100.0 / np.sqrt(2)
    return ref_rms / (loud or 1.0)


@dataclass
class LPRecord:
    x_m: np.ndarray  # the groove's lateral excursion per arc sample (outward positive)
    z_m: np.ndarray  # its vertical excursion (up positive: shallower)
    wall_l_m: np.ndarray  # each wall's position along its inward normal (surface included)
    wall_r_m: np.ndarray
    ds_m: float
    spiral: mg.TableSpiral
    fs_hz: float
    lead_in_samples: int
    gain: float  # m/s per program unit at 1 kHz
    peak_velocity_m_s: float  # the largest per-channel tip velocity cut
    lift_out: float  # the fraction of the cut where the tip rose out of the lacquer
    omega: np.ndarray  # the lathe's angular velocity per sample
    s_m: np.ndarray  # arc length under the cutter per sample

    @property
    def length_m(self) -> float:
        return len(self.x_m) * self.ds_m

    def s_grid(self) -> np.ndarray:
        return np.arange(len(self.x_m)) * self.ds_m


def lathe_motion(spec: dict, n: int, fs_hz: float, seed: int | None) -> np.ndarray:
    """The lathe's angular velocity per sample: 33-1/3 with its wow (a seeded AR(1) at a
    0.5 s correlation, scaled to `wow_rms`), or exact."""
    w0 = 2 * np.pi * spec["lathe"]["rpm"] / 60.0
    if seed is None:
        return np.full(n, w0)
    g = disc.rng(seed, "lathe wow")
    step = int(fs_hz / 1000)  # the process at 1 kHz, interpolated
    m = n // step + 2
    a = np.exp(-1.0 / (0.5 * 1000))
    w = g.standard_normal(m) * np.sqrt(1 - a * a)
    from scipy.signal import lfilter

    y = lfilter([1.0], [1.0, -a], w)
    y *= spec["lathe"]["wow_rms"] / (np.std(y) or 1.0)
    return w0 * (1 + np.interp(np.arange(n), np.arange(m) * step, y))


def record(
    spec: dict,
    x_lr: np.ndarray,
    fs_in_hz: float,
    card_params: np.ndarray | None = None,
    start_radius_m: float | None = None,
    motion_seed: int | None = None,
) -> LPRecord:
    """Cuts the stereo program x_lr (n, 2), left then right, into a groove starting at
    `start_radius_m` (default the outermost groove). The walls are smooth (`press` adds the
    vinyl's surface)."""
    fs = spec["numerics"]["fs_hz"]
    lt = spec["lathe"]
    a = wall_angle(spec)
    if card_params is None:
        card_params = card(spec)
    up = np.stack(
        [resample_poly(np.asarray(c, float), int(fs), int(fs_in_hz)) for c in np.asarray(x_lr).T], 1
    )
    gain = vu_gain(up, fs, spec)
    lead = int(round(spec["numerics"]["lead_in_s"] * fs))
    tail = int(0.05 * fs)
    sig = np.concatenate([np.zeros((lead, 2)), up * gain, np.zeros((tail, 2))])
    irs = cut_irs(spec, card_params, fs)
    n = len(sig)
    exc = np.zeros((2, n))
    for o in range(2):
        for i in range(2):
            exc[o] += oaconvolve(sig[:, i], irs[o, i])[:n]
    vel = np.gradient(exc, 1.0 / fs, axis=1)
    peak_v = float(np.max(np.abs(vel)))
    x, z = mg.channels_to_xz(exc[0], exc[1], a)  # A left (inner) wall, B right (outer)
    # The lathe: speed, feed, the groove's spiral.
    omega = lathe_motion(spec, n, fs, motion_seed)
    theta = np.concatenate([[0.0], np.cumsum(omega[:-1]) / fs])
    half_width = np.maximum(lt["depth_m"] - z, 0.0) * np.tan(a)
    dr = mg.variable_pitch(
        theta, x, 2 * half_width, lt["land_m"], lt["pitch_min_m"], lt["pitch_max_m"]
    )
    r0 = lt["outer_radius_m"] if start_radius_m is None else start_radius_m
    r = r0 - np.cumsum(dr)
    s = np.concatenate([[0.0], np.cumsum(0.5 * (omega[1:] * r[1:] + omega[:-1] * r[:-1]) / fs)])
    s_cut = mg.incline(s, z, cutting_angle(spec))
    ds = omega[0] * r0 / fs
    grid, (xg, zg, rg, thg) = mg.resample_on_grid(s_cut, [x, z, r, theta], ds)
    grid = grid - grid[0]
    wl, wr = mg.walls(xg, zg, a)
    return LPRecord(
        xg, zg, wl, wr, ds, mg.TableSpiral(grid, rg, thg), fs, lead, gain, peak_v,
        mg.lift_outs(z, lt["depth_m"]), omega, s,
    )  # fmt: skip


# Pressing.


def surface_noise_db(
    sigma_m: float, spec: dict, speed_m_s: float, fs_hz: float, seconds=1.0, seed=1
) -> float:
    """The played noise of one wall's roughness of rms sigma at a groove speed: the
    reproducer's tip (a sphere, groove.dilate) on it, its velocity through the RIAA
    reproducing curve, in 500 Hz - 15 kHz, re a 5 cm/s peak tone's rms (NAB's measurement)."""
    srf = spec["surface"]
    ds = speed_m_s / fs_hz
    n = int(seconds * fs_hz)
    w = gv.roughness(n, ds, sigma_m, srf["corr_m"], seed, "noise calibration")
    y = gv.dilate(w, ds, srf["reproducer_tip_m"])
    v = np.diff(y) * fs_hz
    f = np.fft.rfftfreq(len(v), 1.0 / fs_hz)
    spec_v = np.fft.rfft(v)
    play = np.zeros(len(f))
    play[1:] = 1.0 / np.abs(la.riaa_record(f[1:]))
    band = (f >= 500) & (f <= 15000)
    p = np.sum(np.abs(spec_v * play)[band] ** 2) * 2 / len(v) ** 2
    ref = spec["level"]["reference_cm_s"] / 100.0 / np.sqrt(2)
    return float(10 * np.log10(p / ref**2))


def calibrate_surface(spec: dict, speed_m_s: float | None = None) -> float:
    """The roughness's rms for NAB's noise figure, measured at the outer groove's speed."""
    lt = spec["lathe"]
    v = speed_m_s or 2 * np.pi * lt["rpm"] / 60.0 * lt["outer_radius_m"]
    fs = spec["numerics"]["fs_hz"]
    target = -spec["surface"]["noise_db"]
    sigma = 1e-8
    for _ in range(4):  # nearly linear in sigma (the tip's dilation bends it a little)
        sigma *= 10 ** ((target - surface_noise_db(sigma, spec, v, fs)) / 20)
    return sigma


def press(rec: LPRecord, spec: dict, seed: int, sigma_m: float | None = None) -> dict:
    """The vinyl's surface on both walls (in place): roughness, dust, non-fill. Returns the
    counts and the roughness used."""
    srf = spec["surface"]
    sigma = calibrate_surface(spec) if sigma_m is None else sigma_m
    gl, gr = disc.roughness_pair(len(rec.x_m), rec.ds_m, sigma, srf["corr_m"], seed)
    rec.wall_l_m += gl
    rec.wall_r_m += gr
    counts: dict = {"sigma_m": sigma}
    for name, w in (("left", rec.wall_l_m), ("right", rec.wall_r_m)):
        g = gv.Groove(h_m=w, ds_m=rec.ds_m)
        counts[f"dust_{name}"] = dm.dust(g, srf, seed, kind=f"dust {name}")
        counts[f"nonfill_{name}"] = _nonfill(w, rec.ds_m, srf, seed, name)
    return counts


def _nonfill(w: np.ndarray, ds: float, srf: dict, seed: int, name: str) -> int:
    """Non-fill: shallow pits where the vinyl didn't flow into the stamper (in place)."""
    g = disc.rng(seed, f"nonfill {name}")
    n = g.poisson(srf["nonfill_per_m"] * len(w) * ds)
    half = srf["nonfill_length_m"] / 2
    for s0 in g.uniform(0, len(w) * ds, n):
        i0, i1 = max(int((s0 - half) / ds), 0), min(int((s0 + half) / ds) + 1, len(w))
        u = (np.arange(i0, i1) * ds - s0) / half
        w[i0:i1] -= srf["nonfill_depth_m"] * g.uniform(0.5, 1.5) * np.maximum(1 - u * u, 0.0)
    return int(n)
