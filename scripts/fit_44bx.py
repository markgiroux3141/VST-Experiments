"""Fit the RCA 44-BX's ribbon motor to RCA's curves (docs/CHAINS_PLAN.md WP6, step 3).

    uv run python scripts/fit_44bx.py [--grid]

RIBBON_44BX@1 (WP5) is the ribbon from AEA's figures and Olson's circuit with a provisional
motor. Here the motor gets its body (the pole pieces as a rigid baffle disc,
varimu.mics.bor.baffle_mesh, the slot's length on top: bor.ribbon_line_factor) and its
channels as T sections (half the channel's air mass, its volume as a compliance, the other
half: the air between the ribbon and each mouth is spring as well as mass), and the unknowns
are fitted one figure each to RCA's instruction book (IB-24267-5,
data/datasheets/rca_44bx_response.csv and rca_44bx_polar.csv):

    body.radius_m, depth_m   the top: M's shape from 1 kHz to 15 kHz re 1 kHz (the dips at
                             ~2.7 and 9 kHz, the peak at ~13 kHz); the channels' lengths and
                             volumes follow the depth (each half of it)
    ribbon.resonance_hz      the bass bump's frequency (M: +2.8 dB at 65 Hz)
    ribbon.q                 the bass bump's height
    magnet.b_gap_t           the sensitivity: ib's -55 dBm at 10 dyn/cm^2 into 250 ohm (RTMA:
                             matched power), 1.78 mV/Pa open circuit at 250 ohm

The response is the open-circuit EMF across the ribbon (networks.moving_coil_response into
the transformer's primary inductance) times the turns ratio; the whole circuit
(config/circuits/rca_44bx.yaml) is checked against it in tests/test_rca_44bx.py. The polars
(ib Fig. 3, the vertical plane) are a check, not a target.

`--grid` runs the body's grid search (minutes); without it the refinement starts from the
geometry in the script's BODY0. `--reactor` fits the reactor (ib prints no value) on the
whole circuit with its pinned ribbon: its inductance to V2, its resistance to V1 (->
reports/mics/rca44bx_reactor_fit.json). Numbers -> reports/mics/rca44bx_fit.json, plot ->
reports/mics/rca44bx_fit.png; the fitted values are printed for published_points.yaml's
"RIBBON_44BX".
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

N_TURNS = 31.0  # RCA44BX_OT@1: 10 : 310 (the 250 ohm strapping, A-C)
L_PRIMARY_H = 9.6e-3  # RCA44BX_OT@1's primary in its core's linear limit (its report)
SENS_V_PER_PA = 1.78e-3  # ib: -55 dBm at 10 dyn/cm^2 into 250 ohm matched: sqrt(4 R P)
BODY0 = {"radius_m": 0.014, "depth_m": 0.012}  # the grid's best (`--grid`)
TOP_HZ = (1000.0, 15000.0)
BASS_HZ = (50.0, 1000.0)
SLOT_W_M = 4.95e-3  # the channel: the ribbon's width and two sbe clearances
REPORT = REPO_ROOT / "reports" / "mics"


def curves():
    with open(DATA_DIR / "datasheets" / "rca_44bx_response.csv", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    out = {}
    for k in ("M", "V1", "V2"):
        r = [x for x in rows if x["curve"] == k]
        f = np.array([float(x["freq_hz"]) for x in r])
        db = np.array([float(x["db"]) for x in r])
        w = np.array([0.3 if x["quality"] == "coarse" else 1.0 for x in r])
        out[k] = (f, db, w)
    return out


def polars():
    with open(DATA_DIR / "datasheets" / "rca_44bx_polar.csv", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    out = {}
    for x in rows:
        if x["quality"] in ("read", "merged"):
            out.setdefault(float(x["freq_hz"]), []).append((float(x["angle_deg"]), float(x["db"])))
    return {f: np.array(v) for f, v in out.items()}


def geometry(base: dict, radius_m: float, depth_m: float, f_res: float, q: float, b: float):
    """The base geometry (published_points "RIBBON_44BX") with its body, the channels as T
    sections half the depth each side, and the fitted values."""
    g = copy.deepcopy(base)
    g["body"] = {"form": "baffle", "radius_m": radius_m, "depth_m": depth_m}
    g["ribbon"]["resonance_hz"] = f_res
    g["ribbon"]["q"] = q
    g["magnet"]["b_gap_t"] = b
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
    half = 0.25 * depth_m  # half of each side's channel (the ribbon at mid-depth)
    mid = f"c{side}"
    slit = {"kind": "slit", "width_m": SLOT_W_M, "breadth_m": length_m, "length_m": half,
            "wide_at_hz": 1000.0}  # fmt: skip
    return [
        {"name": f"chan_{side}_a", "a": a, "b": mid, **slit},
        {
            "name": f"cav_{side}",
            "kind": "cavity",
            "a": mid,
            "volume_m3": SLOT_W_M * length_m * 0.5 * depth_m,
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
    lf = bor.ribbon_line_factor(g, f, th, in_plane=in_plane)
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
    f, db, w = cv["M"]
    ref = np.interp(np.log(1000.0), np.log(f), db)
    k = (f >= band[0]) & (f <= band[1])
    fk = np.unique(np.r_[f[k], 1000.0])
    return fk, np.interp(np.log(fk), np.log(f), db) - ref, np.interp(np.log(fk), np.log(f), w)


def top_rms(base, cv, radius, depth, f_res, q, b) -> float:
    f, t, w = target(cv, TOP_HZ)
    g = geometry(base, radius, depth, f_res, q, b)
    d = rel_db(response(g, f)[:, 0], f) - t
    return float(np.sqrt(np.sum(w * d**2) / np.sum(w)))


def bass_rms(base, cv, body, f_res, q, b) -> float:
    f, t, w = target(cv, BASS_HZ)
    g = geometry(base, body["radius_m"], body["depth_m"], f_res, q, b)
    d = rel_db(response(g, f)[:, 0], f) - t
    return float(np.sqrt(np.sum(w * d**2) / np.sum(w)))


def circuit_response(over: dict, f: np.ndarray, theta: float = 0.0) -> np.ndarray:
    """The whole mic (config/circuits/rca_44bx.yaml, its pinned ribbon) at `over`'s
    settings: volts at `out` per pascal of a plane wave from theta (the body's entries and
    the slot's length in the ribbon's plane)."""
    from varimu.circuit import builder, spec
    from varimu.devices.library import component_data
    from varimu.measure import ac

    s = spec.load_circuit(spec.circuit_path("rca_44bx"))
    q = spec.resolve(s, over)
    g = component_data(str(q["ribbon_model"]))["geometry"]
    fr, rr = entries(g["body"], bor.entry_size(g), f, np.array([theta]))
    lf = bor.ribbon_line_factor(g, f, [theta], in_plane=True)[:, 0]
    front, rear = fr[:, 0] * lf, rr[:, 0] * lf
    ir = builder.build_ir(s, q, "linear")
    return front * ac.transfer(ir, f, "out", drives={"p_rear": rear / front})


def fit_reactor(cv) -> dict:
    """The reactor (ib prints no value): its inductance to V2's curve (the reactor across
    A-C), its resistance to V1's (across B-C), each re 1 kHz on 50-600 Hz, on the whole
    circuit."""

    def err(x, curve, pos):
        f, db, _ = cv[curve]
        k = (f >= 50.0) & (f <= 600.0)
        fk = np.r_[f[k], 1000.0]
        over = {
            "response": pos,
            "reactor_h": float(np.exp(x[0])),
            "reactor_ohm": float(np.exp(x[1])),
        }
        h = circuit_response(over, fk)
        model = 20 * np.log10(np.abs(h[:-1] / h[-1]))
        t = db[k] - np.interp(np.log(1000.0), np.log(f), db)
        return model - t

    def cost(x):
        return float(np.sum(err(x, "V2", 2) ** 2) + np.sum(err(x, "V1", 1) ** 2))

    sol = minimize(
        cost, [np.log(1.0), np.log(20.0)], method="Nelder-Mead",
        options={"xatol": 1e-3, "fatol": 1e-4, "maxfev": 300},
    )  # fmt: skip
    out = {
        "reactor_h": round(float(np.exp(sol.x[0])), 4),
        "reactor_ohm": round(float(np.exp(sol.x[1])), 2),
    }
    for curve, pos in (("V1", 1), ("V2", 2)):
        e = err(sol.x, curve, pos)
        out[f"{curve}_rms_db"] = round(float(np.sqrt(np.mean(e**2))), 2)
        out[f"{curve}_max_db"] = round(float(np.max(np.abs(e))), 2)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--grid", action="store_true", help="the body's grid search first")
    ap.add_argument(
        "--reactor", action="store_true",
        help="fit the reactor on the whole circuit (its pinned ribbon) instead",
    )  # fmt: skip
    args = ap.parse_args()
    if args.reactor:
        r = fit_reactor(curves())
        REPORT.mkdir(parents=True, exist_ok=True)
        (REPORT / "rca44bx_reactor_fit.json").write_text(json.dumps(r, indent=1))
        print(json.dumps(r, indent=1))
        return
    base = _plain(_published()["RIBBON_44BX"]["geometry"])
    cv = curves()
    f_res, q, b = 60.0, 3.0, float(base["magnet"]["b_gap_t"])
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
    sol = minimize(
        lambda x: bass_rms(base, cv, body, x[0], np.exp(x[1]), b),
        [f_res, np.log(q)], method="Nelder-Mead",
        options={"xatol": 0.01, "fatol": 0.002, "maxfev": 200},
    )  # fmt: skip
    f_res, q = round(float(sol.x[0]), 1), round(float(np.exp(sol.x[1])), 2)
    print("resonance_hz", f_res, "q", q, "bass rms", round(sol.fun, 2), flush=True)
    # B: the sensitivity at 1 kHz (nearly linear; the ribbon's own current damps a little)
    for _ in range(4):
        g = geometry(base, body["radius_m"], body["depth_m"], f_res, q, b)
        s = abs(response(g, np.array([1000.0]))[0, 0])
        b *= SENS_V_PER_PA / s
    b = round(b, 3)
    g = geometry(base, body["radius_m"], body["depth_m"], f_res, q, b)
    result = summary(g, cv)
    result.update({"radius_m": body["radius_m"], "depth_m": body["depth_m"],
                   "resonance_hz": f_res, "q": q, "b_gap_t": b})  # fmt: skip
    REPORT.mkdir(parents=True, exist_ok=True)
    (REPORT / "rca44bx_fit.json").write_text(json.dumps(result, indent=1))
    print(json.dumps(result, indent=1))
    plot(g, cv)


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
    fm, dm, _ = cv["M"]
    ax[0].semilogx(fm, dm - np.interp(np.log(1000.0), np.log(fm), dm), "k.", label="ib Fig. 4 M")
    ax[0].semilogx(f, m, "C0", label="model")
    ax[0].set(xlabel="Hz", ylabel="dB re 1 kHz", ylim=(-25, 6), title="RCA 44-BX, M, plane wave")
    ax[0].grid(True, which="both", alpha=0.3)
    ax[0].legend()
    pol = polars()
    for i, (fz, v) in enumerate(sorted(pol.items())):
        th = np.radians(np.arange(0, 91, 2.5))
        h = response(g, np.array([float(fz)]), th, in_plane=True)[0]
        ax[1].plot(np.degrees(th), 20 * np.log10(np.abs(h / h[0])), f"C{i}", label=f"{fz:g} Hz")
        ax[1].plot(v[:, 0], v[:, 1], f"C{i}.")
    ax[1].set(xlabel="degrees (vertical plane)", ylabel="dB", ylim=(-25, 2),
              title="ib Fig. 3 (dots) and the model")  # fmt: skip
    ax[1].grid(True, alpha=0.3)
    ax[1].legend()
    fig.tight_layout()
    fig.savefig(REPORT / "rca44bx_fit.png", dpi=100)


if __name__ == "__main__":
    main()
