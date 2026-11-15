# Frankenstein: exotic iron and tubes in the U47 -> V76 (2026-11-14)

`uv run --extra fast --extra listen python scripts/chain_frankenstein.py` (production; about 15 min of
renders, then cached). Passes 1-4 at 100 dB SPL on the bass, guitar and lead vocal, staged as in
`../chain_passes/`. Figures are the residual (`../chain_passes/production/README.md`, "Correction"):
what the chain's own response doesn't explain, dB re signal.

## The variants (the script's docstring has every reason and number)

**The BV8**, the U47's output transformer and the iron that distorts. Each new core is **rewound to
the nominal's 91 H**, so the material changes and the bass doesn't. More turns of the same wire on
the same bobbin: DCR x n, leakage x n^2. That scaling is provisional.

| core | mu_r (small signal) | turns | primary DCR | leakage | leakage-capacitance resonance |
| --- | --- | --- | --- | --- | --- |
| mumetall (nominal) | 29,300 | 2,600 | 628 ohm | 0.1 H | ~41 kHz |
| **osmium / uranium = air** (paramagnetic: mu_r 1.00002 / 1.0004) | 1 | 255,292 | 61.7 kOhm | 18 H (k ~ 0.9) | ~1.2 kHz |
| Victorian soft iron (Ewing, 1885) | 187 | 18,796 | 4.5 kOhm | 5.2 H | ~5.7 kHz |
| power-transformer silicon steel | 45,300 | 2,444 | 590 ohm | 0.09 H | ~44 kHz |
| pure nickel (the Nickel Organ's fit) | 102 | 25,420 | 6.1 kOhm | 9.6 H | ~4.2 kHz |
| hardened tool steel (a hard material, Hc ~ 3.5 kA/m) | 21 | 55,696 | 13.5 kOhm | 46 H | ~1.9 kHz |
| **room-sized** (x100 everything: a 1 m^2 core, 9 m path, 7 mm wire) | 29,300 | 2,600 | 6.3 ohm | 10 H | ~410 Hz |

**Tubes in the VF14's place**, heated normally: a 12AX7, a 2A3 (a power triode), a 56 (1930s). And
the **monster**: room-sized, tool steel, a 2A3.

The V76's gain is re-picked per variant so its output peaks match the nominal's: 24 dB for most, 34
for the 56, 52 for the 2A3, 76 for the monster.

## What came out

Residual, pass 1 / 4 (bass, guitar, lead vocal), and the response re 1 kHz:

| variant | bass | guitar | vocal | 50 Hz | 100 Hz | 2 kHz | 5 kHz | 10 kHz |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| nominal | -44.0 / -38.7 | -45.6 / -36.7 | -47.8 / -40.1 | +0.2 | +1.0 | -0.1 | +0.2 | +2.7 |
| air core (osmium / uranium) | -53.0 / -45.6 | -53.7 / -46.5 | -53.3 / -46.7 | -4.5 | +0.4 | -2.7 | -8.8 | -12.3 |
| Victorian iron | -41.0 / -35.4 | -43.1 / -32.9 | -47.4 / -37.3 | +0.6 | +1.9 | -2.3 | -7.8 | -10.9 |
| power steel | -47.0 / -40.4 | -48.0 / -40.2 | -48.5 / -41.7 | +0.3 | +1.1 | -0.1 | +0.2 | +2.7 |
| nickel | -43.7 / -38.2 | -45.2 / -35.4 | -49.5 / -40.5 | +2.1 | +3.5 | -3.9 | -10.6 | -14.0 |
| tool steel | -51.3 / -43.2 | -52.0 / -44.0 | -54.7 / -47.3 | **+10.0** | **+11.4** | -5.9 | -13.5 | -17.0 |
| **room-sized** | -46.1 / -36.0 | -44.9 / -34.3 | -41.5 / -35.6 | +3.4 | +5.3 | -6.3 | -19.2 | **-28.2** |
| **12AX7 in the U47** | **-21.5 / -15.7** | **-22.6 / -17.4** | **-21.4 / -15.9** | -3.6 | +0.1 | +0.6 | +0.5 | +2.4 |
| 2A3 in the U47 | -35.4 / -27.2 | -38.0 / -29.8 | -37.5 / -33.1 | +2.2 | +1.6 | -0.2 | +0.3 | +3.6 |
| 56 in the U47 | -40.5 / -33.8 | -42.0 / -34.5 | -41.6 / -36.3 | -3.7 | +0.1 | -0.2 | +0.2 | +2.9 |
| **monster** | -35.5 / -27.8 | -37.1 / -26.6 | -36.2 / -27.6 | -11.7 | -10.0 | -22.4 | -40.4 | -52.0 |

(`responses.png` draws them.)

- **The exotic cores change the tone, not the grit.** Rewound to the same inductance, a weak core
  needs far more turns. That lowers its flux density (so it distorts *less*: the air core and the tool
  steel are the cleanest of all) and piles up resistance, leakage and capacitance. The sound is those
  parasitics: a softer, darker top. The leakage meets the winding capacitance in the 1-6 kHz range
  instead of 41 kHz.
- **A room-sized transformer sounds huge in the obvious way**: +5 dB of warmth from 60 to 400 Hz and a
  top that falls away (-28 dB at 10 kHz). Everything scales with size, so the leakage and capacitance
  bring its bandwidth down to the low kilohertz. It's a physical reason why bigger iron sounds darker.
- **Tool steel** gets a +11 dB low-mid hump into the V76's padded input. Its sound depends on the load:
  at the V76's 40 dB setting, with the pad out, it rang at +15 dB near 1.8 kHz instead (the first run).
- **The osmium / uranium core is an air core**, physically: neither metal is ferromagnetic. Rewound
  to 91 H, it is so high-impedance that the V76's loading decides its sound. At 34 dB (pad out) its
  2.5 kHz resonance went undamped and overloaded the V76 (-27 dB, peaks +1.5 dBFS). Padded, at 24 dB,
  it is clean and soft-topped.
- **The tube swaps are where the grit is.** A 12AX7 (mu 100) in the VF14's socket, at the U47's 105 V,
  100 kOhm and zero grid bias, distorts about 25 dB more than the VF14 (-21 dB in one pass, -16 by four):
  a fuzzed U47. The 2A3 (mu 4) adds about 8 dB, the 56 about 4.
- **The monster**: room-sized, tool steel and a 2A3, so 85 dB quieter at 1 kHz with the V76 at 76 dB.
  It becomes a narrow resonance at about 870 Hz, everything else 10-50 dB down: a voice from inside a
  mountain.

## Caveats

- Rewinding is a provisional scaling (DCR, leakage and winding capacitance from the turns' ratio), not
  a construction. The component editor's transformer designer (`crates/varimu-components`, with its
  FEM leakage) would give the real parasitics of each design.
- Tool steel's JA parameters are an order-of-magnitude set from Bozorth's coercivities, not a fit.
- The tube swaps run each tube at the VF14's operating point, which suits none of them: that is the
  point, but it is not how anyone would use a 12AX7.
- Physically the uranium core is also radioactive. That has no electrical effect.

## Files

- `<stem>/<variant>/p1.wav`, `p4.wav`: loudness matched to -23 LUFS.
- `<stem>/dry.wav`, `responses.png`, `summary.json` (with each variant's turns, parasitics, V76 gain).

Listen: `lead vocal/room_sized/p4.wav`, `lead vocal/tube_12ax7/p1.wav`, `guitar/tool_steel/p4.wav`,
`lead vocal/monster/p4.wav`.
