"""KiCad as the schematic editor (device builder, B3).

- varimu.kicad.symbols: the symbol library for the macro parts (kicad/varimu.kicad_sym);
- varimu.kicad.netlist: kicad-cli (find, export the XML netlist) and reading it;
- varimu.kicad.importer: a schematic's netlist plus its sidecar -> a circuit file;
- varimu.kicad.export: a circuit file -> a label-connected KiCad project (a starting
  point for a drawing, and the importer's round-trip fixture);
- varimu.kicad.values: engineering numbers ("40u", "4k7") read exactly.

The pre-flight checks the importer runs are varimu.preflight (they apply to any circuit).
"""
