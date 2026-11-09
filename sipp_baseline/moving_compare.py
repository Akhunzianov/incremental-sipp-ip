"""Paired policy comparison on the archived moving-start decision sequences."""
import argparse
import gzip
import json
from pathlib import Path
import subprocess

from .model import load, protocol
from .runner import ROOT, ensure_built
from .validation import validate


def compare(seed, output, profile=False):
    archive = ROOT / 'docs' / f'moving-projections-{seed}.jsonl.gz'
    suite = ROOT / 'runs' / ('diverse-scenarios' if seed == 19 else 'threshold-fresh')
    binary = ROOT / 'build' / ('sipp_profile' if profile else 'sipp_ip_adaptive')
    commands = {'suffix_only': [binary,'0','5'], 'transfer': [binary,'0','5','--projection-reuse']}
    if profile:
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
            for trial in range(1 if profile else 4):
                names = list(commands)
                offset = (trial + len(record['case'])) % len(names)
                for name in names[offset:] + names[:offset]:
                    proc = subprocess.run(['/usr/bin/time','-f','%M',*commands[name]],input=payload,
                                          capture_output=True,check=True,timeout=180)
                    rows = [json.loads(row) for row in proc.stdout.splitlines()]
                    if len(rows)!=len(queries): raise RuntimeError('missing decision')
                    for (q,f), previous, row in zip(queries,episode['queries'],rows):
                        validate(q,f,row)
                        expected = previous['remaining']
                        if expected is not None: expected += q['start_tick']
                        status = 'solved' if expected is not None else episode['outcome']
                        if (row['status'],row['cost_ticks']) != (status,expected):
                            raise RuntimeError(f'{episode["case"]}: decision mismatch')
                    if profile or trial:
                        samples = record['methods'].setdefault(name,dict(times=[],rss=[],strategies=[]))
                        samples['times'].append([r['total_us'] for r in rows])
                        samples['rss'].append(int(proc.stderr.strip()))
                        samples['strategies']=[r.get('strategy','full_replan') for r in rows]
                        if profile: samples['phases']=[r.get('phases',{}) for r in rows]
            target.write(json.dumps(record)+'\n')
            target.flush()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seed',type=int,choices=[19,23,29],required=True)
    parser.add_argument('--profile',action='store_true')
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    subprocess.run(['make','build/sipp_profile' if args.profile else 'build-adaptive'],cwd=ROOT,check=True)
    if args.profile:subprocess.run(['make','build/full_profile'],cwd=ROOT,check=True)
    compare(args.seed,args.output,args.profile)
