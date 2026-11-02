# Drums: real drums, old drum machines and tube drum voices, from physics

Drafted 2026-11-01 from a brainstorm with the user, after the tube kick
(`config/circuits/tube_kick.yaml`, TUBE_SYNTH_PLAN.md). The user picked drums up the same
day (the `drums` worktree, beside the synth's ADSR session): D1's first test is built
(Status below). The order below is a recommendation; which family goes first is the
user's call (Open decisions).

## Status (2026-11-01)

**D1's first test: a struck head, offline, Python only** (`varimu/drums/membrane.py`,
`config/drums/{tom_13,kick_22}.yaml`, `scripts/drum_study.py` -> `reports/drums/<drum>/bare/` (since the body step):
`study.png`, `summary.json`, WAVs in `audio/` with a `sweep.wav` per drum, soft to hard and
the hardest without its glide; `tests/test_membrane.py`). Outside the render cache key;
nothing in circuitsim, the IR or the app.

- **What it is:** one circular Mylar head in vacuo (no shell, no second head, no air
  load): its modes from the Bessel zeros (cos twins only: strike and mic on one line); a
  beater as a mass on a Hunt-Crossley power-law contact over its face's disk, solved
  implicitly per step (explicit blew up: a stick's 4 mm patch sees ~no head mass);
  tension modulation as one shared T(t) = T0 + E h / (4 A (1 - nu)) sum lambda_k q_k^2
  (uniform strain, Berger's averaging); losses per mode = radiation of a baffled head (the
  Rayleigh far field over the hemisphere) + the film's eta = 0.015 (provisional); the
  pressure at 1 m, 30 deg off axis (the Rayleigh far field per mode at its own frequency).
  Mylar's density, modulus and Poisson ratio are DuPont Teijin's (sources in the YAMLs);
  the beaters, the tunings and eta are provisional.
- **Checks that pass:** the Bessel ratios (1.594, 2.136, 2.296), orthonormal modes, the
  monopole limit of the radiation damping, a free mode's frequency (2e-4) and decay, the
  Duffing shift tension modulation predicts (3%); in a soft hit's spectrum the ten
  strongest modes sit within 0.5% of their predictions.
- **Speed:** 2.4x (tom, 1599 modes to 6 kHz) and 3.4x (kick, 3314 modes to 4 kHz) slower
  than real time in a numpy per-sample loop; ~8 / 19 s of set-up (the radiation integrals).
- **Levels:** a 4 m/s tom stroke peaks at 116.5 dB SPL at 1 m, a 4 m/s kick at 125 dB.
- **Contact:** stick on the tom 7-9 ms with the stick's effective mass at its tip (11 g:
  a rod pivoting at the fulcrum); measured 5-8 ms for a mezzoforte tom or snare stroke
  (Dahl's review, web: https://vbn.aau.dk/ws/files/65339564/Dahl_J_AST_review_submi.pdf),
  3-6 ms (Wagner, KTH 2006, web:
  https://www.speech.kth.se/publications/masterprojects/2006/AndreasWagner.pdf). With
  20 g it was 9-11.5 ms: the stick outweighs the head's ~9 g effective (0,1) mass at the
  strike point and rides it down and back. The felt kick beater: 14-21 ms (no data yet).
- **The glide:** under the pressing beater the head stretches a lot (tom +27% at 4 m/s);
  the free head starts +8% above its tuning at ~4 m/s, Rossing's figure for a hard blow on
  a 33 cm tom (Springer Handbook of Systematic Musicology 2018, ch. 9, web:
  https://doi.org/10.1007/978-3-662-55004-5_9). **But it halves within a few ms** (+0.3%
  50 ms on), where Rossing's lasts ~0.2 s: the head loses its energy too fast. A baffled
  head radiates its (0,1) mode as a monopole (T60 0.22 s, 82% of it radiation); a real tom
  radiates from a shell with a second head or an open bottom, and its air couples the
  heads. The kick keeps more (+4% 50 ms on at 4 m/s: its (1,1) mode rings 1.5 s).
- **The audio check of the glide** (the (0,1) band's phase slope) agrees only while the
  (0,1) mode dominates; after that the (1,1) mode leaks in (~1% bias at 50 ms on the tom,
  noise on the kick). The tension's glide is exact by construction; the audio read is a
  cross-check only.

The user listened (2026-11-01): "pretty fake so far", as expected of a bare head in vacuo.

**D1's second step: the drum body** (`varimu/drums/drum.py`, `tests/test_drum.py`; each
drum file's `resonant` and `body` blocks; the study's `drum` part, `reports/drums/<drum>/
drum/`, the bare head moved to `bare/`; both printed through the EMT 140's plate for
listening, `sweep_plate.wav`: the plate's Python reference response, mixed in, not the
plate_reverb circuit).

- **What it is:** both heads on a rigid cylindrical shell, per azimuthal order one
  symmetric system `M x'' + K x = f` solved for its normal modes once:
  - the cavity's air as its rigid-wall modes: the uniform one a static air spring;
    those below a cut oscillators; the rest added mass, summed over the axial order
    in closed form (coth / sinh);
  - the outside air as a baffled head's incompressible added mass (Hankel transforms;
    a piston's 8/3 rho0 a^3 to 1e-8);
  - radiation per normal mode from both heads as monopole layers in free space, so a
    drum whose heads move together is a dipole of the shell's length and rings long;
  - the film's loss weighted by each head's share of the stiffness.
- **The coupled range and the local modes:** below `f_coupled_hz` (tom 3 kHz, kick
  1.6 kHz) both heads and the air are solved as one coupled system. Above it each head's
  modes stand alone, with the air's mass on their diagonal. The heads are subsonic, so
  the near field is local, and across the shell it dies as 1/sinh(qL). Moving the tom's
  cut from 1.5 to 3 kHz changes a 5 m/s hit by -28 dB re signal; the kick's from 0.8 to
  1.6 kHz by -19 dB; the glide is identical to the digit in both.
- **Tension modulation is exact through a sparse G_h:** a hit's tension acts through
  `G_h = V_h^T diag(lambda) V_h` per head. A diagonal approximation was tried first and
  failed: heads tuned alike make every normal mode half batter, half resonant, so it
  put half the stretch on the resonant head at once. Only the pairs' cross terms keep
  it on the batter. The sparse G (G_TOL 1e-4) matches the dense one within 1e-4 rms.
- **Checks that pass:**
  - in a near vacuum the heads keep their in-vacuo modes;
  - the cavity's cut doesn't move the low modes (0.5%);
  - the air splits the lowest mode: heads together below the in-vacuo frequency,
    breathing above, as Rossing describes for two-headed drums;
  - the far field equals brute-force quadrature over both heads (1e-6);
  - a compact drum's breathing mode radiates as a monopole (2%; its stiff air spring
    cancels most of its volume, so the r^2 term shows);
  - a strike stretches the batter more than the resonant head.
- **The tom (13 x 9, both heads at 120 Hz in vacuo):**
  - The (0,1) mode splits into a 91 Hz mode with the heads moving together, a dipole
    (T60 1.6 s, 2% of it radiation), and a 196 Hz breathing mode, a monopole (T60
    0.30 s, 76% radiation).
  - The (1,1) pair falls from 191 to 158 / 162 Hz under the air's mass.
  - The attack is the 196 Hz mode and its overtones; the tail is the 91 Hz mode.
  - The glide (the 196 Hz mode, from the tension) at 6 m/s: +6.2% at the end of
    contact, +2.6% 50 ms on, +0.7% 200 ms on. That's Rossing's ~0.2 s timescale; the
    bare head lost it in a few ms. His 8% would need ~7 m/s.
  - Contact 6-8 ms (measured 5-8 ms at mezzoforte).
  - 114 dB SPL peak at 1 m at 6 m/s, 9 dB below the bare head: free space, not a
    baffle, and the heads' volumes partly cancel.
  - 9-11x slower than real time, 3643 normal modes, 56 s to prepare.
- **The kick (22 x 16, both heads at 55 Hz in vacuo, no port, no muffling):**
  - The fundamental is 36.4 Hz, the heads moving together with the long air column's
    mass on them, T60 4.0 s. Then the (1,1) pair at 66 / 68 Hz (T60 2.2 s) and the
    breathing mode at 94 Hz.
  - The glide at 4 m/s: +18% at the end of contact, +12% 50 ms on, +8.7% 200 ms on:
    a long, deep pitch drop, as an undamped kick has.
  - Contact 11-18 ms (felt; no data yet).
  - 13-14x slower than real time, 7644 normal modes, 111 s to prepare.
- **Speed in Rust (an estimate, not measured):** the per-sample work is a few multiply-adds
  per mode plus two sparse products (tom ~17k, kick ~25k nonzeros per head); Python's
  per-call overhead dominates today. Compiled, the tom should run near or under real
  time on one core and the kick ~1-2x before pruning the modes the mic barely hears
  (many m >= 2 modes are 40+ dB down), running at 48 kHz, SIMD and a thread per group
  of orders. The set-up (eigen-solves, the air's integrals) reruns when a physical value
  changes: a live tuning knob needs it cached or fast.

**Next for D1 (after the user listens to `drum/audio/sweep_plate.wav`):**
- damping as physical controls: a felt strip, a pillow, a port in the kick's front head;
  real kicks are rarely undamped;
- the shell's own modes;
- the beater's felt from data;
- comparing with recordings (Kirby & Sandler's tom at 67 strike strengths);
- the Rust port (a modal medium with nonlinear ports, per-mode states: the plate's
  `Plate` is an LTI impulse response).

**D2's sources (the Wurlitzer Sideman, found 2026-11-01; nothing built):**
- The Model 5000's service manual (MusicParts #51329, 2006, issue of 5/1/60, serial
  320000 on: generator schematic 501648, amplifier 501649, rhythm switching; values mostly
  legible), web:
  https://www.smemmusic.ch/sites/default/files/2025-12/wurlitzer_side-man_service_manual.pdf.
  It is a commercial document: cite it, don't copy it into the repo.
- The patents: US 3,358,069 (the tone generators, with values and frequencies; web:
  https://patents.google.com/patent/US3358069) and US 3,207,835 (the commutator, the
  friction tempo drive, the pattern switching; web:
  https://patents.google.com/patent/US3207835).
- What they show (read through a summarizing fetch, so check against the scans):
  - The tuned voices are keyed damped oscillators on 12AX7 halves, kicked out of
    cut-off on a -22 V line: bass drum ~65 Hz, toms ~120 / 180 Hz, temple blocks
    600 / 900, wood block 1200, clave 2000. Each has a 5k cathode pot for its ring time.
  - Noise comes from a 6C4 super-regenerative source at ~27 MHz.
  - Maracas and brush are 12AX7 gates; the cymbal is a 6BA6.
  - A ~17 Hz "shimmer" oscillator sweeps a 100 mH / 0.0043 uF formant through a diode.
  - The output stage is a 6AV6 preamp, a 12AX7, push-pull 6BQ5s and three speakers.
  - Tempo is set by a rubber wheel on a tempo disc (36-195 bpm). There is no governor,
    and the motor itself isn't specified.
- Audio of a restored 1959 unit exists (Circles Drum Samples; a Vimeo video,
  https://vimeo.com/509979954). No published measurements were found.

## The frame

Every drum is **exciter -> resonator -> radiator -> chain**. The three families the user
named model different parts of that chain:

- **Old drum machines are circuits.** The netlist and the device builder take them as they
  are.
- **Real drums are a mechanical medium coupled at ports.** That is the plate reverb's
  architecture (`plate.rs`: modes worked out from dimensions and material, driven and read
  through transducer ports, `Mna::n_media`). A drumhead is a plate with tension.
- **Tube drum voices** generalize the tube kick: resonators struck by pulses.

Most of the old-school warmth of drum recordings comes from the **chain**: a ribbon or
dynamic mic, a tube preamp, a compressor, a plate, tape. Most of that is built (the 670,
the plate, tape TM1-TM4, rooms in the separation plan). What's missing is the instrument.

The project's rules apply as everywhere: physical values only, each with a source; one
coupled simulation; pure physics by default, with an exception
(HYBRID_PHYSICS_PLAN.md) only where the numbers show the physics is too fast for the
grid.

## A. Real drums

The physics is mostly linear and cheap. The character comes from a few nonlinear spots.

| Part | Physics | Cost (estimate) |
|---|---|---|
| Drumhead | Circular membrane modes (Bessel zeros) under tension; Mylar density, thickness (7-10 mil heads) and tension as physical values | Linear, modal like the plate |
| Two heads and the shell's air | Batter and resonant heads coupled through the enclosed air; this sets a tom's pitch and decay | Linear, a few coupled modes |
| **Tension modulation** | A hard hit stretches the head: tension and pitch rise, then fall as it decays. This is the real pitch drop the tube kick couldn't get from core saturation (TUBE_SYNTH_PLAN.md, the kick's prototypes) | Mildly nonlinear, cheap |
| Beater or stick contact | A nonlinear contact force (felt, plastic, wood), the same physics as a piano hammer; the beater is a physical choice, not a tone knob | An event of a few ms |
| Shell | The shell's own modes (wood species, ply, depth), lightly coupled | Linear |
| **Snare wires** | Collisions of the wires against the resonant head: the buzz | Hard: a hybrid-physics exception (contact) |
| **Cymbals** | Plate modes with large-deflection (von Karman) nonlinearity: energy cascades upward, so the shimmer builds after the strike | The CPU monster: render (print) first |
| Radiation | Pressure at a mic position, like the speaker's readout (the `Vccs` element, C3) | Built |

**A kit is one coupled simulation.** A kick hit makes the snare wires buzz
sympathetically; toms ring when the snare is hit. Sample libraries struggle with this. It
falls out if the kit shares one medium and one room, at the cost of simulating the voices
together rather than apart.

**Sources to start from:** Fletcher & Rossing, *The Physics of Musical Instruments*;
Rossing, *Science of Percussion Instruments*; Bilbao, *Numerical Sound Synthesis* (2009),
and the NESS project's snare-drum and cymbal work (Bilbao, Torin, Ducceschi). Head
materials and drum dimensions are public. Decay data for individual modes, if measured
curves can be found, play the role the EMT 140 brochure played for the plate.

## B. Old drum machines

- **Wurlitzer Sideman (1959): the best fit for this project.** Tube voices triggered by a
  motor-driven rotating commutator. Tubes need no new device model; the motor's speed
  wander reuses TM3's transport model (`TapeMachineSpec.transport`); contact bounce is a
  hybrid-physics event. Service documentation is believed to circulate online (to be
  searched; provisional: model knowledge).
- **Rhythm Ace FR-1, Maestro Rhythm King, Roland CR-78:** germanium and early silicon
  transistors. Germanium leakage drifting with temperature is drift as character (B6's
  thermal lags carry over).
- **Roland TR-808:**
  - Bass drum: a bridged-T resonator pinged by the trigger, its pitch bend from the pulse
    shifting the resonator while the pulse is still present.
  - Snare and other noise: a reverse-biased transistor junction, i.e. avalanche noise, a
    new noise source next to B5's.
  - Hats and cymbals: six detuned Schmitt-trigger square oscillators through band-passes.
    Hard edges: likely hybrid-physics exceptions.
- **TR-909:** a hybrid with some sampled voices. Less interesting here.

**The gate:** everything after the Sideman needs a **BJT model** (Gummel-Poon). SPICE has
one natively, so the two-implementation rule needs a Python reference, circuitsim's port
and fits to datasheets (a germanium part first). The same model opens guitar pedals later.

## C. A tube drum synth (extending `tube_kick`)

- **Toms:** reactor-tuned tanks with glide (SYNTH_IDEAS #1's mechanism).
- **Snare:** amplified tube noise (SYNTH_IDEAS #11) through a tank and a gate.
- **Hats and cymbals:** a cluster of detuned gas-tube relaxation oscillators (SYNTH_IDEAS
  #23, HYBRID_PHYSICS_PLAN.md H1-H5), ring-modulated by a diode ring between transformers
  or a pentagrid.
- **Clap:** a thyratron firing a few times in a burst, then a spring tail (the 6G15,
  REVERB_PLAN.md).
- **All voices on shared rails:** an invented machine in the synth's spirit, where a kick
  hit ducks the hats through the supply's sag.

## What exists and what's new

**Reusable:** the modal medium (`plate.rs`, `Mna::n_media`, `Transient::step_media`); the
pressure readout (`Vccs`); B5 noise; B6 heaters and thermal lags; hybrid-physics
exceptions (collisions, contacts, Schmitt edges); TM3's transport; rooms from the
separation plan; recording (takes as events, so drums re-render at production,
RECORDING_PLAN.md); session inserts and prints (SESSION_FX_PLAN.md); the keyboard and MIDI
input (`varimu-app`'s `midi`).

**New:** membrane and shell modes with air coupling; contact and collision kernels;
tension modulation; a BJT model; avalanche noise; eventually a mic model (a ribbon mic is
a ribbon in a magnetic gap feeding a transformer, which the project is well set up for).

## Proposed order (a recommendation, not decided)

1. **D1: one real drum as a medium**, a kick or a floor tom: heads, the enclosed air,
   tension modulation, a felt beater, the radiated pressure. It reuses the plate's
   machinery most directly, gets the pitch drop from physics, and feeds the chain that's
   built. Linear modes plus two cheap nonlinearities should play in real time (to be
   measured). Done when (draft): it plays from keys or pads, its modes match published
   membrane ratios with air loading, and a hard hit's pitch drop is measured against a
   published or recorded figure.
2. **D2: the Wurlitzer Sideman.** A vintage machine with no new device model: tubes plus a
   motor. Starts with finding its schematic.
3. **D3: the BJT model**, then the TR-808 and the CR-78 (and avalanche noise).
4. **D4: snare wires and cymbals**, where hybrid-physics exceptions and render-first
   quality earn their keep; then the kit as one coupled medium.
5. **Later:** the tube drum synth (C) as an invented machine, and mic models.

## Open decisions (the user's)

- Which family first (the order above is a recommendation).
- Must drums play live from pads or keys from day one, or is printing fine for the
  expensive parts, as with tape?
- The kit as one coupled medium (sympathetic buzz, more CPU) or voice by voice first.
- Where the track goes relative to the synth, tape, reverbs and the session work.
