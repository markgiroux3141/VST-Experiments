# AM10 step 1: the floor's gate

2026-11-13, `scripts/floor_gate.py` -> `summary.json`. Every number here is an estimate from
provisional constants (floor stiffness, the share of the beater's force that reaches the floor,
mounts, the mics' front-to-back paths); the moving masses come from the fitted components.

## What was compared

The kick (`kick_22`, struck at 4 m/s: peak beater force 51 N, 108.6 dB SPL peak at a mic 1.5 m
away) shakes the floor; a stand 1.5 m away carries that to the mic body. The diaphragm feels the
body's acceleration `a` as a pressure difference `sigma a` (sigma = the moving mass per area).
That is compared, per third octave, with what the kick's *sound* drives the same diaphragm with.

Two corrections to the doc's step 1 (both stated in the script):
- **A gradient mic's acoustic drive is the front-to-back difference** `p k d_eff` (with the near
  field's boost), not `p`. At 50 Hz that is ~30 dB below `p` for a 3 cm path, while the inertial
  force meets the diaphragm in full. The doc's "pressure" comparison under-states the vibration
  path by that much for every mic here (all are cardioid or figure-8). `summary.json` keeps both
  (`pressure_reference_max_db`).
- **Mounts:** the U47 and the 44-BX on shock mounts (second order, 8-10 Hz, zeta 0.2: -27 dB at
  50 Hz); the dynamics on rigid clips.

## Result (vibration re acoustic drive, dB; the gate is -40 dB)

| Floor, share of beater force | SM57 | D112 | RE20 | U47 (K47) | 44-BX |
|---|---|---|---|---|---|
| 22 mm boards, no joists, 1.0 | 50 Hz -21, 62 Hz -19, 20 Hz +12 | -19 / -17 / +15 | -27 / -24 / +7 | -69 / -69 / -22 | -79 / -79 / -34 |
| same, 0.1 | -41 / -39 / -8 | -39 / -37 / -5 | -47 / -44 / -13 | -89 | -99 |
| 150 mm concrete, 1.0 | -61 / -59 / -28 | -59 / -57 / -26 | -67 / -65 / -33 | -110 | -119 |

(Columns: the 50 Hz band / the 62 Hz band / the 20 Hz band.)

## Verdict

- **Condensers and ribbons on shock mounts: closed** (55 dB or more under the acoustic drive in
  every band from 31 Hz up, on any floor).
- **Concrete: closed** for every mic in the music's bands.
- **Moving-coil mics on a rigid stand on a wooden floor: the gate passes.** Within 20 dB of the
  kick's own drive at 50-60 Hz if most of the beater's force reaches the boards, ~40 dB with a
  tenth of it; above the acoustic drive at 20-25 Hz, where the kick radiates little and a stand
  shakes freely (a subsonic thump that a preamp's or the tape's low end would mostly take out).

So the package is **not closed**: step 2 (a floor plate, a stand, the mic's front pressure plus
`sigma a`) is worth building for dynamic mics on wooden floors, a late-50s / 60s small-studio
situation (an SM57 / RE20 on a tom or a guitar cab near the kick). The share of the force that
reaches the floor and the floor's real stiffness (joists) decide the level; both are provisional
and move the answer by 20 dB. Not built tonight; the user's call.
