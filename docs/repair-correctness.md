# Correctness of fixed-start SIPP-IP interval repair

This document gives a mathematical proof for the algorithm implemented in
`src/incremental.cpp`, including its update transaction. It does not infer
correctness from agreement with the baseline or inherit a theorem from the paper.
The proof is not machine-checked; the optional executable invariant audit and
independent oracle tests support the correspondence between the proof and code.

## Statement and scope

Fix a finite map, the supplied primitive tables, start configuration and tick
`t0`, goal predicate, and integer horizon `H`. A forecast `B` assigns each cell a
finite union of blocked closed integer intervals. Forecast updates are atomic,
and no update interrupts search. Reservations are exogenous: the robot's path
does not change them. Valid inputs satisfy the bounds checked by `read_input`.

For every finite sequence of such forecasts, after each completed query:

1. **Soundness:** `solved` returns a collision-free concrete trajectory satisfying
   the declared primitives, waiting rules, start and goal, and horizon.
2. **Completeness:** without an effective resource cutoff, a feasible trajectory
   within this model and horizon is eventually found. `no_path` and
   `invalid_start` correctly certify infeasibility in that model.
3. **Optimality:** the returned `cost_ticks` is the smallest feasible absolute
   arrival tick, with arbitrary goal orientation and the specified goal velocity.
4. **Termination:** every individual update and unrestricted search finishes.
5. **Safe interruption:** `expansion_limit` is inconclusive and preserves the
   frontier needed to resume, including after a later forecast change.

These are finite-model, resolution-completeness and earliest-arrival claims.
They are not claims about every possible continuous motion, unbounded horizons,
executing online with an advancing robot, or optimality across unknown future
forecasts. Reuse assumes a fixed query; changing the query invokes a fresh search.
Allocation failure, process timeout and the guarded storage-index limit are
resource failures, not infeasibility certificates. No runtime-speedup claim follows.

## 1. Reference graph and interval meaning

Let `Q` contain the free-cell configurations `(row,column,orientation,velocity)`.
The reference graph has feasible vertices `(x,t)` for `x in Q`, integer
`t0 <= t <= H`, whose cell is free at `t`. Its edges are:

- A supplied primitive of duration `d`, from `(x,t)` to `(y,t+d)`, precisely when
  its static footprint is legal, `t+d <= H`, and every tabulated touch is free.
- A one-tick wait from `(x,t)` to `(x,t+1)` when stopped and free throughout
  that closed interval. Moving configurations have no wait edge.

Paths may stop at their first goal vertex. The graph is finite and every edge
strictly increases time. Absolute time is also the path's accumulated cost from
the fixed start, up to the common additive constant `t0`.

A label `L=(x,[a,b])` means **for each** integer `t in [a,b]` there exists a
root-derived path to `(x,t)`. Different timestamps may use different paths. A
moving interval never asserts permission to wait. A stopped raw label additionally
extends to the end of the same safe interval: `b = safe_end_B(x,a)`.

An expansion `E=(L,[l,u])` processes an arbitrary subinterval of that raw label.
`C[x]`, called CLOSED, is the union of the domains of live expansions at `x`.
It certifies that those exact configuration/time states have been expanded;
it is not a separate reachability witness. Labels keep their full raw intervals,
including portions suppressed by CLOSED.

## 2. Exact projection and reconstruction

For a primitive touch of cell `c` at offsets `[f,l]`, and a blocked interval
`[A,Z]` in `B[c]`, a departure tick `s` collides exactly when

`[s+f,s+l] intersects [A,Z]`, equivalently `A-l <= s <= Z-f`.

Consequently `project_result` computes the exact feasible departure set

`D = [E.lo, min(E.hi,H-d)] minus union([A-l,Z-f])`,

over all touches and their blocked intervals. `normalize` and `subtract` compute
integer-set unions and differences exactly; adjacent integer intervals may merge
because there is no missing integer between them. Each remaining component
`[a,b]` yields the exact arrival interval `[a+d,b+d]`.

Every supplied primitive touches its destination at offset `d`. Therefore the
destination is free at every arrival in this component. These consecutive arrival
ticks lie in one safe interval. When the destination is stopped, the exact union
of those arrivals and all their legal waits is

`[a+d, safe_end_B(destination,b+d)]`.

For a moving destination it remains `[a+d,b+d]`. Every feasible primitive departure
is represented, and every represented output timestamp has a legal witness.
Separate departure components remain separate certificates even if their stopped
waiting closures overlap. The source configuration and primitive determine the
output configuration, and the fingerprint retains both output and departure bounds.

For an output timestamp `t`, reconstruction chooses

`s = min(dep_hi, t-d)`.

The output construction guarantees `dep_lo <= s <= dep_hi`, so `s` is in the
parent expansion and raw label. If `s+d < t`, the output must be stopped and
the destination is free throughout `[s+d,t]`; the emitted wait is legal. Repeating
this construction backwards reaches the root and its legal initial wait. Each
non-root label points to a label that existed before it was created, so the
chain is acyclic. Compaction preserves this order. This proves the projection
contract and reconstruction soundness, assuming valid parent witnesses.

## 3. Invariants at transaction/search boundaries

The following hold after construction, after a complete `update`, and between
search expansions. They need not hold temporarily inside a repair transaction.

**W — Rooted witnesses.** Every live label has the meaning defined above. It is
either the current root or the output of a live record whose live expansion
uses its live parent label. Producer ancestry is acyclic. A stopped raw label
has its full current safe-interval waiting closure.

**C — Owned coverage.** CLOSED equals exactly the union of live expansion
domains. Every domain is contained in its live source label. Live expansion
domains for the same configuration are disjoint. Goal labels are not expanded.

**P — Complete current operators.** Each live expansion has a live record for
every statically legal outgoing primitive, including an empty result. Its output
list, including departure bounds, equals `project_result` in the current forecast.
The records and labels have complete ownership/producer links.

**F — Frontier representation.** For every live non-goal label `L`, every integer
in `L.interval minus C[L.configuration]` is covered by an OPEN task for `L` with
its current scheduling generation. Tasks refer to subintervals of immutable raw
labels. Tasks may be redundant or partly covered, and stale tasks may coexist.

**G — Goal upper bound.** `U` is the smallest lower bound of any live goal label,
or infinity if none exists. Its incumbent is a live witness attaining `U`.

The frontier invariant is intentionally goal-aware. A goal is recorded as an
upper bound and is never expanded or queued. An invariant demanding a frontier
for every reachable state *after* passing through a goal would be false and is
unnecessary for this shortest-path problem.

### Initialization and ordinary expansion

If the start is occupied, no root exists and no path can start. Otherwise the
root is exactly `(x0,[t0,safe_end(x0,t0)])` when stopped, or `(x0,[t0,t0])` when
moving. Scheduling establishes F; CLOSED is empty; P is vacuous; considering a
goal root establishes G.

Before an expansion, search removes CLOSED from its queued interval. If trimming
changes the interval, all remaining components are requeued. Thus `expand` only
receives a nonempty, previously uncovered domain. It adds that domain to the
ownership ledger and CLOSED, creates all statically legal primitive records, and
installs every raw projection output without clipping it to CLOSED. Section 2
establishes W and P; `add_label` schedules all uncovered non-goal output pieces
and considers goals. Existing pending tasks still cover any uncovered portions
of their immutable labels. Hence C, F and G also remain true.

## 4. Repair preserves the invariants

### Complete dependency detection

For a surviving source expansion, an operator's numeric inputs are its immutable
source configuration/domain, the fixed primitive and horizon, and the reservation
tables of its swept cells. The waiting closure additionally depends on the full
destination-cell table. The destination is among the swept cells, and `register_watch`
watches each entire touched-cell table, not merely the old contact-time window.
It registers even a currently empty projection. Therefore every operator that
could change is either visited by the changed-cell watches or has its source
expansion withdrawn. No event label or assumed value of q is needed.

The transaction stamp only deduplicates a record within this visit. On unsigned
stamp-counter rollover the implementation clears old stamps and uses epoch 1,
so an old equal stamp cannot suppress a visit. Without this reset this lemma
would be false; see the counterexample below.

### Retirement and operator replacement

A changed output fingerprint causes every old output label of that record to be
retired. Retiring a label retires every expansion it owns; each such expansion
retires all its records and recursively retires their output labels. Ownership
ledgers include every expansion, and each output has one producer. Thus no live
descendant retains a withdrawn witness. Concrete ancestry, rather than aggregate
reachability, prevents circular support after losing the root.

If the root's represented interval changes, its entire witness subtree is retired
and a new root is constructed if the start is valid. A moving root only needs
replacement when its start tick becomes invalid; its interval is a singleton.

Changed records are previewed under the new forecast. Their previews are installed
only after the retirement cascade and only if their source expansion remains live.
For any surviving old record, either its input cell tables did not change or its
complete fingerprint was recomputed and found identical. Surviving source labels
retain their configurations and intervals. Induction on ancestry therefore proves
that surviving old witnesses are valid under the new forecast. Section 2 proves
validity of newly installed witnesses. Previewing from a subsequently retired
source is harmless because that preview is never installed. This reestablishes W
and P without assuming that a currently invalid old witness is already sound.

### Restoring CLOSED and the frontier

The transaction rebuilds each affected CLOSED union from live owners. Thus it
withdraws all unsupported coverage and preserves C. CLOSED can only shrink during
repair; installing new labels does not expand them.

Consider a surviving old non-goal label. A formerly uncovered timestamp still has
its old task unless the label is rescheduled. Any newly uncovered timestamp lies
in `C_old minus C_new`. Such a loss marks the configuration as affected and causes
**every** surviving raw candidate for that configuration to be rescheduled.
`schedule` posts its entire current `L minus C_new`, not merely the newly lost
portion. Hence invalidating older task generations cannot lose the old frontier.
New output labels and a new root receive the same full scheduling. This proves F,
including for dormant alternatives and states whose older tasks were discarded as
covered. Scanning surviving goals and considering new goals reestablishes G.

The generation counter is not a reachability certificate. Even if it eventually
wraps and an extra old task matches again, that task still names a subinterval of
the same live immutable label; CLOSED is checked before expansion. This can add
redundant work but cannot invalidate W, C or F. New scheduling always supplies all
required current tasks. Label IDs themselves are not reused with a retained heap.

### Compaction and no-change updates

Compaction is a bijective renaming of live labels, expansions and records, preserving
intervals, links and ancestry order. It reconstructs candidates, owners and watches,
clears OPEN and schedules every live label's uncovered interval again. Thus all
invariants survive. Dead provenance is unnecessary because every dormant *live*
alternative is retained.

An identical effective forecast leaves the graph and certificates unchanged. A
previously completed result can be returned directly. An interrupted query is
not marked completed and instead resumes search. Query-identity changes destroy
the old planner and invoke the initialization argument.

## 5. Exact-state dominance and the path-cut lemma

At an exact `(configuration,tick)`, the future feasible edges depend only on that
state and the current forecast. Every path reaching it has the same arrival cost
`t`. Expanding it once through a sound witness therefore suffices, regardless of
which incoming path will be used later. This justifies CLOSED suppression. It
does not justify suppressing a different tick, orientation or velocity.

**Path-cut lemma.** For any feasible root-to-first-goal path arriving at `T`, either
`U <= T`, or there is a current OPEN task containing a non-goal vertex `(x,t)`
on that path with lower endpoint `a <= t`.

**Proof.** Traverse its vertices, including unit waits, and select the first not
in CLOSED. Such a vertex exists because goal states are never expanded. If it
is the root, the root label represents it. Otherwise its predecessor is CLOSED
and so belongs to a live owner's expansion domain. For a primitive edge, P and
exact projection give a live output label containing the successor tick. For a
wait edge, the owner's raw stopped label contains the successor too: the wait
is legal and the raw label extends to the current safe interval's end. If the
selected vertex is a goal, G yields `U <= t <= T`. Otherwise F provides the
claimed task. This proves the lemma. In particular, waiting needs no separately
cached primitive record; its full closure is already a raw-label invariant.

## 6. Optimality and completeness

Use `h(x)=5*ManhattanDistance(x.cell,goal.cell)`. Each supplied primitive satisfies
`duration >= 5*(abs(delta_row)+abs(delta_column))`; waits and turns only add time.
The triangle inequality proves `h(x) <= duration+h(y)` for every edge, and `h=0`
at the goal. Thus it is consistent and lower-bounds any remaining path duration,
even though it ignores orientation, velocity and obstacles.

For the task from the path-cut lemma, the priority satisfies

`f = a+h(x) <= t+h(x) <= T`.

Stale/covered tasks cannot justify stopping. `search` first checks label liveness
and generation and subtracts current CLOSED. A changed domain is requeued with
new lower endpoints. Only a current, fully uncovered task can trigger the bound
test. Since it was popped from a min-heap, its priority lower-bounds all other
retained task priorities. Removing or trimming covered pieces does not lose an
uncovered path cut.

Suppose search returns `solved` at the bound test with a feasible incumbent `U`,
but a path of arrival `T<U` exists. The lemma supplies a task with `f<=T<U`,
contradicting the minimum fully processed heap head having `f>=U`. If the heap
is empty, the lemma gives the same contradiction. W and reconstruction prove
that the incumbent itself is feasible. Hence its arrival is optimal.

Suppose an empty heap yields `no_path` while a feasible path exists. With no
incumbent, the lemma requires a current OPEN task, contradicting emptiness.
An occupied initial state plainly admits no path. These facts prove completeness
and sound infeasibility certificates once search terminates.

The budget check occurs after queue normalization and pushes its task back before
returning `expansion_limit`; it does not claim optimality or infeasibility.
Every previously queued alternative remains available. F therefore holds for
resumption and for the next repair transaction, even if a feasible but uncertified
incumbent was found before interruption.

## 7. Termination

Let `M = |Q|*(H-t0+1)`, an upper bound on the number of exact graph vertices.
During one search the forecast is fixed, CLOSED only grows, and each expansion
adds at least one previously uncovered vertex. Thus at most `M` new expansions
are possible, or more tightly `M - sum_x |C_initial[x]|`.

Each expansion has finitely many primitives and each exact integer departure set
has finitely many components. Hence it creates finitely many labels/tasks.
Cleaning a stale task removes it. Trimming a task removes at least one tick from
its domain and partitions the remaining ticks without adding any; its splitting
tree is finite. Between expansions CLOSED is fixed, so freshly trimmed pieces
cannot undergo an infinite sequence of further trims. With finitely many
expansions and a finite inherited heap, search must terminate or hit a cutoff.

Each update scans finite tables/stores. Retirement visits a label's outgoing
ownership only the first time it becomes dead; the remaining duplicate visits
are finite skips. Replacement and compaction process finite records. Therefore
repair terminates too. Induction over any finite forecast history gives the
theorem stated at the beginning. An expansion budget of at least `M` suffices
mathematically for a query, subject to memory and other resource limits.

There is also a finite bound on live witness storage for the fixed model: at
most `M` live expansions, `3M` live projection records, and
`1 + 3M*(H-t0+1)` live raw labels, because every non-root live label belongs to
one current record and each record has at most one component per departure tick.
These are loose bounds, not practical memory guarantees. They do not establish
that repair uses less memory or time than full replanning.

## 8. Implementation counterexample found and fixed

In commit `9104921`, `++epoch` could wrap to zero, equal to a record's initial
or post-compaction stamp. The affected-record loop then skipped that record.
This state is reachable after `2^64-1` identical updates followed by a changed
forecast; identical updates increment the epoch but leave record stamps untouched.

A direct reproduction sets the epoch to that reachable value after the initial
corridor search, then applies the supplied second forecast. The old implementation
returned arrival **100** although the correct answer is **126**. This was a real
dependency-detection/soundness counterexample, though it requires an extraordinary
history length. Resetting stamps and starting at epoch 1 on wrap repairs it.
`tests/repair_rollover.cpp` checks the corrected answer without replaying that
astronomical prefix. Storage-index casts are also now guarded, so an exhausted
integer identifier space produces a resource failure rather than corrupted links.

No counterexample to the main interval/witness repair rules was found in this
audit. The global-frontier wording in the old design was too strong because
goals are terminal; the goal-aware lemma above supplies the needed argument
without changing goal handling.

## 9. Executable obligations and reproducibility

Compile with `-DSIPP_REPAIR_VERIFY` to audit immediately after repair and search.
`verify_invariants` checks current projection/departure fingerprints, complete
footprint watches, rooted provenance, waiting closures, exact CLOSED ownership,
disjoint expansion domains, all uncovered candidates' task coverage, goal minima,
and completed stopping certificates. It also checks the primitive assumptions
used by projection and the heuristic. These expensive checks are absent from
the release executable and must not be used for performance measurements.

```sh
make test
g++ -std=c++17 -O1 -DSIPP_REPAIR_VERIFY src/incremental.cpp \
  -o build/sipp_ip_incremental_verified
python3 -m sipp_baseline compare-repair-suite runs/q-comparison \
  --output runs/repair-proof-check-new --repeats 1 --warmups 0 --timeout 180
```

`tests/test_repair_proof.py` adds 480 independent-oracle randomized queries with
audits enabled, 25 interrupted/resumed protocol queries, seven owner-loss/root/
compaction queries, and the rollover regression. The previous 800 randomized
oracle comparisons remain in the suite. Independent tests verify finite cases;
they do not constitute exhaustive or machine-checked verification of the proof.

The complete test suite passes **52 tests**. The revised release build again
matched **150/150** five-map queries; the tracked
[validation record](repair-correctness-validation.json) contains their costs,
input/source/binary hashes and settings. The local
[validation report](../runs/repair-proof-check/index.html) retains full per-case
paths and counters. This replay uses one repetition for correctness validation,
not a new performance conclusion. An AddressSanitizer/UndefinedBehaviorSanitizer
verification build also passed the 480 random, seven owner-loss and 25 interruption
queries (512 total). Leak detection was disabled for the execution environment.

The performance results in `repair-results.md` and its JSON refer to commit
`9104921`, before this correctness audit. Their recorded source hashes should
remain historical rather than being relabeled as measurements of modified code.
