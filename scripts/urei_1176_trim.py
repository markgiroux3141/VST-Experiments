"""The 1176's factory trims (config/circuits/urei_1176.yaml, scripts/make_urei_1176.py), run
the way the factory ran them, on the nominal unit, in this order:

    uv run --extra fast python scripts/urei_1176_trim.py [--write]

1. GAIN: T2's feedback winding (a provisional design value) for the manual's 45 dB (ua:
   p. 1): INPUT and OUTPUT fully CW, gain reduction disabled, Q bias fully CCW, 1 kHz at
   -50 dBu at the input terminals, out across 600 ohm.
2. R83 and Q BIAS: the manual's procedure (ua: p. 5; R59 "sets the compression
   threshold"): 4:1, ATTACK and RELEASE mid, a 1 kHz sine at +4 dBu in, INPUT at
   QB_INPUT_ATTEN_DB and OUTPUT turned for +4 dBm out (0 dB on the +4 meter: the two
   split the 45 dB equally, the panel's matched unity setting; the manual doesn't say how
   they share it) with R59 fully CCW, then R59 turned CW until the output is 1.0 dB lower
   (bisection). R83, Figure 5's "T&C" in series with R59, is the E24 value (or a jumper)
   whose 1-dB setting lies nearest R59's mid-rotation (the factory's choice of a resistor
   that centres the trim on the unit's FET).
3. R86 (the LN circuit's distortion null): the least THD at 10 dB of gain reduction, 1
   kHz, 4:1, ATTACK mid, RELEASE slowest, INPUT fully CW, OUTPUT at R86_OUTPUT (the line
   amp clean: the side chain listens ahead of OUTPUT, and fully CW the output would clip
   at the +24 dBm 10 dB of gain reduction takes), by a sweep of R86 and a parabola through
   the best three.

Renders: the draft with Newton at 1e-5 (the SSL compressor's finding: the draft's 1e-3
distorts precise circuits). --write puts the results into the generator's constants and
regenerates the circuit file.
"""

from __future__ import annotations

import argparse
import copy
import dataclasses
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from varimu.circuit import builder  # noqa: E402
from varimu.circuit.spec import load_circuit, resolve  # noqa: E402

GEN = ROOT / "scripts" / "make_urei_1176.py"
CIRCUIT = ROOT / "config" / "circuits" / "urei_1176.yaml"
FS = 96000.0
DBU_PEAK_V = 0.775 * np.sqrt(2)
E24 = [1.0, 1.1, 1.2, 1.3, 1.5, 1.6, 1.8, 2.0, 2.2, 2.4, 2.7, 3.0, 3.3, 3.6, 3.9, 4.3, 4.7,
       5.1, 5.6, 6.2, 6.8, 7.5, 8.2, 9.1]  # fmt: skip
OPEN = dict(input_atten_db=0.0, output=1.0, attack_off=1, q_bias=0.0)
QB_INPUT_ATTEN_DB = 22.5
R86_OUTPUT = 0.45  # the line amp clean at 10 dB of GR (the side chain is ahead of OUTPUT)
QB_PANEL = dict(input_atten_db=QB_INPUT_ATTEN_DB, attack_off=0, ratio=4, attack=0.5,
                release=0.5)  # fmt: skip
POOL = 6


def settings():
    from varimu.sim import io

    st = io.TransientSettings.from_sim_settings(engine="circuitsim", quality="draft")
    return dataclasses.replace(st, newton_reltol=1e-5, newton_vntol=1e-5)


def render(spec, x: np.ndarray, **controls) -> np.ndarray:
    from varimu.sim import fast

    q = dict(resolve(spec))
    q.update(controls)
    c = builder.build(spec, q)
    return np.asarray(fast.run_transient(c.ir, x, settings=settings()).vectors["v(out)"])


def tone(level_dbu: float, dur_s: float, f_hz: float = 1000.0) -> np.ndarray:
    t = np.arange(int(FS * dur_s)) / FS
    return (
        DBU_PEAK_V * 10 ** (level_dbu / 20) * np.sin(2 * np.pi * f_hz * t) * np.clip(t / 0.01, 0, 1)
    )


def level_dbu(y: np.ndarray, f_hz: float = 1000.0, frac: float = 0.5) -> float:
    y = y[int(frac * len(y)) :]
    t = np.arange(len(y)) / FS
    return 20 * np.log10(2 * abs(np.mean(y * np.exp(-2j * np.pi * f_hz * t))) / DBU_PEAK_V)


def thd(y: np.ndarray, f_hz: float = 1000.0, frac: float = 0.6, nh: int = 10) -> float:
    y = y[int(frac * len(y)) :]
    t = np.arange(len(y)) / FS
    w = np.hanning(len(y))
    h = [abs(np.sum(w * y * np.exp(-2j * np.pi * k * f_hz * t))) for k in range(1, nh + 1)]
    return float(np.sqrt(sum(x * x for x in h[1:])) / h[0])


def spec_with(**values):
    """The circuit spec with some `values` entries replaced (the generator's constants)."""
    spec = copy.deepcopy(load_circuit(CIRCUIT))
    for k, x in values.items():
        spec.values[k] = {**spec.values[k], "value": x}
    return spec


def pmap(f, xs):
    with ThreadPoolExecutor(max_workers=POOL) as ex:
        return list(ex.map(f, xs))


def e24(lo: float, hi: float) -> list[float]:
    return [m * 10**d for d in range(2, 6) for m in E24 if lo <= m * 10**d <= hi]


def trim_gain(fb_ratio: float, **fixed) -> tuple[float, float]:
    x = tone(-50.0, 0.25)

    def gain(r):
        return level_dbu(render(spec_with(t2_fb_ratio=r, **fixed), x, **OPEN)) + 50.0

    # A secant on (log ratio, dB): the loop gain is finite, so the gain isn't 1 / ratio.
    r0, g0 = fb_ratio, gain(fb_ratio)
    r1 = r0 * 10 ** ((g0 - 45.0) / 20)
    g1 = gain(r1)
    for _ in range(8):
        if abs(g1 - 45.0) < 0.005:
            break
        s = (g1 - g0) / np.log(r1 / r0)
        r0, g0, r1 = r1, g1, r1 * np.exp((45.0 - g1) / s)
        g1 = gain(r1)
    return float(r1), g1


def q_bias_1db(spec) -> float:
    """The manual's procedure: R59's setting."""
    x = tone(4.0, 0.6)
    lo, hi = 0.0, 1.0  # OUTPUT for +4 dBm out at R59 CCW
    for _ in range(14):
        mid = 0.5 * (lo + hi)
        o = level_dbu(render(spec, x, **dict(QB_PANEL, q_bias=0.0, output=mid)), frac=0.6)
        lo, hi = (mid, hi) if o < 4.0 else (lo, mid)
    ccw = dict(QB_PANEL, q_bias=0.0, output=0.5 * (lo + hi))
    ref = level_dbu(render(spec, x, **ccw), frac=0.6)
    lo, hi = 0.0, 1.0
    for _ in range(14):
        mid = 0.5 * (lo + hi)
        drop = ref - level_dbu(render(spec, x, **dict(ccw, q_bias=mid)), frac=0.6)
        lo, hi = (mid, hi) if drop < 1.0 else (lo, mid)
    return 0.5 * (lo + hi)


def trim_r83(**fixed) -> tuple[float, float, list]:
    cands = [0.0] + e24(100.0, 4300.0)
    rows = pmap(lambda r: (r, q_bias_1db(spec_with(r83_ohm=max(r, 1e-3), **fixed))), cands)
    best = min(rows, key=lambda rq: abs(rq[1] - 0.5))
    return best[0], best[1], rows


def trim_r86(q_bias: float, **fixed) -> tuple[float, list]:
    spec = spec_with(**fixed)
    ctl = dict(input_atten_db=0.0, output=R86_OUTPUT, attack_off=0, q_bias=q_bias, ratio=4,
               attack=0.5, release=0.0)  # fmt: skip
    # The input for 10 dB of gain reduction at R86's middle: the gain below threshold,
    # then the level stepped up until the output falls 10 dB short of it.
    g0 = level_dbu(render(spec, tone(-70.0, 0.3), **ctl)) + 70.0
    lvl = -30.0
    for _ in range(8):
        gr = g0 - (level_dbu(render(spec, tone(lvl, 1.0), **dict(ctl, ln_null=0.5))) - lvl)
        if abs(gr - 10.0) < 0.1:
            break
        lvl += (10.0 - gr) / 0.75  # 4:1 above threshold
    x = tone(lvl, 1.0)
    pts = np.linspace(0.0, 1.0, 11)
    rows = pmap(lambda a: (float(a), thd(render(spec, x, **dict(ctl, ln_null=float(a))))), pts)
    k = int(np.argmin([r[1] for r in rows]))
    k = min(max(k, 1), len(rows) - 2)
    a, b, c = (np.log(rows[k + i][1]) for i in (-1, 0, 1))
    den = a - 2 * b + c
    best = pts[k] + (0.5 * (a - c) / den * (pts[1] - pts[0]) if den > 0 else 0.0)
    return float(np.clip(best, 0.0, 1.0)), rows + [("level_dbu", lvl), ("gr_db", gr)]


def write(consts: dict[str, float]) -> None:
    text = GEN.read_text(encoding="utf-8")
    for name, x in consts.items():
        text, n = re.subn(rf"^{name} = .*$", f"{name} = {x!r}", text, flags=re.M)
        assert n == 1, name
    GEN.write_text(text, encoding="utf-8")
    subprocess.run([sys.executable, str(GEN)], check=True)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--write", action="store_true", help="update the generator and the file")
    a = ap.parse_args()
    fb0 = float(load_circuit(CIRCUIT).values["t2_fb_ratio"]["value"])
    fb, g = trim_gain(fb0)
    fb = round(fb, 4)
    print(f"T2 feedback winding ratio {fb} (gain {g:.3f} dB)")
    fixed = dict(t2_fb_ratio=fb)
    r83, q, rows = trim_r83(**fixed)
    for r, qq in rows:
        print(f"  R83 {r:7.0f} ohm: 1 dB at R59 {qq:.4f}")
    q = round(q, 4)
    print(f"R83 {r83:.0f} ohm, Q bias {q}")
    fixed["r83_ohm"] = max(r83, 1e-3)
    r86, rows = trim_r86(q, **fixed)
    for row in rows:
        print("  ", row)
    r86 = round(r86, 3)
    print(f"R86 at {r86}")
    if a.write:
        write({"T2_FB_RATIO": fb, "R83_OHM": r83, "Q_BIAS_AT": q,
               "R86_AT": r86})  # fmt: skip
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
