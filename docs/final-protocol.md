# Final moving-start benchmark protocol

Planner revision aad27b9. Freeze both binaries and use seeds 1009, 1013, 1019, 1021 and 1031 in that order. These seeds are outside the project's previous training and benchmark suites. Use all five paper maps, requested densities 0.02 and 0.04, the existing nine change patterns and no engineered scenarios. Report every generated case and any generation or comparison failure.

Compare suffix certification plus fresh SIPP-IP with the same certificate plus compact on-demand reuse. Use the full-replan-controlled trajectory and existing effective-change decision rule. Pair the start state, tick and forecast at every query. Check status, earliest arrival, reconstructed path feasibility and agreement of path steps and expansions. Use the existing moving comparison protocol with rotated order, one warm-up and three timed repetitions. Run timed episodes serially.

The primary endpoint is summed median native episode time including the initial solve. Also report update p95, peak process RSS, process wall time, initial and update times, per-seed and per-map results, and groups by number of post-initial certificate misses. Compare ratios of summed times inside each group. Interpret miss counts descriptively. Do not change planner settings after observing outcomes.

## Reproduction

Run from the repository root with clean output filenames. The decision files contain the realized state, tick and forecast for each query; the trial files contain the native times, process wall times, peak RSS and chosen strategy. The generated suite manifest records the per-case scenario SHA-256 digest.

```sh
python3 -m sipp_baseline generate-scenarios --output runs/final-moving \
  --seeds 1009 1013 1019 1021 1031 --densities .02 .04 --no-engineered
for seed in 1009 1013 1019 1021 1031; do
  python3 -m sipp_baseline.moving_replay runs/final-moving --seed "$seed" \
    --minimum 0 --percent 5 --suffix-fresh --output "runs/final-decisions-$seed.jsonl"
  gzip -nc "runs/final-decisions-$seed.jsonl" > "docs/final-decisions-$seed.jsonl.gz"
  python3 -m sipp_baseline.moving_compare --final --seed "$seed" --output "runs/final-trials-$seed.jsonl"
  gzip -nc "runs/final-trials-$seed.jsonl" > "docs/final-trials-$seed.jsonl.gz"
done
python3 -m sipp_baseline.final_summary
make test
```
