"""A channel of the Ampex 300-4 aligned as the 351's manual aligns the 351
(docs/PERIOD_GEAR_BACKLOG.md, PG1, MT5; varimu.measure.tape_align, unchanged): the steps on
config/circuits/ampex_300_4_channel.yaml (the 351 on the deck's tape, SCOTCH202@1, and its
70 mil four-track head, 15 ips), all but 3b (the 7-1/2 ips record EQ: the deck runs at 15).

    uv run --extra fast python scripts/align_300_4.py [--refresh]
-> reports/multitrack/deck/channel_alignment.{json,png}; then
   `uv run python scripts/make_ampex_300_4.py` puts it on the deck's four channels and
   scripts/ampex_300_4_trim.py trims each channel's BIAS ADJUST on the deck.
Cached (cache/tape/align_300_4_<key>.json, tape_align's key on this circuit): ~1 hour cold.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import math
import sys
import time

import numpy as np

from varimu.config import REPO_ROOT
from varimu.measure import tape_align as ta

OUT = REPO_ROOT / "reports" / "multitrack" / "deck"
CIRCUIT = "ampex_300_4_channel"


def note(m: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)


def record_level(b: ta.Bench, o: dict) -> dict:
    """Step 4 (tape_align.record_level), where RECORD LEVEL may run out first: on SCOTCH202
    (Hc 315 Oe against 111's 270) the 351's record gain at its -10 dBm bridging input doesn't
    reach 1% THD at 400 Hz. Then RECORD LEVEL is fully up and the shortfall (dB more input
    for 1%, from the last two points' slope in log-log) is reported: a studio drove the deck
    that much harder (a print's drive)."""
    try:
        return {**ta.record_level(b, o, note), "short_db": 0.0}
    except RuntimeError as err:
        note(f"record level: {err}")
    levels = (0.9, 1.0)
    x = ta.tone(b, [400.0], 0.0)
    runs = ta.run_many(b, [({**o, "record_level": lv}, x) for lv in levels], note)
    th = np.array([ta.thd(ta.window(b, v["v(out)"]), b.fs, 400.0)[0] for v in runs])
    if th[-1] >= 0.01:
        raise RuntimeError(f"record level: 1% THD inside the pot's range after all ({th})")
    # THD against the record current (RECORD LEVEL's taper aside: between the two points).
    slope = math.log(th[1] / th[0]) / math.log(levels[1] / levels[0])
    short_db = 20 * math.log10(0.01 / th[1]) / slope
    note(f"record level: fully up, {th[1] * 100:.3f}% THD; {short_db:.2f} dB short of 1%")
    return {
        "record_level": 1.0,
        "short_db": short_db,
        "sweep_levels": list(levels),
        "sweep_thd_pct": [float(t * 100) for t in th],
    }


def align(b: ta.Bench, partial) -> ta.Alignment:
    """tape_align.align's steps 1-5 without 3b, in its order; each step saved to `partial`
    as it ends (a rerun resumes after the last)."""
    saved = json.loads(partial.read_text()) if partial.exists() else {}
    o: dict = dict(saved.get("o", {}))
    steps: dict = dict(saved.get("steps", {}))
    t0 = time.perf_counter()

    def step(name: str, key: str, fn) -> None:
        if name not in steps:
            steps[name] = fn()
            partial.write_text(json.dumps({"o": {**o, key: steps[name][key]}, "steps": steps},
                                          indent=1, default=float))  # fmt: skip
        o[key] = steps[name][key]

    step("playback_eq", "rep_eq_hi", lambda: ta.playback_eq(b, o, note))
    o.setdefault("record_level", 0.85)
    o.setdefault("playback_level", 0.3)
    step("bias", "bias_adjust_f", lambda: ta.bias(b, o, note))
    step("record_eq", "rec_eq_hi_f", lambda: ta.record_eq(b, o, note))
    step("record_level", "record_level", lambda: record_level(b, o))
    step("playback_level", "playback_level", lambda: ta.playback_level(b, o, note))
    steps["check"] = ta.check(b, o, note)
    steps["wall_s"] = steps.get("wall_s", 0.0) + time.perf_counter() - t0
    return ta.Alignment(dict(o), steps, ta._key(b, None))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--refresh", action="store_true")
    a = ap.parse_args()
    ta.CIRCUIT = CIRCUIT
    b = ta.Bench.load()
    key = ta._key(b, None)
    cache = ta.ALIGN_DIR / f"align_300_4_{key}.json"
    if cache.exists() and not a.refresh:
        al = ta.Alignment(**json.loads(cache.read_text()))
    else:
        al = align(b, ta.ALIGN_DIR / f"align_300_4_{key}.partial.json")
        ta.ALIGN_DIR.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(dataclasses.asdict(al), indent=1, default=float))
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "channel_alignment.json").write_text(
        json.dumps(dataclasses.asdict(al), indent=1, default=float)
    )
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    from align_351 import plot

    plot(al, OUT / "channel_alignment.png")
    note(f"settings: {json.dumps(al.overrides)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
