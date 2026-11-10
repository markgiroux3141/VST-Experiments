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

### Formats *(to source: NAB multitrack standard, the Ampex manuals)*
- **4 tracks on 1/2 in tape (the build)**; 8 on 1 in later. Tracks 0.070 in (1.78 mm) wide on
  0.130 in centres, so a 0.060 in (1.52 mm) guard band between neighbours: the gap the crosstalk
  crosses.
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

Open:
4. For this song: a one-pass print of the four stems (no Sel-Sync heard), or a period overdub
   sequence (e.g. guitar and bass as the basic tracks, then the lead and the harmonies overdubbed,
   the session rendered in that order with Sel-Sync monitoring). With finished stems the second
   changes only what a performer would have heard, so it matters for live overdubs, not for these
   stems.
5. The track assignment for this song (which part sits next to the bass).

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

- 2026-11-10: written. Nothing built. The user chose PG1's machine (the tube Ampex 300-4), 4
  tracks, Sel-Sync and crosstalk in the first pass. Next: MT0 (sources).
