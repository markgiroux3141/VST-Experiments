# AM14: interactions between mechanisms

2026-11-13, `scripts/mechanism_factorial.py` -> `<study>/summary.json`. Every combination of the
switches that exist (2^k renders), main effects and two-factor interactions as signals (dB re the
all-on output), and exact Shapley values of the character score (the power of what one fixed
filter can't explain in y[S] against y[none], re y[none]'s power). An interaction within 6 dB of
the smaller of its two main effects is flagged **not separable**. Listening candidates are the
flagged pairs above **-40 dB**, a screening level chosen here, not a threshold of hearing.

**Done-when met: three studies have tables; no flagged pair is above -40 dB**, so there are no
listening files (none were due).

## 5e3: `fender_5e3_mods`, Dry Guitar 8 s, `volume_bright` 0.7

| Factor (off -> on) | Main effect | after gain match | character | tone | Shapley (character) |
|---|---|---|---|---|---|
| sag (silicon -> 5Y3GT) | **-11.5 dB** | -19.4 | -20.3 | -23.0 | **0.0100** |
| noise (off -> seed 1) | -35.6 | -42.3 | -43.2 | -48.3 | 0.00045 |
| iron (linear -> JA) | -54.1 | -56.7 | -64.8 | -57.5 | ~0 |
| heaters (off -> on) | -63.2 | -64.8 | -65.6 | -70.6 | ~0 |

All on: character -19.8 dB re the all-off output; sag carries 96% of it.

| Interaction | Level | Flag |
|---|---|---|
| sag x noise | -43.1 | separable (7.5 dB under noise's main effect) |
| sag x iron | -56.6 | not separable |
| heaters x noise | -57.1 | not separable (6 dB *above* heaters' own main effect) |
| sag x heaters | -63.6 | not separable |
| iron x noise | -79.1 | separable |
| iron x heaters | -113.0 | separable |

## tape: the idealized machine (`print_audio`), drums 8 s, +6 dB drive

| Factor | Main effect | after gain match | character | tone | Shapley |
|---|---|---|---|---|---|
| transport (flutter off -> on) | -6.9 | -7.2 | -9.2 | -11.1 | 0.125 |
| grain (none -> seed 1) | -36.6 | -36.4 | -36.6 | -49.6 | 0.00017 |
| grain x transport | -43.1 | separable (6.5 dB under grain) | | | |

## 670: `fairchild_670`, drums 8 s

| Factor | Main effect | character | tone |
|---|---|---|---|
| iron (linear -> JA) | -43.9 | -48.5 | -46.5 |
| noise | -54.5 | -55.9 | -60.6 |
| iron x noise | -65.2, separable | | |

## Readings

- **On these devices, the mechanisms add.** No interaction that matters (above -40 dB) is
  flagged, so one-at-a-time ablations (EMERGENCE_RESEARCH.md 2) give the right answer here. The
  "magic is a product" hypothesis isn't supported at this level of these three devices.
- **The flagged pairs are all tiny and two of them are by construction:**
  - heaters x noise: the heaters' temperature follows the mains, and the mains only wander when
    the noise block is on (B5 / B6). With noise off the heaters sit at their rated temperature.
    So the heaters do almost nothing alone (-63 dB) and a little more with noise (-57).
  - sag x iron, sag x heaters: the rectifier moves the operating point, and with it what the
    cores and the cathode temperature do. They are below -56 dB.
- **Sag is the 5E3's big mechanism** at this volume, by an order of magnitude over everything
  else. Most of its -11.5 dB is level (the 5Y3GT's drop); after gain matching it is still -19 dB,
  mostly character (compression and the supply's ripple riding on the notes).
- **The 5E3's noise block is loud at volume 0.7: -36 dB re the output.** It is the mains wander
  and the flicker noise of the first stages, amplified by a cranked amp. (Not checked against a
  real 5E3's hum and noise figure here.)
- **The tape's "transport" effect is a time-base difference** (flutter moves every transient),
  so its sample-wise level (-7 dB) says nothing about audibility. AM2's dewarped null handles
  it. The grain on its own (-37 dB) agrees with AM7. Grain x transport (-43 dB) is physical: the
  grain is attached to the tape's position, which flutter moves.
- **The 670's iron is larger than its noise on drums** (-44 vs -55 dB) and they don't interact.

## Limits

One program and one setting per study. Only switches that exist were used (the doc's rule), so
"sag" means 5Y3GT vs silicon, not sag vs an ideal supply. The noise factor's main effect is
mostly the noise itself; the interactions with noise weren't corrected for a noise-only render
(the doc asks for that "where defined": none of these circuits has a noise-only build).
