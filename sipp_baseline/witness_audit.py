"""Replay the archived decisions and measure root-reachable old witness coverage."""
import argparse
import gzip
import json
import subprocess
from collections import Counter
from pathlib import Path
from statistics import median
from tempfile import TemporaryDirectory

from .model import load, protocol
from .runner import ROOT


def replay(seed):
    suite = 'diverse-scenarios' if seed == 19 else 'threshold-fresh'
    archive = ROOT / 'docs' / f'moving-projections-{seed}.jsonl.gz'
    output = ROOT / 'docs' / f'witness-audit-{seed}.jsonl.gz'
    with TemporaryDirectory(dir=output.parent) as directory:
        temporary = Path(directory) / output.name
        with gzip.open(archive, 'rt') as episodes, gzip.open(temporary, 'wt') as results:
            for line in episodes:
                episode = json.loads(line)
                scenario = load(ROOT / 'runs' / suite / episode['case'] / 'scenario.json')
                forecasts = {f['id']: f for f in scenario['forecasts']}
                queries = episode['queries']
                payload = ''.join(protocol(dict(scenario, start=q['start'], start_tick=q['tick']),
                                           forecasts[q['forecast']], 1_000_000) for q in queries)
                proc = subprocess.run([ROOT / 'build/witness_audit'], input=payload, text=True,
                                      capture_output=True, check=True, timeout=300)
                rows = [json.loads(line) for line in proc.stdout.splitlines()]
                if len(rows) != len(queries):
                    raise ValueError(f"Missing decisions in {episode['case']}")
                for i, (row, q) in enumerate(zip(rows, queries)):
                    cost = None if q['remaining'] is None else q['tick'] + q['remaining']
                    status = episode['outcome'] if cost is None else 'solved'
                    miss = i > 0 and q['strategy'] != 'certified_suffix'
                    if (row['status'], row['cost_ticks'], row['audited']) != (status, cost, miss):
                        raise ValueError((episode['case'], i, row, q))
                results.write(json.dumps(dict(case=episode['case'], queries=rows)) + '\n')
        # Preserve a complete previous archive if replay or validation fails.
        temporary.replace(output)


def summarize(seed):
    with gzip.open(ROOT / 'docs' / f'fresh-policy-{seed}.jsonl.gz', 'rt') as records:
        baseline = {e['case']: e['methods']['suffix_fresh']
                    for e in map(json.loads, records)}
    counts = Counter()
    with gzip.open(ROOT / 'docs' / f'witness-audit-{seed}.jsonl.gz', 'rt') as records:
        for episode in map(json.loads, records):
            counts['episodes'] += 1
            methods = baseline[episode['case']]
            for i, row in enumerate(episode['queries']):
                counts['queries'] += 1
                if row['audited']:
                    counts['misses'] += 1
                    counts['favorable'] += row['credit_us'] > row['discovery_us']
                    counts['baseline_miss_us'] += median(trial[i] for trial in methods['times'])
                    counts.update({k: v for k,v in row.items()
                                   if k not in ('status', 'cost_ticks', 'audited')})
    return counts


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    options = parser.add_mutually_exclusive_group(required=True)
    options.add_argument('--seed', type=int, choices=[19, 23, 29])
    options.add_argument('--summary', action='store_true')
    args = parser.parse_args()
    if args.summary:
        print(json.dumps({seed: summarize(seed) for seed in (19, 23, 29)}, indent=2))
    else:
        subprocess.run(['make', 'build/witness_audit'], cwd=ROOT, check=True)
        replay(args.seed)
