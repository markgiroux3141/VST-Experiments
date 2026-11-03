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

*Decisions (2026-11-04, the user's):*
1. **The leakage check is our own 2D FEM**, not FEMM (not installed; the user prefers own
   tools): a small magnetostatic solver of the winding window in Rust (leakage is a linear
   field problem: A_z on triangles, the windings as current-density regions, the core as a
   high-permeability boundary), plus closed-form cases and the 5E3 OT's measured leakage.
   It replaces "a FEMM 2D leakage solution" in the done-when; C8 can grow from it.
2. **The 5E3 OT first, then the V76's T85.** The 5E3 OT is the one with measured targets for
   everything the designer computes (Amplified Parts P-TGO-002: DCR 147.2 / 195.3 ohm per
   half, 0.493 ohm secondary, 3.67 H per half, leakage 40.47 / 19.31 mH per half;
   `data/schematics/fender_5e3/README.md`); the V72's BV 191 is compiled as a check (its
   construction is published: `data/schematics/telefunken_v76/README.md`). Then T85 version 2
   for B10's two misses (the 90 Hz bump, 40 Hz distortion; no BV 511 construction exists, so it
   stays provisional), then T89, the chokes, the U47's BV 8.
3. **Leakage per winding:** the `transformer` macro gets an optional per-winding leakage
   (both builders; a circuit without it builds the identical IR, goldens unchanged). Today's
   one total split half per side can't hold the 5E3 OT's 40.5 / 19.3 mH halves.
4. **The compiler first, then the view:** `varimu-components` (the format, the lamination
   table, the formulas, compiling and saving a version) with a CLI and tests, then the
   Components view (edit, computed values, the response, heard in a test circuit), both in C2.

*Steps:*
1. **Done 2026-11-04:** the macro's optional per-winding leakage, a winding's `leak` (its own
   series leakage inductance, H; Python `parts.WindingSpec.leak_h` / `builder.py`, Rust
   `parts.rs` / `builder.rs`); `leakage_h` (the total) may be left out when every winding
   has one, and a winding with neither is refused (`tests/test_circuit_format.py`).
   Goldens, `export_app_fixtures.py` without a diff; `varimu-circuit`'s tests pass. Not
   carried by the KiCad / editor symbols yet (`Winding`'s fields are ratio, r, c): designed
   transformers come in by `component:` (step 3), not drawn values. Both builders' agreement
   on `leak` comes with the first circuit that uses it (step 6).
2. **Built 2026-11-04** (status below): `crates/varimu-components`: the transformer source format (lamination from a sourced
   table: EI / UI sizes with window and path; stack, stacking factor, butt gap or
   interleaved; material from `config/magnetics.yaml`; bobbin; winding plan: sections in
   order, turns, wire (bare and insulated diameter), layers, insulation thickness and
   permittivity, taps, shields), compiled by sourced formulas: mean turn length and DCR
   (copper at 20 C), area and path, the gap, per-winding leakage (the window's MMF profile,
   energy method, interleaving), layer and interwinding capacitance; warnings for flux density
   at a stated lowest frequency and level and for window fill. Saving a version (and its lock
   line) from Rust; Python reads only. The compiled form is what the macro takes (core,
   turns, per winding ratio / r / c / leak, interwinding).
   *Status (2026-11-04):* `crates/varimu-components` (depends on `varimu-circuit` for YAML,
   versions and materials; nothing depends on it). The design format is `design.rs`'s
   docstring (designs live in `config/designs/`; drawn disc dimensions `width_m` /
   `build_m`, BV 191's "the discs' geometry is binding"; `shield` sections, a foil with a
   terminal of its own); the tables are `config/transformer/{laminations,wire,dielectrics}.yaml`
   (laminations: Tempel's catalog for US EI / UI, Waasner and SEKELS / VAC for DIN 41302 EI and
   UI, every sourced path reproduced by the dimensions within 0.5%, `tests/tables.rs`;
   wire: NBS Handbook 100 for AWG and IACS copper, MWS after NEMA MW 1000, Elektrisola
   after IEC 60317-0-1; dielectrics: DuPont, Arclin, NBS; enamel, kraft, polystyrene and
   pressboard provisional with bounds in notes: no primary source found). Formulas, each
   cited in its module: the turn length McLyman [4-23]; DCR from the layers' turns; the
   gap two joints, a spacer's fringing McLyman [10-11]; leakage the exact 1D energy integral
   of the MMF profile (Shen et al. TPEL 2021 eq. (14), Mogorovic & Dujic ECCE 2017 eq. (9)),
   copper as the equal-area square (Shen eq. (2)), Rogowski's K_R on the field length
   (layer windings: the layers' length; disc windings: the build, McLyman [17-5]; both
   clamped to the window); layer capacitance Shen et al. TPEL 2019 eqs. (3)-(4), the section
   4 (m - 1) / (3 m^2) by energy (eq. (10), (A.1)), foils by the layer's image (ours). The
   compiled block is the macro's values (core, turns, per winding ratio / r / c / leak,
   interwinding, shields); `report` holds the derivations (short-circuit pairs, Lm in the
   linear limit, flux at the rating, fill) and warnings. Leakage: a star (per-winding
   `leak`) when it is exact and positive, else coupled series leakages (`leak_couplings`):
   the IR refuses negative inductances and a star of three windings over each other has
   one (open decision below). Saving: `store.rs` writes the version and the lock exactly as
   Python's `write_lock`; nothing is saved when the body equals the latest version's. CLI:
   `cargo run -p varimu-components -- compile|save DESIGN [--yaml] [--short p1+p2:s]`.
   Tests: hand computations (`tests/compile.rs`: core, DCR, leakage, flux, refusals, shields,
   saving through `versions::read_text`, PyYAML reads the file), the textbook cases
   (c1/3 + g + c2/3, interleaving's 1/p^2, three windings), Ouyang et al. PEDS 2009's
   measured planar leakage (`tests/measured.rs`: +2.9%, +0.3%; their fully interleaved case
   -21%, which the paper puts on its terminations). A first look at BV 191
   (`config/designs/v72_bv191.yaml`, not saved; mumetall stands in for Hyperm 702): the
   primary halves in series give 132 ohm shorted at 1 kHz (published <= 140; in parallel
   ~32), 23.4 H (published 25 +- 10%; the stacking factor and joint gap from SEKELS / VAC's
   EI 48 tables, the material a stand-in), and 3.62 mH of leakage
   against ~5.1 mH from the published ~500 ohm at 15 kHz (-29%; with the disc field length
   at the bare build, McLyman [17-5] without Rogowski or the window clamp, ~5.3 mH): step 4's
   FEM decides the disc field length.
   *Decided (2026-11-04, the user's):* leakage a star needs a negative branch for goes in as
   coupled series leakages (`leak_couplings`, IR `Coupling` elements; step 3).
   *Decided (2026-11-04, on Claude's recommendation, the user delegating):* (b) a component's
   interwinding capacitance connects by energy over the facing layers' end voltages (Shen et
   al. 2019 eq. (A.1); the windings' layer structure gives the ends' share of each winding's
   voltage) and a shield is a node the circuit names: built with step 6, when the 5E3 needs
   it (its OT has no shield); (c) Hyperm 702 is a provisional material calibrated to BV 191's
   printed initial permeability (12,000, likely the stacked core's, as SEKELS / VAC's EI 48
   1x1 figure for Mumetall): step 5.
3. **Done 2026-11-04** (status below): A circuit's transformer part from a component: `transformer: {component: NAME@N, ...}`
   with the circuit's nodes per winding and per-instance overrides (genome links survive);
   both builders read the compiled values; a version's hash checked as for tubes.
   *Status:* both builders (`varimu/circuit/builder.py` `transformer_spec`, `crates/varimu-circuit`
   `builder.rs`): a transformer part's `component` (a version, or a parameter naming one;
   `kind: transformer` with a `compiled` block, read through the lock like every component)
   gives the core, turns, per winding ratio / r / c / leak and `leak_couplings`; the part names
   every one of the component's windings with its nodes; anything the circuit gives overrides
   (a winding's r, the core, turns, its own `leak_couplings`), so genome links survive;
   `leakage_h` beside a component is refused. The macro's new `leak_couplings: [{between: [a,
   b], k}]` (with or without a component) adds a `Coupling` K<NAME>_<a>_<b> between two
   windings' leakage inductors; the SPICE emitter folds such couplings into the windings'
   mutual inductances (k sqrt(L_lk,a L_lk,b) added to P N_a N_b; `spice.py`). The component's
   interwinding and shield capacitances aren't connected yet (open (b)); a circuit adds its own
   `interwinding`. Every existing circuit builds the identical IR and SPICE
   (`export_circuit_fixtures.py --golden`, `export_app_fixtures.py` without a diff). The first
   saved transformer version is `BV191@1` (saved from Rust; the lock gained one line);
   `config/circuits/transformer_component_test.yaml` drives it (in the app fixtures: both
   builders agree, `tests/agreement.rs`). `tests/test_transformer_component.py`: the compiled
   values land in the IR, overrides win, refusals (unpinned, not a transformer, a missing
   winding, leakage_h, |k| >= 1, an unknown winding, a coupling without a leakage inductor),
   the SPICE matrix's short circuits equal the compiler's report (2e-3; without the couplings
   off by > 20%), circuitsim's transient against ngspice's AC on the folded matrix within
   5e-3 at 1 and 15 kHz with the secondary loaded hard.
4. **Done 2026-11-04:** The 2D FEM leakage check on at least three geometries, within a stated tolerance.
   *Status:* `crates/varimu-components/src/fem.rs`: the window's cross-section, the iron
   infinitely permeable (natural boundaries for A_z on all four sides, one node held), P1
   triangles on a tensor grid with a line at every copper edge, Jacobi-preconditioned
   conjugate gradients, the energy weighted by the turn length at each radius (as the 1D
   model); layer windings' copper as the equal-area layers, discs as full blocks. Checked:
   windings filling the window's height (the field exactly 1D) within 1e-4 (the elements'
   discretization), convergence under refinement. Against the 1D formula
   (`tests/fem_check.rs`, every winding pair): **layer windings within +-8%** (an EI-75
   output transformer P|S +1.8%, interleaved S|P|S -3.3%, the fitted 5E3 OT with ~2 mm of
   paper between its windings -3 to -7%); **disc windings within +-20%**
   (BV 191: pairs -8 to -10%, the series primary against the secondary -17%). Against BV
   191's measurement the field solution gives 4.37 mH (the ~500 ohm at 15 kHz implies ~5.1;
   -14%, the Trolitul masks' thicknesses provisional), the formula 3.62 (-29%). So a design
   may say `leakage_method: field`: the compiler solves every winding pair (a few seconds
   each) and builds the star or the coupled matrix from those pairs (the coupled gauge the 1D
   model's, or winding 0's when that isn't positive definite); the report keeps the
   formula's short circuits beside them; `Compiled::group_short_circuit_h` reads series
   groups from the compiled leakages (equal to the field solution's for three windings).
   The default stays `formula` (decision 4: the field solution where the formulas fall
   short; disc and section windings are that case). CLI: `varimu-components fem DESIGN
   [--short p1+p2:s]` prints both for every pair.
5. **Done 2026-11-04:** The 5E3 OT by construction against P-TGO-002; BV 191 against the V72's figures.
   *Status:* **`OT_5E3@1`** (`config/designs/ot_5e3.yaml`, written by `scripts/fit_ot_5e3.py`,
   which drives the Rust compiler). P-TGO-002's sheet pairs its figures with lead colours:
   Green-Red 147.2 ohm and 40.47 mH of leakage, Red-Yellow 195.3 ohm and 19.31 mH. So the
   low-resistance half is wound first and the other over it (longer turns), and the
   secondary outside both (the inner half, farther from it, leaks more; with the secondary
   between the halves both would be alike). The construction isn't published: EI-87 (the
   reproductions' 2-3/4 x 2-1/4 in frames), a 1 in stack, the material the 5E3 used before
   (grain_oriented_si_steel; M-19 is an option), layer windings; turns, wire, the paper
   between layers and windings fitted, the joint gap to 3.67 H. The wire search (AWG 33-37,
   IEC 0.112-0.18 mm, each half its own size) picks one size for both: 1041 turns per half
   of 0.13 mm (grade 1), 66 secondary turns of AWG 22 (8000 CT : 8 to the turn), 0.13 mm
   kraft between layers, 2.0 / 1.7 mm between the halves and before the secondary (the first
   two at their bounds); the search runs on the formula, the winner is refined on the field
   solution and compiles by it. Against the sheet: DCR 147.25 (+0.04%), **179.5 (-8%)**,
   0.537 ohm (+9%, the secondary's gauge step); 3.67 H; leakage 40.35 / 19.34 mH (-0.3 /
   +0.1%); 1.05 T at 15 W, 70 Hz. The outer half's -8%: one half over the other can't reach
   the 1.33 resistance ratio in this window with these leakages (~6 mm per half would be
   needed); a thinner outer wire overshoots by ~10%. **`BV191@2`**: the field method, mumetall
   kept for Hyperm 702 (no datasheet; BV 191's printed ~12,000 matches SEKELS / VAC's
   1x1-stacked EI 48 of Mumetall, so it is read as the stacked core's, the joint gap from that
   table; a 50% NiFe of 12,000 with any joint gap would miss the 25 H). Against Blatt 4: the
   halves in series 23.4 H (25 +- 10%), shorted 133 ohm at 1 kHz (<= 140), 432 ohm at 15 kHz
   (~500: -14%; the Trolitul masks' thicknesses are provisional, and at 15 kHz the 38-layer
   primary's proximity loss adds ~25% to its resistance, which isn't modelled: Dowell's
   factor). `crates/varimu-components/tests/targets.rs` holds both to these figures and every
   design to its saved version.
6. **Built 2026-11-04 (open: the user listens):** The 5E3 pinned to its OT version, both builders (agreement test), heard against version 1.
   *Status:* **The capacitance connection** (decision (b)): the compiler (0.2.0) turns every
   facing pair into capacitors between terminals (`capacitance::network`): each facing
   side's potential runs linearly between its ends, as shares of its winding's voltage from
   the dotted end (a winding starts at its dot, sections in order, each section's first
   layer from z0 and back and forth; a disc's side face from its first turn to its last), so
   the energy C (U0^2 + U0 U1 + U1^2) / 6 is a quadratic form in the terminal voltages, held
   exactly by a capacitor between every pair of terminals; those across one winding add to
   its own capacitance, the rest (never negative) are the compiled `capacitors`
   (`between: [pb.other, s.dot]`, `shield.S` for a shield). Where a winding's own
   capacitance plus its negative across share is below zero (a single-layer winding facing
   another; BV 191's foil-shielded discs) no positive network holds the energy (Kron
   reduction keeps capacitors positive): it is clamped to 0 with a warning (negative
   capacitors in the IR would be exact: an option, not taken). Both builders place the
   component's capacitors between the part's nodes (`shields: {S: node}` for a shield; one
   with both ends on one node, like the centre tap's, left out), no arithmetic of their own.
   **The pin:** `OT_5E3@2` and `BV191@3` (the same designs, compiled with their networks);
   `config/circuits/fender_5e3.yaml`'s T1 is `component: OT_5E3@2` with its three windings'
   nodes (version 1's `ot_*` values removed: git history before 2026-11-04);
   `fender_5e3_drawn` redrawn by its script with the same pin, the Core symbol's new
   `component` field (both importers, the exporter, the KiCad library and generated
   projects regenerated). App fixtures changed only for the 5E3 and its drawing; both
   builders agree; the 670's goldens unchanged. `tests/test_transformer_component.py` adds
   the network's placement, shields, and the 5E3's pin. The 5E3's live aliasing test now
   reads -29.8 dB at draft-1x (was -28.1) and -34.5 at draft-2x: its margin is 4 dB (was 5).
   **Heard against version 1** (production, the whole guitar take, the app's render; audio
   git-ignored in `reports/transformers/ot_5e3_ab/audio/`, numbers in its `summary.json`):
   loudness within 0.1 LU; LUFS-matched, 63 Hz-4 kHz within 0.1 dB, 8 kHz -0.5 / -0.3 dB,
   16 kHz -2.0 / -0.7 dB (volume 0.5 / full); the difference -40.5 / -32.3 dB re the
   signal. The designed transformer is a little darker at the top (its asymmetric leakage
   and the capacitances) and otherwise the same. Production rendered at 11x real time
   against version 1's 7.6x, but with the test suites running beside it: not a measurement.
7. **Built 2026-11-04 (open: the user makes the second OT version in the view and hears
   it):** The Components view in varimu-app; a second OT version made there and heard.
   *Status:* the window's **Components** tab (`varimu-app --component OT_5E3[@N]`):
   `crates/varimu-app/src/components.rs` (the logic, tested headless) and
   `components_view.rs` (the painting, the studio look). Left, the construction: core
   (lamination, material, stack, stacking factor, butt / interleaved, joint gap, a butt
   spacer), bobbin, arrangement, leakage method, and the winding plan's sections as cards
   (winding, turns, layers, wire, enamel, interlayer paper; insulation; shields), each
   movable, splittable (to interleave), duplicable, removable; Ctrl+Z / Ctrl+Shift+Z.
   Middle, the window to scale (each layer coloured by its winding, the paper and shields;
   a layer's turns on hover), the compiled figures beside the opened version's (per winding
   turns, ratio, DCR, Lm, leakage, C; every pair's short-circuit leakage; the capacitors;
   flux at the rating; fill; warnings), the response. Bottom, listening.
   - *Editing* (`varimu_components::edit`): the design stays the YAML tree it was read as
     (`edit::design_of_version`: a version's name, kind, source and construction), so an
     unedited design compiles to its version byte for byte (`targets.rs`
     `versions_recompile_from_their_construction`: every version this compiler saved). An
     edited value's source becomes `design choice: set in the Components view (DATE)`
     (marked • in the form), never data. Drags of one value are one undo step.
   - *Compiling* on a worker thread, the newest design only; a field design is shown by
     the formula first (instant), then by the field (its winding pairs now solved in
     parallel threads, the same numbers: ~10 s for the OT instead of ~25).
   - *The response* (`varimu_components::response`): the macro's small-signal network
     solved per frequency (each winding's resistance and leakage, the coupled leakage matrix,
     the core node's linear-limit and gap conductance and eddy capacitance, the compiled
     capacitors between terminals), the core in its linear limit. Source and load stated
     in the view: the rating's windings driven (balanced when two: half the EMF at each end,
     the junction grounded, a push-pull pair's plates), the load across the remaining winding
     with the fewest turns (8 ohm when it steps down 10x or more, else 100 kOhm), the source
     the load reflected (a matched source, as OT responses are commonly measured); every
     choice editable. The opened version's curve under the design's, -3 dB points,
     insertion loss at 1 kHz, |Zin|. Checked: the T equivalent by hand (1e-7), and against
     circuitsim's transient on the IR both builders make from BV191@3 and OT_5E3@2 (30 Hz-40
     kHz, within 4e-5: the trapezoid's warping; `tests/response_check.rs`).
   - *Hearing it:* the circuit files that pin the component (`components::uses`,
     hand-written first; for OT_5E3 `fender_5e3` and `fender_5e3_drawn`) play with the
     design in its place: its compiled form served as the next version number by the
     library without a file (`Library::add_unsaved`: never in place of a saved version, in
     that library only), the circuit's parameter retargeted in memory. It plays as the Play
     view's drawing device (draft-1x, the edits heard as they compile; a value updates the
     stream, a structural change restarts it), with the look-ahead Play's device for that
     circuit keeps (the 5E3's 0.25 s; `DrawingDevice::ahead_s`). The 5E3 with `OT_5E3@2` at
     draft-1x: 0.80x real time on the guitar take at volume 0.6, 193 of 5844 blocks over
     (draft-2x 1.55x, every block over: the same as before C2, open item 2 below closed).
   - *A / B* (keys A / B): the circuit as pinned against the design, loudness-matched per
     the hard rules: both rendered at draft-1x over up to 8 s of the loop region with the
     panel as set, integrated loudness (BS.1770-4, `monitor::integrated_lufs`), the design's
     side trimmed by the difference; while a match holds Play's running compensation is off
     (it would undo the trim; `PlayView::set_ab_trim`). An edit needs a new match.
   - *Saving* writes the next version and its lock line through `store::save` (nothing when
     the design equals a saved version: the bench says "Saved as NAME@N"). *Moving a
     circuit* (an explicit button and a confirmation) rewrites the one `values` line that
     pins it (`components::move_pin`; the rest of the file untouched); a drawn circuit is
     refused (its drawing and script pin it: the Editor's Core symbol), as is one naming
     the component inline. Its IR changes as meant: rerun `export_app_fixtures.py`.
   - *Tested* (`crates/varimu-app/tests/components.rs`, on a scratch copy of config/): the
     store lists its transformers and who pins them; an unedited version is itself; undo,
     drags, a broken design; **the done-when's path**: OT_5E3@2 opened, a second winding
     plan made (the secondary moved between the primary halves: pa | s | pb), compiled by
     the field (the inner half's leakage to the secondary 40.35 -> 18.05 mH, the outer's
     19.34 -> 19.53: the halves alike, 2.1x apart before), both played in the 5E3 at
     draft-1x (they differ by -45.7 dB re the signal on a plucked chord; loudness within
     0.02 dB), saved as OT_5E3@3, and the 5E3 moved to it (one line changed). The repo's
     store has no @3: the second version is the user's to make in the view.
   - *Decided here (the user delegating):* `config/designs/*.yaml` must equal *a* saved
     version, not the latest (`targets.rs`): versions made in the view keep their
     construction in the version itself.
   - *Not built:* the speaker's page (C3's component in this view: P12R is a Python fit,
     no Rust compiler yet); adding or removing windings (the circuit names them);
     moving a drawn circuit's pin from here.
8. T85 version 2 for the V76.

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
