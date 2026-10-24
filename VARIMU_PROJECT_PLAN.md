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

*Status (2026-10-23): in progress, the done-when met* (see "What's left").

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
- **Plausibility checks.** The screen:
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

- **Attack is ~8x the published 0.2-0.4 ms** (CV 63% at 1.7 ms for TC1/2/6 from a burst to 10 dB of limiting). Either the manual's attack is defined differently (e.g. the CV's first movement, or a bigger overload) or the sidechain's source impedance / bridge in the model is slower than the original's. Worth a look before Phase 5's listening.
- **Low-level distortion comes from the transformer cores.** 0.16% THD (H3) at -10 dBm with the Jiles-Atherton cores, 0.003% with their linear limit; it falls as the level rises (0.07% at +4 dBm, where the tubes take over). Real permalloy at low fields follows Rayleigh's law, its hysteresis distortion falling with level. The effective-field JA fit of mumetall is almost all irreversible (Phase 2), so at low fields it overstates hysteresis. Within the manual's < 1%, but it is character: a Phase 2 follow-up (a fit with a Rayleigh region, or another hysteresis model).
- **The error estimate misses a diode turning off within a step** (circuit-sim plan, "Speed after Phase 3"): fine on the 670's events, worth knowing for other circuits.

What's left: re-measure the timing check's TC5 / TC6 short-peak release (a burst short enough to be an "individual peak"), and decide the attack question above.

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
- [x] Shared power supply rails whose sag affects audio path and sidechain simultaneously (Phase 3: measurable: under a 0 dBFS burst the 6386 cathode return moves 6 V through the bias choke and the 6973 screen tap sags 6 V; ripple reaches the output through tube mismatch)
- [ ] Grid current that loads the timing networks, producing program-dependent attack/release
- [x] Transformer hysteresis, so low-frequency history shapes later transients (Phase 2: Jiles-Atherton cores; measurable: bass-rich program compresses up to ~2 dB differently than with linear cores)
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
