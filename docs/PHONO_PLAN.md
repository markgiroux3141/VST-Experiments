# Grooves: vinyl, the gramophone and wax cylinders from physics

Drafted 2026-11-01 from a conversation with the user ("do we have a plan for simulating a
vinyl record player from physics? ... extend this to include a gramophone and even wax
cylinders for some really old school sounds"). It grows FUTURE_DIRECTIONS.md §6 (vinyl,
a sketch) into a plan and adds the acoustic machines before it. Nothing in it is built.
It is parked until the user picks it up. The order below is a recommendation; the open
decisions are the user's.

## The frame

Every format here is the same machine: **a groove written in space, read later by a
stylus moving along it.** Only the groove's direction, the materials and what sits on
either side of the groove change:

| | Vinyl LP (1948-) | Shellac 78 (c. 1898-1950s) | Wax cylinder (1888-1929) | Tin foil (1877) |
|---|---|---|---|---|
| Groove modulation | 45/45 stereo: lateral L+R, vertical L-R | Lateral, mono | **Vertical ("hill-and-dale")** | Vertical, embossed, not cut |
| Groove speed | ~0.51 -> 0.21 m/s (33 1/3 rpm, r 146 -> 60 mm) | ~0.98 -> 0.41 m/s (10", 78 rpm) | **~0.47 m/s, constant** (55.6 mm diameter, 160 rpm) | Hand-cranked |
| Stylus | Diamond, ~1-2 g | Steel needle, ~100-150 g, worn in one play | Sapphire or diamond on a floating weight | Blunt point |
| Medium | PVC | Shellac with an abrasive filler | Soft wax ("brown", 1888-1901), hard moulded wax (1902-), celluloid (Blue Amberol, 1912-) | Tin foil on a grooved mandrel |
| Recording | Lathe from an electrical chain, RIAA (1954-) | Acoustic horn (to 1925), then electrical (Western Electric, 1925-) | Acoustic horn | Acoustic horn |
| Playback | Cartridge -> phono stage | Soundbox -> tone arm -> **horn**, no electricity | Reproducer -> **horn**, no electricity | Diaphragm -> horn |

(Every figure in the table is `provisional: model knowledge`. Sources for them are listed
under "Sources to start from".)

Recording and playback are separate events on separate machines: a record is cut, kept,
then played. So **the groove is a print** (SESSION_FX_PLAN.md's sense) between two
simulations. That is the physics, not a break from "one coupled simulation". Each side
is one coupled simulation of its own: the recording chain with its cutter, the player with
its stylus, arm, horn and (for vinyl) its phono stage.

The project's rules apply as everywhere:
- physical values only, each with a `source`; groove dimensions, tip radii and material
  constants start provisional and genome-bounded;
- every device model gets a Python reference and a circuitsim counterpart, with tests that
  they agree; SPICE holds a medium's output at 0 V, as for the plate and the tape;
- reproducibility: dust, scratches, roughness and pressing defects are seeded draws
  (`default_rng([seed, crc32(name)])`);
- realistic first, then bend (the user's rule): every "old" sound is a physical condition
  (a worn needle, a played-out cylinder, a hardened gasket), never an EQ or a noise sample.

## What exists and what's new

| Need | What exists | New |
|---|---|---|
| A medium written in space, read by a moving transducer | Tape: `TapeStream` (`tape_stream.rs`), the IR element `Tape`, `media.rs`, blocks recorded and read a head distance later | The groove: a height (and, for vinyl, a second wall) per arc length |
| Transport: speed and its wander | TM3's transport (`TapeMachineSpec.transport`: capstan, idler, motor hunting) | Turntable drives (belt, idler, direct), the spring motor with its flyball governor |
| Mechanical and acoustic parts as circuits | The speaker (`P12R@1`, C3): pascals as volts, a 29-section delay line, modes | Masses, springs, dampers and horns as a pattern: mechanical and acoustic networks in the IR |
| Fast contact events | HYBRID_PHYSICS_PLAN.md's event kernels (candidate 9: "Vinyl, the stylus losing groove contact") | The Hertz contact in the stylus' port, dust impacts |
| Modes from geometry | The plate (`plate.rs`), INSTRUMENT_PLAN.md's FEM -> modes pipeline | The soundbox diaphragm (a clamped mica or aluminium disc) |
| Radiation from a horn | The pressure readout (`Vccs`), INSTRUMENT_PLAN.md's BEM | The horn mouth's radiation impedance |
| The room in front of a recording horn | MIC_ROOM_PLAN.md (source -> room -> capsule) | The horn mouth as the "capsule" |
| Tube phono stages, step-up transformers | Tubes, JA cores, the device builder | A tube RIAA stage as a circuit file |

## The model

### 1. The groove (shared by every format)

- **Writing.** The cutter's tip position along the groove is sampled along arc length
  (not time), so the groove is a fixed object a player can read at any speed (an
  off-speed 78, a cylinder at 144 instead of 160 rpm, a cranked tin foil).
- **Resolution.** Near an LP's label, 20 kHz is a ~10 um wavelength; sub-micrometre
  sampling is a few hundred thousand points per second per wall. Cylinders and acoustic
  78s carry far less bandwidth (a few kHz), so they are cheaper. Measure convergence in
  the sample spacing, as TM2 did for cells.
- **Reading by dilation.** The stylus tip's centre follows the groove surface **dilated by
  the tip's shape** (grayscale morphological dilation). Tracing distortion, the pinch
  effect (vinyl), worse inner-groove distortion and the up/down asymmetry of hill-and-dale
  grooves all come out of the geometry. For a fixed tip the dilated groove is computed
  once per record and tip; a tip that wears (the steel needle) recomputes it as it goes.
  Vinyl's two walls need a 2-D dilation across the groove's cross-section.
- **Contact.** The tip meets the surface through a Hertz spring, F = (4/3) E* sqrt(R)
  delta^(3/2), in the stylus' port (folded into the solve, INSTRUMENT_PLAN.md's
  "contacts inside the solve"). **Mistracking** is where the force reaches zero: the tip
  flies and lands, a contact event (HYBRID_PHYSICS_PLAN.md, technique K). A
  hill-and-dale stylus is held down only by its weight and spring, so it loses contact on
  steep downward slopes first: one-sided, even-harmonic distortion.
- **The surface (seeded).** Roughness from the compound; dust as particles with a size
  distribution, each kicking the stylus (the click's character comes from the player's
  mechanics); scratches at a fixed angle (a tick once per revolution); cracks in
  cylinders; warp, an off-centre hole or an out-of-round mandrel (once-per-turn wow:
  0.55 Hz on an LP, 2.67 Hz on a cylinder); non-fill; mould on wax.
- **Wear.** Each play rounds the groove's high-frequency detail off where the tip pressed
  hardest: play count is an aging variable. Soft brown wax wears audibly in a few plays,
  shellac under a 100 g steel needle in tens, vinyl under a 2 g diamond in hundreds.

### 2. Vinyl (from FUTURE_DIRECTIONS.md §6)

- **Cutting.** The cutting amplifier with RIAA pre-emphasis drives a cutter head (a
  mass-spring with a feedback coil); variable pitch from a preview signal.
- **Playback.** Tip mass, cantilever compliance and damper (an elastomer that stiffens
  with age and cold), the arm's effective mass: the arm/cartridge resonance and a
  tip-vinyl contact resonance. Tracking-angle error from the arm's geometry; bearing and
  drive rumble as mechanical noise.
- **Electrical.** Moving magnet: EMF ~ velocity into coil R and L, cable capacitance (an
  HF resonance), a tube RIAA phono stage in circuitsim. Moving coil: a step-up
  transformer (the JA transformer model).
- Stereo forces the "mono first" open decision (FUTURE_DIRECTIONS.md, open questions).

### 3. The acoustic gramophone

The player has no electricity: **needle -> soundbox -> tone arm -> horn -> air is one
mechano-acoustic network**, simulated as a circuit by the impedance analogy (force as
volts, velocity as amperes; mass = inductance, compliance = capacitance, friction =
resistance; acoustic pressure as volts, volume velocity as amperes; transformers for the
lever and the diaphragm's area). That is how the machines were engineered at their peak:
Maxfield and Harrison (1926) designed the Orthophonic Victrola as a matched electrical
analog. Their figures are the validation anchor.

- **The needle.** A steel needle grinds itself to the groove's shape within the first
  revolutions (shellac's abrasive filler is there on purpose to do it), so the tip shape is
  a state that changes during the play, and with it the dilation. Needle types are period
  choices: loud, medium, soft (tip thickness and taper), bamboo fibre, thorn.
- **The soundbox.** A mica (Exhibition) or aluminium (Orthophonic) diaphragm, clamped in
  rubber gaskets, driven by a stylus bar pivoted on springs: a few lumped elements plus the
  diaphragm's modes (clamped-disc modes analytically, or INSTRUMENT_PLAN.md's FEM). The
  gaskets' rubber hardens with age (a condition dial).
- **The tone arm and the horn.** Acoustic transmission lines: the horn by Webster's
  equation in sections (the speaker's delay line generalized), the mouth by its radiation
  impedance (analytic for a piston, INSTRUMENT_PLAN.md's BEM for a real flare). Morning
  glory horns, internal cabinet horns, the Orthophonic's folded exponential horn. The
  horn sets the loudness: there is no volume control except the needle and the cabinet's
  doors.
- **Output.** Sound pressure at a listening position, like the 5E3 (`Vccs`), into
  MIC_ROOM_PLAN.md's room if wanted.
- **The motor.** A spring motor with a flyball governor: a mechanical feedback loop whose
  hunting is the wow, its speed falling slightly as the spring runs down.

### 4. Acoustic recording (before 1925)

- Performers play into a recording horn: MIC_ROOM_PLAN.md's source -> room, with the horn
  mouth in place of a capsule. Performers' placement around the horn is part of the sound,
  as it was.
- The horn drives a diaphragm, the diaphragm a cutting stylus into wax. The wax resists
  cutting (a viscoplastic force against the stylus, provisional, to source): the cutter's
  load. The recording horn's resonances and the diaphragm's modes give the narrow, honky
  band of acoustic records (roughly 200 Hz-3 kHz, provisional) from physics, not from a
  curve.
- **Electrical recording (1925-)** follows as a circuit: a condenser microphone, an
  amplifier and the Western Electric moving-iron cutter with its rubber-line damping (whose
  rubber also ages). Pre-RIAA 78s used varied turnover and roll-off curves per label: each
  is a property of the recording chain, read from published tables, not a knob.
- "Print my track to a cylinder" becomes a feature: the user's audio as a source in front
  of the horn, cut into wax, played back on a reproducer.

### 5. Wax cylinders

- **The groove.** Vertical modulation at 100 threads per inch (two-minute) or 200 (Amberol
  four-minute), a constant groove speed (no inner-groove loss), on a slightly tapered
  cylinder.
- **The reproducer.** A floating weight holds the stylus down: the contact physics of §1
  in its most audible regime. A diaphragm and a horn as in §3.
- **The medium's history.** Brown wax (soft, wears per play, moulds, cracks), moulded hard
  wax, celluloid. Speeds weren't standardized before ~1902 (roughly 120-160 rpm): the
  player's governor setting is the user's to choose, and the pitch follows.
- **The motor.** Spring or treadle with a governor, as in §3.

### 6. Tin foil (1877)

Foil embossed (plastically deformed, not cut) over a grooved mandrel, read by the same
diaphragm, cranked by hand. The crudest groove: deformation saturates, the foil tears.
This is VICTORIAN_SYNTH_PLAN.md's "tin-foil phonograph as a sampler" (its V5), built on
this plan's groove.

## Cost

- **Writing** a groove is offline (a print), like tape's recording.
- **Reading** with a fixed tip is a lookup into a precomputed dilated groove plus a
  contact port and a small network: plausibly real time at draft for the acoustic players
  (few elements, a few kHz of bandwidth). Vinyl's 2-D dilation and a tube phono stage cost
  more; measure before promising real time.
- Dust and mistracking are events much shorter than a sample: hybrid exceptions where the
  numbers show they're needed, pure physics otherwise.
- The steel needle's changing tip recomputes the dilation as it wears: offline first.
- Dilation over a few hundred thousand points per second is a GPU fit for prints (the
  user's rule: use the RTX 3080 where it fits, keep a CPU reference).

## Condition dials (realistic first, then bend)

Each a physical condition: play count (groove wear), needle wear and type, dust and
scratch density, warp and off-centre, gasket and damper age, spring tension and governor
setting, the room in front of the recording horn, the performer's distance from the horn.
Once dialed in, out-of-range values as deliberate jank (the user's rule): a needle far too
blunt, a governor set to run away, a horn too small.

## Proposed milestones (a recommendation, not decided)

1. **G1: the groove medium (Python reference, then circuitsim).** Writing along arc
   length, dilation by a tip, the Hertz contact in a port, mistracking as an event; built
   on the tape's medium structure (`media.rs`). Done when: a sinusoidal groove read by a
   spherical tip matches Lewis and Hunt's (1941) closed-form tracing distortion, mistracking
   starts where the force balance says it must, Rust agrees with Python within rounding,
   and convergence in sample spacing is measured.
2. **G2: the acoustic gramophone.** The soundbox, tone arm and horn as a mechano-acoustic
   network, shellac, the steel needle and its wear, the spring motor and governor. Done
   when: the Orthophonic's response matches Maxfield and Harrison's published figures within
   bounds set when the curves are digitized, and a published 78's groove geometry plays at
   plausible acoustic levels.
3. **G3: wax cylinders.** The vertical groove, the floating reproducer, wear per play,
   cracks and mould, the cylinder player's governor. Done when: the reproducer's response
   matches published measurements (to be found), and wear per play is measured against the
   archive literature.
4. **G4: acoustic recording.** The recording horn, diaphragm and cutter into wax, fed by
   MIC_ROOM_PLAN.md's room (or a free field until it exists). Done when: a recorded and
   played-back sweep shows the acoustic era's band, within the published ranges.
5. **G5: vinyl playback.** Cartridge, arm, the 2-D dilation, a tube RIAA phono stage (and
   MC with a step-up transformer).
6. **G6: the surface.** Dust, scratches, roughness and pressing defects as seeded draws,
   for every format.
7. **G7: cutting vinyl.** The lathe, RIAA pre-emphasis, variable pitch; electrical 78
   recording (the Western Electric chain) on the same machinery.
8. **G8: tin foil.** Embossing, tearing, the crank; shared with the Victorian synth's V5.

## Sources to start from

- Groove geometry and tracing: Pierce and Hunt, "On distortion in sound reproduction from
  phonograph grooves" (JASA, 1938); Lewis and Hunt, "A theory of tracing distortion in
  sound reproduction from phonograph records" (JASA, 1941).
- The acoustic gramophone: Maxfield and Harrison, "Methods of high quality recording and
  reproducing of music and speech based on telephone research" (Bell System Technical
  Journal, 1926).
- Horns and acoustic networks: Webster (1919), Olson, *Acoustical Engineering*; Beranek,
  *Acoustics*.
- Formats, speeds, groove dimensions, recording curves: Copeland, *Manual of Analogue
  Sound Restoration Techniques* (British Library, 2008); the UCSB Cylinder Audio Archive.
- Contact mechanics: Johnson, *Contact Mechanics* (Hertz); material constants for PVC,
  shellac compounds and waxes to be found.
- Stylus and cartridge mechanics: the phono cartridge literature (moving-magnet and
  moving-coil equivalent circuits).

## Open decisions (the user's)

- **Which era first.** The order above starts with the acoustic machines: they need only
  G1, no electronics, little bandwidth, and they are the most distinctive sound. Vinyl
  first is the alternative.
- **Mechanical networks in the IR.** Masses, springs and horns as circuit analogs (the
  speaker's precedent, made a pattern) versus a separate mechanical element type.
- **Real time.** The acoustic players' playback is a candidate; recording stays a print.
- **Stereo** for vinyl (FUTURE_DIRECTIONS.md's "mono first").
- **Where the track goes** relative to tape (TM5 onwards shares the medium and transport
  models), the synth, drums, instruments, mics and rooms, and the Victorian synth (G8).
