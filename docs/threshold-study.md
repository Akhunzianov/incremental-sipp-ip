# Choosing the adaptive fallback thresholds

The adaptive executable accepts two optional integers, the minimum number of
changed free cells and the minimum percentage of free cells. Both comparisons
are inclusive. A zero minimum disables that guard. A prediction identical to
the cached forecast can reuse its search, including after a fallback. The
effective-change event filter runs before threshold selection.

The training grid crosses cell minima 0, 8, 16, 32 and 64 with percentages
0, 1, 2, 5, 10 and 20. Seeds 7 and 11 supply the training worlds. Seeds 19,
23 and 29 supply the evaluation worlds. Both stages use the five paper maps,
requested densities .02 and .04, broad and bounded-local changes, and repeated
forecast histories. Small engineered cases provide additional oracle checks.
Seeds 23 and 29 use newly generated worlds.

Every candidate compares the new snapshot with its own retained forecast. The
runner groups candidates that make identical decisions for the entire sequence
and measures one native execution per distinct sequence of decisions. It checks
the native branch choices against that grouping. Costs and paths are checked
on every repetition. One warm-up precedes three measured repetitions, with
rotating execution order. Native time includes parsing, choosing the strategy,
search and reconstruction. Each update contributes its median over repetitions.
The decision timer measures the query compatibility check and cell comparison.

The training objective is the geometric mean across upstream cases of each
case's total update time divided by full-replan update time. Cases without
replans have no ratio. Among candidates within 1% of the best upstream score,
we take the lowest engineered-case score, then the lowest upstream score.
Identical scores favor the percentage nearest 10, then the count nearest 32.
This tolerance and the weights are experiment design choices. Holdout timings
play no role in selecting the candidate. The p95 is the nearest-rank 95th
percentile of event medians and excludes initial search.

Run from the repository root after generating the source and local suites.

```sh
python3 -m sipp_baseline.thresholds runs/diverse-scenarios runs/local-scenarios \
  examples/diverse-pulses --seeds 7 11 --output runs/threshold-training.jsonl
python3 -m sipp_baseline.threshold_report runs/threshold-training.jsonl
```

The moving replay executes the baseline trajectory up to the next effective
revision. A stopped wait can be interrupted immediately. Moving and turning
primitives continue to their next lattice state. The runner checks their
remaining swept cells against every intervening forecast and reports a
committed-motion conflict if needed. Updates during a primitive are coalesced
at the decision boundary. Both planners receive the same actual position,
orientation, velocity and absolute tick. Each episode stops at arrival, conflict
or a query with no executable plan. This shared trajectory lets us compare
remaining optimal costs at identical states. The current cache requires the
same start state and tick, so advancing the robot requires a fresh search.

Training selected 0 cells and 5%. The upstream case time ratios to full
replanning at a zero cell minimum were as follows. Lower is faster.

| Minimum percentage | 0 | 1 | 2 | 5 | 10 | 20 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Training time ratio | 1.007 | 0.561 | 0.478 | 0.441 | 0.449 | 0.468 |

At 5%, minima from 0 through 64 were indistinguishable on the upstream training
worlds. Their engineered-case ratios were 1.081, 1.369, 1.598, 1.598 and 1.598
respectively. The prior 32-cell, 10% rule scored 0.449 upstream and 1.598
on engineered cases. Engineered maps are small enough for the cell floor to
suppress a fallback even when changes cover much of the map.

```sh
python3 -m sipp_baseline generate-scenarios --output runs/threshold-fresh \
  --seeds 23 29 --densities .02 .04 --no-engineered
python3 -m sipp_baseline generate-local-scenarios runs/threshold-fresh \
  --output runs/threshold-local
python3 -m sipp_baseline.thresholds runs/diverse-scenarios runs/local-scenarios \
  examples/diverse-pulses runs/threshold-fresh runs/threshold-local \
  --seeds 19 23 29 --pairs 32/10 0/5 --output runs/threshold-holdout.jsonl
python3 -m sipp_baseline.threshold_report runs/threshold-training.jsonl \
  --holdout runs/threshold-holdout.jsonl
python3 -m sipp_baseline.moving_replay runs/diverse-scenarios \
  --seed 19 --minimum 0 --percent 5 --output runs/threshold-moving.jsonl
```

## Evaluation results

All candidates agreed with full replanning on the 685 training queries in 288
cases. Both adaptive rules and persistent repair agreed with full replanning
on all 956 held-out queries in 404 cases. These include 530 upstream updates
and 22 engineered updates. All validated paths passed. For upstream updates:

| Method | Geometric mean of case time / full time | Median ms | p95 ms |
| --- | ---: | ---: | ---: |
| Full replan | 1.000 | 29.13 | 308.17 |
| Always repair | 0.679 | 33.15 | 686.74 |
| 32 cells and 10% | 0.493 | 16.52 | 250.91 |
| 5%, no cell minimum | 0.488 | 16.84 | 250.91 |

The selected rule reduced the equal-case time ratio by 1.0% over the old rule.
Its median update was slightly slower, and its p95 was identical. Per-seed
case ratios improved by 1.7% and 2.8% on seeds 19 and 29, and worsened by
1.5% on seed 23. Across the 14 small engineered cases, median update time fell
from 10.66 to 7.44 microseconds, and p95 from 19.39 to 14.12 microseconds.
Branch histories differed in 30 of 390 upstream cases and 11 of 14 engineered
cases. There were 200 fallbacks under the new rule and 150 under the old.

We adopted 5% without a cell minimum as the configurable default based on the
training objective and the small-case improvement. The data give little reason
to prefer it on paper-map latency alone. They do not establish a universal
optimum. Host timings include normal scheduling variation. Some generation
of fresh worlds ran concurrently with training. Held-out evaluation ran after
generation completed.

All 30 scattered, many-obstacle bounded-local cases selected repair under both
rules. In 15, adaptive repair was slower than a fresh search, and pure repair
was slower in those same 15. In that subset the median decision-time fraction
was 0.10%, and the median fraction of cached projections flagged for rechecking
was 3.57%. The decision timer is the final measured trial divided by the event's
median total time. These observations locate the overhead in executing repair
and searching again. Counting changed cells alone did not distinguish these
expensive cases.

## Moving-start pilot

Seed 19's 102 broad and engineered scenarios produced 248 planning queries
from a common executed trajectory. The planners agreed at every query. In
98 cases the robot reached the goal. Three stopped with no path from the new
state. One forecast conflicted with a committed motion before its next decision
boundary. All 146 post-initial queries reset the cache when the reference start
or its time advanced. Reusing search across these changes requires supporting
a new root in the retained search.

[Aggregate scores and profile breakdown](threshold-results.json).
[Training event medians](threshold-training.jsonl.gz),
[held-out event medians](threshold-holdout.jsonl.gz), and
[moving states and remaining costs](threshold-moving.jsonl.gz).
