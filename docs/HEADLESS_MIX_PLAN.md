# Headless mixing: from a folder of stems to a final mix, by Claude

Drafted 2026-11-05 (the user's idea: "it would be a neat experiment to see if you could mix a
song end to end and I could listen and see what it sounds like"). Nothing built. The first
song is the user's cover of Gordon Lightfoot's *Did She Mention My Name*
(`sessions/did she mention my name/`: guitar, bass, lead vocal, harmony).

## The idea

Claude can't hear. It can measure (levels, spectra, resonances, masking, phase between mics,
pitch and timing between parts, room content) and apply standard engineering rules of thumb
to the measurements. The experiment: Claude takes a song from stems to a finished mix with the
project's own tools (the room as the recording, the devices as inserts and sends, tape on the
bus), working only from measurements, and the user listens. Two questions:

1. Can the whole pipeline run without the app, and produce exactly what the app would play?
2. How close does a mix made from measurements get to one made by ear?

The answer to the second is interesting either way.

## The key decision: the session is the mix file

No new mix format. Claude edits a session's `session.json` (tracks, inserts with their
settings, trims, wet shares, levels, pans, and later sends and automation) and the room's
`rooms/scene.json`, and a headless tool renders exactly what the app plays. Then:

- a mix Claude makes opens in the app as an ordinary session: the user hears it, moves a
  fader, sees every choice;
- what Claude measures is bit for bit what the user hears (same prints, same mixdown);
- the app's own features (prints, room renders, export) are reused, not reimplemented.

Claude works on a copy of a session (`sessions/<name> (claude mix N)/`), never the user's.

## What runs headless today (2026-11-05)

| Stage | Headless | How |
|---|---|---|
| Analysis | yes | Python; the repo's BS.1770 (`scene.sounding_rms`), `varimu/separation/grouping.py` (temporal coherence, onsets, harmonic cancellation, SNRenv), `listen.difference` (tone vs character) |
| The room | yes | `scripts/room_print.py SCENE` (the Room view runs the same command: `room.rs`); `--balance` gives each source's stem through every mic's chain |
| Inserts | mostly | `examples/print.rs`: a file through a chain of devices (`--device`, `--set`, `--trim`, `--quality`), cached as the app prints. Missing: `--wet` (`print::Slot::wet` exists); mono only |
| Tape | per machine | `scripts/print_351.py`, `print_351_echo.py` |
| Session | no | `Session::load`, `Session::mixdown`, `Session::export_problems` exist as library calls; only the app calls them |

What doesn't exist at all, in the app either: sends and FX tracks (SESSION_FX_PLAN.md F4),
inserts on the mix bus, fader automation (a track's level is one `volume_db`).

## Milestones

**H0. A headless session render.** `varimu-app --headless SESSION --export [--final] [--out
DIR]` (or an example, `examples/session.rs`): load the session, render its room when the scene
changed (`room.rs`'s `room_print.py` call, its tracks placed as `SessionView::add_room_tracks`
places them), print every insert at its play quality (production with `--final`, which also
renders MIDI takes at production, as ⤓ Export final… does), mix down, export the mix WAV, its
`.json` of sources and the stems. Also `print.rs --wet`. Progress and ETAs on stderr (Claude
watches long renders).
*Done when:* the headless export of `did she mention my name` equals the app's ⤓ Export mix…
of the same session bit for bit (a test on a small scratch session; the real one checked once).

**H1. The analysis toolkit.** `scripts/mix_analyze.py SESSION_OR_FOLDER [--reference FILE]`
-> `reports/mixes/<name>/`: per stem and for the mix,
- levels: peak, true peak, integrated / short-term LUFS, crest factor, loudness range, the
  level distribution (how compressed a part already is);
- faults: clipping, DC, hum (50 / 60 Hz and harmonics), noise floor, clicks;
- spectrum: long-term average spectrum, narrow steady resonances (frequency, Q, level),
  sibilance and plosives located in time;
- between parts: masking per critical band over time (the glimpse proportion and SNRenv of
  the lead against the rest), onset timing (harmony vs lead), pitch (harmony vs lead, cents
  per phrase), polarity and delay between mics on one source (comb filtering from leakage);
- room: direct-to-reverberant and decay estimated from note offsets (how much room a stem
  already has: re-amping a roomy stem through the room doubles it);
- stereo: correlation, mid / side, mono compatibility;
- a reference: the same measures on a reference track, and the differences;
- plots Claude reads as images (spectrograms, LTAS overlays, level over time).
*Done when:* it finds faults planted in test stems (hum, a clip, a resonance, a harmony 30 ms
late and 20 cents flat, a polarity flip) and reports no fault on clean ones
(`tests/test_mix_analyze.py`).

**H2. The mix features a 1968 engineer had.** App features wanted anyway, built for the app
first and so headless through H0:
- **Sends and returns** (SESSION_FX_PLAN.md F4): the plate as one shared reverb;
- **the echo chamber:** a Room-view room fed from a send (a speaker source, two mics), the
  1960s New York studios' vocal reverb, out of physics the project already has;
- **a mix-bus chain:** inserts on the stereo mix (the 670, the 351-2); stereo prints;
- **fader automation:** breakpoints per track in `session.json`, followed by the player and
  the mixdown (vocal rides were much of a 1960s mix);
- **a de-esser from existing parts:** the keyed 670 with a high-pass on its key
  (SIDECHAIN_PLAN.md K4).
A console channel (preamp, mid EQ, high-pass) waits for CHAINS_PLAN.md's WP2 (the UA 610);
the experiment doesn't. Each feature is done when the app plays it and H0 exports it.

**H3. The experiment.** Claude mixes *Did She Mention My Name* from its stems:
1. analyse the stems (H1): what they are, how much room they carry, faults;
2. record them in the room (a scene: close mics per part, a gobo between guitar and vocal,
   a room pair), or skip the room if the stems already carry one;
3. inserts, sends, bus, levels, pans and rides, iterated at draft quality against H1's
   measures (and the reference's, if there is one);
4. the final at production, exported.
Claude's rules for itself: few moves, each backed by a number; no move whose measured effect
is below what the user found audible (Phase 5's lesson). Every decision goes into
`reports/mixes/<name>/NOTES.md` with its measurement and its reason, so the user can disagree
with a specific one.
*Done when:* the export is in `reports/mixes/<name>/` with its notes and the session copy
opens in the app.

**H4. The user listens.** Claude's mix against the user's own mix and the raw stems,
loudness-matched (Hard rules), blind if the user wants (the app plays the files; nothing new
to build). The user's notes go back as corrections; a second pass shows whether Claude moved
toward them. Notes on what measurement missed go into this plan, as material for H1.

## Decisions (the user's, open)

1. **Period-faithful or vintage gear with modern freedom?** Period-faithful: three-way pans
   (left / centre / right), a 1968 track count, rides by hand only, a plate or a chamber.
   The sharper experiment; with a reference it is measurable.
2. **A reference track** (a Lightfoot recording of the period), which turns taste into a
   target to measure against.
3. **Time per pass:** production renders through the room and inserts take minutes to tens of
   minutes; draft keeps a pass well under an hour.
4. **H2's scope before H3:** the experiment can run on H0 + H1 alone (inserts at wet shares,
   no sends, no rides), or wait for some of H2 (rides and the chamber matter most here).

## Background: what Lightfoot's records used

*Did She Mention My Name?* (recorded December 1967, released 1968, United Artists) was
produced and arranged in New York by John Simon (Leonard Cohen, The Band), Lightfoot's first
orchestration (web: https://en.wikipedia.org/wiki/Did_She_Mention_My_Name%3F,
https://www.udiscovermusic.com/stories/gordon-lightfoot-did-she-mention-my-name-album/). The
studio and engineer weren't found (the original liner notes or Discogs would say). The Reprise
albums from the 1970s (*Sundown*, November 1973) were recorded at Eastern Sound, Toronto, many
engineered or mixed by Ken Friesen (web:
https://en.wikipedia.org/wiki/Sundown_(Gordon_Lightfoot_album)). A Mix article lists Friesen
using U47, U67, AKG C24, RCA 44, Coles 4038 and a Neve 8014 with 1073s, on an unnamed project
(web: https://www.mixonline.com/?p=77042): his habits, not a Lightfoot recipe.

## Status

*Updated at the end of every session.*

- Nothing built. Next: the user's decisions above, then H0.
- 2026-11-10: a brainstorm on the stems (measured from `stems/Did she mention my name/full/`,
  the user's wish: start from them, not the session's setup). The gear it wants that no plan
  has is in [PERIOD_GEAR_BACKLOG.md](PERIOD_GEAR_BACKLOG.md) (the 1960s multitrack deck first).
- 2026-11-11 (unattended, the user's ask: mix it like a Lightfoot record and hear it through the
  4-track): an early H3 without H0 or H1. `scripts/lightfoot_mix.py` (`--version dry|tape`,
  `--stage match`): inserts printed by `examples/print.rs` at production (the guitar's boom cut
  with the EQP-1A, the vocal's presence and a 670 at ~3 dB median GR, the harmonies on a 670),
  faders by loudness re the lead, constant-power pans (guitar half left, harmonies half right),
  vocal rides by rule (+-3 dB max), a post-fader send into the stereo EMT 140; no bus
  processing. The same moves on the dry lanes and on PERIOD_GEAR_BACKLOG.md's tape print, each
  insert's trim offset by the track's level so both drive the inserts alike; the pair
  loudness-matched. Every move and its measurement: `reports/lightfoot_mix/NOTES.md`. Next: the
  user listens (H4).
