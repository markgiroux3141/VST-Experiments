"""E3 continued (METHODOLOGY_REVIEW.md W1 steps 1-2): link-line cuts on a small general
trapezoidal MNA, the error measured on each part's own copy of the cut.

1. E3's matched case. tlm_cut.py reported the mean of the two copies, (va + vb) / 2. A link
   line of one-way delay T and impedance Z0 = T / C is, driven in phase at both ends (its
   even mode), two open stubs of delay T / 2 and capacitance C / 2: each exactly a
   trapezoidal capacitor (the TLM stub's equivalence). Driven in antiphase (its odd mode) it
   is two shorted stubs: trapezoidal inductors T^2 / (2C), the parasite. With R1 = R2 the
   two sides are mirror images, so the mean is the even mode alone: the one solve of C with
   trapezoidal, to roundoff. Not a bug in the stepping; the metric hid the odd mode. Each
   copy carries it (`va`, `vb` below), and those are what a part's own elements see.
2. The cuts: a capacitor to ground (Z0 = T / C) and a series inductor (Z0 = L / T, its
   parasite a shunt capacitance T^2 / L split between the ends), linear and with a diode;
   then the cuts the amps offer, with their values at draft-1x (48 kHz).

Every case's error is re the one solve with the same integrator (trapezoidal) on whole
periods of the second half of 0.2 s, at 100 Hz / 1 kHz / 10 kHz, in dB re the probe's own
response.

    uv run python scripts/methodology/tlm_cut2.py
"""

from __future__ import annotations

import math

import numpy as np

VT = 0.025852


class Net:
    """A netlist: ("R", a, b, ohm), ("C", a, b, F), ("L", a, b, H), ("V", a, b, f(t)),
    ("D", a, b, Is, n), ("LINE", node, cut): a link line's end at `node`, Z0 = the cut's.
    Node "0" is ground."""

    def __init__(self, elements, z0=None):
        self.el = elements
        self.z0 = z0 or {}
        nodes = []
        for e in elements:
            for n in (e[1], e[2]) if e[0] != "LINE" else (e[1],):
                if n != "0" and n not in nodes:
                    nodes.append(n)
        self.nodes = {n: i for i, n in enumerate(nodes)}
        self.nn = len(nodes)
        self.br = {}
        for k, e in enumerate(self.el):
            if e[0] in ("V", "L"):
                self.br[k] = self.nn + len(self.br)
        self.n = self.nn + len(self.br)

    def idx(self, node):
        return None if node == "0" else self.nodes[node]


class Sim:
    """Trapezoidal steps of a Net at step T; line ends' incident waves set from outside."""

    def __init__(self, net: Net, T: float):
        self.net, self.T = net, T
        self.x = np.zeros(net.n)
        self.ic = {k: 0.0 for k, e in enumerate(net.el) if e[0] == "C"}  # cap currents
        self.inc = {k: 0.0 for k, e in enumerate(net.el) if e[0] == "LINE"}

    def v(self, x, node):
        i = self.net.idx(node)
        return 0.0 if i is None else x[i]

    def step(self, t1):
        net, T, x0 = self.net, self.T, self.x
        x = x0.copy()
        for _ in range(100):
            G = np.zeros((net.n, net.n))
            b = np.zeros(net.n)

            def stamp_g(a, c, g, G=G):
                ia, ic = net.idx(a), net.idx(c)
                if ia is not None:
                    G[ia, ia] += g
                if ic is not None:
                    G[ic, ic] += g
                if ia is not None and ic is not None:
                    G[ia, ic] -= g
                    G[ic, ia] -= g

            def stamp_i(a, c, i, b=b):  # current i from a through the element to c
                ia, ic = net.idx(a), net.idx(c)
                if ia is not None:
                    b[ia] -= i
                if ic is not None:
                    b[ic] += i

            for k, e in enumerate(net.el):
                kind = e[0]
                if kind == "R":
                    stamp_g(e[1], e[2], 1 / e[3])
                elif kind == "C":
                    g = 2 * e[3] / T
                    v0 = self.v(x0, e[1]) - self.v(x0, e[2])
                    stamp_g(e[1], e[2], g)
                    stamp_i(e[1], e[2], -(g * v0 + self.ic[k]))
                elif kind == "LINE":
                    z0 = net.z0[e[2]]
                    stamp_g(e[1], "0", 1 / z0)
                    stamp_i(e[1], "0", -2 * self.inc[k] / z0)
                elif kind in ("V", "L"):
                    j = net.br[k]
                    ia, ic = net.idx(e[1]), net.idx(e[2])
                    for node, s in ((ia, 1.0), (ic, -1.0)):
                        if node is not None:
                            G[node, j] += s
                            G[j, node] += s
                    if kind == "V":
                        b[j] = e[3](t1)
                    else:
                        r = 2 * e[3] / T
                        G[j, j] -= r
                        v0 = self.v(x0, e[1]) - self.v(x0, e[2])
                        b[j] = -(r * x0[j] + v0)
                elif kind == "D":
                    vd = self.v(x, e[1]) - self.v(x, e[2])
                    vd = min(vd, 1.5)
                    nvt = e[4] * VT
                    i = e[3] * math.expm1(vd / nvt)
                    g = e[3] / nvt * math.exp(vd / nvt) + 1e-12
                    stamp_g(e[1], e[2], g)
                    stamp_i(e[1], e[2], i - g * vd)
            xn = np.linalg.solve(G, b)
            if np.max(np.abs(xn - x)) < 1e-12 * (1 + np.max(np.abs(xn))):
                x = xn
                break
            x = xn
        for k, e in enumerate(net.el):
            if e[0] == "C":
                g = 2 * e[3] / T
                v0 = self.v(x0, e[1]) - self.v(x0, e[2])
                v1 = self.v(x, e[1]) - self.v(x, e[2])
                self.ic[k] = g * (v1 - v0) - self.ic[k]
        self.x = x


def run(elements, probes, T, n, cuts=()):
    """The one solve of `elements` (no cuts), or with `cuts`: (element index, side-B node
    renames {node: copy}, elements on side B) -> the line ends exchanged once a step."""
    if not cuts:
        sim = Sim(Net(elements), T)
        out = np.zeros((n, len(probes)))
        for k in range(n):
            sim.step((k + 1) * T)
            out[k] = [sim.v(sim.x, p) for p in probes]
        return out
    els = list(elements)
    z0 = {}
    ends = []
    for ci, (k, rename, side_b) in enumerate(cuts):
        e = elements[k]
        if e[0] == "C":
            z0[ci] = T / e[3]
            a = e[1]
            b = rename[a]
        elif e[0] == "L":
            z0[ci] = e[3] / T
            a, b = e[1], e[2]
        else:
            raise ValueError("cut a C to ground or an L")
        for j in side_b:
            f = els[j]
            if f[0] in ("R", "C", "L", "V", "D"):
                els[j] = (f[0], rename.get(f[1], f[1]), rename.get(f[2], f[2]), *f[3:])
        ends.append((len(els), len(els) + 1))
        els += [("LINE", a, ci), ("LINE", b, ci)]
    removed = {k for k, _, _ in cuts}
    keep = [e for i, e in enumerate(els) if i not in removed]
    shift = {i: i - sum(1 for r in removed if r < i) for i in range(len(els))}
    sim = Sim(Net(keep, z0), T)
    ends = [(shift[a], shift[b]) for a, b in ends]
    out = np.zeros((n, 2 * len(probes)))
    renames = {}
    for _, rename, _ in cuts:
        renames.update(rename)
    for k in range(n):
        sim.step((k + 1) * T)
        refl = {}
        for a, b in ends:
            for me in (a, b):
                node = keep[me][1]
                refl[me] = sim.v(sim.x, node) - sim.inc[me]
        for a, b in ends:
            sim.inc[a], sim.inc[b] = refl[b], refl[a]
        if not np.all(np.isfinite(sim.x)) or np.max(np.abs(sim.x)) > 1e9:
            return None
        row = []
        for p in probes:
            row.append(sim.v(sim.x, p))
            row.append(sim.v(sim.x, renames.get(p, p)))
        out[k] = row
    return out


def amp(y, f, T):
    n = len(y)
    k = np.arange(n // 2, n)
    return 2 * np.mean(y[n // 2 :] * np.exp(-2j * np.pi * f * (k + 1) * T))


def err_db(y, ref, f, T):
    a, b = amp(y, f, T), amp(ref, f, T)
    return 20 * np.log10(abs(a - b) / abs(b) + 1e-300)


def cells(case, probes, T, n, freqs, scale=1.0):
    """For each probe: the one solve vs the cut's copies (A's, B's); returns rows of dB."""
    rows = []
    for f in freqs:

        def vs(t, f=f):
            return scale * math.sin(2 * math.pi * f * t)

        els, cuts = case(vs)
        ref = run(els, probes, T, n)
        y = run(els, probes, T, n, cuts)
        if y is None:
            rows.append(None)
            continue
        r = []
        for j in range(len(probes)):
            r.append(
                (err_db(y[:, 2 * j], ref[:, j], f, T), err_db(y[:, 2 * j + 1], ref[:, j], f, T))
            )
        rows.append(r)
    return rows


def show(label, rows, probes):
    if any(r is None for r in rows):
        print(f"  {label:44s} unstable")
        return
    for j, p in enumerate(probes):
        a = " / ".join(f"{r[j][0]:6.1f}" for r in rows)
        b = " / ".join(f"{r[j][1]:6.1f}" for r in rows)
        print(f"  {label:44s} {p}: A's copy {a} | B's copy {b}")


def main():
    freqs = (100.0, 1000.0, 10000.0)
    T = 1 / 96000
    n = 19200  # 0.2 s: the second half is whole periods at 100 Hz
    print("error re the one solve (dB) at 100 Hz / 1 kHz / 10 kHz, on each part's copy\n")
    print("1. shunt C cut (Vs - R1 - s, C to ground, R2 to ground; B holds R2)")
    for r1, r2, what in [
        (100.0, 10e3, "driving stiff"),
        (10e3, 100.0, "loading stiff"),
        (10e3, 10e3, "matched"),
    ]:
        rp = r1 * r2 / (r1 + r2)
        for tau in (1, 10, 1000):
            c = tau * T / rp

            def case(vs, r1=r1, r2=r2, c=c):
                els = [
                    ("V", "in", "0", vs),
                    ("R", "in", "s", r1),
                    ("C", "s", "0", c),
                    ("R", "s", "0", r2),
                ]
                return els, [(2, {"s": "s'"}, [3])]

            show(f"{what}, tau {tau} T", cells(case, ["s"], T, n, freqs), ["s"])
    print("\n2. series L cut (Vs - R1 - a - L - b - R2 - ground)")
    for r1, r2, what in [
        (100.0, 10e3, "source stiff"),
        (10e3, 100.0, "load stiff"),
        (1e3, 1e3, "matched"),
    ]:
        for tau in (1, 10, 1000):
            ll = tau * T * (r1 + r2)

            def case(vs, r1=r1, r2=r2, ll=ll):
                els = [
                    ("V", "in", "0", vs),
                    ("R", "in", "a", r1),
                    ("L", "a", "b", ll),
                    ("R", "b", "0", r2),
                ]
                return els, [(2, {}, [3])]

            show(f"{what}, L/(R1+R2) {tau} T", cells(case, ["b"], T, n, freqs), ["b"])
    print("\n3. with a diode: 10 V into the shunt-C cut, B a diode and 1k to ground (tau 10 T)")
    for tau in (0.3, 1, 10):
        c = tau * T / 500

        def case(vs, c=c):
            els = [
                ("V", "in", "0", vs),
                ("R", "in", "s", 1e3),
                ("C", "s", "0", c),
                ("R", "s", "0", 1e3),
                ("D", "s", "0", 1e-14, 1.0),
            ]
            return els, [(2, {"s": "s'"}, [3, 4])]

        show(f"shunt C, diode on B, tau {tau} T", cells(case, ["s"], T, n, freqs, 10.0), ["s"])
    for tau in (0.3, 1, 10):
        ll = tau * T * 2e3

        def case(vs, ll=ll):
            els = [
                ("V", "in", "0", vs),
                ("R", "in", "a", 1e3),
                ("L", "a", "b", ll),
                ("R", "b", "0", 1e3),
                ("D", "b", "0", 1e-14, 1.0),
            ]
            return els, [(2, {}, [3, 4])]

        show(f"series L, diode on B, L/R {tau} T", cells(case, ["b"], T, n, freqs, 10.0), ["b"])

    T48, n48 = 1 / 48000, 9600
    print("\n4. the amps' cuts at draft-1x (48 kHz), the AC30's values")

    # The OT primary, plate to plate: the EL84 pairs' plate resistance (~2 x 19k), both
    # halves' leakage, the 4k reflected load across the magnetizing inductance (~20 H).
    def ot_primary(vs):
        els = [
            ("V", "in", "0", vs),
            ("R", "in", "a", 38e3),
            ("L", "a", "b", 2 * 0.6425e-3),
            ("R", "b", "0", 4e3),
            ("L", "b", "0", 20.0),
        ]
        return els, [(2, {}, [3, 4])]

    show("OT primary leakage (1.3 mH)", cells(ot_primary, ["b"], T48, n48, freqs), ["b"])

    # The secondary: the plates reflected (38k / 266 = 143 ohm) plus the winding's 0.72,
    # its leakage, a 15 ohm load.
    def ot_secondary(vs):
        els = [
            ("V", "in", "0", vs),
            ("R", "in", "a", 143.7),
            ("L", "a", "b", 9.64e-6),
            ("R", "b", "0", 15.0),
        ]
        return els, [(2, {}, [3])]

    show("OT secondary leakage (9.6 uH)", cells(ot_secondary, ["b"], T48, n48, freqs), ["b"])

    # The speaker's moving mass (CSPK_m, 13.9 uF at spk_m): the secondary's source, Re, Le,
    # L2 || R2, then the mass, the suspension and its losses (no break-up modes).
    def mass(vs):
        els = [
            ("V", "in", "0", vs),
            ("R", "in", "spk", 143.7),
            ("R", "spk", "l", 11.8),
            ("L", "l", "e", 0.693e-3),
            ("L", "e", "m", 1.444e-3),
            ("R", "e", "m", 12.3),
            ("C", "m", "0", 13.88e-6),
            ("L", "m", "0", 46.4e-3),
            ("R", "m", "0", 272.8),
        ]
        return els, [(6, {"m": "m'"}, [7, 8])]

    show(
        "speaker mass (13.9 uF at spk_m)", cells(mass, ["spk", "m"], T48, n48, freqs), ["spk", "m"]
    )


if __name__ == "__main__":
    main()
