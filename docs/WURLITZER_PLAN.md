# The Wurlitzer 200A electric piano from physics

Drafted 2026-11-20 from a conversation with the user ("what would it take for us to add the
wurlitzer 200 to our list of simulated instruments? How close is it to the rhodes?", then "let's
write a plan for the 200A, and both speaker and no speaker option"; then "let's start building
this now"). It expands INSTRUMENT_PLAN.md's milestone I3, whose prerequisite (the BJT model) exists
since the Clavinet's CL0. The order below is a recommendation; the open decisions are the user's.

Sources: [data/schematics/wurlitzer_200a/README.md](../data/schematics/wurlitzer_200a/README.md)
(the 200 / 200A service manual, Tropical Fish's high-resolution scan of its 200A schematic, Vintage
Vibe's reed blanks and tuning guide, Pfeifle's DAFx-17 model). Values below without a source there
are marked provisional.

## Status (2026-11-20): WZ1 and WZ2 built (branch `wurlitzer`, commit 186856a)

**WZ1, one reed offline in Python** (`varimu/wurlitzer/`, outside the render cache key;
`config/wurlitzer/200a.yaml`; `tests/test_wurlitzer.py`, 16 tests;
`scripts/wurlitzer_key_study.py [--fit] [--keys ...]` -> `reports/wurlitzer/key/`, WAVs of the
plate's voltage):
- `reed.py`: the reed as Euler-Bernoulli FE (the Rhodes' elements), clamped, the lead a sleeve
  with rotary inertia, stiffness-proportional loss (Q = 1 / eta exactly); `tune` solves the free
  length for the note with the lead a set ratio of the tongue's mass (provisional: 0.6 in the
  bass to 0.1 in the treble, log-linear). Lengths come out 65 mm (A1) to 17 mm (C7); the second
  mode at 8.9 to 6.7 x f0.
- `pickup.py`: the plate's capacitance per metre of reed against its height, a 2D Laplace solve
  across the reed in its slot (bilinear rectangles, the reed moved by whole cells, mirror walls
  at the neighbours, grounded shield and reed bar), cached in `cache/wurlitzer/` (5 blanks, ~1.5
  min each on 6 processes). ~0.45-0.50 pF a reed standing; the plate's pull on a reed shifts its
  pitch < 0.003 cents (negligible).
- `key.py`: a strike with the felt's contact solved inside each step (Pfeifle's power-law felt
  with Hunt-Crossley loss), the free ring in closed form, the capacitance integrated over 8
  Gauss points along the slot, the plate's node linear and time invariant (checked against the
  exact equation within 1%).
- **The done-when holds:** every reed rings at its note (< 0.01 cent), the bark grows with the
  strike, a reed at rest in the plate's plane doubles its frequency (the service guide's
  "very strong undesirable harmonic"), the electrostatic force is measured.
- **The fit** (one voicing and one hammer speed per Pie-finger layer on 9 keys, harmonics 2-5
  where the recording holds them above -60 dB): voicing 0.66 mm, speeds 1.9 / 2.7 / 3.9 m/s,
  13.2 dB rms. The bass's bark grows with velocity as the recording's but is too strong at a
  soft strike; the middle and the treble are too clean; the treble's H4-H5 (the recording's
  -60 to -75 dB) are far below in the model (-85 to -150): not the pickup's curvature. One
  voicing can't serve the keyboard: WZ3's per-register fit. The hammer (1 g, K 4e9) gives 0.4-2
  ms contacts; the bass reed swings 2.8-5.6 mm at the slot.
- The WZ1 plate load (`plate.fixed_f` 300 pF, C2 counted) is superseded by WZ2's circuit: the
  preamp bootstraps C2, and the plate sees ~180 pF (the reeds, the stray, C3's Miller share).

**WZ2, the electronics** (`config/circuits/wurlitzer_200a.yaml`, traced from the sharp scan, every
value the drawing's or marked provisional; `scripts/wurlitzer_amp_study.py [--only idle vibrato
vibrato_fit response power]` -> `reports/wurlitzer/amp/summary.json`;
`tests/test_wurlitzer_200a.py`, 5 tests, ~80 s; the app fixtures regenerated, Rust's builder
equal bit for bit, `crates/varimu-circuit/tests/agreement.rs`):
- the reeds enter as the audio input `in` through their standing capacitance CREEDS (31 pF): `in`
  = V0 dC / C_reeds is the reeds' current to first order (WZ4's medium replaces it); `out` is the
  AUX jack into 10 kOhm, `spk` the amplifier into two 16 ohm resistors (WZ5's speakers later);
- **idle:** +-22.5 V, +15 V (IC-1 ideal), +150 V (the HV winding calibrated, its filter started at
  its steady state), the amp centred at +48 mV, TR-2 / the AUX stage / the power amp within 30%
  of the printed voltages; TR-1's base and emitter ~0.7 V above them (README: open);
- **vibrato:** the twin-T oscillates at **5.52 Hz unfitted** (Pie-finger 5.73, the manual's 5.75),
  9.1 V p-p at the collector (the drawing 11.5); R17 fitted (`vib_trim` 0.056, ~260 ohm) for the
  recording's 6.2 dB p-p at VIBRATO full; the envelope's 2nd harmonic -9.5 dB against the
  recording's -13.8 (a rounder swing in the real one: the LDR stand-in's shape); VIBRATO off
  unmodulated;
- **response** (the test input to the AUX jack): a steep rise to ~2-3 kHz (-39 dB at 30 Hz, -10 at
  430 Hz, -3 at 1 kHz, +4.5 above 5 kHz): the plate's differentiator, R2's 1 MOhm against ~180 pF,
  so the reeds' current, not their swing, sets the low end;
- **power:** 18 W at 0.14% THD, 23 W at 6.7% into 8 ohm (clipping ~20 W); the output stage idles
  at 3.8 mA, nearly class B: 2.5% THD at 10 mW (crossover; R58 "opt" only lowers the bias).
  AUX at 1 V of reed-equivalent input: 0.40 V rms, the drawing's "approx. .4 V AC" maximum.
  (These reed-equivalent volts are at WZ2's CREEDS of 31 pF; WZ3's 54.9 pF passes 1.77x the
  current for the same volts: `tests/test_wurlitzer_200a.py` scales its drive to keep it.)

**Open (WZ2):** TR-1's printed voltages; TR-8's collector (read as ground); whether the AUX
output follows VOLUME (read: it doesn't); the transistors' JEDEC types (stand-ins); LG-1's type
(VTL5C2 stands in: the envelope's shape); the low-level crossover distortion (real or the
stand-ins' Vbe).

## Status (2026-11-20, second session): WZ3 built (branch `wurlitzer`, commit aa97133)

**The keyboard** (`varimu/wurlitzer/keyboard.py`; `tests/test_wurlitzer_keyboard.py`, 9 tests):
every key a voice over the events, as the Rhodes' harp: between events the reed moves in closed
form (the system's eigenvectors, decaying rotations); a note-on throws the hammer at the reed
wherever it is (`key.contact`: a ringing reed is met where it swings, the hammer starting at the
lowest the strike point can reach); the damper's felt is on whenever the key is up and the pedal
isn't down; a voice sleeps under 1 nm. All 64 reeds share the plate, so their capacitance changes
sum (`Render.dc_f`). MIDI notes 33-96 are the keys; the velocity law (`spec.hammer_speed`: the
Rhodes' form through the Pie-finger layers' fitted speeds at velocities 40 / 80 / 115,
provisional) gives 1.7-4.8 m/s, a 9.2 dB span. The keyboard runs ~0.2x real time on single notes,
~1.1x on the demo's chords (Python).

**The damper** (`key.System(damped=True)`): a dashpot at 0.6 of the free length (provisional),
its value per key solved so the fundamental decays as the Pie-finger short notes do after the
key's release (`scripts/wurlitzer_register_fit.py --measure` -> `reports/wurlitzer/registers/
damper.json`): -267 / -997 / -518 dB/s, the median per octave 2 / 4 / 6 (quartiles -331 / -227,
-1264 / -423, -882 / -376). **G#6-B6 ring on at every velocity** (0.8-1.5 s), so keys 60-64 have
no damper (C7 unrecorded, taken as G#6-B6; whether the 200A's action has none there is still to
check, WZ0). The keyboard's dampers land within 12% of the recording (model / real median 0.99,
0.88, 0.98 per octave).

**Into the circuit** (`varimu/wurlitzer/circuit.py`): `in` = -V0 dC / c_reeds_f (the reeds'
current through CREEDS, V0 the drawing's 150 V); `transfer()` measures the small-signal response
from `in` to the AUX jack (a 240-tone multisine, cached in `cache/wurlitzer/`). **The AUX path is
linear for this:** on real strikes the circuit's harmonics match the input filtered by that
response within 0.1 dB down to -78 dB re the note (its own distortion appears at ~-98 dB), and
draft-1x agrees with production to -53 dB. So the fit runs on the transfer (seconds per
evaluation) and the full circuit checks the result.

**The fit** (`scripts/wurlitzer_register_fit.py --fit`; the config's `registers` block): least
squares (soft L1, 6 dB) on six keys per recorded octave x three layers: harmonics 2-5 re the
fundamental (where the recording holds them above -60 dB), each layer's fundamental re the middle
layer's, each key's re octave 4. Three parametrizations were tried (their records in
`reports/wurlitzer/registers/`):
- voicing and hammer mass at the octaves' centres (`fit_3anchors.json`): 9.3 dB rms, the levels
  across octaves 6.2 dB rms off. The recording's treble sits 10-26 dB under octave 4 at every key
  and its bass rises ~8 dB across octave 2; the reed's own physics drops the model 13 dB across
  octave 6, which a line through three centres can't undo;
- both at the octaves' ends (`fit_6anchors.json`): 8.2 dB, but the levels 9.7 dB off and the
  hammer jumping 2.6x within an octave (C6 2.1 g, B6 0.8 g): absorbing single keys' scatter, and
  the bass voiced at 2.8 mm with 9 mm swings, far past the field map's 6 mm edge, where the map is
  held flat (a kink that makes odd harmonics);
- **adopted:** the voicing (a 200A is voiced reed by reed) and **the slot's overlap along the
  reed** at the octaves' ends, the hammer at the octaves' centres (a construction value, smooth),
  three layer speeds, a penalty for leaving the map: **5.97 dB rms** (stopped by hand after 19
  iterations gaining < 0.05 dB each). Voicing 1.29 / 1.14 / 0.94 / 0.83 / 1.07 / 0.84 mm at keys
  4 / 15 / 28 / 39 / 52 / 63; overlap 22.8 / 22.4 / 6.0 (held) / 21.1 / 2.4 / 1.8 mm; hammer 0.85 /
  1.00 (held) / 0.59 g; layer speeds 2.37 / 3.12 / 4.47 m/s. The reeds' standing capacitance is
  then 54.9 pF (the circuit's `c_reeds_f`, was 31).

**The overlap is a stand-in, not geometry.** A longer slot raises a register's level without
changing its capacitance per metre, so it separated level from bark; but the fit uses it for bark
too (a longer slot averages in the reed's root-ward part, which swings less), and the values
(1.8 mm in the treble, 23 mm on a 60 mm bass reed, 6 against 21 mm within octave 4) aren't a
plausible comb plate. What they say: the treble couples to the plate ~10 dB less, the bass ~6 dB
more, than octave 4's geometry gives. The real cause (the slot's depth, the side gap, the reed
bar's stagger setting where each tip sits, a weaker treble hammer stroke) needs the pickup's real
geometry per register (WZ0) or a second recording; until then the levels are right and the
mechanism is labelled.

**The check** (`scripts/wurlitzer_register_fit.py --check` -> `reports/wurlitzer/registers/
{README.md, summary.json, audio/}`): all 36 recorded keys x 3 layers by MIDI velocity through the
keyboard and the full circuit at production (6.1x real time):

| Octave | H2-H5 rms (mean) | layer levels rms | level re octave 4, model - real | decay rms (0.2-1.15 s) | damper, model / real |
|---|---|---|---|---|---|
| 2 | 9.4 dB (-1.5) | 2.7 dB | +1.4 dB | 3.0 dB/s | 0.99 |
| 4 | 8.6 dB (-0.2) | 1.0 dB | 0 (reference) | 3.8 dB/s | 0.88 |
| 6 | 9.3 dB (+1.7) | 1.3 dB | -3.6 dB | 6.0 dB/s | 0.98 |

(WZ1's single voicing: 13.2 dB on the harmonics of 9 keys at the bare plate.) The harmonics' rms
is mostly per-key scatter (a basement piano: neighbours differ by 10-20 dB in one harmonic), with
no bias over 2 dB. **The bass blooms**, as the recording's does: a reed swinging deep into the
pickup's nonlinearity sends its fundamental's energy into the bark and gets it back as it decays,
so over 0.2-1.15 s the fundamental rises at hard strikes (C2 high: model +2.1, recording +5.2
dB/s; F#2 high +2.5 / +9.8), weaker in the model. (Over the whole long note the recording's bass
decays -2 to -3 dB/s: the reed's own Q, which the model takes from it.) Pitch: every reed at
equal temperament (A = 440; the Pie-finger unit sits ~+5 cents: the wear dial's). Absolute level:
the demo's loudest 300 ms (A1 and A2 together at velocity 127) reach 0.64 V rms at the AUX jack,
~4 dB over the drawing's "approx .4 V AC" maximum; the recording's own gain is unknown.
`audio/ab_octave{2,4,6}.wav` play three keys' mid notes per octave, the recording then the model,
each at -23 LUFS.

**The render** (`scripts/wurlitzer_render.py (--midi F | --demo) [--quality production|draft-1x]
[--set ...]` -> `reports/wurlitzer/renders/<name>_{aux,speakers,reeds}.wav`): the AUX jack (0 dBFS
= 1 V), the speaker terminals (two 16 ohm resistors until WZ5, 0 dBFS = 20 V) and the reeds' input
(0 dBFS = 4 V). The demo (18 s: Am7-D9-G9-Cmaj7 comping soft to hard with the pedal, a run, A1 +
A2 at 127): keyboard 20 s, circuit 141 s at production (7.7x), draft-1x ~0.7x.

**The done-when holds:** pitch and decay across the keyboard are plausible (above) and a MIDI
file renders, both outputs.

**Open (WZ3):** the overlap's real cause (above); the velocity law's layer velocities
(40 / 80 / 115, provisional: the set's three hand-struck levels) and so its 9.2 dB span; the bass's
bloom weaker than the recording's; the field map's 6 mm range against bass swings (the shield at
8 mm, both provisional); octaves 1, 3, 5 interpolated (unrecorded); the damper's place on the reed
(0.6, provisional); the user listens (`audio/ab_octave*.wav`, `renders/demo_aux.wav`).

**Next:** WZ4, the reeds as a keyed medium in circuitsim (the compiled component, the part in
both builders, the app's `wurlitzer_200a` with OUTPUT); WZ5 the speakers.

## Status (2026-11-20, third session): WZ4 built, AUX live (branch `wurlitzer`, merged to main 2026-11-21)

**The component** `WURLI_REEDS@1` (kind `ep_reeds`; `varimu/wurlitzer/compile.py`,
`scripts/compile_wurlitzer_reeds.py [--check]`, ~12 s; `config/components/wurli_reeds/1.yaml`
pinning `1.reeds.json`, 1.3 MB, by sha256): per key the free and damped systems' complex modes
halved as the Rhodes harp's (strike point, tip, the slot's 8 Gauss heights), the free system's
**reach rows** (the hammer thrown at a ringing reed starts where `key.contact` starts it: the
free reed is proportional, so each kept mode is one real mode and the bound is exact), the
damper's transfers (none for keys 60-64), the hammer, the voicing, the slot's weights and the
key's capacitance at rest; once, each blank's field map as the reference's cubic spline in
piecewise-polynomial form, the velocity law and every reed's standing capacitance (54.9 pF).

**The medium** `crates/circuitsim/src/wurli.rs` on `keyed.rs` (the harp's machinery; IR element
`WurliReeds`, `Medium::Wurli`): every voice renders its dC ahead, one way (the reed doesn't hear
the plate: WZ1's pull < 0.003 cents); the medium **senses the plate** `pk` after each step and
drives its node with `-V dC / C_r`, so the part's capacitor C_r from that node to the plate
carries `-d((C_r + dC) V)/dt`, the reeds' current exactly with V a step late. Against the Python
keyboard (`tests/test_wurlitzer_compiled.py`: strikes, a re-strike of a ringing reed, the pedal,
releases, an undamped key; internal dC at 2x / 4x): **-149 dB**, the same bit for bit on any
number of worker threads. Python: `circuitsim.wurli_render`.

**The part** `wurli_reeds: [plate]` (component, rate_hz, contact_rate_hz) in both builders: the
medium V<NAME> and the capacitor C<NAME> of the model's `standing_f`; Rust's equal bit for bit
(`crates/varimu-circuit/tests/agreement.rs`; the fixtures keep its model once, as a harp's); its
KiCad / editor symbol `WurliReeds`.

**The live circuit** `config/circuits/wurlitzer_200a_live.yaml`, GENERATED by
`scripts/make_wurlitzer_200a_live.py [--check]` from the stock file (which keeps the test input
`in`, WZ3's renders and fits): the reeds on `pk` in CREEDS' place; the reeds at the **96 kHz
step** (`reeds_rate_hz`: the reference's 2x makes no audible difference, -137 dB below 20 kHz
on 22 keys at velocity 127, and costs twice; the contact still 384 kHz); **OUTPUT** as the switch
`speakers` (0 AUX, the default here; 1 SPEAKERS), `out` a readout drawing no current (a VCCS
into 1 ohm) of the AUX jack (volts) or the terminals at 1/5; full scale 4 V (the WZ3 demo's AUX
peaks at 2.33 V: 1 V clipped; the drawing's "approx .4 V AC" maximum is ~12 dB under the model's
loudest, WZ3's open level). **The power amplifier is built only with SPEAKERS** (its section's
`when: [speakers]`; its input network C8 / C9 / R27 stays as the volume wiper's load; with AUX a
6 kOhm drain per rail stands in for its 3.75 mA idle so the rails hold): **AUX without it moves
-55 dB rms, +0.009 dB in level** (a loud chord at volume 1; -81 dB on a mezzo chord at 0.8), the
measurement this plan asked for; whether AUX may drop it is still the user's call. A flip of
OUTPUT restarts a live stream.

**Against WZ3's path** (`tests/test_wurlitzer_live.py`, production): the live circuit and the
keyboard's dC into the stock circuit driven with the plate's own voltage, `-V(t) dC / C_r`:
**-72.6 dB**. WZ3's stand-in (V held at 150 V) is -60 dB from both: the plate swings ~0.2% on a
chord, which the medium now gets right. Draft-1x against draft-1x: -57 dB (the draft's own floor).

**The app's** `wurlitzer_200a` (Instruments, after the Suitcase; draft-2x; panel VOLUME,
VIBRATO, "Output: SPEAKERS (off: AUX OUT)"; `crates/varimu-app/tests/live.rs`
`the_wurlitzer_plays_from_note_events`). **Live load** (`examples/play.rs --strike-all 127
--restrike 2 --mute`, this desktop, another session's pytest running alongside):

| Output | idle | every key ringing (mean / worst block) | dropouts |
|---|---|---|---|
| AUX | 44% | 72-73% / 98-139% | **0 at 50 ms and 20 ms** (30 s each); 3 in 15 s at 10 ms |
| SPEAKERS | 163% | 167% / 212% | hundreds at any buffer |

The cost is the circuit, not the keys: the electronics were 1.63x real time idle at draft-2x, the
power amplifier 24 of part 0's 71 states and 16 of its 33 ports (DK grows with their square);
`dk_sparse` gains only 1.16x. Cutting the amplifier onto threads of its own failed both ways tried
(the keys' medium must stay in part 0, so the amplifier's part owns every shared node: no DC path
at the volume wiper; volume with it diverges at the preamp's feedback node x).

**The done-when** holds for AUX (every key ringing, no dropouts at 20 ms; the user's keyboard
and acceptance still to come); **not for SPEAKERS live**. Production renders and takes render
either output.

**Open (WZ4):** SPEAKERS live, the user's options: (a) the amplifier as a reduced live circuit
(`panel::Device::live_circuit`, the API 550A's route), measured against the discrete one at
production (its crossover distortion, 2.5% at 10 mW, goes unless the reduction keeps it); (b)
draft-1x for SPEAKERS (0.86x idle: still over with the keys, unmeasured); (c) SPEAKERS only
rendered behind (takes at production), AUX live; (d) wait for WZ5's speaker, whose readout costs
more again. Also the user's: the default output (AUX here), a buffer (20 ms works, 10 ms
marginal), AUX without the amplifier (-55 dB), playing it from a keyboard.

### After the user's first try (same session): the vibrato, a crackle, the preamp

The user: "the vibrato doesn't seem to do anything", and "crackling when I play loud, is it
clipping?". Three findings, all fixed (merged to main with WZ4, 2026-11-21):

**The crackle: the reeds ran off their field maps.** Struck at velocity 127, the bass and
low-middle reeds (A1-E3) swing to 7.0 mm from the plate's mid-plane (velocity 100: 5.9 mm); the
maps stopped at 6 mm (`numerics.swing_m`, sized when "a bass reed struck hard swings ~4 mm"),
where c(z) was held: a kink in the current twice a cycle for 5-92 ms after each hard strike
(the slope there still 6% of its peak), a buzz ~-30 dB under the note. The maps now reach 7.5 mm
(the reed's surface just short of the 8 mm shield; `pickup.mesh` caps its fine band at the
shield and refuses a swing that reaches it); inside the old range they moved < 2e-7 of their
peak, so WZ3's fits and every on-map render stand; no key leaves the map at 127.
`WURLI_REEDS@2`, the live circuit pinned to it. Not clipping: draft against production on a loud
passage is -43.7 dB with the same high-frequency content, and the interface was never driven
past full scale, but 4 V left only 0.3 dB on ten keys at 127 with the pedal (the preamp's
compression bounds the peak at ~3.9 V): **full scale 6 V** now (3.7 dB of headroom; SPEAKERS
reads the terminals at 0.3, 20 V at 0 dBFS), so live playing is 3.5 dB quieter.

**The vibrato: the VTL5C2 stand-in was ~30x too conductive.** At this circuit's LED drive its cell
ran 0.4-1 kOhm, nothing beside the 50K VIBRATO pot: the knob did nothing until fully clockwise
(0.9 dB p-p at half, 9.2 at full), where the preamp's gain (1 + R10 / Z) jumped +23 dB; the
Pie-finger set (36 keys, low velocity) changes -1.5 dB (quartiles -2.1 / 0.0; the set is
unprocessed, not normalized). **LG-1 is now its own component** `LG1_200A@2`
(`scripts/fit_wurlitzer_lg1.py [--write] [--knob-law]`): the VTL5C2@2's LED and cell with the
cell's conductance / k (geometry) and its dynamics s times faster (the steady state unchanged),
k, s and R17 fitted to VIBRATO full's depth, level and envelope shape: **5.28 dB p-p, -0.60 dB,
H2 -13.7 dB** against the set's 6.22, -1.50, -13.8 (k 6.27; s ~43, above ~20 it stops mattering:
the cell follows the LED; R17 at its full 4.7K; the cell 12.6-68 kOhm). Both depth and level
together are out of this cell's reach (its swing 5.4x); a third LED / cell parameter (the light
law's knee) is the option if the last dB matters. The knob law (steady tone): 0.25 -> 1.0 dB p-p,
0.5 -> 1.8, 0.75 -> 2.7, 0.9 -> 3.7, 1 -> 5.3; the level dips ~2.4 dB mid-travel (the pot's
loading). Through `Live`: off 0.18, half 1.9, full 5.2 dB (`the_wurlitzer_vibrato_modulates_live`).
`LG1_200A@1` was the same fit on the preamp as WZ2 had it (below); nothing pins it.

**The preamp: R5, D1 and C2 go to ground, not to x.** With the scaled cell VIBRATO throbbed: 0.35
V p-p of 5.5 Hz at AUX with no note (the old stand-in 78 mV, masked), because TR-1's emitter
returned through R5 to x and its DC ran through the cell. On the sharp scan the net of R5, D1 and
C2 stops at R5's corner, joined neither to x nor to a ground symbol (WZ2 read it as x); ground
is what the drawing's printed voltages fit (the model idles at b1 2.72 / e1 2.17 / e2 3.68 / c2
8.92 V against 2.45 / 1.95 / 3.4 / 8.8; on x: 3.21 / 2.66 / 4.33 / 7.85) and what the recording
says (its 5.7 Hz content ~-54 dB re a note, the same with VIBRATO off). D1 is a clamp on the base,
C2 an RF shunt. No throb now (0.23 mV p-p, as off); the preamp has +2.2 dB of gain at VIBRATO off
(R5 now shunts x at audio: a uniform level, which WZ3's fit doesn't see, its levels relative).
Sources README updated. Live load with every key ringing at VIBRATO full: ~77% mean, 0 dropouts
at 20 ms (20 s). Stale: `reports/wurlitzer/amp/` (WZ2's study, before both changes).

## Reference: the Pie-finger set (2026-11-20)

The user added `real instrument samples/Pie-finger Wurlitzer 200A sample set/` (untracked, never
commit; no license stated, so analysis only). Surveyed once by throwaway scripts outside the repo
(onset, pitch near f0 at 0.15-0.65 s, harmonics re the fundamental, the fundamental's decay in a
band, the vibrato's envelope); nothing in the repo changed but this section.

**What it is** (its `.txt`): a real 200A, serial 104774L, "recorded direct into Scarlett 6i6 (2nd
gen)", "no processing added". 287 mono files, **48 kHz / 24-bit** (the txt says 96 kHz; the files
are 48). Only octaves 2, 4 and 6 (C2-B2, C4-B4, C6-B6: 36 of the 64 keys; "Octaves 1, 3, 5
available by request from u/Loom237"):
- short notes and long notes at three velocities (low, mid, high: not calibrated, struck by hand,
  "success was only moderate"); the long notes end with the key's release and a short fade;
- long notes at low velocity with VIBRATO full;
- long notes at mid velocity with VIBRATO full and the sustain pedal down.

The owner's caveat: the piano spent six years in a basement, "variance in note ring time, some
buzzing, noise". The jack it was recorded from (AUX OUTPUT or headphones) isn't stated, so it is
the **AUX OUT reference**; there is no recording through the speakers.

**What it shows:**
- **The vibrato: 5.74 Hz on every note** (5.72-5.78 Hz on the shortest), the manual's "preset to a
  frequency of 5.75 cycles per second" exactly; at full depth **~6 dB peak to peak** (5.8-6.5 dB),
  the same at low and mid velocity and in every register. WZ2's oscillator and LG-1 have a target
  for both.
- **Tuning:** every note **+3 to +10 cents** (median ~+5): the piano tuned to about A = 441 Hz,
  with a per-key spread that is a realistic detune pattern for the wear dial.
- **Decay of the fundamental** (the long notes; low / mid / high velocity alike within ~1 dB/s):

  | Octave | dB/s |
  |---|---|
  | 2 (65-124 Hz) | -0.5 to -6 (bass reeds ring 6-10 s) |
  | 4 (262-495 Hz) | -8 to -20 |
  | 6 (1.05-1.98 kHz) | -20 to -52 |

  Per-key outliers (D4 -13 against its neighbours' -8, G6 -50) are the instrument's own; the fit
  per key uses them as they are, the dial for "duds" explains them.
- **The bark against velocity** (harmonics 2-5 re the fundamental, 0.15-0.65 s in):
  - octave 2: low velocity mostly -5 to -20 dB; high velocity **+6 to +15 dB** (the harmonics
    louder than the fundamental), so strong nonlinearity at the pickup; the 4th and 6th
    harmonics are often weak while the 3rd and 5th are strong (a pattern from the cutout's
    geometry or the strike point, a test for WZ1's map);
  - octave 4: the 2nd harmonic -6 to -20 dB at high velocity, -10 to -40 at low;
  - octave 6: nearly sinusoidal, the 2nd harmonic -21 to -45 dB at any velocity;
  - the spectrum within 60 dB of its peak in the first 100 ms reaches ~2-3 kHz at low velocity
    and ~4-8 kHz at high.
- **The dampers** (short notes, the peak to -40 dB): 0.1-0.35 s in octaves 2 and 4, 0.1-0.2 s in
  octave 6 up to G6; **G#6, A6, A#6 and B6 ring on (0.8-1.3 s)** as if undamped. Whether the
  200A's top keys have no dampers is to check (WZ0: the action's photos or the parts diagram).
- **Noise:** mains hum at 60 Hz ~-95 dBFS and 120 Hz ~-95 dBFS in the tails (the recording's gain
  is unknown, so only relative to the notes: hum ~75-80 dB under a struck note's peak); some tails
  carry other reeds' lines (an 82 Hz line in C2's tail: E2 sympathetic, or a buzz).
- **Onsets are trimmed tight** (2-20 ms before the strike): no noise floor before the notes.

**What it is good for, and not:**
- Good: pitch, decay per key, the bark's growth with velocity, the attack, the damper's stop
  time, the vibrato's rate, depth and shape, the pedal's undamped ring, the AUX path's tone.
- Not: absolute level (the interface's gain is unknown) or a velocity law in MIDI terms (three
  hand-struck levels); the speakers; octaves 1, 3, 5; a healthy instrument (every miss against
  it may be the basement's, so the model's nominal unit should be judged on trends, the worn
  unit's dials on the outliers).
- **Worth asking for:** octaves 1, 3 and 5 from u/Loom237, and which jack it was recorded from.

**The attacks (a first look, inconclusive):** short-window spectra of the first 12+ ms show
peaks away from the harmonics that fade by 0.3 s, but no clean second reed mode yet: in octave 4
they sit at half-integer ratios (likely the short window's leakage), and in octave 6 a peak at
**~2.02 kHz on every key from C6 to F#6** (and ~3.42 kHz from G6 to B6) stays put while f0
moves: a fixed resonance (the reed bar, the action's thump, the pickup's mounting), not a reed.
WZ1 should look again with a high-resolution method (matrix pencil / ESPRIT on the first ms):
the second mode's ratio to f0 would fix each reed's tip mass and so its length.

**Is it enough to build from (2026-11-20)?** Yes, for WZ1-WZ4 and their fits, as the Rhodes went
with jRhodes3d and the Suitcase with its schematic and one recording: the electronics are drawn,
the vibrato has an exact target, and the notes are unprocessed (jRhodes3d was EQ'd). What it can't
settle alone is the scale of the bark: with uncalibrated velocities and an unknown pickup, the
reed's swing and the pickup's gap trade off. One physical dimension of the pickup (photos with a
scale, a vendor's drawing, or Pfeifle and Muenster 2017) breaks that; the reed lengths matter
less (the attack's inharmonic content), and the second mode above may give them.

## The target

- **The instrument:** a Wurlitzer 200A (1974-83; the drawing's starting serial 102905), the
  "Wurly" of most 1970s records. 64 keys, A1 to C7.
- **Two outputs, both the instrument's own** (the user's call):
  - **SPEAKERS:** the 200A's power amplifier into its two 16 Ω 4" x 6" speakers in the case; the
    output is the sound pressure in front of the piano, as the 5E3's and the Suitcase's are.
  - **AUX OUT (no speaker):** the 200A's AUX OUTPUT jack, a buffered line output (TR-15 / TR-16,
    ~0.4 V AC at most) after the preamp, the vibrato and the main volume, before the power
    amplifier. It is how a 200A is recorded direct, and what a later chain can take (an amp, a
    Room view mic, a console).
- **What it shares with the Rhodes:** a struck, nearly linear resonator per key, read by a
  nonlinear pickup whose position sets the bark; the damper and pedal; a shared amplifier after
  all the keys. **What differs:** one reed per key instead of a tine and a tonebar, an
  electrostatic pickup instead of a magnetic one, and an amplifier that must be built (the 200A
  has no passive "Stage" version).

## How the 200A makes its sound

- **The reeds:** flat Sandvik steel cantilevers, five blanks across the keyboard (.020" thick and
  .155" / .129" wide in the bass, .032-.034" and .120-.097" from reed 21 up), screwed to a reed
  bar through an oversized hole and a dished washer, tuned by lead (solder) at the tip. Moving a
  reed forward in its hole drops it 2-5 cents.
- **The action:** a small London-style piano action (whips, butts, flys, dampers), regulated like a
  piano: the hammer (three-ply maple, felt-covered) starts 1 5/64" (27.4 mm) below the reed and
  lets off 1/8" (3.2 mm) from it. Wrong after touch makes it bobble and double strike, or block.
- **The pickup:** one comb-shaped plate held at about +150 V (the 200A's drawing; the 200's text
  says 160-170 V at the pickup, Pfeifle measured 130 V on his). Each reed is grounded through its
  screw and vibrates inside a cutout in the plate, so a reed and the plate are a capacitor whose
  value changes with the reed's position. A changing capacitance at a held voltage pushes a current
  i = V dC/dt into the plate's node.
- **The bark:** C(x) is strongly nonlinear near the cutout, so a hard strike's swing makes
  harmonics; the reed's rest position relative to the plate sets the even / odd balance. The
  service literature's voicing is exactly that: bend the pickup up or down, centre the reed
  sideways ("a reed at rest positioned inside the pickup" gives "a very strong undesirable
  harmonic"; off-centre sideways gives "an undesirable loud tone").
- **The plate's circuit:** +150 V from a very high-impedance supply (a half-wave rectifier and a
  56K / 8.2 MΩ / 1 MΩ / 22 MΩ / 1 MΩ ladder with three .33 µF capacitors) through 1 MΩ to the plate.
  The plate's signal reaches TR-1 through 22K and .022 µF; all 64 reeds' capacitances, the cable's
  and 220 pF at TR-1's base load it. So the pickup isn't a voltage source added on top: it is a
  current into a node the preamp, the supply and every other reed share.
- **The preamp:** TR-1 / TR-2, a two-stage direct-coupled amplifier with feedback on +15 V.
- **The vibrato** (a tremolo, despite the name): an oscillator (TR-3 / TR-4 with a twin-T-like RC
  network) lights the LED of LG-1, an LED / LDR pair; the LDR shunts the preamp's output to ground
  through the VIBRATO depth control. No rate control (the 200's was preset to 5.75 Hz; the 200A's
  rate comes out of its network).
- **The power amplifier:** a complementary BJT amplifier on ±22.5 V (input pair, a bias-control
  transistor, drivers, a PNP / NPN output pair with .47 Ω emitter resistors, 15K / 220 Ω feedback),
  into two 16 Ω speakers in parallel. The headphone jack swaps the speakers for an 8 Ω 5 W load.

## Why many notes at once are cheap (as for the Rhodes)

| Per key | Physics | Live cost |
|---|---|---|
| Reed | A cantilever with a lead tip mass; Pfeifle saw higher modes small even when played hard | ~3-5 two-pole resonators (fewer than a Rhodes key's ~10) |
| Hammer | Felt on maple, a hysteretic contact | Only during the ~1 ms of a strike |
| Damper | Felt on the reed when the key comes up | A coefficient change |
| Pickup | C(x, y) of the reed in its cutout, from an electrostatic field solve | One 2D table lookup and a derivative per sample |

Everything after the plate is shared: one preamp, one vibrato, one amplifier, as the Rhodes'
harp feeds one Stage. The cost is the circuit, not the number of keys. The Suitcase's power amp
(BJTs, five threads) runs live at ~0.8x; the 200A's amplifier is smaller.

## Two tiers from the same physics

As RHODES_PLAN.md's: the live tier is the same physics reduced, the production tier the reference
it is checked against.

| Part | Live (draft) | Production (offline) |
|---|---|---|
| Reed | Modes of the cantilever with its tip mass, computed once from the geometry | A time-domain beam with the large-deflection term (Pfeifle's), the reed bar's clamp |
| Hammer | A fitted hysteretic contact folded into the medium's port | Stulov's felt; the action's key-to-hammer mechanics |
| Pickup | A precomputed C(x, y) map (2D slices along the reed, as Pfeifle) | A 3D field solve; the electrostatic pull on the reed as a force (a negative spring: pitch and bark depend on the voicing) |
| Reed bar | Keys independent | Sympathetic coupling through the bar (its twist is what makes "duds") |
| Output | AUX live; SPEAKERS live through the speaker's readout or a fixed filter | Both at production, the speaker's readout in full |

## The model, part by part

### Reeds

- Beam FE as `varimu/rhodes/beam.py` and the Nickel Organ's brass cantilever (`varimu/nickel/bar.py`):
  the reed's free length, width and thickness, steel's constants, the lead tip as a lumped mass
  and rotary inertia.
- **The missing number is the reed's length per key.** The blanks' thicknesses and widths are
  published; lengths are cut to pitch. Two unknowns (length, lead mass) for one number (the
  pitch): fix the lengths from a source (a reed chart, measured reeds, photos with a scale, or
  Pfeifle and Muenster 2017), else a provisional rule (length per blank interpolated so the lead
  stays in the range a tuner can file) and fit the lead mass to the pitch. The tip mass sets the
  second mode's ratio, so it is audible in the attack: worth sourcing.
- Losses: the clamp (screw, dished washer, reed bar), the lead, air. Q per key from a real 200A's
  decays (WZ6), provisional until then.

### Hammer and action

- The regulation's numbers are the physical values: blow distance 1 5/64", let-off 1/8", key dip
  ~3/8", after touch ~1/32". A velocity law (key velocity to hammer speed) as the Rhodes' and the
  Clavinet's, fitted to a real 200A's loudness per MIDI velocity when one is in hand.
- The felt: Stulov's hysteretic model (Pfeifle's choice; also what INSTRUMENT_PLAN.md's piano needs,
  so it is a shared prerequisite built here first). The contact is inside the step, as the
  Rhodes' ("Contacts inside the solve").
- The strike point along the reed: provisional from photos, a condition dial later.

### Damper and pedal

- Damper felts on the reeds, the sustain pedal lifting the rail (MIDI CC 64), as the harp's.

### The pickup

- **The field map:** the plate's cutout around the reed's tip region, the reed as a grounded
  conductor, the plate at V. Laplace's equation in 2D slices along the reed (Pfeifle's method),
  then 3D for the production tier: the same kind of solve as the Rhodes' magnetostatic map
  (`varimu/rhodes/pickup.py`, `pickup3d.py`), with permittivity in place of permeability.
  C(x, y) for the reed's vertical swing x and sideways offset y; the voicing is the rest point.
- **The geometry is provisional until sourced:** the plate's thickness, the cutouts' width and
  depth, the reed-to-plate clearances per blank (photos, the service literature's feeler-gauge
  checks, Pfeifle and Muenster's Fig. 2-type drawings).
- **Coupling:** the medium senses the plate's node voltage (a sample late, as `reeds.rs` senses the
  Victorian voice's batteries: the plate is held by megohms and hundreds of picofarads, a slow
  node) and drives i = d(C V)/dt into it through a `G`-type current, with the reeds' static
  capacitance as an ordinary capacitor in the circuit. Then the plate's sag on a loud chord (the
  1 MΩ feed), the preamp's loading and the 220 pF at TR-1 all come out of the circuit.
- **The electrostatic force** on a reed, ½ V² dC/dx, is a soft negative spring: estimate it in WZ1
  (Pfeifle doesn't model it). If it moves the pitch by more than a cent, the live tier folds it
  into the reed's stiffness at rest and production carries it as a force, as the Rhodes' magnet.

### The electronics

One circuit file, `config/circuits/wurlitzer_200a.yaml`, from the 200A's schematic as drawn, the
mains included (one coupled simulation): the high-voltage polarizing supply, the low-voltage
supply and its +15 V regulator (IC-1, a 723-type: modelled from its transistors or as a macro,
WZ2's call), the reed bar preamp, the vibrato oscillator and LG-1, the volume controls, the
AUX output's buffer and the power amplifier.
- **Transistors:** Wurlitzer house numbers. Their JEDEC equivalents are WZ0's job; meanwhile
  stand-ins from the fitted BJTs (`2N5088@1` / `2N5087@1` for the small-signal ones,
  `2N3053@1`-class drivers, the Suitcase's `RCA29B@1` / `RCA30B@1` or `2N6254@1` class outputs),
  each marked provisional.
- **LG-1:** an LED / LDR pair, on the `opto` kind (`varimu/devices/opto.py`, the Suitcase's
  `VTL5C2@2`) with a provisional fit until LG-1's data are found (Vintage Vibe sells a
  replacement; its behaviour is published only qualitatively).
- **Checks:** idle voltages against the drawing's printed ones (most transistor nodes have one),
  the vibrato's rate and depth, the preamp's and amplifier's gain, clipping power, hum.

### The two outputs

- **SPEAKERS:**
  - a speaker component for Wurlitzer's 4" x 6" 16 Ω driver (202243): no datasheet expected, so a
    provisional fit (the G12M's route: a measured driver of the same class for the moving system),
    `series`-style parallel pair as two parts or one with a parallel count (whichever the
    `speaker` macro supports by then);
  - mounted in the 200A's case: its volume and openness to source (photos), `box_m3` if closed,
    a baffle otherwise; the output the pressure in front of the piano at the player's position or
    1 m (decision below);
  - live: the speaker's back wave in a section of its own (`speaker::readout_apart`, as the 5E3
    plays its speaker at draft-1x), or Play's fixed speaker filter as the Suitcase's "Hear the
    speakers" (`varimu_app::speaker_filter`) if the load doesn't allow it.
- **AUX OUT:**
  - the circuit's `out` at the AUX jack's 1K pot (the 200A's own aux level), with a realistic
    load (a line input, ~10 kΩ, provisional);
  - the power amplifier still runs in a real 200A when the AUX jack is used (the jack doesn't mute
    the speakers), but it only shares the unregulated rails with the +15 V regulator. Measure in
    WZ2 whether gating the power amplifier and speakers out (a section's `when:`, as the Minimoog's
    sources) changes the AUX signal measurably; if not, AUX plays without them live and the panel
    says so.
- **One device, a switch:** the app's `wurlitzer_200a` with an OUTPUT selector (SPEAKERS / AUX),
  a control in the circuit file, so takes and prints keep which output was heard. Production
  renders either. The headphone jack (the amp into 8 Ω and 470 Ω) is a third option later, if
  wanted.

## How it fits the code (a proposal)

- **The reference:** `varimu/wurlitzer/` in Python (outside the render cache key, like
  `varimu/rhodes/`): the reed beams, the hammer, the field map, a key's strike, the keyboard over
  events; `config/wurlitzer/200a.yaml` for the instrument's numbers.
- **The component:** the reeds compiled offline (kind e.g. `ep_reeds`: per key the modes, the
  strike and pickup rows, the damper; once for all keys the C(x, y) map, the velocity law, the
  clearances), pinned by version like `MK1_HARP@N` (`scripts/compile_wurlitzer_reeds.py [--check]`).
- **The medium:** circuitsim's `wurli.rs` on the generic `keyed.rs` (as the harp and the Clavinet's
  strings), sensing the plate node and driving its current; a part `wurli_reeds: [plate]` in both
  builders; SPICE holds the current at 0 as for the other media.
- **The app:** a keyed device (MIDI, touch, takes, renders behind) with OUTPUT and VIBRATO /
  VOLUME on its panel.

## Condition dials (realistic first, then bend)

Each one is a physical condition, realistic by default (most come straight from the service
literature's faults):
- **voicing:** the pickup bent up or down (1/32"-1/16" per the manual), mellow to all bark;
- **a reed off-centre** in its slot (the "extra loud or harsh" note);
- **the polarizing voltage:** aged filter capacitors and a weak rectifier drop it (Pfeifle's 130 V
  against 170 V): quieter, less bark, more hiss relative;
- **worn hammer felt** (harder, brighter attacks) and **packed damper felt** (notes that don't stop);
- **a dirty reed head** ("lose the ground, you will lose the volume"): a resistance and a damping
  in the reed's clamp;
- **duds:** a twisted reed bar, short ringers;
- **a lop-sided lead tip:** a torsion mode joins in;
- **a tired LDR:** less vibrato depth;
- **per-instrument variation** through seeded draws (every 200A a different one), as the
  Clavinet's wear.

## Proposed milestones (a recommendation, not decided)

1. **WZ0: sources.** Trace the 200A's schematic completely into the README (every value, the
   volume wiring, the AUX output's connections); find the house numbers' JEDEC equivalents; the
   reed lengths per key; the pickup's geometry; the speaker and the case; Pfeifle and Muenster 2017;
   a per-note recording set of a real 200A (DI from AUX and through its speakers). Done when: the
   README has a source or a marked provisional for every value WZ1-WZ2 need.
2. **WZ1: one reed, offline in Python.** The beam with its tip, the felt hammer from the
   regulation's blow distance, the 2D field map, the plate's circuit linearized as a load. Done
   when: the reed's pitch comes out within the lead's tuning range, the bark grows with velocity,
   moving the rest point inside the cutout gives the strong harmonic the service guide describes,
   and the electrostatic force's pitch shift is measured.
3. **WZ2: the electronics.** `config/circuits/wurlitzer_200a.yaml` with a test input in place of
   the reeds (an audio input into the plate node through the reeds' capacitance); its profile
   (`varimu unit --circuit wurlitzer_200a`: idle voltages vs the drawing's, gain, the vibrato's
   rate and depth, THD and clipping power, hum); `tests/test_wurlitzer_200a.py`. Done when: it idles
   within tolerance of the printed voltages and both outputs are measured.
4. **WZ3: the keyboard in Python.** All 64 reeds, the damper and pedal, the velocity law, into the
   circuit (`scripts/wurlitzer_render.py (--midi F | --demo)` -> `reports/wurlitzer/renders/`, both
   outputs). Done when: pitch and decay across the keyboard are plausible and a MIDI file renders.
5. **WZ4: live.** The compiled component, the medium in circuitsim against the Python reference
   within a tested bound, the part in both builders, the app's `wurlitzer_200a` with OUTPUT.
   Done when: it plays from a MIDI keyboard with every key ringing, AUX and SPEAKERS each without
   dropouts at a buffer the user accepts (measured with `examples/play.rs`).
6. **WZ5: the speakers.** The 4" x 6" driver and the case, live and at production. Done when: the
   SPEAKERS output plays live (readout or fixed filter) and production renders the full speaker.
7. **WZ6: against a real 200A.** Single notes per velocity and per register, DI and acoustic: the
   decays, the bark against velocity, the attack, the vibrato. Refit what misses (the
   Rhodes' jRhodes3d step). Done when: the user has heard it against the reference and the
   measured gaps are written down.
8. **WZ7: the production tier and the condition dials.**

## Decisions (the user's, 2026-11-20)

- **The 200A**, not the 200.
- **Both outputs:** the speakers and no speaker (the AUX output).

## Open decisions (the user's)

- **The reference recordings:** the Pie-finger set (above) covers AUX OUT for octaves 2, 4 and 6.
  Open: asking its owner for octaves 1, 3, 5 and the jack; a recording through the speakers; which
  songs it should sound like.
- **The default output live** (AUX is the cheaper; SPEAKERS is the instrument as played in a room).
- **Where the SPEAKERS output listens:** the player's position (the speakers face the player) or
  1 m in front of the piano.
- **Whether AUX live may drop the power amplifier** if WZ2 shows it doesn't change the signal.
- **The headphone jack** as a third output.
- **Where the track goes** relative to the other work in progress.
