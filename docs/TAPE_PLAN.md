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
- Slapback (repro to record, the Sun wiring): DELAY_PLAN.md's D1 (SLAP, REPEAT, varispeed
  from the capstan's supply), the first of the echo machines planned there.
- A mix bus: stereo as a two-track on one transport, both channels sharing v(t) (the
  351-2 / 354 family).

**TM7 (optional): real time.**
- A reduced tier measured against production, if it can be made close enough.
- Brainstormed for the delay (DELAY_PLAN.md "Real time", 2026-11-01; live is essential
  there): the delay's 133 ms as the recording's latency budget, the circuit partitioned at
  the medium, a reduced medium generated from the full one (per-layer tables of the
  ensemble, the zone's aperture, playback as a FIR), Option B's bias live; the literal
  351 stays the print.

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

**The alignment, the transport, the first 351 prints (2026-11-01).**
- **The alignment as a procedure** (`varimu/measure/tape_align.py`, outside the render cache
  key; `scripts/align_351.py` -> `reports/tape/ampex_351_alignment.{json,png}`; cached by the
  circuit file, the code and the settings in `cache/tape/align_351_<key>.json`). The manual's
  steps (p79-85), each measured on the whole machine at production's simulation (192 kHz,
  `oversample` 1 so the BIAS meter sees the 99 kHz), 6 runs at once (~2x one run's
  throughput: each keeps two threads spinning), ~32 min:
  1. **Playback EQ, 2R31**, from a virtual test tape: the NAB flux (3180 / 50 us) read by the
     real head (its loss against an ideal reproducer, from the medium) through the reproduce
     side alone (`repro_ir`: driven at the head's EMF, 4x real time), flattest 1-15 kHz re
     700 Hz. Set 0.784 (the standard 50 us is 0.67): moves the curve <= 1.2 dB (the manual
     allows 2), the test tape flat within 0.53 dB rms (+0.7 at 5 kHz, -0.9 at 15 kHz: one
     pole against the gap and spacing losses).
  2. **Bias, BIAS ADJUST**: 1 kHz at 15 ips ("a specific wavelength": 500 Hz at 7.5 ips),
     -10 dB; the 1/2 dB points either side of the peak read on the BIAS meter (the current's
     rms through 5R24), set at their median (the meter reads VU: the geometric mean). Peak
     at 20.2 pF; 1.54 / 2.62 mA rms; set 2.01 mA rms (2.8 mA peak), 20.4 pF. The low point
     sits just inside the trimmer's 15 pF end.
  3. **Record EQ, 1C7**: the flattest low-level response 1-15 kHz re 500 Hz, -10 dB (the
     machine is linear there, so any 1C7's response is the full machine's at one setting
     times the record side's change, `record_ir`). Set 122 pF of 100-550 (as drawn 330:
     +3.2 dB at 10 kHz); left 0.90 dB rms (+1.4 dB at 5 kHz, -1.0 at 15 kHz).
  4. **Record level**: 400 Hz at 0 VU in to 1% THD at the line out: 0.981 rotation (the
     manual's -10 dBm bridging is a minimum input). THD rises slowly with level (0.58% at
     0.7, 1.05% at 1.0): about h2 0.64 / h3 0.71% at 0 VU, the h2 mostly the record
     amplifier's (0.67% in the head current at 0.4 mA rms, before the tape).
  5. **Playback level**: 700 Hz recorded at 0 VU plays at +8 dBm: 0.343 rotation (the
     manual sets it from the test tape before the record level; with a virtual tape the
     operating level is known only after step 4).
  - The check on the aligned machine: 400 Hz at 0 VU, THD 1.00% (h2 0.64, h3 0.71, h5
    0.26%); 700 Hz out -18.02 dBFS; the repro head at 500 Hz -59.8 dB re 0.78 V (the
    drawing's -68 dB plus 8.2); 0.395 mA rms of audio and 2.08 mA rms of bias in the head.
    These are the second run's (with the transport and the recalibrated repro head); the
    first, without them, set the same bias and EQ, record level 0.978, playback 0.291.
  - Not set: ERASE ADJUST, NOISE BALANCE (centred), the meters' calibrations (not modelled).
  - Levels and THD come from band powers (a VTVM behind a band-pass), not coherent fits:
    with the transport, a 15 kHz tone's phase wanders ~3 rad with the motor's hunting.
- **A bug in the first print's alignment, fixed:** the ideal reproducer was a 1e-9 m gap
  between 1 m poles without relaxation, read per unit gap: its far pole edges' term is as
  large as the gap's, so it read 0..2x by frequency (+29.6 dB at 7.5 kHz, +16 dB at 15 kHz
  against the real head). It is now the gap's term alone (e^{-ky} per unit gap): the real
  head reads -0.02 dB at 1 kHz to -1.98 dB at 15 kHz against it, the gap's -0.91 plus 0.5 um
  spacing's -1.07 (test: within 0.15 dB of sinc times exp). The first print's alignment
  cache is versioned (`ALIGN_VERSION`); its existing prints were trimmed from the bad reading.
- **The repro head calibrated to the drawing.** The drawing's boxed levels are 8.2 dB under
  operating level (its mic input -80 dB re 0.78 V against the manual's 200 uV, -71.8 dB, for
  operating level at full RECORD LEVEL); counting that, its record head current (-12 dB "to
  A" across the 1k dummy) is ~2 dB over ours, but the repro head (-68 dB) read 19 dB
  hotter with model knowledge's 2.5e8 A/m per A (~2000 turns at ~230 nWb/m), and 2V3 then
  added ~0.3% h2 at 0 VU (p3a 2.2 V rms against the drawing's ~70 mV). `rep_h_per_a` is
  2.46e7 now (2.9e7 read -58.4 dB at operating level, 1.4 dB over). rep_l_h stays 0.5 H,
  which these turns don't give (harmless: its corner into 330K is ~100 kHz).
- **The transport on the tape part** (both builders): 13 optional physical values, all or
  none (`parts.TAPE_TRANSPORT`, `tape_transport`; varimu-circuit's `tape::TRANSPORT`), the
  first print's mechanisms (capstan runout 30 Hz, idler 3.8 Hz, reel 0.76 Hz, hunting
  2.5 Hz, scrape flutter 4.06 kHz) scaled to the 351's 0.11%; the 351 has them.
- **The first 351 prints** (`scripts/print_351.py` -> `reports/tape/audio/
  drums_setmefree_351_15ips_drive{+0,+6,+12}dB.wav`, each with a loudness-matched dry file;
  the head distance's 133 ms taken out). Without the transport (kept in
  `reports/tape/audio/351_no_transport/`): peaks -6.9 / -3.1 / -1.5 dBFS; against the dry
  file, loudness matched, 60-200 Hz -1.9 / -2.4 / -3.0 dB and 4-10 kHz +2.7 / +3.8 / +5.1
  (bass saturates first), crest 18.6 / 18.3 / 16.8 dB (dry 20.4; the idealized print 18.2 /
  16.5 / 14.4). Three at once in 32 min: 172x real time each, the 1 s settle counted.
  Reprinted with the transport and the recalibrated repro head (re-aligned): the same
  balance within 0.1 dB, peaks -7.0 / -3.2 / -1.5 dBFS, crest 18.5 / 18.2 / 16.9 dB; -8 /
  -7.5 / -6 dB rms from the prints without it (the wander moves the timing); 189x real
  time each.
- No noise yet: the circuit has no `noise` block (no grain, hiss or hum), so no S/N.
- **Next:**
  - the `tape_suite` profile and the specs: +-2 dB 30 Hz-15 kHz, the S/N with the circuit's
    noise (the oscillator's, the tubes', the grain);
  - the 12AX7 plates still +22-36% off;
  - see "Gaps" below for the order from here;
  - the record head and the bias side stay provisional: the drawing puts the operating
    level's head current at ~0.50 mA rms (if "to A" is across the 1k dummy), ours 0.39: a
    head ~2 dB less sensitive would match, its bias then ~2 dB more (inside BIAS ADJUST).

**Gaps, and the order to close them (the user's list, 2026-11-01).** Checks before fits,
and a baseline of each check before the physics changes, so a change shows what it does
out of sample.
1. **TM5's done-when** (in progress): the `tape_suite` profile. +-2 dB 30 Hz-15 kHz at 15 ips;
   the S/N with the circuit's noise (the oscillator's, the tubes', the grain); idle voltages,
   with the three 12AX7 plates (p3a, p3b, p4b, +22-36%) traced to their cause (12AX7@1's fit
   at low currents on 220-330K, the grid current's contact potential on 2V3a's 10 MOhm leak).
   **Plus a real machine's data:** the manual's p94 has Ampex's record and reproduce response
   curves at 15 ips NAB (record: typical / maximum / minimum over the HF trimmer, +5 dB at
   30 Hz; reproduce: about +14 dB at 30 Hz to -16 dB at 15 kHz re 1 kHz). Digitized
   (`data/datasheets/ampex_351_response_15ips.csv`, `ampex_351_manual.provenance.yaml`),
   they check `record_ir` / `repro_ir` (the electronics, measured, not fitted; test
   `test_the_electronics_follow_ampexs_measured_curves`). Done: re 1 kHz the record side
   at 1C7's ends follows MINIMUM and MAXIMUM within 1.1 dB (30 Hz -0.95: a little less bass
   lift than Ampex's), the reproduce side within 0.6 dB from 200 Hz up but +1.0 / +1.7 /
   +2.2 dB at 100 / 50 / 30 Hz (more bass than Ampex's: 2R29's shelf or a coupling
   capacitor; a lead for the +-2 dB spec at 30 Hz). The alignment's 1C7 (122 pF: +1.1 dB at
   15 kHz) sits between the curves' minimum (+0.95) and typical (+2.6): our tape and heads
   give ~1.5 dB more treble than Ampex's average tape.
   **The 12AX7 plates, traced (2026-11-02):** the drawing's voltages give each stage's
   current (the plate load's drop; 2V3b's cathode, 1.0 V on 1500 ohm less 2R26's bleed,
   agrees). At the drawing's own grid and plate voltages, 12AX7@1 (Koren) gives 2V3b
   0.093 mA against 0.273, 2V4a 0.177 against 0.318, 1V1a 0.263 against 0.500, but 2V4b
   0.388 against 0.409 and 1V1b 0.483 against 0.500; the circuit then settles where the
   model makes the current, at higher plates. GE's 12AX7 sheet (ET-T509B, 6-53, average
   plate characteristics: the -1.0 V curve starts near 100 V) agrees with Koren there. So
   the drawing's unit had three tubes hotter than average: their grids as if +0.14..+0.21 V
   less negative (contact potential and cathode activity vary that much between tubes),
   two average ones. Not a modelling error. Options (the user's): leave the average tubes
   (plates +22-36%, the done-when's idle check excepted for them); per-instance emission
   on those three (x1.8-2.9: beyond the tube tolerance's +-10%, the wrong mechanism); or a
   per-instance grid offset in the triode model (both engines; a provisional +-0.2 V
   spread, the physical one), the drawing's three then +0.14..+0.21 V. **Decided
   (2026-11-02, delegated by the user; not emission): the nominal unit keeps average
   tubes.** The three plates stay outside the done-when's +-20% idle check, for this traced
   reason (`tests/test_ampex_351.py` bounds them at +-40%, `tape_suite`'s idle report lists
   them). A per-instance grid offset is the mechanism if unit-to-unit tube spread (or a
   "tired tubes" condition dial) is wanted later.
   **The profile, first run (2026-11-02; `varimu unit --circuit ampex_351 --name
   ampex351_nominal` -> `reports/units/ampex351_nominal/`; the noise on, the transport on;
   23 renders 6 at once, 27 min after the cached alignment):**
   - **S/N 61.6 dB** (spec 60): the 3% level -14.6 dBFS rms out, the noise 50-15,000 Hz
     -76.2 dBFS rms (tubes, resistors, mains wander, grain, bias and erase all in).
   - **Idle** within +-20% except the three average-tube plates (decided above).
   - **Response at -10 dB fails at the low end:** re 1 kHz, 30 Hz -0.7, 40 +1.9, 50 +1.7,
     **70 -4.45**, 100 -2.0, 200 -1.6, 500 -0.1; 2-15 kHz +0.3 / +1.2 / +1.0 / +0.5 / -0.4 /
     -1.4. The dip is the repro head's contour effect: the poles' far edges cancel the gap's
     reading where cos(k e_c) peaks, e_c = g/2 + pole + relax/2 = 4.5 mm with the
     provisional 3 mm poles and 3 mm relaxation (~85 Hz at 15 ips). Real heads have these
     bumps; the 351's spec says its were within +-2 dB. The pole and contour dimensions are
     unprinted (item 4); the reproduce side's own +2 dB at 30-50 Hz (p94) adds to the
     40-50 Hz bump.
   - **Distortion at 400 Hz** (in re 0 VU: THD / h2 / h3 %): -10 dB 0.44 / 0.24 / 0.36;
     -5 0.52 / 0.40 / 0.30; 0 1.00 / 0.62 / 0.74; +3 2.46 / 0.71 / 2.33; +6 5.32 / 0.79 /
     5.25; +9 9.9; +12 16.1 (out -9.6 dBFS rms). The 3% level is **+3.8 dB** over
     operating level, against the manual's "6 db higher" (p84): h3 rises ~3.3 dB per dB
     from 0 to +3, steeper than cubic. Saturation sets in too abruptly, in the same
     direction as No. 21's too-narrow bias curves: both say the particles switch too
     uniformly, the case for item 3.
   - The alignment with the noise on: record level 0.990, playback 0.336, bias 20.6 pF,
     THD 1.00% at 0 VU.
2. **Baseline checks on the current tape model** (no fitting): No. 14 (permissible level
   against frequency, 7.5 ips) and No. 31 (output against coating thickness).
   - No. 14 prints no figure: by third-order cross-modulation (2F1 - F2), Scotch 111's
     permissible recording current at 7.5 ips is "constant up to about 1200 cps", then rises
     "until at 7000 cycles, 4 db greater"; "a wavelength rather than a frequency effect".
     `scripts/tape_bulletin14.py` (the medium alone, the first print's machine and bias,
     F2 = 1.1 F1, two criteria since none is printed, 15 ips at the same wavelengths).
     **Baseline (2026-11-02, `reports/tape/bulletin14.*`, 6 min):** the permissible field
     re 400 Hz at F1 400 / 800 / 1200 / 2000 / 3000 / 5000 / 7000 Hz, 7.5 ips: 0 / -0.4 /
     -0.4 / -0.9 / -1.3 / -2.1 / -1.8 dB (2F1 - F2 at -40 dB), 0 / -0.4 / -0.2 / -0.6 /
     -0.9 / -1.1 / -1.0 dB (at -30 dB); 15 ips at the same wavelengths within 0.5 dB (the
     bulletin's wavelength claim holds). **The direction is wrong:** the model takes
     slightly less current at short wavelengths where #111 took 4 dB more at 7 kHz: a
     ~5-6 dB miss. 3M ties it to the coercivity ("a direct correlation between coercive
     forces and the permissable high frequency pre-equalization"): the switching again,
     with No. 21's narrow bias curves and the profile's abrupt saturation. Rerun after
     item 3.
   - No. 31: three "high output" coatings, 0.25 / 0.5 / 1.0 mil, at 7.5 ips: Fig. 2 at the
     thickest's optimum bias (long-wavelength output ~3-4 dB per doubling of thickness),
     Fig. 3 at the thinnest's (the three nearly one curve), Fig. 4 each at its own (the
     thick one more bass, fewer highs). The check: our tape's coating thickness varied,
     everything else kept, against those trends (the coatings aren't #111's: trends, not
     levels).
3. **Frequency-dependent switching** (the leading untested candidate for No. 21's narrow bias
   curves, TM2 step 7): Sharrock's law, Hc(t) = H0 [1 - (kT / KV ln(f0 t / ln 2))^n]. Bulletin
   20's Hc is from 60 Hz loops (~8 ms per switch), recording happens within a bias period
   (~5 us), so ln(f0 t) falls from ~16 to ~8.5 (f0 ~ 1e9 Hz): harder switching at bias rates,
   and a wider spread from the particles' volume distribution. Nearly parameter-free here:
   TM3 fitted the particle volume (1.66e-21 m^3) from the noise. A new tape version, the bias
   curves (No. 21) and the checks of 2 rerun; options with numbers to the user first (it
   moves the alignment and every print).
   **Measured 2026-11-02: not the cause; closed without a model change (the user agreed: the
   misses stay open, other mechanisms next).** `scripts/tape_switching_study.py` ->
   `reports/tape/switching_study.{json,png}`, `switching_level_diag.json` (~45 min, the Rust
   kernel; nothing in varimu/ changed). Each variant maps Bulletin 20's 60 Hz ensemble to the
   bias's rate by Sharrock's law (Monte Carlo over particles, refitted as a lognormal; L60
   16.3, Lb 5.8 at 70 kHz, provisional: 0.1 rad of the drive's cycle, f0 1e9 Hz, the meter's
   loop traced ~30 times) and records with it; the interaction field (static) unchanged.
   - **The barrier.** The noise fit's particle with coherent rotation (Ms_p ~360 kA/m, H0 ~1.1
     Hc) has K V / kT ~1950: the bias-rate Hc only 4% up, the spread unchanged. Incoherent
     reversal switches a smaller volume; no gamma-Fe2O3 tape value was found to cite, so
     400, 150 and 60 (n 0.735) bracket it.
   - **The sign of the spread depends on what is independent of the barrier:** with the 60 Hz
     Hc independent, the spread widens (0.283 -> 0.303 at K V / kT 150); with the athermal H0
     independent (shape anisotropy from the aspect ratio, the barrier from the volume), part
     of the 60 Hz spread is thermal and the bias-rate spread narrows (0.228). The hypothesis
     that a volume spread widens it holds only in the first case.
   - **The checks** (No. 21: rms 1k / 15k after one bias scale; the 1 kHz rise at 3 mA, -11.0
     measured; the over-bias fall at 8 mA, 1k -3.3 / 15k -7.1; the 3% level at 400 Hz, 15 ips;
     Bulletin 14 at 7 kHz, +4 by 3M):

     | variant (bias-rate Hc ratio, sigma) | No. 21 rms | 1k at 3 mA | 1k / 15k at 8 mA | 3% level | No. 14 (-40 / -30 dB) |
     |---|---|---|---|---|---|
     | base SCOTCH111@3 (1.00, 0.283) | 2.25 / 1.74 | -5.5 | -3.2 / -5.1 | +3.33 | -1.8 / -1.0 |
     | coherent, K V / kT 1950 (1.04, 0.284) | 2.24 / 1.82 | -5.5 | -3.2 / -5.0 | +3.35 | -1.9 / -0.9 |
     | 400 (1.11, 0.286) | 2.20 / 1.77 | -5.6 | -3.1 / -5.1 | +3.40 | -1.9 / -0.7 |
     | 150, Hc60 independent (1.22, 0.303) | 2.06 / 1.65 | -5.6 | -2.9 / -4.8 | +3.48 | -1.8 / -0.6 |
     | 150, H0 independent (1.21, 0.228) | 3.11 / 2.47 | -4.3 | -4.4 / -7.6 | +3.37 | -1.1 / -0.4 |
     | 60, n 0.735 (1.39, 0.46, skewed) | 1.39 / 1.49 | -7.2 | -0.4 / -2.3 | +3.74 | -2.2 / -1.0 |
     | not physical: sigma 0.45 | 1.42 / 1.51 | -6.8 | -0.6 / -2.1 | +3.53 | -2.8 / -1.7 |
     | not physical: sigma 0.60 | 1.65 / 2.06 | -7.1 | 0.0 / -1.0 | +3.66 | -3.3 / -2.1 |

     The plausible range moves every check by <= 0.4 dB. Even a forced spread only trades
     No. 21's rise (and its peaks, 6.1 / 5.4 mA against 6 / 5) for its over-bias fall, and
     pushes No. 14 further the wrong way.
   - **The 3% level isn't the switching spread's at all.** In this Preisach model the
     anhysteretic is exactly erf(h / (sqrt 2 sigma_Hi)) for every hysteron the bias reaches,
     whatever f(Hc): 3% THD at **+4.9 dB** over 1%, scalar or oriented. The medium is steeper
     (+3.3). Off one at a time, demag (+3.33), the head's image (+3.24) and orientation
     (kappa 20: +3.21) change nothing; more bias cycles per freezing do: the bias 4x faster
     (cells scaled) +3.76, **the Ampex 300's 51 um record gap +4.00** (ours is the provisional
     12.7 um). The trailing edge's field falls ~15% per bias cycle at 15 ips (steps of ~45 Oe
     against sigma_Hi 64 Oe): a cell sees too few cycles for the ideal anhysteretic.
   - **#111's own figure for the knee:** Sound Talk No. 1 (1948, p.2, h3 against output at
     400 Hz, 7.5 ips, a Brush head, 40 kHz bias; read by eye at 300 dpi, ~+-0.3 dB): 1% -> 3%
     h3 in ~4.1 dB of output at 2.4 ampere-turns of bias, ~4.5 at 3.2; steeper overbiased
     (8.0: ~3.4), much softer underbiased (1.6: ~7.5). The manual's "6 db" is a round figure;
     the miss against the tape's data is ~1-1.5 dB (our +3.3 is in recorded field, ~+3.0 in
     output). Not digitized as a CSV yet.
   - **Where the misses go:** the knee to the record zone (the record gap's length and field
     gradient, item 4) and the transfer curve's shape (the interaction field's Gaussian);
     No. 14 to the record head's field at bias against audio (item 4) or short-wavelength
     demagnetization; No. 21's rise to the head's field against current (item 4).
4. **The heads:** no 351 / 350 head data printed (the Minneapolis Magnetics notes are a scan
   without electrical data); keep looking (replacement head sheets: Nortronics, Woelke). The
   record head's field per ampere at the bias frequency against audio (laminated cores lose
   efficiency near 100 kHz: frequency-dependent, linear) and against current (pole tips
   saturating: sublinear) is No. 21's other candidate. The tape part has one `rec_h_per_a`
   for both bands now.
   **Since item 3 (2026-11-02) the heads lead for two misses:** the knee (the record gap 12.7
   -> 51 um moved the 3% level +3.3 -> +4.0 dB; #111's data ~4.1-4.5) and the 70 Hz dip,
   and are the first place to look for No. 14. A head maker's numbers (web:
   https://www.discolathe.com/.pdfs/Nortronics_Silvr_pp1-9.pdf, Nortronics' "Design
   Digest" application notes, catalog pp.2-9, ~1975; not 351 data): the longest wavelength a
   play head reads is the mean of its window and pole lengths; standard heads cut off at
   50 Hz at 7.5 ips, the long-pole WP series at 50 Hz at 15 ips, the Studio / PR series'
   "extra long pole pieces" at **25 Hz at 15 ips** (a ~15 mm wavelength; Fig. 3 plots their
   15 ips curves). Our provisional e_c of 4.5 mm dips at ~85 Hz, a standard head's. Typical
   gaps: play 200 uin (5 um) for 15 ips, **record 500 uin (12.7 um) for 1/4" tape**; metal
   erase cores have "good efficiency up to 60 kHz" (laminations' loss near the bias
   frequency).
   **The study** (`scripts/tape_heads_study.py` -> `reports/tape/heads_study.{json,png}`):
   - **Nortronics' 15 ips curves** (Fig. 3, read at 400 dpi), dB re flat at 20 / 30 / 40 / 50 /
     70 / 100 / 150 / 200 / 300 Hz: WP -5.0 / 0 / +2.0 / +3.0 / +2.2 / +0.7 / -1.2 / -0.5 /
     +0.3; PR / Studio 0 / +1.8 / +1.5 / +0.3 / -1.0 / -0.1 / -0.2 / 0 / 0. The model's head
     (linear relaxation) fits them within 0.58 dB (WP: poles 1.25 mm, relaxation 4.0 mm) and
     0.40 dB (PR: 3.5 / 20.25 mm). The old 3 / 3 mm: +3.8 / +5.3 / +4.3 dB at 30 / 40 / 50 Hz,
     -2.7 at 70.
   - **The aligned machine's low end by block** (re 1 kHz, 30 / 50 / 100 / 200 Hz): record
     electronics +4.05 / +2.45 / +0.85 / +0.23; the medium's flux flat (+0.4); the EMF's
     6 dB/oct plus the reproduce electronics -8.8 / -5.3 / -2.3 / -1.0 (ideal NAB playback of
     NAB flux: the record side should lift ~+5.8 dB at 30 Hz, the reproduce side is 2.6 dB
     under ideal NAB there). Ampex's own measured electronics (p94) have still less bass: a
     flat 351 needed a head that **lifted** the bass, +5.6 / +3.7 / +1.7 / +1.0 dB. No single
     relaxation (linear or raised cosine) makes that without ripple (best 2.7-2.9 dB off): the
     real head shapes its low end with more than one scale (Nortronics' third factor, the
     lamination behind the face). With our electronics, poles 1.5 mm / relaxation 5.5 mm put
     the whole machine within 1.53 dB 30 Hz-1 kHz (WP-like).
   - **The record gap** (medium alone, the first print's machine, each aligned; 3% level over
     1% / No. 14 at 7 kHz (-40 / -30 dB criteria) / 15 kHz re 1 kHz before EQ): 12.7 um +3.33 /
     -1.8 / -1.0 / +7.4; 25 um +3.69 / +0.3 / -0.2 / +4.9; 51 um +4.00 / -3.1 / 0.0 / +1.8 (the
     -40 dB crossing erratic). A 51 um gap records at 0.40x the deep-gap field (bias 1.69 Hc
     against 3.0).
   **Applied (2026-11-02, the user's choices: 51 um, the contour; with speed lever 2's 10
   substeps, later reverted to 20, below):** `config/circuits/ampex_351.yaml` rec_gap_m 51 um (Bulletin 21's Ampex 300;
   Minneapolis Magnetics fits one head to the 300 / 350 / 400), pole_m 1.5 / relax_m 5.5 mm
   (calibrated, near the WP head), rec_h_per_a 8.0e6 A/m per A (operating level at ~0.39 mA
   rms of audio, RECORD LEVEL near its top as before; No. 21's fit measured 6.7e6 for the 300's
   51 um head), so ~480 turns: rec_l_h 3 mH, rec_r_ohm 160. (Keeping 2.0e7 with 4x the turns
   overbiased the head at BIAS ADJUST's minimum: the alignment refused it.)
   - **Aligned:** 2R31 0.788, bias 31.1 pF (2.95 mA rms; the 1/2 dB points 2.48 / 3.51), 1C7
     437 pF (between Ampex's typical and maximum curves: the long gap's treble loss), RECORD
     LEVEL 0.946, PLAYBACK LEVEL 0.390; check: THD 1.00% (h2 0.68, h3 0.71, h5 0.19), audio in
     the head 0.38 mA rms, the repro head at 500 Hz -61.3 dB re 0.78 V (the drawing's -68 + 8.2
     = -59.8: 1.5 dB under; rep_h_per_a left as calibrated, as the 1.4 dB before).
   - **Profile** (`varimu unit --circuit ampex_351 --name ampex351_heads51`, 35 min; the old
     one kept as `ampex351_nominal`):
     - **Response passes:** re 1 kHz 30 Hz -1.84, 40 +0.19, 50 -0.23, 70 -1.74, 100 +0.27, 200
       -0.40, 500 -0.31, 2k +0.60, 5k +0.94, 7.5k +0.01, 10k -0.12, 12.5k -0.35, 15k -1.42
       (was -4.45 at 70 Hz).
     - **The knee:** THD at +3 / +6 / +9 / +12 dB 1.95 / 4.00 / 7.57 / 12.8% (was 2.46 / 5.32 /
       9.94 / 16.1): the 3% level **+4.8 dB** over 0 VU (was +3.8), on #111's own data (Sound
       Talk No. 1, ~4.1-4.5 dB of output, ~4.4-4.8 of input).
     - **S/N fails: 58.3 dB** (was 61.6; spec 60, its method unprinted). The noise rose 1.2-1.7
       dB below 1 kHz (the playback gain) and +6.7 / +12.1 / +5.1 dB at 1-3 / 3-8 / 8-15 kHz:
       the record EQ (1C7 437 pF against 122) lifts the record amplifier's hiss before the
       tape. A real Ampex 300 met 60 dB with a 0.002" gap, so the model's long-gap treble loss
       or the record side's hiss is a little high: open, the user's next question after
       listening.
   **The S/N miss traced (2026-11-02; `scripts/tape_snr_study.py` -> `reports/tape/
   snr_study.*`, `snr_cells.json`, `snr_substeps.json`): a numerical line, not the record
   amplifier.** The profile's noise measurement with the circuit's noise sources kept in some
   sections only (streams keyed by name, so the others' samples are unchanged), the grain off
   by an effectively infinite particle count:
   - with **no noise at all** the machine put -75.2 dBFS into 50 Hz-15 kHz, nearly all a line
     at ~3.3 kHz (-78.6 dBFS): S/N capped at 61.2 dB by it alone. The real noise, the floor
     taken out in power, was -75.4 dBFS (S/N 61.5): the reproduce side's (2V3's hiss and
     flicker under the NAB bass boost, -83 dBFS at 100 Hz) dominates; the grain, the record
     amplifier, the bias section and the supply are each 15+ dB under it.
   - The line didn't move with the cells (as built, 7.62 per wavelength of the measured
     oscillator, half length: within 0.1 dB, all at 3374 Hz): not the medium's sampling. It
     followed the record side's step: -78.6 / -93.0 / -101.6 dBFS at 10 / 20 / 40 substeps.
     The 10 substeps of speed lever 2 had made it (its check compared band levels on drums,
     where a -78 dBFS line can't show). The oscillator now runs at **92.9 kHz** (the 3 mH head
     and BIAS ADJUST's 31 pF), the line near 96 kHz - f_osc.
   - **The peak finder:** the literal bias's extrema were refined by the parabola through
     three samples, whose value error, ~(w h)^4 (2e-4 of the carrier at 20.7 samples per
     period), depends on where the samples fall and so beats against the oscillator. Now
     `refine_extremum`: the quartic through five samples, Newton from the parabola's offset
     (3 fixed steps; one converges), both languages (Rust against Python within 1e-11
     unchanged; `tests/test_tape_stream.py::test_the_extremum_refinement_is_quartic`: 4e-6 at
     20.7 samples, ~h^6). Measured: 10 substeps -86.4 dBFS (floor -81.8), 20 substeps -95.7
     (floor -91.6). Another error, ~9 dB per halving, is left at 10 substeps (the circuit's
     own step at ~20 samples per period, probably): a speed lead.
   - **Back to 20 substeps** (the criterion the user chose: the floor 14 dB under the real
     noise, -89.4 dBFS; 10 substeps' -81.8 fails, 20's -91.6 passes), keeping the quartic.
     Speed lever 2's 1.21x is given up.
   - **Re-aligned and profiled at 20 substeps** (`ampex351_heads51`, 34 min after the
     alignment): the settings as at 10 (bias 31.1 pF, 1C7 437 pF, RECORD LEVEL 0.945, PLAYBACK
     LEVEL 0.391); the response and the knee unchanged (3% at +4.8 dB); **S/N 61.0 dB, passes**
     (noise -75.0 dBFS). **TM5's done-when is met:** +-2 dB 30 Hz-15 kHz, S/N, idle (the three
     average-tube plates excepted, decided above).
5. **SM911** (TM2's second part): the same physics with only the tape's parameters changed,
   against EMTEC's IEC curves and stated gaps: the first true out-of-sample test.
6. **A real machine:** any recording of a real 351 (or 350) with Scotch 111-era tape, a test
   tone or program with its source, would show what no bulletin can (the user's call).
7. **Known approximations**, to consult when a mismatch shows: no print-through, no erase
   field (complete erasure), no magnetized heads, no azimuth; demagnetization of the audio
   band only, a fixed point per block; cells a 2D slab, not 3D; Preisach interaction a fixed
   Gaussian, not a mean-field (moving) model.

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
- **Where the literal 351's time goes (measured 2026-11-01**, 0.5 s of drums at +6 dB,
  production, the 1 s settle counted, one job alone): the whole machine 100x real time; the
  record side alone (20 substeps, its five triodes and the oscillator on one thread) 62.7x;
  the tape kernel (the audio part with the tape on its own bias, the same recording) 36.3x;
  the reproduce side without the tape 2.5x. 100 is about 63 + 36: the parts don't overlap.
  The stream records a 16 mm block inside the audio part's step (the kernel on all
  threads), and the record side, a sample apart, waits on it. Three prints at once:
  189x each (63x aggregate).
- **The levers, in order** (estimates until measured):
  1. Record blocks asynchronously: the repro head reads a block ~3 blocks after it's
     recorded, so a worker can record while the circuit runs on. Exact (bit-identical);
     the time becomes about the larger part's: ~1.5x (100x -> ~65x). **Done
     (2026-11-02):** `tape_stream.rs`'s `Worker` (a thread per stream recording blocks in
     order: a block's recording reads no other block's, its margins are its own) and
     `Recorder` (zones, the kernel, the demag fixed point, with its own FFT plans and
     kernels); the stream prepares each block's field when its samples are in, finishes
     blocks (grain, slopes) in order, and waits only for the blocks a push reads. Output
     bit-identical to before (the 351's medium, literal with flutter and grain, and its own
     bias, 0.5 s in odd chunks). The kernel's threads are now a setting
     (`Recording::threads`, `TapeStream::set_threads`; the output doesn't depend on it): in
     a circuit the media leave four logical cores to the circuit (16 / 12 / 8 / 6 / 4
     threads: 80 / 72.9 / 72.8 / 75.8 / 85.6x on the 351), alone the stream takes all (8%
     faster than 12). **The 351: 100x -> 74.6x real time (1.34x)** on the same excerpt
     (72.9x in another run); the record side alone (62.7x) is now the floor, so lever 2 is
     next for speed.
  2. The record side: fewer substeps (the bias study: 10 instead of 20 moved the bias
     peaks 0.3%; ~2x on that part), tube tables there (the draft's, 9e-8 of the model),
     and the record amplifier's first two stages at the audio rate if a stable cut exists
     (only the oscillator, the 6201 driver and the head need 3.84 MHz). Together ~3-4x on
     that part; each a measured setting against production.
     **Measured (2026-11-02, `scripts/speed_351.py` -> `cache/tape/speed/results.json`; the
     harness above with the circuit's noise off, so runs compare sample by sample; the first
     runs shared the CPU with another session and were timed again):**

     | setting | x real time | waveform vs 20 substeps | band levels vs 20 / vs 40 substeps |
     |---|---|---|---|
     | production (20 substeps) | 78.7 | | 0.020 dB vs 40 |
     | tube tables everywhere | 71.8 (1.10x) | -121 dB | 0.000 |
     | 10 substeps (1.92 MHz) | 65.0 (1.21x) | -46.4 dB | 0.034 / 0.014 dB |
     | 10 substeps + tables | 61.5 (1.28x) | -46.4 dB | 0.034 / 0.014 dB |
     | 40 substeps + tables | 96.5 | -48.1 dB | |
     | 20, the oscillator started 10% off (1C36 0.11 V) | 74.8 | -56.7 dB | 0.002 dB |

     - **A waveform comparison can't judge the record side's step:** the free oscillator's
       phase against the signal moves the bias pattern, so any two step sizes (and the same
       step from a slightly different start) differ by -46 to -57 dB in waveform while their
       third-octave levels (50 Hz-15 kHz) agree within 0.034 dB. In band levels 10 substeps is
       as close to 40 as 20 is.
     - **10 substeps: adopted with the heads' change, then reverted:** it left a line near
       96 kHz - f_osc in the noise that band levels on drums can't show (-78.6 dBFS; S/N 58.3
       dB). Judge the record side's step on the noiseless machine's floor, not only on music
       ("Gaps" 4, the S/N miss traced).
     - **After the quartic peak finder (2026-11-02; `scripts/tape_snr_study.py --cells --grid`,
       the noiseless machine's floor; `scripts/speed_351.py`, the new heads, one job alone):**

       | record side | line near 96 kHz - f_osc | noiseless floor | x real time (drums) | bands vs 40 substeps |
       |---|---|---|---|---|
       | 20 substeps, error control on (was production) | -95.7 dBFS | -91.6 | 87.8 | 0.058 dB |
       | **20, no error control** | **-113.7** | **-95.2** | **83.7** | 0.064 dB |
       | 10, error control on | -86.6 | -82.1 | | |
       | 10, Newton 100x tighter | -86.2 | -81.4 | | |
       | 10, error control 10x tighter | -82.9 | -80.1 | | |
       | 10, no error control | -82.7 | -80.4 | 71.4 | 0.053 dB |
       | 40, error control on | | | 114.2 | |

       10 substeps is under-resolved for the 92.9 kHz oscillator whatever the integrator does
       (the floor 14 dB under the real noise needs <= -89.4). Local error control in the fast
       part only adds artifacts: its subdivisions follow where the oscillator's peaks fall in a
       step and beat against it (tighter is worse). **Now circuitsim's multi-rate parts step
       without local error control** (`stream.rs`; partition.rs's docs; the audio part keeps
       it for the 6X4), the 351 re-aligned and profiled with it. The part's speed is now its
       fixed step's: the levers left are the triodes' cost per step (tables, ~10%), the GPU for
       the tape (lever 3), and a draft tier (lever 4).
     - **The caches don't see circuitsim's source.** The render cache key and the alignment's
       hash the Python code (`runner.code_version`: varimu/{sim,circuit,devices}, config.py),
       not `circuitsim.SOURCE_HASH`, so a Rust-only engine change reuses old renders and
       alignments (this change: the 351's 69 cached renders deleted by hand, `align_351.py
       --refresh`). Adding SOURCE_HASH to the code version would make every circuitsim edit
       re-render everything (the 670's suite: hours): the user's call.
     - **Tube tables: not adopted.** Exact here, but 10% for a global production setting that
       would move every other circuit's renders (the cache key).
     - **The audio-rate cut through the record amplifier: not pursued.** At 10 substeps the
       record side is no longer the floor (the tape part alone was 36.3x): what's left is how
       the parts overlap and the tape kernel (lever 3).
  3. The tape kernel on the GPU as an f32 tier, validated against the f64 kernel: the
     kernel is already parallel over 16 threads, so the gain is the 3080's f32 throughput
     over this CPU's f64, perhaps 5-10x on that part. Only worth it after 1-2, when the
     tape is the bound.
  4. Option B (the bias's amplitude at the audio rate, TM5's measurement) drops the
     3.84 MHz part: the 351 was 46.7x with the medium's own bias, the tape kernel most of
     it. A draft tier for auditioning (it misses the bias in the 6201: -34 dB at +12 dB).
  - All four: perhaps ~10-20x for the literal print, a few x with option B and the GPU.
    Real time needs TM7's reduced medium (DELAY_PLAN.md "Real time").
  - **Continued in [TAPE_SPEED_PLAN.md](TAPE_SPEED_PLAN.md)** (2026-11-02): the levers
    re-ranked after this section's measurements (P1-P6) and a fast tier trained on the
    literal machine (F1-F5).

**Decided 2026-10-31 (the user): condition dials, "turn it to 11".** Continue in plan order
(TM5 the 351's circuit, then TM6's insert). The insert's panel gets condition dials that go
from a clean, well-kept machine to a trashed one, far past a real 351. Each is a physical
condition, not an effect amount: drive; speed 15 / 7.5 ips; flutter overall, wow, scrape
(the transport's mechanisms scaled); hiss (particle size, or off); bias off its aligned
value; head wear (spacing after alignment: the circuit's EQ trims are fixed parts, so a worn
head plays as on a real machine, not re-aligned away). Also wanted for "trash": dropouts
(lost head contact), print-through, azimuth error, magnetized heads. Render only (no live
audition; prints ~50x real time).
