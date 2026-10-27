"""The schematic editor in our web app (device builder B4a).

- varimu.editor.symbols: varimu.kicad.symbols' table as JSON for the page (SVG path data,
  pins with roles, fields), and the placement transform both sides share;
- varimu.editor.drawing: the drawing document (<name>.drawing.json), its reading and
  writing;
- varimu.editor.connect: a drawing's connectivity (pins, wires, labels, ground) as nets,
  and as a varimu.kicad.netlist.Netlist;
- varimu.editor.compile: a drawing -> a circuit file through varimu.kicad.importer, with
  the pre-flight checks mapped back onto the drawing;
- varimu.editor.layout: a generated drawing of a hand-written circuit (the exporter's
  parts, label-connected).

The page is varimu/listen/editor.html with its ES modules in varimu/listen/editor/,
served by `varimu listen` at /editor (varimu.listen.editor_api). Nothing here is in the
render cache key.
"""
