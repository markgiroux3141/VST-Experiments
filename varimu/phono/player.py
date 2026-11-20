"""A groove player's loop, in two engines (docs/PHONO_PLAN.md, G1): a machine's linear
network (network.py's `Stepper`, the trapezoidal rule) driven by known inputs and by
**contacts**, inputs whose value at each step's end is solved against a surface.

A contact k has a row (the tip's coordinate along the contact's normal, toward the
groove's air), a Hertz stiffness K and Hunt and Crossley's damping alpha. Each step:

    x_pred = P x + sum_j (Q0_j u_j[i-1] + Q1_j u_j[i]) + sum_k Q0_k f_k[i-1]
    a_k    = surface_k[i] - row_k . x_pred          (the indentation if no force acted)
    f      = K d^1.5 (1 + alpha (d - d_prev) / h),  f >= 0,  d = a - Kff f
    x      = x_pred + sum_k Q1_k f_k

Kff_kj = row_k . Q1_j: how far contact j's force moves contact k's tip by the step's end.
One contact (a cylinder's floor) is solved by bisection safeguarding Newton
(`solve_one`); several (a V-groove's two walls) by projected Newton with backtracking
(`solve`). Mistracking is where a force is 0: no special case.

Engines (`run(..., engine=)`):
- "python": the reference, the dense stepper, step by step in numpy;
- "rust" (the default): circuitsim's `phono_play` (crates/circuitsim/src/phono.rs) on the
  network's **modes**: P = V diag(lam) V^-1 once (`modal`), one of each conjugate pair kept
  and its read-out rows doubled (a real network's paired states stay conjugate under real
  inputs). O(modes) per step instead of O(states^2), equal to the reference to rounding.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

import numpy as np

from varimu.phono.network import Stepper


@dataclass
class Contact:
    input: str  # the network input that carries its force
    row: np.ndarray  # the tip's coordinate along the normal: row @ x
    k: float  # Hertz: F = k d^1.5
    alpha: float  # Hunt and Crossley's damping (s/m)
    surface: np.ndarray  # the surface along the normal, per step


@dataclass
class Run:
    forces: np.ndarray  # (contacts, steps)
    outputs: np.ndarray  # (rows, steps)


def _law(k: float, alpha: float, d: float, d_prev: float, h: float) -> tuple[float, float]:
    if d <= 0.0:
        return 0.0, 0.0
    rate = 1.0 + alpha * (d - d_prev) / h
    f = k * d**1.5 * rate
    if f < 0.0:
        return 0.0, 0.0
    return f, k * (1.5 * d**0.5 * rate + d**1.5 * alpha / h)


def solve_one(a: float, kff: float, big_k: float, alpha: float, d_prev: float, h: float) -> float:
    """The force f >= 0 at the step's end with f = K d^1.5 (1 + alpha (d - d_prev) / h),
    d = a - kff f (Hunt-Crossley, its rate by the step's difference). The residual is
    increasing in f on [0, a / kff]: bisection safeguarding Newton."""
    lo, hi = 0.0, a / kff
    f = min(big_k * a**1.5, hi)
    for _ in range(60):
        d = a - kff * f
        rate = 1.0 + alpha * (d - d_prev) / h
        law = big_k * d**1.5 * rate
        if law < 0.0:  # separating faster than the surface recovers: no force
            law = 0.0
        r = f - law
        if r > 0:
            hi = f
        else:
            lo = f
        if abs(r) <= 1e-12 * max(1.0, f):
            return f
        dlaw = -kff * big_k * (1.5 * d**0.5 * rate + d**1.5 * alpha / h) if law > 0 else 0.0
        fn = f - r / (1.0 - dlaw)
        f = fn if lo < fn < hi else 0.5 * (lo + hi)
        if hi - lo <= 1e-15 * max(1.0, hi):
            return f
    return f


def solve(a: np.ndarray, kff: np.ndarray, ks, alphas, d_prev: np.ndarray, h: float) -> np.ndarray:
    """The contacts' forces at the step's end (phono.rs's `solve_contacts`)."""
    n = len(a)
    f = np.zeros(n)
    if n == 0:
        return f
    if n == 1:
        if a[0] > 0.0:
            f[0] = solve_one(a[0], kff[0, 0], ks[0], alphas[0], d_prev[0], h)
        return f
    for k in range(n):
        if a[k] > 0.0:
            f[k] = solve_one(a[k], kff[k, k], ks[k], alphas[k], d_prev[k], h)

    def resid(f):
        r = np.empty(n)
        g = np.empty(n)
        for k in range(n):
            d = a[k]
            for j in range(n):
                d -= kff[k, j] * f[j]
            lw, dl = _law(ks[k], alphas[k], d, d_prev[k], h)
            r[k] = f[k] - lw
            g[k] = dl
        return r, g, float(np.max(np.abs(r)))

    r, g, norm = resid(f)
    for _ in range(60):
        if norm <= 1e-12 * max(1.0, float(np.max(np.abs(f)))):
            return f
        jm = np.eye(n) + g[:, None] * kff
        step = np.linalg.solve(jm, r)
        t = 1.0
        for _ in range(40):
            trial = np.maximum(f - t * step, 0.0)
            rt, gt, nt = resid(trial)
            if nt < norm:
                f, r, g, norm = trial, rt, gt, nt
                break
            t *= 0.5
        else:
            return f
    return f


@dataclass
class Modal:
    lam: np.ndarray  # kept eigenvalues (complex)
    vinv: np.ndarray  # rows of V^-1 for the kept modes
    v: np.ndarray  # columns of V for the kept modes, read-out weights folded in
    weight: np.ndarray  # 1 for real modes, 2 for the kept half of a conjugate pair


def modal(st: Stepper) -> Modal:
    """P = V diag(lam) V^-1, one of each conjugate pair kept (LAPACK returns real
    eigenvalues with an exact zero imaginary part and pairs exactly conjugate)."""
    lam, v = np.linalg.eig(st.p)
    vinv = np.linalg.inv(v)
    keep = np.flatnonzero(lam.imag >= 0.0)
    w = np.where(lam[keep].imag > 0.0, 2.0, 1.0)
    if np.sum(w) != len(lam):
        raise ValueError("unpaired complex eigenvalues")
    return Modal(lam[keep], vinv[keep], v[:, keep], w)


def _cvec(z: np.ndarray) -> list[list[float]]:
    z = np.asarray(z, dtype=complex)
    return [z.real.tolist(), z.imag.tolist()]


def model_json(
    st: Stepper, md: Modal, x0: np.ndarray, inputs: list[str], contacts: list[Contact], rows
) -> str:
    """phono.rs's `Player` for this network and its ports."""

    def cols(name):
        q0, q1 = st.input_cols(name)
        return {"b0": _cvec(md.vinv @ q0), "b1": _cvec(md.vinv @ q1)}

    def row(r):
        return _cvec((np.asarray(r) @ md.v) * md.weight)

    return json.dumps(
        {
            "lam": _cvec(md.lam),
            "xi0": _cvec(md.vinv @ x0),
            "inputs": [cols(n) for n in inputs],
            "contacts": [
                {**cols(c.input), "row": row(c.row), "k": float(c.k), "alpha": float(c.alpha)}
                for c in contacts
            ],
            "outputs": [row(r) for r in rows],
        }
    )


def run(
    st: Stepper,
    x0: np.ndarray,
    inputs: dict[str, np.ndarray],
    contacts: list[Contact],
    rows: np.ndarray,
    steps: int,
    engine: str = "rust",
    md: Modal | None = None,
) -> Run:
    """`steps` steps from x0 (step 0), inputs given per step, outputs rows @ x per step."""
    rows = np.atleast_2d(np.asarray(rows, dtype=float))
    names = list(inputs)
    if engine == "python":
        return _run_python(st, x0, inputs, contacts, rows, steps)
    if engine != "rust":
        raise ValueError(f"engine {engine!r}: 'rust' or 'python'")
    from varimu.sim import fast

    fast.check_build()
    import circuitsim

    md = md or modal(st)
    model = model_json(st, md, x0, names, contacts, rows)
    u = np.ascontiguousarray(
        np.concatenate([np.asarray(inputs[n], dtype=float)[:steps] for n in names])
        if names
        else np.zeros(0)
    )
    surf = np.ascontiguousarray(
        np.concatenate([np.asarray(c.surface, dtype=float)[:steps] for c in contacts])
        if contacts
        else np.zeros(0)
    )
    f, out = circuitsim.phono_play(model, u, surf, steps, st.h)
    return Run(
        np.asarray(f).reshape(len(contacts), steps), np.asarray(out).reshape(len(rows), steps)
    )


def _run_python(st, x0, inputs, contacts, rows, steps) -> Run:
    p, h = st.p, st.h
    qin = [(st.input_cols(n), np.asarray(u, dtype=float)) for n, u in inputs.items()]
    qc = [st.input_cols(c.input) for c in contacts]
    nc = len(contacts)
    crow = np.array([c.row for c in contacts]).reshape(nc, -1)
    kff = np.array([[crow[k] @ qc[j][1] for j in range(nc)] for k in range(nc)]).reshape(nc, nc)
    ks = [c.k for c in contacts]
    alphas = [c.alpha for c in contacts]
    surf = [np.asarray(c.surface, dtype=float) for c in contacts]
    x = np.array(x0, dtype=float)
    forces = np.zeros((nc, steps))
    out = np.zeros((len(rows), steps))
    out[:, 0] = rows @ x
    f0 = np.zeros(nc)
    d0 = np.zeros(nc)
    for i in range(1, steps):
        xp = p @ x
        for (q0, q1), u in qin:
            if u[i - 1] != 0.0 or u[i] != 0.0:
                xp = xp + q0 * u[i - 1] + q1 * u[i]
        for k in range(nc):
            if f0[k] != 0.0:
                xp = xp + qc[k][0] * f0[k]
        a = np.array([surf[k][i] - crow[k] @ xp for k in range(nc)])
        f1 = solve(a, kff, ks, alphas, d0, h)
        d0 = np.maximum(a - kff @ f1, 0.0) if nc else d0
        for k in range(nc):
            if f1[k] != 0.0:
                xp = xp + qc[k][1] * f1[k]
        x = xp
        forces[:, i] = f1
        out[:, i] = rows @ x
        f0 = f1
    return Run(forces, out)
