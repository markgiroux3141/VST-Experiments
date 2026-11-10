# Minimoog backlog

Open items from the Minimoog Model D build ([MINIMOOG_PLAN.md](MINIMOOG_PLAN.md); sources
[data/schematics/minimoog/README.md](../data/schematics/minimoog/README.md)), collected 2026-11-07
when the work paused. The plan's Status section has the measurements behind each item.

## Next (2026-11-09: the voice is a Model D; MINIMOOG_PLAN.md "MM3 done and MM5 built")

1. **The user listens** to `minimoog_voice`: three oscillators (RANGE, FREQUENCY, WAVEFORM, OSC 3 CONTROL), the mixer
   (NOISE white / pink, EXTERNAL INPUT through the pre-amp), the MODULATION wheel (MOD MIX, OSC MOD, FILTER MOD), CUTOFF
   as the real pot. The stand-alone `minimoog_vco` too.
2. **Live load** (MINIMOOG_PLAN.md "Real time", 2026-11-09): what nobody hears isn't built (a section's `when`), so the
   default panel plays on five threads at ~70 % with about one dropout a minute (was ~100 %, ~50 in 13 s); two
   oscillators 85-94 % with dropouts, three 1.02x and the full patch 1.25x offline. The user's calls:
   (a) **Newton 1e-4** (the only lever left that the default and the bigger patches feel: default 0.64x, three
   oscillators 0.88x, full 1.06x offline; costs the ladder's resonance ~1 cent, harmonics within 0.12 dB);
   (b) a bigger buffer (the Suitcase's 50 ms: the 5-9 ms spikes at key-down and at each contour's attack end are what
   drops out now);
   (c) not done, no sound change, in order of payoff: pinning each partition thread to its own physical core (8-12 % at
   eight threads, nothing at five; `GetLogicalProcessorInformationEx`, the caller's thread too, a process-wide core
   allocator for a chain end's streams); thread priority (SUITCASE_REALTIME_PLAN.md idea 2, untested); fewer Newton
   iterations at the flip-flops' flips (junction limiting through a regenerative flip; a better predictor);
   (d) for the full patch something structural: the ladder alone is 1.05x real time at 1e-5 with every source on.
   Restarts: a LEVEL leaving or reaching 0, a mixer switch, OSC MOD / FILTER MOD restart the live stream (~0.37 s).
2b. **A contour's flip lands either way in the partition** (MINIMOOG_PLAN.md "Real time", "Found, not fixed"): the
   filter flip-flop's flip at its attack's end sometimes ends the loudness attack too (5.41 V instead of 6.87 V, ~1.9 dB
   quieter through the decay), at single settings (the default panel's A3 at 1e-5: `voice_bench --note 57 --probe
   k_envl`), in old and new layouts; the one solve never did. Options: the contour board at a finer step (an island; its
   flips are faster than a sample), a smaller step only at a flip (local error control for that part), or the flip as an
   event (technique K, a third kind). Worth deciding before the user's listening judges the envelopes.
3. **The triangle at the draft** (MINIMOOG_PLAN.md MM3's K): the reset's band-limited jump through Q6's fold; options:
   the fold's node fed the reset's physical ramp (as the edge follows it), the shaper's own event, or 192 kHz islands.
4. **R135-R137** (Fig 9-1 note 4: "factory selected (if necessary) to achieve 50 % +-1 % rect. duty cycle"): the
   reference's rectangle runs 51.6-52.2 %; a duty trim selecting R135 (220K from +10 V onto the sawtooth's pin) would
   bring it to the manual's 50 %. Not drawn yet.
5. **Red noise** (board 3: R12, C7, C8, Q6, R28 / R23, C10, C28, R59: not traced in full) and SW14's second pole (pink /
   red to the modulation mix); the overload lamp driver (circuit No. 11).
6. **The sub-audio step at key-down** with every mixer level at 0 (~93 mV at the MAIN OUTPUT, -42 dBFS peak).
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
