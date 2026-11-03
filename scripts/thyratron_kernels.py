"""Technique K on the unit: its tables, the Python reference (H3b) and circuitsim's port (H3c)
against the unit's reference (HYBRID_PHYSICS_PLAN.md) -> reports/hybrid/k_unit_<grid>.json,
audio in reports/hybrid/audio/k_unit/

    uv run --extra fast --extra listen python scripts/thyratron_kernels.py [--grid fine|coarse]
        [--seconds S] [--workers N] [--timing] [--write NAME]

`--write NAME` saves the tables as config/events/NAME.json (what a circuit file's `devices`
entry names with `events: NAME`; builder.build(..., events=True)).

The 884's unit (varimu.devices.thyratron_events.Unit: RCA's C6, R4 and grid return) gets its
tables over the grid bias and the ramp's slope from reference runs of the unit alone. Then
the unit oscillates (a near-constant charging current: the instrument's sweep), at grid
points and between them, these ways:
- the reference: circuitsim production at 3.072 MHz, band-limited to 96 kHz (120 dB);
- K, Python: `thyratron_events.Emulator` at 96 kHz (the ramp exact, the strikes predicted
  and injected as the tables' charges);
- K in circuitsim (the unit's IR with the ThyratronEvents element in the tube's place): at
  the draft (trbdf2, 96 kHz, no error control: what plays live) and at production (esdirk4
  at 2x, error control, through renders' decimator);
- direct: circuitsim at the draft with the tube itself, what plays today.
Each against the reference: pitch (cents), cycle-to-cycle jitter, harmonic levels up to
20 kHz, the inharmonic power in 20 Hz-20 kHz (the event study's metrics), the sweep's mean
and peak-to-peak (the supply's charge per cycle is C times the sweep); K in circuitsim also
against the Emulator (the pitch: sample by sample, tenths of a cent drift apart), and the
draft's cost per second of audio (one job at a time, `--timing`).
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
import thyratron_event_study as es  # noqa: E402

from varimu.config import REPO_ROOT  # noqa: E402
from varimu.devices import thyratron_events as te  # noqa: E402

OUT = REPO_ROOT / "reports" / "hybrid"
# the table's grid: `--grid coarse` 5 x 7, `fine` 9 x 13 (interpolation's convergence)
GRIDS = {
    "coarse": ((-4.0, -5.0, -6.0, -7.0, -8.0), tuple(np.geomspace(0.003e6, 0.3e6, 7))),
    "fine": (tuple(np.linspace(-4.0, -8.0, 9)), tuple(np.geomspace(0.003e6, 0.3e6, 13))),
}
# grid points and between them: (v_g, slope V/s)
CHECKS = ((-6.0, 0.03e6), (-6.0, 0.3e6), (-4.0, 0.1e6), (-8.0, 0.01e6), (-5.5, 0.02e6),
          (-6.5, 0.15e6), (-4.5, 0.006e6), (-7.5, 0.25e6))  # fmt: skip


# The units: (Unit, grids, checks). "c6": RCA's C6 and R4 with RCA's grid stopper (H3b-H3d);
# "saw": the voice's (config/circuits/saw_884.yaml, H4: C 5 nF, R_s 450, its 2.2k grid
# return to a bias cell, a pentode's constant current), its grid around the cell's -12 V and
# its slopes over its pitch range (~10 Hz-5 kHz with a ~118 V sweep)
UNITS = {
    "c6": (te.Unit(), GRIDS, CHECKS),
    "saw": (
        te.Unit(r_g_ohm=2.2e3),
        {
            "coarse": (tuple(np.linspace(-14.0, -10.0, 5)), tuple(np.geomspace(0.002e6, 0.8e6, 7))),
            "fine": (tuple(np.linspace(-14.0, -10.0, 9)), tuple(np.geomspace(0.002e6, 0.8e6, 13))),
        },
        (
            (-12.0, 0.003e6),
            (-12.0, 0.01e6),
            (-12.0, 0.05e6),
            (-12.0, 0.3e6),
            (-12.0, 0.6e6),
            (-11.3, 0.02e6),
            (-13.1, 0.15e6),
            (-10.5, 0.4e6),
        ),
    ),
}


def reference(args) -> dict:
    unit, v_g, s, seconds = args
    v = te.run_unit(unit, v_g, s, seconds, oscillate=True)
    return {"out": es.band_limit_ref(v["out"]), "wall_s": v["wall_s"]}


def circuitsim_run(args) -> dict:
    """The unit at a quality: the tube itself (`tables` None) or K."""
    from varimu.sim import fast, io

    unit, v_g, s, seconds, quality, tables = args
    st = dataclasses.replace(
        io.TransientSettings.from_sim_settings(engine="circuitsim", quality=quality),
        full_scale_volts_peak=1.0,
        settle_s=0.0,
    )
    ir = te.unit_ir(unit, v_g, s, oscillate=True, k=tables)
    stats: dict = {}
    t0 = time.perf_counter()
    res = fast.run_transient(ir, np.zeros(int(seconds * te.FS)), settings=st, stats=stats)
    return {
        "out": np.asarray(res.vectors["v(out)"]),
        "wall_s": res.wall_s,
        "total_s": time.perf_counter() - t0,
        "events": stats.get("events", 0),
        "late": stats.get("late_events", 0),
        "latched": stats.get("latched_events", 0),
    }


def metrics(y: np.ndarray, f0: float) -> dict:
    y = y[int(0.1 * te.FS) :]
    m = es.spectrum_metrics(y, te.FS, f0)
    m["jitter_cents"] = es.jitter_cents(y, te.FS)
    m["mean_v"] = float(np.mean(y))
    m["ptp_v"] = float(np.ptp(y))
    return m


def compare(y: np.ndarray, mr: dict, f0: float) -> dict:
    m = metrics(y, f0)
    n = min(len(m["levels_db"]), len(mr["levels_db"]))
    dl = np.array(m["levels_db"][:n]) - np.array(mr["levels_db"][:n])
    within = np.array(mr["levels_db"][:n]) > -60
    return {
        "cents": float(1200 * np.log2(m["f0_hz"] / mr["f0_hz"])),
        "jitter_cents": m["jitter_cents"],
        "harm_err_max_db": float(np.max(np.abs(dl[within]))),
        "inharmonic_db": m["inharmonic_db"],
        "worst_spur_dbc": m["worst_spur_dbc"],
        "mean_err_v": m["mean_v"] - mr["mean_v"],
        "ptp_err_v": m["ptp_v"] - mr["ptp_v"],
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--seconds", type=float, default=0.5)
    ap.add_argument("--workers", type=int, default=7)
    ap.add_argument("--grid", choices=sorted(GRIDS), default="fine")
    ap.add_argument("--unit", choices=sorted(UNITS), default="c6")
    ap.add_argument("--timing", action="store_true", help="time the draft runs one at a time")
    ap.add_argument("--write", metavar="NAME", help="save the tables as config/events/NAME.json")
    args = ap.parse_args()
    unit, grids, checks = UNITS[args.unit]
    tables = te.build_tables(unit, *grids[args.grid], workers=args.workers)
    if args.write:
        from varimu.circuit.builder import EVENTS_DIR

        tables.save(EVENTS_DIR / f"{args.write}.json")
        print("wrote", EVENTS_DIR / f"{args.write}.json")
    latched = int(tables.latched.sum())
    print(f"tables {tables.source['key']}: {tables.v_s.shape}, {latched} latched")
    jobs = [(unit, vg, s, args.seconds) for vg, s in checks]
    runs = {
        "direct": [(*j, "draft", None) for j in jobs],
        "k_draft": [(*j, "draft", tables) for j in jobs],
        "k_production": [(*j, "production", tables) for j in jobs],
    }
    with ProcessPoolExecutor(max_workers=args.workers) as ex:
        refs = list(ex.map(reference, jobs))
        if args.timing:
            out = {k: [circuitsim_run(a) for a in v] for k, v in runs.items()}
        else:
            out = {k: list(ex.map(circuitsim_run, v)) for k, v in runs.items()}
    rows = []
    import soundfile as sf

    adir = OUT / "audio" / "k_unit"
    adir.mkdir(parents=True, exist_ok=True)
    for n, ((_, vg, s, sec), r) in enumerate(zip(jobs, refs, strict=True)):
        em = te.Emulator(tables, vg, s)
        k = em.run(int(sec * te.FS))
        y = r["out"][int(0.1 * te.FS) :]
        ev = es.events(y, te.FS)
        f0 = te.FS / np.mean(np.diff([a for a, _ in ev]))
        mr = metrics(r["out"], f0)
        row = {
            "v_g": vg,
            "slope_v_us": s / 1e6,
            "f_hz": mr["f0_hz"],
            "ref_floor_db": mr["inharmonic_db"],
            "ref_mean_v": mr["mean_v"],
            "ref_ptp_v": mr["ptp_v"],
            "k": {**compare(k, mr, f0), "events": em.events, "late": em.late},
        }
        audio = {"reference": r["out"], "k": k}
        for name, res in ((name, out[name][n]) for name in runs):
            row[name] = {
                **compare(res["out"], mr, f0),
                "events": res["events"],
                "late": res["late"],
                "latched": res["latched"],
                "wall_per_audio_s": res["wall_s"] / sec,
            }
            audio[name] = res["out"]
        # circuitsim's K against Python's: the pitch (sample by sample, a few tenths of a
        # cent drift the phase apart within the window)
        row["k_draft"]["vs_emulator_cents"] = row["k_draft"]["cents"] - row["k"]["cents"]
        rows.append(row)
        tag = f"vg{vg:+.1f}_s{s / 1e6:.3f}"
        for name, yy in audio.items():
            z = yy[int(0.1 * te.FS) :] - np.mean(yy[int(0.1 * te.FS) :])
            sf.write(adir / f"{tag}_{name}.wav", (0.25 * z / 60.0).astype(np.float32), te.FS,
                     subtype="FLOAT")  # fmt: skip

        def fmt(x):
            return (
                f"{x['cents']:+6.2f} c inh {x['inharmonic_db']:6.1f} harm"
                f" {x['harm_err_max_db']:5.2f}"
            )

        print(
            f"vg {vg:+.1f} S {s / 1e6:.3f} V/us f {row['f_hz']:8.1f} Hz"
            f" floor {row['ref_floor_db']:6.1f}"
            f" | K py {fmt(row['k'])} (late {em.late}/{em.events})"
            f" | K draft {fmt(row['k_draft'])} vs py {row['k_draft']['vs_emulator_cents']:+5.2f} c"
            f" ({row['k_draft']['late']}/{row['k_draft']['events']},"
            f" {row['k_draft']['wall_per_audio_s']:.3f}x)"
            f" | K prod {fmt(row['k_production'])}"
            f" | direct {row['direct']['cents']:+7.2f} c inh {row['direct']['inharmonic_db']:6.1f}"
            f" ({row['direct']['wall_per_audio_s']:.3f}x)"
        )
    stem = "k_unit" if args.unit == "c6" else f"k_unit_{args.unit}"
    path = OUT / f"{stem}_{args.grid}.json"
    path.write_text(
        json.dumps({"tables": tables.source, "timing": args.timing, "checks": rows}, indent=1)
    )
    print("wrote", path, adir)


if __name__ == "__main__":
    main()
