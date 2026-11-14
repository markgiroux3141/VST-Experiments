# AM7: noise that fuses (the measurements; the listening is yours)

2026-11-13, `scripts/fusing_noise_study.py` -> `summary.json`; stimuli in
`cache/magic/fusing/<carrier>/` (y0 and the four noises, 96 kHz).

Per carrier, 4 s at 0 VU (-18 dBFS rms) through the idealized tape machine (15 ips, Scotch 111,
flutter off in both): `y0` without grain, `y1` with grain seed 1. `n_phys = y1 - y0` is the tape
model's own noise with the time base held still; `n_stat` is stationary noise with n_phys's
spectrum and power; `n_env` / `n_band` are n_stat made to follow y0's envelope (broadband / per
ERB band).

## The first check: does the model's tape noise follow the signal? Yes.

| Carrier | Noise | Level re signal | Temporal coherence (cross) | Level-envelope slope (dB/dB) | Level corr |
|---|---|---|---|---|---|
| synth line | n_phys | -36.8 dB | **0.60** | 0.77 | 0.25 |
| | n_stat | -36.8 | 0.00 | -0.22 | -0.35 |
| | n_env | -36.8 | 0.74 | 0.88 | 0.78 |
| | n_band | -36.8 | 0.67 | 0.55 | 0.33 |
| bass line | n_phys | -36.4 | **0.40** | 1.44 | 0.51 |
| | n_stat | | 0.02 | -0.05 | -0.11 |
| | n_env | | 0.36 | 0.70 | 0.81 |
| | n_band | | 0.39 | 1.04 | 0.69 |
| voice | n_phys | -37.6 | **0.26** | 0.83 | 0.81 |
| | n_stat | | 0.00 | 0.01 | 0.04 |
| | n_env | | 0.42 | 1.03 | 0.99 |
| | n_band | | 0.34 | 0.85 | 0.97 |

- The tape model's grain is **signal-dependent noise**: its envelope follows the program as
  closely as the constructed followers do (coherence 0.26-0.60 against 0.00 for stationary
  noise; its level rises ~0.8-1.4 dB per dB of program). It is mostly modulation noise, not hiss.
- Its level is **-37 dB re the signal** at 0 VU on one generation (the noise floor alone, on
  silence, is ~73 dB down: TAPE_PLAN.md TM3). That is high enough that it is probably above the
  detection threshold on exposed material. The listening says how high it sits against that threshold.

## Listening (yours, ~20 minutes)

```sh
uv run --extra listen --with sounddevice python scripts/fusing_noise_listen.py --carriers synth bass
```

Task 1 is a staircase per noise kind (which of three is odd); Task 2 asks "which is noisier"
between stationary and following noise at equal power. The hypothesis: the following noises need
>= 3 dB more to be detected and are judged *less* noisy (heard as part of the tone instead).
Results go to `data/judgments/magic/fusing/`.
