"""Export the Python Nickel voice's output for circuitsim's agreement test
(crates/circuitsim/tests/nickel.rs): A4 and C2 powered on, struck, held, released; noise off.

    uv run python scripts/export_nickel_fixture.py

Writes crates/circuitsim/tests/fixtures/nickel/voice.json (about 0.3 s of audio per case).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from varimu.nickel import organ as norgan  # noqa: E402
from varimu.nickel import spec as nspec  # noqa: E402
from varimu.nickel import voice as nvoice  # noqa: E402

OUT = REPO / "crates" / "circuitsim" / "tests" / "fixtures" / "nickel" / "voice.json"
FS = 96000


def case(note: int, velocity: int, sustain: float, hold_s: float, rel_s: float) -> dict:
    d = nspec.load()
    pol = nspec.v(d, "panel.polarize")
    trim = norgan.voicing([note])[note]["trim"]
    vc = nvoice.make_voice(note, d, noise=False, oversample=2)
    vc.trim = trim
    norgan._power_on(vc, pol)
    vc.strike(velocity)
    y1 = vc.run(int(hold_s * FS), sustain=sustain, polarize=pol)
    vc.release()
    y2 = vc.run(int(rel_s * FS), sustain=sustain, polarize=pol)
    return {
        "note": note, "velocity": velocity, "sustain": sustain, "polarize": pol,
        "hold": [float(x) for x in y1], "release": [float(x) for x in y2],
        "m1": vc.m1, "lamp_k": vc.tl,
    }  # fmt: skip


def main() -> None:
    cases = [case(69, 80, 0.75, 0.15, 0.05), case(36, 100, 0.9, 0.25, 0.05)]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"cases": cases}, separators=(",", ":")))
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
