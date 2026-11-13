"""AM14's factorial analysis on a synthetic system with known effects."""

from __future__ import annotations

import numpy as np

from varimu.magic import factorial


def test_main_effects_and_interaction_are_recovered():
    rng = np.random.default_rng(1)
    x = rng.standard_normal(20000)
    f, g, h = np.tanh(x), x**2 - 1, np.sin(3 * x)
    y = {}
    for s in factorial.subsets(["a", "b"]):
        a, b = float("a" in s), float("b" in s)
        y[s] = x + a * f + b * g + a * b * h
    # The main effect of a averages b's two settings: f + h / 2.
    ma = factorial.main_effect(y, ["a", "b"], "a")
    assert np.sqrt(np.mean((ma - (f + h / 2)) ** 2)) / np.std(f) < 1e-4  # -80 dB
    ab = factorial.interaction(y, ["a", "b"], "a", "b")
    assert np.sqrt(np.mean((ab - h) ** 2)) / np.std(h) < 1e-4


def test_shapley_sums_to_the_all_on_score():
    vals = {frozenset(): 0.0, frozenset("a"): 1.0, frozenset("b"): 2.0, frozenset("ab"): 5.0}
    phi = factorial.shapley(lambda s: vals[s], ["a", "b"])
    assert abs(sum(phi.values()) - 5.0) < 1e-12
    assert abs(phi["a"] - 2.0) < 1e-12  # (1 + (5 - 2)) / 2
