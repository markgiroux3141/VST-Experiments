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
