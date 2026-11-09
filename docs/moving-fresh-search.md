# Fresh search after a moving-start certificate miss

The experimental native flag `--suffix-fresh` uses ordinary SIPP-IP for the
initial query and every certificate miss. On a solve it saves the optimum,
the reconstructed steps and the forecast against which those steps were solved.
A certificate hit returns the trimmed path and keeps the original certificate
anchor. An unsuccessful fresh query clears the saved solution. The check uses
the same state, time, monotonicity and swept-motion feasibility rules as the
existing adaptive implementation. This policy stores a path and the reservation
snapshot between queries. No search graph is needed between queries.

Run an episode with the policy using the existing moving replay command and
`--suffix-fresh`. For the timing comparison use the registered pilot decisions:

```sh
for seed in 19 23 29; do
  python3 -m sipp_baseline.moving_compare --seed "$seed" --output "runs/fresh-policy-$seed.jsonl"
done
python3 -m sipp_baseline.moving_compare --seed 19 --profile --output runs/fresh-phases-19.jsonl
```

Each variant runs through an entire episode in one native process and makes its
own certificate decisions. The archived baseline-controlled executed states and
revision ticks give all four variants identical queries. Each reported cost is
checked against the archived full-replan answer and each returned path is
validated. This measures cache effects across a common trajectory. A controller
that executes its own tie-breaking choices can encounter different later states.

The timing runs rotate method order, with one warm-up and three measured
repetitions. Update median and nearest-rank p95 use the median of each update.
Episode time sums all native queries including the initial solve in each trial,
then takes the median of the three episode totals. These times exclude process
startup, serialization and final disposal of retained state after the last
answer. Peak RSS uses GNU time's process high-water mark, including native
allocations during setup and teardown.

The profiling run uses separate optimized binaries with nested exclusive
timers. It compares the same 130 seed-19 advanced-start queries where suffix
certification failed in the retained-search planners. The profiler measures
projection lookup, ordinary projection calculation, witness construction
and scheduling, expansion ownership/coverage/watch bookkeeping, heap operations
and old-search release. Other time includes input parsing, search control,
CLOSED queries and untimed work. Fresh SIPP-IP has no ownership ledger and
its CLOSED maintenance is included in other time. Clock reads on small
operations perturb the phase breakdown. Policy timings use the uninstrumented
binaries.

## Results

Across 282 episodes on seeds 19, 23 and 29, all 703 queries agreed on status
and optimal arrival with the full-replan reference. All returned paths passed
validation. Of 421 advanced-start updates the new policy certified 38 suffixes
and performed 383 fresh searches. The three suffix-capable policies obtained
the same certificate hit counts on each seed.

| Policy | Median update ms | p95 update ms | Median episode ms | Sum of episode times s | Peak MiB |
| --- | ---: | ---: | ---: | ---: | ---: |
| Full replan | 22.71 | 289.02 | 57.73 | 46.72 | 140.8 |
| Suffix check + fresh search | 21.07 | 283.70 | 54.39 | 45.86 | 145.6 |
| Suffix check + retained search | 32.28 | 485.71 | 85.26 | 74.41 | 349.4 |
| Suffix check + projection transfer | 34.75 | 464.29 | 86.41 | 73.75 | 533.1 |

Suffix checking with fresh search reduced summed episode time by 38.4% compared
with the retained-search implementation and by 1.8% compared with full replanning.
The latter difference is small relative to ordinary timing variation. There are
three seeds and three measured trials per episode. These results support using
the simpler policy for these moving trials. Fixed-start comparisons should
continue to use the existing adaptive planner.

## Where the moving search spent time

Exclusive phase times in seconds over the 130 seed-19 certificate misses:

| Phase | Retained search | Projection transfer | Full replan |
| --- | ---: | ---: | ---: |
| Projection lookup | 0.00 | 2.08 | 0.00 |
| Calculate projections | 5.16 | 2.96 | 5.13 |
| Create and schedule witnesses | 4.78 | 4.92 | 1.39 |
| Expansion owners, coverage and watches | 2.78 | 3.16 | 0.00 |
| Heap operations | 1.99 | 2.03 | 2.42 |
| Release old search storage | 2.44 | 2.55 | 0.24 |
| Other | 2.23 | 2.40 | 3.08 |

Transfer saved 2.19 s of projection calculation and spent 2.08 s on lookup.
Building witnesses and expansion records took 40.2% of transfer time, with
a further 12.7% spent releasing the preceding generation. These phases give
a concrete target for a future algorithm that can safely carry reachable
witnesses and their expansion coverage across a root change. The measured
benefit of carrying individual projections alone is too small to justify it
as the default on this workload.

[Aggregate and per-seed metrics](fresh-policy-results.json).
Raw native timing and memory records for
[seed 19](fresh-policy-19.jsonl.gz), [seed 23](fresh-policy-23.jsonl.gz)
and [seed 29](fresh-policy-29.jsonl.gz). [Exclusive phase records](fresh-policy-phases.jsonl.gz).
