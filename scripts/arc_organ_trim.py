"""The Arc Organ's factory trim (docs/INVENTED_LIVE_PLAN.md IL7): each key's condenser on
config/circuits/arc_organ.yaml at the panel's defaults, so the key sounds its note.

The arc pulls the tank flat (its resistance and the time its conductance takes to follow:
~7 % at A4, more in the bass), so a key's condenser is found on the circuit itself: a note
held with the gate down, its pitch measured over the steady part, the condenser corrected
(f goes about as C^-1/2) until it is within 0.5 cent.

    uv run --extra fast python scripts/arc_organ_trim.py --survey      # f0 against C
    uv run --extra fast python scripts/arc_organ_trim.py [--write]     # trim the compass
    uv run --extra fast python scripts/arc_organ_trim.py --check       # exit 1 when stale

--write saves config/arc_organ_trims.yaml (the record: each key's condenser, its pitch
before and after) and crates/varimu-app/src/arc_organ_trims.rs (the app's table, the
Performer's keyed value). Their key is a hash of the circuit file: --check says when a
change to it calls for a new trim.
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import math
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from varimu.circuit import builder, spec  # noqa: E402
from varimu.sim import fast, io  # noqa: E402

CIRCUIT = "arc_organ"
# The compass (decided, the plan's IL7): E2-C6, where the pitch follows the condenser (--survey:
# monotonic from 600 uF, 73.5 Hz, to 2.5 uF, 1521 Hz; at 1.8 uF and less the arc no longer sings,
# its rms 27 dB down).
FIRST_NOTE = 40
LAST_NOTE = 84
TRIMS = ROOT / "config" / "arc_organ_trims.yaml"
RUST = ROOT / "crates" / "varimu-app" / "src" / "arc_organ_trims.rs"
TANK_H = 4.0e-3
ON_S, HOLD_S = 0.05, 1.5
STEADY_S = 1.2  # the pitch over the hold's last this-many seconds (the hiss wanders a bass
# note's pitch ~+-25 cents over a third of a second)
TOL_CENTS = 0.5
# The arc's pull, f / f_LC against the condenser (--survey, 2026-11-21): the first guess.
PULL = [
    (3e-6, 0.956),
    (10e-6, 0.955),
    (30e-6, 0.939),
    (70e-6, 0.913),
    (165e-6, 0.853),
    (290e-6, 0.793),
    (600e-6, 0.716),
]


def note_hz(m: int) -> float:
    return 440.0 * 2.0 ** ((m - 69) / 12)


def circuit_key() -> str:
    """The circuit file's hash without its `key_f` line (the resting condenser, A4's trim),
    its output full scale or comments; line endings normalized."""
    lines = spec.circuit_path(CIRCUIT).read_text(encoding="utf-8").splitlines()
    skip = ("key_f:", "#", "output_volts_peak:")
    kept = [ln for ln in lines if not ln.lstrip().startswith(skip)]
    return hashlib.sha256("\n".join(kept).encode()).hexdigest()[:16]


def _settings():
    st = io.TransientSettings.from_sim_settings(engine="circuitsim", quality="draft")
    return dataclasses.replace(st, full_scale_volts_peak=1.0, settle_s=0.0)


def f0(x: np.ndarray, fs: float, band: tuple[float, float] = (40.0, 20e3)) -> float:
    """The strongest spectral peak in `band` (Hz), refined by a parabola on log magnitude."""
    w = np.hanning(x.size)
    sp = np.abs(np.fft.rfft(x * w, 8 * x.size)) + 1e-30
    fr = np.fft.rfftfreq(8 * x.size, 1 / fs)
    lo, hi = np.searchsorted(fr, band[0]), np.searchsorted(fr, band[1])
    k = lo + int(np.argmax(sp[lo:hi]))
    y0, y1, y2 = np.log(sp[k - 1 : k + 2])
    return float(fr[k] + (y0 - y2) / (2 * (y0 - 2 * y1 + y2)) * (fr[1] - fr[0]))


def sing(
    c_f: float, values: dict | None = None, hold_s: float = HOLD_S
) -> tuple[np.ndarray, float]:
    """The pressure with key_f = c_f held from ON_S for hold_s (the panel's defaults), and
    the rate."""
    sp = spec.load_circuit(spec.circuit_path(CIRCUIT))
    ir = builder.build_ir(sp, spec.resolve(sp, {"key_f": c_f, **(values or {})}))
    st = _settings()
    fs = st.sample_rate
    n = int((ON_S + hold_s) * fs)
    gate = np.zeros(n)
    gate[int(ON_S * fs) :] = 10.0
    v = fast.run_transient(ir, np.zeros(n), settings=st, controls={"gate": gate}).vectors
    return np.asarray(v["v(out)"]), fs


def measure(
    c_f: float, values: dict | None = None, near_hz: float | None = None
) -> tuple[float, float, float]:
    """(f0 over the steady part, f0 over its first half / second half's ratio in cents, rms).
    `near_hz`: the fundamental is looked for within 0.5-1.4x of it (else above 40 Hz)."""
    out, fs = sing(c_f, values)
    seg = out[-int(STEADY_S * fs) :]
    band = (0.5 * near_hz, 1.4 * near_hz) if near_hz else (40.0, 20e3)
    h = seg.size // 2
    a, b = f0(seg[:h], fs, band), f0(seg[h:], fs, band)
    return f0(seg, fs, band), 1200 * math.log2(b / a), float(np.sqrt(np.mean(seg**2)))


def first_guess(hz: float) -> float:
    """The condenser for hz on the survey's pull: f = pull(C) / (2 pi sqrt(L C))."""
    c = 1 / ((2 * math.pi * hz) ** 2 * TANK_H)
    for _ in range(20):
        lc = np.log([p[0] for p in PULL])
        pull = float(np.interp(math.log(c), lc, [p[1] for p in PULL]))
        c = pull**2 / ((2 * math.pi * hz) ** 2 * TANK_H)
    return c


def survey() -> None:
    cs = np.geomspace(3e-6, 800e-6, 40)
    with ThreadPoolExecutor(8) as ex:
        rows = list(ex.map(measure, cs))
    for c, (f, drift, rms) in zip(cs, rows, strict=True):
        lc = 1 / (2 * math.pi * math.sqrt(TANK_H * c))
        print(
            f"C {c * 1e6:8.2f} uF  LC {lc:7.1f} Hz  f0 {f:7.1f} Hz ({f / lc:5.3f})  "
            f"halves {drift:+6.1f} c  rms {rms:.3f} Pa"
        )


def trim_key(m: int) -> dict:
    hz = note_hz(m)
    c = first_guess(hz)
    f, drift, rms = measure(c, near_hz=hz)
    first = f
    best = (abs(1200 * math.log2(f / hz)), c, f, drift, rms)
    for _ in range(8):
        if best[0] < TOL_CENTS:
            break
        c *= (f / hz) ** 2
        f, drift, rms = measure(c, near_hz=hz)
        best = min(best, (abs(1200 * math.log2(f / hz)), c, f, drift, rms))
    _, c, f, drift, rms = best
    return {
        "note": m,
        "hz": round(hz, 4),
        "key_f": float(f"{c:.6e}"),
        "untrimmed_cents": round(1200 * math.log2(first / hz), 1),
        "cents": round(1200 * math.log2(f / hz), 2),
        "halves_cents": round(drift, 2),
        "rms_pa": round(rms, 4),
    }


def write(rows: list[dict]) -> None:
    key = circuit_key()
    TRIMS.write_text(
        "# GENERATED by scripts/arc_organ_trim.py --write: don't edit by hand.\n"
        "# The Arc Organ's factory trim (docs/INVENTED_LIVE_PLAN.md IL7): each key's condenser\n"
        "# (key_f) on config/circuits/arc_organ.yaml at the panel's defaults, its pitch before\n"
        "# (the survey's pull curve, PULL) and after, the steady part's halves.\n"
        + yaml.safe_dump({"circuit_sha256_16": key, "keys": rows}, sort_keys=False),
        encoding="utf-8",
    )
    table = ",\n".join(f"    {r['key_f']:.6e}" for r in rows)
    RUST.write_text(
        "//! GENERATED by scripts/arc_organ_trim.py --write: don't edit by hand.\n"
        "//! The Arc Organ's factory trim (docs/INVENTED_LIVE_PLAN.md IL7): each key's\n"
        "//! condenser (farads) on config/circuits/arc_organ.yaml, from\n"
        f"//! [`ARC_ORGAN_FIRST_NOTE`] up (circuit sha256 {key}...).\n\n"
        "/// The compass's lowest key (MIDI).\n"
        f"pub const ARC_ORGAN_FIRST_NOTE: u8 = {FIRST_NOTE};\n\n"
        f"/// Each key's condenser, from [`ARC_ORGAN_FIRST_NOTE`] up.\n"
        f"pub const ARC_ORGAN_CONDENSERS: &[f64] = &[\n{table},\n];\n",
        encoding="utf-8",
    )
    print(f"wrote {TRIMS.relative_to(ROOT)} and {RUST.relative_to(ROOT)}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--survey", action="store_true")
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    if a.check:
        saved = yaml.safe_load(TRIMS.read_text(encoding="utf-8")) if TRIMS.exists() else {}
        if saved.get("circuit_sha256_16") != circuit_key():
            print("stale: run scripts/arc_organ_trim.py --write")
            sys.exit(1)
        print("current")
        return
    if a.survey:
        survey()
        return
    with ThreadPoolExecutor(8) as ex:
        rows = list(ex.map(trim_key, range(FIRST_NOTE, LAST_NOTE + 1)))
    for r in rows:
        print(
            f"{r['note']:3d} {r['hz']:8.2f} Hz  key_f {r['key_f'] * 1e6:8.3f} uF  "
            f"untrimmed {r['untrimmed_cents']:+7.1f} c  now {r['cents']:+5.2f} c  "
            f"halves {r['halves_cents']:+5.2f} c  rms {r['rms_pa']:.3f} Pa"
        )
    if a.write:
        write(rows)


if __name__ == "__main__":
    main()
