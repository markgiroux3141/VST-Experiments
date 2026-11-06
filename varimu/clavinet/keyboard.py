"""The whole keyboard played from MIDI events: each note a key struck, held and released
(`note.play`), the strings' EMFs summed per pickup (docs/CLAVINET_PLAN.md, CL2).

Every key has its own string, so notes are independent and the pickups' coils add their
EMFs: the sum is exact. One simplification is left: a key struck again while its string still
rings from its release adds to that ring rather than continuing it (the yarn has it
~60 dB down in ~0.1 s on the plain strings).

Velocity is [G13]'s linear law (MIDI 1-127 to 1-4 m/s at the tangent); the mute bar's
slider is one setting for the whole render (0 off, 1 fully on).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from varimu.clavinet import fit, note, spec
from varimu.rhodes import midi


@dataclass(frozen=True)
class NoteSpan:
    t_on_s: float
    t_off_s: float
    midi_note: int
    velocity: int


def spans(events: list[midi.Event]) -> list[NoteSpan]:
    """Note-ons paired with their note-offs (a note still down at the end is released
    there); the sustain pedal is ignored (a Clavinet has none)."""
    down: dict[int, tuple[float, int]] = {}
    out = []
    end = max((e.t_s for e in events), default=0.0)
    for e in events:
        if e.kind == "on":
            if e.note in down:  # re-struck without a release: release it first
                t0, v = down.pop(e.note)
                out.append(NoteSpan(t0, e.t_s, e.note, v))
            down[e.note] = (e.t_s, e.value)
        elif e.kind == "off" and e.note in down:
            t0, v = down.pop(e.note)
            out.append(NoteSpan(t0, e.t_s, e.note, v))
    for n, (t0, v) in down.items():
        out.append(NoteSpan(t0, end, n, v))
    return sorted(out, key=lambda s: s.t_on_s)


def render(
    events: list[midi.Event],
    fs_hz: float = 96000.0,
    tail_s: float = 0.4,
    mute: float = 0.0,
    min_hold_s: float = 0.03,
    progress=None,
) -> tuple[dict[str, np.ndarray], dict]:
    """(EMF per pickup at fs, stats): the notes' sum."""
    sp = spans(events)
    end = max((s.t_off_s for s in sp), default=0.0) + tail_s + 0.1
    n_total = int(np.ceil(end * fs_hz))
    out = {w: np.zeros(n_total) for w in note.PICKUPS}
    cache: dict[tuple, note.Played] = {}
    skipped = 0
    for i, s in enumerate(sp):
        k = spec.key_of_midi(s.midi_note)
        if k is None:
            skipped += 1
            continue
        v = spec.velocity_m_s(s.velocity)
        hold = max(s.t_off_s - s.t_on_s, min_hold_s)
        key = (k, round(v, 4), round(hold, 4), mute)
        if key not in cache:
            cache[key] = note.play(
                k, v, hold, tail_s=tail_s, fs_hz=fs_hz, params=fit.params(k, mute=mute)
            )
        pl = cache[key]
        i0 = int(round(s.t_on_s * fs_hz))
        for w in note.PICKUPS:
            x = pl.emf_v[w]
            m = min(x.size, n_total - i0)
            out[w][i0 : i0 + m] += x[:m]
        if progress:
            progress(i + 1, len(sp))
    return out, {"notes": len(sp), "rendered": len(cache), "out_of_range": skipped}
