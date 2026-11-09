# Incremental SIPP-IP research: full-replanning baseline

Working fixed-start baseline: each forecast snapshot constructs a **fresh SIPP-IP
search**, returns a concrete timed trajectory, validates it, and records timings
and search counters. No search state is reused between snapshots.

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
python3 -m unittest discover -s tests -v
python3 -m sipp_baseline run examples/corridor.json --output runs/corridor --oracle
```

The corridor sequence must produce costs **100, 126, 100, no path, 100** ticks.
One tick is 0.1 seconds. `--oracle` also verifies feasibility and optimal cost
using an independent time-expanded Dijkstra; use it only on small cases.
Output paths must be new: existing runs are never silently overwritten.

## Generate and measure forecast updates

```sh
python3 -m sipp_baseline generate --output runs/seed42.json \
  --width 24 --height 24 --seed 42 --updates 10 --obstacles 12 \
  --probability 0.25 --horizon 800
python3 -m sipp_baseline run runs/seed42.json --output runs/seed42-baseline \
  --repeats 10 --warmups 2
```

Or use the supplied authors' maps (MovingAI-derived) or a MovingAI `.map` file:

```sh
python3 -m sipp_baseline generate --map maps/empty_64_64.txt \
  --output runs/empty-seed7.json --seed 7 --updates 5 --obstacles 163 \
  --probability 0.1 --horizon 1500
python3 -m sipp_baseline run runs/empty-seed7.json \
  --output runs/empty-seed7-baseline --repeats 10 --warmups 2
```

Default start/goal are the first/last free cells in row-major order; use
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
native `DecompressionStream` support; they remain offline, self-contained files.

Sources: [paper, Empirical Evaluation](https://arxiv.org/html/2302.00776)
and [pinned sample release](https://github.com/PathPlanning/SIPP-IP/tree/77ca7491345c00b1cec7d0b88fe96cc561e0be25/tests).

## Run artifacts

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
forecast sequences and are discarded. Every repetition is still a full replan.
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

## Scope and next integration point

See [the model specification](docs/model.md) before interpreting a benchmark.
This milestone includes full replanning, replay, synthetic updates, map import,
validation, a small exact oracle, and measurements. It does not implement
incremental repair, a moving start, continuous geometric collision checking, or
a reproduction of the paper's obstacle-generation distribution.

For a future incremental planner, keep the same saved scenario and result
contract and compare each forecast's status/cost against this baseline. Keep
its dependency-maintenance time inside its reported total. The initial plan
`P0` should be reported separately from update queries `P1...Pk`.

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
