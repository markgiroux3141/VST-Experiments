"""What on disk is dead, regenerable or worth keeping: the census behind docs/DISK_USAGE.md.

Report only: it deletes nothing. It prints the sizes, then each category of dead files with
why it is dead, and with ``--list FILE`` writes every dead path (absolute, one per line) so
the cleanup can delete exactly those (docs/DISK_USAGE.md, "Cleanup procedure").

    uv run python scripts/cache_census.py [--list dead.txt] [--no-sizes]

Dead means no current code can read it again:
- a render in cache/renders whose meta's code version (``runner.code_version()``) or engine
  build (``circuitsim.SOURCE_HASH``) isn't the current one;
- a room print or proxy (cache/rooms/{prints,proxies}) or a Clavinet strike table
  (cache/clavinet/strikes_*.bin) older than the newest circuitsim source file: all three
  are keyed on the engine's source hash, which changes with any of those files (the
  ``cache-keys`` of crates/circuitsim/pyproject.toml);
- cache/jobs (render scratch folders: a finished render removes its own) and the run logs
  at cache/'s top level.
Worktrees under .claude/worktrees are listed with their dirty files and unmerged commits;
removing them is a git step, never part of the list.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CACHE = REPO / "cache"
GB = 1024**3

# The engine's sources: crates/circuitsim/pyproject.toml's cache-keys (SOURCE_HASH).
ENGINE_SOURCES = [
    ("crates/circuitsim", "pyproject.toml"),
    ("crates/circuitsim", "Cargo.toml"),
    ("crates/circuitsim", "build.rs"),
    (".", "Cargo.toml"),
    ("crates/circuitsim/src", "**/*.rs"),
    ("crates/tapegpu", "Cargo.toml"),
    ("crates/tapegpu/src", "**/*.rs"),
    ("crates/tapegpu/src", "**/*.wgsl"),
]


def size(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    total = 0
    for p in path.rglob("*"):
        try:
            if p.is_file():
                total += p.stat().st_size
        except OSError:
            pass
    return total


def engine_stamp() -> float:
    """The newest modification time among the engine's source files."""
    newest = 0.0
    for base, pattern in ENGINE_SOURCES:
        for p in (REPO / base).glob(pattern):
            if p.is_file():
                newest = max(newest, p.stat().st_mtime)
    return newest


def find_key(obj, key: str):
    if isinstance(obj, dict):
        if isinstance(obj.get(key), str):
            return obj[key]
        for v in obj.values():
            found = find_key(v, key)
            if found:
                return found
    return None


def dead_renders() -> list[Path]:
    from varimu.sim.runner import code_version

    code = code_version()
    try:
        import circuitsim

        build = circuitsim.SOURCE_HASH
    except ImportError:
        build = None
    print(f"current code version {code}, engine build {build}")
    dead = []
    root = CACHE / "renders"
    if not root.exists():
        return dead
    for d in root.iterdir():
        if not d.is_dir():
            continue
        try:
            meta = json.loads((d / "meta.json").read_text())
        except (OSError, ValueError):
            dead.append(d)
            continue
        eb = find_key(meta, "engine_build")
        if find_key(meta, "code") != code or (build and eb and eb != build):
            dead.append(d)
    return dead


def older_than(paths, stamp: float) -> list[Path]:
    return [p for p in paths if p.stat().st_mtime < stamp]


def worktrees() -> None:
    out = subprocess.run(
        ["git", "worktree", "list", "--porcelain"], cwd=REPO, capture_output=True, text=True
    ).stdout
    entries = [b for b in out.strip().split("\n\n") if b]
    for block in entries[1:]:
        lines = dict(line.split(" ", 1) for line in block.splitlines() if " " in line)
        path, branch = lines.get("worktree"), lines.get("branch", "").removeprefix("refs/heads/")
        dirty = subprocess.run(
            ["git", "-C", path, "status", "--porcelain"], capture_output=True, text=True
        ).stdout.strip()
        ahead = subprocess.run(
            ["git", "rev-list", "--count", f"main..{branch}"],
            cwd=REPO,
            capture_output=True,
            text=True,
        ).stdout.strip()
        n_dirty = len(dirty.splitlines()) if dirty else 0
        verdict = "merged and clean: remove" if n_dirty == 0 and ahead == "0" else "KEEP / ask"
        print(f"  {path} [{branch}]: {n_dirty} dirty, {ahead} not in main -> {verdict}")
    if len(entries) <= 1:
        print("  none besides main")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--list", type=Path, help="write every dead path here, one per line")
    ap.add_argument("--no-sizes", action="store_true", help="skip the folder sizes (slow)")
    args = ap.parse_args()

    if not args.no_sizes:
        print("sizes (GB):")
        tops = [REPO / "target", REPO / "sessions", REPO / ".claude" / "worktrees"]
        tops += sorted(p for p in CACHE.iterdir() if p.is_dir()) if CACHE.exists() else []
        tops += sorted(p for p in (REPO / "reports").iterdir() if p.is_dir())
        for p in tops:
            if p.exists():
                s = size(p)
                if s > 50 * 1024**2:
                    print(f"  {s / GB:7.2f}  {p.relative_to(REPO).as_posix()}")

    print("worktrees:")
    worktrees()

    stamp = engine_stamp()
    rooms = CACHE / "rooms"
    categories = {
        "cache/renders (old code or engine)": dead_renders(),
        "cache/rooms prints and proxies (older engine)": older_than(
            [p for sub in ("prints", "proxies") for p in (rooms / sub).glob("*")], stamp
        ),
        "cache/rooms/proxies_scratch": [rooms / "proxies_scratch"]
        if (rooms / "proxies_scratch").exists()
        else [],
        "cache/clavinet strike tables (older engine)": older_than(
            list((CACHE / "clavinet").glob("strikes_*.bin")), stamp
        ),
        "cache/jobs (render scratch)": list((CACHE / "jobs").glob("*")),
        "cache/*.log (old run logs)": list(CACHE.glob("*.log")),
    }
    dead = []
    print("dead:")
    for name, paths in categories.items():
        total = sum(size(p) for p in paths)
        print(f"  {total / GB:7.2f} GB  {len(paths):5d}  {name}")
        dead += paths
    print(f"  {sum(size(p) for p in dead) / GB:7.2f} GB in all")
    if args.list:
        args.list.write_text("".join(f"{p.resolve()}\n" for p in dead), encoding="utf-8")
        print(f"wrote {len(dead)} paths to {args.list}")


if __name__ == "__main__":
    main()
