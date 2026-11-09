# Evaluation triggered by prediction changes

Both planners now receive an initial planning query, then a new query only when
an arriving prediction changes the effective blocked-cell/time reservations.
This policy is `effective-prediction-change-v1` and is the default for standalone
baseline benchmarks and paired repair comparisons.

## Trigger and measurements

A shared selector normalizes each free cell's closed integer reservation union.
It merges overlapping/adjacent intervals and ignores ordering, duplicates,
metadata and reservations on permanently blocked static cells. It compares
consecutive predictions, not a global set: A → B → A causes two replans.
Rejected proposals or accepted changes that leave effective occupancy unchanged
cause no planner call. A change anywhere in the effective prediction triggers
both planners, even if the old robot trajectory is still feasible.

The generator retains its configured prediction-revision opportunities because q
is defined per obstacle per revision. Their timestamps do not schedule planning.
The selector also accepts irregularly spaced predictions. Planning is triggered
when the revised prediction arrives, rather than when a future obstacle movement
in that prediction will physically take effect. This remains an offline replay
from the fixed reference robot state; the robot does not advance between queries.

At each trigger the baseline starts a fresh search, while repair retains its
previous search state. The change selector runs once before either planner and
is outside the per-query native timings. No-replan intervals still have ingestion
and comparison costs; this report does not claim zero end-to-end cost for them.
Initial-plan overhead is separate from update speedup. At q=0 there are no
replanning samples and the update speedup is undefined, displayed as a dash.

If effective reservations are unchanged, the finite planning graph is unchanged:
a previously certified optimum remains valid and optimal. A resource-limited
result remains inconclusive and is never promoted to a certificate by skipping.
Independent paper instances are separate problems and are always planned.
The low-level solver API still accepts explicitly repeated queries so unit tests
can check cache reuse, idempotence and interrupted-search resumption; these are
not the performance-evaluation trigger policy.

## Saved outputs and replay

Each case has `events.json` listing every received forecast, its revision tick,
whether planning was invoked, the reason, and the source of a reused plan.
Paired `baseline.jsonl`, `incremental.jsonl` and `comparison.csv` contain only
actual planning queries. Their aggregates exclude skipped observations.
Manifests record the policy, received/skipped/query counts, and Python-driver,
C++ source, executable and scenario hashes. Resume rejects old policies or
changed drivers so old per-snapshot timings cannot silently be reused.

Standalone baseline exports retain every snapshot for trajectory visualization.
Skipped observations are explicitly tagged `planner_invoked=false`, refer to the
previous result with `source_forecast_id`, and have zero planner-work placeholders
and zero measured samples. They are excluded from planning aggregates. Viewers
label them “skipped” instead of presenting them as fast replanning measurements.
Original scenario data and historical run directories are preserved.

## Rerun of the five-map suite

The same 25 saved map/q sequences contain 150 received predictions. Under the
new trigger they produce **25 initial queries, 99 replanning events, and 26
skipped predictions**. All **124 actual planning queries matched** in feasibility
and optimal arrival cost, and their returned trajectories were validated.

All five q=0 sequences contain an initial plan and zero replans. Empty-map q=0.1
also skips one unchanged revision, leaving four replans; the other nonzero-q
sequences each have five. The automated suite passes **57 tests**, including
normalization, irregular prediction times, A → B → A, identical predictions,
both planners receiving exactly the same filtered queries, independent instances,
viewer reuse and q=0 reporting without a speedup.

Update speedup below is full-replan time / repair time, using sums of per-query
median times over three repetitions after one warm-up. Above 1 means faster
repair. These remain exploratory one-seed measurements. The filtering change
does not resolve the algorithm's performance problem: most changing predictions
still invalidate enough work that conservative repair is slower than full search.

| Map | q=0 | q=0.1 | q=0.25 | q=0.5 | q=1 |
| --- | ---: | ---: | ---: | ---: | ---: |
| empty_64_64 | — | 2.22x | 1.22x | 0.80x | 0.63x |
| room-64-64-16 | — | 0.44x | 0.45x | 0.43x | 0.41x |
| warehouse-10-20-10-2-2 | — | 0.52x | 0.44x | 0.39x | 0.41x |
| random128 | — | 0.47x | 0.41x | 0.39x | 0.38x |
| Sydney_2_256 | — | 0.39x | 0.39x | 0.40x | 0.40x |

The [current HTML report](../runs/repair-event-comparison/index.html) shows received,
skipped and replanning counts alongside timings. A compact aggregate with hashes
is tracked in [event-evaluation-results.json](event-evaluation-results.json).
The older [per-snapshot results](repair-results.md), including their q=0 cache-hit
speedups, are historical measurements and should not be used for this policy.

```sh
make test
python3 -m sipp_baseline compare-repair-suite runs/q-comparison \
  --output runs/repair-event-comparison-new --repeats 3 --warmups 1 --timeout 180
```

Native query timings include parsing/normalization, diff, repair, compaction,
search and reconstruction, but exclude Python event selection/serialization,
process startup, validation and final retained-cache disposal at process exit.
These are planning-query measurements rather than application-wide speedups.
