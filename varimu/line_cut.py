"""Link-line cuts of a partitioned run: the Python reference (METHODOLOGY_REVIEW.md W1).

circuitsim's partition.rs can cut an element as a link line (a partition list's
`cut:ELEMENT` entry, `partition::LineCut`): a lossless line of one sample's delay in its
place between two parts. Each part sees a resistor Z0 into a source of twice the wave that
arrives at its end, and sends back the wave that leaves (its end's voltage less the arriving
wave). A capacitor to ground C at a node two parts have: Z0 = h / C, the node split into the
parts' copies. A series inductor L between nodes of two parts: Z0 = L / h. Over sample n ->
n + 1 a part's source goes from twice the other end's wave at n - 1 to twice it at n.

This module runs the same thing on small circuits, to check circuitsim against: a dense
trapezoidal MNA (Newton for the junction diodes) of an IR's resistors, capacitors, inductors,
voltage sources and junction diodes, the input a source at the input node, from the DC
operating point. Cut parts are solved together (their equations don't couple within a step:
the waves are known from the previous one), so the result is the partitioned run's, not an
approximation of it. Parts may meet only through their link lines here (circuitsim's
held / extrapolated shared nodes aren't modelled). Outside varimu/sim (the render cache key):
nothing renders through it.

    run(ir, x, dt, partition=("cut:C1", "B side")) -> {probe name: array}
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from varimu.circuit.ir import (
    Capacitor,
    CircuitIR,
    Device,
    Inductor,
    Resistor,
    VoltageSource,
)
from varimu.devices.diode import VT_TNOM, JunctionDiode

GROUND = "0"
GROUP_BREAK = "|"
CUT_PREFIX = "cut:"


@dataclass(frozen=True)
class End:
    """A link line's end: its node (in the reference's names) and its cut."""

    node: str
    cut: str


def groups(partition) -> list[list[str]]:
    """The partition list's groups of titles (circuitsim's `partition::groups`)."""
    out: list[list[str]] = [[]]
    for t in partition:
        if t == GROUP_BREAK:
            out.append([])
        elif not t.startswith(CUT_PREFIX):
            out[-1].append(t)
    return [g for g in out if g]


def cuts(partition) -> list[str]:
    """The elements the list cuts (its `cut:` entries), in order."""
    return [t[len(CUT_PREFIX) :] for t in partition if t.startswith(CUT_PREFIX)]


def _nodes(e) -> list[str]:
    if isinstance(e, Resistor | Capacitor | Inductor):
        return [e.a, e.b]
    if isinstance(e, VoltageSource):
        return [e.pos, e.neg]
    if isinstance(e, Device):
        return list(e.nodes)
    raise ValueError(f"line_cut reference: {type(e).__name__} {e.name} isn't modelled")


def _split(ir: CircuitIR, partition, dt: float):
    """The elements renamed per part and the link lines' ends: (elements, ends, z0 per cut,
    renames {(part, node): name})."""
    gs = groups(partition)
    part_of = {}
    for g, titles in enumerate(gs):
        for t in titles:
            part_of[t] = g + 1
    names = cuts(partition)
    elements = []  # (part, element)
    for sec in ir.sections:
        p = part_of.get(sec.title, 0)
        elements += [(p, e) for e in sec.elements]
    cut_els = {e.name: (p, e) for p, e in elements if e.name in names}
    if set(names) - set(cut_els):
        raise ValueError(f"no element(s) {sorted(set(names) - set(cut_els))} to cut")
    kept = [(p, e) for p, e in elements if e.name not in names]
    node_parts: dict[str, set[int]] = {}
    for p, e in kept:
        for n in _nodes(e):
            if n != GROUND:
                node_parts.setdefault(n, set()).add(p)
    if ir.input_node != GROUND:
        node_parts.setdefault(ir.input_node, set()).add(0)
    rename: dict[tuple[int, str], str] = {}
    ends: list[tuple[End, End]] = []
    z0: dict[str, float] = {}
    shunt_nodes = set()
    for c in names:
        _, e = cut_els[c]
        if isinstance(e, Capacitor) and GROUND in (e.a, e.b):
            n = e.b if e.a == GROUND else e.a
            ps = sorted(node_parts.get(n, ()))
            if len(ps) != 2:
                raise ValueError(f"cut {c}'s node {n} must be in exactly two parts ({ps})")
            z0[c] = dt / e.c_f
            rename[(ps[1], n)] = f"{n}@{ps[1]}"
            shunt_nodes.add(n)
            ends.append((End(n, c), End(f"{n}@{ps[1]}", c)))
        elif isinstance(e, Inductor):
            pa, pb = node_parts.get(e.a, set()), node_parts.get(e.b, set())
            if len(pa) != 1 or len(pb) != 1 or pa == pb:
                raise ValueError(f"cut {c}'s nodes must be one part's each, two parts")
            z0[c] = e.l_h / dt
            ends.append((End(e.a, c), End(e.b, c)))
        else:
            raise ValueError(f"cut {c}: a capacitor to ground or an inductor")
    for n, ps in node_parts.items():
        if len(ps) > 1 and n not in shunt_nodes:
            raise ValueError(f"node {n} is shared by parts {sorted(ps)} other than by a line")

    def renamed(p, e):
        def r(n):
            return rename.get((p, n), n)

        if isinstance(e, Resistor):
            return Resistor(e.name, r(e.a), r(e.b), e.r_ohm)
        if isinstance(e, Capacitor):
            return Capacitor(e.name, r(e.a), r(e.b), e.c_f, e.v0_v)
        if isinstance(e, Inductor):
            return Inductor(e.name, r(e.a), r(e.b), e.l_h)
        if isinstance(e, VoltageSource):
            return VoltageSource(e.name, r(e.pos), r(e.neg), e.dc_v)
        if isinstance(e, Device):
            return Device(e.name, e.model, tuple(r(n) for n in e.nodes))
        raise AssertionError

    return [renamed(p, e) for p, e in kept], ends, z0, rename, cut_els


class _Mna:
    """Unknowns: the nodes, then a branch current per voltage source and inductor (and the
    input source last)."""

    def __init__(self, elements, input_node, line_nodes):
        nodes: list[str] = []
        for e in elements:
            for n in _nodes(e):
                if n != GROUND and n not in nodes:
                    nodes.append(n)
        for n in [input_node, *line_nodes]:
            if n != GROUND and n not in nodes:
                nodes.append(n)
        self.node = {n: i for i, n in enumerate(nodes)}
        self.branch = {}
        k = len(nodes)
        for e in elements:
            if isinstance(e, VoltageSource | Inductor):
                self.branch[e.name] = k
                k += 1
        self.branch["<input>"] = k
        self.n = k + 1

    def i(self, n):
        return None if n == GROUND else self.node[n]


def run(
    ir: CircuitIR,
    x: np.ndarray,
    dt: float,
    partition=(),
    *,
    gmin: float = 1e-12,
    tol_v: float = 1e-12,
    max_iter: int = 100,
) -> dict[str, np.ndarray]:
    """The probes of `ir` driven by `x` (volts at the input node per sample, step `dt`),
    trapezoidal from the DC operating point at `x[0]`, the elements `partition` cuts
    (`cut:NAME`, its groups of titles the parts) as link lines; sample 0 is the DC point.
    A probe on a cut capacitor's node reads the higher part's copy (as circuitsim does)."""
    elements, ends, z0, rename, cut_els = _split(ir, partition, dt)
    models = {m.name: m for m in ir.models}
    for e in elements:
        if isinstance(e, Device) and not isinstance(models[e.model], JunctionDiode):
            raise ValueError(f"{e.name}: only junction diodes are modelled")
    end_nodes = [x.node for pair in ends for x in pair]
    mna = _Mna(elements, ir.input_node, end_nodes)
    nn = len(mna.node)

    def stamp(G, b, xv, u, h, xprev, hist, inc, dc):
        """Assemble the Newton system at state guess xv. dc: capacitors open, inductors
        shorted, line ends at their sources (inc: the arriving waves)."""

        def g(a, c, val):
            ia, ic = mna.i(a), mna.i(c)
            if ia is not None:
                G[ia, ia] += val
            if ic is not None:
                G[ic, ic] += val
            if ia is not None and ic is not None:
                G[ia, ic] -= val
                G[ic, ia] -= val

        def cur(a, c, val):  # current val from a through the element to c
            ia, ic = mna.i(a), mna.i(c)
            if ia is not None:
                b[ia] -= val
            if ic is not None:
                b[ic] += val

        def v(n, xx):
            i = mna.i(n)
            return 0.0 if i is None else xx[i]

        for i in range(nn):
            G[i, i] += gmin
        for e in elements:
            if isinstance(e, Resistor):
                g(e.a, e.b, 1.0 / e.r_ohm)
            elif isinstance(e, Capacitor):
                if not dc:
                    gc = 2 * e.c_f / h
                    v0 = v(e.a, xprev) - v(e.b, xprev)
                    g(e.a, e.b, gc)
                    cur(e.a, e.b, -(gc * v0 + hist[e.name]))
            elif isinstance(e, VoltageSource | Inductor):
                j = mna.branch[e.name]
                a, c = (e.pos, e.neg) if isinstance(e, VoltageSource) else (e.a, e.b)
                for n, s in ((mna.i(a), 1.0), (mna.i(c), -1.0)):
                    if n is not None:
                        G[n, j] += s
                        G[j, n] += s
                if isinstance(e, VoltageSource):
                    b[j] = e.dc_v
                elif not dc:
                    r = 2 * e.l_h / h
                    G[j, j] -= r
                    v0 = v(e.a, xprev) - v(e.b, xprev)
                    b[j] = -(r * xprev[j] + v0)
            elif isinstance(e, Device):
                m = models[e.model]
                vd = v(e.nodes[0], xv) - v(e.nodes[1], xv)
                nvt = m.n * VT_TNOM
                if m.rs_ohm:
                    raise ValueError(f"{e.name}: series resistance isn't modelled here")
                vd = min(vd, 40 * nvt + np.log(1e3 / m.is_a) * nvt)
                ex = np.exp(vd / nvt)
                i_d = m.is_a * (ex - 1.0)
                gd = m.is_a / nvt * ex
                g(e.nodes[0], e.nodes[1], gd)
                cur(e.nodes[0], e.nodes[1], i_d - gd * vd)
        jin = mna.branch["<input>"]
        ii = mna.i(ir.input_node)
        if ii is not None:
            G[ii, jin] += 1.0
            G[jin, ii] += 1.0
        b[jin] = u
        for pair, k in zip(ends, range(len(ends)), strict=True):
            for side, end in enumerate(pair):
                zz = z0[end.cut]
                g(end.node, GROUND, 1.0 / zz)
                cur(end.node, GROUND, -2.0 * inc[k][side] / zz)

    def newton(xv, u, h, xprev, hist, inc, dc):
        for _ in range(max_iter):
            G = np.zeros((mna.n, mna.n))
            b = np.zeros(mna.n)
            stamp(G, b, xv, u, h, xprev, hist, inc, dc)
            xn = np.linalg.solve(G, b)
            done = np.max(np.abs(xn[:nn] - xv[:nn])) < tol_v * (1 + np.max(np.abs(xn[:nn])))
            xv = xn
            if done:
                return xv
        raise RuntimeError("line_cut reference: Newton didn't converge")

    def vnode(xx, n):
        i = mna.i(n)
        return 0.0 if i is None else xx[i]

    # The DC point: the whole circuit's (uncut), then each line's waves from it.
    whole = run_dc_whole(ir, x[0], gmin, tol_v, max_iter) if ends else None
    inc = []
    for pair in ends:
        c = pair[0].cut
        _, el = cut_els[c]
        vdc = whole["v"][pair[0].node] if pair[0].node in whole["v"] else 0.0
        if isinstance(el, Inductor):
            idc = whole["i"][el.name]
        else:
            # The current through the node from A's copy into B's elements (the line
            # carries it at DC).
            idc = _into(
                whole, [e for e in elements if pair[1].node in _nodes(e)], pair[1].node, models
            )
        d = idc * z0[c]
        w0, w1 = (vdc + d) / 2, (vdc - d) / 2
        inc.append([w1, w0])  # each end's arriving wave: the other's leaving
    xv = newton(np.zeros(mna.n), x[0], dt, np.zeros(mna.n), {}, inc, True)
    hist = {e.name: 0.0 for e in elements if isinstance(e, Capacitor)}
    probes = [p.node for p in ir.probes]

    def probe_values(xx):
        out = []
        for n in probes:
            ps = [k for (pp, nn_), k in rename.items() if nn_ == n]
            out.append(vnode(xx, ps[0] if ps else n))
        return out

    ys = [probe_values(xv)]
    refl_prev = [
        [vnode(xv, end.node) - inc[k][s] for s, end in enumerate(pair)]
        for k, pair in enumerate(ends)
    ]
    for n in range(len(x) - 1):
        # The arriving waves at the step's end: the other end's leaving wave at n.
        inc = [[refl_prev[k][1], refl_prev[k][0]] for k in range(len(ends))]
        xprev = xv
        xv = newton(xprev.copy(), x[n + 1], dt, xprev, hist, inc, False)
        for e in elements:
            if isinstance(e, Capacitor):
                gc = 2 * e.c_f / dt
                v0 = vnode(xprev, e.a) - vnode(xprev, e.b)
                v1 = vnode(xv, e.a) - vnode(xv, e.b)
                hist[e.name] = gc * (v1 - v0) - hist[e.name]
        refl_prev = [
            [vnode(xv, end.node) - inc[k][s] for s, end in enumerate(pair)]
            for k, pair in enumerate(ends)
        ]
        ys.append(probe_values(xv))
    arr = np.array(ys)
    return {f"v({p})": arr[:, j] for j, p in enumerate(probes)}


def _into(whole: dict, els, node: str, models) -> float:
    """The DC current leaving `node` into elements `els` (on the cut copy `node`, read at
    the uncut node's voltages)."""
    base = node.split("@")[0]

    def v(n):
        n = n.split("@")[0]
        return 0.0 if n == GROUND else whole["v"][n]

    total = 0.0
    for e in els:
        if isinstance(e, Resistor):
            other = e.b if e.a == node else e.a
            total += (v(base) - v(other)) / e.r_ohm
        elif isinstance(e, Inductor | VoltageSource):
            a = e.a if isinstance(e, Inductor) else e.pos
            total += whole["i"][e.name] * (1.0 if a == node else -1.0)
        elif isinstance(e, Device):
            m = models[e.model]
            vd = v(e.nodes[0]) - v(e.nodes[1])
            i_d = m.is_a * np.expm1(vd / (m.n * VT_TNOM))
            total += i_d * (1.0 if e.nodes[0] == node else -1.0)
    return total


def run_dc_whole(ir: CircuitIR, u0: float, gmin: float, tol_v: float, max_iter: int) -> dict:
    """The uncut circuit's DC point: {"v": node voltages, "i": inductor currents (a -> b)}."""
    one = CircuitIR(ir.title, ir.input_node, ir.probes, ir.models, ir.sections)
    elements, _, _, _, _ = _split(one, (), 1.0)
    models = {m.name: m for m in ir.models}
    mna = _Mna(elements, ir.input_node, [])
    nn = len(mna.node)
    xv = np.zeros(mna.n)
    for _ in range(max_iter):
        G = np.zeros((mna.n, mna.n))
        b = np.zeros(mna.n)
        for i in range(nn):
            G[i, i] += gmin

        def g(a, c, val, G=G):
            ia, ic = mna.i(a), mna.i(c)
            if ia is not None:
                G[ia, ia] += val
            if ic is not None:
                G[ic, ic] += val
            if ia is not None and ic is not None:
                G[ia, ic] -= val
                G[ic, ia] -= val

        def cur(a, c, val, b=b):
            ia, ic = mna.i(a), mna.i(c)
            if ia is not None:
                b[ia] -= val
            if ic is not None:
                b[ic] += val

        for e in elements:
            if isinstance(e, Resistor):
                g(e.a, e.b, 1.0 / e.r_ohm)
            elif isinstance(e, VoltageSource | Inductor):
                j = mna.branch[e.name]
                a, c = (e.pos, e.neg) if isinstance(e, VoltageSource) else (e.a, e.b)
                for n, s in ((mna.i(a), 1.0), (mna.i(c), -1.0)):
                    if n is not None:
                        G[n, j] += s
                        G[j, n] += s
                if isinstance(e, VoltageSource):
                    b[j] = e.dc_v
            elif isinstance(e, Device):
                m = models[e.model]
                ia, ic = mna.i(e.nodes[0]), mna.i(e.nodes[1])
                vd = (0.0 if ia is None else xv[ia]) - (0.0 if ic is None else xv[ic])
                nvt = m.n * VT_TNOM
                vd = min(vd, 40 * nvt + np.log(1e3 / m.is_a) * nvt)
                ex = np.exp(vd / nvt)
                gd = m.is_a / nvt * ex
                g(e.nodes[0], e.nodes[1], gd)
                cur(e.nodes[0], e.nodes[1], m.is_a * (ex - 1.0) - gd * vd)
        jin = mna.branch["<input>"]
        ii = mna.i(ir.input_node)
        if ii is not None:
            G[ii, jin] += 1.0
            G[jin, ii] += 1.0
        b[jin] = u0
        xn = np.linalg.solve(G, b)
        done = np.max(np.abs(xn[:nn] - xv[:nn])) < tol_v * (1 + np.max(np.abs(xn[:nn])))
        xv = xn
        if done:
            break
    return {
        "v": {n: xv[i] for n, i in mna.node.items()},
        "i": {
            e.name: xv[mna.branch[e.name]]
            for e in elements
            if isinstance(e, Inductor | VoltageSource)
        },
    }
