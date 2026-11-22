# An imperfect Rhodes: what to listen to

docs/RHODES_IMPERFECTION_PLAN.md has the model and every number. The WAVs here are generated (not
committed): rerun the scripts named below to get them back.

## `audio/amount_*`: the Suitcase at IMPERFECTION 0 / 1 / 2 / 5 / 10

`scripts/rhodes_imperfection_demo.py --render --amounts 0 1 2 5 10`: one phrase
(`audio/phrase.mid`) through the whole Suitcase (`rhodes_suitcase_100w`, draft, the speakers'
pressure, stereo, unit 1), each file matched to -23 LUFS. `amount_0` is the default instrument
exactly; `amount_1` a real, played Mark I; `amount_2` a neglected one; `amount_5` badly out of
shape; `amount_10` a wreck. `*_harp.wav` is the harp's own EMF (no amp, no vibrato), easier to
hear the differences in.

| Time | What | Listen for |
|---|---|---|
| 0.2-3.4 s | C4 eight times at velocity 80 | at 0 every strike the same; higher, each a little (or, at 10, a lot) louder or softer, brighter or duller |
| 3.8-6.6 s | one chord four times | the same, on four keys |
| 7.0-13.3 s | chromatic run C3-C5, all at velocity 80 | key to key: level, timbre (voicing), attack, pitch; at 10 some keys nearly dead, some ringing on |
| 13.9-16.6 s | staccato chords | how each key stops: some ring on, some cut short |
| 17.4 s on | the pedalled progression of `rhodes_render.py --demo` | chords beating (2 cents rms at 1, 37 at 10), uneven sustain |

## `audio/sympathy_*`: SYMPATHY off / 1 / 5 / 30

`scripts/rhodes_imperfection_demo.py --render --sympathy 1 5 30`: a phrase built for it
(`audio/phrase_sympathy.mid`), IMPERFECTION 0, each file matched to -23 LUFS:

| Time | What | Listen for |
|---|---|---|
| 0.1-3.6 s | the pedal down, C2 struck hard and let go | the other keys' halo under the note as it rings |
| 4.0-8.5 s | the pedal down: a C major chord, then a melody over it | the halo thickening, the melody's notes ringing on in the other keys |
| 9.0-12 s | the same, the pedal up | nothing rings but the held keys: the difference is the pedal |

`sympathy_0` is off (the default instrument). `*_harp.wav` is the harp's EMF, `*_rail_part.wav`
the rail's part alone (the EMF on minus off) at the `_harp` file's gain: what SYMPATHY adds.

## `rail/`: the first, offline rail study (superseded)

`scripts/rhodes_rail_study.py` (the rail with the pickups still, a key feeling its own push):
kept as the record of why the live version differs (the plan's "Second round"). Its thump and
its loud sympathetic ring were the two artifacts the live version removed.
