"""TM5's bias coupling, measured (docs/TAPE_PLAN.md, TM5; the user decides).

The Ampex 351's bias oscillator runs at ~100 kc, above the netlist's Nyquist frequency.
Two ways to couple it to the tape:

  A. literal: the oscillator, 1T5, the heads' bias network and the 6201 in a part of
     the circuit at a MHz rate, the medium reading the record head's whole current;
  B. carried at audio rate: the oscillator's bias amplitude (its + and - peaks) as a
     function of what it depends on, the medium regenerating the carrier.

The bias section (config/circuits/ampex_351_bias.yaml) is run literally at 3.84 MHz to
measure what B would have to carry and what it would miss:

  1. cost: the section's real-time factor at 1.92 / 3.84 / 7.68 MHz, and the peaks'
     agreement between rates;
  2. the bias against the record B+ (static sensitivity), and how fast the amplitude
     follows a B+ modulation (ripple at 30 Hz-10 kHz: AM depth over the static);
  3. the +/- asymmetry against NOISE BALANCE (even harmonics: a DC field on tape);
  4. the audio's interaction in the 6201 (the bias swings its plate through 1C10):
     the head's audio-band current with and without the bias reaching the head (what
     an audio-rate circuit computes), and the bias envelope's modulation by the audio.

    uv run --extra fast python scripts/tape_bias_study.py [--quick]

-> reports/tape/bias_coupling.json, bias_coupling.png
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import time

import numpy as np
from scipy.signal import resample_poly

from varimu.circuit import builder
from varimu.circuit.spec import load_circuit
from varimu.config import REPO_ROOT
from varimu.sim import fast
from varimu.sim.io import TransientSettings

CIRCUIT = REPO_ROOT / "config" / "circuits" / "ampex_351_bias.yaml"
OUT = REPO_ROOT / "reports" / "tape"
FS = 3.84e6  # 40 x the project's 96 kHz
SETTLE_S = 0.02


def run(
    over: dict,
    x: np.ndarray | None = None,
    dur_s: float = 0.005,
    fs: float = FS,
    settle_s: float = SETTLE_S,
):
    spec = load_circuit(CIRCUIT)
    c = builder.build(spec, over, cores="linear")
    s = TransientSettings.from_sim_settings(engine="circuitsim")
    s = dataclasses.replace(s, sample_rate=int(fs), oversample=1, settle_s=settle_s)
    if x is None:
        x = np.zeros(int(dur_s * fs))
    t0 = time.perf_counter()
    r = fast.run_transient(c.ir, x, settings=s)
    wall = time.perf_counter() - t0
    return r.vectors, wall, (len(x) / fs + settle_s)


def head_current(v) -> np.ndarray:
    return v["v(rbc)"] / 1000.0  # through 5R24 BIAS CALIBRATION, 1000 ohm


def split(i: np.ndarray, fs: float) -> tuple[np.ndarray, np.ndarray]:
    """The audio band (resampled to 96 kHz: a sharp anti-alias filter) and the rest."""
    k = int(round(fs / 96e3))
    a96 = resample_poly(i, 1, k)
    a = resample_poly(a96, k, 1)[: len(i)]
    return a96, i - a


def peaks(b: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Each half-cycle's extremum (index, value) for the positive and negative halves."""
    s = np.sign(b)
    z = np.nonzero(np.diff(s) != 0)[0]
    pi, pv, ni, nv = [], [], [], []
    for a, e in zip(z[:-1], z[1:], strict=False):
        seg = b[a + 1 : e + 1]
        if seg.size == 0:
            continue
        if seg.mean() > 0:
            j = a + 1 + int(np.argmax(seg))
            pi.append(j)
            pv.append(b[j])
        else:
            j = a + 1 + int(np.argmin(seg))
            ni.append(j)
            nv.append(-b[j])
    return np.array(pi), np.array(pv), np.array(ni), np.array(nv)


def steady(over: dict, fs: float = FS) -> dict:
    v, wall, dur = run(over, dur_s=0.005, fs=fs)
    i = head_current(v)
    _, b = split(i, fs)
    pi, pv, ni, nv = peaks(b)
    f = (len(pi) - 1) / ((pi[-1] - pi[0]) / fs)
    i_line = float(np.mean(v["v(brec)"] - v["v(brs)"]))  # through the 1 ohm source
    i_6201 = float(np.mean((v["v(b275)"] - v["v(p2a)"]) / 22e3))
    return {
        "f_hz": float(f),
        "pos_ma": float(1e3 * pv.mean()),
        "neg_ma": float(1e3 * nv.mean()),
        "asym_db": float(20 * np.log10(pv.mean() / nv.mean())),
        "erase_ma_rms": float(1e3 * np.std(v["v(ret)"]) / 8.2),
        "bosc_v": float(np.mean(v["v(bosc)"])),
        "line_ma": 1e3 * i_line,
        "osc_ma": 1e3 * (i_line - i_6201),
        "x_real_time": wall / dur,
    }


def ripple_am(fr: float, amp_v: float, base: dict) -> dict:
    """The bias peaks' modulation by a ripple of amp_v at fr on the record line, against
    the oscillator's own supply node's (1C2c, bosc): an audio-rate model would read bosc
    from the circuit, so what it must add is the oscillator's own dynamics. Settled
    0.6 s; drift terms in the fit."""
    dur = max(0.01, 6.0 / fr)
    v, _, _ = run({**base, "ripple_v": amp_v, "ripple_hz": fr}, dur_s=dur, settle_s=0.6)
    i = head_current(v)
    _, b = split(i, FS)
    pi, pv, ni, nv = peaks(b)
    keep = (pi > 0.1 * len(b)) & (pi < 0.9 * len(b))
    pi, pv = pi[keep], pv[keep]
    t = pi / FS

    def fit(y, tt):
        tc = tt - tt.mean()
        A = np.column_stack(
            [np.ones_like(tt), tc, tc**2, np.cos(2 * np.pi * fr * tt), np.sin(2 * np.pi * fr * tt)]
        )
        c, *_ = np.linalg.lstsq(A, y, rcond=None)
        return float(np.hypot(c[3], c[4]) / c[0]), float(np.arctan2(-c[4], c[3]))

    m_bias, ph_b = fit(pv, t)
    bo = v["v(bosc)"]
    tb = np.arange(len(bo)) / FS
    sel = (tb > 0.1 * tb[-1]) & (tb < 0.9 * tb[-1])
    m_bosc, ph_o = fit(bo[sel][::50], tb[sel][::50])
    return {
        "ripple_hz": fr,
        "ripple_v": amp_v,
        "bias_am_rel": m_bias,
        "bosc_mod_rel": m_bosc,
        "bias_per_bosc": m_bias / m_bosc,
        "phase_deg": float(np.degrees(ph_b - ph_o)),
    }


def audio_interaction(base: dict, grid_v_peak: float, f_hz: float = 1000.0) -> dict:
    """The 6201 driven at its grid: the head's audio band with and without bias in the
    head (4R70 at 1 TOhm: the oscillator still runs, so the supply is the same)."""
    # The run settles 0.6 s with the grid at 0 V (1C2b's 0.16 s at the 6201's B+ moves
    # with the bias it rectifies), then the tone fades in over 5 ms.
    n = int(0.03 * FS)
    t = np.arange(n) / FS
    x = grid_v_peak * np.sin(2 * np.pi * f_hz * t) * np.clip(t / 0.005, 0, 1)
    out = {}
    for name, ov in (("bias", {}), ("no_bias", {"r_bias_feed_ohm": 1.0e12})):
        v, _, _ = run({**base, **ov}, x=x, settle_s=0.6)
        i = head_current(v)
        a96, b = split(i, FS)
        out[name] = (a96, b, v)
    a, b0 = out["bias"][0], out["no_bias"][0]
    m = len(a) // 3  # past the fade-in
    a, b0 = a[m:], b0[m:]
    t96 = np.arange(len(a)) / 96e3
    w = np.hanning(len(a))

    def harm(y, k):
        ph = np.exp(-2j * np.pi * k * f_hz * t96)
        return 2 * abs(np.sum((y - y.mean()) * w * ph)) / np.sum(w)

    h = {nm: [harm(y, k) for k in (1, 2, 3)] for nm, y in (("bias", a), ("no_bias", b0))}
    diff = a - b0
    dc_shift = float(diff.mean())
    diff = diff - diff.mean()
    # The difference at the tone's harmonics and what's left (non-harmonic, or drift).
    hd = [harm(diff, k) for k in range(1, 11)]
    rest = diff.copy()
    for k in range(1, 11):
        ph = np.exp(2j * np.pi * k * f_hz * t96)
        cpx = 2 * np.sum(diff * w * np.conj(ph)) / np.sum(w)
        rest = rest - np.real(cpx * ph)
    # The bias's envelope against the audio.
    bias_part = out["bias"][1]
    pi, pv, ni, nv = peaks(bias_part)
    keep = pi > len(bias_part) // 3
    tp = pi[keep] / FS
    A = np.column_stack(
        [np.ones_like(tp)]
        + [f(2 * np.pi * k * f_hz * tp) for k in (1, 2) for f in (np.cos, np.sin)]
    )
    c, *_ = np.linalg.lstsq(A, pv[keep], rcond=None)
    am1 = float(np.hypot(c[1], c[2]) / c[0])
    am2 = float(np.hypot(c[3], c[4]) / c[0])
    p2a = out["bias"][2]["v(p2a)"]
    return {
        "grid_v_peak": grid_v_peak,
        "head_audio_ma_peak": float(1e3 * h["bias"][0]),
        "fundamental_change_db": float(20 * np.log10(h["bias"][0] / h["no_bias"][0])),
        "h2_dbc": {k: float(20 * np.log10(v[1] / v[0])) for k, v in h.items()},
        "h3_dbc": {k: float(20 * np.log10(v[2] / v[0])) for k, v in h.items()},
        "difference_harmonics_db": [float(20 * np.log10(x / h["no_bias"][0] + 1e-30)) for x in hd],
        "difference_rest_db": float(
            20
            * np.log10(
                np.std(rest[len(rest) // 10 : -len(rest) // 10]) * np.sqrt(2) / h["no_bias"][0]
            )
        ),
        "head_dc_shift_ua": 1e6 * dc_shift,
        "bias_am_by_audio_1f": am1,
        "bias_am_by_audio_2f": am2,
        "bias_peak_ma": float(1e3 * c[0]),
        "p2a_min_v": float(p2a[len(p2a) // 3 :].min()),
        "p2a_max_v": float(p2a[len(p2a) // 3 :].max()),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--quick", action="store_true")
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    res: dict = {}

    base: dict = {}
    s0 = steady(base)
    res["steady"] = s0
    print("steady", s0)

    res["rates"] = {}
    for fs in (1.92e6, 7.68e6):
        r = steady(base, fs=fs)
        res["rates"][f"{fs / 1e6:.2f}MHz"] = {
            "pos_vs_3.84_pct": 100 * (r["pos_ma"] / s0["pos_ma"] - 1),
            "f_vs_3.84_pct": 100 * (r["f_hz"] / s0["f_hz"] - 1),
            "x_real_time": r["x_real_time"],
        }
        print(fs, res["rates"][f"{fs / 1e6:.2f}MHz"])

    v0 = 299.3  # the record line at idle (ampex_351.yaml, oscillator 1)
    sweep = []
    for k in [0.95, 1.05] if a.quick else [0.9, 0.95, 1.0, 1.05, 1.1]:
        r = steady({"b_rec_v": v0 * k}) if k != 1.0 else s0
        sweep.append(
            {
                "b_rec_v": v0 * k,
                **{
                    q: r[q]
                    for q in ("bosc_v", "pos_ma", "neg_ma", "f_hz", "osc_ma", "erase_ma_rms")
                },
            }
        )
    res["b_plus_sweep"] = sweep
    lv = np.log([p["bosc_v"] for p in sweep])
    li = np.log([p["pos_ma"] for p in sweep])
    res["bias_per_b_plus"] = float(np.polyfit(lv, li, 1)[0])
    print("dln(bias)/dln(bosc)", res["bias_per_b_plus"])

    res["ripple"] = []
    for fr in [120.0, 2000.0] if a.quick else [30.0, 120.0, 500.0, 2000.0, 10000.0]:
        # bosc follows the line through 1R59 / 1C2c (10.6 Hz): scale the ripple up
        r = ripple_am(fr, min(20.0, 2.0 * max(1.0, fr / 10.6)), base)
        r["am_over_static"] = r["bias_per_bosc"] / res["bias_per_b_plus"]
        res["ripple"].append(r)
        print("ripple", r)

    res["noise_balance"] = []
    for nb in [0.0, 0.5, 1.0] if a.quick else [0.0, 0.25, 0.5, 0.75, 1.0]:
        r = steady({"noise_balance": nb})
        res["noise_balance"].append(
            {"noise_balance": nb, "asym_db": r["asym_db"], "pos_ma": r["pos_ma"]}
        )
        print("nb", nb, r["asym_db"])

    res["audio"] = []
    for g in [1.1, 4.4] if a.quick else [0.55, 1.1, 2.2, 4.4]:
        r = audio_interaction(base, g)
        res["audio"].append(r)
        print("audio", json.dumps(r))

    (OUT / "bias_coupling.json").write_text(json.dumps(res, indent=2))
    plot(res, OUT / "bias_coupling.png")
    print("->", OUT / "bias_coupling.json")


def plot(res: dict, path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(1, 3, figsize=(13, 4))
    sw = res["b_plus_sweep"]
    ax[0].plot([p["bosc_v"] for p in sw], [p["pos_ma"] for p in sw], "o-")
    ax[0].set(
        xlabel="oscillator B+, 1C2c (V)",
        ylabel="bias peak in the head (mA)",
        title="Bias against B+",
    )
    rp = res["ripple"]
    ax[1].semilogx([r["ripple_hz"] for r in rp], [r["am_over_static"] for r in rp], "o-")
    ax[1].axhline(1, color="0.6", lw=0.8)
    ax[1].set(
        xlabel="B+ modulation (Hz)",
        ylabel="bias AM / (static x bosc modulation)",
        title="How fast the amplitude follows",
    )
    au = res["audio"]
    g = [r["head_audio_ma_peak"] for r in au]
    ax[2].semilogx(
        g, [max(r["difference_harmonics_db"]) for r in au], "o-", label="at the harmonics (max)"
    )
    ax[2].semilogx(g, [r["difference_rest_db"] for r in au], "^-", label="the rest (drift, other)")
    ax[2].semilogx(
        g,
        [20 * np.log10(r["bias_am_by_audio_1f"] + 1e-12) for r in au],
        "s-",
        label="bias AM by the audio (1f)",
    )
    ax[2].set(
        xlabel="head audio current (mA peak)",
        ylabel="dB",
        title="What an audio-rate circuit misses",
    )
    ax[2].legend(fontsize=8)
    for a in ax:
        a.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(path, dpi=110)


if __name__ == "__main__":
    main()
