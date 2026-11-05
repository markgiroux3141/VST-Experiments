# The Shure SM57 (and SM58) from physics

Drafted 2026-11-04 from a conversation with the user ("are there any microphones that we
could make like an SM57 or SM58 to add to our list? what would this entail. No shortcuts
and in keeping with our physics approach", then: "yes, let's write this plan"; the user's decisions 2026-11-05, see "Decisions"). It
expands
MIC_ROOM_PLAN.md's SM57 row and its milestone A7 ("more mics"). SM1, SM2 and SM3 done, SM4's
polars done (its proximity open), SM6 started: a first print (2026-11-05, overnight in the
`sm57` worktree): see "Status".

## Status (2026-11-05)

**SM1 done:** the sources in `data/schematics/shure_sm57/README.md`: Shure's 1965 / 1968
SM57 sheet 27A308 and the 1970 SM58 sheet with the dual-impedance transformer (wiring, the
taps' voltages), the catalogs to 1993 (the tap went between the 1986 and 1988 catalogs, not
"in the 1980s" generally), the user guides; Seeler's 1961 JAES paper (the Unidyne III's
network and design equations) and the patents (US 3,240,883 the Unidyne III, US 3,132,713 the
diaphragm, US 3,989,905 the shock path, Bauer's Uniphase); bench measurements of the
transformer (cj06: 1 : 4.53, 1.50 / 24.18 ohm, 386 mH / 7.95 H, 150 uH / 4.26 mH leakage; an
old dual unit's 10.8 / 25.7 ohm), the coil (12.1 ohm, ~200 uH), the resonance (~100 Hz,
Shure's Born). No dimension of the cartridge is published anywhere found: the geometry is
provisional and bounded, each element's reasoning in the README's table. Digitized: the
response and polars of every era for both mics (`data/datasheets/shure_sm5{7,8}_*.csv`, their
provenance sidecars). Not found: proximity curves, an impedance curve, loaded responses, the
transformer's construction.

**SM2 built (the Python half verified; the Rust half written, its agreement test building):**
- `varimu/devices/moving_coil.py` (kind `moving_coil`): the acoustic network is data, a list
  of physical elements (screen, tube with Poiseuille or Crandall's wide-tube loss, slit,
  cavity, the cap's thin air `film`, `acoustic`, `seeler`, the `diaphragm`) compiled to R / L
  / C and a gyrator (B l / S, two Vccs); the moving mass from its parts (the coil's copper
  length B l / B at the measured DCR). `seeler_rear_network`: Seeler's Eqs. 5-10. **His
  "larger root" gives Lb < 0 with the equations as printed; the smaller root gives a
  physical network (both satisfy the series): the code takes the physical one.**
- The part `moving_coil: [front, rear, plus, minus]` in both builders (Python `parts.py` /
  `builder.py`; Rust `varimu-circuit/src/moving_coil.rs`), its symbol in both tables, noise
  on every resistance but the diaphragm's numerical DC leak.
- The head as a sphere, the rear entries a ring on it (`free_field.sphere_ring_factors`,
  the addition theorem).
- `R57@1` (`config/components/r57/1.yaml`), fitted by `scripts/fit_sm57.py` (one figure per
  unknown): sensitivity 1.488 mV/Pa against s68's 1.49; the on-axis response 50 Hz-4 kHz
  0.71 dB rms (max 2.1) against s68; the polars against c81 (side / rear): 125 Hz -4.9 /
  -10.8 (published -3.8 / -10.8), 1 kHz -7.0 / -19.6 (-6.1 / -20.7), 2 kHz -6.7 / -22.2
  (-6.05 / -20.0). Found on the way: the 125 Hz pattern is first order with the network's
  delay ~1.8 times the entries' path, which the case and handle's air behind the washer
  gives (pat883's branch C'b; Born: "part of the tuning process"): fitted, 4.6 cm^3 behind
  2.0e7 Pa s/m^3; the rear entry sits at 98 degrees on the sphere. Moving mass 106 mg
  (84 mg of it a 2.57 m, ~68 um copper coil at 12.1 ohm): no source either way.
- `config/circuits/shure_sm57.yaml`: R57@1 into the transformer (cj06's figures, a
  provisional mumetall core whose gap gives 386 mH; the H / L switch, s68 Figure A), open
  circuit. `tests/test_moving_coil.py` (the network, Seeler's series, a cardioid, the gyrator
  against a closed form, the formulas), `tests/test_sm57.py` (the figures above).

**SM2 done** (the Rust half too: `tests/agreement.rs` bit for bit on `shure_sm57`, fmt and
clippy clean).

**SM4's body, built ahead of SM3** (the order changed overnight: SM3's done-when, the
on-axis response to 15 kHz, can't be judged on a sphere, and the sphere couldn't make the
presence peak without breaking the rejection): `bor.dynamic_mesh` (body form `dynamic`: the
cartridge's face, a band of rear ports on its side averaged over its area (`Mesh.uniform`),
the closing ring, the grille head, the taper and the connector end from s68 Figure C; the
grille open, its screen in the network); `scripts/fit_sm57.py` on the body (entries cached in
`cache/sm57/`, the port band a grid: `--ports-mm`, best at 3-9 mm behind the face), the band
50 Hz-6.5 kHz with a guard above. **R57@2** (the circuit pins it): sensitivity 1.491 mV/Pa;
on axis 1.08 dB rms (max 2.1) to 6.5 kHz, **the presence peak from the body's diffraction**
(the handle baffles the face: +6 dB at 6 kHz on the front entry), no resonator tuned to it;
the polars at every published frequency within 3 dB (c81, side / rear, model vs published:
125 Hz -4.2 / -11.0 vs -3.8 / -10.8; 1 kHz -5.6 / -19.6 vs -6.1 / -20.7; 2 kHz -6.3 / -19.4
vs -6.05 / -20.0; 4 kHz -6.8 / -15.8 vs -9.2 / -13.5; 8 kHz rear -9.2 vs -11.2): SM4's polar
done-when met. The gap's field is fitted with B l to the sensitivity (the coil's mass grows
as (B l / B)^2 at its measured DCR, so the output has a ceiling the field sets): B l 0.62 T m,
B 1.14 T, moving mass 9.6 mg (a light coil, 0.55 m of wire: no source either way). At bounds:
the handle's volume at the body's 20 cm^3 (the air behind the washer: the fit wants all of
it). **Proximity** (no Shure curve, only text: "6 to 10 dB at 100 Hz" at about 6 mm): the
model gives +18 dB at 100 Hz at 6 mm from the cartridge's face, +16 at 25 mm, +8 at 100 mm,
+2.5 at 300 mm (re 1 kHz). Not tuned to it: a sentence with an ambiguous distance (the grille's
tip or the face behind it), and first-order theory with the 125 Hz pattern gives more still;
open, for the user. `tests/test_sm57.py` checks R57@2 on its body.

**SM3's ducts (the cap), R57@3** (the circuit pins it): on the body, the cap's holes and its
air layer gridded against s68 at 6.5-14 kHz (`film` height 0.072 mm effective, holes 0.75 mm;
the layer's loss is set by its thinnest part, where the dome rises toward the cap), then the
network refitted: sensitivity 1.487 mV/Pa; on axis 0.60 dB rms (max 1.7) to 6.5 kHz and 2.42
dB rms above; the polars within 2.4 dB at every c81 frequency (125 Hz -3.9 / -10.4, 1 kHz
-5.7 / -19.9, 2 kHz -6.2 / -19.4, 4 kHz -6.8 / -15.8, 8 kHz rear -9.5; published as above).
**The moving system's resonance came out at 97 Hz**, Born's "in the 100Hz area", which wasn't
a target (the low end was). B l 2.45 T m, B 1.2 T (at its bound, the sensitivity met), moving
mass 69 mg, the air behind the washer 2.5 cm^3. R57@2's geometry records the handle's volume
as the string '2e-05' (PyYAML reads an exponent without a decimal point as a string; its
lumped value is right, and the builders read only that); fit_sm57.py's writer is fixed.

**SM3 done: the dome's mode, R57@4** (the circuit and the chain pin it). A mode hung from
the coil (`moving_coil.py`'s diaphragm `modes`): a mass on a spring and damper in the
mobility analogy on the gyrator's electrical side (the port's voltage is B l v of the coil,
as speaker.py's cone modes), with its own gyrator to the diaphragm's acoustic port (its area
S_k: the pressure pushes it, its velocity moves air); the rigid part keeps the rest of the
mass and area. A stiff mode is the cartridge without it (tests/test_moving_coil.py). Not a
shell FE: pat713's dome is two molded cones with bridges that break axial symmetry, and no
source gives its dimensions, so the mode's four values are provisional and fitted (bounded:
f 5-16 kHz, q 0.7-10, mass 2-50%, area 5-60%): 8.15 kHz, q 5.0, 14% of the mass, 5.1% of the
area (near its bound). Fitted with the network on s68's whole curve: **0.69 dB rms, 1.76 dB
worst, 50 Hz-14 kHz** (SM3's +-2 dB to 10 kHz and +-3 dB to 15 kHz met: `tests/test_sm57.py`
test_on_axis_to_15_khz), the dip at 7.7 kHz and the second peak at 9.6 kHz drawn; the polars
unchanged (within 2.4 dB); 1.488 mV/Pa; the resonance 104 Hz (Born's ~100); B l 2.28 T m, B
1.2 T (bound), moving mass 60 mg. The Rust half (the gyrator's `c`, `@v` / `@minus`) agrees
bit for bit. Webster ladders weren't needed (no duct here is long against a wavelength
below 14 kHz: the longest, the rear slit's ~10 mm, is a fifth of one at 7 kHz).

**SM6 started: the chain and a first print.** `sm57_v76.yaml` (compose_chain.py; a mic
without a tolerance block allowed), `mic_print.py` finds a cartridge. The 5E3 take (the
amp's sound pressure, the same source the U47 was printed from) at 100 dB SPL on axis into
SM57 -> V76 at 58 dB (the SM57 is ~24 dB less sensitive than the U47, printed at 34):
`reports/mics/audio/sm57_v76_5e3_take_vol0.5_speaker_pressure_100db_0deg_gain_db_v7658.wav`
(R57@3; reprinted with @4 below), peak -1.6 dBFS, 5.5x real time. Against the dry source, re
1 kHz: -5.9 dB at 63 Hz, -1.8 at 125, +2.4 at 4 kHz, +4.5 at 5.6 kHz, +5.3 at 8 kHz.

Reprinted with R57@4 (same names, overwritten): the 5E3 take at 100 dB SPL (V76 at 58 dB) and
the vocal `vocal_longwayhome.wav` at 94 dB SPL (V76 at 64 dB: the U47 was printed at 34 / 40),
both peaking at -1.7 dBFS, 5.9x real time. The U47's prints of the same sources are in main's
reports/mics/audio/ (same SPL, the V76 24 dB lower).

**SM5's loading checks, on the provisional transformer** (`scripts/sm57_loading.py` ->
reports/mics/sm57_loading.json; tones at the front entry, the JA core at 74 dB SPL): the
output impedance at 1 kHz is 354 ohm on 'H' and 89 ohm on 'L' (published: s68 '150-250' and
'30-50' ohm ratings; c88 '310 ohms actual'; a forum quote of an old rating '38 ohms (70
actual)'; ee18 a vintage SM57 228 ohm at 1.28 kHz; hau's two figures imply ~245-250 ohm).
Re open circuit at 1 kHz, 'H': -1.4 dB into 2 kOhm (hau ~1), -7.6 into 250 ohm (hau 6), -4.0
into 600, -10.5 into 150. Below 200 Hz the loading bites much harder (into 150 ohm -17 dB at
50 Hz, -20 at 100 Hz: the motional impedance peaks at the 104 Hz resonance; Stamler's 'the
most load-sensitive dynamic microphone' fits, no curve to check). The impedance is 15-40%
high: 4.53^2 x (1.5 + 12.1 ohm + the motional part) + 25.7 ohm, the ratio and the coil's DCR
both forum figures from later units; the old sheets' lower sensitivity ('H' 0.149 mV/ubar
against 0.16-0.17 from 1974 on) hints at a lower old ratio. Not forced here: SM5's designed
transformer settles the ratio (a small lamination is being sourced: the designer's smallest,
EI-375, doesn't fit the ~23 mm handle).

The sphere-era notes follow.

The presence peak and above were not in SM2: the model has no presence
peak (~11 dB short at 5.8 kHz), a small bump at 11 kHz and a notch at 12.5 kHz. Why: on a
sphere the presence peak's position pins the network's delay against the 1-2 kHz rejection
(fitted to 6.5 kHz, -16.9 dB at the rear against -20.7), and a lumped front resonator
can't draw the dip and second peak (a grid over the cap's holes and air: 5.3 dB rms at
4.5-14 kHz at best; a series screen damps it but costs the rejection; the cap's thin air
layer's radial flow damps it without that cost: the `film` element). So: the real head's
diffraction (SM4: a cylinder with a grille face, not a sphere) and the dome's modes and a
distributed cap (SM3), then R57@2. The 4 / 8 kHz polars (4.2 dB off at the side at 4 kHz,
6.6 dB at the rear at 8 kHz) are SM4's.

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
