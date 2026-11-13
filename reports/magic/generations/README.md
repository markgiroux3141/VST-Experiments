# AM4: tape generations

2026-11-13, `scripts/tape_generations.py` -> `summary.json`, `generations.png`, `audio/`.
The literal Ampex 351, aligned (`align_351.py`'s alignment, SCOTCH111@3, 15 ips), printed
four times in a row. Between generations the gain is reset to unity: +0.42 dB, measured on
the 400 Hz tone at 0 VU, the same for every generation, as an engineer lining up the next
machine would. Each print has its own grain and transport draw (noise seed = the generation).
The prints took 5.9 hours. Generation 1 shared the GPU's tape kernel with AM5 and took 236 min;
generations 2-4 took 28-30 min each.

Two signals: a test signal (400 Hz and 1 kHz at 0 VU, six tones at -20 dB, 3150 Hz for
flutter, 4 s of silence) and 20 s of the cover's plain mix (from 40 s, at 0 VU rms).

## The test signal

| Generation | THD 400 Hz | THD 1 kHz | S/N (50 Hz-15 kHz) | wow | flutter | 50 Hz | 100 Hz | 5 kHz | 15 kHz |
|---|---|---|---|---|---|---|---|---|---|
| G0 (source) | 0 | 0 | (digital) | 0 | 0 | 0 | 0 | 0 | 0 |
| G1 | 1.31 % | 1.73 % | 56.7 dB | 0.091 % | 0.007 % | -0.46 | +0.16 | +1.00 | -1.27 |
| G2 | 2.58 % | 3.56 % | 54.1 dB | 0.163 % | 0.013 % | -0.89 | +0.28 | +2.09 | -2.57 |
| G3 | 3.81 % | 5.46 % | 53.1 dB | 0.222 % | 0.019 % | -1.25 | +0.47 | +3.08 | -3.76 |
| G4 | 4.93 % | 7.37 % | 52.7 dB | 0.310 % | 0.028 % | -1.63 | +0.73 | +4.11 | -5.03 |

Response in dB re 1 kHz, at -20 dB re 0 VU.

- **The distortion adds in amplitude, not in power.** THD grows almost linearly with N (1.31 %
  x 4 = 5.2 %, measured 4.9 %). The same machine bends the same waveform the same way each time,
  so each generation's harmonics land in phase with the last's. Uncorrelated distortion would
  give 2.6 % at G4. By G4 a 0 VU tone carries 5-7 % THD. That is the "pushed" sound of a fourth
  generation, with no stage driven any harder than its alignment.
- **The noise grows more slowly than 10 log10 N.** The rule of thumb predicts 53.7 / 51.9 / 50.7
  dB at G2 / G3 / G4. Measured: 54.1 / 53.1 / 52.7. Each later generation's high-frequency loss
  filters the earlier generations' hiss, which is mostly treble. By G4 the first generation's
  hiss is 5 dB down at 15 kHz.
- **The response errors multiply, as they should.** Per generation: -0.4 dB at 50 Hz, +0.15 at
  100 Hz (the head bump), +1.0 dB at 5 kHz, -1.3 dB at 15 kHz. G1 is within the 351's ±2 dB
  spec. By G4 the machine has a +4 dB presence rise around 5 kHz and a -5 dB top octave.
  The 5 kHz rise is the record EQ against the provisional heads' contour (TAPE_PLAN.md "Gaps"),
  so its size is only as good as those heads. The direction (a bright mid-top over a dull top)
  is the textbook generation-loss signature.
- **Wow grows faster than sqrt(N)** (0.091 -> 0.310 %, about N^0.9; independent random wow
  would give 0.18 % at G4). The transport's capstan and reel components are periodic, so
  successive generations' wow partly adds in phase. Flutter is small at every generation
  (0.03 % at G4).

## The program

`difference.levels(G0, Gk)` on the 20 s excerpt, dB re the output:

| | G1 | G2 | G3 | G4 |
|---|---|---|---|---|
| all | -7.6 | -3.2 | -1.1 | -0.2 |
| tone | -8.2 | -3.8 | -1.7 | -0.9 |
| character | -16.7 | -13.1 | -10.9 | -9.3 |

The "all" and "tone" rows are dominated by the accumulated time base. These were not dewarped,
and by G4 the wow alone decorrelates the top end. "Character" is the right row to read: about
+2 to +3 dB per generation. Asymmetry falls (peak ratio 0.64 -> 0.37 dB) as the tape's
symmetric curve reshapes the peaks. Comodulation stays at 0.25-0.26. Floor-follow falls a
little (slope 0.23 -> 0.17): the added hiss doesn't follow the signal.

**The bounce** (`bounce_*.wav`): the rhythm lanes (bass and guitar) printed separately, summed
and printed again, against their sum printed once. Their difference is -16.7 dB of character
re the output, the same as one generation's (G1's -16.7). A bounce costs the bounced parts
about one generation. This comparison doesn't separate how much of it is intermodulation from
summing before the second print.

## Distance to the 1960s (AM3's measure)

`era_distance.py --variants cover_G1 cover_G2 cover_G4 --baseline cover_G0` (mono, through the
opus 160 codec; added to `reports/magic/era/summary.json`):

| | delta vs G0 | 95 % interval |
|---|---|---|
| G1 | **-17.2** | [-24.8, -13.3] |
| G2 | **-27.3** | [-37.8, -21.8] |
| G4 | **-37.0** | [-50.0, -26.8] |

For scale: AM3's floor (odd vs even 1960s tracks) is 36.7. The plain cover sits at 215. The
1968-style mix moved it -105. A +6 dB low shelf moves it +28.

- **Generations do move the cover toward the era**, and every interval is clear of 0. The
  steps shrink: -17, then -10, then about -5 per generation. The first copy matters most.
- **This contradicts AM3's single pass, which moved away (+8).** The comparisons differ. AM3 put
  the whole 1968-style mix through the Ampex 300-4 deck on Scotch 202. Here the plain cover goes
  through the 351 on 111, at 0 VU rms, in a 20 s excerpt. The 20 s excerpt explains the wide
  intervals. Which difference flips the sign isn't measured. The likeliest is the program: the
  1968-style mix has already taken the steps the tape takes here (a dull top, compressed peaks).
- **The mix is the bigger lever.** Four generations move the plain cover a third as far as the
  1968-style mix did. Tape copies are a garnish on the arrangement and the balance, not a
  substitute.

## Listening (yours)

`audio/`, LUFS-matched:
- `cover_G0.wav`, `cover_G1.wav`, `cover_G2.wav`, `cover_G4.wav`: the same 20 s, 0 / 1 / 2 / 4
  generations;
- `bounce_summed_once.wav` against `bounce_each_then_again.wav`.

## Limits

One machine and one tape for every generation. A real chain would mix machines (a 4-track
master, a 2-track mixdown, a cutting master), each aligned to its own tape. The heads are
provisional, which matters most for the 5 kHz rise. The gain between generations is set once,
at 400 Hz. An engineer would also realign each machine to its reel, which is not modelled.
The excerpt is 20 s.
