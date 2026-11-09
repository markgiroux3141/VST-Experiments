"""The Minimoog oscillator's reset, studied for HYBRID_PHYSICS_PLAN.md's decision
(docs/MINIMOOG_PLAN.md MM3: is the reset an exception, and which: K's event kernels or M1's
multi-rate island?), as H2
studied the 884's (scripts/thyratron_event_study.py, whose band-limiting and spectral metrics this
reuses). On config/circuits/minimoog_vco.yaml as trimmed (scripts/minimoog_vco_trim.py):

1. The reset's anatomy, at ANATOMY_FS with error control: the comparator's pulse, how long Q4
   conducts, C7's recharge, the dead time (the ramp crossing the comparator's threshold to its
   restart), how completely C7 returns to the +5 V reference, over the keyboard's pitches.
2. Every candidate against the reference (REFERENCE_FS with error control, band-limited to 96 kHz
   by a 120 dB FIR): pitch (cents), cycle-to-cycle jitter, harmonic levels, inharmonic power in
   20 Hz-20 kHz, on the saw, triangle and rectangle; and each one's cost (one job at a time).
   Candidates: the draft (96 kHz, trbdf2, no error control), draft-2x, production (esdirk4 at 2x,
   error control), production at 8x through the renders' decimator, and M1 (the expo, core and
   shapers as a multi-rate island behind the decimating FIR, the summers and rails outside, cut
   at V01: a 100 ohm node whose island draws only Q7's base current) at 8x / 16x / 32x.

    uv run --extra fast python scripts/minimoog_vco_study.py [--only anatomy candidates]
        [--candidates NAME ...] [--points NAME ...]

Writes reports/minimoog/vco/study.json; runs are cached in cache/minimoog/vco/."""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import sys
import time
from pathlib import Path

import numpy as np

from varimu.circuit import builder, spec
from varimu.circuit.ir import Section, VoltageProbe
from varimu.config import CONFIG_DIR, REPO_ROOT
from varimu.sim import fast, io

sys.path.insert(0, str(Path(__file__).resolve().parent))
import minimoog_vco_trim as trim  # noqa: E402
import thyratron_event_study as h2  # noqa: E402

OUT = REPO_ROOT / "reports" / "minimoog" / "vco"
CACHE = REPO_ROOT / "cache" / "minimoog" / "vco"
FS = 96000
REFERENCE_FS = 128 * FS  # 12.288 MHz: scripts/minimoog_vco_trim.py REFERENCE_FS
ANATOMY_FS = 256 * FS  # 40.7 ns a sample
PROBES = ("out", "tri", "rect", "ramp", "d", "ref5", "gate", "cmp")
HEARD = ("out", "tri", "rect")
SKIP_S = 0.02
WINDOW_S = 0.4
# (MIDI note, RANGE position): the low A on 32', 8' and 2', the A two octaves up on 2', the top C.
POINTS = {
    "A 32'": (45, 1),
    "A 8'": (45, 3),
    "A 2'": (45, 5),
    "A+2 2'": (69, 5),
    "C top 2'": (84, 5),
}
CANDIDATES = (
    "draft",
    "draft-2x",
    "production",
    "production-8x",
    "m1-8x",
    "m1-16x",
    "m1-32x",
    "m1-64x",
    "m1-128x",
    "k-draft",
    "k-draft-2x",
    "k-production",
)
SLOW_SECTIONS = ("rails and panel", "primary summer", "osc 1 summer")


def build(note: int, rng: int, probes: tuple[str, ...] = PROBES, events: bool = False):
    s = spec.load_circuit(trim.CIRCUIT)
    # K's candidates the events build, the others (and the reference) the literal circuit
    ir = builder.build_ir(
        s, spec.resolve(s, {"osc_range": rng}), "linear", events=events, literal=not events
    )
    return dataclasses.replace(ir, probes=tuple(VoltageProbe(p) for p in probes))


def island_m1(ir, m: int):
    """The expo, core and shapers at m steps per sample behind the decimating FIR."""
    slow = tuple(e for sec in ir.sections if sec.title in SLOW_SECTIONS for e in sec.elements)
    fast_ = tuple(e for sec in ir.sections if sec.title not in SLOW_SECTIONS for e in sec.elements)
    return dataclasses.replace(
        ir,
        sections=(Section("summers", slow), Section("oscillator", fast_, m, decimate="fir")),
    )


# The live qualities' Newton tolerance for this circuit (the app's panel::Device::newton): the
# draft's 1e-2 V put tens of cents of error on the sensed ramp (23 mV a sample at 440 Hz) and
# broke the triangle's fold.
K_NEWTON = 1e-3


def settings(mode: str) -> io.TransientSettings:
    if mode.startswith("k-"):  # the events build (technique K) at the quality named
        st = settings(mode[2:])
        if mode.startswith("k-draft"):
            st = dataclasses.replace(st, newton_reltol=K_NEWTON, newton_vntol=K_NEWTON)
        return st
    base = dict(full_scale_volts_peak=1.0, settle_s=trim.SETTLE_S)
    prod = io.TransientSettings.from_sim_settings(engine="circuitsim", quality="production")
    if mode == "reference":
        return dataclasses.replace(trim.reference_settings(REFERENCE_FS), full_scale_volts_peak=1.0)
    if mode == "anatomy":
        return dataclasses.replace(trim.reference_settings(ANATOMY_FS), full_scale_volts_peak=1.0)
    if mode == "production":
        return dataclasses.replace(prod, **base)
    if mode == "production-8x":
        return dataclasses.replace(prod, oversample=8, **base)
    if mode.startswith("m1-"):  # the island steps without error control (esdirk4)
        return dataclasses.replace(prod, oversample=1, **base)
    draft = io.TransientSettings.from_sim_settings(engine="circuitsim", quality="draft")
    if mode == "draft":
        return dataclasses.replace(draft, **base)
    if mode == "draft-2x":
        return dataclasses.replace(draft, host_rate=48000, oversample=2, **base)
    raise ValueError(mode)


def key(job: dict) -> str:
    h = hashlib.sha256()
    for p in (trim.CIRCUIT, trim.KEYBOARD, CONFIG_DIR / "components" / "versions.lock"):
        h.update(p.read_bytes())
    for p in sorted((REPO_ROOT / "varimu" / "circuit").glob("*.py")):
        h.update(p.read_bytes())
    try:
        import circuitsim

        h.update(circuitsim.SOURCE_HASH.encode())
    except ImportError:
        pass
    h.update(json.dumps(job, sort_keys=True).encode())
    if job["mode"].startswith("k-"):  # the event tables the build reads
        for p in sorted((CONFIG_DIR / "events").glob("minimoog_osc_*.json")):
            h.update(p.read_bytes())
    return h.hexdigest()[:16]


def run(job: dict) -> dict:
    """{'v': {probe: samples}, 'rate', 'wall_s'} for one (point, mode, seconds), cached."""
    path = CACHE / f"{key(job)}.npz"
    if path.exists():
        z = np.load(path, allow_pickle=True)
        meta = json.loads(str(z["meta"]))
        return {**meta, "v": {k[2:]: z[k] for k in z.files if k.startswith("v_")}}
    note, rng = job["note"], job["range"]
    k = job["mode"].startswith("k-")
    ir = build(note, rng, PROBES if job["mode"] == "anatomy" else (*HEARD, "ramp"), events=k)
    if job["mode"].startswith("m1-"):
        ir = island_m1(ir, int(job["mode"][3:-1]))
    st = settings(job["mode"])
    n = int(job["seconds"] * st.sample_rate)
    t0 = time.perf_counter()
    try:
        r = fast.run_transient(
            ir, np.zeros(n), settings=st, controls={"key": np.full(n, trim.keyboard_volts(note))}
        )
    except fast.SimulationFailed as e:
        return {"error": str(e), "wall_s": time.perf_counter() - t0}
    wall = time.perf_counter() - t0
    v = {p: np.asarray(r.vectors[f"v({p})"]) for p in PROBES if f"v({p})" in r.vectors}
    meta = {"rate": st.sample_rate, "wall_s": wall, "seconds": job["seconds"]}
    CACHE.mkdir(parents=True, exist_ok=True)
    np.savez(path, meta=json.dumps(meta), **{f"v_{k}": x for k, x in v.items()})
    return {**meta, "v": v}


# --- 1. The reset's anatomy ----------------------------------------------------------------


def anatomy(note: int, rng: int) -> dict:
    f = trim.target_hz(note, rng)
    r = run({"note": note, "range": rng, "mode": "anatomy", "seconds": min(3.5 / f, 0.13)})
    rate, v = r["rate"], r["v"]
    ramp, d, cmp_, ref5 = v["ramp"], v["d"], v["cmp"], v["ref5"]
    # each reset: the comparator's output above 0 V (Q4's gate driven up)
    hi = cmp_ > 0.0
    starts = np.nonzero(hi[1:] & ~hi[:-1])[0] + 1
    ends = np.nonzero(~hi[1:] & hi[:-1])[0] + 1
    rows = []
    for a in starts[1:]:
        b = ends[ends > a]
        if len(b) == 0:
            break
        b = b[0]
        # the ramp's threshold crossing before the pulse (it falls through ~0 V)
        k0 = a - int(np.argmax(ramp[a::-1] > 0.0))
        # its restart: the ramp's top after the pulse
        w = int(5e-6 * rate)
        top = b + int(np.argmax(ramp[b : b + w]))
        rows.append(
            {
                "pulse_s": (b - a) / rate,
                "dead_s": (top - k0) / rate,
                "d_peak_v": float(d[a : b + w].max()),
                "ref5_v": float(ref5[a]),
                "d_short_v": float(ref5[a] - d[a : b + w].max()),
                "ramp_top_v": float(ramp[top]),
                "cmp_peak_v": float(cmp_[a:b].max()),
            }
        )
    if not rows:
        return {"resets": 0}
    out = {k: float(np.mean([r_[k] for r_ in rows])) for k in rows[0]}
    out["ramp_top_spread_v"] = float(np.std([r_["ramp_top_v"] for r_ in rows]))
    out["resets"] = len(rows)
    out["f_hz"] = f
    out["dead_share"] = out["dead_s"] * f
    return out


# --- 2. Candidates against the reference -----------------------------------------------------


def ramp_pitch(r: dict) -> dict:
    """The oscillator's pitch and period jitter from the ramp's falling crossings of 2.5 V (the
    slow side: the reset's band-limited edge rings, so h2's rising-crossing jitter can't be
    used here); `oscillates` False where the ramp never crosses (the stall)."""
    rate = r["rate"]
    y = r["v"]["ramp"][int(SKIP_S * rate) :]
    t = trim.falling_crossings(y, 2.5) / rate
    if len(t) < 3:
        return {"oscillates": False, "ramp_min_v": float(y.min()), "ramp_max_v": float(y.max())}
    per = np.diff(t)
    c = 1200 * np.log2(per / per.mean())
    return {
        "oscillates": True,
        "f_hz": float(1 / per.mean()),
        "period_sd_cents": float(c.std()),
        "period_pp_cents": float(c.max() - c.min()),
        "ramp_min_v": float(y.min()),
        "ramp_max_v": float(y.max()),
    }


def heard(r: dict, f0: float) -> dict:
    """Per heard output at 96 kHz: spectral metrics and jitter (h2's)."""
    rate = r["rate"]
    k = rate // FS
    out = {}
    for p in HEARD:
        y = r["v"][p][int(SKIP_S * rate) :]
        y96 = h2.band_limit(y, k) if k > 1 else y
        m = h2.spectrum_metrics(y96, FS, f0)
        m["jitter_cents"] = h2.jitter_cents(y96, FS) if p != "rect" else None
        out[p] = m
    return out


def compare(c: dict, ref: dict) -> dict:
    out = {}
    for p in HEARD:
        a, b = c[p], ref[p]
        n = min(len(a["levels_db"]), len(b["levels_db"]))
        dl = np.array(a["levels_db"][:n]) - np.array(b["levels_db"][:n])
        within = np.array(b["levels_db"][:n]) > -60
        out[p] = {
            "cents": float(1200 * np.log2(a["f0_hz"] / b["f0_hz"])),
            "jitter_cents": a.get("jitter_cents"),
            "harm_err_max_db": float(np.abs(dl[within]).max()) if within.any() else None,
            "inharmonic_db": a["inharmonic_db"],
            "worst_spur_dbc": a["worst_spur_dbc"],
            "worst_spur_hz": a["worst_spur_hz"],
        }
    return out


def prerun(jobs: list[dict], workers: int) -> None:
    """Fill the cache with `jobs` on `workers` threads (circuitsim releases the GIL); their
    wall times are then not one job's: `cost` times the candidates alone."""
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(workers) as pool:
        for job, r in zip(jobs, pool.map(run, jobs), strict=True):
            print(
                f"  ran {job}: {'error' if 'error' in r else round(r['wall_s'], 1)} s", flush=True
            )


def candidates(points: dict, names: list[str], workers: int = 1, log=print) -> dict:
    res = {}
    seconds = SKIP_S + WINDOW_S
    if workers > 1:
        prerun(
            [{"note": n, "range": r, "mode": m, "seconds": seconds}
             for n, r in points.values() for m in ("reference", *names)],
            workers,
        )  # fmt: skip
    for pname, (note, rng) in points.items():
        f0 = trim.target_hz(note, rng)
        ref = run({"note": note, "range": rng, "mode": "reference", "seconds": seconds})
        rsig = heard(ref, f0)
        rp = ramp_pitch(ref)
        row = {
            "reference": {
                **rp,
                "f0_hz": rsig["out"]["f0_hz"],
                "inharmonic_db": {p: rsig[p]["inharmonic_db"] for p in HEARD},
                "x_real_time": ref["wall_s"] / seconds,
            }
        }
        for c in names:
            r = run({"note": note, "range": rng, "mode": c, "seconds": seconds})
            if "error" in r:
                row[c] = {"error": r["error"]}
                continue
            cp = ramp_pitch(r)
            row[c] = {**cp, "x_real_time_parallel": r["wall_s"] / seconds}
            if cp["oscillates"]:
                row[c]["cents"] = float(1200 * np.log2(cp["f_hz"] / rp["f_hz"]))
                row[c]["heard"] = compare(heard(r, f0), rsig)
            log(f"{pname} {c}: " + json.dumps(_brief(row[c])))
        res[pname] = row
    return res


def cost(points: dict, names: list[str], seconds: float = 0.2) -> dict:
    """Each candidate's wall time per second of audio, one job at a time (uncached)."""
    out = {}
    for pname, (note, rng) in points.items():
        ir0 = build(note, rng)
        irk = build(note, rng, events=True)
        kv = trim.keyboard_volts(note)
        row = {}
        for c in names:
            ir = island_m1(ir0, int(c[3:-1])) if c.startswith("m1-") else ir0
            ir = irk if c.startswith("k-") else ir
            st = settings(c)
            n = int(seconds * st.sample_rate)
            t0 = time.perf_counter()
            try:
                fast.run_transient(ir, np.zeros(n), settings=st, controls={"key": np.full(n, kv)})
                row[c] = (time.perf_counter() - t0) / seconds
            except fast.SimulationFailed as e:
                row[c] = str(e)
            print(f"cost {pname} {c}: {row[c]}", flush=True)
        out[pname] = row
    return out


def _brief(c: dict) -> dict:
    if "error" in c or not c["oscillates"]:
        return {k: v for k, v in c.items() if k != "heard"}
    return {
        "cents": round(c["cents"], 2),
        "period_sd_cents": round(c["period_sd_cents"], 2),
        "inharm_saw_db": round(c["heard"]["out"]["inharmonic_db"], 1),
        "ramp_max_v": round(c["ramp_max_v"], 2),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--only", nargs="*", default=["anatomy", "candidates"])
    ap.add_argument("--candidates", nargs="*", default=list(CANDIDATES))
    ap.add_argument("--points", nargs="*", default=list(POINTS))
    ap.add_argument("--workers", type=int, default=1)
    args = ap.parse_args()
    points = {k: POINTS[k] for k in args.points}
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / "study.json"
    summary = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    if "anatomy" in args.only:
        from concurrent.futures import ThreadPoolExecutor

        with ThreadPoolExecutor(max(1, min(args.workers, len(points)))) as pool:
            summary["anatomy"] = dict(
                zip(points, pool.map(lambda p: anatomy(*p), points.values()), strict=True)
            )
        print(json.dumps(summary["anatomy"], indent=1))
    if "candidates" in args.only:
        summary.setdefault("candidates", {}).update(
            candidates(points, args.candidates, args.workers)
        )
    if "cost" in args.only:
        summary.setdefault("cost_x_real_time", {}).update(cost(points, args.candidates))
    path.write_text(json.dumps(summary, indent=1), encoding="utf-8")
    print(f"wrote {path}")


if __name__ == "__main__":
    main()
