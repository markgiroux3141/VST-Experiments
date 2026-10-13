"""Genome -> full coupled compressor netlist (Phase 3).

Planned modules:
    netlist.py      genome -> full netlist
    psu.py          power supply section, shared by audio path and sidechain
    subcircuits/    .lib / .sub files, one per stage

Every component value traces to the published schematic; anything illegible
or ambiguous becomes a bounded genome parameter.
"""
