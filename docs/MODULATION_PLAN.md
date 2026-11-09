# Modulation effects: chorus, flanger, phaser, vibrato, tremolo

Started 2026-11-09 (the user: "let's go ahead and start building these"; the Leslie skipped
for now, "we don't need that complexity yet"). Old-school modulation effects as physical
circuits and machines, played as **chain ends** like the reverbs (`panel::CHAIN_ENDS`) and
printed as session inserts. Same rules as everything else: one coupled netlist per device,
every value sourced, the LFO a circuit (never a parameter curve), the swept element the real
physics (a lamp and its photocells, a JFET channel, a tape's speed, a rotating capacitor).

## The list, in build order

| # | Device | What moves | Needs | Status |
|---|---|---|---|---|
| MD1 | **Shin-ei Uni-Vibe** | a tungsten lamp's light on four CdS cells, one per phase-splitter stage | the photocell device (new), `LAMP327`, BJTs | built 2026-11-09 |
| MD2 | **MXR Phase 90** | four JFET all-pass stages swept by an LFO | JFET model (built: `2N5457@1`, `2N3819@1`) | |
| MD3 | **Tape flanging / ADT** | two tape machines, one slowed (a thumb on the flange; ADT: an oscillator on the varispeed) | the 351, VARISPEED, the reduced tape (built) | |
| MD4 | **Hammond scanner vibrato / chorus** | a rotating capacitive scanner over an LC delay line (V1-V3, C1-C3) | a time-varying capacitor element (new) | |
| MD5 | **BBD chorus / flanger** (Boss CE-1, Juno chorus, Electric Mistress) | charge passed along MOSFET buckets at a clock | a MOSFET model, the clock as a hybrid exception (HYBRID_PHYSICS_PLAN.md) | |
| MD6 | **Mu-Tron Bi-Phase**, **Bode frequency shifter** | opto-swept all-passes; Hilbert networks and ring modulators | optos, op-amps, diodes (built) | |
| MD7 | **Tube tremolos and vibratos**: Fender brownface harmonic vibrato, bias-vary tremolo, Magnatone varistor vibrato, the neon / LDR "roach" | the amp's own tubes; varistors; a neon bulb | tubes (built); a varistor model; the neon as a gas discharge | |
| MD8 | **Filters**: Vox / Cry Baby wah (a ferrite inductor), Mu-Tron III | a pedal as a control input; vactrols | BJTs, JA cores (a ferrite fit), optos | |
| — | DeArmond Trem-Trol (a liquid tremolo) | an electrode in a rocking vial of electrolyte | a model of the fluid's conduction | later |
| — | Leslie 122 / Fender Vibratone | rotating horn and drum | moving directional sources | skipped for now (the user) |

The invented ones (INVENTED_DEVICES.md P4 Filament Phaser, P8 Nickel Line Flanger) stay there.

## How they are played

A chain end today must be a reverb or a delay (`panel.rs`'s test). These get their own group,
**Modulation**, in Play's chain-end menu and the insert menu. Most are mono in, mono out; the
stereo ones (Bi-Phase, ADT panned) use `out_r` like the stereo reverbs.

## MD1: the Uni-Vibe

Sources: `data/schematics/univibe/README.md`.

- **The circuit** follows Shin-ei's as the DIY community has traced it (Aion FX's Straylight
  documentation, "the parts that were most often used in actual units throughout production",
  with its list of factory variations; its modern additions, the charge pump, the second speed
  and the rate LEDs, left out), cross-checked against the DAFx 2019 paper's drawing of a
  measured unit (Darabundit, Wedelich and Bischoff, "Digital Grey Box Model of the Uni-Vibe
  Effects Pedal"): a two-transistor preamp with a phase splitter that is stage 1, three
  Darlington-driven phase-splitter stages (15 nF, 220 nF, 470 pF, 4.7 nF), each with its CdS
  cell plus 4.7 k in series against a 1 uF blocking capacitor, an emitter follower, the
  PHASE / CHORUS-VIBRATO mixer and VOLUME; the LFO a Darlington emitter follower driving a
  three-capacitor phase-shift network with back-to-back diodes, SPEED a dual reverse-log pot;
  INTENSITY into a one-transistor lamp driver with CANCEL on its base; the lamp a 28 V 40 mA
  bulb (R.G. Keen, via Aion), our `LAMP327@1`.
- **The photocell** is a new device kind, `photocell` (`varimu/devices/photocell.py`): the
  optocoupler's CdS cell (generation, single-trap and pairwise recombination, one state node)
  lit by a lamp's filament: it senses the lamp's thermal node, and its illuminance follows
  Wien's law at the cell's spectral peak from a `lux` given at 2856 K (the standard tungsten
  source photocell sheets are specified at). The component is the PDV-P9203 (Aion's choice;
  the original cells are a custom part no one cross-references), fitted to its sheet. Each
  cell's `lux` (its place in the lamp's box) is trimmed to the DAFx paper's measured minimum
  resistances.
- **Rails** are ideal for now: 17 V audio, 21 V lamp and LFO (the DAFx paper's drawing of its
  unit); the mains supply is open.
- Open, to the user: the LDRs' rise / fall asymmetry (one state: the sheet's slower rise than
  fall is not in it, as the optocoupler's trap filling isn't), the supply.

### Status (2026-11-09): built

- **The photocell** (`varimu/devices/photocell.py`, circuitsim `devices/photocell.rs`, both
  builders; a `devices` entry's `lux` per instance, required for a photocell and refused
  otherwise; IR `Photocell`, pins (t, tb, s, ra, rb)): `PDVP9203@1` fitted to its sheet (18.3
  kOhm at 10 lux, sensitivity 0.95 for the sheet's 0.90, rise / fall both 39 ms for the sheet's
  60 / 25: one state). Tests: `tests/test_photocell.py`, `test_spice_agreement.py::
  test_photocell_agrees`, circuitsim's device fixtures.
- **The circuit** `config/circuits/univibe.yaml` (sources: `data/schematics/univibe/README.md`):
  SPEED 0.86-7.98 Hz (the DAFx unit: ~0-7.6 Hz; R52 / R53 2k2 of the factory's 1k8-4k7), the
  lamp swinging ~1200-1870 K at full INTENSITY (cut off at the bottom of a fast sweep, as Aion's
  "original LFO sweep"), C20's start voltage (`lfo_kick_v`) standing in for the power-on kick
  (the LFO's excess loop gain is only 2-4%: from an exactly balanced DC point it takes ~4 s to
  build). The cells trimmed (`scripts/univibe_trim.py --write`, rerun after a change to the
  circuit, the lamp or the cell) to the DAFx minima; not fitted and close: their means at mid
  SPEED (0.40 / 0.24 / 0.27 / 0.22 MOhm against 0.405 / 0.233 / 0.290 / 0.240); their maxima
  1.0-2.3 MOhm against 2.6-4.2. Tests: `tests/test_univibe.py`.
- **Measured** by `scripts/univibe_study.py` -> `reports/univibe/`: `rates.png` / `rates.json`
  (rate, lamp and cells over SPEED), `sweep.png` (pink noise through CHORUS: the notches arch
  to ~3-5 kHz and back each cycle with a second one lower, the paper's Fig. 9), and
  `listen/` (Dry Guitar 12 s at -18 dBFS rms through CHORUS and VIBRATO at three speeds,
  production, -23 LUFS, plus the dry).
- **In the app:** the device `univibe` (group MODULATION, a chain end and an insert), draft-1x,
  the LFO, lamp and rails on a thread of their own (`partition`): 0.61x real time mean, 40 of
  5844 blocks over budget on Dry Guitar (one solve: 0.89x, 320 over;
  `examples/load_profile.rs --device univibe`).

Open, to the user: listen (`reports/univibe/listen/`); the cells' maxima (a darker lamp at the
bottom of the sweep, or the cells' slower dark recovery: the sheet's 60 ms rise against 25 ms
fall needs a trap state); the mains supply (the rails are ideal); the LDR's per-strike memory
("light history") isn't modeled.
