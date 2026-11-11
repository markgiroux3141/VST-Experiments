# Discrete transistors and JFETs for the SSL bus compressor and the 1176

Downloaded 2026-11-06 for device builders B11 / B12 (data/schematics/ssl_bus_comp/,
data/schematics/urei_1176/).

## Files

| File | What | Source | sha256 |
|---|---|---|---|
| `central_2N3819.pdf` | Central Semiconductor 2N3819 N-channel JFET datasheet, 4 pp | web: https://my.centralsemi.com/datasheets/2N3819.PDF | `5284972fba6945f4e8ed48b287d5ebd1bfb74d0058211734d94cbcea34880c11` |
| `central_2N3053.pdf` | Central 2N3053 / 2N3053A NPN (the 1176 Rev A's Q6), 3 pp | web: https://my.centralsemi.com/datasheets/2N3053.PDF | `9678253b5961d21c397894e5ef8aff077160114bf6f39f039438b76648fdc6a2` |
| `central_2N2270.pdf` | Central 2N2270 NPN (Rev A's Q6 alternative), 3 pp | web: https://my.centralsemi.com/datasheets/2N2270.PDF | `d11253dd4a272a1dbded78fbd5cf02e98314884768b24b57fd1d337bbe20e479` |
| `central_spice/CSM1455.LIB` | Central SPICE model, 2N3819, 6/25/24 rev A | web: https://central.aeminc.com/docs/ENGINEERING/CSM/CSM1455.LIB | `d00358ff785397bb9b0d81803849bf16e4d5d342c85d20f8083608168dada2f7` |
| `central_spice/2N5457_CSM.LIB` | Central SPICE model, 2N5457, 11/8/22 rev A | web: https://central.aeminc.com/docs/ENGINEERING/CSM/2N5457_CSM.LIB | `80722026f6c2a2aab9f071f2ba6afef323f39248650d72672d707fb928ef2d4c` |
| `central_spice/CSM1481.LIB` | Central SPICE model, CMPFJ175 (SMD J175, P-channel; the SSL's COMP IN/OUT switch TR4), 7/15/24 | web: https://central.aeminc.com/docs/ENGINEERING/CSM/CSM1481.LIB | `d9d2fac1aabba7c4914de30d1fc56f18831eef9c36d9f37dd529462bfd14ba07` |
| `central_spice/2N3707.LIB` | Central SPICE model, 2N3707 (1176 Rev A Q3, Q5, Q7-Q10, Q12, Q13; Rev F Q12-Q15), 11/16/21 | web: https://central.aeminc.com/docs/ENGINEERING/CSM/2N3707.LIB | `43107b14a0a78ae717423cc8e8ede041362fe2ebe6c6d9f154786f630a7a328a` |
| `central_spice/2N3053.LIB` | Central SPICE model, 2N3053, 10/22/19 | web: https://central.aeminc.com/docs/ENGINEERING/CSM/2N3053.LIB | `a6e980ab6ab289ec76101cdf4c4ec7d08840c5541d2522028ce7f79602ee2c6d` |
| `linearsystems_lsk389_models.pdf` | Linear Systems' LSK389 A / B / C / D SPICE models (12/10/2020, 'based on B Device 5 measured on 12/09/2020'), 1 p; the Cloudlifter CL-1's JFETs (CHAINS_PLAN.md WP27) | web: https://www.linearsystems.com/_files/ugd/7e8069_9af1b6d022d14a17931a81b775eb9ed0.pdf | `abddd704c1ee6ad35a5603af0f2bd5e5b91d60f4f451b0da0c919a9d9645fd0d` |
| `central_spice/2N5087.LIB` | Central SPICE model, 2N5087 PNP (Rev F Q6, Q7), 8/18/10 | web: https://central.aeminc.com/docs/ENGINEERING/CSM/2N5087.LIB | `d8bc7b1771d656a0971c894515b070459a28289930c44edd7c17603d579fab09` |
| `central_spice/2N5088.LIB` | Central SPICE model, 2N5088 NPN, 8/18/10 (not in either schematic; kept as the 2N3707 card's sibling) | web: https://central.aeminc.com/docs/ENGINEERING/CSM/2N5088.LIB | `b1c2a377017142e78dc7d2c3318c888617c82341055f91227471782ec4e6a7c0` |

The model URLs come from Central's model search (web:
https://my.centralsemi.com/content/engineering/spicemodels/index.php, a POST of
`type=norm&searchtext=PART` to `index.php?task=filterList`). The search has no model for
2N3391A, 2N5458, 2N2270, MPSU05, MPSU55, BC184 or 2N4250.

**Licence.** Every card's header reads: "Users may not directly or indirectly re-sell or
re-distribute this model. This model may not be modified, or altered without the consent
of Central Semiconductor, LLC." Keep them local (don't commit), and fit our own
parameters with these as a source, not as copies.

## The cards, verbatim (comment headers trimmed to the attribution lines)

```spice
* Item: 2N3819  Date: 6/25/24  Revision History: A  (Central Semiconductor, LLC.)
*SRC=2N3819;2N3819;JFETs N;Depl;35.0V 10.0mA 100ohms   Central Semi Central Semi
.MODEL 2N3819 NJF(
+ VTO=-2.5
+ BETA=1.7524E-3
+ LAMBDA=0.02
+ IS=10.000E-21
+ NR=9.9900
+ ALPHA=1.0000E-6
+ VK=1
+ CGD=7.0632E-12
+ CGS=3.5966E-12
+ M=.62182
+ PB=.39253
+ KF=1.0000E-18
+ BETATCE=-.5
+ VTOTC=-2.5000E-3)
```

```spice
* Item: 2N5457  Date: 11/8/22  Revision History: A  (Central Semiconductor, LLC.)
*DEVICE=2N5457,NJF
* 2N5457 NJF model
* updated using Model Editor release 17.4.0 on 10/18/22 at 15:19
* The Model Editor is a PSpice product.
.MODEL 2N5457 NJF
+ VTO=-1.4676
+ BETA=1.6275E-3
+ LAMBDA=883.30E-6
+ IS=783.14E-18
+ ISR=7.8314E-15
+ NR=2.6845
+ ALPHA=778.30E-9
+ VK=.1
+ RD=60.461
+ RS=60.461
+ CGD=782.34E-12
+ CGS=5.3953E-12
+ M=1.5000
+ PB=.3905
+ KF=1.0000E-18
+ BETATCE=-.5
+ VTOTC=-2.5000E-3
```

```spice
* Item: CMPFJ175  Date: 7/15/24  Revision History: A  (Central Semiconductor, LLC.)
*SRC=CMPFJ175;CMPFJ175;SpiceMod;Test;DUT
* JFETs P;Depl;30.0V 25.0mA 150ohms
.MODEL CMPFJ175 PJF( VTO=-3.00 BETA=5.00m LAMBDA=1.20m RD=21.0
+ RS=18.9 IS=6.58f PB=1.00 FC=.5 CGS=12.5p CGD=17.1p )
```

```spice
* Item: 2N3707  Date: 11/16/21  Revision History: A  (Central Semiconductor, LLC.)
*DEVICE=2N3707,NPN
* 2N3707 NPN model
* created using Model Editor release 17.4.0 on 11/16/21 at 10:14
* The Model Editor is a PSpice product.
.MODEL 2N3707 NPN
+ IS=38.116E-15
+ BF=285
+ VAF=100
+ IKF=.76234
+ ISE=38.128E-15
+ NE=1.9979
+ BR=10.364
+ VAR=100
+ IKR=1.5810
+ ISC=803.76E-15
+ NC=1.5928
+ NK=1.2265
+ RB=9.7439
+ RC=30
+ CJE=11.658E-12
+ VJE=1.2545
+ MJE=.46406
+ CJC=5.3208E-12
+ VJC=.42236
+ MJC=.29245
+ TF=457.31E-12
+ XTF=10.516
+ VTF=10.347
+ ITF=1.6816
+ TR=10.000E-9
```

```spice
* Item: 2N3053  Date: 10/22/19  Revision History: A  (Central Semiconductor, LLC.)
*SRC=sm_NPN;sm_NPN;SpiceMod;Test;DUT
* BJTs NPN;Si;40.0V 0.700A 100MHz
.MODEL sm_NPN NPN (IS=5.42e-017 NF=1.00 BF=205 VAF=114
+ IKF=0.425 ISE=1.64p NE=2.00 BR=4.00 NR=1.00
+ VAR=20.0 IKR=1.05 RE=0.102 RB=0.409 RC=40.9m
+ XTB=1.5 CJE=111p VJE=1.10 MJE=0.500 CJC=43.3p VJC=0.300
+ MJC=0.300 TF=1.49n TR=240n EG=1.12 )
```

```spice
* Item: 2N5087  Date: 8/18/10  Revision History: A  (Central Semiconductor, LLC.)
*SRC=2N5087;2N5087;BJTs PNP;Si;  50.0V  50.0mA  40MHz   CENTRALSEMI
.MODEL 2N5087  PNP (IS=2.45f NF=1.00 BF=1.135k VAF=139
+ IKF=21.2m ISE=380f NE=2.00 BR=4.00 NR=1.00
+ VAR=20.0 IKR=45.0m RE=106 RB=426 RC=42.6
+ XTB=1.5 CJE=9.65p VJE=1.10 MJE=0.500 CJC=11.8p VJC=0.300
+ MJC=0.300 TF=0.80n TR=182.6n EG=1.12 )
```

(`2N5088.LIB` is the 2N3707 card with BF=599.06 and RC=.23381.)

### Problems in the cards

- **2N5457: CGD = 782.34E-12 (782 pF)** is implausible for a TO-92 JFET (Ciss ~ 4.5-7 pF,
  Crss ~ 1.5-3 pF typical on 2N5457 sheets). It looks like a slipped exponent (7.8234 pF).
  Don't use it as printed. RD = RS = 60.461 Ω, IS / ISR / NR / ALPHA / VK are PSpice
  extensions (gate leakage and impact ionization). Of these ngspice's level-1 J reads IS
  and, depending on version, may ignore or reject the rest; check before emitting them.
- **2N3053: the card is named `sm_NPN`**, a generic "SpiceMod" fit (40 V, 0.7 A, 100 MHz),
  not a part-specific extraction.
- **2N3819: NR = 9.99, VK = 1** are fit artefacts (gate-diode emission and breakdown
  knee); only VTO, BETA, LAMBDA, CGS, CGD, M, PB matter for audio.
- **The 2N3707 and 2N5088 cards share every value but BF and RC**: a family template, so
  treat their junction constants as provisional.

### The JFET datasheet figures we have

Central 2N3819 (`central_2N3819.pdf`, R1 9 Jan 2014; TA = 25 °C). The text layer
interleaves the columns, so this is re-paired against the standard JEDEC 2N3819
registration; confirm on the page image:
- IGSS: 2.0 nA max (VGS 15 V); 2.0 µA max at 100 °C;
- IDSS: 2.0-20 mA (VDS 15 V);
- BVGSS: 25 V min (IG 1 µA);
- VGS(off): 8.0 V max (VDS 15 V, ID 2 nA);
- VGS: 0.5-7.5 V (VDS 15 V, ID 200 µA);
- gfs: 2.0-6.5 mS;
- |yos|: 50 µS max;
- Ciss: 8.0 pF max; Crss: 4.0 pF max (VDS 15 V, VGS 0, f 1 MHz).

onsemi's 2N5457 / 2N5458 sheet (2N5457/D Rev. 6, fetched by the user 2026-11-06; kept at
`data/schematics/urei_1176/2N5457-D.PDF`), its table at 25 C (min / typ / max):
- VGS(off) (VDS 15 V, ID 10 nA): 2N5457 -0.5 / - / -6.0 V, 2N5458 -1.0 / - / -7.0 V;
- VGS at VDS 15 V: 2N5457 typ -2.5 V at 100 uA, 2N5458 typ -3.5 V at 200 uA;
- IDSS (VDS 15 V): 2N5457 1.0 / 3.0 / 5.0 mA, 2N5458 2.0 / 6.0 / 9.0 mA;
- |Yfs| (VGS 0, 1 kHz): 2N5457 1000 / 3000 / 5000 umho, 2N5458 1500 / 4000 / 5500;
- |Yos| typ 10, max 50 umho; Ciss typ 4.5, max 7.0 pF; Crss typ 1.5, max 3.0 pF;
- IGSS max -1.0 nA at VGS -15 V (-200 nA at 100 C).

Its Figures 2-3 (2N5457 only) are one unit's: VGS(off) ~-1.2 V, IDSS ~1.05 mA. Figure 3 is
digitized (`data/datasheets/onsemi_2n5457_transfer.csv`) and fitted as `2N5457@2` (VTO -1.25
V, BETA 0.69 mA/V^2, B 0.83; rms 2.5 uA). The typical part of the table (VGS(off) ~-3 V,
BETA ~0.33 mA/V^2 by the square law) lies past the 1176's Q-bias range.

## Still missing

- **The 1176's FET.** Rev F calls it "UREI 13-0027" (a selected house part). The Rev A
  label isn't legible. Repair practice uses 2N5457 / 2N5458 (data/schematics/urei_1176/
  README.md, open questions). `2N5457@1` (2026-11-06) is the Central card's DC values
  with CGD 2 pF (provisional) and plays Q1 and Q4 in `urei_1176`. Its beta makes the
  1176's ratios several times their legend (DEVICE_CANDIDATES.md, B12's status).
  `2N5457@2` is onsemi's Figure 3 unit (above), half as steep.
- **Datasheets (onsemi's site refuses scripted downloads; the user can fetch them):**

  (2n5457-d.pdf: fetched, above.)

  ```
  https://www.onsemi.com/download/data-sheet/pdf/mmbf5457-d.pdf
  ```

  ```
  https://www.onsemi.com/download/data-sheet/pdf/j175-d.pdf
  ```

  ```
  https://www.onsemi.com/download/data-sheet/pdf/2n5087-d.pdf
  ```

  (The last two URLs follow onsemi's pattern but weren't confirmed.)
- **2N3391A** (1176 Rev F Q2-Q4): datasheet and model. Central lists the part as end of
  life and has no model.
- **MPSU05 / MPSU55** (Rev F output pair): obsolete Motorola parts; no model or sheet
  found.
- **BC184** (SSL TR3) and **LM394H** (SSL TR1 / TR2, the bus amp's supermatch pairs): not
  fetched. The bus amp is outside the compressor and may not need modelling.
- **The 1176 Rev F's Q5 "5117"** and the SSL's diode types: not identified.
- **Siliconix AN104, "SPICE parameters"** (measured JFET parameters), cited at
  https://www.technicalaudio.com/pdf/Siliconix/Siliconix_AN104_spice_parameters.pdf:
  that URL returns 404 now.

## The Rhodes 100 W power amp's transistors (added 2026-11-07)

For `config/circuits/rhodes_amp*.yaml` (docs/RHODES_PLAN.md "The Suitcase"). None has a
published SPICE card (Central has no 2N5784 / 2N5781 / 2N6254 / RCA29B / RCA30B model), so
`varimu.devices.library` fits each to the sheet's typical curve and limits and marks the rest
provisional.

| File | What | Source | sha256 |
|---|---|---|---|
| `rca_1981_2N5781-2N5786.pdf` | RCA Power Devices 1981 p. 160-162 (3 pp): 2N5781 (PNP) / 2N5784 (NPN), Fig. 8-9 dc beta | web: https://ftp.mirrorservice.org/sites/www.bitsavers.org/components/rca/_dataBooks/1981_RCA_Power_Devices.pdf | `aa6f163e915d1429e159161e8ead8d6af2da3d61af54f64b58c7606f43606d86` |
| `rca_1981_2N6254_pages.pdf` | the same book's 2N3055 (Hometaxial) / 2N6253 / 2N6254 / 2N6371 pages (5 pp, p. 80-84) | same | `f70ef92ef05d6b1bc85db8f9330c75eb9373d5d53dda28bb4b62ef351372a823` |
| `central_2N5781_2N5784.pdf` | Central's R1 sheet of the same pair (agrees with RCA's limits) | web: https://my.centralsemi.com/datasheets/2N5781.PDF | `05d239076cbb45f20d55b79f3f706964cac1ec926e2008df0130aea74666fe93` |
| `comset_2N6253_6254.pdf` | Comset's 2N6253 / 2N6254 / 2N6371 sheet (agrees with RCA's limits) | web: https://datasheetq.com/pdf-view/2N6253-Comset.pdf | `8bb42190b5ef7893873dd7c8e341709d63144a5bc5cda62c0468a625849984aa` |

RCA29B / RCA30B (the drivers): the RCA sheet wasn't retrievable (datasheetspdf.com refused
downloads; the 1981 databook doesn't list them). Reseller listing only: web:
https://www.littlediode.com/components/RCA29B.html (80 V, 3 A, hFE 15-150 at 1 A / VCE 4 V,
fT 3 MHz min); RCA30 = the PNP complement (datasheetspdf.com's index). Their model is
provisional. A 1966-69 RCA Transistor Manual (worldradiohistory.com, > 10 MB) would have the
RCA29 / RCA30 sheet, if someone wants to fetch it.
## uA726 (the Minimoog's expo converters, 2026-11-07)

- `fairchild_ua726_1979.pdf`: Fairchild's uA726 Temperature-Controlled Differential Pair, pp. 7-33 to
  7-35 of the 1979 Fairchild Linear Op Amp Data Book (extracted from bitsavers' scan:
  https://www.mirrorservice.org/sites/www.bitsavers.org/components/fairchild/_dataBooks/1979_Fairchild_Linear_Op-Amp_Data_Book.pdf,
  PDF pages 342-344). Its current gain curve is digitized in `../fairchild_ua726_hfe.csv`
  (`../fairchild_ua726.provenance.yaml`); `UA726@1` is fitted to it (`library.fit_ua726`). No SPICE
  card or saturation current is published; the heater regulator (Q3-Q8) is drawn but not modelled.
