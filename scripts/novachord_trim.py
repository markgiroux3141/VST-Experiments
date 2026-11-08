"""The Novachord's factory adjustments (docs/NOVACHORD_PLAN.md), the service manual's procedures
on the simulated instrument (2nd ed. pp.20-22), one note name's chain at a time:

  1. tuning: each oscillator's coil (the movable core) set so the note plays at equal
     temperament, A = 440 Hz (the oscillator at 1760 Hz), at production quality, and the
     vibrato's compensation CN31 set so the average pitch is the same with NORMAL VIBRATO
     on and off (p.21), within its printed range, the coil retuned after it (the notes in
     parallel; `--tuning-only` keeps the dividers' trims);
  2. dividers, top to bottom (channel 5, then 4 ... 1): the adjustment resistor RN13 swept
     over the manual's table (1.2 to 3.5 MEG) and the divider classified at each value: OK
     (divides by two), HIGH (doesn't divide: "plays an octave high") or LOW (a sub-octave:
     "plays an octave low"); RN13 set at the middle (geometric) of its OK range, so the
     divider sits "in the center of its range of correct division" (p.20).

    uv run --extra fast python scripts/novachord_trim.py [--notes A C ...] [--write]

--write saves config/novachord_trims.yaml (the generator, scripts/make_novachord.py, reads it;
rerun that afterwards). Without it the results are printed only. Divider classification runs at
draft quality (the circuit's time constants, not the engine's accuracy, set the range).
"""

from __future__ import annotations

import argparse
import dataclasses
import importlib.util
import json
import math
import sys
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import yaml

from varimu.circuit import builder, spec
from varimu.circuit.ir import VoltageProbe
from varimu.config import REPO_ROOT
from varimu.sim import fast, io

FS = 96000
CACHE = REPO_ROOT / "cache" / "novachord"
RN13_TABLE = (
    0.4e6,
    0.6e6,
    0.85e6,
    1.2e6,
    1.5e6,
    1.7e6,
    2.0e6,
    2.5e6,
    3.0e6,
    3.5e6,
)  # SM2 p.20: 1.2-3.5 MEG, extended down to find the range's edge
SUB_DB = -30.0  # a sub-octave component above this: LOW
FUND_DB = -30.0  # the divided fundamental below this: HIGH (no division)
TUNE_S, DIVIDE_S = 0.25, 0.45
THREADS = 7


def _maker():
    sp = importlib.util.spec_from_file_location(
        "make_novachord", REPO_ROOT / "scripts" / "make_novachord.py"
    )
    m = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(m)
    return m


MK = _maker()


def note_spec(note: int, trims: dict) -> spec.CircuitSpec:
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / f"trim_note_{note}.yaml"
    text = MK.build_note(note, trims)
    if not path.exists() or path.read_text(encoding="utf-8") != text:
        path.write_text(text, encoding="utf-8")
    return spec.load_circuit(path)


def render(
    s: spec.CircuitSpec, note: int, sets: dict, probes: list[str], dur_s: float, quality: str
) -> dict:
    ir = builder.build_ir(s, spec.resolve(s, sets))
    ir = dataclasses.replace(ir, probes=tuple(VoltageProbe(p) for p in probes))
    st = dataclasses.replace(
        io.TransientSettings.from_sim_settings(engine="circuitsim", quality=quality),
        full_scale_volts_peak=1.0,
    )
    n = int(dur_s * FS)
    ctl = {k: np.zeros(n) for k in dict(s.cv_inputs)}
    v = fast.run_transient(ir, np.zeros(n), settings=st, controls=ctl).vectors
    return {p: np.asarray(v[f"v({p})"]) for p in probes}


def frequency(x: np.ndarray, skip_s: float = 0.08) -> float:
    """The mean frequency over the run after `skip_s`: rising crossings of the mean,
    interpolated."""
    y = x[int(skip_s * FS) :]
    y = y - y.mean()
    i = np.flatnonzero((y[:-1] < 0) & (y[1:] >= 0))
    t = i + (-y[i]) / (y[i + 1] - y[i])
    return float((len(t) - 1) / ((t[-1] - t[0]) / FS))


def levels(x: np.ndarray, f_hz: float, skip_s: float = 0.15) -> tuple[float, float, float]:
    """(sub-octave, fundamental, input) levels in dB re the strongest of the three: at f / 2,
    f and 2 f."""
    y = x[int(skip_s * FS) :]
    y = (y - y.mean()) * np.hanning(len(y))
    sp = np.abs(np.fft.rfft(y))
    fr = np.fft.rfftfreq(len(y), 1 / FS)

    bin_hz = fr[1]

    def at(f):
        half = max(0.06 * f, 2.0 * bin_hz)
        m = (fr > f - half) & (fr < f + half)
        return float(sp[m].max())

    a = [at(f_hz / 2), at(f_hz), at(2 * f_hz)]
    top = max(a)
    return tuple(20 * math.log10(v / top) for v in a)


def classify(x: np.ndarray, f_out: float) -> tuple[str, list[float]]:
    sub, fund, inp = levels(x, f_out)
    if fund < FUND_DB:
        return "HIGH", [sub, fund, inp]
    if sub > SUB_DB:
        return "LOW", [sub, fund, inp]
    return "OK", [sub, fund, inp]


def longest_run(values: list[float], good: list[bool]) -> list[float]:
    """The longest stretch of consecutive good values (the first if tied): a divider's range
    of correct division, whose middle the trim takes (an isolated good value inside a bad
    stretch is no range)."""
    best: list[float] = []
    run: list[float] = []
    for v, g in zip(values, good, strict=True):
        run = run + [v] if g else []
        if len(run) > len(best):
            best = run
    return best


def tune(note: int, trims: dict) -> float:
    n = MK.NAMES[note].replace("#", "s")
    target = MK.key_hz(61 + note)
    scale = trims.get(n, {}).get("coil_scale", 1.0)
    for _ in range(3):
        t = dict(trims)
        t[n] = dict(trims.get(n, {}), coil_scale=scale)
        s = note_spec(note, t)
        f = frequency(
            render(s, note, {}, [f"{n.lower()}o_top"], TUNE_S, "production")[f"{n.lower()}o_top"]
        )
        cents = 1200 * math.log2(f / target)
        print(f"  {n}: oscillator {f:.3f} Hz ({cents:+.2f} c) at coil x{scale:.5f}", flush=True)
        if abs(cents) < 0.3:
            break
        scale *= (f / target) ** 2
    return scale


CN31_RANGE = (0.005e-6, 0.012e-6)  # SM2 Fig. 15
VIB_S = 1.4  # long enough to average the vibrato over several reed cycles


def mean_pitch_c(note: int, trims: dict, sets: dict) -> float:
    """The oscillator's mean pitch in cents from equal temperament over the run's second half
    (production quality)."""
    n = MK.NAMES[note].replace("#", "s")
    target = MK.key_hz(61 + note)
    s = note_spec(note, trims)
    x = render(s, note, sets, [f"{n.lower()}o_top"], VIB_S, "production")[f"{n.lower()}o_top"]
    return 1200 * math.log2(frequency(x, skip_s=VIB_S / 2) / target)


def compensate(note: int, trims: dict) -> dict:
    """The manual's tuning check (SM2 p.21: 'The average pitch, with and without vibrato,
    should be the same'): CN31 (the compensation, in circuit with NORMAL VIBRATO off) set so
    the mean pitch with NORMAL on matches the tuned pitch with it off (within the printed
    range), the coil retuned after each change. Returns the note's trims."""
    n = MK.NAMES[note].replace("#", "s")
    t = dict(trims)
    t[n] = dict(trims.get(n, {}))
    f = MK.key_hz(61 + note)
    cb = 1.1 * MK.by_period(0.01e-6, 0.02e-6, f, MK.key_hz(61), MK.key_hz(72))  # CN12 + CN11
    r = 0.31**2  # CN31's tap, reflected to the coil's top
    cn31 = t[n].get("cn31_f", math.sqrt(CN31_RANGE[0] * CN31_RANGE[1]))
    for _ in range(3):
        t[n]["cn31_f"] = cn31
        t[n]["coil_scale"] = tune(note, t)
        c_on = mean_pitch_c(note, t, {"normal_vibrato": 1})
        print(f"  {n}: CN31 {cn31 * 1e6:.4f} uF: NORMAL vibrato's mean {c_on:+.2f} c", flush=True)
        if abs(c_on) < 0.5:
            break
        # tuned off: Cb + CN31 r; on: Cb + M. cents_on = 600 log2((Cb + CN31 r) / (Cb + M))
        m = (cb + cn31 * r) * 2 ** (-c_on / 600.0) - cb
        new = min(max(m / r, CN31_RANGE[0]), CN31_RANGE[1])
        if new == cn31:
            print(f"  {n}: CN31 at the printed range's end", flush=True)
            break
        cn31 = new
    t[n]["cn31_f"] = cn31
    t[n]["coil_scale"] = tune(note, t)
    return t[n]


def trim_dividers(note: int, trims: dict) -> dict:
    n = MK.NAMES[note].replace("#", "s")
    out = {}
    s = note_spec(note, trims)
    for ch in range(5, 0, -1):
        f_out = MK.key_hz(1 + (ch - 1) * 12 + note)
        probe = f"{n.lower()}d{ch}_k"
        key = f"{n.lower()}_d{ch}_rn13_ohm"
        lower = {f"{n.lower()}_d{c}_rn13_ohm": out[c] for c in out}

        def one(r, lower=lower, probe=probe, key=key, f_out=f_out):
            dur = max(DIVIDE_S, 0.15 + 24.0 / f_out)  # ~12 cycles of the sub-octave
            v = render(s, note, lower | {key: r}, [probe], dur, "draft")[probe]
            return r, classify(v, f_out)

        with ThreadPoolExecutor(THREADS) as ex:
            res = list(ex.map(one, RN13_TABLE))
        ok = longest_run([r for r, (c, _) in res], [c == "OK" for _, (c, _) in res])
        row = " ".join(f"{r / 1e6:.1f}M:{c}" for r, (c, _) in res)
        best = math.sqrt(ok[0] * ok[-1]) if ok else 2.0e6
        print(f"  {n} channel {ch} ({f_out:.1f} Hz): {row} -> {best / 1e6:.2f} MEG", flush=True)
        out[ch] = best if ok else None
        if not ok:
            out[ch] = 2.0e6
            out[f"{ch}_failed"] = True
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--notes", nargs="*", default=list(MK.NAMES))
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--skip-tuning", action="store_true")
    ap.add_argument("--keep-tuned", action="store_true", help="don't retune a note already tuned")
    ap.add_argument(
        "--tuning-only",
        action="store_true",
        help="tune and compensate only (keep the dividers' trims)",
    )
    args = ap.parse_args()
    existing = MK.load_trims()
    trims = dict(existing)
    report = {}
    notes = [MK.NAMES.index(nm.replace("s", "#") if len(nm) == 2 else nm) for nm in args.notes]
    if not args.skip_tuning:
        # tuning and the vibrato's compensation, the notes in parallel (single-threaded runs)
        todo = [
            nt
            for nt in notes
            if not (
                args.keep_tuned and "coil_scale" in trims.get(MK.NAMES[nt].replace("#", "s"), {})
            )
        ]
        with ThreadPoolExecutor(THREADS) as ex:
            for nt, tr in zip(todo, ex.map(lambda nt: compensate(nt, trims), todo), strict=True):
                trims[MK.NAMES[nt].replace("#", "s")] = tr
    for note in notes:
        n = MK.NAMES[note].replace("#", "s")
        print(f"note {n}", flush=True)
        if args.tuning_only:
            continue
        div = trim_dividers(note, trims)
        failed = [ch for ch in range(1, 6) if div.get(f"{ch}_failed")]
        trims[n] = dict(trims.get(n, {})) | {
            f"d{ch}_rn13_ohm": float(div[ch]) for ch in range(1, 6)
        }
        report[n] = {"failed_channels": failed}
    print(json.dumps(report))
    if args.write:
        body = {
            "source": "scripts/novachord_trim.py: the service manual's tuning (pp.21-22) and "
            "divider adjustment (pp.20-21) on the simulated instrument; regenerate with --write, "
            "then scripts/make_novachord.py",
            "notes": trims,
        }
        MK.TRIMS.write_text(yaml.safe_dump(body, sort_keys=False, width=100), encoding="utf-8")
        print(f"wrote {MK.TRIMS}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
