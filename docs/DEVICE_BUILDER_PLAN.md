# Device builder: audio devices from schematics, parts with physics, an editor to play

Drafted 2026-10-25 with the user, who started B1 the same day (B1 done
2026-10-25, B2 done 2026-10-26, B3 done 2026-10-26; B4a, a schematic editor in our
web app, planned 2026-10-26 after the user turned KiCad down as the editor). It replaces
the main plan's Phases 6-8 as the next work (decided 2026-10-25, the user's call;
the plan's Phase 5, "Closed"). Work milestones in order, each ending with its
"done when" met and covered by tests, like the main plan and
[CIRCUIT_SIM_PLAN.md](CIRCUIT_SIM_PLAN.md). Which devices come after the 670 and the
EQP-1A: [DEVICE_CANDIDATES.md](DEVICE_CANDIDATES.md) (2026-10-28; the user's picks:
guitar amps and the Telefunken V76 first).

## Why

Phase 5 showed two things:

- units within factory tolerance are interchangeable by ear, while plausible
  units spread across the genome give the listener consistent preferences
  (a transitive ranking, repeats answered the same);
- feeding the listener random variations is a slow way to use an ear.

The user's goal (memory: "analog magic, not a clone") is to design devices from
parts and hear what their physics does. An editor where a part is changed and
heard gives every listen a hypothesis, which makes preference far more useful
than a list of random units. The preference stack (matching, A/B, ABX,
tone / character) stays and applies to anything built here; Phases 6-8 are
parked, not dropped.

## What exists

- **A generic circuit IR** (`varimu/circuit/ir.py`, `crates/circuitsim/src/ir.rs`):
  Resistor, Capacitor, Inductor, Coupling, VoltageSource, SineSource, Winding,
  Device (Triode, Pentode, JunctionDiode, VacuumDiode, MagneticCore). Both
  engines run any IR; circuitsim is the default, ngspice the cross-check.
- **Device files** (`config/devices/*.yaml`, fitted by `varimu fit-devices` from
  digitized datasheets) and core materials (`config/magnetics.yaml`, fitted by
  `scripts/fit_core_material.py`).
- **The 670, hand-coded**: `config/circuits/fairchild_670.yaml` (controls, values
  with sources and genome links, part tolerance classes) turned into IR by
  `varimu/circuit/netlist.py` (~900 lines of Python: pots, tapped pots, T-pads,
  the Time Constant switch, transformers, tube instances with per-part draws,
  the power supply, channel 2 lumped).
- **670-specific layers on top**: the setup procedures (`varimu.sim.setup`:
  B+ ADJ / BALANCE / ZERO, the factory threshold), the measurement suite
  (`varimu.measure.suite`: compression curves, timing, thump), the plausibility
  checks (`varimu.measure.plausibility`), the tweak-and-listen page (`/` of
  `varimu listen`), A/B matching by gain reduction.
- **Lessons that carry over**: every rectifier node needs a capacitance (Phase
  3); floating windings need a leak (T104); 80% of the 670's bounded genome
  doesn't work (the diversity survey: mostly oscillation), so an editor must
  screen what it builds.

## Ground rules (unchanged)

CLAUDE.md's hard rules hold: every value has a `source`; the genome is physical
only; one coupled simulation; every device model has two implementations with an
agreement test (the hysteretic core's exception stands); everything seeded and
reproducible. New physics that would change renders comes to the user as sourced
options with numbers before it's applied (memory: "options before model
changes"). Listening experiments that show subtle differences are reported, not
chased (memory: "subtle differences count as verified").

## Milestones

**B1. A generic circuit format, the 670 as its first file.** A circuit file
describes parts and their nodes; a parts library of macro parts expands them into
IR elements: resistor, capacitor, inductor, pot (wiper position), tapped pot,
T-pad (attenuation), rotary switch (positions switch parts in), transformer
(windings on a core: material, geometry, gap, leakage, capacitances), tube
(device file, per-instance draw), rectifier, sources. Per part: designator,
value(s) with `source`, optional genome link, tolerance class. Controls,
operating conditions (mains), overrides (`--set`), genome links, tolerance draws
and seeds work as today, from the file. netlist.py's helpers (`_pot`,
`_tapped_pot`, `_t_pad`, `transformer`, `tube_instance`, `apply_tolerances`,
`part_factor`, `unit_draws`) become library code; what is genuinely 670-specific
(channel 2's lumped load, the 5651's burning voltage, the selenium cell's area
scaling) becomes either a macro part or a documented derived value.
*Done when:* the 670 built from its new file gives the identical IR JSON for every
fixture case (`export_circuit_fixtures.py`: default, every Time Constant, pots at
min / max, mismatch, exact) and byte-identical SPICE goldens; `--set`, genome
links, tolerance draws, `setup.adjust` and the corner sweep behave as before; the
full test suite passes; a second, deliberately small circuit (an RC and a triode
stage) builds from the same format, to show nothing is 670-shaped.

*Status: done 2026-10-25.* The format (plan default: YAML, macro parts, no
expression language) is read by `varimu/circuit/spec.py` (parameters, sources,
overrides, genome links, the tolerance block) and built by
`varimu/circuit/builder.py` (macro registry, devices, tolerance draws, IR and
SPICE) with the parts library `varimu/circuit/parts.py` (the old helpers, now
circuit-agnostic); the docstrings of spec.py and builder.py are the format's
reference. A file has `controls`, `values` and `device_params` (the former
`TUBE_PARAMS`, now with sources and genome links), `derived`, `mains`,
`tolerance` (bands, classes, combined parts, and which parameters are the seed,
spread and tube draws), `devices` (model instances in IR model order: device
file, per-instance draw, parallel count, junction area) and `sections` (parts
as `NAME: {<macro>: <nodes>, params}`). A param is a parameter key,
`{value, source}` inline, or a bare number where it is structural (ratios,
phases, positions, counts); a bare number for a physical value is a load error.
Macro parts: R (with `parallel`), C, L, K, V, sine, mains, device, pot,
tapped_pot, t_pad, switch, transformer, bridge, vr_tube; `builder.register()`
adds circuit-specific ones. How the 670's specifics landed: the 5651's burning
voltage is the generic `vr_tube` macro (its reference current inline, sourced,
tested equal to `library.V5651_REF_A`); the selenium cells' area scaling is the
device entry's `area` (SPICE's area factor) plus the `bridge` macro's
capacitance per area; the mains scaling is the `mains` macro with the file's
`mains` block (rated 117 V inline, sourced [MAN] p.4); channel 2's lumped
values are four derived values in `varimu/circuit/fairchild_670.py` (documented
and sourced in the file), with `R ... parallel: 2` for the plain halves. The
670 file is 609 lines (from 289 of parameters only); netlist.py went from 904
lines to a 240-line wrapper that keeps the API (build, resolve, load_spec,
genome_links, TRANSFORMERS, BANK_TRIODES, tube_instance, part_designator, ...;
TITLE, INPUT_NODE, SAVE and TUBE_PARAMS read from the file). The IR's title
still says "generated by varimu.circuit.netlist", which byte identity
requires.
Measured: `export_circuit_fixtures.py --golden` leaves `git diff` on every
fixture empty (SPICE goldens, IR JSON, device fixtures); a wider snapshot (the
12 fixture cases plus spread 1 / seed 7, spread 0.6 / seed 8 at TC 5, 100 V
50 Hz mains, mid-travel pots, AC THRESHOLD at its tap, a genome change set with
interwinding capacitances, cell area and tolerance bands) gave 90 / 90
identical outputs (IR JSON with both core models, SPICE text, table files,
resolved parameters), and the corner sweep's genome space, its generated
corners and the resolved defaults hash the same under the old and new code. A
build takes 67 ms (was 105 ms; the parsed file is cached per modification
time, a cold parse is 79 ms). The second circuit, `config/circuits/triode_stage.yaml`
(an RC input network into a 12AX7 common-cathode stage, with tolerance classes),
is `test_circuitsim_nonlinear.py`'s triode_stage fixture element for element
and agrees between circuitsim and ngspice within that fixture's bound
(`tests/test_circuit_format.py`, which also covers the format's errors). Full
suite: 343 passed; cargo test, clippy and fmt clean.

**B2. A second real circuit, and per-circuit measurement.** The circuit-sim
plan's M7: a published tube device built only from the format, preferably with
existing devices (new triode types are routine: a datasheet digitized and fitted
by `varimu fit-devices`). Default candidate: a Pultec-style passive tube EQ
(published schematic: LC network, 12AX7 / 12AU7 make-up stage, input and output
transformers); the user picks (Open decisions). The 670-specific layers become
per-circuit profiles: which measurements apply (an EQ: frequency response per
setting against the published curves as anchors, THD vs level; a compressor:
today's suite), which setup procedure, which plausibility checks (generic ones
first: simulates, idle quiet, no oscillation, rails, bias; device-specific ones
in the profile).
*Done when:* the EQ runs on both engines with agreement tests and without engine
changes beyond device models; its measurement report and plausibility screen run
from its profile; the 670's reports are unchanged.

*Decided 2026-10-26 (the user): the Pultec EQP-1A.* Sources found the same day:
the Pulse Techniques manual (web: https://archive.org/details/Pultec_EQP-1A_owners_manual,
8 pages): brochure specs (boost / cut frequencies and ranges, 0.15% at +10 dBm,
noise -92 dB re +10 dBm, amplifier 20 Hz-20 kHz +0 / -1 dB), the published
response curves for every switch position (the measurement anchors), the
potentiometers (A-B types, values and tapers), and drawing DWG E-72,658-2 (the
amplifier, power supply and transformers with printed values and voltages; the
passive network is a box on it). The passive network's values come from a
redraw (web: https://www.recproaudio.com/diy_pro_audio/diy_files/eqp_1a/eqp1a_filter_schematic.jpg,
"Hoef 7-11-97"): its inductor / capacitor pairs resonate at the panel's
frequencies (33 mH with 8.2 nF: 9.7 kHz on 10 k), and a vendor's figures for the
original 5-tap coil (web: https://vintagewindings.com/products/VintageWindings%20EQ-1A.html:
32.0, 51.1, 84.3, 100.2, 150.5 mH, 14-34 ohm) bound the inductances as genome
parameters. New devices: the 12AU7 (Koren's table, like the 12AX7) and the 6X4
(GE ET-T865A, plate curve). Steps, each checked before the next:

1. Sources archived (`data/schematics/pultec_eqp1a/`, provenance), the 12AU7 and
   6X4 device files.
2. Format additions the EQP-1A needs: potentiometer tapers (audio taper, sourced),
   controls with discrete choices (switch positions named by frequency).
3. `config/circuits/pultec_eqp1a.yaml`: input transformer, passive network,
   interstage transformer, 12AX7 / 12AU7 push-pull with feedback, output
   transformer, power supply; it builds, idles at the drawing's voltages.
4. Both engines agree on it (linear cores), as M7 asks.
5. Per-circuit profiles: the EQ's measurements (response per setting against the
   published curves, THD vs level) and plausibility screen; the 670's reports
   unchanged.

*Status 2026-10-26: steps 1-4 done.* (1) Sources, 12AU7, 6X4 (its fit gives the
sheet's 22 V drop at 70 mA: 22.03 V). (2) `rheostat` macro, potentiometer tapers
(`taper_mid`: audio taper through (0.5, mid)), controls with `choices`;
`parts.turns_for_inductance`; the 670's IR stays identical. (3)
`config/circuits/pultec_eqp1a.yaml`: 116 elements, 5 tube models, 3 transformers
(HS-56 and HS-29 from Triad's sheets: ratios, winding resistances, inductances; the
S-217-D's turns from a rebuild, unverified). The passive network's topology is
Pulse Techniques' EQP-1R drawing and Barrera's EQP-1A netlist (they agree); its
values the redraw's, read with one capacitor always in per LF bank (then within
~15% of the EQP-1R's). One derived supply value (`scripts/calibrate_pultec_psu.py`:
PCC-55 292.5 V rms per HV half) puts the rails at 353 / 344 / 325 / 288 / 256 / 61 V
against the drawing's 355 / 345 / 325 / 290 / 250 / 60 V; the 12AU7 cathodes idle at
36.6 V (40 printed), the 12AX7's at 1.13 V (1.3). Small-signal (circuitsim
multitone): overall gain +0.4 dB at 1 kHz (drawing: 0 dB); LF boost +13.1 dB at
20 Hz (brochure 13.5), LF atten -17.1 dB (17.5), HF atten 20k -16.0 dB at 20 kHz
(16), HF boost peaks on every selected frequency at +20.5 dB sharp (brochure 18:
only the coils' 14-33 ohm limit the Q; core loss isn't modeled), +11.3 dB broad;
the flat response droops to -1.9 dB at 20 kHz (the amplifier's spec is +0 / -1 dB:
the provisional HS-29 capacitance is the likely cause; for step 5). Runs at ~2.5x
slower than real time. (4) Both engines on the linear-core build, ngspice as a
reference with tabulated triodes: -63 / -67 dB of the swing at the output (k = 4 /
8), the network and transformer nodes -69 / -80 dB (second order); ngspice's exact
triode formulation stalled at reference tolerances (over 700 s of CPU for 10 ms).
Tests: `tests/test_pultec.py`.

*Status 2026-10-26: step 5 done, so B2 is done.* Per-circuit profiles
(`varimu/measure/profiles.py`): the 670's is today's suite (`varimu.measure.suite`,
setup procedures, plausibility), untouched; render jobs name a circuit file
(`RenderJob.circuit`), and a job without one builds the 670 through
`netlist.build` as before (a test pins its cache keys). The EQP-1A's profile is
`varimu.measure.eq_suite` (`varimu unit --circuit pultec_eqp1a --name NAME`, ~60 s
cold): the generic screen (`varimu.measure.generic`: idle quiet, supply rails within
10% of the drawing after 6 s of idle, no spurs on a tone, overall gain within 6 dB),
the response at every published family's extreme against the manual's curves
(`data/datasheets/pultec_eqp1a_curves.csv`: 68 points of 24 panels read by eye at
400 dpi, +-1.5 dB, with provenance), the brochure's ranges at the selected
frequencies, THD vs level. Nominal unit (reports/units/pultec_nominal/): passes;
rails within 2.1%; ranges LF boost 13.4 / LF atten 17.6 / HF atten 16.7 / HF boost
sharp 20.6 dB against 13.5 / 17.5 / 16 / 18; 65 of 68 curve points within 2 dB
(the worst: the sharp HF peaks, ~2 dB high, and the 5 kc attenuate's knee, 2.3 dB);
THD at +10 dBm 0.0055% with matched tubes, 0.073-0.074% for two units with drawn
part and tube tolerances (seeds 3, 11), against the brochure's 0.15%; at +21 dBm
0.026% / 0.26%. The heaters' +60 V tap is reported, not checked: a divider of two
10% resistors, it read +12.9% on a working unit. Open, for the user (new physics
comes as options): the sharp HF boost's Q (the coil's core loss isn't modeled; only
its 14-33 ohm) and the flat response's -1.9 dB at 20 kHz (the provisional HS-29
capacitance; the brochure's amplifier is +0 / -1 dB). Noise waits for B5.

**B3. KiCad as the schematic editor.** A KiCad symbol library for the macro parts
whose fields carry value, source, genome bounds and tolerance class; an importer
from KiCad's exported netlist (`kicad-cli`) to the circuit format; a check that
reports unconnected pins, floating nodes, loops of voltage sources or inductors,
rectifier nodes without capacitance, before anything renders.
*Done when:* B2's circuit drawn in KiCad imports to a file that builds the same IR
as the hand-written one, and the checks catch a deliberately broken drawing.

*Status 2026-10-26: done (closed by the user's decision, see below).*

**Closed 2026-10-26 (the user).** The user tried KiCad and doesn't want it as the
editor ("it looks like a tool created in the 90s"; memory: "build own tools over
legacy ones"): schematics are drawn in our own web app instead (B4a). B3 closes on what
was measured: the generated EQP-1A imports to the hand-written IR at all 84 switch
combinations, and the broken drawing's four faults are caught. "The EQP-1A drawn by
hand" moves to B4a's done-when, drawn in the new editor. The KiCad route stays as an
import / export path for other people's designs, not extended.

**Decided with the user.** KiCad 10.0.7 is installed per user (the official
installer, its signature checked against kicad.org's certificate serial), at
`%LOCALAPPDATA%\Programs\KiCad\10.0`. The EQP-1A is generated, label-connected, as the
importer's fixture.

**What was built.**
- **The library**: `kicad/varimu.kicad_sym`, 32 symbols from one table
  (`varimu/kicad/symbols.py`).
- **The importer** (`varimu/kicad/importer.py`, reading kicad-cli's XML netlist:
  `netlist.py`).
- **The exporter** (`export.py`): circuit file to a label-connected project; the
  fixtures' source and a starting point for drawings.
- **The pre-flight checks**: `varimu/preflight.py`, kept outside `varimu/circuit`, so
  the render cache stayed warm.
- **Commands**: `kicad-import`, `kicad-export`, `kicad-library`, `check`.
- **The how-to**: `kicad/README.md`.

**Decisions** (the user's request: propose, then take the recommendation):
- **Fields.** Reference is the part's name. Value is the main value: an engineering
  number, read exactly through `decimal`, so `40u` is `40.0e-6` and an int stays an
  int, or a key. Source, Param (makes a number a `values` entry), Genome (the
  genome_bounds path only: bounds stay in one file), Tol (class, `none`, `tube`).
  Lowercase fields are the macro's other params, verbatim YAML.
- **The sidecar.** `<project>.params.yaml` holds what isn't a part.
- **Sections** are hierarchical sheets.
- **Rotary switches** are real switch decks (`SW_Rotary_N`, a `Control` field;
  ganged decks share it). The importer resolves every combination of positions: the
  common joins the selected contact; what an open contact leaves hanging by one node
  (chains of two-terminal parts) drops out; parts that come and go become `switch`
  sub-parts with `in:`.
- **Transformers** are one pinless `Core` symbol plus `Winding` symbols that name it
  and can sit on any sheet (T3's feedback winding).
- **Tubes** are per-type symbols with pins named by role; dual symbols' units are
  instances `X<ref><unit>`, and `Model` shares one model (the 6X4's halves).
- **The rectifier check** applies to diode nodes an inductance feeds. Literally
  ("every rectifier node needs a capacitance") it rejects the working EQP-1A, whose
  6X4 cathode node has only its 470 ohm on it. CLAUDE.md's failure was an inductance
  kicking into an empty node.
- **Element order**: an order-insensitive IR comparison (`varimu/kicad/compare.py`:
  per section, every element by name equal, every model equal) is the importer's
  promise. Reproducing the hand-written order would need an order field on every
  part. What order changes, measured on circuitsim (0.3 s of 1 kHz + 7.3 kHz at 2 V
  peak after the 1 s settle):
  - the same IR twice: bit-identical;
  - imported vs hand-written order: -139.5 dB rms re signal on the EQP-1A (boosts
    and attenuation in; max 0.9 uV) and -128.9 dB on the 670 (threshold 0.8, TC1;
    max 4 uV). That is the Newton tolerance's level, far below the engines'
    agreement with each other.
  - An imported file has its own render cache keys.

**Measured.**
- **EQP-1A**: the generated project (5 sheets, 66 parts, 11 windings, 5 switch decks: SHB's capacitors and coil taps on two)
  imports to the hand-written file's IR with both core models, at the pots' ends and
  with drawn tolerances (spread 1, seed 7), and with linear cores at all 84 switch
  combinations. Its values come back with their sources and genome links. Export
  takes 0.16 s, import 0.07 s, the checks over the 84 combinations ~2 s.
- **The 670 and the triode stage** round-trip through kicad-cli too (every Time
  Constant position, a drawn unit). The 670 brings the macros the EQP-1A lacks:
  T-pad, tapped pot, bridge, VR tube, interwinding capacitance, pentodes, lumped
  `combined` parts, derived values.
- **The broken drawing** (`kicad/generated/pultec_eqp1a_broken/`) has four faults, one
  per check, and all four are caught:
  - CPCCA left out: the 6X4 plate node rka is fed by the PCC-55's leakage with no
    capacitor;
  - RBIAS_B's ground pin open: an unconnected pin, at the netlist and in the IR;
  - RG2A left out: V2A's grid floats;
  - an inductor across LPCCA: an inductor loop.

  The import writes nothing (exit 2).
- **KiCad's own ERC** on the generated project gives 2 warnings: the input label
  has one pin by design, and GND has no PWR_FLAG.
- **Tests**: `tests/test_kicad.py`, 15 tests (4 need kicad-cli; the drawing's skips until
  it exists), 15 s.

**The 670's T104 bridge (decided 2026-10-26, the user: option 2).** The checks found
one thing in the hand-written 670: its bridge nodes `ay` / `bk`. T104's secondary
leakage feeds them, R136 is across them, and there was no capacitor, which is where
CLAUDE.md records ngspice stopping (circuitsim ran it). The fix is a self-capacitance
across T104's 600 ohm secondary:
- `t104_c_sec_f`, 100 pF, provisional (a 600 ohm line winding, as the EQP-1A's HS-56);
- a genome parameter `transformers.sidechain_output.secondary_capacitance_f`,
  bounded 30-300 pF.

Measured on circuitsim, at the default panel, before and after:

| | Output difference (rms, re signal) | Peak difference | Gain reduction |
|---|---|---|---|
| 7 s TC1 burst | -106 dB | -91 dB | median -5.759 dB both, max difference 0.0001 dB |
| 4 s arpeggio | -80 dB | -72 dB | median -11.407 dB both, max difference 0.003 dB |

The control voltage moved by at most 2.8 mV / 18 mV of 69 / 51 V. Each fixture's IR
gained one element (`CT104_s ay bk 1e-10`). Every hand-written circuit now passes the
checks.

**B4a. A schematic editor in our web app.** Drawing and editing circuits in
`varimu listen` (page `/editor`) instead of KiCad, with no external tool. It's
B4's first part: its step 2 is most of B4's loop.
*Done when:*
- the EQP-1A, the 670 and the triode stage open as drawings and compile back to
  their hand-written IR (`varimu.kicad.compare`: every switch combination, both core
  models, drawn tolerances);
- a circuit drawn from scratch in the editor (the triode stage) is saved as a new
  circuit, compiles, passes the checks and renders;
- the EQP-1A drawn by hand in the editor (moved from B3) compiles to the
  hand-written IR at all 84 switch combinations;
- the broken EQP-1A shows its four faults on the canvas;
- the time from a value tweak to hearing it is measured on the EQP-1A and the 670
  (B4, B8);
- the user has seen and accepted the look at each step (screenshots).

*Decided 2026-10-26 (the user).*
- **Look:** a dark studio console. Near-black canvas, gray wires, amber selection,
  cyan net highlight (`docs/editor_mockups/`: the three directions shown, `?theme=studio`
  the one chosen).
- **Sections:** one canvas with sections as titled frames, not pages. Wires may cross
  frames. A part belongs to the frame its origin is in.
- **Hand-written circuits stay the reference.** The 670, the EQP-1A and the triode
  stage are never rewritten by the editor. A value tweak is an override (as `--set`)
  until saved, and anything saved is a new circuit, e.g. `pultec_eqp1a_mine`, whose
  drawing is its source.

*Architecture (the plan's default; reconsider only with a reason).*
- **The drawing is the source.** A circuit made in the editor is
  `config/circuits/<name>.drawing.json`. It holds:
  - the sidecar's content: title, input, probes, controls, values no part carries,
    device parameters, derived values, mains, the tolerance block;
  - frames (the sections, in order);
  - symbols, one entry per Reference: symbol, Value, fields, a placement per unit
    (x, y, rotation, mirror);
  - wires (polylines), net labels and ground symbols.

  Coordinates are mm, y down, on a 1.27 mm grid: `varimu/kicad/symbols.py`'s pin
  geometry as it is. Saving also writes the compiled `<name>.yaml`, whose header says
  it's generated and not to be edited; renders read that, unchanged.
- **Compiling reuses the importer.** Connectivity is computed in Python
  (`varimu/editor/`):
  - a pin joins a wire at any point of it;
  - a wire's end on another wire's segment is a T junction;
  - crossing wires don't join;
  - labels with the same name are one net (one canvas, so every label is global);
  - ground is node 0.

  The connectivity becomes a `varimu.kicad.netlist.Netlist` (frames as sheets) and goes
  through `import_netlist` into a circuit file. The importer already resolves switch
  decks, Core + Winding transformers, dual tubes, Param / Source / Genome values and
  tolerance classes, and blocks a number without a source. The pre-flight checks
  (`varimu.preflight`) and the importer's problems are mapped back onto the drawing: a
  node to its wires and pins, a part to its symbol.
- **Hand-written circuits get a generated drawing.** It is built from the exporter's
  parts (`varimu.kicad.export`: symbols, fields, pin nets) in a label-connected
  layout. It is generated on open and never saved over the hand-written file.
- **One symbol table.** The page draws `symbols.py`'s symbols from JSON the server
  makes from the table: SVG path data, pins with roles, field names.
- **No dependencies.** The page is plain ES modules served by FastAPI: no npm, no
  build step. SVG canvas, pan and zoom by a transform. A library only with the user's
  OK, if the interaction work clearly needs one.
- **The render cache stays warm.** Nothing goes in `varimu/{sim,circuit,devices}`:
  - the editor lives in `varimu/editor/` and `varimu/listen/`;
  - rendering an unsaved edit needs `RenderJob.circuit` to take a path. That one-line
    change in `varimu/sim/runner.py` invalidates every cached render once, so it
    comes in step 2 on its own.

*Steps, each checked (tests, screenshots to the user) before the next.*
1. **A read-only view.** `/editor`: pick a circuit, see its drawing, pan and zoom,
   hover a net to highlight it everywhere (its labels too), click a part to see its
   fields (value, source, genome link and bounds, tolerance class). The document
   format, connectivity, the compiler and the generated drawings, with the round-trip
   tests of the first done-when.
2. **Editing parts in place.** Change a value with its source (an empty source blocks
   compiling, as in the importer; a shared Param edits every part on it, or unlinks
   one), swap a part type from the library (tube type, core material). Renders on a
   short loop run in the background on every change, and the previous render is one
   key away, loudness-matched (the listen page's machinery). "Save as" writes a new
   circuit. The tweak-to-hear time is measured.
3. **Drawing topology.** Place, move, rotate and mirror parts; grid-snapped wires;
   labels and ground; delete; undo / redo; copy / paste; rotary switch decks and
   windings as in `kicad/README.md`. The pre-flight checks run live after each edit,
   with the problems drawn on the canvas (a floating node's wires, an unconnected
   pin, a loop's parts). The triode stage drawn from scratch; the broken EQP-1A's
   faults shown.
4. **Polish.** Keyboard shortcuts, smooth wire dragging (rubber-banding wires when
   parts move), box selection, a command palette for parts. The feel is the point of
   this milestone, so this step gets real time.

*Status 2026-10-26: step 1 done.*
- **Code.**
  - `varimu/editor/`:
    - `symbols.py`: the table as JSON (SVG path data, y down; pins with their direction
      into the body) and the placement transform;
    - `drawing.py`: the document;
    - `connect.py`: connectivity and the `Netlist`;
    - `compile.py`: the importer, the checks, problems mapped onto the drawing;
    - `layout.py`: generated drawings.
  - The page: `varimu/listen/editor.html` with `editor/{main,view,camera,inspector,eng}.js`.
  - The API: `varimu/listen/editor_api.py`.
- **Problems carry their targets.** `varimu.preflight.Problem` now names the nodes and
  IR elements each problem is about. These fields are outside equality, and messages
  are unchanged. A loop names every element on it.
- **Generated drawings.** Parts are in signal-flow order, a breadth-first walk from the
  input. Two-terminal parts stack into wired vertical chains with ground at the
  bottom; everything else gets stubs and labels. Every node keeps its name on a
  label.
- **Compiling back to the IR.** The generated drawings compile to the hand-written IR
  (`varimu.kicad.compare`):
  - the EQP-1A at all 84 switch combinations, with both core models, at the pots'
    ends, and with drawn tolerances; its values, devices and tolerance classes come
    back equal;
  - the 670 at every Time Constant position, and with drawn tolerances;
  - the triode stage.
- **Timing.**
  - Layout plus compile: EQP-1A 0.02 + 0.06 s, 670 0.14 + 0.08 s.
  - The checks at every switch combination: EQP-1A 2.7 s, 670 1.2 s. The page fetches
    them after the drawing.
- **The page.**
  - Pan and zoom: wheel at the cursor, a pinch, drag on the empty canvas, space + drag,
    the middle button. F fits the drawing, Z zooms to the selection.
  - Hovering highlights the whole net, its labels on other frames too, with a chip
    listing its pins. Clicking a part or wire shows its fields or net in the
    inspector.
  - Find (`/`) jumps to a part or node.
  - The problems are listed and drawn on the canvas: wires in red, parts ringed.
    Clicking one zooms to it.
  - A link can name a section or part: `#c=pultec_eqp1a&s=<section>&sel=<part>`.
  - Text hides when zoomed out, and frame titles are screen-sized overlays.
- **On the canvas:** the 670's ay / bk finding rang its four bridge diodes (fixed
  since: see B3). The
  broken EQP-1A, as a generated drawing, shows all four faults on the right parts and
  nets:
  - floating g2a;
  - the loop LBAD / LPCCA;
  - the rectifier at rka on V3;
  - RBIAS_B's open pin.
- **Tests:** `tests/test_editor.py`, 17 tests, ~9 s.
- **Screenshots:** `docs/editor_mockups/step1_*.png`.

*Status 2026-10-26: step 2 done.*
- **Editing values.** The inspector edits a part's value and source.
  - A shared Param changes on every part on it. "Only this part" unlinks one; the genome
    link stays with the parameter.
  - An edit's default source is `edit <date>: by ear; was <old> (<old source>)`. An
    empty source shows in red and doesn't compile.
  - Values outside their genome bounds are flagged, not blocked.
- **Swaps and controls.**
  - Tubes and diodes swap among the device files of their kind; core materials among
    `config/magnetics.yaml`'s.
  - Numeric parameters (core geometry, turns, leakage) edit inline.
  - The front panel's controls are sliders and position chips in the sidebar.
- **History and saving.** Every edit is undoable (Ctrl+Z / Ctrl+Shift+Z). Save as
  (Ctrl+S) writes `<name>.drawing.json` and the compiled `<name>.yaml`. It refuses a
  hand-written circuit's name and a drawing that doesn't compile. The edit rules are
  in `varimu/listen/editor/edits.js`, tested in Node's own test runner
  (`tests/editor_js/`, run from pytest, skipped without Node; no npm).
- **Renders and A/B.**
  - Each edit, 0.45 s after the last, renders the drawing on a loop (default 4 s of a
    chosen clip). The first edit renders the unedited drawing too.
  - B is the drawing as it is, A the render before the last edit. Dry, A and B are
    loudness-matched and switched at the same position, looped.
  - Renders go through the listen app's queue: `RenderJob.circuit` now takes a .yaml
    path. That was the planned one-line `runner.py` change, and it invalidated the
    render cache once.
  - A drawing needs a node named `out` to be heard (the runner's output); the page says
    so.
- **Tweak to hear**, measured in Chrome from the edit to B's audio being ready, cold
  (nothing cached), 4 s of the arpeggio, circuitsim, one render at a time:

  | Circuit | Edit | Edit to heard | Render | Speed |
  |---|---|---|---|---|
  | EQP-1A | CC2A 250n → 330n | 19.9 s | 15.1 s | 3.8x slower than real time |
  | 670 | C103 50n → 100n | 118 s | 114.7 s | 28.7x slower than real time |

  Rendering the unedited drawing runs in parallel. A cached render is heard in 2.3 s.
  The 670's two minutes is B8's question (the user's call with these numbers). The
  options are the plan's: shorter loops (the 1 s settle is a fixed cost), the
  circuit-sim plan's speed work, or fewer oversampled stages. Rendering the loop in
  parallel chunks isn't one of them: the 670's release outlasts any warm-up, so the
  chunks would join audibly.
- **Tests:** `tests/test_editor.py`, 21 tests, including a real render and compare
  through the API and Save as.
- **Screenshot:** `docs/editor_mockups/step2_edit_ab.png`.

*Status 2026-10-26: step 3 done* (the hand drawing of the EQP-1A is the user's).
- **Tools.**
  - Select (V): click, shift-click, box-drag; drag to move (wires rubber-band); drag
    from a pin to draw a wire; R rotates, X mirrors, arrows nudge, Delete; Ctrl+C / X /
    V / D / A.
  - Wire (W): L-shaped corners, `/` flips; ends on a pin or wire, Enter, a double click
    or Esc.
  - Label (L) names a net, with completion; Ground (G); labels and grounds point away
    from the wire they sit on.
  - Section (S): drag a frame and name it. A frame title drags the section with its
    contents; a corner handle resizes it; a double click renames it.
  - Parts are placed from a palette drawn from the symbol table (R / X turn the ghost).
    Rotary decks ask for their number of positions.
  - Pan moved to the right or middle button, or space + drag. A space tap still plays.
    Render-now is Ctrl+Enter, so R can rotate.
- **Topology edits** are `varimu/listen/editor/geom.js`:
  - place, move and turn, with rubber-banding that keeps wires orthogonal;
  - box select, delete;
  - copy and paste, renumbering references, a pasted winding following its pasted core;
  - routes, tidy (merging straight runs), renames.

  They are tested in Node on the real symbol table (`tests/editor_js/geom.test.mjs`,
  7 tests).
- **The inspector also edits:**
  - the reference (windings follow a renamed core);
  - a winding's core and label, and a deck's control;
  - every raw field (YAML), and adding fields;
  - with nothing selected, the circuit: title, input, probes, and controls (a range is
    a knob, a list is a switch's positions).

  The circuit picker has "New circuit"; a `.drawing.json` dropped on the canvas opens.
- **Live checks.** The drawing recompiles after every edit (~50 ms on small drawings)
  and the checks follow 0.6 s later. Open pins are marked while drawing and listed per
  part.
- **A drawing probes `out`.** Renders save only the probes and read `out`, so a
  drawing with an `out` node probes it whatever its probes say.
- **The A/B stimuli stay valid.** `varimu.listen.prepare.code_version` now hashes only
  the 670's circuit file among `config/circuits/`. A circuit saved from the editor no
  longer marks the 670's prepared A/B stimuli stale. This session's `runner.py` change
  had already invalidated them, so the narrowing cost nothing.
- **The triode stage drawn from scratch** through the UI (`scripts/editor_draw_triode.py`
  drives Chrome with Playwright from uv's cache):
  - it places, rotates and renames 10 parts, draws 9 wires (two ending on others as T
    junctions), adds 7 labels and 5 grounds, and enters every value with its source;
  - it takes 13.3 s of scripted UI;
  - saved as `config/circuits/triode_stage_drawn`, it compiles and passes every check;
  - it builds the hand-written stage's IR with both core models. The only differences
    are what the drawing names differently: `out` for `o`, section `main`, its title.
  - It is heard 3 s after Ctrl+Enter (a 2 s burst).
- **The broken EQP-1A shows its four faults on the canvas**
  (`docs/editor_mockups/step3_broken_*.png`):
  - g2a's wire and label in red;
  - LPCCA / LBAD ringed;
  - V3 ringed;
  - RBIAS_B's open pin ringed.
- **Checked in Chrome:** moving RL (its wire bent, its ground and label followed, the
  checks still pass), box select + Delete (2 problems), undo, duplicate.
- **Tests:** `tests/test_editor.py`, 24 tests.

*Status 2026-10-26: step 4 (polish), a first pass.*
- **Value stepping.** ↑ / ↓ in a value field step to the next standard value (E12;
  Shift: E24) and apply at once. The field keeps the focus, so a value can be walked
  and listened to (220n, 270n, 330n, …). An edit of an edit keeps what the first one
  replaced.
- **Wire segments.** Dragging a wire moves the segment under the pointer sideways. The
  wire's ends stay on their pins (jogs are added), and labels, grounds and T junctions
  on the segment go with it. A wire in a multi-selection moves with the selection.
- **Command palette** (Ctrl+K): place any part (rotary decks by size), pick a tool, go
  to a section, find a part or node, render, save, undo, start a new circuit; typed
  words filter.
- **Shortcut sheet** (? or the header's ?).
- **Hover.** The hovered pin is ringed in select mode ("drag to wire").
- **Speed.** A full redraw of the 670 (154 parts, 313 wires) takes 10 ms in Chrome, so
  dragging previews redraw whole on each grid step.
- **Checked in Chrome:**
  - RL stepped 470k → 560k → 680k, keeping its first provenance;
  - the B+ segment dragged up with its `bp` label (the checks pass);
  - `scripts/editor_draw_triode.py` still draws the identical file.
- **Tests:** Node, 7 edit and 9 geometry tests.
- **Screenshots:** `docs/editor_mockups/step4_*.png`.

*B4a's done-when: met (2026-10-27).*
- The hand-written circuits open and compile back to their IR; the triode stage drawn
  from scratch; the broken EQP-1A's faults on the canvas; tweak-to-hear measured.
- **The EQP-1A and the 670 drawn as schematics** after their original drawings
  (`data/schematics/`): `pultec_eqp1a_drawn` and `fairchild_670_drawn`, signal left to
  right, real wires, labels only for rails and the feeds that cross the sheet (the 670:
  out, cv, T104's feedback fy / fg). They are planned by hand in scripts
  (`scripts/draw_pultec_eqp1a.py`, `draw_fairchild_670.py`) on a small drawing kit,
  `varimu/editor/sketch.py` (place, wire pin to pin, label, ground, frame; it checks a
  drawing against its circuit pin by pin), rather than with the mouse, as the handoff
  the user passed on proposed. Both build the hand-written
  IR: the EQP-1A at all 84 switch combinations (`test_eqp1a_drawn_by_hand`), the 670 at
  every Time Constant position with both core models; both with drawn tolerances
  (`tests/test_editor_drawings.py`, which also checks the scripts still draw the saved
  files). The 670's drawing went in with commit 7bc4246 (T104's capacitance).
- **The look, accepted by the user** (2026-10-27): `docs/editor_mockups/drawn_*.png`.
  The page's text rules grew for drawn schematics (`view.js`, `unitTexts`): a winding's
  name away from its turns, a core's above it with its lines the length of its
  windings, decks labelled above (upright) or beside their contacts (on their side),
  parts on their side labelled clear of their pins, flipped parts' names above their
  values, no open-pin marks on a deck's spare contacts.
- The 6386 banks (four tubes a side) share grid, plate and cathode buses; three plate
  leads a side cross the grid bus without joining (no side-by-side layout avoids it).

**B4. The editor loop.** The tweak-and-listen page generalized to any circuit:
its parameters come from the circuit file (with sources and bounds; front-panel
controls separate from parts), renders run on short loops in the background as
values change, the previous render stays one key away for A/B (loudness matched;
gain-reduction matched where the profile is a compressor), and every build is
screened (plausibility) with the reason shown ("oscillates at 31 kHz"). Swapping a
part type (a core material, a tube type, a capacitor dielectric once B6 exists)
works from the parts library.
*Done when:* the user can open the 670 or B2's circuit, change a part, and hear
and compare the result, with warnings for units that don't work; how long a
tweak takes to hear is measured and reported (see B8).

**B5. Noise sources.** Johnson noise of resistors (4kTR), tube shot noise
(2qI, with the space-charge reduction) and flicker (1/f, a corner per tube type,
sourced), each in the Python reference, circuitsim and SPICE (ngspice's
transient noise sources), seeded per part. A noise floor for hum and crosstalk to
sit in (Future Directions 3).
*Done when:* measured spectra of each source on a test circuit match theory within
a stated tolerance in both engines; renders reproduce from the seed; the 670's
idle noise is measured and, if a published figure exists, compared (`vs_670`
style, never a rejection).

*Design decided 2026-10-30 (the user, for the tube synth; TUBE_SYNTH_PLAN.md S4):*
- **Expectation (estimates, to measure):** in tube_synth B5 gives a hiss ~-95..-100 dB re
  the note (the mixer's 1M || 1M at the first grid), gated with the VCA; pitch jitter and
  wander from it are far below a cent (the pitch driver's grid at ~256 cents/V sees ~0.4 uV
  of flicker below 20 Hz; the LC tank's phase noise ~-140 dBc/Hz at 1 Hz). Audible: the
  filter near self-oscillation, oscillator start-up, S5's noise source. The audible drift is
  B6 and the mains (vco_lc: 43 cents per volt of mains), so **slow mains-voltage wander joins
  B5** as an opt-in noise source on the mains (provisional spectrum, the user's call).
- **IR** (optional, absent when off: existing IRs, fixtures, goldens and renders unchanged,
  IR_VERSION stays): `noise: {seed, temperature_k}`; `NoiseCurrent` (white Norton current,
  4kT/R, per physical resistor: not `numerical:` leaks, core-node resistors or MIN_R_OHM
  contacts); `TubeNoise` per tube instance (shot as plate current 4 k T0 beta gm, beta 2.5
  at T0 290 K, i.e. R_eq = 2.5 / gm; pentodes (Ib / Ik)(2.5 / gm)(1 + 8 Ic2 / gm), as
  Spangenberg, *Vacuum Tubes* (1948) gives it; grid-current shot 2q|Ig|; flicker as a
  voltage in series with the grid, K_f / f). No noise on diodes, selenium, the 5651s.
- **Flicker from physics (provisional):** space-charge-limited, a relative emission
  fluctuation moves the potential minimum by (kTc/q) dJ/J, a grid-referred voltage
  independent of the operating point: K_f = (kTc/q)^2 A, A ~3e-12 (oxide cathodes' emission
  flicker, order of magnitude) -> K_f ~2.5e-14 V^2, a corner ~1 kHz for a 12AX7 at
  1.6 mA/V (the user's pick), bounded 100 Hz-10 kHz; one default for oxide cathodes; flat
  below 1e-3 Hz.
- **Generation:** counter-based Philox4x64-10 (numpy's `np.random.Philox`), key (seed,
  crc32(name) << 32 | stream): sample k is a pure function of (key, k), so chunks,
  partitions and a re-render at another quality see the same samples. Python's numpy
  Philox + Box-Muller is the reference; Rust's uniforms equal it bit for bit, and every
  engine uses circuitsim's generator (ngspice's streams through the binding). Flicker: 15
  first-order sections, 2 per decade, stationary at sample 0. On the project's 96 kHz grid,
  sample 0 the first output sample, linear between samples (sinc^4: -0.3 dB at 10 kHz, -1.3 dB at 20 kHz, in the
  theory the tests use); held at sample 0 for the DC point and the settle, as the input is.
  Shot amplitude from gm at the last accepted step.
- **Engines:** circuitsim: `NoiseCurrent` a time-varying source column, `TubeNoise` at the
  device's ports. SPICE: filesource-driven G sources, a grid-lead V source, a B source on
  sqrt(gm) (gm from a duplicate instance at +1 mV). Opt-in: a circuit file's `noise:`
  block (tube_synth only), `--noise` overrides; the seed is in the IR (the cache key).

*Status 2026-10-30: built (commits f5ef8f4..; the done-when's spectra and engine agreement
met).*
- **Streams** (`varimu/devices/noise.py`, circuitsim `noise.rs`): Philox words equal numpy's
  bit for bit, normals and the flicker filter to 1e-14 / 1e-9 (`tests/noise.rs`); the 1/f
  filter within 0.05 dB of 1/f over 0.01 Hz-10 kHz, stationary from sample 0. The grid's
  linear interpolation shapes every density by **sinc^4**(f / fs) (a triangle pulse per
  sample; first written as sinc^2, found by the spectra): -0.3 dB at 10 kHz, -1.3 at 20.
- **The IR and builders:** `noise: {seed, rate_hz, mains_rms?, mains_sources?}`,
  `NoiseCurrent`, `TubeNoise`; a circuit file's `noise:` block (seed; temperature_k,
  flicker_v2, mains_rms default to noise.py's), `build(..., noise=)` (None: the file's;
  False; True; a seed). Both builders bit for bit (`agreement.rs`: a noise case per circuit,
  a seed past 2^63). Without the block nothing moves: fixtures, goldens and every other
  circuit's IR unchanged.
- **circuitsim** (DK only): current columns after the sine sources and externals, each
  stream a window of grid samples (production: two engine samples per grid sample;
  draft-1x: two grid samples per engine sample, aliasing the noise's top octave, stated not
  fixed); tubes' amplitudes from the last accepted step; flicker as gm e_f; streams carry
  over `Transient::update`. `tests/noise_run.rs`: kT/C on every capacitor (1.005 / 0.984),
  the same noise at 1x and 2x (2.3e-4), seeds reproduce, blocks bit for bit, partitions
  within their coupling (0.8%).
- **SPICE:** G sources on filesource streams (Python's generator), tubes' gm from two copies
  on E sources (they load nothing), B sources; `varimu.sim.io.run_transient(..., noise=)`,
  renders on ngspice pass them. ngspice's operating point takes sample 0 (circuitsim's is
  noise-free): microvolts, gone within the settle.
- **The done-when** (`tests/test_noise_spectra.py`, `varimu/measure/noise_theory.py`): a
  resistor across a capacitor, a 12AX7 and a 6V6GT on stiff sources (tube noise only:
  shot, flicker, a pentode's partition noise), every octave 16 Hz-16 kHz within 0.5 dB of
  the closed forms in circuitsim (4 s; measured within 0.47), 64 Hz-16 kHz in ngspice (1 s;
  within 0.45). The engines on the same streams: -61 dB below 20 kHz on that triode
  (ngspice as a reference: at its production settings its interpolation leaves -31 dB),
  -51 dB on triode_stage.yaml (a 0.1-0.2% level offset in ngspice; circuitsim's 2x and 8x
  agree to -53 dB); resistors alone -100 dB (slow RC) / -76 dB (16 kHz corner).
- **Mains wander:** the mains' amplitude times 1 + m(t), one stream for every `mains` part;
  unit flicker through a one-pole at 2 Hz, nominal 0.5% rms (MAINS_SOURCE: provisional; no
  published spectrum of the band between flicker and EN 50160's 10-minute means was found).
  circuitsim equals Python's m to 5e-15; the engines agree to -182 dB.
- **The 670's idle noise** (`scripts/noise_670.py` -> `reports/noise/670_idle.json`; noise
  forced on, defaults, production, 20 Hz-20 kHz across its 600 ohm load): **-115 dBm**,
  49 dB under the published ~70 dB below +4 dBm (-66 dBm; dealers' and the reissue's spec
  sheets, bandwidth unstated, not checked against an original document): vs_670 style, not
  a rejection. The noiseless model is silent at idle (-247 dBm: no hum reaches the output),
  so the published figure is mostly what isn't modelled yet: heater hum, carbon
  resistors' excess noise (B6), aged tubes.
- **Cost in real time:** tube_synth at draft with the app's partition, 0.84-0.89x real time
  without noise, +0.15 with the resistors' (73 white streams; ~16 ns per normal, the
  Box-Muller transform), +0.15 with the tubes' (amplitudes now from DK's own last
  evaluation, no extra device evaluations: that saved little), free for the mains wander;
  all of it ~1.08-1.16x. In the app: ~88% load, worst block 133% (no dropouts in 10 s at
  a 50 ms buffer), against 60% / 91% without, back to back.

**B6. Component physics.** The part non-idealities of FUTURE_DIRECTIONS.md
section 1, each a sourced, bounded parameter of its part class, tested on its
own and measured for audibility on the 670 before it becomes a default:
capacitor ESR, leakage, dielectric absorption (series-RC branches) and voltage
coefficient by dielectric (paper, mica, electrolytic, film, ceramic); resistor
voltage coefficient (carbon composition) and excess noise; pot wiper resistance;
tube heater voltage to cathode temperature to emission (Richardson-Dushman behind
the space-charge limit). Measured effects come to the user as options before
they change defaults.
*Done when:* each element has its reference and engine implementations with
agreement tests, a sourced default, bounds, and a measured audibility note.

*Decided 2026-10-30 (the user, after B5):* the heater first, then pot end / wiper
resistance (the end-stop spike), capacitor leakage and dielectric absorption, carbon
resistors (excess noise, voltage coefficient), each with options first.
- **The heater (the user's picks):** a cathode-temperature state per tube, heated by its
  heater (rated volts x the circuit's mains setting x B5's mains wander) through a thermal
  lag (~10 s, anchored to RCA's printed 11 s warm-up of series-string types and a patent's
  ~5.5 s to 10% current for a 1.5 W oxide cathode); acting through **both** the space-charge
  shift (the potential minimum deepens as the cathode heats: an effective grid shift,
  ~+1.7 mV/K, ~7 mV per 1% of heater voltage; zero at the rated temperature, so the fitted
  curves hold there) **and** a Richardson emission ceiling (tubes come alive from cold,
  starve at low mains, rectifiers ramp B+). **Runs start warm**; a cold start (power on) is
  an option (an app button, a render flag). Opt-in per circuit, so nothing existing moves;
  Python reference, circuitsim and SPICE.
- **The data:** Phywe LEP 4.1.10 (the EC92): Fig. 4's forward curves at heater currents
  100-120 mA (rated 150) flatten at ~3.3 / 7.3 / 12.3 / ~21 mA (100 / 105 / 110 / 115 mA,
  by eye); Fig. 5's retarding region moves ~0.35 V at a fixed 10 uA between 130 and 150 mA.
  Under the sheet's current control a tungsten heater (R ~ T^1.2) gives T ~ I^0.71 (radiation
  balance); with the rated cathode at 1050 K (provisional: oxide cathodes run ~1000-1100 K)
  Fig. 4's ceilings fit a work function of ~1.17 eV, inside oxide cathodes' 1.0-1.3 eV, and
  the same model moves Fig. 5's 10 uA point by ~0.22 V (measured ~0.35: the order holds).

*Status 2026-10-30: the heater built (commits 2f292ed..01cc0c1).*
- **The physics** (`varimu/devices/cathode.py`, `config/cathodes.yaml`, `scripts/fit_cathode.py`
  -> `reports/devices/cathode_ec92.{json,png}`): Fig. 4 (every point read by eye into
  published_points.yaml `EC92_forward_by_heater`) fits with phi **1.22 eV**, a soft ceiling (n
  1.29), the EC92's emission at T0 0.54 A (54x its ~10 mA), rms 0.28 mA; Fig. 5's retarding
  shift comes out ~2/3 of the measured; tau **7 s** (the model's 10% current from cold at
  5.5 s for 1.5 W). Each tube type's emission goes with its heater power (0.57 A/W).
- **The space-charge shift at a fixed reference** (the tube at 1 / reserve of its emission,
  reserve 50): one function of T for every tube, +1.7 mV/K (-67 mV at 40 K cool). From the
  tube's own current it was a signal-dependent ~mV term the engines disagreed on (-41 dB):
  dropped. The ceiling relative to T0's: a tube at the rated heater is its fitted model
  exactly.
- **The IR, builders, engines:** a `heaters` block (the oxide constants, the heater ratio =
  the mains setting over the rated mains, warm / cold) and `HeatedCathode` per triode,
  pentode and vacuum diode; a circuit file's `heaters: {start?}`, `build(..., heaters=)`;
  both builders bit for bit. circuitsim: `cathode.rs`'s `Heated` wraps a tube (equal to
  Python's `heated` to 1e-12, Jacobian checked), `HeatRun` steps the one temperature per
  sample with B5's mains wander, refreshing the tubes past 1e-4 K; a cold start skips the
  settle. SPICE: a capacitance-free copy of the tube on E sources, its control pin shifted,
  B sources driving the pins; the temperature a stream. The triode stage, ngspice against
  circuitsim: -82.6 dB at the rated and at a 90% heater (as unheated), a cold start to the
  millivolt; from cold it is silent ~3 s, alive by ~6 s, and creeps to its operating point
  over tens of seconds (`tests/test_cathode.py`).
- Not modelled: directly heated filaments (the 5Y3GT) are treated as oxide cathodes; the
  heaters don't load the power transformer; the app's live stream settles its first second
  (a power-on's warm-up starts within it).

*Pot end stop, decided and built 2026-10-30 (the user: the engine restart; no end
resistance for now, nothing audible to gain at realistic values).* `Transient::update` now
sets a restart: the next sample takes backward Euler over its first h / 256
(`RESTART_LEVEL` 8, the deepest halving; halving further on failure), then the method over
the other 255/256 in one step (its own step system, `rest_slot`; doubling substeps if it
fails), without extrapolating across the change; both solvers (DK and the full MNA), every
method with an explicit first stage (the coupled ones take no derivative in). Measured: the
tube filter's RESONANCE to 1 (and 0.5 -> 1 at once) peaks as within the range; an update to
the identical circuit costs what it did before (draft, 10 kHz: the 670 -79.7 dB, the EQP-1A
-79.2 dB peak re the signal; production -122 dB; at h / 64 it was -68), the next block
~1-4 ms more on the 670; the 670's pots thrown to their ends in one update now run (Newton
failed in both solvers before) and the solvers agree within 0.21 tolerance. Renders never
update, so none moves. Tests: `crates/circuitsim/tests/update.rs` (a pot's end next to a
series capacitor, at once vs a decade per sample, within 1.6 uV; the 670's pots thrown).
The measurement that led there:

*Pot end stop, measured 2026-10-30.* Reproduced on
`tube_filter` at draft: RESONANCE 0.99 -> 1 throws the output to +-72 V (a thump decaying
over ~30 ms), 0.5 -> 1 to 180 V; CUTOFF, LEVEL and the 5E3's volume reach their ends cleanly.
**The cause is the engine, not the pot:** `Transient::update` carries every node voltage and
takes `C x'` from the new circuit at the old point. RQ's end segment (1 kOhm -> 1 mOhm) lies
between the wiper and a node on a series capacitor (CR5), so `G x` there is ~100 A, a
derivative outside C's range that the first (explicit) stage injects as charge. It scales
with the jump's ratio (1k -> 10 Ohm 0.8 V, -> 1 Ohm 7.5 V), and approached a decade per
update the same 1 mOhm end is clean. Renders never update mid-run, so only live play sees it.
- *Engine restart (prototyped, reverted):* the step after an update starts with backward
  Euler (implicit, L-stable; SPICE drops to first order at a breakpoint the same way), so the
  change settles as a switch does: fast modes within the step, charges held (LEVEL to 0 joins
  1 uF to 100 uF ~1 V apart: the 100 uF side moves 0.01 V, as charge sharing says). Every case
  above clean, renders unchanged. Its cost on an update to the identical circuit (vs none):
  BE over the whole sample -20 dB peak at 10 kHz (draft; a tick); BE over h/64 and the rest
  of the sample in doubling substeps -41 dB (the draft's own local error, re-discretized);
  to build: BE over h/64 then one method step over the other 63/64 (two cached step systems
  per update; expected ~-85 dB). Today's code: -79 dB. A zero-time BE step of h/1024 was tried
  first and fails: a 1 ns mode settles only to 1/11, and its derivative blows up as before.
- *Pot end resistance:* sources: Bourns PDB18 (carbon) residual resistance 1% max; Taiwan
  Alpha RV16 (16E spec sheet) 10 / 20 / 50 Ohm max for tracks <= 20k / <= 100k / <= 1M; the
  EQP-1A's pots are Allen-Bradley type J (MIL-R-94: the scanned spec has no text layer, not
  read). Spike with the end at 20 Ohm: none at 0.99 -> 1, 11 V on 0.5 -> 1; 50 Ohm 4 V; 1%
  none. Renders (production, noise at -20 dBFS, the panel's defaults / knobs at their ends),
  difference re output and the octave levels 31 Hz-16 kHz: Alpha's table: 670 -88.5 / -70.9
  dB, <= 0.003 dB; EQP-1A -41.5 / -44.1 dB, <= 0.08 dB; 5E3 -74.3 / -57.8 dB, <= 0.014 dB.
  1%: 670 -42.7 / -55.4 dB, +0.06 dB; EQP-1A -25.5 / -19.8 dB, -0.96..+0.28 dB; 5E3 -30.0 /
  -13.8 dB, up to +1.8 dB (volume and tone at 10). Low-value pots (the 670's 100 Ohm BALANCE)
  are likely wirewound: an end resistance per element type.
- *Wiper contact resistance* (20 Ohm in series with the wiper): the spike unchanged (the end
  segment is still 1 mOhm).

**B7. Aging.** FUTURE_DIRECTIONS.md section 2: a unit history (years since build,
powered hours, storage temperature and humidity, service events: recapped,
retubed) mapped to per-part drift by sourced laws with Arrhenius acceleration
and seeded per-part draws, applied after the tolerance draw; aged units re-trimmed
by the circuit's setup procedure as a technician would. In the editor, history is
a control like any other.
*Done when:* an aged 670 builds and simulates, its report shows each part's drift
and why, aged-and-retrimmed and aged-untrimmed both run, and everything
reproduces from (history, seed).

**B8. Speed for interactive editing (measure first).** If B4 shows tweaks take
too long to hear, the options are the circuit-sim plan's deferred M5 speed
target and M8 (real-time readiness), shorter loops, or fewer oversampled stages;
the user decides with the numbers.
*Done when:* decided by B4's measurement.

**New device types** (BJT, JFET, MOSFET, op-amp macro model, zener, LDR / opto
cell, thermistor, lamp) arrive when a chosen circuit needs them, each with its
three-way test pattern.

**B9. The Fender 5E3 Deluxe** ([DEVICE_CANDIDATES.md](DEVICE_CANDIDATES.md), the
user's first pick; planned 2026-10-29). A guitar amp built from the format like the
EQP-1A, its output transformer the component editor's first designed component
([COMPONENT_EDITOR_PLAN.md](COMPONENT_EDITOR_PLAN.md), C2). Steps, each checked before
the next:
1. *Sources* in `data/schematics/fender_5e3/` (README with provenance, like the
   EQP-1A's): the schematic with printed values and voltages, the layout, the power and
   output transformers (original part numbers; reproductions' published impedance,
   resistance and inductance figures), the speaker (original Jensen; Thiele-Small data
   of the original or its reissue), published measured DC voltages (Rob Robinette's
   pages) and tube datasheets. *Done 2026-10-29:* `data/schematics/fender_5e3/README.md`
   (Fender's F-EE schematic and layout; no DC voltages or mains on them, so the DC
   targets are kits' published measurements at unstated mains; no original transformer
   data, the output transformer's version 1 from Amplified Parts' P-TGO-002 figures;
   Jensen P12R reissue Thiele-Small data).
2. *Device fits* as component versions (C1): 12AY7 (Koren triode), 6V6GT (Koren
   pentode, as the 6973), 5Y3GT (vacuum diode, as the GZ34 and 6X4), each from a
   digitized datasheet with a provenance sidecar.
   *Fitted 2026-10-29* (`12AY7@1`, `6V6GT@1`, `5Y3GT@1`; builders in
   `varimu/devices/library.py`, plots in `reports/devices/`; the user reviews the plots
   before step 3). Curves digitized from RCA's and Tung-Sol's 12AY7 sheets, GE's
   ET-T914 (6V6-GT) and ET-T965 (5Y3-GT) (`data/datasheets/*.provenance.yaml`). The
   12AY7 fits RCA's curves (250 V, -4 V: 3.06 mA, gm 1646 umho, mu 42.4, rp 25.8 k against
   RCA's 3 mA, 1750, 40, 22.8 k and Tung-Sol's mu 44, 25 k; Tung-Sol's curves within
   0.13 mA rms). The 5Y3GT is Child's law within 3% rms and gives the printed 50 V drop at
   125 mA. The 6V6GT fits the plate and transfer curves to 1.6 mA rms above Va 60 V and
   the class-A and push-pull idle points within 1%, but Koren's form can't draw its knee
   (5.3 mA rms below 60 V), puts rp at the class-A point at 112 k against the printed
   ~50 k (pinning rp to 50 k only reaches 81 k and costs the knee 50%), and fits the
   screen curves to ~57% rms (the 6084's ~40%). *Decided 2026-10-29 (the user, on
   Claude's recommendation):* the 5E3 is built on Koren `6V6GT@1`; after step 5 a
   beam-tetrode model (a sharper knee, the plate slope, screen current that rises as the
   plate swings into the knee: the screen supply's sag) becomes `6V6GT@2`, sourced from a
   published model, heard against `@1` in the 5E3 and dropped if the difference is subtle.
   Why later: through the 8 k : 8 ohm transformer, rp 112 k against ~50-70 k moves the
   speaker's resonance peak by roughly 1-2 dB, and the knee and screen law matter only at
   full drive, where the comparison can be heard.
3. *The circuit* `config/circuits/fender_5e3.yaml`: both channels with their
   interactive volumes, the tone control, the phase inverter and cathode-biased 6V6GT
   pair as the schematic draws them, the 5Y3 supply, the output transformer's version 1
   (lumped values from published figures, like the 670's transformers), the speaker's
   electrical equivalent as its load (a first version from the reissue's Thiele-Small
   parameters; C3 makes it the physical speaker) and the input as decided below.
   Pre-flight checks pass; floating windings get the T104 treatment.
   *Built 2026-10-29* (`config/circuits/fender_5e3.yaml`, `tests/test_fender_5e3.py`):
   as drawn on F-EE, which corrects the README in two places: each channel's coupling
   capacitor drives its volume pot's wiper (ends to ground and V2A's grid: the
   interacting volumes), and the tone's .0005 goes to the bright wiper. The jacks are a
   switch control `input_jack` (bright / normal, input 1 / 2: 34k or the -6 dB divider).
   Output transformer version 1: Amplified Parts P-TGO-002's DCRs, mean leakage (29.9 mH)
   and 3.67 H per half, with turns from a design rule (929 per half: 1.2 T at 15 W, 70 Hz)
   and the joint gap solved for that inductance (145 um, provisional). Power transformer:
   P-TGP-002 (350.7 V per half at 120 V, its DCRs), no calibration. The speaker load: the
   P12R reissue's Re, Le and motional RLC. A 1 GOhm leak on B+1 (no bleeder). Pre-flight
   passes at all four jacks; no floating windings (the secondary and the HV centre tap
   are grounded). Idle against Amplified Parts' kit: B+ 370.0 / 324.2 / 239.6 V (370 /
   325.5 / 240.8), 6V6 cathodes 20.2 V (21.1), inverter 200.8 / 39.9 V (195.1 / 45.9),
   V2A 163.6 / 1.14 V (157.7 / 1.22), V1 117.2 / 2.01 V (136.2 and 128.5 / 1.76): all
   within the layout's +-20% (the 12AY7 fit draws ~15% more than the kit's tubes). IR
   equal in Rust (`tests/agreement.rs`, 30 cases); ngspice (linear cores) runs it, its
   output -54.5 dB from circuitsim's on a 440 Hz tone. 1 kHz: ~1 W clean at half volume,
   15-16 W in hard overdrive.
   *The input level, done 2026-10-29* (the design the user approved): a circuit file's
   optional `full_scale: {input_volts_peak, output_volts_peak}` (each `{value, source}`;
   `spec.py`'s docstring), the 5E3's 1 V in (a hot pickup) and 60 V out (the speaker's
   peak, 53.6 V at 1 kHz, 1 V in, volume 0.5, rounded up). Without it both are
   sim_settings' 13.8 V, so the other circuits are unchanged bit for bit (their IR,
   goldens and app fixtures: no diff; `app_render_agreement.py` equal at production and
   draft-1x, now with the 5E3 and the output audio compared). It is no parameter and not
   in the IR: Python's `varimu.sim.io.full_scale` (renders, with the pair in the cache key
   and meta.json; `live.py`; `eq_suite.py`) and varimu-app's `Circuit::full_scale`
   (render, live, `load_profile`) scale around the circuit. Play's gain meter shows the
   circuit's gain in V/V (0 dB more for circuits on the global scale). The KiCad export and
   import (both parsers) carry it, so a drawing of the 5E3 keeps it.
4. *Its profile* (`varimu/measure/profiles.py`): gain per volume setting, response per
   tone setting, clipping onset, THD vs level, output power into the load, supply sag
   and recovery on bursts, and aliasing at the internal rate (production 2x, draft).
   *Done 2026-10-29* (`varimu/measure/amp_suite.py`, `varimu unit --circuit fender_5e3`,
   84 renders, ~1.5 min; `reports/units/fender_5e3_nominal/`; `tests/test_profiles.py`).
   Levels are volts at the jack and at the speaker; power is what the speaker's
   equivalent takes (from v(out) and its admittance: 6 ohm at DC, 37.6 at the 80 Hz
   resonance, 6.7 at 1 kHz, 32 at 10 kHz). The screen: B+1..3 within 0.5% of the kit,
   the speaker -90 dBFS (1.3 mV) at idle. Gain at 1 kHz, 3 mV in: bright 34.4 dB at
   volume 0.1 to 50.6 at 0.9 and 60.8 at full; normal 6 dB lower at low volume (the
   bright channel's .0005 bypasses part of its volume), equal at full. Response: the
   speaker's voltage follows its impedance (a pentode pair, no feedback: the resonance
   bump, +10 dB toward 16 kHz from Le); the tone adds up to ~+25 dB of treble on the
   bright channel and cuts the normal channel's at full rotation (through the grounded
   bright wiper). 1% THD at half volume at 28 mV peak in (1.8 W); about 13 W into the
   speaker at most (V^2 / 8 says 17-19 W); at full volume 1% at 4 mV. A full-drive burst
   sags B+1 3-4%, B+2 ~10%, B+3 ~8% (recovering 63% in 0.1 / 0.45 s: 5000 and 22K x
   16 uF), lifts the 6V6 cathodes 20-25%, and the output falls 0.5-0.6 dB over 1 s.
   Aliasing (a 2902 Hz tone at 0.5 V, full volume, hard clipped): -40 dB re the
   harmonics at production, -31 at draft, -8 at draft-1x, discrete inharmonic lines at
   -15 to -20 dB re the fundamental. The speaker voltage's harmonics barely fall
   (the impedance rises with frequency), so a clipped 5E3 folds much more than the
   670 or the EQP-1A: draft-1x is a ballpark at best for it (step 5).
5. *The drawing and play*: `scripts/draw_fender_5e3.py` on `varimu/editor/sketch.py`
   (`fender_5e3_drawn`), opened in the native editor; a Play device in `varimu-app`
   with its front panel, on files and live input (a guitar through the interface),
   load and dropouts measured (`examples/play.rs`).
   *Drawn and playable 2026-10-29:* `scripts/draw_fender_5e3.py` lays the circuit out
   after F-EE (`config/circuits/fender_5e3_drawn.*`: the jacks as three switch decks
   per channel, the 12AY7 pair around one cathode, the volumes and tone, the 12AX7 and
   cathodyne, the 6V6 pair on the output transformer and the speaker, the supply below);
   it builds the hand-written IR at every jack and with drawn tolerances, both cores
   (`tests/test_editor_drawings.py`), its full scale included. The look is the user's to
   review in the native editor (`--edit fender_5e3_drawn`). varimu-app's Play has the
   device `fender_5e3` (the input jack, both volumes, the tone). Load on the 62 s dry
   guitar take (`examples/load_profile.rs`, no audio device; volume 0.6): 0.27x real
   time at draft-1x (one block of 5844 over 1.0), 0.46x at draft (96 kHz, 5 of 11688).
   *Decided 2026-10-29 (the user):* the 5E3 plays at the draft's 96 kHz. Built as
   `draft-2x` (varimu-app only; `sim_settings.yaml` `circuitsim_draft_2x`): a 48 kHz
   host (the audio device's rate) with the stream at 2x, Live upsampling each block in
   and decimating each stream's output back (`StreamResampler`; at 1x both pass
   through, so the other devices play bit for bit as before). Each device names its
   Play quality (`panel::Device::quality`: the 670 and the EQP-1A draft-1x, the 5E3
   draft-2x). Through Live, the hard-clipped 2902 Hz leaves -7.2 dB of inharmonic
   content re the harmonics at draft-1x and -24.1 at draft-2x (`tests/live.rs`; hum
   sidebands counted too). Load on the guitar take: 0.47x real time at volume 0.6
   (worst backlog 8 ms), 0.51x at full volume, where hard clipping runs blocks at up to
   2.3x real time (worst backlog 170 ms): the 5E3 keeps 0.25 s ahead on a loop, as
   the 670 does. Live input at full volume needs an input buffer of that order. Not
   yet done: a guitar on the interface's Hi-Z input (`examples/play.rs`, with an audio
   device).
6. *The designed output transformer* (C2): version 2 by construction, heard against
   version 1 in the 5E3.
7. *The physical speaker* (C3): the 5E3 heard as sound pressure at a listening point
   in front of its speaker and open-back cabinet.
   *Built 2026-10-29* (COMPONENT_EDITOR_PLAN.md, C3's status): `out` is the pressure 1 m
   on axis in front of `P12R@1` in the 1956 cabinet's dimensions, `spk` the terminal
   voltage; full scale 50 Pa. On the guitar take the 10-20 kHz share of the power falls by
   ~24 dB against the terminal voltage. Into the component the step 4 profile moved where
   the load did: gain at half volume 46.9 / 41.4 dB (was 45.5 / 40.0: the P12R's ~8 ohm at
   1 kHz with its eddy currents against the equivalent circuit's 6.7), 1% THD at 30 mV in
   (2.3 W), at most 15.5 W; sag and aliasing as before (aliasing still measured on the
   terminal voltage). Open: the user's listening, and Play's load (1.61x real time at
   draft-2x; options in C3's status).

*Decided 2026-10-29 (the user's):* the 5E3 is heard through a physical speaker model
(C3), not a cabinet impulse response; until C3 exists, the load voltage serves for
checks only. Guitar audio (recorded DIs, a live guitar on the interface's Hi-Z input)
drives the input jack as a voltage: a Hi-Z input loads the pickup about like the
amp's 1 MOhm input, so the DI already carries the pickup's response. Its level is a
per-circuit volts-per-full-scale convention (a hot pickup peaks just under 1 V:
web: https://www.sound-au.com/articles/guitar-voltage.htm), trimmed by the Play view's
input gain. A pickup model is for later.
*Done when:* the 5E3 builds equal IR in Python and Rust (`tests/agreement.rs`) and
runs on both engines with an agreement test (ngspice on linear cores); its DC operating
point is within a stated tolerance of the printed voltages at the schematic's mains;
its profile report runs; it plays live in the native app at draft-1x (or the speed
work it needs is measured and brought to the user); the user has heard it through the
physical speaker, with both output transformer versions.

**B10. The Telefunken V76** (the user's second pick). A broadcast microphone preamp
(three EF804S and an E83F, confirmed on the drawing). *Gate cleared 2026-10-29:* IRT's
Braunbuch V 76 (1959) with drawing S 1176, every value, voltage and current printed
(`data/schematics/telefunken_v76/README.md`); its one undrawn part is the input's RF
trap. The wound parts are broadcaster build specs (BV 511-517a) without winding data. Steps as
B9's: sources in `data/schematics/telefunken_v76/`; pentode fits for the EF804S and the
E83F as component versions; the circuit with its input and output transformers as
transformer components (version 1 from replacement datasheets, designed versions with
C2's designer); a preamp profile (gain per step, response per filter, THD vs level,
clipping; equivalent input noise waits for B5's noise sources); the drawing; play on
live input.
*Done when:* as B9's, against the V76's published figures.

## Devices and components together (2026-10-29, the user's call)

B9-B10 and [COMPONENT_EDITOR_PLAN.md](COMPONENT_EDITOR_PLAN.md) run interleaved, each
device the first user of the component milestone next to it:

1. **Now, in parallel:** C1 (the component library and versions; invisible, identical
   IR); B9 step 1 (the 5E3's sources); the V76 schematic search (B10's gate); the
   user's 5E3 decisions (what we listen to, the input convention).
2. **B9 step 2** (the 5E3's tube fits; as device files they can start before C1 ends,
   C1 wraps them as version 1).
3. **B9 steps 3-5** on C1: the 5E3 with its output transformer's version 1, profiled,
   drawn, playing in the native app. *Done 2026-10-29.*
4. **C3's model with B9 step 7** (reordered 2026-10-29, the user's call: the 5E3's
   sound isn't judged until it is heard through its speaker; C3 doesn't need C2): the
   physical speaker as a component, its pressure the heard output; the speaker's view
   in the Components view waits for C2's. *Model built 2026-10-29; open: heard, and
   Play's speed (C3's status). Paused 2026-10-29 (the user's call: a synthesizer session
   may come first); C3's status lists where to pick up and the future optimizations.*
5. **`6V6GT@2`** (B9 step 2's beam-tetrode follow-up), heard against `@1` through the
   speaker.
6. **C2 with B9 step 6:** the transformer designer (and the Components view, the
   speaker's included), the 5E3's output transformer as version 2, A/B in the 5E3.
   B9 done.
7. **B10** (its schematic is found), its transformers designed with C2's tool; C4
   (the existing circuits' transformers as components) fits in here or whenever a
   670 / EQP-1A transformer is to be redesigned.
8. **C5-C7** (tube designer, ratings, physical tolerances), then C8 only on demand.

## Order and why

B1 first: noise, component physics, aging and temperature all attach where a part
is turned into elements, and that place should exist once, in the generic format,
not in netlist.py. B2 proves the format and pries the 670 out of the measurement
layers. B3 and B4 put the editor in the user's hands early, so the physics added
in B5-B7 lands where it can be heard. The brainstorm's priority (aging with noise
first) is kept within the physics milestones.

## Risks

| Risk | Mitigation |
|---|---|
| The port changes the 670's behaviour silently | B1's done-when is byte-identical IR and SPICE goldens on every fixture |
| A format too general to keep simple | Macro parts in Python for the hard cases; no expression language unless B1 shows it's needed |
| Untuned circuits don't converge or oscillate | B3's pre-flight checks; the plausibility screen on every build; DC fallbacks (source stepping) if needed |
| Editing feels slow (renders 12-24x slower than real time on the 670) | Short loops, background renders; B8 decides speed work on numbers |
| Physics data is thin (aging, component drift) | Provisional values as bounded genome parameters with sources, as the hard rules require |

## Open decisions (the user's)

- **The second circuit (B2).** Default: a Pultec-style passive tube EQ. Any device
  with a published schematic and sourced values works.
- **File format (B1).** Default: YAML, like today's circuit file, with macro parts
  and no expression language; derived values in library code. *Taken (B1,
  2026-10-25): the 670 needed no expression language, only four derived values.*
- **Editor scope (B4).** Default: grow the existing web page; Tauri only if a
  native window is wanted (FUTURE_DIRECTIONS.md, Decisions 3). *Taken (2026-10-26):
  our own schematic editor in the web app, not KiCad (B4a).*
- **Whether B8 comes earlier.** Default: after B4 measures it.
