"""The heads a scene's `head` mic may name (docs/BINAURAL_PLAN.md B7), loaded by name.

- `sphere`: the analytic rigid sphere (no pinnae; the control);
- `ppN`: HUTUBS subject N's head, simulated from its mesh (data/hrtf/hutubs);
- `ppN-pinnaSSS`: that head with its pinnae scaled by SSS / 100 about the ear canal points
  (varimu.binaural.variants.scale_pinnae), the base head's ears;
- `ppN_measured`: subject N's measured HRTFs (a SOFA file; far field only).

A simulated head comes from cache/binaural/heads/ (hrtf.cached_head), or is simulated on the
GPU the first time (~2 minutes; a pinna variant simulates its base first when that isn't
cached). `DEFAULT` is the user's pick of 2026-11-22: pp4 with its ears 1.3x.

`digest(head)` identifies a head's data for the room responses' cache key.
"""

from __future__ import annotations

import functools
import hashlib
import re
from pathlib import Path

import numpy as np

from varimu.config import REPO_ROOT

HUTUBS = REPO_ROOT / "data" / "hrtf" / "hutubs"
DEFAULT = "pp4-pinna130"
_NAME = re.compile(r"(pp\d+)(?:-pinna(\d{3}))?(_measured)?")


def _mesh_path(subj: str) -> Path:
    return HUTUBS / "3D head meshes" / f"{subj}_3DheadMesh.ply"


@functools.lru_cache(maxsize=8)
def load(name: str, log=print):
    """The head called `name` (the module docstring)."""
    from varimu.binaural.hrtf import cached_head, simulate
    from varimu.binaural.mesh import read_ply
    from varimu.binaural.render import SofaHead, SphereHead

    if name == "sphere":
        return SphereHead()
    m = _NAME.fullmatch(name)
    if m is None:
        raise ValueError(f"head {name!r}: sphere, ppN, ppN-pinnaSSS or ppN_measured")
    subj, pinna, measured = m.groups()
    if measured:
        if pinna:
            raise ValueError(f"head {name!r}: a measured head has no pinna variants")
        return SofaHead(HUTUBS / "HRIRs" / f"{subj}_HRIRs_measured.sofa", name)
    h = cached_head(f"hutubs_{name}")
    if h is not None:
        return h
    if not _mesh_path(subj).exists():
        raise ValueError(f"head {name!r}: no mesh {_mesh_path(subj)} (data/hrtf/hutubs/README.md)")
    mesh = read_ply(_mesh_path(subj))
    if log:
        log(f"head {name}: not simulated yet, simulating on the GPU (about 2 minutes)")
    if pinna is None:
        return simulate(mesh, f"hutubs_{subj}", log=log)
    from varimu.binaural.variants import scale_pinnae

    base = load(subj, log)
    v = scale_pinnae(mesh, base.ears_m, int(pinna) / 100)
    return simulate(v, f"hutubs_{name}", ears=base.ears_m, log=log)


def digest(head) -> str:
    """A hash of the head's data (its HRTFs, or the sphere's radius); kept on the head."""
    if "_digest" in vars(head):
        return vars(head)["_digest"]
    h = hashlib.sha256(type(head).__name__.encode())
    if hasattr(head, "left"):  # simulated: the SH fields
        for f in (head.left, head.right, head.ref):
            h.update(np.ascontiguousarray(f.coeffs).tobytes())
            h.update(np.ascontiguousarray(f.f_hz).tobytes())
    elif hasattr(head, "s"):  # measured
        h.update(np.ascontiguousarray(head.s.ir).tobytes())
    else:  # the sphere
        h.update(repr(head.radius_m).encode())
        h.update(np.ascontiguousarray(head.f_hz).tobytes())
    vars(head)["_digest"] = h.hexdigest()[:24]
    return vars(head)["_digest"]
