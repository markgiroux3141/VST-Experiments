# Strike and release variation on the Rhodes (future work)

Written 2026-11-04 after RH3, from the user's first playing: "if I play a bunch of notes in
succession, I hear almost the identical key attack and liftoff, which makes it sound a bit
artificial". Nothing here is built; the user parked it ("let's discuss first", then "write
this into a future work doc for now"). It sits beside RHODES_PLAN.md's RH5 (the production
tier) and RH6 (the condition dials), and some of it is theirs.

## Why the model repeats itself

- **The attack.** A key at rest struck at the same MIDI velocity is the same computation
  every time, bit for bit. A strike differs only through its velocity and the tine's state:
  a re-strike of a tine still moving (under the felt that is the first ~0.15 s) lands on
  different motion.
- **The release.** The damper is an instant switch from the free system to the damped one
  (`harp.rs`, `Voice::switch`; `harp.py`'s `Voice.damper`), with a fixed decay (T60 0.15 s,
  provisional). Only the phase at which the key comes up differs.

## Where a real Rhodes varies

In the order we expect them to be heard:

1. **The damper felt landing.** As the key rises the felt approaches and lands on a moving
   tine: where the tine is in its swing, how fast the key comes up and the felt's wear set a
   small thunk or buzz and an uneven cut-off. Model: the felt as a soft lossy contact at the
   damper's point, solved inside the step like the hammer's (`key.contact`'s structure), its
   approach speed from the key's release (MIDI release velocity, which `midi::Keys` ignores
   today; whether the user's keyboard sends it is to be checked), instead of the switch.
   Cheap live: it costs only during a release. Reference first in Python, then the port, as
   RH1-RH3.
2. **Tines never at rest.** Every tone generator hangs on one rail: a ringing note keeps its
   neighbours moving slightly, even under their dampers, so a strike always starts from a
   slightly different state. RH5's sympathetic coupling (the rail as a modal medium); a live
   approximation would couple each voice weakly to a shared rail motion.
3. **The second polarization.** The tine also swings sideways; a hammer a fraction of a
   millimetre off centre excites that plane differently each strike, and the two planes'
   slight detuning beats. Model: the beam FE in both planes (each key's modes about doubled),
   a seeded strike offset per strike (`default_rng([seed, key, strike])`, the reproducibility
   rule), its spread a provisional, bounded value. RH5 lists the second polarization.
4. **The hand.** Real playing varies speed continuously; MIDI's 127 steps are fine enough
   (~0.24 dB per step on the 30 dB law), so this is the keyboard's velocity curve, not the
   model. A velocity range or curve on the Play view (as the synth's) is a convenience.
5. **Per instrument, not per strike:** voicing, tip wear and spring position differing key to
   key (RH6's seeded tolerance draws). It makes a run of different notes less uniform, not a
   repeated note.
6. **Action noise** (key bottoming, the hammer's return) is mostly acoustic and barely reaches
   the pickups: a room or a microphone's (MIC_ROOM_PLAN.md), not the harp's.

## Proposed order (a recommendation, the user decides)

1. The felt as a contact (1), timeboxed, heard against the switch.
2. Then judge by ear whether the attack still sounds mechanical before (2) or (3), which are
   RH5's and the larger jobs.

## Related, from the same session

The harp's absolute level is low (a C4 at velocity 64 gives ~0.6 mV at the jack; a Stage is
said to put out about what a guitar pickup does, no measured figure found). The user's rule:
raise the level only where it doesn't change the sound. Done: the live full scale is the 5E3's
largest swing (20 V, RHODES_PLAN.md's RH3 status). The pickup's level itself stays RH5's 3D
solve's to set.
