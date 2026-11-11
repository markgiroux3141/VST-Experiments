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
