# EQs and filters of the period

Started 2026-11-15 (the user: "old school analog simulations of low pass and high pass
filters, and any other EQs that give us more flexibility in our toolkit while remaining true
to how EQs worked back in the day"). This plan takes over the EQ items of
[MIX_INSERTS_PLAN.md](MIX_INSERTS_PLAN.md) (MX2 the HLF-3C, MX3 the MEQ-5; MX1 the SSL E's EQ
is listed here too) and gathers the EQs that DEVICE_CANDIDATES.md, PERIOD_GEAR_BACKLOG.md and
B13 name, so the toolkit is planned in one place.

Each EQ is a real unit built as one circuit, like every other insert: a circuit file whose
values all carry a source, a profile against the maker's published curves, a device in
`panel::DEVICES` (`Group::Eq`), live auditions and prints as a session insert. The ground rules
are unchanged (CLAUDE.md "Hard rules").

## How EQ worked back in the day, and what that asks of the models

- **Passive networks in a 600 ohm line.** Until the mid-1960s an equalizer or filter was a
  passive LC / RC network between a matched source and load (Pultec, Langevin, Altec, Cinema
  Engineering). Its curves depend on those terminations: drive it from the wrong impedance
  and the knee moves or peaks. So every passive unit here is built with its source and load
  in the netlist, and the line's impedance is a value with its source.
- **Insertion loss and make-up.** A filter set like the HLF-3C has "zero insertion loss"
  against the line it sits in (its passband is the line's level); an equalizer like the
  EQP-1A or the MEQ-5 loses 15-20 dB in its network and has its own tube make-up amplifier.
  The circuit file says which: a filter reads 0 dB through its key at OUT (`full_scale`), an
  equalizer includes its amplifier.
- **Stepped controls.** Frequencies are rotary switches; boost / cut are stepped or carbon
  pots with their tapers. A change of frequency rewires the circuit and restarts a live
  stream, as on the unit (the switch is clickless on the HLF-3C; ours restarts silently).
- **Inductors.** Toroids (molybdenum permalloy: nearly linear) in filters, tapped iron-core
  coils in console EQs (the 1073's, the Helios'). Their losses shape the knee; an iron core
  saturates on a big low boost (the EQP-1A's transformers already do, from their cores).
- **Console EQs after ~1967** are active: API's 550 (discrete op-amps, proportional Q), Neve's
  inductor EQs around class-A BJT stages, then the SSL E's op-amp state-variable bands.

## The list, in the proposed order

| # | Unit | Fills | What's new | Sources | Status |
|---|---|---|---|---|---|
| EQ1 | **Pultec HLF-3C** | passive high-pass / low-pass, 18 dB / oct | nothing (passives) | Pulse Techniques' sheet + a hand-drawn schematic with the 3C's table (found) | **built 2026-11-15** |
| EQ2 | **Pultec MEQ-5** | mids: low-mid peak, mid dip, high-mid peak; the EQP-1A's partner | its network; its amplifier is the EQP-1A's family | gyraf.dk's reverse-engineered schematic (transformers guessed); a user manual listed by vintagedigital.com.au | to source |
| EQ3 | **API 550A** | 3-band proportional-Q console EQ (1967-70s) | the EQ card's networks; the 2520 exists (CHAINS_PLAN.md WP12) | API's brochure; technicalaudio.com's "API 550 Equalizer Versions" | to source |
| EQ4 | **Neve 1073's EQ** | inductor mids, shelves, its HPF | the EQ cards on the built mic path (B13 = CHAINS WP11) | Neve's drawings (data/schematics/neve_1073/README.md) | mic path built |
| EQ5 | **Langevin EQ-251A** | a passive program EQ with slide controls in 1 dB steps (the Motown family) | its network; a make-up amp (to see on the drawing) | elektrotanya's EQ-251A schematic archive; a hand drawing credited to Rick Chinn (GroupDIY) | to source |
| EQ6 | **Altec 9067B / 9069B filter** | a sharper passive filter than the HLF-3C (to confirm: m-derived / Chebyshev sections) | nothing (passives) | GroupDIY threads; Altec's sheets to find | to source |
| EQ7 | **Helios 69 and EMI TG12345 EQs** | the British console EQs of Olympic and Abbey Road | the EQ boards on the built mic paths (CHAINS WP19, WP20) | the mic paths' sources; the EQ boards to trace | mic paths built |
| EQ8 | **SSL 4000 E EQ** (MIX_INSERTS MX1) | the clean, sweepable op-amp parametric and its filters | the 82E02 card on the `opamp` macro | SSL's 82E02 (found, not transcribed) | to transcribe |

Why this order: EQ1-EQ2 are passive or reuse the EQP-1A's amplifier, so they cost little and
complete the Pultec rack (filter + program EQ + mids). EQ3 is the first active console EQ,
and its op-amp exists. EQ4 finishes a device that is half built. EQ5-EQ6 broaden the passive
family with a different design school (Langevin's and Altec's). EQ7 finishes two built channels.
EQ8 is the newest, and is the clean sweepable reference.

## EQ1: the Pultec HLF-3C (built 2026-11-15)

**Sources:** `data/schematics/pultec_hlf3c/README.md`. Pulse Techniques' sheet (eleven positions
per selector, 500-600 ohm, constant-K, zero insertion loss, +28 dBm, shielded toroids) and a
hand-drawn schematic of the older HLF-3 (its toroids' taps in mH) with the HLF-3C's table (each
position's capacitors, the coils by colour).

**Circuit:** `config/circuits/pultec_hlf3c.yaml`, GENERATED by `scripts/make_pultec_hlf3c.py`:
600 ohm source, the IN-OUT key (both ends), a constant-K high-pass T (C-1, L-1 to common, C-2),
a constant-K low-pass T (L-2, C-3 to common, L-3), 600 ohm load. Controls `low_cut_hz` (0 = OFF,
50-2000), `high_cut_hz` (1500-15000, 0 = OFF), `filter_in`. The output's full scale is half the
input's, so the key at OUT reads 0 dB (the brochure's zero insertion loss). Each section is a
3rd-order Butterworth in its terminations (GroupDIY's "Butterworth Tee"). Preflight passes at
all 242 switch combinations.

**Profile:** `varimu unit --circuit pultec_hlf3c --name NAME` (`varimu/measure/filter_suite.py`:
AC analysis per position, the brochure's -40 dB points read by eye, a +28 dBm render per section
against the AC analysis). Tests `tests/test_pultec_hlf3c.py`. The app's `pultec_hlf3c`
(`Group::Eq`, draft-1x).

**Measured (nominal unit, reports/units/hlf3c_nominal/):**
- Both selectors OFF with the key IN: within 0.0004 dB of the key at OUT.
- High cut: -3 dB at 0.86-1.03x the knob, 16-18 dB / octave, -0.1 to -0.3 dB of passband loss
  (the coils' resistance); -40 dB within 0.98-1.17x of the brochure's points.
- Low cut: -3 dB at 1.15-1.36x the knob (50 cps 1.36x), 13-17.5 dB / octave two to three
  octaves out; -40 dB within 0.94-1.10x of the brochure's points (reading error ~10%).
- circuitsim at +28 dBm against the AC analysis: 2e-5 dB at 100 Hz, 0.018 dB at 5 kHz; the
  residual -117 / -81 dB (linear).

**Why the low cut sits above its knob** (each cause alone, against the as-built 1.36x at 50 cps):
the coils' resistance (provisional: the EQP-1A's toroid law, 76 ohm on the 800 mH tap) 1.14x
without it; the 600 ohm line against the drawing's 500 ohm design 1.28x at 500 ohm; the
HLF-3C's smaller C-1 / C-2 (50 cps, 1-2 kc) 1.31x with the HLF-3's. All three together: within
4% of every knob. The brochure's curves are drawn as ideal constant-K sections and only their
stop band can be read, where the model already lands; so nothing is fitted.

**Open (the user's):**
1. **The LF toroid's resistance.** Keep the EQP-1A's law (soft knee, 13 dB / oct near 50 cps),
   or a lower one (a bigger LF core is likely; no source), or fit it to a measured unit if one
   turns up.
2. **The line.** 600 ohm (now) or the drawing's 500 ohm design impedance; or a LINE control
   (500 / 600 / bridging), the user's "realistic first, then bend": a light load gives the bump
   at the knee GroupDIY's builders report.
3. **The cores.** Linear now. Saturating permalloy at +28 dBm is an option with numbers to
   bring first (a material fit, `config/magnetics.yaml`), not a default.
4. **Listening.** The user hears it on program (the app's EQ menu, or as an insert after the
   EQP-1A).

## Decisions for the user

1. **The order** above (EQ2 the MEQ-5 next).
2. **EQ1's open items** above.
3. **Coupling between inserts.** Each insert runs in its own matched line (its own source and
   load), so the EQP-1A -> HLF-3C pair doesn't load each other. Building them as one netlist
   (FUTURE_DIRECTIONS.md section 8, coupling between devices) is a later option.

## Status

- 2026-11-15: written; EQ1 built (circuit, sources, profile, tests, app device).
