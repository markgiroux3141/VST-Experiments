# Period gear backlog: what a 1967-70 studio had that we don't

Started 2026-11-10, from a brainstorm about mixing *Did She Mention My Name* like Gordon Lightfoot's
records of 1968-70 (HEADLESS_MIX_PLAN.md). This doc lists the gear such a mix would want that the
project lacks and no plan covers yet. Nothing is built. The user's favourite is the **1960s
multitrack deck and its tape**, so that one is worked out in detail. The others are short entries
to expand when they're picked up.

**Decided (2026-11-10, the user's):** PG1 is the **tube Ampex** (an Ampex 300 transport with the
351's electronics), **4 tracks on 1/2 in tape**, with **Sel-Sync and crosstalk in the first pass**
(milestones MT0-MT6 below are in that order).

Ground rules as everywhere (CLAUDE.md "Hard rules"): every value sourced, one coupled simulation,
two implementations per device model, everything seeded. Facts below marked *(to source)* are
model knowledge: confirm each against a manual, data sheet or paper before it becomes a value.

## What the stems asked for (2026-11-10)

Measured on `stems/Did she mention my name/full/*.wav` (96 kHz, 24-bit; a scratch script, not a
project tool):
- **The guitar** is boomy and dark. It plays 98% of the song; its 100 Hz third-octave sits ~10 dB
  above its neighbours, and above 1 kHz it is 25-30 dB under that. At import levels it is ~13 dB
  over the bass at 100 Hz.
- **The bass** is in E major, round and even: 500 Hz is ~27 dB under 100 Hz, its loudness range is 5 LU.
- **The lead** is a baritone (A2-G#3), clean, with silence between phrases. Peak -10 dBFS, crest
  18.5 dB: not yet compressed.
- **The harmonies** sing in three choruses only, mostly a 3rd to a 6th above the lead, within
  ~10 ms of it, about 8 dB brighter than the lead above 2 kHz.

So the mix wants a leveler, mid-band EQ and a high-pass for the guitar, a chamber and rides for the
vocal, and tape for the whole. Some of that is planned already; the rest is below.

## Already planned, moved up by this song

| Gear / feature | Plan | Why here |
|---|---|---|
| Teletronix LA-2A | MIX_INSERTS_PLAN.md MX4 | the vocal and bass leveler of the period |
| Pultec MEQ-5 | MX3 | the guitar's 100-200 Hz boom (the EQP-1A only shelves) |
| Pultec HLF-3C | MX2 | a period high-pass |
| Sends, the echo chamber as a send | SESSION_FX_PLAN.md F4, HEADLESS_MIX_PLAN.md H2 | the New York vocal reverb |
| Fader automation | HEADLESS_MIX_PLAN.md H2 | vocal rides (SE8's clip gain envelopes are the stopgap) |
| Neumann U 67 | CHAINS_PLAN.md WP28 | the 1960s vocal and acoustic guitar mic |

## The candidates

| # | Candidate | Fills | Reuses | New to build |
|---|---|---|---|---|
| PG1 | **A 1960s multitrack deck and its tape** | the tracking machine: tracks on one tape, Sel-Sync overdubs, crosstalk, bounces | the tape medium, the 351's electronics, the 351-2's two tracks, varispeed, the GPU kernel | N tracks, Sel-Sync, crosstalk, Scotch 201/202, the session's routing |
| PG2 | A console mix bus with iron | summing through a booster amp and transformers | control inputs, the transformer designer, tubes | the bus circuit; N inputs from the session |
| PG3 | Ampeg B-15 Portaflex | the period bass amp, for re-amping in the Room view | the speaker kind, the 5E3's pattern | a 15" driver, octal tube fits |
| PG4 | Altec 436 / UA 175B-176 | cheap variable-mu compression of the period | the 670's variable-mu approach | remote-cutoff tube fits |
| PG5 | Langevin EQ-251A | a passive program EQ of the period | the EQP-1A's passives | its network, a make-up amp |

PG4 and PG5 are also listed without plans in DEVICE_CANDIDATES.md and MIX_INSERTS_PLAN.md
("later"); this song is their reason to move up, if they do.

## PG1: the 1960s multitrack deck and its tape

### Why

A 1967 record was tracked on a 4- or 8-track machine, then mixed to a two-track. Today our tape is
a print on one track at a time (the 351 insert) or on the mix bus. A multitrack puts **every track
on one tape**, coupled the way the real machine coupled them:
- **One transport:** every track has the same wow and flutter, in phase (today each print draws its own).
- **Neighbours:** adjacent tracks leak into each other through the heads' side fringing, mostly in the bass.
- **Narrow tracks:** about 5 dB more hiss than the 351's full track.
- **Sel-Sync overdubs:** the performer heard the earlier tracks off the *record* head, through its
  wider gap. The overdub was played against a duller version of the song.
- **Bounces:** tracks mixed onto a free track lose a generation, and the bounced mix can't be undone.

This fits the project's "most organic first" rule: shared and coupled before independent.

### Which machine (decided: A)

| Option | Period | Electronics | For us |
|---|---|---|---|
| **A. Ampex 300-4 / 300-8 with 351-series electronics** *(to source)* | late 1950s to late 1960s (Les Paul's and Atlantic's 8-tracks were Ampex 300s) | tube: the 351's own record and repro amplifiers | the most reuse: `ampex_351.yaml`'s electronics, the 300's transport (`data/schematics/ampex_351/AE-4908-Stolaroff-Ampex_300.pdf`) |
| B. Ampex MM-1000 (1967), 3M M-23 (~1966), Scully 280 *(to source)* | the late-1960s solid-state 8-tracks of New York and LA | transistors (the BJT model exists) | closer to a 1967-70 major-studio session; new electronics to draw |

**Chosen: A** (the user's, 2026-11-10: most reuse, tube, period-plausible). B stays a possible
second machine on the same medium. The first build is the **Ampex 300-4**: four channels of the
351's electronics on a 1/2 in headblock. 8 tracks (1 in) is a later variant: the same medium with
N = 8.

### Formats (sourced 2026-11-10: data/schematics/ampex_300_4/README.md)
- **4 tracks on 1/2 in tape (the build)**; 8 on 1 in later. Tracks 0.070 in (1.78 mm) wide on
  0.130 in centres, so a 0.060 in (1.52 mm) guard band between neighbours: the gap the crosstalk
  crosses (the 354 manual's "4 track master" layout; Ampex's 1959 bulletin AI-14 says 80 mil,
  which can't fit four with 60 mil gaps on 500 mil). AI-14: S/N about 55 dB, crosstalk about
  50 dB for this format. The 300 came with 1/2 in heads in three- and four-channel versions,
  separate erase heads, and one **master bias oscillator** feeding "slave" channels.
- On 1/2 in, tracks 1 and 4 run along the tape's edges and 2 and 3 have two neighbours each. Who
  sits next to whom is the engineer's choice and sets the crosstalk.
- 15 ips (30 later). NAB equalization.
- The 351 is full-track, 0.238 in (6.05 mm) wide. A 1.78 mm track has 10 log10(6.05 / 1.78) = 5.3
  dB less S/N if the grain's noise scales as sqrt(width). That should come out of the grain model
  (Poisson particles per area) by itself; check that it does.

### The tape: Scotch 201 / 202 (decision 2)

Eilers' table of 3M's open-reel tapes (`data/datasheets/tape/aes_3m_audio_open_reel_products.pdf`
p. 1, AES Historical Committee) gives:

| Tape | Introduced | Base | Oxide | Hc | Retentivity | Remanence re 111 |
|---|---|---|---|---|---|---|
| 111 (ours) | 1948 | acetate | 0.5 mil | 270 Oe | 900 G | 0 dB |
| **201** | 1962 | acetate | 0.51 mil | 315 Oe | 790 G | 0 dB |
| **202** | 1962 | polyester | 0.51 mil | 315 Oe | 790 G | 0 dB |
| 203 | 1962 | polyester (0.92 mil base) | 0.51 mil | 315 Oe | 790 G | 0 dB |
| 206 | 1969 | polyester, back-treated | 0.56 mil | 320 Oe | 1050 G | +3.2 dB |

- **201 / 202 are the 1967 session's tapes.** 206 is for *If You Could Read My Mind* (1970) and later.
- Ampex's tapes of the period (Ampex 406/407 data are in the repo, their introduction dates aren't)
  are the alternative. 456 is 1974, too late.
- The fit follows SCOTCH111's path (TM1, TM3): a remanence curve, Hc, bias curves, the noise
  spectrum. Sound Talk ends at No. 38 (1960) in the repo; 201 / 202 data need finding (later Sound
  Talk bulletins, 3M data sheets on bitsavers, *db* or *Audio* magazine tests).
- Eilers' copyright note on that PDF (data/datasheets/tape/README.md) is unchanged: its numbers are
  cited, the file isn't redistributed.

### What's new to build
1. **N tracks on one tape** (N = 4 first). The 351-2 already records two tracks in one medium
   (DELAY_PLAN.md "PING-PONG"). Generalize to N, with one transport and one capstan supply, each
   track with its own grain (`live::Circuit::with_track` renames per track today).
2. **Crosstalk between adjacent tracks** (first pass). The medium is 2D today (along the tape
   and into the coating). The side fringing of the record and repro heads across the width is new
   physics: a cross-section field solution per head (as the Rhodes pickup went 3D, `pickup3d.py`).
   It has two paths:
   - **at record:** the record head's side field writes a weak copy of a track onto its
     neighbour's stretch of tape, through the guard band;
   - **at playback:** the repro (or, in Sel-Sync, the record) head's core picks up the
     neighbour's flux.

   The fringing reaches about a wavelength across the width, so long wavelengths, the bass, cross
   most; the guard band (1.52 mm) is short against the bass's wavelengths at 15 ips (38 mm at
   100 Hz). Each pair of neighbours gets a transfer (level and phase per frequency), symmetric
   unless the heads differ. In this song, which part sits next to the bass is audible.
3. **Sel-Sync** (first pass). A track's record head switched to playback, by track, through the
   Sel-Sync switching of the machine's electronics *(the 300's Sel-Sync circuit: to source)*. The
   reciprocity playback exists for the repro head; the record head's geometry plays the same way.
   To check: our record gap is 51 um (the Ampex 300's, TAPE_PLAN.md "Gaps"). At 15 ips the gap's
   first null is at 0.381 / 51e-6 = 7.5 kHz, lower in practice. If that's what a 300's Sel-Sync
   heard, it is a finding. If Sel-Sync machines had narrower record gaps, that's a source to find.
   **Where Sel-Sync is heard** (it changes what you hear while recording; recorded tracks still
   play back off the repro head):
   - **live overdubs** in the app (RECORDING_PLAN.md): the performer monitors the earlier tracks
     off the record head, in time with what they record. Monitored off the repro head instead,
     the overdub lands late by the head spacing over the speed (50.8 mm at 15 ips: 133 ms);
   - **bounces on the same machine:** the sources play off the record head so the bounce lines up
     with the tracks it joins, so a bounce carries the record head's response and its crosstalk;
   - **not in a one-pass print of finished stems:** *Did She Mention My Name*'s four parts on four
     tracks, printed together, need no Sel-Sync. It is heard there only if the session is rendered
     as a period overdub sequence (decision 4).
4. **Erase and punch-in.** The erase head sits ahead of the record head, so a punch leaves a
   stretch set by their spacing over the speed *(spacing and any switching delay: to source)*.
   This hooks into the session's punch (SE7, `Clock::record_to`).
5. **Bounces.** Tracks mixed (the console, PG2 or the session's sum) and recorded onto a free
   track of the same tape: SE8's Bounce plus a print through the deck.
6. **Print-through**, later: layer-to-layer transfer while the reel sits on the shelf (Sound Talk
   Nos. 10 and 38 are in the repo; TAPE_PLAN.md lists it as "later"). It is a condition dial
   (shelf time, temperature), per the "turn it to 11" rule.

### How it sits in the session (decision 3)

The deck is a property of the session, not a track insert:
- tracks are assigned to tape tracks;
- a "tape" print records every assigned track through it at once (offline, at production; the
  GPU kernel, TAPE_SPEED_PLAN.md P5);
- each session track plays its tape track's playback.

A proposed default: the tape tracks are recorded together as in one pass, with crosstalk on (it
is in the first pass). Sel-Sync is used where it is heard: bounces, live overdubs, and an
optional overdub-sequence render (decision 4). Cost: four times the 351's recording kernel, in
pieces (P3). The 351's print runs 10x slower than real time in pieces on the GPU, so 4 tracks may
be ~0.5-1 hour for this song. Measure before promising.

### Where it stands (2026-11-10, the first build session)

- **MT0 done.** `data/schematics/ampex_300_4/README.md`: Ampex's 1959 *Technical Notes on
  Multi-Channel Recording* (AI-14: formats, S/N against width, crosstalk, Sel-Sync, the master
  bias oscillator), the 1976 head assembly list (the 300-4's stack 02-31055-02, part numbers
  only), the 1970 catalog, the 354 manual's primer. Its **measured crosstalk curve** (a
  three-track Model 300) is digitized: `data/datasheets/ampex_300_crosstalk.csv`, sidecar
  `ampex_354_manual.provenance.yaml` (one of its dB labels is misprinted; read so the mid band
  is -59 dB, in line with Ampex's figures). Sel-Sync has no published response: AI-14 only says
  a record head "can serve reasonably well as a playback head". Still missing: the 300's own
  manual (head dimensions, the Sel-Sync switching) and 3M's 201 / 202 data sheets (the AES
  archive refuses scripted fetches: the user fetches it).
- **MT1 provisional.** `SCOTCH202@1` (`scripts/make_scotch202.py`): SCOTCH111@3 moved to
  Eilers' row (315 Oe, the same 0.64 lines per 1/4 in on 0.51 mil), the grain's particle volume
  halved for "low noise" (a reseller's -3 dB). A fitted version when 3M's sheet is in.
- **MT2: the medium already does it.** Every tape element of a circuit draws its transport from
  the circuit's seed and its grain from its own name, so four tape parts share one transport
  bit for bit and hiss independently; the grain's S/N goes as sqrt(width) (70 mil vs 234 mil:
  5.24 dB, as Ampex says). `tests/test_multitrack.py`. Still to build: the four tape parts
  in the deck's circuit (MT5).
- **MT3: the model, in Python** (`varimu/multitrack/crosstalk.py`, outside the render cache key;
  `scripts/multitrack_crosstalk_study.py` -> `reports/multitrack/crosstalk/`). Three
  mechanisms, each named by Ampex:
  1. *the heads' outer contour* reads the neighbour's long wavelengths (the shields screen the
     gap, not the field in air past the stack): our head's contour term times a lateral factor
     (a strip's 3D field, K0 across the width), the bass bleed, -30 to -40 dB below ~60 Hz;
  2. *the cores' coupling* ("stacked heads form a small transformer"): flat, the -59 dB
     plateau;
  3. *the record heads' mutual inductance and capacitance*: +6 / +12 dB an octave, recorded on
     the neighbour, -43 dB at 16 kHz.
  Fitted with our 351's repro head on the curve's octave envelope: **1.85 dB rms** (third
  octaves 4.8 dB: the curve's lobes sit elsewhere, worst 71 Hz, -16.7 dB). Scaled to four
  tracks by AI-14's 55 -> 50 dB: **-52 dB mid band**, -30 dB at 31.5 Hz, -38 dB at 16 kHz
  (15 ips). Above 16 kHz Ampex's curve levels off; ours keeps rising (3 dB over at 20 kHz).
- **Not built yet:** crosstalk in the engine (the medium's neighbour pickup, terms 1-2; the
  record coils' coupling in the circuit, term 3), Sel-Sync (MT4), the deck's circuit (MT5),
  the session (MT6).

### Milestones (first pass: the tube Ampex 300-4 with Sel-Sync and crosstalk)
- **MT0 Sources.** The Ampex 300-4's manual (the 1/2 in headblock, track format, head spacings,
  the Sel-Sync switching and its EQ), tape data for 201 / 202, published crosstalk and Sel-Sync
  response figures for the machine or its heads. *Done when:* every format value above has a
  source, or is a provisional genome parameter with bounds.
- **MT1 The tape.** `SCOTCH202@1` (and 201) fitted like SCOTCH111, a profile against its data.
- **MT2 Four tracks, one transport.** The medium with N tracks of a given width; the grain per
  width checked (the 5.3 dB). *Done when:* four tracks recorded at once share the transport bit
  for bit, each has its own grain, and their S/N is within the data's.
- **MT3 Crosstalk.** The cross-width field of the record and repro heads (a cross-section
  magnetostatic solution, cached), the neighbour transfers at record and at playback, in the
  Python reference and circuitsim. *Done when:* a tone on one track measured on its neighbours
  matches the published crosstalk figures (or, without them, a reference full-field solve of the
  same heads), and the edge tracks have one neighbour.
- **MT4 Sel-Sync.** Record-head playback per track, its response and its crosstalk. *Done when:*
  the Sel-Sync response is within the manual's figures, and a track recorded while monitoring in
  Sel-Sync lines up with the earlier tracks to a sample.
- **MT5 The deck.** Four channels of the 351's electronics with the Sel-Sync switching, a circuit
  GENERATED from `ampex_351.yaml` (as `make_351_echo.py` does), aligned per channel
  (`align_351.py`'s procedure), profiled (`varimu unit --circuit ampex_300_4`). Python and Rust
  agree (the tape tests' pattern).
- **MT6 The session.** Track assignment, the tape print (all assigned tracks at once), bounces
  through Sel-Sync, punch-in erase, live overdubs monitored in Sel-Sync (RECORDING_PLAN.md).
  *Done when:* *Did She Mention My Name*'s four stems print through it from
  `stems/Did she mention my name/full/` and the session plays the tape tracks.
- Later: 8 tracks on 1 in, print-through, azimuth, machine B.

### Decisions
Decided (the user's, 2026-11-10):
1. The machine: **A, the tube Ampex 300 with the 351's electronics.**
2. **4 tracks** on 1/2 in first (this song's guitar, bass, lead, harmonies); 8 later.
3. **Sel-Sync and crosstalk in the first pass.**
- Later the same day, the user took Claude's recommendations on 4, 6 and 7: **a one-pass print**
  of the four stems (4); **the 351's repro head** for the deck, the lobe-fitted head a later
  refinement (6a); **one multi-rate island** for the four record sides on the master oscillator,
  its speed measured first (7). 5 (the track assignment) stays open.

The questions as they were put:
4. For this song: a one-pass print of the four stems (no Sel-Sync heard), or a period overdub
   sequence (e.g. guitar and bass as the basic tracks, then the lead and the harmonies overdubbed,
   the session rendered in that order with Sel-Sync monitoring). With finished stems the second
   changes only what a performer would have heard, so it matters for live overdubs, not for these
   stems.
5. The track assignment for this song (which part sits next to the bass).
6. **The deck's repro heads** (MT3's study, 2026-11-10):
   - (a) the 351's head (pole 1.5 mm, relax 5.5 mm, calibrated with the 351's electronics):
     crosstalk fits the octave envelope (1.85 dB rms) but not the lobes (4.8 dB at third
     octaves);
   - (b) a head whose contour is fitted to the lobes too: pole 6.3 mm, relax 12 mm (at the
     search's bound), third octaves 2.1 dB rms, its own response within about +-2.2 dB
     20 Hz-1 kHz at 15 ips (the 351's head: +3.7 dB at 40 Hz). But its unshielded fraction
     comes out 1.6 (above 1: the lateral factor runs low), and the deck would need its own
     alignment.
   Recommended: (a) for the first pass (one head model for the 351 and the deck), (b) as a
   refinement once the 300's head dimensions are found.
7. **The record side's threads.** One master oscillator biases all four record heads, and
   term 3 couples their coils: physically one solve, one multi-rate island for the four record
   sides (about 4x the 351's record side on one thread; prints run in pieces, P3). Four
   islands would need the oscillator and the coupling cut a sample late. Recommended: one
   island ("most organic first"); measure before anything else.

## PG2: a console mix bus with iron

1960s consoles summed passively into a booster amplifier, through transformers. Today the session
sums digitally. A bus circuit takes the tracks as control inputs (circuits already drive nodes from
samples: the Clavinet's pickups); the iron and tubes come from what exists. Candidates *(to
source)*: the Altec 1567A tube mixer, Langevin's program amps, UA's console line amps. Caution
(SCENE_ANALYSIS.md): a saturating shared bus costs the lead its harmonicity. Realistic levels
first. Overlaps STEREO_PLAN.md ST7's inserts with more than one input.

## PG3: Ampeg B-15 Portaflex

The flip-top bass amp from 1960 *(to source)*, for re-amping the bass through the Room view. The
scene's bass source today is only a directivity cap (`bass_1x15`). Tubes *(from the schematic)*:
octal preamp triodes and a 6L6 pair; a 15 in driver in its own cabinet (the speaker kind, a new
fit). On the 5E3's pattern (circuit, speaker readout, profile).

## PG4: Altec 436 / UA 175B-176

Variable-mu compressors that were cheaper and commoner than the 670 *(to source)*. They need
remote-cutoff tube fits (which tubes: from the schematics). DEVICE_CANDIDATES.md lists the Altec
436 with the Gates Sta-Level and RCA BA-6A.

## PG5: Langevin EQ-251A

A passive program EQ of the period (MIX_INSERTS_PLAN.md "later", DEVICE_CANDIDATES.md "to find").
Passives and a tube make-up amp, nothing new in the models. Low priority while the MEQ-5 and
HLF-3C wait.

## Status

*Updated at the end of every session.*

- 2026-11-10: written. The user chose PG1's machine (the tube Ampex 300-4), 4 tracks, Sel-Sync
  and crosstalk in the first pass.
- 2026-11-10 (later, on main): MT0 done, MT1 provisional (`SCOTCH202@1`), MT2 verified on the
  medium, MT3's model built and fitted in Python ("Where it stands" above). Decisions 4, 6, 7
  taken (Claude's recommendations). Next: crosstalk in the engine (circuitsim's tape stream reading its neighbours, the Python
  reference first) and MT4 (Sel-Sync: the record head's playback).
