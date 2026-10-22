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

from collections.abc import Mapping
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
    Resistor,
    VoltageSource,
    Winding,
    element_nodes,
)
from varimu.devices.core import TESLA_PER_V, MagneticCore
from varimu.devices.diode import JunctionDiode
from varimu.devices.table import TableGrid, cached_table, table_subckt
from varimu.devices.triode import Triode, num

FORMULATIONS = ("table", "exact")


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
    cores = linear_cores(ir)
    folded = {n for c in cores.values() for n in c["parts"]}
    for s in ir.sections:
        lines.append(f"* --- {s.title} ---")
        for el in s.elements:
            if isinstance(el, Winding):
                lines.append(winding_line(el, cores[el.core]))
            elif el.name not in folded:
                lines.append(element_line(el, models))
    if cores:
        lines.append("* --- linear cores: windings coupled (leakage folded in), eddy loss ---")
        for node in sorted(cores):
            lines += core_lines(node, cores[node])
        if rshunt_ohm is not None:
            lines.append(f".options rshunt={num(rshunt_ohm)}")
    return "\n".join(lines) + "\n", files
