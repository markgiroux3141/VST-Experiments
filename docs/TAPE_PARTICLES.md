# Tape at the particle level: a bench for the Preisach model

2026-11-12, one overnight session (the user asleep, every call made here and written down).
A study: nothing in `varimu/devices`, the circuits or the render cache changed. The
question (EMERGENCE_RESEARCH.md section 10, TAPE_PLAN.md TM2 step 7): built from physical
particle parameters and fitted only to static data (Sound Talk No. 20's remanence curve,
Eilers' Hc), does a particle simulation predict No. 21's dynamic bias curves better than
the Preisach model, without being fitted to them? If it does, it is a trustworthy virtual
bench for the cheap model; if it needs No. 21 to get there, it adds nothing.

The literature behind every value is VST-chirp's `docs/TAPE_PARTICLE_RESEARCH.md` (written
the same night by another session; cited here as "research" with its section). Its
recommendation, which this session followed: first a small decisive bench (no head, no
transport), then the moving head only if the bench leaves the question open.

**Verdict:** see "Verdict" at the end.

## The model

### Particles (`varimu/tape_particles/sw.py`, `ensemble.py`)

- **Single-domain Stoner-Wohlfarth macrospins** with uniaxial anisotropy along the needle.
  The moment lies in the plane of the easy axis and the field; its energy
  e(theta) = 1/2 sin^2 theta - a cos theta - b sin theta (a, b the field's components along
  and across the axis over H_K) has both minima and the saddle between them in [0, pi].
  They are found on a 32-point grid of e' and refined by safeguarded Newton; a minimum and
  saddle closer than a grid step (a barrier of ~(0.1 rad)^3, thermally irrelevant) are
  missed, which switches a particle up to 0.3% before the astroid (tested).
- **Thermally activated switching, not LLG:** quasi-static minima, Neel-Brown rates
  f0 exp(-dE / kT) over each barrier, the two-state chain over each step solved exactly.
  Two modes: the master equation (expected state per particle) and kinetic Monte Carlo
  (states +-1, a counter-based hash per particle and step, the same in Python, Rust and
  WGSL). The bench uses kinetic Monte Carlo (an interacting erased state needs real signs).
- **The barrier's scale** K V_act / kT, median 150 (research 1.6: not found for period oxide,
  bracket 60-2000; the earlier switching study showed <= 0.4 dB over that range), V_act
  proportional to the needle's volume.
- **The anisotropy field is effective and fitted** (research 1.4: the ideal SW field of a
  5:1 needle is ~1900-2200 Oe, ~5x the measured switching; incoherent reversal can't be
  predicted from geometry within 2-3x). The SW angular law is kept.

### The bench (`varimu/tape_particles/bench.py`; Rust `bench.rs`, GPU `bench.wgsl`)

- **Needles** 0.5 um long, 5:1 (Westmijze 1956's micrograph, research 1.3), length log
  spread 0.3 (volume spread 0.9; research 1.3's 0.6-1.0), easy axes isotropic (research 1.5:
  #111 predates orientation; the relaxed packing's nematic order is 0.01), at packing 0.35
  (research 1.5: 0.28-0.40), Ms_p 360 kA/m (research 1.2), in a periodic cube (N = 2000:
  3.3 um, ~6.5 needle lengths).
- **No overlaps** (`pack.py`): random placement at 35% packing overlaps heavily, and
  overlapping needles' end charges put ~1000 Oe on each other; random sequential addition
  jams far below 35% for 5:1 needles. Centres and axes are relaxed apart until no two are
  closer than 0.8 of their width (N = 4000 in 83 s, cached).
- **Dipolar interactions, dynamic:** each needle's moment along its axis is two magnetic
  charges at its ends, the part across it a point dipole at its centre; the field on a
  needle is averaged over 5 points along it, from every other needle at its minimum image,
  softened over 0.05 um (half the width). The charges are wrapped one by one, so both
  signs fill the cube uniformly and need no Lorentz term (their sum is the periodic,
  conducting-boundary one); the point dipoles are wrapped whole and get M_perp / 3. The
  sample's demagnetization is (0, 1, 0): a coating, thin in depth, long along the tape.
  Every step's field follows every needle's state.
- **Variants for the question:** `dynamic` (the physics), `frozen` (each needle keeps the
  field it saw in the erased state: a static interaction field per particle, the Preisach
  picture) and `none`. Each variant is fitted to the static data on its own.
- **The erased state** is made, not assumed: from random signs, an AC field along the tape
  decaying from 2000 Oe to 0 over 60 cycles at 100 kHz, interactions live.

### The moving head (`varimu/tape_particles/strip.py`; Rust `strip.rs`, GPU `head.wgsl`)

The Preisach medium's geometry with its Preisach cells replaced by particles, so that the
two models differ only in the particles:
- **No. 21's machine** (scripts/tape_switching_study.py's `no21_spec`): 15 ips, 70 kHz bias,
  the Ampex 300's 51 um record gap, 3 mm poles relaxing over 3 mm, a 6.35 um repro gap,
  0.5 um spacing, the 12.7 um coating in 6 layers, cells of 1/7.62 bias wavelength
  (0.714 um), the same small signal (0.05 x SCOTCH111@3's Hc median, 999 A/m deep-gap peak)
  and the same bias grid in units of that Hc.
- **Every cell holds the same particle sample** (512 particles of the `none` fit; the
  variation with the sample is in "Convergence") and sees the head's field (Hx, Hy of
  `head_field`) at its height while it is within the zone where the head can switch a
  particle (60 Oe at the peak field), 16 steps per bias cycle, then the free field. The
  particles switch by the master equation (the expectation over thermal histories), so the
  antithetic +-signal difference has no Monte Carlo noise.
- **The readback** is `tone_harmonics`' (each layer's M_x and M_y through the repro head's
  Hx and Hy spectra, the fundamental over whole wavelengths).
- **The coating's field**, three ways:
  - `nodemag`: none (every cell independent). The Preisach medium run the same way
    (`demag_iterations=0`) is the like-for-like comparison.
  - `demag`: the Preisach medium's fixed point (each cell sees the final pattern's field,
    with the head's image during its pass, free after; Anderson as
    `record_demagnetized_vector`). **With particles it doesn't converge:** a period-2 limit
    cycle (the 15 kHz output alternating -35.8 / -39.1 dB after 27 damped iterations, rms
    change 0.11 of saturation, not falling; Anderson the same). A cell's response to a
    steady field is a sum of SW steps, far steeper than the Preisach tables' smooth one, and
    the M_y part of the field (the coating's perpendicular demagnetization, N ~ 1 at long
    wavelengths) feeds it back hard. The approximation (a cell seeing a pattern recorded
    after it) is what fails, so:
  - `causal`: every cell steps in absolute time (dt = ds / 2v, cell c entering the zone at
    step 2c), and every 4 steps the cells' present (M_x, M_y) give the field on all of them
    (imaged for the cells in the zone, free for the rest), with the Preisach medium's kernels
    and wavelength cut (> 3 bias wavelengths). `causal_full`: the whole pattern's field.

## Parameters and what was fitted to what

| Value | Used | Source |
|---|---|---|
| Ms_p | 360 kA/m | research 1.2 (74 emu/g x 4.86 g/cm^3) |
| packing | 0.35 | research 1.5 (0.28-0.40); SCOTCH111@3's noise block |
| needle length, aspect | 0.5 um median, 5:1 | research 1.3 (Westmijze 1956's micrograph) |
| length log spread | 0.3 (volume 0.9) | research 1.3, provisional (0.3-0.5) |
| orientation | isotropic in 3D | research 1.5 (#111 predates orientation), provisional |
| K V_act / kT median | 150 | research 1.6 (no period value; bracket 60-2000), provisional |
| f0, T | 1e9 Hz, 293 K | research 1.6 |
| softening, contact | 0.05 um, 0.8 width | provisional (half the end face; needles touching) |
| **H_K median, log spread** | fitted | **No. 20 + Eilers' Hc** |
| **interaction strength** | fitted (`interaction_scale`, the share of the dipolar field of Ms_p at that packing) | **No. 20 + Eilers' Hc** |

Fitted on the bench (N = 2000, 60 Hz meter: 32 steps a cycle for No. 20's loops, each loop
and its mirror on the same erased state; a 1000 Oe loop at 160 steps a cycle for Hc; a grid
then Nelder-Mead; `scripts/tape_particle_bench.py --parts fit`):

| variant | H_K median | log spread | interactions | No. 20 rms (reading errors) | Hc (270 +-10%) | saturation remanence | evaluations |
|---|---|---|---|---|---|---|---|
| dynamic | 726 Oe | 0.224 | 0.110 of physical | 0.87 | 255 Oe | 0.544 | 81 (17 min) |
| frozen | 669 Oe | 0.247 | 0.188 | 0.72 | 244 Oe | 0.507 | 81 |
| none | 705 Oe | 0.226 | - | 0.72 | 262 Oe | 0.508 | 48 |
| SCOTCH111@3 (Preisach) | Hc median 251 Oe | 0.283 | sigma_Hi 64 Oe | 0.57 | 279 Oe | 0.872 (x component) | - |

Nothing was fitted to No. 21 except, as for the Preisach model, its one bias scale (the
Ampex 300's unprinted field per mA) and an offset per curve.

What the static fit says on its own:
- **The physical dipolar interactions are ~9x too strong for No. 20.** At their full strength
  (packing 0.35, Ms_p 360 kA/m, needles as end charges) the interaction field on a needle is
  ~150-200 Oe rms per component, and the remanence curve rises from 2% of saturation at
  100 Oe to 87% at 900 Oe, far wider than No. 20's (0.5% to 100%). The best fit with them at
  0.6 of that is 4.4 reading errors; the fit takes them to 0.11. Either the period oxide's
  near fields are much weaker than point end charges (porous, polycrystalline needles,
  flux closure in chains and clumps: research 1.3, 4) or the coating is far less dense in
  contact than random packing: the static data can't say which, and the bench's question has
  to be asked at both strengths (below).
- **No. 20 can't tell interactions from a switching-field spread:** all three variants fit it
  within a reading error, with the same H_K (~700 Oe) and spread (0.22-0.25).
- **An unfitted check passes:** the saturation remanence of a random 3D SW ensemble is 0.5
  (0.51-0.54 here with interactions), so Mr = 0.35 x 360 kA/m x 0.51-0.54 = 64-69 kA/m:
  No. 20's top (62.7 kA/m over 12.7 um) and Eilers' 900 G (71.6 kA/m) bracket it.
- The effective H_K (~700 Oe) is 0.35 of the ideal coherent field of a 5:1 needle (research
  1.4: ~2000 Oe), the incoherence reduction the research expects (0.13-0.4).

## The validation ladder

Plots in `reports/tape/particles/` (`scripts/tape_particle_validate.py`,
`tape_particle_bench.py`, `tape_particle_no21.py`); tests in `tests/test_tape_particles.py`
(12, ~30 s).

**1. One SW particle** (`sw_validation.png`): the switching field against the astroid
within 0.36% (the grid's early switch, at angles near 90 degrees); the barrier along the
axis 1/2 (1 - h)^2 within 1e-7; athermal loops at 10 / 45 degrees on the analytic minimum
within 3e-5 / 3e-4 of saturation (at 80 degrees 0.04, at the jump only); thermal
activation (master equation, f0 1e9 Hz) on Sharrock's law with n = 1/2 at 60 Hz and 70 kHz
over K V / kT 40-4000 (the switching field 0.47 / 0.66 of H_K at 40, 0.95 / 0.97 at 4000).
A random 3D ensemble's saturation remanence is 0.5 (tested).

**The three implementations agree** (tests): the interaction field Rust f64 against Python
to 1e-9 of its largest value and the GPU's f32 to 5e-4 (sums of near fields that cancel);
a short loop's trace Rust against Python within 0.03 and the GPU within 0.07 of saturation
(kinetic Monte Carlo diverges once one near-threshold decision differs: the check is on the
box's magnetization, not per particle); the moving head's pass Rust f64 against numpy to
1e-6 and the GPU's f32 to 9e-5 of saturation.

**2. The static fit** (`bench.png`, left; "Parameters" above): No. 20 within 0.72-0.87
reading errors (Preisach 0.57), Hc 244-262 Oe against 270 +-10%, for all three interaction
variants. No. 22 is not used: its four panels carry no type labels and its B includes H
over an unstated area (research 1.1); TAPE_PLAN.md TM1 dropped it too.

**3. The anhysteretic remanence** (the bench, `bench_arm.json`: a 70 kHz AC field decaying
from 1500 Oe over 40 cycles on a steady field along the tape, the field then removed;
normalized to the particles' saturation): the non-interacting particles' ARM is a step (51%
of saturation by 20 Oe: the ideal anhysteretic of switching particles, thermal activation
at the bias rate the only rounding), the fitted dynamic interactions (0.11 of physical)
round it to ~40 Oe, and SCOTCH111@3's Preisach ensemble rises over ~100 Oe (its sigma_Hi,
64 Oe). In the bench a sample's perpendicular demagnetization acts on M_y only; along the
tape the ARM's slope is the interactions' alone. So the static fit, which can't tell
interactions from a switching-field spread, leaves the anhysteretic susceptibility
(the recording's small-signal transfer, research 2.1: "strength and sign of interparticle
interactions largely determine" it) undetermined: the Preisach model fixes it by its
sigma_Hi, the particles by their interaction strength, both from the same No. 20. The
3%-over-1% knee from these curves is not meaningful (a 10-point ARM of a step); not
reported.

**4a. The bench's bias curves (the decisive question)** (`bench.png`, `bench_curves.json`):
every particle of a 2000-needle box sees the field a particle at one of 3 depths of the
coating sees passing the 51 um gap at 15 ips (Hx, Hy, 70 kHz bias, 16 steps a cycle, a
20 Oe DC signal), the remanence along the tape read with the 1 kHz depth weights, 3 seeds
(seed-to-seed error <= 2% near the peak, up to 15% far over-bias). SCOTCH111@3's vector
Preisach on the same histories (with the perpendicular demagnetization N_y = 1 solved
self-consistently). Widths in dB of bias from each curve's peak:

| | rise to -3 dB | rise to -10 dB | rise to -20 dB | over-bias fall to -3 dB | -10 dB |
|---|---|---|---|---|---|
| No. 21, 1 kHz (for scale; includes the head's and the coating's depth effects) | 2.95 | 5.66 | 9.39 | 2.36 | - |
| Preisach (SCOTCH111@3) | 2.61 | 5.05 | 7.08 | 4.76 | 9.85 |
| particles, no interactions | 2.62 | 5.20 | 7.44 | 2.35 | 5.30 |
| particles, dynamic interactions (fitted, 0.11) | 2.73 | 5.04 | 6.94 | 2.34 | 5.22 |
| particles, frozen interactions (fitted, 0.19) | 2.22 | 4.75 | 7.34 | 3.94 | 7.21 |
| particles, dynamic at 0.6 of physical (not fitted: No. 20 rms 4.4) | 2.38 | 4.75 | 7.05 | 2.90 | 6.10 |

**The answer to the research's question: no.** At the strength the static data allow,
dynamic interactions don't widen the bias curve's rise: -10 dB is reached 5.04 dB of bias
below the peak against the non-interacting 5.20 and the Preisach model's 5.05; at -20 dB
6.94 against 7.44 and 7.08. No. 21 needs ~2 dB more at -20 dB (9.39). Interactions held
static (frozen) don't either. Nor do strong ones: at 0.6 of the physical strength (a poor static fit, 4.4 reading errors) -20 dB is 7.05 dB below the peak. Interactions narrow the rise slightly if anything; the bias curve's width in this geometry is set by the switching-field distribution and the head's field profile, as the research's freezing picture says (2.1).

What the particles do differently is the **over-bias fall**: Stoner-Wohlfarth switching in
the head's rotating field (the astroid: a field at 45 degrees switches at half the field
along the axis) keeps re-recording particles downstream of the gap, where signal and bias
fall together, and the remanence falls 3 dB within 2.35 dB of bias past the peak against
the Preisach ensemble's 4.76 (No. 21: 2.36). The Preisach model's vector form drives each
axis by the field's projection on it, which has no astroid; its over-bias fall in the full
medium comes from the head's image instead (TAPE_PLAN.md TM2 step 7).

**One caveat on the bench's interactions:** the dynamic variant's `interaction_scale`
scales the sample's perpendicular demagnetization with the near fields (0.11 of -M_y); the
full -M_y applied explicitly a step late is unstable (the "mean" variant: the box's M_y
flips every step, every remanence 0: the feedback's gain is Ms_coat / H_K ~ 2). The moving
head below solves it implicitly.

## Convergence

TBD

## Runtime

TBD

## Verdict

TBD
