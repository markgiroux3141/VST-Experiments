# ruff: noqa: E501  (the regexes and fmt: skip tables run long)
"""Fit the beyerdynamic M 160's ribbon motor to beyer's figures (docs/CHAINS_PLAN.md WP17).

    uv run python scripts/fit_m160.py [--rounds N] [--write]

The base geometry is published_points.yaml's "RIBBON_M160": the double ribbon as one
equivalent ribbon on RIBBON_77DX's circuit (the ribbon's back on a connector cavity, a damped
labyrinth, one fixed slot to the rear: the hypercardioid). No construction is published, so the
unknowns are fitted one figure each:

    body.radius_m, depth_m    the 1 m curve from 1 to 18 kHz re 1 kHz
                              (data/datasheets/beyer_m160_response.csv)
    ribbon.resonance_hz,      the 1 m curve's bass, 40 Hz-1 kHz re 1 kHz (the screen damps the
    screen_f's rayl           resonance in place)
    the slot (width, breadth) a hypercardioid's pattern at 250 Hz and 1 kHz: 90 deg -12 dB, 180
                              deg -6 dB (0.25 + 0.75 cos), 110 deg at most -25 dB (beyer: 'rear
                              attenuation at 1 kHz > 25 dB at 110 deg')
    magnet.b_gap_t            beyer's 1.0 mV/Pa open circuit at 1 kHz

The response is the open-circuit EMF across the ribbon into M160_OT's primary inductance times
its turns ratio (1:26), a plane wave in the horizontal plane (the ribbon upright: beyer's two red
dots on the vertical). Numbers -> reports/mics/beyer_m160_fit.json, plot -> beyer_m160_fit.png;
`--write` puts the fitted values into published_points.yaml (then `varimu fit-devices --only
RIBBON_M160`).
"""

from __future__ import annotations

import argparse
import copy
import csv
import json
import re

import numpy as np
from fit_77dx import _nm, entries, motor

from varimu.config import DATA_DIR, REPO_ROOT
from varimu.devices.library import _plain, _published
from varimu.mics import bor, networks

N_TURNS = 26.0  # M160_OT@1 (config/designs/beyer_m160_ot.yaml)
L_PRIMARY_H = 16.0e-3  # M160_OT@1's primary in its core's linear limit (its compile report)
SENS_V_PER_PA = 1.0e-3  # beyer: 1.0 mV/Pa open circuit at 1 kHz
TOP_HZ = (1000.0, 18000.0)
BASS_HZ = (40.0, 1000.0)
ANGLES_DEG = (0.0, 90.0, 110.0, 180.0)
ROWS = [(f, a, db, bound) for f in (250.0, 1000.0)
        for a, db, bound in ((90.0, -12.0, False), (110.0, -25.0, True), (180.0, -6.0, False))]  # fmt: skip
PUBLISHED = DATA_DIR / "datasheets" / "published_points.yaml"
REPORT = REPO_ROOT / "reports" / "mics"


def curve():
    with open(DATA_DIR / "datasheets" / "beyer_m160_response.csv", encoding="utf-8") as fh:
        rows = [x for x in csv.DictReader(fh) if x["curve"] == "1m"]
    return np.array([float(x["freq_hz"]) for x in rows]), np.array([float(x["db"]) for x in rows])


def base() -> dict:
    return _plain(_published()["RIBBON_M160"]["geometry"])


def unknowns(g: dict) -> dict:
    net = {e["name"]: e for e in g["network"]}
    return {
        "radius_m": g["body"]["radius_m"], "depth_m": g["body"]["depth_m"],
        "resonance_hz": g["ribbon"]["resonance_hz"], "b_gap_t": g["magnet"]["b_gap_t"],
        "screen_rayl": net["screen_f"]["rayl"],
        "slot_w_m": net["slot"]["width_m"], "slot_b_m": net["slot"]["breadth_m"],
    }  # fmt: skip


def geometry(g0: dict, u: dict) -> dict:
    g = copy.deepcopy(g0)
    g["body"].update(radius_m=u["radius_m"], depth_m=u["depth_m"])
    g["ribbon"]["resonance_hz"] = u["resonance_hz"]
    g["magnet"]["b_gap_t"] = u["b_gap_t"]
    net = {e["name"]: e for e in g["network"]}
    gap, length = net["rad_f"]["width_m"], g["ribbon"]["length_m"]
    for n in ("chan_f_a", "chan_f_b"):
        net[n]["length_m"] = 0.25 * u["depth_m"]
    net["cav_f"]["volume_m3"] = gap * length * 0.5 * u["depth_m"]
    net["screen_f"]["rayl"] = u["screen_rayl"]
    net["slot"].update(width_m=u["slot_w_m"], breadth_m=u["slot_b_m"])
    net["rad_r"].update(width_m=u["slot_w_m"], length_m=u["slot_b_m"])
    return g


def response(g: dict, f: np.ndarray, theta_deg=(0.0,)) -> np.ndarray:
    """Open-circuit volts at the 200 ohm output per pascal (freqs, angles), horizontal plane."""
    fr, rr = entries(g["body"], bor.entry_size(g), f, theta_deg)
    c = motor(g)
    out = np.zeros(fr.shape, complex)
    for j in range(fr.shape[1]):
        out[:, j] = N_TURNS * networks.moving_coil_response(
            c, f, (fr[:, j], rr[:, j]), l_load_h=L_PRIMARY_H
        )
    return out


def target(band):
    f, db = curve()
    ref = np.interp(np.log(1000.0), np.log(f), db)
    k = (f >= band[0]) & (f <= band[1])
    fk = np.unique(np.r_[f[k], 1000.0])
    return fk, np.interp(np.log(fk), np.log(f), db) - ref


def curve_rms(g, band) -> float:
    f, t = target(band)
    h = response(g, f)[:, 0]
    i = int(np.argmin(np.abs(f - 1000.0)))
    d = 20 * np.log10(np.abs(h / h[i])) - t
    return float(np.sqrt(np.mean(d**2)))


def pattern(g) -> dict:
    fs = np.array(sorted({r[0] for r in ROWS}))
    h = response(g, fs, ANGLES_DEG)
    rel = 20 * np.log10(np.abs(h / h[:, :1]))
    return {(float(f), a): float(rel[i, ANGLES_DEG.index(a)]) for i, f in enumerate(fs)
            for a in ANGLES_DEG}  # fmt: skip


def polar_errors(g) -> np.ndarray:
    p = pattern(g)
    return np.array([max(0.0, p[(f, a)] - db) if bound else p[(f, a)] - db
                     for f, a, db, bound in ROWS])  # fmt: skip


def sensitivity(g) -> float:
    return float(abs(response(g, np.array([1000.0]))[0, 0]))


def fit_round(g0, u, log) -> dict:
    u = dict(u)

    def with_(**kw):
        return geometry(g0, {**u, **kw})

    s = _nm(lambda x: curve_rms(with_(radius_m=x[0] * 1e-3, depth_m=x[1] * 1e-3), TOP_HZ)
            if 2.0 < x[0] < 30.0 and 1.0 < x[1] < 30.0 else 99.0,
            [u["radius_m"] * 1e3, u["depth_m"] * 1e3], 60, 0.05)  # fmt: skip
    u["radius_m"], u["depth_m"] = round(s.x[0] * 1e-3, 7), round(s.x[1] * 1e-3, 7)
    log(f"body {u['radius_m'] * 1e3:.2f} x {u['depth_m'] * 1e3:.2f} mm: top rms {s.fun:.2f} dB")
    s = _nm(lambda x: curve_rms(with_(resonance_hz=x[0], screen_rayl=np.exp(x[1])), BASS_HZ)
            if 5.0 < x[0] < 120.0 else 99.0,
            [u["resonance_hz"], np.log(u["screen_rayl"])], 120, 0.01)  # fmt: skip
    u["resonance_hz"], u["screen_rayl"] = round(float(s.x[0]), 2), round(float(np.exp(s.x[1])), 3)
    log(
        f"resonance {u['resonance_hz']} Hz, screen {u['screen_rayl']} rayl: bass rms {s.fun:.2f} dB"
    )

    def slot_cost(x):
        w, b = float(np.exp(x[0])), float(np.exp(x[1]))
        if not (10e-6 < w < 5e-3 and 0.5e-3 < b <= 0.022):
            return 1e4
        return float(np.sum(polar_errors(with_(slot_w_m=w, slot_b_m=b)) ** 2))

    s = _nm(slot_cost, [np.log(u["slot_w_m"]), np.log(u["slot_b_m"])], 150, 1e-3)
    u["slot_w_m"], u["slot_b_m"] = round(float(np.exp(s.x[0])), 8), round(float(np.exp(s.x[1])), 8)
    p = pattern(with_())
    log(f"slot {u['slot_w_m'] * 1e3:.3f} x {u['slot_b_m'] * 1e3:.2f} mm: "
        + ", ".join(f"{f:g} Hz {a:g} deg {v:.1f}" for (f, a), v in p.items() if a))  # fmt: skip
    for _ in range(3):
        u["b_gap_t"] *= SENS_V_PER_PA / sensitivity(with_())
    u["b_gap_t"] = round(u["b_gap_t"], 4)
    log(f"B {u['b_gap_t']} T: {sensitivity(with_()) * 1e3:.3f} mV/Pa")
    return u


def summary(g) -> dict:
    f, t = target((40.0, 18000.0))
    h = response(g, f)[:, 0]
    d = 20 * np.log10(np.abs(h / h[int(np.argmin(np.abs(f - 1000.0)))])) - t
    out = {"sensitivity_mv_per_pa": round(1e3 * sensitivity(g), 3)}
    for lo, hi in ((40, 1000), (1000, 10000), (10000, 18000)):
        k = (f >= lo) & (f <= hi)
        out[f"m_{lo}_{hi}_rms_db"] = round(float(np.sqrt(np.mean(d[k] ** 2))), 2)
        out[f"m_{lo}_{hi}_max_db"] = round(float(np.max(np.abs(d[k]))), 2)
    fs = np.array([250.0, 1000.0, 4000.0, 8000.0])
    hp = response(g, fs, ANGLES_DEG)
    out["pattern_db"] = {f"{fz:g} Hz": {f"{a:g}": round(float(20 * np.log10(abs(hp[i, j] / hp[i, 0]))), 2)
                                        for j, a in enumerate(ANGLES_DEG)}
                         for i, fz in enumerate(fs)}  # fmt: skip
    return out


def plot(g) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(1, 2, figsize=(13, 4.8))
    f = np.geomspace(40, 18000, 200)
    h = response(g, f)[:, 0]
    fm, dm = curve()
    ax[0].semilogx(fm, dm, "k.", label="beyer, 1 m")
    ax[0].semilogx(
        f, 20 * np.log10(np.abs(h / np.interp(1000.0, f, np.abs(h)))), "C0", label="model"
    )
    ax[0].set(xlabel="Hz", ylabel="dB re 1 kHz", ylim=(-12, 6), title="M 160, on axis, plane wave")
    ax[0].grid(True, which="both", alpha=0.3)
    ax[0].legend()
    th = np.arange(0.0, 181.0, 5.0)
    for i, fz in enumerate((250.0, 1000.0, 4000.0, 8000.0)):
        hp = response(g, np.array([fz]), th)[0]
        ax[1].plot(th, 20 * np.log10(np.abs(hp / hp[0])), f"C{i}", label=f"{fz:g} Hz")
    ax[1].plot(th, 20 * np.log10(np.abs(0.25 + 0.75 * np.cos(np.radians(th))) + 1e-9), "k--",
               label="hypercardioid")  # fmt: skip
    ax[1].set(xlabel="degrees (horizontal)", ylabel="dB", ylim=(-35, 2), title="the model")
    ax[1].grid(True, alpha=0.3)
    ax[1].legend()
    fig.tight_layout()
    fig.savefig(REPORT / "beyer_m160_fit.png", dpi=100)


def write_published(u: dict) -> None:
    """The fitted values into published_points.yaml's "RIBBON_M160" block, in place."""
    text = PUBLISHED.read_text(encoding="utf-8")
    i = text.index('"RIBBON_M160":')
    j = text.index("\n# BJTs (the Gummel-Poon subset", i)
    blk = text[i:j]

    def sub(pattern, value, blk):
        new, n = re.subn(
            pattern, lambda m: m.group(1) + repr(float(value)) + m.group(2), blk, count=1
        )
        assert n == 1, pattern
        return new

    blk = sub(r"(      radius_m: \{value: )[^}]+(\})", u["radius_m"], blk)
    blk = sub(r"(      depth_m: \{value: )[^}]+(\})", u["depth_m"], blk)
    blk = sub(r"(      resonance_hz: \{value: )[^}]+(\})", u["resonance_hz"], blk)
    blk = sub(r"(      b_gap_t: \{value: )[^}]+(\})", u["b_gap_t"], blk)
    blk = sub(
        r"(name: screen_f, kind: screen, a: fo, b: fs, rayl: \{value: )[^}]+(\})",
        u["screen_rayl"],
        blk,
    )
    blk = sub(
        r"(name: slot, kind: slit, a: r, b: ro, width_m: \{value: )[^}]+(\})", u["slot_w_m"], blk
    )
    blk = sub(
        r"(name: slot, kind: slit, a: r, b: ro, width_m: \{value: [^}]+\}, breadth_m: \{value: )[^}]+(\})",
        u["slot_b_m"],
        blk,
    )
    blk = sub(
        r"(name: rad_r, kind: radiation, a: rear, b: ro, width_m: \{value: )[^}]+(\})",
        u["slot_w_m"],
        blk,
    )
    blk = sub(
        r"(name: rad_r, kind: radiation, a: rear, b: ro, width_m: \{value: [^}]+\}, length_m: \{value: )[^}]+(\})",
        u["slot_b_m"],
        blk,
    )
    g = geometry(base(), u)
    net = {e["name"]: e for e in g["network"]}
    blk = sub(
        r"(name: chan_f_a, kind: slit, a: fs, b: cf, width_m: \{value: [^}]+\}, breadth_m: \{value: [^}]+\}, length_m: \{value: )[^}]+(\})",
        net["chan_f_a"]["length_m"],
        blk,
    )
    blk = sub(
        r"(name: chan_f_b, kind: slit, a: cf, b: f, width_m: \{value: [^}]+\}, breadth_m: \{value: [^}]+\}, length_m: \{value: )[^}]+(\})",
        net["chan_f_b"]["length_m"],
        blk,
    )
    blk = sub(
        r"(name: cav_f, kind: cavity, a: cf, volume_m3: \{value: )[^}]+(\})",
        net["cav_f"]["volume_m3"],
        blk,
    )
    PUBLISHED.write_text(text[:i] + blk + text[j:], encoding="utf-8")
    print("wrote RIBBON_M160 to", PUBLISHED)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--rounds", type=int, default=2)
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()
    g0 = base()
    u = unknowns(g0)
    for k in range(args.rounds):
        u = fit_round(g0, u, lambda s, k=k: print(f"[round {k + 1}] {s}", flush=True))
    g = geometry(g0, u)
    out = {"unknowns": u, **summary(g)}
    REPORT.mkdir(parents=True, exist_ok=True)
    (REPORT / "beyer_m160_fit.json").write_text(json.dumps(out, indent=1))
    print(json.dumps(out, indent=1))
    plot(g)
    if args.write:
        write_published(u)


if __name__ == "__main__":
    main()
