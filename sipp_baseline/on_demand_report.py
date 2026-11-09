"""Summarize paired moving-start trials stored by moving_compare."""
import argparse
from collections import Counter
import gzip
import json
from math import ceil
from statistics import median

from .runner import ROOT


def records(seed, prefix="on-demand"):
    with gzip.open(ROOT/'docs'/f'{prefix}-{seed}.jsonl.gz','rt') as f:
        return list(map(json.loads,f))


def metrics(episodes, method):
    updates, episode_us, wall_us, rss = [], [], [], []
    first_us = 0
    counts = Counter()
    for episode in episodes:
        runs = episode['methods'][method]
        samples = runs['times']
        queries = [median(values) for values in zip(*samples)]
        updates.extend(queries[1:])
        first_us += queries[0]
        episode_us.append(median(sum(trial) for trial in samples))
        wall_us.append(median(runs['wall_us']))
        rss.extend(runs['rss'])
        counts['queries'] += len(queries)
        counts['certificates'] += runs['strategies'].count('certified_suffix')
        for row in runs.get('lookup',[]):
            counts.update(row)
    return dict(episodes=len(episodes),updates=len(updates),**counts,
                summed_episode_s=sum(episode_us)/1e6, summed_wall_s=sum(wall_us)/1e6,
                initial_s=first_us/1e6, update_s=sum(updates)/1e6,
                p95_update_ms=sorted(updates)[ceil(.95*len(updates))-1]/1000 if updates else None,
                peak_mib=max(rss)/1024,
                trial_totals_s=[sum(sum(e['methods'][method]['times'][i]) for e in episodes)/1e6
                                for i in range(len(samples))])


def summary():
    pilot = Counter()
    for e in records(19):
        for row in e['methods']['on_demand_audit']['lookup']:
            pilot.update(row)
    result = {'pilot':dict(pilot)}
    seeds = {str(seed): records(seed) for seed in (31,37)}
    seeds['both'] = seeds['31'] + seeds['37']
    for seed,episodes in seeds.items():
        methods = ('suffix_fresh','on_demand')
        result[seed] = {m:metrics(episodes,m) for m in methods}
        # Extreme combinations across the three observed repeats, conditional
        # on these episodes. This is a sensitivity range, not a confidence interval.
        totals = {m:[[sum(t) for t in e['methods'][m]['times']] for e in episodes]
                  for m in methods}
        baseline, candidate = (totals[m] for m in methods)
        result[seed]['observed_ratio_range'] = [
            sum(map(min,candidate))/sum(map(max,baseline)),
            sum(map(max,candidate))/sum(map(min,baseline))]

    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--compact',action='store_true',help='summarize the three-policy storage comparison')
    if parser.parse_args().compact:
        cohorts = {str(seed):records(seed,'compact-cache') for seed in (31,37)}
        cohorts['both'] = cohorts['31'] + cohorts['37']
        methods = ('suffix_fresh','on_demand','on_demand_compact')
        result = {seed:{m:metrics(episodes,m) for m in methods} for seed,episodes in cohorts.items()}
    else:
        result = summary()
    print(json.dumps(result,indent=2))
