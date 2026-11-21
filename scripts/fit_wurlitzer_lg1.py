"""LG-1, the 200A's LED / LDR (Wurlitzer 142312, type unpublished), fitted to the Pie-finger
set's VIBRATO full (docs/WURLITZER_PLAN.md, WZ4's vibrato).

    uv run --extra fast python scripts/fit_wurlitzer_lg1.py [--write] [--knob-law]

The stand-in so far was the VTL5C2 Vactrol (as the Rhodes Suitcase's) with R17 fitted to the
recorded depth alone. Its cell runs at 0.4-1 kOhm there, nothing beside the 50K VIBRATO pot,
so the knob did nothing until fully clockwise, where the preamp's gain (1 + R10 / Z, Z from
the feedback node x to ground) jumped +23 dB: the recording changes -1 dB.

The model: the VTL5C2@2's LED and cell with the cell's conductance divided by k (a CdS cell's
conductance scales with its electrodes' geometry) and its dynamics s times faster (the steady
state unchanged: `cell_params`). With the stand-in's own speed the cell can't darken within a
5.7 Hz cycle, so its resistance swings ~3x, too little for the recording's depth at its
level. Three unknowns, k, s and R17 (`vib_trim`), and three figures at VIBRATO full on a steady
tone through the stock circuit (scripts/wurlitzer_amp_study.py's measure):

- the depth (dB peak to peak) and the envelope's shape (its 2nd harmonic re its fundamental,
  weighted loosely): the octave-4 VIBRATO-full notes, as WZ2 measured them;
- the level change against VIBRATO off: the median over every VIBRATO-full note of its mean
  envelope (0.3-1.0 s from the onset) less the same key's plain long note (low velocity: both
  struck by hand, so per note it scatters by +-1 dB; the median is the figure).

--write saves the component LG1_200A's next version and sets the stock circuit's `lg1` and
`vib_trim` (rerun scripts/make_wurlitzer_200a_live.py and scripts/export_app_fixtures.py).
--knob-law prints the depth and level per VIBRATO position with the fitted cell.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import numpy as np
import yaml
from scipy import optimize

sys.path.insert(0, str(Path(__file__).resolve().parent))

import wurlitzer_amp_study as amp  # noqa: E402

from varimu.circuit import builder  # noqa: E402
from varimu.devices import library, versions  # noqa: E402
from varimu.devices.opto import Optocoupler  # noqa: E402

BASE = "VTL5C2@2"
NAME = "LG1_200A"
F0 = 330.0
SECONDS = 3.0
NOTES = {n: i for i, n in enumerate("C C# D D# E F F# G G# A A# B".split())}


def note_hz(name: str) -> float:
    m = re.fullmatch(r"([A-G]#?)(\d)", name)
    semis = NOTES[m.group(1)] + 12 * (int(m.group(2)) + 1) - 69
    return 440.0 * 2 ** (semis / 12) * 2 ** (5 / 1200)  # the set is ~5 cents sharp (WZ0)


def cell_params(cell: dict, k: float, s: float) -> dict:
    """The cell's conductance divided by k and its dynamics s times faster: with g' = g / k and
    t' = t / s, dg/dt = a L - g / tau0 - g^2 / kappa becomes a' = a s / k, tau0' = tau0 / s,
    kappa' = kappa / (k s) (the steady state depends on k only)."""
    return {
        "gen_s_per_s_a": cell["gen_s_per_s_a"] * s / k,
        "tau0_s": cell["tau0_s"] / s,
        "kappa_s_s": cell["kappa_s_s"] / (k * s),
        "g_dark_s": cell["g_dark_s"] / k,
    }


def scaled(model: Optocoupler, k: float, s: float = 1.0) -> Optocoupler:
    from dataclasses import replace

    c = cell_params(
        {
            "gen_s_per_s_a": model.gen_s_per_s_a,
            "tau0_s": model.tau0_s,
            "kappa_s_s": model.kappa_s_s,
            "g_dark_s": model.g_dark_s,
        },
        k,
        s,
    )
    return replace(model, **c)


class Cell:
    """builder.load_device with the stand-in's cell scaled by k and sped up by s (no version
    saved per try)."""

    def __init__(self):
        self.k = 1.0
        self.s = 1.0
        self._load = builder.load_device

    def __enter__(self):
        def load(ref, *a, **kw):
            m = self._load(ref, *a, **kw)
            return scaled(m, self.k, self.s) if ref == BASE else m

        builder.load_device = load
        return self

    def __exit__(self, *exc):
        builder.load_device = self._load


def level_reference() -> dict:
    """VIBRATO full against the same key's plain note (low velocity): the mean envelope over
    0.3-1.0 s from the onset, per note; the median and quartiles."""
    import soundfile as sf

    root = amp.PIE_FINGER
    rows = []
    for p in sorted((root / "Vibrato notes" / "vibrato (full), low vel").glob("*.wav")):
        name = p.stem.split("-")[-1]
        plain = sorted((root / "Long notes" / "Low vel").glob(f"*-{name}.wav"))
        if not plain:
            continue
        f0 = note_hz(name)
        lv = []
        for q in (plain[0], p):
            y, fs = sf.read(q)
            y = y.mean(axis=1) if y.ndim > 1 else y
            on = int(np.argmax(np.abs(y) > 0.1 * np.max(np.abs(y))))
            e = amp.envelope_db(y[on:], f0, fs)
            lv.append(float(np.mean(e[int(0.3 * fs) : int(1.0 * fs)])))
        rows.append(lv[1] - lv[0])
    d = np.array(rows)
    return {
        "level_db": float(np.median(d)),
        "quartiles_db": [float(np.percentile(d, 25)), float(np.percentile(d, 75))],
        "notes": int(d.size),
    }


def measure(vibrato: float, trim: float | None = None) -> dict:
    n = int(SECONDS * amp.FS)
    t = np.arange(n) / amp.FS
    # the base cell, scaled by Cell (whatever LG-1 version the circuit pins now)
    sets = {"vibrato": vibrato, "lg1": BASE} | ({} if trim is None else {"vib_trim": trim})
    v = amp.render(sets, 0.2 * np.sin(2 * np.pi * F0 * t))
    e = amp.envelope_db(v["out"], F0, amp.FS)[int(1.0 * amp.FS) : -int(0.2 * amp.FS)]
    st = amp.envelope_stats(v["out"], F0, amp.FS, 1.0)
    g = v["lgs"][int(1.0 * amp.FS) :] if "lgs" in v else None
    return st | {"level_db": float(np.mean(e)), "lgs": g}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--knob-law", action="store_true")
    ap.add_argument("--k", type=float, help="skip the fit: this cell scale")
    ap.add_argument("--speed", type=float, default=1.0, help="skip the fit: this cell speed")
    ap.add_argument("--trim", type=float, help="skip the fit: this vib_trim")
    a = ap.parse_args()
    if "lgs" not in amp.PROBES:
        amp.PROBES = (*amp.PROBES, "lgs")

    depth_ref = amp.vibrato_reference()
    level_ref = level_reference()
    print(
        f"Pie-finger: depth {depth_ref['depth_db_pp']:.2f} dB p-p (octave 4, {depth_ref['notes']}"
        f" notes), envelope H2 {depth_ref['h2_db']:.1f} dB; level {level_ref['level_db']:+.2f} dB"
        f" (quartiles {level_ref['quartiles_db'][0]:+.2f} / {level_ref['quartiles_db'][1]:+.2f},"
        f" {level_ref['notes']} notes)",
        flush=True,
    )
    off = measure(0.0)["level_db"]
    cell = Cell()

    def evaluate(x):
        cell.k, cell.s, trim = float(np.exp(x[0])), float(np.exp(x[1])), float(x[2])
        with cell:
            m = measure(1.0, trim)
        r = np.array(
            [
                (m["depth_db_pp"] - depth_ref["depth_db_pp"]) / 0.3,
                (m["level_db"] - off - level_ref["level_db"]) / 0.3,
                (m["h2_db"] - depth_ref["h2_db"]) / 2.0,  # the envelope's shape, loosely
            ]
        )
        print(
            f"  k {cell.k:7.2f}, speed {cell.s:6.2f}, vib_trim {trim:.4f}: depth"
            f" {m['depth_db_pp']:5.2f} dB p-p, level {m['level_db'] - off:+6.2f} dB, H2"
            f" {m['h2_db']:6.1f} dB",
            flush=True,
        )
        return r

    if a.k is not None:
        k, s, trim = a.k, a.speed, a.trim
    else:
        # a coarse look (k sets the level, the speed the swing, R17 the brightness), then
        # least squares
        best = None
        for k0 in (10.0, 30.0):
            for s0 in (1.0, 4.0, 12.0):
                for t0 in (0.1, 0.4):
                    r = evaluate([np.log(k0), np.log(s0), t0])
                    if best is None or np.sum(r * r) < best[0]:
                        best = (float(np.sum(r * r)), k0, s0, t0)
        sol = optimize.least_squares(
            evaluate,
            [np.log(best[1]), np.log(best[2]), best[3]],
            bounds=([np.log(1.0), np.log(0.3), 0.0], [np.log(300.0), np.log(100.0), 1.0]),
            diff_step=[0.03, 0.03, 0.03],
            xtol=1e-3,
            max_nfev=40,
        )
        k, s, trim = float(np.exp(sol.x[0])), float(np.exp(sol.x[1])), float(sol.x[2])
    cell.k, cell.s = k, s
    with cell:
        m = measure(1.0, trim)
    g = m["lgs"] * 1e-6  # the state node: 1 uS per volt (the scaled model's g)
    print(
        f"fit: k {k:.3f}, speed {s:.3f}, vib_trim {trim:.4f} (R17 {trim * 4700:.0f} ohm): depth"
        f" {m['depth_db_pp']:.2f} dB p-p, level {m['level_db'] - off:+.2f} dB, H2 {m['h2_db']:.1f}"
        f" dB, rate {m['rate_hz']:.3f} Hz; cell {1 / g.max():,.0f}-{1 / g.min():,.0f} ohm"
    )

    if a.knob_law:
        for knob in (0.25, 0.5, 0.75, 0.9):
            with cell:
                mk = measure(knob, trim)
            print(
                f"  VIBRATO {knob:.2f}: depth {mk['depth_db_pp']:5.2f} dB p-p,"
                f" level {mk['level_db'] - off:+.2f} dB"
            )

    if a.write:
        write(k, s, trim, m, off, g, depth_ref, level_ref)


def write(k, s, trim, m, off, g, depth_ref, level_ref) -> None:
    """Save LG1_200A's next version (unless unchanged) and pin it in the stock circuit with R17."""
    base = library.component_data(BASE)
    depth, level = m["depth_db_pp"], m["level_db"] - off
    d = {
        "name": NAME,
        "kind": "optocoupler",
        "source": (
            f"provisional: the {BASE} Vactrol's LED and cell (its fit to PerkinElmer's sheet)"
            f" with the cell's conductance divided by k = {k:.4g} (generation, pairwise"
            " recombination and dark conductance alike: a CdS cell's conductance scales with"
            f" its electrodes' geometry) and its dynamics {s:.4g} times faster (the steady"
            " state unchanged), k and the speed fitted with R17 by scripts/fit_wurlitzer_lg1.py"
            " to the Pie-finger set's VIBRATO full: depth"
            f" {depth_ref['depth_db_pp']:.2f} dB p-p and the envelope's H2"
            f" {depth_ref['h2_db']:.1f} dB (octave 4), level {level_ref['level_db']:+.2f} dB"
            f" against VIBRATO off ({level_ref['notes']} notes' median). Standing in for LG-1"
            " (Wurlitzer 142312, type unpublished; data/schematics/wurlitzer_200a/README.md)"
        ),
        "led": base["led"],
        "cell": cell_params(base["cell"], k, s)
        | {"source": f"{BASE}'s cell, conductance / k, time / speed"},
        "fit": {
            "k": round(k, 4),
            "speed": round(s, 4),
            "depth_db_pp": round(depth, 3),
            "level_db": round(level, 3),
            "h2_db": round(m["h2_db"], 2),
            "vib_trim": round(trim, 4),
            "source": "scripts/fit_wurlitzer_lg1.py through config/circuits/wurlitzer_200a.yaml",
        },
        "state": base["state"],
    }
    text = "# Generated by scripts/fit_wurlitzer_lg1.py. Don't edit by hand: refit.\n" + (
        yaml.safe_dump(d, sort_keys=False, width=100)
    )
    vs = versions.versions(NAME)
    if vs and versions.read_text(f"{NAME}@{vs[-1]}")[1] == text:
        ref = f"{NAME}@{vs[-1]}"
        print(f"{ref} unchanged")
    else:
        ref = str(versions.save(NAME, text))
        print(f"saved {ref}")
    reached = (
        abs(depth - depth_ref["depth_db_pp"]) < 0.2 and abs(level - level_ref["level_db"]) < 0.2
    )
    note = (
        ""
        if reached
        else f" (the cell's resistance swings {g.max() / g.min():.1f}x over the LED's cycle:"
        " both together are out of its reach)"
    )
    path = amp.CIRCUIT
    txt = path.read_text(encoding="utf-8")
    txt, n1 = re.subn(
        r"(\n  lg1: \{value: )[^,]+(, source: )\"[^\"]*\"",
        lambda mm: (
            f'{mm.group(1)}{ref}{mm.group(2)}"fit (scripts/fit_wurlitzer_lg1.py): LG-1'
            " (Wurlitzer 142312, an LED / LDR pair of unpublished type) as the VTL5C2's cell"
            " scaled and sped up to the Pie-finger set's VIBRATO full; Vintage Vibe sells a 200A"
            ' LDR: web: https://www.vintagevibe.com/products/wurlitzer-200a-ldr"'
        ),
        txt,
    )
    txt, n2 = re.subn(
        r"(\n  vib_trim: \{value: )[^,]+(,[^\n]*?source: )\"[^\"]*\"",
        lambda mm: (
            f'{mm.group(1)}{trim:.4f}{mm.group(2)}"fit (scripts/fit_wurlitzer_lg1.py, with'
            f" {ref}): R17, the 4.7K trimmer (203717-2) in the LED's string, at"
            f" {trim * 4700:.0f} ohm; with the cell, least squares on VIBRATO full's depth,"
            f" level against off and envelope H2: {depth:.2f} dB p-p, {level:+.2f} dB,"
            f" {m['h2_db']:.1f} dB, the Pie-finger set's {depth_ref['depth_db_pp']:.2f} dB p-p,"
            f' {level_ref["level_db"]:+.2f} dB, {depth_ref["h2_db"]:.1f} dB{note}"'
        ),
        txt,
    )
    assert n1 == 1 and n2 == 1, (n1, n2)
    path.write_text(txt, encoding="utf-8", newline="\n")
    print(f"set {path.name}: lg1 {ref}, vib_trim {trim:.4f}")


if __name__ == "__main__":
    main()
