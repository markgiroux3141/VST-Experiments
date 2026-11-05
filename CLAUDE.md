# CLAUDE.md

The project plan is [VARIMU_PROJECT_PLAN.md](VARIMU_PROJECT_PLAN.md) (the plan's
layout calls it `PLAN.md`). Read it before starting work.

**Phases 0-5 are done (Phase 4, measurement suite: 2026-10-23; noise waits
for noise sources; Phase 5, listening: closed 2026-10-25). Phase 5 built blind
A/B at `/ab` of `varimu listen` with stimuli matched by `varimu ab-prepare`
(varimu/listen/), difference listening and ABX with a tone / character split
(`difference`, `abx`), and multitrack program material
(`scripts/build_clips.py`). Its finding: units with realistic values are too
close to choose between by preference (audible only exaggerated 6-8x); by the
user's rule that answers the experiment (no more listening aids for subtle
differences). The diversity survey across the whole genome
(`scripts/diversity_survey.py`, 2026-10-25): 16 of 20 sampled units don't
work (mostly oscillation: constrain the space before Phase 7); the plausible
ones differ ~10 dB more than the first pool, and three of them with nominal are
now the session pool (`session_candidates`). A preference session on it gave
consistent, transitive preferences. Then the user parked Phases 6-8
(2026-10-25). Next is the device builder,
[docs/DEVICE_BUILDER_PLAN.md](docs/DEVICE_BUILDER_PLAN.md): B1 (a generic
circuit format with the 670 as its first file, byte-identical IR) is done
(2026-10-25); B2 (the Pultec EQP-1A, the user's choice, and per-circuit
measurement profiles) is done (2026-10-26); B3 (KiCad as the schematic editor) is done
(2026-10-26: closed by the user, who turned KiCad down as the editor; it stays an
import / export path). B4a, a schematic editor in our own web app (`/editor` of
`varimu listen`), is built (2026-10-26): steps 1-3 (view; editing values, renders and A/B,
Save as; drawing topology, with the triode stage drawn from scratch as `triode_stage_drawn`)
and a first polish pass (Ctrl+K command palette, ? keys, ↑ / ↓ step values through E12,
segment dragging). Its done-when is met (2026-10-27): the EQP-1A and the 670 drawn as
schematics after their originals (`pultec_eqp1a_drawn`, `fairchild_670_drawn`), building
the hand-written IR, the look accepted by the user (`docs/editor_mockups/drawn_*.png`).
The devices to build next are listed in [docs/DEVICE_CANDIDATES.md](docs/DEVICE_CANDIDATES.md)
(2026-10-28; the user's picks: guitar amps, the Fender 5E3 Deluxe proposed first, and the
Telefunken V76). A component editor (tubes and transformers designed from geometry and
materials, compiled to device files the circuit editors offer) is planned in
[docs/COMPONENT_EDITOR_PLAN.md](docs/COMPONENT_EDITOR_PLAN.md) (2026-10-29; milestones
C1-C8; the user's decisions: it starts alongside the 5E3, whose output transformer is the
first designed component, heard through a physical speaker (C3); component versions are
immutable and every circuit pins one; the editor is native-app only, compiled in Rust,
Python only reads; field solvers only on demand), interleaved with the device builder's B9
(the 5E3) and B10 (the V76; its schematic found 2026-10-29): the order is
DEVICE_BUILDER_PLAN.md's "Devices and components together". **C1 done (2026-10-29):
device files are component versions**, `config/components/<name>/<N>.yaml` (the former
`config/devices/*.yaml` are version 1, bytes unchanged), each version's sha256 in
`config/components/versions.lock`; `varimu/devices/versions.py` and `varimu-circuit`'s
`versions.rs` read them the same way (a version edited after saving is a load error).
Circuits pin `NAME@N` (`device: 12AX7@1`, `rectifier_tube: {value: GZ34@1, ...}`, a drawn
symbol's value): the builders refuse a bare name, which tools and tests may use for the
latest version. `varimu fit-devices` saves a new version only when a fit changed; moving a
circuit to it is an explicit edit (the native editor's model picker lists every version).
**B9 steps 2-3 done (2026-10-29):** `12AY7@1`, `6V6GT@1` (Koren; a beam-tetrode `@2` after
step 5, the user's call), `5Y3GT@1` fitted to digitized sheets (plots in `reports/devices/`);
`config/circuits/fender_5e3.yaml` idles within the layout's +-20% of a kit's published
voltages (`tests/test_fender_5e3.py`); its input is guitar level (the circuit file's
`full_scale`: 0 dBFS = 1 V peak in, 60 V at the speaker out). **B9 steps 4-5 done
(2026-10-29):** its profile `varimu/measure/amp_suite.py` (`varimu unit --circuit
fender_5e3`: gain per volume, response per tone, THD and power, sag, aliasing per
quality), its drawing `fender_5e3_drawn` (`scripts/draw_fender_5e3.py`, after F-EE) and a
Play device in varimu-app, played at `draft-2x` (the user's choice: hard clipped, draft-1x
aliases at -8 dB re the harmonics, draft -31; a 48 kHz host with the stream at 2x,
varimu-app only, `panel::Device::quality`; the plan's B9 step 5). **C2, the transformer designer (2026-11-04; COMPONENT_EDITOR_PLAN.md C2's steps):** step 1 (a winding's `leak`), step 2 (`crates/varimu-components`: designs in `config/designs/`, tables in `config/transformer/`, compiled and saved as versions from Rust) and step 3 (a transformer part's `component: NAME@N`, both builders; leakage as coupled series inductances, `leak_couplings`, the user's choice; first version `BV191@1`, test circuit `transformer_component_test`) and step 4 (the 2D FEM of the winding window, `varimu-components fem`: the 1D formula within +-5% for layer windings, +-20% for disc windings, so a design may compile its leakage by the field, `leakage_method: field`) and step 5 (`OT_5E3@1` fitted to P-TGO-002 by `scripts/fit_ot_5e3.py`: all figures but the outer half's DCR, -8%; `BV191@2` against the V72's figures) are done; step 6 built: the compiled facing capacitances as capacitors between terminals (compiler 0.2.0, by energy), the 5E3 and its drawing pinned to `OT_5E3@2` (the Core symbol's `component` field), A/B files in `reports/transformers/ot_5e3_ab/` (a little darker above 8 kHz, otherwise the same): open, the user listens; step 7 built: the Components view (`varimu-app --component OT_5E3`; `varimu_app::components`, `components_view.rs`): the construction edited (sources of edits `design choice: ...`), compiled off the UI thread (a field design previewed by the formula), the window to scale, the figures beside the opened version's, the response between a stated source and load (`varimu_components::response`, checked against circuitsim), heard in the circuits that pin it (the unsaved design served by `Library::add_unsaved` as the next version), A / B loudness-matched at draft-1x, Save as the next version, Move a hand-written circuit's pin: open, the user makes the second OT version there and hears it (the path is tested on a scratch config, `crates/varimu-app/tests/components.rs`). Step 8 (T85 version 2) studied and stopped, T85 stays at version 1 (`scripts/t85_study.py`: the 40 Hz network pins ~3 H and needs damping; a gapped, higher-resistance T85 fixes the low end but costs the top end at 1:30; the user's call: too subtle). **Next (2026-10-29, the user's call):
C3's model before C2**: the 5E3 heard as sound pressure through its physical speaker
(COMPONENT_EDITOR_PLAN.md C3; its sound isn't judged until then), then `6V6GT@2`, then C2.
**C3's model built (2026-10-29):** the speaker component `P12R@1` (kind `speaker`:
`varimu/devices/speaker.py`; fitted to the Jensen sheet's curves by `speaker_fit.py`,
`varimu fit-devices --only P12R`), the `speaker` macro in both builders (`speaker: [plus,
minus, out]`, the cabinet and the listening distance as params), its pressure readout on
the new IR element `Vccs` (SPICE `G`; it draws no current). The 5E3's `out` is the sound
pressure 1 m on axis (pascals as volts; `full_scale.output_pascals_peak` 50 Pa, both
parsers), `spk` its terminal voltage. Open: the user hears it, and Play's load (1.61x real
time at draft-2x: the 5E3 drops out in Play until the user picks an option). **Paused
2026-10-29** (the user may do the synthesizer first): COMPONENT_EDITOR_PLAN.md, C3's status,
lists where to pick up (listen, decide Play's speed, `6V6GT@2`, C2) and the future
optimizations. The user intends to retire the web app (`varimu listen`,
2026-10-29): add nothing to it; retiring it isn't planned yet. Mumetall's Rayleigh refit (the plan's Phase 2) is applied
(2026-10-24). The user-facing product is now a native Rust app,
[docs/NATIVE_APP_PLAN.md](docs/NATIVE_APP_PLAN.md) (2026-10-27: standalone only,
egui / eframe, the editor plus real-time play and production render, files and live
input; milestones R0-R4; crates `varimu-circuit`, `varimu-app`). R0 done; R1 done
(2026-10-27): `varimu-circuit` builds every circuit file's IR bit for bit equal to Python's
(`tests/agreement.rs` on `scripts/export_app_fixtures.py`'s fixtures; rerun the script after
a change to a circuit, device file, material or the builder: `tests/test_app_fixtures.py`
says when). Nominal units only (a nonzero tolerance spread is refused). R2 done
(2026-10-28; open: selectors that rewire take 0.3-0.55 s to be heard, the 670 on live
input measured on silence only): `varimu-app`'s Play view plays files and live input at
draft-1x (bypass, gain compensation, input normalization, takes), and its production
render equals Python's bit for bit (`scripts/app_render_agreement.py`); the resampler is
scipy's `resample_poly` ported bit for bit. R3 done (2026-10-28): the Editor view
(`varimu-app`'s `src/editor/`: the web editor's page logic ported and tested, the drawing
format, compile and checks `varimu-circuit`'s, R3a; `src/editor_view.rs`: the egui
canvas in the studio look), edits heard live (the drawing is a Play device: a value
updates the stream, a new topology restarts it); the triode stage drawn from scratch
through the editor's API comes out `triode_stage_drawn` byte for byte
(`tests/editor_draw.rs`). Hand-written circuits don't open as generated drawings yet
(`layout.py` isn't ported). R4 (the look and polish with the user) is paused
(2026-10-28: the artwork isn't a priority now); the plan's R4 says where it stands.** Plausibility (`varimu.measure.plausibility`) rejects only what no
working unit could do; comparisons with the 670's published figures are the
report's `vs_670` and never reject (the plan's Vision: "Aim, restated").
Since 2026-10-23 the default front panel is the
factory adjustment (the manual's threshold procedure to its curve 3,
`varimu.sim.setup.threshold`), T103 is 8.5 and the AC THRESHOLD pots are
tapped (Phase 3's sourced leftovers). Phase 2's decision (the user's): the hysteretic
core has a Python reference and a circuitsim device, no SPICE
implementation; ngspice cross-checks the rest with the cores in their linear
limit (Hard rules). Work one phase at a time. Don't start the next phase until
the current phase's "done when" criterion is met and covered by tests.

Ideas for after Phase 8 (aging, general circuits and KiCad import, stray coupling,
temperature, tape, vinyl, the plugin UI) are brainstormed and prioritized in
[docs/FUTURE_DIRECTIONS.md](docs/FUTURE_DIRECTIONS.md) (2026-10-24; the plan's
"Future Directions"). Nothing in it is built, and none of it interrupts Phases 5-8. Its
section 8 (2026-11-02, a second brainstorm, unprioritized): a live probe bench, an
audibility map of the parts (which provisional values to source first), fitting units to
real-hardware captures, coupling between devices (loading, shared mains, ground loops),
the combo amp's acoustic loop, AM broadcast and the tube radio, a theremin, circuits from
scans, manuals for invented devices.

An invented tube synth (older parts in place of solid state; drift as character; draft to
play, production to render the take) is drafted in [docs/TUBE_SYNTH_PLAN.md](docs/TUBE_SYNTH_PLAN.md)
(2026-10-29; milestones S1-S5, the saturable-reactor filter first). S1 is built except one
decision: the reactor `config/circuits/saturable_reactor.yaml` (two `transformer` parts),
`varimu/synth/` (outside the render cache key), `tests/test_reactor.py`; open: how to
treat the JA core's ratcheting minor loops (the plan's S1 status, three options). Where
the track goes in the order is also the user's open decision. Playable since 2026-10-29:
the passive reactor low-pass `config/circuits/reactor_filter.yaml` is the native app's
`reactor_filter` device (JA cores live: `panel::Device::cores`), played from a MIDI
keyboard (`varimu-app`'s `midi` module: a test oscillator into the device, not part of it;
`varimu-app --device reactor_filter --midi masterkey --play`). S2's circuit,
`config/circuits/tube_filter.yaml` (tube stages around the reactor, a 6V6GT setting the
cutoff, a 12AX7 Q multiplier, a 6386 VCA, its own 6X4 / selenium supply), is the
`tube_filter` device. S3 (2026-10-30): circuits can have **control inputs** (`cv_inputs:
{name: node}` in a circuit file, `controls` in the IR, driven by their own samples, linear
between them; circuitsim, `fast.run_transient(..., controls=)`, the app's `Live`; ngspice
runs none; IRs without them unchanged), and `config/circuits/tube_voice.yaml` (a keyboard
bus gating a diode-steered envelope into a push-pull 6386 VCA) is the `tube_voice` device.
S4, the oscillator (2026-10-30; the user's priority: the sound's character, drift fine):
prototypes measured by `scripts/vco_study.py` -> `reports/tube_synth/vco/`. (b), the
reactor-tuned LC `config/circuits/vco_lc.yaml`, works: 52-1655 Hz, a 0.57 s glide (the
ratchet), 0.56x real time at draft; it is the app's `vco_lc` device (draft-2x), its pitch
from the keys through a measured tuning (`panel::Pitch`, `panel::key_feeds`; `vco_study.py
--tuning`). `config/circuits/tube_synth.yaml` is the voice with that oscillator on one
supply (the 6V6GT's screen on two 5651s: unregulated, the VCA's sag dropped held notes
~780 cents), the app's `tube_synth` device (keys -> gate and pitch; `panel::Device::
partition`: four threads, the VCA | the input and filter | the oscillator | the
supplies): ~62% load, worst block ~99% at a 50 ms buffer (TUBE_SYNTH_PLAN.md, S4's
status). Its oscillator has a RANGE switch (`range`: 0 LOW 224 nF 18.8-789 Hz, 1 HIGH
56 nF 26-1736 Hz; a contact always in the circuit, so a flip updates a stream in place),
the app's panel LOW / HIGH / AUTO (AUTO per key, split at 330 Hz; `panel::RangeSwitch`,
a tuning table per range: docs/SYNTH_LOW_END.md). **Partitions in N parts (2026-10-30):** a `partition` list's `"|"` (or, in
sim_settings.yaml, a nested list) separates groups, each on a thread of its own
(`circuitsim::partition::GROUP_BREAK`); a shared node is owned by the highest-numbered
part with it (list the stiff drivers, the supplies, last), the others see it as a
source; the owner needs a DC path there. One group is the old two-way split, bit for bit. (a), the diode-timed multivibrator `vco_diode.yaml`
on the new `6AL5@1`, doesn't run cleanly yet; (c) isn't started (TUBE_SYNTH_PLAN.md, S4's
status). **S5's modulation measured (2026-10-30; TUBE_SYNTH_PLAN.md S5's status, options to the user, nothing built):** the cutoff follows V4's grid within ~5 ms, pitch steps settle in 17-45 ms (big drops 0.1-0.24 s); ENV -> CUTOFF as a second 6V6GT on the control windings (+1-3% CPU); a key's VCA sag already pulls the cutoff ~half an octave down (V4's screen on b1); a tube kick prototype rings at ~0.3x real time but its core's saturation gives no pitch drop. Built since: V4's screen on its own 5651s (a key moves the cutoff 23-142 cents, was 67-808; tables re-measured) and ENV AMOUNT (`env_amount`: V7, a 6V6GT on the control windings, its grid on the envelope), the app's split now five threads (the VCA | the resonance pair | input, filter, cutoff and envelope | the oscillator | the supplies); `examples/play.rs --hold NOTE` measures a voice's load with a key held. **A tube kick** (2026-10-30): `config/circuits/tube_kick.yaml`, the app's `tube_kick` device (`panel::Device::own_oscillator`: keys gate it, the test oscillator off): the synth's reactor oscillator running, a key's edge sweeping its pitch (TUNE, DEPTH, SWEEP TIME) and opening a differential tube VCA that decays (DECAY), then TONE (a 12AX7 Sallen-Key low-pass, ~50 Hz-1.2 kHz, ~1.5 dB bump); `tests/test_tube_kick.py`. A `rheostat` part can be `reverse: 1` (a reverse-taper pot: resistance falls as it turns up). Capacitors can have a start voltage (a C part's `v0`, IR `Capacitor.v0_v`, held
for the DC operating point only; absent = unchanged IR). Ideas for a more diverse synth
(2026-10-31: 25 in priority order, the user liked all of them; built one at a time in that
order): [docs/SYNTH_IDEAS.md](docs/SYNTH_IDEAS.md). #1 GLIDE built (`glide`: 82k onto 4.7 uF
ahead of the pitch stopper; the 6V6GT's grid leak now a 1 GOhm numerical one, so the
tuning tables were re-measured; `scripts/glide_study.py`). #2 KEY TRACK built (`key_track`: a second keyboard
string, the control input `key`, 0.75 V a key, 0 V at C4 (`key_*` values; the app's
`panel::KeyString`, `Feed::Key`), under the CUTOFF pot; `scripts/keytrack_study.py`).
#3 velocity (the bus's key-down volts from a measured table, `panel::Device::velocity`,
Play's Velocity range; `scripts/velocity_study.py`) and aftertouch (control input
`pressure`, 0-15 V, `Feed::Pressure`, the PRESSURE pot under KEY TRACK) built.
#4 HEATER built (`heater`, 0.6-1.1 of rated, below 0.9 marked out of rating: a `heaters`
block's `tap: KEY` scales the heater ratio, both builders; `scripts/heater_knob_study.py`).
#5 PULSE prototyped and parked (CPU; `scripts/pulse_prototype.py`). #6 RESERVOIR built
(`reservoir`: 1-40 uF in steps, 20 default; the ripple's hum-growl, below 6 uF the pitch
warbles and goes flat; `scripts/supply_study.py`; the rectifier switch dropped). #7 the LFO built: a Wien bridge held by
a #327 pilot lamp (`lfo` section; RATE `lfo_rate`, ~0.08-19 Hz) on a new device, the
incandescent **lamp** (`varimu/devices/lamp.py`, `LAMP327@1`, kind `lamp`: tungsten's
published fits, pins (a, t, b), its temperature the node t, 1 V = 1 K, on a 1 F capacitor;
Python, SPICE, circuitsim `devices/lamp.rs`, both builders; `tests/test_lamp.py`), with #8's
VIBRATO (`vibrato`: summed into the pitch ahead of GLIDE, tuning tables re-measured) and
WOBBLE (`wobble`: into the CUTOFF pot's low end, its law unchanged); the app's split now six
threads (the LFO its own); `scripts/lfo_study.py`. The LFO has a supply of its own (a winding,
silicon rectifiers, a 5651 pair's -174 V): on the synth's rails it ran the 6X4 past its
rating. LFO ON / OFF (`lfo_on`, `unit: switch`: a control the app draws as a checkbox): OFF
empties the `lfo` section, which then gets no thread. #14 the ring modulator built out of order
(the user's call; `scripts/ring_study.py` -> `reports/tube_synth/ring/`): oscillator x LFO, a
selenium diode ring between two mumetall transformers with a 12AU7 follower per input and a
make-up stage, on the LFO's supply; the LFO's AUDIO range (`lfo_audio`, a checkbox: switched
contacts, ~8 Hz-1.9 kHz) makes it a carrier, at LFO rates a tremolo through zero. RING ON
(`ring_on`, a checkbox, off at first: nested in the LFO's switch, so with either off the `ring`
section is empty and gets no thread), RING and OSC level pots in the mixer; the app's split
puts `ring` on a thread ahead of the oscillator. A second VCO as the carrier waits for #9.
#15 ADSR built out of order (`scripts/adsr_study.py` -> `reports/tube_synth/adsr/`): the attack
ends at a 12AX7 comparator (envelope vs the keyboard bus) latched by two 12AU7 inverters,
which switch a 12AU7 attack follower off and a 12AU7 decay switch on toward SUSTAIN; 6AL5
clamps; a -340 V rail off the HV winding. DECAY, SUSTAIN (1 = the old AR); the envelope runs
on a thread of its own. The slowest attack / fastest decay are fragile when the rails sag
(left so, the user's call).
Per feature only targeted tests run (the user's call); the full suite and `--verify` are
batched (SYNTH_IDEAS.md "Owed"): **run 2026-11-02, nothing owed** (647 passed after one
stale count fixed; `--verify` PASS).

Hybrid physics ([docs/HYBRID_PHYSICS_PLAN.md](docs/HYBRID_PHYSICS_PLAN.md), 2026-11-01, the
user's idea): synthesis stays pure, except where the physics is far faster than a sample (a
gas tube's reset, a multivibrator's flip, a carrier above Nyquist) or is spread in space.
There, that part alone becomes an **exception**, generated from a full-physics reference
simulation of the same part and coupled at its ports, with the reference selectable in its
place. A proposed Hard rules addition is still the user's open call. **The gas-tube sawtooth
(SYNTH_IDEAS #23) is built, H1-H4 (2026-11-02..03, merged from the `gas-tube` worktree; the
plan's H1-H4 status blocks):** a thyratron model (`varimu/devices/thyratron.py`: the ion
density as a state node, w over k with a 1 F capacitor; Python, SPICE, circuitsim's
`devices/thyratron.rs`), fitted to the 2D21's sheets with the 884's structure (`2D21@1`,
`884@1`, the user's tube; RCA's sweep circuit `rca_884_sweep.yaml` the reference). Two
techniques: **M1** (renders) a multi-rate island behind an anti-alias FIR decimator (a
section's `substeps`, `decimate: fir`, `owns: [node]`; `partition::Decimator`), and **K** (the
live qualities) event kernels (IR `ThyratronEvents`, tables over grid volts and log slope
from the reference at 3.072 MHz, charge-exact pulses: `config/events/*.json` by
`scripts/thyratron_kernels.py`; `varimu/devices/thyratron_events.py` the reference,
circuitsim's `events.rs` the port). A `devices` entry's `events: NAME` names the tables;
`build(..., events=True)` / Rust `build_ir_events` swaps them in and drops the island; the
draft's `events: true`, the app's `Circuit::with_events` (production and prints build M1).
K's tables need a whole number of 3.072 MHz samples per step (96 kHz: the draft, draft-2x).
A section its switches leave empty is no island (both builders). RCA's sweep is a documented
hard case (the user's option A). **The voice** `config/circuits/saw_884.yaml` (the app's
`saw_884`: a 6V6GT current sink charging 5 nF, the 884 across it, a 12AU7 follower, gated by
tube_voice's AR envelope into tube_kick's VCA, cross-neutralized; ideal rails; tuning
`scripts/saw_884_tuning.py`) and **tube_synth's second oscillator** (SAW ON `saw_on`, off at
first; OSC ON `osc_on` for the LC, on at first: off empties an oscillator's sections, no
thread; its own supply with regulated screen and cathode rails; a second keyboard string
`pitch2`, `panel::Device::pitch2`, `SYNTH_SAW_TUNING` from `saw_884_tuning.py --target
synth`; GLIDE's and VIBRATO's second gangs, the latter buffered; SAW level into the mix).
Every synth script and test passes `pitch2` (0 V with the saw off). `panel::Device::coupling`
overrides the partition coupling per device ("hold" where a one-sample edge crosses a cut:
saw_884's VCA grid; the synth keeps extrapolate). CPU: one oscillator at a time fits (the saw
alone ~ the LC alone); both on is over budget on this desktop. The saw alone still drops out
live (worst blocks 104-142%): [docs/SYNTH_REALTIME_PLAN.md](docs/SYNTH_REALTIME_PLAN.md)
(2026-11-04, nothing built; run on an idle machine) measures scheduling against compute,
then fixes without changing the sound. Open: K reads sharp of M1 in
the bass (+23-33 c at ~40-50 Hz, the one-solve reference itself not converged there: the
plan's H4); the unit's 5 kHz floor.

Drums ([docs/DRUM_PLAN.md](docs/DRUM_PLAN.md), 2026-11-01): real drums as a modal medium
coupled at ports (membranes, tension-modulation pitch drop, beater contact, snare wires and
cymbals as hybrid exceptions), old drum machines as circuits (the Wurlitzer Sideman: its
service manual and patents found, DRUM_PLAN.md D2; 808 / CR-78 after a BJT model), tube drum
voices from `tube_kick`. **D1 prototyped offline in Python** (`varimu/drums/`, outside the
render cache key; `config/drums/{tom_13,kick_22}.yaml`; `scripts/drum_study.py` ->
`reports/drums/<drum>/{bare,drum}/`; `tests/test_membrane.py`, `tests/test_drum.py`):
`membrane.py` a bare head in vacuo, `drum.py` both heads on a shell coupled through the air
(normal modes per azimuthal order, exact sparse tension modulation, a coupled range below
`f_coupled_hz`), 9-14x slower than real time in Python. The user's verdict: still weak ("a
mug dropped in another room": a distant mic, no muffling, no chain); kept as is. **Since
2026-11-04 the track is electric drums first** (the user's call; DRUM_PLAN.md "The direction
since 2026-11-04": D2a-D2c, then bending). **D2a built:** the Wurlitzer Side Man's bass drum
`config/circuits/sideman_bd.yaml` from schematic 501648 (a 12AX7 phase-lead oscillator
degenerated below oscillation by R106, the panel's RING, struck by its ground-out key line
through a silicon-diode contact on the control input `gate`; the 6AV6 preamp as a 12AX7
section; ideal +305 / -22 V rails until the machine's supply; sources
`data/schematics/wurlitzer_sideman/README.md`): idles at the drawing's +1.5 V / +174 V, rings
~70 Hz (-20 dB in 117 ms at RING's default, 51 ms to 1.4 s over RING, a drone below ~0.45),
the app's `sideman_bd` device (0.13x real time at draft-2x); `scripts/sideman_study.py`,
`tests/test_sideman_bd.py`. Open: the user listens.

The Victorian synth ([docs/VICTORIAN_SYNTH_PLAN.md](docs/VICTORIAN_SYNTH_PLAN.md),
2026-11-01, the user's idea, parked until they pick it up; nothing built): a janky synth
from parts that existed by ~1881, wired with today's knowledge (Leclanché cells that sag,
Gray's contact-breaker reeds, gas-tube and spark-gap sawtooths, carbon-granule key VCAs and
carbon relays as the amplifier, the saturable reactor on period iron, telephone receivers).
Milestones V0-V6; it shares the gas tube with HYBRID_PHYSICS_PLAN.md's H1.

Real instruments ([docs/INSTRUMENT_PLAN.md](docs/INSTRUMENT_PLAN.md), 2026-11-01, parked
until the user picks it up; nothing built): exciter -> resonator -> radiator -> room, the
resonators as modal media from geometry (offline FEM, per-mode BEM radiation; GPU with a
CPU reference), contacts folded into the medium's port (not one sample late like the
plate), full-physics references (time-domain FEM, lattice Boltzmann) checking reduced
models. Proposed order: a church bell (the pipeline), the Rhodes Mk I Stage (passive, no
BJT), the Wurlitzer, the piano (hysteretic felt, nonlinear coupled strings, soundboard),
the pipe organ last (jet-drive flue pipes, reed pipes, the wind system as one coupled
circuit). Milestones I1-I8. **The Rhodes** ([docs/RHODES_PLAN.md](docs/RHODES_PLAN.md),
2026-11-04; RH1 built): the Mk I of Stevie Wonder's records; per key only
mechanics (tine and tonebar modes, a brief hammer contact, a pickup table), so every key
rings live and the shared amp is the cost; a live tier and a production tier (time-domain
beams, a 3D pickup map with the magnet's force, sympathetic coupling) from the same physics,
the production one checking the live one; Stage into the 5E3 or the Suitcase after the BJT
model (the user's call). Milestones RH1-RH6. **RH1 built 2026-11-04 (the user: "let's build the
rhodes"; RHODES_PLAN.md's "Status"): one key offline in Python,** `varimu/rhodes/` (outside
the render cache key), `config/rhodes/mk1.yaml`, `tests/test_rhodes.py`,
`scripts/rhodes_key_study.py` -> `reports/rhodes/key/` (WAVs of the pickup's EMF, no amp).
The service manual's tine cutting chart digitized (`scripts/digitize_rhodes_tines.py` ->
`data/datasheets/rhodes_tine_lengths.csv`); the tone bar assembly as beam FE (`beam.py`),
one fit per unknown to a different source (spring -> the note, the bar's length balances
the fork, grommets -> Muenster & Pfeifle's bar resonance, the tine's loss -> Shear's Q);
the pickup a 2D magnetostatic FE map (`pickup.py`, cached in `cache/rhodes/`); a strike
with the contact inside the step, complex modes live against the full system (`key.py`).
Not fitted and matching: the mid-keyboard contact (~6-7 ms vs 6.42), Shear's voicing
(centred: the 2nd harmonic dominates). The user: "sounding pretty good". **RH2 built 2026-11-04 (the user: the full
plan, 73 keys, out of the 5E3 from the start; RHODES_PLAN.md's RH2 status):** all 73 keys
fitted (`scripts/rhodes_fit_keys.py`, cached in `cache/rhodes/keys_*`), the damper and pedal,
voices over events with re-strikes (`harp.py`), the manual's Fig. 10-4 wiring, a velocity
law, MIDI (`midi.py`), the Stage into the 5E3 as one netlist
(`config/circuits/rhodes_stage_5e3.yaml`, GENERATED by `scripts/derive_rhodes_5e3.py`);
`scripts/rhodes_render.py (--midi F | --demo)` -> `reports/rhodes/renders/`;
`scripts/rhodes_keyboard_survey.py` -> `reports/rhodes/keyboard/`. Open: the user listens;
the harp's absolute level (the 2D pickup); keys 46-49's Q. **RH3 built 2026-11-04
(RHODES_PLAN.md's RH3 status): the harp in circuitsim, played live.** The component
`MK1_HARP@1` (kind `ep_harp`: `config/components/mk1_harp/1.yaml` pins its data
`1.harp.json` by sha256; compiled by `varimu/rhodes/compile.py`,
`scripts/compile_rhodes_harp.py [--check]`: per key the live tier's halved complex modes, the
arc reduced to rank 3-4, the damper's transfers; the flux map's B-spline, the velocity law,
the coils). circuitsim's `harp.rs` is a medium (IR `Harp`, driving `out`, sensing nothing)
played by `media::NoteEvent`s (`Transient::queue_note`, `Stream::queue_notes`,
`simulate_notes`, Python `simulate(notes=)` / `fast.run_transient(notes=)`, `harp_render`):
rendered ahead in chunks up to the last known event, voices on up to three worker threads
(the same bit for bit on any number). Rust vs the Python reference -128 dB
(`tests/test_rhodes_compiled.py`, `crates/circuitsim/tests/harp.rs`). The part `harp: [out]`
in both builders (bit for bit; fixtures keep the model once). Live without the speaker's
readout (the user's choice): `build_ir(..., speaker_readout=False)` / `build_ir_live` put a
speaker's terminal voltage on `out`, the app's `panel::Device::live_speaker_v` (the Rhodes
device `rhodes_stage_5e3`; the 5E3's own Play unchanged, C3 open). The app: `midi::Keys::
take_events`, `player::note_offsets`, `Live::process_notes`. Every key ringing live: 80-84%
load, 0 dropouts (`examples/play.rs --strike-all [VEL] --restrike S`); live full scale 20 V
(the 5E3's largest swing; the user: raise the level only where it doesn't change the sound).
Open: the user plays it; next RH4. **Touch** (2026-11-04, RHODES_PLAN.md "Touch"): a
keyboard's Sensitivity (`curve`: the dB line bent into an ease-out, (1 - x)^p, p 1-5) and
Range as `midi::Touch`, applied to velocities as they
arrive (`Keys::message`: devices, takes and renders get the velocity heard), on the harp's own
30 dB law (`live::key_velocity_span_db`); the Play view's sliders, saved per keyboard in
`app.json`. Strike and release variation (repeated notes sound alike) is
parked future work: [docs/RHODES_VARIATION.md](docs/RHODES_VARIATION.md). The Suitcase's
side-to-side pan (its stereo "vibrato") is future work too, nothing built: RHODES_PLAN.md
"The side-to-side pan" (the Suitcase after the BJT model, a tube stereo panner chain end
first, or a Leslie; the user's pick).

Sidechain ([docs/SIDECHAIN_PLAN.md](docs/SIDECHAIN_PLAN.md), 2026-11-01; picked up
2026-11-04 for one track keying another's 670, the kick ducking the bass; branch `sidechain`):
**K1 done**, the keyed 670 `config/circuits/fairchild_670_keyed.yaml`, generated from the
stock file by `scripts/derive_keyed_670.py` (`--check`; never edit the generated file): a
KEY INT / EXT switch (`key_mode`) ahead of T103's primary, the KEY jack the control input
`key` behind 600 ohm (terminated at INT); INT renders as the stock 670 exactly; its profile
`varimu/measure/keyed_suite.py` (`varimu unit --circuit fairchild_670_keyed`; renders via
`fast.run_transient(controls=)`, uncached: `RenderJob` has no control inputs yet). **K2
done**: `render::render_controls` (bit for bit with Python, `app_render_agreement.py`),
`panel::Device::key`, the device `fairchild_670_keyed`, prints with a sidechain
(`print::Slot::key`, a `KeyRoute`), `player::TimelineKey` for live auditions. **K3 built,
the user to try it**: stable track ids (`session::Track::id`), the session-wide chain
signature (a keyed track's includes what its key track plays; it prints once its keys'
prints are current; loops refused), the insert panel's KEY row. Keyed, the 670 has no
ratio but a cliff (-2 to +2 dB of key: a 4 dB duck to the 6386s cut off), so **DEPTH**
(`key_depth`, the user's option B, 2026-11-04): at EXT an EL34 follower from B+ on the DEPTH
wiper clamps the CV line through a silicon diode (its own -174 V supply off T302: a silicon
half-wave, two 5651s); about -3 to -10 dB nearly regardless of the key up to 0.45, fully
clockwise no limit (the plan's "DEPTH", with why simpler clamps failed). Then K4 (FLAT / LP
/ HP at the pick-off), K5 split-band parked.

Delay ([docs/DELAY_PLAN.md](docs/DELAY_PLAN.md), 2026-11-01): a slappy echo from physical
machines, delay time never a parameter (a head distance over a tape speed). Then the Echoplex
EP-2, the EchoSonic; later the Echorec, the oil can, an acoustic pipe. **Started 2026-11-03
(the user's: REPEAT from the start, ping-pong, more; "The 351 echo"):**
`config/circuits/ampex_351_echo.yaml` (GENERATED by `scripts/make_351_echo.py` from
`ampex_351.yaml` and the alignment report: a passive console's SEND and REPEAT, the slap out
wet only; `tests/test_351_echo.py`), printed literally by `scripts/print_351_echo.py`. Live,
the tape is **reduced** (`varimu/delay/reduced.py` the reference, circuitsim's
`TapeReduction` / `ReducedWorker` the port, `tests/test_tape_reduced.py`): per layer a table of
M_x against a constant field and a recording aperture from the reference's step response,
playback the stream's own with a demagnetization correction D(k); generated per machine by
`scripts/tape_reduction.py` -> `config/tape_reductions/<name>.json` (refused by both builders
for another medium). Against the full stream: -34.7 / -28.7 / -25.2 dB at 0 / +6 / +12 dB
drive, every third-octave band within 0.43 dB. A tape part's `reduction: NAME` plays in an
events build (the live qualities), its bias substeps' sections then at the audio rate; a
control's `events:` value is its setting there (the 351's oscillator out). The app's
`ampex_351_echo` device and chain end: 0.5x real time at draft-1x (DELAY_PLAN.md "Status
(2026-11-03)"). **VARISPEED** (`capstan_hz`): a tape part's `supply: NODE` (1 V = 1 Hz) and
`supply_nominal_hz` drive the capstan's motor (IR `TapeMedium.varispeed`: the transport's
hunting resonance, a sample late), positions, the EMF and the reduced apertures follow;
`tests/test_tape_varispeed.py`, `scripts/varispeed_demo.py`. **PING-PONG**: the 351-2
(`ampex_351_2_echo.yaml`, generated beside the echo: two channels on two tracks of one tape,
the console crossed), a stereo chain end in the app (a circuit's `out_r` probe), and the
**medium as a partition cut** (a tape senses a record head in another single-rate part a
sample late; partition.rs): with `coupling: hold` (extrapolated, Newton stalled on the
crossed feed), 0.54x real time. **DRIVE** (both echoes): a console tube line amp ahead of
SEND, 0 to +22.6 dB (12.4 dB of tape compression at full); the reduction's tables to +-200
kA/m (checked to +24 dB over operating). **7.5 ips** (2026-11-03): `ampex_351.yaml`'s `speed`
(a tape part per speed in a switch, TP / TP_LO: a speed change restarts the tape erased) and
`equalization` (EQUAL SWITCH 4S2a: 1C46 for 1C7, contacts always in, a value change; the
playback EQ is the same at both speeds on this board), 1C46 aligned by `align_351.py --low`
(at its 1600 pF end, still -2.6 dB at 10 kHz: the provisional heads, the user's call); a
reduction per speed (`ampex_351_lo.json`; a switch's sub-parts all expand, so both must
exist); live 0.28x real time. **Fixed:** `Mna::media_senses` now includes a tape's capstan
supply (a probe-only DK run read its stale value: the mono echo's tape ran at a third of its
speed since VARISPEED). **BIAS** (2026-11-04): BIAS ADJUST (`bias_adjust_f`) on both echoes'
panels; live, a tape part's `reduction_bias: bias_adjust_f` reads it through the reduction
file's measured `bias_map` (5C13 against the head's bias on the literal machine), and a
reduction is `points` over the bias (tables, apertures and D(k) per point: D depends on the
bias; IR `TapeReductionPoint`, circuitsim `ReductionPoint`, the reference
`reduced.BiasReductions`), interpolated in ln(bias); a turn updates the stream in place
(`TapeStream::set_bias`). Regenerating both files takes ~3 h (`tape_reduction.py`: each
point's D(k) is a full-stream reference). Next (the user's): the condition dials
(DELAY_PLAN.md's proposal).

Distortion ([docs/DISTORTION_PLAN.md](docs/DISTORTION_PLAN.md), 2026-11-04, parked until the
user picks it up; nothing built): warm, gritty tube overdrive from physics with many dials,
each a part value (VARIAC, RECTIFIER, BIAS / CLASS, COUPLING x GRID LEAK, the iron,
condition dials). It runs on rendered audio, printed as a session insert at production (the
user's; live only to audition). Milestones O1-O8: the Fender 5F1 Champ first, then a grit
box grown from it. The 5E3 can already be printed as an insert.

Grooves ([docs/PHONO_PLAN.md](docs/PHONO_PLAN.md), 2026-11-01): vinyl, the acoustic gramophone, wax cylinders and tin foil as one
machine, a groove written along arc length (a print between the recording and the player)
and read by a tip (morphological dilation, a Hertz contact in the stylus' port, mistracking
as a hybrid event), on the tape's medium structure. The acoustic players are one
mechano-acoustic network (needle, soundbox, arm, horn: the impedance analogy, the speaker's
precedent; Maxfield and Harrison 1926 the anchor), acoustic recording a horn into wax fed by
MIC_ROOM_PLAN.md's room; old sound as physical condition (needle wear, wear per play,
governor hunting). Milestones G1-G8, the acoustic machines proposed before vinyl. **The wax
cylinder first, built 2026-11-02** (PHONO_PLAN.md's "Status (2026-11-02)"; offline Python,
`varimu/phono/`, outside the render cache key; `config/phono/edison_standard.yaml`;
`tests/test_phono.py`; `scripts/cylinder_study.py [--file SONG --start S] [--variants smooth
played worn close]` -> `reports/phono/cylinder/`): an Edison two-minute cylinder recorded
acoustically (the 16 in studio horn, a studio 2 in glass diaphragm, the cutter into wax, the
loud passages cut to the ~10 um limit) and played on a Model C (the groove dilated by the
tip, a Hertz contact, the floating weight, a mica diaphragm, a 30 in horn, the pressure 1 m
out). Mechano-acoustic networks in the mobility / impedance analogies (`network.py`, MNA,
IR element types only), Webster ladders (`horn.py`), each machine's spring motor, flyball
governor, belt and the cylinder's runout as the wow (`transport.py`), dust, mould and cracks
as seeded geometry (`damage.py`), earlier plays by Archard's law (`wear.py`). The user's
verdict after comparing with real transfers: the `played` take is the reference; their In
the Pines rendered whole with it (~9x slower than real time). Next, not decided: the
circuitsim port (G1's Rust half), the gramophone (G2), the surface across the tip's patch
(G6). Pin BLAS to one thread (`OPENBLAS_NUM_THREADS=1`) when another job saturates the
cores: its small solves ran ~100x slower.

Mics, preamps and rooms ([docs/MIC_ROOM_PLAN.md](docs/MIC_ROOM_PLAN.md), 2026-11-01; nothing
built; the user picks it up deliberately): source -> room -> capsule -> mic electronics ->
cable -> preamp, rendered, not real time. Mic + cable + preamp one netlist, the capsule's
front / back pressures as control inputs (the polar pattern from its physics); the room a
cached linear medium (IRs per source and mic), any floor plan with vaulted ceilings and
objects, GPU FDTD below a ~4-8 kHz crossover and GPU geometric acoustics above (the user:
use the RTX 3080 wherever it fits). First listen: U47 -> V76 (B10). The list: small
pressure omni (the capsule's verification case), U47, RCA 44-BX, SM57, C12; V76, the 351's
electronics, Neve 1073, API 312, clean transformerless, UA 610; four opposite chains ranked
by the separation metrics. The BJT model is a shared prerequisite (with the drums).
Milestones A1-A9. **Started 2026-11-03 (the user's): U47 -> V76.** A1 = the device
builder's **B10, the Telefunken V76**: `config/circuits/telefunken_v76.yaml` from IRT drawing
S 1176 (gain / filter switches, T85 / T89 and its chokes on JA cores, version-1
constructions provisional; selenium supply `B450C80@1`), tubes `EF804S@1` / `E83F@1` with a
new opt-in pentode **screen law "e1"** (`KorenPentode.screen`: Ig2 = E1^Ex / Kg2; absent =
Koren's, every existing IR unchanged), `tests/test_telefunken_v76.py` (idle vs the printed
voltages); its profile `varimu/measure/preamp_suite.py` (`varimu unit --circuit
telefunken_v76`, the Braunbuch's acceptance specs: the nominal unit meets 47 of 50; misses and
the calibrated T85 values in DEVICE_BUILDER_PLAN.md B10's status). The app plays it (`telefunken_v76`, 0.26x
real time at draft-1x). **A2 done:** capsules as components (kind `capsule`,
`varimu/devices/capsule.py`; parts `capsule`, `capsule_dual` in both builders; pressures as
volts; self-noise from Johnson noise on the acoustic resistances), `varimu/measure/ac.py` (AC
analysis of linear IRs, the reference), `BK4134@1` checked (18.6 dB(A) vs B&K's 18,
`tests/test_capsule.py`). **A3:** `VF14T@1`, `config/circuits/neumann_u47.yaml` (idles at the
drawing's point only with its underheated cathode: a -0.32 V space-charge shift from B6's model),
the chain `u47_v76.yaml` (`scripts/compose_chain.py`), `scripts/mic_print.py`; the K47
(`K47@2`, `scripts/fit_k47.py`) in Torio & Segota's regime (a nearly slack diaphragm, the
gradient resistance between the sides; `data/schematics/neumann_u47/K47_THEORY.md`) with
rigid-sphere diffraction for its entries (`varimu/mics/free_field.py`): the whole U47 at 25.4
mV/Pa cardioid (ds58: 25-28), 13-15 dB front to back (MIC_ROOM_PLAN.md A3's status). The U47's sources:
`data/schematics/neumann_u47/README.md`. The first listen was heard (2026-11-04: "it all sounds
good", subtle). **`K47@3`** (2026-11-04; the U47 and the chain pin it since, the user's call): the capsule's real body for its entries, `varimu/mics/bor.py` (a body-of-revolution BEM,
azimuthal order 0 only: exact for the diaphragm's axisymmetric average; checked on the sphere's
series and Lamb's disk, `tests/test_bor.py`; the K47 geometry's `body` block), the network
refitted on it: the omni's 6.5 kHz dip gone, the presence peak at ~11 kHz, omni 16.8 mV/Pa
(in ds58). `free_field.capsule_entry_pressures` picks body / sphere / path from a capsule's
geometry; `mic_print.py --distance-m` prints a point source (proximity). **The SM57** (and SM58), MIC_ROOM_PLAN.md's A7, is
planned in [docs/SM57_PLAN.md](docs/SM57_PLAN.md) (2026-11-04; nothing built; milestones SM1-SM8; the user's 2026-11-05: both mics, the
pre-1980s transformer, the nominal mic only, high SPL after the first listen): a
`moving_coil` component (a gyrator B l / S to the coil, the rear phase-shift network, the
dome's shell modes, B l(x) from a magnet FE map), its output transformer as a C2 design,
the SM58's ball grille as a permeable BEM surface; passive, so no BJT model needed.

**The room loop** ([docs/ROOM_LOOP_PLAN.md](docs/ROOM_LOOP_PLAN.md), started 2026-11-04, the
user delegating its decisions; MIC_ROOM_PLAN.md's A4 and A9): sources placed in a shoebox room,
mics placed and aimed, each through its chain. `varimu/rooms/` (outside the render cache key):
`entries.py` (a capsule's front / rear entries tabulated over angle to its axis x 1 / r x
frequency, the BEM's `bor.entry_table` solved once per frequency, cached in cache/diffraction/),
`shoebox.py` (image sources keeping their directions, each through its table; the diffuse tail
96 shared plane waves, so a cardioid's diffuse level and spaced mics' coherence come out of the
physics), `scene.py` (scene files, `render`: per mic the chain printed, cached in
cache/rooms/prints/; `solo=True` each source alone: the bleed matrix), `binaural.py` (stereo
separation: better-ear glimpses, Lavandier & Culling's BMLD); `scripts/room_print.py SCENE`;
`tests/test_rooms.py`. **The opposite chain** (R4): `omni_4134` (`BK4134@2`: @1 on its 1/2-inch
housing as a `cylinder` body, `bor.pressure_mesh`; a TL071 follower) into `clean_pre` (an
NE5534A gain stage) = `omni_clean.yaml` (compose_chain.py), on a new macro part **`opamp`**
(both builders, a symbol `OpAmp`: single pole from a datasheet's A0 / GBW, optional clamp diodes
at a swing; data/datasheets/opamps/README.md); `tests/test_clean_chain.py`. **R5:**
`scripts/room_separation.py` (two sources, spots through the chains, a spaced omni room pair
panned hard; -> reports/rooms/separation/summary.json, mixes for
`separation_listen.py --room`). **The app's Room view** (`varimu-app --room`; `room_view.rs`,
`varimu_app::room`): the plan drawn to scale, sources (session tracks) and mics dragged and
aimed with their patterns, Render runs `room_print.py` as a background process (`uv`), a
session track per mic, panned (`SessionView::add_room_tracks`); scene per session in
`<session>/rooms/scene.json`; `crates/varimu-app/tests/room.rs` (ignored: needs uv). **Rooms of any shape** (R6,
2026-11-04): `varimu/rooms/polyroom.py` (a floor polygon, a flat / shed / gable / vault
ceiling; image sources to 4 reflections validated per mic, the tail's level and decay
ray-traced, 4 pi c e(t) / V, shaped per mic by the rays counted at it); scenes with `floor_m` use it (the Room view's Shape and Ceiling,
corners dragged), `dims_m` keeps the shoebox; `scripts/room_demo.py` -> reports/rooms/demo/.
**R7-R11 built (2026-11-05, overnight, the user delegating; ROOM_LOOP_PLAN.md "Status
(2026-11-05)"):** R7 a material per face (`materials.faces: {"wall N", "ceiling N", floor}`,
"wall N" from the plan's corner N as given; the Room view picks a wall on the plan); R8 R5 on
polyroom (`room_separation.py --room poly [--wave HZ]`: cells move <= 1.3 dB, conclusions
stand); R9 **crates/roomsim**, the project's first GPU code (wgpu, Vulkan on the 3080, an f64
CPU reference per kernel; Python `roomsim` in the `fast` extra, `varimu.rooms.gpu` picks gpu /
cpu / numpy, `$VARIMU_ROOM_BACKEND`, a stale build refused like circuitsim's): ray tracing
(64-bit fixed-point sums: bit-identical runs) and the image sources' spectra, 20-50x faster;
R10 the **wave solver** (`varimu/rooms/wave.py`, roomsim's `fdtd`: Bilbao's finite-volume
rectilinear scheme on the voxelized room, one run per octave band under the crossover with
that band's admittance, capsule entries to first order from their tables, blended amplitude-
then power-complementary; a scene's `settings.wave_crossover_hz`, `room_print.py --wave`, the
Room view's "Wave solver", 500 Hz for new scenes; ~6.5 s per source at 500 Hz in 123 m^3, x16
per doubling); R11 **objects** (oriented boxes in `room.objects`, a gobo a thin one: image
sources to order 2, occlusion, rays, the grid) with **first-order BTM edge diffraction**
(`varimu/rooms/diffraction.py`: objects' edges, a plan's reflex corners; on the GPU as
micro-images sharing a spectrum); the Room view's OBJECTS. **Directional sources** (from the
plan's "Later", the same night): `varimu/rooms/directivity.py`, a cap on a sphere (presets
voice, amp_1x12, amp_2x12, bass_1x15; a scene source's `directivity` and `aim`; on-axis
normalized), images and diffraction weighted in their emission directions, rays started with
|D|^2, the wave solver with the source's body in its grid. Demos: `scripts/room_wave_demo.py`
-> reports/rooms/wave_demo/, `scripts/room_gobo_demo.py` -> reports/rooms/gobo_demo/,
`scripts/room_source_demo.py` -> reports/rooms/source_demo/, `room_demo.py --wave 500 --out
reports/rooms/demo_wave` (READMEs there). Open: the user listens; the Room view's new controls are tested but not seen on screen.

Track separation ([docs/SEPARATION_PLAN.md](docs/SEPARATION_PLAN.md), 2026-10-31): tracks
diverged by opposite physical recording chains (devices, per-pass tape flutter, rooms and
distance; mics later). The cheap first experiment is built (`varimu/separation/`,
`scripts/separation_study.py` -> `reports/separation/`, audio in
`cache/separation/conditions/`): each track matched to -23 LUFS on its own, a glimpse
pre-screen (energetic only, on the dry notes' cells), and the listening staircase
`scripts/separation_listen.py` (`--with sounddevice`), whose results are pending (the user's).
**How the ear separates sounds** ([docs/SCENE_ANALYSIS.md](docs/SCENE_ANALYSIS.md),
2026-11-04, a research session the user asked for): the neuroscience distilled (harmonicity,
common onset, temporal coherence; FM incoherence and ITD barely group), four grouping measures
after published models (`varimu/separation/grouping.py`: temporal coherence, onset
coincidence, harmonic cancellation, the mr-sEPSM's SNRenv; `tests/test_grouping.py`) and
`scripts/grouping_study.py [--only conditions bus intervals]` -> `reports/separation/grouping.json`.
Found: per-pass flutter separates nothing (SEPARATION_PLAN.md's "common fate" withdrawn); a
30 ms timing offset moves the measures more than any chain; a saturating or compressing bus
(dev(t + m) vs dev(t) + dev(m), the interaction residual) costs the lead its harmonicity and
half its glimpses, and its intermodulation lands on a root only for octaves and fifths in
equal temperament. Proposals there (glue without mud: share the supply, not the
nonlinearity); nothing validated by ear yet.

**Noise (device builder B5, 2026-10-30; DEVICE_BUILDER_PLAN.md B5's status):** a circuit
file's `noise: {seed}` block turns on Johnson noise (IR `NoiseCurrent` per resistor of R /
pot / t_pad parts and windings, not `numerical:` leaks or core-node resistors), tube shot /
partition / grid-current shot and flicker noise (`TubeNoise` per triode and pentode; flicker
a grid-referred K_f / f, provisional, a ~1 kHz corner for a 12AX7) and the mains wander (the
`mains` parts' amplitude times 1 + m(t), 0.5% rms, provisional); `build(..., noise=)`
overrides (None / False / True / a seed). Only tube_synth has the block: nothing else moved.
Streams: Philox4x64-10 keyed (seed, crc32(name) << 32 | stream), sample k a pure function of
k, on the project's 96 kHz grid from the run's start (settle included), linear between
samples (the density times sinc^4(f / fs)); `varimu/devices/noise.py` is the reference,
circuitsim's `noise.rs` the port (DK solver only: current columns), SPICE via filesources
(`io.run_transient(..., noise=)`). Spectra vs theory and the engines' agreement:
`tests/test_noise_spectra.py`. The app's Play view has a "Noise" switch (off saves the CPU).

**Heated cathodes (device builder B6, the heater, 2026-10-30; DEVICE_BUILDER_PLAN.md B6's
status):** a circuit file's `heaters: {start?: warm | cold, tap?: KEY}` block gives every triode, pentode
and vacuum diode one cathode temperature (IR `heaters` block + `HeatedCathode` per tube),
heated at the mains setting's ratio to the rated mains times B5's mains wander, through a
7 s thermal lag; it acts through the space-charge shift (+1.7 mV/K as on the grid, zero at
the rated temperature) and a Richardson emission ceiling (relative to the rated
temperature's, so a tube at the rated heater is its fitted model exactly). Constants in
`config/cathodes.yaml` (phi 1.22 eV fitted to Phywe's EC92 by `scripts/fit_cathode.py`;
heater ratings per tube type); `varimu/devices/cathode.py` the reference, circuitsim's
`cathode.rs` (DK only), SPICE via a copy of the tube (`spice.heated_lines`). Only tube_synth
has the block. `build(..., heaters=)` overrides (None / False / True / "warm" / "cold"); a
cold start (power on) skips the settle; the app's "Power on (cold)" button.

**Knob changes restart at first order (B6, the pot end stop, 2026-10-30):** after
`Transient::update` the next sample starts with backward Euler over h / 256, then the method
(a pot thrown to its 1 mOhm end next to a series capacitor used to thump tens of volts:
the carried-in derivative). Live streams only; renders never update. No pot end resistance
(the user's call: inaudible at realistic values). DEVICE_BUILDER_PLAN.md B6 has the numbers.

**Tape** ([docs/TAPE_PLAN.md](docs/TAPE_PLAN.md), started 2026-10-31 ahead of the queue, the
user's call; milestones TM1-TM7): an **Ampex 351** (tubes; the Sun slapback family) with
**Scotch 111**, saturation from simulated particles, not curves. The user: quality before real
time, rendering (a print) is fine at first, it may sit on the whole mix bus. Particles are a
continuous Preisach ensemble (`varimu/devices/preisach.py`: a closed-form corner formula over
suffix extrema, rate independent, so AC bias costs only its peaks; a discrete grid is the
tests' oracle), not JA (minor-loop ratcheting). **TM1 done:** `SCOTCH111@1` (kind `tape`,
`varimu fit-devices --only SCOTCH111`: 3M Sound Talk No. 20's remanence curve plus Eilers'
Hc; `varimu/devices/tape_fit.py`); `SCOTCH111@2` adds the particles' orientation (kappa 1.5,
vector Preisach). **TM2 mostly done:** `varimu/devices/tape.py` (head fields with finite poles,
recording a 2D slab of cells at the bias peaks, reciprocity playback, slab demagnetization of
the audio band with the head's image under the head, vector Preisach orientations) against
No. 21's bias curves (Ampex 300): matched up to and past the peak; the model's curves are
narrower in bias than the data (the user chose to move on; the plan's status, step 7, lists
the candidates). **TM4 done:** circuitsim's `tape.rs` (the recording kernel) and
`tape_stream.rs` (the port of `tape_machine.TapeStream`: the record gap's field in per
sample, the repro EMF of the next out; 16 mm blocks recorded with the demag fixed point once
the head has passed, read a head distance, 50.8 mm, later), the IR element `Tape` (like
`Plate`: `media.rs`; SPICE holds its out at 0 V), the `tape` part in both builders
(`tape: [rec_plus, rec_minus, out]`, the tape component and 16 physical values; numerics
fixed, `parts.TAPE_*`), `config/circuits/tape_test.yaml`; Rust against the Python reference
within 4e-13 (`tests/test_tape_stream.py`); 16.5x real time in a circuit. The print is the
stream (`print_audio`, all in Rust). **TM3 done:** the coating's grain (Poisson particles
plus an exponentially correlated packing field, `SCOTCH111@3`'s `noise` block fitted to Sound
Talk No. 34 by `scripts/fit_tape_noise.py`; tape-only S/N 72.9 dB at 15 ips,
`scripts/tape_snr.py`; prints seed 1, `--no-noise`) and the transport (`TapeMachineSpec.
transport`: capstan, idler, reel, motor hunting, scrape flutter; a tone recorded and played
back deviates the 351's 0.11%, `scripts/tape_flutter.py`); cells are 7.62 per bias
wavelength (0.5 um at 15 ips: 1 um aliased the bias residue into the audio band), prints
~2x slower for it. **TM5 in progress (2026-11-01):** `config/circuits/ampex_351.yaml` from the 1962
schematic (record 12AX7 / 6201 / 6201, repro 12AX7 x2 into a 12AU7 push-pull and 6T3 with its
feedback winding, the 6X4 supply; the oscillator only as its load), the new `6201@1` (RCA's
sheet), idle vs the drawing in `tests/test_ampex_351.py`, 46.7x real time at production; the
bias coupling measured on `ampex_351_bias.yaml` at 3.84 MHz (`scripts/tape_bias_study.py` ->
`reports/tape/bias_coupling.*`; TAPE_PLAN.md TM5's status): the user chose A, the literal oscillator in a partition of its own (2026-11-01).
**A is built:** circuitsim's multi-rate parts (a section's `substeps:`, IR `Section.substeps`:
its own thread at m steps per sample, currents averaged per sample, owns no shared node; it
may hold the audio input; `partition.rs`), the medium's literal mode (`TapeStream(literal=M)`,
IR `TapeMedium.bias_substeps`: M samples of the head's whole field per push, recorded at their
extrema), the tape part's `bias_substeps` (senses a record coil drawn in the multi-rate
section). The 351's record side runs at 20 substeps (3.84 MHz; 10 left a line in the noise,
TAPE_PLAN.md "Gaps" 4); multi-rate parts step without local error control (it beat with the
oscillator: TAPE_PLAN.md "Speed"); it meets the rest only at the
input and the reservoirs (a cut through a coupling capacitor diverges). Production's probes
are decimated to 96 kHz and hide the 99 kHz: measure the bias at `oversample` 1. 106x real
time on the drums (was 46.7x). A GPU for the recording kernel is planned (TAPE_PLAN.md: f64 is slow on a 3080).
**The 351 aligned and printed (2026-11-01):** the manual's alignment as a procedure on the whole
machine (`varimu/measure/tape_align.py`: playback EQ from a virtual test tape, bias at the
median of the 1/2 dB points, record EQ, RECORD LEVEL for 1% THD at 400 Hz, PLAYBACK LEVEL for
+8 dBm; `scripts/align_351.py` -> `reports/tape/ampex_351_alignment.*`, cached by circuit, code
and settings, ~32 min), the transport on the tape part (`parts.TAPE_TRANSPORT`, 13 optional
values, all or none, both builders), `rep_h_per_a` calibrated to the drawing's -68 dB, and
prints through it: `uv run --extra fast --extra listen python scripts/print_351.py --drive-db 0 6
12` (~58x real time for the three at once). The 351's profile: `varimu unit --circuit ampex_351
--name NAME` (`varimu/measure/tape_suite.py`; before the heads' change below: S/N 61.6 dB, the
response failing +-2 dB at 70 Hz, the provisional heads' contour; TAPE_PLAN.md "Gaps"). The tape stream records its blocks
on a worker thread (bit-identical; the 351 100x -> ~74x real time; TAPE_PLAN.md "Speed").
**Studies before model changes (2026-11-02):** frequency-dependent switching (Sharrock) is not
the cause of the tape's misses (`scripts/tape_switching_study.py`: <= 0.4 dB on No. 21, the 3%
level, No. 14; closed, SCOTCH111@3 stays); the heads are (`scripts/tape_heads_study.py`). Applied
(the user's choices): record gap 51 um (the Ampex 300's), repro contour pole 1.5 / relax 5.5 mm
(calibrated to the +-2 dB spec, near Nortronics' WP head), record coil 8.0e6 A/m per A, 3 mH:
the response passes (-1.84 / +0.94 dB), the 3% level +4.8 dB (on #111's Sound Talk No. 1),
its S/N miss was a numerical line from 10 substeps (the bias peaks' parabola; now a quartic,
`refine_extremum`, both languages; back to 20 substeps; `scripts/tape_snr_study.py`). Profile
`ampex351_heads51`; `scripts/speed_351.py` times the record side's settings (TAPE_PLAN.md
"Gaps" 3-4, "Speed"). **Tape speed and a fast tier** are planned in
[docs/TAPE_SPEED_PLAN.md](docs/TAPE_SPEED_PLAN.md) (2026-11-02, parked; nothing built): the
literal print faster (P1-P6: the parts' split measured, decoupled by a block of lag, parallel
in time, a cheaper fast-part method, the tape kernel on the GPU, the draft tier) and a fast
tier trained on it (F1-F5: flutter and noise split off, a grey-box reduced medium first, a
neural core if needed; the literal machine stays the print).
**The first print** (idealized NAB electronics, aligned as the 351 manual says;
`varimu/devices/tape_machine.py`): `uv run --extra fast --extra listen python
scripts/tape_print.py --clip drums_setmefree.wav --seconds 10 --drive-db 0 6 12` ->
`reports/tape/audio/` (-18 dBFS rms = 0 VU; ~24x real time since the zone floor and per-cell zones, TAPE_PLAN.md "Speed"). Sources:
`data/schematics/ampex_351/`, `data/datasheets/tape/` (READMEs).

Reverbs as physical media coupled to the netlist at transducer ports are drafted in
[docs/REVERB_PLAN.md](docs/REVERB_PLAN.md) (2026-10-30; milestones E1-E7). **The plate is
built (2026-10-31; the plan's "Status (2026-10-31)")**: `varimu/devices/plate.py` (the
reference) and circuitsim's `plate.rs` (an EMT 140-sized plate's ~26,000 modes from its
dimensions, steel and tension; each mode's decay from the EMT 140 TS brochure's measured
curves, digitized by `scripts/digitize_emt140.py`; force at the exciter to acceleration at
the pickup, as an impulse response), the IR element `Plate` (senses the exciter coil's
current, drives its pickup node one sample later through `circuitsim::convolve`; SPICE holds
the pickup at 0 V; `Mna::n_media`, `Transient::step_media`), the component `EMT140@1`, the
`plate` part in both builders, and the device `config/circuits/plate_reverb.yaml` (our own
tube drive and pickup amplifiers: the V54's schematic isn't public; DRIVE, DECAY at 500 Hz,
RETURN; output wet only), the app's `plate_reverb`. `scripts/plate_report.py` ->
`reports/reverb/`. Then the stereo pair, sends (F4), the spring and the 6G15. More reverbs
(2026-11-02, a brainstorm, nothing built): REVERB_PLAN.md's "Candidates" (ranked: the EMT
240 gold foil, the spring, a nonlinear plate / tam-tam, a magnetostrictive line,
sympathetic strings; then the BX20, wires, water, rooms). **A chain's end** (2026-10-31):
a device after the one played, on threads of its own a block behind (`player::EndDevice`,
`panel::CHAIN_ENDS`: the plate; Play's CHAIN END; `examples/play.rs --end plate_reverb`):
the synth through the plate plays without dropouts (REVERB_PLAN.md, "Live chaining").
**The spring and the EMT 240 (2026-11-04; REVERB_PLAN.md "Status (2026-11-04)", the
decisions delegated):** the spring as a modal medium (Parker & Bilbao's curved rod has exact
modes on a finite spring: `varimu/devices/spring.py` the reference, circuitsim's `spring.rs`;
the IR element `Spring`; the plate's modal sum and convolver now `circuitsim::modal`, the
plate bit for bit unchanged), the tank `ACC4AB3C1B@1` (kind `spring_tank`, part `spring_tank:
[plus, minus, out]`; the input transducer saturates), `6K6GT@1` (RCA's points incl. its
large-signal figures), the Fender 6G15 `config/circuits/fender_6g15.yaml` (the app's
`fender_6g15`, a chain end, 0.40x load; `scripts/spring_report.py`); the EMT 240 as a plate
(its brochure: bending, "constant resonant density"), `EMT240@1`, `foil_reverb.yaml` (the
app's `foil_reverb`; `plate_report.py --circuit foil_reverb`). `scripts/reverb_listen.py`:
one clip through the three, loudness-matched. Open: the user listens.

**Devices in the session** ([docs/SESSION_FX_PLAN.md](docs/SESSION_FX_PLAN.md), 2026-10-30;
milestones F1-F5): processors move into the Session view as track inserts and sends,
**printed** offline into cached audio rather than played live (one live device at a time:
the one being adjusted, F3). Decisions (the user's): the plate first; an audition takes the
live slot; an insert's trim is set once from the take (-18 dBFS), not re-normalized. **F1
done:** `varimu-app`'s `print` (a slot's print of audio through a device at a quality, keyed
by sha256 of the input, the built IR, the settings, gains and `SOURCE_HASH`, kept in
`<session>/prints/<key>/`; chains; background `Job`s below normal priority;
`examples/print.rs`): 30 s through the 670 prints at 0.42x real time at draft-1x, 11.4x at
production. **F2 built**: `Track::inserts` in `session.json`, the mix plays a track's print
(`Track::playing`), insert chips under each strip and the selected insert's panel at the
bottom of the Session view. **F3 built** (after the user's first try): an open insert panel
plays that device live on the track where the transport is (`player::Source::Timeline`,
`PlayView::adopt`), knobs heard in ~0.3 s (the 670: 53% load, 0 dropouts); the session plays
without a device (`Source::Mix`, `Player::start_mix`); the worker's output stage is
`player::Emitter`. An insert has a wet / dry share (`Slot::wet`, `Monitor::wet`): the
plate reverb goes in at 30% wet with an 8 s tail. **⤓ Render** bakes a track's chain at
production into a new take and removes its inserts (`Session::add_rendered_take`,
`Take::rendered_from`; Undo restores), **⤓ Draft** the same at the inserts' play qualities
(from the print cache when current); the session plays tracks-only when no instrument
plays (▶ always there; ● starts the instrument and records once it plays). **Export**
(2026-11-05, RECORDING_PLAN.md T4's bounce): ⤓ Export mix… writes what ▶ plays
(`Session::mixdown`) to a stereo float WAV from bar 1 with a .json of its sources and
optional stems that sum to it, once every audible track is ready (`export_problems`);
⤓ Export final… sets the inserts to production and renders MIDI takes at production first.
The Room view renders each source track as the mix plays it (its print, not the raw take).

**The sampler** (2026-11-02, the user's ask): the user's sample library sorted into the repo's
git-ignored `samples/` by `scripts/import_samples.py` (drums first: `samples/drums/<category>/`,
`index.json`; `samples/README.md`), played in varimu-app as an instrument: Play's device
"Sampler" (`--device sampler`), twelve slots one per key of an octave (every octave plays
them), a browser of `samples/` whose files preview as they are clicked or stepped with
↑ / ↓ (never recorded), Enter loads into the marked slot; the kit kept in `sampler.json`
beside `app.json`. `varimu_app::sampler` (voices, cubic interpolation at the file's rate),
`player::Source::Sampler` (no circuit, 64-sample blocks, the Emitter as every source), so the
Session view records it like the synth. `examples/sampler.rs` plays a beat on the pads into
an armed take and checks its onsets.

MIDI takes ([docs/MIDI_TAKES_PLAN.md](docs/MIDI_TAKES_PLAN.md), 2026-11-04; N1-N4 first
versions built the same day, the plan's "Status"; milestones N1-N7): a take is the notes plus the panel, monitored through a cheap digital
**proxy** that follows the panel through tables measured on the real device (the user's
choices: proxy or device picked by hand, never automatically), rendered offline behind the
recording (draft, then production on demand), edited in a piano roll; polyphony through a
generated `tube_synth_poly` whose voices share the supply, the LFO and the output (the
most organic first, the user's call), four voices, allocator reuse-same-note then
round-robin, GLIDE per voice. The rest the user delegated (the plan's decisions 8-14):
partitioned per voice at production too, a 5U4GB supply, one shared output transformer,
render behind after every take. N1 is RECORDING_PLAN.md T2's steps 2-3. **Built
(2026-11-04):** `varimu_app::performance` (events at their samples in the block, the
`Performer`: the keyboard logic live and offline, a note shorter than a block kept),
`Live`'s log of where each knob build landed (a restart with the input and controls it
settled at), Record from keys = `Player::begin_event_take` (a fresh device settled in the
background, PREPARING, then the count-in), `varimu_app::take_render` (the replay: bit for bit
at the quality played, `examples/take_replay.rs` on tube_synth through the real player;
production via a stream with production's options, 25x slower than real time on
tube_synth), event takes in `session` (revisions `events.<n>.json`, never written over; undo
picks the revision; renders in `takes/<id>/renders/<key>/`; `Take::sound`: PROD > draft >
heard > stale), the Session view (♪ badges, draft renders behind for edited and proxy takes,
⤓ Production on demand, "play drafts" per track; per track "rec MIDI | AUDIO" and "hear
DEVICE | PROXY"; a MIDI take's lane draws its notes), the piano roll (`crate::piano_roll`:
Select / Draw / Erase tools, each gesture one revision), the proxy (`varimu_app::proxy`,
`Source::Proxy`, `config/proxy/tube_synth.json` by `scripts/proxy_tables.py`; Play's
"Monitor through the proxy"). Open: the proxy's unmeasured tables (envelope pots, RESONANCE,
ENV AMOUNT, mixer, single cycles: a sweep owed), its cost (16 voices ~2% of a core, target 1%).
After the user's first try (2026-11-04): the roll's tools, take ids never reused, per-track
⤓ PROD and bounce to an audio take. The final render's
compute ([docs/SYNTH_MASTER_PLAN.md](docs/SYNTH_MASTER_PLAN.md), 2026-11-04; nothing built;
milestones Q1-Q8; the user's: every lever in, each measured): a `master` quality above
production (the user's; production unchanged), one solve without the partition (poly as one
solve at master only, the user's), the render-only features (both oscillators, PULSE), circuit
`detail: master` parts (strays, ground network, distributed windings, core loss), Preisach
reactor cores at master (S1's minor-loop decision, delegated: closed loops with return-point
memory instead of JA's ratchet; live stays JA; an A/B in Q6), excess noise and heater hum,
per-voice tolerance draws; tuning tables per quality. Capacitor DA is out (measured inaudible).

Recording in the native app (a metronome click, takes from the keyboard or an input, tracks
layered and overdubbed) is drafted in [docs/RECORDING_PLAN.md](docs/RECORDING_PLAN.md)
(2026-10-30; milestones T1-T6). A take
is stored as its events (keys, knob changes at the sample they landed, from a defined start)
plus the draft audio heard. Tracks play that audio back while the user iterates, so they cost
almost no CPU. Production is a final render from the events, on demand (the user's call). T2
closes S3's open done-when. **T1 built (2026-10-30, merged from the `recording` worktree):**
varimu-app's `transport` (the grid, a click on its exact sample mixed after the monitor,
count-in, pre-roll; the worker's `Clock` in every player source: `Player::set_transport`,
`transport_run`, `Status::transport`), `loopback` (an input or an output's own mix captured
with dated callbacks, clicks found per pitch to a fraction of a sample, drift, round trip vs
cpal), the app's Session view (`session_view.rs`, prefs in `%APPDATA%\varimu\recording.json`; sessions in the repo's git-ignored `sessions/`)
and `examples/click.rs`. On Realtek's output loopback: 1199 of 1199 clicks in 10 min within
0.0005 samples, 0 ppm; through the UA Twin's own loopback (its input channels 3-4, bit-exact):
1199 of 1199 exactly, round trip 46.6 ms vs cpal's 36.9. The output loopback captures every
program's sound on that output (another session's test tones masked clicks).

A crude end-to-end slice exists ahead of plan order ("end-to-end early,
fidelity later"): one 670 channel as one coupled netlist
(`config/circuits/fairchild_670.yaml` -> `varimu/circuit/builder.py`; see
"Circuit files" below), audio
I/O and a cached parallel runner (`varimu/sim/io.py`, `runner.py`), and a
tweak-and-listen page (`varimu/listen/`). Results are in `reports/slice/`
(compression curve, Time Constant bursts, program clip, `--verify`) and
`reports/transformers/` (each transformer standalone). Its transformers
(Phase 2) are windings on Jiles-Atherton cores (`varimu/devices/core.py`;
materials in `config/magnetics.yaml`, mumetall fitted to its datasheet by
`scripts/fit_core_material.py`) with leakage, winding R, self-capacitance,
the cores' joint gap and classical eddy loss; geometry, turns, leakage and
capacitances are provisional genome parameters (`genome_bounds.yaml`
`transformers`). Since Phase 3 the circuit has the 670's power supply, traced
on the drawing (`data/schematics/fairchild_670/README.md`, "Supply rails"):
the mains (an IR `SineSource`) into T302 / GZ34 / L301, the EL34 / 6084 / 5651
regulator (240 V, B+ ADJ), the selenium bias supply (the 6386 cathode return
at C303, ZERO, the 6973 grid-leak return), and idle channel 2 lumped onto the
same rails. Unprinted supply values are genome parameters, three nominals
calibrated by `scripts/calibrate_psu.py`. Every part and tube instance
deviates by its own seeded draw (`passive_seed`, `passive_spread`; the
nominal genome has spread 0), each 6386 bank is its four triodes, and
`varimu.sim.setup.adjust` sets B+ ADJ / BALANCE / ZERO per the manual.

**Circuit files (device builder B1, 2026-10-25).** A circuit is a YAML file in
`config/circuits/`: parameters with sources (`controls`, `values`,
`device_params`, `derived`), `mains`, `tolerance`, `devices` (model instances)
and `sections` of macro parts (`NAME: {<macro>: <nodes>, params}`). The format's
reference is the docstrings of `varimu/circuit/spec.py` (loading, `resolve`,
genome links) and `varimu/circuit/builder.py` (the macros, devices, tolerance
draws, `build` -> IR + SPICE); the macros expand with the parts library
`varimu/circuit/parts.py`. A physical value is a parameter key or
`{value, source}` inline, never a bare number (load error). An optional `full_scale`
block gives a circuit its own volts at 0 dBFS in and out (else sim_settings' 13.8 V;
`varimu.sim.io.full_scale`, varimu-app's `Circuit::full_scale`). `varimu/circuit/netlist.py`
is the 670's API on top (`nl.build`, `nl.resolve`, ... unchanged for callers);
its derived values (channel 2 lumped) are in `varimu/circuit/fairchild_670.py`.
`config/circuits/triode_stage.yaml` is the small second circuit
(`tests/test_circuit_format.py`); `config/circuits/pultec_eqp1a.yaml` the Pultec
EQP-1A (B2: sources in `data/schematics/pultec_eqp1a/`, tests in
`tests/test_pultec.py`). Measurement is per circuit (`varimu/measure/profiles.py`):
the 670's suite as before, the EQP-1A's `varimu.measure.eq_suite`; render jobs name
their circuit (`RenderJob.circuit`, None = the 670). A change to a circuit file that should leave the
circuit alone must leave `export_circuit_fixtures.py --golden` without a diff.

**KiCad (device builder B3, 2026-10-26).** Circuits can be drawn in KiCad 10 with the
symbol library `kicad/varimu.kicad_sym` (one symbol per macro part; generated from
`varimu/kicad/symbols.py`, whose docstring and `kicad/README.md` list the fields:
Reference = part name, Value = main value or key, Source / Param / Genome / Tol, lowercase
fields = the macro's other params). `varimu kicad-import` reads kicad-cli's XML netlist
(`varimu/kicad/netlist.py`) plus the sidecar `<project>.params.yaml` (what isn't a part)
and writes a circuit file (`varimu/kicad/importer.py`: sheets are sections, rotary
switch decks are resolved into `switch` parts, Core + Winding symbols are transformers).
`varimu kicad-export` writes a circuit file as a label-connected project
(`varimu/kicad/export.py`). The pre-flight checks are `varimu/preflight.py` (unconnected,
floating, source / inductor loops, rectifier nodes fed by an inductance without a
capacitor, probes) at every switch combination; the import runs them and writes nothing
when they find a problem. An imported circuit builds the hand-written one's IR up to
element order (`varimu/kicad/compare.py`; order moves renders ~-130 dB, measured in the
plan's B3). `kicad/generated/` (the EQP-1A and a deliberately broken copy) and
`tests/fixtures/kicad/*.xml` come from `scripts/make_kicad_fixtures.py`; tests that need
kicad-cli skip without it. KiCad 10.0.7 is installed per user
(`%LOCALAPPDATA%\Programs\KiCad\10.0`, not on PATH); `find_kicad_cli` looks at
`$VARIMU_KICAD_CLI`, PATH, then the installer's folders. None of `varimu/kicad` or
`preflight.py` is in the render cache key.

**The schematic editor (device builder B4a, 2026-10-26).** Circuits are drawn in our
own web app, not KiCad (the user's decision): `varimu listen`, then
http://127.0.0.1:8765/editor (`#c=<circuit>&s=<section>&sel=<part>` links). A drawn
circuit's source is `config/circuits/<name>.drawing.json` (`varimu/editor/drawing.py`:
the sidecar's content, frames = sections, symbols with placements, wires, labels,
grounds; mm, y down, 1.27 mm grid). `varimu/editor/connect.py` turns it into a
`varimu.kicad.netlist.Netlist` (a pin joins any wire through its point, a wire's end on
another wire is a T, crossings don't join, same-named labels are one net) and
`compile.py` runs the KiCad importer's core on it, then `varimu.preflight` (problems
carry their nodes and elements, mapped back onto symbols and nets). Hand-written
circuits (670, EQP-1A, triode stage) open as generated drawings (`layout.py`, never
saved over them) that compile back to their IR (`tests/test_editor.py`); edits to them
save as a new circuit (Save as writes `<name>.drawing.json` and the compiled `<name>.yaml`).
Edits render on a loop through the listen app's queue (`RenderJob.circuit` takes a .yaml
path: the compiled drawing in `cache/editor/`), A/B loudness-matched; a drawing needs an
`out` node to be heard (a drawing with one always probes it). Topology edits are
`varimu/listen/editor/geom.js` (place, move with rubber-banding wires, turn, delete,
copy / paste), the tools `tools.js`. The page's rules are tested in Node's own runner
(`tests/editor_js/`, from pytest, on the real symbol table; skipped without Node);
`scripts/editor_draw_triode.py` draws the triode stage through the UI (Playwright via
`uv run --no-project --with playwright`, the installed Chrome). The hand-written
circuits' schematics are drawn by scripts (`scripts/draw_pultec_eqp1a.py`,
`draw_fairchild_670.py`) on `varimu/editor/sketch.py`, which checks a layout pin by pin
against its circuit (`problems()`); rerun a script after a change to its circuit (part
or node names), and `tests/test_editor_drawings.py` tells when that's due. The page is plain ES modules (`varimu/listen/editor.html`,
`varimu/listen/editor/*.js`, no npm, no build step) on the API in
`varimu/listen/editor_api.py`; the look is the dark "studio" direction the user chose
(`docs/editor_mockups/`). Symbols come from `varimu/kicad/symbols.py`'s table as JSON.
None of `varimu/editor` is in the render cache key. For page work, run the server with
reload: `uv run python -m uvicorn varimu.listen.app:create_app --factory --port 8790
--reload --reload-dir varimu/editor --reload-dir varimu/listen` (the JS is read per
request).

A fast Rust circuit simulator (`crates/circuitsim`, ngspice stays the
reference) is planned in [docs/CIRCUIT_SIM_PLAN.md](docs/CIRCUIT_SIM_PLAN.md).
Work its milestones in order, with the same "done when" discipline.
**M0 (scaffolding), M1 (circuit IR), M2 (linear engine), M3 (devices and
Newton), M4 (the 670 slice on the fast engine), M5 (nodal DK) and M6
(default engine) are done, except M5's speed target (10x faster than
ngspice; 5-7x so far), deferred (decided 2026-10-17; the plan's M5 status
lists where to start). M7 and M8 stay deferred after Phase 2 too (decided
2026-10-21, the user delegating: nothing in main-plan Phases 3-5 needs a
second circuit or real time, and renders at 6-7x real time are workable);
next is main-plan Phase 3. Phase 2's core is in circuitsim (the circuit-sim
plan's "Phase 2 in circuitsim").** **M8's draft quality (2026-10-27, in progress;
the plan's M8 "Draft quality"):** `--quality draft` (render / unit / listen; the
listen page's and the editor's quality selector; sim_settings.yaml
`circuitsim_draft` on top of `circuitsim`): TR-BDF2 at a 96 kHz internal rate (1x at
the project's 96 kHz = a 48 kHz host at 2x), no error control, Newton 1e-3 / 1e-2 V,
tube tables (`devices/triode_table.rs`: every Koren section is `(Vp/Kp)^Ex Phi(u)`,
one 1-D table per bank, 9e-8 of the exact model), the cores' linear limit, and the
supplies (power, bias, idle channel 2) on a second thread coupled through the rails
with one sample of latency (`partition.rs`, `Mna::externals`: -103 dB from the one
solve; it bends "one coupled simulation" for the draft only, the user's call). The 670
runs 1.1-1.2x slower than real time on two cores (production: 14-18x). `--quality
draft-1x` (`circuitsim_draft_1x`: a 48 kHz host at 1x via `TransientSettings.host_rate`,
the engine resampling to it and back) runs it at 0.81-0.86x, within ~-45 dB of
production (top octave up to 0.7 dB off): a ballpark while playing. **The Play page**
(`varimu listen`, then /play) loops a clip through it in real time while the front panel
turns (the 670 or the EQP-1A: `play.DEVICES`) (`varimu/sim/live.py`, `varimu/listen/play.py`; `circuitsim.Stream`: block-by-block
runs equal to a whole run, `update` for knob changes, `stream.rs`). Production is
untouched (every new option off). The periodic
agreement test against ngspice is
`slice_report.py --verify` (Commands); run it after changes to the engine,
the circuit or the device models. It checks behaviour (GR, attack/release)
vs production ngspice, waveforms vs exact-formulation ngspice on six short
excerpts (TC1-4 bursts, the clip's loudest and HF-richest 0.25 s), both of
those with both engines on linear cores, and the clip vs circuitsim's
converged solution with the Jiles-Atherton cores, with regression bounds a
few dB outside the measured values (re-measure them when the circuit
changes); numbers in the circuit-sim plan's M6 follow-up and "Phase 2 in
circuitsim".
**What the references are for (decided 2026-10-21):** accuracy is judged
against circuitsim's converged solution and analog behaviour; ngspice is the
independent cross-check that catches bugs, best with the exact triode
formulation on short excerpts (its tabulated triodes are only good to about
-55 dB on hot material); behaviour metrics (GR, attack/release) are compared
with production ngspice. Details: the circuit-sim plan's Verification section.
`netlist.build()` builds a typed circuit IR (`varimu/circuit/ir.py`) and emits
SPICE from it (`varimu/circuit/spice.py`); the Rust side reads the same IR as
JSON (`crates/circuitsim/src/ir.rs`) and simulates it at a fixed step
(`mna.rs`, `transient.rs`), with compiled ports of the Python device models
(`devices/`). The default solver is nodal DK (`dk.rs`): the linear part
folded into responses of the step matrix once per step size, Newton on the
22 device ports with the factored Jacobian reused and unmoved devices not
re-evaluated; `solver: mna` is M3-M4's Newton on the device-node block of the
full MNA system (`newton.rs`), the reference DK is tested against.
`Transient::update(ir)` changes component values mid-run (device state, a
core's magnetization, carries over). Transformers in the IR (v2): `Winding`s
on a core node whose voltage is B (1 V = 1 mT) and a `MagneticCore` device
on it; `netlist.build(cores="ja" | "linear")` (default `devices.cores: ja`);
a "ja" build has no SPICE text (`Circuit.text` is None), and ngspice renders
always build "linear" (`TransientSettings.cores`). `varimu.sim.fast.run_transient(ir, x)` is the Rust counterpart
of `varimu.sim.io.run_transient` (same oversampling and decimation).
Production settings are the `circuitsim` block of `config/sim_settings.yaml`:
esdirk4 at 2x, 5th-order input interpolation, local error control (chosen by
M4's method study; the plan has the numbers), DK with Newton tolerances
1e-4 / 1e-3 V (M5). `simulator.engine` picks the engine for renders,
the CLI, the listen app and `slice_report.py`: **circuitsim by default
(M6)**, ngspice by name (`--engine ngspice`). Without the `fast` extra,
renders stop with instructions (`fast.EngineUnavailable`); nothing falls back
to ngspice silently. circuitsim renders run in-process on the runner's
threads (GIL released), at the `runner:` priority (Windows thread priority),
with progress and Ctrl-C through `circuitsim.simulate(progress=...)`.

## Commands

```sh
uv sync --extra fast             # install; renders need fast (add listen|ml|optimize when a phase needs it)
uv run pytest                    # tests
uv run ruff check . && uv run ruff format --check .
uv run varimu signals [--seed N] [--only NAME ...] [--list]
uv run varimu genome-status
uv run varimu fit-devices [--only 6386 ...]   # refit device models; a changed fit -> a new version config/components/<name>/<N>.yaml
uv run python scripts/digitize_ge6386.py --overlays DIR   # re-digitize the 6386 sheet
uv run --with pymupdf python scripts/digitize_jensen_p12r.py   # C3: the P12R sheet's curves from the PDF's vector paths
uv run --extra fast varimu render --clip data/clips/x.wav --set ac_threshold=0.7 time_constant=3 --out r.wav
uv run --extra fast varimu render --signal steps_1000hz --vary time_constant=1,2,3   # parallel, cached
uv run varimu render --signal burst_1000hz_0dbfs --engine ngspice   # the reference engine
uv run --extra fast varimu render --clip data/clips/x.wav --quality draft   # M8's fast draft (sim_settings circuitsim_draft; also unit, listen)
uv run --extra listen --extra fast varimu listen   # http://127.0.0.1:8765 (editor: /editor, blind A/B: /ab, real-time play: /play)
uv run --extra fast python scripts/slice_report.py [--engine ngspice] [--clip NAME]   # curve, TC bursts, program clip -> reports/slice/
uv run --extra listen --extra fast python scripts/slice_report.py --verify   # periodic agreement test (both engines; ~70 min cold since Phase 3, ~1 min warm)
uv run --extra fast python scripts/transformer_report.py [--only t101 ...]   # each transformer standalone -> reports/transformers/
uv run python scripts/fit_core_material.py mumetall   # refit a core material's JA parameters to its datasheet figures
uv run --extra fast python scripts/calibrate_psu.py    # re-derive T302's voltage, L302's resistance, B+ ADJ from the printed/measured rails
uv run --extra fast python scripts/corner_sweep.py [--quick]   # genome corners: simulates? GR rises? quiet at idle? -> reports/corners/
uv run --extra fast varimu unit --name NAME [--genome FILE] [--set k=v ...] [--no-clips]   # Phase 4: genome -> setup -> renders -> reports/units/NAME/ (exit 2: rejected)
uv run --extra fast varimu unit --circuit pultec_eqp1a --name NAME [--set k=v ...]   # B2: the EQP-1A's profile (response vs published curves, THD) -> reports/units/NAME/
uv run --extra fast varimu unit --circuit fender_5e3 --name NAME [--set k=v ...]   # B9: the 5E3's profile (gain, response, THD / power, sag, aliasing) -> reports/units/NAME/
uv run --extra fast python scripts/calibrate_pultec_psu.py   # B2: the PCC-55's HV voltage from the drawing's +325 V rail
uv run varimu kicad-import kicad/NAME/NAME.kicad_sch --out cache/kicad/NAME.yaml   # B3: drawing (+ NAME.params.yaml) -> circuit file; exit 2 = check problems
uv run varimu check --circuit NAME                 # B3: pre-flight checks at every switch combination
uv run varimu kicad-export --circuit NAME --out DIR   # B3: a circuit file as a label-connected KiCad project
uv run python scripts/draw_fairchild_670.py [--check] [--dry-run]   # B4a: the 670's schematic -> config/circuits/fairchild_670_drawn.* (also draw_pultec_eqp1a.py, draw_fender_5e3.py)
uv run --extra fast python scripts/draft_settings_study.py [--only eqp1a|670] [--fresh --repeat 2] [--rows PREFIX ...]   # the draft's levers: speed vs sound against production -> reports/realtime/
uv run python scripts/make_kicad_fixtures.py       # B3: kicad/varimu.kicad_sym, kicad/generated/, tests/fixtures/kicad/ (needs kicad-cli)
uv run --extra fast python scripts/plausibility_check.py [--only NAME ...]   # the checks on nominal, Phase 3's flagged and deliberately broken genomes -> reports/plausibility/
uv run --extra listen python scripts/build_clips.py --root DIR [--only NAME ...]   # Phase 5: program clips from multitrack stems (config/listening.yaml mixes) -> data/clips
uv run --extra listen --extra fast varimu ab-prepare [--candidates NAME ...] [--swap KEY=VALUE ...] [--targets 3 6]   # Phase 5: match the pool (config/listening.yaml) on data/clips -> SQLite + reports/listening/matching.json
uv run --extra listen --extra fast varimu listen   # then http://127.0.0.1:8765/ab: blind A/B session (keys: Space, 1/2, A/B/N), ABX staircase, difference listening
uv run python scripts/tolerance_study.py    # solver settings vs accuracy -> reports/slice/
uv run python scripts/export_circuit_fixtures.py [--golden]   # IR + device fixtures for Rust tests (+ SPICE goldens)
uv run python scripts/export_app_fixtures.py     # native app R1: Python-built IRs for varimu-circuit's agreement test
uv run python scripts/export_audio_fixtures.py   # native app R2: scipy resample_poly fixtures for varimu-app's resampler
uv run python scripts/export_editor_fixtures.py  # native app R3a: Python's compile of the drawn circuits (and broken copies) for varimu-circuit's tests/editor.rs
uv run --extra fast python scripts/app_render_agreement.py [--quality production|draft-1x]   # R2: the app's render vs Python's, bit for bit
```

Rust (`crates/circuitsim`; workspace `Cargo.toml` at the repo root, output in `target/`):

```sh
cargo test                                            # Rust tests (IR round trip, ...)
cargo run --release --example profile -- circuit.json [method] [oversample] [dk|mna] [reltol] [vntol]   # speed of a step
cargo run --release --features timing --example profile -- ...   # plus where the DK step's time goes (cycle counts)
cargo run --release [--features timing] --example bench -- circuit.json input.f64 2 [out.f64]   # a run on a recorded input; METHOD, RATE, ABSTOL, NRELTOL, TABLES, PARTITION, ... (its docstring)
cargo run --release -p varimu-app [-- FILE --play --device pultec_eqp1a]   # the native app (docs/NATIVE_APP_PLAN.md; R2: the Play view)
cargo run --release -p varimu-app -- --edit triode_stage_drawn   # R3: the Editor view on a drawn circuit (config/circuits/*.drawing.json)
cargo run --release -p varimu-app -- --component OT_5E3   # C2 step 7: the Components view on a transformer component (NAME or NAME@N)
cargo run --release -p varimu-app -- --room   # the Room view: sources and mics placed in a room, rendered into session tracks (docs/ROOM_LOOP_PLAN.md)
uv run --extra fast python scripts/room_print.py config/scenes/NAME.yaml [--solo] [--quality draft]   # a scene recorded through its mics -> reports/rooms/<scene>/
uv run --extra fast --extra listen python scripts/room_demo.py [--only ROOM ...]   # R6: one performance in five rooms -> reports/rooms/demo/
uv run --extra fast --extra listen python scripts/room_separation.py [--render-only | --analyse-only] [--room poly [--wave HZ]]   # R5 (R8: on polyroom) -> reports/rooms/separation/
uv run --extra fast --extra listen python scripts/room_wave_demo.py [--only VARIANT ...] [--crossover 500]   # R7 / R10: the wave solver off / on, a dead front wall -> reports/rooms/wave_demo/
uv run --extra fast --extra listen python scripts/room_gobo_demo.py   # R11: two players without / with a gobo, live and treated -> reports/rooms/gobo_demo/
cargo test -p roomsim --release   # R9-R11: the GPU kernels against their f64 CPU references (skip without a GPU)
uv run --extra listen --with sounddevice python scripts/separation_listen.py --room   # its staircase on headphones
uv run python scripts/compose_chain.py --mic omni_4134 --pre clean_pre [--check]   # the opposite chain -> config/circuits/omni_clean.yaml
cargo run --release -p varimu-app --example render -- --circuit NAME --input FILE [--set k=v ...] [--out out.wav]
cargo run -p varimu-app --example devices             # the audio devices cpal sees
cargo run --release -p varimu-app --example play -- --device fairchild_670 (--file F | --input NAME --channel N) [--for S] [--turn KEY=A,B] [--record take.wav]   # R2: real-time stats (load, dropouts, latency, knob to ear)
cargo run --release -p varimu-app --example click -- [--device D] [--notes] [--for S] [--ab S] [--output NAME] [--loopback output | --loopback input NAME --channel N] [--save DIR]   # recording T1: the click's timing on a loopback, load with / without it
cargo run --release -p varimu-app --example load_profile -- --file F [--device D] [--set k=v] [--add-c NODE=F] [--quality draft|draft-1x|draft-2x] [--out load.csv]   # where the draft's load goes, block by block (no audio device)
cargo run --release -p circuitsim --example harp_bench -- [MODEL.harp.json] [FS] [RATE] [SECONDS]   # RH3: the harp alone, every key ringing
cargo run --release -p varimu-app --example play -- --device rhodes_stage_5e3 --strike-all [VEL] [--restrike S]   # RH3: the Rhodes live, every key struck with the pedal down
cargo run -p varimu-components -- compile config/designs/NAME.yaml [--yaml]   # C2: a transformer design -> its compiled values and report (--yaml: the version file)
cargo run -p varimu-components -- save config/designs/NAME.yaml   # C2: saves config/components/<name>/<N>.yaml + its lock line (nothing when unchanged)
cargo run --release -p varimu-components -- fem config/designs/NAME.yaml [--short p1+p2:s]   # C2: every winding pair's leakage, 1D formula vs the 2D field solution
uv run python scripts/fit_ot_5e3.py [--show]   # C2: the 5E3 OT's construction fitted to P-TGO-002 -> config/designs/ot_5e3.yaml (needs the release build of varimu-components)
uv run python scripts/compile_rhodes_harp.py [--check]   # RH3: the harp compiled -> the next MK1_HARP version (none when unchanged; --check: exit 1 when one is due)
uv run --extra fast python scripts/rhodes_render.py (--midi F | --demo) [--quality draft] [--reference]   # RH2-RH3: MIDI through the harp medium into the 5E3 -> reports/rhodes/renders/
cargo clippy --all-targets -- -D warnings
cargo clippy --all-targets --all-features -- -D warnings   # also the PyO3 bindings
cargo fmt --check
uv sync --extra fast             # build circuitsim (maturin, abi3) into .venv: `import circuitsim`
```

- **Rebuilds:** `uv sync --extra fast` and `uv run --extra fast ...` rebuild
  circuitsim whenever a crate source changes (`cache-keys` in
  `crates/circuitsim/pyproject.toml`: its `pyproject.toml`, `Cargo.toml`,
  `build.rs`, the workspace `Cargo.toml`, `src/**/*.rs`) and are no-ops
  otherwise. **Plain `uv run` does not rebuild:** it keeps the installed
  circuitsim, stale after a Rust edit. So after editing Rust, use
  `uv run --extra fast pytest` (or sync first). Add a cache key if the build
  starts depending on another file. (All verified 2026-10-14.) A stale build
  can't slip through: `build.rs` embeds a hash of the crate sources
  (`circuitsim.SOURCE_HASH`) and `varimu.sim.fast` raises `StaleBuild` when it
  doesn't match the working tree (`tests/test_fast.py` too).
- **`uv sync` is exact:** it uninstalls every extra you don't name (plain
  `uv run` leaves them installed). Name all of them each time, e.g.
  `uv sync --extra listen --extra fast`.
- **Windows file locks:** stop `varimu listen` (and any Python that imported
  circuitsim) before syncing. A sync that hits a locked `.pyd`/`.exe` aborts
  halfway and can leave a package half-removed; rerun the sync once the
  process is gone.
- The circuitsim tests in `tests/test_circuit_ir.py` skip when the extra isn't
  installed. Cargo builds use every core; `CARGO_BUILD_JOBS=6` keeps the
  desktop responsive.
- `tests/fixtures/netlist_golden/` holds byte-exact SPICE netlists,
  `crates/circuitsim/tests/fixtures/` the IR JSON, and its `devices/` the
  Python device models evaluated on grids (`varimu.devices.fixtures`). All
  are regenerated by `export_circuit_fixtures.py` (pytest fails when the IR
  or device fixtures are stale, e.g. after a device refit); re-capture the
  goldens only when the circuit is meant to change, and review the diff.
  `.gitattributes` keeps them LF.

Renders are cached in `cache/renders/<hash>/` (key: netlist, tables, input,
settings, and the source of `varimu/{sim,circuit,devices}` + `config.py`).
`cache/renders/timing.csv` logs wall-clock per second of audio for every render.
`--set` keys are the `controls`, `values` and `device_params` of
`config/circuits/fairchild_670.yaml` (the latter are
`v6386_{a,b}.{emission_scale,mu_spread,grid_contact_v}`).

The dev machine runs Windows. Use `pathlib` for paths and never hardcode separators.

**Simulator:** ngspice 47 is installed portably under `tools/ngspice-47/` (git-ignored).
`varimu.sim.ngspice.find_ngspice()` looks at `$VARIMU_NGSPICE`, then `tools/`,
then `PATH`. To reinstall, download `ngspice-47_64.7z` from SourceForge
(ng-spice-rework/47) and extract it into `tools/ngspice-47/`. SPICE agreement
tests skip when ngspice is missing.

## Hard rules

- **Never present invented values as data.** Prefer a schematic, datasheet or
  cited paper. The user has OK'd using web sources and model knowledge to keep
  moving, but every value carries a `source`: a datasheet reference,
  `web: <url>`, or `provisional: model knowledge (...)`. Provisional values
  should become bounded genome parameters or be replaced later. `varimu.config`
  enforces that every genome parameter has a `source`, and device files carry
  one per block.
- **The genome is physical only.** No EQ curves, saturation knobs or anything
  a real unit couldn't have.
- **One coupled simulation.** The audio path, sidechain and PSU go in one
  netlist, never in separately chained DSP blocks.
- **Every device model has two implementations**, SPICE and a Python
  reference, with a test that they agree. **Exception (decided by the user
  2026-10-21): the hysteretic transformer core** has the Python reference
  and circuitsim only, with tests that they agree; ngspice cross-checks the
  rest of the circuit with the core in its linear limit in both engines
  (measurements behind it: the circuit-sim plan's Open decisions).
- **Reproducibility.** Every result must be reproducible from (genome, signal,
  settings, code version). All randomness goes through a seeded
  `np.random.Generator`. Derive per-item seeds, e.g.
  `default_rng([seed, crc32(name)])`, so adding an item doesn't perturb the others.
- **Loudness lies.** Every listening comparison is matched for both gain
  reduction and LUFS.

## Conventions

- Units are SI in code. Put the unit in the name whenever it isn't obvious:
  `_s`, `_hz`, `_ohm`, `_dbfs`, `_v`.
- Audio levels are **peak dBFS**: 0 dBFS is a sine of amplitude 1.0. Convert to
  circuit volts with `audio.full_scale_volts_peak` from `sim_settings.yaml`,
  in the sim layer only.
- Read the sample rate from `sim_settings.yaml` (96 kHz). Don't hardcode it
  outside tests.
- Audio files are mono float32 WAV. Generated audio is not committed, because
  it can be regenerated from the seed, and `manifest.json` records hashes.
- `data/clips/` holds only recordings the user owns or has rights to.
  Never commit it.
- Digitized datasheet CSVs need a provenance sidecar (see `data/datasheets/README.md`).
- Prefer small, inspectable steps. Save measurement plots for candidates so
  changes in character can be reviewed visually.
- `assets/` and `ui-mockup/` hold plugin UI art for Phase 10. They are not part
  of the Python package.

## Known issues / gotchas

- **ngspice behavioral sources in sweeps.** In a `.dc` sweep, ngspice reports a
  B-source's value linearized from the previous point and accepts it after
  one iteration, even with tight RELTOL. The error scales with step^2 and was
  about 0.1% at 2 V steps. A fresh `.op` is exact, so the agreement tests use
  one `.op` with many instances. The same effect may hurt transient accuracy
  at default tolerances: measure it in Phase 4 before trusting renders.
- The SPICE `D` model uses a cubic approximation in deep reverse bias, so it
  differs from pure Shockley by about 1e-11 A.
- **ngspice render speed (measured 2026-10-13; circuitsim is the default
  since M6, see below).** About **25-40x slower than
  real time** per render (one core each): 25.5 s staircase 28x, 7 s bursts
  28x, 1 s program clip 25-31x, plus ~2-5 s fixed start-up. Parallel renders
  scale with cores. What made it feasible:
  - triode plate currents are XSPICE `table2D` tables of the Python models
    (`varimu/devices/table.py`), ~20x cheaper than the 32-section B-source,
    whose symbolic derivatives blow up (1.3 ms per timepoint). Bilinear error
    is <=1e-4 of max current; `devices.triode_formulation: exact` restores
    the B-sources for verification;
  - the circuit had a parasitic ~30 kHz oscillation (tuned-plate tuned-grid
    through lossless transformer leakage) that forced 80 ns steps. Winding
    self-capacitance and lumped core loss (provisional values) fixed it, and
    `tests/test_slice.py` guards idle stability.
- **Transient accuracy (measured 2026-10-13).** The DC-sweep under-convergence
  above does not show up in transient: at reltol 1e-3 renders are within
  -59 to -67 dB (re signal) of a tight reference. Chosen: trap, reltol 1e-3,
  2x oversampling (`config/sim_settings.yaml` has the numbers). reltol 1e-5
  fails to start at the bridge diodes. KLU (`.options klu`) also fails there.
- **ngspice 47 I/O gotchas** (details in `varimu/sim/io.py`):
  - XSPICE `filesource` load time is quadratic in file length (4.9 M lines:
    140 s), so inputs are split into series-connected chunks;
  - `.options interp` freezes output values when the solver steps below TSTEP;
    interpolate in Python instead;
  - batch mode ignores `.options filetype`; a `.spiceinit` in the job dir sets
    binary output (and `num_threads`);
  - an inline PWL source breakpoints every sample (5x the timepoints);
  - a filesource reads 0 past its last entry (it doesn't hold), and the
    final timepoint can land a rounding error past it, so the last chunk ends
    with an extra hold point (fixed 2026-10-14; before that, the last
    oversampled sample of every render saw input 0);
  - for agreement tests, `run_transient(..., max_step_div=8,
    grid_breakpoints=True)` makes ngspice a reference: plain runs straddle
    the input's sample kinks and interpolate, about -55 to -75 dB re signal;
  - ngspice can stop at its first step (t = h / 100, at a bridge diode on
    T104's floating secondary) depending only on how the input is split into
    filesources (found 2026-10-23: 4 and 4.5 s renders at the default panel;
    no method, rshunt, gmin or capacitance helped). Again 2026-10-24 after
    mumetall's refit (stiffer T101 / T103 couplings): two compression-curve
    chunks stopped 9 and 59 ms into the settling in four filesources and ran in
    three or five. `run_transient` retries any stopped run once with one
    filesource more (a second stop raises).
- **Fixed-step engine accuracy (decided 2026-10-15, plan M4).** Trapezoidal
  frequency-warps the transformers' resonances (the slice peaks +10 dB near
  17 kHz from the pre-Phase 2 provisional winding capacitances; Phase 2's
  transformers moved it to 35.5 kHz, +1.4 dB, and the rerun method comparison
  kept the choice): 0.8 dB / 8 deg off at 20 kHz
  at 2x. Production uses esdirk4 at 2x instead, with 5th-order input
  interpolation (linear input between samples, ngspice's PWL, droops 20 kHz
  by 0.3 dB at 2x and caps any higher-order method) and local error control
  for the non-smooth events (bridge diodes switching on HF, the TC1 attack),
  where only smaller steps help. Measure against the engine's converged
  solution (e.g. radau5 at 8x, input_order 5), not ngspice: ngspice with
  tabulated triodes is ~-62 dB rms from it; with the exact formulation it
  agrees to -92 dB but runs ~7000x slower than real time. The M2/M3
  agreement tests (`tests/engine_compare.py`) still run trapezoidal, the
  engine's 2nd-order baseline.
- **circuitsim speed (measured 2026-10-17, M5).** Production (DK) runs
  3.3x slower than real time on the 7 s TC1 burst and 4.2x on the arpeggio
  clip, against ngspice's 20.6x / 21.2x and M4's full MNA 15.8x / 18.5x in
  the same session (one job at a time). HF test tones are slower (CCIF
  -10 dBFS 77x) where error control subdivides steps. Per sample: ~9 Newton
  iterations over 5 stages, ~1.4 factorizations of the 22 x 22 port matrix.
  M6 (2026-10-21): 3.7x / 4.5x vs ngspice's 26x on the TC1 burst and the
  arpeggio clip at the report's hot front panel. Parallel circuitsim renders
  scale to ~8.5x one job's throughput at 14 jobs (the default) on this
  8-core desktop.
- **Tabulated-triode ngspice can't referee hot program material much below
  -55 dB (measured 2026-10-21, M6).** Its tables are -53 dB from the exact
  formulation where the CV swings to -84 V (the arpeggio clip at pad 0 dB,
  threshold 0.8). So waveform references use the exact formulation
  (`TransientSettings.triode_formulation="exact"`, ~800x slower than real
  time) on short excerpts; even then, on the HF-rich clip excerpt ngspice's
  own error (-61 dB, gear 4x) sets the margin, and the converged-solution
  row is the sensitive one for circuitsim regressions.
- **The compression curve renders in chunks** (`slice_report.py`: 6 steps
  plus 1 warm-up step each, in parallel), equal to the continuous staircase
  to 3e-6 dB on the current circuit. `--verify` checks that; if a circuit
  change (e.g. slow PSU or core dynamics) breaks it, lengthen the warm-up.
- **Transformer cores and ngspice (2026-10-21).** ngspice has no
  Jiles-Atherton core: it runs the cores' linear limit, emitted as coupled
  inductors with the leakage folded into the inductance matrix, eddy loss as
  a shorted turn, and `.options rshunt=1e12` (without it ngspice at reltol
  <= 1e-4 stopped within ~60 ns at the bridge on T104's floating secondary).
  Three other emissions stopped ngspice on the 670 (`varimu/circuit/spice.py`
  docstring). The SPICE text has no core nodes and no inner nodes of
  windings (`spice.spice_nodes`); `.op` comparisons pass `rshunt_ohm=None`.
  The device-stripped 670 no longer runs in ngspice's transient (its T104
  secondary floats), so "the transformers alone" are tested standalone
  (`varimu/measure/transformers.py` fixtures).
- **Core quirks (2026-10-21).** A run starts at the DC operating point with
  its first input sample: DC on T101's primary saturates its mumetall core,
  and a DC point past saturation can fail; fade excerpts in. The linear limit
  is the susceptibility at the demagnetized origin (mumetall since its
  refit: 29,300, within ~20% of its permeability at program levels, so JA and
  linear builds compress the slice's clip within 0.022 dB per 50 ms; the old
  fit's 246 made that ~2 dB).
  The core's map is piecewise smooth (substep and direction changes), so
  Jacobian tests compare it only within 10 uT of its state.
- **Mumetall at low fields (refit 2026-10-24).** The fit now has a Rayleigh
  region (`rayleigh_r_per_a_m`, `h_rayleigh_a_per_m` in its datasheet block;
  c 0.289): origin permeability 29,300, hysteresis distortion that falls with
  level (nominal unit, 1 kHz, -10 dBm: 0.012% THD, was 0.16%). The previous
  fit (c 0.00077, origin 246, H ~ sqrt(B) at program levels) caused Phase 4's
  low-level THD and a level-dependent bass response. T101's and T103's turns
  stay as derived (for 10 H / 5 H at an origin of 5,850); their linear limits
  are 17.7 H / 7.9 H, mostly the joint gap. Keep the Rayleigh targets when
  refitting: the four datasheet scalars alone gave the old fit.
- **Attack is current-limited (2026-10-23).** The 6973 pair (its zero-bias
  current at the ~150 V screen tap) sets the CV's slope into C109; the
  bridge diodes and T104's leakage don't matter. A long burst's CV keeps
  creeping at constant gain (it tracks the supply's sag), so measure attack
  against the CV a few tens of ms in (`metrics.cv_attack`), not the burst's
  end.
- **Listening renders are excerpts (Phase 5).** A GR-matched stimulus takes
  ~8-12 renders of its excerpt (the pool's `excerpt_s`, 8 s: the clip's
  loudest window); `ab-prepare` on 3 candidates x 2 clips x 2 targets is
  ~100 renders. Judgments go to data/judgments/judgments.sqlite (never
  committed); stimuli are stored per code and config version
  (`prepare.code_version`: a material refit counts), so a circuit change
  means preparing again. The listening aids (difference listening, ABX:
  `varimu.listen.difference`, `abx`) render nothing: they work on the
  matched renders in the cache. ABX judgments live in their own tables
  (`abx_*`, every trial that isn't the real pair flagged `exaggerated`) and
  are never preference data. A pair's difference splits into tone (what a
  fixed filter explains) and character (`difference.decompose`); a big
  gain-only residual can be just a bass shelf (T101 permalloy). The pool
  plays `pool_clips` (config/listening.yaml), built from the user's
  multitracks by `scripts/build_clips.py` (Cambridge-MT: educational use
  only; never commit them); the arpeggio stays in data/clips for `--verify`.
  Editing listening.yaml doesn't invalidate stimuli (it is outside
  `prepare.code_version`).
- **One render job twice at once (fixed 2026-10-24).** Two threads rendering
  the identical job (same cache key) used to share `cache/renders/<key>.tmp`
  and `cache/jobs/<key>` (WinError 32). Each render now has its own (key, pid,
  thread) names, and the second to finish keeps the first's cache entry
  (`tests/test_fast.py`). `listen.prepare` still runs a candidate's targets in
  turn: that shares the grid's renders through the cache instead of rendering
  them twice.
- **The power supply and the start of a run (Phase 3, 2026-10-21).** A run
  starts at the DC operating point with the mains sine sources at their t = 0
  value (phase 90: the peak), so the reservoirs start charged to the peak;
  renders first run `start.settle_s` = 1 s with the input held at its first
  sample (both engines, trimmed from the outputs). `--verify`'s exact-ngspice
  excerpts skip it in both engines (`EXCERPT_SETTLE_S`), and the standalone
  transformer measurements have no supply to settle. ngspice stopped ~1 ms in,
  where the GZ34 first cuts off and its leakage inductance kicks into a node
  with nothing on it, until T302's winding capacitance and the selenium cells'
  capacitance went in: keep a capacitance on every rectifier node.
  `varimu.preflight` checks this for diode nodes an inductor or winding feeds (a node
  fed through resistance, like the EQP-1A's 6X4 cathode, is fine). The 670's T104
  bridge nodes ay / bk failed it until T104's secondary got a self-capacitance
  (`t104_c_sec_f`, 100 pF, provisional, genome-bounded 30-300 pF; 2026-10-26, the
  user's choice): renders moved by -106 dB (TC1 burst) / -80 dB (clip) rms, gain
  reduction by <= 0.003 dB. Every hand-written circuit now passes the checks.
- **Speed since Phase 3 (measured 2026-10-21).** circuitsim 14x slower than
  real time on the 7 s TC1 burst and 36x on the 4 s clip (Phase 2: 5.8x /
  7.3x), plus 1 s of settling per render: 45 device ports instead of 22, and
  error-control substeps at every 6973 grid clamp (pentodes have grid current
  since Phase 3; without it the 6973 grids ran to +251 V). Cold `--verify`:
  see the circuit-sim plan's "Phase 3 in circuitsim". 2026-10-23 (the
  circuit-sim plan's "Speed after Phase 3"): step selection, probe-only steps
  with the ports-and-states error norm, and AVX2 linear algebra, 1.16-1.26x
  faster at the same accuracy; the substeps are needed by accuracy (the 6973
  feedback nodes nfa / nfb), not wasted by halving. 2026-10-24, mumetall's
  refit: no change (11.8x / 24.0x against the old fit's 11.9x / 24.3x, back to
  back, one job, the 1 s of settling counted in).
- **Genomes that oscillate** (`reports/corners/summary.json`, flagged): some
  random corners oscillate at 19-30 kHz or wander at LF (weak-supply corners:
  the regulator in dropout). `varimu.measure.plausibility` rejects every one
  (`scripts/plausibility_check.py`). Its oscillation check looks for spurs away
  from the tone's harmonics: at the hottest panel the CV is still settling
  within a short step, and that modulation isn't an oscillation.
- **Benchmarking on this desktop.** Timings drift +-35% between runs:
  VS Code's rust-analyzer recompiles the crate on all cores for ~2 minutes
  after each Rust edit, and explorer.exe often holds a core. Wait until no
  `rustc` runs, report the best of several runs, and compare engines back to
  back rather than against old numbers.
- **Floating windings cost Newton iterations (2026-10-28).** A node held only by diode
  leakage (the bridge on T104's floating secondary) makes Newton wander its common mode
  each time the diodes switch (jumps of 10-700 V, then one nVt per iteration back, a
  refactorization nearly every time): HF-rich input ran the draft 670 at 3-4x real time.
  A capacitance from the winding to ground (`CT104A/B`, the secondary to its core; the
  user's choice) holds it within a step. Check a new circuit's floating windings the same
  way (`examples/load_profile.rs`, its `--add-c`), and see `DkNewton::refactors` /
  `device_limits` for where the iterations go (NATIVE_APP_PLAN.md, R2).
- **The draft quality (M8, 2026-10-27).** A partitioned run (`partition.rs`) only
  holds across stiff, capacitor-held nodes like the supply rails: splitting through
  the signal path made DC singular (a source in a loop with T104's windings; a 6973
  grid without a DC path) or diverged within 30 samples (the 12BH7 in the second
  part). The partition names sections by title (`circuitsim_draft.partition`; titles a
  circuit doesn't have are skipped, so the EQP-1A only moves its power supply). Its
  second thread spins between samples (a core busy for the run). Most of the 670's
  refactors are the sidechain bridge switching against a stale Jacobian; low-rank
  (Woodbury) refactors of just those devices made it slower (plan, M8). `Transient::update`
  takes partitioned runs and unknowns renumbered by a rewiring (a tapped pot's wiper
  crossing its tap); changes of structure (the pad's 0 dB end, TC 5-6) restart a live
  stream instead. Draft and production renders cache apart. The Play page needs the
  `websockets` package (listen extra); a stuck page usually means the server stopped.
- **Floating nodes and Newton tolerance (measured 2026-10-14).** At DC the 670's
  T104 secondary is a 1 mOhm winding held only by bridge-diode leakage and a
  1 GOhm leak; double precision resolves it to ~1e-6..1e-5 V in any engine.
  So circuitsim's vntol is 1e-6 V (SPICE's), and ngspice can't find the
  670's `.op` at reltol 1e-9. Compare such nodes against the engine's own
  roundoff spread (reorder the unknowns), as `test_circuitsim_nonlinear.py` does.
  In transient the floor is ~1e-4 V with the bridge off and ~1e-2 V with it
  reversed for good, in either solver, and reordering doesn't reveal it (both
  orders share it): compare that island relative to its common mode
  (`crates/circuitsim/tests/dk.rs`). DK also needs a 10 uS shunt per diode
  port moved into the step matrix (`Device::shunt`), or its precomputed
  responses lose 4 digits there.
- **`ngspice.run(options=...)` was silently ignored until 2026-10-14** (fixed):
  `.op` agreement tests written before then ran at ngspice's default
  tolerances. Pass `digits=16` for full-precision output (the default prints
  ~10 significant digits, ~5e-7 V at B+).
- **Edits that invalidate the render cache (B1, 2026-10-25).** Any edit to
  `varimu/{sim,circuit,devices}` or `config.py` changes every render's cache key,
  so the next full `pytest` re-renders. Don't edit those directories while the
  suite runs (the key moves again mid-run).
- **Renders and the desktop.** ngspice runs at below-normal priority with one
  thread, and parallel renders default to cpu_count - 2 (`runner:` in
  `sim_settings.yaml`). Don't kill ngspice by walking up process trees: two
  renders launched from one shell share ancestors.
- **Float sums in the builders (2026-10-29).** Python 3.12's `sum()` of floats is
  compensated (Neumaier), Rust's fold isn't: builder code that both languages run sums in
  a plain loop (`parts.speaker_driver`), or tests/agreement.rs finds 1e-16 differences.
- **DK's cost grows with the square of the states (2026-10-29).** Linear elements aren't
  free in real time: the 5E3's speaker readout (a 29-section delay line and 8 modes, ~80
  states) took Play's draft-2x from 0.48x to 1.61x real time with the same Newton work
  (COMPONENT_EDITOR_PLAN.md, C3's status). Measure `examples/load_profile.rs` before and
  after adding networks to a played circuit.
- **roomsim builds like circuitsim (2026-11-05).** `uv run --extra fast ...` rebuilds it after a
  change to `crates/roomsim/src/**/*.rs` or `*.wgsl` (its `cache-keys`); plain `uv run` keeps the
  installed build and `varimu.rooms.gpu` raises StaleBuild. The GPU's ray sums are exact (fixed
  point); its spectra and fields are f32 (agreement with the f64 references in its tests). A
  sealed room keeps a pressure offset after an impulse (the wave solver's zero-frequency mode):
  compare its fields on first differences, renders high-pass it at 15 Hz.
- **Rust-only engine changes don't move the caches (found 2026-11-02).** The render cache
  key and the tape alignment's (`runner.code_version`) hash varimu's Python, not
  `circuitsim.SOURCE_HASH`: after a circuitsim edit, delete the affected entries in
  `cache/renders/` (by their meta.json) and run `align_351.py --refresh`, or results come
  from the old engine. Whether to key on SOURCE_HASH is the user's open call (TAPE_PLAN.md
  "Speed").
- **Patching files from Bash heredocs:** this shell collapses a doubled
  backslash to a single one inside heredocs, so an escaped `\n` meant for a
  Python string arrives as a real newline. Write patch scripts with the Write
  tool, not heredocs.
