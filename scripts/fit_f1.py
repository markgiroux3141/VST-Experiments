"""Fit the Western Electric F1 carbon transmitter (docs/CHAINS_PLAN.md WP31) to Jones's figures
(BSTJ 17, 1938; data/schematics/carbon_transmitter/README.md).

The acoustics are Jones's Fig. 6 network in the impedance analogy (pressure as volts, volume
velocity as amperes), from the face inward: the second grid's holes (m0 r0), the cavity s0, the
moisture membrane (m1 r1), the cavity s1, the diaphragm lumped (its three portions move as one
below 3500 cycles: Jones) with the paper books' stiffness s4 and the carbon's s5 in series, the
back cavity s3 (the controlling stiffness), and the equalizing hole (m3 r3) from the diaphragm's
front into s3. The carbon's force is s5 x: the area S times the voltage on s5.

The carbon: varimu.devices.carbon's law, G(F) = G_open + G0 (F_s / F0)^n with F_s = s ln(1 +
exp(F / s)), F0 = F_s(F_p) so G(F_p) = G_open + G0 = 1 / R0. Fed as Jones's Fig. 5: 20.5 V
through 513 ohm. The response's "volts open circuit" is the transmitter's EMF, I0 dR (Claude's
reading, WP31's Decisions).

Fitted, one figure per unknown (data/datasheets/we_f1_*.csv):
- the hole's resistance and mass: the low end (90 and 135 cycles, the bump at ~280);
- the diaphragm's mass and resistance: the 2000-cycle peak's frequency and height;
- the membrane's mass: the fall to 5000 cycles;
- the level (the preload F_p, given n and the knee): Fig. 6's level;
- n and the zero-force resistance R_open (the granules' own weight; the knee fixed): Fig. 7's
  sum and difference components (1500 + 1700 cycles), their
  rise (1.5-3 bars) and plateau (6-100 bars); a memoryless law makes the two components equal,
  so each is fitted to both (the difference runs ~7 dB above the sum: Jones's "a property of the
  carbon itself", a known miss);
- G0: the resistance R0 (Fig. 5: the new type after two years' aging, the unit Fig. 6 measured).

    uv run python scripts/fit_f1.py [--write] [--plot]

--write puts the fitted values into config/circuits/carbon_transmitter.yaml (the network and
the preload) and data/datasheets/published_points.yaml's "F1" block (the carbon law); then
`varimu fit-devices --only F1` saves the component version.
"""

from __future__ import annotations

import argparse
import csv
import math
import re
from pathlib import Path

import numpy as np
from scipy.optimize import least_squares

from varimu.config import REPO_ROOT
from varimu.devices.capsule import C_AIR, MU_AIR, RHO_AIR

DATA = REPO_ROOT / "data" / "datasheets"
CIRCUIT = REPO_ROOT / "config" / "circuits" / "carbon_transmitter.yaml"
PUBLISHED = DATA / "published_points.yaml"
BAR_PA = 0.1  # 1 bar = 1 dyne / cm^2
RHO_C2 = RHO_AIR * C_AIR**2

# Fig. 5's transmitter circuit and resistances (Jones p. 346).
E_V = 20.5
RS_OHM = 513.0
R0_OHM = 63.0  # the new type at two years' equivalent aging (Fig. 5's point "2")

# Provisional dimensions (model knowledge: the F1 unit is ~2 in across; WP31's Decisions).
RADIUS_M = 0.021  # the diaphragm's
AREA_M2 = math.pi * RADIUS_M**2
V0_M3 = 0.5e-6  # between the handset's grid and the membrane
V1_M3 = 2.0e-6  # between the membrane and the diaphragm's cone
V3_M3 = 1.5e-6  # behind the diaphragm (the die-cast frame's cavity)
S4_N_M = 2.0e4  # the paper books
S5_N_M = 5.0e4  # the carbon chamber
GRID_HOLES, GRID_HOLE_R_M, GRID_T_M = 20, 0.75e-3, 2.0e-3  # the second (insulating) grid
MEMBRANE_R = 1.0e5  # the membrane's loss (small; acoustic ohm)
# The law's knee s / F_p (Claude's call, WP31's Decisions): fitted, it ran to its bound with
# little gain (Fig. 7's rms 3.9 dB at 1, 3.6 at 10); s = F_p, the granules' spread of contact
# loads as wide as the working force.
KNEE = 1.0


def grid_values() -> tuple[float, float]:
    """The second grid's holes: mass with end corrections and Poiseuille resistance."""
    a = math.pi * GRID_HOLE_R_M**2 * GRID_HOLES
    m = RHO_AIR * (GRID_T_M + 1.7 * GRID_HOLE_R_M) / a
    r = 8 * MU_AIR * GRID_T_M / (GRID_HOLES * math.pi * GRID_HOLE_R_M**4)
    return m, r


def fixed() -> dict[str, float]:
    m0, r0 = grid_values()
    return {
        "grid_m": m0,
        "grid_r": r0,
        "cav0_c": V0_M3 / RHO_C2,
        "mem_r": MEMBRANE_R,
        "cav1_c": V1_M3 / RHO_C2,
        "books_c": AREA_M2**2 / S4_N_M,
        "carbon_c": AREA_M2**2 / S5_N_M,
        "back_c": V3_M3 / RHO_C2,
    }


FREE = ("hole_r", "hole_m", "dia_m", "dia_r", "mem_m")
START = {"hole_r": 1.0e8, "hole_m": 4.0e4, "dia_m": 600.0, "dia_r": 2.5e6, "mem_m": 200.0}


def force_per_pa(v: dict[str, float], f: np.ndarray) -> np.ndarray:
    """F / p (N per Pa at the face), complex, by nodal analysis of the network."""
    w = 2 * np.pi * np.atleast_1d(f)
    out = np.empty(len(w), complex)
    for k, wk in enumerate(w):
        y = np.zeros((5, 5), complex)  # n0 n1 nd nc nb
        b = np.zeros(5, complex)

        def add(i, j, adm, y=y):
            if i is not None:
                y[i, i] += adm
            if j is not None:
                y[j, j] += adm
            if i is not None and j is not None:
                y[i, j] -= adm
                y[j, i] -= adm

        yg = 1 / (v["grid_r"] + 1j * wk * v["grid_m"])
        add(0, None, yg)
        b[0] += yg  # p = 1 at the face
        add(0, None, 1j * wk * v["cav0_c"])
        add(0, 1, 1 / (v["mem_r"] + 1j * wk * v["mem_m"]))
        add(1, None, 1j * wk * v["cav1_c"])
        add(1, 2, 1 / (v["dia_r"] + 1j * wk * v["dia_m"]))
        add(2, 3, 1j * wk * v["books_c"])
        add(3, 4, 1j * wk * v["carbon_c"])
        add(4, None, 1j * wk * v["back_c"])
        add(1, 4, 1 / (v["hole_r"] + 1j * wk * v["hole_m"]))
        x = np.linalg.solve(y, b)
        out[k] = AREA_M2 * (x[3] - x[4])
    return out


def load(name: str) -> dict[str, np.ndarray]:
    rows = list(csv.DictReader((DATA / name).open(encoding="utf-8")))
    key = next(iter(rows[0]))
    out: dict[str, list] = {}
    for r in rows:
        out.setdefault(r[key], []).append([float(x) for k, x in r.items() if k != key])
    return {k: np.array(v) for k, v in out.items()}


def carbon_law(fp_n: float, n: float, knee: float, g_open: float) -> dict[str, float]:
    """The law's parameters for a preload, exponent, knee (s / F_p) and zero-force
    conductance."""
    s = knee * fp_n
    f0 = s * math.log1p(math.exp(fp_n / s))
    return {"g0_s": 1 / R0_OHM - g_open, "f0_n": f0, "exponent": n, "g_open_s": g_open,
            "soft_n": s}  # fmt: skip


def g_of(law: dict[str, float], f_n: np.ndarray) -> np.ndarray:
    s = law["soft_n"]
    fs = s * np.logaddexp(0.0, np.asarray(f_n) / s)
    return law["g_open_s"] + law["g0_s"] * (fs / law["f0_n"]) ** law["exponent"]


def rel_sensitivity(n: float, knee: float, g_open: float) -> float:
    """F_p |dR / dF| / R0 at the preload (independent of F_p)."""
    z = 1.0 / knee
    sig = 1.0 / (1.0 + math.exp(-z))
    return (1 - g_open * R0_OHM) * n * sig / (knee * math.log1p(math.exp(z)))


def emf_per_pa(v, f, fp_n, n, knee, g_open) -> np.ndarray:
    """The EMF I0 dR per pascal at the face, complex."""
    i0 = E_V / (RS_OHM + R0_OHM)
    return i0 * R0_OHM * rel_sensitivity(n, knee, g_open) / fp_n * force_per_pa(v, f)


def products_db(v, fp_n, n, knee, g_open, p_bar) -> float:
    """dB below the fundamental of the sum (= difference) component for 1500 + 1700 cycles at
    p_bar each (rms), the transmitter's voltage in Fig. 5's circuit, its law memoryless."""
    law = carbon_law(fp_n, n, knee, g_open)
    h = force_per_pa(v, np.array([1500.0, 1700.0]))
    m = 4096
    t = np.arange(m) / m * 0.01  # one period of 100 cycles
    amp = p_bar * BAR_PA * math.sqrt(2)
    f = fp_n + np.real(amp * (h[0] * np.exp(2j * np.pi * 1500 * t) + h[1] *
                              np.exp(2j * np.pi * 1700 * t)))  # fmt: skip
    r = 1 / g_of(law, f)
    u = E_V * r / (RS_OHM + r)
    spec = np.abs(np.fft.rfft(u)) / m
    fund = 0.5 * (spec[15] + spec[17])
    prod = 0.5 * (spec[2] + spec[32])
    return float(20 * np.log10(fund / prod))


def fit_response(resp):
    f, d = resp[:, 0], resp[:, 1]
    fx = fixed()

    def model(x):
        v = {**fx, **{k: math.exp(xi) for k, xi in zip(FREE, x, strict=True)}}
        return v, 20 * np.log10(np.abs(force_per_pa(v, f)))

    def res(x):
        m = model(x)[1]
        return m + np.mean(d - m) - d

    x0 = np.log([START[k] for k in FREE])
    sol = least_squares(res, x0, bounds=(x0 - math.log(100), x0 + math.log(100)))
    v, m = model(sol.x)
    offset = float(np.mean(d - m))  # dB: 20 log10(A 0.1), A the EMF per N of force
    return v, offset, res(sol.x)


def fit_carbon(v, offset_db, im):
    """n and the zero-force conductance to Fig. 7 (the knee fixed at KNEE); the preload then
    to the level."""
    a = 10 ** (offset_db / 20) / BAR_PA  # EMF (V) per newton of force
    i0r0 = E_V / (RS_OHM + R0_OHM) * R0_OHM
    pts = [(c, p, d) for c, rows in im.items() for p, d in rows]

    def unpack(x):
        n, rr = (math.exp(xi) for xi in x)  # rr: R_open / R0
        g_open = 1 / (R0_OHM * rr)
        return i0r0 * rel_sensitivity(n, KNEE, g_open) / a, n, KNEE, g_open

    def res(x):
        fp, n, knee, g_open = unpack(x)
        return np.array([products_db(v, fp, n, knee, g_open, p) - d for _, p, d in pts])

    lo, hi = np.log([0.03, 1.2]), np.log([3.0, 200.0])
    best = None
    for n0 in (0.2, 0.6):
        for r0 in (2.0, 8.0):
            s = least_squares(res, np.log([n0, r0]), bounds=(lo, hi))
            if best is None or s.cost < best.cost:
                best = s
    return (*unpack(best.x), pts, res(best.x))


def yaml_num(x: float, digits: int = 5) -> str:
    """A number YAML reads as a float (1.0e+05, not 1e+05)."""
    t = f"{x:.{digits}g}"
    if "e" in t and "." not in t.split("e")[0]:
        t = t.replace("e", ".0e", 1)
    return t


def write_values(path: Path, values: dict[str, float], pattern: str) -> None:
    text = path.read_bytes().decode("utf-8")
    for k, x in values.items():
        text, c = re.subn(pattern.format(key=re.escape(k)), rf"\g<1>{yaml_num(x)}", text)
        if c != 1:
            raise SystemExit(f"{path.name}: {c} lines for {k}")
    path.write_bytes(text.encode("utf-8"))


def write_published(law: dict[str, float]) -> None:
    text = PUBLISHED.read_bytes().decode("utf-8")
    start = text.index('"F1":')
    end = text.find('\n"', start + 1)
    end = len(text) if end < 0 else end
    block = text[start:end]
    for k, x in law.items():
        block, c = re.subn(rf"(\n\s+{k}: \{{value: )[^,}}]+", rf"\g<1>{yaml_num(x, 6)}", block)
        if c != 1:
            raise SystemExit(f"published_points.yaml F1: {c} lines for {k}")
    PUBLISHED.write_bytes((text[:start] + block + text[end:]).encode("utf-8"))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--plot", action="store_true")
    args = ap.parse_args()
    resp = load("we_f1_response.csv")["measured"]
    im = load("we_f1_intermod.csv")
    v, offset, r1 = fit_response(resp)
    fp, n, knee, g_open, pts, r2 = fit_carbon(v, offset, im)
    law = carbon_law(fp, n, knee, g_open)
    print("network (acoustic ohm, kg/m^4, m^5/N):")
    for k, x in v.items():
        print(f"  {k:9s} {x:.5g}" + ("  (fitted)" if k in FREE else ""))
    print(f"  diaphragm's mass {v['dia_m'] * AREA_M2**2 * 1e3:.3f} g; area {AREA_M2:.4g} m^2")
    print(f"response: rms {np.sqrt(np.mean(r1**2)):.2f} dB, max {np.max(np.abs(r1)):.2f} dB")
    for (fh, d), e in zip(resp, r1, strict=True):
        print(f"  {fh:6.0f} Hz  {d:6.1f}  {e:+5.2f}")
    print(
        f"carbon: preload {fp * 1e3:.3f} mN, n {n:.4f}, knee s / F_p {knee:.4f}, "
        f"R_open {1 / g_open:.1f} ohm; law {law}"
    )
    print(f"intermodulation: rms {np.sqrt(np.mean(r2**2)):.2f} dB")
    for (c, p, d), e in zip(pts, r2, strict=True):
        print(f"  {c:10s} {p:6.2f} bar  {d:5.1f} dB below  {e:+5.2f}")
    e1k = abs(emf_per_pa(v, np.array([1000.0]), fp, n, knee, g_open)[0])
    print(f"EMF at 1 kHz {e1k * 1e3:.1f} mV/Pa ({20 * math.log10(e1k * BAR_PA):.1f} dB re 1 V/bar)")
    if args.plot:
        import matplotlib.pyplot as plt

        out = REPO_ROOT / "reports" / "carbon_transmitter"
        out.mkdir(parents=True, exist_ok=True)
        fg = np.linspace(50, 5500, 400)
        e = 20 * np.log10(np.abs(emf_per_pa(v, fg, fp, n, knee, g_open)) * BAR_PA)
        fig, ax = plt.subplots(1, 2, figsize=(11, 4))
        ax[0].plot(fg, e, label="fit")
        ax[0].plot(resp[:, 0], resp[:, 1], "o", label="Jones Fig. 6, measured")
        ax[0].set(xlabel="Hz", ylabel="dB re 1 V/bar", ylim=(-60, -20))
        ax[0].legend()
        pg = np.geomspace(1, 100, 40)
        ax[1].semilogx(pg, [products_db(v, fp, n, knee, g_open, p) for p in pg], label="model")
        for c, rows in im.items():
            ax[1].semilogx(rows[:, 0], rows[:, 1], "o-", label=f"Jones Fig. 7, {c}")
        ax[1].invert_yaxis()
        ax[1].set(xlabel="bars per tone", ylabel="dB below the fundamental")
        ax[1].legend()
        fig.tight_layout()
        fig.savefig(out / "fit_f1.png", dpi=110)
        print(f"-> {out / 'fit_f1.png'}")
    if args.write:
        vals = {**v, "preload_n": fp}
        write_values(CIRCUIT, vals, r"(\n  {key}: \{{value: )[^,}}]+")
        write_published(law)
        print(f"-> {CIRCUIT.relative_to(REPO_ROOT)}, {PUBLISHED.relative_to(REPO_ROOT)} (F1)")


if __name__ == "__main__":
    main()
