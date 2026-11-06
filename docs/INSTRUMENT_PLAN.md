# Acoustic and electromechanical instruments from physics

Drafted 2026-11-01 from a conversation with the user ("what's feasible in physical modeling
of real instruments: a pipe organ, a piano, a large church bell, an electric piano; I want
to go deep into simulating the physics"). Nothing in it is built. It is parked until the
user picks it up. The order below is a recommendation; the open decisions are the user's.

## The frame

Almost every instrument splits into the same four parts, and the project already has most
of the machinery for each:

| Part | Physics | Cost | What exists |
|---|---|---|---|
| **Exciter** (hammer, clapper, jet, reed) | Nonlinear and local: a few unknowns per sample | Cheap | Device ports and Newton (`dk.rs`); hysteresis (JA, Preisach) |
| **Resonator** (string, soundboard, bell shell, air column) | Mostly linear and large: modes or waveguides worked out from geometry and material | Offline FEM; cheap modal states at run time | The plate (`plate.rs`, `Mna::n_media`, `Transient::step_media`) |
| **Radiator** | Each mode's directivity and radiation damping | Offline (BEM); cheap at run time | The pressure readout (`Vccs`, C3) |
| **Room** | The space the instrument plays in | Offline | MIC_ROOM_PLAN.md (GPU FDTD + geometric acoustics) |

So "deep" mostly means getting the **geometry, materials and nonlinear contacts** right,
and keeping an expensive **full-physics reference** (time-domain FEM, lattice Boltzmann
CFD) to check every reduced model against: HYBRID_PHYSICS_PLAN.md's pattern, applied to
mechanics and aeroacoustics.

The project's rules apply as everywhere:
- physical values only, each with a `source` (profiles, scalings, material constants);
  felt and wood start provisional and genome-bounded;
- one coupled simulation: exciter, resonator, pickup and electronics (or wind supply) in
  one run, never chained DSP blocks;
- every device model gets a Python reference and its circuitsim counterpart, with tests
  that they agree (and SPICE where it makes sense, as for the plate: SPICE holds the medium's
  output at 0 V);
- reproducibility: per-unit variation through seeded tolerance draws;
- realistic first, then bend (the user's rule).

## Shared machinery to build

- **Geometry -> modes, offline.** An FEM pipeline from a profile or a plate description to
  mode shapes, frequencies and port participation (an axisymmetric solver for bells; plate
  and shell elements for soundboards; 1D acoustic elements for pipes). CPU reference first,
  GPU where it pays (the user's rule: use the RTX 3080, keep a CPU reference). Output is a
  component version like `EMT140@1`.
- **Modes -> radiation, offline.** Per-mode directivity and radiation damping by a boundary
  element solve, so decays come from physics where no measured curves exist. The same
  directivity feeds mic positions in MIC_ROOM_PLAN.md.
- **Contacts inside the solve.** The plate drives its pickup one sample late (a
  convolution). A hammer or clapper can't wait a sample: the contact force depends on the
  surface's displacement now. The medium needs a **driving-point term folded into the
  port** (its instantaneous response, with the rest of the modes as explicit states), so the
  contact's Newton sees the medium. Shared with DRUM_PLAN.md (beaters, sticks, snare
  wires).
- **Modes stay outside DK.** DK's cost grows with the square of its states (CLAUDE.md,
  2026-10-29: the speaker's ~80 states took the 5E3 from 0.48x to 1.61x real time).
  Thousands of modes must live in a media step like the plate's, with only the ports in
  the DK matrix.
- **Hysteretic felt.** Piano hammer felt has memory (Stulov's model: force ~ x^p with a
  relaxation term). Its fit and its Python / Rust pair follow the cores' and the tape's
  pattern.

## A. The church bell

**Why first:** the most rigorous physics for the least run-time cost, and it builds the
geometry -> FEM -> modes -> BEM pipeline the piano and the drums reuse.

- **Resonator:** a bronze (~80/20 Cu/Sn) axisymmetric shell. Published profiles exist
  (traditional minor-third bells; Lehr's FEM-designed major-third bell, Eijsbouts and TU
  Eindhoven, ~1999). An axisymmetric FEM with circumferential harmonics gives hundreds of
  modes: hum, prime, tierce, quint, nominal and up.
- **Imperfection:** a perfect bell's modes come in degenerate pairs. Casting asymmetry
  (wall thickness, inclusions) splits each pair, giving the beats and warble. Seeded
  tolerance draws on the profile make every casting a different bell.
- **Clapper:** a pendulum with Hertzian contact. Contact time (clapper mass, strike speed)
  sets the brightness. Swinging, full-circle (English change ringing) and chimed (a fixed
  bell and a hammer) are different strikes; a swinging bell also sweeps its directivity
  and gives a slow Doppler.
- **Radiation:** BEM per mode, then distance outdoors (air absorption, ground
  reflection) or a tower.
- **The strike note** is a virtual pitch, not a mode. If the modes are right it comes out
  right: a good test of the whole pipeline.
- **Cost:** real time is trivial (a few hundred modes per bell); a carillon is a few
  dozen bells.
- **Bend:** designing new profiles and hearing them before casting; a cracked bell (a
  crack as a stiffness discontinuity).

## B. Electric pianos

**Why early:** the closest to the existing stack. A few modes per voice, a field-solved
pickup, then circuits and amps the project already has.

- **Rhodes (Mk I Stage first):** expanded in [RHODES_PLAN.md](RHODES_PLAN.md) (2026-11-04:
  the target sound, why many keys at once are cheap, a live and a production tier from the
  same physics, milestones RH1-RH6).
  - Neoprene hammer tip with a nonlinear contact.
  - Tine plus tonebar as an asymmetric tuning fork: a few beam modes each, the tuning
    spring a point mass.
  - The **magnetic pickup is the character**: the tine tip moves through a nonlinear
    field, and the tine's offset from the pickup sets the even / odd balance (the "bark").
    A magnetostatic solve per pickup geometry, done once (the component editor's "field
    solvers on demand"), gives flux versus tine position.
  - The Stage is passive: pickups in series-parallel into volume and tone pots, then an
    amp. **No BJT model is needed**; the 5E3 and the P12R speaker are there.
  - Grommets (rubber mounts) as damping, a condition dial when they harden.
- **Wurlitzer 200A:**
  - Steel reeds tuned with solder weights.
  - An **electrostatic pickup**: each reed is one plate of a capacitor polarized to ~150-170
    V (provisional: model knowledge), so a capacitance that varies with reed position drives
    the circuit. A new circuit element: a mechanically driven capacitor.
  - The 200A's preamp is transistorized: it needs the **BJT model** (DRUM_PLAN.md and
    MIC_ROOM_PLAN.md list it as a shared prerequisite). Early models (the 120) are believed
    to have tube amps (provisional: model knowledge, to be checked), which would avoid it.
- **Cost:** ~10 modes per voice and a static pickup map; the amp dominates the CPU, as it
  does now.
- **Data:** service manuals give tine, tonebar and reed dimensions and pickup geometry.

## C. The piano

**Why:** the deepest instrument where real time is proven possible (Pianoteq is a real-time
physical model). It ties every shared piece together.

- **Action:** the escapement leaves the hammer in free flight when it hits, so key
  velocity maps to hammer velocity through the action's mechanics; una corda shifts the
  hammer to fewer strings.
- **Hammer:** hysteretic felt (Stulov; Giordano's and others' measurements). Voicing and
  wear are physical conditions.
- **Strings:**
  - stiffness: inharmonicity;
  - tension modulation and longitudinal waves: phantom partials (Conklin), important in the
    bass;
  - two or three slightly detuned strings per note coupled through the bridge: double decay
    and beating (Weinreich, 1977);
  - duplex scaling, dampers and their felts.
- **Soundboard:** a ribbed, orthotropic spruce plate, the plate machinery again. FEM on a
  real rib layout gives a few thousand modes up to ~10 kHz; each mode's radiation goes to
  the mic positions.
- **Sympathetic resonance:** every undamped string rings (the sustain pedal) through the
  bridge. One coupled simulation gives this for free; sample libraries struggle with it.
- **Depth versus cost:**
  - The full model (geometrically nonlinear strings, a 3D board coupled to air;
    Chabassier, Chaigne and Joly, ~2013) took on the order of hours of cluster time per
    second of sound (provisional: from memory, to be checked).
  - Production: finite-difference strings for all ~230 strings in parallel on the GPU plus
    a modal soundboard, as a print.
  - Draft: a reduced model (modal strings, fewer soundboard modes) to play in real time.
- **Data:** stringing scales (lengths, diameters, tensions) are published for major
  pianos; hammer felt is measured in the literature; soundboard dimensions and rib layouts
  are partly public.

## D. The pipe organ

**Why last:** the sound starts in aeroacoustics, the research frontier. But it has the best
whole-system story: its wind supply is the "one coupled simulation" rule at its fullest.

- **Flue pipes:** the jet at the mouth is unstable and sheds vortices at the labium.
  - Full compressible CFD or lattice Boltzmann is research-grade: hours or more per
    pipe-second in 3D, offline only.
  - The tractable deep model is the **jet-drive model** (Verge, Fabre, Hirschberg): the jet
    deflected by the acoustic velocity at the mouth with a convection delay, a jet flow
    source, a vortex loss term, coupled to the pipe's resonator from its real scaling
    (Töpfer's normal scale, end corrections, radiation impedance). It gives chiff,
    speech (the attack), overblowing and wind-pressure sensitivity.
  - A GPU lattice-Boltzmann run of one mouth geometry is the reference the jet model is
    checked against: HYBRID_PHYSICS_PLAN.md's pattern exactly.
- **Reed pipes:** a beating tongue on a shallot, a nonlinear valve like a clarinet's. Very
  tractable.
- **The wind system** as an acoustic circuit (pressure as voltage, flow as current):
  bellows, reservoirs, trunks and windchests. Drawing full organ makes the wind sag and
  wobble, like a supply under load. Pipes on one chest pull each other into sync
  (Mitnahme). The tremulant and the tracker pallet's opening speed shape the attack.
- **Voicing variance:** every pipe is voiced by hand, so seeded draws per pipe.
- **The church** is half the instrument: MIC_ROOM_PLAN.md becomes essential here.
- **Cost:** each pipe is a delay line plus a small nonlinear jet. A few hundred sounding
  pipes is plausible in real time with reductions (to be measured), and easy as a print.

## Limits

- **Real-time CFD:** not possible. CFD is an offline reference only.
- **Fully coupled 3D time-domain FEM** (soundboard and air together): an offline reference
  only. Modal reduction gets close.
- **Sourced data is the bottleneck, not compute.** Bells and pianos are well documented,
  organ scaling is documented, Rhodes and Wurlitzer dimensions are in service manuals.
  Felt, wood and voicing will start provisional and genome-bounded.

## Condition dials (realistic first, then bend)

A cracked bell, a clapper worn flat, worn or hardened hammers, drifted unisons, a piano
going out of tune with temperature and humidity, hardened Rhodes grommets, a misadjusted
pickup offset, a leaky windchest, a weak blower, a dead or ciphering pipe.

## Others worth noting (not planned)

The Hammond (tonewheels: an electromagnetic pickup like the Rhodes) with a Leslie (a
rotating horn and drum: Doppler and directivity in the room); the clavinet (a struck string
with a magnetic pickup; planned since 2026-11-06 in [CLAVINET_PLAN.md](CLAVINET_PLAN.md)); bowed strings (stick-slip friction, tractable); brass (a lip valve
and nonlinear wave steepening, the "brassy" shock); the acoustic guitar (a top plate like
the soundboard).

## Proposed milestones (a recommendation, not decided)

1. **I1: the bell.** The FEM -> modes -> BEM pipeline (CPU reference, GPU optional) on a
   published profile; a clapper contact folded into the port; tolerance draws splitting the
   doublets. Done when: its partials match published measurements of real bells of that
   profile (frequencies and ratios), the strike note's pitch agrees with published
   listening data, and it plays from keys in real time.
2. **I2: the Rhodes Mk I Stage.** Tine and tonebar modes, a magnetostatic pickup map, the
   passive network into the 5E3. Done when: the tine's partials match measurements or the
   service manual's figures, the pickup offset moves the even / odd balance as published, and
   it plays in real time through the amp and speaker. RHODES_PLAN.md splits it into
   RH1-RH6.
3. **I3: the Wurlitzer.** The electrostatic pickup as a circuit element; the 200A after the
   BJT model, or a tube model first.
4. **I4: one piano note.** Hysteretic hammer, three coupled strings, a bridge and a
   soundboard patch. Done when: inharmonicity, double decay and phantom partials match
   published measurements for that note.
5. **I5: the piano.** All strings, sympathetic resonance, the pedals, the action; a GPU
   production print and a real-time draft.
6. **I6: one flue pipe.** The jet-drive model on a real scaling, checked against a GPU
   lattice-Boltzmann reference of its mouth. Done when: speech, chiff and overblowing
   pressure match published measurements.
7. **I7: a small organ.** Reed pipes, the wind system as one coupled circuit, a few ranks
   (a positive organ).
8. **I8: a large organ in its church** (with MIC_ROOM_PLAN.md).

## Sources to start from

- Fletcher and Rossing, *The Physics of Musical Instruments* (all four).
- Bilbao, *Numerical Sound Synthesis* (2009); the NESS project.
- Bells: Lehr's and Schoofs' papers on bell design by FEM; Hibbert's bell partial
  measurements; Perrin and Charnley on bell modes.
- Piano: Weinreich (1977, coupled strings); Conklin (phantom partials); Stulov (hammer
  felt); Giordano; Bank (real-time piano models); Chabassier, Chaigne and Joly (the full
  model).
- Organ: Fabre, Hirschberg and Verge (jet drive); Töpfer (scaling); Miklós and Angster;
  Giordano (organ pipe CFD).
- Electric pianos: Rhodes and Wurlitzer service manuals; published Rhodes pickup studies.

## Open decisions (the user's)

- Which instrument first (the order above is a recommendation).
- Real time from day one, or print first for the expensive parts (the piano's full
  strings, the organ), as with tape.
- How deep the offline references go (time-domain FEM, 3D LBM) versus published
  measurements as the only check.
- The Wurlitzer: wait for the BJT model or start with a tube model.
- Where the track goes relative to the synth, tape, reverbs, drums, mics and rooms.
