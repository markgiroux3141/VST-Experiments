"""PB0's bench: each part alone, as the voltage at the part (docs/PART_NOISE_PLAN.md).

Three groups, each through one fixed gain in the "same gain" set (real relative levels within
a group, as in the video):
- **hiss** (volts at the part): resistors, a 12AX7 at idle, popcorn in a BJT;
- **barkhausen** (the avalanche rate around the smooth dM/dt, its absolute level not sourced);
- **pot** (volts at the grid while the knob turns: signal-level events, not a noise floor).

`PARTS` lists them; `render(name, seed)` returns (volts, info).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from varimu.devices import noise
from varimu.part_noise import barkhausen, contact, popcorn, resistor, rng_for

SECONDS = 8.0
BENCH_T_K = 296.0
BENCH_T_SOURCE = "a bench at 23 C, IEC 60068-1's standard atmosphere"
R_OHM = 100e3
DC_V = 100.0
DC_SOURCE = (
    "provisional: model knowledge (a 100k plate load with ~100 V across it: a 12AX7 stage at "
    "~1 mA, the 5F1's and most of the project's tube stages)"
)
GM_12AX7_S = 1.6e-3
GM_SOURCE = "RCA 12AX7 sheet: gm 1600 umho at 250 V, -2 V (B5's corner figure)"
RS_OHM = 47e3
RS_SOURCE = "provisional: a transistor stage fed from a high-impedance source (a guitar input)"
LEAKY_DC_V = 2.5
LEAKY_SOURCE = (
    "provisional: model knowledge (a paper coupling capacitor from a ~160 V plate leaking ~60 "
    "MOhm into a 1 MOhm volume pot: 160 V x 1M / 61M; PB1 takes the plate from the 5F1's file)"
)
C_IN_F = 150e-12
KAPPA_PER_S = 2.0 * math.pi * 1000.0
C_PER_RATE_S = 0.25


@dataclass(frozen=True)
class Part:
    name: str
    group: str  # "hiss" or "events"
    title: str
    values: dict = field(default_factory=dict)  # name -> (value, source)


def _n(rate_hz: float) -> int:
    return int(round(SECONDS * rate_hz))


def _gated_tone(n: int, rate_hz: float, amp: float, f_hz: float = 110.0) -> np.ndarray:
    t = np.arange(n) / rate_hz
    gate = (np.floor(t) % 2 == 0).astype(float)  # 1 s on, 1 s off
    ramp = int(0.01 * rate_hz)
    k = np.ones(ramp) / ramp
    gate = np.convolve(gate, k, mode="same")
    return amp * gate * np.sin(2 * math.pi * f_hz * t)


def _gesture(n: int, rate_hz: float) -> np.ndarray:
    """A hand turning a knob: up, hold, back, wiggle, up again (travel 0..1)."""
    t = np.arange(n) / rate_hz
    keys = [(0.0, 0.30), (0.4, 0.30), (1.9, 0.75), (2.9, 0.75), (3.7, 0.40), (4.0, 0.40)]
    keys += [(5.5, 0.40), (7.5, 0.90), (8.0, 0.90)]
    kt, kx = zip(*keys, strict=True)
    x = np.interp(t, kt, kx)
    wiggle = (t >= 4.0) & (t < 5.5)
    x = x + np.where(wiggle, 0.03 * np.sin(2 * math.pi * 3.0 * (t - 4.0)), 0.0)
    # Smooth the corners: a hand doesn't jerk (a Gaussian: no kink in any derivative, which a
    # box left as audible thumps).
    from scipy import ndimage

    return ndimage.gaussian_filter1d(x, 0.06 * rate_hz, mode="nearest")


TRAP_ONE = popcorn.Trap(100e-12, 0.030, 0.060)
TRAPS_DEFECTIVE = (
    popcorn.Trap(100e-12, 0.030, 0.060),
    popcorn.Trap(40e-12, 0.001, 0.003),
    popcorn.Trap(250e-12, 0.4, 1.5),
)
TRACK_NEW = contact.Track(1e6, crv=0.01, bad_spots=0.0)
TRACK_WORN = contact.Track(1e6, crv=0.10, bad_spots=6.0)

R = (R_OHM, "the bench's resistor")
T = (BENCH_T_K, BENCH_T_SOURCE)
PARTS = [
    Part(
        "johnson_100k",
        "hiss",
        "100k, no current: Johnson noise only (every 100k alike)",
        {"r_ohm": R, "t_k": T},
    ),
    Part(
        "metal_film_100k_100v",
        "hiss",
        "metal film 100k, 100 V DC across it",
        {
            "r_ohm": R,
            "dc_v": (DC_V, DC_SOURCE),
            "noise_index_db": (resistor.METAL_FILM.noise_index_db, resistor.METAL_FILM.source),
        },
    ),
    Part(
        "carbon_comp_100k_100v",
        "hiss",
        "carbon composition 100k, 100 V DC across it",
        {
            "r_ohm": R,
            "dc_v": (DC_V, DC_SOURCE),
            "noise_index_db": (resistor.CARBON_COMP.noise_index_db, resistor.CARBON_COMP.source),
        },
    ),
    Part(
        "carbon_comp_100k_100v_aged",
        "hiss",
        "aged carbon composition 100k, 100 V DC",
        {
            "r_ohm": R,
            "dc_v": (DC_V, DC_SOURCE),
            "noise_index_db": (
                resistor.CARBON_COMP_AGED.noise_index_db,
                resistor.CARBON_COMP_AGED.source,
            ),
        },
    ),
    Part(
        "carbon_comp_follows_tone",
        "hiss",
        "carbon composition 100k, no DC, a 110 Hz current (1 mA peak) 1 s on / 1 s off: "
        "the noise alone, the tone removed",
        {
            "r_ohm": R,
            "peak_current_a": (1e-3, DC_SOURCE),
            "noise_index_db": (resistor.CARBON_COMP.noise_index_db, resistor.CARBON_COMP.source),
        },
    ),
    Part(
        "tube_12ax7_idle",
        "hiss",
        "a 12AX7 at idle, grid-referred: shot + flicker (B5's model)",
        {
            "gm_s": (GM_12AX7_S, GM_SOURCE),
            "flicker_v2": (noise.FLICKER_V2, noise.FLICKER_SOURCE),
            "shot_beta": (noise.SHOT_BETA, noise.SHOT_SOURCE),
        },
    ),
    Part(
        "popcorn_one_trap",
        "hiss",
        "a BJT with one trap: base-current steps into 47k",
        {"rs_ohm": (RS_OHM, RS_SOURCE), "trap": (TRAP_ONE, popcorn.TRAP_SOURCE)},
    ),
    Part(
        "popcorn_defective",
        "hiss",
        "a defective BJT, three traps, into 47k",
        {"rs_ohm": (RS_OHM, RS_SOURCE), "traps": (TRAPS_DEFECTIVE, popcorn.TRAP_SOURCE)},
    ),
    Part(
        "barkhausen_slow_sweep",
        "barkhausen",
        "a core swept slowly through its loop (0.1 Hz): the avalanches alone",
        {
            "kappa_per_s": (KAPPA_PER_S, barkhausen.PARAMS_SOURCE),
            "c_per_rate_s": (C_PER_RATE_S, barkhausen.PARAMS_SOURCE),
            "model": ("ABBM", barkhausen.ABBM_SOURCE),
        },
    ),
    Part(
        "barkhausen_mains",
        "barkhausen",
        "a core driven to saturation at 50 Hz: the avalanches alone",
        {
            "kappa_per_s": (KAPPA_PER_S, barkhausen.PARAMS_SOURCE),
            "c_per_rate_s": (C_PER_RATE_S, barkhausen.PARAMS_SOURCE),
            "model": ("ABBM", barkhausen.ABBM_SOURCE),
        },
    ),
    Part(
        "pot_new_leaky_cap",
        "pot",
        "a new 1M volume pot turned, 2.5 V DC on it from a leaky coupling capacitor",
        {
            "track": (TRACK_NEW, contact.CRV_SOURCE + "; " + contact.TRACK_SOURCE),
            "dc_v": (LEAKY_DC_V, LEAKY_SOURCE),
            "c_in_f": (C_IN_F, contact.TRACK_SOURCE),
        },
    ),
    Part(
        "pot_worn_leaky_cap",
        "pot",
        "a worn 1M volume pot turned, 2.5 V DC on it from a leaky coupling capacitor",
        {
            "track": (TRACK_WORN, contact.CRV_SOURCE + "; " + contact.TRACK_SOURCE),
            "dc_v": (LEAKY_DC_V, LEAKY_SOURCE),
            "c_in_f": (C_IN_F, contact.TRACK_SOURCE),
        },
    ),
    Part(
        "pot_worn_tone",
        "pot",
        "a worn 1M volume pot turned, no DC, a 220 Hz tone of 0.3 V on it",
        {
            "track": (TRACK_WORN, contact.CRV_SOURCE + "; " + contact.TRACK_SOURCE),
            "c_in_f": (C_IN_F, contact.TRACK_SOURCE),
        },
    ),
]
BY_NAME = {p.name: p for p in PARTS}


def render(name: str, seed: int, rate_hz: float) -> np.ndarray:
    """The part's voltage (volts at the part; events: their own scale), n = SECONDS x rate."""
    n = _n(rate_hz)
    rng = rng_for(seed, name)

    def johnson():
        return resistor.johnson_v(R_OHM, BENCH_T_K, n, rate_hz, seed, name)

    def excess(ni, current):
        return resistor.excess_v(current, R_OHM, ni, rate_hz, seed, name)

    i_dc = np.full(n, DC_V / R_OHM)
    if name == "johnson_100k":
        return johnson()
    if name == "metal_film_100k_100v":
        return johnson() + excess(resistor.METAL_FILM.noise_index_db, i_dc)
    if name == "carbon_comp_100k_100v":
        return johnson() + excess(resistor.CARBON_COMP.noise_index_db, i_dc)
    if name == "carbon_comp_100k_100v_aged":
        return johnson() + excess(resistor.CARBON_COMP_AGED.noise_index_db, i_dc)
    if name == "carbon_comp_follows_tone":
        i = _gated_tone(n, rate_hz, 1e-3)
        return johnson() + excess(resistor.CARBON_COMP.noise_index_db, i)
    if name == "tube_12ax7_idle":
        r_eq = noise.SHOT_BETA / GM_12AX7_S
        shot = noise.white_sigma(4 * noise.K_B * noise.SHOT_T0_K * r_eq, rate_hz)
        white = shot * noise.normals(noise.key(seed, name, noise.STREAM_MAIN), 0, n)
        flick = math.sqrt(noise.FLICKER_V2) * noise.unit_stream(
            seed, name, noise.STREAM_FLICKER, True, rate_hz, n
        )
        return white + flick
    if name == "popcorn_one_trap":
        return RS_OHM * popcorn.burst_current([TRAP_ONE], n, rate_hz, rng)
    if name == "popcorn_defective":
        return RS_OHM * popcorn.burst_current(TRAPS_DEFECTIVE, n, rate_hz, rng)
    if name == "barkhausen_slow_sweep":
        t = np.arange(n) / rate_hz
        # A triangle from -1.5 to +1.5 at 0.1 Hz, starting at -1.5 rising.
        ph = (t * 0.1) % 1.0
        h = np.where(ph < 0.5, -1.5 + 6.0 * ph, 4.5 - 6.0 * ph)
        smooth, v = barkhausen.crackle(h, rate_hz, KAPPA_PER_S, C_PER_RATE_S, rng)
        return v - smooth
    if name == "barkhausen_mains":
        t = np.arange(n) / rate_hz
        h = 1.5 * np.sin(2 * math.pi * 50.0 * t)
        smooth, v = barkhausen.crackle(h, rate_hz, KAPPA_PER_S, C_PER_RATE_S, rng)
        return v - smooth
    if name in ("pot_new_leaky_cap", "pot_worn_leaky_cap", "pot_worn_tone"):
        track = TRACK_NEW if name == "pot_new_leaky_cap" else TRACK_WORN
        # One pot per track kind: both worn files turn the same worn pot.
        rng = rng_for(seed, "track_new" if track is TRACK_NEW else "track_worn")
        if name == "pot_worn_tone":
            t = np.arange(n) / rate_hz
            top = 0.3 * np.sin(2 * math.pi * 220.0 * t)
        else:
            top = np.full(n, LEAKY_DC_V)
        grid, _ = contact.turned(top, _gesture(n, rate_hz), track, C_IN_F, rate_hz, rng)
        return grid
    raise KeyError(name)
