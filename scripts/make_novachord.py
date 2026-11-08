# ruff: noqa: E501  (the generated circuit's values carry long source strings)
"""Generate the Hammond Novachord's circuit files from its service manual (docs/NOVACHORD_PLAN.md;
sources: data/schematics/hammond_novachord/README.md). Never edit the generated files; edit this
script and rerun.

    uv run python scripts/make_novachord.py [--check]

Writes:
  - config/circuits/novachord_note.yaml (NV1): one note name's whole chain, A: its oscillator
    (A6, 1760 Hz), the five dividers below it (A5 ... A1), the six control tubes and their
    playing keys, the attack switch, the cut-off bus, the shared output network of those
    keys' groups and the control box's tone stack, on ideal rails. `out` is the voltage the
    control box hands the preamplifier (across its 7 MEG input resistor's far end).

The circuit, as the manual draws it (2nd ed., Figs. 15-20; the serial 1700-and-above
oscillator):
  - oscillator (Fig. 15): a 6C8-G. Triode 1 on a tapped tuning coil (the coil's top on its
    grid; CN11 + CN12 across it to the ground tap; a cathode winding below the ground tap
    with RN18 20k || CN13 to ground, the self bias); its plate on RN17 60k from +270 V, out
    through CN1 to the first divider. The coil's upper tap feeds the top-octave control
    tube through RN19 1 MEG and triode 2's grid through CN10 .001; triode 2's plate (RN22
    50k) drives CN17 back onto the coil's top, its gain (so CN17's apparent capacitance) set
    by its grid bias, the vibrato's. With both vibrato switches off triode 2's cathode is
    open and CN31 (lower tap to ground) stands in for its mean capacitance.
  - dividers (Fig. 16, except the lowest octave): a 6W7-G whose cathode sits ~6 V above its
    grounded grid (RN6 1 MEG to -192 V); input through RN3 1 MEG, grid to ground through RN4
    2 MEG || RN13 (the adjustment resistor), CN2 grid to cathode, CN3 cathode to ground;
    plate RN5 500k from +270 V with CN4 to ground, out through CN1 to the next divider;
    screen and suppressor at +70 V. The cathode feeds its control tube through RN1 1 MEG.
    The lowest octave (Fig. 18): plate, screen and suppressor together at +70 V.
  - control tubes (Figs. 16, 17): a 6W7-G per key, normally cut off (its cathode held above
    its grounded grid by the cut-off bus); grid from the divider's cathode through RN1 and
    CN5, RN2 / CN29 / (CN30 at MELLOW) to ground; screen +34 V; cathode CN15 to ground and
    RN7 to the keying lead. Four adjacent tubes share a plate lead (RN23 from +270 V). The
    top octave's grid comes from the oscillator (RN19), RN8 50k at MELLOW, CN15 .05-.06,
    RN7 1 MEG.
  - playing key (Fig. 19): spring 3 rests on bus A and, key down, touches spring 2 (the
    keying lead, CN7 .25 to the keying supply's + rail); spring 1 rests on the cut-off bus
    (through RN10 to the keying lead) and lifts with the key or the sustaining pedal. Spring
    3's charge store CN8 .25 sits between A (RN12 30-75k) and C (RN11 1-5 MEG). The contacts
    are KEY_CONTACT / KEY_BREAK devices worked by the key's gate (a control input).
  - attack switch (manual p.16's table): bus A and bus C per position, ideal sources (the
    switch's RN52 strings aren't printed) behind a provisional 10k.
  - the cut-off divider (Fig. 19): RN38, six RN37 100 ohm, RN33 from +34 V; four taps (notes
    45-72, 13-44, 5-12, 1-4); the 260 V keying supply's + rail is the notes 1-4 tap (C32 .25).
  - control box (Fig. 20): per group of four, RN24 500k and CN18 onto the bus (RN26 250k),
    CN19 .14 and RN27 30k onto the tone stack (BRILLIANT, 3RD, 2ND, 1ST RESONATOR, DEEP, FULL
    in series to ground, each shunted by its control's resistor), out through RN54 7 MEG ||
    CN39. LN2-LN5 and the controls' resistors aren't printed (provisional).
Values printed as ranges ("may vary from note to note or octave to octave", p.5) are set per
note: the frequency-setting capacitors in proportion to the period (log-log between the
printed extremes over the notes they serve), the rest at the range's geometric middle
(provisional, the README's list).
"""

from __future__ import annotations

import argparse
import math
import sys

import yaml

from varimu.config import CONFIG_DIR

CIRC = CONFIG_DIR / "circuits"
SM2 = "Hammond, The Novachord: a manual for the service technician, 2nd ed."
NAMES = ("F", "F#", "G", "G#", "A", "A#", "B", "C", "C#", "D", "D#", "E")
A4_HZ = 440.0


def key_hz(key: int) -> float:
    """Key 1 is F1 (43.65 Hz), key 72 E7: twelve oscillators F6-E7 and five dividers each
    (SM2 p.5; Fig. 12's note A: 1760, 880, 440, 220, 110, 55 cycles)."""
    return A4_HZ * 2.0 ** ((key - 41) / 12.0)


def key_label(key: int) -> str:
    return f"{NAMES[(key - 1) % 12]}{(key - 1) // 12 + 1}".replace("#", "s")


LOW_HZ, HIGH_HZ = key_hz(1), key_hz(72)


def by_period(lo: float, hi: float, f_hz: float, f_lo: float, f_hi: float) -> float:
    """A printed range lo..hi spread over the notes f_lo..f_hi it serves, in proportion to the
    period (log-log): hi at f_lo, lo at f_hi."""
    t = math.log(f_hi / f_hz) / math.log(f_hi / f_lo)
    return lo * (hi / lo) ** t


def geo(lo: float, hi: float) -> float:
    return math.sqrt(lo * hi)


def val(v, source):
    return {"value": v, "source": source}


def fig(n, what):
    return f"{SM2} Fig. {n}: {what}"


# --- shared values ------------------------------------------------------------------------


def shared_values() -> dict:
    p = "provisional: model knowledge"
    v = {
        # supplies (ideal here; the power pack is NV3's)
        "b270_v": val(270.0, "SM2 Figs. 15-16, 20: +270 V; Fig. 24's terminal card"),
        "b70_v": val(70.0, "SM2 Figs. 16, 18: +70 V (the dividers' screens)"),
        "b34_v": val(
            34.0, "SM2 Figs. 16, 19: +34 V (the control tubes' screens, the cut-off divider)"
        ),
        "bias_v": val(-192.0, "SM2 Figs. 15-16: -192 V (the divider bias supply, tube I, p.11)"),
        "key_supply_v": val(260.0, "SM2 Fig. 19: the 260 V keying supply (rectifier tube J, p.11)"),
        "r_bus_ohm": val(
            10.0e3,
            f"{p} (the attack switch's RN52 strings aren't printed: a source resistance for buses A and C)",
        ),
        "r_in_ohm": val(1.0e6, "numerical: a load on the unused audio input"),
        "tube_osc": val("6C8G@1", "SM2 p.6, Fig. 15: a 6C8-G per oscillator"),
        "tube_div": val("6W7G@1", "SM2 Figs. 16-18: 6W7-G dividers and control tubes"),
        "key_make": val(
            "KEY_CONTACT@1", "SM2 Fig. 19: spring 3 onto spring 2 (closes with the key)"
        ),
        "key_break": val(
            "KEY_BREAK@1",
            "SM2 Fig. 19: spring 3 on bus A, spring 1 on the cut-off bus (open with the key or the sustaining cam)",
        ),
        "reed_make": val("REED_CONTACT@1", "SM2 Fig. 15, p.22: the vibrato reed's contact"),
        "reed_drive": val("REED_DRIVE@1", "SM2 Fig. 15, p.22: the reed's middle (drive) contact"),
        # cut-off divider (Fig. 19)
        "rn38_ohm": val(600.0, fig(19, "RN38 500 TO 700 (the range's middle)")),
        "rn37_ohm": val(100.0, fig(19, "RN37 100 (six)")),
        "rn33_ohm": val(2800.0, fig(19, "RN33 2800 (1300 with the +17 V supply in some)")),
        "c32_f": val(0.25e-6, fig(19, "C32 .25 (the keying supply's + rail to ground)")),
        "cn7_f": val(0.25e-6, fig(19, "CN7 .25")),
        "cn8_f": val(0.25e-6, fig(19, "CN8 .25")),
        "rn10_ohm": val(
            geo(180e3, 450e3),
            fig(
                19,
                "RN10 '180M TO 450M' (thousands: SM2 p.8's fast decay through it; the range's geometric middle)",
            ),
        ),
        "rn12_ohm": val(geo(30e3, 75e3), fig(19, "RN12 30,000 TO 75,000 (geometric middle)")),
        "rn11_ohm": val(geo(1e6, 5e6), fig(19, "RN11 1 TO 5 MEG (geometric middle)")),
        # control tubes (Fig. 16), values without a frequency: the range's middle
        "rn1_ohm": val(1.0e6, fig(16, "RN1 1 MEG")),
        "rn2_ohm": val(geo(150e3, 350e3), fig(16, "RN2 150,000 TO 350,000 (geometric middle)")),
        "cn29_f": val(geo(0.0005e-6, 0.002e-6), fig(16, "CN29 .0005 TO .002 (geometric middle)")),
        "rn7_ohm": val(geo(1.5e6, 5e6), fig(16, "RN7 1.5 TO 5 MEG (geometric middle)")),
        "rn7_top_ohm": val(1.0e6, fig(17, "RN7 1 MEG (the highest octave)")),
        "rn2_top_ohm": val(200e3, fig(17, "RN2 200,000 (the highest octave)")),
        "rn8_ohm": val(50e3, fig(17, "RN8 50,000 (the highest octave's MELLOW resistor)")),
        "cn15_top_f": val(0.055e-6, fig(17, "CN15 .05 TO .06 (the middle)")),
        # dividers (Fig. 16)
        "rn3_ohm": val(1.0e6, fig(16, "RN3 1 MEG")),
        "rn4_ohm": val(2.0e6, fig(16, "RN4 2 MEG")),
        "rn6_ohm": val(1.0e6, fig(16, "RN6 1 MEG")),
        "rn5_ohm": val(500e3, fig(16, "RN5 500,000")),
        # output network (Fig. 20)
        "rn23_ohm": val(geo(55e3, 100e3), fig(20, "RN23 55,000 TO 100,000 (geometric middle)")),
        "rn24_ohm": val(500e3, fig(20, "RN24 500,000")),
        "rn26_ohm": val(250e3, fig(20, "RN26 250,000")),
        "cn19_f": val(0.14e-6, fig(20, "CN19 .14")),
        "rn27_ohm": val(30e3, fig(20, "RN27 30,000")),
        "rn54_ohm": val(7.0e6, fig(20, "RN54 7 MEG")),
        "cn39_f": val(15e-12, fig(20, "CN39 .000015")),
        "rn48_ohm": val(1.0e6, fig(20, "RN48 1 MEG (DEEP TONE)")),
        "rn34_ohm": val(30e3, fig(20, "RN34 30,000 (FULL TONE)")),
        "rn61_ohm": val(
            15e3, fig(20, "RN61 15,000 (FULL, switched by BRIGHT-MELLOW; serial 1700 and above)")
        ),
        "cn21_f": val(0.008e-6, fig(20, "CN21 .008 (3RD RESONATOR)")),
        "cn22_f": val(0.023e-6, fig(20, "CN22 .023 (2ND RESONATOR)")),
        "cn23_f": val(0.065e-6, fig(20, "CN23 .065 (1ST RESONATOR)")),
        "cn20_f": val(
            0.05e-6,
            f"{p}: CN20 (DEEP TONE) isn't printed; .05 uF, a low-pass with RN48 and the stack below ~100 Hz-1 kHz by the switch's resistor",
        ),
        "ln_h": val(
            1.0,
            f"{p}: LN2-LN5 aren't printed; one coil type for all (Hammond's practice), 1 H: with CN23 / CN22 / CN21 the resonators at ~620, 1050 and 1780 Hz",
        ),
        "rln_ohm": val(250.0, f"{p}: the resonator coils' winding resistance (Q ~25 at 1 kHz)"),
        "r_tone_1_ohm": val(
            3e3,
            f"{p}: a tone control's shunt at position 1 (soft; the switches' resistors aren't printed)",
        ),
        "r_tone_2_ohm": val(10e3, f"{p}: position 2"),
        "r_tone_3_ohm": val(30e3, f"{p}: position 3 (loudest)"),
        "r_off_ohm": val(
            1.0e-3,
            "numerical: a control at OFF shorts its element (SM2 p.10: 'when any resonator is shorted out ... it has no effect')",
        ),
        "r_open_ohm": val(1.0e9, "numerical: a switch's open contact"),
        "r_contact_open_ohm": val(
            1.0e10,
            "provisional: model knowledge (an open key contact's insulation, 1e10-1e12 ohm; closed it is a pot's end, MIN_R_OHM; as tube_synth's switches)",
        ),
        "osc_kick_v": val(
            1.0,
            "numerical: the oscillators' tanks start 1 V off their DC point (a simulation has no noise to start them; SM2 p.2: 'allow about thirty seconds ... for the vacuum tubes to warm up')",
        ),
    }
    # The attack switch: SM2 p.16's table (DC volts, A / C; 'may vary from 10 to 15 per cent').
    # Position 1's A and position 7's printed without a sign: -268 V and +9 V (the + rail, the
    # notes 1-4 cut-off tap, Fig. 19), as positions 2-6 and p.15 ("-270 ... at 'fast'").
    table = {
        1: (-268, 9),
        2: (-235, -24),
        3: (-180, -40),
        4: (-125, -125),
        5: (-40, -180),
        6: (-24, -235),
        7: (9, -268),
    }
    for pos, (a, c) in table.items():
        v[f"attack{pos}_a_v"] = val(
            float(a), f"SM2 p.16, the attack switch table, position {pos}: A"
        )
        v[f"attack{pos}_c_v"] = val(
            float(c), f"SM2 p.16, the attack switch table, position {pos}: C"
        )
    return v


CONTROLS = {
    "attack": {
        "value": 4,
        "choices": [1, 2, 3, 4, 5, 6, 7],
        "unit": "position",
        "source": "SM2 pp.2, 8, 16: ATTACK, seven positions, 1 fast (percussive) to 7 slow (strings)",
    },
    "mellow": {
        "value": 0,
        "choices": [0, 1],
        "unit": "switch",
        "source": "SM2 p.2: BRIGHT-MELLOW (1 = mellow: CN30 into the control tubes' grids, RN8 on the top octave's, RN61 out of FULL; the lower 18 notes keep CN30 out)",
    },
    "brilliant": {
        "value": 0,
        "choices": [0, 1, 2, 3],
        "unit": "position",
        "source": "SM2 p.2: BRILLIANT TONE, off and three loudness positions",
    },
    "res3": {
        "value": 0,
        "choices": [0, 1, 2, 3],
        "unit": "position",
        "source": "SM2 p.2: THIRD RESONATOR",
    },
    "res2": {
        "value": 0,
        "choices": [0, 1, 2, 3],
        "unit": "position",
        "source": "SM2 p.2: SECOND RESONATOR",
    },
    "res1": {
        "value": 0,
        "choices": [0, 1, 2, 3],
        "unit": "position",
        "source": "SM2 p.2: FIRST RESONATOR",
    },
    "deep": {
        "value": 0,
        "choices": [0, 1, 2, 3],
        "unit": "position",
        "source": "SM2 p.2: DEEP TONE",
    },
    "full": {
        "value": 3,
        "choices": [0, 1, 2, 3],
        "unit": "position",
        "source": "SM2 p.2: FULL TONE ('may be used alone to provide even frequency response'); 3 the default (design choice)",
    },
    "normal_vibrato": {
        "value": 0,
        "choices": [0, 1],
        "unit": "switch",
        "source": "SM2 p.3: NORMAL VIBRATO",
    },
    "small_vibrato": {
        "value": 0,
        "choices": [0, 1],
        "unit": "switch",
        "source": "SM2 p.3: SMALL VIBRATO",
    },
}


def tone_element(name, top, bottom, control, element_parts, shunt_open=False):
    """One tone control: its element between top and bottom, shunted by the control's
    resistor (OFF shorts it; positions 1-3 the provisional resistors). FULL's position 3 is
    open (its element alone)."""
    parts = dict(element_parts)
    sw = {}
    for pos, key in (
        (0, "r_off_ohm"),
        (1, "r_tone_1_ohm"),
        (2, "r_tone_2_ohm"),
        (3, "r_tone_3_ohm"),
    ):
        sw[f"R{name}{pos}"] = {"R": [top, bottom], "r": key, "in": [pos]}
    parts[f"SW{name}"] = {"switch": control, "parts": sw}
    return parts


# --- one note's chain --------------------------------------------------------------------


TRIMS = CONFIG_DIR / "novachord_trims.yaml"
TRIM_SRC = "trim: scripts/novachord_trim.py (the manual's procedures, SM2 pp.20-22)"


def load_trims() -> dict:
    """The factory adjustments per note name (scripts/novachord_trim.py --write): the tuning
    coil's inductance (its movable core) and each divider's adjustment resistor RN13."""
    if not TRIMS.exists():
        return {}
    return yaml.safe_load(TRIMS.read_text(encoding="utf-8")).get("notes", {})


def note_chain(
    note: int, keys: list[int], trims: dict | None = None, key_mode: str = "contacts"
) -> tuple[dict, list, dict, dict]:
    """The oscillator for note index `note` (0 = F ... 11 = E) and its dividers, control
    tubes and keys (the keys of that note in `keys`). Returns (values, sections, devices,
    cv_inputs; with key_mode "switches", the keys' controls instead).

    key_mode "contacts": each key's springs are KEY_CONTACT / KEY_BREAK devices on control
    inputs (a gate `k<key>` for springs 3, `s<key>` for spring 1), stepped per sample.
    "switches": they are rheostats worked by 0 / 1 switch controls of the same names (a
    closed contact the pot's 1 mOhm end, an open one its insulation), always in the
    circuit, so a key changes values in place (a stream updated at each key event:
    scripts/novachord_render.py); no control inputs, no device ports."""
    n = NAMES[note].replace("#", "s")
    p = "provisional: model knowledge"
    trim = (trims or {}).get(n, {})
    values: dict = {}
    devices: dict = {}
    sections: list = []
    cv: dict = {}
    f_osc = key_hz(61 + note)
    pre = f"{n.lower()}_"

    def V(key, v, source):
        values[pre + key] = val(v, source)
        return pre + key

    # --- the oscillator (Fig. 15)
    cn12 = by_period(0.01e-6, 0.02e-6, f_osc, key_hz(61), key_hz(72))
    cn11 = 0.1 * cn12
    # the tank: CN11 + CN12, CN31 reflected through its tap, CN17 (triode 2 off)
    taps = (0.31, 0.66, 1.0)
    c_tank = cn11 + cn12 + taps[0] ** 2 * 0.008e-6 + 75e-12
    l_coil = 1.0 / ((2 * math.pi * f_osc) ** 2 * c_tank)
    coil_src = f"{p}: the tuning coil's upper winding, sized so the tank tunes to {f_osc:.2f} Hz with CN11 + CN12, CN31 through its tap and CN17 (the coil's inductance isn't printed)"
    if "coil_scale" in trim:
        l_coil *= trim["coil_scale"]
        coil_src += (
            f"; times {trim['coil_scale']:.5f}, the tuning ({TRIM_SRC}: the movable core, SM2 p.22)"
        )
    q_coil = 80.0
    r_coil = 2 * math.pi * f_osc * l_coil / q_coil
    k_cath = 0.15
    V("l_coil_h", l_coil, coil_src)
    V(
        "osc_hz",
        f_osc,
        "SM2 p.5, Fig. 12: the top octave F to E (A = 1760 cycles), equal temperament",
    )
    segs = (taps[0], taps[1] - taps[0], taps[2] - taps[1])
    for i, frac in enumerate(segs):
        V(
            f"l_seg{i + 1}_h",
            l_coil * frac**2,
            f"{p}: the upper winding's section {i + 1} ({frac:.2f} of its turns; the taps' places read off Fig. 15's drawing)",
        )
        V(
            f"r_seg{i + 1}_ohm",
            r_coil * frac,
            f"{p}: its winding resistance (the coil's Q {q_coil:.0f} at its note, 'a high Q tuned circuit', SM2 p.5)",
        )
    V(
        "l_cath_h",
        l_coil * k_cath**2,
        f"{p}: the cathode winding ({k_cath} of the upper winding's turns: SM2 p.5's 'little feedback voltage'; with more, the tank swings harder and the vibrato's triode 2 barely modulates: 0.375, read off Fig. 15's drawing, gave 2.8 cents of NORMAL vibrato, 0.15 gives 15)",
    )
    V("r_cath_ohm", r_coil * k_cath, f"{p}: its winding resistance")
    V("k_upper", 0.99, f"{p}: coupling between the upper winding's sections (one coil on one core)")
    V(
        "k_cath",
        0.9,
        f"{p}: the cathode winding's coupling (a separate winding; its sense the one that oscillates)",
    )
    V("cn12_f", cn12, fig(15, "CN12 .01 TO .02 (by the note's period over the top octave)"))
    V("cn11_f", cn11, fig(15, "CN11 'selected at factory' (a tenth of CN12: provisional)"))
    V("cn13_f", geo(0.08e-6, 0.14e-6), fig(15, "CN13 .08 TO .14 (geometric middle)"))
    V("rn18_ohm", 20e3, fig(15, "RN18 20,000"))
    V("cn10_f", 0.001e-6, fig(15, "CN10 .001"))
    V(
        "cn17_f",
        100e-12,
        fig(
            15,
            "CN17 .00005 TO .0001 (its top: below it triode 2's mean Miller capacitance is short of CN31's printed minimum, and NORMAL vibrato plays sharp, scripts/novachord_trim.py)",
        ),
    )
    V("rn17_ohm", 60e3, fig(15, "RN17 60,000"))
    V("rn22_ohm", 50e3, fig(15, "RN22 50,000"))
    V("rn19_ohm", 1.0e6, fig(15, "RN19 1 MEG"))
    V("rn16_ohm", 3.0e6, fig(15, "RN16 3 MEG"))
    V("rn14_ohm", 2.0e6, fig(15, "RN14 2 MEG"))
    if "cn31_f" in trim:
        V(
            "cn31_f",
            float(trim["cn31_f"]),
            f"{TRIM_SRC}: CN31 .005 TO .012 (Fig. 15) set so the average pitch is the same with and without NORMAL vibrato (SM2 p.21), within the printed range",
        )
    else:
        V(
            "cn31_f",
            geo(0.005e-6, 0.012e-6),
            fig(15, "CN31 .005 TO .012 (geometric middle, until the trim)"),
        )
    V(
        "cn1_osc_f",
        by_period(0.01e-6, 0.02e-6, f_osc, key_hz(61), key_hz(72)),
        fig(15, "CN1 .01 TO .02 (by the note's period)"),
    )
    devices[f"V{n}O"] = {"device": "tube_osc"}
    o = f"{n.lower()}o"
    tap1, tap2, top, kc, kw, pl1, pl2, g2, k2, bias2 = (
        f"{o}_{x}" for x in ("t1", "t2", "top", "k", "kw", "p1", "p2", "g2", "k2", "b2")
    )
    osc = {
        f"L{n}O1": {"L": ["0", f"{o}_m1"], "l": pre + "l_seg1_h"},
        f"R{n}O1": {"R": [f"{o}_m1", tap2], "r": pre + "r_seg1_ohm"},
        f"L{n}O2": {"L": [tap2, f"{o}_m2"], "l": pre + "l_seg2_h"},
        f"R{n}O2": {"R": [f"{o}_m2", tap1], "r": pre + "r_seg2_ohm"},
        f"L{n}O3": {"L": [tap1, f"{o}_m3"], "l": pre + "l_seg3_h"},
        f"R{n}O3": {"R": [f"{o}_m3", top], "r": pre + "r_seg3_ohm"},
        f"L{n}OK": {"L": [kc, f"{o}_mk"], "l": pre + "l_cath_h"},
        f"R{n}OK": {"R": [f"{o}_mk", kw], "r": pre + "r_cath_ohm"},
        f"K{n}O12": {"K": [f"L{n}O1", f"L{n}O2"], "k": pre + "k_upper"},
        f"K{n}O13": {"K": [f"L{n}O1", f"L{n}O3"], "k": pre + "k_upper"},
        f"K{n}O23": {"K": [f"L{n}O2", f"L{n}O3"], "k": pre + "k_upper"},
        f"K{n}O1K": {"K": [f"L{n}O1", f"L{n}OK"], "k": pre + "k_cath"},
        f"K{n}O2K": {"K": [f"L{n}O2", f"L{n}OK"], "k": pre + "k_cath"},
        f"K{n}O3K": {"K": [f"L{n}O3", f"L{n}OK"], "k": pre + "k_cath"},
        f"CN{n}11": {"C": [top, "0"], "c": pre + "cn11_f", "v0": "osc_kick_v"},
        f"CN{n}12": {"C": [top, "0"], "c": pre + "cn12_f"},
        f"CN{n}13": {"C": [kc, "0"], "c": pre + "cn13_f"},
        f"RN{n}18": {"R": [kc, "0"], "r": pre + "rn18_ohm"},
        f"X{n}O1": {"device": [pl1, top, kw], "model": f"V{n}O"},
        f"RN{n}17": {"R": ["b270", pl1], "r": pre + "rn17_ohm"},
        # triode 2, the vibrato's Miller stage
        f"CN{n}10": {"C": [tap1, g2], "c": pre + "cn10_f"},
        f"RN{n}16": {"R": [g2, "vib_b2"], "r": pre + "rn16_ohm"},
        f"RN{n}14": {"R": [g2, f"vib_p{note // 2}"], "r": pre + "rn14_ohm"},
        f"X{n}O2": {"device": [pl2, g2, k2], "model": f"V{n}O"},
        f"RN{n}22": {"R": ["b270", pl2], "r": pre + "rn22_ohm"},
        f"CN{n}17": {"C": [pl2, top], "c": pre + "cn17_f"},
        # NORMAL VIBRATO: OFF grounds CN31 (the compensation), ON grounds triode 2's cathode
        f"CN{n}31": {"C": [tap2, f"{o}_c31"], "c": pre + "cn31_f"},
        f"SW{n}NV": {
            "switch": "normal_vibrato",
            "parts": {
                f"RN{n}NV0": {"R": [f"{o}_c31", "0"], "r": "r_off_ohm", "in": [0]},
                f"RN{n}NV1": {"R": [k2, "0"], "r": "r_off_ohm", "in": [1]},
            },
        },
        # SMALL VIBRATO's second pole: triode 2's cathode through RN20 15,000
        f"SW{n}SV": {
            "switch": "small_vibrato",
            "parts": {
                f"RN{n}20": {"R": [k2, "0"], "r": "rn20_ohm", "in": [1]},
            },
        },
        f"RN{n}K2": {"R": [k2, "0"], "r": "r_open_ohm"},
        f"RN{n}C31": {"R": [f"{o}_c31", "0"], "r": "r_open_ohm"},
        f"CN{n}1O": {"C": [pl1, f"{n.lower()}d5_in"], "c": pre + "cn1_osc_f"},
    }
    sections.append({"title": f"oscillator {NAMES[note]}", "parts": osc})

    # --- the dividers (Figs. 16, 18), channel 5 (just below the oscillator) to 1
    for ch in range(5, 0, -1):
        key = 1 + (ch - 1) * 12 + note
        f_out = key_hz(key)
        d = f"{n.lower()}d{ch}"
        tag = f"{n}D{ch}"
        dv = f"d{ch}_"
        if ch >= 2:
            cn2 = by_period(0.0005e-6, 0.009e-6, f_out, key_hz(13), key_hz(60))
            cn3 = by_period(0.005e-6, 0.08e-6, f_out, key_hz(13), key_hz(60))
            src = "(by the output's period over notes 13-60, the dividers Fig. 16 serves)"
            V(dv + "cn2_f", cn2, fig(16, f"CN2 .0005 TO .009 {src}"))
            V(dv + "cn3_f", cn3, fig(16, f"CN3 .005 TO .08 {src}"))
            V(
                dv + "cn4_f",
                by_period(0.001e-6, 0.02e-6, f_out, key_hz(13), key_hz(60)),
                fig(16, f"CN4 .001 TO .02 {src}"),
            )
            V(
                dv + "cn1_f",
                by_period(0.001e-6, 0.02e-6, f_out, key_hz(13), key_hz(60)),
                fig(16, f"CN1 .001 TO .02 {src}"),
            )
        else:
            # Fig. 18 prints CN3 .009 TO .018; the model divides only near ten times that
            # (scripts/novachord_study.py's channel 1 sweep), where Fig. 16's own range lands
            # one octave down (.08 at F2): read as .09 TO .18, a probable misprint (open: the
            # README's gaps)
            cn3 = by_period(0.09e-6, 0.18e-6, f_out, key_hz(1), key_hz(12))
            V(
                dv + "cn3_f",
                cn3,
                f"{p}: Fig. 18 prints CN3 '.009 TO .018'; the model divides only near ten times that, where Fig. 16's range lands an octave down (.08 at F2): read as .09 TO .18 (a probable misprint, open), by the output's period over notes 1-12",
            )
            # CN2 isn't printed on Fig. 18: Fig. 16's ratio CN2 / CN3 at the same period
            ratio = 0.009 / 0.08
            V(
                dv + "cn2_f",
                ratio * cn3,
                f"{p}: CN2 isn't printed on Fig. 18; Fig. 16's CN2 / CN3 at the long end (.009 / .08) times this CN3",
            )
        rn13 = trim.get(f"d{ch}_rn13_ohm")
        if rn13 is None:
            V(
                dv + "rn13_ohm",
                2.0e6,
                f"{SM2} p.20: the adjustment resistor RN13, 1.7 to 2.5 MEG centres a divider (2 MEG until the trim, scripts/novachord_trim.py)",
            )
        else:
            V(
                dv + "rn13_ohm",
                float(rn13),
                f"{TRIM_SRC}: the adjustment resistor RN13 centring the divider in its range of correct division (SM2 p.20: 1.7 to 2.5 MEG, 1.2 to 3.5 in extremes)",
            )
        devices[f"V{tag}"] = {"device": "tube_div"}
        g, k, pl = f"{d}_g", f"{d}_k", f"{d}_p"
        parts = {
            f"RN{tag}3": {"R": [f"{d}_in", g], "r": "rn3_ohm"},
            f"RN{tag}4": {"R": [g, "0"], "r": "rn4_ohm"},
            f"RN{tag}13": {"R": [g, "0"], "r": pre + dv + "rn13_ohm"},
            f"CN{tag}2": {"C": [g, k], "c": pre + dv + "cn2_f"},
            f"CN{tag}3": {"C": [k, "0"], "c": pre + dv + "cn3_f"},
            f"RN{tag}6": {"R": [k, "bias"], "r": "rn6_ohm"},
        }
        if ch >= 2:
            parts |= {
                f"X{tag}": {"device": [pl, "b70", g, k], "model": f"V{tag}"},
                f"RN{tag}5": {"R": ["b270", pl], "r": "rn5_ohm"},
                f"CN{tag}4": {"C": [pl, "0"], "c": pre + dv + "cn4_f"},
                f"CN{tag}1": {"C": [pl, f"{n.lower()}d{ch - 1}_in"], "c": pre + dv + "cn1_f"},
            }
        else:
            parts[f"X{tag}"] = {"device": ["b70", "b70", g, k], "model": f"V{tag}"}
        sections.append({"title": f"divider {NAMES[note]} channel {ch}", "parts": parts})

    # --- control tubes and playing keys
    for key in keys:
        ch = (key - 1) // 12 + 1  # 1..6 (6 = the oscillator's octave)
        assert (key - 1) % 12 == note
        f_key = key_hz(key)
        lab = key_label(key)
        t = f"K{key}_"
        kv = f"k{key}_"
        cg, ck, kl, s3, s1, s1p, nx = (
            f"k{key}_{x}" for x in ("g", "k", "lead", "s3", "s1", "s1p", "x")
        )
        devices[f"VC{key}"] = {"device": "tube_div"}
        if key_mode == "contacts":
            for c in ("make", "brk", "s1k"):
                devices[f"C{c.upper()}{key}"] = {
                    "device": "key_make" if c == "make" else "key_break"
                }
        group = (key - 1) // 4  # four adjacent control tubes share a plate lead
        plate = f"grp{group}"
        parts: dict = {}
        if ch == 6:
            parts |= {
                f"RN{t}19": {"R": [f"{n.lower()}o_t1", cg], "r": pre + "rn19_ohm"},
                f"RN{t}2": {"R": [cg, "0"], "r": "rn2_top_ohm"},
                f"SW{t}M": {
                    "switch": "mellow",
                    "parts": {
                        f"RN{t}8": {"R": [cg, "0"], "r": "rn8_ohm", "in": [1]},
                    },
                },
                f"CN{t}15": {"C": [ck, "0"], "c": "cn15_top_f"},
                f"RN{t}7": {"R": [ck, kl], "r": "rn7_top_ohm"},
            }
        else:
            V(
                kv + "cn5_f",
                by_period(0.0005e-6, 0.02e-6, f_key, key_hz(1), key_hz(60)),
                fig(16, "CN5 .0005 TO .02 (by the note's period over notes 1-60)"),
            )
            V(
                kv + "cn15_f",
                by_period(0.03e-6, 0.19e-6, f_key, key_hz(1), key_hz(60)),
                fig(
                    16, "CN15 .03 TO .19 (by the note's period over notes 1-60: the cathode bypass)"
                ),
            )
            parts |= {
                f"RN{t}1": {"R": [f"{n.lower()}d{ch}_k", f"k{key}_c5"], "r": "rn1_ohm"},
                f"CN{t}5": {"C": [f"k{key}_c5", cg], "c": pre + kv + "cn5_f"},
                f"RN{t}2": {"R": [cg, "0"], "r": "rn2_ohm"},
                f"CN{t}29": {"C": [cg, "0"], "c": "cn29_f"},
                f"CN{t}15": {"C": [ck, "0"], "c": pre + kv + "cn15_f"},
                f"RN{t}7": {"R": [ck, kl], "r": "rn7_ohm"},
            }
            if key > 18:  # SM2 p.6: the lower eighteen notes have no CN30
                V(
                    kv + "cn30_f",
                    by_period(0.0005e-6, 0.005e-6, f_key, key_hz(19), key_hz(60)),
                    fig(16, "CN30 .0005 TO .005 (by the note's period over notes 19-60)"),
                )
                parts[f"SW{t}M"] = {
                    "switch": "mellow",
                    "parts": {
                        f"CN{t}30": {"C": [cg, "0"], "c": pre + kv + "cn30_f", "in": [1]},
                    },
                }
        parts[f"X{t}"] = {"device": [plate, "b34", cg, ck], "model": f"VC{key}"}
        # the playing key (Fig. 19)
        tap = "cut_y" if key >= 45 else "cut_o" if key >= 13 else "cut_r" if key >= 5 else "keyp"
        gate, lift = f"gate{key}", f"lift{key}"
        # the key's gate works springs 3 (0 / 1 V); spring 1 lifts with the key or the
        # sustaining cam (SM2 p.8: the pedal 'opens contact 1 on all keys'; the bass pedal the
        # lower 36): its own control input, the player's OR of the two (KEY_BREAK on it)
        if key_mode == "contacts":
            cv[f"k{key}"] = gate
            cv[f"s{key}"] = lift
            springs = {
                f"XS{t}1": {"device": [tap, s1, lift, "0"], "model": f"CS1K{key}"},
                f"XS{t}3A": {"device": ["abus", s3, gate, "0"], "model": f"CBRK{key}"},
                f"XS{t}3K": {"device": [s3, kl, gate, "0"], "model": f"CMAKE{key}"},
            }
        else:
            src = "SM2 Fig. 19: the playing key's springs (0 up, 1 down)"
            cv[f"k{key}"] = {
                "value": 0,
                "choices": [0, 1],
                "unit": "switch",
                "source": f"{src}: springs 3",
            }
            cv[f"s{key}"] = {
                "value": 0,
                "choices": [0, 1],
                "unit": "switch",
                "source": f"{src}: spring 1, lifted by the key or the sustaining cam",
            }
            springs = {
                f"RS{t}1": {"rheostat": [tap, s1], "r": "r_contact_open_ohm", "at": f"s{key}"},
                f"RS{t}3A": {"rheostat": ["abus", s3], "r": "r_contact_open_ohm", "at": f"k{key}"},
                f"RS{t}3K": {
                    "rheostat": [s3, kl],
                    "r": "r_contact_open_ohm",
                    "at": f"k{key}",
                    "reverse": 1,
                },
            }
        parts |= springs
        parts |= {
            f"CN{t}7": {"C": [kl, "keyp"], "c": "cn7_f"},
            f"RN{t}10": {"R": [s1, kl], "r": "rn10_ohm"},
            f"RN{t}12": {"R": [s3, nx], "r": "rn12_ohm"},
            f"CN{t}8": {"C": [nx, "keyp"], "c": "cn8_f"},
            f"RN{t}11": {"R": [nx, "cbus"], "r": "rn11_ohm"},
        }
        sections.append({"title": f"key {key} ({lab})", "parts": parts})
    return values, sections, devices, cv


REED_HZ = (6.5, 6.7, 6.9, 7.1, 7.3, 7.5)  # provisional: the six reeds' rates


def reed_section(r: int) -> dict:
    """Vibrato reed r (Fig. 15, '+ one used for each vibrato reed'; it serves the oscillators
    2r and 2r + 1: F / F#, G / G#, ... D# / E): its line RN39 off the shared bias, RN40 / CN16
    onto P (the two oscillators' RN14), the reed's contact grounding the line while the reed
    is on its positive half (SM2 p.6: closed half the time). The reed itself as a mechanical
    analogue (mobility: force = current, velocity = volts at `reed<r>_v`): its mass a
    capacitor, its spring an inductor (its current the spring's force, k x), its loss a
    resistor; the displacement read off the spring's current (a 1 mOhm sense, a G into a
    resistor: `reed<r>_x`, 1 V per mm) works the contacts. The drive coil LN6 from -50 V
    through RN25 1,000 to ground; the middle contact shorts RN25 on the reed's negative half;
    the coil's current pulls the reed (a G into the velocity node), lagging by its L / R, so
    it keeps swinging (SM2 p.3: 'kept in motion by electrical means'). The STARTER lever
    ('lift and release', SM2 p.3): a force on the reed from a capacitor held at its start
    voltage for the DC point only (the reed deflected 0.6 mm at the start), released within a
    millisecond as the run starts."""
    v, x, ln, pp = f"reed{r}_v", f"reed{r}_x", f"vib_line{r}", f"vib_p{r}"
    d1, d2, d3 = f"reed{r}_d1", f"reed{r}_d2", f"reed{r}_d3"
    return {
        f"RN39R{r}": {"R": ["vib_n36", ln], "r": "rn39_ohm"},
        f"RN40R{r}": {"R": [ln, pp], "r": "rn40_ohm"},
        f"CN16R{r}": {"C": [pp, "0"], "c": "cn16_f"},
        f"XRC{r}": {"device": [ln, "0", x, "0"], "model": f"CREED{r}"},
        # the reed: mass, spring, loss at the velocity node; the displacement
        f"CRM{r}": {"C": [v, "0"], "c": "reed_mass_kg"},
        f"LRK{r}": {"L": [v, f"reed{r}_k"], "l": f"reed{r}_compliance_m_n"},
        f"RRK{r}": {"R": [f"reed{r}_k", "0"], "r": "reed_k_sense_ohm"},
        f"RRC{r}": {"R": [v, "0"], "r": f"reed{r}_r_mech"},
        f"GRX{r}": {"G": ["0", x, f"reed{r}_k", "0"], "gm": "reed_x_gm"},
        f"RRX{r}": {"R": [x, "0"], "r": f"reed{r}_x_ohm"},
        f"CST{r}": {"C": [f"reed{r}_st", "0"], "c": "reed_starter_f", "v0": "reed_starter_v"},
        f"RST{r}": {"R": [f"reed{r}_st", "0"], "r": "reed_starter_ohm"},
        f"GST{r}": {"G": ["0", v, f"reed{r}_st", "0"], "gm": f"reed{r}_starter_gm"},
        # the drive coil LN6, RN25, the drive contact; the coil's current as the force
        f"LN6R{r}": {"L": ["bn50", d1], "l": "ln6_h"},
        f"RLN6R{r}": {"R": [d1, d2], "r": "ln6_r_ohm"},
        f"RSNS{r}": {"R": [d2, d3], "r": "reed_sense_ohm"},
        f"RN25R{r}": {"R": [d3, "0"], "r": "rn25_ohm"},
        f"XRD{r}": {"device": [d3, "0", x, "0"], "model": f"CDRV{r}"},
        f"GRF{r}": {"G": ["0", v, d3, d2], "gm": "reed_force_gm"},
    }


def reed_values() -> dict:
    p = "provisional: model knowledge"
    m = 5.0e-3
    q = 50.0
    out = {
        "bn50_v": val(-50.0, "SM2 Fig. 15, p.11: the vibrato drive coils' 50 V supply (tube H)"),
        "rn25_ohm": val(1.0e3, fig(15, "RN25 1,000 (one per reed)")),
        "reed_mass_kg": val(
            m,
            f"{p}: a vibrato reed's moving mass (a steel reed some inches long; mobility analogue, 1 F = 1 kg)",
        ),
        "reed_starter_f": val(
            1.0e-6,
            "numerical: the STARTER lever (SM2 p.3: 'lift and release'): its force held by a capacitor at its start voltage for the DC point only, released through 1k (1 ms)",
        ),
        "reed_starter_v": val(1.0, "numerical: the STARTER's hold, 1 V"),
        "reed_starter_ohm": val(1.0e3, "numerical: the STARTER's release"),
        "reed_k_sense_ohm": val(
            1.0e-3,
            "numerical: the spring's current sensed (a loss of Q > 4000, against the reed's 50)",
        ),
        "reed_x_gm": val(
            1.0,
            "numerical: the displacement node's transconductance (with its resistor, 1 V per mm)",
        ),
        "ln6_h": val(
            10.0, f"{p}: the drive coil LN6's inductance (its L / R lag, ~20 ms, pumps the reed)"
        ),
        "ln6_r_ohm": val(
            500.0,
            f"{p}: the drive coil's resistance (100 mA with its contact closed, 33 mA through RN25)",
        ),
        "reed_sense_ohm": val(1.0, "numerical: the drive coil's current sensed for its force"),
        "reed_force_gm": val(
            4.5e-3, f"{p}: the coil's pull, 4.5 mN per A (a ~1 mm swing at Q {q:.0f})"
        ),
    }
    for r, f in enumerate(REED_HZ):
        k = m * (2 * math.pi * f) ** 2
        out[f"reed{r}_compliance_m_n"] = val(
            1.0 / k,
            f"{p}: reed {r}'s spring, tuned to {f} Hz with its mass (SM2 p.6: 'six reeds vibrating at different rates'; 'in the order of seven per second', US 2,126,682)",
        )
        out[f"reed{r}_r_mech"] = val(
            q / (m * 2 * math.pi * f),
            f"{p}: reed {r}'s loss as a mechanical resistance's inverse (Q {q:.0f})",
        )
        out[f"reed{r}_starter_gm"] = val(
            k * 0.6e-3, f"{p}: the STARTER's lift, 0.6 mm (k x 0.6 mm per volt held)"
        )
        # x = i_spring / k; V(x) = gm R i_spring R_sense = 1000 x (1 V per mm)
        out[f"reed{r}_x_ohm"] = val(
            1000.0 / (k * 1.0e-3 * 1.0),
            "numerical: the displacement node's resistor (1 V per mm: 1000 / (k x sense x gm))",
        )
    return out


def shared_sections(groups: list[int], full: bool = False, reeds: tuple = tuple(range(6))) -> list:
    """The supplies, the cut-off bus, the attack switch, the vibrato's shared bias network and
    the control box (for the plate groups in `groups`)."""
    att_a = {
        f"VA{p}": {"V": ["abus_s", "0"], "v": f"attack{p}_a_v", "in": [p]} for p in range(1, 8)
    }
    att_c = {
        f"VC{p}": {"V": ["cbus_s", "0"], "v": f"attack{p}_c_v", "in": [p]} for p in range(1, 8)
    }
    supply = {
        "VB270": {"V": ["b270", "0"], "v": "b270_v"},
        "VB70": {"V": ["b70", "0"], "v": "b70_v"},
        "VB34": {"V": ["b34", "0"], "v": "b34_v"},
        "VBIAS": {"V": ["bias", "0"], "v": "bias_v"},
        "VBN50": {"V": ["bn50", "0"], "v": "bn50_v"},
    }
    keying = {
        "RIN": {"R": ["in", "0"], "r": "r_in_ohm"},
        # the cut-off divider (Fig. 19): ground, RN38, RN37 x 6, RN33, +34 V
        "RN38": {"R": ["0", "cd1"], "r": "rn38_ohm"},
        "RN37A": {"R": ["cd1", "cd2"], "r": "rn37_ohm"},
        "RN37B": {"R": ["cd2", "cut_y"], "r": "rn37_ohm"},
        "RN37C": {"R": ["cut_y", "cut_o"], "r": "rn37_ohm"},
        "RN37D": {"R": ["cut_o", "cut_r"], "r": "rn37_ohm"},
        "RN37E": {"R": ["cut_r", "keyp"], "r": "rn37_ohm"},
        "RN37F": {"R": ["keyp", "cd7"], "r": "rn37_ohm"},
        "RN33": {"R": ["cd7", "b34"], "r": "rn33_ohm"},
        "C32": {"C": ["keyp", "0"], "c": "c32_f"},
        # the attack switch: buses A and C
        "SWATA": {"switch": "attack", "parts": att_a},
        "SWATC": {"switch": "attack", "parts": att_c},
        "RBUSA": {"R": ["abus_s", "abus"], "r": "r_bus_ohm"},
        "RBUSC": {"R": ["cbus_s", "cbus"], "r": "r_bus_ohm"},
    }
    # the vibrato's shared bias network (Fig. 15, '* one used for all oscillators'), the reed
    # line held open until the reeds (NV2): RN35 / RN36 / RN32 off -192 V, RN31 / RN15 (/ RN21
    # at SMALL) to triode 2's grid return
    vib = {
        "RN32": {"R": ["bias", "vib_top"], "r": "rn32_ohm"},
        "RN35": {"R": ["vib_top", "vib_n36"], "r": "rn35_ohm"},
        "RN36": {"R": ["vib_n36", "0"], "r": "rn36_ohm"},
        "SWSV1": {
            "switch": "small_vibrato",
            "parts": {
                # the first pole shorts RN35 at OFF (the reed line's full swing for NORMAL), so
                # SMALL is a shallower swing plus triode 2's degeneration (RN20): NORMAL 15 c,
                # SMALL 1 c (SM2 p.3: 'Normal Vibrato produces a greater variation'). Read the
                # other way (closed at ON, as its other poles) NORMAL fell to 2 c; either way NORMAL
                # and SMALL together don't deepen it as p.3 says (an open gap, docs/NOVACHORD_PLAN.md)
                "RNSV1": {"R": ["vib_top", "vib_n36"], "r": "r_off_ohm", "in": [0]},
            },
        },
        "RN31": {"R": ["bias", "vib_b2"], "r": "rn31_ohm"},
        "RN15": {"R": ["vib_b2", "0"], "r": "rn15_ohm"},
        "SWSV3": {
            "switch": "small_vibrato",
            "parts": {
                "RN21": {"R": ["vib_b2", "0"], "r": "rn21_ohm", "in": [1]},
            },
        },
    }
    box = {
        "RN26": {"R": ["bus", "0"], "r": "rn26_ohm"},
        "CN19": {"C": ["bus", "bus_c"], "c": "cn19_f"},
        "RN27": {"R": ["bus_c", "tone"], "r": "rn27_ohm"},
    }
    for g in groups:
        box |= {
            f"RN23G{g}": {"R": ["bct" if full else "b270", f"grp{g}"], "r": "rn23_ohm"},
            f"RN24G{g}": {"R": [f"grp{g}", f"grp{g}_r"], "r": "rn24_ohm"},
            f"CN18G{g}": {"C": [f"grp{g}_r", "bus"], "c": f"cn18_g{g}_f"},
        }
    # the tone stack, top to ground
    box |= tone_element(
        "BR",
        "tone",
        "ts1",
        "brilliant",
        {
            "LN2": {"L": ["tone", "ln2"], "l": "ln_h"},
            "RLN2": {"R": ["ln2", "ts1"], "r": "rln_ohm"},
        },
    )
    for name, ctl, top, bot, c in (
        ("R3", "res3", "ts1", "ts2", "cn21_f"),
        ("R2", "res2", "ts2", "ts3", "cn22_f"),
        ("R1", "res1", "ts3", "ts4", "cn23_f"),
    ):
        box |= tone_element(
            name,
            top,
            bot,
            ctl,
            {
                f"L{name}": {"L": [top, f"{name.lower()}_l"], "l": "ln_h"},
                f"RL{name}": {"R": [f"{name.lower()}_l", bot], "r": "rln_ohm"},
                f"C{name}": {"C": [top, bot], "c": c},
            },
        )
    box |= tone_element(
        "DP",
        "ts4",
        "ts5",
        "deep",
        {
            "RN48": {"R": ["ts4", "ts5"], "r": "rn48_ohm"},
            "CN20": {"C": ["ts4", "ts5"], "c": "cn20_f"},
        },
    )
    full_tone = tone_element(
        "FL", "ts5", "0", "full", {"RN34": {"R": ["ts5", "0"], "r": "rn34_ohm"}}
    )
    full_tone["SWFL"]["parts"].pop("RFL3")  # position 3: RN34 alone
    full_tone["SWFLM"] = {
        "switch": "mellow",
        "parts": {"RN61": {"R": ["ts5", "0"], "r": "rn61_ohm", "in": [0]}},
    }
    box |= full_tone
    cb = "cbox" if full else "out"
    box |= {
        "RN54": {"R": ["tone", cb], "r": "rn54_ohm"},
        "CN39": {"C": ["tone", cb], "c": "cn39_f"},
    }
    if not full:
        box["RPRE"] = {"R": ["out", "0"], "r": "r_pre_in_ohm"}
        return [
            {"title": "supply", "parts": supply},
            {"title": "keying", "parts": keying},
            {"title": "vibrato bias", "parts": vib},
            *({"title": f"vibrato reed {r}", "parts": reed_section(r)} for r in reeds),
            {"title": "control box", "parts": box},
        ]
    # VOLUME (Fig. 20): four positions shunting the preamplifier's input (a provisional reading
    # of the drawing's contacts: 4 none, 3 RN56 || CN41, 2 RN55 || CN40, 1 both)
    box["SWVOL"] = {
        "switch": "volume",
        "parts": {
            "RN56": {"R": ["cbox", "0"], "r": "rn56_ohm", "in": [1, 3]},
            "CN41": {"C": ["cbox", "0"], "c": "cn41_f", "in": [1, 3]},
            "RN55": {"R": ["cbox", "0"], "r": "rn55_ohm", "in": [1, 2]},
            "CN40": {"C": ["cbox", "0"], "c": "cn40_f", "in": [1, 2]},
        },
    }
    supply["VB260"] = {"V": ["b260", "0"], "v": "b260_v"}
    box |= {
        "RPF1": {"R": ["b260", "bct"], "r": "pre_r_ct_ohm"},
        "CPF1": {"C": ["bct", "0"], "c": "pre_c_ct_f"},
    }
    # the preamplifier (Fig. 21)
    pre = {
        "CVADJ": {"C": ["cbox", "pin"], "c": "pre_c_volume_adjust_f"},
        "CEXPR": {"C": ["pin", "pfb"], "c": "expression_c_f"},
        "RPF5A": {"R": ["pin", "pm2"], "r": "pre_r_fb_ohm"},
        "RPF5B": {"R": ["pm2", "pfb"], "r": "pre_r_fb_ohm"},
        "CPFB": {"C": ["pfb", "p7"], "c": "pre_c_couple_f"},
        "RPST": {"R": ["pin", "g7"], "r": "pre_r_stopper_ohm"},
        "RPM2": {"R": ["pm2", "pj"], "r": "pre_r_tie_ohm"},
        "RPB1": {"R": ["bias", "pnb"], "r": "pre_r_bias1_ohm"},
        "CPB1": {"C": ["pnb", "0"], "c": "pre_c_bias_f"},
        "RPB2": {"R": ["pnb", "pj"], "r": "pre_r_bias2_ohm"},
        "RPB3": {"R": ["pj", "0"], "r": "pre_r_bias3_ohm"},
        "XP7": {"device": ["p7", "s7", "g7", "0"], "model": "VP7"},
        "RPL7": {"R": ["pn2", "p7"], "r": "pre_r_plate7_ohm"},
        "CPN2": {"C": ["pn2", "0"], "c": "pre_c_n2_f"},
        "RPS7": {"R": ["pn2", "s7"], "r": "pre_r_screen7_ohm"},
        "CPS7": {"C": ["s7", "0"], "c": "pre_c_screen7_f"},
        "RPN2": {"R": ["b260", "pn2"], "r": "pre_r_n2_ohm"},
        "RPNB": {"R": ["b260", "pnb5"], "r": "pre_r_nb_ohm"},
        "CPNB": {"C": ["pnb5", "0"], "c": "pre_c_1uf_f"},
        "CPG5": {"C": ["p7", "g5"], "c": "pre_c_couple_f"},
        "RPG5": {"R": ["g5", "pnb"], "r": "pre_r_grid5_ohm"},
        "XP5": {"device": ["p5", "g5", "k5"], "model": "VP5"},
        "RPK5": {"R": ["k5", "0"], "r": "pre_r_k5_ohm"},
        "RPK5F": {"R": ["k5", "pafb"], "r": "pre_r_k5fb_ohm"},
        # the 56 ohm from the power amplifier's output terminal (Fig. 21): the voice coils;
        # without the power amplifier (AMP off), the binding post's 12 ohm to ground (SM2
        # p.10: a separate tone cabinet), and `out` the preamplifier's 500 ohm line
        "SWAMPF": {
            "switch": "amp",
            "parts": {
                "RPPOST": {"R": ["pafb", "spk"], "r": "r_off_ohm", "in": [1]},
                "RPPOST0": {"R": ["pafb", "0"], "r": "pre_r_post_ohm", "in": [0]},
                "RLINE": {"R": ["pre_out", "out"], "r": "r_off_ohm", "in": [0]},
                "RLINEL": {"R": ["out", "0"], "r": "r_in_ohm", "in": [0]},
            },
        },
        # A0-17553-0: the 6J5-G's plate transformer, a 500 ohm push-pull output, 2,500 across it
        "LPT1": {"L": ["pnb5", "pt1"], "l": "pre_t_lp_h"},
        "RPT1": {"R": ["pt1", "p5"], "r": "pre_t_rp_ohm"},
        "LPT2A": {"L": ["0", "pt2a"], "l": "pre_t_ls_h"},
        "RPT2A": {"R": ["pt2a", "pre_out"], "r": "pre_t_rs_ohm"},
        "LPT2B": {"L": ["pre_out_b", "pt2b"], "l": "pre_t_ls_h"},
        "RPT2B": {"R": ["pt2b", "0"], "r": "pre_t_rs_ohm"},
        "KPT1A": {"K": ["LPT1", "LPT2A"], "k": "pre_t_k"},
        "KPT1B": {"K": ["LPT1", "LPT2B"], "k": "pre_t_k"},
        "KPT2": {"K": ["LPT2A", "LPT2B"], "k": "pre_t_k"},
        "RPLOAD": {"R": ["pre_out", "pre_out_b"], "r": "pre_r_load_ohm"},
    }
    # the power amplifier (Fig. 22, the Hammond organ amplifier): two 56s push-pull from the
    # preamplifier's secondary (its centre tap grounded), a shared 2,000 ohm cathode resistor,
    # 75,000 plate loads; .3 into four 2A3s push-pull parallel (75,000 grid returns to the
    # bias), the output transformer into the two 12-inch speakers' voice coils
    amp_parts = {
        "XPA56A": {"device": ["pa_p1", "pre_out", "pa_k"], "model": "VPA56A"},
        "XPA56B": {"device": ["pa_p2", "pre_out_b", "pa_k"], "model": "VPA56B"},
        "RPAK": {"R": ["pa_k", "0"], "r": "pa_r_k56_ohm"},
        "RPAL1": {"R": ["bpa1", "pa_p1"], "r": "pa_r_plate56_ohm"},
        "RPAL2": {"R": ["bpa1", "pa_p2"], "r": "pa_r_plate56_ohm"},
        "CPAC1": {"C": ["pa_p1", "pa_g1"], "c": "pa_c_couple_f"},
        "CPAC2": {"C": ["pa_p2", "pa_g2"], "c": "pa_c_couple_f"},
        "RPAG1": {"R": ["pa_g1", "pa_bias"], "r": "pa_r_grid_ohm"},
        "RPAG2": {"R": ["pa_g2", "pa_bias"], "r": "pa_r_grid_ohm"},
        "CPAB": {"C": ["pa_bias", "0"], "c": "pa_c_bias_f"},
        "RPAB": {"R": ["pa_bias_s", "pa_bias"], "r": "pa_r_bias_ohm"},
        "XPA3A": {"device": ["pa_q1", "pa_g1", "0"], "model": "VPA3A"},
        "XPA3B": {"device": ["pa_q1", "pa_g1", "0"], "model": "VPA3B"},
        "XPA3C": {"device": ["pa_q2", "pa_g2", "0"], "model": "VPA3C"},
        "XPA3D": {"device": ["pa_q2", "pa_g2", "0"], "model": "VPA3D"},
        "TPA": {
            "transformer": {
                "pa": {"nodes": ["pa_q1", "bpa"]},
                "pb": {"nodes": ["bpa", "pa_q2"]},
                "s": {
                    "nodes": ["0", "spk"]
                },  # the sense that makes the 6J5-G's feedback oppose (SM2 p.10)
            },
            "component": "pa_ot_model",
        },
        "SPK1": {
            "speaker": ["spk", "0", "out"],
            "component": "speaker_model",
            "distance_m": "listen_distance_m",
            "width_m": "cab_width_m",
            "height_m": "cab_height_m",
            "depth_m": "cab_depth_m",
            "offset_x_m": "cab_offset_x_m",
        },
        "SPK2": {
            "speaker": ["spk", "0", "spk2_out"],
            "component": "speaker_model",
            "distance_m": "listen_distance_m",
            "width_m": "cab_width_m",
            "height_m": "cab_height_m",
            "depth_m": "cab_depth_m",
            "offset_x_m": "cab_offset_x2_m",
            "readout": 0,
        },
    }
    amp = {"SWAMP": {"switch": "amp", "parts": {k: v | {"in": [1]} for k, v in amp_parts.items()}}}
    supply["SWAMPS"] = {
        "switch": "amp",
        "parts": {
            "VBPA": {"V": ["bpa", "0"], "v": "pa_b_plus_v", "in": [1]},
            "VBPA1": {"V": ["bpa1", "0"], "v": "pa_b_plus_driver_v", "in": [1]},
            "VPAB": {"V": ["pa_bias_s", "0"], "v": "pa_bias_v", "in": [1]},
        },
    }
    return [
        {"title": "supply", "parts": supply},
        {"title": "keying", "parts": keying},
        {"title": "vibrato bias", "parts": vib},
        *({"title": f"vibrato reed {r}", "parts": reed_section(r)} for r in reeds),
        {"title": "control box", "parts": box},
        {"title": "preamplifier", "parts": pre},
        {"title": "power amplifier", "parts": amp},
    ]


def partition(groups_of: int = 4) -> list[str]:
    """The render partition (circuitsim's N parts, the titles of each part, "|" between):
    each group of `groups_of` note names (oscillator and dividers) a part of its own; the
    keys (72 control tubes and their key circuits: shared plate leads, keying buses and B+,
    which a part must own with a DC path), the control box and the preamplifier the main
    part; the rails and the vibrato's bias last (their owner). The cuts: each divider's
    cathode and each oscillator's tap into its control tubes' grid networks (RN1 / RN19,
    1 MEG: each side sees the other a sample late) and the rails."""
    out: list[str] = []
    for start in range(0, 12, groups_of):
        if out:
            out.append("|")
        for note in range(start, start + groups_of):
            out.append(f"oscillator {NAMES[note]}")
            out += [f"divider {NAMES[note]} channel {ch}" for ch in range(5, 0, -1)]
    return out + ["|", "supply", "vibrato bias", *(f"vibrato reed {r}" for r in range(6))]


def preamp_values() -> dict:
    p = "provisional: model knowledge"

    def f21(what):
        return fig(21, what)

    return {
        "b260_v": val(260.0, f21("+260 V (the power pack's 270 V line, Fig. 24)")),
        "pre_r_ct_ohm": val(
            100e3,
            f21(
                "100,000: the control tubes' B+ ('+270 V from filter in pre-amplifier', Fig. 20) off +260 V"
            ),
        ),
        "pre_c_ct_f": val(4e-6, f21("4 MFD")),
        "pre_c_volume_adjust_f": val(
            geo(0.0003e-6, 0.00072e-6),
            f21("VOLUME ADJUST .0003 TO .00072 (set at the factory; geometric middle)"),
        ),
        "expression_c_f": val(
            150e-12,
            f"{p}: the EXPRESSION CONTROL's variable condenser (unprinted range; 'a reduction in its capacity increases the volume', SM2 p.10): mid-pedal 150 pF (25-500 pF assumed)",
        ),
        "pre_r_fb_ohm": val(5e6, f21("5 MEG (two, the feedback path)")),
        "pre_c_couple_f": val(0.0234e-6, f21(".0234 (two)")),
        "pre_r_stopper_ohm": val(
            50e3,
            f21(
                "50,000 (SM2 p.10: 'a 50,000 ohm resistor in series with the control grid of the 6J7-G')"
            ),
        ),
        "pre_r_tie_ohm": val(
            1.0,
            "numerical: the 5 MEGs' midpoint wired to the bias divider's 20,000 / 50,000 junction (Fig. 21)",
        ),
        "pre_r_bias1_ohm": val(2e6, f21("2 MEG off -192 V")),
        "pre_c_bias_f": val(0.255e-6, f21(".255")),
        "pre_r_bias2_ohm": val(50e3, f21("50,000")),
        "pre_r_bias3_ohm": val(20e3, f21("20,000 to ground")),
        "tube_pre7": val(
            "6W7G@1",
            "SM2 Fig. 21: a 6J7-G; RCA's 6W7-G sheet: the 6J7's curves apply to the 6W7-G (the same structure)",
        ),
        "tube_pre5": val("6J5G@1", "SM2 Fig. 21: a 6J5-G"),
        "pre_r_plate7_ohm": val(350e3, f21("350,000 (the 6J7-G's plate load)")),
        "pre_c_n2_f": val(0.25e-6, f21(".25")),
        "pre_r_screen7_ohm": val(2e6, f21("2 MEG (screen)")),
        "pre_c_screen7_f": val(0.05e-6, f21(".05")),
        "pre_r_n2_ohm": val(25e3, f21("25,000")),
        "pre_c_1uf_f": val(1e-6, f21("1 MFD")),
        "pre_r_nb_ohm": val(10e3, f21("10,000")),
        "pre_r_grid5_ohm": val(1e6, f21("1 MEG (the 6J5-G's grid leak, to the bias divider)")),
        "pre_r_k5_ohm": val(39.0, f21("39 OHMS")),
        "pre_r_k5fb_ohm": val(
            56.0, f21("56 OHMS, from the power amplifier's output terminal (hum bucking, SM2 p.10)")
        ),
        "pre_r_post_ohm": val(
            12.0,
            "SM2 p.10: the unused binding post 'grounded through a 12 ohm resistor' (with an external tone cabinet)",
        ),
        "pre_t_lp_h": val(
            50.0, f"{p}: A0-17553-0's primary (not printed; ~25 Hz with the 6J5-G's 7.7k)"
        ),
        "pre_t_rp_ohm": val(1500.0, f"{p}: its primary's winding resistance"),
        "pre_t_ls_h": val(
            50.0 / 15.4 / 4.0,
            f"{p}: each half of the secondary ('a 500 ohm push-pull output', SM2 p.10: the 6J5-G's ~7.7k to 500 ohm, turns 3.9:1 overall)",
        ),
        "pre_t_rs_ohm": val(25.0, f"{p}: each half secondary's winding resistance"),
        "pre_t_k": val(0.995, f"{p}: the windings' coupling"),
        "pre_r_load_ohm": val(2500.0, f21("2,500 across the secondary")),
        "rn56_ohm": val(50e6, fig(20, "RN56 50 MEG (VOLUME)")),
        "cn41_f": val(50e-12, fig(20, "CN41 .00005 (VOLUME)")),
        "rn55_ohm": val(25e6, fig(20, "RN55 25 MEG (VOLUME)")),
        "cn40_f": val(100e-12, fig(20, "CN40 .0001 (VOLUME)")),
    }


def amp_values() -> dict:
    p = "provisional: model knowledge"

    def f22(what):
        return fig(22, what)

    # the console (SM2 p.1: 52 1/4 x 36 3/4 x 38 1/4 in closed)
    return {
        "tube_pa56": val("56@1", "SM2 p.10, Fig. 22: 'two type 56 input tubes'"),
        "tube_pa2a3": val("2A3@1", "SM2 p.10, Fig. 22: 'four 2A3 tubes in push-pull parallel'"),
        "pa_r_k56_ohm": val(2000.0, f22("2,000 (the 56s' cathodes)")),
        "pa_r_plate56_ohm": val(75e3, f22("75,000 (the 56s' plate loads)")),
        "pa_c_couple_f": val(0.3e-6, f22(".3")),
        "pa_r_grid_ohm": val(75e3, f22("75,000 (the 2A3s' grid returns)")),
        "pa_c_bias_f": val(0.25e-6, f22(".25 (the bias line)")),
        "pa_r_bias_ohm": val(50e3, f22("50,000 (the bias line, off the supply's return)")),
        "pa_b_plus_v": val(
            300.0,
            f"{p}: the 2A3s' plate supply (Fig. 22: a 5U4-G on 1050 V CT, two chokes, 6 MFDs, not traced: RCA's 300 V push-pull column)",
        ),
        "pa_b_plus_driver_v": val(
            300.0, f"{p}: the 56s' supply (Fig. 22's 4 MFD node, after the chokes)"
        ),
        "pa_bias_v": val(
            -62.0,
            f"{p}: the 2A3s' grid bias (Fig. 22: the supply's negative return through the speaker field, not traced: RCA's fixed-bias column, -62 V at 300 V)",
        ),
        "pa_ot_model": val(
            "NOVACHORD_OT@1",
            f"{p}: the output transformer (not printed): a 3,000 ohm plate-to-plate primary (RCA's fixed-bias column) to the two voice coils in parallel",
        ),
        "speaker_model": val(
            "P12R@1",
            f"{p}: the two 12-inch field-coil dynamic speakers (SM2 p.5; Fig. 22: fields 250 and 5,000 ohm) stand in as the P12R (its sheet's fit)",
        ),
        "listen_distance_m": val(1.0, "the 5E3's choice (the user's, 2026-10-29): 1 m on axis"),
        "cab_width_m": val(1.327, "SM2 p.1: the console 52 1/4 in wide"),
        "cab_height_m": val(0.972, "SM2 p.1: 38 1/4 in high (closed)"),
        "cab_depth_m": val(0.933, "SM2 p.1: 36 3/4 in deep"),
        "cab_offset_x_m": val(
            -0.33,
            f"{p}: the speakers left and right of the console's centre (Fig. 25's installation drawing)",
        ),
        "cab_offset_x2_m": val(0.33, f"{p}: the second speaker"),
    }


def group_values(groups) -> dict:
    out = {}
    for g in groups:
        f_mid = key_hz(4 * g + 2.5)
        out[f"cn18_g{g}_f"] = val(
            by_period(0.00015e-6, 0.005e-6, f_mid, key_hz(2.5), key_hz(70.5)),
            fig(
                20,
                f"CN18 .00015 TO .005 (by the period at keys {4 * g + 1}-{4 * g + 4}'s middle over the 18 groups)",
            ),
        )
    return out


def build_full(trims: dict | None = None) -> str:
    """The whole instrument (NV3): twelve chains, 72 keys, the control box and preamplifier."""
    values = (
        shared_values()
        | vib_values()
        | reed_values()
        | preamp_values()
        | amp_values()
        | group_values(range(18))
    )
    secs: list = []
    devs: dict = {"VP7": {"device": "tube_pre7"}, "VP5": {"device": "tube_pre5"}}
    devs |= {"VPA56A": {"device": "tube_pa56"}, "VPA56B": {"device": "tube_pa56"}}
    devs |= {f"VPA3{c}": {"device": "tube_pa2a3"} for c in "ABCD"}
    for r in range(6):
        devs |= {f"CREED{r}": {"device": "reed_make"}, f"CDRV{r}": {"device": "reed_drive"}}
    cv: dict = {}
    for note in range(12):
        keys = [1 + c * 12 + note for c in range(6)]
        v2, s2, d2, c2 = note_chain(note, keys, trims, key_mode="switches")
        values |= v2
        secs += s2
        devs |= d2
        cv |= c2
    keys_ctl = {k: cv[k] for k in sorted(cv, key=lambda k: (int(k[1:]), k[0]))}
    controls = (
        keys_ctl
        | CONTROLS
        | {
            "volume": {
                "value": 4,
                "choices": [1, 2, 3, 4],
                "unit": "position",
                "source": "SM2 p.3: VOLUME, four positions, 4 the loudest",
            },
            "amp": {
                "value": 1,
                "choices": [0, 1],
                "unit": "switch",
                "source": "SM2 p.10: the power amplifier and speakers (1), or the preamplifier's 500 ohm line alone (0: 'played through a separate tone cabinet', the feedback lead on its 12 ohm post); 0 renders faster",
            },
        }
    )
    spec = {
        "title": "Hammond Novachord (the generator, control box and preamplifier)",
        "input": "in",
        "probes": ["out", "pre_out", "cbox", "tone", "bct"],
        "full_scale": {
            "input_volts_peak": val(
                1.0, "provisional: model knowledge (the audio input is unused: the keys play it)"
            ),
            "output_volts_peak": val(
                1.0,
                "provisional: model knowledge (AMP on: the sound pressure 1 m in front of the console, pascals as volts, varimu.devices.speaker; AMP off: the preamplifier's line, volts; set from renders)",
            ),
        },
        "controls": controls,
        "values": values,
        "devices": devs,
        "sections": shared_sections(list(range(18)), full=True) + secs,
    }
    header = (
        "# GENERATED by scripts/make_novachord.py (docs/NOVACHORD_PLAN.md, NV3): never edit this\n"
        "# file. The Novachord from its service manual; that script's docstring describes the\n"
        "# circuit and data/schematics/hammond_novachord/README.md the sources.\n\n"
    )
    return header + yaml.safe_dump(spec, sort_keys=False, width=110, allow_unicode=True)


def vib_values() -> dict:
    return {
        "rn20_ohm": val(15e3, fig(15, "RN20 15,000")),
        "rn32_ohm": val(75e3, fig(15, "RN32 75,000 (one for all oscillators)")),
        "rn35_ohm": val(250e3, fig(15, "RN35 250,000 (one for all oscillators)")),
        "rn36_ohm": val(10e3, fig(15, "RN36 10,000 (one for all oscillators)")),
        "rn39_ohm": val(250e3, fig(15, "RN39 250,000 (one per reed)")),
        "rn40_ohm": val(50e3, fig(15, "RN40 50,000 (one per reed)")),
        "cn16_f": val(0.025e-6, fig(15, "CN16 .025 (one per reed)")),
        "rn31_ohm": val(250e3, fig(15, "RN31 250,000 (one for all oscillators)")),
        "rn15_ohm": val(
            18e3, fig(15, "RN15 18,000 (one for all oscillators; read 18,000, possibly 10,000)")
        ),
        "rn21_ohm": val(75e3, fig(15, "RN21 75,000 (one for all oscillators)")),
        "r_pre_in_ohm": val(
            1.0e6,
            "provisional: model knowledge (the preamplifier's input until NV3: a 6J7-G grid's leak behind its 50,000 ohm stopper, SM2 p.10; Fig. 21's input network isn't read yet)",
        ),
    }


def build_note(note: int = 4, trims: dict | None = None) -> str:
    keys = [1 + c * 12 + note for c in range(6)]
    values = shared_values() | vib_values() | reed_values()
    v2, secs, devs, cv = note_chain(note, keys, trims)
    r = note // 2
    devs |= {f"CREED{r}": {"device": "reed_make"}, f"CDRV{r}": {"device": "reed_drive"}}
    values |= v2
    groups = sorted({(k - 1) // 4 for k in keys})
    for g in groups:
        f_mid = key_hz(4 * g + 2.5)
        values[f"cn18_g{g}_f"] = val(
            by_period(0.00015e-6, 0.005e-6, f_mid, key_hz(2.5), key_hz(70.5)),
            fig(
                20,
                f"CN18 .00015 TO .005 (by the period at keys {4 * g + 1}-{4 * g + 4}'s middle over the 18 groups)",
            ),
        )
    spec = {
        "title": f"Hammond Novachord, the note {NAMES[note]} (oscillator, five dividers, six keys)",
        "input": "in",
        "cv_inputs": cv,
        "probes": ["out", "tone", "bus"],
        "full_scale": {
            "input_volts_peak": val(
                1.0, "provisional: model knowledge (the audio input is unused: the keys play it)"
            ),
            "output_volts_peak": val(
                1.0,
                "provisional: model knowledge (to be set from renders: the control box's output into the preamplifier)",
            ),
        },
        "controls": CONTROLS,
        "values": values,
        "devices": devs,
        "sections": shared_sections(groups, reeds=(note // 2,)) + secs,
    }
    # the sustain inputs are driven nodes; their load resistors (SUSA, SUSB) are numerical
    header = (
        "# GENERATED by scripts/make_novachord.py (docs/NOVACHORD_PLAN.md, NV1): never edit this\n"
        "# file. The note A's chain from the Novachord's service manual; that script's docstring\n"
        "# describes the circuit and data/schematics/hammond_novachord/README.md the sources.\n\n"
    )
    return header + yaml.safe_dump(spec, sort_keys=False, width=110, allow_unicode=True)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--check", action="store_true", help="exit 1 when a generated file is stale")
    args = ap.parse_args()
    trims = load_trims()
    outs = {
        CIRC / "novachord_note.yaml": build_note(4, trims),
        CIRC / "novachord.yaml": build_full(trims),
    }
    stale = [
        p for p, text in outs.items() if not p.exists() or p.read_text(encoding="utf-8") != text
    ]
    if args.check:
        for p in stale:
            print(f"stale: {p}")
        return 1 if stale else 0
    for p, text in outs.items():
        p.write_text(text, encoding="utf-8")
        print(f"wrote {p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
