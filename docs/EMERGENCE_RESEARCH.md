# Going deeper: research directions for emergence

2026-11-10. A brainstorm with the user, ranked by what Claude thinks is coolest. Nothing in
it is built. It is meant mostly for offline renders: the depth here costs far more than real
time allows, and production or `master` quality (SYNTH_MASTER_PLAN.md) is where it would live.
It goes further than FUTURE_DIRECTIONS.md (aging §2, temperature §3, stray coupling §4, the
rack as a netlist §8.4, the combo amp hearing itself §8.5, the audibility map §8.2) and
INVENTED_DEVICES.md, and doesn't repeat them.

## The question

What our physics-based devices have over conventional plugins is behaviour at the limits:
the edge cases should fall out of the physics. That holds with three conditions, and every
direction below has to respect them:

1. **Only the physics we modelled emerges.** Arcing, layout parasitics, microphonics and cone
   breakup don't appear until something models them.
2. **Fitted models extrapolate at the edges.** Koren, Jiles-Atherton and Gummel-Poon are
   fitted to datasheet curves that rarely cover the corners. Past the fitted range a model
   still answers, but nobody has checked the answer. Known cases: JA can't meet all four of
   nickel's targets; its minor loops ratchet (S1's open decision); the 884's bass reads
   23-33 cents sharp where the reference itself hasn't converged (H4).
3. **Numerical error can pass for physics.** The edges are where solvers struggle. The
   Suitcase's crackle was a loose Newton tolerance, the power amp latched at +20 V
   numerically, and the 5E3 at draft-1x aliases at -8 dB relative to its harmonics.

## Where emergence comes from

Behaviour nobody designed tends to come from five sources, and each direction below adds at
least one:

- **More states:** a field instead of a lumped part, a population instead of a curve.
- **Discreteness and chance:** individual events instead of averages.
- **Coupling** across parts, across kinds of physics and across timescales.
- **History:** a state that depends on everything before it.
- **Space:** waves, local saturation, hot spots.

## Rules for every experiment here

- **Physics or numerics?** An effect counts only if it survives a tighter solve: production
  settings or the engine's converged solution, plus a change of method or step. If it
  changes, it is numerical. `--verify` does this for the 670; each experiment needs its own.
- **Inside the model's validity?** Every device used past its fitted range is reported as
  extrapolated. A first step that would serve every direction: record each device file's
  fitted range (grid volts, flux density, current) and flag a run that leaves it.
- **Loudness lies** (Hard rules): any listening comparison is matched in LUFS, and in gain
  reduction where there is any.
- **Novelty claims are hedged.** Each entry's "Prior art" lists what a short web search found
  on 2026-11-10 (standard mode, one or two queries per topic). "Not found" means not found
  in that search, not "never done". A real claim needs a proper literature search first.

## The ranking

| # | Direction | Why it's cool | Likely new? | Prerequisite |
|---|---|---|---|---|
| 1 | Voices that pull into tune with each other | an emergent musical effect, heard and reported but never predicted | likely | a real supply on a multi-oscillator circuit |
| 2 | Counterfactual hardware | the first causal map of where "analog character" comes from | likely | none |
| 3 | Charting the design space | finds regimes nobody designed, in physically valid circuits | likely for analog circuits | none (the genome exists) |
| 4 | The edges of feedback loops | the dub engineer's edge, mapped from physics | likely | the rack as a netlist (§8.4) helps |
| 5 | Tubes from their electrodes | plate curves, grid current and matching from geometry | likely for audio | the component editor's tubes |
| 6 | Noise from discrete microphysics | grit that follows the signal; settles a forum argument | Barkhausen: likely | discrete Preisach |
| 7 | Germanium from device physics | why every Fuzz Face differs, from the semiconductor | likely | the BJT model (done) |
| 8 | Wear from what was played | a device whose past shows in its sound | probably | aging (§2) |
| 9 | A nonlinear plate driven by a tube amp | the plate reverb's shimmer when overdriven | the plate isn't; the coupling likely is | the plate (done) |
| 10 | Tape at the particle level | print-through and decay on the shelf, from thermal activation | partly | tape (TM1-TM5) |
| 11 | Iron as a field | local saturation, corner crowding, lamination skin effect | probably | C2's FEM |

## 1. Voices that pull into tune with each other

**The idea.** When oscillators share a supply, its ripple and sag couple them: each draws a
current that varies within its cycle, so each modulates the rail the others run on. Close
enough in frequency (or near a simple ratio), they should pull and then lock (injection
pulling, then injection locking). Organ pipes are known to lock to their neighbours. Synth
players report the same thing with analog oscillators near unison.

**What should emerge.** A lock range that depends on the supply's impedance, the oscillators'
current draw and the detune. Beating that slows and stutters before it locks. Chords whose
intervals bend toward simple ratios. Detuned unison that "breathes" instead of beating
steadily.

**Experiments.**
1. Two of the Minimoog's oscillators near unison on a real Model D supply instead of today's
   ideal ±10 V (`minimoog_voice.yaml`'s `supply_v` / `supply_neg_v`: "ideal here"). Sweep the
   detune and find the lock range and the pulling's shape. Then the same with ideal rails as
   the control: the difference is the emergent part.
2. The Novachord's reference (`novachord.yaml`: 12 oscillators in the circuit, not the live
   tier's compiled phases) on its own power pack: whether semitone neighbours pull each other
   at all, and whether the vibrato's reeds change it.
3. The tube synth's two oscillators (LC and saw) moved onto one supply: today each has its own.
4. The poly synth (`tube_synth_poly`, MIDI_TAKES_PLAN.md, voices sharing the 5U4GB supply),
   once built: whether chords pull.

**Done when** a lock range is measured against detune and supply impedance, survives the
physics-or-numerics check, and the user has heard locked and unlocked versions of the same
part.

**Cost.** Low: the circuits exist. The Model D's supply is the main new work (its regulators
from the service manual). Offline at production.

**Prior art.** Injection locking is classical (Adler; Razavi's time-variant models, which are
written for RF oscillators and dividers). A Moog forum thread describes oscillators locking
on a common supply and attributes it to the current drawn varying within each cycle. One
poster there claims a cleaner supply made the oscillators lock and that design was dropped;
that is anecdote. No simulation of synth VCOs sharing a rail was found.

**Risks.** Every rail in a real synth is regulated, so the coupling may be tiny, and the
answer may be "inaudible at realistic values". That is still an answer. Then, in the spirit
of "realistic first, then bend", a soft supply is a panel control.

## 2. Counterfactual hardware: where analog character comes from

**The idea.** Real iron can't have its hysteresis switched off, and a real tube can't lose
only its grid current. We can do both. Remove one physical mechanism at a time from a
complete device, keep everything else identical, and ABX the version without it against the
full model on the same unit and program. That gives a causal map of where "analog character"
comes from. Hardware studies can only correlate.

**The mechanisms to ablate** (each is a switch the code mostly already has): core hysteresis
(JA → linear; Preisach → anhysteretic), core eddy loss, grid current, supply sag (ideal rails),
heater and cathode temperature (B6 off), Johnson / shot / flicker noise (B5 off), transformer
leakage and winding capacitance, the speaker's impedance on the output stage, tape's particle
grain, tape's transport.

**Experiments.** Start with the devices people argue about: the 670 (hysteresis vs. the
sidechain), the 5E3 (sag vs. the output transformer vs. the speaker's load), the 351 (bias
asymmetry, grain, transport), the U47 → V76 chain. Per device, per mechanism: matched
renders, then a difference analysis (`varimu.listen.difference`: tone vs. character) to pick
the candidates worth an ABX. The ABX itself is the user's.

**Done when** a table exists of mechanism × device: audible or not, at which drive, with what
margin, plus a short write-up. Per the user's rule, subtle differences count as verified, so
"inaudible below X" is a full result.

**Cost.** Mostly renders and listening time. It also decides what the rest of this document
is worth: a mechanism that turns out inaudible here doesn't deserve a deeper model.

**Prior art.** A 2019 Huddersfield master's thesis concluded that transformers likely produce
audible distortion, programme-dependent, and noted that "few pieces of research exist showing
the relationship between device, distortion and perception". Neural amp-modelling papers run
listening tests on their own models (loss functions, pruning, neural vs. SPICE), not on
physical mechanisms. No ablation of physical mechanisms in a coupled model was found.

## 3. Charting the design space

**The idea.** The diversity survey found 16 of 20 random genomes oscillating. That isn't only
a failure rate: it shows that most of the space is uncharted. Instead of sampling it, chart it:
quality-diversity search (MAP-Elites) over physically valid part values (and later
topologies), with audio descriptors as the archive's axes. Then numerical continuation and
Lyapunov exponents at the boundaries, to classify where the behaviour changes: period
doubling, quasi-periodicity, intermittency, locking.

**What should emerge.** Regimes nobody designed: a compressor that pumps chaotically above a
threshold, an EQ that rings at one panel corner, an amp that motorboats only at one bias. The
best of them are candidates for "realistic first, then bend" panel controls and for
INVENTED_DEVICES.md.

**Experiments.** The 670's genome first (bounded, sourced, plausibility checks exist). The
descriptors: gain reduction, its time constants, spectral centroid of the distortion,
spurious tones. Then the tube synth's voice with its panel as part of the genome.

**Done when** an archive of at least a few hundred elites exists, with a browsable map and
renders, and at least one regime is found that the survey didn't show.

**Cost.** Many renders (draft quality to explore, production for the elites). The GPU doesn't
help circuitsim; the cores do.

**Prior art.** MAP-Elites over sound is active for *digital* synthesis: Jónsson et al. evolve
CPPN-driven DSP graphs with a YAMNet classifier defining the cells, and a 2025 paper studies
the behaviour spaces themselves. Over physically simulated analog circuits: not found.
From memory, not re-checked: Thompson's evolved FPGA tone discriminator (1996) and Bird &
Layzell's "evolved radio" (2002) are the classic cases of evolution exploiting physics
nobody intended.

## 4. The edges of feedback loops

**The idea.** A tape echo with saturating regeneration, the 670 in a loop, the Lucier unit
(INVENTED_DEVICES.md P3), the rack as one netlist (FUTURE_DIRECTIONS.md §8.4) driven into
self-oscillation. Dub engineers play exactly these edges. The question is which regimes
appear (limit cycles, chaos, intermittency) and whether physics-based loops differ audibly
from DSP loops with the same delay and gain.

**Experiments.** The 351 echo with REPEAT swept through the point where it runs away, at
several DRIVE settings: the onset, the regime it settles into, how the tape's compression and
the transport's flutter shape it. The same loop with the reduced tape and with an ideal delay
plus a static saturator at the same gain: the difference is what physics adds.

**Done when** the regimes are classified along REPEAT × DRIVE, the three versions are
compared, and the user has heard them.

**Cost.** Low for the 351 (built, live and printed). Long renders: a loop's regime may take
seconds to show.

**Prior art.** Not searched separately. Nonlinear delay-loop dynamics are well studied in
optics and control (the Ikeda map). Not found applied to tape echoes from physics.

## 5. Tubes from their electrodes

**The idea.** Solve the electrons' space charge in the actual electrode geometry (Poisson plus
the electrons' motion) instead of fitting Koren's equations to datasheet curves.

**What should emerge.** Plate curves, grid current, the island effect, secondary emission and
the emission ceiling, all from geometry and the cathode's temperature. Matching becomes
geometric tolerance (grid-wire spacing, cathode coating), which may explain why matched pairs
still sound different. Electrodes that move give microphonics (with FUTURE_DIRECTIONS.md §8.5).

**How.** Electrons cross a tube in nanoseconds, so solving them every audio sample is wasted.
Solve the steady state per operating point offline (a 2D, then 3D, particle-in-cell or
Vlasov-Poisson solve, on the GPU) and tabulate it. That is the hybrid-physics principle
(HYBRID_PHYSICS_PLAN.md). Transit-time effects matter only at MHz.

**Experiments.** Reproduce the 12AX7's published curves from its published geometry, then
compare with `12AX7@1`'s Koren fit at the corners the datasheet doesn't cover. Then vary the
geometry within manufacturing tolerance and measure the spread.

**Done when** a tube's curves come from its geometry within the datasheet's scatter, and a
circuit plays it as a new component version.

**Cost.** High: a new solver, the electrode geometries (sources: tube manufacturers' design
data, x-ray images). It belongs with COMPONENT_EDITOR_PLAN.md's tubes from geometry.

**Prior art.** Particle-in-cell is standard in vacuum electronics: triode-type electron
sources (Altsybeyev et al., 2016), gated field emitters. Not found for an audio triode, nor
coupled into an audio circuit.

## 6. Noise from discrete microphysics

**The idea.** Today noise is an added source (B5). Here it comes out of the same state that
carries the signal:
- **Barkhausen noise:** individual hysterons flipping in a discrete Preisach model of the core.
  It is modulated by the signal, so it is grit that follows the music rather than hiss.
- **1/f noise** from a population of charge traps (McWhorter's model).
- **Popcorn noise** in BJTs (random telegraph noise).
- **Carbon-composition resistors' excess noise** from granular contacts, which depends on the
  current through them.

**Experiments.** Barkhausen noise first: the discrete Preisach grid exists as the tape's test
oracle (`varimu/devices/preisach.py`). Put one in an output transformer's core, scale the
hysteron count to the core's volume with a seeded draw, and measure the noise against level
and frequency. Then the ablation from §2: audible or not.

**Done when** the noise's spectrum and level dependence are measured and the audibility is
settled.

**Prior art.** No controlled study of Barkhausen noise's audibility in audio transformers was
found. Forum posters disagree (plainly audible when sweeping, or far below any amplifier's
noise floor) and note that DC bias quiets it. This is a question the simulation can settle.

## 7. Germanium from device physics

**The idea.** Simulate a germanium transistor by drift-diffusion (TCAD) rather than with
Gummel-Poon. Leakage, its steep temperature dependence and high-injection effects all emerge.
Germanium fuzz is notoriously temperature-sensitive and varies from unit to unit, and this is
the root cause of both.

**Experiments.** An AC128 from its doping profile (sources needed: Mullard's data, period
literature), tabulated over terminal voltages and temperature, played in a Fuzz Face. Then
the spread of a batch with realistic doping tolerance, and a pedal heating up on a stage.

**Done when** the device matches the AC128's published characteristics and the Fuzz Face's
known bias sensitivity.

**Prior art.** Only hobbyist work: SPICE models with a tuned saturation current and an
artificial leakage term, because Gummel-Poon can't get both Vbe and leakage right. No TCAD
of audio germanium found.

## 8. Wear from what was played

**The idea.** Aging (FUTURE_DIRECTIONS.md §2) driven by the device's actual signal history:
cathode depletion from the plate current it actually drew, electromigration, capacitor
dry-out from its ripple current and temperature, a tape head worn by the passes it made. A
device played hard for 20 years sounds different from one that sat in a closet.

**Experiments.** An accelerated life: the 5E3 played for simulated years on a duty cycle,
aged in steps, rendered at each step. The same unit with a gentle life as the control.

**Prior art.** Not searched separately. Reliability engineering models these mechanisms
(Arrhenius, Black's equation). Coupling them to a sound is likely new.

## 9. A nonlinear plate driven by a tube amp

**The idea.** A von Kármán plate (geometric nonlinearity) instead of the linear modal plate.
Driven hard enough, energy cascades upward (wave turbulence): the shimmer and crash of a gong.
In a plate reverb driven by its own tube amplifier, overdriving the drive amp would make the
plate itself bloom.

**Prior art.** Strong for the plate itself: Bilbao's energy-conserving finite-difference
schemes, Ducceschi and Touzé's modal approach, real-time gong synthesis (DAFx 2023). Not found:
a nonlinear plate in one coupled netlist with a tube drive and pickup. REVERB_PLAN.md's
"Candidates" lists the nonlinear plate; this is the reason to build it.

## 10. Tape at the particle level

**The idea.** Micromagnetics (Landau-Lifshitz-Gilbert on the particles) instead of the
Preisach ensemble. Self-erasure at high frequencies, bias as a stochastic process and
modulation noise come from the particles. Add thermal activation (Néel relaxation) and you
get print-through and the slow loss of a recording on the shelf, which gives the Vault
(INVENTED_DEVICES.md P5) a physical basis.

**Cost.** Offline only, GPU. A calibration of Preisach against it is the likely useful
outcome, not a replacement.

**Prior art.** Micromagnetic noise studies of metal-particle tape exist (Stoleriu et al.:
surface particles behave like thin films, bulk ones like thick media), mostly for digital
formats, and analog audio recording has been simulated against measured MOL / SOL data.
Print-through as a simulated mechanism: not found.

## 11. Iron as a field

**The idea.** A 2D or 3D finite-element transformer core with hysteresis per element and
eddy currents in the laminations, instead of one lumped core. Flux crowds at the corners,
saturates locally before the whole core does, and the joint gap behaves nonlinearly.

**Cost.** Offline, GPU. C2's FEM (`varimu-components fem`) is the start; it solves leakage,
not the core. The result would most likely calibrate the lumped core rather than replace it.
§2 should first show whether core hysteresis is audible at all.

**Prior art.** Not searched; field-level hysteresis FEM is standard in power-transformer
design. Its audible consequences in audio iron are likely unexplored.

## A suggested order (not agreed)

1. §2 counterfactual hardware: cheap, needs nothing new, and prices everything else.
2. §1 voices pulling: cheap, the most likely to be both new and audible.
3. §4 feedback edges on the 351: built pieces, a clear result.
4. §3 charting the space: a long background job once the descriptors are chosen.
5. §6 Barkhausen noise: small once §2 says core hysteresis matters.
6. Then the deep models (§5, §7, §10, §11), each justified by what §2 found.

## Sources (searched 2026-11-10)

- Injection locking: https://en.wikipedia.org/wiki/Injection_locking ; Razavi & Razavi, JSSC
  2023: https://www.seas.ucla.edu/brweb/papers/Journals/Hossein_JSSC_2023.pdf ; Moog forum,
  "General Theory Question": https://forum.moogmusic.com/t/general-theory-question/6636
- Transformer audibility: Huddersfield thesis, https://eprints.hud.ac.uk/id/eprint/35000/ ;
  GroupDIY, "Barkhausen noise in audio transformers":
  https://groupdiy.com/threads/barkhausen-noise-in-audio-transformers.49941 ; diyAudio, "SE OPT
  arcana": https://www.diyaudio.com/community/threads/se-opt-arcana.303180/
- Listening tests on models: https://www.arxiv.org/pdf/1911.08922 ;
  https://vbn.aau.dk/ws/files/506491931/Pruning_Deep_Neural_Network_Models_of_Guitar_Distortion_Effects.pdf ;
  https://arxiv.org/html/2403.08559v1 ;
  https://doaj.org/article/ce82677e70f84a40923c88ce9fb28a64
- Quality-diversity over sound: https://arxiv.org/abs/2512.02783v1 ;
  https://arxiv.org/abs/2606.09780
- PIC for triode-type sources:
  https://www.cambridge.org/core/journals/laser-and-particle-beams/article/different-operation-regimes-of-cylindrical-triodetype-electron-accelerator-studied-by-pic-code-simulations/E7BC7D8F4069B0C8C4A8D54680CBF389 ;
  https://arxiv.org/pdf/2011.03278
- Nonlinear plates: https://www2.ph.ed.ac.uk/~sbilbao/platepage.html ;
  https://www.dafx.de/paper-archive/2023/DAFx23_paper_19.pdf ;
  https://perso.ensta-paris.fr/~touze/PDF/ducceschi_smac2013.pdf
- Tape micromagnetics: https://old.joam.inoe.ro/arhiva/pdf4_2/Stoleriu.pdf ;
  https://researchweb.draco.res.ibm.com/publications/micromagnetic-simulations-of-exchange-coupled-core-shell-particulate-media
- Germanium in SPICE (hobbyist): https://www.diystompboxes.com/smfforum/index.php?msg=650786 ;
  https://www.diystompboxes.com/smfforum/index.php?msg=294933
