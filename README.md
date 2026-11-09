# Incremental SIPP-IP research: full replanning and interval repair

Both fixed-start planners run initially, then **only when the effective prediction
changes**. The baseline constructs a fresh SIPP-IP search at each such event;
the incremental planner repairs saved interval witnesses and their dependencies.
Identical snapshots invoke neither planner. Both use the same saved forecasts
and the same event trigger, and return validated concrete timed trajectories.

The production planner is a C++17 adaptation of interval projection with the
authors' exact primitive tables. It is **not an unchanged upstream executable**;
its performance should be labeled `interval-projection-port-v1`. An unmodified,
pinned upstream copy and a differential adapter are included for verification.

Requirements: Python 3.10+, GNU g++ with C++17 support, and optionally GNU Make.
No downloaded Python packages, network access, or CMake required.

## Quick start

Run commands from this repository directory:

```sh
make test
make demo
```

Without Make:

```sh
python3 -m sipp_baseline build
python3 -m sipp_baseline build-incremental
python3 -m unittest discover -s tests -v
python3 -m sipp_baseline run examples/corridor.json --output runs/corridor --oracle
```

The corridor sequence must produce costs **100, 126, 100, no path, 100** ticks.
One tick is 0.1 seconds. `--oracle` also verifies feasibility and optimal cost
using an independent time-expanded Dijkstra; use it only on small cases.
Output paths must be new: existing runs are never silently overwritten.

## Compare incremental repair with full replanning

```sh
python3 -m sipp_baseline compare-repair examples/corridor.json \
  --output runs/corridor-repair --repeats 3 --warmups 1 --oracle
python3 -m sipp_baseline compare-repair-suite runs/q-comparison \
  --output runs/repair-comparison-new --repeats 3 --warmups 1 --timeout 180
```

The suite command replays the existing five-map q suite without regenerating or
copying its scenarios. Open the output `index.html` for the comparison table.
Its `events.json` ledger records every received prediction and whether it invoked
planning. The trigger compares normalized collision reservations, so formatting,
metadata and rejected proposals do not count as changes. At q=0 there is only an
initial plan: no replanning samples and no update-speedup ratio. Generation still
offers prediction revisions at its configured cadence; this does not schedule
planner calls. Arbitrary prediction arrival times are supported.
Each case contains raw `baseline.jsonl` and `incremental.jsonl`, `comparison.csv`,
`summary.json`, and a manifest with input, source and executable hashes. Every
returned trajectory is validated; status/cost disagreements stop the run and
write `mismatch.json`. Resource-limited results are inconclusive. `--resume`
reuses completed cases only when their inputs and planner hashes still match.

The incremental executable accepts the same line protocol as the baseline and
retains state between queries in one process. Changing the fixed query resets
its cache. The Python API is `sipp_baseline.repair.solve_incremental(scenario)`.

See [the current event-based evaluation](docs/event-evaluation.md).
The [older per-snapshot measurements](docs/repair-results.md) are retained as
historical results; their q=0 speedups compare cached reuse against unnecessary
baseline restarts and are not evidence of faster repair.

[The correctness proof](docs/repair-correctness.md) establishes soundness,
termination, completeness and earliest-arrival optimality in the fixed-start,
finite discrete model, assuming sufficient resources. It also documents the
stamp-rollover bug found and fixed during the audit. `make test` includes an
expensive verification build that checks the proof invariants; release builds
omit these audits. The proof is mathematical, not machine-checked verification.

## Diagnose repair and test isolated changes

```sh
python3 -m sipp_baseline controlled-repair --output runs/controlled-repair-new \
  --seeds 7 11 19 --repeats 3 --warmups 1
```

This tests one obstacle's short pause, one-edge speed increase/decrease and nearby
waypoint detour. Four variants share an upstream initial world and future boundary
for each map/seed; other obstacles stay fixed. Normal repair comparisons now
report live-cache survival, direct versus cascading invalidation, exact change
size and repair-phase timings. See [the diagnostic definitions and protocol](docs/diagnostics.md)
and [the measured findings and regression target](docs/diagnostic-findings.md).

## Broader multi-obstacle scenario suite

```sh
python3 -m sipp_baseline generate-scenarios --output runs/diverse-scenarios-new
python3 -m sipp_baseline compare-scenarios runs/diverse-scenarios-new \
  --output runs/diverse-coverage-new
python3 -m sipp_baseline generate-local-scenarios runs/diverse-scenarios-new \
  --output runs/local-scenarios-new
python3 -m sipp_baseline compare-scenarios runs/local-scenarios-new \
  --output runs/local-coverage-new
python3 -m sipp_baseline compare-scenarios examples/diverse-pulses \
  --output runs/pulse-coverage-new
```

Defaults cover five maps, three seeds, two densities, and one/few/many/all-eligible
changes, clustered/spread selections, near/far effects and repeated/cancelled
future predictions. A separate engineered tier guarantees shorter paths, forced
detours, no-path states and recovery with multiple obstacles. Actual changed
counts and observed route outcomes are recorded; profile names are not treated
as evidence of either. The bounded-local supplement preserves downstream arrival
times; six versioned pulse fixtures force the old path to become invalid with
short-lived, nearby changes. Together these provide 432 scenarios.
See [the protocol and commands](docs/diverse-scenarios.md) and
[the measured findings](docs/diverse-findings.md). The completed local run has
an [overview with animated examples](runs/scenario-overview/index.html).

## Generate and measure forecast updates

```sh
python3 -m sipp_baseline generate --output runs/seed42.json \
  --width 24 --height 24 --seed 42 --updates 10 --obstacles 12 \
  --q 0.25 --horizon 40000
python3 -m sipp_baseline run runs/seed42.json --output runs/seed42-baseline \
  --repeats 10 --warmups 2
```

Or use the supplied authors' maps (MovingAI-derived) or a MovingAI `.map` file:

```sh
python3 -m sipp_baseline generate --map maps/empty_64_64.txt \
  --output runs/empty-seed7.json --seed 7 --updates 5 --obstacles 163 \
  --q 0.1 --horizon 40000
python3 -m sipp_baseline run runs/empty-seed7.json \
  --output runs/empty-seed7-baseline --repeats 10 --warmups 2
```

For named paper maps, default start/goal are the authors’ query coordinates.
For other maps they are the first/last free cells in row-major order; use
`--start ROW COLUMN ORIENTATION VELOCITY` and `--goal ROW COLUMN VELOCITY` to
override. A free cell alone does not guarantee feasibility under the primitives.
The time horizon must be long enough for the chosen map and speed constraints.

`--max-expansions` defaults to 1,000,000. Exhausting this budget gives
`expansion_limit`, never `no_path`. `--timeout` bounds a whole forecast batch in
seconds; a timeout fails the run and leaves `manifest.complete=false`.

## Interactive test visualization

Export a standalone viewer from any completed saved run:

```sh
python3 -m sipp_baseline visualize runs/corridor
python3 -m sipp_baseline visualize runs/final-grid24
```

Open the resulting `viewer.html` in a browser (double-click the file). No web
server, network connection, or JavaScript packages are needed. To regenerate an
existing viewer, add `--force`; use `--output path/to/replay.html` for another
location. The HTML embeds its data, so it can be moved or shared as one file.

The viewer provides:

- Forecast selection, animated playback, tick scrubbing and exact tick stepping.
- Map zoom, obstacle occupancy, planned path, and the robot's swept-cell overlay.
- Newly blocked/free cells compared with the previous forecast **at the same tick**.
- Cell inspection with merged, inclusive reservation intervals.
- Clickable timed actions and comparisons of median total time, expansions and arrival time.
- Explicit no-path/limit states and validation failures, without inventing trajectories.

The displayed path uses repetition 0 by default (`--repetition N` selects another).
Timing bars show medians across all saved repetitions. Exporting does not run the
planner again, change benchmark measurements, or modify source run data. The
robot marker interpolates between action endpoints for illustration; collision
occupancy uses the exact integer-tick primitive table. After arrival its faded
marker is a reference, not a guarantee of safe indefinite parking.

## Original SIPP-IP paper samples

An adapted viewer can replay the authors' released data instead of our synthetic
forecasts. Build the five-map viewer bundle with:

```sh
python3 -m sipp_baseline paper-viewer --output runs/paper-new --max-expansions 2000000
```

Open `runs/paper-new/index.html`, choose a map, then select an obstacle count.
To build fewer maps, use e.g. `--maps empty_64_64 room-64-64-16`. `--resume` reuses
matching completed map runs after an interrupted build. A map run that failed
before completing must be kept separately or removed before retrying it.

The pinned upstream repository releases **35 samples**: test index 0 at seven
densities for each of five maps. This is a released subset of the paper's 200
instances per map/density, not the full experimental corpus. Source files are
stored losslessly as gzip under `vendor/sipp-ip/tests/`, with original-byte SHA256
digests. The parser preserves starts, goals, and all reservation intervals. Times
are multiplied by 10 exactly as in the upstream `readInputs()` loader; the full
horizon remains 40,000 planner ticks (4,000 seconds).

Each sample is an independent problem, so the viewer disables the forecast-change
overlay and labels its controls as instances. The default playback range ends at
arrival, or previews 120 seconds for unsolved instances; select **Full horizon**
to inspect all reservation data. No obstacle identities are present in the
released format, so the display shows reserved cells, rather than inventing
individual obstacle tracks.

Robot trajectories are computed by our adapted planner. Arrival/feasibility are
compared with the authors' saved SIPP-IP results and reported both in the viewer
and `verification.json`. Our timings are not the paper's runtimes. An
`expansion_limit` result is inconclusive even if the source reports no solution.
Large HTML viewers embed gzip-compressed data and require a current browser with
native `DecompressionStream` support. Bundles above 4 MB (including Sydney) are
automatically split into a small selection page and one self-contained viewer per
test. Keep these HTML files together for navigation; individual test viewers can
still be opened offline on their own.

Sources: [paper, Empirical Evaluation](https://arxiv.org/html/2302.00776)
and [pinned sample release](https://github.com/PathPlanning/SIPP-IP/tree/77ca7491345c00b1cec7d0b88fe96cc561e0be25/tests).

## Density p and change probability q

`generate` now uses the pinned authors' obstacle-generation routines for its
initial forecast. **p** denotes obstacle density (`--density`), while **q** denotes
change probability (`--change-probability`, also `--q`). The old ambiguous
`--probability` option has been removed. Choose `--density` or `--obstacles`.

```sh
python3 -m sipp_baseline generate --map maps/empty_64_64.txt \
  --output runs/paper-style-q0.json --seed 7 --density 0.04 --q 0 --updates 5
python3 -m sipp_baseline generate --map maps/empty_64_64.txt \
  --output runs/paper-style-q025.json --seed 7 --density 0.04 --q 0.25 --updates 5
```

These two runs have identical initial forecasts. At q=0 every later forecast
remains identical too. For q>0, obstacles can acquire waypoints, pause, or gradually
speed up/slow down while preserving their past, in-progress movements and goals.
An update occurs every 100 ticks by default (`--update-interval`, 10 seconds).
q is the per-obstacle probability of a change **proposal per update**; infeasible
changes are logged as rejected. Use `--change-modes pause`, `waypoint`, or `speed`
to isolate a mechanism. The default horizon is the original 40,000 ticks.

The upstream generator is compiled lazily with g++. `--generation-timeout` bounds
its sampling/search runtime (default 120 s). See [the model specification](docs/model.md)
for exact source procedures, time scaling, rejection policies and compatibility
limits. The old random-walk demo files remain historical examples.

## Compare q across all five maps

Generate matched scenarios, measure the baseline and export the comparison page:

```sh
python3 -m sipp_baseline compare-q --output runs/q-comparison-new
```

Defaults: five paper maps, q = 0 / 0.1 / 0.25 / 0.5 / 1, density p = 0.04,
seed 7, five prediction-revision opportunities every 100 ticks, full 40,000-tick horizon, three measured
repetitions and one warmup. Each map's initial forecast is generated once and
shared across q, with matching initial hashes verified. These are 25 sequences
and 150 received predictions, not 150 required planner calls or independent
random repetitions of the environment. Only effective changes trigger replanning.

Open the resulting `index.html`. Choose a map, two q values and a forecast
revision; shared time, playback and zoom controls synchronize both replays.
The table compares all q values at that revision, including measured time,
expansions, applied/proposed changes, and changed obstacle/cell counts. Standalone
replay links and `comparison.csv` provide direct access to each result. Sydney
and other large exports automatically split by forecast to keep files small.

Override settings with `--q-values`, `--maps`, `--seed`, `--density`, `--updates`,
`--update-interval`, `--repeats`, or `--max-expansions`. `--resume` reuses matching
completed run directories after interruption; partial run directories must be
kept separately or removed before retrying. `suite.json` records settings and
completion, while each run retains its exact scenario and benchmark manifest.
Only completed runs appear while the suite is building. This remains a
fixed-start full-replanning baseline, with one environment seed by default.

Waypoint generation uses a persistent C++ BFS worker for large maps. Tests check
that its chosen routes match the Python reference; it changes generation speed,
not q=0 obstacle generation or waypoint path selection.

## Per-run files

Each run saves:

| File | Contents |
| --- | --- |
| `scenario.json` | Exact replay input: map, fixed query, and every complete forecast |
| `manifest.json` | Scenario/source/binary hashes, Git revision, platform, compiler, settings, completion flag |
| `results.jsonl` | One row per forecast and measured repetition, including the full trajectory |
| `summary.csv` | Per-forecast status, cost, median/p95 total time, search time and counters |
| `aggregate.json` | Initial-query and update-query counts, status breakdown, solved fraction and aggregate measurements |

`setup_us` includes new planner allocation, protocol input and reservation
normalization. `search_us` includes interval projection and queue processing.
`reconstruction_us` produces the executable path. `teardown_us` releases the
planner's search and reservation storage. `total_us` is the sum of these phases,
measured in C++ with a monotonic clock. It excludes JSON output, subprocess
startup and Python validation. `batch_wall_us` covers
the entire subprocess call for all forecasts, including startup, protocol
transfer, planner destruction, and result parsing; it is repeated on each row
for context and **must not be summed across rows**.

Validation and oracle work are outside planner timings. Warmups execute complete
event sequences and are discarded. Each baseline query triggered by a prediction
change is still a full replan; unchanged observations do not invoke the planner.
Very short microsecond timings are noisy; compare repeated runs on the same
machine. p95 uses the nearest-rank definition and is weak evidence with few samples.

`expansions` counts non-goal intervals actually expanded, `generated` counts
queue insertions including trimmed reinsertions, `projections` counts attempted
primitive projections, `queue_pops` includes stale entries, and `peak_open`
counts the largest queue. These definitions differ from upstream's node counter.
Physical memory/RSS is not measured yet.

Rebuild summaries with:

```sh
python3 -m sipp_baseline summarize runs/corridor/results.jsonl --output runs/corridor/summary-new.csv
```

## Scope

The fixed-start incremental algorithm and repair rules are documented in
[the repair design](docs/repair-design.md); the independent baseline continues
to replan from scratch.

See [the model specification](docs/model.md) before interpreting a benchmark.
This milestone includes full replanning, replay, synthetic updates, map import,
validation, a small exact oracle, incremental interval repair, and measurements.
It does not implement a moving start, continuous geometric collision checking,
or the full paper experiment corpus. Dependency maintenance is included in
incremental query time; the initial plan is reported separately from updates.

## Sources and attribution

- [Ali & Yakovlev, AAAI 2023](https://ojs.aaai.org/index.php/AAAI/article/view/26453): SIPP-IP.
- [Authors' implementation](https://github.com/PathPlanning/SIPP-IP), pinned at
  `77ca7491345c00b1cec7d0b88fe96cc561e0be25`.
- [MovingAI benchmarks](https://movingai.com/benchmarks/grids.html); supplied map
  files were copied verbatim from the pinned authors' repository.
- [Vendored provenance](vendor/sipp-ip/PROVENANCE.md) and
  [MIT license](vendor/sipp-ip/LICENSE).

Tests compare 240 random snapshots with a separate time-expanded search, verify
the important deterministic boundary/update cases, validate reconstructed paths,
and compare 24 generated snapshots against the unmodified upstream planner.
These checks provide implementation evidence, not a general proof.

## Adaptive full-replan fallback

Build the optional planner with `make build-adaptive`. The binary
`build/sipp_ip_adaptive` accepts the same forecast protocol as the baseline.
The first query constructs the repair cache. On subsequent queries, the planner
counts free cells whose normalized blocked intervals differ from the forecast
that owns the cache. When at least 5% of the free map
differs, it runs the baseline search. The fresh result is returned immediately
and the previous repair cache remains available for later queries. A small edit
relative to a substantially different forecast can therefore trigger another
full search. Each output row records its strategy.

The current threshold was selected using seeds 7 and 11 and evaluated on seeds 19, 23 and 29. See [the threshold study](docs/threshold-study.md). Replay the earlier seed-11 comparison from the
repository root with the following command and a new output filename.

```sh
python3 -m sipp_baseline.adaptive runs/diverse-scenarios runs/local-scenarios \
  examples/diverse-pulses --seed 11 --thresholds 32 10 --output runs/adaptive-replay.jsonl
```

The comparison applies the effective-change event policy to all three planners.
It rotates execution order, uses one warm-up and three measured trials, validates
paths and checks status and cost against full replanning. Engineered cases also
use the independent oracle. Records contain the individual native timings and
the strategy chosen for each invoked query. Update totals exclude initial search.

For moving-start runs, `python3 -m sipp_baseline.moving_replay` accepts
`--suffix-fresh` to use a certified suffix when possible and otherwise run a
fresh SIPP-IP search. See the [four-policy moving-start comparison and phase
profile](docs/moving-fresh-search.md) for the protocol and measurements.
