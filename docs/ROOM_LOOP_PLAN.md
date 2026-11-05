# Closing the loop: sources in a room, recorded through mic chains

Drafted 2026-11-04 with the user, while A3 (the U47 -> V76) was being finished in another
session; started the same day (the user: "be self reliant and make decisions"; R1-R5 and a
Room view in the app built, "Status (2026-11-04)" at the end). It refines
[MIC_ROOM_PLAN.md](MIC_ROOM_PLAN.md)'s A4 (a shoebox room with directions) and A9 (ranking
chains), and turns SEPARATION_PLAN.md's question into a stereo experiment. A5 (arbitrary rooms,
GPU FDTD) and A6 (the Room view) are not needed to close the loop the first time.

## The goal (the user's)

Place sound sources in a room and mics around them, each mic through its own chain, and hear
the result. The first use: **two sources in a room, each spot-miked through a different chain
(the U47 -> V76 and its polar opposite in texture), plus two room mics panned hard left and
right, and measure how well the two sounds separate.**

## Where the loop stands (2026-11-04)

**source -> room -> capsule entries -> mic -> cable -> preamp -> track -> stereo mix**

| Block | Status |
|---|---|
| Capsule, U47 electronics, cable, V76 as one netlist | Built (`u47_v76.yaml`; front pressure on the input, rear on the control input `p_rear`); prints at ~5.5x slower than real time at production |
| Diffraction at the capsule's entries | Built for one free-field wave at a time (`varimu/mics/bor.py`, plane wave or point source; `free_field.body_entry_grid`, cached per angle) |
| Room | Mono only: `varimu/separation/room.py` (omni to omni). It already computes every image's position (`dx, dy, dz`) and drops the direction |
| Scene (sources and mics placed, aims, bleed) | Missing |
| Stereo | The Session view has pan and a stereo bus (`session::balance`); the separation metrics and `separation_listen.py` are mono |

## Steps

### R1. The capsule's entries as a table over angle and distance

The K47's body is a body of revolution, so its front and rear entries depend only on the angle
to the capsule's axis, and on distance for proximity. `bor.entry_factors` takes an array of
angles against one factored operator per frequency, so a table (e.g. 5 deg steps, 0-180, at a
few distances: 0.1, 0.3, 1, 3 m and a plane wave, interpolated in 1 / r) costs about one of
today's cached solves. Cached in `cache/diffraction/` like the per-angle grids. A capsule with
no body falls back to the sphere or the path delay (`capsule_entry_pressures`'s order).

*Done when:* the table, interpolated, reproduces `mic_print`'s direct per-angle entries (within
a stated tolerance, e.g. 0.05 dB / 0.5 deg in band).

### R2. A room with directions (MIC_ROOM_PLAN.md's A4)

`varimu/separation/room.py` grown, not replaced (the mono IR stays for the separation study):

- **Early part:** image sources as now, each arrival keeping its direction relative to the
  mic's aim (angle to the axis) and its distance. Arrivals binned by angle: one partial IR per
  bin (delay, wall reflection per band, 1 / 4 pi r, ISO 9613-1 air), each convolved with that
  bin's front and rear entry responses. ~37 FFT convolutions per mic regardless of image count.
- **Diffuse tail:** independent decaying noise per angle bin, weighted by the bin's solid
  angle, per band at Eyring's RT60 from the images' energy (as now): the cardioid's
  diffuse-field response and the front / rear coherence come out right.
- **Output:** per (source, mic) a two-channel IR (front, rear) at the project's rate, cached by
  the room, positions, aims, the capsule's body and the code.
- **Sources** are point sources first (omni). A source's directivity (a baffled piston, the
  P12R's cone) is later.

*Done when:* an anechoic room (alpha = 1) equals today's free-field print; a source at 180 deg
shows the polar's rejection; the cardioid's diffuse-field level sits at its directivity index
(~-4.8 dB for an ideal cardioid; the U47's own from its polar); the omni IR summed over bins
equals the old mono IR.

### R3. The scene renderer

`scripts/room_print.py SCENE.yaml` (a scene file in `config/scenes/`):

- the room (dims, materials per surface, air), sources (a clip, a position, a level in Pa at
  1 m: MIC_ROOM_PLAN.md's open full-scale convention), mics (a position, an aim, a chain, its
  pattern switch and settings, a pan);
- per mic: the sources' IRs convolved and summed (front, rear), then the chain printed at
  production (parallel, cached; `mic_print.py`'s path);
- **solo renders:** each source alone through every mic, beside the sum. The room is linear,
  so they give a **bleed matrix** per band (each mic's level of each source), and sum minus
  solos shows how much the chains' nonlinearity mixes the sources;
- output: a mono WAV per mic plus its pan, a mix, and JSON with the bleed matrix; importable as
  session tracks (`Session::add_rendered_take`'s pattern) once the Room view exists (A6).

*Done when:* a scene with one source and one mic on axis in an anechoic room equals
`mic_print.py`'s print bit for bit at the same settings.

### R4. The opposite chain

U47 -> V76: a large heavy diaphragm, cardioid with proximity bass, a presence peak ~11 kHz, a
VF14, iron in three places (BV8, T85, T89): mostly 2nd harmonic plus the transformers' bass
saturation.

| Option | Flips | Cost |
|---|---|---|
| **Small pressure omni -> clean transformerless** (recommended) | Every axis: small and fast, flat and extended, omni (no proximity), no iron, ~no harmonics | The capsule machinery is verified on this capsule type (BK4134); B&K's 4006 recording omni came out of their measurement capsules, a real mic to aim at. The electronics are solid state: **fast route**, an op-amp macro part from existing IR elements (C3's `Vccs`, R, C, diode clamps; datasheet GBW, slew, rails; input noise as an equivalent resistor's Johnson noise under B5), a new macro part, not a new device model; **proper route**, the BJT / JFET models (the shared prerequisite for the 1073, the API 312, the 808, the Suitcase) replace it later |
| SM57 -> API 312 | A different texture (mid-forward, odd harmonics, blunted transients), not its absence | The BJT model, a 2520 (~10 transistors), a new moving-coil component; transformers at both ends (less opposite on iron) |
| RCA 44-BX -> the 351's electronics | Tilt, transients, pattern (figure-8), proximity | No new device type (a ribbon component, a step-up on a JA core); tube against tube, so little contrast in harmonics |

**The pattern confound:** an omni spot picks up more of the other source than a cardioid. The
condition "U47 omni -> V76" (its pattern switch) separates texture from pattern.

*Done when (for the recommended option):* the omni's response and self-noise against the
target mic's datasheet; the preamp's gain, noise and THD against its source; the chain one
netlist, printed by R3.

### R5. The experiment (MIC_ROOM_PLAN.md's A9, in stereo)

**Scene:** a live-room shoebox (~7 x 5.5 x 3.2 m, RT60 ~0.5 s). Sources A and B ~2.5 m apart:
the separation study's synth phrases (`varimu/separation/phrases`: the target melody with its
changed note, the arpeggio masker), dry, so the room is the only room they have. Spot mics at
~30 cm, each aimed at its source with its rear toward the other. A room pair spaced ~3 m out,
panned hard left and right.

| Condition | Isolates |
|---|---|
| Dry, no room | The upper bound |
| The same chain on both spots | Room and bleed alone |
| U47 -> V76 on A, the opposite on B | The chains' contribution |
| Swapped (the opposite on A) | Bias from the chains' character and the room pair's chain |
| U47 omni -> V76 on A | Texture against pattern |
| Room pair off / -6 dB / 0 dB | What the room mics cost or buy |
| Spots centred / spots panned | Panning against chain |

**Measures:**
- **Loudness per source** in the final stereo mix, matched from the solo renders ("loudness
  lies", extended from tracks to sources).
- **The bleed matrix** (R3).
- **A stereo glimpse proportion:** better-ear per cell (the larger target-to-masker ratio of
  the two channels) plus a binaural-unmasking term (Lavandier & Culling's model for speech in
  rooms; its constants sourced or marked provisional).
- **The staircase:** `separation_listen.py` in two channels (headphones proposed).

**Cost:** ~4 mics x 3 inputs (A, B, A + B) per condition at ~5.5x slower than real time:
~10 min of wall clock per condition for 10 s excerpts, in parallel.

### R6. Rooms of any shape (2026-11-04, the user: "the square room obviously reflects a lot")

Built the same evening, the user away (decisions delegated). The geometric half of
MIC_ROOM_PLAN.md A5's hybrid, on the CPU; the wave solver (FDTD, GPU) stays A5's.

- **Geometry** (`varimu/rooms/polyroom.py`): any floor polygon (convex or not), vertical walls,
  a ceiling varying along one direction: flat, shed, gable, barrel vault (as facets). Every
  surface a planar face with its material.
- **Early part:** image sources for arbitrary polyhedra (Borish 1984) up to 4 reflections,
  each path validated per mic (reflection points inside their faces, no segment leaving the
  room: a source round an L's corner has no direct sound). Hand-over at 50 ms.
- **Late part:** ray tracing (20,000 rays, specular or Lambert by a provisional scattering
  coefficient per material) gives the room's energy decay per band, e_b(t); the tail's level
  is 4 pi c e_b(t) / V per second (no Eyring, no matching at the hand-over). On a shoebox:
  the image sets agree exactly up to order 3, the ray-traced RT is within 5-10% of Eyring's,
  and the tail formula is within 0.2 dB of the exact images' energy (tests/test_rooms.py).
- **Each mic's own late sound:** the same rays counted in a 0.35 m sphere at every mic
  (50,000 rays, 1 ms bins) give the energy reaching that point; the shared diffuse field is
  shaped per mic by its ratio to the room's mean (mid bands, smoothed over 5 ms). So flutter
  between parallel surfaces and the shadow of an L's corner reach the tail, not only the
  first 50 ms. Measured (the demo's room L mic, envelope autocorrelation at 8-60 ms lags,
  1-4 kHz): the shoebox 0.15 at 15 ms, the same-volume angled room 0.09: with furnished
  walls (scattering 0.3) flutter stays mild, as in a furnished room; the shapes differ most in
  the early reflections' pattern and, by volume and height, in the decay.
- **Found on the way:** the shoebox's tail (started at the images' energy in the 20 ms before
  80 ms) runs ~2-3 dB hot at 0.1-0.4 s. Scenes with `floor_m` go through polyroom (the Room
  view writes only those now); `dims_m` scenes keep the shoebox, so R5's numbers stand as
  computed. Rerendering R5 through polyroom is open.
- **The Room view:** a Shape preset (shoebox, splayed, trapezoid, L-shape, hexagon, octagon)
  at a width and depth, corners dragged (5 cm snap), a double-click on a wall adds a corner, a
  right-click removes one ("custom"); the Ceiling's form, height and peak, the direction it
  rises along, a vault's facets; the plan draws the ceiling's facet lines with their heights,
  the pointer's ceiling height; positions are kept inside the room (the plan and under the
  ceiling). Old scenes (a shoebox's dims) load as a rectangle.
- **The demo** (`scripts/room_demo.py` -> `reports/rooms/demo/`, README.md there): the vocal,
  an acoustic guitar and the piano of "Long Way Home" (Cambridge-MT) in five rooms through the
  same mics, mixes and room-pair-only files at -18 LUFS.

R7-R11 below (built 2026-11-05).

## R7-R11 (2026-11-04, agreed with the user; built 2026-11-05: "Status (2026-11-05)" below)

The user heard the demo ("sounds amazing") and asked what the rest costs. The estimates below
(work, how much it changes the sound, render time) are the agreed basis; the order is the
agreed one. Nothing in it is built.

**Where the time goes today** (a demo room: 20 s of audio, 3 sources, 4 mics, ~150 s): the
U47 -> V76 print ~110 s (~5.5x slower than real time; the chains run in parallel, so the
slowest sets the wall time), the room ~40 s (ray tracing ~10 s per source; the image
sources' spectra ~13 s per source and two mics). So speeding up the room alone takes a scene
from ~150 s to ~115 s: the chain sets the floor.

### R7. A material per wall (first)

Each face its own material (a wall by its edge, the floor, each ceiling facet), the room's
three as the defaults; the Room view picks a wall on the plan and sets it.
- *Work:* 1-2 hours (polyroom already carries a material per face; the scene format, the
  view).
- *Sound:* clearly audible wherever a room is treated unevenly (a live back wall and a dead
  front, a rug under the drums): how real studios are built.
- *Cost:* none.
- *Done when:* a room with one absorbent wall decays as its ray tracing and Eyring's
  area-weighted absorption say; old scenes render unchanged.

### R8. R5 again, on polyroom

The separation experiment rendered through polyroom (its room as `floor_m`), the summary
compared with the shoebox's.
- *Work:* ~1 hour of rendering.
- *Sound:* small: the shoebox's tail was ~2-3 dB hot at 0.1-0.4 s (R6); the numbers move a
  little.
- *Done when:* `summary.json` from polyroom, the differences noted in R5's table.

### R9. The GPU groundwork: rays and reflections

The project's first GPU code (wgpu proposed: MIC_ROOM_PLAN.md's open call wgpu vs CUDA), on
two embarrassingly parallel jobs with a CPU reference already in place:
- **ray tracing** (`polyroom.ray_decay`: 50,000 independent rays, faces, receivers): ~10 s ->
  under 0.5 s per source;
- **the image sources' spectra** (`shoebox.responses`: each image's smooth spectrum
  interpolated and phased over ~65,000 bins, summed): ~13 s -> under 1 s per source and two
  mics.
- *Work:* a few days (the wgpu setup is shared with R10).
- *Sound:* none (the same physics; f32 checked against the CPU's f64).
- *Cost:* the room's ~40 s to a few seconds.
- *Done when:* GPU and CPU agree (decay curves within 0.1 dB, spectra within -80 dB) and the
  demo renders the same.

### R10. The wave solver below a crossover (MIC_ROOM_PLAN.md A5's low half)

3D FDTD of the room on the GPU (a compact / interpolated scheme, Kowalczyk & van Walstijn
2011; walls as locally reacting impedances fitted to the materials), each source's run
recording every mic's two capsule entries, blended with the geometric model above a
crossover (zero-phase complementary, as the separation room's bands).
- *Work:* 1-2 weeks (the scheme, boundaries, the crossover, validation).
- *Sound:* **the biggest step for small rooms.** Below the Schroeder frequency (~160 Hz in a
  7 m live room, 2000 sqrt(RT / V)) the sound is modes: boomy notes, bass that changes with
  position, which the geometric model can't produce. Large on bass, kick and low piano; modest
  on a vocal or a guitar.
- *Cost:* to 500 Hz, ~4e9 cell updates per second of response in a 123 m^3 room: minutes per
  source on the CPU, **1-2 s on the 3080**; to 2 kHz ~250x that, GPU only (~a minute per
  source). The crossover a setting (draft low, overnight high).
- *Done when:* a rigid shoebox's modes match the closed form; FDTD and image sources agree in
  a shoebox around the crossover; GPU (f32) against the CPU reference (f64) on short runs.

### R11. Objects and edge diffraction (together, last)

Objects as primitives (boxes, thin panels at any angle: gobos, a piano lid, a riser) in the
image sources (two-sided faces, occlusion), the rays and R10's grid; edge diffraction for the
geometric part (first order, Svensson, Fred & Vanderkooy 1999; UTD as a cheaper option) so a
gobo shadows the highs but lets the bass round it, and a source round an L's corner is heard
by its edge too.
- *Work:* ~1 day for objects, 2-4 days for diffraction. Objects without diffraction block
  the bass too, which sounds wrong: build them together.
- *Sound:* large for spill and separation (gobos are how studios get isolation: ~5-15 dB in
  the mids and highs on shadowed paths); small in an open room.
- *Cost:* image-source candidates grow with the faces to the 4th power (two gobos ~10x the
  room's time) unless the order drops to 3 or visibility pruning (beam tracing) comes in;
  first-order diffraction seconds, higher orders tens of seconds per scene. On the GPU
  (R9) this stays small next to the chains.
- *Done when:* a source behind a gobo measures against Svensson's edge-diffraction solution;
  an L-room's hidden source against the same; R10's grid agrees below the crossover.

### What the GPU doesn't help

The mic chains' prints (circuit simulation: sample after sample, a small nonlinear solve each)
are sequential and small-matrix: a GPU loses there. They already run one per CPU thread;
faster prints come from CPU-side work (the draft quality, splitting a print in time:
TAPE_SPEED_PLAN.md's parallel-in-time idea). The capsule tables (BEM) are a few minutes once
per capsule, cached: not worth moving.

Also open, unordered: the Rust port of the room (the app without Python; 2-3 days, the room
3-10x faster on the CPU, no change to the sound), the U47's head basket (Known bias below).

## Known bias

With K47@3 the U47's rear rejection is 20 dB at 1 kHz; Neumann's 1958 polars show 16 (the head
basket and body aren't modelled). Bleed into a U47 spot is underestimated by ~4 dB, which
flatters separation. The basket is the fidelity item that matters most here; it isn't
axisymmetric about the capsule's axis, so it is more than `bor.py`'s order-0 solve (a 3D BEM,
GPU candidate). Report results with this caveat until then.

## Later (not needed to close the loop)

MIC_ROOM_PLAN.md's A5 (arbitrary rooms: GPU FDTD below a crossover, geometric above), A6 (the
Room view in the native app, prints into session tracks), source directivity, the head basket,
more mics and preamps (A7-A8).

## Status (2026-11-04)

Built the day it was drafted (the user away, decisions delegated: "Decisions" below).

- **R1, the entry tables** (`varimu/rooms/entries.py`): per capsule, front / rear over 2.5 deg
  x 1 / r (11 distances from 0.1 m, a plane wave) x 240 log frequencies; a body by the BEM
  (`bor.entry_table`: one system per frequency for every incidence; K47@3 in 193 s, BK4134@2 in
  143 s, cached), a path or a pressure capsule in closed form. Interpolated against direct BEM
  solves between grid points: within -41 dB at worst (the shadowed rear entry at 20 kHz),
  -60 to -100 dB below 10 kHz. `bor.py` gained `pressure_mesh` (a capsule flush on a cylinder,
  `body: {form: cylinder}`) and a mesh with no rear diaphragm.
- **R2, the room** (`varimu/rooms/shoebox.py`): every image source through its table, built
  in the frequency domain (each image's smooth spectrum on the table's grid, its delay as an
  exact phase); air per frequency (ISO 9613-1; the separation room's was per octave up to 8
  kHz: below 6 kHz the two agree within -30 dB); the diffuse tail as 96 shared plane waves.
  Tests (`tests/test_rooms.py`): the anechoic room is 1 / r through the air within 1%; the
  tail continues the images' energy within 3 dB; two omnis 0.3 m apart cohere at 150 Hz and
  not at 2-6 kHz (the diffuse field's sin(kd) / kd); the BMLD's textbook cases (N0S0 0 dB,
  N0Spi 13-16 dB at 250 Hz). ~50 s for 2 sources x 4 mics (numpy; a speed item below).
- **R3, scenes** (`varimu/rooms/scene.py`, `scripts/room_print.py`, `config/scenes/
  two_sources.yaml`): mic prints in parallel, cached; solos for the bleed matrix. The plan's
  "bit for bit with mic_print" became "the same physics through the table" (the table's
  interpolation, above).
- **R4, the opposite chain:** `omni_4134` (BK4134@2: @1 on its 1/2-inch housing, 90 mm; +3
  dB at 8 kHz and +8.7 dB at 20 kHz on axis from the body; a TL071 follower: 9.51 mV/Pa) into
  `clean_pre` (an NE5534A: 20 / 40 / 60 dB within 0.2 dB, no measurable THD below its +-12.7 V
  clip) = `omni_clean`, on the new **`opamp`** macro part (both builders bit for bit, a KiCad /
  editor symbol `OpAmp`; datasheet figures in `data/datasheets/opamps/README.md`).
  `tests/test_clean_chain.py`. Unlike the U47 -> V76 (~5.5x slower than real time), it renders
  at ~1-1.5x.
- **The Room view** (`varimu-app --room`, a tab): the plan to scale with a 1 m grid, sources
  (session tracks) and mics dragged, mics aimed (right- or Shift-drag, "Aim at") and drawn with
  their pattern, chain and settings per mic, distances and off-axis angles listed; Render runs
  `scripts/room_print.py` through `uv` in the background (progress, cancel) and adds a track per
  mic, panned, as one undo step; the scene per session in `<session>/rooms/scene.json`. The
  render path is tested end to end (`crates/varimu-app/tests/room.rs`, ignored by default: it
  needs uv); the canvas was checked on screen, not driven by a test.
- **R5, the experiment** (`scripts/room_separation.py` -> `reports/rooms/separation/
  summary.json`; mixes for `separation_listen.py --room`): 7 x 5.5 x 3.2 m (RT60 0.44-0.84 s),
  the target melody (A) and the masker arpeggio (B) 2.5 m apart, spots at 0.3 m, the room pair
  through the clean chain at 40 dB (50 clipped it: rerendered). Each stem at -23 LUFS, the
  target 6 dB under. Effective TMR (better-ear + BMLD, mean over ERB bands; dB, higher = more
  separated):

  | Spots (A / B) | centred, no room | centred, room -6 | centred, room 0 | panned +-0.5, no room | panned, room -6 |
  |---|---|---|---|---|---|
  | U47 -> V76 both (`same_u47`) | -6.07 | -5.39 | -4.86 | -0.47 | -1.33 |
  | clean omni both (`same_omni`) | -5.82 | -4.46 | -3.45 | -0.88 | -1.58 |
  | U47 / clean omni (`opposite`) | -8.45 | -8.04 | -7.01 | -3.10 | -4.55 |
  | clean omni / U47 (`swapped`) | -6.26 | -4.45 | -3.24 | -0.47 | +0.25 |
  | U47 / U47 omni (`pattern_control`) | -5.63 | -4.90 | -4.48 | -0.41 | -1.49 |

  What it says:
  - **Opposite chains move separation between the tracks rather than adding it** (by these
    measures): the track through the bright, flat omni chain gains, the one through the U47 ->
    V76 loses (`opposite` -2.4 dB, `swapped` up to +1.6 dB re `same_u47`); averaged over both
    ways round it is about what one chain on both gives. The separation study found the same
    for brightness (SEPARATION_PLAN.md: "in one direction").
  - **It is the chain's spectrum, not its pattern:** B through the U47 in omni
    (`pattern_control`) scores like `same_u47`; B through the clean omni scores 2.8 dB lower. The
    pattern sets the spot's isolation (own source minus the other: U47 cardioid 12.5-14.3 dB, U47
    omni 7.9, clean omni 8.0-8.6) but in a loudness-matched mix that hardly moves the measures.
  - **Panning is the big lever** (+5.6 dB from centred to +-0.5); the room pair adds ~1 dB of
    binaural unmasking below 1.5 kHz at 0 dB and helps centred spots (+1.2 to +3 dB) but costs
    panned ones ~1 dB (it smears the panning), except `swapped`.
  - The U47 -> V76 mixes the sources at -54 to -58 dB (intermodulation), the clean chain at
    -146 dB: the stems-from-solos mixes are exact to that.
  - These are energetic and binaural measures: they can't see grouping by texture (harmonic
    signature, onsets, common fate), which is what opposite chains are for. The staircase
    (`separation_listen.py --room`, headphones) is the test of that; the bias above (the U47's
    deeper rear null: its bleed ~4 dB low) flatters every U47 spot.

**Speed items:** `shoebox.responses` (~13 s per source and two mics in numpy: the per-image
phases; a time-domain binning, complex64 or the GPU), the U47 -> V76 prints (~5.5x slower than
real time), a Rust port of the room (the app without Python).

## Decisions (2026-11-04, delegated by the user: "make decisions")

1. **The opposite chain: the small pressure omni into the clean transformerless preamp**
   (`omni_4134` -> `clean_pre` = `omni_clean`), the op-amp macro first (R4). The SM57 -> API
   312 waits for the BJT model; the 44-BX -> 351 stays a candidate.
2. **The room pair: the clean omnis** (the classic spaced pair), through the clean preamp at
   40 dB (50 clipped its NE5534 on the room's peaks). The swap condition cancels its bias.
3. **The staircase on headphones** (`separation_listen.py --room`).
4. **The Room view now, not after A5:** a tab in the native app (the user's offer), rendering
   through the Python reference as a background process until the room is ported to Rust.

## Status (2026-11-05)

R7-R11 built in one night, the user away ("let's build what's in ROOM_LOOP_PLAN.md ... be self
reliant and make decisions"; the decisions: "Decisions (2026-11-05)" below). Commits ceeb216
(R7-R9) and e0497e6 (R10-R11) plus the night's last.

- **R7, a material per face** (`PolyRoom.face_materials`, a scene's `materials.faces`: `"wall N"`
  from the plan's corner N to N + 1 as the plan was given (a clockwise plan's walls renumbered
  inside), `"ceiling N"` a facet, `floor`). Drapes on one long wall of the 7 x 5.5 m room: the
  ray-traced RT falls 8-23% above 250 Hz, within 15% of Eyring's area-weighted absorption (Eyring
  under-reads concentrated absorption, as known), the drop itself within 10%. The Room view: a
  click on a wall selects it (its surface at the side, walls with their own surface drawn in its
  colour and named), a "Ceiling facets" list, corner edits keep each wall's surface (a split
  wall's halves both keep it, a merged one keeps the earlier one's). Old scenes render unchanged
  (naming a face with its room's material changes nothing, bit for bit).
- **R8, R5 on polyroom** (`room_separation.py --room poly` -> `reports/rooms/separation/
  polyroom/`, `compare.json`): the table's cells move by at most 1.3 dB, most under 0.5; the spots'
  isolation (own minus other) rises 1.0-2.1 dB (the shoebox's tail ran 2-3 dB hot, R6). Every
  conclusion of R5 stands. With the wave solver too (`--wave 500` -> `polyroom_wave/`): the
  cells move by at most 1.3 dB again (the same-omni conditions with the room pair drop ~1 dB: a
  modal low end gives the pair less binaural unmasking); the conclusions stand.
- **R9, the GPU** (`crates/roomsim`: wgpu 29, already in the lockfile through eframe; Vulkan on
  the RTX 3080; Python module `roomsim` in the `fast` extra; `varimu.rooms.gpu` picks "gpu",
  "cpu" (roomsim's f64 reference) or "numpy" (the original), `$VARIMU_ROOM_BACKEND`; a stale
  build refused like circuitsim's). Ray tracing (`rays.rs` / `rays.wgsl`): the rooms as
  triangles (`PolyRoom.triangles`), the same counter-based random numbers on GPU and CPU, the
  sums in 64-bit fixed point with integer atomics (a GPU run repeats bit for bit), "still
  travelling" sampled at instants (no 1 - cumsum cancellation). The image sources' spectra
  (`spectra.rs` / `spectra.wgsl`): the phase k d / N reduced exactly in u32 so f32 holds (the
  integer and 12-bit parts exact, the rest small). Against numpy: RTs within 0.5%, GPU against
  roomsim's CPU to the printed digit; spectra -125 to -131 dB. Speed: rays 6-11 s -> 0.3-0.5 s
  per source, spectra 8-12 s -> 0.15-0.3 s; the Rust CPU reference alone is 40x numpy. The
  done-when's "the demo renders the same": the R6 demo's shoebox and angled rooms, every source
  to every mic, GPU against numpy: octave levels within 0.03 dB on average (0.26 dB at worst),
  the tails within 0.1 dB (the rays' random numbers differ, so statistically).
- **R10, the wave solver** (`varimu/rooms/wave.py`; roomsim's `fdtd`, `fdtd_update.wgsl` /
  `fdtd_read.wgsl`). The scheme: the standard rectilinear one read as a finite volume scheme
  (Bilbao, IEEE TASLP 21(7), 2013), so walls of any shape, staircased, are energy-stable
  locally reacting admittances (each wall link its face's admittance divided by |n|_1, the
  staircase's extra area). The grid: 20 points per wavelength at the crossover (3.4 cm at 500
  Hz), the step a whole number of the project's samples. Walls per band: one run per octave band
  whose weight reaches under the crossover, with that band's admittance (Paris' random-incidence
  inversion of the material's alpha); the room is LTI, so the response at f depends only on the
  walls at f, and the runs are weighted by the geometric model's band weights. Mics: pressure and
  gradient; the capsule's entries to first order from its entry table (A + B cos theta: within
  1% to 700 Hz for a 2 cm path), proximity from the near field's gradient. The blend: zero-phase,
  the first 40 ms crossed in amplitude (the same arrivals in both), the rest in power (two
  unrelated tails: amplitude weights dipped the crossover's octave ~1.6 dB). The zero-frequency
  mode (a pressure impulse leaves a sealed room a pressure offset) high-passed at 15 Hz.
  Checks: a rigid box's modes within 0.05% of the closed form; a rigid shoebox within -38 dB of
  exact image sources at 100-340 Hz (its walls on whole cells; -20 dB with walls up to half a
  cell off, the voxelization's 1.7 cm); band decays at the ray-traced RT (0.98x at 250 Hz, 1.02x
  at 500; the normal-incidence mapping gave 0.56x); GPU against CPU on first differences -93 to
  -107 dB; and against a 0.6 s image model with the same walls in the 4.2 x 3.4 m room within
  +-0.5 dB from 79 Hz to 1 kHz. There the production geometric model (images to 50 ms, a
  ray-traced noise tail) is -6 to +3 dB off at the low end, one random realization of the right
  average: what the wave solver replaces. Speed: ~32 G cell updates/s; 6.5 s per source at 500
  Hz in 123 m^3 (4 bands), 125 s at 1 kHz.
- **R11, objects and edge diffraction.** Objects: oriented boxes (`room.objects: [{center_m,
  size_m (width, depth, height), yaw_deg, tilt_deg, material, name}]`), their six faces after
  the room's (a room's faces keep their indices); image sources through objects to order 2 (the
  room's own to 4), occlusion of every path, rays (GPU and numpy), the wave solver's grid (a thin
  one grown to a cell). Diffraction (`varimu/rooms/diffraction.py`): first-order BTM (Svensson,
  Fred & Vanderkooy, JASA 106(5), 1999), the edge sampled at half a sample of path and
  log-densely near the apex; edges: a box's 12 (nu = 2/3), a thin panel's 4 as a plate's (nu =
  1/2), a plan's reflex corners; from the source and its first-order images, visibility checked
  along the edge. On the GPU each path's response becomes micro-images sharing one smooth
  spectrum (the spectra kernel's `spec_index` and `scale`). Checks: the diffracted wave jumps by
  the direct sound's 1 / d at the shadow boundary (within 0.5%: the total field continuous); a
  long screen's insertion loss on Maekawa's law (its slope exact, the level within 0.3 dB once
  its two equal edges are counted); an L-room's hidden source arrives at the corner path's delay;
  behind a gobo the wave solver and the geometric model with diffraction agree below the
  crossover (third octaves 200-315 Hz within 4 dB, their sum within 2 dB); GPU against numpy
  -128 dB. The Room view: OBJECTS (+ Gobo, + Riser, + Cabinet), dragged, turned (right- or
  Shift-drag), sized, tilted, surfaced; drawn from above in their surface's colour.
- **Directional sources** (the "Later" list; `varimu/rooms/directivity.py`): a cap on a rigid
  sphere (Morse & Ingard's series; Flanagan 1960 for the mouth), normalized on its axis (a
  scene's `spl_db` is the on-axis level, so a directional source puts less power into the room).
  Presets: `voice` (9 cm head, 2 cm mouth), `amp_1x12`, `amp_2x12`, `bass_1x15`, or the sizes; a
  source's `directivity` and `aim` in a scene. Paths are traced from the cap (the source's
  position) with the far-field pattern moved there (the rear's sound 2a / c late); every image
  in the direction it leaves the source (mirrored back through its reflections), diffraction
  paths too; rays start with |D|^2 (roomsim's ray weights). The wave solver puts the source's
  body in its grid (the sphere rigid, the cap's cells driven, the response taken to the
  on-axis normalization analytically): a monopole and dipole fit was tried first and was 1-4
  dB off for a cabinet at ka ~ 2. Checks: a voice ~8 dB down behind at 4 kHz, an amp beaming
  (-15 dB at 45 deg by 2 kHz); turned away in an anechoic room, down by D(180) within 0.3 dB;
  the body in the grid against the exact near-field series 2.25 m out within 0.1-0.65 dB at
  80-250 Hz (0.75 m out within 1.1 dB: there the rear is 8 dB down even at 80 Hz, a near field
  the far-field pattern doesn't have). The Room view: a source's "Radiates" and "faces",
  right- or Shift-drag to aim, the facing drawn.
- **The demos** (READMEs in each folder): `reports/rooms/wave_demo/` (kick, bass and piano
  through a spaced omni pair in a small room and the live room, the wave solver off / on, and
  the live room with a dead front wall and a plaster back wall (R7)); `reports/rooms/gobo_demo/`
  (vocal and guitar on close omnis, without / with a gobo, in the live room and treated: the
  bleed falls ~2-4 dB above 500 Hz in the live room, ~6-7 dB treated, nothing at 63 Hz);
  `reports/rooms/demo_wave/` (the R6 demo's five rooms again with the wave solver, beside
  `demo/`); `reports/rooms/source_demo/` (an electric guitar through a 1x12 combo facing the
  room pair, facing the wall, and as an omni).

**What the demos found.** The wave solver lifts a small room's low end at a mic by 5-14 dB at
25-125 Hz over the geometric model's average (the modes at 41, 50, 65 Hz), 4-12 dB below 100 Hz
in the live room. A gobo in a live room is worth a few dB: the reverberant bleed comes round it.
Uneven treatment changes the balance: plaster where furnished walls were lengthened the bass
(125 Hz RT 0.52 -> 0.74 s) while the mids shortened.

**The diffuse tail, fixed and faster (late that night).** Its plane waves now carry one white
noise each, shared by the bands (each band's envelope on it): independent noises per band,
crossed over by amplitude weights that sum to 1, left the tail up to 3 dB low between band
centres (an octave-periodic ripple). The mic's view of the field (its entries and arrival
phases per direction) is formed once per mic for every source, the phases as a running
product: the room's computation 18.5 -> 8.6 s for 3 sources and 4 mics. Renders after this
change differ from the night's demos in the tail's realization (and those dips).
A source within a cell of a wall runs in the wave solver (its injection renormalized over the
room's cells); a mic inside a directional source's body is refused (Python and the Room view).

**Treatments from their physics** (MIC_ROOM_PLAN.md A5's "materials from physics";
`varimu/rooms/materials.py`): a surface's locally reacting impedance from its construction,
its random-incidence absorption by Paris' average per band (the lowest band over 44-177 Hz:
it stands for everything under 125 Hz). Porous layers by Miki's model (flow resistivity,
thickness, an air gap behind), panel absorbers as a mass on a cavity (empty or filled).
Offered as materials beside the measured ones: `mineral_wool_50mm`, `mineral_wool_100mm`,
`wool_100mm_gap_100mm`, `foam_25mm`, `panel_trap_plywood` (~58 Hz, 0.94 at 50 Hz); the Room
view lists them. An ordinary stud wall stays the measured `gypsum_on_studs` (as a lightly
damped panel it under-absorbs). The demo `wave_demo/small_trapped`.

**Diffraction made reciprocal.** The first version had paths reflecting before an edge (the
source's images) but not after it; the mic's first-order images went in too, so a source and a
mic swapped hear the same: in an L-shaped room with a gobo and a turned box (95 paths) the
early responses agree within -126 dB (`test_the_early_response_is_reciprocal`). The night's
demos were rendered before this (their gobo numbers would move a little).

**Robustness.** A smoke-test scene using every feature at once (an L-shaped gable room, treated
walls, a gobo and a riser, a voice and an amp aimed, the wave solver, solos) found one bug: a
source and a mic in one plane through a thin panel's edge put BTM's denominator through 0 / 0
at the apex (~1e275, inf on the GPU); written without cancellation now (diffraction.py, a test
on that geometry). A fuzz of 40 random scenes (plans, ceilings, objects, surfaces, directional
sources, the wave solver) then found nothing: every response finite, the omni early part
reciprocal within -122 to -140 dB; four of them run as `test_random_rooms_are_finite_and_
reciprocal`. The CPU wave solver (the fallback without a GPU) keeps its threads over a run:
~35x slower than the 3080, usable.

**Second-order diffraction** (`diffraction.paths2`, `btm2`): over two edges of one thick object
sharing a face, source to mic, where the source doesn't see the mic. Svensson & Calamia's
double integral times 1/2 for the path along the shared face; checked in the thin limit (a
thick screen's two top edges 5 mm apart against the knife edge: within 0.5 dB, 250 Hz-4 kHz).
Behind a 0.6 x 0.5 x 1.2 m cabinet in an anechoic room first order alone gave silence; now the
bass wraps round (0.6 dB at 250 Hz) and the highs are shadowed (15-25 dB from 4 kHz). Its
cost is bounded (500 points an edge; skipped where the direct sound arrives): the fuzz's
scenes with two large boxes 30-100 s -> under 11 s.

**Not done / limits.** Diffraction of third order and over edges of different objects (thin
panels are plates, so gobos are fine); a second-order path with a reflection. The rays' per-mic tail shaping uses the mid bands (shadowing by objects is
the same for every band in the late part). The Room view's new controls (wall surfaces, facets,
objects, directional sources, the wave solver) are tested through the scene model and were seen
drawn on screen once (the app run on a scratch `APPDATA` and session, so the user's last session
and prefs stayed untouched): the surfaces coloured and named on the plan, the gobo and a riser
to scale, the sources' facing, the forms; dragging and clicking weren't driven.

## Decisions (2026-11-05, delegated: "be self reliant and make decisions")

1. **wgpu, in a crate of its own** (`crates/roomsim`), not CUDA and not inside circuitsim: any
   vendor, the native app can use it, the room's Rust port grows from it.
2. **Deterministic GPU sums** for the rays (fixed point), so a render repeats exactly
   (Reproducibility); the GPU is the default backend, numpy kept as the reference.
3. **The wave solver's scheme: the standard rectilinear one as finite volumes** (Bilbao 2013)
   rather than Kowalczyk & van Walstijn's interpolated scheme: provably stable on staircased
   walls of any plan; dispersion paid for with 20 points per wavelength at the crossover.
4. **Frequency-dependent walls as one run per octave band** rather than a filtered admittance:
   exact for an LTI room where one band weighs, reuses the materials' tables as they are.
5. **Paris' random-incidence admittance** (measured: decays match the rays; normal incidence
   decayed 1.8x too fast).
6. **The crossover: 500 Hz for new scenes in the Room view** (6.5 s per source on the 3080);
   250 / 1000 offered; old scenes load with it off and render as before.
7. **Objects as oriented boxes**, a gobo a thin one; image sources through objects to order 2.
8. **First-order BTM**, thin panels as plates; second order added later the same night for
   a thick object's edges (validated in the thin limit), bounded in cost.
9. **Source directivity as a cap on a sphere** (one physical model for voices and cabinets),
   built the same night from the "Later" list; in the wave solver the body itself, not a
   multipole fit.

## Open (the user's)

- Listen: `reports/rooms/wave_demo/` and `reports/rooms/gobo_demo/` (READMEs), then the Room view
  on a session of your own (a wall's surface, a gobo, the wave solver).
- Listen: the room tracks (`reports/rooms/separation/*/target/*.wav`, the mixes in
  `*/mixes/`), the staircase (`uv run --extra listen --with sounddevice python
  scripts/separation_listen.py --room`), the Room view on a session of your own.
- Whether the room goes to Rust (the app then renders without Python) before A5: roomsim now
  holds its heaviest parts (rays, image spectra, the wave solver); the geometry, image-source
  validation, diffraction, the tail's synthesis and the entry tables are still Python.
- Next candidates (none agreed): the U47's head basket (Known bias); a frequency-dependent wall admittance in one run (fewer runs at high crossovers);
  measured instrument directivities (a piano's lid, a trumpet's bell) beyond the cap on a
  sphere.
