# The Rhodes electric piano from physics

Drafted 2026-11-04 from a conversation with the user ("an electric piano, built the way
we've been doing the other synths with physics; it would sound like the one in most Stevie
Wonder songs. What would be reasonable given our CPU load and the fact that multiple notes
would have to sound at once?", and: "just like with the synths, we could have a production
setting that we could render offline that was much higher quality and more physically
accurate"). Nothing in it is built. It is parked until the user picks it up. It expands
INSTRUMENT_PLAN.md's section B (Rhodes) and its milestone I2; the order below is a
recommendation, and the open decisions are the user's.

## The target

- **The instrument:** a Fender Rhodes Mark I, the electric piano on Stevie Wonder's 1970s
  records. It is often associated with the **Suitcase** model and its stereo "vibrato" (a
  side-to-side pan) (provisional: model knowledge, to be checked against the songs the user
  picks).
- **Not the clavinet:** "Superstition" and "Higher Ground" are a Hohner Clavinet, a struck
  string read by magnetic pickups. Its structure is the same as this plan's (a modal
  resonator into a field-solved pickup into a passive network), so it could follow cheaply
  once this exists.
- **Stage and Suitcase share the action, the hammers, the tines and the pickups (the
  harp).** Only the amp differs:
  - **The Stage** is passive and plugs into an amp. The project's tube amps (the 5E3 and the
    P12R speaker) are there, so it can be built now.
  - **The Suitcase** has a transistor preamp, vibrato and power amp (the Peterson
    electronics; provisional: model knowledge). It needs the **BJT model**, a shared
    prerequisite that DRUM_PLAN.md and MIC_ROOM_PLAN.md also list.

## Why many notes at once are cheap

A tube synth voice is expensive because it is a nonlinear circuit: `tube_synth` takes ~62%
of the desktop for one voice, which is why MIDI_TAKES_PLAN.md plans four voices behind a
proxy. In a Rhodes, everything that happens per key is mechanical and almost linear. The
nonlinear parts are either brief or memoryless:

| Per key | Physics | Live cost |
|---|---|---|
| Tine + tonebar | An uneven tuning fork: a few beam modes each, the tuning spring as a point mass, in both planes | ~8-12 two-pole resonators |
| Hammer | A neoprene tip, a nonlinear contact with loss | Only during the ~1-3 ms of a strike |
| Damper, grommets | Extra damping on the modes when the key comes up; the mounts' loss | Free (a coefficient change) |
| Pickup | The flux through the coil, a nonlinear function of the tine tip's position | One table lookup per sample |

- **An estimate, to be measured:** 88 keys x ~10 modes x 96 kHz is ~85 M resonator updates
  a second. With SIMD that is a few percent of one core, even with the sustain pedal down
  and every key ringing. Keys that have died away sleep (below a threshold of their own
  energy).
- **Everything after the pickups is shared:** coils in series and parallel, the volume and
  tone controls, the cable, then the amp. That costs the same for one note or 88.
- **So the amp is the bottleneck, not the number of notes.** The 5E3 with its speaker
  readout runs at 1.61x real time at draft-2x, and how Play handles that is still open
  (COMPONENT_EDITOR_PLAN.md, C3's status). Live, the amp would run without the speaker
  (0.48x), and the speaker would come in at production. No proxy is needed: unlike the
  synth's, the live model is the real one, reduced.

## Two tiers from the same physics

Like the tape (the reduced tape live, the literal machine for prints), not like the synth's
proxy: the live tier is the same physics reduced, and the production tier is the reference
it is checked against. Takes follow MIDI_TAKES_PLAN.md: play on the draft, keep the notes,
velocity and pedal as events, render the take at production behind.

| Part | Live (draft) | Production (offline) |
|---|---|---|
| Tine + tonebar | Modes computed once from the geometry, fixed damping per mode | A time-domain beam (finite differences or FEM) of tine and tonebar in both planes: the clamp's coupling between them, the spring as a mass on the rod, the large-swing nonlinearity if it measures audible |
| Hammer | A fitted nonlinear contact, folded into the medium's port | Viscoelastic neoprene (rate dependent: velocity changes the contact time and so the brightness); the action's mechanics from key to hammer |
| Pickup | A precomputed table of flux against tine position | A finer field solve (3D), including the magnet's pull on the tine as a nonlinear force (pitch and sustain then depend on the voicing) |
| Harp | Keys independent | Sympathetic coupling between tines through the rail; magnetic crosstalk between neighbouring pickups |
| Bank's rate | Oversampled (2x-4x), behind M1's FIR decimator | Higher oversampling |
| Amp | Draft quality, no speaker | Production quality, with the speaker and cabinet; a room later (MIC_ROOM_PLAN.md) |

The production tier is also the check: each key's partials and decays from the live modes
against the time-domain beam, and the pickup table's harmonics against the full solve, with
measured margins, as the tape's reduction is checked against the full stream.

## The model, part by part

### Action and hammer

- Key velocity to hammer velocity through the action. The service manual's adjustments
  (escapement, strike line, hammer height; provisional: model knowledge, to be checked) are
  the physical values.
- **Neoprene tips graded in hardness across the keyboard** (provisional: model knowledge;
  the service manual should give it). A nonlinear contact with loss (Hunt-Crossley type) at
  first, fitted to whatever can be sourced.
- **The contact can't be a sample late.** The force depends on the tine's displacement now,
  so the tine's instantaneous response at the strike point is folded into the port and the
  contact's small Newton sees it (INSTRUMENT_PLAN.md's "Contacts inside the solve", shared
  with the drums' beaters).

### Tine, tuning spring and tonebar

- The tine is a steel rod clamped at one end. A uniform clamped-free beam's second mode
  sits at 6.27x its first (the beam's eigenvalues 1.875^2 and 4.694^2). The tuning spring,
  a mass wound onto the rod, moves that ratio. This inharmonic partial is part of the
  attack's bell.
- The tonebar is the fork's other, heavier arm, tuned near the tine's fundamental.
  Coupled through the clamp, the pair trade energy, which sets the sustain.
- **Geometry from the service manual:** tine lengths and diameters, spring positions,
  tonebar dimensions per key. Steel's and brass's constants are published. The modes are
  computed offline into a component version, like `EMT140@1`.
- **Losses:** the clamp, the grommets (the rubber mounts) and air. They start provisional
  and genome-bounded until a source or a published decay measurement replaces them.

### Damper

- Felt pressed onto the tine when the key comes up: extra damping on the modes and a brief
  contact. The sustain pedal (MIDI CC 64) lifts the damper rail.
- The production tier can model the felt's contact; the draft changes the damping.

### Pickup (the character)

- The tine tip vibrates in front of a magnet's pole with a coil around it. The flux through
  the coil depends nonlinearly on the tip's position, and the EMF is the coil's turns times
  dPhi/dx times the tip's velocity.
- **The tine's offset from the pole (the voicing) sets the balance of even and odd
  harmonics:** from mellow to the "bark" of hard playing. That offset and the distance are
  the service manual's voicing adjustments.
- **The field:** a 2D cross-section first (the tip as a permeable cylinder moving past the
  pole), on varimu-components' FEM (`varimu-components fem`, extended from linear windings
  to a permanent magnet and a permeable moving part). Then a 3D solve as the production
  tier's map and the check on the 2D one.
- **The magnet's static pull** on the tine acts as a negative spring: it lowers the pitch a
  little and depends on the voicing. The draft folds it into the tine's stiffness at rest;
  the production tier carries it as a force.
- **Back-reaction:** the force of the coil's current on the tine is negligible (a
  high-impedance load), so the pickup drives the circuit one way. Like the plate's
  exciter-to-pickup path, this stays one coupled simulation: the medium is stepped inside
  the circuit's run (`Transient::step_media`), not chained after it.

### The harp network

- Pickups in series and parallel groups (the wiring from the service manual), each a coil's
  inductance and resistance. The Stage's volume and bass controls, then the cable's
  capacitance. Together they form a resonance that shapes the top end.
- Linear and small: a few elements in the circuit's IR, driven by the medium's EMFs.

### The amp

- **Stage:** into a tube amp. The 5E3 is there now. A blackface Twin Reverb, with its
  optical tremolo (a neon lamp and an LDR), is a candidate; it would need a photoresistor
  model (CdS: slow, its attack and release asymmetric).
- **Suitcase:** the Peterson preamp, the stereo vibrato and the power amp, after the BJT
  model. Its speakers and cabinet are another speaker component like `P12R@1`.

## How it would fit the code (a proposal)

- **The reference:** `varimu/rhodes/` in Python (outside the render cache key, like
  `varimu/drums/` and `varimu/phono/`): the beam models, the contact, the pickup map. Its
  circuitsim port is a medium beside the plate and the tape (`media.rs`).
- **Components:** the harp as a component (kind e.g. `ep_harp`: per-key geometry, modes,
  the pickup map), compiled offline. Its versions are immutable and pinned like every
  component, so a revoiced harp is a new version.
- **Circuits:** a part (e.g. `harp: [out_plus, out_minus]`) in both builders, and
  `config/circuits/rhodes_stage.yaml` (the harp, the Stage's controls, the cable), chained
  into an amp or composed with one.
- **Notes into the medium:** 88 keys with velocity and a pedal are events, not the synth's
  control-input voltages. They need a new feed in varimu-app (beside `Feed::Key` and
  `Feed::Pressure`) carrying note-on velocity, note-off and the pedal into the medium at
  the sample they land.
- **SPICE:** holds the harp's output at 0 V, as for the plate. The medium's agreement is
  Python against Rust.

## Condition dials (realistic first, then bend)

Each one is a physical condition, realistic by default:
- the voicing (the tine's offset from the pickup): mellow to all bark;
- the pickup's distance;
- neoprene hardened with age (brighter, harder attacks);
- hardened grommets;
- worn damper felts (notes that don't stop cleanly);
- tuning springs moved (out of tune, the bell partial shifted);
- a weakened magnet;
- per-instrument variation through seeded tolerance draws (every Rhodes a different one).

## Proposed milestones (a recommendation, not decided)

1. **RH1: one key, offline in Python.** Tine, spring and tonebar from service-manual
   dimensions; the hammer contact; the 2D pickup map. The time-domain beam as the
   reference. Heard straight out, without an amp. Done when: the key's partials match the
   service manual's figures or published measurements, and moving the pickup offset moves
   the even / odd balance as published.
2. **RH2: the harp in Python.** All keys (73 or 88), the damper and pedal, the harp
   network. Done when: the keyboard's pitch and decay across the range are plausible
   against published measurements, and a played MIDI file renders.
3. **RH3: the harp in circuitsim.** The medium in Rust, matching the Python reference; the
   harp part in both builders; the note feed in varimu-app. Done when: Rust matches Python
   within a tested bound, and it plays from a MIDI keyboard in real time with every key
   ringing (the load measured with `examples/play.rs`).
4. **RH4: the amp.** A Stage into the 5E3 (live without its speaker readout, production
   with it), or the Suitcase once the BJT model exists. Done when: it plays live through the
   amp, and the user has heard it against the songs they chose.
5. **RH5: the production tier.** The time-domain beams, the 3D pickup map with the magnet's
   force, sympathetic coupling, the speaker, the takes rendered behind
   (MIDI_TAKES_PLAN.md). Done when: the draft is checked against it with measured margins.
6. **RH6: the condition dials.**

## Sources to find

- The Rhodes service manual (tine, spring and tonebar dimensions; hammer tips; voicing,
  escapement and strike-line adjustments; the harp's wiring).
- Published Rhodes pickup and tine studies. Pfeifle and Münster published on the Rhodes
  around 2014-2017 (provisional: from memory; check titles and venues before citing).
- The Suitcase's schematics (the Peterson preamp, vibrato and power amp), for the
  Suitcase.
- Fletcher and Rossing on beams and tuning forks; Bilbao (2009) on finite-difference beams
  and contacts.

## Open decisions (the user's)

- **Which songs it should sound like.** They pick the Stage or the Suitcase, and the amp.
- **Suitcase or Stage first:** the stereo vibrato waits for the BJT model; a Stage into a
  tube amp can be built now.
- **73 or 88 keys.**
- **Where the track goes** relative to the synth, the tape and echoes, the sidechain, the
  drums, the mics and rooms (INSTRUMENT_PLAN.md proposes the bell before it).
- **How deep the production tier goes** (finite differences or FEM for the beams; whether
  it moves to the GPU).
- **The amp's speaker live:** whether Play's speed question for the 5E3 (C3) is settled
  first, or the speaker stays production-only here.
