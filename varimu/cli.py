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


def _render_inputs(args: argparse.Namespace, sample_rate: int, seed: int):
    """(label, samples) for every --clip and --signal, trimmed to --start/--seconds."""
    from varimu.sim.io import load_audio

    items = []
    for clip in args.clip or []:
        items.append((Path(clip).stem, load_audio(Path(clip), sample_rate)))
    if args.signal:
        specs = {sp.name: sp for sp in signals.default_library()}
        for name in args.signal:
            if name not in specs:
                raise SystemExit(f"unknown signal {name!r} (see `varimu signals --list`)")
            items.append(
                (name, signals.render(specs[name], sample_rate=sample_rate, seed=seed).samples)
            )
    if not items:
        raise SystemExit("give at least one --clip or --signal")
    a = round(args.start * sample_rate)
    b = None if args.seconds is None else a + round(args.seconds * sample_rate)
    return [(label, x[a:b]) for label, x in items]


def _cmd_render(args: argparse.Namespace) -> int:
    import itertools

    from varimu.sim import runner
    from varimu.sim.io import write_audio

    settings = load_sim_settings()
    inputs = _render_inputs(args, settings.sample_rate, settings.seed)
    base = runner.parse_overrides(args.set or [])
    axes = []
    for spec in args.vary or []:
        k, _, vals = spec.partition("=")
        axes.append([(k, runner.parse_overrides([f"{k}={v}"])[k]) for v in vals.split(",")])
    combos = [dict(c) for c in itertools.product(*axes)] if axes else [{}]

    jobs, names = [], []
    for (label, x), combo in itertools.product(inputs, combos):
        ov = {**base, **combo}
        suffix = "".join(f"_{k}-{v}" for k, v in combo.items())
        jobs.append(runner.RenderJob(x, ov, label=label + suffix))
        names.append(label + suffix)

    n = min(args.jobs or runner.default_jobs(), len(jobs))
    print(f"{len(jobs)} render(s), up to {n} in parallel")
    renders = runner.render_many(jobs, max_jobs=n)
    single = len(renders) == 1 and args.out and args.out.suffix.lower() == ".wav"
    for r, name in zip(renders, names, strict=True):
        dest = args.out if single else (args.out or Path("renders")) / f"{name}.wav"
        write_audio(dest, r.output, r.sample_rate)
        info = runner.summarize(r)
        status = (
            "cached"
            if info["cached"]
            else f"{info['wall_s']} s, {info['realtime_factor']}x realtime"
        )
        print(f"  {name}: {info['audio_s']} s audio ({status}) -> {dest}")
    return 0


def _cmd_listen(args: argparse.Namespace) -> int:
    try:
        from varimu.listen.app import serve
    except ImportError as e:
        raise SystemExit(f"{e}. Install the listen extra: uv sync --extra listen") from e
    print(f"varimu listen on http://{args.host}:{args.port}  (Ctrl-C to stop)")
    serve(args.host, args.port, args.jobs)
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

    p = sub.add_parser("render", help="run audio through the circuit simulation")
    p.add_argument("--clip", nargs="+", type=Path, help="audio file(s); folded to mono, resampled")
    p.add_argument("--signal", nargs="+", metavar="NAME", help="test signal(s) from the library")
    p.add_argument("--set", nargs="+", metavar="KEY=VALUE", help="circuit control/value overrides")
    p.add_argument("--vary", nargs="+", metavar="KEY=A,B,C", help="render every combination")
    p.add_argument("--start", type=float, default=0.0, help="excerpt start (s)")
    p.add_argument("--seconds", type=float, help="excerpt length (s); default: to the end")
    p.add_argument("--out", type=Path, help="output .wav (single render) or directory")
    p.add_argument("--jobs", type=int, help="parallel renders (default: cpu_count - 2)")
    p.set_defaults(func=_cmd_render)

    p = sub.add_parser("listen", help="tweak-and-listen web page (needs the listen extra)")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--jobs", type=int, help="parallel renders (default: cpu_count - 2)")
    p.set_defaults(func=_cmd_listen)

    args = parser.parse_args(argv)
    return args.func(args)
