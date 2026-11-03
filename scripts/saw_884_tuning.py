"""H4: the keyboard tuning of the gas-tube sawtooth (docs/HYBRID_PHYSICS_PLAN.md H4).

Two targets (TARGETS), each built with events (technique K: the 884 as its event kernels,
config/events/884_saw.json) at the draft (96 kHz internal: the native app's draft-2x, the
quality they play at), partitioned and coupled as the app's device is:
- `voice`: config/circuits/saw_884.yaml, its `pitch` input, the pitch read on node `n`;
- `synth`: config/circuits/tube_synth.yaml's second oscillator (SAW ON), its `pitch2` input,
  the pitch read on `s_ct`; the LC oscillator and the LFO off (neither moves the saw's pitch:
  it has its own supply, and its vibrato follower's grid sits at 0 V either way), noise off
  (the app's default), the key up, 2 s more of settling (its supply's).
Each point holds the pitch input through the render's settling (sim_settings start.settle_s)
and HOLD_S more (longer at low pitches: MIN_CYCLES cycles at least); its pitch is read on CT's
lower plate (the strike is its sharp rise), not the output (the band-limited edge rings there
under M1).

- A coarse sweep, COARSE_STEP_V apart over the target's range, then bisection: between two
  kept points a midpoint is measured, and kept (both halves bisected again) where the
  keyboard's interpolation (linear in log2 Hz: `panel::Pitch`) misses it by more than
  MAX_ERR_CENTS, down to MIN_STEP_V.
- Each point's cycle-to-cycle spread (the 2.5-97.5 percentiles of the per-cycle pitch, in
  cents), its sweep (CT's plate's peak to peak) and its ramp's slope (sweep x pitch), flagged
  where the slope is outside the tables' log-slope axis (K holds the table's end there: the
  monitor is bounded by it, the render isn't).
- K against M1 (the render: production, the oscillator as its island) at the target's check
  points: a take played on K and re-rendered through M1 moves by that much.

Result: reports/hybrid/<target's file>.json and .png, the table printed as Rust.

    uv run --extra fast --extra listen python scripts/saw_884_tuning.py [--target synth]
        [--workers N] [--no-check]
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

from varimu.circuit import builder, spec
from varimu.circuit.ir import VoltageProbe
from varimu.config import CONFIG_DIR
from varimu.sim import fast, io
from varimu.synth import vco

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "reports" / "hybrid"
TABLES = CONFIG_DIR / "events" / "884_saw.json"
COARSE_STEP_V = 5.0
MIN_STEP_V = 0.3125  # 5 V halved four times
MAX_ERR_CENTS = 1.0
HOLD_S = 1.0
MIN_CYCLES = 20

# tube_synth's partition as the app's device has it (panel::DEVICES' tube_synth)
SYNTH_PARTITION = (
    "resonance", "|", "input", "filter", "cutoff", "|", "envelope", "|", "ring", "|",
    "oscillator", "pitch", "|", "saw pitch", "saw", "|", "lfo", "|",
    "power supply", "bias supply", "saw supply",
)  # fmt: skip


@dataclasses.dataclass(frozen=True)
class Target:
    file: str  # the result's name
    circuit: str
    control: str  # the pitch input
    probe: str  # CT's lower plate
    out: str  # the waveform whose peak is reported
    lo_v: float
    hi_v: float
    check_v: tuple[float, ...]
    sets: tuple[tuple[str, float], ...] = ()
    held: tuple[tuple[str, float], ...] = ()  # the other control inputs
    partition: tuple[str, ...] | None = None
    coupling: str | None = None
    # Run this long before the kept part, past the render's settling (its own supply's
    # reservoirs and prefilter settle over ~2 s: the first 0.3 s up to ~-10 c at the bottom)
    discard_s: float = 0.0


TARGETS = {
    "voice": Target(
        file="saw_884_tuning",
        circuit="saw_884",
        control="pitch",
        probe="n",
        out="saw",
        lo_v=-250.0,
        hi_v=0.0,
        check_v=(-250.0, -240.0, -225.0, -200.0, -100.0, 0.0),
        held=(("gate", -110.0),),
        partition=("vca",),
        coupling="hold",
    ),
    "synth": Target(
        file="synth_saw_tuning",
        circuit="tube_synth",
        control="pitch2",
        probe="s_ct",
        out="s_kf",
        lo_v=-310.0,
        hi_v=0.0,
        check_v=(-300.0, -150.0, 0.0),
        discard_s=2.0,
        sets=(("saw_on", 1), ("osc_on", 0), ("lfo_on", 0)),
        held=(("gate", -110.0), ("pitch", -15.0), ("key", 0.0), ("pressure", 0.0)),
        partition=SYNTH_PARTITION,
        coupling="hold",
    ),
}


def render(t: Target, v: float, quality: str, events: bool, dur_s: float) -> dict[str, np.ndarray]:
    c = spec.load_circuit(CONFIG_DIR / "circuits" / f"{t.circuit}.yaml")
    ir = builder.build_ir(c, spec.resolve(c, dict(t.sets)), events=events, noise=False)
    ir = dataclasses.replace(ir, probes=(VoltageProbe(t.probe), VoltageProbe(t.out)))
    st = dataclasses.replace(
        io.TransientSettings.from_sim_settings(engine="circuitsim", quality=quality),
        full_scale_volts_peak=1.0,
    )
    if quality != "production":
        if t.partition is not None:
            st = dataclasses.replace(st, partition=t.partition)
        if t.coupling is not None:
            st = dataclasses.replace(st, partition_coupling=t.coupling)
    fs = io.load_sim_settings().sample_rate
    skip = int(t.discard_s * fs)
    n = int(dur_s * fs) + skip
    controls = {t.control: np.full(n, float(v)), **{k: np.full(n, x) for k, x in t.held}}
    out = fast.run_transient(ir, np.zeros(n), settings=st, controls=controls)
    return {p: out.vectors[f"v({p})"][skip:] for p in (t.probe, t.out)}


def measure(t: Target, v: float, quality: str = "draft", events: bool = True) -> dict:
    """One held point: its pitch, spread, sweep and slope (a longer run if 1 s holds fewer
    than MIN_CYCLES cycles)."""
    fs = io.load_sim_settings().sample_rate
    dur = HOLD_S
    for _ in range(2):
        r = render(t, v, quality, events, dur)
        f = vco.frequency(r[t.probe], fs)
        if np.isfinite(f) and f * dur >= MIN_CYCLES:
            break
        dur = MIN_CYCLES / f if np.isfinite(f) and f > 0 else 4.0 * dur
    fc = vco.cycle_frequencies(r[t.probe], fs)[1]
    spread = (
        float(1200 * np.log2(np.percentile(fc, 97.5) / np.percentile(fc, 2.5)))
        if np.isfinite(f) and len(fc) > 3
        else float("nan")
    )
    sweep = float(np.ptp(r[t.probe]))
    return {
        "v": float(v),
        "hz": float(f),
        "spread_cents": spread,
        "sweep_v": sweep,
        "slope_v_per_us": sweep * f * 1e-6,
        "hold_s": dur,
        "out_peak_v": float(np.max(np.abs(r[t.out] - np.mean(r[t.out])))),
    }


def cents_off_interp(lo: dict, hi: dict, mid: dict) -> float:
    """The keyboard's interpolation between lo and hi (linear in log2 Hz against volts) at
    mid's volts, against mid's measured pitch (cents)."""
    t = (mid["v"] - lo["v"]) / (hi["v"] - lo["v"])
    pred = np.log2(lo["hz"]) + t * (np.log2(hi["hz"]) - np.log2(lo["hz"]))
    return float(1200 * (np.log2(mid["hz"]) - pred))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--target", choices=list(TARGETS), default="voice")
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 4) - 2))
    ap.add_argument("--out", type=Path, default=OUT_DIR)
    ap.add_argument("--no-check", action="store_true", help="skip K against M1")
    a = ap.parse_args()
    t = TARGETS[a.target]
    a.out.mkdir(parents=True, exist_ok=True)
    t0 = time.perf_counter()
    ex = ThreadPoolExecutor(a.workers)

    def meas(v: float) -> dict:
        return measure(t, v)

    vs = np.arange(t.lo_v, t.hi_v + 0.5 * COARSE_STEP_V, COARSE_STEP_V)
    print(f"coarse: {len(vs)} points", flush=True)
    pts = {float(v): m for v, m in zip(vs, ex.map(meas, vs), strict=True)}
    # Below the law's start (no oscillation) a point has no pitch: the table starts above.
    pts = {v: m for v, m in pts.items() if np.isfinite(m["hz"])}
    vs = np.array(sorted(pts))
    # Bisect: every interval whose midpoint the interpolation misses by more than the bound.
    todo = [(float(x), float(y)) for x, y in zip(vs[:-1], vs[1:], strict=True)]
    misses: dict[float, float] = {}
    while todo:
        mids = [0.5 * (x + y) for x, y in todo]
        print(f"bisect: {len(mids)} midpoints", flush=True)
        got = dict(zip(mids, ex.map(meas, mids), strict=True))
        nxt = []
        for (x, y), m in zip(todo, mids, strict=True):
            err = cents_off_interp(pts[x], pts[y], got[m])
            misses[m] = err
            if abs(err) > MAX_ERR_CENTS:
                pts[m] = got[m]
                if y - x > 2 * MIN_STEP_V:
                    nxt += [(x, m), (m, y)]
        todo = nxt
    table = sorted(pts.values(), key=lambda p: p["v"])
    hz = np.array([p["hz"] for p in table])
    assert np.all(np.isfinite(hz)) and np.all(np.diff(hz) > 0), "the law isn't monotonic"

    tab = json.loads(TABLES.read_text())
    ends = (tab["log_slope"][0], tab["log_slope"][-1])
    slope_lo, slope_hi = (float(np.exp(x)) * 1e-6 for x in ends)
    for p in table:
        p["in_tables"] = bool(slope_lo <= p["slope_v_per_us"] <= slope_hi)

    check = []
    if not a.no_check:
        print(f"K against M1 at {t.check_v}", flush=True)
        # Each at the K point's hold: the same cycles.
        holds = {v: pts[v]["hold_s"] if v in pts else HOLD_S for v in t.check_v}

        def m1(v: float) -> dict:
            fs = io.load_sim_settings().sample_rate
            r = render(t, v, "production", False, holds[v])
            return {"v": v, "hz": float(vco.frequency(r[t.probe], fs))}

        for v, r in zip(t.check_v, ex.map(m1, t.check_v), strict=True):
            k = pts.get(v) or measure(t, v)
            check.append(
                {
                    "v": v,
                    "k_draft_hz": round(k["hz"], 3),
                    "m1_production_hz": round(r["hz"], 3),
                    "k_minus_m1_cents": round(float(1200 * np.log2(k["hz"] / r["hz"])), 2),
                }
            )
    ex.shutdown()

    res = {
        "circuit": t.circuit,
        "control": t.control,
        "sets": dict(t.sets),
        "quality": "draft",
        "events": True,
        "probe": t.probe,
        "max_interp_error_cents": MAX_ERR_CENTS,
        "tables_slope_v_per_us": [round(slope_lo, 5), round(slope_hi, 4)],
        "hz_v": [(round(p["hz"], 2), round(p["v"], 4)) for p in table],
        "points": [
            {k: (round(x, 4) if isinstance(x, float) else x) for k, x in p.items()} for p in table
        ],
        "bisection_misses_cents": {f"{v:g}": round(e, 2) for v, e in sorted(misses.items())},
        "k_vs_m1": check,
        "wall_s": round(time.perf_counter() - t0, 1),
    }
    (a.out / f"{t.file}.json").write_text(json.dumps(res, indent=1) + "\n")
    plot(res, a.out / f"{t.file}.png")
    print(json.dumps({k: res[k] for k in ("tables_slope_v_per_us", "k_vs_m1", "wall_s")}, indent=1))
    print(f"{len(table)} points, {hz[0]:.2f} Hz .. {hz[-1]:.1f} Hz")
    print("&[")
    for f, v in res["hz_v"]:
        print(f"    ({f}, {v}),")
    print("]")


def plot(res: dict, path: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    p = res["points"]
    v = np.array([x["v"] for x in p])
    fig, ax = plt.subplots(1, 3, figsize=(15, 4.2))
    ax[0].semilogy(v, [x["hz"] for x in p], ".-")
    for x in p:
        if not x["in_tables"]:
            ax[0].semilogy(x["v"], x["hz"], "rx")
    ax[0].set(title=f"pitch against {res['control']} (K, draft)", xlabel="V", ylabel="Hz")
    ax[1].plot(v, [x["spread_cents"] for x in p], ".-")
    ax[1].set(title="cycle-to-cycle spread (2.5-97.5 %)", xlabel="V", ylabel="cents")
    m = res["bisection_misses_cents"]
    ax[2].plot([float(k) for k in m], list(m.values()), ".")
    ax[2].axhline(res["max_interp_error_cents"], color="k", lw=0.5)
    ax[2].axhline(-res["max_interp_error_cents"], color="k", lw=0.5)
    ax[2].set(title="interpolation's miss at the midpoints", xlabel="V", ylabel="cents")
    fig.suptitle(f"{res['circuit']}: the keyboard tuning (red x: the ramp outside K's tables)")
    fig.tight_layout()
    fig.savefig(path, dpi=80)
    plt.close(fig)


if __name__ == "__main__":
    main()
