"""Device models (Phase 1).

Planned modules:
    triode.py       Koren triode + N-section variable-mu extension, grid current
    fit.py          fitting device models to digitized datasheet curves
    transformer.py  transformer parameter sets -> SPICE subcircuits (Phase 2)

Every model has a SPICE implementation and a Python reference implementation,
with tests that they agree.
"""
