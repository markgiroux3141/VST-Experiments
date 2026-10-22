"""Device models (Phases 1-2).

    triode.py, pentode.py, diode.py   tubes and rectifiers (Phase 1)
    fit.py                            fitting them to digitized datasheet curves
    core.py                           the Jiles-Atherton transformer core (Phase 2)

Every model has a SPICE implementation and a Python reference implementation,
with tests that they agree, except the core (decided 2026-10-21): its Python
reference and the circuitsim device are tested against each other, and
ngspice runs it in its linear limit.
"""
