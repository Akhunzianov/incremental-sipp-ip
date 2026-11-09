"""Paired policy comparison on the archived moving-start decision sequences."""
import argparse
import gzip
import json
from pathlib import Path
import subprocess
from time import perf_counter_ns

from .model import load, protocol
from .runner import ROOT, ensure_built
from .validation import validate


def compare(seed, output, profile=False, on_demand=False):
    archive = ROOT / 'docs' / f'moving-projections-{seed}.jsonl.gz'
    suite = ROOT / 'runs' / ('diverse-scenarios' if seed == 19 else 'threshold-fresh')
    if on_demand and seed != 19:
        suite = ROOT / 'runs/on-demand-holdout'
        archive = ROOT / 'docs' / f'on-demand-decisions-{seed}.jsonl.gz'
    binary = ROOT / 'build' / ('sipp_profile' if profile else 'sipp_ip_adaptive')
    commands = {'suffix_only': [binary,'0','5'], 'transfer': [binary,'0','5','--projection-reuse']}
    audit = on_demand and seed == 19
    if on_demand:
        candidate = 'on_demand_audit' if audit else 'on_demand'
        commands = {candidate: [ROOT/'build'/candidate,'0','5','--suffix-fresh']}
        if not audit:
            commands['suffix_fresh'] = [binary,'0','5','--suffix-fresh']
    elif profile:
        commands["full"]=[ROOT/"build/full_profile"]
    else:
        commands.update(full=[ensure_built()], suffix_fresh=[binary,'0','5','--suffix-fresh'])
    with gzip.open(archive,'rt') as source, output.open('x') as target:
        for line in source:
            episode = json.loads(line)
            data = load(suite / episode['case'] / 'scenario.json')
            forecasts = {f['id']: f for f in data['forecasts']}
            queries = [(dict(data,start=q['start'],start_tick=q['tick']),forecasts[q['forecast']])
                       for q in episode['queries']]
            payload = ''.join(protocol(q,f,1_000_000) for q,f in queries).encode()
            record = dict(case=episode['case'], outcome=episode['outcome'], methods={})
            for trial in range(1 if profile or audit else 4):
                names = list(commands)
                offset = (trial + len(record['case'])) % len(names)
                for name in names[offset:] + names[:offset]:
                    started = perf_counter_ns() if on_demand else 0
                    proc = subprocess.run(['/usr/bin/time','-f','%M',*commands[name]],input=payload,
                                          capture_output=True,check=True,timeout=180)
                    wall_us = (perf_counter_ns()-started)/1000 if on_demand else 0
                    rows = [json.loads(row) for row in proc.stdout.splitlines()]
                    if len(rows)!=len(queries): raise RuntimeError('missing decision')
                    for (q,f), previous, row in zip(queries,episode['queries'],rows):
                        validate(q,f,row)
                        expected = previous['remaining']
                        if expected is not None: expected += q['start_tick']
                        status = 'solved' if expected is not None else episode['outcome']
                        if (row['status'],row['cost_ticks']) != (status,expected):
                            raise RuntimeError(f'{episode["case"]}: decision mismatch')
                    if profile or audit or trial:
                        samples = record['methods'].setdefault(name,dict(times=[],rss=[],strategies=[]))
                        if on_demand: samples.setdefault('wall_us',[]).append(wall_us)
                        samples['times'].append([r['total_us'] for r in rows])
                        samples['rss'].append(int(proc.stderr.strip()))
                        samples['strategies']=[r.get('strategy','full_replan') for r in rows]
                        if name.startswith('on_demand'):
                            fields = ('batch_hits','clipped_hits','probes','lookup_us','credit_us')
                            samples['lookup'] = [{k:r.get(k,0) for k in fields} for r in rows]
                        if profile: samples['phases']=[r.get('phases',{}) for r in rows]
            target.write(json.dumps(record)+'\n')
            target.flush()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seed',type=int,choices=[19,23,29,31,37],required=True)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument('--profile',action='store_true')
    modes.add_argument('--on-demand',action='store_true')
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    subprocess.run(['make','build/sipp_profile' if args.profile else 'build-adaptive'],cwd=ROOT,check=True)
    if args.profile:subprocess.run(['make','build/full_profile'],cwd=ROOT,check=True)
    if args.on_demand:
        if args.seed not in (19,31,37): parser.error('on-demand seeds are 19, 31 and 37')
        target = 'on_demand_audit' if args.seed == 19 else 'on_demand'
        subprocess.run(['make','build/'+target],cwd=ROOT,check=True)
    elif args.seed not in (19,23,29):
        parser.error('original comparison seeds are 19, 23 and 29')
    compare(args.seed,args.output,args.profile,args.on_demand)
