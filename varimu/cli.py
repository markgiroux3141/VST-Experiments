"""Command-line entry point: `uv run varimu <command>`."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

from varimu.config import DATA_DIR, load_genome_bounds, load_sim_settings
from varimu.measure import signals


def _cmd_signals(args: argparse.Namespace) -> int:
    settings = load_sim_settings()
    specs = signals.default_library()
    if args.list:
        for s in specs:
            print(f"{s.name:36s} {s.kind}")
        return 0
    if args.only:
        known = {s.name for s in specs}
        unknown = sorted(set(args.only) - known)
        if unknown:
            raise SystemExit(f"unknown signal(s): {', '.join(unknown)} (see --list)")
        specs = [s for s in specs if s.name in args.only]

    seed = settings.seed if args.seed is None else args.seed
    manifest = signals.write_library(
        args.out, seed=seed, sample_rate=settings.sample_rate, specs=specs
    )
    total = sum(e["duration_s"] for e in manifest["signals"])
    print(
        f"wrote {len(manifest['signals'])} signals ({total:.1f} s of audio, "
        f"seed {seed}, {settings.sample_rate} Hz) to {args.out}"
    )
    return 0


def _cmd_genome_status(args: argparse.Namespace) -> int:
    params = load_genome_bounds()
    unresolved = [p for p in params.values() if not p.resolved]
    for p in unresolved:
        rng = (
            f"choices={list(p.choices) if p.choices != 'TBD' else 'TBD'}"
            if p.is_choice
            else f"[{p.min}, {p.max}] {p.unit or ''}".rstrip()
        )
        print(f"  {p.path:48s} {rng:24s} source={p.source}")
    print(f"{len(params) - len(unresolved)}/{len(params)} genome parameters resolved")
    return 0


def _cmd_fit_devices(args: argparse.Namespace) -> int:
    from varimu.devices import library

    names = args.only or list(library.BUILDERS)
    unknown = sorted(set(names) - set(library.BUILDERS))
    if unknown:
        raise SystemExit(
            f"unknown device(s): {', '.join(unknown)} (known: {', '.join(library.BUILDERS)})"
        )
    for path in library.write_devices(names):
        print(f"wrote {path}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="varimu")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("signals", help="generate the test signal library")
    p.add_argument("--seed", type=int, help="override sim_settings.yaml seed")
    p.add_argument("--out", type=Path, default=DATA_DIR / "test_signals")
    p.add_argument("--only", nargs="+", metavar="NAME", help="generate only these signals")
    p.add_argument("--list", action="store_true", help="list signal names and exit")
    p.set_defaults(func=_cmd_signals)

    p = sub.add_parser("genome-status", help="list genome parameters still TBD")
    p.set_defaults(func=_cmd_genome_status)

    p = sub.add_parser("fit-devices", help="fit device models and write config/devices/*.yaml")
    p.add_argument("--only", nargs="+", metavar="NAME", help="build only these devices")
    p.set_defaults(func=_cmd_fit_devices)

    args = parser.parse_args(argv)
    return args.func(args)
