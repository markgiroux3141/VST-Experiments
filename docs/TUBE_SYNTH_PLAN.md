# Tube synth: an invented instrument from older parts

Drafted 2026-10-29 with the user, after asking how far synthesizer emulation is from the
project (an ARP Odyssey 2800, which the user owns) and whether we could instead invent a
synth from parts older than solid state. **Nothing here is built.** It is its own track
next to [DEVICE_BUILDER_PLAN.md](DEVICE_BUILDER_PLAN.md) and
[COMPONENT_EDITOR_PLAN.md](COMPONENT_EDITOR_PLAN.md); where it sits in their order is
open (below). Work milestones in order, each ending with its "done when" met and covered
by tests, like the other plans.

## Decisions (2026-10-29, the user's)

1. **An invented instrument, not a clone.** A synthesizer built from older parts in
   place of solid-state ones: tubes, transformers and saturable reactors, passives, and
   period rectifiers (vacuum, selenium, copper oxide). No transistors, op-amps or ICs.
2. **Drift is character.** No tuning compensation (no master oscillator divided down,
   no thermal tracking, no auto-tune) until we have heard what the drift sounds like.
   Drift comes from modelled physics, never from an added wobble. The checkpoint is
   S4's done-when; if it turns out unplayable, the fixes come to the user as options.
3. **Two qualities, as today.** Draft for playing live; a **production render** that is
   slow but right, from the same notes. A take played live is recorded as events
   (MIDI), and the production render re-renders those events offline at production
   settings (Jiles-Atherton cores, enough oversampling for the oscillators, error
   control), the way a file is rendered now. The native app's production render equals
   Python's bit for bit, as for the 670 (`scripts/app_render_agreement.py`).

## Why

- **It plays to our strongest models.** Tubes, vacuum diodes, transformers on
  Jiles-Atherton cores and one coupled supply are what the project simulates best. The
  Odyssey would need BJTs, op-amps and comparators first (DEVICE_CANDIDATES.md, tiers
  2-3); this needs almost no new device models to start.
- **Oscillators make small physics audible.** Phase 5 found realistic differences
  between compressor units too subtle to hear. Pitch is different: a few cents between
  two oscillators beat audibly, and B+ sag, heater temperature and flicker noise all
  move pitch. The physics the device builder plans anyway (B5 noise, B6 heater to
  emission, FUTURE_DIRECTIONS.md section 3 warm-up) would be heard here first.
- **It is the project's goal in its purest form** (memory: "analog magic, not a
  clone": design devices from parts and hear their physics). There is no reference
  unit to match, so validation is by parts (each model against its datasheet) and by
  buildability (every part within its ratings).
- **There is history to learn from.** The Hammond Novachord (tube polyphony with
  frequency dividers), the Trautonium (gas-tube relaxation oscillators), the
  Clavioline, and today Metasonix's tube modules (Sources).

## The instrument, block by block (the starting sketch)

| Block | Older-part design | Models we have | New |
|---|---|---|---|
| VCF | LC low-pass whose inductor is a **saturable reactor**: a DC control winding biases the core, incremental inductance falls, cutoff rises. Two cores with control windings in anti-series so the audio cancels in the control circuit (the magnetic-amplifier arrangement). Resonance from triode feedback. | Triode, JA cores, multi-winding `transformer` macro | Validation of JA incremental permeability under DC bias (S1) |
| VCA | Variable-mu tube (the 6386, or a remote-cutoff pentode such as the 6BA6) | 6386 (pentode fit form exists) | A 6BA6 device file if chosen |
| Envelope | RC charge and discharge switched by triodes from the gate | Triode, diodes | -- |
| VCO | Open (S4): triode multivibrator with a vacuum-diode exponential converter; a reactor-tuned LC oscillator; or a thyratron / neon relaxation oscillator | Triode | Vacuum diode's retarding-field region; a gas-tube model for the third |
| LFO | Triode phase-shift oscillator | Triode | -- |
| Noise | Amplified shot noise of a tube (B5), later a noise diode or gas tube | -- | B5 |
| Ring mod | Diode ring between transformers | Diodes, transformers | -- |
| Supply | One supply for everything: sag couples the voice (pitch dips under load) | The 670's and EQP-1A's supply parts | -- |
| Keyboard | The player's pitch CV and gate as sources driven by note events | -- | Event-driven inputs (S3) |

## What exists

- **Devices:** triodes (Koren sections, tabulated in the draft), pentodes, the vacuum
  diode (Child law with a softplus knee, `varimu/devices/diode.py`: no retarding-field
  region yet), junction diodes, selenium, Jiles-Atherton cores with mumetall fitted to
  its datasheet including a Rayleigh region (`config/magnetics.yaml`).
- **Transformers with any windings:** the `transformer` macro takes a mapping of
  windings on one core (`varimu/circuit/builder.py`), so a two-core reactor is two of
  them wired together.
- **Two qualities:** production (esdirk4 at 2x, error control, JA cores) and draft-1x
  for playing (**linear cores**: the core's susceptibility at the origin, fixed). A
  saturable reactor does nothing on linear cores, so the draft needs JA cores for this
  instrument (S2 measures what that costs).
- **The native app:** Play (files, live input) and Editor views, edits heard live, a
  production render equal to Python's. Its circuits have one audio input; there is no
  control or event input. Switches are structure (a change restarts the stream), so
  keys cannot be switches.
- **Not yet:** noise sources (B5), heater temperature to emission (B6), thermal state
  and warm-up (FUTURE_DIRECTIONS.md section 3), ratings in the pre-flight checks (C6).

## Ground rules

CLAUDE.md's hard rules hold: every value has a `source`; the genome is physical only;
one coupled simulation (oscillators, filter, envelopes and supply in one netlist); two
implementations per device model with an agreement test (the hysteretic core's
exception: Python reference and circuitsim, no SPICE); seeded and reproducible.
Additionally:

- **Buildable.** Every part is one that existed, used within its datasheet ratings at
  the DC operating point (plate and screen dissipation, heater-cathode voltage, peak
  inverse voltage, core flux density). Until C6 puts ratings in the pre-flight checks,
  a script checks them per circuit.
- **Model changes are new versions.** Extending a device form (the vacuum diode's
  retarding-field region) or refitting a material comes to the user as options with
  numbers first (memory: "options before model changes"); with pinning it lands as a
  new version or a new material name, so the 670 and the EQP-1A don't move.
- **Native app only.** Nothing is added to the web app.

## Milestones

**S1. The saturable reactor.** A two-core reactor as circuit parts (two `transformer`
instances: signal windings in series, control windings in anti-series), on a material
with published incremental-permeability-versus-DC-bias curves (mumetall or a 50% nickel
alloy; the curve from a manufacturer's catalogue, Sources). A test circuit: a DC control
current, a small AC signal, the incremental inductance read off.
*Done when:* the incremental inductance against control current follows the published
curve within a stated tolerance over the range the filter will use; the audio induced in
the control circuit is measured and is the residual the arrangement predicts (mostly the
second harmonic); the Python reference and circuitsim agree. If the JA fit can't follow
the curve, refit options (a new material entry) come to the user with numbers.

*Status 2026-10-29: the material step done, against an estimate.* No published curve of
incremental permeability against DC bias was found for mumetall or its equivalents
(searched: Vacuumschmelze / Matthey, Carpenter HyMu 80, Magnetics, Arnold, *Reference
Data for Radio Engineers* 1946; the one measurement, IEEE 1464206, is paywalled; Bozorth's
*Ferromagnetism* isn't free). **The user's call:** estimate from physics where real values
are missing, mark it provisional, and leave measured data for later (no bench measurement
now; a toroid with a control winding through the audio interface, or the IEEE paper,
whenever wanted). So the reference is Gans' law of reversible permeability
(`provisional: model knowledge`), normalized to the JA value at zero bias.
`scripts/reactor_material_study.py` (standalone on `varimu.devices.core`, no circuit or
engine) -> `reports/tube_synth/incremental_permeability_mumetall.{json,png}`:
- The JA mumetall follows Gans' law within x0.59-1.95 over 0-100 A/m of bias (0.5 and
  5 mT pp ripple); at 300 A/m (M / Ms 0.99) it sits ~2x above, outside the range used.
- The bias point is the datasheet fit's (mu_max 250,000 lands at ~1 A/m, 313 mT).
- Over 0-100 A/m an ungapped core's incremental inductance falls 313x (0.5 mT) / 199x
  (5 mT): a cutoff sweep of 4.1 / 3.8 octaves. A gap trades sweep for stability: gap /
  path 1e-4 gives 3.2 / 2.8 octaves, 1e-3 gives 1.8 / 1.4.
- The signal moves the cutoff: at strong bias a 5 mT ripple sees up to 1.7x the
  permeability of a 0.5 mT one, so loud notes pull the cutoff down (core physics, kept).
- 100 A/m on a 0.1 m path is 10 ampere-turns: 1000 turns at 10 mA, a triode's plate
  current, so a tube can drive the control winding directly.

*Status 2026-10-29: the circuit step done; one decision open (the user's).* The reactor
is `config/circuits/saturable_reactor.yaml`: two `transformer` parts (no new part type),
signal windings in series, control windings in anti-series, control 0-150 V through
10 kOhm (~1 V per A/m). The shared code is `varimu/synth/reactor.py` (outside the render
cache key). `tests/test_reactor.py`:
- **DC point:** circuitsim's DC operating point puts each core on its initial curve at
  opposite bias (within 1e-7 T of the core-alone bisection).
- **Agreement with an exact solution** (two coupled JA cores, eddy loss included, DOP853
  with each core's reversals as events), rms dB re signal, production / converged:
  unbiased -90 / -89; biased (one core pulled back through zero) -69 / -73; both cores
  saturating in turn -55 / -71. That's below the single-core circuits' -88..-95 because
  the reactor is current-driven: through the steep middle of mumetall's loop (mu up to
  250,000) a small H error is a large B error. The converged runs plateau at -71 dB
  whatever the step (oversample 8-32), so the limit is the core device's own path
  integration, not the step. Accepted (audio-adequate; tightening the core device would
  touch every render); bounds a few dB outside.
- **Inductance:** unbiased, the signal windings' inductance is the core alone's
  permeability under the same drive (18.45 H against 18.48 H).
- **Control feedthrough:** the control circuit carries only even harmonics (odd ones
  -134 dB under the second); at 30 A/m and 30 mT pp the second is 38% of the signal's
  fundamental. S2's control driver has to take that.
- `export_app_fixtures.py` and `varimu-circuit`'s `tests/agreement.rs`: the native app
  builds the reactor's IR as Python does; `varimu check`: no problems.

**Finding: the JA core's minor loops ratchet (the open decision).** Biased on its initial
curve and driven by a signal current, a JA core's loop isn't closed: below the
anhysteretic curve, rising is irreversible and falling reversible, so B climbs toward
the anhysteretic for tens to hundreds of cycles, and the inductance swings while it does
(at 1 A/m it first rises ~5x, then falls). Settled (100 Hz, ~2 mT pp, after 100-300
cycles), the permeability is 29,900 / 5,030 / 1,600 / 363 / 49 at 0 / 3 / 10 / 30 / 100
A/m: a ~600x span, ~4.6 octaves of cutoff (the core-alone estimate said ~4). At 0.5 mT pp
the climb takes over 300 cycles. In the filter, that would make the cutoff wander for
0.3-3 s after the control moves. AC on top of DC really does pull a core toward the
anhysteretic curve (it's how anhysteretic magnetization is measured), but real
nickel-iron minor loops close within a few cycles; JA's non-closing minor loops are a
known weakness of the model. Options (for the user, before S2):
1. **Keep JA as is**, provisional: the cutoff glides after every control change, rising
   first. Possibly an artifact that would read as character.
2. **A minor-loop correction, opt-in per core** (only the reactor's cores use it, so no
   existing render changes; editing `core.py` still changes the render cache key, so
   caches re-render once): Carpenter's differential-equation approach to JA minor loops
   (IEEE Trans. Magn. 27(6), 1991) or Jiles' own generalization for minor-loop excursions
   (IEEE Trans. Magn. 28(5), 1992). Both are in the Python reference and circuitsim, with
   an agreement test. There's no measured mumetall minor-loop data to fit it to, so it
   would be provisional too.
3. **A closed-loop hysteresis model for reactors** (Preisach: loops close by
   construction): the most faithful to real minor loops, and the most work (a new
   device kind, both implementations).

**S2. The first sound: the filter and the VCA as an audio processor.** A circuit file:
audio in, a triode driver, the reactor low-pass with triode resonance feedback, a
variable-mu VCA, an output stage; cutoff, resonance and level as front-panel DC
controls. Drawn in the native editor, played live, rendered at production. A measurement
profile (`varimu/measure/profiles.py`): response against cutoff control, Q against
resonance, cutoff against control current, distortion against level, control
feedthrough (thump on a control step), self-oscillation threshold. The draft's speed with
JA cores measured on it.
*Done when:* the profile renders at production; the cutoff covers a range stated in the
design; every part passes the rating script; the app plays it live (or, if JA cores
don't run in real time, the numbers and options are in front of the user); the app's
production render equals Python's; **the user has heard it on program material and
decides whether the track continues** (the plan's first gate).

*Status 2026-10-29: playable ahead of S2 proper (the user asked to try things before
deciding S1's open question).* `config/circuits/reactor_filter.yaml` is S2's filter
without its tube stages: the S1 reactor in series into 47 nF and a load (controls
`cutoff_v` 0-150 V, `r_load_ohm` 1-47 kOhm, damping to resonance), ~110 Hz to ~4 kHz.
`tests/test_reactor_filter.py`: the control moves the cutoff, and a loud note pulls it
down (10 V peak: -8.4 dB at 110 Hz with the control at 0, against -3.1 at 2 V). The
native app plays it as the `reactor_filter` device with JA cores (`panel::Device::cores`:
a device can override its quality's cores; the draft's linear cores would make the
reactor a fixed inductor): 0.16-0.21x real time at draft-1x (Python), 5% load in the app.
S3's keyboard came early too: `varimu-app`'s `midi` module (midir) reads a keyboard, and
its keys play a **test oscillator** into the device's input, a band-limited saw or square
with one voice. That's a stand-in, not part of the instrument, until S4; there's no
envelope circuit yet. The Play view's source is "File | Live input | MIDI keyboard"; a
device's `mod_wheel` control follows the mod wheel (the user's may be broken; the knob is
on screen). `varimu-app --device reactor_filter --midi masterkey --play` opens playing;
`examples/play.rs --midi` plays without the window; `examples/midi_ports.rs` lists the
ports and echoes what a keyboard sends. The user's keyboard: "masterkey 61". Measured:
62 ms key-to-ear at a 30 ms queue on the user's interface (UA Twin USB, ~32 ms of output
latency of its own).

*Status 2026-10-29: S2's circuit built, on its own supply.* `config/circuits/tube_filter.yaml`:
- V1A, a 12AU7 gain stage (x11), then V1B, a follower driving the reactor through 4.7 uF.
- The reactor low-pass into 47 nF, damped by 4.7k.
- V5, a 12AX7 cathode-coupled pair: the filter node amplified, in phase, fed back through
  the RESONANCE pot and 22k. Gain above 1 makes it a negative resistance across the tank
  (a Q multiplier).
- V2A, a 12AU7 follower off the filter node.
- V3, a 6386 section as the VCA: the signal about 1/23 into its grid, its bias from the
  LEVEL pot (-103 V to -2 V).
- V4, a 6V6GT drawing 0.5-21 mA through the control windings (CUTOFF on its grid, current
  feedback in its cathode). That's a current source, so the reactor runs with forced
  magnetization.
- The supply: mains into a power transformer (250 V per HV half), a 6X4 full-wave
  rectifier, CRC filtering (b1 ~300 V for the 6V6GT, b3 ~245 V for the small stages, b4
  for the VCA, its own RC branch off b2). The bias winding feeds a selenium bridge:
  -105 V, -46 V through a divider, and an RC stage of its own for the VCA's bias.
  - A half-wave bias hummed at -26 dBFS through the VCA's grid; full wave: -138 dBFS at
    60 Hz, -86 at 120.
  - With the VCA on b3, the input stages' signal currents leaked through its plate
    resistor at -34 dB with it cut off.

`tests/test_tube_filter.py`:
- **CUTOFF sweeps the filter:** the 20th harmonic -52 / -30 / -24 dB re the fundamental.
- **LEVEL** -18.5 dB at half.
- **Off is VCA bleed at -50 dB.** At -103 V with ~280 V on its plate, the 6386's remote
  tail still passes ~4% of its grid signal; its plate supply carries 0.006 mV.
- **RESONANCE** lifts the cutoff region +8 dB on a quiet saw.
- **The filter self-oscillates at full resonance** at CUTOFF 0.25 (~700 Hz, -24 dBFS).

The resonance has a character from its parts:
- The 12AX7 pair runs out of headroom at playing levels, so louder input gets less lift.
- It fades toward the top of the sweep (+2 dB at 0.75, +0.7 at 1). There the tank's
  impedance falls to ~800 ohm, and the driving follower's ~400 ohm damps it more than the
  feedback cancels.
- Self-oscillation starts at ~0.8 at low cutoffs and not at all above ~0.4.

Live: 0.23-0.24x real time at draft-1x on program material (an arpeggio and a bass part,
`examples/load_profile.rs`, which now plays a device with its own cores); 25% load idle
(the rectifiers). Not yet: the VCA is single-ended, so a fast bias change will thump
(push-pull, like the 670, with S3's envelope); no ratings check (the 6V6GT at ~300 V and
21 mA is within its plate and screen ratings by hand).

**S3. Notes in: control inputs, the envelope, the score.** Named control inputs beyond
`in` (pitch CV, gate) as IR sources fed per sample, in both builders; notes from a MIDI
file for renders and from a MIDI device in the app (`midir`), timed to the sample; a take
played live is saved as its MIDI events. The envelope generator circuit on the gate,
driving S2's VCA.
*Done when:* the same events give the same output from a MIDI file render and from the
app's live path recorded and re-rendered (bit for bit at the same quality); a take
played at draft re-renders at production; the builders agree on circuits with control
inputs (`export_app_fixtures.py`, `tests/agreement.rs`); envelope shapes are measured
against the gate; key-to-ear latency is measured in the app.

*Status 2026-10-30: notes reach the circuit; the voice plays from the keyboard.*

**Control inputs, in every layer.** A circuit can have control inputs beside its audio
input: a circuit file's `cv_inputs: {name: node}`, the IR's `controls`. Each one is a node
driven to ground by its own samples, linear between samples, because a gate's step would
ring if band-limited.
- An IR without controls reads, writes and simulates exactly as before. Fixtures and
  goldens are unchanged, and IR_VERSION stays.
- circuitsim: rows after the input's, entered as the first `Mna::externals`
  (`Transient::set_controls`; a partition's couplings follow them), so DK solver only.
  `simulate_controls`, `Stream::with_controls` / `process_with` (a control without samples
  holds its last value), partitioned runs (controls stay in the first partition), Python's
  `simulate(..., controls=)` and `Stream(c0=)` / `process(input, controls=)`.
- `varimu-circuit` builds them, and both pre-flights take them as sources.
- `fast.run_transient(..., controls={name: volts})`. ngspice runs none: no SPICE text.
- The app: `Live::with_controls` / `process_with`.
- Tests: `crates/circuitsim/tests/controls.rs`, `tests/test_controls.py`, the app's
  `tests/live.rs`.

**The voice: `config/circuits/tube_voice.yaml`.**
- tube_filter.yaml's filter, Q multiplier, cutoff driver and supply.
- A 12AU7 cathodyne phase splitter, on a decoupled supply of its own. On b3's rail it
  passed the ripple to one VCA grid only: 120 Hz at -60 dBFS.
- A push-pull pair of 6386 sections into an output transformer (3000 turns CT : 600,
  steel).
- **The envelope is keyed as the Novachord keyed its notes.** The `gate` control input is
  the keyboard bus: -110 V with no key, -2 V with a key down (the file's `gate_off_v` /
  `gate_on_v`). A 6X4's two sections steer it: with a key down, the bus charges the
  envelope node through ATTACK; with the key up, the node discharges through RELEASE. The
  node is the VCA grids' common bias. A release resistor to a rail held the key-down
  level at a divider (-13 V); with steering diodes it reaches -2 V.
- The envelope's movement is common mode at the transformer, so it barely thumps.

`tests/test_tube_voice.py`:
- The envelope runs -109.9 V to -2.0 V.
- Attack 16-294 ms to 90% (rotation 0-0.7); release 42-366 ms to 10% (0-0.4).
- A full-scale saw: -74 dBFS with no key (bleed), -10 dBFS held.
- The gate's thump with silence in: ~5.5 mV. Hum with a key held: -85 dBFS.

The app plays it as the `tube_voice` device: `panel::Device::gate` names the control the
keys gate, at the file's voltages. With a gate, the test oscillator keeps sounding the
last key, so the circuit's envelope shapes the notes. 37% load idle, worst block 61%, no
dropouts.

Not yet:
- The gate changes at block boundaries (10 ms), not on the MIDI events' timestamps.
- Velocity sets only the oscillator's level.
- No envelope to the cutoff.
- A take isn't recorded as MIDI or re-rendered at production (S3's done-when).
- A draft-only 48 kHz component (the draft's Nyquist, up to 0.14 V on the splitter's
  plate; production has none) never reaches the output.

*2026-10-30, after the user played it: "the fast attack is still fairly slow".* The fault
was the coupling, not the envelope. The cathodyne fed the VCA's grids through 0.1 uF
coupling capacitors, and the envelope reached them only through 2.2M grid leaks: a 220 ms
low-pass on the bias, ~390 ms 10-90% at any attack. A coupling network can't be fast for
the bias and pass the bass at once.
- **Now:** a parallel-fed 12AU7 driver into an interstage transformer (mumetall, 1000 : 2
  x 60), whose center-tapped secondary drives the grids, the envelope into the center tap,
  as the 670's input transformer takes its control voltage.
- CENV is 0.47 uF with the pots widened (ATTACK 1k + 2.2M, RELEASE 4.7k + 4.7M), and the
  bus aims a volt past the open bias (-1 V), so the diode's creep doesn't slow the last
  volt.
- **Result:** the level rises 10-90% in **2.0 ms** at attack 0 (52 ms at 0.2); release to
  10% in 7 ms at minimum; bleed -74..-87 dBFS; thump 1.3 mV; hum -71 dBFS (re the output's
  full scale, now 2.5 V).
- Tried and dropped: aiming the bus past a clamp diode at 0 V. A vacuum diode drops ~5 V
  at the clamp's 20 mA and drove the grids positive.

**S4. The oscillator, drift as character.** First, cheap prototypes of the three
candidates (triode multivibrator with a vacuum-diode exponential converter, reactor-tuned
LC, thyratron or neon relaxation), each measured for pitch against control, range,
waveform, aliasing at draft and production, and speed; the user picks with the numbers.
The exponential converter needs the vacuum diode's retarding-field region
(I = I0 exp(V / V_T), V_T = k T_cathode / q, about 0.09 V at 1050 K), a new version of
the diode form, sourced (Spangenberg). Drift comes from physics: B+ sag on the shared
supply exists now. Mains variation is an operating condition. B5's flicker and shot
noise add jitter, and B6's heater-to-cathode temperature with the warm-up of
FUTURE_DIRECTIONS.md section 3 adds slow drift (see Open for the order).
*Done when:* the chosen VCO plays from MIDI over a stated range; pitch against key is
measured and reported, not corrected; aliasing is measured at both qualities, with the
production render's oversampling set so aliases stay below a threshold the user agrees
to; drift is measured over a held note and over a warm-up; **the user has heard it and
decides whether drift stays as character** (decision 2's checkpoint).

*Status 2026-10-30: prototypes (b) and (a) built; (b) measured, (a) not yet oscillating
cleanly, (c) not started.* The user deferred S4's design calls and set the priority: **the
sound's analog character first; drift, even very noticeable, is fine** (fixes later). Each
candidate is its own circuit file with a `pitch` control input and tube_filter.yaml's
supply. `scripts/vco_study.py` measures them (pitch against the control, glide, held-note
FM, mains sensitivity, waveforms and harmonics, inharmonic power with the ripple's FM
sidebands masked, speed) at production, draft and draft-1x -> `reports/tube_synth/vco/`;
the readings are `varimu/synth/vco.py`.

**(b) `config/circuits/vco_lc.yaml`, the reactor-tuned LC oscillator: works.**
- The reactor's signal windings (2000 turns per core) are the tank's L, parallel-fed (DC in
  them would bias the cores unequally). A 12AX7 stage (x30) off the tank drives a 12AU7
  cathode-coupled pair, which drives the tank with a square current of the tail's size.
  Without the gain stage, the core's own hysteresis loss set the amplitude: JA mumetall's
  Q is 60+ at tiny swings but 3-8 at swings near its coercivity (1-5 A/m pp), so the tank
  ran 0.03 V at the top and 100 V at the bottom. At 1000 turns, the oscillation stopped
  above ~100 Hz. A 6V6GT sets the bias through the control windings; its grid is `pitch`.
- **Range 52-1655 Hz (5.0 octaves)** over -42..0 V, the same to the hertz at every
  quality. The law is an S, not exponential (+-800 cents from the best fit): a keyboard
  needs the reactor's curve in its resistor string. At the bottom the tank's swing
  saturates the cores every half cycle (flat tops, fast flips: a saturating-core
  oscillator, and the pitch bunches at ~52 Hz).
- Outputs: the tank (near sine from ~400 Hz up: 2nd / 3rd harmonics -20 to -33 dB), and
  V1A's plate, a square (3rd -9.5 dB, 5th -14 dB).
- **Glide 0.57 s** to within 10 cents after a -30 -> -20 V step: S1's ratcheting minor
  loops, now as pitch. Production still drifts ~4 cents in the second after the settling.
- Held note: 2.0 cents rms cycle to cycle (120 Hz ripple). With the 6V6GT's screen on the
  reservoir b1 it was +-20 cents: the screen moved to b3. **Mains: 43 cents per volt.**
- Aliasing (the square's inharmonic power off the ripple sidebands, 426 Hz): production
  -67 dB, draft -49, draft-1x -38. At the top note the reading isn't clean yet (production
  still glides there; draft-1x reads -86 dB on a differently shaped wave).
- Speed: draft (96 kHz internal, the app's draft-2x) **0.56x real time**; production 3.4x;
  draft-1x 3.5x (slower than draft on this circuit: its larger step fights the edges).

**(a) `config/circuits/vco_diode.yaml`, the diode-timed multivibrator: not working yet.**
- The diode: **`6AL5@1`**, a new component in the existing vacuum-diode form, so no model
  code changed. The form's tail below 0 V is P s^1.5 exp(1.5 V / s): the initial-velocity
  law I0 exp(V / V_T) when s = 1.5 V_T. V_T = 0.1196 V is the retarding-field slope
  Phywe measured on an EC92 at its rated heater (LEP 4.1.10: 8.36 / 9.84 / 11.24 per V at
  150 / 140 / 130 mA, data/datasheets/published_points.yaml `EC92_initial_current`). The
  perveance (1.98 mA/V^1.5) is fitted to GE's 1954 curve as kurvmatch tabulates it,
  checked against RCA's 1954 sheet. On the EC92 the construction predicts the measured
  prefactor within ~10% with no contact-potential offset. The 6AL5's tail is ~150 uA
  exp(V / 0.12 V): an octave per 83 mV.
- A noiseless simulation of a symmetric multivibrator sits at its balance point: the
  regeneration grows on a sub-microsecond scale, and the implicit methods' steps damp it
  (h lambda ~100). So **capacitors can now have a start voltage**: a C part's optional
  `v0`, the IR's `Capacitor.v0_v`, held for the DC operating point only, by a Norton
  source in that solve (SPICE's IC=). Absent from the JSON when unset, so every existing
  IR and fixture is unchanged. Both builders take it, and circuitsim's DC solve holds it;
  ngspice ignores it. The first step takes the start's derivative as zero, about half a
  step late (`tests/linear.rs`).
- With CB's start voltage it runs, but not as designed. I0 is large (C V_T / I0 is ~0.4
  us), so the pitch node has to sit 0.75-1.35 V under the threshold, and each flip
  throws a grid ~100 V against diodes that conduct forward. The current design oscillates
  at ~23 kHz (the plates' RC), drives the grids to +15..25 V and the shared cathode to
  13 V, and Newton fails at the clamps at some pitches. Production runs ~80x real time on
  it: the flips are microsecond events. Next, if pursued: grid stoppers and a design
  whose flip doesn't drive the timing node, and edges slow enough for the draft's step.
  **Relaxation oscillators with fast edges are expensive here:** the draft can't resolve
  their flips and production subdivides heavily. (c), the thyratron, would share this.

**S5. A voice.** One monophonic voice: two oscillators, a mixer with noise, the
reactor filter, the VCA, envelopes, an LFO, the ring modulator if wanted, all on one
supply. Drawn, played live, takes re-rendered at production. The user's Odyssey 2800
is a behavioural reference, not a target: the same measurements on it (filter response
from its noise source, envelopes from held notes, pitch tracking from played octaves,
drift from a cold start) shown next to the voice's, like `vs_670`, never a rejection.
*Done when:* the voice plays live at a load the user finds playable (load and dropouts
measured); takes re-render at production equal in both builders; each block's profile
is reported (next to the Odyssey's figures if the user has recorded them by then: hardware
measurements are "further down the road", the user's call 2026-10-29, so they don't gate
S5); every part passes the ratings.

**Later, not planned yet:** more voices (paraphony from one supply first: sag coupling
between voices), gas-tube devices if S4 doesn't choose one, the reactor designed by
construction with C2's transformer designer, a divided-down keyboard if drift proves
unplayable (decision 2), the Odyssey itself as an emulation (it needs BJT and op-amp
models).

## Order and why

S1 first: the reactor is the most novel idea and the one model question that can sink
the filter (JA under DC bias). S2 gives the first sound with no new inputs or devices
and fits the app as it is (audio in, audio out), so the user decides early whether the
sound is worth the rest. S3 before S4: an oscillator has to be played to be judged. S4's
prototypes come before a commitment because the three candidates differ in new work (a
diode form version, or a whole gas-tube model). S5 assembles.

## Risks

| Risk | Mitigation |
|---|---|
| JA's minor loops under DC bias are a known weakness of the model | S1 checks against published incremental-permeability curves before anything is built on it; refit options as a new material |
| JA cores too slow for the draft | S2 measures it; options: JA only on the reactor cores, production-only listening for the filter, the draft partition |
| Oscillator aliasing | Production oversamples as needed (offline, slow is fine); the draft's aliasing is measured and stated; LC oscillators are nearly sinusoidal; tube edges are slowed by stray capacitance |
| Drift makes it unplayable | Decision 2's checkpoint in S4; options then (divider, compensation, a tuning control the player rides) |
| Control feedthrough (thumps) from the reactor and the variable-mu VCA | Measured in S2's profile; the anti-series arrangement and balanced stages are period practice |
| An invented circuit oscillates or won't converge | The pre-flight checks; the plausibility screen's oscillation check |
| No reference unit for the whole instrument | Parts validated against datasheets; ratings; the Odyssey as a behavioural reference |
| It pulls effort from the 5E3 and the component editor | Its own track with a gate after S2; the order is the user's (Open) |

## Open (the user's)

- **Where it goes in the order** relative to "Devices and components together"
  (DEVICE_BUILDER_PLAN.md): after B9 (the 5E3), interleaved, or ahead.
- **B5 and B6 before S4?** Drift as character needs noise and heater temperature to be
  more than B+ sag; doing B5 and B6 (and FD 3's warm-up) for the synth moves them up
  the device builder's order.
- **A source tag for design choices.** An invented circuit's values are design
  decisions, not data; the drawn triode stage files them as `provisional: model
  knowledge (...)`. A `design: <reason>` tag would say so honestly (needs the source
  check to accept it).

## Sources (starting points; verify each before it sources a value)

- H. F. Storm, *Magnetic Amplifiers* (Wiley, 1955); W. A. Geyger, *Magnetic-Amplifier
  Circuits* (McGraw-Hill, 1954): saturable reactors, the anti-series control winding,
  incremental inductance under DC bias.
- Manufacturers' nickel-iron catalogues (Magnetic Metals, Arnold Engineering,
  Vacuumschmelze): incremental permeability against DC magnetizing force.
- K. R. Spangenberg, *Vacuum Tubes* (McGraw-Hill, 1948): the retarding-field
  (initial-velocity) region of a diode, cathode temperature, contact potential.
- RCA *Receiving Tube Manual*: the 6BA6 (remote cutoff), 6BE6 (pentagrid), thyratrons.
- The Hammond Novachord's service documentation (tube dividers, envelopes, formant
  filters); the Trautonium (gas-tube relaxation oscillators); Metasonix (web: today's
  tube synth modules).
- The ARP Odyssey service manual (models 2800-2823: circuit descriptions, trim
  procedures, board test points), for S5's reference measurements:
  web: https://www.lost-manuals.com/en/manufacturer/arp-instruments-inc/odyssey-2800
