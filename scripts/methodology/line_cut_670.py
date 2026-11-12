"""W1's first done-when: the 670's supply cut at the draft, as link lines against
extrapolate (METHODOLOGY_REVIEW.md W1; CIRCUIT_SIM_PLAN.md M8: -103 dB from the one solve).

The draft puts the supplies (power, bias, the idle channel 2) on a second thread, coupled at
the rails they share with the audio part, extrapolated a sample. Each such rail with a
capacitor to ground on it can be cut as a link line instead (`cut:ELEMENT` entries; the
rails without one stay extrapolated). The arpeggio clip through the draft, one solve,
extrapolated and with lines; the error of `out` re its level and the CV's.

    uv run --extra fast --extra listen python scripts/methodology/line_cut_670.py [--seconds 3]
"""

from __future__ import annotations

import argparse
from dataclasses import replace
from pathlib import Path

import numpy as np

from varimu.circuit import netlist
from varimu.circuit.ir import Capacitor
from varimu.sim import fast, io

CLIP = "data/clips/Arpeggio04b_120_m_D#_16b.WAV"


def shared_rails(ir, titles):
    """The nodes the named sections share with the rest, and each one's capacitors to
    ground (name, farads, side)."""
    named = [s for s in ir.sections if s.title in titles]
    rest = [s for s in ir.sections if s.title not in titles]

    def nodes(secs):
        out = set()
        for s in secs:
            for e in s.elements:
                for n in getattr(e, "nodes", None) or [
                    getattr(e, k) for k in ("a", "b", "pos", "neg") if hasattr(e, k)
                ]:
                    out.add(n)
        return out - {"0"}

    both = nodes(named) & nodes(rest)
    rails = {}
    for n in sorted(both):
        caps = []
        for side, secs in (("supply", named), ("audio", rest)):
            for s in secs:
                for e in s.elements:
                    if isinstance(e, Capacitor) and {e.a, e.b} == {n, "0"}:
                        caps.append((e.name, e.c_f, side))
        rails[n] = caps
    return rails


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=float, default=3.0)
    ap.add_argument("--offset", type=float, default=1.0)
    args = ap.parse_args()
    s = io.TransientSettings.from_sim_settings(engine="circuitsim", quality="draft")
    p = netlist.resolve()
    ir = netlist.build_ir(p, cores=s.cores)
    titles = list(fast.partition_sections(ir, s))
    rails = shared_rails(ir, [t for t in titles if t != io.GROUP_BREAK])
    print("the rails the split shares, and their capacitors to ground:")
    cuts = []
    for n, caps in rails.items():
        print(f"  {n}: {caps}")
        if caps:
            biggest = max(caps, key=lambda c: c[1])
            cuts.append(biggest[0])
    fs = s.sample_rate
    x = io.load_audio(Path(CLIP), fs)
    a = int(args.offset * fs)
    x = x[a : a + int(args.seconds * fs)] * s.full_scale_volts_peak

    base = fast.partition_sections

    def run(entries, coupling="extrapolate"):
        fast.partition_sections = lambda ir_, s_: list(entries)
        try:
            st = replace(s, partition_coupling=coupling)
            r = fast.run_transient(ir, x, settings=st).vectors
        finally:
            fast.partition_sections = base
        return r

    one = run([])
    y1 = one["v(out)"]
    level = np.sqrt(np.mean(y1**2))

    def report(name, r):
        y = r["v(out)"]
        e = np.sqrt(np.mean((y - y1) ** 2))
        cv = np.max(np.abs(r["v(cv)"] - one["v(cv)"])) if "v(cv)" in one else float("nan")
        print(f"  {name:40s} {20 * np.log10(e / level):7.1f} dB re out, CV max {cv:.2e} V")

    print(f"\n{args.seconds} s of the arpeggio at the draft, against the one solve:")
    report("supplies extrapolated (today)", run(titles))
    report("supplies held", run(titles, "hold"))
    report(f"lines at {', '.join(cuts)}", run(titles + [f"cut:{c}" for c in cuts]))


if __name__ == "__main__":
    main()
