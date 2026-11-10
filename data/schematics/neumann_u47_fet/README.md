# Neumann U 47 fet (CHAINS_PLAN.md WP25: built 2026-11-10, `config/circuits/neumann_u47_fet.yaml`)

## Sources (via RecordingHacks, https://recordinghacks.com/microphones/Neumann/U-47-fet)

- `U47FET-schematic.png`: Neumann's circuit diagram "Kondensator-Mikrophon U 47 fet" (U 47 fet /
  U 47 fet i), web: http://cdn.recordinghacks.com/images//mic_extras/neumann/U47FET-schematic.png.
  DC voltages printed at most nodes (+46.5, +45, +43, +41.3, +40.7, +22.4, +21.5 V): an idle test.
- `U47FET-manual.pdf` (operating instructions, scanned), `U47FET-parts.pdf` (parts list).

## Readings so far (2026-11-10)

The capsule (72 pF; the K47's cardioid in the U 47 fet: `K47@3` exists) between contact 7 and
ground (3); its signal side through R1 1G from the polarization line (a, WS: R8 10M and R16 10M
from +46.5 V); C1 2200p onto T1's gate (node 1; T1 8280800022.4, a selected FET). The gate leak
R3 100M || C3 33p from node 2, node 2 through R2 220M || C2 18p from the +21.5 V line (b, RT:
bootstrapped). S1 (-10 dB) and S2 (the bass cut, R4 68M, R5 33M) rearrange that network (not yet
read contact by contact). T1's source into T2 (BC212B) and on through T3-T7 (BC182B / BC212B),
Ue1 90331, S3 (-6 dB at the secondary), R18 / R19 6k8, R20 / R21 680k (paired), R22 / R23 56,
C12 / C13 100p; R6 6k8, C4 0.1u, C5 2.2u, R7 4M7, R8 10M, R9 3M3, R10 47k, R11 470k, R12 430k,
R13 470k, R14 4k7, R15 47k, R17 100k, C6 0.33u, C7 4.7u, C8 20u, C9 0.1u, C10 / C11 1u.

Next: the rest of the loop at a larger zoom (T2-T7's connections), then a hand-written circuit
checked against the printed voltages; BC182B / BC212B by the BC550C / BC560C (same family).

More readings (2026-11-10, the drawing's right half):

- Phantom: the output pins through R22 / R23 56 to R18 / R19 6k8 (paired); their junction feeds
  T7 (BC182B) at its collector (+45 V): T7 an emitter follower, +43 V at its emitter, its base on
  R17 100k from the collector and R15 47k from the emitter, C11 1u from the base to ground (a
  filtered +43 V rail).
- Polarization: R20 / R21 680k (paired) from the output pins to +46.5 V, R16 10M, R8 10M to the
  line a (the capsule's R1 1G).
- C12 / C13 100p from the pins to the shield (RF).
- Ue1 90331: the primary between RT and BR with its two WS taps joined (a centre tap); BR to R13
  470k and C10 1u; the secondary (BL / GE / GN / VI) split, S3 (-6 dB) re-wiring its halves.
- T5 (BC212B) from +43 V (R14 4k7 at its emitter, +41.3 V), its base on R10 47k / C7 4.7u (+40.7
  V); T3 (BC182B) on node c (T1's drain) from +43 V, R9 3M3; T4 (BC182B, +22.4 V at its
  collector through R7 4M7, +21.5 V at its emitter with C8 20u); R11 470k, R12 430k a divider;
  T6 (BC182B) on node e; C6 0.33u, C9 0.1u.

Still to read: which transistor drives the primary's RT (the b line at +21.5 V) and the loop's
feedback path (R9, R11 / R12, R13) node by node.

## The loop, traced (2026-11-10, the drawing upscaled 2x)

- T1's drain on node c to **T3's emitter** (T3 a cascode: collector +43 V, base on R9 3M3 from the
  +40.7 V node, C6 0.33u to ground); T1's source to **T2's emitter** (BC212B, a common base: its
  base node d on R7 4M7 from +40.7 V and C5 2.2u to ground, +22.4 V; its collector node e on R6
  6k8 to ground).
- **T6** (BC182B) common emitter from node e, emitter at ground; its collector is line b (RT,
  +21.5 V) with **T5** (BC212B: emitter R14 4k7 from +43 V, +41.3 V; base +40.7 V, C7 4.7u to
  +43 V) as its current-source load. Ü1's primary RT - (WS = WS) - BR; BR to C10 1u to ground and
  R13 470k to T4's base.
- **T4** (BC182B) the DC servo: base on R13 with C8 20u to its emitter, emitter on the R11 470k /
  R12 430k divider from +40.7 V, collector on node d (T2's base).
- The overall feedback: line b through R2 220M || C2 18p to node 2, R3 100M || C3 33p to the gate
  (node 1). S1 (-10 dB): one pole shorts R2 || C2 (b to node 2), the other R4. S2 (bass cut): R4
  68M and R5 33M from line b to the gate (resistive feedback).
- T7 (BC182B) a filtered follower: collector +45 V (R18 / R19 from the pins), base on R17 100k
  from the collector and R15 47k from the emitter, C11 1u to ground; emitter +43 V.

## Neumann's data (references)

8 mV/Pa (-42 dBV +-1 dB, 1 kHz, into 1 kohm), rated impedance 150 ohm, rated load 1000 ohm, 137 dB
SPL for < 0.5% THD (147 with the pad), 18 dB-A (web: https://www.fullcompass.com/common/files/22068-NeumannU47fetBrochure.pdf,
https://www.neumann.com/en-de/products/microphones/u-47-fet-i).

## Built

The circuit idles within 3% of every printed voltage (line b 20.8 V against 21.5). Ü1's ratio
fitted to 8 mV/Pa: 0.1274; then 153 ohm, 0.05% THD at 137 dB SPL, the pad -9.0 dB, the K47's
response +4.2 dB at 10 kHz (its presence peak), -20 dB at 180 deg.
