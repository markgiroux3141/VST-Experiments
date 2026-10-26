"""KiCad fixtures of the device builder (B3): the symbol library, the EQP-1A as a
generated (label-connected) KiCad project, a deliberately broken copy of it, and
their XML netlists for the tests (which then run without KiCad).

    uv run python scripts/make_kicad_fixtures.py

Writes kicad/varimu.kicad_sym, kicad/generated/pultec_eqp1a[_broken]/ and
tests/fixtures/kicad/*.xml (kicad-cli's netlists, with the source path and date made
stable). The broken drawing has four faults, one per check:

- CPCCA left out: the 6X4 plate node rka, fed by the PCC-55's leakage, has no
  capacitor (rectifier);
- RBIAS_B's ground pin left unconnected (unconnected, also at the netlist);
- RG2A left out: V2A's grid has no DC path (floating);
- LBAD, an inductor across LPCCA: a loop of inductors (loop).
"""

from __future__ import annotations

import copy
import dataclasses
import re
from pathlib import Path

from varimu.circuit.spec import circuit_path, load_circuit
from varimu.config import REPO_ROOT
from varimu.kicad.export import export_spec
from varimu.kicad.netlist import export_netlist
from varimu.kicad.symbols import write_library

KICAD = REPO_ROOT / "kicad"
FIXTURES = REPO_ROOT / "tests" / "fixtures" / "kicad"
LIB_URI = "${KIPRJMOD}/../../varimu.kicad_sym"


def broken(spec):
    """The EQP-1A with the four faults (see the module docstring)."""
    sections = copy.deepcopy(list(spec.sections))
    parts = {k: v for s in sections for k, v in s["parts"].items()}
    by_name = {k: s for s in sections for k in s["parts"]}
    del by_name["CPCCA"]["parts"]["CPCCA"]
    del by_name["RG2A"]["parts"]["RG2A"]
    parts["RBIAS_B"]["R"] = [parts["RBIAS_B"]["R"][0], ""]
    by_name["LPCCA"]["parts"]["LBAD"] = {"L": ["hva_r", "rka"], "l": "pcc55_leakage_h"}
    tol = copy.deepcopy(spec.parts)
    tol["classes"] = {c: [d for d in ds if d != "RG2A"] for c, ds in tol["classes"].items()}
    return dataclasses.replace(spec, sections=tuple(sections), parts=tol)


def netlist_fixture(project_dir: Path, project: str) -> Path:
    out = FIXTURES / f"{project}.xml"
    export_netlist(project_dir / f"{project}.kicad_sch", out)
    text = out.read_text(encoding="utf-8")
    rel = (project_dir / f"{project}.kicad_sch").relative_to(REPO_ROOT).as_posix()
    text = re.sub(r"<source>.*?</source>", f"<source>{rel}</source>", text, count=1)
    text = re.sub(r"<date>.*?</date>", "<date>(fixture)</date>", text, count=1)
    out.write_text(text, encoding="utf-8", newline="\n")
    return out


def main() -> None:
    print(write_library(KICAD / "varimu.kicad_sym"))
    spec = load_circuit(circuit_path("pultec_eqp1a"))
    for project, s in (("pultec_eqp1a", spec), ("pultec_eqp1a_broken", broken(spec))):
        d = KICAD / "generated" / project
        files = export_spec(s, d, project, LIB_URI)
        print(f"{d}: {len(files)} files; netlist {netlist_fixture(d, project)}")


if __name__ == "__main__":
    main()
