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
