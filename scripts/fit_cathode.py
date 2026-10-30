"""Fit the oxide cathode's emission to Phywe's EC92 (device builder B6, the heater).

    uv run python scripts/fit_cathode.py [--t0 1050] [--out reports/devices/cathode_ec92]

Phywe LEP 4.1.10's Fig. 4 (data/datasheets/published_points.yaml `EC92_forward_by_heater`):
the EC92 as a diode at heater currents 100-120 mA. Model (varimu.devices.cathode): the
cathode's temperature from the heater current (current-driven: T ~ I^(2 / (4 - ALPHA)),
the rated 150 mA holding T0), a space-charge rise P (V - V0)^1.5 under the emission ceiling
I_s(T) (Richardson, work function phi; sharpness n). Fitted: P, V0, I_s0 (the emission at
T0), phi, n. Checked: Fig. 5's retarding region (`EC92_retarding_by_heater`), where the
current at a fixed voltage follows I_s(T) exp(V / V_T): the voltage of 10 uA should move
with the heater as measured. -> <out>.json, <out>.png
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import yaml
from scipy.optimize import least_squares

from varimu.config import REPO_ROOT
from varimu.devices.cathode import K_EV, Cathode

PUB = REPO_ROOT / "data" / "datasheets" / "published_points.yaml"
OUT = REPO_ROOT / "reports" / "devices" / "cathode_ec92"
HEATER_V, HEATER_A = 6.3, 0.150  # EC92 (RCA / Philips: 6.3 V, 150 mA)


def load():
    pub = yaml.safe_load(PUB.read_text(encoding="utf-8"))
    f4, f5 = pub["EC92_forward_by_heater"], pub["EC92_retarding_by_heater"]
    u = np.array(f4["u_v"])
    pts = []
    for key, row in f4["ia_ma"].items():
        ih = float(key.removeprefix("heater_").replace("_", ".", 1).rstrip("_a"))
        for uv, ia in zip(u, row, strict=True):
            if ia is not None:
                pts.append((ih, uv, ia * 1e-3))
    ret = {
        float(k.removeprefix("heater_").replace("_", ".", 1).rstrip("_a")): v
        for k, v in f5["u_at_10ua_v"].items()
    }
    return np.array(pts), ret


def model(x, ih, u, t0):
    p, v0, is0, phi, n = x
    c = Cathode(HEATER_V, HEATER_A, is0, phi, n, t0_k=t0)
    temps = {h: c.steady_k(amps=h) for h in np.unique(ih)}
    t = np.array([temps[h] for h in ih])
    scl = p * np.maximum(u - v0, 0.0) ** 1.5
    i_s = np.array([c.is_a(tk) for tk in t])
    return scl * (1 + (scl / i_s) ** n) ** (-1 / n), c, t


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--t0", type=float, default=1050.0)
    ap.add_argument("--out", type=Path, default=OUT)
    a = ap.parse_args()
    pts, ret = load()
    ih, u, ia = pts[:, 0], pts[:, 1], pts[:, 2]

    def resid(x):
        return (model(x, ih, u, a.t0)[0] - ia) * 1e3  # mA

    x0 = [3e-3, 0.3, 0.3, 1.1, 3.0]
    fit = least_squares(
        resid, x0, bounds=([1e-4, -1.0, 1e-3, 0.5, 1.0], [0.1, 2.0, 50.0, 3.0, 20.0])
    )
    p, v0, is0, phi, n = fit.x
    pred, c, t = model(fit.x, ih, u, a.t0)
    rms = float(np.sqrt(np.mean((pred - ia) ** 2)) * 1e3)
    heaters = sorted(np.unique(ih))
    temps = {h: c.steady_k(amps=h) for h in [*heaters, 0.130, 0.140, 0.150]}
    # Fig. 5: the voltage of 10 uA in the retarding region, V_T ln(10 uA / I_s(T)), against
    # the 150 mA heater's (a common contact potential cancels).
    v10 = {h: K_EV * temps[h] * np.log(1e-5 / c.is_a(temps[h])) for h in ret}
    check = {
        f"{h * 1e3:.0f}_ma": {
            "measured_v_re_150": ret[h] - ret[0.150],
            "model_v_re_150": float(v10[h] - v10[0.150]),
        }
        for h in sorted(ret)
    }
    # Sensitivities at the rated heater voltage (a heater winding): per 1% of voltage.
    vt = c.steady_k(volts=HEATER_V * 1.01) - a.t0
    shift_1ma = float(c.shift_v(c.steady_k(volts=HEATER_V * 1.01), 1e-3))
    out = {
        "t0_k": a.t0,
        "p_a_per_v15": p,
        "v0_v": v0,
        "is0_a": is0,
        "phi_ev": phi,
        "n": n,
        "rms_ma": rms,
        "temperatures_k": {f"{h * 1e3:.0f}_ma": temps[h] for h in temps},
        "fig5_check": check,
        "per_pct_heater_voltage": {
            "dt_k": vt,
            "shift_mv_at_1ma": shift_1ma * 1e3,
            "emission_pct": 100 * (c.is_a(a.t0 + vt) / is0 - 1),
        },
        "emission_reserve_at_10ma": is0 / 10e-3,
    }
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.with_suffix(".json").write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(out, indent=1))
    plot(pts, fit.x, a.t0, a.out.with_suffix(".png"))


def plot(pts, x, t0, path: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(7, 4.5))
    uu = np.linspace(0, 8, 200)
    for h in sorted(np.unique(pts[:, 0])):
        sel = pts[:, 0] == h
        (line,) = ax.plot(pts[sel, 1], pts[sel, 2] * 1e3, "o", ms=4, label=f"{h * 1e3:.0f} mA")
        m = model(x, np.full_like(uu, h), uu, t0)[0]
        ax.plot(uu, m * 1e3, "-", color=line.get_color(), lw=1)
    ax.set_xlabel("anode V")
    ax.set_ylabel("anode mA")
    ax.set_title("EC92 (Phywe Fig. 4): points read by eye, lines the cathode model")
    ax.legend(title="heater")
    fig.tight_layout()
    fig.savefig(path, dpi=110)


if __name__ == "__main__":
    main()
