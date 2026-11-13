# AM1: record forensics, first pass

2026-11-13. `scripts/split_reference.py` + `scripts/record_forensics.py`; per-label JSON here,
`compare.json` / `compare.png`.

## Material

- **The reference:** the user's copy of Rhino's *Complete Greatest Hits* (2002; a YouTube rip,
  so an Opus-coded source saved as FLAC at 48 kHz), split at its silences into its 20 tracks
  (`cache/magic/reference/lightfoot_complete/`). Tracks 1-6 are the United Artists recordings
  of 1965-69 (gordonlightfoot.com's page for the album: "United Artists original studio
  recording"), labelled **1960s**. Tracks 7-14 (Reprise / Warner, 1970-76), **1970s**.
  Tracks 15-20 (1978-1993 and a rerecording), **later**. The 2002 remastering is shared by all
  three, so differences between them aren't the remaster's.
- **The cover** (the user's, modern gear): `cover_plain` (the four session lanes at the mix's
  faders and pans, nothing else), `cover_mix_no_tape` and `cover_mix_through_4track` (the
  1968-style mixes in reports/lightfoot_mix/). Each through Opus at 160 kbit/s and back
  (`--codec opus160`) so the codec is on both sides.

## What separates the 1960s tracks from Lightfoot's own later ones

Medians [quartiles] over tracks. The cover columns are one file each.

| Fingerprint | 1960s | 1970s | later | cover plain | 1968-style mix | + 4-track |
|---|---|---|---|---|---|---|
| L/R correlation | **0.55** [0.5, 0.6] | 0.81 | 0.84 | 0.98 | 0.93 | 0.93 |
| side / mid (dB) | **-5.4** | -9.7 | -10.6 | -7.8 | -13.5 | -13.6 |
| L/R coherence at 125 Hz | **0.16** [0.1, 0.3] | 0.77 | 0.92 | 0.98 | 0.89 | 0.90 |
| L/R coherence at 8 kHz | **0.45** | 0.68 | 0.81 | 0.73 | 0.97 | 0.97 |
| highest band within 40 dB of 1 kHz | **12.7 kHz** [10.7, 15.2] | 12.7 | 16.0 | 12.7 | 20.2 | 20.2 |
| tilt 100 Hz-10 kHz (dB/oct) | -5.8 | -5.4 | -5.3 | -8.8 | -5.0 | -4.8 |
| crest at 63 Hz / 125 Hz (dB) | **11.3 / 12.3** | 13.3 / 14.1 | 15.4 / 15.8 | 14.7 / 13.1 | 12.1 / 12.5 | 11.9 / 12.4 |
| floor follows the program (slope / corr) | **0.33 / 0.23** | 1.00 / 0.46 | 1.17 / 0.48 | 0.36 / 0.17 | 1.50 / 0.61 | 1.04 / 0.58 |
| 60 Hz line above its neighbours (dB) | **4.5** | 2.2 | 1.1 | 3.5 | 3.7 | 4.1 |
| short-term level spread p95-p10 (dB) | 7.2 | 7.9 | 7.3 | 10.7 | 10.4 | 10.7 |
| comodulation (band envelopes) | 0.16 | 0.23 | 0.23 | 0.26 | 0.18 | 0.18 |
| waveform asymmetry (dB) | 1.08 | 1.06 | 0.69 | 1.04 | 1.97 | 1.09 |

Readings, strongest first:

1. **Stereo is the biggest era marker, and it's an arrangement of the mix, not a device.** The
   1960s tracks are wide and decorrelated, *in the bass too* (coherence 0.16 at 125 Hz: the
   bass on one side or picked up by separate mics). Late-60s three-track / four-track stereo did
   this. Every later track and the cover's mixes are near-mono in the bass. Nothing in our chain
   would produce it; the pans and the mic setup do. This is an input to HEADLESS_MIX_PLAN and to
   the Room view, not to a device model.
2. **The top end stops around 12.7 kHz** (10.7-15.2 over the six tracks); the later tracks reach
   16 kHz through the same codec and remaster, so it's the recordings'. The cover's mixes reach
   20 kHz. One generation of our 351 at 15 ips doesn't cut there (its response passes +-2 dB to
   15 kHz): AM4's generations and the lathe / cartridge, which aren't built, are the candidates.
3. **The noise floor is steady in the 1960s tracks** (it barely rises with the program: slope 0.33)
   and follows the program in the later ones. With this proxy that means more stationary hiss
   relative to the program's top end: hiss you can hear, not hiss that fuses. AM7 found our tape's
   own noise is the signal-following kind. The difference is in the hiss's level, not its kind.
4. **The bass is less peaky** (crest 11-12 dB at 63-125 Hz vs 13-16 later). The 1968-style mix
   already sits there (12.0 / 12.4); the plain cover doesn't (14.7 at 63 Hz).
5. **A mains line**: 60 Hz stands 4.5 dB over its neighbours in the 1960s tracks, 1-2 dB later
   (music has energy near 60 Hz too, so this is weak).

Not separating: overall tilt, level spread (the 2002 remaster sets all of them alike),
comodulation, asymmetry. The tuning fingerprint is unreliable on mixes (the plate and EQ moved
the cover's "drift" from 4 to 20 cents): it isn't used.

## Limits

One artist, one remaster, a codec on the reference. `floor_follow` is a proxy (the program's
own highs confound it); compare it only within material. The cover columns are one song each, so
their numbers have no spread.
