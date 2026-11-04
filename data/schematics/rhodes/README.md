# Rhodes Mark I sources

docs/RHODES_PLAN.md's RH1, collected 2026-11-04. `config/rhodes/mk1.yaml` cites these.

## The service manual

"Rhodes Piano Service Manual", CBS Musical Instruments, 1979 (P/N 34.0119.000), the latest
design (from 1975) and the early designs (chapters 7-10).
web: https://www.fenderrhodes.com/org/manual/ (HTML per chapter), the OCR'd whole as
https://fenderrhodes.com/org/manual2.pdf (downloaded 2026-11-04, not committed).

- **Ch.1, the tone source:** a tuning fork of unequal legs, "alike only in pitch": the
  tine (struck) and the tone bar; the tine's coil spring is a counterweight for fine tuning.
- **Ch.4, dimensional standards:** key dip 3/8 in; escapement graded from 1/4-3/8 in
  (extreme bass bar) to 1/32-3/32 in (extreme treble); hammer tips graded in hardness and
  height (tips 1-30: durometer 30, 1/4 in; 31-40: 50, 5/16 in; 41-50: 70, 3/8 in; 51-64: 90,
  7/16 in; 65-88: wrapped, extra hard, 7/16 in); tone bar height 3/16-1/2 in (factory 3/8
  in); damper clearance 3/8-1/2 in; striking line ~2-1/4 in (extreme bass) to ~1/8 in
  (extreme treble), hammer tip's leading edge to the tone generator's; pickup gap 1/16-1/8
  in (0.020 in acceptable in the middle and upper range after March 1972); voicing: the
  tine's tip slightly above the pickup's dead centre.
- **Ch.5, tuning:** A4 = 440, equal tempered at the factory; the spring moved outwards
  lowers the pitch, as much as 1-1/2 semitones either way.
- **Ch.6, Figure 6-2:** the tine cutting chart (`data/datasheets/rhodes_tine_lengths.csv`,
  provenance beside it). The 73-key piano's tone bars are numbered 1-73 (E1 = 1), the 88's
  1-88 (A0 = 1); the 88's seven lowest were once all "0".
- **Ch.10, "Signal Strength":** the 73 pickups' original series / parallel arrangement
  (Fig. 10-3), then "basic voltage output was quadrupled" by the arrangement of Fig. 10-4
  (pickups 1-4 in parallel, then groups of three in parallel, the groups in series; read off
  the figure, https://fenderrhodes.com/org/manual/fig10-4.gif), "the output impedance then
  becomes approximately 2500 ohms".
- **Ch.7:** the original tine was piano wire 0.075 in across; later tapered at the root to
  spread the hammer's shock; the 1979 tone bar is a "twisted steel bar" (patent 3,644,656).

## Measurements

- **G. Shear, The Electromagnetically Sustained Rhodes Piano, MS thesis, UC Santa Barbara,
  2011.** web: https://www.mat.ucsb.edu/Masters/GregShearMasters2011_12_5.pdf (not
  committed). On a 1974 Mark I, 88 keys: tines 18-157 mm, 1.5 mm across but for a widened
  root (p.4); Q of the fundamental per note (Table 2.1 p.5: Eb2 949, Eb3 731, Eb4 1520, Eb5
  2175, Eb6 1761; Table 5.1 p.28: B3 1101, C4 1238, Db4 1040, D4 1156); the inharmonic
  overtones short-lived, then nearly simple harmonic motion (p.5-6, Fig. 2.2); voicing: as
  the tine's rest approaches the pickup's axis the fundamental and odd partials fall and the
  second dominates (p.8, Figs. 2.4-2.5, at 196 Hz); pickups in parallel groups of three,
  the groups in series (p.9); the lowest seven tines of the 88 have no tone bars (p.32).
- **M. Muenster and F. Pfeifle, Non-linear behaviour in sound production of the Rhodes
  piano, ISMA 2014, Le Mans.** web: http://www.conforg.fr/isma2014/cdrom/data/articles/000062.pdf
  (not committed). A Mark I: the hammer's contact 6.42 ms on average (3.1.1); after a
  10-14 ms transient the tine moves sinusoidally; the tone bar's own resonance (impulse
  hammer) well below the note, the bar driven at the tine's frequency in or out of phase
  (Table 1, nine bars); the pickup's core a round ferrite magnet, wedge-shaped at the tine.
- **F. Pfeifle, Real-time physical model of a Wurlitzer and Rhodes electric piano, DAFx-17.**
  web: https://www.dafx17.eca.ed.ac.uk/papers/DAFx17_paper_79.pdf (not committed). The
  tine as a cantilever with the spring as a mass, two polarisations (vertical larger), a
  Hunt-Crossley hammer, the pickup's field over the pole tip; no dimensions.
- **Pickup resistance:** web: https://www.fenderrhodes.com/service/pickups.html (170-190
  ohm by vintage).

## The Stage's controls

- Stock pots: VOLUME 10K audio taper, BASS (or "tone") 50K reverse audio taper.
  web: https://retrolinear.com/stage-piano-controls.html
- The 1973-on circuit: .047 uF in series from the harp to the volume's top, the 50K reverse
  pot across it (a shelving bass cut), "50KΩ bass boost pot, .047μF capacitor, and 10KΩ
  volume pot" as on Fender's printed schematic (quoted by a poster); before it (from ~1970)
  a 10K / 10K / 1 uF treble cut. web: https://ep-forum.com/smf/index.php?topic=9793.0

## Not found (provisional in mk1.yaml)

Tone bar dimensions; the tine root's taper; spring masses; hammer mass; the pickup's
magnet, coil turns and inductance; grommet stiffness and loss. Patents 2,972,922 and
3,644,656 may dimension some of them (not read yet).
