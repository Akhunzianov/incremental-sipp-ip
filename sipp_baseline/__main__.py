import argparse
import json
from pathlib import Path
import subprocess
import sys

from .generate import generate
from .model import load, read_map
from .runner import benchmark, build, summarize
from .visualize import export_viewer
from .paper import MAPS, build_paper_viewers
from .suite import DEFAULT_Q, build_suite
from .repair import build_incremental, compare_case, compare_suite


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
    parser = argparse.ArgumentParser(description="Fixed-start SIPP-IP: full replanning and persistent interval repair")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("build", help="compile the C++17 planner with g++")
    commands.add_parser('build-incremental',help='compile the persistent interval-repair planner')
    gen = commands.add_parser("generate", help="save a seeded forecast sequence")
    gen.add_argument("--output", required=True, type=Path)
    gen.add_argument("--map", type=Path)
    gen.add_argument("--width", type=positive, default=24)
    gen.add_argument("--height", type=positive, default=24)
    gen.add_argument("--seed", type=int, default=0)
    gen.add_argument("--updates", type=nonnegative, default=5)
    counts = gen.add_mutually_exclusive_group()
    counts.add_argument("--obstacles", type=nonnegative, help="obstacle count (default: 4)")
    counts.add_argument("--density", type=probability, help="obstacles / free cells; independent of q")
    gen.add_argument("--change-probability", "--q", dest="change_probability", type=probability, default=.25,
                     help="q: per-obstacle probability of a proposed change per forecast update")
    gen.add_argument("--update-interval", type=positive, default=100, help="ticks between updates (default: 100 = 10 s)")
    gen.add_argument("--change-modes", nargs="+", choices=['waypoint','pause','speed','accelerate','decelerate'], default=['waypoint','pause','speed'])
    gen.add_argument("--generation-timeout", type=positive, default=120)
    gen.add_argument("--horizon", type=nonnegative, default=40000)
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
    view = commands.add_parser("visualize", help="export an offline interactive viewer for a saved run")
    view.add_argument("run_directory", type=Path)
    view.add_argument("--output", type=Path, help="HTML output (default: RUN_DIRECTORY/viewer.html)")
    view.add_argument("--repetition", type=nonnegative, default=0, help="trajectory repetition to display")
    view.add_argument("--force", action="store_true", help="replace an existing HTML viewer")
    paper = commands.add_parser("paper-viewer", help="build viewers for original released SIPP-IP samples")
    paper.add_argument("--output", type=Path, required=True)
    paper.add_argument("--maps", nargs="+", choices=MAPS, default=list(MAPS))
    paper.add_argument("--max-expansions", type=nonnegative, default=2_000_000)
    paper.add_argument("--timeout", type=positive, default=120)
    paper.add_argument("--resume", action="store_true", help="reuse matching completed map runs in an existing bundle")
    sweep = commands.add_parser('compare-q',help='generate, measure and compare matched q sweeps on the paper maps')
    sweep.add_argument('--output',type=Path,required=True)
    sweep.add_argument('--maps',nargs='+',choices=MAPS,default=list(MAPS))
    sweep.add_argument('--q-values',nargs='+',type=probability,default=list(DEFAULT_Q))
    sweep.add_argument('--seed',type=nonnegative,default=7)
    sweep.add_argument('--density',type=probability,default=.04)
    sweep.add_argument('--updates',type=nonnegative,default=5)
    sweep.add_argument('--update-interval',type=positive,default=100)
    sweep.add_argument('--horizon',type=positive,default=40000)
    sweep.add_argument('--repeats',type=positive,default=3)
    sweep.add_argument('--warmups',type=nonnegative,default=1)
    sweep.add_argument('--max-expansions',type=positive,default=2_000_000)
    sweep.add_argument('--timeout',type=positive,default=120)
    sweep.add_argument('--generation-timeout',type=positive,default=120)
    sweep.add_argument('--resume',action='store_true')
    repair = commands.add_parser('compare-repair',help='differential-test repair against full replanning on one saved scenario')
    repair.add_argument('scenario',type=Path)
    repair.add_argument('--output',type=Path,required=True)
    repair.add_argument('--repeats',type=positive,default=3)
    repair.add_argument('--warmups',type=nonnegative,default=1)
    repair.add_argument('--max-expansions',type=nonnegative,default=2000000)
    repair.add_argument('--timeout',type=positive,default=120)
    repair.add_argument('--oracle',action='store_true')
    repair_suite = commands.add_parser('compare-repair-suite',help='compare repair/full replanning on every run in a saved q suite')
    repair_suite.add_argument('suite',type=Path)
    repair_suite.add_argument('--output',type=Path,required=True)
    repair_suite.add_argument('--repeats',type=positive,default=3)
    repair_suite.add_argument('--warmups',type=nonnegative,default=1)
    repair_suite.add_argument('--max-expansions',type=positive,default=2000000)
    repair_suite.add_argument('--timeout',type=positive,default=120)
    repair_suite.add_argument('--resume',action='store_true')
    args = parser.parse_args()
    try:
        if args.command == "build":
            print(build())
        elif args.command == 'build-incremental':
            print(build_incremental())
        elif args.command == "generate":
            if args.output.exists():
                raise ValueError(f"output already exists: {args.output}")
            grid = read_map(args.map) if args.map else ["."*args.width for _ in range(args.height)]
            data = generate(grid, seed=args.seed, updates=args.updates, obstacles=args.obstacles,
                            change_probability=args.change_probability, horizon=args.horizon,
                            start=args.start, goal=args.goal, map_name=args.map.stem if args.map else None,
                            density=args.density, update_interval=args.update_interval,
                            generation_timeout=args.generation_timeout, change_modes=args.change_modes)
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
        elif args.command == "visualize":
            print(export_viewer(args.run_directory, args.output, args.repetition, args.force))
        elif args.command == "paper-viewer":
            print(build_paper_viewers(args.output, args.maps, args.max_expansions, args.timeout, args.resume))
        elif args.command == 'compare-q':
            print(build_suite(args.output,maps=args.maps,q_values=args.q_values,seed=args.seed,density=args.density,
                              updates=args.updates,update_interval=args.update_interval,horizon=args.horizon,
                              repeats=args.repeats,warmups=args.warmups,max_expansions=args.max_expansions,
                              timeout=args.timeout,generation_timeout=args.generation_timeout,resume=args.resume))
        elif args.command == 'compare-repair':
            print(json.dumps(compare_case(args.scenario,args.output,args.repeats,args.warmups,
                                          args.max_expansions,args.timeout,args.oracle),indent=2))
        elif args.command == 'compare-repair-suite':
            print(compare_suite(args.suite,args.output,args.repeats,args.warmups,
                                args.max_expansions,args.timeout,args.resume))
        else:
            print(json.dumps(summarize(args.results, args.output), indent=2))
    except (ValueError, KeyError, RuntimeError, OSError, subprocess.SubprocessError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
