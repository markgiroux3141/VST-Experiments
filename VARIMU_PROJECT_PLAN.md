# Vari-Mu: A Physically Modeled Fairchild-Style Compressor

## Vision

Build a physically plausible variable-mu tube compressor, modeled after the Fairchild 660/670 topology, whose character **emerges from circuit physics** rather than being designed in as DSP effects. There is no reference hardware, so the goal is not to clone a specific unit. The goal is a simulation faithful enough that the interactions between tubes, transformers, power supply and sidechain produce the "magic" on their own.

**Aim, restated (2026-10-23).** The 670's published curves, specs and parts are ground truth so the model isn't built blind: calibration anchors, not targets. When a measurement disagrees with them, the question is whether physics is missing, not how to tune toward the number. What matters is that every component's physics that shapes the sound is simulated. The end state includes designing new devices from parts (transformers, capacitors, tubes ...) and hearing how their physical properties change the sound. So plausibility checks reject what no real unit could do, not what isn't a 670.

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
- **Mumetall's linear limit** (its origin susceptibility) is ~10x below its incremental permeability at audio levels, so the cores' JA and linear builds differ in LF response: bass-rich program compresses up to ~2 dB differently (median 0.6 dB per 50 ms on the arpeggio clip), while the 1 kHz curve and TC timings agree within 0.06 dB / 0.06%. That is the hysteresis reaching the behaviour (Coupling Checklist). *Superseded 2026-10-24 (the Rayleigh refit below): the ~2 dB was the old fit's origin permeability (246) standing in for the linear limit; with the refit (29,300) JA and linear builds compress the clip within 0.022 dB (median 0.002) per 50 ms.*
- **Rerun of the M4 method comparison** (circuit-sim plan): production esdirk4 at 2x with error control stays, -67.5 to -80 dB from the converged solution on the six excerpts; trapezoidal still needs 8-16x. Render speed with the JA cores: 5.8x / 7.3x slower than real time (7 s burst / 4 s clip), ngspice 22-27x.
- Decided 2026-10-21 (the user delegating): Phase 2's provisional choices stand (T101 leakage 2.5 mH, interwinding capacitance nominal 0, the effective-field JA form, the mumetall fit); they are genome parameters, free to move later. Next is Phase 3; circuit-sim M7 / M8 stay deferred.
- Open: a Cauer ladder for frequency-dependent eddy loss (skin effect makes the classical term wrong above ~100 Hz in high-permeability laminations); per-winding resistance bounds.

**Low-level core physics (follow-up, 2026-10-23). Decided by the user 2026-10-23: Option 1. Applied 2026-10-24 (results at the end of this section).** Phase 4 found 0.16% THD (H3) at -10 dBm with the JA cores, 0.003% with their linear limit, falling as the level rises. Real permalloy at low fields follows Rayleigh's law, mu(H) = mu_i (1 + r H), with a finite initial permeability, so its hysteresis distortion vanishes as the level falls. Numbers: `reports/phase2/mumetall_rayleigh_options.json`.

- **Why.** The production mumetall fit has c = 0.00077: its initial curve is M ~ c chi_an H + chi_an H^2 / (2k), and with c that small the quadratic term rules from ~0.04 A/m up, so the core runs at H ~ sqrt(B) over the whole audio range. Its permeability at the demagnetized origin is 246 (the circuit file's comment says 5,850: the turns were derived to give 10 H at that value, so the linear-limit T101 is ~0.75 H today, -4.6 dB at 40 Hz standalone). On its initial curve it reads 1,270 at 0.01 A/m and 11,200 at 0.1 A/m; the datasheet's own graph reads ~55,000 at 0.1 A/m. T101 and T103 sit at ~0.001-0.006 A/m on program material.
- **Data** (sourced, in the repo): the Mumetall sheet's VAC graph of amplitude permeability, final-annealed (`data/datasheets/matthey_mumetall_mu_a.csv`, digitized with provenance): mu_a ~ 42,000 (1 + 2.8 H) over 0.1-0.6 A/m. Independently, a DC ring of 1J85 permalloy (80Ni-5Mo): mu_i 72,100, r = 3.3 per A/m (web: https://pmc.ncbi.nlm.nih.gov/articles/PMC9608087). Both give r ~ 3 per A/m; the production fit implies ~23.
- **Option 1 (recommended): refit JA with the Rayleigh region as a fifth target.** `scripts/fit_core_material.py` now takes `rayleigh_r_per_a_m` and `h_rayleigh_a_per_m` in a material's datasheet block (mu at h_rayleigh = mu4 (1 + r h_r) / (1 + r 0.4)). With r = 2.8, h_r = 0.04 A/m: a 3.18548, k 1.66935, c 0.289433, alpha 1.76945e-5; mu4 +0.5%, mu_max -0.3%, Hc +2.3%, loss -2.2%, mu(0.04) -0.5%. Its origin permeability 29,300; H3/H1 of the field under sinusoidal B 5.5e-5 / 5.5e-4 / 5.2e-3 at 10 uT / 100 uT / 1 mT (linear in amplitude: Rayleigh); loop loss ~ Hm^3.0. (r = 3.3 gives nearly the same set.) No model or engine change: the Python reference and circuitsim stay as tested.
  - In the nominal unit (no limiting, THD %): 1 kHz -30 / -10 / +4 / +18 dBm in: 0.0001 / 0.0031 / 0.062 / 0.66 (production 0.31 / 0.16 / 0.065 / 0.69; linear limit 0.0001 / 0.0030 / 0.061 / 0.66). 100 Hz: 0.0004 / 0.0061 / 0.073 / 0.64 (production 1.53 / 0.56 / 0.22 / 0.74; linear 0.0000 / 0.0027 / 0.059 / 0.53): the core's distortion now rises with level and adds to the tubes at LF.
  - Standalone, re 1 kHz at 40 Hz: T101 -0.02 dB at any level, JA and linear alike (production JA -1.36 dB at small drive to -0.14 dB at large: a level-dependent bass response; production linear -4.55 dB); T103 -0.01 dB (production -0.48 to -0.05, linear -2.59).
  - Its JA minor loops are Rayleigh-like (loss ~ Hm^3) but their amplitude permeability rises about half as fast as the initial curve does (Rayleigh: equally fast).
  - Consequences: every render with a mumetall core changes (the whole cache); the linear-limit builds change too (ngspice's cross-check cores), so `--verify`'s bounds, `test_transformers.py`, `test_circuitsim_slice.py`, the IR / device fixtures and Phase 2's "JA and linear builds differ up to 2 dB in LF compression" need re-measuring; T101's and T103's linear-limit inductances become ~18 H and ~8 H (the gap now dominates their reluctance at low level; the derived turns' "10 H" / "5 H" notes go stale).
- **Option 2: another JA variant** (e.g. a field-dependent reversibility, or a second anhysteretic term), only if Option 1's minor-loop shape matters: Option 1 already meets every datasheet figure.
- **Option 3: another hysteresis model** (Preisach, or a sum of play operators), Rayleigh by construction with return-point memory (JA's minor loops don't close exactly). A new device in both the Python reference and circuitsim, with a state of reversal points; days of work and an unknown speed cost.

*Option 1 applied (2026-10-24).* `config/magnetics.yaml`'s mumetall datasheet block has `rayleigh_r_per_a_m: 2.8`, `h_rayleigh_a_per_m: 0.04` (sources: the digitized VAC graph; the 1J85 ring as the cross-check), and `fit_core_material.py mumetall` gives exactly the set above (a 3.18548, k 1.66935, c 0.289433, alpha 1.76945e-5; mu4 +0.5%, mu_max -0.3%, Hc +2.3%, loss -2.2%, mu(0.04 A/m) -0.5%). No model or engine change. Re-verified:

- **Linear limits:** T101's primary 17.7 H, T103's 7.9 H (were 0.75 / 0.44 H; the turns derived for 10 / 5 H at an origin permeability of 5,850 stay, the notes restated): the joint gap is 81% / 85% of their reluctance. The SPICE goldens changed only there (T101 / T103 inductances and couplings, now 0.99993 / 0.9997).
- **Standalone** (`tests/test_transformers.py`, `reports/transformers/`), re 1 kHz at 40 Hz / 15 kHz: T101 -0.02 / +0.56 dB (was -0.29 / +0.60), T103 -0.04 / +0.06 dB (was -0.20 / +0.08); T101 -3.3 dB at 2 Hz, -0.8 dB at 5 Hz (the sweep now starts at 2 Hz: at 10 Hz it is only -0.23 dB, too flat for the test's roll-off check); 30 Hz THD at half of saturation 0.08% / 0.09%, past it 12%.
- **The nominal unit** (`varimu unit --name nominal`): the factory adjustment barely moves (pad 11 dB, DC THRESHOLD 0.2529, AC THRESHOLD 0.7088; were 0.2533 / 0.7093; gain below threshold +0.43 dB, was +0.39), its 1 kHz curve within 0.09 dB of curve 3 from +1 to +25 dBm in, as before; plausible. THD without limiting, 1 kHz: 0.012% at -10 dBm in (was 0.159%), 0.032% at 0 dBm (0.090%), 0.063% at +4 (0.070%), 0.66% at +18 (0.69%); 100 Hz at the factory panel: 0.031% at -10 dBm (0.55%), 0.061% at 0 dBm (0.29%), 0.70% at +10 (0.68%). The level-dependent bass response is gone with it (Option 1's standalone measurement: T101 -0.02 dB at 40 Hz at any level); the unit's small-signal response re 1 kHz at 40 Hz is -0.50 dB (was -0.51).
- **JA vs linear cores** (the slice report's clip, gain per 50 ms; same method that gives Phase 2's 1.95 / 0.61 dB on its commit): max 0.022 dB, median 0.002 dB (1.31 / 0.42 dB just before the refit); the 1 kHz curve 0.000 dB, TC timings 0.04%. So the earlier "~2 dB" was the old fit's linear limit being ~120x too low, not hysteresis.
- **Agreement** (`slice_report.py --verify`, cold, pass): behaviour vs ngspice 0.009 dB (curve), 0.008 dB (clip), timings <= 0.03%; excerpts vs exact ngspice -82.5 to -85.0 dB (bursts), -76.2 / -71.7 dB (clip), clip vs the converged solution -77.1 dB, CV 0.10 V; every row 3-4.5 dB inside its bound (kept). `tests/test_circuitsim_slice.py`: -73.1 to -86.3 dB vs converged, -64.3 / -60.4 dB vs ngspice. Found on the way: two production-ngspice curve chunks stopped in the settling with the input split into four filesources (the stiffer couplings), and ran split into three or five, as with the old fit in four: `run_transient` now retries any stopped run once with one filesource more (CLAUDE.md, ngspice gotchas).
- **Plausibility** (`scripts/plausibility_check.py`): all 23 cases judged right; the nominal screen's THD at +4 dBm 0.062% (was 0.065%).
- **Listening:** `ab-prepare` re-matched the pool (12 of 12 solved, worst GR error 0.064 dB, pairs within 0.00 LU, all three candidates pass the screen).

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

*Status (2026-10-22): done* (one channel; the second channel's draw on the supply is in, idle and lumped). What exists:

- **The supply, traced** on A-96039 (`data/schematics/fairchild_670/README.md`, "Supply rails", with `rails*.png`; the rails run between the crops, so the full drawing was rendered and followed):
  - **Main supply.** Mains (a sine source) into T302 and V301 (printed "6234": the GZ34, per the manual's tube list and chassis photo), then C304 4 uF and L301 into C305 + C306: the unregulated rail. The regulator: EL34 triode-connected pass tube, 6084 error amplifier, 5651 reference, and R313 B+ ADJ, giving 240 V. R315/R316 make the 6973 screens' tap.
  - **Bias supply.** T301 into the selenium bridge GR301. C303, after L302, is the 6386 cathode return. C108 feeds ZERO. The R303 end, printed -13 to -14.5 V, is the 6973 grid-leak return; it replaces the slice's provisional -27 V.
  - **What each rail feeds.** The 12BH7 loads and T104's centre tap (6973 plates) are on the unregulated rail, not 240 V. The 12BH7 grid leaks and cathode resistors return to ground. Both settle the slice's open wiring questions.
  - **Unprinted values.** They are genome parameters. Replacement-part specs (Sowter) are reference points. Three nominals are calibrated (`scripts/calibrate_psu.py`) to what the drawing prints and a unit measured:
    - T302's voltage puts the unregulated rail at 435 V (printed 420-450 V);
    - L302's resistance (284 ohm) puts C303 at the measured -6.2 V (web: GroupDIY, Dave P);
    - B+ ADJ sets 240 V.
  - **Checks that came out right without fitting** (`tests/test_psu.py`):
    - C302 -34.4 V (Dave P: ~34 V);
    - the R303 end -13.8 V (printed -13 to -14.5 V);
    - 6386 banks 24.9 mA each (measured ~26 mA);
    - 12AX7 cathodes 3.7 V (web: "3.6 V (cut-off)").
- **New devices**, each fitted to datasheet data digitized here (`data/datasheets/`, provenance sidecars):
  - EL34 triode-connected: Koren triode on Mullard's triode curves, 0.8 sigma rms.
  - 6084 / E80F: Koren pentode on Philips curves, plate current 11% rms; Koren's screen law fits only ~40%.
  - 5651: a diode in series with its burning voltage, the slope from Tung-Sol's plot, the operating voltage a genome parameter (RCA's 82 / 87 / 92 V).
  - Selenium cell: on Tarzian's 25 C static curve, 2% rms, scaled by area, with the handbook's junction capacitance.
  - Pentodes now have grid current (the triodes' law), Python, SPICE and circuitsim.
- **Ripple and sag reach both paths** (`tests/test_psu.py`):
  - **Ripple.** The bias supply's 120 Hz sits on both 6386 grids through ZERO (1.8 mV). Matched banks cancel it at the output; a 10% emission mismatch lets it through as hum (-121 dBFS).
  - **Sag in the audio path.** Under a 0 dBFS burst the 6386 current halves, so the drop across L302 shrinks and the cathode return moves -8.2 to -14.5 V: a slow, program-dependent bias shift, shared with channel 2. The unregulated rail rises 13 V as the stage stops loading it.
  - **Sag in the sidechain.** The 6973 screen tap sags (153 to 147 V), and their grid current pulls the R303 end down (-13.8 to -15.0 V). The 240 V rail holds within 0.6 V.
- **Per-instance tolerance and mismatch.**
  - **Seeded draws.** Every part of channel 1 and the supply, and every tube instance, draws from `default_rng([seed, crc32(designator)])`.
  - **Bands.** Resistor bands are printed: 1%, 5%, and 10% by note 1. Capacitor, pot and tube bands are provisional genome bounds.
  - **Banks.** Each 6386 bank is its four triodes (the drawing's designators), around the bank's genome values. circuitsim merges devices on identical pins into one parallel device, so the Newton system keeps its size: 45 ports, ~5% slower.
  - **The nominal genome has spread 0** (every part at its printed value). Spread 1 is a unit with its parts anywhere in tolerance.
- **Setup** (`varimu.sim.setup`): the manual's procedures on the DC operating point, a few seconds per unit. B+ ADJ to the nominal rail, BALANCE for equal meter readings across R107/R108, ZERO for the nominal total plate current; the meter's ZERO position reads 15 ohm x that current, which is how ZERO's nominal 0.3 got its source.
- **Done when** (`tests/test_corners.py`; full sweep `scripts/corner_sweep.py` -> `reports/corners/summary.json`). 143 genomes over the 63 genome-linked parameters:
  - the genomes: nominal, all-min, all-max, each parameter alone at each bound, and 16 random corners with part spread 1;
  - the runs: set up, and the extreme and random corners also as built (161 runs);
  - each run: 0.1 s idle, then a 1 kHz staircase -30 to 0 dBFS at the hottest front panel.
  - **Every run simulated without convergence failure.** Gain reduction rose at every step in 158 of 161 (to 15-44 dB at 0 dBFS).
- **Genomes Phase 4's plausibility checks must reject** (recorded in the summary):
  - **HF oscillators:** random-15 and random-3 at 19.4 kHz (random-15 near full scale, its CV pinned at -212 V by its own oscillation), random-5 at ~23 kHz, random-6 at 30 kHz (Phase 2's tuned-plate tuned-grid mode).
  - **Low-frequency wander** (-38 to -76 dBFS): random-4, 8, 9, 10, 13, 14. These are weak-supply corners: random-13's unregulated rail sits at 346 V, the regulator is in dropout at 230 V, and ZERO drives the grids into conduction to restore the current.
  - **Gain reduction folding back** at 0 dBFS with T101's leakage at its 20 mH bound (Phase 2's +15 dB peak near 17.8 kHz).

Findings that change later work:

- **Render speed regressed.** circuitsim is 14x slower than real time on the 7 s TC1 burst (Phase 2: 5.8x) and 36x on the 4 s clip (7.3x), at the slice report's front panel.
  - **The circuit doubled:** 45 device ports, 86 states.
  - **The 6973 grid conduction:** error control halves steps at every grid clamp, ~1.8x. It is physical; without grid current the 6973 grids ran to +251 V.
  - **Settling:** renders now run 1 s first (`start.settle_s`), because the supply starts from its DC point at the mains peak.
  - What would help is engine work: step-size selection instead of recursive halving, and M5's deferred speed target (circuit-sim plan, "Phase 3 in circuitsim").
- **Production accuracy on the clip's first attack.** Production circuitsim against its converged solution: -56.8 dB / CV 0.19 V on the whole clip (Phase 2: -76.3 dB / 0.006 V). That is inside the plan's -55 dB / 0.2 V, with the error at the clip's first attack from rest, where the CV falls ~80 V in ~2 ms. 10x tighter error tolerances give 0.07 V (+19% time), 4x oversampling 0.04 V (+43%). Not changed (speed); the user's call.
- **ngspice needed the rectifier's capacitance.** Production ngspice stopped ~1 ms in, where the GZ34 first cuts off, until T302's winding capacitance and the selenium cells' capacitance went in. Both are physical: an inductive kick into a node with nothing on it.
- **Sourced values applied (2026-10-23), and the factory adjustment:**
  - **T103's ratio** is Sowter's replacement, 17+17:1+1 (8.5 per secondary half re the series primary; was a provisional 3.0): +9 dB of sidechain drive. Bounds 7.5-9.5. The old leakage (10 mH, the "k = 0.999" placeholder) is 72x that referred to a secondary half and rolled the sidechain off -2.1 dB at 15 kHz; the nominal is now 5 mH, chosen like T101's (within 0.5 dB, 40 Hz-20 kHz, standalone).
  - **The AC THRESHOLD pots are tapped** (GroupDIY, Walrus reading the original manual; `sidechain_1.png` agrees): each section from its T103 end to the centre line, R113/R114 from the tap to the centre line, the wiper to a 12AX7 grid. AC THRESHOLD 0 now gives no sidechain signal (the manual's curve 1); before, it left 19%. New genome parameters: the tap position (0.3-0.7, nominal 0.5: CJ's "50% tap") and R115B (a choice of 100K / 180K; nominal 100K: the original manual reads "a dual 100k lin tapped pot", "180k on some prints", and 180K with a 50% tap would drive one 12AX7 grid 3 dB less below the tap).
  - **The manual's threshold procedure** (p.8) is `varimu.sim.setup.threshold`: unity gain with AC THRESHOLD at 0 (the input pad in 1 dB steps), then DC THRESHOLD for the desired output at 3 dB of limiting and AC THRESHOLD at 10 dB, repeated until both hold (alternating converges slowly, each moves the other's point by ~0.84 of its own change, so the repeats run as Newton on both: 3 iterations). Run to **curve 3** ("Factory-adjusted condition", PDF p.13, digitized: `data/datasheets/fairchild_670_io_curve3.csv`), the nominal unit lands at pad 11 dB, DC THRESHOLD 0.253, AC THRESHOLD 0.709, and its 1 kHz curve is then **within 0.17 dB of curve 3 from +1 to +25 dBm in** (+0.4 dB below the knee: the pad's 1 dB step). The model reaches the factory curve's shape (knee at +2 dBm, 10 dB of limiting at +15.4 dBm in, +6 dBm out at +25) with the thresholds inside their ranges. These are now the circuit's default front panel.
  - Tests and bounds re-measured: `test_slice.py`, `test_psu.py` (their hottest panel now names DC THRESHOLD 0, the old default), `test_transformers.py` (T103 -0.20 / +0.08 dB at 40 Hz / 15 kHz), `test_circuitsim_slice.py` (vs converged -81.2 / -85.8 / -72.2 / -74.3 dB; vs ngspice -64.0 / -60.4 dB), and `--verify` with the engine changes of the circuit-sim plan's "Speed after Phase 3" (2026-10-23, passes, bounds re-measured in `slice_report.py`): behaviour vs production ngspice 0.01 dB on the curve, 0.035 dB on the clip, TC1-4 times identical; excerpts vs exact ngspice -81.9 to -85.4 dB (bursts), -76.2 / -71.3 dB (clip); the clip vs the converged solution **-77.2 dB / CV 0.070 V** (Phase 3: -56.8 / 0.19). So the pending tolerance decision (Phase 3 findings) is far less pressing: 10x tighter tolerances now give -78.5 / 0.040, 4x oversampling -83.9 / 0.007.
- **Open:**
  - the 5651's ignition (it is lit from the DC point on);
  - electrolytic ESR;
  - selenium reverse leakage (no absolute figure found);
  - the meter's sensitivity, which would calibrate ZERO without the measured current;
  - wiring the setup into renders: renders use the trims as given, and the nominal genome needs none; Phase 4's unit pipeline should apply `setup.adjust`.

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

*Status (2026-10-23): done* (noise waits for noise sources; "Closing Phase 4" below has the last changes).

- **The runner** existed from the slice (cached, parallel, `timing.csv`). New: a fresh render returns exactly what its cached copy will (float32), so anything measured from it, a level that sets the next render's input, gives the same next cache key either way; ngspice's start-up stop at four input chunks is retried with five (circuit-sim plan, "Speed after Phase 3").
- **The one command:** `varimu unit --name NAME [--genome FILE] [--set k=v ...]` (`varimu.measure.suite`) -> `reports/units/NAME/` (report.json, plots, rendered clips in `audio/`, not committed). Exit status 2 when the unit is rejected.
  1. the plausibility screen (`varimu.measure.plausibility.screen`, three short renders);
  2. setup: `setup.adjust` (B+ ADJ, BALANCE, ZERO on the DC point), then `setup.threshold` to curve 3 (the input pad for unity gain, DC and AC THRESHOLD). The unit pipeline now applies the manual's setup; renders elsewhere still take the trims as given;
  3. every section's renders as one parallel batch, then the measurements and the full checks.
- **Levels are the manual's:** dBm at the 600 ohm terminals (`varimu.measure.levels`, the input measured at its terminals, `in_s`, a new probe). The gain-reduction points are curve 3's 0 / 3 / 10 dB of limiting (-10 / +6.66 / +15.41 dBm in), which setup puts the unit on.
- **Sections:**
  - static curves at 1 kHz: AC THRESHOLD 0 (no limiting, to +28 dBm), 0.4, factory, 1; factory at 100 Hz and 6 kHz; the factory curve against curve 3;
  - THD and harmonics from every curve step (vs level, frequency, gain reduction), and the manual's two distortion specs;
  - attack and release for all six Time Constants from a burst to 10 dB of limiting (positions 5 and 6 also a train of short bursts);
  - frequency response at 0 / 3 / 10 dB of limiting (a 1 kHz pilot holds the reduction, a 31-tone probe 40 dB down reads the response);
  - SMPTE (60 Hz + 7 kHz, 4:1, as p.10) and CCIF IMD at the three points;
  - thump (6 kHz bursts with 5 ms edges, the output low-passed at 1 kHz, with the input's own floor);
  - the program clips.
  - Not yet: noise (no noise sources).
- **Plausibility checks** (as first built; split into broken / not a 670 when Phase 4 closed, below). The screen:
  - idle quiet (< -80 dBFS);
  - B+ 232-248 V, the unregulated rail 380-480 V;
  - bank currents 10-50 mA, the grid bias on ZERO's divider;
  - at the hottest panel: gain reduction > 6 dB at 0 dBFS and rising > 0.5 dB per 10 dB step, no spur > -50 dB away from the tone's harmonics, the CV above -150 V;
  - THD < 5% at +4 dBm out with no limiting.

  The full checks:
  - the factory curve within 3 dB of curve 3 and limiting > 10 dB by +25 dBm;
  - gain reduction rising on every limiting curve, no spur under any curve's tone;
  - attack < 20 ms;
  - the 90% CV release within 0.25-4x the published value (or range: TC5 2-10 s, TC6 0.3-25 s, program dependent);
  - the CV back after TC1-4;
  - response within +-3 dB 40 Hz-15 kHz and SMPTE < 10% at no limiting.
- **Done when** (`scripts/plausibility_check.py`, `tests/test_plausibility.py`):
  - **Phase 3's flagged runs:** all 17 rejected (each in the state it was flagged in, set up or as built):
    - the HF oscillators by idle and spur checks;
    - the weak-supply corners by idle wander, B+ and the unregulated rail;
    - T101's 20 mH leakage by the grid bias, the spur check and the CV range.
  - **The nominal unit:** passes.
  - **Deliberately broken genomes, each rejected by the check it targets:** no sidechain drive (T103 at 0.05), the regulator's reference above its rail, dead 6386s, a saturating T101 (1e4 x the flux per volt), C109 x 100 (release).
  - **Two of my first guesses weren't broken in this circuit:**
    - Phase 2's unscreened transformers (20 + 50 pF) now idle at -164 dBFS;
    - a 150 V reference is trimmed back to 240.9 V by B+ ADJ.
- **The nominal unit's report** (`reports/units/nominal/`):
  - factory curve within 0.48 dB of curve 3 (with the pad's +0.39 dB);
  - THD with no limiting 0.07% at +4 dBm out, 0.43% at most to +18 dBm (spec < 1%), 1% at +20.6 dBm;
  - 0.23% at 10 dB of limiting, there at +5.4 dBm out (spec: < 1% at +12 dBm);
  - SMPTE 0.10 / 0.61 / 2.4% at 0 / 3 / 10 dB of limiting (p.10's curves: ~0.3-1% at 0 dB, rising with limiting);
  - response re 1 kHz, 40 Hz-15 kHz: -0.5..0 dB at no limiting, -1.6..+0.4 at 3 dB, -3.9..+1.0 at 10 dB: the response tilts under limiting;
  - 90% CV release 0.24 / 0.69 / 2.03 / 4.06 s at TC1-4 (published 0.3 / 0.8 / 2 / 5), TC5 5.9 s, TC6 11.2 s after a 1 s burst;
  - attack (63% of the CV) 1.7-3.3 ms against the published 0.2-0.4 ms;
  - thump: the output below 1 kHz peaks -47.7 dB re the tone (-64 dBFS) when a burst drives 10 dB of limiting, at the measurement's floor (-101.5 dB) with no limiting: the CV's step reaching the output through the push-pull stage even with every part at its printed value;
  - about 23 minutes per unit on this desktop with nothing else running (the 17 s Time Constant renders are the long pole).

Findings that change later work:

- **Attack is ~8x the published 0.2-0.4 ms** (CV 63% at 1.7 ms for TC1/2/6 from a burst to 10 dB of limiting). Either the manual's attack is defined differently (e.g. the CV's first movement, or a bigger overload) or the sidechain's source impedance / bridge in the model is slower than the original's. Worth a look before Phase 5's listening. *Resolved (closing Phase 4, below): current-limited by the 6973 pair, as physics says; the onset matches the published figures.*
- **Low-level distortion comes from the transformer cores.** 0.16% THD (H3) at -10 dBm with the Jiles-Atherton cores, 0.003% with their linear limit; it falls as the level rises (0.07% at +4 dBm, where the tubes take over). Real permalloy at low fields follows Rayleigh's law, its hysteresis distortion falling with level. The effective-field JA fit of mumetall is almost all irreversible (Phase 2), so at low fields it overstates hysteresis. Within the manual's < 1%, but it is character: a Phase 2 follow-up (a fit with a Rayleigh region, or another hysteresis model). *Options measured: Phase 2, "Low-level core physics"; Option 1 applied 2026-10-24: 0.012% at -10 dBm, rising with level.*
- **The error estimate misses a diode turning off within a step** (circuit-sim plan, "Speed after Phase 3"): fine on the 670's events, worth knowing for other circuits.

**Closing Phase 4 (2026-10-23)**, after the aim was restated (Vision): the 670's figures are anchors, not targets.

- **Plausibility split into "broken" and "not a 670"** (`varimu.measure.plausibility`). Rejecting checks are only what no working unit could do:
  - oscillation: idle quiet, no spur under any tone;
  - runaway DC or collapsed bias: the regulator regulating (B+ within 3% of B+ ADJ's 240 V after setup, 10% as built: the 5651's +-6% and the divider's 10% resistors), bank currents 10-50 mA, the grids negative on ZERO's divider;
  - no gain reduction, or gain reduction folding back, on any curve;
  - absurd distortion: THD > 5% at +4 dBm out or SMPTE > 10% with no limiting;
  - a CV that never returns: its 90% release, extrapolated past the window from the remaining distance's decay, over a minute (`metrics.cv_release_estimate`).
- **The comparisons with the 670 moved to the report's `vs_670`**, which rejects nothing: the factory curve against curve 3, limiting at +25 dBm, attack and release per burst against the manual, the response against +-1 dB, the unregulated rail against its printed 420-450 V. Moved out of rejection: release vs the manual, attack < 20 ms, curve 3 within 3 dB, response +-3 dB, the unregulated rail 380-480 V, the hot CV above -150 V; none had been the only check rejecting a case. `scripts/plausibility_check.py`: all 23 cases judged right again (the nominal passes; Phase 3's 17 and the 5 broken genomes rejected, each by a physical check). `slow_release` is now C109 x300 (rejected by `cv_returns`: TC2 releases in ~208 s; x100 gave 69 s, too near the minute to be a clear case).
- **Attack: no physics missing; the old figure measured a different thing.** Measured on TC1 bursts to 10 dB of limiting with the sidechain probed (one suspect at a time):
  - The bridge current is pinned near 145 mA whatever the bridge diodes (ideal or 1N4007-like), T104's leakage (20 / 5 / 1 mH), R136 or C105. The 6973 grids clamp at about +2 V. So the CV's slope is limited by what the 6973 pair can deliver at the 670's ~150 V screen tap: ~70-79 mA a plate, x2 through T104's 2:1 into C109, at most ~72 V/ms on TC1's 2 uF.
  - The 6973 model in that region agrees with RCA's Vg1 = 0 plate curves (DATA 1 p.6, not used in its two-point fit): 67.5 vs ~65 mA at Vg2 = 150 V, 134.5 vs ~127-135 mA at 250 V.
  - A 54 V swing in 0.2 ms would need ~540 mA, more than the pair can deliver even at a 300 V screen. So "full limiting in 1/5000 s" (the 660 brochure; the manual doesn't say how attack was measured) can't be the CV's 63% point in this circuit.
  - The old 1.7 ms was 63% of the swing at the end of a 1 s burst, whose CV keeps creeping (-58.6 to -67.6 V) at constant gain while it tracks the supply's sag; against the fast swing (the CV 20 ms in) it is 0.88 ms.
  - The CV's **onset** (its first 10%) reproduces the published pattern: 0.16 ms on TC1/2/6 (published 0.2), 0.25 on TC3/5 (0.4), 0.42 on TC4 (0.4); the 2x step between 2 uF and the larger networks included. The gain: 1 dB in the first half period of the 1 kHz tone, 3 dB in 1.0-1.5 ms.
  - The report now gives attack as the CV's 10% and 63% of the fast swing and the gain's 1 / 3 / 6 dB per half period (`metrics.cv_attack`, `metrics.gain_attack`), and compares the onset with the manual (informative).
  - Sensitivity worth knowing for the parts sandbox: the attack scales with the 6973's zero-bias current, i.e. with the screen tap (R315; a redraw reportedly reads 100K, README open questions) and the screen supply's sag.
- **Positions 5 and 6 get an individual peak** (20 ms to the 10 dB point; `suite.PEAK_S`) besides the 1 s burst (a consistently high level) and the train (multiple peaks), each against its own published figure (`suite.PUBLISHED_RELEASE`). Nominal unit, CV 90%: TC6 peak 0.26 s (published 0.3), TC5 peak 2.75 s (2), TC5 train 6.5 s (10), TC6 train 13.9 s (10), TC6 1 s burst 11.2 s (25). The peak's length barely matters (10 / 20 / 50 ms: TC6 0.24 / 0.26 / 0.31 s, TC5 2.6 / 2.75 / 3.0 s). TC6's 25 s probably needs a level sustained long enough to charge C112 (R140 C112 = 2 s; a 1 s burst charges it partly), not a model change.
- Noise stays open until noise sources exist (Coupling Checklist).

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

*Status (2026-10-23): in progress, the done-when met* (see the end). What exists (`varimu/listen/`):

- **Candidates** (`candidates.py`, pool in `config/listening.yaml`): a candidate is a name and a physical genome; front-panel controls are refused. Its id is the genome's content address. The pool: nominal, a parts-sandbox swap (T101's core a harder nickel-iron), a unit built from parts anywhere in tolerance (spread 1, seed 1).
- **The parts sandbox** (`candidates.catalog`, `candidates.swap`, `varimu ab-prepare --swap KEY=VALUE`): every genome-linked circuit value is a swappable part, a choice (core materials) or a value within its bounds (out of bounds is refused), each with its source. A swap is a candidate like any other: screened, set up and matched the same way. Capacitor types aren't swappable yet: dielectric physics (absorption, ESR) isn't modelled.
- **Matching** (`stimuli.py`):
  - each candidate set up as the factory would (the DC trims; pad and DC THRESHOLD at the factory adjustment);
  - **gain reduction**: AC THRESHOLD solved so the average GR on the excerpt is the target (3 and 6 dB), GR measured against the same unit at AC THRESHOLD 0 per 50 ms window, gated 30 dB below the loudest; a parallel grid, then refinements rendering the estimate and a neighbour either side, to 0.1 dB; an unreachable target is flagged, not faked;
  - **loudness**: each pair is matched to one integrated LUFS at playback (lowered together if a peak would clip).
  - Program material: data/clips only (none: `ab-prepare` says so and stops); clips longer than the pool's 8 s play their loudest 8 s window, faded (renders run ~17x slower than real time).
- **Verified by measurement** (`prepare.py`, `varimu ab-prepare` -> SQLite and `reports/listening/matching.json`): every stimulus's GR re-measured from its cached renders, every pair's LUFS after matching; candidates the plausibility screen rejects are left out. `tests/test_ab_matching.py` does it on real renders (two candidates, 3 dB, a 1.5 s program-like excerpt).
- **Protocol** (`session.py`, `/ab` in `varimu listen`, `ab.html`): blind (the page sees trial ids and audio, never candidates), randomized sides and order (one seeded generator per session, the first-heard side too), keyboard (Space, 1 / 2 to switch sides in sync, R, A / B / N to answer), repeated pairs (15% after the 4th trial, at least 3 trials back, sides redrawn) for the listener's consistency, a session timer with a break banner at 25 minutes.
- **Storage** (`store.py`, data/judgments/judgments.sqlite, never committed): candidates, stimuli (per code and config version), sessions, trials (clip, category, GR target, sides, repeat-of, the loudness match applied and measured, choice, preferred candidate, response time, plays per side).
- Tests: `tests/test_ab.py` (no renders: the GR measure and solve on a synthetic compressor, planning, a whole session through the app into SQLite; the HTTP-level variant through `httpx`, a dev dependency).
- **Measured on the user's two clips** (2026-10-23, `reports/listening/matching.json`): the pool's 3 candidates x 2 clips (the arpeggio whole, 4 s; the guitar's loudest 8 s) x 3 and 6 dB: all 12 solved in 7-13 renders each, worst GR error 0.066 dB; all 12 pairs within 0.00 LU after matching; all three candidates pass the screen. Thresholds land close together (3 dB on the guitar: AC 0.627 nominal, 0.629 with T101 permalloy, 0.596 for the built unit), so the pairs differ in character, not amount. A smoke session on a copy of the database: a trial loads in 0.5 s, both sides at -23.0 LUFS.
- The done-when is met by those tests and measurements. Left: a first real session by the listener, then Phase 6 needs judgments.
- **First real session (2026-10-23, 12 trials, a pilot):** the listener found every pair extremely close and chose A 10 of 12 times (sides randomized: ~4% by chance), never "no preference", and got no repeated pair (repeats are drawn at 15% a trial: a 12-trial session gets none ~27% of the time). Read as near chance with a position bias: kept in the database as a pilot, not preference data. The units differ by little once gain reduction and loudness are matched, so preference answers need a check that the pair can be told apart at all.

**Listening aids 1 and 2 (2026-10-24), built after the Phase 2 core refit** (`varimu/listen/difference.py`, `abx.py`; the /ab page has three modes: Preference, "Can I hear it? (ABX)", Difference listening):

- **Difference listening** (`difference.streams`, no new renders): A, B, the residual A - g B (g the least-squares gain aligning B to A) turned up to the listening loudness with its level re A, and A + k (g B - A) for k = 2, 4, 8, all loudness matched (one shared target, lowered together if a peak would clip, and said so). GR stays measured: the extrapolation is applied with the same g to the two units' no-limiting references, so the "unit" at k has a reference, and its average GR is exactly A's at k = 0 and B's at k = 1. Artifacts reported per stream, not hidden: the GR off the pair's by more than 0.5 dB, or the 50 ms envelope off A's by more than 3 dB (where the gain envelopes differ, extrapolating scales that difference, and the envelope can fold). Candidate names are hidden unless asked for.
- **ABX with an exaggeration staircase** (`abx`): X is secretly A or B (seeded), and which of the pair is labelled A is drawn too; B is the pair's other stimulus exaggerated, A + k (B - A), from a base side drawn per pair. One staircase per pair on log2 k, interleaved at random: from k = 8 down after each hit and up after each miss, but with the up step 3x the down step (Kaernbach's weighted up-down, 1991; 0.25 octave down, 0.75 up, 0.5 octave down before the first miss; k in 0.25-16). Equal steps would settle at 50% correct, which in ABX is guessing; 3:1 settles at 75%, halfway to certainty. The estimate is the geometric mean of k at the reversals (the first two left out once there are four); simulated listeners with a known 75% point (k = 0.7, 1.5, 6) are recovered within a factor 1.4 over 300 trials (`tests/test_abx.py`). Per pair: hits and a one-sided binomial p over all its trials and over those at k <= 1, the k track and the estimate. A "real pairs only" mode plays every trial at k = 1 (plain ABX). The anchor: the prepared pair with the largest residual at k = 8, 3 trials per session spread through it. Position bias: the share of "X is A" answers, stored with the session. Feedback (right / wrong, and k) after each answer: this is ear training.
- **Storage:** `abx_sessions`, `abx_pairs`, `abx_trials` in the judgments database, apart from the preference tables; every trial at k != 1 is flagged `exaggerated`, the anchor flagged too; each trial keeps the loudness match, both GRs as played and the artifacts.
- **Preference sessions:** a fixed 3 repeated pairs per session (fewer only when the plan is too short), at seeded positions after the 4th answer, each at least 3 trials after its original (`session.repeat_schedule`); `idx` is now the order of presentation (a repeat goes in at the current position). The position bias (share of A among the A / B answers) is in the progress, shown at the end and stored with the session (`sessions.share_a`; `sessions.repeats` is NULL for the pilot, from before).
- **On the user's clips** (the pool re-prepared after the refit, 2026-10-24; smoke-tested through the app on a copy of the database): residuals re A, T101 permalloy against either other unit -21 to -26 dB, the built unit against nominal -34 to -41 dB (so the anchor is a permalloy pair); every played pair at -23.0 LUFS; artifacts flagged only at k = 8, on 4 of the 12 pairs (all on the guitar: GR 3.92 / 2.38 dB against the pair's 3.0, envelopes up to 4.5 dB off A's). A pair's streams load in 0.2-0.9 s, the pair list in 2.3 s.
- Tests: `tests/test_abx.py` (fake renders: the streams, the exaggerated pair, the staircase's rule and convergence, whole ABX sessions through the app and over HTTP, reproducibility from the seed, fixed repeats, the database migration); `tests/test_ab_matching.py` runs the aids on its real matched pair.

**The first ABX attempt, multitrack material, and tone vs character (2026-10-24).** The listener found the pairs very hard to tell apart even in ABX (one trial answered, a miss at k = 8 on the most different pair). Two things followed, decided with the user: better program material, and a difference measure that separates what is EQ from what is compressor physics. Then the physical caricatures (item 4 below).

- **Program material from multitracks** (`scripts/build_clips.py --root DIR`, recipes in `config/listening.yaml` `mixes`): four Cambridge-MT multitracks the user supplied ("educational purposes only, no commercial use without permission": local research listening, never committed). Mixes are plain sums of stems (static gains, polarity where a zero-lag sum measured it inverted: Long Way Home's overheads), mono, normalized to -14 LUFS over the loudest 8 s or lowered to keep peaks at -0.5 dBFS; data/clips/mixes.json records the stems' SHA-256s and gains. One clip per category: bass (A Reason To Leave, the bass DI), drum bus (Set Me Free, close mics, overheads and rooms; -23.1 LUFS, peak limited), vocal (Long Way Home, the lead), full mix (Long Way Home, all 20 stems as tracked; -16.8 LUFS). `pool_clips` in the pool file names what the pool matches and the page plays (the arpeggio stays in data/clips for `--verify`).
- **Matched** (`ab-prepare`, 2026-10-24): 24 stimuli, worst GR error 0.088 dB, pairs within 0.00 LU; 6 dB is out of reach for nominal and T101-permalloy on the vocal and the mix (5.3 / 5.9 dB at AC THRESHOLD 1.0, flagged and left out: the pad stays at the factory adjustment), so 18 pairs: every clip at 3 dB, bass and drums at 6 dB.
- **Tone vs character** (`difference.decompose`): B aligned to A by gain, then the LTI filter H that best maps it onto A (Welch H1 at 2.9 Hz resolution, smoothed over 1/12 octave around its bulk delay) splits the difference into **tone** T (what a fixed EQ / phase filter explains) and **character** C (what none does: distortion, pumping, thump), B' - A = T + C. On synthetic pairs a filter's character leaks -53 / -62 dB re A (3 / 8 s), distortion's and pumping's tone 26-33 dB below their character; a 20 Hz high-pass, the hardest case, 12 dB below its tone. The difference streams, ABX (`part`: all / character / tone, per session; any trial that isn't the real pair is flagged exaggerated) and the pair list all use it.
- **What it shows** (character / tone, dB re A): T101 permalloy against mumetall is nearly all tone, a low shelf (+1.0 to +1.8 dB at 20 Hz, +0.3 at 50 Hz, ~0 above 100 Hz: the harder core's lower inductance), its character -31 to -52 dB; that is why its -21 dB "residual" didn't help in ABX. The built unit against nominal is mostly character. On the arpeggio and the guitar every pair's character is at -32 to -52 dB; on the new material, bass and drums at 6 dB, it is -24.6 to -31.3 dB (built vs either other unit -24.6 to -27.7): heavier limiting on LF-rich material roughly doubles it, as the condition search (item 3) expected. Character differences are where to listen, and where the caricatures should push.

**Planned next (decided 2026-10-23), after the Phase 2 core refit (Option 1), which changes every unit, so `ab-prepare` runs again** (1 and 2 done 2026-10-24, above):

1. **Difference listening and exaggeration in the A/B page** (no new renders: the matched renders exist). Play the residual A - B (after a least-squares gain alignment) turned up, to hear what a part changes; and A + k (B - A) for k = 2, 4, 8, which extrapolates along the difference (the colour-saturation analogy), loudness matched again after the extrapolation. Artifacts at large k where the gain envelopes differ: report them, don't hide them.
2. **ABX discrimination with an adaptive k staircase, and guaranteed repeats.** X is secretly A or B; hits over 12-16 trials and a binomial p-value say whether the listener can tell the pair apart at all. The staircase starts at a large k, steps down after each correct answer and up after each miss, and converges on the listener's just-noticeable k per pair: k ~ 1.5 means the real difference is just audible, k ~ 6 means preference answers on it are mostly noise. Sessions get a fixed number of repeated pairs (e.g. 3), not a chance draw; position bias (share of A answers) is recorded per session for Phase 6 to correct or discount. An obvious anchor pair checks the listener can hear a real difference in the setup.
3. **Condition search with the measurement suite** (physical, within bounds): for a pair, find the conditions where its difference is largest (gain-reduction target, Time Constant, program material: bass-heavy and quiet passages for core materials, heavy limiting for tube mismatch and thump, transients for the timing parts), measured as the residual's level, and listen there.
4. **Physical caricatures, a flagged diagnostic in the parts sandbox:** a part pushed k times further from nominal than its bounds allow (mismatch x3, a much smaller core, part spread 3; a material "amount" by interpolating or extrapolating two materials' parameters). Real circuit physics, so what is heard is a real mechanism, but not linear in k, never a genome value.

Rules for all of these: they train the ear and show what to listen for; judgments on exaggerated or caricatured stimuli are stored separately and flagged, never used as preference data or by the optimizer (liking a cranked difference doesn't mean liking the real one); everything played is still matched for gain reduction and loudness.

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
- The plugin framework is decided here (2026-10-24, the user's): the research tools stay web-based. The current lean is nih-plug (Rust, no FFI to circuitsim) with a webview editor reusing `ui-mockup/`; JUCE is the alternative. See [docs/FUTURE_DIRECTIONS.md](docs/FUTURE_DIRECTIONS.md), section 7.

## Future Directions (after Phase 8)

Brainstormed and prioritized 2026-10-24; nothing is built yet. The details are in [docs/FUTURE_DIRECTIONS.md](docs/FUTURE_DIRECTIONS.md): what exists, what to build, starting formulas, open questions. None of it interrupts Phases 5-8. In the user's priority order:

1. **Aging, together with noise sources:** a unit history (years, powered hours, storage, service) mapped to per-part parameter drift by sourced laws with Arrhenius acceleration, applied where `apply_tolerances` applies the tolerance draws.
2. **General circuits:** a generic circuit file with a macro-part library (the 670 first, byte-identical IR), KiCad as the drawing tool, and new devices (BJT, JFET, op-amp, LDR ...). This is circuit-sim M7.
3. **Stray coupling and ground networks:** layout as physical genome parameters, dipole-law magnetic coupling from the supply into T101, ground impedance, stray capacitance, channel 2 as a full channel.
4. **Temperature:** static ambient and warm-up first; electrothermal nodes only where measurement shows they matter.
5. **Tape machine and vinyl,** each with its own plan doc. Both share a new "spatial medium" block: a medium written in space, read by a transducer moving relative to it.

## Coupling Checklist

These are the mechanisms most likely responsible for emergent character. Verify each is present and measurable in the simulation:

- [ ] Control voltage on the same grids as the audio, so push-pull imbalance produces thump and signal-dependent asymmetry
- [x] Shared power supply rails whose sag affects audio path and sidechain simultaneously (Phase 3: measurable: under a 0 dBFS burst the 6386 cathode return moves 6 V through the bias choke and the 6973 screen tap sags 6 V; ripple reaches the output through tube mismatch)
- [ ] Grid current that loads the timing networks, producing program-dependent attack/release
- [x] Transformer hysteresis, so low-frequency history shapes later transients (Phase 2: Jiles-Atherton cores. Since mumetall's Rayleigh refit (2026-10-24) measurable as LF distortion that rises with level, Rayleigh-like: the nominal unit at 100 Hz, 0.0061 / 0.073 / 0.64% THD at -10 / +4 / +18 dBm in against 0.0027 / 0.059 / 0.53% with linear cores (Option 1's measurement); its effect on compression is now small: the arpeggio clip's gain per 50 ms within 0.022 dB of linear cores. The earlier "~2 dB" was the old fit's too-low linear limit, not hysteresis. Whether low-frequency history shapes later transients audibly is still to show: bass-heavy, quiet material, Phase 5's condition search)
- [ ] Per-instance tube mismatch, affecting even-harmonic balance (Phase 3 built it: every tube and part draws its own deviation, each 6386 triode separately; its effect on harmonics is Phase 4's to measure)
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
- **Mono first, or stereo/lateral-vertical from the start?** Default: mono first. (A vinyl simulator would force this: 45/45 grooves are two-channel. docs/FUTURE_DIRECTIONS.md.)
- **Tape and "one coupled simulation"** (open, 2026-10-24): may a tape machine chain record circuit -> tape medium -> playback circuit across the tape's physical boundary, or must both circuits share one simulation and supply? docs/FUTURE_DIRECTIONS.md, "Open questions".
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
