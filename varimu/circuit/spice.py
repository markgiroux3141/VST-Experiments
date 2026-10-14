"""Circuit IR -> ngspice netlist text (the reference engine's input).

The device models write their own SPICE (subcircuits, model cards), so the
behavioral expressions stay next to their Python reference implementations.
Triode plate currents go out in one of two formulations:
- "exact": the analytic behavioral expressions;
- "table": an XSPICE table2D of the Python model (varimu.devices.table),
  ~20x faster in ngspice. The table files come back with the text, to be
  copied next to the netlist.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from varimu.circuit.ir import (
    Capacitor,
    CircuitIR,
    Coupling,
    Device,
    DeviceModel,
    Element,
    Inductor,
    Resistor,
    VoltageSource,
)
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


def emit(
    ir: CircuitIR,
    *,
    triode_formulation: str = "exact",
    table_grids: Mapping[str, TableGrid] | None = None,
) -> tuple[str, dict[str, Path]]:
    """Netlist text (no analysis, no .end) and the files it reads (job-dir name -> path).

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
        else:
            lines.append(m.subckt())
    models = {m.name: m for m in ir.models}
    for s in ir.sections:
        lines.append(f"* --- {s.title} ---")
        lines += [element_line(el, models) for el in s.elements]
    return "\n".join(lines) + "\n", files
