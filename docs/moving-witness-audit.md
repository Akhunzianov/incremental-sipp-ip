# Can a moved robot reuse whole SIPP-IP expansions?

The experiment follows the robot through the five-map moving-start benchmark. At each effective prediction change we first try the existing optimal-suffix certificate. On a miss we ask which intervals from the preceding search we can still reach from the robot's actual state, and which of those the fresh planner spends time expanding.

## What counts as reusable

A label records a configuration (cell, orientation and velocity) and a reachable interval of ticks. An expansion records the specific subinterval on which the old search evaluated every legal motion primitive. Multiple labels can contain the same ticks. An old expansion qualifies only when **every tick in its domain is reachable from the new root** and **all its outgoing projections still agree**, including formerly empty actions and the waiting interval after braking.

The auditor starts with the new root and its legal waiting interval if stopped. It propagates newly reached ticks through intersecting old expansion domains at the same configuration, even when reached through a different parent. A motion touching a changed cell is reprojected under the new forecast. Where the projection differs, propagation uses only departures allowed under both forecasts and stops waiting at the earlier of the two waiting limits. A changed projection disqualifies its owner from whole-expansion reuse, but its surviving departures can still establish support downstream. Processing stops when the queue contains no newly reached ticks.

This gives a constructive reachability check. The root ticks are reachable by waiting. Each subsequent tick has a reachable departure, a legal motion and, for a stopped state, legal waiting until that tick. The finite horizon and propagation of newly added ticks ensure termination. The check counts the support that can be recovered through the recorded transitions. A fresh search may discover additional routes. Classifying a label as fully reachable also permits different witnesses to cover different parts of its interval. A production planner would need to preserve those witnesses to reconstruct paths.

## Decision rule and timing

Before testing the held-out seeds, we chose to proceed to an online implementation if the measured work available to save justified the cost of discovery. We replay each archived episode and time each actual expansion in ordinary fresh SIPP-IP. For every fresh expansion that overlaps any qualifying old interval, we credit the entire expansion body, including CLOSED maintenance, outgoing projections, child creation and heap pushes. Full coverage is reported separately. This credit is deliberately generous for partially covered expansions. Heap pops, later pruning and reconstruction fall outside that timer.

Discovery time includes audit storage setup, checking the new forecast and propagating reachable ticks. It excludes the subsequent classification/counting pass, old graph construction, construction of transferable path witnesses and eventual release. Timings are single-run instrumented measurements. For an end-to-end reference, we also sum the archived median native times for suffix-plus-fresh on exactly the same misses. Those measurements came from a separate run with three measured trials.

## Measurements

| Seed | Misses | Old labels fully / partly reachable | Old expansions fully / partly reachable | Old expansions eligible | Fresh expansions fully covered / with any overlap |
| --- | ---: | ---: | ---: | ---: | ---: |
| 19 | 130 | 64.2% / 29.5% | 44.8% / 47.7% | 37.5% | 34.0% / 37.5% |
| 23 | 127 | 69.1% / 26.0% | 53.9% / 40.2% | 44.4% | 42.5% / 45.8% |
| 29 | 126 | 63.6% / 30.7% | 42.8% / 50.3% | 34.8% | 32.3% / 35.5% |
| All | 383 | 65.8% / 28.6% | 47.5% / 45.8% | 39.2% | 36.5% / 39.9% |

| Seed | Discovery (s) | Credited expansion time (s) | Archived suffix-plus-fresh time on the misses (s) | Misses where credit exceeded discovery |
| --- | ---: | ---: | ---: | ---: |
| 19 | 21.99 | 2.02 | 9.11 | 0 |
| 23 | 26.46 | 2.44 | 9.27 | 0 |
| 29 | 19.53 | 1.62 | 7.85 | 1 |
| All | 67.99 | 6.07 | 26.23 | 1 |

Across all three seeds the archive contains 703 decisions. Of the 421 updates, 38 used a certified suffix. All decisions matched the archived status and cost. Percentages pool interval or expansion counts within each row. The first seed was used for development, with seeds 23 and 29 held out.

The one favorable update was the third warehouse update in seed 29’s few-obstacle, repeated-cluster case at density 0.04. All 1,473 fresh expansions were fully covered. Discovery took 0.712 ms against 0.774 ms of expansion credit. The additional classification pass brought the audit to 0.845 ms even in that case.

## Decision

Use the certified suffix when it applies and run fresh SIPP-IP on a moving-start miss. The eager graph traversal already costs more than solving the same misses from scratch. Adding a production implementation of whole-expansion transfer would also require constructing valid parent chains and exposing every unexplored exit to the search frontier. We stopped at the measurement gate. A future experiment could test demand-driven discovery restricted to states the new search actually visits. It would need its own cost and correctness measurements.

The existing moving-policy comparison on the same 282 episodes gives 45.86 s summed episode time, 283.7 ms p95 update latency, and 145.6 MiB peak RSS for suffix-plus-fresh. The corresponding full-replan measurements are 46.72 s, 289.0 ms, and 140.8 MiB. The difference in total time is small. The offline auditor holds both planners and produces no candidate-policy latency or memory estimate. [Paired policy benchmark](moving-fresh-search.md)

## Verification and reproduction

Each archived decision is checked for suffix hit/miss classification, feasibility status and absolute arrival tick against the recorded reference. Each new search also compares the fresh and retained planner answers. A separate regression uses independent tick-by-tick enumeration on 20 small updates to check every reported reachable tick, each eligible expansion's outgoing departures and stopped waiting limits, and the earliest arrival or failure. The benchmark measures reuse opportunities. It introduces no new search termination or pruning rule.

From the repository root, generate the scenario directories if needed, then run the audit and summarize its archives.

```sh
python3 -m sipp_baseline generate-scenarios --output runs/diverse-scenarios --seeds 19 --densities .02 .04
python3 -m sipp_baseline generate-scenarios --output runs/threshold-fresh --seeds 23 29 --densities .02 .04 --no-engineered
for seed in 19 23 29; do
  python3 -m sipp_baseline.witness_audit --seed "$seed"
done
python3 -m sipp_baseline.witness_audit --summary
make test
```

Per-episode records are archived for [seed 19](witness-audit-19.jsonl.gz), [seed 23](witness-audit-23.jsonl.gz) and [seed 29](witness-audit-29.jsonl.gz).
