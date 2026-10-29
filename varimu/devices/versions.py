"""Component versions: `config/components/<name>/<N>.yaml`, never changed once saved.

A component (a tube, a rectifier, later a transformer or a speaker) is a folder of
numbered versions (docs/COMPONENT_EDITOR_PLAN.md, C1). A version is immutable: the
sha256 of its text (line ends normalized to LF, so a CRLF checkout hashes the same) is
recorded in `config/components/versions.lock` when it is saved, and reading a version
whose text no longer matches is an error that names it. Changing a component means
saving its next version (`save`); `varimu fit-devices` does that when a refit changes
a model.

References are `NAME@N` (`12AX7@1`). Circuits must name the version they use
(`require_pinned`, called by the circuit builder), so a new version never changes an
existing circuit; moving a circuit to it is an explicit edit. Tools and tests may name
a component alone (`12AX7`), which is its latest version. Names are case-insensitive:
the folder is the lowercased name.

The Rust side reads the same layout (`varimu-circuit`'s `versions.rs`).
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

from varimu.config import CONFIG_DIR

COMPONENT_DIR = CONFIG_DIR / "components"
LOCK_NAME = "versions.lock"

_REF = re.compile(r"^([^@\s]+)(?:@([1-9][0-9]*))?$")
_VERSION_FILE = re.compile(r"^([1-9][0-9]*)\.yaml$")

_LOCK_HEADER = (
    "# The sha256 of every saved component version (config/components/<name>/<N>.yaml),\n"
    "# its text with LF line ends. A version never changes once saved: save the next one\n"
    "# instead (varimu.devices.versions, docs/COMPONENT_EDITOR_PLAN.md C1).\n"
)


class VersionError(ValueError):
    """A component reference that can't be resolved, or a version edited after saving."""


@dataclass(frozen=True)
class Ref:
    name: str
    version: int | None  # None: the latest version

    def __str__(self) -> str:
        return self.name if self.version is None else f"{self.name}@{self.version}"

    @property
    def folder(self) -> str:
        return self.name.lower()


def parse(ref: str) -> Ref:
    m = _REF.match(str(ref).strip())
    if not m:
        raise VersionError(f"{ref!r} is not a component reference (NAME or NAME@N, N >= 1)")
    return Ref(m.group(1), int(m.group(2)) if m.group(2) else None)


def text_hash(text: str) -> str:
    return hashlib.sha256(text.replace("\r\n", "\n").encode("utf-8")).hexdigest()


def versions(name: str, root: Path = COMPONENT_DIR) -> list[int]:
    """The saved versions of component `name`, ascending (empty when there is none)."""
    folder = root / name.lower()
    if not folder.is_dir():
        return []
    found = (_VERSION_FILE.match(p.name) for p in folder.iterdir())
    return sorted(int(m.group(1)) for m in found if m)


def names(root: Path = COMPONENT_DIR) -> list[str]:
    """Every component's folder name, sorted."""
    if not root.is_dir():
        return []
    return sorted(p.name for p in root.iterdir() if p.is_dir() and versions(p.name, root))


def resolve(ref: str | Ref, root: Path = COMPONENT_DIR) -> Ref:
    """`ref` with its version filled in (the latest when it names none)."""
    r = ref if isinstance(ref, Ref) else parse(ref)
    have = versions(r.name, root)
    if not have:
        raise VersionError(f"no component {r.name!r} in {root} (run `uv run varimu fit-devices`)")
    if r.version is None:
        return Ref(r.name, have[-1])
    if r.version not in have:
        raise VersionError(f"{r} doesn't exist: {r.name} has versions {have}")
    return r


def require_pinned(ref: str) -> Ref:
    """`ref` parsed, refused when it names no version (what a circuit must do)."""
    r = parse(ref)
    if r.version is None:
        try:
            hint = f", e.g. {resolve(r)}"
        except VersionError:
            hint = ""
        raise VersionError(f"{ref!r} names no version: a circuit pins one{hint}")
    return r


def path(ref: str | Ref, root: Path = COMPONENT_DIR) -> Path:
    r = resolve(ref, root)
    return root / r.folder / f"{r.version}.yaml"


def read_lock(root: Path = COMPONENT_DIR) -> dict[str, dict[int, str]]:
    """{folder: {version: sha256}} from versions.lock (empty when there is none)."""
    lock = root / LOCK_NAME
    out: dict[str, dict[int, str]] = {}
    if not lock.exists():
        return out
    current = None
    for n, line in enumerate(lock.read_text(encoding="utf-8").splitlines(), 1):
        text = line.split("#", 1)[0].rstrip()
        if not text:
            continue
        if not text.startswith(" "):
            if not text.endswith(":"):
                raise VersionError(f"{lock}:{n}: expected '<name>:'")
            current = text[:-1].strip()
            out[current] = {}
            continue
        key, _, value = text.strip().partition(":")
        if current is None or not key.isdigit() or not re.fullmatch(r"[0-9a-f]{64}", value.strip()):
            raise VersionError(f"{lock}:{n}: expected '  <version>: <sha256>'")
        out[current][int(key)] = value.strip()
    return out


def write_lock(lock: dict[str, dict[int, str]], root: Path = COMPONENT_DIR) -> None:
    lines = [_LOCK_HEADER.rstrip("\n")]
    for folder in sorted(lock):
        lines.append(f"{folder}:")
        lines += [f"  {v}: {lock[folder][v]}" for v in sorted(lock[folder])]
    (root / LOCK_NAME).write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def read_text(ref: str | Ref, root: Path = COMPONENT_DIR) -> tuple[Ref, str]:
    """A version's text, checked against versions.lock."""
    r = resolve(ref, root)
    p = root / r.folder / f"{r.version}.yaml"
    text = p.read_text(encoding="utf-8")
    want = read_lock(root).get(r.folder, {}).get(r.version)
    if want is None:
        raise VersionError(f"{r} ({p}) isn't in {LOCK_NAME}: versions are saved with `save`")
    if text_hash(text) != want:
        raise VersionError(
            f"{r} ({p}) was edited after it was saved (its sha256 no longer matches "
            f"{LOCK_NAME}); restore it and save the change as a new version"
        )
    return r, text


def save(name: str, text: str, root: Path = COMPONENT_DIR) -> Ref:
    """Save `text` as component `name`'s next version and record it in versions.lock."""
    r = parse(name)
    if r.version is not None:
        raise VersionError(f"save takes a component name, not a version ({name!r})")
    n = (versions(r.name, root) or [0])[-1] + 1
    folder = root / r.folder
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{n}.yaml").write_text(text, encoding="utf-8", newline="\n")
    lock = read_lock(root)
    lock.setdefault(r.folder, {})[n] = text_hash(text)
    write_lock(lock, root)
    return Ref(r.name, n)
