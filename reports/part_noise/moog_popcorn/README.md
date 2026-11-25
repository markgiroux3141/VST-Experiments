# Popcorn noise in the Minimoog's transistors (offline prototype)

docs/PART_NOISE_PLAN.md: popcorn where it physically belongs, in a transistor synth. The bench's
`popcorn_defective` (three traps: 100 pA 30 / 60 ms, 40 pA 1 / 3 ms, 250 pA 0.4 / 1.5 s; provisional,
`varimu.part_noise.popcorn`) put into one transistor of the Minimoog voice at a time, as a current
from its base to its emitter, times DAMAGE. Regenerate with
`uv run --extra listen --extra fast python scripts/moog_popcorn.py [--only SITE ...] [--damage ...]`
(~1 min for four sites at four levels; WAVs not committed).

The voice at draft-1x as the app plays it (its partition), a held A2 (0.2-2.6 s) with EMPHASIS 0.75,
CUTOFF 0.35, AMOUNT 0.3. One pass: a trap's current doesn't depend on the circuit, so a control
input drives it (in the partition's first part, handed to the transistor's part a sample late; in
an oscillator's island, an audio control inside it).

## The sites

| site | transistor | what a trap does there |
|---|---|---|
| `ladder` | Q29, the ladder's input pair | steps into the filter, **rung by its resonance** |
| `vca` | Q16, the VCA's input pair | steps into the VCA |
| `sh` | Q23_b, the keyboard's sample and hold | its base current charges the hold capacitor: a held note's pitch drifts in ramps |
| `expo1` | Q7_o1, oscillator 1's exponential converter | its base current shifts Vbe: the pitch hops between levels |

## What to listen to

- `audio/ladder/damage_0.wav` (no trap) then `damage_1`, `_10`, `_100`, `_1000` (loudness-matched).
- `audio/pops_only/ladder_damage_1000.wav`: the pops alone: clicks at each trap step and the
  filter's resonant peak ringing as the contour sweeps it (`spectrograms.png`).
- `audio/expo1/damage_10000.wav` and `damage_100000.wav`: random pitch hops (a two-level "drunk"
  vibrato), the only way the exponential converter gets audible.
- `audio/vca/`, `audio/sh/` for completeness.

## What came out (`summary.json`)

- **The ladder is the place.** At DAMAGE 1000 the pops are ~5 dB under the note and clearly ring at
  the cutoff; the resonance turns each step into a ping.
- **The pitch sites need far more than a real defect.** The exponential converter's base is driven
  from a low impedance, so a trap's current barely moves its Vbe: within the oscillator's own ~1
  cent cycle-to-cycle jitter up to DAMAGE 1000, 16 cents peak (7.5 rms) at 10000, 1.6 semitones at
  100000 (no real transistor). The sample and hold drifts a held note by 1.3 cents at 1000, 17 cents
  at 100000.
- **A measuring caveat.** "Pass minus no trap" has a floor in this partitioned voice: any change
  shifts some event by a sample (a trap a millionth of DAMAGE 1 at the ladder still differs by
  -36.7 dB re the note), so the levels below ~-30 dB in `summary.json` are that floor, not the trap.
  The `pops_only` files are kept at DAMAGE 1000 only, where the trap dominates.

## Next options (the user's)

- A live DAMAGE control: an IR element for the traps (a seeded telegraph current per sample, both
  builders, circuitsim, deterministic for takes), on the ladder (and VCA) by default; HEAT as the
  traps' Arrhenius rates (cold: slow pops, warm: fast crackle).
- The pitch sites only as an extreme bend, or not at all.
