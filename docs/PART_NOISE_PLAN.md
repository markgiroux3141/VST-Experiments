# Parts heard up close: noise, aging and exaggeration (a spike)

2026-11-25, the user's idea (after a video where resistors and capacitors were amplified until
their noise was audible): model individual components' physics, boost a part to hear it alone,
make aged and degraded versions, and put them into a device in the coupled simulation without
breaking the compute budget. Milestones PB0-PB3. It builds on, and partly carries out,
[COMPONENT_DEPTH_PLAN.md](COMPONENT_DEPTH_PLAN.md) (CD3 the noise sources, CD4 the component
bench, CD6 other part types) and [FUTURE_DIRECTIONS.md](FUTURE_DIRECTIONS.md) section 2 (aging
laws), with one addition of its own: an **exaggerate** setting (10x, 100x, 1000x a physical
parameter) as a condition dial ("realistic first, then bend").

## Is it worth doing (the brainstorm's answer)

- **Not interesting:** Johnson noise. It's 4kTR, the same for every resistor of a value whatever
  it's made of: boosted, it is white noise (B5 models it already). Realistic values in healthy
  parts: B6 measured capacitor leakage and DA inaudible (-47 to -62 dB) on the 670, EQP-1A and
  5E3, and the analog-magic run (closed 2026-11-14) found nothing in single parts.
- **Interesting:** the noise that isn't thermal, which is also where aged parts differ from new:

| Part | Mechanism | Amplified, it sounds like | Aging / damage |
|---|---|---|---|
| Carbon composition resistor | excess (current) noise, 1/f, proportional to the current through it | rumble and fizz that **follows the signal** | noise index up, value creeps up 5-15% |
| Transistor, diode | popcorn (burst) noise: single traps switching the base current between levels | clicks, pops, crackle | defective or stressed units |
| Paper coupling capacitor | leakage: DC on the next grid | not noise: a bias shift, gated / farty distortion | the classic vintage fault |
| Electrolytic | dries: C down, ESR up | more ripple: hum and sag | documented endurance laws |
| Transformer core | Barkhausen noise: domain walls jumping | crackle under magnetization | history more than age |
| Pot, switch | contact resistance variation (CRV) as the wiper moves, oxide | scratch while turning, dropouts | track wear, oxidation |
| Tube | flicker, gas, microphonics, cathode interface | rumble, ringing, ms memory | emission down, interface up |

What is new rather than more of the same: noise that **moves with the music** (excess noise
scales with current), and **intermittent faults** (popcorn, a dying contact): events, not a
spectrum.

## Two kinds of "exaggerated"

1. **The bench (PB0):** the part alone, its noise brought up by a large fixed gain, as in the
   video. It answers "what does this mechanism sound like", nothing about a device.
2. **In the device (PB2):** the part's physical parameter scaled (noise index x10, trap
   amplitude x100, leakage x1000) **inside the coupled simulation**. At realistic levels noise
   is tiny and linear around the clean trajectory; exaggerated, it drives stages, gets
   compressed and intermodulates with the signal. That interaction is the point, and why it
   belongs in the netlist rather than mixed in after.

## Accuracy

Noise is statistical: "accurate" means the published spectra and statistics, not waveforms.
- Excess noise: the current-noise index (IEC 60195, MIL-STD-202 Method 308: uV rms per volt of DC
  per decade, measured around 1 kHz), a resistance fluctuation dR / R with one-sided density
  K / f, K = (NI uV/V)^2 / ln 10. The noise is I(t) R dR/R: with DC, a 1/f hiss; with a signal
  current, 1/f skirts around each tone.
- Popcorn: superposed two-state Markov processes (random telegraph signals), exponential dwell
  times, an amplitude per trap.
- Barkhausen: the ABBM model (Alessandro, Beatrice, Bertotti, Montorsi 1990; Durin & Zapperi's
  review, arXiv cond-mat/0404512): a domain wall in a Brownian pinning landscape. For a
  monotonic drive its velocity is a square-root (Cox-Ingersoll-Ross) diffusion, simulated
  exactly by its noncentral chi-square transition; independent walls add into one such process.
  The drive rate sets c, and the relative fluctuation is 1 / sqrt(c): slow sweeps crackle, fast
  ones smooth out.
- Pots: the contact resistance along the track (a rough profile plus bad spots), read as the
  wiper moves; CRV is its peak variation as a share of the track's resistance (~1% healthy, >10%
  worn: the helical-wiper patent US 4,095,210 quotes both).
- References are published data (the user's rule: no bench measurements for now); a reproduction
  of the video's measurement through the UA Twin stays an option.

## Compute in a device

- Aged **values** (a leaky capacitor as a resistor across it, drifted resistors, a dried
  electrolytic): build-time values, free at run time.
- **Noise sources** are current injections into DK (B5's `NoiseCurrent`): no new states, one
  response column each; B5 measured ~+0.15x real time per noise class at draft on tube_synth.
  Excess noise reads its resistor's current a sample late (fine for noise).
- **Generators**: 1/f is B5's `FlickerFilter` (15 one-pole sections), popcorn a Markov flip per
  trap: near free.
- **Costly** (Barkhausen in a core, a resistor's voltage coefficient as a nonlinear port,
  thermal nodes): production only, and only on parts that rank high.
- **Only the top N parts** get deep models: DK's linearization gives each part's sensitivity at
  the output (CD5's audibility map).

## Milestones

**PB0. The bench.** `varimu/part_noise/` (offline Python, outside the render cache key), the
mechanisms above as references, each part alone at a fixed gain and loudness-matched, its
density in V/sqrt(Hz) at the part, every value with a source.
`scripts/part_noise_bench.py` -> `reports/part_noise/bench/` (WAVs in `audio/`, a spectrum plot,
`summary.json`, a README to listen by); `tests/test_part_noise.py` checks each generator
against its theory (Johnson's level, the noise index per decade, the dwell statistics, ABBM's
mean and 1 / sqrt(c)).
*Done when:* the user has listened to the set.

**PB1. Aging laws for the testbed.** The **Fender 5F1 Champ** (the default testbed: the
simplest real device, period carbon comps and paper / electrolytic capacitors, 0.36x real time
live, and the user plays guitar through it). FUTURE_DIRECTIONS.md section 2's history ->
parameters for its parts, a seeded draw per part; a CONDITION control (healthy, played, needs a
cap job, wreck).
*Done when:* each aged parameter has a sourced law or a bounded provisional one.

**PB2. In the Champ.** The mechanisms as IR elements in both builders and circuitsim (with
agreement tests), on the Champ's parts at realistic and x10 / x100 / x1000 settings; each part
soloable and nulled against the healthy amp (the `solo` tool); live CPU measured.
*Done when:* renders and a live session at each setting, and the cost table filled.

**PB3. Keep what is heard.** What stays a default, what is a condition dial, what is
production only; then other devices (tube_synth's LFO and oscillator, where tempco and memory
become pitch).

## Status

- 2026-11-25: plan written. **PB0 built** (the user listens):
  - `varimu/part_noise/`: `resistor` (Johnson; excess noise from a noise index on B5's unit
    flicker), `popcorn` (random telegraph signals, exact sample averages), `barkhausen` (ABBM:
    the square-root diffusion's exact transition; the crackle is the process minus its mean
    path, so a fast drive's lag leaves no harmonic lines), `contact` (a pot's track into a
    grid's capacitance), `bench` (13 parts with their values and sources);
  - `scripts/part_noise_bench.py` -> `reports/part_noise/bench/` (README is the listening
    guide; a same-gain set per group and a loudness-matched set);
  - `tests/test_part_noise.py`: Johnson's 4kTR, the noise index per decade (+-0.6 dB), the
    telegraph's occupancy and dwell, ABBM's mean and 1 / sqrt(c), no periodic part under a
    50 Hz drive, the pots.
  - Found: carbon comp at 100 V is +30 dB over Johnson (+40 aged), metal film +6; its noise
    exists only while current flows; a pot into a grid is silent however rough its track until
    the contact gaps, and a leaky coupling cap's DC is what makes the gaps loud.
- 2026-11-25 (same session, the user: "integrate this into the 5F1"): **PB1 and PB2 as a
  spike, offline** (the user listens; `reports/part_noise/champ/README.md` has the numbers):
  - `varimu/part_noise/aging.py`: four conditions (new, played, cap_job, wreck; provisional
    numbers on FUTURE_DIRECTIONS.md section 2's forms) as a transform on the built IR: carbon
    comps drift (seeded per part, high values more) and their Johnson sources follow, noise
    index by value (+6.7 dB a decade) plus the condition's, paper coupling caps get a leakage
    resistor, electrolytics lose C and gain ESR (a series resistor; new parts' from tan d 0.1).
  - Excess noise **in two passes, no engine change**: a Vccs per noisy resistor driven by a
    control input; pass 1 reads each resistor's current, pass 2 injects I(t) dR/R(t). The
    error is second order in dR/R. Same IR and B5 seed in both: pass 2 - pass 1 is exact.
  - `scripts/champ_aged.py` (production, B5 noise on; guitar at VOLUME 0.5, idle at 1.0; x10 /
    x100 / x1000 on cap_job; `--rank COND` each resistor alone), `tests/test_part_noise_aging.py`.
  - Found: aging is mostly **hum** (dried filter caps, +21 dB of 120 Hz new -> wreck) and **lost
    gain** (the leaky first coupling cap clamps V1B's grid), not hiss. Realistic excess noise is
    80+ dB under the guitar; exaggerated it is a bright, steady hiss bed that follows the playing
    only ~1 dB (the Champ's noisy resistors carry DC). Two parts carry it: V1A's plate load and
    unbypassed cathode resistor (the rest 30+ dB lower), four with leaky caps.
  - Next options: excess noise in circuitsim in one pass (a resistor-current-modulated noise
    element, both builders, a sample late), only on the ranked parts; the condition as a Play
    control on `fender_5f1` (live); the worn pot's contact in the circuit; parts where the
    signal, not DC, sets the current (a cathode follower, a feedback resistor, a passive EQ's
    network) for noise that follows the music.
- 2026-11-25 (same session): the user's ear: `barkhausen_slow_sweep` and `popcorn_defective`
  are the sounds to pursue, **each in a device where it belongs** (the user: separate devices,
  not both forced into one): Barkhausen in the tube synth's iron first; popcorn later in a
  transistor device (the Minimoog's BJTs). **The tube synth's iron, offline spike** (the user
  listens; `reports/part_noise/synth_iron/README.md`):
  - `varimu/part_noise/iron.py`: pass 1's B replayed through each core's JA model gives the
    irreversible magnetization Mirr; **landscape** avalanches (a fixed seeded barcode of sites
    along Mirr, power-law sizes of exponent 3/2, all the irreversible change by jumps: return-
    point memory, so minor loops repeat their jumps and sweeps scan new ones) or **abbm** (no
    memory); fed back as the core-node current equal to a jump of M at a fixed field. STRESS
    sets the largest jump (1 = ~1e-6 of saturation, provisional).
  - `scripts/synth_iron.py` (draft, the app's partition; scenarios sweep / wobble / riff /
    glide; `--inject filter|osc|all`), `tests/test_part_noise_iron.py`.
  - Found: the bench's ABBM scale, applied in time to a 1 cm2 core at audio-rate drive, made
    jumps as big as the audio (fixed by sizing jumps physically); the filter's iron crackles
    where it moves (plucks, envelope sweeps), -43 dB re the note at STRESS 1 on the riff, +10 dB
    per decade; on sustains memory turns it into a steady harmonic grit; the oscillator's iron
    changes the waveform, not the pitch; a free-running oscillator's pass 2 - pass 1 is phase
    walk, not crackle.
  - Next options (the user's): which model (memory or none); STRESS as a live control on
    `tube_synth` (an IR element in circuitsim: the replay is the JA core's own state, so in the
    engine it costs a lookup per core per sample).

- 2026-11-25 (same session, the user: "sounds really good, integrate it with a stress knob"):
  **STRESS is live on `tube_synth`.** The part `barkhausen: [core]` (material, path_m, stress,
  seed; both builders, a symbol `Barkhausen` in both tables), IR element `Barkhausen` (a
  medium: no SPICE, its output held at 0 V there), `varimu/devices/barkhausen.py` the reference,
  circuitsim's `barkhausen.rs` the port (the landscape in bins of BIN_FACTOR largest jumps keyed
  by Philox streams per bin, so the barcode doesn't depend on the path; the engine hands each
  medium its core device's accepted (B, H, direction): no second integration; a linear-core
  build replays instead). `tube_synth.yaml`: control `stress` (choices 0 / 1 / 3 / 10 / 30 /
  100 / 300 / 1000, default 0: the synth as before), `iron_seed`, BKTA / BKTB on the filter's
  cores; the app's label and knob list. Tests `tests/test_barkhausen.py` (the engine against the
  reference to 8e-17), fixtures regenerated (`export_app_fixtures.py`,
  `export_editor_fixtures.py`, `kicad/varimu.kicad_sym`). Live and the comparison with the
  prototype: `reports/part_noise/synth_iron/README.md` "STRESS live" (up to 300 without
  dropouts at 50 ms; 1000 needs a longer buffer). Next (the user's): popcorn in the Minimoog.

- 2026-11-25 (same session): **popcorn in the Minimoog, offline prototype**
  (`scripts/moog_popcorn.py` -> `reports/part_noise/moog_popcorn/`, README the listening guide):
  the bench's defective traps as a base-emitter current in one transistor at a time (the ladder's
  Q29, the VCA's Q16, the sample and hold's Q23_b, oscillator 1's expo Q7_o1), DAMAGE 1-100000,
  one pass through a control input. Found: the ladder is the place (at 1000 the pops ring at the
  cutoff, ~5 dB under the note); the expo and the S&H need far more than any real defect (16 c at
  10000); "pass minus no trap" has a ~-37 dB floor in the partitioned voice (events shift by a
  sample). Next (the user's): a live DAMAGE (and HEAT) element on the ladder.

## Open decisions (the user's)

1. The testbed: the 5F1 Champ (default) or another device.
2. Published references only (default), or the video's measurement reproduced on real parts.
3. Which video: if it measured particular parts, they are targets.
