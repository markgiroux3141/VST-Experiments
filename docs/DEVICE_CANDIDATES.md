# Device candidates: what to build after the 670 and the EQP-1A

Brainstormed with the user on 2026-10-28. **Nothing here is built yet.** This lists
popular audio devices that suit the app, what each needs that we don't have, and how
well its schematic can be sourced. The first section records the user's picks. Each
device that gets started becomes a milestone in
[DEVICE_BUILDER_PLAN.md](DEVICE_BUILDER_PLAN.md) (like B2, the EQP-1A), with its sources
in `data/schematics/<device>/`.

Ground rules carry over unchanged (CLAUDE.md "Hard rules"): every value has a `source`,
the genome is physical only, one coupled simulation, two implementations per device
model, everything seeded.

Tube complements and other facts below are from model knowledge or web listings unless
a source is given. Confirm each on the schematic before it goes into a circuit file.

## Decisions (2026-10-28, the user's)

1. **First up: the Telefunken V76 and guitar amps.** The user wants to hear how a guitar
   amp's distortion comes out and how analog it sounds. The LA-2A, which was the
   suggested next device, drops behind them.
2. **Order between the two (proposed, the user to confirm):** a guitar amp first, the
   Fender 5E3 Deluxe, because its sources are at hand (annotated schematics, well-known
   values); the V76 second, because its schematic still has to be found (see below).
3. Everything else on this list stays as candidates, in the order of "The rest of the
   list".
4. **Started 2026-10-29 (the user's):** the 5E3 and the V76 are milestones B9 and B10 of
   [DEVICE_BUILDER_PLAN.md](DEVICE_BUILDER_PLAN.md), worked together with the component
   editor ([COMPONENT_EDITOR_PLAN.md](COMPONENT_EDITOR_PLAN.md)); the 5E3 first, the V76
   when its schematic is found.

## First: guitar amps

### Why they suit us

Overdrive in a tube amp comes from what this project already simulates as one coupled
circuit, so it is a strong test of "how analog does it sound":

- grid current charging the coupling capacitors (blocking distortion, bias shift on
  transients) - our triodes have grid current;
- rectifier and supply sag under load (the "one coupled simulation" rule pays off here);
- output transformer saturation and hysteresis at low frequencies (the JA cores);
- cathode bias shifting with signal level;
- push-pull output stage crossover and the phase inverter's imbalance;
- the output stage driving a reactive speaker load.

### Candidates

| Amp | Circuit | Tubes (to confirm) | New work | Sources |
|---|---|---|---|---|
| **Fender 5E3 Deluxe** (1955-60, proposed first) | Two channels, interactive volumes, one tone control, cathode-biased push-pull, no negative feedback | 12AY7, 12AX7 (phase inverter), 2x 6V6GT, 5Y3 rectifier | Fits for 12AY7, 6V6GT (pentode model), 5Y3 (vacuum diode); speaker load; guitar source | Excellent: annotated schematic and "how it works" (robrobinette.com); the lineup per Vintage Guitar. Wikipedia mentions 12AX7s and a GZ34 in some Deluxe, probably a later revision |
| **Marshall JTM45** | Fender Bassman-style, fixed bias, negative feedback | ECC83s, KT66 / 5881, GZ34 | KT66 fit; GZ34 exists | Very good: widely published |
| **Vox AC30** | Cathode-biased EL84s, no negative feedback, Top Boost tone stack | ECC83s, 4x EL84, GZ34 | EL84 fit | Very good |
| **Fender 5F6-A Bassman** | Long-tail phase inverter, tone stack, fixed bias | 12AY7, 12AX7, 5881 / 6L6, GZ34 / 5AR4 | 6L6 fit | Very good |

### What a guitar amp needs that we don't have

The 5E3's output transformer is the component editor's first designed component
(2026-10-29, the user's decision: [COMPONENT_EDITOR_PLAN.md](COMPONENT_EDITOR_PLAN.md), C2),
built alongside the 5E3 itself.

- **Tube fits** for the amp's tubes: preamp triodes (12AY7), output pentodes / beam
  tetrodes (6V6GT, EL84, KT66, 6L6) on the existing pentode model, rectifiers (5Y3) on
  the vacuum-diode model. Same procedure as the 670's tubes (`fit-devices`, datasheet
  curves with provenance sidecars).
- **A speaker load.** The speaker's electrical impedance as passive parts: voice-coil
  resistance and inductance plus the cone's resonance as a parallel RLC (Thiele-Small
  parameters from a speaker datasheet, e.g. the amp's original Jensen). That makes the
  output transformer see the real load, rising impedance at resonance and toward HF.
- **A guitar source.** A pickup is an inductive source (inductance, winding resistance,
  self-capacitance) plus cable capacitance, all physical and sourced from published
  pickup measurements. It shapes the amp's input like the real instrument does.
- **Pre-flight on new topologies.** Long-tail and cathodyne phase inverters and fixed-bias
  supplies are circuits nobody has tuned here; expect the DC operating point and
  oscillation work the 670 needed (capacitance on rectifier nodes, damping on
  transformer resonances).

### Open decisions (the user's, before the first render)

*Decided 2026-10-29:* a physical speaker model (option 3 below; the component editor's
C3) and DIs as a voltage at the input jack (DEVICE_BUILDER_PLAN.md, B9).

- **What we listen to.** The output transformer's secondary across the speaker load is
  the last electrical node. Heard raw, an overdriven amp is fizzy, because the speaker
  cone and cabinet are a steep acoustic low-pass. Options:
  1. listen to the load voltage only (honest, harsh);
  2. chain a measured cabinet impulse response after the circuit: a linear acoustic stage
     after the electrical boundary, like the tape question in FUTURE_DIRECTIONS;
  3. a physical cone and cabinet model (a project of its own).
- **How recorded DIs drive it.** A DI recorded on an interface's Hi-Z input already
  contains the pickup's response under that input's load. Feeding it through the pickup
  model counts the pickup twice; feeding it as an ideal voltage leaves the amp's input
  loading out. Also needs a level convention: the volts a pickup's peaks reach (per
  circuit, like `audio.full_scale_volts_peak`).
- **Aliasing.** A clipping amp makes harmonics far above 20 kHz. Measure aliasing at our
  internal rate (2x of 96 kHz in production, 96 kHz in the draft) before trusting the
  sound (memory: "accuracy means analog behaviour").

## Second: the Telefunken V76

A German broadcast tube microphone preamp, highly regarded for its character.

- **Circuit:** high gain with switchable gain steps and filters (per the front panel; to
  confirm on the schematic). Its predecessor, the V72, is two EF804S and fixed gain
  (34 dB).
- **Tubes:** three EF804S pentodes and one E83F per module, per listings and GroupDIY
  (to confirm). Both need pentode fits from Telefunken / Valvo datasheets. EF804S vs
  EF806S is said to be one tube with different pinouts; check pins against the
  schematic.
- **Transformers:** input and output transformers. Their data are probably unpublished;
  start from modern replacement transformers' datasheets where any exist, otherwise
  provisional genome parameters as for the 670.
- **Schematic: found 2026-10-29.** IRT's "Braunbuch-Beschreibung V 76" (1959, on the
  Wayback Machine) with drawing S 1176, all values printed:
  `data/schematics/telefunken_v76/README.md`. The notes below predate it. A first web
  search (2026-10-28) had turned up listings and forum threads but no drawing. Where to look next: Telefunken / IRT broadcast
  documentation, GroupDIY's V76 threads (a simplified two-tube variant was posted there,
  not the original), diyaudio. This is the gating item.
- **Fit with the app:** a preamp suits real-time play (live input), and the existing
  device set covers it apart from the two pentode fits.

## The rest of the list

Sorted by how much of the current engine each one reuses. Today's device library is all
tubes and rectifiers (`config/components/`: 12AX7, 12AU7, 12BH7, 6386, 6973, 5651, 6084,
EL34 triode-connected, 6X4, GZ34, selenium, silicon); no transistors, FETs, op-amps or
optical cells.

### Tier 1: tubes, transformers and passives only

| Device | What it is | New work | Schematic outlook |
|---|---|---|---|
| Teletronix LA-2A | Tube optical leveler | The T4B opto cell (an electroluminescent panel driving a CdS photoresistor with memory: two-stage release), a 6AQ5 fit; 12AX7 and 12BH7 exist | Excellent: manual schematic; replacement transformers with datasheets |
| Pultec MEQ-5 | Midrange sibling of the EQP-1A | Almost none | Good, same manual family |
| Universal Audio 175B / 176 | Variable-mu compressor | Little; the 176 may use the 6386 (confirm) | Good |
| Gates Sta-Level, Altec 436, RCA BA-6A | Broadcast variable-mu compressors | Remote-cutoff tube fits | Good: broadcast manuals |
| Telefunken V72 | The V76's predecessor | EF804S fit (shared with the V76) | Good |
| Universal Audio 610 | Console tube preamp | Tube fits | Good |
| Ampex 351 electronics | Tape machine preamp, used on its own for colour | Tube fits; a step toward FUTURE_DIRECTIONS' tape | Good |

### Tier 2: needs a BJT model (Gummel-Poon subset)

| Device | Notes |
|---|---|
| Neve 1073 | Discrete class-A preamp / EQ with Marinair / St Ives transformers; schematic widely circulated; Carnhill replacement transformers have datasheets |
| Neve 2254 / 33609 | Diode-bridge compressor; diodes exist |
| Fuzz Face, Tone Bender | Two germanium transistors: a small first test of the BJT model; temperature dependence ties into the thermal direction |
| API 550A / 2500 | The 2520 op-amp is discrete, so it can be built from transistors |

### Tier 3: needs JFETs, op-amps or IC VCAs

| Device | Notes |
|---|---|
| UREI 1176 (Rev A, Rev D/E/F) | JFET as a variable resistor; manuals and DIY clones document the revisions |
| Tube Screamer, Klon | Op-amp macro model |
| SSL bus compressor, dbx 160 | VCA chips are black boxes, a poor fit for "the genome is physical only"; low priority |

Mechanical devices (EMT 140 plate, spring reverbs, tape echo) belong to the "spatial
medium" idea in [FUTURE_DIRECTIONS.md](FUTURE_DIRECTIONS.md), not here.

## Mapping a schematic: what decides how hard a device is

1. **A schematic with printed values.** Vintage broadcast and studio gear shipped with
   service manuals; guitar amps are the most documented audio circuits there are. Units
   still in production (Manley Variable Mu, Tube-Tech CL1B) usually have none public.
2. **Datasheet curves for the active parts.** Classic tubes are well documented.
3. **Transformer data.** Almost always the gap. Modern replacement transformers'
   datasheets (Cinemag, Jensen, Sowter, Carnhill / St Ives, Mercury Magnetics or
   Heyboer for guitar amps) give ratio, inductance and winding resistance; they go in
   with that as their source (a replacement's figures, not the original's). Otherwise,
   provisional genome parameters.
4. **Layout.** A `scripts/draw_<device>.py` on `varimu/editor/sketch.py`, checked pin by
   pin, as for the 670 and the EQP-1A.

**Naming.** Brand names are fine inside the project. Shipping the app with devices named
after brands is a trademark question for later.

## Sources

- Fender 5E3 tube lineup: web: https://www.vintageguitar.com/36026/fender-5e3-deluxe/
- 5E3 annotated schematic and circuit description: web: https://robrobinette.com/How_The_5E3_Deluxe_Works.htm
- Fender Deluxe revisions: web: https://en.wikipedia.org/wiki/Fender_Deluxe
- V76 tube complement and the V72's: web: https://vintageking.com/tab-telefunken-v76-microphone-preamp-4-channel-racked-set-2464-2414-5919-3094-vintage
- V76 threads (tube complement, simplified variant): web: https://groupdiy.com/threads/v76-hack.15169/, https://groupdiy.com/threads/v76-pre.76868/
- EF804S vs EF806S pinouts: web: https://groupdiy.com/threads/erm-ef804s-is-ef806s-with-different-pinouts.14035/
