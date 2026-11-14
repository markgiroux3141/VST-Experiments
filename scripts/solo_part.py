"""AM13 step 1, solo a part (docs/ANALOG_MAGIC_FABLE.md; varimu.magic.solo): every resistor,
capacitor and inductor of a circuit ranked by how loud the output's sensitivity to its value is
on a program, with the value's source text so provisional values stand out.

-> reports/magic/solo/<circuit>/: summary.json (the ranking), ranking.md (the table), the top
ten solos as WAVs at -23 LUFS (audio/solo_NN_<part>.wav) and "what if" pairs: the output as
it is and with the part 20 % up to first order (y + ln(1.2) s), loudness-matched together
(audio/whatif_NN_<part>__{as_is,up20}.wav).

  uv run --extra fast --extra listen python scripts/solo_part.py --circuit pultec_eqp1a
      [--part NAME ...] [--clip "Dry Guitar.wav"] [--seconds 5] [--set k=v ...]
"""

from __future__ import annotations

import argparse
import json
import sys
import time

import numpy as np

from varimu.config import REPO_ROOT
from varimu.magic import render, solo
from varimu.sim.io import load_audio, write_audio

OUT = REPO_ROOT / "reports" / "magic" / "solo"
PROBES = {"triode_stage": "o"}


def program(clip: str, seconds: float, fs: int) -> np.ndarray:
    x = load_audio(REPO_ROOT / "data" / "clips" / clip, fs)[: int(seconds * fs)]
    x = x * 10 ** (-18 / 20) / (np.std(x) + 1e-30)
    f = int(0.02 * fs)
    x[:f] *= np.linspace(0, 1, f)
    return x


def parse_set(items):
    out = {}
    for it in items or []:
        k, v = it.split("=", 1)
        try:
            out[k] = float(v)
        except ValueError:
            out[k] = v
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--circuit", required=True)
    ap.add_argument("--part", nargs="*", default=None)
    ap.add_argument("--clip", default="Dry Guitar.wav")
    ap.add_argument("--seconds", type=float, default=5.0)
    ap.add_argument("--set", nargs="*", default=[])
    ap.add_argument("--jobs", type=int, default=None)
    a = ap.parse_args()
    fs = render.sample_rate()
    x = program(a.clip, a.seconds, fs)
    ov = parse_set(a.set)
    probe = PROBES.get(a.circuit, "out")
    ir, v_in, v_out = solo.build(a.circuit, ov)
    names = a.part if a.part else list(solo.elements(ir))
    print(f"{a.circuit}: {len(names)} parts x 4 runs of {a.seconds:g} s", flush=True)
    t0 = time.time()
    rows = solo.rank(ir, x, v_in, v_out, probe=probe, names=names, workers=a.jobs)
    print(f"  ranked in {(time.time() - t0) / 60:.1f} min", flush=True)
    srcs = solo.sources(a.circuit)
    for r in rows:
        r["key"], r["source"] = solo.source_for(r["name"], srcs)
        r["provisional"] = r["source"].startswith("provisional")

    tag = "__".join(f"{k}={v:g}" if isinstance(v, float) else f"{k}={v}" for k, v in ov.items())
    out = OUT / (a.circuit + (f"__{tag}" if tag else ""))
    (out / "audio").mkdir(parents=True, exist_ok=True)
    from varimu.listen.matching import match_loudness

    for i, r in enumerate(rows[:10], 1):
        if "s" not in r:
            continue
        s, y = r["s"], r["y"]
        (sm,), _ = match_loudness([s], fs, target=-23.0)
        write_audio(out / "audio" / f"solo_{i:02d}_{r['name']}.wav", sm, fs)
        up = y + np.log(1.2) * s
        m, _ = match_loudness([y, up], fs, target=-23.0)
        write_audio(out / "audio" / f"whatif_{i:02d}_{r['name']}__as_is.wav", m[0], fs)
        write_audio(out / "audio" / f"whatif_{i:02d}_{r['name']}__up20.wav", m[1], fs)

    summary = {
        "circuit": a.circuit,
        "overrides": ov,
        "clip": a.clip,
        "seconds": a.seconds,
        "probe": probe,
        "deltas": list(solo.DELTAS),
        "flag_db": solo.FLAG_DB,
        "parts": json.loads(solo.table_json(rows)),
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=1, default=float))
    lines = [
        f"# {a.circuit}: parts by solo level ({a.clip}, {a.seconds:g} s)",
        "",
        "| # | part | value | solo (dB re out) | check | source |",
        "|---|---|---|---|---|---|",
    ]
    for i, r in enumerate(rows, 1):
        flag = " **flag**" if r["flag"] else ""
        src = r["source"].replace("|", "/")
        src = src if len(src) < 90 else src[:87] + "..."
        lines.append(
            f"| {i} | {r['name']} | {r['value']:.3g} | {r['level_db']:.1f} |"
            f" {r['check_db']:.0f}{flag} | {src} |"
        )
    (out / "ranking.md").write_text("\n".join(lines) + "\n")
    for r in rows[:15]:
        print(f"  {r['name']:>14} {r['level_db']:7.1f} dB  {r['source'][:60]}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
