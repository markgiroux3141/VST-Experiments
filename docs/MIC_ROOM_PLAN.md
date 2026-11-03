# Microphones, preamps and rooms, from physics

Drafted 2026-11-01 from a brainstorm with the user. Nothing in it is built. The user picks
it up deliberately when they feel the other tracks are ready; the order below is a
recommendation.

## The idea (the user's)

Record virtual sources in a virtual room through virtual microphones and preamps, all
simulated from the physics of their parts, the way the project does everything else:

- **A first test:** a Neumann **U47** into a Telefunken **V76**, a signal passed through
  them, heard.
- **Then a room:** arbitrary dimensions, a floor plan that needn't be rectangular (vaulted
  ceilings and objects included), sources placed in it, several mics placed around it,
  each into its own preamp. Mic and preamp combinations give different textures; placement
  gives natural reverb and bleed between mics.
- **Chains that are polar opposites**, so tracks recorded through them separate well
  psychoacoustically (SEPARATION_PLAN.md).

**Rendering, not real time** (the user's call). Mic + preamp is a print for texture; the
room is an offline render. A live draft of a mic + preamp chain as a session insert (F3) is
possible later, never a requirement.

**The GPU is in** (the user's call: an RTX 3080, 10 GB, "anywhere we could possibly use
the GPU"). Every GPU path keeps a CPU reference for its tests.

**Sources:** pre-rendered audio, at first the tube synth's renders (they carry no mic or
room of their own; recorded stems do, SEPARATION_PLAN.md's caveat).

## The chain

**source -> room -> capsule -> mic electronics -> cable -> preamp -> print**

Each block is physical, with sourced values (Hard rules):

- **The room** is a linear medium: air at recording levels is linear, and a mic doesn't
  load the room. So the room reduces to **impulse responses**, one per (source, mic), each
  **two channels: the pressure at the capsule's front and at its back entry**. The polar
  pattern then comes out of the capsule's physics, not a table. Computed once per layout,
  cached; the expensive part.
- **Mic, cable and preamp are one netlist** (the "one coupled simulation" rule): the mic's
  output transformer into the preamp's input transformer, the cable's capacitance against
  the mic's source impedance, a ribbon or dynamic loaded by the preamp's input impedance.
  Nonlinear, simulated per take. The two capsule pressures enter as **control inputs**
  (S3's `cv_inputs`: driven by their own samples, linear between them) on pressure sources
  in the capsule's acoustic network.
- **Mono stays the convention.** Each mic is a mono track; a stereo pair is two mono tracks.
  Stereo playback is the separation plan's later, project-wide change.

**Units.** A source track's full scale is a pressure at 1 m on axis in free field
(pascals, like the 5E3's `full_scale.output_pascals_peak`). Proposed: 0 dBFS = 20 Pa peak
(117 dB SPL for a sine), so a source at -18 dBFS is ~99 dB SPL at 1 m: a loud close
instrument. A mic circuit's input is pascals at its capsule.

## Microphones

A capsule is an acoustic-mechanical network (masses, compliances, acoustic resistances)
coupled to an electrical port, like the P12R speaker run backwards (`varimu/devices/
speaker.py`). New component kinds as needed (`capsule`, `ribbon_motor`, `moving_coil`),
versioned like every component (C1).

**Physics shared by all:**
- The diaphragm's mass and tension (or a ribbon's mass and corrugation compliance); the
  air film to the backplate (squeeze-film damping); the backplate's holes (acoustic mass
  and resistance); back volumes; the electrostatic transducer (polarized: linearized first,
  its force-gap nonlinearity later) or the electrodynamic one (B l in a magnet gap, the
  coil's inductance).
- **Proximity effect** is not a feature: a pressure-gradient capsule near a source sees the
  spherical wave's 1 + 1 / (j k r) between its front and back.
- **Self-noise** is not a feature either: every acoustic resistance has thermal noise
  (fluctuation-dissipation), so B5's Johnson noise on the network's resistors gives the
  capsule's self-noise, plus the bias resistor's and the tube's.
- **Free field first:** before any room, a mic is driven by a plane wave at an angle: the
  front and back pressures are the wave at the two entries (the path difference around the
  capsule). Diffraction by the mic's body and head basket is a later fidelity item.

**The list** (the user OK'd it 2026-11-01):

| Mic | Type | Its pole | Build cost | Sources to find |
|---|---|---|---|---|
| **Small pressure omni** (Schoeps MK2 / B&K 4006 style) | Small condenser, transformerless | Flat and fast; also **the capsule machinery's verification case** | The simplest capsule; electronics later | The measurement-mic literature (Zuckerwar's condenser-microphone theory); a datasheet response |
| **Neumann U47** | Tube large-diaphragm condenser, cardioid / omni | Dense, rich upper mids; the user's first listen | Two-diaphragm capsule (M7 / K47); a **VF14** fit; the **BV8** output transformer; its supply (NW47); the cable | The schematic (Neumann service documents); a VF14 sheet; BV8 data; capsule dimensions; Neumann's response and polar plots |
| **RCA 44-BX** | Ribbon, figure-8 | The darkest pole; huge proximity effect | The cheapest mic: a ribbon in a magnet gap and a step-up transformer (JA core), no tubes | RCA's instruction book and published response |
| **Shure SM57** | Dynamic, cardioid | Mid-forward (presence peak ~4-6 kHz), blunted transients | Diaphragm, coil and the capsule's resonances; the coil against the preamp's input | Shure's published response and polar plots |
| **AKG C12** | Tube condenser | The bright tube pole | CK12 capsule; its 6072 is a low-noise 12AY7 (`12AY7@1` exists); its transformer | AKG documentation |

**Later:** Electro-Voice RE20 (Variable-D: no proximity effect), Neumann U67 (figure-8;
an EF86 fit), FET mics (U87, KM84; a JFET model), and lo-fi wildcards with physical
nonlinearities: a crystal mic (Rochelle salt) and a carbon telephone mic (granule
contact resistance).

## Preamps

| Preamp | Character | Build cost |
|---|---|---|
| **Telefunken V76** | Tube pentodes, transformers at both ends, high gain | DEVICE_BUILDER_PLAN.md's **B10**; the schematic is in hand (`data/schematics/telefunken_v76/`) |
| **Ampex 351 electronics** | Tube; the "Ampex pre" colour | Built for tape's TM5 (TAPE_PLAN.md): nearly free |
| **Neve 1073** | Discrete class A transistors, Marinair transformers, 300 / 1200 ohm input (loads ribbons and dynamics) | Needs the **BJT model** |
| **API 312** | The 2520 discrete op-amp, class AB output, transformer: odd harmonics, punch | Needs the BJT model |
| **Clean transformerless** | The neutral pole, and the control: the mic heard without a preamp's colour | Needs the BJT model (or an op-amp macro model) |
| **Universal Audio 610** | Tube console channel | Tube fits (DEVICE_CANDIDATES.md) |

**The BJT model is a shared prerequisite** (the user's OK, 2026-11-01): three of these
preamps, DRUM_PLAN.md's D3 (TR-808, CR-78) and DEVICE_CANDIDATES.md's tier 2 all need it.
Gummel-Poon subset, a Python reference, SPICE's native model, circuitsim's port, an
agreement test, fits to datasheets. It is recorded in DEVICE_BUILDER_PLAN.md's "New device
types".

## Opposite chains

What a chain controls among the cues the ear groups by (SEPARATION_PLAN.md's table):

| Axis | One pole | The other pole |
|---|---|---|
| Tilt / HF | Ribbon: rolled off above ~10 kHz | Small condenser: flat, extended |
| Midrange | Dynamic: presence peak, mids forward | Pressure omni: no peak |
| Transients | Heavy moving coil: blunted | Light condenser diaphragm: fast |
| Harmonics | Tube single-ended + transformer: 2nd, thick lows | Push-pull op-amp (API): odd. Clean transformerless: none |
| Loading | Ribbon or dynamic into a low-impedance transformer input: darker, bass shifted | High-impedance input: the mic as designed |
| Pattern / distance | Close cardioid: dry, proximity bass | Distant figure-8 or omni: room, rear pickup |

**Four poles:**

1. **Dark and thick:** RCA 44-BX -> V76 (or the 351).
2. **Bright and clean:** small omni or C12 -> clean transformerless.
3. **Mid-forward and punchy:** SM57 -> API 312.
4. **Big and glossy:** U47 -> 1073.

1 vs 2 is the widest gap on tilt and harmonics; 1 vs 3 on midrange and harmonic type.
Distance in the room stacks on top: an opposite chain at an opposite distance.

**Measured, not assumed:** once a few chains exist, rank pairs with the separation study's
glimpse metric (`varimu/separation/`) and the listening staircase
(`scripts/separation_listen.py`). These chains differ far more than the 670 units did, so
the "too subtle to choose" finding of Phase 5 shouldn't apply; if it does, the memory rule
holds (call it verified, move on).

## Rooms

### Geometry (the user's call: complex is fine if the sound earns it)

It does, and it's cheap in a wave solver (any shape becomes grid cells):

- **Sloped and vaulted ceilings** break the flutter echo between parallel surfaces and
  spread the room's modes.
- **Objects** (gobos, a piano lid, a riser, a couch) are how real sessions shape bleed:
  they shadow one mic from another source.

The model, kept simple for the editor (not CAD): a **floor polygon** (any shape, convex or
not), a **ceiling height field** over it (flat, shed, gable, barrel vault: a height per
floor point), and **objects as primitives** (boxes, thin panels at any angle). Every
surface has a material.

### Materials, from physics where possible

- **Porous absorbers** (foam, fibreglass, curtains, a couch) from thickness and flow
  resistivity (Delany-Bazley 1970 or Miki 1990), not tabulated coefficients.
- **Panel absorbers** (wood panelling, a door, a window) as a mass on an air cavity: a
  resonance from mass per area and depth.
- **Hard surfaces** (concrete, plaster, brick, glass) from published absorption
  coefficients per octave (sourced tables: Kuttruff, *Room Acoustics*; Vorländer,
  *Auralization*), as the fallback for anything not built from physics.
- **Scattering** coefficients per surface (provisional, bounded) for the geometric part.
- **Air:** ISO 9613-1 absorption (already in `varimu/separation/`), the speed of sound from
  temperature; temperature and humidity are room parameters.

### The solver: a hybrid

| Band | Method | Why |
|---|---|---|
| Low (up to the crossover) | **3D FDTD on the GPU** (wgpu compute, f32) | Truly physical: modes, diffraction round corners and objects, any shape. Boundaries as locally reacting impedances fitted to the materials. A compact or interpolated scheme (Kowalczyk & van Walstijn 2011; Hamilton & Bilbao) needs fewer points per wavelength than the standard leapfrog |
| High (above it) | **Geometric, on the GPU**: image sources with visibility to a low order (Allen & Berkley 1979; Borish 1984 for non-rectangular rooms), stochastic ray tracing with scattering for the tail, edge diffraction (Svensson, Fred & Vanderkooy 1999) where a non-convex room hides the source | Accurate where wavelengths are small; each arrival's direction exact |
| Crossover | Zero-phase complementary blend (as the separation room's bands) | |

**Cost** (estimates for a 5 x 4 x 3 m room on the 3080, to measure): up to ~4 kHz a few
minutes per source per second of response; up to ~8 kHz ~30 min and ~7 GB; full band
doesn't fit 10 GB. So the crossover sits at ~4-8 kHz, a setting (a quick draft lower, an
overnight print higher). A hall (~840 m^3) is ~15x the cells. The CPU reference
(the same scheme, multithreaded) is for tests at low crossovers. Check f32 against the CPU's
f64 on long runs: the 3080's f64 is 1/64 rate.

**One FDTD run per source** records every mic (pressure at the two capsule entries, by
interpolation; below the crossover they are much closer than a cell, so the gradient is
accurate). Above the crossover, each geometric arrival gives the two entries' pressures
from its direction, as in free field.

**Sources radiate:** a point source first; then a source through a virtual speaker (a
baffled piston's directivity; the P12R's cone and cabinet from C3), which also covers
re-amping the 5E3 into the room.

**Bleed is not a feature:** every source reaches every mic, through the same room.

### The caches

- A room's IRs: keyed by the mesh, materials, positions, air and solver settings; per
  (source, mic) two channels at the project's 96 kHz.
- The mic pressures: a source track convolved with its IRs (FFT convolution on the GPU),
  summed over sources per mic.
- The prints: each mic's pressures through its mic + cable + preamp netlist at production,
  as session prints (SESSION_FX_PLAN.md's F1 machinery).

## In the app (the native app only; the web app gets nothing)

A **Room view**: draw the floor polygon, set the ceiling profile, place objects, give each
surface a material; place sources (session tracks or synth renders) and mics with an aim,
the polar pattern drawn at each; pick each mic's model, pattern switch and preamp. Render
prints each mic into a new session track (`Session::add_rendered_take`'s pattern), with
undo. Stereo pairs (XY, ORTF, spaced) are two mics placed. A heat-map of the room's level
at a frequency (from the FDTD run) is a cheap aid for placing mics.

## Proposed order (a recommendation; milestones A1-A9)

1. **A1. The V76** (= B10; nothing new here). Its profile against the Braunbuch's figures,
   on a line signal; rendered, live play optional.
2. **A2. The capsule machinery,** verified on the small pressure omni's capsule alone:
   acoustic network, linearized electrostatic port, pressure in as control inputs, B5 noise
   on its resistances. *Done when:* its response and self-noise match the published
   theory and a datasheet within stated tolerances.
3. **A3. The U47** in free field: the two-diaphragm capsule (pattern switch), the VF14 fit,
   the BV8, the supply, the cable; a plane wave at an angle. *Done when:* its response and
   polar plots match Neumann's within stated tolerances. Then **U47 -> cable -> V76 as one
   netlist**: the user's first listen, on synth renders.
4. **A4. A shoebox room with directions:** the separation room grown up (image sources
   with arrival directions, so per-mic front / back IRs; a directional diffuse tail),
   sources and mics placed, bleed, GPU convolution. The whole chain heard early ("end to
   end early, fidelity later").
5. **A5. Arbitrary rooms:** the floor polygon, ceiling height field and objects; GPU FDTD
   plus GPU geometric, the crossover, materials from physics. *Done when:* a rigid
   shoebox's modes match the closed form; FDTD and image sources agree in a shoebox below
   the crossover; reverberation time in a diffuse room within Eyring's; a source hidden
   round an L-shaped room's corner matches edge-diffraction theory; GPU vs CPU reference
   agree.
6. **A6. The Room view** and its prints into session tracks.
7. **A7. More mics:** the RCA 44-BX, the SM57, the C12; the small omni's electronics.
8. **A8. The BJT model** (shared), then the Neve 1073, the API 312 and the clean
   transformerless preamp; the 351's electronics as a preamp once TM5 exists; the UA 610.
9. **A9. Ranking chains:** the four poles, pairs ranked by the glimpse metric and the
   staircase.

### Status (2026-11-03)

Started by the user (U47 -> V76 first, alongside the gas-tube work in its worktree).
- **A1 (the V76) in progress:** tubes, circuit and idle check built; the profile is next
  (DEVICE_BUILDER_PLAN.md B10's status).
- **A2 (the capsule machinery) built and checked on the B&K 4134:** capsules are components
  (kind `capsule`, `varimu/devices/capsule.py`: the geometry sourced, the lumped network
  derived at fit time so both builders read numbers), the `capsule` part ([front, backplate,
  out]: pressures as volts, volume velocities as currents; the diaphragm's displacement
  drives a Thevenin source behind C0; the electrostatic negative stiffness in the diaphragm's
  compliance) and `capsule_dual` (two diaphragms, through and blind holes: the K47 family;
  an unpolarized side has no source) in both builders, Johnson noise on the acoustic
  resistances (the self-noise), an AC solver for linear IRs as the reference
  (`varimu/measure/ac.py`), `scripts/capsule_study.py` -> `reports/mics/capsule_bk4134/`,
  `tests/test_capsule.py`. `BK4134@1` from Zuckerwar's geometry
  (`data/schematics/bk_4134/README.md`) with H&M's FEM film resistance (Skvor's uniform-array
  formula gave 2.3x: over-damped, 21.8 dB(A)): render vs AC 0.018 dB below 20 kHz, rendered
  noise vs AC prediction 0.5 dB, **self-noise 18.6 dB(A)** (B&K 18; theory 17.9-19.7),
  sensitivity 9.53 mV/Pa (the published geometry's own bound 9.6; B&K's 12.5 is ~2.3 dB
  above it, a known gap of that parameter set), the response peaks +3.3 dB at 15.6 kHz
  (B&K ~+1: 1.3 dB outside its +-2 dB; the gap's air mass and the film's frequency
  dependence aren't modelled).
- **A3 in progress (2026-11-03):**
  - **VF14:** `VF14T@1`, a Koren triode on Telefunken's triode-connected curves (Funkschau
    1/1948, digitized; fitted up to 10 mA / 200 V, the U47's region: mu 27, 21% rms; the
    exponent held at >= 1, below it Newton fails at cutoff).
  - **The U47's electronics:** `config/circuits/neumann_u47.yaml` from the 1959 drawing: the
    capsule (`capsule_dual`, pattern switch: omni polarizes the rear diaphragm, cardioid
    holds it at the backplate), the VF14M with its heater as a resistor at its printed
    point, the BV 8 (a reproduction's ratio, resistances and 91 H), the NG as a Thevenin
    source (300 V open, 105 V at 40 mA). **Its idle needs the underheated cathode:** at the
    rated heater the anode sits at 27 V; B6's cathode model at the heater's printed 35 V of
    60 V gives 855 K and a -0.32 V space-charge shift (a DC source in series with the grid:
    a circuit's `heaters` block is global, so a chain couldn't carry it), and the U47 idles
    at 35.8 V / 0.542 mA against the printed 34 V / ~0.55 mA (`tests/test_u47.py`).
    Amplifier gain grid to output (1 kOhm) +9.7 dB.
  - **The chain:** `scripts/compose_chain.py` writes `config/circuits/u47_v76.yaml` (each
    circuit's keys, parts and nodes suffixed, the mic's measuring load and the preamp's
    generator dropped, a 1 nF cable); builds bit for bit in both builders, pre-flight clean;
    ~5x slower than real time at production. `scripts/mic_print.py` prints a clip through a
    chain as a plane wave from an angle (`varimu/mics/free_field.py`).
  - **The K47 (K47@2, fitted; K47@1 was a placeholder):** Neumann's curves digitized
    (`data/datasheets/neumann_u47_{response,polar}.csv`: Telefunken 1952's measured responses
    re 1 kHz, the 1958 sheet's polars). A first fit bounded the diaphragm like a measurement
    capsule's (300-5000 N/m) and found no cardioid (its internal air's compliance against a
    stiff diaphragm adds an omni term that fills the null) and an omni notch near 15 kHz (no
    diffraction). The theory (`data/schematics/neumann_u47/K47_THEORY.md`: Torio & Segota, AES
    2000; von Braunmuhl & Weber's patent; Neumann's own) put it in another regime: a nearly
    slack diaphragm (tens of N/m), the gradient resistance between the two sides
    (`through_resistance_pa_s_m3`, Torio & Segota's R_a), adiabatic blind holes; and the
    entries' diffraction: the capsule as a rigid sphere (the exact series, cap-averaged:
    `varimu/mics/free_field.py`), whose 3a is the low-frequency path. `scripts/fit_k47.py`
    fits tension, the two resistances, the blind holes' depth and count and the sphere's
    radius into the grid's real load (R2 and the VF14's Miller capacitance, 71 pF: an 8 pF
    guess left the circuit 4.4 dB under the fit); the makers' measured backplate (5.65 mm,
    0.8 / 1.08 mm holes) fixed. Result (`reports/mics/k47_fit.png`, `k47_fit.json`): tension
    23.6 N/m (25% electrostatic softening), R_a 4.7e7, 66 blind holes per side 4.5 mm deep,
    sphere 11.2 mm (path 34 mm; Torio's 32). **The whole U47 against ds58** (`tests/test_u47.py`):
    cardioid 25.4 mV/Pa at 1 kHz into 1 kOhm (25-28), omni 19.1 (14-17: ~1 dB over), front
    to back 13.2 dB at 100 Hz and 15.1 at 1 kHz (the 1958 polars: 11.7, 16.2); on axis the
    cardioid within 1.2 dB rms of Telefunken's curve (its presence peak at ~14 kHz, the
    data's at ~9: 3 dB at worst). **Misses:** the omni's on-axis dip near 6.5 kHz (-9 dB where
    the data has -1: a sphere for a disk-shaped capsule; the theory's next stage, the real
    body's low-frequency path and a BEM of capsule and basket, is where it goes), the
    presence peak's frequency. Free field, plane wave: the polars' measuring distance (and
    proximity) not yet.
  - **The first listen, printed (2026-11-04; heard 2026-11-04: "it all sounds good", the
    differences subtle, the rear print the most noticeable; the user moved on):** `scripts/mic_print.py`
    through `u47_v76` at production (~5.5x slower than real time): the 5E3's guitar take (its
    speaker's sound pressure) at 100 dB SPL, a dry vocal and the tube synth's brass at 94 dB,
    on axis at two V76 gains each (the higher drives the V76 to its +25 dBu clip on peaks), the
    vocal from behind (15 dB down: the cardioid); `reports/mics/prints.json` lists them,
    `reports/mics/audio/matched/` has each at -18 LUFS with the dry sources (audio git-ignored).
  - **The capsule's real body, K47@3 (2026-11-04; the U47 and `u47_v76` pin it since, the
    user's call):** `varimu/mics/bor.py`, a BEM of the capsule as a rigid body of revolution.
    Only the azimuthal order 0 is solved: the diaphragm's axisymmetric mode shape picks out that
    order at any incidence, so one 1-D integral equation gives the entries exactly (static kernel
    in elliptic integrals with Gauss-identity singularity subtraction, CHIEF rows against the
    interior resonances). CPU, ~0.2 s per frequency (~90 panels): the GPU isn't needed here. It
    is checked against the sphere's series within 0.002 dB (plane wave, and a point source at 5 /
    30 cm: `free_field.sphere_point_factors`, Duda & Martens), against Lamb's thin disk within
    ~1% (16a / 5 pi), front / back symmetric (`tests/test_bor.py`); the capsule's mesh converged
    within 0.02 dB in band. The body (`published_points.yaml` "K47" `body`): 29.8 mm behind the
    rings and a 33 mm middle rim (makers / forums), the rim's 1.5 mm, the spacing and the
    rings' height a grid (`fit_k47.py --spacing-mm --proud-mm`: 5.75 / 7 mm x 0 / 0.5 mm all fit
    within 1.10-1.15 dB weighted, so the curves don't pin them; 5.75 mm and 0.5 mm kept). On the
    body the front face builds up +8 dB near 7 kHz (Bore & Peus: up to 10), the low-frequency
    path is 26 mm (the sphere's 33). The network refitted on it (`reports/mics/k47_fit.*`):
    omni on axis 0.64 dB rms / 2.4 max (K47@2: 2.40 / 8.9, the 6.5 kHz dip gone), cardioid
    0.67 / 1.95 (1.16 / 3.1), the presence peak at ~11 kHz (the data's ~10; K47@2 ~14); tension
    32 N/m, R_a 2.1e7, the blind holes again at their 4.5 mm bound. **The whole U47 with K47@3:**
    cardioid 23.9 mV/Pa (ds58 25-28: 0.4 dB under), omni 16.8 (14-17: in; K47@2 19.1), front /
    back 13.6 dB at 100 Hz, 20.2 at 1 kHz (the polars' 11.7 / 16.2: the null deeper than the real
    mic's, whose body and head basket aren't modelled). **Distance:** prints take
    `mic_print.py --distance-m` (a point source on the body); the cardioid at 31 Hz is -2.9 dB re
    1 kHz in a plane wave, +0.5 dB from 1 m, Telefunken's curve -1: its measuring distance was
    probably ~1-2 m (not stated), so the fit stays a plane wave. Entries for prints are cached in
    `cache/diffraction/` (by the body, angle, distance and `bor.py`'s source). A / B prints: the vocal at
    0 / 180 deg, V76 at 40 dB, through K47@3 and (`*_k47v2`) K47@2 (`reports/mics/prints.json`;
    -18 LUFS copies in `audio/matched/`); the rear print now 20 dB under the front (K47@2: 15).
- **A3's gate, the U47's sources:** catalogued in `data/schematics/neumann_u47/README.md`
  (Neumann's own archive: the 1958 data sheet with polars and responses, the 1958 / 1959
  manuals, the 1959 factory drawing U 47-00-00-00 with every value; Funkschau 1/1948's
  VF14 data; the BV8 from a Haufe reproduction sheet, 6.5 : 1). Missing: the capsule's
  geometry (no primary source: diaphragm thickness and tension, gap, backplate holes and
  cavities), the NG supply's full drawing (thumbnail only), the cable's per-metre values,
  the BV8's leakage and capacitances. The capsule's geometry will likely be bounded
  provisional genome parameters fitted to Neumann's curves, capacitance (2 x 78-83 pF) and
  sensitivity (the README lists the options). The early units' grid leak and coupling
  capacitor differ from 1959's: the circuit file picks a revision.

**Later fidelity:** the capsule's electrostatic nonlinearity (a new device: Python, SPICE,
circuitsim); diffraction by the mic's body (a boundary-element solve on the GPU, on
demand, as the component editor's field solvers); a source loaded by a nearby wall
(two-way coupling); the RE20, U67, FET mics and the lo-fi wildcards; stereo playback.

## Reuse

Built: transformers on JA cores (every mic and preamp transformer); tube fits and the
component versions (C1); B5's noise (self-noise); S3's control inputs (the capsule's
pressures); the speaker's acoustic modelling and pascals convention (C3); the plate's
medium-as-impulse-response pattern (REVERB_PLAN.md); the separation study's shoebox room,
ISO 9613-1 air and glimpse metric; session prints and rendered takes (SESSION_FX_PLAN.md);
the tube synth as the source.

New: capsule, ribbon and moving-coil components; the VF14 (and later EF86) fits; the BJT
model; a room format and its editor; the GPU FDTD and geometric solvers (wgpu, the
project's first GPU code); porous and panel absorbers from physics.

## Open decisions (the user's)

- When the track starts, and where it sits among tape, the synth ideas, C3 and the drums.
- The source full-scale convention (proposed above: 0 dBFS = 20 Pa peak at 1 m).
- wgpu (portable, Rust-native; proposed) or CUDA (fastest on the 3080, NVIDIA only).
- Whether the small omni gets its own electronics early (A2) or only in A7.
