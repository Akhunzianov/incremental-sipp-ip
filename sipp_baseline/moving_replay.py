"""Replay effective forecast changes while executing the baseline's validated path."""
import argparse
from collections import Counter
import json
from pathlib import Path
import subprocess
import statistics

from .events import planning_events
from .model import load, protocol
from .runner import ROOT, solve_batch
from .validation import World, primitives, validate


def committed_segment_free(data, forecast, step, first, last):
    r,c,o,v = step['from']
    motion = next(p for p in primitives(o,v) if p[0] == step['action'])
    world = World(data,forecast)
    for dr,dc,a,b in motion[-1]:
        lo = max(first,step['start']+a)
        hi = min(last,step['start']+b)
        if lo <= hi and not world.free(r+dr,c+dc,lo,hi):
            return False
    return True


def replay(data, minimum, percent, paired=False, projection_reuse=False, suffix_fresh=False, on_demand=False):
    forecasts,_ = planning_events(data)
    state, tick = data['start'],data.get('start_tick',0)
    queries = []
    i = 0
    while True:
        query = dict(data,start=state,start_tick=tick)
        forecast = forecasts[i]
        row, = solve_batch(query,[forecast])
        validate(query,forecast,row)
        queries.append((query,forecast,row))
        if row['status'] != 'solved':
            outcome = row['status']
            break
        if i+1 == len(forecasts) or row['cost_ticks'] <= forecasts[i+1]['revision_tick']:
            outcome = 'arrived'
            break
        i += 1
        revision = forecasts[i]['revision_tick']
        step = next(s for s in row['steps'] if s['end'] > revision)
        if step['start'] == revision or step['action'] == 'wait':
            state,tick = step['from'],revision
            continue
        # An in-flight primitive has no intermediate lattice state. Check each
        # portion under the forecast available at that time until it finishes.
        state,tick = step['to'],step['end']
        conflict = False
        while True:
            following = forecasts[i+1]['revision_tick'] if i+1 < len(forecasts) else tick+1
            if not committed_segment_free(data,forecasts[i],step,revision,min(tick,following-1)):
                conflict = True
                break
            if following > tick:break
            i += 1
            revision = following
        if conflict:
            outcome = 'committed_motion_conflict'
            break
    payload = ''.join(protocol(q,f,1_000_000) for q,f,r in queries)
    binary = ROOT/'build'/('on_demand' if on_demand else 'sipp_ip_adaptive')
    commands={'adaptive':[binary,str(minimum),str(percent)]}
    if suffix_fresh or on_demand:
        if paired or projection_reuse or (suffix_fresh and on_demand):raise ValueError('choose one moving policy')
        commands['adaptive'].append('--suffix-fresh')
    if projection_reuse or paired:
        commands['adaptive'].append('--projection-reuse')
    if paired:
        commands['suffix_only']=[binary,str(minimum),str(percent)]
        commands['full']=[ROOT/'build/sipp_ip']
    times={name:[[] for _ in queries] for name in commands}
    for trial in range(4 if paired else 1):
        names=list(commands)
        offset=trial%len(names)
        for name in names[offset:]+names[:offset]:
            proc=subprocess.run(commands[name],input=payload,text=True,capture_output=True,check=True,timeout=180)
            results=[json.loads(line) for line in proc.stdout.splitlines()]
            if len(results)!=len(queries):raise RuntimeError('missing replay result')
            for index,((q,f,ref),result) in enumerate(zip(queries,results)):
                validate(q,f,result)
                if result['status']=='expansion_limit' or (result['status'],result['cost_ticks'])!=(ref['status'],ref['cost_ticks']):
                    raise RuntimeError('moving-start comparison inconclusive or mismatched')
                if trial or not paired:
                    times[name][index].append(result['total_us'])
            if name=='adaptive':rows=results
    decisions = []
    for index,((q,f,ref),row) in enumerate(zip(queries,rows)):
        decisions.append(dict(start=q['start'], tick=q['start_tick'], forecast=f['id'],
                              remaining=None if row['cost_ticks'] is None else row['cost_ticks']-q['start_tick'],
                              reset=row.get('reset'),strategy=row['strategy'], expansions=row['expansions'],
                              projection_hits=row.get('projection_hits',0), clipped_hits=row.get('clipped_hits',0),
                              empty_hits=row.get('empty_hits',0), projections=row['projections'],
                              adaptive_us=statistics.median(times['adaptive'][index]),
                              suffix_only_us=statistics.median(times['suffix_only'][index]) if paired else None,
                              full_us=statistics.median(times['full'][index]) if paired else ref['total_us']))
    return dict(outcome=outcome,queries=decisions)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('suite',type=Path)
    p.add_argument('--seed',type=int,required=True)
    p.add_argument('--minimum',type=int,required=True)
    p.add_argument('--percent',type=int,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--suffix-fresh',action='store_true',help='retain a certified path and use fresh SIPP-IP on a miss')
    p.add_argument('--on-demand',action='store_true',help='try cached outgoing motions after a fresh interval is reached')
    p.add_argument('--projection-reuse',action='store_true',help='enable moving-root projection transfer')
    p.add_argument('--paired',action='store_true',help='compare projection reuse, suffix only and full replanning over three timed trials')
    args=p.parse_args()
    subprocess.run(['make','build/on_demand' if args.on_demand else 'build-adaptive'],cwd=ROOT,check=True)
    counts=Counter()
    with args.output.open('x') as stream:
        for case in json.loads((args.suite/'suite.json').read_text())['cases']:
            if case['seed']!=args.seed:continue
            result=replay(load(args.suite/case['directory']/'scenario.json'),args.minimum,args.percent,args.paired,args.projection_reuse,args.suffix_fresh,args.on_demand)
            counts[result['outcome']]+=1
            stream.write(json.dumps(dict(case=case['directory'],**result))+'\n')
    print(dict(counts))


if __name__=='__main__':main()
