# Fixed-start baseline specification

## Query and time

The map, start configuration, goal configuration, start tick, primitive model,
and finite horizon stay fixed throughout a forecast sequence. A forecast is a
complete replacement reservation table. Query order does not advance the robot
or shift the time origin. Forecast identifiers are unique strings.

Rows increase downward; columns increase rightward. Orientations are 0=east,
1=north, 2=west, 3=south. Velocity indices are 0=stopped and 1=2 cells/second.
Only stopped configurations may wait or rotate. Goal orientation is unrestricted;
goal velocity is explicit (normally zero). Success means reaching the goal at
the earliest tick, with no requirement to remain there forever. `cost_ticks` is
the absolute arrival tick; travel duration is `cost_ticks - start_tick`.

All times are integer ticks, one tick = 0.1 s. Blocked and reachable intervals
are **closed**: `[a,b]` includes both endpoints. Touching an occupied endpoint is
a collision. Waiting at a stopped cell occupies every tick from start to end.
Input reservations may overlap, duplicate, or be adjacent; the planner unions
them. Reservations outside `[0,horizon]` are rejected. Static walls are blocked
for the entire horizon. All actions must finish by the horizon.

`no_path` means no feasible path **within this finite model and horizon**.
`invalid_start` means the specified start is occupied at the start tick.
`expansion_limit` is an inconclusive resource limit, not infeasibility.

## Motion primitives

Primitives and swept-cell timing offsets are copied from upstream `fillActions`.
Acceleration/deceleration uses magnitude 0.5 cells/s² and covers four cells in
40 ticks; cruise covers one cell in five ticks. A quarter-turn while stopped
takes 20 ticks. The table is the collision model; it is not generated from a
continuous simulator during search.

For direction vector `(dr,dc)`, acceleration touches cell `(r+j*dr,c+j*dc)`:

| j | First touch | Last touch |
| --- | --- | --- |
| 0 | 0 | 20 |
| 1 | 0 | 29 |
| 2 | 20 | 35 |
| 3 | 28 | 40 |
| 4 | 34 | 40 |

Braking uses `(first,last)` offsets `(0,6), (0,12), (5,20), (11,40),
`(20,40)` at offsets j=0..4. Cruise touches both source and destination during
`[0,5]`. Rotation touches only its cell during `[0,20]`.

This reproduces the authors' tabulated primitive collision convention, rather
than asserting exact continuous geometry for arbitrary obstacle shapes.

## Interval projection search

A node contains configuration `(r,c,o,v)`, a reachable interval `[lo,hi]`, and
projection provenance. At a stopped configuration the interval includes legal
waiting; at a moving configuration its timestamps represent different possible
arrivals, not permission to wait.

For a touched cell occupied during `[a,b]`, with relative touch offsets `[f,l]`,
the forbidden **departure** ticks are `[a-l,b-f]`. Subtract these intervals for
every touched cell from the parent's reachable interval. Add the primitive
duration to surviving departure intervals. If the result is stopped, extend
each reachable interval through the end of its target safe interval.

A* orders nodes by `lo + 5*ManhattanDistance`, with deterministic ties. The
heuristic is admissible and consistent for the supplied primitives. Expanded
coverage is stored per configuration as a union of intervals. Pending intervals
are reduced by already expanded coverage and requeued when trimmed; distinct
remaining pieces keep their provenance. The implementation does not depend on
upstream's assumption that only the latest CLOSED interval needs inspecting.

Concrete reconstruction chooses feasible departure ticks backward through
provenance. Any slack after arriving stopped is emitted as an explicit `wait`.
The separate Python validator checks durations, endpoints, velocity constraints,
occupancy of every swept cell, continuity, and final state. It uses concrete
actions and does not perform interval projection. The oracle additionally
enumerates `(r,c,o,v,t)` states and one-tick waits with Dijkstra on small cases.

The [correctness argument](repair-correctness.md) proves the implemented
interval/witness algorithm's properties for this finite discrete model, including
repair, waiting, exact-state suppression and stopping. It is not machine-checked
verification of the C++ program. Bounded oracle comparisons and invariant audits
support the code-to-proof correspondence; they are not substitutes for the proof.

## Scenario JSON v1

```json
{
  "schema_version": 1,
  "tick_seconds": 0.1,
  "horizon": 200,
  "grid": ["............."],
  "start": [0, 0, 0, 0],
  "goal": [0, 12, 0],
  "start_tick": 0,
  "forecasts": [
    {"id": "p0", "reservations": []},
    {"id": "p1", "reservations": [[0, 6, 0, 70]]}
  ]
}
```

`grid` uses `.` and `#`; each reservation is `[row,column,first_tick,last_tick]`.
Optional `metadata` and per-forecast `events` describe the experiment and do not
affect search. Full snapshots, rather than deltas, intentionally make baseline
replay independent of change-detection code.

## Obstacle generation and forecast changes (v2)

Use **p = N / free_cells** for obstacle density and **q** for change probability.
The CLI exposes these as `--density` and `--change-probability` (alias `--q`).
Density chooses the obstacle count; q never changes that count.

### Initial forecast: the actual upstream generator

`src/obstacle_generator.cpp` calls `generate_obstacles1()` from the pinned authors'
`generate_obstacles.cpp`, rather than approximating it with a random walk. The
vendored original is unchanged and SHA256-checked. At build time two observation
hooks capture accepted paths; an injected seed replaces `random_device` while
retaining the original `std::mt19937` and `uniform_int_distribution` sampling.
Unused file-driver code is omitted and out-of-horizon successor accesses are
bounded. The original release itself uses an unrecorded random seed, so this
reproduces its procedure, not its historical random instances byte-for-byte.

The upstream implementation uses:

- Eight-neighbor movement (including diagonals) plus a wait successor in the
  temporal branch. As in upstream, diagonals check the destination cell, rather
  than prohibiting corner cutting.
- Random obstacle starts and distinct goals. The robot query endpoints are
  excluded from obstacle routes. Obstacle endpoints need not be globally unique
  in the independent branch.
- A sampled per-cell duration of 1..10 source units, or 10..100 planner ticks
  (1..10 seconds per cell). This is a duration, not a velocity in cells/second.
- `empty_64_64`: starts at zero and temporal breadth-first search against earlier
  obstacle reservations, with waiting available.
- Other paper maps: an independent spatial breadth-first route, with a sampled
  start delay of 0..200 source units. Obstacle-obstacle overlap is allowed by this
  upstream branch. Custom maps use this independent procedure.
- Both endpoints of every obstacle move occupied throughout its inclusive time
  interval; the final cell stays occupied until the source horizon ends.

The upstream occupancy table uses 4,001 source samples (0..4,000). Its loader
multiplies interval endpoints by 10. We preserve that ordering: adjacent occupied
source samples merge before scaling, rather than leaving artificial nine-tick
holes between them. The independent branch also marks its goal once at the
unshifted route duration, in addition to the delayed trajectory and parking.
That upstream quirk is retained in `extra_reservations` to make q=0 exact.

Every generation reconstructs reservations from captured obstacle paths and
asserts equality with the upstream occupancy table. Tests additionally compare
q=0 against a separate wrapper around the unmodified generator for both branches.

For a named paper map, the robot query defaults to the authors' coordinates.
The generation horizon is always the original 40,000 planner ticks; a shorter
`--horizon` clips that original forecast without changing how it was generated.
All future forecasts are identical when q=0. Separate q values with the same
seed, map and obstacle count have exactly the same initial forecast.

### Updates

An update occurs every `--update-interval` planner ticks (default 100 = 10 s).
At each update, each obstacle receives a reproducible Bernoulli(q) change proposal.
Proposal draws and modification choices are keyed by seed, revision and obstacle
ID, independently of the initial C++ sampling. q is **per obstacle per forecast
revision**, not per planner tick. Changing the update interval changes the
proposal rate per second.

A proposal can affect an obstacle only if it has an uncompleted route segment
starting before the scenario horizon. It takes effect at the next route node
strictly after the revision time. The past and any movement already in progress
are preserved. An obstacle that has already parked remains parked. Its identity,
original start and original goal stay fixed.

Default proposal types have equal probabilities:

- **Waypoint:** sample a free intermediate cell and route from the future boundary
  through it to the original goal, using eight-neighbor spatial breadth-first
  paths. Up to 12 waypoint candidates are attempted.
- **Pause:** insert a 1..10 second wait at that boundary and shift the remaining
  trajectory accordingly.
- **Speed:** choose acceleration or deceleration with equal probability. Shorten
  or lengthen successive moving-edge durations by 10 ticks per edge, bounded to
  10..100 ticks. Existing waits retain their duration. This is a discrete speed
  ramp; it does not assert a particular continuous acceleration value.

`--change-modes` can isolate one type for controlled experiments. Changes that
would exceed the source horizon, have no waypoint route, or already hit the
speed bound are not applied. On `empty_64_64`, changes introducing a collision
with another predicted obstacle are rejected; other maps retain the upstream
independent policy. Thus q controls proposal probability, and the actual accepted
change rate is measured from `events`, not assumed to equal q. Each event records
its obstacle, revision/effective ticks, parameters and outcome.

Each forecast saves full reservations plus the individual obstacle node sequences
and source extras. Reservation prefixes through every revision time are tested
for equality before and after updates. The planner query remains the fixed
reference start and start tick; advancing the robot is still a separate extension.

The previous `grid-walk-v1` saved scenarios remain readable, but are historical
smoke tests and are not regenerated by the new `generate` command.
