# The Minimoog Model D from its schematics

Started 2026-11-07 (the user: "let's start building this"), in the worktree `minimoog` beside the
Rhodes session (merged after; builds at 3 cargo jobs, below-normal priority, so the other session
keeps its cores). Sources: [data/schematics/minimoog/README.md](../data/schematics/minimoog/README.md).

## Aim

The Model D as one coupled circuit from its service manual: three VCOs (the uA726 expo
converters), the mixer, the ladder filter, two contour generators, the VCA, the keyboard's
sample-and-hold and the +-10 V supply, all on our BJT model, played live from a MIDI keyboard
like the tube synth. Like every device here, the hardware's values are the anchors
(Folkman's adjustment procedures are the calibration), and bending comes after.

## Choices (made at the start; the user can overrule)

- **The unit:** the 204D manual's "new" oscillator board (serial 10175 and above, the octave
  buffer) and its filter board; the 2022 reissue keeps that signal path.
- **The TIS97** (the ladder and output amp) has no card: the 2N3904 (the sheet's alternate
  for the TIS92) stands in, as the TIS93 is the 2N3906. `2N3904@1`, `2N3906@1` from Central's
  cards (numbers cited, as the 2N5087).
- **Order:** the filter first (the instrument's signature and the best-documented part), then
  the VCA, the oscillators, the contours, the panel and supply.

## Milestones

- **MM0, sources** (done 2026-11-07): the 204D service manual's schematics (Internet Archive)
  read; Folkman's adjustment procedures; Huovilainen's DAFx-04 analysis.
- **MM1, the VCF** (circuit No. 6): `config/circuits/minimoog_vcf.yaml` with ideal +-10 V and a
  test fixture for the panel's control summing. Done when:
  - it idles at the bias the drawing implies (the string, the output amp) and passes the
    pre-flight checks;
  - Folkman's three procedures can be carried out on it (`scripts/minimoog_vcf_trim.py`):
    REGEN CAL (regeneration starts between EMPHASIS 7 and 8 at CUTOFF -1), RANGE (EMPHASIS 10
    oscillates at 440 Hz), SCALE (tracks the keyboard over three octaves);
  - its response is a 4-pole low-pass (-24 dB / octave above the cutoff) with resonance
    rising with EMPHASIS, and its overdrive matches the ladder's tanh-per-stage behaviour
    (Huovilainen) qualitatively;
  - it plays in varimu-app (the test oscillator into it, keys to the keyboard CV), with its
    load measured.
- **MM2, the VCA** (circuit No. 7) and the output, appended to the filter.
- **MM3, the oscillators** (board No. 1, Fig 9-2): the uA726 as a heated matched pair (its
  temperature regulation as a thermal node, the B6 heater's pattern), the integrator and its
  reset (a hybrid exception if the reset is far faster than a sample: HYBRID_PHYSICS_PLAN.md),
  the triangle / rectangular shapers, the octave buffer (board 6) and the -5 V reference;
  Folkman's oscillator tuning procedure as the trim.
- **MM4, the contours and the keyboard** (board No. 2, Fig 9-7): two contour generators, the
  keyboard's current source and sample-and-hold, glide.
- **MM5, the whole voice:** the mixer, noise (board 3), the front panel's wiring (Fig 9-16 /
  9-17: the control node's real summing, replacing MM1's fixture), the +-10 V regulators;
  the app's `minimoog` device with a partition measured for real time.
- **MM6, bending:** after the user has played it (realistic first).

## Status (2026-11-07)

MM0 done. **MM1 built; open: the user plays it.**
- `config/circuits/minimoog_vcf.yaml` idles at the drawing's bias (the string's 1.96 V at the
  input pair, the top emitters 7.30 V); pre-flight now counts a BJT's junctions as DC paths.
- Folkman's procedures by `scripts/minimoog_vcf_trim.py --write`: REGEN CAL 0.847
  (regeneration starts at EMPHASIS 7.5, ~467 Hz), RANGE 0.307 (EMPHASIS 10 at 440 Hz, keyboard
  off; the trim's working span 270-1710 Hz, below ~0.1 the reference current is gone), SCALE
  0.466 (440 / 877 / 1761 / 3525 Hz over three octaves). His Scale loop leans on the low A's
  own keyboard volts, which the fixture puts at 0 V, so the script solves for the loop's end
  state (two octaves between the A keys, the low A at 440 Hz).
- `scripts/minimoog_vcf_study.py`: 24 dB / octave above the cutoff (-65.8 dB at 4.06 kHz,
  -89.1 at 8.25 kHz); a high-pass near 35 Hz from the drawing's C27 10 uF into ~470 ohm;
  EMPHASIS takes the passband down as the peak grows (gain 19.5 -> 9.3 at EMPHASIS 5).
  Overdrive at 110 Hz: 0.5 % THD at 5 mV peak, 5 % at 50 mV, 12 % at 100 mV, 29 % at 200 mV
  (gain 50 -> 23): softer than one tanh(V / 2 Vt) stage at 50-100 mV (the stages and the
  output amp shape it; not chased).
- `tests/test_minimoog_vcf.py` (5 tests); varimu-circuit builds its IR as Python does.
- varimu-app's `minimoog_vcf` (the test oscillator into it, the keys on its keyboard input,
  the mod wheel on the cutoff fixture), Newton 1e-5 (the expo converter): **0.59x real time
  at draft-1x** on a 110 Hz saw at EMPHASIS 6, 6 of 938 blocks over (worst 1.41x), measured
  while the Rhodes session ran (`examples/load_profile.rs`).
- Fixtures until later milestones: the panel's summing (CUTOFF as volts through 100K,
  KEYBOARD CONTROL 1 / 2 as 300K / 150K by inference), the keyboard (0 V at the low A, MIDI 45
  provisional), AMOUNT OF CONTOUR at 0, ideal +-10 V, the mixer as an ideal source.

**MM2 built (2026-11-07): the VCA**, in the same file, renamed
`config/circuits/minimoog_filter_board.yaml` (the app's `minimoog_filter_board`; the VCF's
measurements read `o7`, the filter's output). Values checked against the manual's Table 7-8,
which corrected the reading in places (R67 200 at the string's foot, R12 100 ohm, R40 2.2K vs the
drawing's 22K, R54 470), and R2 82K is in series into the VCA, not a load to ground (MM1's file
had it wrong; the load is the same, the trims held).
- `scripts/minimoog_vca_trim.py --write`: Folkman's VCA Balance read as nulling the EXT.
  LOUDNESS feedthrough (his jumper puts audio on a control line), measured quasi-statically
  (the output's DC shift for EXT. LOUDNESS 4 -> 8 V): 2ND VCA BAL 0.710 (key up), 1ST VCA BAL
  0.618 (key held); untrimmed, hundreds of mV; trimmed, 2.3 mV key up, ~0 held.
- Gain over the contour (220 Hz, 50 mV into the filter): -96 dB at 0 V (shut), -21.7 at 0.5 V,
  -10.3 at 1 V, -2.8 at 2 V, ~0 to +1 dB from 3 V, where the output tops out at ~5.6 V pp (Q17's
  collector idles at 3.1 V, CR2 clamps it at -0.6 V). A contour step 0 -> 5 V with no audio
  thumps 109 mV at the MAIN OUTPUT (attack 0; the contour generators will round it, MM4).
- `tests/test_minimoog_vca.py` (3 tests) with the VCF's 5 on the new file.
- Live: one solve ran 1.22x real time at draft-1x; the VCA now runs as a partition (its own
  ideal rails, the contour's R59 / Q18 on the filter's side so the control input stays in the
  first part; the cut at Q18's collector and Q16's base: a cut at Q18's base diverged), coupled
  **hold** (`panel::Device::coupling`; fixed 2026-11-07 after the user's first note: a key's
  gate steps Q18's current across the cut in one sample, and extrapolated it overshot and
  Newton failed in the VCA at key-down; the load measurement fed no gate, so it hadn't shown):
  **0.71x, 33 of 938 blocks over** (was 0.89x extrapolated). Hold vs the one solve on gated
  220 Hz saws: -57 dB at EMPHASIS 0, -52 dB at 0.9 (the cut's one host sample of lag removed);
  `scripts/minimoog_gate_check.py` runs gated notes through the partitioned draft.
- The contour input is the keys' gate (0 / 5 V, provisional) until MM4.

**MM3 started (2026-11-07): oscillator 1 read** (the sources README, "Oscillator board No. 1").
Nothing built. What it needs, in order (each a prerequisite inside this plan, the user's rule):
1. **The uA726** as a component: a matched NPN pair at the die's regulated 78.4 C (the drawing's
   mark; the BJT model's `temp_c`), first static; its heater loop (a thermal node, B6's pattern)
   later if the drift is wanted (it is the 726's character: units from date codes 7850 / 7907
   wouldn't hold tune).
2. **The LM393** as a comparator: the `opamp` macro with its clamp at the output swing and an
   open-collector pull-up, or a part of its own (its datasheet's gain, slew, output stage).
3. **The E112** reset JFET: no card yet (InterFET / Siliconix N-channel switch); the 2N3819 card
   stands in until one is found.
4. **The reset** (~1 us, from IC8B through C9 100 pF / R33 2K): far below a sample at 48-96 kHz.
   Offline, production's error control can subdivide it; live it is HYBRID_PHYSICS_PLAN.md's
   case (the 884's M1 island or K event kernels), generated from a full-physics reference of this
   core.
5. Then `config/circuits/minimoog_vco.yaml` (one oscillator), Folkman's tuning procedure (p. 12:
   Range trimpot for 3520 Hz at the high "A", Scale trimpot for 440 Hz at the low "A"), the
   waveshapes against the sheet's levels (+-1.75 V ramp, -2.5 V = 15 % pulse), then three
   oscillators and the octave buffer (board 6).

**MM4 started (2026-11-07, unattended session): board No. 2 read, nothing built.** Fig 9-7 read in 230 dpi tiles
(data/schematics/minimoog/README.md, "Contour generator and keyboard"). Call made: do not build a netlist from a
reading that does not yet make a working envelope. The Q1 / Q4 pair, wired as drawn (Q1 base to collector), holds
N_A at one diode drop and no input could flip the generator, so one of the wires is misread (an Eccles-Jordan
reading is proposed there). Next step: build the section as its own file under both readings, drive it with the
trigger section (Q12 / Q20) and keep the one that gives attack, decay to the SUSTAIN clamp and release; the peak
detector (CR3 on N_B) then sets the ~4 V top. Also open: which panel pot is which on Fig 9-16, and the key
trigger's polarity at pin 20. The click (a bare 5 V gate stepped in one sample into the VCA) is unchanged.
MM3's prerequisites (uA726, LM393, E112, the reset exception) are not started.

**MM4's reading resolved (2026-11-07, with the user's help):** a sharper scan of Fig 9-7 (fantasyjackpalance.com's
GIFs, README) shows Q1's base wired through R3 to Q4's collector, not to its own collector: the section is an
Eccles-Jordan flip-flop, the blot at Q1 a misprint (the user spotted it from Q25's missing dot). Pin 20's trigger is
positive-going (CR10 conducts toward Q20's base). Fig 9-16's pot assignments are still untraced (the panel sheet is
916 there, 5988 px wide); building the contour generator on this reading is next.

**MM4, the filter contour built (2026-11-07):** `config/circuits/minimoog_contour.yaml` (board No. 2's filter
section with the trigger section, Fig 9-7 read on the sharp 002 scans: the flip-flop Q1 / Q4 through R3 / R14 / R35 +
CR1, Q5's attack current into C5, Q6 / Q7 / Q8 the decay and the SUSTAIN clamp, Q21 / Q22 the output, CR3's peak
detector, Q20 / Q12 / C1 the trigger that starts the attack), `scripts/minimoog_contour_study.py`,
`scripts/minimoog_contour_times.py`, `tests/test_minimoog_contour.py` (3 tests). Measured (production): attack
(knob 0 to 10) 3.1 ms to 7.7 s to the peak, decay's 1/e time 0.9 ms to 9.6 s, against the panel's 1 ms - 10 s; the
peak 4.86 V at the output (a germanium CR3 would put it ~0.3 V lower: the 1N4148 stands in); SUSTAIN holds E7 at its
setting + a diode drop (0.5 -> 2.2 V); a key-up releases through DECAY. Calls made: the DECAY switch is `decay_on`
(1 = release follows DECAY, pin 2 open; 0 = pin 2 tied to V-TRIG, an instant release); SUSTAIN is a 5K pot from the
panel's +10 V to ground; the +9.3 V is ideal. Idle the output sits at 0.16 V (the VCA's -40 dB leak): from Q8 / CR2's
drops, not chased. **The loudness section is in the same file** (same flip-flop, Q16 attack, Q17 / Q18 / Q19 decay and SUSTAIN,
output Q3 / Q2 a Darlington follower, so out = envelope - 2 drops: peak 5.7 V, idle -0.46 V; it shares the trigger bus,
V-TRIG and the DECAY switch; `lattack`, `ldecay`, `lsustain` provisional pot assignments; R27 read 16.9K, the sheet's
'169K' taken as the filter divider's value). `tests/test_minimoog_contour.py` has 4 tests. Not yet: the join to
pin 16 / pin 9 (AMOUNT OF CONTOUR, R59), the keyboard circuit (current source, S&H, glide), the app.

**MM4, the contours joined and played (2026-11-07):** `config/circuits/minimoog_voice.yaml`, GENERATED by
`scripts/make_minimoog_voice.py` (`--check`) from the filter board and the contour file: the loudness contour is the
VCA's pin 9 (into R59), the filter contour feeds AMOUNT OF CONTOUR (R17 5K to ground, wiper into R74; `amount` 0 = the
old fixture), the keys' gate is pin 20 (the control input `gate`, `gate_on_v` 5 V provisional). The panel's wiring
read on Fig 9-17 (sources README): every contour pot placed but the filter SUSTAIN's top end (taken as +10 V).
- The app's `minimoog_voice` (Play: "Minimoog Voice"; the old `minimoog_filter_board` stays): **three threads**, the
  filter with the trigger's CR10 / R60 | the VCA | the contour board, coupled hold. As one solve with the VCA cut it
  ran ~1.8x real time live. Two things made the contour's cut work (each found from a failure): every node the contour
  part owns needs a linear DC path there (R23 moved beside the flip-flop so V-TRIG has R23 / R32 to +9.3 V; the
  first tries failed singular at V-TRIG, a node with only diodes in its owner, and at C4's feed), and a saturated
  switch must not drive a cut (Q20 / Q12 with the contour; cut at R60 100K into C7 instead of their collectors,
  where a sample-late saturated current diverged). Live with a key held: **59-89 % load, 0 dropouts** in 10 s.
- `scripts/minimoog_gate_check.py --voice [--set k=v]`: the partition vs one solve on gated saws, the cut's lag
  removed: -52 dB at the defaults, -49 dB at ATTACK / DECAY 0, -47 dB at EMPHASIS 0.9, -48 dB at AMOUNT 0.6; both
  together -26 dB, all of it phase (10 ms envelopes within 0.04 dB, band energies within 0.05 dB: a sample-late
  sweep of a ringing filter).
- **The click** (the MAIN OUTPUT above 150 Hz, no audio, the app's partitioned draft): key-down 48.6 mV with the old
  bare gate, **2.65 mV** at the default contours (ATTACK 0.1, DECAY 0.3); key-up 12.5 -> 0.08 mV. At ATTACK / DECAY 0
  (3 ms / 1 ms) 55 mV: the contour's own snap, as the instrument has.
- `tests/test_minimoog_contour.py` (5 tests, one through the app's partition); fixtures and varimu-circuit agree.
- Open: the keyboard circuit (the current source, S&H C9, glide Q13 / Q10, R2) is not built, the keys still reach the
  filter through the KEYBOARD CONTROL fixture; the filter SUSTAIN's top end; the 1N34A germanium diodes (1N4148 stands
  in: peaks ~0.3 V high); the 2N3392 (2N3904 stands in); EXT. S-TRIG; the +9.3 V decoupling (Q26); the user listens.

**MM4, the keyboard circuit built (2026-11-07):** `config/circuits/minimoog_keyboard.yaml` (Fig 9-7's circuit No. 1 traced
on the 002 scan, values checked against Table 7-6: sources README "The keyboard circuit, traced"), joined into the voice by
`make_minimoog_voice.py` in place of the KEYBOARD CONTROL fixture; `scripts/minimoog_keyboard_study.py [--write]`,
`tests/test_minimoog_keyboard.py` (5 tests).
- **The string and its current source:** Q9 / Q11 (2N3906 / 2N3904, the sheet's alternates) set **8.437 mA** into the
  43 x 10 ohm string (Fig 9-7 says 8.33, Fig 9-17 8.48): **84.37 mV a key, 1.0124 V an octave**, 0 V at the lowest F
  (MIDI 41, provisional), 3.628 V at the top C. The keys are the control input `key` on the pitch bar (through the tap's
  ~100 ohm); `key_v_per_semitone` is 10 ohm times the measured current (`--write`), and the app's `Feed::Key` reads it.
  Calls made: the string is one 430 ohm resistor (only its total loads the source); the tap is an ideal source the app
  holds at the last key, so the pitch bar never floats (the hardware's C9 would creep toward +10 V through R53 at key-up,
  ~3 V/s, inaudible while Q13 holds C6); the voice doesn't carry the current source (a constant on ideal rails; revisit
  with the supply board, MM5).
- **The trigger is the real bus:** a key closes the trigger bus onto the +10 V bar (the keyboard wiring diagram), so the
  gate is now +10 V, not the old 5 V. The contact is a diode from the control input `gate` (`gate_on_v` 10.55, so the bus
  sits at +10 V; `gate_off_v` -10 V): at key-up the bus floats down with C13 through R34 (1 ms), as the hardware's does.
  The same bus is the contour board's pin 20.
- **Tracking** (a key held, production): the output follows the bar within -2 / +11 mV over the keyboard, gain 1.0035
  (+4 cents an octave: the matched pair's base currents through R30 10K against the tap's 100 ohm; the oscillators'
  Scale trims take it out).
- **Glide** (an octave, the low A to the next, key held): GLIDE off 0.05 ms (1/e); on, 1/e 8 ms at 2.5, 32 ms at 5,
  105 ms at 7.5, 323 ms at 10 (10-90 %: 0.42 s). **Down is ~2.5x slower than up** (83 vs 32 ms at 5): C6 sits a JFET
  Vgs (~1.3 V) under the output, near 0 V, so the op-amp's +9.9 V swing drives it up with ~10 V and its -4.44 V swing
  (R59 / R54 with Q24 off) down with ~4.4 V. A property of the circuit; its size rests on the stand-in JFET's Vgs.
- **Hold:** after key-up Q13 opens (CR5 pulls its gate to ~-9.3 V) and C6 holds: the output moves < 0.1 mV in 2 s.
  Before the first key after power-up the output sits at C6's DC solution (1.55 V here), as an unplayed instrument's would.
- Stand-ins: the 2N4303 (Q13 / Q10, no card) is the 2N3819 (IDSS ~11 mA, VGS(off) -2.5 V; nearer the 2N4303's 4-10 mA
  than the 2N5457); the 2N3392 pair the 2N3904; Q24's 2N4058 the 2N3906; CR5's 1N4004 the 1N4148.
- **Filter Scale re-trimmed on the real keys:** the filter board's fixture now gives the string's volts (0 V at the low
  F, 84.37 mV a key), and `minimoog_vcf_trim.py --scale-only` runs Folkman's Filter Scale on the A keys' real volts:
  SCALE 0.4658 -> **0.4014**, tracking 440.5 / 876.4 / 1756.2 / 3509.4 Hz (0.992 / 1.003 / 0.999 octaves a keyboard
  octave). REGEN CAL and RANGE don't read the keys and stay. The script's regeneration search failed on the MM2 board
  (a saturated oscillation read as no onset; it hadn't been rerun since MM2): fixed, not rerun.
- Pre-flight counts a JFET's channel as a DC path (C6 is held only by Q13).
- **Live:** the app's `minimoog_voice` gets GLIDE and the GLIDE switch; three threads, the keyboard's S&H and glide beside
  the VCA (cuts at the tap resistance into C9, at R65 into C13, at its output into KEYBOARD CONTROL's 300K / 150K; the
  contacts stay in the first part with the control inputs): **61-86 % load with a key held, worst block 121-126 %, 0
  dropouts** (the keyboard in the first part: 79-90 %, worst 135 %). The gate check, partition vs one solve: -49.8 dB at
  the defaults, with GLIDE on and at ATTACK / DECAY 0; -40.5 dB at EMPHASIS 0.9 (the VCA cut's sample of phase).
- **Open, not understood:** with the keyboard on a thread of its own (four parts, in any order) the loudness contour's
  attack ends early (~5.4 V instead of one solve's 6.8 V; sustain 4.4 V instead of 5.1 V): the gate check fell to -30 dB.
  The keyboard shares no node with the contour board (only with the first part), a fourth part holding only the
  keyboard's rails changes nothing, and the slot wiring in `stream.rs::couple` reads consistently. Beside the VCA it
  matches one solve to the printed digits. Worth a look at circuitsim's partition with three parts sourcing from the first.
- Open: the Model D's keyboard is low-note priority (the string), the app's keyboard logic last-key (a device option
  would make `Feed::Key` and the test oscillator follow the lowest held key); the user listens (glide, the bigger trigger).

**MM3's prerequisites (2026-11-07):**
1. **The uA726 built: `UA726@1`** (`library.build_ua726`, `tests/test_ua726.py`). Fairchild's sheet (1979 Linear Op Amp
   Data Book pp. 7-33 to 7-35, extracted to `data/datasheets/transistors/fairchild_ua726_1979.pdf`), its current gain
   curve digitized (`data/datasheets/fairchild_ua726_hfe.csv`, provenance sidecar; it agrees with the sheet's bias
   currents: hfe 200 at 10 uA, 400 at 100 uA). BF, ISE, NE, IKF fitted at the die's 78.4 C up to 2 mA (rms 14 in hfe;
   above 2 mA the sheet's gain falls as ~1 / Ic, steeper than Gummel-Poon's roll-off, not fitted: the Minimoog runs
   0.05-20 uA); IS 1e-15 A and VAF 100 V provisional; Cje, Cjc the sheet's 1 pF. A circuit runs the pair as one model
   instance with `temp_c: 78.4`: 21.0 mV of Vbe an octave (the fitted IKF adds ~0.2 % at a few uA, a scale error the
   Scale trim takes out). Fig 9-1's "20.5 +-0.4 mV an octave across pins 1 and 10" is the summer's scale (R27 selected),
   not the bare pair's: not a check on the die temperature. The heater regulator (Q3-Q8) stays out until the thermal node.
2. **The LM393: decided, not built.** The sheet's open-collector output to V- (-10 V on board 1: the reset pulse swings
   "+10 .. -10") can't be made from the `opamp` macro and the existing parts (it is ground-referenced, and circuit files
   have no VCCS part), so it needs builder work in both languages: an `opamp` option `open_collector` adding an output
   NPN on a V- node, driven from the integrator node through a VCCS. Its speed (the sheet's ~1.3 us response) only
   matters inside the ~1 us reset, which item 4 turns into an exception generated from a full-physics reference of the
   core (integrator, comparator, reset JFET): so the comparator's form is decided with that reference, next session.
3. **The E112:** the 2N3819 card stands in (provisional; an N-channel switch, as the plan said), to be named in the VCO file.
4. **The reset exception** and 5. `minimoog_vco.yaml` and Folkman's tuning: not started. Next: read
   HYBRID_PHYSICS_PLAN.md's H1-H4 (the 884 saw's M1 island and K kernels) against board 1's core and propose the split
   (what is the island, what the kernels tabulate: the ramp's slope from the expo converter's current, the reset's
   charge and dead time, HI END COMP's correction).

**MM3, the reference built (2026-11-09, worktree `minimoog`):**
- **The LM393 and the TL081's slew** (prerequisite 2): the `opamp` macro's options `slew_v_per_s` (the
  input stage limited by antiparallel clamp diodes: small signal unchanged, the integrator's current
  capped at slew x C) and `open_collector: BJT` with a fourth node `v_minus` (an output NPN driven from
  the integrator node, its emitter on V-); both builders, refused without a clamp
  (`tests/test_minimoog_vco.py`, the app fixtures' agreement). The LM393's gain-bandwidth and slew
  fitted to TI's two response times (1.3 us at 5 mV overdrive, 0.3 us TTL; `scripts/fit_lm393.py`,
  `config/circuits/lm393_test.yaml`): 37 MHz, 5.4 V/us internal. TL081 / LM393 figures in
  data/datasheets/opamps/README.md.
- **The E112** (prerequisite 3): `PN4092@1` (Central's card of the 2N4092, the J112's 50 ohm switch
  class) stands in; the 2N3819 (~100 ohm) left C7 at ~4 V, the reset incomplete.
- **`config/circuits/minimoog_vco.yaml`** (prerequisite 5): oscillator 1 with the primary summer, its
  summer, the expo (UA726@1 at 78.4 C), the core, the saw / triangle / rectangle shapers; RANGE as the
  ladder's volts (a switch), TUNE, PITCH WHEEL, PW; the keyboard's volts on the control input `key`.
  The board re-read (data/schematics/minimoog/README.md, "Core": the 002 GIF's dots at IC7's output and
  node 2 are crossings; R31 is the HI END trim, IC4A the +5 V reference).
- **Folkman's tuning** (`scripts/minimoog_vco_trim.py --write`): SHIFT, SCALE, HI END, OCT ADJ solved
  jointly on the reference for 440 / 3520 / 4186 Hz on 2' and 110 Hz on 8': all within 0.05 cents, 32'
  -0.4 cents untrimmed.
- **The reset studied** (`scripts/minimoog_vco_study.py`, reports/minimoog/vco/README.md): the
  reference needs 12.288 MHz with error control (205-280x slower than real time per oscillator; at
  3.072 MHz 2 cents rms of period jitter from the reset's unresolved end state). **Every direct
  candidate fails**: the draft, draft-2x and production stall (the solver's large step damps the
  ~0.3 us comparator / Q4 loop into a DC equilibrium), production at 8x jitters 17-24 c and stalls at
  the top C, M1 islands up to 128x (no error control inside) are tens to hundreds of cents off.
  So M1 isn't a render tier here, unlike the 884: the options (K for live and renders, the reference
  for renders, event location in circuitsim) are with the user (MINIMOOG_BACKLOG.md, Next 1); nothing
  of K built.

**MM3, technique K built (2026-11-09; the user's call: K for live play and renders):** the reset
and the rectangle's comparator as event kernels generated from the reference
(`scripts/minimoog_event_tables.py` -> `config/events/minimoog_osc_{reset,edge}.json`; the circuit's
`exceptions` XRESET / XRECT with `renders: true`; HYBRID_PHYSICS_PLAN.md H5 for the machinery).
Against the reference at the draft's 96 kHz and production's 192 kHz: pitch within 0.6 cents from
27.5 Hz to 4186 Hz, the saw and rectangle as clean as the reference (-53 to -107 dB inharmonic),
the rectangle's duty within 0.6 % of it; the triangle at the draft -31 to -70 dB (the reset's
band-limited jump through Q6's fold; production -50 to -97). Draft 0.47-0.89x real time; the app's
`minimoog_vco` (draft-2x, Newton 1e-3) plays it at 41 % load, no dropouts
(reports/minimoog/vco/README.md). Tests: `tests/test_minimoog_vco.py`, circuitsim
`tests/reset_events.rs` (Rust vs Python on `fixtures/events/reset_events.json`), the app fixtures'
agreement.

**MM3 done and MM5 built (2026-11-09, unattended session, worktree `minimoog`): the voice is a Model D.**
`config/circuits/minimoog_voice.yaml` (GENERATED by `scripts/make_minimoog_voice.py`) now has board No. 1's three
oscillators, the mixer, board 3's noise generator and modulation mix, board 4's external pre-amp and the panel's
control summing; the app's `minimoog_voice` plays it (the test oscillator off). Readings in
data/schematics/minimoog/README.md, "Oscillators 2 and 3, the RANGE path, the mixer".
- **Oscillators 2 and 3** (`config/circuits/minimoog_osc2.yaml`, `minimoog_osc3.yaml`, GENERATED from oscillator 1's
  file by `scripts/make_minimoog_oscillators.py`): Fig 9-2 draws the same core, expo and shapers value for value, so
  oscillator 1's event tables serve all three. Differences: SHIFT through 82.5K (R53 / R93; oscillator 1's R13 69.8K),
  OSC 2 / 3 FREQUENCY (5K over 5.1K, through 402K: +- a fifth), OSC 3 CONTROL (Q2 an E101 passing the primary summer
  to oscillator 3's SCALE, Q3 / Q19 2N3904 switching it off from 16A, R97 121K the FREQ pot's wider range: off, the keys
  no longer play oscillator 3), REV SAW 3 OUT (Q20 inverting the sawtooth, 4.6 V p-p). E101 stand-in: the 2N5457 card.
- **The RANGE path** (in oscillator 1's file, shared): the -5 V reference (IC2 741, Q1 2N3906, R8-R11, C3), the panel's
  ladder R25-R29 (-5.0000 V at 2', 571.4 mV an octave, LO 0 V), each RANGE switch's wiper into board 6's 741 follower:
  the ideal range sources are gone.
- **Folkman's tuning on the instrument** (`scripts/minimoog_vco_trim.py [--circuit NAME] --write`): KBD PITCH is now
  the keyboard circuit's output (its gain 1.0035: +4 cents an octave untrimmed), fitted as a straight line over the
  keyboard (residual <= 0.35 mV) into each oscillator file's `key_*`; then SHIFT, SCALE, HI END and OCT ADJ on the
  12.288 MHz reference. Within 0.07 cents at the low A, high A, top C on 2' and the low A on 8' for all three; 32'
  (untrimmed) -0.34 / -0.22 / -0.33 cents. In the voice (draft-1x, partitioned) A3 on 8' plays 220.05 Hz (+0.4 c).
- **Each oscillator an island at 96 kHz** inside the voice's draft-1x (48 kHz): K's tables need 96 kHz (at 48 kHz the
  top C ran at 6.26 kHz), and the whole voice at draft-2x ran ~1.6x real time. Two engine / builder additions: a
  section's `substeps_in: events` (both builders: the island only in a build with event kernels; the literal reference
  at its own rate; before, kernels always dropped their island), and a named partition group of multi-rate sections at
  one rate is a part of its own (circuitsim `partition.rs`: three islands at the same rate on three threads; before,
  sections were grouped by rate only). Also: an `owns` node no other part has stays the claimant's (a switch can leave
  an island's output unused).
- **The mixer** (Fig 9-17): each source onto its 25K LEVEL pot, through 33K (NOISE 11K) and its ON switch onto board
  4's pin 4 (C27); the waveform switches (six positions; their second pole PULSE WIDTH IN from the panel's -1.5 / -2.5 V
  divider), the triangle-sawtooth mix on oscillators 1 and 2, REV SAW on 3. OSC 1 at 8, OSC 2 / 3 at 0 by default.
- **The noise generator** (`config/circuits/minimoog_noise.yaml`, board 3 circuit No. 3): Q15's emitter-base junction
  in avalanche stands in as its breakdown voltage and dynamic resistance (provisional) with its noise as a new part,
  **`noise_source`** (both builders: a white current always on, a sound source not an imperfection; the IR's noise
  block emitted for it with the circuit's noise off), then the board's amplifiers and pinking legs as drawn: white
  flat (-0.14 dB / octave), pink -3.17 dB / octave (ideal -3.01). Folkman's "Noise Level ... -5dB maximum in the white
  position" read as 5 dB under a sawtooth at the mixer: R26 trimmed to 0.484 (`scripts/minimoog_noise_trim.py`); the
  avalanche density chosen so R26 sits mid-travel (provisional). Red noise not drawn.
- **EXTERNAL INPUT** (board 4 circuit No. 12): the jack onto R9 1 Meg audio into the pre-amp (+46 dB at audio), out
  through R46 33K: 0.1 V at the jack full scale; at EXT 10 it clips (17 V p-p), as the Model D overdrives.
- **MM5's panel summing** (Fig 9-17) on the filter board itself: CUTOFF is R11 5K across +-10 V through R55 200K
  (`cutoff`, a rotation; Folkman's CUTOFF -1 is 0.4), J2 empty through R51 100K, FILTER MOD through R52 33K.
  `minimoog_vcf_trim.py --write` re-run all three procedures on it, twice (SCALE moves RANGE's 440 Hz: 425 Hz after
  one pass): REGEN CAL 0.845, RANGE 0.563 (was 0.307: CUTOFF -1 is now -2 V at the wiper), SCALE 0.649; tracking
  0.989 / 1.003 / 1.004 octaves per keyboard octave from 440 Hz. CUTOFF's default is 0.4, the procedures' setting.
- **The modulation mix** (board 3 circuit No. 15): pink noise and oscillator 3's selected waveform through 24K each,
  MOD MIX R3 25K between them (wiper on ground), Q18 / Q17 / Q7 an inverting summer (-2.1), out through R57 1K to the
  left-hand controller's MODULATION wheel (50K audio: the app's mod wheel), its wiper onto OSC MOD (R5 100K into the
  primary summer) and FILTER MOD (R52). Red noise for the mod (SW14's other pole) not drawn.
- **Levels** (`full_scale` out 12 V; draft-1x, partitioned, A3 held): no key 0 V; oscillator 1 at the defaults
  -18.4 dBFS peak; all three at 10 -11.5; white noise at 10 -18.6; pink -11.2; a 0.1 V sine at EXT 10 -11.5 dBFS. With
  every level at 0 a key still moves the output ~93 mV (a sub-audio step through the VCA, not chased).
- **Live** (`examples/play.rs --hold-bass 1 --from 57 --mute`, eight threads: the panel and first part | the ladder |
  noise and modulation mix | the VCA, keyboard | the contours | three oscillator islands): **~100 % load, dropouts**
  (72 in 13 s): every part 0.57-0.79x real time, the machine saturated by eight spinning threads. Tried: nine threads
  (worse, 107 %), shorter spin waits (worse), Newton 1e-4 / 1e-3 (pitch unchanged, no speed). The partition against the
  rest as one solve (`minimoog_gate_check.py --voice`): -44.6 dB, 10 ms envelopes within 0.05 dB; at ATTACK / DECAY 0
  -34.8 dB, envelopes within 0.79 dB (the cuts' phase).
- Tests: `tests/test_minimoog_voice.py` (generated files current, the islands' rule and refusals, silent before a key,
  -18 dBFS, the pitch; oscillator 3's control and reverse sawtooth).
- Calls made (faithful to the Model D where the schematic decides; the rest provisional, in the sources): the LEVEL pots
  linear; OSC 1 at 8 and the others at 0 by default; the sawtooth on every waveform switch by default; Folkman's noise
  "-5 dB" read against a sawtooth; the E101 as a 2N5457; Q15's avalanche as 7 V and 20K; EXT's full scale 0.1 V.

## CPU while another session runs

`CARGO_BUILD_JOBS=3`, builds started with `cmd /c start /belownormal /wait /b ...`; one render
at a time; `OPENBLAS_NUM_THREADS=1` for numpy-heavy scripts.
