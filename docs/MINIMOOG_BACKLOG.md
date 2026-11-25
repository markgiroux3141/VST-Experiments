# Minimoog backlog

Open items from the Minimoog Model D build ([MINIMOOG_PLAN.md](MINIMOOG_PLAN.md); sources
[data/schematics/minimoog/README.md](../data/schematics/minimoog/README.md)), collected 2026-11-07
when the work paused. The plan's Status section has the measurements behind each item.

## Authenticity first (2026-11-25, the user's direction)

The user's priority: one really good, simple oscillator sound authentic to a Model D (how it
behaves when keys are pressed and notes connect, the parts' interrelations), not more oscillators,
effects or compute. Worked in this order, each measured; nothing here adds threads at the default
panel.

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
4. **Stand-ins that shape the envelope and glide (values only):** a germanium diode card for the
   1N34A (the 1N4148 puts the contour peaks ~0.3 V high: how far the filter opens, how hard the VCA
   is pushed); check the fastest attack (3.1 ms against the panel's 1 ms) against it; a 2N4303 card
   for the glide JFETs (the down / up asymmetry, ~2.5x, rests on the 2N3819's Vgs); the TIS97.
5. **Circuit noise (small compute; measure first):** the voice has no `noise:` block, so periods are
   exactly deterministic. NH2's transistor noise gives the expo converter's shot noise at microamps
   and the comparator's noise: cycle-to-cycle jitter, the self-oscillating filter's wander. Measure
   the jitter and its cost before turning it on live.
6. **Slow drift (cheap):** the 726's heater loop (a thermal node per oscillator, B6's pattern) and
   C7's tempco: unison beat rates that wander, a warm-up from cold.
7. **Coupling through the supply (moderate; unproven):** the +-10 V regulators, the -5 V reference
   and the keyboard's current source on real rails, the heaters' current on them; whether the
   oscillators pull on each other is unknown: offline first.
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
- **Stand-ins to replace when cards are found:** the 1N34A germanium diodes (1N4148: envelope
  peaks ~0.3 V high), the 2N3392 (2N3904), the 2N4303 glide JFETs (2N3819; the glide's down / up
  asymmetry, ~2.5x, rests on its Vgs), the 2N4058 (2N3906), CR5's 1N4004 (1N4148), the TIS97 ladder
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
