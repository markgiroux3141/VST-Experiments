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

## Open (the user's)

- Listen: the room tracks (`reports/rooms/separation/*/target/*.wav`, the mixes in
  `*/mixes/`), the staircase (`uv run --extra listen --with sounddevice python
  scripts/separation_listen.py --room`), the Room view on a session of your own.
- Whether the room goes to Rust (the app then renders without Python) before A5.
