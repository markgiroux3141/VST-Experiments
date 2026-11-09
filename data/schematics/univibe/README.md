# Shin-ei / Univox Uni-Vibe: sources

The circuit `config/circuits/univibe.yaml` (docs/MODULATION_PLAN.md, MD1) is drawn from these.

| File | What | Source |
|---|---|---|
| `aion_straylight_documentation.pdf` | Aion FX, *Straylight Chorus/Vibe* documentation 1.0.4 (2026-08-21): a direct clone of the Uni-Vibe circuit, its schematic (p.15), parts list (pp.5-8) and "Part variations" (p.13: the factory values of the units Aion has seen, and where the factory schematic is wrong) | web: https://aionfx.com/app/files/docs/straylight_documentation.pdf |
| `straylight_preamp.png`, `straylight_stages_1_2.png`, `straylight_stages_3_4.png`, `straylight_lfo.png`, `straylight_lamp_driver.png` | p.15 rendered at 5x (PyMuPDF), the regions the circuit file was traced from | derived from the above |
| `dafx2019_darabundit_univibe.pdf` | C. Darabundit, R. Wedelich, P. Bischoff, "Digital Grey Box Model of the Uni-Vibe Effects Pedal", Proc. DAFx-19, Birmingham 2019 (CC BY 3.0): an original unit measured. Fig. 2 (the whole circuit), Fig. 3 (a phase stage, +17 VDC), Table 1 (each stage's C_p, inverting / non-inverting gains, each cell's average, minimum and maximum resistance), the LFO's range (toe to heel ~0-7.6 Hz) | web: https://ccrma.stanford.edu/~champ/files/DAFx2019_paper_31.pdf |
| `dafx2019_fig2_lfo_lamp.png` | its Fig. 2's LFO and lamp sections at 10x: the LFO a Darlington (QO1 / QO2), the lamp driver one transistor, +21 VDC | derived from the above |

Not fetched: R.G. Keen's "The Technology of the Univibe" (geofex.com: the site reset the connection;
the Wayback Machine refused the client). Aion quotes it for the lamp (28 V 40 mA, our `LAMP327@1`).

## What the circuit takes from where

- **Topology and values:** Aion's schematic, with the original's value wherever p.13 names one and
  its own additions left out (the charge pump and 15 V regulator, the second SPEED pot and its
  footswitch, the rate LEDs, the OFFSET / GAIN / PHASE trimmers and the 2.2M input option): R46
  150 ohm to ground, R48 100k collector to base with R47 47k (p.11), R12 = R13 = 100k (p.11), R45
  4k7 (p.13: "incorrectly listed on the factory schematic as 47k"). R52 / R53 are 2k2 (p.13: "often
  4k7 and sometimes 1k8, 2k or 2k2"), the value that puts the top speed at the DAFx unit's.
- **Cross-checked against the DAFx drawing:** stage 1 driven by the preamp's last transistor, not a
  Darlington; the Darlington LFO; one lamp transistor; the rails (+17 V audio, +21 V lamp / LFO).
- **The cells:** a custom Shin-ei part (Aion p.9: "no cross reference to a standard manufacturer part
  number"); the PDV-P9203 that Aion specifies stands in (`config/components/pdvp9203/1.yaml`, fitted
  to `data/datasheets/photocell/advanced_photonix_pdv_p9203.pdf`). Each cell's light coupling is
  trimmed to DAFx Table 1's measured minimum (`scripts/univibe_trim.py`).
- **Transistors:** 2SC828 (Q2-Q12) and 2SC539 (Q1) in the original (Aion p.12); the BC550C stands in.

## Missing

- The original's mains supply (a transformer and a half-wave rectifier, Aion p.3): the rails are
  ideal.
- Shin-ei's own service schematic (Aion: it "differs from many of their own production units").
