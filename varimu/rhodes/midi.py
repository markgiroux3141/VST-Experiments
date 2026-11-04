"""A Standard MIDI File's notes and sustain pedal, in seconds (docs/RHODES_PLAN.md, RH2).

`read(path)` parses formats 0 and 1 (running status, tempo changes on any track, SMPTE
division refused) into `Event`s on one channel-blind timeline: note on (velocity > 0),
note off (or note on at velocity 0), and the sustain pedal (CC 64, down at >= 64). Other
messages are skipped. No dependency: the format is small (the MIDI 1.0 specification's
"Standard MIDI Files").
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Event:
    t_s: float
    kind: str  # "on", "off", "pedal"
    note: int = 0  # MIDI note (60 = C4)
    value: int = 0  # velocity (on), 0/1 (pedal up/down)


def _varlen(data: bytes, i: int) -> tuple[int, int]:
    v = 0
    while True:
        b = data[i]
        i += 1
        v = (v << 7) | (b & 0x7F)
        if not b & 0x80:
            return v, i


def read(path: Path) -> list[Event]:
    data = Path(path).read_bytes()
    if data[:4] != b"MThd":
        raise ValueError(f"{path}: not a Standard MIDI File")
    hlen = struct.unpack(">I", data[4:8])[0]
    fmt, ntrk, division = struct.unpack(">HHH", data[8:14])
    if division & 0x8000:
        raise ValueError(f"{path}: SMPTE time division isn't supported")
    if fmt not in (0, 1):
        raise ValueError(f"{path}: format {fmt} isn't supported")
    i = 8 + hlen
    raw: list[tuple[int, str, int, int]] = []  # (tick, kind, a, b)
    tempos: list[tuple[int, int]] = [(0, 500000)]  # (tick, us per quarter)
    for _ in range(ntrk):
        if data[i : i + 4] != b"MTrk":
            raise ValueError(f"{path}: expected a track at byte {i}")
        tlen = struct.unpack(">I", data[i + 4 : i + 8])[0]
        j, end = i + 8, i + 8 + tlen
        tick, status = 0, 0
        while j < end:
            delta, j = _varlen(data, j)
            tick += delta
            b = data[j]
            if b == 0xFF:  # meta
                mtype = data[j + 1]
                mlen, j = _varlen(data, j + 2)
                if mtype == 0x51:
                    tempos.append((tick, int.from_bytes(data[j : j + 3], "big")))
                j += mlen
                continue
            if b in (0xF0, 0xF7):  # sysex
                slen, j = _varlen(data, j + 1)
                j += slen
                continue
            if b & 0x80:
                status, j = b, j + 1
            kind = status & 0xF0
            nbytes = 1 if kind in (0xC0, 0xD0) else 2
            a = data[j]
            c = data[j + 1] if nbytes == 2 else 0
            j += nbytes
            if kind == 0x90 and c > 0:
                raw.append((tick, "on", a, c))
            elif kind == 0x80 or (kind == 0x90 and c == 0):
                raw.append((tick, "off", a, 0))
            elif kind == 0xB0 and a == 64:
                raw.append((tick, "pedal", 0, int(c >= 64)))
        i = end
    tempos.sort()
    events = []
    for tick, kind, a, c in sorted(raw, key=lambda e: e[0]):
        events.append(Event(_seconds(tick, tempos, division), kind, a, c))
    return events


def _seconds(tick: int, tempos: list[tuple[int, int]], division: int) -> float:
    t, last_tick, us = 0.0, 0, tempos[0][1]
    for tt, tempo in tempos[1:]:
        if tt >= tick:
            break
        t += (tt - last_tick) * us / division / 1e6
        last_tick, us = tt, tempo
    return t + (tick - last_tick) * us / division / 1e6


def write(path: Path, events: list[Event], tpq: int = 480, tempo_us: int = 500000) -> None:
    """A format 0 file of the events (for tests and generated phrases)."""
    out = bytearray()
    last = 0
    track = bytearray(b"\x00\xff\x51\x03" + tempo_us.to_bytes(3, "big"))
    for e in sorted(events, key=lambda e: e.t_s):
        tick = round(e.t_s * 1e6 / tempo_us * tpq)
        track += _vl(tick - last)
        last = tick
        if e.kind == "on":
            track += bytes([0x90, e.note, e.value])
        elif e.kind == "off":
            track += bytes([0x80, e.note, 0])
        else:
            track += bytes([0xB0, 64, 127 if e.value else 0])
    track += b"\x00\xff\x2f\x00"
    out += b"MThd" + struct.pack(">IHHH", 6, 0, 1, tpq)
    out += b"MTrk" + struct.pack(">I", len(track)) + track
    Path(path).write_bytes(bytes(out))


def _vl(v: int) -> bytes:
    out = [v & 0x7F]
    v >>= 7
    while v:
        out.append((v & 0x7F) | 0x80)
        v >>= 7
    return bytes(reversed(out))
