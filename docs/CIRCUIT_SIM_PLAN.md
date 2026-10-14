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

**M2. Linear engine.** MNA stamps for R, C, L, coupled inductors and sources;
trapezoidal fixed step; input and probes.
*Done when:* linear test circuits match closed form and ngspice; the 670's
transformers alone (driven by the input, tubes removed) match ngspice.

**M3. Devices and Newton (full MNA).** Device trait; triode, variable-mu triode,
grid current, pentode, diodes; Newton with limiting and substeps; DC
operating point.
*Done when:* device fixtures match Python to 1e-12; the small nonlinear
circuits match ngspice; the 670 operating point matches ngspice's `.op`.

**M4. The 670 slice on the fast engine.** Full transient with the full-MNA
solver; engine setting in the runner and cache.
*Done when:* the 670 verification rows in the table above pass, and the speed
is measured and recorded.

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
- **Fixed vs adaptive step.** The plan is fixed-step (simple, plugin-ready).
  If accuracy at 2x oversampling falls short on some circuit, the options are
  4x or local substepping, not a full adaptive scheme.
- **Sparse vs dense.** Full MNA in M3-M4 uses a sparse LU (faer). DK in M5 is
  dense and small. Decide in M3 from benchmarks.
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
