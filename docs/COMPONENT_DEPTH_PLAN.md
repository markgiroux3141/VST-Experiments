# Component depth: where deeper part models matter

2026-11-11. A brainstorm with the user; nothing built. The question: would modelling
individual parts more deeply (resistors, capacitors, tubes, transformers) change the sound
where it matters, and what would it cost? The answer we chose to pursue: test depth where a
device **misses its published figures**, starting with the 670, rather than part by part in
the abstract. It picks up DEVICE_BUILDER_PLAN.md B6's backlog ("B6's rest backlogged",
2026-10-30) and feeds FUTURE_DIRECTIONS.md §8.2 (the audibility map).

## What exists

- **Resistors:** an ideal R, plus Johnson noise in circuits with a `noise` block (B5; only
  tube_synth has one).
- **Capacitors:** an ideal C (an optional start voltage `v0`).
- **Tubes:** Koren fits, variable-mu, grid current, interelectrode capacitances, shot /
  partition / flicker noise (B5), the heated cathode (B6).
- **Transformers:** Jiles-Atherton cores with a Rayleigh region, leakage, winding R and C,
  eddy loss; Preisach for tape only.
- **Measured and found inaudible (B6, 2026-10-30):**
  - capacitor leakage and dielectric absorption (DA): 670 -58 dB / 0.012 dB, EQP-1A
    -62 / 0.008, 5E3 -47 / 0.10. Measured on the **default panels** with noise at
    -20 dBFS (see "The release" below for why that matters);
  - pot end resistance: inaudible at realistic values.

## Method: three axes, not one

Probing a part in isolation tells us whether a deeper model differs from the ideal one. It
doesn't tell us whether that matters, and it misleads both ways:
- **Big in isolation, masked in the circuit.** A carbon resistor's voltage coefficient
  distorts, but a triode next to it distorts 20-30 dB more (estimate).
- **Tiny in isolation, amplified by the circuit.** 100 ppm in an oscillator's timing, a
  cathode resistor in a stage biased near cutoff, anything inside a feedback loop, a
  timing capacitor holding charge for seconds.

So every experiment looks at all three:

1. **Isolation (the component bench).** A small test circuit per part type in both
   builders: source impedance -> part -> load. Stimuli:
   - DC sweeps;
   - sines at several bias points;
   - two-tone IMD;
   - burst trains, for memory: does burst 10 differ from burst 1?
   - level steps, for thermal effects;
   - noise under bias.

   Metrics:
   - harmonics and IMD (for resistors, IEC 60440's third-harmonic index);
   - a memory score;
   - the noise spectrum, and how much the noise envelope follows the signal;
   - the null against the ideal part, as a spectrum.
2. **Context (the operating envelope).** One render per circuit with every probe on. For
   each part, record:
   - its DC voltage and current;
   - its signal swing over a program excerpt;
   - its dissipation;
   - the impedances around it.

   Then look up step 1's deviation at exactly those conditions.
3. **Consequence (at the output).** Multiply each part's deviation by the output's
   sensitivity to that part (DK's linearized step gives it at the operating point, as in
   FUTURE_DIRECTIONS.md §8.2). Confirm the top few parts per circuit with full renders:
   deep against ideal, nulled, loudness-matched.

Changes that move renders come to the user as options first (the hard rules and the
project's working rules); subtle differences count as verified.

## Where depth is likely to matter (rules of thumb)

- **Anything holding charge for seconds** (compressor release, envelopes, LFOs): DA and
  leakage in the timing capacitors.
- **Anything setting a pitch or frequency** (VCOs, LFOs, filter tuning): tempco and
  self-heating become cents. The Minimoog's exponential converter has a deliberate
  +3300 ppm/K tempco resistor for this reason.
- **High-gain first stages at idle:** excess noise and heater hum.
- **Balanced and push-pull stages:** mismatch is what lets hum, supply noise and thump
  through. A perfectly matched model hides everything else.
- **A part's own nonlinearity** only where nothing bigger masks it: solid-state gear, high-K
  ceramic capacitors (X7R / Z5U), rarely tube circuits.

## The 670's gaps

From `reports/units/nominal/report.json` (`vs_670`) and `reports/noise/670_idle.json`. The
compression curve (curve 3 within 0.52 dB), limiting at +25 dBm (19.5 vs 19.0 dB), the
distortion specs, the 40 Hz-15 kHz response and the supply rails all agree. These don't:

| Gap | Ours | Published | Ratio / difference | Source of the figure |
|---|---|---|---|---|
| Idle noise | -115 dBm | ~-66 dBm | 49 dB quieter | "~70 dB below +4 dBm": dealers' and the reissue's sheets, bandwidth unstated, not from an original document |
| Release, TC 6, "consistently high program level" | 11.2 s | 25 s | 0.45x | [MAN] p.4 |
| Release, TC 5, "multiple peaks" | 6.5 s | 10 s | 0.65x | [MAN] p.4 |
| Attack, TC 3 and TC 5 | 0.25 ms | 0.4 ms | 0.62x | [MAN] p.4 (how it was measured isn't stated) |

TC 6's release from multiple peaks runs long instead (13.9 s vs 10 s, 1.39x, within the
check's bounds).

### The release: the test first, then the capacitors

**Our measurement can't reach the figure.** `varimu/measure/suite.py` measures "consistently
high program level" with one `BURST_S` = 1 s burst at the 10 dB point, then a
`RELEASE_WINDOW_S` of 15 s. TC 6's slow branches are R139 / C110 (100k x 8 uF = 0.8 s) and
R140 / C112 (100k x 20 uF = 2 s). A 1 s burst doesn't fill C112, and a 15 s window can't
measure a 25 s release. We test a peak and call it sustained program.

**DA was measured where it couldn't show.** The slow parts of TC 4-6 are C111 (4 uF 150 V,
position 4), C110 (8 uF 150 V, positions 5-6) and C112 (20 uF 150 V, position 6). The circuit
file's tolerance block classes them as electrolytic (an assignment, not printed on the
drawing). B6's DA measurement ran at the default panel, TC 2, where none of them is switched
in.
- Electrolytics' DA is ~10-15% (IEC 60384-1 data; B6 fitted k = 14.5% per decade of time
  constant for Dow's model).
- A dielectric that held a charge gives part of it back slowly after the program stops. So
  the release would lengthen with how long the unit has been compressing: the direction of
  the gap.
- It is memory over tens of seconds to minutes: a 670 that squashed the chorus would let go
  more slowly in the bridge. An ideal capacitor can't do that.

**Leakage** works the other way (it shortens the release). An electrolytic's leakage falls
steeply below its rated voltage, and the control voltage sits far below 150 V, so it is
probably small; it should be measured alongside DA.

### The noise floor: mismatch, then hum, then hiss

With noise off, the 670 idles at -247 dBm: no hum reaches the output. Its 49 dB gap is what
we don't model. In the order to test:

1. **Mismatch (no new physics).** The nominal genome has `passive_spread` 0, so the 6386
   push-pull stage is perfectly balanced and cancels supply ripple and common-mode noise
   exactly. A real unit is trimmed only for thump (BALANCE). `scripts/noise_670.py` with a
   realistic spread and per-tube draws may raise the floor by tens of dB on its own. The
   Python builder draws tolerances; varimu-circuit refuses a nonzero spread (nominal units
   only, NATIVE_APP_PLAN.md R1).
2. **Hum.** Nothing of it is modelled (`data/schematics/fairchild_670/README.md`: the heater
   windings and loads are left out):
   - AC heaters into the cathodes through heater-cathode capacitance and leakage (whether the
     audio tubes' heaters are AC, and how they are elevated, is to be read off the drawing);
   - the power transformer's stray field into T101 / T102: a small mutual inductance from
     the mains to the audio windings (the coupling has no source; provisional and bounded).
3. **Hiss with character.**
   - Carbon resistors' excess noise where DC flows through high values (the sidechain's
     plate loads, the dividers).
   - The 6386's flicker noise.

   Once the noise comes from parts whose current follows the control voltage, the hiss rises
   and falls with the gain reduction: texture.

**A better target first.** Fairchild's own noise spec, with its bandwidth and weighting, or
any recording or measurement of a real unit at idle, would say whether the gap is mostly hum
lines (build 2) or hiss (build 3). If the source is walled, the user fetches it.

## The resistor in layers (for the bench)

Figures are model knowledge, to be replaced by MIL-R-11, IEC 60440 and Allen-Bradley /
Ohmite sheets before anything is fitted.

| Layer | What it adds | Carbon composition | Metal film |
|---|---|---|---|
| L0 | ideal R + Johnson noise (what we have) | | |
| L1 | tempco + self-heating on a thermal node (the lamp's pattern), seconds-scale lag | ~+-500-1500 ppm/K | ~+-50 ppm/K |
| L2 | voltage coefficient: R depends on the voltage across it, mostly 3rd harmonic | ~0.01-0.05 %/V | ~0 |
| L3 | excess (current) noise: 1/f, proportional to the DC through it, so it follows the signal | noise index ~0 to +10 dB | -20 to -40 dB |
| L4 | parasitic L / C | negligible at audio | negligible, some wirewounds aside |
| L5 | a micro-model: a network of carbon grains with contact constrictions; L1-L3 come out of it together, correlated per part | | |

L5 would be the reference that L1-L3 are fitted to, as in HYBRID_PHYSICS_PLAN.md.

The predictions to test:
- **L2 is masked in tube circuits.** A 100k plate load swinging +-50 V at 0.03 %/V changes
  by ~1.5% over a cycle; the triode's own distortion is far larger.
- **L3 is the strongest candidate.** A 100k plate load with ~100 V across it at noise
  index 0 dB (1 uV per volt per decade) gives ~170 uV over 20 Hz-20 kHz; its Johnson noise
  is ~6 uV. That puts excess noise ~30 dB above what B5 models there, at low frequencies
  (1/f), and modulated by the signal.
- **L1 matters for power stages and tuning.** Cathode-bias, screen and dropping resistors
  heat up, so the bias drifts over seconds with the music's envelope (a slow sag). In the
  synths' oscillators, tempco becomes pitch drift.

## Processing cost

| Item | Rough cost | Where it runs |
|---|---|---|
| Longer release measurement | none (a test change) | n/a |
| Tolerance spread on | none at run time (drawn at build) | Python now; the app needs varimu-circuit to accept spreads |
| DA on the 670's three timing capacitors | 4-9 RC branches each, on the control-voltage node. DA on every capacitor cost 1.5-5.2x (B6); here a guess of +5-15%, to be measured | probably live as well |
| Excess noise | B5's streams, one per DC-carrying resistor (~20-40 in the 670); each B5 noise class cost ~+0.15x real time at draft on tube_synth | production default; a live option |
| Heater hum, stray mains coupling | a few sources and R / C per tube; near free, though DK's cost grows with the square of the states | both |
| Self-heating (L1) | one thermal state per resistor that has it | both |
| Voltage coefficient (L2) | makes a resistor a nonlinear device port: costly in DK | production only, and only where the bench says it matters |

**A production catch with long memory.** DA's slow branches (up to ~1000 s) make a render
depend on minutes of history. Chunked renders (the compression curve's chunks, tape-style
pieces) and short excerpts would start "fresh" where a real unit wouldn't. Either production
gets a longer warm-up, or the first minute of a print runs fresh, stated. `--verify`'s check
that the chunked curve equals the continuous staircase would catch the first case.

## Milestones

**CD0. Fix the release measurement.** Sustained limiting of 10, 30 and 60 s before the
release, and a release window of at least 60 s, for TC 4-6; keep the 1 s burst as the
"peak" measure where the manual means one. Re-run the nominal unit's timing.
*Done when:* the report has both, the tests cover the new stimuli, and the remaining gap is
stated.

**CD1. Noise with mismatch.** `noise_670.py` with a realistic passive spread and per-tube
draws (several seeds); the idle floor and its spectrum (hum lines vs hiss) for each.
*Done when:* the floor's spread over seeds is in the report and the gap is restated.

**CD2. DA and leakage on the timing capacitors.** In a scratch copy first: Dow's branches
(the B6 prototype) on C110, C111 and C112, plus leakage. Soak at 10 dB of gain reduction
for 10, 60 and 300 s; measure the release against ideal capacitors and the manual's 25 s;
measure the cost. Options to the user before it becomes a default.
*Done when:* the numbers and options are written here.

**CD3. The noise sources.** After a better target is found: hum (heaters, stray coupling)
and / or hiss (excess noise in resistors, the 6386's flicker), each a sourced, bounded
parameter in both builders and engines, as B5's streams are. Measured on the 670, then the
5E3 and tube_synth.
*Done when:* each has its reference and engine implementations with agreement tests, and
the 670's floor is within a few dB of the target (or the remainder is explained).

**CD4. The component bench.** The isolation harness above, generic per part type; the
resistor layers L1-L3 first, L5 offline as their reference.

**CD5. Envelope and consequence.** The operating-envelope harvest and the sensitivity
ranking for the 670, the EQP-1A, the 5E3 and tube_synth: a table of each layer's effect in
dB at the output. This is FUTURE_DIRECTIONS.md §8.2's audibility map, extended from values
to physics.

**CD6. Other part types**, ranked by where interesting results are likely to remain:
1. **Tubes:**
   - cathode interface resistance (an aged cathode's internal RC: memory on the ms scale);
   - heater-cathode leakage;
   - space charge from the electrodes' geometry (EMERGENCE_RESEARCH.md);
   - gas current;
   - microphonics.
2. **Transformers:**
   - Preisach cores instead of JA (return-point memory, no minor-loop ratcheting);
   - eddy currents diffusing through the laminations instead of lumped loss;
   - core temperature.
3. **Capacitors beyond B6:**
   - high-K ceramics' voltage coefficient and piezoelectricity (the SSL, the 1176, the
     Minimoog);
   - electrolytics as coupling capacitors with a large signal across them at low
     frequencies.
4. **Contacts and pots:** wiper noise while turning, oxidized switch contacts that rectify
   slightly. These belong with the condition dials (jank), not with defaults.

## Sources to find

- Fairchild's own 670 noise specification (bandwidth, weighting), or a measurement or
  recording of a real unit at idle.
- What dielectric C110 / C111 / C112 really are (restorers' parts lists; the drawing's
  part numbers).
- How the 670's heaters are wired (AC or DC, elevation).
- Cyril Bateman, *Capacitor Sounds* (Electronics World, 2002-2003): measured distortion of
  electrolytic, film and ceramic capacitors.
- IEC 60440 (resistor non-linearity), MIL-R-11 (carbon composition: voltage coefficient,
  noise), Allen-Bradley's hot-molded resistor data (tempco, noise index by value).

## Open decisions (the user's)

1. Start with CD0-CD2 (cheap; a few hours of renders) or wait?
2. If DA lengthens the release, is a render's dependence on minutes of history acceptable
   at production (and how is it warmed up)?
3. Should the nominal 670 carry mismatch by default (a seeded spread), or stay ideal with
   mismatch as an option?
