# Minimoog backlog

Open items from the Minimoog Model D build ([MINIMOOG_PLAN.md](MINIMOOG_PLAN.md); sources
[data/schematics/minimoog/README.md](../data/schematics/minimoog/README.md)), collected 2026-11-07
when the work paused. The plan's Status section has the measurements behind each item.

## Authenticity first (2026-11-25, the user's direction)

The user's priority: one really good, simple oscillator sound authentic to a Model D (how it
behaves when keys are pressed and notes connect, the parts' interrelations), not more oscillators,
effects or compute. Worked in this order, each measured; nothing here adds threads at the default
panel.

**Closed (2026-11-25, the user's call).** Items 1-2 changed how it plays; items 3-6 found every
realistic part difference within a cent or a few percent (the 2N4303 kept, the trims' UNIT # not
built: option A). The model follows the drawing; whether it sounds like a real Model D was never
compared. Reopen for something the user hears as wrong (the ladder's TIS97 stand-in first), or for
item 8's recordings. Not measured yet: the voice's production render speed (`examples/voice_bench.rs
--quality production`; estimated 10-20x slower than real time from the 670's production / draft ratio).

1. **Playing behaviour (no compute). Done 2026-11-25.**
   - Single trigger: `panel::SINGLE_TRIGGER` (the voice, the VCO); Play's Retrigger starts off for
     them (the trigger bus stays on +10 V while any key is down: a legato key changes the pitch, the
     contours carry on).
   - Low-note priority: `panel::LOW_NOTE_PRIORITY`, `Playing::low_note` (written in a take's JSON only
     when set, so older takes keep their bytes), `Player::set_low_note`; the Performer sounds the
     lowest key held (the string). Test: `performance::tests::low_note_priority_...`.
   - Start phases: the three oscillators started at one DC point (oscillator 2 12 deg from 1, ~20 deg
     after 2 s: a unison was one louder oscillator, after every restart). Oscillators 2 and 3 now
     start their C7 (C18 / C29) at 1.7 / 3.4 V (`c7_v0_v`, make_minimoog_oscillators.py `START_V`):
     96 / -143 deg from oscillator 1. Oscillator 1 and the stand-alone VCO unchanged.
2. **A source by its mixer switch only (no compute at the default panel). Done 2026-11-25.**
   `make_minimoog_voice.py`'s WHEN: an oscillator or the noise is built while its ON is on, never by
   its LEVEL, so LEVEL turns in place from 0 (play.rs `--turn osc2_level=0,0.5`: 0 restarts, knob to
   ear 91 ms, was a 368 ms restart). OSC 2, OSC 3 and NOISE now default to OFF. With their 33K
   summing resistors off the bus, oscillator 1 alone reads -17.9 dBFS peak (was -18.3): the real
   mixer's own loading.
3. **A unit's own parts (values only).** Seeded tolerance draws per unit (a UNIT # control), baked by
   the generators (the Rust builder refuses spreads), then Folkman's procedures re-run on the drawn
   unit (oscillator trims on the 12.288 MHz reference, slow: once per unit), so trims leave real
   residuals: tracking errors of a few cents per oscillator (a unison beats differently up and down
   the keyboard), ladder mismatch (even harmonics, a little control-voltage thump on fast filter
   contours), contour times, the rectangle's duty. The start phases (item 1) belong in the draw too.
   **Measured 2026-11-25 (nothing built):**
   - *The ladder: not worth it.* `scripts/minimoog_ladder_mismatch.py` (each ladder transistor its
     own instance, SPICE area drawn +-12 %, ~+-3 mV of Vbe; the filter board's printed note matches
     its expo pair Q26 / Q28 to +-3 mV) against the nominal voice, three draws: the key-down thump
     with no source and AMOUNT 1, ATTACK 0 (414 mV peak nominal) moves -0.3 to +4 %; H2 of a sine at
     EXT moves < 0.02 dB driven hot (-22 dB) and <= 0.3 dB at 1 mV (-52.4 dB). The voice's own
     asymmetry (output amp, VCA, pre-amp) swamps the ladder's: reports/minimoog/units/ladder_mismatch.json.
     The thump itself (414 mV, -29 dBFS, nominal) is backlog Next 6's, larger at full AMOUNT.
   - *The oscillators: the trims take the draws out.* `scripts/minimoog_unit_study.py` (oscillator
     1's 69 parts drawn in their printed classes, Folkman's four trims re-solved on the 12.288 MHz
     reference, 7 Newton iterations, ~75 min while other runs shared the cores; seed 1 only, seed 2
     stopped): untrimmed the unit ran +203 to +254 c; trimmed, it tracks within 1.0 c of the nominal
     unit at 11 keys (2': within 0.2 c; 8' up to 0.7, 32' up to 1.0, where only OCT ADJ's one point
     holds it). So two oscillators drawn and trimmed would beat differently across the keyboard by at
     most ~1 c: subtle (the user's rule: verified, move on). reports/minimoog/units/study.json.
   - *What would make a unit audible instead:* how well the technician trims. Folkman's trims here
     are solved to 0.05 c; a bench with a frequency counter or by ear leaves each trim point off by
     its resolution, and that error is a values-only change (no re-trim, no compute): SHIFT's error a
     constant offset, SCALE's a cents-per-octave tilt, OCT ADJ's an offset per footage. Its size needs
     a source (Folkman's text, benmook.com minimoog2.pdf, may state the tolerances he tunes to). This
     is the next step of item 3.
   - *The technician's trims: sized 2026-11-25, nothing built; options to the user.* Folkman's text
     (read in full: 24 pages, 7/73) states methods, not tolerances: a frequency counter at the main
     output, or "Visualign" (the overload lamp's blink against the A-440: a unison at the low A, the
     A-440's 8th harmonic at the high A), "repeat until no further improvement is attainable", the
     octave trimmer for zero beats on 8', then "check tracking between any two oscillators and make
     any necessary touch-up adjustments". Moog's own service manual (archive.org) has no adjustment
     text; a fan's tuning guide on ManualsLib gives targets only. Its only numbers: the A-440 "on
     frequency, within 1 Hz" (a common offset, taken out by TUNE), the pitch wheel 15.0-15.6 K in its
     detent, the rails to 10.00 V on a 0.1 % DVM. So a trim point is off by its method's resolution
     (provisional: model knowledge): a 1 s counter gate +-0.5 Hz, a zero beat by ear +-0.33 Hz (a
     beat slower than one per 3 s). `scripts/minimoog_trim_tolerance.py` (pitch space only: the
     SHIFT / SCALE line, HI END's term ~ the frequency, OCT ADJ per range step; no circuit runs) ->
     reports/minimoog/units/trim_tolerance.json, 4000 units, by ear (on the counter the solo figures are up to 40 % larger, the unison's the
     same):
     one oscillator, retuned with TUNE at the second A on 8': its shape across the keyboard within
     0.7 / 1.9 c (p50 / p95) on 8', 0.9 / 2.4 c on 2'; a footage switch moves it 0.3-0.7 / 0.8-1.7 c.
     Below hearing (the user's rule: verified). Two oscillators in unison (oscillator 2 touched up
     against 1 at the A's, then FREQUENCY set for zero beat at the second A on 8'): a beat appears
     along the keyboard, at most 0.47 / 1.27 Hz on 8', 0.19 / 0.54 Hz on 16', 3.0 / 8.0 Hz on 2'. The
     keyboard string (43 x 10 ohm 1 %, each uniform +-1 %, a bound) puts a key off the trimmed line by
     up to 2.6 / 4.4 c, common to every oscillator (no beating), a semitone's own error <= 1 c.
     Options (the user's):
     A. Nothing built: solo it's under hearing.
     B. A UNIT # for the trims, audible only in unison patches: per unit, each oscillator's four trim
        points drawn in that resolution (oscillators 2 / 3 touched up against 1), mapped to r14_at /
        r16_at / r31_at / r18_at through a 4 x 4 sensitivity measured once per oscillator on the
        12.288 MHz reference (one trim Newton iteration's runs, ~10 min an oscillator), written to a
        units table the app applies as value overrides (UNIT 0 the factory unit, bit for bit; a value
        change updates the stream in place). No compute while playing.
     C. B plus the string per unit: a per-key table in place of `panel::KeyString`'s straight line (a
        Rust change); solo it's under hearing too.
4. **Stand-ins that shape the envelope and glide (values only):** a germanium diode card for the
   1N34A; a 2N4303 card for the glide JFETs (the down / up asymmetry, ~2.5x, rests on the 2N3819's
   Vgs); the TIS97. **Measured 2026-11-25:** Table 7-6 has CR1, CR3, CR6, CR8, CR10 1N34A and CR2,
   CR4, CR5, CR7, CR9 1N4004 (the file has all ten as the 1N4148; sources README "Parts lists").
   Microsemi's 1N34A sheet gives only limits (VF <= 1.0 V at 5 mA, IR <= 30 uA at 10 V): no card can
   be fitted from it. `scripts/minimoog_diode_sensitivity.py` (all ten diodes' forward drop ~0.3 V
   lower, SPICE area 750, an upper bound): the filter contour's peak 4.87 -> 4.50 V, its idle +0.18
   -> -0.11 V, the fastest attack 0.63 -> 0.58 ms (10-90 %), decay 0.88 -> 0.86 ms. A knob's worth
   of AMOUNT / CUTOFF, not a character: wait for a typical 1N34A curve (and germanium's reverse
   leakage, which would droop a held peak), then model only CR1 / 3 / 6 / 8 / 10. Also: the fastest
   attack is 0.6 ms 10-90 % (within the panel's 1 ms); the old "3.1 ms" was time to the rounded top.
   **2026-11-25, second pass:**
   - *The 2N4303: built and in.* InterFET's 2N4302-3-4 sheet gives limits only (IDSS 4-10 mA,
     VGS(off) -6 V max) but names its die, N0026S, whose geometry sheet has typical output curves
     as vector charts; its VGS(off) -2.5 V unit (IDSS 5.8 mA, inside the type's band) is digitized
     (`scripts/digitize_interfet_n0026s.py` -> data/datasheets/interfet_n0026s_output.csv) and
     fitted with the 2N5457's doping tail (`library.fit_2n4303`: VTO -3.23 V, BETA 0.516 mA/V^2, B
     1.55, LAMBDA 7.2e-3; 0.4 % at IDSS, within 9 % down the curves): `2N4303@1`, a modern process
     for the 1970s part. Against the 2N3819 on the keyboard circuit
     (reports/minimoog/units/glide_2n4303.json): glide 1/e at 5 up 32.4 -> 34.3 ms, down 82.7 ->
     83.8 ms (down / up 2.55x -> 2.44x: the asymmetry is the circuit's, C6 a Vgs under the output);
     the output 0.3-0.6 mV lower (-0.35 to -0.73 c, a near-constant offset TUNE takes out), the gain
     the same to 1e-4. Subtle, but it's the drawn part and values only: the keyboard (and so the
     voice) now pins it. The oscillator trims weren't rerun for it (~75 min each; the shift is
     inside a technician's resolution, item 3); `minimoog_vco_trim.py` reads the keyboard live, so a
     rerun takes it out.
   - *The 1N34A: still no curve.* BKC / Microsemi's sheet (the UCL lab's copy) has the same limits;
     no Sylvania-era sheet with typical curves was found online; the SPICE cards in circulation
     (LTspice groups, circuitjs) disagree by orders of magnitude in IS and carry no measurement.
     A typical curve is still wanted (a Sylvania or Hughes data book page, or a measured part).
5. **Circuit noise (small compute; measure first). Measured 2026-11-25: inaudible in pitch.**
   `scripts/minimoog_noise_jitter.py` (the voice at draft-1x with `noise=1`: 340 Johnson currents and
   56 transistor noises, oscillator 1's period from its ramp): A3's cycle-to-cycle jitter 0.218 c rms
   with noise, 0.219 without (the event kernels' numerical floor at 96 kHz); the output's rms the
   same to 5 digits; cost ~2 %. White noise on ~1 uA over a period is ~0.01 c (q / Q). A real VCO's
   wander is flicker (1/f) in the expo pair, and config/device_noise.yaml has no sourced KF for the
   uA726 or 2N3904: a source for it is the open item. A `noise` block on the voice would only add
   Play's Noise switch (off by default) and the output's hiss floor; not added.
   **The flicker, sourced 2026-11-25: inaudible, verified.** The 726's own sheet (the 1979 data
   book, p. 7-34, data/datasheets/transistors/fairchild_ua726_1979.pdf, the uA726C table) gives the
   pair's slow noise at IC 10 uA, RS <= 50 ohm: "Low Frequency Noise 4.0 uVp-p, BW 0.001-0.1 Hz",
   "Broadband Noise 10 uVp-p, 0.1 Hz-10 kHz", "Long-Term Drift 5.0 uV/week", offset drift 0.2 uV/C
   typical (2 max). At the expo's 20.5 mV an octave (Fig 9-1's R27 selection), that is 0.23 c p-p of
   wander over minutes, <= 0.6 c p-p faster, 0.3 c a week, 0.01-0.1 c a kelvin of ambient. The
   summers' and the reference's op-amp flicker enter at ~1 V an octave, orders lower. So no KF is
   needed for pitch; config/device_noise.yaml stays empty (a KF fitted to these figures would only
   matter with Play's Noise on).
6. **Slow drift. Measured from the parts list 2026-11-25: no strong source on this board.** Table
   7-4: C7 / C18 / C29 are polycarbonate (+-10 %; tempco roughly +-50-100 ppm/K, ~0.1-0.2 c per
   kelvin, model knowledge), the expo pair on the 726's regulated die, the summers 1 % metal-film
   networks. Building a thermal model would mean inventing an ambient process and the 726 loop's
   residual: wait for a measured drift figure (a reference recording, item 8, or a published one).
7. **Coupling through the supply (moderate; unproven):** the +-10 V regulators, the -5 V reference
   and the keyboard's current source on real rails, the heaters' current on them; whether the
   oscillators pull on each other is unknown: offline first. **Read 2026-11-25 (nothing run): a low
   prior.** Each oscillator's ramp starts at +10 V / 2 (R25 / R26 into IC4A) and its expo's reference
   current is +10 V / R30, so its pitch (I / (C dV)) cancels the +10 V rail to first order: ripple, or
   another oscillator's reset current (R33 2K: ~5 mA pulses) on a real rail's impedance, mostly
   doesn't reach pitch that way. What's left: the keyboard's current source (its reference R20 / R22
   on +10 V: key volts follow the rail; 1 mV of ripple is ~0.4 c at the top key, a hum-rate vibrato
   far below hearing), the -5 V reference's rejection (RANGE), and the comparators' thresholds. If
   picked up: Fig 9-8 (power supply No. 3, PDF page 10) for the regulators' output impedance and
   ripple, then one offline run with two oscillators a few cents apart, looking for pulling.
8. **A real reference:** no recording of a real Model D is in the repo; everything is checked against
   the schematic and Folkman. Direct recordings of single notes, glides, legato runs, filter sweeps,
   fast bass (the user fetches walled sources).

Left alone for now (the user's focus): red noise, the overload lamp, EXT S-TRIG, the headphone amp,
the feedback-loop trick, all three oscillators live. Small and only for those waveforms: the
triangle at the draft (Next 3), R135's duty (Next 4).

## Next (2026-11-09: the voice is a Model D; MINIMOOG_PLAN.md "MM3 done and MM5 built")

1. **The user listens** to `minimoog_voice`: three oscillators (RANGE, FREQUENCY, WAVEFORM, OSC 3 CONTROL), the mixer
   (NOISE white / pink, EXTERNAL INPUT through the pre-amp), the MODULATION wheel (MOD MIX, OSC MOD, FILTER MOD), CUTOFF
   as the real pot. The stand-alone `minimoog_vco` too.
2. **Live load** (MINIMOOG_PLAN.md "Real time", 2026-11-09): what nobody hears isn't built (a section's `when`), so the
   default panel plays on five threads at ~70 % with about one dropout a minute (was ~100 %, ~50 in 13 s); two
   oscillators 85-94 % with dropouts, three 1.02x and the full patch 1.25x offline. The user's calls:
   (a) done: Newton 1e-4 by default, Play's "Precise solver" for 1e-5 (MINIMOOG_PLAN.md "Second pass"): default
   0.68x, two oscillators 0.77x, three 0.92x, full 1.14x offline;
   (b) a 50 ms buffer: no dropouts in 60 s at the default panel and with two oscillators (the ~12-15 ms spikes at
   key-down, release and each contour's flip are what drops out at 20 ms);
   (c) not done, no sound change, in order of payoff: pinning each partition thread to its own physical core (8-12 % at
   eight threads, nothing at five; `GetLogicalProcessorInformationEx`, the caller's thread too, a process-wide core
   allocator for a chain end's streams); thread priority (SUITCASE_REALTIME_PLAN.md idea 2, untested); fewer Newton
   iterations at the flip-flops' flips (junction limiting through a regenerative flip; a better predictor);
   (d) for the full patch something structural: the ladder alone is 1.05x real time at 1e-5 with every source on.
   Restarts: a LEVEL leaving or reaching 0, a mixer switch, OSC MOD / FILTER MOD restart the live stream (~0.37 s).
2b. **Done: a contour's flip landing either way** (MINIMOOG_PLAN.md "Second pass"): hard steps (a step whose Newton
   needs 12+ iterations redone as halves, to h / 16). Left: the events' spikes (~12-15 ms; a better predictor through a
   regenerative flip, or the flip as an event, would shrink them).
3. **The triangle at the draft** (MINIMOOG_PLAN.md MM3's K): the reset's band-limited jump through Q6's fold; options:
   the fold's node fed the reset's physical ramp (as the edge follows it), the shaper's own event, or 192 kHz islands.
4. **R135-R137** (Fig 9-1 note 4: "factory selected (if necessary) to achieve 50 % +-1 % rect. duty cycle"): the
   reference's rectangle runs 51.6-52.2 %; a duty trim selecting R135 (220K from +10 V onto the sawtooth's pin) would
   bring it to the manual's 50 %. Not drawn yet.
5. **Red noise** (board 3: R12, C7, C8, Q6, R28 / R23, C10, C28, R59: not traced in full) and SW14's second pole (pink /
   red to the modulation mix); the overload lamp driver (circuit No. 11).
6. **The sub-audio step at key-down** with every mixer level at 0 (~93 mV at the MAIN OUTPUT, -42 dBFS peak), and its
   twin at key-up with the DECAY switch off: the note gone within 50 ms (the audio band down >100 dB), a sub-20 Hz
   offset of ~-64 mV left fading over ~0.3 s (`voice_bench --up 1.5 --set decay_on=0 --probe out`).
7. **The 726's heater loop** (drift), the comparator macro's slow-ramp delay (item 4 may make it moot).
8. **Python's YAML loader accepts duplicated keys** (the Rust builder refuses them): a duplicated `r11_ohm` in the filter
   board silently replaced the VCA's R11 for a moment this session. A load-time check in `varimu.circuit.spec` would
   catch it.
9. **The filter's procedures** now run on the real CUTOFF pot (CUTOFF -1 = 0.4); `minimoog_vcf_study.py`'s figures in
   the plan (MM1) predate it.

## Open from MM4 (contours and keyboard)

- **The filter SUSTAIN pot R18's top end:** taken as +10 V like its loudness twin R19; Fig 9-17's
  scan doesn't show it legibly. A question for the user (the 002 scan, R18 near the board 2 box).
- **The four-thread partition effect, not understood:** with the keyboard's S&H and glide on a
  thread of their own, the loudness contour's attack ends early (~5.4 V instead of one solve's
  6.8 V; the gate check fell to -30 dB). The keyboard shares no node with the contour board, and a
  fourth part holding only the keyboard's rails changes nothing. The app runs the keyboard beside the
  VCA, where it matches one solve. Worth a look at circuitsim's partition with three parts sourcing
  from the first.
- **Low-note priority:** the Model D's string sounds the lowest held key; the app's keyboard logic
  is last-key. A device option would make `Feed::Key` and the test oscillator follow the lowest key.
- **Stand-ins to replace when cards are found** (the 2N4303 glide JFETs are their own card since
  2026-11-25, `2N4303@1`: "Authenticity first" item 4): the 1N34A germanium diodes (1N4148: envelope
  peaks ~0.3 V high), the 2N3392 (2N3904), the 2N4058 (2N3906), CR5's 1N4004 (1N4148), the TIS97 ladder
  transistors (2N3904).
- **EXT. S-TRIG** (pin 19) isn't drawn.
- **The +9.3 V decoupling** (Q26, R62 / R63) is an ideal source.
- **The keyboard's current source on real rails:** the voice doesn't carry it (a constant on ideal
  rails); revisit with the supply board (MM5), where rail wander would move the key volts.
- **The pitch bar never floats:** the app holds the last key, so C9's creep through R53 at key-up
  (~3 V/s, inaudible while Q13 holds C6) isn't modelled.
- **`minimoog_vcf_trim.py`'s REGEN CAL and RANGE steps** haven't been rerun since MM2 changed the
  board (the regeneration search was fixed this session; only Filter Scale was rerun).

## Later milestones (the plan's)

- **MM5, the rest:** the +-10 V regulators (board 3's circuit No. 10), the keyboard's current source on them, the
  headphone amplifier, EXT. S-TRIG, the A-440.
- **The uA726's heater loop** as a thermal node (B6's pattern), if the drift is wanted.
- **MM6, bending:** after the user has played it.

## Listening (the user)

- The voice with the keyboard circuit: glide (down slower than up), the +10 V trigger's effect on the
  contours, the click at the default contours.
