# Mixing inserts: filters, EQ, leveling, gating, de-essing

Started 2026-11-09 (the user: "what other mixing inserts should we create to complete our
app? things like low and high pass filters", then "let's write the plan"). Nothing built.
This plan lists the inserts a mix still lacks and picks a real unit for each. Each unit is
built as a physical circuit in the same pipeline as everything else: a circuit file, a
profile against its published figures, a device in `panel::DEVICES`, live auditions and
prints as a session insert (SESSION_FX_PLAN.md). Same ground rules (CLAUDE.md "Hard
rules"): every value sourced, one coupled netlist per device, two implementations per
device model, everything seeded.

## Why analog, filters included

A gentle high-pass at 80 Hz sounds about the same from a real unit as from a biquad. By
the user's rule ("subtle differences count as verified") that alone wouldn't justify the
work. These reasons do:
- **One pipeline.** A filter built as a circuit prints, caches, chains and renders like
  every other insert, so the app keeps no digital exception to maintain.
- **It costs little.** Op-amp filters are linear: DK folds them into the step matrix, so a
  clean channel filter costs a few states and plays live easily. The cost is in tubes and
  iron around a filter, not in the filter.
- **Character where filters work hard:** steep slopes, the bump at the cutoff from a real
  inductor's Q, an inductor's core saturating on a big low boost (it already comes out of
  the physics in the EQP-1A), insertion loss and the make-up amp's distortion,
  transformers, and how a passive network loads the device ahead of it.

**Not inserts:** trim, polarity, pan and the fader are the mixer's job and stay digital
(SESSION_EDITING_PLAN.md SE4). Console character belongs to STEREO_PLAN.md's ST6-ST7 and a
summing stage, not to the fader.

## What exists (2026-11-09)

| Job | Inserts | Gap |
|---|---|---|
| Compression | the 670, the keyed 670, the SSL bus compressor, the 1176 | a leveler for vocals and bass |
| EQ | the EQP-1A (low and high boost / cut) | high-pass / low-pass filters, mids, a parametric |
| Colour | the tape insert, the V76, V72 and UA 610 preamps, the 5E3 | (enough for now) |
| Space and time | the plate, the gold foil plate, the 6G15 spring, the 351 echoes | (enough for now) |
| Modulation | the Uni-Vibe (MODULATION_PLAN.md MD1, in progress) | that plan's list |
| Gating | none | a gate / expander |
| De-essing | none (a keyed 670 without a sidechain filter) | a filtered sidechain |
| Width | none | STEREO_PLAN.md ST7 |

## The list, in build order

| # | Insert | Fills | What's new to build | Status |
|---|---|---|---|---|
| MX1 | **SSL 4000 E channel filters and EQ** | HPF / LPF, a 4-band parametric: the clean workhorse | the EQ card's circuit; the `opamp` part and the E's mic amp exist (CHAINS_PLAN.md WP4) | |
| MX2 | **Pultec HLF-3C** | coloured passive HP / LP | a make-up amp (a decision); nothing new in the models | |
| MX3 | **Pultec MEQ-5** | coloured mids: the EQP-1A's partner | nothing new | |
| MX4 | **Teletronix LA-2A** | the vocal and bass leveler | the T4B (an electroluminescent panel on CdS cells), a 6AQ5 fit | |
| MX5 | **A VCA gate / expander** | drum gating, cleanup | the gate's detector and timing; the Blackmer cell exists (B11) | |
| MX6 | **De-essing: K4 on the keyed compressors** | a filtered sidechain | SIDECHAIN_PLAN.md K4 | |
| MX7 | **Neve 1073** | inductor mids and its HPF | = DEVICE_BUILDER_PLAN.md B13 (= CHAINS_PLAN.md WP11) | queued there |
| MX8 | **The mid / side matrix in iron** | width | = STEREO_PLAN.md ST7 | planned there |

MX7 and MX8 are tracked in their own plans and listed here only so the mixing toolkit is
seen whole.

Later, if wanted: the API 550A (its 2520 op-amp waits on the user's schematic, CHAINS_PLAN.md
WP12), the Langevin EQ-251A and Cinema Engineering 7080 passive EQs, an Aphex Aural
Exciter, an analog transient shaper (a VCA keyed by two envelope followers), the dbx 160,
the Neve 2254 / 33609 (DEVICE_CANDIDATES.md "After B13").

## MX1: the SSL 4000 E channel filters and EQ

The clean analog filter, and a parametric the app doesn't have. Continuous pots, so it
sweeps (the Pultecs and the 1073 switch).

- **Sources:** SSL's EQ card 82E02 (the "brown knob" 02 EQ) is already found, beside the
  82E01 mic amp card (`data/schematics/ssl_4000e/README.md`: web:
  https://www.ka-electronics.com/images/SSL/ssl_82E02.pdf, sha256
  `4f30c2e4f20454b8b6ae347c8f416ca32b5192f0459e6600f41e22f45db0a814`). Not yet transcribed.
  To confirm on the drawing: whether the high-pass / low-pass filters are on that card or on
  their own, and the 02 card against the "black knob" 242 card (the user picks if both are
  found; the 02 is the one at hand).
- **Circuit:** `config/circuits/ssl_4000e_eq.yaml`, the EQ card's op-amp stages (5534s) on
  the `opamp` macro, ideal rails like the E's mic amp. Mono in, mono out.
- **Profile:** a profile like `varimu/measure/opamp_pre_suite.py`, per band: the response
  at each pot's ends and centre against whatever curves SSL published; the filters'
  cutoffs and slopes; THD at +4 dBu and near clipping.
- **The app:** `ssl_4000e_eq` in `Group::Eq`, live at draft-1x; measure its load with
  `examples/load_profile.rs` (target: well under the 670's).

**Done when:** the circuit matches the drawing (a test reads the transcribed values), the
profile's curves land on the published ones or the misses are written down with a cause,
and the device plays live and prints as an insert.

## MX2: the Pultec HLF-3C

A passive program filter: stepped high-pass and low-pass LC sections. Facts from model
knowledge until the sheet is found: the frequencies, slopes and impedance (600 ohm) to
confirm.

- **Sources:** Pulse Techniques' sheet or manual for the HLF-3C, in the EQP-1A's family
  (`data/schematics/pultec_eqp1a/README.md` lists that manual). To find: `data/schematics/
  pultec_hlf3c/`.
- **The make-up amp (a decision, below).** The HLF-3C is passive: in a studio it sat after a
  line amp that made up its insertion loss. Without one its output is just quieter, and its
  source and load impedances set its curves. Options: (a) passive alone, with source and
  load resistances as parameters; (b) after the EQP-1A's own amplifier (the drawing
  exists); (c) after a period line amp (the V72 or the 351's console line amp).
- **The inductors** as designs in C2's transformer designer, so a big signal into the
  high-pass saturates them the way it would in the unit.
- **Switches:** the steps are `switch` parts. A change of step is a rewiring and restarts
  the stream, as the 670's TC switch does (accepted: it is how the unit behaves).

**Done when:** each step's response against the published curves, the inductors'
saturation at a high level measured, the insert plays and prints.

## MX3: the Pultec MEQ-5

A passive mid-range EQ with a tube make-up amp: a low-mid peak, a mid dip and a high-mid
peak, stepped frequencies (to confirm on the sheet). Stacked after the EQP-1A, it is the
classic Pultec pair.

- **Sources:** Pulse Techniques' MEQ-5 manual (to find; `data/schematics/pultec_meq5/`).
- **Circuit:** `config/circuits/pultec_meq5.yaml`; its amplifier is probably the
  EQP-1A's family of 12AX7 / 12AU7 stages (to confirm). Reuse the EQP-1A's transformers
  only where the drawing names the same parts.
- **Profile:** `varimu.measure.eq_suite` (the EQP-1A's) extended to the MEQ-5's bands.

**Done when:** as MX2, and the EQP-1A -> MEQ-5 chain prints as two inserts.

## MX4: the Teletronix LA-2A

The optical leveler for vocals and bass. Dropped behind the guitar amps and the V76 on
2026-10-28 (DEVICE_CANDIDATES.md "Decisions"). Its main blocker, a photocell model, is
being built now for the Uni-Vibe (MODULATION_PLAN.md MD1: `varimu/devices/photocell.py`).

- **Sources:** the manual's schematic (widely circulated; DEVICE_CANDIDATES.md rates the
  outlook excellent), the transformers' datasheets. `data/schematics/teletronix_la2a/`.
- **New to build:**
  - **The T4B's light source:** an electroluminescent panel, driven by the audio-frequency
    sidechain. Its light follows the drive's voltage and frequency, not a filament's
    temperature, so it is a new light input for the photocell (a device kind or an option,
    decided when built), with two implementations as usual.
  - **The CdS cells' memory:** the LA-2A's release is two-stage (fast at first, then slow,
    slower after long gain reduction). The photocell has one state (traps filled and
    emptied), and MD1 already lists its missing rise / fall asymmetry as open. The
    Suitcase's `VTL5C2@2` needed a slow cell for its pan for the same kind of reason. This
    is the milestone's physics risk: bring options with numbers before changing the
    model (the user's rule).
  - **A 6AQ5 fit** (the output tube); the 12BH7 and 12AX7 exist.
- **Profile:** a limiter suite like `varimu/measure/limiter_suite.py`: gain reduction
  against level, attack, the two-stage release, THD, against the manual's figures.

**Done when:** the profile against the manual's figures, the release's two stages
measured, the insert plays and prints. A cheaper first step if the T4B stalls: a
lamp-driven photocell limiter of our own design (DEVICE_CANDIDATES.md lists it; the lamp
and the photocell both exist).

## MX5: a VCA gate / expander

Every drum mix needs one. Candidates (a decision, below), from model knowledge until the
schematics are found:
- the **Allison Research Kepex** (1970s, Paul Buff's VCA: to confirm which gain cell);
- the **Drawmer DS201** (1980s, a VCA gate with HP / LP filters on its key);
- a gate of our own on the dbx 202C's Blackmer cell (B11, `scripts/blackmer_cell.py`), if
  neither schematic turns up.

New to build: the detector (a comparator with hysteresis), attack / hold / release timing,
the range (how far it closes), and a key input like the keyed 670's (`panel::Device::key`),
so a kick can open a gate on another track. Done when: open and close thresholds,
hysteresis, the timing and the range measured against the unit's figures, keyed from
another track in a session, printed.

## MX6: de-essing (K4 on the keyed compressors)

De-essing in the period was a compressor keyed from a high-passed copy of its own input.
SIDECHAIN_PLAN.md's **K4** (FLAT / LP / HP at the pick-off, on a JA-cored inductor) builds
the filter. With the keyed 670 at INT and K4 at HP it is a de-esser. This plan adds:
- K4 on the SSL bus compressor's key as well (it is keyed already);
- a de-essing profile: gain reduction on a sibilant test signal against a voiced one;
- a preset or note in the insert panel ("HP key for de-essing"), not a separate device.

Done when: K4 is done (its own plan's done-when), and the 670 at INT + HP reduces
sibilance by a measured amount while leaving the voiced band within a stated tolerance.

## Decisions for the user

1. **The order.** Proposed: MX1, MX2, MX3, MX4, MX5, MX6 (MX6 can go any time K4 does).
2. **MX1's card:** the 02 EQ card (found) or the 242 black-knob card (to find).
3. **MX2's make-up amp:** passive alone, the EQP-1A's amp, or a period line amp.
4. **MX5's unit:** the Kepex, the DS201, or our own gate on the Blackmer cell.
5. **A digital utility filter:** proposed never; MX1 is the cheap clean filter.

## Status

Nothing built (2026-11-09).
