# Chain passes with noise (2026-11-14)

`uv run --extra fast --extra listen python scripts/chain_passes.py --noise` (production, about 14 min
with 12 workers; the U47 -> V76 ran at 11-19x real time per pass with noise, the omni chain at 1x).

This is the same experiment as `../production/` (see its README for the setup, staging and file
meanings), with B5's noise switched on in every pass:

- Johnson noise of every resistor, winding resistance and acoustic resistance in the capsules;
- the tubes' shot and flicker noise;
- mains wander where a circuit has a mains supply (the V76, the 610).

Each stem's pass has its own seed (`chain_passes.pass_seed`): a re-amp pass doesn't repeat the last
pass's hiss. H is measured without noise.

Not covered: the BJTs, JFETs and op-amp macros have no noise model. The API 312 (a 2520 from BJTs)
and the clean pre's NE5534 / TL071 macros therefore carry only their resistors' noise, and are
quieter than real ones.

## Noise in one pass (dB re the signal, 20 Hz-20 kHz, at 100 dB SPL; carbon at 90)

`noise_vs_clean`: the noisy p1 minus the noiseless one, with the same input.

| chain | bass | guitar | harmonies | lead vocal |
| --- | --- | --- | --- | --- |
| U47 -> V76 | -69.5 | -71.2 | -69.9 | -70.8 |
| 44-BX -> 610 | -79.2 | -80.5 | -78.5 | -79.9 |
| SM57 -> API 312 | -73.5 | -75.6 | -74.6 | -75.5 |
| carbon -> clean | -74.2 | -76.4 | -82.6 | -79.6 |
| omni -> clean | -71.7 | -73.0 | -71.5 | -72.4 |

The U47's noise is mostly below 200 Hz: its 60 MOhm grid leak against the capsule's ~80 pF. Measured
alone, idle, B5 gives the U47 12.8 uV unweighted at its output, about 27 dB SPL equivalent; Neumann
gives a "Rauschgrenze" of 24 dB. The V76 alone is -127.5 dB re 0.775 V at the input, against its
acceptance limit of -120 dB.

## What noise does to the passes

The figures are the residual of `../production/README.md` ("Correction": the fitted "character" of the
first version was the fit's own floor), dB re signal.

- **For the tube chains, nothing measurable.** One pass's noise (-70 to -80 dB) is 25-35 dB under
  their distortion (-41 to -49), so their residuals move by at most 0.1 dB through pass 8.
- **The SM57 -> API 312 distorts least, so its noise shows.** On the harmonies its residual goes from
  -74.2 to -71.3 at pass 1 and from -67.3 to -62.3 at pass 4.
- **It compounds through a bright chain's EQ.** The omni control lifts 15 kHz by about 10 dB per pass.
  Its residual against the dry stem goes from -72 to -73 dB at pass 1 to -44 to -51 at pass 4 (noiseless:
  -69 to -78). Pass 4 alone adds -55 dB on the guitar, against -88 without noise. The first passes'
  hiss gets every later pass's treble boost. This is generation loss: it falls out of the physics,
  nothing was added for it. Pass 8 can't be predicted (+85 dB at 15 kHz is past the correction's
  limit), but it is audible.
- Listen to `<stem>/omni_clean/p8.wav` against `../production/<stem>/omni_clean/p8.wav`.
