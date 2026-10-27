# Future directions: general circuits, aging, temperature, stray coupling, tape, vinyl, UI

Brainstormed with the user on 2026-10-24. **Nothing here is built yet.** This
is the starting point for future sessions. It records what the repo already
has for each idea, what is missing, the formulas to start from, and the
priorities the user agreed to.

Ground rules carry over unchanged (CLAUDE.md "Hard rules"):
- Every value needs a `source`.
- The genome is physical only.
- One coupled simulation.
- Each device model has two implementations, with an agreement test.
- Everything is seeded and reproducible.

The functional forms below are **provisional starting shapes** (model
knowledge). Each needs a cited source, or a fit to datasheet endpoints, before
it drives a render.

## Decisions (2026-10-24, the user's)

1. **Timing.** None of this interrupts the main plan. Phase 5 continues
   (item 4, physical caricatures, then item 3). Items 1 and 2 below become plan
   phases after Phase 8. Tape and vinyl get their own plan docs, like
   [CIRCUIT_SIM_PLAN.md](CIRCUIT_SIM_PLAN.md), when started.
2. **Priority order:**
   1. aging, together with noise sources;
   2. a general circuit format plus KiCad import (circuit-sim M7, "a second
      circuit");
   3. stray coupling and ground networks (after noise sources);
   4. thermal: static ambient and warm-up first, full electrothermal later;
   5. tape and vinyl, which share one new "spatial medium" building block.
3. **UI.** The research tools (`varimu listen`, `/ab`, reports) stay web-based.
   Polish them with CSS if wanted, or wrap them in Tauri if a native window is
   ever wanted. The plugin framework is decided in Phase 10, once a real-time
   model exists. The current lean is nih-plug (Rust, no FFI to circuitsim)
   with a webview editor that reuses the [ui-mockup/](../ui-mockup/) HTML.
   JUCE (C++, with JUCE 8's WebView UI) is the alternative
   ([UI_PIPELINE.md](UI_PIPELINE.md) section 9 assumed JUCE).
   **Superseded 2026-10-27 (the user's):** the user-facing product is a standalone
   native Rust app (egui / eframe, no plugin): [NATIVE_APP_PLAN.md](NATIVE_APP_PLAN.md).

## Open questions for the user

- **Tape and "one coupled simulation".** The tape is a physical boundary
  between the record and playback electronics, separated by a transport delay
  of tens of ms. The question is whether chaining record circuit -> tape
  medium -> playback circuit is acceptable. The alternative is that both
  circuits must run in one simulation, sharing the machine's power supply.
- **Stereo.** Vinyl is inherently two-channel: 45/45 groove walls, with
  lateral = L+R and vertical = L-R. It forces the plan's "mono first" open
  decision.
- **Plugin licensing.** Check the licences of the VST3/CLAP SDKs and Rust
  bindings, and JUCE's licence tiers, before choosing a framework.

---

## 1. General circuits: our own schematics for any audio device

**What exists.**
- The circuit IR ([varimu/circuit/ir.py](../varimu/circuit/ir.py),
  `crates/circuitsim/src/ir.rs`) is already generic: Resistor, Capacitor,
  Inductor, Coupling, VoltageSource, SineSource, Winding and Device (Triode,
  Pentode, JunctionDiode, VacuumDiode, MagneticCore).
- Both engines run any IR.
- What is 670-specific is [varimu/circuit/netlist.py](../varimu/circuit/netlist.py)
  (~900 lines). It turns `config/circuits/fairchild_670.yaml` into IR, with
  pots, pads, switches, transformers, tube instances, tolerance draws and the
  idle channel 2 written in Python.

**To build:**
- **A generic circuit file plus a parts library of macro parts** (pot, tapped
  pot, rotary switch, T-pad, transformer, tube with heater, rectifier bridge).
  Macro parts expand into IR elements.
  - Every parameter can be overridden with `--set` or made a genome entry, and
    each keeps its `source`.
  - netlist.py's helpers (`_pot`, `_tapped_pot`, `_t_pad`, `transformer`,
    `tube_instance`, `apply_tolerances`) become library code.
  - The 670 becomes the first circuit file. Done when it builds a
    byte-identical IR, with the goldens in `tests/fixtures/netlist_golden/`
    unchanged.
- **Drawing: KiCad, not a home-made editor.**
  - Custom symbols carry fields (value, source, genome bounds, part class).
  - An importer reads KiCad's exported netlist.
  - Optional later: a read-only schematic view in the listen app.
- **New devices**, each in Python + Rust + SPICE with agreement tests:
  - BJT (Gummel-Poon subset), JFET, MOSFET;
  - op-amp macro model (GBW, slew, rails);
  - zener;
  - LDR / opto cell (the LA-2A's T4B: a lamp or electroluminescent panel
    driving a photoresistor with memory);
  - thermistor, incandescent lamp.
- **Robustness on circuits nobody has tuned.**
  - DC operating-point fallbacks: source stepping, a small helper
    conductance.
  - Pre-flight checks for floating nodes and loops of voltage sources or
    inductors. CLAUDE.md's T104 notes show why.
  - A capacitance on every rectifier node (the Phase 3 lesson).

### Component variables

Bold means modeled today. Everything else is a candidate parameter.

| Part | Variables |
|---|---|
| Wire / trace | **R**; copper tempco (+0.393 %/K); inductance (order of uH/m); capacitance to neighbours and chassis; contact resistance at joints (oxidized contacts are slightly rectifying); skin effect (negligible at audio: ~0.46 mm in copper at 20 kHz) |
| Resistor | **R, tolerance**; tempco; voltage coefficient (carbon composition: R depends on the voltage across it, a real distortion source; metal film ~0); excess (current) noise; Johnson noise; self-heating and thermal time constant; humidity uptake; parasitic L and C |
| Pot | **track R, tolerance, taper, tap**; wiper contact resistance and noise; track wear |
| Capacitor | **C, tolerance**; ESR; ESL; leakage (insulation resistance); dielectric absorption (parallel series-RC branches); voltage coefficient (high-K ceramics lose much of C under DC bias); loss tangent vs frequency; tempco; piezo microphonics. Electrolytic: formation state, dry-out. Paper: moisture leading to leakage |
| Transformer / choke | **turns, core material (Jiles-Atherton), cross-section, path length, gap, lamination thickness, resistivity (eddy loss), leakage, winding capacitance, winding R**. Missing: winding geometry (layering, interleaving -> leakage and capacitance from first principles), Faraday shield, copper temperature, remanent magnetization at the start of a run, shielding can |
| Tube | **Koren parameters, variable-mu profile, grid current and contact potential, interelectrode capacitances (Cgk, Cgp, Cpk in `varimu/devices/triode.py`), emission scale, mu spread**. Missing: heater voltage -> cathode temperature -> emission; gas (reverse grid current); grid emission; cathode interface resistance; heater-cathode leakage (hum); microphonics; shot and flicker noise |
| Diode / rectifier | **Is, n, Rs, junction capacitance** (fixed at 27 C: `varimu/devices/diode.py`). Missing: reverse recovery, temperature, selenium aging |
| Sources | **mains V and Hz**. Missing: mains source impedance; mains waveform distortion (real mains is flat-topped by everyone's rectifier loads) |

## 2. Aging (priority 1, together with noise sources)

Age is physical history, so it belongs in the genome.

**Already there:**
- `emission_scale` in `config/genome_bounds.yaml` is sourced as cathode aging.
- `varimu.sim.setup.adjust` re-trims B+ ADJ / BALANCE / ZERO, as the manual
  says to do "when tubes age". An aged unit can then be re-adjusted the way a
  technician would.

**Design.**
- No per-part age knobs. The unit gets a short **history**:
  - years since build;
  - powered hours;
  - storage humidity and temperature;
  - service events (recapped, retubed).
- Each part class gets a sourced **aging law** mapping that history to
  parameter changes, plus a seeded per-part draw. Derive seeds per part as
  CLAUDE.md requires, so two units of the same age differ.
- It runs as a transform in the same place as `apply_tolerances` /
  `part_factor` / `unit_draws` in netlist.py, after the tolerance draw.

Temperature enters through Arrhenius acceleration:

    t_eff = integral_0^t exp[(Ea/k) (1/T_ref - 1/T(tau))] dtau
    p_i(t) = p_i0 * f_i(t_eff; theta_i, eps_i)     (theta_i: sourced law, eps_i: seeded per-part draw)

| Part | What happens | Starting form (provisional) |
|---|---|---|
| Electrolytic capacitor | Electrolyte evaporates: C falls, ESR rises; life doubles per 10 K cooler | L(T) = L_rated * 2^((T_rated - T)/10 K); u = t_eff / L; C = C0 (1 - 0.2 u^m), ESR = ESR0 (1 + u^n). Fit m and n to datasheet endurance end-of-life criteria (typically dC <= -20 %, tan delta <= 2x initial). Unpowered storage de-forms the oxide: high leakage at power-up until it reforms |
| Paper / oil capacitor | Moisture ingress: insulation resistance falls, loss rises. A leaky coupling capacitor puts positive DC on the next grid (the classic vintage fault) | Leakage vs moisture uptake, roughly sqrt(t) diffusion |
| Carbon composition resistor | Drifts upward with humidity, often 5-15 %+ over decades, high values most | dR/R = A t_eff^n, n ~ 0.5 (common empirical form) |
| Film resistor | Small drift | Same form; datasheet load-life specs (e.g. dR <= x % after 1000 h at 70 C) as anchors |
| Tube | Emission falls; cathode interface resistance grows (worst in tubes idled near cutoff); gas | Emission curve fitted to an end-of-life criterion (e.g. gm down to ~70 % of new); interface as a growing RC in series with the cathode |
| Selenium rectifier | Forward resistance rises (well documented) | Rs(t) increasing. Moves the 670's bias supply (GR301) |
| Pot | Track wear, wiper oxidation: scratchiness | Contact resistance and a noise source scaled by wear |
| Transformer | Barely ages electrically | Remanent magnetization from DC events is history, not age: the JA state at the start of a run |

What aging adds beyond today's tolerance ranges:
- **Correlated** drift: all electrolytics dry together, all carbon
  compositions creep up together.
- **New mechanisms**: leaky capacitors, interface resistance, noisy pots.

Several of these need **noise sources** first (the plan's Coupling Checklist
"(Later)" item and its open decision on noise). The weak spot is data: most
drift literature is reliability-oriented, so expect provisional laws that
become bounded genome parameters.

## 3. Temperature (priority 4)

**Static: ambient and warmed-up state.**
- An operating condition, like `mains_v_rms` in the circuit file's
  `controls`, not genome.
- It uses the same transform seam as aging:
  - copper: R(T) = R0 [1 + 0.00393 (T - T0)];
  - diodes: SPICE's standard Is(T) and Vt = kT/q (today fixed at 27 C);
  - carbon composition tempco;
  - electrolytic ESR vs T;
  - core permeability vs T.

**Warm-up.**
- A unit 5 minutes after switch-on differs from one 2 hours in. That's why
  the 670 manual adjusts after warm-up.
- Heater temperature follows the heater supply (from the mains) with a time
  constant of tens of seconds.
- **Aging and temperature interact.** A healthy oxide cathode is
  space-charge-limited, so plate current barely depends on heater
  temperature. A worn cathode turns emission-limited and becomes sensitive to
  mains voltage and warm-up. Model emission as a function of cathode
  temperature with Richardson-Dushman (J = A T^2 exp(-W/kT)) behind the
  space-charge limit.

**Dynamic (electrothermal).**
- Each hot part gets a thermal node: C_th dT/dt = P(t) - (T - T_amb)/R_th.
- That is an RC circuit, so it fits in the same coupled simulation as new IR
  elements: thermal R and C, and a device's dissipated power as a source. It
  also needs devices with a temperature input (Python, Rust, SPICE).
- Expected to be inaudible within 8 s excerpts of tube gear. It matters for
  solid-state (Vbe tracking, thermal memory in class-AB stages). Measure
  before building.
- Thermal coupling between neighbours (a rectifier tube heating the
  electrolytics) feeds back into aging.

## 4. Stray coupling: components affecting each other (priority 3)

**Modeled today:**
- Intended magnetic coupling inside each transformer (windings on a core
  node).
- Coupling through the shared supply rails (Coupling Checklist, Phase 3).
  Ripple reaches the output through 6386 bank mismatch as hum, at -121 dBFS
  nominal.
- The ~30 kHz tuned-plate tuned-grid oscillation found and damped in the
  early end-to-end slice (CLAUDE.md, "ngspice render speed") is the piano "sympathetic resonance" analogy: two
  resonators (leakage and winding capacitance) ringing together, through the
  circuit.

**Not modeled:**
- stray magnetic fields between parts;
- stray capacitance between wires;
- ground impedance (every ground is the ideal node "0");
- mechanical coupling;
- thermal coupling.

**Is it meaningful? Yes, mainly as hum, buzz and crosstalk, not as
character.** That's why real gear has mu-metal cans, input transformers at
90 degrees to the mains transformer, and star grounds.

| Mechanism | Size in practice | Notes |
|---|---|---|
| Mains transformer T302, chokes L301 / L302 -> input transformer T101 | The biggest stray effect in tube gear | The aggressor current is rectifier charging pulses, so it's buzz (120 Hz harmonics), not a pure 60 Hz hum. It grows with supply load, so it is **program-modulated** |
| Ground impedance | Often as big; depends on layout | Amp-level charging pulses through milliohms of shared ground return |
| Output transformer T102 -> T101 | A magnetic feedback path | Matters in high-gain amps; small at the 670's ~unity gain |
| Stray capacitance (wire to wire, channel to channel) | HF crosstalk rising 6 dB/oct | Plate-to-grid lead capacitance adds to Miller |
| Microphonics (chassis vibration -> tube grids) | Small in rack gear | The closest analogue to sympathetic resonance: transformer magnetostriction hum shaking the tube elements |
| Thermal neighbours | Indirect | Through aging |

**To build:**
- **A layout description:** positions, orientations and shielding of magnetic
  parts, and wire runs. It becomes physical genome parameters.
- **Stray magnetic coupling** as a small mutual coupling with a dipole law:
  k(r, theta) ~ k0 (r0/r)^3 g(theta) / S_shield. Dipole far field:
  B ~ mu0 m / (4 pi r^3) * sqrt(1 + 3 cos^2 theta).
  - IR `Coupling` covers linear inductors.
  - Coupling into a Jiles-Atherton core likely needs an extension: an external
    field (H) term on the core node, in `varimu/devices/core.py` and
    `crates/circuitsim/src/devices/core.rs`.
- **A ground network** in place of the ideal ground: small R and L per return
  path, star vs daisy-chain as a layout choice.
- **Stray capacitances** between named nodes.
- **Channel 2 as a full channel** instead of the idle lumped load. Supply
  crosstalk between channels then comes for free. It doubles render cost.
- Do it after noise sources, so hum has a noise floor to sit in.

## 5. Tape machine (priority 5; own plan doc when started)

**Physics chain:**
1. The record amplifier drives the record head, a gapped core (already
   modeled: Winding + MagneticCore + gap).
2. The head field (Karlqvist gap field) plus AC bias (~50-150 kHz)
   magnetizes the moving particles.
3. The remanent magnetization along the tape gives the playback head flux
   (reciprocity: the same head field function), and the playback EMF
   N dPhi/dt drives the playback amplifier.

These would **emerge from geometry** instead of being filters:
- gap loss ~ sinc(pi g / lambda);
- Wallace spacing loss 54.6 d / lambda dB;
- thickness loss, head bump, self-erasure at HF;
- the 6 dB/oct playback rise (lambda = v / f).

Transport:
- wow from capstan eccentricity;
- scrape flutter (the tape between guides is a vibrating string).

History:
- print-through between reel layers (pre-echo);
- sticky-shed binder (drag, squeal);
- worn head gaps.

**Reuse:**
- The JA core: hysteresis is the standard physical-tape core. Prior work:
  J. Chowdhury, "Real-Time Physical Modelling for Analog Tape Machines",
  DAFx-19.
- circuitsim for the machine's electronics and bias oscillator.
- The transformer model for the heads.
- Seeded randomness for particle noise.
- The listening, preference and optimization stack.

**New: the spatial medium.**
- A 1D array of hysteretic cells moving at v(t), written by one transducer
  and read by another.
- Only cells within a few gap lengths of a head are active, so it's feasible
  offline. The bias needs that part sampled well above the bias frequency.

**Genome:**
- tape formulation: JA parameters fitted to tape datasheets (coercivity,
  retentivity, MOL, SOL);
- head gaps;
- transport tolerances.

Operating conditions:
- tape speed;
- bias level, set by an alignment procedure (over-bias by x dB at 10 kHz),
  like `setup.threshold`.

## 6. Vinyl: carved groove, simulated stylus, dust (priority 5; own plan doc)

1. **Cutting.**
   - The cutting amplifier (with RIAA pre-emphasis) drives the cutter head
     (mass-spring with a feedback coil); the stylus motion carves the groove
     walls along the spiral (45/45: lateral L+R, vertical L-R).
   - Variable pitch from a preview signal.
   - Resolution: near the label the groove moves ~0.2 m/s
     (2 pi r * 33.33/60 at r ~ 6 cm), so 20 kHz is a ~10 um wavelength.
     Sub-um sampling is a few hundred thousand points per second per wall.
2. **The surface (seeded).**
   - Random roughness from the compound.
   - **Dust:** discrete particles with a size distribution. Each kicks the
     stylus, and the cantilever, cartridge and RIAA chain shapes the click,
     so crackle character comes from the playback hardware.
   - **Scratches:** features at a fixed angle, so they tick once per
     revolution.
   - **Wear:** play count rounds the HF off the walls (an aging variable).
   - Pressing defects: non-fill, warp, an off-centre hole (0.55 Hz wow).
3. **Playback.**
   - The stylus-tip centre follows the groove wall **dilated by the tip
     shape** (grayscale morphological dilation), so these emerge from
     geometry:
     - tracing distortion;
     - the pinch effect;
     - worse inner-groove distortion.
   - Tip contact is a Hertz spring, F = (4/3) E* sqrt(R) delta^(3/2).
   - It drives tip mass, cantilever compliance and damper (an elastomer that
     stiffens with age and cold), and the arm's effective mass. That gives the
     arm/cartridge resonance and a tip-vinyl contact resonance.
   - **Mistracking** emerges where the contact force reaches zero.
   - Tracking-angle error comes from arm geometry. Bearing rumble is a
     mechanical noise source.
4. **Electrical.**
   - Moving magnet: EMF ~ velocity, into coil R and L, then cable capacitance
     (an HF resonance), then a real tube RIAA phono stage in circuitsim.
   - Moving coil: through a step-up transformer (the transformer model).

**Shared with tape:** "a medium written in space, read by a transducer moving
relative to it". Build that block once.

## 7. UI

See Decisions, item 3.
- The art pipeline is framework-independent and is what makes a plugin look
  professional: relit filmstrip knobs, lit/unlit overlays, needle ballistics
  ([UI_PIPELINE.md](UI_PIPELINE.md), [IMAGE_GEN_GUIDE.md](IMAGE_GEN_GUIDE.md)).
- Before Phase 10, there's nothing real-time to put a plugin UI on: circuitsim
  renders ~12-24x slower than real time (CLAUDE.md speed notes).
