"""Minimal ngspice batch interface.

Enough for the device-agreement tests. The parallel, cached runner is Phase 4.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import numpy as np

from varimu.config import REPO_ROOT


class SimulatorNotFound(RuntimeError):
    pass


class SimulationFailed(RuntimeError):
    pass


def find_ngspice() -> Path:
    """$VARIMU_NGSPICE, then the portable copy under tools/, then PATH."""
    env = os.environ.get("VARIMU_NGSPICE")
    if env and Path(env).exists():
        return Path(env)
    for pattern in ("tools/ngspice-*/Spice64/bin/ngspice_con.exe", "tools/ngspice-*/bin/ngspice"):
        hits = sorted(REPO_ROOT.glob(pattern))
        if hits:
            return hits[-1]
    for name in ("ngspice_con", "ngspice"):
        found = shutil.which(name)
        if found:
            return Path(found)
    raise SimulatorNotFound("ngspice not found: set VARIMU_NGSPICE, or install it under tools/")


def run(
    netlist: str, analysis: str, vectors: list[str], *, options: str = "", timeout: float = 120.0
) -> dict[str, np.ndarray]:
    """Run one analysis (e.g. "dc vp 0 400 1") in batch mode and return the requested vectors.

    `options` is inserted as a `.options` line, e.g. "reltol=1e-9".
    The result maps each name in `vectors` to an array, with the sweep or time
    axis under "scale". For AC analyses the values are complex.
    """
    exe = find_ngspice()
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        out = td / "out.txt"
        cir = td / "in.cir"
        cir.write_text(
            f"* varimu\n{netlist}\n.control\nset wr_singlescale\nset wr_vecnames\n"
            f"set filetype=ascii\n{analysis}\nwrdata {out.as_posix()} {' '.join(vectors)}\n"
            f"quit\n.endc\n.end\n",
            encoding="utf-8",
        )
        proc = subprocess.run(
            [str(exe), "-b", str(cir)], capture_output=True, text=True, timeout=timeout, cwd=td
        )
        if not out.exists():
            raise SimulationFailed(
                f"ngspice produced no output:\n{proc.stdout[-3000:]}\n{proc.stderr[-3000:]}"
            )
        lines = out.read_text().splitlines()
    header = lines[0].split()
    arr = np.loadtxt(lines[1:], ndmin=2)
    cols = {name.lower(): arr[:, k] for k, name in enumerate(header)}
    result = {"scale": arr[:, 0]}
    complex_out = analysis.strip().lower().startswith("ac")
    for v in vectors:
        key = v.lower()
        if complex_out:
            # wrdata writes complex vectors as two columns (re, im); the header names the first.
            k = header.index(next(h for h in header if h.lower() == key))
            result[v] = arr[:, k] + 1j * arr[:, k + 1]
        else:
            result[v] = cols[key]
    return result
