# The tube synth's iron crackling

docs/PART_NOISE_PLAN.md: Barkhausen avalanches in tube_synth's four mumetall cores (the reactor
filter's TA / TB, the oscillator's OTA / OTB), driven by each core's own irreversible
magnetization (`varimu/part_noise/iron.py`). Regenerate with
`uv run --extra listen --extra fast python scripts/synth_iron.py --model landscape|abbm --inject
filter|osc|all` (~2 min each; WAVs not committed). Draft quality (what Play plays), the app's
partition, the synth's own noise on.

## How it works

- Pass 1 renders the synth; each core's B is replayed through its Jiles-Atherton model, which
  gives the **irreversible** magnetization Mirr per sample (only that jumps).
- **landscape** (the default): the core's pinning is a fixed, seeded barcode of sites along Mirr,
  with power-law jump sizes (ABBM's 3/2). Where the iron goes, it jumps at the same places every
  time: a sweep scans new sites (crackle), each audio cycle's minor loop retraces the same ones
  (return-point memory: a steady grit, part of the tone, which shifts as the sweep moves it).
- **abbm** (no memory): new random avalanches whatever the path, as the bench's
  `barkhausen_slow_sweep`. Its STRESS scale isn't matched to the landscape's (it runs ~15-20 dB
  louder at the same label): compare by ear, loudness-matched.
- Pass 2 feeds each jump back as the current at the core node that equals a jump of M at a fixed
  field, so every winding on the core hears it, eddies damp it, the filter acts on it.
- **STRESS** sets the largest jump: 1 is realistic (~1e-6 of saturation, sub-uT jumps in these
  1 cm2 cores), 10 / 100 / 1000 fewer and bigger jumps. Provisional: nothing is fitted to a
  measured core.

## The scenarios

- `sweep`: one long note, the envelope sweeping the filter.
- `wobble`: a held note, the LFO (~0.4 Hz) sweeping the cutoff.
- `riff`: six plucks, the filter snapping open on each.
- `glide`: legato octaves with GLIDE.

## What to listen to

1. `landscape_filter/audio/riff/stress_0.wav` then `stress_1` ... `stress_1000`
   (loudness-matched): the filter's iron, the crackliest scenario.
2. `landscape_filter/audio/crackle_only/riff_stress_1000.wav`: the crackle alone (pass 2 - pass
   1, one gain per scenario). Then `sweep_` and `wobble_`.
3. The same in `abbm_filter/`: crackle without memory.
4. `landscape_osc/audio/*/`: the oscillator's iron instead (no crackle-only files: any nudge to a
   free-running oscillator walks its phase, so pass 2 - pass 1 is the whole note).

## What came out

| landscape, the filter's iron, crackle re the note | STRESS 1 | 10 | 100 | 1000 |
|---|---|---|---|---|
| riff | -42.7 dB | -34.3 | -22.1 | -13.4 |
| sweep | -50.6 | -41.8 | -31.7 | -18.6 |
| glide | -52.1 | -43.2 | -30.7 | -21.6 |
| wobble | -60.7 | -49.7 | -33.2 | -30.3 |

- About 10 dB per decade of STRESS (the jumps' sizes go as its square root). Its peaks stand
  ~35 dB above its average: crackle, not hiss.
- **Where the iron moves, it crackles**: on each pluck's filter snap, on the envelope's sweep
  (`*.png`: broadband while the iron sweeps, collapsing into the note's harmonics on the
  sustain, the memory's grit). The slow LFO wobble crackles least: it moves the iron slowly and
  little, and the audio's minor loops dominate the drive.
- The cores sit at +-0.56-0.66 T (mumetall saturates at 0.8 T): the irreversible share falls
  when the envelope pushes them deeper (the dips in the plots' top panel), so a high cutoff
  crackles less than a low one.
- **The oscillator's iron** barely moves the pitch (cycle-to-cycle jitter 2-5 cents with or
  without, the supply's own); with memory its jumps repeat each cycle and change the waveform,
  not the pitch.

## STRESS live (the engine, 2026-11-25)

The tube synth now has a STRESS selector (0 off, the default; 1, 3, 10, 30, 100, 300, 1000):
`BKTA` / `BKTB` (part `barkhausen`) on the filter's cores, a medium in circuitsim
(`crates/circuitsim/src/barkhausen.rs`, reference `varimu/devices/barkhausen.py`) that reads
each core device's accepted state after every sample and feeds the jumps back in one pass.
`scripts/synth_iron_engine.py` -> `engine/` renders the scenarios through it.

| riff, crackle re the note | STRESS 1 | 10 | 100 | 300 | 1000 |
|---|---|---|---|---|---|
| the prototype (two passes) | -42.7 dB | -34.3 | -22.1 | | -13.4 |
| the engine (one pass) | -49.0 | -46.1 | -31.9 | -24.9 | -16.8 |

The engine is quieter at the low end: its landscape is cut into bins (100 largest jumps wide),
each pinned so its jumps add up to its width, which removes the slow wander the prototype's one
long staircase had; the character matches (`engine/riff_compare.png`), and the engine's 300 is
about the prototype's 100-1000.

Live (Play's draft, a 50 ms buffer, a held note with envelope and wobble, 12 s): STRESS 0 75-82%
load, 1 ~83%, 100 ~85%, 300 ~92% (no dropouts up to here), 1000 90-106% with 7-9 dropouts (the
core's own integration takes more substeps when its flux jumps: use a longer buffer or render).
