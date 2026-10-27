# Fast Circuit Simulator: Plan

A purpose-built nonlinear audio circuit simulator in Rust, in its own crate in
this repo (`crates/circuitsim`). It takes a netlist and produces audio and
internal signals, like ngspice does for the Vari-Mu project today, but 10-100x
faster. It is general by design: any circuit built from devices it has models
for (the 670, tube EQs, preamps, other compressors), not code written for one
unit.

Decided 2026-10-13, after the first end-to-end 670 slice (see
`reports/slice/` and CLAUDE.md). This pulls part of the main plan's Phase 10,
option B (a nodal DK implementation), forward, because render speed is now the
bottleneck for tweak-and-listen and will be for Phases 5-8.

## Why

Measured on the 670 slice (one channel, ngspice 47, 2x oversampling):

- A render runs **25-40x slower than real time**. A 4 s clip takes about 2
  minutes.
- **Python is about 2%** of that (1.7 s of input file writing, 0.3 s
  everything else). Rewriting Python would gain nothing.
- **Inside ngspice, about 70% is device evaluation**, about 10% the matrix
  solve, and the rest is time-step control and overhead. ngspice is
  general-purpose: it interprets behavioral expressions, goes through the
  XSPICE plugin layer for tables, adapts its time step, and solves Newton
  iterations over every node (about 3.4 per time point).

A dedicated engine for a fixed circuit can:

- evaluate compiled analytic device models (the 32-section 6386 is cheap in
  compiled code, so no tables are needed);
- run at a fixed step equal to the oversampled audio rate, so there's no
  interpolation onto a grid;
- run Newton only on the nonlinear device ports, about 20-25 unknowns for the
  670, not about 100 nodes, using the nodal DK method below.

## Goals

1. **General:** netlist in, signals out. Adding a circuit means writing a
   netlist; adding a device kind means writing a model plus tests.
2. **Correct:** agrees with ngspice on every circuit we use, by a stated
   tolerance, with tests. ngspice stays the reference engine.
3. **Fast:** the 670 slice at least 10x faster than ngspice offline (target:
   near real time on one core). Simpler circuits (a tube EQ) faster still.
4. **Plugin-ready later:** allocation-free per-sample processing and
   control-rate parameter changes, so the same engine can sit in a VST
   (main plan, Phase 10).

## Non-goals (for now)

- SPICE compatibility beyond what our netlists use. No `.include` libraries
  of vendor models, no AC/noise/pole-zero analyses. Those stay in ngspice.
- Arbitrary analog circuits at RF or with thousands of nonlinear devices.
- Replacing the measurement suite, cache or listen app. They stay in Python
  and gain an `engine` setting.

## How it relates to the main plan's rules

- **Two implementations:** every device model already has a Python reference
  and a SPICE version. The Rust version becomes a third, tested against the
  Python reference on the same point grids. Whole circuits are tested Rust
  vs ngspice.
- **One coupled simulation:** unchanged. The engine solves the whole netlist
  at once. The DK reduction is exact algebra on the same equations, not a
  split into blocks.
- **The genome is physical only:** unchanged. An EQ would be another
  simulated unit with its own netlist and sourced values, never an EQ knob on
  the compressor.
- **Reproducibility:** the cache key gains the engine name and a hash of the
  crate sources.

## Architecture

```
 varimu (Python)                                crates/circuitsim (Rust)
 ───────────────                                ────────────────────────
 config/circuits/*.yaml                         ir      netlist types (serde)
        │                                       mna     element stamps
 varimu/circuit/netlist.py                      dk      state-space reduction
        │  builds                               device  model trait + library
        ▼                                       newton  nonlinear solve
   Circuit IR (JSON) ──┬── emit SPICE text ──▶ ngspice (reference engine)
                       └── circuitsim (PyO3) ─▶ fast engine
                                │
 varimu/sim/runner.py ◀─────────┘  same Render objects, cache, timing log
```

### One circuit description, two engines

Today `netlist.py` writes SPICE text directly. It changes to build a typed
**circuit IR** first: nodes, elements with values, device instances with
model parameters, inputs and probes. The IR goes to two emitters, the
existing SPICE text (ngspice) and JSON for the Rust engine. Both engines then
always simulate the same circuit, and the agreement tests mean something.

IR element kinds, initially: resistor, capacitor, inductor, coupled-inductor
group (inductance matrix), DC voltage source with series resistance, input
port (audio), probe (node voltage or branch current), junction diode,
vacuum diode, triode (Koren or variable-mu, plus grid current), and pentode
(Koren). Controls such as pots and switches stay as values in the IR, so
changing a knob means rebuilding from the IR (see "Parameter changes").

### Discretization

- Fixed step h = 1 / (oversample x sample rate), the same oversampling as now
  (2x, from the tolerance study).
- Trapezoidal companion models for capacitors and inductors (bilinear
  transform). Coupled inductors use the inductance matrix directly, so
  k = 0.999 doesn't need its ill-conditioned inverse.
- Known risk: trapezoidal integration rings at Nyquist on stiff modes, as
  ngspice's trap did while the netlist oscillated. Mitigations, in order:
  oversampling, then a per-run switch to TR-BDF2 or backward Euler damping.
- *Superseded by M4's method study:* production is esdirk4 (L-stable, 4th
  order) at 2x with 5th-order input interpolation and local error control
  (see M4's status). Trapezoidal stays available and is the baseline the
  agreement tests check convergence with.

### Solver: full MNA Newton first, then nodal DK

1. **Full MNA with Newton (M3-M4).** Stamp everything into the modified nodal
   analysis matrix and run Newton over all unknowns each step. It is simple and
   obviously correct, and it is the baseline the DK version must match.
   Compiled models and a fixed step alone should already beat ngspice clearly.
2. **Nodal DK (M5).** The linear part of the circuit (R, C, L, sources) is
   folded into a discrete state-space system once, so each step only solves
   Newton on the nonlinear port variables (voltages and currents of the
   devices):

   ```
   p[n]   = D x[n] + E u[n]           (linear prediction of port voltages)
   v      = p[n] + F i                 (port voltages given port currents)
   f(v,i) = 0                          (device equations; Newton on M unknowns)
   y[n]   = D_o x[n] + E_o u[n] + F_o i
   x[n+1] = A x[n] + B u[n] + C i      (state update)
   ```

   Here M is the nonlinear dimension. For the 670: 6386 banks 2x(grid, plate),
   12AX7 and 12BH7 2x(grid, plate) each, 6973 2x(plate, screen), 4 bridge
   diodes, so M is about 20-24. Newton on a dense 24x24 system takes a few
   microseconds per iteration in compiled code.

   This follows the generalized method of Holters and Zölzer (2015), which
   derives the matrices automatically from a netlist. That's what makes the
   engine general, not hand-derived per circuit. ACME.jl (Julia, same
   authors) implements it and is our design reference.

### Devices

A `Device` trait: number of ports, `eval(v) -> (i, di/dv)` with analytic
Jacobians, an optional internal state (for hysteresis later), and an
initial-guess hint. The first library ports the existing Python models:

| Device | Source of truth | Notes |
|---|---|---|
| Koren triode, variable-mu triode (N sections), grid current | `varimu/devices/triode.py` | analytic; replaces the ngspice tables |
| Koren pentode | `varimu/devices/pentode.py` | |
| Junction diode (Shockley + Rs) | `varimu/devices/diode.py` | SPICE-style junction voltage limiting in Newton |
| Vacuum diode (Child law) | `varimu/devices/diode.py` | for the GZ34 rectifier |

Later, as circuits need them: BJT (Ebers-Moll / Gummel-Poon subset), JFET,
op-amp macro-model, optical cell (LA-2A T4B: an LDR with memory), and a
nonlinear transformer core with hysteresis (Jiles-Atherton, main plan Phase 2).
Every new device lands with the same three-way tests.

### Newton robustness

- Initial guess: the previous step's ports, extrapolated linearly.
- Step limiting: SPICE-style junction limiting for diodes and grid
  conduction, and a cap on the per-iteration change of tube port voltages.
- On failure, retry the step as k substeps (halving), then report the time
  and device, like ngspice's "timestep too small" with more detail.
- DC operating point: Newton with source stepping, then gmin stepping, the
  standard SPICE homotopies.

### Parameter changes

DK matrices depend on component values, so a pot or switch change means
recomputing them: a dense factorization of size about the node count, well
under a millisecond. That's free offline. For real time, recompute at control
rate on a worker, or precompute per switch position (the Time Constant
selector has 6) and crossfade.

### Python integration

- PyO3 bindings behind a `python` cargo feature, built with maturin as a
  separate Python package (`circuitsim`). `varimu` depends on it as an
  optional local path dependency (an extra, like `listen`).
- `sim_settings.yaml` gains `simulator.engine: ngspice | circuitsim`.
  `varimu.sim.runner` dispatches on it. The cache key includes the engine and
  a hash of the crate sources.
- The engine returns probes at the oversampled rate, and decimation stays in
  `varimu.sim.io` for now. It moves into Rust when the plugin needs it.

### Layout

```
Cargo.toml                 workspace (room for a plugin crate later)
crates/circuitsim/
  Cargo.toml
  src/lib.rs               public API: Circuit::from_ir, simulate, Session
  src/ir.rs                IR types (serde), validation
  src/mna.rs               stamps, sparse/dense assembly
  src/dk.rs                state-space derivation and port Newton (M5)
  src/fastmath.rs          vectorizable exp/ln for device sections (M5)
  src/newton.rs            nonlinear solve, limiting, substeps
  src/devices/{mod,triode,pentode,diode}.rs
  src/python.rs            PyO3 bindings (feature "python")
  tests/                   cargo tests; fixtures exported from Python
  benches/                 criterion benchmarks (670 slice, small circuits)
  pyproject.toml           maturin package `circuitsim`
```

## Verification

| Level | Check | Tolerance |
|---|---|---|
| Device | Rust model vs Python reference on fixture grids exported from Python (incl. 6386 with mismatch spreads) | 1e-12 relative |
| Linear circuits | RC, RLC, coupled inductors vs closed form and vs ngspice | ~1e-6 (discretization-limited, stated per test) |
| Small nonlinear | diode clipper, single triode stage, push-pull pair with transformer: vs ngspice at tight tolerance | output error < -60 dB re signal |
| 670 slice | vs ngspice with the exact triode formulation (gear, reltol 1e-4, 4x) on short excerpts: TC1-4 burst onset and release, the program clip's loudest and HF-richest 0.25 s; the whole clip vs circuitsim's converged solution (M6 follow-up) | output < -55 dB re signal; CV within 0.2 V; plus regression bounds a few dB outside the measured values |
| 670 behaviour | compression curve and Time Constant attack/release from `scripts/slice_report.py` | GR within 0.2 dB per step; times within 5% |
| Stability | idle circuit quiet (same as `tests/test_slice.py`) | |
| Speed | criterion benches and the existing `timing.csv` | tracked per milestone |

Fixtures come from Python, so the Python models stay the single source of
truth. Python tests call the binding on the same circuits ngspice runs.

**What each reference is for (decided 2026-10-21, after M6).** circuitsim
is now the more accurate engine: on the hot program clip, production ngspice
is -50.7 dB from circuitsim's converged solution and the tolerance study's
ngspice reference -55.3 dB, both limited by ngspice's tabulated triodes, not
its integration (M6 status). So:

- **Accuracy** is judged against circuitsim's own converged solution
  (esdirk4 at 4x, error tolerance / 10) and against analog behaviour: small-
  signal response vs `.ac` or closed form, aliasing, idle stability, no
  numerical artifacts. The converged-solution rows are the regression
  guards.
- **ngspice is the independent cross-check that catches bugs** (a wrong
  stamp, swapped pins, an IR translation error), which no self-convergence
  test can: a wrong equation converges to the same wrong answer. It does
  that best with the **exact triode formulation on short excerpts** (0.1-
  0.5 s at ~560x slower than real time alone, ~800x with `--verify`'s 14
  renders at once: a few minutes each), where it agrees with circuitsim to
  -62 to -68 dB (hot clip) and -76 to -92 dB (bursts), not with tabulated
  triodes on long renders.
- **Behaviour metrics** (gain reduction per step, CV attack and release)
  stay compared with production ngspice: they are robust to its waveform
  error.

`slice_report.py --verify` checks the 670 slice and behaviour rows this way
since the M6 follow-up (2026-10-21; numbers there).

## Milestones

Each one ends with its "done when" met and tested, like the main plan.

**M0. Scaffolding.** Workspace, crate, `cargo test` / `clippy` / `fmt`, a PyO3
"hello" built with maturin and importable from `uv run`. CLAUDE.md gets the
commands.
*Done when:* `uv run python -c "import circuitsim"` works and CI-style
commands pass on this machine.

**M1. Circuit IR.** Define the IR (Python dataclasses plus JSON schema; Rust
serde types). Refactor `netlist.py` to build IR, then emit SPICE from it.
*Done when:* ngspice renders from the IR path are bit-identical to today's (same
netlist text), and the IR round-trips Python -> JSON -> Rust -> JSON.

*Status (2026-10-13): M0 and M1 done.* Measured: the SPICE text emitted from
the IR is byte-identical to the pre-refactor netlists for 12 builds (defaults,
every Time Constant position, both pot extremes incl. the 0 dB T-pad short,
6386 mismatch, both triode formulations; `tests/test_netlist_golden.py`), and
all 10 distinct IRs round-trip Python -> JSON -> Rust -> JSON exactly (cargo
test on the fixtures; pytest through the binding). IR decisions made along the
way, with M2 in mind:

- **Coupled inductors are pairwise `Coupling` elements** (SPICE `K`: two
  inductor names and k), not a matrix in the IR. That is what SPICE emission
  needs. M2 turned out not to need explicit groups either: each inductor has
  a branch-current unknown, and each coupling stamps
  M_ij = k_ij sqrt(L_i L_j) into the reactive matrix next to the self
  inductances, so the inductance matrix is never inverted.
- **Device models in the IR are the `varimu.devices` dataclasses** (Triode
  with Koren or variable-mu plate and grid current, Pentode, JunctionDiode,
  VacuumDiode) with every parameter, so they can't drift from the Python
  reference. Instances are one generic `Device` element: model name plus
  nodes in the model's pin order.
- **The triode formulation (table vs exact) is not in the IR.** It's a SPICE
  emission choice; table grids are passed to the emitter.
- **Sections** (titled element groups) exist for readable, exactly
  reproducible SPICE; engines just concatenate them.
- **JSON** is versioned (`version: 1`), every number is a float, unknown
  fields are errors on both sides, and both sides run the same validation
  (unique names ignoring case, SPICE letter prefixes, positive values, model
  references and pin counts, couplings name inductors, input and probes
  connected).
- **Binding:** PyO3 0.29 with `abi3-py311` (one wheel for Python >= 3.11);
  for now it exposes `__version__`, `IR_VERSION` and `ir_roundtrip(json)`.

**M2. Linear engine.** MNA stamps for R, C, L, coupled inductors and sources;
trapezoidal fixed step; input and probes.
*Done when:* linear test circuits match closed form and ngspice; the 670's
transformers alone (driven by the input, tubes removed) match ngspice.

*Status (2026-10-14): done.* `mna.rs` (stamps), `linalg.rs` (dense LU),
`transient.rs` (fixed step; trapezoidal in companion form, as SPICE does it,
so resistive rows are solved exactly instead of averaged; backward Euler as
an option); binding `circuitsim.simulate`; Python wrapper
`varimu.sim.fast.run_transient` with `io.run_transient`'s oversampling and
decimation. Measured:

- **Closed form** (cargo, `tests/linear.rs`): RC, RL and series RLC driven by
  a sine from rest, and a k = 0.999 transformer against an independent RK4
  integration of its ODE. Errors fall 4x per halving of the step (2x for
  backward Euler); the transformer's start-up shows the known trapezoidal
  ringing of a mode faster than the step (leakage, tau = 0.65 us), 2e-3 of
  peak on the first step, decaying 0.6x per step.
- **ngspice** (`tests/test_circuitsim_linear.py`): small circuits and the 670
  with tubes and diodes removed, driven at the input (T101), the output
  (T102, T103) and a 6973 plate (T104), every node probed. The difference
  falls 12 dB per doubling of the oversampling, so what's left is the
  trapezoidal error; operating points agree with `.op` to 1.3e-9 of B+.
  Worst probe at k = 2 / 4 / 8: input -45 / -56 / -68 dB, output
  -39 / -49 / -60 dB, T104 -16 / -29 / -41 dB.
- **Speed:** the device-stripped 670 (83 unknowns, dense) runs at 2.0 s per
  second of audio at k = 2. Sparse vs dense is still M3's decision.

Findings that change later milestones:

- **k = 2 is not enough for the fixed-step engine on this circuit.** The
  transformers resonate at 20-110 kHz with Q up to 7 (T101 secondary 35 kHz,
  T103 75 kHz, T104 110 kHz: winding capacitance against leakage
  inductance), and trapezoidal integration warps those frequencies, by -9%
  at 35 kHz at k = 2. ngspice escapes this because it adapts its step. The
  670 target (-55 dB) needs about k = 8 near T104 unless the resonances are
  damped in reality (Phase 2's transformer models decide that) or the
  engine changes method. Options for M4: higher oversampling only inside the
  engine (decimating in Rust), or a higher-order or prewarped scheme for
  those modes. Measure on the full slice before choosing.
- **ngspice needs a reference mode to be a reference.** Plain runs straddle
  the input's sample kinks and interpolate the output (-55 to -75 dB on small
  circuits at tight reltol); `io.run_transient(max_step_div=8,
  grid_breakpoints=True)` fixes that. On the device-stripped 670 ngspice also
  needs gear for the T104 drive (trap ran > 300 s) and crawls at reltol 1e-6.
- **Bug found in the ngspice path:** a filesource reads 0 past its last
  entry, and the final timepoint could land a rounding error past it, so the
  last oversampled sample of every render saw input 0. Fixed in
  `io.input_chunks` (extra hold point), with a test.
- **Ill-conditioned nodes:** a node held only by a 1 GOhm leak (T104's
  secondary once the bridge diodes are gone) showed ~4 mV of roundoff with
  unscaled pivoting. Row/column equilibration brings it to the double-
  precision floor (~5e-5 V; ngspice shows ~2e-5 V there). Iterative
  refinement didn't help further and was dropped. Expect the same with
  reverse-biased diodes in M3; Newton's residuals behave like ngspice's.

**M3. Devices and Newton (full MNA).** Device trait; triode, variable-mu triode,
grid current, pentode, diodes; Newton with limiting and substeps; DC
operating point.
*Done when:* device fixtures match Python to 1e-12; the small nonlinear
circuits match ngspice; the 670 operating point matches ngspice's `.op`.

*Status (2026-10-14): done.* `devices/` (a `Device` trait: ports relative
to the last pin, currents plus analytic Jacobian, optional limiting, and an
`accept` hook for devices with memory), `newton.rs`, `transient.rs` (DC and
fixed-step transient with Newton). Measured:

- **Devices** (`tests/devices.rs`, fixtures from `varimu.devices.fixtures`):
  every 670 model, the mismatched 6386s, a 12AX7 without grid current, a
  diode without series resistance and the GZ34, ~3000 points. The tubes are
  bit-identical to Python (same order of operations, numpy's `logaddexp`
  softplus); the junction diode's Lambert W is within 1.7e-13 of scipy's.
  Jacobians match finite differences except where those can't straddle
  (the pentode's 1 mV screen floor, the onsets of `Vp^Ex` and `x^1.5`).
- **Small nonlinear circuits vs ngspice** (`tests/test_circuitsim_nonlinear.py`):
  a diode clipper, a 12AX7 stage driven into grid current, and a 12BH7
  push-pull pair with input and output transformers. Worst probe at
  k = 2 / 4 / 8: -39 / -51 / -63 dB, -39 / -51 / -63 dB, -45 / -55 / -68 dB,
  falling 12 dB per doubling, so what remains is the fixed-step trapezoidal
  error (M2's finding), not Newton's. DC within 1e-8 of the largest voltage.
- **670 operating point vs ngspice `.op`** (five builds: default, mismatch,
  both pot extremes, Time Constant 6): plain Newton converges in 14-17
  iterations (~3 ms). Every node agrees within 1e-10 of B+ or within the
  engine's own roundoff spread (see below), and ngspice's value lies inside
  that spread. Where the bridge is reverse biased (pots at minimum), every
  node is within 5.7e-10 V (2e-12 of B+).
- **Newton cost on audio:** ~3 iterations per step on the small circuits and
  2.6 on the full 670 (1 kHz tone, k = 2), no halvings. A first unoptimized
  run of the full 670: **1 s of audio in 9.2 s** at k = 2, one core, about
  3-4x faster than ngspice. M4 measures properly.

Decisions made along the way:

- **Sparse vs dense (open decision, now closed): dense, with block
  elimination.** Newton runs on the full MNA system, but the unknowns no
  device touches are eliminated once per step size (Schur complement), so
  each iteration refactors only the device-node block: 27 x 27 for the 670
  instead of 83 x 83. The iterates are exactly those of full-MNA Newton.
  Unknowns that would leave the linear block singular (a source or inductor
  between device nodes) join the device block automatically. No sparse LU,
  no faer dependency.
- **Junction diode as a two-terminal Lambert W device**, like the Python
  reference, not SPICE's internal node for RS. SPICE's GMIN (1e-12 S) is
  stamped across each junction diode as a linear conductance, to match
  ngspice. ngspice's `D` replaces Shockley with a cubic below -3 nVt (3e-3
  relative at -0.2 V); the bridge doesn't sit there in the builds tested.
- **Convergence tolerances: reltol 1e-6, vntol 1e-6 V** (SPICE's vntol).
  vntol can't go much lower: at DC, T104's secondary is a 1 mOhm winding
  whose common mode only the bridge diodes' leakage and a 1 GOhm leak hold,
  so double precision resolves it to ~1e-6..1e-5 V in any engine (measured
  by reordering the unknowns), and Newton's updates there never shrink
  below that. ngspice fails to find the operating point at all at
  reltol 1e-9. Newton's quadratic convergence leaves the real error on
  well-conditioned nodes far below the last update.
- **Robustness:** linear extrapolation of the previous two points as the
  initial guess (on by default: 2.6 vs 3.3 iterations per step on the 670;
  it costs iterations after a hard input step, e.g. 15 vs 8 on a 0 -> 100 V
  step onto a diode), SPICE `pnjlim` for junctions (tubes need no limiting so
  far), step halving up to 8 times with errors that name the time, sample,
  node and device pins, and DC by plain Newton, then gmin stepping, then
  source stepping. Halving only helps a junction so far: a step that turns a
  diode further on needs ~7 iterations at almost any step size.
- **Bug found in the ngspice path:** `varimu.sim.ngspice.run` documented an
  `options` argument but never wrote it into the deck, so every `.op`
  agreement test asking for tight tolerances ran at ngspice's defaults.
  Fixed (the existing tests still pass with the options applied), and `run`
  gained `digits` (`numdgt`; the default output has ~10 significant digits,
  which had limited the M2 `.op` comparison to ~5e-7 V).

**M4. The 670 slice on the fast engine.** Full transient with the full-MNA
solver; engine setting in the runner and cache.
*Done when:* the 670 verification rows in the table above pass, and the speed
is measured and recorded.

*Status (2026-10-15): done.* M2-M3 had left the engine at -40 dB from ngspice
at 2x on small circuits, and the plan's options were more oversampling or
another integration method. A method study on the full 670 decided it,
judged two ways: agreement with ngspice, and behaving like an analog circuit
(frequency response, aliasing, no numerical artifacts).

What the engine has now (`transient.rs`):

- **Methods:** `trap`, `euler`, `trbdf2`, `sdirk3`, `esdirk4` (Kennedy &
  Carpenter's ESDIRK4(3)6L[2]SA, with its embedded 3rd-order solution),
  `radau3`, `radau5`. All are stiffly accurate, so the MNA system's algebraic
  rows hold at every sample. Diagonally implicit methods solve one stage at a
  time with the same block-eliminated Newton as before; Radau solves its
  stages coupled (every device placed once per stage). `tests/methods.rs`
  checks each reaches its order.
- **Input interpolation** (`input_order` 1 / 3 / 5): Lagrange through the
  nearest oversampled samples at stage times. Linear (the default) is
  ngspice's PWL source.
- **Local error control** (`error_abstol`, `error_reltol`, esdirk4): Hairer &
  Wanner's filtered estimate, (G + G_dev + C/(gh))^-1 (1/g) sum d_i F_i with
  the last stage's Newton Jacobian; a step whose estimate exceeds the
  tolerance on a node voltage is redone as halves, up to 4 levels, starting
  each sample one level above the deepest the previous one needed. Outputs
  stay on the sample grid.
- **Newton predictor** for later stages: the quadratic through the last two
  samples and the latest solved stage (11-23% fewer iterations).
- Sparse `C x` and a vectorizable LU loop (about 1.5x per step, results
  within ~1e-11 relative of before).

How the method was chosen (scripts and data in the session's scratch
directory; the numbers below are what matters). The reference is the
engine's own converged solution (radau5 at 8x; trap at 32x agrees to
-105 dB), itself checked once against ngspice with the exact triode
formulation: -92 dB rms, CV within 0.003 V (0.5 s burst onset; that ngspice
run took an hour). ngspice with tabulated triodes, the tolerance study's
reference, sits -62 dB rms from it on every excerpt, so it can only referee
to about -60 dB.

1. **The error has three sources, not one.** (a) Integration of smooth
   dynamics: the slice's transformers resonate near 17 kHz (+10 dB, from the
   provisional winding capacitances) and trapezoidal's frequency warping
   moves that resonance; small-signal error at 20 kHz vs ngspice `.ac`:
   trap 2x 0.8 dB / 8 deg, 4x 0.18 dB / 2 deg, 8x 0.04 dB / 0.5 deg.
   (b) The input: linear between samples (as ngspice's PWL) droops a 20 kHz
   tone by 0.3 dB at 2x, which capped every higher-order method at -41 dB
   at 10 kHz until the input was interpolated to higher order. (c) Non-smooth
   events: the sidechain bridge switching (the TC1 attack slews the CV 75 V
   in 0.15 ms; HF content rectified), where no method's order helps and
   every method converges ~12 dB per doubling of the rate.
2. **With smooth input, higher order wins (a):** esdirk4 at 2x, input order
   5, matches `.ac` to -63 dB up to 20 kHz (0.00 dB / 0.04 deg); radau5 -73 dB.
3. **Only time resolution helps (c):** on a -10 dBFS 19 + 20 kHz twin tone,
   esdirk4 2x / 3x / 4x is -36 / -44 / -59 dB; trap 8x / 16x / 32x
   -39 / -50 / -62 dB.
4. **Error control combines both:** esdirk4 at 2x with error_abstol 0.01 V,
   error_reltol 1e-3, vs the converged solution (rms re signal / max CV):

   | excerpt | no control | with control | cost | fixed 4x |
   |---|---|---|---|---|
   | CCIF 19+20 kHz -10 dBFS | -36 dB / 0.71 V | -64 / 0.049 | 2.6x | -59 / 0.18 |
   | multitone -10 dBFS | -64 / 0.036 | -70 / 0.011 | 1.4x | -81 / 0.007 |
   | SMPTE 0 dBFS | -48 / 0.53 | -71 / 0.017 | 1.1x | -71 / 0.13 |
   | sweep 0 dBFS | -73 / 0.017 | -84 / 0.006 | 1.0x | -93 / 0.002 |
   | burst onset TC1 | -75 / 0.043 | -86 / 0.005 | 1.1x | -88 / 0.011 |
   | arpeggio clip | -80 / 0.012 | -83 / 0.006 | 1.05x | -92 / 0.002 |

   ("cost" is wall time relative to no control; fixed 4x costs ~1.7x.)
   Rejected: trapezoidal (needs 16x for broadband HF at -60 dB), 1x with any
   method (aliasing: a 7.9 kHz 0 dBFS tone leaves -47 dB of inharmonic
   products with esdirk4, -35 dB with trap; 2x: -68 / -51 dB; the analog
   truth -78 dB), trbdf2, sdirk3 and radau3 (each beaten at equal cost),
   radau5 (twice esdirk4's cost for little gain at 2x). Trapezoidal's
   theoretical Nyquist ringing on stiff modes did not show at any probe.
5. The 0 dBFS twin tone (CCIF) drives the provisional ~17 kHz resonance so
   hard that every setting, the reference included, halves thousands of
   steps: a limit of the provisional transformer model, left out of the
   tests. Phase 2's transformer models change the resonance, so rerun this
   comparison then; trapezoidal may become competitive again.

Verification (production: `sim_settings.yaml` `circuitsim` block):

- **670 slice** (`tests/test_circuitsim_slice.py`, 0.1 s excerpts): vs the
  converged solution, burst onset -79.7 dB / CV 0.010 V, sweep -79.6 / 0.009,
  CCIF -10 dBFS -63.7 / 0.044, multitone -70.5 / 0.010; vs the plan's ngspice
  reference (gear, reltol 1e-4, 4x), on the excerpts it can referee (content
  well below 20 kHz): burst -61.2 dB / 0.024 V, sweep -57.4 / 0.167 (that
  reference's own error at 0 dBFS). ngspice's input is linear between
  samples (-41 dB at 20 kHz at 4x) and gear damps near 20 kHz, so HF-rich
  excerpts are checked against the converged solution only.
- **670 behaviour** (`scripts/slice_report.py --engine circuitsim`, compared
  with the ngspice summary, both regenerated 2026-10-15): the compression
  curve (51 steps, 1 kHz) agrees within 0.033 dB per step (tolerance 0.2 dB);
  for TC1-4 the CV attack and the 63% / 90% releases agree within 0.05%
  (tolerance 5%) and the burst gain reduction within 0.04 dB.
- **Stability:** `tests/test_slice.py` runs the idle and gain-reduction tests
  on both engines.
- **Speed** (one core, production settings, nothing else running): 25-30x
  slower than real time on program material and tone bursts (~10 Newton
  iterations per sample: 5 stages, ~2 each, ~13 us per iteration), 70x on
  the -10 dBFS multitone, 190x on the -10 dBFS twin tone. That is about
  ngspice's speed (25-40x), with far better accuracy. Trapezoidal at 2x runs
  6-8x. Where the time goes (`examples/profile.rs`): per iteration, the two
  32-section 6386 models (~4.6 us) and the 27 x 27 refactor (~4 us); per
  stage, the block reduction. M5 has to recover the speed: fewer iterations
  per stage (the update-based convergence test needs 2), cheaper 6386
  evaluation, the DK reduction.

Engine plumbing: `simulator.engine` in `sim_settings.yaml` (ngspice stays
the default until M6), `TransientSettings.from_sim_settings(engine=...)`,
`varimu render --engine`, `slice_report.py --engine` (it writes
`summary_circuitsim.json` and compares it with the ngspice summary against
the behaviour tolerances). The render cache key includes the engine and the
hash of the crate sources the binary was built from; `build.rs` embeds that
hash (`circuitsim.SOURCE_HASH`) and `varimu.sim.fast` refuses to run a build
whose hash doesn't match the working tree (`StaleBuild`), so plain `uv run`
after a Rust edit fails loudly instead of rendering with the old binary.

Found along the way: `metrics.cv_timing` read crossings at whole samples,
which quantizes the TC1 attack (13 samples) by 8%, more than the 5%
tolerance; it now interpolates between samples (`tests/test_metrics.py`).

**M5. Nodal DK.** Automatic derivation of the state-space matrices from the
IR; Newton on the nonlinear ports only; parameter-change recomputation.
*Done when:* DK and full-MNA agree to solver tolerance on every test circuit,
and the 670 slice is at least 10x faster than ngspice (target: near real time).

*Status (2026-10-17): done except the speed target.* DK, agreement and
parameter changes are done; the 670 slice runs 5-6x faster than ngspice,
short of the 10x target. Decided 2026-10-17: the speed target is deferred
until the main milestone work is done (the "Open" item under Speed below
lists where to start), and M6 goes ahead. What the engine has now:

- **`dk.rs`**: for each step matrix `A = G + C/(g h)` (one per step size,
  built on first use, ~0.7 ms for the 670), the responses of `A^-1` to the
  state, the stage inputs, the device ports, `b` and the input, read out on
  the ports, the state rows and all unknowns. A diagonally implicit stage is
  then an M x r product, Newton on the M = 22 device port voltages, and an
  r x (r + M) product for the state (r = 43: the rows where `C` has
  entries); the unknowns themselves only at the end of a step. Radau (fully
  implicit) stays on full MNA. `solver: dk | mna` picks the solver (`dk` is
  the default; `mna` is M3-M4's, the reference).
- **Newton with a lagged Jacobian** (Hairer & Wanner IV.8): the factored
  `I + K G` is kept across iterations, stages and steps (one per step size)
  and refactored when an iteration contracts by less than 0.5, after the
  last solve contracted by more than 0.1, and on and after junction
  limiting (a chord step from a limited linearization cycles at a diode
  turning on). Devices whose ports moved less than the tolerance keep their
  last evaluation (SPICE's bypass). On a 1 kHz tone at the production
  tolerance: 8.7 iterations, 63 device evaluations (of 12 devices) and 1.4
  factorizations per sample, against 11.5 iterations and as many 27 x 27
  refactors for M4.
- **Device evaluation**: the 6386's 32 sections run in passes over arrays
  with vectorizable `exp`/`ln` (`fastmath.rs`, within 1 ulp of `std`), AVX2
  when the CPU has it (detected at run time; same results either way):
  0.4 us per tube instead of 2.0. Fixtures still within 4e-16 of Python.
- **Parameter changes**: `Transient::update(ir)` takes the same circuit
  with other values (pots, refits, Time Constant positions 1-4), carries
  the state over and restarts consistently (`C x'` from the new circuit at
  the current point). ~0.3 ms, plus ~0.8 ms in the next step (the DK
  system); positions that add nodes (TC 5-6, the input pad's 0 dB end) are
  refused, and switching while running is M8's (crossfading).
- **Settings**: `circuitsim` block: `solver: dk`, Newton `reltol 1e-4`,
  `vntol 1e-3 V` (10x tighter than the local error tolerance), reuse on.
  Python: `TransientSettings.solver / newton_*`, `circuitsim.simulate(...,
  solver=, newton_reuse=)`, stats with device evaluations and
  factorizations.

Numerical findings (each cost a wrong turn first):

- **State variables.** The first DK version carried `C x` (charges,
  fluxes) as the state, as DK derivations usually do. In the 670 the
  push-pull windings carry DC fluxes (~5 Wb) that cancel between halves, so
  `C x/(g h)` is 1e4-1e6 while the port voltages are 1-300 V: summing
  precomputed response columns with such coefficients lost 3-5 digits (DK
  1e-4 V from full MNA on the plates, whose own roundoff spread is 1e-7 V).
  Carrying `x_S` (node voltages, inductor currents) and precomputing the
  response to `C x_S/(g h)`, which is `I - A^-1 G` on those rows, fixed it.
- **The floating bridge.** With the devices removed, `A` leaves T104's
  secondary and the bridge on a 1 GOhm leak next to 1 mOhm windings: K
  reaches 1e9 Ohm and the precomputed responses lost 4 digits everywhere
  (iterative refinement diverged: the matrix is too close to singular for
  double-precision residuals). Each diode port now lends a fixed 10 uS from
  the device to `A` (`A + N^T G0 N`, the device becomes `i - g0 v`): exact
  in exact arithmetic, and the island's conditioning moves to the small
  Newton matrix, equilibrated and refactored when needed, as full MNA does
  on its device block. 1e-7..1e-5 S all agree with full MNA within its own
  roundoff spread; 0 is 50-80x off, 1e-3 S 2.4x.
- **The island's own floor.** With the bridge off, T104's secondary hangs
  on ~1e-7 S of diode leakage (or the 1 GOhm leak alone, bridge reversed),
  and the 1 mOhm winding's ~5e4 A conductance terms leave ~1e-11 A of
  roundoff in its KCL: 1e-4..1e-2 V of common mode in any solver. In
  40-digit arithmetic at one sample, full MNA's solution there violated the
  island's KCL by 4e-12 A, DK's by 1e-12 A. Reordering the unknowns doesn't
  reveal this floor (both orderings share it). Tests compare the island
  relative to its common mode, and the common mode against that floor.
- **Newton tolerance.** Against the converged solution (esdirk4 4x, error
  tolerance / 10), production with Newton tolerances 1e-6, 1e-5, 1e-4 and
  1e-3 (with and without reuse) gives the same error to 0.3 dB on all five
  M4 excerpts: the integration error dominates by orders of magnitude.
  Newton's update tolerance was what forced a second iteration per stage
  (the stage predictor misses by ~1e-3 V on the plates); most stages now
  take one. The remaining extra iterations are the bridge diodes switching.
- **Large instantaneous parameter jumps** (a pot thrown end to end in one
  sample) make Newton fail in both solvers, halving or not: an algebraic
  jump looks the same at any step size. Swept over 32 samples, it runs.
  Smoothing is M8's.

Verification:

- **DK vs full MNA** (exact Newton, so the iterates are the same):
  `tests/dk.rs`, every node of the 670 at every sample, four builds
  (default, TC1, pots at minimum, mismatched 6386s), trapezoidal and
  esdirk4 with and without error control, 6 ms of 0 dBFS: within 0.2
  tolerance, with the same error-control decisions; the island's common
  mode within its floor. With reuse each solve ends within a tolerance and
  the differences add up over steps (<= 3 tolerances with esdirk4, <= 18
  with trapezoidal, which doesn't damp them). Python
  (`test_circuitsim_{linear,nonlinear}.py`): every small test circuit and
  the device-stripped 670 driven at three points, trapezoidal and esdirk4:
  within one tolerance (the stripped 670's floating secondary excepted).
  Through parameter changes (`tests/update.rs`): within 0.13 tolerance.
- **Closed form**: an RC whose R switches mid-run, within 7e-13 V. The M2-M4
  closed-form, order-of-accuracy and nonlinear tests all run on DK now.
- **670 slice** (`tests/test_circuitsim_slice.py`, production = DK): same
  bounds as M4 vs the converged solution and vs ngspice. `slice_report.py
  --engine circuitsim` (regenerated): compression curve within 0.033 dB per
  step of ngspice, TC1-4 attack and releases within 0.05%, burst gain
  reduction within 0.04 dB, as at M4.
- **Speed** (`varimu.sim.runner.render`, cache bypassed, one job at a
  time, same desktop and session, 2026-10-17; x = slower than real time):

  | render | ngspice (trap 1e-3, 2x) | full MNA (M4) | DK (M5) | DK vs ngspice |
  |---|---|---|---|---|
  | 7 s burst, TC1, 0 dBFS | 20.6x | 15.8x | 3.3x | 6.2x faster |
  | 4 s program clip (arpeggio) | 21.2x | 18.5x | 4.2x | 5.0x faster |

  On the HF test excerpts error control still subdivides steps: CCIF
  -10 dBFS 77x (M4 142x), multitone -10 dBFS 21x (M4 53x). This desktop's
  timings drift +-35% with background load (an IDE's `cargo check`, a busy
  explorer.exe), so speed claims here are back-to-back ratios.

  **Open: the 10x target** (2-2.5x real time on this material). A stage
  costs ~4 us on average: one evaluation of the devices (~1.5 us, half of
  it the two 6386s), the bridge diodes' extra iterations, the M x M solves,
  and ~1 us of stage linear algebra. Next candidates, roughly by size:
  fewer factorizations (tune the reuse thresholds), the bridge diodes'
  extra iterations (a cheaper partial update when only they moved), the
  6386's sections (their 1/mu are an arithmetic progression, so
  `exp(-|a|)` is a running product: one transcendental of four), and loop
  overhead in the iteration bookkeeping. Each is a few percent to ~15%.

Profile of a step on the 670 (1 kHz tone, production tolerances, cycle
counts from `cargo run --release --features timing --example profile`):
devices 37%, the rest of the Newton iterations 20%, stage linear algebra
16%, factorizations 14%, per-step linear algebra 7%. The 6386 pair is half
the device time. Global AVX2 (`target-cpu=x86-64-v3`) gained nothing: at
these sizes (M = 22, r = 43) the linear algebra is bound by loop overhead,
not arithmetic.

**M6. Default engine.** The listen app and renders use the fast engine. ngspice
stays for verification (a setting, plus a periodic agreement test).
*Done when:* the done-when renders from the slice handoff (compression curve,
TC bursts, a program clip) reproduce on the fast engine within the
verification tolerances.

*Status (2026-10-21): done.* circuitsim is the default engine
(`simulator.engine: circuitsim`); ngspice is the reference, by name
(`--engine ngspice`) and in the periodic agreement test. What changed:

- **Default and fallback.** Renders, `varimu render`, the listen app and
  `slice_report.py` use the configured engine. Without the `fast` extra a
  render raises `fast.EngineUnavailable`, whose message says how to install
  it or pick ngspice; the CLI (`render`, `listen`) checks the engine (and a
  stale build) before any work and exits with that message. Decided: no
  silent fallback to ngspice, for the same reason as `StaleBuild`: a render
  that quietly comes from another engine (5-7x slower, different numbers,
  another cache key) is worse than a clear stop.
- **Progress and Ctrl-C.** `circuitsim.simulate(..., progress=)`: the run
  takes the GIL back ~200 times to check signals and report the fraction
  done (`transient::simulate_with_progress` in Rust), so the listen page's
  progress bar moves (it used to jump to 100%) and Ctrl-C stops a render.
- **Parallel renders and priority.** circuitsim runs on the runner's
  threads, in-process with the GIL released; `fast.thread_priority` gives
  each such thread the `runner.priority` (Windows: below_normal is
  THREAD_PRIORITY_LOWEST, base priority 6, the same as a thread of ngspice's
  BELOW_NORMAL process; elsewhere a no-op) and restores it afterwards.
  Throughput on this 8-core / 16-thread desktop (2 s clip excerpts at once,
  per-job wall vs one job): 1 / 2 / 4 / 8 / 14 / 16 jobs give 1.0 / 1.9 /
  3.6 / 6.4 / 8.5 / 7.8x one job's throughput, so the default
  `max_parallel_jobs` (cpu_count - 2 = 14) stays.
- **Listen app.** Checked end to end over HTTP on circuitsim (two 2 s
  renders of the arpeggio clip, progress in 34 visible steps, compare and
  audio); the page shows the engine and starts its time estimate from that
  engine's last uncached render in `timing.csv`.
- **Program clip in `slice_report.py`** (`--clip`, default the arpeggio in
  `data/clips/`, left out where missing): gain over 50 ms windows and the
  CV, at the tolerance study's front panel (input pad 0 dB, threshold 0.8,
  TC2), where the clip compresses by up to ~6 dB and the CV swings to
  -84 V.
- **The periodic agreement test** is one command, `slice_report.py
  --verify`: the report on both engines, the TC bursts and the clip on the
  ngspice reference (gear, reltol 1e-4, 4x), the clip on the converged
  solution (esdirk4 4x, error tolerance / 10), checked against the
  Verification table; `reports/slice/agreement.json` and `agreement.png`,
  exit status 1 on failure. ~15 min from a cold cache (18 renders in
  parallel; ngspice's 25.5 s staircase is the longest at 13 min), 15 s
  warm. The pytest agreement tests (`test_spice_agreement.py`,
  `test_circuitsim_{linear,nonlinear,slice}.py`, `test_slice.py`) stay in
  the default test run.

Verification (`slice_report.py --verify`, 2026-10-21, all pass):

| check | tolerance | measured |
|---|---|---|
| compression curve, GR per step vs ngspice | 0.2 dB | 0.033 dB |
| clip gain per 50 ms window vs ngspice | 0.2 dB | 0.028 dB |
| TC1-4 burst GR vs ngspice | 0.2 dB | 0.03-0.04 dB |
| TC1-4 CV attack, 63% / 90% release vs ngspice | 5% | <= 0.05% |
| TC1-4 bursts (7 s) vs ngspice reference | -55 dB, 0.2 V | -65.8 to -67.2 dB, CV <= 0.023 V |
| clip (4 s) vs ngspice reference | -55 dB, 0.2 V | -55.5 dB, CV 0.040 V |
| clip vs converged solution | -55 dB, 0.2 V | -76.7 dB, CV 0.007 V |

For scale, production ngspice vs its reference: bursts -74 to -77 dB,
clip -54.6 dB (it would fail the clip row), and production ngspice vs the
converged solution on the clip: -50.7 dB.

**The clip row vs ngspice passes by 0.5 dB, and the margin is the
reference's, not circuitsim's.** The ngspice reference itself is -55.3 dB
from the converged solution, band for band the same as circuitsim vs the
reference, mostly below 2 kHz. It is not integration error: ngspice gear
and trap at 8x agree with each other to -72 dB and still sit -56 dB from
the converged solution. It is the tabulated triodes: on 0.1 s of the clip
around its deepest CV (-84.5 V), ngspice with tables vs the exact
formulation is -53.3 dB; with the exact formulation ngspice agrees with
circuitsim's converged solution to -66.3 dB, and circuitsim production
with exact ngspice to -66.4 dB (production vs converged there: -79.5 dB).
M4 measured the tables at ~-62 dB on lighter material; this front panel
drives the 6386s further down their curves. So with the tolerance study's
reference the -55 dB row can't referee this clip much more tightly; a
regression in circuitsim shows first in the converged-solution row. Options
if the margin bites: the exact formulation for the clip's reference (~560x
slower than real time: ~40 min for the 4 s clip), or finer 6386 table
grids. (The follow-up below replaced this row with exact-formulation
excerpts.)

- **Speed** (`runner.render`, cache bypassed, one job at a time, back to
  back, 2026-10-21; x = slower than real time; best of the runs, which
  drifted 3.7-6.5x for circuitsim):

  | render | ngspice (trap 1e-3, 2x) | circuitsim | |
  |---|---|---|---|
  | 7 s burst, TC1, 0 dBFS (defaults) | 26.0x | 3.7x | 7.0x faster |
  | 4 s arpeggio clip (pad 0 dB, threshold 0.8, TC2) | 25.6x | 4.5x | 5.6x faster |

  In the listen app, with the verify run's 14 renders going at once, a 2 s
  render took ~14x.

**M6 follow-up: rework `--verify` around the reference roles** (decided
2026-10-21; do it first in the next session, before Phase 2 changes the
circuit, so the agreement test is trustworthy when it matters). In
`scripts/slice_report.py --verify`:

- Replace the waveform rows against the tabulated ngspice reference (7 s
  bursts, 4 s clip at gear 4x) with ngspice at the **exact** triode
  formulation (`nl.build(..., triode_formulation="exact")`; `runner.render`
  builds with the configured formulation, so this needs a way to pass it,
  e.g. a field in the render job or a direct `io.run_transient` as in the
  M6 scratch measurement) on short excerpts: the TC1-4 burst onsets and
  releases (~0.1-0.3 s each) and 0.1-0.3 s of the clip at its deepest CV
  and at a loud HF-rich passage. circuitsim runs the same excerpts.
- Keep the plan's -55 dB / 0.2 V as the pass criterion, and record the
  measured values with regression bounds a few dB outside them, as
  `tests/test_circuitsim_slice.py` does (measured on the clip excerpt: exact
  ngspice vs circuitsim production -66.4 dB, CV 0.030 V).
- Keep the behaviour rows vs production ngspice and the clip vs the
  converged solution. Drop the production-ngspice-vs-reference rows (they
  were only for scale).
- Target: cold run well under the current ~15 min, the excerpts in parallel.
- Update the Verification table's 670 slice row, CLAUDE.md's command line
  for `--verify`, and this status with the new numbers.

*Status (2026-10-21): done.* What `slice_report.py --verify` runs now:

- **Waveforms vs exact ngspice** (gear, reltol 1e-4, 4x, exact triodes:
  `TransientSettings.triode_formulation`, which `runner.render` builds the
  netlist with; it is part of the cache key) on six excerpts, each from the
  operating point: a 0.1 s 0 dBFS 1 kHz burst out of -40 dBFS at TC1-4
  (20 ms before, 0.15 s of release after: 0.27 s), and 0.25 s of the clip
  ending with its loudest 0.1 s window (0.60-0.85 s, the deepest CV:
  -84.4 V) and with its HF-richest one (most energy above 5 kHz; 2.35-
  2.60 s), faded in over 10 ms. Both windows are picked from the input, so
  another `--clip` gets its own. The reference settings stay: production
  ngspice (trap 2x) with exact triodes fails the HF excerpt on its own
  error (-50 dB from the converged solution; -61 dB at gear 4x).
- **The whole clip vs the converged solution**, and the behaviour rows vs
  production ngspice, as before. Dropped: the tabulated ngspice reference
  and the production-ngspice-vs-reference rows.
- **The compression curve's staircase runs as 9 parallel chunks** of 6 steps,
  each with one warm-up step whose gain is dropped (in every report, not
  only `--verify`). Every step settles well within its 0.5 s and levels only
  rise, so this is the continuous curve: within 2.9e-6 dB on circuitsim
  (2.3e-5 dB without a warm-up step). `--verify` keeps checking that (0.01 dB
  tolerance). It took ngspice's staircase, the old long pole, from 13 min to
  ~2.
- **Cold run 344 s** (42 renders, 14 at once; the longest are production
  ngspice's 7 s bursts at ~255 s and the exact excerpts at 190-245 s), down
  from ~15 min; 16 s warm.
- Found on the way: one of the 42 renders failed renaming its finished
  directory into the cache (Windows access denied: a scanner or the indexer
  briefly holding a new file). `runner` now retries the rename with backoff.

Verification (`slice_report.py --verify`, 2026-10-21, all pass; regression
bounds apply at the default front panel and clip):

| check | tolerance | regression bound | measured |
|---|---|---|---|
| compression curve, GR per step vs ngspice | 0.2 dB | | 0.033 dB |
| clip gain per 50 ms window vs ngspice | 0.2 dB | | 0.028 dB |
| TC1-4 burst GR vs ngspice | 0.2 dB | | 0.03-0.04 dB |
| TC1-4 CV attack, 63% / 90% release vs ngspice | 5% | | <= 0.05% |
| chunked vs continuous staircase (circuitsim) | 0.01 dB | | 2.9e-6 dB |
| burst TC1 excerpt vs exact ngspice | -55 dB, 0.2 V | -75 dB, 0.05 V | -78.1 dB, CV 0.028 V |
| burst TC2 excerpt | | -73 dB, 0.05 V | -76.3 dB, 0.028 V |
| burst TC3 excerpt | | -73 dB, 0.03 V | -76.8 dB, 0.015 V |
| burst TC4 excerpt | | -78 dB, 0.02 V | -81.3 dB, 0.007 V |
| clip, loudest 0.25 s, vs exact ngspice | -55 dB, 0.2 V | -64 dB, 0.04 V | -67.5 dB, 0.017 V |
| clip, HF-richest 0.25 s | | -58 dB, 0.06 V | -61.6 dB, 0.034 V |
| clip (4 s) vs converged solution | -55 dB, 0.2 V | -73 dB, 0.02 V | -76.7 dB, 0.007 V |

On every excerpt the margin to -55 dB is ngspice's: exact ngspice is as far
from circuitsim's converged solution as circuitsim production is from it
(bursts -76 to -83 dB, clip -67 / -61 dB), while circuitsim production is
-73 to -91 dB from its converged solution there. So a regression in
circuitsim shows first in the converged-solution row; the exact-ngspice
rows are the independent check for wrong equations. The bounds change when
the circuit does (Phase 2): re-measure them then.

**Phase 2 in circuitsim: the hysteretic core (2026-10-21).** Main plan
Phase 2's transformers need a core with memory. What the engine has now:

- **IR v2:** `Winding` (a branch with `v_a - v_b = N A dB/dt` on a core
  node whose voltage is B, 1 V = 1 mT, `TESLA_PER_V`; its current feeds
  `N i` into the core node's KCL) and the `MagneticCore` device model (a
  Jiles-Atherton core from the core node to ground drawing `l_e H(B)`).
  Gap and eddy loss are linear elements on the core node. A transformer is
  windings + series R + leakage L + self-capacitance + core node + core.
- **The core** (`devices/core.rs`, Python reference `varimu/devices/core.py`,
  same order of operations): the JA model in its effective-field form, as a
  rate-independent map H(B) from the last accepted point along a monotonic
  path, integrated by RK4 substeps (at most 1 mT of B, 5% of `a + |H|` of
  H, halved until the end slope is within 25% of the start's: stiffness and
  curvature deep in mumetall's saturation and its Rayleigh region need
  both); `accept` commits (B, H, direction). Jacobian dH/dB at the path's
  end. Newton limiting: 50 mT per iteration, and an iterate that crosses
  the state's B keeps 10% of its offset (H ~ sqrt(B) from the demagnetized
  state cycles plain Newton). `shunt` lends the demagnetized slope to DK.
  Fixtures from Python on a magnetization history (demagnetized, up, down,
  saturation; three materials and a literature set) agree to 1e-12.
- **DK** takes C's columns as well as its rows as the state (a winding's
  row reads its core node's column: C isn't symmetric there), and a
  stateful device's `accept` now drops only its own cached evaluation
  (`DkNewton::invalidate_device`), not every device's and the factored
  Jacobians. `Transient::update` carries device state across (new trait
  methods `state` / `set_state`): it used to rebuild cores demagnetized.
- **SPICE** (`varimu/circuit/spice.py`): no MagneticCore (decided
  2026-10-21); a core in its linear limit (resistors and capacitors on the
  core node) goes out as coupled inductors with each winding's leakage
  folded into the inductance matrix (k < 1), eddy loss as a shorted turn,
  and `.options rshunt=1e12`. Three other emissions ran small circuits but
  stopped ngspice on the 670 (the module docstring has which and where).

Verification:

| check | measured |
|---|---|
| core map vs a forward (H-driven) JA solve | 2e-9 .. 5e-8 of the peak H (mumetall 4e-6) |
| per-sample stepping vs the same path 50x finer (30 Hz into saturation) | <= 1.5e-6 of peak-to-peak H |
| circuits vs an exact Python solution (winding / transformer with gap / load, driven into saturation with minor loops; steel, permalloy, mumetall below and past saturation) | production -79 to -95 dB, converged -85 to -94 dB, B within 5e-5 T |
| DK vs full MNA on those circuits | 0.00 tolerances (exact Newton) |
| linear-core windings vs coupled inductors, circuitsim | -250 dB |
| linear-core windings vs ngspice, small circuit / each 670 transformer standalone | -145 dB / -60 to -71 dB at 8x (trap, converging 12 dB per doubling) |
| 670: DK vs MNA, `.op` vs ngspice, idle stability | pass (an error-control decision with reuse can now differ: then within 5 error tolerances) |

`slice_report.py --verify` on the Phase 2 circuit: ngspice rows compare
both engines on linear cores (behaviour 0.043 dB / 0.06%; excerpts -61.8 to
-80.7 dB), the converged row runs the Jiles-Atherton cores (-76.3 dB, CV
0.006 V); bounds re-measured (the script lists them). Cold run 541 s (the
report now also renders on circuitsim with linear cores), 37 s warm.

**M4's method comparison rerun on the Phase 2 slice** (Jiles-Atherton cores,
0.1 s excerpts faded in, front panel pad 0 dB / threshold 0.8, reference
radau5 at 8x with error tolerance / 10; rms dB re signal):

| excerpt | production (esdirk4 2x, control) | esdirk4 2x | esdirk4 4x | trap 2x | trap 8x | trap 16x |
|---|---|---|---|---|---|---|
| CCIF 19+20 kHz -10 dBFS | -67.5 | -35.4 | -47.5 | -18.3 | -43.0 | -52.8 |
| multitone -10 dBFS | -70.3 | -69.4 | -79.5 | -40.0 | -64.7 | -76.0 |
| SMPTE 0 dBFS | -74.3 | -41.4 | -60.6 | -40.7 | -50.9 | -66.9 |
| sweep 0 dBFS | -80.0 | -79.1 | -81.7 | -61.4 | -82.6 | -88.2 |
| burst onset TC1 | -71.7 | -59.8 | -73.5 | -51.8 | -70.1 | -77.7 |
| arpeggio clip, loudest 0.1 s | -76.6 | -75.5 | -81.5 | -61.4 | -85.0 | -86.6 |

The provisional 17 kHz resonance that chose esdirk4 is gone (T101's
secondary resonance now sits at 35.5 kHz, +1.4 dB), and the choice stands:
trapezoidal still needs 8-16x on HF-rich and switching material. Speed
(`runner.render`, cache bypassed, one at a time; x = slower than real time):
7 s TC1 burst / 4 s arpeggio clip, circuitsim with JA cores 5.8x / 7.3x,
with linear cores 4.2x / 5.8x, ngspice (linear cores) 22.3x / 26.6x. The
four cores cost ~35% (four more devices evaluated every iteration).

**Phase 3 in circuitsim: the power supply (2026-10-21).** Main plan Phase 3
puts the 670's power supply in the circuit: the mains, two rectifiers, a
tube regulator, the bias supply, and idle channel 2's draw on the rails.
What the engine gained:

- **IR v3: `SineSource`**, SPICE's `SIN(VO VA FREQ 0 0 PHASE)` (the mains).
  It gets a branch row like a DC source: its offset is in `b`, and its sine
  is a `Wave` on its row, evaluated exactly at every stage's absolute time
  `(n + theta) h` in all three step paths (DK, full-MNA DIRK, Radau). DK
  keeps one more response column per wave (`DkSystem::bw`, applied in
  `stage` / `unknowns`). The DC operating point takes the source at t = 0,
  as ngspice's transient operating point does, so phase 90 starts the run
  at the mains peak with no jump (`spice.py` writes `dc` = the t = 0 value
  as well). Checks: an RC driven by a sine source against its closed form,
  DK / MNA / Radau / trapezoidal (`tests/linear.rs`), and a GZ34 full-wave
  rectifier against ngspice, -108.6 / -120.6 / -132.1 dB at 2x / 4x / 8x,
  DC 5e-11 (`tests/test_circuitsim_nonlinear.py`).
- **Pentode grid current.** The Koren pentode now takes the triode's
  `GridCurrent` law on its control grid (Python reference, SPICE `Bg1`, Rust
  `devices/pentode.rs`; the grid term is shared, `triode::grid_current`).
  Without it, the 6973 grids, now driven harder (the 12BH7 plates on the
  traced 435 V rail, the 6973 grid-leak return at -13.7 V instead of the
  slice's provisional -27 V), went to +251 V on the mismatch fixture, with
  plates at 1245 V and the CV at -296 V. With it they clamp near +1.9 V
  (the CV then peaks at -60 V), and esdirk4 at 2x / 4x / 8x and radau5 at 8x
  agree. Trapezoidal at 2x rings at 57.7 kHz there, its known weakness.
- **An exact retry before halving** (`try_step_dk`): when a stage's Newton
  solve with the lagged Jacobian fails, it is redone from the same guess with
  exact Newton before the step is halved (`Stats::exact_retries`). The new
  grid-conduction knee is where reuse stalled: `pots_min` halved 4 steps
  with reuse where exact Newton halved none.
- **Settling** (`TransientSettings.settle_s`, sim_settings `start.settle_s`
  = 1 s): the run starts from the DC point with the mains at its peak, so
  renders first run 1 s with the input held at its first sample; both
  engines, outputs trimmed. `--verify`'s exact-ngspice excerpts skip it in
  both engines (`EXCERPT_SETTLE_S`): an engine-to-engine comparison needs
  the same start, not a settled one.

- **Parallel devices merged** (`devices::Parallel`, `mna::merge_parallel`):
  stateless instances of one kind on the same pins (a 6386 bank, now its four
  triodes, each with its own mismatch) become one instance, named after all
  of them, their currents and Jacobians summed. The Newton system keeps the
  bank's two ports (45 in all), and the DK bypass skips evaluating unmoved
  parts: four triodes per bank cost ~5% over one (1 s of the clip, 27.6x vs
  26.2x real time). Tested against the sum of the parts (`tests/devices.rs`).

`slice_report.py --verify` on the Phase 3 circuit (2026-10-22): behaviour vs
production ngspice 0.08 dB GR, clip gain 0.022 dB, attack / release within
0.15%; excerpts vs exact ngspice -80.9 to -85.2 dB on the bursts, -76.2 /
-70.8 dB on the clip's loudest / HF windows (better than Phase 2's); the clip
vs circuitsim's converged solution -56.8 dB / CV 0.19 V (Phase 2: -76.3 /
0.006), at the plan's tolerance: the error is the clip's first attack from
rest, the CV falling ~80 V in ~2 ms, the bridge turning on within a step.
10x tighter error tolerances give 0.07 V for +19% time, 4x oversampling
0.04 V for +43%; production is unchanged pending the user's call (main plan,
Phase 3 findings). Cold run 72 minutes (exact ngspice on a circuit twice the
size).

DK vs full MNA on the 670 (`tests/dk.rs`) still holds at its bounds: exact
Newton within 0.12 tolerance everywhere, Jacobian reuse within 28
tolerances (the worst nodes are now the 6973 plate-to-grid feedback nodes
nfa / nfb), differing error-control decisions within 18.5 error tolerances.
The test now names the worst node.

**Speed regressed** (one render at a time, x = slower than real time): the
7 s TC1 burst 14.3x (Phase 2: 5.8x), the 4 s arpeggio clip 36x (7.3x), at
the slice report's front panel (pad 0 dB, threshold 0.8). Two causes,
measured on 1 s of the clip:

| variant | x real time | halved samples |
|---|---|---|
| as built | 26.2 | 14107 of 192000 |
| 6973 grid current off | 14.7 | 357 |
| softer grid knee (0.2 V, every tube) | 25.4 | 13321 |
| error control off | 17.4 | 0 |

- **The circuit doubled** (45 device ports, 82 states; Phase 2: 22 ports):
  ~2x on its own.
- **The 6973 grid conduction** costs another ~1.8x: every time the hard-driven
  6973 grids clamp, error control halves the step (16,529 rejections in that
  second). It is physical (it also stops the runaway above) and a softer knee
  doesn't help; what would is step-size selection that doesn't halve
  recursively from the full step, or not re-deriving the whole step on a
  local event. Open, with M5's deferred speed target.

**Speed after Phase 3: step selection, probe-only steps, AVX2 (2026-10-23).**
Asked for before main-plan Phase 4, with the obvious lever named: step-size
selection that doesn't halve recursively from the full step. Measured first
(1 s of the arpeggio clip at the slice report's clip panel, `examples/bench.rs`,
the Phase 3 circuit with T103 at 8.5):

- **Halving wasn't the cost.** Error control costs ~1.34x over none (25.2x vs
  33.9x real time), but rejected steps are only 6% of step attempts (13.7k of
  223k). The rest is substeps the accuracy needs (error control off: -55 dB /
  CV 0.26 V from the converged solution, against -79 dB / 0.039 V on).
- **Where the events are:** 97% of rejections are at `nfa` / `nfb`, the 6973
  plate-to-grid feedback nodes (47K into 20 pF: ~0.94 us against the 5.2 us
  step), each time a 6973 grid clamps.
- **Where a step's time goes** (cycle counts, `--features timing`): devices 27%,
  factorizations 14%, the rest of the iterations 18%, stage linear algebra 21%,
  per-step linear algebra 19%. The linear algebra grew with the state (86 rows)
  and the 250 unknowns every step computed three times (step base, end point,
  error estimate) while a render reads 14 probes.

What went in (`transient.rs`, `dk.rs`, `linalg.rs`):

- **Step selection** (`Options::step_selection`, default on;
  `Transient::advance_selected`): a rejected step is redone at the level its
  error ratio predicts (h^4 scaling, target 0.5), at least one deeper; after an
  accepted substep the next coarsens by up to 2 levels when its ratio predicts
  < 0.8 and the substep grid allows; the next sample starts at the level the
  last substep chose. Rejections drop 4x (13.7k -> 3.4k on the clip second);
  accepted substeps rise (30.8k -> 40.1k): the total attempts barely move
  (223k -> 218k), but the level switches stop refactoring stale Jacobians
  (1.22 -> 1.08 factorizations per sample). Its constants barely matter (a
  sweep of the targets and the coarsening limit: within 1% of the attempts and
  0.6 dB). `Stats::{accepted,rejected}_by_level` count steps per level.
- **The ports-and-states error norm** (`Options::error_norm`, production
  `ports_states` in sim_settings): the estimate is measured on the device port
  voltages and the state nodes; the other nodes are algebraic in those. With it
  a DK step computes only the probes' unknowns (`Options::all_unknowns`;
  the Python binding always keeps only the probes; the DK systems put them
  first in their unknown block), and the estimate only on ports and states:
  per-step linear algebra 19.8% -> 12.4% of the run. Same accuracy (-79.9 vs
  -79.2 dB on the clip second). `Transient::update` refuses a probes-only run.
- **AVX2** for the matrix-vector products and the port matrix's LU, detected at
  run time like the 6386 sections: the same scalar loops 4 lanes wide, no fused
  multiply-add, bit-identical results (tested; and outputs `cmp`-identical):
  6-10%.

Speed (one job at a time, best of three back to back; "before" is the same
binary's old paths: halving, every node, every unknown, SSE2): **1 s of the clip
20.9x -> 16.6x real time (1.26x faster), 1 s of the TC1 burst 22.1x -> 19.1x
(1.16x)**. The remaining levers are M5's (the 6386 sections' exponentials, the
reuse thresholds) and the stage linear algebra (86 states); the 10x target over
ngspice stays deferred.

Found on the way:

- **The error estimate misses a diode turning off within a step.** An RC clamped
  by two steep diodes, with a 1 us node behind it, at 2x 96 kHz: 17 mV off the
  converged solution at the knee (8x, 16x and trapezoidal at 64x agree to
  0.3 mV there), and the estimate never asks for a substep: it uses the end
  point's Jacobian, after the diode has switched. The 670's events are caught
  (their kinks reach the 1 us feedback nodes), so production meets its rows; a
  circuit whose error sits only at a switching junction may not be.
- **DK with Jacobian reuse vs full MNA** on the sidechain driven 9 dB harder
  (T103 at 8.5): a decision can move without changing the number of substeps
  (0.55 V at `nfb` for one sample at a grid clamp; the CV within 0.3 mV).
  `tests/dk.rs` now compares reuse runs with error control in error-tolerance
  units always (measured <= 45; bound 100), the CV within 10 mV; exact Newton
  still agrees within 0.14 Newton tolerance everywhere, with the same decisions,
  under both controllers and both norms. `tests/control.rs`: both controllers on
  the 670 against its converged solution (-101 dB each), probe-only runs
  bit-identical to full ones, `update` refused without every unknown.
- **ngspice can stop at its first step depending only on the input's chunking**
  (`varimu.sim.io.run_transient`): at the default front panel, 4 and 4.5 s
  renders stopped at t = h / 100 at a bridge diode on T104's floating
  secondary, whatever the input, method (gear too), rshunt (1e10), gmin, or
  added capacitance on the secondary; 3.5 s renders, and the same input split
  into 200k- or 1M-line filesources, ran. A run that stops within its first
  sample is retried once with another split.

**Milestone order after M6 (decided 2026-10-21; main plan Phase 2 done the
same day, and M7 / M8 stay deferred after it: nothing in main-plan Phases
3-5 needs them; next is main-plan Phase 3).** The simulator is fast
enough to listen with (5-7x faster than ngspice) and more accurate than the
model it runs: the slice's transformers are still linear placeholders with
provisional parasitics, whose error dwarfs a -55 dB numerical one. So the
main plan's **Phase 2 (transformer models) comes next**, and M7 (a second
circuit) and M8 (real time) wait until Phase 2 is done; M5's speed target
stays deferred. Phase 2's nonlinear core is engine work in circuitsim (a
device with state, which the device trait has carried since M3) and lands
as part of Phase 2. After Phase 2, rerun the M4 method study (its item 5:
the ~17 kHz resonance that chose esdirk4 at 2x comes from provisional
winding capacitances).

**M7. Beyond the 670.** (Deferred until main plan Phase 2 is done; see
"Milestone order after M6" above. Since 2026-10-25 it is the device builder
plan's B2, after B1's generic circuit format: docs/DEVICE_BUILDER_PLAN.md.
*Done 2026-10-26 as B2: the Pultec EQP-1A on both engines, ngspice agreement
-67 dB at k = 8 with tabulated triodes, no engine changes; new devices 12AU7, 6X4.*) Device library growth, and a second circuit as proof
of generality: a passive tube EQ (LC network plus tube make-up stage), with
its own sourced YAML and ngspice agreement tests. Then BJT, JFET, op-amp and
opto-cell models as circuits need them.
*Done when:* the EQ circuit runs on both engines with agreement tests, without
engine changes beyond new device models.

**M8. Real-time readiness.** Allocation-free `process(block)` API, control-rate
parameter updates with smoothing, decimation in Rust, latency and CPU budget
measured. This hands over to main plan Phase 10.
*Done when:* a benchmark processes audio in real time on one core with knob
changes, and the output matches offline renders.

*A first look at a draft mode (2026-10-27, `scripts/draft_settings_study.py --fresh
--repeat 2`, no engine changes; `reports/realtime/draft_study.json`).* Cheaper settings,
one lever at a time, against production on 3 s excerpts (two each), timed on an idle
desktop, best of 2-3 runs (x = slower than real time per simulated second, the 1 s of
settling counted as audio; null re signal; the 670's CV has a mean of -60 to -77 V):

| setting | EQP-1A x | EQP-1A null | 670 x | 670 null | 670 CV rms |
|---|---|---|---|---|---|
| production | 2.6-3.0 | | 13.8-17.7 | | |
| error control off | 2.4-2.6 | identical | 11.8-13.4 | -62 / -73 dB | 0.006-0.015 V |
| + 48 kHz | 1.3-1.4 | -52 / -68 dB | 7.6-8.7 | -54 / -61 dB | 0.02-0.04 V |
| + TR-BDF2 | 0.7-0.8 | -47 / -60 dB | 4.1-4.4 | -54 / -58 dB | 0.025-0.036 V |
| + trapezoidal, loose Newton | 0.5 | -43 / -55 dB | 2.5-2.9 | -43 / -50 dB | 0.09-0.14 V |
| + 1x oversampling | 0.2-0.3 | -27 / -41 dB | 2.1-2.4 | -36 / -38 dB | 0.17-0.24 V |

Octave bands stay within 0.4 dB of production down to trapezoidal at 2x; 1x loses 1-2 dB
(the top octave) and gains the 670 only ~1.2x. The EQP-1A runs faster than real time on
settings alone (48 kHz with TR-BDF2: 1.3x headroom; trapezoidal: 2x). The 670 is 3-4x
faster and still 2.5-4.4x short, which leaves the structural levers: one port per
paralleled 6386 bank (exact), tabulated tube models, the idle channel 2 at its operating
point, and (the user's call: the one-coupled-simulation rule) a slower rate for the
supplies. Not yet listened to. (A first run under a full test suite's load read 2-8x
slower.)

**Draft quality (2026-10-27).** Asked for: the 670 in real time on one core at 48 kHz,
2x, TR-BDF2, no error control, with headroom (0.5-0.7x), within ~-45 dB of production
and the CV within ~0.1 V rms; production unchanged.

*Where the time went.* `examples/bench.rs` (now with the draft's settings as environment
variables, `--features timing` in us per step, and partitioned runs) on the study's two
670 excerpts at 48 kHz, 2x, TR-BDF2: **44 us per step against the 10.4 us of real time**
at that 96 kHz internal rate: devices 35%, factorizations 25% (0.93 per step), the rest
of the iterations 19%, stage linear algebra 15%. So the target needed 6-9x, not the
2.5-4.4x the settings table suggests. Of the handoff's levers:

- *One port per paralleled 6386 bank* was already in: `mna.rs` merges stateless devices
  on the same pins into a `Parallel` since Phase 3 (the 45 ports are after it).
- **Tube tables** (`devices/triode_table.rs`, `Options::tube_tables`): every Koren
  section factors exactly into `(Vp/Kp)^Ex Phi(u)`, `u = Vg / sqrt(Kvb + Vp^2)`, so all
  sections sharing (Kp, Ex, Kvb) (a 6386's 32, a bank's 128: mu and Kg1 carry the
  per-tube spread) are one 1-D function: ln Phi as a cubic Hermite through its exact
  values and slopes at spacing 0.05/Kp; below the grid every section is in its
  exponential tail and ln Phi is linear (exact); above u = 0.5 the exact sections.
  Within 9e-8 of the exact model over the 670's range (`tests/devices.rs`), -118 dB
  from it on the 670; a bank costs ~1 lookup instead of 128 sections. 43 -> 37 us.
- *The reuse thresholds* (THETA_REFACTOR / THETA_MAX) are at their optimum: looser
  ones trade factorizations for iterations (37-42 us, and -63 dB at 1.0 / 0.95).
- *Why the 670 refactors so often:* the sidechain bridge (DCR101-104 on T104's floating
  secondary) is the worst port in 95% of the slowly contracting iterations and has all
  the junction limiting: diodes switching against a stale Jacobian, coupled to the 6973s
  through T104. Tried and dropped: a current convergence test for ports whose current
  doesn't move (accepting on current alone diverges at DV304; capped at 0.1 V it saves
  1.5%), and **low-rank (Woodbury) refactors** of just the devices whose Jacobian moved
  (15.5-20 us instead of 13: the rest of the matrix goes stale, 5-12k exact retries).
- *The 45 x 45 LU* runs at ~1 multiply-add per cycle (8.9 us); a left-looking,
  4-updates-per-pass version (same arithmetic) was no faster, nor were AVX2 or FMA on
  the kernel alone; the 22 x 22 solve (0.45 us) is latency-bound. Kernel work is worth
  ~1 us per step at most; not done.

*Speed ceilings of the model-level options* (the user's decisions; timing-only IR
variants, draft settings with tables): channel 2's devices out of Newton -12%; every
supply as an ideal rail -51% (and still 1.8x short: the audio path and sidechain alone
are 18.9 us); the JA cores in their linear limit (`cores: linear`, as ngspice runs them)
-21% at -54 dB / CV 0.03 V from the JA draft; all three 13.3 us (TR-BDF2, 1.27x) and
10.6 us (trapezoidal, 1.01x). So one core can't reach the target with TR-BDF2 at this
rate even with every option. The user allowed two cores and left the model choices to
a recommendation: the cores' linear limit (yes), channel 2 linearized (no: small), the
supplies on a second core (yes, measured below).

- **Partitioned runs** (`partition.rs`, `Mna::externals` / `outputs`,
  `Transient::with_externals` / `set_externals`): the IR's sections split by title, the
  named ones (power supply, bias supply, the idle channel 2) on a second thread. At each
  shared node (the six rails) the first partition sees a voltage source at the second's
  voltage, the second a current injection, the first's source current; both start at
  the whole circuit's DC point and step in lockstep, each with the other's values from
  the end of the previous sample, extrapolated linearly over the sample (the rows are
  "externals": sources whose values the caller sets per sample, a DK response column
  each, like the mains' sine sources). The schedule is fixed, so results don't depend on
  timing (bit-identical runs, tested). **-103 dB / CV 0.1 mV from the one solve** on the
  arpeggio (held values: -90 dB; `tests/partition.rs`: -114 dB on a 0 dBFS tone). It
  bends "one coupled simulation" for the draft only: still one circuit, its supply rails
  coupled explicitly with 10 us of latency, against millisecond rail dynamics. Splits
  through the signal path don't work: at T104's secondary the first side's source closes
  a loop with the windings (singular DC), at a 6973 grid the second side has no DC path,
  and with the 12BH7 in the second partition the lagged coupling diverges in 29 samples.
  The supply side alone is 4.8 us per step (0.04 factorizations: the refactors are all
  the audio side's), so the first partition sets the pace.
- *Loose Newton* (1e-3 / 1e-2 V, a solver setting): -74 dB / CV 4 mV from production's
  tolerances on the draft, 11% faster (3e-3 / 3e-2: -38 dB, rejected).

Bench, 48 kHz 2x TR-BDF2, linear cores, tables, loose Newton, supplies on a second
thread: **1.18x (arpeggio) and 1.10x (mix) slower than real time** (12.3 / 11.5 us per
step; the audio thread alone with ideal rails 11.3 us: devices 2.1, factorizations 2.1,
iterations 2.2, stage algebra 2.5, step algebra 1.3, other 1.2). The supply thread
spins between samples (yielding sooner costs 4%).

*Exposed as a quality* (the user's choice): `circuitsim_draft` in sim_settings.yaml on
top of `circuitsim`, `--quality draft` on `render`, `unit` and `listen` (sets
`$VARIMU_QUALITY` for the process; `TransientSettings.from_sim_settings(quality=...)`;
callers that name an engine stay production), and a production / draft selector on the
listen page and in the editor's listen panel (per render job). Offline the draft runs at
the project's 96 kHz at 1x: the same 96 kHz internal rate and cost as a 48 kHz host at
2x, without resampling every caller's input. Draft renders cache apart (the settings
are in the key). Production is untouched: every new option is off in it, and the DK
path computes the same numbers (the source rows generalize the sine sources' columns).

The draft study with the new rows (`draft_settings_study.py --fresh --repeat 2`,
2026-10-27; x per simulated second, settling counted; null and CV against production;
the 670's arpeggio / mix, the EQP-1A's drums / mix):

| setting | 670 x | 670 null | 670 CV rms | EQP-1A x | EQP-1A null |
|---|---|---|---|---|---|
| production | 18.1 / 13.7 | | | 2.6 / 2.9 | |
| 48 kHz TR-BDF2 (as above) | 4.3 / 4.2 | -54 / -58 dB | 0.036 / 0.025 V | 0.7 / 0.8 | -47 / -60 dB |
| + tube tables | 3.8 / 3.5 | -54 / -58 dB | 0.036 / 0.025 V | 0.7 / 0.8 | -47 / -60 dB |
| + loose Newton | 3.3 / 3.0 | -54 / -58 dB | 0.039 / 0.025 V | 0.6 / 0.7 | -47 / -60 dB |
| + linear cores | 2.6 / 2.3 | -52 / -54 dB | 0.039 / 0.057 V | 0.5 / 0.4 | -46 / -58 dB |
| + supplies on a 2nd thread (48 kHz 2x) | 1.2 / 1.2 | -52 / -54 dB | 0.041 / 0.057 V | 0.3 / 0.3 | -46 / -58 dB |
| **draft quality (96 kHz 1x)** | **1.2 / 1.2** | **-52 / -55 dB** | **0.042 / 0.054 V** | **0.3 / 0.3** | **-48 / -58 dB** |

Octave bands within 0.03 dB on the 670 and 0.25 dB on the EQP-1A. The draft at 96 kHz 1x
matches the real-time configuration (48 kHz 2x) in speed and sound. So: the 670 11-15x
faster than production, within -52 dB of it, its CV within 0.06 V rms; the EQP-1A 3x
faster than real time (it only moves its power supply to the second thread).

*Draft-1x (2026-10-27, the user's request: while playing, a ballpark is enough; the
final render is production).* `--quality draft-1x` (sim_settings `circuitsim_draft_1x`
on top of the draft): a 48 kHz host at 1x, so a 48 kHz internal rate.
`TransientSettings.host_rate` makes it hearable in the 96 kHz project: the engine
resamples a render's input to the host rate and its outputs back (`fast.run_transient`).
Same study, fresh, best of 2:

| quality | 670 x | 670 null | 670 band | 670 CV rms | EQP-1A x | EQP-1A null | EQP-1A band |
|---|---|---|---|---|---|---|---|
| draft | 1.2 / 1.13 | -52 / -55 dB | 0.03 dB | 0.042 / 0.054 V | 0.32 | -48 / -58 dB | 0.25 dB |
| draft-1x | **0.86 / 0.81** | -49 / -45 dB | 0.3 / 0.7 dB | 0.061 / 0.068 V | 0.16 | -33 / -46 dB | 2.6 / 1.0 dB |

**The 670 runs faster than real time on two cores at draft-1x** (0.81-0.86x, ~20%
headroom), within about -45 dB of production and its CV within 0.07 V rms; the top
octave is where 1x shows (up to 0.7 dB on the 670, 2.6 dB on the EQP-1A's drums with
its 10 kHz boost). Only 1.4x faster than the draft at half the steps: the larger step
takes more Newton iterations. Not yet listened to.

*Status.* The 670 runs in real time on two cores at draft-1x (0.81-0.86x); the draft
(2x-equivalent) is 1.1-1.2x slower than real time (the handoff's target was one core at
0.5-0.7x; M8's real-time API, smoothing and the in-Rust resampling are still to do). What's left, each a few percent to ~10%:
the small-matrix kernels (the 22 x 22 LU and solve, the iteration bookkeeping), the
partition's own ~1 us per step, and moving the sidechain bridge to the second core
(per-node coupling roles: T104's floating secondary must receive current, not voltage;
its speed ceiling couldn't be measured cheaply, since the sidechain without its bridge
runs unloaded). Listening to production against the draft in the blind A/B page comes
next, with the user.

Phase 2's nonlinear transformer core lands in circuitsim when Phase 2 does,
not in ngspice (decided 2026-10-21, Open decisions). The device trait
carries state from M3 so that isn't a redesign.

## Risks

| Risk | Mitigation |
|---|---|
| Newton fails to converge (diodes, tube cutoff, grid conduction onset) | Limiting, substeps, previous-step extrapolation; failures report time and device |
| Trapezoidal ringing on stiff modes | Oversampling; TR-BDF2 or backward Euler switch |
| Ill-conditioned matrices (k = 0.999 coupling, MOhm and Ohm in one circuit) | Inductance-matrix formulation; scaled unknowns; f64 throughout; condition numbers checked in tests |
| The engines drift apart as the circuit evolves | One IR feeds both; agreement tests in the default test run |
| DK recomputation too slow for real-time knob moves | Control-rate updates; precompute per switch position; crossfade |
| Windows toolchain friction (MSVC linker vs Git's `link.exe` on PATH, maturin builds) | Pin the commands in CLAUDE.md; build through `cargo` / `maturin`, which find MSVC themselves |
| Effort grows with each new device | Library grows only as circuits need devices; every device has the same three-way test pattern |

## Open decisions

- **Crate name.** `circuitsim` is a placeholder.
- ~~**Fixed vs adaptive step.**~~ Decided in M4: a fixed output grid at 2x
  with local, error-controlled substepping (steps halved only where the
  embedded error estimate asks). Still open for real time (M8): substepping
  makes the cost per block vary (2.7 substeps per sample on the hardest
  test signal); a fixed 4x without error control is the fixed-cost
  fallback.
- ~~**Sparse vs dense.**~~ Decided in M3: dense, with the linear unknowns
  eliminated once per step size so Newton refactors only the device-node
  block (see M3's status).
- **Which EQ for M7.** It must have a published schematic so values are
  sourced.
- ~~**SPICE implementations of new devices**~~ (raised 2026-10-21, the user's
  call). *Decided 2026-10-21: the hysteretic core has the Python reference
  and circuitsim, with tests that they agree, and no SPICE implementation;
  ngspice cross-checks the rest of the circuit with the core in its linear
  limit in both engines (the measurements below).* The question was: The hard rule asks for a SPICE
  implementation and a Python reference of every device model. A nonlinear
  transformer core with hysteresis may be awkward and slow in ngspice (not
  yet checked: XSPICE's `core` code model, or behavioral sources with
  integrators, whose symbolic derivatives already made the 6386 B-source
  impractical). If it is, the option is: Python reference + circuitsim for
  the core, with tests that they agree, and ngspice keeps cross-checking the
  existing devices and the circuit around the core (e.g. with the core
  replaced by its linear limit in both engines).

  *Measured 2026-10-21 (scratch study, the session's scratch directory).* Test: a voltage source and 10 Ohm drive one winding
  (500 turns, 1 cm^2, 10 cm path) on a Jiles-Atherton core (Jiles, Thoelke,
  Devine 1992 form), two scratch parameter sets (steel-like: Ms 1.45e6, a 50,
  k 40 A/m; nickel-like: Ms 6e5, a 4, k 2 A/m; provisional: model
  knowledge). Reference: the circuit's ODE in Python with every direction
  and irreversible-gate switch located as an event, DOP853 at rtol 1e-11.
  Signals: 1 kHz tone, a 30 Hz ramp into saturation, 30 Hz plus a 3 kHz tone
  that reverses H mid-loop (minor loops), 80 V switch-on inrush, a DC step.
  Settings: production (trap, reltol 1e-3, 2x) and reference (gear, 1e-4, 4x).

  | ngspice route | loop | vs JA reference | cost per timepoint | robustness |
  |---|---|---|---|---|
  | XSPICE `lcouple` + `core`, PWL mode | anhysteretic B(H) only, no memory | -27 dB (another model) | 3.5-7 us | fine |
  | XSPICE `core`, HYSTERESIS mode | the generic `hyst` block: a parallelogram (linear ramp, hard limits, +-hyst by direction); minor loops collapse onto a line | -0.5 dB on minor loops | 3.5-7 us | fine |
  | B-sources, `ddt()` for dH/dt | JA | diverges (1 kHz tone) | | |
  | B-sources, state in 1 F capacitors (M integrated, dH/dt sensed by a capacitor), hard `sgn`/`u` switching | JA | prod / ref: tone -71 / -77 dB, minor loops -62 / -67, saturation -94 / -95, inrush -84 / -90 (steel); nickel -58 to -85 prod, -67 to -93 ref | 57-91 us (nickel inrush 190 us at prod) | DC step into saturation fails at the reference settings: "timestep too small" at the dH/dt sensor (steel), no progress in 300 s (nickel); production settings pass |
  | same, irreversible gate smoothed (tanh) | JA, smoothed | minor -60, saturation -80 (the smoothing changes the model) | 72-130 us | also hangs on the DC step at ref |

  In the 670 (four such cores appended, driven near the knee plus 1 kHz, 0.5 s
  of the burst): **production ngspice goes from 29x to 291x slower than real
  time**, ~5x more than the per-timepoint cost alone (the cores' direction
  switches cut the shared timestep); with exact triodes at the reference
  settings, 713x vs 650x (no change: the step is pinned at 4x and the exact
  triodes dominate). Not tested: a Verilog-A core compiled to OSDI with
  OpenVAF (ngspice 47 has the adapter; OpenVAF is a separate download). It
  would evaluate faster than B-sources but share the timestep and the
  direction-switch problem.

## References

- D. T. Yeh, *Digital Implementation of Musical Distortion Circuits by
  Analysis and Simulation*, PhD thesis, Stanford University, 2009 (nodal DK
  method).
- D. T. Yeh, J. S. Abel, J. O. Smith, "Automated physical modeling of
  nonlinear audio circuits for real-time audio effects, Part I: theoretical
  development", *IEEE Trans. Audio, Speech, and Language Processing* 18(4),
  2010.
- M. Holters, U. Zölzer, "A generalized method for the derivation of
  non-linear state-space models from circuit schematics", EUSIPCO 2015.
- ACME.jl, analog circuit modeling and emulation in Julia:
  https://github.com/HSU-ANT/ACME.jl
- N. Koren, "Improved vacuum tube models for SPICE simulations", *Glass Audio*
  8(5), 1996 (the triode and pentode models already in `varimu/devices/`).
