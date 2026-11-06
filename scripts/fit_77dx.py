"""Fit the RCA 77-DX's ribbon motor to RCA's figures (docs/CHAINS_PLAN.md WP7, step 5).

    uv run python scripts/fit_77dx.py [--rounds N] [--reactor]

The base geometry is published_points.yaml's "RIBBON_77DX": the ribbon from IB-24884-2's
parts list on Olson's polydirectional circuit (the ribbon's back on a connector cavity, the
labyrinth a matched lossy `line`, the slot under the shutter a narrow `slit` whose opening
(width, breadth) the cam sets per stop: 0 N closed, 1 L-3, 2 U, 3 L-2, 4 L-1, 5 B wide).
The unknowns are fitted one figure each to ib2's Figs. 4-5
(data/datasheets/rca_77dx_response.csv, rca_77dx_polar.csv) and its sensitivities:

    body.radius_m, depth_m     B's and N's (M) shapes from 1 to 15 kHz re 1 kHz together (the
                               gradient's path around the pole pieces and the connector; the
                               pressure ribbon's rise on the head)
    ribbon.resonance_hz,       B's (M) bass, 50 Hz-1 kHz re 1 kHz (the foil's q is the
    screen_f's rayl            44-BX's; the screen's resistance damps the resonance)
    magnet.b_gap_t             B's sensitivity, -50 dBm (3.16 mV/Pa open circuit at 250 ohm)
    lab.radius_m               N's sensitivity, -56 dBm (1.58 mV/Pa): Olson's p / (Z1 + r3)
    conn.volume_m3, lab's      N's (M) shape re 1 kHz (the hump at ~3.5 kHz: the ribbon's
    flow resistivity           mass on the connector's compliance, damped by the line)
    the opening per stop       each pattern's rows (its 90 / 180-degree levels: L-3, U, L-2,
    (width, breadth)           L-1; B's rear lobe): the gap's resistance against its mass
                               sets the omni part's phase, the L stops' large rear lobes
                               (the breadth at most the ribbon's length)

The slot's length along the flow is the shutter's thickness (ib2: .005 in), not fitted; the
patterns' 4 and 10 kHz rows are checks.

The rounds repeat the sequence (each step moves the others' figures a little). U's
sensitivity (-53 dBm) and its on-axis curve are checks, not targets. The patterns are the
horizontal plane (the ribbon upright: the incident phase is the same along its length).

The response is the open-circuit EMF across the ribbon into the transformer's primary
inductance times the turns ratio (ib2: 1:23.5); the whole circuit (config/circuits/
rca_77dx.yaml) is checked in tests/test_rca_77dx.py. Numbers -> reports/mics/rca77dx_fit.json,
plot -> reports/mics/rca77dx_fit.png; `--write` puts the fitted values into
published_points.yaml (then `varimu fit-devices --only RIBBON_77DX`).
`--reactor` checks the reactor's wiring on the whole circuit with its pinned ribbon (the
printed reactor, 0.276 H at 0.5 V and 28 ohm, its fixed end on the secondary's C or A, V1
and V2 against Fig. 5), then fits its inductance at mic level to U's V2 on that wiring
(-> reports/mics/rca77dx_reactor_check.json).
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

STOPS = ("N", "L3", "U", "L2", "L1", "B")  # the shutter from closed to wide open
N_TURNS = 23.5  # ib2: 'turns ratio 1:23.5 +-2%'
L_PRIMARY_H = 15.3e-3  # RCA77DX_OT@1's primary in its core's linear limit (its compile report)
SENS = {"B": 3.16e-3, "U": 2.24e-3, "N": 1.58e-3}  # ib2: -50 / -53 / -56 dBm, sqrt(4 R P)
TOP_HZ = (1000.0, 15000.0)
BASS_HZ = (50.0, 1000.0)
ANGLES_DEG = (0.0, 90.0, 135.0, 150.0, 170.0, 180.0)
MAX_BREADTH_M = 50.8e-3  # the slot behind the ribbon: no longer than the ribbon (ib2's 2 in)
BOUND_DB = -15.0  # the patterns' innermost readable ring
REPORT = REPO_ROOT / "reports" / "mics"


def curves() -> dict:
    """(pattern, curve) -> (f, dB, weight) of ib2 Fig. 5."""
    with open(DATA_DIR / "datasheets" / "rca_77dx_response.csv", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    out = {}
    for x in rows:
        out.setdefault((x["pattern"], x["curve"]), []).append(x)
    res = {}
    for k, r in out.items():
        f = np.array([float(x["freq_hz"]) for x in r])
        db = np.array([float(x["db"]) for x in r])
        w = np.array([0.5 if x["quality"] == "rule" else 1.0 for x in r])
        res[k] = (f, db, w)
    return res


def polars() -> list[dict]:
    """ib2 Fig. 4's key angles: stop, f, angle, dB, weight, bound (a ceiling, not a level)."""
    with open(DATA_DIR / "datasheets" / "rca_77dx_polar.csv", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    out = []
    for x in rows:
        out.append({
            "stop": STOPS.index(x["pattern"]),
            "pattern": x["pattern"], "f": float(x["freq_hz"]), "angle": float(x["angle_deg"]),
            "db": float(x["db"]), "bound": x["quality"] == "bound",
            "w": 0.5 if x["quality"] == "single" else 1.0,
        })  # fmt: skip
    return out


def base() -> dict:
    return _plain(_published()["RIBBON_77DX"]["geometry"])


def unknowns(g: dict) -> dict:
    """The fitted values read from a geometry."""
    net = {e["name"]: e for e in g["network"]}
    return {
        "radius_m": g["body"]["radius_m"], "depth_m": g["body"]["depth_m"],
        "resonance_hz": g["ribbon"]["resonance_hz"],
        "b_gap_t": g["magnet"]["b_gap_t"],
        "lab_radius_m": net["lab"]["radius_m"],
        "lab_sigma": net["lab"]["flow_resistivity_pa_s_m2"],
        "conn_m3": net["conn"]["volume_m3"],
        "screen_rayl": net["screen_f"]["rayl"],
        "slot_length_m": net["slot"]["length_m"],
        "openings_m": [None if s is None else [s["width_m"], s["breadth_m"]]
                       for s in net["slot"]["stops"]],
    }  # fmt: skip


def geometry(g0: dict, u: dict) -> dict:
    """The base geometry with the unknowns `u` (and the front channel from the depth)."""
    g = copy.deepcopy(g0)
    g["body"].update(radius_m=u["radius_m"], depth_m=u["depth_m"])
    g["ribbon"]["resonance_hz"] = u["resonance_hz"]
    g["magnet"]["b_gap_t"] = u["b_gap_t"]
    net = {e["name"]: e for e in g["network"]}
    gap, length = net["rad_f"]["width_m"], g["ribbon"]["length_m"]
    for n in ("chan_f_a", "chan_f_b"):
        net[n]["length_m"] = 0.25 * u["depth_m"]
    net["cav_f"]["volume_m3"] = gap * length * 0.5 * u["depth_m"]
    net["lab"].update(radius_m=u["lab_radius_m"], flow_resistivity_pa_s_m2=u["lab_sigma"])
    net["conn"]["volume_m3"] = u["conn_m3"]
    net["screen_f"]["rayl"] = u["screen_rayl"]
    net["slot"]["length_m"] = u["slot_length_m"]
    net["slot"]["stops"] = [None if o is None else {"width_m": o[0], "breadth_m": o[1]}
                            for o in u["openings_m"]]  # fmt: skip
    net["rad_r"]["stops"] = [None if o is None else {"width_m": o[0], "length_m": o[1]}
                             for o in u["openings_m"]]  # fmt: skip
    return g


def motor(g: dict) -> mc.MovingCoil:
    return mc.moving_coil_from_data(
        {"name": "fit", "kind": "ribbon_motor", "lumped": ribbon.compile_network(g)},
        kind="ribbon_motor",
    )


_BEM: dict = {}


def entries(body: dict, a: float, f: np.ndarray, theta_deg) -> tuple[np.ndarray, np.ndarray]:
    th = tuple(float(x) for x in theta_deg)
    key = (round(body["radius_m"], 8), round(body["depth_m"], 8), a, tuple(f), th)
    if key not in _BEM:
        op = bor.operator(bor.baffle_mesh(body, a, panel_m=0.75e-3))
        _BEM[key] = bor.entry_factors(op, f, np.radians(th))
    return _BEM[key]


def response(g: dict, stop: int, f: np.ndarray, theta_deg=(0.0,)) -> np.ndarray:
    """Open-circuit volts at the 250 ohm strap per pascal (freqs, angles), horizontal plane."""
    fr, rr = entries(g["body"], bor.entry_size(g), f, theta_deg)
    c = ribbon.at_stop(motor(g), stop)
    out = np.zeros(fr.shape, complex)
    for j in range(fr.shape[1]):
        out[:, j] = N_TURNS * networks.moving_coil_response(
            c, f, (fr[:, j], rr[:, j]), l_load_h=L_PRIMARY_H
        )
    return out


def target(cv, pattern: str, band):
    f, db, w = cv[(pattern, "M")]
    ref = np.interp(np.log(1000.0), np.log(f), db)
    k = (f >= band[0]) & (f <= band[1])
    fk = np.unique(np.r_[f[k], 1000.0])
    return fk, np.interp(np.log(fk), np.log(f), db) - ref, np.interp(np.log(fk), np.log(f), w)


def curve_rms(g, cv, pattern: str, band) -> float:
    f, t, w = target(cv, pattern, band)
    h = response(g, STOPS.index(pattern), f)[:, 0]
    i = int(np.argmin(np.abs(f - 1000.0)))
    d = 20 * np.log10(np.abs(h / h[i])) - t
    return float(np.sqrt(np.sum(w * d**2) / np.sum(w)))


def polar_errors(g, rows, stops=None) -> np.ndarray:
    """Model minus reading (dB, weighted) per polar row; a bound row only above its ring."""
    out = []
    for stop in sorted({r["stop"] for r in rows}):
        if stops is not None and stop not in stops:
            continue
        rs = [r for r in rows if r["stop"] == stop]
        fs = np.array(sorted({r["f"] for r in rs}))
        h = response(g, stop, fs, ANGLES_DEG)
        rel = 20 * np.log10(np.abs(h / h[:, :1]))
        for r in rs:
            m = rel[list(fs).index(r["f"]), ANGLES_DEG.index(r["angle"])]
            e = max(0.0, m - BOUND_DB) if r["bound"] else m - r["db"]
            out.append(np.sqrt(r["w"]) * e)
    return np.array(out)


def sensitivity(g, pattern: str) -> float:
    return float(abs(response(g, STOPS.index(pattern), np.array([1000.0]))[0, 0]))


def _nm(fun, x0, fev, tol=1e-3):
    return minimize(fun, x0, method="Nelder-Mead",
                    options={"xatol": tol, "fatol": 1e-4, "maxfev": fev})  # fmt: skip


def fit_round(g0: dict, u: dict, cv, rows, log, polish: bool = False) -> dict:
    u = copy.deepcopy(u)

    def with_(**kw):
        return geometry(g0, {**u, **kw})

    if not polish:  # --polish: the openings and the sensitivities only
        # 1. the body: B's and N's tops (the gradient's path and the pressure ribbon's on-axis
        # rise on the head: an equivalent disc can't have both, so their sum)
        def body_cost(x):
            if not (2.0 < x[1] < 60.0 and 2.0 < x[0] < 60.0):
                return 99.0
            g = with_(radius_m=x[0] * 1e-3, depth_m=x[1] * 1e-3)
            return curve_rms(g, cv, "B", TOP_HZ) + curve_rms(g, cv, "N", TOP_HZ)

        s = _nm(body_cost, [u["radius_m"] * 1e3, u["depth_m"] * 1e3], 60, 0.05)
        u["radius_m"], u["depth_m"] = round(s.x[0] * 1e-3, 7), round(s.x[1] * 1e-3, 7)
        g = with_()
        eb, en = curve_rms(g, cv, "B", TOP_HZ), curve_rms(g, cv, "N", TOP_HZ)
        log(f"body {u['radius_m'] * 1e3:.2f} x {u['depth_m'] * 1e3:.2f} mm: B top rms {eb:.2f}, "
            f"N top {en:.2f} dB")  # fmt: skip
        # 2. the tuning and the screen's resistance (it damps the resonance in place): B's bass
        s = _nm(lambda x: curve_rms(with_(resonance_hz=x[0], screen_rayl=np.exp(x[1])), cv, "B",
                                    BASS_HZ) if 1.0 < x[0] < 400.0 else 99.0,
                [u["resonance_hz"], np.log(u["screen_rayl"])], 120, 0.01)  # fmt: skip
        u["resonance_hz"] = round(float(s.x[0]), 2)
        u["screen_rayl"] = round(float(np.exp(s.x[1])), 3)
        log(f"resonance {u['resonance_hz']} Hz screen {u['screen_rayl']} rayl: B bass rms "
            f"{s.fun:.2f} dB")  # fmt: skip
        # 3. the connector and the stuffing: N's shape
        s = _nm(lambda x: curve_rms(with_(conn_m3=np.exp(x[0]), lab_sigma=np.exp(x[1])), cv, "N",
                                    (50.0, 15000.0)),
                [np.log(u["conn_m3"]), np.log(u["lab_sigma"])], 120, 0.005)  # fmt: skip
        u["conn_m3"], u["lab_sigma"] = float(np.exp(s.x[0])), round(float(np.exp(s.x[1])), 1)
        log(f"conn {u['conn_m3'] * 1e6:.3f} cm^3, sigma {u['lab_sigma']}: N rms {s.fun:.2f} dB")
    # 4. each stop's opening (width, breadth) to its pattern's 400-1000 cps rows (the 4 and
    # 10 kHz rows are checks)
    low = [r for r in rows if r["f"] <= 1000.0]
    for k, wb in enumerate(u["openings_m"]):
        if wb is None:
            continue

        def stop_cost(x, k=k):
            w, b = float(np.exp(x[0])), float(np.exp(x[1]))
            if not (20e-6 < w < 15e-3 and 0.5e-3 < b <= MAX_BREADTH_M):
                return 1e4
            op = list(u["openings_m"])
            op[k] = [w, b]
            return float(np.sum(polar_errors(with_(openings_m=op), low, {k}) ** 2))

        s = _nm(stop_cost, [np.log(wb[0]), np.log(min(wb[1], 0.999 * MAX_BREADTH_M))], 150, 1e-3)
        u["openings_m"][k] = [round(float(np.exp(s.x[0])), 8), round(float(np.exp(s.x[1])), 8)]
    e = polar_errors(with_(), rows)
    log(
        "openings (w x b) "
        + ", ".join("-" if o is None else f"{o[0] * 1e3:.3f} x {o[1] * 1e3:.2f}"
                    for o in u["openings_m"])
        + f" mm: polar rms (all rows) {np.sqrt(np.mean(e**2)):.2f} dB"
    )  # fmt: skip
    # 5. B's sensitivity, 6. N's (last: every step above moves them; alternately)
    for _ in range(3):
        u["b_gap_t"] *= SENS["B"] / sensitivity(with_(), "B")

        def n_err(x):
            return abs(np.log(sensitivity(with_(lab_radius_m=np.exp(x[0])), "N") / SENS["N"]))

        s = _nm(n_err, [np.log(u["lab_radius_m"])], 40, 1e-4)
        u["lab_radius_m"] = float(np.exp(s.x[0]))
    u["b_gap_t"] = round(u["b_gap_t"], 4)
    u["lab_radius_m"] = round(u["lab_radius_m"], 7)
    g = with_()
    log(f"B {u['b_gap_t']} T, lab radius {u['lab_radius_m'] * 1e3:.3f} mm: B "
        f"{sensitivity(g, 'B') * 1e3:.3f}, N {sensitivity(g, 'N') * 1e3:.3f} mV/Pa")  # fmt: skip
    return u


def summary(g, cv, rows) -> dict:
    out = {}
    for p in ("B", "U", "N"):
        out[f"sensitivity_{p}_mv_per_pa"] = round(1e3 * sensitivity(g, p), 3)
        out[f"sensitivity_{p}_target_mv_per_pa"] = SENS[p] * 1e3
        f, t, _ = target(cv, p, (50.0, 15000.0))
        h = response(g, STOPS.index(p), f)[:, 0]
        d = 20 * np.log10(np.abs(h / h[int(np.argmin(np.abs(f - 1000.0)))])) - t
        for lo, hi in ((50, 1000), (1000, 10000), (10000, 15000)):
            k = (f >= lo) & (f <= hi)
            out[f"{p}_{lo}_{hi}_rms_db"] = round(float(np.sqrt(np.mean(d[k] ** 2))), 2)
            out[f"{p}_{lo}_{hi}_max_db"] = round(float(np.max(np.abs(d[k]))), 2)
            out[f"{p}_{lo}_{hi}_max_at_hz"] = float(f[k][np.argmax(np.abs(d[k]))])
    pol = []
    for r in rows:
        h = response(g, r["stop"], np.array([r["f"]]), ANGLES_DEG)[0]
        m = 20 * np.log10(abs(h[ANGLES_DEG.index(r["angle"])] / h[0]))
        pol.append({"pattern": r["pattern"], "f": r["f"], "angle": r["angle"],
                    "read_db": r["db"], "model_db": round(float(m), 2),
                    "bound": r["bound"]})  # fmt: skip
    out["polars"] = pol
    e = [p["model_db"] - p["read_db"] for p in pol if not p["bound"]]
    out["polar_rms_db"] = round(float(np.sqrt(np.mean(np.square(e)))), 2)
    out["polar_max_db"] = round(float(np.max(np.abs(e))), 2)
    lumped = ribbon.compile_network(g)
    out["foil_ohm"] = round(lumped["foil_ohm"], 4)
    out["moving_mass_mg"] = round(lumped["moving_mass_kg"] * 1e6, 3)
    return out


PUBLISHED = DATA_DIR / "datasheets" / "published_points.yaml"


def write_published(u: dict) -> None:
    """The fitted values into published_points.yaml's "RIBBON_77DX" (its text: the sources and
    comments stay)."""
    import re

    text = PUBLISHED.read_text(encoding="utf-8")
    i = text.index('"RIBBON_77DX":')
    j = text.find("\n\n", i)
    j = len(text) if j < 0 else j
    lines = text[i:j].split("\n")

    def val(x: float) -> str:
        return f"{{value: {float(f'{x:.5g}')!r}}}"

    def line_of(line_key: str) -> int:
        k = [n for n, x in enumerate(lines) if line_key in x]
        if not k:
            raise ValueError(f"published_points: no line with {line_key!r}")
        return k[0]

    def field(line_key: str, key: str, x: float) -> None:
        n = line_of(line_key)
        pat = re.compile(r"(\b" + re.escape(key) + r": )\{value: [^}]*\}")
        lines[n], c = pat.subn(lambda m: m.group(1) + val(x), lines[n], count=1)
        if c != 1:
            raise ValueError(f"published_points: {line_key} {key} not found")

    def stops(name: str, keys: tuple[str, str]) -> None:
        items = ", ".join(
            "null" if o is None else f"{{{keys[0]}: {val(o[0])}, {keys[1]}: {val(o[1])}}}"
            for o in u["openings_m"]
        )
        n = line_of(f"name: {name},")
        pat = re.compile(r"(stops: )\[[^\]]*\]")
        lines[n], c = pat.subn(lambda m: m.group(1) + "[" + items + "]", lines[n], count=1)
        if c != 1:
            raise ValueError(f"published_points: {name}'s stops not found")

    field("      radius_m:", "radius_m", u["radius_m"])
    field("      depth_m:", "depth_m", u["depth_m"])
    field("resonance_hz:", "resonance_hz", u["resonance_hz"])
    field("b_gap_t:", "b_gap_t", u["b_gap_t"])
    field("name: screen_f,", "rayl", u["screen_rayl"])
    field("name: conn,", "volume_m3", u["conn_m3"])
    field("name: lab,", "radius_m", u["lab_radius_m"])
    field("name: lab,", "flow_resistivity_pa_s_m2", u["lab_sigma"])
    # derived from the depth (geometry()): the front channel's halves and its air
    net = {e["name"]: e for e in geometry(base(), u)["network"]}
    for name in ("chan_f_a", "chan_f_b"):
        field(f"name: {name},", "length_m", net[name]["length_m"])
    field("name: cav_f,", "volume_m3", net["cav_f"]["volume_m3"])
    stops("slot", ("width_m", "breadth_m"))
    stops("rad_r", ("width_m", "length_m"))
    PUBLISHED.write_text(text[:i] + "\n".join(lines) + text[j:], encoding="utf-8")


def circuit_response(over: dict, f: np.ndarray, wiring: str = "C") -> np.ndarray:
    """The whole mic (config/circuits/rca_77dx.yaml, its pinned ribbon) at `over`'s settings:
    volts at `out` per pascal of a plane wave on axis. `wiring`: the reactor's fixed end on
    the secondary's C (the file's: V1 across C-B) or A (V1 across A-B)."""
    from varimu.circuit import builder, spec
    from varimu.devices.library import component_data
    from varimu.measure import ac

    s = spec.load_circuit(spec.circuit_path("rca_77dx"))
    if wiring == "A":
        s = copy.deepcopy(s)
        sw = next(x for x in s.sections if x["title"] == "transformer")["parts"]["SRESP"]["parts"]
        sw["LRX"]["L"] = ["ta", "rx"]
        sw["RRX2"]["R"] = ["rx", "tc"]
    q = spec.resolve(s, over)
    g = component_data(str(q["ribbon_model"]))["geometry"]
    fr, rr = entries(g["body"], bor.entry_size(g), f, (0.0,))
    front, rear = fr[:, 0], rr[:, 0]
    ir = builder.build_ir(s, q, "linear")
    return front * ac.transfer(ir, f, "out", drives={"p_rear": rear / front})


PRINTED_REACTOR_H = 0.276  # ib2: 91 ohm at 50 cps, 0.5 v, 28 ohm DC: sqrt(91^2 - 28^2) / 2 pi 50


def _voice_errors(cv, p: str, curve: str, pos: int, wiring: str, reactor_h: float):
    """Model minus Fig. 5 (dB re 1 kHz) on 50-600 Hz and the model's / RCA's at 100 Hz."""
    f, _, _ = cv[(p, curve)]
    k = (f >= 50.0) & (f <= 600.0)
    fk = np.r_[f[k], 1000.0]
    over = {"pattern": STOPS.index(p), "response": pos, "reactor_h": reactor_h}
    h = circuit_response(over, fk, wiring)
    model = 20 * np.log10(np.abs(h[:-1] / h[-1]))
    fc, dc, _ = cv[(p, curve)]
    t = np.interp(np.log(fk[:-1]), np.log(fc), dc) - np.interp(np.log(1000.0), np.log(fc), dc)
    at = [float(np.interp(np.log(100.0), np.log(fk[:-1]), x)) for x in (model, t)]
    return model - t, at


def reactor_check(cv) -> dict:
    """The reactor (ib2: 0.276 H at 0.5 V, 28 ohm). First which wiring ib Fig. 2 draws: V1
    and V2 re M on 50-600 Hz with the printed reactor, its fixed end on C or on A, for U, B
    and N. Then its inductance at a ribbon's millivolts (an iron core's initial permeability:
    less than at 0.5 V) fitted to U's V2 on that wiring, the 28 ohm kept; V1 and B / N
    checks."""
    from scipy.optimize import minimize_scalar

    out: dict = {}

    def rec(tag, e, at):
        out[f"{tag}_rms_db"] = round(float(np.sqrt(np.mean(e**2))), 2)
        out[f"{tag}_max_db"] = round(float(np.max(np.abs(e))), 2)
        out[f"{tag}_at_100_db"] = [round(x, 2) for x in at]

    score = {}
    for wiring in ("C", "A"):
        score[wiring] = 0.0
        for p in ("U", "B", "N"):
            for curve, pos in (("V1", 1), ("V2", 2)):
                e, at = _voice_errors(cv, p, curve, pos, wiring, PRINTED_REACTOR_H)
                rec(f"printed_{wiring}_{p}_{curve}", e, at)
                score[wiring] += float(np.sum(e**2))
    wiring = min(score, key=score.get)
    out["wiring"] = wiring
    s = minimize_scalar(
        lambda x: float(np.sum(_voice_errors(cv, "U", "V2", 2, wiring, np.exp(x))[0] ** 2)),
        bounds=(np.log(0.02), np.log(1.0)), method="bounded",
    )  # fmt: skip
    lh = round(float(np.exp(s.x)), 4)
    out["reactor_h"] = lh
    for p in ("U", "B", "N"):
        for curve, pos in (("V1", 1), ("V2", 2)):
            rec(f"fitted_{p}_{curve}", *_voice_errors(cv, p, curve, pos, wiring, lh))
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--rounds", type=int, default=3)
    ap.add_argument("--write", action="store_true", help="write the fit into published_points")
    ap.add_argument(
        "--polish", action="store_true",
        help="from published_points' values: only the openings and the sensitivities",
    )  # fmt: skip
    ap.add_argument(
        "--reactor", action="store_true",
        help="check the reactor's wiring on the whole circuit (its pinned ribbon) instead",
    )  # fmt: skip
    args = ap.parse_args()
    if args.reactor:
        r = reactor_check(curves())
        REPORT.mkdir(parents=True, exist_ok=True)
        (REPORT / "rca77dx_reactor_check.json").write_text(json.dumps(r, indent=1))
        print(json.dumps(r, indent=1))
        return
    g0 = base()
    cv, rows = curves(), polars()
    u = unknowns(g0)
    lines = []

    def log(s):
        print(s, flush=True)
        lines.append(s)

    for k in range(args.rounds):
        log(f"-- round {k + 1}")
        u = fit_round(g0, u, cv, rows, log, polish=args.polish)
    g = geometry(g0, u)
    result = {"unknowns": u, **summary(g, cv, rows), "log": lines}
    REPORT.mkdir(parents=True, exist_ok=True)
    (REPORT / "rca77dx_fit.json").write_text(json.dumps(result, indent=1))
    if args.write:
        write_published(u)
    print(json.dumps({k: v for k, v in result.items() if k not in ("polars", "log")}, indent=1))
    plot(g, cv, rows)


def plot(g, cv, rows) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(1, 2, figsize=(14, 5.2))
    f = np.geomspace(40, 16000, 160)
    for i, p in enumerate(("U", "B", "N")):
        fm, dm, _ = cv[(p, "M")]
        off = -12 * i
        ax[0].semilogx(fm, dm + off, f"C{i}.", ms=3)
        h = response(g, STOPS.index(p), np.r_[f, 1000.0])[:, 0]
        ax[0].semilogx(
            f, 20 * np.log10(np.abs(h[:-1] / h[-1])) + off, f"C{i}", label=f"{p} (offset {off} dB)"
        )
    ax[0].set(xlabel="Hz", ylabel="dB re 1 kHz", ylim=(-45, 12),
              title="RCA 77-DX, M: ib2 Fig. 5 (dots) and the model")  # fmt: skip
    ax[0].grid(True, which="both", alpha=0.3)
    ax[0].legend()
    th = np.arange(0.0, 181.0, 5.0)
    for i, stop in enumerate(range(1, 6)):
        fz = min(r["f"] for r in rows if r["stop"] == stop)
        h = response(g, stop, np.array([fz]), th)[0]
        ax[1].plot(th, 20 * np.log10(np.abs(h / h[0])), f"C{i}", label=f"{STOPS[stop]} {fz:g} Hz")
        pts = [r for r in rows if r["stop"] == stop and r["f"] == fz]
        ax[1].plot([r["angle"] for r in pts], [r["db"] for r in pts], f"C{i}o",
                   mfc="none" if any(r["bound"] for r in pts) else None)  # fmt: skip
    ax[1].set(xlabel="degrees (horizontal plane)", ylabel="dB", ylim=(-30, 2),
              title="ib2 Fig. 4 at 400-1000 cps (circles) and the model")  # fmt: skip
    ax[1].grid(True, alpha=0.3)
    ax[1].legend()
    fig.tight_layout()
    fig.savefig(REPORT / "rca77dx_fit.png", dpi=100)


if __name__ == "__main__":
    main()
