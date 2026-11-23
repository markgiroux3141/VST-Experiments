"""Pinna-scaled variants of simulated heads (docs/BINAURAL_PLAN.md B5): each head's ears
grown or shrunk about the ear canal point (`variants.scale_pinnae`), simulated on the GPU and
saved as `hutubs_<subj>-pinna<SSS>` (SSS = scale x 100), so binaural_demo.py / _listen.py
play them as heads `<subj>-pinna<SSS>`. Prints each one's front / back contrast.

    uv run --extra fast --extra binaural python scripts/binaural_variants.py \
        [--subjects pp1 pp4 pp5] [--scales 0.8 1.3]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from varimu.binaural.hrtf import cached_head, simulate
from varimu.binaural.mesh import read_ply
from varimu.binaural.variants import front_back_contrast, scale_pinnae

ROOT = Path(__file__).resolve().parents[1]
HUTUBS = ROOT / "data" / "hrtf" / "hutubs"
OUT = ROOT / "reports" / "binaural" / "validate" / "variants.json"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--subjects", nargs="*", default=["pp1", "pp4", "pp5"])
    ap.add_argument("--scales", nargs="*", type=float, default=[0.8, 1.3])
    args = ap.parse_args(argv)
    res = json.loads(OUT.read_text()) if OUT.exists() else {}
    for subj in args.subjects:
        base = cached_head(f"hutubs_{subj}")
        if base is None:
            raise SystemExit(f"{subj}: run scripts/binaural_validate.py --subject {subj} first")
        mesh = read_ply(HUTUBS / "3D head meshes" / f"{subj}_3DheadMesh.ply")
        res[subj] = round(front_back_contrast(base), 2)
        for s in args.scales:
            name = f"{subj}-pinna{round(s * 100):03d}"
            v = scale_pinnae(mesh, base.ears_m, s)
            h = simulate(v, f"hutubs_{name}", ears=base.ears_m)
            res[name] = round(front_back_contrast(h), 2)
            print(f"{name}: front / back contrast {res[name]} dB (base {res[subj]})", flush=True)
            OUT.write_text(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
