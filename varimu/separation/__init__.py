"""Track separation experiments (docs/SEPARATION_PLAN.md).

Prototypes for the plan's cheap first experiment: tape flutter per record pass
(`flutter`), a shoebox room by image sources with a diffuse tail (`room`), the
separation measures (`metrics`) and the tube synth played from note lists (`phrases`).
They process audio offline, outside the circuit netlist, and none of it is in the render
cache key. The full models (TAPE_PLAN.md's transport, a room as a medium, microphones as
components) replace them if the experiment says they're worth it.
"""
