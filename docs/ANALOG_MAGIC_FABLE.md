# Analog magic: the Fable brainstorm as work packages

2026-11-12, at the user's request: a brainstorm by Claude Fable 5 on what made 1960s recordings
sound the way they do, written out so that a later session on any model can build each idea
without having been in the conversation. Fourteen work packages, AM1-AM14, on a small shared
toolkit, AM0.

**Nothing here is built and nothing was run.** No model, circuit, engine or app code changed.
What was read for this document: EMERGENCE_RESEARCH.md, SCENE_ANALYSIS.md (sections 2, 3, 5, 6),
the headings of FUTURE_DIRECTIONS.md, COMPONENT_DEPTH_PLAN.md, METHODOLOGY_REVIEW.md and
INVENTED_DEVICES.md, circuitsim's `dk.rs` (module docs, `DkSystem`, `DkNewton`) and
`transient.rs` (`try_step_dk`), and three read-only surveys of the Python analysis and render
code, the rooms / drums / plate / capsule code and varimu-app's takes and mixer. Nine web
searches (standard mode) checked the citations; "Sources" at the end says what each found.

Tags on claims:
- **[code]**: read in the code on 2026-11-12; the path and line are given. Line numbers drift:
  when one is off, search for the name.
- **[search]**: found in a web search on 2026-11-12, at the level of an abstract or a summary.
- **[memory]**: from the model's memory, not checked. Check before relying on it.
- **[estimate]**: a figure derived here, not measured.

Every package is a hypothesis until it is measured. "Inaudible at realistic values" is a full
result (the user's rule: subtle differences count as verified).

## The thesis

The project's own results say the magic is not inside any one device. Units with realistic
values were too close to choose between by preference (Phase 5). The second T85, the output
transformer's capacitances and the U47 into the V76 were all "subtle". Per-pass flutter
separated nothing, and a 30 ms timing offset moved the grouping measures more than any chain
(SCENE_ANALYSIS.md). So this document bets on four things the project has not modelled or
measured:

1. **Accumulation.** A 1960s signal crossed 30-60 stages and three to five tape generations.
   Small effects compound, and the order of linear and nonlinear stages matters.
2. **Noise that moves with the signal.** Modulation noise shares the signal's envelope, so the
   ear's grouping rules should fuse it into the source's timbre instead of hearing hiss.
3. **Nothing repeats.** No two passes, notes or reverb tails are identical in hardware or in a
   room. Several of our models are frozen: the same input gives the same output forever.
4. **Two-way coupling.** Instruments excite each other through the air and the floor, and the
   gear changes how the player plays.

It does not repeat the earlier brainstorms. Where a package extends one, it says so.

## Rules for whoever builds this

These are the project's rules (CLAUDE.md) as they apply here. Follow them without being asked.

1. **One package at a time**, in the order of "Order and dependencies" unless the user picks
   another. A package is done when its "Done when" is met and its tests pass.
2. **Do not change a model, a circuit file or a device file.** Every package here measures or
   adds an opt-in path. If a result suggests a model change, write the options with numbers and
   stop: that decision is the user's.
3. **Where code goes.** New Python lives in `varimu/magic/` (new package), scripts in
   `scripts/`, tests in `tests/test_magic_*.py`, results in `reports/magic/<package>/`,
   intermediate audio in `cache/magic/<package>/`, the user's judgments in
   `data/judgments/magic/` (git-ignored already: `.gitignore` line 27 `data/judgments/*`).
   `varimu/magic/` is outside the render cache key, which covers only
   `varimu/{sim,circuit,devices}` and `config.py`.
4. **Do not edit `varimu/sim`, `varimu/circuit` or `varimu/devices`** unless a package says to.
   Any edit there changes every render's cache key and the next full test run re-renders for
   hours. Two packages touch code outside `varimu/magic/` (AM9: `varimu/drums/drum.py`; AM13
   step 2: `crates/circuitsim`); both say how to keep existing results bit for bit.
5. **Do not add to the web app** (`varimu listen`): it is being retired. Listening tests are
   terminal scripts on the pattern of `scripts/separation_listen.py` (AM0 describes it).
6. **Every value has a source.** A constant in new code carries a comment with a citation,
   `web: <url>` or `provisional: model knowledge (...)`. Never present an invented number as
   data.
7. **Reproducible.** All randomness through `np.random.default_rng([seed, zlib.crc32(name)])`.
8. **Loudness lies.** Every listening comparison is matched in LUFS (and in gain reduction
   where a compressor is involved). The functions are in AM0.
9. **Tests.** Per package run only its own tests (`uv run --extra fast pytest
   tests/test_magic_<x>.py`). The full suite is batched at the end; say that it is owed.
10. **Estimate a run's time before starting it**, from the rates in each package's "Cost", and
    tell the user when it exceeds a few minutes. Long runs log progress with an ETA.
11. **Commands.** Renders need `uv run --extra fast ...`; loudness needs `--extra listen`
    (pyloudnorm); playback needs `--with sounddevice` (it is in no extra) [code:
    pyproject.toml]. Plain `uv run` does not rebuild circuitsim after a Rust edit.
12. **Windows.** Paths with spaces (`stems/Did she mention my name/full/`) need quoting; use
    `pathlib`. Do not write patch scripts as shell heredocs; use the Write tool.
13. **Audio conventions.** Mono float32 WAV unless stereo is the point; levels in peak dBFS;
    the sample rate from `TransientSettings.sample_rate` (96 kHz), never hardcoded outside
    tests.

## What exists (the facts every package leans on)

All [code], read 2026-11-12.

**Rendering a clip through a circuit** (the pattern of `scripts/reverb_listen.py:53-66`):

```python
from varimu.circuit import builder, spec
from varimu.sim import fast
from varimu.sim.io import TransientSettings, full_scale, load_audio, write_audio

st = TransientSettings.from_sim_settings(engine="circuitsim", quality="production")
fs = st.sample_rate                                    # 96000
x = load_audio(path, fs)                               # mono float64 at fs
c = spec.load_circuit(spec.circuit_path("fender_5e3")) # config/circuits/<name>.yaml
v_in, v_out = full_scale(st, c)                        # volts peak at 0 dBFS, in and out
circuit = builder.build(c, {"volume_bright": 0.6})     # overrides: a plain dict
r = fast.run_transient(circuit.ir, x * v_in, settings=st)
y = r.vectors["v(out)"] / v_out                        # back to dBFS scale
write_audio(out_path, y, fs)                           # mono float32 WAV
```

- `builder.build(spec, overrides=None, *, triode_formulation=None, cores=None, noise=None,
  heaters=None, events=False, literal=False)` (`varimu/circuit/builder.py:1844`).
  - `noise`: None = the file's `noise:` block; False = off; True = on (the block's seed or 0);
    an int = on with that seed. One seed drives the resistor and tube noise, the mains wander
    and, in a tape circuit, the grain and the transport's random parts together
    (`crates/circuitsim/src/media.rs:134-145`).
  - `heaters`: None = the file's block; False; True; "warm"; "cold".
  - `cores`: "ja" or "linear".
- `fast.run_transient(ir, input_v, *, settings=None, method=None, progress=None,
  controls=None, stats=None, notes=None, origin_s=0.0)` (`varimu/sim/fast.py:239`). It has no
  noise argument: noise is fixed in the IR at build time. `origin_s` continues the mains'
  phase, the noise streams and a tape's transport and grain from that time of a longer run.
- `TransientSettings` is a frozen dataclass (`varimu/sim/io.py:97`); change a field with
  `dataclasses.replace(st, error_abstol=0.0, ...)`. Qualities for Python: "production",
  "draft", "draft-1x" (`QUALITY_BLOCKS`, io.py:69). Renders settle for 1 s first
  (`settle_s`), trimmed from the output.
- The cached, parallel runner: `runner.RenderJob(samples, overrides, label, circuit,
  controls)` and `runner.render_many(jobs, settings=, max_jobs=)` (`varimu/sim/runner.py:106,
  322`). **It cannot pass `noise=` or `heaters=`** (`build_circuit`, runner.py:123), so
  packages that switch mechanisms call `builder.build` and `fast.run_transient` directly
  (AM0's `through`), on threads (circuitsim releases the GIL).
- Circuits with a `noise:` block: `ampex_300_4`, `ampex_300_4_channel`, `ampex_351` and its
  echo / insert files, `capsule_bk4134`, `nickel_organ`, `tube_synth`. With `heaters:`:
  `fender_5e3_mods`, `tube_synth`. Any other circuit takes `noise=1` or `heaters=True` on the
  build and uses the defaults (`varimu/devices/noise.py`: flicker and mains wander are
  provisional).

**The idealized tape machine** (no circuit; grain and transport seeded apart):
`tape_machine.print_audio(x, fs, spec, tape, al, drive_db=0.0, progress=None,
engine="circuitsim", noise_seed=None, transport_seed=0)` (`varimu/devices/tape_machine.py:
1075`). `noise_seed=None` is no grain; `dataclasses.replace(spec, flutter=False)` is no
transport. `scripts/tape_print.py` shows how `spec`, `tape` and `al` are made. About 24x slower
than real time.

**The 351 as a circuit**: `scripts/print_351.py` (`builder.build(c, al.overrides, cores="ja",
noise=False if a.no_noise else None)`, line 67; the alignment `al` is loaded just above).
About 27x slower than real time with the GPU kernel (CLAUDE.md, TAPE_SPEED_PLAN.md).

**Loudness.** `varimu.listen.matching.integrated_lufs(x, sample_rate)` and
`match_loudness([a, b], sample_rate, target=-23.0)` -> `([a', b'], Matched)` (one shared
target, with a peak guard); `varimu.separation.metrics.match_loudness(x, fs, target_lufs)` for
one array. Both need pyloudnorm (`--extra listen`).

**Differences.** `varimu.listen.difference.decompose(a, b)` -> `Decomposition(g, h, tone,
character)`: after a least-squares gain, `tone` is what one fixed filter explains of B - A and
`character` is the rest. `difference.levels(a, b)` gives the three levels in dB re A.
`difference.align_gain(a, b)` is the least-squares gain.

**Grouping measures** (`varimu/separation/grouping.py`; mono arrays and `fs`; each resamples to
24 kHz inside): `envelopes(x, fs)` -> `Envelopes(centres_hz, env)` (32 ERB bands, envelopes at
1 kHz); `temporal_coherence(t, m, fs)` -> `{"rates", "cross", "within"}`; `onsets(x, fs)` ->
times; `onset_coincidence`; `harmonic_cancellation`; `envelope_snr(t, m, fs)` ->
`{"snr_env_db", "per_mod"}`; `shares(bus, target, masker)`. Tests with known answers:
`tests/test_grouping.py`.

**Tones.** `varimu.measure.metrics.harmonics(y, freq_hz, sample_rate)` (a least-squares fit, a
whole number of periods; `.thd`); `varimu.measure.tape_align.thd(y, fs, f_hz)` (robust to
flutter); `varimu.measure.tape_suite.band_rms(y, fs, band_hz)`; flutter from a 3150 Hz tone:
`scripts/tape_flutter.py:59-70` (band-pass 2-4.5 kHz, Hilbert, instantaneous frequency).
There is no crest-factor function in the library.

**The listening-test template** is `scripts/separation_listen.py`: `player(fs, device)`
returns a `play(x)` closure on sounddevice (lines 87-107); `staircase(...)` is a 2-down 1-up
three-interval odd-one-out with steps 6 / 4 / 2 dB, 8 reversals, the threshold the mean of the
last 6 (lines 110-178); answers by `input()` (1 / 2 / 3, r replay, q quit); results rewritten
after every condition to `data/judgments/separation/<stamp>.json`. Copy its structure.

**Rooms.** `shoebox.responses(room, sources_m, mics, fs, *, ism_s=0.08, length_s=None,
seeds=None, tail=True, backend=None, wave=None, directivity=None, tail_offsets=None,
log=None)` (`varimu/rooms/shoebox.py:237`) returns `(sources, mics, 2 entries, samples)`:
impulse responses of the front and rear entries per unit source (1 / r in free field). It
serves `Shoebox` and `PolyRoom`. A mic is `shoebox.Mic(position_m, aim, table)` with
`aim_vector(azimuth_deg, elevation_deg)` and a table from `entries.entry_table(geometry,
fs)`; an empty geometry `{}` is a pressure point (rear = front) (`varimu/rooms/entries.py:
12-20`). **Nothing in a room is time-varying**, and the speed of sound is the constant
`SPEED_OF_SOUND_M_S = 343.2` (`varimu/separation/room.py:24`); `temp_c` only feeds air
absorption. Scenes: `scene.load_scene(path_or_dict)`, `scene.source_signals(scene, fs)`
(pascals at 1 m), `scene.mic_pressures(...)`, `scene.print_chain(chain, overrides, front,
rear, quality)`, `scene.render(scene, out_dir, solo=False)`. `scene._cached_responses` keeps
only the newest 12 response files.

**Drums.** `drum.load(name)`, `drum.prepare(d2)` -> `Prepared2` (its `mic` vector is the
far-field pressure per modal acceleration at `mic_distance_m`, `body.mic_angle_deg`),
`drum.run(prep, *, fs, seconds, velocity_m_s, tension_modulation=True)` -> `Hit2(fs,
pressure_pa, force_n, tension_n_m, f_fund_hz)` (`varimu/drums/drum.py:343, 436`). **There is
no input for incident sound.** 9-14x slower than real time. Snare wires are not built.

**The plate as a general plate.** `plate.PlateSpec(lx_m, ly_m, thickness_m, density_kg_m3,
youngs_pa, poisson, tension_n_m, drive_xy, pickup_xy, f_max_hz, decay, tail_db)` and
`plate.impulse_response(p, fs)` (force in newtons to acceleration in m/s^2;
`varimu/devices/plate.py:147, 230`). Any dimensions and material; tension may be 0;
`drive_xy` / `pickup_xy` are fractions of the sides; simply supported, isotropic; `decay` is
`((f_hz, energy_decay_per_s), ...)`.

**Mics have no vibration input.** Capsule, moving-coil and ribbon networks are driven by the
front and rear pressures only.

**The app.** A session take keeps the device's output only; **the dry input is not saved with
a take** (`crates/varimu-app/src/player.rs:1849`, `session.rs:3626`). The dry input is saved
only by the Play view's Record button or `examples/play.rs --record FILE` (one channel, the
input device's rate). An event take's keys are in `<session>/takes/<id>/events.json` (later
revisions `events.<n>.json`): `{"rate": 48000, "events": [[at, "on", note, velocity], [at,
"off", note], [at, "pressure", p], [at, "pedal", bool]], "knobs": [...], ...}`, `at` in
samples at `rate` from the take's own start. There is **no fader automation**: a track has one
`volume_db`; a clip has a gain envelope `Clip::env: Vec<(i64, f64)>` (samples from the clip's
start, dB; -48 to +12), which the live mix and the mixdown both follow (`session.rs:1043,
262`). MIDI controllers are only stored as (last value, count) (`midi.rs:216-247`); the mod
wheel alone maps to a knob. Offline renders: `examples/render.rs --circuit NAME --input FILE
[--set k=v]`; a chain of inserts: `examples/print.rs`.

**The engine's linearization.** `DkSystem::solve_linearized` (`crates/circuitsim/src/dk.rs:
594`) already solves `(A + N^T G_d N)^-1 E_S e` with the devices' Jacobians of the last Newton
iteration; `DkNewton::jacobians()` (dk.rs:743) returns them; current columns between two nodes
already exist for the noise sources (`Mna::current_columns`, `mna.rs:706`).

---

## AM0. The shared toolkit

A small package the others use. Build it first, with its tests.

### `varimu/magic/render.py`

```python
def through(circuit: str, x: np.ndarray, *, overrides: Mapping[str, Any] | None = None,
            quality: str = "production", noise: bool | int | None = None,
            heaters: bool | str | None = None, cores: str | None = None,
            origin_s: float = 0.0, controls: Mapping[str, np.ndarray] | None = None,
            settings: TransientSettings | None = None,
            probes: Sequence[str] = ("out",), cache: bool = True) -> dict[str, np.ndarray]:
    """x (dBFS scale, at the settings' sample rate) through config/circuits/<circuit>.yaml;
    each probe's output on the dBFS scale."""
```

Steps: the pattern under "What exists", with `builder.build(c, overrides or {},
triode_formulation=st.triode_formulation, cores=cores if cores is not None else st.cores,
noise=noise, heaters=heaters)` (as `runner.build_circuit` does) and
`r.vectors[f"v({p})"] / v_out` per probe. `settings` overrides the quality's settings (AM13
needs that).

Cache (when `cache`): the key is the sha256 of the circuit file's bytes, `json.dumps` of the
sorted overrides, the quality, `repr` of noise / heaters / cores / origin_s, `repr(settings)`
when given, `x.astype("<f8").tobytes()`, each control's bytes, `circuitsim.SOURCE_HASH` and a
module constant `VERSION`. Files `cache/magic/renders/<key>.npz`. (The render cache of
`runner` can't be used: it has no noise or heaters argument.)

```python
def through_many(jobs: Sequence[dict], workers: int | None = None) -> list[dict]:
    """`through(**job)` for each job on a thread pool (runner.default_jobs() workers)."""
```

### `varimu/magic/null.py`

```python
def align(a, b, fs, max_lag_s=0.05) -> tuple[np.ndarray, np.ndarray, float]:
    """a and b cut to their overlap with b delayed to match a; the delay in samples
    (fractional: the cross-correlation's peak, refined by a parabola through three points,
    applied as a windowed-sinc fractional delay)."""

def delay_track(a, b, fs, window_s=0.05, hop_s=0.01, max_lag_s=0.002) -> tuple[np.ndarray, np.ndarray]:
    """(times, delay of b against a in seconds) from windowed cross-correlations, each
    peak refined by a parabola; windows whose correlation peak is under 0.5 are NaN."""

def dewarp(b, fs, times, delay_s) -> np.ndarray:
    """b resampled so that its delay track against a is zero: NaNs filled by linear
    interpolation, the track smoothed (a 3-point median, then a 30 ms Hann), b read at
    t + delay(t) from an 8x upsampled copy (scipy.signal.resample_poly) by linear
    interpolation."""

def null_report(a, b, fs) -> dict:
    """How deep two passes null, in stages. All levels in dB re a's rms.
    raw: a - b after `align`.
    gain: a - g b (difference.align_gain).
    filter: the character part of difference.decompose(a, b) (one fixed filter removed).
    dewarped: the character part after `dewarp` (the time base removed).
    bands: {third-octave centre: the 'gain' residual's level in that band re a's level in it}.
    over_time: (t, 'gain' residual per 100 ms block)."""
```

### `varimu/magic/listen.py`

Copy from `scripts/separation_listen.py`: `player(fs, device, channels)`, a generic
`staircase(make_trial, start_db, min_db, max_db, rng)` where `make_trial(level_db, odd)`
returns the three intervals, and `save(folder, stamp, data)` writing JSON to
`data/judgments/magic/<test>/<stamp>.json`. Add `abx(a, b, trials, rng)`: each trial plays A,
B, then X (A or B at random); the user answers a / b; return the count correct and the
one-sided binomial p-value. Every pair passed to these is loudness-matched by the caller.

### Tests (`tests/test_magic_toolkit.py`)

- `through("triode_stage", x)` equals the pattern written out by hand, and a second call reads
  the cache (the file's mtime doesn't change).
- `null_report` on `b = 0.5 * a`: raw about -6 dB, gain under -200 dB.
- `b` = `a` through a one-pole low-pass: gain shallow, filter under -60 dB.
- `b` = `a` with a 5 Hz sinusoidal delay of 30 us peak: filter shallow at 4 kHz, dewarped at
  least 25 dB deeper.
- `align` recovers a 3.3-sample delay within 0.02 samples.

**Done when** the tests pass. **Cost:** half a session.

---

## AM1. Record forensics

**New.** (FUTURE_DIRECTIONS.md 8.3 fits one unit to captures of that unit; this measures whole
records.)

**The question.** Which measurable properties separate a 1960s record from a modern one, and
which mechanisms in our chain move each of them? Without this the other packages aim at
guesses.

**What to build.** `varimu/magic/fingerprints.py`: functions from audio to numbers, each
validated on synthetic signals with known answers before it sees music. Then
`scripts/record_forensics.py FILE_OR_FOLDER ... [--label NAME] [--out reports/magic/forensics]`
writing `<label>.json` (every fingerprint per file, then medians and quartiles over files) and
overlay plots when several labels are given.

The fingerprints (inputs: `x` mono or `(n, 2)` stereo, `fs`; analyse at 48 kHz, resampling
with `scipy.signal.resample_poly`):

| Name | Definition | Synthetic check |
|---|---|---|
| `ltas` | Third-octave long-term power spectrum, 25 Hz-20 kHz (Welch, 8192, Hann). Also `tilt_db_oct`: the slope of a line through the 100 Hz-10 kHz bands; `hf_edge_hz`: the highest band within 40 dB of the 1 kHz band | Pink noise: tilt -3.0 +- 0.2 dB/oct; noise low-passed at 12 kHz: edge 12.5 kHz band |
| `crest_by_band` | Per octave band 63 Hz-8 kHz: peak over rms in dB in 3 s windows, the median over windows | A sine: 3.0 dB; white noise: 11-13 dB |
| `asymmetry` | Per 3 s window: 20 log10(max positive / max negative), and the skewness; the median of the absolute values | A 100 Hz pulse train through a high-pass: large; after 4 all-pass poles at 200 Hz: at least 3 dB smaller |
| `level_distribution` | Short-term level: K-weighted rms in 400 ms blocks, 100 ms hop (the K-weighting filter as `k_weight` in `scripts/lightfoot_mix_analyze.py:25`; pyloudnorm per block is too slow); report the 10 / 50 / 95 percentiles and their spread | A tone stepping between two levels 12 dB apart: spread 12 dB |
| `comodulation` | `grouping.envelopes(x, fs)`; compress each envelope (power 0.3), band-pass 2-32 Hz, correlate every pair of bands at least 8 channels apart; report the mean. The record's bands moving together | Independent noise bands: 0 +- 0.1; one envelope imposed on all: over 0.8 |
| `floor_follow` | A proxy for noise that follows the signal. STFT (2048, hop 512). Per frame: `floor` = the 10th percentile of bin power in 6-12 kHz (dB), `level` = the frame's 100 Hz-4 kHz power (dB). Over frames within 30 dB of the loudest: the regression slope of floor on level, and their correlation | A 200 Hz tone with a 3 Hz tremolo plus stationary noise: slope under 0.1; the same with the noise multiplied by the tremolo: slope 0.8-1.0 |
| `hum` | Level of 50, 60, 100, 120, 150, 180 Hz lines above the median of their neighbouring bins (a 16 s FFT) | A planted 60 Hz line at -70 dBFS under pink noise at -40: found within 1 dB |
| `stereo` | Stereo only: correlation of L and R; side / mid level in dB; magnitude-squared coherence per octave band (`scipy.signal.coherence`, 4096) | Identical channels: coherence 1, side -inf; independent noise: coherence under 0.1 |
| `tuning` | Per 10 s window: spectral peaks 200-2000 Hz (STFT 8192), each peak's cents modulo 100 re A4 = 440, their circular mean: the record's pitch offset. Report the median and the drift (max - min) | A chord synthesized 15 cents sharp: +15 +- 2 |
| `flutter` | Manual: `--tone-band LO HI --segment T0 T1` names a sustained fixed-pitch partial (a piano, organ or vibraphone note). The method of `scripts/tape_flutter.py:59-70`; report the rms deviation in 0.2-6 Hz (wow) and 6-200 Hz (flutter) | A 1 kHz tone with 0.1% rms of 5 Hz frequency modulation: 0.1% +- 0.01 in the wow band |
| `bass_arrival` | **Paired comparisons only** (the same performance through two chains). At each onset (`grouping.onsets`) the lag that maximizes the cross-correlation between the 2-6 kHz envelope and the 40-100 Hz envelope, +-60 ms; the median | A click plus a 60 Hz burst delayed 20 ms: 20 +- 2 ms |

`floor_follow` and `bass_arrival` are proxies: real music confounds them (the program's own
highs, the instrument's own low-frequency build-up). Report them only as differences between
versions of the same material until the synthetic checks have been extended to mixes.

**Material.**
- The user's own files, never committed: add `data/reference_records/*` to `.gitignore` next
  to `data/clips/*`, with subfolders per label (`era_1960s/`, `modern/`). The user supplies
  them; ask which records, do not download any.
- The paired case: `stems/Did she mention my name/full/` (`bass.wav`, `guitar.wav`,
  `harmonies.wav`, `lead vocal.wav`: 96 kHz, 24 bit, stereo, 157.08 s [code]) and the mixes in
  `reports/lightfoot_mix/` (`mix_no_tape.wav`, `mix_through_4track.wav`) against the 1968
  release, if the user has a copy. **Ask the user first what the stems are** (the original
  multitrack, a re-recording, or stems separated from the release): the pairing only means
  something for the first.

**The mechanism map.** After AM14's switches exist, `scripts/forensics_mechanisms.py` renders
one program through each chain variant and tabulates the fingerprints' change per mechanism
(rows: mechanisms; columns: fingerprints). The fingerprints that differ between the eras and
that some mechanism moves are the leads.

**Tests** `tests/test_magic_fingerprints.py`: every row's synthetic check.

**Done when** the synthetic checks pass, the two Lightfoot mixes and at least one era pair
have reports, and a short `reports/magic/forensics/README.md` says which fingerprints separate
them, with the proxies' limits stated.

**Cost.** One session for the fingerprints; minutes of compute per record.

---

## AM2. The two-pass null

**New.**

**The question.** Play the same input through a device twice. In hardware the two outputs
never cancel exactly; in a plugin they cancel to nothing. How deep do ours cancel, what limits
it, and which of our devices are frozen?

**No published anchor.** A search found no measured two-pass null for a tape machine [search].
The figure given in the conversation that preceded this document (-20 to -30 dB) was from
memory and is withdrawn. A physical expectation instead [estimate]: two passes with
independent flutter differ by a time displacement of rms `sigma_t` seconds, and the residual of
a tone at `f` is about `20 log10(2 pi f sigma_t sqrt(2))` dB. A flutter component of relative
depth `e` at `f_w` hertz displaces by `e / (2 pi f_w)`: 0.1% at 5 Hz is 32 us, so about -11 dB
at 1 kHz and -31 dB at 100 Hz. If the model's flutter is right, tape should null badly above a
few hundred hertz and well in the bass, and `dewarp` should recover most of it.

**What to build.** `scripts/two_pass_null.py [--only DEVICE ...] [--clip NAME] [--seconds 10]`
-> `reports/magic/null/`.

The program: 10 s of `data/clips/Dry Guitar.wav` and of `data/clips/drums_setmefree.wav` (the
clips other scripts use), scaled to -18 dBFS rms as `reverb_listen.py:57` does, with a 20 ms
fade in.

The pass pairs, each compared with `null.null_report`:

| Pair | Pass A | Pass B | What it isolates |
|---|---|---|---|
| P0 | `noise=False` | the same again | A sanity check: must be bit-identical (the cache off for B) |
| P1 | `noise=False, origin_s=0` | `noise=False, origin_s=7.3` | The mains' phase against the music (ripple, hum) |
| P2 | `noise=1` | `noise=2` | Everything seeded: resistor and tube noise, mains wander |
| P3 | `noise=1, origin_s=0` | `noise=1, origin_s=7.3` | The same unit at another moment |
| P4 | `heaters="warm"` | `heaters="cold"` | Only for `fender_5e3_mods` and `tube_synth`: a warm unit against one just switched on (state the limit: 10 s is inside the 7 s thermal lag) |

Devices (production quality): `fairchild_670`, `pultec_eqp1a`, `telefunken_v76`,
`fender_5e3`, `urei_1176`, `ssl_bus_comp`, `plate_reverb`, `fender_6g15`, `ampex_351` (through
the code of `print_351.py`, P2 and P3 only).

The tape machine on its own, through `tape_machine.print_audio` (set up as
`scripts/tape_print.py` does), where the two seeds are separate:

| Pair | Pass A | Pass B |
|---|---|---|
| T1 grain | `noise_seed=1, transport_seed=0` | `noise_seed=2, transport_seed=0` |
| T2 transport | `noise_seed=None, transport_seed=0` | `noise_seed=None, transport_seed=1` |
| T3 both | `noise_seed=1, transport_seed=0` | `noise_seed=2, transport_seed=1` |

**Outputs.** `summary.json`: per device and pair the four stages of `null_report` and the
bands. `null.png`: per device, the residual against frequency for each pair. WAVs of the
residuals as they are, and with +20 dB marked in the file name. `README.md`: a "liveness"
table (device x pair -> the `gain` and `dewarped` levels), the tape's residual against the
estimate above, and a list **"more deterministic than hardware"**: every pair that nulls
below -120 dB. For each of those, name what a real unit would vary between passes that the
model holds fixed (no `noise:` block in the file, thermal state, a pot's position). These are
candidates, not changes: adding a `noise:` block to a circuit moves its renders and is the
user's decision.

**Tests** `tests/test_magic_null.py`: P0 on `triode_stage` is identical; P2 on `triode_stage`
gives a finite residual whose level matches the stage's output noise (render silence with
`noise=1` and compare within 1 dB).

**Done when** the table exists for the devices above and the tape's result is compared with
the estimate. Listening is optional here: the result is a measurement.

**Cost [estimate].** Per device about 8 renders of 11 s (settle included). At 14-36x real time
for the 670 that is 20-50 minutes on one thread, a few minutes in parallel. The 351: 4 renders
x 10 s x 27 = 18 minutes. `print_audio`: 6 x 10 s x 24 = 24 minutes.

---

## AM3. Distance to an era

**New.**

**The question.** Is there one number for "sounds like a 1960s record" that can score a chain
variant, so that the ablations (AM14) and the design-space charting (EMERGENCE_RESEARCH.md 3)
have an objective that isn't a spec sheet?

**Background.** The Fréchet audio distance compares the statistics of embeddings of two sets
of audio (two fitted Gaussians) and needs no matched reference (Kilgour et al., Interspeech
2019) [search]. Its original embedding is VGGish. Later work is reported to prefer other
embeddings for music and to ship a toolkit [memory: Gui et al. 2024, the `fadtk` package;
check before use].

**The confound.** Era correlates with repertoire, arrangement and performance. So never
compare absolute distances between unrelated material. Use differences on the **same
performance**: `D(variant) - D(baseline)`, both measured against the era corpus.

**Step 1 (no new dependency): a statistics distance.** `varimu/magic/era.py`:
- `features(x, fs) -> (windows, d)`: per 2 s window (1 s hop) the texture statistics of
  McDermott and Simoncelli (Neuron 2011) [memory] on `grouping.envelopes`: per ERB band the
  envelope's mean (dB), coefficient of variation, skewness; the correlation of envelopes
  between bands 2, 4 and 8 channels apart; the envelope's power in modulation bands 2, 4, 8,
  16, 32 Hz. About 32 x 3 + 3 x 30 + 32 x 5 numbers per window.
- `frechet(f_a, f_b) -> float`: means and covariances, each covariance shrunk toward its
  diagonal (`0.9 S + 0.1 diag(S)`; say that the 0.1 is a choice), then
  `|mu_a - mu_b|^2 + tr(S_a + S_b - 2 (S_a S_b)^(1/2))` with `scipy.linalg.sqrtm` (take the
  real part).
- `era_delta(variant, baseline, corpus, fs)`: `frechet(features(variant), F_corpus) -
  frechet(features(baseline), F_corpus)`; negative means the variant moved toward the era.
- A bootstrap over windows (200 resamples) for an interval on the delta.

Checks before trusting it (`tests/test_magic_era.py` for the synthetic ones):
- two halves of one corpus: a distance near 0, the floor;
- held-out era files against the era corpus are closer than modern files against it; if not,
  the features don't carry the era and step 2 is needed;
- a known change (a 6 dB shelf, a band limit at 10 kHz) moves the delta in a stated direction.

Corpus size: at least 30 minutes per label (about 1800 windows against about 350 dimensions;
with less, use the diagonal only).

**Step 2 (the user decides): a learned embedding.** Needs `torch` (the `ml` extra exists) and
pretrained weights downloaded from the network. Ask the user before adding a dependency or
downloading weights. Keep step 1's interface: only `features` changes. Run on the RTX 3080.

**Done when** step 1's checks have run on the user's corpora and the two Lightfoot mixes have
a delta with an interval. A flat result ("the statistics distance cannot tell the eras apart
beyond tilt and bandwidth") is a full result and decides step 2.

**Cost.** One session; minutes of compute.

---

## AM4. Generations

**New.**

**The question.** With four tracks, a 1960s production bounced: the rhythm track could pass
through record, tape and playback three or four times before the mix, then once more to the
master. What compounds with each generation, and what converges?

**What to build.** `scripts/tape_generations.py [--generations 4] [--clip NAME] [--seconds
20]` -> `reports/magic/generations/`.

1. Load the 351 and its alignment exactly as `scripts/print_351.py` does (copy its setup
   lines; the alignment comes from `cache/tape/`, made by `scripts/align_351.py`).
2. **Unity gain between generations.** Print a 400 Hz tone at -18 dBFS (0 VU). The output
   must be within 0.2 dB of the input; if it is not, apply that one measured gain between
   generations. Never normalize a generation by its program loudness: the tape's compression
   is part of the result.
3. **A different stretch of tape per generation.** Build generation k with `noise=k` (k = 1,
   2, ...). With one seed for all, every generation has the same flutter and grain pattern,
   and after the head delay is removed they add in step (flutter growing as N instead of
   sqrt(N)). **For this reason do not use `examples/print.rs` with the tape insert repeated:**
   every insert there is seeded alike.
4. **Remove the head delay** between generations: `null.align` each output to its input (a
   delay of 50.8 mm over the tape speed plus the electronics') and cut.
5. Generation 0 is the input; G1..G4 are successive prints. Also the bounce case with two
   clips: (a) each printed, then summed, then printed again; (b) summed and printed once.

**Measures per generation.**
- Tones (4 s each, 3 s analysed): THD at 400 Hz and 1 kHz at 0 VU (`tape_align.thd`); the
  response at 50, 100, 1k, 5k, 10k, 15 kHz at -20 dB; S/N (`tape_suite.band_rms` of a silent
  print in 50 Hz-15 kHz against the 0 VU tone); flutter (the method of
  `scripts/tape_flutter.py`).
- Program: `difference.levels(G0, Gk)` (tone and character), third-octave levels re G0, and
  the AM1 fingerprints `crest_by_band`, `comodulation`, `floor_follow`, `asymmetry`.

**Expectations to check [estimate].** Noise power adds: S/N falls by `10 log10(N)` dB (3 dB
at 2, 6 dB at 4). Independent flutter grows as `sqrt(N)`. The linear response is the single
pass's to the power N (a -1 dB corner becomes -4 dB at four generations). Distortion products
of products appear. Whether the compression of peaks saturates (each generation has less left
to compress) is the open part: look at `crest_by_band` against N.

**Tests** `tests/test_magic_generations.py` on the fast path: the same chain on
`tape_machine.print_audio` with a 1 s tone, two generations: S/N falls by 3 +- 1 dB; the
flutter grows by 1.2-1.6x with different transport seeds and by more with equal ones (measure
the equal-seed factor and record it: it depends on how the pattern lines up after the head
delay).

**Done when** the table (measure x generation) and the plots exist, the three expectations
are confirmed or contradicted with numbers, and loudness-matched G0 / G1 / G4 files are in
`reports/magic/generations/audio/` for the user.

**Cost [estimate].** A 20 s clip x 4 generations x 27 = 36 minutes, run one after another
(each needs the last). Tones: 8 x 4 s x 4 generations x 27 = about an hour. Tell the user
before starting.

---

## AM5. Dispersion before saturation

**New.**

**The question.** Every coupling capacitor and transformer adds a high-pass pole, and every
pole rotates phase. Across a whole chain the rotation is large in the bass and reshapes every
waveform before it reaches the next nonlinear stage. Broadcast processors do this on purpose:
a "phase rotator" (typically four all-pass poles at 200 Hz) makes voice waveforms symmetric
and can lower their peak-to-average ratio by 3-4 dB ahead of a limiter (Orban 2001); a drum
track lost 1.6 dB of peaks through an all-pass in one published demonstration [search]. Does
the accumulated phase of a 1960s chain change what the saturation after it does?

**The size of it [estimate].** One first-order high-pass at `f0` delays `f` by
`tau = (1 / (2 pi f0)) / (1 + (f / f0)^2)`. Twenty such poles at 10 Hz: 18.7 ms at 40 Hz,
4.9 ms at 80 Hz. Transformers are second order and add more. The count of poles in our chain
is not assumed: step 1 measures it. No controlled threshold for group delay below 500 Hz was
found; the rule of thumb of one to two cycles (25 ms at 40 Hz) is an extrapolation of Blauert
and Laws (1978) [search]. So the delay by itself is near the edge of audibility, and the
interesting part is its effect on the nonlinear stages.

**Step 1: measure each stage's phase.** `varimu/measure/ac.py` refuses circuits with devices
(`Unsupported`), so measure by rendering. `varimu/magic/dispersion.py`:
- `small_signal(circuit, overrides, fs) -> (f, H)`: a 10 s exponential sweep, 10 Hz-40 kHz,
  at -40 dBFS through `through(..., noise=False)`; `H = FFT(y) / FFT(x)` on the sweep's
  band; remove the pure delay (the slope of the unwrapped phase between 1 and 5 kHz).
- `group_delay(f, H)`: `-d(phase) / d(omega)`.
- Check: at -50 dBFS the result is the same within 0.1 dB and 1 degree (it is small-signal).
- Stages: `telefunken_v76`, `pultec_eqp1a` (flat), `fairchild_670` (below threshold),
  `ampex_351` (record, tape, playback: this one through `print_351.py`'s setup, the head
  delay removed with the rest), `ampex_351` again (the mix-down), `fairchild_670` again (the
  master). A lathe and a playback cartridge are not built; say so in the report.
- Output: each stage's group delay, the cumulative delay against frequency, and the fitted
  count of high-pass poles (a fit of the model above to the cumulative phase below 200 Hz).

**Step 2: the chain's phase as a filter.** From the cumulative `H`:
- `allpass_fir(f, H, fs, n=2**16)`: unit magnitude, the chain's phase:
  `irfft(exp(1j * phase))`, rotated to be causal, windowed (Hann over the last quarter).
  Check that its magnitude is flat within 0.05 dB from 20 Hz to 20 kHz.

**Step 3: the commutator.** For a saturating stage S (three cases: `print_audio` at
`drive_db` 0 / +6 / +12; the 670 at about 6 dB of gain reduction; `fender_5e3` at
`volume_bright` 0.7) and a program x (drums, a male voice, the bass stem):
- `y1 = S(AP(x))` (rotated, then saturated: the historical order);
- `y2 = AP(S(x))` (saturated, then rotated).
Both have the same linear magnitude and the same linear phase; they differ only in the order.
- Report: the crest factor of `x` and of `AP(x)` (overall and per octave: AM1's function);
  the stage's own reading (gain reduction for the 670, THD-like character level for the
  others); and `difference.levels(y2, y1)`: the `character` level is the interaction. If
  dispersion and saturation commuted it would be minus infinity.
- With seeded stages keep the seeds equal in both orders (`noise=False` for circuits;
  `noise_seed=None`, `flutter=False` for `print_audio`), or the seeds' difference hides the
  effect.

**Step 4: listening.** `y1` against `y2`, LUFS-matched, with `listen.abx`, on the case with
the largest interaction. Realistic drive first. If the user cannot tell them apart at
realistic drive, the result is "verified: subtle" and the package closes.

**Tests** `tests/test_magic_dispersion.py`: `small_signal` on an RC high-pass circuit (build a
small test circuit file, or use `triode_stage` and compare with a 2x finer sweep) matches the
analytic phase within 1 degree; `allpass_fir` of a known first-order all-pass matches
`scipy.signal.lfilter` of it within -60 dB; a `tanh` commutes with a pure delay (the
interaction under -100 dB) and does not commute with the four-pole 200 Hz all-pass on a pulse
train (above -40 dB).

**Done when** the cumulative delay curve exists, the interaction level is tabulated against
drive for the three stages and three programs, and the user has done the ABX on the largest.

**Cost [estimate].** Step 1: six sweeps of 11 s: minutes, except the 351 (5 minutes each).
Step 3: 3 stages x 3 drives x 3 programs x 2 orders x 10 s: tape rows 18 x 10 s x 24 = 72
minutes; the others minutes.

---

## AM6. Noise-forced gain staging

**New.**

**The question.** A 1960s engineer ran every stage as hot as the hiss demanded and as cool as
the distortion allowed. Digital has no such pressure. If we set each stage's level where noise
plus distortion is least, do the period's operating levels, and with them the period's amount
of saturation, come out of the physics?

**What to build.** `scripts/noise_forced_levels.py [--only STAGE ...]` ->
`reports/magic/levels/`.

Per stage (start with `telefunken_v76`, `ampex_351` through `print_351.py`'s setup,
`fairchild_670`, `pultec_eqp1a`) and per input level `L` from -40 to +6 dBFS rms in 3 dB
steps, on a 6 s program clip:
1. **Noise:** `through(stage, zeros, noise=1)`; its rms, A-weighted (an A-weighting filter is
   needed: write `a_weight(x, fs)` from IEC 61672's poles, 20.6, 107.7, 737.9 and 12194 Hz,
   with the citation in a comment, and check it reads 0 dB at 1 kHz and -19.1 dB at 100 Hz).
   Noise does not depend on `L`: render once.
2. **Distortion:** `y = through(stage, x * g, noise=False)`; the `character` level of
   `difference.decompose(x * g, y)` is everything a fixed filter does not explain.
3. **The signal:** the rms of `y`.
4. `impairment(L) = (noise^2 + character^2) / signal^2`. The optimum `L*` is its minimum.

**Report.** Per stage: the two curves and their sum against `L`; `L*`; the stage's historical
operating level on the same axis (0 VU = -18 dBFS rms in this project's convention; the tape's
aligned operating level); the distortion at `L*` as a percentage. The claim to test: `L*`
lies within a few dB of the historical level, and at `L*` noise and distortion are about
equal. If it holds, the headless mix (HEADLESS_MIX_PLAN.md) gets a rule for setting levels
that produces period-typical drive without a "drive" guess.

**Limits to state in the report.** The flicker-noise constant and the mains wander are
provisional (`varimu/devices/noise.py`), so every `L*` moves with them: give `L*` at half
and double the noise as well. A-weighted rms is a crude ear: METHODOLOGY_REVIEW.md W5's
masked metric would be the right one and is not built.

**Tests** `tests/test_magic_levels.py`: on a synthetic stage (`y = tanh(x) + noise`) the
optimum found equals the analytic one within one step; `a_weight`'s two checks.

**Done when** the four stages have curves and the claim is confirmed or contradicted.

**Cost [estimate].** Per stage 17 renders of 7 s: the 670 at about 25x is 50 minutes on one
thread, 5 in parallel; the 351 about 55 minutes.

---

## AM7. Noise that fuses

**Extends EMERGENCE_RESEARCH.md 6** (noise from microphysics) with a perceptual hypothesis
and a pass / fail test. Nothing in a model changes.

**The hypothesis.** Stationary hiss is heard as a separate sound. Noise whose envelope
follows the signal should be grouped with the signal by the ear's own rules (common
modulation, common onset: SCENE_ANALYSIS.md section 1) and heard as part of its timbre.
Speech synthesis found exactly this: stationary aspiration noise is "to a large extent
perceived as coming from a separate sound source", while noise bursts synchronous with the
pitch pulses fuse with the vowel, lowering the loudness of the separate noise stream and
changing the vowel's timbre (Hermes, Speech Communication 10, 1991) [search: abstract only].
Tape's modulation noise is of the fusing kind. A dither floor is of the other.

**Two predictions.**
1. A signal-following noise is harder to detect than a stationary one of the same power
   (comodulation detection differences, 1-12 dB: McFadden 1987, cited in SCENE_ANALYSIS.md).
2. Above threshold, the stationary one is heard as "noisier" and the following one as a
   change of the source's tone.

**Stimuli** (`varimu/magic/fusing.py`; all DSP on existing renders; seeded):
- Carriers `s`: `cache/separation/conditions/dry/target.wav` (the tube synth's dry line; run
  `scripts/separation_study.py` if it is missing), a bass note line, a voice clip from
  `data/clips/`. 4 s excerpts, 20 ms fades.
- `n_phys`: the tape model's own signal-dependent noise. Through `print_audio` with
  `flutter=False` in both: `y1` with `noise_seed=1`, `y0` with `noise_seed=None`;
  `n_phys = y1 - y0`; the clean carrier is `y0`. (On the circuit path grain cannot be
  switched without changing the transport's seed, which would bury the noise in time-base
  differences.)
- `n_stat`: stationary Gaussian noise with `n_phys`'s long-term spectrum (shape white noise
  by `n_phys`'s Welch spectrum, a 4096-tap FIR) and its exact rms.
- `n_env`: `n_stat` multiplied by the broadband envelope of `y0` (Hilbert, low-passed at
  30 Hz), rescaled to the same rms.
- `n_band`: per ERB band (`grouping.erb_centres_hz`), `n_stat`'s band multiplied by `y0`'s
  envelope in that band, summed, rescaled.
- Report for each: `grouping.temporal_coherence(y0, n, fs)["cross"]` and the noise's level
  re `y0`. Expect about 0 for `n_stat` and high for the others. **If `n_phys` reads near 0,
  the model's tape noise does not follow the signal** and that is the first finding: stop
  and report it before any listening.

**Listening** (`scripts/fusing_noise_listen.py`, on `varimu/magic/listen.py`; run with
`uv run --extra listen --with sounddevice python ...`):
- **Task 1, detection.** A staircase per noise kind and carrier: three intervals, two are
  `y0`, one is `y0 + g n`; the level `g` adapts (start +20 dB re the physical level, floor
  -30). The threshold is the noise level at which it is just heard. Compare thresholds:
  prediction 1 says the following kinds need at least 3 dB more than `n_stat`.
- **Task 2, which is noisier.** At 10 dB above the higher threshold: pairs `y0 + n_stat`
  against `y0 + n_phys` (and `n_env`, `n_band`), equal noise power, LUFS-matched, order
  random, 12 trials per pair: "which is noisier? 1 / 2". Report the proportion.
- First record where the physical level (g = 0 dB) sits against the threshold: if the tape's
  own noise is below threshold on these carriers at realistic level, say so. That alone
  answers whether it can matter on a single generation (AM4 says what four do to it).

**Tests** `tests/test_magic_fusing.py`: the constructed noises have equal rms within 0.01 dB
and equal long-term spectra within 1 dB per third octave; coherence under 0.15 for `n_stat`
and over 0.6 for `n_env` on a tremolo tone.

**Done when** the coherence table exists and the user has run both tasks on at least two
carriers; the write-up states the threshold differences and the proportion, and whether the
physical level is above threshold.

**Cost.** Half a session of code; six `print_audio` runs of 5 s (10 minutes); about 20
minutes of the user's listening.

---

## AM8. Nothing in the room holds still

**New.** (STEREO_PLAN.md lists a Leslie's moving source as out of scope; this is slow, small
motion and drifting air.)

**The hypothesis.** A convolution reverb and our rooms return the identical tail for the
identical note, forever. A real room does not: the player sways a few centimetres, so the
comb filters of the early reflections sweep, and the air's temperature drifts, which changes
every delay in proportion to its length. Room impulse responses are known to vary with small
temperature changes; the effect has been compensated by linearly time-warping the response
(Tatekura et al., EUSIPCO 2002) and measured as a loss of coherence between repeated
measurements (Prawda, Schlecht and Välimäki, JASA 2024; Elko, Diethorn and Gänsler, IWAENC
2003) [search: the citations confirmed, the papers not read]. Listeners learn an exactly
repeated noise pattern within a few presentations and keep it for weeks (Agus, Thorpe and
Pressnitzer, Neuron 66, 2010) [search], so exact repetition is a cue that something is
artificial.

**Sizes [estimate].** Sway of 2 cm rms at 0.3 Hz moves a 1 m path's delay by 58 us rms: at
4 kHz that is 1.5 rad, a comb filter fully re-tuned. A uniform temperature change of 0.1 C
changes the speed of sound by 0.017% (`c = 331.3 sqrt(1 + T / 273.15)`), so a reflection
arriving at 500 ms moves by 85 us: 2.7 rad at 5 kHz. The early sound barely changes; the late
tail above 2 kHz becomes a new realization. Both motion values are `provisional: model
knowledge` until a source is found.

**What to build.** `varimu/magic/moving.py`, wrapping the rooms code. **Do not edit
`varimu/rooms/*`**: those files are hashed into the room response cache
(`scene.RESPONSE_CODE`), and an edit recomputes every cached room.

(a) A swaying source.
1. `sway(n, fs, rms_m, hz, seed) -> (n,)`: displacement along one axis: Gaussian noise
   through a second-order band-pass at `hz` (Q 1), scaled to `rms_m`, at 100 Hz then
   interpolated to `fs`.
2. Position grid: `K` points along the axis covering +-3 `rms_m`, spaced 2 mm (61 points for
   2 cm rms).
3. Early responses per grid point: `shoebox.responses(room, [p_k], mics, fs, tail=False)`.
   Call it directly, not through `scene._cached_responses` (which keeps only 12 files); save
   the stack as one `.npz` in `cache/magic/moving/` keyed by the room, the grid and the mics.
   Measure one call's time first and tell the user the total.
4. The static tail, once: `responses(..., tail=True) - responses(..., tail=False)` at the
   centre position.
5. Per grid point convolve the whole dry signal with that point's early response (FFT
   convolution, `scene._fftconv`'s method): `y_k`.
6. Mix over time with triangular weights on position: at each sample the two grid points
   around `p(t)` get weights by linear interpolation; `y_early(t) = sum_k w_k(p(t)) y_k(t)`.
   At 2 mm spacing two neighbours differ by 5.8 us, so the interpolation's own comb error is
   under 0.6 dB at 20 kHz.
7. Add the dry signal convolved with the static tail.

(b) Drifting air.
1. `drift(n, fs, rms_c, minutes, seed)`: a slow temperature offset: Gaussian noise low-passed
   at `1 / (60 minutes)` Hz, scaled to `rms_c` (0.1 C, provisional).
2. `eps(t) = -0.5 * drift / (273.15 + temp_c)`: the relative change of every delay (warmer
   air is faster, so delays shrink).
3. A grid of 9 values of eps over +-3 sigma; for each, the full response time-scaled:
   `h_eps[n] = h0` read at `n (1 + eps)` from an 8x upsampled copy, linear interpolation.
4. Convolve and mix as in (a) 5-6, with weights on eps.

A uniform temperature change is what this models (heating cycling). Local turbulence and
people moving are not modelled; say so.

**Measures** (`scripts/breathing_room_demo.py` -> `reports/magic/moving/`), on the room of
`config/scenes/two_sources.yaml`:
- The two-pass null (AM2's `null_report`) between two renders that differ only in the motion
  seed: static rooms give minus infinity; report the level per band.
- The same note struck eight times, 1 s apart (a synthetic decaying tone, then the Rhodes):
  the correlation between the wet parts of repeats 1 and k, per octave band. Static: 1.0.
- Listening: static against swaying against swaying plus drift, LUFS-matched (`listen.abx`),
  at the realistic sizes first. One exaggerated step (3x) only if the realistic one is not
  heard, then stop.

**Tests** `tests/test_magic_moving.py`: with `rms_m = 0` the result equals the static render
within -100 dB; a source moving at constant speed along the axis toward the mic in an
anechoic room (`"anechoic"` material) shifts a 1 kHz tone by `v / c` within 5%; the
interpolation's error against a direct render at an off-grid position is under -40 dB.

**Done when** the measures are tabulated and the user has heard the three versions. If it is
kept, moving it into the scene format (a source's `motion: {rms_m, hz, seed}`, a room's
`drift_c`) is a change to `varimu/rooms/scene.py` and the user's decision.

**Cost [estimate].** 61 calls of `responses` (seconds to tens of seconds each on the GPU
backend; measure) and 61 convolutions per mic entry; about one session of code.

---

## AM9. Instruments listen

**New** as room physics. (DRUM_PLAN.md says a kit is one coupled simulation and lists it for
D4; this couples a drum to any source in the room and needs nothing from D4.)

**The hypothesis.** In a live room every instrument is also a resonator. Toms and the kick
sing along with the bass amp; a piano with the pedal down answers the whole band. Overdubbed,
isolated tracks have none of it. **What this cannot do yet:** the snare's buzz needs snare
wires, which are not built (DRUM_PLAN.md D4). This package gives ringing heads only.

**The physics: reciprocity.** `Prepared2.mic` gives the far-field pressure per modal
acceleration: `p_A = sum_k g_k qdd_k` at distance `R` (`mic_distance_m`), direction
`mic_angle_deg`. By vibroacoustic reciprocity (Lyamshev: the pressure at A per unit force at B
equals the velocity at B per unit volume velocity at A), a point source at A with volume
acceleration `Qdd` puts the modal force `f_k = g_k Qdd` on mode k. The same source's
free-field pressure at the drum is `p_inc = rho0 Qdd / (4 pi R)`. So

```text
f_k(t) = a_k p_inc(t),      a_k = 4 pi R g_k / rho0
```

`a_k` has the units of an area: for a compact drum it is the head's area weighted by the mode
shape, and it does not depend on `R` (`g_k` falls as 1 / R). Check with a piston of area S:
`g = rho0 S / (4 pi R)`, so `a = S` and the force is `p S`. Use the acceleration part of the
gain (`gain_acc` in `drum.run`) for `g_k`; the velocity part is a phase correction that
matters only where the drum is not compact (above about 300 Hz for a 13 inch head).

**What to build.**
1. **An opt-in input on the drum** (`varimu/drums/drum.py`, outside the render cache key):
   `run(prep, *, fs, seconds, velocity_m_s, tension_modulation=True, incident_pa=None,
   incident_area=None)`. In the time loop, where the beater's force is added to the new
   modal displacements (`qn += drive_a * f`, near line 494), add the incident force the same
   way: `qn += drive_inc * incident_pa[n]`, with `drive_inc` built from `incident_area` (the
   `a_k` above) exactly as `drive_a` is built from `face` (same step-size and modal-mass
   factors: read lines 450-495 and mirror them). `velocity_m_s=0.0` must be allowed with an
   incident field (no strike). With `incident_pa=None` nothing changes: the existing
   `tests/test_drum.py` must pass unmodified, and a strike's `pressure_pa` must be
   bit-identical to before (assert this in a new test against a saved array).
2. `varimu/magic/sympathetic.py`:
   - `incident_area(prep, d2, theta_deg)`: `a_k` for a source at angle `theta_deg` from the
     drum's axis: prepare a copy of the drum with `body.mic_angle_deg = theta_deg`
     (`dataclasses.replace`) and take `4 pi R * gain_acc / rho0` from it. The modes don't
     depend on the mic angle, so the modal basis is the same; assert that `omega` matches.
   - `pressure_at(room, source_m, point_m, signal_pa, fs)`: the source's pressure at the
     drum: `shoebox.responses(room, [source_m], [Mic(point_m, aim_vector(0), entry_table({},
     fs))], fs)[0, 0, 0]` convolved with the source's signal in pascals at 1 m
     (`scene.source_signals`).
   - `ring(drum_name, incident_pa, fs, theta_deg)`: `drum.run(..., velocity_m_s=0.0,
     incident_pa=..., incident_area=...)`; returns the drum's own radiated pressure at its
     `mic_distance_m`, scaled to 1 m.
   - The drum then becomes a second source at its position: its 1 m pressure through the
     room's responses to the real mics, added to the program. The coupling is one way (the
     drum's sound does not drive the amp back); say so.
3. `scripts/sympathetic_demo.py` -> `reports/magic/sympathetic/`: the room of
   `config/scenes/two_sources.yaml`; the source is the bass stem at 100 dB SPL at 1 m with
   the directivity preset `bass_1x15`; `tom_13` 1.5 m away and `kick_22` 2 m away;
   a spaced omni pair as in that scene. Outputs: the pair without and with the drums'
   ringing, LUFS-matched; the ringing alone; its level re the bass per third octave; the
   drums' fundamentals (`Hit2.f_fund_hz`) against the bass line's notes.

**Tests** `tests/test_magic_sympathetic.py`:
- **Reciprocity** (the test that the formula and its factors are right): (i) strike the drum
  with a small force impulse and read the far-field pressure at A: `p_A / F`. (ii) drive the
  drum with the incident field of a monopole at A and read the head's velocity averaged over
  the beater's face (`face @ qdot`): `v / Q`. The two transfer functions agree within 1 dB
  from the fundamental to 300 Hz. (Use `small(f_max_hz=700.0)` from `tests/test_drum.py` to
  keep it fast.)
- A compact drum's `a_0` for the breathing mode is within 10% of the head's area times the
  mode's mean shape.
- No incident field and no strike: silence.

**Done when** the reciprocity test passes, the demo's files exist, and the user has heard
with against without. Report the ringing's level: if it is more than 40 dB under the bass at
the room mics, say that it is probably inaudible there and try the close position (a tom's
own spot mic).

**Cost [estimate].** One session. Each drum runs 9-14x slower than real time: a 20 s bass
line is 3-5 minutes per drum.

---

## AM10. The floor

**New.** Gated: do step 1 first and stop if it fails.

**The hypothesis.** A kick drum and a bass amp shake the floor, the floor shakes every mic
stand, and a microphone's diaphragm responds to its body's acceleration. This would be a
shared low-frequency thump on every mic of a live session.

**Step 1: an estimate that can close the package (one hour, no code beyond a notebook-style
script).** In the mic's own frame an acceleration `a` of the body is an inertial force on the
diaphragm, equivalent to a pressure difference `p_eq = sigma a`, with `sigma` the moving
system's mass per unit area.
- A condenser's diaphragm (6 um polyester, about 1400 kg/m^3): sigma = 0.0084 kg/m^2. At
  1 m/s^2: 8 mPa, 52 dB SPL.
- A ribbon (2 um aluminium): 0.0054 kg/m^2: 49 dB SPL at 1 m/s^2.
- A moving coil (diaphragm and coil of the order of 0.1 g on 3 cm^2): sigma about 0.3
  kg/m^2: 0.3 Pa, 84 dB SPL at 1 m/s^2.

All four figures are [estimate] from `provisional: model knowledge` dimensions. Replace them
with the fitted values: the moving mass and area in the component files (`R57@4`,
`R_D112@1`, `R_RE20@1`, `K47@3`, `RIBBON_44BX@2` under `config/components/`). Then estimate
the floor's acceleration under a stand 1.5 m from a kick: the beater's force
(`drum.run(...).force_n`, peak and spectrum) into a floor's point mobility (for an infinite
plate `Y = 1 / (8 sqrt(D rho h))`, with D the bending stiffness: 22 mm softwood boards,
`provisional`), times the stand's transmissibility (1 at low frequency for a rigid stand;
isolation above a shock mount's resonance).

**The gate.** Compare `p_eq` with the acoustic pressure of the same kick at the same mic.
If the vibration path is more than 40 dB under the acoustic path for every mic type, write
that down in `reports/magic/floor/README.md` and **close the package as inaudible**. The
expectation from the numbers above: condensers and ribbons fail the gate; a moving-coil mic
on a rigid stand near the kick may pass it at low frequencies.

**Step 2 (only past the gate).** `varimu/magic/floor.py`:
- The floor as a `plate.PlateSpec`: the room's `lx`, `ly`; thickness, density and Young's
  modulus of the boards; `tension_n_m=0.0`; `f_max_hz=500`; `decay` from a loss factor eta
  (energy decay rate `eta * 2 pi f` at each listed frequency; eta 0.02-0.05 for a timber
  floor, `provisional`); `drive_xy` and `pickup_xy` as fractions of the sides.
  `plate.impulse_response(spec, fs)` gives force to acceleration. State the limits: simply
  supported edges, isotropic (a joisted floor is neither).
- The stand: a second-order low-pass on acceleration (resonance and damping `provisional`).
- Into the mic: add `sigma * a(t) * cos(angle between the mic's axis and vertical)` to the
  front pressure before `scene.print_chain`. This is exact for a pressure capsule and an
  approximation for gradient capsules (the proper form is a force on the diaphragm node,
  which needs a new input on the mic parts in both builders: a later step, the user's
  decision).
- A demo like AM9's, with against without, on a moving-coil mic.

**Tests** `tests/test_magic_floor.py`: the floor plate's point mobility averaged over
frequency is within 3 dB of the infinite plate's formula; zero force gives zero.

**Done when** step 1's table exists and either the package is closed by the gate or the demo
has been heard.

---

## AM11. The device plays the player

**New.**

**The hypothesis.** Part of what gear contributes never passes through it afterwards: it
changes the performance. An amp that sags and compresses lets a guitarist dig in; a stiff one
makes them back off. Re-amping a finished take can never show this. The user plays guitar
live through the amps at a 10 ms buffer and keys through the instruments, so it can be
measured on them.

**The manipulation.** One amp, one switch: `fender_5e3_mods` with `rectifier` 1 (5Y3GT, saggy)
against 3 (silicon, stiff) [code: `config/circuits/fender_5e3_mods.yaml:50`]. Everything else
equal. (A second pair if wanted: `mains_v_rms` 120 against 100, the variac.)

**Recording the dry guitar.** A session take does not keep the dry input; `examples/play.rs
--record FILE` does (the input channel at the input device's rate). So the experiment runs on
`play.rs`:

```sh
cargo run --release -p varimu-app --example play -- --device fender_5e3_mods \
  --input "<the Twin's input name>" --channel 0 --buffer 0.01 --for 90 \
  --set rectifier=1 --record data/judgments/magic/player/<stamp>_t01.wav
```

(`--list-inputs` prints the names.) Before the first session check two things in `play.rs`
and `player.rs`:
- **Loudness.** The two conditions must sound equally loud to the player, or level explains
  everything. Render one dry take through both offline (`examples/render.rs --circuit
  fender_5e3_mods --input DI.wav --set rectifier=N`), measure LUFS, and bring the stiffer
  one down with its `volume_bright` until they are within 0.5 LU.
- **The monitor's gain compensation** is on by default in the player
  (`player.set_compensation`, `play.rs:333`). Find out what it does over time (read
  `Monitor` in `player.rs`). If it rides gain within a phrase it would cancel the very
  dynamics under test: then add a `--no-compensation` flag to `play.rs` (a two-line change)
  and use fixed, pre-matched gains.

**The protocol** (`scripts/player_loop_session.py`, a terminal script that launches `play.rs`
with `subprocess` per trial):
- The user chooses one riff they can repeat, about 30 s, with soft and hard passages.
- 12 trials, 6 per condition, in an order drawn from a seed
  (`default_rng([seed, crc32(b"player")])`). The script prints only "Trial 3 of 12: play the
  riff", never the condition. The order is written to the results file, not to the screen.
- One warm-up minute on each condition first, unrecorded.
- Results to `data/judgments/magic/player/<stamp>.json`: seed, order, file per trial.

**Analysis** (`varimu/magic/player.py`, on the dry files):
- onsets: `grouping.onsets(x, fs)`;
- per note: the peak level in the 30 ms after the onset (dB), the spectral centroid of that
  30 ms (a harder attack is brighter), the duration to the next onset or to -30 dB;
- per take: the mean and spread (p95 - p5) of note peaks, the mean centroid, inter-onset
  variability (the standard deviation of the intervals' deviations from their median grid),
  the tempo, the overall rms.
- Statistics: a permutation test on the condition labels per feature (10,000 shuffles),
  the effect size, and a correction for the number of features (Holm). Six against six is
  small: report the intervals, not only p-values.

**For keys** the same without new recording code: an event take's `events.json` holds every
velocity and time. Play the same part on `rhodes_stage_5e3` and on a cleaner variant, read
the `"on"` events, and compare the velocity distributions and timing.

**Step 2, does it reach the sound.** A 2 x 2: takes played on A or B, each rendered through A
and through B (`examples/render.rs`). Listening: "played on A, rendered through A" against
"played on B, rendered through A", LUFS-matched (`listen.abx`). If they can be told apart,
the performance carries the device's mark.

**Tests** `tests/test_magic_player.py`: the feature extractor on a synthetic sequence of
plucks with known levels and times recovers them (levels within 0.5 dB, onsets within 5 ms);
the permutation test finds a planted 2 dB difference in 6 against 6 and finds none in
shuffled data at the stated rate.

**Done when** one session of 12 trials has been played and analysed. A null result ("the
playing did not change within the intervals") is a full result.

**Cost.** One session of code; 30 minutes of the user playing. The 5E3 runs at about 0.4x
real time live, without dropouts.

---

## AM12. The mix as a performance

**Extends HEADLESS_MIX_PLAN.md H2** (fader automation), which is not built.

**The hypothesis.** Until console automation, a mix was performed: hands on faders in real
time, rehearsed, with human lag and overshoot. Drawn automation and rule-based rides have a
different shape.

**Step 1: a model of the hand, for rule-based rides** (`varimu/magic/rides.py`; no app
change). `scripts/lightfoot_mix.py:168` `rides()` computes an ideal gain curve for the lead
(+-3 dB). Wrap it:
- `human_ride(ideal_db, fs_ctrl=100, seed, rehearsed=True)`: the ideal curve through a
  pursuit model: a pure delay (0.2 s unrehearsed; -0.1 to +0.1 s drawn per phrase when
  rehearsed), a critically damped second-order low-pass (1.5 Hz), plus motor noise (0.3 dB
  rms, low-passed at 2 Hz), then held where the change is under 0.5 dB (a hand doesn't move
  for less). All five constants are `provisional: model knowledge`; manual-tracking
  literature (the "crossover model" of McRuer and Jex, 1967 [memory]) is the place to source
  them: do that search first and replace the constants with cited ones.
- Compare three mixes of the Lightfoot session, LUFS-matched: no rides, the rule's rides,
  the hand model's rides. Listening is the user's.

**Step 2: performed rides in the app** (only if the user wants it). What exists: a clip's gain
envelope `Clip::env` is followed by the live mix and by exports; controllers arrive as
`Keys::cc(number) -> (value, count)`; `mixer::fader_db(x)` is the fader's law. The smallest
build:
- a "ride" arm per track and a chosen controller number in the Session view;
- while the transport plays and a track is ride-armed, each UI frame read the controller,
  map 0-127 through `fader_db`, apply it as a live offset on the track's `volume_db`, and
  log (timeline sample, dB);
- on stop, restore `volume_db`, thin the log (keep points that deviate more than 0.25 dB
  from the line between their neighbours) and write the points into the clips under the
  range with `Clip::set_env_point` (one undo step);
- a test in `crates/varimu-app/tests/` that a logged ride reproduces in `Session::mixdown`.
Frame-rate timing (about 16 ms) is enough for rides. This is an app feature: confirm with the
user before building.

**Done when** step 1's three mixes exist and the user has compared them.

**Cost.** Step 1 half a session. Step 2 one session of app work.

---

## AM13. Solo a part

**Extends FUTURE_DIRECTIONS.md 8.2** (the audibility map) with a tool: hear exactly what one
component contributes.

**The idea.** The sensitivity of the output to a part's value, `s(t) = d out(t) / d ln(value)`,
is itself an audio signal: what you would add to the output per unit of relative change of
that part. Played alone it is the part's "solo". Its level ranks every part of a circuit by
how much it matters for a given program, which tells us which provisional values to source
first.

**A correction to the conversation that preceded this document.** It said the sensitivity
costs "about one more back-substitution per step". That is too low: each parameter carries
its own copy of the circuit's states, so a parameter costs about the linear part of a step
(no device evaluations, no Newton iterations), perhaps a third to a half of a plain step
[estimate]. Still several times cheaper than two extra renders, and exact.

### Step 1: finite differences (Python only; the reference for step 2)

`varimu/magic/solo.py`:
- `elements(ir)`: every `Resistor` (`r_ohm`), `Capacitor` (`c_f`) and `Inductor` (`l_h`) of
  the IR by name. The IR is `built.ir`, a `CircuitIR` of frozen dataclasses with `sections`
  [code: `varimu/circuit/ir.py:77-106, 956`]. Read `ir.py` for how sections hold elements;
  do not guess field names.
- `perturbed(ir, name, factor)`: a copy of the IR with that one element's value multiplied
  (`dataclasses.replace` down the nesting).
- `sensitivity(circuit, overrides, x, name, delta=0.01, settings=None)`:
  `(y(1 + delta) - y(1 - delta)) / (2 delta)` with `fast.run_transient` on the two IRs.
  **Settings for this** (or the two runs differ by solver noise, not by the part):
  `dataclasses.replace(st, error_abstol=0.0, error_reltol=0.0, newton_reltol=1e-9,
  newton_vntol=1e-9)` (no step-size control, so both runs take the same steps; tight
  Newton), `noise=False`, heaters off, `cores="linear"` for a first pass.
- **Self-check, always:** compute at `delta` 0.005 and 0.02. If the two results differ by
  more than -30 dB re their own level, flag the part: either the response is not linear in
  that range or the result is under the numerical floor.
- `solo_level_db`: rms of `s` re rms of `y`. `rank(circuit, x)`: every element, through
  `through_many`-style threads, sorted.

`scripts/solo_part.py --circuit NAME [--part NAME | --rank] [--clip C] [--seconds 5]` ->
`reports/magic/solo/<circuit>/`: the ranking as a table (part, value, its `source` text from
the circuit file so provisional values stand out, level), the top ten solos as WAVs at
-23 LUFS, and "what if" files `y + k s` for k = 0.2 (the part 20% up, to first order).

Start with `triode_stage`, then `pultec_eqp1a`, then `fender_5f1`. **Cost [estimate]:** two
renders per part. The EQP-1A (of the order of 100 parts, 5 s, a few times real time): about
an hour on 12 threads. The 670 with a few hundred parts at 14-36x: overnight.

**Tests** `tests/test_magic_solo.py`: for an RC low-pass (a small test circuit) the
sensitivity to R matches the analytic derivative of the filter's response within -50 dB;
`y(1.05)` is predicted by `y + 0.05 s` within -40 dB re `s` on `triode_stage`.

**Done when** the EQP-1A has a ranking and the user has heard a few solos. This already
delivers the audibility map; step 2 only makes it fast.

### Step 2: the tangent-linear run in circuitsim (engine work; ask the user before starting)

Step 2 changes `crates/circuitsim`. With the new option off, every existing result must stay
bit for bit (assert it), and `slice_report.py --verify` is owed afterwards (CLAUDE.md).

**The mathematics.** A stage of the DIRK step solves (`dk.rs` module docs; `try_step_dk`,
`transient.rs:1766`):

```text
G Y_i + N^T i(N Y_i) + F_i = b + u e_in
F_i = C (Y_i - x_n) / (g h) - w_i,        w_i = (1/g) sum_j a_ij F_j
```

Differentiate with respect to a parameter theta (a dot is d / d theta), with `G_d,i` the
devices' Jacobian at the converged stage and `A = G + C / (g h)`:

```text
(A + N^T G_d,i N) Ydot_i = C xdot_n / (g h) + wdot_i + q_i
Fdot_i = C (Ydot_i - xdot_n) / (g h) - wdot_i + (dC/dtheta) (Y_i - x_n) / (g h)
wdot_i = (1/g) sum_j a_ij Fdot_j
q_i    = -(dG/dtheta) Y_i - (dC/dtheta) (Y_i - x_n) / (g h)
```

This is the same stage as the primal's with: no sources and no input; the state `xdot_S` and
stage inputs `wdot` in place of `x_S` and `w`; the devices replaced by the linear `G_d,i`;
and one injected current `q_i`.
- **A resistor** between nodes a and b, theta = ln R: `dG/dtheta = -(1/R) (e_a - e_b)(e_a -
  e_b)^T`, so `q_i = +(1/R) (v_ab)_i (e_a - e_b)`: a current source across the resistor
  equal to the current through it at that stage. (The compensation theorem: a part's change
  acts as a source at its own terminals.)
- **A capacitor**, theta = ln C: `q_i = -C ((v_ab)_i - (v_ab)_n) / (g h) (e_a - e_b)`, and
  the same vector with a plus sign is added to `Fdot_i` on the rows of a and b.
- Inductors and windings come later, the same way with the branch current.

In DK form: `pdot = (responses to xdot_S, wdot and q_i on the port rows)`, then
`(I + K G_d,i) vdot = pdot` (an M x M solve), `idot = G_d,i vdot`, then the states and
`Fdot_i` exactly as the primal computes them from `i`.

**What the code already has.** The responses to the state and the stage inputs
(`DkSystem::step_base`, `stage`, `states`, `unknowns`); current columns between two nodes
(`bw`'s current columns, built from `Mna::current_columns()`; the noise sources use them);
the devices' Jacobians at the last evaluation (`DkNewton::jacobians()`). `solve_linearized`
shows the Woodbury form with the factored matrix.

**What to add.**
1. `Options::sensitivities: Vec<String>` (element names; empty = off, and then no code path
   changes). At `Mna` build, each named element adds one current column (its two nodes) and
   its two nodes to the unknowns computed at every stage.
2. Per parameter a tangent state: `xs_dot` (r), `f_dot` (r), `stage_f_dot` (s x r).
3. In `try_step_dk`, after each stage's Newton solve succeeds: read the element's voltage at
   the stage from the stage's unknowns; form `q_i`; form `pdot`; factor `I + K G_d` from
   `sys.k_matrix()` and `newton.jacobians()` **freshly for this stage** (do not use the
   Newton solver's own factorization: with Jacobian reuse it is a lagged matrix); solve;
   compute `Fdot_i`. Keep these in scratch and commit them only where the primal step is
   committed (after the error and hard-step checks, where `dk.xs` is copied).
   Mirror every branch of the primal loop, including the explicit first stage of the
   ESDIRK methods (`tab.explicit_first()`: stage 0 reuses the last step's `dk.f`, so the
   tangent reuses its `f_dot`).
4. At the step's end the tangent's probe values: the same response rows as `unknowns()`.
5. Output: per parameter, per probe, a vector alongside the primal's. Python:
   `circuitsim.simulate(..., sensitivities=[...])`; call it from `varimu/magic/solo.py`
   directly so that `varimu/sim/fast.py` is not edited.

**Restrictions for the first version; refuse anything else with a clear error.** Solver `dk`
(not `dk_sparse`, not `mna`); no error control (`error_abstol = 0`) and no hard steps; no
partition; no media (tape, plate, spring, harp), no events, no noise, no heaters; no device
with memory (`Device::has_state()` true: JA cores, lamps, optocouplers), so `cores="linear"`;
resistors first, then capacitors.

**Tests** (`crates/circuitsim/tests/sensitivity.rs` and `tests/test_magic_solo.py`): the
tangent matches step 1's finite difference within -60 dB re the sensitivity on an RC
circuit, a diode clipper and `triode_stage`, for a resistor and a capacitor each; with
`sensitivities` empty the outputs of the existing agreement tests are bit-identical.

**Later, in order:** all parameters sharing one factorization per stage; the lagged
factorization as a preconditioner instead of a fresh one; inductors and windings; pots (two
resistors moving oppositely: the chain rule); the app's Editor playing a clicked part's solo.

**Done when** the tests pass and the EQP-1A's ranking from the tangent equals step 1's.

---

## AM14. Interactions between mechanisms

**Extends EMERGENCE_RESEARCH.md 2** (counterfactual hardware), which removes one mechanism at
a time. The magic may be a product: hysteresis that only matters when the supply sags, noise
that only matters after compression.

**What to build.** `varimu/magic/factorial.py` and `scripts/mechanism_factorial.py --study
NAME` -> `reports/magic/factorial/<study>/`.

A study is a circuit, a program and factors with two levels each. Use only switches that
exist; do not create "ideal" variants of circuits here.

Study `5e3` on `fender_5e3_mods` (guitar, 8 s, `volume_bright` 0.7):

| Factor | Off | On |
|---|---|---|
| sag | `rectifier=3` (silicon) | `rectifier=1` (5Y3GT) |
| iron | `cores="linear"` | `cores="ja"` |
| heaters | `heaters=False` | `heaters=True` |
| noise | `noise=False` | `noise=1` |

Study `tape` on `print_audio` (drums, 8 s, `drive_db` +6):

| Factor | Off | On |
|---|---|---|
| grain | `noise_seed=None` | `noise_seed=1` |
| transport | `flutter=False` | `flutter=True` |

(Add a study per device as its switches allow: `fairchild_670` has `cores` and `noise`.)

**Analysis.** Render all `2^k` combinations (`through_many`). With `y[S]` the output with the
set S of factors on:
- the main effect signal of factor a: the mean over all settings of the others of
  `y[.. a on] - y[.. a off]`;
- the two-factor interaction signal: the mean over the others of
  `y[ab] - y[a] - y[b] + y[none]` (the same shape as SCENE_ANALYSIS.md's interaction
  residual);
- each signal's level in dB re the all-on output, and its tone / character split
  (`difference.decompose` between the two sides);
- **Shapley values** of a scalar score over the factors (exact: all orderings of k factors):
  the score is the character level of `y[S]` against `y[none]`, or AM3's `era_delta` once
  that exists.
- The noise factor's own signal is mostly the noise itself: for interactions with noise
  compare after subtracting a noise-only render where that is defined, and say so.

**Report.** The table of main effects and pairwise interactions; every interaction that is
within 6 dB of the smaller of its two main effects is flagged "not separable": for those
pairs a one-at-a-time ablation gives the wrong answer. Listening candidates: the flagged
pairs above -40 dB re the signal (a screening level chosen here, not a threshold of hearing;
state it as such).

**Tests** `tests/test_magic_factorial.py`: a synthetic system `y = x + a f(x) + b g(x) + a b
h(x)`: the analysis returns `f`, `g`, `h` as the two main effects and the interaction within
-80 dB; the Shapley values sum to the score of the all-on condition.

**Done when** the `5e3` and `tape` studies have tables and the flagged pairs, if any, have
loudness-matched files for the user.

**Cost [estimate].** 16 renders of 9 s of the 5E3 (minutes in parallel); 4 `print_audio` runs
of 8 s (13 minutes).

---

## Order and dependencies

| # | Package | Needs | Needs the user for | Size |
|---|---|---|---|---|
| 1 | AM0 toolkit | nothing | nothing | half a session |
| 2 | AM2 two-pass null | AM0 | nothing | one session |
| 3 | AM7 noise that fuses | AM0 | 20 minutes of listening | one session |
| 4 | AM5 dispersion | AM0, AM1's `crest_by_band` | one ABX | one session |
| 5 | AM1 forensics | AM0 | reference records; what the stems are | one session |
| 6 | AM14 interactions | AM0 | listening only if pairs are flagged | half a session |
| 7 | AM4 generations | AM0, AM1 | listening | one session, 2 hours of renders |
| 8 | AM6 noise-forced levels | AM0 | nothing | one session |
| 9 | AM13 step 1, solo by finite differences | AM0 | hearing a few solos | one session |
| 10 | AM8 breathing room | AM0, AM2's null | one ABX | one session |
| 11 | AM9 instruments listen | AM0 | one comparison | one session |
| 12 | AM11 the player | AM0 | 30 minutes of playing | one session |
| 13 | AM3 era distance | AM1's corpora | corpora; a decision on step 2 | one session |
| 14 | AM10 the floor | step 1 alone first | nothing unless it passes the gate | an hour, then one session |
| 15 | AM13 step 2, the tangent in the engine | AM13 step 1 | a go-ahead (engine work) | several sessions |
| 16 | AM12 the mix as a performance | the Lightfoot mix | listening; a go-ahead for step 2 | half a session |

The order is a recommendation: cheap and decisive first. AM2, AM7 and AM5 each answer one of
the thesis's four bets within a session, and their results say how much the later packages
are worth. The user may pick any order; only the "Needs" column binds.

## Open decisions (the user's)

1. Which records go into `data/reference_records/` (AM1, AM3), and whether a copy of the 1968
   release of *Did She Mention My Name* is available.
2. What the Lightfoot stems are: the original multitrack, a re-recording, or separated from
   the release (AM1's pairing depends on it).
3. AM3 step 2: a learned embedding means the `ml` extra and downloaded weights.
4. AM13 step 2: engine work in circuitsim, with `--verify` owed after it.
5. AM12 step 2: a ride-recording feature in the Session view.
6. AM8 and AM9, if kept: moving them from `varimu/magic/` into the scene format changes
   `varimu/rooms/scene.py` (and recomputes cached room responses).
7. AM2's list "more deterministic than hardware": whether any circuit gets a `noise:` block
   (it moves that circuit's renders).

## Corrections to the brainstorm in the conversation

- The two-pass null of real tape "reportedly -20 to -30 dB": no source was found. AM2 uses a
  derived estimate instead and measures ours.
- "Solo a part costs about one more back-substitution per step": too low; see AM13.
- "The snare buzzing with every bass note" (AM9): snare wires are not built; the package
  gives ringing toms and kick.
- "A capsule responds to its body's acceleration" (AM10): true, but the estimate says the
  effect is far too small for condensers and ribbons, and possibly relevant only for
  moving-coil mics near the kick. The package is gated on that estimate.
- Group delay in the bass (AM5): no controlled audibility threshold below 500 Hz was found;
  the package tests the interaction with saturation, not the delay's audibility alone.

## Sources (searched 2026-11-12, standard mode, one query each)

Found and matching the claim made here (abstract or summary level only; none was read in
full):
- D. J. Hermes, "Synthesis of breathy vowels: Some research methods", *Speech Communication*
  10 (5-6), 497-502, 1991. Stationary aspiration noise is heard as a separate source; noise
  bursts synchronous with the pulses fuse with the vowel.
  https://research.tue.nl/nl/publications/f8136044-8160-4fed-ae1d-4a08cdd83f94
- T. R. Agus, S. J. Thorpe, D. Pressnitzer, "Rapid formation of robust auditory memories:
  insights from noise", *Neuron* 66 (4), 610-618, 2010, doi 10.1016/j.neuron.2010.04.014.
  https://pure.qub.ac.uk/en/publications/rapid-formation-of-robust-auditory-memories-insights-from-noise/
- G. W. Elko, E. Diethorn, T. Gänsler, "Room impulse response variation due to thermal
  fluctuation and its impact on acoustic echo cancellation", Proc. IWAENC 2003: the citation
  confirmed through K. Prawda's 2025 paper (https://arxiv.org/pdf/2501.01206), the paper
  itself not found. Related: Prawda, Schlecht and Välimäki, JASA 2024 (short-time coherence
  between repeated room impulse response measurements); Tatekura, Saruwatari and Shikano,
  EUSIPCO 2002 (compensating temperature by linear time warping).
- F. Esqueda, B. Kuznetsov, J. D. Parker, "Differentiable white-box virtual analog modeling",
  DAFx 2021, pp. 41-48 (component values learned through a differentiable circuit model:
  prior art for gradients through a white-box model, relevant to AM13).
  https://dafx.de/paper-archive/details/BuG_2piIUOi3oZvJGTn48g
- K. Kilgour, M. Zuluaga, D. Roblek, M. Sharifi, "Fréchet Audio Distance: a reference-free
  metric for evaluating music enhancement algorithms", Interspeech 2019, pp. 2350-2354.
  https://arxiv.org/abs/1812.08466
- R. Orban, radio processing paper, 2001: the phase rotator as a chain of all-pass filters
  ("typically four poles, all at 200 Hz"), voice asymmetry up to 6 dB, peak-to-average
  reduced by 3-4 dB. https://totalsonic.net/manuals/Radioprocessing_Bob_Orban_2001.pdf
  Universal Audio's all-pass article (drum peaks lowered about 1.6 dB):
  https://www.uaudio.com/blogs/ua/allpass-filters
- SUNDIALS CVODES, forward sensitivity analysis (simultaneous and staggered correctors):
  https://sundials.readthedocs.io/en/latest/cvodes/Usage/FSA.html . The search did not
  confirm how CVODES reuses the Newton matrix for the sensitivity solves, and found nothing
  on Xyce's transient sensitivities.

Searched and not found:
- A measured two-pass null of a tape machine (AM2).
- A controlled threshold for group delay at 40 Hz. Found: thresholds of 1-3.2 ms from 500 Hz
  to 8 kHz (Blauert and Laws 1978, via summaries); Liski, Mäkivirta and Välimäki (AES 144,
  2018) for loudspeakers; the "two cycles" figure in the bass is an extrapolation.

From memory, not searched: McDermott and Simoncelli (Neuron 2011) on sound texture
statistics; Gui et al. (2024) and the `fadtk` toolkit; McFadden (1987) and Hall, Haggard and
Fernandes (1984) as cited in SCENE_ANALYSIS.md; Lyamshev's reciprocity; McRuer and Jex
(1967); IEC 61672's A-weighting poles; the diaphragm, ribbon and moving-coil masses in AM10.
Not searched at all: prior art for a "solo a part" audio tool, for sympathetic resonance of
drums in a simulated room, and for performance changes caused by amplifier sag. Novelty is
not claimed for any package until a proper search has been made.
