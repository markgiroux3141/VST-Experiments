# Neumann M 49 (CHAINS_PLAN.md WP29)

## Found (2026-11-11; third-party, git-ignored: URLs and sha256 here)

From RecordingHacks' M 49 page (https://recordinghacks.com/microphones/Neumann/M-49):

- `M49-M50-manual.pdf` (sha256 1bc104f74e2fc940dc5ab97dbbc875b8f498cf01234c00159c310b5107e51cd9),
  web: http://recordinghacks.com/pdf/neumann/M49-M50-manual.pdf: Neumann's operating instructions
  for the M 49 b / M 50 b and accessories (3 pages: technical data, the N 49 b supply, the remote
  pattern control).
- `M49-M50.pdf` (sha256 e3826ac9ba1e14f539e44ffbaf6f510e81d9403a2bae2ee34d2364f42019c1cc), web:
  http://recordinghacks.com/pdf/neumann/M49-M50.pdf: Neumann's product description of the M 49 b
  and M 50 b (8 pages: technical details, the frequency responses per pattern, the polar diagrams).
- `M49-history.pdf` (sha256 0fcf99ccf74c37c2dfe05daa354cbfc8bdc3881043582b7f3fdc66acf8beac7c), web:
  http://recordinghacks.com/pdf/neumann/M49-history.pdf: Neumann's history page.
- `m49-1.jpg`, `m49-2.jpg` (sha256 3f459bf69f53760961401d3e01b769b5ec342b792f00939cb877ffb4a2a4030c,
  3b48bd4615282df2b24df1794c0dd96c278a474ea8b1d92bc8aeaeeb57f6721a), web:
  http://recordinghacks.com/images/mic_extras/neumann/m49-1.jpg and m49-2.jpg: a cut sheet.

The AC701's sheet (Telefunken, frank.pocnet.net) is `data/datasheets/sources/telefunken_ac701.pdf`.

## The circuit diagram (supplied by the user 2026-11-11, from the walled sources below)

- `M49c-schematic.jpg` (sha256 4346bda8ebc1ab66007eb27f68c94dcf0303f7f3d7a5438224b83c302d4d312b):
  Neumann's "Kondensatormikrophon / Condenser-Microphone M49c", M49c-930-00, "gültig ab Gerät-Nr.
  2660", dated 4.12.64; statically measured voltages in ovals. **sch:** below.
- `M49-redraw-eagle.png` (sha256 b65d8277b7be989bcaf68ab4e5f15b4808664aadd35726e97a71a01133ee3ac0):
  a builder's Eagle redraw of the same circuit (pin names, R1-R12, C2-C9 as Neumann's); a
  cross-check only.

Where they came from (login or request):

```
https://groupdiy.com/threads/m49c-circuit-details-questions.80237
```

```
https://www.radiomuseum.org/r/neumann_kondensator_mikrofon_m49b.html
```

## sch: the trace (2026-11-11; config/circuits/neumann_m49.yaml)

- The capsule KK 49 (2 x 78...83 pF): the front diaphragm is the grid (R5 150M to the ground line,
  pin 3); the backplate at ca. +58 V through R2 100M from the R8 / R9 divider (1M / 1M from +116 V,
  pin 5), returned through C2 0.01u and C3 0.01u to the cal line (pin 8; R4 200 ohm to the ground
  line, C8 0.01u to +H); R3 5M from the output (the transformer's primary, after C5) into C2 / C3:
  the bass feedback (man D.12: removing R3 makes the response flat to 20 cps).
- The rear diaphragm through R1 150M from C7 0.01u, R11 100M from pin 6 (the pattern potential,
  0...116 V; R12 2M from pin 6 to the cal line), and at AC onto the grid through C1 1000p and the
  head's strap S2 (man D.13: opened, a fixed cardioid).
- C4 "ca. 8 pF abgleichen / selected" from the grid to the anode (the wire labelled "ca. 43 V").
- Rö1 AC 701 k: the anode at ca. 43 V on R10 100k from +116 V (0.73 mA), C6 800 pF anode to
  ground; the cathode at +1,6 V on R7 printed "22 kOhm" (2.2 k: 1.6 V / 0.73 mA; the Eagle redraw
  reads 2k2) with C9 25 uF / 6 V; the filament f1 on +H (pin 4), f2 on the ground line.
- C5 1 uF into Ü1 (BV 11): the primary's two halves in series (bl to bl), its cold end (rt) on the
  ground line; the secondaries strapped by S1 (200 / 50 ohm) onto pins 1 / 2.

Specification (pd p. 5, the M 49 c): 0.45 / 0.6 / 0.8 mV/ub omni / cardioid / figure-8 into 1000
ohm; 200 (50) ohm +-20%; 2 x 80 pF; 0.5% THD at >= 125 dB SPL (40 cps, 1 and 5 kcps); amplifier gain
at 1 kc/s 0 dB. Curves: pd p. 7 (on axis per pattern), p. 8 (polars at 100 Hz - 15 kHz), digitized
by scripts/digitize_neumann_m49.py (data/datasheets/neumann_m49.provenance.yaml).
