# Op-amp datasheets (ROOM_LOOP_PLAN.md R4: the clean chain)

The op-amp macro model (`varimu/circuit/parts.py` `opamp`) takes a datasheet's typical
figures. Read 2026-11-04 from TI's current sheets (the PDFs aren't kept here):

## NE5534A (the clean preamp's gain stage)

web: https://www.ti.com/lit/ds/symlink/ne5534.pdf (SLOS070D), "Electrical
Characteristics", VCC = +-15 V, 25 C, typical:

| Figure | Value |
|---|---|
| AVD, large-signal differential voltage amplification (RL >= 600 ohm, VO +-10 V) | 100 V/mV |
| B1, unity-gain bandwidth (CC = 22 pF, CL = 100 pF) | 10 MHz |
| ri, input resistance | 100 kohm |
| zo, output impedance (AVD = 30 dB, RL = 600 ohm) | 0.3 ohm |
| VO(PP), maximum peak-to-peak output swing (RL >= 600 ohm, +-15 V) | 26 V |
| Vn, equivalent input noise voltage at 1 kHz (NE5534A) | 3.5 nV/rtHz |
| SR, slew rate | 13 V/us |

## TL071 (the small omni's impedance converter)

web: https://www.ti.com/lit/ds/symlink/tl071.pdf, "Electrical Characteristics (DC) / (AC)
for TL07xC, TL07xAC, TL07xBC, TL07xI, TL07xM", VS = +-15 V, 25 C, typical:

| Figure | Value |
|---|---|
| AOL, open-loop voltage gain | 200 V/mV |
| GBW (all NS and PS packages; all TL07xM) | 3 MHz (5.25 MHz all other devices) |
| RID, input resistance | 1 Tohm |
| VOM, maximum peak output swing (RL = 10 kohm) | +-13.5 V |
| eN at 1 kHz (PS / NS packages, TL07xM) | 18 nV/rtHz (37 all other devices) |
| SR | 20 V/us |
| IB | 65 pA |

## uPC4570 (the Tascam 424's mic input, docs/CHAINS_PLAN.md WP4)

web: https://www.renesas.com/en/document/dst/upc4570-datasheet (R03DS0135EJ0200 Rev.2.00,
Feb.27.25; 655,374 bytes, sha256
`5478508c87f9b97a939fc4ea7829ffe648dccf603a09ec1320db458eb7f2cb56`), "Electrical
Characteristics", V+- = +-15 V, 25 C, typical (minimum):

| Figure | Value |
|---|---|
| AV, large signal voltage gain (RL >= 2 kohm, VO = +-10 V) | 300000 (30000) |
| GBW, gain bandwidth product (fO = 100 kHz) | 15 MHz (10) |
| funity, unity gain frequency, open loop | 7 MHz |
| Vom, output voltage swing (RL >= 10 kohm) | +-13.4 V (+-12) |
| Vom (RL >= 2 kohm) | +-12.8 V (+-10) |
| SR, slew rate | 7 V/us (5) |
| en at 1 kHz, RS = 100 ohm | 4.5 nV/rtHz |
| in at 1 kHz | 0.7 pA/rtHz |
| IB | 100 nA (PNP input: out of the IC) |

## MC1458 (the Rhodes Suitcase's preamp, docs/RHODES_PLAN.md "The Suitcase")

web: https://www.ti.com/lit/ds/symlink/mc1458.pdf (SLOS069C, revised August 2010; kept here as
`ti_mc1458.pdf`, 1,226,247 bytes, sha256
`84827ff7b0210b43b4c7337ec92badf96565a63d08be9603a4bed8e0e0da1fb1`, read with PyMuPDF), "electrical characteristics", VCC+- = +-15 V, 25 C, typical
(minimum) for the MC1458; each half "electrically similar to the uA741":

| Figure | Value |
|---|---|
| AVD, large-signal differential voltage amplification (RL >= 2 kohm, VO = +-10 V) | 200 V/mV (20) |
| B1, unity-gain bandwidth | 1 MHz |
| ri, input resistance | 2 Mohm (0.3) |
| ro, output resistance (VO = 0; above a few hundred Hz) | 75 ohm |
| VOM, maximum peak output swing (RL = 10 kohm) | +-14 V (+-12) |
| VOM (RL = 2 kohm) | +-13 V (+-10) |
| SR, slew rate at unity gain (RL = 2 kohm, CL = 100 pF) | 0.5 V/us |
| Vn, equivalent input noise (closed loop, AVD 100, RS 0, 1 kHz) | 45 nV/rtHz |
| IIB, input bias current | 80 nA (500 max.) |
| IOS, short-circuit output current | +-25 mA (+-40 max.) |
