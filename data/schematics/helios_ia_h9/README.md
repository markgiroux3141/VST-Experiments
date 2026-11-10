# IA-H9 (a Helios-style mic preamp, for CHAINS_PLAN.md WP19)

Supplied by the user (2026-11-06): an EasyEDA project, IA-H9 / IA-H9M / IA-H9MR / IA-H9R
(schematic PDFs `Schematic_IA-H9*.pdf`, PCB PDFs, Gerbers, BOMs, a wiring list), by Iron Age
Audioworks. Not committed (a third party's design files; the drawing reserves its use). The user
cleared them for use as a source for WP19 (2026-11-10); `config/circuits/helios.yaml` cites the
schematic's part values, it doesn't copy the files.

It is a modern clone of the Helios Type 69 channel, not Olympic's drawing: the variants share the
mic amp, HPF, EQ and output amp; the M versions replace the output amp with a BD139 output stage
into a Jensen JT-110K-HPC and use VTB9043 / VTB9042 (Carnhill) as the EQ's inductors (L1, L2:
these are the EQ's inductors in every variant, not audio transformers); the R versions add an
input selector. **The model follows `Schematic_IA-H9.pdf` (rev 1, 2020-04-05)**, the plainest:
the Sowter 7490E input transformer and a transformerless output.

## The trace (rendered at 250 dpi with pymupdf and read wire by wire, 2026-11-10)

Rails: U1 MC7808CT from the +16VDC pin is +V (+8 V; the rev note "Added 7808 to limit voltage to
+24V": +8 over -V), the -16VDC pin through D2 1N4004 is -V (~ -15.3 V). Signal ground is
between. Each amplifier's +V is through 120R (R23, R48) with 33 uF to ground (PC4, PC6); 33 uF
from ground to -V (PC3, PC7).

Input (SW1 drives relays RL1-RL3; "Up - Mic - 2-1,5-4; Mid - Pad - 2-3, 5-4; Dwn - Line - 2-3,
5-6"): at Mic the XLR's HI / LO onto T1's primary, T1's whole secondary (its bottom grounded)
through RL2 and RL3 to C1; at Pad RL2 takes the secondary's tap instead; at Line RL1 / RL3 route
HI through R52 10K / R51 4.7K to C1 (not modelled). +48 V phantom through RP1 / RP2 6.8k from H1
(open for a dynamic mic: not modelled).

T1 Sowter 7490E: Sowter's catalog, "7490 Lustraphone M10 Input Transformer 1:10 with a 1:1 tap ...
Max input level +9dBu ... Internal electrostatic shield ... Mumetal can, 34 mm"
(https://www.sowter.co.uk/acatalog/VINTAGE-RECORDING-AMPLIFIER-TRANSFORMERS-A-to-K.html); a
GroupDIY post quoting Sowter: 1:10.5 with the tap for 200 ohm, 30 Hz low end. DCR, inductance and
capacitance unpublished: the JT-115K-E's fitted construction stands in (ssl_4000e.yaml, also
1:10).

Mic Amp 2128: C1 1.5uF into Q1's base (2N5087, PNP); C2 150 pF base to -V; bias R6 820K from a
node filtered by R10 180k / PC2 33 uF off the amp's +V, R7 680K to -V. Q1's emitter (the
feedback point) -> R12 1K -> node F -> R13 47K -> the output node O (Q3's collector). F -> C4 220
uF -> SW2 GAIN's common, each position a resistor to ground: 20 R1 56K, 30 R2 22K, 40 R3 5.1K,
50 R4 1.5K, 60 R5 460R, 70 R8 110R. Q1's collector: R9 220K to -V, R11 220R + C3 1200 pF to -V
(the compensation), Q2's base (BC550C follower, collector to +V, emitter R14 22K to -V) into Q3's
base (BC550C, emitter R16 470R || C6 220 uF to -V, collector R15 1.2K to +V). So the gain is
1 + R13 / R(GAIN) (R12 carries no signal current at high loop gain).

HPF: C5 33 uF from O to node H1; H2 ('HPF - 80', a header to a switch) shorts H1 to H2' across
C7 .15 uF (H1 -> H3) and C8 .15 uF (H3 -> H2'); R17 4.7K from H3 to the follower's output (after
C10), R18 180k from H2' to -V: a unity-gain Sallen-Key high-pass, the follower's input (C9 1.5uF
into Q4's ~25k) in parallel with R18 (so ~100 Hz, Q ~1). Q4 BC550C: base bias R19 56K from its
collector, R20 56K to -V; collector R21 680R to +V; emitter R22 3.6K to -V, C10 33 uF to the
output, R24 12.1K to ground, R25 240R to the EQ.

EQ CUT (SW7): at 1 the EQ's output, at 3 R35 27K straight from R25's node; the common onto
R36 5.1K || C43 68 pF to ground and the output amp's input A. The EQ (50 Hz cut SW3.1 with C11-
C15, bass boost SW3.2 with C16-C20 and L1's taps, mid SW4 with C32-C42 on L2's taps, PK/TR SW5,
RV1 / RV2, the 10k shelf SW6 with C21-C31 / R29-R33) is not modelled.

Output Amp 2128: the mic amp's circuit (Q5 2N5087, Q6 / Q7 BC550C; R37 820K, R38 680K, R40 180k
/ PC5, C44 1.5uF, C45 150 pF, R42 1K, R44 47K, C47 220 uF, R39 220K, R41 220R + C46 1200 pF,
R45 22K, R46 1.2K, R47 470R || C48 220 uF) with R43 8.2K as its fixed gain resistor (x6.7).
Output: Q7's collector through R49 47R .5W and C49 33 uF to HI out; LO out is C50 33 uF / R50
47R to ground (the chain reads HI out against ground).

## Measured (reports/units/helios_nominal/)

GAIN from a 150 ohm generator into 10k: 25.2 / 29.8 / 40.0 / 50.0 / 60.1 / 72.3 dB at 20-70
(the low end above its label: R1 56K gives x1.8, not x0.6). The idle output node -4.5 V
between +8 / -15.3.
