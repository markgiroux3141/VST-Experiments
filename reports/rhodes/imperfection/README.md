# An imperfect Rhodes: what to listen to

docs/RHODES_IMPERFECTION_PLAN.md has the model and every number. The WAVs here are generated (not
committed): rerun the scripts named below to get them back.

## `audio/`: the Suitcase at IMPERFECTION 0 / 1 / 2

`scripts/rhodes_imperfection_demo.py --render`: one phrase (`audio/phrase.mid`) through the whole
Suitcase (`rhodes_suitcase_100w`, draft, the speakers' pressure, stereo, unit 1), each file matched
to -23 LUFS. `amount_0` is today's harp exactly; `amount_1` a real, played Mark I; `amount_2` a
neglected one. `*_harp.wav` is the harp's own EMF (no amp, no vibrato), easier to hear the
differences in.

| Time | What | Listen for |
|---|---|---|
| 0.2-3.4 s | C4 eight times at velocity 80 | at 0 every strike the same; at 1 / 2 each a little louder or softer, brighter or duller |
| 3.8-6.6 s | one chord four times | the same, on four keys |
| 7.0-13.3 s | chromatic run C3-C5, all at velocity 80 | key to key: level, timbre (voicing), attack, pitch |
| 13.9-16.6 s | staccato chords | how each key stops: some ring on a little, some cut short |
| 17.4 s on | the pedalled progression of `rhodes_render.py --demo` | chords beating slightly (2 cents rms at 1), uneven sustain |

## `rail/`: the tone bar rail (offline study, not in the instrument)

`scripts/rhodes_rail_study.py`: the harp's EMF on a rigid rail and on a moving plywood rail
(`varimu/rhodes/rail.py`), at three rail stiffnesses (`ei_x1`, `ei_x4`, `ei_x16`). Each pair
(`*_rigid.wav`, `*_rail.wav`) shares one gain; `*_sympathetic.wav` is only the keys never struck,
at that gain.

- `thump_*`: F1, E2, A2 alone at velocity 120, pedal up: the attack's low thud on the rail.
- `pedal_*`: the demo's pedalled chords: the sympathetic ring of the other 60-odd keys.

The rail's values are unsourced, and its thump doesn't match the real piano's register pattern
(summary.json; the plan's table), so it isn't adopted: these are to hear what it would add.
