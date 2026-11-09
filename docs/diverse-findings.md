# Multi-obstacle experiment findings

The expanded suite completed on 2026-11-09. All **1,026 paired planning queries**
matched in feasibility and optimal cost. No timeout, expansion cutoff or path
validation failure occurred. The native baseline and repair algorithm are unchanged
from commit `8f67756`; this experiment expands the tests and measurement coverage.

## Coverage

| Family | Cases | Paired queries | Actual replans |
| --- | ---: | ---: | ---: |
| Upstream-derived, nine broad profiles | 270 | 678 | 408 |
| Upstream-derived, four bounded-local profiles | 120 | 240 | 120 |
| Six engineered outcome families | 36 | 96 | 60 |
| Targeted bounded-local pulses | 6 | 12 | 6 |
| Total | 432 | 1,026 | 594 |

The upstream cases use all five paper maps, three seeds (7/11/19), and two
requested initial densities (p=.02/.04). There are 30 shared initial worlds.
The synthetic cases have their own layouts/densities and are reported separately.
These are forced change profiles, with no q parameter.

Of 1,038 received snapshots, 432 initialize a sequence, 594 change effective
reservations, and 12 leave them unchanged. Those 12 invoke neither planner.
**556 replans change multiple obstacle plans**, with a maximum batch of **1,925**.
Actual invoked batch counts are:

| Changed plans | Events |
| --- | ---: |
| 1 | 38 |
| 2–4 | 256 |
| 5–25 | 81 |
| 26+ | 219 |

Thirteen upstream events actually change every obstacle; an all-eligible request
does not always do so. Proposal rejection/inactivity counts and applied modes are
retained. This prevents interpreting a requested large batch as an actual one.

## Changes now affect the robot's solution

The previous single-obstacle experiment left every old path feasible and optimal.
This broader experiment has **162 invalidated old paths**, including 126 in the
large upstream cases. The disjoint transition categories are:

| Observed result after an actual change | Events |
| --- | ---: |
| Old path remains optimal | 394 |
| Shorter optimal path | 62 |
| Old path invalid, new solution at equal/higher cost | 102 |
| No path within the horizon | 18 |
| Recovery from no path | 18 |

Some shorter-path events also invalidate the previous route, so the 162 invalidation
flags overlap the category counts. The 18 no-path transitions and 18 recoveries
are from constructive engineered cases. All **108 queries in the 42 engineered
cases** also match the independent time-expanded oracle.

Every random bounded-local update happened to leave the old path optimal. This
cohort tests locality and cache reuse, rather than difficult route changes. The
six targeted bounded pulses close that gap for short-lived, on-path changes:
all six invalidate the old path and require additional waiting. The geometric
detour templates separately require a different route.

The locality control is observable: across the 30 worlds, median normalized
changed-cell diameters for few-cluster/few-spread are 0.062/0.864; for many they
are 0.423/0.933. Actor clustering in the broad profiles alone does not guarantee
local changed reservations, because entire future tails may shift or reroute.

## Performance on the preselected subset

Coverage uses one replay without warm-up. A separate **79-case, 189-query** subset
uses seed 7, requested upstream p=.04, three repetitions and one warm-up. No case
was selected by its speed. For each sequence, speedup is the sum of baseline
per-forecast median native times divided by the corresponding repair sum,
excluding initial search. The table reports medians of those case ratios;
values above 1 favor repair. Histories aggregate their actual update queries.

| Upstream profile | Cases with replans | Median speedup | Repair faster |
| --- | ---: | ---: | ---: |
| One, broad change | 4 | 7.75× | 3/4 |
| Few clustered, broad | 4 | 2.92× | 3/4 |
| Few spread, broad | 5 | 3.18× | 4/5 |
| Many clustered, broad | 5 | 0.44× | 0/5 |
| Many spread, broad | 5 | 0.42× | 1/5 |
| All eligible, broad | 5 | 0.44× | 1/5 |
| Many spread, far future | 5 | 0.46× | 1/5 |
| Few clustered, repeated | 5 | 2.42× | 4/5 |
| Many spread, alternating | 5 | 0.43× | 0/5 |
| Few clustered, bounded local | 5 | 11.08× | 5/5 |
| Few spread, bounded local | 5 | 11.03× | 5/5 |
| Many clustered, bounded local | 5 | 2.37× | 4/5 |
| Many spread, bounded local | 5 | 2.48× | 5/5 |

Repair benefits from benign small changes. Broad batches often cost roughly
2.2–2.4 times a fresh search in this subset. This supports measuring the actual
reservation footprint and invalidation work rather than using agent count alone
to predict the benefit. Even changes after the old arrival can impose overhead
on the retained search cache.

Synthetic timings remain separate: their median case ratios range from 0.49–0.65×
for the forced outcome families, 0.54× for bounded pulses, and 1.83× for benign
changes. These tiny cases are useful correctness regressions; constant overhead
dominates them. Locality therefore does not by itself guarantee a speedup.

These are exploratory measurements with five worlds per upstream profile and
three timing repetitions, not a statistical scaling study. Native time excludes
shared event selection, serialization, process startup, validation and final cache
disposal. The robot still uses a fixed start/time during prediction replay;
these are not closed-loop execution trials. No aggregate speedup mixes the
engineered and upstream tiers.

## Artifacts and next step

- [Overview, reports and 14 paired animation examples](../runs/scenario-overview/index.html).
- [Compact tracked results, fingerprints and exact measurement configuration](diverse-results.json).
- [Generation/audit/evaluation protocol and reproduction commands](diverse-scenarios.md).
- [Versioned short-lived pulse fixtures](../examples/diverse-pulses/README.md).

Generated large inputs and raw results stay under ignored `runs/`. The compact
results retain all 432 canonical input fingerprints and each measured case's
update times/expansions. Generator, native source, binary and driver hashes were
checked against the recorded manifests. The upstream empty-map worlds retain
some inherited obstacle overlaps; the audit rejects new overlap windows and
records inherited ones. Other maps retain their original overlap policy.

The next implementation target is a conservative choice between repair and a
fresh search for expensive updates, using measured change/invalidation signals.
It must preserve the same exact-cost checks and remain fast on benign local
changes. This suite supplies both controls and difficult outcomes for that work;
it is a coverage matrix rather than a full factorial experiment.
