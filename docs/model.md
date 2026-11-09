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

The current implementation is derived from SIPP-IP but has not received a new
formal proof. The test suite checks its equivalence on bounded cases and against
the authors' implementation; do not present those tests as a proof.

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

## Synthetic forecast generator

The `grid-walk-v1` generator uses a private seeded Python RNG. Initial obstacle
cells are sampled without replacement, excluding the query endpoints. Obstacles
follow four-neighbor grid walks. Their source and destination are both reserved
for the whole movement interval, a conservative grid occupancy approximation.
Obstacle-obstacle overlap is allowed. Initial moves avoid occupying the robot's
start at tick zero; later conflicts remain possible and are handled by planning.

On each forecast revision, each obstacle is independently selected with
probability `p`. A selected obstacle's entire forecast is regenerated from its
original starting cell using speed changes (5/10/20 ticks per cell), a waypoint
bias, or random pauses (10/20/30 ticks). Metadata records the selections. Forecast
snapshots share a fixed time origin; revisions are not execution times, and
regeneration does not preserve an executed prefix.

Thus `p` is **per obstacle per forecast revision**, not the presentation's
per-obstacle-per-time-step model. This intentionally simple initial generator
supports deterministic experiments; a causally consistent trajectory-prediction
simulator matching the final experimental design is a later task.
