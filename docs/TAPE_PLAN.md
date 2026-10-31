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
  - 4 iterations: 65x real time, within -41 dB of converged; the default for prints
    now.
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

**TM4 started (2026-10-31):** circuitsim's `tape.rs`.
- Contents: the Preisach tables and corner formula, the vector head field, and the
  recording kernel (cells in parallel, orientations, a steady field during the pass and
  another after it).
- Python bindings `circuitsim.tape_record` and `tape_state_after`;
  `varimu.devices.tape.record(..., engine="rust")`.
- Agreement in `tests/test_tape.py`: particles within 1e-12; recording within 1e-9, scalar
  and vector.
- A bias sweep at kappa 3 takes 37 s against 1751 s in numpy.
- Not yet: the IR element `Tape`, the builders' part, the playback inside a run.
