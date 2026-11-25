# The 5F1 Champ aged, its carbon resistors' noise in the coupled simulation

docs/PART_NOISE_PLAN.md, the first device spike. Regenerate with
`uv run --extra listen --extra fast python scripts/champ_aged.py` (~3.5 min; WAVs not committed) and
the ranking with `... --rank new` / `--rank cap_job` (~2 min each).

Every render: production quality, the amp's own noise on (B5: Johnson, tube shot and flicker, the
mains' wander), the pressure 1 m in front of the speaker. The carbon comps' excess noise goes in as
current sources across each resistor, driven by I(t) x dR/R(t), with I from a first pass of the same
aged amp (two passes; the error is second order in dR/R). Aging: `varimu/part_noise/aging.py`
(drift, noise index, leaky coupling caps, dried electrolytics; every number provisional).

## The conditions

| | carbon comps | noise index | coupling caps leak | electrolytics |
|---|---|---|---|---|
| `new` | as drawn | by value (0 dB at 100k) | no | as drawn (ESR from tan d 0.1) |
| `played` (~1975) | +4% +-3% | +3 dB | 1 GOhm | C x0.9, ESR x2 |
| `cap_job` (today, original parts) | +12% +-6% | +8 dB | 20 MOhm | C x0.5, ESR x8 |
| `wreck` (damp basement) | +25% +-10% | +15 dB | 3 MOhm | C x0.2, ESR x30 |

## What to listen to

- `audio/playing/`: the dry guitar at VOLUME 0.5, loudness-matched (-23 LUFS): the four
  conditions, then `cap_job_x10` / `_x100` / `_x1000` (only the excess noise exaggerated).
- `audio/idle/`: nothing played, VOLUME 1.0, **one gain for all**: the amp's floor as it really
  rises with age (turn it up).
- `audio/excess_only/`: what the carbon comps add, alone (pass 2 - pass 1), one gain per program.

## What came out

| | idle at 1 m | of which 120 Hz hum | B+ ripple | 6V6 grid - cathode | playing level |
|---|---|---|---|---|---|
| new | 45.6 dB SPL | 45.4 | 4.4 V rms | -18.0 V | 96.0 dB SPL |
| played | 46.9 | 46.7 | 4.9 V | -18.2 V | 95.8 |
| cap_job | 53.6 | 53.1 | 9.1 V | -17.3 V | 90.8 |
| wreck | 66.4 | 66.0 | 25.2 V | -12.7 V | 73.2 |

- **Aging is mostly hum and lost gain, not hiss.** The dried filter caps (no choke on a 5F1) raise
  the 120 Hz ripple and the hum 21 dB from new to wreck. The leaky first coupling cap puts DC on
  V1B's grid, which conducts and clamps the volume wiper at +0.83 V: V1B loses gain (-5 dB playing
  at cap_job, -23 dB at the wreck, which barely works). The leaky second cap biases the 6V6 hotter
  (+5 V on its grid, 43 mA).
- **Realistic carbon-comp noise is inaudible playing**: 80+ dB under the guitar at every
  condition. Idle at full volume it is ~16 dB under the hum (29 dB SPL new). It *falls* in the
  older amps although their noise index is higher: the gain it would go through is gone.
- **Exaggerated, it is a bright hiss bed**: x10 adds 20 dB, exactly (linear: no intermodulation
  at these levels); x1000 sits 15 dB under the guitar, brighter than it (2-8 kHz), and follows the
  playing only ~1 dB (loudest quarter vs quietest; the guitar 15 dB): in the Champ the noisy
  resistors carry DC, so the signal barely modulates their noise. Faint harmonic lines in it are
  the part that does (`playing_cap_job_x1000.png`).
- **Two parts carry it** (`rank_new.json`): V1A's plate load RPLA (29 dB SPL alone) and its
  unbypassed cathode resistor RKA (-15 dB); everything else is 30+ dB lower. With leaky caps
  (`rank_cap_job.json`) the volume pot and the 6V6's grid leak wake up 20-30 dB but stay far
  below. In the engine the Champ needs excess noise on two parts, four with leaky caps.
