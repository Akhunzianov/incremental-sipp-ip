# Findings from repair diagnostics

All 62 automated tests pass. The original event-triggered q sweep again matched
124/124 planning queries. The new 60 controlled two-query cases matched 120/120,
for **244 matched planning queries** total, with every returned path validated.
The studies ran sequentially, using three measured repetitions after one warm-up.
No finer repair or adaptive restart is included: this is an instrumented measurement
of the existing algorithm. Definitions and instrumentation limits are in
[diagnostics.md](diagnostics.md).

## Local single-obstacle changes

Each map has three seeds (7, 11, 19), four independently measured interventions
per seed, and an identical initial world/obstacle/boundary within that group.
All 15 common groups were available; no failed groups were dropped. Selection
used feasibility and geometry, never planner runtime or its path.

| Map | Faster updates | Median update speedup | Median initial + update speedup | Median labels retired |
| --- | ---: | ---: | ---: | ---: |
| empty_64_64 | 12/12 | 5.27x | 1.14x | 4.6% |
| room-64-64-16 | 7/12 | 2.82x | 1.11x | 13.1% |
| warehouse-10-20-10-2-2 | 12/12 | 7.88x | 1.20x | 0.8% |
| random128 | 12/12 | 9.37x | 1.25x | 3.5% |
| Sydney_2_256 | 12/12 | 10.41x | 1.25x | 0.9% |

Ratios are full-replan time / repair time; above one is faster repair.
Overall **55/60 updates** were faster, and **52/60 complete initial-plus-update
sequences** were faster. Two-query ratios include both native initial-query and
update costs, but retain the documented process/serialization/final-disposal
exclusions; they are not whole-application wall times.

**Important limitation:** all 60 old robot paths remained feasible and all 60
optimal costs stayed unchanged. Five returned trajectories changed shape despite
equal costs. These are benign effective-prediction changes, not forced-rerouting
cases. None occur wholly after the old arrival time, so their benign nature is
not explained by changes starting only after the planning task has ended.
An old feasible path alone would not establish current optimality: obstacle
changes could also open a shorter route. These cases therefore still exercise
certificate maintenance, but they do not test rebuilding an infeasible route.
The cohort demonstrates that reuse can help on this type of local change;
it does not establish rerouting performance, uniform obstacle sampling or a
general speedup. An on-path cohort that deliberately invalidates the old route
is needed before drawing those conclusions.

## Why q=0.1 is not necessarily local

The following are medians across actual update events for the existing seed-7
q=0.1 sequences. Fractions of cells refer to changed blocked-time sets, not
simultaneous obstacle density. Search ratio is repair expansions / full expansions.

| Map | Cells changed | Projections watched | Labels retired | Search ratio | Maintenance share |
| --- | ---: | ---: | ---: | ---: | ---: |
| empty_64_64 | 0.8% | 0.7% | 1.0% | 0.002 | 10.5% |
| room-64-64-16 | 15.1% | 33.0% | 99.5% | 0.993 | 35.3% |
| warehouse-10-20-10-2-2 | 32.3% | 49.2% | 74.6% | 0.729 | 49.2% |
| random128 | 27.4% | 49.3% | 89.8% | 0.883 | 47.3% |
| Sydney_2_256 | 34.7% | 63.6% | 98.6% | 0.981 | 46.1% |

The same nominal q produces very different effective changes across maps.
On rooms and Sydney, almost all useful exploration is repeated while maintenance
adds substantial cost. Improving only compaction cannot remove the repeated search.

## Concrete regression target

The worst controlled case is **room-64-64-16, seed 11, nearby-waypoint**.
It is only 0.56x as fast as full replanning (repair takes 1.80x as long).
Only 1.23% of free cells change reservations and
5.00% of cached projections are watched, yet
97.45% of old labels are withdrawn. The cascade
amplification is 34.2x and the search repeats
97.0% of baseline expansions, although the old
trajectory remains valid. This is a small direct change with a large dependency
cascade, and a concrete target for preserving unaffected witness intervals.

## Next implementation experiment

Preserve this case as a regression target. Prototype finer interval/witness
withdrawal against it, extending the existing invariants and oracle tests.
Separately, a pre-repair restart decision based on cheap affected-record counts
could protect against broad q-sweep changes. A fallback must include cache disposal
and decision overhead in its timings. Its threshold should be trained and tested
on separate seeds; three exploratory seeds do not justify a universal threshold.
Small watched fractions do not bound cascades: a threshold on that fraction alone
would miss the room-map regression, so fallback also needs a cascade/budget signal.
Keep benign, on-path and broad-change cohorts separate when assessing either
optimization.

## Artifacts

- [Controlled comparison](../runs/controlled-repair/index.html) and its per-case CSVs.
- [Profiled q sweep](../runs/repair-diagnostics/index.html).
- [Tracked aggregate, provenance and 60 case records](diagnostic-results.json).

To reproduce the worst group, run `controlled-repair` with
`--maps room-64-64-16 --seeds 11`; the `nearby-waypoint` case is the regression.
Use a new output directory. Source scenarios contain the full prediction tables
and the changed obstacle before/after; base worlds and manifests are retained.
The generated runs are ignored by Git, while this summary and its hashes are tracked.
