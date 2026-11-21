"""Renders the invented-instrument sketches (varimu/invented/, docs/INVENTED_DEVICES.md's
second brainstorm) -> reports/invented/<name>/<take>.wav, <take>_plate.wav, <take>.png,
summary.json. Every take is matched to -20 LUFS.

    uv run python scripts/invented_sketches.py [--only NAME ...] [--seed N]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from varimu.invented import common as c  # noqa: E402
from varimu.invented.common import FS, Note, note  # noqa: E402


def score(spec: str, beat_s: float, vel: float = 0.7, gap: float = 0.0) -> list[Note]:
    """'D4:2 F4:1 A4:1' -> notes in sequence (beats), each held for its length minus gap."""
    out, t = [], 0.0
    for tok in spec.split():
        name, _, beats = tok.partition(":")
        b = float(beats or 1)
        if name != "r":
            out.append(Note(t, b * beat_s - gap, note(name), vel))
        t += b * beat_s
    return out


def shift(notes: list[Note], dt: float) -> list[Note]:
    return [Note(n.start_s + dt, n.dur_s, n.midi, n.vel) for n in notes]


# --- I11 the Rosin Wheel Organ -------------------------------------------------------


def rosin_wheel(seed: int) -> list[dict]:
    from varimu.invented import friction as fr

    def render(n: Note, i: int) -> np.ndarray:
        f1 = c.hz(n.midi)
        m = int((n.dur_s + 1.0) * FS)
        force = fr.press(m, n.dur_s, n.vel)
        damp = int((n.dur_s + 0.05) * FS)
        y = fr.bowed_bar(f1, force, c.rng(seed, f"rosin{i}"), damp_at=damp)
        return fr.resonator(y, f1)

    takes = []
    melody = score("D4:2 F4:1 A4:1 G4:2 E4:1 C4:1 D4:3 r:1", 0.55, vel=0.55, gap=0.06)
    chord = [Note(0.0, 4.0, note(x), 0.45) for x in ("D3", "A3", "F4", "C5")]
    x = c.place(melody + shift(chord, 6.6), render, 3.0)
    takes.append(c.finish("rosin_wheel", "melody_and_chord", x))
    # one bar, the press swept from a feather to a crush (the regimes: squeal, tone, raucous)
    m = int(9 * FS)
    t = np.arange(m) / FS
    force = np.interp(t, [0, 0.3, 7.5, 8.0, 9.0], [0, 0.15, 6.0, 0, 0])
    bar = fr.bowed_bar(c.hz(note("A2")), force, c.rng(seed, "sweep"), damp_at=int(8.05 * FS))
    y = fr.resonator(bar, c.hz(note("A2")))
    takes.append(c.finish("rosin_wheel", "press_sweep_A2", y, {"force_n": "0.15 -> 6 N over 7 s"}))
    return takes


# --- I12 the Aeolian Keyboard ----------------------------------------------------------


def aeolian(seed: int) -> list[dict]:
    from varimu.invented import aeolian as ae

    takes = []
    # a chord held while the WIND pedal climbs and falls: the harmonics walk the series
    dur = 14.0
    m = int((dur + 1.5) * FS)
    t = np.arange(m) / FS
    pedal = np.interp(t, [0, 3, 8, 12, dur], [1.3, 1.6, 4.6, 2.0, 1.4])
    x = np.zeros(m)
    for i, name in enumerate(("A2", "E3", "A3", "C#4")):
        slot = c.envelope(m, 0.4 * i, dur, 0.25, 0.4)
        x += ae.string(c.hz(note(name)), pedal * slot, c.rng(seed, f"aeolian_chord{i}"))
    takes.append(c.finish("aeolian", "chord_wind_swell", x, {"wind_m_s": "1.3 -> 4.6 -> 1.4"}))

    # a melody over a drone at the nominal wind, gusty
    def render(n: Note, i: int) -> np.ndarray:
        m = int((n.dur_s + 0.8) * FS)
        slot = c.envelope(m, 0.0, n.dur_s, 0.2, 0.3)
        return ae.string(c.hz(n.midi), ae.U_NOMINAL * slot, c.rng(seed, f"aeolian{i}"), gust=0.1)

    melody = score("A3:2 C4:1 E4:1 D4:2 C4:1 B3:1 A3:2 E4:2 A4:4", 0.6, gap=-0.15)
    drone = [Note(0.0, 10.0, note("A2")), Note(0.0, 10.0, note("E3"))]
    x = c.place(melody + drone, render, 1.0)
    takes.append(c.finish("aeolian", "melody_over_drone", x))
    return takes


# --- I13 the Arc Organ ------------------------------------------------------------------


def arc_organ(seed: int) -> list[dict]:
    from varimu.invented import arc

    def keys(notes: list[Note], current_a: float, n: int, r: float = arc.TANK_OHM) -> np.ndarray:
        caps = np.zeros(n)
        for nt in notes:
            cf = arc.tuned_condenser(c.hz(nt.midi), current_a, tank_ohm=r)
            caps[int(nt.start_s * FS) : int((nt.start_s + nt.dur_s) * FS)] = cf
        return caps

    takes = []
    melody = score("r:1 E4:1 G4:1 A4:2 G4:1 E4:1 D4:2 C4:1 D4:1 E4:3 r:1", 0.45, gap=0.0)
    n = int((melody[-1].start_s + melody[-1].dur_s + 1.2) * FS)
    p, _ = arc.sing(keys(melody, 5.0, n), 5.0, c.rng(seed, "arc_melody"))
    takes.append(c.finish("arc_organ", "melody_5A", p, {"current_a": 5.0}))

    # the same phrase at three arc currents: gentle, nominal, hissing
    phrase = score("r:1 A3:1 C4:1 E4:2 D4:1 C4:1 A3:2 r:1", 0.4)
    parts = []
    for current in (3.0, 5.0, 9.0):
        n = int((phrase[-1].start_s + phrase[-1].dur_s + 0.6) * FS)
        p, _ = arc.sing(keys(phrase, current, n), current, c.rng(seed, f"arc_i{current}"))
        parts.append(p / np.sqrt(np.mean(p**2)))
    takes.append(
        c.finish("arc_organ", "currents_3_5_9A", np.concatenate(parts), {"current_a": [3, 5, 9]})
    )

    # SPEAK (the tank's resistance): near the arc's -1.31 ohm a note takes ~0.3 s to build
    parts = []
    for r in (0.4, 1.1, 1.25):
        n = int((phrase[-1].start_s + phrase[-1].dur_s + 0.6) * FS)
        p, _ = arc.sing(keys(phrase, 5.0, n, r), 5.0, c.rng(seed, f"arc_r{r}"), tank_ohm=r)
        parts.append(p / np.sqrt(np.mean(p**2)))
    takes.append(
        c.finish(
            "arc_organ",
            "speak_0.4_1.1_1.25ohm",
            np.concatenate(parts),
            {"tank_ohm": [0.4, 1.1, 1.25]},
        )
    )

    # two arcs, two voices
    upper = score("r:1 E4:2 F4:1 G4:1 A4:2 G4:2 F4:2 E4:4 r:1", 0.4)
    lower = score("r:1 C4:2 D4:2 C4:2 B3:2 A3:2 G#3:4 r:1", 0.4)
    n = int((upper[-1].start_s + upper[-1].dur_s + 1.0) * FS)
    p1, _ = arc.sing(keys(upper, 5.0, n), 5.0, c.rng(seed, "arc_upper"))
    p2, _ = arc.sing(keys(lower, 5.0, n), 5.0, c.rng(seed, "arc_lower"), arc_mm=2.3)
    takes.append(c.finish("arc_organ", "two_arcs", p1 + 0.8 * p2))
    return takes


# --- I15 the Siren Organ ----------------------------------------------------------------


def siren_organ(seed: int) -> list[dict]:
    from varimu.invented import siren as sr

    def keys(spec: str, beat_s: float, gap: float = 0.03) -> list:
        """'16:2 18:1 ...' -> keys in sequence (holes:beats; r = rest)."""
        out, t = [], 0.3
        for tok in spec.split():
            h, _, b = tok.partition(":")
            if h != "r":
                out.append(sr.Key(int(h), t, float(b or 1) * beat_s - gap))
            t += float(b or 1) * beat_s
        return out

    takes = []
    tune = "16:1 18:1 20:1 24:2 27:1 28:1 27:1 24:1 20:2 21:1 20:1 18:1 16:3"
    for stop in ("flute", "reed"):
        k = keys(tune, 0.42)
        y, info = sr.play(k, k[-1].start_s + k[-1].dur_s + 1.0, c.rng(seed, f"siren_{stop}"), stop)
        takes.append(c.finish("siren_organ", f"harmonic_melody_{stop}", y, info))
    # a 4:5:6:7 chord entering a key at a time: the shaft (every pitch) and the wind sag
    k = [sr.Key(16, 0.3, 6.5), sr.Key(20, 1.6, 5.2), sr.Key(24, 2.9, 3.9), sr.Key(28, 4.2, 2.6)]
    for stop in ("flute", "reed"):
        y, info = sr.play(k, 8.0, c.rng(seed, f"siren_chord_{stop}"), stop)
        takes.append(c.finish("siren_organ", f"just_chord_sag_{stop}", y, info))
    # the SPEED lever under a held fifth
    nc = int(9.0 * sr.CONTROL_HZ)
    tc = np.arange(nc) / sr.CONTROL_HZ
    lever = np.interp(tc, [0, 1.5, 4.0, 6.0, 7.5, 9.0], [1, 1, 2, 0.6, 1, 1])
    k = [sr.Key(16, 0.3, 8.0), sr.Key(24, 0.3, 8.0)]
    y, info = sr.play(k, 9.0, c.rng(seed, "siren_glide"), "reed", speed=lever)
    takes.append(c.finish("siren_organ", "speed_glide_reed", y, info))
    return takes


# --- I14 the Buzz Zither ----------------------------------------------------------------


def buzz_zither(seed: int) -> list[dict]:
    from varimu.invented import jawari as jw

    jaw = 0.2  # the open jawari (a flat bridge: the strongest bloom of those tried)
    takes = []

    def tanpura(cycles: int, gap_s: float, amp: float, jawari: float) -> np.ndarray:
        strings = ("G2", "C3", "C3", "C2")  # Pa, Sa, Sa, low Sa
        period = gap_s * len(strings)
        total = cycles * period + 7.0
        out = np.zeros(int(total * FS))
        for cyc in range(cycles):
            for i, name in enumerate(strings):
                t0 = cyc * period + i * gap_s
                last = cyc == cycles - 1
                dur = (total - t0) if last else period + 0.04
                y = jw.string(c.hz(note(name)), dur, amp, jawari=jawari, pluck_at=0.27 + 0.02 * i)
                if not last:  # the finger catches the string again: 40 ms
                    y[-int(0.04 * FS) :] *= np.linspace(1, 0, int(0.04 * FS))
                k = int(t0 * FS)
                m = min(y.size, out.size - k)
                out[k : k + m] += y[:m]
        return jw.soundboard(out)

    takes.append(c.finish("buzz_zither", "tanpura_cycle", tanpura(3, 0.95, 1.5e-3, jaw)))
    # the mechanism alone: one C3 pluck on a sharp bridge, then on the jawari
    a = jw.string(c.hz(note("C3")), 5.0, 1.5e-3, jawari=0.0)
    b = jw.string(c.hz(note("C3")), 5.0, 1.5e-3, jawari=jaw)
    ab = np.concatenate([a / np.sqrt(np.mean(a**2)), b / np.sqrt(np.mean(b**2))])
    takes.append(c.finish("buzz_zither", "sharp_then_jawari_C3", jw.soundboard(ab)))

    # the keyboard: a string per key, shorter up the scale like a harp's, damped on release
    def render(n: Note, i: int) -> np.ndarray:
        f = c.hz(n.midi)
        length = max(jw.LENGTH_M * c.hz(note("C3")) / f, 0.2)
        y = jw.string(f, n.dur_s + 0.5, 1.2e-3 * (0.5 + n.vel), jawari=jaw,
                      damp_at_s=n.dur_s, length_m=length)  # fmt: skip
        return jw.soundboard(y)

    melody = score("C4:1 Db4:1 E4:2 F4:1 G4:2 Ab4:1 G4:1 F4:1 E4:2 Db4:1 C4:3", 0.38, gap=0.02)
    drone = tanpura(2, 1.2, 1.0e-3, jaw)
    mel = c.place(melody, render, 0.6)
    n = max(mel.size + int(1.2 * FS), drone.size)
    mix = np.zeros(n)
    mix[: drone.size] += 0.6 * drone / np.sqrt(np.mean(drone**2))
    k = int(1.2 * FS)
    mix[k : k + mel.size] += mel / np.sqrt(np.mean(mel**2))
    takes.append(c.finish("buzz_zither", "melody_over_tanpura", mix))
    return takes


# --- I16 the Bubble Organ ---------------------------------------------------------------


def bubble_organ(seed: int) -> list[dict]:
    from varimu.invented import bubbles as bb

    takes = []

    # struck: one bubble per key (chords are bubbles released together)
    def single(n: Note, i: int) -> np.ndarray:
        g = c.rng(seed, f"single{i}")
        return (0.5 + n.vel) * bb.bubble(bb.radius_for(c.hz(n.midi)), g)

    tune = score("G4:1 E4:1 G4:1 C5:2 A4:1 G4:1 E4:1 D4:1 E4:1 C4:3", 0.3)
    chords = []
    for j, ch in enumerate(
        (("C3", "G3", "E4"), ("A2", "E3", "C4"), ("F2", "C3", "A3"), ("G2", "D3", "B3"))
    ):
        for k, name in enumerate(ch):
            chords.append(Note(4.6 + 0.9 * j + 0.025 * k, 0.1, note(name), 0.7))
    x = c.place(tune + chords, single, 1.5)
    takes.append(c.finish("bubble_organ", "single_bubbles", x))

    # held: streams (a chord, each key its own nozzle and rhythm)
    x = np.zeros(int(9 * FS))
    for k, (name, rate) in enumerate((("C3", 7.0), ("G3", 9.0), ("E4", 11.0), ("C5", 13.0))):
        y = bb.stream(c.hz(note(name)), 7.0, rate, c.rng(seed, f"stream{k}"))
        x[: y.size] += y[: x.size]
    takes.append(c.finish("bubble_organ", "held_streams_chord", x))

    # breath: one held key, the flow swelled 0.7 -> 1.4 -> 0.7 (bigger bubbles: flatter, faster)
    m = int(8 * FS)
    t = np.arange(m) / FS
    flow = np.interp(t, [0, 4, 8], [0.7, 1.4, 0.7])
    y = bb.stream(c.hz(note("A3")), 8.0, 10.0, c.rng(seed, "breath"), flow=flow)
    takes.append(c.finish("bubble_organ", "breath_bend_A3", y, {"flow": "0.7 -> 1.4 -> 0.7"}))
    return takes


# --- I7 the Rijke Organ -----------------------------------------------------------------


def rijke_organ(seed: int) -> list[dict]:
    from varimu.invented import rijke as rj

    takes = []

    def render(n: Note, i: int) -> np.ndarray:
        m = int((n.dur_s + 3.0) * FS)
        heater = c.envelope(m, 0.0, n.dur_s, 0.01, 0.01)
        return rj.pipe(c.hz(n.midi), heater, c.rng(seed, f"rijke{i}"))

    chord = [Note(1.2 * k, 7.0 - 1.2 * k, note(x)) for k, x in enumerate(("D3", "A3", "F#4", "D4"))]
    takes.append(c.finish("rijke_organ", "blooming_chord", c.place(chord, render, 3.0)))

    # one pipe, the heater turned up slowly and back down: a sudden start past the Hopf
    # point, and it holds well below it before it lets go
    m = int(14 * FS)
    t = np.arange(m) / FS
    drive = np.interp(t, [0, 6, 12, 14], [0.2, 1.0, 0.2, 0.2])
    y = rj.pipe(c.hz(note("A3")), drive, c.rng(seed, "rijke_hyst"))
    takes.append(
        c.finish("rijke_organ", "heater_hysteresis_A3", y, {"heater": "0.2 -> 1 -> 0.2 x K"})
    )

    melody = score("D4:2 E4:1 F#4:1 A4:3 G4:1 F#4:2 E4:2 D4:4", 0.5, gap=-0.3)
    drone = [Note(0.0, 8.5, note("D3"))]
    takes.append(c.finish("rijke_organ", "melody_over_drone", c.place(melody + drone, render, 3.0)))
    return takes


SKETCHES = {
    "rosin_wheel": rosin_wheel,
    "aeolian": aeolian,
    "arc_organ": arc_organ,
    "siren_organ": siren_organ,
    "buzz_zither": buzz_zither,
    "bubble_organ": bubble_organ,
    "rijke_organ": rijke_organ,
}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*", default=None)
    ap.add_argument("--seed", type=int, default=1)
    args = ap.parse_args()
    for name, fn in SKETCHES.items():
        if args.only and name not in args.only:
            continue
        with c.Timer() as tm:
            takes = fn(args.seed)
        c.write_summary(name, takes, tm.s)
        print(f"{name}: {len(takes)} takes in {tm.s:.0f} s -> {c.OUT / name}")


if __name__ == "__main__":
    main()
