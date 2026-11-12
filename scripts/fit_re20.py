"""Fit the R_RE20 cartridge's provisional geometry to EV's RE20 figures (CHAINS_PLAN.md WP13).

    uv run python scripts/fit_re20.py [--write] [--band LO HI]

fit_d112.py's method on the RE20 (no construction published: data/schematics/ev_re20/README.md):
1.5 mV/Pa open circuit, the 0 and 180 deg responses with the bass tilt off
(data/datasheets/ev_re20_response.csv) and the polar's 90 deg points (ev_re20_polar.csv: below
700 Hz -4.2 dB, above -5.6 dB, the two sides' mean). The rear path is Mawby's continuously
Variable-D, the `slotted_line` kind on a `variable_d` body: its slot bands' BEM factors are
solved once per frequency (cached in cache/re20/ by the body, the radius and bor.py) and summed
with the cartridge's weights (varimu.devices.moving_coil.rear_entry_weights) at every step, so
the network's rear part moves freely. `--write` puts the values into published_points.yaml's
"R_RE20" block; `varimu fit-devices --only R_RE20` makes the component version. Plot ->
reports/mics/r_re20_fit.png, numbers -> reports/mics/r_re20_fit.json.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import sys
from pathlib import Path

import numpy as np
import yaml
from scipy.optimize import least_squares

sys.path.insert(0, str(Path(__file__).parent))
import fit_sm57 as fs  # noqa: E402

from varimu.config import DATA_DIR, REPO_ROOT  # noqa: E402
from varimu.devices import moving_coil as mc  # noqa: E402
from varimu.devices.library import _plain  # noqa: E402
from varimu.mics import bor  # noqa: E402
from varimu.mics.networks import moving_coil_response  # noqa: E402

KEY = "R_RE20"
BAND_HZ = (40.0, 14000.0)
FREE = [
    (("coil", "bl_tm"), 0.5, 20.0, True),
    (("diaphragm", "moving_mass_kg"), 0.15e-3, 3e-3, True),
    (("diaphragm", "resonance_hz"), 30.0, 600.0, True),
    (("diaphragm", "q"), 0.2, 8.0, True),
    (("diaphragm", "modes", 0, "f_hz"), 4000.0, 16000.0, True),
    (("diaphragm", "modes", 0, "q"), 0.7, 8.0, True),
    (("diaphragm", "modes", 0, "mass_fraction"), 0.02, 0.4, True),
    (("diaphragm", "modes", 0, "area_fraction"), 0.05, 0.6, True),
    (("network", "grille", "rayl"), 1.0, 1000.0, True),
    (("network", "cav", "volume_m3"), 0.2e-6, 20e-6, True),
    (("network", "damp", "r_pa_s_m3"), 1e4, 1e9, True),
    (("network", "damp", "m_kg_m4"), 10.0, 1e5, True),
    (("network", "vd", "radius_m"), 1e-3, 8e-3, True),
    (("network", "vd", "slot_rayl"), 10.0, 1e4, True),
    (("network", "term", "volume_m3"), 1e-6, 100e-6, True),
]
POLAR_90 = {250.0: -4.2, 1000.0: -5.6, 2000.0: -5.6, 4000.0: -5.6}  # ev_re20_polar.csv, the sides
SENS_WEIGHT, POLAR_WEIGHT, REAR_WEIGHT = 3.0, 1.0, 0.5
ANGLES = (0.0, 90.0, 180.0)
_BANDS: dict[float, tuple[np.ndarray, np.ndarray]] = {}  # f -> (front (angles), bands (n, angles))


def load_targets():
    with open(DATA_DIR / "datasheets" / "ev_re20_response.csv", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    out = {}
    for tr in ("0_off", "180_off"):
        fr = np.array([float(r["freq_hz"]) for r in rows if r["trace"] == tr])
        db = np.array([float(r["db_re_0deg_1khz"]) for r in rows if r["trace"] == tr])
        out[tr] = (fr, db)
    return out


def band_factors(g, f: np.ndarray):
    """The front entry and each slot band's factor (angles ANGLES) at f, cached."""
    body, a = g["body"], g["diaphragm"]["radius_m"]
    missing = sorted({float(x) for x in f} - set(_BANDS))
    if missing:
        src = Path(bor.__file__).read_bytes()
        key = hashlib.sha256(json.dumps([body, a]).encode() + src).hexdigest()[:16]
        path = REPO_ROOT / "cache" / "re20" / f"bands_{key}.npz"
        if path.exists() and not _BANDS:
            z = np.load(path)
            for i, x in enumerate(z["f"]):
                _BANDS[float(x)] = (z["front"][i], z["bands"][i])
            missing = sorted({float(x) for x in f} - set(_BANDS))
        if missing:
            mesh = bor.body_mesh(body, a)
            op = bor.operator(mesh)
            n = int(body["slot_sections"])
            wf = mesh.face_weights(bor.FRONT)
            wb = np.array([mesh.face_weights(bor.SLOT0 + k) for k in range(1, n + 1)])
            th = np.radians(ANGLES)
            for x in missing:
                p = bor.surface_pressure(op, x, th, np.inf)
                _BANDS[x] = (wf @ p, wb @ p)
            fs_ = sorted(_BANDS)
            path.parent.mkdir(parents=True, exist_ok=True)
            np.savez(path, f=np.array(fs_), front=np.array([_BANDS[x][0] for x in fs_]),
                     bands=np.array([_BANDS[x][1] for x in fs_]))  # fmt: skip
    front = np.array([_BANDS[float(x)][0] for x in f])
    bands = np.array([_BANDS[float(x)][1] for x in f])  # (f, n, angles)
    return front, bands


def response(g, f, theta_deg):
    """Volts open circuit per pascal of a plane wave from theta."""
    f = np.atleast_1d(np.asarray(f, float))
    front, bands = band_factors(g, f)
    j = ANGLES.index(float(theta_deg))
    w = mc.rear_entry_weights(g, f)  # (n, f)
    rear = np.einsum("kf,fk->f", w, bands[:, :, j])
    c = mc.moving_coil_from_data({"name": KEY, "kind": "moving_coil",
                                  "lumped": mc.compile_network(g)})  # fmt: skip
    return moving_coil_response(c, f, (front[:, j], rear))


def residuals(x, g0, band, targets, sens):
    g = fs._with(g0, x, FREE)
    f0, d0 = targets["0_off"]
    f1, d1 = targets["180_off"]
    s0 = (f0 >= band[0]) & (f0 <= band[1])
    s1 = (f1 >= band[0]) & (f1 <= band[1])
    grid = np.unique(np.concatenate([f0[s0], f1[s1], [1000.0], list(POLAR_90)]))
    h0 = response(g, grid, 0.0)
    ref = abs(h0[grid == 1000.0][0])
    db0 = 20 * np.log10(abs(h0) / ref)
    r = list(np.interp(f0[s0], grid, db0) - d0[s0])
    h1 = response(g, grid, 180.0)
    db1 = 20 * np.log10(abs(h1) / ref)
    r += list(REAR_WEIGHT * (np.interp(f1[s1], grid, db1) - d1[s1]))
    h9 = response(g, np.array(list(POLAR_90)), 90.0)
    h09 = np.interp(list(POLAR_90), grid, abs(h0))
    r += list(POLAR_WEIGHT * (20 * np.log10(abs(h9) / h09) - np.array(list(POLAR_90.values()))))
    r.append(SENS_WEIGHT * 20 * math.log10(ref / sens))
    return np.array(r)


def summary(g, targets, sens, band):
    out = {"values": {fs._label(p): fs._get(g, p) for p, *_ in FREE}}
    ref = abs(response(g, [1000.0], 0.0)[0])
    out["sensitivity_v_per_pa"] = float(ref)
    for tr, th in (("0_off", 0.0), ("180_off", 180.0)):
        f, d = targets[tr]
        sel = (f >= band[0]) & (f <= band[1])
        err = 20 * np.log10(abs(response(g, f[sel], th)) / ref) - d[sel]
        i = int(np.argmax(abs(err)))
        out[tr] = {
            "rms_db": float(np.sqrt(np.mean(err**2))),
            "worst": [float(f[sel][i]), float(err[i])],
        }
    f9 = np.array(list(POLAR_90))
    out["side_90_db"] = dict(zip(map(str, f9), [round(float(v), 2) for v in 20 * np.log10(
        abs(response(g, f9, 90.0)) / abs(response(g, f9, 0.0)))], strict=True))  # fmt: skip
    out["resonance_hz"] = mc.compile_network(g)["resonance_hz"]
    return out


def plot(g, targets, band, path):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    ff = np.geomspace(30, 18000, 100)
    ref = abs(response(g, [1000.0], 0.0)[0])
    fig, ax = plt.subplots(figsize=(8, 5))
    for th, style in ((0.0, "-"), (90.0, "--"), (180.0, ":")):
        ax.semilogx(ff, 20 * np.log10(abs(response(g, ff, th)) / ref), "k" + style, lw=1.2,
                    label=f"model {th:.0f} deg")  # fmt: skip
    for tr, col in (("0_off", "tab:red"), ("180_off", "tab:blue")):
        ax.semilogx(*targets[tr], "o", ms=3, color=col, label=f"ev {tr}")
    for fr, v in POLAR_90.items():
        ax.plot(fr, v, "s", color="tab:green", ms=5)
    ax.axvspan(*band, color="0.93", zorder=0)
    ax.set(xlabel="Hz", ylabel="dB re 1 kHz on axis", ylim=(-35, 8), title="R_RE20 (Variable-D)")
    ax.grid(True, which="both", alpha=0.3)
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(path, dpi=120)


def write(g) -> None:
    """The fitted values into published_points.yaml's R_RE20 block, in place."""
    p = fs.PUBLISHED
    text = p.read_bytes().decode("utf-8")
    crlf = "\r\n" in text
    lines = text.replace("\r\n", "\n").split("\n")
    start = next(i for i, ln in enumerate(lines) if ln.startswith(f'"{KEY}":'))
    end = next((i for i in range(start + 1, len(lines)) if lines[i] and not lines[i][0].isspace()
                and not lines[i].startswith("#")), len(lines))  # fmt: skip
    for path, *_ in FREE:
        key, v = path[-1], fs._get(g, path)
        if path[0] == "network":
            hits = [i for i in range(start, end) if f"name: {path[1]}," in lines[i]]
        elif "modes" in path:
            hits = [i for i in range(start, end) if "name: dome," in lines[i]]
        else:
            hits = [i for i in range(start, end) if re.match(rf"\s+{key}: \{{value:", lines[i])]
        if len(hits) != 1:
            raise SystemExit(f"published_points.yaml: {len(hits)} lines for {path}")
        i = hits[0]
        lines[i], n = re.subn(rf"(\b{key}: \{{value: )([^}}]+)\}}", rf"\g<1>{fs._num(v, 5)}}}",
                              lines[i])  # fmt: skip
        if n != 1:
            raise SystemExit(f"published_points.yaml: {key} not on line {i + 1}")
    out = "\n".join(lines)
    p.write_bytes((out.replace("\n", "\r\n") if crlf else out).encode("utf-8"))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--band", type=float, nargs=2, default=BAND_HZ)
    args = ap.parse_args()
    entry = yaml.safe_load(fs.PUBLISHED.read_text(encoding="utf-8"))[KEY]
    g0 = _plain(entry["geometry"])
    sens = entry["published"]["sensitivity_v_per_pa"]
    targets = load_targets()
    band = tuple(args.band)
    res = least_squares(
        residuals, fs._x0(g0, FREE), bounds=fs._bounds(FREE), x_scale="jac",
        args=(g0, band, targets, sens), diff_step=1e-4,
    )  # fmt: skip
    g = fs._with(g0, res.x, FREE)
    out = summary(g, targets, sens, band)
    out["cost"] = float(res.cost)
    out["at_bounds"] = [
        fs._label(p) for (p, lo, hi, log), v in zip(FREE, res.x, strict=True)
        if min(abs(v - (math.log(lo) if log else lo)), abs(v - (math.log(hi) if log else hi)))
        < 1e-3 * abs(v or 1)
    ]  # fmt: skip
    print(json.dumps(out, indent=1, default=float))
    rep = REPO_ROOT / "reports" / "mics"
    rep.mkdir(parents=True, exist_ok=True)
    (rep / "r_re20_fit.json").write_text(json.dumps(out, indent=1, default=float), "utf-8")
    plot(g, targets, band, rep / "r_re20_fit.png")
    if args.write:
        write(g)
        print("written; run: uv run varimu fit-devices --only R_RE20")


if __name__ == "__main__":
    main()
