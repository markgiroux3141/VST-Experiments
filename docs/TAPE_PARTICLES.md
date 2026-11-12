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

### The moving head (`varimu/tape_particles/medium.py`; Rust `medium.rs`)

TBD

## Parameters and what was fitted to what

TBD

## The validation ladder

TBD

## Convergence

TBD

## Runtime

TBD

## Verdict

TBD
