# Device builder: audio devices from schematics, parts with physics, an editor to play

Drafted 2026-10-25 with the user, who started B1 the same day (B1 done
2026-10-25, B2 done 2026-10-26; next is B3). It replaces
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
  native window is wanted (FUTURE_DIRECTIONS.md, Decisions 3).
- **Whether B8 comes earlier.** Default: after B4 measures it.
