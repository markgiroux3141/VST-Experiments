# Where we left off (2026-10-28)

The resume point for this spike. The plan and done-when criteria are in
[README.md](README.md), and so is the full log of what we tried. This page is the short
version: where things stand, how to get back to it, and what to do next.

Last commit: `40c2724` ("Spike: a neural transformer core, stage 1").

## Status: stage 1, three of four checks pass

The **incremental net** (`model_inc.py`) is the one that works: run `inc1`. Its recurrent
state is the physical pair (B, H), and a static MLP (3 inputs, 3 x 64 tanh) learns one
sample's slope: `H_n = H_{n-1} + S_LIN exp(g(B_{n-1}, H_{n-1}, dB)) dB`. Closed loop in
the bench, against Jiles-Atherton:

| Check | Target | inc1 |
|---|---|---|
| Stable (idle after a loud burst) | silent, no drift | ✅ remanent B 9.581 vs 9.594 mT |
| Output residual, random test items | ≤ -60 dB | ✅ worst -85.3 dB, family means -95..-107 |
| THD vs level, 20 Hz / 50 Hz / 1 kHz, -40..+20 dBu | within 1 dB (floor -120) | ✅ within 0.2 dB |
| Remanence probe (+20 dBu 20 Hz burst, then -20 dBu 1 kHz) | tone residual ≤ -60 dB, THD within 1 dB | ❌ -48.2 dB; THD -79.9 vs -83.3; remanent B -51.4 vs -48.2 mT |

What's wrong, seen in `cache/spike/neural_core/runs/inc1/eval/bh_loops.png`:
- **The negative saturation tip is wrong**: H reaches -5.2 A/m instead of -9.5 at about
  -640 mT, with a straight segment where JA curves. The positive side is right, so the
  net hasn't learned that the material is symmetric. The descent from saturation, and so
  the remanent B, inherit this.
- **H drifts on quiet HF signals**: summing H has no restoring force, so if the slopes up
  and down are off by different amounts, every cycle leaves a small offset (open loop: the
  test items sine/000, sine/005, burst/003, burst/006). In the circuit it becomes a DC
  flux offset of about 1.5 uT: harmless, but not physical.

The **plain GRU** (`model.py`, `train.py`) is shelved: it plateaued at -8.9 dB (hidden 32)
and -10.5 dB (hidden 64) open loop, and at -9.8 dB on loud items only. Keep it as the
negative result; don't spend more time on it.

## Next steps, in order

1. **Symmetry built in (free).** The material has no preferred direction, and all three
   inputs are odd functions of (B, H, dB), so the slope must satisfy g(u) = g(-u). Use
   `g_sym(u) = (g(u) + g(-u)) / 2` in `IncNet.forward` and in `NumpyInc.eval` (the
   derivative too: only u2 depends on b, and its sign flips in the mirrored branch).
   Retrain (`train_inc.py`, ~3 min), re-evaluate. Expect the saturation tip and the
   remanence to move most.
2. **Rollout fine-tuning** if 1 isn't enough. Windows of a few hundred samples from random
   points of the training data, started at the teacher's (B, H), the net carried on its
   own H, loss on H relative to the local level. This trains away the drift and the error
   coming down out of saturation, which one-step regression doesn't see. A Python loop over
   the window's steps, batched over thousands of windows on the GPU.
3. **More data near saturation** (sines and bursts at 20-50 Hz, +10..+24 dBu, both
   polarities of DC offset) if the remanence still misses.
4. **Speed**, not measured yet. Per sample: one MLP evaluation (~8.5k multiply-adds) per
   Newton iteration, about 3 per sample. Stage 1 has no speed target; the numbers matter
   from stage 2.
5. **Stage 2** (the README's Stages): a lamination split into 20-50 layers with eddy-current
   diffusion between them as the teacher. That physics is rate-dependent, so the state will
   need more than (B, H): add a small learned hidden state next to (B, H), still at the
   fixed 96 kHz.

## Getting back into it

```sh
uv run --extra ml python -m spike.neural_core.teacher       # data (~7 min, 14 processes); only after a bench or signal change
uv run --extra ml python -m spike.neural_core.train_inc --name inc2    # ~3 min on the GPU, 60 epochs
uv run --extra ml python -m spike.neural_core.evaluate --name inc2     # ~6 min (closed loop in numpy)
```

- `--extra ml` brings CUDA torch (2.11 + cu128, the RTX 3080). `uv run` without `--extra ml`
  doesn't have torch.
- Everything generated lives in `cache/spike/neural_core/` (git-ignored, reproducible
  from the seeds): `data/{train,test}.npz`, and per run `runs/<name>/` with `net.pt`,
  `log.json` and `eval/` (summary.json, thd_vs_level.png, bh_loops.png). The teacher data
  from this session is still there; no need to regenerate it.
- `evaluate.py` takes either kind of net (it reads the run's `log.json`). Its verdict line
  is the done-when.

## Things that bit us (don't relearn them)

- **JA's H(B) jumps deep in saturation** (0.15 A/m within 0.13 uT at 0.8 T, from its RK4
  substep bounds), and the bench's Newton cycled across it. The bench now takes the
  smallest-residual iterate (`STALL_T`), and items are capped at a +24 dBu sine's peak
  (`signals.PEAK_MAX_DBU`). No stalls since.
- **NaN in training** had two causes: `sinh` of the output overflowing float32 (now soft-
  clamped at +-40), and gradients overflowing to inf over 50 ms of BPTT, which
  `clip_grad_norm_` turns into NaN weights (now 10 ms chunks, and non-finite steps skipped).
  Both only matter for the GRU.
- **A loss on the companded residual** (`asinh(r / R0)`) is dominated by the residual's
  zero crossings (a steep +-20 swing twice a cycle). The incremental net avoids it: its
  target, the log of the slope, has no zero crossings.
- **In this bench the core barely distorts at 1 kHz** (-142 dB THD at -40 dBu, a 620 ohm
  source against ~111 kOhm of reactance), so the THD check has a -120 dB floor. Low
  frequencies are where the core is audible: 20 Hz -75 to -42 dB.
- **Watching runs:** redirect training output to a log file with `python -u`, or the
  epoch lines only show up at the end.
