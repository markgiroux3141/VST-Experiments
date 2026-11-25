"""Popcorn noise in the Minimoog's transistors (docs/PART_NOISE_PLAN.md: popcorn in the device
where it belongs, a transistor synth): a defective transistor's traps (the bench's
`popcorn_defective`, varimu.part_noise.popcorn) put into one site of the voice at a time, as a
current from the transistor's base to its emitter (the trap's base-current steps), at DAMAGE 1
(the bench's amplitudes), 100, 1000 and 10000.

    uv run --extra listen --extra fast python scripts/moog_popcorn.py [--only ladder sh ...]
        [--damage 1 100 1000 10000] [--seconds 3]

The voice at draft-1x as the app plays it (minimoog_gate_check's partition), a held A2 with the
filter's emphasis up. One pass: a trap's current doesn't depend on the circuit (a control
input drives a Vccs in the transistor's own section). -> reports/part_noise/moog_popcorn/:
- audio/<site>/damage_<N>.wav, loudness-matched (-23 LUFS) with damage_0 (no trap);
- audio/pops_only/<site>_damage_<N>.wav: the run minus damage_0, where the oscillators are
  untouched (a trap off their path); else the pitch is measured instead;
- summary.json: each site's pitch deviation (cents) and pops' level re the note.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import math
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import minimoog_gate_check as gc  # noqa: E402
import minimoog_vcf_study as vs  # noqa: E402

from varimu.circuit import builder, spec  # noqa: E402
from varimu.circuit import ir as irm  # noqa: E402
from varimu.config import CONFIG_DIR  # noqa: E402
from varimu.part_noise import bench, popcorn, rng_for  # noqa: E402
from varimu.sim import fast, io  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SRC = CONFIG_DIR / "circuits" / "minimoog_voice.yaml"
OUT = ROOT / "reports" / "part_noise" / "moog_popcorn"
GM_S = 1e-6
LUFS_TARGET = -23.0
NOTE = 45  # A2
PANEL = {"emphasis": 0.75, "cutoff": 0.35, "amount": 0.3}

# site: (the transistor's part, what a trap there does)
SITES = {
    "ladder": ("Q29", "the ladder's input pair: steps into the filter, rung by its resonance"),
    "vca": ("Q16", "the VCA's input pair: steps into the VCA"),
    "sh": ("Q23_b", "the keyboard's sample and hold: its input transistor's base current"),
    "expo1": ("Q7_o1", "oscillator 1's exponential converter: its base current"),
}


def with_trap(ir: irm.CircuitIR, site: str) -> irm.CircuitIR:
    """A Vccs from the transistor device's base into its emitter (its own nodes, inside any
    base resistance), its control `trap` (a volt is a microamp). Control inputs stay in the
    partition's first part: the Vccs goes in a section of its own there and its current is
    handed to the transistor's part (a sample late); in an oscillator's multi-rate island it
    goes in the transistor's section with `trap` an audio control (the island reads it)."""
    part = SITES[site][0]
    sec = next(
        (x for x in ir.sections
         if any(isinstance(e, irm.Device) and e.name == part for e in x.elements)),
        None,
    )  # fmt: skip
    if sec is None:
        raise KeyError(f"no device {part}")
    dev = next(e for e in sec.elements if isinstance(e, irm.Device) and e.name == part)
    _, b, e = dev.nodes
    trap = (
        irm.Vccs("GTRAP", b, e, "trap", "0", GM_S),
        irm.Resistor("RTRAP", "trap", "0", 1e6),
    )
    island = sec.title.startswith("osc ")
    if island:
        sections = tuple(
            dataclasses.replace(x, elements=(*x.elements, *trap)) if x is sec else x
            for x in ir.sections
        )
    else:
        sections = (*ir.sections, irm.Section("popcorn trap", trap))
    return dataclasses.replace(
        ir,
        sections=sections,
        controls=(*ir.controls, irm.Control("trap", "trap", audio=island)),
    )


def crossings(x: np.ndarray, level: float) -> np.ndarray:
    i = np.nonzero((x[:-1] > level) & (x[1:] <= level))[0]
    return i + (x[i] - level) / (x[i] - x[i + 1])


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--only", nargs="*", default=list(SITES))
    ap.add_argument("--damage", nargs="*", type=float, default=[1.0, 100.0, 1000.0, 10000.0])
    ap.add_argument("--seconds", type=float, default=3.0)
    args = ap.parse_args()
    import pyloudnorm
    import soundfile as sf

    s = spec.load_circuit(SRC)
    base = builder.build_ir(s, spec.resolve(s, PANEL), "linear", events=True)
    base = dataclasses.replace(base, probes=(irm.VoltageProbe("o1_ramp"), irm.VoltageProbe("out")))
    st = dataclasses.replace(
        vs.settings("draft-1x"),
        newton_reltol=gc.VOICE_NEWTON,
        newton_vntol=gc.VOICE_NEWTON,
        partition=gc.VOICE_PARTITION,
        partition_coupling="hold",
        hard_step_iterations=gc.VOICE_HARD_STEP,
    )
    fs = st.sample_rate
    n = int(args.seconds * fs)
    off, on = gc.gate_levels(s, "gate")
    gate = np.full(n, off)
    gate[int(0.2 * fs) : int((args.seconds - 0.4) * fs)] = on
    key = np.full(n, gc.key_volts(s, NOTE))
    irs = {site: with_trap(base, site) for site in args.only}
    # One trap realization per site (the same traps at every DAMAGE: a worse transistor).
    traps = {
        site: popcorn.burst_current(bench.TRAPS_DEFECTIVE, n, fs, rng_for(1, f"popcorn:{site}"))
        for site in args.only
    }

    def run(item):
        site, damage = item
        ctl = {"key": key, "gate": gate, "trap": traps[site] * damage / GM_S}
        return item, fast.run_transient(irs[site], np.zeros(n), settings=st, controls=ctl).vectors

    items = [(site, d) for site in args.only for d in [0.0, *args.damage]]
    t0 = time.perf_counter()
    with ThreadPoolExecutor(2) as pool:
        res = dict(pool.map(run, items))
    print(f"renders: {time.perf_counter() - t0:.0f} s", flush=True)

    meter = pyloudnorm.Meter(fs)

    def write(path: Path, y: np.ndarray) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        peak = float(np.max(np.abs(y)))
        if peak > 0.99:
            y = y * (0.99 / peak)
        sf.write(path, y.astype(np.float32), fs, subtype="FLOAT")

    full_scale = io.full_scale(st, s)[1]
    summary = {"note": NOTE, "panel": PANEL, "traps": popcorn.TRAP_SOURCE, "sites": {}}
    a, b = int(0.4 * fs), int((args.seconds - 0.4) * fs)
    for site in args.only:
        ref = res[(site, 0.0)]
        prog = ref["v(out)"]
        rms = float(np.sqrt(np.mean(prog[a:b] ** 2)))
        t_ref = crossings(ref["v(o1_ramp)"][a:b], 2.5)
        entry = {"what": SITES[site][1], "transistor": SITES[site][0], "damage": {}}
        osc_same = True
        diffs = {}
        for d in args.damage:
            v = res[(site, d)]
            t = crossings(v["v(o1_ramp)"][a:b], 2.5)
            m = min(len(t), len(t_ref))
            per, per_ref = np.diff(t[:m]), np.diff(t_ref[:m])
            cents = 1200 * np.log2(per / per_ref)  # cycle by cycle against no trap
            same = m > 2 and np.max(np.abs(t[:m] - t_ref[:m])) < 1e-6
            osc_same &= bool(same)
            diffs[d] = v["v(out)"] - prog
            entry["damage"][f"{d:g}"] = {
                "pitch_dev_cents_max": float(np.max(np.abs(cents))) if m > 2 else None,
                "pitch_dev_cents_rms": float(np.sqrt(np.mean(cents**2))) if m > 2 else None,
                "oscillator_untouched": bool(same),
                "pops_re_note_db": 20
                * math.log10(max(float(np.sqrt(np.mean(diffs[d][a:b] ** 2))), 1e-30) / rms),
            }
        for d in [0.0, *args.damage]:
            y = res[(site, d)]["v(out)"] / full_scale
            write(OUT / "audio" / site / f"damage_{d:g}.wav",
                  y * 10 ** ((LUFS_TARGET - meter.integrated_loudness(y)) / 20))  # fmt: skip
        if osc_same:
            top = max(float(np.max(np.abs(x))) for x in diffs.values())
            g = 10 ** (-1 / 20) / max(top, 1e-30)
            for d in args.damage:
                write(OUT / "audio" / "pops_only" / f"{site}_damage_{d:g}.wav", diffs[d] * g)
        summary["sites"][site] = entry
        print(site, json.dumps(entry["damage"]))
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
