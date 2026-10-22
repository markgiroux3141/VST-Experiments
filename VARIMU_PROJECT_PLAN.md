# Vari-Mu: A Physically Modeled Fairchild-Style Compressor

## Vision

Build a physically plausible variable-mu tube compressor, modeled after the Fairchild 660/670 topology, whose character **emerges from circuit physics** rather than being designed in as DSP effects. There is no reference hardware, so the goal is not to clone a specific unit. The goal is a simulation faithful enough that the interactions between tubes, transformers, power supply and sidechain produce the "magic" on their own.

On top of the simulator sits a human-in-the-loop optimization system. The developer A/B-tests candidate units by ear, a preference model learns their taste, and an evolutionary search explores the space of physically realizable units to find ones they love. The end product may be a single "definitive" unit, a palette of distinct characters, or both, and eventually a real-time model (neural or wave digital filter) suitable for a plugin.

## Guiding Principles

1. **One coupled simulation.** Emergence requires coupling. The audio path, sidechain and power supply must live in the same circuit simulation, never as separately chained DSP blocks.
2. **The genome is physical.** Optimization only ever varies physical parameters (tube emission, pair mismatch, core material, winding capacitance, PSU impedance, tolerances), each bounded to physically plausible ranges. No EQ curves, no saturation knobs, nothing a real unit couldn't have.
3. **End-to-end early, fidelity later.** Get a crude but complete loop working (simple models → simulation → listening → preference → optimization) before deepening any one stage. Fidelity is increased incrementally, and each increase is checked against the measurement suite.
4. **Loudness lies.** Every listening comparison is matched for both output loudness and amount of gain reduction. Louder and "more compressed" always win otherwise.
5. **Never fabricate data.** Component values come from the published schematics and datasheets. Where a value is unknown, it becomes a bounded genome parameter with its range documented, not a guess presented as fact.

## System Overview

```
 ┌────────────────┐    ┌───────────────────┐    ┌──────────────────┐
 │ Device models  │───▶│ Netlist generator │───▶│ Simulation runner│
 │ (tubes, xfmrs) │    │ (genome → SPICE)  │    │ (Xyce / ngspice) │
 └────────────────┘    └───────────────────┘    └────────┬─────────┘
         ▲                      ▲                        │
         │                      │                        ▼
 ┌───────┴────────┐    ┌────────┴──────────┐    ┌──────────────────┐
 │ Field solve /  │    │    Optimizer      │    │ Measurement suite│
 │ PIC (optional) │    │ (PBO / CMA-ES /   │    │ + audio renders  │
 └────────────────┘    │   MAP-Elites)     │    └────────┬─────────┘
                       └────────┬──────────┘             │
                                ▲                        ▼
                       ┌────────┴──────────┐    ┌──────────────────┐
                       │ Preference model  │◀───│ Listening app    │
                       │ (Bradley-Terry)   │    │ (blind A/B)      │
                       └───────────────────┘    └──────────────────┘

        Surrogate simulator (neural, conditioned on genome) is trained
        from simulation runs and stands in for the full sim during search.
```

## Repository Layout

```
varimu/
├── CLAUDE.md                  # Points to this plan; conventions for Claude Code
├── PLAN.md                    # This file
├── pyproject.toml
├── config/
│   ├── genome_bounds.yaml     # Every physical parameter, its range, and its source
│   └── sim_settings.yaml      # Timestep, tolerances, sample rates
├── data/
│   ├── datasheets/            # Digitized tube curves (CSV) with provenance notes
│   ├── test_signals/          # Generated bursts, sweeps, multitones
│   ├── clips/                 # Program material (user-owned recordings only)
│   └── judgments/             # Listening results (SQLite)
├── varimu/
│   ├── devices/
│   │   ├── triode.py          # Koren model + variable-mu extension, grid current
│   │   ├── fit.py             # Fitting device models to digitized curves
│   │   └── transformer.py     # Transformer parameter sets → SPICE subcircuits
│   ├── circuit/
│   │   ├── netlist.py         # Genome → full netlist
│   │   ├── subcircuits/       # .lib / .sub files, one per stage
│   │   └── psu.py             # Power supply section
│   ├── sim/
│   │   ├── runner.py          # Launch Xyce/ngspice, parallel jobs, caching
│   │   └── io.py              # Audio ↔ PWL sources, raw output → WAV
│   ├── measure/
│   │   ├── signals.py         # Test signal generation
│   │   ├── metrics.py         # Compression curve, attack/release, THD, IMD, thump
│   │   └── plausibility.py    # Sanity checks that reject broken units
│   ├── listen/
│   │   ├── app.py             # Local blind A/B web app
│   │   └── matching.py        # Loudness + gain-reduction matching
│   ├── prefs/
│   │   ├── features.py        # Audio embeddings + handcrafted features
│   │   ├── model.py           # Bradley-Terry ensemble
│   │   └── active.py          # Uncertainty-based pair selection
│   ├── surrogate/
│   │   ├── dataset.py
│   │   └── model.py           # Neural sim surrogate conditioned on genome
│   ├── optimize/
│   │   ├── pbo.py             # Preferential Bayesian optimization
│   │   ├── cmaes.py
│   │   └── map_elites.py      # Quality-diversity search
│   └── physics/               # Optional Phase 9: field solve / PIC
└── tests/
```

## Suggested Tech Stack

| Area | Choice | Notes |
|---|---|---|
| Language | Python 3.11+ | Orchestration, analysis, ML |
| Circuit sim | Xyce (primary), ngspice (fallback) | Xyce has parallel solving and a nonlinear magnetic core model based on Jiles-Atherton; verify current feature support |
| Numerics | numpy, scipy | Fitting, signal processing |
| Audio I/O | soundfile, resampy or soxr | |
| Loudness | pyloudnorm | LUFS matching |
| ML | PyTorch | Preference model, surrogate, real-time model |
| Embeddings | LAION-CLAP or OpenL3 | Pretrained audio features for the preference model |
| Optimization | BoTorch (preferential BO), `cma`, `pyribs` (MAP-Elites) | |
| Listening app | FastAPI + minimal HTML/JS, or Gradio | Keyboard shortcuts for fast A/B |
| Storage | SQLite | Judgments, run metadata, cache index |
| Magnetics FEM (optional) | FEMM via pyfemm, or Elmer | Transformer core modeling |
| Electron physics (optional) | WarpX, or a custom 2D Poisson + Child-Langmuir solver | Phase 9 only |

## Phases

Each phase lists its goal, tasks and a "done when" criterion. Do not start a phase until the previous one meets its criterion.

### Phase 0: Scaffolding and Test Signals

**Goal:** Project skeleton, configuration system and a deterministic test signal library.

- Set up the repo layout, `pyproject.toml`, test runner and a `CLAUDE.md` with conventions.
- Generate test signals at 96 kHz:
  - tone bursts at multiple levels and frequencies (attack/release measurement)
  - exponential sine sweeps (harmonic distortion via Farina's method)
  - SMPTE and CCIF twin-tone signals (IMD)
  - stepped-level sine series (static compression curve)
  - silence followed by bursts (thump measurement)
- Write `genome_bounds.yaml` as an initial skeleton; it fills in during Phases 1–3.

**Done when:** Signals generate reproducibly from a seed and tests pass.

### Phase 1: Device Models

**Goal:** Compact models for every active device, fit to real published data.

**6386 variable-mu triode (most important device in the project):**

- Digitize the RCA 6386 datasheet curves (plate characteristics, transconductance vs grid bias) into CSV with provenance notes.
- Start from the Koren triode model:

  ```
  E1 = (Vp / Kp) * ln(1 + exp(Kp * (1/mu + Vg / sqrt(Kvb + Vp^2))))
  Ip = (E1^Ex / Kg1) * (1 + sign(E1))
  ```

- Extend it to variable-mu by modeling the tube as N parallel triode sections, each with its own mu and a weight representing its share of the cathode area. This mirrors the physical variable-pitch grid:

  ```
  Ip_total = Σ w_i * Ip(Vg, Vp; mu_i, ...)    with Σ w_i = 1
  ```

- Fit N (start with 3–5), the mu values and the weights to the datasheet. The transconductance-vs-bias curve matters most, because it *is* the compression law.
- Add grid current (a diode-like conduction above a contact-potential offset) and interelectrode capacitances from the datasheet.

**Other devices:** sidechain amplifier tubes, rectifier diodes and power supply rectifiers. Standard Koren-family models are fine here, also fit to their datasheets.

**Outputs:** SPICE subcircuits (behavioral sources) plus a Python reference implementation of each model, tested against each other.

**Done when:** Each model's plate curves and the 6386's gm-vs-bias curve match the digitized data within a documented error, and the Python and SPICE implementations agree.

### Phase 2: Transformer Models

**Goal:** Lumped transformer models with hysteresis, leakage and parasitics for every transformer in the topology (input, interstage, output, sidechain).

- Each transformer subcircuit includes:
  - a nonlinear magnetic core (Jiles-Atherton via Xyce's core model, or a behavioral implementation)
  - leakage inductance, winding resistance and interwinding/self capacitance
  - optionally, a Cauer ladder for frequency-dependent eddy-current loss
- Core material, air gap, turns ratio, leakage and capacitance become genome parameters with bounds drawn from literature on vintage audio transformers. Document each range's source in `genome_bounds.yaml`.

**Done when:** Each transformer, tested standalone, shows plausible frequency response, low-frequency saturation with rising level, and a visible hysteresis loop.

**Starting Phase 2 (notes from 2026-10-21; the circuit-sim plan's M6 status has the details):**

- The engines are now circuitsim (`crates/circuitsim`, the default for renders) and ngspice (the reference); Xyce isn't used. "Xyce's core model" above becomes: the core as a circuitsim device with state, plus its Python reference.
- **First, before any modelling:** the circuit-sim plan's "M6 follow-up" (rework `slice_report.py --verify` around exact-formulation ngspice excerpts), so the agreement test is trustworthy once the circuit starts changing. *Done 2026-10-21* (cold run ~6 min; numbers in the circuit-sim plan's M6 follow-up).
- *Measured 2026-10-21 for the decision below* (circuit-sim plan, Open decisions): XSPICE's `core` can't express a Jiles-Atherton core (its hysteresis mode is a fixed parallelogram whose minor loops collapse); a behavioral JA core (B-sources with capacitor integrators) agrees with a Python reference to -62 to -95 dB, but four of them make production ngspice on the 670 10x slower (29x -> 291x real time), and a DC step into saturation fails at the reference settings. *Decided by the user 2026-10-21:* the core gets the Python reference and a circuitsim device with tests that they agree, no SPICE implementation; ngspice cross-checks everything else with the core replaced by its linear limit in both engines; the nonlinear core is judged against circuitsim's converged solution and analog behaviour.
- **First decision of the phase (the user's):** whether the core also gets a SPICE implementation, as the hard rule asks. Check what ngspice can express (XSPICE `core` code model, or behavioral sources with integrators) and at what speed and robustness, then bring the user the options: keep the rule, or Python reference + circuitsim for the core with ngspice cross-checking everything else. See the circuit-sim plan's Open decisions.
- Accuracy is judged against circuitsim's converged solution and analog behaviour (frequency response, saturation, the hysteresis loop itself, aliasing of the core's harmonics); ngspice is the cross-check for bugs (circuit-sim plan, Verification).
- The slice's current transformers are linear with provisional winding capacitances and core loss (`config/circuits/fairchild_670.yaml`); they cause the ~17 kHz resonance that drove the fixed-step method choice. When Phase 2's models replace them, rerun the circuit-sim plan's M4 method comparison (and `tests/test_slice.py`'s idle stability), and re-run `--verify`.
- Circuit-sim M7 (second circuit) and M8 (real time) wait until Phase 2 is done; M5's speed target stays deferred.

*Status (2026-10-21): done.* What exists:

- **The core:** the Jiles-Atherton model (effective-field form) as a rate-independent circuitsim device with state (`crates/circuitsim/src/devices/core.rs`) and its Python reference (`varimu/devices/core.py`), tested to agree (fixtures to 1e-12; circuits against an exact Python solution, -79 to -95 dB). No SPICE implementation (the decision above); ngspice runs the cores' linear limit. The engine side is in the circuit-sim plan, "Phase 2 in circuitsim".
- **Materials** (`config/magnetics.yaml`): grain-oriented silicon steel (a published JA fit of H75-23 transformer steel, for the replacements' M6), MUMETALL (fitted here to its datasheet by `scripts/fit_core_material.py`: mu4, mu_max, Hc, loss within 2%), and a harder permalloy (a published fluxgate-core fit).
- **Every transformer** (`config/circuits/fairchild_670.yaml`, `varimu/circuit/netlist.transformer`): windings with DC resistance, leakage inductance and self-capacitance on one core with its joint gap and classical eddy loss; balanced interwinding capacitance (nominal 0, screened). Material choice, core area and path, gap, turns, leakage and capacitances are genome parameters (`genome_bounds.yaml`), provisional where nothing is published, the turns derived so the small-signal inductance is the slice's former value, and checked against the 670's published specs (T102 saturates near +27 dBu at 30 Hz; clipping is specified at +27 dBm, <1% THD to +18 dBm). Winding resistances stay TBD (provisional values in the circuit).
- **Done when** (`tests/test_transformers.py`, `scripts/transformer_report.py` -> `reports/transformers/`): each transformer standalone (the slice's own source and load impedances, tubes as resistances), re 1 kHz at 40 Hz / 15 kHz: T101 -0.29 / +0.60 dB, T102 -0.33 / -0.32 dB, T103 -0.26 / +1.02 dB, T104 -6.6 dB (pentode drive without the slice's feedback; flat from 300 Hz) / -0.04 dB; 30 Hz THD rising with flux to 12-17% past saturation (1 kHz below 0.05%); B-H loops with coercivity, minor loops.

Findings that change later work:

- **ngspice and the new transformers.** Three SPICE emissions of the linear-limit windings stopped ngspice on the 670; what runs is coupled inductors with the leakage folded in, eddy loss as a shorted turn, and `rshunt=1e12`. The device-stripped 670 no longer runs in ngspice's transient, so "transformers alone" are tested standalone.
- **The 30 kHz tuned-plate tuned-grid mode** is still there under the old loss resistors: with the classical eddy loss it is damped at the nominal values, but an unscreened interwinding capacitance (20 pF on T101 plus 50 pF on T102) made the idle slice oscillate at ~31 kHz, and T101's leakage at the slice's old k = 0.999 equivalent (20 mH) peaked +15 dB at 17.8 kHz; the nominal leakage (2.5 mH) was chosen to meet the published +-1 dB to 15 kHz. Phase 4's plausibility checks must catch oscillating genomes.
- **Mumetall's linear limit** (its origin susceptibility) is ~10x below its incremental permeability at audio levels, so the cores' JA and linear builds differ in LF response: bass-rich program compresses up to ~2 dB differently (median 0.6 dB per 50 ms on the arpeggio clip), while the 1 kHz curve and TC timings agree within 0.06 dB / 0.06%. That is the hysteresis reaching the behaviour (Coupling Checklist).
- **Rerun of the M4 method comparison** (circuit-sim plan): production esdirk4 at 2x with error control stays, -67.5 to -80 dB from the converged solution on the six excerpts; trapezoidal still needs 8-16x. Render speed with the JA cores: 5.8x / 7.3x slower than real time (7 s burst / 4 s clip), ngspice 22-27x.
- Decided 2026-10-21 (the user delegating): Phase 2's provisional choices stand (T101 leakage 2.5 mH, interwinding capacitance nominal 0, the effective-field JA form, the mumetall fit); they are genome parameters, free to move later. Next is Phase 3; circuit-sim M7 / M8 stay deferred.
- Open: a Cauer ladder for frequency-dependent eddy loss (skin effect makes the classical term wrong above ~100 Hz in high-permeability laminations); per-winding resistance bounds.

### Phase 3: Full Circuit Netlist

**Goal:** A parametric netlist generator that turns a genome into a complete, coupled compressor circuit.

- Transcribe the topology from the published Fairchild 670 schematics, one channel first. Keep every component value traceable to the schematic. Values that are illegible or ambiguous become genome parameters, not guesses.
- Required elements (these are the coupling paths that produce emergent behavior; see the checklist below):
  - the push-pull 6386 gain stage, with the control voltage applied to its grids
  - the sidechain amplifier, rectifier and Time Constant RC networks (all six positions)
  - the DC threshold and balance trims
  - **the full power supply**, shared by the audio path and sidechain, including rectifier sag and filter capacitor ripple
- Per-instance tolerance and mismatch: every resistor, capacitor and tube instance gets its own deviation drawn from the genome, so the two tubes of a push-pull pair are never identical unless the genome says so.
- Later: second channel and lateral/vertical (mid/side) mode.

**Done when:** The netlist simulates without convergence failure across the corners of the genome bounds, and the compressor visibly reduces gain as input level rises.

### Phase 4: Simulation Runner and Measurement Suite

**Goal:** Reliable, parallel, cached simulation plus objective measurements of every unit.

- Runner:
  - convert audio to PWL voltage sources, launch Xyce/ngspice jobs in parallel and convert results back to WAV
  - cache results by hash of (genome, signal, sim settings)
  - log wall-clock time per second of audio, and measure this early so later budgets are realistic
- Measurement suite, run on every candidate:
  - static compression curve (gain reduction vs input level) at each threshold setting
  - attack and release envelopes for each Time Constant position
  - THD and harmonic profile vs level and frequency, at several amounts of gain reduction
  - IMD
  - thump (output transient on bursts out of silence)
  - frequency response at several amounts of gain reduction
  - noise floor (once noise is modeled)
- Plausibility checks that automatically reject broken units: no gain reduction at all, oscillation, runaway DC, absurd distortion at nominal level, release times far outside the vari-mu range.

**Done when:** A single command takes a genome and produces a measurement report plus rendered audio clips, and the plausibility checks catch deliberately broken genomes.

### Phase 5: Listening App and Preference Data

**Goal:** A fast, fatigue-aware, bias-resistant way to collect pairwise judgments.

- Matching (critical): for each comparison, both candidates must be:
  - **gain-reduction matched:** solve for each candidate's threshold so its average gain reduction on the clip equals a target (e.g. 3 dB or 6 dB)
  - **loudness matched:** normalize outputs to the same integrated LUFS
- Protocol:
  - blind, randomized left/right assignment, keyboard-driven (A / B / "no preference")
  - occasional repeated pairs, to measure the listener's own consistency
  - a session timer that suggests a break after roughly 20–30 minutes
  - record clip, source category (vocal, drum bus, bass, full mix), gain-reduction target, response time and session ID
- Program material: only recordings the user owns or has rights to.

**Done when:** A session can be run end to end, judgments land in SQLite, and the matching is verified by measurement.

### Phase 6: Preference Model

**Goal:** A learned score that predicts which of two units the listener will prefer.

- Features: pretrained audio embeddings (CLAP or OpenL3) of the rendered clips, plus handcrafted features from the measurement suite (harmonic balance, attack/release shape, thump, spectral tilt).
- Model: a small MLP producing a scalar score, trained with a Bradley-Terry loss on pairwise outcomes. Use an ensemble so uncertainty is available.
- Optionally condition on source category, since taste likely differs by material.
- Active learning: choose the next pairs to present where the ensemble disagrees most.

**Done when:** Held-out prediction accuracy clearly beats chance and approaches the listener's own measured consistency rate (which is the realistic ceiling).

### Phase 7: Surrogate Simulator

**Goal:** A fast neural stand-in for the full circuit simulation, so the optimizer can evaluate thousands of candidates.

- Dataset: a few thousand full simulations across the genome space (Latin hypercube or Sobol sampling), on short clips and test signals.
- Model: a neural audio model (e.g. a temporal convolutional network or recurrent network) conditioned on the genome via feature-wise modulation (FiLM).
- Also supervise internal signals the simulator exposes, especially the sidechain control voltage on the 6386 grids. This is a major advantage over hardware data.

**Done when:** Surrogate outputs match full-simulation outputs closely enough on held-out genomes that the measurement suite gives similar results, and the preference model ranks surrogate renders and full renders similarly.

### Phase 8: Optimization

**Goal:** Search the space of physically realizable units for ones the listener loves.

- Multi-fidelity loop:
  1. search on the surrogate, using the preference model as the fitness function
  2. re-simulate finalists with the full circuit simulation
  3. present finalists to the listener; their judgments retrain the preference model
- Algorithms (implement in this order):
  - **Preferential Bayesian optimization:** most sample-efficient when human judgments are the bottleneck
  - **CMA-ES:** robust single-objective search on the surrogate
  - **MAP-Elites (via pyribs):** quality-diversity search that keeps the best unit in each region of a "character map." Candidate behavior descriptors: harmonic warmth, program-dependence of release, thump level, low-frequency saturation. This produces a palette of distinct units.
- Guarding against reward hacking:
  - keep the listener in the loop at regular intervals
  - hard physical bounds from `genome_bounds.yaml`
  - plausibility checks from Phase 4 on every candidate
  - watch for drift toward extremes in any one feature

**Done when:** Optimized units are preferred by the listener over random plausible units in blind tests at a clearly better-than-chance rate.

### Phase 9 (Optional): Electron-Level Device Physics

**Goal:** Derive 6386 characteristics from tube geometry, adding physical grounding beyond the datasheet.

- Start with a 2D electrostatic field solve of the electrode geometry (cathode, variable-pitch grid, plate) combined with local Child-Langmuir space-charge-limited emission.
- If warranted, move to particle-in-cell (e.g. WarpX) with thermionic emission (Richardson-Dushman, Schottky lowering) and self-consistent space charge.
- Outputs feed back into Phase 1 as fitted model parameters. Grid pitch profile could then become a genome parameter.
- This is used offline only to derive device curves. It never runs during audio simulation, since tube transit times (~1 ns) make the quasi-static device model accurate at audio rates.

### Phase 10: Real-Time Model

**Goal:** A plugin-ready model of the chosen unit(s).

- Option A: a neural model distilled from full simulations of the chosen genome(s), conditioned on the front-panel controls (input, threshold, Time Constant).
- Option B: a wave digital filter or nodal DK-method implementation of the same circuit, preserving the physics directly.
- Compare A and B by measurement suite and by blind listening.

## Coupling Checklist

These are the mechanisms most likely responsible for emergent character. Verify each is present and measurable in the simulation:

- [ ] Control voltage on the same grids as the audio, so push-pull imbalance produces thump and signal-dependent asymmetry
- [ ] Shared power supply rails whose sag affects audio path and sidechain simultaneously
- [ ] Grid current that loads the timing networks, producing program-dependent attack/release
- [x] Transformer hysteresis, so low-frequency history shapes later transients (Phase 2: Jiles-Atherton cores; measurable: bass-rich program compresses up to ~2 dB differently than with linear cores)
- [ ] Per-instance tube mismatch, affecting even-harmonic balance
- [ ] Interelectrode capacitances, including Miller effect in the gain stage
- [ ] (Later) Noise sources: tube shot and flicker noise, resistor thermal noise
- [ ] (Later) Slow thermal drift of cathode emission

## Genome Specification Example

```yaml
# config/genome_bounds.yaml (illustrative structure; values to be sourced)
tubes:
  v6386_a:
    emission_scale: {min: 0.75, max: 1.05, source: "aging range, see notes"}
    mu_spread:      {min: 0.95, max: 1.05, source: "manufacturing tolerance"}
  v6386_b:
    emission_scale: {min: 0.75, max: 1.05, source: "aging range, see notes"}
    mu_spread:      {min: 0.95, max: 1.05, source: "manufacturing tolerance"}
transformers:
  output:
    core_material:  {choices: [silicon_steel, nickel_alloy], source: "TBD"}
    air_gap_mm:     {min: 0.0, max: 0.1, source: "TBD"}
    leakage_mH:     {min: TBD, max: TBD, source: "TBD"}
psu:
  source_impedance_ohm: {min: TBD, max: TBD, source: "TBD"}
passives:
  tolerance_pct: {resistor: 10, capacitor: 20, source: "era-typical tolerances"}
```

Every entry carries a `source` field. "TBD" is acceptable during development; an unsourced invented number is not.

## Risks and Mitigations

| Risk | Mitigation |
|---|---|
| Simulation too slow | Measure early (Phase 4); short clips; caching; parallel runs; surrogate for search |
| Convergence failures in SPICE | Test genome-bound corners; tune tolerances; add small parasitic resistances; log and auto-retry failures |
| Preference model learns loudness or GR amount | Strict matching in Phase 5, verified by measurement |
| Reward hacking during optimization | Physical bounds, plausibility checks, periodic human verification, diversity search |
| Listener fatigue and inconsistency | Session limits, repeated-pair consistency tracking, active pair selection |
| Surrogate errors misleading the search | Always verify finalists with full simulation |
| Invented component values | Provenance requirement in config; ambiguous values become bounded genome parameters |

## Open Decisions

- **One unit or a palette?** Preferential BO and CMA-ES aim for a single best unit; MAP-Elites yields a palette of characters. The default plan implements both and decides based on results.
- **Mono first, or stereo/lateral-vertical from the start?** Default: mono first.
- **Noise modeling:** include from Phase 3, or add after the optimization loop works? Default: add after.
- **Primary simulator:** Xyce vs ngspice, decided after Phase 2 testing of transformer core support and speed.
  - *Decided 2026-10-13:* build a fast netlist-driven simulator in Rust (`crates/circuitsim`),
    with ngspice kept as the reference engine and agreement tests between them. This pulls Phase
    10 option B (nodal DK) forward, because render speed (25-40x slower than real time on the
    670 slice) is the bottleneck for listening. Plan: [docs/CIRCUIT_SIM_PLAN.md](docs/CIRCUIT_SIM_PLAN.md).
  - *2026-10-21:* circuitsim is the default engine (circuit-sim M6), 5-7x faster than ngspice
    and closer to the converged solution. ngspice's role is now the independent cross-check
    for bugs (exact triode formulation on short excerpts) and the behaviour metrics; accuracy is
    judged against circuitsim's converged solution and analog behaviour. Whether new devices
    (Phase 2's core first) still need a SPICE implementation is open; see Phase 2's notes.

## Notes for Claude Code

- Work one phase at a time, and do not move on until the phase's "done when" criterion is met and tested.
- Keep the end-to-end loop working at all times once Phase 5 exists; fidelity improvements must not break it.
- Never invent component values, tube parameters or transformer specs. If a value can't be traced to a schematic, datasheet or cited literature, make it a bounded genome parameter and flag it.
- Every device model has both a SPICE implementation and a Python reference implementation, with tests that they agree. Exception (decided 2026-10-21): the hysteretic transformer core has the Python reference and circuitsim only; ngspice cross-checks the circuit around it with the core in its linear limit (Phase 2's notes).
- Every simulation result is cached and reproducible from (genome, signal, settings, code version).
- Prefer small, inspectable steps and plots over large untested changes; save measurement plots for every candidate so changes in character can be reviewed visually as well as by ear.
