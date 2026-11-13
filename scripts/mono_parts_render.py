"""A MIDI file played by a monophonic instrument: its hands split into single lines, each line
rendered through its own copy of the device, mixed (the user's: "rendered as parts that have
only one voice per part").

    uv run --extra listen python scripts/mono_parts_render.py --midi FILE
        [--device tube_synth] [--set KEY=VALUE ...] [--quality draft-2x|production]
        [--start S] [--seconds S] [--tail 2] [--jobs 2] [--out NAME] [--split-only]

**The split** (per MIDI track and channel, a hand): notes in time; the notes starting
together (within 15 ms) are matched to the lines as a group, every assignment tried, at a cost
of the semitones each line leaps, a new line costing 24 and a line still holding a note
(past `OVERLAP_S` or a third of that note) not offered; a line that takes a note while its
last one still sounds is cut there (legato: the keyboard's retrigger). Lines are numbered
top down by their mean pitch. A note shorter than 20 ms or at velocity 1 is dropped.

**The render**: each line through `cargo run --release -p varimu-app --example midi_render`
(the take renderer: the Play view's keyboard logic, knobs and range switch), a fresh warm
device per stretch of a line (rests longer than `--gap` split it: silence costs as much to
simulate as notes), each started a different fraction of a second earlier per line (so the
lines' LFOs don't run in phase: separate units), the lead-in cut. One render at a time by
default: the device's partition threads spin, and two at once ran each 3x slower. Stems and
the mix go to
reports/mono_parts/<name>/: stems/line_<k>.wav (the device's full scale), mix.wav (mono)
and mix_stereo.wav (the lines spread top-left to bottom-right, constant power), the mixes
normalized to -1 dBFS peak; parts.json has the split and the times.
"""

from __future__ import annotations

import argparse
import itertools
import json
import math
import struct
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "reports" / "mono_parts"
EXE = REPO / "target" / "release" / "examples" / "midi_render"
if sys.platform == "win32":
    EXE = EXE.with_suffix(".exe")
GROUP_S = 0.015
OVERLAP_S = 0.06
NEW_LINE = 24.0
MIN_DUR_S = 0.02


def _varlen(d: bytes, i: int) -> tuple[int, int]:
    v = 0
    while True:
        b = d[i]
        i += 1
        v = (v << 7) | (b & 0x7F)
        if not b & 0x80:
            return v, i


def read_hands(path: Path) -> dict[str, list[list]]:
    """Notes per (track, channel): [on_s, off_s, note, velocity], in time."""
    d = Path(path).read_bytes()
    hlen = struct.unpack(">I", d[4:8])[0]
    fmt, ntrk, div = struct.unpack(">HHH", d[8:14])
    if div & 0x8000 or fmt not in (0, 1):
        raise ValueError(f"{path}: unsupported MIDI file")
    i = 8 + hlen
    raw, tempos, names = [], [(0, 500000)], {}
    for t in range(ntrk):
        tlen = struct.unpack(">I", d[i + 4 : i + 8])[0]
        j, end, tick, st = i + 8, i + 8 + tlen, 0, 0
        while j < end:
            dt, j = _varlen(d, j)
            tick += dt
            b = d[j]
            if b == 0xFF:
                mt = d[j + 1]
                ml, j = _varlen(d, j + 2)
                if mt == 0x51:
                    tempos.append((tick, int.from_bytes(d[j : j + 3], "big")))
                elif mt == 0x03:
                    names[t] = d[j : j + ml].decode("latin1").strip("\x00 ")
                j += ml
                continue
            if b in (0xF0, 0xF7):
                sl, j = _varlen(d, j + 1)
                j += sl
                continue
            if b & 0x80:
                st, j = b, j + 1
            k, ch = st & 0xF0, st & 0x0F
            nb = 1 if k in (0xC0, 0xD0) else 2
            a, c = d[j], (d[j + 1] if nb == 2 else 0)
            j += nb
            if k == 0x90 and c > 0:
                raw.append((tick, t, ch, "on", a, c))
            elif k == 0x80 or (k == 0x90 and c == 0):
                raw.append((tick, t, ch, "off", a, 0))
        i = end
    tempos.sort()

    def sec(tick: int) -> float:
        s, last, us = 0.0, 0, tempos[0][1]
        for tt, u in tempos:
            if tt > tick:
                break
            s += (tt - last) * us / div / 1e6
            last, us = tt, u
        return s + (tick - last) * us / div / 1e6

    hands: dict[str, list[list]] = {}
    open_: dict[tuple, list] = {}
    for tick, t, ch, kind, n, v in sorted(raw, key=lambda r: (r[0], r[3] == "on")):
        hand = f"{names.get(t, f'track{t}')} ch{ch}"
        key = (t, ch, n)
        if kind == "on":
            if key in open_:  # struck again while down: the old one ends here
                old = open_.pop(key)
                old[1] = sec(tick)
            note = [sec(tick), None, n, v]
            open_[key] = note
            hands.setdefault(hand, []).append(note)
        elif key in open_:
            open_.pop(key)[1] = sec(tick)
    for note in open_.values():
        note[1] = note[0] + 0.5
    return {h: sorted(ns) for h, ns in hands.items()}


def split(notes: list[list]) -> list[list[list]]:
    """A hand's notes as monophonic lines (see the module docs)."""
    notes = [n for n in notes if n[1] - n[0] >= MIN_DUR_S and n[3] > 1]
    lines: list[list[list]] = []
    i = 0
    while i < len(notes):
        group = [notes[i]]
        while i + len(group) < len(notes) and notes[i + len(group)][0] - notes[i][0] < GROUP_S:
            group.append(notes[i + len(group)])
        i += len(group)
        group.sort(key=lambda n: -n[2])
        t = group[0][0]

        def offered(line: list[list], t: float = t) -> bool:
            on, off = line[-1][0], line[-1][1]
            return off - t <= max(OVERLAP_S, (off - on) / 3)

        free = [k for k, line in enumerate(lines) if offered(line)]
        best, best_cost = None, math.inf
        # Each note to a free line or to a new one (-1 - j: the j-th new line).
        slots = free + [-1 - j for j in range(len(group))]
        for perm in itertools.permutations(slots, len(group)):
            cost = 0.0
            for note, k in zip(group, perm, strict=True):
                cost += NEW_LINE if k < 0 else abs(note[2] - lines[k][-1][2])
            # Higher notes to higher lines where lines exist (no crossing within a chord).
            pairs = zip(group, perm, strict=True)
            used = [(lines[k][-1][2], note[2]) for note, k in pairs if k >= 0]
            for (a1, b1), (a2, b2) in itertools.combinations(used, 2):
                if (a1 - a2) * (b1 - b2) < 0:
                    cost += 6
            if cost < best_cost:
                best, best_cost = perm, cost
        for note, k in zip(group, best, strict=True):
            if k < 0:
                lines.append([note[:]])
            else:
                last = lines[k][-1]
                if last[1] > note[0]:
                    last[1] = note[0]  # legato: the line's last note cut here
                lines[k].append(note[:])
    return lines


def segments(line: list[list], gap_s: float) -> list[list[list]]:
    """A line in stretches separated by more than `gap_s` of rest."""
    out = [[line[0]]]
    for note in line[1:]:
        if note[0] - out[-1][-1][1] > gap_s:
            out.append([])
        out[-1].append(note)
    return out


def render_line(args, k: int, line: list[list], lead_s: float, dirs, fs: int) -> dict:
    """A line through its device, each stretch from a fresh warm start `lead_s` ahead of
    its first note, placed where it plays: the stem (from 0 s) and the times."""
    import soundfile as sf

    pieces, wall, played = [], 0.0, 0.0
    for j, seg in enumerate(segments(line, args.gap)):
        t0_s = seg[0][0]
        notes = [[on - t0_s + lead_s, off - t0_s + lead_s, n, v] for on, off, n, v in seg]
        end_s = seg[-1][1] - t0_s + lead_s + args.tail
        part = dirs["parts"] / f"line_{k}_{j}.json"
        part.write_text(json.dumps({"notes": notes, "end_s": end_s}))
        raw = dirs["parts"] / f"line_{k}_{j}_raw.wav"
        cmd = [
            str(EXE),
            "--device",
            args.device,
            "--notes",
            str(part),
            "--out",
            str(raw),
            "--quality",
            args.quality,
        ]
        for kv in args.set:
            cmd += ["--set", kv]
        t0 = time.perf_counter()
        r = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True)
        if r.returncode:
            raise RuntimeError(f"line {k}: {r.stderr[-2000:]}")
        wall += time.perf_counter() - t0
        played += end_s - lead_s
        y, rate = sf.read(raw, dtype="float64")
        if rate != fs:
            raise RuntimeError(f"line {k}: {rate} Hz, expected {fs}")
        raw.unlink()
        pieces.append((t0_s, y[int(round(lead_s * fs)) :]))
    n = max(int(round(t * fs)) + len(y) for t, y in pieces)
    stem = np.zeros(n)
    for t, y in pieces:
        i = int(round(t * fs))
        stem[i : i + len(y)] += y
    print(
        f"  line {k}: {len(line)} notes in {len(pieces)} stretches, {played:.0f} s rendered"
        f" in {wall:.0f} s ({wall / max(played, 1e-9):.2f}x real time)",
        flush=True,
    )
    return {"line": k, "stem": stem, "stretches": len(pieces), "rendered_s": played, "wall_s": wall}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--midi", type=Path, required=True)
    ap.add_argument("--device", default="tube_synth")
    ap.add_argument("--set", nargs="*", default=[], metavar="KEY=VALUE")
    ap.add_argument("--quality", default="draft-2x")
    ap.add_argument("--start", type=float, default=0.0)
    ap.add_argument("--seconds", type=float)
    ap.add_argument("--tail", type=float, default=2.0)
    ap.add_argument("--jobs", type=int, default=1, help="renders at once (each spins threads)")
    ap.add_argument("--gap", type=float, default=3.0, help="rest that splits a line's renders")
    ap.add_argument("--out")
    ap.add_argument("--split-only", action="store_true")
    args = ap.parse_args()

    hands = read_hands(args.midi)
    t_end = args.start + args.seconds if args.seconds else math.inf
    lines: list[tuple[str, list[list]]] = []
    for hand, notes in hands.items():
        for line in split(notes):
            cut = []
            for on, off, n, v in line:
                if args.start <= on < t_end:
                    cut.append([on - args.start, min(off, t_end) - args.start, n, v])
            if cut:
                lines.append((hand, cut))
    lines.sort(key=lambda hl: -np.mean([n[2] for n in hl[1]]))
    end_s = max(n[1] for _, line in lines for n in line) + args.tail
    print(f"{args.midi.name}: {len(lines)} lines over {end_s:.1f} s")
    for k, (hand, line) in enumerate(lines):
        ns = [n[2] for n in line]
        print(
            f"  line {k}: {hand:<12} {len(line):5d} notes, MIDI {min(ns)}-{max(ns)},"
            f" mean {np.mean(ns):.1f}"
        )
    if args.split_only:
        return

    name = args.out or args.midi.stem
    out = OUT / name
    dirs = {"parts": out / "parts", "stems": out / "stems"}
    for d in dirs.values():
        d.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["cargo", "build", "--release", "-q", "-p", "varimu-app", "--example", "midi_render"],
        cwd=REPO,
        check=True,
    )
    import soundfile as sf

    fs = 48000 if args.quality.startswith("draft") else 96000
    t0 = time.perf_counter()
    leads = [0.5 + 0.37 * k for k in range(len(lines))]
    with ThreadPoolExecutor(args.jobs) as ex:
        done = list(
            ex.map(
                lambda kl: render_line(args, kl[0], kl[1][1], leads[kl[0]], dirs, fs),
                enumerate(lines),
            )
        )
    stems = []
    for r in done:
        y = r["stem"][: int(round(end_s * fs))]
        stems.append(y)
        sf.write(dirs["stems"] / f"line_{r['line']}.wav", y.astype(np.float32), fs, subtype="FLOAT")
    n = max(len(s) for s in stems)
    stems = [np.pad(s, (0, n - len(s))) for s in stems]
    mix = np.sum(stems, axis=0)
    peak = np.max(np.abs(mix))
    g = 10 ** (-1 / 20) / max(peak, 1e-12)
    sf.write(out / "mix.wav", (mix * g).astype(np.float32), fs, subtype="FLOAT")
    # Constant-power spread: the top line left, the bottom right (+-0.6 of hard pan).
    st = np.zeros((n, 2))
    for k, s in enumerate(stems):
        pos = 0.0 if len(stems) == 1 else -0.6 + 1.2 * k / (len(stems) - 1)
        a = (pos + 1) * math.pi / 4
        st[:, 0] += s * math.cos(a)
        st[:, 1] += s * math.sin(a)
    st *= 10 ** (-1 / 20) / max(np.max(np.abs(st)), 1e-12)
    sf.write(out / "mix_stereo.wav", st.astype(np.float32), fs, subtype="FLOAT")
    wall = time.perf_counter() - t0
    (out / "parts.json").write_text(
        json.dumps(
            {
                "midi": str(args.midi),
                "device": args.device,
                "set": args.set,
                "quality": args.quality,
                "start_s": args.start,
                "seconds": end_s,
                "mix_peak_fs": float(peak),
                "wall_s": wall,
                "lines": [
                    {
                        "hand": h,
                        "notes": len(line),
                        "lead_s": leads[k],
                        "stretches": done[k]["stretches"],
                        "rendered_s": done[k]["rendered_s"],
                        "wall_s": done[k]["wall_s"],
                    }
                    for k, (h, line) in enumerate(lines)
                ],
            },
            indent=2,
        )
    )
    print(f"mix peak {peak:.3f} FS (each line at the device's full scale); {wall:.0f} s -> {out}")


if __name__ == "__main__":
    main()
