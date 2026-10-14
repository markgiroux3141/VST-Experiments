"""Genome -> full coupled compressor circuit (Phase 3).

Modules:
    netlist.py      circuit values + overrides -> circuit IR (+ SPICE text)
    ir.py           the circuit IR shared with the Rust engine (crates/circuitsim)
    spice.py        circuit IR -> ngspice netlist text

Every component value traces to the published schematic; anything illegible
or ambiguous becomes a bounded genome parameter.
"""
