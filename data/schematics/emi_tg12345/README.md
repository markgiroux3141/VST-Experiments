# EMI TG12345 (CHAINS_PLAN.md WP20)

- `TG 12345 Mk II.txt` (supplied by the user, 2026-11-06; the text of the EMI TG12345 Mk II
  Handbook, as on manualmachine.com; sha256 271f667dee67d021e6dd0acc56218a05567cd66f8bc66ae9e059199aa7bb39b5;
  not committed: EMI's document). What it gives for the mic channel:
  - 3.2: each input has a screened input transformer, **step-up 1:3.16**, primary from a 200
    ohm source; 3.3: 50 V phantom through a pair of 6.8k resistors matched to 0.5%.
  - 3.4.1: the coarse input level control, 12 steps of 5 dB: the first three from taps on the
    transformer's secondary, the rest a resistive potentiometer of 8.33 kohm total.
  - 3.4.2 / 12.27: the input amplifier is **Amplifier D** (drawing BE232), nominal **25 dB**
    voltage gain, a fine gain control +-5 dB in 0.5 dB steps (0 to 1.2 kohm from the gain
    terminal to 0 V, through C6 / R8 from VT1's emitter); AOT1 sets 20 dB with 1.2k in;
    direct-coupled output, in phase, >= 1.4 V rms into 3k.
  - 12.3: Amplifier D's forward path is Amplifier A3's (drawing AE.203): three d.c.-coupled
    transistors, VT1 and VT2 voltage gain, VT3 an emitter follower; overall feedback from a
    tap across the output to VT1's emitter; gain ~ (R5 + R6 || AOT1) / (R6 || AOT1); C2 and C5
    against r.f. oscillation.
  - 3.4.3: -10 dBV nominal at Amplifier D's output; the input range +20 to -50 dBV.
  - 2.4.8: mixer inputs measured from a 200 ohm source; outputs ~200 ohm into >= 2k.
- **Missing: the component values** (drawings BE232, AE.203: the text names them but doesn't
  reproduce them) and the input transformer's figures beyond its ratio. Forum figures (not
  verified, GroupDIY "EMI TG mic preamp schematic"): input stage BC109 / BCY71 (later BC184 /
  BC214), 0.47 uF input coupling, ~390k base to ground, 75k collector, 8200 pF collector to
  ground, a 43k second-stage collector, ~75 dB overall.

## What `config/circuits/emi_tg12345.yaml` infers (2026-11-10, CHAINS_PLAN.md WP20)

The topology is the handbook's (3.2, 3.4.1, 12.3, 12.27); the forum's figures are provisional
values (0.47 uF, 390k, 75k, 43k); what neither gives is derived or fitted: R6 || AOT1 3883
and R8 356.5 from hb 12.27's 20 dB at 1.2 kohm and the control's +5 dB at 0; the FINE positions
(1 dB steps, not the A191's 0.5 dB) from the same arithmetic; COARSE's taps at -5 / -10 / -15
dB of the secondary and the 8.33 kohm ladder across the -15 dB tap in 5 dB steps; VT1's
emitter resistor for the direct-coupled output at 0 V DC. The forum's 8200 pF slewed VT1's ~10
uA at 20 kHz, so C2 is 470 pF (the handbook: "against r.f. oscillation"). Measured
(reports/units/tg12345_nominal/): 34.8 dB at COARSE 0 / FINE 0 (29.8-39.8 over FINE), COARSE
5 dB a step to -20.4 dB, flat to -0.1 dB at 20 kHz, 1% THD at +13.8 dBu out into 3k, output
0.35 ohm, input 16 kohm at 1 kHz (4.2 kohm at 40 Hz: the provisional primary inductance).
