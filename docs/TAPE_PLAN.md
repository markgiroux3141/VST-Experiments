# Tape: the Ampex 351 and its tape, from the particles up

Started 2026-10-31, ahead of the queue (the user's call). FUTURE_DIRECTIONS.md §5 sketched
it; this plan replaces that sketch. Milestones TM1-TM7, each finished only when its "done
when" is met and covered by tests, like the other plans.

## What the user asked for (2026-10-31)

- Tape saturation done the project's way: the dirt and warmth fall out of simulated
  physics. Nothing is a curve or a filter chosen to sound like tape.
- I pick what to emulate. It must have tubes and sound "warm and slappy".
- Real time if possible, but quality comes first: rendering is fine at the start.
- It may end up on the whole mix bus, so a render step (a print, SESSION_FX_PLAN.md) is
  acceptable at first.

## The choice: an Ampex 351 with Scotch 111

- **Machine: the Ampex 351** (catalog 30960 electronics), with tube record and repro
  amplifiers and a tube bias oscillator. It is the 350's electronics family, and a
  350 at Sun Records made the slapback echo: the repro head fed back to the record
  input. Sources are in `data/schematics/ampex_351/README.md`:
  - the 1962 manual has a legible schematic (p95), parts lists (pp88-93), specs (p10),
    EQ (pp13-14) and the alignment procedure (pp79-85);
  - the 1959 manual has three schematic revisions;
  - tubes: record 12AX7 x2 and a 6201 driver (constant-current head drive); repro
    12AX7 x2 and a 12AU7 push-pull output; bias / erase 12AU7 push-pull, about 100 kc;
    6X4 rectifier;
  - spec: +-2 dB 30 Hz-15 kHz at 15 ips; S/N 60 dB full track; wow and flutter
    0.11% rms at 15 ips.
- **Tape: Scotch 111**, the tape of its era (gamma-Fe2O3, 270 Oe, 900 G, 12.7 um coating,
  per Eilers' table). 3M's Sound Talk bulletins measure it from the particles up (files and
  extracted numbers: `data/datasheets/tape/README.md`):
  - B-H loops (No. 22) and remanence against peak field (No. 20): the Preisach
    distribution measured directly;
  - bias curves at 1 and 15 kHz measured on an Ampex 300 at 15 ips with a stated
    record gap and bias frequency (No. 21);
  - permissible record level against frequency (No. 14), coating thickness against
    response (No. 31), noise spectra (No. 34), print-through (Nos. 10 and 38).
  Era tape saturates sooner than modern stock: warmer at the same level.
- **Second formulation, later: a 456-class tape** (EMTEC SM911's complete IEC curve set
  with its head gaps stated: sensitivity, MOL and SOL against bias at three speeds; the
  ATR Master's overbias-against-gap table). It checks that the physics carries over with
  only the tape's parameters changed. It also gives the hotter, cleaner stock a mix bus
  may want.

## The model

The physics chain: record amplifier -> record head (a gapped core, the transformer
model) -> head field plus AC bias -> a moving slab of magnetic particles -> remanent
magnetization -> repro head flux by reciprocity -> EMF -> repro amplifier. The
transport moves the tape at v(t) between the heads.

1. **Particles: a continuous Preisach ensemble** (`varimu/devices/preisach.py`, TM1).
   - Hysterons with a lognormal switching-field distribution f(Hc) and a Gaussian
     interaction field g(Hi).
   - Not Jiles-Atherton: the coating is literally an ensemble of single-domain
     particles, the classical explanation of AC bias is Preisach's, and JA ratchets on
     minor loops (TUBE_SYNTH_PLAN.md S1). Under bias every particle runs hundreds of
     minor loops per audio cycle.
   - The model is rate independent: a cell's state depends only on the extrema of its
     field. So the bias costs two field values per carrier cycle, exactly.
   - A cell's whole field history is known once the record head has passed it (about
     0.5 ms, against ~130 ms to the repro head). Its remanence is then computed in
     closed form: suffix extrema and lookups in smooth cumulative tables of the
     continuous density.
   - A discrete hysteron grid would turn the anhysteretic curve, which is the
     recording's transfer curve, into a staircase of ~5% of Ms per step at 128 points.
     The continuous tables don't. The discrete grid stays as the tests' exact oracle.
2. **The medium** (`varimu/devices/tape.py`, TM2).
   - A 2D slab of cells: along the tape (~0.5 um) by layers in depth through the
     coating.
   - Each cell sees the record head's field at its own position at the bias's peaks.
   - Head fields come from the head surface's magnetic potential, with a gap and finite
     pole faces (Karlqvist with finite poles). Its spectrum is
     g e^{-ky}[sinc(kg/2) - cos(k e) R(k)]: the gap loss, the spacing and thickness
     losses and the head bump are in the geometry, not added.
   - Playback is reciprocity (flux = mu0 W integral of M times the repro head's field
     per ampere), and the EMF is -v d lambda / ds.
   - These follow from the model and are not programmed in: the anhysteretic transfer
     curve and its soft 3rd-harmonic saturation; the bias curve (sensitivity peaks,
     then falls, falling faster at short wavelengths); HF self-erasure and HF
     saturation (with the record pre-emphasis); the head bump; the 6 dB/oct repro rise.
3. **Noise and transport** (TM3).
   - Particle noise: a cell holds a finite number of particles (particle volume and
     packing, bounded genome parameters). Their binomial state and Poisson count give
     hiss, plus modulation noise that grows with the recorded level.
   - v(t) comes from the capstan (a hysteresis synchronous motor's shaft), roller
     eccentricity, reel tension along the reel, and scrape flutter (the tape span
     between guides as a string under stick-slip friction).
   - The same v(t) drives both heads at different times, so the flutter heard is
     v(t) against v(t - delay).
4. **Coupling into the netlist** (TM4).
   - A `Tape` IR element like the plate's `Plate`. It senses the record head's core
     (its B node gives the gap field), keeps the recorded tape, and drives the repro
     head's EMF.
   - The record-to-repro delay (~2 in of tape: about 133 ms at 15 ips; secondary
     sources, the manual doesn't print it) is far longer than a sample, so record and
     repro electronics, the bias oscillator and the power supply stay one coupled
     simulation.
   - SPICE sees the repro EMF held at 0 V, as with the plate (the medium cut out at its
     ports). The medium has its Python reference and circuitsim's port, tested to agree.
5. **The bias in the circuit** (TM5, a measured decision). The 351's 12AU7 oscillator
   runs at ~100 kHz, above the netlist's Nyquist frequency at 2x of 96 kHz. Options:
   - the literal oscillator with the head section at ~1.5 MHz (a multi-rate partition;
     the reference);
   - the oscillator's amplitude carried at audio rate and the carrier regenerated inside
     the medium.
   Measure one against the other before choosing.

## Validation anchors

- **Theory:** gap loss sinc(pi g / lambda), Wallace's 54.6 d / lambda dB, thickness loss
  (1 - e^{-k delta}) / (k delta), the 6 dB/oct repro rise (Bertram 1994).
- **Scotch 111:**
  - loops and remanence curve (Nos. 20 and 22, +-10% sample tolerance);
  - bias curves at 1 and 15 kHz on an Ampex 300 at 15 ips (No. 21: 70 kHz bias,
    0.002" record gap);
  - +4 dB permissible level at 7 kHz at 7.5 ips (No. 14);
  - the coating-thickness curves (No. 31);
  - noise spectra (No. 34).
- **SM911 (TM2's second part):** S1 / S10 / S16, MOL and SOL against bias at 7.5 / 15 /
  30 ips, with a 7 um record gap and a 3 um repro gap; the recommended overbias (3 dB at
  15 ips) should come out of the model; THD against level.
- **The 351:** its specs (above) and its alignment procedure run as a procedure.

## Milestones

**TM1: the particles.**
- The continuous Preisach model and its tests: the discrete corner formula equals
  every hysteron stepped; extrema-only equals dense histories; the continuous tables
  converge.
- Scotch 111's loops and remanence curve digitized (CSVs with provenance), the fit
  (`varimu fit-devices --only SCOTCH111`), the component `SCOTCH111@1` (kind `tape`).
- Done when the fit reproduces Hc, Br and squareness within the bulletins' +-10%,
  and the remanence curve's rise within it, with plots in `reports/tape/`.

**TM2: the medium (Python reference).**
- Recording with bias, playback by reciprocity, the heads' geometry, a reference
  fluxivity readout.
- Done when:
  - the theory losses hold within 0.1 dB;
  - convergence in cell length, layers and bias samples is measured;
  - Scotch 111 on the Ampex 300's geometry gives No. 21's bias curves within +-2 dB,
    peak positions within +-1.5 dB of bias, the 15 kHz peak below the 1 kHz peak;
  - No. 14's level against frequency within +-1.5 dB;
  - then SM911 with the IEC heads: its curves against bias within +-2 dB.
- Demagnetization inside the recording zone goes in only if these don't hold without
  it (measured).

**TM3: noise and transport.**
- Particle noise against No. 34 and the 351's 60 dB S/N.
- v(t) against the 351's 0.11% rms; the wow and flutter spectrum plotted.

**TM4: circuitsim.**
- `tape.rs`, the IR element `Tape`, the `tape` part in both builders, Python against
  Rust within rounding, the speed measured.

**TM5: the Ampex 351.**
- `config/circuits/ampex_351.yaml` from the 1962 schematic; heads as windings on
  gapped cores; the bias coupling decided by measurement.
- The alignment as a procedure (`setup`): bias at 500 Hz, 7.5 ips, the median of
  1/2 dB either side of the peak; operating level at 1% THD, 400 Hz; repro EQ to a
  virtual test tape (700 Hz at 0 VU = +8 dBm).
- A `tape_suite` profile.
- Done when the specs hold: +-2 dB 30 Hz-15 kHz at 15 ips, S/N, idle voltages within
  +-20% of the printed ones.

**TM6: in the app.**
- The device in varimu-app, printed as an insert (a production render).
- Slapback (repro to record, the Sun wiring).
- A mix bus: stereo as a two-track on one transport, both channels sharing v(t) (the
  351-2 / 354 family).

**TM7 (optional): real time.**
- A reduced tier measured against production, if it can be made close enough.

**Later:** print-through (Nos. 10 and 38: thermal activation of the neighbouring layer's
particles), the erase head's real field (incomplete erasure), magnetized heads (the head
cores' JA remanence: noise and even harmonics, degaussing as maintenance), azimuth,
sticky shed, the 456-class stock as a second component.

## Status

*2026-10-31:* sources archived (`data/schematics/ampex_351/`, `data/datasheets/tape/`; the
manual scans and the AES table are git-ignored, their READMEs keep URLs and hashes).

**TM1 done.** `varimu/devices/preisach.py` (continuous Preisach, its corner formula, the
discrete oracle), `varimu/devices/tape_fit.py`, the component `SCOTCH111@1`
(`varimu fit-devices --only SCOTCH111`, `reports/devices/scotch111_fit.png`),
`tests/test_preisach.py`.
- The corner formula on the discrete grid equals every hysteron stepped (4e-16).
- Extrema-only histories equal dense ones exactly.
- 1024- against 2048-point tables differ by 1.3e-5 of Ms.
- The model is odd to ~1e-7 of Ms (-140 dB): a mirrored history reads other table points.
- 20,000 cells with 300 field samples each take 0.24 s in numpy.
- The fit: Sound Talk No. 20's Type B curve digitized (`scotch_111_remanence.csv`, by eye
  from an 800 dpi render, +-0.01 lines) plus Eilers' Hc. Bulletin 20 alone fits any
  sigma_Hi from 20 to 150 Oe (it trades off against the median switching field); Hc
  breaks the tie.
- Result: Hc median 293 Oe, sigma_ln 0.33, sigma_Hi 46 Oe, Ms 62.8 kA/m (the
  irreversible part: about half of bulk gamma-Fe2O3 at typical packing, as an
  unoriented ensemble gives). Remanence rms 0.66 reading errors; loop Hc 296 Oe against
  270 (+9.6%, inside the +-10%).
- The plan's squareness check is dropped: no source gives #111's squareness.

**TM2 in progress.** `varimu/devices/tape.py`:
- head fields: Hx, Hy, closed-form spectra, finite poles;
- recording at the bias peaks, with the oscillator's phase free;
- reciprocity playback of Mx and My;
- slab demagnetization and its self-consistent recording;
- the vector Preisach orientations;
- tests in `tests/test_tape.py`: spectra, gap and Wallace losses, reciprocity and the
  6 dB/oct rise, the demag kernel against the slab factor, oddness over bias phase,
  peaks against dense bias sampling.

What the bias curves taught (Sound Talk No. 21, Type B on an Ampex 300: 15 ips, 70 kHz,
0.002" record gap). The one free parameter is the head's field per mA (unprinted).
1. **Scalar Hx-only, no demag:** the 1 kHz shape is roughly right, but 15 kHz has the
   same shape as 1 kHz. Measured, 15 kHz falls 10.4 dB against 1 kHz from 2 to 8 mA;
   modelled, 0.6 dB. Larger head-to-tape spacing (3, 8 um) moves it the wrong way.
2. **The full pattern's demag:** the fixed point doesn't converge. The recorded bias
   pattern (lambda_b 5.4 um, N ~ 0.97) feeds back hysteretically.
3. **Demag of the audio band only** (wavelengths > 15 um, converges): the differential
   becomes 0 / -4.0 / -5.7 / -6.4 / -6.8 / -7.1 / -7.3 dB against the measured 0 / -2.2 /
   -4.6 / -6.0 / -8.3 / -9.9 / -10.4. The 15 kHz curve's rms error drops from 3.7 to
   1.8 dB. About 3 dB of loss past the peak is still missing, and the 1 kHz rise below
   the peak is too steep (-5.6 against -11 dB at 3 mA).
4. **Next: the perpendicular field.** Past the gap, Hy falls as g / (pi x), Hx as
   g y / (pi x^2). Particles not aligned with the tape keep switching far downstream
   (x* ~ Hg g / (pi H_sw), ~25 um for a 51 um gap), with a spread comparable to 15 kHz's
   wavelength, and it grows with bias. That is the classical over-bias HF loss.
   - The model: Mayergoyz's vector Preisach (`Orientation`: an axial von Mises
     distribution of easy axes, each a scalar ensemble driven by the field along it).
   - For each orientation, bulletin 20 is refitted (it measures the x component).
   - Orientation then becomes a fitted parameter, constrained by No. 21. The validation
     anchors move to No. 14 (MOL against frequency), No. 31 (coating thickness) and
     SM911.
5. **Vector Preisach plus audio-band demag (Mx only)**, measured.
   - kappa = 0 (unoriented) fits bulletin 20 poorly (rms 2.6 reading errors: averaging
     over orientations smooths its steep rise).
   - kappa = 3 fits it as well as the scalar model (0.62): Hc median 277 Oe, sigma_ln
     0.32, sigma_Hi 48 Oe, Ms 66.3 kA/m.
   - Its bias curves (one scale, 68 Oe/mA):
     - 15k - 1k: 0 / -3.6 / -6.9 / -8.4 / -9.0 / -9.3 / -9.5 dB against 0 / -2.2 / -4.6 /
       -6.0 / -8.3 / -9.9 / -10.4. The treble loss with bias is now its measured size.
     - 1 kHz below the peak is right (-10.9 against -11.0 dB at 3 mA).
     - Past the peak both curves fall too little: 1 kHz -0.9 against -3.3 dB at 8 mA;
       15 kHz -1.5 against -7.1.
   - Reading My through Hy too (M . H) is worse, but My has no demagnetization yet. Its
     perpendicular factor (1 - e^{-k delta}) / (k delta) is ~0.9 at audio wavelengths.
     Next: the perpendicular demag, consistent with Mx's.
   - Cost: 34 min of numpy per orientation for 20 bias points. The Python reference is
     too slow for fitting kappa; the Rust port (TM4) may need to come before the fit.
6. **The consistent model** (vector Preisach, demag of both components:
   `demag_field_vector`, `record_demagnetized_vector`, read as M . H), kappa = 3.
   - Matches No. 21 up to and including the peak:
     - 15k - 1k: 0 / -2.2 / -4.7 / -5.8 / -6.3 / -6.4 / -6.3 dB against 0 / -2.2 / -4.6 /
       -6.0 / -8.3 / -9.9 / -10.4;
     - 1 kHz: -24.7 / -11.0 / -3.4 / -0.6 / 0 / -0.3 / -0.8 against -20.4 / -11.0 / -4.0 /
       -0.6 / 0 / -0.8 / -3.3.
   - Over-bias is the open part: past the peak both curves fall too little (8 mA: 1 kHz
     -0.8 against -3.3 dB, 15 kHz -0.8 against -7.1). That region matters: 3M's No. 4
     says professional machines ran at ~2x the bias for maximum 1 kHz output.
   - Candidates, not yet tried:
     - the record head's image (the soft head under the tape changes the in-zone demag);
     - kappa (3 against 8, and a 3D rather than an in-plane distribution);
     - a mean-field interaction (moving Preisach);
     - the provisional head geometry (pole lengths, spacing).
   - The demag iteration reached 3.5e-3 within 25 steps.
   - 29 min per kappa in numpy.
7. **The Rust kernel** (TM4's first part, below) made sweeps ~50x faster. With one scale
   fitted to both curves, at 8 mA (measured: 1 kHz -3.3, 15 kHz -7.1, 15k - 1k -10.4 dB):

   | variation | 1 kHz | 15 kHz | 15k - 1k | rms 1k / 15k | 1 kHz at 3 mA (-11.0) |
   |---|---|---|---|---|---|
   | base (kappa 3) | -2.1 | -2.3 | -6.0 | 2.42 / 2.68 | -5.6 |
   | kappa 1 / 8 / 20 | -1.9 / -2.3 / -2.2 | -3.6 / -2.5 / -2.5 | ~-5.8 | 1.30 / 2.20 (kappa 1) | -9.1 / -5.4 / -5.5 |
   | spacing 0.25 / 1.5 um | -1.2 / -2.3 | -1.6 / -2.4 | -6.1 | | |
   | demag cutoff 8 / 30 um | -2.2 / -2.8 | -2.1 / -3.2 | -5.3 / +1.6 | | |
   | no demag | -2.8 | -3.7 | -1.8 | | |
   | 16 layers / 0.25 um cells / 16 orientations | within 0.3 dB of base | | | | |
   | **head image**, kappa 1 | **-3.6** | **-7.2** | -6.8 | 2.67 / 2.38 | -5.2 |
   | head image, kappa 1.5 | -3.2 | -5.2 | -6.4 | 2.42 / 2.04 | -5.7 |
   | head image, kappa 2 | -2.8 | -4.4 | -6.7 | 2.19 / 2.08 | -6.3 |

   - Numerics have converged.
   - Demag of the audio band is the 15k / 1k mechanism.
   - The head's image (under the head the tape's charges are mirrored with opposite sign:
     `demag_field_vector(image_spacing_m)`; during the pass the imaged field, after it
     free tape's) gives the over-bias fall at both frequencies (kappa 1).
   - Left over: the model's curves are narrower in bias than the measured ones. They
     peak at lower bias, so the rise below the peak is too steep (3 mA, 1 kHz: -5 against
     -11 dB), and 15k - 1k reaches only -6.4 to -6.8 dB.
   - Against the done-when (kappa 1.5, image): 1 kHz peak 1.1 dB of bias from the data's
     (ok); 15 kHz peak 1.9 dB (over 1.5); the 15 kHz peak below the 1 kHz peak (ok); rms
     2.4 / 2.0 dB (at the +-2 dB edge).
   - Untested candidates: the Ampex 300 head's field against current (its efficiency at
     70 kHz isn't printed; a sublinear law would stretch the data's bias axis), and the
     particles' dynamic coercivity (switching under a 70 kHz bias is harder and broader
     than in bulletin 20's 60 Hz loops: thermal activation, Sharrock's law).
- Each cell is a point sample. Averaging cells over a particle's length was tested and
  changes nothing: the ± asymmetry seen at one bias phase is the locked phase, not
  aliasing.

**The first print (2026-10-31, the user's call: "move on to sound so I can hear it").**
`varimu/devices/tape_machine.py` and `scripts/tape_print.py` put audio through the
simulated tape with **idealized electronics**: NAB networks (3180 / 50 us) plus one HF
trim each in record and repro. TM5 replaces them with the 351's circuit.
- The alignment follows the 351 manual:
  - bias at the 500 Hz peak at 7.5 ips (the median of the -1/2 dB points);
  - repro trim from a test tape's definition (the real head's reading over an ideal
    reproducer's, flat at 10 kHz);
  - 0 VU = 1% THD at 400 Hz;
  - record trim for a flat low-level response at 10 kHz.
- Levels: -18 dBFS rms = 0 VU in and out; `--drive-db` is the record level.
- Provisional machine geometry (`TapeMachineSpec`): record gap 12.7 um (the ATR sheet's
  test gap; the 351's isn't printed), 3 mm poles, 0.5 um spacing. Printed: the repro gap,
  the full-track width, 100 kHz bias, NAB.
- Aligned on SCOTCH111@2 at 15 ips: bias 3.0 Hc, 0 VU at 0.65 Hc (peak deep-gap
  field), trims -0.7 dB (repro) and +1.8 dB (record) at 10 kHz; 117 s.
- Tones through the print:

  | | 0 VU (-18 dBFS) | +6 dB | +12 dB |
  |---|---|---|---|
  | 1 kHz out | -17.98 dBFS, THD 1.3% | -13.0 (1.0 dB compression), 6.2% | -10.3 (4.3 dB), 18% |
  | 10 kHz out | -18.11, 0.3% | -14.0, 1.4% | -13.1 (7 dB: treble saturates first), 4.3% |
  | 100 Hz out | -18.96, 1.7% | -14.3, 9.7% | -11.9, 26% |

- Bugs found on the way:
  1. A test tape magnetized uniformly through the coating exaggerates thickness loss
     (repro trim +8 dB). A test tape's level is the surface short-circuit flux, so the
     trim compares the real head with an ideal one on the same recorded pattern.
  2. THD normalized by the low-level recording's own harmonics.
  3. A 3-wavelength test pattern next to erased tape: edge demagnetization gave a
     level-independent 0.7% THD floor; recording 2 more wavelengths either side and
     reading the middle brings it to 0.05%.
- Speed: demag kernels are cached (they don't depend on M).
  - 12 demag iterations: 185x real time (converged).
  - 4 iterations: 65x real time, within -41 dB of converged; the prints' default until
    "Speed" below (now 8).
  - 2 iterations: -25 dB.
- The clip's ends: the tape now runs (recording silence) before and after the clip.
  Stopping with cells inside the record zone left them as the bias's last peak left
  them: a spike of 0.12 on a silent impulse test, spread over ~0.1 s by the repro head's
  reach and the EQ's bass tail. Now 0.0002.
- No delay: a click comes back within 3 samples. Cross-correlating music with its print
  finds 7-26 ms instead (the NAB networks' bass group delay, ~80 samples at 30 Hz, or a
  beat period), so the dry A/B files aren't shifted.
- First prints (`reports/tape/audio/`, git-ignored):
  - the user's drums at 0 / +6 / +12 dB drive, the mix at +6, each with a
    loudness-matched dry file;
  - drums at 0 dB: peaks -2.3 to -6.7 dBFS (the kick's transients reach ~13 dB over 0 VU
    and bass saturates first), 60-200 Hz -3.5 dB, 16-20 kHz -3.2 dB;
  - render cost: 57-114x real time (hotter drive is slower: more records per cell).
- Not in the first print: wow and flutter, particle noise (TM3), the 351's electronics
  (TM5).

**TM4 done (2026-10-31):** circuitsim's `tape.rs`, the stream, the IR element and the part.
- `tape.rs`: the Preisach tables and corner formula, the vector head field, and the
  recording kernel (cells in parallel, orientations, a steady field during the pass and
  another after it). Bindings `circuitsim.tape_record`, `tape_state_after`;
  `varimu.devices.tape.record(..., engine="rust")`. A bias sweep at kappa 3 takes 37 s
  against 1751 s in numpy.
- **The stream** (`varimu.devices.tape_machine.TapeStream`, the reference; circuitsim's
  `tape_stream.rs`, the port; `circuitsim.tape_stream_run`): the record gap's signal
  field in per sample, the repro EMF of the next sample out. Tape is recorded in blocks
  of 16 mm (the print's algorithm: zones, the demag fixed point with the head's image)
  once the record head is 2 mm past a block's 0.5 mm margin, a block's flux slope at the
  repro head once its successor is recorded; the repro gap reads the head distance
  behind (50.8 mm, ~133 ms at 15 ips), so the medium never waits on the circuit. The
  heads must leave room: 2 blocks + margin + pad (checked). Block length moves a print by
  -63 dB against 0.5 s blocks.
- **The print is the stream**, fed offline with the delay taken out (`print_audio`,
  engine "circuitsim": all of it in Rust, 1.2x faster than the reference driving the
  Rust kernel; the recording kernel dominates).
- **Anderson's least squares** is modified Gram-Schmidt in column order in both languages
  (`lstsq_mgs`), so the fixed point agrees step for step.
- **One fix on the way:** the Python kernel padded each cell's history to the chunk's
  longest zone with the steady field, so whether a cell's history ended "imaged field,
  then free field" depended on its neighbours; Rust never had that step. Both now end
  every pass with the steady field alone, then the field the cell is left in (the
  physical history as the tape leaves the head; ~1e-6 of Ms). The kernels then agree to
  4e-13 with steady fields (was 1e-6).
- **Agreement** (`tests/test_tape_stream.py`, a small machine so the reference's own
  kernel runs): the Rust stream against the all-Python reference within 4e-13 at any
  iteration count, against the reference on the Rust kernel within 2e-15; any chunking
  gives identical output in both.
- **The IR element `Tape`** (Python `varimu.circuit.ir.Tape` with `TapeMedium`, Rust
  `ir::Tape` with `tape_stream::TapeParams`): senses the record coil's current across its
  resistance (`h_per_v`), drives `out` with the repro EMF one sample later, as the plate
  does (`media.rs`: plates and tapes as one kind of medium in MNA and the transient; a
  changed medium mid-run starts on erased tape). SPICE holds `out` at 0 V. In a circuit,
  the output equals the reference stream fed the sensed voltage, one sample later,
  within 1e-9.
- **The `tape` part** in both builders (`parts.tape`, varimu-circuit's `tape.rs`):
  `tape: [rec_plus, rec_minus, out]`, the tape component and the machine's 16 physical
  values (transport, bias, heads' geometry, each coil's L, R and field per ampere); the
  numerics are fixed (`parts.TAPE_*`: the print's, 8 demag iterations). The record coil,
  the tape, the repro coil to `out`. Its test circuit `config/circuits/tape_test.yaml`
  (provisional coils); the builders agree bit for bit (app fixtures), its symbol is in
  both symbol tables.
- **Speed:** `tape_test` on 2 s of the drums at about operating level, production
  settings (esdirk4 at 2x), runs at 16.5x real time with the 1 s settle counted (the
  recording kernel dominates, as in the print); the repro head gives 12 mV peak, 0.85 mV
  rms into its 1 MOhm load.

**Speed (2026-10-31, the user's call: speed before TM4's element).** Measured on 0.4 s of
the user's drums at +6 dB drive (the loudest material, one block), each setting against
the one it replaces, in dB of difference re the print's rms; times on a free desktop.
- **Where the time went:** every 1 um cell (381,000 per second of tape, times 6 layers) ran
  8 orientations over every bias peak in its zone, 100-280 peaks: the zone was sized by
  the clip's loudest peak and a floor of 31 Oe, and the demag iteration records 5 times.
- **The zone's floor was never what `floor_tol` said.** `switching_floor` reads the
  ensemble's 64-point grid, so it returned half a grid step (31 Oe) for any tolerance; the
  continuous density has no gap near zero field (weight ~ linear in it: 1e-3 below
  4.5 Oe), so a 1e-5 tolerance would need 0.05 Oe, a zone wider than the head. The floor is
  now a field (`record(floor_a_m=...)`, `TapeMachineSpec.zone_floor_oe`), set by measuring
  the print:

  | floor | vs 31 Oe | time (CPU shared) |
  |---|---|---|
  | 15 Oe | -85.7 dB | 99 s |
  | 31 Oe (was) | | 61 s |
  | 62 / 120 / 200 / 300 Oe | -82 / -76 / -71 / -66 dB | 42 / 31 / 28 / 25 s |

  31 Oe was converged; 120 Oe is the default (8 Oe can't be run: the pole edges reach
  9.6 Oe).
- **Per-cell zones** (`local_zones`): each cell's zone from the largest |field| over its own
  pass (rounded up on a grid of 8 steps per octave, cached per layer), not the clip's peak.
  The same bound, so the floor means the same; tested (`tests/test_tape.py`: no left-out
  sample reaches the floor; Rust and Python agree within 1e-9 with per-cell zones).
- **Orientations stay 8:** 16 is -61 dB from 8, 6 is -50 dB and only 1.2x faster, 4 is
  -39 dB.
- **Cheaper iterations don't pay:** recording the demag iteration with a 300 Oe floor or
  fewer orientations and the result once more in full is -37 dB from converged (the plain
  last step is worse than Anderson's extrapolation); not kept.
- **Exact:** the free and imaged demag fields share their transforms (scipy, threaded, a
  fast length); the kernel's two Q lookups per record share the beta weights.
- **Demag iterations:** the default print (4) is -42.3 dB from converged (12). With the new
  zones (0.4 s excerpt):

  | iterations | vs converged | time |
  |---|---|---|
  | 2 | -27.0 dB | 8.0 s |
  | 4 | -42.3 dB | 11.0 s |
  | 6 | -51.1 dB | 14.4 s |
  | 8 | -58.5 dB | 17.1 s |
  | 4, the old zones | -42.3 dB | 28.6 s |

  Prints now run 8 (`tape_print.py --demag-iterations`): 1.7x faster than before and 16 dB
  closer to converged.
- **The whole clip:** 10 s of the drums at +6 dB print in 240 s (24x real time; 78x
  before), -40.6 dB from the old print (that print's own distance from converged: 4
  iterations). On 2 s: the Rust kernel 60% of the time, the demag iteration's Python
  (Anderson's least squares and history, the transforms, kernel builds) most of the rest.
- **Next for speed:** the demag iteration in Rust. Not now: TM4's element needs a causal
  demag (a cell sees the tape recorded so far, not the whole clip's fixed point), which
  restructures the iteration.
- **Since TM4:** the iteration runs in Rust after all (the stream, `print_audio`'s engine
  "circuitsim"), with a demag that stays the print's: blocks recorded with the fixed point
  once the record head has passed them, read a head distance later (TM4 below).

**TM3 done (2026-10-31): the coating's grain and the transport.**
- **The model** (`TapeNoise` in a tape component's `noise` block; the stream's grain, both
  languages, `noise_seed` / the circuit's noise seed, Philox streams indexed by cell):
  - particles of one volume at a packing fraction, placed at random: a Poisson count per
    cell, each particle up or down, so the cell's variance is sum_j w_j cos^2 phi_j / N
    whatever the level (hiss);
  - the packing's own fluctuation along the tape, one field through the coating's depth,
    each cell's magnetization times 1 + it (modulation noise, growing with level).
  - Binomial states with a fixed count would make the noise fall with level, and a Poisson
    count alone keeps it constant: Bulletin 34's DC noise, ~15 dB over the erased noise,
    needs the packing field.
- **The data:** Sound Talk No. 34 (#111, 7.5 ips, NARTB playback), digitized by eye
  (`scotch_111_noise.csv`, `3m_sound_talk_34.provenance.yaml`): bulk-erased octave spectra
  (Fig. 3), DC at the 3% level in the head (Fig. 2), the machine's own noise (Fig. 3).
- **The fit** (`scripts/fit_tape_noise.py` -> `reports/tape/noise_fit.*`): the first print's
  machine at 7.5 ips (3% THD at 400 Hz at +4.2 dB over 0 VU), levels below that tone's
  output, the bulletin's machine noise added in power.
  - Erased: particle volume 1.66e-21 m^3 at packing 0.35 (provisional), rms 1.7 dB over
    300-2400 Hz: an acicular particle of ~0.4 x 0.07 um, plausible for the era. Above
    2.4 kHz the model, flat-aligned, sits 6-12 dB over the data: the bulletin's machine's
    HF response isn't printed (its noise there rose when plastic base improved head contact,
    p.3); those bands aren't fitted.
  - DC: a Gaussian-correlated field (agglomerates, 1 um-1 mm) can't fit: its spectrum is a
    hump, the data fall a steady ~3 dB per octave band from 20 Hz to 10 kHz (a k^-2
    spectrum through this chain). An exponentially correlated field (an AR(1) from cell to
    cell) longer than ~2 mm gives k^-2: mm-scale nonuniformity of the coating. Fitted:
    rms 1.5 dB over 20-2400 Hz (the bands above within 2.5 dB too); only
    packing_sigma^2 / packing_corr_m is measured (8.7e-3 per m), set as 0.0162 over 30 mm.
  - The component: `SCOTCH111@3` (the `noise` block; `library.SCOTCH111_NOISE`).
- **Against the 351** (`scripts/tape_snr.py`): tape recorded silent with bias, 15 ips, 3%
  THD at 400 Hz (+3.1 dB over 0 VU) to unweighted noise 50-15,000 Hz: **72.9 dB**. The
  351's 60 dB includes its bias, erase and amplifier noise; Bulletin 34 Fig. 4 has a
  normal machine's erase and bias ~10 dB over bulk-erased tape (60 Hz and bias recorded),
  and R-e/p 1974 gives #111 66 dB. That share comes with TM5's oscillator and amplifiers.
- `tape_print.py` prints with the grain (seed 1; `--no-noise`); the tape element has it
  when the circuit's noise is on (keyed by its name).
- **The transport** (`TapeMachineSpec.transport`; the stream's position integrated from
  v (1 + eps) sample by sample, cubic between samples, both languages; blocks recorded and
  read by position, so drift costs nothing; without flutter the arithmetic is unchanged):
  - periodic: the capstan's runout at v / (pi d), 30 Hz (the 351's capstan is its hysteresis
    synchronous motor's shaft, 4.04 mm for 15 ips at 1800 rpm: derived, the diameter isn't
    printed); the rubber idler at 3.8 Hz; the supply reel at 0.76 Hz (mid pack);
  - random resonances (Philox-driven, scipy's lfilter order in both languages): the motor's
    hunting (2.5 Hz, Q 3) and scrape flutter, the free span's first longitudinal mode c / 2L
    (~4.06 kHz, Q 10; Sound Talk No. 34's "FM noise");
  - their sizes provisional (nothing printed separates them), scaled so a 3150 Hz tone
    recorded and played back deviates 0.11% rms over 0.5-250 Hz, the 351's spec (a playback
    measurement, ASA Z57.1-1954; `scripts/tape_flutter.py` -> `reports/tape/flutter_15ips.*`):
    measured 0.110%, the speed itself 0.087%, scrape flutter 0.03% above the band. Playback reads v at record time against v 133 ms later, so
    independent wander adds up to sqrt 2, and the capstan's 30 Hz cancels (133 ms is four
    of its turns).
  - The `tape` part has no transport yet (the 351's comes with its circuit, TM5); in a
    circuit its random parts take the circuit's noise seed.
- **An artifact the fit found: the bias residue aliased.** Cells are point samples, and the
  bias leaves a residue at its wavelength and harmonics. At 1 um cells the harmonics folded
  into the audio band: DC recorded at the 3% level played back a 9.5 kHz line at -59 dB re
  the 3% tone at 7.5 ips (19 kHz, -75 dB at 15 ips; masked in the drums print). Not block
  seams (0.5 to 8 mm margins change nothing). Fixed by cells at 7.62 per bias wavelength
  (0.5 um at 15 ips, scaled with speed; both builders' part too): no line in band at 15 ips,
  19 kHz at -75 dB at 7.5 ips. A whole number of cells per bias wavelength would alias the
  residue to DC (the locked phase). The cost: twice the cells (prints ~2x slower).

**TM5 in progress (2026-11-01): the 351's circuit, and the bias coupling measured.**
- **The circuit** `config/circuits/ampex_351.yaml`, transcribed from the 1962 schematic
  (p95, read at 300 dpi; designators as printed). Record and play at once (relay 3K1
  energized), 15 ips (4S2 at HI), NAB, the UNBALANCED BRIDGE input (4R5 / 4R4 / 4R3, so
  6T1 and 1V1b are out of the path; 1V1b stays in for its DC load), the line out into
  600 ohm. The chain:
  - record: RECORD LEVEL 4R9, then 1V1a (12AX7); 1V2b (6201), whose pre-emphasis is 1C7
    across 1R17 plus 1R18 / 1C8 at its plate; 1V2a (6201), the head driver (unbypassed
    cathode, 22K plate load), through 1C10 into the record head, then 5R24 to ground;
  - repro: the head into 2R25; 2V3b with the NAB feedback from 2V3a's plate to 2V3b's
    cathode (2R31 to 2R29 || 2C15; 2R26 lifts the cathode); 2V3a, grid-leak biased;
    PLAYBACK LEVEL 4R36; 2V4a, then 2V4b as a self-balancing paraphase (2R40 the common
    plate resistor, 2C18 to 2V4b's grid); the 12AU7 push-pull 1V5 into 6T3, with a
    feedback winding through 2R49 to 2V4a's cathode;
  - supply: 6X4, then the RC chain 330 / 300 / 250 / 220 / 215 / 190 V and the record
    line (3R56, 3R57, 1R59) to 1C2c, which feeds the oscillator and the 6201.
  - Not modelled: the mic input, the meter and its switch, monitor and phones, the
    heaters, the CCIR network, the 7-1/2 ips trimmer.
- **New component `6201@1`** (the 6201 is RCA's premium 12AT7): Koren, all five parameters
  fitted to RCA's two class-A1 points and the cutoff (TENTATIVE DATA 1, 10-56; local copy
  `sources/rca_6201_1956.pdf`). It is within 1.4% of Ip, gm and rp at both points. Koren's
  tables have no 12AT7.
- **Calibrated, not printed:**
  - 6T4's HV per half, 262 V rms, for the drawing's 330 V at the 6X4 (provisional R and
    leakage);
  - 6T3's secondary, 0.315 per primary half, from the drawing's signal voltages (+18 dB on
    each plate, +8 dB out);
  - its feedback winding, 0.216 per half, for the drawing's 29 dB from 2V4a's grid to the
    line at 500 Hz (11.7 dB of feedback);
  - the oscillator's DC load while it runs (`oscillator` 1: 11.96 kOhm on 1C2c, measured
    literally below).
  - The heads stay provisional. The record head is now 5 mH: the ~300 turns its field per
    ampere implies, at A_L ~ 50 nH. 0.1 H was inconsistent with that, and with a bias
    feed through 15-130 pF.
- **Idle against the drawing** (`oscillator` 0, as it was measured; `tests/test_ampex_351.py`):
  - the supply from the 6X4 to the output stage is within 2.6% (330 / 300 / 275 / 250 V,
    the output plates, k5);
  - the rest is within 10%, except 4 nodes.
  - 1V2a's cathode: 12.6 V against the printed 6 V. The drawing contradicts itself: its
    150 V plate on 22K from 275 V is 5.7 mA, and 5.7 mA through 2420 ohm is 13.8 V.
  - p3b, p4b and p3a are +22%, +25% and +36%: 12AX7 plates on 220-330K loads. There a
    7% current error and the supply's +8% add up. 2V3a, grid-leak biased on 10 MOhm,
    also depends on the provisional grid current's contact potential. The printed 90 V
    needs its grid near -0.5 V.
  - The done-when's +-20% isn't met for these three: tested at +-40% for now.
- **Signal levels at 500 Hz:**
  - record gains match the drawing: 1V1a to 1V2b +23.1 dB (drawing +23), 1V2b to 1V2a
    +5.7 (+3.5); the record head at about the drawing's level, scaled to our input;
  - the repro head gives ~20 dB more than the drawing's -68 dB. Its sensitivity
    (rep_h_per_a) is provisional, and PLAYBACK LEVEL takes it up in the alignment (not
    built yet).
- **Speed:** 2 s of the drums at production (JA cores, the tape's grain off) take 46.7x
  real time, the 1 s settle counted. tape_test alone was 16.5x.
- **The bias coupling, measured** (`scripts/tape_bias_study.py` -> `reports/tape/bias_coupling.*`).
  - The bias section is `config/circuits/ampex_351_bias.yaml`: the 12AU7 push-pull
    oscillator, 1T5 and the erase head as coupled inductors (provisional), ERASE ADJUST
    in series with the erase head, the bias from the erase head's hot end through 4R70
    and BIAS ADJUST into the record head, and the 6201 on the head through 1C10.
  - The drawing's note allows leaving out 5C39 ("may be eliminated"), so it is out: with
    it, even BIAS ADJUST's minimum overbiases the provisional head.
  - It runs at 99.3 kc with ~79 mA of erase current. At 24 pF it gives 2.86 mA peak of
    bias, about the 3.0 mA the tape's alignment needs.
  - The record line idles at 299 V with the oscillator's load, 324 V without, and has
    9.7 V p-p of 120 Hz ripple there (0.76 V p-p on 1C2c).
  - The findings:

  | | measured |
  |---|---|
  | literal cost (bias section alone) | 33x / 43x / 64x real time at 1.92 / 3.84 / 7.68 MHz; bias peaks -0.30% / ref / +0.13%, frequency within 0.005% |
  | bias against its B+ (1C2c) | proportional: d ln(bias) / d ln(B+) = 1.08 (2.56-3.17 mA over 236-288 V) |
  | how fast it follows | quasi-static to 500 Hz (1.00 of static), 0.91 at 2 kHz, 0.58 at 10 kHz. 1R59 / 1C2c (10.6 Hz) filters the line, so only slow changes reach it |
  | NOISE BALANCE (+/- asymmetry) | -1.05 / -0.13 / 0.00 / +0.13 / +1.05 dB at 0 / 1/4 / 1/2 / 3/4 / 1 rotation |
  | the bias in the 6201 (missed at audio rate) | at about operating level (0.39 mA of audio in the head): harmonics -68 dB, the rest -63 dB re the fundamental, the bias's AM by the audio 0.02%. At +6 dB: -55 / -49 dB. At +12 dB (1.5 mA): -48 / -34 dB, h3 +1.1 dB, and a level-dependent shift of the driver's operating point (44 uA in the head, settling over ~10 ms) |

  - Option A, the literal oscillator, keeps all of it. It needs:
    - a multi-rate partition in circuitsim: one part at ~40x the audio rate, coupled
      through the record line and the head node;
    - the medium reading the head's whole current, with its peaks found in it, in the
      Python reference and the Rust port.
    - Cost: about +33-43x real time if it runs in turn with the rest (the 351 then about
      80-90x); about +0 if its partition runs on a thread of its own, as the supplies do.
  - Option B, the amplitude at audio rate, needs:
    - the oscillator's + and - peaks as a table against 1C2c's voltage (made by running
      the bias section at setup), with a ~7 kHz lag;
    - NOISE BALANCE's asymmetry;
    - the load above;
    - the medium taking a per-sample bias amplitude.
    - It costs about nothing. It misses the bias inside the head driver: negligible up
      to +6 dB, about -34 dB at +12 dB drive. That is the "turn it to 11" region, where
      the 6201's plate swings with bias and audio together.
  - **Decided 2026-11-01 (the user): A, the literal oscillator.**

**Option A built (2026-11-01): the literal bias in the 351.**
- **Engine: multi-rate parts** (circuitsim's `partition.rs`, `stream.rs`; the IR's
  `Section::substeps`, a section's `substeps:` in a circuit file, both builders).
  - A section with `substeps` m > 1 runs as a part of its own on its own thread, at m steps
    per sample. Sections with the same m form one part. Within a sample it sees the others'
    values interpolated over its steps.
  - It publishes the currents it draws averaged over the sample (the charge moved). It owns
    no shared node.
  - The audio input may be a multi-rate part's: that part reads the stream's input itself,
    the same Lagrange window as the first partition, each step a sub-range of it
    (`StepInput::sub`; identity for every existing run, so they're bit-identical).
  - A tape with the literal bias senses the record head remotely: the multi-rate part
    publishes the sense after each of its steps, and the tape's part pushes them a sample
    later.
  - An IR with multi-rate sections always runs partitioned (`circuitsim.simulate`, `Stream`).
    The single-solve `simulate` refuses it.
  - Test (`tests/partition.rs`): a 99.3 kHz source in a 16-substep part against the whole
    circuit solved as one at the fine step. The audio side agrees within 0.4 mV in the audio
    band (16-sample means), against its 9 mV of 100 kHz ripple; the fast node agrees within
    1e-3 sample by sample.
- **The medium's literal mode** (`TapeStream(literal=M)`, the reference; `tape_stream.rs`'s
  port; the IR's `TapeMedium.bias_substeps`).
  - Each push is M samples of the head's whole field, bias included. Push n carries
    (t_{n-2}, t_{n-1}]: the partition's lag is built in, and the first two pushes are the DC
    point's.
  - A block records at the field's extrema: each local extremum of the samples, refined by
    the parabola through three samples, in the same arithmetic in both languages.
  - The rest of the kernel is unchanged: it already ran on (time, field) lists.
  - Tests (`tests/test_tape_stream.py`):
    - Rust against the Python reference within 1e-11;
    - convergence in M: 32 against 64 within 2e-4;
    - an ideal carrier against the medium's own bias: 0.34% apart, which is physics, not
      error. The extrema of bias plus signal move with the signal's slope, and the own bias
      ignores that;
    - the whole path through a multi-rate partition (an ideal bias plus a tone at 16 substeps)
      equals the reference stream fed the same samples.
- **The tape part:** `bias_substeps: M` makes it sense across a record coil drawn in the
  multi-rate section (`[sense+, sense-, out]`). It then has no record coil of its own, and
  takes no `bias_a_m` or `rec_l_h`. `f_bias_hz` stays, as the oscillator's nominal frequency
  that sets the cells' length.
- **The 351** (`config/circuits/ampex_351.yaml`): the record side from the input on at 20
  substeps (3.84 MHz in production):
  - the record amplifier, the 6201, 1R59 / 1C2c and the record line, the oscillator, 1T5, the
    erase head, the bias feed and the record head (values as in the bias study; 5C39 left out,
    as the drawing's note allows);
  - the audio part keeps the supply, the idle 1V1b, the tape, the repro side and the output;
  - they meet only at the input and the 330 / 250 / 220 V reservoirs.
- **What it took (measured):**
  1. **A signal-path cut isn't stable.** Cutting at 1V2b's plate (1C9 into the multi-rate
     part) diverged within 52 samples: a step there becomes a capacitor current into a high
     impedance node a sample later. Only capacitor-held nodes (the reservoirs) and the input
     can be cut, so the whole record side is in the fast part.
  2. **Production's probes can't show the oscillator.** Probes are decimated from 192 to 96
     kHz, and the decimation filter removes 99 kHz. Measure it at 192 kHz without
     decimation (`oversample` 1). The grids' grid-leak bias, -30 V, is visible either way.
  3. **A start state.** A noiseless symmetric oscillator can sit at its balance point: 1C36
     starts at 0.1 V (`osc_kick_v`, a capacitor's `v0`). With the circuit's noise on, the
     tubes' noise would do it.
- **Running** (`tests/test_ampex_351.py`): the oscillator runs at ~99 kHz, +-229 V on the
  erase head and +-3.8 mA in the record head (bias plus a 0 VU tone). The tone comes back
  off the tape at the output 133 ms later.
- **Speed:** 2 s of the drums at production (JA cores, the 1 s settle counted) take 106x
  real time, against 46.7x for the 351 with the medium's own bias; a tone with linear cores,
  96.6x. The record side's five triodes at 3.84 MHz are the new cost.
- **Next:**
  - the alignment as a procedure: BIAS ADJUST for the bias peak, RECORD LEVEL for 1% THD at
    0 VU, the repro trim and PLAYBACK LEVEL;
  - the `tape_suite` profile and the specs: +-2 dB 30 Hz-15 kHz, the S/N, which now includes
    the oscillator's and the amplifiers' noise;
  - the 351's transport on its tape part;
  - the 12AX7 plates still +22-36% off.

**Speed: the GPU (the user's suggestion, 2026-11-01).** The dev machine has an RTX 3080.
- **The candidate is the recording kernel** (`tape.rs`): every cell times 8 orientations
  over every bias peak in its zone. It is embarrassingly parallel over cells (each cell's
  history is sequential) and dominated the prints before A.
- Also: the demag iteration's FFTs, and alignment sweeps (many bias settings recorded at
  once).
- **Not the circuit:** Newton on small dense systems, sequential in time.
- **The catch: double precision.** The kernel is f64 so that the port agrees with the Python
  reference to ~4e-13, and a 3080 runs f64 at 1/64 of its f32 rate (~0.5 TFLOPS, about this
  CPU's). A big win needs an f32 kernel: a tier of its own, measured against the f64
  reference (a draft print, or the alignment's sweeps), not a replacement.
- **First, measure where the literal 351's time goes.** The tape kernel runs on the audio
  part's thread, the record side on its own, so the slower of the two sets the wall time.
- Planned after TM5's alignment, with TM7 (real time).

**Decided 2026-10-31 (the user): condition dials, "turn it to 11".** Continue in plan order
(TM5 the 351's circuit, then TM6's insert). The insert's panel gets condition dials that go
from a clean, well-kept machine to a trashed one, far past a real 351. Each is a physical
condition, not an effect amount: drive; speed 15 / 7.5 ips; flutter overall, wow, scrape
(the transport's mechanisms scaled); hiss (particle size, or off); bias off its aligned
value; head wear (spacing after alignment: the circuit's EQ trims are fixed parts, so a worn
head plays as on a real machine, not re-aligned away). Also wanted for "trash": dropouts
(lost head contact), print-through, azimuth error, magnetized heads. Render only (no live
audition; prints ~50x real time).
