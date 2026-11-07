"""The Minimoog VCF's factory trims by Folkman's adjustment procedures (the Model D technical
service manual, p. 14; data/schematics/minimoog/README.md), in his order:

1. Regeneration Cal.: CUTOFF -1, EMPHASIS 7.5, rotate the Regeneration Cal. trimpot (R73) until
   regeneration starts.
2. Filter Range: KEYBOARD CONTROL 1 and 2 off, CUTOFF -1, EMPHASIS 10: the Range trimpot (R39)
   for zero beats with the A-440.
3. Filter Scale: CUTOFF -1, EMPHASIS 10, keyboard control on; the third "A" key from the bottom:
   CUTOFF for zero beats two octaves above 440 (1760 Hz); the low "A" key: the Scale trimpot
   (R49) for zero beats (440 Hz). Repeat until it tracks three octaves.

CUTOFF -1 is the fixture's 0 V (config/circuits/minimoog_filter_board.yaml); the A keys' volts are
the keyboard string's (the circuit file's key_* values: the low A MIDI 45, the third A MIDI 69).

    uv run --extra fast python scripts/minimoog_vcf_trim.py [--write] [--scale-only]

--write puts the three trims into the circuit file's control defaults; --scale-only keeps the file's
REGEN CAL and RANGE and runs procedure 3 (the one that reads the keyboard's volts)."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import minimoog_vcf_study as st  # noqa: E402

DUR_S = 0.6
A_HZ = 440.0
LOW_A, THIRD_A = 45, 69


def key_volts(s, note: int) -> float:
    """The keyboard string's volts at MIDI `note` (the circuit file's key_* values, as the
    app's)."""
    v = lambda k: float(s.values[f"key_{k}"]["value"])  # noqa: E731
    return float(np.clip((note - v("ref_note")) * v("v_per_semitone"), v("min_v"), v("max_v")))


def envelope_growth(s, ov: dict, key_v: float = 0.0) -> tuple[float, float, float]:
    """(end / middle peak-to-peak, end pp, frequency) after a small kick: > 1 grows."""
    v = st.run(st.build(s, ov), st.kick(DUR_S, 0.005), key_v=key_v)[st.VCF]
    mid = v[int(0.15 * st.FS) : int(0.25 * st.FS)]
    end = v[-int(0.1 * st.FS) :]
    pp_mid, pp_end = float(np.ptp(mid)), float(np.ptp(end))
    _, f = st.ring(v)
    return pp_end / max(pp_mid, 1e-12), pp_end, f


def bisect(fn, lo: float, hi: float, steps: int = 9) -> float:
    """x in [lo, hi] where fn(x) changes sign (fn(lo), fn(hi) of opposite signs)."""
    flo = fn(lo)
    for _ in range(steps):
        mid = 0.5 * (lo + hi)
        fm = fn(mid)
        if (fm > 0) == (flo > 0):
            lo, flo = mid, fm
        else:
            hi = mid
    return 0.5 * (lo + hi)


def freq(s, ov: dict, key_v: float = 0.0) -> float:
    _, _, f = envelope_growth(s, {**ov, "emphasis": 1.0}, key_v)
    return f


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--scale-only", action="store_true")
    a = ap.parse_args(argv)
    s = st.load()
    ov = {"cutoff_v": 0.0, "kb1": 1, "kb2": 1}

    # 1. regeneration starts at EMPHASIS 7.5
    def regen(r):
        g, pp, f = envelope_growth(s, {**ov, "emphasis": 0.75, "regen_cal": r})
        print(f"  regen_cal {r:.4f}: growth {g:.3f} (f {f:.0f} Hz)", flush=True)
        # an oscillation already saturated by the middle window has growth 1: it counts as onset
        return np.log(g) + (1.0 if pp > 0.05 else 0.0)

    # 2. range: keyboard off, EMPHASIS 10 at 440 Hz. Below ~0.1 the reference current is
    # nearly nothing (the wiper under Q26's emitter) and the ladder stops tracking: the
    # search stays in the trim's working span.
    def rng(x):
        f = freq(s, {**ov, "kb1": 0, "kb2": 0, "range_trim": x})
        print(f"  range_trim {x:.4f}: {f:.1f} Hz", flush=True)
        return np.log(max(f, 1e-3) / A_HZ)

    # The onset of regeneration depends on the frequency, so 1 and 2 alternate twice
    # (the procedure's "repeat" in practice).
    ctl = lambda k: float(s.controls[k]["value"])  # noqa: E731
    regen_cal, range_trim = ctl("regen_cal"), ctl("range_trim")
    ov["regen_cal"], ov["range_trim"] = regen_cal, range_trim
    for _ in range(0 if a.scale_only else 2):
        g0, g1 = regen(0.0), regen(1.0)
        if (g0 > 0) == (g1 > 0):
            print("REGEN CAL: no onset at EMPHASIS 7.5 within the trim's range", flush=True)
            regen_cal = 0.0 if g0 > g1 else 1.0
        else:
            regen_cal = bisect(regen, 0.0, 1.0)
        ov["regen_cal"] = regen_cal
        range_trim = bisect(rng, 0.1, 1.0)
        ov["range_trim"] = range_trim

    # 3. scale. Folkman's loop (CUTOFF for 1760 Hz at the third A, SCALE for 440 Hz at the
    # low A, repeated) ends where the third A sounds two octaves over the low A and the low
    # A at 440 Hz. It is solved for that end state directly: SCALE for a ratio of 4 between
    # the two A keys (their string volts), then CUTOFF for 440 Hz at the low A.
    ka, kc = key_volts(s, LOW_A), key_volts(s, THIRD_A)

    def ratio(x):
        o = {**ov, "scale_trim": x}
        f0, f2 = freq(s, o, key_v=ka), freq(s, o, key_v=kc)
        print(f"  scale_trim {x:.4f}: {f0:.1f} -> {f2:.1f} Hz ({f2 / max(f0, 1e-3):.3f}x)")
        return np.log(max(f2, 1e-3) / max(f0, 1e-3) / 4.0)

    scale = bisect(ratio, 0.0, 1.0, 9)
    ov["scale_trim"] = scale

    def cutf(c):
        f = freq(s, {**ov, "cutoff_v": c}, key_v=ka)
        print(f"  cutoff_v {c:+.4f} @ the low A: {f:.1f} Hz", flush=True)
        return np.log(max(f, 1e-3) / A_HZ)

    cut = bisect(cutf, -1.0, 1.0, 9)

    # the result: tracking over three octaves at the trimmed scale (the four A keys)
    track = [freq(s, {**ov, "cutoff_v": cut}, key_v=key_volts(s, LOW_A + 12 * i)) for i in range(4)]
    out = {
        "regen_cal": regen_cal,
        "range_trim": range_trim,
        "scale_trim": scale,
        "cutoff_v_at_scale": cut,
        "tracking_hz": track,
        "octaves_per_keyboard_octave": np.diff(np.log2(track)).tolist(),
    }
    print(json.dumps(out, indent=1))
    st.OUT.mkdir(parents=True, exist_ok=True)
    (st.OUT / "trim.json").write_text(json.dumps(out, indent=1))
    if a.write:
        text = st.CIRCUIT.read_text()
        for key in ("scale_trim",) if a.scale_only else ("regen_cal", "range_trim", "scale_trim"):
            text, n = re.subn(
                rf"(\n  {key}: \{{value: )[0-9.eE+-]+", rf"\g<1>{out[key]:.4f}", text, count=1
            )
            assert n == 1, key
        st.CIRCUIT.write_text(text)
        print(f"wrote the trims into {st.CIRCUIT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
