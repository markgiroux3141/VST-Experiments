"""kicad-cli and the XML netlist it exports (`sch export netlist --format kicadxml`).

What the importer relies on (KiCad 10.0.7, measured 2026-10-26): every placed pin is in
exactly one net; a pin with nothing on it is a net of its own named
"unconnected-(REF-PadN)", typed "...+no_connect" when it carries a no-connect flag; an
unplaced unit's pins are in no net; a symbol without pins is still a component; the
fields of a multi-unit symbol's units are merged into one component; a local label's
net is named "/<sheet path>/<label>", a global label's "<label>", unlabeled nets
"Net-(...)".
"""

from __future__ import annotations

import os
import shutil
import subprocess
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

_BUILTIN_FIELDS = {"Footprint", "Datasheet", "Description"}


class KiCadUnavailable(RuntimeError):
    pass


def _version_key(p: Path) -> tuple:
    return tuple(int(x) if x.isdigit() else 0 for x in p.parent.parent.name.split("."))


def find_kicad_cli() -> Path:
    """$VARIMU_KICAD_CLI, then PATH, then the installer's per-user and machine-wide
    folders (the newest version)."""
    env = os.environ.get("VARIMU_KICAD_CLI")
    if env:
        if Path(env).is_file():
            return Path(env)
        raise KiCadUnavailable(f"VARIMU_KICAD_CLI={env} is not a file")
    found = shutil.which("kicad-cli")
    if found:
        return Path(found)
    roots = [
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "KiCad",
        Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "KiCad",
    ]
    exe = "kicad-cli.exe" if os.name == "nt" else "kicad-cli"
    candidates = [p for r in roots if r.is_dir() for p in r.glob(f"*/bin/{exe}")]
    if candidates:
        return max(candidates, key=_version_key)
    raise KiCadUnavailable(
        "kicad-cli not found: install KiCad (https://www.kicad.org/download/) or set "
        "VARIMU_KICAD_CLI to kicad-cli's path"
    )


def export_netlist(schematic: Path, out: Path) -> Path:
    """The schematic's XML netlist, written to `out` by kicad-cli."""
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = [str(find_kicad_cli()), "sch", "export", "netlist", "--format", "kicadxml",
           "-o", str(out), str(schematic)]  # fmt: skip
    r = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if r.returncode != 0 or not out.exists():
        raise RuntimeError(f"kicad-cli failed ({r.returncode}): {r.stderr or r.stdout}")
    return out


@dataclass(frozen=True)
class Component:
    ref: str
    value: str
    part: str  # the library symbol's name
    lib: str
    sheet: str  # the sheet path, e.g. "/power supply/"
    fields: dict[str, str]  # non-empty user fields
    units: dict[str, tuple[str, ...]]  # unit name -> its pin numbers


@dataclass(frozen=True)
class Pin:
    ref: str
    pin: str
    no_connect: bool


@dataclass(frozen=True)
class Net:
    name: str
    pins: tuple[Pin, ...]


@dataclass(frozen=True)
class Netlist:
    source: str
    sheets: tuple[str, ...]  # sheet paths in page order
    components: dict[str, Component]
    nets: tuple[Net, ...]
    title: str = ""
    extra: dict = field(default_factory=dict)


def read_netlist(path: Path) -> Netlist:
    root = ET.parse(path).getroot()
    design = root.find("design")
    sheets = sorted(design.findall("sheet"), key=lambda s: int(s.get("number")))
    comps = {}
    for c in root.find("components"):
        fields = {}
        for f in c.find("fields") if c.find("fields") is not None else ():
            name, text = f.get("name"), (f.text or "").strip()
            if name not in _BUILTIN_FIELDS and text:
                fields[name] = text
        src = c.find("libsource")
        units = {u.get("name"): tuple(p.get("num") for p in u.iter("pin")) for u in c.iter("unit")}
        comps[c.get("ref")] = Component(
            ref=c.get("ref"),
            value=(c.findtext("value") or "").strip(),
            part=src.get("part"),
            lib=src.get("lib"),
            sheet=c.find("sheetpath").get("names"),
            fields=fields,
            units=units,
        )
    nets = tuple(
        Net(
            n.get("name"),
            tuple(
                Pin(x.get("ref"), x.get("pin"), "no_connect" in (x.get("pintype") or ""))
                for x in n.findall("node")
            ),
        )
        for n in root.find("nets")
    )
    title = sheets[0].findtext("title_block/title") or "" if sheets else ""
    return Netlist(
        source=design.findtext("source") or "",
        sheets=tuple(s.get("name") for s in sheets),
        components=comps,
        nets=nets,
        title=title,
    )
