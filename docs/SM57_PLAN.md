# The Shure SM57 (and SM58) from physics

Drafted 2026-11-04 from a conversation with the user ("are there any microphones that we
could make like an SM57 or SM58 to add to our list? what would this entail. No shortcuts
and in keeping with our physics approach", then: "yes, let's write this plan"; the user's decisions 2026-11-05, see "Decisions"). It
expands
MIC_ROOM_PLAN.md's SM57 row and its milestone A7 ("more mics"). Nothing is built.

## The target

The SM57 is the mid-forward pole of MIC_ROOM_PLAN.md's opposite chains: a presence peak
around 4-6 kHz, transients blunted by a heavy moving coil, and a response that depends on
the preamp it drives. The SM58 is the same family with a ball grille and foam in front.

Published facts (Shure's user guide and spec sheet, to be archived in
`data/schematics/shure_sm57/`): cardioid dynamic; 40 Hz-15 kHz; open-circuit sensitivity
-56.0 dBV/Pa (1.6 mV) at 1 kHz; rated impedance 150 ohm (310 ohm actual). The Unidyne III
cartridge (Ernie Seeler, 1959) first went into the Model 545; the SM57 (1965) and the SM58
use it. The SM57 has an internal output transformer (a 50 ohm tap was removed in the
1980s, per a Shure history; web: https://en.wikipedia.org/wiki/Shure_SM57). The SM7
uses a modified Unidyne III without a transformer.

## Why it is a new kind of mic

The U47 and the 4134 are condensers: a light diaphragm whose position is read out at
GOhm, with no back-reaction from the load (`capsule.py` leaves it out on purpose). A
moving-coil capsule differs in three ways:

1. **It is a loudspeaker run backwards.** The coil moves in a magnet gap: its EMF is
   B l v, and the current the load draws is a force B l i on the diaphragm. So the
   preamp's input impedance damps the moving system and moves its response. Under the
   "one coupled simulation" rule this comes out by itself, as long as the coil, the
   transformer, the cable and the preamp's input are one netlist (MIC_ROOM_PLAN.md: "a
   ribbon or dynamic loaded by the preamp's input impedance").
2. **Its cardioid is a single diaphragm behind an acoustic phase-shift network**, not
   two diaphragms. Rear ports around the cartridge feed damping screens, cavities and the
   narrow annular gap around the coil. That network delays and filters the rear pressure
   so that sound from behind cancels (Bauer's "Uniphase" principle, the ancestor of the
   Unidyne line).
3. **There is iron inside:** the output transformer, a small core at very low flux, so
   its Rayleigh region matters.

## What we already have

| Piece | Where | Used for |
|---|---|---|
| Capsules as components; front / rear entry pressures as control inputs; proximity effect from the spherical wave | `varimu/devices/capsule.py`, parts `capsule` / `capsule_dual`, `varimu/rooms/entries.py` | The SM57 enters the room loop exactly like the U47 |
| Axisymmetric BEM for the entries (body of revolution) | `varimu/mics/bor.py` (`K47@3`, `BK4134@2`) | The SM57's body and grille diffraction |
| The electrodynamic transducer: BL, LR-2 coil (Re, Le, L2 \|\| R2), the motional network, modes hung from the coil | `varimu/devices/speaker.py` (`P12R@1`) | The same physics with sound in and volts out |
| Webster ladders | `varimu/phono/horn.py` | Ducts long against a wavelength |
| Magnetostatic FE maps (the Rhodes pickup); the winding window's 2D FEM | `varimu/rhodes/pickup.py`; `varimu-components fem` | BL(x) from the magnet's geometry; the transformer's leakage |
| Transformer components (JA cores, the C2 designer, `component: NAME@N`) | `crates/varimu-components`, `config/designs/` | The output transformer |
| Johnson noise on acoustic and electrical resistances | B5's noise | Self-noise with no extra feature (the coil's DCR dominates) |
| Chains, the Room view | `scripts/compose_chain.py`, `room_print.py` | `sm57_v76` into rooms |

Nothing here needs the BJT model: the SM57 is passive, and the V76 and `clean_pre` exist
to drive it into. The "SM57 -> API 312" pole waits for MIC_ROOM_PLAN.md's A8.

## The model, part by part

### The acoustic network (impedance analogy, pascals as volts)

- **Front:** the front entry's pressure on the dome. The air between the dome and the
  grille is a compliance. The grille screen is an acoustic resistance and mass in series.
- **The moving system** couples to the electrical port through a gyrator of ratio
  B l / S_d (volume velocity U = S_d v; EMF = B l v; the net pressure on the diaphragm
  times S_d is the force B l i). It is built from two `Vccs`, or as a new IR element if DK
  works better with one; decided at the build. The dome plus surround: mass, compliance
  and loss. The coil: its moving mass rides on the dome.
- **Behind the diaphragm:** the cavity under the dome, the coil's annular gap (a
  viscous slit: a resistance and mass per unit length, Poiseuille between parallel
  walls), the magnet's centre vent if present, the rear chamber, and the rear ports with
  their damping screens (felt or cloth) to the rear entry's pressure. A duct that is
  long against a wavelength at the top of the band becomes a Webster ladder, not a
  lumped mass. The cartridge is about 2 cm across, so at 4-6 kHz lumped elements are
  borderline. Which ducts need ladders is measured: each one is checked against its own
  ladder.
- **Proximity effect** is not a feature: the entries' pressures come from the spherical
  wave and the body's BEM, as for the K47.

### The diaphragm's modes

A dynamic diaphragm stops moving as a piston near the top of the band, where the
presence peak and the rolloff are. An axisymmetric shell FE of the dome and surround
(the thickness, the formed profile and the polyester's modulus and density) gives its
modes. They hang from the coil the way `speaker.py` hangs breakup modes from the cone,
but derived from geometry, not fitted. Each mode also has its own pressure-weighted area,
since the front and rear pressures act on its shape, not on a piston. Only axisymmetric
modes: the entries' pressures are azimuthal order 0 (bor.py), so other modes are not
driven.

### The magnet and B l(x)

A 2D axisymmetric magnetostatic FE solution of the magnet, the pole pieces and the gap
(the Rhodes pickup's method) gives B l as a function of the coil's displacement x, and
the gap's field leakage. Linear first: B l at rest, checked against the sensitivity. Then
B l(x) and the suspension's stiffness K(x) as a nonlinear device for very high SPL (a
kick drum or a guitar cab at 140 dB+). That is a new device model, so by the Hard rules it
gets a Python reference, a circuitsim port and a SPICE implementation, with agreement
tests. The coil's inductance with its eddy currents in the pole pieces (the LR-2 form) is
fitted to the impedance curve where one is published, else derived from the FE solution.

### The output transformer

A component like `OT_5E3` / `BV191`: a construction (core, turns, layers) in
`config/designs/`, compiled by `varimu-components`, on a JA core at the cartridge's tiny
flux. The turns ratio comes from the transformer-removal mod's level change and the
rated / actual impedance. The core and wire come from teardown photos, provisional where
missing. The pre-1980s transformer, with its 50 ohm tap (the user's choice, Decisions),
is version 1.

### The body and grille

- **SM57:** the body as a body of revolution in `bor.py`. The grille is a short perforated
  cap close to the dome. First as rigid with the screen in the network; then as a
  permeable surface (below), if the response asks for it.
- **SM58:** a **permeable surface in the BEM**, which bor.py doesn't have yet. The wire
  mesh is a thin resistive sheet (a transfer impedance), and the foam is a porous layer
  (Delany-Bazley first; Johnson-Champoux-Allard if the data ask for it). The air inside
  the ball is a resonator in front of the cartridge, likely part of the SM58's own
  presence shape. Checked on the textbook cases first: a permeable sphere against its
  series solution.

### Noise and level

The coil's DCR and every acoustic resistance carry Johnson noise (B5). There is no
self-noise parameter. A dynamic's output is ~1.6 mV/Pa, so the preamp's noise will
dominate, which is the real behaviour.

## How it would fit the code (a proposal)

- `varimu/devices/moving_coil.py`: the component kind `moving_coil` (MIC_ROOM_PLAN.md
  names it): geometry and materials in, lumped elements out at fit time, `formulas` and
  sources per block, like `capsule.py`.
- A part `moving_coil: [front, rear, plus, minus]` in both builders (bit for bit,
  `tests/agreement.rs`), the entries' pressures as control inputs, as `capsule_dual`.
- `config/components/sm57/<N>.yaml`; `config/circuits/shure_sm57.yaml` (the cartridge,
  the transformer, the XLR's pins); the chain `sm57_v76.yaml` by `compose_chain.py`;
  `room_print.py` and the Room view's chain list pick it up.
- `scripts/fit_sm57.py`: each unknown fitted to its own published figure (below).
  `tests/test_moving_coil.py` (the network's limits, the gyrator's energy balance, the
  shell FE against Kirchhoff plate modes), `tests/test_sm57.py` (the published figures).
- Sources and teardown photos in `data/schematics/shure_sm57/README.md` (SM58 alongside),
  provenance as `data/datasheets/README.md` asks.

Mics render offline in the room loop, so real time is not a constraint. DK's cost still
grows with the square of the states (CLAUDE.md), so measure a render's speed once the
labyrinth's ladders and the modes are in.

## Fitting and verification: one figure per unknown

As the K47: build from geometry first, then fit only what the sources leave open, each
unknown to a different figure, so one figure never absorbs another's error.

| Unknown | Fitted to |
|---|---|
| B l (at rest) | Sensitivity, -56.0 dBV/Pa at 1 kHz, through the transformer, open circuit |
| Moving mass, suspension compliance | The bass rolloff and the impedance curve's resonance |
| Rear screens' resistances | The polar plot's front-to-back ratio at the published frequencies |
| Coil Le, L2, R2 | The impedance curve above resonance (if published; else derived) |
| Transformer ratio | Rated vs actual impedance and the transformerless mod's level |

Checked, not fitted (the done-when criteria, Decisions 3):

- Free-field on-axis response against Shure's curve: within +-2 dB 50 Hz-10 kHz, +-3 dB
  to 15 kHz.
- Polar plots at Shure's published frequencies: front-to-back within 3 dB.
- Proximity effect against the user guide's bass-boost curves at its stated distances.
- The response into 150 ohm, 600 ohm, 2.5 kOhm and open circuit: its shape against
  published loading measurements (to find).
- Johnson noise of the coil's DCR at the output against the sensitivity: an equivalent
  self-noise that matches published estimates for dynamics (to find; Shure publishes none).

## Milestones

1. **SM1. Sources.** Shure's user guide, spec sheet, response and polar plots,
   proximity curves (archived, digitized with provenance sidecars); Seeler's Unidyne III
   patent(s); Bauer's Uniphase paper; Olson's and Beranek's treatments of single-diaphragm
   cardioids; teardowns with dimensions (diaphragm, coil, gap, ports, screens, magnet,
   transformer). *Done when:* every network element has a source or a provisional
   estimate with its reasoning, catalogued in the README.
2. **SM2. The cartridge, lumped.** `moving_coil.py`, the part in both builders, the
   gyrator, the rear network as lumped elements, the body as a sphere first.
   *Done when:* the fitted unknowns hit their figures and the agreement tests pass in
   both builders.
3. **SM3. Ducts and modes.** Webster ladders where a duct asks for one; the dome's
   shell FE and its modes hung from the coil. *Done when:* the on-axis response meets the
   tolerance to 15 kHz.
4. **SM4. The body.** The SM57's real body in `bor.py`. *Done when:* the polar plots
   meet their tolerance at every published frequency, and proximity matches the guide's
   curves.
5. **SM5. The transformer.** The design compiled by `varimu-components` and pinned by
   the circuit; the loading checks. *Done when:* sensitivity and the actual impedance come
   out of the circuit, and the response into the four loads has its published shape.
6. **SM6. In the chains.** `sm57_v76`; into the Room view; a first listen (an SM57 on a
   guitar cab or a snare against the U47 in the same scene). *Done when:* the user hears
   it.
7. **SM7. High SPL.** B l(x), K(x) as a device in Python, circuitsim and SPICE.
   *Done when:* the agreement tests pass, and the distortion at 140-150 dB SPL is in the
   range published measurements show (to find).
8. **SM8. The SM58.** The permeable BEM surface (mesh and foam), checked on a permeable
   sphere, then the ball grille; the SM58's own sensitivity and curves. *Done when:* the
   SM58's published response and polar plots meet the same tolerances.

The SM57 is complete at SM6. SM7 and SM8 follow, in either order (Decisions 4).

## Condition dials (realistic first, then bend)

Once the nominal mic matches, the bends are physical (memory: realistic first, then bend):
a dented grille (the cap pushed toward the dome: less front air, a shifted peak), a torn or
clogged rear screen (the cardioid's null fills: it goes omni-ish), a weakened magnet (B l
down: quieter, less damped, a boomier resonance), the transformer removed (the
transformerless mod), and the preamp's input impedance as a knob.

## Sources to find

- Shure: SM57 / SM58 user guides and spec sheets (response, polar, proximity, impedance);
  the Unidyne III history; any Shure engineering paper on the cartridge (Torio & Segota,
  who wrote on the dual-diaphragm capsule, are Shure engineers: check for a dynamic
  companion).
- Patents: Seeler's Unidyne III (to locate on Google Patents by inventor); Bauer's
  Unidyne / Uniphase patents.
- Bauer, "Uniphase unidirectional microphone", JASA (1941) (model knowledge: to confirm the
  citation); Olson, "Acoustical Engineering"; Beranek, "Acoustics" (single-diaphragm
  cardioids, slits and screens).
- Teardowns with measurements (forums, iFixit's SM57 page), transformer-mod write-ups
  with before / after levels, independent measurements of SPL handling and loading.
- For the SM58's foam: Delany & Bazley (1970); Allard & Atalla, "Propagation of Sound in
  Porous Media".

## Decisions (the user's, 2026-11-05)

1. **Both mics:** the SM57 and the SM58. SM8 (the permeable BEM, the ball grille and
   foam) is in scope.
2. **The old era:** the output transformer with the 50 ohm tap, as built before the
   1980s change. SM1 looks for that transformer's construction and ratio, and for
   response and polar data from the same era where they differ from today's sheets. Its
   component is version 1. A current-era version stays possible later (components are
   versioned), but it isn't planned.
3. **Done-when tolerances as proposed:** on axis within +-2 dB 50 Hz-10 kHz and +-3 dB to
   15 kHz; front-to-back within 3 dB at every published frequency (both mics).
4. **SM7 (high SPL) after the first listen** (SM6): the linear mic covers everything below
   ~130 dB SPL.
5. **The nominal mic only:** no tolerance draw between units.

Order: SM1-SM6 (the SM57 heard), then SM7 and SM8 in either order.
