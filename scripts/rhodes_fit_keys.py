"""Fit the Rhodes's 73 keys (varimu/rhodes/spec.py) in parallel into the disk cache
(cache/rhodes/keys_*), so the studies and renders start at once.

    uv run python scripts/rhodes_fit_keys.py [--workers 6] [--keys 8 9 ...]
"""

from __future__ import annotations

import argparse
import os
import time
from concurrent.futures import ProcessPoolExecutor

from varimu.rhodes import spec


def _fit(n: int) -> tuple[int, float, float]:
    t = time.time()
    k = spec.key(n)
    return n, k.fits["fundamental_hz"] / k.note_hz, time.time() - t


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 2))
    ap.add_argument("--keys", type=int, nargs="+", default=list(spec.KEYS_73))
    args = ap.parse_args()
    os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
    t0 = time.time()
    with ProcessPoolExecutor(args.workers) as pool:
        for n, ratio, dt in pool.map(_fit, sorted(args.keys, key=lambda n: n)):
            print(f"key {n:2d}: f/note {ratio:.6f} ({dt:.0f} s)", flush=True)
    print(f"done in {time.time() - t0:.0f} s")


if __name__ == "__main__":
    main()
