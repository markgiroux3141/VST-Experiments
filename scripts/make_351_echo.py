"""The Ampex 351 as a studio's slap echo (docs/DELAY_PLAN.md, "The 351 echo"), generated
from the machine's own circuit file.

    uv run python scripts/make_351_echo.py [--check]

Writes config/circuits/ampex_351_echo.yaml from config/circuits/ampex_351.yaml and the
machine's alignment (reports/tape/ampex_351_alignment.json, written by
scripts/align_351.py): the alignment's settings become the controls' values, and a passive
console bus goes in front of the bridging input:
- SEND: a pot across the source, its wiper into the bus through r_send_ohm;
- VARISPEED (`capstan_hz`): the capstan's motor on a variable-frequency supply (the tape
  part's `supply`), the speed gliding and hunting after the frequency;
- REPEAT: a pot across the line output (its 600 ohm load), its wiper into the bus through
  r_repeat_ohm. With the bridging input's ~99k, full REPEAT feeds the output back ~3 dB
  above unity loop gain (the machine records at -10 dBm and plays back at +8 dBm), so the
  repeats run away past ~0.7 of the pot's travel, into the tape's and the tubes' saturation.

Live (an events build: the draft qualities), the tape plays its reduction
(config/tape_reductions/ampex_351.json, ampex_351_lo.json at 7-1/2 ips;
scripts/tape_reduction.py): the oscillator leaves its socket (the `oscillator` control's
`events: 0`) and the record side runs at the audio rate, the tape recording at BIAS ADJUST's
setting through the reduction's measured bias map (BIAS as a knob, both tiers); production
renders the literal machine.

The output is the line output, wet only (the slap): the app's chain end and a session
insert mix it with the dry. The REPEAT pot sits in the output section (audio rate) and only
its feed resistor in the record side's multi-rate section, so the two share the pot's wiper,
a stiff node, a sample apart (inside a 133 ms loop).

Also writes config/circuits/ampex_351_2_echo.yaml, PING-PONG on the 351-2 (two 351
electronics, each with its own supply, on two tracks of one tape and one transport): the
echo's parts twice (the right channel's parts and nodes suffixed `_r`; both read the same
controls and values: identical machines, their parts drawn apart), the two-track heads, the
capstan's supply in a section of its own (both tapes on it: one wow and flutter), and the
console crossed: SEND into the left channel only, each return into the other channel's
record input (REPEAT gangs both), so the slap lands left, then right, then left.

Also writes config/circuits/ampex_351_insert.yaml, the machine itself as a session insert
(docs/TAPE_SPEED_PLAN.md, F2 / F5): the aligned 351 line in to line out with the same live
tier (the reduced tape, the oscillator out), no console, no VARISPEED.

The generated files say they are generated; edit their sources and rerun (`--check` exits 1 when
the file on disk differs: tests/test_351_echo.py).
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
from typing import Any

import yaml

from varimu.circuit import spec
from varimu.config import CONFIG_DIR, REPO_ROOT

BASE = "ampex_351"
OUT = "ampex_351_echo"
OUT_PINGPONG = "ampex_351_2_echo"
OUT_INSERT = "ampex_351_insert"
OUT_INSERT_2 = "ampex_351_2_insert"
ALIGNMENT = REPO_ROOT / "reports" / "tape" / "ampex_351_alignment.json"
#: Each speed's tape part and its reduction for the live qualities (config/tape_reductions/,
#: scripts/tape_reduction.py; a reduction is made for one medium, so one per speed).
REDUCTIONS = {"TP": "ampex_351", "TP_LO": "ampex_351_lo"}
#: The oscillator's passive network: in the echo file it goes with the tubes (`oscillator`).
OSCILLATOR_NETWORK = (
    "C35 C32 C36 R61 R62 R63 RT5A LT5A RT5B LT5B LT5S RT5S KAB KAS KBS R64 C33 C34 LER RER R70 C13"
).split()
ALIGNED_SOURCE = (
    "derived: the machine's alignment (reports/tape/ampex_351_alignment.json, "
    "varimu.measure.tape_align, key {key})"
)

LINE_AMP = "provisional: model knowledge (a 1950s console's tube line amplifier ahead of the send: "


def _line_amp(what: str) -> str:
    return f"{LINE_AMP}{what})"


CONTROLS = {
    "drive": {
        "value": 0.44,
        "min": 0.0,
        "max": 1.0,
        "unit": "rotation",
        "source": "provisional: the console's line amplifier gain into the send (engineers "
        "slammed the machine with it); an audio-taper pot ahead of the stage",
        "notes": "measured at 1 kHz into the send pot: 0 dB at 0.44 (the echo as it was), "
        "+2.6 dB at 0.5, +6.8 at 0.6, +12.9 at 0.75, +22.6 at 1; the tape compresses from "
        "~+5 dB over its operating level, then the record amplifier and the line "
        "amplifier's own 12AX7 clip too",
    },
    "capstan_hz": {
        "value": 60.0,
        "min": 40.0,
        "max": 80.0,
        "unit": "Hz",
        "source": "provisional: model knowledge (VARISPEED: the capstan's hysteresis "
        "synchronous motor fed from a variable-frequency oscillator and power amplifier "
        "instead of the mains, the studio trick; the range is the supply's, +-33%, not a "
        "printed figure)",
        "notes": "the tape's speed follows the frequency through the rotor's inertia (the "
        "transport's hunting, 2.5 Hz Q 3): the delay is 133 ms x 60 / f at 15 ips (267 ms "
        "at 7-1/2), and the repeats bend while it moves",
    },
    "send": {
        "value": 1.0,
        "min": 0.0,
        "max": 1.0,
        "unit": "rotation",
        "source": "provisional: the console's send to the machine (a 1950s passive bus; "
        "Sun's desk isn't sourced)",
        "notes": "full: 0 VU at the input records 3.5 dB under the operating level",
    },
    "repeat": {
        "value": 0.35,
        "min": 0.0,
        "max": 1.0,
        "unit": "rotation",
        "source": "provisional: the console's return from the repro output into the send "
        "(the Sun wiring)",
        "notes": "unity loop gain near 0.7 at 1 kHz (the machine's +-2 dB response moves it); "
        "past it the repeats build until the tape and the tubes saturate",
    },
}

VALUES = {
    "console_bplus_v": {"value": 250.0, "source": _line_amp("its own regulated supply")},
    "drive_pot_ohm": {"value": 250.0e3, "source": _line_amp("the DRIVE pot across the input")},
    "drive_taper_mid": {
        "value": 0.1,
        "source": _line_amp("an audio-taper pot, 10% of its track at half rotation"),
    },
    "r_dg_ohm": {"value": 10.0e3, "source": _line_amp("the 12AX7's grid stopper")},
    "r_dp_ohm": {"value": 100.0e3, "source": _line_amp("the 12AX7's plate load")},
    "r_dk_ohm": {
        "value": 1500.0,
        "source": _line_amp("the 12AX7's cathode resistor, unbypassed: ~+30 dB"),
    },
    "c_dc_f": {"value": 0.1e-6, "source": _line_amp("the interstage coupling capacitor")},
    "r_dpad1_ohm": {
        "value": 33.0e3,
        "source": _line_amp("the interstage pad's series arm: -2.5 dB with the shunt arm"),
    },
    "r_dpad2_ohm": {
        "value": 100.0e3,
        "source": _line_amp("the interstage pad's shunt arm, to the follower's bias node"),
    },
    "r_dcb1_ohm": {
        "value": 150.0e3,
        "source": _line_amp("the follower's grid bias divider from B+, ~+100 V: its headroom"),
    },
    "r_dcb2_ohm": {"value": 100.0e3, "source": _line_amp("the bias divider's foot")},
    "c_dcb_f": {"value": 10.0e-6, "source": _line_amp("the bias node's bypass")},
    "r_dck_ohm": {
        "value": 47.0e3,
        "source": _line_amp("the 12AU7 cathode follower's load, ~2 mA"),
    },
    "c_dout_f": {"value": 1.0e-6, "source": _line_amp("the output coupling into the send pot")},
    "send_pot_ohm": {
        "value": 10.0e3,
        "source": "provisional: model knowledge (a console's 10k fader across a low-impedance "
        "source)",
    },
    "repeat_pot_ohm": {
        "value": 10.0e3,
        "source": "provisional: model knowledge (a 10k pot across the 600 ohm line)",
    },
    "r_send_ohm": {
        "value": 22.0e3,
        "source": "provisional: model knowledge (a passive bus's isolating resistor; with "
        "the bridging input's 98.7k and the return's 82k: -3.5 dB from the send's wiper)",
    },
    "r_repeat_ohm": {
        "value": 82.0e3,
        "source": "provisional: model knowledge (sets full REPEAT ~3 dB over unity loop "
        "gain: -14.9 dB from the return's wiper into the bus against the machine's +18 dB "
        "from -10 dBm in to +8 dBm out)",
    },
}

HEADER = """# GENERATED by scripts/make_351_echo.py from config/circuits/{base}.yaml and
# reports/tape/ampex_351_alignment.json: don't edit; edit those and rerun (`uv run python
# scripts/make_351_echo.py`). The Ampex 351 as a studio's slap echo (docs/DELAY_PLAN.md,
# "The 351 echo"): the factory alignment as its settings, a passive console bus in front
# (SEND, and REPEAT from the line output back into the record side), the slap out (wet only).

"""


def live_machine(base: dict, alignment: dict, *, varispeed: bool) -> dict:
    """The aligned 351 with its live tier: production renders the literal machine; an events
    build (the live qualities) plays the tape's reduction with the oscillator out."""
    c = copy.deepcopy(base)
    # The aligned machine.
    for k, v in alignment["overrides"].items():
        ctl = c["controls"][k]
        ctl["value"] = float(v)
        ctl["source"] = ALIGNED_SOURCE.format(key=alignment["key"])
    # The live qualities (an events build): the tape plays its reduction at the aligned
    # bias, so the oscillator leaves its socket and the record side runs at the audio rate.
    c["controls"]["oscillator"]["events"] = 0
    heads = next(s for s in c["sections"] if s["title"] == "heads and tape")
    tapes = heads["parts"]["STP"]["parts"]
    if sorted(tapes) != sorted(REDUCTIONS):
        raise ValueError(f"ampex_351's tape parts changed: {sorted(tapes)}")
    for name, red in REDUCTIONS.items():
        tp = tapes[name]
        tp["reduction"] = red
        # BIAS: live, the reduced tape records at BIAS ADJUST's setting through the
        # reduction's measured map (the literal machine's oscillator sets it itself).
        tp["reduction_bias"] = "bias_adjust_f"
        if varispeed:
            # VARISPEED: the capstan's supply frequency as a node (1 V = 1 Hz), the motor
            # synchronous at the machine's mains frequency (either winding).
            tp["supply"] = "cap_hz"
            tp["supply_nominal_hz"] = "mains_hz"
    if varispeed:
        heads["parts"] = {"VCAP": {"V": ["cap_hz", "0"], "v": "capstan_hz"}, **heads["parts"]}
    # With its tubes out, the oscillator's passive network (1T5, the erase head and its
    # tuning, the grid networks, the bias feed) reaches the record head only through BIAS
    # ADJUST's ~31 pF and rings far above the audio band: live it leaves with the tubes (DK's
    # cost grows with the square of the states), production keeps every part.
    bias = next(s for s in c["sections"] if s["title"] == "bias and head driver")
    sw = bias["parts"]["SOSC"]
    moved = [k for k in bias["parts"] if k in OSCILLATOR_NETWORK]
    if sorted(moved) != sorted(OSCILLATOR_NETWORK):
        raise ValueError(f"ampex_351's oscillator network changed: {sorted(moved)}")
    for k in moved:
        sw["parts"][k] = {**bias["parts"].pop(k), "in": [1]}
    # The oscillator's nodes aren't there live: the live machine probes none of them.
    gone = {"ers", "p6a", "p6b", "g6a", "g6b", "sec"}
    c["probes"] = [n for n in c["probes"] if n not in gone]
    return c


def compose_insert(base: dict, alignment: dict) -> dict:
    """The 351 as a session insert (TAPE_SPEED_PLAN.md F2 / F5): the aligned machine, line in
    to line out, its live tier the reduced tape."""
    c = live_machine(base, alignment, varispeed=False)
    c["title"] = "Ampex 351 tape insert"
    return c


def compose(base: dict, alignment: dict) -> dict:
    c = live_machine(base, alignment, varispeed=True)
    c["title"] = "Ampex 351 slap echo"
    c["controls"] = {**CONTROLS, **c["controls"]}
    c["values"] = {**VALUES, **c["values"]}
    c["probes"] = [*c["probes"], "rin", "rpt"]
    secs: list[dict[str, Any]] = c["sections"]
    rec = next(s for s in secs if s["title"] == "record amplifier")
    out = next(s for s in secs if s["title"] == "output")
    parts = rec["parts"]
    if parts["RIN_S"]["R"][0] != "in":
        raise ValueError("ampex_351's bridging input no longer starts at `in`")
    parts["RIN_S"]["R"][0] = "rin"
    rec["parts"] = {
        # The console bus: the send's wiper and the return's into the bridging input.
        "RSB": {"R": ["snd", "rin"], "r": "r_send_ohm", "tolerance": "none"},
        "RRB": {"R": ["rpt", "rin"], "r": "r_repeat_ohm", "tolerance": "none"},
        **parts,
    }
    c["tolerance"]["classes"]["pot"] = [
        *c["tolerance"]["classes"]["pot"],
        "RDRV",
        "RSEND",
        "RREP",
    ]
    # DRIVE: the console's line amplifier ahead of the send (its own section at the audio
    # rate: the record side shares only the send pot's wiper with it).
    c["devices"] = {
        **c["devices"],
        "VDA": {"device": "12AX7@1", "tolerance": "tube"},
        "VDB": {"device": "12AU7@1", "tolerance": "tube"},
    }
    nt = {"tolerance": "none"}
    line_amp = {
        "VCB": {"V": ["cb", "0"], "v": "console_bplus_v"},
        "RDRV": {
            "pot": ["0", "dw", "in"],
            "r": "drive_pot_ohm",
            "at": "drive",
            "taper_mid": "drive_taper_mid",
        },
        "RDG": {"R": ["dw", "dg"], "r": "r_dg_ohm", **nt},
        "XVDA": {"device": ["dp", "dg", "dk"], "model": "VDA"},
        "RDP": {"R": ["cb", "dp"], "r": "r_dp_ohm", **nt},
        "RDK": {"R": ["dk", "0"], "r": "r_dk_ohm", **nt},
        "CDC": {"C": ["dp", "dpa"], "c": "c_dc_f", **nt},
        "RDPAD1": {"R": ["dpa", "dcg"], "r": "r_dpad1_ohm", **nt},
        "RDPAD2": {"R": ["dcg", "dcb"], "r": "r_dpad2_ohm", **nt},
        "RDCB1": {"R": ["cb", "dcb"], "r": "r_dcb1_ohm", **nt},
        "RDCB2": {"R": ["dcb", "0"], "r": "r_dcb2_ohm", **nt},
        "CDCB": {"C": ["dcb", "0"], "c": "c_dcb_f", **nt},
        "XVDB": {"device": ["cb", "dcg", "dck"], "model": "VDB"},
        "RDCK": {"R": ["dck", "0"], "r": "r_dck_ohm", **nt},
        "CDOUT": {"C": ["dck", "dout"], "c": "c_dout_f", **nt},
        "RSEND": {"pot": ["0", "snd", "dout"], "r": "send_pot_ohm", "at": "send"},
    }
    c["sections"] = [{"title": "console line amplifier", "parts": line_amp}, *c["sections"]]
    c["probes"] = [*c["probes"], "dp", "dout"]
    # The return's pot across the line output, at the audio rate.
    out["parts"] = {
        **out["parts"],
        "RREP": {"pot": ["0", "rpt", "out"], "r": "repeat_pot_ohm", "at": "repeat"},
    }
    return c


#: The 351-2's two-track heads (half the tape each, a guard band between).
TWO_TRACK = {
    "track_m": {
        "value": 1.905e-3,
        "source": "provisional: model knowledge (NAB two-track 1/4 in: 0.075 in tracks, "
        "the 351-2's head stack isn't in the manual)",
    },
    "rep_h_per_a": {
        "value": 2.46e7 * 5.94e-3 / 1.905e-3,
        "source": "derived: the full-track head's (2.46e7, calibrated to the drawing's -68 dB) "
        "times 5.94 / 1.905 mm: a two-track repro head wound for the full-track head's output "
        "(provisional), so the factory alignment carries over",
    },
}
PINGPONG_HEADER = """# GENERATED by scripts/make_351_echo.py from config/circuits/{base}.yaml and
# reports/tape/ampex_351_alignment.json: don't edit; edit those and rerun (`uv run python
# scripts/make_351_echo.py`). PING-PONG on the Ampex 351-2 (docs/DELAY_PLAN.md, "The 351
# echo"): the echo's two channels on two tracks of one tape, the console crossed; the left
# channel's line output is `out`, the right's `out_r`.

"""


def compose_pingpong(echo: dict) -> dict:
    """The 351-2 from the echo (see the module docs)."""
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    from compose_chain import Renamer

    c = copy.deepcopy(echo)
    c["title"] = "Ampex 351-2 ping-pong echo"
    for k, v in TWO_TRACK.items():
        c["values"][k] = v
    c["controls"]["repeat"]["notes"] = (
        "PING-PONG: each channel's return into the other's record input, ganged; unity loop "
        "gain per round trip near 0.7"
    )
    r = Renamer(c, "r", keep_nodes=("in", "cap_hz"))
    r.keys = set()  # both channels read the same controls and values
    secs: list[dict[str, Any]] = c["sections"]
    heads = next(s for s in secs if s["title"] == "heads and tape")
    vcap = heads["parts"].pop("VCAP")
    right = []
    for s in secs:
        if s["title"] == "console line amplifier":
            continue  # the send, its line amplifier and DRIVE: the left channel's only
        b = copy.deepcopy(s)
        b["title"] = f"{s['title']} (right)"
        b["parts"] = {r.part_name(n): r.part(p) for n, p in s["parts"].items()}
        right.append(b)
    rec_l = next(s for s in secs if s["title"] == "record amplifier")
    rec_r = next(s for s in right if s["title"] == "record amplifier (right)")
    # The console crossed: the send into the left only (the right's send has no source:
    # its 22k still loads the bus, so both directions cross at the mono echo's loop gain);
    # each return into the other side.
    rec_r["parts"]["RSB_r"]["R"] = ["0", "rin_r"]
    rec_l["parts"]["RRB"]["R"] = ["rpt_r", "rin"]
    rec_r["parts"]["RRB_r"]["R"] = ["rpt", "rin_r"]
    c["sections"] = [*secs, *right, {"title": "capstan", "parts": {"VCAP": vcap}}]
    left_only = {"VDA", "VDB", "RDRV", "RSEND"}  # the line amplifier's
    c["devices"] = {
        **c["devices"],
        **{f"{k}_r": v for k, v in c["devices"].items() if k not in left_only},
    }
    classes = c["tolerance"]["classes"]
    for cls, names in classes.items():
        classes[cls] = [*names, *(f"{n}_r" for n in names if n not in left_only)]
    c["probes"] = ["out", "out_r", "rin", "rin_r", "rpt", "rpt_r", "rh", "rh_r", "cap_hz"]
    return c


INSERT_HEADER = """# GENERATED by scripts/make_351_echo.py from config/circuits/{base}.yaml and
# reports/tape/ampex_351_alignment.json: don't edit; edit those and rerun (`uv run python
# scripts/make_351_echo.py`). The Ampex 351 as a session insert (docs/TAPE_SPEED_PLAN.md, F2):
# the factory alignment as its settings, line in to line out. Production renders the literal
# machine (the print); the live qualities play the tape's reduction with the oscillator out.

"""


def render() -> str:
    base = yaml.safe_load(spec.circuit_path(BASE).read_text(encoding="utf-8"))
    alignment = json.loads(ALIGNMENT.read_text(encoding="utf-8"))
    body = yaml.safe_dump(compose(base, alignment), sort_keys=False, width=100, allow_unicode=True)
    return HEADER.format(base=BASE) + body


def render_insert() -> str:
    base = yaml.safe_load(spec.circuit_path(BASE).read_text(encoding="utf-8"))
    alignment = json.loads(ALIGNMENT.read_text(encoding="utf-8"))
    c = compose_insert(base, alignment)
    body = yaml.safe_dump(c, sort_keys=False, width=100, allow_unicode=True)
    return INSERT_HEADER.format(base=BASE) + body


INSERT_2_HEADER = """# GENERATED by scripts/make_351_echo.py from config/circuits/{base}.yaml and
# reports/tape/ampex_351_alignment.json: don't edit; edit those and rerun (`uv run python
# scripts/make_351_echo.py`). The Ampex 351-2 as a session insert for stereo tracks
# (docs/TAPE_SPEED_PLAN.md, stereo): one channel of the two-track machine, the insert's
# electronics on a two-track head. The app prints a stereo track's right channel through it
# as the tape's second track (varimu-app's `Circuit::with_track`: the same transport, the
# coating's grain its own).

"""


def compose_insert_2(base: dict, alignment: dict) -> dict:
    """The 351-2 as a stereo insert: the insert's machine on the two-track heads."""
    c = compose_insert(base, alignment)
    c["title"] = "Ampex 351-2 tape insert (two-track)"
    for k, v in TWO_TRACK.items():
        c["values"][k] = v
    return c


def render_insert_2() -> str:
    base = yaml.safe_load(spec.circuit_path(BASE).read_text(encoding="utf-8"))
    alignment = json.loads(ALIGNMENT.read_text(encoding="utf-8"))
    c = compose_insert_2(base, alignment)
    body = yaml.safe_dump(c, sort_keys=False, width=100, allow_unicode=True)
    return INSERT_2_HEADER.format(base=BASE) + body


def render_pingpong() -> str:
    base = yaml.safe_load(spec.circuit_path(BASE).read_text(encoding="utf-8"))
    alignment = json.loads(ALIGNMENT.read_text(encoding="utf-8"))
    c = compose_pingpong(compose(base, alignment))
    body = yaml.safe_dump(c, sort_keys=False, width=100, allow_unicode=True)
    return PINGPONG_HEADER.format(base=BASE) + body


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    stale = False
    outs = (
        (OUT, render()),
        (OUT_PINGPONG, render_pingpong()),
        (OUT_INSERT, render_insert()),
        (OUT_INSERT_2, render_insert_2()),
    )
    for name, text in outs:
        path = CONFIG_DIR / "circuits" / f"{name}.yaml"
        if args.check:
            same = path.exists() and path.read_text(encoding="utf-8") == text
            print("current" if same else f"stale: {path}")
            stale = stale or not same
            continue
        path.write_text(text, encoding="utf-8")
        spec.load_circuit(path)  # it loads
        print(f"wrote {path}")
    if stale:
        sys.exit(1)


if __name__ == "__main__":
    main()
