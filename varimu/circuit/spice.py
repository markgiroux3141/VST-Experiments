"""Circuit IR -> ngspice netlist text (the reference engine's input).

The device models write their own SPICE (subcircuits, model cards), so the
behavioral expressions stay next to their Python reference implementations.
Triode plate currents go out in one of two formulations:
- "exact": the analytic behavioral expressions;
- "table": an XSPICE table2D of the Python model (varimu.devices.table),
  ~20x faster in ngspice. The table files come back with the text, to be
  copied next to the netlist.

Windings on a core node (Phase 2): a MagneticCore has no SPICE
implementation (decided 2026-10-21), so ngspice runs circuits whose cores
are in their linear limit: only resistors (the core's limit, the gap) and
capacitors (eddy loss) from the core node to ground. That magnetic circuit,
sum(N i) = G u + C du/dt with every winding at N A TESLA_PER_V du/dt, is
exactly coupled inductors: with permeance P = A TESLA_PER_V / G and each
winding's leakage inductor in series folded in (an Inductor alone on the
winding's inner node), the inductance matrix is L_jj = L_leak,j + P N_j^2,
L_jk = P N_j N_k, so k_jk = P N_j N_k / sqrt(L_jj L_kk). The eddy loss is
what eddy currents are, a shorted turn: one more winding of the first
winding's turns, without leakage, closed by a resistor N^2 A TESLA_PER_V / C
(its mmf is then exactly the core node's C du/dt). The core node and the
windings' inner nodes don't appear in the SPICE text (spice_nodes lists the
nodes that do).

Tried and dropped (measured 2026-10-21 on the 670 with linear cores):
controlled sources that differentiate the core node, as the IR literally
reads (ngspice's transient stopped at a few ns: trap's differentiation
rings); an ideal transformer of VCVS / CCCS pairs on a magnetizing
inductance (stopped at ~60 ns at the bridge diodes on T104's secondary); and
separate leakage inductors with the windings coupled at k = 1 (runs at
production tolerances, stopped at ~30 ns at the reference's gear 1e-4, on the
node between T102's leakage and magnetizing inductances).

A circuit with windings also gets `.options rshunt=1e12` (1 pS from every
node to ground, in ngspice only): without it ngspice at reltol <= 1e-4
stopped within ~60 ns at the bridge diodes on T104's floating secondary
(trap and gear, every emission above; measured 2026-10-21). 1 pS is 1e-3 of
the island's 1 GOhm leak and far below every other conductance.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from varimu.circuit.ir import (
    GROUND,
    Capacitor,
    CircuitIR,
    Coupling,
    Device,
    DeviceModel,
    Element,
    Inductor,
    IRError,
    NoiseCurrent,
    Resistor,
    SineSource,
    TubeNoise,
    Vccs,
    VoltageSource,
    Winding,
    element_nodes,
)
from varimu.devices import noise as nz
from varimu.devices.core import TESLA_PER_V, MagneticCore
from varimu.devices.diode import JunctionDiode
from varimu.devices.pentode import Pentode
from varimu.devices.table import TableGrid, cached_table, table_subckt
from varimu.devices.triode import Triode, num

FORMULATIONS = ("table", "exact")

# Noise (device builder B5): the grid offset that gives a tube's gm by difference.
GM_DELTA_V = 1e-3


@dataclass(frozen=True)
class NoiseStream:
    """A unit noise stream ngspice reads as a node's voltage (varimu.sim.io writes its
    samples for the run's length): stream `stream` of source `name` under `seed`, white or
    unit flicker (varimu.devices.noise.unit_stream)."""

    node: str
    seed: int
    name: str
    stream: int
    flicker: bool
    rate_hz: float  # the noise grid (the IR's noise.rate_hz)


def noise_streams(ir: CircuitIR) -> list[NoiseStream]:
    """The unit streams `emit`'s noise elements read, in IR order."""
    if ir.noise is None:
        return []
    out = []
    for el in ir.elements():
        if isinstance(el, NoiseCurrent):
            out.append(
                NoiseStream(
                    _nz(el.name), ir.noise.seed, el.name, nz.STREAM_MAIN, False, ir.noise.rate_hz
                )
            )
        elif isinstance(el, TubeNoise):
            for suffix, stream, flicker in (
                ("s", nz.STREAM_MAIN, False),
                ("g", nz.STREAM_GRID, False),
                ("f", nz.STREAM_FLICKER, True),
            ):
                node = _nz(f"{el.name}_{suffix}")
                out.append(
                    NoiseStream(node, ir.noise.seed, el.name, stream, flicker, ir.noise.rate_hz)
                )
    return out


def _nz(name: str) -> str:
    return "nz_" + name.lower()


def noise_lines(
    el: NoiseCurrent | TubeNoise,
    rate_hz: float,
    devices: Mapping[str, Device],
    models: Mapping[str, DeviceModel],
) -> list[str]:
    """A noise element in SPICE (B5): a resistor's Norton current is a G source on its unit
    stream's node. A tube's noise reads gm and the currents off two copies of the tube on E
    sources (they load nothing; one with its control grid GM_DELTA_V up), sensed by
    zero-volt sources: B sources for the plate (shot, or a pentode's partition noise, and
    gm e_f) and the control grid (full shot noise of its current)."""
    half = rate_hz / 2.0
    if isinstance(el, NoiseCurrent):
        sigma = math.sqrt(el.psd_a2_hz * half)
        return [f"G{el.name} {el.a} {el.b} {_nz(el.name)} 0 {num(sigma)}"]
    d = devices[el.device]
    m = models[d.model]
    target = instance_target(m)
    b = el.name.lower()
    pins = list(d.nodes)
    k, g = pins[-1], pins[-2]  # cathode; the control grid is the pin before it
    lines = [f"* noise of {d.name} (B5): gm and currents from copies of the tube"]
    copied = {}
    for i, n in enumerate(pins):
        copied[i] = f"{b}_e{i}"
        lines.append(f"E{b}_e{i} {copied[i]} 0 {n} 0 1")
    lines.append(f"V{b}_d {b}_gd {copied[len(pins) - 2]} dc {num(GM_DELTA_V)}")
    for c, grid in ((0, copied[len(pins) - 2]), (1, f"{b}_gd")):
        # Copy c's pins: each sensed (V source: i() is the current into that pin).
        nodes = []
        for i in range(len(pins)):
            src = grid if i == len(pins) - 2 else copied[i]
            if i == len(pins) - 1:
                nodes.append(src)  # the cathode: its current returns through E
                continue
            node = f"{b}_c{c}p{i}"
            lines.append(f"V{b}_c{c}s{i} {src} {node} dc 0")
            nodes.append(node)
        lines.append(f"X{b}_c{c} {' '.join(nodes)} {target}")
    ip0, ip1 = f"i(V{b}_c0s0)", f"i(V{b}_c1s0)"
    gm = f"max(({ip1}-{ip0})/{num(GM_DELTA_V)},0)"
    ig = f"i(V{b}_c0s{len(pins) - 2})"
    if isinstance(m, Pentode) and el.partition > 0:
        ib, ic2 = f"max({ip0},0)", f"max(i(V{b}_c0s1),0)"
        psd = f"{ib}/({ib}+{ic2}+1e-30)*{num(el.shot_k)}*({gm}+{num(el.partition)}*{ic2})"
    else:
        psd = f"{num(el.shot_k)}*{gm}"
    rt = num(math.sqrt(el.flicker_v2))
    lines += [
        f"B{b}_p {pins[0]} {k} I={{sqrt({psd}*{num(half)}+1e-60)*v({_nz(el.name + '_s')})"
        f"+{gm}*{rt}*v({_nz(el.name + '_f')})}}",
        f"B{b}_g {g} {k} I={{sqrt({num(2 * nz.Q_E * half)}*abs({ig})+1e-60)"
        f"*v({_nz(el.name + '_g')})}}",
    ]
    return lines


def instance_target(model: DeviceModel) -> str:
    """What a SPICE instance line names: the model card or the subcircuit."""
    return model.model_name if isinstance(model, JunctionDiode) else model.subckt_name


def table_file(model: Triode) -> str:
    """Job-dir file name of a triode's plate-current table (lower case: ngspice lower-cases)."""
    return "v" + "".join(c if c.isalnum() else "_" for c in model.name).lower() + ".tab"


def element_line(el: Element, models: Mapping[str, DeviceModel]) -> str:
    if isinstance(el, Resistor):
        return f"{el.name} {el.a} {el.b} {num(el.r_ohm)}"
    if isinstance(el, Capacitor):
        return f"{el.name} {el.a} {el.b} {num(el.c_f)}"
    if isinstance(el, Inductor):
        return f"{el.name} {el.a} {el.b} {num(el.l_h)}"
    if isinstance(el, Coupling):
        return f"{el.name} {el.l_a} {el.l_b} {num(el.k)}"
    if isinstance(el, VoltageSource):
        return f"{el.name} {el.pos} {el.neg} dc {num(el.dc_v)}"
    if isinstance(el, SineSource):
        # The dc value (for .op) is the t = 0 value, which the transient op
        # takes from the SIN function too.
        return (
            f"{el.name} {el.pos} {el.neg} dc {num(el.at(0.0))} sin({num(el.offset_v)} "
            f"{num(el.amplitude_v)} {num(el.freq_hz)} 0 0 {num(el.phase_deg)})"
        )
    if isinstance(el, Vccs):
        return f"{el.name} {el.pos} {el.neg} {el.ctrl_pos} {el.ctrl_neg} {num(el.gm_s)}"
    if isinstance(el, Device):
        return f"{el.name} {' '.join(el.nodes)} {instance_target(models[el.model])}"
    raise TypeError(type(el))


def linear_cores(ir: CircuitIR) -> dict[str, dict]:
    """Per core node: its windings, the conductance g and capacitance c from it to
    ground (folded into the windings), and each winding's leakage inductor, if it has
    one alone on its inner node (folded in too).
    Raises IRError for anything else on a core node (not a linear core)."""
    cores: dict[str, dict] = {}
    for el in ir.elements():
        if isinstance(el, Winding):
            cores.setdefault(
                el.core, {"windings": [], "g": 0.0, "c": 0.0, "parts": set(), "leak": {}}
            )
            cores[el.core]["windings"].append(el)
    touching: dict[str, list] = {}
    for el in ir.elements():
        for n in set(element_nodes(el)):
            touching.setdefault(n, []).append(el)
    for core in cores.values():
        for w in core["windings"]:
            others = [e for e in touching[w.a] if e is not w]
            if len(others) == 1 and isinstance(others[0], Inductor):
                lk = others[0]
                outer = lk.b if lk.a == w.a else lk.a
                core["leak"][w.name] = (lk, outer)
                core["parts"].add(lk.name)
    for el in ir.elements():
        if isinstance(el, Winding):
            continue
        on = [n for n in element_nodes(el) if n in cores]
        if not on:
            continue
        u = cores[on[0]]
        if isinstance(el, Resistor | Capacitor) and {el.a, el.b} == {on[0], GROUND}:
            u["parts"].add(el.name)
            if isinstance(el, Resistor):
                u["g"] += 1 / el.r_ohm
            else:
                u["c"] += el.c_f
        else:
            raise IRError(
                f"{el.name} on core node {on[0]}: SPICE takes a core only in its linear limit "
                "(resistors and capacitors from the core node to ground)"
            )
    for name, u in cores.items():
        if u["g"] <= 0:
            raise IRError(f"core node {name}: no conductance to ground (a linear core needs one)")
    return cores


def _self_l(w: Winding, core: dict) -> float:
    """The winding's self-inductance: magnetizing plus its folded-in leakage."""
    lk = core["leak"].get(w.name)
    return w.turns**2 * w.area_m2 * TESLA_PER_V / core["g"] + (lk[0].l_h if lk else 0.0)


def winding_line(w: Winding, core: dict) -> str:
    lk = core["leak"].get(w.name)
    a = lk[1] if lk else w.a
    return f"{w.name} {a} {w.b} {num(_self_l(w, core))}"


def core_lines(node: str, core: dict) -> list[str]:
    """Every pair of the core's windings coupled (see the module docstring), and its eddy
    loss as a shorted turn coupled to all of them."""
    ws = core["windings"]
    perm = ws[0].area_m2 * TESLA_PER_V / core["g"]
    # (name, turns, self-inductance) of every coupled inductor, the eddy turn last
    coils = [(w.name, w.turns, _self_l(w, core)) for w in ws]
    out = []
    if core["c"] > 0:
        n_e = ws[0].turns
        name = f"L{node}_eddy"
        out.append(f"{name} {node}_eddy 0 {num(perm * n_e**2)}")
        out.append(
            f"R{node}_eddy {node}_eddy 0 {num(n_e**2 * ws[0].area_m2 * TESLA_PER_V / core['c'])}"
        )
        coils.append((name, n_e, perm * n_e**2))
    for i in range(len(coils)):
        for j in range(i + 1, len(coils)):
            (a, na, la), (b, nb, lb) = coils[i], coils[j]
            k = min(1.0, perm * na * nb / (la * lb) ** 0.5)
            out.append(f"K{node}_{i}_{j} {a} {b} {num(k)}")
    return out


def spice_nodes(ir: CircuitIR) -> set[str]:
    """The IR's nodes that appear in its SPICE text (not core nodes, not the inner nodes
    of windings whose leakage is folded in)."""
    gone = set()
    for node, core in linear_cores(ir).items():
        gone.add(node)
        gone |= {w.a for w in core["windings"] if w.name in core["leak"]}
    return set(ir.nodes()) - gone


def emit(
    ir: CircuitIR,
    *,
    triode_formulation: str = "exact",
    table_grids: Mapping[str, TableGrid] | None = None,
    rshunt_ohm: float | None = 1e12,
) -> tuple[str, dict[str, Path]]:
    """Netlist text (no analysis, no .end) and the files it reads (job-dir name -> path).

    `rshunt_ohm`: ngspice's rshunt for circuits with windings (see the module
    docstring); None leaves it out (a DC operating point doesn't need it, and its
    1 pS per node moves B+ by ~3e-7 V against an exact comparison).

    table_grids maps triode model names to their table grids; every triode
    needs one when triode_formulation is "table".
    """
    if triode_formulation not in FORMULATIONS:
        raise ValueError(f"unknown triode formulation {triode_formulation!r}")
    files: dict[str, Path] = {}
    lines = [f"* {ir.title}"]
    for m in ir.models:
        if isinstance(m, Triode) and triode_formulation == "table":
            if table_grids is None or m.name not in table_grids:
                raise ValueError(f"no table grid for triode {m.name}")
            fname = table_file(m)
            files[fname] = cached_table(m, table_grids[m.name])
            lines.append(table_subckt(m, fname))
        elif isinstance(m, JunctionDiode):
            lines.append(m.model_card())
        elif isinstance(m, MagneticCore):
            raise IRError(
                f"{m.name}: a MagneticCore has no SPICE implementation; "
                "build the circuit with its cores in their linear limit for ngspice"
            )
        else:
            lines.append(m.subckt())
    models = {m.name: m for m in ir.models}
    devices = {e.name: e for e in ir.elements() if isinstance(e, Device)}
    cores = linear_cores(ir)
    folded = {n for c in cores.values() for n in c["parts"]}
    for s in ir.sections:
        lines.append(f"* --- {s.title} ---")
        for el in s.elements:
            if isinstance(el, Winding):
                lines.append(winding_line(el, cores[el.core]))
            elif isinstance(el, NoiseCurrent | TubeNoise):
                assert ir.noise is not None  # validated
                lines += noise_lines(el, ir.noise.rate_hz, devices, models)
            elif el.name not in folded:
                lines.append(element_line(el, models))
    if cores:
        lines.append("* --- linear cores: windings coupled (leakage folded in), eddy loss ---")
        for node in sorted(cores):
            lines += core_lines(node, cores[node])
        if rshunt_ohm is not None:
            lines.append(f".options rshunt={num(rshunt_ohm)}")
    return "\n".join(lines) + "\n", files
