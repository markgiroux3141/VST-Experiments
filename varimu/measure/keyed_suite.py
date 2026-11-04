"""The keyed 670's profile (docs/SIDECHAIN_PLAN.md, K1): fairchild_670_keyed.

    report = run(name, genome)     # varimu unit --circuit fairchild_670_keyed --name NAME

A unit is the circuit file with the genome's overrides at its default panel (the stock
670's factory adjustment); the program is a bass tone (BASS_HZ at BASS_DBFS, which keys
nothing at KEY EXT), the key a kick: a decaying sine whose pitch falls from 150 to 50 Hz,
every KICK_PERIOD_S, at a level relative to KEY_REF_DBFS (a steady pattern of kicks whose
rms, as a sine's peak, is -18 dBFS: what the session's key trim sets). Sections:

- screen (varimu.measure.generic's idle check, then the profile's own): KEY INT renders as
  the stock 670 (the same tone through both, the key's kicks at INT's terminated jack:
  within INT_SAME_DB re the signal); KEY EXT keys (a kick KEY_DUCKS_OFFSET_DB above the
  reference ducks the bass by more than KEY_DUCKS_DB, DEPTH fully on);
- ext_load: the program's gain at EXT re INT at a level that hardly compresses (EXT takes
  the pick-off's load off the output);
- duck_curve: the deepest duck of the bass, and the duck 100 ms after the kick, against
  the key's level (KEY_OFFSETS_DB), with the control voltage's swing. Keyed, the 670 is
  feed-forward: no feedback sets a ratio, so the duck goes from nothing to the 6386s'
  cutoff within a few dB of key (DEPTH fully on: no limit);
- depth: the deepest duck per DEPTH (DEPTHS) with the kicks at DEPTH_OFFSETS_DB, and B+'s
  lowest (the clamp's follower draws from it);
- recovery: one kick at the reference level per time constant: the duck's depth and the
  time back to -3 dB and -1 dB (the release: TC5 and TC6 are program dependent), at the
  panel's DEPTH;
- thump: the program silent, the kicks at the reference and 6 dB above, at BALANCE 0.4 /
  0.5 / 0.6: the output's peak (the control voltage moving on the push-pull grids), at the
  panel's DEPTH.

The renders call varimu.sim.fast.run_transient with the key as a control input, uncached:
runner.RenderJob has no control inputs yet (adding them edits varimu/sim, so every
render's cache key; SIDECHAIN_PLAN.md K1). Results: reports/units/<name>/report.json,
duck_curve.png, depth.png, recovery.png.
"""

from __future__ import annotations

import datetime as dt
import json
import time
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import numpy as np

from varimu.circuit import builder, spec
from varimu.config import REPO_ROOT
from varimu.measure import generic
from varimu.sim import fast, runner
from varimu.sim.io import TransientSettings, full_scale

CIRCUIT = "fairchild_670_keyed"
STOCK = "fairchild_670"
REPORT_DIR = REPO_ROOT / "reports" / "units"

BASS_HZ, BASS_DBFS = 110.0, -18.0
KEY_REF_DBFS = -18.0
KICK_PERIOD_S = 0.5
KICK_DECAY_S, KICK_SWEEP_S = 0.12, 0.03
PRE_S = 1.0  # before the first kick (the program's level settles)
CURVE_KICKS = 4
KEY_OFFSETS_DB = (-12.0, -9.0, -6.0, -4.0, -2.0, 0.0, 2.0, 4.0, 6.0)
RECOVERY_S = {1: 2.0, 2: 3.0, 3: 6.0, 4: 10.0, 5: 14.0, 6: 30.0}  # after the kick
THUMP_OFFSETS_DB = (0.0, 6.0)
THUMP_BALANCES = (0.4, 0.5, 0.6)
DEPTHS = (0.0, 0.15, 0.3, 0.45, 0.6, 0.8, 1.0)
DEPTH_OFFSETS_DB = (0.0, 6.0, 12.0)
DEPTH_KICKS = 3
NO_LIMIT = {"key_depth": 1.0}
ENV_BIN_S = 0.005

IDLE_S = 1.0
INT_TONE_HZ, INT_TONE_DBFS, INT_S = 1000.0, -6.0, 1.0
INT_SAME_DB = -100.0
EXT_LOAD_DBFS = -40.0
KEY_DUCKS_OFFSET_DB, KEY_DUCKS_DB = 6.0, -6.0


def _t(seconds: float, fs: int) -> np.ndarray:
    return np.arange(int(round(seconds * fs))) / fs


def sine(f_hz: float, dbfs: float, seconds: float, fs: int) -> np.ndarray:
    """A sine faded in over 50 ms (a core's DC point: varimu's core quirks)."""
    t = _t(seconds, fs)
    return 10 ** (dbfs / 20) * np.sin(2 * np.pi * f_hz * t) * np.minimum(1.0, t / 0.05)


def kick(starts_s, offset_db: float, seconds: float, fs: int) -> np.ndarray:
    """Kicks at `starts_s`, `offset_db` re KEY_REF_DBFS (see the module docs)."""
    t = _t(seconds, fs)
    one_t = _t(KICK_PERIOD_S, fs)
    f = 50.0 + 100.0 * np.exp(-one_t / KICK_SWEEP_S)
    one = np.sin(2 * np.pi * np.cumsum(f) / fs) * np.exp(-one_t / KICK_DECAY_S)
    level = 20 * np.log10(np.sqrt(np.mean(one**2)) * np.sqrt(2))
    one *= 10 ** ((KEY_REF_DBFS + offset_db - level) / 20)
    x = np.zeros(len(t))
    for s0 in starts_s:
        a = int(round(s0 * fs))
        n = min(len(one), len(x) - a)
        x[a : a + n] += one[:n]
    return x


def env_db(y: np.ndarray, fs: int) -> np.ndarray:
    """The level per ENV_BIN_S, rms as a sine's peak (dBFS)."""
    n = int(ENV_BIN_S * fs)
    m = len(y) // n
    rms = np.sqrt(np.mean(y[: m * n].reshape(m, n) ** 2, axis=1))
    return 20 * np.log10(rms * np.sqrt(2) + 1e-12)


class Bench:
    """Renders of the unit (or the stock 670) with a key, in parallel."""

    def __init__(self, genome: Mapping[str, Any], s: TransientSettings):
        self.genome, self.s, self.fs = dict(genome), s, s.sample_rate
        self.keyed = spec.load_circuit(spec.circuit_path(CIRCUIT))
        self.stock = spec.load_circuit(spec.circuit_path(STOCK))
        self.v_in, self.v_out = full_scale(s, self.keyed)

    def job(self, program: np.ndarray, key: np.ndarray | None, ov: Mapping[str, Any], stock=False):
        return (program, key, dict(ov), stock)

    def _one(self, job) -> dict[str, np.ndarray]:
        program, key, ov, stock = job
        c = self.stock if stock else self.keyed
        ir = builder.build(c, {**self.genome, **ov}).ir
        ctl = (
            None if stock else {"key": (np.zeros(len(program)) if key is None else key) * self.v_in}
        )
        with fast.thread_priority(self.s.priority):
            r = fast.run_transient(ir, program * self.v_in, settings=self.s, controls=ctl)
        v = r.vectors
        return {"out": v["v(out)"] / self.v_out, "cv": v["v(cv)"], "bp": v["v(bp)"]}

    def run(self, jobs: list) -> list[dict[str, np.ndarray]]:
        # The longest first, so the pool's tail is short.
        order = sorted(range(len(jobs)), key=lambda i: -len(jobs[i][0]))
        out: list = [None] * len(jobs)
        with ThreadPoolExecutor(runner.default_jobs()) as ex:
            for i, r in zip(order, ex.map(self._one, [jobs[i] for i in order]), strict=True):
                out[i] = r
        return out


def rel_rms_db(a: np.ndarray, b: np.ndarray) -> float:
    d = np.sqrt(np.mean((a - b) ** 2))
    return round(float(20 * np.log10(d / np.sqrt(np.mean(b**2)) + 1e-300)), 1)


def screen(b: Bench) -> tuple[dict, dict]:
    fs = b.fs
    tone = sine(INT_TONE_HZ, INT_TONE_DBFS, INT_S, fs)
    keys = kick(np.arange(0.2, INT_S, KICK_PERIOD_S), 6.0, INT_S, fs)
    n_idle = int(IDLE_S * fs)
    ducks_s = PRE_S + KICK_PERIOD_S
    bass = sine(BASS_HZ, BASS_DBFS, ducks_s, fs)
    idle, stock, at_int, ducks = b.run(
        [
            b.job(np.zeros(n_idle), None, {"key_mode": 1}),
            b.job(tone, None, {}, stock=True),
            b.job(tone, keys, {"key_mode": 0}),
            b.job(
                bass,
                kick([PRE_S], KEY_DUCKS_OFFSET_DB, ducks_s, fs),
                {"key_mode": 1, **NO_LIMIT},
            ),
        ]
    )
    a = int(0.05 * fs)  # the decimation filter's ring-in
    int_db = rel_rms_db(at_int["out"][a:], stock["out"][a:])
    e = env_db(ducks["out"], fs)
    i0 = int(PRE_S / ENV_BIN_S)
    duck = float(np.min(e[i0:]) - np.mean(e[i0 - 30 : i0 - 2]))
    checks = {
        "idle_quiet": generic.quiet(idle["out"][a:]),
        "int_is_stock": generic.check(int_db < INT_SAME_DB, int_db, INT_SAME_DB),
        "ext_keys": generic.check(duck < KEY_DUCKS_DB, round(duck, 1), KEY_DUCKS_DB),
    }
    return checks, {"int_minus_stock_db_re_signal": int_db, "duck_at_plus6_db": round(duck, 1)}


def duck_of(r: dict, kick_s: float, fs: int, until_s: float) -> dict:
    """The bass's level re its level before the kick at `kick_s`: the deepest duck, the
    duck 100 ms on, the times back to -3 and -1 dB (0 if it never got there, None if not
    back within `until_s`)."""
    e = env_db(r["out"], fs)
    i0 = int(round(kick_s / ENV_BIN_S))
    pre = float(np.mean(e[i0 - 30 : i0 - 2]))
    seg = e[i0 : int(round(until_s / ENV_BIN_S))] - pre
    deepest = int(np.argmin(seg))

    def back(db):
        if seg[deepest] > db:
            return 0.0
        above = np.nonzero(seg[deepest:] > db)[0]
        return None if len(above) == 0 else round((deepest + above[0]) * ENV_BIN_S, 3)

    return {
        "deepest_db": round(float(seg[deepest]), 2),
        "at_100ms_db": round(float(seg[int(0.1 / ENV_BIN_S)]), 2),
        "back_to_3db_s": back(-3.0),
        "back_to_1db_s": back(-1.0),
        "cv_min_v": round(float(np.min(r["cv"][int(kick_s * fs) :])), 2),
        "trace_db": np.round(seg, 2).tolist(),
    }


def run(
    name: str,
    genome: Mapping[str, Any] | None = None,
    *,
    clips: bool = False,
    settings: TransientSettings | None = None,
    log: Callable[[str], Any] = print,
) -> dict:
    """Screen the genome; if it passes, measure everything, write the report."""
    del clips  # no program clips
    t0 = time.perf_counter()
    genome = dict(genome or {})
    out_dir = REPORT_DIR / name
    out_dir.mkdir(parents=True, exist_ok=True)
    s = settings or TransientSettings.from_sim_settings(engine="configured")
    if s.engine != "circuitsim":
        raise ValueError("the keyed 670 needs circuitsim (ngspice runs no control inputs)")
    b = Bench(genome, s)
    fs = s.sample_rate
    report: dict[str, Any] = {
        "name": name,
        "circuit": CIRCUIT,
        "when": dt.datetime.now().isoformat(timespec="seconds"),
        "code": runner.code_version(),
        "engine": s.engine,
        "quality": s.quality,
        "genome": genome,
    }
    log(f"{name}: screen")
    checks, info = screen(b)
    report["screen"], report["checks"] = info, checks
    report["plausible"] = all(c["passes"] for c in checks.values())
    if not report["plausible"]:
        log(f"{name}: rejected: {[k for k, c in checks.items() if not c['passes']]}")
        _write(out_dir, report)
        return report

    jobs, keys = [], []

    def add(k, *job):
        keys.append(k)
        jobs.append(b.job(*job))

    lo = sine(BASS_HZ, EXT_LOAD_DBFS, 1.0, fs)
    add(("load", 0), lo, None, {"key_mode": 0})
    add(("load", 1), lo, None, {"key_mode": 1})
    curve_s = PRE_S + CURVE_KICKS * KICK_PERIOD_S
    starts = PRE_S + KICK_PERIOD_S * np.arange(CURVE_KICKS)
    for off in KEY_OFFSETS_DB:
        add(
            ("curve", off),
            sine(BASS_HZ, BASS_DBFS, curve_s, fs),
            kick(starts, off, curve_s, fs),
            {"key_mode": 1, **NO_LIMIT},
        )
    depth_s = PRE_S + DEPTH_KICKS * KICK_PERIOD_S
    depth_starts = PRE_S + KICK_PERIOD_S * np.arange(DEPTH_KICKS)
    for dp in DEPTHS:
        for off in DEPTH_OFFSETS_DB:
            add(
                ("depth", dp, off),
                sine(BASS_HZ, BASS_DBFS, depth_s, fs),
                kick(depth_starts, off, depth_s, fs),
                {"key_mode": 1, "key_depth": dp},
            )
    for tc, rel_s in RECOVERY_S.items():
        n_s = PRE_S + rel_s
        add(
            ("recovery", tc),
            sine(BASS_HZ, BASS_DBFS, n_s, fs),
            kick([PRE_S], 0.0, n_s, fs),
            {"key_mode": 1, "time_constant": tc},
        )
    for off in THUMP_OFFSETS_DB:
        for bal in THUMP_BALANCES:
            add(
                ("thump", off, bal),
                np.zeros(int(curve_s * fs)),
                kick(starts, off, curve_s, fs),
                {"key_mode": 1, "balance": bal},
            )
    log(f"{name}: {len(jobs)} renders")
    got = dict(zip(keys, b.run(jobs), strict=True))

    a = int(0.5 * fs)
    g = [20 * np.log10(np.sqrt(np.mean(got[("load", m)]["out"][a:] ** 2))) for m in (0, 1)]
    report["ext_load"] = {
        "ext_re_int_db": round(float(g[1] - g[0]), 2),
        "program_dbfs": EXT_LOAD_DBFS,
    }

    # The curve's third kick: the duck has its steady pattern by then.
    k3 = float(starts[2])
    curve = {
        off: duck_of(got[("curve", off)], k3, fs, k3 + KICK_PERIOD_S) for off in KEY_OFFSETS_DB
    }
    report["duck_curve"] = {
        "key_re_dbfs": KEY_REF_DBFS,
        "rows": [
            {"key_offset_db": off, **{k: v for k, v in d.items() if k != "trace_db"}}
            for off, d in curve.items()
        ],
    }
    # The last kick of each: the clamp's supply and wiper have seen the ones before.
    k_last = float(depth_starts[-1])
    depth = {
        (dp, off): duck_of(got[("depth", dp, off)], k_last, fs, k_last + KICK_PERIOD_S)
        for dp in DEPTHS
        for off in DEPTH_OFFSETS_DB
    }
    report["depth"] = {
        "key_re_dbfs": KEY_REF_DBFS,
        "rows": [
            {
                "key_depth": dp,
                "key_offset_db": off,
                "deepest_db": depth[dp, off]["deepest_db"],
                "at_100ms_db": depth[dp, off]["at_100ms_db"],
                "back_to_1db_s": depth[dp, off]["back_to_1db_s"],
                "cv_min_v": depth[dp, off]["cv_min_v"],
                "b_plus_min_v": round(float(np.min(got[("depth", dp, off)]["bp"][a:])), 1),
            }
            for dp in DEPTHS
            for off in DEPTH_OFFSETS_DB
        ],
    }
    rec = {
        tc: duck_of(got[("recovery", tc)], PRE_S, fs, PRE_S + RECOVERY_S[tc]) for tc in RECOVERY_S
    }
    report["recovery"] = {
        "key_offset_db": 0.0,
        "rows": [
            {"time_constant": tc, **{k: v for k, v in d.items() if k != "trace_db"}}
            for tc, d in rec.items()
        ],
    }

    def peak_db(y):
        return round(float(20 * np.log10(np.max(np.abs(y[a:])) + 1e-30)), 1)

    report["thump"] = {
        "rows": [
            {
                "key_offset_db": off,
                "balance": bal,
                "out_peak_dbfs": peak_db(got[("thump", off, bal)]["out"]),
            }
            for off in THUMP_OFFSETS_DB
            for bal in THUMP_BALANCES
        ],
        "program_dbfs": BASS_DBFS,
    }
    report["elapsed_s"] = round(time.perf_counter() - t0, 1)
    _write(out_dir, report)
    _plots(out_dir, curve, depth, rec)
    log(f"{name}: done in {report['elapsed_s']} s -> {out_dir}")
    return report


def _write(out_dir: Path, report: Mapping[str, Any]) -> None:
    (out_dir / "report.json").write_text(
        json.dumps(report, indent=1, default=str), encoding="utf-8"
    )


def _plots(out_dir: Path, curve: dict, depth: dict, rec: dict) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, (ax, bx) = plt.subplots(1, 2, figsize=(11, 4.2))
    offs = list(curve)
    ax.plot(offs, [curve[o]["deepest_db"] for o in offs], "o-", label="deepest")
    ax.plot(offs, [curve[o]["at_100ms_db"] for o in offs], "s--", label="100 ms after the kick")
    ax.set_xlabel(f"key level re {KEY_REF_DBFS:g} dBFS (dB)")
    ax.set_ylabel("bass level re before the kick (dB)")
    ax.set_title("Duck against the key's level (KEY EXT)")
    ax.grid(True, alpha=0.3)
    ax.legend()
    for o in offs:
        tr = curve[o]["trace_db"]
        bx.plot(np.arange(len(tr)) * ENV_BIN_S * 1e3, tr, label=f"{o:+g} dB")
    bx.set_xlabel("ms after the kick")
    bx.set_ylabel("bass level (dB)")
    bx.set_ylim(-60, 3)
    bx.set_title("Duck traces")
    bx.grid(True, alpha=0.3)
    bx.legend(fontsize=7, ncol=2)
    fig.tight_layout()
    fig.savefig(out_dir / "duck_curve.png", dpi=110)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(7, 4.2))
    for off in DEPTH_OFFSETS_DB:
        ax.plot(
            DEPTHS, [depth[dp, off]["deepest_db"] for dp in DEPTHS], "o-", label=f"key {off:+g} dB"
        )
    ax.set_xlabel("DEPTH (rotation)")
    ax.set_ylabel("deepest duck (dB)")
    ax.set_ylim(-60, 1)
    ax.set_title(f"Duck against DEPTH (KEY EXT, key re {KEY_REF_DBFS:g} dBFS)")
    ax.grid(True, alpha=0.3)
    ax.legend()
    fig.tight_layout()
    fig.savefig(out_dir / "depth.png", dpi=110)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(8, 4.2))
    for tc, d in rec.items():
        tr = d["trace_db"]
        ax.plot(np.arange(len(tr)) * ENV_BIN_S, tr, label=f"TC{tc}")
    ax.set_xscale("symlog", linthresh=0.1)
    ax.set_xlabel("s after the kick")
    ax.set_ylabel("bass level (dB)")
    ax.set_title(f"Recovery per time constant (one kick at {KEY_REF_DBFS:g} dBFS)")
    ax.grid(True, alpha=0.3)
    ax.legend()
    fig.tight_layout()
    fig.savefig(out_dir / "recovery.png", dpi=110)
    plt.close(fig)
