"""A room render's progress lines and their ETAs (varimu.rooms.progress)."""

from __future__ import annotations

import json

from varimu.rooms.progress import Countdown, Step, fmt_s


def test_fmt_s():
    assert fmt_s(0.42) == "0.4 s"
    assert fmt_s(42) == "42 s"
    assert fmt_s(125) == "2 min 05 s"
    assert fmt_s(3780) == "1 h 03 min"


def test_eta_from_the_last_render_then_this_one(tmp_path):
    rates = tmp_path / "rates.json"
    rates.write_text(json.dumps({"wave:gpu": 2.0}))
    lines: list[str] = []
    step = Step(lines.append, "wave solver", "wave:gpu", [1.0, 3.0], rates_path=rates)
    step.start(0, "source 1")
    # before any item is done: the saved rate, 2 s per unit
    assert lines[-1] == "wave solver 1/2: source 1 (est. 2.0 s, wave solver ~8.0 s left)"
    step.done_s, step.done_work, step.t_item, step.k = 0.5, 1.0, None, None  # 0.5 s per unit
    step.start(1, "source 2")
    # blended: the saved rate weighs half the step's work, 2 units: (2 x 2 + 0.5) / 3 = 1.5
    assert lines[-1] == "wave solver 2/2: source 2 (est. 4.5 s)"
    step.end()
    assert lines[-1].startswith("wave solver: done in ")
    assert json.loads(rates.read_text())["wave:gpu"] > 0


def test_no_history_and_silent(tmp_path):
    lines: list[str] = []
    step = Step(lines.append, "rays", "rays:cpu", [1.0], rates_path=tmp_path / "none.json")
    step.start(0, "source 1")
    assert lines == ["rays 1/1: source 1 (est. after the first)"]
    quiet = Step(None, "rays", "rays:cpu", [1.0], rates_path=tmp_path / "q.json")
    quiet.start(0, "x")
    quiet.done()
    assert quiet.end() == 0.0
    assert not (tmp_path / "q.json").exists()


def test_quick_items_are_logged_now_and_then(tmp_path):
    rates = tmp_path / "rates.json"
    rates.write_text(json.dumps({"conv": 0.01}))  # 10 ms an item
    lines: list[str] = []
    step = Step(lines.append, "convolution", "conv", [1.0] * 24, rates_path=rates)
    for k in range(24):
        step.start(k, f"item {k + 1}")
    # the first and the last (24 items within a second)
    assert [x.split(":")[0] for x in lines] == ["convolution 1/24", "convolution 24/24"]


def test_countdown_throttles():
    lines: list[str] = []
    c = Countdown(lines.append, "chains", every_s=0.0)
    c.update(0.0)
    assert lines == []
    c.update(0.5)
    assert lines[-1].startswith("chains: 50% in ")
