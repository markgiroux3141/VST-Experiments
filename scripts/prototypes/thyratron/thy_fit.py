"""Prototype fit of the lumped 2D21 to the sheets."""

import sys
import time

import numpy as np
from scipy.optimize import brentq, least_squares

sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
from thy_proto import P0, arc, ie, ig, kg, rate, stable_x, vg_crit  # noqa: E402

REPO = __import__("pathlib").Path(__file__).resolve().parents[3]
D = REPO / "data/datasheets"
ctl = np.loadtxt(D / "sylvania_2d21_control.csv", delimiter=",", skiprows=1)
bef = np.loadtxt(D / "sylvania_2d21_grid_before.csv", delimiter=",", skiprows=1)
dur = np.loadtxt(D / "sylvania_2d21_grid_during.csv", delimiter=",", skiprows=1)


def at(c, key, xcol, ycol, x):
    s = c[c[:, 0] == key]
    s = s[np.argsort(s[:, xcol])]
    return np.interp(x, s[:, xcol], s[:, ycol])


# Control targets: (va, vs, vg1)
CT = []
for vs, vas in (
    (0.0, (650, 500, 400, 300, 200, 150, 100, 70, 55)),
    (2.0, (650, 400, 200, 100, 50)),
    (8.0, (650, 400, 200, 100, 50)),
):
    for va in vas:
        CT.append((va, vs, at(ctl, vs, 1, 2, va)))
CT = np.array(CT)

# Leakage: the flat levels of the before-conduction curves (-15..-10 V).
flat = np.array(
    [
        [va, bef[(bef[:, 0] == va) & (bef[:, 1] < -10) & (bef[:, 1] > -15), 2].mean()]
        for va in (25, 200, 400, 600)
    ]
)
g_leak, i_off = np.polyfit(flat[:, 0], -flat[:, 1], 1)
print(f"leakage {g_leak:.3e} S, offset {i_off * 1e9:.2f} nA")

# Knee targets: the ion part (curve minus its flat level) where it is 2-30x the leakage's
# noise, at (va, vg).
KT = []
for va in (200.0, 400.0, 600.0):
    s = bef[bef[:, 0] == va]
    s = s[np.argsort(s[:, 1])]
    base = s[(s[:, 1] < -10) & (s[:, 1] > -15), 2].mean()
    ion = s[:, 2] - base
    for lvl in (-2e-9, -4e-9, -8e-9, -15e-9):
        k = np.where(ion < lvl)[0]
        if len(k):
            KT.append((va, s[k[0], 1], lvl))
KT = np.array(KT)

# During: Ig / Ia at (ia, vg)
DT = []
for ia in (0.025, 0.05, 0.1, 0.15, 0.2):
    for vg in (-7.0, -5.0, -3.0, -2.0, -1.5):
        DT.append((ia, vg, at(dur, ia, 1, 2, vg)))
DT = np.array(DT)

FREE = ["mu_a", "mu_s", "v0", "e_v", "c_m", "x_n", "q_s", "k_g0", "p_g", "tau_d", "a", "v_x", "g_s"]
LOG = {"c_m", "x_n", "q_s", "k_g0", "tau_d", "a", "g_s", "v_x"}


def unpack(th):
    p = dict(P0)
    p["g_leak"] = g_leak
    for k, v in zip(FREE, th, strict=True):
        p[k] = np.exp(v) if k in LOG else v
    return p


def deion(p, vg, va=125.0, ia=0.1):
    va_arc, x_arc = arc(p, ia, vg)
    # the separatrix at 125 V: the unstable root above the stable one
    xs = np.geomspace(1e-14, 1e4, 6000)
    r = rate(p, va, vg, 0.0, xs)
    neg = np.where(r < 0)[0]
    if len(neg) == 0:
        return np.nan
    k = neg[-1]
    if k + 1 >= len(xs):
        return 0.0
    xu = brentq(lambda x: rate(p, va, vg, 0.0, x), xs[k], xs[k + 1])
    tau = 1.0 / (1.0 / p["tau_d"] + kg(p, vg))
    return tau * np.log(x_arc / xu) if x_arc > xu else 0.0


def ion_time(p, vsup=100.0, ipk=0.5, vbias=-10.0, pulse=50.0, drop=8.0):
    """RCA's ionization-time test: vsup through a load for ipk at the drop, the grid
    stepped by `pulse` from `vbias` (assumed); the time until the anode has made 90% of
    its fall to the drop."""

    rl = (vsup - drop) / ipk
    vg = vbias + pulse

    def va_of(x):
        return brentq(lambda v: v - vsup + rl * ie(p, v, vg, 0.0, x), -100.0, vsup + 1.0)

    x0 = stable_x(p, vsup, vbias, 0.0)
    if x0 is None:
        return np.nan
    target = drop + 0.1 * (vsup - drop)
    # 1-D: Va is algebraic in x, so t = integral of dw / (dw/dt) up to Va = target.
    g = lambda w: va_of(np.exp(w)) - target  # noqa: E731
    w0 = np.log(x0)
    if g(30.0) > 0:
        return np.nan
    w1 = brentq(g, w0, 30.0)
    ws = np.linspace(w0, w1, 3000)
    r = np.array([rate(p, va_of(np.exp(w)), vg, 0.0, np.exp(w)) / np.exp(w) for w in ws])
    if np.any(r <= 0):
        return np.nan
    return np.trapezoid(1.0 / r, ws)


def resid(th, verbose=False):
    try:
        return _resid(th, verbose)
    except Exception as e:  # noqa: BLE001
        print("resid failed:", e)
        return np.full(len(CT) + len(KT) + len(DT) + 4, 100.0)


def _resid(th, verbose=False):
    p = unpack(th)
    r = []
    for va, vs, vg in CT:
        r.append((vg_crit(p, va, vs) - vg) / 0.1)
    for va, vg, lvl in KT:
        x = stable_x(p, va, vg, 0.0)
        ion = ig(p, va, vg, x) - p["g_leak"] * (vg - va) if x is not None else 1.0
        r.append(np.log(max(-ion, 1e-15) / -lvl) / 0.3)
    for ia, vg, igm in DT:
        va, x = arc(p, ia, vg)
        r.append((ig(p, va, vg, x) / ia - igm / ia) / 0.002)
    va, _ = arc(p, 0.1, -10.0)
    r.append((va - 8.0) / 0.3)
    r.append(np.log(max(ion_time(p), 1e-12) / 0.5e-6) / 0.1)
    r.append(np.log(max(deion(p, -10.0), 1e-7) / 75e-6) / 0.05)
    r.append(np.log(max(deion(p, -100.0), 1e-7) / 35e-6) / 0.05)
    r = np.nan_to_num(np.array(r, float), nan=100.0, posinf=100.0, neginf=-100.0)
    if verbose:
        n1, n2, n3 = len(CT), len(KT), len(DT)
        print("control rms (V)", np.sqrt(np.mean((r[:n1] * 0.1) ** 2)))
        print("knee rms (ln)", np.sqrt(np.mean((r[n1 : n1 + n2] * 0.3) ** 2)))
        print("during rms (Ig/Ia)", np.sqrt(np.mean((r[n1 + n2 : n1 + n2 + n3] * 0.002) ** 2)))
        print("drop, ion time, deion", r[-4:])
    return r


if __name__ == "__main__":
    th0 = np.array([np.log(P0[k]) if k in LOG else P0[k] for k in FREE])
    t = time.time()
    r0 = resid(th0, True)
    print("eval", time.time() - t, "s; cost", 0.5 * np.sum(r0**2))
    sol = least_squares(
        resid,
        th0,
        diff_step=1e-3,
        max_nfev=int(sys.argv[1]) if len(sys.argv) > 1 else 60,
        verbose=2,
    )
    p = unpack(sol.x)
    resid(sol.x, True)
    for k in FREE:
        print(f"  {k} = {p[k]:.6g}")
    np.save(__import__("pathlib").Path(__file__).parent / "thy_fit.npy", sol.x)
