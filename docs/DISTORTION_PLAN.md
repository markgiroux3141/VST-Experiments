# Distortion: warm, gritty tube overdrive from physics

Drafted 2026-11-04 from a brainstorm with the user. **Nothing in it is built; parked until
the user picks it up.** The user asked for a distortion that is like the plate and the echo
(a device after the instrument), with warm tubes, grit, an analog sound, the physics behind
it, and lots of dials. The order below is a recommendation; the choices are the user's (Open
decisions).

**Where it runs (the user's, 2026-11-04):** if it is costly, it goes on **rendered audio**:
a session insert printed offline (SESSION_FX_PLAN.md F1-F3), so it never competes with a
synth or another instrument for CPU. Prints run at **production**, the very-high-quality
setting. Live play is only for auditioning a panel (F3's one live device) at a draft
quality. A chain end (`panel::CHAIN_ENDS`, like the plate) is optional, if a cheap variant
fits beside an instrument.

**Usable today:** the 5E3 (`fender_5e3`) is already in the session's insert menu. A take
can be printed through it now. Its input is guitar level (its `full_scale`: 0 dBFS = 1 V
peak in), so a line-level track trimmed to -18 dBFS rms drives it moderately. At production
its out is the P12R's sound pressure (C3's readout).

## To pick this up

1. Read "Ground rules" and "Open decisions", and ask the user the open questions.
2. Check what changed since 2026-11-04: SESSION_FX_PLAN.md (inserts, prints), the BJT model
   (shared with the drums and the mics: transistor fuzzes open up once it exists),
   COMPONENT_EDITOR_PLAN.md (C2's transformer designer, for the iron), and SYNTH_MASTER_PLAN.md
   (a `master` quality above production, if built).
3. Start at O1.

## Ground rules

CLAUDE.md's hard rules hold. For this device in particular:

- **Every dial is a part value or a switch a real unit could have:** a pot, a resistor, a
  capacitor, a tube type, a supply voltage, a transformer, a bias setting. No saturation
  curves, "drive" multipliers or blend-of-harmonics knobs. Distortion comes from the
  tubes, the iron and the supply in one coupled netlist.
- **Realistic first, then bend** (the user's rule, memory "realistic first, then bend"):
  each dial's default and its normal range are real values. A range that goes past what a
  real part could do is allowed when marked out of rating, as tube_synth's HEATER is below
  0.9.
- **Condition dials** (the user's, memory "tape condition dials"): faults and wear (a
  leaky coupling cap, a gassy tube, worn emission, a variac) go from clean to "turn it to
  11", each one a physical condition, with the default realistic.
- **Loudness lies.** Every A/B of settings is LUFS-matched. Distortion is louder as it
  compresses, so an unmatched comparison always prefers more.
- New physics (a gassy tube's ions, a torn cone) is an options-before-model-changes step:
  sourced options and numbers to the user before building.

## What exists to build on

| Piece | Where | What it gives distortion |
|---|---|---|
| Triodes / pentodes with grid current | `varimu/devices/`, circuitsim `devices/` | grid conduction, blocking distortion, bias shift on transients |
| Heated cathodes (B6) | `heaters` block, `cathode.py` / `cathode.rs` | a Richardson emission ceiling: a cold heater sputters for real; a `tap: KEY` makes it a knob |
| Supplies | 5Y3GT@1, GZ34@1, 6X4@1, si_rectifier, selenium, `mains` parts | sag, ripple, rectifier character; B5's mains wander |
| JA transformer cores | `varimu/devices/core.py`, `config/magnetics.yaml` | iron saturation and hysteresis, level-dependent bass |
| The transformer designer (C2) | `crates/varimu-components`, the Components view | an output or interstage transformer designed from core and windings, deliberately undersized |
| Tubes | 12AX7, 12AU7, 12AY7, 12BH7, 6V6GT, EL34T, EF804S (an EF86-type pentode), 6AL5, 884 / 2D21 | the stages below (no EL84, KT66 or 6L6 yet) |
| The speaker | P12R@1, the `speaker` macro | cone and cabinet as the acoustic low-pass that tames fizz |
| The 5E3 and its profile | `fender_5e3.yaml`, `varimu/measure/amp_suite.py` | a working amp, a measurement suite to reuse (gain, response, THD / power, sag, aliasing per quality) |
| Inserts and prints | SESSION_FX_PLAN.md F1-F3, `print.rs` | printing, caching by sha256, auditioning, ⤓ Render |
| Not available | the BJT model | Fuzz Face, Tone Bender and other transistor fuzzes wait for it |

## The kinds of grit (the physics)

Each sounds different and gets its own dials:

1. **Triode curvature.** Soft, warm; a single-ended stage is mostly even harmonics.
2. **Grid conduction and blocking.** Dynamic: a hard note charges the coupling capacitor
   through the grid, the bias shifts, then recovers through the grid leak: bloom, then a
   farty gating. Set by the coupling capacitor and the grid leak.
3. **Cutoff and crossover.** A push-pull stage biased cold: a crossover notch, sputter, a
   decay that gates off.
4. **Emission limit and starved plates.** Low B+ or a cold heater: spitty, broken, level
   dependent.
5. **Iron saturation and hysteresis.** Bass only, level dependent, a thick low end; the
   core's loop adds odd harmonics that fall with level (as mumetall's Rayleigh region).
6. **Supply sag and ripple.** Compression, breathing, hum modulating the signal.
7. **Rectifying the signal.** A full-wave tube rectifier (a 6AL5 on a centre-tapped
   transformer): octave-up fuzz, an Octavia's principle without transistors.
8. **Gas-tube thresholds.** The 884 as a flip-flop: a sub-octave or a stutter locked to
   the input (HYBRID_PHYSICS_PLAN.md's event kernels).
9. **Contacts and carbon.** Granular grit, noise-modulated: a carbon microphone into a
   telephone line, VICTORIAN_SYNTH_PLAN.md's carbon relay.
10. **Mechanical breakup.** The cone breaking up, or a torn or slashed cone rattling (Link
    Wray, the Kinks): a rattle contact as a hybrid exception.

## Candidate devices

### Real units (realistic first)

- **Fender 5F1 Champ** (recommended first): one 12AX7, one single-ended 6V6GT, a 5Y3GT,
  every part already fitted. Cranking it is the whole sound, and it is about half the 5E3's
  tubes. Its schematic is widely circulated (source to be found and filed in
  `data/schematics/fender_5f1/`).
- **The 5E3** (exists): as an insert today; a line-level input pad and a load-box out are
  the only additions.
- **Vox AC30 / Marshall JTM45:** push-pull with cathode bias, so crossover and sag on top.
  Need EL84 / KT66 device fits.
- **Overloaded studio electronics.** The Revolution guitar went straight into an
  overloaded Abbey Road desk; Grady Martin's fuzz on Marty Robbins' "Don't Worry" (1961) is
  told as a failing console channel. Faults as physics. Their schematics are to be found;
  the stories to be checked against sources before they are written as data.
- **The V76 and the 351 driven hot** (exist): the 351 already has DRIVE (0 to +22.6 dB).

### Invented: the grit box (the many-dials device)

A studio tube distortion unit of our own, in the spirit of the Thermionic Culture Vulture
(its schematic isn't public, so we design our own, as the plate's drive amplifiers were).
It starts from the Champ's topology and grows by modules. Signal flow:

`in` -> input transformer / pad -> front stage (triode or pentode) -> coupling network ->
interstage (RC or iron) -> power stage (single-ended or push-pull) -> output transformer ->
load (resistive load box, line out; or the speaker) -> tone -> `out`, with its own supply
(mains -> variac -> power transformer -> rectifier -> reservoir -> choke -> rails).

| Group | Dial | The part behind it |
|---|---|---|
| Input | INPUT | input transformer ratio or a pad; the transformer saturates at bass when hit |
| | DRIVE | a pot as the first grid's divider |
| Front stage | TUBE | 12AX7 / 12AU7 / 12AY7 / EF804S: a device swap (a switch between parts) |
| | TRIODE / PENTODE | the pentode's screen strapped to the plate or not |
| | BIAS | the cathode resistor: hot (soft) to cold (cutoff, sputter) |
| | BYPASS | the cathode bypass capacitor: bass gain, and the bias drifting on transients |
| | SCREEN | the screen supply's dropping resistor |
| Coupling | COUPLING x GRID LEAK | the blocking recovery: tight to farty |
| Iron | INTERSTAGE | an interstage transformer (core material, size: from C2) or RC |
| | OUTPUT IRON | the output transformer's design (C2); undersized saturates |
| | LOAD | matched, mismatched, open-ish (the reflected load moves the power stage's line) |
| Power | VARIAC | the mains voltage, 90-130 V: B+ and heaters together (the "brown sound" trick) |
| | RECTIFIER | 5Y3GT / GZ34 / silicon / selenium |
| | RESERVOIR | the reservoir capacitor: sag and hum (as tube_synth's RESERVOIR) |
| | HEATER | the heater ratio (B6's `tap`), out of rating below 0.9 |
| Power stage | CLASS | the power pair's fixed-bias pot: A -> AB -> B (crossover) |
| | FEEDBACK / PRESENCE | the negative feedback resistor and its presence capacitor |
| Condition | LEAKY CAP | a leakage resistance across the coupling capacitor: DC creeping onto a grid |
| | GASSY | a gassy power tube's reverse grid current (new physics: the thyratron's ion state is a candidate) |
| | WORN | emission scale per tube (as the 670's `emission_scale`) |
| Extras | OCTAVE | a 6AL5 full-wave stage on a centre-tapped transformer |
| | SUB | an 884 divider (hybrid physics) |
| | SPEAKER | the P12R and cabinet as the output instead of the load box; a torn cone later |
| Out | TONE | a passive tone stack |
| | OUTPUT | the output level pot |
| | MIX | the insert's wet / dry (`Slot::wet`) |

Every part needs a `source`. Most values will be `provisional: model knowledge (...)`
until a real unit's schematic anchors them.

## Measurement: a distortion profile

Reuse `amp_suite.py` where it fits; add what distortion needs:

- THD and the harmonic spectrum (even / odd) against level, per setting of the main dials;
- intermodulation (two tones);
- dynamics: blocking (the bias shift after a burst and its recovery time), sag (the
  output's droop and recovery), gating (a decay's cliff with CLASS cold);
- aliasing per quality (as the 5E3's: draft-1x aliased at -8 dB re the harmonics, draft-2x
  was chosen for play). The production print's internal rate must be measured hard: at
  96 kHz x 2 the harmonics of a cranked stage reach well past 96 kHz. If production
  aliases audibly, the device gets more oversampling at production, or waits for the
  `master` quality (SYNTH_MASTER_PLAN.md).
- plausibility: idle stable, no oscillation at any dial corner (the corner sweep's checks).

## Costs and risks

- **Aliasing** is the main risk (above). Print at production; audition at draft-2x.
- **CPU** matters only for auditioning, since prints are offline. The speaker readout
  (~80 states) took the 5E3's draft-2x from 0.48x to 1.61x real time: the live audition
  uses the load box, and the speaker is print-only unless measured to fit.
- **JA cores live:** the draft runs the cores' linear limit, so the iron's saturation is
  heard only in prints (or in a draft that keeps JA, measured first).
- **Input level:** tracks are line level, amps expect guitar level. A pad or an input
  transformer handles it physically. The insert's trim is set once from the take (-18
  dBFS, SESSION_FX_PLAN.md's decision); INPUT and DRIVE then set how hard it is hit.
- **Switches that restart:** a TUBE or RECTIFIER swap changes the topology, so a live
  audition restarts its stream (as the 670's structural switches). Fine for a print.
- **Many dials, many corners:** a cranked power stage on a high VARIAC with a mismatched
  LOAD may oscillate. Each module gets the corner sweep before the next is added.

## Proposed milestones

- **O1: the Champ as an insert.** `config/circuits/fender_5f1.yaml` from its schematic
  (sources filed), a line-level input pad, a load box and line out; idle vs the published
  voltages (+-20%, as the 5E3's test); its profile; a `panel::Device`; printed through a
  session insert at production; aliasing measured per quality. Done when a take prints
  through it and the profile's numbers are within the sources.
- **O2: the cheap dials on the Champ.** VARIAC, RECTIFIER, RESERVOIR, HEATER. (tube_synth
  dropped its rectifier switch because it only retuned an oscillator; in an amp it changes
  sag and is kept.) Measured: sag and THD vs each.
- **O3: the grit box's front stage.** TUBE, TRIODE / PENTODE, BIAS, BYPASS, SCREEN,
  COUPLING x GRID LEAK; the blocking measurement.
- **O4: the power stage.** A push-pull 6V6GT pair beside the single-ended one; CLASS;
  FEEDBACK / PRESENCE; crossover measured.
- **O5: the iron.** INPUT, INTERSTAGE and OUTPUT transformers designed in the Components
  view (C2), LOAD.
- **O6: condition.** LEAKY CAP and WORN (part values, no new physics); GASSY (options to
  the user first).
- **O7: the speaker.** The P12R and cabinet as an output (print-only unless measured to
  fit live); the torn cone as a hybrid exception (options first).
- **O8: extras.** OCTAVE, SUB, carbon grit.
- **Later:** the AC30 / JTM45 (EL84 / KT66 fits), the console-fault units, transistor
  fuzzes after the BJT model.

## Open decisions (the user's)

1. **One box with many dials, or a rack of historical units** (the Champ, the AC30, the
   console channel) each with its real panel? The plan above does both: the Champ first,
   the grit box grown from it.
2. **The default output:** the load box's line out (cheaper, brighter) or the speaker's
   sound pressure (darker, costlier)?
3. **A live chain end at all,** or prints and auditions only?
4. **Where it goes in the order** among the paused tracks (the Rhodes RH4, the condition
   dials of the echo, C3, the drums' D2b).

## Status (2026-11-04)

Nothing built. The 5E3 can already be printed as an insert (above).
