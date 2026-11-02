#import "../style.typ": *

#part[A Tape Machine from the Particles Up][
  The Ampex 351, a tube recorder from the 1950s, with Scotch 111 tape. Its saturation,
  hiss and flutter come from simulated magnetic particles, heads and a transport.
]

= How Tape Records

#sketch[
  *The reader leaves knowing:* the record head, the gap and its field; why tape needs AC
  bias (and that nobody fully explained it until Preisach); remanence; playback by
  reciprocity and the 6 dB per octave rise; equalization (NAB); what "saturation" means on
  tape (soft third harmonic, HF self-erasure).

  - Why the 351: tubes, warm and slappy, the electronics family of the 350 that made Sun's
    slapback.
  - Why Scotch 111: the tape of its era, and 3M's Sound Talk bulletins measured it from the
    particles up.
]

#todo-figure([Record head, tape and repro head in cross-section, with the gap field drawn.], from: "new diagram")

#incode("docs/TAPE_PLAN.md", "data/schematics/ampex_351/README.md", "data/datasheets/tape/README.md")

= Particles

#sketch[
  *The reader leaves knowing:* the Preisach picture (a coating as an ensemble of tiny
  switches, each with its own switching and interaction field); why it fits tape better
  than Jiles-Atherton (no ratcheting, and it is literally what a coating is); how bias
  works in that picture.

  - The trick that makes it affordable: the model is rate independent, so a cell's state
    depends only on the extrema of its field: two values per bias cycle, and a closed-form
    remanence once the head has passed.
  - Fitting to Sound Talk No. 20's remanence curve; orientation (vector Preisach).
]

#report-figure("/reports/devices/scotch111_fit.png", [Scotch 111's particle ensemble fitted to 3M's remanence curve.])

#deeper("the Preisach model")[
  $M = integral.double_(alpha >= beta) mu(alpha, beta) gamma_(alpha beta)[H] dif alpha dif beta$:
  each hysteron $gamma_(alpha beta)$ switches up at $alpha$ and down at $beta$.
]

= The Medium

#sketch[
  *The reader leaves knowing:* the tape as a 2D slab of cells moving past the heads; head
  fields from the head's geometry (Karlqvist with finite poles); playback by reciprocity;
  self-demagnetization.

  - What falls out instead of being programmed: the transfer curve and its soft
    saturation, the bias curve (sensitivity peaks then falls), gap loss, spacing and
    thickness loss, the head bump.
  - Checked against Sound Talk No. 21's bias curves (Ampex 300): matched to and past the
    peak; narrower in bias than the data (say so).
]

#todo-figure([Bias curves: model against Sound Talk No. 21 at 1 and 15 kHz.], from: "varimu/devices/tape.py (TM2's validation)")

= Grain and Motion

#sketch[
  *The reader leaves knowing:* where tape hiss comes from (a finite number of particles,
  packed unevenly) and where wow and flutter come from (capstan, idler, reels, motor
  hunting, scrape flutter); that the same speed wobble reaches both heads at different
  times.

  - Tape-only S/N 72.9 dB at 15 ips; the 351's 0.11% flutter reproduced.
]

#report-figure("/reports/tape/noise_fit.png", [The coating's grain fitted to Sound Talk No. 34's noise spectra.])
#report-figure("/reports/tape/flutter_15ips.png", [Flutter at 15 ips: a recorded tone played back.])

= The Ampex 351

#sketch[
  *The reader leaves knowing:* the whole machine as one circuit, and how it is aligned and
  printed.

  - The 1962 schematic: record 12AX7 and 6201s, repro 12AX7s, a 12AU7 push-pull, the 6X4
    supply.
  - The bias: the real oscillator, simulated at 3.84 MHz in a partition of its own (20 steps
    per sample) and meeting the rest at the input and the reservoirs. Show the bias
    coupling measurement that led to the choice.
  - Alignment run as the manual's procedure on the simulated machine: playback EQ from a
    virtual test tape, bias, record EQ, levels.
  - Prints: drums at 0, +6 and +12 dB of drive.
]

#report-figure("/reports/tape/bias_coupling.png", [The bias coupling measured at 3.84 MHz.])
#report-figure("/reports/tape/ampex_351_alignment.png", [The simulated 351 aligned by its own manual's procedure.])

#listen("drums through the 351")[The same drum loop at 0, +6 and +12 dB of drive, loudness matched, next to the dry recording.]
