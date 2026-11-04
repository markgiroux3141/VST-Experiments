# Tube synth: ideas for a more diverse instrument

Brainstormed 2026-10-31 with the user, who liked all of them. They're listed here in
priority order. **They're being built one at a time in this order (from 2026-10-31, the
user's call); a section says when its idea is built.** The order is mine:
cheap ideas that change how the synth plays come first, then the voice's missing blocks
(several are S5's own scope), then ideas that need new device models or a lot of CPU. The
user picks what to build and when. Each one starts the usual way: a prototype with numbers,
then the user's go.

The synth meant here is `config/circuits/tube_synth.yaml`, the app's `tube_synth` device
(TUBE_SYNTH_PLAN.md, S4-S5). What it has today: the reactor-tuned LC oscillator with RANGE
and WAVE (tank to square); the reactor low-pass with the 12AX7 Q multiplier; the
diode-steered envelope; the push-pull 6386 VCA; ENV AMOUNT; noise (B5) and heated cathodes
(B6); the plate as a chain end. Its LFO doesn't oscillate yet.

## Owed: the full test suite (at the user's discretion)

Per feature only a targeted set runs (the synth's tests, the new code's, the quick shared
checks; the user's call, 2026-11-01). The full suite re-renders the 670 at production for
hours whenever `varimu/{sim,circuit,devices}` or `config.py` change, so it waits for the end
of the list or a night the user picks. **Run 2026-11-02 (overnight, nothing else running,
the tree at 8e3132c):** the full suite 647 passed, 1 failed in 61 min: `test_noise`'s
`test_the_mains_wander_rides_on_the_mains_parts` counted the synth's mains parts as 3, and
#7 / #15 had added the LFO's winding (two halves) and the bias winding (5; the assertion
that the wander rides on every one held): the count fixed, `test_noise.py` 12 passed.
`test_circuit_format`'s ngspice comparison passed. `slice_report.py --verify` PASS (GR
within 0.01 dB of ngspice, waveforms -71.8 to -83.3 dB, every row inside its bound).
**Run 2026-11-04 night (after the tape echo's 7.5 ips and BIAS, uncommitted on 2be1eff;
nothing else running): the full suite 762 passed, 2 failed in 64 min.**
`test_ampex_351.py::test_the_tape_runs_the_351s_transport` broke on the 351's tape parts
moving into the speed switch (its text edit left an indentation fragment): fixed, passes.
`test_profiles.py::test_amp_profile_measures_the_nominal_5e3`: the 5E3's aliasing at
production -25.7 dB (the test wants < -35, the qualities in order): not today's (the 5E3 has
no tape or media); most likely `OT_5E3@2`'s compiled capacitances (C2 step 6, commit
3129096, after the last full run): **open**. `slice_report.py --verify` PASS (GR within
0.010 dB of ngspice, waveforms -71.8 to -83.3 dB, every row inside its bound: as on 11-02).

**Run 2026-11-02 evening (nothing else running, the tree at 8c0e301): the full suite 674
passed in 70 min; `slice_report.py --verify` PASS (GR within 0.010 dB of ngspice, waveforms
-71.8 to -83.3 dB, every row inside its bound). Nothing owed now.** Was owed since
2026-11-02 (the tape, TAPE_PLAN.md "Gaps" 4): `varimu/devices/tape_machine.py`
and circuitsim's `tape_stream.rs` gained the literal bias's quartic peak finder
(`refine_extremum`): only tape circuits read it, but every render's cache key moved. Targeted:
`tests/test_tape_stream.py`, `test_ampex_351.py`, `test_app_fixtures.py`, clippy. Then
circuitsim's multi-rate parts lost local error control (`stream.rs`; only circuits with
`substeps` sections: the 351, `ampex_351_bias.yaml`, `tests/partition.rs`, all run). Owed:
the full `uv run --extra fast pytest` and `slice_report.py --verify` (no change, as expected:
the 670 has no tape and no multi-rate part). **Was owed since #7 (2026-11-01):**
- `uv run --extra fast pytest` (everything): #7 changed shared code (the IR's device union,
  the parts library, the device library and fixtures, the preflight checks, the SPICE
  emission, `fast.partition_sections`, the controls' `unit: switch` in both spec loaders). In the targeted run `test_circuit_format`'s
  ngspice comparison timed out (300 s) while the tuning sweep held every core: rerun it.
- #15 (2026-11-01) added the 6AL5's heater to `config/cathodes.yaml` (shared config); the
  full run above covers it.
- #14 (2026-11-01) added nothing shared (circuit file, scripts, panel.rs); the full run above
  covers it.
- `uv run --extra listen --extra fast python scripts/slice_report.py --verify` (the
  periodic agreement with ngspice, ~70 min cold): circuitsim gained a device and its
  limiting; the 670 doesn't use it, so expect no change.

## Ground rules (TUBE_SYNTH_PLAN.md's, restated where they bite)

- **Every value is sourced.** Design choices are tagged `provisional: model knowledge
  (design: ...)` like the synth's existing ones. Every part works within its ratings.
- **New device models come as options first.** A lamp, a gas tube, a pentagrid or a
  copper-oxide fit is a new model with two implementations and an agreement test. Each
  comes to the user with numbers before it's built (memory: "options before model changes").
- **Physics, not DSP.** Every idea below is a circuit in the one coupled netlist. The
  app's keyboard (velocity, aftertouch) only drives control inputs, as the gate and the
  pitch do now.
- **Measure CPU before and after.** With a key held (`examples/play.rs --hold 69`, 50 ms
  buffer, five threads) the synth runs at 67-70% load at ENV AMOUNT 0 (worst block
  85-101%) and 77-80% at 1 (103-108%). There's little headroom. DK's cost grows with the
  square of the states, and JA cores and sharp edges cost Newton iterations. Each prototype
  states its load from `examples/load_profile.rs` and, if it adds edges, its aliasing at
  draft-2x.
- **Panel controls update in place.** A new switch is built from contacts that are always
  in the circuit, as RANGE is, so turning it doesn't restart the stream.

## The list

| # | Idea | What it adds to the sound | New work | Cost (estimate) |
|---|---|---|---|---|
| 1 | Glide (**built**) | Notes slide | A rheostat | ~0 (measured) |
| 2 | KEY TRACK (**built**) | Filter brightness follows the note | A pot, a key string | ~0 (measured) |
| 3 | Velocity, aftertouch (**built**) | Expression | App feeds; a control input | ~0 (measured) |
| 4 | HEATER (**built**) | "Tired tubes": softer, more drift | The heater ratio as a panel value | ~0 |
| 5 | PULSE (peaking transformer) (**parked**: prototyped, CPU) | Bright, buzzy pulse, magnetic PWM | One small JA core | ~1.9x the oscillator thread |
| 6 | SUPPLY: RESERVOIR (**built**; the rectifier switch dropped: it only retunes) | How much the voice sags and blooms | Switch contacts; copper oxide needs a fit | Small |
| 7 | Lamp-stabilized Wien LFO | A working LFO that blooms | Lamp device model | ~+1% |
| 8 | LFO routing, delayed vibrato | Vibrato, tremolo, filter wobble | Pots, an RC | Small |
| 9 | Second oscillator, DETUNE, COUPLING | Beating, pulling, locking | A second VCO | One VCO; a thread |
| 10 | Sub-octave divider | Square sub-octaves, weight | Triode flip-flops | Edges: Newton, aliasing |
| 11 | NOISE in the mixer | Breath, wind, percussion | Amplified B5 noise | Noise on: measure |
| 12 | Filter MODE (LP / BP / HP) | Thin, vocal, nasal shapes | Switch contacts | ~0 |
| 13 | Filter DRIVE | Grit; loud notes darken | A gain stage | Small |
| 14 | Ring modulator (**built**: oscillator x LFO; a second VCO waits for #9) | Metallic, bell-like | Diode ring, transformers | A thread (a core) when on |
| 15 | ADSR (**built**; the second envelope not) / second envelope | Shaped notes, independent sweeps | A comparator and latch, switches, a -340 V rail | A thread (a core) |
| 16 | Sample-and-hold | Random stepped modulation | 6AL5 gate, a capacitor | Small |
| 17 | Units (part tolerances) | Each instrument its own | Port the tolerance draws | ~0 at run time |
| 18 | Through an amp | The 5E3 and its speaker | Chain end or insert | 5E3: 1.61x real time |
| 19 | Duophonic (two keys) | Two-note lines, as the Odyssey | Key assignment, second pitch | Needs #9 |
| 20 | Pentagrid modulator (6BE6) | Asymmetric, bleeding ring-mod | Pentagrid model | One tube |
| 21 | Formant banks | Fixed vowel / instrument colours | LC band-passes | States grow |
| 22 | Paraphony on one supply | Chords that sag together | More oscillators | One VCO per voice |
| 23 | Gas-tube sawtooth oscillator | The Trautonium's sound | Thyratron / neon model | Model work |
| 24 | Subharmonic mixtures | Mixtur-Trautonium chords | Dividers by 2-4 on #23 | Needs #23 or #10 |
| 25 | Step sequencer in tubes | Patterns clocked by the LFO | Dekatron or flip-flop ring | Many tubes |

## 1. Glide

A GLIDE rheostat (0 to ~2.2M, reverse audio taper) in series with the pitch input's
stopper. The 6V6GT's grid already holds 0.1 uF, so glide is that RC: up to ~0.2 s at full
rotation. A value change updates the stream in place. vco_lc had a fixed 0.57 s glide (its
33k tail and b3-fed screen); this makes it a control.
**Watch:** pitch already settles in 17-45 ms going up and up to 0.24 s on big drops (S1's
minor loops). Glide at 0 has to stay as fast as now, and long glides may sound uneven up
against down. Measure both directions as S5 did. The tuning tables are steady-state, so
they're unaffected.

**Built (2026-10-31).** Not the 2.2M above: RCA rates a fixed-bias 6V6GT's grid circuit at
0.1 MOhm, so GLIDE (`glide`) is an 82k audio-taper rheostat from the pitch input onto
4.7 uF, ahead of the 10k stopper (the `keyboard` section, the partition's first part):
time constants ~14 ms at 0.25, ~45 ms at 0.5, ~0.16 s at 0.75, ~0.39 s at 1. The 6V6GT's
10M grid leak would have divided the pitch against it (0.9%, ~90 cents at -20 V), so it is
now a 1 GOhm `numerical:` leak (only the partition's DC path). That moved the pitch ~-10
cents at -20 V, so both tuning tables were re-measured (panel.rs). `scripts/glide_study.py`
-> `reports/tube_synth/glide.json` (before GLIDE: `glide_baseline.json`): a step -20 ->
-15 V (172 -> 475 Hz) and back with a key held, at draft with the app's partition:

| GLIDE | halfway in cents, up / down | within 10 cents, up / down |
|---|---|---|
| 0 | 1 / 20 ms | 27 / 26 ms (before GLIDE: 26 / 29) |
| 0.25 | 2 / 23 ms | 65 / 63 ms |
| 0.5 | 23 / 42 ms | 0.21 / 0.20 s |
| 0.75 | 74 / 116 ms | 0.68 / 0.65 s |
| 1 | 0.22 / 0.33 s | > 1.6 s (still landing at the run's end) |

Down is slower to halfway than up: the glide is exponential in volts and the pitch law is
steeper in cents per volt at the bottom (as portamento without an expo converter). A big
drop (1.3 kHz -> 58 Hz) still creeps for ~1.9 s at any setting (S1's minor loops, as
before). Load with a key held (`play.rs --hold 69`, GLIDE 0.5): 68-73%, worst block
97-103% (unchanged). Test: `tests/test_tube_synth.py`, the glide test.

## 2. KEY TRACK

A KEY TRACK pot takes a fraction of the pitch input into V4's grid (the cutoff driver), so
the cutoff follows the note. V4 and the oscillator's pitch driver are both 6V6GTs driving
reactor control windings, so the same law may track the oscillator's pitch with no shaping
network. Measure it (cutoff against pitch, per range) before adding any.
**Watch:** the pitch input lives in the partition's first part and V4 on the filter's
thread. Feed V4 through a resistor onto a capacitor-held node, as RBUS / CBA do for ENV
AMOUNT.

**Built (2026-11-01), not from the pitch input.** Measured first (`scripts/keytrack_study.py`:
a multitone at the external input, the oscillator cut from the mixer, RESONANCE 0, the -10
dB point at `f`; `reports/tube_synth/keytrack/law_before.json`): CUTOFF moves V4's grid
linearly, -29.3 V (304 Hz) to 0 V (4.87 kHz); the filter's law is ~300 cents/V at the bottom
falling to ~45 at the top, the oscillator's 1.4-2x steeper per grid volt. And the pitch
input is tuned per RANGE: on AUTO it jumps ~4.5 V at the 330 Hz split, which would jump the
cutoff. So the keys get a second contact string, `key` (a control input: linear, 0.75 V a
key, 0 V at C4, ends at C1 / C7, +-27 V; the circuit file's `key_*` values, varimu-app's
`panel::KeyString` / `Feed::Key`, following the last key as the pitch does). It feeds the
KEY TRACK pot (2k) through 220 ohm onto 4.7 uF (the partition's coupling node: the string
on the first thread, the pot with the cutoff driver), and the pot's wiper is the CUTOFF
pot's ground end. The share of the wiper's volts on V4's grid grows with CUTOFF (0.4 at 0,
1 at full: RCUTL and the CUTOFF pot divide it). At C4, or KEY TRACK 0, the cutoff is as
before (a 10k pot moved C4's cutoff up to ~170 cents as KEY TRACK turned: the CUTOFF
network's 0.27 mA through its wiper; at 2k <= 24 cents).

Cutoff (Hz) at CUTOFF 0.3 (`track_1.json`, `track_0.5.json`):

| key | C1 | C2 | C3 | C4 | C5 | C6 | C7 |
|---|---|---|---|---|---|---|---|
| KEY TRACK 0 | 1278 | 1278 | 1278 | 1278 | 1278 | 1278 | 1278 |
| KEY TRACK 0.5 | | 603 | 881 | 1260 | 1686 | 2209 | 2674 |
| KEY TRACK 1 | | 215 | 609 | 1272 | 2219 | 3218 | 4019 |

(C1 is the filter's floor.) At KEY TRACK 1 that's ~1280 cents an octave C3-C4, ~965 C4-C5,
~640 C5-C6: full tracking mid-keyboard, compressing toward the top with the reactor's law;
at 0.5 an even ~50%. At high CUTOFF and high keys V4's grid goes positive of ground (up to
+24 V at CUTOFF 1, C7) but not of its cathode (1k: a follower there, ~29 mA, ~5.6 W of the
6V6GT's 12 W, b1 9 V down), and past the top the cutoff droops ~250 cents (the cores past
saturation). Load with a key held (A4, back to back): 71-73% at KEY TRACK 0 and 1. Test:
`tests/test_tube_synth.py`, the key-track test.

## 3. Velocity and aftertouch

- **Velocity:** the gate's key-down volts (`gate_on_v`) scaled per note by velocity
  (`panel::key_feeds`' `Feed::Gate`). The envelope's peak, the VCA's opening and ENV
  AMOUNT's sweep then follow how hard the key is played. The circuit is unchanged.
- **Aftertouch:** a new control input (`pressure`) into V4's grid like KEY TRACK, or into
  the pitch grid for vibrato by pressure. The `midi` module reads channel pressure.
- Both are the player's keyboard, outside the instrument, so nothing here bends "physics,
  not DSP". A velocity curve is a panel setting.

**Built (2026-11-01).**
- **Velocity** (no circuit change): `scripts/velocity_study.py` measured the output against
  the keyboard bus's key-down volts with a key held (`reports/tube_synth/velocity.json`):
  -1 V 0 dB, -10 V -7.4, -20 V -11.3, -40 V -15.3, -60 V -19.1, -80 V -27.2, -90 V -35.5
  (the 6386's remote cutoff: gentle, then the VCA closes fast). The harmonics stay ~7%
  throughout (the waveform's, not the VCA's): a soft key is quieter, not cleaner. ENV
  AMOUNT's sweep follows the envelope, so a soft key also opens the filter less. That table
  is varimu-app's `panel::Device::velocity` (`TUBE_SYNTH_VELOCITY`); a key at velocity v
  aims at -range x (127 - v) / 126 dB (`panel::velocity_volts`, `Feed::VelocityGate`), the
  range the Play view's "Velocity" slider (0-30 dB, 18 at first; `Player::set_velocity_range`),
  with a checkbox beside it that turns velocity off (every key at full level, the range kept;
  the user's ask).
  A legato key changes the bus's level under the held note: the envelope follows through
  ATTACK going up, RELEASE going down.
- **Aftertouch:** a fourth control input, `pressure` (0 V at rest, `pressure_full_v` 15 V
  pressed fully; the app's `Feed::Pressure`; `midi::Keys::pressure`: channel pressure, or the
  sounding key's poly pressure, 0 with no key held), through 220 ohm onto 4.7 uF across the
  PRESSURE pot (2k), whose wiper is the KEY TRACK pot's foot (KEY TRACK's wiper is the CUTOFF
  pot's). Fully pressed at PRESSURE 1 (`keytrack_study.py --pressure-v`,
  `reports/tube_synth/keytrack/pressure_*.json`): CUTOFF 0 301 -> 727 Hz, 0.3 1272 -> 2706 Hz,
  0.6 3054 -> 4548 Hz. Both pots at mid move C4's cutoff -30 cents (the CUTOFF network's
  current through both wipers). Pressure into the pitch (vibrato) isn't built.
- Load with a key held: the defaults 72-75% back to back with the runs before (71-73%); the
  same settings spread 69-93% run to run on this desktop, so nothing attributable. Tests:
  `tests/test_tube_synth.py` (the pressure test), panel.rs and midi.rs unit tests.

## 4. HEATER

A HEATER control: the heater voltage as a ratio of the rated, set on the panel (period
practice: a heater transformer's taps, or a series rheostat). Today the ratio follows the
mains setting (B6, `heater_ratio`). It needs the ratio as its own value that
`Transient::update` can change. The cathode temperature follows through B6's 7 s thermal
lag, so turning it is slow, like the real thing.
- **Low:** emission reaches its ceiling sooner, so peaks soften and compress. The
  space-charge shift moves operating points and the oscillator drifts.
- **High:** quicker warm-up, no change at the rated temperature.
- **Buildable:** tube heaters are rated +-10%. The panel range stays inside it, or the
  out-of-rating zone is marked on the panel (to decide with the user). Pairs with "Power on
  (cold)".

**Built (2026-11-01).** The user chose the extended range, marked: HEATER (`heater`) runs
0.6-1.1 of rated, the panel's label saying below 0.9 is out of rating. A circuit file's
`heaters` block takes a `tap: KEY` (both builders; the IR's `heater_ratio` = the mains
setting over its rating, times the tap). A turn is a value change: `Transient::update`
carries the cathodes' temperature, so the sound follows through the 7 s thermal lag. Warm,
a key held at -15 V (`scripts/heater_knob_study.py` -> `reports/tube_synth/heater_knob.json`):

| HEATER | pitch | level | THD | B+ (b3) |
|---|---|---|---|---|
| 1.1 | +18 cents | +0.1 dB | 6.55% | 207 V |
| 1.0 | 0 | 0 | 6.60% | 207 V |
| 0.9 | -21 | -0.15 | 6.66% | 206 V |
| 0.8 | -51 | -0.4 | 6.73% | 204 V |
| 0.7 | -113 | -0.9 | 6.81% | 193 V |
| 0.6 | -259 | -2.2 | 7.63% | 162 V |

Inside the rating it's a drift control. Below ~0.75 the 6X4's own cathode hits its emission
ceiling and B+ falls (45 V by 0.6), so the whole voice sags, goes flat and grittier: the
emission ceiling of the signal tubes matters less than the rectifier's. No CPU cost (the
heaters were already on). Test: `tests/test_tube_synth.py`, the starved-heater test.

The user heard mostly pitch, which the numbers agree with: the oxide cathodes' 50x emission
reserve keeps the signal tubes off their ceiling even at 0.6 (only the rectifier's charging
peaks reach it), while the pitch driver turns tenths of a volt of bias into hundreds of
cents. Kept anyway (free in CPU; the user's call). **Proposed, not scheduled: WEAR**, worn
cathodes (each tube's emission reserve shrunk from 50x toward ~2x, at full heater), which is
what "tired tubes" usually means: peaks compress, attacks soften, loud notes lose gain.
Measure first whether it compresses without only detuning (the pitch driver may pull too);
it would interact with HEATER (a worn tube is far more heater-sensitive).

## 5. PULSE: a peaking transformer

A third waveform beside WAVE's tank and square. From thyratron firing circuits: a small
ungapped mumetall core driven through a resistor from the oscillator saturates on each
half-cycle. Its secondary gives a sharp pulse at each flux reversal, a buzzy spectrum with
many harmonics. A DC bias winding (a pot) shifts when each half-cycle saturates, so the
pulses' spacing becomes PWM done with magnetics. The kick's prototypes found mumetall lossy
when driven through saturation: here that only rounds the pulses.
**New:** one more JA core. **Watch:** aliasing at draft-2x (narrow pulses), and Newton at
the reversals. Measure load and the alias level against the harmonics, as the 5E3's
quality choice was made.

**Prototyped (2026-11-01), parked (the user listened: "sounds ok", not worth ~1.9x the oscillator's thread).** `scripts/pulse_prototype.py`
(a variant of tube_synth.yaml -> `reports/tube_synth/pulse/`): a 12AU7 cathode follower off
the tank drives the core through 2.2k (the classic sine-current drive, ~+-4.5 mA); a 1:1
secondary through a PULSE pot (1M) into the WAVE wiper; a bias winding (5x the turns, 100k)
from a PULSE WIDTH pot centred on 0 V (150k from b3 to its top, its foot on -50 V; centred on
b3 / -50 V's midpoint, +60 V, it held the core saturated and nothing pulsed).
- **It pulses, and PWM works:** 2-4 V at the secondary at each flux reversal, and PULSE WIDTH
  moves the two polarities apart (at 178 Hz, widths 391 / 917 us at one end, 736 / 610 at
  the other; peaks 4.1 / -2.0 V).
- **But the pulses are wide:** ~0.5 ms with a 10 mm^2, 30 mm, 150-turn mumetall core (a
  quarter of a cycle at 480 Hz; harmonics roll off ~-12 dB by the 4th: a spiky rounded wave
  more than a buzzy pulse train). The drive (~22 A/m peak) sits in mumetall's soft knee.
- **Sharper cores don't run at draft:** 3 mm^2 / 20 mm / 250 turns and a 1 mm^2 bobbin core
  (15 mm, 300 turns) stop Newton at the core's reversal (draft: fixed step, 8 halvings) with
  or without a thread of their own. At production the 3 mm^2 core runs (16x slower than real
  time) but its pulses are still 0.3-0.4 ms: narrow pulses need a much harder drive (tens of
  mA: a power tube switching the primary) as well as a draft that converges there.
- **CPU:** the working (wide) version on the oscillator's thread: 4.25 s against the synth's
  2.24 s for 1 s of audio (+1 s settle) in Python's draft run, ~1.9x that thread. It can't
  have a thread of its own: split from the oscillator at the follower's cathode, or summed
  into the mixer on another thread, the core (or the mixer's thread) stops Newton within the
  first ms. So it shares the oscillator's thread, and Play's load is the question.
- Listening takes (draft, the user's): `reports/tube_synth/pulse/audio/` (the synth's tank
  and square without PULSE, PULSE at widths 0.2 / 0.5 / 0.8, and with the filter open).
- **Options:** park it (the findings stay here); take the wide version as a "spiky" third
  timbre on the oscillator's thread (listen first; Play's load); or make narrow pulses work: a beam-tube current
  switch on the primary plus engine work so draft converges at a JA core's hard reversal
  (step limiting in the core's Newton). The last is the biggest.

## 6. SUPPLY: rectifier and reservoir

A RECTIFIER switch (6X4, selenium; copper oxide needs a new device fit) and a reservoir
switch (contacts always in the circuit). Together they set how far b1-b3 sag under a note.
**Watch:** the pitch and the cutoff were taken off the sag on purpose (the 5651s on the
oscillator's and V4's screens), so sag now mostly moves the VCA's level, V7's sweep and
what's left of the pitch. It sounds like bloom and compression rather than pitch dips.
Measure it before promising more. Rectifier peak inverse voltage and surge ratings apply
per position.

**Measured (2026-11-01); RESERVOIR built, the rectifier switch dropped.** `scripts/supply_study.py`
-> `reports/tube_synth/supply/supply.json`: a key held 1.2 s at -15 V with a fast attack, per
rectifier (the 6X4; silicon standing in for the stiff end, a selenium stack between) and
reservoir (8 / 20 / 40 uF):

| rectifier, reservoir | bloom (first 100 ms to held) | b1 sag | b3 sag | ripple sidebands (+-120 Hz) | pitch |
|---|---|---|---|---|---|
| 6X4, 8 uF | -0.65 dB | 22 V | 41 V | -25 dB | as now |
| 6X4, 20 uF (now) | -0.65 | 21 | 40 | -33 | |
| 6X4, 40 uF | -0.64 | 21 | 40 | -39 | |
| silicon, 8 uF | Newton stops at the oscillator's 5651 (1.5 s) | | | | |
| silicon, 20 uF | -0.47 | 8 | 33 | -24 | +70 cents |
| silicon, 40 uF | -0.55 | 14 | 37 | -37 | +60 cents |

- **The bloom is the same everywhere** (~-0.6 dB, 0.2 dB apart): b3's sag is the decoupling
  resistors' drop under the VCA's current, not the rectifier's. Not a control.
- **The rectifier mostly retunes:** silicon lifts B+ ~25 V and the pitch ~60-70 cents (the
  tuning tables would need a set per rectifier), and at 8 uF a run stopped.
- **The reservoir is the one audible lever:** the ripple's sidebands go -39 / -33 / -25 dB
  (40 / 20 / 8 uF): a hum-growl on every note, more at low cutoff. Takes:
  `reports/tube_synth/supply/audio/` (each normalized to -6 dBFS peak).
- **Options:** skip #6; or only a RESERVOIR switch (the capacitors on contacts always in
  the circuit, as RANGE: a "hum" control, ~5 cents of pitch across it, no CPU).
- **How low** (6X4, `reports/tube_synth/supply/reservoir.json`): the ripple sidebands and the
  oscillator's cycle-to-cycle spread (the ripple's FM on the pitch, 2.5-97.5 percentiles),
  the held pitch re 20 uF, the 6X4's steady-state peak plate current (GE ET-T865A: 245 mA max;
  its 10 uF is the sheet's typical operation, not a limit):

  | reservoir | sidebands | pitch spread | pitch | plate peak |
  |---|---|---|---|---|
  | 1 uF | -14 dB | 215 cents | -59 cents | 131 mA |
  | 2 uF | -16 dB | 172 cents | -39 cents | 159 mA |
  | 3 uF | -18 | 137 | -26 | 180 |
  | 4 uF | -20 | 111 | -17 | 191 |
  | 6 uF | -23 | 79 | -10 | 202 |
  | 8 uF | -25 | 61 | -5 | 206 |
  | 12 uF | -28.5 | 42 | -2 | 210 |
  | 20 uF | -33 | 25 | 0 | 211 |
  | 40 uF | -39 | 13 | +1 | 212 |

  Below ~6 uF the pitch itself warbles at 120 Hz by more than half a semitone and goes flat
  (the tuning tables are 20 uF's): a broken-amp growl. Takes at 2 and 4 uF too.

**Built (2026-11-01): RESERVOIR** (`reservoir`, the user's call: "super janky and broken but
a neat effect" at the bottom): a rotary switch choosing the reservoir electrolytic, 1 / 2 / 4
/ 6 / 8 / 12 / 20 / 40 uF, 20 as before, the panel's label saying under 6 uF detunes. The
control holds farads (CB1's `c`); a step is a value change, so a live stream updates in place
(`play.rs --turn reservoir=1.0e-6,2.0e-5` with a key held: heard in ~95 ms, no restarts, no
dropouts, load unchanged). varimu-app's `Knob::unit` / `Knob::choice_text` print a choice with
unit F in uF. No CPU cost. Test: `tests/test_tube_synth.py`, the reservoir test.

## 7. The LFO: a lamp-stabilized Wien bridge

This replaces the stalled phase-shift LFO (TUBE_SYNTH_PLAN.md, S5's status: its loop gain
stayed under 29 for a reason not found). A Wien bridge needs a gain of only 3. An
incandescent lamp in its negative feedback holds the amplitude, as in Hewlett's HP200A
(1939). The lamp's thermal lag makes the amplitude bloom after a RATE change.
**New:** a lamp device model: filament resistance against temperature, heat capacity,
radiated loss, with a SPICE and a Python implementation and an agreement test. It could
also steady the VCO's amplitude later.
**Watch:** the lamp's time constant against a 0.1-20 Hz LFO. Too slow and the amplitude
hunts (period designs bounce too; how much is the sound).

**Built (2026-11-01; the user chose the full thermal lamp model over a thermistor or grid
clipping).**
- **The lamp** (`varimu/devices/lamp.py`, component `LAMP327@1`, `varimu fit-devices --only
  LAMP327`): a #327 pilot lamp (28 V, 40 mA) as a tungsten filament lumped at one
  temperature: resistivity, specific heat and conductivity from the published fits (Tolias
  2017: White-Minges, Hust-Lankford), total emissivity a cubic through Holladay's table
  (JOSA 1928), radiation from a coil's share of the wire (0.65, provisional) and conduction
  to the leads (the rod's 12 k A / L, Kirchhoff-integrated). The wire (11.4 um, 106 mm
  uncoiled) is solved from the rating at an assumed 2300 K (provisional): 56 ohm cold, 700
  hot. A device with pins (a, t, b): its temperature is the node t (1 V = 1 K above
  ambient) on a 1 F capacitor, the device's second port current dT/dt, so the model is
  stateless, DK integrates it implicitly and a DC point is the hot steady state. Python
  reference, SPICE subcircuit (`tests/test_spice_agreement.py`), circuitsim
  (`devices/lamp.rs`, bit-equal to the fixtures), both builders (`tests/test_lamp.py`: the
  rating, the Jacobian, a 20 V step against an ODE of the reference). Numerics only: a
  cold filament's thermal resistance is ~4e5 K/W, so Newton's steps are limited on both
  ports (the DC point ran away to 1e16 V without it), and past the fits' 3400 K a restoring
  slope keeps the thermal port alive. Its time constant: ~10 s cold, ~1 s at 600 K, 13 ms
  at the rating.
- **The LFO** (tube_synth.yaml's `lfo` section; its header has the circuit): DC-coupled, since
  at 0.1 Hz no coupling capacitor works and the lamp may carry no DC: a 12AX7 long-tailed
  pair, a divider, a grounded-cathode 12AU7 section, a divider, the 12AU7's other section as
  the follower; RLF, RLS and the lamp in the negative feedback; RATE a dual 2M reverse-audio
  rheostat with 1 uF. A prototype first (scratch, ideal rails): one stage's open-loop gain
  (~12) didn't start it; the pair's plates must sit level or its offset puts DC on the lamp.
- **Its own supply** (the user's choice of three options, 2026-11-01). On the synth's rails
  the LFO ran the 6X4 past its peak rating (259.8 mA at 20 uF, GE's limit 245; 211 before the
  LFO) and its follower's current at the LFO's rate reached the pitch through b1 (+-4-7
  cents). Now a center-tapped winding of its own (as the HV halves), silicon rectifiers
  (SI_RECTIFIER@1): a full-wave reservoir (~310 V) for the follower's plate (through 4.7k,
  bypassed) and, filtered, the stages' ~270 V; a half-wave minus rail held at -174 V by two
  5651s for the follower's return, the dividers and the tail. On the way: through a filter
  resistor alone the minus rail moved volts with the follower's current and the slow end ran
  at the wrong rate; from one 5651 (-87 V) the dividers passed too little for the lamp to
  warm; the follower on the stages' filtered supply fed back through it; with its plate
  resistor unbypassed it oscillated at ~1-3 kHz; on the HV winding's own ends the
  rectifiers sagged b1 4 V (the pitch 6.5 cents apart with the LFO on and off). Now the 6X4
  peaks at 211.7 mA with the LFO on or off (as before it), the pitch is the same on and off
  (497.251 Hz at -15 V) and the tuning tables measured before stand. `scripts/supply_study.py`
  now reads the 6X4's own current from its model (the winding's current also fed the LFO's
  rectifiers). `scripts/lfo_study.py` -> `reports/tube_synth/lfo.json` (a key held at -15 V,
  from the run's start):

  | RATE | rate | settled | DC | THD | to within 5% | lamp | its swing in a cycle | VIBRATO 1 |
  |---|---|---|---|---|---|---|---|---|
  | 0.25 | 0.354 Hz | 6.3 V pk | -0.3 V | 0.39% | 20 s | 530 K | 21 K | +-33 cents |
  | 0.5 | 1.49 Hz | 6.9 | 0.4 | 0.68% | 15 s | 566 | 5 | +-34 |
  | 0.7 (default) | 4.57 Hz | 6.8 | 0.5 | 0.28% | 8 s | 580 | 2 | +-35 |
  | 1 | 19.5 Hz | 7.3 | 0.4 | 0.29% | 4 s | 587 | 0.6 | +-33 |

  The bloom: from a start the amplitude overshoots to ~10-13 V peak (the follower clips it)
  and the lamp brings it down over 4-20 s, slower at the slow end, where the filament follows
  the cycle (21 K). Never hunting. With VIBRATO at 0 the LFO reaches the pitch by under 0.75
  cents. CPU: the LFO runs on a thread of its own (it owns its pots' wipers; on the first
  thread, with the cutoff's thread owning WOBBLE's wiper, Newton failed at the lamp within 5
  samples), so the load figure (the slowest thread) barely moves: a key held, back to back,
  72-82% with it, 74-78% with it off, no dropouts (this desktop drifts +-10%). What it costs
  is a core: the process used ~5.6 cores against ~4.4 with it off.
  `--turn lfo_rate=0.3,0.9` heard in ~93 ms, no restarts.
- **LFO ON / OFF** (`lfo_on`, the user's call: CPU; `unit: switch`, a checkbox in the app).
  OFF takes the oscillator, its pots and its supply out (switch parts), so the `lfo` section
  is empty and gets no thread (`fast.partition_sections` / varimu-app's `partition_sections`
  skip empty sections): one thread fewer, ~1.15 cores freed. RVIB's and RWOB's far ends are
  grounded. The synth's rails don't move. A flip restarts a live stream (~1.9 s to the ear,
  no dropouts).
- **VIBRATO and WOBBLE** (#8's start): 10k pots on the LFO. VIBRATO is summed into the pitch
  ahead of GLIDE (the key string through 1k, the wiper through 47k): into the 6V6GT's grid
  directly the 10k stopper's low source would have made the pitch follow GLIDE's setting, a
  coupling capacitor would have slid every key change for a second. Full: +-33-35 cents at
  every rate. The pitch scales by 0.979 and GLIDE 0 is a 4.7 ms time constant; the tuning
  tables were re-measured (panel.rs). WOBBLE feeds the CUTOFF pot's low end (127k, RCUTL now
  143k from -100 V: the same Thevenin source as before, so CUTOFF's law is unchanged; into
  V4's grid itself the same depth bent the law ~half an octave): V4's grid ~3 V peak to peak
  at CUTOFF 0.3 (all of the low end's share at 0, none at 1). Tests: `tests/test_tube_synth.py`,
  the LFO tests.

## 8. LFO routing and delayed vibrato

DEPTH into the pitch grid (S5's design), plus pots into V4's grid (filter wobble) and the
VCA's bias (tremolo). Delayed vibrato: an RC charged from the gate scales the vibrato
depth, so it fades in after the note starts. The alternative to the pitch grid is a
reactance tube across the tank (the period's FM). The kick's two attempts swept the wrong
way, so the grid is the first choice.

## 9. Second oscillator: DETUNE and COUPLING

S5's second oscillator, with one control nobody else has: COUPLING, a small variable
capacitance between the two tanks.
- At 0 the two beat freely (DETUNE sets how fast).
- Turning it up, they pull toward each other and lock when close (injection locking).
  That's the LC equivalent of hard sync, and the change from beating to locking is
  audible physics.
- Both already share the supply, so loud notes couple them anyway.

**Cost:** one VCO's Newton work, on a sixth thread. The load is the open question (the
first VCO is the voice's most expensive part). **Watch:** DETUNE adds to the drift that's
already there, so it may need a fine control.

## 10. Sub-octave divider

Eccles-Jordan triode flip-flops (1918, the first flip-flop) clocked by the square,
dividing by 2 and by 4, mixed in with SUB pots. It speaks to SYNTH_LOW_END.md's "light on
bass", and the divided squares keep perfect octaves whatever the oscillator drifts. It's
also the Novachord's principle (its 12 top-octave oscillators, divided down).
**Watch:** each flip-flop is two triodes that switch hard: Newton iterations at the edges
and aliasing at draft-2x. Slowing the edges with stray capacitance is the period's own
fix. Measure both.

## 11. NOISE in the mixer

S5's noise source: B5's shot or Johnson noise of a resistor or a tube, amplified by a
12AX7 chain into the mixer with a NOISE pot. Its spectrum then comes from the physics
(flicker below ~1 kHz, white above). Through the filter it gives wind, breath and snares.
**Watch:** the app's "Noise" switch costs CPU when on, and this needs it on. Measure the
load. A gas-tube or noise-diode source can come with #23.

## 12. Filter MODE

Low-pass (today), band-pass and high-pass from the same reactor and capacitor rearranged,
on a switch built from contacts that are always in the circuit. Measure each mode's sweep
and Q. The Q multiplier's feedback may need a different tap for each.

## 13. Filter DRIVE

A gain stage before the reactor with a DRIVE pot. S1 found that the signal moves the
cutoff: at strong bias a 5 mT ripple sees up to 1.7x the permeability of a 0.5 mT one, so
loud notes pull the cutoff down. DRIVE turns that core physics into a playable effect, plus
the stage's own clipping. **Watch:** control feedthrough grows with signal (S1: the control
circuit carries the second harmonic).

## 14. Ring modulator

S5's "if wanted": a diode ring between two transformers, oscillator 1 times oscillator 2
(after #9), with a RING level pot in the mixer and a balance trimmer for carrier bleed.
Diodes: SELENIUM@1 exists. The original ring modulator (Cowan, 1934) used copper-oxide
rectifiers, whose soft knee and leakage sound dirtier. That's a new device fit, shared with
#6. **Cost:** two transformers (JA cores, or gapped, where linear is enough).

**Prototyped (2026-11-01), then built out of order (the user's call) with the LFO as the
carrier.** `scripts/ring_study.py` -> `reports/tube_synth/ring/` (`core.json`, `synth_*.json`,
`cpu.json` from `scripts/ring_cpu.py`; takes under `audio/`).
- **The ring alone** (`core`: ideal sources, 1 : 1+1 mumetall transformers, a 10k load): with
  nominal parts the carrier and the signal bleed -47 to -70 dB under the product; from ~1 V of
  carrier it switches (3 f_c +- f_s ~10 dB under the product, a square carrier's). Selenium
  (1/4 sq. in. cells) and silicon measure within ~2 dB of each other (selenium quieter): the
  dirt copper oxide or selenium would add is leakage and mismatched cells, neither of which is
  modelled (the selenium fit leaves out its Fig. 6 leakage). ~0.3 s per second of audio alone
  at draft, half of it the JA cores.
- **In the synth it needs a thread of its own and drivers of its own.** On the filter's thread
  it cost +46% (Python's draft, back to back); alone, nothing in wall time but a core. Fed from
  the oscillator's buffer directly, its load current crossed the partition one sample late and
  Newton stopped at the cells: a 12AU7 follower per input fixes it (the period's practice too).
  Unterminated, its output rang.
- **What it multiplies, the options brought** (a key held, the oscillator out of the mix):
  (a) a second reactor VCO: the classic tracking bell, but +26-34% wall time on its own thread
  (the app's ~75% load toward ~100%), and a fixed tank ratio doesn't hold the interval
  (sqrt 2's capacitors: 1.42 / 1.40 at 1.3 kHz / 500 Hz, 1.23 at 197 Hz, 1.16 at 109 Hz: it
  needs a pitch input and tuning of its own, #9 / #19's); (b) the external input: the ring's
  thread only, but the app can't take keys and live input at once; (c) the LFO with 10 nF
  Wien capacitors: 8 Hz-1.9 kHz, no new oscillator. **The user chose (c)**; (a) stays #9's.

**Built (2026-11-01).**
- **LFO AUDIO** (`lfo_audio`, a checkbox): contacts (always in the circuit, so a flip updates a
  live stream in place) take 0.99 uF from beside each 10 nF Wien capacitor and 900 pF from the
  loop's compensation. `measure` (`built.json`): RATE 0 / 0.25 / 0.5 / 0.75 / 1: 8.0 / 34.6 /
  147 / 590 / 1884 Hz, 6.2-8.4 V peak, THD 0.2-0.55%. Off (LOW) it is the LFO as before (4.58
  Hz at RATE 0.7).
- **The ring** (`ring` section; RING ON `ring_on`, a checkbox, off at first; RING level; OSC
  level, new in the mixer): Cowan's diode ring of four selenium cells between two 1 : 1+1
  mumetall transformers; the oscillator's buffer into T1 through a 12AU7 follower (0.1 uF
  in), the LFO DC-coupled (it runs down to 0.08 Hz) through a divider into the other
  follower and T1's centre tap; T2 terminated (2.4k) into the RING pot and a 12AU7 make-up
  stage (~10x), into the mixer through 2.2M. Its supply is its own RC off the LFO's
  reservoirs, and it is in only with the LFO on and RING ON (nested switches): off, its
  section is empty and gets no thread, and the synth's rails never see it.
- **Measured** (`built.json`, a key held at -20 / -15 / -10 V, OSC 0): the oscillator bleeds
  -25 to -42 dB and the carrier -24 to -48 dB under the product (AUDIO RATE 0.5-0.9, and LOW
  at ~10 Hz, the through-zero tremolo). The ring at full peaks -1.7 to +4.9 dB from the
  oscillator alone at full (through 1M it was 3-9 dB over: 2.2M). RING ON moves the pitch
  0.004 cents (499.347 / 499.346 Hz) and the LFO's rate not at all; its ~12 mA sags the
  LFO's reservoirs ~6 V (the LFO's DC +0.24 V, ~1 cent through VIBRATO at full; the 5651s'
  feed falls ~0.5 mA, inside RCA's 1.5-3.5 mA).
- **Load** (`play.rs --hold 69`, 50 ms buffer, back to back, twice): RING OFF 75-91% (worst
  block 102-119%), RING ON (AUDIO, RATE 0.75, OSC 0.5) 86-91% (108-114%); no dropouts. The
  ring's thread costs a core. `--turn lfo_audio=0,1`: no restarts (contacts); `--turn
  ring_on=0,1` restarts the stream (switch parts, as LFO ON), no dropouts.
- Tests: `tests/test_tube_synth.py` (the ring's switches, the AUDIO range's rates, the
  product and bleeds with the pitch unchanged); panel.rs's knob order. The app's partition
  has a `ring` group ahead of the oscillator (it owns its output into the mixer; the
  oscillator and the LFO own its inputs).

## 15. ADSR and a second envelope

S5 measured option B, a second envelope (its own 6X4 and 0.47 uF from the keyboard bus,
ATTACK2 / RELEASE2) on V7's grid: +3% CPU. ADSR adds a DECAY to a SUSTAIN level on the
VCA's envelope (diode steering onto a divider set by the SUSTAIN pot). The Odyssey has an
ADSR and an AR. This would make the synth match.

**ADSR built (2026-11-01; the user's ask: staccato, plucky sounds). The second envelope isn't
built.** Diode steering alone can't do it: a decay while the key is held needs the attack
to *end*, and the keyboard bus holds its level as long as the key is down. So the attack
ends at a comparator with a latch (the envelope's header in tube_synth.yaml has the parts):
a 12AU7 attack follower (plate ~+43 V through ATTACK, grid clamped to the bus by a 6AL5)
charges the envelope toward the bus, so the peak follows velocity; a 12AX7 comparator
(envelope against the bus) fires near the top; two 12AU7 inverters latch it (fed back
through a 6AL5) and switch the follower off and a 12AU7 decay switch on (the envelope
through DECAY into the SUSTAIN wiper) until the next key down, when the comparator's
cathode jumps with the bus and lets go. RELEASE is as before. A -340 V rail (a silicon
diode off the HV winding) sits under the dividers so the switches turn fully off. New:
DECAY (`decay`), SUSTAIN (`sustain`, 1 = the AR envelope as before); ATTACK's track
2.2M -> 1.5M (~0.7 s at the slow end). `config/cathodes.yaml` gained the 6AL5's heater
(RCA, 1954).
- **How it was found** (`scripts/adsr_study.py`: the prototype as a variant, a bench of the
  envelope alone on ideal rails, then the built circuit): each stage of the design stalled in
  a new linear equilibrium first (the follower out of plate volts below the threshold, the
  decay switch turning on before the latch closed, the latch's feedback loaded down by the
  decay switch's grid current, the attack cut by the comparator's half-conduction before the
  latch engaged). The fixes: the follower's own plate supply, high-impedance dividers off
  the inverters, a second inverter for the attack, and an RC on the latch node for the reset.
- **Measured in the synth** (`--built`, `proto.json`, takes `reports/tube_synth/adsr/audio/`):

  | Case | Peak | Held at key up | Output -20 / -40 dB |
  |---|---|---|---|
  | pluck (A 0, D 0.3, S 0) | +0.1 V at 7 ms | -101 V | 96 / 224 ms |
  | brass (A 0.5, D 0.5, S 0.6) | -2.1 V at 97 ms | -40 V (SUSTAIN's -43) | |
  | organ (S 1) | +0.1 V | -1.8 V | |
  | soft key (bus -20 V) | -17 V at 5 ms | -102 V | 158 / 331 ms |

  A key re-pressed during the decay re-attacks (bench: 4.6 ms to the peak).
- **Retrigger (the user's ask, 2026-11-01).** A key pressed while another is held is legato:
  the bus stays down, so the latch doesn't reset (single trigger, as a Minimoog's). The Play
  view's **Retrigger** checkbox (on at first; `Player::set_retrigger`) makes the keyboard
  multi-trigger, as ARP's: a new key-down while one sounds lifts the bus for 1 ms
  (`player::RETRIGGER_GAP_S`, `midi::Keys::presses`), and the latch resets as for a fresh
  key. `--bench --legato-gap-ms` (`bench_nominal.json`): no gap, no restart; 0.5 ms already
  restarts a pluck (8 ms to the peak), a brass swell (36 ms) and a high sustain; at the
  fastest RELEASE the 1 ms dips the envelope ~20 V before the new attack (a retrigger's
  click). In the synth (built, legato pluck): -94 V -> +0.1 V with the lift, nothing without.
  A key going back to an older held one (a release) doesn't retrigger. The peak sits
  ~1 V above the bus (+0.1 V at full velocity, the AR's was -0.9 V): the VCA's grids a
  touch past zero bias for the attack's few ms.
- **Fragile corners (the user's call: leave them, they may sound interesting).** The bench
  (`bench_*.json`) with b1 sagged to 268 V and the -340 V rail +-20 V: at the slowest attack
  the comparator can sit half on and the attack stalls short of its peak (no decay: an AR
  note); at the fastest decay the latch can drop and the note re-attacks; one brass corner
  failed too. Nominal rails pass every case. A key's VCA sag moves b1 ~25 V, so the slowest
  ATTACK on a loud patch is where to listen.
- **Side effects:** the pitch moved +0.7 to +2.9 cents (b1 and the bias rail ~0.6 V higher;
  tuning tables kept); the SUSTAIN pot's ~1 mA lifted the -105 V rail, so V4's grid at C4
  moved +0.18 V (the cutoff tests re-baselined). The velocity table wasn't re-measured.
- **Load** (`play.rs --hold 69`, 50 ms buffer): on the filter's thread it ran 97-118% with
  dropouts; the envelope now has a thread of its own (the app's split: ... cutoff | envelope
  | ring | ...): 80-82%, no dropouts, one more core.

## 16. Sample-and-hold

A 6AL5 bridge gate samples NOISE (#11) or oscillator 2 onto a low-leakage capacitor,
clocked by the LFO's edge (#7), read out through a cathode follower and routed like the LFO
(#8). It gives random stepped pitch or cutoff. **Watch:** the capacitor's droop between
clocks (the 6AL5's leakage, the follower's grid current) is the sound's character: measure
it, don't hide it.

## 17. Units: each instrument its own

The circuits have seeded part tolerances (`passive_seed`, `passive_spread`), but the native
app builds nominal units only (`varimu-circuit` refuses a nonzero spread, R1). Port the
tolerance draws bit for bit (agreement test), then a UNIT number on the Play panel, so
"unit 7" and "unit 12" of the same design sound apart. It costs nothing at run time.
**Watch:** the tuning tables are measured per circuit, so a unit with different parts needs
its own (`vco_study.py --tuning` per unit, or measured on the unit's first build).

## 18. Through an amp

The synth through the 5E3 and its P12R speaker. As a live chain end (`panel::CHAIN_ENDS`,
today only the plate) it needs the 5E3's speed (1.61x real time at draft-2x with the
speaker; COMPONENT_EDITOR_PLAN.md C3: the user's pending decision). As a session insert
(SESSION_FX_PLAN.md: printed offline), speed only matters while auditioning. So the insert
route works first.

## 19. Duophonic

Two keys at once, the lowest on oscillator 1 and the highest on oscillator 2, as the
user's Odyssey 2800 does. It needs #9, a second pitch control input and a key-assignment
rule in the app (`panel::key_feeds`; the Odyssey's rule is the reference). One filter and
one VCA, so it's a two-note line, not polyphony.

## 20. Pentagrid modulator (6BE6)

A superhet converter tube used as a multiplier: one signal on each control grid. Compared
with the ring (#14) it's asymmetric and leaks each input, a different flavour of the same
idea. **New:** a pentagrid model (two control grids: a new tube form, both implementations,
fitted to the RCA manual's curves) and a component `6BE6@1`.

## 21. Formant banks

The Novachord's and Hammond's fixed resonant colours: a bank of LC band-passes (gapped
inductors) on a selector, as preset timbres after the filter. **Watch:** every LC adds
states, and DK's cost grows with their square (the 5E3's speaker readout took Play from
0.48x to 1.61x real time). Measure one formant before planning a bank.

## 22. Paraphony on one supply

Several oscillators sharing the filter and the VCA, all on one supply, so a chord's notes
pull each other's pitch and level through the sag (TUBE_SYNTH_PLAN.md's "later"). It costs
one VCO per voice. It waits on #9's measured cost, and possibly on speed work (the
partition's threads, M5's deferred speed).

## 23. Gas-tube sawtooth oscillator

S4's candidate (c): a thyratron or neon relaxation oscillator. A capacitor charges until
the tube strikes and discharges until it goes out. It gives a sawtooth, the sound the
synth lacks most after #5, and the Trautonium's own.
**New:** a gas-tube model (striking and extinction voltages, deionization time, the glow's
drop), both implementations, fitted to an RCA thyratron sheet (2D21 or 884) or a neon
lamp's. **Watch:** the discharge is a hard edge (aliasing, Newton). The plan for that
edge: [HYBRID_PHYSICS_PLAN.md](HYBRID_PHYSICS_PLAN.md) (the first physics exception, H1-H4).

## 24. Subharmonic mixtures

Oskar Sala's Mixtur-Trautonium: dividers on the main oscillator give subharmonics (1/2,
1/3, 1/4...), mixed into chords that are always in tune with each other. #10's flip-flops
give the binary ones (1/2, 1/4). Dividing by 3 is easiest with a relaxation oscillator
locked to the main one (#23), as the Trautonium did.

## 25. A step sequencer in tubes

Patterns clocked by the LFO. Two ways: a Dekatron (a cold-cathode counting tube, 10
steps; needs a glow-transfer model, after #23), or a ring of Eccles-Jordan flip-flops (#10's
cell, as 1940s computers counted; many tubes, so CPU). Each step's CV comes from a pot,
into the pitch or the cutoff. The app's recording (RECORDING_PLAN.md) would capture it as
the circuit's own output, with no events to replay.

## Breaking it on purpose (the user's direction, 2026-11-01)

After RESERVOIR's 1 uF end (a supply that can't hold up, the pitch warbling two semitones at
120 Hz) the user said: keep building true to real hardware values, and once the instrument is
dialed in, start breaking things on purpose. Component values pushed out of their sensible
range in interesting places, for effects and jank, as circuit benders do with real gear.

- **Order:** realistic first (every idea above is built with sourced, sensible values and
  measured), then the bends, each one a panel control whose normal position is the real
  value, as RESERVOIR's 20 uF is.
- **An experiment to do (not scheduled):** sweep candidate parts of the dialed-in synth far
  off their values and listen for what's interesting. Candidates to start from: the
  decoupling capacitors and filter resistors (b2 / b3, where the VCA's current sags the
  rails), the tank and RANGE capacitors, the Q multiplier's feedback, the envelope's
  timing capacitor, the coupling capacitors (bass, blocking distortion), cathode bypasses,
  the 5651 regulators' feeds (regulation dropping out), the grid leaks (blocking), the
  reactor's turns and core size. Per candidate: a short sweep with numbers (as
  `scripts/supply_study.py` did) and takes for the user to judge.
- **Asked for, parked (2026-11-01): deeper VIBRATO and WOBBLE** (the user: "it would be cool
  to hear more extreme settings"; revisit later). The pots are at their ends at 1; the depth
  is set by RVIB (47k against the key string's 1k: ~2% of the LFO's +-7 V, +-34 cents) and
  RWOB (127k, matched to RCUTL so CUTOFF's law holds). Options brought: (a, recommended) a
  DEEP checkbox feeding both pots from a one-tube LFO booster (a 12AX7 section, ~5x: VIBRATO
  ~+-1.7 semitones, WOBBLE ~+-1 octave; tuning and CUTOFF untouched; a few cents of pitch
  from the booster's DC offset while on); (b) smaller injection resistors (to ~10x) with the
  app rescaling the key string's volts by the divider's ratio (exact: the pitch's DC is
  linear in it) and RWOB / RCUTL changed as a pair; (c) a hotter lamp (a smaller RLS) for a
  bigger LFO swing: ~1.6x before the follower clips.
- **Still physical:** a bend is a part value a real unit could be built with (a switch of
  capacitors, a pot), never DSP. The panel marks the bent zone, as RESERVOIR's label does.
  Ratings: say on the panel when a position takes a part past its rating; the simulation
  doesn't wear out, but the label should be honest.

## What comes after

#9 and #11, with the LFO (#7), envelopes (#15) and ring (#14), are S5's own blocks. Built,
they close most of S5's done-when (TUBE_SYNTH_PLAN.md). #19-#25 belong to a later
milestone (S6), planned when S5 is done.
