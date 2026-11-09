# Moving-start SIPP-IP repair design

**Status.** Proposed algorithm for the finite, integer-tick model. The moving replay currently resets the search whenever its start or start tick changes. In the seed-19 pilot that happened on all 146 post-initial queries. The design has two opportunities for reuse. Sometimes the executed prefix and the old optimum certify the remaining route immediately. Otherwise the new search can reuse individual successor computations as it establishes reachability from its new root.

## Decision state

Use the moving replay's state `(row, column, orientation, velocity, absolute tick)`. A stopped wait can be interrupted at the revision tick. For a revision inside a turn, acceleration, cruise or brake, check the remaining swept-cell contacts against the forecast in force during each portion of the primitive. Consume intervening revisions and use the endpoint configuration and tick as the next root. A collision before a decision boundary is a committed-motion conflict. The old route is trimmed at the actual boundary, including splitting a stopped wait there. Keep the absolute horizon and goal fixed. Report remaining cost as arrival tick minus decision tick.

## Rule 1. Certify an old suffix directly when possible

Save the last **certified optimal** absolute arrival U, its forecast, and the timed trajectory. The following conditions together permit an immediate answer.

1. The executed prefix from the old query reaches the new configuration at exactly the decision tick t and was feasible under the old forecast. Following the recorded optimal route to the boundary is a sufficient prefix witness.
2. A suffix starting at that exact state and tick reaches the goal at U and validates against the current forecast, including waits.
3. Within the remaining time window [t,U), every free cell-time under the new forecast was also free under the old forecast. Check the normalized interval differences on traversable cells, including **removals**. Pure additions satisfy this condition. For t = U, verify the goal at the new root directly.

**Reason.** Any new path arriving strictly before U would use only times before U. Condition 3 makes it feasible under the old forecast. Prepending the prefix from condition 1 would yield a feasible old solution arriving before the certified optimum. Condition 2 attains U, so the suffix is optimal. This also works for a future-only change that first takes effect after arrival. Use the forecast associated with the certificate even if an intervening adaptive fallback used a different cache.

If a blockage is removed while the old suffix remains feasible, a shortcut might open elsewhere. A validated suffix then supplies an upper bound. Keep its actual steps for return if search proves the bound optimal. Store this external incumbent separately from the current native incumbent label, whose parent chain belongs to a search root. A cutoff before certification remains inconclusive. An old no-path result supplies no feasible suffix.

## Rule 2. Establish reachability from the actual state

| Search object | Action when the root changes |
| --- | --- |
| Root | Check occupancy at t. For a moving root, seed the singleton [t,t]. For a stopped root, seed [t,end of current safe interval]. |
| Labels, OPEN, CLOSED, expansion owners, candidate lists and completion flags | Start a new logical generation. Old ownership and parents cannot certify coverage or a path from this root. An implementation can lazily initialize touched buckets using generation tags. |
| Old expansions | Keep value records indexed by full source configuration and original departure domain. Preserve the primitive's feasible departure components, full footprint dependencies and the forecast version under which they were computed. Include empty projections. Copy values or hold immutable storage across compaction. |
| New witnesses | Create labels with parents and owners in the new generation. A match on a cell, a time or an old label ID alone never creates a witness. |
| Fallback | A fresh search from the actual state is always available. Track the root, forecast and version that own each retained record. Tune a moving-start fallback only after measuring its costs. |

At a new expansion, let J be the reachable departure interval left after subtracting **current-generation** CLOSED. For each statically legal action:

1. Look up an old record with the same source cell, orientation, velocity and action whose expanded domain I contains J. Reuse requires the same static grid, motion model and horizon, and identical normalized blocked intervals on every swept cell, including the destination. A version check is sufficient only when every change updates that cell's version and version rollover clears the cache. Check dependencies even for a formerly empty output.
2. On a hit, intersect each **feasible departure component** in the record with J. For every surviving component [a,b], create the arrival witness [a+w,b+w] with departures [a,b], where w is the primitive duration. For a stopped destination extend the upper endpoint through its current safe interval, exactly as in the ordinary projector. For a moving destination preserve the arrival interval. This clipping must happen before waiting closure.
3. On a miss, changed dependency, or partial overlap that does not cover J, run the ordinary projector on all of J. This first version needs no stitching of overlapping records. Install outputs with the new parent, including alternatives suppressed by another expansion. Record coverage of J only after all statically legal actions have been processed.
4. Continue the ordinary best-first search. Return the cheapest witnessed goal once the smallest live frontier lower bound cannot improve it. With an empty frontier, return the incumbent if present, otherwise no path within the horizon. Validate an external incumbent before returning its saved trajectory.

For example, suppose an old departure component was [10,20] and the moving robot now reaches its source only at tick 17. The transferable departure is [17,17]. If that departure is unavailable, an old stopped arrival label spanning tick 17 gives no permission to wait or move from this source. Similarly, if the robot has passed a junction, its old side branch becomes eligible for reuse only if the new search reaches that branch's source configuration again.

## Correctness argument

For fixed action and reservations, feasible departures are the input interval intersected with a fixed set of legal ticks. Restricting from I to J contained in I therefore commutes with departure filtering. Restoring arrival times and applying stopped waiting closure to the restricted components yields exactly the ordinary projector's output on J. This includes the empty case. Comparing full dependency intervals covers a change at a destination that shortens or extends a possible wait beyond the motion's arrival.

Induct from the new root. Each installed successor is backed by a reachable new parent and a legal departure. Each expanded domain processes all legal actions, and CLOSED contains only domains processed in this generation. Thus replacing a projection calculation by an eligible hit preserves the successor set, reconstruction and frontier coverage of a fresh interval search. The finite-model completeness and optimality argument then applies with the new root. A validated suffix can tighten the stopping bound without removing a solution that could improve it. Resource limits have the same inconclusive semantics as the baseline.

## Implementation and acceptance

Begin with the suffix certificate as a separate return path. Then introduce an immutable projection-value cache around the existing projection/installation boundary. The current verifier assumes every incumbent is a live label and checks parent order, CLOSED ownership and frontier coverage. Extend it for a separately validated suffix and current-generation witnesses. In verification builds recompute every cache hit with the ordinary projector and compare the complete departure/arrival fingerprint.

Test against full replanning and the independent time-expanded oracle on small maps. Include a revision during a stopped wait, a moving singleton inside a formerly wider domain, the same cell with a different velocity or heading, an unreachable branch behind the robot, an old empty projection that becomes feasible, a shortened destination wait, a feasible old route with a newly opened shortcut, and consecutive revisions inside one committed action. Include no-path, recovery on a later feasible decision state, and expansion cutoff. Check the executed prefix as well as each returned suffix.

Replay the 102 seed-19 pilot episodes on the same executed trajectory first. For the 146 advanced-root queries count direct certificates, recomputed and reused projections, and searches completed without any hits. Report total native time including cache indexing, validation of certificates and disposal, along with median and p95 update latency, peak retained storage and exact remaining-cost agreement. Repeat on separate seeds only after the differential checks pass. A projection hit saves computation but still requires installing a new witness, so hit counts alone do not establish a speedup.

References: [fixed-root proof](repair-correctness.md), [native search](../src/incremental.cpp), [moving replay](../sipp_baseline/moving_replay.py), [pilot results](threshold-study.md).

## Implemented suffix certificate and pilot

Rule 1 runs in the native adaptive executable on an advanced start tick. It uses the completed optimum and forecast held by the retained search. A matching configuration and tick on the reconstructed optimal route supplies a feasible prefix witness. A wait can be split at the decision tick. Reaching the goal at the decision tick has a direct zero-remaining-cost certificate. The implementation checks interval containment over [t,U) on traversable cells and every retained motion contact or wait against the updated forecast, including the endpoint at U. A hit returns the validated steps with strategy `certified_suffix`, zero expansions, and no cache reset. A miss continues through the existing planner. A full-replan fallback does not install a new certificate in this version.

The seed-19 replay matched full replanning on all 248 queries. The 102 episodes had the same decision states, remaining costs and outcomes as the preceding pilot. The certificate avoided 16 of the 146 advanced-start resets (11.0%). The other 130 queries rebuilt the search. There were 98 arrivals, three no-path outcomes and one conflict with committed motion.

In this single replay the 16 hits had median native time 0.66 ms versus 9.90 ms for fresh SIPP-IP on those same queries. Across all 146 updates the respective medians were 22.59 ms and 15.56 ms. These are descriptive timings from one pass with a common executed baseline trajectory. The next implementation target is rule 2 for uncertified queries.

Reproduce with the moving replay command in the [threshold study](threshold-study.md), using a new output filename. [Recorded decisions and native timings](moving-suffix-pilot.jsonl.gz).
