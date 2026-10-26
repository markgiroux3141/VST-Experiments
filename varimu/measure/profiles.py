"""Per-circuit profiles (device builder B2): which measurements, setup and checks apply.

A profile names a circuit file (config/circuits/<name>.yaml) and the suite that
measures it: run(name, genome, clips=..., settings=..., log=...) -> report, with
report["plausible"] and report["checks"] (its plausibility screen: the generic
checks of varimu.measure.generic and the circuit's own).

- fairchild_670 (compressor): varimu.measure.suite, unchanged: the manual's setup
  procedures, compression curves, timing, response under gain reduction, IMD,
  thump, program clips; its checks are varimu.measure.plausibility's.
- pultec_eqp1a (equalizer): varimu.measure.eq_suite: response at every published
  family's extreme against the curves, THD vs level, the generic screen.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Profile:
    circuit: str
    kind: str  # "compressor" | "equalizer"
    run: Callable[..., dict[str, Any]]


def _run_670(*args, **kwargs):
    from varimu.measure import suite

    return suite.run(*args, **kwargs)


def _run_eq(*args, **kwargs):
    from varimu.measure import eq_suite

    return eq_suite.run(*args, **kwargs)


PROFILES = {
    "fairchild_670": Profile("fairchild_670", "compressor", _run_670),
    "pultec_eqp1a": Profile("pultec_eqp1a", "equalizer", _run_eq),
}


def profile(circuit: str) -> Profile:
    try:
        return PROFILES[circuit]
    except KeyError:
        raise KeyError(f"no measurement profile for {circuit!r} ({', '.join(PROFILES)})") from None
