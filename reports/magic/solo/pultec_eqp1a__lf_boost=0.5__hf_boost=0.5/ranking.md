# pultec_eqp1a: parts by solo level (Dry Guitar.wav, 5 s)

| # | part | value | solo (dB re out) | check | source |
|---|---|---|---|---|---|
| 1 | RIN_TERM | 620 | -5.7 | -81 | dwg: 620 across the HS-56 secondary |
| 2 | Rsrc | 600 | -6.7 | -82 | man: input impedance 600 ohms, matching (p.4) |
| 3 | RK1 | 820 | -7.3 | -69 | dwg: 820 between the cathodes (pins 3, 8) |
| 4 | RLB | 1e+03 | -7.5 | -85 | man: low boost control A-B JA-1031, 10,000 ohm audio taper (p.5) |
| 5 | RHBb | 5e+03 | -7.7 | -84 | man: high boost control A-B JU-1031, 10,000 ohm linear (p.5) |
| 6 | RHBa | 5e+03 | -7.7 | -84 | man: high boost control A-B JU-1031, 10,000 ohm linear (p.5) |
| 7 | RHAb | 1e+03 | -8.4 | -101 | man: high attenuate control A-B JU-1021, 1000 ohm linear (p.5) |
| 8 | RFBB | 360 | -13.3 | -104 | dwg: 360, each cathode to an end of the output transformer's feedback winding |
| 9 | RFBA | 360 | -13.7 | -99 | dwg: 360, each cathode to an end of the output transformer's feedback winding |
| 10 | CLB330 | 3.3e-07 | -19.4 | -90 | dwg-interp: redraw 330nF, wired to the switch's common (in on every position; 100 cps a... |
| 11 | Rload | 600 | -21.5 | -70 | man: output feeds a 600 ohm load (p.4) |
| 12 | RSHUNT | 1e+04 | -22.4 | -72 | redraw: 10k from the output to the LF-boost node; Barrera's netlist: 10k (the EQP-1R's ... |
| 13 | CLB60 | 2.2e-07 | -22.9 | -97 |  |
| 14 | RT1_s | 55 | -27.5 | -123 |  |
| 15 | RT1_p | 54.6 | -27.5 | -124 |  |
| 16 | RLA_SER | 1e+03 | -27.7 | -110 | redraw: 1k from the LF atten network to the output (HS-29 pin 4); Barrera's netlist: 1k |
| 17 | RBIAS_B | 6.2e+04 | -31.7 | -78 | dwg: 62K from the grid divider to ground |
| 18 | RBIAS_T | 4.7e+05 | -32.4 | -87 | dwg: 470K from +250 V to the grid divider (+31 V) |
| 19 | RT3_sa | 12 | -34.7 | -141 |  |
| 20 | RT3_sb | 12 | -34.7 | -140 |  |
| 21 | RK2B | 4.7e+03 | -35.3 | -85 | dwg: 4700 1W from each cathode to ground (* resistors selected alike) |
| 22 | RK2A | 4.7e+03 | -35.3 | -84 | dwg: 4700 1W from each cathode to ground (* resistors selected alike) |
| 23 | CHB82 | 8.2e-09 | -35.5 | -86 |  |
| 24 | RPL1B | 2e+05 | -38.0 | -72 | dwg: 200K 1W plate loads |
| 25 | RPL1A | 2e+05 | -38.6 | -72 | dwg: 200K 1W plate loads |
| 26 | RT1_gap | 126 | -39.0 | -69 |  |
| 27 | RFBR | 1e+03 | -40.2 | -106 | dwg: 1000 from the feedback winding's tap S to ground (+1.1 V) |
| 28 | RT2_gap | 126 | -41.3 | -69 |  |
| 29 | RT3_gap | 62.8 | -43.5 | -68 |  |
| 30 | RPSU4 | 4.7e+04 | -44.9 | -95 | dwg: 47K from +325 V to the 12AX7 plate loads (+250 V) |
| 31 | CZIN | 2.7e-10 | -45.2 | -96 | dwg: .00027 (uF) |
| 32 | RT2_p | 1.96e+03 | -49.4 | -120 |  |
| 33 | RPSU3 | 2.2e+03 | -51.3 | -129 | dwg: 2200 1W from +325 V to the output transformer's centre tap (+290 V) |
| 34 | RG2B | 1e+06 | -53.7 | -69 | dwg: 1M grid resistors, from the grids to the 470K / 62K divider |
| 35 | RT1_core | 736 | -54.4 | -69 |  |
| 36 | RG2A | 1e+06 | -54.6 | -69 | dwg: 1M grid resistors, from the grids to the 470K / 62K divider |
| 37 | CK2B | 5e-05 | -55.7 | -68 | dwg: 50/50 V across each 4700 |
| 38 | CK2A | 5e-05 | -55.9 | -68 | dwg: 50/50 V across each 4700 |
| 39 | CT2_sb | 3e-10 | -55.9 | -111 |  |
| 40 | CT2_sa | 3e-10 | -56.5 | -112 |  |
| 41 | RT2_core | 736 | -56.7 | -69 |  |
| 42 | RBW | 1.25e+03 | -57.2 | -98 | man: bandwidth control A-B JU-2521, 2500 ohm linear (p.5) |
| 43 | CPSU4 | 4e-05 | -57.5 | -79 | dwg: 40/450 V at +345, +325, +290 and +250 V |
| 44 | RT3_fb | 2 | -58.4 | -120 |  |
| 45 | RT3_fa | 2 | -58.8 | -125 |  |
| 46 | RT2_sb | 2.27e+03 | -59.9 | -116 |  |
| 47 | LT1_s_lk | 0.001 | -61.8 | -119 |  |
| 48 | LT1_p_lk | 0.001 | -61.8 | -119 |  |
| 49 | RT2_sa | 1.65e+03 | -62.8 | -115 |  |
| 50 | CC2B | 2.5e-07 | -62.9 | -77 | dwg: .25 coupling capacitors |
| 51 | CC2A | 2.5e-07 | -62.9 | -77 | dwg: .25 coupling capacitors |
| 52 | LHB33 | 0.033 | -63.2 | -99 |  |
| 53 | LT3_sa_lk | 0.000375 | -64.4 | -112 |  |
| 54 | LT3_sb_lk | 0.000375 | -64.4 | -111 |  |
| 55 | RT3_core | 711 | -64.6 | -69 |  |
| 56 | RZIN | 4.3e+04 | -64.8 | -94 | dwg: 43K in series with .00027 across the HS-29 secondary |
| 57 | CT3_eddy | 1.7e-06 | -65.9 | -110 |  |
| 58 | RPSU1 | 470 | -67.5 | -96 | dwg: 470 2W from the 6X4 cathode (+355 V) to +345 V |
| 59 | RT3_pb | 150 | -67.6 | -114 |  |
| 60 | RT3_pa | 150 | -68.2 | -113 |  |
| 61 | RPSU2 | 1e+03 | -68.7 | -110 | dwg: 1000 1W from +345 V to +325 V |
| 62 | CPP1 | 2e-11 | -74.3 | -106 | dwg: .00002 (uF) from plate to plate |
| 63 | LT2_p_lk | 0.01 | -74.8 | -95 |  |
| 64 | CZOUT | 3e-09 | -75.8 | -97 | dwg: .003 (uF) |
| 65 | CT1_eddy | 7.58e-08 | -82.5 | -97 |  |
| 66 | CT2_eddy | 7.58e-08 | -84.8 | -99 |  |
| 67 | RPCCA | 100 | -86.3 | -97 | provisional: model knowledge (HV winding resistance per half of a 25 W mains transformer) |
| 68 | RHTR_T | 2.7e+05 | -86.5 | -72 | dwg: 270K from +325 V to the heaters' tap (+60 V) |
| 69 | LT2_sa_lk | 0.01 | -86.8 | -89 |  |
| 70 | LT2_sb_lk | 0.01 | -86.8 | -92 |  |
| 71 | RPCCB | 100 | -87.6 | -96 | provisional: model knowledge (HV winding resistance per half of a 25 W mains transformer) |
| 72 | CT1_p | 1e-10 | -89.4 | -91 |  |
| 73 | CT1_s | 1e-10 | -89.4 | -94 |  |
| 74 | LT3_pb_lk | 0.0075 | -92.4 | -82 |  |
| 75 | CT3_pb | 1.5e-10 | -92.6 | -89 |  |
| 76 | CT3_pa | 1.5e-10 | -92.6 | -85 |  |
| 77 | LT3_pa_lk | 0.0075 | -92.6 | -86 |  |
| 78 | RLHB33 | 15.5 | -95.3 | -90 |  |
| 79 | CPSU2 | 4e-05 | -95.9 | -89 | dwg: 40/450 V at +345, +325, +290 and +250 V |
| 80 | CPSU1 | 4e-05 | -97.3 | -82 | dwg: 40/450 V at +345, +325, +290 and +250 V |
| 81 | RHTR_B | 6.2e+04 | -99.3 | -88 | dwg: 62K from the heaters' tap to ground |
| 82 | CPSU3 | 4e-05 | -99.4 | -77 | dwg: 40/450 V at +345, +325, +290 and +250 V |
| 83 | LT3_fb_lk | 1.52e-05 | -100.4 | -79 |  |
| 84 | LT3_fa_lk | 1.52e-05 | -100.6 | -79 |  |
| 85 | RZOUT | 620 | -101.6 | -78 | dwg: 620 in series with .003 across the output |
| 86 | RHAa | 0.001 | -128.2 | -31 | man: high attenuate control A-B JU-1021, 1000 ohm linear (p.5) |
| 87 | RLA | 0.001 | -144.4 | -11 **flag** | man: low attenuate control A-B JA-1041, 100,000 ohm audio taper (p.5) |
| 88 | LPCCA | 0.005 | -149.5 | -39 | provisional: model knowledge (leakage per HV half) |
| 89 | LPCCB | 0.005 | -149.7 | -37 | provisional: model knowledge (leakage per HV half) |
| 90 | CLA60 | 8.2e-09 | -159.0 | -2 **flag** |  |
| 91 | RHA75 | 75 | -162.7 | -0 **flag** | redraw: 75 from the HF atten wiper to its capacitors (Barrera's netlist: 75 too) |
| 92 | CHTR | 3e-07 | -167.5 | -23 **flag** | dwg: .3 across the 62K |
| 93 | CLA12 | 1.2e-08 | -167.9 | 10 **flag** | dwg-interp: redraw 12nF, wired to the switch's common (in on every position; 100 cps al... |
| 94 | CHA68 | 6.8e-08 | -172.1 | -2 **flag** | redraw: 68nF from the 75 ohm to the LF-boost node, in on every position |
| 95 | CHA10K | 6.8e-08 | -172.1 | -2 **flag** |  |
| 96 | CPCCB | 3e-10 | -182.5 | -4 **flag** | provisional: model knowledge (self-capacitance per HV half; a capacitance on every rect... |
| 97 | CPCCA | 3e-10 | -183.5 | -6 **flag** | provisional: model knowledge (self-capacitance per HV half; a capacitance on every rect... |
