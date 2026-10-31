# Reverb: springs and plates as coupled physical media

Drafted 2026-10-30 with the user, after asking where old analog reverbs (spring, plate)
would fit what we've built, in keeping with the physical simulation. **Picked up
2026-10-30 (the user): the reverb is first used as a printed send in the Session view
([SESSION_FX_PLAN.md](SESSION_FX_PLAN.md)), and the plate goes first** (below, "The
session's reverb"). It
is its own track next to [DEVICE_BUILDER_PLAN.md](DEVICE_BUILDER_PLAN.md),
[COMPONENT_EDITOR_PLAN.md](COMPONENT_EDITOR_PLAN.md) and
[TUBE_SYNTH_PLAN.md](TUBE_SYNTH_PLAN.md). When started, work milestones in order, each
ending with its "done when" met and covered by tests, like the other plans. It is the
first user of the "spatial medium" block that [FUTURE_DIRECTIONS.md](FUTURE_DIRECTIONS.md)
reserves for tape and vinyl, and where [DEVICE_CANDIDATES.md](DEVICE_CANDIDATES.md) sends
the EMT 140 and spring tanks.

## Decisions (2026-10-30, the user's, taking Claude's recommendations)

1. **~~Spring first, plate after.~~ Plate first, spring after (revised 2026-10-30).**
   The spring went first for being cheap enough for real time. The reverb's first use is
   now a send printed offline in the session, where real time doesn't decide, and the
   plate is the mix's reverb. The spring (the 6G15) follows for guitar and synth.
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

## The session's reverb: the plate first (2026-10-30)

The user's decision, taking Claude's recommendation (SESSION_FX_PLAN.md decision 1):

- **Why the plate.** The reverb is used as a send printed in the background
  (SESSION_FX_PLAN.md F4), so real-time cost no longer orders the media. The plate is the
  studio's reverb for a mix. Its modes have closed forms to check against, so it is the
  surer way to a first sound. The modes are independent, so a print spreads over every
  core.
- **The order of the milestones becomes:** E6 (the plate medium), E2 (the medium in
  circuitsim, one-way, for the plate's modes), E7 (a plate device), and then E1, E3, E4
  (the spring and the 6G15) and E5.
- **The electronics are ours.** The EMT 140's tube amplifier, the V54, has a schematic
  only for sale ($9.99 at Dan Alexander Audio, with a request not to repost), and its
  tube line-up isn't published. E7's fallback applies: a driver and a pickup preamp
  designed from the tubes and transformers we have, with values sourced or provisional
  (memory: "analog magic, not a clone"). Buying the V54 sheet is the user's call.
- **A linear medium is an impulse response.** With one-way coupling the plate between
  the exciter's force and a pickup's motion is linear and time-invariant. A print can
  convolve with the impulse response computed from the modes (FFT, partitioned), exact
  to rounding and much cheaper than stepping 26,000 resonators. A test checks the two
  forms against each other. The stepped form stays for anything time-varying (tension
  drift, the damper moving during a take).

### What the sources give (research 2026-10-30; to cite per value when E6 starts)

- **The plate.** 2 m x 1 m, 0.5 mm steel (Russo, MSc thesis, Aalborg 2021, §1.1.1,
  https://projekter.aau.dk/projekter/files/517547034/Master_Thesis_Russo.pdf; Ducceschi &
  Webb, ICA 2016, https://mdphys.org/PDF/icaPLA_2016.pdf; Bilbao, DAFx-10 chapter
  "Electromechanical effects", https://ccrma.stanford.edu/~bilbao/dafx10/electro.pdf).
  Steel as modelled there: E 200 GPa, nu 0.3, rho 7850-7872 kg/m^3 (Russo §6.1: SAE 1010).
  Hung by wires at the corners in a tubular frame (EMT 140 TS brochure, 1971, p.4,
  https://www.barryrudolph.com/recall/manuals/emt140ts.pdf).
- **Tension: not published.** Ducceschi & Webb model 600 (N/m, our reading). Provisional
  and genome-bounded; it mostly moves the low modes.
- **Decay (the anchors for E6's done-when).** The brochure (p.8): 1-4 s at 500 Hz with the
  damper. Its p.2 plot of decay against frequency per damper setting: undamped about
  5 s at 500 Hz, about 1.5 s at 10 kHz, rising towards the bass (about 10 s near 50 Hz
  on the 4.5 s curve), and curves for 2 s and 1 s. The damper is a porous plate swung
  parallel to the steel one, about 1/8 inch at its closest (brochure p.4); Russo gives
  11-66 mm.
- **Losses (Arcas & Chaigne 2010, as Russo §3 reproduces them):**
  - thermoelastic loss, with SAE 1010's constants R1 9.664e-3 and C1 0.1855e-3, near
    its high-frequency limit (about 3.6 1/s) above 500 Hz;
  - radiation, weak in the audio band (the critical frequency is about 25 kHz);
  - the porous damper as a function of distance (Cummings' model): at 11 mm about
    2.3 1/s near 100 Hz falling to 0.2 1/s at 10 kHz, at 65.8 mm under 0.4 1/s;
  - support losses, not modelled.
  - Decay rate and T60: sigma = 6 ln 10 / T60.
- **Transducers.** A moving-coil exciter on the middle of three bridges across the frame,
  and two ceramic contact pickups at unequal distances on either side (the stereo pair:
  their outputs are decorrelated; brochure pp.3-6). The coil's impedance and the
  positions aren't published; Ducceschi & Webb's model puts the input at (0.52, 0.53)
  and an output at (0.47, 0.62) of the sides.
- **Modes and cost.** About 1.3 modes per Hz (our estimate from the plate's stiffness,
  consistent with a 1.27 quoted in a ResearchGate snippet that we couldn't read), so
  about 26,000 below 20 kHz. Ducceschi & Webb step about 10,000 modes at 44.1 kHz in
  1.1 s per second of output on one core (double precision; 0.7 s single). At 96 kHz
  with 26,000 modes that is roughly 6x real time on one core, so under real time across
  this desktop's cores, and far less as a convolution.
- **The transistor 140 TS** (1971, its EMT 162 amplifier) had a compressor in the drive
  path against overload, and noise -50 dB unweighted at T 2 s (brochure p.8): a
  reference for our driver's headroom and the preamp's hiss.

### Status (2026-10-31): the plate built (E6, E2 for the plate, E7)

The user's ask: a reverb to put on recorded tracks in the Session view. Built in one go:

- **The damping, decided on the way.** The sources' loss formulas (Russo 2021, Arcas &
  Chaigne 2010) don't reproduce the EMT's measured decay: within ~20% up to 1 kHz, ~2x too
  long at 10 kHz (`reports/reverb/plate_losses.png`, `plate_summary.json`). The sources
  also write the rates as energy decay rates (T60 = 6 ln 10 / sigma) inside an equation that
  makes them amplitude rates; read as energy rates (amplitude decays at half), thermoelastic
  loss alone gives 4.0 s at 500 Hz against the brochure's 4.8. So the plate's modes come
  from physics (dimensions, steel, tension, positions), and each mode's decay from the
  EMT's own measured curves: the 1971 brochure's reverberation time against frequency for
  three damper settings, digitized (`scripts/digitize_emt140.py` ->
  `data/datasheets/emt_140ts_decay.csv`, provenance `emt_140ts.provenance.yaml`). DECAY
  sets the damper as the decay at 500 Hz (the EMT's remote scale), interpolating between
  the curves. The formulas stay as the report's cross-check. Hardly a model change to
  bring as options: no plate existed before.
- **E6, the plate medium.** `varimu/devices/plate.py` (the reference: modes in closed form,
  a point force in, the acceleration at the pickup out (the EMT's pickups are
  accelerometers), impulse invariance, each mode summed to -90 dB) and circuitsim's
  `plate.rs` (the same, in fixed time segments on every core, bit for bit the same on any
  thread count; a cache of responses). About 26,000 modes below 20 kHz (1.31 per Hz,
  Russo's 1.3). Agree within 1e-8 (`tests/test_plate.py`); Rust tests check the closed form,
  the modal density and the response against a direct modal sum.
- **E2, the medium in the engine, one-way.** An IR element `Plate` (both IRs; SPICE holds
  its pickup at 0 V: the medium cut out at its ports): it senses the exciter coil's current
  across its resistance after each sample and drives its pickup node one sample later, the
  force convolved with the response (`circuitsim::convolve`: zero latency, strictly causal,
  a direct head of B taps and FFT-partitioned blocks, B 256 at 48 kHz). The pickup rides on
  the externals after the control inputs (`Mna::n_media`, `Transient::step_media`); a
  whole run, a stream (bit for bit) and a partitioned run agree (`crates/circuitsim/tests/
  plate.rs`). A new response (DECAY turned) takes over the force while the old one rings
  out; the app's builder thread computes it first (`plate::prepare`), off the audio thread.
  The plate's load on the coil is a resistor, an infinite plate's driving-point impedance
  8 sqrt(D rho H) times BL^2 (cheap two-way coupling where it matters).
- **The component** `EMT140@1` (`varimu fit-devices --only EMT140`): the plate (Russo's 2 m
  x 1 m x 0.5 mm SAE 1010), tension 600 N/m and the positions provisional (Ducceschi &
  Webb's model values), the exciter (6 ohm, 0.3 mH, BL 2.5) and pickups (5 mV per m/s^2,
  1 nF) provisional, the decay curves digitized. The `plate` part in both builders
  (`[plus, minus, out]`, component, decay_500hz_s); symbols for the editors.
- **E7, a plate device:** `config/circuits/plate_reverb.yaml`, our own electronics (the V54
  has no public schematic): DRIVE into a 12AX7 stage, the 5E3's cathodyne, 6V6GT pair,
  output transformer and supply, the plate, then a 10 MOhm 12AU7 pickup amplifier on its
  own decoupled supply (B+3's ripple came through at first; now ~-120 dBFS), RETURN, a
  12AU7 cathode follower. Output wet only. The app's `plate_reverb` device (DRIVE, DECAY,
  RETURN).
- **Measured** (`scripts/plate_report.py` -> `reports/reverb/`): the device's impulse
  response per octave band follows the EMT curves at DECAY 1, 2, 2.5 and 4.5 s, mostly
  within 10% (worst 17%, 500 Hz at DECAY 2; the curves' interpolation between settings is
  coarse there); hum 0.012-0.021 mV rms at the output. Prints at draft-1x run at ~0.6x real
  time; live, 0.55x mean load (`examples/load_profile.rs`), so it can be auditioned.
- **Not yet:** the stereo pair (the EMT's two pickups: a two-channel print), the user's
  listening, the exciter's and pickups' real figures (genome bounds), production renders'
  cost (the response at 192 kHz), sends (SESSION_FX_PLAN.md F4).

### The spring, for later (same research)

- Accutronics / Belton Type 4 part code (Belton's "Part Numbering Specifications",
  https://www.tubetown.net/ttstore/media/products/Part%20Numbering%20Specifications%20Reverb%201%20and%204.pdf):
  4AB3C1B = 8 Ohm in, 2250 Ohm out, long decay (2.75-4.0 s), input insulated, output
  grounded, horizontal open side down: the 6G15's usual tank. Coil data (measured, Rod
  Elliott, https://sound-au.com/articles/reverb.htm): input A 0.81 Ohm DC, 1.27 mH;
  output B 200 Ohm DC, 270 mH.
- Spring geometry (Parker & Bilbao, DAFx-09, Tables 1-2): wire 0.35 mm, helix 4.4-6.1
  mm, 133-351 turns; with their formulas, delays of 34-51 ms and transition frequencies
  of 2.6-5 kHz.
- Fender 6G15: 12AT7, 6K6GT driver into a 125A12A (about 7.5 kOhm : 8 Ohm), 7025 recovery
  and cathode-follower mixer, solid-state rectifier; voltages on the schematic
  (https://www.thetubestore.com/lib/thetubestore/schematics/Fender/Fender-Reverb-6G15-Schematic.pdf).

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

- **~~Where the track goes in the order.~~** Picked up 2026-10-30 (the user), the plate
  first, its first use the session's sends (SESSION_FX_PLAN.md).
- **Stereo returns.** The EMT 140's two pickups make a stereo pair. Devices and prints
  are mono today: a plate device with two outputs means a print with two channels and an
  FX track with a stereo return. Recommended: one pickup first (mono, panned), the pair
  right after E7.
- **~~Live chaining in the app.~~** Built 2026-10-31 (the user's call: a device that goes
  at a chain's end, the Play view as the debug window): `player::EndDevice` /
  `Player::set_end`, a second device on a thread of its own (its partitions on theirs),
  fed the device's monitored output a block (10 ms) behind, so the two compute side by
  side; no sample coupling (a reverb's input is a grid). `panel::CHAIN_ENDS` lists the
  devices that can go there (the plate; the 670 and the EQP-1A would fit). Play's CHAIN
  END section (device, mix, its knobs); `examples/play.rs --end ID`. Measured: tube_synth
  with a key held, 30 s at a 30 ms buffer, 0 dropouts, the synth's load ~70% mean (65%
  alone), the plate's thread ~50% mean (worst block 94%).
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
- EMT 140 TS brochure (EMT, April 1971):
  https://www.barryrudolph.com/recall/manuals/emt140ts.pdf.
- F. Russo, *Plate reverberation* (MSc thesis, Aalborg University, 2021):
  https://projekter.aau.dk/projekter/files/517547034/Master_Thesis_Russo.pdf.
- M. Ducceschi, C. Webb, a plate reverberation model, ICA 2016, paper 559 (title to
  copy from the PDF): https://mdphys.org/PDF/icaPLA_2016.pdf.
- S. Bilbao, "Electromechanical effects", DAFx-10 chapter:
  https://ccrma.stanford.edu/~bilbao/dafx10/electro.pdf.
- Accutronics / Belton tank specifications and part-number code; the Fender 6G15
  schematic; EMT 140 documentation: to be located when E3, E4 and E6 start.
