"""The multitrack medium in the engine (docs/PERIOD_GEAR_BACKLOG.md, PG1: MT3's crosstalk and
MT4's Sel-Sync) on the deck's heads: the 351's heads (config/circuits/ampex_351.yaml: gaps,
pole faces, the heads' fields per ampere) on a 70 mil track of SCOTCH202@1 at 15 ips, the
production medium's numerics (varimu.circuit.parts' TAPE_*), circuitsim's stream.

A low tone on a track; at each frequency, the EMFs at the tone:
- crosstalk: what a head beside the track reads over the track's own head (the engine's
  `CrossPickup` with the four-track pickup the deck uses) against the model it was fitted
  as (`varimu.multitrack.crosstalk.Crosstalk.playback`, playback terms only: the record
  heads' couplings are the deck circuit's);
- Sel-Sync: the record head's reading over the repro head's (both heads read the same
  stretch of tape), against the heads' spectra; and the record head's reading alone re
  1 kHz, its own response (the playback EQ follows it in the deck: the monitor's sound).

    uv run --extra fast python scripts/multitrack_engine_study.py
-> reports/multitrack/engine/{engine.json,engine.png}
"""

from __future__ import annotations

import json
import math
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np

from varimu.circuit import parts
from varimu.config import REPO_ROOT
from varimu.devices import library
from varimu.devices.tape import CrossPickup, HeadGeometry, head_hx_spectrum
from varimu.devices.tape_machine import TapeMachineSpec, stream_params
from varimu.multitrack import crosstalk as x

OUT = REPO_ROOT / "reports" / "multitrack" / "engine"
FS = 96_000.0
V = 0.381
OE = 1000.0 / (4.0 * math.pi)
TRACK = 70 * x.MIL
#: The 351's heads (config/circuits/ampex_351.yaml).
REC_GAP, REP_GAP, POLE, RELAX = 51e-6, 6.35e-6, 1.5e-3, 5.5e-3
REC_H_PER_A, REP_H_PER_A = 8.0e6, 2.46e7
#: The record field's bias for this study: tape_test.yaml's 59,894 A/m (the first print's
#: alignment on Scotch 111) times 202's Hc over 111's (315 / 270): near the optimum (the
#: ratios measured here are of one recorded pattern, read by two heads: the bias hardly
#: matters).
BIAS_A_M = 59894.5 * 315.0 / 270.0
FREQS = (
    31.5,
    40,
    50,
    63,
    80,
    100,
    125,
    160,
    200,
    250,
    315,
    500,
    1000,
    2000,
    4000,
    6000,
    7000,
    7470,
    8000,
    10000,
    12500,
    16000,
)


def spec() -> TapeMachineSpec:
    return TapeMachineSpec(
        speed_m_s=V,
        rec_gap_m=REC_GAP,
        rep_gap_m=REP_GAP,
        pole_m=POLE,
        relax_m=RELAX,
        track_m=TRACK,
        layers=parts.TAPE_LAYERS,
        ds_m=V / (100e3 * parts.TAPE_CELLS_PER_BIAS_WAVELENGTH),
        table_step=parts.TAPE_TABLE_STEP,
        demag_iterations=parts.TAPE_DEMAG_ITERATIONS,
        demag_tol=parts.TAPE_DEMAG_TOL,
        flutter=False,
    )


def pickup() -> tuple[CrossPickup, x.Crosstalk]:
    fit = json.loads((REPO_ROOT / "reports" / "multitrack" / "crosstalk" / "fit.json").read_text())
    p = fit["four_track"]["params"]
    head = HeadGeometry(REP_GAP, POLE, RELAX)
    c = x.Crosstalk(head, p["unshielded"], p["contour_width_ratio"], p["core"], 1.0, 1.0)
    fmt = x.FOUR_TRACK_HALF_INCH
    return CrossPickup(fmt.pitch_m, c.unshielded, c.contour_width_m(fmt), c.core), c


def tone_run(f: float, params: str) -> dict:
    import circuitsim

    lag = spec().head_distance_m / V
    periods = max(8, round(0.06 * f))
    n_meas = int(round(FS * periods / f))
    start = lag + 0.03
    n = int((start + periods / f) * FS) + 64
    t = np.arange(n) / FS
    h = 120 * OE * np.sin(2 * math.pi * f * t) * np.clip(t / 0.01, 0.0, 1.0)
    r = circuitsim.tape_stream_run(params, FS, h, readouts=True)
    k0 = int(start * FS)
    tt = np.arange(k0, k0 + n_meas) / FS
    ph = np.exp(-2j * math.pi * f * tt)

    def at(y):
        return complex(np.mean(np.asarray(y)[k0 : k0 + n_meas] * ph))

    return {k: at(r[k]) for k in ("emf", "cross", "sync")}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    sp = spec()
    tape = library.load_tape("SCOTCH202@1")
    xp, model = pickup()
    params = json.dumps(
        stream_params(
            sp,
            tape,
            BIAS_A_M,
            rep_h_per_a=REP_H_PER_A,
            crosstalk=("deck", 1, xp),
            sync_h_per_a=REC_H_PER_A,
        )
    )
    t0 = time.time()
    with ThreadPoolExecutor(4) as ex:
        res = list(ex.map(lambda f: tone_run(f, params), FREQS))
    wall = time.time() - t0
    f = np.array(FREQS, float)
    own = np.array([r["emf"] for r in res])
    cross = np.array([r["cross"] for r in res])
    sync = np.array([r["sync"] for r in res])
    xt_engine = 20 * np.log10(np.abs(cross / own))
    fmt = x.FOUR_TRACK_HALF_INCH
    xt_model = 20 * np.log10(np.abs(model.playback(f, V, fmt, fmt.pitch_m)))
    k = 2 * math.pi * f / V
    rec, rep = HeadGeometry(REC_GAP, POLE, RELAX), HeadGeometry(REP_GAP, POLE, RELAX)
    ratio_formula = (REC_H_PER_A * head_hx_spectrum(rec, k, 0.0)) / (
        REP_H_PER_A * head_hx_spectrum(rep, k, 0.0)
    )
    ratio_engine = sync / own
    i1k = FREQS.index(1000)
    sync_db = 20 * np.log10(np.abs(sync) / abs(sync[i1k]))
    own_db = 20 * np.log10(np.abs(own) / abs(own[i1k]))
    rel_db = 20 * np.log10(np.abs(ratio_engine) / abs(ratio_engine[i1k]))
    report = {
        "setup": {
            "fs_hz": FS,
            "speed_m_s": V,
            "track_m": TRACK,
            "tape": "SCOTCH202@1",
            "heads": {"rec_gap_m": REC_GAP, "rep_gap_m": REP_GAP, "pole_m": POLE, "relax_m": RELAX},
            "pickup": {
                "pitch_m": xp.pitch_m,
                "unshielded": xp.unshielded,
                "contour_width_m": xp.contour_width_m,
                "core": xp.core,
            },
            "bias_a_m": BIAS_A_M,
            "wall_s": wall,
        },
        "crosstalk_db": {
            f"{fr:g}": {"engine": float(a), "model": float(b), "miss": float(a - b)}
            for fr, a, b in zip(FREQS, xt_engine, xt_model, strict=True)
        },
        "crosstalk_worst_miss_db": float(np.max(np.abs(xt_engine - xt_model))),
        "sync_over_repro": {
            f"{fr:g}": {
                "engine_db": float(20 * np.log10(abs(e))),
                "formula_db": float(20 * np.log10(abs(q))),
                "miss_db": float(20 * np.log10(abs(e / q))),
            }
            for fr, e, q in zip(FREQS, ratio_engine, ratio_formula, strict=True)
        },
        "sync_over_repro_worst_miss_db": float(
            np.max(np.abs(20 * np.log10(np.abs(ratio_engine / ratio_formula))))
        ),
        "sync_response_re_1k_db": {
            f"{fr:g}": float(v) for fr, v in zip(FREQS, sync_db, strict=True)
        },
        "repro_response_re_1k_db": {
            f"{fr:g}": float(v) for fr, v in zip(FREQS, own_db, strict=True)
        },
        "sync_re_repro_re_1k_db": {
            f"{fr:g}": float(v) for fr, v in zip(FREQS, rel_db, strict=True)
        },
        "sync_gap_null_hz": V / REC_GAP,
    }
    (OUT / "engine.json").write_text(json.dumps(report, indent=1), encoding="utf-8")

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(1, 2, figsize=(12, 5))
    dense = np.geomspace(25, 18000, 600)
    ax[0].semilogx(
        dense,
        20 * np.log10(np.abs(model.playback(dense, V, fmt, fmt.pitch_m))),
        color="C0",
        lw=1.2,
        label="model (fitted, 4 tracks), playback terms",
    )
    ax[0].semilogx(f, xt_engine, "o", color="C3", label="engine: a neighbour's head over its own")
    ax[0].set(xlabel="Hz", ylabel="dB", title="Crosstalk at playback, 15 ips", ylim=(-90, -20))
    ax[0].grid(True, which="both", alpha=0.3)
    ax[0].legend(fontsize=8)
    ax[1].semilogx(f, own_db, "o-", label="repro head (6.35 um)")
    ax[1].semilogx(f, sync_db, "s-", label="record head in Sel-Sync (51 um)")
    ax[1].semilogx(f, rel_db, "x:", label="record over repro")
    ax[1].axvline(V / REC_GAP, color="0.5", ls=":", lw=1)
    ax[1].set(
        xlabel="Hz",
        ylabel="dB re 1 kHz",
        title="Head EMF at 15 ips (before the EQ)",
        ylim=(-50, 25),
    )
    ax[1].grid(True, which="both", alpha=0.3)
    ax[1].legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(OUT / "engine.png", dpi=120)
    print(json.dumps({k: v for k, v in report.items() if not isinstance(v, dict)}, indent=1))
    print("sync re repro re 1k:", json.dumps(report["sync_re_repro_re_1k_db"]))


if __name__ == "__main__":
    main()
