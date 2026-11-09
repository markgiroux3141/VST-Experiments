"""The Minimoog oscillator's event tables (technique K, HYBRID_PHYSICS_PLAN.md; varimu/devices/
reset_events.py; docs/MINIMOOG_PLAN.md MM3): the reset's and the rectangle's edge, from reference
runs of their units cut from config/circuits/minimoog_vco.yaml at 12.288 MHz with error control
(the rate the oscillator converges at: reports/minimoog/vco/README.md).

- reset unit: the oscillator less its summers, V01 (the 726's base) driven by a source for the
  slope (the expo itself sinks the current: Q7's collector capacitance and Early effect see the
  reset as in the instrument; an ideal sink there left K 2-7 cents sharp in the circuit), C7
  started with the ramp START_V above the trigger. Slopes up to a 2 ms period run 3.5 periods
  and take the last complete event (the previous one's leftovers in), slower ones their first.
- edge unit: IC8A with R39, R46, PW's divider at 0 V and its load R48 / R49, node `out` driven
  by a ramp through zero at the slope, both ways.

    uv run --extra fast python scripts/minimoog_event_tables.py [--only reset edge] [--check]
        [--workers N]

Writes config/events/minimoog_osc_reset.json and minimoog_osc_edge.json (the circuit's
`exceptions` name them), reports/minimoog/vco/event_tables.json; runs cached in
cache/hybrid/reset/. --check: K on an emulated ramp (a constant current into C7, the reset
from the tables at 96 kHz) against the reference's period at each slope."""

from __future__ import annotations

import argparse
import dataclasses
import json
import math
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np

from varimu.circuit import builder, spec
from varimu.circuit.ir import (
    CircuitIR,
    Element,
    Section,
    VoltageProbe,
    VoltageSource,
)
from varimu.config import CONFIG_DIR, REPO_ROOT
from varimu.devices import reset_events as re_
from varimu.sim import fast, io

sys.path.insert(0, str(REPO_ROOT / "scripts"))

CIRCUIT = CONFIG_DIR / "circuits" / "minimoog_vco.yaml"
OUT = REPO_ROOT / "reports" / "minimoog" / "vco"
RESET_NAME, EDGE_NAME = "minimoog_osc_reset", "minimoog_osc_edge"
RATE = re_.REF_RATE
V_SINK = -10e3
RESET_SLOPES = np.geomspace(4.0, 1.6e5, 62)
# A first-event run's ramp starts this far above the trigger: the curvature's fit (g_s, over
# reset_events.G_FIT_V of ramp) needs that much of it.
START_V = 2.3  # V/s: ~1 Hz .. ~30 kHz of a 5 V ramp
EDGE_SLOPES = np.geomspace(1.0, 3.2e5, 37)
DROP_SECTIONS = ("primary summer", "osc 1 summer")
VT_726 = 1.380649e-23 * (78.4 + 273.15) / 1.602176634e-19  # kT/q at the 726's 78.4 C
I_R = 5e-6  # the expo's reference current (R30 from +10 V into IC6's virtual ground)


def _ir():
    s = spec.load_circuit(CIRCUIT)
    vals = spec.resolve(s, {})
    return builder.build_ir(s, vals, "linear", literal=True), vals


def _settings() -> io.TransientSettings:
    st = io.TransientSettings.from_sim_settings(engine="circuitsim", quality="production")
    return dataclasses.replace(
        st, sample_rate=RATE, oversample=1, full_scale_volts_peak=1.0, settle_s=0.0,
        error_abstol=1e-5, error_reltol=1e-5, newton_reltol=1e-7, newton_vntol=1e-7,
    )  # fmt: skip


def _el(ir, name: str) -> Element:
    return next(e for e in ir.elements() if e.name == name)


def reset_unit(slope: float) -> tuple[CircuitIR, dict]:
    """The reset unit at a ramp slope (V/s): its IR and what the extraction needs."""
    ir, vals = _ir()
    c7 = float(vals["c7_f"])
    cgd = float(vals["j_reset_cgd_f"])
    r31 = _el(ir, "R31").r_ohm
    i_c = slope * (c7 + cgd)
    d0 = START_V + i_c * r31  # the ramp START_V above the trigger
    keep = []
    for sec in ir.sections:
        if sec.title in DROP_SECTIONS:
            continue
        els = tuple(
            dataclasses.replace(e, v0_v=5.0 - d0) if e.name == "C7" else e for e in sec.elements
        )
        keep.append(Section(sec.title, els))
    keep.append(Section("v01", (VoltageSource("VV01", "v01", "0", VT_726 * math.log(i_c / I_R)),)))
    probes = ("ramp", "d", "e", "ref5")
    ir = dataclasses.replace(
        ir, sections=tuple(keep), probes=tuple(VoltageProbe(p) for p in probes), controls=()
    )
    return ir, {"c7": c7, "cgd": cgd, "r31": r31, "i_c": i_c}


def run_reset(slope: float) -> dict:
    period = 5.0 / slope
    steady = period < 2e-3
    seconds = (0.3 / slope + 3.5 * period) if steady else ((START_V + 0.1) / slope + 40e-6)
    ir, k = reset_unit(slope)
    n = int(seconds * RATE)
    t0 = time.perf_counter()
    r = fast.run_transient(ir, np.zeros(n), settings=_settings())
    v = {p: np.asarray(r.vectors[f"v({p})"]) for p in ("ramp", "d", "e", "ref5")}
    # the injected current per sample: charge into d (C7's and the off Q4's Cgd's) plus what
    # left through R31, per sample's time
    dq = k["c7"] * np.diff(v["d"] - v["ref5"]) + k["cgd"] * np.diff(v["d"])
    i_r31 = 0.5 * ((v["d"] - v["e"])[:-1] + (v["d"] - v["e"])[1:]) / k["r31"]
    i_ev = np.append(dq * RATE + i_r31, 0.0)
    e = re_.reset_event({"i_ev": i_ev, "sense": v["ramp"]}, RATE, k["c7"] + k["cgd"], steady)
    if e is None:
        raise RuntimeError(f"no complete reset at {slope:g} V/s")
    # the reference's own period at this slope (steady runs: between its starts)
    starts = np.where((i_ev[:-1] < re_.I_START_A) & (i_ev[1:] >= re_.I_START_A))[0]
    e["period_s"] = float(np.diff(starts[-3:]).mean() / RATE) if len(starts) >= 3 else None
    e["wall_s"] = time.perf_counter() - t0
    e["slope_set"] = slope
    return e


def edge_unit() -> CircuitIR:
    ir, _ = _ir()
    names = {"R39", "R46", "R47", "R45", "C14", "R48", "R49", "VP", "VN", "VPW", "DCL", "QO"}
    els = [e for e in ir.elements() if e.name in names or e.name.upper().startswith(
        ("RIC8A", "GIC8A", "CIC8A", "DIC8A", "VIC8A", "QIC8A", "RQIC8A", "CQIC8A"))]  # fmt: skip
    return dataclasses.replace(
        ir, input_node="out", sections=(Section("edge", tuple(els)),),
        probes=tuple(VoltageProbe(p) for p in ("n11", "n12", "rc")), controls=(),
    )  # fmt: skip


def run_edge(slope: float, direction: int) -> dict:
    ir = edge_unit()
    _, vals = _ir()
    pre, move, lead = 20e-6, 10e-6, 20e-6
    # after the crossing the comparator's internal node slews at ~2 pi GBW times the growing
    # overdrive: ~100 us to switch at 1 V/s
    n = int((pre + move + lead + 120e-6 + 300e-6 / math.sqrt(slope)) * RATE)
    t = np.arange(n) / RATE
    sign = -1.0 if direction == 0 else 1.0  # on: the input falling through 0
    # centred on the direction's switching point: off -> on as `out` falls through ~0; on ->
    # off as it rises through R46's hysteresis (R39 / (R39 + R46) of the collector's swing).
    # Inside that band the comparator is bistable at DC: the run starts held where only the
    # state before the edge is consistent (+20 mV off, -10 mV on), moves in 10 us to `lead`
    # short of the switching point, and ramps at the slope from there.
    r39, r46 = float(vals["r39_ohm"]), float(vals["r46_ohm"])
    hyst = r39 / (r39 + r46) * 10.0
    at = hyst if direction == 1 else 0.0
    x0 = 0.02 if direction == 0 else -0.01
    x1 = at - sign * slope * lead
    t0 = pre + move
    x = np.where(t < pre, x0, np.where(t < t0, x0 + (x1 - x0) * (t - pre) / move,
                                       x1 + sign * slope * (t - t0)))  # fmt: skip
    # held 0.3 V past the switching point (beyond, R46 drags the collector along with it)
    x = np.clip(x, at - 0.3, at + 0.3) if sign < 0 else np.minimum(x, at + 0.3)
    x = np.maximum(x, min(x0, at - 0.3))
    r = fast.run_transient(ir, x, settings=_settings())
    v = {p: np.asarray(r.vectors[f"v({p})"]) for p in ("n11", "n12", "rc")}
    r_load = float(vals["r48_ohm"]) + float(vals["r49_ohm"])
    # the collector's current into its load R48 / R49 (R46's ~2 uA, which follows the input,
    # stays the circuit's: in an events build it moves the collector node by ~0.35 %)
    i_out = -v["rc"] / r_load
    e = re_.edge_event({"diff": v["n11"] - v["n12"], "i_out": i_out}, RATE, direction)
    if e is None:
        raise RuntimeError(f"no edge at {slope:g} V/s, direction {direction}")
    e["slope_set"] = slope
    return e


def emulate_period(t: re_.ResetTables, slope: float, c_f: float, fs: float = 96000.0) -> float:
    """K on an ideal ramp: a constant current out of C, the resets from the tables, the sensed
    ramp the capacitor's voltage; its mean period from the falling crossings of the ramp's
    middle (interpolated), past the first two."""
    run = re_.ResetRun(t, 1.0 / fs)
    i_c = slope * c_f
    h = 1.0 / fs
    n = int(max(14 * 5.0 / slope, 0.02) * fs)
    v = np.empty(n)
    v[0] = 4.8
    for k in range(n - 1):
        i = run.sense(v[k])
        v[k + 1] = v[k] + (i - i_c) * h / c_f
    x = run.times[2:]
    if len(x) < 3:
        return float("nan")
    return float((x[-1] - x[0]) / (len(x) - 1) / fs)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--only", nargs="*", default=["reset", "edge"])
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--workers", type=int, default=12)
    args = ap.parse_args()
    import circuitsim

    summary: dict = {}
    if "reset" in args.only:
        with ThreadPoolExecutor(args.workers) as pool:
            evs = list(pool.map(run_reset, RESET_SLOPES))
        evs.sort(key=lambda e: e["slope"])
        _, vals = _ir()
        c_f = float(vals["c7_f"]) + float(vals["j_reset_cgd_f"])
        # The discharging network's conductance is Q7's Early effect, Ic / ratio: the ratio from
        # the first-event runs' curvature fits (clean: nothing before them), ~VAF + Vce. A
        # steady run's window holds the +5 V reference's recovery from the previous reset (C6
        # through IC4A, ~110 us), so its curvature isn't the Early effect: there the fit put the
        # top C 4.7 cents flat at 96 kHz, the ratio within 0.6 cents everywhere.
        clean = [e["slope"] * c_f / e["g_s"] for e in evs
                 if e.get("period_s") is None and e["g_s"] > 0]  # fmt: skip
        ratio = float(np.median(clean))
        print(f"Ic / G: median {ratio:.2f} V over {len(clean)} first-event runs")
        t = re_.ResetTables(
            log_slope=np.log([e["slope"] for e in evs]),
            v_t=np.array([e["v_t"] for e in evs]),
            dead_s=np.array([e["dead_s"] for e in evs]),
            pulses=[e["pulse"] for e in evs],
            g_s=np.array([e["slope"] * c_f / ratio for e in evs]),
            c_f=c_f,
            source={
                "reference": "circuitsim production (esdirk4, error control 1e-5), 12.288 MHz",
                "circuit": "config/circuits/minimoog_vco.yaml (the reset unit: "
                "scripts/minimoog_event_tables.py reset_unit)",
                "circuitsim": circuitsim.SOURCE_HASH,
                "g_s": f"Ic / {ratio:.4f} V (Q7's Early effect: the median of the first-event "
                "runs' curvature fits)",
            },
        )
        re_.save_tables(RESET_NAME, t)
        summary["reset"] = [{k: v for k, v in e.items() if k != "pulse"} for e in evs]
        print(f"reset: {len(evs)} points, wall {sum(e['wall_s'] for e in evs):.0f} s")
    if "edge" in args.only:
        jobs = [(s, d) for d in (0, 1) for s in EDGE_SLOPES]
        with ThreadPoolExecutor(args.workers) as pool:
            evs = list(pool.map(lambda j: run_edge(*j), jobs))
        waves = [[e["wave"] for e in evs[d * len(EDGE_SLOPES):(d + 1) * len(EDGE_SLOPES)]]
                 for d in (0, 1)]  # fmt: skip
        t = re_.EdgeTables(
            log_slope=np.log(EDGE_SLOPES),
            waves=waves,
            source={
                "reference": "circuitsim production (esdirk4, error control 1e-5), 12.288 MHz",
                "circuit": "config/circuits/minimoog_vco.yaml (the edge unit: "
                "scripts/minimoog_event_tables.py edge_unit)",
                "circuitsim": circuitsim.SOURCE_HASH,
            },
        )
        re_.save_tables(EDGE_NAME, t)
        summary["edge"] = [{"slope": e["slope_set"], "levels": e["levels"],
                            "len": len(e["wave"])} for e in evs]  # fmt: skip
        print(f"edge: {len(evs)} runs")
    if args.check:
        t = re_.load_tables(RESET_NAME)
        _, vals = _ir()
        c_f = float(vals["c7_f"]) + float(vals["j_reset_cgd_f"])
        rows = []
        ref = (
            json.loads((OUT / "event_tables.json").read_text())["reset"]
            if (OUT / "event_tables.json").exists() and "reset" not in summary
            else summary["reset"]
        )
        for e in ref:
            if e.get("period_s"):
                p = emulate_period(t, e["slope"], c_f)
                rows.append(
                    {
                        "slope": e["slope"],
                        "ref_period_s": e["period_s"],
                        "k_period_s": p,
                        "cents": 1200 * math.log2(e["period_s"] / p) if p == p else None,
                    }
                )
        summary["check"] = rows
        for r in rows:
            print(f"  S {r['slope']:10.1f} V/s: ref {1 / r['ref_period_s']:9.2f} Hz, "
                  f"K {r['cents'] if r['cents'] is None else round(r['cents'], 2)} c")  # fmt: skip
    path = OUT / "event_tables.json"
    old = json.loads(path.read_text()) if path.exists() else {}
    old.update(summary)
    path.write_text(json.dumps(old, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
