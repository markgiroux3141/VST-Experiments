# Component editor: tubes and transformers designed from geometry and materials

Drafted 2026-10-29 with the user, after a brainstorm on how deep physical simulation
can usefully go; decisions taken with the user the same day (below). **Nothing here is
built.** It runs alongside the Fender 5E3 ([DEVICE_CANDIDATES.md](DEVICE_CANDIDATES.md)),
whose output transformer is the first designed component. Work milestones in order, each
ending with its "done when" met and covered by tests, like
[DEVICE_BUILDER_PLAN.md](DEVICE_BUILDER_PLAN.md), [NATIVE_APP_PLAN.md](NATIVE_APP_PLAN.md)
and [CIRCUIT_SIM_PLAN.md](CIRCUIT_SIM_PLAN.md).

## Decisions (2026-10-29, the user's)

1. **Start alongside the Fender 5E3.** Its output transformer is the first designed
   component (C2), and the 5E3 is the first circuit that uses a designed component.
   The 5E3 is heard through a physical speaker model (C3), not a cabinet impulse
   response.
2. **Versions are pinned, always.** A saved component version never changes. Every
   circuit names the exact version it uses, so editing a component never changes an
   existing circuit; a circuit moves to a newer version only by an explicit action.
3. **The component editor lives in the native app only** (`varimu-app`, a view beside
   Play and Editor). The compiler (formulas and fitting) is Rust; no web pages. The user
   intends to retire the web app (`varimu listen`); this plan adds nothing to it.
   Retiring it is its own piece of work, not planned here: the blind A/B, ABX and
   difference listening (Phase 5's tools) have no native counterpart yet, and the
   hand-written circuits' generated drawings (`layout.py`) aren't ported.
4. **Field solvers only if a need shows up.** Tier A (formulas) is the plan; C8 is
   investigated only when a component needs what the formulas can't do.

## Why

Phase 5 showed that units within factory tolerance can't be told apart by ear. More
physics won't make the 670 sound more real. What it buys is **real knobs**: a tube
specified by its cathode diameter, grid pitch and plate spacing, a transformer by its
lamination, stack and winding plan, instead of fitted curve parameters. That serves the
user's goal (memory: "analog magic, not a clone": design devices from parts and hear
their physics) and the genome rule (physical only) more strictly than today.

The idea: a separate editor for individual components. A component is designed there,
compiled once, saved as a version, and then appears in the circuit editor's model list
like the datasheet-fitted tubes do now.

## How deep is worth going (the brainstorm's conclusion)

| Level | What is modelled | Heard? |
|---|---|---|
| 0 (today) | Behavioural fits to datasheets (Koren sections, Jiles-Atherton cores) | Baseline |
| 1 | Analytic physics: geometry and materials -> the same lumped parameters (Langmuir, amplification-factor formulas, winding formulas) | Yes, as a design change: a 0.1 mm grid move shifts gain and curvature more than tube-to-tube spread |
| 2 | Field solvers offline: 2D electrostatics with space charge for a tube's cross-section, magnetostatic FEM for a transformer; results tabulated | Only where level 1's formulas fail (unusual shapes, fringing); otherwise a cross-check |
| 3 | Particle-in-cell, per-lamination eddy currents | Practically never: electron transit times are nanoseconds, so a static I-V surface is complete at audio rates |
| 4 | Individual electrons | Only as statistics: shot noise (2qI), which B5 models directly |

So the plan works at level 1 and reaches level 2 only if needed (C8). Not worth
simulating for the audio: transit time, Barkhausen noise, skin effect in wiring at
audio, thermal expansion at audio rates, magnetostriction (heard in the room, not in
the signal).

## What exists

- **A component library in all but name.** `config/devices/*.yaml` are compiled models
  (written by `varimu fit-devices` from `data/datasheets/` with provenance sidecars, or
  from published model parameters like the 12AX7's Koren set; "don't edit by hand").
  Circuits reference them by name (`V1: {device: 12AX7, tolerance: tube}`), drawings'
  device symbols carry a `Model` field, and `varimu-circuit` (`devices.rs`) reads the
  same files in Rust.
- **The 6386 is already partly geometric.** Its device file has a `pitch_distribution`
  (a remote-cutoff grid as 32 parallel sections, `varimu/devices/fit.py`
  `PitchDistribution`). A grid-pitch profile from real geometry would produce those
  sections directly.
- **Tables.** circuitsim tabulates triode banks (`devices/triode_table.rs`); ngspice
  reads XSPICE `table2D` tables of the Python models (`varimu/devices/table.py`).
- **Transformers as circuit parts.** The `transformer` macro takes a core material
  (`config/magnetics.yaml`), cross-section, path length, gap, turns, leakage and
  winding capacitances, all as parameters of the circuit file (the 670's T101-T104,
  several provisional and genome-bounded).
- **The native app** (`varimu-app`): Play and Editor views, edits heard live at
  draft-1x, production render; `varimu-circuit` builds IR bit for bit equal to Python's
  (`tests/agreement.rs` on `export_app_fixtures.py`'s fixtures) and runs the pre-flight
  checks.
- **The fitter is Python** (`varimu/devices/fit.py`, scipy least squares). A designed
  tube needs a fitter in Rust (C5).

## Ground rules

CLAUDE.md's hard rules hold: every value has a `source` (dimensions and material
constants included); the genome is physical only; one coupled simulation; every device
model has two implementations with an agreement test (a new *table* device kind needs
the Python reference, circuitsim and SPICE `table2D`); everything seeded and
reproducible. Physics that would change existing renders comes to the user as sourced
options with numbers first (memory: "options before model changes"); with pinning, it
lands as a new version and a circuit moves to it only when the user says so.

**Rust compiles, Python reads.** The compiler exists once, in Rust. A compiled version
is data, like a device file today: Python reads it to build IR (measurement, renders,
fixtures) and never compiles, and `export_app_fixtures.py` plus `tests/agreement.rs`
keep the two builders equal on circuits that use components.

## Design

- **Source and compiled form.** A component version holds its source (geometry,
  materials, physical tolerances and ratings, each with a `source`) and its compiled
  form (what the builders read: device parameters or a table for a tube, lumped values
  for a transformer), the compiler version and a hash of both. The source is what the
  component editor edits; the compiled form is never hand-edited.
- **Versions are immutable.** Saving makes a new version (`OT_5E3@3`); a loaded
  version whose content doesn't match its recorded hash is a load error naming it.
  Circuits refer to a version (`device: 12AX7@1`). Existing device files become
  version 1 of their component with their bytes unchanged (where they live is C1's
  choice). A refit (`fit-devices`, a material refit) writes a new version instead of
  overwriting; moving circuits to it is explicit, which is also when goldens are meant
  to change. Old versions stay (they are small).
- **Moving a circuit to a new version** is an action in the native editor: it shows
  that a newer version exists and what changed, plays old against new (A/B at draft-1x,
  loudness-matched per the hard rules), and saves the circuit with the new pin.
- **Two kinds of compiled output for tubes.**
  1. *A fit to an existing device form* (Koren sections, pentode, vacuum diode) when the
     fit is good enough, with a fit report. Engines, SPICE and agreement tests stay
     untouched.
  2. *A table* when the form can't express the result (a pentode's kink, unusual
     geometries, a field-solver run): a new device kind with all three implementations.
- **Genome links survive.** Today's transformer genome parameters
  (`transformers.input.turns_ratio`, ...) link circuit parameters. A circuit's instance
  of a component keeps per-instance overrides (turns, gap, ...) with genome links and
  sources, or the genome loses its transformer dimensions.
- **Ratings.** A component carries its limits (plate and grid dissipation, cathode
  current density, peak inverse voltage, core flux density at a frequency, insulation
  voltage). `varimu-circuit`'s pre-flight checks gain a rating check at the DC
  operating point.
- **Crates.** The compiler (formulas, fitter, component format) is a new crate,
  `varimu-components`; `varimu-circuit` reads compiled versions only and doesn't depend
  on it; `varimu-app`'s Components view uses both.
- **Hearing a component.** The Components view plays a component in a circuit: the
  circuit it was opened from, or a small test circuit for its kind (a push-pull stage
  into a speaker load for an output transformer). Edits are heard live like the Editor
  view's (a value updates the stream, a structural change restarts it).
- **Not every part gets an editor.** Transformers, speakers (C3) and tubes; pickups
  later. Resistors and capacitors get material
  choices in the circuit editor's inspector, which is the device builder's B6, not this
  plan.

## Milestones

**C1. The component library and versions.** The component format with versions and
hashes (read by `varimu-circuit` and by Python; written by `varimu-components`), the
existing device files as version 1 of their components (kind "fitted", pointing at
their `fit-devices` inputs), every existing circuit pinned to them, and a model picker
in the native editor's inspector (today a device's model is shown, not chosen).
*Done when:* every circuit builds the identical IR and SPICE goldens
(`export_circuit_fixtures.py --golden` without a diff, `export_app_fixtures.py` and
`export_editor_fixtures.py` unchanged, `tests/agreement.rs` passes); a version edited
after saving is a load error that names it, in Rust and Python; the native editor
offers every library model, and choosing another one rebuilds and is heard; moving a
circuit to another version is an explicit action that saves the new pin.

*Status: done 2026-10-29.* The store: `config/components/<name>/<N>.yaml` (folder = the
lowercased name), each version's sha256 (its text with LF line ends, so a CRLF checkout
hashes the same) in `config/components/versions.lock`, a small `name:` / `  N: sha256`
file both languages parse. The twelve former `config/devices/*.yaml` are version 1 of
their components, moved with `git mv`, bytes unchanged. Readers:
`varimu/devices/versions.py` (parse, resolve, read with the lock check, save) under
`varimu.devices.library.load_device`, and `varimu-circuit`'s `versions.rs` under
`Library::device` (reading only; saving stays Python's until `varimu-components`).
References are `NAME@N`; a bare `NAME` is the latest version for tools and tests, and
both builders refuse it in a circuit (`devices.V1: '12AX7' names no version: a circuit
pins one, e.g. 12AX7@1`). Pinned: the hand-written circuits' device entries and their
device-choice parameters (`rectifier_tube`, `bridge_diode`, `bias_rectifier`), the drawn
circuits (redrawn by their scripts; the triode stage's value edited), the symbol table's
and both editors' placement defaults (`12AX7@1`, `6973@1`, `6X4@1`), the KiCad fixtures
(regenerated). The native editor's model picker lists every version (`PartLib`), the web
editor's part list too (kept working until the web app is retired). `varimu
fit-devices` compares a fit with the latest version's data and saves the next version
only when it differs. Checked: `export_circuit_fixtures.py --golden` and
`export_app_fixtures.py` without a diff (identical IR and SPICE for every circuit and
case); `export_editor_fixtures.py` changed only by the pins and the device files' new
paths in source strings; tests: `tests/test_versions.py`,
`crates/varimu-circuit/tests/versions.rs` (an edited version and an unrecorded one
refused, a bare name in a circuit refused, CRLF hashes alike, fit-devices saves only a
changed fit), `crates/varimu-app/tests/editor_draw.rs` (the picker offers every version;
swapping one rebuilds a different IR with a source naming the old version; undo).
Not done here: a new version's SPICE model name (a circuit using two versions of one
tube would clash in SPICE), and a new tube type's SPICE table grid
(`varimu.devices.table.GRIDS` is keyed by the device file's `name`); both are C5's.

**C2. Transformer designer, Tier A: the 5E3's output transformer.** The transformer
component (core material, lamination, stack, gap, windings) and its designer in the
Components view. A transformer specified by construction: a lamination from a standard
size table (EI, with its window and path length), stack, core material, butt or
interleaved stacking (-> effective gap), and a winding plan (sections, layers, wire
gauge, insulation thickness and permittivity, taps, Faraday shields). Compiled to the
lumped parameters the `transformer` macro takes by sourced formulas: DC resistance from
wire length and copper resistivity, leakage inductance from the winding geometry, layer
and inter-winding capacitance; warnings for flux density at the lowest frequency and
level, and window fill. The view shows the computed values and the response between a
stated source and load. The first component is the 5E3's output transformer
(center-tapped push-pull primary for the 6V6GT pair, secondary into the speaker load),
its construction sourced where published and otherwise provisional with bounds.
*Done when:* the formulas are tested against independent computations (closed-form
cases, and a FEMM 2D leakage solution for at least three geometries within a stated
tolerance); the 5E3 OT's compiled impedance ratio and winding resistances match the
published figures for the original or its reproductions within their tolerance; the
5E3 circuit builds with the OT pinned and renders in both builders (agreement test);
the V72's input transformer, whose full construction is published (NWDR Bauvorschrift
Nr. 191: core, lamination, stack, disc winding, turns, wire;
`data/schematics/telefunken_v76/README.md`), compiles to values consistent with the
V72's published figures;
a second version of the OT (a different winding plan) is made in the Components view
and heard against the first in the 5E3.

**C3. Speakers, physical: the 5E3's Jensen.** The user's choice for what the 5E3 is
heard through (2026-10-29): a physical speaker, not a cabinet impulse response.
*Reordered 2026-10-29 (the user's call):* C3's model comes before C2 (it doesn't need
it; the 5E3's sound isn't judged until it is heard through its speaker); the speaker's
page in the Components view comes with C2's view. Where it starts: the 5E3 already
loads its output transformer with the P12R reissue's electrical equivalent
(`config/circuits/fender_5e3.yaml`, `RSPK_E` .. `CSPK_M`: Re, Le, the motional
parallel RLC from the Thiele-Small figures; 6 ohm at DC, 37.6 at 80 Hz, 32 at 10 kHz).
The voltage across the motional branch is BL times the cone's velocity. Heard without a
speaker (the terminal voltage), the overdriven 5E3 is fizzy: 10-20 kHz is -34.5 dB of
its output's power on a guitar take (B9 step 5). A
speaker component specified by physical quantities: moving mass, suspension compliance
and mechanical loss, motor strength (BL), voice-coil resistance and inductance (with
the eddy-current losses that make it frequency-dependent), cone area; the cabinet
(open-back baffle dimensions) and the listening point (on-axis distance). In the
circuit it is its electrical equivalent: the voice coil in series with the motional
branch (moving mass, compliance and loss mapped through BL into C, L and R, plus the
air load), so it needs no new IR element and loads the output transformer the way the
real speaker does. What is heard is the sound pressure at the listening point, computed
from the cone's motion (linear acoustics: a piston's on-axis pressure follows the
cone's acceleration), with cone breakup as a modal model (each mode a resonator in the
mechanical branch with its own radiating share) and the open back as a dipole whose
cancellation is set by the baffle's size. First values from the reissue's published
Thiele-Small parameters (Jensen P12R, 8 ohm), breakup modes fitted to its published
response curve; excursion nonlinearity (BL and compliance vs excursion) is a later
option, provisional and bounded when it comes.
*Done when:* the model's impedance matches the datasheet's Re, Fs and Qts and its
impedance curve's shape; its on-axis response matches the published response curve
within a stated tolerance up to the band where the curve ends; the pressure output is
computed identically in both builders' renders (the app's production render equal to
Python's); the 5E3 renders through it and the user has heard it.

*Status: the model is built (2026-10-29, the design the user approved); open: the user
hears it, and Play's real-time load (below).*
- *The component.* `P12R@1` (`config/components/p12r/1.yaml`, kind `speaker`: voice coil,
  moving system, modes, fit report), saved by `varimu fit-devices --only P12R`
  (`varimu/devices/speaker_fit.py`; Python, like the tube fits: a Rust compiler comes with
  `varimu-components` in C2). The sheet's two curves are vector paths in its PDF, read
  exactly (`scripts/digitize_jensen_p12r.py`, `data/datasheets/jensen_p12r.provenance.yaml`):
  the page clips the plot at 8.5 kHz, the paths run to 20 kHz. The impedance trace reads as
  kz 20 log10 |Z| + z0 (both traces and the Thiele-Small Zmax agree on kz ~1.25-1.37).
- *The model* (`varimu/devices/speaker.py`'s docstring): Re, Le and the eddy-current pair
  L2 || R2; the moving system through BL (mobility analogy: mass a capacitor, compliance an
  inductor); eight breakup modes from 300 Hz, each a mass on a spring and damper hung from
  the coil, with a signed radiating share. The pressure readout: a new IR element `Vccs`
  (SPICE `G`: Python `ir.py`, circuitsim `ir.rs` / `mna.rs`, the SPICE emitter,
  varimu-circuit; other circuits' JSON is unchanged, IR_VERSION stays 3) senses each
  radiating node's BL v and drives one 1 H inductor: p_front = rho sum(S a) / (2 pi r), a
  baffled piston's on-axis far field. The back wave reaches the listener around each of the
  four baffle edges: inverted, low-passed at ka = 1.616 (705 Hz for the P12R: a piston's
  directivity at 90 degrees), delayed by its extra path (cabinet depth, edge distance,
  listening distance) on taps of one lumped delay line (62.5 us sections), each edge
  weighted by the angle it subtends. Heard: p_front - sum(w p_back). Everything is in the
  netlist; the readout draws no current (a far field doesn't push on the cone; the air
  load that does is in the sheet's free-air Mms and Qms). The macro `speaker: [plus, minus,
  out]` (`component`, `distance_m`, `width_m`, `height_m`, `depth_m`, `offset_x_m`,
  `offset_y_m`) in both builders, bit for bit (`tests/agreement.rs`); the symbol `Speaker`.
- *The fit* (`reports/devices/p12r_fit.png`): Re 6.05 ohm, Fs 79.7 Hz, Qms 13.13, Qes 2.525,
  Qts 2.118 read off the model's impedance the way they are measured (sheet: 80, 13.07,
  2.50, 2.1); impedance shape 0.5 dB of |Z| rms; the response on the IEC baffle 1.01 dB rms,
  2.6 dB worst over 20 Hz-8.5 kHz (4.8 dB rms on the unprinted 8.5-20 kHz). The finite IEC
  baffle (1650 x 1350 mm) explains why the curve shows no Qts 2.1 peak at Fs: the same edge
  model, so it is checked on the sheet before it models the cabinet. Twelve modal parameters
  sit at their bounds: the shares are a modal expansion, not ring geometry (two near-massless
  modes carry the 2-3.5 kHz presence peak with the cone's whole area). Variants with
  physical shares (area per mass at most 4x the cone's) fit 1.7-1.9 dB rms. Modal Q is
  capped at 10: the curve's points are ~1/12 octave apart and a sharper mode rang as a tone
  the sheet doesn't show. `tests/test_speaker.py` holds the tolerances (Fs +-1 Hz, Qts +-2%,
  shape 1.5 dB rms, response 2 dB rms and 4 dB worst on the printed band).
- *The engines:* circuitsim's transient (production) gives the AC model's pressure within
  0.5% at 60 Hz-8 kHz; ngspice's AC analysis within 1e-6 (`tests/test_speaker.py`).
- *The 5E3* hears `out`, the pressure 1 m on axis in front of its open-back cabinet (a
  1956 5E3's 19 7/8 x 16 1/4 x 9 1/2 in; the speaker centred, provisional); `spk` is the
  terminal voltage. Full scale 50 Pa (`full_scale.output_pascals_peak`, both parsers; the
  guitar take peaks at 40 Pa at full volume); Play shows a dB SPL meter. On the guitar
  take's loudest 8 s (production): 10-20 kHz falls from -35.5 to -59.2 dB of the power at
  volume 0.5 (-23.2 to -47.7 at full volume), 2-5 kHz rises from -17.7 to -9.8 dB; ~110 dB
  SPL rms at 1 m. The profile (`amp_suite.py`) keeps its electrical figures on `spk` and adds
  the pressure response per tone setting and SPL per row.
- *Play's load, measured* (`examples/load_profile.rs`, the guitar take, draft-2x, volume
  0.6): 1.61x real time, every block over budget (the 5E3 before C3: 0.48x). Newton's work is
  unchanged; DK's dense state update grows with the square of the states (39 -> ~120: the
  delay line 58, the modes 16). With 250 us delay sections (7 instead of 29): 0.80x, 487 of
  5844 blocks over (782 at full volume). At draft-1x: 0.85x / 0.92x (volume 0.6 / 1.0), and
  0.43x / 0.50x with the 7-section line. Through the speaker draft-1x aliases much less than
  it did on the terminal voltage: the hard-clipped 2902 Hz leaves -28.1 dB of inharmonic
  content re the harmonics at draft-1x and -34.5 at draft-2x (`tests/live.rs`; on the
  terminal voltage -7.2 and -24.1, which is why the 5E3 moved to draft-2x). Brought to the
  user as options (not built): the readout on the partition's second thread (it reads the
  driver and never acts back, so a one-way coupling is exact up to one sample of latency;
  `partition.rs` today only couples rails the second part holds), the shorter delay line,
  draft-1x for the 5E3 again, or a combination.
- *Listening files* (production, the whole guitar take, git-ignored, regenerate from the
  take): `reports/speaker/audio/5e3_take_vol{0.5,1.0}_speaker_pressure.wav` and the terminal
  voltage LUFS-matched beside each.

*Paused 2026-10-29 (the user's call: a synthesizer session may come first).* Where to pick
up, in order:
1. The user listens to the files above (C3's last done-when item).
2. The user decides Play's speed (the options above; Claude's recommendation: the one-way
   partition if the engine work is wanted, else draft-1x with the shorter delay line). Until
   then the 5E3 plays at draft-2x and can't keep up (1.61x real time): it drops out in Play.
3. Then `6V6GT@2` against `@1` through the speaker, then C2
   (DEVICE_BUILDER_PLAN.md, "Devices and components together").

*Future optimizations and options (none built):*
- *Speed, keeping the model:* the readout as a one-way partition (exact up to one sample's
  latency; or, without latency, the engine stepping a one-way linear subnetwork after the
  main solve on its own sparse factorization: its delay line is tridiagonal, so O(n) per
  step instead of DK's dense O(r^2)); DK exploiting the block-triangular structure of
  one-way networks in general.
- *Speed, changing the model (each a new speaker part or setting, heard against the
  current one):* a shorter delay line (7 sections at 250 us: the back wave cut above
  ~1.3 kHz, where its directivity pole has it -6 dB already); a delay of fewer states (an
  all-pass / Bessel cascade on Vccs and capacitors: about half the states of the LC line for
  the same delay-bandwidth); fewer modes (2 states each; the driver alone with 8 modes costs
  ~0.6x at draft-2x by the measured scaling).
- *Fidelity:* modes with physical shares (a cone model from its geometry and paper: the
  plan's "speakers designed from cone material"); excursion nonlinearity (Xmax is +-1 mm:
  BL(x), Cms(x), provisional and bounded); the radiation resistance's rise with frequency;
  the cabinet's back panels and internal resonance; the speaker's position on the baffle
  (a source; now provisional, centred); other listening points (off axis, a close
  microphone: a near-field model); a room.
- *The profile:* aliasing measured on the heard pressure as well as the terminal voltage;
  the high-frequency share on program material as a profile figure (now only in this
  status).

**C4. The existing circuits' transformers as components.** The 670's T101-T104, T302,
L301, L302 and the EQP-1A's transformers become version 1 of transformer components
(their current parameters as the compiled form; construction unknown where it is),
pinned by their circuits, with per-instance overrides keeping their genome links.
*Done when:* identical IR and goldens for every circuit and fixture case; `--set` and
genome links on transformer parameters behave as before (`genome-status`, the corner
sweep); the drawn circuits (`*_drawn`) compile to the same IR in both languages. Where
re-specifying one by construction moves its provisional values, that comes to the user
as a new version with numbers, never a silent change.

**C5. Tube designer, Tier A (triodes).** A triode specified by geometry and materials:
cathode (radius, length, coating, temperature from heater power), grid (radius, wire
diameter, material, pitch profile along its length: uniform for sharp cutoff, varied
for remote cutoff), plate (radius, or spacing for planar electrodes). Compiled by
sourced formulas: space-charge-limited current per section (Child-Langmuir with
Langmuir's cylindrical correction, the equivalent-diode method), amplification factor
per section from grid geometry, contact potential from work functions, the
initial-velocity tail near cutoff from cathode temperature, the emission limit from
cathode area, interelectrode capacitances from geometry. The computed I-V surface is
fitted to the existing device form by a fitter in Rust (Levenberg-Marquardt: a crate
or our own, the problems are small); the result is a version with a fit report. The
view overlays the computed curves on a real tube's digitized curves.
*Done when:* geometries of two real tubes (the 12AX7 and the 6386; dimensions sourced,
or back-solved from their curves and checked for physically plausible dimensions) give
mu, gm and plate resistance at the datasheet's operating points within the datasheet's
own published limits (or ±15% where none are published), and the 6386's cutoff curve
within ±10% in grid voltage; the Rust fitter refits a datasheet tube to within the
Python fit's residual; a fictional 6386 (half the pitch variation) builds, renders, and
its compression curve moves in the direction the physics predicts; every compiled
version passes the existing device agreement tests.

**C6. Ratings in the pre-flight checks.** Components carry ratings (values from
datasheets, or computed for designed components); `varimu-circuit`'s checks evaluate
them at the DC operating point at every switch combination, shown in the native editor.
*Done when:* a deliberately overdriven test circuit is flagged with the part, the
rating and the margin; every hand-written circuit and the 5E3 pass, or each flag is
shown to the user as a finding about the circuit (not suppressed).

**C7. Physical tolerances.** A designed component's spread comes from its construction
(grid pitch, spacings, coating activity, turns, gap) as seeded per-instance draws,
replacing its tolerance class.
*Done when:* the designed 12AX7's spread of mu and gm over many draws matches the
datasheet's published limits (or a sourced bogey range); draws are reproducible from the
seed, equal in both builders, and adding a component doesn't perturb other parts' draws
(the hard rules' seeding).

**C8. Tier B: field solvers, offline (only if a need shows up; decision 4).** A 2D
electrostatic solver with space charge for a tube's cross-section (iterated Poisson with
a self-consistent charge density; no particles), and FEMM (or an equivalent) for
transformer leakage and gap fringing, run offline and cached by the source hash; outputs
feed the same fitter or become table devices.
*Done when:* Tier B agrees with Tier A on regular geometries within a stated tolerance,
and the case that called for it (a planar-electrode tube, a shell core with an unusual
winding window, ...) compiles, renders and is checked against an independent result.

**Later, not planned yet:** pentodes and beam tetrodes (screen, suppressor, beam
plates, secondary emission, partition noise; the 5E3's 6V6GT is a datasheet fit first);
speakers designed from cone material and geometry (C3 starts from published
Thiele-Small parameters); pickups (coil, magnet, cable); tube microphonics (grid wire as a string
under tension, for guitar amps next to their speaker); a whole envelope as one component
(a dual triode's shared heater and spacers: hum and crosstalk, with FUTURE_DIRECTIONS.md
section 4).

## Order and why

The milestones interleave with the device builder's B9 (the 5E3) and B10 (the V76):
[DEVICE_BUILDER_PLAN.md](DEVICE_BUILDER_PLAN.md), "Devices and components together",
is the sequence. Within this plan: C1 first: everything needs versions and pins, and it is invisible (identical IR). C2
next, alongside the 5E3: its output transformer is a component the 5E3 needs anyway,
transformer formulas are textbook engineering with good cross-checks (FEMM), and it
proves the whole loop (design, compile, pin, hear) on a new circuit with nothing to
keep byte-identical. C3 (its model) before C2 since 2026-10-29: the 5E3 is heard through its speaker (the user's
choice), and a speaker is a component the same way. C4 brings the existing transformers into the library without
changing them. C5 after the transformer: tube geometry data is thinner and it needs the
Rust fitter. C6 and C7 make designed components safe and realistic to use. C8 only on
demand.

## Risks

| Risk | Mitigation |
|---|---|
| The 5E3 OT's construction isn't published (confirmed 2026-10-29: only frame sizes) | Published impedance and resistance figures (original and reproductions) as targets; construction provisional with bounds; the Rust formulas checked on FEMM regardless |
| Published electrode dimensions of real tubes are thin | Back-solve geometry from datasheet curves and check the dimensions are physically plausible; teardown photographs with a scale; mark dimensions provisional with bounds |
| Transformer validation data (construction plus measured leakage and capacitance) is rare | FEMM as the independent check; manufacturers' application notes; replacement transformers' published figures |
| Tier A misses real-tube effects (contact potential, coating non-uniformity, grid emission) | Report the fit against a real tube's curves; keep datasheet fits as the versions real circuits pin, designed tubes as options |
| The Rust fitter is less robust than scipy's | Test it on every existing datasheet fit (C5's done-when); the existing fits stay as they are (version 1) either way |
| Pinning leaves old versions everywhere | Versions are small; the editor shows which circuits use which version |
| Physics depth with no audible payoff | Every milestone ends with a render that shows what moved; Tier B only on demand (memory: "flag diminishing returns") |

## Open

- ~~Version syntax and layout~~ (C1): taken 2026-10-29: `NAME@N`, one folder per
  component (C1's status).
- **Ratings in Python's `varimu check`** (C6): default no, the native app's checks only.

## Sources (starting points; verify each before it sources a value)

- K. R. Spangenberg, *Vacuum Tubes* (McGraw-Hill, 1948): space charge, the
  equivalent-diode method, amplification-factor formulas, cathode emission, design
  examples.
- C. D. Child (1911) and I. Langmuir (1913): space-charge-limited current;
  I. Langmuir and K. B. Blodgett (1923): cylindrical electrodes.
- F. B. Vogdes and F. R. Elder (1925): formulas for the amplification factor of triodes
  from grid geometry.
- O. W. Richardson, S. Dushman: thermionic emission (temperature-limited current, work
  functions of oxide cathodes).
- RCA and Philips tube design literature (e.g. the RCA *Receiving Tube Manual*'s
  technical sections, Philips' *Electronic Valves* series) for typical dimensions and
  materials.
- C. W. T. McLyman, *Transformer and Inductor Design Handbook*: lamination tables,
  winding resistance, leakage inductance.
- A. Massarini and M. K. Kazimierczuk (1997): self-capacitance of windings.
- P. L. Dowell (1966): winding AC resistance (to show it is negligible at audio).
- D. Meeker, FEMM (femm.info): 2D magnetostatics for the leakage cross-check.
