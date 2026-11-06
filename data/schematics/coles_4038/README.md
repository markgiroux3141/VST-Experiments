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
  https://www.coutant.org/bbc-pgs/bbc_monograph_04.pdf. Read 2026-11-06 (pdf page = printed
  page + 2). The **PGS** is the microphone STC made as the 4038 (single-ended magnet;
  the PGD double-ended and the AXBT are compared). Values, by printed page:
  - p5: PGS 2-6 lb, 3 3/8 in wide x 1 3/8 deep x 8 3/8 in tall (Fig. 1: 3 1/8 x ... read
    roughly); the brief: -71 dB PGD, **-75 dB PGS** re 1 V/dyne/cm^2 open circuit, **300 ohm**
    (the AXB / AXBT -77 / -71 dB, 300 ohm).
  - p6-8 (2.2): magnet Ticonal 'G', mild-steel pole pieces cemented with Araldite baked at
    200 C; leakage: 2-10 % of the magnet's flux reaches the pole tips; best pole shape the
    straight 60 deg chamfer on flat tips, **gap 0.25 in** (Fig. 6: useful-flux fraction
    against gap, ~5 % at 0.25 in); flux density 6500 G at the pole tips to 4500 G at the
    centre (fairly constant along the length).
  - p8-10 (2.3): **ribbon length 1 in** (PGD 1.125), **width 0.23 in** in the 0.25 in gap;
    aluminium leaf 2.5 x 10^-5 in (0.6 um) thick, 0.2 mg/cm^2; **d.c. resistance 0.22 ohm**;
    20 corrugations per inch, < 0.002 in deep, pulled nearly flat on fitting; fundamental
    resonance of the unloaded ribbon between 25 and 45 c/s ("over 40 c/s" in 3.2: the
    PGS is tensioned high; the response within +-0.75 dB, transient aperiodic); transverse
    modes at about 10 and 11 kc/s (the ribbon's field is ~30 % weaker at the centre).
  - p10-12 (2.3.4, 2.4): Monel wire-gauze **damping screens** each side of the ribbon,
    **spacing 0.03 in**, held by the magnet (Fig. 7 shows the response with and without
    them: the bass loss they cost, and the longitudinal modes below 1 kc/s they damp);
    a **low-frequency baffle** of bolting cloth on a coarse wire mesh each side, in the
    hollow of the magnet, fitting the poles within **0.06 in** (Fig. 11: raises the bass
    by up to ~1.5 dB at 30 Hz); lost bass is compensated that way.
  - p12-14 (2.5): the upper case is perforated brass under two layers of wire gauze,
    D-shaped windows cut in front and behind the ribbon; **parallel reflectors** of
    perforated plastic in front of and behind the ribbon (Figs. 3-4, 13: -0.7 dB mid-band
    and a rise of a few dB toward ~13 kc/s that offsets the natural fall; the first maximum
    varies as the cube of their spacing).
  - p14-15: hum-neutralized wiring (reduction >30 dB), the ribbon-to-line transformer in the
    stirrup's base with a Mumetal screen, secondary through 0.25 in twin screened cable.
  - p15-18 (3.2, Figs. 16-19): open-circuit response, horizontal and vertical planes,
    at 0, 30, 45, 60 deg (the 60 deg curves raised 6 dB to compare), a crevasse in the +60
    vertical curve at 10 kc/s; the response with a 300 ohm load; Fig. 19(b): impedance
    modulus about 270 ohm at 1 kc/s (mean of the first 50: 230-320 ohm), a bump to ~400
    ohm near 60 Hz and a rise to ~300 at 20 kc/s; mean sensitivity of the first 50: -75 dB
    (three-quarters within +-0.5 dB). Fig. 22: the production spread.
  - p19-21: self noise weighted +22 dB re 0.0002 dyne/cm^2 (PGS), hum pick-up at 1 mG: +4 dB
    (50 c/s), +27 (1000), +42 (10 kc/s) re 0.0002 dyne/cm^2; Fig. 23 wind noise.
  The 4038 is the PGS with a transformer for 30 ohm and -85 dB (the brochure): 10 dB less
  output, the impedance a tenth, i.e. the PGS' ratio over sqrt(10).
- The page that quotes it: https://coutant.org/bbc-pgs/index.html (ribbon about 1 in long
  against the AXBT's 2.5 in, output 4 dB below the AXBT's, response held to ~18 kHz by the
  perforated fibre plates on each side of the ribbon, introduced 1953).

## Other (not fetched: 429 from the Wayback Machine for scripts)

- Coles' data sheet and the user's guide (Wes Dooley, 1997-2006), via
  https://web.archive.org/web/20110928190552/http://www.wesdooley.com/pdf/Coles_4038_Data_Sheet_web.pdf
  and https://web.archive.org/web/20110928190541/http://www.wesdooley.com/pdf/4038C.pdf.
  The user can fetch them if the monograph lacks a figure (each URL alone in a code block).
- web: https://en.wikipedia.org/wiki/Coles_4038 (modern figures: -65 dB re 1 V/Pa, 300 ohm).
