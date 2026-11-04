"""A circuit's tape reduced for the live qualities (docs/DELAY_PLAN.md, "The reduced
medium"; varimu.delay.reduced): its tape part's own medium (the IR's `TapeMedium`, the
numerics the builder chose), recorded by the real kernel over a grid of bias amplitudes
(BIAS as a knob): per bias and layer a table of M_x against a constant field and the
apertures, and the demagnetization correction D(k) measured against the full stream on
low-level noise (it depends on the bias: a shallower recording loses less to its own field).

    uv run --extra fast python scripts/tape_reduction.py [--circuit ampex_351] [--name NAME]
        [--set k=v ...] [--workers 4]

Writes config/tape_reductions/<name>.json (default name: the circuit's). `--set` picks the
tape part a switch puts in (the 351's 7-1/2 ips tape: `--set speed=0 --name ampex_351_lo`).

The bias: the alignment's (reports/tape/ampex_351_alignment.json: the record head's bias
current, rms, as the aligned machine draws it) times the head's field per ampere is the
file's own (`bias_a_m`). The bias map is BIAS ADJUST's (5C13) capacitance against that
current, measured on the literal machine: the alignment's sweep (15-78 pF) and three more
runs to the trimmer's 130 pF (cached in cache/tape/). The grid spans the map's currents,
2^(1/3) apart; a tape part's `reduction_bias: bias_adjust_f` plays the reduction at the
control's setting through the map. The file records the medium's values it was made for
(`varimu.delay.reduced.MEDIUM_KEYS`); a builder refuses it for a tape part whose medium
differs (rerun this then).
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np

from varimu.circuit import builder, spec
from varimu.circuit import ir as irm
from varimu.config import CONFIG_DIR, REPO_ROOT
from varimu.delay import reduced as rd
from varimu.devices.library import load_tape
from varimu.sim.io import TransientSettings

OUT = CONFIG_DIR / "tape_reductions"
ALIGNMENT = REPO_ROOT / "reports" / "tape" / "ampex_351_alignment.json"
MAP_CACHE = REPO_ROOT / "cache" / "tape"
#: The coarse cells (15 kHz at 15 ips is 25 um), the tables' span (checked to +24 dB over the
#: operating level against the full stream: scripts/delay_live_study.py) and points, the noise's
#: level for D(k) (dB re the aligned operating level's field: well inside the linear part) and
#: its band (to 40 kHz: 9.5 um at 15 ips, so VARISPEED's slowest tape, 2/3 of nominal, still
#: reads D(k) measured up to its 16 kHz band; 20 kHz left the top octave held there).
DS_M = 2e-6
H_MAX_A_M = 200e3  # past DRIVE's +23 dB with the record pre-emphasis (DELAY_PLAN.md, DRIVE)
POINTS = 481
DEMAG_LEVEL_DB = -12.0
DEMAG_BAND_HZ = 40e3
#: BIAS ADJUST beyond the alignment's sweep (to the trimmer's end, sch 5C13 15-130 pF) and the
#: bias grid's spacing.
MAP_EXTRA_F = (90e-12, 110e-12, 130e-12)
GRID_RATIO = 2 ** (1 / 3)
BIAS_CONTROL = "bias_adjust_f"


def note(m: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)


def bias_map(al: dict) -> tuple[list[float], list[float]]:
    """BIAS ADJUST (F) against the record head's bias (mA rms): the alignment's sweep plus
    MAP_EXTRA_F measured on the literal machine as the alignment measures (1 kHz at -10 dB,
    the BIAS meter across 5R24), cached by the alignment's key."""
    from varimu.measure import tape_align as ta

    sweep = al["steps"]["bias"]
    xs, ys = list(sweep["sweep_f"]), list(sweep["sweep_bias_ma_rms"])
    path = MAP_CACHE / f"bias_map_{al['key']}.json"
    if path.exists():
        extra = json.loads(path.read_text())
    else:
        b = ta.Bench.load()
        o = {"rep_eq_hi": al["overrides"]["rep_eq_hi"], "record_level": 0.85}
        o["playback_level"] = 0.3  # the alignment's bias step's settings (tape_align.align)
        x = ta.tone(b, [1000.0], ta.BIAS_LEVEL_DB)
        runs = ta.run_many(b, [({**o, BIAS_CONTROL: c}, x) for c in MAP_EXTRA_F], note)
        r_cal = spec.resolve(b.circuit)["r_bias_cal_ohm"]
        extra = [
            [c, ta.bias_rms(ta.window(b, v["v(rbc)"]), b.fs, r_cal) * 1e3]
            for c, v in zip(MAP_EXTRA_F, runs, strict=True)
        ]
        MAP_CACHE.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(extra))
    for c, ma in extra:
        xs.append(c)
        ys.append(ma)
    order = np.argsort(xs)
    return [float(xs[i]) for i in order], [float(ys[i]) for i in order]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--circuit", default="ampex_351")
    ap.add_argument("--name")
    ap.add_argument("--set", nargs="*", default=[], metavar="K=V")
    ap.add_argument("--workers", type=int, default=4, help="D(k)s measured at once")
    a = ap.parse_args()
    sets = {k: float(v) for k, v in (x.split("=", 1) for x in a.set)}
    c = spec.load_circuit(spec.circuit_path(a.circuit))
    p = spec.resolve(c, sets)
    ir = builder.build(c, sets, cores="linear", noise=False).ir
    tapes = [e for s in ir.sections for e in s.elements if isinstance(e, irm.Tape)]
    if len(tapes) != 1:
        raise SystemExit(f"{a.circuit}: {len(tapes)} tape parts (one expected)")
    medium = tapes[0].medium
    sp = rd.spec_from_medium(medium)
    tape = load_tape(str(p["tape_model"]))
    al = json.loads(ALIGNMENT.read_text())
    bias_ma = float(al["steps"]["check"]["bias_ma_rms"])
    audio_ma = float(al["steps"]["check"]["record_head_audio_ma_rms"])
    h_per_a = p["rec_h_per_a"]
    hg_bias = rd.bias_hg(bias_ma, h_per_a)
    map_f, map_ma = bias_map(al)
    note(f"bias map: {map_ma[0]:.2f}-{map_ma[-1]:.2f} mA over {map_f[0] * 1e12:.0f}-"
         f"{map_f[-1] * 1e12:.0f} pF")  # fmt: skip
    lo, hi = rd.bias_hg(map_ma[0], h_per_a), rd.bias_hg(map_ma[-1], h_per_a)
    n = math.ceil(math.log(hi / lo) / math.log(GRID_RATIO)) + 1
    grid = np.geomspace(lo, hi, n)
    t0 = time.perf_counter()
    reds = rd.reduce_bias(sp, tape, grid, H_MAX_A_M, POINTS, note=note)
    note(f"tables and apertures at {n} biases in {time.perf_counter() - t0:.0f} s")
    fs = TransientSettings.from_sim_settings(engine="circuitsim").sample_rate
    h_rms = rd.bias_hg(audio_ma, h_per_a) / np.sqrt(2) * 10 ** (DEMAG_LEVEL_DB / 20)
    t0 = time.perf_counter()

    def demag(r):
        return rd.demag_correction(sp, tape, r, fs, DS_M, h_rms, band_hz=DEMAG_BAND_HZ)

    with ThreadPoolExecutor(a.workers) as ex:
        ds = list(ex.map(demag, reds.points))
    k = ds[0][0]
    if any(not np.array_equal(kk, k) for kk, _ in ds):
        raise RuntimeError("the D(k)s' wavenumbers differ between biases")
    note(f"D(k) at {n} biases in {time.perf_counter() - t0:.0f} s")
    name = a.name or a.circuit
    doc = {
        "source": (
            f"scripts/tape_reduction.py on config/circuits/{a.circuit}.yaml's tape part "
            f"{tapes[0].name}{' (' + ' '.join(a.set) + ')' if a.set else ''} "
            f"({p['tape_model']}) over the bias, the aligned bias {bias_ma:.4g} mA rms "
            f"(reports/tape/ampex_351_alignment.json key {al['key']})"
        ),
        "tape": str(p["tape_model"]),
        "medium": {key: getattr(medium, key) for key in rd.MEDIUM_KEYS},
        "bias_a_m": hg_bias,
        "bias_map": {
            "control": BIAS_CONTROL,
            "source": (
                "BIAS ADJUST 5C13 against the record head's bias current on the literal "
                "machine (the alignment's sweep, plus scripts/tape_reduction.py's runs to "
                "130 pF), times rec_h_per_a"
            ),
            "x": map_f,
            "bias_ma_rms": map_ma,
            "bias_a_m": [rd.bias_hg(m, h_per_a) for m in map_ma],
        },
        "ds_m": DS_M,
        "h_a_m": reds.points[0].h_a_m.tolist(),
        "tau0_s": reds.points[0].tau0_s,
        "dt_s": reds.points[0].dt_s,
        "demag_k": k.tolist(),
        "points": [
            {
                "bias_a_m": r.hg_bias,
                "mx": r.mx.tolist(),
                "slope": r.slope.tolist(),
                "ax": r.ax.tolist(),
                "ky": r.ky.tolist(),
                "demag_d": d.tolist(),
            }
            for r, (_, d) in zip(reds.points, ds, strict=True)
        ],
    }
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"{name}.json"
    path.write_text(json.dumps(doc, indent=1), encoding="utf-8")
    note(f"wrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
