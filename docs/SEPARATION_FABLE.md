# Separation revisited: the Fable brainstorm as work packages

2026-11-16, at the user's request: a second look at track separation by Claude Fable 5, written
so that a later session on any model can build each idea without having been in the
conversation. Fourteen work packages, SR0-SR13. SR0 is a shared bench, SR1 is the listening
that has been owed since 2026-10-31.

**As written: nothing here is built and nothing was run.** No model, circuit, engine or app code
changed. What was read for this document: [SEPARATION_PLAN.md](SEPARATION_PLAN.md),
[SCENE_ANALYSIS.md](SCENE_ANALYSIS.md), the separation parts of ROOM_LOOP_PLAN.md (R5, R8), the
rules and "What exists" of [ANALOG_MAGIC_FABLE.md](ANALOG_MAGIC_FABLE.md), and the code named
under "What exists" below. No web search was made: every citation that is not already in
SCENE_ANALYSIS.md is tagged [memory].

Tags on claims:
- **[code]**: read in the code on 2026-11-16; the path is given. Line numbers drift: when one is
  off, search for the name.
- **[doc]**: stated with its source in SCENE_ANALYSIS.md or SEPARATION_PLAN.md.
- **[memory]**: from the model's memory, not checked. Check before quoting it in a report.
- **[estimate]**: a figure derived here, not measured.

Every package is a hypothesis until it is measured **and heard**. "Inaudible" is a full result
(the user's rule: subtle differences count as verified).

## The user's question

> When you hear a really good mix, the sounds sometimes don't touch each other. How do we get
> maximum separation of sounds, and make some sound warm, some cold, bright or dark?

Two goals, and they are not the same:

1. **Separation**: each sound can be followed on its own inside the mix.
2. **Identity**: each sound has its own colour (warm, cold, bright, dark, near, far, hard, soft).

The user's ruling on means (2026-11-16): simulating feasible analog devices is important, but
**any processing is allowed** if it produces psychoacoustic effects that make the brain tell the
sounds apart. This document therefore has two tiers (see "Two tiers").

## What "separation" is made of

Four different things, each with its own lever. A package says which one it works on.

| Kind | What it means | Measured by | Budget |
|---|---|---|---|
| **Energetic** | The target's time-frequency cells are not covered | Glimpse proportion (`metrics.py`) | Zero-sum for static tone: brightening one track covers another [doc: both studies found separation "moves between the tracks"] |
| **Grouping** | The ear forms the target as one object and the rest as others | Harmonic cancellation, onset coincidence, temporal coherence (`grouping.py`) | Positive-sum: timing, harmonicity and not sharing a nonlinearity help every track |
| **Informational** | The target is audible but confused with a similar sound | Not measured yet; driven by similarity [doc] | Positive-sum: making tracks dissimilar helps both |
| **Identity** | The colour each sound has | Not measured yet (SR7) | A palette to be assigned (SR8) |

The earlier work measured the first two, on one pair of sounds, by models only.

## What was tried (2026-10-31 to 2026-11-05)

All [doc]; numbers in SEPARATION_PLAN.md, SCENE_ANALYSIS.md section 4 and ROOM_LOOP_PLAN.md R5.

| Tried | Result (by the models) |
|---|---|
| The same chain on both tracks | Nothing |
| Opposite chains (670, EQP-1A, 5E3; U47 -> V76 against a clean omni) | Separation moves to the brighter track; it is the chain's spectrum, not its pattern or texture |
| Independent tape flutter per pass | Nothing at real depths; the literature agrees (FM incoherence is not a grouping cue). Withdrawn |
| Reverb on the accompaniment | The costliest thing measured: -12.6 dB of the lead's cancellation benefit, a third of its glimpses. On the lead: almost free |
| A nonlinear bus against the same device per track | 5E3 bus: the lead's cancellation benefit 15 dB -> 0-1 dB, glimpses halved. 670 bus: the same, less |
| The masker 30 ms late (no device) | The largest grouping change of all: coherence 0.59 -> 0.19, shared onsets 1.00 -> 0.36 |
| Stereo panning by level (R5) | The big lever in the room experiment: +5.6 dB |

**What limits all of it:**

1. **Nothing was heard.** `scripts/separation_listen.py` was never run:
   `data/judgments/separation/` does not exist [code: checked 2026-11-16]. Every result above is
   a model's opinion. SR1 fixes this first.
2. **One worst-case pair**: two tube-synth lines, one patch, one register, the masker on the
   target's grid. A real mix has different instruments.
3. **Physical only.** Both documents rule out anything but chains, parts and performance. The
   one non-physical move (a 30 ms shift) won.
4. **Real chains are small.** One pass of U47 -> V76 at 100 dB SPL is -44 to -48 dB of
   distortion [code: `reports/chain_passes/`, the session of 2026-11-14]. Chains are a colour
   lever at realistic levels, not a separation lever. Level (drive) is what makes them larger.
5. **Never studied:** identity (warm / cold), signal-aware processing, depth as a goal,
   binaural tricks beyond panning, and choosing chains per track as an optimization.

## Two tiers

- **Oracle tier**: plain DSP with no physical counterpart required. It answers "what is the most
  separation any processing can buy on this material". It lives in `varimu/separation/` and is
  never referenced by a circuit file, a device or the app.
- **Physical tier**: the project's devices (circuits, tape, rooms) doing the same job. Each
  oracle package ends by asking how much of the oracle's gain a physical device recovers
  (SR9, SR10).

The hard rule "the genome is physical only" is untouched: nothing here is in a genome. Whether
an oracle processor ever becomes a feature of the app is the user's decision (Open decisions 1).

## Rules for whoever builds this

The project's rules (CLAUDE.md) as they apply here. Follow them without being asked.

1. **One package at a time**, in the order of "Order and dependencies" unless the user picks
   another. A package is done when its "Done when" is met and its tests pass.
2. **Do not change a model, a circuit file or a device file.** If a result suggests one, write
   the options with numbers and stop: that decision is the user's.
3. **Where code goes.** Python in `varimu/separation/` (it exists and is outside the render
   cache key, which covers only `varimu/{sim,circuit,devices}` and `config.py`). Scripts
   `scripts/sep_<name>.py`. Tests `tests/test_sep_<name>.py`. Results
   `reports/separation/<package>/README.md` with its JSON and plots (WAVs under `reports/` are
   git-ignored: `.gitignore` `reports/**/*.wav`). Intermediate audio
   `cache/separation/<package>/`. The user's judgments `data/judgments/separation/`
   (git-ignored: `data/judgments/*`).
4. **Do not edit `varimu/sim`, `varimu/circuit` or `varimu/devices`.** Any edit there changes
   every render's cache key.
5. **Do not add to the web app** (`varimu listen`): it is being retired. Listening tests are
   terminal scripts.
6. **Every value has a source.** A constant in new code carries a comment with a citation,
   `web: <url>` or `provisional: model knowledge (...)`.
7. **Reproducible.** All randomness through `np.random.default_rng([seed, zlib.crc32(name)])`.
8. **Loudness lies, twice.** A louder track sounds more separated. So each stem keeps its
   loudness through any processing (`bench.rematch`, SR0), and every pair of mixes the user
   compares is matched in LUFS.
9. **A measure a processor optimizes cannot judge that processor.** SR2 raises the glimpse
   proportion by construction. Judge it by the measures it does not touch and by ear.
10. **Check a measure's floor first.** Before trusting a new measure on real audio, run it on a
    signal where the answer is known (identity processing, a pure linear filter). The
    2026-11-14 chain experiments reported a "character" that was the fit's own floor.
11. **Self-agreement is not validation.** A new mechanism needs a reference outside the model
    (the user's ear here) before anything is called "works".
12. **Tests.** Per package run only its own tests (`uv run --extra fast --extra listen pytest
    tests/test_sep_<x>.py`). The full suite is batched; say that it is owed.
13. **Estimate a run's time before starting it** and tell the user when it exceeds a few
    minutes. Time one render first; do not trust the rates quoted here after a code change.
14. **The user's listening time is the scarce resource.** Plan each session to 15 minutes or
    less and say how long it will take before asking. "Listening" below gives the arithmetic.
15. **Commands.** Renders need `uv run --extra fast ...`; loudness needs `--extra listen`
    (pyloudnorm); playback needs `--with sounddevice` (it is in no extra).
16. **Windows.** Paths with spaces (`stems/Did she mention my name/full/`) need quoting; use
    `pathlib`. Do not write patch scripts as shell heredocs; use the Write tool.

## What exists (the facts every package leans on)

All [code], read 2026-11-16.

**Energetic measures** (`varimu/separation/metrics.py`):
- `match_loudness(x, fs, target_lufs=-23.0)`, `loudness_lufs(x, fs)` (pyloudnorm, BS.1770).
- `cell_energies(x, fs, frame_s=0.02)` -> (48 ERB bands 80 Hz-12 kHz, frames): Hann frames of
  40 ms hopped by 20 ms.
- `glimpse_proportion(target, rest, fs, *, local_snr_db=3.0, range_db=50.0, notes=None)`.
  `notes` is the target **before processing**: only the cells where it was present count, so
  energy that processing adds elsewhere (a reverb tail between notes, distortion harmonics) is
  not counted as the notes being heard. Without it a hall scored +5.5 dB for nothing.
- `level_for_proportion(target, rest, fs, proportion, *, notes=None)`: the gain on the target
  at which its glimpse proportion equals `proportion` (bisection).

**Grouping measures** (`varimu/separation/grouping.py`; mono arrays; each resamples to 24 kHz
inside): `temporal_coherence(t, m, fs)` -> `{"rates", "cross", "within"}`; `onsets(x, fs)` ->
times in s; `onset_coincidence(t, m, fs, window_s=0.03)`; `f0_track(x, fs)` (YIN, 60-800 Hz);
`harmonic_cancellation(t, m, fs, *, t_clean=None, m_clean=None)` -> `{"gain_db",
"residual_db", "voiced_t", "voiced_m", ...}`; `envelope_snr(t, m, fs)` -> `{"snr_env_db",
"per_mod"}`; `shares(bus, target, masker)`; `all_measures(t, m, fs)`. Tests with known answers:
`tests/test_grouping.py`.

**Binaural measures** (`varimu/rooms/binaural.py`): `band_measures(t, m, fs)` (per ERB band the
better channel's target-to-masker ratio and the BMLD of the equalization-cancellation model)
and `better_ear_glimpse(t, m, fs, notes)`. **Arrays are `(2, n)`, channels first.**
`soundfile.read` gives `(n, 2)` and the player wants `(n, 2)`: transpose at the boundary.

**The study's audio is still on disk** (git-ignored):
- `cache/separation/conditions/<name>/{target,target_changed,masker}.wav`: mono, 96 kHz, 8 s,
  each at -23 LUFS. 25 conditions (`dry`, `T5e3_M670`, `flutter_independent`,
  `room_Thall_Mbooth`, ...). If missing: `uv run --extra fast --extra listen python
  scripts/separation_study.py`.
- `cache/separation/grouping/{5e3,5e3_hot,670_hot,eqp1a}/{per_track,bus,residual}.wav`: mixes
  at -20 LUFS (not separate stems).
- Predictions: `reports/separation/summary.json`, `reports/separation/grouping.json`.

**The listening harness.**
- `scripts/separation_listen.py`: a three-interval odd-one-out, 2-down 1-up (70.7 %), on the
  **changed note** (the target's D4 becomes E4 at beat 4). It scales the target linearly under
  a fixed masker. `--room` plays the stereo mixes of R5.
- `varimu/magic/listen.py`: the same pieces as a library: `player(fs, device, channels)`,
  `staircase(make_trial, start_db, min_db, max_db, rng, play, fs, name)` where
  `make_trial(level_db, odd)` returns the three intervals, `abx(a, b, trials, rng, play, fs,
  name)`, `binomial_p(correct, trials)`. Its `save` writes under `data/judgments/magic/`: do
  not use it; write your own under `data/judgments/separation/`.
- **Trap:** `listen.staircase` and `listen.abx` build the silent gap as a 1-D array
  (`np.zeros(int(GAP_S * fs))`), so stereo intervals `(n, 2)` fail in `np.concatenate`. Fix it
  once in SR0: build the gap as `np.zeros((int(GAP_S * fs),) + iv[0].shape[1:])`.

**Real material.** `stems/Did she mention my name/full/{bass,guitar,harmonies,lead vocal}.wav`:
96 kHz, 24 bit, stereo, 157.08 s. `.../sample/` holds the same four at 6.36 s. They are the
user's own cover on modern clean gear (ANALOG_MAGIC_FABLE.md "Status"). A reference balance and
pans exist in `scripts/lightfoot_mix.py` `MOVES`: loudness re the lead (LU) bass -7, guitar
-3.5, lead vocal 0, harmonies -5; pans 0, -0.5, 0, +0.5.

**Rendering through a device.** Two routes:

1. *The app's print* (`crates/varimu-app/examples/print.rs`): a mono file at 48 kHz through a
   chain of inserts, cached as the app caches prints.
   ```
   cargo build --release -p varimu-app --example print
   target/release/examples/print.exe --file IN.wav --quality draft-1x \
       --device pultec_eqp1a --set hf_boost=0.5 --set hf_boost_freq_khz=8 --trim 0 \
       --cache cache/separation/prints --out OUT.wav
   ```
   Device names are the ids in `panel::DEVICES` (`crates/varimu-app/src/panel.rs`).
   `scripts/lightfoot_mix.py` `run_chain` is the pattern from Python. It has **no key input and
   no wet / dry flag** (its flags: `--file --out --cache --rate --seconds --quality --device
   --set --trim`).
2. *Python* (`varimu/magic/render.py`): `through(circuit, x, *, overrides=None,
   quality="production", noise=None, controls=None, probes=("out",), cache=True)` ->
   `{probe: array}`. `x` is on the dBFS scale **at the settings' rate (96 kHz)**: resample a
   48 kHz stem up with `scipy.signal.resample_poly(x, 2, 1)` and the result down again.
   `through_many(jobs)` runs jobs on threads. `controls` are passed **in volts, not dBFS**: for
   a key input multiply by the circuit's input full scale, as
   `varimu/measure/keyed_suite.py` does:
   ```python
   from varimu.circuit import spec
   from varimu.sim.io import full_scale
   from varimu.magic import render
   c = spec.load_circuit(spec.circuit_path("fairchild_670_keyed"))
   v_in, _ = full_scale(render.settings("production"), c)
   y = render.through("fairchild_670_keyed", bed96, overrides={"key_mode": 1, "key_depth": 0.45},
                      controls={"key": lead96 * v_in})["out"]
   ```
   The control array has the same length and rate as `x`.

**Panel controls of the devices named below** (from the circuit files; `--set` keys):

| Device | Controls |
|---|---|
| `pultec_eqp1a` | `lf_freq_hz` 20 / 30 / 60 / 100, `lf_boost`, `lf_atten`, `hf_boost_freq_khz` 3 / 4 / 5 / 8 / 10 / 12 / 16, `hf_boost`, `bandwidth`, `hf_atten_freq_khz` 5 / 10 / 20, `hf_atten` (rotations 0-1) |
| `pultec_meq5` | `low_peak_hz`, `low_boost`, `dip_hz`, `dip`, `high_peak_hz`, `high_boost` |
| `pultec_hlf3c` | `low_cut_hz` 0 (off) / 50 ... 2000, `high_cut_hz` 1500 ... 15000 / 0 (off) |
| `api_550a` | `lf_gain_db` / `mf_gain_db` / `hf_gain_db` in -12 ... 12, `lf_freq` / `mf_freq` / `hf_freq` 1-5, `lf_shelf`, `hf_shelf` |
| `fairchild_670` | `input_atten_db`, `ac_threshold`, `time_constant` 1-6, `dc_threshold` |
| `fairchild_670_keyed` | the 670's plus `key_mode` (0 INT, 1 EXT), `key_depth` 0-1; control input `key` |
| `fairchild_670_stereo` | per channel `..._2`; `mode` 1 LEFT & RIGHT, 2 LATERAL & VERTICAL; audio input `in_r` |
| `ssl_bus_comp` | `threshold`, `ratio` 2 / 4 / 10, `attack` 0-5, `release` 0-4, `makeup`, `key_mode`; control input `key` |
| `urei_1176` | `input_atten_db`, `output`, `attack`, `release`, `ratio` 4 / 8 / 12 / 20 / 0 (all buttons) |
| `univibe` | `speed`, `intensity`, `volume`, `mode` 0 / 1, `cancel` |
| `plate_reverb` | `stereo`, `drive`, `decay_500hz_s` 1.0-4.8, `return_level`; output wet only |
| `ampex_351_echo` | `drive`, `capstan_hz` 40-80, `send`, `repeat`, `speed` 0 (7.5 ips) / 1 (15 ips); output wet only |
| `ampex_351_insert` | the aligned machine as an insert (drive it with the trim) |

**The study's room** (`varimu/separation/room.py`): `ROOMS` = `home`, `booth`, `hall`;
`impulse_response(room, source_m, mic_m, fs, *, ism_s=0.08, length_s=None, seed=0)` (omni to
omni, mono). Near / far positions: `scripts/separation_study.py` `NEAR`, `FAR` (0.3 m and
2.45 m in `home`). The full room (stereo, mics, directivity): `varimu/rooms/`, ROOM_LOOP_PLAN.md.

**A time-varying delay** already exists: `varimu/separation/flutter.py` `read_at(x, pos,
taps=32, beta=8.0)` reads `x` at fractional sample positions `pos` (a Kaiser-windowed sinc).
Vibrato and time warps use it.

**Linear circuits in closed form:** `varimu/measure/ac.py` `transfer(ir, f_hz, "out")` gives the
complex response of a **linear** IR (no tubes: a device element raises `Unsupported`). The
HLF-3C is linear; the EQP-1A, MEQ-5 and 550A are not (their networks are, their amplifiers are
not).

**Distortion against tone.** Do not use `varimu.listen.difference.decompose` to call something
"character": its fit floor equals what it reports on steep filters. Use the method of
`scripts/chain_passes.py` (`multisine`, `measure_h`, `residual_db`): measure the linear response
H on a multisine at the same level, apply it exactly, and take the residual of `y` against
`g H x`, brick-walled to 40 Hz-20 kHz. Check its floor on a pure filter first.

**Speeds** (CLAUDE.md, measured earlier; time one before a batch): the 670 prints at 0.42x real
time at draft-1x and 11.4x at production; the 351 insert ~27x at production with the GPU;
mic chains ~5.5x at production.

---

## SR0. The bench

One module every package uses, so that every result is on the same material, balance and
measures. Build it first, with its tests.

### `varimu/separation/bench.py`

```python
WORK_FS = 48_000   # the session's rate (the app's prints); the stems are 96 kHz

def load_stems(folder: Path, fs: int = WORK_FS) -> dict[str, np.ndarray]:
    """Every WAV of the folder by its stem name: the mid (L + R) / 2, float64, at fs."""

def excerpt(stems, fs, seconds=20.0) -> tuple[int, int]:
    """(start, stop) samples of the window in which every stem sounds the most."""

def balance(stems, fs, lu: Mapping[str, float], pans: Mapping[str, float]) -> Balance:
    """Gains that put each stem at lu[name] LU relative to the stem at 0 LU, and its pan."""

def rematch(processed, reference, fs) -> np.ndarray:
    """processed scaled to reference's integrated loudness (mono or (n, 2))."""

def pan(x, position) -> np.ndarray:
    """(n, 2): constant power, position -1 (left) ... +1 (right)."""

def mix(stems, bal: Balance, *, stereo: bool) -> np.ndarray:
    """The balanced sum: (n,) with stereo False (pans ignored), else (n, 2)."""

def score(stems, dry, fs, bal, *, target: str, reference=None) -> dict:
    """Every measure for `target` against the rest (see below)."""

def collision_map(stems, fs, bal) -> dict:
    """Per pair of stems: (bands, frames) booleans where both are present and within 3 dB."""
```

**How each works.**

- `load_stems`: `soundfile.read(..., dtype="float64")`, mean over the channel axis, then
  `scipy.signal.resample_poly(x, 1, 2)`. Stem names are the file stems ("lead vocal" has a
  space).
- `excerpt`: per stem the rms of 400 ms blocks in dB; a block is *active* when within 30 dB of
  that stem's loudest block (as `sounding_db` in `scripts/lightfoot_mix.py`). Slide a window of
  `seconds` in 1 s hops; choose the window that maximizes the **minimum over stems** of the
  active share; ties go to the earliest. Print the result: the harmonies only sing in parts of
  the song, so check that their active share in the chosen window is over 0.5, and say so if
  not.
- `balance`: loudness per stem **over the excerpt** (`metrics.loudness_lufs`), gains from
  `lu`. The default `lu` and `pans` are `lightfoot_mix.MOVES`' numbers (copy them into a
  constant `REFERENCE_MIX` with that source in a comment; do not import the script).
- `rematch`: `loudness_lufs` of both; pyloudnorm needs at least 0.4 s and takes `(n, 2)` for
  stereo. For an all-silent input return it unchanged.
- `pan`: gains `cos(theta)`, `sin(theta)` with `theta = (position + 1) pi / 4`.
- `score` returns, for the target against the summed rest (all after `balance`):
  - `glimpse`: `metrics.glimpse_proportion(t, rest, fs, notes=dry_t)`.
  - `energetic_db`: minus `metrics.level_for_proportion(t, rest, fs, p_ref, notes=dry_t)`,
    where `p_ref` is the glimpse proportion of `reference` (the unprocessed balanced stems;
    default: `dry`). Positive = the target can drop that many dB and keep the reference's
    glimpses. This is SEPARATION_PLAN.md's "energetic separation".
  - `grouping`: `grouping.all_measures(t, rest, fs)`.
  - `self_comodulation`: `grouping.temporal_coherence(t, t, fs)["cross"]`: how far the
    target's own bands move together (SR4 uses it).
  - with stereo stems: `binaural.better_ear_glimpse` and the mean over bands of
    `binaural.band_measures`' better-ear ratio plus BMLD.
  - `loudness`: each stem's LUFS (to prove rule 8 held).
- `collision_map` is a diagnostic picture (a PNG per pair in the report): where to act.

**Tricky bits.**

1. **`notes=` must be time-aligned with the processed target.** A device adds latency (the
   351's heads: 133 ms at 15 ips), and SR3 shifts tracks on purpose. Pass `dry` already moved
   by the same delay. Find a device's delay with `varimu.magic.null.align(a, b, fs)` (it returns
   the fractional delay) and remove it before scoring.
2. **`harmonic_cancellation` assumes one F0 per source.** With a polyphonic "rest" (guitar +
   bass + harmonies) the YIN track is meaningless. Report `voiced_m` beside every `gain_db`,
   and compute cancellation only between pairs of single-line stems (lead vocal against bass).
   Do not put a polyphonic pair's `gain_db` in a headline table.
3. **Mono measures on stereo mixes**: the grouping measures take mono. Give them the mid, and
   let the binaural measures speak for the stereo part.
4. **The glimpse range is relative to the target's loudest cell** (`range_db=50`): a stem with
   one loud consonant can shrink its "present" set. Keep the default; note it if a stem's
   present share is under 5 % of its cells.
5. `cell_energies` uses `hop = int(0.02 * fs)`: all stems must be the same length and rate.

### `scripts/sep_listen.py`: three listening tasks

All through `varimu.magic.listen` (`player`, `staircase`, `binomial_p`) after the stereo gap
fix. Results to `data/judgments/separation/<task>/<stamp>.json`, rewritten after every
condition. Play gain +10 dB on -23 LUFS material, as `separation_listen.py`.

- `presence` (a masked threshold on real stems): three intervals of the **same** processed
  bed; one also has the target, at `level_db` re its mix level. 2-down 1-up from 0 dB, floor
  -50 dB. A lower threshold = the processing opened more room.
  - **The bed must be identical in all three intervals.** If the processing is keyed by the
    target (SR2, SR3, SR9), key it with the target at its **mix level**, once, and reuse that
    bed in every interval and at every staircase level. Otherwise the user can pick the odd
    interval by hearing the bed duck, not the target.
  - Excerpt: 2.0 s containing a clear phrase of the target, 20 ms raised-cosine fades.
- `ab` (a blind preference): pairs of mixes, each pair LUFS-matched
  (`varimu.listen.matching.match_loudness([a, b], fs, target=-23.0)` -> `([a', b'],
  Matched)`). Each trial plays the
  two in a random order and asks one fixed question; the questions are an argument:
  `lead` ("in which is the lead clearer?"), `apart` ("in which do the parts sit more apart?"),
  `prefer` ("which do you prefer?"). 10 trials a pair; report the count and `binomial_p`.
  8 s excerpts.
- `rate` (SR7's calibration): one clip, then two numbers 1-7 typed (warm 1 ... cold 7, dark 1
  ... bright 7); `r` replays.

**Listening arithmetic** [estimate]: a staircase trial is 3 x 2 s + 2 gaps of 0.4 s + ~3 s to
answer = ~10 s; 25-40 trials = 4-7 minutes a condition. An `ab` pair is 10 x (2 x 8 s + 3 s) =
~3 minutes. Plan sessions of at most three staircases or five pairs.

### Tests (`tests/test_sep_bench.py`)

- `excerpt` on four synthetic stems, one of which only sounds in seconds 30-50: the window
  lies inside 30-50.
- `balance` then `loudness_lufs` of each scaled stem: the `lu` differences within 0.1 LU.
- `rematch(0.5 * x, x)` returns `x` within 0.05 dB.
- `pan(x, 0)`: both channels `x / sqrt(2)`; `pan(x, -1)`: right is zero.
- `score` with `stems == dry`: `energetic_db` is 0 within 0.1 dB; with the target +6 dB:
  `energetic_db` is +6 within 0.5 dB.
- The stereo gap fix: `listen.staircase` runs on `(n, 2)` intervals with a stub `play` and
  scripted answers (monkeypatch `builtins.input`).

**Done when** the tests pass and `scripts/sep_bench.py` writes
`reports/separation/bench/README.md`: the excerpt chosen, the reference balance, the reference
mix's `score` for every stem as the target, and the collision maps. **Cost:** one session.

---

## SR1. Hear the old predictions

**The question.** Do the model measures agree with the user's ear? Everything else leans on the
answer. This is SCENE_ANALYSIS.md proposal 8, never done.

**Conditions** (the synth pair, the changed-note staircase of `scripts/separation_listen.py`):

| Condition | Why | Prediction [doc] |
|---|---|---|
| `dry`, run twice (first and last) | The repeatability of the user's threshold | - |
| `masker_30ms_late` | The largest grouping change, no energy moved | Coherence 0.19, onsets 0.36; glimpses unchanged |
| `T5e3_M670` | The largest energetic change | +10 dB energetic |
| `room_Thall_Mbooth` and `room_Tbooth_Mhall` | Reverb on the lead against reverb on the bed | Bed in the hall: -12.6 dB cancellation; lead in the hall: ~free |
| `flutter_independent` | A predicted null | Nothing |
| 5E3 per track against 5E3 bus | The harmonicity claim | Bus: cancellation 15 -> 0 dB, glimpses halved |

**What to build.**

1. `masker_30ms_late`: a new folder in `cache/separation/conditions/` holding `dry`'s target
   and changed target and its masker delayed by 30 ms (prepend zeros, keep the length), as
   `scripts/grouping_study.py` does in `condition_measures`.
2. **The bus pair cannot use the linear staircase.** The staircase lowers the target under a
   fixed masker by scaling it; on a nonlinear bus the target's level changes what the bus
   does. Render a ladder instead: for `g` in +8, +6, ..., -40 dB (the staircase's steps are 6,
   4, 2 dB from 0, so every level it can reach is even), `bus(g t + m)` and `bus(g t_changed +
   m)` over the excerpt (`EXCERPT_S = (1.15, 4.0)` plus the render's own settle), with
   `render.through("fender_5e3", ...)` at production through `through_many`, at the levels and
   settings of `scripts/grouping_study.py` `bus_experiment` (each track at -23 LUFS, one gain
   so the louder peaks at -12 dBFS, the 5E3's volume 0.5). The per-track
   twin is linear in `g` (the fader is after the insert): `g dev(t) + dev(m)`. Add a loader to
   `separation_listen.py` (a `--ladder DIR` option) that picks the files for a level instead
   of scaling. 50 short renders: time one first.
3. Run `uv run --extra listen --with sounddevice python scripts/separation_listen.py dry
   masker_30ms_late T5e3_M670 ...`. Eight staircases are about 45 minutes [estimate]: split
   into three sessions, `dry` in the first and the last.

**How to read it** (`scripts/sep_calibrate.py` -> `reports/separation/calibration/README.md`):

- Repeatability `r` = the difference between the two `dry` thresholds.
- Per condition: the threshold's shift against `dry` beside every measure's shift.
- A measure is **trusted for sign** when it has the right sign on every condition whose
  threshold moved by more than `max(r, 2 dB)`, and **trusted for size** only if its rank order
  matches the thresholds' (Spearman's rho, reported with its small n).
- A condition the ear moves and no measure predicts is the most valuable row: say so plainly.

With one listener and seven conditions this is a sanity check, not statistics. Do not fit
weights to it.

**Done when** the table exists and the README says which measures later packages may quote as
evidence and which only as hints. **Cost:** half a session of code, three short listening
sessions.

---

## SR2. Mask-aware ducking (oracle)

**The idea.** Turn the bed down only in the time-frequency cells where the target is present
and could win, and nowhere else. It works on **energetic** separation directly. Commercial
"unmasking" processors do this [memory].

**Hypothesis.** A few dB of ducking in winnable cells lowers the target's masked threshold by
several dB with little audible damage to the bed, because a brief gap in a sound that a louder
sound covers is filled in by the ear (the continuity illusion: Warren 1970; Warren, Obusek and
Ackroff 1972 [memory]).

### `varimu/separation/oracle.py`

```python
def duck(bed: Sequence[np.ndarray], key: np.ndarray, fs: int, *, depth_db: float = 9.0,
         margin_db: float = 3.0, policy: str = "winnable", attack_ms: float = 5.0,
         release_ms: float = 120.0, lookahead_ms: float = 10.0, n_fft: int = 2048,
         hop: int = 256, range_db: float = 40.0) -> tuple[list[np.ndarray], np.ndarray]:
    """Each bed stem with the same time-frequency gain applied; the gain (bins, frames) in dB.
    `key` is the target at its mix level."""
```

**Steps.**

1. STFT of the key and of each bed stem: `scipy.signal.stft(x, fs, window="hann",
   nperseg=n_fft, noverlap=n_fft - hop)`; invert with `istft` and the same arguments (scipy
   normalizes by the window overlap, so a modified STFT inverts correctly). At 48 kHz that is
   a 43 ms window and a 5.3 ms hop.
2. **Bands as a partition of unity.** Centres spaced 0.5 on the ERB-number scale from 50 Hz to
   16 kHz (`erbn(f) = 21.4 log10(1 + 0.00437 f)`, as `metrics.erb_edges_hz`). A weight matrix
   `W[band, bin] = cos^2(pi / 2 * d)` for `|d| < 1`, else 0, with `d = (erbn(f_bin) -
   erbn(centre)) / 0.5`. At every frequency inside the range the weights sum to 1, so band
   gains map back to bins smoothly. Bins outside the range get gain 1. (Hard-edged ERB bands
   are narrower than one bin below ~150 Hz and leave bands empty: that is why this form.)
3. Band powers `T = W |K|^2` for the key and `M = W sum_i |B_i|^2` for the summed bed (powers
   add; cross terms ignored).
4. Present cells: `T > max(T) * 10^(-range_db / 10)`.
5. The gain a present cell needs: `g_req = sqrt(T / (M * 10^(margin_db / 10)))`.
   - `policy="winnable"` (default): duck only where `10^(-depth_db / 20) <= g_req < 1`; where
     even the full depth cannot win the cell, leave the bed alone. The glimpse account says a
     lost cell is lost at any margin, so ducking it is damage for nothing.
   - `policy="always"`: `g = clip(g_req, 10^(-depth_db / 20), 1)` in every present cell.
6. Smooth in time, per band, in dB: first a look-ahead (`scipy.ndimage.minimum_filter1d` over
   the next `lookahead_ms` of frames, so the gain is down before the onset; set `origin` so
   the window looks **forward** and test that on an impulse), then a one-pole follower with
   the attack constant while the gain falls and the release constant while it rises.
7. Bin gains `G = W^T g` (linear gains, not dB), multiplied onto every bed stem's STFT; invert;
   trim to the input length.

**Tricky bits.**

1. **Circular measure** (rule 9): this raises the glimpse proportion by construction. Its
   evidence is the presence staircase, the `ab` test, and the measures it does not optimize
   (SNRenv, onset coincidence).
2. **Loudness**: ducking lowers the bed's loudness a little. Report both the raw result and the
   `bench.rematch`-ed one, and listen to the rematched one, so the gain is never "the bed is
   quieter".
3. **Bed damage** must be reported with every setting: `20 log10(rms(bed_out - bed_in) /
   rms(bed_in))`, and the bed's `temporal_coherence` with the key. Expect the cross-coherence
   to go **negative** (the bed's envelope now mirrors the lead's); that is the audible
   "pumping" signature and it is a cost.
4. **Do not key the bed with itself.** Bleed between stems would do that. Check the stems for
   bleed first: the peak of the normalized cross-correlation between any two stems within
   +-50 ms should be under 0.05 over the excerpt; report it in SR0's README.
5. Time resolution: the 43 ms window smears a gain change by about +-20 ms. That is fine here
   and wrong for onsets, which is why SR3 works in the time domain.
6. Several targets: give each stem a priority; a stem is ducked by the sum of the stems above
   it. Start with one target (the lead vocal) and get that heard before generalizing.

### Tests (`tests/test_sep_oracle.py`)

- Identity: with a silent key the bed comes back within 1e-9 of its rms, away from the first
  and last window.
- A key of 1 kHz tone bursts (200 ms on, 300 ms off) over pink noise, `policy="always"`,
  `depth_db=9`: during a burst the bed's level in a band 1 ERB wide at 1 kHz is 9 +- 1 dB
  down; in a band at 4 kHz it moves by less than 0.2 dB; between bursts (after 3 release
  times) the 1 kHz band is within 0.5 dB of the input.
- Look-ahead: the gain at the burst's first frame is already at least 6 dB down.
- `policy="winnable"`: with the key 30 dB under the noise nothing is ducked.
- Partition of unity: `W.sum(0)` is 1 within 1e-12 for bins between 60 Hz and 15 kHz.

### `scripts/sep_duck.py` -> `reports/separation/duck/`

On SR0's excerpt, target the lead vocal: depths 3 / 6 / 9 / 12 dB x both policies. A table of
`score` (flagged circular where it is), SNRenv, bed damage, the coherence, the loudness
change. Audio in `cache/separation/duck/<setting>/` (the stems and the mix).

**Listening** (about 15 minutes): `presence` on reference / 6 dB / 12 dB winnable; `ab lead`
and `ab prefer` on reference against 9 dB winnable.

**Done when** the README states, with the user's thresholds, how many dB of masked threshold
each depth buys and at which depth the user starts to prefer the reference. **Cost:** one
session plus one listening session.

---

## SR3. Onsets: protection and lead-ahead (oracle)

**The idea.** Onsets are the strongest grouping cue a mix can move [doc: common onset within
~40 ms fuses; a 30 ms offset was the largest effect measured]. Two tools:

- **Protection**: a short broadband dip in the bed at each target onset, so the target's attack
  is heard clean.
- **Lead-ahead**: the bed a few tens of ms behind the target, so their onsets stop coinciding.

### In `varimu/separation/oracle.py`

```python
def onset_starts(x, fs, *, back_ms=30.0, rel=0.1) -> np.ndarray:
    """Sample indices where each onset physically starts."""

def dip(bed, starts, fs, *, depth_db=6.0, pre_ms=5.0, hold_ms=30.0, release_ms=60.0,
        band_hz=None) -> np.ndarray:
    """bed with a gain dip at each start; band_hz=(lo, hi) dips only that band."""

def delay(x, fs, ms) -> np.ndarray:
    """x later by ms (fractional samples allowed), same length."""

def best_lag(target, bed, fs, *, max_ms=45.0, step_ms=1.0, window_s=0.03) -> dict:
    """Onset coincidence of the target with the bed delayed by 0 ... max_ms."""
```

**How.**

- `onset_starts`: `grouping.onsets(x, fs)` returns the time of the **steepest rise**, which is
  5-15 ms after the sound starts (its envelope filters and a 10 ms smoothing). For each onset
  time, take the broadband envelope (rms in 1 ms blocks), find its peak within 100 ms after
  the onset, and walk back up to `back_ms` to the first block under `rel` of that peak. That
  block is the start.
- `dip`: a gain curve of 1 everywhere, then per start a raised-cosine fall over `pre_ms`
  ending **at** the start, a floor of `-depth_db` for `hold_ms`, a raised-cosine rise over
  `release_ms`. Overlapping dips take the minimum. Multiply. With `band_hz`, split the bed into
  band and remainder (`remainder = bed - band`, with `band` from
  `scipy.signal.sosfiltfilt`: zero phase, so the two sum back exactly) and dip only the band.
- `delay`: `varimu.magic.null.frac_delay(x, d_samples)` [code: `varimu/magic/null.py`].
- `best_lag`: `grouping.onset_coincidence(target, delay(bed, ms), fs, window_s=window_s)` per
  lag; return the curve and its first minimum.

**Tricky bits.**

1. `onset_coincidence` counts `<= 30 ms` as shared. A bed on the target's grid delayed by
   exactly 30 ms still reads as coincident on some onsets. Scan to 45 ms and look at the curve,
   not one number.
2. **Only whole stems can be shifted.** Moving single notes inside a polyphonic audio stem
   needs note-level editing. A smooth time warp with `flutter.read_at` cannot do it: a delay
   that changes by 20 ms must change slowly or it bends the pitch (a slope of 0.5 % is 8.6
   cents; 20 ms at that slope takes 4 s). For **MIDI takes** (the synth, the Rhodes, the
   Clavinet) per-note shifts are trivial: move the events. Say this in the report as the
   reason the audio version is a constant lag.
3. **Bleed makes a shifted stem comb-filter** against its own leak in the other stems. Use
   SR2's bleed check before shifting anything.
4. A constant 20-40 ms lag is audible as feel ("laid back") and as a flam on percussive
   parts. That is a musical cost only the user can price: the `ab prefer` question.
5. `notes=` for the glimpse measure: delay the dry stem by the same lag (SR0 tricky bit 1).
6. The dip must end its fall at the start, not begin there: a dip that starts with the onset
   lets the first 5 ms through masked.

### Tests

- `onset_starts` on a click train through a one-pole low-pass: each start within 2 ms of the
  click.
- `dip` on white noise with one start: the level 10 ms after the start is `-depth_db` +- 0.3
  dB; 300 ms later it is back within 0.1 dB; 20 ms before the start it is untouched.
- `dip` with `band_hz`: outside the band the output equals the input within 1e-9.
- `best_lag` on two click trains on one grid: coincidence 1.0 at 0 ms and 0.0 at 40 ms.

### `scripts/sep_onsets.py` -> `reports/separation/onsets/`

On SR0's excerpt: dips of 3 / 6 / 9 dB (broadband, and above 1 kHz only); bed lags of 10 / 20
/ 30 / 40 ms; the best of each combined with SR2's 6 dB winnable duck. `score` for each.

**Listening** (about 15 minutes): `presence` on reference / 6 dB dip / 30 ms lag; `ab prefer`
on reference against each. Ask the user in words whether the dip is audible as pumping.

**Done when** the README says which of the two the user's ear credits, and the largest lag the
user accepts musically. **Cost:** one session plus one listening session.

---

## SR4. A modulation signature per track

**The idea.** Bands whose envelopes rise and fall together are bound into one object
(comodulation: up to ~10 dB) and a modulated source becomes more prominent whatever the others
do [doc: Hall et al. 1984; McAdams 1989]. Independent **flutter** failed because it is slight
FM, which is not a cue. **AM** common to all of one track's bands is. A singer's vibrato and a
Leslie are the natural cases.

**Hypothesis.** A slow common modulation on the target lowers its masked threshold; the same
modulation on the bed does not, or hurts.

**What to build** (`oracle.py`):

```python
def tremolo(x, fs, *, rate_hz=5.5, depth_db=2.0, phase=0.0) -> np.ndarray:
    """x with a gain that swings sinusoidally by +-depth_db / 2."""

def vibrato(x, fs, *, rate_hz=5.5, cents=25.0, phase=0.0) -> np.ndarray:
    """x read at t - d(t): a sinusoidal delay whose peak upward pitch deviation is `cents`."""
```

- `tremolo`: gain `10^((depth_db / 2) sin(2 pi rate t + phase) / 20)`.
- `vibrato`: the output is `x(t - d(t))`, so the pitch ratio is `1 - d'(t)`. For a peak
  deviation of `c` cents the delay is `d(t) = A sin(2 pi rate t + phase)` seconds with
  `A = (2^(c / 1200) - 1) / (2 pi rate)`; read with `flutter.read_at(x, n - d * fs)`, `n` the
  sample indices.

Conditions on SR0's excerpt and on the synth pair: tremolo 1 / 2 / 4 dB on the target only, on
the bed only, on both at different rates (5.5 and 4.3 Hz); vibrato 15 / 30 / 50 cents on the
target only.

**Physical tier** (render only what the oracle shows to matter): the Uni-Vibe on the target
(`univibe`, `mode`, `speed`, `intensity`); on the synth the panel's own VIBRATO.

**Tricky bits.**

1. Tremolo changes loudness: `bench.rematch` after it.
2. The measure to watch is `self_comodulation` of the target (it should rise) and the
   cross-coherence with the bed in the 4 and 8 Hz rate bands (it should fall).
3. Vibrato on a stem with reverb or bleed in it smears; on the synth pair it is clean. Use the
   synth pair (and its changed-note staircase) for vibrato.
4. 2 dB of tremolo is plainly audible as an effect. The question for the user is whether a
   depth small enough to pass as natural still helps.

**Tests:** a 1 kHz tone through `tremolo(depth_db=2)`: its envelope's peak-to-trough is 2.0 +-
0.05 dB at 5.5 Hz. Through `vibrato(cents=25)`: the instantaneous frequency (Hilbert) peaks
at 1000 x 2^(25 / 1200) +- 0.5 Hz.

**Listening:** the changed-note staircase on dry / target tremolo 2 dB / target vibrato 30
cents / bed tremolo 2 dB (four staircases: two sessions).

**Done when** the README gives the threshold shifts and the smallest depth that still helped.
**Cost:** half a session plus two listening sessions.

---

## SR5. Mid / side and binaural unmasking

**The idea.** A target whose interaural phase differs from the masker's is unmasked by up to
~15 dB at low frequencies on headphones (the N0S-pi condition: Hirsh 1948; Licklider 1948
[memory]); the equalization-cancellation model gives 10.7 dB at 500 Hz against a coherent
masker and 5.0 dB when the masker's interaural coherence is 0.5 [doc]. So: **keep the bed
coherent (in the mid) and give the target side content.** Mixing practice often does the
reverse (a wide bed, a mono lead). This package tests both.

**Conditions** (stereo, SR0's excerpt, the lead vocal as target, each stem rematched):

| Name | Bed | Target |
|---|---|---|
| `mono` | centre | centre (the reference: N0S0) |
| `pan` | centre | level-panned to +0.5 (ILD) |
| `ref_mix` | `REFERENCE_MIX` pans | centre (the usual mix) |
| `side_delay` | centre | `L = t + a D(t)`, `R = t - a D(t)`, `D` a delay of 8 ms, `a` = 0.5 |
| `side_lowflip` | centre | below 1.5 kHz inverted in the right channel (N0S-pi: the lab's upper bound) |
| `wide_bed` | each bed stem as `side_delay` with its own delay (7, 11, 13 ms) | centre |

- `side_delay` is Lauridsen's pseudo-stereo (1954 [memory]): the two channels are
  complementary comb filters, and **the mono sum is exactly `2 t`**, so it is mono-compatible.
- `side_lowflip`: `lo = sosfiltfilt(butter(4, 1500, fs=fs, output="sos"), t)`, `hi = t - lo`;
  `L = t`, `R = hi - lo`. Its mono sum loses the low band: it is an anchor, not a proposal.

**What to measure:** `binaural.better_ear_glimpse`, `binaural.band_measures` (remember `(2,
n)`), the mono sum's level of each stem re its stereo loudness (mono compatibility), and the
interaural coherence of the bed per octave (`scipy.signal.coherence`).

**Tricky bits.**

1. Headphones only for the listening: loudspeakers leak each channel into both ears and shrink
   the effect. Ask the user which they will use (Open decisions 3) and write it in the
   judgments file.
2. Loudness of a stereo stem: pyloudnorm sums the channels' powers. Rematch each stem after
   its stereo treatment.
3. The comb of `side_delay` colours each ear. With `a = 1` the nulls are total; start at 0.5.
4. The model's BMLD is derived for a stationary masker. Treat its numbers as a hint until SR1
   says how far it is trusted (R5's stereo staircase was never run either).

**Physical tier.** The mid / side matrix in iron and the shuffler are STEREO_PLAN.md's ST7 (not
built). The stereo 670's LATERAL & VERTICAL mode exists (`fairchild_670_stereo`, `mode` 2):
compressing mid and side apart. If `side_delay` wins by ear, that is the argument to build ST7.

**Tests:** `side_delay`'s mono sum equals `2 t` within 1e-12; `side_lowflip` on a 300 Hz tone:
interaural correlation -1; on a 4 kHz tone: +1; `pan` at 0.5: the ILD is `20 log10(tan(3 pi /
8))` = 7.66 dB.

**Listening** (two sessions): `presence` on `mono` / `pan` / `side_delay` / `side_lowflip`;
`ab apart` and `ab prefer` on `ref_mix` against `side_delay` and against `wide_bed`.

**Done when** the README ranks the conditions by threshold beside the model's ranking, and
says whether a coherent bed with a side-content lead beats the usual wide bed for this user.
**Cost:** one session plus two listening sessions.

---

## SR6. Depth as its own axis

**The idea.** "Sounds that don't touch" may be sounds at different distances. Distance is heard
from level, the direct-to-reverberant ratio (DRR), high-frequency loss and, close up, the
proximity bass rise [doc: Zahorik et al. 2005]; these work in mono. The earlier studies only
counted what a room costs energetically (every room cost glimpses). Whether staging by depth
helps the ear is untested.

**Conditions** (mono first; room `home`, positions as `separation_study.NEAR` / `FAR`):

| Name | Lead | Bed |
|---|---|---|
| `flat` | dry | dry |
| `habit` | near (0.3 m) | far (2.45 m) |
| `inverse` | far | near |
| `early_only` | near | far, the response cut to its first 80 ms (`ism_s`; no tail) |
| `staggered` | 0.3 m | harmonies 1.0 m, guitar 1.7 m, bass dry |
| `predelay` | dry + a reverb return delayed 25 ms | dry |

Each stem convolved with `room.impulse_response(ROOMS["home"], source, mic, fs)`
(`scipy.signal.fftconvolve`), then rematched. For `early_only`, zero the response after the
direct arrival + 80 ms with a 5 ms fade. For `staggered`, place the sources on a line from the
mic. For `predelay`, the return is the stem through the `hall` response with its direct sound
removed, delayed, at -12 LU re the stem.

**What to measure:** `score`; per stem the DRR of its response (direct = the energy from 1 ms
before to 2.5 ms after the first arrival's peak; DRR = direct over the rest, in dB); the 8-16
kHz level change.

**Tricky bits.**

1. Per-stem rematching removes the level cue to distance on purpose (rule 8). Say so: the test
   is of DRR and spectrum, not of "the far thing is quieter".
2. `impulse_response` is per unit source at 1 m scaling; only the shape matters after
   rematching.
3. The predicted outcome is a conflict: `inverse` should score best on the lead's measures
   (SCENE_ANALYSIS.md proposal 5) and `habit` is what engineers do. The `ab` test is the
   point of the package. Do not pre-judge it in the README.
4. Stereo depth (the Room view, a coincident pair) is a second pass only if the mono pass
   shows an effect: `scripts/room_print.py` and scenes cost far more.

**Tests:** the DRR of a response that is a unit impulse plus white noise at -20 dB total is +20
dB within 0.5; `early_only`'s response is zero after 90 ms.

**Listening:** `ab apart`, `ab lead`, `ab prefer` on `flat` / `habit` / `inverse` /
`staggered` (six pairs against `flat` and each other: two sessions); `presence` on `habit`
against `inverse`.

**Done when** the README says whether depth staging reads as "more apart" to the user and at
what cost to the lead's threshold. **Cost:** one session plus two listening sessions.

---

## SR7. The chain atlas (identity)

**The idea.** To make one sound warm and another cold we need to know what each of our devices
does to a sound, in the dimensions the ear uses for timbre. Timbre research finds roughly
three: spectral centroid, attack time, and spectral flux or fine structure (Grey 1977; McAdams
et al. 1995 [memory]). The atlas measures every device setting's displacement of a stem along
such descriptors.

### `varimu/separation/atlas.py`

```python
def descriptors(x, fs) -> dict[str, float]:
    """The absolute timbre descriptors of one stem."""

def displacement(dry, wet, fs) -> dict[str, float]:
    """descriptors(wet) - descriptors(dry), after aligning wet to dry and rematching."""
```

| Descriptor | Definition | Known-answer test |
|---|---|---|
| `centroid_cam` | Power-weighted mean ERB-number of the long-term spectrum, 50 Hz-16 kHz (Welch, 4096 at 48 kHz) | A 1 kHz tone: `erbn(1000)` = 15.6 +- 0.1 |
| `tilt_db_oct` | Slope of a line through the third-octave levels, 100 Hz-10 kHz | Pink noise: -3.0 +- 0.2; white: 0 +- 0.2 |
| `low_mid_db` | 150-500 Hz level re the total (50 Hz-16 kHz) | White noise: 10 log10(350 / 15950) = -16.6 +- 0.5 |
| `presence_db` | 2-5 kHz re the total | as above |
| `air_db` | 8-16 kHz re the total | as above |
| `attack_ms` | Median over onsets (`oracle.onset_starts`) of the time the 1 ms rms envelope takes from 10 % to 90 % of its local peak | Tone bursts with 20 ms linear ramps: 16 +- 2 ms |
| `crest_db` | Peak over rms in 3 s windows, the median | A sine: 3.0; white noise: 11-13 |
| `flux` | Mean over active frames of the mean absolute change, frame to frame, of the 48 band levels in dB (`cell_energies`) | A steady tone: under 0.1; the same tone with a 4 Hz tremolo of 6 dB: clearly larger |
| `distortion_db` | The residual of wet against `g H dry`, H measured on a multisine at the stem's level (the method of `scripts/chain_passes.py`) | A pure filter: under -60 dB (the floor); a tanh at 1 % THD: -40 +- 3 |
| `even_odd_db` | On a 220 Hz sine at the stem's rms level: 2nd harmonic over 3rd (`varimu.measure.metrics.harmonics`) | An `x + 0.01 x^2` law: large positive; `x + 0.01 x^3`: large negative |

**The moves.** A move is a device with settings and a drive (the trim). Start with line-level
devices through `print.exe` at `draft-1x`: the EQP-1A (LF boost at 60 and 100; LF atten; HF
boost at 3 / 5 / 10 / 16 kHz, narrow and broad; HF atten), the MEQ-5 (each peak, the dip at
three frequencies), the 550A (each band at +-6), the HLF-3C (low cut 80 / 150, high cut 5 / 8 /
12 kHz), the 670 (two thresholds x TC 1 and 4), the 1176 (4:1 and all-buttons), the 351 insert
at trims 0 / +6 / +12, the 5E3 at two volumes. About 40 moves x 4 stems x a 20 s excerpt.
**Estimate the time from one render per device before the batch**; `print.exe` caches, so a
rerun is free.

Second pass (re-amping through microphones): `scripts/mic_print.py --circuit CHAIN --clip
FILE --spl-db L --distance-m D` prints a clip as a point source through a mic chain in free
field: the chain list is `config/chains.yaml` (51 chains). Level and distance are the big
levers there (+10 dB of distortion at 115 dB SPL; proximity). SEPARATION_PLAN.md's caveat
holds: a recorded stem already carries its own microphone.

**Output:** `reports/separation/atlas/atlas.json` (move x stem -> displacement), a scatter per
stem (centroid against tilt, attack against crest, coloured by device), and the audio in
`cache/separation/atlas/<move>/<stem>.wav`, each rematched to its dry stem.

**Words.** Operational first guesses [memory: Zacharakis, Pastiadis and Reiss 2014 on timbre
semantics; treat every mapping as a hypothesis]: bright / dark = `centroid_cam`; warm / cold =
more `low_mid_db`, a more negative tilt, a positive `even_odd_db`, a longer attack; hard /
soft = `attack_ms` and `crest_db`; near / far = SR6's DRR, `air_db`, `low_mid_db`. Then
**calibrate on the user**: `sep_listen.py rate` on 16 atlas clips (4 stems x 4 moves spread
over the scatter) gives the user's own warm-cold and dark-bright numbers; regress them on the
descriptors (least squares, report the fit and its residual; 16 points support two or three
predictors, no more). The fitted axes replace the guesses.

**Tricky bits.**

1. Align before comparing: tape and some devices delay (`null.align`).
2. `draft-1x` is within ~-45 dB of production and up to 0.7 dB off in the top octave
   (CLAUDE.md): `air_db` and `distortion_db` near that floor are not trustworthy at the draft.
   Re-render the three most extreme moves at production and report the differences.
3. Displacements are per stem: a nonlinear device moves a bass and a vocal differently. Never
   average over stems.
4. The trim: an insert expects about -18 dBFS rms; a stem far from that is driven softer or
   harder than intended. Record each stem's level into the device with every move.
5. `distortion_db`'s floor: run it on the HLF-3C (linear) first and print the floor in the
   README.

**Tests:** the table's third column, in `tests/test_sep_atlas.py`.

**Done when** the atlas, the scatters and the calibrated word axes exist, and the README names
the three moves that go furthest toward each end of each axis for each stem. **Cost:** two
sessions plus one rating session (16 clips: about 10 minutes).

---

## SR8. Assignment: who gets which colour

**The idea.** Brightness separated "in one direction": the brightened track gains what the
other loses. So tone is a budget, and the mix decision is an assignment. With per-track
processing the mix of any assignment is the **sum of stems already rendered**, so every
combination can be scored without a new render.

### `varimu/separation/assign.py`

```python
def search(atlas_audio: Mapping[str, Mapping[str, np.ndarray]], dry, fs, bal, *,
           roles: Mapping[str, Mapping[str, float]], weights, limits) -> list[Assignment]:
    """The best assignments of one move per stem (the dry stem is always a candidate)."""
```

**Objective** for an assignment `a` (a move per stem):

`J = w_d * min over pairs d(i, j) + w_r * sum over stems role(i) + w_g * min over stems
glimpse(i) - penalties`

- `d(i, j)`: the Euclidean distance between the two processed stems' **absolute** descriptors
  (`centroid_cam`, `tilt_db_oct`, `attack_ms` as log10, `flux`, `crest_db`), each z-scored over
  the whole atlas. Dissimilar stems are the lever on informational masking.
- `role(i)`: the user's intent for the stem (e.g. `{"lead vocal": {"warm": 1, "near": 1},
  "guitar": {"bright": 1}}`) dotted with the stem's position on SR7's word axes.
- `glimpse(i)`: stem `i` against the rest.
- Penalties: `distortion_db` over a limit; a stem's third-octave spectrum more than 6 dB from
  its dry one (the instrument must stay itself).

**How to make it fast.** Precompute each candidate stem's complex STFT once. A mix's cell
energies are then band sums of `|sum of STFTs|^2`; or, cheaper and nearly the same, the sum of
the stems' cell energies (cross terms dropped): use the cheap form for the search and the
exact form for the top 20. With 4 stems and ~40 moves the full grid is 40^4 = 2.6 million
combinations: prune first (keep per stem the 12 moves that are most distinct in descriptor
space: farthest-point sampling), giving 12^4 = 20,736, which brute force handles.

**Report:** not one winner. The five best assignments that differ in at least two stems; the
Pareto front of (the lead's glimpses, the minimum glimpses over all stems); and the weights
used. Render the top three as mixes.

**Tricky bits.**

1. The weights are not known. Run three settings (distance only, glimpses only, equal) and
   show how the winner changes. Do not tune weights to a preferred answer.
2. The rematched atlas audio is what gets summed (rule 8), at `REFERENCE_MIX`'s balance.
3. Time-aligned stems only: a delaying move (tape) must be aligned before summing.

**Tests:** on a toy atlas of two stems and three moves where one move is a +6 dB shelf above 2
kHz: the search gives the shelf to exactly one stem, never both.

**Listening:** `ab apart` and `ab prefer` on the reference mix against each of the top three.

**Done when** the user has heard the top three against the reference. **Cost:** one session
plus one listening session. Needs SR7.

---

## SR9. Physical cousins

How much of each oracle result does a real device recover? Build only the parts whose oracle
won by ear.

**a. Keyed ducking** (SR2's and SR3's cousin; SCENE_ANALYSIS.md proposal 7, never measured).
The bed through a compressor keyed by the lead: `fairchild_670_keyed` (`key_mode` 1,
`key_depth` 0.2 / 0.45 / 0.7, `time_constant` 1 and 2) and `ssl_bus_comp` (`key_mode` 1,
`ratio` 4, the fastest and a slow `attack`, `release` 0 and 2), with `render.through(...,
controls={"key": ...})` as under "What exists".
- The keyed 670 has no ratio but a cliff: a 4 dB change of key takes it from no ducking to
  cut-off, and `key_depth` sets the floor (about -3 to -10 dB) (CLAUDE.md, SIDECHAIN_PLAN.md
  "DEPTH"). Sweep the key's gain (-12 ... +6 dB in 3 dB steps) on a 5 s piece to find where it
  starts to duck before any long render.
- A broadband ducker moves the whole bed; the oracle moves cells. Report SR2's table for it
  (score, damage, coherence) beside the oracle at the same loudness change. **If the multiband
  oracle is far ahead, that is the case for SIDECHAIN_PLAN.md's parked K5 (split-band).**
- Production renders of 20 s through the 670 take 4-12 minutes each (11-36x real time,
  CLAUDE.md): estimate the batch.

**b. Tape pre-delay into the plate** (SR6's `predelay` in period hardware): the lead through
`ampex_351_echo` (`repeat` 0, `send` 1, wet only) into `plate_reverb`, against the plate
alone, as a send at the same return loudness. The delay is the head distance over the tape
speed: 50.8 mm at 15 ips = 133 ms, 267 ms at 7.5 ips, +-33 % by `capstan_hz`. `print.exe
--device ampex_351_echo --set repeat=0 --device plate_reverb --set decay_500hz_s=2.2`. Measure
the lead's onset coincidence with its own return and `score`; listen with `ab lead`.

**c. A just third on a saturating bus** (SCENE_ANALYSIS.md's untested prediction): in
`scripts/grouping_study.py` `interval_experiment`, add a row for the just major third (ratio
5:4 exactly, 386.3 cents) beside the equal-tempered one. Prediction: its intermodulation lands
on the root's series like the fifth's (about -20 dB after the comb at the root), where the
tempered third's does not (-0.4 dB). Run `--only intervals`.

**d. Period devices built as psychoacoustic processors** [memory: all of these need sources
before anything is claimed]: the Aphex Aural Exciter (1975: harmonics added to the top band),
Kepex expanders (tightening decays so gaps open), the Orban stereo synthesizer (complementary
combs: SR5's `side_delay` in hardware), ADT (MODULATION_PLAN.md MD3). None is built. For each
one whose *function* an oracle package already showed to matter, write a short entry in
DEVICE_CANDIDATES.md with what the oracle measured; building one follows the device builder's
rules (a schematic first; the user fetches walled sources). **Do not write a "generic exciter"
and present it as a device.**

**Done when** each built part has its row beside its oracle and the README states the recovered
share. **Cost:** a to c one session each; d is notes only.

---

## SR10. An optimizer over real knobs

**The idea.** Automatic-mixing research minimizes masking by searching EQ settings (Hafezi and
Reiss 2015; Ronan et al. 2018 [memory]). Ours searches the knobs of real devices: the physical
tier's version of SR8, continuous.

**How to keep it cheap: a linear proxy, then one real render.**

1. For every EQ setting on a grid, get the device's small-signal response `H(f)`:
   - the HLF-3C is linear: `varimu.measure.ac.transfer(ir, f_hz, "out")` per position
     (`varimu/measure/filter_suite.py` already does this);
   - the EQP-1A, MEQ-5 and 550A have tube or discrete amplifiers, so `ac.transfer` raises
     `Unsupported`: measure `H` with a multisine through `render.through` at -18 dBFS (the
     `chain_passes.py` method), once per setting, at `draft-1x`. The EQP-1A's distortion on
     program was -23.7 dB re the mix in the bus study, so the proxy is good to about that.
   Cache the responses (`cache/separation/eq_responses/<device>.npz`).
2. A candidate's stem is the dry stem filtered by `H` (in the frequency domain, zero-padded).
   Thousands of candidates a second.
3. Search per stem over (device, discrete switch positions, pot rotations on a grid of 5),
   maximizing SR8's `J`, with coordinate descent from the reference mix (one stem at a time,
   three sweeps), or `cma` from the `optimize` extra for the pots.
4. **Confirm the winner with real renders** (`print.exe`, production) and report the proxy's
   error on `J` and on each stem's spectrum. A winner that only wins in the proxy is not a
   result.

**Constraints:** rule 8's loudness; each stem within 6 dB of its dry third-octave spectrum
unless its role says otherwise; at most two inserts a stem.

**Done when** the confirmed winner's mix has been heard against the reference and against
SR8's best. **Cost:** two sessions. Needs SR7 and SR8.

---

## SR11. Recoverability as a second opinion (optional)

**The idea.** We own the stems, so we can ask a neural source separator to pull each one back
out of a processed mix and score how well it did. A separator uses harmonicity, onsets and
timbre at once, so it may see grouping the four hand-built measures miss.

**How** [memory: check every API name against the installed package]: `uv run --extra ml
--with demucs ...`; `demucs.pretrained.get_model("htdemucs")`; `demucs.apply.apply_model(model,
mix[None], device="cuda")` returns `(1, sources, 2, samples)` with `model.sources` =
drums / bass / other / vocals at 44.1 kHz stereo. Our stems map to: vocals = lead vocal +
harmonies, bass = bass, other = guitar. Score each by the scale-invariant SDR against the
processed true stem group: `s_t = (<e, s> / <s, s>) s`, `SI-SDR = 10 log10(|s_t|^2 / |e -
s_t|^2)`.

**Limits, stated up front.** It cannot split lead from harmonies (one class). It exploits cues
people do not have, and its training data did not contain SR2's ducked beds, so an oracle
processor can fool it either way. It downloads model weights: **ask the user before the first
run** (Open decisions 4). Use it only after checking it against SR1's thresholds on the synth
pair (does its score rank the conditions as the ear did?); if it does not, write that down and
stop.

**Cost:** one session.

---

## SR12. Predictability (speculative)

**The idea.** A sound that follows a predictable pattern fades into the background; change
holds attention [doc: Winkler, Denham and Nelken 2009: an auditory object is a predictive
regularity]. A steady bed under a lead that keeps changing might read as more separate than
the same levels with the roles reversed.

**One experiment, by ear only.** Flatten a part's short-term loudness (a slow gain ride toward
its median 3 s loudness, at most +-3 dB, as `lightfoot_mix.py`'s vocal ride does in reverse):
(a) the bed flattened, the lead as played; (b) the lead flattened, the bed as played; (c)
neither. `ab apart` and `ab prefer` on (a) against (b) and each against (c).

No measure in the bench predicts this. If the user hears nothing, it is closed. **Cost:** half
a session plus one listening session.

---

## SR13. Partial-collision notching (deferred, with the reason)

The brainstorm listed "notch the bed only at the lead's harmonics". Writing it out exposed the
flaw: **masking is set by the masker's power inside the auditory filter around each partial**
(about one ERB wide). A notch much narrower than an ERB removes only a small share of that
power, so it barely unmasks; a notch an ERB wide is SR2. What a narrow notch can change is
beating between two partials a few Hz apart, which is roughness, not masking.

Build it only if SR2 by ear shows that bed damage, not the size of the gain, is the limit. Then:
track the lead's F0 (`grouping.f0_track`), and in SR2's step 5 restrict ducking to bins within
a quarter ERB of `k f0(t)` for the resolved harmonics (k up to ~8), with `n_fft` 4096. Compare
damage and threshold at equal glimpse gain.

---

## Order and dependencies

```
SR0 bench ──> SR1 hear the old predictions ──┬─> SR2 ducking ──> SR3 onsets ──> SR9a keyed duckers
                                             ├─> SR5 mid / side
                                             ├─> SR6 depth ──> SR9b tape pre-delay
                                             ├─> SR4 modulation
                                             └─> SR7 atlas ──> SR8 assignment ──> SR10 knob optimizer
SR9c (the just third): any time, one run.   SR11, SR12: optional.   SR13: only if SR2 asks for it.
```

Suggested: SR0, SR1, SR2, SR3, then the user chooses a branch: **maximum separation** (SR5,
SR6, SR4, SR9) or **colour** (SR7, SR8, SR10). SR1 comes before any oracle because it decides
which numbers the later READMEs may lean on.

Expect roughly a dozen short listening sessions over the whole document. Each package's
"Listening" says how many.

## Open decisions (the user's)

1. **May an oracle processor become a feature of the app** (a non-physical insert), or do they
   stay research tools whose job is to say which physical devices to build?
2. **Material.** Is the *Did She Mention My Name* cover the primary multitrack? A second song
   with drums would test onsets far better (this one has none).
3. **Headphones or loudspeakers** for the stereo tests (SR5 assumes headphones).
4. **A download** of a pretrained separator's weights (SR11).
5. **Which pairs matter most**: the lead against everything (assumed here), or also the
   harmonies under the lead (the most similar pair, so the hardest informational case)?
6. **Roles** for SR8: which stem should be warm, bright, near, far?

## Sources

From SCENE_ANALYSIS.md (read there in the paper or its abstract; see its tags): Bregman 1990;
Darwin 1984; Rasch 1979; Elhilali et al. 2009; Hall, Haggard and Fernandes 1984; Carlyon 1991,
1994; McAdams 1989; de Cheveigne 2021; Cooke 2006; Joergensen, Ewert and Dau 2013; Zahorik et
al. 2005; Winkler, Denham and Nelken 2009; Kolotzek et al. 2021 (the EC model's BMLD);
Brungart and Iyer 2012.

[memory], to check before quoting: Warren 1970 and Warren, Obusek and Ackroff 1972 (the
continuity illusion: a gap is filled in only when the interrupting sound could have masked the
missing part); Hirsh 1948 and Licklider 1948 (binaural masking level differences); Lauridsen
1954 (pseudo-stereo by complementary combs); Grey 1977 and McAdams et al. 1995 (timbre
spaces); Zacharakis, Pastiadis and Reiss 2014 (timbre semantics: luminance, texture, mass);
Hafezi and Reiss 2015 and Ronan et al. 2018 (automatic masking reduction in multitrack
mixes); the Demucs API.
