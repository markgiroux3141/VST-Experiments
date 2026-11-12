"""Tape at the particle level (docs/TAPE_PARTICLES.md): a study, not part of the tape model.

Single-domain Stoner-Wohlfarth particles with thermally activated switching (`sw`), an
ensemble drawn from physical distributions (`ensemble`), its static loops and the fit to
3M's static data (`static`), recording on a strip of coating moving past the record head
with AC bias (`medium`, the Python reference; `crates/tapeparticles` is the GPU version)
and Sound Talk No. 21's bias curves as a blind prediction (`no21`).

Nothing in varimu/devices, the circuits or the render cache depends on this package.
"""
