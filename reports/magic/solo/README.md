# AM13 step 1: solo a part

2026-11-13, `scripts/solo_part.py` on `varimu/magic/solo.py`. Tests: `tests/test_magic_solo.py`.
For each resistor, capacitor and inductor, the output's sensitivity to its value,
s = d out / d ln(value), by central differences at ±0.5 % (checked at ±2 %). Fixed steps,
Newton at 1e-9, noise and heaters off, cores linear. "Solo" is s's level re the output: what
the output gains per unit of relative change of that part. -6 dB means a 10 % change of the
part moves the output by about 5 % of itself. "check" is s(2 %) - s(0.5 %) re s. A **flag**
(above -30 dB) means the part's effect is not linear over that range or lies under the
numerical floor. Every flagged row here is under -140 dB, so it is the floor.

Each folder has `ranking.md` (all parts), `summary.json`, and `audio/`: the top ten solos at -23
LUFS, plus "what if" pairs, the output as is and with that part 20 % up (first order),
loudness-matched.

Steps 2 (the engine's adjoint) and the app feature were skipped by agreement.

## triode_stage (2 s of Dry Guitar)

Every part is provisional, and the ranking is the order to source them in: the plate load RP
-11.9 dB, the grid leak RG -16.6, the next stage's leak RL -17.3, then RK, RS, CI and CO
around -20, and the cathode bypass CK -30.3. Self-checks -69 to -79 dB.

## pultec_eqp1a (5 s of Dry Guitar)

| Rank | flat panel (`pultec_eqp1a/`) | LF and HF BOOST at 0.5 (`pultec_eqp1a__lf_boost=0.5__hf_boost=0.5/`) |
|---|---|---|
| 1 | RHBb -1.0 (high boost pot, the leg in circuit) | RIN_TERM -5.7 (620 ohm across the input transformer) |
| 2 | RHAb -1.5 (high atten pot) | Rsrc -6.7 (the 600 ohm source) |
| 3 | RIN_TERM -5.7 | RK1 -7.3 (820 ohm between the cathodes) |
| 4 | Rsrc -6.7 | RLB -7.5 (low boost pot) |
| 5 | RK1 -7.3 | RHBa / RHBb -7.7 (high boost pot, both legs) |
| 6-7 | RFBA / RFBB -13.5 (the feedback winding's 360 ohm) | RHAb -8.4, then RFBA / RFBB -13.5 |
| | | **CLB330 -19.4, CLB60 -22.9** (the LF boost's capacitors, switched in) |

- **Every part that matters is sourced** (drawing, manual or redraw), on both panels. The only
  provisional values are the power transformer's HV winding, RPCCA/B, LPCCA/B and CPCCA/B,
  all 86 dB or more under the output. Nothing in the EQP-1A needs sourcing for its sound.
- **The most audible interpreted value is CLB330** (330 nF, "dwg-interp": the redraw's
  reading of where it is wired), at -19.4 dB boosted. If one value deserves a second look at
  the drawing, it is that one.
- **The pots dominate.** On the flat panel the high-boost and high-atten pots' legs set the
  flat path's loss. The boosted panel spreads the sensitivity over the boost pots and the LF
  network. The cathode and feedback resistors set the gain on either panel.
- **The HF boost inductor barely matters on this program** (LHB33 -63 dB at 10 kHz boost):
  guitar has little there. The ranking is per program. Rank again with a brighter source
  before sourcing the inductors.

**A gap in the tool:** 43 rows show no source. Those are the transformers' internals (winding
resistance, gaps, cores, leakage), whose values come from the circuit's transformer blocks,
and the switched networks' parts (CLB60, CHB82, LHB33, ...), which sit inside a switch's
`network` and aren't mapped by `solo.sources`. Their values are sourced in the circuit file;
the tool just doesn't find the text.
