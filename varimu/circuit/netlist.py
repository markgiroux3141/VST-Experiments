"""Fairchild 670 (one channel) -> one coupled SPICE netlist.

Audio path, sidechain and power supply are a single circuit. The control
voltage reaches the 6386 grids through the input transformer's centre tap,
the sidechain is fed from the output transformer (feedback topology), and
every stage hangs off the same B+ node.

Component values and their sources are in config/circuits/fairchild_670.yaml.
`build()` takes overrides for any control or value, by the same key names.

Simplifications in this first slice (each is a later fidelity step):
- transformers are linear coupled inductors with winding resistance (Phase 2);
- B+ is an ideal 240 V source behind a source impedance, standing in for the
  regulated supply (EL34 / 6084 / 5651);
- each 4-triode 6386 bank is one device instance with 4x the current, so
  mismatch is between the two banks, not within one;
- passives are at their nominal values (no per-part tolerance yet).
"""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from varimu.config import CONFIG_DIR, ConfigError, load_genome_bounds, load_sim_settings
from varimu.devices.library import load_device
from varimu.devices.pentode import Pentode
from varimu.devices.table import GRIDS, cached_table, table_subckt
from varimu.devices.triode import GridCurrent, KorenTriode, Triode, VariMuTriode, num

CIRCUIT_FILE = CONFIG_DIR / "circuits" / "fairchild_670.yaml"
INPUT_NODE = "in"

# Vectors every render saves (see varimu.sim.io.run_transient).
SAVE = ("v(out)", "v(cv)", "v(tcb)", "v(bp)", "v(ga)", "v(gb)", "v(ka)", "v(kb)")

# Genome parameters that act on device instances rather than on a netlist value.
TUBE_PARAMS = {
    "v6386_a.emission_scale": 1.0,
    "v6386_a.mu_spread": 1.0,
    "v6386_a.grid_contact_v": None,  # None -> the device file's value
    "v6386_b.emission_scale": 1.0,
    "v6386_b.mu_spread": 1.0,
    "v6386_b.grid_contact_v": None,
}

_MIN_R = 1e-3  # ohm; stands in for the zero end of a pot
_STRING_VALUES = {"bridge_diode"}


# --- Parameters --------------------------------------------------------------------


@dataclass(frozen=True)
class CircuitSpec:
    controls: dict[str, dict[str, Any]]
    values: dict[str, dict[str, Any]]

    def defaults(self) -> dict[str, Any]:
        d = {k: e["value"] for k, e in self.controls.items()}
        d.update({k: e["value"] for k, e in self.values.items()})
        d.update({k: v for k, v in TUBE_PARAMS.items() if v is not None})
        return d


def load_spec(path: Path = CIRCUIT_FILE) -> CircuitSpec:
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    errors = []
    for section in ("controls", "values"):
        for k, e in data[section].items():
            if not isinstance(e, Mapping) or "value" not in e:
                errors.append(f"{section}.{k}: needs a `value`")
            elif not str(e.get("source", "")).strip():
                errors.append(f"{section}.{k}: needs a `source`")
            elif isinstance(e["value"], str) and k not in _STRING_VALUES:
                # PyYAML reads 1.0e6 as a string; write 1.0e+6.
                errors.append(f"{section}.{k}: value {e['value']!r} is not a number")
    if errors:
        raise ConfigError(f"{path}:\n  " + "\n  ".join(errors))
    return CircuitSpec(data["controls"], data["values"])


def resolve(overrides: Mapping[str, Any] | None = None, spec: CircuitSpec | None = None):
    """Defaults merged with overrides. Unknown keys and out-of-range controls are errors."""
    spec = spec or load_spec()
    p = spec.defaults()
    known = set(p) | set(TUBE_PARAMS)
    for k, v in (overrides or {}).items():
        if k not in known:
            raise KeyError(f"unknown circuit parameter {k!r}")
        p[k] = v
    for k, e in spec.controls.items():
        if not e["min"] <= p[k] <= e["max"]:
            raise ValueError(f"control {k}={p[k]} outside [{e['min']}, {e['max']}]")
    p["time_constant"] = int(p["time_constant"])
    return p


def genome_links(spec: CircuitSpec | None = None) -> dict[str, str]:
    """Circuit value key -> genome_bounds.yaml path, for the uncertain values."""
    spec = spec or load_spec()
    return {k: e["genome"] for k, e in spec.values.items() if "genome" in e}


def check_genome_links(spec: CircuitSpec | None = None) -> list[str]:
    """Problems with the circuit <-> genome_bounds links (empty list = fine)."""
    spec = spec or load_spec()
    bounds = load_genome_bounds()
    problems = []
    for key, path in genome_links(spec).items():
        b = bounds.get(path)
        v = spec.values[key]["value"]
        if b is None:
            problems.append(f"{key}: genome path {path} not in genome_bounds.yaml")
        elif not b.resolved:
            problems.append(f"{key}: genome bounds {path} still TBD")
        elif not b.min <= v <= b.max:
            problems.append(f"{key}: nominal {v} outside [{b.min}, {b.max}] ({path})")
    return problems


# --- Device instances --------------------------------------------------------------------


def tube_instance(
    base: Triode,
    name: str,
    *,
    n_parallel: int = 1,
    emission_scale: float = 1.0,
    mu_spread: float = 1.0,
    grid_contact_v: float | None = None,
) -> Triode:
    """A triode instance: n identical sections in parallel, with this instance's spreads.

    Emission scales plate current (Kg1 / scale), mu_spread scales every
    section's mu, and the grid current, capacitances and current scale with n.
    """
    k = n_parallel * emission_scale
    pl = base.plate
    if isinstance(pl, VariMuTriode):
        plate = dataclasses.replace(pl, mus=tuple(m * mu_spread for m in pl.mus), kg1=pl.kg1 / k)
    elif isinstance(pl, KorenTriode):
        plate = dataclasses.replace(pl, mu=pl.mu * mu_spread, kg1=pl.kg1 / k)
    else:
        raise TypeError(type(pl))
    grid = base.grid
    if grid is not None:
        grid = GridCurrent(
            grid.perveance * n_parallel,
            grid.contact_v if grid_contact_v is None else grid_contact_v,
            grid.smooth_v,
        )
    return Triode(
        name,
        plate,
        grid,
        c_gk=base.c_gk * n_parallel,
        c_gp=base.c_gp * n_parallel,
        c_pk=base.c_pk * n_parallel,
    )


# --- Netlist building blocks ---------------------------------------------------------------


def _r(name: str, a: str, b: str, ohms: float) -> str:
    return f"R{name} {a} {b} {num(max(ohms, _MIN_R))}"


def _pot(name: str, end_a: str, wiper: str, end_b: str, total: float, pos: float) -> list[str]:
    """Potentiometer; pos = 0 puts the wiper at end_a, 1 at end_b."""
    return [
        _r(f"{name}a", end_a, wiper, pos * total),
        _r(f"{name}b", wiper, end_b, (1 - pos) * total),
    ]


def _t_pad(name: str, a: str, b: str, z: float, atten_db: float) -> list[str]:
    """Symmetric T attenuator between a and b (to ground), characteristic impedance z."""
    if atten_db <= 0:
        return [_r(f"{name}s", a, b, 0.0)]
    k = 10 ** (atten_db / 20)
    r1 = z * (k - 1) / (k + 1)
    r2 = 2 * z * k / (k * k - 1)
    return [
        _r(f"{name}1", a, f"{name}_m", r1),
        _r(f"{name}2", f"{name}_m", b, r1),
        _r(f"{name}3", f"{name}_m", "0", r2),
    ]


def _transformer(
    name: str,
    windings: list[tuple[str, str, str, float, float, float, float]],
    l_unit_h: float,
    k: float,
) -> list[str]:
    """Linear transformer as coupled inductors.

    windings: (label, dot_node, other_node, turns, r_ohm, c_f, rloss_ohm).
    Inductance is l_unit_h * turns^2, every pair is coupled with k, and a
    positive voltage from dot to other on one winding gives the same on the
    others. c_f is the winding's self-capacitance and rloss_ohm a lumped
    core/eddy loss, both across its terminals (0 = none).
    """
    lines = []
    for label, dot, other, turns, r, c, rloss in windings:
        mid = f"{name}_{label}_r"
        lines.append(_r(f"{name}_{label}", dot, mid, r))
        lines.append(f"L{name}_{label} {mid} {other} {num(l_unit_h * turns * turns)}")
        if c > 0:
            lines.append(f"C{name}_{label} {dot} {other} {num(c)}")
        if rloss > 0:
            lines.append(_r(f"{name}_{label}_loss", dot, other, rloss))
    labels = [w[0] for w in windings]
    for i, a in enumerate(labels):
        for b in labels[i + 1 :]:
            lines.append(f"K{name}_{a}_{b} L{name}_{a} L{name}_{b} {num(k)}")
    return lines


def _time_constant(position: int, p: Mapping[str, Any], top: str, bot: str) -> list[str]:
    """S102: R137 || C109 always, plus the parts each position switches in."""
    lines = [_r("137", top, bot, p["r137_ohm"]), f"C109 {top} {bot} {num(p['c109_f'])}"]
    if position == 1:
        lines.append(_r("141", top, bot, p["r141_ohm"]))
    if position == 2:
        lines.append(_r("138", top, bot, p["r138_ohm"]))
    if position in (3, 4, 5):
        lines.append(f"C113 {top} {bot} {num(p['c113_f'])}")
    if position == 4:
        lines.append(f"C111 {top} {bot} {num(p['c111_f'])}")
    if position in (5, 6):
        lines += [_r("139", top, "tc139", p["r139_ohm"]), f"C110 tc139 {bot} {num(p['c110_f'])}"]
    if position == 6:
        lines += [_r("140", top, "tc140", p["r140_ohm"]), f"C112 tc140 {bot} {num(p['c112_f'])}"]
    return lines


# --- The circuit -------------------------------------------------------------------------------


@dataclass(frozen=True)
class Circuit:
    text: str
    input_node: str
    save: tuple[str, ...]
    params: dict[str, Any]
    files: dict[str, Path]  # extra files the netlist reads (job-dir name -> source), e.g. tables


def build(
    overrides: Mapping[str, Any] | None = None,
    spec: CircuitSpec | None = None,
    *,
    triode_formulation: str | None = None,
) -> Circuit:
    """The netlist for one channel. `triode_formulation` is "table" or "exact"
    (default from sim_settings.yaml, devices.triode_formulation)."""
    p = resolve(overrides, spec)
    form = triode_formulation or load_sim_settings().data["devices"]["triode_formulation"]
    if form not in ("table", "exact"):
        raise ValueError(f"unknown triode formulation {form!r}")
    base6386 = load_device("6386")
    v12ax7 = load_device("12AX7")
    v12bh7 = load_device("12BH7")
    v6973: Pentode = load_device("6973")
    diode = load_device(p["bridge_diode"])
    n = int(p["v6386_per_side"])
    bank = {
        side: tube_instance(
            base6386,
            f"6386_{side}",
            n_parallel=n,
            emission_scale=p[f"v6386_{side}.emission_scale"],
            mu_spread=p[f"v6386_{side}.mu_spread"],
            grid_contact_v=p.get(f"v6386_{side}.grid_contact_v"),
        )
        for side in ("a", "b")
    }

    files: dict[str, Path] = {}
    L: list[str] = ["* Fairchild 670, one channel: generated by varimu.circuit.netlist"]
    for fname, t, grid in (
        ("v6386_a.tab", bank["a"], GRIDS["6386"]),
        ("v6386_b.tab", bank["b"], GRIDS["6386"]),
        ("v12ax7.tab", v12ax7, GRIDS["12AX7"]),
        ("v12bh7.tab", v12bh7, GRIDS["12BH7"]),
    ):
        if form == "table":
            files[fname] = cached_table(t, grid)
            L.append(table_subckt(t, fname))
        else:
            L.append(t.subckt())
    L += [v6973.subckt(), diode.model_card()]

    # Power supply: one B+ node shared by every stage.
    L += [
        "* --- power supply ---",
        f"VBP bpi 0 dc {num(p['b_plus_v'])}",
        _r("psu", "bpi", "bp", p["psu_source_impedance_ohm"]),
        f"C307A bp 0 {num(p['c307a_f'])}",
        f"VBIAS vbi 0 dc {num(p['bias_v'])}",
        _r("bias", "vbi", "vb", p["bias_source_impedance_ohm"]),
        f"VSCB vsc 0 dc {num(p['v6973_grid_bias_v'])}",
    ]

    # Input: source impedance, AT101, T101 (secondary centre tap = control voltage).
    t1 = p["t101_turns_half"]
    half1 = (t1, p["t101_r_half_ohm"], p["t101_c_half_f"], p["t101_rloss_half_ohm"])
    L += ["* --- input ---", _r("src", INPUT_NODE, "in_s", p["source_impedance_ohm"])]
    L += _t_pad("AT101", "in_s", "pri", p["attenuator_z_ohm"], p["input_atten_db"])
    L += [_r("101", "pri", "0", p["r101_r102_ohm"])]
    L += _transformer(
        "T101",
        [
            ("p", "pri", "0", 1.0, p["t101_r_pri_ohm"], 0.0, 0.0),
            ("sa", "ga", "cv", *half1),
            ("sb", "cv", "gb", *half1),
        ],
        p["t101_lp_h"],
        p["transformer_k"],
    )

    # 6386 banks: plates to T102, cathodes through R103/R104 and the balance pot.
    L += [
        "* --- 6386 push-pull ---",
        f"XVA pa ga ka {bank['a'].subckt_name}",
        f"XVB pb gb kb {bank['b'].subckt_name}",
        _r("103", "ka", "ta", p["r103_r104_ohm"]),
        _r("104", "kb", "tb", p["r103_r104_ohm"]),
        *_pot("105", "ta", "0", "tb", p["r105_ohm"], p["balance"]),
        f"C101 ka kb {num(p['c101_f'])}",
        _r("111", "bp", "ctr", p["r111_ohm"]),
        _r("107", "ctr", "t3", p["r107_r108_ohm"]),
        _r("108", "ctr", "t2", p["r107_r108_ohm"]),
    ]
    t2 = p["t102_turns_half"]
    half2 = (t2, p["t102_r_half_ohm"], p["t102_c_half_f"], p["t102_rloss_half_ohm"])
    L += _transformer(
        "T102",
        [
            ("pa", "pa", "t3", *half2),
            ("pb", "t2", "pb", *half2),
            ("s", "out", "0", 1.0, p["t102_r_sec_ohm"], 0.0, 0.0),
        ],
        p["t102_l_half_h"] / t2**2,
        p["transformer_k"],
    )
    L += [_r("load", "out", "0", p["load_ohm"])]

    # Sidechain pick-off from the output, T103, AC threshold pots.
    t3 = p["t103_turns_half"]
    L += [
        "* --- sidechain input ---",
        _r("145", "out", "s1", p["r145_r148_ohm"]),
        _r("147", "0", "s2", p["r145_r148_ohm"]),
        _r("149", "s1", "s2", p["r149_r150_ohm"]),
    ]
    L += _transformer(
        "T103",
        [
            ("p", "s1", "s2", 1.0, 0.0, 0.0, 0.0),
            ("sa", "t5", "0", t3, 0.0, p["t103_c_half_f"], 0.0),
            ("sb", "0", "t8", t3, 0.0, p["t103_c_half_f"], 0.0),
        ],
        p["t103_lp_h"],
        p["transformer_k"],
    )
    th = p["ac_threshold"]
    L += _pot("115A", "t5", "w1a", "x1a", p["r115a_ohm"], 1 - th)
    L += _pot("115B", "t8", "w1b", "x1b", p["r115b_ohm"], 1 - th)
    L += [_r("113", "x1a", "0", p["r113_r114_ohm"]), _r("114", "x1b", "0", p["r113_r114_ohm"])]

    # 12AX7, biased beyond cutoff by the DC threshold network.
    L += [
        "* --- 12AX7 ---",
        f"XV105A p1a w1a k1 {v12ax7.subckt_name}",
        f"XV105B p1b w1b k1 {v12ax7.subckt_name}",
        _r("120", "bp", "p1a", p["r120_r121_ohm"]),
        _r("121", "bp", "p1b", p["r120_r121_ohm"]),
        _r("118", "bp", "k1", p["r118_ohm"]),
        _r("119", "k1", "0", p["r119_ohm"]),
        _r("116", "bp", "dw", p["r116_ohm"]),
        *_pot("117", "0", "dw", "k1", p["r117_ohm"], p["dc_threshold"]),
        f"C103 p1a g2a {num(p['c103_c104_f'])}",
        f"C104 p1b g2b {num(p['c103_c104_f'])}",
    ]

    # 12BH7 with feedback from T104's tertiary winding into its cathodes.
    L += [
        "* --- 12BH7 ---",
        _r("122", "g2a", "0", p["r122_r123_ohm"]),
        _r("123", "g2b", "0", p["r122_r123_ohm"]),
        f"XV106A p2a g2a k2a {v12bh7.subckt_name}",
        f"XV106B p2b g2b k2b {v12bh7.subckt_name}",
        _r("124", "k2a", "0", p["r124_r125_ohm"]),
        _r("125", "k2b", "0", p["r124_r125_ohm"]),
        _r("126", "bp", "p2a", p["r126_r127_ohm"]),
        _r("127", "bp", "p2b", p["r126_r127_ohm"]),
        _r("fba", "fy", "k2a", p["r_fb_ohm"]),
        _r("fbb", "fg", "k2b", p["r_fb_ohm"]),
        _r("134", "fy", "0", p["r134_ohm"]),
        _r("135", "fg", "0", p["r135_ohm"]),
        f"C107 p2a g3a {num(p['c107_c108_f'])}",
        f"C108 p2b g3b {num(p['c107_c108_f'])}",
    ]

    # 6973 push-pull into T104.
    L += [
        "* --- 6973 ---",
        _r("130", "g3a", "vsc", p["r130_r131_ohm"]),
        _r("131", "g3b", "vsc", p["r130_r131_ohm"]),
        f"XV107 pa3 sa3 g3a 0 {v6973.subckt_name}",
        f"XV108 pb3 sb3 g3b 0 {v6973.subckt_name}",
        _r("132", "bp", "sa3", p["r132_r133_ohm"]),
        _r("133", "bp", "sb3", p["r132_r133_ohm"]),
        _r("143", "g3a", "nfa", p["r143_r144_ohm"]),
        f"C105 nfa pa3 {num(p['c105_c106_f'])}",
        _r("144", "g3b", "nfb", p["r143_r144_ohm"]),
        f"C106 nfb pb3 {num(p['c105_c106_f'])}",
    ]
    L += _transformer(
        "T104",
        [
            ("pa", "pa3", "bp", 1.0, 0.0, p["t104_c_half_f"], p["t104_rloss_half_ohm"]),
            ("pb", "bp", "pb3", 1.0, 0.0, p["t104_c_half_f"], p["t104_rloss_half_ohm"]),
            ("s", "ay", "bk", p["t104_sec_per_half"], 0.0, 0.0, 0.0),
            ("f", "fy", "fg", p["t104_fb_per_half"], 0.0, 0.0, 0.0),
        ],
        p["t104_l_half_h"],
        p["transformer_k"],
    )

    # Bridge rectifier, time constant network, ZERO.
    d = diode.model_name
    L += [
        "* --- rectifier and time constant ---",
        _r("136", "ay", "bk", p["r136_ohm"]),
        _r("leak", "bk", "0", p["numerical_leak_ohm"]),
        f"DCR101 ay tcb {d}",
        f"DCR102 bk tcb {d}",
        f"DCR103 cv ay {d}",
        f"DCR104 cv bk {d}",
        *_time_constant(p["time_constant"], p, "cv", "tcb"),
        f"C115 tcb 0 {num(p['c115_f'])}",
        *_pot("142", "0", "tcb", "vb", p["r142_ohm"], p["zero"]),
    ]
    return Circuit("\n".join(L) + "\n", INPUT_NODE, SAVE, p, files)
