"""The gas-tube sawtooth's event study (HYBRID_PHYSICS_PLAN.md H2) -> reports/hybrid/event_study.*

    uv run --extra fast --extra listen python scripts/thyratron_event_study.py [--seconds S]
        [--only R,F ...] [--workers N] [--fresh]

On config/circuits/rca_884_sweep.yaml (H1's reference circuit), three questions:

1. **The reset** (the reference: circuitsim production, esdirk4 with local error control,
   output at 3.072 MHz, oversample 1, as H1): per setting, averaged over the window's events,
   - its length: the strike (the sweep's top) to the ramp's restart (its bottom), the anode
     node's 90 -> 10% fall, the anode current's rise (strike to peak);
   - the charge it moves (the anode current's integral, against C x the swing) and the
     current pulse's spectrum normalized by it, |I(f)| / Q: 1 at frequencies where the
     pulse is a delta of charge Q (only its charge and moment matter), its -3 dB frequency;
   - the plasma's decay after extinction (the state w's slope: one e-fold of ion density
     per 1 V);
   over every S1 range at both ends of R6, and at C4, C6, C8 the conditions: B+ 350 / 550 V
   (the cathode's bias divider follows it), R11 1000 / 2200 ohm (the bias, so the strike),
   R4 350 / 500 ohm (RCA's range). The heater isn't in the 884's model (no cathode
   temperature): not studied.
2. **Its spectrum above 48 kHz** (the reference, the 14 base settings): the share of the
   sweep's AC power above 20, 48 and 96 kHz, the harmonics' level there against an ideal
   sawtooth's 1 / n.
3. **Aliasing of the direct simulation at 96 kHz** (the 14 base settings): every candidate
   against the reference band-limited to 20 kHz (a 120 dB Kaiser FIR, decimated to 96 kHz):
   - `direct-Nx`: the draft's method (trbdf2, no error control, Newton 1e-3) at N x 96 kHz,
     decimated as renders are (`io.decimate`);
   - `production`: production at its 2x, error control on;
   - `draft-2x` (96 kHz behind a 48 kHz host: the native app's Play quality for hard
     clippers), `draft-1x` (48 kHz);
   - `production-8x`: production's method and error control at 8x;
   - `island-Mx[-esdirk4]`: technique M as built (partition.rs's multi-rate parts): the
     oscillator (tube, timing capacitors, charging, grid, the 6J7's input) at M steps per
     sample on its own thread, B+ and the cathode's divider (shared at B+ and the cathode's
     25 uF) at 96 kHz with the draft's method (production's with `-esdirk4`); its outputs
     are the island's nodes as probed (a sample each); `-avg`: the cut also through C9 into
     the 6J7's grid (`n8` in the slow part, fed the island's current averaged per sample:
     what a multi-rate part hands the rest), the coupling held (extrapolated, it diverges);
   - `ideal-96k`: the reference itself point-sampled at 96 kHz (every 32nd sample): what any
     simulation handing on one sample per sample of the exact waveform has (an island's
     probe); `ideal-Nk`: point-sampled at N kHz, then decimated by `io.decimate` (renders'
     filter, Kaiser beta 5), `ideal-Nk-aa` by a 120 dB filter: an exact simulation at that
     rate behind a decimator (M with an anti-alias filter at its boundary), the floor under
     the candidates' numerical error.
   Metrics: the pitch (cents from the reference), the period's jitter (cents rms, cycle to
   cycle), the harmonics' levels up to 20 kHz (the largest error over those within 60 dB of
   the fundamental), the inharmonic power in 20 Hz-20 kHz re the harmonics' (dB) and its
   largest spur (dBc), and the cost (wall seconds per audio second; one job at a time per
   core, `--workers` at once).

Every run starts with the slow capacitors (C9: 0.75 s; C11, C12) preset to their steady
voltages from a production run of 4 s, so the window (the run's last `--seconds` - 0.15
s) doesn't drift. Runs are cached in cache/hybrid/h2/ (keyed by the setting, the mode, the
circuit and component files and circuitsim's source hash; `--fresh` reruns them; costs
are the first run's). Plots and numbers ->
reports/hybrid/event_study.{json,png}.
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
from scipy.signal import firwin, kaiserord, resample_poly

from varimu.circuit import builder, spec
from varimu.circuit.ir import Capacitor, Device, Section, VoltageProbe
from varimu.config import CONFIG_DIR, REPO_ROOT
from varimu.sim import fast, io

OUT = REPO_ROOT / "reports" / "hybrid"
CACHE = REPO_ROOT / "cache" / "hybrid" / "h2"
CIRCUIT = CONFIG_DIR / "circuits" / "rca_884_sweep.yaml"
COMPONENT = CONFIG_DIR / "components" / "884" / "1.yaml"
FS = 96000
REF_RATE = 32 * FS
SKIP_S = 0.15  # the start's transient left out
BAND_HZ = (20.0, 20000.0)
PROBES = ("out", "k", "a", "g", "w", "n7", "n8", "n12")
# The slow part of an island split: B+ and the cathode's divider (stiff nodes: B+ and the
# cathode's 25 uF); `-avg` islands also the 6J7's grid return R8 (the cut through C9 into
# the grid: the island's current averaged per sample; it diverges with the extrapolated
# coupling, so those run with the coupling held).
SLOW = {"VB", "R11", "R12", "R13", "R14", "C11", "C12"}
CONDITIONS = {
    "b350": {"b_plus_v": 350.0},
    "b550": {"b_plus_v": 550.0},
    "r11_1000": {"r11_ohm": 1000.0},
    "r11_2200": {"r11_ohm": 2200.0},
    "r4_350": {"r4_ohm": 350.0},
    "r4_500": {"r4_ohm": 500.0},
}
CANDIDATES = (
    "direct-1x",
    "direct-2x",
    "direct-4x",
    "direct-8x",
    "direct-16x",
    "direct-32x",
    "production",
    "draft-2x",
    "draft-1x",
    "production-8x",
    "island-4x",
    "island-8x",
    "island-16x",
    "island-32x",
    "island-8x-esdirk4",
    "island-32x-esdirk4",
    "island-8x-avg",
    "island-32x-avg",
    "m1-8x",
    "m1-8x-esdirk4",
    "m1-16x-esdirk4",
    "m1-32x-esdirk4",
    "k-draft",
    "k-production",
)
# Technique K's tables per range (config/events/NAME.json; HYBRID_PHYSICS_PLAN.md H3c-H3d): a
# range without them has no K candidate.
K_TABLES = {6: "884_unit_c6"}


# --- Building and running --------------------------------------------------------------


def build(rng: int, fine: float, over: dict, preset: dict | None = None):
    s = spec.load_circuit(CIRCUIT)
    vals = spec.resolve(s, {"range": rng, "fine": fine, **over})
    ir = builder.build_ir(s, vals)
    ir = dataclasses.replace(ir, probes=tuple(VoltageProbe(p) for p in PROBES))
    if preset:
        secs = []
        for sec in ir.sections:
            els = tuple(
                dataclasses.replace(e, v0_v=preset[e.name])
                if isinstance(e, Capacitor) and e.name in preset
                else e
                for e in sec.elements
            )
            secs.append(dataclasses.replace(sec, elements=els))
        ir = dataclasses.replace(ir, sections=tuple(secs))
    return ir, vals


def with_k(ir, rng: int):
    """The 884 as its event kernels (technique K) from the range's tables."""
    from varimu.devices import thyratron_events as te

    name = K_TABLES[rng]
    t = te.Tables.load(CONFIG_DIR / "events" / f"{name}.json")

    def swap(e):
        if isinstance(e, Device) and e.name == "XV1":
            return te.element(t, e.name, *e.nodes, source=te.source_label(name, t))
        return e

    secs = tuple(
        dataclasses.replace(sec, elements=tuple(swap(e) for e in sec.elements))
        for sec in ir.sections
    )
    return dataclasses.replace(ir, sections=secs, models=())


def island(ir, m: int, cut_n8: bool = False):
    """The oscillator at m steps per sample on a thread of its own (technique M)."""
    names = SLOW | ({"R8"} if cut_n8 else set())
    els = [e for sec in ir.sections for e in sec.elements]
    slow = tuple(e for e in els if e.name in names)
    fast_ = tuple(e for e in els if e.name not in names)
    return dataclasses.replace(
        ir, sections=(Section("supply and load", slow), Section("oscillator", fast_, m))
    )


def island_m1(ir, m: int):
    """M1 (HYBRID_PHYSICS_PLAN.md H3a): the oscillator, the 6J7's input included, at m steps
    per sample behind the decimator, B+ and the cathode's divider outside (stiff: the
    delayed currents into them cost nothing measurable); heard through its decimated
    probes. (Cut at `out` instead, with the island owning it and the 6J7's input outside,
    the input's current through R7, ~4% of the charging current, came back a sample and
    the decimator's ~6.4 samples late: +7 cents at 18.8 kHz, -45 dB at any m. The rule:
    cut where nothing comes back, at a grid the island owns.)"""
    els = [e for sec in ir.sections for e in sec.elements]
    slow = tuple(e for e in els if e.name in SLOW)
    fast_ = tuple(e for e in els if e.name not in SLOW)
    osc = Section("oscillator", fast_, m, decimate="fir")
    return dataclasses.replace(ir, sections=(Section("supply and load", slow), osc))


def settings(mode: str) -> io.TransientSettings:
    base = dict(full_scale_volts_peak=1.0, settle_s=0.0)
    if mode == "k-draft":
        mode = "draft"
    if mode in ("reference", "preset", "production", "production-8x", "k-production") or (
        mode.endswith("-esdirk4")
    ):
        st = io.TransientSettings.from_sim_settings(engine="circuitsim", quality="production")
        if mode == "reference":
            return dataclasses.replace(st, sample_rate=REF_RATE, oversample=1, **base)
        if mode.endswith("-esdirk4"):
            # the island steps without error control; the slow part keeps production's
            return dataclasses.replace(st, oversample=1, **base)
        if mode == "production-8x":
            return dataclasses.replace(st, oversample=8, **base)
        return dataclasses.replace(st, **base)
    if mode == "draft-1x":
        st = io.TransientSettings.from_sim_settings(engine="circuitsim", quality="draft-1x")
        return dataclasses.replace(st, **base)
    st = io.TransientSettings.from_sim_settings(engine="circuitsim", quality="draft")
    if mode == "draft":  # the draft at 96 kHz (K's live quality)
        return dataclasses.replace(st, **base)
    if mode == "draft-2x":
        return dataclasses.replace(st, host_rate=48000, oversample=2, **base)
    if mode.startswith("direct-"):
        return dataclasses.replace(st, oversample=int(mode[7:-1]), **base)
    if mode.startswith(("island-", "m1-")):
        hold = "hold" if mode.endswith("-avg") else st.partition_coupling
        return dataclasses.replace(st, oversample=1, partition_coupling=hold, **base)
    raise ValueError(mode)


def run(job: dict) -> dict:
    rng, fine, over, mode = job["range"], job["fine"], job["over"], job["mode"]
    ir, vals = build(rng, fine, over, job.get("preset"))
    if mode.startswith("island-"):
        ir = island(ir, int(mode.split("-")[1][:-1]), cut_n8=mode.endswith("-avg"))
    elif mode.startswith("m1-"):
        ir = island_m1(ir, int(mode.split("-")[1][:-1]))
    elif mode.startswith("k-"):
        ir = with_k(ir, rng)
    st = settings(mode)
    seconds = job["seconds"]
    n = int(seconds * st.sample_rate)
    t0 = time.perf_counter()
    try:
        res = fast.run_transient(ir, np.zeros(n), settings=st)
    except fast.SimulationFailed as e:
        if mode in ("reference", "preset"):
            raise
        return {**job, "error": str(e), "wall_s": time.perf_counter() - t0}
    wall = time.perf_counter() - t0
    v = {p: np.asarray(res.vectors[f"v({p})"]) for p in PROBES if f"v({p})" in res.vectors}
    return {**job, "values": vals, "v": v, "wall_s": wall, "rate": st.sample_rate}


def preset_of(r: dict) -> dict:
    """The slow capacitors' steady voltages: their mean over the run's last 0.3 s."""
    tail = slice(-int(0.3 * r["rate"]), None)
    v = {p: float(np.mean(r["v"][p][tail])) for p in ("k", "n7", "n8", "n12")}
    return {"C9": v["n7"] - v["n8"], "C11": v["k"], "C12": v["n12"]}


def key(job: dict) -> str:
    import circuitsim

    from varimu.devices import thyratron_events as te

    h = hashlib.sha256()
    h.update(CIRCUIT.read_bytes())
    h.update(COMPONENT.read_bytes())
    if job["mode"].startswith("k-"):
        h.update(circuitsim.SOURCE_HASH.encode())
        h.update((CONFIG_DIR / "events" / f"{K_TABLES[job['range']]}.json").read_bytes())
    else:  # the event kernels' code moves only K's runs
        h.update(te.engine_hash().encode())
    h.update(
        json.dumps(
            {k: job[k] for k in ("range", "fine", "over", "mode", "seconds", "preset")},
            sort_keys=True,
        ).encode()
    )
    return h.hexdigest()[:16]


def run_cached(job: dict) -> dict:
    p = CACHE / f"{key(job)}.npz"
    if p.exists() and not job.get("fresh"):
        z = np.load(p, allow_pickle=True)
        meta = json.loads(str(z["meta"]))
        return {**job, **meta, "v": {k[2:]: z[k] for k in z.files if k.startswith("v_")}}
    r = run(job)
    if "error" in r:
        return r
    CACHE.mkdir(parents=True, exist_ok=True)
    meta = {"values": r["values"], "wall_s": r["wall_s"], "rate": r["rate"]}
    np.savez(p, meta=json.dumps(meta), **{f"v_{k}": x for k, x in r["v"].items()})
    return r


# --- 1. The reset ------------------------------------------------------------------------


def events(y: np.ndarray, rate: int) -> list[tuple[int, int]]:
    """(strike, restart) sample pairs: each period's top and the bottom after it, between
    upward crossings of the ramp's midpoint."""
    lo, hi = np.percentile(y, 0.5), np.percentile(y, 99.5)
    mid = 0.5 * (lo + hi)
    ups = np.where((y[:-1] < mid) & (y[1:] >= mid))[0]
    out = []
    for a, b in zip(ups[:-1], ups[1:], strict=False):
        top = a + int(np.argmax(y[a:b]))
        bot = top + int(np.argmin(y[top:b]))
        out.append((top, bot))
    return out


def reset_metrics(r: dict) -> dict:
    rate, vals = r["rate"], r["values"]
    i0 = int(SKIP_S * rate)
    v = {p: x[i0:] for p, x in r["v"].items()}
    y = v["out"] - v["k"]
    ia = (v["out"] - v["a"]) / vals["r4_ohm"]
    w = v["w"] - v["k"]
    c = vals[f"c{r['range']}_f"]
    ev = events(y, rate)[1:-1]
    if len(ev) < 3:
        return {"oscillates": False}
    rows = []
    freqs = np.array([1e3, 5e3, 10e3, 20e3, 48e3, 96e3])
    for top, bot in ev[: min(len(ev), 40)]:
        swing = y[top] - y[bot]
        a90, a10 = y[bot] + 0.9 * swing, y[bot] + 0.1 * swing
        seg = y[top : bot + 1]
        j90, j10 = int(np.argmax(seg < a90)), int(np.argmax(seg < a10))
        kp = top + int(np.argmax(ia[top : bot + 1]))
        # the pulse: the anode current from a little before the strike to the restart
        # (the charging current through R5 + R6 is ~1 mA against tens of mA, and the
        # restart is where they balance)
        p0 = max(top - int(2e-6 * rate), 0)
        pulse = ia[p0 : bot + 1]
        t = np.arange(len(pulse)) / rate
        q = float(np.sum(pulse) / rate)
        spec_ = np.abs(np.exp(-2j * np.pi * np.outer(freqs, t)) @ pulse / rate) / q
        # the -3 dB frequency of |I(f)| / Q, on a log grid
        fg = np.logspace(2, 7, 300)
        sg = np.abs(np.exp(-2j * np.pi * np.outer(fg, t)) @ pulse / rate) / q
        f3 = float(fg[np.argmax(sg < 10 ** (-3 / 20))]) if np.any(sg < 10 ** (-3 / 20)) else None
        # the plasma's decay: w's slope over the 30 us after the current falls below 1% of
        # its peak (the arc out)
        ko = kp + int(np.argmax(ia[kp:] < 0.01 * ia[kp]))
        ws = w[ko : ko + int(30e-6 * rate)]
        slope = np.polyfit(np.arange(len(ws)) / rate, ws, 1)[0] if len(ws) > 10 else np.nan
        rows.append(
            dict(
                v_strike=float(y[top]),
                v_low=float(y[bot]),
                reset_s=(bot - top) / rate,
                fall_90_10_s=(j10 - j90) / rate,
                rise_s=(kp - top) / rate,
                peak_ia_a=float(ia[kp]),
                charge_c=q,
                charge_vs_cdv=q / (c * swing),
                pulse_rel_db={
                    f"{f / 1e3:g}k": float(20 * np.log10(s))
                    for f, s in zip(freqs, spec_, strict=True)
                },
                pulse_f3db_hz=f3,
                plasma_tau_s=float(-1.0 / slope) if slope < 0 else None,
            )
        )
    out: dict = {"oscillates": True, "events": len(rows)}
    for k in rows[0]:
        if k == "pulse_rel_db":
            out[k] = {f: float(np.mean([r_[k][f] for r_ in rows])) for f in rows[0][k]}
        else:
            xs = [r_[k] for r_ in rows if r_[k] is not None]
            out[k] = float(np.mean(xs)) if xs else None
            if k == "reset_s" and xs:
                out["reset_spread"] = float(np.std(xs) / np.mean(xs))
    per = np.diff([top for top, _ in ev]) / rate
    out["f_hz"] = float(1.0 / per.mean())
    out["drift_over_window"] = float(
        np.polyfit(np.arange(len(per)), per, 1)[0] * len(per) / per.mean()
    )
    return out


# --- 2. The spectrum above 48 kHz --------------------------------------------------------


def hi_spectrum(r: dict) -> dict:
    rate = r["rate"]
    i0 = int(SKIP_S * rate)
    y = (r["v"]["out"] - r["v"]["k"])[i0:]
    y = y - y.mean()
    win = np.blackman(len(y))
    p = np.abs(np.fft.rfft(y * win)) ** 2
    f = np.fft.rfftfreq(len(y), 1 / rate)
    tot = p[f > 0].sum()
    share = {
        f"above_{int(c // 1000)}k_db": float(10 * np.log10(p[f > c].sum() / tot))
        for c in (20e3, 48e3, 96e3)
    }
    # the harmonics' mean level in +-10% around 20 ... 480 kHz re the fundamental's, against
    # an ideal sawtooth's 1 / n (band power over the harmonics in the band: no per-harmonic
    # bin search, which a slightly wrong f0 makes miss at high orders)
    k1 = int(np.argmax(p[f > 10]) + np.argmax(f > 10))
    f0 = f[k1]
    p1 = p[max(k1 - 6, 0) : k1 + 7].sum()
    lev = {}
    for fc in (20e3, 48e3, 96e3, 192e3, 480e3):
        band = p[(f >= 0.9 * fc) & (f < 1.1 * fc)].sum() / (0.2 * fc / f0)
        lev[f"{fc / 1e3:g}k"] = {
            "n": int(round(fc / f0)),
            "db_re_f0": float(10 * np.log10(band / p1)),
            "ideal_db": float(-20 * np.log10(fc / f0)),
        }
    return {"share": share, "harmonics": lev}


# --- 3. Aliasing -------------------------------------------------------------------------


_FIRS: dict[int, np.ndarray] = {}


def band_limit(y: np.ndarray, k: int) -> np.ndarray:
    """k x 96 kHz to 96 kHz through a 120 dB Kaiser low-pass (20 -> 40 kHz)."""
    if k not in _FIRS:
        rate = k * FS
        n, beta = kaiserord(120.0, 20e3 / (rate / 2))
        # unity gain at DC: resample_poly doesn't rescale a filter it is given (down only)
        _FIRS[k] = firwin(n | 1, 30e3, window=("kaiser", beta), fs=rate)
    return resample_poly(y, 1, k, window=_FIRS[k])


def band_limit_ref(y: np.ndarray) -> np.ndarray:
    """The reference at 3.072 MHz to 96 kHz (the 120 dB filter)."""
    return band_limit(y, 32)


def spectrum_metrics(y: np.ndarray, rate: int, f0_hint: float) -> dict:
    y = y - y.mean()
    n = len(y)
    from scipy.signal.windows import blackmanharris

    x = np.fft.rfft(y * blackmanharris(n))
    p = np.abs(x) ** 2
    f = np.fft.rfftfreq(n, 1 / rate)
    df = f[1]

    # the fundamental, then each harmonic's peak near n f0 (refined per harmonic: drift and
    # the candidates' own pitch)
    def peak(fc, half):
        lo, hi = np.searchsorted(f, fc - half), np.searchsorted(f, fc + half)
        k = lo + int(np.argmax(p[lo:hi]))
        if 0 < k < len(p) - 1:  # quadratic interpolation on log power
            a, b, c = np.log(p[k - 1 : k + 2] + 1e-300)
            d = 0.5 * (a - c) / (a - 2 * b + c)
        else:
            d = 0.0
        return k, (k + d) * df

    k1, f1 = peak(f0_hint, 0.05 * f0_hint)
    hs = []
    for h in range(2, 11):
        if h * f1 > BAND_HZ[1]:
            break
        hs.append(peak(h * f1, 0.02 * h * f1 + 3 * df)[1] / h)
    f0 = float(np.median([f1] + hs))
    mask = np.zeros(len(p), bool)
    levels = []
    for h in range(1, int(BAND_HZ[1] / f0) + 1):
        k, _ = peak(h * f0, max(0.002 * h * f0, 4 * df))
        lo, hi = max(k - 6, 0), k + 7
        mask[lo:hi] = True
        levels.append(float(p[lo:hi].sum()))
    band = (f >= BAND_HZ[0]) & (f <= BAND_HZ[1])
    harm = float(np.sum(levels))
    resid = p[band & ~mask]
    return {
        "f0_hz": f0,
        "levels_db": (10 * np.log10(np.array(levels) / levels[0])).tolist(),
        "inharmonic_db": float(10 * np.log10(resid.sum() / harm)),
        "worst_spur_dbc": float(10 * np.log10(resid.max() / p[k1])) if len(resid) else None,
        "worst_spur_hz": float(f[band & ~mask][np.argmax(resid)]) if len(resid) else None,
    }


def jitter_cents(y: np.ndarray, rate: int) -> float:
    """The period's cycle-to-cycle variation (cents rms): from the midpoint's upward
    crossings (linear interpolation on the ramp)."""
    lo, hi = np.percentile(y, 1), np.percentile(y, 99)
    mid = 0.5 * (lo + hi)
    k = np.where((y[:-1] < mid) & (y[1:] >= mid))[0]
    t = (k + (mid - y[k]) / (y[k + 1] - y[k])) / rate
    per = np.diff(t)
    if len(per) < 4:
        return float("nan")
    return float(1200 / np.log(2) * np.std(np.diff(per)) / np.sqrt(2) / per.mean())


def compare(cand: dict, ref: dict) -> dict:
    out = {}
    for probe in ("out", "n8"):
        if probe not in cand["sig"]:
            continue
        c, r_ = cand["sig"][probe], ref["sig"][probe]
        dl = np.array(c["levels_db"][: len(r_["levels_db"])]) - np.array(
            r_["levels_db"][: len(c["levels_db"])]
        )
        within = np.array(r_["levels_db"][: len(dl)]) > -60
        out[probe] = {
            "cents": float(1200 * np.log2(c["f0_hz"] / r_["f0_hz"])),
            "jitter_cents": c["jitter_cents"],
            "harm_err_max_db": float(np.max(np.abs(dl[within]))) if within.any() else None,
            "harm_err_rms_db": float(np.sqrt(np.mean(dl[within] ** 2))) if within.any() else None,
            "inharmonic_db": c["inharmonic_db"],
            "worst_spur_dbc": c["worst_spur_dbc"],
            "worst_spur_hz": c["worst_spur_hz"],
        }
    return out


def signals(v: dict, rate: int, f0_hint: float) -> dict:
    """Per output: the spectral metrics and the jitter over the window."""
    i0 = int(SKIP_S * rate)
    out = {}
    for probe, y in (("out", v["out"] - v["k"]), ("n8", v.get("n8"))):
        if y is None:
            continue
        y = y[i0:]
        m = spectrum_metrics(y, rate, f0_hint)
        m["jitter_cents"] = jitter_cents(y, rate)
        out[probe] = m
    return out


# --- Plot ----------------------------------------------------------------------------------


def plot(res: dict, path: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(2, 3, figsize=(18, 10))
    base = [r for r in res["reset"] if not r["cond"] and r.get("oscillates")]
    conds = [r for r in res["reset"] if r["cond"] and r.get("oscillates")]
    # (a) the reset's length
    a = ax[0, 0]
    fs_ = [r["f_hz"] for r in base]
    a.loglog(fs_, [r["reset_s"] * 1e6 for r in base], "o-", label="strike -> restart")
    a.loglog(fs_, [r["fall_90_10_s"] * 1e6 for r in base], "s-", label="90 -> 10% fall")
    a.loglog(fs_, [r["rise_s"] * 1e6 for r in base], "^-", label="strike -> peak current")
    a.loglog(
        [r["f_hz"] for r in conds],
        [r["reset_s"] * 1e6 for r in conds],
        "kx",
        label="conditions (C4/C6/C8)",
    )
    a.axhline(1e6 / FS, color="r", ls=":", label="one sample at 96 kHz")
    a.set_xlabel("pitch (Hz)")
    a.set_ylabel("us")
    a.set_title("the reset's length (reference)")
    a.legend(fontsize=7)
    # (b) the pulse's spectrum re its charge
    a = ax[0, 1]
    keys = list(base[0]["pulse_rel_db"])
    fx = [float(k[:-1]) * 1e3 for k in keys]
    for r in base:
        if r["fine"] == 0:
            a.semilogx(fx, [r["pulse_rel_db"][k] for k in keys], "o-", label=f"C{r['range']}")
    a.axvline(20e3, color="k", ls=":")
    a.axvline(48e3, color="r", ls=":")
    a.set_xlabel("Hz")
    a.set_ylabel("|I(f)| / Q (dB)")
    a.set_title("the discharge pulse vs a delta of its charge (R6 at 0)")
    a.legend(fontsize=7)
    # (c) power above 48 kHz
    a = ax[0, 2]
    hs = res["spectrum"]
    for k_, mk in (("above_20k_db", "o-"), ("above_48k_db", "s-"), ("above_96k_db", "^-")):
        a.semilogx([h["f_hz"] for h in hs], [h["share"][k_] for h in hs], mk, label=k_)
    a.set_xlabel("pitch (Hz)")
    a.set_ylabel("dB re the sweep's AC power")
    a.set_title("the sweep's power above 20 / 48 / 96 kHz (reference)")
    a.legend(fontsize=7)
    # (d), (e) aliasing and pitch per candidate
    al = res["alias"]
    ideals = ("ideal-96k", "ideal-192k", "ideal-384k-aa", "ideal-768k-aa")
    names = [c for c in CANDIDATES + ideals if any(c in x["cands"] for x in al)]
    cmap = plt.get_cmap("tab20")
    for i, c in enumerate(names):
        pts = [
            (x["f_hz"], x["cands"][c]["out"])
            for x in al
            if c in x["cands"] and "error" not in x["cands"][c]["out"]
        ]
        pts.sort()
        st = "--" if c.startswith("ideal") else "-"
        ax[1, 0].semilogx(
            [p[0] for p in pts],
            [p[1]["inharmonic_db"] for p in pts],
            st,
            marker=".",
            color=cmap(i),
            label=c,
        )
        ax[1, 1].semilogx(
            [p[0] for p in pts],
            [p[1]["cents"] for p in pts],
            st,
            marker=".",
            color=cmap(i),
            label=c,
        )
    ref_floor = sorted((x["f_hz"], x["ref_floor_db"]) for x in al)
    ax[1, 0].semilogx(
        [p[0] for p in ref_floor], [p[1] for p in ref_floor], "k:", lw=2, label="reference's floor"
    )
    ax[1, 0].set_xlabel("pitch (Hz)")
    ax[1, 0].set_ylabel("inharmonic power 20 Hz-20 kHz re harmonics (dB)")
    ax[1, 0].set_title("aliasing of the sweep (out - k)")
    ax[1, 0].legend(fontsize=6, ncol=2)
    ax[1, 1].set_xlabel("pitch (Hz)")
    ax[1, 1].set_ylabel("cents from the reference")
    ax[1, 1].set_title("pitch")
    ax[1, 1].set_ylim(-150, 150)
    # (f) cost
    a = ax[1, 2]
    for c in (n for n in names if not n.startswith("ideal")):
        pts = sorted(
            (x["f_hz"], x["cands"][c]["out"]["wall_per_audio_s"])
            for x in al
            if c in x["cands"] and "error" not in x["cands"][c]["out"]
        )
        a.loglog(
            [p[0] for p in pts],
            [p[1] for p in pts],
            marker=".",
            color=cmap(names.index(c)),
            label=c,
        )
    pts = sorted((x["f_hz"], x["ref_wall_per_audio_s"]) for x in al)
    a.loglog(
        [p[0] for p in pts], [p[1] for p in pts], "k:", lw=2, label="reference (3.072 MHz, EC)"
    )
    a.axhline(1.0, color="r", ls=":")
    a.set_xlabel("pitch (Hz)")
    a.set_ylabel("wall s per audio s")
    a.set_title("cost (one job per core)")
    a.legend(fontsize=6, ncol=2)
    fig.tight_layout()
    fig.savefig(path, dpi=110)


# --- Main ----------------------------------------------------------------------------------


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--seconds", type=float, default=0.5)
    ap.add_argument("--only", nargs="*", help="settings as RANGE,FINE (e.g. 6,0)")
    ap.add_argument("--workers", type=int, default=7)
    ap.add_argument("--fresh", action="store_true", help="ignore cached references")
    ap.add_argument("--candidates", nargs="*", default=list(CANDIDATES))
    ap.add_argument("--tag", default="", help="suffix for the output files (e.g. a timing pass)")
    args = ap.parse_args()
    base = [(n, f) for n in range(2, 9) for f in (0.0, 1.0)]
    if args.only:
        base = [(int(x.split(",")[0]), float(x.split(",")[1])) for x in args.only]
    cond_ranges = [n for n in (4, 6, 8) if (n, 0.0) in base]
    settings_ = [(n, f, "") for n, f in base] + [
        (n, 0.0, c) for n in cond_ranges for c in CONDITIONS
    ]

    def job(n, f, c, mode, preset=None, seconds=args.seconds):
        return dict(
            range=n,
            fine=f,
            cond=c,
            over=CONDITIONS.get(c, {}),
            mode=mode,
            seconds=seconds,
            preset=preset,
            fresh=args.fresh,
        )

    with ProcessPoolExecutor(max_workers=args.workers) as ex:
        print(f"presets: {len(settings_)}")
        pre = list(
            ex.map(run_cached, [job(n, f, c, "preset", seconds=4.0) for n, f, c in settings_])
        )
        presets = {(r["range"], r["fine"], r["cond"]): preset_of(r) for r in pre}
        print(f"references: {len(settings_)}")
        refs = list(
            ex.map(
                run_cached, [job(n, f, c, "reference", presets[n, f, c]) for n, f, c in settings_]
            )
        )
        cjobs = [
            job(n, f, "", m, presets[n, f, ""])
            for n, f in base
            for m in args.candidates
            if not m.startswith("k-") or n in K_TABLES
        ]
        print(f"candidates: {len(cjobs)}")
        cands = list(ex.map(run_cached, cjobs))

    res: dict = {"reset": [], "spectrum": [], "alias": []}
    refd = {}
    for r in refs:
        m = reset_metrics(r)
        m.update(
            range=r["range"],
            fine=r["fine"],
            cond=r["cond"],
            wall_per_audio_s=r["wall_s"] / r["seconds"],
        )
        res["reset"].append(m)
        if r["cond"] or not m.get("oscillates"):
            continue
        refd[r["range"], r["fine"]] = (r, m)
        res["spectrum"].append(
            {"range": r["range"], "fine": r["fine"], "f_hz": m["f_hz"], **hi_spectrum(r)}
        )
    for (n, f), (r, m) in sorted(refd.items()):
        f0 = m["f_hz"]
        vb = {p: band_limit_ref(x) for p, x in r["v"].items()}
        ref = {"sig": signals(vb, FS, f0)}
        entry = {
            "range": n,
            "fine": f,
            "f_hz": f0,
            "ref_floor_db": ref["sig"]["out"]["inharmonic_db"],
            "ref_floor_n8_db": ref["sig"]["n8"]["inharmonic_db"],
            "ref_jitter_cents": ref["sig"]["out"]["jitter_cents"],
            "ref_wall_per_audio_s": r["wall_s"] / r["seconds"],
            "cands": {},
        }
        # the reference point-sampled: 96 kHz, and 192 kHz decimated as production is
        ideal = {"ideal-96k": ({p: x[::32] for p, x in r["v"].items()}, FS)}
        for k_ in (2, 4, 8, 16):
            n96 = len(r["v"]["out"][::32])
            ideal[f"ideal-{96 * k_}k"] = (
                {p: io.decimate(x[:: 32 // k_], k_, n96) for p, x in r["v"].items()},
                FS,
            )
            ideal[f"ideal-{96 * k_}k-aa"] = (
                {p: band_limit(x[:: 32 // k_], k_)[:n96] for p, x in r["v"].items()},
                FS,
            )
        for name, (v, rate) in ideal.items():
            c = {"sig": signals(v, rate, f0)}
            entry["cands"][name] = compare(c, ref)
        for c_ in cands:
            if (c_["range"], c_["fine"]) != (n, f):
                continue
            if "error" in c_:
                entry["cands"][c_["mode"]] = {"out": {"error": c_["error"]}}
                continue
            try:
                c = {"sig": signals(c_["v"], c_["rate"], f0)}
                cmp_ = compare(c, ref)
            except Exception as e:  # noqa: BLE001  (a candidate that doesn't oscillate)
                cmp_ = {"out": {"error": str(e)}}
            for p in cmp_.values():
                p["wall_per_audio_s"] = c_["wall_s"] / c_["seconds"]
            entry["cands"][c_["mode"]] = cmp_
        res["alias"].append(entry)

    OUT.mkdir(parents=True, exist_ok=True)
    stem = f"event_study{'_' + args.tag if args.tag else ''}"
    (OUT / f"{stem}.json").write_text(json.dumps(res, indent=1))
    plot(res, OUT / f"{stem}.png")
    for x in res["reset"]:
        if x.get("oscillates"):
            us = {
                k: (x[k] or 0) * 1e6 for k in ("reset_s", "fall_90_10_s", "rise_s", "plasma_tau_s")
            }
            print(
                f"C{x['range']} R6 {x['fine']:.0f} {x['cond'] or 'base':9s} f {x['f_hz']:8.1f}"
                f"  reset {us['reset_s']:7.1f} us  90-10 {us['fall_90_10_s']:6.2f}"
                f"  rise {us['rise_s']:5.2f}  f3dB {x['pulse_f3db_hz'] or 0:9.0f}"
                f"  48k {x['pulse_rel_db']['48k']:6.2f} dB  tau_plasma {us['plasma_tau_s']:5.1f} us"
            )
    for e in res["alias"]:
        floor = e["ref_floor_db"]
        print(f"C{e['range']} R6 {e['fine']:.0f} f {e['f_hz']:8.1f}  ref floor {floor:6.1f} dB")
        for name, c in e["cands"].items():
            o = c["out"]
            if "error" in o:
                print(f"   {name:20s} {o['error'][:80]}")
                continue
            n8 = c.get("n8", {})
            harm, spur = o["harm_err_max_db"] or 0, o["worst_spur_dbc"] or 0
            n8_db, cost = n8.get("inharmonic_db", float("nan")), o.get("wall_per_audio_s", 0)
            print(
                f"   {name:20s} {o['cents']:+8.2f} c  jit {o['jitter_cents']:6.2f} c"
                f"  harm {harm:6.2f} dB  inharm {o['inharmonic_db']:6.1f} dB  spur {spur:6.1f} dBc"
                f"  n8 inharm {n8_db:6.1f}  cost {cost:6.2f}x"
            )
    print("wrote", OUT / f"{stem}.json", OUT / f"{stem}.png")


if __name__ == "__main__":
    main()
