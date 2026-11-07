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

MM0 done. MM1 in progress: the circuit is drawn from Fig 9-11; the trims and checks follow.

## CPU while another session runs

`CARGO_BUILD_JOBS=3`, builds started with `cmd /c start /belownormal /wait /b ...`; one render
at a time; `OPENBLAS_NUM_THREADS=1` for numpy-heavy scripts.
