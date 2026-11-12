# Methodology review: the engine, the models, the fits

2026-11-12. A review of how we simulate analog devices (circuitsim, the tube synth, the tape,
the 670), looking for better methods. Three small experiments were run; nothing in the engine
or any circuit changed. This doc is meant to be worked by a model that has not seen the
review: each work package says what to build, where, and when it is done.

The reading and the experiments ran on Fable 5.2; the write-up on Opus 5.5.

## What not to redo

The project has already measured and rejected many of the obvious levers. Before starting a
package, check that it is not one of these (sources in brackets):

- **Linear algebra:** Woodbury low-rank refactors (slower: 15.5-20 us vs 13 per step, stale
  matrix, thousands of exact retries); iterative refinement (no help in M2, diverged in M5);
  a left-looking 4-update LU, AVX2 or FMA on the kernel, global `x86-64-v3`, fat LTO (no
  gain); `target-cpu=native` (breaks bit identity with Python). [CIRCUIT_SIM_PLAN.md M5, M8]
- **Newton:** looser reuse thresholds (already at the optimum); a current-based convergence
  test (diverges, or 1.5%); draft Newton 3e-3 (-38 dB). [CIRCUIT_SIM_PLAN.md "Draft quality"]
- **Integration:** trapezoidal for production (needs 8-16x), trbdf2 / sdirk3 / radau3 (beaten
  at equal cost), radau5 (2x the cost); error control in multi-rate parts (beats with the
  oscillator). [CIRCUIT_SIM_PLAN.md M4; TAPE_PLAN.md "Speed"]
- **Partitions:** cuts through the 670's signal path (singular DC or divergence in ~30
  samples); P2's lag coupling (no gain); spin-count tweaks; more threads on the Minimoog.
  [CIRCUIT_SIM_PLAN.md M8; TAPE_SPEED_PLAN.md P2; MINIMOOG_PLAN.md "Real time"]
- **Tape medium:** Sharrock switching, moving and static mean fields, the head's current law,
  3D axes, astroid switching (studied, not adopted), particle-level interactions.
  [TAPE_PLAN.md "Gaps", "Over-bias options"; TAPE_PARTICLES.md]
- **Parts:** capacitor DA and leakage on default panels (inaudible: -47 to -62 dB), pot end
  resistance. [DEVICE_BUILDER_PLAN.md B6]

Ideas already written down elsewhere are not repeated here: EMERGENCE_RESEARCH.md's eleven
directions, COMPONENT_DEPTH_PLAN.md's CD0-CD6, TAPE_HEAD_RESEARCH.md's exact gap field (the
leading tape lead), SYNTH_REALTIME_PLAN.md and SUITCASE_REALTIME_PLAN.md's scheduling fixes,
SYNTH_MASTER_PLAN.md's Q1-Q8.

None of these appear anywhere in the docs or code (checked by search): antiderivative
antialiasing (ADAA), wave digital filters, port-Hamiltonian formulations, Rosenbrock or
exponential integrators, transmission-line (TLM) partitioning, uncertainty or
identifiability of device fits, a perceptual error metric, SIMD across voices. GPU for
circuits was ruled out by reasoning, not by measurement.

## The experiments

Toys, not the engine. The scripts are in `scripts/methodology/`; run them from the repo root
with `uv run python scripts/methodology/NAME.py`.

### E1. The DK step matrix is sparse; DK's dense products are not (`dk_sparsity.py`)

DK precomputes dense responses of A^-1 (A = G + C/(g h)) on the ports, the states and the
probes, so each stage costs about (m + r) x r + r x m multiply-adds and each step another
(m + r) x r. That grows with the square of the states (CLAUDE.md's gotcha: the 5E3's speaker
took draft-2x from 0.48x to 1.61x real time with Newton's work unchanged). A itself is very
sparse. A sparse LU of A, built once per step size, would replace those products with two
triangular solves plus the port-current share:

| circuit | n | m | r | nnz(L+U) | dense stage | sparse stage | ratio |
|---|---|---|---|---|---|---|---|
| triode_stage | 9 | 2 | 5 | 32 | 45 | 78 | 0.6 |
| pultec_eqp1a | 98 | 10 | 56 | 592 | 4256 | 1844 | 2.3 |
| fairchild_670 | 145 | 53 | 74 | 1110 | 13320 | 8951 | 1.5 |
| fender_5e3 | 141 | 16 | 113 | 1073 | 16385 | 4210 | 3.9 |
| tube_synth | 216 | 74 | 96 | 1620 | 23424 | 15820 | 1.5 |
| minimoog_voice | 369 | 129 | 201 | 2945 | 92259 | 48460 | 1.9 |
| urei_1176 | 121 | 25 | 78 | 918 | 9984 | 4411 | 2.3 |
| neve_1073 | 100 | 18 | 76 | 669 | 8512 | 3030 | 2.8 |
| univibe | 105 | 46 | 84 | 976 | 14784 | 7932 | 1.9 |
| rhodes_suitcase_100w | 577 | 79 | 470 | 3716 | 295160 | 50803 | 5.8 |
| victorian_voice | 83 | 6 | 44 | 379 | 2464 | 1058 | 2.3 |
| telefunken_v76 | 89 | 16 | 54 | 528 | 4644 | 2176 | 2.1 |

These are counted multiply-adds, not timings. The script builds A from the IR itself, with
every device port counted and linear cores; its m and r differ a little from the engine's
(the 670: 53 / 74 here, 45 / 82 in CIRCUIT_SIM_PLAN.md), so read the ratios as indicative.
The gain is largest where the states dominate the ports: speakers, delay lines, many
transformers. It is not a gain for small circuits.

### E2. Free oversampling from the solver's stage values (`stage_sampling.py`, `stage_sampling2.py`)

An implicit Runge-Kutta step already computes the solution partway through the step.
TR-BDF2's stage lands at gamma h, gamma = 2 - sqrt(2) ~ 0.586. Two interleaved sample
streams per period can in principle reconstruct a signal band-limited to two Nyquist zones
(recurrent nonuniform sampling). So the stage values were used as extra output samples, a
2x stream was rebuilt by a least-squares interpolator (32 taps per stream), and that stream
was decimated. The test was a diode clipper driven hard at 2902 Hz, with inharmonic power
measured re the harmonics (lower is better):

| step rate | end points (1x) | + stage values (no extra solves) | + stage values and slopes | a real 2x run | a real 4x run |
|---|---|---|---|---|---|
| 48 kHz | -16.3 dB | **-29.1 dB** | -20.2 dB | -32.5 dB | -51.7 dB |
| 96 kHz | -32.5 dB | **-42.8 dB** | -33.6 dB | -51.7 dB | -74.9 dB |

The stage values buy 10-13 dB, most of a 2x run's gain at 48 kHz and about half of it at
96 kHz, for an interpolation filter. Adding the slopes (v' is known at every stage) made it
worse: asking for four zones from two sampling positions is ill-conditioned when the signal
is not band-limited. One circuit only.

### E3. Partition cuts as transmission lines (`tlm_cut.py`)

Today a partition couples parts with one sample of latency, the other side's value held or
extrapolated. That is explicit, so it is only stable across stiff, capacitor-held nodes,
and cuts through the signal path diverge (CLAUDE.md, "The draft quality").

Power-system real-time simulators cut at a reactive element instead, replaced by a lossless
transmission line whose delay is one step. This is the TLM link-line idea; the latency
insertion method is a close relative (as recalled; check the literature). A shunt
capacitance C at a node becomes a line between the node's two copies, Z0 = T / C. Each side
sees a resistor Z0 to a source of twice the incident wave, and the waves are exchanged once
per sample. A passive line cannot add energy, so the coupling is stable whatever the
circuit. The price is a parasitic dual element (inductance T^2 / C), so the error grows as
the node's own time constant falls toward a sample.

The toy is a source through R1 into a node with C to ground, loaded by R2, cut at the node.
The error of the node's response is given re the one solve with the same integrator, in dB
at 100 Hz / 1 kHz / 10 kHz:

| case | tau (samples) | hold | extrapolate | line |
|---|---|---|---|---|
| driving side stiff (100 ohm / 10k) | 0.3 | unstable | unstable | -80 / -57 / -18 |
| | 1 | -44 / -24 / +2.5 | unstable | -90 / -59 / -20 |
| | 10 | -44 / -24 / -7 | -75 / -37 / -10 | -99 / -61 / -36 |
| | 1000 | -49 / -30 / -9 | -50 / -30 / -9 | -116 / -96 / -76 |
| loading side stiff (10k / 100 ohm) | 0.3 | -50 / -30 / -10 | -50 / -30 / -10 | -40 / -20 / +1.6 |
| | 10 | -50 / -30 / -9 | -50 / -30 / -9 | -70 / -51 / -35 |
| | 1000 | -50 / -30 / -9 | -50 / -30 / -9 | -116 / -96 / -76 |
| matched (10k / 10k) | any | -50 to -56 / -30 to -36 / -5 to -9 | (unstable at 0.3) | roundoff (-280 or lower) |

The line is never unstable, and from ~10 samples of time constant up it is 20-60 dB better
than today's coupling. It is poor only on a fast node whose load is the stiff side. The
matched case agreeing to roundoff is suspicious; it may be an exact equivalence of the link
line with trapezoidal in a symmetric circuit, or a bug in the toy. Settle that first.

**Settled (2026-11-12, W1 step 1): the matched case is an exact equivalence, and the table's
line column is optimistic.** A link line driven alike at both ends (its even mode) is two open
stubs of delay T / 2, each exactly a trapezoidal C / 2; driven in antiphase (its odd mode) it is
two shorted stubs, the parasitic inductance. The toy reported the mean of the two copies,
(va + vb) / 2, which is the even mode alone when R1 = R2: hence roundoff. The mean hides the odd
mode in every case. Measured on each part's own copy (what its elements see;
`scripts/methodology/tlm_cut2.py`), the line has a floor of about (w T / 2)^2 relative to the cut
node's own response: -99 / -59 / -19 dB at 100 Hz / 1 kHz / 10 kHz at 96 kHz, whatever the
time constant (not -116 / -96 / -76). It still beats hold and extrapolate by 30-50 dB from
~10 samples of time constant up, stays stable with a diode on either side, and a series-L cut
is its dual (the same numbers).

**Where it applies.** A line replaces a node's shunt capacitance (a filter capacitor, a
timing capacitor, a rail, a node with a stated stray), or a series inductance (Z0 = L / T: a
choke, a transformer's leakage inductance). It does **not** replace a series coupling
capacitor between two nodes. Each side then sees Z0 into a source, so each part's own DC
solve has a path where today's cut leaves none (the 6973 grid case). A transformer's leakage
inductance as the cut is the case worth testing first. It would separate primary and
secondary sides, which today cannot be split.

## Work packages

Each package is opt-in and leaves every existing build, IR and render as it is.
circuitsim edits don't move the render cache key (CLAUDE.md, "Rust-only engine changes"),
so measure against fresh renders.

### W1. Transmission-line cuts (from E3) — highest value

1. Resolve E3's matched-case result: derive the link line against trapezoidal on paper, or
   find the toy's bug.
2. Extend the toy to a series inductance cut (Z0 = L / T) and to a nonlinear load (a diode on
   one side) to see that stability holds with devices.
3. In `crates/circuitsim/src/partition.rs`, add a coupling kind beside `Hold` / `Extrapolate`
   for a cut named by an element, not a node:
   - a capacitor to ground (or to a node both parts hold);
   - an inductor, including a transformer's leakage element.

   The element is removed and each part gets a resistor Z0 and a source. The sources' values
   are exchanged at the per-sample barrier the partitions already have. Name it in the
   partition settings: `coupling: line` and `cut: [ELEMENT]`.
4. Python reference first, `varimu/sim/` style, with a test of Rust against Python as the
   project's rule asks.

Done when:
- on the 670's existing supply cut, the line matches or beats extrapolate's -103 dB;
- a cut the project could not make before runs stable and is measured against the one solve.
  Candidates: a 670 channel at T104's leakage; the tube synth at a filter capacitor in the
  signal path.
- Report each new cut's error and the load it moved, as in TUBE_SYNTH_PLAN.md's partition
  tables.

Don't apply it to production: this is the draft's bend of "one coupled simulation", like
the existing partitions.

**Status (2026-11-12): built, the done-when met; on the amps it doesn't buy what was hoped.**

- **The engine.** A partition list's `cut:ELEMENT` entry (circuitsim `partition::LineCut`,
  `partition::cuts`; stream.rs `Feed::Line`): a capacitor to ground at a node two parts have,
  or an inductor (not coupled) between nodes of two parts. The element is removed; each part
  gets a resistor Z0 into a source `VLINE_<element>`, the waves exchanged at the per-sample
  barrier (a part's source runs from twice the other end's wave at n - 1 to twice it at n).
  Lines mix with held / extrapolated shared nodes in one split. The DC start is the whole
  circuit's: an inductor's current, or the current through a capacitor's node from one part
  to the other (read on a copy of the circuit with the node split by a short,
  `Split::dc_meter`; `ir::Element::nodes_mut`). Opt-in: without `cut:` entries the split,
  its IRs and runs are as before (`tests/partition.rs`, `tests/stream.rs` pass).
  The app passes cuts through `Settings::partition_sections`; Python's
  `fast.partition_sections` doesn't yet (an edit there moves every render's cache key).
- **The reference** `varimu/line_cut.py` (a dense trapezoidal MNA with the same ends and
  waves; outside the render cache key). `tests/test_line_cut.py`: circuitsim's cut runs
  within 1e-9 of it, a capacitor cut and an inductor cut each with a diode, and both start at
  the whole circuit's DC point. `crates/circuitsim/tests/line_cut.rs`: what can be cut, and
  E3's hard case (tau 0.3 samples behind a stiff source) stable at -50 dB from the one solve.
- **The 670's supply cut** (`scripts/methodology/line_cut_670.py`, 3 s of the arpeggio at the
  draft): its five rails with reservoir capacitors as lines (`ur` has none and stays
  extrapolated) **-103.2 dB** from the one solve, the same as extrapolate (-103.2), CV max
  3.8 mV against 4.2 (held: -89.6 dB).
- **The amps** (draft-1x, 48 kHz; `examples/cut_error.rs`, the Dry Guitar take's heaviest 8 s
  at the panels' defaults, VOLUME 0.5):
  - *The output transformer's leakage* can't be cut at this step: its L / R is a few
    hundredths of a sample (AC30: primary 1.3 mH plate to plate, secondary 9.6 uH), so the
    line's parasitic capacitance h^2 / L (0.3 uF, 45 uF) swamps the windings: -3 / 0 / 0 dB
    in the toy (`tlm_cut2.py`, part 4).
  - *The speaker's moving mass* (`C<P>_m`, the motional node's capacitor; the mechanics moved
    to `<P> mechanics` by `varimu_circuit::speaker::mechanics_apart`) cuts cleanly and moves
    ~18 states off the amp thread. AC30, against the one solve:

    | partition | load | blocks > 1.0 | error at `out` | above 2 kHz | at `spk` |
    |---|---|---|---|---|---|
    | the device's today (readout, supply apart) | 0.79x | 145 / 800 | -35.3 dB | -28.7 | -62.7 |
    | + mechanics, the mass as a line | 0.65x | 96 / 800 | -23.8 dB | -17.1 | -46.1 |
    | + mechanics, extrapolated at the mass | 0.67x | 98 / 800 | -22.6 dB | -16.0 | -44.6 |

    The line is the more accurate of the two, but at 48 kHz its floor ((w h / 2)^2 re the cut
    node) sits on the cone's velocity, which is the output: 11 dB of accuracy for 18% of load.
    Not put in panel.rs.
  - *The worst blocks* are Newton's, at the power tubes, and no partition removes them. The
    whole take (62 s): the AC30 averages 0.70x on one amp thread but its heavy blocks run 2-4x
    (8-10 factorizations and 8 iterations a sample, "contraction" refactors); the Plexi
    averages 1.17x, 14% of its blocks over 2x, the worst 9x (40 factorizations, Newton at its
    50-iteration cap, step halvings). In those passages the plates fly back to 1.14 kV (AC30,
    a 373 V rail) and 1.48 kV (Plexi, 451 V) at the default VOLUME. The Plexi split at its
    cathode follower (held) with its mechanics apart: the power amp's thread 0.71x mean, still
    1207 of 6234 blocks over 1.0.
- Not measured: the 670 at T104's leakage, the tube synth at a filter capacitor.

### W2. A sparse-state DK (from E1)

The state update without the dense products: with A's sparse LU (pattern and factors fixed
per step size), a stage's linear part is

```text
y = E_S x_S + A^-1 (b + u e_in + sum wv_k e_k + w - G E_S x_S)
```

which is the same algebra as dk.rs's `(I - A^-1 G)` on S. Keep that form: dk.rs's header
explains why `C x/(g h)` must never be formed (DC fluxes of ~5 Wb cancel and lost 3-5
digits). Newton still needs only K = N A^-1 N^T (m x m, dense, precomputed as today) and
the port rows of y. After Newton, subtract the port currents' share from the states with the
precomputed (A^-1 N^T) on the state rows (r x m) or a second sparse solve, whichever is
cheaper for the circuit.

1. A small sparse LU in `linalg.rs`: symbolic analysis once (COLAMD- or AMD-like ordering;
   scipy's COLAMD gave the fill above), equilibration as `Lu` does, then numeric
   factorization per step size and triangular solves. No new crate dependency is needed for
   these sizes.
2. `solver: dk_sparse` beside `dk` and `mna`; pick per circuit by r against m (E1's table:
   only where it wins).
3. Measure first on the 5E3 with its speaker readout and on the Suitcase
   (`examples/load_profile.rs`, `examples/play.rs --mute`).

Done when `dk_sparse` agrees with `dk` within the Newton tolerance on the agreement fixtures,
and the 5E3's draft-2x load with the speaker readout is measured both ways. Its success
criterion: the 1.61x falls toward the 0.48x it had without the readout. That also answers
COMPONENT_EDITOR_PLAN.md C3's open question (Play's speed with the speaker), without the
one-way partition proposed there.

### W3. Stage-value oversampling (from E2)

1. Repeat E2 on the real engine at draft-1x: the 5E3's hard-clipped tone, with aliasing at
   -8 dB today (DEVICE_BUILDER_PLAN.md B9), and the tube synth's square.
2. The stage's probe values cost the probe rows of the third DK block at each stage
   (`DkSystem::unknowns` on the first `n_first` rows: a few rows), not a full solve.
3. Compare three ways of getting the in-between values:
   - the stage values directly;
   - the method's dense output (Hairer-Wanner's continuous extensions: a polynomial through
     the stage derivatives, at any point in the step);
   - for esdirk4 (production), its five stage times, which might give up to ~4x.

Done when the 5E3 at draft-1x reports its aliasing with and without the stages, at the same
cost per sample within a few percent. If it reaches draft-2x's -24 dB, draft-1x becomes an
option for the devices that dropped it for aliasing.

### W4. Fit uncertainty and fitted ranges

No fit reports anything beyond residuals; no parameter covariance or identifiability exists
anywhere. The degenerate `56@1` (Kp 1.1e7, NOVACHORD_PLAN.md) was found only because its
table took 20 s.

1. In `varimu/devices/fit.py` and `library.py`'s fitters, from the Jacobian at the optimum
   (scipy's `least_squares` returns it): the covariance (J^T J)^-1 scaled by the residual
   variance, each parameter's standard error, the correlation matrix and the condition
   number. Write them into the fit's report in `reports/devices/`, not into component files
   (versions are immutable).
2. Flag a fit whose condition number or relative standard error passes a threshold (a
   parameter the data don't determine).
3. Record each fit's data range (grid and plate volts for tubes; flux density for cores;
   current for diodes) in the same report. Add a run-time check that counts samples outside
   it per device. This is EMERGENCE_RESEARCH.md's rule 2 ("inside the model's validity?"),
   proposed there and not built.

Done when every device fit in `fit-devices` writes its standard errors and range, and one
render of the 5E3 driven hard reports which devices left their range and for how long.

### W5. A masked error metric for numerics decisions

Draft settings are chosen by rms error in dB re the signal (-45 dB, -52 dB). Rms doesn't say
where the error sits: draft-1x's top octave is up to 0.7 dB off, which rms barely counts.

Add a noise-to-mask ratio: the error's spectrum per critical band against a masking
threshold computed from the reference signal. Use a published model, PEAQ's NMR
(ITU-R BS.1387) or Zwicker's spreading, cited as `source` in the code; don't invent
psychoacoustics. Report the worst and mean NMR beside rms in
`scripts/draft_settings_study.py`.

Done when the draft study's existing rows show NMR beside rms, and at least one setting
ranks differently by NMR than by rms (or the doc says none did).

### W6. Tape: is the Preisach density separable?

The tape's density is a product, mu = f(Hc) g(Hi) / 2 (preisach.py): the interaction spread
is the same at every coercivity. Published FORC diagrams of particulate recording media
usually show the interaction spread varying with coercivity (as recalled; check the
literature). Such a density need not be a product, and that changes how the ensemble
responds across bias levels, which is where the model misses No. 21 (~2.3 dB of bias
narrow, TAPE_PLAN.md step 7).

1. Search for a FORC diagram (or Henkel / delta-M data) of an acicular gamma-Fe2O3 audio
   tape of #111's era, or the closest modern equivalent.
2. A variant in `varimu/tape_variants.py`'s style: sigma_Hi = sigma_0 (Hc / Hc_median)^p.
   Refit No. 20 + Hc for each p in a small set, then run No. 21 and the knee, as the
   over-bias study did.

Done when the variant's table row exists beside TAPE_PLAN.md's "Over-bias options", with
the source (or the absence) of FORC data stated. It doesn't compete with the exact gap field
lead (TAPE_HEAD_RESEARCH.md); run it after, or alongside if the field is blocked.

### W7. SIMD across identical voices

A polyphonic tube synth's voices are one circuit repeated. Today they run as a partition per
voice or as one solve at ~16x a voice (SYNTH_MASTER_PLAN.md). With identical component values
(nominal units), the DK matrices are shared. Stepping 4 voices in AVX2 lanes turns every
`gemv` into a matrix times four vectors. That is far better arithmetic intensity than the
latency-bound 22 x 22 solves (CIRCUIT_SIM_PLAN.md: "loop overhead" bound). Voices whose
Newton has converged are masked.

Done when a 4-voice bench (`examples/voice_bench.rs`) runs 4 voices in lanes against 4
voices on threads, both measured.

The lanes stop sharing matrices once per-voice tolerance draws (SYNTH_IDEAS #17) differ.
Say so in the result.

## Research ideas (nothing built; novelty hedged, a short search only)

- **Stage-sampled output as antialiasing for implicit solvers.** E2 suggests the intermediate
  stages of an implicit RK method are worth 10-13 dB of aliasing for free. RK dense output is
  textbook; using it as recurrent nonuniform samples for a band-limited audio reconstruction
  was not found in a short search. A proper search, and W3, come first.
- **Partitions chosen by the circuit.** With W1, any shunt capacitance or series inductance
  is a candidate cut, and E3's table says roughly what each costs in accuracy (from the node's
  time constant and which side is stiff). Choosing cuts becomes a graph partitioning problem:
  balance the threads' loads subject to a predicted error bound. Today the partitions are
  chosen by hand, section by section.
- **Numerics judged by audibility.** W5's metric, applied to EMERGENCE_RESEARCH.md's rule 1
  ("physics or numerics?"): an effect is numerical if it moves with the step or the method,
  and inaudible if its NMR stays below 0 dB. Together these give each live quality a stated,
  checkable audibility budget instead of an rms number.

## Order

W1 first: it attacks the real-time limit every live device hits, and its toy result is the
strongest. Then W2, which matters for the 5E3 / Suitcase class. W4 and W5 are cheap, Python
only, and can run alongside. W3, W6 and W7 come after, each a measurement before any
adoption.
