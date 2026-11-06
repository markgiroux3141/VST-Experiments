# Device candidates: what to build next

First brainstormed with the user on 2026-10-28 (guitar amps and the V76). Rewritten
2026-11-06 for compressors and EQs, also with the user. That brainstorm set the next
work: **dynamics and EQ**, below. This file lists popular audio devices that suit the
app, what each needs that we don't have, and how well its schematic can be sourced. A
device that gets started becomes a milestone in
[DEVICE_BUILDER_PLAN.md](DEVICE_BUILDER_PLAN.md) (B9 the 5E3, B10 the V76, B11-B13
below), its sources in `data/schematics/<device>/`.

The ground rules are unchanged (CLAUDE.md "Hard rules"):
- every value has a `source`;
- the genome is physical only;
- one coupled simulation;
- two implementations per device model;
- everything seeded.

Facts below come from model knowledge or web listings unless a source is given. Confirm
each on the schematic before it goes into a circuit file.

## Decisions

**2026-10-28 (the user's):** the first devices are guitar amps and the Telefunken V76.
The LA-2A, which had been proposed next, dropped behind them. The 5E3 came first because
its sources were at hand. The 5E3 and the V76 became B9 and B10 (2026-10-29), worked
together with the component editor.

**2026-11-06 (the user's): next, a compressor for each job and the EQs that go with
them.** The user asked for:
- a compressor good for snappy attacks on drums;
- a compressor good for sidechain pumping: a sawtooth ducked by the kick, as on Benny
  Benassi's *Satisfaction*.

The order:
1. **B11, the SSL G-series bus compressor, keyed:** pumping and the drum bus. Its gain
   cell is a Blackmer VCA built from our BJTs.
2. **B12, the JFET model and the UREI 1176 Rev A:** snappy drums. The JFET model is
   CHAINS_PLAN.md's WP21; whichever plan gets there first builds it.
3. **B13, the Neve 1073 with its EQ:** the first BJT EQ. It is CHAINS_PLAN.md's WP11,
   so it also opens three mic chains.

Everything else stays a candidate in "The rest of the list".

## Next: dynamics and EQ

### Why the 670 doesn't pump, and what does

The keyed 670 (SIDECHAIN_PLAN.md K1-K3) showed the problem. In a feedback compressor the
detector reads the compressor's own output, so the ratio comes from the loop closing
through the gain cell. An external key doesn't pass through the gain cell, so the loop
never closes. Keyed, the 670 has no ratio, only a cliff: -2 to +2 dB of key spans a 4 dB
duck down to the 6386s cut off. DEPTH (a clamp on the CV line) made it usable, at
roughly -3 to -10 dB.

Pumping needs a duck whose depth in dB follows the key's level in dB at a set ratio, and
a recovery that sounds like a swell. Two topologies give that:
- **Feedforward:** the detector reads the key directly, and the gain cell's law turns
  its level into dB of gain reduction. The dbx 160 is built this way: decilinear VCA,
  RMS detection, feedforward (web: https://www.mixonline.com/technology/birth-of-a-classic-the-dbx-160-compressor).
- **A loop inside the sidechain:** the detector reads a second gain cell, fed from the
  input (or the key) and driven by the same control voltage. The loop then closes around
  the key, so a keyed unit keeps its ratio. This is how the SSL bus compressor is
  described:
  - SSL's Bus+ manual: a feedback sidechain fed from a feedforward tap, with a switch
    moving the tap after the main VCA (web: https://vintageking.com/blog/exploring-the-ssl-the-bus-stereo-bus-compressor/);
  - Bonedo's G Comp review: the detector at an auxiliary VCA's output, ahead of the
    signal VCA (web: https://www.bonedo.de/artikel/ssl-g-comp-bus-compressor-test);
  - other writers call it feedforward (web: https://fr.audiofanzine.com/compresseur-de-studio/ssl/the-busplus/).

  The schematic settles which (B11 step 1).

Either way, the gain cell turns its control voltage into dB, and the control voltage is a
release capacitor discharging through its resistor. So the gain recovers exponentially in
dB, with the RELEASE network's RC, whatever the depth: the swell after each kick. In a
VCA compressor it comes from the circuit, not a curve. (Corrected 2026-11-06: an earlier
version of this section said "linear in dB"; that needs a constant-current discharge,
which the SSL doesn't have.)

### B11. The SSL G-series bus compressor, keyed (pumping, the drum bus)

What it is (published, to confirm on the schematic):
- a stereo VCA compressor on one shared sidechain;
- ATTACK 0.1 / 0.3 / 1 / 3 / 10 / 30 ms; RELEASE 0.1 / 0.3 / 0.6 / 1.2 s and AUTO;
  RATIO 2 / 4 / 10;
- the 30 ms attack with a fast release is the classic "drum bus snap", and a hard ratio
  with the release on the beat is the dance-music pump.

The gain cell was dbx's Blackmer VCA, later THAT 2150 / 2180-series ICs. SSL's reissue
uses THAT 2181s with a VCA inside the sidechain's loop (web:
https://www.mixonline.com/technology/news-products/ssl-launches-bus-comp-classic-unit).

**The physics-first point.** DEVICE_CANDIDATES.md's 2026-10-28 version dismissed IC VCAs
as black boxes. They aren't, once the BJT model exists. A Blackmer cell is a log /
antilog circuit of matched NPN and PNP pairs. Its gain is exponential in the control
voltage through kT/q: about 6 mV per dB at room temperature, to confirm on THAT's sheet.
Its distortion comes from:
- the pairs' mismatch: IS between halves, the even-order part, which the real units
  trim with a SYMMETRY pot;
- their ohmic resistances;
- their thermal tracking.

All of these are physical part values: a genome, not a curve.

Steps:
1. **Sources.** In `data/schematics/ssl_bus_comp/`:
   - the bus compressor card's schematic (the console's service documentation; GroupDIY
     clone threads, fetched by the user if walled, per the memory rule);
   - the dbx 202 / 200 VCA's schematic (GroupDIY's dbx202.pdf, web:
     https://groupdiy.com/threads/dbx-160vu-clone.30006/page-9);
   - THAT 2150 / 2180 / 2181 datasheets (internal structure, control constant,
     distortion vs trim).

   Settle the topology question above. Decide, with the user, which version is built:
   the 202-era original or the THAT-era card.
2. **The BJT at temperature.** `varimu/devices/bjt.py` is at TNOM only ("no
   temperature"). The cell's gain law needs SPICE's temperature scaling of Vt, IS (XTI,
   EG) and BF (XTB): an instance's junction temperature as a parameter, both builders,
   SPICE via `.temp` / the instance's TEMP, agreement tests. A matched pair in thermal
   contact shares one temperature.
3. **The Blackmer cell** as a macro part (`blackmer_vca: [in, out, ec_plus, ec_minus]`
   or similar): the matched pairs as `bjt` parts with a seeded mismatch and the
   SYMMETRY trim. Checked against THAT's published figures:
   - the control constant, 0.0 dB at Ec = 0;
   - THD vs gain, trimmed and untrimmed;
   - the noise floor once BJT shot noise exists (B5's noise has none for BJTs yet; an
     open item, not a blocker).
4. **The detector and the time constants:** the card's rectifier, its log converter and
   the ATTACK / RELEASE / AUTO switching. The op-amps are the `opamp` part (WP4's single
   pole). If the card's op-amps shape the sound (slew on the detector), that is the
   reason to build them from BJTs later.
5. **The circuit** `config/circuits/ssl_bus_comp.yaml`, stereo, one netlist. Its profile:
   - GR curves per ratio;
   - attack and release against the panel's figures;
   - THD vs GR;
   - the AUTO release's two time constants.
6. **Keyed.** A KEY jack into the detector as a control input (`key`), INT / EXT, the way
   `scripts/derive_keyed_670.py` derives the 670's. Then K2 / K3's machinery (prints with
   a sidechain, the KEY row) applies unchanged.

   **Done when:**
   - a kick keys a held tube_synth sawtooth (a session print);
   - the duck's depth in dB follows the key's level at the set ratio within the profile's
     tolerance;
   - the recovery follows the RELEASE network's RC at every depth;
   - the user hears the pump.
7. **The app:** a Play device `ssl_bus_comp` and an insert, its load measured
   (`examples/load_profile.rs`) before any live claim.

### B12. The JFET model and the UREI 1176 Rev A (snappy drums)

What it is:
- the FET compressor: a JFET as a voltage-controlled resistor in a shunt attenuator,
  then a gain stage;
- attack 20 µs to 800 µs (web: https://en.wikipedia.org/wiki/1176_Peak_Limiter);
- RATIO 4 / 8 / 12 / 20, and "all buttons in" (a side effect of the ratio switch's
  wiring, which a netlist reproduces by itself);
- the FET's distortion rises with gain reduction.

Rev A ("blue stripe", 1967) is the first and has an input transformer; Rev C was Brad
Plunkett's redesign; Rev D-F are the LN versions. The revisions' schematics differ, and
GroupDIY compares them (web:
https://groupdiy.com/threads/1176-plosives-looking-for-rev-a-schematic-or-high-res-internal-shots.34502/page-5).

Steps:
1. **The JFET model** (CHAINS_PLAN.md WP21, the same work):
   - Shichman-Hodges (SPICE's level 1 JFET: BETA, VTO, LAMBDA, IS) with both drain-source
     polarities, because a FET used as a resistor passes audio both ways;
   - a Python reference, SPICE's native `J`, circuitsim's port, both builders;
   - fitted to the 1176's part's datasheet (the type to confirm on the schematic, e.g. a
     2N3819 / 2N5457-class device).
2. **Sources** in `data/schematics/urei_1176/`: the Rev A schematic and the manual
   (attack, release, ratio figures). Pick the revision with the user: Rev A by default
   ("blue stripe", the input transformer), an LN revision as a second file.
3. **The circuit** `config/circuits/urei_1176.yaml`:
   - its transformers as designs (C2) or from replacement datasheets;
   - the BJT gain stages on `bjt` parts.

   Its profile:
   - GR per ratio, all buttons in included;
   - attack and release against the manual;
   - THD vs GR;
   - the overshoot on a drum hit.
4. **Keyed**, as B11 step 6 (the 1176 is also a classic pumper at all buttons in), and
   the app's device and insert.

**Done when:** the profile meets the manual's figures or says why not, a drum loop
through it is printed, and the user hears it.

### Status (2026-11-06)

**The prerequisites are built:**
- **The BJT at temperature:** a `devices` entry's `temp_c`. SPICE's scaling (TLEV 0) of
  Vt, IS, BF, BR, ISE, ISC, with EG / XTI / XTB from the component file, SPICE's defaults
  when absent. Python, circuitsim and both builders; ngspice's instance `temp` is its
  SPICE side. `tests/test_bjt.py` checks 0 / 40 / 60 C against ngspice. IRs without it
  are unchanged.
- **The JFET:** `varimu/devices/jfet.py`, circuitsim's `devices/jfet.rs`, the part
  `jfet: [d, g, s]` in both builders, the KiCad / editor symbol JFET.
  - It is SPICE's level-1 model with the doping tail B, both modes, N- and P-channel.
  - `tests/test_jfet.py` checks it against ngspice on a grid, plus the device fixtures.
  - Components `2N3819@1`, `J175@1`; also `1N4148@1`, `ZPD12@1`. Central's cards are
    kept as cited numbers only: their licence forbids redistributing the card text.
- **The Blackmer cell from our BJTs:** `scripts/blackmer_cell.py` (Hebert's AES 4055
  topology) and its test circuit `blackmer_vca_test.yaml` (THAT 2180's Figure 2),
  `tests/test_blackmer_vca.py`:
  - idle 20 uA;
  - 6.20 mV/dB;
  - THD 0.0047 % at unity, 0.015 % at -15 dB;
  - both engines agree on the DC point.

**B11 is built:** `config/circuits/ssl_bus_comp.yaml`, GENERATED by
`scripts/make_ssl_bus_comp.py` (its docstring lists what is left out).
- **What it is:** one 82E26 bus card and the 82E27, the dbx 202C as THAT's 202XT (one
  cell of eight times the area), and a KEY INT / EXT switch.
- **The app:** the device `ssl_bus_comp`, a session insert with a KEY input.
- **Measured** (`tests/test_ssl_bus_comp.py`):
  - ratios in order but softer than the legend (2:1 → 1.5, 4:1 → 2.5, 10:1 → 3.8 at a
    30 ms attack; 6:1 keyed at a 0.1 ms attack);
  - keyed, each 6 dB of key adds 5.0 dB of duck (a ratio, no cliff);
  - recovery τ 81-95 ms at RELEASE 0.1 s (RC 85 ms);
  - THD -60 to -80 dB while compressing.
- **The pump demo:** `scripts/ssl_pump_demo.py` writes `reports/ssl_bus_comp/pump/`
  (128 BPM saw keyed by a kick, a 14 dB duck per beat). Open: the user listens.
- **Speed:** the draft's Newton tolerance of 1e-3 is a 2 % gain error in a log-domain
  cell (distortion near -50 dB). The device plays with 1e-5 (`panel::Device::newton`, a
  new field), which is about 3.4x slower than real time. So it prints; it doesn't play
  live.
- **Open:**
  - which ratio contact is which (derived: 37 = 10:1, 38 = 4:1, 39 = 2:1);
  - the THRESHOLD pot's value (10K, provisional);
  - pin 15 (held at 0 V);
  - the 202C's own control port;
  - the AUTO pairing;
  - a second bus card for stereo.

**B12: the JFET and its components are built; the 1176 circuit isn't.** Its sources are
in `data/schematics/urei_1176/` (Rev A R-10743 and Rev F R11914, both transcribed; UA's
reissue manual). The manual's Figure 5 (the D/E gain-reduction control circuit) is clean,
and with it and the Rev A sheet the topology is mostly known. Four things stop a build
worth trusting:
1. R83 in the Q-bias divider and the ratio decks' T&C resistors are factory-selected and
   unprinted.
2. The Q-bias range then comes out at about 0 to -1.2 V at the gate. A 2N3819 pinches
   off near -2.5 V, so Q-bias couldn't be calibrated on it: the 1176's selected FET
   (Rev A's label is illegible, Rev F's "UREI 13-0027") must pinch off lower.
3. How Q7-Q10 reach the rail and ground can't be read with certainty (Figure 5 labels
   two different resistors R46).
4. No winding data exists for the output transformer (UA-5002, or Rev F's B11148).

None of the four blocks a build (the user's go-ahead, 2026-11-06; the GroupDIY links in
the README turned out dead or private, so don't ask for them again). The agreed plan:
- **The circuit:** a D/E-era 1176LN.
  - Front end, LN gain-reduction stage and preamp from UA's manual (Figs 2-3).
  - The control amp from Fig 5, its wiring read off the clean Rev F sheet (the same
    circuit: 2N3707s, 1 % resistors).
  - Rev A's class-A output (Q5 2N3707, Q6 2N3053, the UA-5002's emitter and feedback
    windings): the manual says D/E kept that design, and Rev F's push-pull needs models
    we don't have.
- **The FET:** a 2N5457 / 2N5458 class part (repairers' stand-ins), Central's card's DC
  values (its CGD is a slipped exponent).
- **The T+C values** calibrated as the factory did: R83 so the Q-bias range covers the
  FET's pinch-off, then the manual's Q-bias procedure (1.0 dB drop at 0 dB out).
- **The transformers:** provisional. T1 about 1:1.58 into 270 ohm; T2 designed from Q6's
  operating point and +22 dBm into 600 ohm.
- **Done when:** the profile meets the manual's figures or says why, a drum loop is
  printed, and there is an app device.

### B13. The Neve 1073 (the EQ, and three chains)

- The class-A BJT preamp and its inductor EQ: high shelf 12 kHz; low shelf 35 / 60 /
  110 / 220 Hz; mid bell 0.36-7.2 kHz; high-pass 50-300 Hz. Frequencies to confirm on
  the schematic.
- The Marinair (St Ives) transformers, and the EQ's inductors as designs in C2's
  designer. A big low boost saturating the inductor's core then comes out of the
  physics, as in the EQP-1A.
- Carnhill's replacement transformers have datasheets.
- This is CHAINS_PLAN.md's WP11 (44-BX, SM57, U47 -> 1073): built once, it counts for
  both plans.

**Done when:** WP11's done-when, plus the EQ's curves against the published ones per
band and the inductors' saturation at full boost measured.

### After B13

The next three share B11-B13's prerequisites:
- the **dbx 160** (the VCA exists after B11; an RMS detector; feedforward, so it is a
  second pumper and a classic on kick, snare and bass);
- the **Neve 2254 / 33609** (diode-bridge gain cell; a drum-bus glue with grit);
- the **API 2500 / 550A** (the 2520 op-amp built from BJTs, CHAINS_PLAN.md WP12's API
  312 shares it; the 2500's feedback / feedforward switch and THRUST).

## Built so far

- the 670 (the slice), the EQP-1A (B2), the 5E3 (B9), the V76 (B10);
- from CHAINS_PLAN.md: the V72, the UA 610, the SSL 4000 E's mic amp and the Tascam 424
  mk1's input (op-amps only), the Ampex 351's electronics (TAPE_PLAN.md and WP7).

## The rest of the list

The device library (`config/components/`) now has:
- tubes: 12AX7, 12AU7, 12AY7, 12BH7, 6386, 6973, 5651, 6084, EL34 triode-connected,
  6V6GT, 6K6GT, 6201, EF804S, E83F, VF14T, 6AL5, 884, 2D21;
- rectifiers: 6X4, 5Y3GT, GZ34, selenium, silicon, a zener;
- BJTs: BC550C, BC560C, BC413C, BC238;
- the `opamp` part, a single-pole macro from a datasheet's A0 / GBW;
- transducers and media (capsules, cartridges, ribbons, speakers, tape, plates, the
  lamp).

Still missing:
- the JFET (B12);
- a BJT at temperature (B11 step 2);
- a photocell;
- MOSFETs.

### Compressors and limiters

| Device | What it is | Needs | Schematic outlook |
|---|---|---|---|
| **SSL G bus compressor** | Stereo VCA bus compressor; pumping, drum bus | **B11** | Clone threads; THAT sheets |
| **UREI 1176** | JFET compressor; snappy, all buttons in | **B12** (the JFET) | Good: manuals, revision threads |
| dbx 160 | Feedforward VCA, RMS detector; punch on kick / snare / bass, a second pumper | B11's VCA | Leads: dbx202.pdf, a 160 / 161 service manual (web: https://manualmachine.com/dbx/161/4655886-service-manual) |
| Neve 2254 / 33609 | Diode-bridge gain cell; drum-bus glue | BJTs (built), diodes | Widely circulated |
| API 2500 | VCA bus compressor, feedback / feedforward switch, THRUST (a high-pass in the detector) | The 2520 from BJTs; a VCA | Fair |
| Teletronix LA-2A | Tube optical leveler; vocals, bass | A photocell model: the T4B's electroluminescent panel and the CdS cell's memory (the two-stage release), a 6AQ5 fit | Excellent: manual schematic; transformer datasheets |
| A lamp-driven photocell limiter | An incandescent bulb lighting a CdS cell: the filament's heating lag sets the attack | The photocell (as the LA-2A); the lamp exists (`LAMP327@1`) | Generic; a design of our own is fine |
| Universal Audio 175B / 176 | Variable-mu, the 670's family | Little; the 176 may use the 6386 (to confirm) | Good |
| Gates Sta-Level, Altec 436, RCA BA-6A | Broadcast variable-mu | Remote-cutoff tube fits | Good: broadcast manuals |
| Spectra Sonics 610 | A very fast discrete limiter (to confirm) | BJTs | To find |

### EQs

| Device | What it is | Needs | Schematic outlook |
|---|---|---|---|
| **Neve 1073 / 1081** | Class-A BJT, inductor EQ | **B13** (= CHAINS WP11) | Widely circulated; Carnhill datasheets |
| SSL 4000 E channel EQ | The console EQ (black / brown knob) | The `opamp` part; the E's mic amp exists (WP4) | Good |
| API 550A | Proportional-Q EQ, 2520 op-amps | The 2520 from BJTs (CHAINS WP12) | Fair |
| Helios 69 | Inductor EQ (Island, Olympic) | BJTs (CHAINS WP19) | Fair |
| Pultec MEQ-5, HLF-3C | The EQP-1A's siblings (mid EQ; filters) | Nothing new | Good, same manual family |
| Langevin EQ-251A, Cinema Engineering 7080 | Passive program / graphic EQs with a make-up amp | Passives, tube make-up | To find |
| EMI REDD-era and TG12345 EQs | The EMI consoles | Tubes (REDD), BJTs (TG, CHAINS WP20) | To find |

### Guitar amps and pedals

| Device | Needs |
|---|---|
| Marshall JTM45 | KT66 / 5881 fit; GZ34 exists |
| Vox AC30 | EL84 fit; cathode-biased, Top Boost stack |
| Fender 5F6-A Bassman | 6L6 fit; long-tail inverter |
| Fender 5F1 Champ | DISTORTION_PLAN.md's O1 |
| Fuzz Face, Tone Bender | Germanium BJTs (the BJT at temperature: B11 step 2 helps) |
| Tube Screamer, Klon | The `opamp` part, diodes |

Mechanical devices (plates, springs, tape echo) are in REVERB_PLAN.md and DELAY_PLAN.md,
not here.

## Mapping a schematic: what decides how hard a device is

1. **A schematic with printed values.** Vintage broadcast and studio gear shipped with
   service manuals; guitar amps are the most documented audio circuits there are. Units
   still in production (Manley Variable Mu, Tube-Tech CL1B, the Distressor) usually have
   none public.
2. **Datasheet curves for the active parts.** Classic tubes are well documented;
   transistor and JFET types have SPICE cards and curves on their sheets.
3. **Transformer and inductor data.** Almost always the gap. Either design them in C2's
   designer, or use modern replacements' datasheets as the source (Cinemag, Jensen,
   Sowter, Carnhill / St Ives, Mercury Magnetics or Heyboer for guitar amps): ratio,
   inductance and winding resistance, sourced as a replacement's figures, not the
   original's. Otherwise, provisional genome parameters.
4. **Layout.** A `scripts/draw_<device>.py` on `varimu/editor/sketch.py`, checked pin by
   pin, as for the 670, the EQP-1A and the 5E3.

**Naming.** Brand names are fine inside the project. Shipping the app with devices named
after brands is a trademark question for later.

## Sources

- Fender 5E3 tube lineup: web: https://www.vintageguitar.com/36026/fender-5e3-deluxe/
- 5E3 annotated schematic and circuit description: web: https://robrobinette.com/How_The_5E3_Deluxe_Works.htm
- V76: `data/schematics/telefunken_v76/README.md` (IRT's Braunbuch, drawing S 1176)
- SSL bus compressor topology: web: https://vintageking.com/blog/exploring-the-ssl-the-bus-stereo-bus-compressor/, https://www.bonedo.de/artikel/ssl-g-comp-bus-compressor-test, https://fr.audiofanzine.com/compresseur-de-studio/ssl/the-busplus/
- SSL Bus Comp Classic (THAT 2181, a VCA in the sidechain's loop): web: https://www.mixonline.com/technology/news-products/ssl-launches-bus-comp-classic-unit
- dbx 160 (decilinear VCA, RMS, feedforward): web: https://www.mixonline.com/technology/birth-of-a-classic-the-dbx-160-compressor
- dbx 200 / 202 VCA schematic lead: web: https://groupdiy.com/threads/dbx-160vu-clone.30006/page-9
- 1176 attack range and revisions: web: https://en.wikipedia.org/wiki/1176_Peak_Limiter
- 1176 Rev A schematic comparison: web: https://groupdiy.com/threads/1176-plosives-looking-for-rev-a-schematic-or-high-res-internal-shots.34502/page-5
