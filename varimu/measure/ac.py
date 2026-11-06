"""Small-signal AC analysis of a linear circuit IR (MIC_ROOM_PLAN.md, A2's reference).

    h = transfer(ir, f_hz, "out")          # complex V(out) / V(input), per frequency
    h = transfer(ir, f_hz, "out", drives={"p_rear": d})   # control inputs driven too
    psd = noise_psd(ir, f_hz, "out")       # V^2/Hz at out from the IR's NoiseCurrents

Nodal analysis with the input node driven by an ideal source (1 V); a control input's
node is driven by an ideal source too (0 V unless `drives` gives it a complex amplitude
per frequency); DC sources (V, sine and mains sources) are AC shorts. Elements: Resistor,
Capacitor, Inductor (its current an unknown, so a 0 H inductor is a short), Coupling
(the mutual inductance k sqrt(La Lb) between two inductors' branches: a transformer's
coupled series leakages, `leak_couplings`), Vccs,
NoiseCurrent (noise only), Winding (its current an unknown: V(a) - V(b) = s N A
TESLA_PER_V V(core), N i into the core node; a transformer in a build with
`cores="linear"`, its core a resistor). A device or medium element is an error: this is
for the linear networks (capsules, the speaker's readout, a transformer's linear limit)
whose renders it checks, independently of circuitsim's transient.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np

from varimu.circuit.ir import (
    GROUND,
    Capacitor,
    CircuitIR,
    Coupling,
    Inductor,
    NoiseCurrent,
    Resistor,
    SineSource,
    Vccs,
    VoltageSource,
    Winding,
)
from varimu.devices.core import TESLA_PER_V


class Unsupported(ValueError):
    pass


def _system(ir: CircuitIR):
    nodes: list[str] = []
    index: dict[str, int] = {}

    def node(n: str) -> int:
        if n == GROUND:
            return -1
        if n not in index:
            index[n] = len(nodes)
            nodes.append(n)
        return index[n]

    els = list(ir.elements())
    branches = []  # (kind, a, b, value): Inductors and voltage sources get a current unknown
    stamps = []
    couplings = [e for e in els if isinstance(e, Coupling)]
    for e in els:
        if isinstance(e, Coupling):
            continue
        if isinstance(e, Resistor):
            stamps.append(("g", node(e.a), node(e.b), 1.0 / e.r_ohm))
        elif isinstance(e, Capacitor):
            stamps.append(("c", node(e.a), node(e.b), e.c_f))
        elif isinstance(e, Inductor):
            branches.append(("l", node(e.a), node(e.b), e.l_h))
        elif isinstance(e, VoltageSource | SineSource):
            branches.append(("v", node(e.pos), node(e.neg), 0.0))
        elif isinstance(e, Vccs):
            stamps.append(
                ("gm", node(e.pos), node(e.neg), (node(e.ctrl_pos), node(e.ctrl_neg), e.gm_s))
            )
        elif isinstance(e, NoiseCurrent):
            node(e.a), node(e.b)
        elif isinstance(e, Winding):
            k = e.turns * e.area_m2 * TESLA_PER_V
            branches.append(("w", node(e.a), node(e.b), (node(e.core), k, e.turns)))
        else:
            raise Unsupported(f"{type(e).__name__} {getattr(e, 'name', '')}: not linear")
    l_index = {e.name: k for k, e in enumerate(x for x in els if isinstance(x, Inductor))}
    l_rows = [k for k, b in enumerate(branches) if b[0] == "l"]
    l_value = {e.name: e.l_h for e in els if isinstance(e, Inductor)}
    for c in couplings:
        if c.l_a not in l_index or c.l_b not in l_index:
            raise Unsupported(f"Coupling {c.name}: {c.l_a} or {c.l_b} isn't an inductor")
        mutual = c.k * (l_value[c.l_a] * l_value[c.l_b]) ** 0.5
        stamps.append(("m", l_rows[l_index[c.l_a]], l_rows[l_index[c.l_b]], mutual))
    for ctl in ir.controls:
        branches.append(("ctl:" + ctl.node, node(ctl.node), -1, 0.0))
    inp = node(ir.input_node)
    branches.append(("in", inp, -1, 0.0))
    return nodes, index, stamps, branches, els


def _solve(ir: CircuitIR, f_hz: Sequence[float], rhs_fn) -> tuple[list[str], np.ndarray]:
    nodes, index, stamps, branches, els = _system(ir)
    n, m = len(nodes), len(branches)
    out = []
    for f in np.atleast_1d(np.asarray(f_hz, float)):
        s = 2j * np.pi * f
        a = np.zeros((n + m, n + m), complex)

        def add(i, j, y, a=a):
            if i >= 0 and j >= 0:
                a[i, j] += y

        for kind, p, q, v in stamps:
            if kind in ("g", "c"):
                y = v if kind == "g" else s * v
                add(p, p, y), add(q, q, y), add(p, q, -y), add(q, p, -y)
            elif kind == "m":  # branches p and q (indices): - s M i on each other's row
                a[n + p, n + q] -= s * v
                a[n + q, n + p] -= s * v
            else:  # current gm (V(cp) - V(cn)) from p to q through the source
                cp, cn, gm = v
                add(q, cp, -gm), add(q, cn, gm), add(p, cp, gm), add(p, cn, -gm)
        for k, (kind, p, q, v) in enumerate(branches):
            r = n + k
            add(p, r, 1.0), add(q, r, -1.0)  # the branch current leaves p, enters q
            add(r, p, 1.0), add(r, q, -1.0)
            if kind == "l":
                a[r, r] -= s * v  # V(p) - V(q) - s L i = 0
            elif kind == "w":
                core, k_v, turns = v
                add(r, core, -s * k_v)  # V(p) - V(q) - s N A k V(core) = 0
                add(core, r, -turns)  # N i flows into the core node
        out.append(np.linalg.solve(a, rhs_fn(n, m, index, els, branches, f)))
    return nodes, np.array(out)


def transfer(
    ir: CircuitIR, f_hz: Sequence[float], node: str, drives: dict | None = None
) -> np.ndarray:
    """Complex V(node) per volt at the IR's input node; `drives` {control node: complex
    amplitude (a scalar, or one per frequency)} drives control inputs as well."""
    freqs = list(np.atleast_1d(np.asarray(f_hz, float)))
    drives = dict(drives or {})

    def rhs(n, m, index, els, branches, f):
        b = np.zeros(n + m, complex)
        b[n + m - 1] = 1.0  # the input's branch equation: V(in) = 1
        for k, (kind, *_rest) in enumerate(branches):
            if kind.startswith("ctl:") and kind[4:] in drives:
                d = np.broadcast_to(np.asarray(drives[kind[4:]], complex), (len(freqs),))
                b[n + k] = d[freqs.index(f)]
        return b

    nodes, x = _solve(ir, f_hz, rhs)
    return x[:, nodes.index(node)]


def noise_psd(ir: CircuitIR, f_hz: Sequence[float], node: str) -> np.ndarray:
    """V^2/Hz at `node` from every NoiseCurrent of the IR (uncorrelated; the input
    shorted)."""
    total = np.zeros(len(np.atleast_1d(f_hz)))
    noises = [e for e in ir.elements() if isinstance(e, NoiseCurrent)]
    for e in noises:

        def rhs(n, m, index, els, branches, f, e=e):
            b = np.zeros(n + m, complex)
            if e.a != GROUND:
                b[index[e.a]] -= 1.0  # a unit current from a to b
            if e.b != GROUND:
                b[index[e.b]] += 1.0
            return b

        nodes, x = _solve(ir, f_hz, rhs)
        total += e.psd_a2_hz * np.abs(x[:, nodes.index(node)]) ** 2
    return total
