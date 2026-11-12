"""Structure of the DK step matrix A = G + C/(g h) per circuit: n, m, r, and what a
sparse LU of A would cost per solve against DK's dense stage products.

Devices are left out of A (as in DK) except a small conductance on each of their ports
(DK's shunts, here on every port so the device-stripped matrix is regular)."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import scipy.sparse as sp
import scipy.sparse.linalg as spla

from varimu.circuit import builder
from varimu.circuit import ir as irm
from varimu.circuit import spec as specm

ROOT = Path.cwd()
H = 1.0 / 96000.0
GAMMA = 1.0 - 2.0**-0.5  # TR-BDF2's diagonal
INV = 1.0 / (GAMMA * H)


def system(ir):
    index: dict[str, int] = {}

    def node(n):
        if n == irm.GROUND:
            return -1
        return index.setdefault(n, len(index))

    g, c = [], []  # (i, j, value) on node rows; branches appended after
    branches = []
    ports = 0
    els = list(ir.elements())
    ind_branch = {}
    for e in els:
        if isinstance(e, irm.Resistor):
            a, b = node(e.a), node(e.b)
            y = 1.0 / max(e.r_ohm, 1e-9)
            g += [(a, a, y), (b, b, y), (a, b, -y), (b, a, -y)]
        elif isinstance(e, irm.Capacitor):
            a, b = node(e.a), node(e.b)
            c += [(a, a, e.c_f), (b, b, e.c_f), (a, b, -e.c_f), (b, a, -e.c_f)]
        elif isinstance(e, irm.Inductor):
            ind_branch[e.name] = len(branches)
            branches.append(("l", node(e.a), node(e.b), e.l_h))
        elif isinstance(e, irm.VoltageSource | irm.SineSource):
            branches.append(("v", node(e.pos), node(e.neg), 0.0))
        elif isinstance(e, irm.Winding):
            branches.append(
                ("w", node(e.a), node(e.b), (node(e.core), e.turns * e.area_m2 * 1e-3, e.turns))
            )
        elif isinstance(e, irm.Vccs):
            p, q, cp, cn = node(e.pos), node(e.neg), node(e.ctrl_pos), node(e.ctrl_neg)
            g += [(q, cp, -e.gm_s), (q, cn, e.gm_s), (p, cp, e.gm_s), (p, cn, -e.gm_s)]
        elif isinstance(e, irm.Device):
            pins = [node(x) for x in e.nodes]
            ref = pins[-1]
            for p in pins[:-1]:
                ports += 1
                y = 1e-5
                g += [(p, p, y), (ref, ref, y), (p, ref, -y), (ref, p, -y)]
        else:
            for x in irm.element_nodes(e) if hasattr(irm, "element_nodes") else ():
                node(x)
    branches.append(("v", node(ir.input_node), -1, 0.0))
    for ctl in ir.controls:
        branches.append(("v", node(ctl.node), -1, 0.0))
    nn = len(index)
    n = nn + len(branches)
    gm = sp.lil_matrix((n, n))
    cm = sp.lil_matrix((n, n))
    for i, j, v in g:
        if i >= 0 and j >= 0:
            gm[i, j] += v
    for i, j, v in c:
        if i >= 0 and j >= 0:
            cm[i, j] += v
    for k, (kind, p, q, v) in enumerate(branches):
        r = nn + k
        for a, s in ((p, 1.0), (q, -1.0)):
            if a >= 0:
                gm[a, r] += s
                gm[r, a] += s
        if kind == "l":
            cm[r, r] -= v
        elif kind == "w":
            core, kv, turns = v
            if core >= 0:
                cm[r, core] -= kv
                gm[core, r] -= turns
    for e in els:
        if isinstance(e, irm.Coupling) and e.l_a in ind_branch and e.l_b in ind_branch:
            la = next(x for x in els if getattr(x, "name", None) == e.l_a)
            lb = next(x for x in els if getattr(x, "name", None) == e.l_b)
            mval = e.k * (la.l_h * lb.l_h) ** 0.5
            ra, rb = nn + ind_branch[e.l_a], nn + ind_branch[e.l_b]
            cm[ra, rb] -= mval
            cm[rb, ra] -= mval
    return gm.tocsc(), cm.tocsc(), ports, nn


def report(name, overrides=None, cores="linear"):
    spec = specm.load_circuit(ROOT / "config" / "circuits" / f"{name}.yaml")
    try:
        circ = builder.build(spec, overrides, cores=cores, events=True)
    except Exception as exc:  # noqa: BLE001
        print(f"{name}: build failed: {exc}")
        return
    ir = circ.ir
    g, c, m, nn = system(ir)
    n = g.shape[0]
    a = (g + INV * c).tocsc()
    # a leak on every node so floating device-only nodes don't make it singular
    a = a + sp.diags([1e-12] * nn + [0.0] * (n - nn)).tocsc()
    cc = c.tocsr()
    support = set(np.nonzero(cc.getnnz(axis=1))[0]) | set(np.nonzero(c.getnnz(axis=0))[0])
    r = len(support)
    try:
        lu = spla.splu(a, permc_spec="COLAMD")
        fill = lu.L.nnz + lu.U.nnz
    except Exception as exc:  # noqa: BLE001
        print(f"{name}: n={n} m={m} r={r} nnz(A)={a.nnz}  LU failed: {exc}")
        return
    dense_stage = (m + r) * r + r * m  # qa on ports+states, ia on states
    dense_step = (m + r) * r  # xa once per step
    sparse_stage = 2 * fill + (m + r) * m  # one sparse solve + the port-current share
    print(
        f"{name:28s} n={n:4d} m={m:3d} r={r:4d} nnz(A)={a.nnz:5d} nnz(L+U)={fill:6d} "
        f"| dense stage {dense_stage:7d} step {dense_step:7d} flops "
        f"| sparse stage ~{sparse_stage:7d} | ratio {dense_stage / sparse_stage:4.1f}"
    )


if __name__ == "__main__":
    names = sys.argv[1:] or [
        "triode_stage",
        "pultec_eqp1a",
        "fairchild_670",
        "fender_5e3",
        "tube_synth",
        "minimoog_voice",
        "urei_1176",
        "neve_1073",
        "univibe",
        "rhodes_suitcase_100w",
        "victorian_voice",
        "telefunken_v76",
    ]
    for nm in names:
        report(nm)
