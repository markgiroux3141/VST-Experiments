# Minimoog backlog

Open items from the Minimoog Model D build ([MINIMOOG_PLAN.md](MINIMOOG_PLAN.md); sources
[data/schematics/minimoog/README.md](../data/schematics/minimoog/README.md)), collected 2026-11-07
when the work paused. The plan's Status section has the measurements behind each item.

## Next (MM3, the oscillators)

1. **The reset exception.** Read HYBRID_PHYSICS_PLAN.md's H1-H4 (the 884 saw's M1 island and K event
   kernels) against board 1's core and propose the split: what is the island, and what the kernels
   tabulate (the ramp's slope from the expo converter's current, the reset's charge and dead time,
   HI END COMP's correction). The ~1 us reset (IC8B through C9 100 pF / R33 2K) is far below a
   sample.
2. **The LM393.** Its open-collector output to V- (-10 V on board 1) needs an `opamp` option
   `open_collector` in both builders (an output NPN on a V- node, driven from the integrator node
   through a VCCS). Decide its form with the reset exception's reference (item 1).
3. **`config/circuits/minimoog_vco.yaml`** (one oscillator), the E112 reset JFET as the 2N3819 card
   (provisional), `UA726@1` at `temp_c: 78.4`.
4. **Folkman's tuning procedure** (p. 12) as a trim script: Range trimpot for 3520 Hz at the high
   "A", Scale trimpot for 440 Hz at the low "A"; the waveshapes against the sheet's levels.
5. Then three oscillators and the octave buffer (board 6).

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

- **MM5, the whole voice:** the mixer, noise (board 3), the front panel's real summing (Fig 9-16 /
  9-17, replacing the CUTOFF and KEYBOARD CONTROL fixtures), the +-10 V regulators; the app's
  `minimoog` device with a partition measured for real time.
- **The uA726's heater loop** as a thermal node (B6's pattern), if the drift is wanted.
- **MM6, bending:** after the user has played it.

## Listening (the user)

- The voice with the keyboard circuit: glide (down slower than up), the +10 V trigger's effect on the
  contours, the click at the default contours.
