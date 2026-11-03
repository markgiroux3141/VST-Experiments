"""Prototype: the thyratron sawtooth as an ODE (scipy Radau), with the fitted model."""

import sys
import time
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from scipy.integrate import solve_ivp

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
from thy_proto import P0, ie, ig, rate  # noqa: E402

p = dict(P0)
p["g_leak"] = 4.14e-11
if (HERE / "thy_fit.npy").exists() and "--p0" not in sys.argv:
    from thy_fit import FREE, LOG  # noqa: E402

    th = np.load(HERE / "thy_fit.npy")
    for k, v in zip(FREE, th, strict=True):
        p[k] = np.exp(v) if k in LOG else v

B, R, C, RA = 300.0, 330e3, 10e-9, 270.0
ARGS = [a for a in sys.argv[1:] if a != "--p0"]
RG, VBIAS = 47e3, float(ARGS[0]) if ARGS else -2.5
CAK, CGK, CGA = 1.6e-12, 2.4e-12, 0.026e-12


def f(t, s):
    vc, va, vg, w = s
    x = np.exp(w)
    i_a = ie(p, va, vg, 0.0, x)
    i_g = ig(p, va, vg, x)
    dvc = ((B - vc) / R - (vc - va) / RA) / C
    # anode node: from the capacitor through RA, into the tube; Cak to ground; Cga ignored
    dva = ((vc - va) / RA - i_a) / CAK
    dvg = ((VBIAS - vg) / RG - i_g) / CGK
    dw = rate(p, va, vg, 0.0, x) / x
    return [dvc, dva, dvg, dw]


t_end = float(ARGS[1]) if len(ARGS) > 1 else 0.02
t0 = time.time()
sol = solve_ivp(
    f,
    (0, t_end),
    [10.0, 10.0, VBIAS, np.log(1e-10)],
    method="Radau",
    rtol=1e-7,
    atol=[1e-6, 1e-6, 1e-6, 1e-6],
    max_step=2e-5,
)
print("solved", sol.status, sol.message, len(sol.t), "steps in", round(time.time() - t0, 1), "s")
t, vc, va, vg, w = sol.t, *sol.y
ia = np.array([ie(p, a, g, 0.0, np.exp(x)) for a, g, x in zip(va, vg, w, strict=True)])
# resets: where vc falls fast
k = np.where(np.diff(vc) < -1.0)[0]
starts = k[np.concatenate([[True], np.diff(t[k]) > 1e-4])] if len(k) else []
if len(starts) > 2:
    per = np.diff(t[starts])
    print("periods (ms):", np.round(per[-5:] * 1e3, 4), "f =", round(1 / per[-3:].mean(), 2), "Hz")
    print(
        "vc range in last period:",
        vc[starts[-2] : starts[-1]].min(),
        vc[starts[-2] : starts[-1]].max(),
    )
fig, ax = plt.subplots(3, 1, figsize=(9, 8))
ax[0].plot(t * 1e3, vc, label="vc")
ax[0].plot(t * 1e3, va, label="va", lw=0.6)
ax[0].legend()
if len(starts) > 1:
    s0 = starts[-1]
    m = (t > t[s0] - 5e-6) & (t < t[s0] + 60e-6)
    ax[1].plot((t[m] - t[s0]) * 1e6, vc[m], ".-", label="vc")
    ax[1].plot((t[m] - t[s0]) * 1e6, va[m], label="va")
    ax[1].set_xlabel("us")
    ax2 = ax[1].twinx()
    ax2.plot((t[m] - t[s0]) * 1e6, ia[m], "r", label="ia")
    ax[2].plot((t[m] - t[s0]) * 1e6, w[m], label="ln x")
    ax[2].plot((t[m] - t[s0]) * 1e6, vg[m], label="vg")
    ax[2].legend()
fig.savefig(HERE / "thy_osc.png", dpi=80)
