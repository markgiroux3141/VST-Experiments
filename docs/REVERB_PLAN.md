# Reverb: springs and plates as coupled physical media

Drafted 2026-10-30 with the user, after asking where old analog reverbs (spring, plate)
would fit what we've built, in keeping with the physical simulation. **Nothing here is
built, and nothing starts until the user asks for it** (the user's call, 2026-10-30). It
is its own track next to [DEVICE_BUILDER_PLAN.md](DEVICE_BUILDER_PLAN.md),
[COMPONENT_EDITOR_PLAN.md](COMPONENT_EDITOR_PLAN.md) and
[TUBE_SYNTH_PLAN.md](TUBE_SYNTH_PLAN.md). When started, work milestones in order, each
ending with its "done when" met and covered by tests, like the other plans. It is the
first user of the "spatial medium" block that [FUTURE_DIRECTIONS.md](FUTURE_DIRECTIONS.md)
reserves for tape and vinyl, and where [DEVICE_CANDIDATES.md](DEVICE_CANDIDATES.md) sends
the EMT 140 and spring tanks.

## Decisions (2026-10-30, the user's, taking Claude's recommendations)

1. **Spring first, plate after.** A spring is 1D, cheap enough for real time, and
   carries the most character per unit of work; it plays after the 5E3 and inside the
   tube synth.
2. **A standalone reverb is its own device.** A studio patches a separate box in with a
   cable, so rendering a take (the 5E3's, the synth's) and then rendering it through the
   reverb device is physically honest: "one coupled simulation" holds inside each box.
   The cable's load is a one-way coupling at most (a grid input). A built-in reverb (in
   an amp, or a tank in the tube synth's voice) shares its host's supply and goes in the
   host's netlist.
3. **Media have two implementations without SPICE.** A spring or a plate is a
   distributed system with thousands of modes; SPICE can't run it sensibly. Like the
   hysteretic core's exception: a Python reference and circuitsim, with tests that they
   agree, plus checks against closed-form results (the dispersion relation, mode
   frequencies, energy). The transducers' lumped parts (coils, magnets, masses) are
   ordinary IR elements with SPICE as usual; ngspice cross-checks a tank's circuit with
   the medium cut out at its ports.
4. **One-way coupling first.** The drive transducer feeds the medium and the pickup
   reads it, with neither pushed back on (the speaker readout's arrangement). The
   back-reaction is measured in E3; the exact two-way coupling (E5) follows, because the
   same engine feature also speeds up the speaker.
5. **Native app only.** Nothing is added to the web app.

## Why

- **The electronics are what we already do best.** A spring reverb unit is a tube driver
  into a transformer, a tank, and a high-gain tube recovery stage. Much of a spring's
  "drip" is the driver saturating as Dwell turns up: tubes and transformer cores, our
  strongest models.
- **The transducers are half built.** A tank's input is a coil on a pole piece turning
  a magnet on the spring's end; its output is the same in reverse. The plate's exciter is
  a moving coil. The P12R speaker (C3) already has a coil, BL and a moving system in the
  mobility analogy.
- **The medium is new, and can't be lumped into DK.** C3 measured that DK's cost grows
  with the square of the states: the speaker's ~80 readout states took Play from 0.48x
  to 1.61x real time. A spring has ~1000 grid points, a plate ~26,000 modes. The medium
  has to be stepped on its own and coupled at its ports.
- **It's the project's goal in a new place** (memory: "analog magic, not a clone"):
  tanks and plates are designed from geometry and materials (wire gauge, coil radius,
  steel, tension, damping), which is where the component editor heads anyway.

## The physics, and what makes each sound like itself

**Spring (Accutronics / Hammond tanks).** A helical spring carries coupled
longitudinal, transverse and torsional waves; their speed depends strongly on frequency,
so each echo is smeared into a chirp, and a transition frequency set by the helix
geometry (a few kHz) changes how the waves propagate. Echoes repeat at the spring's
round-trip time; 2-3 springs of different lengths per tank decorrelate them. Character
to capture: the chirps, the echo train, the decay against frequency, the driver's
saturation with Dwell, the transducers' resonances, and the recovery stage's hiss and
hum (its gain is high; the output coil picks up mains fields). Later: the tank's crash
when kicked (springs and magnets hitting their limits: nonlinear).
Model: the finite-difference scheme of Bilbao and Parker (Sources) on the helical-spring
equations, from the spring's geometry and steel. A tank is a component (C1's versioning,
kind `spring_tank`), its springs, transducers and mounts as parameters with sources; the
published tank specs (decay class, delay, coil impedances, decoded from the part number)
are its anchors.

**Plate (EMT 140).** A tensioned steel plate (about 2 m x 1 m x 0.5 mm) in a frame.
Bending waves are dispersive (phase speed ~ sqrt(f)), which builds a dense, bright tail
quickly with no room-like early reflections. A porous damper plate beside it sets the
decay time by its distance: the real control, so the knob is physical. Model: modal
synthesis; a tensioned rectangular plate's modes are close to closed form, and each
mode's damping comes from physics (internal loss, thermoelastic loss, radiation, the
damper's air layer). The exciter is a moving coil (the speaker's driver model); the
plate's driving-point impedance is nearly resistive, so its two-way coupling is cheap.
Cost, a rough estimate to measure in E6: a plate's modal density is constant,
n = S / (4 pi) sqrt(rho h / D) per rad/s; for 2 m^2 of 0.5 mm steel that is ~1.3 modes
per Hz, ~26,000 below 20 kHz. A SIMD bank of that many resonators may reach real time on
a few cores; otherwise production renders offline and the draft keeps fewer modes.

**Later or quirkier media** (not milestones yet): tape echo (FUTURE_DIRECTIONS.md's tape
medium), the Binson Echorec (tubes and a magnetic drum), oil-can delays (charge on a disc
turning in oil), the echo chamber (the speaker plus a microphone in a room: a 3D medium,
the most expensive, last).

## The engine: a medium coupled at ports

- **One-way (E2).** The medium is a new IR element on the netlist's nodes: it senses
  drive nodes (like the speaker's `Vccs` readout: it draws no current) and drives pickup
  nodes as sources. circuitsim steps it after each solve, O(N) per sample, outside DK's
  dense state update. Other circuits' IR JSON is unchanged.
- **Two-way (E5).** At each port a linear medium looks like a capacitor's companion
  model: an instantaneous conductance plus a current from its own history. The netlist
  sees a resistor and a current source per port, and the medium steps its internals
  itself: exact, no latency, still O(N). With multi-stage methods (esdirk4, TR-BDF2) the
  companion is per stage; working that out is part of E5. The speaker's readout and its
  delay line move onto the same mechanism (C3's open speed question).
- **Draft and production.** The spring's grid and the plate's mode count are draft
  levers, measured against production like the draft's other levers
  (`scripts/draft_settings_study.py`).

## Ground rules

CLAUDE.md's hard rules hold: every value has a `source` (a tank's sheet, a paper's
measured spring, or `provisional:` and genome-bounded); the genome is physical only;
seeded and reproducible; loudness-matched listening (decision 3 replaces SPICE for the
media only). Additionally:

- **Accuracy is analog behaviour** (memory): judged on the chirp structure (group delay
  against frequency), echo density, decay against frequency, the driver's distortion
  and aliasing, against the tank's specs and published measured impulse responses, not
  on waveform identity with any one recording.
- **Model changes are new versions.** A tank or plate refit lands as a new component
  version; circuits pin theirs.

## Milestones

**E1. The spring medium (Python reference).** The helical-spring scheme from the
spring's geometry and material (wire radius, coil radius, pitch, length, density,
Young's and shear moduli, losses), standalone: a force in at one end, the motion read at
the other. *Done when:* the scheme's numerical dispersion matches the continuous
dispersion relation within a stated tolerance across the audio band; the lossless
scheme conserves its energy to rounding and the lossy one only loses it; the impulse
response shows the echo train at the round-trip time and the chirps, plotted as a
spectrogram with the theoretical group delay over it (`reports/reverb/`); a spring with a
published geometry and measurement (Sources) reproduces its transition frequency and echo
spacing within a stated tolerance.

**E2. The medium in circuitsim, one-way.** The IR element (Python `ir.py`, `ir.rs`, the
builders in both languages: a `spring_tank` macro with ports `[in_plus, in_minus,
out_plus, out_minus]` naming a component version), the medium stepped after each solve.
*Done when:* circuitsim and the Python reference agree on E1's springs within a stated
tolerance; the IR round-trips; `export_circuit_fixtures.py --golden` and the app fixtures
show no diff for existing circuits; the step's cost is measured
(`examples/load_profile.rs`).

**E3. The transducers and a whole tank.** The input transducer (coil, pole piece, a
magnet turning on the spring's end) and the output transducer, lumped in the netlist,
coupled to the medium's ends; 2-3 springs per tank. A first tank component (an
Accutronics type 4, the 6G15's kind), its coil impedances from the published part code,
its spring geometry from a paper's measurements or provisional and genome-bounded.
*Done when:* the input impedance against frequency and the output level at a stated drive
match the tank's published figures within stated tolerances; the decay time is in the
tank's published class; the back-reaction (how much the spring's motion changes the
drive coil's current, and the pickup's load on the spring) is measured, deciding how much
E5 matters for tanks.

**E4. The Fender 6G15 reverb unit.** The 1961 standalone reverb: an input stage, a
driver pentode into a transformer into the tank, a recovery stage, Dwell / Mixer / Tone
(the tube line-up checked against the schematic when started; new device files, e.g. the
12AT7 and the 6K6GT, fitted to their sheets as versions). Its circuit file, drawing,
measurement profile (decay and spectrogram per Dwell, the driver's THD per Dwell, wet /
dry, hiss and hum at the output once B5's noise sources are in), and a Play device in
varimu-app. *Done when:* it idles within +-20% of published voltages (as the 5E3); the
profile's figures are in its report; the 5E3's guitar take and a tube synth take are
rendered through it (offline chaining: a render into a render), and the user listens.

**E5. Two-way coupling.** The companion-port coupling in circuitsim; the speaker's
readout moved onto it. *Done when:* a tank with two-way coupling equals a monolithic
reference (the Python reference solving the circuit and the medium's states together,
slow) within a stated tolerance; the 5E3's Play load through the speaker is measured
before and after (C3's numbers: 1.61x at draft-2x).

**E6. The plate medium.** Modal synthesis of a tensioned rectangular plate from its
dimensions, steel and tension; damping per mode from physics, including the damper
plate's distance; the moving-coil exciter and the pickups; Python reference and a SIMD
bank in circuitsim. *Done when:* mode frequencies match the closed form; decay time
against damper distance and frequency matches the EMT 140's published figures within
stated tolerances (or, without published curves, the physics' prediction, provisional);
the cost is measured, and whether it plays in real time is known.

**E7. A plate device.** The EMT 140 if its tube-era electronics' schematic can be
sourced; otherwise a plate driven by electronics we have, or a plate in the tube synth
(whichever the user picks then).

## Open decisions (the user's)

- **Where the track goes in the order.** Parked until the user asks (2026-10-30). Open
  next to it: B5 noise, C3 (paused), the synth's S4 / S5, B10.
- **Live chaining in the app.** E4 chains offline (a render into a render). Playing a
  synth live through a reverb live needs two devices on one stream; the partition's
  one-sample coupling is a ready mechanism. Brought with numbers when E4 is done.
- **A tank in the tube synth.** A spring tank on the voice's output fits
  TUBE_SYNTH_PLAN.md's spirit (the ARP 2600 had one); that track's order decides.
- **The tank's crash** (nonlinear contact), and temperature drift of spring and plate
  tension (the synth's "drift as character"): after E4, as options.

## Sources (to verify when started)

- S. Bilbao, J. Parker, "A virtual model of spring reverberation", IEEE Transactions on
  Audio, Speech, and Language Processing 18(4), 2010.
- J. Parker, S. Bilbao, "Spring reverberation: a physical perspective", DAFx-09, 2009.
- W. H. Wittrick, "On elastic wave propagation in helical springs", International
  Journal of Mechanical Sciences 8, 1966.
- J. S. Abel, D. P. Berners, S. Costello, J. O. Smith, "Spring reverb emulation using
  dispersive allpass filters in a waveguide structure", AES 121st Convention, 2006, and
  V. Valimaki, J. Parker, J. S. Abel, "Parametric spring reverberation effect", JAES
  58(7/8), 2010: signal models, for comparison of measured responses, not our approach.
- S. Bilbao, "A digital plate reverberation algorithm", JAES 55(3), 2007.
- K. Arcas, A. Chaigne, "On the quality of plate reverberation", Applied Acoustics 71,
  2010.
- S. Bilbao, *Numerical Sound Synthesis*, Wiley, 2009 (finite-difference schemes for
  bars, springs and plates).
- Accutronics / Belton tank specifications and part-number code; the Fender 6G15
  schematic; EMT 140 documentation: to be located when E3, E4 and E6 start.
