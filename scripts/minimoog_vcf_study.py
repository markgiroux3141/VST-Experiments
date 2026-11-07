"""The Minimoog VCF (config/circuits/minimoog_vcf.yaml, docs/MINIMOOG_PLAN.md MM1): its idle
bias, self-oscillation (where it starts, its frequency), the small-signal response and the
cutoff's law over the keyboard.

    uv run --extra fast python scripts/minimoog_vcf_study.py [--only idle osc response track]
        [--set k=v ...] [--quality production|draft]

Writes reports/minimoog/vcf/summary.json (and response.png with matplotlib)."""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from pathlib import Path

import numpy as np

from varimu.circuit import builder, spec
from varimu.config import CONFIG_DIR
from varimu.sim import fast
from varimu.sim.io import TransientSettings

FS = 96000.0
CIRCUIT = CONFIG_DIR / "circuits" / "minimoog_vcf.yaml"
OUT = Path(__file__).resolve().parents[1] / "reports" / "minimoog" / "vcf"
SETTLE_S = 0.3  # the slowest network: C24 220 uF on ~200 ohm (44 ms), C5 / C1 on 47K (10 ms)


def load():
    return spec.load_circuit(CIRCUIT)


def build(s, overrides: dict | None = None):
    return builder.build_ir(s, spec.resolve(s, overrides or {}), "ja")


def settings(quality: str = "production") -> TransientSettings:
    s = TransientSettings.from_sim_settings(engine="circuitsim", quality=quality)
    return dataclasses.replace(s, settle_s=SETTLE_S)


def run(ir, x, *, key_v=0.0, contour_v=0.0, quality="production", stats=None):
    n = len(x)
    ctl = {"key": np.full(n, float(key_v)), "contour": np.full(n, float(contour_v))}
    r = fast.run_transient(ir, x, settings=settings(quality), controls=ctl, stats=stats)
    return {k: np.asarray(v) for k, v in r.vectors.items()}


def kick(dur_s: float, amp_v: float = 0.02) -> np.ndarray:
    """A short click into the input (starts a regenerating filter ringing)."""
    x = np.zeros(int(dur_s * FS))
    x[10:40] = amp_v
    return x


def ring(v: np.ndarray) -> tuple[float, float]:
    """(peak-to-peak over the last 0.1 s, frequency from its zero crossings) of a signal."""
    tail = v[-int(0.1 * FS) :]
    tail = tail - tail.mean()
    pp = float(tail.max() - tail.min())
    s = np.signbit(tail)
    idx = np.flatnonzero(s[:-1] & ~s[1:])
    if len(idx) < 3:
        return pp, 0.0
    # sub-sample crossings
    fr = idx + tail[idx] / (tail[idx] - tail[idx + 1])
    return pp, float(FS * (len(fr) - 1) / (fr[-1] - fr[0]))


def oscillates(ir, dur_s=0.6, **kw) -> tuple[bool, float, float]:
    """Kicked, does it still ring at full size at the end (pp at the end vs 0.2 s in)?"""
    v = run(ir, kick(dur_s), **kw)["v(out)"]
    mid = v[int(0.2 * FS) : int(0.3 * FS)]
    pp_mid = float(mid.max() - mid.min())
    pp, f = ring(v)
    return bool(pp > 0.05 and pp >= 0.7 * pp_mid), pp, f


def idle(s) -> dict:
    v = run(build(s), np.zeros(int(0.05 * FS)))
    return {k: float(np.mean(x[-480:])) for k, x in v.items()}


def osc_sweep(s, base: dict) -> dict:
    """Self-oscillation against EMPHASIS (0.5 .. 1) at the overrides `base`."""
    rows = []
    for e in (0.5, 0.6, 0.7, 0.75, 0.8, 0.9, 1.0):
        ok, pp, f = oscillates(build(s, {**base, "emphasis": e}))
        rows.append({"emphasis": e, "oscillates": ok, "pp_v": pp, "freq_hz": f})
        tag = "OSC" if ok else "   "
        print(f"  emphasis {e:.2f}: {tag} pp {pp:.3f} V  f {f:.1f} Hz", flush=True)
    return {"base": base, "rows": rows}


def multisine(dur_s: float, amp_v: float, freqs: np.ndarray, seed: int = 1) -> np.ndarray:
    rng = np.random.default_rng([seed, 7])
    t = np.arange(int(dur_s * FS)) / FS
    ph = rng.uniform(0, 2 * np.pi, len(freqs))
    x = np.sum(np.sin(2 * np.pi * freqs[:, None] * t + ph[:, None]), axis=0)
    return amp_v * x / np.max(np.abs(x))


def response(s, base: dict, amp_v: float = 0.005) -> dict:
    """|out / in| at log-spaced tones (bins of a 1 s periodic multisine), relative to the lowest."""
    dur = 1.0
    freqs = np.unique(np.round(np.geomspace(20, 20000, 40)))
    x = multisine(dur + 0.2, amp_v, freqs)
    v = run(build(s, base), x)
    n = int(dur * FS)
    o, i = v["v(out)"][-n:], x[-n:]
    spec_o, spec_i = np.fft.rfft(o), np.fft.rfft(i)
    k = freqs.astype(int)  # 1 Hz bins
    h = np.abs(spec_o[k] / spec_i[k])
    db = 20 * np.log10(h / h[0])
    return {"base": base, "freq_hz": freqs.tolist(), "gain_db": db.tolist(), "g0": float(h[0])}


def track(s, base: dict) -> dict:
    """Oscillation frequency at EMPHASIS 10 over keyboard volts (1 V / octave expected)."""
    ir = build(s, {**base, "emphasis": 1.0})
    rows = []
    for kv in (-1.0, 0.0, 1.0, 2.0, 3.0):
        _, pp, f = oscillates(ir, key_v=kv)
        rows.append({"key_v": kv, "freq_hz": f, "pp_v": pp})
        print(f"  key {kv:+.0f} V: f {f:.1f} Hz  pp {pp:.3f}", flush=True)
    f = np.array([r["freq_hz"] for r in rows])
    if np.all(f > 0):
        oct_per_v = np.diff(np.log2(f)).tolist()
    else:
        oct_per_v = []
    return {"base": base, "rows": rows, "octaves_per_volt": oct_per_v}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--only", nargs="*", default=["idle", "osc", "response", "track"])
    ap.add_argument("--set", nargs="*", default=[], metavar="K=V")
    a = ap.parse_args(argv)
    base = {}
    for kv in a.set:
        k, _, v = kv.partition("=")
        base[k] = float(v)
    s = load()
    OUT.mkdir(parents=True, exist_ok=True)
    out = {}
    if "idle" in a.only:
        out["idle"] = idle(s)
        for k, v in out["idle"].items():
            print(f"  {k:10s} {v:+9.4f}")
    if "osc" in a.only:
        print("self-oscillation vs EMPHASIS (key 0 V, keyboard control on):")
        out["osc"] = osc_sweep(s, base)
    if "response" in a.only:
        out["response"] = {}
        for e in (0.0, 0.5, 0.7):
            r = response(s, {**base, "emphasis": e})
            out["response"][f"emphasis_{e:g}"] = r
            peak = int(np.argmax(r["gain_db"]))
            pk_db, pk_hz = r["gain_db"][peak], r["freq_hz"][peak]
            print(f"  emphasis {e:g}: peak {pk_db:+.1f} dB at {pk_hz:.0f} Hz, g0 {r['g0']:.2f}")
        try:
            import matplotlib

            matplotlib.use("Agg")
            import matplotlib.pyplot as plt

            fig, ax = plt.subplots(figsize=(7, 4))
            for name, r in out["response"].items():
                ax.semilogx(r["freq_hz"], r["gain_db"], label=name)
            ax.set_ylim(-80, 20)
            ax.grid(True, which="both", alpha=0.3)
            ax.set_xlabel("Hz")
            ax.set_ylabel("dB re 20 Hz")
            ax.legend()
            fig.savefig(OUT / "response.png", dpi=120, bbox_inches="tight")
        except ImportError:
            pass
    if "track" in a.only:
        print("keyboard tracking at EMPHASIS 10:")
        out["track"] = track(s, base)
    (OUT / "summary.json").write_text(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
