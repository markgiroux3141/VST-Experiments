"""Circuit files -> one coupled circuit (IR) -> both engines.

Modules:
    spec.py           circuit files (config/circuits/*.yaml): parameters, sources, overrides
    builder.py        circuit file + overrides -> circuit IR (+ SPICE text); the macro parts
    parts.py          the parts library the macros expand with (pots, transformers, tubes, ...)
    netlist.py        the Fairchild 670's API (build, resolve, ...) on its circuit file
    fairchild_670.py  the 670's derived values (channel 2 lumped) and constants
    ir.py             the circuit IR shared with the Rust engine (crates/circuitsim)
    spice.py          circuit IR -> ngspice netlist text

Every component value traces to a source (a schematic, datasheet, web page, or
provisional model knowledge); anything illegible or ambiguous becomes a bounded
genome parameter.
"""
