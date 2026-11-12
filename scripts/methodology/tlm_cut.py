"""The cut toy again, measured properly: against the one solve with the same integrator
(trapezoidal), on whole periods, error relative to the node's own response.

Circuit: Vs - R1 - s (C to ground) - R2 - ground; part A = Vs, R1; part B = R2 (+ C).
  lag-hold / lag-extrap : B owns s and C, gets A's current from the end of the last
                          sample; A sees s's voltage from the end of the last sample
                          (held / extrapolated to this sample's end)
  tlm                   : C as a link line, Z0 = T / C
"""

from __future__ import annotations

import numpy as np

FS = 96000.0
T = 1.0 / FS
N = 96000 * 2


def tone(f):
    return np.cos(2 * np.pi * f * np.arange(N + 1) * T)


def amp(y, f):
    k = np.arange(N // 2, N)
    return 2 * np.mean(y[N // 2 : N] * np.exp(-2j * np.pi * f * k * T))


def mono(r1, r2, c, vs):
    g = 1 / r1 + 1 / r2
    v = np.zeros(N)
    x = 0.0
    for k in range(N):
        # C v' = (vs - v)/r1 - v/r2, trapezoidal
        rhs = x * (c / T - g / 2) + (vs[k] + vs[k + 1]) / (2 * r1)
        x = rhs / (c / T + g / 2)
        v[k] = x
    return v


def lag(r1, r2, c, vs, extrapolate):
    v = np.zeros(N)
    x, x1 = 0.0, 0.0  # v at the end of the last sample, and the one before
    ia0 = 0.0  # A's current at the end of the last sample
    for k in range(N):
        seen = 2 * x - x1 if extrapolate else x
        ia1 = (vs[k + 1] - seen) / r1  # A's current at this sample's end, on the seen voltage
        # B: C v' = i_A - v / r2, trapezoidal; i_A as B knows it: last sample's, held
        g = 1 / r2
        xn = (x * (c / T - g / 2) + ia0) / (c / T + g / 2)
        x1, x = x, xn
        ia0 = ia1
        v[k] = xn
        if not np.isfinite(xn) or abs(xn) > 1e9:
            return None
    return v


def tlm(r1, r2, c, vs):
    z0 = T / c
    ia = ib = 0.0
    v = np.zeros(N)
    for k in range(N):
        va = (vs[k + 1] / r1 + 2 * ia / z0) / (1 / r1 + 1 / z0)
        vb = (2 * ib / z0) / (1 / r2 + 1 / z0)
        ia, ib = vb - ib, va - ia
        v[k] = 0.5 * (va + vb)
    return v


def cell(y, ref, f):
    if y is None:
        return " unstable"
    a, b = amp(y, f), amp(ref, f)
    return f"{20 * np.log10(abs(a - b) / abs(b) + 1e-300):8.1f}"


def main():
    freqs = (100.0, 1000.0, 10000.0)
    print("error of the node's response re the one solve (dB) at 100 Hz / 1 kHz / 10 kHz")
    for r1, r2, label in [
        (100.0, 10e3, "the driving side is stiff (R1 100, R2 10k)"),
        (10e3, 100.0, "the loading side is stiff (R1 10k, R2 100)"),
        (10e3, 10e3, "matched (10k, 10k)"),
    ]:
        print(f"\n{label}")
        rp = r1 * r2 / (r1 + r2)
        for tau in [0.3, 1, 3, 10, 100, 1000]:
            c = tau * T / rp
            row = [f"tau {tau:6g} T"]
            for name in ("hold", "extrap", "tlm"):
                cells = []
                for f in freqs:
                    vs = tone(f)
                    ref = mono(r1, r2, c, vs)
                    y = (
                        lag(r1, r2, c, vs, False)
                        if name == "hold"
                        else lag(r1, r2, c, vs, True)
                        if name == "extrap"
                        else tlm(r1, r2, c, vs)
                    )
                    cells.append(cell(y, ref, f))
                row.append(f"{name}:" + "".join(cells))
            print("  " + " | ".join(row))


if __name__ == "__main__":
    main()
