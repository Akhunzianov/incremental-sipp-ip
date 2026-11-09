"""Replay distinct threshold decisions once per case, including persistent histories."""
import argparse
from collections import defaultdict
from functools import lru_cache
from itertools import product
import json
from pathlib import Path
import statistics
import subprocess

from .events import effective_reservations, planning_events
from .model import protocol, load
from .runner import ROOT, ensure_built
from .repair import ensure_incremental
from .validation import validate, oracle


def measure(data, policies, repeats, engineered):
    selected, _ = planning_events(data)
    free = sum(row.count('.') for row in data['grid'])
    snapshots = [dict(effective_reservations(data, f)) for f in selected]

    @lru_cache(None)
    def changed(a, b):
        x, y = snapshots[a], snapshots[b]
        return sum(x.get(k) != y.get(k) for k in x.keys() | y.keys())

    groups = defaultdict(list)
    for minimum, percent in policies:
        cached = 0
        choices = ['repair']
        for i in range(1, len(selected)):
            count = changed(cached, i)
            if count and count >= minimum and count * 100 >= free * percent:
                choices.append('full_replan')
            else:
                choices.append('repair')
                cached = i
        groups[tuple(choices)].append((minimum, percent))
    commands = {'full': [ensure_built()], 'repair': [ensure_incremental()]}
    for choices, pairs in groups.items():
        commands[choices] = [ROOT/'build/sipp_ip_adaptive', *map(str, pairs[0])]
    payload = ''.join(protocol(data, f, 1_000_000) for f in selected).encode()
    times = defaultdict(list)
    diagnostics = {}
    expected = None
    validated_paths = [set() for _ in selected]
    for trial in range(repeats + 1):
        names = list(commands)
        offset = trial % len(names)
        for name in names[offset:] + names[:offset]:
            proc = subprocess.run(commands[name], input=payload, stdout=subprocess.PIPE, check=True, timeout=180)
            rows = [json.loads(line) for line in proc.stdout.splitlines()]
            answers = [(r['status'], r['cost_ticks']) for r in rows]
            if expected is None:
                expected = [oracle(data, f) for f in selected] if engineered else answers
            if len(rows) != len(selected) or answers != expected or any(s=='expansion_limit' for s,c in answers):
                raise ValueError('inconclusive or mismatched answers')
            if isinstance(name, tuple) and tuple(r['strategy'] for r in rows) != name:
                raise ValueError('policy prediction differs from native decisions')
            for f,r,seen in zip(selected,rows,validated_paths):
                witness = (r['status'],r['cost_ticks'],json.dumps(r['steps'],sort_keys=True))
                if witness not in seen:
                    validate(data,f,r)
                    seen.add(witness)
            if trial:
                times[name].append([r['total_us'] for r in rows[1:]])
            diagnostics[str(name)] = [{k:r[k] for k in ('decision_us','suspect_projections','before_live_projections','changed_cells') if k in r} for r in rows[1:]]
    timings = {str(name):list(map(statistics.median,zip(*samples))) for name,samples in times.items()}
    return dict(policy={f'{a}/{b}':str(trace) for trace,pairs in groups.items() for a,b in pairs},
                us=timings, diagnostics=diagnostics,queries=len(selected))


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('suites',nargs='+',type=Path)
    p.add_argument('--seeds',nargs='+',type=int,required=True)
    p.add_argument('--pairs',nargs='+',help='minimum/percent pairs; defaults to the training grid')
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--repeats',type=int,default=3)
    args=p.parse_args()
    policies=[tuple(map(int,s.split('/'))) for s in args.pairs] if args.pairs else list(product((0,8,16,32,64),(0,1,2,5,10,20)))
    if args.repeats < 1:
        p.error('--repeats must be positive')
    if any(len(pair) != 2 or not 0 <= pair[0] <= 2**31-1 or not 0 <= pair[1] <= 100 for pair in policies):
        p.error('each pair requires a nonnegative 32-bit cell count and a percentage in [0,100]')
    subprocess.run(['make','build-adaptive'],cwd=ROOT,check=True)
    with args.output.open('x') as stream:
        for suite in args.suites:
            registry=json.loads((suite/'suite.json').read_text())
            if not registry['complete']:raise ValueError('incomplete suite')
            for case in registry['cases']:
                if case['seed'] not in args.seeds:continue
                data=load(suite/case['directory']/'scenario.json')
                result=measure(data,policies,args.repeats,case['tier']=='engineered')
                record={k:case[k] for k in ('directory','seed','density','map','tier','profile','scenario_sha256')}
                stream.write(json.dumps(dict(record,**result))+'\n')
                stream.flush()


if __name__=='__main__':
    main()
