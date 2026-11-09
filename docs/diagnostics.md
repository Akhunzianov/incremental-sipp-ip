# Repair diagnostics and controlled changes

This stage adds measurements and isolated experiments. It does not change search,
projection, retirement or stopping decisions. Finer interval repair and adaptive
restarts are not implemented by this change.

## Metrics

`compare-repair` and `compare-repair-suite` now include these fields in each
`comparison.csv`, plus update-event medians in `summary.json`. Initial plans
remain separate; unchanged predictions are skipped for both planners.

| Metric | Meaning |
| --- | --- |
| `reservation_changed_cells` | Free cells whose normalized blocked-time sets differ |
| `changed_cell_ticks` | Exact symmetric difference of blocked `(cell,tick)` pairs |
| `change_first_tick`, `change_last_tick` | Earliest/latest differing occupancy tick, potentially later than prediction arrival |
| `changed_cell_fraction` | Changed free cells / all free cells |
| `changed_cell_tick_fraction` | Changed `(cell,tick)` pairs / `(free_cells * (horizon+1))` |
| `suspect_projection_fraction` | Records visited by cell watches / live cached records before repair |
| `retired_label_fraction` | Old raw labels withdrawn, including descendants / live labels before repair |
| `retired_owner_fraction` | Withdrawn expansion pieces / live expansion pieces before repair |
| `retained_projection_fraction` | Fraction of old cached records whose source expansion survives |
| `retained_coverage_fraction` | Fraction of old expanded configuration/tick coverage surviving retirement |
| `direct_invalidated_labels` | Unique old outputs of changed records, plus an invalidated root |
| `cascade_amplification` | All retired labels / directly invalidated labels |
| `search_expansion_ratio` | New repair expansions / full-baseline expansions for the same query |
| `maintenance_time_fraction` | Repair maintenance / total native query time |

Undefined ratios are null, not zero. Coverage counts represented states, not saved
CPU work; wide intervals can be cheap to expand. The search ratio is separate and
can exceed one. A direct seed is counted even if another seed's cascade also
reaches it. Baseline and repair projection-attempt counters are different work
units because only the baseline includes statically rejected attempts.

Live counts are maintained incrementally, not inferred from storage containing
tombstones. The verification build recomputes and checks them from the stores;
tests check creation/withdrawal accounting across compaction and repeated updates.
New counters and phase-boundary clocks add instrumentation overhead, included in
reported native timings. The search decisions themselves are unchanged.

## Phase times

| Field | Work |
| --- | --- |
| `recheck_us` | Preview suspect projections and compare fingerprints |
| `retirement_us` | Withdraw root/output witnesses and dependent branches |
| `coverage_restore_us` | Goal rescan, CLOSED rebuilding and dormant reactivation |
| `installation_us` | Install replacement outputs and construct a new root |
| `compaction_us` | Remap stores and rebuild indexes/OPEN |
| `repair_us` | Whole transaction, including these phases, watches and compaction decision |
| `maintenance_us` | Diff, repair and table disposal; construction on initial queries |
| `search_us` | Resumed search after repair |

These are nested: do not add repair to its subphases or maintenance to repair.
CSV times are per-query medians; sums of component medians need not equal a
total's median. Native times exclude Python change-size analysis, serialization,
process startup, validation and final retained-cache disposal. Physical peak RSS
is not measured. Verification builds are for correctness, not performance.

## Controlled protocol

```sh
python3 -m sipp_baseline controlled-repair --output runs/controlled-repair-new \
  --seeds 7 11 19 --density .04 --repeats 3 --warmups 1
python3 -m sipp_baseline compare-repair-suite runs/q-comparison \
  --output runs/repair-diagnostics-new --repeats 3 --warmups 1 --timeout 180
```

For each map/seed, generate an unmodified upstream initial world once, then four
separately executed two-prediction sequences sharing one changed obstacle and one future
moving-edge boundary:

1. **pause-10:** insert a ten-tick pause before that edge.
2. **accelerate-one-edge:** shorten that edge by ten ticks.
3. **decelerate-one-edge:** lengthen that edge by ten ticks.
4. **nearby-waypoint:** replace that edge with two edges via an adjacent free
   waypoint, each retaining the old edge duration.

Later arrival times shift as required, but other edge durations remain unchanged.
Thus a one-edge intervention can change reservations along a long future route;
it does not imply a one-cell effect. The waypoint can shift times more than ten
ticks, so the measured change sizes matter. Speed variants perturb discrete
edge travel durations; they do not assert a continuous acceleration profile.

Other obstacles, original starts/goals, source extras and the observed/in-flight
prefix are preserved. Default revision time is tick 100. Select edges of duration
20–90 so both speed directions stay within 10–100 ticks. Waypoints use the original
eight-neighbor convention. Empty-map prioritized cases reject obstacle conflicts;
independent-map overlaps remain permitted, matching their source policy.

Selection uses a deterministic shuffled obstacle order and first eligible future
moving edge. It selects the first common four-mode group that is feasible and
changes effective reservations. It never uses the robot's planned route, search
counters or planner speed. Unavailable map/seed groups are logged rather than
forced or repaired by changing other obstacles. This feasibility selection is not
uniform sampling of all obstacles. Three seeds are exploratory. Forced cases
have no q parameter.

Each sequence starts fresh processes, alternates planner execution order, and has
one warm-up and three measured repetitions. The repair cache persists from the
initial to changed query. All paths/status/cost pairs are checked; resource limits
are inconclusive. Small controlled fixtures also use the independent oracle.

`controlled-suite.json` records settings, generator hashes, unavailable groups and
comparisons. Each map/seed retains `base.json`; each intervention saves
`scenario.json` with the changed obstacle before/after and a base hash/reference.
Its `comparison` directory contains normal manifests, concrete paths and CSVs.
Top-level `diagnostics.csv` and `index.html` compare update events. The q sweep
overview and CSVs expose the same diagnostic fields.

See [the measured findings](diagnostic-findings.md) for the three-seed results,
the distinction between benign updates and forced rerouting, and a concrete room
map case with a large invalidation cascade.
