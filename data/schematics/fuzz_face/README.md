# Arbiter / Dallas-Arbiter Fuzz Face (germanium, c.1966-68) sources

Collected 2026-11-12 for a Fuzz Face model (worktree `vst-amps`, branch `amps`). Arbiter
Electronics (London) made the Fuzz Face from autumn 1966, "Dallas-Arbiter" from about 1968;
the germanium PNP version came first, silicon NPN later (ElectroSmash, Fuzz Central). No
circuit file exists yet; values going into one should cite these as `sch:` (none exists, see
below), `trace:` (a third-party trace or redraw of a real unit), `web:` (an analysis page or
a datasheet) or `provisional:`. The transcriptions below are from one research pass
(2026-11-12): recheck each against its image when it goes into the circuit file.

## The drawings (all in this folder)

Tags used in the value lists:

| Tag | File | What it is |
|---|---|---|
| **ES** | `electrosmash_fuzz_face_schematic.png` (4541 x 3233), `electrosmash_fuzz_face_bias.jpg` (DC voltages), `electrosmash_fuzz_face_pcb.jpg` (original board photo) | ElectroSmash, "Fuzz Face Analysis": "the first Arbiter Fuzz Face model equipped with PNP germanium transistors"; BOM with designators C1-C3, R1-R4, Rvol, Rfuzz; bias points; two germanium SPICE cards. |
| **RGK** | `keen_basic_fuzz_face_1998.gif`, `keen_fuzz_face_mayer_mods_1998.gif` | R.G. Keen, "The Technology of the Fuzz Face" (1998): "Basic Fuzz Face" and the "Roger Mayer / Jimi Hendrix" mods. Text in `keen_technology_of_the_fuzz_face_1998.html` (transistor gains, leakage, a leakage / gain test). |
| **FC** | `fuzzcentral_fuzz_face_pnp_ge_trace.gif`, `fuzzcentral_fuzz_face_npn_si_trace.gif` | Fuzz Central (Dano), "Arbiter Fuzz Face": "a schematic of the original Germanium transistor version of the Dallas-Arbiter Fuzz Face" (and the silicon one), with pot tapers; the page's text on the original parts is in `fuzzcentral_fuzz_face_page.html`. |
| **HHW** | `whitehead_holmes2017_fuzzface.mod` (in `holmes_holters_vanwalstijn_2017_dafx_germanium_bjt_models.pdf`, Fig. 9) | The Fuzz Face that Holmes, Holters and van Walstijn simulated (DAFx-17). **Not the 1966 values** (62K feedback, 36K / 11K / 680 ohm collector resistors, 22 uF, 0.1 uF, a 1K + 6.8 nF source): listed for the transistor card only. |

No Arbiter / Dallas-Arbiter factory schematic was found anywhere (ElectroSmash, Fuzz
Central, Keen, the DAFx paper and the Wikipedia article all draw their own; a Scribd copy of
an analysis notes the original "had a complex switching system which has been simplified
and a unique grounding setup", unverified). So every circuit value below is `trace:` or
`web:`, never `sch:`.

Provenance:

- ES: web: https://electrosmash.com/fuzz-face. **electrosmash.com did not resolve on
  2026-11-12** (DNS); page and images were fetched from the Wayback Machine, snapshot
  2026-05-18 (web: http://web.archive.org/web/20260518130743/https://electrosmash.com/fuzz-face).
  Page saved as `electrosmash_fuzz_face_analysis_wayback_20260518.html` (raw `id_` copy;
  the SPICE cards are in its text). Images: `images/tech/fuzz-face/fuzz-face-original-schematic-parts.png`,
  `fuzz-face-bias.jpg`, `fuzz-face-pcb.jpg`.
- RGK: web: http://www.geofex.com/Article_Folders/fuzzface/fftech.htm, images `fftech1.gif`,
  `fftech2.gif`.
- FC: web: https://fuzzcentral.ssguitar.com/fuzzface.php, images
  `fuzzface/fuzzfacepnpschematic.gif`, `fuzzface/fuzzfacenpnschematic.gif`.
- HHW: the paper web: http://bencholmes.github.io/files/Comparison%20of%20Germanium%20BJTs_Holmes%20et%20al.pdf
  (B. Holmes, M. Holters, M. van Walstijn, "Comparison of Germanium Bipolar Junction
  Transistor Models for Real-Time Circuit Simulation", Proc. DAFx-17, Edinburgh, 2017); the
  ngspice files from Greg Whitehead's repository web: https://github.com/grwhitehead/germaniumbjts
  (MIT licence, `whitehead_germaniumbjts_LICENSE.txt`; page web:
  https://grwhitehead.github.io/germaniumbjts).

## Values

Negative ground: the battery's (+) is ground, its (-) is the -9 V rail; emitters to ground
(Q1 directly, Q2 through FUZZ), collectors toward -9 V.

| Part | ES | RGK | FC | Pick |
|---|---|---|---|---|
| C1 input cap | 2.2 uF electrolytic, + toward the input jack | 2.2uF | 2.2µF ("electrolytic axial lead") | 2.2 uF electrolytic |
| Q1 | AC128 | Q1 | NKT275, AC128 or SFT363E | AC128 (see versions) |
| R1, Q1 collector to -9 V | 33K | 33K | 33K | 33K |
| Q1 collector to Q2 base | direct | direct | direct | direct |
| Q2 | AC128 | Q2 | as Q1 | AC128 |
| R3, Q2 collector to the output tap | 8.2K | 8.2K | 8K2 | 8.2K |
| R2, output tap to -9 V | 470 | "330 or 470" | 470 | 470 ohm |
| R4, feedback from Q2's emitter to Q1's base | 100K | 100K | 100K | 100K |
| FUZZ, Q2's emitter to ground | 1K "linear tap" | 1K | "Fuzz 1KB" | 1K, B (linear) |
| C2, FUZZ wiper to ground | 20 uF, + to ground | 20uF ("2ouF") | 20µF ("electrolytic with axial leads") | 20 uF electrolytic |
| C3 output cap, from the tap | 0.01 uF | 0.01 (drawing; the text says "the output 0.1uF capacitor") | 0.01µF ("metallized polyester") | 0.01 uF film |
| VOLUME | 500K "audio tap", cold to ground | 500K | "Volume 500KA" | 500K, A (log) |
| Supply | 9 V battery, no filter capacitor ("the power supply does not include any capacitors") | 9V | 9V | 9 V battery alone |

- The output is taken at the junction of R2 (470, to the rail) and R3 (8.2K, to Q2's
  collector): with the battery an AC ground, R2 / (R2 + R3) = 0.054, -25 dB (ES; RGK "acts
  like a volume pot permanently set to a low value").
- FUZZ: the whole 1K track from Q2's emitter to ground, the wiper to C2. Full fuzz = the
  wiper at the emitter end (all of the 1K bypassed for AC); ES and RGK's gain arguments.
- Parts in the originals (FC): resistors 1/2 W carbon composition, ±10 %; C1 and C2 axial
  electrolytics; C3 metallized polyester.
- Switch: true bypass on a DPDT footswitch (ES: "the first pedal including a DPDT
  stomp-switch"). Not modelled (effect on only). Whether the input jack switches the
  battery is not shown on any drawing found.
- C2 at 22 uF: no source found for 22 uF in a 1966-68 unit (HHW's measured circuit and
  modern kits use 22 uF). Pick 20 uF (ES, RGK, FC).
- Battery internal resistance: ES and RGK both say it matters ("FF sounds different with
  different batteries and with the same battery as it gets run down"; it adds to R2's
  470). Not published: provisional: model knowledge (a 1960s PP3 / 006P carbon-zinc cell of
  the order of 10-35 ohm fresh, rising as it runs down; a modern alkaline 1-2 ohm); make it
  a genome parameter (5-50 ohm). ES cites a DingoTone paper on Fuzz Face batteries (not
  fetched).

### Bias targets

- ES (`electrosmash_fuzz_face_bias.jpg`, simulated with Q1 β = 85, Q2 β = 120, FUZZ at
  mid-travel): Q1 base -0.2 V, Q1 collector -0.7 V, Q2 emitter -0.5 V, Q2 collector
  -4.5 V, output tap -8.7 V, rail -9 V. ES: "The important settings to get the best sound
  out of a Fuzz Face is to have Q1 VC = -0.5 to -0.7 and Q2 VC = -4.5V" (citing web:
  http://www.physics.mcgill.ca/~grant/Stuff/fuzzface.txt, not fetched).
- RGK: "Fuzz Faces naturally tend to bias with only about half a volt on the collector of
  the first transistor".
- So the model's check: Q2 collector about -4.5 V and Q1 collector -0.5 to -0.7 V at
  room temperature with a Q1 / Q2 pair in the ranges below.

### Transistor gains (selection)

- ES: "the best match uses a low gain in the first stage (β = 70-80 approx.) and a high gain
  in the second stage (β = 110-130 approx.)"; "for a more compressed sound you can use β =
  90-120 for Q1 and β = 150-190 Q2".
- RGK: a sweet spot at gains "of about 80-110. If you allow combinations of one high and one
  low gain device, the range widens out to 70 or so on the low end and perhaps 130 on the
  high end"; "The right *real* gains are from 70 to about 130 ... Some people prefer equal
  gains, others prefer having a lower gain of 70-100 for the first transistor and 90 to 130
  for the second." AC128s he measured ran "from a gain of 16 to probably 180"; readings up
  to ~500 "are clearly leaky devices". Leakage (his open-base test, i.e. ICEO at 9 V):
  "100uA is common, 200 happens pretty often. More than 300uA means the device is
  suspicious, and more than 500uA I would say is bad."
- FC: "the Q1 hfe of 70 and Q2 hfe of 120".
- Pick: Q1 hFE ~80 (70-90), Q2 ~120 (110-130), ICEO ~100 uA each, as genome ranges.

## Germanium PNP data

### AC128 datasheets

- **Valvo** (Philips Germany), "AC 128, Germanium-p-n-p-NF-Transistor für Endstufen",
  Vorläufige Daten 8.63 (pages dated 8.63 / 9.62 / 4.62), 7 pages:
  `valvo_ac128_datasheet_1963.pdf`, from ElectroSmash's "AC128 Transistor datasheet 1"
  (web: https://electrosmash.com/images/tech/fuzz-face/ac128_datasheet1.pdf, via the Wayback
  Machine; byte-identical to `references/ac128.pdf` in Whitehead's repository). At
  junction 25 C:
  - ICBO <= 10 uA at -VCB = 10 V; IEBO <= 500 uA at -VEB = 5 V, 75 C;
  - VCB >= 32 V at ICBO = 200 uA; VEB >= 10 V;
  - VCE(sat) ("Kollektor-Restspannung") <= 0.6 V at -IC = 1 A;
  - -VBE <= 300 mV at IE = 50 mA, <= 450 mV at 300 mA (VCB = 0);
  - hFE (B) = 90 (55-175) at IE 50 mA, 90 (60-175) at 300 mA, 80 (45-165) at 1 A;
  - f1 (|β| = 1) 1.5 MHz (>= 1.0) and fβ 15 kHz (>= 10) at -VCB 2 V, IE 10 mA;
    rbb' = 25 ohm at -VCB 5 V, IE 1 mA; Cb'c = 100 pF at -VCB 5 V;
  - limits: VCB / VCE 32 V, VEB 10 V, IC 1 A, P 700 mW, Tj 90 C;
  - curves: output characteristics to 1 A (p. 3); IE vs IB, mean and spread, 0-10 mA and
    0-1 A (p. 4); **IE vs -VBE, mean and spread, 0-10 mA and to 1 A (p. 5)**, with
    dVBE / dT = -2.3 mV/K and dVBE / dVCE = 0.4 mV/V; hFE vs IC (p. 6); **ICBO vs
    junction temperature, mean and maximum, at -VCB 10 and 32 V (p. 7)**.
  - Read by eye (to digitize before fitting): p. 5's mean curve at 25 C, VCB = 0: -VBE
    ~78 mV at 0.3 mA, ~103 at 1 mA, ~120 at 2 mA, ~138 at 4 mA, ~163 at 10 mA, spread about
    ±15 mV; p. 4's mean IB at IE = 10 mA ~115 uA (hFE ~86); p. 7 at -VCB = 10 V: ICBO mean
    ~4 uA at 25 C (max curve 10 uA), ~50 uA mean at 60 C, doubling about every 9-10 K.
  These are the only small-current AC128 data found, and the Fuzz Face runs Q1 at a few
  hundred uA.
- **Germanium Power Devices Corp.** catalog, "Germanium Small Signal Transistors, Pro
  Electron Types" (4 pages): `gpd_germanium_small_signal_catalog_ac128.pdf` (ElectroSmash's
  "datasheet 2"). AC128: PNP, VCBO 32 V, VEBO 10 V, VCE 16 V, ICBO 10 uA max at VCB 10 V,
  hFE 55-175 at IC 50 mA, Cob 100 pF max, fab 1.0 MHz min, TO-1, 340 mW (a later US
  production, not 1966 Mullard / Philips parts).
- Mullard's own AC128 sheet wasn't found.

### SPICE cards (Gummel-Poon)

1. **Holmes, Holters, van Walstijn 2017 (DAFx-17), Table 1**: parameters extracted from a
   measured vintage AC128 (Keithley 2602B; common-emitter, forward and reverse Gummel
   sweeps; one device), as published and as Whitehead's `whitehead_germaniumbjts.lib`
   writes them:
   `.MODEL AC128 PNP(IS=20.66u BF=229.6 BR=14.66 NF=1.133 NR=1.140 VT=25.5m VAF=19.68
   VAR=88.28 IKF=463.0m IKR=241.5m ISE=2.190u ISC=7.546u NE=1.796 NC=1.364 RB=1.885
   RE=306.4m RC=1.727u CCB=100p)`.
   - Every DC parameter of the project's subset is there (IS, BF, BR, NF, NR, VAF, VAR,
     IKF, IKR, ISE, NE, ISC, NC) plus RB, RE, RC. CCB 100 pF is a constant
     collector-base capacitance (the paper's "constant capacitance values"; Valvo's
     Cb'c = 100 pF); no emitter-base capacitance for the AC128 (the OC44's CEB 410p).
   - VT = 25.5 mV is the measurement's thermal voltage (room temperature, T = 296 K =
     22.8 C), not a SPICE .model parameter (Whitehead's lib keeps it; ngspice ignores it).
     The project's model sits at TNOM 27 C (Vt 25.85 mV): a component file should either
     accept the 1.4 % Vt difference or set the junction temperature; for temperature
     scaling germanium needs EG = 0.67 eV (the card has none; SPICE's default 1.11 is
     silicon's).
   - Evaluated in the project's DC subset (my check, Vt 25.5 mV, VCE 4.5 V): VBE 106 mV at
     1 mA and 173 mV at 10 mA (Valvo's mean, read by eye: ~103 and ~163); IC / IB ~69 at
     1 mA, ~82 at 10 mA, ~108 at 50 mA (Valvo: 90 typ at 50 mA); below ~0.5 mA the leakage
     dominates and IC / IB is meaningless. Leakage: ~40 uA collector current with the base
     shorted to the emitter at 10 V (ICES, at least ICBO; Valvo's ICBO: ~4 uA typ, <= 10 uA
     max at 25 C), ICEO (open base, 9 V) ~350 uA, which Keen
     would call "suspicious". So this one device is leaky and lower in gain at Fuzz Face
     currents than the selection targets: use it as the structure and refit IS / ISE /
     ISC / BF per instance to the hFE and leakage targets above (provisional until then).
   - The paper's OC44 card (same table) is also in the lib.
2. **ElectroSmash's cards** ("PsPice models used for AC128 Fuzz Face simulation", in the
   saved page), no stated derivation:
   - `GERPNP_LOWGAIN` ("AC128 with β = 85"): IS=85.8N BF=85.000 NF=1.000 VAF=102.207
     IKF=9.981M ISE=0.435N NE=1.200 BR=20.000 NR=1.000 VAR=20.000 IKR=1.248M ISC=120.8N
     NC=1.200 RB=173.312 IRB=5.000U RBM=43.328 RE=20.000 RC=60.000 CJE=6.000P VJE=0.400
     MJE=0.400 TF=0.150U XTF=9.996 VTF=2.000 ITF=9.983M PTF=1.000 CJC=3.750P VJC=0.600
     MJC=0.330 XCJC=0.650 TR=2.865U CJS=0.0 VJS=0.700 MJS=0.500 XTB=1.000 EG=0.670
     XTI=4.000 KF=5.000F AF=1.000 FC=0.750;
   - `GERPNP_HIGHGAIN` ("AC128 with β = 120"): the same with IS=120.8N, BF=120.000.
   - My check in the DC subset (27 C): VBE 244 mV at 1 mA (Valvo's mean ~103 mV: these
     cards are 2-3 times too high, silicon-like), ICES at 10 V ~0.2 uA (Valvo's ICBO ~4 uA typ), hFE 74 /
     104 at 1 mA. They give the right β by construction but neither germanium's low VBE nor
     its leakage: not picked.
3. Others seen in search summaries only (not used): a forum card attributed to Jim Hagerman
   (BF = 90, IS = 17u, RE = 220m, BR = 100m, VAF = 30), and a thesis card (BF = 70, IS =
   1.41f, VJE = 0.2, XTI = 3, EG = 1.11: a silicon-like IS), both via web:
   https://www.diyaudio.com/community/threads/ac128-pnp-germanium-transistor-spice-model-rare.117257/
   and web: https://www.mikrocontroller.net/topic/367147 (bot-walled, not read).

Pick: the HHW AC128 card as the structure (the only card extracted from a measured AC128),
refitted per instance to ES / Keen's hFE pairs and a leakage target, checked against
Valvo's VBE and ICBO curves (to be digitized).

### NKT275

- No SPICE card exists that I could find.
- No Newmarket datasheet found. A distributor's table (web:
  https://www.littlediode.com/components/NKT275.html): germanium PNP, TO-1, VCBO / VCEO
  15 V, VEBO 5 V, IC 0.25 A, PD 0.2 W, hFE min 30 at IC 1 mA, VCE 4.5 V, ICBO 10 uA max
  ("@ Vcb max"), fT 1.0 MHz (and 0.5 MHz in another field), Cc 60 pF, Tj 90 C. Radiomuseum
  calls it a germanium alloy PNP AF amplifier / driver (web:
  https://radiomuseum.org/tubes/tube_nkt275.html). Secondary data, not used for values.
- RGK: "followed by runs with the Newmarket NKT275, which is very similar"; his NKT275s
  "seem to be much more consistent than the AC128". Dunlop's reissues use newly made
  "NKT275"s (RGK), not the 1960s part.

2N1305 / 2N404: not documented as Fuzz Face parts in any source read; not pursued.

## Versions and the pick

- **AC128 vs NKT275 (1966-68)**: the sources conflict. ES quotes Dennis Cornell (who built
  them): "I think the Arbiter-England one didn't use the NKT275 germanium transistor; in
  those days we used the AC128." RGK: "The first ones seem to have been all AC128's ...
  followed by runs with the Newmarket NKT275". FC: "at least three types used: NKT275,
  AC128, and SFT363E" (FC's board photo has NKT275s). Vintage Guitar says the first used
  NKT275, "or sometimes AC128" (web: https://vintageguitar.com/16117/arbiter-fuzz-face,
  search summary only). **Pick AC128**: two of three first-hand-ish sources put it first,
  and it is the only one with a manufacturer's datasheet and a measured Gummel-Poon card.
- **Germanium vs silicon**: from about 1969-70 BC108C / BC109(C) / BC183L / BC209C / BC239C
  NPN silicon, positive ground (ES, RGK, FC). FC: with silicon "The 470-ohm resistor was
  replaced with a 330-ohm"; RGK's "330 or 470" covers both. Pick 470 for germanium.
- Arbiter's late-1980s reissue (AC128s): "not exactly a reissue, but an improved version",
  collector resistors and output cap varying unit to unit (FC). Not ours.
- RGK's "Roger Mayer / Jimi Hendrix" mods (R2 1K, R3 18K, FUZZ 2K;
  `keen_fuzz_face_mayer_mods_1998.gif`): a later tweak, not stock.

## Values that remain provisional

- Battery internal resistance (genome range), every transistor parameter until refitted to
  the hFE / leakage targets, pot taper laws (A for VOLUME, B for FUZZ: no curves printed),
  the germanium bandgap for temperature scaling (0.67 eV: textbook germanium, provisional:
  model knowledge; ElectroSmash's card also uses EG = 0.670).

## What wasn't found

- Any Arbiter / Dallas-Arbiter schematic, service sheet or parts list.
- Mullard's AC128 sheet; any NKT275 manufacturer sheet or SPICE card.
- The DingoTone battery paper and McGill's fuzzface.txt (cited by ES, not fetched).
- ElectroSmash itself (domain not resolving 2026-11-12): everything from it here is the
  Wayback snapshot of 2026-05-18.

## File hashes (sha256, downloaded 2026-11-12)

```
038515dde3138d2154f63c1a8963fdaef74fe3de35dd869a7f642babc9c34f48  electrosmash_fuzz_face_analysis_wayback_20260518.html
09e908805c0c54f862cfff6bdfa67499c7f13a5faa75817d637bef5b898e711d  electrosmash_fuzz_face_bias.jpg
4aae40946d87d6e12f490447d63248677a2ea72855ad3a50db8c24c190253c05  electrosmash_fuzz_face_pcb.jpg
804b318f2c862a6cfb6b2b0668bf7aac13b567544f18484e43352d70802cfd47  electrosmash_fuzz_face_schematic.png
57e73e15c047075eef0570e254b507f47b7a62bc5237efd1a0b278992c9de660  fuzzcentral_fuzz_face_npn_si_trace.gif
b2c3e43637f3866bf7a0c76b8503345599f9f2bc7ac99eb67a4d5297a2da3b40  fuzzcentral_fuzz_face_page.html
d50bb72791cd949f71e317170f9179671320368310a2a15df6769cb23d78f6ef  fuzzcentral_fuzz_face_pnp_ge_trace.gif
e78a5e2606329410c6525a2cd187e3214fea69bf33f3515995bd3ee229be9632  gpd_germanium_small_signal_catalog_ac128.pdf
2d73c9df818243477704566db72c05f5410d579c1b2c44cbd75a88e1e5bdad97  holmes_holters_vanwalstijn_2017_dafx_germanium_bjt_models.pdf
b7d67e809d50c5583a46c0f8651e66084ee5a841d14039c2ef73b27f373307a5  keen_basic_fuzz_face_1998.gif
ed04088cfd9138d08befb839c730baf60ddf855f93feaf2a802df3b67a172275  keen_fuzz_face_mayer_mods_1998.gif
65da940ed896de319b3128e062b813f88af0903a0c82ce936270e5ccea52fa53  keen_technology_of_the_fuzz_face_1998.html
f259590c73a6f1290a85d77b5e1b47a6681f796506ed5b91cc5d13f1be1ba8f7  valvo_ac128_datasheet_1963.pdf
d246c840f9610bfce04d744505ce414dcae0f52d9fdffe9f1ef2ff07c441e873  whitehead_germaniumbjts.lib
428cefbf407b4865deb9265db9901bff1d9934cc176106c41145b3b573e8cac4  whitehead_germaniumbjts_LICENSE.txt
c40b99a1418b605f9e42f07688c5ddc2179c13e4d024fa759cdabd0f006ce3c8  whitehead_holmes2017_fuzzface.mod
```
