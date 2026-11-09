"""Select a training policy and summarize paired native update timings."""
import argparse
from collections import defaultdict
import json
import math
from pathlib import Path
import statistics


def read(path):
    return [json.loads(line) for line in Path(path).read_text().splitlines()]


def score(rows, policy, tier):
    ratios=[]
    for row in rows:
        if row['tier']!=tier or not row['us']['full']:continue
        times=row['us'][row['policy'][policy]]
        ratios.append(sum(times)/sum(row['us']['full']))
    return statistics.geometric_mean(ratios)


def select(rows):
    scores={p:(score(rows,p,'upstream'),score(rows,p,'engineered')) for p in rows[0]['policy']}
    best=min(s[0] for s in scores.values())
    candidates=[p for p,s in scores.items() if s[0]<=best*1.01]
    def preference(p):
        a,b=map(int,p.split('/'))
        return (scores[p][1],scores[p][0],abs(b-10),abs(a-32))
    return min(candidates,key=preference),scores


def distribution(values):
    ordered=sorted(values)
    return {'median_us':statistics.median(values),'p95_us':ordered[math.ceil(.95*len(values))-1]}


def summarize(rows,policy):
    groups=defaultdict(list)
    for r in rows:
        groups[r['tier']].append(r)
        groups[r['tier']+' / '+r['profile']].append(r)
    result={}
    for name,cases in groups.items():
        summary={}
        for method in dict.fromkeys(('full','repair','32/10',policy)):
            values=[]
            for case in cases:
                key=case['policy'].get(method,method)
                values.extend(case['us'][key])
            if values:
                summary[method]=distribution(values)
                ratios=[sum(r['us'][r['policy'].get(method,method)])/sum(r['us']['full'])
                        for r in cases if r['us']['full']]
                summary[method]['geomean_time_over_full']=statistics.geometric_mean(ratios)
                summary[method]['updates']=len(values)
        result[name]=summary
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('training')
    parser.add_argument('--holdout')
    args=parser.parse_args()
    winner,scores=select(read(args.training))
    result=dict(selected=winner,training_ratios=scores)
    if args.holdout:result['holdout']=summarize(read(args.holdout),winner)
    print(json.dumps(result,indent=2))
