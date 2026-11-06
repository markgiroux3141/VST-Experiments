"""A worn Clavinet: one instrument's per-key irregularities and age, drawn from a seed and
applied to the compiled strings once, at load (docs/CLAVINET_PLAN.md, "Variation and
wear"). The user's rule for it: what costs no compute goes into the live tier; this does
(the voices run the same operations on other numbers), so the app plays it live. circuitsim's
`clavinet.rs` (`ClavModel::worn`) is the port; this is the reference.

An **age** and five parts' shares of it, and a seed (the unit: which instrument). A part's
amount is age x its share, at most `WEAR_MAX`: 0 a freshly serviced instrument (the
compiled strings exactly), 1 a well-worn old one (realistic), 2 beyond (neglected, for
character). The shares default to 1 (every part as old as the instrument); one at 0 keeps
that part new, at 2 twice as worn. Every draw is a pure function of (seed, its name, the
key), so changing one amount moves only what it scales.

**Where it acts.** The modes' new frequencies and decays act where the modes rotate freely:
the hold (`held.lam`) and the released string ringing between contacts (a new array,
`released.lam_free`). The contact runs (the strike and the release, a few milliseconds
each) step the compiled released modes: a decay changed under a mode's compiled residues
makes the driving point active, and the contact's feedback then grows without bound (yarn
damping kept at 0.4 broke strikes on 2 of 6 keys). With no feedback the free rotations
are stable at any decay. The switches' transfers stay the compiled ones (the approximation
aftertouch's bend already makes).

- **tuning**: each string off by its own cents (a normal, `TUNING_CENTS` per unit): every
  mode's frequency scaled by the same ratio, as a tension change does.
- **strings**: old strings (corrosion, dirt): extra loss growing as the square of the
  frequency (the upper partials die first), per key its own share (lognormal); and the
  modes' frequencies scattered by a fraction of a cent each (uneven mass along the wire:
  the polarizations split, "false beats").
- **tangents**: the rubber tips hardened with age, each its own amount: Shore A up by
  `TANGENTS_SHORE` per unit (lognormal per key, capped at `SHORE_MAX`), the Hunt-Crossley
  stiffness scaled by Gent's modulus (`spec.gent_youngs_pa`), so the strike's contact is
  shorter and brighter. The held system stays the compiled one (linearized about the
  nominal rubber's compression under the hold force); the strike's end and the release's
  start move the tangent by the difference between the two compressions
  (`contact.hold_shift_m`), so the hold starts at its static press.
- **yarn**: the yarn compacted and worn thin: the released system's oscillating modes keep
  `(1 - YARN_LOSS)^(yarn g)` of their damping above the string's own (the held modes'
  lowest decay near the same frequency; g lognormal per key), so a note rings on after its
  release.
- **pickups**: the strings' heights over the pickups: per bar of ten strings (its
  screws) and per string (the wire's own sag), the clearance moved by normals; level and
  the pickup's nonlinearity change key to key.

Values are provisional (model knowledge): each constant below says so.
"""

from __future__ import annotations

import copy
import math
from dataclasses import dataclass

import numpy as np

from varimu.clavinet import spec
from varimu.devices import noise

#: The largest amount (2: beyond a realistic old instrument).
WEAR_MAX = 2.0

#: Per-key detune at tuning 1, cents rms. Provisional: model knowledge (a Clavinet some
#: months from its last tuning drifts by roughly 5-10 cents string to string).
TUNING_CENTS = 6.0
#: Old strings' extra decay rate at `STRINGS_F_REF_HZ` at strings 1, 1/s: E4's partials near
#: 3 kHz decay twice as fast ([G13] Fig. 8's T60 ~3.8 s halved). Provisional: model
#: knowledge (dull old strings lose their upper partials first).
STRINGS_SIGMA_REF = 6.91 / 3.8
STRINGS_F_REF_HZ = 3000.0
#: Each key's share of the loss: lognormal, this sigma. Provisional.
STRINGS_SPREAD = 0.3
#: Each mode's frequency scatter at strings 1, cents rms. Provisional: model knowledge
#: (beats of a few tenths of a hertz in the mid range).
STRINGS_JITTER_CENTS = 0.5
#: The compiled tangents' rubber, Shore A (config/clavinet/d6.yaml's tangent.rubber_shore_a;
#: tests/test_clavinet_wear.py checks they agree).
NOMINAL_SHORE = 60.0
#: Hardening at tangents 1, Shore A (lognormal per key, sigma `TANGENTS_SPREAD`).
#: Provisional: model knowledge (rubber ages 10-20 Shore A harder over decades).
TANGENTS_SHORE = 12.0
TANGENTS_SPREAD = 0.4
SHORE_MAX = 90.0
#: The yarn's share of a released mode's damping lost at yarn 1 (the share kept is
#: (1 - YARN_LOSS)^(yarn g), g lognormal per key, sigma `YARN_SPREAD`). Provisional: model
#: knowledge (a worn weave lets a released note ring a few tenths of a second instead of
#: [G13]'s ~0.1 s).
YARN_LOSS = 0.6
YARN_SPREAD = 0.3
#: The held modes counted as "near" a released one: within this fraction of its frequency.
YARN_BAND = 0.15
#: The strings' heights at pickups 1: per bar and per string, m rms. Provisional: model
#: knowledge (a bar's screws and a string's sag move the ~3 mm clearance by tenths of a mm;
#: ~0.3 mm rms is about +-2 dB of level key to key by the pickup's map, more on the peaks:
#: a string swinging nearer the bar meets the map's steep part).
PICKUP_BAR_M = 0.25e-3
PICKUP_STRING_M = 0.15e-3
#: The clearance stays within these multiples of the compiled one.
PICKUP_RANGE = (0.6, 1.6)
#: Strings per pickup bar ([R12] 2, config/clavinet/d6.yaml's pickups.strings_per_bar).
BAR_STRINGS = 10
#: A complex eigenvalue counts as a pair (oscillating) above this |Im| / |lambda|
#: (`clavinet.rs`' set_pressure's test).
PAIR = 1e-12

AMOUNTS = ("tuning", "strings", "tangents", "yarn", "pickups")


@dataclass(frozen=True)
class Wear:
    """An instrument's wear (see the module docstring)."""

    seed: int = 1
    age: float = 1.0
    tuning: float = 1.0
    strings: float = 1.0
    tangents: float = 1.0
    yarn: float = 1.0
    pickups: float = 1.0

    def amount(self, part: str) -> float:
        """The part's amount: age x its share, at most `WEAR_MAX`."""
        return min(self.age * getattr(self, part), WEAR_MAX)

    def new(self) -> bool:
        """No wear at all: the compiled strings exactly (the seed doesn't matter)."""
        return all(self.amount(a) == 0.0 for a in AMOUNTS)


def check(w: Wear) -> None:
    if isinstance(w.seed, bool) or int(w.seed) != w.seed or not 0 <= w.seed < 2**53:
        raise ValueError(f"wear seed {w.seed!r}: a whole number in [0, 2^53)")
    for a in ("age", *AMOUNTS):
        v = getattr(w, a)
        if not (math.isfinite(v) and 0.0 <= v <= WEAR_MAX):
            raise ValueError(f"wear {a} = {v}: in [0, {WEAR_MAX}]")


def _key_draws(seed: int, n: int) -> np.ndarray:
    """Key n's draws: tuning, strings, tangents, yarn, the centre and bridge pickups."""
    return noise.normals(noise.key(seed, "clavinet.wear", n), 0, 6)


def _bar_draws(seed: int, bar: int) -> np.ndarray:
    """A pickup bar's draws: the centre and bridge pickups' bars."""
    return noise.normals(noise.key(seed, "clavinet.wear.bars", bar), 0, 2)


def _pairs(lam: np.ndarray) -> np.ndarray:
    return np.abs(lam.imag) > PAIR * np.abs(lam)


def _yarn(lam_r: np.ndarray, lam_h: np.ndarray, keep: float) -> np.ndarray:
    """The released modes with `keep` of their damping above the string's own."""
    out = lam_r.copy()
    hp = _pairs(lam_h)
    fh, sh = np.abs(lam_h.imag[hp]), -lam_h.real[hp]
    if sh.size == 0:
        return out
    floor_all = float(np.min(sh))
    for j in np.flatnonzero(_pairs(lam_r)):
        f = abs(lam_r[j].imag)
        near = np.abs(fh - f) <= YARN_BAND * f
        floor = float(np.min(sh[near])) if np.any(near) else floor_all
        s = -lam_r[j].real
        if s > floor:
            out[j] = complex(-(floor + (s - floor) * keep), lam_r[j].imag)
    return out


def _decay(lam: np.ndarray, extra: float) -> np.ndarray:
    """Old strings' loss: `extra` 1/s at the reference frequency, as its square."""
    out = lam.copy()
    for j in np.flatnonzero(_pairs(lam)):
        f = abs(lam[j].imag) / (2.0 * math.pi)
        r = f / STRINGS_F_REF_HZ
        out[j] = complex(lam[j].real - extra * (r * r), lam[j].imag)
    return out


def _tune(lam: np.ndarray, cents: float, jitter: np.ndarray, jitter_cents: float) -> np.ndarray:
    """Every oscillating mode's frequency by 2^((cents + jitter_cents z_j) / 1200)."""
    out = lam.copy()
    for j in np.flatnonzero(_pairs(lam)):
        ratio = 2.0 ** ((cents + jitter_cents * float(jitter[j])) / 1200.0)
        out[j] = complex(lam[j].real, lam[j].imag * ratio)
    return out


def apply(
    header: dict, arrays: dict[int, dict[str, np.ndarray]], w: Wear | None
) -> tuple[dict, dict[int, dict[str, np.ndarray]]]:
    """The compiled strings (`compile.load_data`'s) worn by `w`: new header and arrays (the
    inputs untouched; arrays not worn are shared)."""
    if w is None or w.new():
        return header, arrays
    check(w)
    seed = int(w.seed)
    tuning, strings, tangents, yarn, pickups = (w.amount(a) for a in AMOUNTS)
    h = copy.deepcopy(header)
    out: dict[int, dict[str, np.ndarray]] = {}
    for kd in h["keys"]:
        n = kd["key"]
        a = dict(arrays[n])
        z = _key_draws(seed, n)
        lam_r, lam_h = a["released.lam"], a["held.lam"]
        # yarn (on the compiled decays), then old strings, then the frequencies
        if yarn > 0.0:
            g = yarn * math.exp(YARN_SPREAD * float(z[3]))
            lam_r = _yarn(lam_r, lam_h, (1.0 - YARN_LOSS) ** g)
        jitter = np.zeros(lam_r.size + lam_h.size)
        if strings > 0.0:
            extra = strings * STRINGS_SIGMA_REF * math.exp(STRINGS_SPREAD * float(z[1]))
            lam_r, lam_h = _decay(lam_r, extra), _decay(lam_h, extra)
            jitter = noise.normals(noise.key(seed, "clavinet.wear.modes", n), 0, jitter.size)
        if tuning > 0.0 or strings > 0.0:
            cents = tuning * TUNING_CENTS * float(z[0])
            jc = strings * STRINGS_JITTER_CENTS
            lam_r = _tune(lam_r, cents, jitter[: lam_r.size], jc)
            lam_h = _tune(lam_h, cents, jitter[lam_r.size :], jc)
        # the contacts keep the compiled released modes (the module docstring)
        a["released.lam_free"], a["held.lam"] = lam_r, lam_h
        if tangents > 0.0:
            c = kd["contact"]
            shore = min(
                NOMINAL_SHORE + tangents * TANGENTS_SHORE * math.exp(TANGENTS_SPREAD * float(z[2])),
                SHORE_MAX,
            )
            k0 = c["rubber_k"]
            k1 = k0 * spec.gent_youngs_pa(shore) / spec.gent_youngs_pa(NOMINAL_SHORE)
            p, f = c["rubber_p"], c["hold_force_n"]
            c["rubber_k"] = k1
            c["hold_shift_m"] = (f / k0) ** (1.0 / p) - (f / k1) ** (1.0 / p)
        if pickups > 0.0:
            bar = _bar_draws(seed, (n - 1) // BAR_STRINGS)
            for j, name in enumerate(("centre", "bridge")):
                pk = kd["pickups"][name]
                c0 = pk["clearance_m"]
                moved = c0 + pickups * (
                    PICKUP_BAR_M * float(bar[j]) + PICKUP_STRING_M * float(z[4 + j])
                )
                pk["clearance_m"] = min(max(moved, PICKUP_RANGE[0] * c0), PICKUP_RANGE[1] * c0)
        out[n] = a
    return h, out
