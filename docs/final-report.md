# Incremental SIPP-IP under changing obstacle predictions

Adaptive repair at a fixed start took **0.488× the full-replan update time** by the held-out geometric mean of per-case ratios. With the robot moving, compact on-demand reuse had **3.7% lower summed episode time** than suffix certification followed by fresh search on 450 episodes from five new seeds. It used **32.6% higher peak memory**. All 1,129 final decision results agreed with their full-replan reference.

## Research question

A robot has an earliest-arrival plan and receives a revised obstacle forecast. How much previous search can it use while still returning the earliest feasible arrival? We studied this first at a fixed start configuration and tick, the task posed in the initial project presentation, then while the robot executes its plan. The reference for each decision is Safe Interval Path Planning with Interval Projection (SIPP-IP) run from scratch on the same state and forecast. The repository preserves the upstream implementation, generation code and sample instances. [Upstream provenance](../vendor/sipp-ip/PROVENANCE.md)

## Model and trigger

A configuration specifies a cell, heading and velocity. Time advances in 0.1-second ticks to a finite horizon. The robot can accelerate, cruise, brake and turn using tabulated swept-cell motions. Only a stopped robot can wait. A forecast specifies closed intervals of occupancy. A search label covers times at which the robot can reach one configuration, with enough information to reconstruct a path to each time.

The evaluator always solves the initial query. After that it normalizes and compares occupied cell-time intervals. An update to that union triggers a decision, even if the old path still looks safe. A duplicate prediction or an unsuccessful proposed obstacle change adds no planning query. In the moving experiment, a revision during a committed motion is handled at the next decision boundary after checking intervening swept cells. A conflict before that boundary ends the episode. [Model](model.md) · [Event evaluation](event-evaluation.md)

## Fixed-start repair

Each expansion records its source interval, every statically legal outgoing action, and the feasible departure and arrival intervals for that action. Even an action with no feasible departure keeps a record. A change to any cell in an action’s footprint can therefore reveal a newly open route.

On an update the algorithm reprojects affected actions. It keeps unchanged results, retires invalidated witnesses and their dependent expansions, updates CLOSED to contain only intervals still owned by live expansions, and requeues live intervals that have lost coverage. The search then continues until its frontier lower bound certifies its best reachable goal. The adaptive policy chooses a fresh solve when at least 5% of free cells have changed reservation intervals. This threshold was selected on training worlds. [Repair design](repair-design.md) · [Threshold selection](threshold-study.md)

### Worked example

Suppose a moving robot can reach a source cell at any tick in [10,20]. A cruise takes five ticks and touches the destination throughout offsets [0,5]. If the destination is blocked at ticks [10,18], departure ticks [5,18] collide. Intersecting with the reachable source leaves [19,20], giving arrivals [24,25]. When the forecast removes the blockage, the departures expand to [10,20] and the earliest arrival becomes 15. The previous arrival at 24 is still feasible. Rechecking the outgoing action is necessary to recover the earlier route. The moving source interval represents different feasible arrivals at the source; it grants no permission to wait while moving.

## Moving-start policy

If the robot has followed the previous optimal path to the decision state, the planner first tries to certify the remaining path. It checks suffix feasibility and whether the new forecast opened any previously blocked cell-time before the old arrival. When no earlier opportunity has opened, an earlier feasible suffix would also have improved the old optimum, so the validated suffix remains optimal. Otherwise the planner searches from the robot’s actual state and tick.

We compare two ways to perform that search. **Suffix + fresh** retains only the certificate information and runs ordinary SIPP-IP on a miss. **Compact reuse** additionally indexes the outgoing motions from the preceding search. It considers an old expansion only after the current search reaches a configuration with a departure interval contained in the old one. If the map, horizon and swept-cell reservation checks pass, it clips the stored departure intervals and attaches successors to a current parent. The four stored integers are the action, two departure bounds and waiting endpoint. [Moving-start implementation and prior experiments](on-demand-reuse.md)

## Correctness

For a motion touching a cell at relative ticks [f,l], occupancy at [A,B] forbids exactly the departures in [A−l,B−f]. Subtracting these sets over every swept cell produces the exact feasible successors. For fixed-start repair, live labels have witnesses from the root, live expansions account for every tick marked CLOSED, and OPEN covers the remaining reachable work represented by live labels. Rechecking dependencies, including empty projections, and reopening lost coverage preserve these invariants. Positive-duration actions and the finite horizon bound the search. With an admissible lower bound, termination certifies the earliest feasible arrival or exhaustion of all paths.

For a moved start the planner establishes reachability anew. Reusing a projection on a contained source interval with identical touched reservations produces exactly the same clipped departures as recomputation. Stopped children keep the endpoint of the same safe waiting interval. These arguments concern the current forecast in the declared discrete model, with sufficient search resources. An expansion cutoff is inconclusive. They make no guarantee against a future forecast revision. The proof is mathematical; independent tick-expanded Dijkstra tests on small worlds and concrete path validation check the implementation. [Full proof and test evidence](repair-correctness.md)

## Fixed-start results

Training used seeds 7 and 11. On seeds 19, 23 and 29, all compared policies agreed with full replanning on 956 queries in 404 cases. On the upstream-derived cases, the geometric mean of per-case update-time ratios was **0.488** for adaptive repair and **0.679** for always repairing. Median update time was 16.84 ms for adaptive repair versus 29.13 ms for fresh search. Their p95 values were 250.91 and 308.17 ms. Initial solves are excluded from these update comparisons. [Fixed-start measurements](threshold-study.md)

## Final moving-start study

The planner was frozen at commit `aad27b9`, and the protocol was committed before generation. The five new seeds were 1009, 1013, 1019, 1021 and 1031. For each seed we used all five paper maps, two requested densities (p = 0.02 and 0.04), and nine change patterns. The initial obstacle worlds follow the upstream generator. Future revisions may add a pause, change speed or introduce a waypoint. The nine patterns vary the requested batch size, spatial distribution and revision history. Actual changes can be fewer than requested. These controlled batches are distinct from the earlier probabilistic generator, in which q denotes the probability of attempting a change per obstacle per revision. [Frozen protocol](final-protocol.md) · [Scenario construction](diverse-scenarios.md)

Full replanning drives the executed trajectory. Both policies receive identical decisions. We check the archived status and arrival tick, validate every returned path, and check that both implementations return the same path and expansion count on every trial. Each episode runs in one native process per policy with rotating order, one warm-up and three measured trials. The primary number sums each episode’s median native planning time, including the initial search. Process wall time includes launch, communication and final teardown. The update p95 is the nearest-rank percentile of per-update medians. Peak RSS is the largest process high-water mark. Timings exclude scenario generation. The fixed-start geometric mean and the moving-start summed episode time answer different questions.

The robot reached the goal in all 450 scheduled episodes. Across 1,129 planning decisions, both methods matched the reference status and earliest arrival and returned identical paths and expansion counts. Evidence about no-path behavior comes from the earlier engineered cases and small-world oracle tests. Both certified 56 of 679 post-initial updates. Compact reuse answered 20,004,133 of 43,434,775 expansion lookups (46.1%).

| Across all episodes | Suffix + fresh | Compact reuse |
| --- | ---: | ---: |
| Summed episode time (s) | 89.28 | 85.95 |
| Summed process wall time (s) | 90.64 | 87.46 |
| Initial queries (s) | 38.28 | 40.58 |
| Post-initial queries (s) | 51.02 | 45.39 |
| p95 update (ms) | 418.01 | 333.15 |
| Peak memory (MiB) | 149.79 | 198.54 |

Initial and post-initial rows sum separate query medians. The primary endpoint takes the median after summing the queries within each trial, so those rows need not add exactly to the episode total.

| Seed | Episodes | Fresh (s) | Compact (s) | Compact time change |
| --- | ---: | ---: | ---: | ---: |
| 1009 | 90 | 14.51 | 13.95 | -3.9% |
| 1013 | 90 | 19.25 | 18.48 | -4.0% |
| 1019 | 90 | 20.28 | 19.60 | -3.4% |
| 1021 | 90 | 18.64 | 17.96 | -3.7% |
| 1031 | 90 | 16.58 | 15.96 | -3.8% |

| Map | Episodes | Fresh (s) | Compact (s) | Compact time change |
| --- | ---: | ---: | ---: | ---: |
| empty_64_64 | 90 | 0.72 | 0.69 | -4.2% |
| room-64-64-16 | 90 | 4.62 | 4.44 | -3.8% |
| warehouse-10-20-10-2-2 | 90 | 3.87 | 3.78 | -2.2% |
| random128 | 90 | 14.82 | 14.26 | -3.8% |
| Sydney_2_256 | 90 | 65.24 | 62.77 | -3.8% |

| Post-initial certificate misses | Episodes | Fresh (s) | Compact (s) | Compact time change |
| --- | ---: | ---: | ---: | ---: |
| 0 | 72 | 4.74 | 5.02 | +6.0% |
| 1 | 280 | 49.66 | 48.13 | -3.1% |
| 2 | 1 | 0.01 | 0.01 | -15.4% |
| 3 | 47 | 15.14 | 11.35 | -25.1% |
| 4 | 50 | 19.71 | 21.44 | +8.7% |

## Interpretation

The three whole-suite trial totals ranged from 89.12 to 89.57 s for suffix-plus-fresh and 86.01 to 86.11 s for compact reuse. The largest contributor, Sydney_2_256, accounted for 73.1% of suffix-plus-fresh episode time. The pooled result weights expensive episodes more heavily than an equal-map mean.

Across the five new seeds, compact reuse reduced **summed episode time by 3.7%** and had lower totals on **5 of 5 seeds**. Its p95 update latency was 20.3% lower and its peak process memory was 32.6% higher. The frozen compact implementation pays its recording cost on the initial solve, including episodes with no subsequent search. Later searches can recover that cost when they reach old expansion domains.

A single miss was enough for an aggregate 3.1% saving in its 280 episodes. In the 47 three-miss episodes, all from the clustered repeated-change profile, 90.6% of expansion lookups hit and episode time fell 25.1%. In the 50 four-miss episodes, all from the widely scattered alternating-change profile, only 10.4% hit and time rose 8.7%. The two-miss group contains only one episode. This comparison groups episodes after execution. The number of misses, map, graph size and ease of reuse can vary together, so the observed grouping does not establish a universal break-even rule.

Fixed-start adaptive repair remains the clearest result for the original project question. Use the fixed-start rule when the start configuration and tick stay fixed. For a moving robot, suffix-plus-fresh is the lower-storage policy; compact reuse is available for workloads where its observed timing and memory tradeoff is appropriate. The five seeds extend the sample on the same maps and scenario generator. They do not cover unseen map families, continuous dynamics, prediction accuracy in deployment, or different controller choices under tied optimal paths.

## Reproduction and evidence

The final study ran on an AMD Ryzen 9 9900X under Linux x86-64 using GCC 13.3.0. The build, generation and replay commands are in the [frozen protocol](final-protocol.md). The [aggregate JSON](final-summary.json) includes all three trial totals and per-group metrics. The [suite manifest](final-suite.json.gz) records the initial-world settings and scenario hashes.

| Seed | Decision states and reference costs | Paired time and RSS records |
| --- | --- | --- |
| 1009 | [Decisions](final-decisions-1009.jsonl.gz) | [Trials](final-trials-1009.jsonl.gz) |
| 1013 | [Decisions](final-decisions-1013.jsonl.gz) | [Trials](final-trials-1013.jsonl.gz) |
| 1019 | [Decisions](final-decisions-1019.jsonl.gz) | [Trials](final-trials-1019.jsonl.gz) |
| 1021 | [Decisions](final-decisions-1021.jsonl.gz) | [Trials](final-trials-1021.jsonl.gz) |
| 1031 | [Decisions](final-decisions-1031.jsonl.gz) | [Trials](final-trials-1031.jsonl.gz) |
