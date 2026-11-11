# ruff: noqa: E501  (the values' sources are long strings, kept one per line)
"""Generate the Victorian synth's 1881 voice, config/circuits/victorian_voice.yaml
(docs/VICTORIAN_SYNTH_PLAN.md, V3): one netlist of

- the reeds (the `reed_keys` medium, GRAY_REEDS: per key a self-interrupting reed in a local
  circuit, its second contact chopping the line through the carbon under the key);
- four batteries of Leclanche cells (config/victorian/leclanche.yaml, Carhart's 1891 cell: an
  EMF behind its resistance and two polarization states): the local battery (2 cells) that
  keeps the reeds going, the line battery (4) that the keys chop, the relay's battery (3) and
  the CUTOFF battery (2);
- the induction coil (Blake's proportions: a 0.5 ohm primary in the line, a 250 ohm secondary,
  on an open core of soft iron wire) and the line's condenser;
- the filter: a two-core saturable reactor on Ewing's soft iron (the tube synth's S1 reactor,
  re-wound for the line), its series windings into a paper condenser; CUTOFF a rheostat feeding
  the control windings from their battery;
- the carbon relay: a 200 ohm receiver (Ader's) whose diaphragm presses a carbon button in the
  relay battery's circuit (CARBON_BUTTON), with a 40 ohm Bell receiver in that circuit;
- `out`: the Bell receiver's sound pressure 0.3 m in front of it.

    uv run python scripts/make_victorian_voice.py [--check]

--check exits 1 when the file on disk differs from what this writes.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "config" / "circuits" / "victorian_voice.yaml"
CELL = REPO / "config" / "victorian" / "leclanche.yaml"

CARHART = "config/victorian/leclanche.yaml (Carhart 1891's cell, scripts/fit_leclanche.py)"
BLAKE = (
    "web: https://archive.org/details/americantelephone00mill (Miller, American Telephone "
    "Practice, 1905: the Blake transmitter's induction coil, a 0.5 ohm primary and a 250 ohm "
    "secondary, p. 79; its core ~500 strands of No. 24 B&S Swedish iron wire, 4 in long and 9/16 "
    "in across, p. 74)"
)


def v(value, source: str, **extra) -> dict:
    return {"value": value, "source": source, **extra}


def cells(prefix: str, n: int, top: str, parts: dict) -> None:
    """A battery of n identical Leclanche cells in series from ground to `top`: exactly one
    cell with n times the EMF and the resistances and 1/n the capacitances (an EMF behind r0
    and two R || C polarization states). One cell's states, not n: the live circuit's cost
    grows with its states (per-cell tolerance would split it again)."""
    e, a, b = f"{prefix}e", f"{prefix}a", f"{prefix}b"
    u = prefix.upper()
    parts[f"V{u}"] = {"V": [e, "0"], "v": f"{prefix}_e0_v"}
    parts[f"R{u}0"] = {"R": [e, a], "r": f"{prefix}_r0_ohm"}
    parts[f"R{u}1"] = {"R": [a, b], "r": f"{prefix}_r1_ohm"}
    parts[f"C{u}1"] = {"C": [a, b], "c": f"{prefix}_c1_f"}
    parts[f"R{u}2"] = {"R": [b, top], "r": f"{prefix}_r2_ohm"}
    parts[f"C{u}2"] = {"C": [b, top], "c": f"{prefix}_c2_f"}


def battery_values(prefix: str, n: int, what: str, cv: dict) -> dict:
    src = f"derived: {n} cells in series ({what}), each {CARHART}"
    return {
        f"{prefix}_e0_v": v(n * cv["e0_v"], src),
        f"{prefix}_r0_ohm": v(n * cv["r0_ohm"], src),
        f"{prefix}_r1_ohm": v(n * cv["r1_ohm"], src),
        f"{prefix}_c1_f": v(cv["tau1_s"] / cv["r1_ohm"] / n, f"{src}; C = tau / r"),
        f"{prefix}_r2_ohm": v(n * cv["r2_ohm"], src),
        f"{prefix}_c2_f": v(cv["tau2_s"] / cv["r2_ohm"] / n, f"{src}; C = tau / r"),
    }


BATTERIES = (
    (
        "bl",
        4,
        "bline",
        "line battery",
        "design: the line battery, four Leclanche cells (the keys chop it)",
    ),
    (
        "bk",
        2,
        "loc",
        "local battery",
        "design: the local battery, two cells, as Gray's local circuits (US 165,728)",
    ),
    ("br", 3, "brel", "relay battery", "design: the relay's battery, three cells"),
    (
        "bc",
        6,
        "bctl",
        "cutoff battery",
        "design: the CUTOFF battery, six cells (the bias's ampere-turns)",
    ),
)


def build() -> dict:
    cell = yaml.safe_load(CELL.read_text(encoding="utf-8"))["cell"]
    cv = {k: x["value"] for k, x in cell.items()}
    values = {}
    for prefix, n, _, _title, src in BATTERIES:
        values.update(battery_values(prefix, n, src, cv))
    values.update(
        {
            # The reeds.
            "reeds_model": v(
                "GRAY_REEDS@2", "the compiled keyboard (scripts/compile_victorian_reeds.py)"
            ),
            "reeds_step_hz": v(
                768000.0,
                "design: the keys' internal rate, 8 x 96 kHz (config/victorian/reeds.yaml numerics.oversample)",
            ),
            "reeds_v_per_a": v(1.0, "design: the medium's outputs, 1 V per A"),
            "g_sense_s": v(
                1.0, "design: the G parts drawing the medium's currents, its outputs' inverse scale"
            ),
            "c_line_f": v(
                10.0e-6,
                "design: the line's condenser, a box of paraffined paper-and-foil condensers across the line at the keys (holds the line while the keys chop it; with the induction coil's primary a ~1-2 kHz resonance)",
            ),
            # The induction coil.
            "ic_primary_turns": v(
                150.0, f"design: Blake's proportions ({BLAKE}): 150 primary turns of heavy wire"
            ),
            "ic_ratio": v(
                15.0, f"design: 1:15 for Blake's 0.5 / 250 ohm windings ({BLAKE}) in one window"
            ),
            "ic_r_primary_ohm": v(0.5, BLAKE),
            "ic_r_secondary_ohm": v(250.0, BLAKE),
            "ic_l_primary_h": v(
                0.00032206975045794646,
                f"derived: mu0 N^2 A / (gap + l / mu_i): 150 turns on Miller's 9/16 in bundle at 3/4 iron (1.2 cm^2, {BLAKE}), its 4 in of soft iron (Ewing's initial permeability 190, config/magnetics.yaml soft_iron_ewing) and the open core's air return as a 10 mm gap (provisional: model knowledge)",
            ),
            "ic_l_secondary_h": v(
                0.07246569385303796, "derived: the primary's times the turns ratio squared (15^2)"
            ),
            "ic_k": v(
                0.968,
                "derived: sqrt(1 - L_leak / L_p) with a ~20 uH leakage, ~6% of the primary's (provisional: model knowledge, the windings on one bundle)",
            ),
            # The filter.
            "rf_turns": v(
                525.0,
                "design: ~66 mH per core at the iron's reversible permeability unbiased (~185: JA's c dMan/dH, soft_iron_ewing): with 2.1 uF and the ~250 ohm load aimed at a ~300 Hz low-pass, rising toward ~4 kHz biased. Measured (scripts/victorian_voice_study.py, cutoff): CUTOFF lifts the filter's output above ~2 kHz by 20-30 dB and the output's level by ~7 dB, the band below ~2 kHz barely moves, and the receivers' band (~0.3-1.5 kHz) hides most of it at the output: an open item (VICTORIAN_SYNTH_PLAN.md, V3 status)",
            ),
            "rf_r_signal_ohm": v(
                5.0, "provisional: model knowledge (525 turns of 0.4 mm wire on a 10 cm ring)"
            ),
            "rf_control_ratio": v(
                3.0,
                "design: the control windings, three times the signal's turns (1575): a few kA/m of bias from the CUTOFF battery takes the iron past its knee",
            ),
            "rf_r_control_ohm": v(
                12.0,
                "provisional: model knowledge (1575 turns of 0.6 mm wire, a thick outer winding)",
            ),
            "rf_area_m2": v(1.0e-4, "design: a ring of soft iron wire, 1 cm^2"),
            "rf_path_m": v(0.1, "design: 10 cm round"),
            "rf_gap_m": v(0.0, "design: a wound ring, no joint"),
            "rf_leakage_h": v(
                0.0, "provisional: model knowledge (windings on a ring couple closely)"
            ),
            "rf_c_f": v(2.1e-6, "design: a paper condenser for the ~300 Hz low-pass"),
            "cutoff_r_max_ohm": v(
                500.0,
                "design: the CUTOFF rheostat, 500 ohm of German silver wire (Wheatstone's rheostat, 1843), wound evenly in the log of its resistance",
            ),
            "cutoff_taper_mid": v(
                0.1,
                "design: the rheostat's resistance at half its turn, a tenth of its whole (graded: CUTOFF moves evenly in octaves)",
            ),
            "cutoff_r_min_ohm": v(
                2.0,
                "design: a fixed resistance in the control circuit (the rheostat's leads and stop)",
            ),
            # The relay.
            "relay_rx": v(
                "ADER_RX@1",
                "the relay's receiver: a 200 ohm magneto receiver (Preece & Maier 1889, the Ader system)",
            ),
            "button": v("CARBON_BUTTON@1", "the relay's carbon button (varimu.devices.carbon)"),
            "button_k_n_m": v(
                1.0e4,
                "provisional: model knowledge (the button's stiffness against the diaphragm, the grains' bed and its cup's spring)",
            ),
            "button_preload_n": v(
                0.3, "design: the button's working pressure, set by its adjusting screw"
            ),
            "relay_l_button_h": v(
                12.97**2 / 1.0e4,
                "derived: the button's stiffness on the diaphragm in the receiver's mechanical network, BL^2 / k (ADER_RX's BL 12.97 N/A)",
            ),
            "relay_r_button_ohm": v(
                0.01,
                "numerics: a DC path in series with the button's stiffness (it parallels the diaphragm's compliance, two inductors in a loop); its corner R / 2 pi L ~0.1 Hz",
            ),
            "relay_gm_s": v(
                1.0e4 / 12.97,
                "derived: k / BL: the diaphragm's velocity voltage (BL v) integrated on 1 F is the button's force in newtons (1 V = 1 N)",
            ),
            "relay_c_f": v(1.0, "design: the force integrator's 1 F (numerics: volts as newtons)"),
            "relay_r_ohm": v(
                1.0,
                "design: its leak, 1 s (numerics: the force's AC part; its rest is the preload)",
            ),
            # The loud-speaking end.
            "out_rx": v("BELL_RX@1", "Bell's 40 ohm hand telephone (Preece & Maier 1889, p. 27)"),
            "listen_distance_m": v(0.3, "design: the listener 0.3 m in front of the receiver"),
            "rx_baffle_m": v(
                0.07,
                "provisional: model knowledge (the receiver's case and mouthpiece as a 7 cm flat baffle)",
            ),
            "rx_depth_m": v(0.0, "design: a flat baffle (the receiver's closed case)"),
            "r_in_ohm": v(1.0e3, "design: a load on the unused input"),
        }
    )
    controls = {
        "cutoff": v(
            0.3,
            "design: the CUTOFF rheostat's rotation (0: all 500 ohm in, the cores barely biased, a dark ~300 Hz; 1: out, the control windings on their battery through 2 ohm, the iron past its knee)",
            min=0.0,
            max=1.0,
            unit="rotation",
        ),
    }
    sections = []
    for prefix, n, top, title, _ in BATTERIES:
        p: dict = {}
        cells(prefix, n, top, p)
        sections.append({"title": title, "parts": p})
    sections.append(
        {
            "title": "keys",
            "parts": {
                "RIN": {"R": ["in", "0"], "r": "r_in_ohm"},
                "REEDS": {
                    "reed_keys": ["loc", "line", "ol", "ok"],
                    "component": "reeds_model",
                    "step_hz": "reeds_step_hz",
                    "v_per_a": "reeds_v_per_a",
                },
                "GLOC": {"G": ["loc", "0", "ol", "0"], "gm": "g_sense_s"},
                "GLINE": {"G": ["line", "0", "ok", "0"], "gm": "g_sense_s"},
                "CLINE": {"C": ["line", "0"], "c": "c_line_f"},
                # The induction coil: its open core's flux returns through the air (a 10 mm
                # equivalent gap against the iron's ~0.5 mm), so the iron's hysteresis is
                # diluted ~20x: coupled inductors (the circuit's iron is the reactor's).
                "RICP": {"R": ["bline", "icp"], "r": "ic_r_primary_ohm"},
                "LICP": {"L": ["icp", "line"], "l": "ic_l_primary_h"},
                "LICS": {"L": ["s1", "ics"], "l": "ic_l_secondary_h"},
                "RICS": {"R": ["ics", "0"], "r": "ic_r_secondary_ohm"},
                "KIC": {"K": ["LICP", "LICS"], "k": "ic_k"},
            },
        }
    )
    sections.append(
        {
            "title": "filter",
            "parts": {
                "TRA": {
                    "transformer": {
                        "sig": {"nodes": ["s1", "fm"], "r": "rf_r_signal_ohm"},
                        "ctl": {
                            "nodes": ["c1", "c2"],
                            "ratio": "rf_control_ratio",
                            "r": "rf_r_control_ohm",
                        },
                    },
                    "core": {
                        "material": "soft_iron_ewing",
                        "area_m2": "rf_area_m2",
                        "path_m": "rf_path_m",
                        "gap_m": "rf_gap_m",
                    },
                    "turns": "rf_turns",
                    "leakage_h": "rf_leakage_h",
                },
                "TRB": {
                    "transformer": {
                        "sig": {"nodes": ["fm", "f1"], "r": "rf_r_signal_ohm"},
                        "ctl": {
                            "nodes": ["0", "c2"],
                            "ratio": "rf_control_ratio",
                            "r": "rf_r_control_ohm",
                        },
                    },
                    "core": {
                        "material": "soft_iron_ewing",
                        "area_m2": "rf_area_m2",
                        "path_m": "rf_path_m",
                        "gap_m": "rf_gap_m",
                    },
                    "turns": "rf_turns",
                    "leakage_h": "rf_leakage_h",
                },
                "RCMIN": {"R": ["bctl", "cr"], "r": "cutoff_r_min_ohm"},
                "RCUT": {
                    "rheostat": ["cr", "c1"],
                    "r": "cutoff_r_max_ohm",
                    "at": "cutoff",
                    "taper_mid": "cutoff_taper_mid",
                    "reverse": 1,
                },
            },
        }
    )
    sections.append(
        {
            "title": "relay",
            "parts": {
                # The filter's condenser, drawn here: the live partition's cut at f1, held by
                # it in this part (the reactor's winding sees f1 a sample late).
                "CF": {"C": ["f1", "0"], "c": "rf_c_f"},
                "RLY": {
                    "speaker": ["f1", "0", "rly_out"],
                    "component": "relay_rx",
                    "distance_m": "listen_distance_m",
                    "width_m": "rx_baffle_m",
                    "height_m": "rx_baffle_m",
                    "depth_m": "rx_depth_m",
                    "readout": 0,
                },
                "LBUT": {"L": ["rly_m", "rly_bk"], "l": "relay_l_button_h"},
                "RBUT": {"R": ["rly_bk", "0"], "r": "relay_r_button_ohm"},
                "GFX": {"G": ["0", "fx", "rly_m", "0"], "gm": "relay_gm_s"},
                "CFX": {"C": ["fx", "0"], "c": "relay_c_f"},
                "RFX": {"R": ["fx", "0"], "r": "relay_r_ohm"},
                "VPRE": {"V": ["0", "fref"], "v": "button_preload_n"},
                "XBUT": {"device": ["brel", "o1", "fx", "fref"], "model": "XBUT"},
                "OUT": {
                    "speaker": ["o1", "0", "out"],
                    "component": "out_rx",
                    "distance_m": "listen_distance_m",
                    "width_m": "rx_baffle_m",
                    "height_m": "rx_baffle_m",
                    "depth_m": "rx_depth_m",
                },
            },
        }
    )
    return {
        "title": "Victorian synth voice (1881)",
        "input": "in",
        "probes": ["out", "line", "loc", "bline", "s1", "f1", "fx", "o1", "ol", "ok"],
        "full_scale": {
            "input_volts_peak": v(1.0, "design: the voice has no audio input (a load on `in`)"),
            "output_pascals_peak": v(
                0.003,
                "derived: a 4-key chord at velocity 90 with a run over it peaks at ~0.0014-0.002 Pa 0.3 m in front of the receiver (scripts/victorian_voice_study.py demo, 2026-11-11), with ~4-6 dB of headroom",
            ),
        },
        "controls": controls,
        "values": values,
        "devices": {"XBUT": {"device": "button"}},
        "sections": sections,
    }


HEADER = """\
# GENERATED by scripts/make_victorian_voice.py: don't edit by hand.
#
# The Victorian synth's 1881 voice (docs/VICTORIAN_SYNTH_PLAN.md, V3): Gray's reeds (the
# reed_keys medium) chopping a line of Leclanche cells through the carbon under each key; the
# line's induction coil; a saturable reactor on Ewing's soft iron with CUTOFF on its control
# battery; a carbon relay (a 200 ohm receiver pressing a carbon button) driving Bell's 40 ohm
# receiver; `out` its sound pressure 0.3 m in front (pascals as volts). Every part existed by
# 1881; the wiring is ours. "design:" values are the instrument builder's choices.

"""


def text() -> str:
    return HEADER + yaml.safe_dump(build(), sort_keys=False, width=100, allow_unicode=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    t = text()
    if a.check:
        same = OUT.exists() and OUT.read_text(encoding="utf-8") == t
        print("up to date" if same else "stale: rerun without --check")
        return 0 if same else 1
    OUT.write_text(t, encoding="utf-8", newline="\n")
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
