# Final moving-start benchmark protocol

Planner revision aad27b9. Freeze both binaries and use seeds 1009, 1013, 1019, 1021 and 1031 in that order. These seeds are outside the project's previous training and benchmark suites. Use all five paper maps, requested densities 0.02 and 0.04, the existing nine change patterns and no engineered scenarios. Report every generated case and any generation or comparison failure.

Compare suffix certification plus fresh SIPP-IP with the same certificate plus compact on-demand reuse. Use the full-replan-controlled trajectory and existing effective-change decision rule. Pair the start state, tick and forecast at every query. Check status, earliest arrival, reconstructed path feasibility and agreement of path steps and expansions. Use the existing moving comparison protocol with rotated order, one warm-up and three timed repetitions. Run timed episodes serially.

The primary endpoint is summed median native episode time including the initial solve. Also report update p95, peak process RSS, process wall time, initial and update times, per-seed and per-map results, and groups by number of post-initial certificate misses. Compare ratios of summed times inside each group. Interpret miss counts descriptively. Do not change planner settings after observing outcomes.
