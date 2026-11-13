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

**Verdict, short (the end has it in full): no, not as it stands.**
- **The decisive bench says no.** Interacting Stoner-Wohlfarth needles fitted to No. 20 +
  Hc record over the same range of bias as the Preisach ensemble: the rise to -20 dB spans
  6.9-7.4 dB of bias in every interaction variant (none, dynamic, frozen, strong), the
  Preisach ensemble 7.1, No. 21 9.4. Dynamic interactions don't widen it.
- **The particles differ in the over-bias fall.** It takes 2.35 dB of bias to fall 3 dB
  past the peak against the Preisach ensemble's 4.76 (No. 21: 2.36). The cause is SW
  switching in the head's rotating field, which the vector Preisach model's projections
  lack.
- **The blind prediction of No. 21 on the moving head is not better than the Preisach
  medium's:**
  - the physical, converged configuration (the coating's perpendicular self-field solved
    implicitly) scores rms 3.5 / 2.5 dB against 2.25 / 1.74;
  - the configuration that reproduces the treble's loss with bias (no coating field) does
    it with an unphysical perpendicular remanence;
  - the full coating field doesn't converge with particles.
- **What it points at:** the cheap model's missing astroid, a calibration target, not a
  replacement.
- **A stretch that did predict something:** print-through's time law, 3.6-4.2 dB per decade
  of storage over the whole bracket of barriers, against Manly's 3.45, nothing fitted; its
  level rests on the unknown K V_act / kT.

**Reproducing it** (the GPU binary first: `cargo build --release -p tapeparticles`;
`$TPSIM_TARGET_DIR` points `varimu/tape_particles/runner.py` at another target directory):

    uv run python scripts/tape_particle_validate.py                       # rung 1
    uv run python scripts/tape_particle_bench.py --parts fit --variants dynamic frozen none
    uv run python scripts/tape_particle_bench.py --parts curves arm plot \
        --variants none dynamic frozen dynamic_strong                     # rungs 2-4a
    uv run --extra fast python scripts/tape_particle_no21.py --configs nodemag --n 1024 \
        --seeds 1 2 3 --tag _1024x3                                                     # rung 4b
    uv run python scripts/tape_particle_no21.py --configs local --n 256 --seeds 1 2 3 4 \
        --tag _4s --parts particles plot
    uv run python scripts/tape_particle_print.py                          # rung 5
    uv run pytest tests/test_tape_particles.py                            # ~2 min

-> `reports/tape/particles/`. Packed boxes are cached in `cache/tape_particles/packs/`.

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
- **Every cell of a run holds the same particle sample** of the `none` fit, and a reported
  curve averages several runs' complex fundamentals, each a different sample (as along a
  real tape the cells hold different particles): 3 x 1024 without a coating field, 4 x 256
  with it ("Convergence" says why). A cell sees the head's field (Hx, Hy of `head_field`) at
  its height while it is within the zone where the head can switch a particle (60 Oe at the
  peak field), 16 steps per bias cycle, then the free field. The particles switch by the
  master equation (the expectation over thermal histories), so the antithetic +-signal
  difference has no Monte Carlo noise.
- **The readback** is `tone_harmonics`' (each layer's M_x and M_y through the repro head's
  Hx and Hy spectra, the fundamental over whole wavelengths).
- **The coating's field**, the ways tried:
  - `nodemag`: none (every cell independent). The Preisach medium run the same way
    (`demag_iterations=0`) is the like-for-like comparison.
  - `local`: the cell's own perpendicular demagnetization, -Ms_coat M_y (the field inside
    a uniformly perpendicular layer: the coating's field's long-wavelength limit), **solved
    implicitly in each step**: the cell's M_y after the step solves M_y = F(H - Ms M_y) (F
    the particles' M_y after the step in that field; it falls as M_y rises, so bisection,
    14 halvings, a GPU workgroup per cell, `step_local`). Cells stay independent. This is
    the run that is both physical and converged.
  - `demag`: the Preisach medium's fixed point (each cell sees the final pattern's field,
    with the head's image during its pass, free after; Anderson as
    `record_demagnetized_vector`). **With particles it doesn't converge:** a period-2 limit
    cycle (the 15 kHz output alternating -35.8 / -39.1 dB after 27 damped iterations, rms
    change 0.11 of saturation, not falling; Anderson the same). A cell's response to a
    steady field is a sum of SW steps, far steeper than the Preisach tables' smooth one, and
    the M_y part of the field (N ~ 1 at long wavelengths, Ms_coat ~1580 Oe against
    switching fields ~350 Oe) feeds it back with a gain of ~2-4.
  - `causal`: every cell steps in absolute time (dt = ds / 2v, cell c entering the zone at
    step 2c), and every few steps the cells' present (M_x, M_y) give the field on all of
    them (imaged for the cells in the zone, free for the rest; the medium's kernels and
    wavelength cut). Explicit, it is unstable for the same reason ("Convergence").
  - `local_fp`: `local`, plus the rest of the coating's field (the layered kernels less the
    cell's own term) by the medium's fixed point.

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
(13, ~2 min with the GPU).

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
static (frozen) don't either. Nor do strong ones: at 0.6 of the physical strength (a
poor static fit, 4.4 reading errors) -20 dB is 7.05 dB below the peak. Interactions narrow
the rise slightly if anything; the bias curve's width in this geometry is set by the
switching-field distribution and the head's field profile, as the research's freezing
picture says (2.1). (The rows aren't like for like in one respect: the Preisach row has the
coating's perpendicular demagnetization, the particle rows none or the interactions' share
of it; the moving head below has it in full, and the widths' answer doesn't change there:
the 1 kHz rise to -20 dB of the `local` run spans no more bias than the Preisach medium's.)

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

**4b. The blind prediction: No. 21 on the moving head** (`no21.png`, `no21.json`;
`scripts/tape_particle_no21.py`). The particles are the `none` fit (SW particles, H_K
705 Oe, log spread 0.226, nothing from No. 21); each model gets No. 21's one bias scale and
an offset per curve (the switching study's protocol, reproduced: the Preisach medium's
rms 2.25 / 1.74 dB). dB re each curve's peak:

| model | bias scale (A/m per mA) | rms 1k / 15k (dB) | peaks 1k / 15k (mA) | 1k at 2 / 3 mA | 1k / 15k at 8 mA | 15k - 1k at 5 / 8 mA |
|---|---|---|---|---|---|---|
| **No. 21** (#111, Ampex 300) | - | - | 6 / 5 | -20.4 / -11.0 | -3.3 / -7.1 | -6.0 / -10.4 |
| Preisach medium, demag + image (SCOTCH111@3; the switching study's base) | 6694 | 2.25 / 1.74 | 5.1 / 4.5 | -20.6 / -5.5 | -3.2 / -5.1 | -4.8 / -6.6 |
| Preisach medium, no coating field | 6963 | 2.57 / 2.15 | 4.3 / 4.3 | -18.5 / -4.5 | -3.4 / -5.1 | -0.5 / -2.2 |
| particles, no coating field (3 x 1024; the samples' own fits 1.8-2.2 / 2.3-2.7) | 7819 | 1.92 / 2.51 | 4.6 / 3.8 | -22.2 / -6.7 | -0.8 / -9.1 | -5.4 / -12.4 |
| **particles, the cell's perpendicular demagnetization (4 x 256; 2.9-4.3 / 1.9-3.5)** | 8062 | 3.54 / 2.49 | 4.5 / 4.5 | -24.4 / -7.9 | -9.2 / -8.2 | -4.3 / -2.6 |

Reading it:
- **Without a coating field** (`nodemag`) the particles already have what the Preisach
  medium needed its demagnetization for: the 15 kHz curve peaks below the 1 kHz one and
  the 15k - 1k spread grows with bias (-12.4 dB at 8 mA, No. 21 -10.4; the Preisach
  ensemble run the same way: -2.2). That is SW switching downstream of the gap, in the
  field's vertical part (Hy falls as g / (pi x), Hx as g y / (pi x^2): TAPE_PLAN.md TM2
  step 4's mechanism, here without a fitted orientation). But the 1 kHz curve doesn't fall
  past its peak (-0.8 dB at 8 mA against -3.3): the same downstream switching leaves a
  large perpendicular remanence (M_y up to 18x M_x far over-bias in the bench), which a
  coating can't keep: its own field -M_y (Ms_coat ~1580 Oe) is 2-4x the switching fields.
- **With that field** (`local`: the cell's perpendicular demagnetization, implicit) the
  prediction gets worse, not better: rms 3.54 / 2.49 dB (the Preisach medium 2.25 / 1.74),
  the 1 kHz curve falls too fast past the peak (-9.2 against -3.3 dB at 8 mA), the treble's
  loss with bias nearly gone (15k - 1k -2.6 against -10.4 at 8 mA), both peaks at 4.5 mA
  (No. 21: 6 / 5). The four samples' own fits spread 2.9-4.3 / 1.9-3.5 dB. On the 1 kHz
  curve's own bias axis: the rise to -20 dB spans 6.0 dB of bias (the Preisach medium
  without a coating field 6.9, No. 21 9.4), the fall to -3 dB 2.5 (No. 21 2.4): narrower
  below the peak, as in the bench, and right for 3 dB past it, then too steep.
- **The rest of the coating's field** (in-plane, and perpendicular beyond the cell) on top
  of the local term by the medium's fixed point (`local_fp`, 15 kHz, 2 x 256,
  `no21_fp.json`) lowers the 15 kHz output by 6-10 dB, not uniformly, and doesn't
  converge where it matters: below 2e-3 rms change of saturation up to 0.9 Hc of bias,
  0.03-0.22 at 1.2-2.6 Hc (the peak's region). Taken as it stands, with the same two
  samples' local 1 kHz curve, the fit is no better: rms 3.97 / 2.45 dB (local alone
  3.92 / 2.64), 15k - 1k -1.0 dB at 8 mA.

So the one configuration that is both physical and converged (`local`) predicts No. 21
worse than the Preisach medium does, and the configuration that matches the treble's loss
(`nodemag`) does it with an unphysical perpendicular remanence. Neither counts as a blind
success.

**5. Print-through, a stretch: a prediction of its time law** (`scripts/tape_particle_print.py`
-> `print.json`). The `none` fit's particles (40,000, two samples), AC-erased, sit in a
weak steady field H for a storage time t at 293 K, then in no field for 10 s (rewound and
played); the remanence left over H is the print susceptibility, through the next layer's
field at the print's peak wavelength (research 3.3: 307 um, 2 pi x #111's 48.8 um; the
field of a layer's M through the 36.1 um base, (1 - e^{-k delta}) e^{-k d} / 2 = 0.06 of
M). The master equation over a constant field is exact in one step of any length. Against
Manly (1977, research 3.4: -52 dB at 5 min, -40 dB after a week, 3.45 dB per decade):

| K V_act / kT median | print at 5 min | 1 day | 1 week | 1 year | dB per decade, 5 min to 1 week |
|---|---|---|---|---|---|
| 60 | -30.8 | -20.8 | -18.7 | -15.1 | 3.6 |
| **150 (the provisional value)** | **-49.9** | -38.8 | **-36.3** | -31.9 | **4.1** |
| 400 | -78.1 | -66.7 | -64.1 | -58.9 | 4.2 |

(H = 2 Oe; at 10 Oe within 1.3 dB: linear, as Manly's print is.) The **time law is a
prediction** and comes out near Manly's: 3.6-4.2 dB per decade over the whole bracket of
barriers, against 3.45, from the lognormal tail of the barrier distribution and nothing
fitted. The **level is not**: it moves ~19 dB per factor 2.5 of K V_act / kT, the least
known number of the model (research 1.6); the provisional 150 lands within 2-4 dB of
Manly's two points, which is coincidence until K V_act / kT is measured. Warmer storage, kT
alone (Ms and K held): +0.9 dB per 10 K against Manly's 1.8 (research 3.3: the rest is Ms
and K falling with temperature, not in this model). Not run: a recorded receiving layer,
the wind and the decay after separation (research 3.4's items 4-6).

## Convergence

**The bench** (0-D bias curves): steps per bias cycle and the zone's floor checked on the
Preisach curves of the same histories (16 against 32 steps: <= 0.03 dB; a 20 against a
40 Oe floor: <= 0.3 dB, far over-bias only); the particles' seed-to-seed standard error
(3 seeds of 2000 needles) <= 2% near the peak, up to 15% at -20 dB over-bias (the shading
in `bench.png`). The box (2000 needles, 3.3 um, 6.5 needle lengths) was not varied in
size; the static fit's cost has steps of single switching events (N = 2000: a reading
error is ~3 needles' worth of remanence), which is why the fit is a grid and Nelder-Mead.

**The moving head** (each change against the base; `no21.json`):

| change | 1 kHz curve, max diff | 15 kHz | 15k - 1k at 8 mA | peaks (mA) |
|---|---|---|---|---|
| base (nodemag, 512 particles, seed 1) | - | - | -15.4 | 6.01 / 4.92 |
| 32 steps a bias cycle | 0.2 dB | 0.5 | -15.9 | 6.04 / 4.95 |
| zone floor 30 Oe (60) | 0.2 | 0.8 | -16.2 | 6.04 / 4.94 |
| 12 layers (6) | 0.4 | 0.9 | -15.9 | 6.06 / 4.07 |
| 1024 particles | 1.7 | 3.2 | -12.1 | 4.67 / 3.83 |
| another 512-particle sample | 1.6 | 3.3 | -10.7 | 4.68 / 3.83 |

The numerics (steps, zone, layers) are converged to <= 0.9 dB; **the particle sample is
not**: one 512-particle sample moves the fitted curves by 1.6-3.3 dB and the fitted peaks by
1.3 mA. Every cell holds the same sample, so a sample's outliers (a few soft particles at
one orientation) act coherently along the whole strip. The reported runs average several
samples (each a different set of cells' particles, as along a real tape): `nodemag` 3 x
1024, `local` 4 x 256, with each sample's own fit shown thin in `no21.png` as the spread.
The `local` result holds with 4 other samples at 32 steps a bias cycle (`local_4s_m32`):
rms 3.74 / 3.60 dB (3.54 / 2.49), 1 kHz -8.4 at 8 mA (-9.2), 15k - 1k -2.4 at 8 mA (-2.6),
peaks 4.5 / 3.7 mA (4.5 / 4.5).

**The coating's field:**
- the Preisach medium's fixed point (each cell sees the final pattern's field) with
  particles: a period-2 limit cycle (above);
- causal (every cell in absolute time, the field from the present pattern, explicit):
  unstable when the field lags (15 kHz at 1.2 / 2.2 Hc: -36.6 / -69.8 dB updating every 8
  steps, -35.6 / -39.6 every 4, -27.5 / -35.8 every 2, -27.2 / -20.1 every step; at twice
  the steps -23.7 / -31.9): not converged in either. The cause is the coating's
  perpendicular self-demagnetization (-M_y over a layer, Ms_coat ~1580 Oe against switching
  fields ~350 Oe: an explicit step's gain ~2);
- **the cell's perpendicular demagnetization solved implicitly** (each step's M_y by
  bisection on M_y = F(H - Ms M_y)): stable by construction; the only coupling the `local`
  runs keep. The rest of the coating's field on top of it by the medium's fixed point
  (`local_fp`): converged below 2e-3 of saturation up to 0.9 Hc of bias, 0.03-0.22 at
  1.2-2.6 Hc after 12 Anderson iterations; at 2.2 Hc the residual stays at ~0.1 over
  iterations 4-12. Not converged.

## Runtime

On the RTX 3080 (Vulkan), the desktop's CPU saturated by other jobs all night (another
session's process at 100%: the CPU paths were unusable for big runs, which is why the GPU
carries everything):
- **The bench:** 2000 needles, every pair's end charges and dipole at 5 points along each
  target, ~7e10 pair evaluations per second: a step of 96 replicas ~25 ms. A static-fit
  evaluation (erase, 34 loops of 80 steps, the coercivity loop) 7-30 s, a variant's fit
  7-17 min; the bias curves (16 biases x 3 depths x +-signal, 4122 steps) ~110 s per seed.
- **The moving head:** a tone at one bias, every cell of the strip (1 kHz: 533 cells x 6
  layers x 2 signs, 1024 particles each, ~2400 steps) 1-14 s without demagnetization; with
  the cell's perpendicular demagnetization solved implicitly (14 bisections a step, 256
  particles a cell) 2-13 s; a whole No. 21 run (2 frequencies x 16 biases) 2-10 min per
  particle sample.
- The Preisach medium's tone on the same machine: ~1 s (circuitsim's kernel, no demag).

## Verdict

**Is it a trustworthy bench? Not yet, and not for No. 21's width.**

1. **The decisive bench says no to the hoped-for mechanism.** Interacting Stoner-Wohlfarth
   needles fitted to the same static data as the Preisach model don't record over a wider
   range of bias: the rise to -20 dB spans 6.9-7.4 dB of bias for every interaction variant
   (none, dynamic, frozen, and dynamic at 0.6 of physical strength) against the Preisach
   ensemble's 7.1 and No. 21's 9.4. Dynamic interactions (neighbours flipping with the
   bias) were the research's best candidate for the ~2-3 dB the Preisach model lacks; at the
   strength No. 20 allows (0.11 of the point-charge estimate) they change the rise by
   < 0.3 dB, and stronger ones narrow it. By the research's own criterion the misfit of the
   rise is not the particles' and the next suspect is the head (its field against current
   and depth, provisional: TAPE_PLAN.md item 4).
2. **The particles do differ from Preisach, in the over-bias fall, and that difference
   comes from physics the Preisach model lacks: Stoner-Wohlfarth switching under the head's
   rotating field.** In the bench the remanence falls 3 dB within 2.35 dB of bias past the
   peak (No. 21's 1 kHz: 2.36; Preisach 4.76), with no fitting to No. 21; in the moving
   head the 15 kHz curve's peak sits below the 1 kHz one and the 15k - 1k spread grows with
   bias without any coating field. But:
3. **The blind prediction of No. 21 on the moving head is not better than the Preisach
   medium's.** With no coating field, M_y (a 3D-random coating's perpendicular remanence)
   is unopposed and the 1 kHz curve doesn't fall past its peak (-0.8 dB at 8 mA against
   -3.3), though the 15k - 1k spread comes out near No. 21's (-12.4 against -10.4). With
   the cell's own perpendicular demagnetization solved implicitly (`local`, the physical
   and converged configuration) the prediction is worse than the Preisach medium's: rms
   3.54 / 2.49 against 2.25 / 1.74 dB, the 1 kHz curve falling too fast past the peak
   (-9.2 dB at 8 mA), the treble's loss with bias nearly gone (15k - 1k -2.6 against
   -10.4). The rest of the coating's field doesn't converge with particles in any scheme
   tried (the medium's fixed point: a limit cycle, or a residual ~0.1 of saturation at
   2.2 Hc on top of the local term; the explicit causal coupling: unstable), so the 15 kHz
   curve, where the coating's field matters most, is open.
4. **And the static data underdetermine the particles.** No. 20 + Hc fit all interaction
   strengths equally (0.72-0.87 reading errors), while the anhysteretic susceptibility
   (the recording's small-signal transfer) depends on that strength by an order of
   magnitude (a step without interactions, ~40 Oe wide at the fitted 0.11, ~100 Oe in the
   Preisach ensemble). A bench whose answer depends on a parameter its calibration data
   can't fix is not trustworthy by itself; Bulletin 22's loops can't fix it either (no type
   labels).

**What it would calibrate in the cheap model, once its coating field converges:** the
vector Preisach model's switching rule. The Mayergoyz form (each easy axis driven by the
field's projection on it) has no astroid; the particles say the over-bias fall and the
treble's loss with bias depend on switching under rotating fields. A cheap fix to test:
each orientation's hysterons switching at the astroid's field for the angle between the
field and their axis (h_sw(psi) = (cos^{2/3} + sin^{2/3})^{-3/2}), which the medium's
kernel can tabulate per (orientation, field angle) at no cost per sample. The bench gives
its target curves (`bench_curves.json`), the static fit its switching distribution.
(Tested since, opt-in: TAPE_PLAN.md's "Over-bias options" and its "second round" status
block, 2026-11-12. The astroid moves No. 21 the right way; its 15 kHz overshoot goes with the
orientation, gone for unoriented 3D axes, which then distort at low level on the 51 um gap.
Not adopted.)

**What would make it trustworthy:** (a) the coating's field converged with particles: an
implicit (per-step self-consistent) solve of the whole layered field, not only the cell's
own perpendicular part; the GPU kernel already solves the local part by bisection per
step; (b) a second static constraint on the interaction strength: a measured anhysteretic
or Henkel (delta-M) curve of a period oxide; (c) the head: No. 21's bias axis is the
Ampex 300's unprinted field per mA, and the research's freezing picture puts the rise's
width in the head's field profile and depth, which both models share.

## Unfinished and not done

- **The 3% THD level** (Sound Talk No. 1): not run (the moving head isn't converged in the
  coating's field, and the knee depends on the anhysteretic susceptibility, which the
  static fit leaves open; above).
- Print-through as a model (research 3.4's linear condition dial) is not built; above is
  only its time law from the particles.
- `varimu/tape_particles/medium.py` / Rust `medium.rs` (a CPU strip with a cell FFT and a
  quenched local field) is written but unused: the CPU was saturated by other jobs all
  night; the GPU strip (`strip.py`) replaced it.
