# Device builder: audio devices from schematics, parts with physics, an editor to play

Drafted 2026-10-25 with the user; **a draft for the user's approval**. It replaces
the main plan's Phases 6-8 as the next work (decided 2026-10-25, the user's call;
the plan's Phase 5, "Closed"). Work milestones in order, each ending with its
"done when" met and covered by tests, like the main plan and
[CIRCUIT_SIM_PLAN.md](CIRCUIT_SIM_PLAN.md).

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

**B3. KiCad as the schematic editor.** A KiCad symbol library for the macro parts
whose fields carry value, source, genome bounds and tolerance class; an importer
from KiCad's exported netlist (`kicad-cli`) to the circuit format; a check that
reports unconnected pins, floating nodes, loops of voltage sources or inductors,
rectifier nodes without capacitance, before anything renders.
*Done when:* B2's circuit drawn in KiCad imports to a file that builds the same IR
as the hand-written one, and the checks catch a deliberately broken drawing.

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
  and no expression language; derived values in library code.
- **Editor scope (B4).** Default: grow the existing web page; Tauri only if a
  native window is wanted (FUTURE_DIRECTIONS.md, Decisions 3).
- **Whether B8 comes earlier.** Default: after B4 measures it.
