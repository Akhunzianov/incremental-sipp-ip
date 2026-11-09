"""Compare fresh, persistent and adaptive planning on registered scenarios."""
import argparse
import json
import statistics
import subprocess
from pathlib import Path

from .events import planning_events
from .model import load
from .repair import ensure_incremental
from .runner import ROOT, ensure_built, solve_batch
from .validation import oracle, validate


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('suites', nargs='+', type=Path)
    parser.add_argument('--seed', type=int, required=True)
    parser.add_argument('--density', type=float, default=.04)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--repeats', type=int, default=3)
    args = parser.parse_args()
    if args.repeats < 1:
        parser.error('--repeats must be positive')
    subprocess.run(['make', 'build-adaptive'], cwd=ROOT, check=True)
    binaries = {'full': ensure_built(), 'repair': ensure_incremental(),
                'adaptive': ROOT / 'build/sipp_ip_adaptive'}
    with args.output.open('x') as stream:
        for suite in args.suites:
            registry = json.loads((suite / 'suite.json').read_text())
            for case in registry['cases']:
                if case['seed'] != args.seed or (case['tier'] == 'upstream' and case['density'] != args.density):
                    continue
                data = load(suite / case['directory'] / 'scenario.json')
                forecasts, _ = planning_events(data)
                times = {name: [[] for _ in forecasts] for name in binaries}
                expected = {}
                strategies = {}
                for trial in range(args.repeats + 1):
                    names = list(binaries)
                    offset = trial % len(names)
                    for name in names[offset:] + names[:offset]:
                        rows = solve_batch(data, forecasts, binary=binaries[name])
                        for i, (forecast, row) in enumerate(zip(forecasts, rows)):
                            validate(data, forecast, row)
                            answer = row['status'], row['cost_ticks']
                            if answer[0] == 'expansion_limit':
                                raise RuntimeError(f'inconclusive: {case["directory"]}')
                            if i not in expected:
                                expected[i] = oracle(data, forecast) if case['tier'] == 'engineered' else answer
                            if expected[i] != answer:
                                raise RuntimeError(f'{case["directory"]}: {name} {answer} != {expected[i]}')
                            if trial:
                                times[name][i].append(row['total_us'])
                            if name == 'adaptive':
                                strategies[i] = row['strategy']
                record = {'case': case['directory'], 'profile': case['profile'], 'tier': case['tier'],
                          'seed': args.seed, 'strategies': list(strategies.values()), 'repeats': args.repeats,
                          'total_us': times, 'update_us': {name: sum(map(statistics.median, samples[1:]))
                                                           for name, samples in times.items()}}
                stream.write(json.dumps(record) + '\n')
                stream.flush()


if __name__ == '__main__':
    main()
