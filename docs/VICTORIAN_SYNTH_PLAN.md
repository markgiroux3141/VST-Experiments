# The Victorian synth: a janky synthesizer from 1880s parts

Drafted 2026-11-01 from a brainstorm with the user ("do a Doc Brown": take today's synth
knowledge back to the 1800s, see what parts exist, walk forward until a synth is just
possible, and MacGyver one that sounds disgusting but has a lot of character). **Picked up
2026-11-11 (the user: "let's build the victorian synth"): V0-V3 built in one session;
"Status (2026-11-11)" at the end has what is built, the numbers and what is open.**

## The frame

**Parts from then, knowledge from now.** Every component is something that was made, sold
or found in nature by about 1881. The wiring is ours. What the Victorians lacked was the
ideas: negative resistance, feedback oscillation, subtractive synthesis, envelopes, a
keyboard as a control source. Whether a part may be a material that existed but wasn't
used that way yet (zincite as an oscillator) is an open decision.

The project's rules apply as everywhere:
- physical values only, each with a source;
- one coupled simulation: the cells, the oscillators, the carbon and the receiver in one
  netlist;
- every device model gets a Python reference and its circuitsim / SPICE counterparts;
- realistic first, then bend (the user's rule): the period-accurate instrument comes
  first, and deliberate out-of-range values become panel controls only once it plays.

The period literature is rich, and often the first measurements of exactly the physics we
need (Ewing on iron, Ayrton on the arc, Du Moncel on carbon contacts). Old sources are
good sources here: they count as data, with their own `source`.

## The walk forward

Dates are from model knowledge; each is to be checked against a source when its component
is built.

| Year | What exists | A synth? |
|---|---|---|
| 1800-1836 | Volta's pile (1800), Leyden jars (1745), wire, magnets, huge battery stacks (Davy's at the Royal Institution, 1808). Mechanical synthesis: Kempelen's speaking machine (1791), Kratzenstein's vowel resonators (1779) | **No.** Nothing turns a current into sound except a spark's crackle |
| 1837 | Page's "galvanic music": a magnet rings when its coil is switched. The Neef / Wagner hammer: a self-interrupting contact, the first electric oscillator | **Just possible:** a bank of tuned buzzers on a keyboard, each armature on a soundboard. No filter, amplifier or speaker |
| 1851-1866 | Ruhmkorff's induction coil (1851), Fizeau's condenser across its breaker (1853), Geissler tubes (1857), Planté's lead-acid cell (1859), Reis's telephone (1861), Helmholtz's fork synthesizer (1863), Holtz's influence machine (1865), the Leclanché cell (1866) | Additive synthesis exists (Helmholtz: electrically driven tuning forks and resonators). Gas and spark relaxation oscillators become possible |
| 1871-1881 | Gramme's dynamo (1871), selenium photoconductivity (1873), **Gray's Musical Telegraph (1874: keyboard-played self-vibrating reeds, arguably the first electric synth)**, Bell's telephone (1876), Edison's phonograph (1877), the carbon microphone (Edison, Hughes, 1877-78), Edison's loud-speaking telephone (the electromotograph), the carbon lamp (1879), the Wimshurst machine and the photophone (1880), Ewing's hysteresis (1881) | **A full voice:** oscillator, filter, VCA, amplifier, speaker. The target year: **1881** |
| 1898-1906 | Poulsen's telegraphone, Duddell's singing arc, Cahill's Telharmonium, the Audion | This becomes the tube synth (TUBE_SYNTH_PLAN.md) |

## The instrument: the Menlo Park Abomination (c. 1881)

### Power: wet cells

- **Leclanché cells** polarize under load (hydrogen at the carbon) and recover when
  rested. Hold a chord and the instrument sags. Rest it and it comes back: a sag
  compressor with a memory of minutes.
- **The high-voltage stack**: a few hundred cells in series for the gas oscillator,
  each one's internal resistance and polarization its own (per-cell tolerance draws,
  like `passive_seed`).
- **A Gramme dynamo** instead: commutator ripple, a whine that tracks the crank or the
  engine. The dynamo's speed wander reuses TM3's transport model
  (`TapeMachineSpec.transport`).

### Oscillators

1. **The contact-breaker reed** (Gray, 1874). A steel reed interrupts its own
   electromagnet. A raspy pulse, with arc spray at every break. The pitch follows the
   reed's mechanics, pulled by the battery's sag and the contact's wear. One reed per key
   (paraphonic), as Gray's was.
2. **The gas-tube sawtooth.** The cell stack charges a Leyden jar through a resistor until
   a low-pressure tube strikes (a short gap near Paschen's minimum, a few hundred volts in
   air; Paschen is 1889, but we know it). The **pitch knob is a salt-water rheostat**: an
   electrode sliding in brine. Electrolysis bubbles crackle and the pitch creeps as the
   brine changes. Gas tubes strike late in the dark (the dark effect: they wait for a
   stray ion), so **the synth plays differently with the lamps off**.
3. **The spark-gap sawtooth.** A Wimshurst or Holtz machine (a crank-driven current
   source at tens of kV) charges a Leyden jar until a spark gap fires. The crank's speed
   is the pitch. Loud, filthy, and deadly; in simulation only.
4. **The tonewheel.** A toothed iron wheel past a magnet coil, turned by a treadle or
   clockwork through a flyball governor. The governor's hunting is the wow.
5. **The singing arc** (Duddell found it in 1900, but carbon arcs and dynamos exist by
   1880). An LC across a DC arc lamp oscillates on the arc's negative resistance. A
   whistle with hiss and carbon crackle; the Leyden jar bank and the coil tune it.
6. **The anachronism: zincite.** A zincite crystal against a steel point has a negative
   resistance region (Losev's crystadyne, 1920s; Eccles noted crystal negative resistance
   around 1910). Zincite was a known mineral, so an LC crystal oscillator could exist 40
   years early.

### Filter

- **Coils on bundles of soft iron wire** (the Ruhmkorff coil's core) with Leyden jars
  and paper-and-foil condensers. Iron of the period is far lossier than the 670's mumetall:
  its hysteresis distorts in the filter itself.
- **The saturable reactor as VCF.** Built (TUBE_SYNTH_PLAN.md S1,
  `config/circuits/reactor_filter.yaml`), and 1880s-buildable: a battery and rheostat on
  the control windings are CUTOFF. On period iron its curve changes.

### VCA and envelope

- **Carbon under the key** (Hughes's microphone principle). Pressing the key squeezes
  carbon granules, so the resistance follows the force: velocity and aftertouch with no
  electronics, plus granular hiss that grows with pressure.
- **A dashpot envelope.** An oil-damped piston presses the carbon: a mechanical ADSR whose
  release changes with the oil's temperature.
- **A carbon-filament lamp in series.** Carbon's resistance falls as it heats (tungsten's,
  the LFO's #327, rises): loud notes get louder. A runaway expander.
- **A selenium cell** (optional). A lamp and a shutter make an optical VCA, slow, with
  selenium's notorious fatigue and memory.

### Amplifier: the carbon relay

A telephone receiver's diaphragm presses a carbon button in a second battery circuit. It
gives gain (tens of times, to be sourced), plus hiss, frying, rectification and the
diaphragm's resonant peak. Two in cascade with any acoustic or electric coupling howl.
This is the period's "tube".

### Speaker

- **A Bell receiver on a horn.** Quiet, nasal, peaked at the diaphragm's resonance. Close
  to the speaker model's machinery (`P12R@1`, the `speaker` macro, the `Vccs` readout).
- **Edison's electromotograph.** A hand-cranked chalk drum moistened with an
  electrolyte; the current changes its friction against a metal finger tied to a
  diaphragm. Loud, and stick-slip distortion that depends on the cranking.

### Effects

- **Spring reverb:** a receiver drives a coil spring, a carbon microphone listens at the
  far end. (The spring is in REVERB_PLAN.md already.)
- **Plate reverb:** the same on a sheet of iron (the plate's machinery, `plate.rs`, with
  period steel).
- **Echo: Poulsen's telegraphone** (1898, past the target year; an open decision).
  Steel wire with no bias: the Preisach tape model (TAPE_PLAN.md) in its ugliest regime.
- **A tin-foil phonograph as a sampler:** record, replay at whatever speed it's cranked.

## What exists and what's new

**Reusable:**
- the JA and Preisach cores, a new material fitted to period iron;
- the saturable reactor;
- the lamp device (`varimu/devices/lamp.py`): carbon is a new fit, with the opposite
  temperature coefficient;
- the speaker's modal machinery and `Vccs`;
- the plate (`plate.rs`, `Mna::n_media`);
- B5 noise, B6 thermal lags;
- TM3's transport (dynamo, treadle, governor);
- the Preisach tape for the telegraphone;
- HYBRID_PHYSICS_PLAN.md's gas tube (H1) and its event kernels (H3);
- control inputs, the keyboard and MIDI (`varimu-app`'s `midi`), recording.

**New device models**, with where to source them:

| Device | Physics | Sources to start from |
|---|---|---|
| Wet cell | EMF, internal resistance, a polarization state that builds under current and relaxes at rest | Period battery handbooks; modern Leclanché electrochemistry |
| Contact breaker | The reed's modes, contact bounce, the break arc: microsecond events, so a hybrid-physics exception (HYBRID_PHYSICS_PLAN.md candidate 7) | Gray's patents; induction-coil literature on breakers |
| Carbon contact | Resistance against force (Hertzian granule contacts, packing), its 1/f and burst noise, slow drift. One model for the microphone, the key VCA and the relay | Du Moncel, *The Telephone, the Microphone and the Phonograph* (1879); Hughes (1878); modern carbon-microphone papers |
| Telephone receiver | A permanent magnet, a coil and a diaphragm: a transducer with a few modes | Period telephone engineering texts (Preece and Maier, 1889) |
| Gas tube (cold, low pressure) | Paschen breakdown, glow drop, extinction, the dark effect's statistical delay | H1's model generalized; Paschen (1889); gas discharge texts |
| Spark gap | Breakdown voltage against gap, spark resistance, the jar's discharge | Period spark measurements; Paschen |
| Arc | The V-I curve and its dynamics | Hertha Ayrton, *The Electric Arc* (1902); Duddell (1900); Cassie / Mayr models |
| Zincite contact | A negative-resistance region on a point contact | Losev's papers (1920s) |
| Period soft iron | A JA or Preisach fit | Ewing's measurements (1881-85), *Magnetic Induction in Iron and Other Metals* (1891) |
| Carbon filament | Resistance falling with temperature, a thermal mass | Edison-era lamp data |
| Salt-water rheostat | Brine resistance, electrolysis gas and its crackle, slow drift | Electrochemistry texts |
| Electromotograph | Electrolytic friction, stick-slip | Edison's patents (1877-79) |
| Selenium cell (optional) | Photoconductivity with fatigue and memory | Smith (1873); Bell's photophone (1880) |

## Proposed order (a recommendation, not decided)

1. **V0: sources.** Gather the period texts and patents above into
   `data/datasheets/victorian/` (README per source), and check the walk's dates.
2. **V1: the 1837 buzzer.** A wet cell, a contact-breaker reed, a soundboard or receiver.
   The smallest instrument: one note, then a keyboard of reeds. It brings in the cell and
   the contact-breaker exception. *Done when (draft):* it plays from the keyboard, its
   pitch moves with the cell's sag by a measured amount, and the breaker's exception
   matches its reference within stated bounds.
3. **V2: carbon.** The carbon contact as the key VCA and as the relay, and the receiver.
   *Done when (draft):* the key's force maps to level through the sourced curve, the
   relay's gain and noise match period or modern figures, and two relays in a loop howl
   at the predicted frequency.
4. **V3: the 1881 voice.** Reed -> soft-iron reactor filter -> carbon key -> carbon relay
   -> receiver, all on sagging Leclanché cells, as a `varimu-app` device. Period iron
   (Ewing's fit) and the carbon lamp go in here. *Done when (draft):* the user plays it
   live from MIDI, at a measured load.
5. **V4: more oscillators.** The gas-tube sawtooth through H1-H3 (with the brine pitch
   knob and the dark effect), then the arc, the tonewheel, the spark gap and zincite,
   each its own device first.
6. **V5: effects.** The spring and plate driven by receivers and read by carbon, the
   electromotograph, the phonograph, the telegraphone.
7. **V6: bend.** Out-of-range values as panel controls (the user's rule): brine
   concentration, relay cascade depth, cell count, crank speed, lights on / off.

## Open decisions (the user's)

Taken 2026-11-11: the first three ("Status (2026-11-11)"); where the track goes stays open.

- **How strict the period is:** parts made and sold by 1881 only, or anything that
  existed (zincite as an oscillator, the 1898 telegraphone, the 1900 arc)?
- **Paraphonic or polyphonic:** one reed per key (Gray's way, CPU per held key) or a few
  voices.
- **Live or printed:** must every piece play live, or can the expensive ones (spark gap,
  arc, electromotograph) print first, as with tape?
- **Where the track goes** relative to the tube synth's ideas, hybrid physics (the gas tube
  is shared: H1 serves both), tape, reverbs, drums and the session work.

## Status (2026-11-11): V0-V3 built

**The user's decisions (2026-11-11):** the 1881 core strictly, anachronisms (zincite, the arc,
the telegraphone) later as marked V4 / V5 extras; one reed per key (Gray's way, paraphonic);
the voice must play live, the costly extras may print first; this session V0-V3.

**V0, sources.** A research pass found and read:
- Carhart, *Primary Batteries* (1891), p. 122's table of a Leclanche cell closed on 5 ohm for
  an hour and opened for an hour (`data/datasheets/victorian/carhart_1891_leclanche.csv`, its
  provenance beside it); Niaudet (1880);
- Gray's patents US 165,728 (local-circuit magnets of 16 and 4 ohm working a steel reed),
  166,095 / 166,096 (the Musical Telegraph's self-vibrating "electrotomes", an induction coil
  "of the usual construction");
- Du Moncel (1879: Edison's carbon button changes its resistance almost in proportion to the
  pressure);
- Preece & Maier, *The Telephone* (1889: Bell's receiver, 40 ohm, a 2 in ferrotype diaphragm
  0.13-0.25 mm; Ader's 200 ohm receiver with a 0.5 / 250 ohm induction coil); Miller,
  *American Telephone Practice* (1905: Blake's induction coil, its core of No. 24 Swedish iron
  wire);
- Ewing, *Magnetic Induction in Iron and Other Metals* (Hc 1.9 Oe, mu_max ~1,740, Table V's
  hysteresis losses); Holm's contact tables via the Ney Contact Manual (platinum's minimum arc
  15-17.5 V, 0.67-1.1 A); Ram (1894) on carbon filaments (hot / cold ~1:2).

Dates checked: Wagner's hammer 1836, Page 1837, Fizeau's condenser 1853, Leclanche 1866
(agglomerate 1871, not 1876), Gray 1874, Hughes May 1878, Ewing's "hysteresis" 1881. Found
nowhere: a period telegraph magnet's inductance, a Bell receiver's resonance, a carbon relay's
gain, a measured granular-carbon exponent.

**V1, the reed** (`varimu/victorian/reed.py` the reference, circuitsim's `reeds.rs` the port;
`config/victorian/reeds.yaml`; compiled by `scripts/compile_victorian_reeds.py` into
`GRAY_REEDS@2`, kind `reed_keys`). Per key, 49 keys C2-C6:
- a steel cantilever's two modes, driven where the magnet's poles and the contacts are: at the
  second mode's node, 0.78 of the length (ours: tip-driven by a fast coil, the reed locked onto
  its second mode, 6.27 f1, in the first experiment);
- a horseshoe magnet in flux-linkage form (the pull and the motional EMF from one inductance
  law) in a **local circuit** whose L / R is a quarter of the reed's period, and a **second
  platinum point on the same follow spring chopping the line** through the carbon under the
  key (the two circuits of Gray's and the period's tuning-fork interrupters; with the carbon in
  the drive circuit the reed ran 200-600 cents sharp and moved with velocity);
- contacts that snap open (a preloaded follow spring: a contact whose force faded to nothing
  held the reed hovering at its edge), Fizeau's condenser across the drive break, and a spark
  (micro-gap breakdown, held at platinum's arc voltage until its current falls below the arc's
  minimum); the line's break never sparks at its few volts;
- an oil dashpot pressing the carbon (8 ms pressing, 60 ms releasing; the force proportional
  to velocity, aftertouch up to 1.5x); a felt damper on the reed with its key up (Q 5);
- each reed filed to pitch in place by the reference (`compile.tuning`, two passes: a
  maintained reed runs ~45 cents above its free frequency), within 1.4 cents.

Measured (`scripts/victorian_voice_study.py` -> `reports/victorian/voice/summary.json`):
- **the breaker against its reference** (V1's done-when): the live rate, 768 kHz, against
  6.144 MHz on C2, C3, C4, C5 and C6: pitch within 0.41 cents, the line current's harmonics to
  20 kHz within 0.44 dB rms and 2.1 dB at worst. At 384 kHz the error doubles, so the keys
  stay at 8x;
- **pitch with the cells' sag:** small. The local battery sits at 3.16 V with one key held and
  falls to 2.62-2.92 V with eight; A3 moves +0.7 to -2.1 cents against the nominal 2.8 V (the
  reed is maintained, not forced). The line sags far more: 5.8 V with one key, 4.6 V with
  four, 3.6 V with eight (chords compress);
- circuitsim's medium matches the reference to 1e-9 on ideal batteries
  (`tests/test_victorian.py`; a note at t = 0 lands a sample late, at the first push).

**V2, carbon and the receiver.**
- A new device kind **`carbon`** (`varimu/devices/carbon.py`, circuitsim `devices/carbon.rs`,
  IR `Carbon` in both builders, a SPICE B-source with its agreement test; pins (a, b, f, ref),
  the force on f in newtons): G = G_open + G0 (F / F0)^n, softened through zero force.
  `CARBON_BUTTON@1`: 20 ohm at 0.5 N, exponent 1 after Du Moncel.
- The receivers are `speaker`-kind components: `BELL_RX@1` (40 ohm) and `ADER_RX@1` (200 ohm,
  the same window wound finer), the diaphragm at 700 Hz, Q 10 (provisional: no period figure).
- The relay: the 200 ohm receiver's diaphragm velocity integrated into the button's force (its
  stiffness also loads the diaphragm), the button in its own battery's circuit with the 40 ohm
  receiver.
- Velocity to level (A3, `velocity`): 10 -> -17.7 dB, 20 -> -12.1, 40 -> -7.0, 64 -> -3.9,
  90 -> -1.9, 110 -> -0.7, 127 -> 0.
- **Not done:** the relay's gain against a period figure (none found), two relays in a loop
  howling (V2's draft done-when), the carbon's noise (its 1/f and burst noise grow with the
  current: the plan's character; next).

**V3, the 1881 voice**, `config/circuits/victorian_voice.yaml` (GENERATED by
`scripts/make_victorian_voice.py`):
- the reeds medium on a local battery (2 cells) and a line battery (4) behind Blake's induction
  coil (coupled inductors: its open core's air return dilutes the iron ~20x) and a 10 uF line
  condenser;
- a two-core saturable reactor on **`soft_iron_ewing`** (new in config/magnetics.yaml: JA
  fitted to Ewing's figures, Hc -7.9%, loss +10.1%, under a datasheet block's
  `fit_tolerance`), CUTOFF a graded 500 ohm rheostat from a 6-cell battery on 1575-turn control
  windings;
- the carbon relay (3 cells) into Bell's receiver; `out` its pressure 0.3 m in front (full
  scale 0.003 Pa);
- the cells are **Carhart's cell** (`scripts/fit_leclanche.py` ->
  `config/victorian/leclanche.yaml`: 1.58 V behind 1.0 ohm, a 1.55 ohm / 84 s and a 4.6 ohm /
  3.2 h polarization state; the EMF within 24 mV rms over the two hours; a middle state went to
  zero), each battery one equivalent cell (identical cells in series exactly; per-cell
  tolerance would split them again).

The app's **`victorian_voice`** (Instruments; draft-2x, JA cores live, two threads cut at the
filter's condenser, -44.6 dB rms from the one solve; the mod wheel turns CUTOFF): at a 50 ms
buffer a 4-key chord with a run over it plays without dropouts (worst block 121%); an 8-key
chord drops out (~8 in 10 s). The offline bench (`cargo run --release -p varimu-app --example
victorian -- --bench`): 0.63x real time with the 4-key chord, each sounding key ~0.03x
(`reeds_bench`: 41 ns a key-step). The sound: nasal and telephone-like, the receivers' 700 Hz
diaphragms over the fundamental (on A3 the fundamental sits 37 dB under the 3rd and 4th
harmonics).

**Open:**
- **CUTOFF reads mostly as level.** It lifts the filter's output above ~2 kHz by 20-30 dB and
  the output by ~7 dB, but the band below ~2 kHz barely moves and the receivers pass little
  above ~1.5 kHz. Doubling the reactor's turns (aiming at ~180 Hz unbiased) changed nothing
  below 1 kHz either: the filter isn't the LC the design assumed (the reversible permeability
  at signal levels, the source and load impedances). Timeboxed. Options: an AC look at the
  biased reactor (`varimu/measure/ac.py` at an operating point); a damped (lower-Q) receiver or
  a horn, either of which broadens the band the filter acts in; the filter moved after the
  relay.
- The user listens: `reports/victorian/voice/demo*.wav` (a 4-key chord and a run; CUTOFF 0 and
  1) and plays `victorian_voice` live.
- Not built from V1-V3's list: the carbon lamp (the runaway expander), per-cell tolerance, the
  carbon's noise, the relay's howl, contact wear, a horn on the receiver.
