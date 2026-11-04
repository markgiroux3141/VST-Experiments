# Delay: a slap from physical echo machines

Drafted 2026-11-01 from a brainstorm with the user. Nothing in it is built. The user asked
for a delay in keeping with the project: vintage, warm, dirty, from real physics, and
"slappy". The order below is a recommendation; the choices are the user's (Open decisions).

**Where it goes (agreed 2026-11-01):** after the tape work. The slap on the Ampex 351 *is*
TAPE_PLAN.md's TM6 ("Slapback (repro to record, the Sun wiring)"), so finishing TM5 (the
351's circuit and its alignment) and building the slap are one path. The loop machines
(EP-2, EchoSonic) sit on the same tape medium. The non-tape media are independent but are
all new physics.

**Started 2026-11-03 (the user's call):** the Sun slap on the 351 with the REPEAT pot from
the start, live play essential, plus more physical features (ping-pong named). The features
and their order are "The 351 echo (2026-11-03)" below; its status is at the end of this file.

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

## The 351 echo (2026-11-03)

The user's decisions: REPEAT from the start; ping-pong; "anything else cool". Every feature
is a physical part or condition (Ground rules), each heard live and printed literally.

**The device: the 351 as a studio wired it.** The 351 records and plays back at once; the
console around it is ours (Sun's own desk isn't sourced; a passive bus as a 1950s console's
mixing network, values provisional):
- **SEND** (the input to the record side), **REPEAT** (the repro output back into the record
  input through a resistive mix: unity loop gain sits inside its travel, so past it the
  repeats build until the tape and the 6201 saturate: runaway as on a real machine), **SLAP**
  (the repro into the output bus) and **DRY** (the input into the bus).
- The machine's own controls stay (RECORD LEVEL, PLAYBACK LEVEL); the alignment is the
  factory's (`varimu.measure.tape_align`).

**The features, in order (each its own step, measured, then heard):**
1. **REPEAT and SLAP** on the full-physics 351 (the print, the reference for everything
   live) and on the live tier (below). The repeats' darkening, grit and wobble come from each
   pass through the heads, the tape, the EQs and the tubes.
2. **The live tier**: the reduced medium (below), the electronics at draft, a chain's end in
   the app (`panel::CHAIN_ENDS`).
3. **VARISPEED**: the capstan's hysteresis synchronous motor on a variable-frequency supply
   (the studio's oscillator and power amplifier), the speed following the frequency through
   the rotor's inertia and its hunting (TM3's 2.5 Hz, Q 3): a quick turn glides the repeats'
   pitch and the tape overshoots and settles. Delay and pitch move together; the playback
   reads the tape where it is (the medium is in position, so the gap loss and the record
   aperture follow the speed by themselves).
4. **PING-PONG: the 351-2**, two tracks on one tape and one transport (shared wow and
   flutter), two record and two repro heads in one headblock, two channels of electronics;
   the console crosses the repeats (left repro into right record and back). Needs a stereo
   device at a chain's end (the app's chain end is mono today: `player::EndDevice` returns
   one channel) and two tracks in the medium (half-track heads: track width, the guard band's
   crosstalk later).
5. **BIAS as a performance knob**: under-biased grit to over-biased dark repeats. The live
   tier's tables over the bias amplitude too (2D), the bias from the circuit (TAPE_PLAN.md
   TM5's option B).
6. **7.5 ips** (the 351's speed switch: 266 ms, its EQ positions; the 7-1/2 board's CCIR /
   trimmer parts aren't modelled yet).
7. **The condition dials** (TAPE_PLAN.md, "turn it to 11"): wow and flutter, head wear,
   hiss, dropouts, as the tape insert will have them.

**Later ideas** (not ordered): a passive tone network in the send (studios patched an EQ into
the loop: a bass cut and a treble cut); the plate (or a spring) inside the loop (dub); two
machines at different speeds (a double slap; Abbey Road's ADT with one machine on
varispeed); the EP-2's loop with the erase head off (sound on sound).

**The reduced medium (the live tier's tape, refining "Reason 2" above).** The stream
(`TapeStream`, `tape_stream.rs`) records in 16 mm blocks, reads them a head distance later
and plays back by an FFT per block: all of that stays, exact. Only a block's recording is
replaced (the Preisach ensemble over every bias peak in every 0.5 um cell, then the demag
fixed point: 12 more passes), by, per layer l:
- **a table** T_l(H) of M_x and M_y against a constant deep-gap signal field, recorded by the
  real kernel at the aligned bias (the ensemble's anhysteretic remanence, orientations
  included; generated from `SCOTCH111@N`, never chosen);
- **an aperture** a_l(x) behind the gap: where in the trailing zone the layer's particles
  are last switched by the decaying bias, measured as the reference's small-signal step
  response; it carries the HF self-erasure and the record gap's losses. In time it is x / v,
  so it follows the speed;
- M_l(s) = T_l(sum_x a_l(x) H(t when s is x past the gap)) on coarse cells (a few um: 15
  kHz at 15 ips is 25 um), then the stream's playback as now;
- **demagnetization** as a linear correction measured against the reference at low level
  (its level dependence measured, not modelled, at first);
- **grain** as the stream's: the Poisson count's variance scaled to the coarse cells'
  volume, the packing field's AR(1) at the coarse step.

Measured against the reference stream on the same deep-gap field (sweeps at low level for
the linear part, the drums at 0 / +6 / +12 dB for the knee), then in the circuit against the
literal 351.

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

- ~~Single slap or repeats~~: REPEAT from the start (decided 2026-11-03), plus ping-pong
  and more ("The 351 echo").
- **Live is essential** (decided 2026-11-01). Route C with A live is being built
  (2026-11-03: the reduced medium, "Status"); B (the GPU) stays for later.
- **The live tier's accuracy:** how far from the print is acceptable (measured, then the
  user's call, as with the 670's draft)?
- **After D1:** the EP-2's dirt, the EchoSonic, or the Echorec next?
- **Where it goes** relative to the other parked tracks (it follows TM5 either way).

## Status (2026-11-03)

**The echo circuit:** `config/circuits/ampex_351_echo.yaml`, GENERATED by
`scripts/make_351_echo.py` from `ampex_351.yaml` and the alignment report: the factory
alignment as its settings, the console's SEND and REPEAT (feed resistors provisional), the
slap out wet only; `tests/test_351_echo.py`. Pre-flight clean. Re-aligned against today's
code first (`scripts/align_351.py`, 65 min on a shared CPU): the same settings to the last
digit.

**The reduced medium is built and measured** (`varimu/delay/reduced.py`, the reference;
circuitsim's `tape_stream.rs` `TapeReduction`, the port, within 1e-10 with flutter and grain:
`tests/test_tape_reduced.py`). Against the full stream on the same deep-gap field (the 351's
heads, Scotch 111, the aligned bias 2.94 mA rms; idealized NAB networks around it; 2 s of the
drums; `scripts/delay_live_study.py medium --demag`):

| drive | difference (re the reference's rms) | level | worst third-octave band, 31 Hz-16 kHz |
|---|---|---|---|
| 0 dB | -34.7 dB | -0.02 dB | -0.31 dB (16 kHz) |
| +6 dB | -28.7 dB | -0.05 dB | -0.39 dB |
| +12 dB | -25.2 dB | -0.05 dB | -0.43 dB (79 Hz) |

- Without the demagnetization correction: -22.2 / -20.1 / -17.6 dB, the reduced tape up to
  +5.7 dB bright at 16 kHz. The missing loss is linear (coherence 0.999+ across the band) and
  the same within ~0.2 dB on noise at -12 dB and on the drums at 0 dB, so D(k) is measured
  once, on noise, per reduction.
- The apertures: M_x's an S-curve from ~-50 to ~+90 us around the gap's centre, half its
  weight ~55 us (21 um at 15 ips) behind it, the deeper layers a little earlier; M_y's
  bipolar (Hy is odd about the gap), modelled as its own linear kernel times M_x's
  saturation.
- The aperture as an FIR on the samples (`aperture_fir`; the per-cell form costs ~8x more)
  adds ~0.2 dB of droop at 16 kHz (the cubic between samples).
- Python's reduced stream: 2.8x real time; the reference 36x (both one job alone).

**Generated, not chosen:** `scripts/tape_reduction.py` makes
`config/tape_reductions/ampex_351.json` from the circuit's own tape part (the builder's
medium, 8 demag iterations) at the alignment's bias: tables 7 s, D(k) 5.5 min. The file
records the medium it was made for; both builders refuse it for another.

**In the builders (both, IRs equal: `export_app_fixtures.py`, `agreement.rs`):** a tape
part's `reduction: NAME`; in an events build (the live qualities) the tape plays it at its
bias and cell length, the sections at its bias substeps run at the sample rate, and a
control's `events:` value is its setting there (the 351's `oscillator: events: 0`).
Production builds the literal machine as before; every other circuit's IR unchanged.

**In the app:** `ampex_351_echo` is a device (SEND, REPEAT) and a chain's end
(`panel::CHAIN_ENDS`); `live.rs` turns the events build on for a file whose tape names a
reduction. Live, the oscillator's passive network (1T5, the erase head, the grid networks,
the bias feed) goes with its tubes (the echo file puts it under the `oscillator` switch:
with the tubes out it reaches the head only through ~31 pF); production keeps every part.
The reduced tape records and finishes its blocks on a thread of its own
(`tape_stream::ReducedWorker`, the full medium's per-block finishing factored into
`Finisher`; the full medium bit-identical, `tests/test_tape_stream.py`).

**Real-time load** (`examples/load_profile.rs --device ampex_351_echo --quality draft-1x`,
the drums, 38.8 s, blocks of 512 at 48 kHz, one job alone):

| step | mean | median | p95 | worst block |
|---|---|---|---|---|
| first try (the app played the literal tape: the events build was for thyratrons only) | >20x | | | |
| the reduced tape, recorded inline | 1.46 | 0.96 | 3.06 | 4.52 |
| the oscillator's network out live | 1.39 | 0.85 | 3.13 | 4.67 |
| the reduced tape on its own thread | 0.86 | 0.82 | 1.17 | 1.78 |
| the circuit's noise off (as a chain's end plays: `--no-noise`) | **0.52** | 0.44 | 0.97 | 2.14 |

- 3.1 Newton iterations and 7 device evaluations per sample: the cost is the linear part.
- The remaining spikes come in pairs ~4 blocks apart (the tape's 16 mm block, 42 ms): the
  worker's 64k-point playback FFTs (the 7 mm pole contour's reach at 2 um cells) beside the
  circuit's thread, and loud transients (5-6 iterations a sample). Levers if they're heard:
  coarser cells or a shorter contour FFT in the reduced tape, the circuit split (the record
  side must stay in the first partition with the input; the repro side on a second thread
  measured worse, 3.3x).

**Live against the print** (`scripts/print_351_echo.py` with and without `--live`: the drums,
4 s plus 2.5 s of tail, SEND 1, the circuit's noise on; the print at production, 4 at once,
~300x real time each; live at Python's draft, 2.2x; audio in `reports/delay/audio/`). The slap
lands at 133.08 ms (head distance over speed: 133.33). Waveforms differ by -5 to -7 dB (the
print's free oscillator and its own noise draw), so the measures are levels, bands and the
repeats' decay:

| REPEAT | level, live re print | worst third-octave band, 40 Hz-16 kHz | repeats (133 ms windows after the input, print / live) |
|---|---|---|---|
| 0 | +0.12 dB | +0.41 dB (79 Hz) | |
| 0.35 | +0.13 dB | -0.61 dB (16 kHz) | -37, -44, -51, -57, -63 / -36, -43, -50, -56, -62 dBFS |
| 0.6 | +0.19 dB | -1.21 dB (16 kHz) | -26, -28, -30, -32, -34 / -26, -28, -29, -31, -33 dBFS |
| 0.8 (past unity) | +1.75 dB | +2.80 dB (5 kHz) | holds at -11 / -9 dBFS (saturated) |

In the runaway the knee's small differences compound pass after pass: the live tier settles
~2 dB hotter and brighter.

**VARISPEED built (2026-11-03; the user heard the slap and asked to continue):**
- A tape part's `supply: NODE` and `supply_nominal_hz` (both builders; IR `Tape.supply`,
  `TapeMedium.varispeed`): the capstan's hysteresis synchronous motor on a supply whose
  frequency is the node's voltage (1 V = 1 Hz), the rotor following it as an all-pole
  resonator at the transport's hunting (2.5 Hz, Q 3), unity at DC, a sample late. Every
  position integrates its factor (the delay; the repeats bend while it moves), the EMF goes
  with it, and the reduced tape's apertures scale as 1 / ratio per block (positions behind
  the gap). Without a supply every path is bit-identical (`tests/test_tape_stream.py`).
- The Python reference (`tape_machine.TapeStream`, `push_many(hs, supply_hz)`; the spec's
  `varispeed_nominal_hz`) and circuitsim's port agree within 1e-9 (full medium) and 1e-10
  (reduced) with the supply stepping and gliding (`tests/test_tape_varispeed.py`, which also
  checks delay x speed constant at 50 / 60 / 72 Hz). `tape_stream_run(..., supply_hz=)`.
- The echo: `capstan_hz` (VARISPEED, 40-80 Hz, provisional: the studio oscillator's range)
  drives `VCAP` onto `cap_hz`, the motor synchronous at `mains_hz`; on the app's panel.
- Heard as the app plays it: `scripts/varispeed_demo.py` (the live tier streamed block by
  block, the knob turned between blocks: glide 60 -> 45 -> 75 -> 60 Hz, a jump to 50 Hz, a
  0.8 Hz wobble) -> `reports/delay/audio/Dry_Guitar_varispeed_*.wav`. Steady delays from a
  click train: 133.8 / 178.3 / 160.4 / 107.1 ms at 60 / 45 / 50 / 75 Hz (133.3 x 60 / f:
  133.3 / 177.8 / 160.0 / 106.7; the rest is the electronics' group delay).
- Load unchanged: 0.49x real time at draft-1x (`--no-noise`).

**PING-PONG built (2026-11-03): the 351-2** (`config/circuits/ampex_351_2_echo.yaml`, GENERATED
by `make_351_echo.py` beside the mono echo): the echo's two channels (the right's parts and
nodes `_r`; shared controls and values), two-track heads (1.905 mm, NAB two-track,
provisional; the repro head scaled to keep the full-track output, so the alignment carries
over; track width left out of a reduction's medium keys: the 351 and the 351-2 share
`ampex_351.json`), one capstan supply in a section of its own, the console crossed (SEND
into the left; each return into the other side's record input, REPEAT ganged; the right's
send resistor returned to ground, or its bus picked the crossed feed up 9.6 dB hotter and the
bounces grew). A click: left 134 / 400 / 667 ms, right 267 / 534 / 800 ms, -2.7 dB a bounce at
REPEAT 0.5, holding at 0.7 (the mono echo's unity). `print_351_echo.py --pingpong [--live]`
writes stereo files (`reports/delay/audio/Dry_Guitar_351pingpong_rep*_live*.wav`).
- **A stereo chain's end** (varimu-app): a circuit with an `out_r` probe plays left and right
  apart (`live.rs` `Live::right`, `player.rs` `Tail`, `Emitter::emit`), the dry in both; a
  take keeps the mid. The app's `ampex_351_2_echo` device and chain end.
- **The medium as a partition cut** (circuitsim `partition.rs`, `stream.rs`): a tape whose
  record head is in another single-rate part senses it a sample late (the literal bias's
  remote sense, generalized: single-rate parts, the first partition too, publish their
  senses). The mono echo cut there matches its one solve at -67.9 dB after the one-sample
  shift (REPEAT 0; each repeat crosses again, a sample more).
- **Hold, not extrapolate, across these cuts.** Extrapolated, the crossed slap through each
  part's input bus kept the record side's Newton from contracting: 13.6 iterations and 5.5
  factorizations a sample (1.8x real time); held, 3.3 and 0.06. The 351-2's device:
  `coupling: hold`, four parts (both record sides with the input | left tape, repro, output |
  right | the supplies and the capstan): 0.54x real time, p95 1.35 (more spikes than the mono
  echo's 0.50 / 0.88: four threads spinning). Two machines on one thread: 1.31x.

**DRIVE built (2026-11-03; the user's choices, asked after hearing it: the 7.5 ips switch for
delay range; DRIVE, BIAS and the condition dials for saturation, "normally tape should be
subtle but this is an effect, so we can crank up the dirt").** A console line amplifier
ahead of SEND in both echo files (the left channel's in the 351-2): a 250k audio-taper DRIVE
pot, a 12AX7 half (100k plate, 1.5k cathode unbypassed), a 33k / 100k pad, a 12AU7 cathode
follower biased to ~+100 V into the send pot, on an ideal 250 V supply (all provisional: a
generic 1950s console). Its own audio-rate section; the record side shares only the send
pot's wiper. Measured at 1 kHz: 0 dB at 0.44 (the default: the echo as it was), +2.6 at 0.5,
+6.8 at 0.6, +12.9 at 0.75, +22.6 at 1 (the tape then ~+19 dB over its operating level).
- The guitar at REPEAT 0.5 (`print_351_echo.py --live --drive D`): +12.9 dB in gives the slap
  +7.5 dB (5.4 dB of compression, crest 9.4 -> 8.2 dB); +22.6 dB in gives +9.1 dB (13.5 dB
  of compression, crest 7.8 dB). `reports/delay/audio/Dry Guitar_351echo_rep0.5_drive*_live*.wav`.
- The live tape driven hard (the reduction's tables widened to +-200 kA/m, 481 points;
  `ampex_351.json` regenerated): against the full stream -21.9 / -17.2 dB at +18 / +24 dB over
  the operating level, level +0.02 / +0.28 dB, worst band -0.48 / +1.1 dB.
- Load: at full DRIVE one thread ran 0.85x (p95 1.95, a factorization a sample in the
  saturating record side); the mono echo now plays cut at the medium with hold coupling:
  0.55x (p95 1.25) at full DRIVE, 0.50x (p95 1.35) at the default.

**7.5 ips built (2026-11-03; the user's pick for more delay range):**
- **Sourced** (sch p95, Table 1 NAB; man p83-84): on the 7-1/2 / 15 ips board (30960-01-03)
  EQUAL SWITCH 4S2a puts the record HF trimmer 1C46 (550-1600 pF) across 1R17 in place of 1C7;
  the playback EQ is the same 50 us at both speeds (2R30, LOW's rheostat, is "*" on this board,
  a jumper keeps 2R31 in: the manual's "7-1/2 ips NAB: the same as 15"); 4S2b switches only the
  CCIR network. The bias is set once, "at a specific wavelength" (500 Hz at 7-1/2 = 1 kHz at 15),
  so the 15 ips alignment's carries over; so do the levels.
- **In `ampex_351.yaml`:** `speed` (the transport's switch: the capstan motor's other winding;
  each speed its own tape part in a switch, TP / TP_LO, the medium's cells per bias wavelength:
  0.25 um at 7-1/2) and `equalization` (4S2a as contacts always in the circuit, so a flip is a
  value change; set with the speed, or against it). The 351's default IR moves only by the two
  contacts.
- **Aligned** (`varimu.measure.tape_align.record_eq_lo`, step 3b; `scripts/align_351.py --low`
  merges it into the report): 1C46 at its end, 1600 pF, and the response still short: -0.6 /
  -1.2 / -2.6 / -4.7 / -7.3 dB at 5 / 7.5 / 10 / 12.5 / 15 kHz re 500 Hz (the spec: +-2 dB to
  10 kHz, +-4 to 15 kHz, man p10: 0.6 and 3.3 dB short). The provisional heads (the Ampex 300's
  51 um record gap, the contour calibrated at 15 ips) lose more at half speed than the 351's;
  changing them moves the 15 ips alignment: the user's call (TAPE_PLAN.md "Gaps").
- **The live tier:** a reduction per speed (`ampex_351_lo.json`; a switch's sub-parts all
  expand, so both files must exist). Against the full stream at 7-1/2 ips (drums, `--speed-ips
  7.5`): -34.2 / -28.6 / -24.9 dB at 0 / +6 / +12 dB, every band within 0.5 dB. The 15 ips
  reduction played at 7-1/2 (its apertures scaled by the speeds' ratio: in space they agree
  within 0.6 um): -32.8 dB and +2 dB at 16 kHz, -0.5 to -1 dB at 8-12.7 kHz, from D(k)
  (measured on noise to 20 kHz, 19 um at 15 ips, held below) and the tables (1.9%: the bias
  wavelength). So per speed, not interpolated by speed; D(k)'s band widened instead (BIAS,
  below), which also covers VARISPEED's slowest tape.
- **Heard:** a click lands at 134.4 / 267.8 ms (head distance over speed: 133.3 / 266.7);
  `print_351_echo.py --ips 7.5 [--live]` -> `reports/delay/audio/*_7.5ips*.wav`.
- **Load** (`load_profile --device ampex_351_echo --quality draft-1x --no-noise`, the drums,
  back to back): 7-1/2 ips 0.28x real time (median 0.23, p95 0.61, worst 1.55; 24 of 3637
  blocks over 1.0) against 15 ips 0.47x (0.25, 1.28, 2.42; 806 over): a 16 mm block lasts
  twice as long, so the worker's playback FFTs (the 15 ips spikes) come half as often.
- **A bug fixed (circuitsim `Mna::media_senses`):** a run that computes only its probes (DK)
  didn't compute the tape's capstan supply node, and the medium read its stale value: the mono
  echo's tape ran at a third of its speed (the slap at 399 ms) since VARISPEED. The ping-pong
  probes `cap_hz` and was right. Results redone: the load (the same: 0.47x), DRIVE (+12.9 dB in:
  the slap +8.4 dB, 4.5 dB of compression; +22.6 dB: +10.2 dB, 12.4 dB), the audio. Guarded by
  `tests/test_351_echo.py::test_live_slap_lands_a_head_distance_later`.

- **Live against the print at 7-1/2 ips** (`print_351_echo.py --ips 7.5 [--live]`, the drums,
  4 s plus 2.5 s; the print at production, ~600x real time on a shared CPU): level +0.21 /
  +0.22 / +0.28 dB at REPEAT 0 / 0.35 / 0.6, the worst third-octave band 16 kHz (-1.6 to -1.8
  dB), the repeats within 1 dB (print -26 -34 -41 -48 -54, live -26 -33 -40 -47 -54 dBFS at
  0.35).

**BIAS built (2026-11-03; under-biased grit to over-biased dark, both tiers on the same
control):**
- **One control, BIAS ADJUST** (`bias_adjust_f`, 5C13, 15-130 pF). The print's literal
  oscillator follows it by itself; live, the tape part's `reduction_bias: bias_adjust_f` (both
  builders) reads the control through the reduction's **bias map**: 5C13 against the record
  head's bias current on the literal machine (the alignment's sweep, 15-78 pF, and three runs
  to 130 pF by `tape_reduction.py`): 1.44 mA at 15 pF (1 kHz 12 dB down at -10 dB: under-biased)
  to 10.7 mA at 130 pF; aligned 2.95 mA at 31 pF; ~0.096 mA per pF.
- **The reduction over the bias** (`varimu.delay.reduced.BiasReductions`, circuitsim's
  `TapeReduction::points` / `ReductionPoint`, IR `TapeReductionPoint`): tables, apertures
  (trimmed to one span) and D(k) at 10 biases 2^(1/3) apart over the map, interpolated in
  ln(bias), held past the ends. D(k) is per point: it depends on the bias (at 50 um -1.35 dB
  at 1.44 mA, -3.44 dB aligned: a shallower recording loses less to its own field), and each
  block's flux slope takes its own bias's. D(k) is now measured on noise to 40 kHz (was 20:
  the top octave was held at 7-1/2 ips and under VARISPEED).
- **A turn in place:** a reduced medium differing only in its bias updates the stream
  (`TapeStream::set_bias`, media.rs `update`): blocks recorded from then on take the new
  bias, the tape already recorded stays (no restart). The port against the reference with the
  bias turned twice mid-run: within 1e-10 (`tests/test_tape_reduced.py`); in the echo's
  stream, a turn between a click and its slap keeps the slap
  (`test_351_echo.py::test_a_bias_turn_keeps_the_tape`).
- **The panel** (varimu-app): BIAS shows in pF (`Knob::display_scale`: a range in a tiny SI
  unit gets a prefix; in farads the slider's 3 decimals rounded it to 0 and it wouldn't move),
  and every two-position switch (choices [0, 1]: SPEED, EQUALIZATION, the V76's treble cut,
  the U47's pattern) is a checkbox.
- **Validated before building** (`delay_live_study.py medium --demag --bias-ma-rms B`, each
  bias's own reduction against the full stream, drums at 0 / +6 / +12 dB):

  | bias | difference | level | bands |
  |---|---|---|---|
  | 1.44 mA (15 pF, under) | -22.2 / -18.3 / -15.2 dB | -0.25 dB | within 0.9 dB (1-2.5 kHz low, +0.7 at 6.3 kHz) |
  | 2.94 mA (aligned) | -34.7 / -28.7 / -25.2 dB | -0.02 dB | within 0.43 dB |
  | 7.0 mA (78 pF, over) | -19.6 / -20.8 / -22.1 dB | +0.2 dB | within 0.3 dB, flat: the residual is phase (the over-biased tape records farther behind the gap) |

  Under-bias the recording depends more on each cell's history than one aperture and table
  hold.
- **Generated** (`scripts/tape_reduction.py`, `[--set speed=0 --name ampex_351_lo]`): the
  bias map's three literal runs 11 min; per speed the 10 points' tables 3-7 min and their
  D(k)s (each a full-stream reference, 5 at a time) ~50 min at 15 ips, ~115 min at 7-1/2: the
  references slow down with the bias (its recording zone widens). The interpolation between
  points against a reduction made there directly: the small-signal slope within +-0.4 dB per
  layer (one layer +1.5 dB between the lowest two points, where the level moves fastest),
  saturation within 0.02 dB, apertures within 1 us (one deep layer -4.7 us at 70 kA/m).
- **Heard** (`print_351_echo.py --bias-pf C --live`, the guitar at REPEAT 0.5 ->
  `reports/delay/audio/Dry Guitar_351echo_rep0.5_bias*_live.wav`), against the aligned 31 pF:
  15 pF -7.2 dB (250 Hz / 1 / 4 / 8 / 12 kHz: -8.9 / -9.9 / -11.1 / -5.3 / -4.5: relatively
  bright on top, as an under-biased tape is), 78 pF -6.3 dB (-8.2 / -9.1 / -10.6 / -9.1 /
  -6.9), 130 pF -10.4 dB (-12.7 / -13.5 / -16.4 / -12.4 / -8.0); the repeats compound it. The
  output peaks at the aligned bias (the alignment's definition), so either way the slap drops:
  DRIVE or SEND makes it up.
- Load unchanged: 0.49x real time (p95 1.33) at 31 pF and at 15 pF. The fixtures of the
  echo's events builds embed the whole reduction (13-15 MB per file): trim before a commit.
- **Live against the print at the bias's ends** (`print_351_echo.py --bias-pf C [--live]`,
  the drums at REPEAT 0.35; the prints 70x / 136x real time alone): 15 pF level +0.12 dB, the
  worst band +1.17 dB (157 Hz), the repeats within 1 dB (print -47 -65 -69, live -46 -64 -69
  dBFS); 78 pF level +0.34 dB, the worst band -0.94 dB (16 kHz), the repeats within 1 dB (-43
  -56 -66 / -42 -55 -66).

**Proposed: the condition dials** (the user's list; each a physical condition, clean by
default, "turn it to 11" at the end; none built):
- **TRANSPORT WEAR** (wow and flutter): one knob scaling the transport's mechanisms from a
  new machine (the spec's 0.11 / 0.14%) to a worn one, ~30x: the capstan's runout (a worn
  shaft), the idler (a hardened, out-of-round pinch roller), the reel (warped, a weak tension
  motor), the motor's hunting (worn bearings), scrape (glazed heads). Their amplitudes are
  the medium's `flutter` / `flutter_noise`: a set in place, as the bias's.
- **DIRTY HEADS** (spacing): oxide shed onto the repro head lifts the tape, 0.5 um to ~10 um
  (54.6 dB per wavelength: at 10 um 15 kHz at 15 ips loses ~22 dB). The playback is the
  stream's own (exact, in place); the record head's spacing would need reductions per
  spacing (a later grid).
- **TAPE GRADE** (hiss): a cheaper, coarser coating, the grain's particle volume up to ~100x
  (+20 dB of hiss) and its packing variation (modulation noise). The chain end plays with the
  circuit's noise off: the tape's grain needs its own switch.
- **SHED OXIDE** (dropouts): seeded bare or lifted spots along the tape (a density per metre,
  each a few mm), the recorded magnetization removed or the spacing lifted there.
- Later: print-through, azimuth (HF loss, the 351-2's interchannel phase), magnetized heads
  (a DC field in the record head: hiss and even harmonics).

**Next (the user's order):** the condition dials (above: which, and their ranges). Then: the user listens: the literal prints (`scripts/print_351_echo.py`, REPEAT 0 / 0.35 /
0.6 / 0.8, the last past unity) against the live tier's (`--live`), and plays it at a chain's
end. Ping-pong's literal print isn't made (two literal machines: ~600x real time); its parts are
the echo's, each checked.
