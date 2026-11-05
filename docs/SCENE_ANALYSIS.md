# How the ear separates sounds, and what it means for analog chains

A research session, 2026-11-04 (the user's ask: the neuroscience of separation, distilled
into things we can compute and build). It follows [SEPARATION_PLAN.md](SEPARATION_PLAN.md),
whose pre-screen is energetic only (the glimpse proportion) and blind by design to the cues
below. Built from it: four grouping measures (`varimu/separation/grouping.py`,
`tests/test_grouping.py`) and a study (`scripts/grouping_study.py` ->
`reports/separation/grouping.json`, audio in `cache/separation/grouping/`). Nothing in the
netlists or the render cache key changed.

Sources are cited inline. Numbers marked [A] come from an abstract or a secondary summary,
not the paper's text; everything else was read in the paper or its full-text copy (PMC,
arXiv, the authors' PDFs).

## 1. What the brain uses

### Simultaneous grouping (which components belong together right now)

Ranked by how strong and robust the evidence is:

| Cue | What the ear does | Numbers |
|---|---|---|
| **Harmonicity** | Components on one F0's harmonic series fuse; one mistuned partial pops out as its own tone. The *masker's* harmonicity matters more than the target's: the ear cancels a harmonic background (a comb at its period) rather than enhancing the target | Mistuning heard at 1-3% (Moore, Glasberg and Peters, JASA 80, 1986); a harmonic masker is worth 5-15 dB to the target over an inharmonic or noise one (de Cheveigne, *Trends in Hearing* 25, 2021, a review); concurrent vowels improve with dF0 up to ~1 semitone, then plateau (Assmann and Summerfield 1990 [A]); the benefit vanishes at the same F0 (de Cheveigne et al., JASA 97, 1995 [A]). Inharmonic speech mixtures are ~20% less intelligible, single words not (Popham et al., *Nat. Commun.* 9, 2018) |
| **Common onset** | Components that start together fuse; a component leading by 30-50 ms drops out of the sound's timbre; offsets barely matter | ~40 ms (Darwin 1984; Darwin and Sutherland 1984 [A]); 50 ms abolishes comodulation masking release (Grose and Hall 1993 [A]); pitch needs 160-300 ms of lead (Darwin and Ciocca 1992 [A]); synchronous tones fuse even 15 semitones apart (Elhilali et al., *Neuron* 61, 2009) |
| **Temporal coherence** | Cochlear channels whose envelopes rise and fall together (2-32 Hz) bind into one stream; attention to one feature pulls in everything coherent with it | Model: rate filters 2-32 Hz, zero-lag correlation over ~50-500 ms (Elhilali et al. 2009; Krishnan, Elhilali and Shamma, *PLoS Comput Biol* 10, 2014: ~6 dB SNR gain on talker mixtures). Stochastic figure-ground: a few coherent components among random ones are detected from ~8 chords of 50 ms (Teki et al., *eLife* 2, 2013). EEG coherence response at ~115 ms, present without attention (O'Sullivan, Shamma and Lalor 2015 [A]). **Not absolute:** 4% mistuning segregated a component as well as incoherence did (Micheyl et al., JASA 133, 2013) |
| **Common AM (comodulation)** | A band whose envelope matches the masker's is fused into it and is harder to hear | CMR up to ~10 dB (Hall, Haggard and Fernandes 1984 [A]); comodulation detection differences: a band sharing the maskers' envelope is 1-12 dB harder to detect (McFadden 1987 [A]) |
| **Common FM** | **Weak or absent as a cue of its own.** Listeners detect incoherent FM only through the mistuning it creates (chance in inharmonic complexes); different vibrato on competing vowels doesn't help; modulating a source makes *it* more prominent whatever the others do | Carlyon, JASA 89, 1991 and 95, 1994 [A]; McAdams, JASA 86, 1989 [A]; Summerfield, Culling and Fourcin 1992 [A]. Natural-sound statistics agree: common AM or FM didn't emerge as separate cues (Mlynarski and McDermott, PNAS 116, 2019) |
| **Spatial (ITD)** | **Selects and tracks a stream, barely forms one.** Bands sharing an ITD aren't grouped across frequency; location guides attention to objects already formed by harmonicity and onsets | Culling and Summerfield, JASA 98, 1995; Darwin and Hukin 1999 [A]. ILD separates more than ITD (Glyde et al. 2013 [A]: ILD alone ~ the full spatial release) |

Two corollaries:

- **Reverberation erases the moving-F0 cue** (the comb can't cancel a smeared, changing
  period) but leaves static-F0, timbre and size cues; ITD is the least robust cue in rooms,
  timbre the most (Culling, Summerfield and Marshall 1994; Darwin and Hukin 2000 [A]).
- **Energetic vs informational masking.** Energetic: the target's cells are covered (what
  glimpses measure). Informational: the target is represented but not *segregated*, driven
  by target-masker similarity. Most of the spatial benefit with speech maskers is
  informational: 18 dB vs 7 dB energetic at 90 deg (Arbogast, Mason and Kidd 2002 [A]). The
  separation study's worst case (one patch, one register) is maximally informational.

### Sequential streaming (which events form one line over time)

Two tones alternating split into two streams at >= ~6 semitones and short gaps (rates >=
10 Hz), marginal at 3; build-up over ~2 s. In A1 the mechanism is forward suppression set by
the silent interval (Fishman et al. 2001, 2004; Micheyl et al., *Neuron* 48, 2005, via the
review in PMC2040076). Tonotopic separation in A1 alone can't explain it: synchronous and
alternating tones give the same tonotopic pattern, only their timing differs (Elhilali 2009).
Voice-leading rules derive from these principles (Huron, *Music Perception* 19, 2001: avoid
unisons, octaves and fifths between voices, small steps within one, avoid parallel motion and
synchronous onsets); with one timbre, counting voices fails above three (Huron 1989 [A]).

### Where it happens

- Auditory cortex represents the **attended** source: spectrograms reconstructed from
  non-primary cortex during a two-talker mixture look like the attended talker alone
  (Mesgarani and Chang, *Nature* 485, 2012 [A]); the attended talker's representation scales
  with its own level only, over 8 dB of masker level (Ding and Simon, PNAS 109, 2012 [A]).
- Harmonic template neurons in marmoset A1 respond >2x more to harmonic complexes and fall
  off when spectral jitter exceeds 10% (Feng and Wang, PNAS 114, 2017).
- A mistuned partial evokes an "object-related negativity" at ~180 ms without attention
  (Alain, Arnott and Picton 2001 [A]).
- An auditory object is a *predictive regularity* (Winkler, Denham and Nelken, TICS 13,
  2009): regularities that predict the next sounds compete as parsings of the scene.
- A binaural deep network trained to attend reproduces human effects (same-sex confusions,
  inharmonic speech segregating worse, horizontal > vertical, precedence) with selection
  emerging late (Griffith, Hess and McDermott, preprint 2025, PMC12154610).

## 2. What it predicts for recording chains

The folklore: per-track analog chains give separation, summing through shared gear gives
"glue". The literature turns that into specific mechanisms:

1. **A shared nonlinearity (bus saturation, summing into one tape track) makes
   intermodulation:** f1 +- f2 and 2f1 - f2 products between the tracks belong to neither
   one's harmonic series. They make the accompaniment less harmonic, which costs the lead
   the cancellation benefit (5-15 dB). Per-track saturation keeps each track harmonic. **No
   controlled study of per-track vs bus distortion exists** (the closest: Campbell, Paterson
   and Toulson 2014, an abstract without numbers). The simulation can answer it exactly.
2. **A shared compressor imposes common gain**, but Corey and Singer (JASA 2021,
   arXiv:2012.03860) prove compression makes independent envelopes *negatively* correlated
   (each source in a mixture is compressed less than alone); hearing-aid research found
   this across-source modulation correlation the dominant factor in intelligibility (Stone
   and Moore, JASA 121, 2007 [A]). For music, though, compressing before vs after mixing had
   **no effect** on instrument clarity (Madsen et al., JASA 137, 2015 [A]). Contested.
3. **Independent tape flutter per pass** (SEPARATION_PLAN.md called common fate
   "underrated, nearly free"): the literature says FM incoherence isn't a cue, and 0.1%
   (1.7 cents) is far below the 1-3% mistuning that is one. Expected: nothing. Flutter on the
   accompaniment could even *hurt* the lead (a moving F0 cancels worse, worse still in a
   room; de Cheveigne 2021).
4. **Reverb on the accompaniment** costs the lead twice: it fills the glimpses and it smears
   the accompaniment's periodicity, so it can't be cancelled.
5. **Onsets are the strongest cue a chain can move**, but only by tens of ms: compressor
   attack that passes or clamps a transient, distance (1 ms per 34 cm), reverb smearing.
6. **Stereo:** pan by level (ILD), not time; keep the bed coherent. A decorrelated bed
   (spaced room mics hard left and right, wide reverb) lowers the masker's interaural
   coherence and with it the binaural unmasking left for every target: at 500 Hz, 10.7 dB
   at coherence 1, 5.0 dB at 0.5 (the equalization-cancellation model as in Kolotzek et al.
   2021, arXiv:2106.16024, eq. 1).

## 3. The measures

`varimu/separation/grouping.py`, each after a published model, on the target's and the
masker's shares of the mix (for a bus device, what each adds: `bus(t + m) - bus(m)`, so
the intermodulation lands in both as the ear meets it; linear processing gives the tracks):

| Measure | Model | Reads |
|---|---|---|
| `temporal_coherence` | Envelope correlation between the sources' 32 ERB channels, 2-32 Hz rate bands (Q ~ 1), windows of 4 periods, weighted by both channels' power (Elhilali 2009; the within-channel part is Stone and Moore's ASMC) | Higher = fused |
| `onset_coincidence` | Share of target onsets with a masker onset within +-30 ms | Higher = fused |
| `harmonic_cancellation` | The masker's F0 tracked (YIN), a comb at its period below 4 kHz: the target's SNR gain from the cancellation; the reverse for the masker; what survives both combs (energy harmonic to neither source) | Gain higher = separable; residual higher = inharmonic |
| `envelope_snr` | The multi-resolution sEPSM's SNRenv (Joergensen, Ewert and Dau, JASA 134, 2013): octave modulation bands 1-128 Hz below a quarter of each channel's centre | Higher = separable |

Checked on signals with known answers (`tests/test_grouping.py`): independent envelopes
read ~0 +- 0.1, a shared one > 0.8, steady tones ~0; onsets 0-25 ms apart coincide, 50 ms
and more don't (the literature's ~40 ms); a tanh on the sum of two harmonic tones drops the
cancellation gain from 27.6 to 13.3 dB and raises the inharmonic residual from -21 to
-4.8 dB, the same tanh per track changes neither.

## 4. Results

### The separation study's conditions

The grouping measures on the study's audio (each track at -23 LUFS, the target -6 dB under
the masker), plus masker variants computed here. Coherence and onsets: lower = more
separated; cancellation gain, SNRenv and glimpses: higher = more separated.

| Condition | Coherence | Onsets | Cancel. gain (dB) | Residual (dB) | SNRenv (dB) | Glimpses |
|---|---|---|---|---|---|---|
| Dry | 0.59 | 1.00 | 20.0 | -14.2 | 18.7 | 0.30 |
| Flutter (shared, independent, either side, 4x) | 0.58-0.59 | 1.00 | 19.8-20.1 | -14.2 | 18.7-18.9 | 0.30 |
| Masker flutter 16x (1.8% rms) | 0.58 | 1.00 | 16.8 | -11.8 | 18.3 | 0.29 |
| Masker in the hall | 0.13 | 0.91 | 7.4 | -2.9 | 16.7 | 0.20 |
| Masker in the hall, flutter 1x / 16x | 0.13 / 0.20 | 1.00 | 7.4 / 5.4 | -3.1 / -1.8 | 17.1 / 14.1 | 0.20 / 0.16 |
| Target hall, masker booth | 0.11 | 0.24 | 18.9 | -10.6 | 19.9 | 0.30 |
| Target booth, masker hall | 0.14 | 0.91 | 7.0 | -2.8 | 15.6 | 0.19 |
| Both near / both far (home) | 0.27 / 0.11 | 0.79 / 0.85 | 10.3 / 11.0 | -5.8 / -6.1 | 16.8 / 17.1 | 0.22 / 0.19 |
| Target 5E3, masker 670 / EQP-1A | 0.57 / 0.56 | 1.00 | 19.6 / 19.8 | -12.6 / -12.9 | 22.5 / 24.0 | 0.47 / 0.51 |
| Masker 5E3, target 670 / EQP-1A | 0.58 / 0.57 | 1.00 | 15.1 / 14.9 | -9.7 | 20.4 / 20.1 | 0.26 / 0.25 |
| Same chain on both (670, EQP-1A, 5E3) | 0.57-0.60 | 1.00 | 15.1-19.6 | -9.1 to -13.6 | 18.7-18.9 | 0.29-0.30 |
| **The masker 30 ms late** (no chain) | **0.19** | **0.36** | 20.1 | -14.5 | 20.0 | 0.31 |

What it says:

- **The arrangement dominates.** The study's masker plays eighths on the target's grid, so
  every target onset has a masker onset (1.00) and their envelopes correlate at 0.59. Moving
  the masker 30 ms late (an ensemble's ordinary asynchrony: 30-50 ms SD, Rasch 1979) cuts
  both to 0.19 / 0.36. No device moves coherence by more than 0.03.
- **Flutter at the 351's 0.11% does nothing in any measure,** independent or shared, as the
  literature predicts. At 16x (1.8%, a broken machine) it costs the target 3 dB of
  cancellation, and more in a room: flutter on the accompaniment hurts the lead, slightly.
  SEPARATION_PLAN.md's "common fate is underrated" is withdrawn.
- **Reverb on the accompaniment is the most expensive thing measured:** 12.6 dB of the
  target's cancellation gain (the hall smears the masker's period) and a third of its
  glimpses. Reverb on the target instead costs it almost nothing by these measures (gain
  18.9 dB, glimpses 0.30) and decorrelates the onsets (0.24). Note the conflict with mixing
  practice (dry lead, wet bed): the measures speak to the lead's audibility, not its
  closeness, which is DRR and level (Zahorik et al. 2005 [A]); see "Proposals".
- **Distortion on the masker costs the target ~5 dB of cancellation gain** even per track:
  the 5E3's added harmonics stay harmonic, but a comb's null is shallower at high harmonic
  numbers for a given period error (partly the measure's front end, partly real: the ear's
  own delay jitter does the same; de Cheveigne's model has it).

### Per track vs on the bus (the new experiment)

The study's dry target and masker, each at -23 LUFS, one gain so the louder peaks at -12 dBFS,
rendered at production four ways per device: target alone, masker alone, both summed into
one device, silence. Per track = dev(t) + dev(m); bus = dev(t + m); every render taken
relative to the device's response to silence (its idle output, -77 dB re the target or less,
belongs to neither). The **interaction residual** dev(t + m) - dev(t) - dev(m) is what a bus
adds and per-track processing never has (exact in simulation; the hearing-aid literature's
phase-inversion trick, Hagerman and Olofsson 2004, approximates it on hardware). The measures
are on the shares, then scaled as above (each -23 LUFS, the target -6 dB). The "target clean"
column gives the target its own render alone against everything else in the bus mix (the
masker and all the intermodulation): the reading most favourable to the bus.

| Device | Residual re bus mix | | Coherence (within) | Onsets | Cancel. gain | Inharmonic residual | SNRenv | Glimpses |
|---|---|---|---|---|---|---|---|---|
| EQP-1A (nearly linear, the control) | -23.7 dB | per track | 0.59 (0.61) | 1.00 | 19.6 dB | -13.6 dB | 18.8 dB | 0.30 |
| | | bus | 0.59 (0.61) | 1.00 | 20.2 dB | -14.4 dB | 18.8 dB | 0.30 |
| 5E3 + speaker (volume 0.5) | **-0.7 dB** | per track | 0.57 (0.62) | 1.00 | 15.1 dB | -9.1 dB | 18.8 dB | 0.29 |
| | | bus | 0.60 (0.72) | 0.92 | **0.1 dB** | **+5.1 dB** | 10.2 dB | **0.12** |
| | | bus, target clean | 0.65 (0.72) | 1.00 | 1.0 dB | +3.9 dB | 11.1 dB | 0.16 |
| 5E3 hot (volume 0.85) | +0.5 dB | per track | 0.57 (0.61) | 1.00 | 15.3 dB | -9.3 dB | 18.6 dB | 0.28 |
| | | bus | 0.58 (0.72) | 1.00 | -0.7 dB | +3.8 dB | 11.3 dB | 0.13 |
| 670 hot (pad 0 dB, threshold 1, TC 1) | -6.0 dB | per track | 0.61 (0.62) | 1.00 | 14.6 dB | -9.8 dB | 18.1 dB | 0.28 |
| | | bus | 0.53 (0.62) | 0.92 | **5.4 dB** | -2.0 dB | 10.7 dB | **0.13** |
| | | bus, target clean | 0.63 (0.66) | 1.00 | 5.7 dB | -5.6 dB | 10.8 dB | 0.21 |

(The 670 compressed each track alone by 6.8 / 7.3 dB and each in the bus mix by 9.2 / 9.5 dB.)

What it says:

- **On a nonlinear bus, the tracks stop being separable by harmonicity.** Summed into the
  5E3, the interaction residual is as loud as the mix itself; the energy harmonic to neither
  source goes from -9 dB to +5 dB (more of the mix fits neither line than fits them), the
  target's cancellation benefit from 15 dB to 0-1 dB, and its glimpses fall by half to
  three fifths. Driving each track harder on its own (volume 0.85) changes nothing per
  track (15.3 dB): the loss is the sharing, not the drive.
- **Bus compression does the same, less:** the 670's shared gain imprints each source's
  envelope on the other (cross-modulation), costing ~9 dB of cancellation benefit and half
  the glimpses. Caveat: the bus 670 also compressed ~2.5 dB deeper (it sees the sum); a
  per-track run at the bus's depth would separate depth from sharing (not done).
- **Coherence moves little and its sign depends on the attribution** (0.53 or 0.63 for the
  670 bus against 0.61 per track): Corey and Singer's negative correlation shows when the
  cross-modulation is split between the shares, not when the target is taken clean. The
  harmonicity and energetic losses hold either way. Within-channel coherence rises clearly
  on the 5E3 bus (0.62 -> 0.72): intermodulation fills each channel with a mixture of both
  sources' envelopes, the "glue" the folklore names.
- **A linear device on the bus is the same as per track** (the EQP-1A, the control), as it
  must be.

The audio, each mix loudness-matched at -20 LUFS (the residual at the bus mix's gain):
`cache/separation/grouping/<device>/{per_track,bus,residual}.wav`.

### Which intervals a saturating bus glues

Two sustained harmonic tones (10 harmonics, A3 and an equal-tempered interval above it, each
-12 dBFS peak) through the 5E3 alone and together; the interaction residual combed at the
common root of the nearest just ratio (q <= 5):

| Interval | Just ratio (ET error) | Residual re per-track | Residual combed at the root | Per track combed at the root |
|---|---|---|---|---|
| Octave | 2:1 (0%) | -5.6 dB | **-26.7 dB** | -27.6 dB |
| Fifth | 3:2 (+0.11%) | -3.9 dB | **-21.3 dB** | -22.5 dB |
| Major third | 5:4 (-0.79%) | -3.9 dB | -0.4 dB | -2.0 dB |
| Tritone | 7:5 (-1.0%) | -3.7 dB | -1.0 dB | -0.4 dB |
| Minor second | none | -3.6 dB | +0.6 dB | -0.7 dB |

The amount of intermodulation hardly depends on the interval (-3.6 to -5.6 dB); **where it
lands does.** On octaves and fifths it falls on the root's harmonic series, so it adds to
one harmonic object (the power chord: fusion, "glue"); in equal temperament every other
interval's products miss any root by more than the ~1-3% the ear forgives (the third's 0.8%
grows with each product's order), so they are inharmonic: mud. This is the mechanism behind
Herbst's finding that distorted power chords stay pleasant and dense chords don't (Herbst
2017, Huddersfield thesis; 2018-2019 [A]), and it predicts something not tested anywhere we
found: a **just-tuned** major third should glue on a saturating bus like a fifth.

## 5. Proposals

Ranked by what the evidence and the measurements support. Each stays physical (the genome
rule): a chain, a part, a performance, never a "separation" knob.

1. **Glue without mud: share the modulation, not the nonlinearity.** The measurements split
   "bus character" into two things the folklore lumps together: shared *nonlinearity*
   (intermodulation: harmonicity lost, glimpses lost) and shared *slow modulation*. A
   physical bus that gives the second without the first: tracks through their own stages
   that share a power supply (common sag and ripple), a transport (one tape's speed, one
   capstan) or a mains, then summed passively or at low level into a summing amp with
   headroom. This is how a real console is built, and the most-organic-first design the poly
   synth already uses (one supply for every voice). Test: the poly synth's voices on a
   shared supply vs independent supplies vs one shared output stage driven hot, with these
   measures; the summing amp's drive as the dial between glue and mud.
2. **The interaction residual as a meter.** In simulation dev(t + m) - dev(t) - dev(m) is
   exact. Per bus insert in the Session view: its level, and the share of it that sits on a
   common root (`residual_root_comb_db`). It answers "is this bus gluing or muddying" for
   the actual program, before anyone listens. Costs one render per track in the bus (the
   per-track prints exist already: SESSION_FX_PLAN.md).
3. **Just intonation on a saturating bus.** The tube synth's tuning tables could hold a just
   scale (or the poly allocator could tune each chord's notes to just ratios, as barbershop
   singers and string quartets do). The prediction above (a just third glues like a fifth on
   the 5E3) is one render to check and one listening comparison to hear.
4. **Ensemble timing is the biggest lever measured, and it's physical.** A 30 ms offset did
   more to the grouping measures than any chain (coherence 0.59 -> 0.19, shared onsets 1.00
   -> 0.36). Ensembles play 30-50 ms apart (Rasch 1979); pianists' melody notes lead the
   chord by ~20-30 ms, and one account is the action itself: a faster hammer arrives sooner
   (Goebl, JASA 110, 2001, "melody lead": expressive or artifact? [unverified numbers]).
   - The Rhodes strikes every key at its MIDI event (`varimu/rhodes/harp.py`); a key-to-
     hammer travel time that depends on the hammer's speed (the action's mechanics,
     RHODES_PLAN.md "Action and hammer") would give the melody its lead for free.
   - Separately recorded takes (MIDI_TAKES_PLAN.md) already carry each pass's own timing;
     nothing should quantize it away. A per-track "player" (onset scatter, a part leading or
     laying back) belongs to the performance, like the takes, not to the chain.
5. **Keep the accompaniment harmonic and point-like; spend the reverb with care.** Reverb on
   the bed cost the lead 12.6 dB of cancellation benefit and a third of its glimpses; on the
   lead it cost nearly nothing by these measures. That contradicts the habit of a dry lead
   over a wet bed, which buys closeness (direct-to-reverberant ratio), not audibility.
   Physical options that keep both: pre-delay past the echo threshold (15-30 ms for music;
   Brown, Stecker and Tollin 2015 review) so the onsets stay clean; a damped, short room on
   the bed (booth or plate at short DECAY) and the long tail on the lead. Worth a staircase
   comparison: lead wet / bed dry against the habit.
6. **For the stereo room loop (ROOM_LOOP_PLAN.md):** pan by level; keep the bed coherent.
   Spaced room mics hard left and right decorrelate the bed and take binaural unmasking
   from every target (EC model: 10.7 dB at 500 Hz with a coherent masker, 5.0 dB at
   coherence 0.5). A coincident room pair, or the room mics on the lead rather than the
   bed. The separation metric there should be binaural: per band the better ear's SNR plus
   the BMLD of the EC model, BMLD(f) = 10 log10((k - cos(phi_T - phi_M)) / (k - rho_M)),
   k = (1 + 0.25^2) exp((2 pi f)^2 (105 us)^2) (Durlach 1972 via Kolotzek et al. 2021),
   24 ms frames, the BMLD smoothed over 300 ms and the better-ear SNR over 200 ms (their
   time-resolved form). Better-ear glimpses (Brungart and Iyer 2012) are the stereo glimpse
   proportion.
7. **The keyed 670 is a separation device.** Ducking the bed from the lead (SIDECHAIN_PLAN.md,
   K1-K3) opens glimpses where the lead plays and, by these measures, should anticorrelate
   the envelopes rather than imprint them. Measure it with `grouping_study.py`'s bus
   machinery on a keyed render.
8. **Validate the measures against the ear.** The separation staircase
   (`scripts/separation_listen.py`) is still unrun. The cheapest decisive listen: the 5E3
   per track vs on the bus (`cache/separation/grouping/5e3/`), then the masker 30 ms late.
   If the staircase agrees with the cancellation gain and the glimpses, the measures become
   the pre-screen for MIC_ROOM_PLAN.md's A9 (ranking chains) and the room loop's stereo test.

What doesn't earn a model on this evidence: independent flutter per pass for separation
(it's free in TAPE_PLAN.md's transport anyway), detune or ensemble scatter between parts
(5-14 cents fuses a section into one object: Ternstrom 1993 [A]), ITD panning.

## Limits

- The measures are models, run on one worst-case pair (one patch, one register, a masker on
  the target's grid); none has been checked against the user's ears yet (proposal 8).
- The harmonic cancellation is sensitive to period error at high harmonic numbers, so a
  bright, distorted masker reads ~5 dB worse even per track (the 5E3, the 670 hot); part of
  that is the front end (a YIN track, linear interpolation), part real (the ear's own delay
  jitter limits cancellation the same way: de Cheveigne 2021).
- Mono throughout. Informational masking in music is barely measured anywhere; most numbers
  above are from speech.

## 6. Corrections to earlier plans

- SEPARATION_PLAN.md "Common fate is underrated, and it's nearly free" (independent flutter
  per pass): not supported. FM incoherence isn't a grouping cue (Carlyon 1991, 1994;
  McAdams 1989; Summerfield et al. 1992), and the measures above find nothing at real
  flutter depths. What independent passes do buy is per-pass *timing* (a re-recorded part
  lands tens of ms differently), which is the performance, not the transport.
- SEPARATION_PLAN.md's table puts space as "the strongest cue". For forming groups it is
  among the weakest (ITD); for *releasing informational masking* and selecting a stream it is
  strong, mostly through level differences (ILD) and perceived location.
