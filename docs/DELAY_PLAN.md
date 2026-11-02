# Delay: a slap from physical echo machines

Drafted 2026-11-01 from a brainstorm with the user. Nothing in it is built. The user asked
for a delay in keeping with the project: vintage, warm, dirty, from real physics, and
"slappy". The order below is a recommendation; the choices are the user's (Open decisions).

**Where it goes (agreed 2026-11-01):** after the tape work. The slap on the Ampex 351 *is*
TAPE_PLAN.md's TM6 ("Slapback (repro to record, the Sun wiring)"), so finishing TM5 (the
351's circuit and its alignment) and building the slap are one path. The loop machines
(EP-2, EchoSonic) sit on the same tape medium. The non-tape media are independent but are
all new physics.

## Ground rules

CLAUDE.md's hard rules hold. In particular, **delay time is never a parameter**: it is a
head distance over a tape speed, a drum's circumference over its rotation, a pipe's length
over the speed of sound. The darkening, saturation and wobble of the repeats come from the
medium and the electronics each repeat passes through again, not from a filter in a loop.
Feedback (repeats) is a physical path: a REPEAT pot from the repro amplifier back into the
record amplifier, inside the one netlist. The medium's delay is far longer than a sample,
so the loop closes through the `Tape` element causally (no algebraic loop), and the
electronics, bias and supply stay one coupled simulation.

## The options

### 1. Sun slapback on the Ampex 351 (recommended first)

- The repro head's output goes to the mix (one slap) and, through a REPEAT pot, back to the
  record input (repeats).
- **Delay:** the record-to-repro head distance over tape speed: ~2 in, so ~133 ms at 15 ips
  and ~266 ms at 7.5 ips (secondary sources; the manual doesn't print the distance:
  TAPE_PLAN.md, model item 4; `tape_stream.rs` reads 50.8 mm).
- **What falls out of the physics:**
  - every repeat is recorded again: harder saturation, more HF self-erasure and gap loss,
    the head bump each pass, so repeats get darker and dirtier;
  - the flutter heard is v(t) against v(t - delay) (TM3's transport, already built);
  - particle noise and modulation noise build up per pass.
- **Varispeed as a physical control:** the capstan's hysteresis synchronous motor fed from
  a variable-frequency supply (the studio trick) instead of the mains. Slap time and pitch
  move together, as on a real machine.
- **Needs:** TM5. Then the REPEAT and SLAP controls, and the capstan's supply frequency as
  a control.

### 2. Ray Butts EchoSonic (a tube guitar amp with a built-in tape slap)

- The Scotty Moore / Elvis / Chet Atkins amp: a combo of the 5E3's era with a small tape
  loop inside. The most "slappy" item here.
- The slap goes through the same output stage and speaker as the dry signal, so they
  interact (sag, the output transformer, the P12R).
- **Combines** B9's amp work (`fender_5e3`, the speaker `P12R@1`) with the tape medium.
- **Needs:** sources for its circuit and loop geometry (to find), the tape loop (option 3's
  machinery), and C3's open Play speed question settled if it is to be played live.

### 3. Maestro Echoplex EP-2 (tube, a tape loop in a cartridge)

The dirty one. The same medium as option 1, plus:

- **A sliding record head.** Delay set by the head's position (roughly 60-650 ms;
  to source). Moving it while playing glides the pitch, from the head's speed relative to
  the tape, not from a modulation knob.
- **A loop.** The same tape passes again and again:
  - a splice thump once per revolution;
  - wear and dropouts along the loop (a condition dial);
  - **incomplete erasure**: the erase head's real field (TAPE_PLAN.md "Later") leaves
    ghosts of earlier repeats.
- **Condition dials** (memory: "turn it to 11"): loop wear, the pressure pad's felt, dirty
  heads, a tired loop's stretch.
- **Needs:** sources for the EP-2's circuit (tubes) and transport; the medium as a ring of
  cells erased before each recording; the record head's position as a control input.

### 4. Binson Echorec (tubes, a magnetic drum)

- A spinning drum with a steel recording rim, one record head and several playback heads
  switched in combinations; SWELL mode feeds back. Multi-tap rhythmic slaps (Hank Marvin,
  early Pink Floyd).
- **New medium:** a hard steel surface (a Preisach fit to a different material, from
  sources to find) and a rotating geometry; several repro readouts of one medium.
- More character per knob than a tape echo.

### 5. Oil-can delay (Tel-Ray Adineko)

- Charge written by brushes onto a disc rotating in oil, read back by another brush.
- **Physics:** dielectric relaxation and leakage set a frequency-dependent decay; brush
  contact noise and wobble set the grit. Wet, warbly, lo-fi.
- Probably the only option here cheap enough to run live without a reduced tier.
- **New medium**, sourced from patents and service notes rather than datasheets.

### 6. Acoustic slap (speaker -> hose or pipe -> microphone)

- The pre-tape broadcast trick. 100 ms is ~34 m of tubing.
- **Physics:** viscous and thermal wall losses (a frequency-dependent decay, a little
  dispersion); the driver and the mic make it honky.
- **Reuses** the speaker (C3), the acoustic tube sections PHONO_PLAN.md's horns need, and a
  mic from MIC_ROOM_PLAN.md. Linear between its transducers, so cheap.

## What it costs in this codebase

- **Tape options (1-3)** use the `Tape` IR element (TM4: `tape.rs`, `tape_stream.rs`):
  - option 1 needs nothing new in the medium: the feedback is netlist wiring;
  - options 2-3 need a closed loop of tape (cells re-recorded after erase), the erase
    head's field, and (EP-2) a head position that moves (a control input; the head's
    velocity relative to the tape enters the recording and playback geometry);
  - the Echorec needs several repro heads reading one medium.
- **Speed.** The literal 351 runs ~100x slower than real time (TAPE_PLAN.md, TM5's
  status). Live play is essential (the user, 2026-11-01): see "Real time" below.
- **Measurement (a profile for a delay):** the delay against the transport's speed;
  response, THD and noise per repeat (pass 1, 2, 3, ...); the slap's flutter; for the
  loop machines, the erase depth (ghost level) and the splice.

## Real time

Brainstormed 2026-11-01. The user: the delay is an effect at the end of a chain, like the
plate reverb, and **playing it in real time is essential**. It is feasible, I think, for
two reasons below. Nothing here is measured yet ("Measure first").

### Where the ~100x goes today (TAPE_PLAN.md, TM5 and "Speed")

- **The literal bias.** The record side runs at 20 substeps (3.84 MHz in production) to
  resolve the ~99 kHz oscillator: the 351 goes from 46.7x (the medium's own bias) to 106x.
- **The recording kernel.** Every 0.5 um cell x 6 layers x 8 orientations runs over every
  bias peak in its zone (~100). Cells are 7.62 per bias wavelength, so their count per
  second doesn't depend on the tape speed: ~7.62 x f_bias, ~760k per second. That is
  roughly 3-4e9 Preisach corner evaluations per second of audio.
- **The circuit itself:** tubes, JA transformers, the supply. Probably near real time at
  the draft quality, as the 670 is; not measured.

### Reason 1: the delay is its own latency budget

- A cell recorded now isn't read until the repro head reaches it: 133 ms at 15 ips (60 ms
  or more on an EP-2). So the recording doesn't have to finish within the audio block. It
  has to keep up on average, and can run asynchronously, across every core or the GPU,
  with up to ~100 ms of slack.
- Feedback keeps the slack: each repeat crosses the medium again.
- **The medium is the natural partition.** The record side, the repro side and the supply
  meet only through the tape (133 ms) and the reservoirs (capacitor-held: the cut that
  works, TM5's "What it took"). So they run on threads of their own, as the synth's parts
  do. The repro -> record feedback crosses the partitions with a sample of latency in a
  133 ms loop.
- The same holds for the 351 as a plain tape insert: it plays from the repro head 133 ms
  late anyway (the session compensates the latency).

### Reason 2: the full model can generate a cheap one

Under AC bias, a cell's final magnetization is set where the bias's envelope falls out of
the zone: by the audio field it sees there, the bias amplitude, its depth in the coating.
The rest of the chain is linear. A reduced medium, generated from the full one (the
pattern of HYBRID_PHYSICS_PLAN.md: a reduced part made from the full-physics reference,
coupled at its ports, the reference selectable in its place):

- **Recording:** the audio field weighted over the record zone (an aperture: the HF
  self-erasure comes from the audio moving while the bias decays), then a table per layer
  from the Preisach ensemble (remanence against effective field and bias amplitude;
  orientations folded in). Tables computed from `SCOTCH111@N`, never a curve chosen by ear.
- **The tape:** a ring buffer of positions, at audio-rate spacing (no bias residue to
  alias: the bias isn't resolved).
- **Playback:** reciprocity is a linear FIR in position, read at a fractional position;
  flutter is v(t) moving the read and write points (TM3's transport, unchanged).
- **Grain:** the Poisson count per cell as its statistics (variance per cell), the packing
  field's AR(1) as it is.
- **Demag:** a linear loss against wavelength (or a small fixed point), measured against
  the reference.
- **The bias in the circuit:** TAPE_PLAN.md's Option B (the oscillator's amplitude at audio
  rate, a table against 1C2c's voltage with its lag, NOISE BALANCE's asymmetry). Measured
  there: it misses only the bias inside the 6201 head driver, negligible to +6 dB drive,
  ~-34 dB at +12 dB (the "turn it to 11" region). The print keeps the literal oscillator.
- Cost: a few hundred operations per sample. The EP-2's sliding head (a moving write
  point) and the Echorec's heads (several read points) cost nothing more.

### Routes

| Route | Bias | Medium | Fidelity | Risk |
|---|---|---|---|---|
| **A: reduced tier** | Option B | tables + FIR, CPU | measured against the print; a guess: -30 to -45 dB, like the 670's draft | low |
| **B: full medium, async** | Option B | the real kernel in f32 on the GPU, in the 133 ms of slack | near the reference | throughput unknown: a rough 100-200 GFLOP/s of f32 work, within a 3080 on paper (TAPE_PLAN.md "Speed: the GPU": f64 runs at 1/64 there) |
| **C: the project's split** | | A live while playing and adjusting, the reference when printing or rendering (SESSION_FX_PLAN.md: F3's audition, ⤓ Render) | both | none new |

**Recommended: C, with A as the live tier.** It is how the 670 and the synth already work
(draft to play, production to render). B is an experiment for later: if the GPU keeps up,
live becomes the full model.

In the app it plays like the plate: a chain's end (`player::EndDevice`, a block behind on
threads of its own), so its latency doesn't matter for playing.

### Measure first (cheap, before building anything)

1. The 351's electronics at draft-2x, partitioned at the medium, with the medium's own bias
   (`examples/load_profile.rs`): does the circuit fit real time at all, and on how many
   threads?
2. A Python prototype of the tables: how close a static table per layer plus the zone's
   aperture gets to the reference medium on the drums at 0 / +6 / +12 dB drive (dB re the
   print's rms, as TAPE_PLAN.md's speed tables).
3. For B: the kernel's cost per cell on the CPU, to project the GPU's throughput.

## Proposed milestones

- **D1: the Sun slap** (TAPE_PLAN.md TM6's first piece; needs TM5). SLAP level, REPEAT pot,
  the capstan's supply frequency as varispeed. Done when the delay matches head distance
  over speed, the per-repeat profile above is measured and plotted, and it prints as a
  session insert.
- **D1-live: the real-time tier** (TAPE_PLAN.md's TM7, for the delay first). "Measure
  first" 1-3, then route A: the reduced medium in both languages (Python reference,
  circuitsim port), Option B's bias, the circuit partitioned at the medium, a chain's end
  in the app. Done when it runs live without dropouts at the end of a chain and its
  distance from the print is measured and accepted by the user.
- **D2: the Echoplex EP-2.** The loop, the sliding record head, the erase head's real
  field, the splice, its circuit from sources. Done when the delay range and the ghost
  level are measured against sourced figures.
- **D3: the EchoSonic.** The 5E3-family amp with its loop. After C3's Play speed decision.
- **Later:** the Echorec (a steel drum medium), the oil can, the acoustic pipe; route B
  (the full medium on the GPU, live).

## Open decisions (the user's)

- **Single slap or repeats:** the Sun slap only, or the REPEAT pot from the start
  (recommended: both, they are the same wiring)?
- **Live is essential** (decided 2026-11-01). Open: route C with A live (recommended), or
  try B (the GPU) first?
- **The live tier's accuracy:** how far from the print is acceptable (measured, then the
  user's call, as with the 670's draft)?
- **After D1:** the EP-2's dirt, the EchoSonic, or the Echorec next?
- **Where it goes** relative to the other parked tracks (it follows TM5 either way).
