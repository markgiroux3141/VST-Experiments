# What to listen to (the rooms, 2026-11-05)

Built overnight: docs/ROOM_LOOP_PLAN.md R7-R11 and directional sources ("Status
(2026-11-05)" there). Each folder below has a README with the details; every comparison is
loudness-matched (or, where the level *is* the point, shares one gain, said in its README).
Headphones or good monitors; the low-end differences need a full-range system.

**1. The wave solver (R10): the bass of a real room.** `wave_demo/`
- `small_geometric/room_pair.wav` against `small_wave/room_pair.wav`: kick, bass and piano in a
  small 4.2 x 3.4 m room. The geometric model gives the room's average low end; the wave solver
  the modes this room has at these mic positions: some bass notes bloom, others thin out.
- The same in the 7 x 5.5 m live room: `shoebox_geometric/` against `shoebox_wave/` (subtler:
  more modes, closer together).

**2. Your R6 demo again, with the wave solver.** `demo_wave/` beside `demo/`
- Each room's `room_pair.wav` and `mix.wav` against the same file in `demo/`: the vocal, guitar
  and piano you heard before, now with each room's modes below 500 Hz. Most audible on the
  piano's left hand and in the smaller rooms (`treated_studio`, `shoebox`).

**3. A material per wall (R7).** `wave_demo/`
- `shoebox_wave/room_pair.wav` against `shoebox_dead_front/room_pair.wav`: drapes on the wall
  behind the players, plaster behind the mics. The mids and highs drier, the bass longer (the
  plaster reflects what the furnished wall absorbed).

- `small_wave/room_pair.wav` against `small_trapped/room_pair.wav`: the small room treated with
  absorbers computed from their construction (100 mm of wool spaced off the side walls, a
  plywood bass trap): tighter and drier, every band decaying faster.

**4. Gobos and edge diffraction (R11).** `gobo_demo/`
- `open/guitar_spot__vocal.wav` against `gobo/guitar_spot__vocal.wav`: the vocal's bleed into
  the guitar's omni, without and with a gobo between the players (live room: a few dB, the
  room's reverb comes round it).
- `treated_open/guitar_spot__vocal.wav` against `treated_gobo/guitar_spot__vocal.wav`: the same
  in the treated room: ~6-7 dB less bleed above 500 Hz (less at 1 kHz), the bass bending round.

**5. Sources that face somewhere.** `source_demo/`
- `toward/room_pair.wav`, `away/room_pair.wav`, `omni/room_pair.wav`: an electric guitar through
  a 1x12 combo heard by the room pair: facing the mics (bright, direct), facing the wall
  (darker, more room, the cabinet's back), and as the omni every source used to be.

Not audible by design: R9 (the GPU) changes the speed, not the sound (the demo renders the
same within 0.03 dB), and R8 is numbers (`separation/polyroom/compare.json`).

How long things take now (the RTX 3080): a room's geometric part ~3 s per source with four
mics (was ~25-30 s: rays and image spectra on the GPU, the diffuse tail's synthesis
restructured); the wave solver below 500 Hz ~6.5 s per source in a 123 m^3 room (~2.5 min in the
990 m^3 hall, whose 2 s tail runs ~50,000 steps on ~25 million cells); the mic chains' prints are the floor (the U47 -> V76 ~5.5x slower than real
time).

The demos above were rendered before one late fix to the diffuse tail (one white noise per
plane wave shared by the bands: independent noises per band dipped the tail by up to 3 dB
between band centres); every variant of a demo was rendered the same way, so the comparisons
hold.
