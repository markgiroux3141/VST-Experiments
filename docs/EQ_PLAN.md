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
| EQ2 | **Pultec MEQ-5** | mids: low-mid peak, mid dip, high-mid peak; the EQP-1A's partner | its network; its amplifier is the EQP-1A's family | Gyraf's 2002 reconstruction, read pixel by pixel (data/schematics/pultec_meq5/README.md) | **built 2026-11-15** |
| EQ3 | **API 550A** | 3-band proportional-Q console EQ (1967-70s) | the EQ card's networks; the 2520 exists (CHAINS_PLAN.md WP12) | API's drawing 613-759 (a clean 400 ppi rescan) and the 550 / 550A sheets, found (data/schematics/api_550a/README.md) | **built 2026-11-15** |
| EQ4 | **Neve 1073's EQ** | inductor mids, shelves, its HPF | the EQ cards on the built mic path (B13 = CHAINS WP11) | Neve's EH10023, B182, B205, B211 (in the 1073 packet); its switches EK20065 / EK20066 / EK20105 missing | mic path built |
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

## EQ2: the Pultec MEQ-5 (built 2026-11-15)

**Sources:** `data/schematics/pultec_meq5/README.md`. Only Gyraf Audio's 2002 reconstruction of the
filter sections is public (the GroupDIY attachment is the same file); its switches are read
pixel by pixel as mirrored decks, the reading under which MID CUT resonates on its knobs. The
front panel's 0-10 dB is KMR's listing.

**Circuit:** `config/circuits/pultec_meq5.yaml`, GENERATED by `scripts/make_pultec_meq5.py` from
`pultec_eqp1a.yaml`: the EQP-1A's input transformer, interstage, 12AX7 / 12AU7 amplifier, output
transformer and supply (Gyraf: "cross-compatible with the PEQ1A"), its passive network replaced:
LOW BOOST (2K5 linear in series, a tapped coil and capacitor from its wiper; 200-1000 Hz), 1K
shunt, 510 ohm, MID CUT (2K5 reverse-log to ground, 270 ohm, a tapped coil and capacitor to
ground; 200 Hz-7 kHz), HIGH BOOST (10K linear as LOW BOOST; 1.5-5 kHz), 5K1 shunt. Controls
`low_peak_hz` / `low_boost`, `dip_hz` / `dip`, `high_peak_hz` / `high_boost`. Coil resistance
the EQP-1A toroid's law (provisional). Preflight passes at all 275 switch combinations.

**Profile:** `varimu unit --circuit pultec_meq5 --name NAME` (`varimu/measure/meq5_suite.py`: the
EQP-1A's screen and THD on the MEQ-5's panels, every position's extreme at full knob). Tests
`tests/test_pultec_meq5.py` (the network by AC analysis with the tubes out). The app's
`pultec_meq5` (`Group::Eq`, draft-1x: 0.22x real time on the drum clip, no block over).

**Measured (nominal unit, reports/units/meq5_nominal/; the multitone's 31 tones set the
frequency resolution, ~1/3 octave):**
- Passes the screen (rails, quiet idle, no spurs); overall gain -1.7 dB at 1 kHz (the network
  loses 2.5 dB more than the EQP-1A's into the same amplifier); THD 0.0055% at +10 dBm, 0.024%
  at +21 dBm.
- Full-knob extremes: LOW 11.2-11.8 dB, MID CUT 8.6-11.4 dB, HIGH 7.1-8.6 dB (published 0-10 dB).
- Where (AC analysis, finer): MID CUT on its knob within 5% from 200 Hz to 2 kHz, 3 kHz 1.11x,
  4 / 5 / 7 kHz 1.25 / 1.37 / 1.24x; LOW 0.97-1.2x but 500 Hz 1.57x; HIGH 1.08-1.50x, rising with
  the knob.
- Flat: -3.9 dB at 20 kHz re 1 kHz (the EQP-1A on the same amplifier -2.3 dB): the network's
  ~3.4 kOhm into the interstage's provisional winding capacitance.

**Open (the user's):** listening; whether to correct the reconstruction's misses (LOW 500, the
top of MID CUT and HIGH) by resonance, which would be our inference, not a source; the
amplifier's tubes (one post says a 6AQ5 output).

## EQ3: the API 550A (built 2026-11-15)

**Sources:** `data/schematics/api_550a/README.md` (API's drawing 613-759, traced in full: "The
trace, complete"), the Model 550's sheet (its curves and specifications) and the 550A's
installation page. The drawing's arc rotors are progressive shorting contacts (each frequency
step adds a capacitor), the key to its frequencies; the drive decks' overlap at 0 dB was read
by the user (2026-11-15: the cut-side deck on 1-6, the boost-side on 7-11).

**Circuit:** `config/circuits/api_550a.yaml`, GENERATED by `scripts/make_api_550a.py` from
`api_2520_test.yaml` (A1 and A2, two 2520s) and `api_312.yaml` (the AP2503's values), with the
drawing's four discrete followers A3-A6 (`2N5087@1` and the new `2N5088@1`, Central's card) and
ideal +-15 V rails. One reciprocal bridge per band; the cut strings run A6 -> A4 -> A3 -> A2's +
input, the boost strings in A2's (and A1's) feedback, so each band's cut is its boost's exact
reciprocal. Controls: `hf_gain_db` / `mf_gain_db` / `lf_gain_db` (the panel's -12 ... +12),
`hf_freq` / `mf_freq` / `lf_freq` (positions 1-5, 1 = most counter-clockwise = the highest),
`hf_shelf` / `lf_shelf`, `bandpass`, `eq_in`, `level` (HIGH / LOW, input and output together)
and `gain_trim_db` (the installation page's resistor between terminals 8 and 11). The generator
also writes `api_550a_network.yaml`, the same circuit with linear op-amps for AC analysis.
Pre-flight passes on a covering set of 606 switch combinations (the product is 37 million).

**Profile:** `varimu unit --circuit api_550a --name NAME` (`varimu/measure/api550a_suite.py`;
run it with `OPENBLAS_NUM_THREADS=1`: the network's small solves slow ~100-1000x when BLAS
threads fight renders for the cores). Tests `tests/test_api_550a.py`. The app's `api_550a`
(`Group::Eq`, draft-1x).

**Measured (the network, nominal unit, relative to flat):**
- Peaks by position: LF 421 / 302 / 203 / 102 / 53 Hz, MF 4.84k / 2.95k / 1.47k / 770 / 381,
  HF 15.4k / 11.8k / 9.4k / 6.9k / 4.8k (cut; HF boost peaks sit 3-12% lower at small steps).
  They land on API's panel frequencies (LF 50-400, MF 400-5k, HF 5k-15k) from the capacitors
  alone; the frequency doesn't move with the step (R_up R_q ~9.4e7 ohm^2 at every step), the Q
  does (+12 dB: ~2.1 octaves wide at half its dB; the 550's family reads ~2.6 by eye).
- Steps: LF and MF reach +-2.0 / 6.0 / 11.9 at +-2 / 6 / 12, boost and cut mirror within 0.3 dB.
  HF peak: cut -11.3 to -11.7, boost +10.2 to +11.3 at +-12 (S9A / S9B's capacitors differ,
  C37 68 pF bridges the boost string): short of the 550's +-12. HF shelf +-12.0 to 12.8; LF
  shelf +-13.3 at +-12 (its R27 6340 against the boost string's 23.2K).
- Flat: HIGH LEVEL -0.03 dB at 1 kHz (the -7.85 dB pad, the AP2503's 1:3 and its losses into
  600 ohm), -0.30 at 30 Hz, -0.52 at 20 kHz (the 550's +-0.5 dB, at its edge: the AP2503's
  provisional construction); LOW LEVEL -0.62 dB.
- Band-pass IN: -4.8 dB at 50 Hz, -2.5 at 15 kHz, -0.25 at 1 kHz.
- Gain trim: 2.6 / 5.3 / 7.4 / 9.8 / 12.1 / 13.2 dB against the table's 2 / 4 / 6 / 8 / 10 /
  11. R106 200 / R76 56 as drawn give 1 + 200 / (56 + R); R106 = 150 would match the table
  within 0.3 dB. Reported, not fitted.
- The real circuit (2520s, followers; reports/units/api550a_nominal/) renders within 0.02-0.22
  dB of the network on six panels; A3-A6 idle 40-140 mV above their inputs (the PNP / NPN Vbe
  mismatch). 1 kHz at +4 dBm out: -0.12 dB, 0.0045% THD, idle -229 dBFS.
- Headroom: 0.068% THD at +26 dBm, 1.9% at +28 dBm (1 kHz and 30 Hz), 0.35% at +27.4 dBm at 20
  kHz, against the 550's "+28 dBm, < 0.35% 30 Hz-20 kHz". A2 clips at +10.3 / -10.8 V driving
  the AP2503's reflected 600 ohm (~100 mA peak): the 2520 stand-in (its data sheet's 7.75 V
  rms) and the AP2503's provisional winding resistances leave it ~1.5-2 dB short. Reported.
- Live, the discrete circuit: 2.07x real time at draft-1x on one thread (2.7 Newton iterations,
  44 device evaluations a sample: the 30 transistors' ports, and 60 of its 114 capacitors are
  their junctions). No partition fits: A2's feedback loop (through A5) can't take a sample of
  latency, and a feed-forward cut at a follower's output (A4) leaves its driver in the
  lower-numbered part, against the engine's ownership rule (the input stays in part 0). Also
  measured: `dk_sparse` 1.44x; the junction capacitances dropped ~25% faster (-60 dB).

### Live (2026-11-15, the user's call: the draft the cheap way, production the real one)

`config/circuits/api_550a_live.yaml` (GENERATED, `make(live=True)`): the drawing as built, A1 / A2
as clamped `opamp` macros (the 2520 data sheet's A0 3e5, GBW 50 MHz, Zin 10 Mohm; 5.6 ohm out, the
output pair's emitter resistors; each clamped at the swing the production circuit's A1 / A2 clip
at, measured: +12.0 / -12.15 V and +10.8 / -11.6 V, A2's as their mean, the macro being
symmetric), A3-A6 as unclamped unity buffers at the discrete followers' measured gain (0.99497,
a0 198; their inputs come from the 2520s, which clip first). `panel::Device::live_circuit`
names it and `Device::circuit_at(quality)` picks it at every draft quality (Play, auditions, draft
prints, takes rendered at a draft, a chain's end); production renders the discrete circuit. The
panel is the real circuit's (`a_live_circuit_has_its_circuits_controls`).

- Load (`examples/load_profile.rs`, draft-1x): 0.19x real time on the mix, none of 3918 blocks
  over; 0.20x on the drums at -3 dBFS with +-12 dB in all bands (worst block 0.44).
- Against the discrete circuit on program: -47.6 dB; as a fixed filter within 0.04 dB to 15 kHz,
  -0.38 dB / -5.4 deg at 20 kHz (the discrete 2520s' extra pole); -70 dB past it. Clipping: the
  output's peak 28.0 V against +27.1 / -29.5 V (flat, 1 kHz, far over).
- Not live: the 2520's own distortion below clipping (0.0045% at +4 dBm), its asymmetric clip
  and load-dependent swing, the followers' current-limited negative swing. Prints at production
  have them.
- Tests: `test_the_live_circuit_tracks_the_real_one` (three tones within 0.1 dB, the clipped
  peak within 5%).

**Open (the user's):** listening; the gain trim's table vs R106; the HF peak's shortfall (as
drawn); the headroom at +28 dBm (the 2520 stand-in, the AP2503's construction); the panel
labels for the
frequency positions (the 550A's own marked frequencies aren't in the sources, only the 550's:
the positions are numbered, their frequencies measured).

## Decisions for the user

1. **The order** above (EQ3 the API 550A next).
2. **EQ1's open items** above.
3. **Coupling between inserts.** Each insert runs in its own matched line (its own source and
   load), so the EQP-1A -> HLF-3C pair doesn't load each other. Building them as one netlist
   (FUTURE_DIRECTIONS.md section 8, coupling between devices) is a later option.

## Status

- 2026-11-15: written; EQ1 built (circuit, sources, profile, tests, app device).
- 2026-11-15 (later): EQ2 blocked on its source: Gyraf's MEQ-5 reconstruction is too coarse to read
  which tap and capacitor each position joins, and the better redraw is a GroupDIY attachment (the
  user's to fetch). EQ3 moved up: API's 550A drawing found as a clean rescan with the 550 / 550A
  sheets; the HF band's structure read (A1's reciprocal bridge on S8A, the twin-T decks, the
  proportional-Q decks S8B / S8C); the rest of the tracing is listed in its README. EQ4's packet
  holds Neve's EQ boards but not its three switch drawings.
- 2026-11-15 (later): EQ2 built from Gyraf's reconstruction, read pixel by pixel (the user's
  GroupDIY download was the same file); its misses reported in EQ2's section.
- 2026-11-15 (later): EQ3 built: the 550A's drawing traced in full (the arc rotors are
  progressive, each frequency step adds a capacitor), the circuit, its network check, the 2N5088,
  the profile, tests and the app device; numbers and misses in EQ3's section.
- 2026-11-15 (later): the 550A plays live through `api_550a_live.yaml` (the drafts; production
  stays discrete), `panel::Device::live_circuit`: 0.19x real time (was 2.1x); EQ3's "Live".
