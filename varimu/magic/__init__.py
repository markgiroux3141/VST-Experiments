"""Analog magic (docs/ANALOG_MAGIC_FABLE.md): measurements of where a 1960s record's sound
comes from if not from single devices. AM0's toolkit (`render`, `null`, `listen`) and the
packages built on it. Outside the render cache key (varimu/{sim,circuit,devices} and
config.py): nothing here changes a model."""


def main_root():
    """The main checkout (a worktree's git-ignored files, e.g. reports' WAVs, live there)."""
    import subprocess
    from pathlib import Path

    from varimu.config import REPO_ROOT

    try:
        common = subprocess.run(
            ["git", "rev-parse", "--git-common-dir"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        p = Path(common)
        p = p if p.is_absolute() else (REPO_ROOT / p)
        return p.resolve().parent
    except Exception:
        return REPO_ROOT
