# AM3: distance to an era, step 1 (the statistics distance)

2026-11-13, `scripts/era_distance.py` -> `summary.json`. Corpus: the 1960s tracks (1-6) of the
user's Lightfoot compilation, 1146 windows of 2 s (20 minutes: under the doc's 30, so the
**diagonal** Fréchet distance is the one used; the shrunk full covariance is in the JSON).
Features: 338 texture statistics per window on 32 ERB envelopes (mono), z-scored by the corpus.

## The checks

| Check | Result |
|---|---|
| A. floor: odd tracks vs even tracks | 36.7 |
| B. held-out 1960s tracks vs the rest (median) | 87.0 |
| B. 1970s tracks vs the 1960s corpus (median) | 85.2 |
| B. later tracks (1978-93) vs the corpus (median) | 126.4 |
| C. cover plain, low-passed at 10 kHz (delta) | +0.8 [+0.6, +1.0] |
| C. cover plain, +6 dB shelf below 150 Hz (delta) | +27.7 [+26.5, +28.9] |

- **The features don't tell Lightfoot's 1960s from his 1970s** (held-out 87 vs 85); they do
  tell both from his later records (126). So this distance measures roughly "the analog era of
  this artist" and not "the 1960s". The strongest 1960s marker AM1 found, the stereo picture, is
  not among these mono features. Adding inter-channel coherence per band is the obvious next
  feature (cheap). A learned embedding is step 2, the user's decision.
- The band limit at 10 kHz barely moves it (the corpus's own edge is ~12.7 kHz, and the
  features are envelope statistics that weight the top octave little); a bass shelf moves it a lot.

## The cover

Distance to the corpus (diagonal; the floor is ~37, held-out tracks ~87):

| Version | D | delta vs plain | 95% interval |
|---|---|---|---|
| plain (four lanes, faders and pans) | 214.9 | 0 | |
| 1968-style mix, no tape | 109.7 | -105.2 | [-116.9, -93.1] |
| 1968-style mix through the 4-track | 117.7 | -97.2 | [-110.1, -86.7] |
| **4-track vs no tape** (paired) | | **+8.0** | [+0.2, +10.5] |

- The mix (EQ, the 670s, the plate, balance) moves the cover most of the way: from far outside
  the corpus (215) to the distance of a held-out Lightfoot track (110 vs 87).
- **The 4-track moves it slightly *away*** (+8, the interval just clear of 0). Which features do
  it isn't decomposed yet (the per-feature contributions to the mean term are the way in).
  With AM1's reading (the 1960s tracks have a steady hiss and a 12.7 kHz top), one pass of
  clean 15 ips tape isn't the missing piece. AM4's generations are the next thing to score here.
