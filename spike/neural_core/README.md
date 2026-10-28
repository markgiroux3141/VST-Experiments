# Spike: a neural transformer core

**Question.** Can a small recurrent network, trained on an accurate but slow simulation
of a component with memory, stand in for that component *inside a circuit*: stable,
accurate down to the low-level distortion, and (eventually) cheaper than the physics?

Started 2026-10-28 from a brainstorm with the user: expensive physics offline as the
teacher, its behaviour baked into weights, the net run in the circuit.

## Decisions

- **One fixed rate: 96 kHz** (`sim_settings.yaml`'s rate), the user's call. The net is a
  discrete cell, one step per sample: `h_n = F(h_{n-1}, B_n)`, `H_n = G(h_n)`. No
  oversampling, no variable steps, no draft-1x host rate. Other rates (a continuous-time
  net, `dh/dt = f(h, B)`) are a later problem if the spike works.
- **The component is the magnetic core**, not a tube: it has memory in the audio band
  (hysteresis now; eddy-current diffusion in stage 2). A tube at audio rates is a static
  map (electron transit is nanoseconds) and doesn't need a recurrent net.
- **Closed loop is the test.** Inside a circuit the core's B depends on the current it
  draws, so each sample Newton asks the net for `H(B)` and `dH/dB` at a frozen state many
  times, then accepts. The net is trained open loop (teacher-forced on recorded B), but it
  passes only when it runs in the loop.
- **The test bench is our own fixed-step circuit** (`bench.py`), not circuitsim: T101
  (the 670's input transformer, values from `config/circuits/fairchild_670.yaml`) between
  a 600 ohm source and its load, trapezoidal at 96 kHz, one Newton unknown (B). The
  integrator is the same for both cores, so it cancels out of the comparison.
- **Rules this spike bends** (spike/README.md): the net has no SPICE implementation (as
  the JA core, the user's 2026-10-21 exception) and, during the spike, no Rust one. Data,
  weights and plots go to `cache/spike/neural_core/` (git-ignored, reproducible from the
  seeds); summaries and numbers go into this README.

## Stages

1. **Method, on a teacher we trust (in progress).** Teacher: our own Jiles-Atherton
   mumetall core (`varimu/devices/core.py`). It's no faster than a net would be, so stage 1
   is about whether the net can be *right* in the loop, not speed.
   Done when, in the bench at 96 kHz, net against JA on held-out signals:
   - stable everywhere: no divergence or oscillation, including silence after loud LF
     bursts and 10 s of idle;
   - output residual at or below -60 dB re signal (rms) from -30 to +20 dBu;
   - THD vs level at 20 Hz, 50 Hz and 1 kHz within 1 dB of JA's from -40 to +20 dBu
     wherever JA's is above -120 dB, and below -120 dB wherever JA's is (the low-level
     end is the hysteresis distortion of mumetall's Rayleigh region; in this bench JA
     gives 1 kHz -142 dB at -40 dBu, -94 dB at +10 dBu, and 50 Hz -56 dB at +10 dBu:
     a 620 ohm source against ~111 kOhm of reactance at 1 kHz);
   - remanence: after a loud LF burst, the recoil and the next small signal's distortion
     match.
   Speed per sample is measured and reported, no target.
2. **An expensive teacher.** A lamination split through its thickness into 20-50 layers,
   each its own JA material, coupled by eddy-current diffusion: the skin effect inside the
   laminations that our lumped eddy loss doesn't have, too slow to run in a render. Train
   on it, compare to it and to the lumped core. Here the net has to win on speed.
3. **Into circuitsim** (only if 1-2 work): the cell as a `Device` with state, in Rust,
   at the decided rate.

## The hard part, expected

B at T101 spans five decades: ~20 uT at -40 dBu, 1 kHz up to 0.8 T (saturation) at
+20 dBu, 20 Hz. At the bottom the hysteresis that makes the distortion is ~1e-3 of H
(Rayleigh: mu = mu_i (1 + r H)), so the net must be right to ~1e-4 of H there and to a
few percent in saturation. A plain net in float32 can't even represent a 1e-10
quadratic term next to O(1) activations, so the inputs and output are companded
(`asinh`), and the loss is relative per sequence. Whether that's enough is what stage 1
finds out.

## Files

- `bench.py`: the test bench (T101 in a 600 ohm line), a pluggable core (JA or net).
- `signals.py`: excitation families, seeded per item.
- `teacher.py`: runs the bench with the JA core on every signal, saves (B, H) sequences.
- `model.py`: the net (torch, for training) and its numpy cell with `dH/dB` (for the bench).
- `train.py`, `evaluate.py`: training; the done-when checks.

```sh
uv run --extra ml python -m spike.neural_core.teacher        # data -> cache/spike/neural_core/data/
uv run --extra ml python -m spike.neural_core.train
uv run --extra ml python -m spike.neural_core.evaluate
```

## Log

**2026-10-28: bench, teacher, first runs.**
- Bench (T101, 620 ohm, trapezoidal at 96 kHz): JA runs 3-10k samples/s in Python, Newton
  takes 3 iterations. THD of the JA core in the bench: 20 Hz -75 dB at -40 dBu to -42 dB at
  +20 dBu; 50 Hz -90 to -56 dB; 1 kHz -142 to -86 dB. The linear-limit core's output is
  -44..-91 dB (family means) and -28 dB (worst item) from JA's: the margin a net must beat.
- JA's H(B) jumps deep in saturation (0.15 A/m within 0.13 uT at 0.8 T: its RK4 substep
  bounds), and Newton cycled across it on a +34 dBu peak; circuitsim's looser tolerance
  never sees it. The bench takes the smallest-residual iterate (`STALL_T`) and items are
  capped at a +24 dBu sine's peak (`PEAK_MAX_DBU`). No stalls since.
- Data: 448 training items (224 s, 399 s to teach on 14 processes), 79 test items (54 s).
  The residual r = H - S_LIN B spans 9e-8 A/m (1 kHz, -40 dBu: 4e-4 of H) to ~10 A/m (it
  exceeds H at LF: mumetall's permeability rises far above its origin value).
- v1 (relative loss through log1p, sinh output): slow (-12 dB open-loop residual after 120
  epochs), then sinh overflowed float32 and both runs went NaN (hidden 64 before epoch 40).
  Fixed with a soft clamp of y (+-40) and a loss on the companded output (v2).
- v3 (10 ms BPTT chunks, inputs /4, non-finite steps skipped): stable but slow. Best open
  loop -8.9 dB (hidden 32), -10.5 dB (64), and -9.8 dB on loud items only (peak B 10 mT-1 T,
  `--b-peak-range`): the dynamic range isn't what stops it. The plain GRU is shelved.
- **The incremental net (`model_inc.py`, `train_inc.py`): the state is the physical pair
  (B, H), the net a static MLP (3 x 64, tanh) for one step's slope, H_n = H_{n-1} +
  S_LIN exp(g) dB.** Plain regression on 21M samples: 157 s for 60 epochs, rms error of
  log-slope 0.014, open-loop residual -35.5 dB (two-tone -55, level sweep -50, chirp -46,
  noise -44, multisine -37; sine -6.5 and burst -10 from a few quiet HF items, where H drifts
  over thousands of cycles: summing H has no restoring force).
- **inc1 closed loop (evaluate.py): stable, residual and THD pass; remanence misses.**
  Residual vs JA: family means -95..-107 dB, worst item -85.3 dB (linear core: -44..-91,
  worst -28). THD within 0.2 dB of JA at 20 Hz and 50 Hz from -40 to +20 dBu, and at 1 kHz
  down to -20 dBu (-40 dBu: -136.5 vs -142, under the -120 floor). Idle after a loud burst:
  remanent B 9.581 vs 9.594 mT. Remanence probe (+20 dBu 20 Hz, cut at B's extreme, then a
  -20 dBu 1 kHz tone): remanent B -51.4 vs -48.2 mT (6.5% off), the tone's residual -48.2 dB
  (needs -60) and THD -79.9 vs -83.3 dB. Next: rollout fine-tuning (multi-step windows from
  teacher states: the drift and the descent from saturation), more data near saturation.
