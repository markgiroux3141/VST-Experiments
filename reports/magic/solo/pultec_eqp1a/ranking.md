# pultec_eqp1a: parts by solo level (Dry Guitar.wav, 5 s)

| # | part | value | solo (dB re out) | check | source |
|---|---|---|---|---|---|
| 1 | RHBb | 1e+04 | -1.0 | -71 | man: high boost control A-B JU-1031, 10,000 ohm linear (p.5) |
| 2 | RHAb | 1e+03 | -1.5 | -101 | man: high attenuate control A-B JU-1021, 1000 ohm linear (p.5) |
| 3 | RIN_TERM | 620 | -5.7 | -81 | dwg: 620 across the HS-56 secondary |
| 4 | Rsrc | 600 | -6.7 | -82 | man: input impedance 600 ohms, matching (p.4) |
| 5 | RK1 | 820 | -7.3 | -69 | dwg: 820 between the cathodes (pins 3, 8) |
| 6 | RFBB | 360 | -13.4 | -118 | dwg: 360, each cathode to an end of the output transformer's feedback winding |
| 7 | RFBA | 360 | -13.6 | -115 | dwg: 360, each cathode to an end of the output transformer's feedback winding |
| 8 | RSHUNT | 1e+04 | -15.9 | -72 | redraw: 10k from the output to the LF-boost node; Barrera's netlist: 10k (the EQP-1R's ... |
| 9 | RLA_SER | 1e+03 | -21.5 | -111 | redraw: 1k from the LF atten network to the output (HS-29 pin 4); Barrera's netlist: 1k |
| 10 | Rload | 600 | -21.5 | -70 | man: output feeds a 600 ohm load (p.4) |
| 11 | RT1_s | 55 | -27.4 | -123 |  |
| 12 | RT1_p | 54.6 | -27.5 | -124 |  |
| 13 | RBIAS_B | 6.2e+04 | -31.7 | -78 | dwg: 62K from the grid divider to ground |
| 14 | RBIAS_T | 4.7e+05 | -32.5 | -87 | dwg: 470K from +250 V to the grid divider (+31 V) |
| 15 | RT3_sb | 12 | -34.7 | -136 |  |
| 16 | RT3_sa | 12 | -34.7 | -135 |  |
| 17 | RK2B | 4.7e+03 | -35.3 | -84 | dwg: 4700 1W from each cathode to ground (* resistors selected alike) |
| 18 | RK2A | 4.7e+03 | -35.4 | -84 | dwg: 4700 1W from each cathode to ground (* resistors selected alike) |
| 19 | RPL1B | 2e+05 | -38.2 | -72 | dwg: 200K 1W plate loads |
| 20 | RPL1A | 2e+05 | -38.5 | -73 | dwg: 200K 1W plate loads |
| 21 | RT1_gap | 126 | -39.2 | -69 |  |
| 22 | RFBR | 1e+03 | -40.2 | -107 | dwg: 1000 from the feedback winding's tap S to ground (+1.1 V) |
| 23 | RT2_gap | 126 | -43.0 | -69 |  |
| 24 | RT3_gap | 62.8 | -43.7 | -68 |  |
| 25 | CZIN | 2.7e-10 | -43.8 | -93 | dwg: .00027 (uF) |
| 26 | RPSU4 | 4.7e+04 | -44.9 | -96 | dwg: 47K from +325 V to the 12AX7 plate loads (+250 V) |
| 27 | RT2_p | 1.96e+03 | -47.3 | -119 |  |
| 28 | RPSU3 | 2.2e+03 | -51.3 | -124 | dwg: 2200 1W from +325 V to the output transformer's centre tap (+290 V) |
| 29 | RG2B | 1e+06 | -53.4 | -69 | dwg: 1M grid resistors, from the grids to the 470K / 62K divider |
| 30 | RG2A | 1e+06 | -53.8 | -69 | dwg: 1M grid resistors, from the grids to the 470K / 62K divider |
| 31 | CT2_sb | 3e-10 | -54.5 | -110 |  |
| 32 | RT1_core | 736 | -54.5 | -69 |  |
| 33 | CT2_sa | 3e-10 | -55.1 | -109 |  |
| 34 | CK2B | 5e-05 | -55.7 | -66 | dwg: 50/50 V across each 4700 |
| 35 | CK2A | 5e-05 | -55.8 | -66 | dwg: 50/50 V across each 4700 |
| 36 | CPSU4 | 4e-05 | -57.7 | -79 | dwg: 40/450 V at +345, +325, +290 and +250 V |
| 37 | RT2_sb | 2.27e+03 | -57.8 | -120 |  |
| 38 | RT2_core | 736 | -58.4 | -69 |  |
| 39 | RT3_fb | 2 | -58.5 | -120 |  |
| 40 | RT3_fa | 2 | -58.7 | -117 |  |
| 41 | LT1_s_lk | 0.001 | -59.6 | -119 |  |
| 42 | LT1_p_lk | 0.001 | -59.6 | -112 |  |
| 43 | CC2B | 2.5e-07 | -60.0 | -79 | dwg: .25 coupling capacitors |
| 44 | CC2A | 2.5e-07 | -60.0 | -79 | dwg: .25 coupling capacitors |
| 45 | RT2_sa | 1.65e+03 | -60.6 | -113 |  |
| 46 | RZIN | 4.3e+04 | -61.0 | -94 | dwg: 43K in series with .00027 across the HS-29 secondary |
| 47 | LT3_sb_lk | 0.000375 | -62.2 | -111 |  |
| 48 | LT3_sa_lk | 0.000375 | -62.2 | -107 |  |
| 49 | RT3_core | 711 | -64.7 | -69 |  |
| 50 | CT3_eddy | 1.7e-06 | -66.0 | -103 |  |
| 51 | RPSU1 | 470 | -67.7 | -96 | dwg: 470 2W from the 6X4 cathode (+355 V) to +345 V |
| 52 | RT3_pb | 150 | -67.8 | -109 |  |
| 53 | RT3_pa | 150 | -68.1 | -104 |  |
| 54 | RPSU2 | 1e+03 | -69.0 | -110 | dwg: 1000 1W from +345 V to +325 V |
| 55 | LT2_p_lk | 0.01 | -70.9 | -93 |  |
| 56 | CPP1 | 2e-11 | -72.1 | -95 | dwg: .00002 (uF) from plate to plate |
| 57 | CZOUT | 3e-09 | -73.6 | -95 | dwg: .003 (uF) |
| 58 | CT1_eddy | 7.58e-08 | -82.5 | -91 |  |
| 59 | LT2_sa_lk | 0.01 | -82.9 | -92 |  |
| 60 | LT2_sb_lk | 0.01 | -83.0 | -92 |  |
| 61 | CT2_eddy | 7.58e-08 | -86.3 | -94 |  |
| 62 | RPCCA | 100 | -86.6 | -94 | provisional: model knowledge (HV winding resistance per half of a 25 W mains transformer) |
| 63 | RHTR_T | 2.7e+05 | -86.8 | -72 | dwg: 270K from +325 V to the heaters' tap (+60 V) |
| 64 | CT1_p | 1e-10 | -87.2 | -86 |  |
| 65 | CT1_s | 1e-10 | -87.2 | -74 |  |
| 66 | RPCCB | 100 | -87.8 | -93 | provisional: model knowledge (HV winding resistance per half of a 25 W mains transformer) |
| 67 | LT3_pa_lk | 0.0075 | -90.4 | -84 |  |
| 68 | LT3_pb_lk | 0.0075 | -90.4 | -82 |  |
| 69 | CT3_pb | 1.5e-10 | -90.5 | -83 |  |
| 70 | CT3_pa | 1.5e-10 | -90.5 | -85 |  |
| 71 | CPSU2 | 4e-05 | -96.2 | -76 | dwg: 40/450 V at +345, +325, +290 and +250 V |
| 72 | RZOUT | 620 | -97.1 | -79 | dwg: 620 in series with .003 across the output |
| 73 | CPSU1 | 4e-05 | -97.6 | -80 | dwg: 40/450 V at +345, +325, +290 and +250 V |
| 74 | LT3_fb_lk | 1.52e-05 | -98.3 | -82 |  |
| 75 | LT3_fa_lk | 1.52e-05 | -98.3 | -70 |  |
| 76 | CPSU3 | 4e-05 | -99.4 | -75 | dwg: 40/450 V at +345, +325, +290 and +250 V |
| 77 | RHTR_B | 6.2e+04 | -99.5 | -81 | dwg: 62K from the heaters' tap to ground |
| 78 | RLB | 0.001 | -119.1 | -59 | man: low boost control A-B JA-1031, 10,000 ohm audio taper (p.5) |
| 79 | RHAa | 0.001 | -121.5 | -59 | man: high attenuate control A-B JU-1021, 1000 ohm linear (p.5) |
| 80 | RHBa | 0.001 | -141.8 | -18 **flag** | man: high boost control A-B JU-1031, 10,000 ohm linear (p.5) |
| 81 | RLA | 0.001 | -143.0 | -11 **flag** | man: low attenuate control A-B JA-1041, 100,000 ohm audio taper (p.5) |
| 82 | LPCCA | 0.005 | -149.8 | -31 | provisional: model knowledge (leakage per HV half) |
| 83 | LPCCB | 0.005 | -149.9 | -34 | provisional: model knowledge (leakage per HV half) |
| 84 | CHB82 | 8.2e-09 | -150.5 | -0 **flag** |  |
| 85 | CLA12 | 1.2e-08 | -154.9 | 2 **flag** | dwg-interp: redraw 12nF, wired to the switch's common (in on every position; 100 cps al... |
| 86 | RBW | 1.25e+03 | -166.4 | 3 **flag** | man: bandwidth control A-B JU-2521, 2500 ohm linear (p.5) |
| 87 | CHTR | 3e-07 | -167.8 | -16 **flag** | dwg: .3 across the 62K |
| 88 | CLA60 | 8.2e-09 | -171.5 | 11 **flag** |  |
| 89 | CLB60 | 2.2e-07 | -173.4 | -1 **flag** |  |
| 90 | CHA68 | 6.8e-08 | -175.5 | -1 **flag** | redraw: 68nF from the 75 ohm to the LF-boost node, in on every position |
| 91 | CHA10K | 6.8e-08 | -175.5 | -1 **flag** |  |
| 92 | CLB330 | 3.3e-07 | -177.4 | -0 **flag** | dwg-interp: redraw 330nF, wired to the switch's common (in on every position; 100 cps a... |
| 93 | RHA75 | 75 | -177.5 | 0 **flag** | redraw: 75 from the HF atten wiper to its capacitors (Barrera's netlist: 75 too) |
| 94 | CPCCB | 3e-10 | -180.5 | -2 **flag** | provisional: model knowledge (self-capacitance per HV half; a capacitance on every rect... |
| 95 | CPCCA | 3e-10 | -180.8 | -2 **flag** | provisional: model knowledge (self-capacitance per HV half; a capacitance on every rect... |
| 96 | RLHB33 | 15.5 | -183.9 | 0 **flag** |  |
| 97 | LHB33 | 0.033 | -185.1 | 0 **flag** |  |
