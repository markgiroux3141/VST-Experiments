"""Small-signal AC analysis of linear IR elements (complex nodal analysis).

For linear networks only: resistors, capacitors, inductors and voltage-controlled
current sources (varimu.circuit.ir.Vccs). It serves the speaker (component editor C3):
its impedance and on-axis response for the fit to the datasheet's curves, and the
speaker's admittance for the amplifier profile's power figures. The transient engines
never use it; tests compare it with them.

`solve(elements, freqs, drive, outputs)` drives `drive = (pos, neg)` with 1 A (into pos,
out of neg) and returns the voltage of every output node per frequency; a 1 A drive at
the terminals gives the impedance there, and the response to a voltage at the terminals
is any node's voltage over it (the network is linear).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

import numpy as np

from varimu.circuit.ir import GROUND, Capacitor, Element, Inductor, Resistor, Vccs, element_nodes


def solve(
    elements: Iterable[Element],
    freqs_hz: Sequence[float] | np.ndarray,
    drive: tuple[str, str],
    outputs: Sequence[str],
) -> dict[str, np.ndarray]:
    """Node voltages (complex, one per frequency) for 1 A driven into drive[0] and out of
    drive[1]. Raises TypeError for an element that isn't linear R, C, L or Vccs."""
    els = list(elements)
    nodes: dict[str, int] = {}
    for el in els:
        for n in element_nodes(el):
            if n != GROUND and n not in nodes:
                nodes[n] = len(nodes)
    n = len(nodes)
    g, c, gam = np.zeros((n, n)), np.zeros((n, n)), np.zeros((n, n))

    def stamp(m: np.ndarray, a: str, b: str, y: float) -> None:
        for u, v, s in ((a, a, 1.0), (b, b, 1.0), (a, b, -1.0), (b, a, -1.0)):
            if u != GROUND and v != GROUND:
                m[nodes[u], nodes[v]] += s * y

    for el in els:
        if isinstance(el, Resistor):
            stamp(g, el.a, el.b, 1.0 / el.r_ohm)
        elif isinstance(el, Capacitor):
            stamp(c, el.a, el.b, el.c_f)
        elif isinstance(el, Inductor):
            stamp(gam, el.a, el.b, 1.0 / el.l_h)
        elif isinstance(el, Vccs):
            for row, sr in ((el.pos, 1.0), (el.neg, -1.0)):
                for col, sc in ((el.ctrl_pos, 1.0), (el.ctrl_neg, -1.0)):
                    if row != GROUND and col != GROUND:
                        g[nodes[row], nodes[col]] += sr * sc * el.gm_s
        else:
            raise TypeError(f"{el.name}: AC analysis takes R, C, L and Vccs only")
    rhs = np.zeros(n, complex)
    if drive[0] != GROUND:
        rhs[nodes[drive[0]]] += 1.0
    if drive[1] != GROUND:
        rhs[nodes[drive[1]]] -= 1.0
    jw = 2j * np.pi * np.asarray(freqs_hz, float)[:, None, None]
    y = g[None] + jw * c[None] + gam[None] / jw
    x = np.linalg.solve(y, np.broadcast_to(rhs, (len(jw), n))[..., None])[..., 0]
    return {o: (x[:, nodes[o]] if o != GROUND else np.zeros(len(jw), complex)) for o in outputs}
