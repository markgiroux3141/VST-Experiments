# Invented instruments and devices

Brainstormed with the user on 2026-11-06. The ideas are parked until the user picks one up.
**Built:** I1, the Nickel Organ (2026-11-06, offline Python: docs/NICKEL_ORGAN_PLAN.md).
**Sketched and rendered (2026-11-21, a second brainstorm, unattended at the user's request):**
I7 and I11-I16, see "Second brainstorm" at the end; samples in `reports/invented/`.

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

**Sketched 2026-11-21** (`varimu/invented/rijke.py`; "Second brainstorm" below).

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

## Second brainstorm (2026-11-21): sound sources the project doesn't have

The user asked for more invented instruments that sound **different** from the ones already
built, with simple experiments and rendered samples to judge by ear, and delegated the
decisions. Every instrument built so far is struck, plucked, a keyed reed or tube
electronics. So this round starts from excitations the engine has never had: **friction, a
moving air stream, a plasma, grazing contact, liquid and heat**.

Each one was prototyped alone, offline in Python (the RH1 / D1 pattern: "test audibility
before building"):
- the code is `varimu/invented/` (outside the render cache key);
- `scripts/invented_sketches.py [--only NAME]` renders to `reports/invented/<name>/`: each
  take dry and through the EMT 140 plate at 30 %, all at -20 LUFS, with a spectrogram
  beside each; the listening guide is `reports/invented/README.md`;
- `tests/test_invented.py` checks one physical claim per sketch (~20 s).

The sketches run at 48 kHz. Most values are `provisional: model knowledge` or design
choices, marked in the modules. **Nobody has listened yet:** the notes below on how the
instruments sound come from the spectra.

### I11. The Rosin Wheel Organ (bowed steel bars): sketched

**The phenomenon:** stick-slip friction.

**The design:** tuned steel bars (8 x 25 mm, free-free: 0.31 m at A4, 0.62 m at A2) over
tuned tube resonators, as on a vibraphone. A key presses its bar onto a rosined wheel
turning at 0.25 m/s, the hurdy-gurdy's mechanism (Chladni's clavicylinder of 1799 also
rubbed bars from a keyboard). The key's depth is the press force (0.4-4 N), and a felt
damper falls when the key lifts.

**The panel:** WHEEL SPEED, the key's depth, DAMPER.

**The sketch** (`friction.py`): the bar's bending modes, one trapezoidal step per sample.
The contact force at the step's end is solved exactly from a hyperbolic rosin curve: stick
while the static limit holds, else the slip speed from a quadratic. Rosin noise and the
wheel's eccentricity are seeded. It costs 0.4 s of compute per second per bar.

**Found:** the regimes a bow gives on a bar.
- A light press on a low bar speaks its second mode (2.76 f1): the squeal.
- A moderate press speaks the fundamental, with the bar's inharmonic partials above.
- Past ~4 N it breaks into a raucous multi-mode scrape (`press_sweep_A2`).

**Next if picked:** a circuitsim medium (a handful of modes and one scalar contact: cheap
live), a magnetic pickup into the 5E3 or a tube preamp, and the glass version (I17).

### I12. The Aeolian Keyboard (wind-sung strings): sketched

**The phenomenon:** vortex shedding locking in to one of a string's harmonics.

**The design:** gut strings, all 0.7 m, over a wind chest. A key opens the slot under its
string, and a WIND pedal sets the speed. The diameters are voiced so that the nominal
2.5 m/s speaks the 4th harmonic on every key (D = St U / (4 f1): 1.14 mm at A2, 0.28 mm at
A4). The pedal therefore walks the whole keyboard up and down the harmonic series together.

**The sketch** (`aeolian.py`): the string's modes (exact per step), driven by six wake
oscillators along the slot (Facchinetti, de Langre & Biolley 2004: a van der Pol lift,
A = 12, epsilon = 0.3), with gusts as seeded noise. It costs 1.4 s per second per string.

**Found:** at 110 Hz the wind picks the harmonic: 1.5 m/s speaks the 3rd, 2.5 m/s the
4th, 3.6 m/s the 6th. Gusts make the shedding whistles glide above the locked partials
(the wake's own harmonics, unlocked). It sounds ethereal and is hard to play in tune: the
pitch is always a harmonic of the key, but the wind decides which one.

**Next if picked:** the soundboard as modes, a law from key velocity to slot opening, and
whether to let the player choose the harmonic per key (a second slot height).

### I13. The Arc Organ (Duddell's singing arc, keyed): sketched

**The phenomenon:** a carbon arc's negative resistance, sustaining an LC circuit across it
(Ayrton's law: V = a + b l + (c + d l) / I). The arc is its own loudspeaker: the pressure
follows d(power)/dt. Duddell played tunes on one in 1900 by switching condensers.

**The design:**
- a 110 V DC arc on 2 mm solid carbons, with a ballast and a choke;
- a 4 mH tank coil and a condenser per key, after the factory trim: 145 uF at G3,
  30.5 uF at A4, 7.7 uF at A5;
- each condenser rests charged to the arc's voltage and lets go through a quench
  resistance.

Each arc is monophonic; a duet is two arcs.

**The panel:** CURRENT (3-9 A: from gentle to Ayrton's hissing arc), SPEAK (the tank's
resistance), ARC GAP.

**The sketch** (`arc.py`): a Mayr arc whose steady state is Ayrton's law (tau 30 us,
provisional), a strike voltage and a residual conductance so it can restrike, and the
carbons' feed hunting the gap. One trapezoidal substep (x8) reduces to one scalar equation.
It costs ~3.5 s per second.

**Found:**
- The arc's small-signal resistance at 5 A is -1.31 ohm. A tank with more resistance than
  that never starts (a test checks it).
- The arc always ends up going out and restriking every cycle (Duddell's type II), so it
  is **bright and buzzy** at every setting, with a breathy hiss between notes.
- SPEAK near the threshold (1.1-1.25 ohm) makes a note take ~0.3 s or more to build, and
  while it builds it is a **pure, quiet sine**: short notes stay pure and only held notes
  grow into the bright regime, so brightness follows how long a key is held
  (`speak_0.4_1.1_1.25ohm`). Probably the arc's most musical setting.
- Untrimmed, the arc pulls the pitch 50-200 cents flat, depending on the current. Trimmed,
  it lands within ~15 cents and wanders with the gap.

**Next if picked:** a horn or a resonator box in front of the arc if it is too harsh; the
arc as a device kind in both builders (a Mayr conductance on a state node, like the lamp),
keyed by a tube circuit; I18.

### I14. The Buzz Zither (jawari bridges): sketched

**The phenomenon:** a distributed one-sided contact. A string grazes a gently curved bridge
once a cycle: the tanpura's and the sitar's jawari.

**The design:** keyed steel strings over bone jawari bridges on a gourd-and-top soundboard.
The strings run 1 m at C3 and shorten up the scale like a harp's, so every string sees the
bridge at the same resolution. A key plucks its string, and a felt damper falls on release.
The tanpura's four drone strings (Pa Sa Sa Sa) are plucked by a cam.

**The panel:** JAWARI (the bridge's curvature; 0 is a sharp bridge), the pluck point.

**The sketch** (`jawari.py`): a finite-difference string with two decay times, at 2x. The
bridge's contact is solved implicitly, point by point (rigid in effect: an explicit
penalty either missed the contact or blew up). The soundboard reads the end tension plus
the contact forces. It costs 2.2 s per second per string.

**Found:** at JAWARI 0.2 (a 10 um drop over 12 mm), the share of energy above 1.5 kHz rises
after the pluck: -21 dB to -16 dB at 1 s, 9 dB over the sharp bridge. The spectrogram
shows the jawari's sweeping formant (`sharp_then_jawari_C3`). JAWARI 1 (a 50 um drop) is
mild, and flatter bridges buzz more. **The likeliest of this round to sound good** (a guess
from the spectra).

**Next if picked:** a Rust medium (the grid is small, so live is plausible), the cotton
thread (the jawari's tuning aid) as a point contact, and sympathetic strings.

### I15. The Siren Organ (a perforated disc): sketched

**The phenomenon:** a chopped air jet (Seebeck's and Cagniard de la Tour's sirens).

**The design:** one motor-driven disc with a ring of holes per key; a key opens the wind to
its ring. Every pitch is a whole multiple of the shaft's speed, so **the keyboard is the
harmonic series** of 13.75 Hz: 16 holes is A3, 32 is A4, and the 7th and 11th harmonics
give their flat notes. Chords are in just intonation by construction. The keys are coupled
twice over:
- each open ring loads the motor, so every sounding note sags together (~20 cents a key);
- they share the bellows, so the level sags too.

**The panel:**
- STOPS: FLUTE (wide holes, through a Helmholtz chamber per key) or REED (narrow holes
  venting straight from the disc);
- SPEED: the siren's glide.

**The sketch** (`siren.py`): the motor and the bellows at 1 kHz, each ring's aperture as
the overlap of two circles, the orifice law, and jet noise riding on the pulses. It is
vectorized and nearly free to compute.

**Found:**
- A 4:5:6:7 chord pulls the shaft from 13.75 to 13.24 rev/s (-65 cents) as the keys come
  in, and it recovers as they leave.
- A note after a rest starts ~20 cents sharp and settles in ~0.35 s as the disc slows
  under the new load: a scoop on every note.
- REED is a buzzy pulse train (2nd harmonic at -4 dB); FLUTE is nearly a sine.

**Next if picked:** a horn per key in place of the chamber (a Webster ladder exists), a
second disc for an equal-tempered keyboard, and the siren's own drive (oblique holes:
self-driven).

### I16. The Bubble Organ (Minnaert resonances): sketched

**The phenomenon:** a bubble's breathing mode (Minnaert 1933: f r ~ 3.3 m/s). Its pitch
rises as it nears the surface, because the surface acts as a pressure-release mirror
(Strasberg 1953).

**The design:** a nozzle per key at the bottom of a water tank, read by a hydrophone.
- Struck, a key releases one bubble: a pitched drop. C3 needs a bubble of 25 mm radius,
  C5 one of 6 mm.
- Held, it streams at the rate the flow sets, with real pinch-off jitter.
- Blown harder, the bubbles grow (V ~ Q^1.2), so the note bends flat (1.4x the flow is
  ~-230 cents) and the bubbles come faster.

**The sketch** (`bubbles.py`): each bubble in closed form (radiation and thermal damping,
the chirp from the surface's image along its rise, a faint surface pop).

**Found:** each bubble rings for 50-250 ms and chirps up 3-14 % before it fades: a
gurgling, glugging tone, percussive when struck. More a novelty than a voice.

**Next if picked:** the tank's own modes (the water's and the glass's), the bubbles'
coupling in a dense stream, and a circuit after the hydrophone.

### I7. The Rijke Organ: sketched (first heard)

I7 above has the design.

**The sketch** (`rijke.py`): the standard reduced Rijke tube (Balasubramanian & Sujith
2008: Galerkin modes of the open pipe, King's-law heat release with a time lag). A heater
gauze per key heats with a 0.6 s thermal lag, the plume's turbulence scales with the heat,
and the sound is the volume velocity leaving both ends (heard broadside). It costs ~1 s
per second per pipe.

**Found:**
- A note blooms ~1 s after its key and then starts suddenly (a subcritical Hopf point).
- Hysteresis: the heater must reach K ~ 0.55 to start a pipe, which then holds down to
  K ~ 0.25 (`heater_hysteresis_A3`).
- The pitch is within ~10 cents of the pipe's length.
- Odd harmonics dominate broadside, because each even mode's two ends cancel.

It sounds hollow and organ-like, with a slow, swelling attack nothing else here has.

**Next if picked:** the gauze as the lamp device (a tube keying its current), stopped pipes,
and I21.

### More ideas, not sketched

- **I17. The Glass Clavicylinder:** I11's friction on glass rods or bowls (Q in the
  thousands, wet-finger friction): the glass harmonica played from a keyboard. A cheap
  follow-up.
- **I18. The Plasma Choir:** several arcs on one DC supply and one ballast. The arcs share a
  current, so the voices pull toward one another or beat. This is EMERGENCE_RESEARCH.md's
  first direction (voices pulling into tune through a shared supply), with a coupling that
  is strong by nature.
- **I19. The Chaos Organ:** a tube negative-resistance (dynatron) Chua circuit in circuitsim.
  Key velocity walks it through period doubling into chaos, so the timbre is a bifurcation
  diagram. Circuit-native: no new device kind.
- **I20. The Waterphone Keyboard:** I11's wheel bowing rods on a water-filled steel
  resonator. The water sloshing bends the resonator's modes (geometry that changes over
  time, shared with P7 / P10).
- **I21. The Singing Flame (Higgins, 1777):** I7 with a gas flame's transfer function and
  its flicker in place of the gauze.
- **I22. The Musical Saw Keyboard:** a bent plate whose S-curve localizes one mode; the
  bend is the pitch. Bowed by I11's wheel.

### Suggested picks (Claude's guess before anyone listened)

1. **I14 Buzz Zither:** the clearest mechanism in the spectra, musical, and plausible live.
2. **I7 Rijke Organ:** the bloom and the hysteresis are unlike any instrument here.
3. **I11 Rosin Wheel Organ:** bowed sustain with an expressive press; the cheapest to play
   live.
4. **I13 Arc Organ:** the rawest of the set; it may be too harsh without a horn.
5. **I12 Aeolian Keyboard, I15 Siren Organ, I16 Bubble Organ:** textures and novelties.

**Open (the user's):** listen (`reports/invented/README.md`), pick, and say what's wrong
with the ones worth keeping. Each module names the provisional values that matter most.
