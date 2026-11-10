# ruff: noqa: E501, UP031  (the generated published_points block carries long source comments)
"""Fit the Royer R-121's ribbon motor to Royer's curve (docs/CHAINS_PLAN.md WP16).

    uv run python scripts/fit_r121.py [--grid] [--write]

RIBBON_R121 (published_points.yaml) is Royer's ribbon (the manual: 1.5 x 3/16 in x 2.5 um
aluminium in the Flux-Frame's neodymium gap) on Olson's circuit, the pole pieces as a baffle like
fit_4038.py's, the ribbon **offset** toward the front (the manual's "offset ribbon": the front
channel OFFSET of the pole pieces' depth, the rear the rest). Fitted, one figure each, to Royer's
chart (data/datasheets/royer_r121_response.csv) and sensitivity:

    body.radius_m, depth_m   the top: the chart from 1 kHz to 16 kHz re 1 kHz
    ribbon.resonance_hz, q   the bass: 25 Hz to 1 kHz re 1 kHz (with the screens' resistance)
    magnet.b_gap_t           the sensitivity: -49 dB re 1 V/Pa (3.55 mV/Pa) open circuit

The response is the open-circuit EMF across the ribbon times the transformer's turns ratio
(R121_OT@1: 20 : 800), its primary inductance as the load, a plane wave in the horizontal plane
(the ribbon upright). `--write` replaces the RIBBON_R121 block of published_points.yaml.
Numbers -> reports/mics/royer_r121_fit.json, plot -> royer_r121_fit.png.
"""

from __future__ import annotations

import argparse
import copy
import csv
import json

import numpy as np
from scipy.optimize import minimize

from varimu.config import DATA_DIR, REPO_ROOT
from varimu.devices import moving_coil as mc
from varimu.devices import ribbon
from varimu.devices.library import _plain, _published
from varimu.mics import bor, networks

N_TURNS = 40.0  # R121_OT@1: 20 : 800
L_PRIMARY_H = 11.1e-3  # R121_OT@1's primary in its core's linear limit (its report)
SENS_V_PER_PA = 3.55e-3  # royer: -49 dB re 1 V/Pa (the manual; the 2000 cut sheet -50 dBV)
BODY0 = {"radius_m": 0.0125, "depth_m": 0.012}  # a first guess (`--grid`)
TOP_HZ = (1000.0, 16000.0)
BASS_HZ = (25.0, 1000.0)
F_RES_BOUNDS = (8.0, 60.0)  # provisional: model knowledge (a ribbon's in-vacuo tuning)
RAYL0 = 4.0
SLOT_W_M = 5.0e-3  # the channel: the 3/16 in ribbon and two 125 um clearances
OFFSET = 0.3  # provisional: model knowledge (the front channel's share of the depth: royer's "offset ribbon ... towards the front")
REPORT = REPO_ROOT / "reports" / "mics"


def curves():
    with open(DATA_DIR / "datasheets" / "royer_r121_response.csv", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    out = {}
    for k in ("axial",):
        r = [x for x in rows if x["curve"] == k]
        f = np.array([float(x["freq_hz"]) for x in r])
        db = np.array([float(x["db"]) for x in r])
        w = np.array([0.3 if x["quality"] == "coarse" else 1.0 for x in r])
        out[k] = (f, db, w)
    return out


def polars():
    return {}  # the chart's polar (a figure-8) not digitized


def geometry(
    base: dict,
    radius_m: float,
    depth_m: float,
    f_res: float,
    q: float,
    b: float,
    rayl: float | None = None,
):
    """The base geometry (published_points "RIBBON_R121") with its body, the channels as T
    sections half the depth each side, and the fitted values."""
    g = copy.deepcopy(base)
    g["body"] = {"form": "baffle", "radius_m": radius_m, "depth_m": depth_m}
    g["ribbon"]["resonance_hz"] = f_res
    g["ribbon"]["q"] = q
    g["magnet"]["b_gap_t"] = b
    for e in g["network"]:
        if rayl is not None and str(e["name"]).startswith("screen_"):
            e["rayl"] = rayl
    length = float(g["ribbon"]["length_m"])
    net = []
    for e in g["network"]:
        name = str(e["name"])
        if name.startswith(("chan_f", "chan_r", "cav_")):
            continue
        net.append(e)
        if name == "screen_f":  # after the front screen: the front channel to the ribbon
            net += _channel("f", "fs", "f", depth_m, length)
    # the rear channel between the ribbon and the rear screen
    i = next(k for k, e in enumerate(net) if e["name"] == "screen_r")
    net[i:i] = _channel("r", "r", "rs", depth_m, length)
    g["network"] = net
    return g


def _channel(side: str, a: str, b: str, depth_m: float, length_m: float) -> list[dict]:
    share = OFFSET if side == "f" else 1.0 - OFFSET  # the offset ribbon
    half = 0.5 * share * depth_m  # half of this side's channel
    mid = f"c{side}"
    slit = {"kind": "slit", "width_m": SLOT_W_M, "breadth_m": length_m, "length_m": half,
            "wide_at_hz": 1000.0}  # fmt: skip
    return [
        {"name": f"chan_{side}_a", "a": a, "b": mid, **slit},
        {
            "name": f"cav_{side}",
            "kind": "cavity",
            "a": mid,
            "volume_m3": SLOT_W_M * length_m * share * depth_m,
        },  # fmt: skip
        {"name": f"chan_{side}_b", "a": mid, "b": b, **slit},
    ]


def motor(g: dict) -> mc.MovingCoil:
    return mc.moving_coil_from_data(
        {"name": "fit", "kind": "ribbon_motor", "lumped": ribbon.compile_network(g)},
        kind="ribbon_motor",
    )


_BEM: dict = {}


def entries(body: dict, a: float, f: np.ndarray, theta: np.ndarray):
    key = (round(body["radius_m"], 7), round(body["depth_m"], 7), a, tuple(f), tuple(theta))
    if key not in _BEM:
        op = bor.operator(bor.baffle_mesh(body, a, panel_m=0.75e-3))
        _BEM[key] = bor.entry_factors(op, f, theta)
    return _BEM[key]


def response(g: dict, f: np.ndarray, theta=(0.0,), in_plane=False) -> np.ndarray:
    """Open-circuit volts at the 250 ohm strap per pascal (freqs, angles)."""
    th = np.asarray(theta, float)
    fr, rr = entries(g["body"], bor.entry_size(g), f, th)
    lf = (
        bor.ribbon_line_factor(g, f, th, in_plane=in_plane)
        if in_plane
        else np.ones((len(f), len(th)))
    )
    c = motor(g)
    out = np.zeros((len(f), len(th)), complex)
    for j in range(len(th)):
        out[:, j] = N_TURNS * networks.moving_coil_response(
            c, f, (fr[:, j] * lf[:, j], rr[:, j] * lf[:, j]), l_load_h=L_PRIMARY_H
        )
    return out


def rel_db(h: np.ndarray, f: np.ndarray) -> np.ndarray:
    i = int(np.argmin(np.abs(f - 1000.0)))
    return 20 * np.log10(np.abs(h / h[i]))


def target(cv, band):
    f, db, w = cv["axial"]
    ref = np.interp(np.log(1000.0), np.log(f), db)
    k = (f >= band[0]) & (f <= band[1])
    fk = np.unique(np.r_[f[k], 1000.0])
    return fk, np.interp(np.log(fk), np.log(f), db) - ref, np.interp(np.log(fk), np.log(f), w)


def top_rms(base, cv, radius, depth, f_res, q, b, rayl=None) -> float:
    f, t, w = target(cv, TOP_HZ)
    g = geometry(base, radius, depth, f_res, q, b, rayl)
    d = rel_db(response(g, f)[:, 0], f) - t
    return float(np.sqrt(np.sum(w * d**2) / np.sum(w)))


def bass_rms(base, cv, body, f_res, q, b, rayl=None) -> float:
    f, t, w = target(cv, BASS_HZ)
    g = geometry(base, body["radius_m"], body["depth_m"], f_res, q, b, rayl)
    d = rel_db(response(g, f)[:, 0], f) - t
    return float(np.sqrt(np.sum(w * d**2) / np.sum(w)))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--grid", action="store_true", help="the body's grid search first")
    ap.add_argument("--write", action="store_true", help="write the fit into published_points.yaml")
    args = ap.parse_args()
    base = _plain(_published()["RIBBON_R121"]["geometry"])
    cv = curves()
    f_res, q, b = 40.0, 1.0, float(base["magnet"]["b_gap_t"])
    body = dict(BODY0)
    if args.grid:
        best = None
        for r in (0.004, 0.006, 0.008, 0.010, 0.012, 0.014, 0.017, 0.020):
            for d in (0.006, 0.008, 0.010, 0.012, 0.014, 0.016, 0.018, 0.020, 0.024):
                e = top_rms(base, cv, r, d, f_res, q, b)
                print(f"grid radius {r * 1e3:4.1f} mm depth {d * 1e3:4.1f} mm: {e:.2f} dB")
                if best is None or e < best[0]:
                    best = (e, r, d)
        body = {"radius_m": best[1], "depth_m": best[2]}
    # the body: the top's shape (the bass hardly moves it)
    sol = minimize(
        lambda x: top_rms(base, cv, x[0] * 1e-3, x[1] * 1e-3, f_res, q, b),
        [body["radius_m"] * 1e3, body["depth_m"] * 1e3],
        method="Nelder-Mead", options={"xatol": 0.05, "fatol": 0.005, "maxfev": 80},
    )  # fmt: skip
    r_mm, d_mm = (round(float(x), 2) for x in sol.x)
    body = {"radius_m": r_mm * 1e-3, "depth_m": d_mm * 1e-3}
    print("body", body, "top rms", round(sol.fun, 2), flush=True)

    # the tuning and the foil's loss: the bass bump
    # (the tuning bounded, the damping screens' flow resistance free)
    def bass_cost(x):
        f_ = float(np.clip(x[0], F_RES_BOUNDS[0], F_RES_BOUNDS[1]))
        pen = 0.05 * abs(float(x[0]) - f_)
        return bass_rms(base, cv, body, f_, np.exp(x[1]), b, float(np.exp(x[2]))) + pen

    sol = minimize(
        bass_cost, [f_res, np.log(q), np.log(RAYL0)], method="Nelder-Mead",
        options={"xatol": 0.01, "fatol": 0.002, "maxfev": 300},
    )  # fmt: skip
    f_res = round(float(np.clip(sol.x[0], *F_RES_BOUNDS)), 1)
    q, rayl = round(float(np.exp(sol.x[1])), 3), round(float(np.exp(sol.x[2])), 3)
    print(
        "resonance_hz",
        f_res,
        "q",
        q,
        "screen rayl",
        rayl,
        "bass rms",
        round(sol.fun, 2),
        flush=True,
    )
    # B: the sensitivity at 1 kHz (nearly linear; the ribbon's own current damps a little)
    for _ in range(4):
        g = geometry(base, body["radius_m"], body["depth_m"], f_res, q, b, rayl)
        s = abs(response(g, np.array([1000.0]))[0, 0])
        b *= SENS_V_PER_PA / s
    b = round(b, 3)
    g = geometry(base, body["radius_m"], body["depth_m"], f_res, q, b, rayl)
    result = summary(g, cv)
    result.update({"radius_m": body["radius_m"], "depth_m": body["depth_m"],
                   "resonance_hz": f_res, "q": q, "screen_rayl": rayl, "b_gap_t": b})  # fmt: skip
    REPORT.mkdir(parents=True, exist_ok=True)
    (REPORT / "royer_r121_fit.json").write_text(json.dumps(result, indent=1))
    print(json.dumps(result, indent=1))
    plot(g, cv)
    if args.write:
        write_block(g)


def summary(g: dict, cv) -> dict:
    out = {}
    f, t, _ = target(cv, (50.0, 15000.0))
    d = rel_db(response(g, f)[:, 0], f) - t
    out["sensitivity_mv_per_pa"] = round(1e3 * abs(response(g, np.array([1000.0]))[0, 0]), 3)
    for lo, hi in ((50, 1000), (1000, 10000), (10000, 15000)):
        k = (f >= lo) & (f <= hi)
        out[f"m_{lo}_{hi}_rms_db"] = round(float(np.sqrt(np.mean(d[k] ** 2))), 2)
        out[f"m_{lo}_{hi}_max_db"] = round(float(np.max(np.abs(d[k]))), 2)
        out[f"m_{lo}_{hi}_max_at_hz"] = float(f[k][np.argmax(np.abs(d[k]))])
    pol = polars()
    for fz, v in pol.items():
        th = np.radians(v[:, 0])
        h = response(g, np.array([float(fz)]), th, in_plane=True)[0]
        model = 20 * np.log10(np.abs(h / h[0]))
        k = v[:, 0] <= 60
        e = model[k] - v[k, 1]
        out[f"polar_{int(fz)}_rms_db"] = round(float(np.sqrt(np.mean(e**2))), 2)
        out[f"polar_{int(fz)}_max_db"] = round(float(np.max(np.abs(e))), 2)
    out["lumped"] = {k: v for k, v in ribbon.compile_network(g).items() if k not in ("elements",)}
    return out


def plot(g: dict, cv) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(1, 2, figsize=(13, 4.8))
    f = np.geomspace(40, 16000, 200)
    m = rel_db(response(g, f)[:, 0], f)
    fm, dm, _ = cv["axial"]
    ax[0].semilogx(fm, dm - np.interp(np.log(1000.0), np.log(fm), dm), "k.", label="royer")
    ax[0].semilogx(f, m, "C0", label="model")
    ax[0].set(xlabel="Hz", ylabel="dB re 1 kHz", ylim=(-10, 6), title="R-121, axial, plane wave")
    ax[0].grid(True, which="both", alpha=0.3)
    ax[0].legend()
    pol = polars()
    for i, (fz, v) in enumerate(sorted(pol.items())):
        th = np.radians(np.arange(0, 91, 2.5))
        h = response(g, np.array([float(fz)]), th, in_plane=True)[0]
        ax[1].plot(np.degrees(th), 20 * np.log10(np.abs(h / h[0])), f"C{i}", label=f"{fz:g} Hz")
        ax[1].plot(v[:, 0], v[:, 1], f"C{i}.")
    ax[1].set(xlabel="degrees (vertical plane)", ylabel="dB", ylim=(-25, 2),
              title="the model")  # fmt: skip
    ax[1].grid(True, alpha=0.3)
    ax[1].legend()
    fig.tight_layout()
    fig.savefig(REPORT / "royer_r121_fit.png", dpi=100)


def write_block(g: dict) -> None:
    """Replace the RIBBON_R121 block of published_points.yaml with `g`'s fitted values."""
    import re

    path = DATA_DIR / "datasheets" / "published_points.yaml"
    text = path.read_text(encoding="utf-8")
    m = re.search(r'^"RIBBON_R121":.*?(?=^# --- |^"[A-Z0-9_]+":)', text, flags=re.S | re.M)
    block = render_block(g)
    path.write_text(text[: m.start()] + block + "\n" + text[m.end() :], encoding="utf-8")
    print("wrote RIBBON_R121 to", path)


_COMMENTS = {
    "length_m": "royer: the manual's '1.5\" x 3/16\" x 2.5-micron ribbon assembly' (38.1 mm)",
    "width_m": "royer: the same, 3/16 in (4.76 mm)",
    "thickness_m": "royer: the same, 2.5 micron (aluminium: the cut sheet's '2.5-micron aluminum ribbon')",
    "density_kg_m3": "provisional: model knowledge (pure aluminium, CRC handbook 2.70 g/cm^3)",
    "resistivity_ohm_m": "provisional: model knowledge (pure aluminium at 20 C, CRC handbook 2.65 uOhm cm)",
    "corrugation": "provisional: as RIBBON_44BX (a corrugated foil)",
    "resonance_hz": "fitted (scripts/fit_r121.py): the foil's own tuning in vacuo, to royer's bass (bounds 8-60 Hz)",
    "q": "fitted with resonance_hz: the bass shape (the screens' and the foil's damping together)",
    "modes": "numerical: the odd length modes 1-9, the rest lumped on the 11th",
}


def _val(x) -> str:
    return "{value: %d}" % x if isinstance(x, int) else "{value: %r}" % float(x)


def render_block(g: dict) -> str:
    base = _published()["RIBBON_R121"]
    rb, mg, bd = g["ribbon"], g["magnet"], g["body"]
    lines = [
        '"RIBBON_R121":',
        f"  source: {json.dumps(base['source'])}",
        "  geometry:",
        "    body:",
        "      form: baffle",
        f"      radius_m: {_val(bd['radius_m'])}   # fitted (scripts/fit_r121.py): royer's chart from 1 to 16 kHz re 1 kHz (an equivalent disc, not a drawing)",
        f"      depth_m: {_val(bd['depth_m'])}   # fitted with radius_m to the same curve; the channels below OFFSET (0.3) of it in front, the rest behind (the offset ribbon)",
        "    ribbon:",
    ]
    for k, c in _COMMENTS.items():
        lines.append(f"      {k}: {_val(rb[k])}   # {c}")
    lines += [
        "    magnet:",
        f"      b_gap_t: {_val(mg['b_gap_t'])}   # fitted (scripts/fit_r121.py): royer's -49 dB re 1 V/Pa open circuit through R121_OT@1 (1:40)",
        f"      gap_length_m: {_val(mg['gap_length_m'])}   # provisional: model knowledge (the pole pieces span the ribbon)",
        "    leads:",
        "      r_ohm: {value: 0.01}   # provisional: model knowledge (the clamps and short leads)",
        "      l_h: {value: 4.0e-8}   # provisional: model knowledge (the ribbon and its return as a loop ~38 x 8 mm)",
        "    network:",
    ]
    for e in g["network"]:
        parts = []
        for k, x in e.items():
            if isinstance(x, float):
                parts.append(f"{k}: {{value: {x!r}}}")
            else:
                parts.append(f"{k}: {x}")
        lines.append("      - {" + ", ".join(parts) + "}")
    lines += [
        "  published:",
        "    sensitivity_v_per_pa: 3.55e-3   # royer: -49 dB re 1 V/Pa (the manual; the fit's target)",
        "    output_ohm: 300.0              # royer: 300 ohm nominal balanced (a check, through R121_OT@1)",
        "",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    main()
