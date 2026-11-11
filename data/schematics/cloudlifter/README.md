# The Cloudlifter CL-1 (CHAINS_PLAN.md WP27)

## Sources (supplied by the user 2026-11-11; third-party, git-ignored: sha256 here)

From the GroupDIY Cloudlifter threads (login):

```
https://groupdiy.com/goto/post?id=1123046
```

```
https://groupdiy.com/threads/cloudlifter-cl-1repair.78404/page-2
```

- `CL1-traced-schematic.png` (sha256 1cd64757dddf8f352ae233a39028a6fbea17c90094ecb6a0497287f98bc1645a):
  a traced CL-1 as a simulator schematic, two versions side by side. Left (the original JFETs):
  per leg an input JFET (J1 / J3) common source with R1 / R2 22 ohm to a shared R3 39 ohm to ground,
  a cascode JFET above it (J4 / J2) whose gate is on the input FET's source, the drain (Out+ / Out-)
  on R6 / R7 6.8k from 48 V (the downstream preamp's phantom feed); the inputs with R4 / R5 33k and
  C1 / C2 3.3 nF to ground; the test source V2 through R8 3.0k (the 3k input of Cloud's
  specification). Right ("new FETs", JFE140 for X1 / X3): the same, the shared source resistor R11
  62 ohm. The JFET part numbers of the original aren't printed.
- `CL1-traced-sim-response.png` (sha256 23b69f4dcc9b13a32f64a77b0de12c505aab2acb5949d46e019fee7222f80f1c):
  that schematic simulated ("Cloud_CL-1_new_Fets.CIR"): 29.9 dB (original) and 29.4 dB (new FETs)
  out of each output, flat to ~20 kHz, -0.1 dB at ~40-50 kHz.

Cloud Microphones' own figures (web: https://www.cloudmicrophones.com/cloudlifter-cl-1): up to
+25 dB, phantom not passed to the microphone, a class-A discrete JFET amplifier powered by the
phantom supply; retailers: two gain stages of four hand-matched JFETs, a 3k input load. The
traced schematic's simulated 29.9 dB is per output against ground; balanced, into a preamp's
input, the gain depends on that input's load: to be checked when built.

## The JFETs (found 2026-11-11)

GroupDIY's teardown and repair threads (web: https://groupdiy.com/threads/cloudlifter-cl-1repair.78404,
https://groupdiy.com/goto/post?id=1123031): two Linear Systems LSK389 duals (the first with a 33k
and a capacitor at the input). Linear Systems' cards for the four grades:
data/datasheets/transistors/linearsystems_lsk389_models.pdf (its README row). The grade isn't
known: the A grade gives the traced schematic's simulated gain (28.3 dB per output unloaded
against its 29.9; B 31.3, C 32.5, D 33.4 by the card's square law), `LSK389A@1`.

## Built (config/circuits/cloudlifter.yaml)

The traced left (original) version on LSK389A; the mic's floating output as +-v / 2 on the gates
(controlled sources; the legs' 66k / 1.65 nF in series as the mic's load); the downstream preamp's
phantom feed (IEC 61938 P48, 6.81 k a leg), 47 uF blocking capacitors, each leg loaded by half the
clean preamp's 10 k, the output the legs' difference. 1.40 mA a leg, 26.8 dB into the 10 k (Cloud:
"up to +25 dB"), 0.1% THD at 50 mV peak in, 1% at 100 mV.
