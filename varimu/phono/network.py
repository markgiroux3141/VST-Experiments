"""Linear lumped networks for the acoustic machines (docs/PHONO_PLAN.md, G1-G3).

Mechanical parts in the **mobility** analogy (a node's voltage is its velocity in m/s, a
branch current the force in N it carries): a mass is a capacitor to ground (an inertial
frame), a spring an inductor of 1 / stiffness, a damper a conductance of its mechanical
resistance, a lever an ideal transformer (velocities in its ratio, forces in its inverse).
Acoustic parts in the **impedance** analogy (voltage: pressure in Pa, current: volume
velocity in m^3/s): a duct's air mass an inductance rho dx / S, its compliance a capacitor
S dx / (rho c^2) to ground. A diaphragm of area S joins the two as a gyrator (force = -S p
on the mechanical side, volume velocity = S v on the acoustic side). The network's topology
is the machine's: nodes are moving points and air volumes.

The network is a descriptor system E x' + G x = B u (modified nodal analysis: node voltages,
then the currents of inductors, transformers and voltage sources, then integrators, whose
state is a node's displacement). Two ways to run it:

- `response(f)`: the exact continuous-time response at frequencies f (linear chains, e.g.
  the recorder: pressure in, cutter displacement out);
- `Stepper`: the trapezoidal rule at a fixed step (algebraic rows held at the step's end,
  so they don't ring), with one nonlinear port (the stylus' contact) solved per step.

Python only for now: the circuit-sim port is G1's Rust half (PHONO_PLAN.md).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

GROUND = "0"


@dataclass
class Network:
    nodes: list[str] = field(default_factory=list)
    _c: list[tuple[str, str, float]] = field(default_factory=list)
    _g: list[tuple[str, str, float]] = field(default_factory=list)
    _l: list[tuple[str, str, float, str]] = field(default_factory=list)
    _xf: list[tuple[str, str, str, str, float, str]] = field(default_factory=list)
    _vccs: list[tuple[str, str, float]] = field(default_factory=list)
    _vsrc: list[tuple[str, str, str]] = field(default_factory=list)
    _isrc: list[tuple[str, str]] = field(default_factory=list)
    _integ: list[tuple[str, str]] = field(default_factory=list)

    def node(self, name: str) -> str:
        if name != GROUND and name not in self.nodes:
            self.nodes.append(name)
        return name

    # Elements (a, b: nodes; positive current flows a -> b through the element).
    def capacitor(self, a: str, b: str, c: float) -> None:
        self._c.append((self.node(a), self.node(b), float(c)))

    def conductance(self, a: str, b: str, g: float) -> None:
        self._g.append((self.node(a), self.node(b), float(g)))

    def resistor(self, a: str, b: str, r: float) -> None:
        self.conductance(a, b, 1.0 / r)

    def inductor(self, a: str, b: str, ind: float, name: str) -> None:
        self._l.append((self.node(a), self.node(b), float(ind), name))

    def transformer(self, p1: str, p2: str, s1: str, s2: str, n: float, name: str) -> None:
        """Ideal: v(s1, s2) = n v(p1, p2); the current into p1 is -n times that into s1."""
        for x in (p1, p2, s1, s2):
            self.node(x)
        self._xf.append((p1, p2, s1, s2, float(n), name))

    def vccs(self, out: str, ctrl: str, g: float) -> None:
        """Injects g * v(ctrl) into node `out`."""
        self._vccs.append((self.node(out), self.node(ctrl), float(g)))

    def gyrator(self, mech: str, acoustic: str, area_m2: float) -> None:
        """A diaphragm of effective area S: force -S p on `mech` (positive velocity moves
        it into the air volume `acoustic`), volume velocity S v into `acoustic`."""
        self.vccs(mech, acoustic, -area_m2)
        self.vccs(acoustic, mech, area_m2)

    def voltage_source(self, a: str, b: str, name: str) -> None:
        self._vsrc.append((self.node(a), self.node(b), name))

    def current_source(self, node: str, name: str) -> None:
        """Injects the input `name` into `node` (a force in the mobility analogy)."""
        self._isrc.append((self.node(node), name))

    def integrator(self, node: str, name: str) -> None:
        """A state equal to the integral of v(node): a displacement."""
        self._integ.append((self.node(node), name))

    # Assembly.
    def compile(self) -> System:
        idx = {n: i for i, n in enumerate(self.nodes)}
        extra: list[str] = (
            [e[3] for e in self._l]
            + [e[5] for e in self._xf]
            + [e[2] for e in self._vsrc]
            + [e[1] for e in self._integ]
        )
        names = list(self.nodes) + extra
        if len(set(names)) != len(names):
            raise ValueError("duplicate node / element names")
        pos = {n: i for i, n in enumerate(names)}
        inputs = [e[2] for e in self._vsrc] + [e[1] for e in self._isrc]
        inputs = list(dict.fromkeys(inputs))
        ipos = {n: i for i, n in enumerate(inputs)}
        size = len(names)
        e_m = np.zeros((size, size))
        g_m = np.zeros((size, size))
        b_m = np.zeros((size, len(inputs)))

        def stamp2(m: np.ndarray, a: str, b: str, val: float) -> None:
            ia, ib = idx.get(a), idx.get(b)
            if ia is not None:
                m[ia, ia] += val
            if ib is not None:
                m[ib, ib] += val
            if ia is not None and ib is not None:
                m[ia, ib] -= val
                m[ib, ia] -= val

        for a, b, c in self._c:
            stamp2(e_m, a, b, c)
        for a, b, g in self._g:
            stamp2(g_m, a, b, g)
        for out, ctrl, g in self._vccs:
            if out in idx and ctrl in idx:
                g_m[idx[out], idx[ctrl]] -= g
        for a, b, ind, name in self._l:
            k = pos[name]
            e_m[k, k] = ind
            for node, sgn in ((a, 1.0), (b, -1.0)):
                if node in idx:
                    g_m[idx[node], k] += sgn
                    g_m[k, idx[node]] -= sgn
        for p1, p2, s1, s2, n, name in self._xf:
            k = pos[name]
            for node, sgn in ((s1, 1.0), (s2, -1.0)):
                if node in idx:
                    g_m[idx[node], k] += sgn
                    g_m[k, idx[node]] += sgn
            for node, sgn in ((p1, -n), (p2, n)):
                if node in idx:
                    g_m[idx[node], k] += sgn
                    g_m[k, idx[node]] += sgn
        for a, b, name in self._vsrc:
            k = pos[name]
            for node, sgn in ((a, 1.0), (b, -1.0)):
                if node in idx:
                    g_m[idx[node], k] += sgn
                    g_m[k, idx[node]] += sgn
            b_m[k, ipos[name]] = 1.0
        for node, name in self._isrc:
            b_m[idx[node], ipos[name]] += 1.0
        for node, name in self._integ:
            k = pos[name]
            e_m[k, k] = 1.0
            g_m[k, idx[node]] = -1.0
        return System(names=names, inputs=inputs, e=e_m, g=g_m, b=b_m, net=self)


@dataclass
class System:
    names: list[str]
    inputs: list[str]
    e: np.ndarray
    g: np.ndarray
    b: np.ndarray
    net: Network

    def index(self, name: str) -> int:
        return self.names.index(name)

    def pick(self, name: str) -> np.ndarray:
        row = np.zeros(len(self.names))
        row[self.index(name)] = 1.0
        return row

    def element_current(self, a: str, b: str, kind: str, value: float) -> np.ndarray:
        """The row c with c @ x = the current a -> b through a conductance (kind 'g') of
        value g; inductor currents are states (`pick`)."""
        if kind != "g":
            raise ValueError(kind)
        row = np.zeros(len(self.names))
        if a != GROUND:
            row[self.index(a)] += value
        if b != GROUND:
            row[self.index(b)] -= value
        return row

    def response(self, f_hz: np.ndarray, inp: str) -> np.ndarray:
        """X(f) per unit of input `inp`: shape (len(f), len(names)), exact in continuous
        time (batched solves). Rows at f = 0 are left 0 (integrators make DC singular)."""
        col = self.b[:, self.inputs.index(inp)]
        f_hz = np.asarray(f_hz, dtype=float)
        out = np.zeros((len(f_hz), len(self.names)), dtype=complex)
        live = np.flatnonzero(f_hz != 0.0)  # DC is singular with integrators: left 0
        chunk = max(1, 2_000_000 // max(1, len(self.names) ** 2))
        for lo in range(0, len(live), chunk):
            idx = live[lo : lo + chunk]
            m = 2j * np.pi * f_hz[idx, None, None] * self.e + self.g
            rhs = np.broadcast_to(col, (len(idx), len(col)))[..., None]
            out[idx] = np.linalg.solve(m, rhs)[..., 0]
        return out


class Stepper:
    """The trapezoidal rule at step h with inputs held per step's ends; rows of E that are
    zero (algebraic) hold at the step's end instead of the average.

    x1 = P x0 + Q0 u0 + Q1 u1. A nonlinear port is an input (a current into a node) whose
    value at the step's end the caller solves for: x1 = x_pred + q1[port] * u1[port].
    """

    def __init__(self, sys: System, h: float):
        n = len(sys.names)
        alg = ~np.any(sys.e != 0.0, axis=1)
        left = sys.e / h + 0.5 * sys.g
        right = sys.e / h - 0.5 * sys.g
        b0 = 0.5 * sys.b.copy()
        b1 = 0.5 * sys.b.copy()
        left[alg] = sys.g[alg]
        right[alg] = 0.0
        b0[alg] = 0.0
        b1[alg] = sys.b[alg]
        lu = np.linalg.inv(left)
        self.sys = sys
        self.h = h
        self.p = lu @ right
        self.q0 = lu @ b0
        self.q1 = lu @ b1
        self.x = np.zeros(n)

    def input_cols(self, name: str) -> tuple[np.ndarray, np.ndarray]:
        k = self.sys.inputs.index(name)
        return self.q0[:, k], self.q1[:, k]

    def run(self, name: str, u: np.ndarray, rows: np.ndarray) -> np.ndarray:
        """A linear run from rest driven by input `name` (one value per step), returning
        rows @ x per step (rows: (k, n)). x_0 = Q1 u_0, then x_i = P x_(i-1) + Q0 u_(i-1)
        + Q1 u_i."""
        q0, q1 = self.input_cols(name)
        rows = np.atleast_2d(rows)
        out = np.empty((len(u), rows.shape[0]))
        x = q1 * u[0]
        out[0] = rows @ x
        p = self.p
        for i in range(1, len(u)):
            x = p @ x + q0 * u[i - 1] + q1 * u[i]
            out[i] = rows @ x
        return out

    def impulse_response(self, name: str, row: np.ndarray, n: int) -> np.ndarray:
        """The response of rows @ x to a unit sample of input `name`, n samples long."""
        u = np.zeros(n)
        u[0] = 1.0
        return self.run(name, u, row)[:, 0]
