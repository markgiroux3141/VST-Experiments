# Telefunken ELA M 250 E / 251 E (for CHAINS_PLAN.md WP18)

The only drawing found is `elam250_2.jpg` (368 x 550 px): AKG's "Kondensator-Mikr. ELA M 250 E,
ELA M 251 E", Z. Nr. 1524 Sch 2 f, dated 2 Jan. 1961 (Akustische- u. Kinogeräte, Wien). A legible
copy can't be had (the user, 2026-11-10: don't ask again); WP18 is built by inference (the user's
decision), every value sourced as below.

## Read from the drawing (upscaled 3-4x, 2026-11-10)

The amplifier ("Verstärker f. ELA M 250 E u. ELA M 251 E"): B+ enters at the 7-pin connector's
pin 5 onto a node with R10 (the anode load, down to a1) and R3; R3 to a node with R4 to ground;
R2 from there to the capsule's polarization terminal, with C1 to ground. The capsule's signal
terminal to g1; R1 the grid leak to ground. The cathode k1 through R11 with C4 across to
ground (cathode bias, unlike the C12's grounded cathode); the second section unused. From a1: C2
to ground and C3 to Ü1's primary; Ü1's two secondaries strapped 50 / 200 ohm by links (pins 4 /
1).

The parts list (legible rows): R1 30 MOhm 1/2 W; R2 8 MOhm 1/4 W; R3 0.5 MOhm 1/10 W; R4 0.5
MOhm 1/10 W; R8 200 ohm 1/3 W (struck through); R9 30 MOhm 1/4 W (marked for the 251's head);
R10 0.1 MOhm 1/4 W; R11 1.8 kOhm 1/8 W; Rö 6072; Ü1 T14/1; C1 4000 pF / 350 V ceramic; C2 100
pF / 500 V ceramic; C3 1 uF / 160 V electrolytic; C4 20 uF / 6 V electrolytic; C5 1000 pF / 125 V
Styroflex. Not legible or not listed: R5-R7, C6.

The capsule heads ("Kapsel f. ELA M 250 E", "... 251 E"): the CK12's four terminals onto a
three-deck switch (the 251 E's with R9 and C6 on its first deck; the arrows "O / 8" for the 250
E, "O / 8 / B" for the 251 E: omni, figure-8 and cardioid ("Breite"? the third pattern). The
wiring of the decks can't be followed at this resolution.

## What is inferred (CHAINS_PLAN.md WP18's Decisions)

- The capsule `CK12@1`, as the C12 (the 251 used AKG's CK12).
- The polarization: B+ / 2 by R3 / R4 (equal), through R2 8 MOhm with C1 4000 pF (the drawing),
  onto the backplate through R9 30 MOhm (inferred: R9 is the head's only resistor), C5 1000 pF
  from the backplate to the grid (as the C12's C13 1000 pF). The front diaphragm at ground.
- The three patterns as the C12's equivalent polarizations: the rear diaphragm at the front's
  (omni), at the backplate's (cardioid) and opposite (figure-8: the rear at B+, an inferred
  wire; the head's decks aren't legible). `akg_c12.yaml`'s positions 0 / 4 / 8.
- B+ 120 V at the microphone (the C12's brochure's 120 V plate voltage, `akg_c12.yaml`): the
  251's supply isn't documented here. Ideal.
- T14/1 as `akg_c12.yaml`'s (Haufe's sheet; its gap fitted there), strapped 200 ohm.

## Published figures (references)

- Sensitivity: 10 mV/Pa for an original ELA M 251 (web: https://micpedia.com/?p=6678); the
  reissue (Telefunken Elektroakustik's ELA M 251E): 17 mV/Pa +-1 dB, 200 ohm, 130 dB SPL at 1%,
  9 dBA (web: https://www.thomann.de/gr/telefunken_ela_m_251e.htm, studiocare.com).
