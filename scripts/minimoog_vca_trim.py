"""The Minimoog VCA (circuit No. 7 of config/circuits/minimoog_filter_board.yaml,
docs/MINIMOOG_PLAN.md MM2): Folkman's VCA Balance, then the VCA's gain law over the contour and
its thump.

Folkman, p. 13 ('VCA Balance'): all MIXER switches off, headphones on, a jumper from point "A"
on the filter board to point "A" on the oscillator board; adjust the 2nd VCA Balance trimpot for
the minimum audio signal; depress and hold a key, adjust the 1st VCA Balance for the minimum.
Read as: the jumper puts an oscillator's audio on a VCA control line (EXT. LOUDNESS, the 2nd
stage's tail); what reaches the output is the control's feedthrough, which a balanced stage
cancels. Measured here quasi-statically: the output's DC shift between two EXT. LOUDNESS
voltages (an audio-rate feedthrough at low frequency), key up (the 1st stage off) for R12, key
held (the contour on) for R14.

    uv run --extra fast python scripts/minimoog_vca_trim.py [--write] [--skip-trim]

Writes reports/minimoog/vca/summary.json."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import minimoog_vcf_study as st  # noqa: E402

OUT = st.OUT.parent / "vca"
LOUD_V = (4.0, 8.0)  # the two EXT. LOUDNESS levels of the balance


def vo_dc(s, ov: dict, contour_v: float) -> float:
    """The VCA's output node (Q17's collector) at rest, no audio."""
    v = st.run(st.build(s, ov), np.zeros(int(0.03 * st.FS)), contour_v=contour_v)
    return float(np.mean(v["v(vo)"][-480:]))


def feedthrough(s, ov: dict, contour_v: float) -> float:
    lo, hi = (vo_dc(s, {**ov, "ext_loudness": 1, "ext_loudness_v": x}, contour_v) for x in LOUD_V)
    return hi - lo


def golden_min(fn, lo=0.0, hi=1.0, steps=14) -> float:
    """The minimum of |fn| on [lo, hi]: fn is ~linear in the trim, so bisect its zero when it
    changes sign, else return the better end."""
    flo, fhi = fn(lo), fn(hi)
    if (flo > 0) == (fhi > 0):
        return lo if abs(flo) < abs(fhi) else hi
    for _ in range(steps):
        mid = 0.5 * (lo + hi)
        fm = fn(mid)
        if (fm > 0) == (flo > 0):
            lo, flo = mid, fm
        else:
            hi = mid
    return 0.5 * (lo + hi)


def gain_law(s, ov: dict, amp_v: float = 0.05, f_hz: float = 220.0) -> list[dict]:
    """A sine through the filter (cutoff +4 V, EMPHASIS 0) and the VCA at contour levels: the
    MAIN OUTPUT's level re the filter's output, and its THD."""
    o = {**ov, "cutoff": 0.7, "emphasis": 0.0}
    ir = st.build(s, o)
    t = np.arange(int(0.3 * st.FS)) / st.FS
    x = amp_v * np.sin(2 * np.pi * f_hz * t)
    rows = []
    for c in (0.0, 0.5, 1.0, 1.5, 2.0, 3.0, 4.0, 5.0, 6.0):
        v = st.run(ir, x, contour_v=c)
        n = int(0.2 * st.FS)
        out, flt = v["v(out)"][-n:], v[st.VCF][-n:]
        out = out - out.mean()
        sp = np.abs(np.fft.rfft(out * np.hanning(n)))
        fr = np.fft.rfftfreq(n, 1 / st.FS)

        def pk(h, sp=sp, fr=fr):
            i = int(np.argmin(np.abs(fr - f_hz * h)))
            return sp[i - 3 : i + 4].max()

        thd = float(np.sqrt(sum(pk(k) ** 2 for k in range(2, 8))) / max(pk(1), 1e-30))
        g = float(np.ptp(out) / max(np.ptp(flt), 1e-12))
        rows.append({"contour_v": c, "gain": g, "gain_db": 20 * np.log10(max(g, 1e-12)),
                     "out_pp_v": float(np.ptp(out)), "thd": thd})  # fmt: skip
        gdb = 20 * np.log10(max(g, 1e-12))
        print(f"  contour {c:3.1f} V: out {np.ptp(out):7.4f} V pp, gain {gdb:+6.1f} dB"
              f" re the filter, THD {100 * thd:5.2f} %", flush=True)  # fmt: skip
    return rows


def thump(s, ov: dict) -> dict:
    """No audio, the contour stepped 0 -> 5 V (a key, attack 0) and back: the MAIN OUTPUT's
    largest excursion (control feedthrough)."""
    n = int(0.4 * st.FS)
    c = np.zeros(n)
    c[int(0.1 * st.FS) : int(0.25 * st.FS)] = 5.0
    v = st.run(st.build(s, ov), np.zeros(n), contour_v=c)["v(out)"]
    return {"peak_v": float(np.max(np.abs(v - v[: int(0.09 * st.FS)].mean())))}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--skip-trim", action="store_true")
    a = ap.parse_args(argv)
    s = st.load()
    ov: dict = {}
    out: dict = {}
    if not a.skip_trim:
        print("2nd VCA balance (key up):")

        def f2(x):
            d = feedthrough(s, {**ov, "vca2_bal": x}, 0.0)
            print(f"  vca2_bal {x:.4f}: {1e3 * d:+8.3f} mV", flush=True)
            return d

        ov["vca2_bal"] = golden_min(f2)
        print("1st VCA balance (key held):")

        def f1(x):
            d = feedthrough(s, {**ov, "vca1_bal": x}, 5.0)
            print(f"  vca1_bal {x:.4f}: {1e3 * d:+8.3f} mV", flush=True)
            return d

        ov["vca1_bal"] = golden_min(f1)
        out["trims"] = dict(ov)
        out["residual_mv"] = {
            "key_up": 1e3 * feedthrough(s, ov, 0.0),
            "key_held": 1e3 * feedthrough(s, ov, 5.0),
        }
        print(json.dumps(out, indent=1))
    print("gain law (220 Hz, 50 mV into the filter):")
    out["gain_law"] = gain_law(s, ov)
    out["thump"] = thump(s, ov)
    print(f"thump: {1e3 * out['thump']['peak_v']:.1f} mV peak at the MAIN OUTPUT")
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "summary.json").write_text(json.dumps(out, indent=1))
    if a.write and "trims" in out:
        text = st.CIRCUIT.read_text()
        for key, val in out["trims"].items():
            text, n = re.subn(rf"(\n  {key}: \{{value: )[0-9.eE+-]+", rf"\g<1>{val:.4f}", text)
            assert n == 1, key
        st.CIRCUIT.write_text(text)
        print(f"wrote the trims into {st.CIRCUIT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
