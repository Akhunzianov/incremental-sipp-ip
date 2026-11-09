# Broader scenario suite

This suite expands coverage before changing repair rules. It keeps both existing
planners and their fixed-start query model unchanged. Replanning is triggered only
by effective prediction changes. Prediction revisions preserve each obstacle's
observed/in-flight prefix; the robot is still queried from the same reference
start/time, not advanced during replay.

## Separate tiers and bounded-local controls

**Upstream-derived:** five paper maps, seeds 7/11/19 and requested densities
p=0.02/0.04 give 30 initial worlds. Each world has the authors' unmodified initial
generation procedure, then nine profiles, for 270 cases. Worlds and reference
initial solutions are shared across profiles. Existing matching base worlds can
be reused with `--base-cache`; their reservation tables are not altered.

| Profile | Requested changed plans | Selection | Future boundary | History |
| --- | --- | --- | --- | --- |
| one-spread-near | 1 | seeded | earliest available | one revision |
| few-cluster-near | 4 | clustered | earliest available | one revision |
| few-spread-near | 4 | spread | earliest available | one revision |
| many-cluster-near | ceil(25% of agents) | clustered | earliest available | one revision |
| many-spread-near | ceil(25% of agents) | spread | earliest available | one revision |
| all-eligible-near | all eligible agents | all | earliest available | one revision |
| many-spread-far | ceil(25% of agents) | spread | after old arrival + margin | one revision |
| few-cluster-repeated | 4, same requested IDs | clustered | future boundary >=500 | three revisions |
| many-spread-alternating | ceil(25%), same requested IDs | spread | future boundary >=500 | four revisions |

Each batch mixes pauses, speed increases, speed decreases and waypoint reroutes.
Pauses are 10–100 ticks, speed changes use the existing bounded travel-duration
ramp, and waypoints can reroute the future tail. Individual perturbation modes
follow the existing generator. Starts, goals, initial start times, actor counts,
and source extra reservations remain fixed. These are forced batch profiles and
therefore have no q parameter. Density p is a separate world-generation factor;
the actual density after integer rounding is retained in each scenario.

"Few", "many" and "all" describe requested batches, not guaranteed acceptance.
Parked agents may be ineligible; speed-bound, horizon, routing and collision checks
may reject proposals. Records retain requested/eligible/selected counts and actual
changed IDs. The suite reports actual batch sizes, including zero effective changes,
and does not silently replace rejected agents to reach a desired result. "All
eligible" must not be interpreted as all agents when some have already parked.

Cluster selection takes nearest agents to a common seeded anchor; spread selection
uses farthest-point sampling. Positions are evaluated at their intervention
boundary. Changed future paths can extend across the map, so this selection does
not guarantee spatially local reservation differences. Exact changed-cell and
cell/tick counts remain available in the comparison CSVs.

Single revisions arrive at tick 100. Repeated histories arrive at 100,140,310;
alternating histories arrive at 100,140,230,310 and restore/reapply a future
proposal: A→B→A→B→A. Intervals are irregular but stay on the source time lattice.
All repeated/cancelled interventions start at or after tick 500, so withdrawing
them does not rewrite observed history. Near means earliest eligible opportunity,
not a guarantee of an early effect for a delayed-start obstacle. Far boundaries
are at least max(2000, old optimal arrival+100), when that arrival is known.
The actual first differing tick and its relation to the previous arrival are
measured, rather than assumed from the profile name.

This is a coverage matrix, not a full factorial design. It should not be used to
attribute every performance difference to one dimension in isolation.

**Engineered:** six small regression families, three seeds and 2/4 agents give
36 additional cases. These are explicitly synthetic, not samples from the
authors' initial generator. Seeded column/timing variations retain constructive
outcome guarantees:

- A benign change leaves the old path optimal.
- A blocked interval moves away and a shorter path opens.
- A changed forecast invalidates the old path and requires waiting.
- Multiple parked blockers force a geometric detour.
- A bottleneck closes completely, then a prediction cancellation restores a path.
- Repeated future cancellations alternate no-path and feasible states.

Both planners' results on every engineered case are checked against the independent
time-expanded oracle. Expected outcomes are also asserted, subject to resource
limits; a cutoff remains inconclusive. The no-path claim is within the declared
finite horizon and supplied motion primitives. Engineered cases have their own
actual densities and are not pooled with the two requested primary densities.

**Bounded-local upstream supplement:** the same 30 initial worlds each receive
four additional profiles: few/many × cluster/spread, for 120 cases. These edits
replace one future moving edge with a nearby waypoint or a pause followed by
faster travel to its original endpoint. The original edge's arrival deadline
and every downstream node/time are retained. Edge durations remain within the
discrete obstacle model's 10–100 tick bounds; this is not a continuous acceleration
model. A changed actor affects at most three nearby cells, within the original
edge window plus at most nine ticks on either side from source merging. The
union over a batch can span a longer time range. Waypoint rejection can fall
back to pause/catch-up; modes and actual support are recorded.

The normalized Manhattan diameter of the changed cells is measured separately
from the actor selection. This makes spatial locality observable. These are
randomly placed controls, with no selection based on the robot's previous path;
they do not guarantee a difficult repair.

**Targeted bounded pulses:** six small, versioned fixtures in
[`examples/diverse-pulses`](../examples/diverse-pulses/README.md) cover three
seeded layouts/timings and 2/4 actors. They apply the same deadline-preserving
waypoint operation on the old robot path. Their short-lived changes force an
invalid old path and a higher optimal cost. They are additional engineered cases
with oracle checks, rather than upstream-generated worlds.

The complete experiment has 390 upstream-derived cases and 42 engineered cases,
for 432 in total. See [the findings](diverse-findings.md) for actual coverage.

## Physical and source-fidelity checks

Each case saves a compressed, deterministic trajectory-delta trace containing
every changed obstacle before/after. Auditing replays those deltas, verifies
identities/endpoints, positive legal eight-neighbor motion, unchanged source
extras, unchanged observed prefixes, exact changed-ID counts, and reconstruction
of every reservation snapshot. Other agents are not silently modified.

The upstream empty-map generator can already produce some overlapping obstacle
reservations. The suite preserves that initial data, rather than changing the
authors' initial world to satisfy a stronger assumption. New proposals use the
existing conservative collision-rejection policy. The audit permits inherited
cell/agent-pair collision windows but rejects new ones; inherited counts are
recorded. Other paper maps retain their original independent-obstacle overlap
policy. The engineered cases use separated actors and also undergo the conflict
audit. The tables, not a continuous geometry simulator, define occupancy.

## Evaluation and observed outcomes

Every received prediction has an event decision. Unchanged effective reservations
invoke neither planner. The baseline starts a fresh search at each actual event;
repair retains state within each sequence. Fresh processes start each repetition.
Paths are validated and feasibility/optimal cost are compared at every query.

`observed-events.json` and the overview's `events.csv` classify each transition
using the baseline result and validation of the previous path against the new
prediction. They distinguish skipped observations, unchanged optima, shorter
paths, invalid old paths, no-path transitions, recovery and inconclusive results.
An old feasible path is not by itself an optimality certificate. Some shorter-path
events can also invalidate the old path; the validity flag is retained separately.
CSV modes/proposal outcomes and actual changed IDs expose what was applied.

Time/expansion limits are not infeasibility or correctness matches. Failed/capped
cases are recorded and excluded from speedup claims in the overview. A disagreement
stops evaluation and retains the mismatch artifact. Native timing has the existing
parsing/diff/repair/search phases and excludes shared Python selection, process
startup, serialization, validation and final retained-cache disposal.

The full matrix defaults to one replay without warm-up: it is a coverage and
stress check. A preselected seed-7, p=0.04 subset is separately measured with
three repetitions and one warm-up. This subset is chosen by configuration,
not by observed speed. Its engineered seed-7 cases are retained as a separate
tier. No pooled speedup across synthetic and upstream cases is reported.

## Commands and files

```sh
make test
python3 -m sipp_baseline generate-scenarios --output runs/diverse-scenarios-new \
  --seeds 7 11 19 --densities .02 .04 --base-cache runs/controlled-repair
python3 -m sipp_baseline compare-scenarios runs/diverse-scenarios-new \
  --output runs/diverse-coverage-new
python3 -m sipp_baseline compare-scenarios runs/diverse-scenarios-new \
  --output runs/diverse-measured-new --seeds 7 --densities .04 --repeats 3 --warmups 1
python3 -m sipp_baseline generate-local-scenarios runs/diverse-scenarios-new \
  --output runs/local-scenarios-new
python3 -m sipp_baseline compare-scenarios runs/local-scenarios-new \
  --output runs/local-coverage-new
python3 -m sipp_baseline compare-scenarios runs/local-scenarios-new \
  --output runs/local-measured-new --seeds 7 --densities .04 --repeats 3 --warmups 1
python3 -m sipp_baseline compare-scenarios examples/diverse-pulses \
  --output runs/pulse-coverage-new
python3 -m sipp_baseline compare-scenarios examples/diverse-pulses \
  --output runs/pulse-measured-new --seeds 7 --repeats 3 --warmups 1
```

`--base-cache` is optional. `--no-engineered` omits the synthetic tier during
generation. Density filters apply to the upstream tier, while seed filters apply
to both tiers. `--resume` on comparison checks settings, input and source/binary/
driver hashes; stale and incomplete case results are not silently reused.

Generated scenarios retain base worlds, source provenance, reference solutions,
`scenario.json`, and `trajectory-changes.json.gz`. Comparisons retain all standard
raw paths, manifests, per-query CSVs, observed events and summaries. `coverage.json`
reports measured outcome and actual agent-count coverage; `index.html` compares
cases. Generated data are ignored by Git; the findings and compact results are
tracked. The six authored pulse fixtures are also tracked. The completed run's
[`runs/scenario-overview/index.html`](../runs/scenario-overview/index.html) links
all reports and 14 small examples, each with baseline and repair animation.
Those viewers embed the saved results and do not rerun planning. For another
trajectory viewer, use `run` and `visualize` on a case's `scenario.json`, as with
existing tests.
