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
