# midi/

MIDI of songs, for trying the instruments on real parts (`scripts/clavinet_render.py --midi F`,
`scripts/rhodes_render.py --midi F`, ...). Only this README is committed: the files are fan
transcriptions downloaded from the web. The songs and the transcriptions are other people's
copyright, so they are kept for private testing and never redistributed (like `data/clips/`).

Layout: `<song>/` holds the files as downloaded, `<song>/parts/` one type-0 file per channel
(tempo and time signature kept), so one instrument's part can go to one device. The project's
reader (`varimu.rhodes.midi.read`) merges every channel of a file, so feed it a part, not a
whole song.

## superstition/ (Stevie Wonder, 1972), fetched 2026-11-06

| File | Source | sha256 |
|---|---|---|
| `bitmidi_98524_superstition.mid` | https://bitmidi.com/uploads/98524.mid | `1bc280ffd2b4c5b5e3b719f192fc12433adc0aa32b48e461913f646a4f6b86a3` |
| `bitmidi_97097_stevie_wonder.mid` | https://bitmidi.com/uploads/97097.mid (also freemidi.org #6659) | `1869e7c6b60f30bdcd7a10eb012747e4cb426658772718bb4247f9bf541a178c` |
| `bitmidi_75081_mommidi.mid` | https://bitmidi.com/uploads/75081.mid | `5a8b89afab2dfa30c0f70c8c676f8d1b1a60e4fcf3c6d68a4193982bae6e373b` |
| `bitmidi_111008_wonder_k.mid` | https://bitmidi.com/uploads/111008.mid | `5b6b070a15f932b4afcd6e060cd5d3b1aaf5e117ef949ad1bfe2f087981dc0d0` |

There are two independent transcriptions:

- **A** (98524, 97097 and 75081 have the same notes, voiced differently): 101 BPM, 7 parts.
  The clavinet is one part, `parts/A_ch03_clavi.mid`: 1148 notes, MIDI 32-66, velocities
  72-127, 65% on the 16th grid. 98524 is the cleanest of the three (named tracks).
- **B** (`wonder_k`, a GS-style arrangement): 103 BPM, 15 channels. The clavinet is two parts:
  a low riff `parts/B_ch12_clavi.mid` (809 notes, 39-54) and a high part
  `parts/B_ch13_clavi.mid` (1367 notes, 54-63), together in `parts/B_clavi_both.mid`. Its
  velocities are more varied than A's.

The record has about eight overdubbed clavinets, so either file is a reduction. None is
authorized or checked against the record; audition before trusting a part.
