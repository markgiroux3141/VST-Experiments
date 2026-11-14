"""Interactions between mechanisms (ANALOG_MAGIC_FABLE.md AM14): a 2^k factorial of switches
that exist, main effects and two-factor interactions as signals, Shapley values of a score.

`y` maps a frozenset of the factors switched on to the output. With S the factors on:
- main effect of a: mean over the settings of the others of y[S + a] - y[S];
- interaction of a and b: mean over the others of y[S+ab] - y[S+a] - y[S+b] + y[S];
- Shapley value of a score v(S) (exact, all orderings): each factor's average marginal
  contribution; they sum to v(all) - v(none).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from itertools import combinations, permutations

import numpy as np

from varimu.listen import difference


def subsets(factors: Sequence[str]) -> list[frozenset[str]]:
    return [frozenset(c) for k in range(len(factors) + 1) for c in combinations(factors, k)]


def _trim(ys: Mapping[frozenset, np.ndarray]) -> dict[frozenset, np.ndarray]:
    n = min(len(v) for v in ys.values())
    return {k: np.asarray(v[:n], float) for k, v in ys.items()}


def main_effect(y: Mapping[frozenset, np.ndarray], factors: Sequence[str], a: str) -> np.ndarray:
    y = _trim(y)
    others = [f for f in factors if f != a]
    terms = [y[s | {a}] - y[s] for s in subsets(others)]
    return np.mean(terms, axis=0)


def interaction(
    y: Mapping[frozenset, np.ndarray], factors: Sequence[str], a: str, b: str
) -> np.ndarray:
    y = _trim(y)
    others = [f for f in factors if f not in (a, b)]
    terms = [y[s | {a, b}] - y[s | {a}] - y[s | {b}] + y[s] for s in subsets(others)]
    return np.mean(terms, axis=0)


def shapley(v: Callable[[frozenset], float], factors: Sequence[str]) -> dict[str, float]:
    """Exact Shapley values of the set function v over `factors`."""
    cache: dict[frozenset, float] = {}

    def val(s: frozenset) -> float:
        if s not in cache:
            cache[s] = v(s)
        return cache[s]

    phi = dict.fromkeys(factors, 0.0)
    perms = list(permutations(factors))
    for p in perms:
        s: frozenset = frozenset()
        for f in p:
            phi[f] += val(s | {f}) - val(s)
            s = s | {f}
    return {f: x / len(perms) for f, x in phi.items()}


def rms_db(x: np.ndarray, re: np.ndarray) -> float:
    a, b = float(np.sqrt(np.mean(x * x))), float(np.sqrt(np.mean(re * re)))
    return 20 * np.log10(a / b) if a > 0 and b > 0 else float("-inf")


def analyse(
    y: Mapping[frozenset, np.ndarray],
    factors: Sequence[str],
    *,
    score: Callable[[frozenset], float] | None = None,
) -> dict:
    """The study's table: each main effect's and interaction's level (dB re the all-on
    output), the main effects' tone / character split (difference.levels between the
    averaged off and on sides), the 'not separable' flags (an interaction within 6 dB of the
    smaller of its two main effects) and, with `score`, Shapley values."""
    y = _trim(y)
    allon = y[frozenset(factors)]
    out: dict = {"factors": list(factors), "main": {}, "interactions": {}}
    mains = {}
    for a in factors:
        m = main_effect(y, factors, a)
        mains[a] = rms_db(m, allon)
        others = [f for f in factors if f != a]
        on = np.mean([y[s | {a}] for s in subsets(others)], axis=0)
        off = np.mean([y[s] for s in subsets(others)], axis=0)
        out["main"][a] = {"level_db": mains[a], "split": difference.levels(off, on)}
    for a, b in combinations(factors, 2):
        lv = rms_db(interaction(y, factors, a, b), allon)
        out["interactions"][f"{a} x {b}"] = {
            "level_db": lv,
            "not_separable": bool(lv >= min(mains[a], mains[b]) - 6.0),
        }
    if score is not None:
        out["shapley"] = shapley(score, factors)
        out["score_all"] = score(frozenset(factors))
    return out


def character_power(y: Mapping[frozenset, np.ndarray], base: frozenset = frozenset()):
    """A score for Shapley: the power of y[S]'s character part against y[base] (what one
    fixed filter can't explain), relative to y[base]'s power. Linear, so v(base) = 0."""
    y = _trim(y)
    ref = y[base]
    p_ref = float(np.mean(ref * ref))
    cache: dict[frozenset, float] = {}

    def v(s: frozenset) -> float:
        if s == base:
            return 0.0
        if s not in cache:
            d = difference.decompose(ref, y[s])
            e = len(d.h) // 2
            c = d.character[e:-e] if len(d.character) > 2 * e + 10 else d.character
            cache[s] = float(np.mean(c * c)) / p_ref
        return cache[s]

    return v
