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
| 6 | SUPPLY: rectifier and reservoir | How much the voice sags and blooms | Switch contacts; copper oxide needs a fit | Small |
| 7 | Lamp-stabilized Wien LFO | A working LFO that blooms | Lamp device model | ~+1% |
| 8 | LFO routing, delayed vibrato | Vibrato, tremolo, filter wobble | Pots, an RC | Small |
| 9 | Second oscillator, DETUNE, COUPLING | Beating, pulling, locking | A second VCO | One VCO; a thread |
| 10 | Sub-octave divider | Square sub-octaves, weight | Triode flip-flops | Edges: Newton, aliasing |
| 11 | NOISE in the mixer | Breath, wind, percussion | Amplified B5 noise | Noise on: measure |
| 12 | Filter MODE (LP / BP / HP) | Thin, vocal, nasal shapes | Switch contacts | ~0 |
| 13 | Filter DRIVE | Grit; loud notes darken | A gain stage | Small |
| 14 | Ring modulator | Metallic, bell-like | Diode ring, transformers | Two transformers |
| 15 | ADSR / second envelope | Shaped notes, independent sweeps | Diode steering, a pot | ~+3% |
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

## 15. ADSR and a second envelope

S5 measured option B, a second envelope (its own 6X4 and 0.47 uF from the keyboard bus,
ATTACK2 / RELEASE2) on V7's grid: +3% CPU. ADSR adds a DECAY to a SUSTAIN level on the
VCA's envelope (diode steering onto a divider set by the SUSTAIN pot). The Odyssey has an
ADSR and an AR. This would make the synth match.

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

## What comes after

#9 and #11, with the LFO (#7), envelopes (#15) and ring (#14), are S5's own blocks. Built,
they close most of S5's done-when (TUBE_SYNTH_PLAN.md). #19-#25 belong to a later
milestone (S6), planned when S5 is done.
