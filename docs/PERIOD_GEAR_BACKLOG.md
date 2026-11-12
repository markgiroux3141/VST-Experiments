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
- **The fit's reference corrected (2026-11-10, second session).** The fit took the driven
  track's own playback as flat; Ampex measured the neighbour against the driven track through
  the same EQ, and our head's own reading isn't flat (its bump, +3.7 dB at 40 Hz).
  `Crosstalk.playback` is now the neighbour's EMF over the driven head's own, which is what
  the engine computes. Refit: **1.64 dB rms on octaves** (was 1.85), 5.0 dB on third octaves
  (was 4.8); the cores' coupling now negative (-59.2 dB), unshielded 0.84, the contour width
  ratio again at its bound (1.848, the three-track pitch); record terms -54.3 dB (mutual) and
  -53.2 dB (capacitive) at 10 kHz. Four tracks: -54.0 dB at 1 kHz, -29.6 dB at 31.5 Hz, a
  null at 63 Hz (the contour and core terms cancel), -38.8 dB at 16 kHz
  (`reports/multitrack/crosstalk/fit.json`).

### Built in the second session (2026-11-10)

- **MT3 in the engine: a head reads its neighbours' tracks.** Design (decided here, stated
  as the brief asked): **tape elements of one tape form a group**, not one multi-track
  medium element. Playback crosstalk is linear in the recorded magnetization, so each
  track's stream also computes, from the same recorded blocks, the slope a head one pitch
  away reads of it (`CrossPickup`: the contour's term through the shields times the lateral
  factor, plus the cores' coupling times the head's own reading), and the media layer adds
  each neighbour's cross EMF to a head's own. Everything the single-track medium has
  (literal bias, multi-rate feeds, one sense per medium, a recorder thread per track, grain
  per element, reduced tape) stays as it was; the group only needs its tracks in one
  partition part (refused otherwise).
  - Python reference: `varimu/devices/tape.py` (`CrossPickup`, `lateral_factor`: K0's
    integral in closed form over the triangle, the trapezoidal rule in t, both languages;
    `cross_hx_spectrum`; `flux_slope(cross=)`), `tape_machine.TapeStream(crosstalk=)`
    (`push_both`, `cross_out`), `with_neighbours`.
  - circuitsim: `TapeParams.crosstalk` (`TapeCrosstalk`: group, track, pitch, unshielded,
    contour width, core), the finisher's cross slope, `TapeStream::push_many_readouts`,
    `media::crosstalk_pairs`, the transient's sum per output row, partition.rs's one-part
    check; `tape_stream_run(readouts=True)`.
  - IR and both builders: the tape part's `crosstalk_group`, `crosstalk_track`,
    `crosstalk_pitch_m`, `crosstalk_unshielded`, `crosstalk_contour_width_m`,
    `crosstalk_core` (all or none; refused on a reduced tape); two tapes on one track refused
    (both languages). Test circuit `config/circuits/tape_tracks_test.yaml`.
  - Agreement: Rust against the reference within 1e-11 (own bit for bit unchanged), in a
    circuit within 1e-9; on the deck's heads (`scripts/multitrack_engine_study.py` ->
    `reports/multitrack/engine/`) the engine's crosstalk is the fitted model's within
    0.006 dB at 31.5 Hz-16 kHz, 0.28 dB at the 63 Hz null (-81.6 dB). The cross slope is read
    over the own head's reach either side of a block; the lateral spread's 1/x^2 tail past it
    costs at most 2 % (0.17 dB) on the deck's 14 mm reach (measured with a synthetic pattern
    against a 6-block window).
- **MT4: Sel-Sync's readout.** A tape part's optional fourth node `sync` (and `sync_l_h`,
  the record coil seen in playback) gives the record head's reading (its 51 um gap, the same
  pole faces, its field per ampere) of the tape the repro head reads at that sample, behind
  the record coil: the medium's `sync` (`TapeSync`), the IR's `Tape.sync_out`, a second
  output of the medium (and its neighbours' record-head cross EMF). That stretch of tape
  passed the record gap a head distance earlier, so the readout is the Sel-Sync monitor one
  head distance late: stored with a pass's print and advanced by the head distance, it is
  what a later pass hears in SYNC (the earlier pass's wow and flutter, not its own; the
  second order of a real overdub). No new storage concept: a pass's print already keeps its
  outputs.
  - **The finding (no published figure exists):** heard in Sel-Sync, the record head plays
    -0.8 dB at 2 kHz, -4.3 dB at 4 kHz, -12.3 dB at 6 kHz against the repro head, nulls at
    7.47 kHz (v / g at 15 ips), and comes back only to -13 to -23 dB above it (+0.2 dB in the
    bass). The engine's record-over-repro ratio is the heads' spectra's within 0.002 dB.
  - Alignment: an overdub recorded where pass 2 hears pass 1 in Sel-Sync plays back within a
    sample of pass 1 (`test_an_overdub_monitored_in_sync_lines_up_to_a_sample`, the
    transport shared, flutter on).
- **MT5's prerequisite: audio controls in a multi-rate part** (circuitsim's partition.rs,
  stream.rs). An audio control (`audio_inputs`) whose node is in one multi-rate part alone is
  that part's: it reads the control's samples from the stream's shared history as it reads
  the input (the same interpolation, each step a part of the sample's polynomial); the first
  part trims that history behind it. A plain control must still stay in the first part.
  Tested: an island driven by an audio control equals it driven by the input within 1e-12,
  and a stream fed in uneven chunks equals one run bit for bit
  (`tests/test_multirate_controls.py`).
- **MT5: the deck's circuit.** `config/circuits/ampex_300_4.yaml`, GENERATED by
  `scripts/make_ampex_300_4.py` from `ampex_351.yaml`: four 351 channels (each its own
  supply, as the 351-2's), channel 1 on `in`, channels 2-4 on the audio inputs `in2`..`in4`
  (read in the island), line outs `out`, `out_2`..; one master oscillator (channel 1's 1V6,
  1T5 and erase head; each slave's bias line, its own BIAS ADJUST `bias_adjust_f_2`.., from
  the master's erase-head node; the slaves' erase heads not modelled); the four record sides
  one island (20 steps); four tape parts on SCOTCH202@1, 70 mil tracks, one crosstalk group,
  each with its Sel-Sync readout on `sy`, `sy_2`..; the repro heads the 351's, wound for its
  output (rep_h_per_a x 234 / 70); 15 ips only. The record heads' coupling: a coefficient
  between neighbouring heads (`k_rec_heads`, provisional 0.02) and a capacitance between
  their hot ends (`c_rec_heads_f`), the latter sized by `scripts/ampex_300_4_trim.py
  --coupling` to the fit's record-side crosstalk at 10 kHz: the heads hang on the 6201's
  ~11 kohm, so a mutual inductance would need k ~ 0.2 to give it (not a shielded stack's),
  and the record term's slope in the circuit is the heads' (their resistance: ~6 dB an
  octave), not the fit's 6 + 12. **Trimmed:** 74 pF gives the fit's -45.7 dB at 10 kHz;
  in the circuit -57.7 / -51.8 / -39.4 dB at 2.5 / 5 / 20 kHz (the fit's record terms:
  ~-61 / ~-54 / ~-35 dB: 3 dB over at 2.5 kHz, where the playback terms' -54 dB rule, 4 dB
  under at 20 kHz); k 0.02 alone gives -74 dB at 10 kHz (`reports/multitrack/deck/trim.json`).
  Also `ampex_300_4_channel.yaml`: one channel, for the
  alignment (`scripts/align_300_4.py`: tape_align's steps on it, all but the 7-1/2 ips one);
  the deck then carries it, and the trim's `--bias` sets each channel's BIAS ADJUST on the
  deck to that alignment's bias current (four bias lines on the master, the heads' coupling).
  Tests `tests/test_ampex_300_4.py`; both builders agree (72 cases).
- **Aligned and trimmed** (`reports/multitrack/deck/channel_alignment.{json,png}`,
  `trim.json`; `config/ampex_300_4_trims.yaml`). The 351's procedure on one deck channel
  (SCOTCH202 on the 70 mil head): playback EQ 2R31 0.812 (0.63 dB rms 1-15 kHz), bias at
  36.7 pF (3.47 mA rms; the 351 on 111: 31.1 pF), 1C7 398 pF (0.84 dB rms), PLAYBACK LEVEL
  0.432 (700 Hz at -18.04 dBFS). **RECORD LEVEL runs out:** fully up, 0 VU in records 400 Hz
  at 0.92% THD, **0.54 dB short of operating level** (202's coercivity against the 351's
  record gain at its -10 dBm bridging input; `align_300_4.py` reports it rather than
  failing). A studio fed the deck hotter: a print's drive takes it (+0.5 dB for operating
  level at 0 VU). On the deck each BIAS ADJUST sets its head to that 3.47 mA within 0.12 %:
  ~46.6 pF (the master drives four lines and sags), the inner heads 0.15 pF less (their
  neighbours' bias through the heads' coupling).
- **The one-island print's speed** (`scripts/ampex_300_4_speed.py` ->
  `reports/multitrack/deck/speed.json`; production, the GPU kernel, a tone per track): **122x
  slower than real time**, the 351 alone 27x on the same panel. The island is the bound (busy
  117 s of 162 s, 3.6x the 351's), the rest 75 s (266 unknowns: four supplies, repro sides,
  output transformers). A 3-minute song as one run ~6 hours; in pieces (P3; each piece ~2.2
  cores) about 2 hours is the estimate, not measured.

### Built in the third session (2026-11-10)

- **MT5's profile:** `varimu unit --circuit ampex_300_4` (`varimu/measure/deck_suite.py`,
  registered in `varimu/measure/profiles.py`): the generated deck as it stands (its channel
  alignment and trims), production, noise on, the GPU kernel, 32 renders (58 min, 5 at once).
  Every channel tones at once on different frequencies (neighbours bands apart), 400 Hz THD
  against level on all four, silence for S/N, an edge track driven for crosstalk (1 -> 2 and
  4 -> 3 in one run). `reports/units/ampex_300_4_nominal/`. **All specs pass:**
  - response re 1 kHz, -10 dB, 30 Hz-15 kHz: -1.78 / +1.06, -1.77 / +0.86, -1.58 / +1.06,
    -1.57 / +1.06 dB (the 351's +-2 dB); the low end's dip at 30 and 70 Hz, -1.4 to -1.6 dB
    at 15 kHz;
  - S/N (400 Hz at 3% against the 30-15,000 Hz noise, AI-14's definition): 58.9 / 58.7 / 58.7
    / 59.6 dB (AI-14: "about 55" for four tracks on 1/2 in);
  - crosstalk 1.04 dB rms from MT3's fitted curve (63 Hz left out: the fit's null sits under
    the mains' 60 Hz hum and the hiss in a tone's band, measured -57 to -58 dB), the two
    edge pairs within 0.6 dB of each other, worst mid band -51.0 dB (AI-14: "around 50");
    16 kHz 2.5-2.8 dB under the fit (the record heads' coupling in the circuit rolls off
    above 10 kHz, as the trim said);
  - rails within 5.3 %.
  - **Found: the master's channel records dirtier.** 1 % THD at +0.29 dB re 0 VU on channel
    1 (0.94 % at 0 VU, the channel alignment's 0.92 %), +1.52 to +1.57 dB on the three
    slaves (0.69-0.70 %), 3 % at +5.4 against +5.9 dB. Each head's bias current is the same
    3.47 mA (the trim); what differs is how it gets there (the master's own bias network
    against the slaves' lines off its erase-head node). Not chased.
- **Pieces with control inputs** (TAPE_SPEED_PLAN.md P3 on the deck): the app's
  `render::render_pieces_controls` and Python's `fast.run_transient_chunked(controls=)`,
  step for step: each piece takes its stretch of every control, an audio control faded in
  as the input is. Tests: `render::tests::pieces_carry_an_audio_control` (the test circuit
  `config/circuits/audio_input_test.yaml`, two 12AX7 stages, `in2` an audio input: < -80 dB
  from one run), `tests/test_chunked.py::test_pieces_carry_an_audio_control`.
- **MT6: the deck in the session** (`varimu_app::deck`; decision 3). The session's `deck`
  (saved in `session.json` only when there is one): the device, each tape track's session
  track (by id), a record trim per tape track, the panel's values, noise. A trim is set once
  when a track is assigned: the lane's loudest 8 s to the alignment level, as an insert's
  first trim, **+0.5 dB** (`deck::DRIVE_DB`: 202's operating level at 0 VU). A **tape
  print** records every assigned lane (its clips, before inserts and strip; a stereo lane's
  mid: a tape track is mono) at once from the earliest lane's start, at production in
  P3's pieces, shifted back by the head distance, each line out brought back to its lane's
  level by the trim's inverse; the Sel-Sync readouts `sy`.. are kept beside it, advanced
  the same (in time with what was recorded: what a later pass hears in SYNC). Cached in
  `<session>/prints/deck-<key>/` (`tape<k>.wav`, `sync<k>.wav`, `deck.json`). Each assigned
  track then plays its tape track in place of its lane (`Track::tape`, `tape_playing`;
  `lane_lr`, `mix_clips`, `lane_span` follow it, `clips_lr` is the raw lane), and its
  inserts print the tape (`Track::source_signature` keys them); an edited lane plays raw
  until the deck prints again; a print of older deck settings plays on, stale. The Session
  view's **Tape deck** window (toolbar): a track per tape track, trims, noise, Print to
  tape, Cancel, Remove; on load the print is looked up in the cache (SE1: nothing prints
  until asked). Headless: `cargo run --release -p varimu-app --example tape_print --
  --session DIR [--stems DIR --tracks "a,b,c,d" [--from S --seconds S]] [--measure CHUNK_S
  --out DIR]`. Tests: `deck::tests`, `session::tests::a_tape_deck_print_plays_in_place_of_its_lanes`.
  - A 2 s smoke print (90-92 s of the stems): each tape track 0.8-1.9 dB under its lane's
    broadband level, the voices within 2 samples of their lanes, the bass 36 samples (the
    tape's low-end phase).
- **The song on tape: started, stopped (the user's call).** The session `sessions/did she
  mention my name (tape)` (git-ignored) holds the four full stems at 48 kHz with the deck
  assigned (**the user's assignment: 1 bass, 2 guitar, 3 lead vocal, 4 harmonies**; trims
  set), not printed. Its print (157 s, six 30 s pieces at once, the GPU kernel) ran 26 % in
  46 min: **about 3 hours for the song** (each piece needs ~2.2 threads, six at once
  overcommit the 8 cores / 16 threads, and each slows). The user stopped it: 3 hours a song
  is too long, the user will think about what to do. Options put to the user:
  1. **Four islands** (a record side per track; the master oscillator's bias and the heads'
     coupling reach each a sample late): probably 3-4x faster per piece; measure against the
     one-island print (the reference), as decision 7 asked.
  2. **A reduced tape tier for the deck** (DELAY_PLAN.md's reduced tape, as the 351 insert's
     live tier, ~0.5x real time): the grey box for drafts, the literal print kept for finals.
  3. Print overnight as is (cached once printed).
- **Not run (deferred with the print):** the 30 s seam check of the deck's pieces against one
  run (`examples/tape_print.rs --measure 10` on 90-120 s, then `scripts/deck_pieces_study.py`
  -> `reports/multitrack/deck/pieces.json`).

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
- 2026-11-10 (second session, on main; "Built in the second session" above): MT3 in the
  engine (a group of tape elements; the fit's reference corrected, 1.64 dB rms), MT4's
  Sel-Sync readout and its finding (the 51 um gap's null at 7.47 kHz), audio controls inside
  a multi-rate island, MT5's deck (`ampex_300_4.yaml`, generated, aligned per the 351's
  procedure, the record heads' coupling and each BIAS ADJUST trimmed on the deck), its
  print at 122x real time. Found: RECORD LEVEL is 0.54 dB short of operating level on 202.
  Not done: MT4's figures (none published: the model's response is the finding), MT5's
  profile (`varimu unit --circuit ampex_300_4`: no suite registered for the deck yet), a
  piece-wise print's measured speed. **Next: MT6** (the session's track assignment, still
  the user's call, and the one-pass tape print of the four stems; the deck's Sel-Sync
  outputs `sy`.. stored with the print for later overdubs).
- 2026-11-10 (third session, on main; "Built in the third session" above): MT5's profile
  (every spec passes; the master's channel records ~1.2 dB dirtier), pieces with control
  inputs (app and Python), MT6's deck in the session (`varimu_app::deck`, the Tape deck
  window, `examples/tape_print.rs`), the user's track assignment (1 bass, 2 guitar, 3 lead,
  4 harmonies). **Parked by the user:** the song's tape print takes ~3 hours (stopped at
  26 %); the user will decide between four islands, a reduced deck tier, or printing
  overnight. MT6's done-when (the song printed and played) is open; so are the seam check,
  Sel-Sync overdubs, bounces and punch-in.
- 2026-11-11 (the user: "I can afford a 3 hour run"): **the song printed**, MT6's done-when met.
  `examples/tape_print.rs --session "sessions/did she mention my name (tape)" --out
  reports/lightfoot_mix/tape`: 10,656 s (67.8x real time, six pieces at once while other
  renders ran), key `ac920f35...`; the session plays its tape tracks. Measured against the lanes
  (`scripts/lightfoot_tape_effect.py`): levels -0.6 to -1.2 dB, the response within -1.8 / +2.0
  dB from 31 Hz to 6.3 kHz, the silent harmonies track at -72.6 dBFS rms (hiss, a trace of the
  lead's crosstalk). Then mixed with and without tape (HEADLESS_MIX_PLAN.md's status;
  `reports/lightfoot_mix/NOTES.md`). Still open: the seam check, Sel-Sync overdubs, bounces,
  punch-in.
- 2026-11-11, **an artifact the user heard** in the song's tape tracks: a ~5.4 kHz chirp on each
  bass note (bass strongest, guitar too, the voices none). Measured on the files: the 5.2-5.8 kHz
  band follows the bass level (correlation 0.76, its neighbour 0.42) and rises 7-9 dB over its
  neighbour 50-300 ms after each of 231 onsets, peak ~5.44 kHz (5.37-5.53). Suspected (not
  confirmed): the ~100 kHz bias residue aliasing at a 96 kHz sampling point (90.6 or 101.4 kHz
  folds to 5.4 kHz), its residue growing with the record drive. The test, a 3 s bass excerpt at
  2x vs 3x oversampling (`examples/tape_print.rs --oversample N`: an alias moves with the rate),
  takes 15-20 min per run and was stopped; parked by the user. The song's print would be redone
  after a fix.
- 2026-11-12, **the chirp found** (overnight, branch `tape-chirp`; scripts `chirp_ultrasonic.py`,
  `chirp_medium.py`, `chirp_alias_map.py` -> `reports/tape/chirp/`): **the deck's, not the 351's,
  and numerical.** The same 3 s bass (the song at 25 s) through the 351 (at the song's level and
  +6 dB) has no rise in 5.2-5.8 kHz (2.6 dB after each note, the dry 2.8) and no line 1-23 kHz
  the dry lacks but a steady 21.2 kHz at -64 to -70 dB re the total; the deck with the bass alone
  on track 1 has it (14.9 dB; the song 16.9), so not crosstalk. Its picture: a ~800 Hz wide band at
  5.1-5.9 kHz and a copy at 10.4-11.4 kHz while a note sounds, striped by the bass's period.
  - **The master oscillator runs at 95.86 kHz** (the erase head's node at 192 kHz, no decimation),
    the 351's at 92.99 kHz: four bias lines load the deck's tank.
  - **Not the island's box average** (`decimate: fir` on the nine record-side sections: the same
    14.9 dB) **nor the substeps** (the medium alone at 10, 20 and 40: the same to 0.1 dB).
  - **The tape's cells.** The medium alone (circuitsim's TapeStream on the deck's and the 351's
    media, an ideal sine bias plus a tone) makes it at 95.865 kHz and not at 92.99 (-57 against
    -73 dB re the tone in 5.2-5.8 kHz), on Scotch 202 and 111 alike; the line moves 8 Hz per Hz of
    f_b (4.9 / 5.6 / 6.5 kHz at 95.765 / 95.865 / 95.965 kHz): **|8 f_b - v / ds|**. With the
    literal bias the recorded pattern of the field's peaks (two per bias cycle, ~1.99 um apart at
    15 ips) is point-sampled by cells of ds = v / (7.62 f_nominal) = 0.5 um, sized for the nominal
    100 kHz (the beat then at 38 kHz); at the deck's 95.9 kHz it falls to ~5.5 kHz, at the 351's
    93.0 kHz to ~18 kHz (the medium alone: a line at 17.4-17.7 kHz, -68 dB re the tone; the
    flutter smears the beat into a band). The bass modulates the pattern's residue (the stripes).
  - **Shorter cells remove the medium's alias.** At 0.25 um (and 0.125) the medium alone has no
    line above -82 dB re the tone under 20 kHz at 95.865 kHz; 0.25 um was within 0.3 dB of 0.5 um on
    No. 21 (TAPE_PLAN.md TM2 step 7). Built: the tape part's optional `cell_m` (both builders;
    absent, every IR as before; a reduction keeps its own ds), the deck's tape parts at 0.25 um
    (`make_ampex_300_4.py`'s `TAPE_CELL_M`, its channel file too). The cost: the recording
    kernel's cells double.
  - **But the deck's chirp stays** (the same excerpt on 0.25 um cells: 15.6 dB, peak 5.42 kHz,
    the 10.8 kHz copy: unchanged). So a second mechanism dominates in the circuit, near the same
    frequency: the record island's own numerics, which the medium-alone runs (an ideal sine
    bias) can't show. Its candidate: the oscillator's and head driver's waveform integrated at 20
    substeps of 192 kHz without error control, its error periodic in where the bias cycle falls
    on the substep grid, beating at m (fs - 2 f_b) = 20 x 0.27 kHz = 5.4 kHz exactly (the FIR
    test above only changed the supply currents the island hands on, not the head current the
    tape senses per substep).
  - **Confirmed (06:35): the record island's substeps.** The first 1.2 s of the excerpt (three
    notes, trim +13.6 dB: 2 dB hotter than the 3 s run) with the island and the tapes' literal
    bias at 40 substeps: the 5.2-5.8 kHz band rises 3.9 dB after each note against the dry's 3.2
    (at 20 substeps, the same 1.2 s: +11.9 dB over the dry), nothing at 10.8 kHz, no band
    1-23 kHz over +4.7 dB; its spectrogram has the bass's harmonics and the hiss only. The 351's
    oscillator puts the same beat at 65.7 kHz (out of the band), which is why it never showed
    there and why the 351's noise-floor checks of the record side's numerics (P4's TR-BDF2 with
    tube tables, TAPE_SPEED_PLAN.md) couldn't see it. Options (the user's): 40 substeps on the
    deck (its record side's cost doubles), or the island's method (esdirk4 without tables at
    20, P4's previous setting, tested next), then the deck re-aligned and the song reprinted.
  - **Open (the user's):** the deck's re-alignment and trims on 0.25 um cells (align_300_4.py,
    ampex_300_4_trim.py: their settings move little, measured below when done), the song's
    reprint (~3 h), and the 351 family (its beat at ~18 kHz, -68 dB re a hot tone: near the top of
    the band; a BIAS ADJUST that moves its oscillator toward 96 kHz brings it down into the band):
    the same `cell_m` there moves every 351 print and needs its re-alignment (~1 h).
