import argparse
import json
from pathlib import Path
import subprocess
import sys

from .generate import generate
from .model import load, read_map
from .runner import benchmark, build, summarize


def nonnegative(text):
    value = int(text)
    if value < 0:
        raise argparse.ArgumentTypeError("must be nonnegative")
    return value


def positive(text):
    value = int(text)
    if value < 1:
        raise argparse.ArgumentTypeError("must be positive")
    return value


def probability(text):
    value = float(text)
    if not 0 <= value <= 1:
        raise argparse.ArgumentTypeError("must be in [0,1]")
    return value


def main():
    parser = argparse.ArgumentParser(description="Fixed-start SIPP-IP: full replan on every forecast")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("build", help="compile the C++17 planner with g++")
    gen = commands.add_parser("generate", help="save a seeded forecast sequence")
    gen.add_argument("--output", required=True, type=Path)
    gen.add_argument("--map", type=Path)
    gen.add_argument("--width", type=positive, default=24)
    gen.add_argument("--height", type=positive, default=24)
    gen.add_argument("--seed", type=int, default=0)
    gen.add_argument("--updates", type=nonnegative, default=5)
    gen.add_argument("--obstacles", type=nonnegative, default=4)
    gen.add_argument("--probability", type=probability, default=.25)
    gen.add_argument("--horizon", type=nonnegative, default=500)
    gen.add_argument("--start", nargs=4, type=int, metavar=("R", "C", "O", "V"))
    gen.add_argument("--goal", nargs=3, type=int, metavar=("R", "C", "V"))
    run = commands.add_parser("run", help="replan independently for all saved forecasts")
    run.add_argument("scenario", type=Path)
    run.add_argument("--output", required=True, type=Path)
    run.add_argument("--repeats", type=positive, default=3)
    run.add_argument("--warmups", type=nonnegative, default=1)
    run.add_argument("--oracle", action="store_true", help="also run bounded time-expanded Dijkstra (small scenarios)")
    run.add_argument("--max-expansions", type=nonnegative, default=1_000_000)
    run.add_argument("--timeout", type=positive, default=120, help="seconds per full forecast batch")
    run.add_argument("--binary", type=Path, help="use an explicitly built planner, e.g. sanitizer build")
    report = commands.add_parser("summarize")
    report.add_argument("results", type=Path)
    report.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        if args.command == "build":
            print(build())
        elif args.command == "generate":
            if args.output.exists():
                raise ValueError(f"output already exists: {args.output}")
            grid = read_map(args.map) if args.map else ["."*args.width for _ in range(args.height)]
            data = generate(grid, args.seed, args.updates, args.obstacles, args.probability,
                            args.horizon, args.start, args.goal)
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(data, indent=2) + "\n")
            print(args.output)
        elif args.command == "run":
            summary = benchmark(load(args.scenario), args.output, args.repeats, args.warmups,
                                args.oracle, args.max_expansions, args.binary, args.timeout)
            for row in summary:
                print(f"{row['forecast_id']}: {row['status']}, cost={row['cost_ticks']}, "
                      f"median={row['median_total_us']:.1f} us, expansions={row['expansions']}")
            print(f"Saved results to {args.output}")
        else:
            print(json.dumps(summarize(args.results, args.output), indent=2))
    except (ValueError, KeyError, RuntimeError, OSError, subprocess.SubprocessError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
