# Magnetic tape datasheets

Source documents for the tape model (particulate coating, AC-bias recording, reciprocity playback).
Every file was downloaded with curl on **2026-10-31**. Page numbers are PDF pages, read with the
Read tool. Nothing here is digitized yet: a curve used for fitting needs a CSV plus a provenance
sidecar, as `../README.md` describes.

Units: 1 Oe = 79.58 A/m; 1 G = 0.1 mT. Remanent flux per width = Br x coating thickness
(e.g. 150 mT x 12.7 um = 1905 nWb/m). 1 flux line (maxwell) per 1/4" = 1.575 uWb/m.
"Sensitivity" and "MOL" in dB are relative to each maker's own reference tape or level, so they
can't be compared across makers.

**Copyright note:** `aes_3m_audio_open_reel_products.pdf` says "Reproduction in any form prohibited
without the written permission of Delos A. Eilers". It is kept for private reference. Don't
redistribute it, and decide before committing it.

## Files

| File | What it is | Source URL |
|---|---|---|
| `quantegy_456.pdf` | Quantegy 456 Grand Master data sheet, rev. 03/03-T32-456, 2 pp. | https://web.archive.org/web/20180413024957id_/http://www.technicalaudio.com:80/pdf/Quantegy_tape/Quantegy_456.pdf |
| `quantegy_406_407.pdf` | Quantegy 406/407 data sheet, 03/03-T32-406/407, 2 pp. | https://web.archive.org/web/20191021021509id_/http://www.technicalaudio.com:80/pdf/Quantegy_tape/Quantegy_406_407.pdf |
| `quantegy_GP9.pdf` | Quantegy GP9 data sheet, 03/03-T32-GP9, 2 pp. | https://web.archive.org/web/20170918094715id_/http://www.technicalaudio.com:80/pdf/Quantegy_tape/Quantegy_GP9.pdf |
| `aes_3m_audio_open_reel_products.pdf` | D. A. Eilers (ex-3M), "3M Audio Open Reel Tapes, in Customary Units", rev.2-cust 2011-07-24, AES Historical Committee, 2 pp. | https://aes2.org/wp-content/uploads/2025/01/aorprod-cust.pdf |
| `rep_1974-12_p19_scotch250.pdf` | "3M's Scotch 250 High Energy Mastering Tape", R-e/p (Recording Engineer/Producer) Dec. 1974, magazine p. 21, 1 p. | https://www.worldradiohistory.com/hd2/IDX-Audio/Archive-REP-IDX/IDX/70s/Recording-1974-12-OCR-Page-0019.pdf |
| `3m_Sound_Talk_01_19481007.pdf` | 3M Sound Talk Bulletin 1 (1948): curves for #111 | http://bitsavers.org/pdf/3M/bulletins/sound_talk/Sound_Talk_01_19481007.pdf |
| `3m_Sound_Talk_04.pdf` | Bulletin 4: setting AC bias for #101 / #111 | http://bitsavers.org/pdf/3M/bulletins/sound_talk/Sound_Talk_04.pdf |
| `3m_Sound_Talk_10.pdf` | Bulletin 10: layer-to-layer transfer (print-through) | http://bitsavers.org/pdf/3M/bulletins/sound_talk/Sound_Talk_10.pdf |
| `3m_Sound_Talk_14_19500609.pdf` | Bulletin 14 (1950): permissible record current vs frequency, #111 | http://bitsavers.org/pdf/3M/bulletins/sound_talk/Sound_Talk_14_19500609.pdf |
| `3m_Sound_Talk_20.pdf` | Bulletin 20: remanent flux vs peak field, #111 types | http://bitsavers.org/pdf/3M/bulletins/sound_talk/Sound_Talk_20.pdf |
| `3m_Sound_Talk_21_195302.pdf` | Bulletin 21 (Feb. 1953): output vs bias current, #111 types, Ampex 300 | http://bitsavers.org/pdf/3M/bulletins/sound_talk/Sound_Talk_21_195302.pdf |
| `3m_Sound_Talk_22_195303.pdf` | Bulletin 22 (Mar. 1953): B-H loops and magnetization curves of the coatings | http://bitsavers.org/pdf/3M/bulletins/sound_talk/Sound_Talk_22_195303.pdf |
| `3m_Sound_Talk_31.pdf` | Bulletin 31 (R. A. Von Behren): coating thickness vs frequency response | http://bitsavers.org/pdf/3M/bulletins/sound_talk/Sound_Talk_31.pdf |
| `3m_Sound_Talk_34.pdf` | Bulletin 34 (Von Behren): tape noise, DC noise spectra incl. #111 | http://bitsavers.org/pdf/3M/bulletins/sound_talk/Sound_Talk_34.pdf |
| `3m_Sound_Talk_38_19600815.pdf` | Bulletin 38 (1960): storing masters to minimize print | http://bitsavers.org/pdf/3M/bulletins/sound_talk/Sound_Talk_38_19600815.pdf |
| `emtec_basf_sm911.pdf` | EMTEC (BASF) Studio Master 911 technical data, 05/99, 6 pp. Not on the requested list: a 456-class tape (320 Oe / 1450 G) with full curves | https://web.archive.org/web/20161020023727id_/http://www.technicalaudio.com:80/pdf/EMTEC_BASF_tape/EMTEC_BASF_Studio_Master_911.pdf |
| `atr_master_tape.pdf` | ATR Magnetics Master Tape technical data, 3 pp. Not on the requested list: a current 456-class tape (330 Oe / 1400 G) with curves and an overbias table | https://www.duplication.com/atr_magnetics/ATR-Master-Tape-Technical-Data-Sheet-Standard.pdf |

The direct technicalaudio.com URLs (`https://www.technicalaudio.com/pdf/Quantegy_tape/...`) have an
expired TLS certificate, so the Wayback Machine copies were used. zZounds' copy of the 456 sheet
sits behind a Cloudflare check.

## Extracted numbers

### Ampex / Quantegy 456 Grand Master (`quantegy_456.pdf`, p. 2)
- Hc **320 Oe (25.5 kA/m)**; retentivity **1500 G (150 mT)** -> ~1905 nWb/m at 12.7 um
- Base 1400 uin (35.4 um), oxide **500 uin (12.7 um)**, backcoat 30 uin (0.8 um), total 1930 uin (48.9 um)
- Sensitivity +2.0 dB at 1 kHz, +4.0 dB at 10 kHz (re the maker's reference tape)
- THD3 at reference level (1 kHz) 0.1 %; output at 3 % THD3 (1 kHz) **+12.3 dB**; modulation noise -76.0 dB; print-through **-55.0 dB**
- The reference level and the bias procedure aren't printed on this revision. No curves.
- Not given: Ms, squareness, SFD, particle data.

### Ampex / Quantegy 406/407 (`quantegy_406_407.pdf`, p. 2)
- Hc **330 Oe (26.3 kA/m)**; retentivity **1300 G (130 mT)** -> ~1313 nWb/m at 10.1 um
- Base 1400 uin (35.4 um, 406) / 850 uin (21.5 um, 407); oxide **400 uin (10.1 um)**; backcoat 30 uin; total 1830 / 1280 uin (the second "Total" is misprinted "for 406")
- Sensitivity +0.8 dB at 1 kHz, +1.5 dB at 10 kHz. The THD line is cut off (no value printed). "Bias compatible with 456" (p. 1). No curves.

### Quantegy GP9 (`quantegy_GP9.pdf`, p. 2)
- Hc **370 Oe (29.5 kA/m)**; retentivity **1600 G (160 mT)** -> ~2832 nWb/m at 17.7 um
- Base 1400 uin (35.4 um), oxide **700 uin (17.7 um)**, backcoat 30 uin, total 2130 uin (53.9 um)
- Sensitivity 0.8 dB at 1 kHz, 1.1 dB at 10 kHz; THD3 at reference 0.06 %; output at 3 % THD3 **+17.5 dB**; modulation noise -73.0 dB; print-through **-58.0 dB**. No curves.

### Scotch 111, 206, 250 (Eilers table, `aes_3m_audio_open_reel_products.pdf`, p. 1)
| Product | Year | Base | Base / oxide / total [mil] | Remanence [lines/(1/4")] | Rel. re 111 [dB] | Hc [Oe] | Retentivity [G] |
|---|---|---|---|---|---|---|---|
| 111 (111A) | 1948 | acetate | 1.42 / **0.5** / 1.92 | 0.64 (~1.0 uWb/m) | 0 | **270** | **900** |
| 102 (111AM) | 1953 | polyester | 1.45 / 0.5 / 1.95 | 0.64 | 0 | 270 | 900 |
| 206 | 1969 | polyester, back treated | 1.42 / **0.56** / 2.08 | 0.93 (~1.46 uWb/m) | +3.2 | **320** | **1050** |
| 250 | 1974 | polyester, back treated | 1.3 / **0.68** / 2.06 | 1.3 (~2.05 uWb/m) | +6.2 | **380** | **1200** |
| 112 | 1948 | acetate | 1.42 / 0.7 / 2.12 | 0.45 | -3.1 | 170 | 450 ("tape for Ampex 200A") |

(0.5 mil = 12.7 um, 0.56 mil = 14.2 um, 0.68 mil = 17.3 um.) The AES intro page notes that test
conditions changed over the decades, so these aren't strictly comparable across eras.

### Scotch 206 vs 250 (`rep_1974-12_p19_scotch250.pdf`, p. 1)
- Dynamic range: #111 66 dB, #202 71 dB, #206 74 dB, **#250 78 dB**; 250's NAB-weighted noise -72 dB; 206's 3 % THD3 output +3 dB over 202's; 250's another +3 dB over 206's
- 250's bias is **2 dB (20 %) higher** than 206's; equalization unchanged
- 250: "particles more uniform in size and needle shape", higher packing density
- **Curves (digitizable):** output at 3 % THD3 vs bias, 1 kHz at 15 ips (206 and 250); short-wavelength saturation output vs bias (206 and 250), on normalized bias scales.

### Scotch 111, 1948-1960 (3M Sound Talk bulletins)
- **Bulletin 21 (p. 1):** output vs bias current at **1 kHz and 15 kHz**, for tape types B (#111A 4RBA), BQ (#111A 5RBA, #111AP), BP and RR (#112). Measured on an **Ampex Model 300 at 15 ips, 70 kHz bias, record gap 0.002" (51 um)**, NARTB equalization. Audio was held ~20 dB below the 1 % distortion level. Type B peaks near 5 mA (1 kHz) and 4.5 mA (15 kHz), read by eye. **Digitizable.**
- **Bulletin 20 (p. 1):** remanent flux per 1/4" tape vs peak magnetizing field (60 Hz B-H meter, symmetric loops), Type B saturating at ~0.63 lines (~0.99 uWb/m) and BQ at ~0.58, with the steep rise between ~200 and 400 Oe; +-10 % sample tolerance. This is a remanence curve, i.e. the integral of the switching-field distribution. **Digitizable: a direct Preisach anchor.**
- **Bulletin 22 (pp. 1-2):** major loops (1000 Oe peak, 60 Hz) and normal magnetization curves for coating types A, B, BQ, RR. The scan has four unlabeled panels. They are presumably in the text's order (A, B, BQ, RR): the 4th panel's low Hc fits RR (#112, 170 Oe). Visual reads give Br ~500-600 G and Hc ~190-230 Oe for the middle panels. That is lower than Eilers' 900 G / 270 Oe for #111: an era or measurement difference to resolve when digitizing. **Digitizable.**
- **Bulletin 1 (p. 2):** #111 at 7.5 ips with 40 kHz bias: frequency response at three bias / audio settings (2.4, 3.2 and 8.0 ampere-turns); frequency response at 3.75, 7.5 and 18 ips; THD3 vs output at 400 Hz for four bias values. Bias "not particularly critical" for 101 / 111: similar results at +-50 % (p. 1). **Digitizable.**
- **Bulletin 4 (p. 1):** bias for 101 / 111: professional machines about **2x the bias for maximum 1 kHz output** (a compromise); home machines at maximum output, or 1.5x with DC erase.
- **Bulletin 14 (p. 1-2):** #111 at 7.5 ips: the permissible record current (equal 3rd-order distortion, two-tone method) is flat to ~1200 Hz and **+4 dB at 7 kHz**; #112 is -2 dB at 7 kHz. It is a wavelength effect, and the HF lost to extra bias can't be recovered by pre-emphasis without more distortion.
- **Bulletin 10 (pp. 1-2):** print-through is like unbiased recording: **~2 dB of transfer per 1 dB of level**; it grows with storage time (days to months) and **~1 dB per 10 F**. Stray fields of a few Oe raise it by up to 30-40 dB. It peaks at mid frequencies (long wavelengths have weak fields, short ones are attenuated by the base).
- **Bulletin 38 (pp. 1-2):** the outer layer prints more (separated by the base only); a printed signal drops **>=6 dB within minutes** after unwinding.
- **Bulletin 31 (pp. 1-3):** coatings of 0.25 / 0.5 / 1.0 mil at low, optimum and high bias: long-wavelength output scales with thickness at high bias, and short-wavelength output converges (only a surface layer records). **Digitizable** (Figs. 2-4).
- **Bulletin 34:** DC-noise octave spectra for oriented vs unoriented #111 (Fig. 2).
- Particle type for #111: acicular gamma-Fe2O3 (web: https://ibm-1401.info/MagTapeMedia.html , a secondary history: Type 101 of 1948 was the first acicular gamma-Fe2O3 tape at 250-275 Oe, and Type 111 used the same particles on acetate. Not stated in the files here.)

### EMTEC Studio Master 911 (`emtec_basf_sm911.pdf`): the best curve set
- p. 3: Hc **25.5 kA/m (320 Oe)**, Brs **145 mT (1450 G)**, Phi_rs/w **2320 nWb/m**; base 30 um, coating **16 um**, total 50 um
- Conditions (p. 3): IEC reference heads, **record gap 7.0 um, playback gap 3.0 um**, track 6.3 / 2.575 mm; reference level 320 nWb/m
- p. 3, at 15 ips: MOL1/3 (1 kHz, 3 %) **+12.5 dB**, MOL1/1 +9.0, **SOL10 +10.5**, SOL16 +7.5, MTL10 +6.0, MTL16 +3.0, S1 +1.5, S10 +2.5, S16 +3.0, THD at 320 nWb/m 0.10 %, at 514 nWb/m 0.25 %, DC noise -56, bias noise IEC -60.5 / CCIR -47.5, MOL/BN 73.0 / 60.0, print-through 56 dB. **Recommended bias = 10 kHz peak + 3.0 dB overbias at 15 ips** (1.5 dB at 30 ips, 6.0 dB at 7.5 ips). The 30 and 7.5 ips columns are also given.
- **Curves:** p. 2: S1, S10, S16, MOL, SOL, MTL, THD, DCN and bias noise **vs bias**, at 30, 15 and 7.5 ips. p. 4: THD3 vs output at 1 kHz; input vs output at 1 / 10 / 16 kHz (saturation). p. 6: test-method notes (IEC 94-5).

### ATR Master Tape (`atr_master_tape.pdf`)
- p. 1: Hc 330 Oe, Brs 1400 G; base 1420 uin, oxide **500 uin (12.7 um)**, total 1950 uin; S1 +1.2, S10 +1.0 dB; THD 0.10 %; output at 3 % THD **+12 dB re 320 nWb/m**; modulation noise -68 dB; print-through **-56 dB**. Conditions: 15 ips, IEC 35 us, **record gap 0.5 mil (12.7 um), repro gap 0.12 mil (3 um)**.
- p. 2: **overbias (dB past the 10 kHz peak) vs record-gap length and speed**: 15 ips: 3.0 / 2.5 / 2.0 / 1.0 dB at 0.25 / 0.3 / 0.5 / 1.0 mil; 30 ips 1.5 / 1.2 / 1.0 / 0.5; 7.5 ips 5.0 / 4.5 / 4.0 / 2.0. **Curves:** S1, S10, THD3 and bias noise vs bias; THD vs output at 7.5 / 15 / 30 ips.
- p. 3: definitions (print-through: 1 kHz at reference level, 24 h at 21 C).

## Validation anchors (curves worth digitizing)
1. **SM911 p. 2 and p. 4**: the complete IEC bias-curve family plus saturation and THD curves, with the head gaps stated. A 456-class tape.
2. **Sound Talk 20 / 21 / 22 / 1**: #111's remanence curve, B-H loops, bias curves at 1 and 15 kHz on an **Ampex 300 at 15 ips** (gap and bias frequency stated), and THD vs level. The 1950s anchor.
3. **R-e/p 1974**: 206 vs 250 MOL and SOL vs bias.
4. **ATR p. 2**: bias curves, THD vs output, and the overbias-vs-gap table (checks the model's gap dependence).

No curves: the Quantegy 456, 406/407 and GP9 sheets (numbers only). No original data sheets were found for
Scotch 206 / 250 / 111 or for a 1970s-80s Ampex 456 (the old Ampex sheets with curves are attached to a
tapeheads.net thread behind a browser check).
