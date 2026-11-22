# An imperfect Rhodes

Started 2026-11-22 on the branch `rhodes-imperfection` (worktree
`D:\Claude Code Projects\vst-imperfect`), the user away and delegating. What they asked:
real-world imperfection on the Rhodes Suitcase (key to key and strike to strike), separate
imperfection knobs as on the Clavinet, notes depending on each other where a real instrument's
do, the instrument still playable live, the production tier for what doesn't fit, renders to
hear whether it makes a difference. Only the Rhodes for now. The keyboard sends no release
velocity; there are no recordings beyond jRhodes3d and the Suitcase mp3.

Read first: [INSTRUMENT_REALISM_FABLE.md](INSTRUMENT_REALISM_FABLE.md) "What was tried,
2026-11-13" (the last round's lessons: fits to jRhodes3d's timbre made the instrument feel worse;
keep each key's level and feel; the user plays it before anything is pinned) and
[RHODES_VARIATION.md](RHODES_VARIATION.md) (why the model repeats itself).

## The rules this round follows

- **0 is today's harp, bit for bit.** Every knob scales a spread around the compiled
  instrument; at IMPERFECTION 0 (or every share 0) the medium plays MK1_HARP@2 exactly
  (tested). Nothing in the compiled harp changes.
- **Realistic first, then bend.** 1 is a real, played, maintained Mark I (spreads measured on
  jRhodes3d where it can say, provisional and labelled otherwise); 2 a neglected one.
- **Live.** All of it is on the harp's worker threads, which have headroom (73 keys ringing
  ~0.22x real time); nothing is added to the circuit's threads, where the Suitcase is at its edge.
- **Reproducible.** Every draw is a pure function of (unit, the part's name, the key) and, per
  strike or release, that key's count of them since the medium started: a MIDI take replays bit
  for bit, and changing one share moves only what it scales.

## Second round (2026-11-22, the user's: one knob, a wreck at the top, sympathy on a switch)

After the first round the user found the seven share knobs "a little too chaotic" and asked for
one global IMPERFECTION slider whose top "basically destroys the instrument", 0 the default
instrument; and the sympathetic sound on an on / off switch (off the default, to save compute)
with an amount that can go extreme.

**One knob.** The panel shows IMPERFECTION (0-10, default 0) and UNIT # only; the shares stay in
the IR (1 each; the builders take `imp_seed` and `imp_amount`, the shares optional) for tests and
studies. Each part's spread is its value at 1 times `imperfection.growth(amount)`: linear to 2
(0-2 exactly as the first round measured), then quadratic, 30x at 10, every draw held to a cap
(design choices, labelled so in the module: detune +-200 cents, tips and each strike's stiffness
1/20-20 and 1/10-10, decay and felt 1/20-20 (the felt's floor 0.02 now), each strike's speed
-20 to +1.5 dB: the bass tines already swing 10-14 mm of the map's +-18 at ff). Measured
(`rhodes_imperfection_demo.py --measure`, the harp alone, 73 keys at velocity 90, unit 1):

| | 1 | 2 | 5 | 10 |
|---|---|---|---|---|
| level key to key, dB rms | 1.2 | 2.6 | 9.9 | 21.6 |
| pitch, cents rms | 2.0 | 4.0 | 16.8 | 37.3 |
| sustain (0.45 -> 1.35 s), dB rms | 2.7 | 6.0 | 59.7 | 190 (keys dead at once, others ringing on) |
| release time, ln ratio rms | 0.44 | 0.80 | 1.46 | 1.76 |
| attack brightness, rms | 6% | 14% | 34% | 63% |
| a repeated C4, level / brightness | 0.40 dB / 3.4% | 0.78 / 7.6% | 2.2 / 23% | 4.0 / 32% |

Rust against the reference at 10 (every part): within -100 dB, finite on the test's events
(`tests/test_rhodes_imperfection.py`); the caps are tested over 73 keys and 50 strikes.

**Sympathetic resonance, live** (`varimu/rhodes/sympathetic.py` the reference; circuitsim's
`harp.rs` the port; the Suitcase's SYMPATHY switch, `sympathy`, off by default, and its amount,
`sympathy_amount`, 1 the compiled rail, up to 30). The offline rail study's mechanism
(`rail.py`), changed in three ways on the way to live, each found by measuring:

1. **Two phases per chunk** (`keyed.rs`: a coupled medium): every voice renders its own motion
   and records its grommets' force; the rail's modes step on the calling thread from all of
   them; every voice whose felt is off then adds its modes' rail-driven motion (kept apart from
   its own, carried through the damper's switches the same way) and reads the two through the
   pickup. The same on any number of threads and any chunking (tested, `tests/harp.rs`; a switch
   on a chunk's first sample was lost at first and only showed against the reference).
2. **A key doesn't feel its own push.** One way, the self-term drives a key at its own resonance
   for as long as it rings (two way it would be a small detuning and damping, not modelled):
   it put the sympathetic part 13 dB under a pedalled chord.
3. **Motion relative to the rail, pickups riding with it.** With the pickups still, the rail's
   low modes (36 Hz) moved every block alike and all 73 pickups read the same bounce, in phase:
   -15 dB under a pedalled chord, most of the "sympathy" (the keys' own rings summed only to
   -31 dB). Now the rail drives each assembly by its acceleration (exact for the free assembly:
   only its grommets resist a rigid translation, `K r = k_g g` to 1e-13) and a key moving with
   the rail adds nothing. The rail (rail.py's plank at EI x4) and so amount 1 stay provisional.

Measured (a pedalled C3-E3-G3-C4, all 73 keys, the harp alone): the rail's part 25.6 dB under the
whole at amount 1 (the struck keys' share -45 to -51 dB each; the loudest unstruck key, D3,
-38 dB; the unstruck keys together -34 dB), ~0 dB at 30. **The live tier's one approximation:**
a key only ringing in sympathy is read through the pickup's small-signal gain while its tip's
bound stays under 10 um (`harp.rs` `LINEAR_M`): -74 dB re the whole against the reference's
whole-map readout on that chord (-51 dB re the rail's part); without it the port agreed within
-118 dB. Amount 0 is off bit for bit; `MK1_HARP@3` is @2's data plus the rail's rows.

**Cost.** The harp alone (`harp_bench`, all of it on the medium's threads): a pedalled chord
0.05x real time off, ~0.29x on (every key wakes: 53 of the 69 unstruck keys ring between -40 and
-60 dB re the loudest struck key, so no level cut-off saves much without losing the halo); every
key struck 0.25x off, ~0.5-0.7x on. Live (`examples/play.rs --device rhodes_suitcase`): keys
held without the pedal, on costs about what off does; with the pedal down (`--pedal`, new) see
"Status" below.

**Status (2026-11-22, second round):** built, tested and committed on the branch; renders in
`reports/rhodes/imperfection/audio/` (`amount_{0,1,2,5,10}_unit_1.wav`, `sympathy_{0,1,5,30}.wav`
and their `_harp` / `_rail_part` files; the README there says what to listen for). In the
sympathy phrase's harp EMF the rail's part is -24 to -33 dB re the whole with the pedal down at 1
(-44 dB with it up), -10 to -19 at 5, about 0 at 30. **Live with the pedal down it doesn't keep
up yet:** `play.rs --device rhodes_suitcase --hold-bass 4 --from 48 --restrike 2 --pedal --mute
--buffer 0.05`, an idle machine, twice each: off 91-92% load, 0-1 dropouts; SYMPATHY 1 121-127%,
~300 dropouts in 12 s (was ~140% before the small-signal readout and the vectorized steps). The
medium's chunks run partly on the circuit's own thread. Options (the user's): a longer buffer,
SYMPATHY for renders only (a take recorded off, rendered on), or more work on the medium
(rendering it ahead on threads of its own, a batched filter bank for the keys only ringing in
sympathy); without the pedal (held keys only) on costs about what off does.

## Built (2026-11-22): the knobs (the first round; the panel since: the section above)

`varimu/rhodes/imperfection.py` is the reference (its docstring has the physics and every
constant's source), through `varimu/rhodes/harp.py`'s voices (`harp.render(...,
imperfection=)`); circuitsim's `harp.rs` is the port (`Imp`, applied in `Voice::new` and at each
event). The IR's `harp` element has an optional `imperfection` (absent: as compiled); the `harp`
part takes `imp_seed`, `imp_amount`, `imp_tuning`, `imp_voicing`, `imp_tips`, `imp_decay`,
`imp_dampers`, `imp_hammer`, `imp_release` (all or none, both builders).
`config/circuits/rhodes_suitcase.yaml` (and the generated 100 W file) has them as controls, the
app's `rhodes_suitcase` panel shows them; a change is another instrument (the stream restarts).

| Knob | What it varies | Spread at 1 | Source |
|---|---|---|---|
| UNIT # | which instrument (the seed) | | design choice |
| IMPERFECTION | every part's amount (x its share) | 1 = a real Mark I | design choice, default 1 |
| Tuning | each key's detune (a time scaling of its tone generator, exact) | 2.1 cents rms | **measured**: jRhodes3d from E2 up, 90% interval 1.6-3.2 (`scripts/rhodes_unit_spread.py`) |
| Voicing | each tine's height over its pole (timbre and level) | 0.3 mm rms, kept in 0.5-3.5 mm | derived: a per-key voicing fit to jRhodes3d came out 0.9-2.4 mm |
| Hammer tips | each tip's contact stiffness (attack brightness) | lognormal 0.2 | provisional: +-5 Shore A by Gent's relation |
| Sustain | each key's free decay rates | lognormal 0.25 | **measured**: jRhodes3d's Q per note about the fitted cubic, 0.257 in ln Q (includes measurement scatter) |
| Dampers | each felt's damping above the tine's own | lognormal 0.35, floor 0.1 | provisional: Rhodes dampers are uneven |
| Each strike | per strike: contact stiffness and hammer speed | lognormal 0.08; 0.4 dB | provisional |
| Each release | per release: the felt's landing (its damping) | lognormal 0.25 | provisional |

**Where each acts, and why.** Tuning scales the key's eigenvalues by r, its force input by 1/r and
its velocity rows by r (stiffness by r^2, mass kept): the contact and the damper's transfers stay
consistent. Sustain and dampers change only the free rotation's eigenvalues; the hammer's contact
steps keep the compiled decays (the Clavinet's lesson: a decay changed under the compiled residues
can make the contact's driving point active). A key whose sustain is changed steps the hammer's
whole 30 ms window (ending it early, as the medium otherwise does, would move the result). A
release counts only on a key that has been struck (the pedal moves every voice's damper).

**Tests:** `tests/test_rhodes_imperfection.py` (amount 0 bit for bit in both languages; Rust
against the reference within -110 dB with every part on and each alone; a repeated note varies
only with the hammer's share; the draws pure; the spreads; a detuned key sounds its cents; the
IR's check), `crates/circuitsim/tests/harp.rs` (the same on any number of threads). The existing
harp tests pass unchanged.

**Measured** (`scripts/rhodes_imperfection_demo.py --measure` ->
`reports/rhodes/imperfection/measurements.json`; the harp alone, 73 keys at velocity 90, unit 1):

| | amount 1 | amount 2 |
|---|---|---|
| level key to key | 1.2 dB rms (-3.7 to +3.7) | 2.6 dB rms (-8.2 to +6.2) |
| pitch | 2.0 cents rms (-3.7 to +6.7) | 4.0 cents rms |
| sustain (level lost 0.45 -> 1.35 s) | 2.7 dB rms | 6.0 dB rms |
| release (ms to fall 40 dB) | x/÷ 1.55 rms (0.23-2.3x) | x/÷ 2.2 rms (0.07-5.1x) |
| attack brightness (centroid, first 100 ms) | 6% rms | 14% rms |
| a repeated C4 (hammer share only), level | 0.40 dB rms | 0.78 dB rms |
| a repeated C4, brightness | 3.4% rms | 7.6% rms |

So per strike the variation is subtle by design (a real action is consistent); key to key it is
clearly there at 1 and strong at 2.

**Renders** (`--render` -> `reports/rhodes/imperfection/audio/`): one phrase (a repeated C4, a
repeated chord, a chromatic run C3-C5 at one velocity, staccato chords, the pedalled progression of
`rhodes_render.py --demo`) through the whole Suitcase at draft, at amounts 0 / 1 / 2, each matched
to -23 LUFS, with the harp's EMF beside it (`*_harp.wav`). Status below.

## Notes depending on each other

Already in the model: a re-struck tine is hit while it moves; every note shares the preamp, the
vibrato's photocells, the power amps and their unregulated mains supply, the speakers. The keys
themselves don't touch: the tone generators hang on a rigid rail.

**The rail** is the one mechanism in a real Rhodes that couples the keys mechanically
([INSTRUMENT_REALISM_FABLE.md](INSTRUMENT_REALISM_FABLE.md) SC5): every tone bar assembly sits on
its two grommets on the tone bar rail, so a struck key's reaction shakes the rail and the rail
shakes every other key's block. It would give, from one mechanism:
- a thump at the attack (the low assemblies' blocks bouncing on the grommets, seen by their
  pickups); SC4 measured the real bass with 2-11 dB more sub-f0 energy at the attack in loud
  layers than ours, a real gap;
- sympathetic ring with the pedal down (undamped tines at a struck note's harmonics);
- tines never starting from exactly rest.

No source gives the rail's modes or its mounting: they would be provisional, bounded, and fitted
only to SC4's thump.

**Studied offline (2026-11-22), not adopted.** `varimu/rhodes/rail.py` (the module docstring has
the model: weak coupling in three passes, the struck keys' grommet forces into a simply supported
plywood plank's modes, its motion back into all 73 keys as a base excitation through their
grommets; the plank 1 m x 100 x 19 mm, the assemblies' mass added, all provisional; the plywood
rail and its two screws through springs per assembly: web: https://shadetreekeys.com/category/tines)
and `scripts/rhodes_rail_study.py` -> `reports/rhodes/imperfection/rail/` (summary.json, WAVs: each
scene rigid / on the rail at one gain, and the keys never struck alone). At three plank stiffnesses
(EI x1, x4, x16: first mode 18, 36, 72 Hz):

| | EI x1 | EI x4 | EI x16 | real (SC4) | rigid |
|---|---|---|---|---|---|
| thump F1 (dB, < 0.7 f0 in the first 50 ms) | -23.9 | -26.0 | -26.6 | -16.3 | -26.6 |
| thump E2 | -14.9 | -14.1 | -22.2 | -20.0 | -25.6 |
| thump A2 | -11.5 | -12.3 | -14.1 | -23.7 | -25.8 |
| pedal down: the unstruck keys re the whole | -23.8 dB | -27.7 | -21.0 | ? | none |
| pedal down: the struck keys' own sound moved | -17.4 dB | -25.4 | -25.6 | | 0 |
| the rail's largest swing | 530 um | 180 um | 228 um | | 0 |

- **The thump has the wrong register pattern** at every stiffness: the real piano's grows toward
  the deep bass (F1 the most), the rail's grows upward (a rail mode under A2's f0 / 0.7, not under
  F1's) and overshoots A2 by ~10 dB. The real thump isn't this mechanism, or the pickups move with
  the tone bars (both rails on one harp frame: only their relative motion counts, which this model
  doesn't have), or the rail is far stiffer than any plank here.
- **The sympathetic ring is strong** (-21 to -28 dB re the played notes, pedal down): likely more
  than a real Mark I's (players describe a faint halo; nothing measured).
- So: no live port. What would decide it: a recording of a real Rhodes with the pedal down,
  one note struck and the others' ring audible (or a measured harp frame's modes). The WAVs are
  there to hear what it would add.

## Status

**2026-11-22 (one night, the user away):**

- **Built and tested:** the imperfection knobs above, live on `rhodes_suitcase` (Python reference,
  circuitsim port, both builders, the circuit, the app's panel; a change restarts the live stream:
  `live::structure` keys the harp's element on its imperfection). Tests listed above, plus
  `live::tests::the_rhodes_imperfection_restarts_the_stream`. Default IMPERFECTION 1.
- **Live load:** none measurable. `examples/play.rs --device rhodes_suitcase --hold-bass 6 --from
  48 --restrike 2 --mute --buffer 0.05 --for 15`, twice each: amount 0 84-93% mean (16 / 4
  dropouts), amount 1 84-95% (6 / 0): the spread is run to run. The all-keys stress test (`--strike-all
  127 --restrike 3`) overloads either way, as on main.
- **Renders** (`reports/rhodes/imperfection/audio/`, `README.md` there says what to listen for): the
  phrase through the whole Suitcase at draft (speakers' pressure, stereo, -23 LUFS each), 62x real
  time with three at once. In it a repeated C4 at one velocity varies -0.6 to +1.2 dB at amount 1,
  -1.3 to +2.1 dB at 2 (0: +-0.1 dB, the vibrato's pan).
- **Not done / open (the user's):**
  - the user plays it, especially IMPERFECTION 0 against 1 (the spreads at 1 are the measured
    piano's where it could say; "Each strike" and "Each release" are provisional);
  - merge or not (the branch keeps main's Rhodes untouched until then);
  - per-strike strike position (where the hammer meets the tine): measured, ±1 mm moves the
    fundamental ±0.4 dB and the upper modes 1-4 dB, about as subtle as the per-strike stiffness;
    it needs a recompiled harp (each key's input at a second point), so not built;
  - the release itself is still the switch the user disliked in RHODES_VARIATION.md (only its
    length now varies key to key and release to release); a real release reference would decide
    the felt-as-contact model INSTRUMENT_REALISM_FABLE.md describes;
  - the rail: offline only (above);
  - found on the way, not this work's: varimu-app's `print::tests::an_inserts_noise_seed_and_hum_change_its_build_and_key`
    (the V76's hum count, 13 sources, not a multiple of 3) and clippy's `repeat_vec_with_capacity`
    in circuitsim's `noise.rs` fail on the branch with code it didn't touch.
