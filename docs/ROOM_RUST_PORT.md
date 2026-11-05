# Backlog: the room in Rust

Status: **backlog, not agreed** (2026-11-05, the user: "add this as a doc so we don't lose it").
The question was ROOM_LOOP_PLAN.md's open "whether the room goes to Rust (the app then renders
without Python)", asked again after R7-R11 were built.

## The answer in one line

A Rust port makes the room stage ~1.6x faster but a whole scene only ~10-25% faster: the mic
chains' prints (already Rust, circuitsim) and the wave solver (already on the GPU) set the
time. Its real value is the native app rendering rooms without Python and `uv`.

## Where a scene's time goes (measured 2026-11-05)

The R6 demo's shoebox: 3 sources x 4 mics, 20 s clips, the wave solver below 500 Hz, the RTX
3080.

| Stage | Today (Python + roomsim) | In Rust (estimate) |
|---|---|---|
| Python start-up through `uv` (the Room view's background process) | ~3 s | 0 |
| Load and resample the clips | 3.7 s | ~0.5 s |
| Geometric room (mostly the diffuse tail's FFTs) | 7.4 s | ~1.5-2 s |
| Wave solver (GPU-bound) | ~20 s | ~20 s |
| Convolving the clips with the room's responses | 3.7 s | ~0.5-1 s |
| **Room stage** | **~38 s** | **~23 s** |
| Mic chain prints (U47 -> V76 ~5.5x slower than real time) | ~110 s | ~110 s |

- A whole scene: ~150 s -> ~135 s (~10%); with only the clean chains ~65 s -> ~50 s (~25%).
- The wave solver off: the room stage ~15 s -> ~3 s (~5x). That is where Rust shows: quick
  room-only auditions in the Room view in a couple of seconds.

## The work: ~7-9 working days (2-3 overnight sessions)

About 3,000 lines of Python in `varimu/rooms/`:

| Part | Python today | Estimate |
|---|---|---|
| Geometry: floor plans, ceilings, faces, objects, triangles, inside / on-face, image sources and their validation (Borish) | `polyroom.py`, `shoebox.py` (images) | ~1.5 days |
| Diffraction: edges, BTM first and second order, visibility | `diffraction.py` | ~1 day |
| Room responses: band weights, ISO 9613-1 air, image spectra (roomsim already), the diffuse tail and the per-mic receiver gains, the wave-solver blend | `shoebox.py` | ~1 day |
| Wave solver's setup: voxelizing, alpha -> admittance, the capsule's first-order entries, a source's body and cap cells, band groups (the kernel is roomsim already) | `wave.py` | ~1 day |
| Directivity (spherical Bessel and Legendre series), materials (Miki, panels), scene files, solos and the bleed matrix, render.json, the Room view calling it in-process | `directivity.py`, `materials.py`, `scene.py`, `crates/varimu-app` | ~1.5 days |
| Agreement tests against the Python reference (the two-implementation rule), fixtures as `export_app_fixtures.py` does for circuits | | ~1-1.5 days |

Stays in Python: the capsules' entry tables (`varimu/rooms/entries.py` on `varimu/mics/bor.py`'s
BEM: minutes once per capsule, cached). Rust reads them from exported files, as the app reads
device fits. The app already has the resampler (scipy's `resample_poly`, bit for bit) and the
chain prints.

**Agreement:** exact (~-100 dB or better) for the early part (images, diffraction); statistical
for the diffuse tail, whose white noise comes from numpy's generator (PCG64 + ziggurat, not
easily reproduced bit for bit), as the GPU rays already agree with numpy's only statistically.

The original 2-3 day estimate (ROOM_LOOP_PLAN.md, before 2026-11-05) predates R7-R11, which
tripled the room's code.

## The cheaper option: only the hot parts (~1 day)

Move the diffuse tail's synthesis and the convolution into `roomsim`, called from Python as
the rays, image spectra and wave solver already are: the room stage ~38 s -> ~26 s, no change
to the app's architecture. **Recommended if speed is the goal**; the full port when the app
should render rooms without Python.

## Related

ROOM_LOOP_PLAN.md ("Status (2026-11-05)", "Open"); NATIVE_APP_PLAN.md (the native app);
TAPE_SPEED_PLAN.md (the prints' speed, which sets a scene's floor).
