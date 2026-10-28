"""The teacher: every signal through the bench with the Jiles-Atherton core, in parallel.

Saves cache/spike/neural_core/data/{train,test}.npz: the items' names and metadata (JSON),
their lengths, and the concatenated sequences v (source EMF), b, h, e (the bench's
output). Reproducible from (seed, per-family counts, code); a rerun overwrites.

    uv run --extra ml python -m spike.neural_core.teacher [--train-per-family 64]
"""

from __future__ import annotations

import argparse
import json
import os
import time
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict
from pathlib import Path

import numpy as np

from spike.neural_core.bench import JACore, run, t101_bench
from spike.neural_core.signals import Item, random_items, test_items
from varimu.config import load_sim_settings

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "cache" / "spike" / "neural_core"
DATA_DIR = OUT_DIR / "data"


def _teach(item: Item) -> tuple[str, dict[str, np.ndarray], float]:
    bench = t101_bench()
    t0 = time.perf_counter()
    r = run(bench, item.v, JACore(bench.core_model()))
    keep = {k: r[k] for k in ("b", "h", "e")} | {"stalls": int(r["stalls"].sum())}
    return item.name, keep, time.perf_counter() - t0


def teach(items: list[Item], workers: int) -> dict[str, dict[str, np.ndarray]]:
    by_name = {}
    done = 0
    # the longest first, so the pool doesn't end on one long item
    order = sorted(items, key=lambda it: -len(it.v))
    with ProcessPoolExecutor(workers) as pool:
        for name, r, dt in pool.map(_teach, order, chunksize=1):
            by_name[name] = r
            if r["stalls"]:
                print(f"  {name}: Newton stalled on {r['stalls']} samples (bench.STALL_T)")
            done += 1
            if done % 25 == 0 or done == len(items):
                print(f"  {done}/{len(items)} ({name}: {len(r['b']) / dt / 1e3:.1f} k samples/s)")
    return by_name


def save(path: Path, items: list[Item], results: dict, info: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    cat = {
        k: np.concatenate([results[it.name][k] for it in items]).astype(np.float64)
        for k in ("b", "h", "e")
    }
    np.savez(
        path,
        v=np.concatenate([it.v for it in items]),
        lengths=np.array([len(it.v) for it in items]),
        index=json.dumps({"info": info, "items": [[it.name, it.meta] for it in items]}),
        **cat,
    )


def load(split: str) -> tuple[list[tuple[str, dict]], dict[str, list[np.ndarray]], dict]:
    """(items as (name, meta), sequences per key {v, b, h, e}, info) of a saved split."""
    z = np.load(DATA_DIR / f"{split}.npz")
    index = json.loads(str(z["index"]))
    cuts = np.cumsum(z["lengths"])[:-1]
    seqs = {k: np.split(z[k], cuts) for k in ("v", "b", "h", "e")}
    return [tuple(x) for x in index["items"]], seqs, index["info"]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--train-per-family", type=int, default=64)
    ap.add_argument("--test-per-family", type=int, default=8)
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 4) - 2))
    ap.add_argument("--only", choices=("train", "test"))
    args = ap.parse_args()
    settings = load_sim_settings()
    fs, seed = settings.sample_rate, settings.seed
    bench = t101_bench()
    splits = {
        "train": lambda: random_items(seed, "train", args.train_per_family, fs),
        "test": lambda: test_items(seed, args.test_per_family, fs),
    }
    for split, make in splits.items():
        if args.only and split != args.only:
            continue
        items = make()
        total_s = sum(len(it.v) for it in items) / fs
        print(f"{split}: {len(items)} items, {total_s:.0f} s of audio, {args.workers} workers")
        t0 = time.perf_counter()
        results = teach(items, args.workers)
        info = {
            "seed": seed,
            "fs_hz": fs,
            "bench": asdict(bench),
            "per_family": {"train": args.train_per_family, "test": args.test_per_family},
        }
        save(DATA_DIR / f"{split}.npz", items, results, info)
        print(f"{split}: {time.perf_counter() - t0:.0f} s -> {DATA_DIR / (split + '.npz')}")


if __name__ == "__main__":
    main()
