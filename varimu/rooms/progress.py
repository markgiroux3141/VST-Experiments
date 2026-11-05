"""Progress lines for a room render (varimu.rooms.scene.render's `log`), with an ETA per step.

A step is a known list of items, each with a work measure from the render's parameters (a
ray trace's rays x mics, a wave run's cells x steps, a convolution's n log n, ...). Each item
logs a line as it starts: what it is, its estimate, and the step's time left. The estimate is
the item's work times a rate in seconds per unit of work: the last renders'
(cache/rooms/step_rates.json, per step key: a backend or a room's size class goes in the key
where it changes the rate) blended with this run's items so far (`Step.rate`), this run's
alone without a history, else none ("est. after the first"). A step saves this run's rate
when it ends. Items expected to take under `QUICK_S` are logged at most once a second (and
the first and last), so the slow steps' lines stay on screen.
"""

from __future__ import annotations

import json
import os
import threading
import time
from collections.abc import Callable
from pathlib import Path

from varimu.config import REPO_ROOT

RATES = REPO_ROOT / "cache" / "rooms" / "step_rates.json"
QUICK_S = 1.0  # items estimated under this get a line at most once a second


def fmt_s(s: float) -> str:
    """A duration for a log line: 0.4 s, 12 s, 2 min 05 s, 1 h 03 min."""
    if s < 10:
        return f"{s:.1f} s"
    if s < 60:
        return f"{s:.0f} s"
    if s < 3600:
        return f"{int(s // 60)} min {int(s % 60):02d} s"
    return f"{int(s // 3600)} h {int(s % 3600 // 60):02d} min"


def _load_rates(path: Path) -> dict[str, float]:
    try:
        return {k: float(v) for k, v in json.loads(path.read_text(encoding="utf-8")).items()}
    except (OSError, ValueError, AttributeError):
        return {}


def _save_rate(path: Path, key: str, rate: float) -> None:
    rates = _load_rates(path)
    rates[key] = rate
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(f".{os.getpid()}.tmp")
        tmp.write_text(json.dumps(rates, indent=1, sort_keys=True), encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        pass  # an ETA is a convenience: never fail a render over it


class Step:
    """One step's items (the module docstring). `log` None: silent, nothing timed or saved.

    step = Step(log, "rays", key, works=[...])
    for k in range(n):
        step.start(k, "source 2, 50,000 rays")
        ...
        step.done()  # optional: when other work follows before the next start
    step.end()
    """

    def __init__(
        self,
        log: Callable[[str], None] | None,
        name: str,
        key: str,
        works: list[float],
        rates_path: Path = RATES,
    ):
        self.log, self.name, self.key = log, name, key
        self.works = [max(float(w), 1e-30) for w in works]
        self.rates_path = rates_path
        self.prior = _load_rates(rates_path).get(key) if log else None
        self.done_work = 0.0
        self.done_s = 0.0
        self.t_item: float | None = None
        self.k: int | None = None
        self.t_line = -1e9

    def rate(self) -> float | None:
        """Seconds per unit of work: the last renders' and this run's items blended, the
        last renders' counting as half the step's work (one slow item, a source's first
        mic building its images, doesn't swing the ETA), else this run's alone."""
        if self.prior is not None:
            w = 0.5 * sum(self.works)
            return (self.prior * w + self.done_s) / (w + self.done_work)
        if self.done_work > 0 and self.done_s > 0:
            return self.done_s / self.done_work
        return None

    def done(self) -> None:
        """The open item ends (start() and end() also close it)."""
        if self.t_item is not None and self.k is not None:
            self.done_s += time.perf_counter() - self.t_item
            self.done_work += self.works[self.k]
        self.t_item = self.k = None

    def start(self, k: int, what: str) -> None:
        """Item k starts (the previous one, if open, ends)."""
        if not self.log:
            return
        self.done()
        n = len(self.works)
        r = self.rate()
        now = time.perf_counter()
        # quick items only now and then: the first, the last, one a second, any >= 1 s
        quick = r is not None and self.works[k] * r < QUICK_S
        if not quick or k in (0, n - 1) or now - self.t_line >= QUICK_S:
            if r is None:
                eta = "est. after the first"
            else:
                left = sum(self.works[k:]) * r
                eta = f"est. {fmt_s(self.works[k] * r)}"
                if k + 1 < n:
                    eta += f", {self.name} ~{fmt_s(left)} left"
            self.log(f"{self.name} {k + 1}/{n}: {what} ({eta})")
            self.t_line = now
        self.k, self.t_item = k, now

    def end(self, note: str = "") -> float:
        """The step's time (its items', so steps whose items interleave each count their
        own); its rate saved for the next renders."""
        if not self.log:
            return 0.0
        self.done()
        if self.done_work > 0 and self.done_s > 0:  # this run's own (not blended)
            _save_rate(self.rates_path, self.key, self.done_s / self.done_work)
        self.log(f"{self.name}: done in {fmt_s(self.done_s)}{note}")
        return self.done_s


class Countdown:
    """A fraction's ETA from its own pace (the chains' prints: the bar's mean), logged at
    most every `every_s` seconds."""

    def __init__(self, log: Callable[[str], None] | None, name: str, every_s: float = 5.0):
        self.log, self.name, self.every_s = log, name, every_s
        self.t0 = time.perf_counter()
        self.t_last = self.t0
        self.lock = threading.Lock()  # called from the prints' threads

    def update(self, frac: float) -> None:
        if not self.log:
            return
        now = time.perf_counter()
        with self.lock:
            if now - self.t_last < self.every_s or frac <= 0:
                return
            self.t_last = now
        el = now - self.t0
        left = el / frac * (1 - frac) if frac < 1 else 0.0
        self.log(f"{self.name}: {frac * 100:.0f}% in {fmt_s(el)}, ~{fmt_s(left)} left")
