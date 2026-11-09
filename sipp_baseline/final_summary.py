"""Aggregate the frozen final-study archives by seed, map and certificate misses."""
from collections import Counter, defaultdict
import gzip
import json

from .moving_compare import FINAL_SEEDS
from .on_demand_report import metrics, records
from .runner import ROOT

POLICIES = ('suffix_fresh', 'on_demand_compact')


def summarize():
    groups = defaultdict(list)
    outcomes = Counter()
    for seed in FINAL_SEEDS:
        episodes = records(seed, 'final-trials')
        with gzip.open(ROOT/'docs'/f'final-decisions-{seed}.jsonl.gz','rt') as stream:
            decisions = {e['case']: e for e in map(json.loads,stream)}
        if len(episodes) != 90 or len({e['case'] for e in episodes}) != 90:
            raise ValueError(f'Incomplete final archive for seed {seed}')
        for e in episodes:
            ref = decisions[e['case']]
            strategies = e['methods']['suffix_fresh']['strategies']
            hits = [s == 'certified_suffix' for s in strategies]
            other = e['methods']['on_demand_compact']['strategies']
            if hits != [s == 'certified_suffix' for s in other] or len(hits) != len(ref['queries']):
                raise ValueError(f"Decision classification mismatch in {e['case']}")
            outcomes[ref['outcome']] += 1
            groups['all'].append(e)
            groups[f'seed/{seed}'].append(e)
            groups['map/'+e['case'].split('/')[0]].append(e)
            groups[f'misses/{hits[1:].count(False)}'].append(e)
    result = {key:{p:metrics(episodes,p) for p in POLICIES} for key,episodes in groups.items()}
    return dict(outcomes=outcomes,groups=result)


if __name__ == '__main__':
    print(json.dumps(summarize(),indent=2))
