"""Magnetic tape's particles as a Preisach ensemble (docs/TAPE_PLAN.md, TM1).

A tape coating is a packed ensemble of single-domain particles. The Preisach model
describes it as hysterons: each switches up when the field reaches alpha and down when
it falls to beta (alpha > beta). In the coordinates Hc = (alpha - beta) / 2 (the
particle's switching field) and Hi = -(alpha + beta) / 2 (the interaction field its
neighbours put on it), the ensemble is a density mu = f(Hc) g(Hi) / 2 over (alpha,
beta): f lognormal (the particles' switching-field spread), g a zero-mean Gaussian (many
random dipolar contributions). Della Torre, "Magnetic Hysteresis" (IEEE Press, 1999),
ch. 2-3; Mayergoyz, "Mathematical Models of Hysteresis" (Springer, 1991), ch. 1.

**The erased state** is what an erase head's decaying AC field leaves: a hysteron ends
up iff Hi > 0 (the last switch is the one needing the smaller amplitude). M = 0.

**State after a history** (`state_after`). A hysteron is up iff the last sample with
h >= alpha comes after the last one with h <= beta, else (neither ever happened) it keeps
its erased state. The hysterons switched up and not since switched down are the union of
the quadrants {alpha <= h_t, beta < S_min(t+1)} (S_min, S_max: the suffix extrema of h),
whose corners are the backward records of h (h_t > S_max(t+1)). With Q(a, b) the weight
of {alpha <= a, beta < b} (beta < alpha), that union weighs

    sum over records t of Q(h_t, S_min(t+1)) - Q(S_max(t+1), S_min(t+1)),

and the hysterons never reached (alpha > max h, beta < min h) keep the erased state:
I(A, B) = Q(max(A, -B), B) - Q(A, B) + D(max(A, -B)), D(x) the erased-up weight of the
hysterons with alpha > x. All of it is suffix extrema and table lookups, vectorized over
cells. Only extrema of h matter (the model is rate independent): a tape cell under AC
bias needs only the field's peaks, two per bias cycle.

**Two quadratures of the same formula.** The production tables (`Preisach`) are Q and D
of the continuous density on a fine grid, read by bicubic interpolation: M is smooth in
the fields (a discrete set of hysterons would make the anhysteretic curve, the
recording's transfer curve, a staircase: ~5% of Ms per step at 128 points). The tests'
`grid=True` reads Q and D of a coarse discrete grid exactly, which `brute_force` (every
hysteron stepped) must match.

M is in units of the saturation magnetization (M / Ms in [-1, 1]); fields in A/m. The
reversible (rotational) part of a particle's magnetization isn't modelled: it vanishes
with the field, so recorded remanence doesn't depend on it (it would act through
demagnetization, TAPE_PLAN.md TM2).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from functools import cached_property

import numpy as np

OE_A_PER_M = 1000.0 / (4.0 * math.pi)  # 1 Oe in A/m


@dataclass(frozen=True)
class PreisachParams:
    """The ensemble: f(Hc) lognormal with median hc_median_a_m and log-spread sigma_ln_hc,
    g(Hi) Gaussian with standard deviation sigma_hi_a_m, both over +-h_max_a_m (fields
    beyond it are clamped: the mass outside is `truncated_mass`). n: points per axis of
    the tests' discrete grid; n_table: of the production tables."""

    hc_median_a_m: float
    sigma_ln_hc: float
    sigma_hi_a_m: float
    h_max_a_m: float
    n: int = 64
    n_table: int = 1024


def _weights(p: PreisachParams, n: int) -> tuple[np.ndarray, np.ndarray, float]:
    """(centres, w, raw total): w[i, k] the density's weight in the cell centred on
    (alpha_i, beta_k) of an n x n grid over +-h_max (zero unless alpha > beta),
    normalized to 1."""
    h = p.h_max_a_m
    d = 2.0 * h / n
    c = -h + (np.arange(n) + 0.5) * d
    alpha, beta = c[:, None], c[None, :]
    hc = 0.5 * (alpha - beta)
    hi = -0.5 * (alpha + beta)
    valid = hc > 0
    hcs = np.where(valid, hc, 1.0)
    f = np.exp(-0.5 * (np.log(hcs / p.hc_median_a_m) / p.sigma_ln_hc) ** 2) / (
        hcs * p.sigma_ln_hc * math.sqrt(2.0 * math.pi)
    )
    g = np.exp(-0.5 * (hi / p.sigma_hi_a_m) ** 2) / (p.sigma_hi_a_m * math.sqrt(2.0 * math.pi))
    w = np.where(valid, f * g * d * d / 2.0, 0.0)
    total = float(w.sum())
    return c, w / total, total


def _erased(n: int) -> np.ndarray:
    """The erased state on an n x n grid: 1 up (Hi > 0: i + k < n - 1), 1/2 on Hi = 0."""
    s = np.add.outer(np.arange(n), np.arange(n))
    return np.where(s < n - 1, 1.0, np.where(s == n - 1, 0.5, 0.0))


def _tables(w: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Q at the grid's nodes (Q[a, b]: cells i < a, k < b) and D (D[m]: erased-up weight
    of cells i >= m)."""
    n = w.shape[0]
    q = np.zeros((n + 1, n + 1))
    q[1:, 1:] = np.cumsum(np.cumsum(w, axis=0), axis=1)
    row = (w * _erased(n)).sum(axis=1)
    d = np.zeros(n + 1)
    d[:n] = np.cumsum(row[::-1])[::-1]
    return q, d


def _catmull_rom(f: np.ndarray) -> tuple[np.ndarray, ...]:
    """Catmull-Rom weights for fractions f (four taps at -1, 0, 1, 2)."""
    f2, f3 = f * f, f * f * f
    return (
        -0.5 * f3 + f2 - 0.5 * f,
        1.5 * f3 - 2.5 * f2 + 1.0,
        -1.5 * f3 + 2.0 * f2 + 0.5 * f,
        0.5 * f3 - 0.5 * f2,
    )


@dataclass(frozen=True)
class Preisach:
    p: PreisachParams

    # --- The tests' discrete grid -------------------------------------------------------

    @cached_property
    def _grid(self) -> tuple[np.ndarray, np.ndarray, float]:
        return _weights(self.p, self.p.n)

    @property
    def grid(self) -> np.ndarray:
        """The discrete grid's alpha_i = beta_i (A/m), rising."""
        return self._grid[0]

    @property
    def weights(self) -> np.ndarray:
        """The discrete grid's w[i, k] for hysteron (alpha_i, beta_k), summing to 1."""
        return self._grid[1]

    @cached_property
    def initial(self) -> np.ndarray:
        """The discrete grid's erased state."""
        return _erased(self.p.n)

    @cached_property
    def _grid_tables(self) -> tuple[np.ndarray, np.ndarray]:
        return _tables(self.weights)

    def _grid_count(self, x: np.ndarray, strict: bool) -> np.ndarray:
        """How many grid points are <= x (strict: < x)."""
        return np.searchsorted(self.grid, x, side="left" if strict else "right")

    def _q_grid(self, a: np.ndarray, b: np.ndarray) -> np.ndarray:
        q, _ = self._grid_tables
        return q[self._grid_count(a, False), self._grid_count(b, True)]

    def _d_grid(self, x: np.ndarray) -> np.ndarray:
        _, d = self._grid_tables
        return d[self._grid_count(x, False)]

    # --- The production tables ----------------------------------------------------------

    @cached_property
    def _fine(self) -> tuple[np.ndarray, np.ndarray, float]:
        c, w, total = _weights(self.p, self.p.n_table)
        q, d = _tables(w)
        return q, d, total

    @property
    def truncated_mass(self) -> float:
        """The density's mass outside +-h_max (by the fine grid's quadrature)."""
        return 1.0 - self._fine[2]

    def _node(self, x: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Fine-table node index and fraction for fields x (clamped to +-h_max)."""
        n, h = self.p.n_table, self.p.h_max_a_m
        u = (np.clip(x, -h, h) + h) * (n / (2.0 * h))
        i = np.clip(np.floor(u).astype(np.int64), 0, n - 1)
        return i, u - i

    def _q(self, a: np.ndarray, b: np.ndarray) -> np.ndarray:
        """Q(a, b), bicubic in the fine table's nodes (held at its edges)."""
        q = self._fine[0]
        n = self.p.n_table
        ia, fa = self._node(a)
        ib, fb = self._node(b)
        wa, wb = _catmull_rom(fa), _catmull_rom(fb)
        out = np.zeros(np.broadcast(a, b).shape)
        for da in range(4):
            ra = np.clip(ia + da - 1, 0, n)
            acc = np.zeros_like(out)
            for db in range(4):
                acc += wb[db] * q[ra, np.clip(ib + db - 1, 0, n)]
            out += wa[da] * acc
        return out

    def _d(self, x: np.ndarray) -> np.ndarray:
        d = self._fine[1]
        n = self.p.n_table
        i, f = self._node(x)
        w = _catmull_rom(f)
        return sum(w[k] * d[np.clip(i + k - 1, 0, n)] for k in range(4))

    # --- The model ----------------------------------------------------------------------

    def state_after(self, h: np.ndarray, grid: bool = False) -> np.ndarray:
        """M / Ms after each row of `h` (cells x samples, A/m), starting erased. grid:
        on the discrete grid (exact, the tests'), else on the production tables."""
        q, dfun = (self._q_grid, self._d_grid) if grid else (self._q, self._d)
        h = np.atleast_2d(np.asarray(h, dtype=float))
        cells = h.shape[0]
        smax = np.maximum.accumulate(h[:, ::-1], axis=1)[:, ::-1]
        smin = np.minimum.accumulate(h[:, ::-1], axis=1)[:, ::-1]
        # The suffix extrema after each sample (after the last: none).
        nmax = np.concatenate([smax[:, 1:], np.full((cells, 1), -np.inf)], axis=1)
        nmin = np.concatenate([smin[:, 1:], np.full((cells, 1), np.inf)], axis=1)
        rec = h > nmax
        r, t = np.nonzero(rec)
        a, b, a_next = h[r, t], nmin[r, t], nmax[r, t]
        big = 4.0 * self.p.h_max_a_m  # stands in for the infinities (clamped anyway)
        b = np.minimum(b, big)
        a_next = np.maximum(a_next, -big)
        up = np.zeros(cells)
        np.add.at(up, r, q(a, b) - q(a_next, b))
        # Never reached: the erased state.
        top, bot = smax[:, 0], smin[:, 0]
        x = np.maximum(top, -bot)
        up += q(x, bot) - q(top, bot) + dfun(x)
        return 2.0 * up - 1.0

    def brute_force(self, h: np.ndarray) -> np.ndarray:
        """state_after on the discrete grid by stepping every hysteron (the tests'
        oracle; slow)."""
        h = np.atleast_2d(np.asarray(h, dtype=float))
        a = self.grid
        out = np.empty(h.shape[0])
        for c in range(h.shape[0]):
            s = self.initial.copy()
            for x in h[c]:
                s = np.where(a[:, None] <= x, 1.0, s)
                s = np.where(a[None, :] >= x, 0.0, s)
            out[c] = 2.0 * float((self.weights * s).sum()) - 1.0
        return out

    # --- Curves of the ensemble ---------------------------------------------------------

    def major_loop(self, h: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """(ascending, descending) M / Ms at fields `h` after saturation the other way."""
        h = np.asarray(h, dtype=float)
        hs = 2.0 * self.p.h_max_a_m
        asc = self.state_after(np.stack([np.full_like(h, -hs), h], axis=1))
        desc = self.state_after(np.stack([np.full_like(h, hs), h], axis=1))
        return asc, desc

    def _decaying_ac(self, h: np.ndarray, cycles: int) -> np.ndarray:
        amp = 2.0 * self.p.h_max_a_m * (1.0 - np.arange(cycles) / cycles)
        sign = np.where(np.arange(cycles) % 2 == 0, 1.0, -1.0)
        return h[:, None] + (amp * sign)[None, :]

    def anhysteretic(self, h: np.ndarray, cycles: int = 4096) -> np.ndarray:
        """M / Ms left by an AC field decaying linearly from saturation to 0 over
        `cycles` half cycles on top of a steady h."""
        h = np.asarray(h, dtype=float)
        return self.state_after(self._decaying_ac(h, cycles))

    def anhysteretic_remanence(self, h: np.ndarray, cycles: int = 4096) -> np.ndarray:
        """M / Ms after the decaying AC with h, then h removed."""
        h = np.asarray(h, dtype=float)
        hist = self._decaying_ac(h, cycles)
        return self.state_after(np.concatenate([hist, np.zeros((len(h), 1))], axis=1))
