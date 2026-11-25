# PB0: parts heard up close

docs/PART_NOISE_PLAN.md's bench: each part's noise alone, as the voltage at the part, boosted until
you can hear it (the video's experiment, simulated). Regenerate with
`uv run --extra listen --extra fast python scripts/part_noise_bench.py` (~25 s; WAVs are not
committed). 8 s each, 96 kHz mono float, band-limited to 20 Hz - 20 kHz. Every value and its source
is in `summary.json`.

## Two sets

- `audio/same_gain/<group>/`: one fixed gain per group, so you hear the **real relative levels**
  within the group (as in the video). Hiss: +50.6 dB. Quiet files really are quiet; turn up.
- `audio/matched/`: every file at -23 LUFS, so you hear the **character**, not the level.

## Listening order

| # | File | What to listen for | Level at the part (20 Hz-20 kHz) |
|---|---|---|---|
| 1 | `johnson_100k` | the reference: plain white hiss. Every 100k sounds like this, whatever it's made of | 5.5 uV, 0 dB |
| 2 | `metal_film_100k_100v` | a good resistor with 100 V on it: barely more than Johnson, a little low-end added | 11 uV, +6 dB |
| 3 | `carbon_comp_100k_100v` | a period carbon comp as a plate load: a darker, rumbling 1/f hiss, 30 dB above Johnson | 168 uV, +30 dB |
| 4 | `carbon_comp_100k_100v_aged` | the same aged (+10 dB noise index): louder, the same colour | 534 uV, +40 dB |
| 5 | `carbon_comp_follows_tone` | no DC, a 110 Hz current 1 s on / 1 s off, the tone removed: **the noise exists only while the signal flows** (the 1/f skirts around the tone) | 121 uV |
| 6 | `tube_12ax7_idle` | the 12AX7 at idle as B5 models it (grid-referred): already in the engine | 0.8 uV |
| 7 | `popcorn_one_trap` | one trap in a transistor: low ticking, a lopsided two-level flutter | 1.0 uV |
| 8 | `popcorn_defective` | three traps: fast crackle on top of slow pops | 1.3 uV |
| 9 | `barkhausen_slow_sweep` | a core swept slowly through its loop: crackle that thickens around the coercive field, sparse at the tips | level not sourced |
| 10 | `barkhausen_mains` | the same core at 50 Hz: a fizz bunched twice per cycle | level not sourced |
| 11 | `pot_new_leaky_cap` | a new 1M volume pot turned with 2.5 V DC on it (a leaky coupling cap): **silent**: a pot into a grid carries no current, so its contact noise does nothing | |
| 12 | `pot_worn_leaky_cap` | the same, worn track: clicks and scratches where the wiper rides on oxide and the grid holds, then jumps | |
| 13 | `pot_worn_tone` | the worn pot turned with a tone on it, no DC: dropouts and splats in the tone | |

## What it says so far

- Resistor material only matters where **DC flows**: a carbon comp plate load is ~30 dB above
  Johnson noise (40 aged), a metal film 6 dB. With no current, every resistor is just Johnson.
- Carbon comp's noise **follows the signal** (#5): a fixed noise bed can't do that.
- A scratchy pot needs a worn track **and** something that makes the contact matter: a gap in the
  contact (bad spots) or a current through the wiper. A leaky coupling cap makes the scratches
  far louder by putting DC on the track.
- Popcorn and the 12AX7 are microvolts: in a device they matter only at a high-gain input.

## Provisional (to replace)

The noise indices (Motchenbacher & Connelly's ranges, unchecked against the book), the aged +10 dB,
the popcorn traps' amplitudes and times, Barkhausen's kappa and drive scale (ABBM's form is the
model, its parameters aren't fitted), the pot track's roughness, bad spots and C_in, the leaky
cap's 2.5 V.
