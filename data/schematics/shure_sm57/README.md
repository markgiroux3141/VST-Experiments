# Shure SM57 / SM58 sources

docs/SM57_PLAN.md's SM1, found 2026-11-05 (three research passes: Shure's documents, patents
and theory, teardowns and measurements). The mic modelled is the **old era** (the plan's
Decisions 2): the Unidyne III cartridge with the dual-impedance output transformer (the
30-50 / 150-250 ohm taps, later rated 38 / 150 ohm), as built until the change to one
150 ohm (310 ohm actual) winding between the 1986 and 1988 catalogs. Values in
`config/components/sm57*/` and `config/circuits/shure_sm57.yaml` cite these as:

- `s65:` / `s68:` Shure data sheet 27A308 "Model SM57" (6-65) / (2-68); `s70:` SM58 sheet
  27A378 (1-70);
- `c74:`, `c77:`, `c81:`, `c86:`, `c88:`, `c93:` Shure's catalogs of those years;
- `g02:`, `g06:`, `g25:` / `g24:` the SM57 / SM58 user guides of those years;
- `seeler61:` E. Seeler, "A Small Unidirectional Dynamic Probe Microphone", J. Audio Eng.
  Soc. 9(4), 276-277 and 308, Oct. 1961 (presented 12 Oct 1960);
- `pat883:` US 3,240,883 (Seeler, Shure, "Microphone", filed 1961-05-25, issued
  1966-03-15: the Unidyne III); `pat713:` US 3,132,713 (Seeler, the diaphragm); `pat905:`
  US 3,989,905 (Anderson, Rusch, Seeler: the shock path); `pat596:` US 2,305,596 (Bauer:
  Uniphase theory and the Unidyne I's numbers);
- `born12:` John Born (Shure product specialist) interviewed by RecordingHacks, 2012
  (secondhand from Shure, on the record); `cj06:` CJ's bench measurements on GroupDIY,
  2006; `tab07:` TAB-Funkenwerk's bench sheet of a stock SM58 transformer, 2007;
  forum figures are marked as such and are provisional at best;
- `wt31:` Wente & Thuras, "Moving-Coil Telephone Receivers and Microphones", Bell Syst.
  Tech. J. 10(4), 565-576 (1931) (the slit formulas).

The PDFs are not committed (as the U47's). URLs, sha256 and sizes are below. The PNGs here
were rendered from them with PyMuPDF and reduced to 16 gray levels.

## Documents

### Shure

| Id | Document | URL | sha256, bytes |
|---|---|---|---|
| s65 | 1965 Professional Products catalog; the SM57 sheet 27A308 (6-65) is PDF pp. 11-12 (scans, no text layer) | web: https://content-files.shure.com/KnowledgeBaseFiles/vintage-catalogs/1965-pro-products.pdf | `8c7de4f7e57d811767f6d8cfe162f12236fa49db86da855146134597d892d1d3`, 6249913 |
| s68, s70 | "Shure 1964-1971 Catalog Sheets" (World Radio History's compendium of Shure prints): SM57 27A308 (2-68) PDF pp. 29-30, SM58 27A378 (1-70) pp. 31-32 | web: https://www.worldradiohistory.com/Archive-Catalogs/Miscellaneous-Manufacturers/Shure-1964-1971-Catalog-Sheets.pdf | `5839e761efb1ae1aa58ff944e5817ce5a5b8bf2936e94c034acc509f66d77ccc`, 12622118 |
| c74 | 1974 catalog, PDF p. 8 | web: https://content-files.shure.com/KnowledgeBaseFiles/vintage-catalogs/1974.pdf | `fea2583b1901f4713817721de850f2a2e43c7f79cc2423a9f8c347b913443fab`, 4447119 |
| c77 | 1977 catalog, p. 8 | web: .../vintage-catalogs/1977.pdf | `0c59bd4f523d4a0ec476b3e028417e877bc8fb528e6e13185ffe0dc60d29667a`, 14255764 |
| c81 | 1981 "Microphone and Circuitry Products", PDF pp. 12-13 (printed 10-11) | web: .../vintage-catalogs/1981_Microphone_and_Circuitry_Products.pdf | `610866043de2989d8b6b14b0e5c81678bdec7acd21510764bf940d1bebf97bd2`, 35608192 |
| c86 | 1986 Professional Products, pp. 5-6 | web: .../vintage-catalogs/1986-professional-products.pdf | `b24b0b189a7f2c444a8e204c318e3fc8f3989b2edb0761d2c647c88d1f6ab444`, 8902613 |
| c88 | 1988 "Microphone and Circuitry Products", p. 24 | web: .../vintage-catalogs/1988-microphone-and-circuitry-products.pdf | `34604e59f41199b9e6032721f1a0f2e974acfc25e1fc101729e8e409a3180076`, 17881257 |
| c93 | 1993 tech specs | web: .../vintage-catalogs/1993_tech_specs.pdf | `7f5abb2ccd43061ff50617bb5f067aa1cc4c5f340588a80b88e981b7b536d325`, 3167092 |
| g02 | SM57 user guide 27B2903 (a vendor mirror; dated by the PDF's creation, 2002) | web: https://cf3.zzounds.com/media/sm57-de1d2289c80392c39abc987484bf36b7.pdf | `8a5f1e220949d6818ac4403a24bba0d4a9b27fd33d16d9ee5db5fd294107d62f`, 259927 |
| g06 | SM57 user guide 27C2903 Rev. 5, printed "(c)2006" (mirrors) | web: https://coutant.org/sm57/sm57.pdf | `14a9ef6e3dbed4bfb9ff46d5a606ac0360213874acf29cab391058d74f1a2775`, 298153 |
| g25 | SM57 user guide, Version 3.6 (2025-A) | web: https://pubs.shure.com/view/guide/SM57/en-US.pdf | `af4873b2e14e4c1541e077d3269dd4d46f3df074d261222f1f58dda306c36733`, 541685 |
| g24 | SM58 user guide, Version 6.4 (2024-F) | web: https://pubs.shure.com/view/guide/SM58/en-US.pdf | `5932523424328412b0b7c0adb28e9cc25d73b9d15c1a3d5db1e59e6a94360344`, 485578 |
| g18 | 545SD user guide (PDF created 2018-03-29) | web: https://pubs.shure.com/view/guide/545SD/en-US.pdf | `4a3b3830818029e3104e2998035519676c75b5b4e71204fe782b63023e1382c3`, 91775 |
| sp10 | SM57 spec sheet (vendor mirror, PDF created 2010-06-14) | web: https://media.sweetwater.com/store/media/us_pro_sm57_specsheet.pdf | `cc9949a04c52a0b5d43e985b8976931f4621cd257828d3703317475e79caf0bf`, 270798 |

PNGs: `sm57_27A308_1968_p1.png`, `sm57_27A308_1968_p2.png` (s68), `sm58_27A378_1970_p1.png`,
`sm58_27A378_1970_p2.png` (s70); the digitized figures' crops `sm57_{1965,1968,1981,2025}_
response.png`, `sm57_{1968,1981,2025}_polar.png`, `sm58_{1970,1981,2024}_{response,polar}.png`
(their digitization: `data/datasheets/shure_sm57.provenance.yaml`, `shure_sm58.provenance.yaml`;
the curves in `shure_sm5{7,8}_{response,polar}.csv`). Notes from the digitizing: s65's Figure B
is s68's artwork (0.05 dB rms); the SM58 sheet's figures are on PDF p. 31; the 1968 / 1970
polar rings are +5 / 0 / -5 / -10 / -15 dB; the vintage SM58 polars are the SM57's drawing
(s70 = s68 scaled, c81's SM58 = c81's SM57), the responses each mic's own; the 2025 SM57
drawing rolls off far more below 150 Hz than 1965-81 (-4.7 against ~-1.2 dB at 100 Hz).

### Patents and papers

| Id | Document | URL | sha256, bytes |
|---|---|---|---|
| seeler61 | Seeler, JAES 9(4) 1961 (Shure's copy; pp. 276-277 here, p. 308 is not in it) | web: https://content-files.shure.com/KnowledgeBaseFiles/Seeler_Unidyne_III_AES_Paper_1960.pdf | `931862854772a3c1142f4c4bd5c7e30baeb60cc256cee5d9dba60611598dde5a`, 3739657 |
| pat883 | US 3,240,883 | web: https://patents.google.com/patent/US3240883A/en | `71b6c9f9a145626e6a492f966184928ff7382c79632094708931ca30b8d002ae`, 684792 |
| pat713 | US 3,132,713 | web: https://patents.google.com/patent/US3132713A/en | `fe3691b3058552236b88618e9444d382c91e74c574d0dfc173ef80f3ccb00da5`, 522689 |
| pat905 | US 3,989,905 | web: https://patents.google.com/patent/US3989905A/en | `9a9aa902239cf4e07e1cc2e2860451e11269a37c5a6be113686d6083686894ed` |
| pat596 | US 2,305,596 (Bauer) | web: https://patents.google.com/patent/US2305596A/en | `5b3466c4a02c3535ced1e82781d40ef337f59fe55a43414af7ae1556e22509a6` |
| pat036 | US 5,259,036 (Seeler 1993, a laminated diaphragm; which product used it isn't stated) | web: https://patents.google.com/patent/US5259036A/en | `2baac2b8278413af1bd901c2b273ac2179175aa4c6b7713512ed58067bec29ed` |
| wt31 | Wente & Thuras, BSTJ 10(4) 1931 | web: archive.org (Bell System Technical Journal) | `9b81329fd27fd61bfcc7bc2f41e6168a6e0cf516e9a977a3b4494cae052483ab` |
| olson47 | Olson, "Elements of Acoustical Engineering", 2nd ed., Van Nostrand 1947, sec. 8.4B3 "Uniphase Dynamic Microphone" pp. 266-267, Fig. 8.38 | web: archive.org (Digital Library of India scan) | `f42e57e328610745898dc04998f8f15a4ee265170d8febbb53390c47f540a8da` |

PNGs: `seeler_1961_jaes_p1.png` .. `p3.png`, `us3240883_seeler_figs.png` (the patent's
sheet 1: Figs. 1-4), `us3132713_diaphragm_figs.png`.

Bauer, "Uniphase Unidirectional Microphones", J. Acoust. Soc. Am. 13(1), 41-45 (1941),
doi:10.1121/1.1916145 (confirmed by Crossref; paywalled, not read). Peng & Huang,
"Electroacoustic analysis of a directional moving-coil microphone using combined
lumped-parameter models and BEM", Sens. Actuators A 332, 112914 (2021) is the closest
published method (a hypercardioid handheld; paywalled, not read).

### Teardowns and measurements (secondhand)

| Id | What | URL |
|---|---|---|
| born12 | John Born (Shure), RecordingHacks interview, parts I-III, Oct-Nov 2012 (read via the Wayback Machine; the live site returns 500) | web: http://recordinghacks.com/2012/10/31/how-a-dynamic-microphone-works/ ; .../2012/11/01/engineering-secrets-sm57/ ; .../2012/11/02/shure-invisible-shockmount/ |
| born20 | "johnborn3" (apparently John Born) on Gearspace, 24 Jun 2020 | web: https://gearspace.com/board/low-end-theory/728752-sm57-transformerless-impedance.html |
| cj06 | CJ, GroupDIY "Modify the Shure SM57", posts 87-90, 28 Mar 2006, a 1990 SM57's transformer | web: https://groupdiy.com/threads/modify-the-shure-sm57-microphone.14541/page-3 |
| tab07 | Stephen Haselton for AMI / TAB-Funkenwerk, 9 Apr 2007: a stock SM58 transformer on the bench, 10 ohm source | web: http://web.archive.org/web/20090419073931/http://www.tab-funkenwerk.com:80/sitebuildercontent/sitebuilderfiles/t58specs.pdf (sha256 `1c607a25b3a1235416e26ec27d886fe6c6d65fc2f73a42ef1523a57bdd2204a5`, 129965 bytes) |
| psw17 | ProSoundWeb thread 165653 (Dec 2017): DCRs of several units incl. an old dual-impedance SM58 | web: https://forums.prosoundweb.com/index.php?topic=165653.0 |
| hr23 | "rob aylestone", homerecording.com, Jul 2023: a capsule cut open | web: https://homerecording.com/bbs/threads/sm57-thin-sound-fixed-very-unusual-fault-but-pictures-xplain-it-all.422373/ |
| vear95 | Tim Vear (Shure) quoted on music-electronics-forum, 1995: the production changes | web: https://music-electronics-forum.com/forum/music-electronics/11911-info-on-extra-tap-extra-orange-wire-from-internal-transformer-in-old-sm57-sm58s |
| hau | Andreas Hau, Sound & Recording, "SM57 / SM58 schoener toenen" (archived): loading; an independent on-axis curve (Rossi's, GroupDIY 2011, 33 cm, method undisclosed) | web: https://www.soundandrecording.de/tutorials/sm57-sm58-schoener-toenen/ ; https://groupdiy.com/threads/my-new-diy-article-sm57-58-filter-for-flat-response.45454/ |
| ee18 | euroelectron blog, 2018: impedances at 1.28 kHz (Escort ELC-120) | web: https://euroelectron.blogspot.com/2018/10/mic-output-impedances.html |

## Published figures

### The SM57, old era (s65 / s68; transcribed 2026-11-05 from the scans)

- "Type: Dynamic". "Frequency Response: 50 to 15,000 cps" (s65), "40 to 15,000 Hz" (s68,
  with a redrawn curve, Figure B). "Polar Pattern: Cardioid ... rotationally symmetrical
  about microphone axis, uniform with frequency (See Figure D)".
- "Impedance: Dual. 30-50 ohms and 150-250 ohms. (Connected for 150-250 ohms when
  shipped)."
- Output level, 1,000 Hz: "30-50 ohms 'L' position: Open circuit voltage -83.5 db* (.067 mv);
  Power level -56.0 db**; EIA ... Gm -149.0 db***"; "150-250 ohms 'H' position: Open circuit
  voltage -76.5 db* (.149 mv); Power level -56.0 db**; Gm -148.0 db***". "* 0 db = 1 volt per
  microbar; ** 0 db = 1 milliwatt with 10 microbars; *** EIA Standard SE-105, August 1949."
  In SI (my arithmetic): H 1.49 mV/Pa = -56.5 dBV/Pa, L 0.67 mV/Pa = -63.5 dBV/Pa; the
  ratio of the two, 2.22 (6.9 dB), is the tap's voltage ratio.
- Architect's specification (s68): "The cancellation at the sides shall be approximately
  6 db, and the cancellation at the rear shall be 15 to 20 db"; "Gm (sensitivity) at 1,000
  Hz shall be within +-3 db"; "6-17/64 (159.1 mm) in length and 1-1/4 (31.75 mm) in
  diameter". "Net Weight less cable: 10 ounces (284 grams)". Case "Die-cast and
  'Armo-Dur'". Patents printed: D-190,864; 3,312,713 [sic; the SM58 sheet prints 3,132,713]
  and 3,240,883.
- Figure A, internal connections: the voice coil's GREEN ("coded terminal") and YELLOW to
  the transformer's primary, BLACK to the cartridge ground; the secondary BLUE to pin 2,
  RED (the whole winding, 150-250 ohm) or ORANGE (the tap, 30-50 ohm) to pin 3; "positive
  pressure produces positive voltage at pin 2 with respect to pin 3". The procedure:
  "Disconnect RED lead from pin number 3. Solder the ORANGE lead to pin number 3."
- Figure B, response: 20 Hz-20 kHz, about +-15 dB. Figure C, dimensions. Figure D, polars
  in bands: "at 70 / 70 to 250 / 250 to 3,500" Hz and "3,500 to 7,000 / 7,000 to 10,000 /
  at 10,000" Hz; rings -5, -10, -15 dB.

### The SM57 later (the same cartridge; the transformer's change)

- c74: "Dual: 50 and 150 ohms"; "Open Circuit Voltage: H -75.5 dB (.17 mV), L -81.5 dB
  (.082 mV)"; "146 mm long, 31.8 mm diam." [sic].
- c77: "38 ohms and 150 ohms"; 38 ohms -82 dB (.079 mV), 150 ohms -76 dB (.157 mV);
  157 mm x 32 mm, 284 g.
- c81: "Dual: 38/150 ohms"; 0.08 mV (38 ohms), 0.17 mV (150 ohms); polars now at 125 / 500
  / 1000 and 2000 / 4000 / 8000 Hz. c86: still dual 38 / 150.
- c88: "Impedance: 150 ohms (310 ohms actual)", -75.5 dB (0.17 mV). c93: "150 ohms (300 ohms
  actual)". So the tap went between the 1986 and 1988 catalogs (vear95: "50 ohm tap (orange
  wire) eliminated from transformer (1980's)"; "Brown 'gooey' transformer potting compound
  changed to RTV silicone (1970's)").
- A forum quote of an old Shure rating, "38 ohms (70 ohms actual)" with "150 ohms (310 ohms
  actual)" (music-electronics-forum; the Shure document wasn't found).
- g02: -54.5 dBV/Pa (1.9 mV), "150 ohm (310 ohm actual)". g06 / sp10 / g25: -56.0 dBV/Pa
  (1.6 mV) open circuit at 1 kHz; "Rated impedance is 150 ohm (310 ohm actual)" (g06);
  40-15,000 Hz; 0.284 kg; "die-cast steel with a polycarbonate grille and a stainless steel
  screen" (g25). Proximity, text only (g06): "less than 6 mm (1/4 in.) ... boosts bass
  frequencies (by 6 to 10 dB at 100 Hz)"; g25: "6 to 10 dB below 100 Hz when the microphone
  is at a distance of about 6 mm (1/4 in.)". No proximity curve was found in any Shure
  document, old or new.
- Replacement cartridge R57 (g25: "Cartridge for SM56 and SM57"); the SM58's R59 (g24), in
  1970 99B352 (s70). The 545SD (Unidyne III, g18): "150 ohms (250 ohms actual)", L -58.0
  dB (1.3 mV).

### The SM58 (s70, g24)

- s70: "50 to 15,000 Hz"; "Dual. 30-50 ohms and 150-250 ohms"; the same outputs as the
  SM57 (L .067 mV, H .149 mV); "15 ounces (425 grams)"; "6-3/8 (161.9 mm) ... 2 (50.8 mm)";
  the same transformer figure; polars in the same bands. g24: 50-15,000 Hz; -56.0 dBV/Pa
  (1.6 mV); "Output Impedance 300 ohm"; 0.33 kg; "spherical steel mesh grille".

## The cartridge's construction (pat883, seeler61, pat905, born12)

The SM57 / SM58 cartridge is the Unidyne III. pat905 says so: "Microphones of the type
described in the Seeler patent have been marketed under the tradename 'Unidyne III' ...
since the early 1960's" (the Seeler patent there is pat883). pat883's embodiment is a
545-era end-address mic; the SM57 packages the same cartridge (born12 describes the same
parts in the SM57). From pat883 (Fig. 1-4) and seeler61 (Fig. 2):

- A magnet 13 with an inner pole piece 14 in front; an outer pole piece 15, a tube; the
  radial air gap 16 between them; a brass spacing bushing 17 behind the gap; the pole piece
  ring 18 and the yoke 19 close the circuit at the rear. The voice coil 20 ("a number of
  turns of fine wire cemented together to form a solid structure in the form of a short,
  thin-walled tube") is cemented to the diaphragm 21, carried on the resistance ring 22 on
  the outer pole piece.
- In front of the diaphragm, "a protective, perforated resonator plate 23 ... substantially
  parallel to the diaphragm", "with a plurality of circularly arranged" holes 24, behind
  the headpiece's screen 12. born12 on the SM57's cap: "there is a space of air above the
  diaphragm, and that space of air is tuned to a particular resonant frequency. [It is] a
  very high frequency ... The more air you have above [the diaphragm], or the bigger holes
  you have [within the resonator cap], create a lower frequency [boost]." hr23's photo of
  a capsule's face shows a ring of 7-8 round holes around a solid centre.
- The rear entry: screen 39 at radial openings where the headpiece meets the shell,
  recesses 40 along the outer pole piece, apertures 41 in the resistance ring (pat883);
  seeler61: Z1 = p L1 + R1, "the inertance and the acoustical resistance of the annular
  slit which surrounds the magnetic structure and which contains the screen B"; P2 "the
  pressure at the back opening of the annular slit". born12: the mesh at the capsule's
  base holds "the rear-entry ports"; the delay comes from "a resistance cloth".
- Behind the diaphragm: cavity 42 under the dome (Ca), the coil's gap passages 43 and
  apertures 29 in the bushing with cloth screen 28 (Lb, Rb), felt 30 filling the space
  between the magnet and the outer pole ring (R'b), that felt-filled chamber (Cb); in
  pat883's full network also yoke apertures 31 and a felt / cloth washer 32 (compressed by
  nut 34 against plate 33: adjustable) into the case chamber 44 and the transformer chamber
  45 (C'b), joined by holes 46.
- pat905: chambers 44 and 45 are a pneumatic shock canceller; their pressure reaches the
  dome's back through holes 46, plate 33, washer 32, apertures 31, felt 30, screen 28,
  passages 29 and gap 16. born12 on the SM57: "The volume of air that's between the closing
  ring and the transformer ... when you screw the handle of the '57 together, that volume
  of air is part of the tuning process"; "Every chamber of air in here is tuned to a
  specific value and a specific volume."
- The diaphragm (pat713): molded Mylar, two intersecting concentric cones, the coil on the
  stiff circle where they meet; bridges (33, 42) let air under the dome and across the
  coil. seeler61: "molded Mylar ... as thin as 1/4 mil" (the OCR reads "4 mil"; the page
  image reads 1/4). The bridges break axial symmetry (a note for SM3's shell FE). born12:
  "typically made out of mylar"; the coil "normally made out of copper, or aluminum, or
  copper-clad aluminum of some sort" (in general, not the SM57's). The 1993 laminate
  (pat036) isn't tied to a product.
- born12: "The resonant frequency of the diaphragm of an SM57 or SM58 is pretty low, in
  the 100Hz area." Damping: "a cavity behind ... resistance materials under the microphone
  ... a lot of resistance cloth that is tuned to a specific resistance value ... small gaps
  of air."

No source gives a dimension of the cartridge: no diaphragm or coil diameter, gap, magnet
size, port or cavity size. RecordingHacks lists the coil diameter as "n/a". The magnet
material: "ceramic" in the classic SM mics, neodymium in the Beta series (a GroupDIY post,
2006, unsourced); Shure's own page says only that the Beta 57A has "hotter output due to
neodymium magnet design".

## The phase-shift network (seeler61)

Fig. 2: P1 -- Z3 (the diaphragm and coil, p L3 + R3 + 1 / p C3) -- the node under the dome;
from it Z1 = p L1 + R1 to P2 and Z2 = Ca || (p Lb + Rb + 1 / p Cb) to the ambient.
Eq. 1: u = [(1 + Z1 / Z2) P1 - P2] / [Z3 (1 + Z1 / Z2) + Z1]; P2 = P exp(-p K cos theta),
K = d / c, d "the 'effective' acoustical distance between the center of the diaphragm and
the back opening (d is usually taken as the shortest unobstructed distance between these
two points and is assumed to be independent of frequency ...)". The cardioid needs
1 + Z1 / Z2 = exp(p K) (Eq. 3), independent of Z3. Matched to fourth order (Eq. 5):
K = R1 (Ca + Cb), K^2 / 2 = L1 (Ca + Cb) - R1 Rb Cb^2, K^3 / 6 = ..., K^4 / 24 = ...;
with q = L1 / (K R1) > 1/2 (Eqs. 6-10): Cb = (K / R1) s, Ca = (K / R1)(1 - s), Rb = R1 (2q -
1) / (2 s^2), Lb = (K R1 / 12 s^3) {3 (1 - 2q)^2 - 2s [1 - 3q (1 - 2q)]}, s a root of Eq. 10.
Implemented in `varimu.devices.moving_coil.seeler_rear_network` (the root: its docstring;
the paper's "larger root" gives Lb < 0 with the equations as printed, the smaller one all
positive; both satisfy Eq. 5: tests/test_moving_coil.py).

Low frequencies, on axis, R3 << R1, L3 ~ L1 (Eq. 15): U ~ 2 P K w / {R1^2 + w^2 (L1 + L3)^2
[1 - f1^2 / f^2]^2}^(1/2), f1 = 1 / 2 pi [(L1 + L3) C3]^(1/2): below f1 the volume velocity
rises at 12 dB / octave, above it U ~ 2 P K / (L1 + L3), flat (the diaphragm mass-
controlled); R1 damps the resonance. Measured (on the 545, Figs. 5-6): cardioid at 70 Hz
with 13 dB at 180 degrees; at 125 Hz 6 dB at 90 degrees; 20 dB at 90 degrees by 10 kHz; a
back lobe from 3.2 kHz, 12 dB at 180 degrees at 10 kHz.

Design rules elsewhere: Bauer (pat596, p. 7) d / c = R'C' - R C, L = C R^2 / 2, valid while
d is under a quarter wavelength; his Unidyne I (pat596, Fig. 10): pole piece ~3.8 cm square,
coil ~2.8 cm, d ~2.5 cm, cavities 6 cc, a passage 0.16 cm long and 0.007 cm thick, Ca = Cb
= 2.1e-6 cm^5/dyne, R' = 17.3 and Rb = 50 acoustical ohms, L' = Lb = 0.0015 g/cm^4, the coil's
resonance "in the neighborhood of 60 cycles". Shure's US 10,542,337 (Grinnip, 2020) Fig. 1:
the rear tuning resistance "is typically set to a value equal to the critical damping
resistance R_d of the diaphragm/coil system". wt31 p. 569: an annular slit's "acoustic
resistance ... 12 mu l / (d^3 w) and the reactance j (6/5)(rho l / (w d)) omega" (l radial
length, d width, w annular length).

## The electrical side

- The coil: DC resistance "12.1 Ohms" at the capsule's terminals, "12 point something ...
  I tested three" (hr23, forum); "in the 10 ohm range. 1kHz inductance is about 200uH
  IIRC" (Les, Gearspace 2012, forum; the only inductance figure found). born20: "Without
  the transformer, the output impedance of a SM57 at 1kHz is approx 14-20 ohms."
- The transformer, a 1990 SM57's (single 150 ohm winding; cj06): "Pri- DCR - 1.50 ohms L =
  386 mH Leakage - 150 uH"; "Sec- DCR - 24.18 Ohms L = 7.95 H Leakage - 4.26 mH"; "Impedance
  Ratio: 1:20.6 / Turns Ratio: 1:4.53" (the square root of 7.95 / 0.386 is 4.54); "ratio
  changes from 1:3 to 1:4 and then 1:5 as the level goes up ... This is probably the core";
  "Starts to droop before 20 K".
- The transformer of an old dual-impedance SM58 (psw17, Mike Caldwell, 7 Dec 2017): "The
  150 ohm side measured 25.7 ohms DC resistance and the 50 ohm side measured 10.8 ohms".
  Other secondaries: 16-25 ohm (psw17, several units); 17.8 ohm (Khron's blog, 2021, with a
  1.6 ohm primary).
- tab07, a stock SM58 transformer from a 10 ohm source, gain at 1 kHz: +5.95 dB into 200
  ohm, +10.0 dB into 600 ohm, +12.7 dB into 10 kOhm; re 1 kHz at 10 / 20 / 30 kHz: -0.5 /
  -1.85 / -3.55 dB (200 ohm), -0.05 / -0.5 / -1.15 dB (600 ohm), +0.2 / +0.25 / +0.4 dB
  (10 kOhm); at 20 Hz -0.25 / -0.4 / -0.55 dB; THD at -10 dBu 0.025% (100 Hz), 0.0035-0.005%
  (1 kHz). The same sheet's replacement (T58): "Primary inductance: 250 mH (120Hz) @ 1.5
  Ohm; Step up ratio: 1 to 5; Secondary inductance: 5.4H"; moving-coil elements "typical 15
  to 25 Ohm". No core type, lamination, bobbin or wire for the stock part.
- The transformerless mod: about 10 dB less (born20; born12: "We get about 10 dB more signal
  level through the use of this transformer in the SM57. And we gain about 200 ohm on the
  impedance"); "drops 12 db. The low end does extend down toward 20 hz, where the stock mic
  drops fast under 50 hz" (Jim Williams, R/E/P 2005, forum); "about 12dB" (DIYRE, 2011).
  The turns ratio's 4.53 is 13.1 dB.
- Impedance at 1.28 kHz (ee18): "Shure SM58 Mexico 310 ohm", "Shure Unidyne III vintage SM57
  U.S. 228 ohm".
- Loading (hau): "An einem Preamp-Input mit 2.000 Ohm erzeugt die 250-Ohm-Ausgangsimpedanz
  des SM57/58 einen Pegelverlust von ca. 1 dB ... mit nur 250 Ohm ... 6 dB"; Paul Stamler
  (GroupDIY 2008, listening only): "a 500 ohm load impedance turns the SM57 into a very
  different ... microphone". No measured response into the four loads was found.
- Self-noise: "around 20dB SPL" (PRR, GroupDIY 2005, forum). Max SPL: secondhand Shure
  claims only (~150 dB SPL at 100 Hz, ~160 at 1 kHz: Andertons' blog).

## Every network element: source or estimate (SM1's done-when)

The network is seeler61's Fig. 2 with pat883's further branch (the case and handle
chambers: born12 says they are tuned), the resonator in front (pat883, born12), and the
grille. "Provisional" values are model knowledge with the reasoning given; each is a
bounded unknown in `scripts/fit_sm57.py` or replaced when a source turns up. Geometry is
given where the formulas need it (varimu/devices/moving_coil.py).

| Element | Value / how | Source |
|---|---|---|
| K = d / c, the entries' delay | d: the diaphragm's centre to the rear entry around the cartridge's front edge, ~15 mm (the radius ~11 mm plus ~8 mm back along the side, shortened by diffraction); bounded 10-22 mm | provisional: the 31.75 mm head (s68) and pat883's Fig. 2 layout |
| R1, L1: the rear entry (annular slit, screen B) | fitted: R1 to the low end's damping (Grinnip: ~ the critical damping resistance), q = L1 / K R1 to the front-to-back ratio at 125-1000 Hz | fit (seeler61's parameters) |
| Ca, Cb, Rb, Lb: under the dome, the coil gap + screen A, the magnet's felt cavity | from K, R1, L1 by seeler61's Eqs. 5-10 (no further unknowns) | derived: seeler61 |
| C'b, R''b: the washer into the case and handle chambers | both fitted to c81's pattern at 125 Hz (its first-order shape needs the network's delay ~1.8 times the entries' path there: the air behind the washer lengthens it below the washer's corner); the volume bounded 0.5-40 cm^3 (at most the body's ~20 cm^3) | fit; pat883, pat905, born12 (its role) |
| The diaphragm's area S | effective radius 8 mm (a ~22 mm clamped diaphragm in a ~27 mm cartridge, the outer surround moving less); bounded 6.5-9.5 mm | provisional: s68's 31.75 mm head; pat713's form |
| Moving mass m (L3 = m / S^2) | dome: Mylar 1/4 mil (seeler61) at 1390 kg/m^3 over the moving area, ~2.5 mg; coil: its copper length l = B l / B over the measured 12 ohm DCR (hr23), mass = density x resistivity x l^2 / R, ~18 mg at l = 1.2 m; former and adhesive ~3 mg; air load on both faces 8 rho a^3 / 3 each, ~3 mg | derived from sourced figures and the provisional B |
| B in the gap | 0.9 T (a small ceramic / Alnico circuit), bounded 0.6-1.2 T | provisional: model knowledge |
| Bl | fitted to the sensitivity: s68 H 0.149 mV/ubar at 1 kHz open circuit through the transformer | fit |
| Compliance C3 | fitted to the resonance ~100 Hz (born12) with the moving mass | fit |
| R3, the suspension's loss | small against R1 (seeler61: R3 << R1): Q of the diaphragm alone ~3 | provisional: model knowledge |
| The resonator (cap in front) | 8 holes (hr23: 7-8) of ~0.7 mm radius in a ~1 mm plate, their visco-thermal loss in Crandall's wide-tube limit at 9.6 kHz, into the thin air layer between cap and dome (radius 11 mm, fed at 6 mm, 0.15 mm, 60% fill) filled by radial viscous flow (the `film` element: its loss damps the cap without costing the rear rejection, as a screen in series would). Provisional in R57@1; the region above 4 kHz is SM3's / SM4's | provisional geometry; hr23 (hole count), pat883, born12 |
| The grille screen | the SM57's stainless screen (g25) over the head's face: a woven screen's resistance, ~10 rayl over ~5 cm^2 (negligible but present) | provisional: model knowledge |
| Coil Re | 12.1 ohm | hr23 (forum, three capsules) |
| Coil Le | 200 uH; L2 || R2 none until an impedance curve is found | Les, Gearspace 2012 (forum, "IIRC") |
| The transformer | turns 1 : 4.53 on the full secondary (cj06, the 1990 unit: the tap's removal is the only change vear95 names besides the potting); the tap at 2.22 / 4.53 of the turns (the s65 / s68 voltage ratio); primary 1.50 ohm, 386 mH, 150 uH leakage; secondary 24.18 ohm, 7.95 H, 4.26 mH leakage (cj06); the tap's DCR 10.8 ohm of 25.7 (psw17) | cj06, s65 / s68, psw17; the construction (SM5) provisional |

The body (SM4): the SM57's head as a body of revolution, 31.75 mm diameter (s68 Figure C:
2-1/2 in (63.50 mm) of grille head, 2-31/32 in (75.39 mm) taper, 23.81 mm at the
connector end). For SM2 the entries are a rigid sphere's (the plan: "the body as a sphere
first").

## Not found

Proximity curves at stated distances (any era); an impedance curve; the response into
150 / 600 / 2.5k ohm; the transformer's core and windings; a Shure part number for the
transformer ("51A303" only on vendor and forum pages); any dimension of the cartridge; a
Shure or AES paper on the SM57 itself; the 1966 SM58 sheet's first printing; Beranek
(1954) and Olson (1957) in a readable copy; Bauer 1941 (paywalled).

## Fitted (R57@1, scripts/fit_sm57.py; reports/mics/r57_fit.json)

| Unknown | Value | Its figure |
|---|---|---|
| B l | 2.31 T m | s68 'H' 0.149 mV/ubar open circuit: 1.488 mV/Pa |
| resonance | 117 Hz (Born: "in the 100Hz area") | s68's low end (50-150 Hz) |
| R1 | 3.11e6 Pa s/m^3 | s68's low-end damping (the bump at 180 Hz) |
| q, d | 9.93, 23.2 mm | c81's side ratio at 1-2 kHz, s68's rise to 4 kHz |
| washer, the air behind it | 2.03e7 Pa s/m^3, 4.6 cm^3 | c81 at 125 Hz: -4.9 / -10.8 dB (published -3.8 / -10.8) |
| the rear ring on the sphere | 97.6 deg | c81's rear at 1-2 kHz: -19.6 / -22.2 dB (-20.7 / -20.0) |

Derived: Seeler's Ca 1.97e-12, Cb 1.97e-11 m^5/N, Rb 3.55e7 Pa s/m^3, Lb 1017 kg/m^4; moving
mass 106 mg (dome 1.8, wire 83.9, adhesive 16.8, air 3.3 mg; the wire 2.57 m at B 0.9 T). The
on-axis response 50 Hz-4 kHz: 0.71 dB rms against s68. Above: SM3 / SM4 (docs/SM57_PLAN.md
"Status").

## Fitted on the body (R57@2, SM4; scripts/fit_sm57.py --ports-mm 6)

The mic as a rigid body of revolution (`bor.dynamic_mesh`; s68 Figure C's outline, the
cartridge's face 13 mm in radius and 22 mm deep, provisional; the grille open). Its rear ports
a band 3-9 mm behind the face (a grid: 3-9 / 5-11 / 7-13 / 11-17 / 15-21 mm; cost 60 / 64 / 123
/ 243 / 168). Fitted: B l 0.620 T m and B 1.137 T (the sensitivity: 1.491 mV/Pa), resonance
148 Hz, R1 3.40e5 Pa s/m^3, q 22.4, d 17.5 mm, washer 1.26e6 Pa s/m^3, the air behind it 20
cm^3 (at the body's bound). Moving mass 9.6 mg. The on-axis response 50 Hz-6.5 kHz 1.08 dB rms
against s68, the presence peak included (the body's diffraction); the polars at every c81
frequency within 3 dB (docs/SM57_PLAN.md "Status"). R57@1 (the sphere) stays for the record.

## R57@3 (the cap fitted on the body)

The cap's holes (0.75 mm radius) and its air layer's effective height (0.072 mm) gridded
against s68's 6.5-14 kHz on the body, then the network refitted (`fit_sm57.py --ports-mm 6`):
B l 2.45 T m, B 1.2 T (bound), resonance 97 Hz (Born: ~100 Hz; not a target), R1 2.11e6,
q 13.8, d 17.7 mm, washer 1.59e7 Pa s/m^3, 2.5 cm^3 behind it; moving mass 69 mg.
Sensitivity 1.487 mV/Pa; on axis 0.60 dB rms to 6.5 kHz, 2.42 dB rms above; polars within
2.4 dB at every c81 frequency.
