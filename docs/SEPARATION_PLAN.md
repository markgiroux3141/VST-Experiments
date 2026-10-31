# Track separation: diverging tracks through physical recording chains

Brainstormed 2026-10-31 with the user. **Status (2026-10-31): the cheap first experiment is
built** (below, "A cheap first experiment"). Nothing else is scheduled. The user's
decision on undoing a recorded chain: not needed for now; they'll record as clean as
possible.

## The question

In professional recordings each track usually went through its own chain: a different
microphone, distance, room, preamp, compressor and tape pass. That makes tracks easier to
tell apart in the mix, and EQ is only part of it. Psychoacoustic cues do much of the work.
The user's idea: simulate those chains physically, as everything else in the project is,
and **diverge** two tracks by giving them opposite settings. A/B tests then show which
settings make tracks seem most different.

## What separates tracks: the ear's grouping cues

The ear sorts sound into streams by a few cues (Bregman, *Auditory Scene Analysis*, 1990).
Each cue has a physical cause in a recording chain:

| Cue | What the ear does | Physical cause in a session |
|---|---|---|
| **Common fate** | Partials that move together (AM / FM) are grouped | Each overdub had its own tape record pass, with independent wow and flutter; different rooms; drift |
| **Onset and transient shape** | Sharp onsets come forward, smeared ones sit back | Diaphragm mass (ribbon, condenser, dynamic); mic distance (early reflections smear the attack); compressor attack |
| **Distance** | Near vs far | Proximity effect, direct-to-reverberant ratio, air absorption of HF, the early-reflection comb. **These work in mono.** |
| **Spectral region** | Masking | Capsule resonances, transformer LF / HF corners, the mic loaded by the preamp's input impedance (EQ is the crude version) |
| **Harmonic texture** | Different distortion signatures read as different objects | Transformer saturation (odd, LF, level dependent), triode (2nd), clean |
| **Space** | Direction and width | Stereo placement and decorrelation; binaural unmasking (up to ~10-15 dB at low frequencies, provisional: model knowledge, the binaural masking level difference). **Needs stereo.** |

Two observations:

- **Common fate is underrated, and it's nearly free.** Tracks printed through tape with
  independently seeded flutter (TAPE_PLAN.md's v(t), one record pass per overdub)
  decorrelate in a way no EQ can.
- **Distance cues work in mono**, which matters while the project stays mono.

## Physical models it suggests

Each is a component or medium in the project's usual way: sourced values, the one coupled
simulation, two implementations with an agreement test.

1. **Microphones as components** (COMPONENT_EDITOR_PLAN.md already lists a microphone and
   a room as later components).
   - *Ribbon* (the best first one): a corrugated aluminium ribbon (mass, compliance) in a
     magnet gap, velocity in and EMF out, into a high-ratio step-up transformer on our JA
     cores (LF saturation included). Proximity effect follows from the physics: a
     pressure-gradient capsule at distance r boosts the bass by about √(1 + 1/(kr)²).
   - *Condenser*: diaphragm tension and mass, the backplate's air damping, the capsule
     resonance near 10 kHz, then a tube impedance converter and an output transformer.
   - *Dynamic*: diaphragm and coil, the coil's inductance against the preamp's input.
   - Mic, cable and preamp go in **one netlist**. Loading a ribbon or dynamic mic with
     different preamps changes its response, and that is a big part of why "mic X into
     preamp Y" sounds the way it does.
2. **Preamps.** The V76 (DEVICE_CANDIDATES.md, B10) is already queued; a second preamp with
   a very different input transformer and topology would give the contrast.
3. **A room as a medium**, like the plate (REVERB_PLAN.md): image-source early reflections
   and a diffuse tail from the room's dimensions and wall absorption, with the source and
   the mic placed in it. Mic distance then sets direct-to-reverberant ratio, onset smear and
   HF loss together, as a real room does.
4. **Tape flutter per pass.** TAPE_PLAN.md's v(t) (capstan, reels, scrape flutter) with a
   seed per track's record pass.
5. **Stereo**, later: the strongest cue (binaural unmasking), but a project-wide change from
   the mono convention.

**Caveat: recorded stems already carry their own mic and room.** Mic emulation on them is
re-amping. The tube synth's DI tracks have no acoustic chain at all, so their separation is
entirely up to us; and the 5E3's speaker (C3) already outputs sound pressure at 1 m, a
mic's input. Synth and amp tracks are the cleanest test bed.

## Diverging (and converging) two tracks

Opposed axes, each a physical setting pushed in opposite directions for the two tracks:

| Axis | Track A | Track B |
|---|---|---|
| Distance | Near: proximity, dry, full transients | Far: room, HF air loss, smeared onset |
| Transducer | Ribbon: dark, soft transients | Small condenser: bright, fast |
| Electronics | Transformer-heavy (odd, LF) | Triode (2nd) or clean |
| Dynamics | Fast-attack compression (pushed back) | Slow attack (punch forward) |
| Time stability | Flutter, its own seed | Stable, or another seed |
| Room | Small and bright | Large and dark |

Run the same axes the other way and you get **glue**: one shared tape pass, one shared
reverb, bus compression. The tool could be one control from *diverge* to *converge*.

Everything stays physical (the genome rule): the settings are mic type, distance, angle,
room dimensions, absorption, preamp and tape pass, never "separation" knobs.

## Testing separation, not preference

- **Loudness matching per track.** A louder track sounds more separated, so each track's
  loudness *within the mix* is matched, not only the whole mix's (the hard rule "Loudness
  lies", extended).
- **A masked-threshold staircase** (the measure): lower the target track inside the mix until
  the user can no longer tell whether one of its notes changed (ABX style; Phase 5 has a
  staircase). The threshold's shift in dB is the separation an axis buys ("independent
  flutter: +2 dB, near / far: +4 dB"): a number per effect, not "seems clearer".
- **A model pre-screen** before listening: a glimpse proportion (the share of
  time-frequency cells where the target dominates the rest by more than 3 dB; Cooke, JASA
  2006) or partial loudness (Moore, Glasberg and Baer, 1997). It ranks candidate chain pairs
  so the user only listens to the promising ones.
- Large differences are the point here, so this doesn't conflict with the rule that
  subtle differences count as verified: the staircase shows quickly whether an axis is
  worth keeping.

Where it lives: the native app's Session view (tracks with print-cached chains as inserts,
SESSION_FX_PLAN.md), plus a separation-test mode. Nothing goes into the web app.

## A cheap first experiment

Two synth tracks that mask each other, three axes that are nearly buildable now:

1. The existing devices as contrasting chains: the 670, the EQP-1A, the 5E3 through its
   speaker.
2. A flutter-only model: a time-varying delay from capstan physics, ahead of TAPE_PLAN.md's
   full transport.
3. A basic image-source room for near / far (mono).

The staircase on each axis says which ones earn full models (mics, a real room, stereo)
before we invest in them.

**Built (2026-10-31).** Prototypes outside the netlist and the render cache key, in
`varimu/separation/` (tests: `tests/test_separation.py`):

- `phrases`: the tube synth played from note lists (the app's gate levels and measured
  tuning at HIGH), at draft, noise off, cached in `cache/separation/synth/`.
- `flutter`: one record pass's speed error s(t) from a capstan, a pinch roller, a reel,
  motor hunting, random LF wander and scrape flutter (shares assumed, total scaled to the
  351's 0.11% rms), applied as a time-varying delay (Kaiser-windowed sinc). A pass running
  fast plays back flat. Two seeds = two passes on one machine: the rotations keep their
  rates at random phases, the random parts are independent.
- `room`: a shoebox's impulse response, omni source to omni mic: image sources (Allen and
  Berkley) for 80 ms per octave band (walls' sqrt(1 - alpha), 1 / 4 pi r, ISO 9613-1 air),
  then a diffuse tail per band at Eyring's RT60 from the image sources' energy, the bands
  recombined by zero-phase complementary weights. Rooms: `home` (5 x 4 x 2.6 m, RT60
  0.36-0.62 s), `booth` (0.06-0.32 s), `hall` (14 x 10 x 6 m, ~1.4-1.7 s mid). Near is
  0.3 m (direct-to-reverberant +5.7 dB in the home room), far 2.45 m (-10.8 dB).
- `metrics`: per-track loudness matching (BS.1770, -23 LUFS each, before mixing) and the
  glimpse proportion (Cooke 2006: 20 ms frames on 48 ERB bands, the target's cells within
  50 dB of its loudest that beat the rest by 3 dB).

`scripts/separation_study.py` renders the target melody, the same melody with one note
changed (D4 -> E4 at beat 4) and an arpeggio masker (A3-G4, one patch), runs them through
the conditions (devices: the 670, the EQP-1A at a boost / cut setting, the 5E3 and speaker,
each same-on-both and crossed; flutter: shared pass, independent passes, target or masker
only, independent at 4x; room: near / far combinations in the home room, booth against
hall) and writes `reports/separation/summary.json`: per condition the glimpse proportion at
the target -6 dB under the masker and the **energetic separation** (dB the target can drop
and keep the dry pair's proportion at -6 dB). Audio per condition (each track at -23 LUFS,
and a demo mix at -6 dB) goes to `cache/separation/conditions/<name>/`.

`scripts/separation_listen.py` is the staircase (needs `--with sounddevice`): three mixes
of an excerpt around the changed note, one with the changed note; pick the odd one;
2-down 1-up (70.7%), steps 6 / 4 / 2 dB, 8 reversals, the threshold the mean of the last 6;
conditions in a random order; results to `data/judgments/separation/` (never committed).
A lower threshold = more separated.

**The pre-screen's results (2026-10-31; `reports/separation/summary.json`).** Energetic
separation in dB against the dry pair (positive = the target holds its glimpses lower
under the masker). "All cells" counts every cell the processed target fills; "notes' cells"
only those where the dry target was. The first run showed why the second is needed: a
target in the hall scored +5.5 dB on all cells, all of it the reverb's tail between notes
(-0.2 dB on the notes' cells).

| Condition | All cells | Notes' cells |
|---|---|---|
| Same chain on both (670, EQP-1A) | +0.1 / +1.2 | 0.0 / +0.2 |
| Same chain on both (5E3) | -4.5 | -0.5 |
| Target 670, masker EQP-1A | +2.9 | +2.8 |
| Target EQP-1A, masker 670 | -1.1 | -2.2 |
| Target 5E3, masker 670 / EQP-1A | +13.3 / +18.9 | +10.0 / +13.5 |
| Masker 5E3, target 670 / EQP-1A | -2.3 / -2.2 | -2.5 / -3.3 |
| Flutter (any: shared, independent, one side, 4x) | -0.1 to +0.1 | -0.04 to +0.06 |
| Room: both near / both far | -2.4 / -3.1 | -3.6 / -5.4 |
| Room: target near, masker far / the reverse | -1.2 / -3.1 | -1.8 / -5.9 |
| Room: target booth, masker hall / the reverse | -3.6 / +5.5 | -3.7 / -0.2 |

What it says:
- **The same chain on both tracks separates nothing**, as expected: divergence is what counts.
- **Brightness and distortion separate energetically, a lot, and in one direction.** The
  5E3 and its speaker move the synth's spectral centroid from 439 Hz to 1.3 kHz; the
  brightened track stands out, and a brightened masker covers more. The EQP-1A's setting
  (LF boost and cut, 5 kHz boost, 10 kHz cut) darkens the line (centroid 367 Hz): the
  undarkened track gains ~2.8 dB.
- **The 670 barely worked**: at the factory adjustment and -12 dBFS peak in, its gain moved
  by ~1 dB over the phrase (a fixed -7 dB otherwise). A compression contrast needs a
  hotter threshold (a rerun of 670 renders).
- **Flutter is invisible to the energetic measure** (as designed: it moves no energy) and
  **every room costs energy** (reverb fills the gaps); whether they separate is the
  staircase's question. Distance is the interesting case: the energetic cost of putting
  the masker far (-1.8 dB) against whatever grouping benefit the ear finds.

`separation_listen.py`'s default list follows from this: dry; T670_Meqp1a and T5e3_M670
(does the energetic number match the ear?); flutter shared, independent, independent at
4x; room both near, target near and masker far.

Listening results: pending (the user's).

## Open decisions (the user's)

- A track of its own, or folded into SESSION_FX_PLAN.md?
- Test on the synth tracks first, or on the Cambridge-MT stems?
- Is stereo on the table? It's the strongest cue, and a project-wide change.
- Where it goes in the order (tape, the plate's stereo pair, the synth and C2 are in flight).
