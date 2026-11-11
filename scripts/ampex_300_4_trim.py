"""The Ampex 300-4's trims on the deck itself (docs/PERIOD_GEAR_BACKLOG.md, PG1, MT5), into
config/ampex_300_4_trims.yaml (scripts/make_ampex_300_4.py reads them; rerun it after):

- `--coupling`: the record heads' coupling (MT3's record term). The fit puts the record
  side's crosstalk at 10 kHz at the mutual inductance's and the capacitance's terms together
  (reports/multitrack/crosstalk/fit.json, four tracks). Here the heads hang on the 351's
  6201 driver, a current source of ~11 kohm through 0.47 uF, so a mutual inductance couples
  little (k ~ 0.2 would be needed: not a shielded stack's); the coupling coefficient stays
  provisional (`k_rec_heads`) and the capacitance between neighbouring heads' hot ends
  (`c_rec_heads_f`) is sized so the record side's crosstalk at 10 kHz is the fit's: a 10 kHz
  tone into channel 1, 10 dB under 0 VU, the oscillator out (the audio's currents alone), the
  current in channel 2's head over channel 1's. Its slope in the circuit (the heads' voltage
  is mostly their resistance at audio: ~6 dB an octave) is reported at 2.5, 5 and 20 kHz.
- `--bias`: each channel's BIAS ADJUST, so its head's bias current is the deck channel's
  aligned one (scripts/align_300_4.py: reports/multitrack/deck/channel_alignment.json): the
  master oscillator drives four bias lines, and the heads' coupling carries a neighbour's
  bias too (inner heads two). The current goes nearly as BIAS ADJUST's capacitance (its
  reactance is far above the head's), but the master's amplitude falls as its four lines
  load it: a proportional pass, then secant passes, to within BIAS_TOL.

    uv run --extra fast python scripts/ampex_300_4_trim.py --coupling [--bias] [--write]
-> reports/multitrack/deck/trim.json
"""

from __future__ import annotations

import argparse
import json
import math
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import yaml

from varimu.circuit import spec
from varimu.config import CONFIG_DIR, REPO_ROOT
from varimu.measure import tape_align as ta

OUT = REPO_ROOT / "reports" / "multitrack" / "deck"
TRIMS = CONFIG_DIR / "ampex_300_4_trims.yaml"
FIT = REPO_ROOT / "reports" / "multitrack" / "crosstalk" / "fit.json"
CHANNEL_ALIGNMENT = OUT / "channel_alignment.json"
TAGS = ("", "_2", "_3", "_4")
#: The coupling's runs: short tones (the record side settles within the 1 s settle).
TONE_S = 0.06
FROM_S = 0.03
BIAS_PASSES = 6
BIAS_TOL = 3e-3


def run(b: ta.Bench, overrides: dict, x: np.ndarray, controls: dict | None = None) -> dict:
    from varimu.circuit import builder
    from varimu.sim import fast

    c = builder.build(b.circuit, overrides, cores="ja")
    ctl = {f"in{k}": np.zeros_like(x) for k in (2, 3, 4)} | (controls or {})
    return fast.run_transient(c.ir, x, settings=b.settings, controls=ctl).vectors


def head_current(b: ta.Bench, v: dict, tag: str, f_hz: float, r_ohm: float) -> float:
    i = (v[f"v(hra{tag})"] - v[f"v(rbc{tag})"]) / r_ohm
    return ta.level(ta.window(b, i, FROM_S), b.fs, f_hz)


def coupling(b: ta.Bench, p: dict, fit: dict) -> dict:
    """The capacitance between neighbouring heads for the fit's record-side crosstalk at
    10 kHz (with k_rec_heads as the circuit has it), and the slope that gives."""
    f4 = fit["four_track"]["params"]
    target = math.sqrt(f4["mutual_at_10k"] ** 2 + f4["capacitive_at_10k"] ** 2)
    k0, c0 = float(p["k_rec_heads"]), float(p["c_rec_heads_f"])
    freqs = (2500.0, 5000.0, 10000.0, 20000.0)
    r_ohm = float(p["rec_r_ohm"])
    jobs = []
    # One coupling at a time (the other negligible: the IR takes no zero capacitance).
    for k, c in ((k0, 1e-18), (1e-9, c0)):
        for f in freqs:
            o = {"oscillator": 0, "k_rec_heads": k, "c_rec_heads_f": c}
            jobs.append((o, ta.tone(b, [f], -10.0, TONE_S), f))
    with ThreadPoolExecutor(b.workers) as ex:
        runs = list(ex.map(lambda j: run(b, j[0], j[1]), jobs))
    ratio = []
    for (_, _, f), v in zip(jobs, runs, strict=True):
        i1 = head_current(b, v, "", f, r_ohm)
        i2 = head_current(b, v, "_2", f, r_ohm)
        ratio.append(i2 / i1)
    n = len(freqs)
    by_k = dict(zip(freqs, ratio[:n], strict=True))
    by_c = dict(zip(freqs, ratio[n:], strict=True))
    need_c = math.sqrt(max(target**2 - by_k[10000.0] ** 2, 0.0))
    c_trim = c0 * need_c / by_c[10000.0]
    return {
        "target_at_10k": target,
        "target_at_10k_db": 20 * math.log10(target),
        "k_rec_heads": k0,
        "mutual_db": {f"{f:g}": 20 * math.log10(r) for f, r in by_k.items()},
        "capacitance_db_at_c0": {f"{f:g}": 20 * math.log10(r) for f, r in by_c.items()},
        "c0_f": c0,
        "c_rec_heads_f": c_trim,
        "with_trim_db": {
            f"{f:g}": 10 * math.log10(by_k[f] ** 2 + (by_c[f] * c_trim / c0) ** 2) for f in freqs
        },
    }


def bias(b: ta.Bench, p: dict, start: dict, note=print) -> dict:
    al = json.loads(CHANNEL_ALIGNMENT.read_text(encoding="utf-8"))
    target = al["steps"]["bias"]["bias_ma_rms"] * 1e-3
    r_cal = float(p["r_bias_cal_ohm"])
    keys = ["bias_adjust_f"] + [f"bias_adjust_f{t}" for t in TAGS[1:]]
    o = dict(start)
    for k in keys:
        o.setdefault(k, float(p[k]))
    x = np.zeros(int(0.05 * b.fs))
    passes = []
    for i in range(BIAS_PASSES):
        v = run(b, o, x)
        got = [ta.bias_rms(ta.window(b, v[f"v(rbc{t})"], 0.01), b.fs, r_cal) for t in TAGS]
        passes.append({"bias_ma_rms": [g * 1e3 for g in got], "c_f": [o[k] for k in keys]})
        note(f"pass {i}: {[round(g * 1e3, 4) for g in got]} mA rms (target {target * 1e3:.4f})")
        if max(abs(g / target - 1.0) for g in got) < BIAS_TOL:
            break
        prev = passes[-2] if len(passes) > 1 else None
        for j, (k, g) in enumerate(zip(keys, got, strict=True)):
            if prev is None or g == prev["bias_ma_rms"][j] * 1e-3:
                o[k] = o[k] * target / g
            else:
                # Secant: the master's amplitude falls as its four lines load it.
                c0, i0 = prev["c_f"][j], prev["bias_ma_rms"][j] * 1e-3
                o[k] = o[k] + (target - g) * (o[k] - c0) / (g - i0)
    return {"target_ma_rms": target * 1e3, "passes": passes, **{k: o[k] for k in keys}}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--coupling", action="store_true")
    ap.add_argument("--bias", action="store_true")
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args()
    ta.CIRCUIT = "ampex_300_4"
    b = ta.Bench.load()
    p = spec.resolve(b.circuit)
    fit = json.loads(FIT.read_text(encoding="utf-8"))
    OUT.mkdir(parents=True, exist_ok=True)
    report_path = OUT / "trim.json"
    report = json.loads(report_path.read_text()) if report_path.exists() else {}
    trims = (yaml.safe_load(TRIMS.read_text(encoding="utf-8")) if TRIMS.exists() else {}) or {}
    if a.coupling:
        r = coupling(b, p, fit)
        report["coupling"] = r
        trims["k_rec_heads"] = r["k_rec_heads"]
        trims["c_rec_heads_f"] = r["c_rec_heads_f"]
        print(json.dumps(r, indent=1))
    if a.bias:
        start = {k: trims[k] for k in ("k_rec_heads", "c_rec_heads_f") if k in trims}
        r = bias(b, p, start)
        report["bias"] = r
        for k in ("bias_adjust_f", *(f"bias_adjust_f{t}" for t in TAGS[1:])):
            trims[k] = r[k]
    report_path.write_text(json.dumps(report, indent=1), encoding="utf-8")
    if a.write:
        TRIMS.write_text(
            "# Written by scripts/ampex_300_4_trim.py (its docstring); don't edit by hand.\n"
            + yaml.safe_dump({k: float(v) for k, v in trims.items()}, sort_keys=True),
            encoding="utf-8",
        )
        print(f"wrote {TRIMS}")


if __name__ == "__main__":
    main()
