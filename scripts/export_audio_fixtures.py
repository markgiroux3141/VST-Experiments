"""Write the native app's resampling fixtures (docs/NATIVE_APP_PLAN.md, R2).

    uv run python scripts/export_audio_fixtures.py

scipy's `resample_poly` (the reference: varimu.sim.io loads files, oversamples renders
and brings draft-1x to its host rate with it) on short seeded inputs, for every ratio
and padding the project uses, with the filter taps it designs.
crates/varimu-app/tests/resample.rs ports it and compares bit for bit, which a Rust
render equal to a Python render needs. tests/test_audio_fixtures.py fails when the
fixtures are stale (another scipy).
"""

from __future__ import annotations

import json
from math import gcd
from typing import Any

import numpy as np
import scipy
from scipy.signal import firwin, resample_poly

from varimu.config import REPO_ROOT

FIXTURE = REPO_ROOT / "crates" / "varimu-app" / "tests" / "fixtures" / "resample.json"

# (up, down, padtype): render oversampling (2, 1, constant) and decimation (1, 2, edge);
# draft-1x's 96 -> 48 kHz and back (edge); file loads at 44.1 and 48 kHz (constant); a
# 44.1 kHz device (edge); ratios that aren't reduced.
CASES = [
    (2, 1, "constant"),
    (1, 2, "edge"),
    (2, 1, "edge"),
    (320, 147, "constant"),
    (147, 320, "edge"),
    (160, 147, "edge"),
    (4, 2, "edge"),
    (3, 1, "constant"),
]
LENGTHS = (300, 7)  # the second is shorter than a filter phase: upfirdn's flush loop


def case(up: int, down: int, pad: str, n: int, seed: int) -> dict[str, Any]:
    rng = np.random.default_rng([seed, up, down, n])
    x = rng.standard_normal(n) + (0.5 if pad == "edge" else 0.0)
    y = resample_poly(x, up, down, padtype=pad)
    return {"up": up, "down": down, "pad": pad, "x": x.tolist(), "y": y.tolist()}


def taps(m: int) -> dict[str, Any]:
    """resample_poly's filter for max(up, down) = m (reduced), before its scaling by up."""
    h = firwin(2 * 10 * m + 1, 1.0 / m, window=("kaiser", 5.0))
    return {"max_rate": m, "h": h.tolist()}


def fixture_json() -> str:
    cases = [case(u, d, p, n, i) for i, (u, d, p) in enumerate(CASES) for n in LENGTHS]
    rates = sorted({max(u, d) // gcd(u, d) for u, d, _ in CASES})
    data = {
        "scipy": scipy.__version__,
        "numpy": np.__version__,
        "taps": [taps(m) for m in rates],
        "cases": cases,
    }
    return json.dumps(data, indent=None, separators=(",", ":")) + "\n"


def main() -> None:
    FIXTURE.parent.mkdir(parents=True, exist_ok=True)
    text = fixture_json()
    FIXTURE.write_text(text, encoding="utf-8", newline="\n")
    print(f"{FIXTURE.relative_to(REPO_ROOT)}: {len(text) / 1000:.0f} kB")


if __name__ == "__main__":
    main()
