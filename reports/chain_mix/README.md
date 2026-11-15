# The sample song through four chains, with and without noise and hum (2026-11-14)

`uv run --extra fast --extra listen python scripts/chain_mix.py` (production; about 10 min of renders;
cached in `cache/chain_passes/`, its calibrations in `cache/chain_mix/`). The question: does noise and
hum add anything **by ear** that the dB figures of `../chain_passes/` and `../chain_spike/` miss?

## The chains (all tube preamps: B5 models tube and resistor noise, not transistors or op-amps)

| stem | chain | at the mic | settings |
| --- | --- | --- | --- |
| bass | RCA 44-BX -> UA 610 ("upright bass" in its use note) | 100 dB SPL | 610 level 0.4 |
| acoustic guitar | AKG C12 -> UA 610 | 85 dB SPL | 610 level 0.4 |
| lead vocal | Neumann U47 -> Telefunken V76 | 95 dB SPL | V76 at 24 dB |
| harmonies | Neumann U67 -> EMI REDD.47 | 90 dB SPL | REDD.47 at 34 dB |

Two staging corrections an engineer would have made:
- **REDD.47 at 40 dB clipped its output** on the harmonies (residual -26 dB, peaks -4.4 dBFS); at 34 dB
  it reads -54.
- **The 610's first stage overloads on the C12 at 90 dB SPL** (residual -34 dB; the C12 alone reads -60,
  and the 610's Lo gain link doesn't help). The guitar is at 85 dB SPL, a little further back: -44.

Each pass is staged as in `../chain_passes/`: the input at that SPL, turned down where the response
predicts a higher peak than pass 1's.

## The two versions

- **clean**: no noise, no hum.
- **noisy**:
  - B5's noise: every resistor, winding and acoustic resistance, and the tubes' shot and flicker
    noise, with a seed per stem and pass. The simulated supplies' ripple and mains wander come with it.
  - Hum, calibrated as `../chain_spike/` calibrated the U47 -> V76: the preamp's input transformer
    picking up a stray mains field (50 / 150 / 250 Hz).
    - The 610 and the REDD.47: at -122.4 dB re 0.775 V at their input, the level the V76 landed at.
      Provisional for these two.
    - The V76: 26 uV in T85, the spike's.
  - Ripple on the tube mics' supplies (100 / 200 / 300 Hz): the U47 and the U67 at 3 uV at the mic's
    output. The C12 is capped at 0.5 V of supply ripple: its circuit rejects ripple so well that 3 uV
    would have needed ~40 V. All provisional.

## The mixes

Each processed stem goes back to its dry loudness. The gain is set by the clean version and applied
to both, so the noisy mix is the clean mix plus exactly the noise and hum, at their true level. Bass
and vocal are centre, guitar left, harmonies right. Each pass count's pair shares one gain (-20 LUFS).

| passes | noise + hum re the mix | re the quietest 5 % of the song (50 ms blocks) | absolute |
| --- | --- | --- | --- |
| 1 | -58.8 dB | -49.1 dB | -77.8 dBFS rms |
| 4 | -53.0 dB | -43.8 dB | -72.4 dBFS rms |
| 8 | -46.1 dB | -37.6 dB | -65.6 dBFS rms |

What it is (its power spectrum):

| passes | hum lines (50 Hz harmonics to 1 kHz) | below 200 Hz | 200 Hz-2 kHz | 2-8 kHz | above 8 kHz |
| --- | --- | --- | --- | --- | --- |
| 1 | 10 % | 64 % | 14 % | 6 % | 10 % |
| 4 | 7 % | 40 % | 18 % | 9 % | 31 % |
| 8 | 3 % | 12 % | 9 % | 4 % | **75 %** |

- After one pass the added sound is mostly low: the condensers' grid-leak noise and the hum.
- **By 8 passes it is treble hiss.** The chains lift the top a little every pass (the U47 -> V76 +2.7
  dB at 10 kHz), and the early passes' hiss gets every later lift. This is generation loss. The hum
  stays put and is swamped.
- Per stem, noisy minus clean: the guitar's is largest (-58.7 dB at pass 1, -44.8 at pass 8). It is
  the quietest source, into the most gain (46.5 dB). The bass's is smallest (-72 / -68).
- The noise and hum don't change the distortion: each stem's residual is the same within 0.3 dB with
  and without.

## Listening

The measure question is yours: can you hear it?

1. `mix_clean_p1.wav` against `mix_noisy_p1.wav`, then the same at p4 and p8 (a blind A/B is better:
   the pairs differ only by the noise and hum).
2. `added_pN.wav`: what was added, at its true level (very quiet). `added_pN_x30dB.wav`: the same
   +30 dB, to hear what it is.
3. `mix_dry.wav`: the stems unprocessed, the same balance.

The figures are `summary.json` (with each chain's calibration and every stem's residuals).
