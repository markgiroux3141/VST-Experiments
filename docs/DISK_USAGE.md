# Disk usage and cleanup

How to clean the repo's disk use, what is safe to delete and what must stay. Follow the
procedure below step by step. The log at the end records what each cleanup removed.

None of the large folders is tracked by git: `.gitignore` excludes `target/`, `cache/`,
`sessions/` and the generated audio in `reports/`. Deleting them changes nothing in git.

## The user's rules

Set by the user on 2026-11-11:

- **Remove worktrees once they are merged** into main.
- **Keep the caches that speed up generation**: rooms, prerendered chains, and anything
  the current instruments use (tube synth, Rhodes Suitcase, Clavinet, Novachord, Minimoog,
  tape, delay, ...). A cache entry that the current code can't read is not speeding
  anything up, so it goes.
- **Remove what belongs to older versions** of an instrument, such as the Rhodes Stage into
  the 5E3 once the Suitcase replaced it, or a superseded harp or Minimoog. The current
  version's files stay.
- **Remove files of no use**: finished study scratch, old logs, training data for parked
  experiments.
- **`cargo clean` and a full rebuild are fine.**

## Cleanup procedure

Run every step from the repo root.

### 1. Check that nothing is running

A render, the app or a build can hold files open, and deleting under a running render
corrupts it.

```powershell
Get-CimInstance Win32_Process -Filter "Name like 'python%' or Name like 'varimu%' or Name like 'cargo%' or Name like 'rustc%' or Name like 'ngspice%'" | Select-Object ProcessId, CommandLine | Format-List
```

Some processes are harmless: VS Code's language servers (isort, ruff, rust-analyzer), the
`http.server` and the Automated Stream Capture GUI. Anything running `varimu`, a `scripts/`
file, `varimu-app` or ngspice is not. Wait for those to finish, or ask the user.

### 2. Run the census (report only)

```sh
uv run python scripts/cache_census.py --list <scratchpad>/dead.txt
```

It takes about 10 seconds and deletes nothing. It prints the following:

- the sizes of `target/`, `sessions/`, each `cache/` folder and each `reports/` folder
  over 50 MB;
- the worktrees under `.claude/worktrees`, each with its dirty files and its commits not
  in main;
- the dead files by category, with a list of their absolute paths written to `dead.txt`.

The census applies these rules (its docstring has the details):

| Category | Dead when | Why |
| --- | --- | --- |
| `cache/renders/<key>/` | Its `meta.json` code version isn't `runner.code_version()`, or its engine build isn't `circuitsim.SOURCE_HASH` | The render key hashes both, so an older entry can never be hit. Any edit to `varimu/{sim,circuit,devices}` or `config.py` kills every entry. Expect almost all of this cache to be dead each time. `timing.csv` is never listed. |
| `cache/rooms/prints/*`, `cache/rooms/proxies/*` | Older than the newest engine source file | Their keys include `circuitsim.SOURCE_HASH` (`scene._print_key`, `balance._proxy_key`). The engine's sources are `crates/circuitsim/pyproject.toml`'s `cache-keys`. |
| `cache/clavinet/strikes_*.bin` | Older than the newest engine source file | The file name carries a hash of the crate's sources (`clavinet.rs`, `StrikeTable::path`). The app re-records the table in the background on the next Clavinet play anyway. |
| `cache/rooms/proxies_scratch` | Always | Scratch from 2026-11-05 |
| `cache/jobs/*` | Always, while no render runs | Scratch folders of interrupted renders. A finished render removes its own. |
| `cache/*.log` | Always | Logs of runs whose results went to reports and docs |

### 3. Remove merged worktrees

Remove a worktree only when the census shows **0 dirty files and 0 commits not in main**.
Otherwise ask the user.

```sh
git worktree remove .claude/worktrees/NAME
git branch -d worktree-NAME        # -d (not -D): it refuses an unmerged branch
```

**First, copy the worktree's own `cache/sources/` (and any other downloaded source files
in its git-ignored folders) into main's `cache/`.** A merge brings over only tracked
files. On 2026-11-11, the Minimoog's manual scans existed only in the worktree's
`cache/sources/minimoog/` and were lost with it. Seven were downloaded again from the URLs
in `data/schematics/minimoog/README.md`. Three others (906, 912, 916) weren't named there.
Check with:

```sh
ls .claude/worktrees/NAME/cache/sources .claude/worktrees/NAME/cache/dl_* 2>/dev/null
```

Then remove the worktree. Its other caches (renders, prints, `target/`) are dead: they were
made by its own code.

Delete anything left in `.claude/worktrees/` (sync logs). Remove the folder once it is
empty.

### 4. Delete the census's dead list

```powershell
Get-Content <scratchpad>\dead.txt | ForEach-Object { Remove-Item -LiteralPath $_ -Recurse -Force }
```

Delete only by **absolute paths**. Claude Code's safety check refuses an `rm -rf` whose
target it can't resolve, such as a relative glob after `cd` (`cd cache && rm -rf jobs/*`
was refused). Never try to get around that check. Write the paths out instead. The folders
the code needs, `cache/jobs` and `cache/tables`, are recreated on demand
(`runner.py` and `devices/table.py` `mkdir` them).

Afterwards, run the census again: every category should show 0.

### 5. Judgment calls: look, then decide

The census can't decide these. Look at dates and contents, and compare them with
CLAUDE.md's current state of each instrument.

**In `reports/`, delete only untracked files.** Plots, `summary.json` and `results.json`
are tracked: they are the study's record. Only the audio and renders are ignored, so delete
those file by file (`*.wav`, `*.npy`), never a whole folder. List what git tracks first with
`git ls-files reports/<folder>`. Then check that `git status` shows no `D` lines after
deleting. On 2026-11-11, `rm -rf reports/tape/chunks` deleted the seam study's plot and
`results.json`, and `git checkout -- reports/tape/chunks` restored them.

| What | Rule | Example (2026-11-11) |
| --- | --- | --- |
| `cache/tables` (ngspice triode tables) | Delete all. They are rebuilt in seconds. | 0.7 GB |
| `cache/spike/neural_core/data` | Training data of a parked spike: delete it. Keep `runs/` (weights and plots, 1 MB). | 0.8 GB |
| Study scratch in `cache/` and `reports/` | Delete once the study is written up in its plan, for example `cache/tape/{chunks,speed*}`, `reports/tape/chunks` (TAPE_SPEED_PLAN.md P3). Keep alignment JSONs (KBs). | 0.4 GB |
| Older instrument versions in `reports/` | Delete audio that a newer version of the same instrument replaced: renders on a superseded component version, or prints from before a model change. Keep what the user still listens to or compares against. | `reports/rhodes/renders/demo*` (Stage + 5E3 on MK1_HARP@1); `reports/tape/audio/` from before the 351 or TM3 |
| `reports/rooms` | **Keep**, unless the user says they are done listening. It holds listening material (`separation/` is the pending R5 staircase) and takes hours to rebuild. | 3.4 GB |
| Comparison audio against references | Keep it while it compares against the current version, for example `reports/rhodes/jrhodes` (MK1_HARP@2). | 0.2 GB |
| Old component versions (`config/components/<name>/<N>.*`) | **Keep.** They are tracked in git and in `versions.lock`, circuits and scripts may pin them, and deleting them frees no git space. | D6_STRINGS@1-2, MK1_HARP@1 |
| `cache/dl_*`, `cache/sources`, `cache/scratch` | Keep. They are downloaded source documents and model cards behind fits (~0.2 GB) and may be hard to download again. | |
| `cache/separation`, `cache/novachord`, `cache/delay`, `cache/rooms/responses`, `cache/diffraction`, `cache/clavinet/fits_*`, `cache/rhodes`, `cache/tape/align_*`, `cache/app_renders` | Keep. These are current, small, slow-to-rebuild caches. | |
| `sessions/` | **Never** delete without the user. These are recorded takes and mixes. The scratch sessions (`saw test`, `test room`, `mmx`, `hip hop test`, numbered `Session N`) are the user's call. | 7.5 GB |
| `tools/`, `data/`, `samples/`, `stems/`, `real instrument samples/`, `.git`, `.venv` | Keep. These are the reference engine, source material and the installed environment. | |

When an old instrument version has its own files in `cache/` (the Minimoog worktrees did),
handle them like step 3's worktrees: check they are merged or superseded, then delete them.

### 6. `cargo clean` and rebuild

`target/` grows back to tens of GB within weeks: incremental compile state, plus one output
per feature combination and dependency version, which Cargo never collects. A clean rebuild
brings it to about **15 GB** (14 GB debug, 1.5 GB release).

```sh
cd "<repo root>"                         # never from inside target/: see below
cargo clean                               # rerun if it reports "os error 32"
cargo build --release --workspace
cargo build --release --workspace --examples
cargo test --workspace --no-run           # every test built in debug, none run
```

The rebuild took about 5 minutes on 2026-11-11 (release about 3 minutes). Run it in the
background.

Gotchas:

- **"The process cannot access the file" (os error 32).** On 2026-11-11, `cargo clean`
  failed twice and left 20 GB behind. The likely cause was the Bash tool's working folder
  sitting inside `target/debug/deps` from an earlier step. `cd` back to the root and run
  `cargo clean` again until `target/` is gone (`ls target` fails). Also check step 1's
  processes: rust-analyzer and a running `varimu-app.exe` lock files too.
- If `ls target` still lists folders, the clean did not finish. Don't start the rebuild
  then: it reuses what survived and the size barely drops.
- The Python `circuitsim` in `.venv` is separate from `target/` and keeps working
  throughout. `uv sync --extra fast` builds it in its own folders.

### 7. Measure and log

Measure per folder: the census prints the sizes first (`--no-sizes` skips them), or use
PowerShell. A single `du` over the whole repo can take more than 2 minutes
and time out: run it in the background, or measure only the big folders.

```powershell
Get-ChildItem cache, reports -Directory | ForEach-Object { '{0,8:N0} MB {1}' -f ((Get-ChildItem $_.FullName -Recurse -File -EA SilentlyContinue | Measure-Object Length -Sum).Sum/1MB), $_.FullName }
```

Add an entry to the log below: the date, the size before and after, and what was removed
and what was kept, with the reasons.

## Cleanup log

### 2026-11-11: 132 GB -> about 32 GB

- **Worktrees:** `minimoog` and `minimoog-rt` (6.5 GB, 5.2 GB of it their own `target/`)
  and their branches are gone. Both were clean and fully merged. The other local branches
  (`master-insert`, `sidechain`, `tape-*`, `victorian`, `varimu-phase-0-1`) are fully
  merged but take no space, so they were left. The worktree's `cache/sources/minimoog/`
  scans were lost with it. Seven were downloaded again into main's `cache/sources/minimoog/`
  (step 3's note).
- **`cache/renders`:** all 6,466 entries (43 GB) are gone. None matched code version
  `0.1.0+e4107e029d79`. Their versions spanned 65 older ones.
- **`cache/rooms`:** 400 of 443 prints and the older proxies (6.6 GB) are gone. They were
  made before the engine change of 2026-11-11 02:52. Kept: 43 prints, `responses/`,
  `step_rates.json`.
- **`cache/clavinet`:** the three strike tables (0.63 GB) had older code hashes and are
  gone. Kept: fits, levels, `listen/`.
- **Also gone from `cache/`:** `cache/jobs` (0.7 GB, Oct 23-24), `cache/tables` (0.7 GB),
  `cache/spike/neural_core/data` (0.8 GB), `cache/tape/{chunks,speed,speed_heads12um}`
  (0.15 GB), `lit351_out.npy`, 27 run logs.
- **`reports/`:** gone are `rhodes/renders/demo*` (the Stage into the 5E3 on MK1_HARP@1),
  the audio of `tape/chunks` (the P3 seam study; its tracked plot and results.json were
  restored) and the `tape/audio/` prints from before the 351 or TM3
  (`before_tm3/`, `351_no_transport/`, `351_heads12um_no_noise/`, the Oct 31 WAVs).
- **`target/`:** `cargo clean` and a rebuild took it from 58 GB to 15 GB.
- **Kept on purpose:** `sessions/` (7.5 GB), all of `reports/rooms` (3.4 GB), the jRhodes
  comparison, the old component versions.

After the cleanup the biggest folders were `target/` 15 GB, `sessions/` 7.5 GB,
`reports/rooms` 3.4 GB, `tools/` 1 GB, and data / samples / stems 1.4 GB. Everything else
was under 0.5 GB each.
