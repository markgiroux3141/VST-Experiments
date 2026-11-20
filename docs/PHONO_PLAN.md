# Grooves: vinyl, the gramophone and wax cylinders from physics

Drafted 2026-11-01 from a conversation with the user ("do we have a plan for simulating a
vinyl record player from physics? ... extend this to include a gramophone and even wax
cylinders for some really old school sounds"). It grows FUTURE_DIRECTIONS.md §6 (vinyl,
a sketch) into a plan and adds the acoustic machines before it. Nothing in it is built.
Picked up 2026-11-02 (the user: start with the easiest case, an acoustic machine so the
result is obvious by ear): **the wax cylinder first**, built in a worktree beside the tape
session. Status below ("Status (2026-11-02)"). The open decisions are the user's.

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

## Status (2026-11-02): a wax cylinder end to end, offline in Python

Why the cylinder: its groove is one height per arc length (hill-and-dale), it turns at a
constant groove speed (0.466 m/s at 160 rpm, no inner-groove loss), and its reproducer and
horn need no electronics, so G1's groove and G3 / G4's acoustic chains meet in the smallest
machine there is. Built like the drums' D1: Python only, `varimu/phono/` (outside the render
cache key), `config/phono/edison_standard.yaml`, `tests/test_phono.py`,
`scripts/cylinder_study.py` -> `reports/phono/cylinder/`.

- **Networks** (`network.py`): mechanical parts in the mobility analogy (velocity as volts,
  force as amperes: a mass a capacitor to ground, a spring an inductor, a lever an ideal
  transformer), acoustic parts in the impedance analogy, a diaphragm a gyrator of its
  effective area. MNA into E x' + G x = B u; the exact response per frequency, or the
  trapezoidal rule (algebraic rows at the step's end) with one nonlinear port solved per
  step. This answers the open decision "mechanical networks in the IR" in the circuit-analog
  direction: every element here is an existing IR element type (C, L, G, transformer, VCCS).
- **Ducts and horns** (`horn.py`): Webster ladders of conical sections; the mouth an
  unflanged pipe's end correction in parallel with rho c / S (+1.8 dB of radiation
  resistance below ka ~ 1, documented). Tested against the transmission line (a pipe's
  resonances within 0.3%) and a 4000-step exact reference (a 30 in horn within 1 dB).
- **The groove** (`groove.py`): written along arc length (the cutter leaving the wax leaves
  the surface uncut), read by grayscale dilation with the tip's radius along the groove,
  a Hertz contact with Hunt-Crossley damping; seeded roughness. Tests: Lewis and Hunt's
  second harmonic (pi^2 R A / lambda^2) within 3%, the dilation equal to the exact offset
  curve where the tip fits, 2.4 um spacing within 1% of 0.24 um, mistracking starting
  within the force balance's +-25%.
- **The machine** (`cylinder.py`): recording is linear (Edison's 16 in conical studio horn,
  a glass diaphragm with its clamped fundamental, the cutter, the wax's cutting resistance;
  the performer's placement cuts the format's ~10 um maximum at the loudest point). Playing
  is nonlinear: the Model C's two-minute stylus (0.0075 in along the groove) on a stylus
  bar pivoted on the floating weight, a mica diaphragm, the neck and a 30 in horn; the
  output the pressure 1 m out. ~5-9x slower than real time (a per-sample Python loop over
  ~220 states).
- **What came out** (`reports/phono/cylinder/summary.json`): the whole chain's small-signal
  band (within 10 dB of its peak) is ~680 Hz-2.9 kHz, peaking at 1.74 kHz near both
  diaphragms' fundamentals (1.70 and 1.57 kHz); the cut needs ~118-124 dB SPL at the horn's
  mouth (performers did sing into it), and plays back at ~66-93 dB at 1 m. Published
  ranges for acoustic cylinders are ~200 / 300 Hz-3 kHz: the low end is likely too weak,
  from provisional values (the diaphragms' stiffness, the recording horn's 6 in mouth).
- **Surface noise:** read along one line, a 0.3 um rms roughness (inside Fadeyev's '< 1 um')
  hissed at 68 dB at 1 m against the vocal's 70 (mostly above 2 kHz, where the reproducer
  is +12 dB/octave in displacement). The real tip touches a ~100 um patch across the groove
  and averages fine roughness away, so the line overstates it: the config now carries an
  effective 0.03 um aimed at ~20 dB S/N, provisional until G6 models the patch.
- **Wow** (`transport.py`, the user's ask after the first listen: real cylinders warble):
  each machine's drive as seven ODEs at 8 kHz (RK4): a mainspring (running down, seeded
  irregularity), a flyball governor (collar on springs, a felt brake whose friction varies
  around its disc; the operator's speed screw solved for the target speed), a leather belt
  on eccentric pulleys, the mandrel; the cylinder's runout (an eccentric seat and an oval
  warp) both lifts the surface (the floating weight absorbs it) and modulates the arc rate
  under the stylus (w times the contact's radius, derived in `surface_speed`). Recording:
  the cut's drag (~ depth^1.5) loads the lathe, so loud passages slow it; the groove is
  written along the arc that actually passed. Playing: read along the player's own arc.
  Measured: the recorder 0.40% peak, the player 0.64% (its runout 100 um: Fadeyev's ~250
  um off true), 2.67 Hz (mandrel) and 5.3 Hz (motor pulley) strongest; a played take ~5.8
  cents rms, ~19 cents peak to peak; a 50% load step settles in ~3 s, 0.075% slow. Tests:
  a perfect drive holds its speed to 1e-9, runout swings the arc rate +-e/R at 2.67 Hz, a
  tone through the whole player warbles +-e/R, loud passages slow the lathe.
- **Crackle** (`damage.py`, G6's first cut, the user's ask: the hiss alone sounded like pink
  noise): dust grains (Poisson along the groove, power-law sizes, half pressed into the
  wax), mould colonies pitting the surface, cracks meeting the groove once a turn (a gap
  and a step: a tick at 2.67 Hz), all seeded geometry, so the clicks are the player's
  mechanics (a grain throws the tip; the diaphragm and horn ring). Defaults: light dust
  (~5 grains a second); the study's `worn` take adds heavy dust, mould and a crack. Wear per
  play (the groove changing with each play) isn't built.
- **The thin low end, analysed (2026-11-02):** the chain is flat only between the two
  diaphragms' resonances: the recorder cuts constant displacement per pascal below its
  resonance and falls above it; the reproducer's pressure rises ~12 dB/octave with groove
  displacement up to its own (1.57 kHz). The recorder's at 1.70 kHz squeezes the band.
  Damping doesn't move it (Q 5 -> 1.5: +3 dB at 300 Hz); the recording diaphragm's
  resonance does: a 50 mm glass disc (f0 ~400 Hz) lifts 200-500 Hz by ~25 dB at ~8 dB more
  singing level. But a seller's listing gives Edison's Automatic Recorder a 1-5/16 in
  (33 mm) glass diaphragm, the size used (web: https://www.ebay.com/itm/365629322052), and
  thinner glass (0.1 mm, f0 1.13 kHz) gains only ~8 dB at 300 Hz. Fadeyev 2005 (App. A2)
  calls the Edison recorder's resonance broad. Open: which recorder is meant (a home
  Automatic Recorder vs. a studio recorder, whose diaphragm and stylus linkage may differ;
  to source), the user's call.
- **After the user's comparison with real transfers (2026-11-02: more warble, more
  distortion, thin low end; fixes deferred to me):**
  - wow: the played cylinder's runout raised to Fadeyev's ~250 um (eccentric seat), the
    moulded copy inheriting 50 um from the lathe, worn governors (zeta 0.15), stickier
    springs (6%): 13.8 cents rms, 52 peak to peak (was 5.5 / 22). Below zeta ~0.13 the
    governor's speed loop falls into a limit cycle (75-180 cents peak to peak): a condition
    dial for a seasick machine;
  - low end: a studio recorder's ~2 in glass diaphragm, 0.1 mm (f0 ~400 Hz; provisional,
    the home Automatic Recorder's 33 mm is the documented alternative): the chain re its
    peak is now -30 dB at 300 Hz (was -55), -29 at 200, -48 at 150;
  - wear per play (`wear.py`): Archard's law (k p / H per distance slid, the Hertz patch's
    pressure, the quasi-static force F0 + m v^2 y''), k set so a play takes ~0.2 um off a
    flat groove (brown wax lasting "several dozen plays"). Two plastic-dent rules tried
    first ran away (a dent sharpens the curvature that made it; the worn track's width
    across the groove wasn't modelled); Archard's is linear per pass and stays bounded.
    Its audible effect at that rate is modest (tones' H2 / H3 move a few dB after 30-60
    plays); the `worn` take carries 30 plays.
  - noise vs music (the user: the `played` take's music quieter than its crackle): dust up
    to 40 um left bumps twice the loudest music's 10 um, and the cut was set by the program's
    single loudest instant (In the Pines averaged 86 dB SPL at the horn, music ~= noise).
    Now grains <= 15 um pressed 70% in, and the cut is set by the loud passages
    (`cut_level_percentile` 99: the engineer's placement, rarer peaks overloading to ~2.6x):
    on In the Pines the music sits ~15 dB rms over hiss and crackle, clicks peak about level
    with the music's peaks, the stylus leaves the groove 0.17% of the time on peaks (the
    distortion of hot acoustic records), the singer ~94 dB SPL at the horn.
- **Gaps / next:** most values provisional (sources are collectors' pages and Fadeyev et al.
  2005); the user's listen; the low end against published responses; wear per play and
  the steel needle (G2); the governor's wow; the circuitsim port (G1's Rust half: the
  network is IR elements plus a groove medium element like `Tape` / `Plate`); BLAS threads
  pinned to one when another job saturates the cores (`OPENBLAS_NUM_THREADS=1`: 150-state
  solves ran 100x slower under contention).

## Status (2026-11-18): G1's Rust half, and the gramophone's first cut (G2)

The user's ask: "the rust port, then start work on the grammaphone, let me listen and then
we'll move on to the record player", shortcuts allowed where they don't cost sound.

- **The Rust port** (`crates/circuitsim/src/phono.rs`, bound as `circuitsim.phono_play` /
  `phono_drive`; Python `varimu/phono/player.py`). The shortcut taken: the network stays a
  network in Python (network.py), which **diagonalizes the trapezoidal step once**
  (`player.modal`: P = V diag(lam) V^-1, one of each conjugate pair kept, its read-out
  rows doubled); Rust plays the modes (O(modes) per step instead of the dense O(states^2))
  with **N coupled Hertz contacts** solved at each step's end (one: the cylinder's
  bisection-Newton, ported; several: projected Newton with backtracking, the same algorithm
  in `player.solve`). The transport's RK4 loop is ported too (the seeded draws stay in
  Python). Not done: the groove as an IR element inside circuitsim's MNA (`Tape` /
  `Plate`-like); nothing needs it until the record player's electronics, and the
  cartridge's EMF can then feed a phono stage as a control input (the Clavinet's route) if
  its back-coupling proves negligible. Measured: the cylinder's played 10 s take, play
  68.9 s (Python) -> 3.9 s (Rust), the whole take 0.49x real time (was ~7x); Rust vs the
  Python reference -195 dB on the pressure (`tests/test_phono_rust.py`: a mistracking
  cylinder, the drive within 1e-12, two coupled contacts < -150 dB). `cylinder.play` and
  `transport.simulate` take `engine="rust"` (default) or `"python"` (the reference). The
  modal form is exact to rounding: -220 dB against the dense stepper (cond(V) ~2e6).
- **The gramophone** (`varimu/phono/disc.py`, `gramophone.py`,
  `config/phono/victor_exhibition.yaml`, `tests/test_gramophone.py`,
  `scripts/gramophone_study.py` -> `reports/phono/gramophone/`): a 10 in shellac 78 cut
  acoustically (the cylinder's studio horn and 2 in glass diaphragm driving a lateral
  cutter through a stylus bar; a weight-driven lathe) and played on a Victor with the
  Exhibition sound-box (mica, 43.2 mm, the one sourced size: cylinder.de), a steel needle
  on its bending spring, the stylus bar's lever, a tapered tone arm and an exponential
  flower horn (245 Hz cut-off), the pressure 1 m out. New physics:
  - the **spiral** (r(s) = sqrt(r0^2 - p s / pi); the groove slows toward the label) and
    the **two walls** of the V, each dilated by the tip along its own normal (exact for a
    sphere: each wall varies along s only), **two Hertz contacts** (lateral = their
    difference, height = their sum: the **pinch effect** at 2f, tested);
  - **tracking error** of the pivoted arm (the tip reads s + y tan(phi), y / cos(phi);
    its H2 = tan(phi) k y / 2 within 5%, tested), +6 / -9 degrees over a side;
  - the **steel needle grinding itself flat**: a flat of half-length a(s) = a_side
    (s / s_side)^(1/3) (Archard on a cone) with the point's radius at its ends, dilated
    per sample; a new needle goes 0 -> 17 um over a 10 s excerpt, a needle 1.5 sides in
    sits at 46 um;
  - the disc's **eccentric hole** (wow once a turn, 1.3 Hz) and **warp** (the heavy arm
    rides it), the Victor's spring motor, governor and worm (transport.py's model, the
    'belt' standing for the worm's mesh); dust per wall, **scratches** once a turn at
    their angle (a gouge with burrs), the shellac's grain per wall.
  Measured (`summary.json`): the chain's band within 10 dB of its peak ~360 Hz-1.8 kHz,
  peaking at 1.4 kHz (the recorder's diaphragm at 407 Hz, the sound-box's at 1.49 kHz;
  published acoustic-era ranges ~250-2500 Hz: the top is a little low, the recorder's);
  a full-level 1 kHz tone 96 dB SPL at 1 m, H2 -39 dB; the music 77-83 dB rms at 1 m;
  surface noise ~28 dB under it (the grain set for that: 0.08 um gave 36 dB); wow 5.7
  cents rms (36 p-p); mistracking ~0 at the outer grooves, 0.14% near the label; ~1.0-1.4x
  real time per take. The arm's 0.13 kg rides the contact at ~178 Hz vertically (lightly
  damped, provisional).
- **Maxfield and Harrison (1926), found by the user** (`data/schematics/victor_orthophonic/`,
  reprint B-204 of BSTJ 5, 493-523). Fig. 20 digitized
  (`data/datasheets/maxfield_harrison_1926_fig20.csv` + provenance): curve A the
  Orthophonic, curve B "one of the best commercial machines previously on the market".
  **The Victor model against curve B, unfitted: 3.8 dB rms over 300-3900 Hz** (most points
  within +-2.5 dB; misses: the model's one diaphragm mode peaks at 1.3 kHz, +12 dB, where B
  dips between peaks at 1.0 and 1.6 kHz; 5-7 dB low at 3.5-3.8 kHz; B cuts off sharply at
  ~238 Hz); `test_the_victor_follows_maxfield_and_harrisons_old_machine` guards it. Not
  refitted (the user's takes were rendered before it: options first). The paper's design
  figures for an Orthophonic (pp. 25-30): a three-section low-pass mechanical filter, f_c
  5000 Hz, z0 = pi f_c m3 = 2920 mechanical ohms (cgs; 2.92 N s/m), diaphragm 0.186 g over
  13 cm^2 (aluminium alloy 0.0017 in, corrugated, driven at six points by a spider), the
  needle arm a transformer up to ~4500 mechanical ohms at the record, the needle point's
  compliance the network's first half-shunt (~7e-6 m/N, "easily realized with commercial
  types of needle": the Victor's needle, 3.8e-5 m/N, is ~5x softer), horn throat
  A2 = G A1^2 / (pi f_c m3) ~2.4 cm^2 (G = 41 cgs ohms per cm^2), a logarithmic folded horn
  cut off at ~115 Hz; Fig. 16 its whole network. Electrical recording (pp. 5, 22-23): uniform
  velocity 200-4000 Hz, constant amplitude below, constant acceleration above, 60-6000 Hz
  recordable.
- **The Victor fitted, the Orthophonic built (same day, the user's ask: "fit the victor
  and build the orthophonic and regenerate the audio")**:
  - **The output** is now the mouth's radiated power as a pressure 1 m away
    (`gramophone.output_row`: p_mouth a / 2r), not the cylinder's on-axis monopole: 1 m is
    in the near field of a 0.3-0.8 m mouth, and the monopole rises 6 dB/octave where a
    matched horn's power is flat; Maxfield and Harrison designed for and measured flat power
    (curve A). The cylinder is unchanged (the user's approved take).
  - **The needle** is the paper's commercial needle (p. 26: the needle-point compliance
    7.07e-6 m/N): 1.37 mm mean diameter, 5x stiffer than the first guess.
  - **The ducts' wall losses** (horn.py `_ladder`'s `loss_hz`: Kirchhoff's viscous and
    thermal boundary layers at 300 Hz; the cylinder's ladders stay lossless): ~3 dB off a
    duct resonance below the horn's cut-off.
  - **The Victor fitted to curve B** (`scripts/fit_gramophone.py`, 11 provisional values,
    log space, a weak prior, guards: below the curve's first point the model stays 10 dB
    under it, and on a dense grid at most 6 dB over its line): 6.7 -> 4.9 dB rms. Unguarded
    it reached 3.4 dB with a +20 dB duct resonance at 207 Hz (the tone arm, neck and horn
    resonating below the horn's cut-off, where the mouth hardly radiates: a boom). Several
    values sit at their bounds (lever 1.5, the air chamber 0.3 mm, horn 0.41 m with a 0.35 m
    mouth): curve B's "best commercial machine" was likely not an Exhibition on a flower
    horn (an internal-horn Victrola, a No. 2 sound-box?).
  - **The Orthophonic** (`config/phono/victor_orthophonic.yaml`, `gramophone._orthophonic`,
    `ortho_design`): Fig. 16 in the mobility analogy, every element from the design
    equations (z0 2.92 N s/m, sections 1 / c = pi^2 f_c^2 m on 0.186 g masses, the arm 1.241,
    the chamber 5.2 cm^3, throat 2.39 cm^2, a 115 Hz exponential horn 1.83 m long, a 0.82 m
    mouth); provisional only its soft compliances, losses and neck. **Unfitted 4.1 dB rms
    from curve A** (fitting those four bought 0.3 dB at their bounds: not adopted).
  - **The electrical recorder** (`electrical_recorder_network`: M&H Fig. 12, a mid-series
    terminated three-section low-pass, f_c 5 kHz, the stylus 0.3 g, balancing springs net
    of the field's negative stiffness turning over at 200 Hz, the rubber line 0.5 z0, parts
    at Q 2 (heavily rubber-damped: a Q 30 filter rippled +5-6 dB under its cut-off): the
    cutter's velocity uniform within 1.5 dB over 300-4000 Hz, uniform amplitude below 200 Hz
    (the paper's p. 5), -6 dB at 6 kHz, -17 at 8 kHz. The condenser transmitter and
    amplifiers taken flat (Fig. 2: within ~1 dB 50-5000 Hz).
  - The chains: acoustic 78 on the Victor peaks at 1.6-2 kHz, a broad hump near 280 Hz;
    electrical 78 on the Orthophonic within ~8 dB from 150 Hz to 3 kHz, -9 dB at 4 kHz. The
    acoustic 78 on the Orthophonic is dull (228-749 Hz within 10 dB): the acoustic recorder's
    2 in studio diaphragm (f0 407 Hz, chosen for the cylinder's low end) isn't a sourced disc
    recorder, and the Orthophonic, flat in velocity, doesn't hide it: not rendered.
  - Numerics: `System.response` solves sparse above 120 states (the ladders: 0.02 s against
    5-10 s dense with threaded BLAS; equal to 1e-12); the scripts pin OPENBLAS to one thread.
    The modal player's condition number grew with the loss nodes (6e7 Victor, 9e8
    Orthophonic): Rust within ~-120 to -140 dB of the dense reference (tests at -120).
  - Renders: In the Pines from `assets/songs/` (its first second trimmed), cut as one side
    from the outer groove inward (98 s, to r ~83 mm), `smooth` and `played` for each pair:
    `reports/phono/gramophone/audio/in_the_pines_side_{acoustic78_exhibition,
    electric78_orthophonic}_{smooth,played}.wav`.
- **What's open for the user's listen**: the four takes (`smooth`, `played` with a new
  needle, `worn`, `inner` near the label) on In the Pines (the cylinder's excerpt: compare
  with `reports/phono/cylinder/audio/in_the_pines_played.wav`), vocal_longwayhome and
  mix_longwayhome. Above ~4 kHz the takes are all surface noise and it stays flat to
  16 kHz (the single-mode diaphragm is mass-driven by a stiff drive; a real mica's higher
  modes and breakup may roll it off: unchecked). A worn needle barely quiets the hiss (a
  rigid flat rests on the highest grains instead of averaging them). Not built: the
  shellac's wear per play (wear.py is the cylinder's), the needle's angle to the record,
  the sound-box body's lateral motion, the Orthophonic (its design figures above), electrical
  78s.

## The 1960s record player (2026-11-18, the user's choices)

After the gramophone, the user asked for the record player, and chose:
- a **portable with a ceramic cartridge** over a hi-fi deck;
- **stereo 45/45 now**, not mono first;
- a **real 60s lathe**, not an ideal cut.

Sources: `data/schematics/ge_rp1560/README.md` and `data/schematics/westrex_3d/README.md`.

**The machines.**
- **The record** is cut on a **Westrex 3D** stereo cutter with 28 dB of feedback, driven by an
  RA-1574-D. It sits on a lathe with variable pitch, writing a 90 degree groove whose walls each
  carry one channel. The record is a 12 in LP pressed in vinyl.
- **The player** is a **General Electric RP1560** (1961), a US AC/DC portable:
  - a V-M changer with a rim drive;
  - a Sonotone 16T ceramic stereo cartridge on its 0.7 mil sapphire;
  - a 12AX7 into two 35EH5s;
  - a 35W4 half-wave rectifier on a series heater string with a hot chassis;
  - two 6 in speakers in steel wings.
- These are the best documented in each class: Beitman's 1963 sheet has every value and voltage,
  and Nelson and Stafford's 1964 paper has the cutter's responses with and without feedback.

**The pipeline.**
- **Cutting.**
  - The program goes through the RIAA pre-emphasis (NAB 1964 §3.05).
  - Then the constant-velocity card, then the amplifier and each 45 degree axis of the cutter:
    a drive coil, a moving system on its springs, a feedback coil closing the loop. This is
    the stylus' excursion per channel.
  - Each channel is cut along its wall's normal (`microgroove.py`). The vertical angle is 23
    degrees geometric, minus Bauer's springback.
  - The variable pitch comes from the program a turn ahead, and the groove is written along arc
    length.
- **Pressing.** The vinyl's surface: roughness to NAB's noise figure, plus non-fill ticks.
- **Playing.**
  - The changer's rim drive (`rimdrive.py`) and the arm's geometry (tracking error, skating).
  - Each wall is dilated by the 0.7 mil sphere, and read by two Hertz contacts.
  - The cartridge's mechanics: the tip, the butyl link, the PZT bars as piezoelectric elements
    with their capacitance, and the arm's mass. Out comes each bar's EMF.
  - The amplifier is a circuit file (`ge_rp1560.yaml`) with the cartridge's EMFs as audio
    inputs. Its outputs are the wings' sound pressure, L and R.

**Milestones (LP1-LP6).**
1. **LP1, the stereo groove and the lathe.** Done when:
   - one channel cut alone moves one wall, and the vertical angle's distortion matches its
     closed form;
   - the cutter's open loop fits NS64 Fig. 6, and its closed loop Fig. 7 with 28 dB of feedback;
   - the card brings the cut within +-1 dB from 50 Hz to 12 kHz, the RA-1574-D's spec.
2. **LP2, the pressing.** Done when the surface noise meets NAB's at least 50 dB below 5 cm/s
   (500 Hz - 15 kHz).
3. **LP3, the changer and the arm.** The rim drive, the arm's geometry, skating. Done when the
   wow and flutter land in a period changer's range.
4. **LP4, the cartridge.** The Sonotone 16T. Done when:
   - its compliance is Sonotone's 2.4e-6 cm/dyne;
   - its separation is 25 dB;
   - its response into 2 M is Sonotone's 20 Hz - 12 kHz;
   - its output is ~0.65 V.
5. **LP5, the amplifier.** `35EH5@1` and `35W4@1` fitted to their sheets, then `ge_rp1560.yaml`.
   Done when it idles at the sheet's printed voltages within +-20%.
6. **LP6, In the Pines** cut, pressed and played, for the user to listen.

### Status (2026-11-18): LP1-LP6 built, offline in Python

Tests: `tests/test_record_player.py` (17). Each item below gives the module and what it does.

- **LP1, the stereo groove and the lathe.**
  - `microgroove.py`: the 45/45 walls (A on the left, inner wall; B on the right, outer one);
    the cutter's incline; a table spiral; variable pitch from the program a turn ahead.
  - `lathe.py`: the Westrex 3D's axis as a network (drive coil R / L / Bl, the coil form on its
    springs, the torque tube to the sapphire, the lacquer's load, the feedback coil on the
    form). Both axes are coupled by the links' sideways spring.
    - `scripts/fit_westrex_3d.py` fits it to NS64 Fig. 6: 0.89 dB rms, resonance 1067 Hz,
      Bl 3.2 T m.
    - Closed with 28 dB of feedback, it is 3.0 dB rms from Fig. 7. That's a check, not a fit:
      the amplifier's two provisional poles can't shape it, and a fit runs them to any bound.
  - The card is fitted per cutter (`lathe.fit_card`), as the factory trimmed each one. With it
    the chain is within 0.38 dB of RIAA from 50 Hz to 12 kHz and 0.9 dB at 15 kHz (spec +-1 /
    +-2). Separation is 30-64 dB (NAB: at least 26).
  - `lp.record`:
    - the VU sets the level: the louder channel's 99th percentile of 300 ms rms at 5 cm/s
      peak per channel (NAB §3.15);
    - the chain's impulse responses give each axis' excursion;
    - the AM 32b's 0.035% wow;
    - the effective cutting angle from Bauer's springback: tan C = tan 23 - 0.42, ~0.3 degrees.
  - A gotcha fixed: normalizing the chain by its complex value at 1 kHz rotated every phase,
    which isn't causal, and cut 1.9 dB low. It is now normalized by the magnitude.
- **LP2, the pressing** (`lp.press`).
  - Roughness on each wall at 22 nm rms, for NAB's -50 dB (500 Hz - 15 kHz, re 5 cm/s, through
    a 0.7 mil tip and the RIAA). The inner groove plays -47.7 dB.
  - Dust (damage.py's grains, embedded 0.2) and non-fill pits (provisional rates).
- **LP3, the changer.**
  - `rimdrive.py`: a shaded-pole motor's torque line (stall to synchronous, x V^2, 2 f
    pulsation) on a stepped pulley sized at the factory for the rated load. Then the rubber
    idler, with a set flat and runout, and the platter's rim. Nine states, RK4 at 2 kHz.
  - Low mains slows it.
  - Every V-M value is provisional: no data found.
- **LP4, the cartridge** (`portable.py`).
  - The structure:
    - the tip's mass with the two walls' Hertz contacts (sapphire on vinyl, E 2.94 GPa x
      1.055 dynamic);
    - the arm's masses and bearings, the downforce, the skating force;
    - per 45 degree axis, through two transformers in series: the butyl link (a standard
      linear solid relaxing at the arm resonance), the resolver's mass, the PZT bar, and its
      piezoelectric gyrator into C0 and the 2 M load.
  - N is calibrated to Sonotone's 0.65 V (at 1 kHz and 5 cm/s: the velocity isn't stated).
  - The resolver's error is 3.2 degrees for 25 dB of separation.
  - Response +3.3 / -0.9 dB from 100 Hz to 12 kHz, the arm resonance +7 dB at 20-30 Hz,
    k^2 2.8%.
  - Played, the tone gives 0.652 V and -24.3 dB of crosstalk. Skating loads the inner wall to
    45 mN against 38 mN. The player runs at 0.3x real time.
  - A gotcha fixed: a viscous damper in parallel with the link was 30x stiffer than its spring
    at 1 kHz. Rubber's loss isn't a dashpot's.
- **LP5, the amplifier.**
  - `35EH5@1`: Koren, 7% rms on RCA's plate family, read by eye. At the typical point it gives
    36.8 mA (the sheet 32 mA, its curves ~37), gm 12.5 mS, but rp 37 k against the sheet's 14 k.
  - `35W4@1`: Child's perveance for RCA's typical half-wave operation (134.9 / 120.1 V
    against 135 / 120).
  - `config/circuits/ge_rp1560.yaml`, all from Beitman's sheet: VOLUME / BALANCE (reversed on
    the right) / TONE, the 12AX7's bleeder bias, the step network, the shared cathode, the
    35W4 on the line through RCA's minimum 15 ohm plate-supply impedance.
  - It idles within 14% of every printed voltage: B+ 128 / 104 V against 120 / 105.
  - Provisional: the output transformers (3000 ohm per the 35EH5 sheet); the speakers (the
    P8R stands in for the unknown 6 in PMs) in closed 5.5 L wings.
- **LP6, the renders.**
  - `scripts/record_player_study.py` -> `reports/phono/record_player/`: the variants `smooth`
    (a perfect pressing on a perfect turntable) and `played` (surface, dust, non-fill, the
    changer, warp, off-centre hole, rumble).
  - In the Pines, the whole side (98 s from the outer groove, 146 -> 139 mm): 78 dB SPL from
    each wing at 1 m, peak cut 26 cm/s (NAB's ~21: a hot cut), no lift-outs.
  - 30 dust grains and 6 non-fill pits per wall; mistracking 0.04%.
  - Speed: cut 0.15x, play 0.3x, amplifier 4.0x real time (production): 15 min for both
    variants.
  - Per channel against the dry mix (dB re 1 kHz, Welch): 63 Hz -26, 125 -9, 250 +8...9, 500
    +1...2, 2 kHz +-2, 3 kHz +7, 4 kHz +4, 8 kHz -6...-10, 10 kHz -15...-17.
    - The thin bass: the ceramic's ~700 pF into the volume and balance pots in parallel is a
      high-pass near 200 Hz, and the speaker sits in a small closed box.
    - The 250 Hz hump: the speaker's resonance in the 5.5 L wing.
    - 3 kHz: the P8R stand-in's presence peak (+7 dB in its published response).
    - The top: the 12AX7's grid stopper against its Miller capacitance, and the cartridge.
  - Checked stage by stage (Welch and cross-spectra): the groove against the dry follows RIAA
    within 0.6 dB, the cartridge's EMF is flat with displacement (coherence ~1), and the
    amplifier's program transfer equals its tone response.
  - A trap: this source's side carries as much treble as its mid (side / mid +1 to +2.4 dB at
    3-8 kHz), so comparing mono mixes made the dry look 10 dB dark. Compare per channel.
  - The amplifier distorts 5.8% at the reference level, VOLUME 0.7 (2.6% at 0.5): H2 from the
    starved 12AX7, already at the 35EH5's grid, core-independent. The model's 12AX7 runs at
    0.05 mA (plate 94 V) where the sheet's 85 V means ~0.09 mA, deeper in Koren's cutoff tail.

**Open (the user's):**
- Listen.
- The wings' real 6 in speakers: no data found. Options: a provisional 6 in PM from typical
  figures, or Sams 596-5 (paid), which should name them.
- The V-M changer's data, with the same Sams lead.
- The 35EH5's plate resistance (37 k against 14 k), and the 12AX7's current in its starved stage (0.05 mA against ~0.09: 5.8% THD at the reference level).
- The 16T's capacitance, and the velocity its 0.65 V is rated at.
- Gravereaux and White 1976 (AES, paywalled), which would replace the cutter's fit.

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
