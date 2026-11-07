# The Minimoog Model D from its schematics

Started 2026-11-07 (the user: "let's start building this"), in the worktree `minimoog` beside the
Rhodes session (merged after; builds at 3 cargo jobs, below-normal priority, so the other session
keeps its cores). Sources: [data/schematics/minimoog/README.md](../data/schematics/minimoog/README.md).

## Aim

The Model D as one coupled circuit from its service manual: three VCOs (the uA726 expo
converters), the mixer, the ladder filter, two contour generators, the VCA, the keyboard's
sample-and-hold and the +-10 V supply, all on our BJT model, played live from a MIDI keyboard
like the tube synth. Like every device here, the hardware's values are the anchors
(Folkman's adjustment procedures are the calibration), and bending comes after.

## Choices (made at the start; the user can overrule)

- **The unit:** the 204D manual's "new" oscillator board (serial 10175 and above, the octave
  buffer) and its filter board; the 2022 reissue keeps that signal path.
- **The TIS97** (the ladder and output amp) has no card: the 2N3904 (the sheet's alternate
  for the TIS92) stands in, as the TIS93 is the 2N3906. `2N3904@1`, `2N3906@1` from Central's
  cards (numbers cited, as the 2N5087).
- **Order:** the filter first (the instrument's signature and the best-documented part), then
  the VCA, the oscillators, the contours, the panel and supply.

## Milestones

- **MM0, sources** (done 2026-11-07): the 204D service manual's schematics (Internet Archive)
  read; Folkman's adjustment procedures; Huovilainen's DAFx-04 analysis.
- **MM1, the VCF** (circuit No. 6): `config/circuits/minimoog_vcf.yaml` with ideal +-10 V and a
  test fixture for the panel's control summing. Done when:
  - it idles at the bias the drawing implies (the string, the output amp) and passes the
    pre-flight checks;
  - Folkman's three procedures can be carried out on it (`scripts/minimoog_vcf_trim.py`):
    REGEN CAL (regeneration starts between EMPHASIS 7 and 8 at CUTOFF -1), RANGE (EMPHASIS 10
    oscillates at 440 Hz), SCALE (tracks the keyboard over three octaves);
  - its response is a 4-pole low-pass (-24 dB / octave above the cutoff) with resonance
    rising with EMPHASIS, and its overdrive matches the ladder's tanh-per-stage behaviour
    (Huovilainen) qualitatively;
  - it plays in varimu-app (the test oscillator into it, keys to the keyboard CV), with its
    load measured.
- **MM2, the VCA** (circuit No. 7) and the output, appended to the filter.
- **MM3, the oscillators** (board No. 1, Fig 9-2): the uA726 as a heated matched pair (its
  temperature regulation as a thermal node, the B6 heater's pattern), the integrator and its
  reset (a hybrid exception if the reset is far faster than a sample: HYBRID_PHYSICS_PLAN.md),
  the triangle / rectangular shapers, the octave buffer (board 6) and the -5 V reference;
  Folkman's oscillator tuning procedure as the trim.
- **MM4, the contours and the keyboard** (board No. 2, Fig 9-7): two contour generators, the
  keyboard's current source and sample-and-hold, glide.
- **MM5, the whole voice:** the mixer, noise (board 3), the front panel's wiring (Fig 9-16 /
  9-17: the control node's real summing, replacing MM1's fixture), the +-10 V regulators;
  the app's `minimoog` device with a partition measured for real time.
- **MM6, bending:** after the user has played it (realistic first).

## Status (2026-11-07)

MM0 done. **MM1 built; open: the user plays it.**
- `config/circuits/minimoog_vcf.yaml` idles at the drawing's bias (the string's 1.96 V at the
  input pair, the top emitters 7.30 V); pre-flight now counts a BJT's junctions as DC paths.
- Folkman's procedures by `scripts/minimoog_vcf_trim.py --write`: REGEN CAL 0.847
  (regeneration starts at EMPHASIS 7.5, ~467 Hz), RANGE 0.307 (EMPHASIS 10 at 440 Hz, keyboard
  off; the trim's working span 270-1710 Hz, below ~0.1 the reference current is gone), SCALE
  0.466 (440 / 877 / 1761 / 3525 Hz over three octaves). His Scale loop leans on the low A's
  own keyboard volts, which the fixture puts at 0 V, so the script solves for the loop's end
  state (two octaves between the A keys, the low A at 440 Hz).
- `scripts/minimoog_vcf_study.py`: 24 dB / octave above the cutoff (-65.8 dB at 4.06 kHz,
  -89.1 at 8.25 kHz); a high-pass near 35 Hz from the drawing's C27 10 uF into ~470 ohm;
  EMPHASIS takes the passband down as the peak grows (gain 19.5 -> 9.3 at EMPHASIS 5).
  Overdrive at 110 Hz: 0.5 % THD at 5 mV peak, 5 % at 50 mV, 12 % at 100 mV, 29 % at 200 mV
  (gain 50 -> 23): softer than one tanh(V / 2 Vt) stage at 50-100 mV (the stages and the
  output amp shape it; not chased).
- `tests/test_minimoog_vcf.py` (5 tests); varimu-circuit builds its IR as Python does.
- varimu-app's `minimoog_vcf` (the test oscillator into it, the keys on its keyboard input,
  the mod wheel on the cutoff fixture), Newton 1e-5 (the expo converter): **0.59x real time
  at draft-1x** on a 110 Hz saw at EMPHASIS 6, 6 of 938 blocks over (worst 1.41x), measured
  while the Rhodes session ran (`examples/load_profile.rs`).
- Fixtures until later milestones: the panel's summing (CUTOFF as volts through 100K,
  KEYBOARD CONTROL 1 / 2 as 300K / 150K by inference), the keyboard (0 V at the low A, MIDI 45
  provisional), AMOUNT OF CONTOUR at 0, ideal +-10 V, the mixer as an ideal source.

**MM2 built (2026-11-07): the VCA**, in the same file, renamed
`config/circuits/minimoog_filter_board.yaml` (the app's `minimoog_filter_board`; the VCF's
measurements read `o7`, the filter's output). Values checked against the manual's Table 7-8,
which corrected the reading in places (R67 200 at the string's foot, R12 100 ohm, R40 2.2K vs the
drawing's 22K, R54 470), and R2 82K is in series into the VCA, not a load to ground (MM1's file
had it wrong; the load is the same, the trims held).
- `scripts/minimoog_vca_trim.py --write`: Folkman's VCA Balance read as nulling the EXT.
  LOUDNESS feedthrough (his jumper puts audio on a control line), measured quasi-statically
  (the output's DC shift for EXT. LOUDNESS 4 -> 8 V): 2ND VCA BAL 0.710 (key up), 1ST VCA BAL
  0.618 (key held); untrimmed, hundreds of mV; trimmed, 2.3 mV key up, ~0 held.
- Gain over the contour (220 Hz, 50 mV into the filter): -96 dB at 0 V (shut), -21.7 at 0.5 V,
  -10.3 at 1 V, -2.8 at 2 V, ~0 to +1 dB from 3 V, where the output tops out at ~5.6 V pp (Q17's
  collector idles at 3.1 V, CR2 clamps it at -0.6 V). A contour step 0 -> 5 V with no audio
  thumps 109 mV at the MAIN OUTPUT (attack 0; the contour generators will round it, MM4).
- `tests/test_minimoog_vca.py` (3 tests) with the VCF's 5 on the new file.
- Live: one solve ran 1.22x real time at draft-1x; the VCA now runs as a partition (its own
  ideal rails, the contour's R59 / Q18 on the filter's side so the control input stays in the
  first part; the cut at Q18's collector and Q16's base: a cut at Q18's base diverged), coupled
  **hold** (`panel::Device::coupling`; fixed 2026-11-07 after the user's first note: a key's
  gate steps Q18's current across the cut in one sample, and extrapolated it overshot and
  Newton failed in the VCA at key-down; the load measurement fed no gate, so it hadn't shown):
  **0.71x, 33 of 938 blocks over** (was 0.89x extrapolated). Hold vs the one solve on gated
  220 Hz saws: -57 dB at EMPHASIS 0, -52 dB at 0.9 (the cut's one host sample of lag removed);
  `scripts/minimoog_gate_check.py` runs gated notes through the partitioned draft.
- The contour input is the keys' gate (0 / 5 V, provisional) until MM4.

**MM3 started (2026-11-07): oscillator 1 read** (the sources README, "Oscillator board No. 1").
Nothing built. What it needs, in order (each a prerequisite inside this plan, the user's rule):
1. **The uA726** as a component: a matched NPN pair at the die's regulated 78.4 C (the drawing's
   mark; the BJT model's `temp_c`), first static; its heater loop (a thermal node, B6's pattern)
   later if the drift is wanted (it is the 726's character: units from date codes 7850 / 7907
   wouldn't hold tune).
2. **The LM393** as a comparator: the `opamp` macro with its clamp at the output swing and an
   open-collector pull-up, or a part of its own (its datasheet's gain, slew, output stage).
3. **The E112** reset JFET: no card yet (InterFET / Siliconix N-channel switch); the 2N3819 card
   stands in until one is found.
4. **The reset** (~1 us, from IC8B through C9 100 pF / R33 2K): far below a sample at 48-96 kHz.
   Offline, production's error control can subdivide it; live it is HYBRID_PHYSICS_PLAN.md's
   case (the 884's M1 island or K event kernels), generated from a full-physics reference of this
   core.
5. Then `config/circuits/minimoog_vco.yaml` (one oscillator), Folkman's tuning procedure (p. 12:
   Range trimpot for 3520 Hz at the high "A", Scale trimpot for 440 Hz at the low "A"), the
   waveshapes against the sheet's levels (+-1.75 V ramp, -2.5 V = 15 % pulse), then three
   oscillators and the octave buffer (board 6).

## CPU while another session runs

`CARGO_BUILD_JOBS=3`, builds started with `cmd /c start /belownormal /wait /b ...`; one render
at a time; `OPENBLAS_NUM_THREADS=1` for numpy-heavy scripts.
