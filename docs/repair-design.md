# Proposed repair rules for fixed-start Incremental SIPP-IP

Status: implemented as a first prototype in [src/incremental.cpp](../src/incremental.cpp).
See [implementation and measured results](repair-results.md) and the subsequent
[correctness proof and audit](repair-correctness.md). This design deliberately repairs whole projection
results when their witnesses change; finer interval surgery is a later optimization.

## 1. Decision and scope

Repair a graph of **cached interval projections and path witnesses**. A displayed
parent tree alone is insufficient: it loses failed transitions and alternative
intervals suppressed by CLOSED. Both are needed after forecasts change.

Keep the map, robot primitives, start configuration, start tick, goal and finite
horizon fixed. Only the effective blocked-time sets change. Moving-start repair,
changes to the motion model, and an adaptive restart policy are separate tasks.
Use p for obstacle density and q for obstacle-change proposal probability;
neither parameter is needed by the repair algorithm itself. It consumes actual
reservation changes, not obstacle-generator event labels.

Do not attach identity to a safe interval's ordinal number: splitting or merging
safe intervals can renumber them. A configuration is x = (row, column,
orientation, velocity); labels have independent stable handles.

## 2. Mathematical contract for a projection

All timestamps are planner ticks and all intervals are inclusive. Let B[c] be
the normalized union of blocked intervals at cell c. Normalize at the planner's
one-tick resolution; do not apply the obstacle generator's source-time scaling
or ten-tick merging rule during repair.

For a primitive a of duration w, let each swept cell c have touch offsets [f,l].
If c is blocked on [b0,b1], the forbidden departure interval is:

```text
[b0 - l, b1 - f]
```

For a reachable source interval I, calculate:

```text
D = (I intersect [0, H-w])
      minus union of all forbidden departure intervals over all swept cells
A = D shifted forward by w
```

For a moving destination, A is the reachable arrival-time set. It is not
permission to wait. For a stopped destination, apply waiting closure:

```text
for every destination safe interval S with A intersect S nonempty:
    include [min(A intersect S), upper(S)]
```

There is no reachable interval after an intervening blockage unless there is an
actual arrival seed on that side of it. Waiting cannot cross an occupied time.

Keep enough provenance to choose an actual feasible departure for every reported
timestamp. In the first version, keep separate output labels for separate
departure components and witnesses, even when their reachable intervals overlap.
Do not merge different witnesses into one label with one arbitrary parent.

These equations describe the baseline's projection contract for the supplied
primitives, whose terminal footprint is the destination cell. Supporting other
primitive geometries requires checking their terminal occupancy separately.

## 3. Retained records

| Record | Required contents | Purpose |
| --- | --- | --- |
| Label L | Stable handle, configuration x, immutable reachable interval I, producing projection handle, feasible departure component, live flag | A concrete root-derived witness for every time in I |
| Expansion E | Source label handle, expanded subinterval I_E, live flag, outgoing projection handles | Owns the exact configuration/time coverage whose outgoing actions were processed |
| Projection R | E, primitive, semantic version, full swept-cell list, last result fingerprint, all output label handles | Cached computation, including an empty result |
| CLOSED[x] | Union of intervals owned by live expansions, plus the ownership ledger | Expansion coverage, not independent evidence of reachability |
| Candidates[x] | All live generated labels for x, including fully or partly suppressed ones | Restore alternatives when CLOSED coverage disappears |
| OPEN | Pending label/interval tasks, witness handles and versions | Unexpanded work; stale tasks can be removed lazily |
| Watch[c] | All live projection records whose primitive depends on c | Find affected computations, including previously empty projections |
| Incumbent | Goal label handle, exact arrival tick U, reconstruction witness | Feasible upper bound, never a reason by itself to stop |

A root label is a special witness: if the start is stopped, its interval starts
at the fixed start tick and ends at that start-cell safe interval's upper bound;
if moving, it contains only the start tick. A blocked start has no root label.

A label can be a witness without being expanded. For example, its timestamp set
may be fully covered by another label's expansion. Keep the label dormant instead
of deleting it. A projection must retain its outputs **before** CLOSED clipping.

Store only actual attempted projections of expanded source pieces, not every
possible time-expanded edge. However, create their dependency records for all
statically valid primitives before any dynamic-obstacle early return. A
statically impossible primitive can be omitted because the spatial graph is fixed.

## 4. Invariants

1. **Witness validity.** Every live label has a current root-derived witness for
   every timestamp in its interval. A moving label never invents waiting.
2. **Owned coverage.** CLOSED contains only live expansion coverage. Removing a
   witness must remove coverage owned by its dependent expansions.
3. **Cached expansion completeness.** Every retained expansion has a projection
   record for each statically valid outgoing primitive, including failed ones.
4. **Dormant alternatives survive.** CLOSED suppression changes scheduling, not
   the stored reachable interval or its witness.
5. **Frontier coverage.** After repair, every live non-goal raw label has OPEN
   tasks covering all of its timestamps outside CLOSED. Goal witnesses instead
   update the incumbent; they need not be expanded or queued. Together with
   complete cached operators, this supplies a frontier on every feasible path
   to its first goal unless an equally early goal witness already exists.
6. **Independent path witnesses.** CLOSED coverage does not serve as a label's
   parent proof. Each new label refers to an existing source witness, so its
   producer ancestry is acyclic by creation order.

The sixth rule prevents a pair of aggregate reachability sets from incorrectly
supporting each other after their connection to the start has disappeared.

## 5. Update transaction

Apply a whole forecast as one transaction. Do not mix old and new reservations
while accepting a path or expanding search tasks.

```text
REPLAN(new_forecast):
    normalize effective blocked unions and compute changed cells
    if no effective change and previous query completed:
        return previous answer

    snapshot old CLOSED ownership before any retirement
    collect suspect projection handles from changed-cell watches
    install the new reservation snapshot
    replace the root witness if its reachable interval changed

    for each suspect projection whose source expansion is still live:
        preview its new departure/output mapping
        if mapping unchanged: refresh observed versions, retain its witnesses
        otherwise: remember replacement and retire its old output witnesses

    drain witness retirement, including dependent expansions and their outputs
    remove retired ownership contributions from CLOSED
    reactivate surviving candidates in newly uncovered time ranges
    install remembered replacements whose exact source expansions survived
    resume interval A* with a certified incumbent and the complete frontier
```

Retirement can be queued while previews are computed. Do not install replacements
or accept a goal until the retirement work queue has drained. Coverage snapshots
must precede root retirement as well as ordinary projection retirement.

### R1: detect changes in effective occupancy

Normalize the new reservations and compare each cell's blocked union with the
old union. Let Delta[c] be their symmetric difference. Ignore obstacle identity:
one obstacle leaving a cell does not free it if another still occupies it.

If every Delta[c] is empty, return the previous answer directly, provided the
previous query completed. An old expansion-limit/timeout result remains
inconclusive and cannot become a certified answer through this shortcut.
Account for full-snapshot parsing and comparison time in measurements.

If an interrupted query is retained, it must still satisfy frontier coverage:
requeue a popped but unprocessed task before a budget exit and handle partially
computed expansions transactionally. If that cannot be guaranteed, restart the
next query instead of reusing its partial state.

### R2: identify suspect projections and check the root

The first implementation uses a conservative index:

```text
suspect = union(Watch[c] for changed cells c)
```

Watch the entire geometric footprint, not only cells reached before an old early
return. For stopping primitives, include destination waiting dependencies. A
change to a blocking boundary just beyond the old waiting interval may extend
that interval, even though the old output never included the boundary itself.
Watching the whole destination cell handles this without fragile SI IDs.

Recalculate the root interval. If it changes, retire the old root witness and its
dependents, and enqueue the new root if one exists. If only later reservations
change while the root's actual reachable interval stays identical, it can remain.

### R3: preview suspect computations under the new forecast

For each suspect projection, compute its new result using the same source
expansion interval. Compare complete semantic fingerprints:

```text
(output configurations,
 ordered feasible departure components,
 corresponding reachable output intervals and waiting bounds)
```

If the fingerprint is identical, preserve its labels and descendants and update
its observed reservation versions. Comparing output intervals alone is unsafe:
the same reachable set could now require a different departure witness.
An identical fingerprint does not increment the record's semantic version;
observation epochs and witness semantics are distinct bookkeeping fields.

If it differs, mark that projection as changed. Its old output labels will be
retired, and a new result installed if its source expansion survives. It is safe
to preview a source that is subsequently invalidated; just discard that preview.

### R4: retire changed witnesses and dependent expansions

For each changed projection, retire all of its old output labels. Recursively
retire expansions and projection records whose source witnesses were retired.
Use an iterative work queue and live flags rather than recursive C++ calls.

For every retired expansion:

- Remove its ownership contribution from CLOSED.
- Retire its outgoing projection outputs and remove dead projection watches.
- Invalidate queued tasks and goal incumbents that rely on its dead witnesses.
- Record the configuration whose expansion coverage may have shrunk.

Keep a directly changed projection record available for replacement if its source
expansion is still live. A changed outgoing action does **not** by itself retire
that source expansion; it retires the action's results.

Retire an entire changed label in version 1, even if only part of its interval
became invalid. This can over-delete good work but avoids keeping stale departure
maps or accidentally shifting descendants with different motion constraints.

No feasibility is inferred from a nonzero support count or another CLOSED owner.
An alternative witness must be an explicit surviving label or be rediscovered.

### R5: restore alternatives and install replacement projections

Compute genuinely lost coverage from the ownership ledger:

```text
lost[x] = old_CLOSED[x] minus remaining_live_CLOSED[x]
```

For affected configurations, inspect all surviving labels in Candidates[x].
Re-enqueue their portions that are no longer covered by live expansions. This
includes intervals previously trimmed out or completely suppressed as duplicates.
Do not erase coverage still owned by another live expansion.

Install the new outputs of changed projections whose exact source expansion is
still live. Reuse their previews when possible. Allocate new label handles and
store their original intervals and departure mappings before CLOSED clipping.
Queue uncovered portions; keep covered portions dormant.

If a source expansion died, skip replacement of its old projection. When its
source state is rediscovered through a valid witness, normal expansion will
compute the corresponding projections again.

This phase must complete before testing A* termination. A formerly empty
projection becoming nonempty is just as important as a disappearing edge.

### R6: resume interval A*

Retain the remaining valid CLOSED owners and OPEN tasks. Use the baseline's
admissible, consistent key:

```text
key(x, [lo,hi]) = lo + 5 * ManhattanDistance(x.cell, goal.cell)
```

On a pop, reject dead handles and subtract live CLOSED coverage. Requeue trimmed
pieces as needed. When a piece is expanded, give it an ownership record and
create all outgoing projection records before processing their results.

New labels arising from newly available paths enter this same process. No
spatial-radius restriction is used: effects propagate through dependencies and
the search frontier.

## 6. Exact stopping rule

An unchanged old path can remain feasible while becoming suboptimal. Keep it
only as the incumbent upper bound U.

After all repair work has completed, discard stale/covered OPEN heads and stop
with the incumbent only when:

```text
minimum valid OPEN key >= U
```

An empty OPEN has key infinity. If there is no incumbent, continue searching.
No incumbent plus an empty OPEN certifies no path within the finite horizon.
A blocked start returns invalid_start. Resource limits retain their distinct
inconclusive status.

Goal labels are terminal for the arrival-time objective. They need not be
expanded to establish an upper bound. Even when a goal candidate is popped and
the query ends, retain the frontier and dormant labels; a later forecast may
make another route better.

Do not prune all tasks whose keys exceed the current goal's cost: that goal may
disappear in the next query. Preserve that work, or preserve a recoverable lazy
representation with a separate proof of completeness.

## 7. Repair cases and failure modes

| Update/case | Required repair |
| --- | --- |
| Effective occupancy unchanged | Reuse the completed answer; do no projection/search work |
| A transition becomes blocked | Reproject; if its fingerprint changes, retire its old labels and dependent owners |
| A transition becomes free | Recompute even a previously empty projection; put new reachable pieces in OPEN |
| A moving interval splits | Create separate reachable components, preserving their departure witnesses |
| A stopped interval is split by occupancy | Truncate waiting at the blockage; no later component without a later arrival seed |
| A stopped safe interval merges/extends | Recompute waiting closure; propagate newly reachable times and resume search |
| One predecessor is invalidated | Restore surviving candidates; do not assume its descendants are globally unreachable |
| A suppressed duplicate becomes necessary | Wake its uncovered parts when the former CLOSED owner's coverage disappears |
| Old goal survives, a shortcut opens elsewhere | Retain goal as U and search until the frontier bound proves optimality |
| No path becomes a path | Failed projection records at the old reachable boundary must seed renewed search |
| Start safe interval changes | Replace the root; a large invalidation is acceptable in the first version |
| Forecast changes repeatedly before repair finishes | First implementation serializes queries; later cancellation/coalescing needs a separate protocol |

The following use small abstract intervals for explanation, not the paper's
specific acceleration duration.

**Alternative predecessor.** A moving configuration X has a label from P on
[3,5] and another from Q on [4,8]. Suppose P owned [3,5], and Q only expanded
[6,8] because [4,5] was already covered. If P is invalidated, Q's stored full
label [4,8] must restore [4,5]. Retaining only Q's clipped [6,8] loses valid paths.
Descendants whose actual witness used P are retired and may then be rediscovered
through Q. There is no need to claim the entire reachability set of X vanished.

**Do not fill holes.** A moving X reachable through separate witnesses on [3,5]
and [7,8] is not reachable at tick 6. Taking their convex hull is incorrect.

**Waiting split/merge.** An arrival seed at tick 5 and target blockage [10,12]
allow stopped waiting only on [5,9]. The later safe interval [13,30] is not
reachable from that seed. Removing the blockage extends waiting to [5,30].

**Swept-cell timing.** A source interval [0,20], an action of duration 5, and a
swept cell touched at offsets [2,4] with blockage [10,12] give forbidden
departures [6,10]. Feasible departures are [0,5] and [11,20], yielding moving
arrival intervals [5,10] and [16,25]. Checking only source/destination arrival
occupancy would miss this interior collision.

**No circular self-support.** If a retained A-to-B-to-A path depended on an
invalidated arrival from the root, keep neither segment merely because A and B
appear in each other's aggregate predecessor sets. Retire their concrete witness
chain, then require new root-derived witnesses.

## 8. Correctness proof and executable obligations

The following records the original proof obligations. They are now addressed by
the detailed lemmas and theorem in [repair-correctness.md](repair-correctness.md),
including a correction to the old overly broad global-frontier wording. The
argument is for this implementation's finite model and does not simply inherit
the original SIPP-IP theorem.

**Soundness.** Prove the projection contract, waiting closure and backward
departure reconstruction. Induct over producer ancestry to establish witness
validity. Retirement invalidates every dependent certificate; unchanged
fingerprints retain the same valid departure mapping under the new forecast.

**Coverage restoration.** Prove that owner withdrawal cannot leave unsupported
CLOSED entries and that every newly uncovered surviving candidate is scheduled.
Separately prove that every changed outgoing operator of a retained expansion
is either replaced or shown semantically unchanged. Empty results are included.

**Completeness of resumed search.** For any feasible path not already represented
by live expansion coverage, consider its first unexpanded configuration/time.
Its preceding expanded state must have a current projection that generates a
frontier witness, or itself have an earlier frontier ancestor. Exact-state
dominance is sound because position, orientation, velocity and absolute time
fully determine future motion feasibility in this fixed model.

**Optimality.** On a hypothetical path arriving before U, an appropriate frontier
label has key no greater than that path's arrival time. After the repair barrier,
OPEN.min >= U rules such a path out. Numerical equality of arrival costs is the
criterion; path shape and tie-breaking need not match a fresh run.

**Termination.** Use the finite horizon, positive primitive durations, finite
primitive set and exact CLOSED coverage. Within a consistent resumed search,
expansion processes only previously uncovered configuration/time pieces. The
batch retirement graph has finite stored records and visited/live flags.

The proof gives implementation-level definitions of suppression, fingerprints,
owner withdrawal, queue normalization and reconstruction. The optional
`SIPP_REPAIR_VERIFY` build audits their invariants at repair/search boundaries;
independent oracle tests provide additional bounded evidence. The mathematical
proof and its C++ correspondence have not been machine-checked.

## 9. Implementation order in this repository

1. Factor the baseline projection into a pure function returning departure
   components and reachable output components. Keep its existing CLI results.
2. Add label witnesses, expansion ownership, dormant candidates and projection
   records. Make a fresh initial search agree with the current baseline/oracle.
3. Persist a planner across forecasts, including OPEN and the incumbent. Add
   cell watches and the no-effective-change shortcut.
4. Implement the transactional preview/retire/restore/resume rules. Use whole
   labels when fingerprints differ; do not start with fragment-level support
   counts or automatic parent adoption.
5. Differential-test every forecast against fresh SIPP-IP and the bounded
   time-expanded oracle on small maps, including adversarial updates below.
6. Integrate repair metrics and compare on the existing five-map q suite.

`src/planner.cpp` currently destroys its Planner after each input and loses empty
projections and clipped duplicates. Its flat CLOSED union lacks owner identities.
Changing only `search()` or removing `planner.reset()` cannot implement this
design safely. Keep the full-replan executable as an independent baseline while
building the incremental variant.

### Required adversarial acceptance cases

| Test | What must be checked |
| --- | --- |
| q=0 / identical normalized forecast | Same answer, no repair projections or expansions; diff cost still counted |
| First blocked swept cell becomes free | Formerly empty projection is retried |
| A later swept cell changes after an earlier old rejection | Full footprint was registered before the old early return |
| Obstacle changes but effective union does not | No spurious repair |
| Split and merge, including one-tick boundaries | Correct inclusive interval arithmetic and waiting seeds |
| Only one of two overlapping predecessors is invalidated | Previously suppressed times are restored |
| Disjoint moving contributions | A gap is never filled by union normalization |
| Old path valid, off-path shortcut opens | An improved optimum is found before stopping |
| Mixed additions/removals in one forecast | No intermediate mixed-version answer is accepted |
| Root is blocked then unblocked | invalid_start followed by a fresh valid root |
| No-path / path / no-path sequence | Correct renewed frontier discovery and failure status |
| A spatial cycle loses its only root witness | No circular support remains |
| Repeated updates and stale queue handles | No dead witness is expanded or reconstructed |
| Budget exit followed by another query | The popped task is retained, or the planner restarts; no false no-path certificate |
| Change only beyond an old waiting upper bound | The blocker boundary still triggers closure repair |
| Same output interval, changed feasible departure map | Old reconstruction data is not silently reused |

Randomized updates should be independent of the obstacle generator as well:
arbitrary normalized reservation changes catch cases a realistic simulator may
never produce. Keep the existing trajectory validator separate from repair.

## 10. Measurements, limits, and later optimizations

Measure normalization/diff, preview projection, invalidation, alternative
reactivation, resumed search and reconstruction separately, and include all of
them in end-to-end replanning time. Record suspect/changed/unchanged projections,
retired labels/owners, reactivated intervals, expansions, dormant candidates,
retained memory, and whether the old incumbent survived. Compare initial search
and updates separately; retaining failed and dominated results has an initial
time/memory cost.

The first version can still approach a full restart for small occupancy changes
near a widely used witness. Whole-cell watches and whole-label invalidation are
conservative choices, not a claim of minimal repair or guaranteed speedup.

Optimize only after differential correctness passes:

- Narrow watches using actual occupancy differences. For a touched cell with
  Delta[c], potentially affected departures lie in the union of shifted
  intervals [d0-l,d1-f], intersected with I_E. Waiting closure needs additional
  safe-boundary dependencies; the departure test alone is insufficient.
- Preserve unchanged output components when a projection fingerprint partly
  changes. Compare witness mappings, not just reachable unions.
- Adopt an alternative valid parent without retiring a label, only after proving
  its new certificate covers the entire retained interval and reconstructs it.
- Replace per-configuration candidate scans with an interval index.
- Garbage-collect retired witnesses and stale queue storage using stable
  generation-tagged handles, while preserving live certificate ancestry.
- Add a measured restart threshold once memory/time costs are understood.

Do not jump straight to a scalar g/rhs per configuration. Moving configurations
can have disjoint reachable-time intervals, and compressed label identities can
change with forecasts. An interval-valued LPA*-style formulation is another
research direction, with additional consistency and least-fixed-point issues;
it is not automatically proved by borrowing the scalar update equation.

## Sources and attribution

The projection starting point is [Ali and Yakovlev's SIPP-IP
paper](https://arxiv.org/html/2302.00776) and the pinned source in this repository.
[Lifelong Planning A*](https://idm-lab.org/bib/abstracts/papers/aij04.pdf) is the
general incremental-search reference. [Unhelkar, Buhai and Shah's FSIP workshop
paper](https://people.csail.mit.edu/cdarpino/RSS2016WorkshopHRcolla/abstracts/RSS16WS_11_PlanningDynamicEvolvingGraphs.pdf)
is a related incremental safe-interval approach. The concrete witness/ownership
repair protocol above is a proposed design for this project; these references do
not establish its correctness, novelty or performance.
