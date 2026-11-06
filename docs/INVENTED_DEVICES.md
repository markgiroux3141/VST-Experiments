# Invented instruments and devices

Brainstormed with the user on 2026-11-06. The ideas are parked until the user picks one up.
**Built:** I1, the Nickel Organ (2026-11-06, offline Python: docs/NICKEL_ORGAN_PLAN.md).

Each idea is an instrument or processor that never existed but could have. It is built from
parts this project already models, plus at most one or two new physical mechanisms, and it
is sourced and measured the way the rest of the project is. FUTURE_DIRECTIONS.md 8.9
("manuals for invented devices") is the natural companion: an invented device's spec
sheet is its measurement profile.

The Hard rules carry over unchanged (CLAUDE.md). The numbers below are **rough, from
model knowledge**, and only size the ideas. The sources named are where real values would
come from. Nothing here is data yet.

## How to design one

1. **Start from a phenomenon, not a sound.** The engine simulates several things nobody
   has turned into a product: return-point memory (Preisach), thermal lag (lamps, heated
   cathodes), magnetostriction's square law, ionization (thyratrons), groove wear (Archard),
   room eigenmodes, tension modulation, dispersion (the spring). Ask what instrument or box
   each one wants to be.
2. **Fix an era and a parts catalog.** "Every part existed by 1955" (or 1881, 1935) is
   what makes the device plausible. VICTORIAN_SYNTH_PLAN.md sets the precedent.
3. **Write the manual first.** It covers the front panel, what each knob physically is,
   the specs, and a service-manual operating point.
4. **Source every part; only the topology is invented.** There is no reference for the
   whole device, so plausibility does the anchoring. Tubes stay within their ratings, idle
   voltages look like ones a technician would recognize, and the profile reads like a spec
   sheet.
5. **Test audibility before building.** Phase 5's lesson: realistic differences can be
   too subtle to choose between. Prototype the new mechanism alone, offline in Python (the
   RH1 / D1 pattern), and hear it at realistic values. If it can't be heard, bend it on
   purpose (the "realistic first, then bend" rule).
6. **Then the usual path:** the Python reference, a circuit file, a profile, and a live
   tier if the device earns one.

## Instruments

### I1. The Nickel Organ (a magnetostrictive bar organ)

**Built 2026-11-06** (offline Python; docs/NICKEL_ORGAN_PLAN.md has the manual, the first
experiment's answers and what changed from this sketch: a dead-twin bridge for the one coil, a
per-key voiced drive ladder, the lamp in series with a triode-connected 6V6GT). The zero-bias
sub-octave doesn't happen; POLARIZE turned out to be a timbre and level control.

**The phenomenon.** Magnetostriction: nickel and iron change length when magnetized,
roughly as M². That's why transformers hum at twice the mains frequency. In the 1950s it
drove sonar transducers and Collins' mechanical filters (nickel-alloy resonators). No
keyboard instrument was built on it.

**The design.** Each key has a nickel-clad flexural bar, tuned like a Rhodes tine. One coil
per bar both drives it (magnetostriction) and senses it (the Villari effect: stress changes
the magnetization). The bar sets the frequency of a tube feedback loop.

**The panel:**
- **SUSTAIN:** the loop gain. Below 1, the loop is held just short of oscillating (the
  Side Man's RING), so a key gives a struck bell that decays. Above 1, it sustains like an
  organ, held level by a lamp AGC (the LFO's #327) whose thermal lag makes the note bloom.
- **POLARIZE:** the DC bias. With bias, a drive at f pushes at f and gives a clean tone.
  At zero bias the push comes at 2f, so the loop has to run parametrically. The guess is
  that the electrical side runs at half the bar's pitch, a sub-octave growl under the bell.
  Nobody here knows what that loop does; finding out is the first experiment.
- **The shared yoke:** all bars return their flux through one frame. A note partly biases
  its neighbours, so chords interact magnetically and through the mounting rail as a modal
  medium ("most organic first").
- **Remanence:** nickel keeps magnetization, so a hard strike pre-biases its own bar. The
  instrument remembers how it was just played.

**What we have:** JA / Preisach cores, the C2 coil designer, the Rhodes harp's keyed
machinery (`keyed.rs`), the Side Man's degenerated loop, the lamp.

**What's new:** a magnetoelastic coupling, a device joining a core node to a modal medium
(λ(M) one way, Villari back). It is shared with P8 and REVERB_PLAN.md's candidate 4.
Sources: Bozorth, *Ferromagnetism* (1951), for nickel's λ(H) (saturation about -30 ppm, to
be sourced); Hunt, *Electroacoustics* (1954); Adler (1947) and Roberts (1953) on
mechanical filters.

**First experiment:** one bar in a tube loop in Python, sweeping POLARIZE from saturation to
zero.

### I2. The Singing Drum

**The phenomenon.** A membrane's modes are inharmonic, and tension modulation bends them up
with level.

**The design.** A drumhead with a moving-coil driver at its centre and a pickup, in a tube
loop. Each key switches a tuned LC into the loop, which picks the mode the loop locks to.
The scale is the drum's own set of modes. A beater can still strike it, and loud notes
bend sharp as the head stretches.

**The panel:** KEY (which LC), SUSTAIN (loop gain, lamp AGC), HEAD TENSION (all modes),
KETTLE (sealed or open: the air spring shifts the (0,1) mode).

**What we have:** `varimu/drums/` (modes, tension modulation, shells coupled through the
air), `moving_coil`, the lamp.

**What's new:** a drum medium in circuitsim (D1 runs 9-14x slower than real time in Python,
so offline first).

### I3. The Drip Organ (a spring tank in a loop)

**The phenomenon.** A spring's dispersion: a strike comes out as a falling chirp, the
"drip".

**The design.** The 6G15's tank (`ACC4AB3C1B@1`) in a tube feedback loop. A key's LC picks a
spring mode to sustain. A strike (a pulse into the driver) chirps before the loop settles on
the note. Bent versions would swap springs: longer, stiffer, two in parallel beating.

**What we have:** all of it, live (the spring medium, the 6G15's driver and recovery stages,
the lamp).

**What's new:** nothing physical. It's the cheapest idea here: an evening's experiment in
circuitsim.

### I4. The Ribbon Harp

**The phenomenon.** A ribbon mic's motor is a nearly massless conductor in a magnetic gap.
Under tension, it becomes a string.

**The design.** Tensioned corrugated aluminium ribbons in magnet gaps. A current drives each
one (Lorentz force, as in a ribbon tweeter), and its own EMF senses it through a bridge. A
tube loop sustains them like an EBow. They radiate directly as dipoles, so the instrument
needs a room.

**The panel:**
- TENSION: a pedal. A slackened ribbon falls in pitch, and the corrugation starts buzzing
  against the pole pieces.
- BOW: the loop gain.
- BAFFLE: the 77-DX's shutter, so the pattern into the room changes the sound.

**What we have:** `ribbon_motor`, the labyrinth, the BOR BEM, rooms, the Clavinet's
tensioned-string modes.

**What's new:** a tensioned ribbon's modes (string plus bending), and the ribbon's contact
with the gap.

### I5. The Room Organ (the notes are a room's modes)

**The phenomenon.** Larsen feedback howls at a room's modes.

**The design.** Each key puts a band-pass LC into a mic -> tube amp -> speaker loop inside a
modelled room. The loop howls at the room mode nearest the filter, so a room is a scale.
Moving or aiming the mic is the expression, since each mode has nodes in different places.
Room presets are the timbres (the stairwell, the chapel). A lamp AGC holds the level.

**What we have:** rooms (image sources, the wave solver), every mic chain, the P12R and its
pressure readout.

**What's new:** a room as an in-loop medium (a convolution like the plate's, but seconds
long). It is shared with P3. Offline first; live is a GPU convolution question.

### I6. The Groove Sampler (samples that wear out)

**The phenomenon.** Archard wear and mistracking.

**The design.** A wax drum with twelve circular loop grooves (no feed screw), one per key,
each with its own reproducer that the key lowers. Holding REC with a key cuts that loop
acoustically from a horn: you sing your samples in. Key velocity is the stylus force, so
loud notes play louder, mistrack and wear their groove faster. The samples age as they're
played. SHAVE resurfaces a loop (Edison's shavers). The governor setting transposes the
whole drum.

**Precedent:** the Chamberlin, the Mellotron and the Optigan played their own fixed
recordings. User-cut acoustic loops that wear are the new part.

**What we have:** `varimu/phono/` (cutting, Hertz contact, wear, the governor, horns).

**What's new:** a loop groove (no feed), and wear on every play.

### I7. The Rijke Organ (heat-driven pipes)

**The phenomenon.** Thermoacoustics. A heated grid a quarter of the way up a vertical pipe
makes it sing (Rijke, 1859; Rayleigh's criterion).

**The design.** Each pipe has a heater grid that a key switches on through a tube. The
attack is slow and breathy (the grid's thermal lag), and the note dies away as the grid
cools. STOPS change the grid's position and the pipe ends.

**Precedent:** Kastner's pyrophone (1870s, gas flames). Electric grids keyed by tubes are
the new part.

**What we have:** the lamp's filament heat (King's-law heat transfer is new), Webster
ladders (`phono/horn.py`).

**What's new:** thermoacoustic coupling (heat release driven by acoustic velocity, with a
lag).

**A variant, the thermophone choir:** a hot filament radiates sound directly (Arnold and
Crandall, 1917). Without a DC bias it sounds at 2f. Very quiet, so it needs a horn: a soft
octave voice.

### I8. The Telegraphone String (speculative)

**The idea.** A steel recording-wire alloy used as a vibrating string, with a playback head
as its pickup. A record head (with bias) writes a magnetization pattern on the wire next to
the pickup. The pattern acts as the pickup's pole shape, so each string's timbre is
recorded and can be erased. Vibration stress slowly demagnetizes it (the magnetomechanical
effect), so the voicing fades with playing until you re-record it.

**The long-wire variant:** long wires rubbed lengthwise, as in Ellen Fullman's Long String
Instrument. The longitudinal motion reads a fine recorded pattern by position, which is phase
modulation: an FM-like spectrum whose index grows with how hard you play.

**What we have:** the tape's Preisach medium, head reciprocity, the Clavinet's strings, the
Rhodes pickup's 2D magnetostatics.

**Open:** whether the geometry gives a usable effect at all. **First experiment:** the 2D
field of a striped wire moving past a head.

### I9. Thyratron Rain

**The phenomenon.** A gas tube fires after a statistical and formative time lag, so its
firing jitters.

**The design.** A bank of thyratron relaxation oscillators held near firing. Their jitter
turns into a granular, rain-like texture. Keys set the charge currents, DENSITY is the grid
bias, and SPREAD is how far the tubes sit apart.

**What we have:** the 2D21 / 884 models and event kernels (H1-H4).

**What's new:** stochastic firing (the lag's distribution, seeded as the Hard rules
require).

### I10. The Tension Gong

**The design.** A plate struck by felt hammers at points chosen by the keys, with the frame's
tension on a pedal. Bending the tension while it rings slides every mode: a pedal-timpani
gong. Hard strikes bloom through the nonlinear plate (REVERB_PLAN.md candidate 3).

**What we have:** the plate (its tension is already a parameter).

**What's new:** a strike port on the plate, tension changing mid-run, and the nonlinear
plate for the bloom.

## Processors

### P1. The Remanence Leveler (memory, not time constants)

**The phenomenon.** Return-point memory. A square-loop core (Deltamax, a 1950s
magnetic-amplifier material) is left in a state set by the largest field it has seen and
hasn't since erased.

**The design.** The gain element is a saturable reactor in an L-R divider, the same part as
synth S1's filter. A 6AL5 rectifies the program into the control winding. A peak leaves the
core partly magnetized, which lowers its incremental permeability and moves the gain. That
setting stays after the peak is gone; there is no release RC.

**Release is erasure.** An ERASE winding takes a decaying AC field (like tape bias, or a TV's
degauss coil with its PTC thermistor). It walks the Preisach state back down its nested
minor loops. Because of the wiping-out property, the gain relaxes to the loudest peak still
remembered, not to zero. Recovery comes in steps that follow the song's dynamics: it
remembers the chorus.

**The modes:**
- HOLD: no erase; it rides the largest peak so far.
- BREATHE: the erase gated from the KEY input (the keyed 670's sidechain work), so a kick can
  wipe the memory every beat.
- FADE: a weak, constant erase.

**Open, answered by the prototype:** the audio winding is itself an AC field on the core, so
loud music may partly erase its own memory, a release that depends on the program for free.

**What we have:** the Preisach ensemble (tape), the reactor, the 6AL5, the keyed sidechain.

**What's new:** a square-loop material, and a PTC thermistor (a small device like the lamp).
It fits the dynamics track (B11-B13), and it turns S1's open problem, the reactor's minor
loops, into the feature.

### P2. The Shaving Echo (about 1935)

**The design.** A wax loop cylinder at 160 rpm (0.375 s a turn), cut by an electrical cutter
on one circumferential track with no feed. A reproducer a movable angle behind the cutter
sets the delay, so time is geometry (DELAY_PLAN.md's rule). A shaving blade just ahead of the
cutter sets how much old groove survives. Feedback happens mechanically in the wax: each
pass is cut over the half-shaved previous one. Repeats lose top end through the tip's
dilation and gain dust, wear and the governor's wow. When the wax can't take any more, the
cutter overloads.

**What we have:** nearly all of it (`varimu/phono/`).

**What's new:** a groove cut over an existing surface, and the shaver.

### P3. The Lucier Unit

**The design.** A tape echo (the 351 echo) whose feedback path runs through the P12R into a
room preset and back through any mic chain. Each repeat converges on the room's eigenmodes,
as in Lucier's *I Am Sitting in a Room*, in a box.

**The panel:** REPEAT, DISTANCE, ROOM, MIC.

**What we have:** tape, the speaker, rooms, the mic chains.

**What's new:** the room in the loop (shared with I5). Print-only.

### P4. The Filament Phaser

**The design.** Lamps of several sizes as the resistances in an all-pass ladder. The program
heats the filaments: through a sidechain driver (HEAT), and through the audio's own current.
The phase sweeps with the program's heat history and drifts back as the lamps cool. COLOUR
picks the lamp sizes, which sets the thermal time constants.

**What we have:** the lamp (tungsten's fits, its thermal node).

**What's new:** nothing physical; it's a topology. Cheap.

### P5. The Vault (print-through as a processor)

**The phenomenon.** Tape print-through. Wound layers magnetize their neighbours by thermal
activation over storage time, which gives a pre-echo and a post-echo one reel turn apart.

**The design.** Record on the 351, store the reel, play it back.
- STORAGE: days to decades.
- TEMPERATURE.
- WIND: tails out or heads out, which decides whether the pre-echo or the post-echo is
  louder.

The echo's spacing is one turn of the reel. It changes through the song as the radius
changes: at 15 ips, roughly 0.8 s near the hub to 2.1 s at the outside of a 10.5 in reel
(rough).

**What we have:** the tape (Preisach particles, head fields); TAPE_PLAN.md lists
print-through as "Later", with Sound Talk Nos. 10 and 38 as the data.

**What's new:** thermal activation in the Preisach ensemble (it also serves tape aging), and
the neighbouring layer's field.

### P6. The Glow Fuzz

**The phenomenon.** A glow discharge strikes at one voltage and goes out at a lower one, and
its ionization is noisy.

**The design.** A gas tube biased just below striking, with the audio coupled in. Peaks strike
it, and it holds until the signal falls past the extinction voltage. The result is a gated,
crackling, hysteretic fuzz. BIAS sets how near it sits to striking, GAS the tube type.

**What we have:** the thyratron's ion-density model.

**What's new:** a glow-discharge tube (today's 5651 is a regulator model).

### P7. The Slide Horn

**The design.** A compression driver (moving coil) into a horn whose length is a trombone
slide. The horn's mouth plays into a room, and a mic picks it up. Moving the slide sweeps the
horn's resonances: a wah made of real air. At high levels, the air in the throat steepens
the wave into a brassy distortion (nonlinear propagation, Hirschberg et al. 1996).

**What we have:** Webster ladders, `moving_coil`, rooms, mics.

**What's new:** a horn whose length changes over time, and nonlinear propagation (Burgers
steepening).

### P8. The Nickel Line Flanger

**The design.** REVERB_PLAN.md's candidate 4 (a magnetostrictive wire delay line) at short
delays. Torsional waves travel at roughly 3,000 m/s, so 3-30 m of coiled nickel wire gives
1-10 ms (rough). The pickup coil slides on a rail: flanging without tape. Without bias, the
square law adds an octave. BIAS sets how much, and the transducers' hysteresis adds grit.

**What's new:** the same magnetoelastic coupling as I1.

### P9. The Cathode Leveler (a bend)

**The design.** The sidechain drives the heater voltage. Run underheated, where the
Richardson ceiling limits emission, the gain follows the cathode's temperature with B6's
roughly 7 s lag: a leveler whose time constant is a cathode's thermal mass.

**What we have:** all of it (B6's heated cathodes).

**What's new:** nothing. It's a bend: a tube run out of its rating on purpose.

### P10. The Swinging Panel

**The design.** A reflecting panel on a pendulum near the mic. The reflection's path length
swings, so the comb filter sweeps: flanging from air, at a period set by the pendulum's
length. SWING sets the amplitude, LENGTH the period, DISTANCE how deep the comb is.

**What we have:** the room's image sources and objects.

**What's new:** moving reflectors (a time-varying image source, with its Doppler shift).

## At a glance

| Idea | New mechanism | Reuses | Cost | Risk |
|---|---|---|---|---|
| I1 Nickel Organ | magnetoelastic coupling | cores, tines, tube loop, lamp | M | the zero-bias loop is unknown |
| I2 Singing Drum | drum medium in circuitsim | drums, moving coil, lamp | M-L | speed |
| I3 Drip Organ | none | spring, 6G15, lamp | S | may sound like a spring and nothing more |
| I4 Ribbon Harp | tensioned ribbon modes, gap contact | ribbon motor, labyrinth, rooms | M | |
| I5 Room Organ | room in the loop | rooms, mics, speaker | M | live cost |
| I6 Groove Sampler | loop grooves, wear per play | phono | M | |
| I7 Rijke Organ | thermoacoustics | lamp heat, Webster ladders | M | |
| I8 Telegraphone String | recorded pole shape | tape, strings, pickup FE | L | may not work at all |
| I9 Thyratron Rain | stochastic firing | thyratron | S-M | |
| I10 Tension Gong | strike port, tension changing mid-run | plate | S-M | the bloom needs the nonlinear plate |
| P1 Remanence Leveler | square-loop core, PTC | Preisach, reactor, sidechain | M | audible at realistic values? |
| P2 Shaving Echo | cut over a surface, shaver | phono | M | |
| P3 Lucier Unit | room in the loop | tape, rooms, mics | M | print only |
| P4 Filament Phaser | none | lamp | S | |
| P5 The Vault | thermal activation | tape | M | |
| P6 Glow Fuzz | glow-discharge tube | thyratron | S-M | |
| P7 Slide Horn | changing horn length, nonlinear air | Webster, moving coil, rooms | M | |
| P8 Nickel Line Flanger | magnetoelastic coupling | cores | M (S after I1) | |
| P9 Cathode Leveler | none | heated cathodes | S | subtle unless bent |
| P10 Swinging Panel | moving reflectors | rooms | S-M | |

**Shared prerequisites, each worth more than one idea:**
- magnetoelastic coupling: I1, P8, REVERB_PLAN.md 4;
- a room in the loop: I5, P3;
- geometry that changes over time: P7, P10;
- thermal activation in Preisach: P5, tape aging;
- stochastic gas firing: I9, P6.

## A suggested order (not agreed)

1. **P1 Remanence Leveler.** It fits the dynamics track, and the Preisach model exists.
   First experiment: one gain cell fed a drum loop, to hear whether the stepped memory is
   audible at realistic values.
2. **I3 Drip Organ.** The cheapest; every part exists live.
3. **I1 Nickel Organ.** The most novel. Its coupling also unlocks P8 and the
   magnetostrictive reverb. First experiment: the zero-bias loop.
4. **P5 The Vault.** It turns the tape's "Later" item into a processor.
5. **I5 / P3.** They share the room in the loop.
