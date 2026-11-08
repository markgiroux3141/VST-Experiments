"""The Novachord's live tier against the reference (docs/NOVACHORD_PLAN.md, NV4's done-when).

    uv run --extra fast python scripts/novachord_live_check.py
        [--only chord percussive strings vibrato] [--quality draft]

Each scenario is rendered twice with the amplifier off (the preamplifier's 500 ohm line):
through config/circuits/novachord.yaml (the literal instrument, scripts/novachord_render.py:
the keys as switch controls updated at each event; the quality's own method) and through
config/circuits/novachord_live.yaml (the oscillators, dividers and keys as circuitsim's keys
medium, played by note events) as the app plays it: the trapezoidal rule (the device's
`method`) and make_novachord.live_partition(). Both settle the same way first (sim_settings'
settle_s, every key up).

The dividers' phases (which of its input's cycles a divider fires on) are the power-up's in
either, so the waveforms aren't compared sample by sample. Compared instead:
  - the envelope: the line's rms in 20 ms windows, in dB, where the reference is within
    40 dB of its loudest window (max and rms of the difference);
  - the spectrum over the held part: third-octave bands 40 Hz-20 kHz within 50 dB of the
    loudest band (max and rms of the difference; where two notes' partials nearly coincide
    the band beats with the dividers' phases, which no two runs share);
  - the level over the held part (dB) and the control tubes' B+ (`bct`, V);
  - the pitch (the vibrato scenario: A6 alone, NORMAL on): the line's fundamental tracked
    through its zero crossings, smoothed over 20 ms, from 1.5 s on (the reeds' swing has
    built up): its mean in cents from 1760 Hz, its peak-to-peak depth and its rate;
  - the speed of both (x real time over the simulated time, settling included; the live
    one's start-up too).
Writes reports/novachord/live_check.json.
"""

from __future__ import annotations

import argparse
import dataclasses
import importlib.util
import json
import time

import numpy as np

from varimu.circuit import builder, spec
from varimu.circuit.ir import VoltageProbe
from varimu.config import CONFIG_DIR, REPO_ROOT
from varimu.rhodes import midi
from varimu.sim import fast
from varimu.sim.io import TransientSettings

OUT = REPO_ROOT / "reports" / "novachord"
#: The method the app plays the live tier with (panel.rs, the device's `method`).
LIVE_METHOD = "trap"
SCENARIOS = {
    # name: (panel, [(t_on, t_off, midi note)], seconds)
    "chord": ({"attack": 4}, [(0.05, 0.65, n) for n in (45, 57, 61, 64, 69)], 1.0),
    "percussive": ({"attack": 1}, [(0.05, 0.45, n) for n in (57, 64)], 0.7),
    "strings": ({"attack": 7}, [(0.05, 1.05, n) for n in (57, 60, 64)], 1.4),
    "vibrato": ({"attack": 4, "normal_vibrato": 1}, [(0.05, 3.45, 93)], 3.5),
}


def _script(name):
    sp = importlib.util.spec_from_file_location(name, REPO_ROOT / "scripts" / f"{name}.py")
    m = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(m)
    return m


def reference(panel, notes, seconds, quality):
    nr = _script("novachord_render")
    ev = []
    for on, off, n in notes:
        ev += [midi.Event(on, "on", n, 100), midi.Event(off, "off", n, 0)]
    ev.sort(key=lambda e: e.t_s)
    sets = {**panel, "amp": 0}
    v, el, _ = nr.render(ev, seconds, quality, sets, 4, probes=("out", "bct"), progress=None)
    return v, el


def live(panel, notes, seconds, quality):
    import circuitsim

    mk = _script("make_novachord")
    s = spec.load_circuit(CONFIG_DIR / "circuits" / "novachord_live.yaml")
    ir = builder.build_ir(s, spec.resolve(s, {**panel, "amp": 0}))
    ir = dataclasses.replace(ir, probes=tuple(VoltageProbe(p) for p in ("out", "bct")))
    st = TransientSettings.from_sim_settings(engine="circuitsim", quality=quality)
    st = dataclasses.replace(st, method=LIVE_METHOD)
    fs = st.sim_rate
    settle = int(round(st.settle_s * fs))
    n = settle + int(round(seconds * fs))
    ev = []
    for on, off, note in notes:
        ev += [
            (settle + int(round(on * fs)), "on", note, 100),
            (settle + int(round(off * fs)), "off", note, 0),
        ]
    ev.sort()
    t0 = time.perf_counter()
    out = circuitsim.simulate(
        ir.to_json(), np.zeros(n), 1.0 / fs, st.method, solver=st.solver,
        reltol=st.newton_reltol, vntol=st.newton_vntol, input_order=st.input_order,
        newton_reuse=st.newton_reuse, tube_tables=st.tube_tables, partition=mk.live_partition(),
        partition_coupling=st.partition_coupling, error_abstol=st.error_abstol,
        error_reltol=st.error_reltol, step_selection=st.step_selection,
        error_norm=st.error_norm, notes=ev,
    )  # fmt: skip
    el = time.perf_counter() - t0
    v = {p.split("(")[1][:-1]: np.asarray(a)[settle:] for p, a in out.items()}
    return v, el, fs


def env_db(y, fs, win_s=0.02):
    m = int(win_s * fs)
    k = len(y) // m
    y = y[: k * m].reshape(k, m)
    y = y - y.mean(axis=1, keepdims=True)
    return 20 * np.log10(np.sqrt(np.mean(y**2, axis=1)) + 1e-12)


def bands_db(y, fs):
    from scipy.signal import welch

    f, p = welch(y - y.mean(), fs, nperseg=8192)
    out = []
    fc = 40.0
    while fc < 20000:
        lo, hi = fc / 2 ** (1 / 6), fc * 2 ** (1 / 6)
        sel = (f >= lo) & (f < hi)
        out.append((fc, 10 * np.log10(p[sel].sum() + 1e-30)))
        fc *= 2 ** (1 / 3)
    return out


def pitch(y, fs, f0, start_s):
    """The fundamental near f0 over time: band-passed, upward zero crossings, each period's
    frequency, smoothed over 20 ms. (mean cents from f0, peak-to-peak cents, rate Hz)."""
    from scipy.signal import butter, sosfiltfilt

    sos = butter(4, [f0 / 1.3, f0 * 1.3], btype="band", fs=fs, output="sos")
    x = sosfiltfilt(sos, y - y.mean())[int(start_s * fs) :]
    i = np.nonzero((x[:-1] < 0) & (x[1:] >= 0))[0] + 1
    tc = (i - 1) + x[i - 1] / (x[i - 1] - x[i])
    f = fs / np.diff(tc)
    t = 0.5 * (tc[1:] + tc[:-1]) / fs
    k = max(1, int(0.02 * f0))
    c = 1200 * np.log2(np.convolve(f, np.ones(k) / k, mode="valid") / f0)
    tt = t[k // 2 : k // 2 + len(c)]
    # the rate: the strongest component of the pitch track between 3 and 15 Hz
    g = np.interp(np.arange(tt[0], tt[-1], 1e-3), tt, c)
    spec_ = np.abs(np.fft.rfft((g - g.mean()) * np.hanning(len(g))))
    fr = np.fft.rfftfreq(len(g), 1e-3)
    sel = (fr > 3) & (fr < 15)
    rate = float(fr[sel][np.argmax(spec_[sel])]) if sel.any() else 0.0
    return float(np.mean(c)), float(np.ptp(c)), rate


def compare(name, quality):
    panel, notes, seconds = SCENARIOS[name]
    print(f"{name}: the reference ...", flush=True)
    rv, rel = reference(panel, notes, seconds, quality)
    print(f"  {rel:.0f} s; the live tier ...", flush=True)
    lv, lel, fs = live(panel, notes, seconds, quality)
    print(f"  {lel:.1f} s", flush=True)
    n = min(len(rv["out"]), len(lv["out"]))
    r, li = rv["out"][:n], lv["out"][:n]
    er, el_ = env_db(r, fs), env_db(li, fs)
    keep = er > er.max() - 40
    d = el_[keep] - er[keep]
    on = min(o for o, _, _ in notes)
    off = min(f for _, f, _ in notes)
    held = slice(int((on + 0.25 * (off - on)) * fs), int(off * fs))
    br, bl = bands_db(r[held], fs), bands_db(li[held], fs)
    top = max(b for _, b in br)
    bd = [lb - rb for (fc, rb), (_, lb) in zip(br, bl, strict=True) if rb > top - 50]

    def lvl(y):
        y = y[held] - y[held].mean()
        return 20 * np.log10(np.sqrt(np.mean(y**2)) + 1e-12)

    def rounded(x):
        return [round(float(v), 2) for v in x]

    res = {
        "panel": panel,
        "notes": notes,
        "envelope_db": {
            "max_abs": round(float(np.abs(d).max()), 2),
            "rms": round(float(np.sqrt(np.mean(d**2))), 2),
        },
        "bands_db": {
            "max_abs": round(float(np.abs(bd).max()), 2),
            "rms": round(float(np.sqrt(np.mean(np.square(bd)))), 2),
        },
        "level_db": {"reference": round(float(lvl(r)), 2), "live": round(float(lvl(li)), 2)},
        "bct_v": {
            "reference": round(float(rv["bct"][held].mean()), 2),
            "live": round(float(lv["bct"][held].mean()), 2),
        },
        # both runs include the settling (sim_settings' settle_s), the live one its start-up
        "x_real_time": {
            "reference": round(rel / (seconds + 1.0), 1),
            "live": round(lel / (seconds + 1.0), 2),
        },
        "bands": {
            "fc_hz": [round(fc, 1) for fc, _ in br],
            "reference_db": rounded(b for _, b in br),
            "live_db": rounded(b for _, b in bl),
        },
        "envelopes_db": {"reference": rounded(er), "live": rounded(el_)},
    }
    if name == "vibrato":
        pr, pl = pitch(r, fs, 1760.0, 1.5), pitch(li, fs, 1760.0, 1.5)
        res["vibrato"] = {
            what: {"reference": round(a, 2), "live": round(b, 2)}
            for what, a, b in zip(("mean_cents", "depth_cents_pp", "rate_hz"), pr, pl, strict=True)
        }
    print(json.dumps({k: v for k, v in res.items() if k not in ("envelopes_db", "bands")}))
    return res


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--only", nargs="*", default=list(SCENARIOS))
    ap.add_argument("--quality", default="draft")
    args = ap.parse_args()
    fast.check_build()
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / "live_check.json"
    have = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    for name in args.only:
        have[name] = compare(name, args.quality)
        path.write_text(json.dumps(have, indent=1), encoding="utf-8")
    print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
