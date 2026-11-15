# Radioactivity in audio: a neon oscillator primed by a radioisotope (2026-11-14)

`uv run --extra listen python scripts/neon_primer.py` (about 5 min, offline Python, nothing in the
engine changed). The script's docstring has every source and fitted number.

## The idea

Radioactivity did have a real job in audio-era electronics: **GE put a "mild radioactive additive"
in most of its neon glow lamps "for the reduction of dark effect"** (Kr-85 in the fill gas, per patent
literature; GE never names the isotope). A neon lamp across a capacitor fed through a resistor is a
sawtooth oscillator, and it was the first tone source of the Trautonium (1930).

The lamp fires when the capacitor passes its breakdown voltage, but only once a free electron
appears in the gas to start the avalanche. Light knocks those electrons out of the cathode. In the dark
they come from:
- the afterglow of the last discharge;
- cosmic rays;
- **the radioisotope**.

So in a dark cabinet, the radioactivity decides how regularly the oscillator fires.

## The model

One NE-23 (GE's 5AB, which has the additive), fitted to **GE's Glow Lamp Manual (2nd ed., 1966)**:

| what | from | how |
| --- | --- | --- |
| seed electrons in the dark: 200 /s; the chance one starts an avalanche, P(overvoltage) | Fig. 5.9, 0 ft-c | fitted, 0.09 rms in log |
| avalanche time vs overvoltage (300 us just over breakdown, 25 us at +60 V) | Fig. 5.9, 500 ft-c | fitted |
| seeds per foot-candle of light (5e5 /s) | Fig. 5.9, 0.1 ft-c | fitted |
| breakdown lowered just after a discharge (~10 V, recovering over ~5 ms) | Fig. 5.12 | by eye |
| avalanche faster just after a discharge (22 us at 0.5 ms, 100 us after 50 ms) | Fig. 1.3 | by eye |
| extinguishing voltage vs R and frequency | Fig. 2.16 | by eye |
| afterglow seeds | provisional, two scenarios (below) | |
| cosmic-ray background for an unprimed lamp, 0.1 /s | provisional | |
| Kr-85's half-life, 10.76 y (2.1 % left after 60 years) | model knowledge | |

**The check (not fitted):** the lamp oscillating under office light against GE's Figs. 2.15 and 2.17.

| | GE | model |
| --- | --- | --- |
| firing voltage, rel. to 1 Hz, at 100-200 Hz | +1.3 / +1.8 V | +0.8 / +0.5 V |
| firing voltage at 1 / 4 / 10 kHz | -0.5 / -3.0 / -2.0 V | -2.0 / -4.0 / -1.3 V |
| sawtooth amplitude at 1 / 100 / 300 / 1k / 10k Hz | 18 / 30 / 32 / 31.5 / 28 V | 16 / 27 / 29 / 28 / 28 V |

The shape comes out right: the bump at ~200 Hz, the dip at ~4 kHz, the amplitude's rise and fall.
An earlier version without Fig. 1.3's faster re-avalanche missed it by +9 V at 10 kHz.

**What isn't known: the afterglow's memory.** After a discharge, the gas keeps seeding the next
breakdown for a while.
- GE (Fig. 5.12) shows it lasts at least ~5 ms.
- Pejović et al. measured it in neon lab tubes from 30 ms out to ~3 s, after which cosmic rays and
  natural radioactivity take over ([osti.gov/biblio/22253136](https://www.osti.gov/biblio/22253136)).

  Their tubes are 7 mbar lab tubes, not glow lamps.

So everything is run in two scenarios:
- **short**: only GE's ~1 ms;
- **long**: a Pejović-like tail to ~3 s.

## Conditions

| name | seed electrons from outside, /s | what it is |
| --- | --- | --- |
| `lit` | 2.6e7 | the NE-23 under office light (50 ft-c) |
| `dark_hot` | 6,000 | the primer x30 (GE: dark effect "cannot be completely eliminated without prohibitively high radiation intensities") |
| `dark_1966` | 200 | the NE-23 in a dark cabinet, primer as made |
| `dark_2026` | 4.3 | the same lamp today: its Kr-85 decayed to 2 % |
| `dark_unprimed` | 0.1 | a plain neon lamp in the dark, cosmic rays only |

## What came out

**1. How late a keyed note speaks** (the first firing after 8 s of rest, GE's own test; 400 draws):

| | median | 90 % |
| --- | --- | --- |
| lit | 0.6 ms | 0.6 ms |
| primer x30 | 1.8 ms | 2.8 ms |
| primer, 1966 | 8 ms | 16 ms |
| **primer, 2026** | **185 ms** | **625 ms** |
| no primer | 8 s | 25 s |

This holds in both memory scenarios: after rest there is no afterglow, only light and the isotope.
- **A neon voice from 1966, in its dark cabinet today, speaks a fifth of a second to more than half a
  second late**, because its radioactive primer has decayed. New, it was 8-16 ms.
- In the tunes, the 2026 lamp's first notes come in at 0.56-0.67 s; the unprimed lamp's at 1.8-3.1 s.

**2. Pitch jitter while running** (`neon_primer.png`, right; cycle-to-cycle, rms cents):

| | 27.5-110 Hz | 220 Hz | 440 Hz | 880 Hz |
| --- | --- | --- | --- | --- |
| lit | 3-6 | 3 | 3 | 3 |
| dark, short memory, primer 1966 | 400-800 (the pitch halves) | 19 | 7 | 5 |
| dark, short memory, primer 2026 | 1,200-2,900 (stalls) | 19 | 7 | 5 |
| dark, long memory, any primer | 30-45 | 18 | 7 | 5 |

- **Above ~200 Hz the primer doesn't matter.** The lamp seeds itself from its own afterglow. It
  jitters 5-20 cents in the dark against ~3 under light. That alone makes a dark neon voice a little
  chorused against a lit one.
- **In the bass it depends on the afterglow's memory**:
  - short memory: the primer is the difference between a working bass (barely: the pitch drops an
    octave, as GE warns, "an entirely different frequency" in the dark) and a dead one;
  - long memory: the bass runs on its afterglow with 30-45 cents of jitter, and the primer only sets
    when it starts.

  Which is real for a glow lamp is unmeasured here.

**3. Processing: a neon LFO as a tremolo** on the acoustic guitar stem (4.4 Hz, R 1 MOhm, C 0.47 uF; the
gain law is an idealized stage, not a circuit):

| | short memory | long memory |
| --- | --- | --- |
| lit | 4.40 Hz, 3 cents | the same |
| primer x30 | 4.04 Hz, 67 cents | 4.25 Hz, 28 cents |
| primer 1966 | 3.20 Hz, 250 cents | 4.25 Hz, 34 cents |
| primer 2026 | 1.27 Hz, 620 cents, beats up to 2.3x long | 4.24 Hz, 28 cents |
| no primer | never starts (gain stuck) | never starts |

At LFO rates the primer is the instrument: with a short memory it moves the tremolo from metronomic
(lit), through a drunk lurch (1966), to a limp (2026), to stuck (unprimed).

## Listen

- `tune_<memory>_<condition>.wav`: a bass line and melody on two neon lamps, Trautonium-style (pitch by
  the resistor, each key trimmed under the bench lamp, then played in the dark). The tone filters are
  plain RC low-passes, not a model. Loudness matched, voices at the lit version's gains; the stalled ones
  have their peaks held at -1 dBFS.
  - `tune_short_lit` vs `tune_short_dark_1966` vs `tune_short_dark_2026`: the bass wandering, then
    collapsing.
  - `tune_long_lit` vs `tune_long_dark_1966`: the subtler version, a chorused, uneasy bass.
- `tremolo_<memory>_<condition>.wav`: the guitar through the neon tremolo. Start with `tremolo_short_lit`,
  `tremolo_short_dark_1966`, `tremolo_short_dark_2026`.

## Caveats

- The afterglow memory decides the bass. Both scenarios are provisional; the long one is lab-tube data.
- The unprimed background (0.1 /s) is an order-of-magnitude estimate, x10 either way.
- One lamp, nominal. GE's spread between lamps (breakdown 60-90 V) isn't drawn.
- The discharge is instantaneous; the extinguishing voltage is quasi-static from Fig. 2.16.
- The 3 cents of jitter under light is the model's statistics just past breakdown (few seed electrons
  start an avalanche there); GE doesn't publish a jitter figure to check it against.
- Not part of the engine: no SPICE / circuitsim twin, no tests. Turning it into a device (a `glow_lamp`
  kind, its random firing as a hybrid event like the thyratron's) would be a plan of its own.

## Sources

- GE Glow Lamp Manual, 2nd ed. (1966): [archive.org/details/ge-glow-lamp-manual-1966](https://archive.org/details/ge-glow-lamp-manual-1966), Figs. 1.2, 1.3, 2.15-2.17, 5.9, 5.12, the NE-23 / NE-2 specification pages.
- GE glow lamp specifications (NE-2U's dark-effect figure, NE-23's additive): [w140.com/tekwiki/images/e/e6/Neon_lamp_specifications.pdf](https://w140.com/tekwiki/images/e/e6/Neon_lamp_specifications.pdf).
- Kr-85 in glow discharge starters: US patent 5,512,799 ([uspto](https://image-ppubs.uspto.gov/dirsearch-public/print/downloadPdf/5512799)).
- Neon memory curves: Pejović et al., [osti.gov/biblio/22253136](https://www.osti.gov/biblio/22253136).
- The Trautonium's neon oscillators: [Wikipedia](https://en.wikipedia.org/wiki/Trautonium).
