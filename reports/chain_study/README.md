# Where a chain's character comes from (2026-11-14)

This follows `../chain_passes/` and `../chain_spike/`: the same repeated-pass setup (100 dB SPL, the
V76 at 24 dB, pass N fed back as the next pass's input). Four studies:

- **attribution:** which part of the U47 -> V76 distorts;
- **units:** how far units of a chain spread;
- **bends:** conditions past the nominal;
- **whatif:** the transformer values a web search turned up.

Run with `uv run --extra fast --extra listen python scripts/chain_study.py [--only ...]` (about 50 + 9
min of renders on 14 threads; cached). The stage probes are `scripts/chain_stages.py`.

**Read `../chain_passes/production/README.md`'s "Correction" first.** The fitted "character" measure
of the earlier reports was as large as its own floor on these chains. Every figure here is the
**residual**: the output against g H^N x (the multisine-measured response, applied exactly). Its
floor is -82 to -90 dB on the omni control and -59 to -64 dB on the U47 -> V76 at 80 dB SPL.
`stages.json` (the per-stage probe study) used the old measure and shows mostly its floor; it isn't
used below.

## Attribution: tubes vs iron (U47 -> V76)

Each core Jiles-Atherton alone, the others in their linear limit. Residual against the dry stem,
pass 1 / 4:

| cores JA | bass | guitar | harmonies | lead vocal |
| --- | --- | --- | --- | --- |
| all (nominal) | -44.0 / -38.7 | -45.6 / -36.7 | -45.6 / -40.2 | -47.8 / -40.1 |
| none (the tubes alone) | -47.5 / -40.2 | -49.4 / -42.5 | -45.8 / -40.5 | -48.7 / -42.2 |
| BV8 only | -45.0 / -39.5 | -47.2 / -39.3 | -45.6 / -40.2 | -48.1 / -40.9 |
| T85 only | -47.0 / -40.4 | -48.0 / -40.2 | -45.8 / -40.5 | -48.5 / -41.8 |
| L86, L88 or T89 only | = none | = none | = none | = none |

- **On the bass and guitar the iron distorts about as much as the tubes** (by power, the iron's
  share is about -46.6 dB on the bass), almost all of it the BV8, some the T85.
- **On the harmonies and the vocal the tubes do it**: the iron adds nothing measurable.
- The chokes and the output transformer add nothing.

## Units: 8 tolerance draws per chain

passive_spread 1 (every part and tube uniform across its band), seeds 1-8. Bass and lead vocal,
passes 1-4.

| chain | 1 kHz gain spread | response shape spread | pass-1 residual, bass / vocal (nominal) |
| --- | --- | --- | --- |
| U47 -> V76 | 1.2 dB | <= 0.25 dB | -44.3 .. -43.8 / -48.0 .. -47.2 (-44.0 / -47.8) |
| 44-BX -> 610 | 2.4 dB | <= 0.2 dB | **-51.3 .. -36.7 / -55.1 .. -40.4** (-45.1 / -48.9) |
| SM57 -> API 312 | 2.6 dB | <= 0.12 dB, but 2.8 dB at 15 kHz | -54.6 / -61.5 for every unit |

- **Units differ mostly in level**, which a loudness match takes away. Their response shapes agree
  within a quarter dB. (The spike's "a tolerance draw changes the sound most" was this level
  difference.)
- **The UA 610's distortion depends on the unit: 14 dB from the cleanest to the dirtiest.** That
  is a real difference between units: some 610s would sound clean, others gritty.
- The SM57 -> API 312's distortion doesn't vary because its transistors have no tolerance draws
  (only the passives do).

## Bends (U47 -> V76)

Each is a physical condition; `../chain_study/variants_why.json` has every number's reason. Residual
against the dry stem, passes 1 / 4 / 8:

| bend | bass | guitar | harmonies | lead vocal |
| --- | --- | --- | --- | --- |
| nominal | -44.0 / -38.7 / -34.2 | -45.6 / -36.7 / -30.9 | -45.6 / -40.2 / -34.1 | -47.8 / -40.1 / -34.6 |
| **loud_115** (a 115 dB SPL source, the V76 at 9 dB) | **-33.6 / -26.7 / -21.9** | **-36.2 / -27.8 / -22.3** | **-32.6 / -26.9 / -21.8** | **-36.5 / -28.8 / -23.2** |
| hum_heavy (dried-out filter caps: ripple +40 dB, field +20 dB) | -40.5 / -37.5 / -31.6 | -40.5 / -29.3 / -22.6 | -40.9 / -38.1 / -32.5 | -41.7 / -36.9 / -29.4 |
| weak_ng (the NG at 220 V, not 300) | -43.0 / -38.1 / -33.6 | -44.3 / -36.1 / -30.3 | -43.2 / -37.8 / -31.8 | -45.7 / -38.7 / -33.4 |
| small_bv8 (a quarter of the core, twice the turns) | -42.1 / -36.4 / -31.8 | -44.1 / -34.5 / -28.6 | -45.5 / -39.6 / -33.5 | -47.0 / -38.4 / -32.8 |
| brownout (mains 198 V, the NG 270 V) | -43.5 / -38.0 / -33.4 | -45.0 / -36.3 / -30.6 | -44.6 / -39.3 / -33.2 | -46.9 / -39.6 / -34.2 |
| tired_vf14 (half its emission) | -44.8 / -39.3 / -34.7 | -46.3 / -36.8 / -30.9 | -47.6 / -41.8 / -35.7 | -49.3 / -41.0 / -35.5 |
| microphonic (the modes at -20 dB) | = nominal | = nominal | = nominal | = nominal |

- **Level is the lever.** A loud source puts 10 dB more distortion into every pass, about 2-3 % per
  pass at 115 dB SPL, and 6-8 % after 8 passes. This one is realistic: a guitar cab or a kick at
  115 dB SPL into a U47 happens.
- **Hum compounds**: on the guitar it reaches -22.6 dB by pass 8.
- A weak supply or a smaller BV8 adds 1-2 dB. A brownout adds less.
- **An aged VF14 distorts less** (-1 to -2 dB). At half the emission it has 0.5 dB less gain, and
  its operating point moves to a straighter part of its curves.
- **The microphonics are invisible to the residual: as modelled they are linear.** The tube
  rings with the sound, so they count as tone: narrow peaks at the modes. Real microphonics are
  mostly linear too. They show in `p8.wav` as rings, not in this number.

## What-ifs: the sourced transformer values (U47 -> V76)

From a web search (`data/schematics/{neumann_u47,telefunken_v76}/README.md`, "Found 2026-11-14").
These are options, **not applied to the circuit files**. Residual pass 1 / 4, and the response:

| variant | bass | guitar | harmonies | lead vocal | 50 Hz re 1 kHz | 15 kHz |
| --- | --- | --- | --- | --- | --- | --- |
| nominal | -44.0 / -38.7 | -45.6 / -36.7 | -45.6 / -40.2 | -47.8 / -40.1 | +0.17 | +0.51 |
| BV8 30 pF (originals, forum) | same | same | same | same | +0.17 | +0.53 |
| BV8 180 H (clones 150-211 H, forum) | -44.1 / -38.6 | -46.2 / -37.6 | -45.7 / -40.6 | -47.9 / -40.2 | -0.65 | +0.51 |
| T85 3 ohm per half (a 1974 unit, forum) | -43.5 / -36.6 | -45.6 / -36.4 | -45.6 / -40.2 | -47.9 / -40.2 | **+1.53** | +0.75 |
| T89 650 / 11 ohm (forum, origin unknown) | same | same | same | same | +0.16 | +0.51 |
| all four | -43.5 / -37.1 | -46.2 / -37.5 | -45.7 / -40.6 | -48.0 / -40.3 | +0.70 | +0.77 |

- Better transformer data moves the distortion by 2 dB at most, and the tone by 1.5 dB at 50 Hz at
  most.
- The one discrepancy worth deciding is **T85's primary resistance**. Ours is 77 ohm per half,
  calibrated to the Braunbuch's response; one owner measured 3 ohm. Its source says the 77 ohm damps
  the 40 Hz high-pass's resonance and "stands in for losses the core lacks at microphone levels",
  so it isn't a winding's resistance at all. With 3 ohm the chain gets 1.4 dB more at 50 Hz, and
  the V76 alone (`varimu unit --circuit telefunken_v76 --set t85_r_half_ohm=3`,
  `reports/units/v76_t85_3ohm/`) meets 45 of the Braunbuch's 50 specs instead of 47. It newly fails
  the 40 Hz distortion at +22 dB out: k3 4.85 % at 76 dB of gain and k2 3.96 % at 34 dB, against
  1.0 / 1.5 % allowed. The flat-response spec fails either way. So the stand-in keeps the unit closer
  to its published behaviour. The option is to model T85 with its real 3 ohm winding and put the
  missing loss where it belongs (the core's loss at low level, which the material fit lacks). It's
  the user's call, since it changes renders.

## Files

- `<study>/summary.json`: every figure, plus each variant's response at fixed frequencies.
- `variants_why.json`: why each bend and what-if has its numbers.
- Audio, loudness matched to -23 LUFS:
  - `attribution/<stem>/<config>/p1.wav`;
  - `units/<stem>/<chain>_unit{1,2,3}|nominal/p1.wav, p4.wav`;
  - `bends/<stem>/<bend>/p1.wav, p8.wav, p8_eqnull.wav`;
  - `whatif/<stem>/<variant>/p1.wav, p4.wav`;
  - `dry_<stem>.wav`.

Listen: `bends/<stem>/loud_115/p8.wav` against `bends/<stem>/nominal/p8.wav` (the biggest
realistic change), `bends/guitar/hum_heavy/p8.wav`, `bends/lead vocal/microphonic/p8.wav` (the rings),
and the 610's cleanest unit against its dirtiest: `units/<stem>/r44_ua610_unit2/` (bass -51.3 dB)
against `r44_ua610_unit4/` (-36.7 dB). The order of all eight is in summary.json.
