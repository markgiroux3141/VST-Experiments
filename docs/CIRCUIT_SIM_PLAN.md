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
  src/dk.rs                state-space derivation (M5)
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
| 670 slice | vs the ngspice reference used in the tolerance study (gear, reltol 1e-4, 4x) on the burst and a program clip | output < -55 dB re signal; CV within 0.2 V |
| 670 behaviour | compression curve and Time Constant attack/release from `scripts/slice_report.py` | GR within 0.2 dB per step; times within 5% |
| Stability | idle circuit quiet (same as `tests/test_slice.py`) | |
| Speed | criterion benches and the existing `timing.csv` | tracked per milestone |

Fixtures come from Python, so the Python models stay the single source of
truth. Python tests call the binding on the same circuits ngspice runs.

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

**M6. Default engine.** The listen app and renders use the fast engine. ngspice
stays for verification (a setting, plus a periodic agreement test).
*Done when:* the done-when renders from the slice handoff (compression curve,
TC bursts, a program clip) reproduce on the fast engine within the
verification tolerances.

**M7. Beyond the 670.** Device library growth, and a second circuit as proof
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

Phase 2's nonlinear transformer core lands in both engines when Phase 2 does.
The device trait carries state from M3 so that isn't a redesign.

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
