# Coles 4038 (STC 4038) sources

The chains build-out's WP8 (docs/CHAINS_PLAN.md), found 2026-11-06. The BBC PGS ribbon of
1953, made by STC as the 4038 (BBC patents 738,864 and 742,006) and by Coles since. The PDFs
are not committed (they live in the git-ignored cache); URLs, sha256 and sizes are below.
Transcribed 2026-11-06; recheck a value against its page when it goes into a file.

## stc: STC brochure C/PA22 Ed. 3/2 (1961), 4 pages

- web: http://www.coutant.org/stc/4038/4038.pdf (693,615 bytes, sha256
  `58d667fed1204c90864b2aea230d5caa40d71a46e19a3b6ffbe446f0e225f511`). Page 3 is the
  specification of the **4038-A**, typical values:
  - sensitivity 0.06 mV per microbar open circuit = -85 dB re 1 V per microbar (= 0.6 mV/Pa,
    -64.4 dBV/Pa; Wikipedia / Coles' modern -65 dB re 1 V/Pa agrees);
  - **nominal impedance 30 ohm** (works into a high impedance against 30 ohm, may be
    terminated as low as 50 ohm; the input transformer must work from 20-50 ohm). Modern
    Coles lists 300 ohm: the 1961 unit is the one modelled;
  - Fig. 1 free-field response (open circuit, 0 dB = 1 V per dyne/cm^2): within about
    +-1 dB from 40 Hz to 14 kHz (-85 dB mean), -2.5 dB at 30 Hz, a dip near 1.5 kHz and
    9 kHz, a rise at 11 kHz, falling to -87 dB at 15 kHz (read by eye from the page);
  - hum pick-up < +5 dB re 0.0002 dyne/cm^2 for 1 mG at 50 Hz;
  - distortion < 1 % at 125 dB above 0.0002 dyne/cm^2 at 110 c/s, < 0.1 % at 250 c/s;
  - 197 x 83 x 61 mm, 1.08 kg.
  Page 2 (description): a toroidal "ribbon-to-line" transformer in the base, hum-neutralising
  wiring; heavy-gauge perforated brass case lined with monel mesh; the figure of eight
  "substantially constant" in horizontal and vertical planes. Page 4 Figs. 2-3: the
  horizontal and vertical polar diagrams (6 dB rings, curves at several frequencies, not
  labelled legibly at this scan).
- Page images were read in the session; render with pymupdf for the polars.

## bbc: BBC Engineering Monograph No. 4 (Shorter & Harwood, December 1955)

*The Design of a Ribbon Type Pressure-gradient Microphone for Broadcast Transmission*, 24
pages, a scan without a text layer.

- web: http://downloads.bbc.co.uk/rd/pubs/archive/pdffiles/monographs/bbc_monograph_04.pdf
  (4,352,273 bytes, sha256
  `277ac6c4f130011e7b19a2687a5932fba7daa57d0f4637628cf6022ec7421c83`); mirror
  https://www.coutant.org/bbc-pgs/bbc_monograph_04.pdf. **Not yet read** (WP8's step 1):
  it should give the ribbon's dimensions, the gap, the perforated fibre plates, the
  transformer, the damping and the polar / response curves.
- The page that quotes it: https://coutant.org/bbc-pgs/index.html (ribbon about 1 in long
  against the AXBT's 2.5 in, output 4 dB below the AXBT's, response held to ~18 kHz by the
  perforated fibre plates on each side of the ribbon, introduced 1953).

## Other (not fetched: 429 from the Wayback Machine for scripts)

- Coles' data sheet and the user's guide (Wes Dooley, 1997-2006), via
  https://web.archive.org/web/20110928190552/http://www.wesdooley.com/pdf/Coles_4038_Data_Sheet_web.pdf
  and https://web.archive.org/web/20110928190541/http://www.wesdooley.com/pdf/4038C.pdf.
  The user can fetch them if the monograph lacks a figure (each URL alone in a code block).
- web: https://en.wikipedia.org/wiki/Coles_4038 (modern figures: -65 dB re 1 V/Pa, 300 ohm).
