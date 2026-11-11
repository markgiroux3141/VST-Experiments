# The Crown PZM-30D (CHAINS_PLAN.md WP26)

## Sources (found 2026-11-11; the PDFs are git-ignored: URL and sha256 here)

- AKG / Crown, "PZM30 D" operating manual (Harman, 2015), 2 pp.:
  https://support.harmanaudio.com/on/demandware.static/-/Sites-masterCatalog_Harman/default/dwe57280aa/pdfs/AKG_PZM30D_Manual.pdf
  (`akg_pzm30d_manual.pdf`, sha256 63850920091d6ca0e45893045768415e1c3fe4ad0128341af67d92037e42dc00).
  p. 1: the specifications and Fig. 1 (the frequency response, RISING and FLAT, "measured on an
  'infinite' boundary"); p. 2: **the PZM30 D schematic** (topology only, no values), the placement
  notes (the low end shelves below F = 750 / D, D the boundary's size in feet).
- AKG, PZM-30D / PZM-6D cut sheet (Harman):
  https://support.harmanaudio.com/on/demandware.static/-/Sites-masterCatalog_Harman/default/dw085e2bb5/pdfs/AKG_PZM30D_PZM6D_Cutsheet.pdf
  (`akg_pzm30d_pzm6d_cutsheet.pdf`, sha256 92d03003112528d0503c18b1a9b6e5651879e090c33b4a5fd66c65808a2309c0):
  the same figures; the plate 6 x 5 x 0.75 in.

The figures (manual p. 1): electret condenser; 20 Hz-20 kHz; hemispherical on a boundary; 7 mV/Pa
open circuit (-43 dB re 1 V/Pa); 240 ohm balanced, minimum load 1000 ohm; self-noise 20 dB(A); 150 dB
SPL at 3% THD (open circuit); phantom 12-48 V, 1.1 mA; positive pressure gives positive pin 2.

## The schematic (read 2026-11-11 from a 400 dpi render of p. 2)

The microphone capsule (its own can): the electret capsule on the gate of Q1, a JFET source
follower inside the capsule's housing: drain B+ (RED), source AUDIO (ORG) with a resistor to the
capsule's ground (GRAY). The electronics: ORG -> C1 (electrolytic, + to the transformer) -> T1's
primary (GRN), its other end (BLK) through R7 to GRAY; R1 from ORG to pin 1 (the source's DC load);
the RISING / FLAT switch from ORG through C4 and a second "R7" to GRAY (closed = FLAT: a shunt that
lowers the top); T1's secondary (BLU pin 2, RED pin 3) with R4 / R5 across it, their junction the
phantom's centre, joined to B+; R2 from B+ to GRAY, R3 from GRAY to pin 1, C2 across R2 and C3 across
R3 (the capsule's ground sits on a divider of the phantom supply). No value is printed: everything
is inferred (the user's rule of 2026-11-10 for walled drawings: provisional values fitted to the
published figures; CHAINS_PLAN.md WP26's Decisions).
