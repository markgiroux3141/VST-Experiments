"""The Minimoog oscillator's factory trims (config/circuits/minimoog_vco.yaml;
docs/MINIMOOG_PLAN.md MM3), after Folkman's oscillator tuning (the TECHNICAL SERVICE MANUAL p.
12-13, data/schematics/minimoog/README.md): on 2', the 'Range trimpot' (this board's SHIFT, R14)
for 3520 Hz at the high A and the Scale trimpot (SCALE, R16) for 440 Hz at the low A, repeated
until nothing improves; the Octave Range trimmer (OCT ADJ, R18) for 8' two octaves below 2' on
the same key. This board's HI END (R31, not in
Folkman's text: his boards predate it) is trimmed with SHIFT and SCALE for the top key's C on 2'
(4186.0 Hz: equal temperament from the low A's 440 Hz), so the reset's dead time is taken out.

Frequencies come from the full-physics reference: the oscillator at REFERENCE_FS with local error
control, measured on the ramp's falling crossings of its middle (interpolated between samples) over
whole periods after a settle.

    uv run --extra fast python scripts/minimoog_vco_trim.py [--write]

--write puts r14_at, r16_at, r18_at, r31_at into the circuit file. Writes
reports/minimoog/vco/trim.json."""

from __future__ import annotations

import argparse
import dataclasses
import json
import math
import re
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

from varimu.circuit import builder, spec
from varimu.config import CONFIG_DIR
from varimu.sim import fast
from varimu.sim.io import TransientSettings

CIRCUIT = CONFIG_DIR / "circuits" / "minimoog_vco.yaml"
KEYBOARD = CONFIG_DIR / "circuits" / "minimoog_keyboard.yaml"
OUT = Path(__file__).resolve().parents[1] / "reports" / "minimoog" / "vco"
# The reference's rate: the reset (~0.5 us) lands on the step grid, and local error control
# doesn't catch it (the period's jitter is the same at tolerances 1e-5 .. 1e-7): at 3.072 MHz
# 2 cents rms a period and 0.8 cents of bias, at 12.288 MHz 0.08 rms and the mean within 0.03
# cents of 24.6 and 49 MHz (reports/minimoog/vco/README.md).
REFERENCE_FS = 12_288_000
SETTLE_S = 0.005
PERIODS = 16
RANGE_2 = 5  # the RANGE switch's positions: 0 LO, 1 32', 2 16', 3 8', 4 4', 5 2'
RANGE_8 = 3
LOW_A, HIGH_A, TOP_C = 45, 81, 84  # MIDI: the keyboard's first and fourth A, its top C
A_HZ = 440.0  # the low A on 2'
TRIMS = ("r14_at", "r16_at", "r31_at", "r18_at")


def keyboard_volts(note: int) -> float:
    """The keyboard circuit's pitch-bar volts for MIDI `note` (its file's key_* values)."""
    k = spec.load_circuit(KEYBOARD).values
    v = (note - k["key_ref_note"]["value"]) * k["key_v_per_semitone"]["value"]
    return float(np.clip(v, k["key_min_v"]["value"], k["key_max_v"]["value"]))


def target_hz(note: int, rng: int = RANGE_2) -> float:
    """Equal temperament from the low A's 440 Hz on 2', octaves down per range step."""
    return A_HZ * 2.0 ** ((note - LOW_A) / 12.0) / 2.0 ** (RANGE_2 - rng)


def reference_settings(fs: int = REFERENCE_FS) -> TransientSettings:
    s = TransientSettings.from_sim_settings(engine="circuitsim")
    return dataclasses.replace(
        s, sample_rate=fs, oversample=1, settle_s=SETTLE_S, error_abstol=1e-5,
        error_reltol=1e-5, newton_reltol=1e-7, newton_vntol=1e-7,
    )  # fmt: skip


def falling_crossings(x: np.ndarray, level: float) -> np.ndarray:
    """Sample positions (fractional) where x falls through `level`."""
    k = np.nonzero((x[:-1] >= level) & (x[1:] < level))[0]
    return k + (x[k] - level) / (x[k] - x[k + 1])


def measure_hz(
    overrides: dict, note: int, rng: int = RANGE_2, settings: TransientSettings | None = None,
    periods: int = PERIODS,
) -> float:  # fmt: skip
    """The oscillator's frequency at MIDI `note`, RANGE `rng` (the ramp's mean period)."""
    st = settings or reference_settings()
    s = spec.load_circuit(CIRCUIT)
    # the literal circuit (its reset's exception is generated from this reference)
    ir = builder.build_ir(s, spec.resolve(s, {**overrides, "osc_range": rng}), "linear", literal=True)
    n = round((periods + 2) / target_hz(note, rng) * 1.3 * st.sample_rate)
    r = fast.run_transient(
        ir, np.zeros(n), settings=st, controls={"key": np.full(n, keyboard_volts(note))}
    )
    t = falling_crossings(r.vectors["v(ramp)"], 2.5)
    if len(t) < 3:
        raise RuntimeError(f"no oscillation at note {note}, range {rng}: {overrides}")
    t = t[1:]  # the first crossing may follow the start's transient
    return float((len(t) - 1) / (t[-1] - t[0]) * st.sample_rate)


def cents(f: float, ref: float) -> float:
    return 1200.0 * math.log2(f / ref)


def trim(trims: dict, log=print) -> dict:
    """All four together: Newton on the four targets (low A, high A and top C on 2', the low A
    on 8' at a quarter of 2''s 440 Hz), each Jacobian column by a finite step, until every
    target is within 0.05 cents. (In turn, as Folkman iterates by hand, OCT ADJ moves 2' too
    and HI END is weakly determined: the alternation crept.)"""
    trims = dict(trims)
    pts = [(LOW_A, RANGE_2), (HIGH_A, RANGE_2), (TOP_C, RANGE_2), (LOW_A, RANGE_8)]
    keys = ("r14_at", "r16_at", "r31_at", "r18_at")
    pool = ThreadPoolExecutor(20)
    cols = ThreadPoolExecutor(len(keys))  # the Jacobian's columns at once, each on `pool`

    def errs(t: dict) -> np.ndarray:
        fs = list(pool.map(lambda p: measure_hz(t, *p), pts))
        return np.array([cents(f, target_hz(*p)) for f, p in zip(fs, pts, strict=True)])

    best = (float("inf"), dict(trims))
    for _it in range(10):
        e = errs(trims)
        log(f"  {[round(trims[k], 5) for k in keys]}: cents {e.round(3).tolist()}", flush=True)
        if np.abs(e).max() < best[0]:
            best = (float(np.abs(e).max()), dict(trims))
        if best[0] < 0.05:
            break
        h = 2e-3
        jac = np.empty((len(pts), len(keys)))
        for j, ek in enumerate(cols.map(lambda k, h=h: errs({**trims, k: trims[k] + h}), keys)):
            jac[:, j] = (ek - e) / h
        step = np.linalg.lstsq(jac, -e, rcond=None)[0]
        step *= min(1.0, 0.2 / max(1e-12, np.abs(step).max()))  # at most 0.2 of a turn
        for j, k in enumerate(keys):
            trims[k] = float(np.clip(trims[k] + step[j], 0.0, 1.0))
    pool.shutdown()
    cols.shutdown()
    return best[1]


def write(trims: dict) -> None:
    text = CIRCUIT.read_text(encoding="utf-8")
    for k in TRIMS:
        text, n = re.subn(rf"(\n  {k}: \{{value: )[^,]+", rf"\g<1>{trims[k]:.5f}", text)
        if n != 1:
            raise SystemExit(f"{k} not found once")
    CIRCUIT.write_text(text, encoding="utf-8")
    print(f"wrote {CIRCUIT.name}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()
    s = spec.load_circuit(CIRCUIT)
    start = {k: float(s.values[k]["value"]) for k in TRIMS}
    t0 = time.time()
    trims = trim(start)
    checks = {
        f"{name}": {"hz": (f := measure_hz(trims, n, r)), "cents": cents(f, target_hz(n, r))}
        for name, n, r in (("low A 2'", LOW_A, RANGE_2), ("high A 2'", HIGH_A, RANGE_2),
                           ("top C 2'", TOP_C, RANGE_2), ("low A 8'", LOW_A, RANGE_8),
                           ("low A 32'", LOW_A, 1))
    }  # fmt: skip
    summary = {"trims": trims, "checks": checks, "wall_s": time.time() - t0}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "trim.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    print(json.dumps(summary, indent=1))
    if args.write:
        write(trims)


if __name__ == "__main__":
    main()
