"""An imperfect Rhodes: one instrument's key-to-key irregularities, and how each strike and
release differs from the last (docs/RHODES_IMPERFECTION_PLAN.md). `varimu/rhodes/harp.py`'s
voices take it (`harp.render(..., imperfection=)`, the reference); circuitsim's `harp.rs`
(`Imperfection`, applied where the medium builds its voices and at each event) is the port.

An **amount** (the panel's IMPERFECTION) and seven parts' shares of it, and a seed (the unit:
which instrument). A part's amount is amount x its share, at most `AMOUNT_MAX`: 0 the compiled
harp exactly, 1 a real, played, maintained Mark I (the spreads below), 2 beyond (a neglected
one, for character). The shares default to 1. Every draw is a pure function of (seed, its name,
the key) and, per strike or release, of that key's count of them since the medium started, so
a take replays bit for bit and changing one share moves only what it scales.

**Per instrument** (drawn once per key, applied when the voices are built):

- **tuning**: each key off equal temperament by its own cents (a normal). Applied as a time
  scaling of the key's tone generator (its stiffness by r^2, the mass kept): every mode's
  eigenvalue times r, the hammer's input b over r, the velocity rows (strike, tip) times r;
  the damper's transfers are unchanged (both systems scale alike). Exact for the compiled data.
- **voicing**: the tip's height over the pole moved by a normal, within `VOICING_RANGE_M`
  (the timbre: the fundamental against the second harmonic, and the level).
- **tips**: the neoprene's hardness: the hammer's contact stiffness K times a lognormal.
- **decay**: how long the key sustains: every oscillating free mode's decay rate times a
  lognormal. Applied where the modes rotate freely; the hammer's contact steps keep the
  compiled decays (as the Clavinet's wear, `varimu/clavinet/wear.py`: a decay changed under
  a mode's compiled residues can make the contact's driving point active).
- **dampers**: the felt: each damped mode's decay above the free tine's own (the least decay
  of the free modes within `DAMPER_BAND` of its frequency) times a lognormal, at least
  `DAMPER_MIN`: a worn felt lets the note ring on after the key comes up, a firm one cuts it.

**Per strike / release** (drawn at each event):

- **hammer**: each strike's contact stiffness (the tip's compression and patch) and hammer
  speed (the action's friction) off by small lognormals, so a repeated note at one velocity
  isn't the same computation twice.
- **release**: each release's felt landing: the dampers' factor above times one more
  lognormal (a release is each switch from the free tine onto the felt: a key coming up, or
  the pedal's, while the hammer is off the tine).

Values: see each constant's source.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from varimu.devices import noise

#: The largest part amount (2: beyond a realistic instrument).
AMOUNT_MAX = 2.0

#: Per-key detune at tuning 1, cents rms. Measured (2026-11-22, scripts/rhodes_unit_spread.py):
#: jRhodes3d's notes from E2 up, their fundamentals in the softer layers against equal
#: temperament, 2.09 cents rms about their mean (15 notes; 90% interval 1.6-3.2); its F1 and
#: B1 sit 9 and 3 cents flat (not modelled: one spread for every key).
TUNING_CENTS = 2.1
#: Per-key voicing offset at voicing 1, m rms. Derived: a voicing fitted per key to jRhodes3d's
#: layers came out 0.9-2.4 mm (median 2.0; config/rhodes/mk1.yaml's pickup.voicing_m), a fit's
#: scatter (it trades against the EQ), read as ~0.3 mm rms of a real piano's.
VOICING_M = 0.3e-3
#: The voicing stays within these (m). Provisional: model knowledge (the manual's "slightly
#: above dead center"; past 3.5 mm the pole barely sees the tip's swing at mezzo-forte).
VOICING_RANGE_M = (0.5e-3, 3.5e-3)
#: The tips' contact stiffness at tips 1: lognormal sigma. Provisional: model knowledge
#: (neoprene of one nominal durometer is held to about +-5 Shore A and hardens with age; by
#: Gent's relation +-5 Shore A at 50 is about +-20% of the modulus, and K is linear in it).
TIPS_SPREAD = 0.2
#: The free modes' decay at decay 1: lognormal sigma. Measured (2026-11-22,
#: scripts/rhodes_unit_spread.py): config/rhodes/mk1.yaml's q_jrhodes about the cubic the tine's
#: loss is fitted to, 0.257 rms in ln Q (15 notes; it includes the measurement's own scatter).
DECAY_SPREAD = 0.25
#: The felt's damping above the tine's own at dampers 1: lognormal sigma. Provisional: model
#: knowledge (a Rhodes' dampers are notoriously uneven: some keys ring on for a few tenths of
#: a second after release, others stop dead).
DAMPER_SPREAD = 0.35
#: The felt's factor's floor (a felt always damps). Numerical.
DAMPER_MIN = 0.1
#: A damped mode's "own" decay: the least free decay within this fraction of its frequency.
DAMPER_BAND = 0.15
#: Each strike's contact stiffness at hammer 1: lognormal sigma. Provisional: model knowledge
#: (the neoprene's patch and compression differ stroke to stroke).
STRIKE_K_SPREAD = 0.08
#: Each strike's hammer speed at hammer 1, dB rms. Provisional: model knowledge (the action's
#: friction and the escapement at one key speed).
STRIKE_SPEED_DB = 0.4
#: Each release's felt factor at release 1: lognormal sigma. Provisional: model knowledge
#: (the felt lands with more or less pressure as the key comes up).
RELEASE_SPREAD = 0.25
#: A complex eigenvalue is a pair (oscillating) above this |Im| / |lambda| (compile._halve).
PAIR = 1e-12

PARTS = ("tuning", "voicing", "tips", "decay", "dampers", "hammer", "release")
KEY_NAME = "rhodes.imperfection"
STRIKE_NAME = "rhodes.imperfection.strike"
RELEASE_NAME = "rhodes.imperfection.release"


@dataclass(frozen=True)
class Imperfection:
    """An instrument's imperfection (see the module docstring)."""

    seed: int = 1
    amount: float = 1.0
    tuning: float = 1.0
    voicing: float = 1.0
    tips: float = 1.0
    decay: float = 1.0
    dampers: float = 1.0
    hammer: float = 1.0
    release: float = 1.0

    def part(self, name: str) -> float:
        """The part's amount: amount x its share, at most `AMOUNT_MAX`."""
        return min(self.amount * getattr(self, name), AMOUNT_MAX)

    def none(self) -> bool:
        """No imperfection at all: the compiled harp exactly (the seed doesn't matter)."""
        return all(self.part(p) == 0.0 for p in PARTS)


def check(imp: Imperfection) -> None:
    if isinstance(imp.seed, bool) or int(imp.seed) != imp.seed or not 0 <= imp.seed < 2**53:
        raise ValueError(f"imperfection seed {imp.seed!r}: a whole number in [0, 2^53)")
    for a in ("amount", *PARTS):
        v = getattr(imp, a)
        if not (math.isfinite(v) and 0.0 <= v <= AMOUNT_MAX):
            raise ValueError(f"imperfection {a} = {v}: in [0, {AMOUNT_MAX}]")


@dataclass(frozen=True)
class KeyDraws:
    """One key's per-instrument values (identity at amount 0)."""

    ratio: float  # its frequencies' factor
    voicing_m: float  # its voicing (absolute)
    stiffness: float  # its contact stiffness' factor
    decay: float  # its free modes' decay factor
    damper: float  # its felt's factor


def key_draws(imp: Imperfection | None, key: int, voicing_m: float) -> KeyDraws:
    """Key `key`'s values; `voicing_m` the compiled voicing."""
    if imp is None or imp.none():
        return KeyDraws(1.0, voicing_m, 1.0, 1.0, 1.0)
    z = noise.normals(noise.key(int(imp.seed), KEY_NAME, key), 0, 5)
    tuning, voicing, tips, decay, dampers = (imp.part(p) for p in PARTS[:5])
    ratio = 2.0 ** (tuning * TUNING_CENTS * float(z[0]) / 1200.0) if tuning > 0 else 1.0
    v = voicing_m
    if voicing > 0:
        lo, hi = VOICING_RANGE_M
        v = min(max(voicing_m + voicing * VOICING_M * float(z[1]), lo), hi)
    k = math.exp(tips * TIPS_SPREAD * float(z[2])) if tips > 0 else 1.0
    d = math.exp(decay * DECAY_SPREAD * float(z[3])) if decay > 0 else 1.0
    g = max(math.exp(dampers * DAMPER_SPREAD * float(z[4])), DAMPER_MIN) if dampers > 0 else 1.0
    return KeyDraws(ratio, v, k, d, g)


def strike_draws(imp: Imperfection | None, key: int, count: int) -> tuple[float, float]:
    """Key `key`'s `count`-th strike (from 0): its (stiffness factor, speed factor)."""
    if imp is None or imp.none():
        return 1.0, 1.0
    a = imp.part("hammer")
    if a == 0:
        return 1.0, 1.0
    z = noise.normals(noise.key(int(imp.seed), STRIKE_NAME, key), 2 * count, 2)
    return (
        math.exp(a * STRIKE_K_SPREAD * float(z[0])),
        10.0 ** (a * STRIKE_SPEED_DB * float(z[1]) / 20.0),
    )


def release_draw(imp: Imperfection | None, key: int, count: int) -> float:
    """Key `key`'s `count`-th release (from 0): its felt factor."""
    if imp is None or imp.none():
        return 1.0
    a = imp.part("release")
    if a == 0:
        return 1.0
    z = noise.normals(noise.key(int(imp.seed), RELEASE_NAME, key), count, 1)
    return math.exp(a * RELEASE_SPREAD * float(z[0]))


def pairs(lam: np.ndarray) -> np.ndarray:
    return np.abs(lam.imag) > PAIR * np.abs(lam)


def decayed(lam: np.ndarray, factor: float) -> np.ndarray:
    """The oscillating modes' decay rates times `factor`."""
    if factor == 1.0:
        return lam
    out = lam.copy()
    p = pairs(lam)
    out[p] = lam.real[p] * factor + 1j * lam.imag[p]
    return out


def damped(lam_d: np.ndarray, lam_f: np.ndarray, factor: float) -> np.ndarray:
    """The damped system's oscillating modes with `factor` of their decay above the free
    tine's own (the least decay of the free pairs within `DAMPER_BAND` of the frequency, or of
    all of them), loops in order so both languages sum alike."""
    if factor == 1.0:
        return lam_d
    out = lam_d.copy()
    pf = pairs(lam_f)
    fh = np.abs(lam_f.imag[pf])
    sh = -lam_f.real[pf]
    if sh.size == 0:
        return out
    floor_all = float(np.min(sh))
    for j in np.flatnonzero(pairs(lam_d)):
        f = abs(lam_d[j].imag)
        near = np.abs(fh - f) <= DAMPER_BAND * f
        floor = float(np.min(sh[near])) if np.any(near) else floor_all
        s = -lam_d[j].real
        if s > floor:
            out[j] = complex(-(floor + (s - floor) * factor), lam_d[j].imag)
    return out
