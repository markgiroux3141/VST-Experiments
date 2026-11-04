# Sidechain: a keyed 670, a filtered sidechain, a split-band ducker

Drafted 2026-11-01 from a brainstorm with the user; picked up 2026-11-04 (Decisions, Plan of
attack below). The user asked two things: how sidechain compression would work
on our 670, and whether a variant could duck only the bass, with a low-pass filter. The order
below is the one agreed on 2026-11-04.

**Status (2026-11-04): K1 and K2 done, K3 built, the user to try it** (details under
Milestones). Keyed, the 670 has no ratio but a cliff (a few dB of key go from a light duck
to the 6386s cut off); the user chose option B, a DEPTH control, built the same day
("DEPTH" under K1).

## How the 670 listens today

The 670 is a **feedback** compressor: its sidechain hears its own output. The path, in
`config/circuits/fairchild_670.yaml` (sections "sidechain input" to "rectifier and time
constant"):

`out` (T102's 600 ohm secondary) -> the pad R145 / R147 (150 ohm legs), R149 (1360 ohm
shunt) -> T103 (600 ohm : 170k step-up, centre-tapped) -> AC THRESHOLD (R115A / B) -> 12AX7
-> 12BH7 -> 6973 push-pull -> T104 -> the bridge -> the time-constant network -> the
control voltage on the 6386 grids.

There is no external sidechain input on the original.

## The key input: switch T103's primary

T103's primary is already a 600 ohm line input. So the most plausible mod is a switch on
what feeds it:

- **INT**: the stock pick-off from `out`;
- **EXT**: a KEY jack, a line-level signal at 600 ohms.

That is one `switch` part ahead of T103. Everything after it is unchanged.

**What changes in behaviour.** With an external key the feedback loop is open, so the 670
becomes **feed-forward**:

- Its "ratio" disappears. In the stock unit the ratio comes from the feedback around the
  6386's remote-cutoff curve. Keyed, gain reduction depends only on the key's level.
- AC THRESHOLD becomes a sensitivity control. The time constants become the duck's attack
  and release (TC1's ~0.3 s release suits pumping).
- **Thumps.** The 6386 pair is push-pull, so a moving control voltage mostly cancels. Hard
  ducking at a fast TC lets any imbalance through as thumps. The per-tube mismatch draws and
  the BALANCE setting produce that on their own. It is real character; measure it rather
  than hide it.

## Two meanings of "duck the bass with a low-pass"

### (a) A filter in the sidechain: the bass triggers, the whole signal ducks

- The filter goes at the pick-off, in the 600 ohm world ahead of T103, so one filter covers
  both push-pull legs. (At the 12AX7 grids it would need a matched pair.)
- A first estimate at 150 Hz: a 2nd-order Butterworth between 600 ohm terminations, about
  **0.9 H in series and 2.5 uF shunt** (provisional: to be redesigned against the real
  terminations, T102's secondary as the source and the pad plus T103 as the load).
- The inductor is iron-cored. Model it as one winding on a Jiles-Atherton core (the
  `transformer` macro), so loud bass saturates the detector's own filter. The 670 never
  had this physics; a real mod would.
- A rotary switch: **FLAT / LP / HP**. The HP position (the common pro mod: stop the bass
  from pumping the whole mix) costs almost nothing extra.

### (b) Split-band: only the bass gets ducked

- A passive crossover at 600 ohms splits the input.
- The low band goes through channel 1's 6386 stage, keyed.
- The high band goes through channel 2's 6386 stage at a fixed bias (its sidechain
  disconnected), so both bands get the same tube and transformer colour.
- The bands are summed (a summing transformer or a resistive mixer).
- Push-pull transformers make polarity inversion free (swap a winding's ends), so an LR2
  crossover with one band inverted sums flat at 0 dB of gain reduction.
- Under ducking, the crossover region shifts in phase and dips. That is the real artifact
  of doing this in hardware: worth hearing, not hiding.
- A real engineer could build it from a stereo 670, a passive crossover and a summing
  transformer.

### Which one when

For "the kick ducks the bass": **(a) on the bass track, keyed from the kick, with the LP on
the key.** A bass track is mostly lows anyway, and the LP makes the key respond to the
kick's thump rather than its click or bleed. (b) is for ducking only the low end of a full
mix or a dense bus.

Related, period-correct: the stereo 670's LAT / VERT mode compressed the sum and difference
for vinyl cutting. The vertical (L-R) channel's job was largely to tame out-of-phase bass
that would throw the cutter. It needs the full stereo unit (the matrix), so it isn't a
first step.

## What it costs in this codebase

- **New circuit files.** `fairchild_670_keyed.yaml`, later `fairchild_670_splitband.yaml`.
  `fairchild_670.yaml` stays as it is, so its goldens and fixtures stay byte-identical. They
  could also be drawn in the native editor from `fairchild_670_drawn`.
- **The key as an input.**
  - The quick path is the existing control inputs (`cv_inputs`, S3). They work now with no
    engine change. They interpolate linearly between samples, which is fine for a detector,
    especially a low-passed one (production's 5th-order input interpolation isn't needed
    there).
  - The catch: ngspice runs no control inputs, so the keyed path wouldn't be cross-checked.
    The fix is small: a second filesource in `io.run_transient`.
- **Split-band.** Channel 2 is lumped onto the rails today ("channel 2 (idle, lumped)"); it
  would become a full signal path. DK's cost grows with the square of the states, but the
  N-way partition fits well: the two channels share only the supply rails, so channel 1 |
  channel 2 | supplies, each on its own thread. Measure with `examples/load_profile.rs`.
- **The native app.**
  - Session inserts need a "key from track X" route (SESSION_FX_PLAN.md).
  - A print's cache key must include the key track's audio hash.
  - The live timeline source feeds two streams.
  - The web app gets nothing.
- **Measurement (a profile for the keyed unit).** Gain reduction vs key level; duck depth
  and recovery per TC; thump level vs BALANCE and mismatch; for (b), the sum's flatness at
  0 dB of gain reduction and the crossover dip under ducking.


## Decisions (2026-11-04, the user's, taking Claude's recommendations)

The user picked it up on 2026-11-04 for one use first: **one session track keying another's
670** (the kick ducking the bass). So (a) first, keyed from another track.

1. **A separate keyed device.** `fairchild_670_keyed.yaml` is generated from
   `fairchild_670.yaml` by a script, so the stock 670 and its goldens, fixtures and caches
   stay byte-identical, and later fixes to the 670 carry over by rerunning it.
2. **The key's tap: after the key track's inserts, before its fader, whatever its mute.**
   A muted kick still keys (the "ghost kick").
3. **The key's level: a trim on the route** (console arithmetic, as an insert's trim), set
   once from the key track's loudest stretch to -18 dBFS, then fixed. AC THRESHOLD stays
   the sensitivity; no KEY LEVEL pot on the mod.
4. **Built on a branch** (`sidechain`).

## Plan of attack

### The 670 (K1)

- `scripts/derive_keyed_670.py` patches the stock file's text (comments and sources kept):
  R145's top end goes through a `switch` part `KEY` (control `key_mode`, 0 INT, 1 EXT): INT
  is the stock pick-off from `out`, EXT takes it from the KEY jack, a control input
  (`cv_inputs: {key: key_src}`) behind a 600 ohm source. Everything from T103 on is the
  stock circuit.
- The key is in circuit volts on the 670's input convention: 0 dBFS = the input full
  scale behind the source impedance, so a key as loud as the program keys as hard as the
  program would.
- In EXT, `out` loses the pick-off's ~1.66k load: real behaviour, measured.
- **The keyed profile** (`varimu unit --circuit fairchild_670_keyed`,
  `varimu/measure/keyed_suite.py`): gain reduction against the key's level, duck depth and
  recovery per time constant on kick-like bursts, the thump at the output with the program
  silent (against BALANCE), INT against the stock 670. It renders with
  `fast.run_transient(controls=)` directly: `RenderJob` has no control inputs, and adding
  them edits `varimu/sim` (every render's cache key); that waits for the next batch of
  cache-invalidating edits.

### The key in the app's engine (K2)

- `render::render` takes control streams (the port of Python's `control_streams`: the
  settle's first value in front, linear onto the simulation's grid), on
  `simulate_controls` / `simulate_partitioned_controls`; bit for bit with Python on a
  keyed case (`app_render_agreement.py`).
- A device "Fairchild 670 + key" in `panel::DEVICES` (the 670's art, the KEY switch), its
  key input named by `Device::key` (not a keyboard `Feed`: the keys don't play it).
- `print::Slot` takes a key; `print::key` hashes its samples; the print renders with it.
- `player::Source::Timeline` takes an optional key (audio and its start, read at the same
  transport positions), fed through `Live`'s control inputs.

### The session (K3)

- **Stable track ids** in `session.json` (old sessions get them on load); routes name ids.
- **A slot's key route** `{track, trim_db}`: the key track's playing audio (its print, else
  its take) on the timeline, cut to the keyed track's print span, silence elsewhere. Written
  as a route (source track, tap, level) that F4's sends can reuse.
- **Dependencies:** a keyed track's chain signature includes its key track's playing
  signature, so a change to the kick re-prints the bass; the scheduler prints a keyed track
  only once its key tracks are current; cycles are refused (greyed out in the menu).
- **The view:** the insert panel's KEY row (track, trim, INT / EXT; picking a track sets
  EXT, none sets INT), the chip `[670 ⚷ Kick]`, a gain-reduction trace under the keyed
  track's lane from the print's `cv` probe.
- **Audition** plays the keyed insert live with its key; **⤓ Render** bakes it with the key
  as it plays now (`rendered_from` names the key).
- Known edge: a key hit just before the keyed take starts is ignored (a print starts at its
  take).

### Milestones

- **K1, the keyed circuit.** *Done when:* INT renders as the stock 670 (within roundoff);
  a kick-keyed bass ducks in a render; the profile measures it.

  *Status (2026-11-04): done.* `scripts/derive_keyed_670.py` -> `fairchild_670_keyed.yaml`
  (`--check`; `tests/test_keyed_670.py`): the switch `KEY` (`key_mode`), R145 at INT, R145K
  (R145 rewired, its own tolerance draw) and the jack `RKEY` (600 ohm source) at EXT; at INT
  the jack is terminated in 600 ohm (`RKT`; without a load the control input's node would
  float). Its IR at INT is the stock IR plus the jack's two resistors; renders at INT equal
  the stock 670's exactly (0 of every sample differs, draft-1x and production). The profile
  `varimu/measure/keyed_suite.py` (`varimu unit --circuit fairchild_670_keyed --name NAME`,
  ~7 min at production on this desktop; reports in `reports/units/keyed670_nominal/`): a
  110 Hz bass at -18 dBFS keyed by a kick (150 -> 50 Hz, 0.12 s decay) whose steady pattern
  is at -18 dBFS (KEY_REF_DBFS, what the session's key trim sets), the default panel (the
  factory adjustment), TC 2. Production and draft-1x agree within 0.1 dB:

  | key re -18 dBFS | -12 | -6 | -4 | -2 | 0 | +2 | +4 |
  |---|---|---|---|---|---|---|---|
  | deepest duck (dB) | -0.4 | -0.7 | -2.2 | -4.4 | -15.7 | -95 | -96 |
  | 100 ms on (dB) | -0.4 | -0.6 | -1.5 | -3.1 | -6.5 | -29.7 | -92.9 |
  | CV min (V) | -5.7 | -8.2 | -21.4 | -46.1 | -86.1 | -131.5 | -159.9 |

  Recovery from one kick at the reference, back to -1 dB: TC1 0.22 s, TC2 0.62, TC3 1.8, TC4
  3.4, TC5 1.8, TC6 0.22 (TC5 / TC6 program dependent: one kick takes their fast release).
  Thump with the program silent: -217 dBFS at BALANCE 0.5 (the nominal unit is symmetric),
  -30 dBFS at 0.4 or 0.6 (key at the reference; -25 at +6 dB): 12 dB under the program. EXT
  takes the pick-off's load off the output: +1.06 dB. `RenderJob` still has no control
  inputs (the suite calls `fast.run_transient` directly): adding them edits `varimu/sim`,
  so waits for the next batch of cache-invalidating edits.

  **The cliff.** Without its feedback the sidechain's gain is all there is: from -2 to +2 dB
  of key the duck goes from 4 dB to the 6386s cut off. It is the physics of opening the
  loop, not the draft. The options as put to the user (B chosen, 2026-11-04):
  - **A. Keep it** (the mod as a studio would wire it): the key trim and AC THRESHOLD set
    where the cliff is; good for a hard pump, hard to set for a gentle duck.
  - **B. A DEPTH control** (recommended): a diode from the control-voltage line to a pot's
    wiper on the bias supply, so the CV can't go below the pot's voltage: the duck bottoms
    out where DEPTH says (from the table: about -45 V for -4 dB, -86 V for -16 dB). One
    diode and one pot, what a gate's RANGE does; values provisional.
  - **C. INT and EXT summed** (the key added to the stock pick-off): the feedback keeps a
    little ratio for the program, but the key's own contribution is still open loop; it
    doesn't fix the cliff.

  **DEPTH (built 2026-11-04).** B as first sketched didn't survive the numbers; what was
  measured on the way (draft-1x prototypes, an ideal source first):
  - The bias supply is only -34 V (C302's node; the 6386s' ZERO end -19 V): too shallow.
  - An ideal clamp on the CV line works (at -40 V the duck stays at -6 dB from 0 to +12 dB
    of key; at -90 V at -34 dB), but it must take what the 6973 pair pushes through T104
    and the bridge: 60-107 mA peaks, 8-23 mA mean over a kick, up to 11 mC per kick. No
    pot (or a capacitor at its wiper) holds that.
  - Limiting the drive at the 12AX7 grids (the AC THRESHOLD wipers, microamps) only moves
    the cliff onto the knob: a limit of 3 V gives -1.2 dB, 4 V -3.4 to -4.8 dB, 6 V the
    6386s cut off.
  - So a follower on the CV line: a 12BH7 with its plate at ground was too weak at low
    plate voltage (its grid then dragged the wiper 25-55 V); an EL34 (triode connected,
    the regulator's type) from B+ held, but its Koren tail at ~245 V conducted ~1.8 mA at
    idle (the program 0.2 dB louder) until its cathode got a load of its own and a clamp
    diode to the CV line (off at idle); its standing current, ~14 mA on 39k to the
    supply's reservoir, keeps the 60-100 mA peaks within ~13 V of grid swing. One EL34 is
    ~0.5 dB softer than two; one it is.

  The circuit (all in the KEY switch's EXT position, so INT is the stock circuit; the
  generated file's `KEYS` in "power supply", `KEYD` in "rectifier and time constant"):
  T302's HV half A -> a silicon diode -> 22 uF (~-560 V) -> 100k -> two 5651s (-174 V,
  0.1 uF across) -> 30k / the DEPTH pot 100k (`key_depth`) / 15k (the wiper -36 to -156 V,
  4.7 uF on it) -> 47k -> the EL34's grid; its plate on B+ through 1k, its cathode on 39k
  to the reservoir and through a silicon diode to `cv`. Values provisional (design).

  Measured at production (`reports/units/keyed670_nominal/`, depth.png), the deepest duck
  on the third of three kicks, TC 2, by the key re -18 dBFS:

  | DEPTH | 0 | 0.15 | 0.3 | 0.45 | 0.6 | 0.8 | 1.0 |
  |---|---|---|---|---|---|---|---|
  | key 0 dB | -2.6 | -3.9 | -5.1 | -7.5 | -11.8 | -15.5 | -15.5 |
  | key +6 dB | -3.3 | -4.5 | -6.0 | -9.5 | -17.4 | -39.9 | -96.8 |
  | key +12 dB | -3.3 | -4.2 | -5.8 | -9.5 | -17.6 | -37.3 | -95.1 |

  Up to ~0.45 the key's level hardly matters (what DEPTH is for); deeper, the 6386s' own
  steepness near cutoff turns the clamp's last few volts into many dB; fully clockwise is
  the keyed 670 without a limit. The shallowest is ~-3 dB, not 0: the follower's swing at
  the bridge's peaks. B+ dips at most 5 V (DEPTH 0, key +12 dB), elsewhere < 1 V. At the
  default (0.45) one kick at the reference ducks ~10 dB in every time constant; thump at
  BALANCE 0.4 -31 dBFS (key at the reference), -29 at +6 dB (was -25 without the limit).
  The idle is untouched (the program's level the same at DEPTH 0 and 1 within -60 dB:
  `tests/test_keyed_670.py`); INT still renders as the stock 670 exactly. Cost: a draft-1x
  render keyed by kicks at +6 dB runs 0.5-0.6x real time (DEPTH 0 to 1; the settle
  counted), EXT without a key 0.49x live against the stock 670's 0.63x (no ducking, the
  sidechain idle); the app's keyed render through the clamp equals Python's bit for bit
  (draft-1x and production).
- **K2, the key in the app's engine.** *Done when:* the app's keyed render equals Python's
  bit for bit; a print and a live stream take a key.

  *Status (2026-11-04): done.* `render::render_controls` (`render` is it with none: control
  inputs at 0 V) with `control_streams` / `interp`, the port of Python's `control_streams`
  and `np.interp`; `examples/render.rs --control NAME=FILE.f64`; `app_render_agreement.py`'s
  case `fairchild_670_keyed` (kicks on the key, EXT, TC1): 360,000 values, 0 differ, at
  draft-1x and production. `panel::Device::key` and the device `fairchild_670_keyed`
  (DEVICES[14], "Fairchild 670 + key"). `print::Slot::key` (`KeyRoute {track, trim_db}`,
  saved with the slot), `print::key_control`; `print`, `print_chain`, `Job::spawn` take the
  sidechain (`sidechain`, `sidechains`; "key" in print.rs is the cache key): the print key
  hashes its samples, the route's trim and the control input only when there is one, so
  every other print keeps its key. `player::Source::Timeline { key: Option<TimelineKey> }`
  (the key track's audio from the same start, read at the same transport positions, on the
  key input through `Live::process_with`); `examples/audition.rs --key FILE --key-db DB
  --set KEY=V`. Tests: `print::tests::{the_key_follows_the_sidechain,
  a_keyed_print_ducks_under_its_sidechain}`, `live::tests::
  a_key_on_its_control_input_ducks_a_live_stream`. In a live stream the key isn't delayed
  by the program's upsampler (a few samples at 2x): inaudible for a ducker.
- **K3, routing in the session.** *Done when:* kick -> bass set up in a session, heard live
  and in the print; a change to the kick re-prints the bass; a cycle can't be made.

  *Status (2026-11-04): built, the user to try it.* `session::Track::id` (saved; a session
  saved before ids gets `track<N>` by place), `Session::{track_index, chain_signature,
  print_current, keys_ready, sidechain, sidechains, key_signature, would_cycle}`; the view
  uses the session-wide signature for prints, their states and Match. The insert panel's
  KEY row (a keyed insert only): the key track (tracks that would make a loop greyed out;
  none = INT), the key trim; choosing a track sets `key_mode` 1 and the trim (its loudest
  8 s to -18 dBFS), none sets 0. The chip reads `670 ⚷ Kick`. A keyed track prints once its
  key tracks' prints are current ("waiting for its key track to render"); the audition plays
  with the key and restarts when it changes; ⤓ Render bakes with the key as it plays then
  (the take's `rendered_from.keys`: track, take, position). Test:
  `session::tests::a_key_route_feeds_the_kick_into_the_bass_and_follows_it`. Not yet: the
  gain-reduction trace under the lane (a print keeps only its audio; it needs the `cv`
  probe kept with the print).
- **K4, the sidechain filter** (FLAT / LP / HP on a JA-cored inductor). After the routing:
  an isolated kick track needs it less than a bleedy or mixed key does.
- **K5, split-band.** Parked.
- **Optional:** the key in ngspice (a second filesource) for the cross-check.
