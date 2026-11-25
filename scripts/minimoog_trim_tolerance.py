"""How far a technician's trims leave a Minimoog's oscillators off (MINIMOOG_BACKLOG.md
"Authenticity first", item 3), in pitch space only: no circuit runs, a Monte Carlo of the
procedures' resolution.

Folkman's TECHNICAL SERVICE MANUAL (7/73, pp. 12-13; data/schematics/minimoog/README.md) gives the
methods, not tolerances: on 2' the Range trimpot (this board's SHIFT) for 3520 Hz at the high A and
the Scale trimpot for 440 Hz at the low A, "repeat until no further improvement is attainable",
either on a frequency counter at the main output or "Visualign" (the overload lamp's blink, the
oscillator against the A-440: a unison at the low A, the A-440's 8th harmonic at the high A); the
Octave Range trimmer for zero beats with the A-440 on 8' at the second A; "finally, check tracking
between any two oscillators and make any necessary touch-up adjustments". HI END (this board's R31)
postdates his boards. So a trim point is off by its method's resolution:

- a counter on a 1 s gate reads to 1 Hz: +-0.5 Hz at the reading (provisional: model knowledge, the
  period's counters; a 10 s gate is 10x finer);
- zero beats by ear: a beat slower than about one per 3 s passes for none, +-0.33 Hz (provisional:
  model knowledge; every error below scales linearly with it).

Each oscillator's pitch error over the keyboard (cents, MIDI 41-84, footage k octaves below 2')
is the SHIFT / SCALE line through the low and high A, HI END's term (the reset's dead time: cents ~
the frequency, so it shrinks an octave per footage) through the top C, and OCT ADJ's error per range
step from the 8' reading. The player retunes with TUNE and the FREQUENCY knobs at one key (the
second A on 8'), so what is left is the error's shape: a tilt across the keyboard, jumps between
footages, and for two oscillators in unison a beat rate that changes along the keyboard. The
keyboard string's 43 x 10 ohm 1 % resistors (Fig 9-7) are drawn too: their error is common to all
oscillators (no beating).

    uv run python scripts/minimoog_trim_tolerance.py [--units 4000] [--seed 1]

Writes reports/minimoog/units/trim_tolerance.json.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

OUT = Path(__file__).resolve().parents[1] / "reports" / "minimoog" / "units"
KEYS = np.arange(41, 85)  # F2 .. C6, the 44 keys (key_ref_note 41)
LOW_A, SECOND_A, HIGH_A, TOP_C = 45, 57, 81, 84
FOOT = {"32'": 4, "16'": 3, "8'": 2, "4'": 1, "2'": 0}  # octaves below 2'
EAR_HZ = 0.33  # a zero beat by ear
COUNTER_HZ = 0.5  # a 1 s gate


def hz(note: int | np.ndarray, k: int = 0) -> np.ndarray:
    """On footage k: 440 Hz at the low A on 2'."""
    return 440.0 * 2.0 ** ((np.asarray(note) - LOW_A) / 12.0) / 2.0**k


def c_of(df_hz: float, f_hz: float) -> float:
    return 1200.0 * np.log2(1.0 + df_hz / f_hz)


def resolutions(method: str) -> dict:
    """The half-width (cents) of each trim point's error."""
    lo = EAR_HZ if method == "ear" else COUNTER_HZ
    return {
        "lo": c_of(lo, 440.0),  # unison with the A-440 / the counter at 440
        "hi": c_of(lo, 3520.0),  # the A-440's 8th harmonic / the counter at 3520
        "top": c_of(COUNTER_HZ, float(hz(TOP_C))),  # HI END: not in Folkman; a counter at the top C
        "oct": c_of(EAR_HZ, 440.0),  # 8' second A (220 Hz) zero beat: its 2nd harmonic on 440
    }


def unit_errors(pts: np.ndarray) -> np.ndarray:
    """pts (..., 4): lo, hi, top, oct (cents at their points) -> errors (..., footage, key)."""
    lo, hi, top, oc = (pts[..., i] for i in range(4))
    # a + b (n - 45) + c g(n) through the three 2' points, g = f / f(top C) (the dead time)
    g = lambda n, k=0: hz(n, k) / hz(TOP_C)  # noqa: E731
    m = np.array([[1, 0, g(LOW_A)], [1, HIGH_A - LOW_A, g(HIGH_A)], [1, TOP_C - LOW_A, 1.0]])
    a, b, c = np.moveaxis(np.linalg.solve(m, np.stack([lo, hi, top], -1)[..., None])[..., 0], -1, 0)
    line = lambda n, k: a[..., None] + b[..., None] * (n - LOW_A) + c[..., None] * g(n, k)  # noqa: E731
    at8 = line(np.array([SECOND_A]), 2)[..., 0]
    per_step = (oc - at8) / 2.0  # the 8' reading sets OCT ADJ's error per range step
    return np.stack([line(KEYS, k) + per_step[..., None] * k for k in FOOT.values()], -2)


def draw(rng: np.random.Generator, n: int, res: dict) -> np.ndarray:
    half = np.array([res["lo"], res["hi"], res["top"], res["oct"]])
    return rng.uniform(-1.0, 1.0, (n, 4)) * half


def pct(x: np.ndarray) -> dict:
    return {f"p{q}": round(float(np.percentile(x, q)), 3) for q in (50, 95)}


def study(rng: np.random.Generator, n: int, method: str) -> dict:
    res = resolutions(method)
    e1 = unit_errors(draw(rng, n, res))  # (n, footage, key)
    ia, i8 = int(np.nonzero(KEYS == SECOND_A)[0][0]), FOOT["8'"]
    tuned = e1 - e1[:, i8 : i8 + 1, ia : ia + 1]  # TUNE at the second A on 8'
    solo = {
        f: pct(np.abs(e1[:, k] - e1[:, k, ia : ia + 1]).max(-1)) for f, k in FOOT.items()
    }  # the shape across the keyboard within a footage
    jumps = {f: pct(np.abs(tuned[:, k, ia])) for f, k in FOOT.items() if f != "8'"}
    # a second oscillator, touched up against the first at the low and high A (unison beats)
    q1 = draw(rng, n, res)
    q2 = draw(rng, n, res)  # HI END and OCT ADJ its own
    touch = rng.uniform(-1.0, 1.0, (n, 2)) * np.array([c_of(EAR_HZ, 440.0), c_of(EAR_HZ, 3520.0)])
    q2[:, 0:2] = q1[:, 0:2] + touch
    d = unit_errors(q2) - unit_errors(q1)
    d = d - d[:, i8 : i8 + 1, ia : ia + 1]  # FREQUENCY 2 for the unison at the second A on 8'
    beats = {}
    for f, k in FOOT.items():
        fr = hz(KEYS, k)
        db = np.abs(fr * (2.0 ** (d[:, k] / 1200.0) - 1.0))  # Hz of beat the unison picks up
        beats[f] = {"max_hz": pct(db.max(-1)), "cents_max": pct(np.abs(d[:, k]).max(-1))}
    return {
        "resolution_cents": {k: round(v, 3) for k, v in res.items()},
        "solo_shape_cents": solo,
        "footage_jump_cents": jumps,
        "unison_8ft_tuned": beats,
    }


def string(rng: np.random.Generator, n: int) -> dict:
    """The 43 resistors, each uniform +-1 % (a bound: real 1 % parts sit tighter), the lowest key on
    ground; the trims take out the line through the low and high A."""
    d = rng.uniform(-0.01, 0.01, (n, 43))
    v = np.concatenate([np.zeros((n, 1)), np.cumsum(1.0 + d, 1)], 1)  # semitones at taps 0..43
    k = KEYS - 41
    lo, hi = LOW_A - 41, HIGH_A - 41
    line = v[:, [lo]] + (v[:, [hi]] - v[:, [lo]]) * (k - lo) / (hi - lo)
    err = 100.0 * (v[:, k] - line)  # cents off the trimmed line
    step = 100.0 * np.abs(d)  # a semitone's own error
    return {"key_cents_max": pct(np.abs(err).max(-1)), "semitone_cents_max": pct(step.max(-1))}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--units", type=int, default=4000)
    ap.add_argument("--seed", type=int, default=1)
    a = ap.parse_args()
    out = {
        m: study(np.random.default_rng([a.seed, i]), a.units, m)
        for i, m in enumerate(("counter", "ear"))
    }
    out["string"] = string(np.random.default_rng([a.seed, 9]), a.units)
    out["assumptions"] = {"ear_hz": EAR_HZ, "counter_hz": COUNTER_HZ, "units": a.units}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "trim_tolerance.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
