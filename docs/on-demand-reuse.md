# Reusing outgoing motions when fresh SIPP-IP reaches an interval

The question is whether a robot that has moved can reuse previous SIPP-IP search work cheaply enough to improve a whole episode. We kept the existing optimal-suffix check. On a certificate miss, fresh SIPP-IP starts from the robot's current configuration and tick. Once the search would expand an interval, the prototype checks for reusable outgoing motions at that configuration.

## What the cache proves

Each expansion saves its source interval and the contiguous range of children it generated, including an empty range when all actions fail. Old expansions are indexed by cell, orientation and velocity. A hit requires one old interval to contain the entire newly reached interval. The static map and horizon must match, and the normalized reservations must be unchanged on every cell touched by any outgoing primitive, including destinations. The cell check is shared across later lookups at the same configuration within the query. This conservative check can reject safe reuse when a change lies outside the relevant time window.

For each action, feasible departure times on the narrower source are precisely the old feasible departures intersected with that source. Durations and swept reservations agree. Moving children inherit the clipped arrival interval. For a stopped child, the surviving departures all arrive in the same safe interval, so its old waiting endpoint is still valid. The implementation processes children in their original order and assigns each a parent reached in the new search. An empty old output can be reused under the same checks. If any check fails, the planner projects every action normally. These rules reproduce ordinary SIPP-IP successors at each expansion, so its finite-horizon completeness and earliest-arrival guarantee carry over under the same assumptions and sufficient expansion budget. The prototype retains a single previous generation, including the child-node storage needed for lookup.

## How we made the decision

The seed-19 audit used the 102 archived episodes from all five maps. A shadow lookup ran at each fresh expansion after a certificate miss, and ordinary SIPP-IP still generated the successors. We timed lookup and validation and separately summed the ordinary outgoing-action time on hits. The latter includes work that replay must still perform, such as pushing children. The lookup timer excludes forecast differencing, allocating indices, keeping the old generation and final disposal. The first pilot ran during scenario generation and passed the screen. The archived repeat used the final code after generation finished.

For the online comparison we generated two new seeds, 31 and 37, across the same five maps, two obstacle densities and nine change patterns. We generated the executed trajectory with full SIPP-IP and triggered decisions on effective forecast changes. Both policies received the same states and forecasts. We checked each query against the full-replan status and arrival time and independently validated each returned path. A small time-expanded oracle regression covers formerly blocked actions becoming available, changed reservations, clipped domains, moving roots, changed horizons and changed maps.

For each of the 180 held-out episodes we rotated method order, dropped one warm-up and kept three trials. The episode metric sums native query times within each trial, takes the median for that episode, then sums over episodes. It includes the initial solve, cache construction, forecast differencing, replay, and disposal of replaced generations. The wall-time metric additionally includes starting the process, transmitting the query sequence, output and final process teardown. Update p95 uses the median of each post-initial query across trials and nearest rank. Peak RSS is the largest process high-water mark from GNU time. Peak memory and p95 may occur on different episodes for different policies.

## Results

The seed-19 pilot found 3,441,488 hits in 7,785,873 lookups (44.2%). Of those hits, 1,361,583 used a strictly narrower source interval. In the archived repeat, lookup took 0.54 s and the ordinary outgoing-action work on hits took 2.22 s. This passed the screening test for an online prototype.

| Seed | Policy | Summed episode time (s) | Summed process wall time (s) | p95 update (ms) | Peak RSS (MiB) |
| --- | --- | ---: | ---: | ---: | ---: |
| 31 | Suffix + fresh | 14.43 | 14.69 | 358.10 | 149.3 |
| 31 | Suffix + on-demand | 14.01 | 14.30 | 346.19 | 212.6 |
| 37 | Suffix + fresh | 15.44 | 15.71 | 318.23 | 106.2 |
| 37 | Suffix + on-demand | 14.94 | 15.24 | 301.72 | 149.9 |
| Both | Suffix + fresh | 29.88 | 30.40 | 335.15 | 149.3 |
| Both | Suffix + on-demand | 28.94 | 29.54 | 335.78 | 212.6 |

All 452 held-out decisions agreed on status and earliest arrival. Every returned path passed validation. Both policies certified 24 of 272 updates. The remaining 248 updates searched from the current state. The cache answered 6,440,452 of 14,501,864 expansion lookups (44.4%). All 180 held-out episodes reached their goals, so evidence for no-path behavior comes from the oracle cases and the seed-19 pilot.

Summing the per-query medians, initial solves increased from 12.94 s to 13.73 s and updates fell from 16.90 s to 15.21 s. Across complete episodes the gain was 3.1%. Both seeds and all three trial totals favored on-demand reuse. Pooled p95 was effectively tied and peak memory increased by 42.4%. The pooled p95 is computed from the combined latency distribution, so it can move differently from either per-seed p95.

Across the three measured repetitions the two-seed totals ranged from 28.99–29.06 s for the prototype and 29.89–30.00 s for the reference. As a sensitivity check, independently selecting the fastest or slowest observed run of each episode gives an extreme candidate/reference ratio range of 0.930–1.011. The gain is modest and its size depends on the workload and host. Two new seeds do not establish a general speedup.

## Project decision

Keep the lighter suffix-plus-fresh policy as the moving-start default and offer on-demand reuse as an experimental option for repeated updates. It saves update time, but the extra initial cost offsets nearly half that saving and the old node storage raises peak memory. A focused follow-up would store compact child records containing only the action, departure interval and stopped waiting endpoint, then rerun the same paired experiment. Use additional untouched seeds for any claim about generalization.

For a fixed start and tick, the adaptive repair result remains the stronger research finding. On the prior held-out study, its geometric mean per-case time ratio to full replanning was 0.488, with median update time 16.84 ms versus 29.13 ms. It selected full replanning when at least 5% of free cells changed, with no minimum cell count. These fixed-start ratios and the moving-start summed episode times use different denominators. [Fixed-start threshold study](threshold-study.md)

## Reproduction

From the repository root, the seed-19 pilot uses the existing `runs/diverse-scenarios` suite. Generate the held-out scenarios once. The two full-replan decision archives are included to reproduce the paired comparisons directly. To rebuild those archives use `sipp_baseline.moving_replay` with `--suffix-fresh` on the generated suite, then gzip its JSONL output.

```sh
python3 -m sipp_baseline generate-scenarios --output runs/on-demand-holdout --seeds 31 37 --densities .02 .04 --no-engineered
for seed in 19 31 37; do
  python3 -m sipp_baseline.moving_compare --on-demand --seed "$seed" --output "runs/replication-$seed.jsonl"
done
python3 -m sipp_baseline.on_demand_report
make test
```

The report command reads the archived JSONL files under `docs`. The experimental planner is available through `sipp_baseline.moving_replay --on-demand`. [Pilot measurements](on-demand-19.jsonl.gz), [seed 31 trials](on-demand-31.jsonl.gz), [seed 37 trials](on-demand-37.jsonl.gz), [seed 31 decisions](on-demand-decisions-31.jsonl.gz), [seed 37 decisions](on-demand-decisions-37.jsonl.gz).

## Compact child storage

The compact variant saves four integers per outgoing child, covering the action index, the lower and upper departure ticks, and the endpoint used for stopped waiting. The search keeps full nodes until it reconstructs the current path. It then releases the previous generation, packs only the children covered by expansion records, and remaps each record to its packed range. Empty ranges and child order are preserved. At replay, the reached source and its motion primitive determine the destination cell, orientation, velocity and duration. The new path supplies the parent. Both variants apply the same departure clipping and waiting rules.

With this build, a packed child occupies 16 bytes and a full node occupies 40 bytes. Total process memory also includes the in-progress search, expansion index, reservations and the temporary overlap during packing. The three-way comparison measures that high-water mark using the same episode protocol as above. Seeds 31 and 37 are reused for a paired storage experiment. All three methods run anew in rotating order, with one warm-up and three measured trials. Every trial checks path steps and expansion counts across all three methods, and probe, hit and clipped-hit counts across the two caches.

| Seed | Policy | Summed episode time (s) | Summed process wall time (s) | p95 update (ms) | Peak RSS (MiB) |
| --- | --- | ---: | ---: | ---: | ---: |
| 31 | Suffix + fresh | 14.41 | 14.66 | 350.6 | 149.6 |
| 31 | Full-node cache | 14.09 | 14.38 | 342.0 | 212.4 |
| 31 | Compact cache | 14.05 | 14.32 | 343.8 | 185.6 |
| 37 | Suffix + fresh | 15.46 | 15.73 | 317.3 | 106.1 |
| 37 | Full-node cache | 14.77 | 15.07 | 291.5 | 149.6 |
| 37 | Compact cache | 14.86 | 15.15 | 288.2 | 139.0 |
| Both | Suffix + fresh | 29.87 | 30.40 | 335.5 | 149.6 |
| Both | Full-node cache | 28.87 | 29.45 | 333.8 | 212.4 |
| Both | Compact cache | 28.91 | 29.48 | 338.5 | 185.6 |

Across 180 episodes and 452 decisions, all returned paths were feasible and all statuses and arrival times matched the archived reference. Both caches made the same 6,440,452 hits on 14,501,864 probes. The compact cache reduced peak process memory by 26.9 MiB (12.6%) relative to the full-node cache. Its summed episode time increased by 0.04 s (0.14%). The direction of that small timing difference changed between seeds and the trial totals overlapped.

Relative to suffix-plus-fresh, compact reuse reduced summed episode time by 3.2%, used 24.0% more peak memory and had a slightly higher pooled p95. For these maps and update patterns, compact storage is the preferred representation when enabling on-demand reuse. Suffix-plus-fresh remains the lower-memory option. This repeat on the same seeds isolates the representation change and gives no additional evidence about generalization to new worlds.

To use the compact variant, run the moving replay with `--compact`. To repeat the comparison with the existing scenario directory and decision archives:

```sh
for seed in 31 37; do
  python3 -m sipp_baseline.moving_compare --compact --seed "$seed" --output "runs/compact-replication-$seed.jsonl"
done
python3 -m sipp_baseline.on_demand_report --compact
```

The summary command reads the archived [seed 31 trials](compact-cache-31.jsonl.gz) and [seed 37 trials](compact-cache-37.jsonl.gz).
