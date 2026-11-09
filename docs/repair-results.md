# First incremental repair implementation and results

**Historical per-snapshot evaluation.** The current
[event-based evaluation](event-evaluation.md) invokes both planners only on
prediction changes. In particular, the q=0 speedups below are cached-answer
reuse versus repeated baseline searches, not improvements from repairing a change.

The fixed-start repair prototype is implemented in `src/incremental.cpp`.
All 150 queries in the existing five-map q suite matched full replanning in
status and optimal arrival cost, and every returned path passed the separate
trajectory validator. None hit the expansion limit. This is a correctness and
measurement milestone: most changing-forecast cases are slower than full replanning.

## Implementation

The planner retains immutable reachable interval labels, their projection
witnesses, expansion ownership of CLOSED coverage, and dormant alternatives.
Each statically legal primitive has a cached record even when its projection
is empty. Records watch every swept cell, including the destination waiting
cell. On a normalized reservation change, affected records are previewed and
compared by their complete output/departure-domain fingerprint. Changed witnesses
are retired with their dependent expansions; lost CLOSED coverage wakes surviving
alternatives. New projections are installed only after retirement finishes.
Search then resumes and certifies the incumbent against the valid OPEN lower bound.

Root changes retire dependent support. Fixed-query changes reset the cache.
Identical effective forecasts return a certified previous result without search;
resource-limited searches preserve their frontier and remain inconclusive.
Compaction remaps live labels, owners and projections and rebuilds watches/OPEN
when at least a third of stored labels are dead. Concrete path reconstruction
uses retained departure domains and emits waits explicitly.

`src/model.hpp` contains the shared primitive tables and interval utilities.
The baseline search in `src/planner.cpp` remains independent; extracting the
shared model did not change its search logic. The Python finite time-expanded
oracle and trajectory validator remain separate from both search implementations.

## Validation

At this measurement milestone, the automated suite had 48 passing tests. Repair tests include 800 randomized
queries (80 sequences of ten forecasts) checked against both full replanning and
the independent oracle, plus targeted tests for empty projections, obstacle
insertion/removal, root replacement, invalid starts, one-tick boundaries,
waiting/departure changes, new shortcuts despite a feasible old path, dormant
alternative reactivation, compaction, moving initial velocity, nonzero start time,
query resets and resuming an expansion-limited search. Report tests validate
artifacts and reject resuming against changed inputs.

An AddressSanitizer/UndefinedBehaviorSanitizer build also matched baseline results
and validated paths on 165 queries. Leak detection was disabled because of the
execution environment; this is not a leak-check claim. These checks provide
empirical evidence. The subsequent [correctness audit](repair-correctness.md)
adds a mathematical proof for the finite model, executable invariant checks and
a stamp-rollover fix. These performance measurements and their source hashes
remain historical results for commit `9104921`.

## Five-map measurements

The input is the already saved `runs/q-comparison` suite: seed 7, density p=0.04,
q in {0, 0.1, 0.25, 0.5, 1}, horizon 40000, five updates at 100-tick spacing,
and the identical initial scenario for every q of a map. There are 25 sequences,
each with an initial query and five updates. Each comparison uses one warm-up
and three measured repetitions, with execution order alternated. Each repetition
starts fresh processes and replays the entire forecast sequence; incremental state
persists within that sequence. Both planners receive identical saved reservations.

The table reports full-replan time divided by repair time for updates only,
using sums of per-query median times. Above 1 is faster repair; below 1 is slower.
Initial plans are excluded from these ratios and cost approximately 1.3–1.65x
as much in the incremental planner because it builds the retained dependency graph.

| Map | q=0 | q=0.1 | q=0.25 | q=0.5 | q=1 |
| --- | ---: | ---: | ---: | ---: | ---: |
| empty_64_64 | 2.38x | 2.25x | 1.22x | 0.82x | 0.63x |
| room-64-64-16 | 41.59x | 0.47x | 0.44x | 0.41x | 0.40x |
| warehouse-10-20-10-2-2 | 8.37x | 0.52x | 0.45x | 0.40x | 0.38x |
| random128 | 20.69x | 0.44x | 0.40x | 0.40x | 0.38x |
| Sydney_2_256 | 11.76x | 0.39x | 0.40x | 0.40x | 0.39x |

All q=0 updates perform zero expansions and zero projections. Empty-map repair
also helps for q=0.1 and q=0.25. On the other maps, even q=0.1 invalidates enough
witness support that repair repeats most baseline expansions while paying for
retirement, index maintenance, extra retained labels and compaction. For example,
Sydney at q=0.1 performs 1,071,715 update expansions versus 1,102,360 for full
replanning; at q=1 these counts are 1,428,946 versus 1,428,966. The graph bookkeeping
therefore buys almost no search reduction on those runs. This explains the result
more directly than assuming q measures actual repair locality.

Times include input parsing/normalization, diff, maintenance, compaction, search
and reconstruction. `repair_us` includes compaction; `compaction_us` is a subset,
not an extra additive phase. Process startup, Python validation/serialization and
final disposal of the retained cache at process exit are outside per-query C++
times. These are update-query ratios, not end-to-end application speedups.
Physical peak memory/RSS is not measured. Stored-label/projection counters include
tombstones until compaction. Baseline projection counters include statically
rejected attempts; incremental counters count statically legal evaluations,
including repair previews, so those counters are not directly equivalent work units.

This is one exploratory seed and one machine. It establishes no general speedup
claim. The next performance experiment should isolate maintenance cost and actual
changed-cell/witness counts, then evaluate finer witness repair or an adaptive
full-restart policy without weakening the existing correctness checks.

## Reproduce and inspect

```sh
make test
python3 -m sipp_baseline compare-repair examples/corridor.json \
  --output runs/corridor-repair --repeats 3 --warmups 1 --oracle
python3 -m sipp_baseline compare-repair-suite runs/q-comparison \
  --output runs/repair-comparison-new --repeats 3 --warmups 1 --timeout 180
```

The current local [HTML report](../runs/repair-comparison/index.html) links raw CSV
results. Per-case manifests record canonical scenario, source and executable
hashes, compiler and flags; raw JSONL contains complete concrete paths and repair
counters. Generated runs are ignored by Git. A compact copy of the complete
150-query aggregate is tracked in [repair-results.json](repair-results.json).
The source scenarios remain in the original q suite and are referenced rather
than duplicated. The existing q-comparison viewer still displays its original
full-replan trajectories; the repair report is the comparison of both algorithms.
