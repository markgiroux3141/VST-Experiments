"""Fit the R57 cartridge's provisional geometry to Shure's SM57 figures (SM57_PLAN.md SM2).

    uv run python scripts/fit_sm57.py [--write]

No dimension of the Unidyne III cartridge is published (data/schematics/shure_sm57/README.md,
"Every network element: source or estimate"): what is known is sourced (the coil's DC
resistance, the diaphragm's Mylar, the resonance "in the 100Hz area", the transformer's
turns), the rest is bounded and fitted here, each unknown to its own figure:

    bl_tm, b_gap_t           the sensitivity: s68 'H' 0.149 mV/ubar at 1 kHz, open circuit (the
                             coil's mass grows as (B l / B)^2 at its measured DCR, so the output
                             has a ceiling over B l that the gap's field sets: B is pinned by the
                             sensitivity within its bounds, 0.6-1.2 T)
    resonance_hz             the low end's corner (s68's response, -3 dB at ~81 Hz)
    ps.r1_pa_s_m3            the low end's damping (s68's response 100-400 Hz: the bump)
    ps.q, ps.d_m             the network's delay: the side ratio at 1-2 kHz (c81's polars) and
                             the response's rise toward the presence peak (s68, 1-4 kHz)
    rear_ring_deg            the entries' external path on the head: the rear at 1-2 kHz
    washer.r_pa_s_m3,        the pattern at 125 Hz (c81: -3.8 dB at the side, -10.8 at the rear:
    handle.volume_m3         first order, (beta + cos theta), beta ~ 1.8: the network's delay
                             1.8 times the entries' path): the air behind the washer lengthens
                             the delay below its corner (pat883's branch C'b; born12: tuned), its
                             resistance sets the corner and how little it leaks above (the side
                             at 125 Hz, the rear at 1 kHz: two figures, two unknowns)

The cartridge-only network (varimu.mics.networks.moving_coil_response) with the head as a
rigid sphere, the rear entries a ring on it (free_field.sphere_ring_factors: SM2's "body as a
sphere first"), into the transformer's open-circuited primary (cj06's 386 mH) and through its
turns ratio (cj06's 4.53: the 'H' winding), on 50 Hz-4 kHz.

Not fitted here: the presence peak and above (s68: +5.9 dB at 5.8 kHz, the dip at 7.7 kHz,
the second peak at 9.6 kHz, the fall to 13.9 kHz), and the 4 / 8 kHz polars (reported only).
On a sphere the presence peak's position pins the network's delay against the 1-2 kHz
rejection (fitted to 6.5 kHz: -16.9 dB at the rear against c81's -20.7); the real head is a
cylinder with a grille face (SM4's body). The cap's resonator (born12: 'a very high
frequency') as a lumped front Helmholtz on a sphere can't draw the region: a grid over its
holes' radius and its air layer's height got no better than 5.3 dB rms over 4.5-14 kHz, and
an undamped one puts a +10 dB peak there; a series resistance ahead of the cap (the screen)
damps it but costs the rear rejection (the front air's shunt makes the front path a low-pass
whose phase breaks the null), the layer's radial flow (the `film` element) doesn't. So the
resonator keeps a damped provisional geometry and the region is SM3's / SM4's (the dome's
modes, the cap and its layer as distributed elements; SM3's done-when is the response to
15 kHz).

`--write` puts the fitted values into data/datasheets/published_points.yaml's "R57" block (the
line of each network element by its name, the diaphragm's and coil's by key); `varimu
fit-devices --only R57` then makes the component version. Plot -> reports/mics/r57_fit.png,
numbers -> reports/mics/r57_fit.json.
"""

from __future__ import annotations

import argparse
import copy
import csv
import hashlib
import json
import math
import re

import numpy as np
import yaml
from scipy.optimize import least_squares

from varimu.config import DATA_DIR, REPO_ROOT
from varimu.devices import moving_coil as mc
from varimu.devices.library import _plain
from varimu.mics import bor
from varimu.mics.free_field import sphere_ring_factors
from varimu.mics.networks import moving_coil_response

PUBLISHED = DATA_DIR / "datasheets" / "published_points.yaml"
RESPONSE_DOC, POLAR_DOC = "s68", "c81"
L_PRIMARY_H = 0.386  # cj06: the transformer's primary inductance (open-circuited secondary)
FIT_BAND_HZ = (50.0, 4000.0)  # on a sphere: below the presence peak, where the head's shape
# matters little (above: the body's diffraction, SM4, and the modes, SM3)
BODY_BAND_HZ = (50.0, 6500.0)  # on the real body (SM4): to the presence peak
MODES_BAND_HZ = (50.0, 14000.0)  # with the dome's mode (SM3): the whole published curve
MODE = [  # the dome's mode (SM3), when the geometry has one
    (("diaphragm", "modes", 0, "f_hz"), 5000.0, 16000.0, True),
    (("diaphragm", "modes", 0, "q"), 0.7, 10.0, True),
    (("diaphragm", "modes", 0, "mass_fraction"), 0.02, 0.5, True),
    (("diaphragm", "modes", 0, "area_fraction"), 0.05, 0.6, True),
]
SENS_WEIGHT, POLAR_WEIGHT = 4.0, 2.0

# (path into the geometry, low, high, log scale): network elements by name, else keys.
FREE = [
    (("coil", "bl_tm"), 0.2, 3.0, True),
    (("coil", "b_gap_t"), 0.6, 1.2, False),
    (("diaphragm", "resonance_hz"), 60.0, 160.0, False),
    (("network", "ps", "r1_pa_s_m3"), 1e5, 1e8, True),
    (("network", "ps", "q"), 0.55, 80.0, True),
    (("network", "ps", "d_m"), 0.008, 0.030, False),
    (("network", "washer", "r_pa_s_m3"), 1e6, 1e10, True),
    (("network", "handle", "volume_m3"), 0.5e-6, 20e-6, True),  # at most the body's air
]
RING = (("rear_ring_deg",), 50.0, 150.0, False)  # on a sphere only (the body's ports: a grid)
ANGLES_DEG = np.arange(0.0, 360.0, 5.0)  # the body's entries are solved for all at once
CAP_HZ = (7000.0, 14000.0)  # above the fitted band, on a dense grid (a sharp peak hides between
CAP_DB = (3.0, -8.0)  # 1/6-octave points): the model within s68 + 3 / - 8 dB there (no spurious
# peak or notch where SM3's modes go; one-sided outside the band)
CAP_F = np.geomspace(*CAP_HZ, 80)
CAP_ON = False  # on a sphere off (the region above 4 kHz isn't the sphere's); on the body on


def load_targets(band):
    def rows(name):
        with open(DATA_DIR / "datasheets" / name, encoding="utf-8") as f:
            return list(csv.DictReader(f))

    resp = [r for r in rows("shure_sm57_response.csv") if r["document"] == RESPONSE_DOC]
    f = np.array([float(r["freq_hz"]) for r in resp])
    db = np.array([float(r["db"]) for r in resp])
    q = np.array([r["quality"] != "coarse" for r in resp])
    keep = (f >= band[0]) & (f <= band[1]) & q
    polar = {}
    for r in rows("shure_sm57_polar.csv"):
        if r["document"] != POLAR_DOC or r["band_lo_hz"]:
            continue
        fr, ang = float(r["freq_hz"]), float(r["angle_deg"]) % 360
        side = {90.0: 90, 270.0: 90, 180.0: 180}.get(ang)
        if side and r["quality"] != "coarse" or (side == 180 and fr == 2000.0):
            polar.setdefault((fr, side), []).append(float(r["db"]))
    polar = {k: float(np.mean(v)) for k, v in polar.items()}
    return (f[keep], db[keep]), (f, db), polar


def _get(g, path):
    if path[0] == "network":
        return next(e for e in g["network"] if e["name"] == path[1])[path[2]]
    for k in path:
        g = g[k]
    return g


def _set(g, path, v):
    if path[0] == "network":
        next(e for e in g["network"] if e["name"] == path[1])[path[2]] = v
        return
    for k in path[:-1]:
        g = g[k]
    g[path[-1]] = v


def cartridge(g) -> mc.MovingCoil:
    return mc.moving_coil_from_data(
        {"name": "R57", "kind": "moving_coil", "lumped": mc.compile_network(g)}
    )


_ENTRIES: dict[str, dict[float, tuple[np.ndarray, np.ndarray]]] = {}


def body_entries(body: dict, a: float, f: np.ndarray, theta_deg: float):
    """The body's front and rear entries at f for a plane wave from theta (one of
    ANGLES_DEG): the BEM (varimu.mics.bor.dynamic_mesh) solved once per frequency for every
    angle, kept in cache/sm57/ by the body, the diaphragm's radius and bor.py's source."""
    src = (REPO_ROOT / "varimu" / "mics" / "bor.py").read_bytes()
    key = hashlib.sha256(json.dumps([body, a], sort_keys=True).encode() + src).hexdigest()[:16]
    path = REPO_ROOT / "cache" / "sm57" / f"body_{key}.npz"
    table = _ENTRIES.setdefault(key, {})
    if not table and path.exists():
        z = np.load(path)
        for i, x in enumerate(z["f"]):
            table[float(x)] = (z["front"][i], z["rear"][i])
    missing = sorted({float(x) for x in np.atleast_1d(f)} - set(table))
    if missing:
        op = bor.operator(bor.body_mesh(body, a))
        fr, rr = bor.entry_factors(op, np.array(missing), np.radians(ANGLES_DEG))
        for i, x in enumerate(missing):
            table[x] = (fr[i], rr[i])
        path.parent.mkdir(parents=True, exist_ok=True)
        fs = sorted(table)
        np.savez(path, f=np.array(fs), front=np.array([table[x][0] for x in fs]),
                 rear=np.array([table[x][1] for x in fs]))  # fmt: skip
    j = int(np.argmin(abs(ANGLES_DEG - theta_deg % 360)))
    if abs(ANGLES_DEG[j] - theta_deg % 360) > 1e-9:
        raise ValueError(f"the body's entries are solved every 5 deg, not at {theta_deg}")
    ff = np.atleast_1d(f)
    return (np.array([table[float(x)][0][j] for x in ff]),
            np.array([table[float(x)][1][j] for x in ff]))  # fmt: skip


def response(g, f, theta_deg) -> np.ndarray:
    """Volts open circuit at the 'H' winding per pascal of a plane wave from theta: on the
    geometry's `body` (SM4) or its sphere with the rear ring (SM2)."""
    c = cartridge(g)
    cap = g["diaphragm"]["radius_m"]
    if "body" in g:
        ent = body_entries(g["body"], cap, f, theta_deg)
    else:
        ring = math.radians(g["rear_ring_deg"])
        ent = sphere_ring_factors(f, math.radians(theta_deg), g["sphere_radius_m"], cap, ring)
    return 4.53 * moving_coil_response(c, f, ent, l_load_h=L_PRIMARY_H)


def _with(g0, x, free):
    g = copy.deepcopy(g0)
    for (path, _lo, _hi, log), v in zip(free, x, strict=True):
        _set(g, path, float(np.exp(v)) if log else float(v))
    return g


def _x0(g, free):
    return np.array([math.log(_get(g, p)) if log else _get(g, p) for p, _, _, log in free])


def _bounds(free):
    lo = [math.log(a) if log else a for _, a, _, log in free]
    hi = [math.log(b) if log else b for _, _, b, log in free]
    return lo, hi


def residuals(x, g0, free, band, fit_resp, polar, sens_v_pa, all_resp=None):
    """The response in `band`, the sensitivity, the polars."""
    g = _with(g0, x, free)
    f, db = fit_resp
    sel = (f >= band[0]) & (f <= band[1])
    f, db = f[sel], db[sel]
    grid = np.unique(np.concatenate([f, [1000.0], [k[0] for k in polar]]))
    h0 = response(g, grid, 0.0)
    ref = abs(h0[grid == 1000.0][0])
    on = 20 * np.log10(abs(h0) / ref)
    r = list(np.interp(f, grid, on) - db)
    r.append(SENS_WEIGHT * 20 * math.log10(ref / sens_v_pa))
    if all_resp is not None and CAP_ON:
        fa, da = all_resp
        want = np.interp(np.log(CAP_F), np.log(fa), da)
        hh = 20 * np.log10(abs(response(g, CAP_F, 0.0)) / ref)
        r += list(np.maximum(0.0, hh - (want + CAP_DB[0])))
        r += list(np.minimum(0.0, hh - (want + CAP_DB[1])))
    for side in (90, 180):
        fr = np.array(sorted(k[0] for k in polar if k[1] == side))
        if len(fr):
            h = response(g, fr, float(side))
            mod = 20 * np.log10(abs(h) / abs(np.interp(fr, grid, abs(h0))))
            r += list(POLAR_WEIGHT * (mod - np.array([polar[(x_, side)] for x_ in fr])))
    return np.array(r)


def _label(path) -> str:
    return "/".join(str(x) for x in (path[1:] if path[0] == "network" else path))


def _has_modes(g) -> bool:
    return bool(g["diaphragm"].get("modes"))


def free_of(g) -> list:
    if "body" not in g:
        return [*FREE, RING]
    return [*FREE, *MODE] if _has_modes(g) else FREE


def band_of(g) -> tuple[float, float]:
    if "body" not in g:
        return FIT_BAND_HZ
    return MODES_BAND_HZ if _has_modes(g) else BODY_BAND_HZ


def summary(g, all_resp, polar, sens_v_pa) -> dict:
    f, db = all_resp
    h0 = response(g, f, 0.0)
    ref = abs(response(g, np.array([1000.0]), 0.0)[0])
    on = 20 * np.log10(abs(h0) / ref)
    band = (f >= band_of(g)[0]) & (f <= band_of(g)[1])
    pol = {}
    for (fr, side), want in sorted(polar.items()):
        h = response(g, np.array([fr]), float(side))[0]
        h0f = response(g, np.array([fr]), 0.0)[0]
        pol[f"{fr:.0f} Hz {side} deg"] = {"model_db": round(20 * math.log10(abs(h) / abs(h0f)), 2),
                                          "published_db": round(want, 2)}  # fmt: skip
    lp = mc.compile_network(g)
    return {
        "fitted": {_label(p): _get(g, p) for p, *_ in free_of(g)},
        **({"body": g["body"]} if "body" in g else {}),
        "sensitivity_mv_pa": round(ref * 1e3, 4),
        "sensitivity_target_mv_pa": sens_v_pa * 1e3,
        "rms_on_axis_db_fit_band": round(float(np.sqrt(np.mean((on[band] - db[band]) ** 2))), 3),
        "max_on_axis_db_fit_band": round(float(np.max(abs(on[band] - db[band]))), 3),
        "rms_on_axis_db_above": round(float(np.sqrt(np.mean((on[~band] - db[~band]) ** 2))), 3),
        "polar": pol,
        "moving_mass_mg": round(lp["moving_mass_kg"] * 1e6, 2),
        "mass_parts_mg": {
            k: round(v * 1e6, 3) for k, v in lp.get("mass_parts", {}).items() if k.endswith("_kg")
        },  # fmt: skip
        "wire_length_m": round(lp.get("mass_parts", {}).get("wire_length_m", float("nan")), 4),
        "seeler": {
            k: v
            for k, v in mc.seeler_rear_network(
                _get(g, ("network", "ps", "d_m")) / 343.2,
                _get(g, ("network", "ps", "r1_pa_s_m3")),
                _get(g, ("network", "ps", "q"))
                * _get(g, ("network", "ps", "d_m"))
                / 343.2
                * _get(g, ("network", "ps", "r1_pa_s_m3")),
            ).items()
        },  # fmt: skip
    }


def _num(v, digits: int) -> str:
    """A float as YAML 1.1 reads it back as one: an exponent needs a decimal point
    (PyYAML reads `2e-05` as a string)."""
    text = f"{float(v):.{digits}g}"
    if "e" in text and "." not in text.split("e")[0]:
        head, tail = text.split("e")
        text = f"{head}.0e{tail}"
    return text


def write(g) -> None:
    """The fitted values into published_points.yaml's R57 block, in place."""
    lines = PUBLISHED.read_text(encoding="utf-8").split("\n")
    start = next(i for i, ln in enumerate(lines) if ln.startswith('"R57":'))
    end = next((i for i in range(start + 1, len(lines)) if lines[i] and not lines[i][0].isspace()
                and not lines[i].startswith("#")), len(lines))  # fmt: skip
    paths = [p for p, *_ in free_of(g)] + ([("body", "ports_m")] if "body" in g else [])
    for path in paths:
        key, v = path[-1], _get(g, path)
        if path[0] == "network":
            hits = [i for i in range(start, end) if f"name: {path[1]}," in lines[i]]
        elif "modes" in path:
            mode = g["diaphragm"]["modes"][path[2]]["name"]
            hits = [i for i in range(start, end) if f"name: {mode}," in lines[i]]
        else:
            hits = [i for i in range(start, end) if re.match(rf"\s+{key}: \{{value:", lines[i])]
        if len(hits) != 1:
            raise SystemExit(f"published_points.yaml: {len(hits)} lines for {path}")
        i = hits[0]
        text = f"[{_num(v[0], 4)}, {_num(v[1], 4)}]" if isinstance(v, list) else _num(v, 5)
        pat = rf"({key}: \{{value: )(\[[^]]*\]|[^}}]+)\}}"
        lines[i], n = re.subn(pat, rf"\g<1>{text}}}", lines[i])
        if n != 1:
            raise SystemExit(f"published_points.yaml: {key} not on line {i + 1}")
    PUBLISHED.write_text("\n".join(lines), encoding="utf-8")


def plot(g, all_resp, polar, path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    f, db = all_resp
    ff = np.geomspace(30, 16000, 120)
    ref = abs(response(g, np.array([1000.0]), 0.0)[0])
    fig, ax = plt.subplots(1, 2, figsize=(13, 4.8))
    for th, style in ((0, "-"), (90, "--"), (180, ":")):
        ax[0].semilogx(ff, 20 * np.log10(abs(response(g, ff, th)) / ref), "k" + style,
                       lw=1.2, label=f"model {th} deg")  # fmt: skip
    ax[0].semilogx(f, db, "o", ms=3, color="tab:red", label=f"{RESPONSE_DOC} on axis")
    for (fr, side), want in polar.items():
        ax[0].plot(fr, want, "s" if side == 90 else "^", color="tab:blue", ms=5)
    ax[0].axvspan(*band_of(g), color="0.93", zorder=0)
    on = "the body" if "body" in g else "a sphere"
    ax[0].set(xlabel="Hz", ylabel="dB re on axis at 1 kHz", ylim=(-30, 10),
              title=f"R57 on {on}, open circuit (H): on axis, 90 and 180 deg")  # fmt: skip
    ax[0].grid(True, which="both", alpha=0.3)
    ax[0].legend(fontsize=8)
    th = np.radians(np.arange(0, 361, 5))
    ax[1].remove()
    ax1 = fig.add_subplot(1, 2, 2, projection="polar")
    for fr in (125.0, 1000.0, 2000.0, 4000.0, 8000.0):
        h0 = abs(response(g, np.array([fr]), 0.0)[0])
        lv = [20 * np.log10(abs(response(g, np.array([fr]), np.degrees(t))[0]) / h0) for t in th]
        ax1.plot(th, np.clip(lv, -25, 0) + 25, label=f"{fr:.0f} Hz")
    ax1.set_theta_zero_location("S")
    ax1.set_yticks([5, 10, 15, 20, 25], ["-20", "-15", "-10", "-5", "0"])
    ax1.legend(fontsize=7, loc="upper right", bbox_to_anchor=(1.3, 1.1))
    ax1.set_title("model polars (dB)")
    fig.tight_layout()
    fig.savefig(path, dpi=120)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--ports-mm", type=float, nargs="+",
                    help="rear-port band centres to try, mm behind the face")  # fmt: skip
    args = ap.parse_args()
    global CAP_ON
    entry = yaml.safe_load(PUBLISHED.read_text(encoding="utf-8"))["R57"]
    g0 = _plain(entry["geometry"])
    sens = entry["published"]["sensitivity_h_v_per_pa"]
    CAP_ON = "body" in g0 and not _has_modes(g0)  # with the mode the band covers it
    fit_resp, all_resp, polar = load_targets(band_of(g0))
    starts = [g0]
    if "body" in g0 and args.ports_mm:
        lo, hi = g0["body"]["ports_m"]
        starts = []
        for c_mm in args.ports_mm:
            g1 = copy.deepcopy(g0)
            g1["body"]["ports_m"] = [1e-3 * c_mm - 0.5 * (hi - lo), 1e-3 * c_mm + 0.5 * (hi - lo)]
            starts.append(g1)
    best, grid = None, []
    for g in starts:
        free = free_of(g)
        res = least_squares(residuals, _x0(g, free), bounds=_bounds(free), x_scale="jac",
                            args=(g, free, band_of(g), fit_resp, polar, sens, all_resp),
                            diff_step=1e-4)  # fmt: skip
        g = _with(g, res.x, free)
        out = summary(g, all_resp, polar, sens)
        out["cost"] = float(res.cost)
        out["at_bounds"] = [
            _label(p) for (p, lo, hi, log), v in zip(free, res.x, strict=True)
            if min(abs(v - (math.log(lo) if log else lo)), abs(v - (math.log(hi) if log else hi)))
            < 1e-3 * abs(v or 1)
        ]  # fmt: skip
        print(json.dumps(out, indent=1), flush=True)
        grid.append(out)
        if best is None or out["cost"] < best[1]["cost"]:
            best = (g, out)
    g, out = best
    if len(grid) > 1:
        out = {**out, "grid": [{"ports_m": x["body"]["ports_m"], "cost": x["cost"]} for x in grid]}
    rep = REPO_ROOT / "reports" / "mics"
    rep.mkdir(parents=True, exist_ok=True)
    (rep / "r57_fit.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    plot(g, all_resp, polar, rep / "r57_fit.png")
    if args.write:
        write(g)
        print("written; run: uv run varimu fit-devices --only R57")


if __name__ == "__main__":
    main()
