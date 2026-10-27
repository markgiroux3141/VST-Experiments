# KiCad import and export (device builder B3)

Circuits are drawn in our own schematic editor (`varimu listen`, page `/editor`; device
builder B4a). KiCad stays as an import / export path, for other people's designs: draw a
circuit in KiCad (10.x) with the `varimu` symbol library, and
`varimu kicad-import` turns the drawing into a circuit file
(`config/circuits/*.yaml`, the format of `varimu/circuit/spec.py` and `builder.py`).
The import runs the pre-flight checks before writing anything.

| Path | What it is |
|---|---|
| `varimu.kicad_sym` | the symbol library, one symbol per macro part (written by `uv run varimu kicad-library` from `varimu/kicad/symbols.py`) |
| `generated/pultec_eqp1a/` | the EQP-1A exported from its hand-written file: label-connected, a parts list rather than a drawing. It's the importer's test fixture and a starting point for a drawing |
| `generated/pultec_eqp1a_broken/` | the same with four deliberate faults (the checks' test fixture) |

`generated/` is rewritten by `uv run python scripts/make_kicad_fixtures.py`; don't
edit it by hand.

## Commands

```sh
uv run varimu kicad-import kicad/pultec_eqp1a/pultec_eqp1a.kicad_sch --out cache/kicad/pultec_eqp1a.yaml
uv run varimu check --circuit pultec_eqp1a          # the pre-flight checks on any circuit file
uv run varimu kicad-export --circuit NAME --out DIR  # a circuit file as a label-connected project
uv run varimu kicad-library                          # rewrite varimu.kicad_sym
```

`kicad-import` runs `kicad-cli sch export netlist --format kicadxml` and reads the sidecar
`<project>.params.yaml` next to the schematic. It prints the problems it finds and, if
there are any, writes nothing (exit 2; `--no-check` writes anyway). It only overwrites
files it wrote itself (`--force` overrides that). kicad-cli is found through
`$VARIMU_KICAD_CLI`, then PATH, then the installer's folders
(`%LOCALAPPDATA%\Programs\KiCad\*\bin`, `%ProgramFiles%\KiCad\*\bin`).

## Starting a drawing

1. Make a KiCad project in `kicad/<name>/` (e.g. `kicad/pultec_eqp1a/pultec_eqp1a.kicad_pro`).
2. Add the library as a project library named `varimu`, path
   `${KIPRJMOD}/../varimu.kicad_sym` (Preferences > Manage Symbol Libraries > Project
   Specific Libraries). Symbols from other libraries are an import error, power
   symbols aside.
3. Copy the sidecar (`generated/<name>/<name>.params.yaml`) next to the schematic as
   `<name>.params.yaml`. It holds what isn't a part: title, input node, probes,
   controls, values no part carries, device parameters, derived values, mains, and
   the tolerance block. The tolerance classes come from the parts' `Tol` fields; the
   sidecar's `classes` list only designators that aren't drawn (parts that `combined`
   lumps into a drawn one).
4. Draw. Opening the generated project shows every part with its fields already
   filled in. Copying symbols from it is the quickest route.

For the import to build the same IR as a hand-written file, use the file's part
names as References and its node names as net labels.

## What goes where

**Sheets are sections.** One hierarchical sheet per section; the sheet's name is the
section's title, and the page order is the section order. Parts on the root sheet go
in a section `main`.

**Nets are nodes.** A net's label is its node name. A local label's sheet path is
dropped, so a name used on two sheets must be one net (use a global label) or it's
an error. GND is node `0`. An unlabeled net becomes `n_<ref>_<pin>`. The input
node may have one pin (the simulation drives it).

**Fields.** A part's Reference is its name in the circuit file: its element names, its
tolerance designator and the seed of its draw. Capitalized fields are metadata;
lowercase fields are the macro's other params, written as in the circuit file (a
parameter key, a bare number where the param is structural, or
`{value: 2.5e-3, source: "..."}`). Empty fields count as absent.

| Field | Meaning |
|---|---|
| Value | the main value (R `r`, C `c`, L `l`, pot `r`, T-pad `z`, sources `v` / `amplitude_v` / `v_rms`, VR tube `operating_v`): an engineering number (`470`, `40u`, `8.2n`, `4k7`; read exactly, so `40u` is `40.0e-6`) or a parameter key |
| Source | where a number comes from; required for every number |
| Param | names the number: it becomes a `values` entry you can `--set`. Parts with the same Param must agree, and one of them needs the Source |
| Genome | the value's path in `config/genome_bounds.yaml` (needs Param). Bounds stay in that file, in one place |
| Tol | the tolerance class (`r10`, `network`, ...), `none` (not a physical part), or `tube` on a tube |
| Unit, Notes | carried into the `values` entry |

**Parts by symbol.** Pin 1 is the first node of the macro.

| Symbol | Macro and pins |
|---|---|
| R, C, L | 1, 2 (L: current from the dotted pin 1); R takes `parallel` |
| Pot | 1 end_a, 2 wiper, 3 end_b; `at` (0 = wiper at pin 1), `taper_mid` |
| Rheostat | 1, 2; `at` (0 = no resistance), `taper_mid` |
| Pot_Tapped | 1 end_a, 2 tap, 3 wiper, 4 end_b; `at`, `tap` |
| T_Pad | 1 a, 2 b, 3 common; `atten_db` |
| V, Sine, Mains | 1 +, 2 -; Sine: `freq_hz`, `offset_v`, `phase_deg`; Mains: `phase_deg` (the file's `mains` block scales it) |
| Bridge | 1 ac_a, 2 ac_b, 3 +, 4 -; Value is the device file; `arm_c_f_per_area`, `area` |
| VR_Tube | 1 anode, 2 cathode; `device` (its junction-diode file), `ref_current_a`, Mid (the inner node, default `<ref>_mid`) |
| K | no pins; `inductors: [LA, LB]`, Value is k |

**Tubes and diodes** (Triode, Triode_Dual, Pentode, Diode, Diode_Dual). The Value is the
device file (`12AX7`) or a parameter naming one. Pins are named by role (p, g, k; p,
g2, g1, k; a, k). Fields: Tol `tube` (the per-instance emission and mu draws), and
`emission`, `mu`, `grid_contact_v`, `parallel`, `area`, `instance`, `name`.

Each placed unit is one device instance. Unit A of V1 becomes part `XV1A` (`DV1A` for a
junction diode, as the SPICE letters demand) with model key `V1A`. Give both units
`Model: V3` to share one model, as the 6X4's two halves do. KiCad merges a dual
symbol's fields across its units, so a pair whose instances differ is drawn as two
single symbols.

**Transformers.** A `Core` symbol (no pins) whose Reference names the transformer (`T3`),
with fields `material`, `area_m2`, `path_m`, `gap_m`, `turns`, `leakage_h` and
optionally `interwinding: {ends: [pa.dot, pb.other], to: s.dot, c: key}`.

One `Winding` symbol per winding, anywhere in the drawing, with the dot at pin 1. Its
Value is the label (`pa`), its `Transformer` field names the core, and it takes `ratio`,
`r` and `c`. Windings are taken in the order of their References; the transformer's
elements go in the core's section.

**Rotary switches.** Decks are `SW_Rotary_N`: common `C`, contacts 1..N for the control's
`choices` in order (or min..max of a `unit: position` control). Field `Control` names
the control. Decks with the same Control are one ganged switch.

Wire a part that's in at positions 3 and 4 to both contacts, as the real switch is
wired, and leave unused contacts open or flag them no-connect. The importer resolves
every combination of positions:
- The common joins the selected contact.
- Whatever an open contact leaves hanging by one node carries no current and drops
  out. That includes a chain of two-terminal parts, like a coil and its series
  resistance.
- A part that comes and goes becomes a `switch` sub-part with `in:` its positions.

It must follow one control and keep its nodes. Two parts on one open contact form a
series path, which is an error.

## The pre-flight checks (`varimu/preflight.py`)

The checks run at every combination of switch positions:
- **unconnected:** a pin without a connection, in the netlist and as a node with one
  element.
- **floating:** no DC path to ground through resistors, inductors, windings, sources
  or cores. Tube and diode pins don't count.
- **loop:** a loop of sources, inductors and resistance-less windings.
- **rectifier:** a diode's node that an inductor or winding feeds with no capacitor on
  it; CLAUDE.md's lesson from the 670's supply.
- **probe:** a probe or input that names no node.

The hand-written 670 has one such finding: its T104 bridge nodes `ay` / `bk` (see
docs/DEVICE_BUILDER_PLAN.md, B3).
