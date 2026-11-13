"""AM2, the two-pass null (docs/ANALOG_MAGIC_FABLE.md): the same input through a device twice,
and how deep the two outputs cancel, stage by stage (varimu.magic.null.null_report).

Pairs per device (production quality):
  P0  noise off, twice (the second uncached): must be bit-identical
  P1  noise off, origin 0 vs 7.3 s: the mains' phase against the music
  P2  noise seed 1 vs 2: resistor and tube noise, mains wander (and a tape's grain and
      transport together)
  P3  noise seed 1, origin 0 vs 7.3 s: the same unit at another moment
  P4  heaters warm vs cold (fender_5e3_mods only; 10 s is inside the 7 s thermal lag's span)
plus each device's noise alone (seed 1 on silence): P2's residual against sqrt(2) x that floor
says how much of the difference is signal-dependent.

The tape machine alone (varimu.devices.tape_machine.print_audio), grain and transport apart:
  T1 grain seed 1 vs 2, T2 transport seed 0 vs 1 (no grain), T3 both.

-> reports/magic/null/ (summary.json, null.png, residual WAVs, README.md written by hand).

  uv run --extra fast --extra listen python scripts/two_pass_null.py [--only DEVICE ...]
      [--clips guitar drums] [--seconds 10] [--jobs N] [--analyse-only]

--analyse-only recomputes the reports from the render cache (P0's uncached second pass is not
rerun: P0 keeps the previous summary's result).
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import numpy as np

from varimu.config import REPO_ROOT
from varimu.magic import null, render
from varimu.sim.io import load_audio, write_audio

OUT = REPO_ROOT / "reports" / "magic" / "null"
CLIPS = {"guitar": "Dry Guitar.wav", "drums": "drums_setmefree.wav"}
ORIGIN_S = 7.3
# Devices: (circuit, overrides, controls factory or None). The 351 and the tape machine are
# handled apart (their own render functions).
DEVICES: dict[str, tuple[str, dict, bool]] = {
    "fairchild_670": ("fairchild_670", {}, False),
    "pultec_eqp1a": ("pultec_eqp1a", {}, False),
    "telefunken_v76": ("telefunken_v76", {}, False),
    "fender_5e3": ("fender_5e3", {}, False),
    "fender_5e3_mods": ("fender_5e3_mods", {}, False),
    "urei_1176": ("urei_1176", {}, False),
    "ssl_bus_comp": ("ssl_bus_comp", {}, True),  # its KEY input held at 0 (INT)
    "plate_reverb": ("plate_reverb", {}, False),
    "fender_6g15": ("fender_6g15", {}, False),
}
EXTRA = ("ampex_351", "tape_machine")


def program(name: str, seconds: float, fs: int) -> np.ndarray:
    x = load_audio(REPO_ROOT / "data" / "clips" / CLIPS[name], fs)[: int(seconds * fs)]
    x = x * 10 ** (-18 / 20) / (np.std(x) + 1e-30)
    f = int(0.02 * fs)
    x[:f] *= np.linspace(0, 1, f)
    return x


def jobs_for(dev: str, clip: str, x: np.ndarray) -> dict[str, dict]:
    """The renders a device needs for one clip: {tag: job}."""
    z = np.zeros_like(x)
    if dev == "ampex_351":
        f = render.ampex_351
        base = {"fn": f, "x": x}
        return {
            "base": {**base, "noise": False},
            "base_again": {**base, "noise": False, "cache": False},
            "origin": {**base, "noise": False, "origin_s": ORIGIN_S},
            "n1": {**base, "noise": 1},
            "n2": {**base, "noise": 2},
            "n1_origin": {**base, "noise": 1, "origin_s": ORIGIN_S},
            "floor": {"fn": f, "x": z, "noise": 1},
        }
    if dev == "tape_machine":
        f = render.tape_print
        return {
            "g1t0": {"fn": f, "x": x, "noise_seed": 1, "transport_seed": 0},
            "g2t0": {"fn": f, "x": x, "noise_seed": 2, "transport_seed": 0},
            "g0t0": {"fn": f, "x": x, "noise_seed": None, "transport_seed": 0},
            "g0t1": {"fn": f, "x": x, "noise_seed": None, "transport_seed": 1},
            "g2t1": {"fn": f, "x": x, "noise_seed": 2, "transport_seed": 1},
            "floor": {"fn": f, "x": z, "noise_seed": 1, "transport_seed": 0},
        }
    circuit, ov, keyed = DEVICES[dev]
    base = {"circuit": circuit, "x": x, "overrides": ov}
    if keyed:
        base["controls"] = {"key": np.zeros_like(x)}
    out = {
        "base": {**base, "noise": False},
        "base_again": {**base, "noise": False, "cache": False},
        "origin": {**base, "noise": False, "origin_s": ORIGIN_S},
        "n1": {**base, "noise": 1},
        "n2": {**base, "noise": 2},
        "n1_origin": {**base, "noise": 1, "origin_s": ORIGIN_S},
        "floor": {**base, "x": z, "noise": 1, **({"controls": {"key": z}} if keyed else {})},
    }
    if dev == "fender_5e3_mods":
        out["warm"] = {**base, "noise": False, "heaters": "warm"}
        out["cold"] = {**base, "noise": False, "heaters": "cold"}
    return out


PAIRS = {
    "P0 identical": ("base", "base_again"),
    "P1 mains phase": ("base", "origin"),
    "P2 noise seeds": ("n1", "n2"),
    "P3 another moment": ("n1", "n1_origin"),
    "P4 warm vs cold": ("warm", "cold"),
    "T1 grain": ("g1t0", "g2t0"),
    "T2 transport": ("g0t0", "g0t1"),
    "T3 both": ("g1t0", "g2t1"),
}


def cost_weight(dev: str) -> float:
    """Rough relative render cost, longest first in the queue."""
    return {
        "ampex_351": 30,
        "tape_machine": 24,
        "fairchild_670": 25,
        "fender_5e3": 20,
        "fender_5e3_mods": 22,
        "plate_reverb": 10,
    }.get(dev, 8)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--only", nargs="+", default=None)
    ap.add_argument("--clips", nargs="+", default=list(CLIPS))
    ap.add_argument("--seconds", type=float, default=10.0)
    ap.add_argument("--jobs", type=int, default=None)
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--analyse-only", action="store_true")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    fs = render.sample_rate()
    devs = a.only or [*DEVICES, *EXTRA]
    progs = {c: program(c, a.seconds, fs) for c in a.clips}

    work: list[tuple[str, str, str, dict]] = []
    for dev in devs:
        for clip, x in progs.items():
            for tag, job in jobs_for(dev, clip, x).items():
                if a.analyse_only and tag == "base_again":
                    job = {**job, "cache": True}
                work.append((dev, clip, tag, job))
    work.sort(key=lambda w: -cost_weight(w[0]))
    print(
        f"{len(work)} renders of {a.seconds:g} s (+1 s settle) on {a.jobs or 'default'} threads",
        flush=True,
    )

    results: dict[tuple[str, str, str], np.ndarray] = {}
    t0 = time.time()

    def run(w):
        dev, clip, tag, job = w
        t = time.time()
        job = dict(job)
        fn = job.pop("fn", render.through)
        y = fn(**job)["out"]
        return w, y, time.time() - t

    from varimu.sim.runner import default_jobs

    with ThreadPoolExecutor(a.jobs or default_jobs()) as ex:
        futs = [ex.submit(run, w) for w in work]
        for i, f in enumerate(as_completed(futs), 1):
            try:
                (dev, clip, tag, _), y, el = f.result()
            except Exception as e:  # keep the others going; report at the end
                print(f"  FAILED: {e!r}", flush=True)
                continue
            results[(dev, clip, tag)] = y
            done = time.time() - t0
            eta = done / i * (len(work) - i)
            print(
                f"  [{i}/{len(work)}] {dev} {clip} {tag}: {el:.0f} s "
                f"(elapsed {done / 60:.1f} min, ETA {eta / 60:.1f} min)",
                flush=True,
            )

    summary: dict = {"seconds": a.seconds, "fs": fs, "devices": {}}
    prior = out / "summary.json"
    if prior.exists() and (a.only or a.analyse_only):
        summary = json.loads(prior.read_text())
    for dev in devs:
        d = summary["devices"].setdefault(dev, {})
        for clip in progs:
            c = d.setdefault(clip, {})
            base = results.get((dev, clip, "base"), results.get((dev, clip, "g0t0")))
            floor = results.get((dev, clip, "floor"))
            if base is not None and floor is not None:
                c["noise_floor_db"] = null.rms_db(floor, base)
                c["output_rms_dbfs"] = null.rms_db(base, 1.0)
                c["floor_bands"] = null.band_levels(floor, base, fs)
                c["noise_floor_audio_db"] = null.rms_db(
                    null.audio_band(floor, fs), null.audio_band(base, fs)
                )
            for pname, (ta, tb) in PAIRS.items():
                ya, yb = results.get((dev, clip, ta)), results.get((dev, clip, tb))
                if ya is None or yb is None:
                    continue
                if a.analyse_only and pname.startswith("P0") and pname in c:
                    continue
                r = null.null_report(ya, yb, fs)
                if pname.startswith("P2") and "noise_floor_db" in c:
                    # Independent additive noise alone would give the floor + 3.01 dB.
                    c["P2 additive expectation"] = c["noise_floor_db"] + 10 * math.log10(2)
                    c["P2 additive expectation audio"] = c[
                        "noise_floor_audio_db"
                    ] + 10 * math.log10(2)
                c[pname] = r
                if not r.get("identical"):
                    ra, rb, _ = null.align(ya, yb, fs)
                    g = r["gain_factor"]
                    res = ra - g * rb
                    stem = f"{dev}_{clip}_{pname.split()[0]}"
                    write_audio(out / "audio" / f"{stem}_residual.wav", res, fs)
                    write_audio(out / "audio" / f"{stem}_residual_+20dB.wav", res * 10, fs)
            print(
                f"{dev} {clip}: "
                + ", ".join(
                    f"{p.split()[0]} gain {c[p]['gain']:.1f} / dewarped {c[p].get('dewarped', float('nan')):.1f}"
                    for p in PAIRS
                    if p in c and not c[p].get("identical")
                )
                + (" | P0 identical" if c.get("P0 identical", {}).get("identical") else ""),
                flush=True,
            )
    prior.write_text(json.dumps(summary, indent=1, default=float))
    plot(summary, out)
    print(f"done in {(time.time() - t0) / 60:.1f} min -> {out}")
    return 0


def plot(summary: dict, out: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    devs = list(summary["devices"])
    n = len(devs)
    fig, axes = plt.subplots(
        math.ceil(n / 3), 3, figsize=(15, 3.6 * math.ceil(n / 3)), squeeze=False
    )
    for ax, dev in zip(axes.flat, devs, strict=False):
        for clip, c in summary["devices"][dev].items():
            for p, r in c.items():
                if not isinstance(r, dict) or "bands" not in r or r.get("identical"):
                    continue
                f = [float(k) for k in r["bands"]]
                v = list(r["bands"].values())
                ax.semilogx(
                    f, v, label=f"{clip} {p.split()[0]}", ls="-" if clip == "guitar" else "--"
                )
        ax.set_title(dev)
        ax.set_ylim(-140, 10)
        ax.grid(True, which="both", alpha=0.3)
        ax.set_xlabel("Hz")
        ax.set_ylabel("residual re band (dB)")
        ax.legend(fontsize=6)
    for ax in list(axes.flat)[n:]:
        ax.axis("off")
    fig.tight_layout()
    fig.savefig(out / "null.png", dpi=110)
    plt.close(fig)


if __name__ == "__main__":
    sys.exit(main())
