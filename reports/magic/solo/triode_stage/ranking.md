# triode_stage: parts by solo level (Dry Guitar.wav, 2 s)

| # | part | value | solo (dB re out) | check | source |
|---|---|---|---|---|---|
| 1 | RP | 1e+05 | -11.9 | -73 | provisional: model knowledge (12AX7 plate load, 100k) |
| 2 | RG | 1e+06 | -16.6 | -71 | provisional: model knowledge (12AX7 grid leak, 0.5-1 MOhm) |
| 3 | RL | 4.7e+05 | -17.3 | -72 | provisional: model knowledge (the next stage's grid leak) |
| 4 | RK | 1.5e+03 | -19.6 | -79 | provisional: model knowledge (12AX7 self-bias with a 100k plate load, 1.5k) |
| 5 | RS | 1e+04 | -20.0 | -79 | provisional: model knowledge (a source impedance that lets the grid-current peaks show) |
| 6 | CI | 1e-07 | -21.3 | -69 | provisional: model knowledge (coupling capacitor: 1.6 Hz with the grid leak) |
| 7 | CO | 1e-07 | -21.8 | -75 | provisional: model knowledge (output coupling capacitor) |
| 8 | CK | 2.2e-05 | -30.3 | -69 | provisional: model knowledge (cathode bypass, a few Hz) |
