# Did She Mention My Name: a 1968 Lightfoot-style mix, with and without the 4-track

2026-11-11, made unattended (the user's ask: "mix the song like an actual Gordon Lightfoot song
and we'll see what it sounds like processed through the 4 track"). An early run of
HEADLESS_MIX_PLAN.md's H3 without H0 (no headless session render yet): the mixdown is a
script, the devices are the app's own prints.

## The files

| File | What |
|---|---|
| `mix_through_4track.wav` | the four stems recorded on the Ampex 300-4 (Scotch 202, 15 ips, crosstalk, hiss, flutter), then mixed |
| `mix_no_tape.wav` | the same mix moves on the stems as they are (no tape) |
| `tape/tape1..4.wav` | the four tape tracks as the deck plays them back (1 bass, 2 guitar, 3 lead vocal, 4 harmonies) |
| `match.json` | the two mixes' gains to one loudness (Hard rules: loudness lies) |

Both mixes are at the same integrated loudness, so an A/B between them hears tape, not level.
Each mix's every number (faders, rides, the plate's return, the insert prints) is in
`cache/lightfoot_mix/<dry|tape>/mix.json` and `inserts.json`.

## The signal flow (as a 1968 New York mixdown)

Stems -> the 4-track (one pass, all four tracks at once; your assignment) -> the console's
inserts per track -> faders, pans, vocal rides -> a post-fader echo send into a stereo EMT 140
plate -> the stereo mix. No mix-bus compression and no limiter (Lightfoot's records of the
period aren't squashed); the level is set by loudness only.

All inserts at production quality, printed by `varimu-app`'s `examples/print.rs` (the app's
print, cached in `cache/lightfoot_mix/prints/`). Script: `scripts/lightfoot_mix.py`
(`--version dry|tape`, `--stage match`); probes `scripts/lightfoot_mix_probe.py`,
`scripts/lightfoot_mix_analyze.py`.

## What the stems measured, and each move

Measured on the session's lanes (the mid of each stem, at 48 kHz: what goes to tape).

| Track | Measured | Move | Its effect, measured |
|---|---|---|---|
| Bass | round, even: 100 Hz the top third-octave, 500 Hz ~27 dB under; loudness range 5 LU | none; fader 7 LU under the lead; centre | already even, no leveler needed |
| Guitar | boomy: 100 Hz third-octave 25 dB over 1 kHz, 30 over 2.5 kHz; ~6 dB over the bass at 100 Hz in a first mix | **Pultec EQP-1A**: LOW 100 cps ATTEN 10, HIGH 4 kcs BOOST 8, BANDWIDTH 8 (broad) | -16.5 dB at 100 Hz, -8 at 400 Hz, +6.7 at 4 kHz, all re 1 kHz: the bass owns the bottom, the guitar sparkles; fader 3.5 LU under the lead; panned half left |
| Lead vocal | baritone (160 Hz top), crest 18.5 dB, uncompressed | **EQP-1A**: LOW 100 cps ATTEN 5, HIGH 8 kcs BOOST 5, BANDWIDTH 7 -> **Fairchild 670**, TIME CONSTANT 2, factory threshold, input +12 dB over the lane's level | EQ: -1.4 dB below 400 Hz, +4.4 at 4 kHz, +5.5 at 6.3 kHz (presence); the 670: median 3 dB of gain reduction in the loudest chorus, 4.6 at the 90th percentile, 6 at most; centre |
| Harmonies | sing 23 % of the song, mostly a 3rd-6th over the lead, brighter than it | **Fairchild 670**, TC 2, input +6 dB | median 1.9 dB gain reduction, 3.9 at p90; fader 5 LU under the lead; panned half right |

**Vocal rides** (a hand on the fader): the lead's 3 s loudness held near its median excess over
the guitar and bass, at most +-3 dB, moving over about a second, held between phrases. In the
draft they span -2.4 to +2.6 dB (5th to 95th percentile).

**Echo**: a post-fader send (lead 1.0, harmonies 1.3, guitar 0.25, bass 0) into the EMT 140
plate (`plate_reverb`, STEREO on: the 140 TS's two pickups), DECAY 2.2 s at 500 Hz, its return
11 LU under the dry lead: an audible tail behind the voice, not a wash.

**Pans**: three-way-ish, as late-60s stereo: bass and lead centre, guitar half left, harmonies
half right, the plate's two pickups spread.

## The mix's measured balance (dry, draft quality)

Third-octave long-term spectrum of the mix's mid, re its loudest band: 100 Hz -0.9, 160 Hz 0,
250 Hz -6, 1 kHz -10, 2.5 kHz -8, 4 kHz -13, 10 kHz -14, 16 kHz -28 dB. L/R correlation 0.92.

## What isn't period, or isn't there

- The faders are set by measured loudness, not by ear; the rides by a rule.
- No echo chamber (the plan's H2): the EMT 140 stands in (New York studios had both).
- Nothing on the mix bus (a 670 or the 351-2 there is possible later).
- Lightfoot's original arrangement had strings and a band; the stems are four parts.

## Results

**The print.** `examples/tape_print.rs` on `sessions/did she mention my name (tape)` (157.1 s,
six 30 s pieces at once, the GPU tape kernel): 10,656 s, 67.8x real time, key
`ac920f357bea810159b3d7990261aa61`; the session now plays its tape tracks (the deck's print is
saved in it: open it in the app and the four tracks play from tape).

**What the tape did** (`scripts/lightfoot_tape_effect.py` -> `tape_effect.json`, each tape
track against its lane):

| Track | Level | Response re 1 kHz (31 Hz - 6.3 kHz) | Above 6 kHz | Not a linear filter |
|---|---|---|---|---|
| Bass | -1.2 dB | -1.8 to +1.1 dB | +6 to +12 dB (hiss: the bass has nothing there) | -17 dB |
| Guitar | -0.8 dB | -1.7 to +1.0 dB | flat | -19 dB |
| Lead vocal | -0.8 dB | -1.5 to +1.2 dB | -1.2 dB at 16 kHz | -12 dB |
| Harmonies | -0.6 dB | -0.3 to +2.0 dB | -1.1 dB at 16 kHz | -8 dB (hiss in its long silences) |

"Not a linear filter" is the share of the tape track no fixed EQ explains (hiss, flutter,
distortion together), from coherence. Where the harmonies are silent (107 s of the song) their
track sits at -72.6 dBFS rms, 44 dB under their singing: mostly hiss, a trace of the lead's
crosstalk from track 3 next door (coherence 0.15). Lags read by cross-correlation (bass 36
samples, voices 7-8) are the tape's low-end phase, not a delay; the tracks are mixed as the
deck plays them.

**The mixes.** The tape version needed the same moves within a dB: the insert trims +0.6 to
+1.2 dB (each tape track's level loss, so the 670s compress the same), the faders within 1.4
dB, the rides -2.3 to +2.6 dB, the plate's return -13.4 dB (no tape: -13.4). Matched at
-20.9 LUFS: `mix_no_tape.wav` peaks at -2.6 dBFS, `mix_through_4track.wav` at -1.1. The tape
mix's higher peaks are guitar attacks (33.03 s, 92.36 s, the same moments in both), the tape's
low-end phase reshaping the attack before the guitar's big EQ, not a click (the raw tape track
there peaks 0.5 dB under its lane, with smaller steps and the same content above 8 kHz).

Tape mix against no-tape mix, third-octaves re 1 kHz: 63 Hz -1.0, 160 Hz -0.9, 2.5 kHz +0.6,
4 kHz +0.9, 10 kHz -0.4, 16 kHz -1.3 dB. So tonally the deck is a faint loudness-curve tilt;
the rest of the difference is the tape's texture (hiss, flutter, saturation, crosstalk).

**Times:** the print 2 h 58 min; each mix at production ~45-55 min (the 670 prints ~15-18x real
time, the EQP-1A ~5.5x, the plate ~14x, run in parallel with the print).

## For the next pass

- **The user's first listen (2026-11-11):** the voice's reverb far too much and too bright;
  harsh around 6 kHz (the "s" region). And on the tape tracks a ~5.4 kHz chirp on each bass
  note, an artifact (PERIOD_GEAR_BACKLOG.md's status has the measurements and the suspected
  bias alias); the tape mix waits on its fix.

- The user listens: `mix_through_4track.wav` vs `mix_no_tape.wav` (matched), and the mix
  itself (balance, the vocal's compression, the plate's amount, the pans).
- Moves are one line each in `scripts/lightfoot_mix.py`'s `MOVES`; a remix re-uses the cached
  prints of every chain it doesn't change (`--stage mix` re-runs only faders, rides and the plate).
