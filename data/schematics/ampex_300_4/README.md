# Ampex 300-4 (four tracks on 1/2 in) sources

Gathered 2026-11-10 for PERIOD_GEAR_BACKLOG.md's PG1 (the tube Ampex 300-4: the 351's
electronics, four channels, Sel-Sync). All files retrieved on 2026-11-10 with curl. "p N" is
the PDF page index; "(N)" the printed page. The PDFs are git-ignored, like `../ampex_351/`'s:
fetch them from the URLs below (sha256 prefixes to check).

| File | What it is | Source URL | Pages |
|---|---|---|---|
| `AmpexMultiChannelRecording.pdf` | Ampex, **"Technical Notes on Multi-Channel Recording"**, Bulletin AI-14, revised Jan. 1959 (scanned by Timothy Hughes, 2005) | web: https://bh.hallikainen.org/uploads/AmpexMultiChannelRecording.pdf | 22 |
| `Ampex_head_assy.pdf` | Ampex Field Engineering Bulletin 70178, "Head Assemblies", 2/76: every catalog head assembly's part numbers | web: https://bh.hallikainen.org/uploads/harold/Ampex%20head%20assy-s.pdf | 21 |
| `AmpexProfessionalAudioCatalog1970.pdf` | Ampex Professional Audio catalog, 1970 (AG-440B, MM-1000, ...): specifications | web: https://bh.hallikainen.org/uploads/harold/AmpexProfessionalAudioCatalog1970.pdf | 8 |

Also used: `../ampex_351/Ampex354_TM-2011B.pdf` (the 354 manual's primer, 1960) and
`../ampex_351/Ampex351.pdf` (the 351's master / slave bias).

sha256 (first 16 hex digits): AmpexMultiChannelRecording `64bd541d037b6271`, Ampex_head_assy
`e34fc1d1217ed6f6`, AmpexProfessionalAudioCatalog1970 `93af07f56c732ba3`.

## What they say

### The format (four tracks on 1/2 in)

- **354 manual p 44 (12), head layout figure:** "4 track master, or duplicator master": four
  **70 mil** tracks **60 mil** apart on 1/2 in tape (three-track master: 100 mil tracks, 85 mil
  apart). Its relative S/N row is consistent with S/N in proportion to the square root of the
  width: 4 track -1.5 dB re a 100 mil track (10 log10 0.70 = -1.55), full track (234 mil)
  +3.7 dB (+3.69).
- **AI-14 p 13 (13):** "Using tape one-half inch wide, four channels are the maximum ... track
  width of **80 mils** is used, with inter-track spacing of 60 mils. Signal-to-noise ratio ...
  about **55 decibels**, crosstalk rejection around **50 decibels**." Four 80 mil tracks and three
  60 mil gaps fill all 500 mil with no edge margin, so the build takes the 354 manual's 70 mil
  (the NAB 1/2 in four-track layout: 70 mil tracks on 130 mil centres). The bulletin's S/N and
  crosstalk figures stand.
- **AI-14 p 17 (17):** "Model 300 equipment may be had with half-inch tape in three- and
  four-channel versions, with separate erase heads. One-inch tape on Model 300 permits six- or
  eight-channel models." Speeds 7.5 and 15 ips; NAB and AME equalization (AME: Ampex Master
  Equalization, about +7 dB weighted S/N; NAB is the build's).
- **FEB 70178 p 15:** the 300-4 four-track 1/2 in head assembly 02-31055-02 (repro 4040558-01,
  record 4040558-02, erase 4040564-01); the AG 300-4's 4020264-01. Part numbers only: no
  dimensions or gaps.
- **AI-14 p 16 (16):** three-track 1/2 in heads are "cast" (gaps in line within 0.2 mil);
  multi-track stacks otherwise "sandwich" construction (heads stacked and bolted).

### S/N and track width

- **AI-14 p 13 (11):** noise is the tape's in a good machine: doubling the width doubles the
  output (+6 dB) and the noise power (+3 dB), so +3 dB S/N. S/N is defined as 400 Hz at 3%
  total distortion against the rms noise of erased and biased tape, 30-15,000 Hz.
- **1970 catalog p 2:** AG-440B four-track (1/2 in) S/N 60 dB at 15 ips (full track 66, two
  track 63); MM-1000 / AG-440-8 crosstalk 50 dB min at 500 Hz. Later, solid-state machines:
  references, not the 300's figures.

### Crosstalk

- **354 manual p 44 (12):** "Typical crosstalk vs. frequency curve on adjacent channels of an
  Ampex three channel Model 300" (digitized: `data/datasheets/ampex_300_crosstalk.csv`, its
  provenance `ampex_354_manual.provenance.yaml`, the y-label misprint there). Two mechanisms
  (the text beside it): "At long wavelengths magnetic coupling occurs in reproduce between the
  signal recorded on one track and the reproduce head of the other track. At high frequencies,
  the mutual inductance and capacitance between the two record heads causes the signal from
  one record head to be present in the other record head, and therefore to get recorded on
  that other track." An 85 mil spacing with good shielding is "a good compromise".
- **AI-14 p 13 (10):** the long-wavelength part "could not be reduced ... the sheer geometry of
  the head structure ... the direct pick-up by one head of flux passing the other head." Inter-
  winding shields reduce the rest. Crosstalk is quoted "effective": at a frequency of greatest
  hearing sensitivity; "At very low and very high frequencies, rejection is usually much less."
- **354 manual p 47 (15):** 60 dB mid-band rejection is adequate for independent tracks.

### Sel-Sync

- **AI-14 p 11 (8):** "a good recording head can serve reasonably well as a playback head."
  Any record head in the stack can be switched to its channel's playback amplifier without
  affecting the others. "What he hears in his headphones, when he uses a recording head for
  playback, is not the high quality signal he receives when he uses his regular playback head,
  but it is perfectly adequate for him to keep in time and tune." No response figure.
- **AI-14 p 3 (front matter):** a photo of three 351-style channels with a SEL-SYNC panel
  (NORMAL / SYNC switch per channel).
- **AI-14 p 18 (18):** the eight-channel Model 300 with Sel-Sync for Les Paul (1 in tape).

### Bias: one master oscillator

- **AI-14 p 14 (14):** "Completely separate control over upper and lower tracks of a two-channel
  recorder can be achieved through the use of a **Master Bias Oscillator** and two **Slave**
  electronics chassis. This facility is available on Series 300 and Series 351 recorders."
- **351 manual p 21-22 (3-6, 3-7):** the 351-2's master electronic assembly feeds the slave's
  record head bias through J9 BIAS COUPLING (cable 05-0160-02). The multichannel deck is wired
  the same way: one oscillator, every channel's head on it.

## Still missing

- The Model 300's own manual (transport, head stack dimensions, the Sel-Sync switching and its
  equalization). The elektrotanya "Ampex 300 section 1" service manual is behind a gated
  download; the Ampex Virtual Museum (recordist.com/ampex) wasn't searched yet.
- Scotch 201 / 202 data beyond Eilers' table: the AES Historical Committee's archive of 3M
  technical data sheets (https://aes.org/?p=60055) refuses scripted fetches (HTTP 403). A 2012
  JAS paper cites "Scotch Magnetic Tape, Technical Data #111, 201, 202, 203 (69.06)".
